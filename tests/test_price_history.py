"""Teste pentru istoricul prețurilor la același produs (price_history.py), pe linii inventate.

Numerele sunt alese ca rezultatele să se verifice cu mâna. Sumele sunt în bani.
"""

import json

import pytest

from emag_spend import block_status
from emag_spend.models import LineOutcome
from emag_spend.price_history import build_price_history
from emag_spend.product_key import load_color_words

COLORS = load_color_words()
PRODUCT_KEYS = {"key", "name", "category", "purchases", "kept_units", "first_unit_bani", "last_unit_bani", "min_unit_bani",
                "max_unit_bani", "last_vs_prev_unit_bani", "last_vs_prev_pct", "last_vs_prev_impact_bani",
                "overpaid_vs_min_bani", "color_variants"}
PURCHASE_KEYS = {"date", "order_id", "seller", "name", "qty", "unit_bani"}
SUMMARY_KEYS = {"products", "purchases", "units", "overpaid_vs_min_bani", "last_vs_prev"}
LAST_VS_PREV_KEYS = {"cheaper_products", "pricier_products", "same_products", "cheaper_bani", "pricier_bani"}

LONG_NAME = "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Negru"


def _line(order_id, date, name, total, qty=1, kept=None, seller="eMAG", category="Diverse", status=block_status.DELIVERED):
    """O linie de registru: `date` = "YYYY-MM-DD" (sau None), `kept` = unități păstrate (implicit toate)."""
    line = LineOutcome(order_id, f"{date}T10:00" if date else None, seller, name, qty, total, status,
                       category=category)
    line.kept_qty = qty if kept is None else kept
    return line


def _history(lines):
    return build_price_history(lines, COLORS)


def _one(lines):
    history = _history(lines)
    assert len(history["products"]) == 1, [p["key"] for p in history["products"]]
    return history["products"][0]


def test_same_model_in_two_colors_is_one_product_with_the_hand_calculated_numbers():
    product = _one([
        _line("101", "2024-01-10", "Husă Kelmor Fit, silicon, Alb", 3000),
        _line("102", "2024-06-01", "Husă Kelmor Fit, silicon, Negru", 2500),
    ])
    assert product["name"] == "Husă Kelmor Fit, silicon, Negru"  # cel mai recent nume
    assert [(p["date"], p["order_id"], p["qty"], p["unit_bani"]) for p in product["purchases"]] == [
        ("2024-01-10", "101", 1, 3000), ("2024-06-01", "102", 1, 2500)]
    assert (product["first_unit_bani"], product["last_unit_bani"], product["min_unit_bani"], product["max_unit_bani"]) == (
        3000, 2500, 2500, 3000)
    assert product["last_vs_prev_unit_bani"] == -500 and product["last_vs_prev_pct"] == -16.7
    assert product["last_vs_prev_impact_bani"] == -500 and product["overpaid_vs_min_bani"] == 500
    assert product["color_variants"] is True and product["kept_units"] == 2 and product["category"] == "Diverse"


def test_same_color_twice_is_not_a_color_variant():
    product = _one([_line("101", "2024-01-10", "Husă Kelmor Fit, Alb", 3000), _line("102", "2024-06-01", "Husă Kelmor Fit, Alb", 3000)])
    assert product["color_variants"] is False and product["last_vs_prev_unit_bani"] == 0 and product["last_vs_prev_pct"] == 0.0


def test_a_name_with_a_color_and_one_without_count_as_color_variants():
    product = _one([_line("101", "2024-01-10", "Husă Kelmor Fit", 3000), _line("102", "2024-06-01", "Husă Kelmor Fit, Alb", 3000)])
    assert product["color_variants"] is True


def test_different_screen_sizes_are_different_products():
    history = _history([
        _line("1", "2024-01-01", 'Televizor Smart Norvik 43" alb', 150000), _line("2", "2024-05-01", 'Televizor Smart Norvik 43" negru', 140000),
        _line("3", "2024-02-01", 'Televizor Smart Norvik 55" alb', 250000), _line("4", "2024-06-01", 'Televizor Smart Norvik 55" negru', 260000),
    ])
    names = sorted(p["name"] for p in history["products"])
    assert names == ['Televizor Smart Norvik 43" negru', 'Televizor Smart Norvik 55" negru']
    assert all(len(p["purchases"]) == 2 for p in history["products"])


