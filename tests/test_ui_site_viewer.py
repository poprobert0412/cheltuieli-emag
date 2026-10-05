"""Reparațiile din site (vizualizator, simulator, contrast forțat) verificate în browser real (Edge sau Chrome, prin Playwright), din file://.

Primește: interfata/index.html și datele demonstrative inventate din assets/demo-data.js. Verifică: lipirea unui text peste limita de 25 MB primește un
mesaj clar (nu îngheață pagina), un fișier mare arată „Se desenează…” înaintea raportului (unul mic se desenează pe loc), simulatorul scrie
„Produse peste prag: 1” (nu „1 produse”), iar în contrast forțat (Windows high contrast) starea aleasă a comutatoarelor și liniile din meniu rămân vizibile.
Dacă niciun browser nu pornește, tot fișierul se sare.
"""

import json

import pytest

from tests.dashboard_browser_support import read_demo_file_data
from tests.test_site_browser import SETTLE_MS, SITE_URL, browser, open_site, playwright_instance  # noqa: F401

MAX_BYTES = 25 * 1024 * 1024  # limita din site-viewer.js (testul de paritate din test_site_static.py o ține la zi)
DEFER_DRAW_BYTES = 1024 * 1024  # peste atât, mesajul „Se desenează…” apare înaintea desenării
FILLER_ITEMS = 30000  # produse necategorizate puse în plus ca fișierul să treacă de DEFER_DRAW_BYTES (raportul arată doar primele 40)
RECORD_STATUS = """() => { window.__status = []; const el = document.getElementById('viewer-status');
  new MutationObserver(() => window.__status.push(el.textContent)).observe(el, { childList: true, subtree: true, characterData: true }); }"""
SYSTEM_COLOR = """(keyword) => { const probe = document.createElement('i'); probe.style.background = keyword; document.body.appendChild(probe);
  const color = getComputedStyle(probe).backgroundColor; probe.remove(); return color; }"""


def upload(page, name, content):
    """Alege `content` (text) ca fișier cu numele `name` în câmpul de încărcare."""
    page.set_input_files("#file-input", files=[{"name": name, "mimeType": "application/json", "buffer": content.encode("utf-8")}])


def big_valid_report() -> str:
    """Un analiza.json valid de peste DEFER_DRAW_BYTES: datele demo plus multe produse necategorizate (raportul le taie la primele 40)."""
    demo = read_demo_file_data()
    if demo is None:
        pytest.skip("interfata/assets/demo-data.js nu există")
    demo["uncategorized"] = [{"name": f"Produs necategorizat inventat numărul {i} cu un nume destul de lung", "units": 1, "bani": 1000 + i} for i in range(FILLER_ITEMS)]
    demo["uncategorized_count"] = FILLER_ITEMS
    text = json.dumps(demo, ensure_ascii=False)
    assert len(text.encode("utf-8")) > DEFER_DRAW_BYTES
    return text


# ---------- lipire peste limită ----------

def test_pasting_more_than_the_file_limit_gets_a_clear_message_and_does_not_freeze_the_page(open_site):
    page, probe = open_site()
    page.click("#paste > summary")  # zona de lipire e un <details> închis
    page.evaluate("(n) => { document.getElementById('paste-input').value = 'x'.repeat(n); }", MAX_BYTES + 1)
    page.click("#paste-load")
    status = page.inner_text("#viewer-status")
    assert "Textul lipit are" in status and "peste limita de" in status and "25" in status
    assert page.get_attribute("#viewer-status", "data-kind") == "error"
    assert page.eval_on_selector("#viewer-mount", "e => e.hidden") is True, "nu s-a încercat desenarea"
    assert page.evaluate("document.activeElement !== null")  # pagina răspunde
    assert not any(probe.problems().values()), probe.problems()


def test_pasting_a_small_valid_report_still_works(open_site):
    page, _ = open_site()
    page.click("#paste > summary")
    page.evaluate("(text) => { document.getElementById('paste-input').value = text; }", json.dumps(read_demo_file_data()))
    page.click("#paste-load")
    assert "Gata: am încărcat" in page.inner_text("#viewer-status")
    assert page.locator("#viewer-mount [data-ed-block]").count() >= 12


# ---------- „Se desenează…” ----------

