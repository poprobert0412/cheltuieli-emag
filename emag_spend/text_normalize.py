"""Normalizarea textului pentru comparații: fără diacritice, litere mici,
spații unice.

Primește: orice text. Dă înapoi: textul normalizat. Folosit la potrivirea
numelor de produse (comandă vs. retur) și la regulile de categorii.
"""

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Scoate diacriticele, trece la litere mici și unifică spațiile.

    "Ţelină  Șampon" -> "telina sampon". Nu scoate punctuația.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", without_marks).strip().casefold()
