"""Calculează cât s-a cheltuit efectiv, pe categorii, ani, vânzători și produse.

Primește: comenzile, retururile, clasificatorul, pragul „achiziție mare” (bani, pe prețul de listă pe bucată), ora generării
și, opțional, textele avertismentelor, culorile și modurile de restituire gata încărcate (altfel le citește din config/).
Dă înapoi: `Analysis` = `summary` (dicționar JSON, sume în BANI) + registrul de linii (`lines`) pentru CSV.
Cifra principală e cheia `paid` (paid_totals.py): banii plătiți efectiv. Rândurile au și sume plătite (`paid_*`, prețul
minus partea produsului din reducerile blocului), lângă cele la preț de listă (cheile vechi, păstrate pentru rapoartele vechi).
Nu citește pagini și nu scrie fișiere.
"""

import logging
from collections import defaultdict

from emag_spend import block_status, warning_messages
from emag_spend.classifier import Classifier
from emag_spend.line_ledger import build_lines
from emag_spend.models import LineOutcome, Order, ReturnRequest
from emag_spend.paid_totals import PaidTotals, compute_paid_totals, year_of
from emag_spend.price_history import build_price_history
from emag_spend.product_key import ColorWords, load_color_words
from emag_spend.refund_modes import RefundModes, load_refund_modes
from emag_spend.return_matcher import apply_returns
from emag_spend.text_normalize import normalize_text
from emag_spend.warning_details import (
    build_warnings_detail, completed_returns_without_amount, current_order_warnings, load_warning_texts,
    returns_without_result,
)

logger = logging.getLogger(__name__)

# Câte categorii apar separat în graficul pe ani; restul se strâng la "Altele".
# 6 + "Altele" = 7 serii, sub plafonul de lizibilitate al paletei de culori.
YEARLY_CHART_TOP_CATEGORIES = 6
OTHER_LABEL = "Altele"
TOP_PRODUCTS_LIMIT = 25
TOP_SELLERS_LIMIT = 12
UNCATEGORIZED_SAMPLE_LIMIT = 40
HIGHLIGHT_ITEMS_LIMIT = 80
# Sufixul unui rând care nu e produs („Transport și taxe”…) când o categorie din reguli are exact același nume:
# în graficul pe ani seriile se deosebesc după nume, iar două serii cu același nume s-ar aduna într-una.
EXTRA_NAME_CLASH_SUFFIX = " (rând separat)"

# Totalurile unei categorii: la preț de listă (cheile vechi) și plătite, după reduceri (paid_*).
_CATEGORY_KEYS = (
    "ordered_bani", "ordered_units", "kept_bani", "kept_units", "returned_bani", "returned_units",
    "cancelled_bani", "cancelled_units", "pending_bani",
    "paid_ordered_bani", "paid_kept_bani", "paid_returned_bani", "paid_cancelled_bani", "paid_pending_bani",
)
# Sumele plătite ale unui an (paid_totals._Year): ordered − cancelled − returned − pending − unknown + fees = spent.
_PAID_YEAR_KEYS = (
    "paid_ordered_bani", "paid_returned_bani", "paid_cancelled_bani", "paid_pending_bani", "paid_unknown_bani",
    "paid_fees_bani", "spent_bani",
)


class Analysis:
    """Rezultatul analizei: `summary` (dict pentru raport) și `lines` (pentru CSV)."""

    def __init__(self, summary: dict, lines: list[LineOutcome]):
        """Păstrează dicționarul pentru raport și registrul de linii pentru CSV."""
        self.summary = summary
        self.lines = lines


