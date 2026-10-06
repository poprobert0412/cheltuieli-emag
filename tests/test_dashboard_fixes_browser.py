"""Teste de regresie în browser pentru reparațiile auditului interfeței (Edge sau Chrome instalat, prin Playwright).

Fiecare test reproduce o problemă găsită de verificatori și ar pica pe versiunea veche: contrast forțat,
puncte de oprire Tab, ținte de 40 px, „eMAG” netraductibil în datele din cont, tabele ca liste de carduri
pe ecran îngust, grafic pe ani care încape pe telefon, focus tăiat la marginea ecranului, memorie reținută
de tabelele înlocuite, paginarea listelor lungi, date inexistente, curățenia la rădăcină scoasă din document.
Datele sunt inventate (tests/dashboard_samples.py). Fixture-urile și ajutoarele vin din test_dashboard_browser.py.
"""

import pytest

from emag_spend import settings
from emag_spend.report_html import write_report
from tests.dashboard_browser_support import write_harness
# Fixture-urile (`browser`, `data`, `open_page`) se importă pe nume ca pytest să le găsească și aici.
from tests.test_dashboard_browser import (  # noqa: F401
    BLOCKS, INSTRUMENT_LISTENERS, assert_clean, blocks, browser, data, mount, open_page, settle,
)

NBSP = chr(0xA0)  # spațiul nedespărțitor, generat din cod (nu scris de mână)
FOCUS_RING_PX = 4  # 2 px contur + 2 px decalaj: cât iese inelul de focus în afara elementului
MAX_TAB_PRESSES = 400  # raportul are acum și linkuri către comenzi și butoane de extindere în tabele: cercul de Tab e mai lung decât 150


def sound(text):
    """Textul fără spații nedespărțitoare, ca asertările să nu depindă de ele."""
    return text.replace(NBSP, " ")


# ---------- contrast forțat (Windows high contrast) ----------

@pytest.fixture
def forced_page(browser, tmp_path, data):  # noqa: F811
    """Pagină cu contrastul forțat activ, ca la un utilizator cu tema „high contrast” din Windows."""
    contexts = []

    def _open():
        context = browser.new_context(viewport={"width": 1280, "height": 900}, forced_colors="active")
        contexts.append(context)
        page = context.new_page()
        page.goto(write_harness(tmp_path, data).as_uri())
        return page

    yield _open
    for context in contexts:
        context.close()


SYSTEM_COLOR = """(keyword) => { const probe = document.createElement('i'); probe.style.background = keyword; document.body.appendChild(probe);
  const color = getComputedStyle(probe).backgroundColor; probe.remove(); return color; }"""


def test_forced_colors_keep_the_funnel_bars_category_bars_and_swatches_visible(forced_page):
    page = forced_page()
    mount(page)
    settle(page)
    canvas = page.evaluate(SYSTEM_COLOR, "Canvas")
    paint = page.evaluate("""() => { const read = (sel) => [...document.querySelectorAll('#a ' + sel)].map((e) => { const s = getComputedStyle(e);
        return { bg: s.backgroundColor, border: s.borderTopWidth }; });
      return { seg: read('.ed-funnel-seg'), fill: read('.ed-bar-fill'), sw: read('.ed-legend-item .ed-sw, .ed-fl-item .ed-sw:not(.ed-sw-ring)') }; }""")
    for kind, items in paint.items():
        assert items, kind
        assert all(i["bg"] != canvas and i["bg"] != "rgba(0, 0, 0, 0)" for i in items), (kind, canvas, items[:2])  # culoarea lor, nu fundalul paginii
        assert all(i["border"] == "1px" for i in items), kind  # contur de text: marginea se vede pe orice fundal


