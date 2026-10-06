"""Testele versiunii programului (emag_spend/version.py): sursa unică, parsarea strictă și compararea X.Y.Z.

Verifică: VERSION e o versiune validă și exact 1.0.0 la prima lansare (decis 5 oct. 2026, D1); parse_version acceptă doar
„X.Y.Z” și „vX.Y.Z” (fără spații, sufixe, zerouri în față, cifre non-ASCII sau numere uriașe); is_newer compară numeric și
refuză tot ce nu se parsează. Ce NU face: nu verifică eticheta git a lansării (asta e treaba lui lansare.yml și a testelor lui).
"""

import pytest

from emag_spend import version
from emag_spend.version import VERSION, is_newer, parse_version


def test_the_program_version_is_a_valid_x_y_z():
    """VERSION se parsează, iar eticheta git corespunzătoare („v” + VERSION) se parsează la aceeași versiune."""
    assert parse_version(VERSION) is not None, f"VERSION = «{VERSION}» nu e de forma X.Y.Z"
    assert parse_version("v" + VERSION) == parse_version(VERSION)


def test_the_first_release_is_1_0_0():
    """Prima lansare cu actualizări e 1.0.0 (D1); la o lansare nouă testul se schimbă odată cu VERSION și CHANGELOG.md."""
    assert VERSION == "1.0.0"


@pytest.mark.parametrize("text, expected", [
    ("1.2.3", (1, 2, 3)), ("v1.2.3", (1, 2, 3)), ("0.0.1", (0, 0, 1)), ("v0.0.0", (0, 0, 0)), ("10.20.30", (10, 20, 30)),
    ("999999.0.0", (999999, 0, 0)),
])
def test_parse_version_accepts_exact_versions(text, expected):
    """Formele acceptate: X.Y.Z și vX.Y.Z, cu numere fără zerouri în față."""
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", [
    "", "1", "1.2", "1.2.3.4", "V1.2.3", "vv1.2.3", " 1.2.3", "1.2.3 ", "1.2.3\n", "1.2.3-beta", "1.2.3+build", "01.2.3", "1.02.3",
    "1.2.03", "1.2.x", "a.b.c", "1..3", "-1.2.3", "1.2.-3", "\u0661.\u0662.\u0663", "1\uff0e2\uff0e3", "1234567.0.0", "v",
    "1.2.3v", "latest",
])
def test_parse_version_refuses_everything_else(text):
    """Orice altceva (spații, sufixe, zerouri în față, cifre arabe sau „late”, numere uriașe, alte separatoare) dă None."""
    assert parse_version(text) is None, f"«{text!r}» nu trebuia acceptat"


@pytest.mark.parametrize("value", [None, 1, 1.2, b"1.2.3", ["1.2.3"], ("1", "2", "3")])
def test_parse_version_returns_none_for_non_text_without_raising(value):
    """Un tip greșit (ex. un câmp JSON neașteptat) nu ridică excepție: dă None."""
    assert parse_version(value) is None


@pytest.mark.parametrize("candidate, current", [
    ("1.0.1", "1.0.0"), ("1.1.0", "1.0.9"), ("2.0.0", "1.99.99"), ("v1.0.1", "1.0.0"), ("1.0.1", "v1.0.0"),
    ("1.10.0", "1.9.0"), ("1.0.10", "1.0.9"), ("10.0.0", "9.9.9"),
])
def test_is_newer_compares_numerically(candidate, current):
    """O versiune strict mai mare e „mai nouă”; compararea e numerică (1.10.0 > 1.9.0), nu ca text."""
    assert is_newer(candidate, current) is True


@pytest.mark.parametrize("candidate, current", [
    ("1.0.0", "1.0.0"), ("v1.0.0", "1.0.0"), ("0.9.9", "1.0.0"), ("1.0.0", "1.0.1"), ("1.9.0", "1.10.0"),
    ("2.0.0", "nu-e-versiune"), ("nu-e-versiune", "1.0.0"), ("", ""), (None, "1.0.0"), ("1.0.1", None),
])
def test_is_newer_refuses_equal_older_and_unparseable(candidate, current):
    """Fără downgrade și fără reinstalarea aceleiași versiuni (D6): egal, mai vechi sau neparsabil → False."""
    assert is_newer(candidate, current) is False


def test_the_digit_cap_is_a_named_constant_used_by_the_parser():
    """Plafonul de cifre pe componentă e constanta cu nume: exact MAX_VERSION_PART_DIGITS cifre trec, una în plus nu."""
    longest = "9" * version.MAX_VERSION_PART_DIGITS
    assert parse_version(f"{longest}.0.0") == (int(longest), 0, 0)
    assert parse_version(f"{longest}9.0.0") is None
