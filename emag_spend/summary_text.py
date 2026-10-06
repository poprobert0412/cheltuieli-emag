"""Construiește rezumatul în text simplu al unei analize (ecran + rezumat.txt).

Primește: dicționarul `summary` din spend_analysis. Dă înapoi: un text în română, cu cifrele principale: cât ai
cheltuit (banii plătiți efectiv, cheia `paid`), lanțul de la comandat la plătit, categorii, ani, alcool, televizoare,
achiziții mari, cifre de control, prețuri la același produs și avertismente (cu linkul comenzii la fiecare rând).
Un rezumat vechi, fără `paid`, `warnings_detail` sau `price_history`, se formatează ca înainte (la preț de listă).
Nu calculează nimic: doar formatează ce a calculat spend_analysis.
"""

from emag_spend.money_ro import format_lei
from emag_spend.order_links import order_url
from emag_spend.warning_messages import parse_order_warning

# Câte rânduri se arată dintr-o grupă de avertismente în rezumat; restul se văd în analiza.json.
_MAX_WARNING_ITEMS_SHOWN = 15
# Câte produse se arată la „Prețuri la același produs”; lista completă e în istoric_preturi.csv.
_MAX_PRICE_PRODUCTS_SHOWN = 10
# Lățimea la care se taie numele unui produs în rezumat (numele întreg e în CSV).
_PRODUCT_NAME_WIDTH = 70
# Lățimea etichetelor din lanțul în bani plătiți (cea mai lungă, „= PLĂTIT EFECTIV PE CE AI PĂSTRAT”, plus puncte):
# sumele încep toate în aceeași coloană.
_FUNNEL_LABEL_WIDTH = 38
# Lățimea maximă a coloanei de nume la categorii: numele mai lungi împing doar rândul lor, nu tot tabelul.
_MAX_CATEGORY_NAME_WIDTH = 46


def _units(count: int) -> str:
    """Număr de bucăți, afișat ca "12 buc"."""
    return f"{count} buc"


def _counted(count: int, one: str, many: str) -> str:
    """„1 retur”, „5 retururi”, „25 de retururi”: acordul numeralului în română."""
    if count == 1:
        return f"1 {one}"
    rest = abs(count) % 100
    return f"{count} {'de ' if count and (rest >= 20 or rest == 0) else ''}{many}"


def _short(name: str) -> str:
    """Numele produsului, tăiat la _PRODUCT_NAME_WIDTH caractere (cu „…” dacă s-a tăiat)."""
    return name if len(name) <= _PRODUCT_NAME_WIDTH else name[: _PRODUCT_NAME_WIDTH - 1].rstrip() + "…"


def _change_text(delta_bani: int) -> str:
    """„mai scump cu X” / „mai ieftin cu X” / „același preț”, pentru diferența ultimul − precedentul."""
    if delta_bani > 0:
        return f"mai scump cu {format_lei(delta_bani)}"
    if delta_bani < 0:
        return f"mai ieftin cu {format_lei(-delta_bani)}"
    return "același preț"