def test_forced_colors_still_tell_a_pressed_filter_from_an_unpressed_one(forced_page):
    page = forced_page()
    mount(page)
    highlight, canvas = page.evaluate(SYSTEM_COLOR, "Highlight"), page.evaluate(SYSTEM_COLOR, "Canvas")
    chips = page.locator("#a [data-ed-block='big'] .ed-chip")
    colors = lambda i: chips.nth(i).evaluate("e => getComputedStyle(e).backgroundColor")
    assert chips.nth(0).get_attribute("aria-pressed") == "true" and colors(0) == highlight
    assert colors(1) != highlight and colors(1) == canvas
    toggle = page.locator("#a [data-ed-block='categories'] .ed-toggle")
    before = toggle.evaluate("e => getComputedStyle(e).backgroundColor")
    toggle.click()
    page.wait_for_timeout(300)  # tranziția de culoare (0,12 s) trebuie să se termine, altfel getComputedStyle citește valoarea veche
    assert toggle.evaluate("e => getComputedStyle(e).backgroundColor") == highlight != before


# ---------- tastatură: un singur punct de oprire pe listă ----------

def test_each_bar_list_is_one_tab_stop_and_the_whole_page_has_few_stops(open_page):
    page, _ = open_page()
    mount(page)
    settle(page)
    per_list = page.evaluate("[...document.querySelectorAll('#a .ed-bars')].map((ul) => [ul.querySelectorAll('.ed-bar-row[tabindex=\"0\"]').length, ul.querySelectorAll('.ed-bar-row').length])")
    assert len(per_list) == 2  # categorii și vânzători
    assert all(stops == 1 and rows > 3 for stops, rows in per_list)
    page.keyboard.press("Tab")
    page.evaluate("window.__first = document.activeElement")
    classes = [page.evaluate("document.activeElement.className")]
    for _ in range(MAX_TAB_PRESSES):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement === document.body || document.activeElement === window.__first"):
            break  # s-a închis cercul: focusul a ieșit din pagină sau a revenit la început
        classes.append(page.evaluate("document.activeElement.className.baseVal ?? document.activeElement.className"))
    assert len(classes) > 10 and classes.count("ed-bar-row") == 2  # înainte erau 31 de opriri, câte una pe rând-bară


def test_arrow_keys_home_and_end_move_between_rows_and_tab_remembers_the_current_row(open_page):
    page, probe = open_page()
    mount(page)
    list_selector = "#a [data-ed-block='categories'] .ed-bars"
    rows = page.locator(f"{list_selector} .ed-bar-row")
    last = rows.count() - 1
    focused = lambda: page.evaluate("(sel) => [...document.querySelectorAll(sel)].indexOf(document.activeElement)", f"{list_selector} .ed-bar-row")
    page.focus("#a [data-ed-block='categories'] .ed-toggle")
    page.keyboard.press("Tab")
    assert focused() == 0
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert focused() == 2 and page.is_visible("#a .ed-tip")  # tooltip-ul urmărește focusul și la săgeți
    assert rows.nth(2).get_attribute("tabindex") == "0" and rows.nth(0).get_attribute("tabindex") == "-1"
    page.keyboard.press("ArrowUp")
    assert focused() == 1
    page.keyboard.press("End")
    assert focused() == last
    page.keyboard.press("ArrowDown")
    assert focused() == last  # la capăt rămâne pe loc
    page.keyboard.press("Home")
    page.keyboard.press("ArrowUp")
    assert focused() == 0
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")  # părăsește lista
    assert focused() == -1
    page.keyboard.press("Shift+Tab")
    assert focused() == 1  # revine pe rândul pe care a rămas
    assert_clean(probe)


# ---------- ținte de cel puțin 40 px, și cu mouse-ul ----------

def test_every_button_and_summary_is_at_least_40px_tall_even_with_a_mouse(open_page):
    page, _ = open_page(width=1280, height=900)
    mount(page, "hostile")
    settle(page)
    small = page.evaluate("""() => [...document.querySelectorAll('#a button, #a summary')].filter((e) => e.offsetParent !== null)
      .map((e) => [e.className || e.tagName, e.textContent.trim().slice(0, 24), e.getBoundingClientRect().height]).filter(([, , h]) => h < 39.9)""")
    assert small == []
    assert page.locator("#a .ed-more").count() >= 1 and page.locator("#a summary").count() >= 1  # a măsurat și „Arată încă”, și rezumatele


