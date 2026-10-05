"""Teste în browser real (Edge sau Chrome, prin Playwright) ale site-ului din interfata/, deschis din file://.

Primește: interfata/index.html și un browser instalat; singurele date sunt cele inventate din assets/demo-data.js.
Verifică ce nu se vede static: ordinea focusului, regiuni live, reflow la lățimi mici, erori de izolare între
module, fără JavaScript, încărcarea unui analiza.json, aterizarea pe #hash (și în Firefox, dacă e instalat).
NU testează componenta raportului în sine (tests/test_dashboard_browser.py). Se sare dacă niciun browser nu pornește.
"""

import functools
import http.server
import json
import re
import threading

import pytest

from emag_spend import settings
from tests.dashboard_browser_support import attach_probe, launch_browser

sync_api = pytest.importorskip("playwright.sync_api")

SITE_DIR = settings.PROJECT_ROOT / "interfata"
SITE_URL = (SITE_DIR / "index.html").as_uri()
# Lățimi la care bonul din hero a ieșit din ecran (860–895, sub 333) plus cele uzuale; 320 = reflow la zoom 400%.
WIDTHS = (320, 340, 360, 390, 480, 600, 768, 860, 880, 896, 1024, 1100, 1280, 1920)
# Câte adnotări are lista (una pe bloc al raportului): se numără în sursă, ca testele să nu depindă de un număr scris de mână.
ANNOTATION_COUNT = len(re.findall(r"\{ slug: '[a-z]+', block: '", (settings.PROJECT_ROOT / "interfata" / "assets" / "site-annotations.js").read_text(encoding="utf-8")))
# Tastele apăsate la rând din lista de adnotări (de la a doua) până la butoanele explicației: restul listei (ANNOTATION_COUNT - 2) + 1,
# fără raportul de zeci de opriri.
MAX_TABS_LIST_TO_CAPTION = ANNOTATION_COUNT - 1
# Contrast minim între textul din marker și galben (cerneală închisă pe galben: ~12–14:1 în ambele teme).
MIN_MARKER_CONTRAST = 7
# CLS (layout shift) tolerat la încărcare fără #hash: bonul își rezervă înălțimea, deci aproape zero.
MAX_LOAD_CLS = 0.02
SETTLE_MS = 400
# Cod inline scurt (fără spații, ≤ 28 de caractere) care se rupe pe mai multe rânduri sau iese din cutia părintelui.
INLINE_CODE_PROBE_JS = """(() => { const found = {split: [], outside: []};
    for (const code of document.querySelectorAll('code, kbd')) {
      const text = code.textContent.trim(); const rect = code.getBoundingClientRect(); if (!rect.width) continue;
      const box = code.closest('td, th, li, dd, p, .cmd-line, .never, .cap__facts, div').getBoundingClientRect();
      if (code.getClientRects().length > 1 && text.length <= 28 && !/\\s/.test(text)) found.split.push(text);
      if (rect.right > Math.min(box.right, innerWidth) + 1) found.outside.push(text.slice(0, 40)); }
    return found; })()"""
HASH_LANDING = ("probleme", "intrebari", "comenzi", "confidentialitate", "fisiere", "incarca", "faq-date")
SPACING_CSS = "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }"
# Politica de conținut din pagină (style-src 'self') refuză un <style> adăugat de test; o foaie de stil construită (CSSOM) nu e refuzată.
APPLY_SHEET_JS = "(css) => { const s = new CSSStyleSheet(); s.replaceSync(css); document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def playwright_instance():
    """Un singur driver Playwright pentru tot fișierul."""
    with sync_api.sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="module")
def browser(playwright_instance):
    """Browserul instalat (Edge sau Chrome); se sare dacă niciunul nu pornește."""
    try:
        instance = launch_browser(playwright_instance)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    yield instance
    instance.close()


@pytest.fixture
def open_site(browser):
    """Fabrică de pagini: deschide site-ul și întoarce (pagină, sondă); contextele se închid la final."""
    contexts = []

    def _open(*, width=1280, height=900, scheme="light", motion="reduce", touch=False, hash_="", js=True, init_script=None):
        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion=motion,
                                      has_touch=touch, java_script_enabled=js)
        contexts.append(context)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        probe = attach_probe(page)
        page.goto(SITE_URL + (f"#{hash_}" if hash_ else ""))
        page.wait_for_load_state("load")
        page.wait_for_timeout(SETTLE_MS)
        return page, probe

    yield _open
    for context in contexts:
        context.close()


