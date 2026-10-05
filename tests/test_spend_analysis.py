"""Teste pentru calculul cheltuielilor, pe scenariul inventat din tests/scenario.py."""

import copy

import pytest

from emag_spend.spend_analysis import analyze
from tests import scenario

THRESHOLD = 50000  # 500,00 lei


@pytest.fixture()
def result():
    return analyze(scenario.orders(), scenario.returns(), scenario.classifier(), THRESHOLD,
                   "2026-10-04 12:00", highlight_categories=("Televizoare", "Alcool"))


def test_funnel_numbers_match_hand_calculation(result):
    funnel = result.summary["funnel"]
    assert funnel["ordered_bani"] == 409001
    assert funnel["cancelled_bani"] == 70000
    assert funnel["returned_bani"] == 18000  # 1 husă (30) + rucsac marcat anulat (150)
    assert funnel["pending_bani"] == 8000
    assert funnel["kept_bani"] == 313001
    assert funnel["unknown_bani"] == 0
    assert (funnel["ordered_units"], funnel["cancelled_units"], funnel["returned_units"],
            funnel["pending_units"], funnel["kept_units"]) == (9, 1, 2, 1, 5)


def test_funnel_always_closes(result):
    f = result.summary["funnel"]
    assert f["ordered_bani"] == f["cancelled_bani"] + f["returned_bani"] + f["pending_bani"] + f["unknown_bani"] + f["kept_bani"]
    assert f["ordered_units"] == f["cancelled_units"] + f["returned_units"] + f["pending_units"] + f["unknown_units"] + f["kept_units"]


def test_insurance_paid_without_delivery_is_excluded_from_products(result):
    summary = result.summary
    assert [p["order_id"] for p in summary["paid_only"]] == ["F"]
    assert summary["paid_only"][0]["paid_bani"] == 50000
    assert all("Asigurare" not in row["name"] for row in summary["top_products"])


def test_pending_orders_are_listed_separately(result):
    assert [p["order_id"] for p in result.summary["in_progress"]] == ["E"]


def test_order_outcomes_add_up_to_total(result):
    o = result.summary["orders"]
    assert o["total"] == 7
    assert (o["kept_all"], o["kept_partial"], o["cancelled_all"], o["returned_all"], o["in_progress"], o["paid_only"]) == (2, 1, 1, 1, 1, 1)
    keys = ("kept_all", "kept_partial", "returned_all", "cancelled_all", "in_progress", "paid_only", "unknown", "no_items")
    assert sum(o[k] for k in keys) == o["total"]


def test_by_category_amounts(result):
    rows = {r["name"]: r for r in result.summary["by_category"]}
    assert rows["Televizoare"]["kept_bani"] == 200000 and rows["Televizoare"]["kept_units"] == 1
    assert rows["Alcool"]["kept_bani"] == 10000 and rows["Alcool"]["pending_bani"] == 8000
    assert rows["Alcool"]["ordered_units"] == 2
    assert rows["Diverse"]["returned_bani"] == 18000 and rows["Diverse"]["cancelled_bani"] == 70000
    assert sum(r["kept_bani"] for r in rows.values()) == result.summary["funnel"]["kept_bani"]


def test_highlight_categories_show_their_totals_and_items(result):
    highlights = result.summary["highlights"]
    assert highlights["Televizoare"]["totals"]["kept_units"] == 1
    assert [i["state"] for i in highlights["Alcool"]["items"]] == ["kept", "pending"]


def test_highlight_category_missing_from_the_rules_is_warned_not_silently_zero():
    # o categorie redenumită sau ștearsă din config/categorii.json nu are voie să apară ca „0,00 Lei” fără nicio vorbă
    result = analyze(scenario.orders(), scenario.returns(), scenario.classifier(), THRESHOLD,
                     "2026-10-04 12:00", highlight_categories=("Alcool", "Inexistenta"))
    highlights = result.summary["highlights"]
    assert highlights["Inexistenta"]["totals"]["kept_bani"] == 0 and highlights["Inexistenta"]["items"] == []
    warned = [w for w in result.summary["warnings"] if "evidențiată" in w]
    assert len(warned) == 1 and "«Inexistenta»" in warned[0] and "Alcool" not in warned[0]


