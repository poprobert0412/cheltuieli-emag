"""Teste pentru fișierele pe care le poate edita utilizatorul: categorii.json și comenzi.json / retururi.json (--din-cache).

Un fișier rupt, salvat cu BOM, editat de mână sau scris de altă versiune a programului nu dă
traceback: mesajul spune CE fișier e greșit și unde. Toate datele sunt inventate.
"""

import json

import pytest

import ruleaza
from emag_spend import run_store, settings
from emag_spend.classifier import Classifier
from emag_spend.json_file import read_json
from tests import scenario


def _cache_with_valid_data(folder):
    run_store.save_orders(folder, scenario.orders())
    run_store.save_returns(folder, scenario.returns())
    return folder


def _write(folder, name, content: str | bytes):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


# ---------- json_file.read_json ----------

def test_read_json_names_the_file_line_and_column_of_a_syntax_error(tmp_path):
    path = _write(tmp_path, "rupt.json", '{\n  "a": 1\n  "b": 2\n}')
    with pytest.raises(ValueError) as error:
        read_json(path)
    message = str(error.value)
    assert "rupt.json" in message and "linia 3" in message and "coloana" in message


def test_read_json_accepts_a_file_saved_with_a_bom(tmp_path):
    path = _write(tmp_path, "bom.json", b"\xef\xbb\xbf" + '{"nume": "Ștefan"}'.encode("utf-8"))
    assert read_json(path) == {"nume": "Ștefan"}


def test_read_json_says_when_the_file_is_not_utf8(tmp_path):
    path = _write(tmp_path, "latin.json", b'{"a": "\xe9\xff"}')
    with pytest.raises(ValueError, match=r"latin\.json.*UTF-8"):
        read_json(path)


# ---------- categorii.json ----------

def test_classifier_error_names_the_rules_file_for_a_missing_comma(tmp_path):
    path = _write(tmp_path, "categorii.json", '{"categories": [\n {"name": "A" "patterns": ["x"]}\n]}')
    with pytest.raises(ValueError) as error:
        Classifier.from_file(path)
    assert "categorii.json" in str(error.value) and "linia 2" in str(error.value)


def test_classifier_loads_rules_saved_with_a_bom(tmp_path):
    rules = {"categories": [{"name": "Cafea", "patterns": ["cafea"]}]}
    path = _write(tmp_path, "categorii.json", b"\xef\xbb\xbf" + json.dumps(rules).encode("utf-8"))
    assert Classifier.from_file(path).classify("Cafea boabe 1kg")[0] == "Cafea"


def test_classifier_refuses_a_rules_file_that_is_not_an_object(tmp_path):
    path = _write(tmp_path, "categorii.json", "[1, 2]")
    with pytest.raises(ValueError, match=r"categorii\.json.*obiect"):
        Classifier.from_file(path)


# ---------- comenzi.json / retururi.json ----------

def test_load_run_missing_key_names_file_order_and_key(tmp_path):
    cache = _cache_with_valid_data(tmp_path / "cache")
    _write(cache, "comenzi.json", json.dumps([{"order_id": "1"}]))
    with pytest.raises(ValueError) as error:
        run_store.load_run(cache)
    message = str(error.value)
    assert "comenzi.json" in message and "comanda nr. 1" in message and "blocks" in message


def test_load_run_unknown_extra_key_from_a_future_version_is_reported_with_its_name(tmp_path):
    cache = _cache_with_valid_data(tmp_path / "cache")
    orders = json.loads((cache / "comenzi.json").read_text(encoding="utf-8"))
    orders[1]["camp_nou"] = "x"
    _write(cache, "comenzi.json", json.dumps(orders))
    with pytest.raises(ValueError) as error:
        run_store.load_run(cache)
    assert "comanda nr. 2" in str(error.value) and "camp_nou" in str(error.value)


@pytest.mark.parametrize("content", ['{"a": 1}', '"text"', "5", "null"])
def test_load_run_refuses_a_file_that_is_not_a_list(tmp_path, content):
    cache = _cache_with_valid_data(tmp_path / "cache")
    _write(cache, "retururi.json", content)
    with pytest.raises(ValueError, match=r"retururi\.json.*listă"):
        run_store.load_run(cache)


@pytest.mark.parametrize("entry", ['"o comandă care e text"', "[1, 2]", "7", "null"])
def test_load_run_wrong_entry_type_is_a_clear_error_not_a_traceback(tmp_path, entry):
    cache = _cache_with_valid_data(tmp_path / "cache")
    _write(cache, "comenzi.json", f"[{entry}]")
    with pytest.raises(ValueError, match=r"comenzi\.json, comanda nr\. 1"):
        run_store.load_run(cache)


def test_load_run_blocks_that_are_not_a_list_of_objects(tmp_path):
    cache = _cache_with_valid_data(tmp_path / "cache")
    orders = json.loads((cache / "comenzi.json").read_text(encoding="utf-8"))
    orders[0]["blocks"] = "nu-lista"
    _write(cache, "comenzi.json", json.dumps(orders))
    with pytest.raises(ValueError, match="comanda nr. 1"):
        run_store.load_run(cache)


def test_load_run_reads_files_saved_with_a_bom_and_round_trips(tmp_path):
    cache = _cache_with_valid_data(tmp_path / "cache")
    for name in ("comenzi.json", "retururi.json"):
        path = cache / name
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    orders, returns = run_store.load_run(cache)
    assert orders == scenario.orders() and returns == scenario.returns()


def test_load_run_broken_json_names_the_file(tmp_path):
    cache = _cache_with_valid_data(tmp_path / "cache")
    _write(cache, "comenzi.json", '[{"a": 1,]')
    with pytest.raises(ValueError, match=r"comenzi\.json: JSON invalid la linia 1"):
        run_store.load_run(cache)


def test_cli_din_cache_with_a_bad_file_prints_an_error_with_the_file_and_no_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    cache = _cache_with_valid_data(tmp_path / "cache")
    _write(cache, "comenzi.json", json.dumps([{"order_id": "1"}]))
    code = ruleaza.main(["--din-cache", str(cache), "--iesire", str(tmp_path / "out")])
    output = capsys.readouterr().out
    assert code == 1 and "EROARE" in output and "comenzi.json" in output and "Traceback" not in output