# ---------- ajutoare ----------

def _active_label(page):
    """Eticheta elementului cu focus (aria-label sau primele caractere din text)."""
    return page.evaluate("(() => { const a = document.activeElement; return a ? (a.getAttribute('aria-label') || a.textContent.trim().slice(0, 40)) : null; })()")


def _tabs_until(page, text, limit=150):
    """Câte apăsări de Tab până când elementul cu focus conține `text`; None dacă nu ajunge în `limit`."""
    for count in range(1, limit + 1):
        page.keyboard.press("Tab")
        if text in (_active_label(page) or ""):
            return count
    return None


def _type_into(page, selector, text):
    """Scrie `text` în câmp ca un om (selectează tot, tastează): declanșează input, iar la Tab și change."""
    page.click(selector)
    page.keyboard.press("Control+A")
    page.keyboard.type(text)


def _demo_json(page):
    """Datele demonstrative inventate ale paginii, ca text JSON."""
    return page.evaluate("JSON.stringify(window.EMAG_DEMO_DATA)")


def _upload(page, name, content):
    """Alege `content` (text) ca fișier cu numele `name` în câmpul de încărcare."""
    page.set_input_files("#file-input", files=[{"name": name, "mimeType": "application/json", "buffer": content.encode("utf-8")}])


# ---------- încărcare curată, reflow, bon ----------

@pytest.mark.parametrize("width", WIDTHS)
def test_site_loads_clean_and_fits_the_screen_at_every_width(open_site, width):
    """Fără erori în consolă, fără cereri de rețea, fără scroll orizontal; bonul din hero încape în coloana lui."""
    page, probe = open_site(width=width, height=800)
    assert not any(probe.problems().values()), probe.problems()
    widths = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert widths[0] <= widths[1], widths
    stray = page.evaluate("""(() => { const t = document.querySelector('.ticket').getBoundingClientRect();
        return [...document.querySelectorAll('.ticket *')].filter((e) => !e.closest('.stamp') && e.getBoundingClientRect().right > t.right + 1).length; })()""")
    assert stray == 0, f"{stray} elemente ies din bon la {width}px"


@pytest.mark.parametrize("width", [320, 340, 349, 390])
def test_page_fits_with_wcag_text_spacing(open_site, width):
    """Cu spațierea textului din WCAG 1.4.12 aplicată, nici bonul din hero, nici lanțul simulatorului nu lărgesc pagina (320–349 px: rândurile se rup)."""
    page, _ = open_site(width=width, height=844)
    page.evaluate(APPLY_SHEET_JS, SPACING_CSS)
    assert page.evaluate("getComputedStyle(document.querySelector('.lead')).wordSpacing") != "0px", "spațierea nu s-a aplicat: testul ar trece degeaba"
    widths = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert widths[0] <= widths[1], widths
    stray = page.evaluate("""[...document.querySelectorAll('.ticket *, .sim-chain *')]
        .filter((e) => !e.closest('.stamp') && e.getBoundingClientRect().right > innerWidth + 1).map((e) => e.className)""")
    assert not stray, stray


@pytest.mark.parametrize("size", [(1280, 800), (1024, 768), (390, 844), (320, 700)])
def test_hero_does_not_jump_while_it_fills_in(browser, size):
    """CLS la încărcare (fără #hash) rămâne aproape de zero: piesa din hero își rezervă înălțimea."""
    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, reduced_motion="no-preference")
    try:
        page = context.new_page()
        page.add_init_script("""window.__cls = 0; try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
            .observe({type: 'layout-shift', buffered: true}); } catch (e) {}""")
        page.goto(SITE_URL)
        page.wait_for_timeout(1800)
        assert page.evaluate("window.__cls") < MAX_LOAD_CLS
    finally:
        context.close()


