"""Teste pentru interfata/assets/demo-data.js: format, determinism și prospețime față de Python."""

import json
import shutil
import subprocess

import pytest

from emag_spend import settings, site_demo_writer
from emag_spend.classifier import Classifier
from emag_spend.demo_data import DEMO_GENERATED_AT
from emag_spend.site_demo_writer import (
    build_demo_summary, expected_demo_data_js, render_demo_data_js, write_demo_data_js,
)

PREFIX = "window.EMAG_DEMO_DATA = "


def test_demo_data_js_in_the_site_is_fresh():
    path = site_demo_writer.DEMO_DATA_JS_FILE
    if not path.exists():
        pytest.fail(f"lipsește {path}; generează-l cu: python ruleaza.py --demo")
    if path.read_bytes().decode("utf-8") != expected_demo_data_js():
        pytest.fail(
            f"{path} nu mai corespunde datelor demo din Python (s-au schimbat datele demo, "
            "regulile de categorii sau calculul). Rulează: python ruleaza.py --demo"
        )


def test_demo_summary_is_deterministic_and_independent_of_the_prag_option_and_the_clock():
    first = build_demo_summary()
    assert first == build_demo_summary()
    assert first["meta"]["generated_at"] == DEMO_GENERATED_AT
    assert first["meta"]["threshold_bani"] == round(settings.BIG_PURCHASE_THRESHOLD_LEI * 100)


def test_published_demo_data_never_depends_on_personal_category_rules(tmp_path, monkeypatch):
    # categorii.personal.json e al fiecărui utilizator și nu intră în git: demo-data.js se publică pe site,
    # deci regulile personale ale cuiva nu au voie să-i schimbe nicio categorie sau cifră.
    published = expected_demo_data_js()
    rules_dir = tmp_path / "config"
    rules_dir.mkdir()
    shutil.copy(settings.CATEGORY_RULES_FILE, rules_dir / "categorii.json")
    personal = {"categories": [{"name": "Doar a mea", "patterns": ["."]}]}  # ar prinde ORICE produs, dacă ar fi folosită
    (rules_dir / settings.PERSONAL_CATEGORY_RULES_FILE_NAME).write_text(json.dumps(personal), encoding="utf-8")
    monkeypatch.setattr(settings, "CATEGORY_RULES_FILE", rules_dir / "categorii.json")
    control = Classifier.from_file(settings.CATEGORY_RULES_FILE)  # control: cu fișierul personal, regula ar prinde un produs demo
    assert control.classify("Televizor demo")[0] == "Doar a mea"
    summary = build_demo_summary()
    assert "Doar a mea" not in {row["name"] for row in summary["by_category"]}
    assert expected_demo_data_js() == published
    target = write_demo_data_js(tmp_path / "demo-data.js")
    assert target.read_bytes().decode("utf-8") == published


def test_rendered_file_is_one_line_utf8_with_the_exact_wrapper():
    summary = build_demo_summary()
    text = render_demo_data_js(summary)
    assert text.startswith(PREFIX) and text.endswith(";")
    assert "\n" not in text and "\r" not in text
    assert "ă" in text and "\\u0103" not in text  # diacritice scrise ca atare, nu ca \uXXXX
    parsed = json.loads(text[len(PREFIX):-1])
    assert parsed == summary
    assert list(parsed) == list(summary)  # aceeași ordine a cheilor ca în analiză


def test_rendered_file_cannot_close_a_script_tag_or_break_a_js_string():
    text = render_demo_data_js({"nume": "Produs </script><b>x</b>  "})
    assert "</" not in text and " " not in text and " " not in text
    assert json.loads(text[len(PREFIX):-1])["nume"] == "Produs </script><b>x</b>  "


def test_write_creates_folders_and_writes_exact_utf8_bytes_without_bom(tmp_path):
    target = tmp_path / "interfata" / "assets" / "demo-data.js"
    assert write_demo_data_js(target) == target
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and b"\n" not in raw
    assert raw.decode("utf-8") == expected_demo_data_js()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node nu e instalat")
def test_file_runs_as_a_classic_script_and_exposes_the_data(tmp_path):
    target = write_demo_data_js(tmp_path / "demo-data.js")
    script = (
        "const vm=require('vm'),fs=require('fs');const ctx={window:{}};vm.createContext(ctx);"
        "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);"
        "const d=ctx.window.EMAG_DEMO_DATA;console.log(d.funnel.kept_bani+' '+d.by_year.length)"
    )
    out = subprocess.run(["node", "-e", script, str(target)], capture_output=True, text=True, check=True).stdout.split()
    summary = build_demo_summary()
    assert out == [str(summary["funnel"]["kept_bani"]), str(len(summary["by_year"]))]


def test_demo_summary_is_marked_as_demo_so_the_report_does_not_link_invented_orders():
    """`build_demo_summary()` pune `meta.demo = true`: eMAG nu cunoaște comenzile inventate și te trimite la lista de comenzi, deci interfața le lasă text."""
    from emag_spend.site_demo_writer import DEMO_META_KEY, build_demo_summary

    assert build_demo_summary()["meta"][DEMO_META_KEY] is True
    assert '"demo": true' in settings.PROJECT_ROOT.joinpath("interfata", "assets", "demo-data.js").read_text(encoding="utf-8")


def test_analysis_of_a_real_account_has_no_demo_marker():
    """Doar datele inventate poartă `meta.demo`: pe un cont real marcajul ar stinge linkurile spre comenzi."""
    from tests import dashboard_samples as samples

    assert site_demo_writer.DEMO_META_KEY not in samples.small_summary()["meta"]