def _funnel(lines: list[LineOutcome]) -> dict:
    """Lanțul comandat -> anulat -> returnat -> în curs -> păstrat, la PREȚ DE LISTĂ, în bani și bucăți.

    Cheia veche `funnel`, păstrată pentru rapoartele vechi și ca informație secundară (lanțul în bani plătiți e în `paid`).
    - comandat = valoarea tuturor produselor din comenzi (fără serviciile plătite fără livrare, ex. asigurări,
      listate separat);
    - anulat = produse din blocuri „Livrare anulata” fără retur finalizat;
    - returnat = produse restituite (retur finalizat), inclusiv cele marcate ulterior „Livrare anulata” de eMAG;
    - în curs = produse plătite dar încă nelivrate/neridicate;
    - păstrat = comandat − anulat − returnat − în curs = livrate/ridicate și rămase la client.
    """
    priced = [line for line in lines if line.paid_only_qty == 0]
    return {
        "ordered_bani": sum(l.line_total_bani for l in priced),
        "cancelled_bani": sum(l.cancelled_bani for l in priced),
        "returned_bani": sum(l.returned_bani for l in priced),
        "pending_bani": sum(l.pending_bani for l in priced),
        "unknown_bani": sum(l.unknown_bani for l in priced),
        "kept_bani": sum(l.kept_bani for l in priced),
        "ordered_units": sum(l.qty for l in priced),
        "cancelled_units": sum(l.cancelled_qty for l in priced),
        "returned_units": sum(l.returned_qty for l in priced),
        "pending_units": sum(l.pending_qty for l in priced),
        "unknown_units": sum(l.unknown_qty for l in priced),
        "kept_units": sum(l.kept_qty for l in priced),
    }


def _empty_category(name: str) -> dict:
    """Totalurile unei categorii fără niciun produs (toate zero)."""
    return {"name": name, **dict.fromkeys(_CATEGORY_KEYS, 0)}


def _by_category(lines: list[LineOutcome]) -> list[dict]:
    """Totaluri pe categorii, sortate descrescător după suma plătită pe produsele păstrate."""
    acc: dict[str, dict] = defaultdict(lambda: dict.fromkeys(_CATEGORY_KEYS, 0))
    for line in lines:
        if line.paid_only_qty:
            continue
        row = acc[line.category]
        row["ordered_bani"] += line.line_total_bani
        row["ordered_units"] += line.qty
        row["kept_bani"] += line.kept_bani
        row["kept_units"] += line.kept_qty
        row["returned_bani"] += line.returned_bani
        row["returned_units"] += line.returned_qty
        row["cancelled_bani"] += line.cancelled_bani
        row["cancelled_units"] += line.cancelled_qty
        row["pending_bani"] += line.pending_bani
        row["paid_ordered_bani"] += line.paid_value_bani
        row["paid_kept_bani"] += line.kept_paid_bani
        row["paid_returned_bani"] += line.returned_paid_bani
        row["paid_cancelled_bani"] += line.cancelled_paid_bani
        row["paid_pending_bani"] += line.pending_paid_bani
    rows = [{"name": name, **values} for name, values in acc.items()]
    return sorted(rows, key=lambda r: (-r["paid_kept_bani"], -r["kept_bani"], r["name"]))


def _by_year(orders: list[Order], lines: list[LineOutcome], paid: PaidTotals) -> list[dict]:
    """Totaluri pe ani (după data plasării comenzii), crescător: la preț de listă și în bani plătiți (paid_totals.py)."""
    acc: dict[str, dict] = defaultdict(
        lambda: dict(orders=0, orders_with_kept=0, ordered_bani=0, kept_bani=0, kept_units=0,
                     returned_bani=0, cancelled_bani=0)
    )
    for order in orders:
        acc[year_of(order.placed_at)]["orders"] += 1
    kept_orders: set[tuple[str, str]] = set()
    for line in lines:
        if line.paid_only_qty:
            continue
        year = year_of(line.placed_at)
        row = acc[year]
        row["ordered_bani"] += line.line_total_bani
        row["kept_bani"] += line.kept_bani
        row["kept_units"] += line.kept_qty
        row["returned_bani"] += line.returned_bani
        row["cancelled_bani"] += line.cancelled_bani
        if line.kept_qty > 0 and (year, line.order_id) not in kept_orders:
            kept_orders.add((year, line.order_id))
            row["orders_with_kept"] += 1
    rows = []
    for year, values in sorted(acc.items()):
        spent = paid.by_year.get(year)
        rows.append({"year": year, **values, **({
            "paid_ordered_bani": spent.ordered_bani, "paid_returned_bani": spent.returned_bani,
            "paid_cancelled_bani": spent.cancelled_bani, "paid_pending_bani": spent.pending_bani,
            "paid_unknown_bani": spent.unknown_bani, "paid_fees_bani": spent.fees_bani, "spent_bani": spent.spent_bani,
        } if spent else dict.fromkeys(_PAID_YEAR_KEYS, 0))})
    return rows