def _price_history_lines(history: dict) -> list[str]:
    """Secțiunea „Prețuri la același produs”: totaluri, cele mai mari diferențe și avertismentul de interpretare."""
    summary = history["summary"]
    out = ["", "PREȚURI LA ACELAȘI PRODUS (păstrate, cumpărate în cel puțin 2 comenzi)"]
    if not summary["products"]:
        out.append("  niciun produs păstrat nu a fost cumpărat în două sau mai multe comenzi")
        return out
    change = summary["last_vs_prev"]
    out.append(f"  {summary['products']} produse, {summary['purchases']} cumpărări, {_units(summary['units'])}")
    out.append(
        f"  ultima cumpărare față de cea dinainte: {change['pricier_products']} mai scumpe "
        f"({format_lei(change['pricier_bani'])} în plus la bucățile ultimei cumpărări), "
        f"{change['cheaper_products']} mai ieftine ({format_lei(change['cheaper_bani'])} mai puțin), "
        f"{change['same_products']} la același preț"
    )
    out.append(f"  diferență totală față de cel mai mic preț plătit: {format_lei(summary['overpaid_vs_min_bani'])}")
    out.append("  cele mai mari diferențe față de cel mai mic preț:")
    for product in history["products"][:_MAX_PRICE_PRODUCTS_SHOWN]:
        out.append(
            f"    - {_short(product['name'])}: {len(product['purchases'])} cumpărări ({_units(product['kept_units'])}), "
            f"prima {format_lei(product['first_unit_bani'])}, ultima {format_lei(product['last_unit_bani'])} / buc "
            f"(ultima față de cea dinainte: {_change_text(product['last_vs_prev_unit_bani'])}), "
            f"cel mai mic {format_lei(product['min_unit_bani'])}, "
            f"diferență față de minim {format_lei(product['overpaid_vs_min_bani'])}"
        )
    if len(history["products"]) > _MAX_PRICE_PRODUCTS_SHOWN:
        out.append(f"    ... și încă {len(history['products']) - _MAX_PRICE_PRODUCTS_SHOWN} (vezi istoric_preturi.csv)")
    out.append(
        "  Atenție: prețurile includ promoții, sunt înainte de vouchere și pot fi de la vânzători diferiți; "
        "„mai scump” nu înseamnă că ai pierdut bani. Comparația e pe prețul de listă din comenzi, nu pe suma plătită."
    )
    return out


def _item_head(item: dict) -> str:
    """„comanda X”, „retur Y” sau „retur Y, comanda X”, după ce are rândul (gol dacă nu are niciuna)."""
    orders = ", ".join(item["order_ids"])
    parts = []
    if item.get("return_id"):
        parts.append(f"retur {item['return_id']}")
    if orders:
        parts.append(f"comanda {orders}")
    return ", ".join(parts)


def _item_lines(item: dict) -> list[str]:
    """Un rând de avertisment (comanda sau returul, data, detaliul) și, dedesubt, linkul fiecărei comenzi."""
    head = _item_head(item)
    date = f" ({item['placed_at']})" if item.get("placed_at") else ""
    lines = [f"    - {head}{date}: {item['text']}" if head else f"    - {item['text']}"]
    lines.extend(f"      {url}" for url in (order_url(order_id) for order_id in item["order_ids"]) if url)
    return lines


def _warning_lines(summary: dict) -> list[str]:
    """Secțiunea „Avertismente”: pe grupe, cu explicație, ce faci și linkul comenzilor.

    Fără `warnings_detail` (rezumat vechi) se arată lista simplă de texte, cu linkul comenzii când textul numește una.
    """
    warnings = summary["warnings"]
    out = ["", f"AVERTISMENTE: {len(warnings)}"]
    groups = summary.get("warnings_detail")
    if groups is None:
        for warning in warnings[:_MAX_WARNING_ITEMS_SHOWN]:
            out.append(f"  - {warning}")
            urls = (order_url(order_id) for order_id in parse_order_warning(warning).order_ids)
            out.extend(f"      {url}" for url in urls if url)
        if len(warnings) > _MAX_WARNING_ITEMS_SHOWN:
            out.append(f"  ... și încă {len(warnings) - _MAX_WARNING_ITEMS_SHOWN} (vezi analiza.json)")
        return out
    for group in groups:
        out.append(f"  {group['title']}: {group['count']}")
        out.append(f"    {group['explanation']}")
        out.append(f"    Ce faci: {group['what_to_do']}")
        for item in group["items"][:_MAX_WARNING_ITEMS_SHOWN]:
            out.extend(_item_lines(item))
        if group["count"] > _MAX_WARNING_ITEMS_SHOWN:
            out.append(f"    ... și încă {group['count'] - _MAX_WARNING_ITEMS_SHOWN} (vezi analiza.json)")
    return out


def _signed(bani: int) -> str:
    """Suma cu semn explicit („+1,00 Lei” / „-1,00 Lei”), pentru descompunerea cifrei principale."""
    return ("+" if bani >= 0 else "") + format_lei(bani)


