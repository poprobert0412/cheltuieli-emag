"""Citește o pagină de detalii retur eMAG și o transformă într-un `ReturnRequest`.

Primește: calea paginii și liniile ei de text (html_lines).
Dă înapoi: numărul returului, comenzile la care se referă, produsele, pașii
parcurși, suma restituită și modul de restituire.
NU citește secțiunea "Detalii de contact" (nume, e-mail, telefon, adresă) și
nici codurile PIN/QR: parserul se uită doar la secțiunile de mai jos.
Ridică ValueError dacă pagina nu e un retur (sesiune expirată).
"""

import re

from emag_spend.models import ReturnRequest
from emag_spend.money_ro import parse_refund_amount
from emag_spend.text_normalize import normalize_text

_RETURN_HEADER = re.compile(r"^Retur\s*#(\d+)", re.IGNORECASE)
_REFUND = re.compile(r"Suma de\s*([\d.,]+)\s*(?:RON|Lei|lei)", re.IGNORECASE)
_ORDER_REF = re.compile(r"#(\d{5,})")
_STEP_DATE_ANYWHERE = re.compile(r"Data:\s*\d{1,2}\s+[A-Za-zăâîșțşţ]+[^|]*", re.IGNORECASE)


def _index_of(lines: list[str], text: str, start: int = 0) -> int | None:
    """Prima linie egală (normalizat) cu `text`, de la `start`."""
    wanted = normalize_text(text)
    for i in range(start, len(lines)):
        if normalize_text(lines[i]) == wanted:
            return i
    return None


def _value_after_label(lines: list[str], label: str) -> str:
    """Valoarea unei etichete: pe aceeași linie după etichetă (cu sau fără ':') sau pe linia următoare."""
    wanted = normalize_text(label)
    label_pattern = re.compile(r"^\s*" + re.escape(label) + r"\s*:?\s*", re.IGNORECASE)
    for i, line in enumerate(lines):
        if normalize_text(line).startswith(wanted):
            rest = label_pattern.sub("", line, count=1).strip()
            if rest:
                return rest
            return lines[i + 1].strip() if i + 1 < len(lines) else ""
    return ""


def parse_return(detail_path: str, lines: list[str]) -> ReturnRequest:
    """Construiește `ReturnRequest` din liniile paginii de retur."""
    header = next((m for m in map(_RETURN_HEADER.match, lines) if m), None)
    if header is None:
        raise ValueError(f"pagina {detail_path} nu conține 'Retur #' (sesiune expirată?)")

    products_at = _index_of(lines, "Detalii comanda")
    status_at = _index_of(lines, "Status retur")
    contact_at = _index_of(lines, "Detalii de contact", status_at or 0)
    product_names: list[str] = []
    if products_at is not None and status_at is not None:
        product_names = lines[products_at + 1 : status_at]

    steps: list[str] = []
    refund_bani: int | None = None
    section: list[str] = []
    if status_at is not None:
        section = lines[status_at + 1 : contact_at if contact_at is not None else len(lines)]
        for i, line in enumerate(section):
            if _STEP_DATE_ANYWHERE.search(line):
                before = _STEP_DATE_ANYWHERE.split(line)[0].strip()
                if before:  # titlul și data pe aceeași linie
                    steps.append(before)
                elif i > 0 and not _STEP_DATE_ANYWHERE.search(section[i - 1]):
                    steps.append(section[i - 1])  # titlul pe linia de dinainte
        refund_match = _REFUND.search(" ".join(section))
        if refund_match:
            refund_bani = parse_refund_amount(refund_match.group(1))

    order_ids: list[str] = []
    orders_at = next(
        (i for i, line in enumerate(lines) if normalize_text(line).startswith("produse din comanda")), None
    )
    if orders_at is not None:
        for line in lines[orders_at:]:
            if normalize_text(line).startswith("istoricul tau"):
                break
            for ref in _ORDER_REF.finditer(line):  # numărul poate fi lipit de alt text pe aceeași linie
                if ref.group(1) not in order_ids:
                    order_ids.append(ref.group(1))

    # Doar pașii CU DATĂ sunt încheiați: la un retur neprocesat, pagina listează și pașii
    # viitori ("... Receptionare produs, Restituire suma") fără dată; ei nu înseamnă restituire.
    normalized_steps = [normalize_text(step) for step in steps]
    completed = any("restituire suma" in step for step in normalized_steps)
    cancelled = (not completed) and any("cerere anulata" in step for step in normalized_steps)

    return ReturnRequest(
        return_id=header.group(1),
        detail_path=detail_path,
        order_ids=order_ids,
        product_names=product_names,
        steps=steps,
        refund_bani=refund_bani,
        refund_mode=_value_after_label(lines, "Modalitate restituire"),
        completed=completed,
        cancelled=cancelled,
    )
