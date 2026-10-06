"""Teste pentru împărțirea reducerilor pe produse și a sumei unui bloc (proportional_split.py, block_payment.py), plus
împărțirea valorii unei linii pe stări (models.LineOutcome: păstrat, returnat, anulat, în curs...).

Toate sumele și numele sunt INVENTATE. Invarianții verificați: părțile se adună exact (niciun ban pierdut la rotunjire),
nicio linie și nicio stare nu are sumă negativă sau peste prețul ei de listă, iar produsele + transportul și taxele = suma blocului.
"""

import random

import pytest

from emag_spend import block_status
from emag_spend.block_payment import NOT_CHARGED, PAID_FROM_COMPONENTS, PAID_SHOWN, block_payment
from emag_spend.models import Item, LineOutcome, SellerBlock
from emag_spend.proportional_split import split_proportionally


def _block(items, *, status=block_status.DELIVERED, vouchers=(), shipping=0, services=(), other=(), paid="auto"):
    """Un bloc inventat; `paid="auto"` = „Total platit” egal cu componentele (ca pe o pagină care se leagă)."""
    lines = [Item(name, total, qty) for name, total, qty in items]
    products = sum(item.line_total_bani for item in lines)
    if paid == "auto":
        paid = products + sum(vouchers) + shipping + sum(services) + sum(other)
    return SellerBlock(seller="Vânzător Test", status=status, status_text="test", has_storno=False, items=lines,
                       products_total_bani=products, vouchers_bani=list(vouchers), shipping_bani=shipping,
                       services_bani=list(services), other_bani=list(other), paid_bani=paid)


# ---------- împărțirea proporțională ----------

def test_split_adds_up_exactly_and_follows_the_weights():
    assert split_proportionally(4000, [30000, 10000]) == [3000, 1000]
    assert sum(split_proportionally(10, [3333, 3333, 3333])) == 10
    assert split_proportionally(0, [5, 7]) == [0, 0]
    assert split_proportionally(0, []) == []


def test_split_gives_the_leftover_ban_to_the_largest_remainder_then_to_the_first_position():
    assert split_proportionally(1, [1, 1, 1]) == [1, 0, 0]  # egalitate: prima poziție
    assert split_proportionally(2, [1, 2]) == [1, 1]  # 0,67 și 1,33: restul cel mai mare (0,67) primește banul


def test_split_rejects_negative_values_and_money_without_any_weight():
    with pytest.raises(ValueError):
        split_proportionally(-1, [1])
    with pytest.raises(ValueError):
        split_proportionally(5, [1, -1])
    with pytest.raises(ValueError):
        split_proportionally(5, [0, 0])


def test_split_invariants_on_many_invented_cases():
    rng = random.Random(20261005)
    for _ in range(2000):
        weights = [rng.randint(0, 500000) for _ in range(rng.randint(1, 6))]
        if not sum(weights):
            continue
        total = rng.randint(0, sum(weights))
        parts = split_proportionally(total, weights)
        assert sum(parts) == total
        for part, weight in zip(parts, weights):
            exact = total * weight / sum(weights)
            assert part >= 0 and abs(part - exact) < 1 and part <= weight


# ---------- suma blocului și împărțirea ei ----------

def test_product_with_voucher_and_shipping_gets_price_minus_voucher_and_shipping_stays_separate():
    payment = block_payment(_block([("Televizor Test 50 inch", 249999, 1)], vouchers=[-40000], shipping=2999))
    assert payment.source == PAID_SHOWN
    assert payment.paid_bani == 212998
    assert payment.line_paid_bani == (209999,)  # 2.499,99 − 400,00
    assert payment.fees_bani == 2999 and payment.discount_bani == 40000


def test_voucher_is_shared_by_lines_in_proportion_to_their_price():
    payment = block_payment(_block([("Produs Mare Test", 30000, 1), ("Produs Mic Test", 10000, 2)], vouchers=[-4000], services=[149]))
    assert payment.line_paid_bani == (27000, 9000)
    assert sum(payment.line_paid_bani) + payment.fees_bani == payment.paid_bani
    assert payment.fees_bani == 149


def test_rounding_never_loses_a_ban():
    payment = block_payment(_block([("A Test", 3333, 1), ("B Test", 3333, 1), ("C Test", 3333, 1)], vouchers=[-10]))
    assert sum(payment.line_paid_bani) == 9989 and payment.discount_bani == 10
    assert all(0 <= paid <= 3333 for paid in payment.line_paid_bani)


def test_voucher_bigger_than_the_products_also_covers_part_of_the_shipping():
    payment = block_payment(_block([("Produs Ieftin Test", 1500, 1)], vouchers=[-2000], shipping=1499))
    assert payment.paid_bani == 999
    assert payment.line_paid_bani == (0,) and payment.fees_bani == 999 and payment.discount_bani == 1500


