"""Teste ale componentei dashboard într-un browser real (Edge sau Chrome instalat, prin Playwright).

Paginile sunt în tmp_path și se deschid din file://, ca la utilizator. Se verifică: contractul
(validate/mount/unmount), toate blocurile, stări goale și de eroare, date ostile, două instanțe,
curățenia la unmount, tastatura, formatarea românească, teme, mișcare redusă, layout fără
scroll orizontal și raportul generat de Python. Dacă niciun browser nu pornește, tot fișierul se sare.
"""

import json
import re

import pytest

from emag_spend import settings
from emag_spend.report_html import write_report
from tests import dashboard_samples as samples
from tests.dashboard_browser_support import attach_probe, launch_browser, write_harness

sync_api = pytest.importorskip("playwright.sync_api")

BLOCKS = ["hero", "funnel", "tiles", "categories", "highlights", "years", "big", "top", "preturi", "sellers", "excluded", "control", "method"]
DEMO_BANNER = "Date de demonstrație, inventate. Nu sunt comenzile nimănui."
NBSP = " "
DARK_PAGE_RGB = "rgb(13, 13, 13)"
LIGHT_PAGE_RGB = "rgb(249, 249, 247)"
SETTLE = "new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 60))))"
INSTRUMENT_LISTENERS = """
(() => {
  window.__net = 0; window.__roActive = 0;
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function (t, f, o) { if (this === window || this === document) window.__net++; return add.call(this, t, f, o); };
  EventTarget.prototype.removeEventListener = function (t, f, o) { if (this === window || this === document) window.__net--; return rem.call(this, t, f, o); };
  const RO = window.ResizeObserver;
  window.ResizeObserver = class extends RO {
    constructor(cb) { super(cb); this.__off = false; window.__roActive++; }
    disconnect() { if (!this.__off) { this.__off = true; window.__roActive--; } super.disconnect(); }
  };
})();
"""


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def browser():
    """Un singur browser pentru tot fișierul; se sare dacă nu pornește (nu strică suita pe alt PC)."""
    with sync_api.sync_playwright() as playwright:
        try:
            instance = launch_browser(playwright)
        except RuntimeError as exc:
            pytest.skip(str(exc))
        yield instance
        instance.close()


@pytest.fixture(scope="module")
def data():
    return {"demo": samples.demo_summary(), "small": samples.small_summary(), "empty": samples.empty_summary(), "hostile": samples.hostile_summary()}


@pytest.fixture
def open_page(browser, tmp_path, data):
    """Fabrică de pagini: scrie harness-ul, deschide pagina și întoarce (pagină, sondă)."""
    contexts = []

    def _open(*, width=1280, height=900, scheme="light", motion="no-preference", init_script=None, extra_data=None, touch=False, **harness):
        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion=motion,
                                      has_touch=touch, is_mobile=touch)
        contexts.append(context)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        probe = attach_probe(page)
        page.goto(write_harness(tmp_path, {**data, **(extra_data or {})}, **harness).as_uri())
        return page, probe

    yield _open
    for context in contexts:
        context.close()


def mount(page, dataset="demo", root="a", options="{ demo: true }"):
    """Montează `DATA[dataset]` în #root și întoarce {ok, errors} din rezultatul mount."""
    return page.evaluate(
        f"(() => {{ window.H = window.H || {{}}; const r = EmagDashboard.mount(document.getElementById('{root}'), DATA['{dataset}'], {options});"
        f" window.H['{root}'] = r; return {{ ok: r.ok, errors: r.errors }}; }})()"
    )


def settle(page):
    """Așteaptă două cadre și o clipă: desenarea, observatorul de dimensiuni și rAF s-au terminat."""
    page.evaluate(SETTLE)


def blocks(page, root="a"):
    """Numele blocurilor `data-ed-block` din #root, în ordinea din pagină."""
    return page.eval_on_selector_all(f"#{root} [data-ed-block]", "els => els.map(e => e.dataset.edBlock)")


def money(bani):
    """Același format ca în raport, calculat independent în Python: 313001 -> '3.130,01'."""
    whole, frac = divmod(abs(bani), 100)
    return ("-" if bani < 0 else "") + f"{whole:,}".replace(",", ".") + f",{frac:02d}"


def assert_clean(probe):
    """Pagina nu are voie să fi scris erori în consolă, să fi aruncat excepții sau să fi cerut ceva din rețea."""
    assert probe.problems() == {"console": [], "pageerror": [], "network": []}


# ---------- contract și blocuri ----------

def test_demo_report_has_every_block_in_order_without_errors_or_network(open_page):
    page, probe = open_page()
    assert mount(page)["ok"] is True
    settle(page)
    assert blocks(page) == BLOCKS
    titles = page.eval_on_selector_all("#a [data-ed-block]", "els => els.map(e => e.dataset.edTitle)")
    assert all(t and t.strip() for t in titles)
    assert page.eval_on_selector("#a", "e => e.classList.contains('emag-dash') && e.dataset.edState === 'ready'")
    assert_clean(probe)


def test_public_contract_surface(open_page):
    page, _ = open_page()
    shape = page.evaluate("""() => {
      const r = EmagDashboard.mount(document.getElementById('a'), DATA.small);
      return { version: EmagDashboard.version, keys: Object.keys(EmagDashboard).sort(), unmount: typeof r.unmount,
               sameRoot: r.root === document.getElementById('a'), validate: typeof EmagDashboard.validate(DATA.small).errors };
    }""")
    assert shape == {"version": "1", "keys": ["mount", "validate", "version"], "unmount": "function", "sameRoot": True, "validate": "object"}


