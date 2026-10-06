"""Teste pentru „plătit efectiv” (paid_totals.py prin analyze()): cifra principală, retururile și invarianții sumelor.

Toate comenzile, retururile, numele și sumele sunt INVENTATE. Invarianți: suma categoriilor (cu rândurile „Transport și taxe”,
„Retururi cu voucher sau sold”, „Diferențe la restituiri”) = plătit efectiv; un bloc fără retururi = exact „Total platit”;
reducerile alocate pe linii = reducerea blocului; nicio linie negativă; lanțul și anii se închid.
"""

import pytest

from emag_spend import block_status, warning_messages
from emag_spend.models import Item, Order, ReturnRequest, SellerBlock
from emag_spend.refund_modes import RefundModes, load_refund_modes
from emag_spend.spend_analysis import analyze
from tests import scenario

THRESHOLD = 50000
CASH = "Vreau banii inapoi"
VOUCHER = "Emitere voucher"


def _block(items, *, status=block_status.DELIVERED, vouchers=(), shipping=0, services=(), seller="eMAG", paid="auto"):
    """Un bloc inventat a cărui pagină se leagă (Total platit = componente), dacă nu se cere altfel."""
    lines = [Item(name, total, qty) for name, total, qty in items]
    products = sum(item.line_total_bani for item in lines)
    if paid == "auto":
        paid = 0 if status == block_status.CANCELLED else products + sum(vouchers) + shipping + sum(services)
    return SellerBlock(seller=seller, status=status, status_text=status, has_storno=False, items=lines, products_total_bani=products,
                       vouchers_bani=list(vouchers), shipping_bani=shipping, services_bani=list(services), paid_bani=paid)


def _order(order_id, placed_at, *blocks):
    """O comandă inventată; totalul din antet = suma „Total platit” a blocurilor."""
    return Order(order_id, placed_at, placed_at, sum(b.paid_bani or 0 for b in blocks), list(blocks))


def _return(return_id, order_id, names, refund, mode=CASH, completed=True):
    """Un retur inventat pe o comandă: finalizat (pasul „Restituire suma”) sau doar înregistrat."""
    return ReturnRequest(return_id, f"/user/return-history/1/{return_id}", [order_id], list(names),
                         ["Restituire suma"] if completed else ["Cerere inregistrata"], refund, mode, completed, False)


def _paid(orders, returns=(), **options):
    """Analiza completă a comenzilor inventate (rezultatul lui analyze(), cu cheia `paid` în summary)."""
    return analyze(orders, list(returns), scenario.classifier(), THRESHOLD, "2026-10-05 12:00", **options)


def _assert_invariants(analysis):
    """Invarianții care trebuie să țină la orice date."""
    summary, paid = analysis.summary, analysis.summary["paid"]
    spent = paid["spent_bani"]
    assert sum(c["paid_kept_bani"] for c in summary["by_category"]) + sum(r["bani"] for r in paid["extra_rows"]) == spent
    assert paid["products_kept_bani"] + paid["fees_bani"] + paid["credit_returns_bani"] + paid["refund_differences_bani"] == spent
    assert sum(y["spent_bani"] for y in summary["by_year"]) == spent
    f = paid["funnel"]
    assert f["ordered_bani"] - f["cancelled_bani"] - f["returned_bani"] - f["pending_bani"] - f["unknown_bani"] + f["fees_bani"] == spent
    for year in summary["by_year"]:
        assert (year["paid_ordered_bani"] - year["paid_cancelled_bani"] - year["paid_returned_bani"] - year["paid_pending_bani"]
                - year["paid_unknown_bani"] + year["paid_fees_bani"]) == year["spent_bani"], year["year"]
    rec = paid["reconciliation"]
    assert rec["paid_delivered_bani"] - rec["cash_refunds_bani"] + rec["credit_returns_added_bani"] == spent
    assert all(line.paid_value_bani >= 0 and line.kept_paid_bani >= 0 for line in analysis.lines)
    assert not any("lanțul sumelor" in w for w in summary["warnings"])
    if not any(r["bani"] < 0 for r in paid["extra_rows"]):
        matrix = paid["by_year_category"]["values"]
        assert sum(v for year in matrix.values() for v in year.values()) == spent


