"""Compatibilitatea cu fișierele vechi și cu ieșirile noi ale „plătit efectiv” (date INVENTATE, fără browser).

Verifică: un comenzi.json salvat înainte de `due_bani` se încarcă (cu „Total de plata” scos din taxe doar la identitate
exactă), parserul citește „Total de plata” separat, un analiza.json fără `paid` face același rezumat ca înainte, o linie
fără sumă plătită calculată valorează prețul de listă, CSV-ul are coloanele plătite, iar un config/restituiri.json greșit
oprește rularea înainte de colectare.
"""

import csv
import json

import pytest

from emag_spend import block_status, run_store
from emag_spend import run_pipeline
from emag_spend.csv_export import write_lines_csv
from emag_spend.html_lines import html_to_lines
from emag_spend.models import LineOutcome, to_dict
from emag_spend.order_parser import parse_order
from emag_spend.summary_text import build_summary_text
from tests import scenario
from tests.html_builders import order_page
from tests.test_platit_analiza import _block, _order, _paid


def _saved_order(other, paid=None, products=10000, vouchers=(-1000,), shipping=1099, services=(149,)):
    """Un bloc așa cum îl salva versiunea de dinainte de `due_bani` (cheia lipsește din fișier)."""
    block = to_dict(_block([("Produs Test", products, 1)], status=block_status.IN_PROGRESS, vouchers=vouchers, shipping=shipping,
                           services=services, paid=paid))
    block["other_bani"] = list(other)
    del block["due_bani"]
    return {"order_id": "200001", "placed_text": "1 oct 2026, 10:00", "placed_at": "2026-10-01T10:00", "header_total_bani": None,
            "blocks": [block], "warnings": []}


def _load(tmp_path, saved_orders):
    """Scrie comenzile ca într-un folder de rulare (fără retururi) și le reîncarcă prin run_store, ca la --din-cache."""
    (tmp_path / "comenzi.json").write_text(json.dumps(saved_orders, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "retururi.json").write_text("[]", encoding="utf-8")
    return run_store.load_run(tmp_path)[0]


def test_old_saved_amount_due_is_moved_out_of_the_fees_only_when_it_equals_the_whole_block(tmp_path):
    due = 10000 - 1000 + 1099 + 149
    (upgraded,) = _load(tmp_path, [_saved_order([due])])
    assert (upgraded.blocks[0].other_bani, upgraded.blocks[0].due_bani) == ([], due)
    (kept,) = _load(tmp_path, [_saved_order([250])])  # o taxă adevărată: nu e egală cu tot blocul, rămâne taxă
    assert (kept.blocks[0].other_bani, kept.blocks[0].due_bani) == ([250], None)
    (with_paid,) = _load(tmp_path, [_saved_order([due], paid=due)])  # cu „Total platit”, nimic de reparat
    assert with_paid.blocks[0].other_bani == [due]


def test_new_saved_files_keep_their_fields_through_save_and_load(tmp_path):
    orders, returns = scenario.orders(), scenario.returns()
    orders[4].blocks[0].due_bani = 8000
    run_store.save_orders(tmp_path, orders)
    run_store.save_returns(tmp_path, returns)
    loaded, _ = run_store.load_run(tmp_path)
    assert loaded == orders


def test_parser_reads_total_de_plata_as_the_amount_due_not_as_a_fee():
    block = dict(header="Produse vandute de ALFA TEST SRL si livrate de eMAG", seller_label="ALFA TEST SRL",
                 status=["Livrare anulata"], items=[("Produs Test Anulat", "84,99", 1)], total_products="84,99",
                 shipping="GRATUIT", to_pay="84,99")
    order = parse_order("489000040", html_to_lines(order_page("489000040", "9 feb 2025, 19:54", None, [block])))
    assert order.blocks[0].due_bani == 8499 and order.blocks[0].other_bani == [] and order.warnings == []


def test_line_without_a_computed_paid_amount_is_worth_its_list_price_and_a_negative_line_nothing():
    line = LineOutcome("1", None, "eMAG", "Produs Test", 2, 5000, block_status.DELIVERED, kept_qty=2)
    assert (line.paid_value_bani, line.kept_paid_bani, line.kept_list_bani) == (5000, 5000, 5000)
    discount = LineOutcome("1", None, "eMAG", "Reducere Test", 1, -700, block_status.DELIVERED, kept_qty=1)
    assert (discount.paid_value_bani, discount.kept_paid_bani, discount.kept_bani) == (0, 0, -700)


def test_old_analysis_without_paid_keeps_the_old_summary_text():
    summary = _paid(scenario.orders(), scenario.returns(), highlight_categories=("Televizoare", "Alcool")).summary
    old = {key: value for key, value in summary.items() if key != "paid"}
    text = build_summary_text(old)
    assert "DE LA COMANDAT LA PĂSTRAT" in text and "3.130,01 Lei" in text and "CÂT AI CHELTUIT" not in text
    new = build_summary_text(summary)
    assert "CÂT AI CHELTUIT: 3.080,01 Lei" in new and "PLĂTIT EFECTIV PE CE AI PĂSTRAT" in new
    assert "comandat 4.090,01 Lei, păstrat 3.130,01 Lei" in new  # prețul de listă rămâne, ca informație secundară


def test_csv_has_the_paid_columns_next_to_the_list_price_ones(tmp_path):
    analysis = _paid([_order("200002", "2025-01-01T10:00", _block([("=Televizor Test", 249999, 1)], vouchers=[-40000], shipping=2999))])
    path = tmp_path / "produse.csv"
    write_lines_csv(path, analysis.lines, 50000)
    (row,) = csv.DictReader(path.open(encoding="utf-8-sig"), delimiter=";")
    assert (row["valoare_linie_lei"], row["platit_linie_lei"], row["pastrat_lei"], row["platit_pastrat_lei"]) == (
        "2499,99", "2099,99", "2499,99", "2099,99")
    assert row["produs"] == "'=Televizor Test"  # neutralizarea formulelor rămâne pe celulele de text


def test_broken_refund_modes_file_stops_the_run_before_any_folder_is_created(tmp_path, monkeypatch):
    broken = tmp_path / "restituiri.json"
    broken.write_text('{"bani_inapoi": ["Mod Test"], "credit_emag": ["MOD TEST"]}', encoding="utf-8")  # același mod în ambele liste
    monkeypatch.setattr(run_pipeline, "REFUND_MODES_FILE", broken)
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="restituiri.json"):
        run_pipeline.run(run_pipeline.RunOptions(from_cache=cache, output_dir=out))
    assert not out.exists()


def test_run_info_names_the_refund_modes_file(tmp_path):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    run_dir = run_pipeline.run(run_pipeline.RunOptions(from_cache=cache, output_dir=tmp_path / "out"))
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    assert info["modurile_de_restituire"].replace("\\", "/") == "config/restituiri.json"
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert analiza["paid"]["spent_bani"] == 308001 and analiza["funnel"]["kept_bani"] == 313001