def test_mount_requires_an_element_as_root(open_page):
    page, _ = open_page()
    names = page.evaluate("""() => [null, {}, 'a', document.createTextNode('x')].map((bad) => {
      try { EmagDashboard.mount(bad, DATA.small); return 'fără eroare'; } catch (e) { return e.name; }
    })""")
    assert names == ["TypeError"] * 4


def test_demo_banner_only_when_requested(open_page):
    page, _ = open_page()
    mount(page, "small", "a", "{ demo: true }")
    mount(page, "small", "b", "{}")
    assert page.inner_text("#a .ed-banner[role='note']") == DEMO_BANNER
    assert page.locator("#b .ed-banner").count() == 0
    assert page.eval_on_selector("#a", "e => e.firstElementChild.className") == "ed-banner"  # în vârful componentei


def test_no_ids_inside_the_component_so_two_instances_never_collide(open_page):
    page, _ = open_page()
    mount(page, "demo", "a")
    mount(page, "small", "b")
    ids = page.evaluate("[...document.querySelectorAll('#a [id], #b [id]')].map((e) => e.id)")
    assert ids == []


def test_headings_never_skip_a_level_and_headingLevel_shifts_them(open_page):
    page, _ = open_page()
    mount(page, "demo", "a")
    mount(page, "demo", "b", "{ headingLevel: 3 }")
    levels = lambda root: page.evaluate(f"[...document.querySelectorAll('#{root} h1,#{root} h2,#{root} h3,#{root} h4,#{root} h5,#{root} h6')].map((h) => +h.tagName[1])")
    a, b = levels("a"), levels("b")
    assert a[0] == 2 and 3 in a and max(a) == 3
    assert b[0] == 3 and 4 in b and max(b) == 4
    for sequence in (a, b):
        assert all(nxt <= prev + 1 for prev, nxt in zip(sequence, sequence[1:]))


def test_highlight_block_title_comes_from_the_data_not_from_the_code(open_page, data):
    page, _ = open_page()
    mount(page, "demo")
    assert page.get_attribute("#a [data-ed-block='highlights']", "data-ed-title") == "Alcool și televizoare"
    renamed = json.loads(json.dumps(data["small"]))
    renamed["highlights"] = {"Cafea": renamed["highlights"]["Alcool"]}
    page.evaluate("(d) => { DATA.renamed = d; }", renamed)
    mount(page, "renamed", "b")
    assert page.get_attribute("#b [data-ed-block='highlights']", "data-ed-title") == "Cafea"


# ---------- validate ----------

def js_validate(page, mutation, dataset="small"):
    """Aplică `mutation` (cod JS pe `d`) peste o copie a setului de date și întoarce rezultatul validate."""
    return page.evaluate(f"(() => {{ const d = JSON.parse(JSON.stringify(DATA['{dataset}'])); {mutation}; return EmagDashboard.validate(d); }})()")


def test_validate_accepts_real_data_and_tolerates_unknown_keys(open_page):
    page, _ = open_page()
    assert page.evaluate("EmagDashboard.validate(DATA.demo)") == {"ok": True, "errors": []}
    result = js_validate(page, "d.versiune_viitoare = { x: 1 }; d.funnel.cheie_noua = 5; d.by_category[0].extra = 'x'; d.big.items[0].camp_nou = [1]")
    assert result == {"ok": True, "errors": []}


def test_validate_accepts_missing_optional_keys_and_mount_still_draws_everything(open_page):
    page, probe = open_page()
    mutation = ("delete d.highlights; delete d.paid_only; delete d.in_progress; delete d.uncategorized; delete d.uncategorized_count;"
                " delete d.reconciliation.refund_modes; delete d.reconciliation.refunds_without_amount; delete d.returns.unmatched_refund_bani")
    page.evaluate(f"(() => {{ const d = JSON.parse(JSON.stringify(DATA.small)); {mutation}; DATA.partial = d; }})()")
    assert page.evaluate("EmagDashboard.validate(DATA.partial)")["ok"] is True
    assert mount(page, "partial")["ok"] is True
    assert blocks(page) == BLOCKS
    assert_clean(probe)


@pytest.mark.parametrize("mutation, must_contain", [
    ("delete d.funnel", ["Fișierul nu pare să fie analiza.json generată de program: lipsește cheia funnel", "iesiri"]),
    ("delete d.funnel; delete d.meta", ["lipsesc cheile", "funnel", "meta"]),
    ("d.funnel.kept_bani = 'abc'", ["funnel.kept_bani trebuie să fie un număr întreg", "text („abc”)"]),
    ("d.by_category[0].kept_bani = 1.5", ["by_category[0].kept_bani", "un număr zecimal (1.5)"]),
    ("d.by_category = {}", ["by_category trebuie să fie o listă", "un obiect"]),
    ("d.meta = null", ["meta trebuie să fie un obiect", "null"]),
    ("delete d.big.items", ["big:", "Lipsește cheia items"]),
    ("d.by_year_category.years.push('1999')", ["1999", "by_year_category.years"]),
    ("d.warnings = [1]", ["warnings[0] trebuie să fie text"]),
])
def test_validate_rejects_with_concrete_romanian_messages(open_page, mutation, must_contain):
    page, _ = open_page()
    result = js_validate(page, mutation)
    assert result["ok"] is False
    joined = " | ".join(result["errors"])
    for needle in must_contain:
        assert needle in joined, (needle, joined)


@pytest.mark.parametrize("value, needle", [
    ("null", "Nu am primit niciun conținut"), ("undefined", "Nu am primit niciun conținut"), ("[]", "o listă"),
    ("'text'", "text („text”)"), ("42", "un număr întreg"), ("true", "adevărat sau fals"),
])
def test_validate_rejects_non_objects_and_says_what_to_upload(open_page, value, needle):
    page, _ = open_page()
    result = page.evaluate(f"EmagDashboard.validate({value})")
    assert result["ok"] is False and len(result["errors"]) == 1
    assert needle in result["errors"][0] and "analiza.json" in result["errors"][0]