def test_block_without_returns_costs_exactly_its_total_platit_and_shipping_has_its_own_row():
    order = _order("100001", "2025-03-01T10:00", _block([("Televizor Test 55 inch", 249999, 1)], vouchers=[-40000], shipping=2999))
    analysis = _paid([order])
    paid = analysis.summary["paid"]
    assert paid["spent_bani"] == order.blocks[0].paid_bani == 212998
    assert paid["products_kept_bani"] == 209999 and paid["fees_bani"] == 2999
    assert paid["list_kept_bani"] == 249999 and paid["discounts_kept_bani"] == 40000
    assert [(r["key"], r["name"], r["bani"]) for r in paid["extra_rows"]] == [("fees", "Transport și taxe", 2999)]
    rows = {c["name"]: c for c in analysis.summary["by_category"]}
    assert rows["Televizoare"]["paid_kept_bani"] == 209999 and rows["Televizoare"]["kept_bani"] == 249999
    _assert_invariants(analysis)


def test_discounts_given_to_the_lines_add_up_to_the_discount_of_the_block():
    block = _block([("Whisky Test 0.7L", 12999, 3), ("Produs Diverse Test", 3333, 1), ("Alt Produs Test", 7, 1)], vouchers=[-1001, -500])
    analysis = _paid([_order("100002", "2025-04-01T10:00", block)])
    lines = analysis.lines
    assert sum(l.list_value_bani - l.paid_value_bani for l in lines) == 1501
    assert sum(l.paid_value_bani for l in lines) == block.paid_bani
    _assert_invariants(analysis)


def test_the_scenario_of_the_old_tests_spends_its_paid_totals_minus_the_refunds():
    analysis = _paid(scenario.orders(), scenario.returns(), highlight_categories=("Televizoare", "Alcool"))
    paid = analysis.summary["paid"]
    # A: 2.050,00 plătit; B: 60,00 plătit − 30,00 restituit; G: 1.000,01; D (marcat anulat, retur în bani) nu intră
    assert paid["spent_bani"] == 205000 + 3000 + 100001
    assert paid["reconciliation"]["cash_refunds_bani"] == 3000 and paid["refund_differences_bani"] == 0
    assert analysis.summary["funnel"]["kept_bani"] == 313001  # cheia veche rămâne la preț de listă
    highlights = analysis.summary["highlights"]
    assert highlights["Televizoare"]["totals"]["paid_kept_bani"] + highlights["Alcool"]["totals"]["paid_kept_bani"] < 210000
    _assert_invariants(analysis)


def test_cash_refund_lower_than_the_paid_part_leaves_the_difference_as_spent():
    order = _order("100003", "2025-05-01T10:00", _block([("Produs Test A", 11699, 1), ("Produs Test B", 5000, 1)], vouchers=[-3400], shipping=149))
    analysis = _paid([order], [_return("3000001", "100003", ["Produs Test A"], 9200)])
    paid = analysis.summary["paid"]
    line_a = next(l for l in analysis.lines if l.name == "Produs Test A")
    assert line_a.returned_paid_bani == 9317  # 116,99 − partea lui din 34,00 (proporțional cu prețul)
    assert paid["spent_bani"] == order.blocks[0].paid_bani - 9200
    assert paid["refund_differences_bani"] == 9317 - 9200
    assert {r["key"] for r in paid["extra_rows"]} == {"fees", "refund_differences"}
    _assert_invariants(analysis)


def test_cash_refund_without_an_amount_is_estimated_as_the_paid_part_and_counted_as_an_estimate():
    order = _order("100004", "2025-06-01T10:00", _block([("Produs Test", 20000, 2)], vouchers=[-2000]))
    analysis = _paid([order], [_return("3000002", "100004", ["Produs Test"], None)])
    rec = analysis.summary["paid"]["reconciliation"]
    assert rec["estimated_refunds"] == 1 and rec["estimated_refunds_bani"] == 9000 == rec["cash_refunds_bani"]
    assert analysis.summary["paid"]["spent_bani"] == 9000
    kinds = {g["kind"] for g in analysis.summary["warnings_detail"]}
    assert "completed_return_without_refund" in kinds
    _assert_invariants(analysis)