def _by_year_category(lines: list[LineOutcome], categories: list[dict]) -> dict:
    """Matrice an × categorie (valoare păstrată la preț de listă) pentru graficul stivuit al rapoartelor vechi."""
    by_list_value = sorted(categories, key=lambda c: (-c["kept_bani"], c["name"]))
    top = [c["name"] for c in by_list_value if c["kept_bani"] > 0][:YEARLY_CHART_TOP_CATEGORIES]
    years = sorted({year_of(l.placed_at) for l in lines if l.paid_only_qty == 0})
    matrix: dict[str, dict[str, int]] = {y: defaultdict(int) for y in years}
    has_other = False
    for line in lines:
        if line.paid_only_qty or line.kept_bani == 0:
            continue
        series = line.category if line.category in top else OTHER_LABEL
        has_other = has_other or series == OTHER_LABEL
        matrix[year_of(line.placed_at)][series] += line.kept_bani
    series_names = top + ([OTHER_LABEL] if has_other else [])
    return {
        "years": years,
        "series": series_names,
        "values": {y: {s: matrix[y].get(s, 0) for s in series_names} for y in years},
    }


def _paid_by_year_category(lines: list[LineOutcome], categories: list[dict], paid: PaidTotals) -> dict:
    """Matrice an × serie în bani plătiți efectiv: cele mai mari categorii și rândurile care nu sunt produse
    („Transport și taxe”…), restul la „Altele”. Suma unui an = plătitul efectiv al anului (dacă nicio serie nu e negativă)."""
    taken = {c["name"] for c in categories}
    extras = [(row["name"] + (EXTRA_NAME_CLASH_SUFFIX if row["name"] in taken else ""), row["key"], row["bani"])
              for row in paid.summary["extra_rows"]]
    ranking = [(c["name"], c["paid_kept_bani"]) for c in categories if c["paid_kept_bani"] > 0]
    ranking += [(name, bani) for name, _, bani in extras if bani > 0]
    top = [name for name, _ in sorted(ranking, key=lambda r: (-r[1], r[0]))[:YEARLY_CHART_TOP_CATEGORIES]]
    years = sorted(paid.by_year)
    matrix: dict[str, dict[str, int]] = {y: defaultdict(int) for y in years}
    used_other = False

    def add(year: str, name: str, bani: int) -> None:
        """Adaugă `bani` la seria `name` (sau la „Altele”, dacă nu e printre primele) în anul dat."""
        nonlocal used_other
        series = name if name in top else OTHER_LABEL
        used_other = used_other or series == OTHER_LABEL
        matrix[year][series] += bani

    for line in lines:
        if not line.paid_only_qty and line.kept_paid_bani:
            add(year_of(line.placed_at), line.category, line.kept_paid_bani)
    for name, key, _ in extras:
        for year, bani in paid.extra_values(key).items():
            if bani:
                add(year, name, bani)
    series_names = top + ([OTHER_LABEL] if used_other else [])
    return {"years": years, "series": series_names, "values": {y: {s: matrix[y].get(s, 0) for s in series_names} for y in years}}


def _latest_order(orders_seen: dict[str, str]) -> str:
    """Comanda cea mai recentă dintre cele văzute ({număr: data ISO}): după dată, apoi după număr (mai lung = mai nou)."""
    return max(orders_seen, key=lambda order_id: (orders_seen[order_id], len(order_id), order_id))


