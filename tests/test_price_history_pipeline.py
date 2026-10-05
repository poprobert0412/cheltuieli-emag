"""Teste pentru istoricul prețurilor în fluxul complet: analiză, CSV, rezumat.txt, analiza.json, --din-cache, demo.

Toate datele sunt inventate. Scriu doar în foldere temporare.
"""

import csv
import json
import shutil

import pytest

from emag_spend import block_status, run_pipeline, run_store, settings
from emag_spend.csv_export import write_lines_csv
from emag_spend.models import Item, Order, SellerBlock
from emag_spend.price_history_csv import write_price_history_csv
from emag_spend.run_pipeline import RunOptions, run
from emag_spend.spend_analysis import analyze
from emag_spend.summary_text import build_summary_text
from emag_spend.text_normalize import normalize_text
from tests import scenario

TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
ORDER_LINK = "https://www.emag.ro/history/shoppingdetails/"
HOSTILE = ['=HYPERLINK("http://exemplu.invalid/x","Apasa")', "+SUM(1+1)", "-2+3", "@SUM(1+1)", "\t=1+1", "   =1+1"]


def _block(items, seller="Vanzator Alfa SRL", paid=None):
    total = sum(i.line_total_bani for i in items)
    return SellerBlock(seller, block_status.DELIVERED, "Produse livrate", False, items, total, [], 0, [], [],
                       total if paid is None else paid)


def _order(order_id, placed, items, **block_options):
    block = _block(items, **block_options)
    return Order(order_id, placed, placed, block.paid_bani, [block])


def _orders_with_repeats():
    """Scenariul mic + două cumpărări ale aceluiași model în culori diferite + un al doilea produs repetat."""
    return scenario.orders() + [
        _order("100200301", "2026-05-01T10:00", [Item("Husă Kelmor Fit, Alb", 3000, 1), Item("Cablu Test 2 m", 1000, 1)]),
        _order("100200302", "2026-06-01T10:00", [Item("Husă Kelmor Fit, Negru", 2500, 1), Item("Cablu Test 2 m", 1200, 1)]),
    ]


def _summary(orders=None, returns=None):
    orders = _orders_with_repeats() if orders is None else orders
    returns = scenario.returns() if returns is None else returns
    return analyze(orders, returns, scenario.classifier(), 50000, "2026-10-04 12:00",
                   highlight_categories=("Televizoare", "Alcool")).summary


