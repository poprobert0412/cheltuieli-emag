"""Verifică explicit că datele demonstrative arată TOT ce arată raportul.

Cazurile scrise de mână (demo_scenario.py) trebuie să existe la ORICE seed; de aceea
fiecare verificare rulează pe mai multe seed-uri. „Anul de vârf" se verifică doar pe
seed-ul implicit, fiindcă el depinde și de comenzile obișnuite alese aleator.
Regulile personale de categorii (categorii.personal.json) sunt ignorate: demo-ul trebuie să dea
același rezultat pe orice calculator.
"""

from functools import lru_cache

import pytest

from emag_spend import block_status, settings
from emag_spend.classifier import Classifier
from emag_spend.demo_data import DEMO_GENERATED_AT, DEMO_SEED, demo_orders_and_returns
from emag_spend.demo_scenario import CAFEA_MACINATA, scripted_plans
from emag_spend.spend_analysis import analyze
from emag_spend.text_normalize import normalize_text
from emag_spend.warning_messages import ALL_KINDS

SEEDS = [1, DEMO_SEED, 42, 2026]
THRESHOLD_BANI = round(settings.BIG_PURCHASE_THRESHOLD_LEI * 100)
EMAG = "eMAG"
# Totalurile din antet pe care scenariul le cere diferite de suma blocurilor (în bani: antet − blocuri).
DECLARED_HEADER_DIFFERENCES = sorted(plan.header_extra_bani for plan in scripted_plans()[0] if plan.header_extra_bani)


@lru_cache(maxsize=None)
def _demo(seed: int):
    orders, returns = demo_orders_and_returns(seed)
    summary = analyze(orders, returns, Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False), THRESHOLD_BANI,
                      DEMO_GENERATED_AT, highlight_categories=settings.HIGHLIGHT_CATEGORIES).summary
    return orders, returns, summary


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_spans_every_year_2017_to_2026(seed):
    years = {row["year"] for row in _demo(seed)[2]["by_year"]}
    assert years == {str(y) for y in range(2017, 2027)}


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_many_categories(seed):
    kept_categories = [row["name"] for row in _demo(seed)[2]["by_category"] if row["kept_bani"] > 0]
    assert len(kept_categories) >= 15


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_at_least_two_televisions_and_all_their_states(seed):
    block = _demo(seed)[2]["highlights"]["Televizoare"]
    assert block["totals"]["kept_units"] >= 2
    states = {item["state"] for item in block["items"]}
    assert {"kept", "returned", "cancelled", "pending"} <= states
    assert all("televizor" in normalize_text(item["name"]) for item in block["items"])  # suportul TV nu intră aici


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_alcoholic_drinks(seed):
    block = _demo(seed)[2]["highlights"]["Alcool"]
    assert block["totals"]["kept_units"] >= 3
    assert block["totals"]["kept_bani"] > 0
    assert {"kept", "returned", "cancelled"} <= {item["state"] for item in block["items"]}
    # „Alcool sanitar" e produs de curățenie, nu băutură: regula de excludere trebuie să-l țină afară.
    assert not any("sanitar" in normalize_text(item["name"]) for item in block["items"])


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_cancelled_returned_and_marked_cancelled_returns(seed):
    summary = _demo(seed)[2]
    assert summary["funnel"]["cancelled_bani"] > 0
    assert summary["funnel"]["returned_bani"] > 0
    assert summary["returns"]["matched_from_cancelled_units"] >= 1  # retur marcat „Livrare anulata" de eMAG
    assert any(item["returned_from_cancelled"] for item in summary["big"]["items"])
    assert summary["returns"]["unmatched_refund_bani"] == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_orders_in_progress(seed):
    summary = _demo(seed)[2]
    assert summary["orders"]["in_progress"] >= 1
    assert summary["funnel"]["pending_bani"] > 0
    assert len(summary["in_progress"]) >= 1


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_insurance_paid_without_delivery_and_outside_the_calculation(seed):
    orders, _, summary = _demo(seed)
    assert len(summary["paid_only"]) >= 1
    row = summary["paid_only"][0]
    assert row["paid_bani"] > 0 and any("asigurare" in normalize_text(n) for n in row["names"])
    assert "Asigurări (RCA)" not in {r["name"] for r in summary["by_category"]}
    priced = sum(b.products_total_bani for o in orders for b in o.blocks if b.status != block_status.PAID_ONLY)
    assert summary["funnel"]["ordered_bani"] == priced


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_vouchers_shipping_and_taxes(seed):
    rec = _demo(seed)[2]["reconciliation"]
    assert rec["vouchers_delivered_bani"] > 0
    assert rec["shipping_delivered_bani"] > 0
    assert rec["services_delivered_bani"] > 0


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_header_total_mismatches_are_exactly_the_ones_the_scenario_declares(seed):
    mismatches = _demo(seed)[2]["reconciliation"]["header_total_mismatches"]
    assert DECLARED_HEADER_DIFFERENCES == [-1000, 550, 3490]
    assert sorted(m["header_bani"] - m["blocks_bani"] for m in mismatches) == DECLARED_HEADER_DIFFERENCES


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_purchases_above_the_threshold_in_every_state(seed):
    orders, _, summary = _demo(seed)
    big = summary["big"]
    assert big["threshold_bani"] == THRESHOLD_BANI
    assert big["items"] and all(item["unit_bani"] > THRESHOLD_BANI for item in big["items"])
    assert {"kept", "returned", "cancelled", "pending"} <= {item["state"] for item in big["items"]}
    # Un produs exact la prag există în comenzi (arată că pragul e STRICT) și nu apare la „peste prag".
    at_threshold = {i.name for o in orders for b in o.blocks for i in b.items if i.line_total_bani == THRESHOLD_BANI * i.qty}
    assert at_threshold
    assert not at_threshold & {item["name"] for item in big["items"]}


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_marketplace_sellers(seed):
    sellers = [row["seller"] for row in _demo(seed)[2]["by_seller"]]
    assert EMAG in sellers
    assert len([s for s in sellers if s != EMAG]) >= 3


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_uncategorized_products_with_the_warning(seed):
    summary = _demo(seed)[2]
    assert summary["uncategorized_count"] >= 1
    assert any("necategorizate" in w for w in summary["warnings"])


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_has_returns_in_every_state_and_both_refund_modes(seed):
    rec = _demo(seed)[2]["reconciliation"]
    assert rec["returns_completed"] >= 5
    assert rec["returns_cancelled"] >= 1
    assert rec["returns_pending"] >= 1
    assert len(rec["refund_modes"]) >= 2
    assert any("fără rezultat" in w for w in _demo(seed)[2]["warnings"])


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_shows_every_group_of_warnings_with_their_orders(seed):
    groups = {g["kind"]: g for g in _demo(seed)[2]["warnings_detail"]}
    assert list(groups) == list(ALL_KINDS)  # toate cele cinci grupe, în ordinea fixă
    assert groups["header_total_mismatch"]["count"] == 3 and groups["pending_return_without_result"]["count"] == 1
    with_hint = [i for i in groups["header_total_mismatch"]["items"] if "bloc anulat" in i["text"]]
    assert len(with_hint) == 1  # doar comanda cu bloc anulat primește explicația
    assert groups["completed_return_without_refund"]["count"] == 1 and groups["missing_paid_total"]["count"] == 1
    for group in groups.values():
        assert group["count"] == len(group["items"])
    assert all(item["order_ids"] for kind, g in groups.items() if kind != "other" for item in g["items"])
    assert all(item["return_url"] for item in groups["pending_return_without_result"]["items"])


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_price_history_shows_colors_capacities_and_cheaper_or_pricier_prices(seed):
    history = _demo(seed)[2]["price_history"]
    products = {p["key"]: p for p in history["products"]}
    shirt = products["tricou bumbac barbati brenta xl"]  # negru în 2018, alb în 2022: același model
    shirt_words = {w for p in shirt["purchases"] for w in normalize_text(p["name"]).replace(",", " ").split()}
    assert shirt["color_variants"] is True and {"negru", "alb"} <= shirt_words
    assert "tricou bumbac barbati brenta l" not in products  # mărimea L a fost cumpărată o singură dată
    stick_128, stick_256 = products["stick usb brenta 128gb usb 3 2"], products["stick usb brenta 256gb usb 3 2"]
    assert stick_128["name"] != stick_256["name"] and stick_128["key"] != stick_256["key"]  # capacitățile NU se unesc
    assert [p["unit_bani"] for p in stick_256["purchases"]] == [7990, 7490] and stick_256["last_vs_prev_unit_bani"] == -500
    coffee = products["cafea macinata aroma casa 500 g"]  # doar în scenariu: cifrele nu depind de seed
    assert [p["unit_bani"] for p in coffee["purchases"]] == [2490, 3190] and coffee["name"] == CAFEA_MACINATA
    assert (coffee["last_vs_prev_unit_bani"], coffee["last_vs_prev_impact_bani"], coffee["overpaid_vs_min_bani"]) == (700, 1400, 1400)
    change = history["summary"]["last_vs_prev"]
    assert change["cheaper_products"] >= 1 and change["pricier_products"] >= 1