def test_voucher_refund_from_a_delivered_block_is_not_subtracted():
    order = _order("100005", "2025-07-01T10:00", _block([("Produs Test", 19999, 1)]))
    analysis = _paid([order], [_return("3000003", "100005", ["Produs Test"], 19999, mode=VOUCHER)])
    paid = analysis.summary["paid"]
    assert paid["spent_bani"] == 19999  # voucherul scade „Total platit” al comenzii în care e folosit: nu se scade și aici
    assert paid["credit_returns_bani"] == 19999 and paid["credit_returns_units"] == 1
    assert paid["products_kept_bani"] == 0 and paid["funnel"]["returned_bani"] == 0
    assert paid["reconciliation"]["credit_returns_delivered_bani"] == 19999
    _assert_invariants(analysis)


def test_voucher_refund_from_a_block_marked_cancelled_is_added_once():
    kept = _order("100006", "2025-08-01T10:00", _block([("Produs Păstrat Test", 50000, 1)], vouchers=[-25199]))
    returned = _order("100007", "2025-07-01T10:00", _block([("Produs Returnat Test", 27999, 1)], status=block_status.CANCELLED,
                                                           vouchers=[-2800], seller="Vânzător Test SRL"))
    analysis = _paid([kept, returned], [_return("3000004", "100007", ["Produs Returnat Test"], None, mode=VOUCHER)])
    paid = analysis.summary["paid"]
    # banii plătiți pe produsul returnat au devenit voucher, folosit apoi ca reducere: bani ieșiți din buzunar = 249,99 + 251,99
    assert paid["spent_bani"] == 24801 + 25199
    assert paid["reconciliation"]["credit_returns_added_bani"] == 25199
    _assert_invariants(analysis)


def test_cash_return_on_a_block_marked_cancelled_cancels_out_and_stays_outside():
    returned = _order("100008", "2025-09-01T10:00", _block([("Rucsac Test", 15000, 1)], status=block_status.CANCELLED, seller="Beta Test SRL"))
    analysis = _paid([returned], [_return("3000005", "100008", ["Rucsac Test"], 15000)])
    paid = analysis.summary["paid"]
    assert paid["spent_bani"] == 0
    assert paid["reconciliation"]["cancelled_cash_returns_bani"] == 15000 == paid["reconciliation"]["cancelled_cash_refunds_shown_bani"]
    _assert_invariants(analysis)


def test_unknown_refund_mode_is_treated_as_money_back_and_warned():
    order = _order("100009", "2025-10-01T10:00", _block([("Produs Test", 10000, 1)]))
    analysis = _paid([order], [_return("3000006", "100009", ["Produs Test"], 10000, mode="Mod Nou De Test")])
    assert analysis.summary["paid"]["spent_bani"] == 0
    expected = warning_messages.format_unknown_refund_mode("3000006", "Mod Nou De Test")
    assert expected in analysis.summary["warnings"]
    parsed = warning_messages.parse_order_warning(expected)
    assert parsed.return_id == "3000006" and parsed.affects_totals


def test_partially_matched_return_uses_the_estimate_and_keeps_the_rest_of_the_refund_outside():
    order = _order("100010", "2025-10-02T10:00", _block([("Produs Găsit Test", 10000, 1), ("Alt Produs Test", 5000, 1)]))
    analysis = _paid([order], [_return("3000007", "100010", ["Produs Găsit Test", "Produs Lipsă Din Comandă Test"], 14000)])
    rec = analysis.summary["paid"]["reconciliation"]
    assert rec["cash_refunds_bani"] == 10000 and rec["estimated_refunds"] == 1
    assert rec["unattributed_refunds_bani"] == 4000
    _assert_invariants(analysis)


