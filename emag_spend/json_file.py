"""Citește un fișier JSON editabil de utilizator, cu mesaje de eroare care spun CE fișier e greșit.

Primește: calea unui fișier JSON (config/categorii.json, comenzi.json, retururi.json).
Dă înapoi: conținutul parsat. Ridică ValueError cu calea fișierului, linia și coloana
unde s-a rupt, ca utilizatorul să știe ce deschide și unde.
Acceptă și fișiere salvate cu BOM (Notepad pe Windows le scrie așa).
Ce NU face: nu verifică forma conținutului (asta e treaba apelantului) și nu scrie fișiere.
"""

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Conținutul JSON al fișierului; ValueError cu calea, linia și coloana dacă nu se poate citi."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")  # utf-8-sig: BOM-ul de la început nu mai strică parsarea
    except UnicodeDecodeError as error:
        raise ValueError(f"{path}: nu e text UTF-8 valid (salvează fișierul ca UTF-8)") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: JSON invalid la linia {error.lineno}, coloana {error.colno}: {error.msg}") from error