def _read(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    return rows[0], [dict(zip(rows[0], row)) for row in rows[1:]]


# --- în analiză ---------------------------------------------------------------------------------

def test_analysis_has_the_price_history_and_it_matches_the_hand_calculation():
    history = _summary()["price_history"]
    by_name = {p["name"]: p for p in history["products"]}
    case = by_name["Husă Kelmor Fit, Negru"]
    assert case["color_variants"] is True and [p["unit_bani"] for p in case["purchases"]] == [3000, 2500]
    assert case["last_vs_prev_unit_bani"] == -500 and case["overpaid_vs_min_bani"] == 500
    cable = by_name["Cablu Test 2 m"]
    assert cable["last_vs_prev_unit_bani"] == 200 and cable["last_vs_prev_impact_bani"] == 200
    assert history["summary"]["products"] == 2 and history["summary"]["last_vs_prev"]["pricier_bani"] == 200
    assert history["summary"]["last_vs_prev"]["cheaper_bani"] == 500


def test_price_history_never_counts_more_units_than_the_funnel_keeps_and_is_json():
    summary = _summary()
    assert summary["price_history"]["summary"]["units"] <= summary["funnel"]["kept_units"]
    assert json.loads(json.dumps(summary["price_history"])) == summary["price_history"]


def test_the_small_scenario_keeps_its_hand_calculated_figures_and_has_no_repeated_product():
    summary = _summary(scenario.orders())
    funnel = summary["funnel"]
    assert (funnel["ordered_bani"], funnel["kept_bani"], funnel["returned_bani"]) == (409001, 313001, 18000)
    assert summary["price_history"]["products"] == []


# --- istoric_preturi.csv --------------------------------------------------------------------------

def test_price_history_csv_has_one_row_per_purchase_with_link_and_amounts(tmp_path):
    path = tmp_path / "istoric_preturi.csv"
    write_price_history_csv(path, _summary()["price_history"])
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    header, rows = _read(path)
    assert header == ["produs", "categorie", "data", "comanda", "link_comanda", "vanzator", "nume_in_comanda",
                      "bucati_pastrate", "pret_bucata_lei", "pret_minim_lei", "peste_minim_lei", "variante_culoare"]
    husa = [r for r in rows if r["produs"] == "Husă Kelmor Fit, Negru"]
    assert [(r["data"], r["comanda"], r["pret_bucata_lei"], r["pret_minim_lei"], r["peste_minim_lei"], r["variante_culoare"])
            for r in husa] == [("2026-05-01", "100200301", "30,00", "25,00", "5,00", "da"),
                               ("2026-06-01", "100200302", "25,00", "25,00", "0,00", "da")]
    assert [r["link_comanda"] for r in husa] == [ORDER_LINK + "100200301", ORDER_LINK + "100200302"]
    cablu = [r for r in rows if r["produs"] == "Cablu Test 2 m"]
    assert all(r["variante_culoare"] == "" for r in cablu) and len(rows) == 4


def test_price_history_csv_without_repeated_products_is_just_the_header(tmp_path):
    path = tmp_path / "istoric_preturi.csv"
    write_price_history_csv(path, _summary(scenario.orders())["price_history"])
    header, rows = _read(path)
    assert "produs" in header and rows == []


def test_price_history_csv_neutralizes_formulas_in_every_text_cell(tmp_path):
    orders = []
    for index, hostile in enumerate(HOSTILE):
        for month in (1, 2):
            orders.append(_order(f"{100300000 + index * 10 + month}", f"2026-0{month}-01T10:00",
                                 [Item(hostile + "x", 1000 * month, 1)], seller=hostile))
    history = analyze(orders, [], scenario.classifier(), 50000, "x").summary["price_history"]
    assert history["products"], "testul trebuie să aibă produse în istoric"
    path = tmp_path / "istoric_preturi.csv"
    write_price_history_csv(path, history)
    _, rows = _read(path)
    for row in rows:
        for column in ("produs", "categorie", "comanda", "link_comanda", "vanzator", "nume_in_comanda"):
            assert not row[column].startswith(TRIGGERS), (column, row[column])
    assert any(row["vanzator"].startswith("'") for row in rows)  # apostroful a fost pus, nu doar ocolit


def test_price_history_csv_leaves_the_link_empty_for_an_order_number_that_is_not_valid(tmp_path):
    orders = [_order("A1", "2026-01-01T10:00", [Item("Produs Test", 1000, 1)]),
              _order("../x", "2026-02-01T10:00", [Item("Produs Test", 1100, 1)])]
    path = tmp_path / "istoric_preturi.csv"
    write_price_history_csv(path, analyze(orders, [], scenario.classifier(), 50000, "x").summary["price_history"])
    _, rows = _read(path)
    assert [r["link_comanda"] for r in rows] == ["", ""]


# --- rezumat.txt -------------------------------------------------------------------------------------

def _text(summary=None):
    return build_summary_text(summary or _summary())


def test_summary_text_has_the_price_section_with_cheaper_and_pricier_wording_and_one_caveat():
    text = _text()
    assert "preturi la acelasi produs" in normalize_text(text)
    assert "  2 produse, 4 cumpărări, 4 buc" in text
    assert "mai scump cu 2,00 Lei" in text and "mai ieftin cu 5,00 Lei" in text
    assert "ai câștigat" not in text and text.count("ai pierdut") == 1  # singura apariție e în avertismentul de interpretare
    assert text.count("Atenție: prețurile includ promoții") == 1


def test_summary_text_says_so_when_no_product_was_bought_twice():
    text = _text(_summary(scenario.orders()))
    assert "niciun produs păstrat nu a fost cumpărat în două sau mai multe comenzi" in text


def test_summary_text_lists_only_the_top_products_and_points_to_the_csv():
    orders = []
    for i in range(14):  # 14 produse repetate, cu diferențe de preț din ce în ce mai mari
        orders.append(_order(f"{100400000 + i * 2}", "2026-01-01T10:00", [Item(f"Produs Mare {i:02d}", 1000, 1)]))
        orders.append(_order(f"{100400001 + i * 2}", "2026-02-01T10:00", [Item(f"Produs Mare {i:02d}", 1000 + 100 * (i + 1), 1)]))
    text = _text(_summary(orders))
    assert text.count("    - Produs Mare") == 10 and "... și încă 4 (vezi istoric_preturi.csv)" in text
    assert text.index("Produs Mare 13") < text.index("Produs Mare 04")  # cele mai mari diferențe întâi


def test_summary_text_shows_the_two_sums_and_the_order_link_under_a_header_mismatch_row():
    orders = _orders_with_repeats()
    orders[-1].header_total_bani += 777  # comanda 100200302: produse 37,00 Lei, antet 44,77 Lei
    text = _text(_summary(orders))
    assert "AVERTISMENTE: 1" in text
    assert "Comenzi la care totalul din antet nu e egal cu suma blocurilor: 1" in text
    assert "comanda 100200302 (2026-06-01): total din antet 44,77 Lei, suma blocurilor 37,00 Lei" in text
    assert text.count(ORDER_LINK) == 1 and f"\n      {ORDER_LINK}100200302\n" in text + "\n"


def test_summary_text_gives_no_link_for_an_order_number_that_is_not_valid():
    orders = scenario.orders()
    orders[6].header_total_bani += 777  # comanda „G”: litere, nu număr de comandă real
    text = _text(_summary(orders))
    assert "Comenzi la care totalul din antet nu e egal cu suma blocurilor: 1" in text and ORDER_LINK not in text


def test_summary_text_shows_links_for_numeric_order_numbers_in_the_warning_lines():
    orders = _orders_with_repeats()
    orders[-1].blocks[0].paid_bani = None
    orders[-1].warnings = [f"comanda {orders[-1].order_id}, Vanzator Alfa SRL: lipsește 'Total platit'"]
    text = _text(_summary(orders))
    assert f"      {ORDER_LINK}100200302" in text
    assert "Comenzi la care lipsește „Total plătit”: 1" in text


def test_summary_text_of_an_old_report_without_the_new_keys_still_works_and_links_orders_in_the_flat_list():
    summary = _summary(_orders_with_repeats())
    for key in ("price_history", "warnings_detail"):
        summary.pop(key)
    summary["warnings"] = ["comanda 100200302, Vanzator Alfa SRL: niciun produs găsit", "2 produse necategorizate (adaugă reguli)"]
    text = build_summary_text(summary)
    assert "PREȚURI LA ACELAȘI PRODUS" not in text
    assert "AVERTISMENTE: 2" in text and f"      {ORDER_LINK}100200302" in text
    assert text.count(ORDER_LINK) == 1


def test_summary_text_caps_the_rows_of_a_long_warning_group():
    orders = [_order(f"{100500000 + i}", "2026-01-01T10:00", [Item("Produs Test", 1000, 1)], paid=1000) for i in range(20)]
    for order in orders:
        order.header_total_bani += 100  # 20 de comenzi cu antetul diferit
    text = _text(_summary(orders, []))
    assert "Comenzi la care totalul din antet nu e egal cu suma blocurilor: 20" in text
    assert text.count(ORDER_LINK) == 15 and "... și încă 5 (vezi analiza.json)" in text


# --- fișierul produse.csv ---------------------------------------------------------------------------

def test_products_csv_has_the_order_link_column_right_after_the_order_number(tmp_path):
    lines = analyze(_orders_with_repeats(), scenario.returns(), scenario.classifier(), 50000, "x").lines
    write_lines_csv(tmp_path / "produse.csv", lines, 50000)
    header, rows = _read(tmp_path / "produse.csv")
    assert header[:2] == ["comanda", "link_comanda"]
    by_order = {r["comanda"]: r["link_comanda"] for r in rows}
    assert by_order["100200301"] == ORDER_LINK + "100200301"
    assert by_order["A"] == "" and by_order["G"] == ""  # numerele inventate cu litere nu produc link


# --- fluxul complet ---------------------------------------------------------------------------------

def _cache(tmp_path, orders=None, returns=None):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, orders or _orders_with_repeats())
    run_store.save_returns(cache, returns or scenario.returns())
    return cache


