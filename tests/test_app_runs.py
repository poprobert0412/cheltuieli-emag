"""Teste pentru lista și citirea rulărilor din iesiri/ (emag_spend/app_runs.py), în foldere temporare cu rulări inventate.

Verifică: doar foldere cu nume valid, cifrele citite din analiza.json, fișiere lipsă sau stricate tolerate, limite de mărime,
lista albă de descărcări și, mai ales, că nimic nu iese din iesiri/ (joncțiuni, legături simbolice, id-uri cu `..`).
Fiecare test de siguranță spune în mesaj ce s-a încălcat și de ce contează.
"""

import json
import os
from pathlib import Path

import pytest

from emag_spend import app_runs, app_security

RUN_A = "2026-10-05_09-00-00"
RUN_B = "2026-10-05_12-30-15_demo"
RUN_C = "2026-10-06_08-00-00"
SECRET_MARKER = "SECRET-INVENTAT-DIN-AFARA-IESIRILOR"
# Liste imbricate de 100.000 de ori: parserul JSON ar depăși adâncimea recursiei (RecursionError), iar codul trebuie să-l prindă.
# În parametrii testelor apare ca „IMBRICAT” (un id de test de 100.000 de caractere ar strica pytest).
NESTED_JSON = "[" * 100000


def make_run(base: Path, run_id: str, *, orders: int | None = 12, kept_bani: int | None = 345600, spent_bani: int | None = None,
             report: bool = True, extra: dict[str, str] | None = None) -> Path:
    """Un folder de rulare inventat; `orders=None` înseamnă fără analiza.json; `spent_bani=None` = analiză veche, fără secțiunea `paid`."""
    folder = base / run_id
    folder.mkdir(parents=True)
    if orders is not None:
        analysis = {"meta": {"orders": orders}, "funnel": {"kept_bani": kept_bani}}
        if spent_bani is not None:
            analysis["paid"] = {"spent_bani": spent_bani, "spent_units": 4}
        (folder / "analiza.json").write_text(json.dumps(analysis), encoding="utf-8")
    if report:
        (folder / "raport.html").write_text("<html>raport inventat</html>", encoding="utf-8")
    for name, content in (extra or {}).items():
        (folder / name).write_text(content, encoding="utf-8")
    return folder