def _top_products(lines: list[LineOutcome]) -> list[dict]:
    """Produsele cu cea mai mare sumă PLĂTITĂ pe bucățile păstrate, grupate după nume, cu comanda lor cea mai recentă.

    Se ordonează după suma totală pe nume, nu după prețul pe bucată: un produs ieftin cumpărat des poate trece înaintea
    unuia scump cumpărat o dată (titlul din raport spune asta). `order_id` = comanda cea mai recentă în care a fost
    păstrat (linkul din raport), `order_count` = în câte comenzi; `bani` = aceeași sumă la preț de listă (cheia veche).
    """
    groups: dict[str, dict] = {}
    orders_by_key: dict[str, dict[str, str]] = defaultdict(dict)
    for line in lines:
        if line.paid_only_qty or line.kept_qty == 0:
            continue
        key = normalize_text(line.name)
        row = groups.setdefault(key, {"name": line.name, "category": line.category, "units": 0, "bani": 0, "paid_bani": 0})
        row["units"] += line.kept_qty
        row["bani"] += line.kept_bani
        row["paid_bani"] += line.kept_paid_bani
        seen = orders_by_key[key]
        seen[line.order_id] = max(seen.get(line.order_id, ""), line.placed_at or "")
    rows = [{**row, "order_id": _latest_order(orders_by_key[key]), "order_count": len(orders_by_key[key])}
            for key, row in groups.items()]
    return sorted(rows, key=lambda r: (-r["paid_bani"], -r["bani"], r["name"]))[:TOP_PRODUCTS_LIMIT]


def _by_seller(lines: list[LineOutcome]) -> list[dict]:
    """Vânzătorii cu cea mai mare sumă plătită pe produsele păstrate (fără transport și taxe)."""
    groups: dict[str, dict] = {}
    for line in lines:
        if line.paid_only_qty or (line.kept_bani == 0 and line.kept_paid_bani == 0):
            continue
        row = groups.setdefault(line.seller, {"seller": line.seller, "units": 0, "bani": 0, "paid_bani": 0})
        row["units"] += line.kept_qty
        row["bani"] += line.kept_bani
        row["paid_bani"] += line.kept_paid_bani
    return sorted(groups.values(), key=lambda r: (-r["paid_bani"], -r["bani"], r["seller"]))[:TOP_SELLERS_LIMIT]


# Stările unei linii: (numele stării, câmpul cu bucăți, suma la preț de listă, suma plătită).
_STATE_PARTS = (
    ("kept", "kept_qty", "kept_bani", "kept_paid_bani"),
    ("returned", "returned_qty", "returned_bani", "returned_paid_bani"),
    ("cancelled", "cancelled_qty", "cancelled_bani", "cancelled_paid_bani"),
    ("pending", "pending_qty", "pending_bani", "pending_paid_bani"),
    ("unknown", "unknown_qty", "unknown_bani", "unknown_paid_bani"),
)


def _big_items(lines: list[LineOutcome], threshold_bani: int) -> dict:
    """Produsele cu preț de LISTĂ pe bucată STRICT peste prag, cu starea fiecărei părți (sumă de listă și sumă plătită)."""
    rows: list[dict] = []
    for line in lines:
        if line.paid_only_qty or line.qty <= 0:
            continue
        if line.line_total_bani <= threshold_bani * line.qty:
            continue
        unit = (line.line_total_bani * 2 + line.qty) // (line.qty * 2)
        for state, qty_attr, bani_attr, paid_attr in _STATE_PARTS:
            qty = getattr(line, qty_attr)
            if qty > 0:
                rows.append({
                    "order_id": line.order_id,
                    "date": (line.placed_at or "")[:10],
                    "name": line.name,
                    "seller": line.seller,
                    "category": line.category,
                    "qty": qty,
                    "unit_bani": unit,
                    "amount_bani": getattr(line, bani_attr),
                    "paid_amount_bani": getattr(line, paid_attr),
                    "state": state,
                    "returned_from_cancelled": bool(line.returned_from_cancelled_qty) and state == "returned",
                })
    rows.sort(key=lambda r: (-r["unit_bani"], r["date"], r["order_id"]))
    totals = {f"{s}_bani": sum(r["amount_bani"] for r in rows if r["state"] == s) for s, *_ in _STATE_PARTS}
    totals.update({f"{s}_units": sum(r["qty"] for r in rows if r["state"] == s) for s, *_ in _STATE_PARTS})
    totals.update({f"{s}_paid_bani": sum(r["paid_amount_bani"] for r in rows if r["state"] == s) for s, *_ in _STATE_PARTS})
    return {"threshold_bani": threshold_bani, "items": rows, **totals}


