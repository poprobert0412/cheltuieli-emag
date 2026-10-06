"""Trimiterile din cod la decizii, față de tabelul din docs/DECIZII.md: fiecare Id citat are un rând, fiecare rând e citat.

Primește: tot ce urcă în git (tests.garda_support.files_to_publish), fără tabel, fără acest fișier și fără binare; tabelul din
docs/DECIZII.md. Verifică: (1) fiecare trimitere D…, N…, P… din cod („decis 6 oct. 2026, N13”, „D2/D4”, „N8a”) și fiecare membru al
unui interval („P1–P8” = P1, P2, …, P8) are un rând în coloana Id; (2) fiecare Id din tabel e citat măcar o dată în cod (altfel rândul e
mort); (3) tabelul are coloana Id prima, iar Id-urile au forma literă + număr (+ a–d) și nu se repetă; (4) excepțiile (potriviri care
nu sunt trimiteri, ca „Vitamina D3” din catalogul demonstrativ) au motiv scris și mai sunt necesare; (5) trimiterile din textul
tabelului („refăcut prin N5”, „ca la P8”) au și ele rândul lor. Fiecare detector și fiecare comparație sunt probate pe text-capcană.
De ce: README trimite la „deciziile deja luate”, iar cine urmează o trimitere din cod trebuie să găsească decizia.
Ce NU face: nu judecă textul deciziilor, data sau coloana „Unde”, și nu cunoaște constatările de audit (R1, S1, J3, C4, V2-3).
"""

import functools
import re
from collections.abc import Container, Iterable
from pathlib import Path

import pytest

from tests.garda_support import PROJECT_ROOT, files_to_publish, read_text_or_none, relative

DECISIONS_FILE = PROJECT_ROOT / "docs" / "DECIZII.md"
HEADER = ["Id", "Data", "Decizia", "Unde"]
# Rândul unei decizii fără Id în cod (de exemplu sesiunea eMAG, 4 oct. 2026).
NO_ID = "—"
# Seriile de decizii: D (5 oct. 2026), N și P (6 oct. 2026). Celelalte litere din teste sunt constatări de audit, nu decizii.
SERIES = "DNP"
# O trimitere: litera seriei, una sau două cifre și, opțional, o literă a–d (N8a), ca un cuvânt întreg („ID1”, „D123” nu sunt).
REFERENCE = re.compile(rf"\b[{SERIES}][0-9]{{1,2}}[a-d]?\b")
# Un interval din aceeași serie, cu liniuță lungă sau scurtă, pe același rând: „N1–N14” trimite și la N2, N3, …, N13. Fără
# salt de rând între capete: „D2” la capăt de rând și „- D9” la începutul unui punct de listă nu fac din D3…D8 trimiteri.
RANGE = re.compile(rf"\b([{SERIES}])([0-9]{{1,2}})[ \t]*[–-][ \t]*\1([0-9]{{1,2}})\b")
ID_FORMAT = re.compile(rf"[{SERIES}][0-9]{{1,2}}[a-d]?")
# Ce nu se caută: tabelul (altfel orice rând s-ar cita singur) și acest fișier (are Id-uri ca exemple și ca text-capcană).
NOT_SCANNED = frozenset({relative(DECISIONS_FILE), relative(Path(__file__))})
# Fișiere fără text de citit: imagini, fonturi, arhive.
BINARY_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".woff", ".woff2", ".zip", ".pdf"})
MIN_REASON_LENGTH = 30
# EXCEPȚII text -> motiv: potriviri ale lui REFERENCE care nu sunt trimiteri la decizii; se scot din text înainte de căutare.
# Testul de necesitate de mai jos pică imediat ce una nu mai apare, ca lista să nu rămână deschisă.
NOT_REFERENCES = {
    "Vitamina D3": "numele unui produs inventat din catalogul demonstrativ (emag_spend/demo_catalog.py și demo-data.js făcut din el)",
}


def references_in(text: str) -> set[str]:
    """Id-urile la care trimite `text`: fiecare potrivire a lui REFERENCE și fiecare membru al unui interval, fără NOT_REFERENCES."""
    for phrase in NOT_REFERENCES:
        text = text.replace(phrase, " ")
    found = set(REFERENCE.findall(text))
    for series, first, last in RANGE.findall(text):
        found.update(f"{series}{number}" for number in range(int(first), int(last) + 1))
    return found


def table_rows(markdown: str) -> list[list[str]]:
    """Celulele fiecărui rând de tabel din `markdown` (rânduri care încep cu «|»), inclusiv antetul și rândul |---|."""
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in markdown.splitlines() if line.startswith("|")]


