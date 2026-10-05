"""Teste pentru construcția comenzilor demonstrative din planuri (numere, totaluri, retururi)."""

import pytest

from emag_spend import block_status, warning_messages
from emag_spend import demo_builder as builder
from emag_spend.demo_builder import BlockPlan, LinePlan, OrderPlan, ReturnPlan, build_orders_and_returns


def _plan(placed_at="2024-05-01T10:00", *blocks):
    return OrderPlan(placed_at, list(blocks))


def test_totals_follow_the_real_page_rules():
    block = BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("Produs A", 15000, 2), LinePlan("Produs B", 1000)],
                      voucher_bani=500, services_bani=(149,), other_bani=(200,))
    (order,), _ = build_orders_and_returns([_plan("2024-05-01T10:00", block)], [])
    sb = order.blocks[0]
    assert sb.products_total_bani == 31000 and [i.line_total_bani for i in sb.items] == [30000, 1000]
    assert sb.vouchers_bani == [-500] and sb.services_bani == [149] and sb.other_bani == [200]
    assert sb.shipping_bani == 0  # 310 Lei de produse: peste pragul de transport gratuit
    assert sb.paid_bani == 31000 - 500 + 0 + 149 + 200
    assert order.header_total_bani == sb.paid_bani
    assert order.placed_text == "1 mai 2024, 10:00"


def test_shipping_fee_depends_on_seller_and_free_threshold():
    cheap = [LinePlan("Ieftin", builder.SHIPPING_FREE_FROM_BANI - 1)]
    free = [LinePlan("Scump", builder.SHIPPING_FREE_FROM_BANI)]
    orders, _ = build_orders_and_returns([
        _plan("2024-01-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, cheap)),
        _plan("2024-01-02T10:00", BlockPlan("Firma SRL", block_status.DELIVERED, cheap)),
        _plan("2024-01-03T10:00", BlockPlan("eMAG", block_status.DELIVERED, free)),
        _plan("2024-01-04T10:00", BlockPlan("eMAG Asigurari", block_status.PAID_ONLY, cheap)),
    ], [])
    assert [o.blocks[0].shipping_bani for o in orders] == [
        builder.SHIPPING_FEE_EMAG_BANI, builder.SHIPPING_FEE_MARKETPLACE_BANI, 0, 0]


def test_cancelled_block_shows_zero_paid_and_order_has_no_header_total():
    block = BlockPlan("Firma SRL", block_status.CANCELLED, [LinePlan("Produs", 9000)], voucher_bani=1000, services_bani=(149,))
    (order,), _ = build_orders_and_returns([_plan("2024-05-01T10:00", block)], [])
    sb = order.blocks[0]
    assert (sb.paid_bani, sb.shipping_bani, sb.vouchers_bani, sb.services_bani) == (0, 0, [], [])
    assert sb.products_total_bani == 9000 and order.header_total_bani is None


def test_mixed_order_keeps_a_header_total_equal_to_the_delivered_part():
    delivered = BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 20000)])
    cancelled = BlockPlan("Firma SRL", block_status.CANCELLED, [LinePlan("B", 30000)])
    (order,), _ = build_orders_and_returns([_plan("2024-05-01T10:00", delivered, cancelled)], [])
    assert order.header_total_bani == 20000


def test_orders_are_sorted_in_time_and_returns_point_at_the_final_order_numbers():
    late = _plan("2025-01-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("Tardiv", 12000)]))
    early = _plan("2020-01-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("Timpuriu", 8000, 2)]))
    orders, returns = build_orders_and_returns(
        [late, early], [ReturnPlan(early, ("Timpuriu",)), ReturnPlan(late, ("Tardiv",), outcome="pending")])
    assert [o.placed_at for o in orders] == ["2020-01-01T10:00", "2025-01-01T10:00"]
    assert returns[0].order_ids == [orders[0].order_id] and returns[1].order_ids == [orders[1].order_id]
    assert returns[0].refund_bani == 8000 and returns[0].completed  # o bucată din două, la prețul pe bucată
    assert returns[1].refund_bani is None and not returns[1].completed and not returns[1].cancelled


def test_cancelled_return_is_flagged_and_has_no_refund():
    order = _plan("2024-05-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 5000)]))
    _, (ret,) = build_orders_and_returns([order], [ReturnPlan(order, ("A",), outcome="cancelled")])
    assert ret.cancelled and not ret.completed and ret.refund_bani is None
    assert ret.steps == builder.RETURN_STEPS["cancelled"]


def test_return_for_unknown_product_or_foreign_order_is_rejected():
    order = _plan("2024-05-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 5000)]))
    other = _plan("2024-06-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("B", 5000)]))
    with pytest.raises(ValueError, match="nu e în comanda"):
        build_orders_and_returns([order], [ReturnPlan(order, ("Inexistent",))])
    with pytest.raises(ValueError, match="nu face parte"):
        build_orders_and_returns([order], [ReturnPlan(other, ("B",))])


def test_block_without_a_shown_paid_total_has_no_amount_and_the_same_warning_as_a_parsed_page():
    shown = BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 5000)])
    hidden = BlockPlan("Firma SRL", block_status.DELIVERED, [LinePlan("B", 7000)], paid_shown=False)
    (order,), _ = build_orders_and_returns([_plan("2024-05-01T10:00", shown, hidden)], [])
    assert order.blocks[0].paid_bani is not None and order.blocks[1].paid_bani is None
    assert order.warnings == [warning_messages.format_missing_paid_total(order.order_id, "Firma SRL")]
    assert order.header_total_bani == order.blocks[0].paid_bani  # antetul însumează doar ce se vede


def test_cancelled_block_never_warns_about_a_missing_paid_total():
    cancelled = BlockPlan("Firma SRL", block_status.CANCELLED, [LinePlan("B", 7000)], paid_shown=False)
    (order,), _ = build_orders_and_returns([_plan("2024-05-01T10:00", cancelled)], [])
    assert order.blocks[0].paid_bani is None and order.warnings == []


def test_header_extra_makes_the_header_differ_from_the_blocks_by_exactly_that_amount():
    block = BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 20000)])
    plan = OrderPlan("2024-05-01T10:00", [block], header_extra_bani=-750)
    (order,), _ = build_orders_and_returns([plan], [])
    assert order.header_total_bani == order.blocks[0].paid_bani - 750 and order.warnings == []
    cancelled = OrderPlan("2024-06-01T10:00", [BlockPlan("eMAG", block_status.CANCELLED, [LinePlan("B", 9000)])], header_extra_bani=300)
    (all_cancelled,), _ = build_orders_and_returns([cancelled], [])
    assert all_cancelled.header_total_bani is None  # la comenzile anulate eMAG nu arată totalul


def test_completed_return_can_hide_its_refund_amount():
    order = _plan("2024-05-01T10:00", BlockPlan("eMAG", block_status.DELIVERED, [LinePlan("A", 5000)]))
    _, (shown, hidden) = build_orders_and_returns(
        [order], [ReturnPlan(order, ("A",)), ReturnPlan(order, ("A",), refund_shown=False)])
    assert shown.refund_bani == 5000 and hidden.refund_bani is None
    assert shown.completed and hidden.completed and "Restituire suma" in hidden.steps
