"""Teste pentru CSV, raportul HTML, salvarea datelor și fluxul complet fără browser."""

import csv
import json
import re

import pytest

from emag_spend import run_store, settings
from emag_spend.csv_export import write_lines_csv
from emag_spend.report_html import write_report
from emag_spend.run_pipeline import RunOptions, run
from emag_spend.spend_analysis import analyze
from emag_spend.summary_text import build_summary_text
from tests import scenario


def _analysis():
    return analyze(scenario.orders(), scenario.returns(), scenario.classifier(), 50000, "2026-10-04 12:00",
                   highlight_categories=("Televizoare", "Alcool"))


def test_csv_has_header_decimal_comma_and_threshold_flag(tmp_path):
    analysis = _analysis()
    path = tmp_path / "produse.csv"
    write_lines_csv(path, analysis.lines, 50000)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM pentru Excel
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig"), delimiter=";"))
    assert len(rows) == len(analysis.lines)
    by_name = {r["produs"]: r for r in rows}
    assert by_name["Televizor Alfa 55 inch"]["valoare_linie_lei"] == "2000,00"
    assert by_name["Televizor Alfa 55 inch"]["peste_prag"] == "da"
    assert by_name["Laptop Test"]["peste_prag"] == ""
    assert by_name["Monitor Test"]["valoare_linie_lei"] == "500,01"
    assert by_name["Husa telefon X"]["pastrat_lei"] == "30,00" and by_name["Husa telefon X"]["returnat_lei"] == "30,00"
    assert by_name["Husa telefon X"]["retur_id"] == "R1"


def test_report_embeds_json_that_roundtrips_and_cannot_break_out_of_script(tmp_path):
    summary = {"nume": "Produs </script><b>x</b> <!--<script>", "n": 1}
    out = tmp_path / "r.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, summary)
    html = out.read_text(encoding="utf-8")
    template_scripts = settings.REPORT_TEMPLATE_FILE.read_text(encoding="utf-8").count("</script>")
    assert html.count("</script>") == template_scripts  # datele nu aduc niciun </script> în plus
    embedded = re.search(r'<script id="date-analiza" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(embedded) == summary


@pytest.mark.parametrize("placeholder", ["/*__DASHBOARD_CSS__*/", "/*__DASHBOARD_JS__*/", "/*__DATE_ANALIZA__*/null"])
def test_report_requires_every_placeholder_in_template(tmp_path, placeholder):
    template = settings.REPORT_TEMPLATE_FILE.read_text(encoding="utf-8").replace(placeholder, "")
    broken = tmp_path / "t.html"
    broken.write_text(template, encoding="utf-8")
    with pytest.raises(ValueError, match="exact o dată"):
        write_report(tmp_path / "r.html", broken, {})


def test_run_store_roundtrip(tmp_path):
    orders, returns = scenario.orders(), scenario.returns()
    run_store.save_orders(tmp_path, orders)
    run_store.save_returns(tmp_path, returns)
    loaded_orders, loaded_returns = run_store.load_run(tmp_path)
    assert loaded_orders == orders
    assert loaded_returns == returns


def test_load_run_reports_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="comenzi.json"):
        run_store.load_run(tmp_path)


def test_summary_text_contains_the_key_figures():
    text = build_summary_text(_analysis().summary)
    assert "3.130,01 Lei" in text  # păstrat
    assert "4.090,01 Lei" in text  # comandat
    assert "Televizoare" in text and "Alcool" in text
    assert "PESTE 500,00 Lei" in text


def test_full_pipeline_from_cache_writes_every_output(tmp_path, capsys):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    out = tmp_path / "out"
    run_dir = run(RunOptions(threshold_lei=500, from_cache=cache, output_dir=out))
    for name in ("comenzi.json", "retururi.json", "analiza.json", "raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt", "run_info.json"):
        assert (run_dir / name).exists(), name
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert analiza["funnel"]["kept_bani"] == 313001
    html = (run_dir / "raport.html").read_text(encoding="utf-8")
    embedded = re.search(r'type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(embedded)["funnel"]["kept_bani"] == 313001
    assert settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8") in html  # designul e lipit inline: un singur fișier
    assert "<link" not in html and "<script src" not in html
    assert "PĂSTRAT" in capsys.readouterr().out
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    assert info["comenzi"] == 7 and info["prag_lei"] == 500


def test_pipeline_threshold_option_changes_the_big_items(tmp_path):
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    run_dir = run(RunOptions(threshold_lei=1000, from_cache=cache, output_dir=tmp_path / "out"))
    analiza = json.loads((run_dir / "analiza.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in analiza["big"]["items"]] == ["Televizor Alfa 55 inch"]


def test_cli_reports_expected_errors_without_traceback(tmp_path, monkeypatch, capsys):
    import ruleaza
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    code = ruleaza.main(["--din-cache", str(tmp_path / "nu_exista"), "--iesire", str(tmp_path / "out")])
    assert code == 1
    assert "EROARE" in capsys.readouterr().out


def test_cli_main_runs_from_cache(tmp_path, monkeypatch):
    import ruleaza
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    cache = tmp_path / "cache"
    run_store.save_orders(cache, scenario.orders())
    run_store.save_returns(cache, scenario.returns())
    assert ruleaza.main(["--din-cache", str(cache), "--iesire", str(tmp_path / "out")]) == 0
    assert list((tmp_path / "logs").glob("*.log"))