def _orders_lines(summary: dict) -> list[str]:
    """Capul rezumatului: câte comenzi și cum s-au încheiat."""
    meta, orders = summary["meta"], summary["orders"]
    return [
        "=" * 64,
        "CHELTUIELI eMAG — REZUMAT",
        "=" * 64,
        f"Comenzi vizibile în cont: {orders['total']} (prima: {meta['first_order']}, ultima: {meta['last_order']})",
        f"  păstrate integral: {orders['kept_all']} | păstrate parțial: {orders['kept_partial']} | "
        f"returnate integral: {orders['returned_all']} | anulate integral: {orders['cancelled_all']}",
        f"  în curs: {orders['in_progress']} | doar servicii/asigurări: {orders['paid_only']} | necunoscute: {orders['unknown']}",
    ]


def _paid_head_lines(paid: dict) -> list[str]:
    """Cifra principală (plătit efectiv), descompusă: preț de listă, reduceri, transport și taxe, retururi cu credit, diferențe."""
    parts = [f"la preț de listă {format_lei(paid['list_kept_bani'])}", f"reduceri {format_lei(-paid['discounts_kept_bani'])}",
             f"transport și taxe {_signed(paid['fees_bani'])}"]
    if paid["credit_returns_bani"]:
        parts.append(f"retururi cu voucher sau sold eMAG {_signed(paid['credit_returns_bani'])}")
    if paid["refund_differences_bani"]:
        parts.append(f"diferențe la restituiri {_signed(paid['refund_differences_bani'])}")
    return [
        "",
        f"CÂT AI CHELTUIT: {format_lei(paid['spent_bani'])}",
        "  banii plătiți efectiv pe ce ai păstrat: după reduceri și vouchere, cu transportul și taxele, minus banii primiți înapoi",
        "  " + " | ".join(parts),
    ]


def _funnel_row(label: str, bani: int, units: int | None = None) -> str:
    """Un rând al lanțului: eticheta completată cu puncte până la _FUNNEL_LABEL_WIDTH, suma aliniată și, opțional, bucățile."""
    tail = f"  ({_units(units)})" if units is not None else ""
    return f"  {(label + ' ').ljust(_FUNNEL_LABEL_WIDTH, '.')} {format_lei(bani):>16}{tail}"


def _paid_funnel_lines(paid: dict) -> list[str]:
    """Lanțul în bani plătiți: comandat (după reduceri) − anulat − returnat − în curs + transport și taxe = plătit efectiv."""
    funnel = paid["funnel"]
    out = [
        "",
        "DE LA COMANDAT LA PLĂTIT (sume plătite, după reduceri)",
        _funnel_row("Comandat (după reduceri)", funnel["ordered_bani"], funnel["ordered_units"]),
        _funnel_row("- Anulat", funnel["cancelled_bani"], funnel["cancelled_units"]),
        _funnel_row("- Returnat (bani primiți înapoi)", funnel["returned_bani"], funnel["returned_units"]),
        _funnel_row("- În curs (nelivrat încă)", funnel["pending_bani"], funnel["pending_units"]),
    ]
    if funnel["unknown_bani"]:
        out.append(_funnel_row("- Status necunoscut", funnel["unknown_bani"], funnel["unknown_units"]))
    out.append(_funnel_row("+ Transport și taxe (livrate)", funnel["fees_bani"]))
    out.append(_funnel_row("= PLĂTIT EFECTIV PE CE AI PĂSTRAT", funnel["spent_bani"], funnel["spent_units"]))
    if paid["credit_returns_bani"]:
        out.append(f"  din care {format_lei(paid['credit_returns_bani'])} pe {_units(paid['credit_returns_units'])} returnate cu voucher "
                   "sau sold eMAG: banii nu s-au întors în cont, voucherul scade „Total plătit” al comenzii în care îl folosești")
    if paid["refund_differences_bani"]:
        out.append(f"  din care diferențe la restituiri {_signed(paid['refund_differences_bani'])}: partea plătită a produselor "
                   "returnate minus suma restituită afișată")
    return out


