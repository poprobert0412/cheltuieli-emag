"""Potrivește retururile finalizate cu produsele din comenzi.

Primește: registrul de linii și lista de retururi. Modifică liniile pe loc:
o unitate "păstrată" devine "returnată". Dă înapoi avertismentele și
statistici (câte potriviri, ce n-a găsit loc).
Reguli:
- doar retururile finalizate (cu pasul "Restituire suma") scad din total;
  cele anulate sau fără rezultat lasă produsul păstrat;
- numele din retur se caută în produsele comenzii (identic sau prefix al unui
  nume trunchiat "[...]" de eMAG, apoi aproximativ ≥ 0.88 doar dacă nu există
  potrivire identică);
- la marketplace, eMAG marchează produsul returnat "Livrare anulata": o
  unitate "anulată" găsită în retur devine "returnată", ca să nu fie numărată
  ca anulare și nici scăzută a doua oară.
"""

import difflib
import logging
import re
from dataclasses import dataclass, field

from emag_spend.models import LineOutcome, ReturnRequest
from emag_spend.text_normalize import normalize_text

logger = logging.getLogger(__name__)

# Sub acest scor un nume de produs din retur NU se consideră același produs.
FUZZY_MATCH_MIN_RATIO = 0.88


@dataclass
class ReturnMatchReport:
    """Rezultatul potrivirii retururilor."""

    matched_units: int = 0
    matched_from_cancelled_units: int = 0
    warnings: list[str] = field(default_factory=list)
    unmatched_refund_bani: int = 0  # restituiri fără produs potrivit


_TRUNCATION_MARKER = re.compile(r"\s*(?:\[\.\.\.\]|\.\.\.|…)\s*$")
# Un nume trunchiat de eMAG ("... [...]") se potrivește cu numele întreg doar dacă prefixul e destul de lung.
MIN_TRUNCATED_PREFIX = 30


def _matches_exactly(line_name: str, norm_name: str) -> bool:
    """Nume identic, sau nume trunchiat de eMAG care e prefixul numelui din retur."""
    normalized = normalize_text(line_name)
    if normalized == norm_name:
        return True
    if _TRUNCATION_MARKER.search(normalized):
        prefix = _TRUNCATION_MARKER.sub("", normalized).rstrip(" ,")
        return len(prefix) >= MIN_TRUNCATED_PREFIX and norm_name.startswith(prefix)
    return False


def _pick_line(pool: list[LineOutcome], norm_name: str) -> tuple[LineOutcome | None, str]:
    """Linia care corespunde numelui: prefer una cu unități păstrate, apoi una anulată.

    Întoarce (linie, "kept" | "cancelled") sau (None, "").
    """
    exact = [line for line in pool if _matches_exactly(line.name, norm_name)]
    candidates = exact
    if not candidates:
        names = {normalize_text(line.name) for line in pool}
        close = difflib.get_close_matches(norm_name, list(names), n=1, cutoff=FUZZY_MATCH_MIN_RATIO)
        candidates = [line for line in pool if close and normalize_text(line.name) == close[0]]
    for line in candidates:
        if line.kept_qty > 0:
            return line, "kept"
    for line in candidates:
        if line.cancelled_qty > 0:
            return line, "cancelled"
    return None, ""


def apply_returns(lines: list[LineOutcome], returns: list[ReturnRequest]) -> ReturnMatchReport:
    """Aplică retururile finalizate pe liniile registrului (modifică `lines`)."""
    report = ReturnMatchReport()
    by_order: dict[str, list[LineOutcome]] = {}
    for line in lines:
        by_order.setdefault(line.order_id, []).append(line)

    for ret in returns:
        if not ret.completed:
            continue
        label = f"retur {ret.return_id}"
        if not ret.order_ids:
            report.warnings.append(f"{label}: nu are nicio comandă asociată")
            report.unmatched_refund_bani += ret.refund_bani or 0
            continue
        pool = [line for order_id in ret.order_ids for line in by_order.get(order_id, [])]
        if not pool:
            report.warnings.append(f"{label}: comanda {', '.join(ret.order_ids)} nu e în lista citită")
            report.unmatched_refund_bani += ret.refund_bani or 0
            continue
        if not ret.product_names:
            report.warnings.append(f"{label}: nu are produse listate")
        unmatched_here = 0
        for product_name in ret.product_names:
            line, source = _pick_line(pool, normalize_text(product_name))
            if line is None:
                unmatched_here += 1
                report.warnings.append(f"{label}: produsul {product_name!r} nu are potrivire în comanda {ret.order_ids}")
                continue
            if source == "kept":
                line.kept_qty -= 1
            else:
                line.cancelled_qty -= 1
                line.returned_from_cancelled_qty += 1
                report.matched_from_cancelled_units += 1
            line.returned_qty += 1
            line.return_ids.append(ret.return_id)
            report.matched_units += 1
        if unmatched_here and unmatched_here == len(ret.product_names):
            report.unmatched_refund_bani += ret.refund_bani or 0
    logger.info(
        "retururi aplicate: %d unități (din care %d marcate 'anulat' de eMAG), %d avertismente",
        report.matched_units, report.matched_from_cancelled_units, len(report.warnings),
    )
    return report
