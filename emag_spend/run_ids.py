"""Numele folderului unei rulări (`<data>_<ora>` sau `<data>_<ora>_demo`): cum se face și cum se recunoaște.

Primește: momentul rulării și dacă e demonstrație, sau un text de verificat. Dă înapoi: numele (id-ul rulării) și,
la verificare, momentul și tipul lui (ParsedRunId) sau None. Același nume e folderul din iesiri/ și id-ul din API-ul
aplicației locale, deci formatul stă într-un singur loc: run_pipeline îl face, app_security și app_runs îl verifică,
app_runner alege id-ul înainte ca rularea să pornească.
Ce NU face: nu creează foldere și nu citește discul.
"""

import re
from dataclasses import dataclass
from datetime import datetime

RUN_ID_TIME_FORMAT = "%Y-%m-%d_%H-%M-%S"
DEMO_SUFFIX = "_demo"
# Clase ASCII explicite ([0-9], nu \d: \d primește și cifre din alte alfabete) și fullmatch: id-ul ajunge în calea unui folder,
# deci nu poate conține nimic în afară de cifre, cratime, liniuță jos și sufixul demo (nici „..”, nici separatori de cale).
_RUN_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}(?:_demo)?")


@dataclass(frozen=True)
class ParsedRunId:
    """Ce se află dintr-un id valid: momentul din nume (ora locală a calculatorului) și dacă e rulare demonstrativă."""

    moment: datetime
    demo: bool


def new_run_id(moment: datetime, demo: bool) -> str:
    """Id-ul (numele folderului) pentru o rulare începută la `moment`; cele demo primesc sufixul `_demo`."""
    return f"{moment.strftime(RUN_ID_TIME_FORMAT)}{DEMO_SUFFIX if demo else ''}"


def parse_run_id(text: object) -> ParsedRunId | None:
    """Momentul și tipul din `text`, sau None dacă nu e exact un id de rulare (formă greșită sau dată care nu există).

    Primește orice obiect (valoarea vine din cale sau din JSON) și nu ridică excepții.
    """
    if not isinstance(text, str) or not _RUN_ID_PATTERN.fullmatch(text):
        return None
    demo = text.endswith(DEMO_SUFFIX)
    stamp = text[: -len(DEMO_SUFFIX)] if demo else text
    try:
        return ParsedRunId(datetime.strptime(stamp, RUN_ID_TIME_FORMAT), demo)
    except ValueError:  # ex. luna 13 sau 31 februarie: forma e bună, data nu există
        return None
