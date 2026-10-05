"""Istoricul prețurilor la același produs, din produsele cumpărate în cel puțin două comenzi.

Primește: registrul de linii (după retururi) și lista de culori. Dă înapoi: `price_history` din analiza.json
(`summary` + `products`, sortate descrescător după diferența față de cel mai mic preț plătit), sume în BANI.
Contează doar unitățile PĂSTRATE; preț pe bucată = total linie / cantitate, rotunjit întreg; liniile cu preț ≤ 0
(cadouri) se ignoră. „Același produs” = aceeași cheie (product_key.py); un nume trunchiat „[...]” se alătură
unei grupe doar dacă potrivirea e unică. Ce NU face: nu spune „ai pierdut/ai câștigat” (prețul include promoții).
"""

from dataclasses import dataclass

from emag_spend.models import LineOutcome
from emag_spend.product_key import ColorWords, ProductKey, make_product_key
from emag_spend.return_matcher import MIN_TRUNCATED_PREFIX

# Un produs intră în istoric doar dacă are unități păstrate în cel puțin atâtea comenzi diferite:
# o singură comandă nu are un „preț de data trecută” cu care să se compare.
MIN_ORDERS_PER_PRODUCT = 2
# Procentele de variație se rotunjesc la o zecimală (ex. 7,4%): mai multe ar sugera o precizie
# pe care prețuri cu promoții și vânzători diferiți nu o au.
PERCENT_DECIMALS = 1


@dataclass
class _Purchase:
    """O linie păstrată din registru, cu cheia produsului și prețul pe bucată."""

    line: LineOutcome
    product_key: ProductKey
    unit_bani: int


def _unit_bani(line: LineOutcome) -> int:
    """Prețul pe bucată în bani: total linie / cantitate, rotunjit la cel mai apropiat ban (aritmetică întreagă)."""
    return (line.line_total_bani * 2 + line.qty) // (line.qty * 2)


def _purchases(lines: list[LineOutcome], color_words: ColorWords) -> list[_Purchase]:
    """Liniile cu cel puțin o unitate păstrată, preț pe bucată pozitiv și nume cu cel puțin un cuvânt."""
    found = []
    for line in lines:
        if line.kept_qty <= 0 or line.qty <= 0 or line.line_total_bani <= 0:
            continue
        unit = _unit_bani(line)
        product_key = make_product_key(line.name, color_words)
        if unit > 0 and product_key.key:  # un preț care se rotunjește la 0 bani e tot un cadou
            found.append(_Purchase(line, product_key, unit))
    return found


def _truncated_prefix_matches(truncated: _Purchase, members: list[_Purchase]) -> bool:
    """True dacă numele trunchiat începe la fel ca numele (sau cheia) vreunui membru al grupei, cu un prefix de
    cel puțin MIN_TRUNCATED_PREFIX caractere (ca la retururi: unul mai scurt ar potrivi produse diferite)."""
    prefix = truncated.product_key.prefix
    key_prefix = truncated.product_key.key
    return any(
        (len(prefix) >= MIN_TRUNCATED_PREFIX and member.product_key.normalized.startswith(prefix))
        or (len(key_prefix) >= MIN_TRUNCATED_PREFIX and member.product_key.key.startswith(key_prefix))
        for member in members
    )


def _group_by_product(purchases: list[_Purchase]) -> dict[str, list[_Purchase]]:
    """Grupează cumpărările după cheie; un nume trunchiat se alătură grupei care se potrivește, dacă e una singură.

    Ambiguu sau fără potrivire: rămâne în grupa lui (mai bine două grupe decât produse unite greșit).
    """
    groups: dict[str, list[_Purchase]] = {}
    for purchase in purchases:
        if not purchase.product_key.truncated:
            groups.setdefault(purchase.product_key.key, []).append(purchase)
    for purchase in purchases:
        if not purchase.product_key.truncated:
            continue
        matching = [key for key, members in groups.items()
                    if any(not m.product_key.truncated for m in members) and _truncated_prefix_matches(purchase, members)]
        target = matching[0] if len(matching) == 1 else purchase.product_key.key
        groups.setdefault(target, []).append(purchase)
    return groups