def test_pipeline_from_cache_writes_the_price_history_csv_and_the_new_json_keys(tmp_path):
    run_dir = run(RunOptions(from_cache=_cache(tmp_path), output_dir=tmp_path / "out"))
    assert (run_dir / "istoric_preturi.csv").stat().st_size > 0
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert {"price_history", "warnings_detail"} <= set(analiza)
    assert analiza["price_history"]["summary"]["products"] == 2
    assert analiza["funnel"]["kept_bani"] == 313001 + 3000 + 1000 + 2500 + 1200
    text = (run_dir / "rezumat.txt").read_text(encoding="utf-8")
    assert "PREȚURI LA ACELAȘI PRODUS" in text
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    assert info["culorile_produselor"].replace("\\", "/") == "config/culori.json"
    assert info["textele_avertismentelor"].replace("\\", "/") == "config/avertismente.json"


def test_an_old_run_folder_without_the_new_files_reloads_with_the_new_outputs(tmp_path):
    cache = _cache(tmp_path, scenario.orders(), scenario.returns())
    (cache / "analiza.json").write_text('{"funnel": {}, "warnings": []}', encoding="utf-8")  # raport vechi, fără chei noi
    (cache / "rezumat.txt").write_text("vechi", encoding="utf-8")
    run_dir = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out"))
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert analiza["price_history"]["products"] == []
    assert all(group["count"] == len(group["items"]) for group in analiza["warnings_detail"])
    assert analiza["funnel"]["kept_bani"] == 313001
    assert (run_dir / "istoric_preturi.csv").exists()
    assert (cache / "rezumat.txt").read_text(encoding="utf-8") == "vechi"  # folderul vechi nu e atins