@pytest.mark.parametrize("seed", SEEDS)
def test_demo_price_history_keeps_its_invariants(seed):
    summary = _demo(seed)[2]
    history = summary["price_history"]
    assert history["summary"]["units"] <= summary["funnel"]["kept_units"]
    assert history["summary"]["products"] == len(history["products"]) >= 10
    for product in history["products"]:
        prices = [p["unit_bani"] for p in product["purchases"]]
        assert product["min_unit_bani"] == min(prices) <= min(product["first_unit_bani"], product["last_unit_bani"])
        assert product["max_unit_bani"] == max(prices)
        assert product["overpaid_vs_min_bani"] >= 0 and len({p["order_id"] for p in product["purchases"]}) >= 2
        assert product["kept_units"] == sum(p["qty"] for p in product["purchases"])


def test_demo_has_one_clear_peak_year():
    kept = sorted((row["kept_bani"], row["year"]) for row in _demo(DEMO_SEED)[2]["by_year"])
    (second, _), (peak, peak_year) = kept[-2], kept[-1]
    assert peak >= second * 1.15, f"anul de vârf ({peak_year}) nu iese clar în evidență"


def test_demo_funnel_looks_like_a_real_account():
    funnel = _demo(DEMO_SEED)[2]["funnel"]
    share_kept = funnel["kept_bani"] / funnel["ordered_bani"]
    assert 0.70 <= share_kept <= 0.95  # nici toate păstrate, nici majoritatea anulate/returnate
    assert 200 <= _demo(DEMO_SEED)[2]["meta"]["lines"] <= 400  # destul cât să umple listele, nu atât cât să obosească