def _chronological(purchases: list[_Purchase]) -> list[_Purchase]:
    """Cumpărările de la cea mai veche la cea mai nouă (fără dată = cele mai vechi; apoi după număr de comandă)."""
    return sorted(
        purchases,
        key=lambda p: ((p.line.placed_at or "")[:16], len(p.line.order_id), p.line.order_id),
    )


def _display_name(purchases: list[_Purchase]) -> str:
    """Cel mai recent nume complet (netrunchiat); dacă toate sunt trunchiate, cel mai recent."""
    for purchase in reversed(purchases):
        if not purchase.product_key.truncated:
            return purchase.line.name
    return purchases[-1].line.name


def _product_entry(key: str, purchases: list[_Purchase]) -> dict:
    """Intrarea unui produs: cumpărările, extremele de preț și comparațiile cerute."""
    ordered = _chronological(purchases)
    units = [p.unit_bani for p in ordered]
    kept_units = sum(p.line.kept_qty for p in ordered)
    low = min(units)
    last = ordered[-1]
    previous = next(p for p in reversed(ordered) if p.line.order_id != last.line.order_id)
    delta = last.unit_bani - previous.unit_bani
    return {
        "key": key,
        "name": _display_name(ordered),
        "category": last.line.category,
        "purchases": [{
            "date": (p.line.placed_at or "")[:10] or None,
            "order_id": p.line.order_id,
            "seller": p.line.seller,
            "name": p.line.name,
            "qty": p.line.kept_qty,
            "unit_bani": p.unit_bani,
        } for p in ordered],
        "kept_units": kept_units,
        "first_unit_bani": ordered[0].unit_bani,
        "last_unit_bani": last.unit_bani,
        "min_unit_bani": low,
        "max_unit_bani": max(units),
        "last_vs_prev_unit_bani": delta,
        "last_vs_prev_pct": round(delta * 100 / previous.unit_bani, PERCENT_DECIMALS),  # prețul precedent e > 0 (liniile ≤ 0 sunt ignorate)
        "last_vs_prev_impact_bani": delta * last.line.kept_qty,
        "overpaid_vs_min_bani": sum((p.unit_bani - low) * p.line.kept_qty for p in ordered),
        # nume trunchiate nu intră: ele pot pierde culoarea din coadă fără ca produsul să fi variat
        "color_variants": len({p.product_key.colors for p in ordered if not p.product_key.truncated}) > 1,
    }


def _summary(products: list[dict]) -> dict:
    """Totalurile pe toate produsele din istoric (impactul ultimei cumpărări, ca sume pozitive)."""
    cheaper = [p for p in products if p["last_vs_prev_unit_bani"] < 0]
    pricier = [p for p in products if p["last_vs_prev_unit_bani"] > 0]
    return {
        "products": len(products),
        "purchases": sum(len(p["purchases"]) for p in products),
        "units": sum(p["kept_units"] for p in products),
        "overpaid_vs_min_bani": sum(p["overpaid_vs_min_bani"] for p in products),
        "last_vs_prev": {
            "cheaper_products": len(cheaper),
            "pricier_products": len(pricier),
            "same_products": len(products) - len(cheaper) - len(pricier),
            "cheaper_bani": -sum(p["last_vs_prev_impact_bani"] for p in cheaper),
            "pricier_bani": sum(p["last_vs_prev_impact_bani"] for p in pricier),
        },
    }


def build_price_history(lines: list[LineOutcome], color_words: ColorWords) -> dict:
    """Istoricul prețurilor la același produs (cheia `price_history` din analiza.json)."""
    groups = _group_by_product(_purchases(lines, color_words))
    products = [
        _product_entry(key, members)
        for key, members in groups.items()
        if len({p.line.order_id for p in members}) >= MIN_ORDERS_PER_PRODUCT
    ]
    products.sort(key=lambda p: (-p["overpaid_vs_min_bani"], p["key"]))
    return {"summary": _summary(products), "products": products}
