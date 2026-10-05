"""Proprietăți care trebuie să fie adevărate pentru ORICE comenzi: istoricul prețurilor față de restul analizei.

Primește: comenzi inventate, generate cu un seed fix (aceleași la fiecare rulare), cu culori, nume trunchiate,
cadouri la preț 0, comenzi anulate / în curs și retururi. Verifică invarianții (minim ≤ orice preț, diferența
față de minim ≥ 0, unitățile din istoric ≤ unitățile păstrate din pâlnie) pe analiza completă, nu pe un caz ales.
"""

import json
import random

import pytest

from emag_spend import block_status
from emag_spend.models import Item, Order, ReturnRequest, SellerBlock
from emag_spend.spend_analysis import analyze
from tests import scenario

SEEDS = range(40)  # destule combinații ca să apară repetări, culori și trunchieri; fix, ca rularea să fie repetabilă
NAMES = [
    "Husă Kelmor Fit, silicon, Alb", "Husă Kelmor Fit, silicon, Negru", "Husă Kelmor Fit, silicon, Roșu",
    "Stick USB Brenta 128GB, Negru", "Stick USB Brenta 256GB, Negru",
    'Televizor Smart Norvik 43" negru', 'Televizor Smart Norvik 55" negru',
    "Cablu Test 2 m", "Cablu Test 3 m",
    "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Negru",
    "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Ne [...]",  # trunchiat de eMAG
]
UNIT_PRICES_BANI = [0, 1, 990, 1000, 1250, 2500, 2999, 4000, 9990]  # include cadouri (0) și prețuri care se rotunjesc prost
STATUSES = [block_status.DELIVERED] * 4 + [block_status.CANCELLED, block_status.IN_PROGRESS]


def _random_orders(seed: int) -> tuple[list[Order], list[ReturnRequest]]:
    """Comenzi și retururi inventate, determinate de `seed`; fiecare comandă are un singur bloc."""
    rng = random.Random(seed)
    orders: list[Order] = []
    returns: list[ReturnRequest] = []
    for index in range(rng.randint(6, 14)):
        items = [
            Item(rng.choice(NAMES), rng.choice(UNIT_PRICES_BANI) * qty, qty)
            for qty in (rng.randint(1, 4) for _ in range(rng.randint(1, 3)))
        ]
        total = sum(item.line_total_bani for item in items)
        status = rng.choice(STATUSES)
        block = SellerBlock("eMAG", status, status, False, items, total, [], 0, [], [], total)
        order_id = str(100200000 + index)
        date = None if rng.random() < 0.1 else f"{rng.randint(2022, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T10:00"
        orders.append(Order(order_id, date or "", date, total, [block]))
        if status == block_status.DELIVERED and rng.random() < 0.3:
            returns.append(ReturnRequest(
                str(3000000 + index), f"/user/return-history/1/{3000000 + index}", [order_id], [items[0].name],
                ["Restituire suma"], items[0].line_total_bani // items[0].qty, "Vreau banii inapoi", True, False,
            ))
    return orders, returns


@pytest.fixture(params=SEEDS)
def summary(request):
    orders, returns = _random_orders(request.param)
    return analyze(orders, returns, scenario.classifier(), 50000, "2026-10-05 10:00").summary


def test_minimum_is_never_above_a_price_paid_and_the_difference_to_it_is_never_negative(summary):
    for product in summary["price_history"]["products"]:
        prices = [purchase["unit_bani"] for purchase in product["purchases"]]
        assert product["min_unit_bani"] == min(prices) and product["max_unit_bani"] == max(prices)
        assert all(product["min_unit_bani"] <= price <= product["max_unit_bani"] for price in prices)
        assert product["overpaid_vs_min_bani"] >= 0
        assert product["overpaid_vs_min_bani"] == sum(
            (purchase["unit_bani"] - product["min_unit_bani"]) * purchase["qty"] for purchase in product["purchases"]
        )
        assert product["min_unit_bani"] > 0  # cadourile (preț 0) nu intră


def test_every_product_has_kept_units_in_at_least_two_different_orders_in_time_order(summary):
    for product in summary["price_history"]["products"]:
        purchases = product["purchases"]
        assert len({purchase["order_id"] for purchase in purchases}) >= 2
        assert all(purchase["qty"] > 0 for purchase in purchases)
        assert product["kept_units"] == sum(purchase["qty"] for purchase in purchases)
        dates = [purchase["date"] or "" for purchase in purchases]
        assert dates == sorted(dates)  # cele fără dată, primele
        assert product["first_unit_bani"] == purchases[0]["unit_bani"] and product["last_unit_bani"] == purchases[-1]["unit_bani"]


def test_units_in_the_history_never_exceed_the_units_the_funnel_keeps(summary):
    history = summary["price_history"]
    assert history["summary"]["units"] == sum(product["kept_units"] for product in history["products"])
    assert history["summary"]["units"] <= summary["funnel"]["kept_units"]


def test_summary_adds_up_and_impacts_are_positive_amounts(summary):
    history = summary["price_history"]
    change = history["summary"]["last_vs_prev"]
    assert change["cheaper_products"] + change["pricier_products"] + change["same_products"] == history["summary"]["products"]
    assert change["cheaper_bani"] >= 0 and change["pricier_bani"] >= 0
    assert history["summary"]["purchases"] == sum(len(product["purchases"]) for product in history["products"])
    assert history["summary"]["overpaid_vs_min_bani"] == sum(product["overpaid_vs_min_bani"] for product in history["products"])
    ordered = [(-product["overpaid_vs_min_bani"], product["key"]) for product in history["products"]]
    assert ordered == sorted(ordered)  # descrescător după diferența față de minim, apoi după cheie


def test_the_whole_summary_is_json_and_the_funnel_still_closes(summary):
    assert json.loads(json.dumps(summary)) == summary
    funnel = summary["funnel"]
    parts = sum(funnel[key] for key in ("cancelled_bani", "returned_bani", "pending_bani", "unknown_bani", "kept_bani"))
    assert parts == funnel["ordered_bani"]  # istoricul prețurilor nu schimbă nicio sumă din pâlnie


def test_the_generator_really_produces_repeated_products_for_some_seeds():
    # fără asta, testele de mai sus ar putea trece gol (nicio comandă cu produs repetat)
    with_history = 0
    for seed in SEEDS:
        orders, returns = _random_orders(seed)
        result = analyze(orders, returns, scenario.classifier(), 50000, "2026-10-05 10:00").summary
        with_history += bool(result["price_history"]["products"])
    assert with_history >= len(SEEDS) // 2
