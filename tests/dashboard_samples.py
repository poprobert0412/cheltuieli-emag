"""Seturi de date INVENTATE pentru testele componentei dashboard (nu e un fișier de teste).

Primește: nimic. Dă înapoi rezumate de analiză (`Analysis.summary`) de felurile:
demonstrativ (mare, ca în site), mic (scenariul cu cifre verificabile cu mâna), gol
(un cont fără comenzi, produs de aceeași `analyze()`), ostil (nume cu HTML, nume
foarte lungi, chei periculoase, sute de linii), „cu extra” (prețuri la același produs și
avertismente pe grupe scrise de mână, cu cifre inventate), „vechi” (fără cheile noi) și
„cu linkuri ostile” (numere de comandă și adrese de retur care NU au voie să devină link).
Ce NU face: nu pornește browserul și nu scrie fișiere. Toate datele sunt inventate.
"""

import copy
import importlib

from emag_spend import settings
from emag_spend.classifier import Classifier
from emag_spend.site_demo_writer import DEMO_META_KEY
from emag_spend.spend_analysis import analyze
from tests import scenario

THRESHOLD_BANI = 50000
GENERATED_AT = "2026-10-04 12:00"
HOSTILE_ALERT = "<script>window.__pwned = 1</script>"
HOSTILE_IMG = '<img src=x onerror="window.__pwned = 1">'
# Numere „de comandă” care NU sunt 3–15 cifre ASCII: nu au voie să producă niciodată un link.
HOSTILE_ORDER_IDS = ["../../x", "12a45", "12", "1" * 16, "123?x=1", "javascript:alert(1)", "١٢٣٤٥٦", " 123456", "123456\n"]
LONG_NAME_LENGTH = 3000
MANY_BIG_ITEMS = 400  # peste 3 pagini de câte 100 de rânduri


def without_demo_flag(summary: dict) -> dict:
    """Copie a analizei fără `meta.demo`: testele de randare și de linkuri au nevoie de date care se poartă ca ale unui cont real.

    Cu marcajul, raportul arată bannerul „date de demonstrație" și lasă numerele de comandă text simplu (nu există pe eMAG);
    comportamentul acesta se testează separat, cu `flagged_demo_summary()`.
    """
    plain = copy.deepcopy(summary)
    plain["meta"].pop(DEMO_META_KEY, None)
    return plain


def demo_summary() -> dict:
    """Analiza datelor demonstrative (aceleași cifre ca în site), FĂRĂ marcajul `meta.demo`: vezi `without_demo_flag`."""
    return without_demo_flag(flagged_demo_summary())


def flagged_demo_summary() -> dict:
    """Analiza datelor demonstrative exact cum o scrie programul la `--demo`, cu `meta.demo = true`.

    Folosește generatorul agentului DEMO (`site_demo_writer.build_demo_summary`) și, dacă
    nu există, generatorul de comenzi din `emag_spend.demo_data` sau `tests.demo_data`.
    """
    try:
        return importlib.import_module("emag_spend.site_demo_writer").build_demo_summary()
    except (ImportError, AttributeError):
        pass
    for module in ("emag_spend.demo_data", "tests.demo_data"):
        try:
            generator = importlib.import_module(module).demo_orders_and_returns
        except (ImportError, AttributeError):
            continue
        orders, returns = generator()
        return _analyze(orders, returns, settings.HIGHLIGHT_CATEGORIES)
    raise RuntimeError("nu găsesc niciun generator de date demonstrative")


def small_summary() -> dict:
    """Scenariul mic din tests/scenario.py: 7 comenzi, cifre verificabile cu mâna."""
    return _analyze(scenario.orders(), scenario.returns(), ("Televizoare", "Alcool"), scenario.classifier())


def empty_summary() -> dict:
    """Un cont fără nicio comandă, exact cum îl produce `analyze()`."""
    return _analyze([], [], ())


def _analyze(orders, returns, highlights, classifier=None) -> dict:
    """Rulează analiza reală, cu pragul și ora fixe ale testelor."""
    # include_personal=False: regulile personale ale unui om nu au voie să influențeze testele (altfel rezultatul depinde de calculator)
    classifier = classifier or Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    return analyze(orders, returns, classifier, THRESHOLD_BANI, GENERATED_AT, highlight_categories=highlights).summary