def test_a_size_bought_once_does_not_join_the_other_size_to_make_a_history():
    history = _history([_line("1", "2024-01-01", 'Televizor Smart Norvik 43" alb', 150000), _line("2", "2024-05-01", 'Televizor Smart Norvik 55" alb', 250000)])
    assert history["products"] == [] and history["summary"]["products"] == 0


def test_different_capacities_are_different_products():
    history = _history([
        _line("1", "2024-01-01", "Stick USB Brenta 128GB", 4500), _line("2", "2024-02-01", "Stick USB Brenta 256GB", 7900),
        _line("3", "2024-03-01", "Stick USB Brenta 128GB", 4000), _line("4", "2024-04-01", "Stick USB Brenta 256GB", 7400),
    ])
    assert sorted(p["name"] for p in history["products"]) == ["Stick USB Brenta 128GB", "Stick USB Brenta 256GB"]
    by_name = {p["name"]: p for p in history["products"]}
    assert by_name["Stick USB Brenta 128GB"]["min_unit_bani"] == 4000 and by_name["Stick USB Brenta 256GB"]["min_unit_bani"] == 7400


def test_hand_calculated_product_with_a_partly_returned_line():
    product = _one([
        _line("1", "2024-01-05", "Cablu Test", 20000, qty=2),  # 100,00 / buc
        _line("2", "2024-03-05", "Cablu Test", 9000, qty=1),  # 90,00
        _line("3", "2024-05-05", "Cablu Test", 28500, qty=3, kept=2),  # 95,00 / buc, o bucată returnată: contează 2
    ])
    assert [p["qty"] for p in product["purchases"]] == [2, 1, 2]
    assert [p["unit_bani"] for p in product["purchases"]] == [10000, 9000, 9500]
    assert product["kept_units"] == 5
    assert (product["first_unit_bani"], product["last_unit_bani"], product["min_unit_bani"], product["max_unit_bani"]) == (
        10000, 9500, 9000, 10000)
    assert product["last_vs_prev_unit_bani"] == 500 and product["last_vs_prev_pct"] == 5.6  # 500 / 9000 = 5,56%
    assert product["last_vs_prev_impact_bani"] == 1000  # +5,00 Lei × 2 bucăți din ultima cumpărare
    assert product["overpaid_vs_min_bani"] == (10000 - 9000) * 2 + 0 + (9500 - 9000) * 2


@pytest.mark.parametrize("total, qty, expected_unit", [(1000, 3, 333), (1001, 3, 334), (1003, 2, 502), (999, 2, 500), (3000, 3, 1000)])
def test_unit_price_is_rounded_to_the_nearest_ban_with_integer_arithmetic(total, qty, expected_unit):
    product = _one([_line("1", "2024-01-01", "Produs Rotunjit", total, qty=qty), _line("2", "2024-02-01", "Produs Rotunjit", total, qty=qty)])
    assert [p["unit_bani"] for p in product["purchases"]] == [expected_unit, expected_unit]
    assert all(isinstance(p["unit_bani"], int) for p in product["purchases"])


@pytest.mark.parametrize("gift_total, gift_qty", [(0, 1), (0, 4), (-500, 1), (1, 3)])  # ultimul: 1 ban / 3 buc se rotunjește la 0
def test_lines_with_a_price_of_zero_or_less_are_ignored(gift_total, gift_qty):
    paid_then_gift = _history([_line("1", "2024-01-01", "Cadou Test", 3000), _line("2", "2024-02-01", "Cadou Test", gift_total, qty=gift_qty)])
    assert paid_then_gift["products"] == []  # cadoul nu face din produs unul „repetat”
    twice_paid_and_gift = _one([
        _line("1", "2024-01-01", "Cadou Test", 3000), _line("2", "2024-02-01", "Cadou Test", gift_total, qty=gift_qty),
        _line("3", "2024-03-01", "Cadou Test", 2800),
    ])
    assert [p["order_id"] for p in twice_paid_and_gift["purchases"]] == ["1", "3"] and twice_paid_and_gift["min_unit_bani"] == 2800


