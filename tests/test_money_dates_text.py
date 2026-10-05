"""Teste pentru sume (money_ro), date (dates_ro) și normalizarea textului."""

import pytest

from emag_spend.dates_ro import parse_ro_datetime
from emag_spend.money_ro import (
    find_amount, find_last_amount, format_lei, parse_full_amount, parse_refund_amount, ro_amount_to_bani,
)
from emag_spend.text_normalize import normalize_text


@pytest.mark.parametrize("text,expected", [
    ("1.449,27", 144927), ("-34,00", -3400), ("0,99", 99), ("551,98", 55198),
    ("19.813,51", 1981351), ("1.000.000,00", 100000000), ("-0,05", -5),
])
def test_ro_amount_to_bani(text, expected):
    assert ro_amount_to_bani(text) == expected


def test_parse_full_amount_accepts_only_whole_text():
    assert parse_full_amount("105,99 Lei") == 10599
    assert parse_full_amount("105,99") == 10599
    assert parse_full_amount("-34,00 Lei") == -3400
    assert parse_full_amount("Total 1,00 Lei") is None
    assert parse_full_amount("GRATUIT") is None
    assert parse_full_amount("") is None


def test_find_amount_and_last_amount():
    assert find_amount("Total: 190,47 Lei") == 19047
    assert find_amount("fara suma") is None
    assert find_amount(": 1,49 Lei") == 149
    assert find_last_amount("a 1,00 Lei b 2,50 Lei") == 250
    assert find_last_amount("nimic") is None


@pytest.mark.parametrize("text,expected", [
    ("93.59", 9359), ("129", 12900), ("249.9", 24990), ("1.449", 144900),
    ("1.449,27", 144927), ("0.5", 50), ("", None), ("abc", None), ("12.3.4", None),
])
def test_parse_refund_amount(text, expected):
    assert parse_refund_amount(text) == expected


@pytest.mark.parametrize("bani,expected", [
    (144927, "1.449,27 Lei"), (-3400, "-34,00 Lei"), (5, "0,05 Lei"), (0, "0,00 Lei"),
    (100000000, "1.000.000,00 Lei"), (99999, "999,99 Lei"),
])
def test_format_lei(bani, expected):
    assert format_lei(bani) == expected


def test_format_and_parse_roundtrip():
    for bani in (1, 99, 100, 12345, 987654321):
        assert ro_amount_to_bani(format_lei(bani).replace(" Lei", "")) == bani


@pytest.mark.parametrize("text,expected", [
    ("26 mai 2026, 10:07", "2026-05-26T10:07"),
    ("9 decembrie 2023", "2023-12-09T00:00"),
    ("29 ian 2026, 09:46", "2026-01-29T09:46"),
    ("12 noi 2024, 23:59", "2024-11-12T23:59"),
    ("3 oct 2026, 18:21", "2026-10-03T18:21"),
    ("19 iulie 2026", "2026-07-19T00:00"),
    ("15 iun 2026, 13:15", "2026-06-15T13:15"),
    ("1 Iulie, 13:44", None),
    ("fara data", None),
    ("", None),
    ("5 xyz 2026", None),
])
def test_parse_ro_datetime(text, expected):
    assert parse_ro_datetime(text) == expected


def test_normalize_text():
    assert normalize_text("Ţelină  Șampon") == "telina sampon"
    assert normalize_text("  ÎNCĂLȚĂMINTE\n") == "incaltaminte"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""