def test_a_second_pass_from_the_cache_of_a_run_gives_the_same_new_sections(tmp_path):
    first = run(RunOptions(from_cache=_cache(tmp_path), output_dir=tmp_path / "out1"))
    second = run(RunOptions(from_cache=first, output_dir=tmp_path / "out2"))
    one = json.loads((first / "analiza.json").read_text(encoding="utf-8"))
    two = json.loads((second / "analiza.json").read_text(encoding="utf-8"))
    assert one["price_history"] == two["price_history"] and one["warnings_detail"] == two["warnings_detail"]
    assert (first / "istoric_preturi.csv").read_bytes() == (second / "istoric_preturi.csv").read_bytes()


def test_demo_run_writes_a_price_history_csv_and_ignores_personal_category_rules(tmp_path, monkeypatch):
    rules_dir = tmp_path / "config"
    rules_dir.mkdir()
    shutil.copy(settings.CATEGORY_RULES_FILE, rules_dir / "categorii.json")
    personal = {"categories": [{"name": "Doar a mea", "patterns": ["."]}]}  # ar prinde ORICE produs, dacă ar fi folosită
    (rules_dir / settings.PERSONAL_CATEGORY_RULES_FILE_NAME).write_text(json.dumps(personal), encoding="utf-8")
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", rules_dir / "categorii.json")
    run_dir = run(RunOptions(demo=True, output_dir=tmp_path / "out", demo_data_js=tmp_path / "demo-data.js"))
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert "Doar a mea" not in {row["name"] for row in analiza["by_category"]}
    assert analiza["price_history"]["summary"]["products"] >= 10 and len(analiza["warnings_detail"]) == 5
    _, rows = _read(run_dir / "istoric_preturi.csv")
    assert len(rows) == analiza["price_history"]["summary"]["purchases"]
    cache_run = run(RunOptions(from_cache=run_dir, output_dir=tmp_path / "out2"))  # fără --demo: regulile personale se aplică
    again = json.loads((cache_run / "analiza.json").read_text(encoding="utf-8"))
    assert "Doar a mea" in {row["name"] for row in again["by_category"]}
    assert again["funnel"] == analiza["funnel"]  # categoriile nu schimbă nicio sumă


def test_run_info_says_whether_personal_category_rules_were_used(tmp_path, monkeypatch):
    rules_dir = tmp_path / "config"
    rules_dir.mkdir()
    shutil.copy(settings.CATEGORY_RULES_FILE, rules_dir / "categorii.json")
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", rules_dir / "categorii.json")
    cache = _cache(tmp_path, scenario.orders(), scenario.returns())
    without = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out1"))
    assert json.loads((without / "run_info.json").read_text(encoding="utf-8"))["reguli_personale"] is None
    personal = {"categories": [{"name": "Doar a mea", "patterns": ["rucsac"]}]}
    (rules_dir / settings.PERSONAL_CATEGORY_RULES_FILE_NAME).write_text(json.dumps(personal), encoding="utf-8")
    with_personal = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out2"))
    assert json.loads((with_personal / "run_info.json").read_text(encoding="utf-8"))["reguli_personale"] == "categorii.personal.json"
    demo = run(RunOptions(demo=True, output_dir=tmp_path / "out3", demo_data_js=tmp_path / "demo-data.js"))
    assert json.loads((demo / "run_info.json").read_text(encoding="utf-8"))["reguli_personale"] is None