def _price_product(key, name, category, purchases, color_variants=False) -> dict:
    """Un produs din `price_history`, cu toate câmpurile derivate calculate din cumpărări (aceleași reguli ca emag_spend/price_history.py).

    `purchases` = listă de (data, comandă, vânzător, nume în comandă, bucăți, preț pe bucată în bani), în ordine cronologică.
    """
    rows = [{"date": d, "order_id": o, "seller": v, "name": n, "qty": q, "unit_bani": u} for d, o, v, n, q, u in purchases]
    units = [r["unit_bani"] for r in rows]
    previous, last = units[-2], units[-1]
    minimum = min(units)
    return {
        "key": key, "name": name, "category": category, "purchases": rows,
        "kept_units": sum(r["qty"] for r in rows), "first_unit_bani": units[0], "last_unit_bani": last,
        "min_unit_bani": minimum, "max_unit_bani": max(units),
        "last_vs_prev_unit_bani": last - previous,
        "last_vs_prev_pct": round((last - previous) / previous * 100, 1) if previous else None,
        "last_vs_prev_impact_bani": (last - previous) * rows[-1]["qty"],
        "overpaid_vs_min_bani": sum((r["unit_bani"] - minimum) * r["qty"] for r in rows),
        "color_variants": color_variants,
    }


def _price_history(products: list[dict]) -> dict:
    """Blocul `price_history` complet (rezumat + produse, descrescător după „plătit peste minim”) din produse deja făcute."""
    ordered = sorted(products, key=lambda p: -p["overpaid_vs_min_bani"])
    pricier = [p for p in ordered if p["last_vs_prev_unit_bani"] > 0]
    cheaper = [p for p in ordered if p["last_vs_prev_unit_bani"] < 0]
    return {
        "summary": {
            "products": len(ordered), "purchases": sum(len(p["purchases"]) for p in ordered),
            "units": sum(p["kept_units"] for p in ordered), "overpaid_vs_min_bani": sum(p["overpaid_vs_min_bani"] for p in ordered),
            "last_vs_prev": {
                "cheaper_products": len(cheaper), "pricier_products": len(pricier),
                "same_products": len(ordered) - len(cheaper) - len(pricier),
                "cheaper_bani": -sum(p["last_vs_prev_impact_bani"] for p in cheaper),
                "pricier_bani": sum(p["last_vs_prev_impact_bani"] for p in pricier),
            },
        },
        "products": ordered,
    }


def _warning_item(order_ids, text, *, return_id=None, return_url=None, seller=None, status=None, placed_at=None) -> dict:
    """Un rând dintr-o grupă `warnings_detail` (schema din emag_spend/warning_details.py)."""
    return {"order_ids": order_ids, "return_id": return_id, "seller": seller, "status": status, "placed_at": placed_at,
            "text": text, "return_url": return_url}


def _warning_group(kind, title, explanation, affects, todo, items) -> dict:
    """O grupă `warnings_detail`, cu `count` = numărul rândurilor."""
    return {"kind": kind, "title": title, "explanation": explanation, "affects_totals": affects, "what_to_do": todo,
            "count": len(items), "items": items}