def test_validate_caps_the_number_of_messages(open_page):
    page, _ = open_page()
    result = js_validate(page, "d.by_category.forEach((c) => { c.kept_bani = 'x'; c.name = 5; }); d.top_products.forEach((c) => { c.bani = 'x'; })", "demo")
    assert result["ok"] is False and len(result["errors"]) <= 9
    assert "… și încă" in result["errors"][-1]


def test_validate_never_throws_on_exotic_input(open_page):
    page, _ = open_page()
    outcomes = page.evaluate("""() => {
      const circular = { a: 1 }; circular.self = circular;
      const hostileGetter = {}; Object.defineProperty(hostileGetter, 'funnel', { enumerable: true, get() { throw new Error('boom'); } });
      const proxy = new Proxy({}, { get() { throw new Error('boom'); }, ownKeys() { throw new Error('boom'); }, has() { throw new Error('boom'); } });
      let deep = []; for (let i = 0; i < 5000; i++) deep = [deep];
      return [circular, hostileGetter, proxy, deep, Symbol('s'), 10n, () => 1, new Date(), /x/, NaN, Infinity, -0].map((v) => {
        try { const r = EmagDashboard.validate(v); return r.ok === false && Array.isArray(r.errors) && r.errors.length > 0; } catch (e) { return 'a aruncat: ' + e.message; }
      });
    }""")
    assert outcomes == [True] * 12


# ---------- stări: eroare, gol, ostil ----------

@pytest.mark.parametrize("bad", ["{}", "null", "[]", "'text'", "42", "{ funnel: 1, meta: 'x' }", "{ __proto__: { funnel: 1 } }"])
def test_mount_draws_a_clear_error_state_for_invalid_data_and_never_throws(open_page, bad):
    page, probe = open_page()
    outcome = page.evaluate(f"""() => {{
      const root = document.getElementById('a');
      try {{ const r = EmagDashboard.mount(root, {bad}); return {{ ok: r.ok, errors: r.errors, thrown: null }}; }}
      catch (e) {{ return {{ thrown: e.message }}; }}
    }}""")
    assert outcome["thrown"] is None and outcome["ok"] is False and outcome["errors"]
    assert page.eval_on_selector("#a", "e => e.dataset.edState") == "error"
    alert = page.locator("#a .ed-error[role='alert']")
    assert alert.count() == 1
    text = alert.inner_text()
    assert "Nu pot afișa raportul" in text and "analiza.json" in text
    assert blocks(page) == []
    assert_clean(probe)


def test_empty_account_draws_every_block_with_decent_empty_states(open_page):
    page, probe = open_page()
    assert mount(page, "empty")["ok"] is True
    settle(page)
    assert blocks(page) == BLOCKS
    assert page.inner_text("#a .ed-big") == "0" and page.inner_text("#a .ed-cents") == f",00{NBSP}Lei"
    text = page.inner_text("#a")
    for expected in ("Nu există comenzi de afișat.", "Nicio categorie evidențiată", "Nu există date pe ani.", "Niciun produs nu depășește pragul.",
                     "Nu există vânzători de afișat.", "Nimic de raportat aici.", "Niciun avertisment"):
        assert expected in text, expected
    assert page.locator("#a .ed-toggle").count() == 1  # doar „Pe categorii”: la „Pe ani” nu e nimic de comutat fără ani
    assert_clean(probe)


def test_hostile_text_stays_inert_and_visible_as_plain_text(open_page):
    page, probe = open_page(width=390, height=844)
    assert mount(page, "hostile")["ok"] is True
    settle(page)
    inert = page.evaluate("""() => {
      const root = document.getElementById('a');
      return { pwned: window.__pwned === undefined,
               injected: root.querySelectorAll('script, img, iframe, object, embed, style, link, base').length,
               handlers: [...root.querySelectorAll('*')].filter((e) => e.getAttributeNames().some((n) => n.startsWith('on'))).length,
               overflow: document.documentElement.scrollWidth <= innerWidth };
    }""")
    assert inert == {"pwned": True, "injected": 0, "handlers": 0, "overflow": True}
    text = page.inner_text("#a")
    assert samples.HOSTILE_ALERT in text and samples.HOSTILE_IMG in text and "x" * 200 in text
    assert page.locator("#a [data-ed-block='highlights']").count() == 1
    assert_clean(probe)