def test_highlighting_the_default_category_needs_no_warning():
    result = analyze(scenario.orders(), scenario.returns(), scenario.classifier(), THRESHOLD,
                     "2026-10-04 12:00", highlight_categories=(scenario.classifier().default_category,))
    assert not any("evidențiată" in w for w in result.summary["warnings"])


def test_big_items_threshold_is_strictly_greater(result):
    big = result.summary["big"]
    names = [(r["name"], r["state"]) for r in big["items"]]
    assert ("Laptop Test", "kept") not in names  # exact 500,00 nu depășește
    assert ("Monitor Test", "kept") in names  # 500,01 depășește
    assert ("Televizor Alfa 55 inch", "kept") in names
    assert ("Ceva scump", "cancelled") in names
    assert len(names) == 3
    assert big["kept_bani"] == 250001 and big["kept_units"] == 2
    assert big["cancelled_bani"] == 70000
    assert big["items"][0]["name"] == "Televizor Alfa 55 inch"  # sortate după preț descrescător


def test_by_year_rows(result):
    rows = {r["year"]: r for r in result.summary["by_year"]}
    assert rows["2024"]["kept_bani"] == 210000 and rows["2024"]["orders"] == 1
    assert rows["2025"]["kept_bani"] == 3000 and rows["2025"]["orders"] == 2
    assert rows["2026"]["kept_bani"] == 100001 and rows["2026"]["orders"] == 4
    assert sum(r["orders"] for r in rows.values()) == 7


def test_year_category_matrix_sums_to_kept(result):
    matrix = result.summary["by_year_category"]
    total = sum(v for year in matrix["values"].values() for v in year.values())
    assert total == result.summary["funnel"]["kept_bani"]
    assert matrix["years"] == ["2024", "2025", "2026"]


def test_reconciliation_numbers(result):
    rec = result.summary["reconciliation"]
    assert rec["vouchers_delivered_bani"] == 5000
    assert rec["returns_total"] == 3 and rec["returns_completed"] == 2
    assert rec["returns_cancelled"] == 1 and rec["returns_pending"] == 0
    assert rec["refunds_bani"] == 18000
    assert rec["header_total_mismatches"] == []


def test_clean_scenario_has_no_warnings(result):
    assert result.summary["warnings"] == []
    assert result.summary["uncategorized_count"] == 0


def test_cancelled_return_leaves_the_product_kept(result):
    whisky = [l for l in result.lines if l.name == "Whisky Test 0.7L"][0]
    assert whisky.kept_qty == 1 and whisky.returned_qty == 0


def test_unknown_status_is_reported_not_counted_as_kept():
    orders = scenario.orders()
    orders[1].blocks[0].status = "UNKNOWN"
    orders[1].blocks[0].status_text = "ceva nou"
    result = analyze(orders, scenario.returns(), scenario.classifier(), THRESHOLD, "x")
    assert result.summary["funnel"]["unknown_bani"] > 0
    assert any("status necunoscut" in w for w in result.summary["warnings"])
    assert result.summary["orders"]["unknown"] == 1


def test_uncategorized_products_are_listed_and_warned():
    rules = copy.deepcopy(scenario.RULES)
    rules["categories"].pop()  # fără regula "Diverse"
    from emag_spend.classifier import Classifier
    result = analyze(scenario.orders(), scenario.returns(), Classifier(rules), THRESHOLD, "x")
    assert result.summary["uncategorized_count"] > 0
    assert any("necategorizate" in w for w in result.summary["warnings"])


def test_pending_return_warns_and_keeps_product():
    returns = scenario.returns()
    returns.append(type(returns[0])("R4", "/x", ["G"], ["Laptop Test"], ["Cerere inregistrata"], None, "", False, False))
    result = analyze(scenario.orders(), returns, scenario.classifier(), THRESHOLD, "x")
    assert result.summary["reconciliation"]["returns_pending"] == 1
    assert any("fără rezultat" in w for w in result.summary["warnings"])
    assert result.summary["funnel"]["kept_bani"] == 313001