def test_one_order_alone_is_never_a_repeated_purchase_even_with_two_lines_of_the_same_product():
    history = _history([_line("1", "2024-01-01", "Baterii Test", 2000), _line("1", "2024-01-01", "Baterii Test", 2200)])
    assert history["products"] == []


def test_only_kept_units_make_a_purchase():
    assert _history([
        _line("1", "2024-01-01", "Produs Test", 2000),
        _line("2", "2024-02-01", "Produs Test", 2000, kept=0, status=block_status.CANCELLED),  # anulat
        _line("3", "2024-03-01", "Produs Test", 2000, kept=0),  # returnat integral
        _line("4", "2024-04-01", "Produs Test", 2000, kept=0, status=block_status.IN_PROGRESS),  # încă nelivrat
    ])["products"] == []


def test_purchases_are_chronological_whatever_the_input_order_and_undated_ones_come_first():
    product = _one([
        _line("100", "2024-03-01", "Produs Test", 3000),
        _line("99", "2024-03-01", "Produs Test", 2900),  # același minut: după numărul de comandă (99 < 100)
        _line("7", None, "Produs Test", 2500),  # fără dată: considerată cea mai veche
        _line("5", "2023-12-31", "Produs Test", 2700),
    ])
    assert [p["order_id"] for p in product["purchases"]] == ["7", "5", "99", "100"]
    assert [p["date"] for p in product["purchases"]] == [None, "2023-12-31", "2024-03-01", "2024-03-01"]
    assert product["first_unit_bani"] == 2500 and product["last_unit_bani"] == 3000


def test_last_versus_previous_compares_with_the_last_line_of_the_previous_order_not_the_same_order():
    product = _one([
        _line("1", "2024-01-01", "Produs Test", 5000),
        _line("2", "2024-02-01", "Produs Test", 4000),
        _line("3", "2024-03-01", "Produs Test, Alb", 3000, qty=2),  # două linii în ultima comandă
        _line("3", "2024-03-01", "Produs Test, Negru", 3600, qty=2),
    ])
    assert product["last_unit_bani"] == 1800 and product["last_vs_prev_unit_bani"] == 1800 - 4000
    assert product["last_vs_prev_impact_bani"] == (1800 - 4000) * 2  # unitățile ultimei linii cumpărate


def test_a_truncated_name_joins_the_product_with_the_full_name_and_the_full_name_is_displayed():
    product = _one([
        _line("1", "2024-01-01", LONG_NAME, 150000),
        _line("2", "2024-06-01", "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Ne [...]", 140000),  # mai nouă, trunchiată
    ])
    assert product["name"] == LONG_NAME  # nu numele trunchiat
    assert [p["order_id"] for p in product["purchases"]] == ["1", "2"]
    assert product["purchases"][1]["name"].endswith("[...]")  # numele original rămâne în cumpărare
    assert product["color_variants"] is False  # un nume trunchiat nu schimbă „variantele de culoare”


def test_a_truncated_name_with_another_color_still_joins_by_key_prefix():
    product = _one([
        _line("1", "2024-01-01", LONG_NAME, 150000),
        _line("2", "2024-06-01", "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Alb [...]", 140000),
    ])
    assert len(product["purchases"]) == 2


def test_a_truncated_name_that_fits_two_products_is_not_attached_to_either():
    base = "Telefon mobil Vexor X5, Dual SIM, "
    history = _history([
        _line("1", "2024-01-01", base + "128GB, Negru", 150000), _line("2", "2024-02-01", base + "128GB, Alb", 149000),
        _line("3", "2024-03-01", base + "256GB, Negru", 190000), _line("4", "2024-04-01", base + "256GB, Alb", 189000),
        _line("5", "2024-05-01", base + "[...]", 100000),  # prefixul se potrivește cu ambele capacități
    ])
    assert sorted(len(p["purchases"]) for p in history["products"]) == [2, 2]
    assert all(p["purchases"][-1]["order_id"] != "5" for p in history["products"])


def test_a_short_truncated_prefix_is_not_matched_at_all():
    assert _history([_line("1", "2024-01-01", LONG_NAME, 150000), _line("2", "2024-06-01", "Telefon [...]", 140000)])["products"] == []


