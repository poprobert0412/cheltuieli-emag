"""Salvează și reîncarcă datele colectate (comenzi, retururi) în JSON.

Primește: folderul unei rulări și listele de obiecte. Dă înapoi: listele
reconstruite. Cu datele salvate, raportul se poate reface fără browser
(`--din-cache`). Se salvează doar datele parsate, fără date personale.
Un fișier editat de mână sau salvat de altă versiune a programului nu dă
traceback: `load_run` ridică ValueError cu fișierul și poziția greșelii.
"""

import json
from pathlib import Path
from typing import Callable, TypeVar

from emag_spend.json_file import read_json
from emag_spend.models import Order, ReturnRequest, order_from_dict, return_from_dict, to_dict

ORDERS_FILE = "comenzi.json"
RETURNS_FILE = "retururi.json"

T = TypeVar("T")


def _write_json(path: Path, data) -> None:
    """Scrie `data` ca JSON UTF-8 indentat, creând folderul dacă lipsește."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def save_orders(folder: Path, orders: list[Order]) -> Path:
    """Scrie comenzile în `<folder>/comenzi.json`."""
    path = folder / ORDERS_FILE
    _write_json(path, [to_dict(o) for o in orders])
    return path


def save_returns(folder: Path, returns: list[ReturnRequest]) -> Path:
    """Scrie retururile în `<folder>/retururi.json`."""
    path = folder / RETURNS_FILE
    _write_json(path, [to_dict(r) for r in returns])
    return path


def save_json(folder: Path, name: str, data) -> Path:
    """Scrie un dicționar/listă oarecare în `<folder>/<name>`."""
    path = folder / name
    _write_json(path, data)
    return path


def _load_records(path: Path, build: Callable[[dict], T], noun: str) -> list[T]:
    """Citește lista din `path` și reconstruiește fiecare înregistrare cu `build`.

    Orice formă neașteptată (cheie lipsă sau în plus, tip greșit) devine ValueError cu
    fișierul și numărul înregistrării, nu KeyError/TypeError din interiorul modelelor.
    """
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{path}: trebuie să conțină o listă de {noun}, nu {type(data).__name__}")
    records = []
    for index, entry in enumerate(data, start=1):
        try:
            records.append(build(entry))
        except (KeyError, TypeError) as error:
            detail = f"lipsește cheia {error}" if isinstance(error, KeyError) else str(error)
            raise ValueError(
                f"{path}, {noun} nr. {index}: nu are forma așteptată ({detail}); "
                "fișier editat de mână sau salvat de o altă versiune a programului?"
            ) from error
    return records


def load_run(folder: Path) -> tuple[list[Order], list[ReturnRequest]]:
    """Încarcă comenzile și retururile dintr-un folder de rulare salvat.

    Ridică FileNotFoundError cu mesaj clar dacă lipsește vreun fișier și ValueError
    (cu fișierul și poziția) dacă un fișier nu are forma salvată de `save_orders` / `save_returns`.
    """
    orders_path, returns_path = folder / ORDERS_FILE, folder / RETURNS_FILE
    for path in (orders_path, returns_path):
        if not path.exists():
            raise FileNotFoundError(f"lipsește {path} (nu e un folder de rulare complet)")
    orders = _load_records(orders_path, order_from_dict, "comanda")
    returns = _load_records(returns_path, return_from_dict, "returul")
    return orders, returns
