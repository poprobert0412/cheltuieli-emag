"""Teste pentru potrivirea retururilor cu produsele din comenzi."""

from emag_spend import block_status
from emag_spend.line_ledger import build_lines
from emag_spend.models import Item, LineOutcome, Order, ReturnRequest, SellerBlock
from emag_spend.return_matcher import apply_returns


def _line(order_id, name, total, qty=1, status=block_status.DELIVERED):
    line = LineOutcome(order_id, "2026-01-01T10:00", "eMAG", name, qty, total, status)
    field = {
        block_status.DELIVERED: "kept_qty", block_status.CANCELLED: "cancelled_qty",
    }[status]
    setattr(line, field, qty)
    return line


def _return(return_id, order_ids, names, completed=True, refund=None):
    return ReturnRequest(return_id, f"/user/return-history/1/{return_id}", order_ids, names,
                         ["Cerere inregistrata"] + (["Restituire suma"] if completed else []),
                         refund, "Vreau banii inapoi", completed, False)


def test_completed_return_moves_one_unit_from_kept_to_returned():
    line = _line("1", "Rucsac Test", 11699)
    report = apply_returns([line], [_return("r1", ["1"], ["Rucsac Test"])])
    assert (line.kept_qty, line.returned_qty) == (0, 1)
    assert line.return_ids == ["r1"]
    assert line.returned_bani == 11699 and line.kept_bani == 0
    assert report.matched_units == 1 and report.warnings == []


def test_return_of_one_unit_from_a_multi_unit_line_splits_the_value():
    line = _line("1", "Husa Test", 6000, qty=2)
    apply_returns([line], [_return("r1", ["1"], ["Husa Test"])])
    assert (line.kept_qty, line.returned_qty) == (1, 1)
    assert line.returned_bani == 3000 and line.kept_bani == 3000


def test_repeated_name_in_return_consumes_one_unit_each_time():
    lines = [_line("1", "Absorbante Test", 1000), _line("1", "Absorbante Test", 1000), _line("1", "Absorbante Test", 1000)]
    apply_returns(lines, [_return("r1", ["1"], ["Absorbante Test", "Absorbante Test"])])
    assert sum(l.returned_qty for l in lines) == 2
    assert sum(l.kept_qty for l in lines) == 1


def test_marketplace_return_marked_cancelled_becomes_returned_not_cancelled():
    line = _line("1", "Rucsac Marketplace", 15000, status=block_status.CANCELLED)
    report = apply_returns([line], [_return("r1", ["1"], ["Rucsac Marketplace"])])
    assert (line.cancelled_qty, line.returned_qty, line.returned_from_cancelled_qty) == (0, 1, 1)
    assert report.matched_from_cancelled_units == 1


def test_kept_unit_is_preferred_over_cancelled_one():
    kept = _line("1", "Produs Test", 1000)
    cancelled = _line("1", "Produs Test", 1000, status=block_status.CANCELLED)
    apply_returns([cancelled, kept], [_return("r1", ["1"], ["Produs Test"])])
    assert (kept.returned_qty, cancelled.returned_qty) == (1, 0)
    assert cancelled.cancelled_qty == 1


def test_returns_that_are_not_completed_are_ignored():
    line = _line("1", "Produs Test", 1000)
    apply_returns([line], [_return("r1", ["1"], ["Produs Test"], completed=False)])
    assert (line.kept_qty, line.returned_qty) == (1, 0)


def test_return_for_unknown_order_warns_and_counts_refund_as_unmatched():
    report = apply_returns([_line("1", "Produs Test", 1000)], [_return("r1", ["999"], ["Produs Test"], refund=1000)])
    assert any("nu e în lista citită" in w for w in report.warnings)
    assert report.unmatched_refund_bani == 1000


def test_product_not_found_in_order_warns():
    line = _line("1", "Produs Test", 1000)
    report = apply_returns([line], [_return("r1", ["1"], ["Total altceva 123456"], refund=500)])
    assert line.kept_qty == 1
    assert any("nu are potrivire" in w for w in report.warnings)
    assert report.unmatched_refund_bani == 500


def test_slightly_different_name_matches_when_similar_enough():
    line = _line("1", "Puma, Tricou Test, Negru, 3XL", 5000)
    apply_returns([line], [_return("r1", ["1"], ["Puma Tricou Test Negru 3XL"])])
    assert line.returned_qty == 1


def test_order_name_truncated_by_emag_matches_the_full_name_in_the_return():
    full = "Aparat de ras Norvik Shaver Seria 3000 N3134/51, fara fir, Sistem de lame TaieRapid cu 27 de lame, Albastru inchis"
    line = _line("1", "Aparat de ras Norvik Shaver Seria 3000 N3134/51, fara fir, Sistem de lame TaieRapid [...]", 20000)
    apply_returns([line], [_return("r1", ["1"], [full])])
    assert line.returned_qty == 1


def test_truncated_name_with_too_short_a_prefix_does_not_match():
    line = _line("1", "Aparat [...]", 20000)
    apply_returns([line], [_return("r1", ["1"], ["Aparat de ras Norvik Shaver Seria 3000"])])
    assert line.returned_qty == 0


def test_clearly_different_name_does_not_match():
    line = _line("1", "Puma, Tricou Test, Negru, 3XL", 5000)
    apply_returns([line], [_return("r1", ["1"], ["Televizor Alfa 55 inch"])])
    assert line.returned_qty == 0


def test_returning_more_units_than_exist_warns_for_the_extra_ones():
    line = _line("1", "Produs Test", 1000)
    report = apply_returns([line], [_return("r1", ["1"], ["Produs Test", "Produs Test"])])
    assert line.returned_qty == 1
    assert len(report.warnings) == 1


def test_return_without_orders_or_products_warns():
    line = _line("1", "Produs Test", 1000)
    report = apply_returns([line], [_return("r1", [], ["Produs Test"]), _return("r2", ["1"], [])])
    assert len(report.warnings) == 2


def test_ledger_initial_states_follow_block_status():
    blocks = [SellerBlock("eMAG", status, "", False, [Item("P", 1000, 2)]) for status in (
        block_status.DELIVERED, block_status.CANCELLED, block_status.IN_PROGRESS, block_status.PAID_ONLY, block_status.UNKNOWN)]
    lines = build_lines([Order("1", "", "2026-01-01T10:00", None, blocks)])
    assert [(l.kept_qty, l.cancelled_qty, l.pending_qty, l.paid_only_qty, l.unknown_qty) for l in lines] == [
        (2, 0, 0, 0, 0), (0, 2, 0, 0, 0), (0, 0, 2, 0, 0), (0, 0, 0, 2, 0), (0, 0, 0, 0, 2)]