def ids_in_cell(cell: str) -> list[str]:
    """Id-urile dintr-o celulă a coloanei Id („N5” sau „D2, D18”); niciunul pentru NO_ID."""
    return [] if cell == NO_ID else [part.strip() for part in cell.split(",")]


def table_ids(markdown: str) -> list[str]:
    """Id-urile din prima coloană a tabelului, în ordinea rândurilor (cu repetări, dacă există)."""
    return [ident for row in table_rows(markdown)[2:] for ident in ids_in_cell(row[0])]


def ids_without_row(markdown: str, cited: Iterable[str]) -> list[str]:
    """(1) Id-urile din `cited` care nu au rând în coloana Id a tabelului din `markdown`, sortate."""
    in_table = set(table_ids(markdown))
    return sorted(ident for ident in cited if ident not in in_table)


def rows_not_cited(markdown: str, cited: Container[str]) -> list[str]:
    """(2) Id-urile din coloana Id a tabelului din `markdown` care nu sunt în `cited`, în ordinea rândurilor."""
    return [ident for ident in table_ids(markdown) if ident not in cited]


def ids_cited_in_the_table_text(markdown: str) -> set[str]:
    """(5) Id-urile la care trimit celulele Data, Decizia și Unde ale rândurilor de date („Lacătul e refăcut prin N5”)."""
    return {ident for row in table_rows(markdown)[2:] for cell in row[1:] for ident in references_in(cell)}


def _scanned_files() -> list[Path]:
    """Fișierele în care se caută trimiterile: tot ce urcă în git, fără NOT_SCANNED și fără binare."""
    return [path for path in files_to_publish() if path.suffix.lower() not in BINARY_SUFFIXES and relative(path) not in NOT_SCANNED]


@functools.lru_cache(maxsize=None)
def cited_ids() -> dict[str, tuple[str, ...]]:
    """Id -> fișierele (căi relative) care îl citează, din tot ce urcă în git."""
    places: dict[str, list[str]] = {}
    for path in _scanned_files():
        text = read_text_or_none(path)
        for ident in references_in(text or ""):
            places.setdefault(ident, []).append(relative(path))
    return {ident: tuple(found) for ident, found in places.items()}


def _decisions_text() -> str:
    """Textul lui docs/DECIZII.md."""
    return DECISIONS_FILE.read_text(encoding="utf-8")


# ---------- pe fișierele reale ----------

def test_the_table_starts_with_the_id_column_and_every_row_has_four_cells():
    """Tabelul are antetul Id | Data | Decizia | Unde și fiecare rând are exact patru celule (o «|» în plus ar muta coloanele)."""
    rows = table_rows(_decisions_text())
    assert rows and rows[0] == HEADER, rows[:1]
    assert len(rows) > 2, "tabelul nu are niciun rând: testul n-ar dovedi nimic"
    wrong = [row for row in rows if len(row) != len(HEADER)]
    assert not wrong, f"rânduri fără exact {len(HEADER)} celule: {wrong}"


def test_every_id_in_the_table_has_the_expected_form_and_appears_once():
    """Fiecare Id din tabel e literă + număr (+ a–d) sau NO_ID, și niciun Id nu are două rânduri."""
    ids = table_ids(_decisions_text())
    malformed = [ident for ident in ids if not ID_FORMAT.fullmatch(ident)]
    repeated = sorted({ident for ident in ids if ids.count(ident) > 1})
    assert not malformed, f"Id-uri cu altă formă (folosește {NO_ID!r} pentru un rând fără Id): {malformed}"
    assert not repeated, f"Id-uri cu mai multe rânduri: {repeated}"


def test_every_decision_cited_in_the_code_has_a_row():
    """(1) Fiecare Id citat în cod are rândul lui în docs/DECIZII.md: cine urmează trimiterea găsește decizia."""
    cited = cited_ids()
    missing = {ident: cited[ident] for ident in ids_without_row(_decisions_text(), cited)}
    assert not missing, (
        "Id-uri citate în cod, fără rând în docs/DECIZII.md (adaugă rândul: Id, data, decizia într-o frază, unde):\n  "
        + "\n  ".join(f"{ident}: {', '.join(places[:5])}" for ident, places in sorted(missing.items())))


def test_every_row_with_an_id_is_cited_in_the_code():
    """(2) Fiecare Id din tabel e citat măcar o dată în cod; un Id pe care nu-l mai citează nimeni e un rând mort."""
    dead = rows_not_cited(_decisions_text(), cited_ids())
    assert not dead, (f"Id-uri din docs/DECIZII.md pe care nu le mai citează niciun fișier (decizia rămâne: pune {NO_ID!r} "
                      f"în coloana Id): {dead}")


