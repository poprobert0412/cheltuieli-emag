"""Scrie registrul complet de produse într-un CSV pe care îl deschizi în Excel.

Primește: calea fișierului, liniile de registru și pragul pentru „achiziție mare”. Dă înapoi: nimic (scrie
fișierul; separator `;`, zecimale cu virgulă, UTF-8 cu BOM). Coloana `link_comanda` = adresa comenzii pe eMAG
(doar pentru numere valide, order_links.py); `platit_linie_lei` / `platit_pastrat_lei` = sumele plătite, după partea
produsului din reducerile blocului (lângă cele la preț de listă). Celulele de TEXT vin din pagini controlate de vânzători: dacă încep
cu `= + - @` sau tab/CR, Excel le-ar evalua ca formulă (CSV injection), deci `text_cell` pune un apostrof în față;
sumele generate de program (și cele negative) nu se ating. `text_cell` și `lei_cell` le folosește și price_history_csv.py.
"""

import csv
from pathlib import Path

from emag_spend.models import LineOutcome
from emag_spend.order_links import order_url

_HEADER = [
    "comanda", "link_comanda", "data", "an", "vanzator", "produs", "categorie", "regula_categorie",
    "cantitate", "valoare_linie_lei", "platit_linie_lei", "pastrat_lei", "platit_pastrat_lei", "returnat_lei", "anulat_lei", "in_curs_lei",
    "bucati_pastrate", "bucati_returnate", "bucati_anulate", "bucati_in_curs",
    "status_bloc", "retur_id", "peste_prag",
]


# Caracterele cu care o celulă începe ca formulă în Excel / LibreOffice (lista OWASP pentru CSV injection).
# Tuplu, nu șir: `"" in "=+-"` ar fi adevărat pentru o celulă goală.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def text_cell(value: str) -> str:
    """Text sigur de deschis în Excel: un apostrof în față dacă ar începe ca formulă (și după spații).

    Se aplică doar câmpurilor de text din cont, nu sumelor: '-12,00' generat de program rămâne număr.
    """
    text = str(value)
    if text[:1] in _FORMULA_STARTS or text.lstrip()[:1] in _FORMULA_STARTS:
        return "'" + text
    return text


def lei_cell(bani: int) -> str:
    """Suma în lei cu virgulă zecimală, fără separator de mii (ex. 144927 -> '1449,27')."""
    sign = "-" if bani < 0 else ""
    whole, frac = divmod(abs(bani), 100)
    return f"{sign}{whole},{frac:02d}"


def write_lines_csv(path: Path, lines: list[LineOutcome], threshold_bani: int) -> None:
    """Scrie câte un rând pe produs; `peste_prag` = da dacă prețul pe bucată depășește pragul."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(_HEADER)
        for line in lines:
            above = line.qty > 0 and line.line_total_bani > threshold_bani * line.qty
            writer.writerow([
                text_cell(line.order_id),
                text_cell(order_url(line.order_id) or ""),
                (line.placed_at or "")[:10],
                (line.placed_at or "")[:4],
                text_cell(line.seller),
                text_cell(line.name),
                text_cell(line.category),
                text_cell(line.rule),
                line.qty,
                lei_cell(line.line_total_bani),
                lei_cell(line.paid_value_bani),
                lei_cell(line.kept_bani),
                lei_cell(line.kept_paid_bani),
                lei_cell(line.returned_bani),
                lei_cell(line.cancelled_bani),
                lei_cell(line.pending_bani),
                line.kept_qty,
                line.returned_qty,
                line.cancelled_qty,
                line.pending_qty,
                text_cell(line.block_status),
                text_cell(",".join(line.return_ids)),
                "da" if above else "",
            ])