def test_dangerous_key_names_in_valid_data_do_not_break_drawing(open_page):
    # JSON.parse creează „__proto__” ca proprietate proprie; defineProperty face la fel aici
    page, probe = open_page()
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.small));
      d.by_year_category.series.push('__proto__');
      d.by_year_category.years.forEach((y) => Object.defineProperty(d.by_year_category.values[y], '__proto__', { value: 100, enumerable: true, configurable: true, writable: true }));
      DATA.proto = d; }""")
    assert page.evaluate("EmagDashboard.validate(DATA.proto).ok") is True
    result = mount(page, "proto")
    assert result["ok"] is True
    assert page.eval_on_selector("#a", "e => e.dataset.edState") == "ready"
    assert page.locator("#a svg.ed-chart rect.ed-hit").count() == len(page.evaluate("DATA.proto.by_year_category.years"))
    assert_clean(probe)


# ---------- două instanțe, unmount ----------

def test_two_instances_in_one_page_do_not_interfere(open_page, data):
    page, probe = open_page()
    mount(page, "demo", "a")
    mount(page, "small", "b", "{}")
    settle(page)
    assert blocks(page, "a") == BLOCKS and blocks(page, "b") == BLOCKS
    hero = lambda root: (page.inner_text(f"#{root} .ed-big"), page.inner_text(f"#{root} .ed-cents"))
    spent = data["demo"]["paid"]["spent_bani"]  # cifra mare = banii plătiți efectiv (cheia `paid`)
    assert hero("a") == (money(spent).split(",")[0], f",{spent % 100:02d}{NBSP}Lei")
    assert hero("b") == ("3.080", f",01{NBSP}Lei")  # scenariul mic: 3.130,01 la preț de listă, minus voucherul de 50,00
    page.click("#a [data-ed-block='categories'] .ed-toggle")
    assert page.get_attribute("#a [data-ed-block='categories'] .ed-toggle", "aria-pressed") == "true"
    assert page.get_attribute("#b [data-ed-block='categories'] .ed-toggle", "aria-pressed") == "false"
    assert page.locator("#b [data-ed-block='categories'] table").count() == 0
    seller_row = page.locator("#a [data-ed-block='sellers'] .ed-bar-row >> nth=0")
    seller_row.scroll_into_view_if_needed()
    settle(page)  # „scroll” sosește după un cadru și ar închide tooltip-ul
    seller_row.hover()
    assert page.is_visible("#a .ed-tip") and not page.is_visible("#b .ed-tip")
    page.click("#a [data-ed-block='big'] .ed-chip >> nth=1")
    assert page.get_attribute("#b [data-ed-block='big'] .ed-chip >> nth=0", "aria-pressed") == "true"
    assert_clean(probe)


def test_unmount_one_instance_leaves_the_other_working(open_page):
    page, probe = open_page()
    mount(page, "demo", "a")
    mount(page, "small", "b")
    page.evaluate("H.a.unmount()")
    assert page.eval_on_selector("#a", "e => e.children.length") == 0
    assert blocks(page, "b") == BLOCKS
    page.click("#b [data-ed-block='years'] .ed-toggle")
    assert page.get_attribute("#b [data-ed-block='years'] .ed-toggle", "aria-pressed") == "true"
    assert_clean(probe)


def test_unmount_removes_nodes_classes_attributes_listeners_and_observers(open_page):
    page, probe = open_page(init_script=INSTRUMENT_LISTENERS)
    page.evaluate("document.getElementById('a').className = 'clasa-gazdei'")
    baseline = page.evaluate("[window.__net, window.__roActive]")
    mount(page, "demo")
    settle(page)
    mounted = page.evaluate("[window.__net, window.__roActive]")
    assert mounted[0] > baseline[0] and mounted[1] == 1
    page.evaluate("H.a.unmount(); H.a.unmount()")  # al doilea apel e inofensiv
    assert page.evaluate("[window.__net, window.__roActive]") == baseline
    state = page.evaluate("""() => { const r = document.getElementById('a'); return { kids: r.children.length, text: r.textContent, attrs: r.getAttributeNames().sort(), cls: r.className }; }""")
    assert state == {"kids": 0, "text": "", "attrs": ["class", "id"], "cls": "clasa-gazdei"}
    page.wait_for_timeout(150)  # niciun rAF sau observator rămas nu mai are voie să scrie ceva
    assert_clean(probe)


def test_unmounted_root_without_a_host_class_goes_back_to_a_bare_element(open_page):
    page, _ = open_page(init_script=INSTRUMENT_LISTENERS)
    mount(page, "small")
    page.evaluate("H.a.unmount()")
    assert page.evaluate("document.getElementById('a').getAttributeNames()") == ["id"]


def test_mounting_twice_on_the_same_root_replaces_the_first_without_leaks(open_page):
    page, probe = open_page(init_script=INSTRUMENT_LISTENERS)
    baseline = page.evaluate("window.__net")
    mount(page, "small")
    once = page.evaluate("[window.__net, window.__roActive]")
    mount(page, "demo")
    settle(page)
    assert page.evaluate("[window.__net, window.__roActive]") == once
    assert page.locator("#a .ed-wrap").count() == 1 and page.locator("#a .ed-banner").count() == 1
    assert once[0] > baseline
    assert_clean(probe)


# ---------- tastatură, tooltip, comutatoare, filtre ----------

def test_table_toggle_works_from_the_keyboard_and_keeps_one_label(open_page, data):
    page, probe = open_page()
    mount(page)
    toggle = "#a [data-ed-block='categories'] .ed-toggle"
    page.focus(toggle)
    page.keyboard.press("Enter")
    assert page.get_attribute(toggle, "aria-pressed") == "true" and page.inner_text(toggle) == "Vezi tabel"
    assert page.is_visible("#a [data-ed-block='categories'] table") and not page.is_visible("#a [data-ed-block='categories'] .ed-bars")
    rows = page.locator("#a [data-ed-block='categories'] tbody tr").count()
    extra = [r for r in data["demo"]["paid"]["extra_rows"] if r["bani"]]  # „Transport și taxe”… au rândul lor
    assert rows == len(data["demo"]["by_category"]) + len(extra)
    page.keyboard.press("Space")
    assert page.get_attribute(toggle, "aria-pressed") == "false" and page.is_visible("#a [data-ed-block='categories'] .ed-bars")
    assert "Graficul e afișat" in page.inner_text("#a [role='status']")
    assert_clean(probe)


def test_year_table_alternative_matches_the_data(open_page, data):
    page, _ = open_page()
    mount(page)
    page.click("#a [data-ed-block='years'] .ed-toggle")
    assert page.locator("#a [data-ed-block='years'] tbody tr").count() == len(data["demo"]["by_year"])
    assert not page.is_visible("#a [data-ed-block='years'] svg.ed-chart")
    first_year = data["demo"]["by_year"][0]
    assert page.inner_text("#a [data-ed-block='years'] tbody tr >> nth=0 >> td >> nth=0") == first_year["year"]
    page.click("#a [data-ed-block='years'] .ed-toggle")
    assert page.is_visible("#a [data-ed-block='years'] svg.ed-chart")


def test_tooltip_follows_keyboard_focus_and_escape_closes_it(open_page, data):
    page, probe = open_page()
    mount(page)
    page.focus("#a [data-ed-block='categories'] .ed-toggle")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "ed-bar-row"
    assert page.is_visible("#a .ed-tip[role='tooltip']")
    first = next(c for c in data["demo"]["by_category"] if c["kept_bani"] > 0)
    assert page.inner_text("#a .ed-tip-title") == first["name"]
    inside = page.evaluate("""() => { const t = document.querySelector('#a .ed-tip').getBoundingClientRect();
      return t.left >= 0 && t.top >= 0 && t.right <= innerWidth && t.bottom <= innerHeight; }""")
    assert inside
    page.keyboard.press("Escape")
    assert not page.is_visible("#a .ed-tip")
    page.keyboard.press("ArrowDown")  # lista e UN punct de oprire Tab: săgețile trec de la un rând la altul
    assert page.is_visible("#a .ed-tip")
    page.evaluate("document.activeElement.blur()")
    assert not page.is_visible("#a .ed-tip")
    assert_clean(probe)


def test_tooltip_survives_the_scroll_that_keyboard_focus_causes(open_page):
    # Tab spre un element din afara ecranului derulează pagina; „scroll” nu are voie să închidă tooltip-ul focusului
    page, _ = open_page(height=500)
    mount(page)
    assert page.evaluate("document.querySelector('#a svg.ed-chart .ed-hit').getBoundingClientRect().top > innerHeight")
    page.focus("#a svg.ed-chart .ed-hit >> nth=1")
    settle(page)
    assert page.evaluate("scrollY") > 0
    assert page.is_visible("#a .ed-tip")
    inside = page.evaluate("""() => { const t = document.querySelector('#a .ed-tip').getBoundingClientRect(), a = document.activeElement.getBoundingClientRect();
      return t.top >= 0 && t.bottom <= innerHeight && Math.abs(t.left - (a.left + 12)) < 40; }""")
    assert inside, "tooltip-ul trebuie să rămână lângă elementul focusat, în ecran"


FOCUSED_YEAR = """() => { const e = document.activeElement;
  return e.isConnected && e.matches('#a svg.ed-chart .ed-hit') ? e.getAttribute('aria-label').split(':')[0] : null; }"""


def test_column_focused_before_the_first_frame_keeps_focus_and_tooltip_after_the_redraw(open_page, data):
    # Primul cadru după mount redesenează graficul la lățimea reală (la mount containerul nu era încă în pagină).
    # Pe macOS, page.focus a ajuns înaintea acelui cadru: coloana focusată era înlocuită, blur închidea tooltip-ul și
    # focusul cădea pe <body>. Aici mount și focus sunt în același task: niciun cadru între ele, deci fără noroc la cronometru.
    year = data["demo"]["by_year_category"]["years"][1]
    page, probe = open_page(height=500)
    page.evaluate("""() => { EmagDashboard.mount(document.getElementById('a'), DATA.demo, { demo: true });
      window.__old = document.querySelectorAll('#a svg.ed-chart .ed-hit')[1]; __old.focus(); }""")
    settle(page)
    assert page.evaluate("!__old.isConnected"), "primul cadru trebuie să fi înlocuit coloana (altfel testul nu verifică nimic)"
    assert page.evaluate("scrollY") > 0 and page.evaluate(FOCUSED_YEAR) == year
    assert page.is_visible("#a .ed-tip") and page.inner_text("#a .ed-tip-title") == year
    assert_clean(probe)


def test_chart_redrawn_for_a_new_width_keeps_keyboard_focus_and_respects_escape(open_page, data):
    years = data["demo"]["by_year_category"]["years"]
    page, probe = open_page(height=500)
    mount(page)
    settle(page)
    page.focus("#a svg.ed-chart .ed-hit >> nth=1")
    page.keyboard.press("Tab")
    settle(page)
    page.evaluate("window.__old = document.activeElement")
    page.set_viewport_size({"width": 1000, "height": 500})  # fereastră micșorată: graficul se redesenează pe noua lățime
    settle(page)
    assert page.evaluate("!__old.isConnected"), "graficul trebuie să se fi redesenat (altfel testul nu verifică nimic)"
    assert page.evaluate(FOCUSED_YEAR) == years[2] and page.evaluate("document.activeElement.matches(':focus-visible')")
    assert page.is_visible("#a .ed-tip") and page.inner_text("#a .ed-tip-title") == years[2]
    page.keyboard.press("Tab")  # Tab continuă de la anul curent, nu de la prima coloană
    assert page.evaluate(FOCUSED_YEAR) == years[3]
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1280, "height": 500})
    settle(page)
    assert page.evaluate(FOCUSED_YEAR) == years[3] and not page.is_visible("#a .ed-tip")  # redesenarea nu redeschide ce a închis Escape
    assert_clean(probe)


def test_pointer_tooltip_closes_when_the_page_scrolls(open_page):
    page, _ = open_page(height=500)
    mount(page)
    row = page.locator("#a .ed-bar-row >> nth=0")
    row.scroll_into_view_if_needed()
    settle(page)
    row.hover()
    assert page.is_visible("#a .ed-tip")
    page.evaluate("scrollBy(0, 300)")  # derulare programatică: fără mișcare sintetică de mouse care să-l redeschidă
    settle(page)
    assert not page.is_visible("#a .ed-tip")


def test_funnel_segments_and_chart_columns_are_focusable_with_tooltips(open_page, data):
    page, _ = open_page()
    mount(page)
    page.focus("#a .ed-funnel-seg >> nth=0")
    assert "Plătit efectiv" in page.inner_text("#a .ed-tip-title") and "Valoare" in page.inner_text("#a .ed-tip")
    page.focus("#a svg.ed-chart .ed-hit >> nth=0")
    assert page.inner_text("#a .ed-tip-title") == data["demo"]["by_year_category"]["years"][0]
    label = page.get_attribute("#a svg.ed-chart .ed-hit >> nth=0", "aria-label")
    assert label.startswith(data["demo"]["by_year_category"]["years"][0] + ": ") and "Lei" in label


def test_touch_tap_shows_the_tooltip_through_focus_and_tapping_elsewhere_closes_it(open_page):
    page, probe = open_page(width=390, height=844, touch=True)
    mount(page)
    row = page.locator("#a [data-ed-block='categories'] .ed-bar-row >> nth=1")
    row.scroll_into_view_if_needed()
    settle(page)
    row.tap()
    assert page.is_visible("#a .ed-tip") and page.inner_text("#a .ed-tip-title")
    page.locator("#a [data-ed-block='categories'] .ed-caption").tap()
    assert not page.is_visible("#a .ed-tip")
    assert_clean(probe)


def test_every_interactive_control_is_a_comfortable_touch_target(open_page):
    page, _ = open_page(width=390, height=844, touch=True)
    mount(page)
    small = page.evaluate("""() => [...document.querySelectorAll('#a button, #a summary')].filter((e) => e.offsetParent !== null)
      .map((e) => [e.textContent.trim().slice(0, 30), Math.round(e.getBoundingClientRect().height)]).filter(([, h]) => h < 40)""")
    assert small == []


def test_tooltip_stays_next_to_the_pointer_inside_a_transformed_ancestor(open_page):
    page, _ = open_page(wrapper_style="transform: translate(60px, 30px)")
    mount(page)
    row = page.locator("#a .ed-bar-row >> nth=2")
    row.scroll_into_view_if_needed()
    settle(page)  # evenimentul „scroll” sosește după un cadru și ar închide tooltip-ul deschis între timp
    box = row.bounding_box()
    x, y = box["x"] + 40, box["y"] + 6
    page.mouse.move(x, y)
    rect = page.evaluate("(() => { const r = document.querySelector('#a .ed-tip').getBoundingClientRect(); return [r.left, r.top]; })()")
    assert abs(rect[0] - (x + 14)) <= 2 and abs(rect[1] - (y + 14)) <= 2


def test_big_table_filters_update_rows_footer_and_live_region(open_page):
    page, probe = open_page()
    mount(page)
    chips = page.locator("#a [data-ed-block='big'] .ed-chip")
    labels = chips.all_inner_texts()
    assert labels[0].startswith("Toate (") and len(labels) >= 2
    total = int(re.search(r"\((\d+)\)", labels[0]).group(1))
    assert page.locator("#a [data-ed-block='big'] tbody tr").count() == total
    for index in range(1, len(labels)):
        wanted = int(re.search(r"\((\d+)\)", labels[index]).group(1))
        chips.nth(index).click()
        assert chips.nth(index).get_attribute("aria-pressed") == "true" and chips.nth(0).get_attribute("aria-pressed") == "false"
        assert page.locator("#a [data-ed-block='big'] tbody tr").count() == wanted
        assert f"Total ({wanted}" in page.inner_text("#a [data-ed-block='big'] tfoot")
        assert "Se afișează" in page.inner_text("#a [role='status']")
    assert_clean(probe)


def test_big_table_pages_through_hundreds_of_rows(open_page):
    page, probe = open_page()
    mount(page, "hostile")
    rows = lambda: page.locator("#a [data-ed-block='big'] tbody tr").count()
    assert rows() == 100
    expected = [200, 300, 400]
    for want in expected:
        page.click("#a [data-ed-block='big'] .ed-more")
        assert rows() == want
    assert page.locator("#a [data-ed-block='big'] .ed-more").count() == 0
    assert f"Total (400{NBSP}de{NBSP}linii)" in page.inner_text("#a [data-ed-block='big'] tfoot")
    assert f"Se afișează 400{NBSP}de{NBSP}linii din 400" in page.inner_text("#a [role='status']")
    assert_clean(probe)


def test_every_focusable_element_has_an_accessible_name(open_page):
    page, _ = open_page()
    mount(page)
    nameless = page.evaluate("""() => [...document.querySelectorAll('#a button, #a [tabindex], #a summary, #a a')]
      .filter((e) => !(e.getAttribute('aria-label') || e.textContent.trim())).map((e) => e.outerHTML.slice(0, 80))""")
    assert nameless == []


def test_scrollable_regions_are_keyboard_reachable_only_when_they_overflow(open_page):
    page, _ = open_page(width=390, height=844)
    mount(page)
    settle(page)
    report = page.evaluate("""() => [...document.querySelectorAll('#a .ed-tbl-wrap, #a .ed-chart-scroll')].filter((e) => e.offsetParent !== null).map((e) => ({
      overflow: e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1, tabindex: e.getAttribute('tabindex'),
      role: e.getAttribute('role'), named: !!e.getAttribute('aria-label') }))""")
    assert report and any(r["overflow"] for r in report)
    for r in report:
        assert r["role"] == "group" and r["named"]
        assert (r["tabindex"] == "0") == r["overflow"]


# ---------- formatare ----------

def test_numbers_dates_and_units_follow_romanian_conventions(open_page, data):
    page, _ = open_page()
    mount(page, "small", "a", "{}")
    kept = data["small"]["paid"]["spent_bani"]
    assert page.inner_text("#a .ed-big") == money(kept).split(",")[0]
    assert page.inner_text("#a .ed-cents") == f",{kept % 100:02d}{NBSP}Lei"
    period = page.inner_text("#a .ed-meta-line")
    assert period == "Comenzi din 10.03.2024 până în 01.04.2026 · generat 04.10.2026, 12:00"
    text = page.evaluate("document.getElementById('a').textContent")
    assert not re.search(r"\d Lei|\d buc|\d %", text), "între număr și unitate trebuie spațiu nedespărțitor"
    assert "..." not in text
    assert f"3.130,01{NBSP}Lei" in text and f"4.090,01{NBSP}Lei" in text


@pytest.mark.parametrize("script", [
    "delete window.Intl;",
    "const NF = Intl.NumberFormat, DF = Intl.DateTimeFormat; Intl.NumberFormat = function (l, o) { return new NF('en-US', o); };"
    " Intl.DateTimeFormat = function (l, o) { return new DF('en-US', o); };",
], ids=["fara-Intl", "Intl-fara-datele-ro-RO"])
def test_formatting_falls_back_to_manual_romanian_when_intl_is_unusable(open_page, script):
    page, probe = open_page(init_script=script)
    mount(page, "small", "a", "{}")
    assert page.inner_text("#a .ed-big") == "3.080" and page.inner_text("#a .ed-cents") == f",01{NBSP}Lei"
    assert page.inner_text("#a .ed-meta-line").endswith("generat 04.10.2026, 12:00")
    assert "10.03.2024" in page.inner_text("#a .ed-meta-line")
    assert_clean(probe)


def test_plural_agreement_in_romanian(open_page):
    page, _ = open_page()
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.small)); d.warnings = Array.from({ length: 25 }, (_, i) => 'w' + i); DATA.many = d;
      const one = JSON.parse(JSON.stringify(DATA.small)); one.warnings = ['unul']; DATA.one = one; }""")
    mount(page, "many", "b", "{}")
    mount(page, "one", "a", "{}")
    assert page.inner_text("#b [data-ed-block='control'] summary").replace(NBSP, " ") == "25 de avertismente de verificat"
    assert page.inner_text("#a [data-ed-block='control'] summary").replace(NBSP, " ") == "1 avertisment de verificat"


