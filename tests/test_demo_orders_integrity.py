"""Verifică coerența internă a comenzilor și retururilor inventate (ca și cum ar fi citite din pagini eMAG)."""

import pytest

from emag_spend import block_status, settings
from emag_spend.classifier import Classifier
from emag_spend.dates_ro import parse_ro_datetime
from emag_spend.demo_catalog import FILLER_FAMILIES, MARKETPLACE_SELLERS
from emag_spend.demo_data import DEMO_GENERATED_AT, DEMO_SEED, demo_orders_and_returns
from emag_spend.demo_scenario import UNCATEGORIZED_DEMO_NAMES, scripted_plans
from emag_spend.warning_messages import format_missing_paid_total

SEEDS = [1, DEMO_SEED, 42, 2026]
# „Defectele” cerute de scenariu (ca raportul să arate avertismentele): blocuri fără „Total platit”,
# totaluri din antet diferite de suma blocurilor, retururi finalizate fără sumă. Orice altceva trebuie să se lege.
_PLANS, _RETURN_PLANS = scripted_plans()
DECLARED_BLOCKS_WITHOUT_PAID = sum(1 for plan in _PLANS for block in plan.blocks if not block.paid_shown)
DECLARED_HEADER_EXTRAS = sorted(plan.header_extra_bani for plan in _PLANS if plan.header_extra_bani)
DECLARED_RETURNS_WITHOUT_REFUND = sum(1 for plan in _RETURN_PLANS if not plan.refund_shown)


@pytest.mark.parametrize("seed", SEEDS)
def test_order_and_return_numbers_are_unique_and_grow_with_time(seed):
    orders, returns = demo_orders_and_returns(seed)
    ids = [int(o.order_id) for o in orders]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
    assert [o.placed_at for o in orders] == sorted(o.placed_at for o in orders)
    return_ids = [int(r.return_id) for r in returns]
    assert len(set(return_ids)) == len(return_ids) and return_ids == sorted(return_ids)


@pytest.mark.parametrize("seed", SEEDS)
def test_order_dates_are_readable_and_before_the_demo_generation_time(seed):
    for order in demo_orders_and_returns(seed)[0]:
        assert parse_ro_datetime(order.placed_text) == order.placed_at
        assert order.placed_at.replace("T", " ") < DEMO_GENERATED_AT


@pytest.mark.parametrize("seed", SEEDS)
def test_block_statuses_are_read_back_as_the_same_status_by_the_real_classifier(seed):
    for order in demo_orders_and_returns(seed)[0]:
        for block in order.blocks:
            assert block_status.classify_status(block.status_text) == block.status, block.status_text


@pytest.mark.parametrize("seed", SEEDS)
def test_totals_tie_together_like_on_the_real_pages(seed):
    without_paid, header_differences = 0, []
    for order in demo_orders_and_returns(seed)[0]:
        missing = [b for b in order.blocks if b.paid_bani is None]
        without_paid += len(missing)
        # același mesaj ca la citirea paginii
        assert order.warnings == [format_missing_paid_total(order.order_id, b.seller) for b in missing]
        for block in order.blocks:
            assert block.products_total_bani == sum(i.line_total_bani for i in block.items)
            assert all(i.line_total_bani > 0 and i.qty >= 1 for i in block.items)
            if block.status == block_status.CANCELLED:
                assert block.paid_bani == 0 and not block.vouchers_bani
            elif block.paid_bani is not None:
                parts = block.products_total_bani + sum(block.vouchers_bani) + block.shipping_bani \
                    + sum(block.services_bani) + sum(block.other_bani)
                assert block.paid_bani == parts
        shown = sum(b.paid_bani or 0 for b in order.blocks)
        if all(b.status == block_status.CANCELLED for b in order.blocks):
            assert order.header_total_bani is None  # eMAG nu arată totalul la comenzile anulate
        elif order.header_total_bani != shown:
            header_differences.append(order.header_total_bani - shown)
    assert without_paid == DECLARED_BLOCKS_WITHOUT_PAID == 1
    assert sorted(header_differences) == DECLARED_HEADER_EXTRAS


@pytest.mark.parametrize("seed", SEEDS)
def test_returns_point_at_real_orders_and_products(seed):
    orders, returns = demo_orders_and_returns(seed)
    by_id = {o.order_id: o for o in orders}
    for ret in returns:
        assert ret.detail_path.endswith(f"/{ret.return_id}")
        (order_id,) = ret.order_ids
        names = [i.name for b in by_id[order_id].blocks for i in b.items]
        assert ret.product_names and all(name in names for name in ret.product_names)
        assert not (ret.completed and ret.cancelled)  # un retur nu e și finalizat, și anulat
        if ret.completed:
            assert "Restituire suma" in ret.steps
            assert ret.refund_bani is None or ret.refund_bani > 0
        else:
            assert ret.refund_bani is None
    completed_without_amount = [r for r in returns if r.completed and r.refund_bani is None]
    assert len(completed_without_amount) == DECLARED_RETURNS_WITHOUT_REFUND == 1  # doar cel cerut de scenariu


@pytest.mark.parametrize("seed", SEEDS)
def test_every_product_lands_in_a_category_except_the_declared_uncategorized_ones(seed):
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    names = {i.name for o in demo_orders_and_returns(seed)[0] for b in o.blocks for i in b.items}
    uncategorized = {n for n in names if classifier.classify(n)[0] == classifier.default_category}
    assert uncategorized == set(UNCATEGORIZED_DEMO_NAMES)


def test_every_catalog_product_has_a_category_and_a_sane_price_range():
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    for family_name, family in FILLER_FAMILIES.items():
        assert family.weight > 0 and family.qty_options and family.items, family_name
        for item in family.items:
            assert classifier.classify(item.name)[0] != classifier.default_category, item.name
            assert 0 < item.low_lei <= item.high_lei <= 5000, item.name
    assert len(set(MARKETPLACE_SELLERS)) == len(MARKETPLACE_SELLERS)


def test_demo_names_contain_no_contact_details():
    orders, _ = demo_orders_and_returns(DEMO_SEED)
    texts = [i.name for o in orders for b in o.blocks for i in b.items] + [b.seller for o in orders for b in o.blocks]
    assert not any("@" in text or "http" in text.lower() for text in texts)