def extras_summary() -> dict:
    """Scenariul mic + `price_history` și `warnings_detail` scrise de mână (cifre INVENTATE, nicio dată reală).

    Patru produse repetate (unul scumpit, unul ieftinit cu culori diferite și o dată lipsă, unul neschimbat, unul cu diacritice)
    și patru grupe de avertismente: unul cu retur (cu adresă), unul cu mai multe comenzi, unul cu „eMAG” în text.
    """
    data = copy.deepcopy(small_summary())
    data["price_history"] = _price_history([
        _price_product("cafea boabe aroma test 1 kg", "Cafea boabe Aroma Test 1 kg", "Alimente", [
            ("2023-01-10", "100000101", "eMAG", "Cafea boabe Aroma Test 1 kg", 1, 5000),
            ("2024-02-12", "100000202", "Magazin Test SRL", "Cafea boabe Aroma Test 1 kg", 2, 4500),
            ("2025-03-14", "100000303", "eMAG", "Cafea boabe Aroma Test 1 kg", 1, 5500)]),
        _price_product("mouse wireless test m1", "Mouse wireless Test M1, negru", "Periferice", [
            (None, "100000404", "eMAG", "Mouse wireless Test M1, alb", 1, 12000),
            ("2025-06-01", "100000505", "eMAG", "Mouse wireless Test M1, negru", 1, 9000)], color_variants=True),
        _price_product("baterii test aa", "Baterii Test AA, set 20 buc", "Casă", [
            ("2024-04-01", "100000606", "eMAG", "Baterii Test AA, set 20 buc", 1, 2000),
            ("2025-04-01", "100000707", "eMAG", "Baterii Test AA, set 20 buc", 1, 2000)]),
        _price_product("sampon test 400 ml", "Șampon Test 400 ml", "Cosmetice", [
            ("2025-01-05", "100000808", "eMAG", "Șampon Test 400 ml", 3, 3000),
            ("2025-09-05", "100000909", "eMAG", "Șampon Test 400 ml", 1, 2400)]),
    ])
    data["warnings_detail"] = [
        _warning_group("missing_paid_total", "Comenzi la care lipsește „Total plătit”", "Pagina comenzii nu arată suma plătită.", False,
                       "Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo.", [
                           _warning_item(["100000401"], "Vânzător Test SRL: blocul nu afișează „Total plătit” (livrat sau ridicat)",
                                         seller="Vânzător Test SRL", status="livrat sau ridicat", placed_at="2025-05-01")]),
        _warning_group("pending_return_without_result", "Retururi cerute, dar fără rezultat", "Cererea de retur nu are încă rezultat.", True,
                       "Verifică starea returului pe eMAG.", [
                           _warning_item(["100000501"], "cerere de retur pentru Produs Test; ultimul pas înregistrat: Recepționare produs",
                                         return_id="3000001", return_url="https://www.emag.ro/user/return-history/1/3000001",
                                         status="Recepționare produs", placed_at="2025-07-01")]),
        _warning_group("header_total_mismatch", "Comenzi la care totalul din antet nu e egal cu suma blocurilor",
                       "Totalul din antet diferă de suma blocurilor.", False, "Verifică totalul comenzii pe eMAG.", [
                           _warning_item(["100000601"], "total din antet 110,39 Lei, suma blocurilor 104,89 Lei", placed_at="2024-10-08"),
                           _warning_item(["100000701"], "total din antet 89,79 Lei, suma blocurilor 54,89 Lei", placed_at="2025-09-10")]),
        _warning_group("other", "Alte avertismente", "Mesaje de la eMAG care nu intră în celelalte grupe.", False,
                       "Citește fiecare rând; eMAG poate schimba paginile.", [_warning_item([], "2 produse necategorizate")]),
    ]
    return data


def strip_paid(summary: dict) -> dict:
    """Copie a analizei fără nimic din „plătit efectiv” (cheia `paid` și câmpurile plătite și de link de pe rânduri): un analiza.json vechi."""
    data = copy.deepcopy(summary)
    data.pop("paid", None)
    paid_key = lambda key: key.startswith("paid_") or key.endswith("_paid_bani") or key in ("spent_bani", "order_count")
    for row in data["by_category"] + data["by_year"] + data["by_seller"] + data["big"]["items"]:
        for key in [k for k in row if paid_key(k)]:
            del row[key]
    for row in data["top_products"] + data.get("uncategorized", []):
        for key in [k for k in row if paid_key(k) or k == "order_id"]:
            del row[key]
    for key in [k for k in data["big"] if paid_key(k)]:
        del data["big"][key]
    for block in data.get("highlights", {}).values():
        for row in [block["totals"]] + block["items"]:
            for key in [k for k in row if paid_key(k)]:
                del row[key]
    return data


def pre_paid_summary() -> dict:
    """Un analiza.json de dinainte de „plătit efectiv”, dar cu prețuri și avertismente pe grupe: `extras_summary` fără cheile plătite."""
    return strip_paid(extras_summary())


def legacy_summary() -> dict:
    """Un analiza.json de dinainte de prețuri, avertismente pe grupe și „plătit efectiv”: scenariul mic fără cheile noi (și cu avertismente text)."""
    data = strip_paid(small_summary())
    del data["price_history"], data["warnings_detail"]
    data["warnings"] = ["comanda 100000401, Vânzător Test SRL: lipsește 'Total platit'", "2 produse necategorizate (adaugă reguli în config/categorii.json)"]
    return data


def hostile_links_summary() -> dict:
    """`extras_summary` cu numere de comandă și adrese de retur care NU au voie să devină link.

    Fiecare număr din HOSTILE_ORDER_IDS apare în istoricul unui produs și într-un avertisment; adresele de retur sunt greșite în feluri
    diferite (altă gazdă, alt număr, „..”, parametri, javascript:, număr nevalid, fără adresă, rând nou la sfârșit, fără https).
    """
    data = extras_summary()
    product = data["price_history"]["products"][0]
    product["purchases"] = [dict(product["purchases"][0], order_id=hostile) for hostile in HOSTILE_ORDER_IDS]
    wrong_urls = [
        ("3000001", "https://alt-site.invalid/user/return-history/1/3000001"),
        ("3000001", "https://www.emag.ro/user/return-history/1/3000002"),
        ("3000001", "https://www.emag.ro/user/return-history/../3000001"),
        ("3000001", "https://www.emag.ro/user/return-history/1/3000001?x=1"),
        ("3000001", "javascript:alert(1)"),
        ("abc", "https://www.emag.ro/user/return-history/1/abc"),
        ("3000001", None),
        ("3000001", "https://www.emag.ro/user/return-history/1/3000001\n"),
        ("3000001", "http://www.emag.ro/user/return-history/1/3000001"),
    ]
    group = data["warnings_detail"][1]
    group["items"] = [_warning_item([hostile], "rând cu număr ostil", return_id=rid, return_url=url) for hostile, (rid, url) in zip(HOSTILE_ORDER_IDS, wrong_urls)]
    group["count"] = len(group["items"])
    return data