def test_hero_numbers_add_up_in_every_animation_frame(browser):
    """În timpul numărării: comandat − anulat − returnat − în curs = păstrat, la fiecare cadru, nu doar la final."""
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="no-preference")
    try:
        page = context.new_page()
        page.add_init_script("""window.__frames = []; (function () { const raf = window.requestAnimationFrame.bind(window);
            window.requestAnimationFrame = function (cb) { return raf(function (t) { cb(t); const v = {};
              document.querySelectorAll('#ticket [data-key]').forEach((e) => { const x = e.querySelector('[aria-hidden]'); v[e.dataset.key] = x ? x.textContent : null; });
              window.__frames.push(v); }); }; })();""")
        page.goto(SITE_URL)
        page.wait_for_timeout(2200)
        frames = page.evaluate("window.__frames")
    finally:
        context.close()

    def bani(text):
        return round(float(text.replace("Lei", "").replace(" ", "").replace(".", "").replace(",", ".").strip()) * 100) if text else None

    checked = 0
    for frame in frames:
        values = [bani(frame.get(key)) for key in ("ordered_bani", "cancelled_bani", "returned_bani", "pending_bani", "kept_bani")]
        if None in values:
            continue
        checked += 1
        ordered, cancelled, returned, pending, kept = values
        assert ordered - cancelled - returned - pending - (bani(frame.get("unknown_bani")) or 0) == kept, frame
    assert checked > 20


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_hero_marker_keeps_readable_ink_on_one_box(open_site, scheme):
    """Textul din marker are cerneală închisă pe galben (contrast mare) și markerul nu se rupe în două pastile."""
    page, _ = open_site(width=1280, height=800, scheme=scheme)
    info = page.evaluate("""(() => { const m = document.querySelector('.marker'); const c = getComputedStyle(m).color.match(/[\\d.]+/g).map(Number);
        return {ink: c.slice(0, 3), boxes: m.getClientRects().length, hl: getComputedStyle(document.documentElement).getPropertyValue('--hl').trim()}; })()""")

    def luminance(rgb):
        channel = [(v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * channel[0] + 0.7152 * channel[1] + 0.0722 * channel[2]

    highlight = [int(info["hl"][i:i + 2], 16) for i in (1, 3, 5)]
    light, dark = sorted([luminance(info["ink"]), luminance(highlight)], reverse=True)
    assert (light + 0.05) / (dark + 0.05) >= MIN_MARKER_CONTRAST, info
    assert info["boxes"] == 1, info


# ---------- tastatură și ordinea focusului ----------

@pytest.mark.parametrize("width", [1280, 390])
def test_keyboard_goes_from_the_annotation_list_to_the_explanation(open_site, width):
    """De la lista de adnotări, Tab ajunge la „Anterioară” fără să treacă prin raport; punctele numerotate nu primesc focus."""
    page, _ = open_site(width=width, height=900)
    page.focus(".rail__item[data-slug=lant]")
    page.keyboard.press("Enter")
    assert page.evaluate("location.hash") == "#raport-demo/lant"
    assert _tabs_until(page, "Anterioară") <= MAX_TABS_LIST_TO_CAPTION
    page.focus(".rail__item[data-slug=metoda]")
    page.keyboard.press("Tab")
    assert "Anterioară" in _active_label(page)
    page.focus(".rail__item[data-slug=cifra]")
    reached = set()
    for _ in range(40):
        page.keyboard.press("Tab")
        reached.add(page.evaluate("document.activeElement.getAttribute('class') || ''"))  # className e un obiect pe elementele SVG
    assert "hs" not in reached and "tree" not in reached


def test_theme_button_comes_right_after_the_logo_in_the_desktop_sidebar(open_site):
    """Pe desktop comutatorul de temă e a treia oprire și stă vizual între siglă și cuprins (focus = aspect)."""
    page, _ = open_site(width=1280, height=800)
    for _ in range(3):
        page.keyboard.press("Tab")
    assert _active_label(page) == "Temă: automată"
    tops = page.evaluate("""[document.querySelector('.site-brand'), document.getElementById('theme-toggle'), document.querySelector('.toc a')]
        .map((e) => Math.round(e.getBoundingClientRect().top))""")
    assert tops == sorted(tops), tops


@pytest.mark.parametrize("size", [(1366, 650), (1280, 560)])
def test_sidebar_keeps_the_theme_button_on_screen_on_short_laptops(open_site, size):
    """Pe un laptop scund butonul de temă nu e tăiat la marginea de jos a barei laterale."""
    page, _ = open_site(width=size[0], height=size[1])
    assert page.evaluate("document.getElementById('theme-toggle').getBoundingClientRect().bottom") <= size[1]


def test_mobile_menu_closes_when_focus_leaves_the_header(open_site):
    """Tab dincolo de ultimul link din meniul deschis închide meniul: focusul nu intră în conținutul acoperit."""
    page, _ = open_site(width=390, height=844, touch=True)
    page.focus("#menu-toggle")
    page.keyboard.press("Enter")
    assert page.get_attribute("#menu-toggle", "aria-expanded") == "true"
    assert _tabs_until(page, "Deschide raportul tău") is not None
    page.keyboard.press("Tab")
    assert page.get_attribute("#menu-toggle", "aria-expanded") == "false"


def test_picking_an_annotation_on_a_phone_brings_the_window_into_view(open_site):
    """Pe telefon, alegerea din listă aduce fereastra sub antet, blocul evidențiat se vede, butoanele nu fug între pași."""
    page, _ = open_site(width=390, height=844, touch=True)
    page.click(".rail__item[data-slug=categorii]")
    page.wait_for_timeout(700)
    layout = page.evaluate("""(() => { const win = document.getElementById('demo-win').getBoundingClientRect(); const mark = document.querySelector('.win__mark').getBoundingClientRect();
        const frame = document.getElementById('demo-scroll').getBoundingClientRect();
        const next = [...document.querySelectorAll('#demo-caption button')].find((b) => b.textContent.trim() === 'Următoarea').getBoundingClientRect();
        return {winTop: win.top, markVisible: mark.top < frame.bottom && mark.bottom > frame.top, nextTop: next.top, vh: innerHeight, frameH: frame.height}; })()""")
    assert 40 <= layout["winTop"] <= 130 and layout["markVisible"] and 0 < layout["nextTop"] < layout["vh"], layout
    assert layout["frameH"] >= 0.4 * layout["vh"], layout
    tops = []
    for _ in range(4):
        tops.append(round(page.evaluate("[...document.querySelectorAll('#demo-caption button')].find((b) => b.textContent.trim() === 'Următoarea').getBoundingClientRect().top + scrollY")))
        page.click("#demo-caption button:has-text('Următoarea')")
        page.wait_for_timeout(250)
    assert max(tops) - min(tops) <= 1, tops


def test_back_to_the_empty_address_clears_the_annotation(open_site):
    """După „Înapoi” până la adresa fără adnotare, selecția și chenarul de evidențiere dispar."""
    page, _ = open_site()
    for slug in ("cifra", "lant", "cifre"):
        page.click(f".rail__item[data-slug={slug}]")
        page.wait_for_timeout(120)
    for _ in range(3):
        page.evaluate("history.back()")
        page.wait_for_timeout(450)
    assert page.evaluate("location.hash") in ("", "#")
    assert page.evaluate("document.querySelector('.rail__item[aria-pressed=true]')") is None
    assert page.evaluate("document.querySelector('.win__mark').hidden") is True


# ---------- titluri, nume accesibile, fără JavaScript ----------

def test_report_blocks_sit_below_the_section_headings(open_site):
    """Un singur h1 și 10 titluri h2 (câte unul pe secțiune): raportul montat folosește h3/h4, nu 12 h2 în plus."""
    page, _ = open_site()
    counts = page.evaluate("({h1: document.querySelectorAll('h1').length, h2: document.querySelectorAll('h2').length, demoH2: document.querySelectorAll('#demo-mount h2').length, demoH3: document.querySelectorAll('#demo-mount h3').length})")
    assert counts["h1"] == 1 and counts["h2"] == 10 and counts["demoH2"] == 0 and counts["demoH3"] >= 12, counts
    page.click("#seg-demo")
    assert page.evaluate("document.querySelectorAll('#viewer-mount h2').length") == 0


def test_accessible_names_do_not_include_decorative_marks(browser, open_site):
    """Semnele „+”/„−” din <summary> nu intră în nume; butonul de temă și sigla au nume care conțin textul vizibil."""
    if browser.browser_type.name != "chromium":
        pytest.skip("arborele de accesibilitate se citește prin CDP (Chromium)")
    page, _ = open_site()
    cdp = page.context.new_cdp_session(page)
    cdp.send("Accessibility.enable")
    root = cdp.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]

    def name_of(selector):
        node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        return cdp.send("Accessibility.getPartialAXTree", {"nodeId": node, "fetchRelatives": False})["nodes"][0]["name"]["value"]

    assert name_of("#faq-pentru-toti > summary") == "Funcționează pentru toți?"
    assert "+" not in name_of("#paste > summary")
    assert name_of("#theme-toggle") == "Temă: automată"
    assert "Cheltuieli eMAG interfață locală" in name_of(".site-brand")


def test_without_javascript_the_dead_widgets_are_hidden_and_the_text_stays(open_site):
    """Fără JS: antetul nu mai e lipicios, controalele moarte sunt ascunse, iar secțiunile interactive au un mesaj <noscript>."""
    page, _ = open_site(width=390, height=844, js=False)
    state = page.evaluate("""({pos: getComputedStyle(document.getElementById('antet')).position,
        hidden: ['#theme-toggle', '.annot', '.sim', '.viewer', '.hero__piece', '.pfilter', '.annot ~ .note', '[data-copy-from]', '.flow__pause']
            .map((s) => getComputedStyle(document.querySelector(s)).display),
        noscripts: document.querySelectorAll('noscript').length, lead: document.querySelector('#cum-functioneaza .step') !== null})""")
    assert state["pos"] == "static" and set(state["hidden"]) == {"none"} and state["noscripts"] >= 4 and state["lead"], state
    desktop, _ = open_site(width=1280, height=800, js=False)
    assert desktop.evaluate("getComputedStyle(document.getElementById('antet')).position") == "fixed"


# ---------- tabele și comenzi pe ecran îngust ----------

@pytest.mark.parametrize("width", [320, 360, 390, 759])
def test_tables_stack_with_full_width_cells_and_captions(open_site, width):
    """Sub 760 px mesajul din „Probleme și soluții” ocupă tot rândul, iar titlurile de tabel nu rămân coloane înguste."""
    page, _ = open_site(width=width, height=800)
    sizes = page.evaluate("""(() => { const row = [...document.querySelectorAll('#problems-table tbody tr')].find((r) => !r.classList.contains('group'));
        const th = row.querySelector('th').getBoundingClientRect().width, td = row.querySelector('td').getBoundingClientRect().width;
        const cap = document.querySelector('#confidentialitate caption').getBoundingClientRect().width, table = document.querySelector('#confidentialitate table').getBoundingClientRect().width;
        return {th, td, cap, table}; })()""")
    assert sizes["th"] >= sizes["td"] - 2 and sizes["cap"] >= sizes["table"] - 2, sizes


def test_problem_table_keeps_its_column_widths_on_desktop(open_site):
    """De la 760 px coloana de mesaj rămâne ~34% din tabel (regula de lățime nu mai bate stivuirea sub 760)."""
    page, _ = open_site(width=1024, height=800)
    th, td = page.evaluate("""(() => { const row = [...document.querySelectorAll('#problems-table tbody tr')].find((r) => !r.classList.contains('group'));
        return [row.querySelector('th').getBoundingClientRect().width, row.querySelector('td').getBoundingClientRect().width]; })()""")
    assert 0.30 < th / (th + 2 * td) < 0.40


@pytest.mark.parametrize("width", [320, 360, 390])
def test_command_blocks_put_the_button_under_the_code_on_phones(open_site, width):
    """Pe telefon codul ia toată lățimea (butonul „Copiază” trece dedesubt), iar steagurile scurte nu se rup în două rânduri."""
    page, _ = open_site(width=width, height=800)
    info = page.evaluate("""(() => { const code = document.getElementById('c-prag').getBoundingClientRect(); const btn = document.querySelector("button[data-copy-from='#c-prag']").getBoundingClientRect();
        return {code: code.width, below: btn.top >= code.bottom - 1, split: [...document.querySelectorAll('code.nb')].filter((c) => c.getClientRects().length > 1).length}; })()""")
    assert info["code"] >= width - 80 and info["below"] and info["split"] == 0, info


@pytest.mark.parametrize("engine", ["default", "firefox"])
def test_inline_code_neither_splits_nor_sticks_out(playwright_instance, browser, engine):
    """Cod scurt fără spații (steaguri, căi) rămâne pe un rând și încape în rândul sau celula lui; Firefox îl rupea la „/” și la cratimă."""
    if engine == "firefox":
        try:
            instance = playwright_instance.firefox.launch(channel="moz-firefox")
        except Exception as exc:  # Firefox lipsește sau nu e controlabil: testul se sare
            pytest.skip(f"Firefox indisponibil: {str(exc).splitlines()[0]}")
    else:
        instance = browser
    try:
        for width in (320, 390, 768):
            context = instance.new_context(viewport={"width": width, "height": 800})
            page = context.new_page()
            page.goto(SITE_URL)
            page.wait_for_timeout(SETTLE_MS)
            page.evaluate("document.querySelectorAll('details').forEach((d) => { d.open = true; })")  # și răspunsurile din FAQ
            found = page.evaluate(INLINE_CODE_PROBE_JS)
            context.close()
            assert found == {"split": [], "outside": []}, (width, found)
    finally:
        if engine == "firefox":
            instance.close()


# ---------- simulator, filtru, încărcare de fișier ----------

def test_threshold_field_reads_romanian_numbers_and_does_not_respeak_the_rule(open_site):
    """Câmpul de prag înțelege „1.000” și „499,99”, plafonează valorile uriașe și nu rescrie regula din zona live la fiecare tastă."""
    page, _ = open_site()
    page.evaluate("""window.__rule = 0; new MutationObserver((r) => { window.__rule += r.length; }).observe(document.getElementById('sim-rule'), {childList: true, subtree: true, characterData: true});""")
    _type_into(page, "#sim-threshold", "1234")
    assert page.evaluate("window.__rule") == 0, "regula activă a fost rescrisă la tastare"
    assert "1.234" in page.inner_text("#sim-threshold-hint")
    for typed, shown in (("1.000", "1.000"), ("499,99", "499,99"), ("499.99", "499,99"), ("0,5", "0,50")):
        page.fill("#sim-threshold", typed)
        assert shown in page.inner_text("#sim-threshold-hint"), typed
    for typed, kept in (("-5", "500"), ("1e308", "500"), ("99999999", "1000000")):
        _type_into(page, "#sim-threshold", typed)
        page.keyboard.press("Tab")
        page.wait_for_timeout(250)
        assert page.input_value("#sim-threshold") == kept, typed
    assert "∞" not in page.inner_text("#sim-chain")
    page.check("input[name=stare-D-01][value=cancelled]", force=True)
    page.wait_for_timeout(200)
    assert page.evaluate("window.__rule") >= 1, "la schimbarea stării regula trebuie rescrisă"
    shows = page.evaluate("document.querySelectorAll('.sim-order__shows')[2].textContent")
    assert "de 2 ori" in shows, "D-03 (2 bucăți) cu retur finalizat trebuie să spună că returul listează produsul de 2 ori"


def test_problem_filter_announces_once_and_matches_real_messages(open_site):
    """Contorul se scrie o singură dată după pauză; mesajele reale (cu numere și nume) găsesc rândul lor."""
    page, _ = open_site()
    page.evaluate("""window.__count = []; new MutationObserver(() => window.__count.push(document.getElementById('problems-count').textContent))
        .observe(document.getElementById('problems-count'), {childList: true, characterData: true, subtree: true});""")
    page.click("#problems-filter")
    page.keyboard.type("status", delay=60)
    page.wait_for_timeout(900)
    assert len(page.evaluate("window.__count")) == 1

    def visible_rows(query):
        page.fill("#problems-filter", query)
        return page.evaluate("[...document.querySelectorAll('#problems-table tbody tr')].filter((r) => !r.hidden && !r.classList.contains('group') && !r.classList.contains('empty')).length")

    for query in ("1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat",
                  "2 produse necategorizate (adaugă reguli în config/categorii.json)",
                  "retur 12345: comanda 100000001 nu e în lista citită",
                  "suma produselor (22298) ≠ 'Total produse' (22000)",
                  "status necunoscut"):
        assert visible_rows(query) >= 1, query
    assert visible_rows("xyzxyz") == 0


@pytest.mark.parametrize("missing", ["site-theme.js", "site-nav.js", "site-hero.js", "site-simulator.js", "site-viewer.js", "site-copy.js"])
def test_a_missing_script_does_not_stop_the_other_modules(browser, missing):
    """Un site*.js blocat sau lipsă lasă celelalte module să pornească (lista de adnotări, simulatorul, bonul)."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        page.route(f"**/{missing}", lambda route: route.abort())
        page.goto(SITE_URL)
        page.wait_for_timeout(500)
        started = page.evaluate("""({rail: document.querySelectorAll('.rail__item').length, chain: !!document.querySelector('.chain__row'),
            ticket: !!document.querySelector('.ticket__val .sr-only')})""")
    finally:
        context.close()
    started["rail"] = started["rail"] == ANNOTATION_COUNT
    unaffected = {"site-theme.js": ("rail", "chain", "ticket"), "site-nav.js": ("rail", "chain", "ticket"), "site-hero.js": ("rail", "chain"),
                  "site-simulator.js": ("rail", "ticket"), "site-viewer.js": ("rail", "chain", "ticket"), "site-copy.js": ("rail", "chain", "ticket")}[missing]
    assert all(started[key] for key in unaffected), started


def test_copy_button_survives_a_clipboard_that_throws(open_site):
    """Dacă navigator.clipboard.writeText aruncă sincron, butonul trece pe rezerva de selecție, fără eroare necaptată."""
    page, probe = open_site()
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText() { throw new Error('sync'); }}, configurable: true}); document.execCommand = () => false;")
    page.click("button[data-copy-from='#c-demo']")
    page.wait_for_timeout(150)
    assert "Ctrl" in page.inner_text("button[data-copy-from='#c-demo']")
    assert not probe.page_errors


def test_viewer_does_not_say_done_when_the_report_could_not_be_drawn(open_site):
    """Dacă mount raportează ok=false, vizualizatorul arată eroare (nu „Gata”) și nu afișează bannerul „Raportul tău”."""
    page, _ = open_site()
    page.evaluate("""(() => { const real = window.EmagDashboard; Object.defineProperty(window, 'EmagDashboard', {configurable: true, value: Object.assign({}, real, {
        mount(root, data, opts) { const r = real.mount(root, data, opts); return opts && opts.demo ? r : {unmount() { r.unmount(); }, root, ok: false, errors: ['Eroare la desenare: simulată pentru test.']}; } })}); })()""")
    _upload(page, "analiza.json", _demo_json(page))
    page.wait_for_timeout(500)
    status = page.inner_text("#viewer-status")
    assert status.startswith("Eroare") and "Gata" not in status, status
    assert page.evaluate("document.getElementById('viewer-banner').hidden") is True


def test_a_very_long_file_name_does_not_widen_the_page(open_site):
    """Un nume de fișier de 200 de caractere fără spații nu lărgește pagina la 360 px."""
    page, _ = open_site(width=360, height=800)
    _upload(page, "iesiri_demo_" + "x" * 190 + ".json", _demo_json(page))
    page.wait_for_timeout(800)
    widths = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert widths[0] <= widths[1], widths


def test_drag_layer_is_nearly_opaque(open_site):
    """Stratul de tragere acoperă aproape opac zona de dedesubt: mesajul nu se suprapune peste titlul zonei de tragere."""
    page, _ = open_site()
    page.evaluate("document.documentElement.classList.add('is-dragging')")
    color = page.evaluate("getComputedStyle(document.body, '::after').backgroundColor")
    alpha = float(color.replace("rgba(", "").replace(")", "").split(",")[3]) if color.startswith("rgba(") else 1.0
    assert alpha >= 0.85, color


# ---------- aterizare pe #hash, politica de conținut ----------

@pytest.mark.parametrize("engine", ["default", "firefox"])
def test_direct_links_land_on_their_target(playwright_instance, browser, engine):
    """Încărcarea directă a #secțiune sau #faq-… așază ținta sus (Firefox făcea un singur salt, înainte să se umple simulatorul)."""
    if engine == "firefox":
        try:
            instance = playwright_instance.firefox.launch(channel="moz-firefox")
        except Exception as exc:  # Firefox lipsește sau nu e controlabil: testul se sare
            pytest.skip(f"Firefox indisponibil: {str(exc).splitlines()[0]}")
    else:
        instance = browser
    try:
        for target in HASH_LANDING:
            context = instance.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto(SITE_URL + "#" + target)
            page.wait_for_timeout(1200)
            top = page.evaluate("(id) => Math.round(document.getElementById(id).getBoundingClientRect().top)", target)
            context.close()
            assert 0 <= top <= 120, f"#{target}: ținta e la {top}px de marginea de sus"
    finally:
        if engine == "firefox":
            instance.close()


def test_boot_script_sets_the_js_class_and_saved_theme_before_the_body_exists(open_site):
    """site-boot.js (fișier extern, nu inline) rulează înaintea <body>: clasa js și tema salvată sunt deja pe <html> la prima pictare."""
    probe_js = """localStorage.setItem('emag-tema', 'dark');
        new MutationObserver(() => { if (document.body && !window.__first) window.__first = [document.documentElement.className, document.documentElement.getAttribute('data-theme')]; })
          .observe(document, {childList: true, subtree: true});"""
    page, probe = open_site(scheme="light", init_script=probe_js)
    assert page.evaluate("window.__first") == ["js", "dark"]
    assert page.evaluate("document.getElementById('theme-toggle').dataset.mode") == "dark"
    assert not any(probe.problems().values()), probe.problems()


def test_the_page_policy_blocks_network_requests_by_itself(open_site):
    """Cu politica din <meta>, un fetch, o imagine sau un script inline către/din afara paginii sunt refuzate de browser."""
    page, _ = open_site()
    answered, failed = [], []  # răspunsuri de pe internet; cereri oprite de browser (Playwright le raportează cu motivul „csp”)
    page.on("response", lambda response: answered.append(response.url) if response.url.startswith("http") else None)
    page.on("requestfailed", lambda request: failed.append((request.url, request.failure)))
    page.evaluate("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.effectiveDirective));")
    outcome = page.evaluate("fetch('https://example.invalid/leak').then(() => 'sent', () => 'blocked')")
    page.evaluate("new Image().src = 'https://example.invalid/leak.png'")
    page.evaluate("(() => { const s = document.createElement('script'); s.textContent = 'window.__ran = 1'; document.head.appendChild(s); })()")
    page.wait_for_timeout(300)
    violations = page.evaluate("window.__csp")
    assert outcome == "blocked" and {"connect-src", "img-src"} <= set(violations), (outcome, violations)
    assert any(name.startswith("script-src") for name in violations) and page.evaluate("window.__ran") is None, violations
    assert answered == [] and failed == [("https://example.invalid/leak.png", "csp")], (answered, failed)


def test_site_works_under_a_strict_content_security_policy(browser):
    """Sub script-src/style-src 'self' (și ca antet HTTP, nu doar ca <meta>) nu apare nicio încălcare; barele (flex-grow) se desenează."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        """Servește doar interfata/ și adaugă antetul CSP."""

        def end_headers(self):
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:")
            super().end_headers()

        def log_message(self, *args):
            """Fără zgomot în ieșirea testelor."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(SITE_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push([e.violatedDirective, e.blockedURI]));")
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
        page.wait_for_timeout(1200)
        violations = page.evaluate("window.__csp")
        bars = page.evaluate("[...document.querySelectorAll('#ticket-bar i')].map((i) => i.getBoundingClientRect().width)")
        rail = page.evaluate("document.querySelectorAll('.rail__item').length")
    finally:
        context.close()
        server.shutdown()
    assert violations == [], violations
    assert bars and min(bars) > 0 and rail == ANNOTATION_COUNT, (bars, rail)
