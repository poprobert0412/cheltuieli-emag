"""Adresele paginilor unei comenzi sau ale unui retur pe eMAG, construite doar din numere validate.

Primește: numărul comenzii (text) sau numărul returului împreună cu calea lui din cont.
Dă înapoi: adresa https către pagina din contul utilizatorului, sau None dacă numărul nu arată
ca un număr real. Validarea e STRICTĂ: analiza.json poate veni din orice sursă, iar un număr
ciudat (litere, gol, "..", "/") nu are voie să producă niciodată un link.
Constantele de mai jos sunt cele pe care le repetă dashboard.js (un test verifică paritatea).
Ce NU face: nu deschide adrese, nu cere nimic din rețea, nu citește pagini.
"""

import re

from emag_spend import settings

# Numerele de comandă eMAG sunt doar cifre. 3–15 cifre: destul cât să acopere orice număr real
# (și pe cele scurte din date inventate), prea puțin ca să încapă text, "../" sau o cale în el.
ORDER_ID_PATTERN = r"[0-9]{3,15}"
# Clase ASCII explicite ([0-9], nu \d): \d acceptă și cifre din alte alfabete, iar acelea nu
# trebuie să ajungă într-o adresă.
_ORDER_ID = re.compile(ORDER_ID_PATTERN)

# Adresa comenzii: baza și calea vin din settings.py (o singură sursă pentru căile eMAG).
ORDER_URL_PREFIX = settings.BASE_URL + settings.ORDER_DETAIL_PATH.format(order_id="")

# Pagina unui retur are forma reală "/user/return-history/<x>/<număr retur>" (cea pe care o
# colectează return_list_scraper.py); doar numărul returului NU ajunge pentru adresă, de aceea
# adresa se construiește din calea salvată în ReturnRequest.detail_path, după aceeași validare.
_RETURN_PATH = re.compile(rf"{re.escape(settings.RETURN_LIST_PATH)}/([0-9]{{1,15}})/({ORDER_ID_PATTERN})")


def is_valid_order_id(order_id: object) -> bool:
    """True dacă `order_id` e un text format doar din 3–15 cifre ASCII."""
    return isinstance(order_id, str) and _ORDER_ID.fullmatch(order_id) is not None


def order_url(order_id: object) -> str | None:
    """Adresa paginii comenzii pe eMAG, sau None dacă numărul nu e valid (fără parametri în adresă)."""
    if not is_valid_order_id(order_id):
        return None
    return ORDER_URL_PREFIX + order_id


def return_url(return_id: object, detail_path: object = None) -> str | None:
    """Adresa returului pe eMAG, din calea lui salvată (`detail_path`), sau None dacă numărul sau calea nu sunt valide.

    Numărul singur nu ajunge: adresa reală are un segment în plus, iar una ghicită ar duce la altă pagină.
    """
    if not is_valid_order_id(return_id) or not isinstance(detail_path, str):
        return None
    match = _RETURN_PATH.fullmatch(detail_path)
    if match is None or match.group(2) != return_id:
        return None
    return settings.BASE_URL + detail_path
