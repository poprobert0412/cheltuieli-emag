"""Teste pentru deschiderea raportului (emag_spend/report_opener.py) și pentru --deschide din ruleaza.py.

`webbrowser.open` se înlocuiește cu un înregistrator: testele nu deschid nimic real.
Numele folderelor sunt inventate; unul are spațiu și diacritice, ca adresa file:// să fie verificată pe un caz greu.
"""

import ast
from pathlib import Path

import pytest

import ruleaza
from emag_spend import report_opener, settings


@pytest.fixture
def opened(monkeypatch):
    """Lista adreselor pe care codul a cerut browserului să le deschidă (nimic nu se deschide cu adevărat)."""
    urls: list[str] = []
    monkeypatch.setattr(report_opener.webbrowser, "open", lambda url, *args, **kwargs: urls.append(url) or True)
    return urls


def _report(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / "raport.html"
    report.write_text("<html></html>", encoding="utf-8")
    return report


def test_opens_the_report_through_a_file_uri(tmp_path, opened):
    report = _report(tmp_path / "rularea mea ăîșț")
    assert report_opener.open_report(report) is True
    assert opened == [report.resolve().as_uri()]
    assert opened[0].startswith("file:///") and "%20" in opened[0] and " " not in opened[0]


def test_a_relative_path_is_resolved_to_an_absolute_uri(tmp_path, opened, monkeypatch):
    report = _report(tmp_path / "rulare")
    monkeypatch.chdir(tmp_path)
    assert report_opener.open_report(Path("rulare") / "raport.html") is True
    assert opened == [report.resolve().as_uri()]


def test_a_missing_report_is_not_opened_and_returns_false(tmp_path, opened):
    assert report_opener.open_report(tmp_path / "lipseste" / "raport.html") is False
    assert report_opener.open_report(tmp_path) is False  # un folder nu e un raport
    assert opened == []


def test_returns_false_when_the_system_has_no_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(report_opener.webbrowser, "open", lambda url, *args, **kwargs: False)
    assert report_opener.open_report(_report(tmp_path / "rulare")) is False


def test_nothing_in_the_command_line_or_the_opener_uses_the_windows_only_startfile():
    for module in (ruleaza, report_opener):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        used |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "startfile" not in used, module.__name__


# ---------- --deschide din linia de comandă ----------

@pytest.fixture
def finished_run(tmp_path, monkeypatch):
    """`run` înlocuit cu o funcție care întoarce un folder de rulare cu raport.html; jurnalul merge în folderul temporar."""
    run_dir = tmp_path / "iesiri" / "2026-01-01_10-00-00"
    _report(run_dir)
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(ruleaza, "run", lambda options, log_path=None: run_dir)
    return run_dir


def test_deschide_opens_the_report_of_the_finished_run(finished_run, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ruleaza, "open_report", lambda path: calls.append(path) or True)
    assert ruleaza.main(["--deschide"]) == 0
    assert calls == [finished_run / "raport.html"]
    assert "Nu am putut deschide" not in capsys.readouterr().out


def test_without_deschide_nothing_is_opened(finished_run, monkeypatch):
    monkeypatch.setattr(ruleaza, "open_report", lambda path: pytest.fail("raportul nu trebuia deschis fără --deschide"))
    assert ruleaza.main([]) == 0


def test_deschide_tells_the_user_the_path_when_the_browser_cannot_be_opened(finished_run, monkeypatch, capsys):
    monkeypatch.setattr(ruleaza, "open_report", lambda path: False)
    assert ruleaza.main(["--deschide"]) == 0  # raportul există; doar deschiderea automată n-a mers
    output = capsys.readouterr().out
    assert "Nu am putut deschide raportul automat" in output and str(finished_run / "raport.html") in output