def _highlights(lines: list[LineOutcome], categories: list[dict], names: tuple[str, ...]) -> dict:
    """Pentru fiecare categorie cerută explicit: totalurile și lista produselor, pe stări (sumă de listă și plătită)."""
    result: dict[str, dict] = {}
    by_name = {c["name"]: c for c in categories}
    for name in names:
        totals = by_name.get(name) or _empty_category(name)
        items = []
        for line in lines:
            if line.category != name or line.paid_only_qty:
                continue
            for state, qty_attr, bani_attr, paid_attr in _STATE_PARTS:
                qty = getattr(line, qty_attr)
                if qty > 0:
                    items.append({
                        "order_id": line.order_id,
                        "date": (line.placed_at or "")[:10],
                        "name": line.name,
                        "qty": qty,
                        "amount_bani": getattr(line, bani_attr),
                        "paid_amount_bani": getattr(line, paid_attr),
                        "state": state,
                    })
        items.sort(key=lambda r: (r["date"], r["order_id"], r["name"]))
        result[name] = {"totals": totals, "items": items[:HIGHLIGHT_ITEMS_LIMIT], "items_total": len(items)}
    return result


def _order_outcomes(orders: list[Order], lines: list[LineOutcome]) -> dict:
    """Câte comenzi s-au păstrat integral/parțial, s-au returnat, anulat etc."""
    by_order: dict[str, list[LineOutcome]] = defaultdict(list)
    for line in lines:
        by_order[line.order_id].append(line)
    counts = defaultdict(int)
    for order in orders:
        group = by_order.get(order.order_id, [])
        kept = sum(l.kept_qty for l in group)
        returned = sum(l.returned_qty for l in group)
        cancelled = sum(l.cancelled_qty for l in group)
        pending = sum(l.pending_qty for l in group)
        unknown = sum(l.unknown_qty for l in group)
        paid_only = sum(l.paid_only_qty for l in group)
        if not group:
            outcome = "no_items"
        elif paid_only and not (kept or returned or cancelled or pending or unknown):
            outcome = "paid_only"
        elif pending:
            outcome = "in_progress"
        elif unknown:
            outcome = "unknown"
        elif kept and not returned and not cancelled:
            outcome = "kept_all"
        elif kept:
            outcome = "kept_partial"
        elif returned:
            outcome = "returned_all"
        else:
            outcome = "cancelled_all"
        counts[outcome] += 1
    keys = ("kept_all", "kept_partial", "returned_all", "cancelled_all", "in_progress", "paid_only", "unknown", "no_items")
    return {"total": len(orders), **{k: counts.get(k, 0) for k in keys}}


def _excluded_blocks(orders: list[Order], status: str) -> list[dict]:
    """Blocuri de un anumit status, cu produsele și suma plătită (pentru secțiunea 'excluse')."""
    rows = []
    for order in orders:
        for block in order.blocks:
            if block.status == status:
                rows.append({
                    "order_id": order.order_id,
                    "date": (order.placed_at or "")[:10],
                    "seller": block.seller,
                    "names": [item.name for item in block.items],
                    "products_bani": sum(item.line_total_bani for item in block.items),
                    "paid_bani": block.paid_bani or 0,
                    "status_text": block.status_text,
                })
    return rows