def test_truncated_names_with_the_same_prefix_group_together_when_no_full_name_exists():
    prefix = "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM [...]"
    product = _one([_line("1", "2024-01-01", prefix, 150000), _line("2", "2024-06-01", prefix, 140000)])
    assert [p["order_id"] for p in product["purchases"]] == ["1", "2"] and product["name"] == prefix


def test_products_are_sorted_by_the_difference_to_the_minimum_then_by_key():
    history = _history([
        _line("1", "2024-01-01", "Produs Mic", 1000), _line("2", "2024-02-01", "Produs Mic", 1100),  # diferență 1,00
        _line("3", "2024-01-01", "Produs Mare", 10000), _line("4", "2024-02-01", "Produs Mare", 12000),  # diferență 20,00
        _line("5", "2024-01-01", "Produs Egal", 500), _line("6", "2024-02-01", "Produs Egal", 500),  # diferență 0
    ])
    assert [p["name"] for p in history["products"]] == ["Produs Mare", "Produs Mic", "Produs Egal"]
    assert [p["overpaid_vs_min_bani"] for p in history["products"]] == [2000, 100, 0]


def test_summary_adds_up_the_products_and_reports_impacts_as_positive_amounts():
    history = _history([
        _line("1", "2024-01-01", "Mai Ieftin", 5000, qty=2), _line("2", "2024-02-01", "Mai Ieftin", 4400, qty=2),  # −3,00 × 2 = −6,00
        _line("3", "2024-01-01", "Mai Scump", 1000), _line("4", "2024-02-01", "Mai Scump", 1250, qty=1),  # +2,50 × 1
        _line("5", "2024-01-01", "La Fel", 700, qty=3), _line("6", "2024-02-01", "La Fel", 700, qty=3),
    ])
    summary = history["summary"]
    assert (summary["products"], summary["purchases"], summary["units"]) == (3, 6, 2 + 2 + 1 + 1 + 3 + 3)
    assert summary["overpaid_vs_min_bani"] == sum(p["overpaid_vs_min_bani"] for p in history["products"])
    assert summary["last_vs_prev"] == {
        "cheaper_products": 1, "pricier_products": 1, "same_products": 1, "cheaper_bani": 600, "pricier_bani": 250}


def test_empty_input_gives_an_empty_history_with_zero_totals():
    history = _history([])
    assert history["products"] == []
    assert history["summary"] == {
        "products": 0, "purchases": 0, "units": 0, "overpaid_vs_min_bani": 0,
        "last_vs_prev": {"cheaper_products": 0, "pricier_products": 0, "same_products": 0, "cheaper_bani": 0, "pricier_bani": 0}}


def test_lines_with_an_empty_name_or_no_quantity_are_skipped_without_error():
    history = _history([
        _line("1", "2024-01-01", "", 1000), _line("2", "2024-02-01", " ,; ", 1000),
        _line("3", "2024-03-01", "Produs Test", 1000, qty=0, kept=0),
    ])
    assert history == _history([])


def test_result_has_exactly_the_documented_keys_and_is_json():
    history = _history([_line("1", "2024-01-01", "Produs Test", 1000), _line("2", "2024-02-01", "Produs Test", 1500)])
    assert set(history) == {"summary", "products"} and set(history["summary"]) == SUMMARY_KEYS
    assert set(history["summary"]["last_vs_prev"]) == LAST_VS_PREV_KEYS
    (product,) = history["products"]
    assert set(product) == PRODUCT_KEYS and all(set(p) == PURCHASE_KEYS for p in product["purchases"])
    assert json.loads(json.dumps(history)) == history
    assert isinstance(product["last_vs_prev_pct"], float) and isinstance(product["color_variants"], bool)


def test_input_lines_are_not_modified():
    lines = [_line("1", "2024-01-01", "Produs Test", 1000), _line("2", "2024-02-01", "Produs Test", 1500)]
    snapshot = [(l.kept_qty, l.returned_qty, l.line_total_bani, l.name) for l in lines]
    _history(lines)
    assert [(l.kept_qty, l.returned_qty, l.line_total_bani, l.name) for l in lines] == snapshot