def make_directory_link(link: Path, target: Path) -> bool:
    """O joncțiune (Windows, nu cere drepturi speciale) sau o legătură simbolică la folder; False dacă sistemul nu permite."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, ImportError, AttributeError):
        return False


@pytest.fixture
def outputs(tmp_path) -> Path:
    """Un folder iesiri/ gol, lângă un folder „din afară” cu un fișier secret inventat."""
    base = tmp_path / "iesiri"
    base.mkdir()
    outside = tmp_path / "in_afara"
    outside.mkdir()
    (outside / "analiza.json").write_text(json.dumps({"meta": {"orders": 999}, "funnel": {"kept_bani": 1}, "secret": SECRET_MARKER}), encoding="utf-8")
    (outside / "raport.html").write_text(SECRET_MARKER, encoding="utf-8")
    return base


# ---------- lista ----------

def test_list_has_the_contract_fields_newest_first(outputs):
    """GET /api/runs: id, created_at, kind, orders, kept_bani, spent_bani, has_report; cele mai noi întâi.

    `spent_bani` vine din `paid.spent_bani` (analizele noi) și e null la analizele vechi, fără secțiunea `paid`.
    """
    make_run(outputs, RUN_A)
    make_run(outputs, RUN_B, orders=7, kept_bani=1000, spent_bani=950)
    make_run(outputs, RUN_C, orders=20, kept_bani=5000, report=False)
    runs = app_runs.RunsStore(outputs).list_runs()
    assert [run["id"] for run in runs] == [RUN_C, RUN_B, RUN_A]
    assert runs[0] == {"id": RUN_C, "created_at": "2026-10-06T08:00:00", "kind": "real", "orders": 20, "kept_bani": 5000, "spent_bani": None, "has_report": False}
    assert runs[1] == {"id": RUN_B, "created_at": "2026-10-05T12:30:15", "kind": "demo", "orders": 7, "kept_bani": 1000, "spent_bani": 950, "has_report": True}
    assert set(runs[2]) == {"id", "created_at", "kind", "orders", "kept_bani", "spent_bani", "has_report"}


def test_folders_with_invalid_names_files_and_stray_entries_are_ignored(outputs):
    """Foldere cu nume invalid (și fișiere cu nume valid de rulare) nu apar în listă: doar numele exacte de rulare contează."""
    make_run(outputs, RUN_A)
    for bad in ("2026-10-05_09-00-00.bak", "backup", "2026-10-05_09-00-00_DEMO", "2026-13-01_00-00-00", "x2026-10-05_09-00-00", ".git", "iesiri vechi"):
        (outputs / bad).mkdir()
        (outputs / bad / "analiza.json").write_text("{}", encoding="utf-8")
    (outputs / "2026-10-07_10-00-00").write_text("nu e folder", encoding="utf-8")  # fișier cu nume valid de rulare
    (outputs / "note.txt").write_text("x", encoding="utf-8")
    assert [run["id"] for run in app_runs.RunsStore(outputs).list_runs()] == [RUN_A]


def test_a_missing_outputs_folder_gives_an_empty_list(tmp_path):
    """La prima pornire iesiri/ nu există încă: lista e goală, nu o eroare."""
    assert app_runs.RunsStore(tmp_path / "nu_exista").list_runs() == []


def test_an_interrupted_run_without_analysis_is_listed_with_null_numbers(outputs):
    """O rulare oprită la jumătate (fără analiza.json) apare în listă, cu orders, kept_bani și spent_bani null și fără raport."""
    make_run(outputs, RUN_A, orders=None, report=False, extra={"comenzi.json": "[]"})
    (run,) = app_runs.RunsStore(outputs).list_runs()
    assert run["orders"] is None and run["kept_bani"] is None and run["spent_bani"] is None and run["has_report"] is False


@pytest.mark.parametrize("content", ["", "nu e json", "[1, 2]", "42", '{"meta": 5, "funnel": []}', '{"meta": {"orders": "12"}, "funnel": {"kept_bani": 1.5}}',
                                     '{"meta": {"orders": true}, "funnel": {"kept_bani": null}}', '{"meta": {"orders": NaN}}', "﻿{}", "IMBRICAT",
                                     '{"paid": [1]}', '{"paid": {"spent_bani": "950"}}', '{"paid": {"spent_bani": 9.5}}', '{"paid": {"spent_bani": false}}'])
def test_a_broken_or_unexpected_analysis_does_not_break_the_list(outputs, content):
    """Analiză stricată, de alt tip, cu NaN sau imbricată absurd: rularea rămâne în listă, cifrele devin null, iar lista nu pică."""
    folder = make_run(outputs, RUN_A, orders=None)
    (folder / "analiza.json").write_text(NESTED_JSON if content == "IMBRICAT" else content, encoding="utf-8")
    (run,) = app_runs.RunsStore(outputs).list_runs()
    assert run["id"] == RUN_A and run["orders"] is None and run["kept_bani"] is None and run["spent_bani"] is None, f"cifre luate dintr-o analiză nevalidă: {run}"


def test_an_oversized_analysis_is_not_read_for_the_list(outputs, monkeypatch):
    """O analiză mai mare decât limita nu se citește deloc în memorie: cifrele rămân null."""
    make_run(outputs, RUN_A)
    monkeypatch.setattr(app_runs, "MAX_ANALYSIS_BYTES", 10)
    (run,) = app_runs.RunsStore(outputs).list_runs()
    assert run["orders"] is None and run["kept_bani"] is None and run["spent_bani"] is None


def test_only_the_three_needed_fields_are_taken_from_the_analysis(outputs):
    """Din analiza.json se iau doar meta.orders, funnel.kept_bani și paid.spent_bani; restul (poate uriaș) nu ajunge în listă."""
    folder = make_run(outputs, RUN_A)
    (folder / "analiza.json").write_text(json.dumps({"meta": {"orders": 3, "alt": "x"}, "funnel": {"kept_bani": 9}, "paid": {"spent_bani": 8, "extra_rows": [1] * 50},
                                                     "orders": {"cheie": "mare"}, "warnings": ["a"] * 50}), encoding="utf-8")
    (run,) = app_runs.RunsStore(outputs).list_runs()
    assert set(run) == {"id", "created_at", "kind", "orders", "kept_bani", "spent_bani", "has_report"} and (run["orders"], run["kept_bani"], run["spent_bani"]) == (3, 9, 8)


def test_the_list_is_capped_at_the_newest_runs(outputs, monkeypatch):
    """Lista are un plafon (cele mai noi MAX_LISTED_RUNS): mii de foldere vechi nu încetinesc pagina."""
    for day in range(1, 8):
        make_run(outputs, f"2026-10-0{day}_10-00-00", orders=None, report=False)
    monkeypatch.setattr(app_runs, "MAX_LISTED_RUNS", 3)
    runs = app_runs.RunsStore(outputs).list_runs()
    assert [run["id"] for run in runs] == ["2026-10-07_10-00-00", "2026-10-06_10-00-00", "2026-10-05_10-00-00"]


def test_the_summary_is_cached_until_the_file_changes(outputs, monkeypatch):
    """Analiza nu se parsează din nou la fiecare cerere de listă, dar o analiză rescrisă se recitește."""
    folder = make_run(outputs, RUN_A, orders=3, kept_bani=30)
    store = app_runs.RunsStore(outputs)
    parses = []
    real = app_security.parse_strict_json
    monkeypatch.setattr(app_security, "parse_strict_json", lambda data: parses.append(1) or real(data))
    first = store.list_runs()
    second = store.list_runs()
    assert first == second and len(parses) == 1, f"analiza s-a parsat de {len(parses)} ori pentru două liste"
    (folder / "analiza.json").write_text(json.dumps({"meta": {"orders": 4}, "funnel": {"kept_bani": 40}}) + "  ", encoding="utf-8")
    assert store.list_runs()[0]["orders"] == 4, "analiza rescrisă nu s-a recitit"


# ---------- citirea analizei ----------

def test_read_analysis_returns_the_exact_json_bytes(outputs):
    """GET /api/runs/<id>/analysis dă exact conținutul analiza.json."""
    folder = make_run(outputs, RUN_A)
    assert app_runs.RunsStore(outputs).read_analysis(RUN_A) == (folder / "analiza.json").read_bytes()


def test_read_analysis_of_a_missing_run_or_file_is_not_found(outputs):
    """Rulare inexistentă, fără analiză sau cu analiza ca folder: RunNotFound (404), nu o eroare internă."""
    make_run(outputs, RUN_A, orders=None)
    store = app_runs.RunsStore(outputs)
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis("2030-01-01_00-00-00")
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis(RUN_A)
    (outputs / RUN_A / "analiza.json").mkdir()
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis(RUN_A)


@pytest.mark.parametrize("content", ["nu e json", "", "[1]", '{"a": NaN}', '{"a": Infinity}', "IMBRICAT", "﻿{}"])
def test_read_analysis_refuses_invalid_json_with_a_stable_code(outputs, content):
    """JSON stricat, de alt tip, cu NaN/Infinity (pe care JSON.parse din browser nu le acceptă) sau imbricat absurd: RunFileUnreadable(analysis_invalid)."""
    folder = make_run(outputs, RUN_A, orders=None)
    (folder / "analiza.json").write_text(NESTED_JSON if content == "IMBRICAT" else content, encoding="utf-8")
    with pytest.raises(app_runs.RunFileUnreadable) as error:
        app_runs.RunsStore(outputs).read_analysis(RUN_A)
    assert error.value.code == "analysis_invalid" and "analiza.json" in error.value.message


def test_read_analysis_refuses_a_file_over_the_size_limit(outputs, monkeypatch):
    """O analiză peste limită nu se trimite: RunFileUnreadable(analysis_too_large), cu mesaj în română."""
    make_run(outputs, RUN_A)
    monkeypatch.setattr(app_runs, "MAX_ANALYSIS_BYTES", 10)
    with pytest.raises(app_runs.RunFileUnreadable) as error:
        app_runs.RunsStore(outputs).read_analysis(RUN_A)
    assert error.value.code == "analysis_too_large" and "prea mare" in error.value.message


def test_the_size_limit_matches_the_site_viewer_limit():
    """Limita analizei e aceeași cu a vizualizatorului din site (25 MB): un fișier pe care pagina oricum nu l-ar deschide nu se citește."""
    assert app_runs.MAX_ANALYSIS_BYTES == 25 * 1024 * 1024


# ---------- descărcări ----------

def test_whitelisted_files_are_returned_with_their_content_type(outputs):
    """Cele 4 fișiere din lista albă se citesc, cu tipul potrivit."""
    make_run(outputs, RUN_A, extra={"produse.csv": "a;b", "istoric_preturi.csv": "c;d", "rezumat.txt": "text"})
    store = app_runs.RunsStore(outputs)
    assert store.read_download(RUN_A, "raport.html") == (b"<html>raport inventat</html>", "text/html; charset=utf-8")
    assert store.read_download(RUN_A, "produse.csv") == (b"a;b", "text/csv; charset=utf-8")
    assert store.read_download(RUN_A, "istoric_preturi.csv")[1] == "text/csv; charset=utf-8"
    assert store.read_download(RUN_A, "rezumat.txt")[1] == "text/plain; charset=utf-8"


@pytest.mark.parametrize("name", ["analiza.json", "comenzi.json", "retururi.json", "run_info.json", "RAPORT.HTML", "raport.html ", "../analiza.json", "sub/raport.html", "", None])
def test_files_outside_the_whitelist_cannot_be_downloaded_even_if_they_exist(outputs, name):
    """comenzi.json, retururi.json (date personale brute) și orice nume neexact: RunNotFound, chiar dacă fișierul există."""
    make_run(outputs, RUN_A, extra={"comenzi.json": "[1]", "retururi.json": "[2]", "run_info.json": "{}"})
    with pytest.raises(app_runs.RunNotFound):
        app_runs.RunsStore(outputs).read_download(RUN_A, name)


def test_a_missing_whitelisted_file_is_not_found_and_an_oversized_one_is_refused(outputs, monkeypatch):
    """Fișier din lista albă lipsă: RunNotFound; peste limită: RunFileUnreadable(file_too_large)."""
    make_run(outputs, RUN_A, report=False, extra={"produse.csv": "x" * 50})
    store = app_runs.RunsStore(outputs)
    with pytest.raises(app_runs.RunNotFound):
        store.read_download(RUN_A, "raport.html")
    monkeypatch.setattr(app_runs, "MAX_DOWNLOAD_BYTES", 10)
    with pytest.raises(app_runs.RunFileUnreadable) as error:
        store.read_download(RUN_A, "produse.csv")
    assert error.value.code == "file_too_large"


# ---------- nimic nu iese din iesiri/ ----------

@pytest.mark.parametrize("run_id", ["..", ".", "../in_afara", "..\\in_afara", "2026-10-05_09-00-00/../../in_afara", "in_afara", "", "2026-10-05_09-00-00/", None])
def test_run_ids_with_traversal_never_read_outside_the_outputs_folder(outputs, run_id):
    """Un id cu `..`, separatori sau fără forma exactă nu citește fișierul secret din folderul vecin (analiza și descărcarea dau RunNotFound)."""
    store = app_runs.RunsStore(outputs)
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis(run_id)
    with pytest.raises(app_runs.RunNotFound):
        store.read_download(run_id, "raport.html")


@pytest.mark.parametrize("name", ["backup", "x", "2026-10-05_09-00-00.bak", "2026-10-05_09-00-00 copie", "2026-10-05_09-00-00_demo_demo", "2026-13-01_00-00-00"])
def test_a_real_folder_with_an_invalid_run_name_is_not_readable_by_id(outputs, name):
    """Un folder real din iesiri/ al cărui nume NU e un id de rulare (backup, sufix .bak, dată imposibilă) nu se citește prin id, deși există: validarea numelui e apărarea de bază."""
    make_run(outputs, name)
    store = app_runs.RunsStore(outputs)
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis(name)
    with pytest.raises(app_runs.RunNotFound):
        store.read_download(name, "raport.html")


def test_a_different_letter_case_never_reaches_a_folder_on_a_case_insensitive_disk(outputs):
    """Pe Windows `..._demo` și `..._DEMO` ar fi același folder: id-ul cerut trebuie să coincidă EXACT cu numele de pe disc, altfel RunNotFound (nume neexact = alt id)."""
    make_run(outputs, "2026-10-05_09-00-00_DEMO")
    store = app_runs.RunsStore(outputs)
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis("2026-10-05_09-00-00_demo")
    assert store.list_runs() == [], "un folder cu litere mari în nume a ajuns în listă"


def test_a_junction_or_symlink_run_folder_pointing_outside_is_neither_listed_nor_readable(outputs):
    """Un „folder de rulare” care e de fapt o joncțiune/legătură spre afara iesiri/ nu apare în listă și nu se citește: altfel s-ar putea scoate date din alt folder."""
    link = outputs / RUN_A
    if not make_directory_link(link, outputs.parent / "in_afara"):
        pytest.skip("sistemul nu permite crearea unei joncțiuni sau legături simbolice de folder")
    store = app_runs.RunsStore(outputs)
    assert store.list_runs() == [], "o joncțiune spre exterior a apărut în lista rulărilor"
    for read in (lambda: store.read_analysis(RUN_A), lambda: store.read_download(RUN_A, "raport.html")):
        with pytest.raises(app_runs.RunNotFound):
            read()


def test_a_file_symlink_inside_a_run_folder_pointing_outside_is_not_followed(outputs):
    """Un analiza.json sau raport.html care e o legătură simbolică spre un fișier din afară nu se citește (nici la listă, nici la cerere)."""
    folder = make_run(outputs, RUN_A, orders=None, report=False)
    try:
        os.symlink(outputs.parent / "in_afara" / "analiza.json", folder / "analiza.json")
        os.symlink(outputs.parent / "in_afara" / "raport.html", folder / "raport.html")
    except (OSError, NotImplementedError):
        pytest.skip("sistemul nu permite crearea de legături simbolice de fișier (pe Windows cere modul dezvoltator sau drepturi de administrator)")
    store = app_runs.RunsStore(outputs)
    (run,) = store.list_runs()
    assert run["orders"] is None and run["has_report"] is False, "o legătură simbolică de fișier a fost urmărită la listare"
    with pytest.raises(app_runs.RunNotFound):
        store.read_analysis(RUN_A)
    with pytest.raises(app_runs.RunNotFound):
        store.read_download(RUN_A, "raport.html")


def test_a_junction_to_a_subfolder_inside_a_run_folder_is_not_followed(outputs):
    """Un folder-legătură PUT în interiorul unei rulări (ex. raport.html ca joncțiune) nu e citit ca fișier: nu e fișier obișnuit."""
    folder = make_run(outputs, RUN_A, report=False)
    if not make_directory_link(folder / "raport.html", outputs.parent / "in_afara"):
        pytest.skip("sistemul nu permite crearea unei joncțiuni sau legături simbolice de folder")
    with pytest.raises(app_runs.RunNotFound):
        app_runs.RunsStore(outputs).read_download(RUN_A, "raport.html")


def test_the_secret_outside_the_folder_never_shows_up_in_any_result(outputs):
    """Verificare de ansamblu: după toate încercările de mai sus, marcajul secret din folderul vecin nu apare în nicio listă."""
    make_run(outputs, RUN_A)
    store = app_runs.RunsStore(outputs)
    assert SECRET_MARKER not in json.dumps(store.list_runs()) and SECRET_MARKER not in store.read_analysis(RUN_A).decode("utf-8")


def test_link_detection_recognizes_symlink_and_reparse_point_attributes(tmp_path, monkeypatch):
    """_is_link_like spune „legătură” pentru S_ISLNK și pentru atributul Windows REPARSE_POINT (joncțiuni), chiar dacă sistemul nu permite crearea lor aici."""
    import stat
    from types import SimpleNamespace

    regular = tmp_path / "fisier.txt"
    regular.write_text("x", encoding="utf-8")
    assert app_runs._is_link_like(regular) is False and app_runs._is_link_like(tmp_path / "lipseste") is False
    real_lstat = os.lstat

    def fake(mode, attributes):
        return lambda path: SimpleNamespace(st_mode=mode, st_file_attributes=attributes)

    monkeypatch.setattr(app_runs.os, "lstat", fake(stat.S_IFLNK, 0))
    assert app_runs._is_link_like(regular) is True, "o legătură simbolică (S_IFLNK) nu a fost recunoscută"
    monkeypatch.setattr(app_runs.os, "lstat", fake(stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT))
    assert app_runs._is_link_like(regular) is True, "o joncțiune Windows (REPARSE_POINT) nu a fost recunoscută"
    monkeypatch.setattr(app_runs.os, "lstat", real_lstat)
    assert app_runs._is_link_like(regular) is False
