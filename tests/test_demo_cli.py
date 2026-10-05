"""Teste pentru `python ruleaza.py --demo`: fără browser, fără login, cu toate fișierele rulării."""

import json
import re
import shutil

import pytest

import ruleaza
from emag_spend import browser_session, run_pipeline, settings, site_demo_writer
from emag_spend.demo_data import demo_orders_and_returns

RUN_FILES = ("raport.html", "produse.csv", "rezumat.txt", "analiza.json", "comenzi.json", "retururi.json", "run_info.json")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Jurnalul și demo-data.js merg în folderul temporar (testul nu atinge proiectul real);
    orice încercare de a deschide browserul sau de a cere login pică testul. Regulile de categorii
    sunt o copie fără fișierul personal, ca rezultatul să fie același pe orice calculator."""
    def forbidden(*args, **kwargs):
        raise AssertionError("modul --demo nu are voie să deschidă browserul sau să ceară login")

    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "config").mkdir()
    shutil.copy(settings.CATEGORY_RULES_FILE, tmp_path / "config" / "categorii.json")
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", tmp_path / "config" / "categorii.json")
    monkeypatch.setattr(site_demo_writer, "DEMO_DATA_JS_FILE", tmp_path / "site" / "demo-data.js")
    monkeypatch.setattr(run_pipeline, "collect_all", forbidden)
    monkeypatch.setattr(ruleaza, "login_only", forbidden)
    monkeypatch.setattr(browser_session, "logged_in_browser", forbidden)
    monkeypatch.setattr(ruleaza, "open_report", forbidden)  # raportul se deschide doar la cerere (--deschide)
    return tmp_path


def test_demo_writes_every_run_file_into_a_demo_folder(isolated):
    out = isolated / "out"
    assert ruleaza.main(["--demo", "--iesire", str(out)]) == 0
    (run_dir,) = out.iterdir()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_demo", run_dir.name)
    for name in RUN_FILES:
        assert (run_dir / name).stat().st_size > 0, name
    orders, returns = demo_orders_and_returns()
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    assert info["demo"] is True and info["comenzi"] == len(orders) and info["retururi"] == len(returns)
    analysis = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert analysis["meta"]["orders"] == len(orders)
    assert "Televizoare" in analysis["highlights"] and analysis["uncategorized_count"] >= 1
    assert "PĂSTRAT" in (run_dir / "rezumat.txt").read_text(encoding="utf-8")
    assert "<html" in (run_dir / "raport.html").read_text(encoding="utf-8").lower()


def test_demo_rewrites_the_site_data_file_with_the_default_threshold(isolated):
    site_file = site_demo_writer.DEMO_DATA_JS_FILE
    assert not site_file.exists()
    assert ruleaza.main(["--demo", "--prag", "1000", "--iesire", str(isolated / "out")]) == 0
    assert site_file.read_bytes().decode("utf-8") == site_demo_writer.expected_demo_data_js()
    (run_dir,) = (isolated / "out").iterdir()
    analysis = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert analysis["meta"]["threshold_bani"] == 100000  # rularea respectă --prag
    assert json.loads(site_file.read_text(encoding="utf-8")[len("window.EMAG_DEMO_DATA = "):-1])["meta"]["threshold_bani"] == 50000


def test_demo_run_is_a_cache_for_a_later_rebuild_without_browser(isolated):
    assert ruleaza.main(["--demo", "--iesire", str(isolated / "out")]) == 0
    (run_dir,) = (isolated / "out").iterdir()
    assert ruleaza.main(["--din-cache", str(run_dir), "--iesire", str(isolated / "out2")]) == 0
    (rebuilt,) = (isolated / "out2").iterdir()
    first = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    second = json.loads((rebuilt / "analiza.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in first.items() if k != "meta"} == {k: v for k, v in second.items() if k != "meta"}


@pytest.mark.parametrize("extra", [["--din-cache", "x"], ["--doar-login"], ["--limita-comenzi", "5"]])
def test_demo_refuses_options_that_make_no_sense_with_invented_data(isolated, extra, capsys):
    with pytest.raises(SystemExit) as stop:
        ruleaza.main(["--demo", *extra])
    assert stop.value.code == 2
    assert "--demo nu se combină" in capsys.readouterr().err
    assert not (isolated / "site" / "demo-data.js").exists()
