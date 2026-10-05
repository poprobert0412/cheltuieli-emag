"""Teste pentru `write_report`: raportul generat e un singur fișier autonom, cu date protejate."""

import json
import re

import pytest

from emag_spend import settings
from emag_spend.report_html import write_report
from tests import dashboard_samples

SCRIPT_JSON = re.compile(r'<script id="date-analiza" type="application/json">(.*?)</script>', re.S)
CSS_PLACEHOLDER = "/*__DASHBOARD_CSS__*/"
JS_PLACEHOLDER = "/*__DASHBOARD_JS__*/"
DATA_PLACEHOLDER = "/*__DATE_ANALIZA__*/null"


def _report(tmp_path, summary=None, **kwargs):
    """Scrie raportul cu șablonul real și întoarce (textul HTML, calea fișierului)."""
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, summary if summary is not None else dashboard_samples.small_summary(), **kwargs)
    return out.read_text(encoding="utf-8"), out


def _template_with(tmp_path, css=True, js=True, data=True, extra=""):
    """Un șablon minimal cu doar placeholder-ele cerute (celelalte lipsesc, `extra` se adaugă la final)."""
    parts = ["<html><body>"]
    parts.append(f"<style>{CSS_PLACEHOLDER}</style>" if css else "")
    parts.append(f'<script id="date-analiza" type="application/json">{DATA_PLACEHOLDER}</script>' if data else "")
    parts.append(f"<script>{JS_PLACEHOLDER}</script>" if js else "")
    parts.append(extra + "</body></html>")
    path = tmp_path / "t.html"
    path.write_text("".join(parts), encoding="utf-8")
    return path


def test_report_is_one_self_contained_file_without_external_references(tmp_path):
    html, _ = _report(tmp_path)
    assert settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8") in html
    assert settings.DASHBOARD_CSS_FILE.read_text(encoding="utf-8") in html
    assert "<link" not in html.lower()
    assert not re.search(r"<script[^>]*\ssrc=", html, re.I)
    assert not re.search(r"@import|url\(\s*['\"]?https?:", html, re.I)
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?:', html, re.I)
    for placeholder in (CSS_PLACEHOLDER, JS_PLACEHOLDER, DATA_PLACEHOLDER):
        assert placeholder not in html


def test_embedded_json_roundtrips_and_is_valid_with_hostile_names(tmp_path):
    summary = dashboard_samples.hostile_summary()
    html, _ = _report(tmp_path, summary)
    embedded = SCRIPT_JSON.search(html).group(1)
    assert json.loads(embedded) == summary
    assert "<" not in embedded  # nicio „<” brută în date: nici </script>, nici <!--<script>
    # același număr ca în șablon: datele nu aduc niciun </script> în plus
    assert html.count("</script>") == settings.REPORT_TEMPLATE_FILE.read_text(encoding="utf-8").count("</script>")


def test_data_with_html_comment_and_script_sequences_cannot_derail_the_parser(tmp_path):
    summary = {"nume": "<!--<script>alert(1)</script>", "alt": "</SCRIPT><b>x</b>", "n": 1}
    html, _ = _report(tmp_path, summary)
    embedded = SCRIPT_JSON.search(html).group(1)
    assert json.loads(embedded) == summary
    assert "<!--" not in embedded and "</" not in embedded


def test_placeholder_text_inside_data_does_not_corrupt_the_report(tmp_path):
    summary = {"nume": f"{JS_PLACEHOLDER} și {CSS_PLACEHOLDER} și {DATA_PLACEHOLDER}"}
    html, _ = _report(tmp_path, summary)
    assert json.loads(SCRIPT_JSON.search(html).group(1)) == summary
    assert html.count(settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8")) == 1  # JS-ul a intrat o singură dată


def test_diacritics_are_kept_as_utf8_not_escaped(tmp_path):
    summary = {"nume": "Țigări și șuruburi în păstrăvărie"}
    html, out = _report(tmp_path, summary)
    assert "Țigări și șuruburi în păstrăvărie" in html
    assert "Țigări".encode("utf-8") in out.read_bytes()


def test_file_is_written_with_lf_only(tmp_path):
    _, out = _report(tmp_path)
    assert b"\r\n" not in out.read_bytes()


@pytest.mark.parametrize("missing, expected", [("css", CSS_PLACEHOLDER), ("js", JS_PLACEHOLDER), ("data", DATA_PLACEHOLDER)])
def test_missing_placeholder_raises_a_clear_error(tmp_path, missing, expected):
    template = _template_with(tmp_path, **{missing: False})
    with pytest.raises(ValueError, match="exact o dată") as err:
        write_report(tmp_path / "r.html", template, {})
    assert expected in str(err.value) and "0" in str(err.value)


def test_duplicated_placeholder_raises_a_clear_error(tmp_path):
    template = _template_with(tmp_path, extra=f"<script>{JS_PLACEHOLDER}</script>")
    with pytest.raises(ValueError, match="am găsit 2"):
        write_report(tmp_path / "r.html", template, {})
    assert not (tmp_path / "r.html").exists()  # nu lasă un fișier pe jumătate


@pytest.mark.parametrize("kind, bad", [("css", "</style>"), ("css", "a<!--b"), ("js", "x</SCRIPT>"), ("js", "y<!--z")])
def test_assets_that_would_break_the_inline_tag_are_refused(tmp_path, kind, bad):
    css = tmp_path / "d.css"
    js = tmp_path / "d.js"
    css.write_text("/* ok */", encoding="utf-8")
    js.write_text("/* ok */", encoding="utf-8")
    (css if kind == "css" else js).write_text(f"/* {bad} */", encoding="utf-8")
    with pytest.raises(ValueError, match="nu poate fi lipit inline"):
        write_report(tmp_path / "r.html", settings.REPORT_TEMPLATE_FILE, {}, css_path=css, js_path=js)


def test_missing_design_file_raises_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="lipsește"):
        write_report(tmp_path / "r.html", settings.REPORT_TEMPLATE_FILE, {}, js_path=tmp_path / "nu_exista.js")


def test_explicit_design_paths_are_used(tmp_path):
    css = tmp_path / "x.css"
    js = tmp_path / "x.js"
    css.write_text("/* css-de-test */", encoding="utf-8")
    js.write_text("/* js-de-test */", encoding="utf-8")
    html, _ = _report(tmp_path, {}, css_path=css, js_path=js)
    assert "css-de-test" in html and "js-de-test" in html
    assert settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8") not in html


def test_defaults_come_from_settings_at_call_time(tmp_path, monkeypatch):
    css = tmp_path / "alt.css"
    js = tmp_path / "alt.js"
    css.write_text("/* css-din-settings */", encoding="utf-8")
    js.write_text("/* js-din-settings */", encoding="utf-8")
    monkeypatch.setattr(settings, "DASHBOARD_CSS_FILE", css)
    monkeypatch.setattr(settings, "DASHBOARD_JS_FILE", js)
    html, _ = _report(tmp_path, {})
    assert "css-din-settings" in html and "js-din-settings" in html


def test_settings_point_to_existing_design_files():
    assert settings.DASHBOARD_CSS_FILE.is_file() and settings.DASHBOARD_JS_FILE.is_file()
    assert settings.DASHBOARD_CSS_FILE.parent == settings.DASHBOARD_JS_FILE.parent