def test_every_decision_cited_in_the_table_text_has_a_row():
    """(5) Trimiterile dintr-un rând la alt rând („refăcut prin N5”, „restrânge N12”) duc și ele la un rând din coloana Id."""
    text = _decisions_text()
    missing = ids_without_row(text, ids_cited_in_the_table_text(text))
    assert not missing, f"Id-uri citate în textul tabelului, fără rând în coloana Id: {missing}"


def test_the_scan_covers_the_program_the_tests_the_launchers_and_the_workflows():
    """Lista citită conține chiar codul care trimite la decizii, dar nu și tabelul (altfel garda n-ar dovedi nimic)."""
    scanned = {relative(path) for path in _scanned_files()}
    for needed in ("ruleaza.py", "emag_spend/update_apply.py", "tests/test_site_static.py", "porneste.bat", "porneste.sh",
                   ".github/workflows/lansare.yml", "interfata/assets/app-update.js"):
        assert needed in scanned, f"{needed} nu e citit de garda deciziilor"
    assert relative(DECISIONS_FILE) not in scanned
    assert {"D1", "N13", "P1"} <= set(cited_ids()), sorted(cited_ids())


def test_exceptions_are_justified_and_still_needed():
    """Fiecare excepție are motiv scris, chiar ar fi luată drept trimitere și încă apare în cod; când dispare, se scoate."""
    texts = [read_text_or_none(path) or "" for path in _scanned_files()]
    for phrase, reason in NOT_REFERENCES.items():
        assert len(reason.strip()) >= MIN_REASON_LENGTH, f"excepția «{phrase}» nu are motiv scris"
        assert REFERENCE.search(phrase), f"«{phrase}» nu ar fi luată drept trimitere: excepția e de prisos"
        assert any(phrase in text for text in texts), f"«{phrase}» nu mai apare în cod: scoate excepția din NOT_REFERENCES"


# ---------- detectorul probat pe text-capcană ----------

@pytest.mark.parametrize("text, expected", [
    ("Garda (decis 6 oct. 2026, N16): ...", {"N16"}),
    ("D2/D4: o singură cerere", {"D2", "D4"}),
    ("(D8–D11, D14; N1, N4, N6, P2–P4 din 6 oct. 2026)", {"D8", "D9", "D10", "D11", "D14", "N1", "N4", "N6", "P2", "P3", "P4"}),
    ("N8b, S1/J3, P8: legătură", {"N8b", "P8"}),
    ("decis de Robert pe 5 oct. 2026", set()),
    ("Vezi D2\n- D9 pe rândul următor", {"D2", "D9"}),
])
def test_the_detector_finds_references_and_ranges(text, expected):
    """Trimiterile simple, cele cu literă (N8b), cele lipite cu «/» și fiecare membru al unui interval sunt găsite."""
    assert references_in(text) == expected


@pytest.mark.parametrize("text", [
    "Supliment alimentar Vitamina D3 2000 UI",
    "R1, S2, J7, C4, V1-1, V2-3",
    "ID1, PD1, 1D2, D123, N8e, x86_64",
])
def test_the_detector_ignores_what_is_not_a_reference(text):
    """Fals pozitiv: excepțiile, constatările de audit și cuvintele care doar conțin o literă și o cifră nu sunt trimiteri."""
    assert references_in(text) == set()


def test_the_table_reader_takes_ids_only_from_the_first_column():
    """Coloana Id se citește din primul rând de date în jos; NO_ID nu e un Id, iar „D2, D18” înseamnă două Id-uri."""
    markdown = ("Text cu D7.\n\n| Id | Data | Decizia | Unde |\n|---|---|---|---|\n"
                f"| {NO_ID} | 4 oct. 2026 | Ceva fără Id, dar cu N5 în text. | `a.py` |\n| D2, D18 | 5 oct. 2026 | Altceva. | `b.py` |\n")
    assert table_ids(markdown) == ["D2", "D18"]
    assert table_rows(markdown)[0] == HEADER


def test_a_new_reference_without_a_row_and_a_row_nobody_cites_are_caught():
    """Capcană pentru (1), (2) și (5): o trimitere nouă „(decis 7 oct. 2026, D99)” fără rând, un rând scos (N13) și unul necitat (D1)."""
    markdown = ("| Id | Data | Decizia | Unde |\n|---|---|---|---|\n"
                "| D1 | 5 oct. 2026 | Ceva. | `a.py` |\n| N5 | 6 oct. 2026 | Altceva, refăcut prin N6. | `b.py` |\n")
    cited = references_in("# Ceva nou (decis 7 oct. 2026, D99).\n# Lacătul (decis 6 oct. 2026, N5); lansarea (N13).\n")
    assert ids_without_row(markdown, cited) == ["D99", "N13"]
    assert rows_not_cited(markdown, cited) == ["D1"]
    assert ids_without_row(markdown, ids_cited_in_the_table_text(markdown)) == ["N6"]
