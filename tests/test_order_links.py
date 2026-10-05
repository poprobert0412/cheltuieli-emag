"""Teste pentru adresele comenzilor și retururilor către eMAG (numere inventate).

Numărul vine din analiza.json, care poate fi încărcat din orice sursă: orice număr care nu e
format doar din 3–15 cifre ASCII trebuie să dea None, niciodată o adresă.
"""

import pytest

from emag_spend import settings
from emag_spend.order_links import ORDER_ID_PATTERN, ORDER_URL_PREFIX, is_valid_order_id, order_url, return_url

ORDER_PREFIX = "https://www.emag.ro/history/shoppingdetails/"
HOSTILE_IDS = [
    "", " ", "abc", "12a45", "12", "1" * 16, " 123456", "123456 ", "123456\n", "\n123456", "123456\n789",
    "../../x", "..", "123/456", "123\\456", "123?x=1", "123#a", "123%2e", "12 34", "-123456", "+123456", "1.5e3",
    "١٢٣٤٥٦",  # cifre arabo-indice: \d le-ar accepta, [0-9] nu
    "１２３４５６",  # cifre pe lățime întreagă
    "123456​", "123456\x00", "javascript:alert(1)",
]


def test_valid_order_number_gives_the_exact_address_without_parameters():
    assert order_url("489012345") == ORDER_PREFIX + "489012345"
    assert "?" not in order_url("489012345") and "#" not in order_url("489012345")
    assert ORDER_URL_PREFIX == ORDER_PREFIX


def test_address_parts_come_from_the_single_source_of_emag_paths_in_settings():
    assert ORDER_URL_PREFIX == settings.BASE_URL + settings.ORDER_DETAIL_PATH.format(order_id="")


@pytest.mark.parametrize("number", ["100", "1" * 15, "000123", "489012345"])
def test_three_to_fifteen_digits_are_accepted(number):
    assert order_url(number) == ORDER_PREFIX + number and is_valid_order_id(number)


@pytest.mark.parametrize("number", HOSTILE_IDS)
def test_anything_that_is_not_three_to_fifteen_ascii_digits_gives_no_link(number):
    assert order_url(number) is None and not is_valid_order_id(number)
    assert return_url(number, f"/user/return-history/1/{number}") is None


@pytest.mark.parametrize("not_text", [None, 489012345, 4.9, ["489012345"], b"489012345", object()])
def test_a_value_that_is_not_text_gives_no_link(not_text):
    assert order_url(not_text) is None and not is_valid_order_id(not_text)
    assert return_url(not_text, "/user/return-history/1/489012345") is None


def test_pattern_constant_is_the_one_the_javascript_side_repeats():
    assert ORDER_ID_PATTERN == "[0-9]{3,15}"


def test_return_address_uses_the_real_path_shape_with_its_extra_segment():
    # adresa reală a unui retur are un segment numeric în plus față de numărul returului (vezi return_list_scraper.py)
    assert return_url("3001291", "/user/return-history/1/3001291") == "https://www.emag.ro/user/return-history/1/3001291"
    assert return_url("3001291", "/user/return-history/12/3001291") == "https://www.emag.ro/user/return-history/12/3001291"


def test_return_address_cannot_be_guessed_from_the_number_alone():
    assert return_url("3001291") is None and return_url("3001291", None) is None


@pytest.mark.parametrize("path", [
    "/user/return-history/1/3001292",  # alt număr decât cel cerut
    "/user/return-history/1/3001291/extra", "/user/return-history/3001291", "/user/return-history//3001291",
    "/user/return-history/a/3001291", "/user/return-history/1/3001291?x=1", "/user/return-history/../3001291",
    "https://alt-site.invalid/user/return-history/1/3001291", "//alt-site.invalid/user/return-history/1/3001291",
    "/user/return-history/1/3001291\n", "/history/shoppingdetails/3001291", "", 3001291,
])
def test_return_address_requires_the_exact_saved_path_for_that_number(path):
    assert return_url("3001291", path) is None


def test_dashboard_script_repeats_the_same_constants_when_it_builds_order_links():
    # Paritate Python <-> JS: se activează singură când dashboard.js începe să construiască linkuri
    # (până atunci e SĂRITĂ, nu verde: apare în raportul pytest ca skipped).
    script = settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8")
    if "shoppingdetails" not in script:
        pytest.skip("dashboard.js nu construiește încă linkuri către comenzi (se face în etapa interfeței)")
    assert ORDER_PREFIX in script
    assert ORDER_ID_PATTERN in script