def test_summary_is_json_serializable(result):
    import json
    json.dumps(result.summary)


def test_empty_input_does_not_crash():
    result = analyze([], [], scenario.classifier(), THRESHOLD, "x")
    assert result.summary["funnel"]["kept_bani"] == 0
    assert result.summary["orders"]["total"] == 0
    assert result.summary["meta"]["first_order"] is None


def test_top_products_are_ordered_by_total_kept_value_not_by_unit_price():
    # „Produse cu cea mai mare valoare păstrată”: un produs ieftin cumpărat des îl depășește pe unul scump cumpărat o dată
    from emag_spend import block_status
    from emag_spend.models import Item, Order, SellerBlock

    def block(items):
        total = sum(i.line_total_bani for i in items)
        return SellerBlock(seller="Vanzator Test", status=block_status.DELIVERED, status_text="livrat", has_storno=False,
                           items=items, products_total_bani=total, paid_bani=total, shipping_bani=0)

    orders = [
        Order("T1", "2026-01-01T10:00", "2026-01-01T10:00", 400000, [block([Item("Televizor scump de test", 400000, 1)])]),
        Order("T2", "2026-02-01T10:00", "2026-02-01T10:00", 453000, [block([Item("Detergent ieftin de test", 453000, 151)])]),  # 151 × 30 lei
    ]
    top = analyze(orders, [], scenario.classifier(), THRESHOLD, "2026-10-04 12:00").summary["top_products"]
    assert [p["name"] for p in top] == ["Detergent ieftin de test", "Televizor scump de test"]
    assert top[0]["bani"] == 453000 and top[0]["units"] == 151


def test_summary_has_the_new_keys_and_the_flat_warnings_list_next_to_the_grouped_one(result):
    summary = result.summary
    assert {"warnings", "warnings_detail", "price_history"} <= set(summary)
    assert summary["warnings_detail"] == [] and summary["price_history"]["products"] == []  # scenariul curat n-are ce grupa


def test_every_flat_warning_of_a_known_kind_is_in_exactly_one_group():
    returns = scenario.returns()
    returns.append(type(returns[0])("R4", "/user/return-history/1/R4", ["G"], ["Laptop Test"], ["Cerere inregistrata"], None, "", False, False))
    orders = scenario.orders()
    orders[6].header_total_bani += 500
    summary = analyze(orders, returns, scenario.classifier(), THRESHOLD, "x").summary
    kinds = {g["kind"]: g for g in summary["warnings_detail"]}
    assert set(kinds) == {"pending_return_without_result", "header_total_mismatch"}
    assert kinds["header_total_mismatch"]["items"][0]["text"] == "total din antet 1.005,01 Lei, suma blocurilor 1.000,01 Lei"
    assert len(summary["warnings"]) == 2 and summary["reconciliation"]["returns_pending"] == kinds["pending_return_without_result"]["count"] == 1


def test_analysis_uses_the_texts_and_colors_it_is_given_without_reading_any_config(monkeypatch):
    from emag_spend import spend_analysis
    from emag_spend.product_key import ColorWords
    from emag_spend.warning_details import load_warning_texts

    texts = load_warning_texts()
    texts["grupe"]["pending_return_without_result"]["title"] = "Titlu schimbat de test"

    def forbidden(*args, **kwargs):
        raise AssertionError("analyze() nu are voie să citească config/ când primește datele")

    monkeypatch.setattr(spend_analysis, "load_warning_texts", forbidden)
    monkeypatch.setattr(spend_analysis, "load_color_words", forbidden)
    returns = scenario.returns()
    returns.append(type(returns[0])("R4", "/x", ["G"], ["Laptop Test"], ["Cerere inregistrata"], None, "", False, False))
    summary = analyze(scenario.orders(), returns, scenario.classifier(), THRESHOLD, "x",
                      warning_texts=texts, color_words=ColorWords(["foarte-rar"])).summary
    assert [g["title"] for g in summary["warnings_detail"]] == ["Titlu schimbat de test"]

