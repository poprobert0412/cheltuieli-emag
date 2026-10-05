"""Teste pentru produse.csv: celulele de text nu au voie să fie evaluate ca formule în Excel (CSV injection).

Numele de produs și vânzătorul vin din pagini controlate de vânzători din marketplace. Toate
valorile de mai jos sunt inventate. Verificăm ce ajunge în fișier, recitit cu `csv.reader`.
"""

import csv

import pytest

from emag_spend.csv_export import write_lines_csv
from emag_spend.models import LineOutcome

HOSTILE_TEXTS = [
    '=HYPERLINK("http://exemplu.invalid/x","Apasa")',
    "+SUM(1+1)",
    "-2+3",
    "@SUM(1+1)",
    "\t=1+1",
    "\r=1+1",
    "=cmd|' /C calc'!A0",
    "   =1+1",  # spațiile din față nu schimbă faptul că Excel poate evalua restul
]
TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
TEXT_COLUMNS = ("comanda", "link_comanda", "vanzator", "produs", "categorie", "regula_categorie", "status_bloc", "retur_id")
ORDER_LINK = "https://www.emag.ro/history/shoppingdetails/"


def _line(name="Produs obisnuit", seller="Vanzator Test", **overrides) -> LineOutcome:
    fields = dict(order_id="100", placed_at="2026-01-02T10:00", seller=seller, name=name, qty=1,
                  line_total_bani=1000, block_status="delivered", kept_qty=1, category="Diverse", rule="regula")
    fields.update(overrides)
    return LineOutcome(**fields)


def _read(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    return [dict(zip(rows[0], row)) for row in rows[1:]]


@pytest.mark.parametrize("hostile", HOSTILE_TEXTS)
def test_product_and_seller_text_that_looks_like_a_formula_gets_a_leading_apostrophe(tmp_path, hostile):
    write_lines_csv(tmp_path / "p.csv", [_line(name=hostile, seller=hostile)], 50000)
    (row,) = _read(tmp_path / "p.csv")
    assert row["produs"] == "'" + hostile and row["vanzator"] == "'" + hostile  # textul original rămâne întreg după apostrof


def test_no_text_column_ever_starts_with_a_formula_character(tmp_path):
    lines = [_line(name=t, seller=t, category=t, rule=t, order_id=t, block_status=t, return_ids=[t]) for t in HOSTILE_TEXTS]
    write_lines_csv(tmp_path / "p.csv", lines, 50000)
    for row in _read(tmp_path / "p.csv"):
        for column in TEXT_COLUMNS:
            assert not row[column].startswith(TRIGGERS), (column, row[column])


def test_ordinary_text_and_generated_numbers_are_left_untouched(tmp_path):
    # suma negativă e generată de program (nu e text din cont): rămâne număr, fără apostrof
    lines = [_line(name="Televizor Alfa 55 inch", line_total_bani=-1250, kept_qty=1), _line(name="3 în 1 Test", seller="Beta SRL")]
    write_lines_csv(tmp_path / "p.csv", lines, 50000)
    first, second = _read(tmp_path / "p.csv")
    assert first["produs"] == "Televizor Alfa 55 inch" and first["pastrat_lei"] == "-12,50" and first["valoare_linie_lei"] == "-12,50"
    assert second["produs"] == "3 în 1 Test" and second["vanzator"] == "Beta SRL"
    assert first["data"] == "2026-01-02" and first["an"] == "2026"


def test_empty_text_cells_stay_empty(tmp_path):
    write_lines_csv(tmp_path / "p.csv", [_line(rule="", category="")], 50000)
    (row,) = _read(tmp_path / "p.csv")
    assert row["regula_categorie"] == "" and row["categorie"] == "" and row["retur_id"] == ""


def test_valid_order_number_gets_its_emag_link_in_its_own_column(tmp_path):
    write_lines_csv(tmp_path / "p.csv", [_line(order_id="489012345")], 50000)
    (row,) = _read(tmp_path / "p.csv")
    assert row["comanda"] == "489012345" and row["link_comanda"] == ORDER_LINK + "489012345"
    header = (tmp_path / "p.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    assert header[:2] == ["comanda", "link_comanda"]


@pytest.mark.parametrize("order_id", ["A", "", "12", "../../x", "489012345/../1", "489012345?x=1", "4890 12345", "\u0661\u0662\u0663\u0664"])
def test_order_number_that_is_not_a_real_number_gets_an_empty_link_cell(tmp_path, order_id):
    write_lines_csv(tmp_path / "p.csv", [_line(order_id=order_id)], 50000)
    (row,) = _read(tmp_path / "p.csv")
    assert row["link_comanda"] == ""


def test_link_cell_never_starts_with_a_formula_character_even_for_hostile_order_numbers(tmp_path):
    lines = [_line(order_id=t) for t in HOSTILE_TEXTS] + [_line(order_id="489012345")]
    write_lines_csv(tmp_path / "p.csv", lines, 50000)
    rows = _read(tmp_path / "p.csv")
    assert all(not row["link_comanda"].startswith(TRIGGERS) for row in rows)
    assert [row["link_comanda"] for row in rows if row["link_comanda"]] == [ORDER_LINK + "489012345"]
