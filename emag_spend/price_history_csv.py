"""Scrie istoricul prețurilor la același produs într-un CSV pe care îl deschizi în Excel.

Primește: calea fișierului și dicționarul `price_history` din analiza.json. Dă înapoi: nimic
(scrie `istoric_preturi.csv`): câte un rând pe cumpărare, grupate pe produs, cu linkul comenzii.
Același format ca produse.csv (separator `;`, zecimale cu virgulă, UTF-8 cu BOM) și aceeași
protecție contra formulelor din celulele de text (csv_export.text_cell). Fără produse repetate,
fișierul conține doar capul de tabel. Nu calculează nimic: formatează ce a calculat price_history.
"""

import csv
from pathlib import Path

from emag_spend.csv_export import lei_cell, text_cell
from emag_spend.order_links import order_url

_HEADER = [
    "produs", "categorie", "data", "comanda", "link_comanda", "vanzator", "nume_in_comanda",
    "bucati_pastrate", "pret_bucata_lei", "pret_minim_lei", "peste_minim_lei", "variante_culoare",
]


def write_price_history_csv(path: Path, price_history: dict) -> None:
    """Scrie câte un rând pe cumpărare; `peste_minim_lei` = (preț − minimul produsului) × bucăți."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(_HEADER)
        for product in price_history["products"]:
            for purchase in product["purchases"]:
                writer.writerow([
                    text_cell(product["name"]),
                    text_cell(product["category"]),
                    purchase["date"] or "",
                    text_cell(purchase["order_id"]),
                    text_cell(order_url(purchase["order_id"]) or ""),
                    text_cell(purchase["seller"]),
                    text_cell(purchase["name"]),
                    purchase["qty"],
                    lei_cell(purchase["unit_bani"]),
                    lei_cell(product["min_unit_bani"]),
                    lei_cell((purchase["unit_bani"] - product["min_unit_bani"]) * purchase["qty"]),
                    "da" if product["color_variants"] else "",
                ])
