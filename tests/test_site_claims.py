"""Afirmațiile din pagina interfata/index.html despre ce scrie programul, verificate pe o rulare --demo reală.

Primește: o rulare cu comenzi INVENTATE (fără browser, fără login), făcută într-un folder temporar; textul paginii.
Verifică: fiecare fișier scris în folderul rulării e descris în pagină (și apare în arborele de fișiere), fiecare fișier din
arbore chiar există, iar run_info.json nu conține căi absolute (pagina spune că nu are numele contului Windows).
NU scrie nimic în proiect: folderul rulării și demo-data.js merg într-un folder temporar.
"""

import html
import json
import re
from pathlib import Path

import pytest

from emag_spend import settings
from emag_spend.run_pipeline import RunOptions, run

INDEX = (settings.PROJECT_ROOT / "interfata" / "index.html").read_text(encoding="utf-8")
PAGE_TEXT = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
# Arborele din secțiunea „Ce găsești în folderul rezultatelor”: iesiri/<rulare>/ cu fișierele, apoi logs/ (jurnalul nu stă în rulare).
TREE = html.unescape(re.sub(r"<[^>]+>", "", re.search(r'<pre class="tree".*?</pre>', INDEX, re.S).group(0)))
TREE_FILES = set(re.findall(r"[├└]─ ([A-Za-z0-9_.\-]+\.[a-z]+)", TREE))


@pytest.fixture(scope="module")
def demo_run_dir(tmp_path_factory):
    """Folderul unei rulări --demo făcute în temporar (demo-data.js al interfeței nu se atinge)."""
    parent = tmp_path_factory.mktemp("rulare_demo")
    return run(RunOptions(output_dir=parent, demo=True, demo_data_js=parent / "demo-data.js"))


def test_the_page_documents_every_file_a_run_writes(demo_run_dir: Path):
    """Un fișier nou scris de program în folderul rulării trebuie descris în pagină și pus în arbore."""
    written = sorted(path.name for path in Path(demo_run_dir).iterdir() if path.is_file())
    assert {"raport.html", "analiza.json", "comenzi.json", "retururi.json", "run_info.json"} <= set(written), written
    undocumented = [name for name in written if name not in PAGE_TEXT]
    not_in_tree = [name for name in written if name not in TREE_FILES]
    assert not undocumented and not not_in_tree, f"nedocumentate: {undocumented}; lipsă din arbore: {not_in_tree}"


def test_every_file_in_the_tree_exists_in_the_run_folder(demo_run_dir: Path):
    """Fiecare fișier din arborele paginii chiar se scrie într-o rulare (altfel pagina promite un fișier care nu există)."""
    written = {path.name for path in Path(demo_run_dir).iterdir() if path.is_file()}
    assert TREE_FILES, "arborele din pagină nu s-a putut citi"
    assert TREE_FILES <= written, sorted(TREE_FILES - written)


def test_run_info_has_no_absolute_paths_as_the_page_says(demo_run_dir: Path):
    """Pagina spune că run_info.json are căi relative la proiect, fără numele contului Windows."""
    info = json.loads((Path(demo_run_dir) / "run_info.json").read_text(encoding="utf-8"))
    paths = [value for value in info.values() if isinstance(value, str) and ("/" in value or "\\" in value)]
    assert paths, "run_info.json n-are nicio cale: testul n-ar verifica nimic"
    assert not [value for value in paths if Path(value).is_absolute() or ":" in value], paths
    assert "numele contului tău Windows" in PAGE_TEXT


def test_run_info_keeps_the_program_version_the_page_names(demo_run_dir: Path):
    """Pagina spune că run_info.json are versiunea programului (program_version): cheia există și e versiunea de acum."""
    from emag_spend.version import VERSION
    info = json.loads((Path(demo_run_dir) / "run_info.json").read_text(encoding="utf-8"))
    assert info.get("program_version") == VERSION, info.get("program_version")
    assert "program_version" in PAGE_TEXT and "versiunea programului" in PAGE_TEXT
