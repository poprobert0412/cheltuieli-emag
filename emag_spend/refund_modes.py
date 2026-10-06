"""Modul de restituire al unui retur finalizat: bani înapoi (se scad din cheltuieli) sau credit eMAG (nu se scad).

Primește: config/restituiri.json, cu listele `bani_inapoi` și `credit_emag` (textele de la „Modalitate restituire”).
Dă înapoi: `RefundModes`, care spune despre un mod dacă e credit (voucher, sold) și dacă e cunoscut.
De ce: un voucher restituit se folosește apoi ca reducere în altă comandă și scade deja „Total platit” al acelei comenzi;
scăzut și la retur, aceiași bani s-ar scădea de două ori. „Generare sold” (sold eMAG) e credit, ca voucherul: decis de
Robert pe 5 oct. 2026. Un mod necunoscut se tratează ca bani înapoi (cazul obișnuit),
iar analiza scrie un avertisment. Ce NU face: nu citește retururi și nu calculează sume (paid_totals.py).
"""

from dataclasses import dataclass
from pathlib import Path

from emag_spend import settings
from emag_spend.json_file import read_json
from emag_spend.text_normalize import normalize_text

REFUND_MODES_FILE = settings.PROJECT_ROOT / "config" / "restituiri.json"
_LIST_KEYS = ("bani_inapoi", "credit_emag")


@dataclass(frozen=True)
class RefundModes:
    """Modurile cunoscute, normalizate (fără diacritice, litere mici)."""

    cash: frozenset[str]
    credit: frozenset[str]

    def is_credit(self, mode: str | None) -> bool:
        """True dacă restituirea a fost voucher sau sold eMAG (banii nu s-au întors în cont)."""
        return normalize_text(mode or "") in self.credit

    def is_known(self, mode: str | None) -> bool:
        """True dacă modul e într-una dintre liste (altfel se tratează ca bani înapoi, cu avertisment)."""
        normalized = normalize_text(mode or "")
        return normalized in self.cash or normalized in self.credit


def load_refund_modes(path: Path = REFUND_MODES_FILE) -> RefundModes:
    """Citește config/restituiri.json; ValueError (cu fișierul) la o listă lipsă, un text gol sau un mod în ambele liste."""
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: trebuie să fie un obiect cu listele {', '.join(repr(k) for k in _LIST_KEYS)}")
    lists = {}
    for key in _LIST_KEYS:
        values = data.get(key)
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f"{path}: '{key}' trebuie să fie o listă de texte nevide")
        lists[key] = frozenset(normalize_text(v) for v in values)
    both = sorted(lists["bani_inapoi"] & lists["credit_emag"])
    if both:
        raise ValueError(f"{path}: un mod nu poate fi și „bani_inapoi”, și „credit_emag”: {both}")
    return RefundModes(cash=lists["bani_inapoi"], credit=lists["credit_emag"])
