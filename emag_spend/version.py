"""Versiunea programului: sursa unică (decis 5 oct. 2026, D1) și compararea versiunilor X.Y.Z.

Ce conține: VERSION (eticheta git a lansării trebuie să fie exact "v" + VERSION; lansare.yml pică altfel),
parse_version (text → (X, Y, Z) sau None) și is_newer (candidatul e strict mai nou decât versiunea curentă?).
Ce NU face: nu citește rețeaua, nu știe de GitHub și nu decide dacă se instalează ceva (asta e treaba
lui update_check.py și update_apply.py).
"""

import re

VERSION = "1.0.1"

# Cifre ASCII explicite ([0-9], nu \d, care acceptă și cifre din alte alfabete) și fără zerouri în față (ca la semver:
# „01.2.3” nu e o versiune). Plafonul de cifre oprește numere uriașe venite dintr-un răspuns străin: versiunile reale
# ale programului au cel mult câteva cifre pe componentă, iar 6 lasă loc cu o marjă imensă.
MAX_VERSION_PART_DIGITS = 6
_PART = rf"(0|[1-9][0-9]{{0,{MAX_VERSION_PART_DIGITS - 1}}})"
_VERSION_PATTERN = re.compile(rf"v?{_PART}\.{_PART}\.{_PART}")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """(X, Y, Z) pentru „X.Y.Z” sau „vX.Y.Z”, exact (fără spații, sufixe sau zerouri în față); altfel None, fără excepții."""
    if not isinstance(text, str):
        return None
    match = _VERSION_PATTERN.fullmatch(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def is_newer(candidate: str, current: str) -> bool:
    """True dacă `candidate` e strict mai nouă decât `current`; False la egalitate, la versiune mai veche sau dacă oricare nu se parsează."""
    parsed_candidate, parsed_current = parse_version(candidate), parse_version(current)
    if parsed_candidate is None or parsed_current is None:
        return False
    return parsed_candidate > parsed_current
