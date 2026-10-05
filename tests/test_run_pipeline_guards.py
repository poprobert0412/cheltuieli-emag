"""Teste pentru gardurile din run_pipeline: reguli verificate înainte de colectare și run_info.json fără căi personale.

Valorile sunt inventate; regulile de categorii folosite aici stau în foldere temporare.
"""

import json
from pathlib import Path

import pytest

from emag_spend import run_pipeline, run_store, settings
from emag_spend.run_pipeline import RunOptions, run
from tests import scenario


def _rules_file(folder: Path, names: list[str]) -> Path:
    rules = {"default_category": "Necategorizat", "categories": [{"name": n, "patterns": ["."]} for n in names]}
    path = folder / "categorii.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    return path


def test_a_highlighted_category_missing_from_the_rules_stops_the_run_before_anything_is_read_or_written(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("colectarea nu are voie să pornească dacă regulile sunt greșite")

    monkeypatch.setattr(run_pipeline, "collect_all", forbidden)
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", _rules_file(tmp_path, ["Televizoare", "Bauturi"]))  # „Alcool” redenumită
    out = tmp_path / "out"
    with pytest.raises(ValueError) as error:
        run(RunOptions(output_dir=out))
    message = str(error.value)
    assert "«Alcool»" in message and "categorii.json" in message and "HIGHLIGHT_CATEGORIES" in message
    assert "Televizoare" not in message  # doar categoria lipsă e numită
    assert not out.exists()  # nici măcar folderul rulării


def test_every_missing_highlighted_category_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", _rules_file(tmp_path, ["Altceva"]))
    with pytest.raises(ValueError) as error:
        run(RunOptions(output_dir=tmp_path / "out"))
    assert "«Alcool»" in str(error.value) and "«Televizoare»" in str(error.value)


def test_a_run_with_all_highlighted_categories_present_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", _rules_file(tmp_path, ["Alcool", "Televizoare", "Diverse"]))
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    run_dir = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out"))
    assert (run_dir / "raport.html").exists()


def test_run_info_has_no_absolute_paths_or_the_windows_account_name(tmp_path):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    log_path = settings.PROJECT_ROOT / "logs" / "2026-10-04_12-00-00.log"
    run_dir = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out"), log_path=log_path)
    text = (run_dir / "run_info.json").read_text(encoding="utf-8")
    info = json.loads(text)
    assert Path(info["regulile_de_categorii"]) == Path("config") / "categorii.json"
    assert Path(info["jurnal"]) == Path("logs") / "2026-10-04_12-00-00.log"
    assert info["din_cache"] == "cache"  # în afara proiectului: doar numele folderului
    assert str(settings.PROJECT_ROOT) not in text and str(tmp_path) not in text and Path.home().name not in text


def test_project_relative_keeps_paths_inside_the_project_relative(tmp_path):
    inside = settings.PROJECT_ROOT / "iesiri" / "2026-10-04_12-00-00"
    assert Path(run_pipeline._project_relative(inside)) == Path("iesiri") / "2026-10-04_12-00-00"
    assert run_pipeline._project_relative(tmp_path / "alt_folder") == "alt_folder"


@pytest.mark.parametrize("target, content, expected", [
    ("WARNING_TEXTS_FILE", '{"grupe": {}}', "'etichete_status'"),  # config/avertismente.json: lipsesc cheile
    ("WARNING_TEXTS_FILE", '{"grupe": ', "JSON invalid"),
    ("COLOR_WORDS_FILE", '{"culori": "alb"}', "listă de texte"),  # config/culori.json: nu e listă
    ("COLOR_WORDS_FILE", '[', "JSON invalid"),
])
def test_a_wrong_warning_texts_or_colors_file_stops_the_run_before_anything_is_read_or_written(tmp_path, monkeypatch, target, content, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError("colectarea nu are voie să pornească dacă fișierele de configurare sunt greșite")

    monkeypatch.setattr(run_pipeline, "collect_all", forbidden)
    broken = tmp_path / "broken.json"
    broken.write_text(content, encoding="utf-8")
    monkeypatch.setattr(run_pipeline, target, broken)
    out = tmp_path / "out"
    with pytest.raises(ValueError) as error:
        run(RunOptions(output_dir=out))
    assert "broken.json" in str(error.value) and expected in str(error.value)
    assert not out.exists()  # nici măcar folderul rulării


def test_a_run_writes_the_new_files_and_names_the_config_files_without_absolute_paths(tmp_path):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    run_dir = run(RunOptions(from_cache=cache, output_dir=tmp_path / "out"))
    assert (run_dir / "istoric_preturi.csv").exists()
    text = (run_dir / "run_info.json").read_text(encoding="utf-8")
    info = json.loads(text)
    assert Path(info["textele_avertismentelor"]) == Path("config") / "avertismente.json"
    assert Path(info["culorile_produselor"]) == Path("config") / "culori.json"
    assert str(settings.PROJECT_ROOT) not in text and str(tmp_path) not in text
