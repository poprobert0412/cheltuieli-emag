"""Citirea și afișarea sumelor în lei, în format românesc.

Primește: text ("1.449,27 Lei", "-34,00 Lei", "93.59 RON", "GRATUIT").
Dă înapoi: sume întregi în BANI (int), ca să nu apară erori de rotunjire
la adunări. Nu face altceva (nu știe de comenzi sau retururi).
"""

import re

# Suma în format românesc: puncte pentru mii, virgulă pentru zecimale.
_RO_AMOUNT = r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}"
_RO_AMOUNT_FULL = re.compile(rf"^({_RO_AMOUNT})\s*(?:Lei|lei|RON)?$")
_RO_AMOUNT_ANY = re.compile(rf"({_RO_AMOUNT})\s*(?:Lei|lei|RON)")


def ro_amount_to_bani(text: str) -> int:
    """Transformă "1.449,27" sau "-34,00" în bani (144927 / -3400)."""
    cleaned = text.strip().replace(".", "").replace(",", ".")
    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:]
    whole, _, frac = cleaned.partition(".")
    bani = int(whole or "0") * 100 + int((frac + "00")[:2])
    return -bani if negative else bani


def parse_full_amount(text: str) -> int | None:
    """Suma, dacă TOT textul este o sumă ("105,99 Lei"); altfel None."""
    match = _RO_AMOUNT_FULL.match(text.strip())
    return ro_amount_to_bani(match.group(1)) if match else None


def find_amount(text: str) -> int | None:
    """Prima sumă urmată de "Lei" găsită oriunde în text; altfel None."""
    match = _RO_AMOUNT_ANY.search(text)
    return ro_amount_to_bani(match.group(1)) if match else None


def find_last_amount(text: str) -> int | None:
    """Ultima sumă urmată de "Lei" din text (ex. "Total: 190,47 Lei")."""
    matches = list(_RO_AMOUNT_ANY.finditer(text))
    return ro_amount_to_bani(matches[-1].group(1)) if matches else None


def parse_refund_amount(text: str) -> int | None:
    """Suma dintr-un mesaj de retur: "93.59", "129", "249.9" sau "1.449,27".

    Paginile de retur scriu uneori punct ca separator zecimal. Un singur punct
    urmat de exact 3 cifre se citește ca separator de mii ("1.449").
    """
    value = text.strip()
    if not value:
        return None
    if "," in value:
        return ro_amount_to_bani(value) if re.fullmatch(_RO_AMOUNT, value) else None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        return int(value.replace(".", "")) * 100
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        whole, _, frac = value.partition(".")
        return int(whole) * 100 + int((frac + "00")[:2])
    return None


def format_lei(bani: int) -> str:
    """Afișare românească: 144927 -> "1.449,27 Lei"."""
    sign = "-" if bani < 0 else ""
    bani = abs(bani)
    whole, frac = divmod(bani, 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{frac:02d} Lei"