def _paid_breakdown_lines(summary: dict) -> list[str]:
    """Evidențiatele, achizițiile mari, categoriile (cu rândurile care nu sunt produse) și anii, în bani plătiți."""
    paid, big = summary["paid"], summary["big"]
    out = ["", "EVIDENȚIATE (plătit, după reduceri)"]
    for name, block in summary["highlights"].items():
        totals = block["totals"]
        out.append(f"  {name}: {format_lei(totals['paid_kept_bani'])} plătit pe {_units(totals['kept_units'])} păstrate "
                   f"(comandat {_units(totals['ordered_units'])}; returnat {_units(totals['returned_units'])}, anulat {_units(totals['cancelled_units'])})")
    out += [
        "",
        f"ACHIZIȚII PESTE {format_lei(big['threshold_bani'])} / bucată (pragul: prețul de listă pe bucată; sumele: plătite, după reduceri)",
        f"  păstrate: {_units(big['kept_units'])}, {format_lei(big['kept_paid_bani'])} | "
        f"returnate: {_units(big['returned_units'])}, {format_lei(big['returned_paid_bani'])} | "
        f"anulate: {_units(big['cancelled_units'])}, {format_lei(big['cancelled_paid_bani'])}",
        "",
        "PE CATEGORII (plătit efectiv; transportul și taxele au rândul lor)",
    ]
    rows = [(row["name"], row["paid_kept_bani"], _units(row["kept_units"])) for row in summary["by_category"] if row["paid_kept_bani"] > 0]
    rows += [(row["name"], row["bani"], None) for row in paid["extra_rows"]]
    width = min(_MAX_CATEGORY_NAME_WIDTH, max((len(name) for name, _, _ in rows), default=0))
    for name, bani, units in rows:
        out.append(f"  {name:<{width}} {format_lei(bani):>16}" + (f"  ({units})" if units else ""))
    out += ["", "PE ANI (plătit efectiv)"]
    for row in summary["by_year"]:
        out.append(f"  {row['year']}  {format_lei(row['spent_bani']):>16}  ({_counted(row['orders'], 'comandă', 'comenzi')})")
    return out


def _list_price_lines(summary: dict) -> list[str]:
    """Lanțul, evidențiatele, achizițiile mari, categoriile și anii la preț de listă (rezumatele vechi, fără `paid`)."""
    funnel, big = summary["funnel"], summary["big"]
    out = [
        "",
        "DE LA COMANDAT LA PĂSTRAT (doar produse)",
        f"  Comandat în total ........ {format_lei(funnel['ordered_bani']):>16}  ({_units(funnel['ordered_units'])})",
        f"  - Anulat ................. {format_lei(funnel['cancelled_bani']):>16}  ({_units(funnel['cancelled_units'])})",
        f"  - Returnat ............... {format_lei(funnel['returned_bani']):>16}  ({_units(funnel['returned_units'])})",
        f"  - În curs (nelivrat încă)  {format_lei(funnel['pending_bani']):>16}  ({_units(funnel['pending_units'])})",
    ]
    if funnel["unknown_bani"]:
        out.append(f"  - Status necunoscut ...... {format_lei(funnel['unknown_bani']):>16}  ({_units(funnel['unknown_units'])})")
    out += [f"  = PĂSTRAT (livrat/ridicat) {format_lei(funnel['kept_bani']):>16}  ({_units(funnel['kept_units'])})", "", "EVIDENȚIATE"]
    for name, block in summary["highlights"].items():
        totals = block["totals"]
        out.append(f"  {name}: {format_lei(totals['kept_bani'])} păstrat în {_units(totals['kept_units'])} "
                   f"(comandat {format_lei(totals['ordered_bani'])} / {_units(totals['ordered_units'])}; "
                   f"returnat {_units(totals['returned_units'])}, anulat {_units(totals['cancelled_units'])})")
    out += [
        "",
        f"ACHIZIȚII PESTE {format_lei(big['threshold_bani'])} / bucată",
        f"  păstrate: {_units(big['kept_units'])}, {format_lei(big['kept_bani'])} | "
        f"returnate: {_units(big['returned_units'])}, {format_lei(big['returned_bani'])} | "
        f"anulate: {_units(big['cancelled_units'])}, {format_lei(big['cancelled_bani'])}",
        "",
        "PE CATEGORII (păstrat)",
    ]
    for row in summary["by_category"]:
        if row["kept_bani"] > 0:
            out.append(f"  {row['name']:<34} {format_lei(row['kept_bani']):>16}  ({_units(row['kept_units'])})")
    out += ["", "PE ANI (păstrat)"]
    for row in summary["by_year"]:
        out.append(f"  {row['year']}  {format_lei(row['kept_bani']):>16}  ({row['orders']} comenzi)")
    return out