def test_on_a_touch_screen_the_tappable_bar_rows_are_40px_tall_too(open_page):
    page, _ = open_page(width=390, height=844, touch=True)
    mount(page)
    settle(page)
    heights = page.eval_on_selector_all("#a .ed-bar-row", "els => els.map((e) => e.getBoundingClientRect().height)")
    assert len(heights) > 20 and min(heights) >= 39.9


# ---------- „eMAG” din date nu se traduce automat ----------

EMAG_OUTSIDE_NO_TRANSLATE = """() => { const found = []; const walker = document.createTreeWalker(document.getElementById('a'), NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) { const node = walker.currentNode;
    if (/eMAG/.test(node.nodeValue) && !node.parentElement.closest('[translate=no]')) found.push(node.nodeValue.slice(0, 60)); }
  return found; }"""


@pytest.mark.parametrize("dataset", ["demo", "small", "hostile"])
def test_brand_name_inside_the_data_is_wrapped_in_translate_no(open_page, dataset):
    page, _ = open_page()
    mount(page, dataset)
    settle(page)
    assert page.evaluate(EMAG_OUTSIDE_NO_TRANSLATE) == []
    assert page.locator("#a [translate=no]", has_text="eMAG").count() > 10  # scanarea a văzut cu adevărat numele


def test_brand_name_in_any_text_from_the_account_is_wrapped_including_tooltips_and_warnings(open_page):
    page, _ = open_page()
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.small));
      d.top_products[0].name = 'Voucher eMAG de test'; d.by_seller[0].seller = 'eMAG Marketplace Test';
      d.warnings = ['status necunoscut la comanda 9 (eMAG): ceva nou']; d.uncategorized = [{ name: 'Cadou eMAG', units: 1, bani: 1000 }]; d.uncategorized_count = 1;
      d.highlights.Alcool.items[0].name = 'Whisky de la eMAG'; DATA.branded = d; }""")
    mount(page, "branded")
    settle(page)
    page.hover("#a [data-ed-block='sellers'] .ed-bar-row >> nth=0")
    assert "eMAG" in page.inner_text("#a .ed-tip-title")
    assert page.evaluate(EMAG_OUTSIDE_NO_TRANSLATE) == []
    assert page.eval_on_selector_all("#a [translate=no]", "els => els.map((e) => e.textContent).filter((t) => t === 'eMAG').length") >= 6


# ---------- tabele ca liste de carduri pe ecran îngust ----------

CARD_REPORT = """() => ['big', 'highlights', 'top', 'excluded'].flatMap((block) => [...document.querySelectorAll("#a [data-ed-block='" + block + "'] .ed-tbl-wrap")].map((wrap) => {
  const table = wrap.querySelector('table'); return { block, over: wrap.scrollWidth - wrap.clientWidth, display: getComputedStyle(table).display }; }))"""


@pytest.mark.parametrize("width", [360, 390, 768])
def test_long_tables_become_cards_so_value_and_state_never_leave_the_screen(open_page, width):
    page, probe = open_page(width=width, height=900)
    mount(page, "demo")
    settle(page)
    report = page.evaluate(CARD_REPORT)
    assert {r["block"] for r in report} == {"big", "highlights", "top", "excluded"}
    assert all(r["over"] <= 1 and r["display"] == "block" for r in report), report
    in_screen = page.evaluate("""() => ['Valoare', 'Stare'].map((label) => [...document.querySelectorAll("#a [data-ed-block='big'] td[data-label='" + label + "']")].slice(0, 6)
      .every((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= innerWidth; }))""")
    assert in_screen == [True, True]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


def test_tables_stay_tables_on_a_wide_component_and_cards_in_a_mid_width_frame(open_page):
    page, _ = open_page(width=1280, height=900)
    mount(page, "demo")
    settle(page)
    assert {r["display"] for r in page.evaluate(CARD_REPORT)} == {"table"}
    assert page.evaluate("getComputedStyle(document.querySelector('#a [data-ed-block=big] td:nth-child(7)'), '::before').content") in ("none", "normal")
    framed, _ = open_page(width=1280, height=900, wrapper_style="width: 900px")  # ca fereastra demo din site: componenta e mai îngustă decât pagina
    mount(framed, "demo")
    settle(framed)
    assert {r["display"] for r in framed.evaluate(CARD_REPORT)} == {"block"}


def test_cards_keep_table_semantics_labels_and_hide_empty_fields(open_page):
    page, _ = open_page(width=390, height=900)
    mount(page, "demo")
    settle(page)
    info = page.evaluate("""() => { const table = document.querySelector("#a [data-ed-block='big'] table");
      const heads = [...table.querySelectorAll('thead th')].map((th) => th.textContent);
      const labels = [...table.querySelectorAll('tbody tr:first-child td')].map((td) => td.dataset.label);
      const footVisible = [...table.querySelectorAll('tfoot td')].filter((td) => getComputedStyle(td).display !== 'none').map((td) => td.dataset.label);
      const headBox = table.querySelector('thead').getBoundingClientRect();
      return { roles: [table.getAttribute('role'), table.querySelector('thead').getAttribute('role'), table.querySelector('tbody tr').getAttribute('role'),
                       table.querySelector('th').getAttribute('role'), table.querySelector('td').getAttribute('role')],
               heads, labels, footVisible, headSize: [headBox.width, headBox.height] }; }""")
    assert info["roles"] == ["table", "rowgroup", "row", "columnheader", "cell"]
    assert info["labels"] == info["heads"]  # eticheta fiecărei celule e antetul coloanei ei
    assert info["footVisible"] == ["Produs", "Buc", "Plătit"]  # totalul: câmpurile goale nu ocupă loc
    assert info["headSize"] == [1, 1]  # antetul rămâne pentru cititoarele de ecran, ascuns doar vizual


def test_card_text_from_the_data_is_still_plain_text(open_page):
    page, probe = open_page(width=390, height=900)
    mount(page, "hostile")
    settle(page)
    assert page.evaluate("window.__pwned === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


# ---------- graficul pe ani încape pe telefon ----------

YEAR_AXIS = """() => { const host = document.querySelector('#a .ed-chart-scroll'), svg = host.querySelector('svg');
  const labels = [...svg.querySelectorAll('text[text-anchor=middle]:not(.ed-total)')].map((t) => { const r = t.getBoundingClientRect(); return { text: t.textContent, left: r.left, right: r.right }; });
  return { host: host.clientWidth, svg: +svg.getAttribute('width'), scrolls: host.scrollWidth > host.clientWidth + 1, labels }; }"""


@pytest.mark.parametrize("width", [360, 390])
def test_year_chart_fits_a_phone_and_thins_year_labels_without_overlap(open_page, data, width):
    years = data["demo"]["by_year_category"]["years"]
    page, probe = open_page(width=width, height=800)
    mount(page)
    settle(page)
    axis = page.evaluate(YEAR_AXIS)
    assert not axis["scrolls"] and axis["svg"] == axis["host"]  # înainte: 476 px într-un loc de 294
    labels = axis["labels"]
    assert 1 < len(labels) < len(years) and labels[-1]["text"] == years[-1]  # ultimul an are mereu etichetă
    assert all(a["right"] <= b["left"] for a, b in zip(labels, labels[1:])), [l["text"] for l in labels]
    assert page.locator("#a svg.ed-chart rect.ed-hit").count() == len(years)  # toate coloanele rămân cu tooltip
    assert_clean(probe)


def test_year_chart_labels_every_year_when_there_is_room_and_scrolls_when_there_is_none(open_page, data):
    years = data["demo"]["by_year_category"]["years"]
    page, _ = open_page(width=1280, height=900)
    mount(page)
    settle(page)
    wide = page.evaluate(YEAR_AXIS)
    assert [l["text"] for l in wide["labels"]] == years
    page.set_viewport_size({"width": 320, "height": 800})
    settle(page)
    tiny = page.evaluate(YEAR_AXIS)
    assert tiny["scrolls"] and tiny["svg"] > tiny["host"]  # sub lățimea minimă a coloanelor rămâne derularea orizontală


def test_year_chart_keeps_a_visible_focus_ring_on_the_focused_column(open_page):
    page, _ = open_page()
    mount(page)
    page.focus("#a svg.ed-chart .ed-hit >> nth=2")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    style = page.evaluate("""() => { const e = document.activeElement, s = getComputedStyle(e);
      const focus = getComputedStyle(document.getElementById('a')).getPropertyValue('--ed-focus').trim();
      return { isHit: e.classList.contains('ed-hit'), stroke: s.stroke, width: s.strokeWidth, fill: s.fill, probe: (() => { const p = document.createElement('i'); p.style.color = focus; document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; })() }; }""")
    assert style["isHit"] and style["width"] == "2px" and style["stroke"] == style["probe"]  # contur, nu doar umplere


# ---------- focus: inelul nu se taie la marginea ecranului ----------

@pytest.mark.parametrize("offset, edge", [(-100, "top"), (800, "bottom")])
def test_focus_on_a_half_visible_scroll_region_leaves_room_for_the_focus_ring(open_page, offset, edge):
    page, _ = open_page(width=1280, height=900)
    mount(page)
    settle(page)
    region = "document.querySelector(\"#a [aria-label='Tabel: Alcool']\")"
    page.evaluate(f"(off) => {{ const r = {region}; window.scrollTo(0, r.getBoundingClientRect().top + scrollY - off); }}", offset)
    settle(page)
    page.evaluate(f"{region}.focus()")
    settle(page)
    top, bottom, inner = page.evaluate(f"(() => {{ const r = {region}.getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; }})()")
    assert top >= FOCUS_RING_PX and bottom <= inner - FOCUS_RING_PX, (edge, top, bottom, inner)  # înainte: top −0,9 px, bottom 901 px din 900


# ---------- memorie: tabelele înlocuite nu rămân reținute ----------

def test_tables_replaced_by_a_filter_or_show_more_are_released_by_the_component(browser, tmp_path, data):  # noqa: F811
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        page.goto(write_harness(tmp_path, data).as_uri())
        cdp = context.new_cdp_session(page)
        mount(page, "hostile")
        settle(page)
        page.evaluate("window.__old = [new WeakRef(document.querySelector(\"#a [data-ed-block='big'] .ed-tbl-wrap\"))]")
        page.click("#a [data-ed-block='big'] .ed-more")  # „Arată încă” înlocuiește tabelul
        page.evaluate("window.__old.push(new WeakRef(document.querySelector(\"#a [data-ed-block='big'] .ed-tbl-wrap\")))")
        page.click("#a [data-ed-block='big'] .ed-chip >> nth=1")  # filtrul îl înlocuiește iar
        for _ in range(4):
            cdp.send("HeapProfiler.collectGarbage")
            page.wait_for_timeout(60)
        assert page.evaluate("window.__old.map((ref) => ref.deref() === undefined)") == [True, True]
    finally:
        context.close()


# ---------- liste lungi: paginare ----------

def long_dataset(page, count=250):
    """Pune în DATA.long un set valid cu `count` rânduri în fiecare listă (nume inventate; sumele plătite egale cu cele de listă)."""
    page.evaluate("""(n) => { const d = JSON.parse(JSON.stringify(DATA.small));
      d.by_seller = Array.from({ length: n }, (_, i) => ({ seller: 'Vanzator ' + i, units: 1, bani: 250000 - i * 1000, paid_bani: 250000 - i * 1000 }));
      d.top_products = Array.from({ length: n }, (_, i) => ({ name: 'Produs ' + i, category: 'Diverse', units: 1, bani: 1000 + i, paid_bani: 1000 + i,
        order_id: String(100000000 + i), order_count: 1 }));
      const excluded = (i) => ({ order_id: 'X' + i, date: '2026-01-01', seller: 'Vanzator', names: ['Asigurare ' + i], products_bani: 100, paid_bani: 100, status_text: 'Plata acceptata' });
      d.paid_only = Array.from({ length: n }, (_, i) => excluded(i)); d.in_progress = [];
      d.highlights.Alcool.items = Array.from({ length: n }, (_, i) => ({ order_id: 'H' + i, date: '2026-01-01', name: 'Whisky ' + i, qty: 1, amount_bani: 100,
        paid_amount_bani: 100, state: 'kept' }));
      d.highlights.Alcool.items_total = n; DATA.long = d; }""", count)


def test_every_long_list_draws_a_page_at_a_time_with_show_more(open_page):
    page, probe = open_page()
    long_dataset(page)
    mount(page, "long")
    settle(page)
    kinds = {
        "top": "[data-ed-block='top'] tbody tr", "excluded": "[data-ed-block='excluded'] tbody tr",
        "sellers": "[data-ed-block='sellers'] .ed-bar-row", "highlights": "[aria-label='Tabel: Alcool'] tbody tr",
    }
    for name, selector in kinds.items():
        assert page.locator(f"#a {selector}").count() == 100, name
        more = page.locator(f"#a [data-ed-block='{name}'] .ed-more")
        assert sound(more.first.inner_text()) == "Arată încă 100 (150 rămase)", name
        more.first.click()
        assert page.locator(f"#a {selector}").count() == 200, name
        assert page.evaluate("document.activeElement.className") == "ed-more"  # focusul rămâne pe buton, la locul lui
        assert sound(page.inner_text("#a [role='status']")) == "Se afișează 200 de rânduri din 250.", name
        page.locator(f"#a [data-ed-block='{name}'] .ed-more").first.click()
        assert page.locator(f"#a {selector}").count() == 250, name
        assert page.locator(f"#a [data-ed-block='{name}'] .ed-more").count() == 0, name
    assert_clean(probe)


def test_show_more_keeps_the_bar_scale_and_a_single_tab_stop(open_page):
    page, _ = open_page()
    long_dataset(page)
    mount(page, "long")
    fill_width = lambda i: page.eval_on_selector(f"#a [data-ed-block='sellers'] .ed-bar-row >> nth={i}", "e => e.querySelector('.ed-bar-fill').style.width")
    assert fill_width(0) == "100%" and fill_width(99) == "60.4%"  # (250000 − 99·1000) / 250000: scara e a tuturor rândurilor
    page.click("#a [data-ed-block='sellers'] .ed-more")
    assert fill_width(0) == "100%" and fill_width(99) == "60.4%" and fill_width(100) == "60%"
    assert page.locator("#a [data-ed-block='sellers'] .ed-bar-row[tabindex='0']").count() == 1


def test_short_lists_have_no_extra_wrapper_or_button(open_page):
    page, _ = open_page()
    mount(page, "demo")
    assert page.locator("#a [data-ed-block='sellers'] .ed-more, #a [data-ed-block='top'] .ed-more").count() == 0
    assert page.locator("#a [data-ed-block='sellers'] .ed-card > .ed-bars").count() == 1  # aceeași structură ca înainte


# ---------- date inexistente ----------

def test_dates_that_do_not_exist_stay_as_the_original_text_while_real_ones_are_formatted(open_page):
    page, _ = open_page()
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.small));
      d.big.items[0].date = '2026-02-31'; d.big.items[1].date = '0099-01-01'; d.big.items[2].date = '2024-02-29';
      d.meta.first_order = '0001-01-01'; d.meta.last_order = '2023-02-29'; d.meta.generated_at = '2026-02-31 25:61'; DATA.dates = d; }""")
    mount(page, "dates")
    # prima parte a celulei „Data și comanda” e data; linkul comenzii vine după ea (celula nu mai conține doar data)
    cells = page.eval_on_selector_all("#a [data-ed-block='big'] tbody td[data-label='Data și comanda']", "els => els.map((e) => e.firstChild.textContent).sort()")
    assert cells == sorted(["2026-02-31", "0099-01-01", "29.02.2024"])  # înainte: 03.03.2026, 01.01.1999 (rescrise în tăcere)
    assert page.inner_text("#a .ed-meta-line") == "Comenzi din 0001-01-01 până în 2023-02-29 · generat 2026-02-31 25:61"