# ---------- teme, mișcare, layout ----------

@pytest.mark.parametrize("scheme, attrs, expected_bg, expected_scheme", [
    ("dark", "", DARK_PAGE_RGB, "dark"),
    ("light", "", LIGHT_PAGE_RGB, "light"),
    ("dark", 'data-theme="light"', LIGHT_PAGE_RGB, "light"),
    ("light", 'data-theme="dark"', DARK_PAGE_RGB, "dark"),
])
def test_theme_follows_the_system_unless_the_host_forces_one(open_page, scheme, attrs, expected_bg, expected_scheme):
    page, _ = open_page(scheme=scheme, html_attrs=attrs)
    mount(page, "small")
    style = page.evaluate("(() => { const s = getComputedStyle(document.getElementById('a')); return [s.backgroundColor, s.colorScheme]; })()")
    assert style == [expected_bg, expected_scheme]


@pytest.mark.parametrize("scheme, expected", [
    ("light", ["#2a78d6", "#eb6834", "#a8a69d", "#1baf7a"]),
    ("dark", ["#3987e5", "#d95926", "#6b6a63", "#199e70"]),
])
def test_state_colors_are_blue_orange_grey_aqua_in_both_themes(open_page, scheme, expected):
    # păstrat = albastru, returnat = portocaliu, anulat = gri, în curs = aqua (paleta validată)
    page, _ = open_page(scheme=scheme)
    mount(page, "small")
    colors = page.evaluate("""() => { const s = getComputedStyle(document.getElementById('a'));
      return ['--ed-kept', '--ed-returned', '--ed-cancelled', '--ed-pending'].map((n) => s.getPropertyValue(n).trim().toLowerCase()); }""")
    assert colors == expected