def hostile_summary() -> dict:
    """Date VALIDE ca schemă, dar cu text ostil în toate locurile în care apar nume.

    Nume cu <script> și <img onerror>, un nume de 3000 de caractere, o categorie care
    seamănă a atribut HTML, chei „__proto__” și „constructor” (în highlights și pe ani),
    zero-width și RTL, plus MANY_BIG_ITEMS linii peste prag pentru paginarea tabelului.
    """
    data = copy.deepcopy(demo_summary())
    long_name = "Produs-cu-nume-foarte-lung-" + "x" * LONG_NAME_LENGTH
    data["top_products"][0]["name"] = HOSTILE_ALERT
    data["top_products"][1]["name"] = long_name
    data["by_seller"][0]["seller"] = HOSTILE_IMG
    data["by_seller"][-1]["seller"] = long_name
    data["warnings"].insert(0, '<b onmouseover="window.__pwned = 1">avertisment</b> &amp; "ghilimele"')
    data["by_category"][0]["name"] = '"><svg onload=window.__pwned=1>'
    data["by_category"][1]["name"] = "Ștefan ‮ txet-lrt ​​" + "\U0001F600"
    first_series = data["by_year_category"]["series"][0]
    renamed = '<u>"serie"</u>'
    data["by_year_category"]["series"][0] = renamed
    for year_values in data["by_year_category"]["values"].values():
        year_values[renamed] = year_values.pop(first_series)
    if data["by_year"]:
        data["by_year"][0]["year"] = "<i>an</i>"
    # chei care, citite fără grijă dintr-un obiect, ar putea atinge prototipul
    any_highlight = next(iter(data["highlights"].values()))
    data["highlights"]["__proto__"] = copy.deepcopy(any_highlight)
    data["highlights"]["constructor"] = copy.deepcopy(any_highlight)
    data["highlights"]["<em>categorie</em>"] = copy.deepcopy(any_highlight)
    data["by_year_category"]["years"].append("__proto__")
    data["by_year_category"]["values"]["__proto__"] = {renamed: 123456}
    data["paid_only"].append({
        "order_id": "<x>", "date": "2026-01-01", "seller": HOSTILE_IMG, "names": [HOSTILE_ALERT, long_name],
        "products_bani": 1000, "paid_bani": 1000, "status_text": "Plata acceptata",
    })
    # prețuri la același produs și avertismente pe grupe: același text ostil, în toate locurile din care vin nume
    product = data["price_history"]["products"][0]
    product["name"] = HOSTILE_ALERT
    product["category"] = HOSTILE_IMG
    product["purchases"][0]["name"] = HOSTILE_IMG
    product["purchases"][0]["seller"] = long_name
    product["purchases"][-1]["order_id"] = "<x>" + "9" * LONG_NAME_LENGTH
    data["price_history"]["products"][1]["name"] = long_name
    group = data["warnings_detail"][0]
    group["title"] = HOSTILE_ALERT
    group["explanation"] = HOSTILE_IMG
    group["items"][0]["text"] = '<b onmouseover="window.__pwned = 1">rând</b>'
    group["items"][0]["order_ids"] = ["<x>", "9" * LONG_NAME_LENGTH]
    template = copy.deepcopy(data["big"]["items"][0]) if data["big"]["items"] else {
        "order_id": "1", "date": "2026-01-01", "name": "x", "seller": "eMAG", "category": "Diverse",
        "qty": 1, "unit_bani": 60000, "amount_bani": 60000, "state": "kept", "returned_from_cancelled": False,
    }
    states = ("kept", "returned", "cancelled", "pending", "kept")
    data["big"]["items"] = [
        dict(template, order_id=str(i), name=f"{HOSTILE_ALERT if i % 50 == 0 else 'Produs'} {i}", state=states[i % len(states)])
        for i in range(MANY_BIG_ITEMS)
    ]
    return data
