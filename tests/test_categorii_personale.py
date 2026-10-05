"""Teste pentru regulile personale de categorii (config/categorii.personal.json) și pentru fișierul-exemplu.

Regulile publice și cele personale din teste sunt INVENTATE și stau în foldere temporare; nu se citește
fișierul personal real al nimănui. Testele care citesc config/categorii.json cer `include_personal=False`,
ca rezultatul să fie același pe orice calculator, cu sau fără fișier personal.
"""

import json
import shutil
from pathlib import Path

import pytest

from emag_spend import settings
from emag_spend.classifier import Classifier

PERSONAL_NAME = settings.PERSONAL_CATEGORY_RULES_FILE_NAME
EXAMPLE_FILE = settings.PROJECT_ROOT / "config" / "categorii.personal.exemplu.json"

_PUBLIC = {
    "default_category": "Necategorizat",
    "categories": [
        {"name": "Cărți", "patterns": [r"\bcarte\b"]},
        {"name": "Auto", "patterns": [r"\bmasina\b", r"\bcovorase\b"], "exclude": [r"\bjucarie\b"]},
    ],
}
_PERSONAL = {
    "_descriere": "reguli inventate pentru teste",
    "categories": [
        {"name": "Cărți", "patterns": [r"\bpovestea lui zeta\b"]},  # același nume ca la regulile publice
        {"name": "Hobby", "patterns": [r"\bcovorase zeta\b"]},  # câștigă în fața lui «covorase» din Auto
    ],
}


def _write(folder: Path, name: str, content) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def rules_dir(tmp_path):
    """Folder cu categorii.json (public) și categorii.personal.json (personal), ambele inventate."""
    _write(tmp_path, "categorii.json", _PUBLIC)
    _write(tmp_path, PERSONAL_NAME, _PERSONAL)
    return tmp_path


# ---------- ordinea și combinarea ----------

def test_personal_rules_are_evaluated_before_the_public_ones(rules_dir):
    classifier = Classifier.from_file(rules_dir / "categorii.json")
    assert classifier.classify("Covorase Zeta 4 buc") == ("Hobby", r"\bcovorase zeta\b")
    assert classifier.classify("Covorase universale")[0] == "Auto"  # fără potrivire personală, rămân regulile publice


def test_without_the_personal_file_only_public_rules_apply(rules_dir):
    only_public = Classifier.from_file(rules_dir / "categorii.json", include_personal=False)
    assert only_public.classify("Covorase Zeta 4 buc")[0] == "Auto"
    assert only_public.personal_source is None


def test_a_missing_personal_file_is_not_an_error(tmp_path):
    _write(tmp_path, "categorii.json", _PUBLIC)
    classifier = Classifier.from_file(tmp_path / "categorii.json")
    assert classifier.personal_source is None and classifier.classify("O carte")[0] == "Cărți"


def test_personal_file_is_looked_up_next_to_the_given_rules_file_by_name(tmp_path):
    _write(tmp_path / "unu", "categorii.json", _PUBLIC)
    _write(tmp_path / "doi", PERSONAL_NAME, _PERSONAL)  # alt folder: nu are voie să fie citit
    assert Classifier.from_file(tmp_path / "unu" / "categorii.json").personal_source is None


def test_a_personal_category_may_reuse_a_public_name_and_names_are_listed_once(rules_dir):
    classifier = Classifier.from_file(rules_dir / "categorii.json")
    assert classifier.classify("Povestea lui Zeta")[0] == "Cărți"  # regula personală, în categoria publică
    assert classifier.classify("O carte oarecare")[0] == "Cărți"  # regula publică rămâne
    assert sorted(classifier.category_names) == ["Auto", "Cărți", "Hobby"]
    assert classifier.personal_source == PERSONAL_NAME


def test_personal_rules_use_their_own_exclude_lists_only(rules_dir):
    _write(rules_dir, PERSONAL_NAME, {"categories": [{"name": "Hobby", "patterns": [r"\bzeta\b"], "exclude": [r"\bnu\b"]}]})
    classifier = Classifier.from_file(rules_dir / "categorii.json")
    assert classifier.classify("Produs zeta")[0] == "Hobby"
    assert classifier.classify("Produs zeta nu")[0] == "Necategorizat"


def test_loading_personal_rules_is_logged(rules_dir, caplog):
    with caplog.at_level("INFO", logger="emag_spend.classifier"):
        Classifier.from_file(rules_dir / "categorii.json")
    assert any(PERSONAL_NAME in message and "2 categorii" in message for message in caplog.messages)


# ---------- erori clare, cu numele fișierului și al categoriei ----------

def test_broken_personal_json_names_the_file_the_line_and_what_to_do(rules_dir):
    _write(rules_dir, PERSONAL_NAME, '{"categories": [\n {"name": "Hobby" "patterns": ["x"]}\n]}')
    with pytest.raises(ValueError) as error:
        Classifier.from_file(rules_dir / "categorii.json")
    message = str(error.value)
    assert PERSONAL_NAME in message and "linia 2" in message and "reguli personale" in message