def test_a_big_file_shows_the_drawing_message_before_the_report_and_a_small_one_does_not(open_site):
    page, probe = open_site()
    page.evaluate(RECORD_STATUS)
    upload(page, "analiza.json", big_valid_report())
    page.wait_for_selector("#viewer-mount [data-ed-block]", timeout=60000)
    page.wait_for_function("document.getElementById('viewer-status').textContent.startsWith('Gata')", timeout=60000)
    history = page.evaluate("window.__status")
    drawing = [i for i, text in enumerate(history) if text.startswith("Se desenează")]
    done = [i for i, text in enumerate(history) if text.startswith("Gata")]
    assert drawing and done and drawing[0] < done[0], history
    assert "„analiza.json”" in history[drawing[0]] and history[drawing[0]].endswith("…")
    assert page.get_attribute("#viewer-status", "data-kind") == "ok"
    page.evaluate("window.__status = []")
    upload(page, "mic.json", json.dumps(read_demo_file_data()))
    page.wait_for_function("document.getElementById('viewer-status').textContent.includes('mic.json')", timeout=60000)
    assert not any(text.startswith("Se desenează") for text in page.evaluate("window.__status"))
    assert not any(probe.problems().values()), probe.problems()


def test_the_drawing_message_is_in_the_polite_live_region(open_site):
    page, _ = open_site()
    assert page.get_attribute("#viewer-status", "role") == "status" and page.get_attribute("#viewer-status", "aria-live") == "polite"


# ---------- simulator: fără „1 produse” ----------

def test_simulator_counts_big_products_without_a_wrong_plural(open_site):
    page, _ = open_site()
    page.click("#sim-threshold")
    page.keyboard.press("Control+A")
    page.keyboard.type("1000")
    page.keyboard.press("Tab")
    page.wait_for_timeout(SETTLE_MS)
    text = page.inner_text(".chain__big").replace(chr(0xA0), " ")
    assert text == "Produse peste prag: 1 (strict peste 1.000 Lei pe bucată)."
    assert "1 produse" not in text


# ---------- contrast forțat ----------

@pytest.fixture
def forced(browser):
    """Fabrică de pagini cu contrastul forțat activ (ca la o temă „high contrast” din Windows)."""
    contexts = []

    def _open(width):
        context = browser.new_context(viewport={"width": width, "height": 900}, forced_colors="active", reduced_motion="reduce")  # fără tranziții: culoarea se citește după schimbare, nu în timpul ei
        contexts.append(context)
        page = context.new_page()
        page.goto(SITE_URL)
        page.wait_for_load_state("load")
        page.wait_for_timeout(SETTLE_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


def test_in_forced_colors_the_chosen_state_of_the_toggles_uses_the_selection_colors(forced):
    page = forced(1280)
    highlight, button_text = page.evaluate(SYSTEM_COLOR, "Highlight"), page.evaluate(SYSTEM_COLOR, "ButtonText")
    page.click("#seg-demo")
    pressed = page.evaluate("getComputedStyle(document.getElementById('seg-demo')).backgroundColor")
    unpressed = page.evaluate("getComputedStyle(document.getElementById('seg-mine')).backgroundColor")
    assert pressed == highlight and unpressed != highlight
    checked = page.evaluate("[...document.querySelectorAll('.pill input:checked + span')].map((s) => getComputedStyle(s).backgroundColor)")
    unchecked = page.evaluate("[...document.querySelectorAll('.pill input:not(:checked) + span')].map((s) => getComputedStyle(s).backgroundColor)")
    assert checked and set(checked) == {highlight}
    assert unchecked and highlight not in unchecked
    dots = page.evaluate("[...document.querySelectorAll('.win__dots i')].map((i) => getComputedStyle(i).backgroundColor)")
    assert dots and set(dots) == {button_text}


def test_in_forced_colors_the_menu_icon_lines_stay_visible_on_a_phone(forced):
    page = forced(390)
    button_text = page.evaluate(SYSTEM_COLOR, "ButtonText")
    bars = page.evaluate("[...document.querySelectorAll('.menu-toggle__bars i')].map((i) => [getComputedStyle(i).backgroundColor, i.getBoundingClientRect().height])")
    assert len(bars) == 3 and all(color == button_text and height > 0 for color, height in bars)