def test_valid_leap_day_and_year_end_are_formatted(open_page):
    page, _ = open_page()
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.small)); d.meta.first_order = '2024-02-29'; d.meta.last_order = '2025-12-31'; d.meta.generated_at = '2026-01-01 00:00'; DATA.dates = d; }""")
    mount(page, "dates")
    assert page.inner_text("#a .ed-meta-line") == "Comenzi din 29.02.2024 până în 31.12.2025 · generat 01.01.2026, 00:00"


# ---------- rădăcină scoasă din document fără unmount() ----------

def test_a_root_removed_from_the_document_without_unmount_releases_its_listeners_and_observers(open_page):
    page, probe = open_page(init_script=INSTRUMENT_LISTENERS)
    baseline = page.evaluate("[window.__net, window.__roActive]")
    mount(page)
    settle(page)
    assert page.evaluate("[window.__net, window.__roActive]") != baseline
    page.evaluate("document.getElementById('a').remove()")  # gazda uită unmount()
    page.evaluate("window.dispatchEvent(new Event('scroll'))")
    settle(page)
    assert page.evaluate("[window.__net, window.__roActive]") == baseline
    assert page.evaluate("H.a.root.children.length") == 0  # și a golit nodurile detașate
    assert_clean(probe)


def test_mounting_into_a_root_that_is_attached_later_keeps_working(open_page):
    page, probe = open_page()
    page.evaluate("""() => { window.late = document.createElement('div'); EmagDashboard.mount(window.late, DATA.small, {}); }""")
    page.wait_for_timeout(150)  # câteva cadre cu rădăcina încă detașată: nu are voie să se autodistrugă
    page.evaluate("document.body.appendChild(window.late)")
    page.evaluate("window.dispatchEvent(new Event('scroll'))")
    settle(page)
    assert page.eval_on_selector_all("body > div:last-child [data-ed-block]", "els => els.map((e) => e.dataset.edBlock)") == BLOCKS
    assert_clean(probe)


# ---------- texte: adevărul pe care îl poate susține programul ----------

def test_no_warning_message_claims_only_what_the_internal_checks_prove(open_page):
    page, _ = open_page()
    mount(page, "empty")
    assert "Niciun avertisment: verificările interne de sume au trecut." in page.inner_text("#a [data-ed-block='control']")
    assert "toate sumele se leagă" not in page.inner_text("#a")


def test_top_products_block_is_named_for_what_it_sorts_by(open_page):
    page, _ = open_page()
    mount(page)
    assert page.get_attribute("#a [data-ed-block='top']", "data-ed-title") == "Produse cu cea mai mare valoare păstrată"
    assert page.inner_text("#a [data-ed-block='top'] h2") == "Produse cu cea mai mare valoare păstrată"
    assert "Cele mai scumpe" not in page.inner_text("#a")
    assert page.get_attribute("#a [data-ed-block='top'] .ed-tbl-wrap", "aria-label") == "Tabel: Produse cu cea mai mare valoare păstrată"


def test_method_text_gives_the_rule_as_fact_and_the_emag_behaviour_as_an_observation(open_page):
    # Regula programului e sigură; ce face eMAG pe pagini nu poate fi dovedit din depozit (testele folosesc pagini inventate),
    # deci textul îl dă ca observație de la scrierea programului, nu ca fapt.
    page, _ = open_page()
    mount(page)
    text = sound(page.inner_text("#a [data-ed-block='method']"))
    rule = text.index("Un retur finalizat se numără ca returnat, nu ca anulare.")
    observed = text.index("Pe paginile observate la scrierea programului")
    assert rule < observed < text.index("factură storno") < text.index("marchează returul „Livrare anulată”")


def test_generated_report_theme_button_is_a_40px_target_even_with_a_mouse(browser, tmp_path, data):  # noqa: F811
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, data["small"])
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        page.goto(out.as_uri())
        settle(page)
        assert page.eval_on_selector("#rp-theme", "e => e.getBoundingClientRect().height") >= 39.9  # înainte: 32 px
    finally:
        context.close()