def _reconciliation(orders: list[Order], returns: list[ReturnRequest]) -> dict:
    """Cifre de control: ce s-a plătit efectiv, vouchere, taxe, restituiri."""
    delivered = [b for o in orders for b in o.blocks if b.status == block_status.DELIVERED]
    header_mismatches = []
    for order in orders:
        if order.header_total_bani is None:
            continue
        paid_sum = sum(b.paid_bani or 0 for b in order.blocks)
        if paid_sum != order.header_total_bani:
            header_mismatches.append({"order_id": order.order_id, "header_bani": order.header_total_bani, "blocks_bani": paid_sum})
    completed = [r for r in returns if r.completed]
    modes: dict[str, int] = defaultdict(int)
    for ret in completed:
        modes[ret.refund_mode or "necunoscut"] += 1
    return {
        "paid_delivered_bani": sum(b.paid_bani or 0 for b in delivered),
        "vouchers_delivered_bani": -sum(sum(b.vouchers_bani) for b in delivered),
        "shipping_delivered_bani": sum(b.shipping_bani or 0 for b in delivered),
        "services_delivered_bani": sum(sum(b.services_bani) + sum(b.other_bani) for b in delivered),
        "returns_total": len(returns),
        "returns_completed": len(completed),
        "returns_cancelled": sum(1 for r in returns if r.cancelled),
        "returns_pending": len(returns_without_result(returns)),  # aceleași selecții ca în warnings_detail
        "refunds_bani": sum(r.refund_bani or 0 for r in completed),
        "refunds_without_amount": len(completed_returns_without_amount(returns)),
        "refund_modes": dict(modes),
        "header_total_mismatches": header_mismatches,
        "orders_with_storno": sorted({o.order_id for o in orders for b in o.blocks if b.has_storno}),
    }


def _uncategorized(lines: list[LineOutcome], default_category: str) -> list[dict]:
    """Produsele fără categorie (după nume), cu valoarea de listă și comanda lor cea mai recentă (pentru link)."""
    groups: dict[str, dict] = defaultdict(lambda: {"units": 0, "bani": 0})
    orders_by_name: dict[str, dict[str, str]] = defaultdict(dict)
    for line in lines:
        if line.category == default_category and not line.paid_only_qty:
            groups[line.name]["units"] += line.qty
            groups[line.name]["bani"] += line.line_total_bani
            seen = orders_by_name[line.name]
            seen[line.order_id] = max(seen.get(line.order_id, ""), line.placed_at or "")
    rows = [{"name": name, **values, "order_id": _latest_order(orders_by_name[name]), "order_count": len(orders_by_name[name])}
            for name, values in groups.items()]
    return sorted(rows, key=lambda r: (-r["bani"], r["name"]))


