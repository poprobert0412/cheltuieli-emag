"""Citirea datelor scrise românește de eMAG ("26 mai 2026, 10:07").

Primește: text cu o dată. Dă înapoi: ISO "2026-05-26T10:07" sau None.
Lunile se recunosc după primele 3 litere (fără diacritice), deci merg și
formele scurte din liste ("ian", "noi") și cele întregi din detalii
("ianuarie", "noiembrie").
"""

import re

from emag_spend.text_normalize import normalize_text

_MONTHS = {
    "ian": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "iun": 6,
    "iul": 7, "aug": 8, "sep": 9, "oct": 10, "noi": 11, "dec": 12,
}
_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-zăâîșțşţĂÂÎȘȚ]+)\.?\s+(\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?"
)


def parse_ro_datetime(text: str) -> str | None:
    """Întoarce data ca ISO "YYYY-MM-DDTHH:MM" (ora 00:00 dacă lipsește)."""
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    day, month_name, year, hour, minute = match.groups()
    month = _MONTHS.get(normalize_text(month_name)[:3])
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}T{int(hour or 0):02d}:{int(minute or 0):02d}"