def test_blocks_in_progress_paid_only_and_unknown_stay_outside_the_spent_total():
    orders = [
        _order("100011", "2026-01-01T10:00", _block([("Produs Livrat Test", 10000, 1)])),
        _order("100012", "2026-01-02T10:00", _block([("Produs În Curs Test", 20000, 1)], status=block_status.IN_PROGRESS, shipping=1499)),
        _order("100013", "2026-01-03T10:00", _block([("Asigurare Test", 30000, 1)], status=block_status.PAID_ONLY)),
        _order("100014", "2026-01-04T10:00", _block([("Produs Necunoscut Test", 40000, 1)], status=block_status.UNKNOWN)),
    ]
    analysis = _paid(orders)
    paid = analysis.summary["paid"]
    assert paid["spent_bani"] == 10000 and paid["fees_bani"] == 0
    assert (paid["funnel"]["pending_bani"], paid["funnel"]["unknown_bani"]) == (20000, 40000)
    rec = paid["reconciliation"]
    assert (rec["in_progress_bani"], rec["paid_only_bani"], rec["unknown_bani"]) == (21499, 30000, 40000)
    _assert_invariants(analysis)


def test_rows_carry_paid_amounts_next_to_list_prices_and_the_latest_order_for_links():
    first = _order("100015", "2024-01-01T10:00", _block([("Cafea Test 1 kg", 5000, 1)], vouchers=[-500]))
    second = _order("100016", "2025-01-01T10:00", _block([("Cafea Test 1 kg", 6000, 1)]))
    big = _order("100017", "2025-02-01T10:00", _block([("Monitor Test 27 inch", 80000, 1)], vouchers=[-10000]))
    summary = _paid([first, second, big]).summary
    top = {p["name"]: p for p in summary["top_products"]}
    assert top["Cafea Test 1 kg"]["paid_bani"] == 10500 and top["Cafea Test 1 kg"]["bani"] == 11000
    assert (top["Cafea Test 1 kg"]["order_id"], top["Cafea Test 1 kg"]["order_count"]) == ("100016", 2)
    (row,) = summary["big"]["items"]
    assert (row["unit_bani"], row["amount_bani"], row["paid_amount_bani"]) == (80000, 80000, 70000)  # pragul: prețul de listă
    assert summary["big"]["kept_paid_bani"] == 70000
    assert summary["by_seller"][0]["paid_bani"] == 80500


def test_empty_account_has_zero_everywhere():
    analysis = _paid([])
    paid = analysis.summary["paid"]
    assert paid["spent_bani"] == 0 and paid["extra_rows"] == [] and paid["by_year_category"]["years"] == []
    _assert_invariants(analysis)


def test_refund_modes_come_from_the_config_file_and_can_be_passed_in(monkeypatch):
    from emag_spend import spend_analysis

    def forbidden(*args, **kwargs):
        """Înlocuiește citirea fișierului: dacă e chemată, testul pică."""
        raise AssertionError("analyze() nu are voie să citească config/restituiri.json când primește modurile")

    monkeypatch.setattr(spend_analysis, "load_refund_modes", forbidden)
    order = _order("100018", "2025-01-05T10:00", _block([("Produs Test", 10000, 1)]))
    custom = RefundModes(cash=frozenset(), credit=frozenset({"vreau banii inapoi"}))
    paid = _paid([order], [_return("3000008", "100018", ["Produs Test"], 10000)], refund_modes=custom).summary["paid"]
    assert paid["spent_bani"] == 10000 and paid["credit_returns_bani"] == 10000
    modes = load_refund_modes()
    assert not modes.is_credit(CASH) and modes.is_credit(VOUCHER) and modes.is_credit("Generare sold") and modes.is_known("  EMITERE  voucher ")


@pytest.mark.parametrize("content, message", [
    ('{"bani_inapoi": ["A"]}', "'credit_emag'"),
    ('{"bani_inapoi": ["A"], "credit_emag": [""]}', "'credit_emag'"),
    ('{"bani_inapoi": ["Mod Test"], "credit_emag": ["mod test"]}', "ambele"),
    ("[]", "obiect"),
])
def test_broken_refund_modes_file_is_rejected_with_the_file_named(tmp_path, content, message):
    path = tmp_path / "restituiri.json"
    path.write_text(content.replace("ambele", ""), encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_refund_modes(path)
    assert str(path) in str(error.value)
    assert message.replace("ambele", "și „bani_inapoi”") in str(error.value)