@pytest.mark.parametrize("motion, expect_zero", [("reduce", True), ("no-preference", False)])
def test_reduced_motion_removes_transitions(open_page, motion, expect_zero):
    page, _ = open_page(motion=motion)
    mount(page, "small")
    durations = page.evaluate("""() => ['.ed-bar-row', '.ed-toggle', '.ed-chip', '.ed-funnel-seg'].map((sel) => getComputedStyle(document.querySelector('#a ' + sel)).transitionDuration)""")
    assert all(set(d.split(", ")) == {"0s"} for d in durations) == expect_zero


@pytest.mark.parametrize("width, scheme, dataset", [
    (320, "light", "hostile"), (360, "light", "hostile"), (390, "dark", "demo"), (390, "light", "hostile"), (768, "dark", "hostile"), (1280, "light", "hostile"),
])
def test_no_horizontal_page_scroll_at_any_width(open_page, width, scheme, dataset):
    page, probe = open_page(width=width, height=900, scheme=scheme)
    mount(page, dataset)
    settle(page)
    scroll, inner = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert scroll <= inner, (scroll, inner)
    assert_clean(probe)


CONTRAST_SCAN = r"""() => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map((x) => parseFloat(x)); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const over = (top, bottom) => ({ r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a), b: top.b * top.a + bottom.b * (1 - top.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
  const backdrop = (el) => { const stack = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) stack.push(c); if (c && c.a === 1) break; }
    let acc = { r: 255, g: 255, b: 255, a: 1 }; for (let i = stack.length - 1; i >= 0; i--) acc = over(stack[i], acc); return acc; };
  const bad = []; let checked = 0;
  const walker = document.createTreeWalker(document.getElementById('a'), NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement, st = getComputedStyle(el);
    if (el.closest('[hidden]') || st.visibility === 'hidden' || st.display === 'none' || el.closest('.ed-sr') || !el.getClientRects().length) continue;
    const fg = parse(el instanceof SVGElement ? st.fill : st.color); if (!fg) continue;
    const bg = backdrop(el), size = parseFloat(st.fontSize), bold = parseInt(st.fontWeight, 10) >= 700;
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5, got = ratio(over(fg, bg), bg); checked++;
    if (got < need) bad.push([n.textContent.trim().slice(0, 40), el.className && el.className.baseVal === undefined ? el.className : el.tagName, +got.toFixed(2), need]);
  }
  return { checked, bad };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_rendered_text_contrast_meets_wcag_aa(open_page, scheme):
    page, _ = open_page(scheme=scheme)
    mount(page)
    settle(page)
    result = page.evaluate(CONTRAST_SCAN)
    assert result["checked"] > 300  # a citit cu adevărat textul raportului
    assert result["bad"] == []


def test_year_chart_is_redrawn_to_the_container_and_scrolls_when_columns_would_overlap(open_page):
    page, probe = open_page(width=1280, height=900)
    mount(page)
    settle(page)
    measure = """() => { const host = document.querySelector('#a .ed-chart-scroll'), svg = host.querySelector('svg');
      return { host: host.clientWidth, svg: +svg.getAttribute('width'), scrolls: host.scrollWidth > host.clientWidth + 1 }; }"""
    wide = page.evaluate(measure)
    assert wide["svg"] == wide["host"] and not wide["scrolls"]
    page.set_viewport_size({"width": 390, "height": 844})
    settle(page)
    phone = page.evaluate(measure)
    assert phone["svg"] == phone["host"] and not phone["scrolls"] and phone["svg"] < wide["svg"]  # redesenat pe lățimea telefonului, fără derulare
    page.set_viewport_size({"width": 320, "height": 844})
    settle(page)
    narrow = page.evaluate(measure)
    assert narrow["svg"] > narrow["host"] and narrow["scrolls"] and narrow["svg"] < wide["svg"]  # sub lățimea minimă a coloanelor: derulare
    page.set_viewport_size({"width": 1280, "height": 900})
    settle(page)
    assert page.evaluate(measure)["svg"] == page.evaluate(measure)["host"]
    assert_clean(probe)


# ---------- raportul generat de Python și fișierul de demo ----------

def test_generated_report_end_to_end(browser, tmp_path, data):
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, data["demo"])
    context = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
    try:
        page = context.new_page()
        probe = attach_probe(page)
        page.goto(out.as_uri())
        settle(page)
        assert page.title() == "Cheltuieli eMAG" and page.inner_text("h1") == "Cheltuieli eMAG"
        assert blocks(page, "raport") == BLOCKS
        assert page.locator("#raport .ed-banner").count() == 0  # raportul real nu e „demo”
        assert page.eval_on_selector("html", "e => e.lang") == "ro"
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.className") == "rp-skip"
        button = page.locator("#rp-theme")
        assert button.inner_text() == "Temă: automată"
        button.click()
        assert page.get_attribute("html", "data-theme") == "light" and button.inner_text() == "Temă: luminoasă"
        button.click()
        assert page.get_attribute("html", "data-theme") == "dark" and button.inner_text() == "Temă: întunecată"
        assert page.eval_on_selector("#raport", "e => getComputedStyle(e).backgroundColor") == DARK_PAGE_RGB
        assert page.eval_on_selector_all("meta[name='theme-color']", "ms => ms.map((m) => m.content)") == ["#0d0d0d", "#0d0d0d"]
        assert "Tema este acum întunecată" in page.inner_text("#rp-theme-live")
        if page.evaluate("(() => { try { localStorage.setItem('probe', '1'); return true; } catch (e) { return false; } })()"):
            page.reload()
            assert page.get_attribute("html", "data-theme") == "dark"  # tema se ține minte
        button.click()
        assert page.get_attribute("html", "data-theme") is None
        assert page.eval_on_selector_all("meta[name='theme-color']", "ms => ms.map((m) => m.content)") == ["#f9f9f7", "#0d0d0d"]
        assert_clean(probe)
    finally:
        context.close()


def test_generated_report_without_javascript_still_explains_itself(browser, tmp_path, data):
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, data["small"])
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.goto(out.as_uri())
        assert "Raportul are nevoie de JavaScript" in page.inner_text("#raport")
    finally:
        context.close()


def test_generated_report_with_hostile_data_is_inert(browser, tmp_path, data):
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, data["hostile"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        page = context.new_page()
        probe = attach_probe(page)
        page.goto(out.as_uri())
        settle(page)
        assert page.evaluate("window.__pwned") is None
        assert blocks(page, "raport") == BLOCKS
        assert samples.HOSTILE_ALERT in page.inner_text("#raport")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert_clean(probe)
    finally:
        context.close()


def test_demo_data_file_from_the_site_validates_and_renders(open_page):
    demo_file = settings.PROJECT_ROOT / "interfata" / "assets" / "demo-data.js"
    if not demo_file.is_file():
        pytest.skip("interfata/assets/demo-data.js nu există (încă)")
    text = demo_file.read_text(encoding="utf-8")
    prefix, suffix = "window.EMAG_DEMO_DATA = ", ";"
    assert text.startswith(prefix) and text.rstrip().endswith(suffix)
    from_file = json.loads(text[len(prefix):text.rstrip().rindex(suffix)])  # json.loads înțelege și „<\/”
    page, probe = open_page(extra_data={"file": from_file})
    assert page.evaluate("EmagDashboard.validate(DATA.file)") == {"ok": True, "errors": []}
    assert mount(page, "file")["ok"] is True
    settle(page)
    assert blocks(page) == BLOCKS
    assert page.inner_text("#a .ed-banner") == DEMO_BANNER
    assert_clean(probe)