def test_negative_line_is_a_discount_spread_over_the_real_products_and_is_worth_zero_itself():
    payment = block_payment(_block([("Produs Test", 20999, 1), ("Reducere Pachet Test", -2250, 1)], shipping=250))
    assert payment.paid_bani == 18999 and payment.list_bani == 20999
    assert payment.line_paid_bani == (18749, 0)
    assert payment.discount_bani == 2250 and payment.fees_bani == 250


def test_block_without_total_platit_is_rebuilt_from_its_components():
    payment = block_payment(_block([("Produs Test", 10000, 1)], vouchers=[-1000], shipping=1999, paid=None))
    assert payment.source == PAID_FROM_COMPONENTS
    assert payment.paid_bani == 10999 and payment.line_paid_bani == (9000,) and payment.fees_bani == 1999


def test_cancelled_block_charges_nothing_and_values_products_after_vouchers():
    payment = block_payment(_block([("Produs Test", 27999, 1)], status=block_status.CANCELLED, vouchers=[-2800], shipping=1999, paid=0))
    assert payment.source == NOT_CHARGED
    assert payment.line_paid_bani == (25199,) and payment.fees_bani == 0 and payment.paid_bani == 25199


def test_paid_above_products_and_fees_keeps_products_at_list_price_and_the_excess_with_the_fees():
    payment = block_payment(_block([("Produs Test", 10000, 1)], paid=10500))  # o taxă pe care pagina nu o numește
    assert payment.line_paid_bani == (10000,) and payment.fees_bani == 500


def test_block_invariants_on_many_invented_blocks():
    rng = random.Random(51)
    for _ in range(1500):
        items = [(f"Produs {i}", rng.choice([rng.randint(1, 300000), 0, -rng.randint(1, 5000)]), rng.randint(1, 4))
                 for i in range(rng.randint(1, 5))]
        items[0] = ("Produs principal", rng.randint(1, 300000), 1)
        status = rng.choice([block_status.DELIVERED, block_status.CANCELLED, block_status.IN_PROGRESS])
        block = _block(items, status=status, vouchers=[-rng.randint(0, 50000)], shipping=rng.choice([0, 1499, 2999]),
                       services=[rng.choice([0, 149])], paid=rng.choice(["auto", None]))
        payment = block_payment(block)
        assert sum(payment.line_paid_bani) + payment.fees_bani == payment.paid_bani
        for item, paid in zip(block.items, payment.line_paid_bani):
            assert 0 <= paid <= max(0, item.line_total_bani)
        assert payment.discount_bani == payment.list_bani - sum(payment.line_paid_bani) >= 0


# ---------- împărțirea unei linii pe stări ----------

_PAID_PARTS = ("kept_paid_bani", "returned_paid_bani", "cancelled_paid_bani", "pending_paid_bani", "paid_only_paid_bani",
               "unknown_paid_bani")


def _line(qty, total, paid, **states):
    """O linie inventată, cu bucățile pe stări date ca argumente (kept_qty=..., returned_qty=...)."""
    return LineOutcome(order_id="1000000001", placed_at="2025-03-01T10:00", seller="Vânzător Test", name="Produs Test",
                       qty=qty, line_total_bani=total, block_status=block_status.CANCELLED, paid_total_bani=paid, **states)


def test_cancelled_line_with_one_unit_returned_and_an_odd_total_has_no_negative_part():
    # 2 bucăți dintr-un bloc anulat, una returnată după „Livrare anulată”: 251,99 nu se împarte exact în două
    line = _line(2, 27999, 25199, cancelled_qty=1, returned_qty=1, returned_from_cancelled_qty=1)
    parts = [getattr(line, name) for name in _PAID_PARTS]
    assert min(parts) >= 0 and sum(parts) == 25199
    assert line.kept_paid_bani == 0 and line.kept_list_bani == 0
    assert sorted((line.cancelled_paid_bani, line.returned_paid_bani)) == [12599, 12600]


def test_line_parts_add_up_and_stay_non_negative_on_many_invented_lines():
    rng = random.Random(9417)
    states = ("kept_qty", "returned_qty", "cancelled_qty", "pending_qty", "paid_only_qty", "unknown_qty")
    for _ in range(3000):
        qty = rng.randint(1, 7)
        counts = dict.fromkeys(states, 0)
        for _unit in range(qty):
            counts[rng.choice(states)] += 1
        total = rng.randint(1, 50000)
        line = _line(qty, total, rng.randint(0, total), **counts)
        parts = [getattr(line, name) for name in _PAID_PARTS]
        assert min(parts) >= 0 and sum(parts) == line.paid_value_bani
        for name, state in zip(_PAID_PARTS, states):
            if counts[state] == 0:
                assert getattr(line, name) == 0
        assert 0 <= line.kept_list_bani <= line.list_value_bani