def _paid_check_lines(paid: dict) -> list[str]:
    """Reconcilierea plătitului efectiv cu „Total plătit” al blocurilor livrate (cu estimările numite ca atare)."""
    check = paid["reconciliation"]
    estimated = (f" (din care estimat {format_lei(check['estimated_refunds_bani'])} la "
                 f"{_counted(check['estimated_refunds'], 'retur', 'retururi')} fără sumă afișată sau cu produse nepotrivite)"
                 ) if check["estimated_refunds"] else ""
    out = [f"  Total plătit eMAG, blocuri livrate/ridicate ...... {format_lei(check['paid_delivered_bani'])}"]
    if check["rebuilt_blocks"]:
        out.append(f"    din care {check['rebuilt_blocks']} blocuri fără „Total plătit”, calculate din componente: {format_lei(check['rebuilt_bani'])}")
    out.append(f"  - bani primiți înapoi la retururi ................. {format_lei(check['cash_refunds_bani'])}{estimated}")
    if check["credit_returns_added_bani"]:
        out.append(f"  + retururi cu voucher sau sold, din blocuri marcate „anulat” {format_lei(check['credit_returns_added_bani'])}")
    out.append(f"  = plătit efectiv .................................. {format_lei(check['spent_bani'])}")
    return out


def _control_lines(summary: dict) -> list[str]:
    """Cifrele de control: reconcilierea (dacă analiza are `paid`), voucherele, transportul, retururile, ce a rămas în afară."""
    rec, paid = summary["reconciliation"], summary.get("paid")
    out = ["", "CIFRE DE CONTROL (blocuri livrate/ridicate)"]
    if paid:
        out.extend(_paid_check_lines(paid))
        out.append("  În „Total plătit” de mai sus: vouchere/reduceri "
                   f"{format_lei(rec['vouchers_delivered_bani'])} | transport {format_lei(rec['shipping_delivered_bani'])} | servicii/taxe {format_lei(rec['services_delivered_bani'])}")
    else:
        out.append(f"  Total plătit eMAG ........ {format_lei(rec['paid_delivered_bani'])}")
        out.append(f"  din care vouchere/reduceri {format_lei(rec['vouchers_delivered_bani'])} | transport {format_lei(rec['shipping_delivered_bani'])} | servicii/taxe {format_lei(rec['services_delivered_bani'])}")
    out.append(f"  Retururi: {rec['returns_total']} cereri, {rec['returns_completed']} finalizate "
               f"(restituit {format_lei(rec['refunds_bani'])}), {rec['returns_cancelled']} anulate, {rec['returns_pending']} fără rezultat")
    if paid:
        funnel, check = summary["funnel"], paid["reconciliation"]
        out.append(f"  La preț de listă, înainte de reduceri: comandat {format_lei(funnel['ordered_bani'])}, păstrat {format_lei(funnel['kept_bani'])}")
        outside = [f"în curs {format_lei(check['in_progress_bani'])}", f"plătite fără livrare {format_lei(check['paid_only_bani'])}"]
        if check["unknown_bani"]:
            outside.append(f"status necunoscut {format_lei(check['unknown_bani'])}")
        out.append("  În afara calculului: " + ", ".join(outside))
    return out


def build_summary_text(summary: dict) -> str:
    """Rezumatul complet, ca text cu mai multe rânduri: în bani plătiți dacă analiza are `paid`, altfel la preț de listă."""
    out = _orders_lines(summary)
    paid = summary.get("paid")
    if paid:
        out += _paid_head_lines(paid) + _paid_funnel_lines(paid) + _paid_breakdown_lines(summary)
    else:
        out += _list_price_lines(summary)
    out.extend(_control_lines(summary))
    history = summary.get("price_history")
    if history:
        out.extend(_price_history_lines(history))
    out.extend(_warning_lines(summary))
    return "\n".join(out)