def analyze(
    orders: list[Order],
    returns: list[ReturnRequest],
    classifier: Classifier,
    threshold_bani: int,
    generated_at: str,
    highlight_categories: tuple[str, ...] = (),
    warning_texts: dict | None = None,
    color_words: ColorWords | None = None,
    refund_modes: RefundModes | None = None,
) -> Analysis:
    """Rulează toată analiza și întoarce `Analysis`.

    O categorie din `highlight_categories` care nu există în regulile clasificatorului primește
    un avertisment (totalul ei ar apărea 0, un rezultat greșit care pare normal).
    `warning_texts` (config/avertismente.json), `color_words` (config/culori.json) și `refund_modes`
    (config/restituiri.json), încărcate de apelant; dacă lipsesc, se citesc fișierele implicite din config/.
    """
    warning_texts = warning_texts if warning_texts is not None else load_warning_texts()
    color_words = color_words if color_words is not None else load_color_words()
    refund_modes = refund_modes if refund_modes is not None else load_refund_modes()
    lines = build_lines(orders)
    for line in lines:
        line.category, line.rule = classifier.classify(line.name)
    match_report = apply_returns(lines, returns)
    paid = compute_paid_totals(orders, lines, returns, match_report, refund_modes)

    funnel = _funnel(lines)
    categories = _by_category(lines)
    dates = sorted(o.placed_at for o in orders if o.placed_at)
    reconciliation = _reconciliation(orders, returns)

    warnings: list[str] = []
    for order in orders:
        warnings.extend(current_order_warnings(order))  # fără zgomotul vechi din cache-uri salvate de o versiune anterioară
    warnings.extend(match_report.warnings)
    warnings.extend(paid.warnings)
    known_categories = set(classifier.category_names) | {classifier.default_category}  # și „Necategorizat” are totaluri reale
    for name in highlight_categories:
        if name not in known_categories:
            warnings.append(warning_messages.format_highlight_category_missing(name))
    parts = sum(funnel[k] for k in ("cancelled_bani", "returned_bani", "pending_bani", "unknown_bani", "kept_bani"))
    if parts != funnel["ordered_bani"]:
        warnings.append(warning_messages.format_funnel_not_closing(funnel["ordered_bani"], parts))
    unknown_blocks = _excluded_blocks(orders, block_status.UNKNOWN)
    for block in unknown_blocks:
        warnings.append(warning_messages.format_unknown_status(block["order_id"], block["seller"], block["status_text"]))
    if reconciliation["returns_pending"]:
        warnings.append(warning_messages.format_pending_returns(reconciliation["returns_pending"]))
    if reconciliation["refunds_without_amount"]:
        warnings.append(warning_messages.format_refunds_without_amount(reconciliation["refunds_without_amount"]))
    if reconciliation["header_total_mismatches"]:
        warnings.append(warning_messages.format_header_mismatches(len(reconciliation["header_total_mismatches"])))

    uncategorized_rows = _uncategorized(lines, classifier.default_category)
    if uncategorized_rows:
        warnings.append(warning_messages.format_uncategorized(len(uncategorized_rows)))

    paid_summary = {**paid.summary, "by_year_category": _paid_by_year_category(lines, categories, paid)}
    summary = {
        "meta": {
            "generated_at": generated_at,
            "threshold_bani": threshold_bani,
            "first_order": dates[0][:10] if dates else None,
            "last_order": dates[-1][:10] if dates else None,
            "orders": len(orders),
            "blocks": sum(len(o.blocks) for o in orders),
            "lines": len(lines),
        },
        "funnel": funnel,
        "paid": paid_summary,
        "orders": _order_outcomes(orders, lines),
        "by_category": categories,
        "by_year": _by_year(orders, lines, paid),
        "by_year_category": _by_year_category(lines, categories),
        "top_products": _top_products(lines),
        "by_seller": _by_seller(lines),
        "big": _big_items(lines, threshold_bani),
        "highlights": _highlights(lines, categories, highlight_categories),
        "paid_only": _excluded_blocks(orders, block_status.PAID_ONLY),
        "in_progress": _excluded_blocks(orders, block_status.IN_PROGRESS),
        "reconciliation": reconciliation,
        "returns": {
            "matched_units": match_report.matched_units,
            "matched_from_cancelled_units": match_report.matched_from_cancelled_units,
            "unmatched_refund_bani": match_report.unmatched_refund_bani,
        },
        "uncategorized": uncategorized_rows[:UNCATEGORIZED_SAMPLE_LIMIT],
        "uncategorized_count": len(uncategorized_rows),
        "price_history": build_price_history(lines, color_words),
        "warnings": warnings,
        "warnings_detail": build_warnings_detail(
            warnings, orders, returns, reconciliation["header_total_mismatches"], warning_texts
        ),
    }
    logger.info(
        "analiză: %d comenzi, plătit efectiv %d bani (păstrat la preț de listă %d bani), %d avertismente",
        len(orders), paid.summary["spent_bani"], funnel["kept_bani"], len(warnings),
    )
    return Analysis(summary, lines)
