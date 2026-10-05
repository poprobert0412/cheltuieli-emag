"""Verifică fluxul complet pe date demonstrative mari (fără browser)."""

import json

import pytest

from emag_spend import settings
from emag_spend.classifier import Classifier
from emag_spend.demo_data import DEMO_GENERATED_AT, demo_orders_and_returns
from emag_spend.demo_scenario import UNCATEGORIZED_DEMO_NAMES
from emag_spend.spend_analysis import analyze
from emag_spend.warning_messages import (
    KIND_COMPLETED_RETURN_NO_REFUND, KIND_HEADER_MISMATCH, KIND_MISSING_PAID_TOTAL, KIND_PENDING_RETURN, parse_order_warning,
)


@pytest.mark.parametrize("seed", [1, 7, 42, 2026])
def test_demo_data_funnel_closes_and_is_consistent(seed):
    orders, returns = demo_orders_and_returns(seed)
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    result = analyze(orders, returns, classifier, 50000, DEMO_GENERATED_AT,
                     highlight_categories=settings.HIGHLIGHT_CATEGORIES)
    s = result.summary
    f = s["funnel"]
    assert f["ordered_bani"] == f["cancelled_bani"] + f["returned_bani"] + f["pending_bani"] + f["unknown_bani"] + f["kept_bani"]
    assert sum(r["kept_bani"] for r in s["by_category"]) == f["kept_bani"]
    assert sum(r["kept_bani"] for r in s["by_year"]) == f["kept_bani"]
    matrix = s["by_year_category"]["values"]
    assert sum(v for year in matrix.values() for v in year.values()) == f["kept_bani"]
    assert sum(s["orders"][k] for k in ("kept_all", "kept_partial", "returned_all", "cancelled_all", "in_progress", "paid_only", "unknown", "no_items")) == len(orders)
    # Avertismentele permise sunt cele DORITE în demo (scenariul le cere): produsele necategorizate, returul
    # cerut dar fără rezultat, returul finalizat fără sumă, un bloc fără „Total plătit” și totalurile din antet
    # diferite. Orice altceva (suma produselor care nu se leagă, retur fără potrivire) ar fi o greșeală a datelor.
    wanted = {KIND_PENDING_RETURN, KIND_COMPLETED_RETURN_NO_REFUND, KIND_HEADER_MISMATCH, KIND_MISSING_PAID_TOTAL}
    unexpected = [w for w in s["warnings"] if parse_order_warning(w).kind not in wanted and "necategorizate" not in w]
    assert unexpected == []
    assert len(s["warnings"]) == 5
    assert sorted(u["name"] for u in s["uncategorized"]) == sorted(UNCATEGORIZED_DEMO_NAMES)
    # Doar returul finalizat scade din total; cel anulat și cel fără rezultat nu se potrivesc cu nimic.
    assert s["returns"]["matched_units"] == sum(len(r.product_names) for r in returns if r.completed)
    json.dumps(s)


def test_demo_data_is_deterministic():
    assert demo_orders_and_returns(5) == demo_orders_and_returns(5)
    assert demo_orders_and_returns(5) != demo_orders_and_returns(6)
