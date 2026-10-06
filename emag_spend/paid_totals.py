"""Banii plătiți efectiv: cifra principală a raportului, lanțul în bani plătiți și rândurile care nu sunt produse.

Primește: comenzile, registrul de linii (cu `paid_total_bani` de la line_ledger.py și retururile aplicate de return_matcher.py),
retururile, raportul potrivirii și modurile de restituire (refund_modes.py). Completează pe linii `credit_returned_qty`.
Dă înapoi: `PaidTotals` = cheia `paid` din analiza.json + sumele pe ani + avertismentele (moduri de restituire necunoscute).
Reguli:
- plătit efectiv = „Total platit” al blocurilor livrate/ridicate − banii primiți înapoi la retururile lor
  + partea plătită a produselor returnate cu voucher sau sold din blocuri marcate „anulat” (marketplace);
- retur cu bani înapoi: se scade suma restituită afișată; fără sumă, cu produse nepotrivite sau întins pe blocuri cu stări
  diferite, se scade partea plătită a produselor (estimare, numărată separat); la un bloc marcat „anulat”, plata și
  restituirea se anulează reciproc și nu intră în calcul;
- retur cu voucher sau sold: nu se scade nimic, fiindcă voucherul scade deja „Total platit” al comenzii în care e folosit;
- transportul și taxele blocurilor livrate rămân rând separat; blocurile anulate, în curs, cu status necunoscut și cele
  plătite fără livrare nu intră în plătit efectiv (apar la „în afara calculului”).
Invariant verificat: produse păstrate + transport și taxe + retururi cu credit + diferențe la restituiri = plătit efectiv.
Ce NU face: nu citește fișiere, nu grupează pe categorii (spend_analysis.py) și nu scrie text (summary_text.py).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from emag_spend import block_status, warning_messages
from emag_spend.block_payment import PAID_FROM_COMPONENTS, block_payment
from emag_spend.models import LineOutcome, Order, ReturnRequest
from emag_spend.proportional_split import split_proportionally
from emag_spend.refund_modes import RefundModes
from emag_spend.return_matcher import ReturnMatchReport

# Rândurile care nu sunt produse: apar după categorii și ca serii în graficul pe ani, ca suma lor să fie plătitul efectiv.
EXTRA_FEES = "fees"
EXTRA_CREDIT_RETURNS = "credit_returns"
EXTRA_REFUND_DIFFERENCES = "refund_differences"
EXTRA_ROW_NAMES = {
    EXTRA_FEES: "Transport și taxe",
    EXTRA_CREDIT_RETURNS: "Retururi cu voucher sau sold eMAG",
    EXTRA_REFUND_DIFFERENCES: "Diferențe la restituiri",
}
UNKNOWN_YEAR = "necunoscut"


def year_of(placed_at: str | None) -> str:
    """Anul din data ISO a comenzii, sau "necunoscut" (aceeași regulă ca în spend_analysis.py)."""
    return placed_at[:4] if placed_at else UNKNOWN_YEAR


@dataclass
class _ReturnPart:
    """Unitățile unui retur pe o linie: câte sunt și partea lor plătită (împărțită exact între retururile liniei)."""

    line: LineOutcome
    units: int
    paid_bani: int


@dataclass
class _Year:
    """Sumele unui an; între ele: ordered − cancelled − returned − pending − unknown + fees = spent."""

    ordered_bani: int = 0
    cancelled_bani: int = 0
    returned_bani: int = 0
    pending_bani: int = 0
    unknown_bani: int = 0
    fees_bani: int = 0
    kept_bani: int = 0
    credit_bani: int = 0
    differences_bani: int = 0

    @property
    def spent_bani(self) -> int:
        """Plătit efectiv în acest an: produse păstrate + transport și taxe + retururi cu credit + diferențe."""
        return self.kept_bani + self.fees_bani + self.credit_bani + self.differences_bani


@dataclass
class PaidTotals:
    """Rezultatul: `summary` (cheia `paid` din analiza.json), sumele pe ani și avertismentele găsite."""

    summary: dict
    by_year: dict[str, _Year]
    warnings: list[str] = field(default_factory=list)

    def extra_values(self, key: str) -> dict[str, int]:
        """Valoarea pe ani a unui rând care nu e produs (EXTRA_*)."""
        attribute = {EXTRA_FEES: "fees_bani", EXTRA_CREDIT_RETURNS: "credit_bani", EXTRA_REFUND_DIFFERENCES: "differences_bani"}[key]
        return {year: getattr(values, attribute) for year, values in self.by_year.items()}


def mark_credit_returns(lines: list[LineOutcome], returns: list[ReturnRequest], modes: RefundModes) -> None:
    """Completează `credit_returned_qty` pe fiecare linie: unitățile ei returnate cu voucher sau sold eMAG."""
    credit_ids = {r.return_id for r in returns if modes.is_credit(r.refund_mode)}
    for line in lines:
        line.credit_returned_qty = sum(1 for return_id in line.return_ids if return_id in credit_ids)


def _return_parts(lines: list[LineOutcome]) -> dict[str, list[_ReturnPart]]:
    """Pentru fiecare retur, liniile lui; pe o linie, partea plătită a returnatului se împarte exact între retururi."""
    parts: dict[str, list[_ReturnPart]] = defaultdict(list)
    for line in lines:
        if not line.return_ids:
            continue
        counts = Counter(line.return_ids)
        ids = list(counts)
        for return_id, share in zip(ids, split_proportionally(line.returned_paid_bani, [counts[i] for i in ids])):
            parts[return_id].append(_ReturnPart(line, counts[return_id], share))
    return parts


def compute_paid_totals(
    orders: list[Order],
    lines: list[LineOutcome],
    returns: list[ReturnRequest],
    match_report: ReturnMatchReport,
    modes: RefundModes,
) -> PaidTotals:
    """Calculează cheia `paid` (vezi antetul modulului pentru reguli). `lines` trebuie să aibă retururile deja aplicate."""
    mark_credit_returns(lines, returns, modes)
    years: dict[str, _Year] = defaultdict(_Year)
    warnings: list[str] = []
    for ret in returns:
        if ret.completed and not modes.is_known(ret.refund_mode):
            warnings.append(warning_messages.format_unknown_refund_mode(ret.return_id, ret.refund_mode))

    # ---- produsele, pe stări (în bani plătiți) ----
    priced = [line for line in lines if line.paid_only_qty == 0]
    units = Counter()
    list_kept = 0
    for line in priced:
        year = years[year_of(line.placed_at)]
        year.ordered_bani += line.paid_value_bani
        year.cancelled_bani += line.cancelled_paid_bani
        year.pending_bani += line.pending_paid_bani
        year.unknown_bani += line.unknown_paid_bani
        year.kept_bani += line.kept_paid_bani
        list_kept += line.kept_list_bani
        units.update(ordered=line.qty, cancelled=line.cancelled_qty, pending=line.pending_qty, unknown=line.unknown_qty,
                     kept=line.kept_qty, returned=line.returned_qty - line.credit_returned_qty, credit=line.credit_returned_qty)

    # ---- blocurile: transportul și taxele celor livrate, sumele celor rămase în afara calculului ----
    paid_delivered = rebuilt_bani = rebuilt_blocks = 0
    outside = Counter()
    for order in orders:
        for block in order.blocks:
            payment = block_payment(block)
            if block.status == block_status.DELIVERED:
                paid_delivered += payment.paid_bani
                years[year_of(order.placed_at)].fees_bani += payment.fees_bani
                if payment.source == PAID_FROM_COMPONENTS:
                    rebuilt_blocks += 1
                    rebuilt_bani += payment.paid_bani
            elif block.status == block_status.IN_PROGRESS:
                outside["in_progress_bani"] += payment.paid_bani
            elif block.status == block_status.PAID_ONLY:
                outside["paid_only_bani"] += payment.paid_bani
            elif block.status == block_status.UNKNOWN:
                outside["unknown_bani"] += payment.paid_bani

    # ---- retururile: bani înapoi (scădeți) sau credit (rămân cheltuiți) ----
    by_id = {r.return_id: r for r in returns}
    partial = set(match_report.partially_matched_return_ids)
    refunds = Counter()
    for return_id, parts in _return_parts(lines).items():
        ret = by_id.get(return_id)
        delivered = [p for p in parts if p.line.block_status == block_status.DELIVERED]
        elsewhere = [p for p in parts if p.line.block_status != block_status.DELIVERED]
        on_delivered = sum(p.paid_bani for p in delivered)
        on_elsewhere = sum(p.paid_bani for p in elsewhere)
        if ret is not None and modes.is_credit(ret.refund_mode):
            for part in parts:  # banii n-au revenit în cont: rămân cheltuiți, pe anul comenzii
                years[year_of(part.line.placed_at)].credit_bani += part.paid_bani
            refunds["credit_on_delivered_bani"] += on_delivered
            refunds["credit_added_bani"] += on_elsewhere
            continue
        for part in elsewhere:  # bloc marcat „anulat”: plata și restituirea se anulează reciproc
            years[year_of(part.line.placed_at)].returned_bani += part.paid_bani
        refunds["cancelled_cash_bani"] += on_elsewhere
        shown = ret.refund_bani if ret is not None else None
        if not delivered:
            if shown is not None:
                refunds["cancelled_cash_shown_bani"] += shown
            continue
        exact = shown is not None and not elsewhere and return_id not in partial
        attributed = shown if exact else on_delivered
        # suma restituită se împarte pe liniile returului proporțional cu partea lor plătită, ca fiecare an să se închidă exact
        weights = [p.paid_bani for p in delivered]
        shares = split_proportionally(attributed, weights) if sum(weights) else [attributed] + [0] * (len(delivered) - 1)
        for part, share in zip(delivered, shares):
            year = years[year_of(part.line.placed_at)]
            year.returned_bani += share
            year.differences_bani += part.paid_bani - share
        refunds["cash_bani"] += attributed
        if not exact:
            refunds["estimated_bani"] += on_delivered
            refunds["estimated_returns"] += 1
            if shown is not None:  # suma afișată acoperă și produse nepotrivite sau din alt bloc: rămâne neatribuită
                refunds["unattributed_bani"] += shown - on_delivered - on_elsewhere

    # ---- totaluri și verificarea lanțului ----
    total = _Year()
    for values in years.values():
        for name in total.__dataclass_fields__:
            setattr(total, name, getattr(total, name) + getattr(values, name))
    spent_by_chain = (total.ordered_bani - total.cancelled_bani - total.returned_bani - total.pending_bani - total.unknown_bani
                      + total.fees_bani)
    if spent_by_chain != total.spent_bani:
        warnings.append(warning_messages.format_paid_not_closing(warning_messages.PAID_CHECK_CHAIN, spent_by_chain, total.spent_bani))
    spent_by_blocks = paid_delivered - refunds["cash_bani"] + refunds["credit_added_bani"]
    if spent_by_blocks != total.spent_bani:
        warnings.append(warning_messages.format_paid_not_closing(warning_messages.PAID_CHECK_BLOCKS, spent_by_blocks, total.spent_bani))

    extra_rows = [
        {"key": key, "name": EXTRA_ROW_NAMES[key], "bani": bani}
        for key, bani in ((EXTRA_FEES, total.fees_bani), (EXTRA_CREDIT_RETURNS, total.credit_bani),
                          (EXTRA_REFUND_DIFFERENCES, total.differences_bani))
        if bani
    ]
    summary = {
        "spent_bani": total.spent_bani,
        "spent_units": units["kept"],
        "list_kept_bani": list_kept,
        "discounts_kept_bani": list_kept - total.kept_bani,
        "products_kept_bani": total.kept_bani,
        "fees_bani": total.fees_bani,
        "credit_returns_bani": total.credit_bani,
        "credit_returns_units": units["credit"],
        "refund_differences_bani": total.differences_bani,
        "extra_rows": extra_rows,
        "funnel": {
            "ordered_bani": total.ordered_bani, "cancelled_bani": total.cancelled_bani, "returned_bani": total.returned_bani,
            "pending_bani": total.pending_bani, "unknown_bani": total.unknown_bani, "fees_bani": total.fees_bani,
            "spent_bani": total.spent_bani,
            "ordered_units": units["ordered"], "cancelled_units": units["cancelled"], "returned_units": units["returned"],
            "credit_units": units["credit"], "pending_units": units["pending"], "unknown_units": units["unknown"],
            "spent_units": units["kept"],
        },
        "reconciliation": {
            "paid_delivered_bani": paid_delivered,
            "rebuilt_blocks": rebuilt_blocks,
            "rebuilt_bani": rebuilt_bani,
            "cash_refunds_bani": refunds["cash_bani"],
            "estimated_refunds_bani": refunds["estimated_bani"],
            "estimated_refunds": refunds["estimated_returns"],
            "credit_returns_delivered_bani": refunds["credit_on_delivered_bani"],
            "credit_returns_added_bani": refunds["credit_added_bani"],
            "refund_differences_bani": total.differences_bani,
            "spent_bani": total.spent_bani,
            "in_progress_bani": outside["in_progress_bani"],
            "paid_only_bani": outside["paid_only_bani"],
            "unknown_bani": outside["unknown_bani"],
            "cancelled_cash_returns_bani": refunds["cancelled_cash_bani"],
            "cancelled_cash_refunds_shown_bani": refunds["cancelled_cash_shown_bani"],
            "unattributed_refunds_bani": refunds["unattributed_bani"] + match_report.unmatched_refund_bani,
        },
    }
    return PaidTotals(summary=summary, by_year=dict(years), warnings=warnings)
