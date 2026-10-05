"""Teste pentru parserul paginii de retur (pagini inventate)."""

import json

import pytest

from emag_spend.html_lines import html_to_lines
from emag_spend.models import to_dict
from emag_spend.return_parser import parse_return
from tests.html_builders import FAKE_ADDRESS, FAKE_EMAIL, FAKE_NAME, FAKE_PHONE, return_page

_COMPLETED_STEPS = [
    ("Cerere inregistrata", "Data: 1 Iulie, 13:44"),
    ("Preluat de catre curier", "Data: 1 Iulie, 16:21"),
    ("Restituire suma", "Data: 1 Iulie, 16:45"),
]
_REFUND = "Suma de 93.59 RON a pornit spre contul tau. Finalizarea transferului poate dura."


def _parse(html, path="/user/return-history/1/777"):
    return parse_return(path, html_to_lines(html))


@pytest.mark.parametrize("merge", [False, True])
def test_completed_return_with_refund(merge):
    html = return_page("777", ["Rucsac Test, Negru"], _COMPLETED_STEPS, ["489000001"], _REFUND, merge_title_and_date=merge)
    ret = _parse(html)
    assert ret.return_id == "777"
    assert ret.order_ids == ["489000001"]
    assert ret.product_names == ["Rucsac Test, Negru"]
    assert ret.steps == ["Cerere inregistrata", "Preluat de catre curier", "Restituire suma"]
    assert ret.refund_bani == 9359
    assert ret.refund_mode == "Vreau banii inapoi"
    assert ret.completed is True and ret.cancelled is False


def test_cancelled_return():
    steps = [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Cerere anulata", "Data: 2 Iulie, 09:00")]
    ret = _parse(return_page("778", ["Produs Test"], steps, ["489000002"]))
    assert ret.completed is False and ret.cancelled is True
    assert ret.refund_bani is None


def test_pending_return_has_no_outcome():
    ret = _parse(return_page("779", ["Produs Test"], [("Cerere inregistrata", "Data: 1 Iulie, 13:44")], ["489000003"]))
    assert ret.completed is False and ret.cancelled is False


@pytest.mark.parametrize("merge", [False, True])
def test_future_steps_without_a_date_do_not_count_as_refund(merge):
    html = return_page("785", ["Produs Test"], [("Cerere inregistrata", "Data: 19 Iunie, 13:42")], ["489000007"],
                       future_steps=["Preluat de catre curier", "Receptionare produs", "Verificare produs", "Restituire suma"],
                       merge_title_and_date=merge)
    ret = _parse(html)
    assert ret.steps == ["Cerere inregistrata"]
    assert ret.completed is False and ret.cancelled is False


def test_cancelled_return_with_listed_future_steps_stays_cancelled():
    steps = [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Cerere anulata", "Data: 2 Iulie, 09:00")]
    ret = _parse(return_page("786", ["Produs Test"], steps, ["489000008"], future_steps=["Restituire suma"]))
    assert ret.completed is False and ret.cancelled is True


def test_voucher_refund_without_amount_is_still_completed():
    steps = [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Restituire suma", "Data: 3 Iulie, 10:00")]
    ret = _parse(return_page("780", ["Produs Test"], steps, ["489000004"], mode="Emitere voucher"))
    assert ret.completed is True
    assert ret.refund_bani is None
    assert ret.refund_mode == "Emitere voucher"


def test_duplicate_product_names_are_preserved():
    names = ["Absorbante Test, 10 bucati", "Spray Test, 200 ml", "Absorbante Test, 10 bucati", "Absorbante Test, 10 bucati"]
    ret = _parse(return_page("781", names, _COMPLETED_STEPS, ["489000005"], _REFUND))
    assert ret.product_names == names


def test_return_referencing_two_orders():
    ret = _parse(return_page("782", ["Produs Test"], _COMPLETED_STEPS, ["489000006", "489000007"], _REFUND))
    assert ret.order_ids == ["489000006", "489000007"]


def test_refund_with_integer_amount():
    ret = _parse(return_page("783", ["Produs Test"], _COMPLETED_STEPS, ["489000008"], "Suma de 129 RON a pornit spre contul tau."))
    assert ret.refund_bani == 12900


def test_personal_data_and_pin_are_never_stored():
    ret = _parse(return_page("784", ["Produs Test"], _COMPLETED_STEPS, ["489000009"], _REFUND))
    dumped = json.dumps(to_dict(ret), ensure_ascii=False)
    for secret in (FAKE_NAME, FAKE_EMAIL, FAKE_PHONE, FAKE_ADDRESS, "ABC123"):
        assert secret not in dumped


def test_labels_and_values_glued_on_the_same_line():
    lines = [
        "Retur #901", "Detalii comanda", "Produs Test", "Status retur", "Cerere inregistrata Data: 1 Iulie, 13:44",
        "Restituire suma Data: 1 Iulie, 16:45", "Suma de 12.50 RON a pornit spre contul tau.",
        "Detalii de contact", "Nume Nume Fictiv", "Modalitate restituire Emitere voucher",
        "Produse din comanda: #489000010 Produs vandut de eMAG #489000011", "Istoricul tau de navigare",
    ]
    ret = parse_return("/x", lines)
    assert ret.refund_mode == "Emitere voucher"
    assert ret.order_ids == ["489000010", "489000011"]
    assert ret.refund_bani == 1250
    assert ret.completed is True


def test_page_without_return_header_raises():
    with pytest.raises(ValueError, match="sesiune expirată"):
        parse_return("/x", ["Autentificare"])