def test_personal_file_that_is_not_an_object_is_refused(rules_dir):
    _write(rules_dir, PERSONAL_NAME, "[1, 2]")
    with pytest.raises(ValueError, match=rf"{PERSONAL_NAME}.*obiect"):
        Classifier.from_file(rules_dir / "categorii.json")


def test_bad_regex_in_personal_rules_names_the_file_and_the_category(rules_dir):
    _write(rules_dir, PERSONAL_NAME, {"categories": [{"name": "Hobby", "patterns": ["(deschis"]}]})
    with pytest.raises(ValueError) as error:
        Classifier.from_file(rules_dir / "categorii.json")
    message = str(error.value)
    assert PERSONAL_NAME in message and "'Hobby'" in message and "expresie regulată greșită în categoria" in message


@pytest.mark.parametrize("categories, fragment", [
    ([{"name": "", "patterns": ["a"]}], "nu are nume"),
    ([{"name": "A", "patterns": ["a"]}, {"name": "A", "patterns": ["b"]}], "duplicată"),
    ([{"name": "A", "patterns": []}], "niciun model"),
    ([{"name": "A", "patterns": "nu e listă"}], "listă de texte"),
    ([{"name": "A", "patterns": [5]}], "listă de texte"),
    ([{"name": "A", "patterns": ["a"], "exclude": "x"}], "«exclude»"),
    (["nu e obiect"], "fiecare categorie trebuie să fie un obiect"),
    ("nu e listă", "«categories» trebuie să fie o listă"),
])
def test_structure_mistakes_in_personal_rules_name_the_file(rules_dir, categories, fragment):
    _write(rules_dir, PERSONAL_NAME, {"categories": categories})
    with pytest.raises(ValueError) as error:
        Classifier.from_file(rules_dir / "categorii.json")
    assert PERSONAL_NAME in str(error.value) and fragment in str(error.value)


@pytest.mark.parametrize("pattern", ["", "   ", ".*", "a*", "(?:)", "x|"])
def test_patterns_that_would_match_every_product_are_refused(rules_dir, pattern):
    """Un model gol sau care potrivește textul gol ar trimite TOATE produsele într-o singură categorie."""
    _write(rules_dir, PERSONAL_NAME, {"categories": [{"name": "Hobby", "patterns": [pattern]}]})
    with pytest.raises(ValueError, match="orice produs"):
        Classifier.from_file(rules_dir / "categorii.json")


def test_an_exclude_that_matches_everything_is_refused_too(rules_dir):
    _write(rules_dir, PERSONAL_NAME, {"categories": [{"name": "Hobby", "patterns": ["x"], "exclude": [".*"]}]})
    with pytest.raises(ValueError, match="orice produs"):
        Classifier.from_file(rules_dir / "categorii.json")


def test_default_category_is_decided_only_by_the_public_file(rules_dir):
    _write(rules_dir, PERSONAL_NAME, {"default_category": "Altceva", "categories": _PERSONAL["categories"]})
    with pytest.raises(ValueError, match="default_category"):
        Classifier.from_file(rules_dir / "categorii.json")
    _write(rules_dir, PERSONAL_NAME, {"default_category": "Necategorizat", "categories": _PERSONAL["categories"]})
    assert Classifier.from_file(rules_dir / "categorii.json").default_category == "Necategorizat"


def test_errors_in_the_public_file_name_that_file(tmp_path):
    _write(tmp_path, "categorii.json", {"categories": [{"name": "A", "patterns": ["("]}]})
    with pytest.raises(ValueError, match=r"categorii\.json: expresie regulată greșită în categoria 'A'"):
        Classifier.from_file(tmp_path / "categorii.json")


# ---------- fișierele din proiect ----------

def test_the_public_rules_file_loads_and_has_no_match_everything_pattern():
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    assert classifier.personal_source is None and set(settings.HIGHLIGHT_CATEGORIES) <= set(classifier.category_names)


def test_the_example_file_is_valid_documented_and_has_two_invented_rules(tmp_path):
    example = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    assert isinstance(example["_descriere"], str) and PERSONAL_NAME in example["_descriere"]
    patterns = [pattern for category in example["categories"] for pattern in category["patterns"]]
    assert len(patterns) == 2
    # copiat ca fișier personal lângă regulile publice reale, trebuie să se încarce fără erori și să se aplice
    shutil.copy(settings.CATEGORY_RULES_FILE, tmp_path / "categorii.json")
    shutil.copy(EXAMPLE_FILE, tmp_path / PERSONAL_NAME)
    with_example = Classifier.from_file(tmp_path / "categorii.json")
    without_example = Classifier.from_file(tmp_path / "categorii.json", include_personal=False)
    for category, pattern in ((c["name"], p) for c in example["categories"] for p in c["patterns"]):
        sample = pattern.replace("\\b", "").replace("^", "").replace("$", "")  # textul din regulă, folosit ca nume de produs
        assert with_example.classify(sample.title())[0] == category
        assert without_example.classify(sample.title())[0] != category, "exemplul trebuie să adauge ceva, nu să repete regulile publice"
