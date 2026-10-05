"""Teste de calitate în browser real ale paginii aplicatie.html: contrast, ținte, layout, teme, mișcare, tastatură, accesibilitate.

Primește: pagina servită de serverul fals din tests/app_ui_support.py, adusă pe fiecare ecran. Verifică (măsurat în pagina randată,
nu din tokeni): contrastul fiecărui text vizibil în ambele teme, ținte de cel puțin 40 px, fără scroll orizontal la 320, 390 și 1280 px,
fără salturi de layout în timpul rulării și la încărcare (CLS), tema automată/luminoasă/întunecată (și că raportul o urmează),
mișcarea redusă, contrastul forțat, inelul de focus vizibil, ierarhia de titluri și numele accesibile.
Ce NU face: nu verifică fluxurile (test_app_ui_screens.py) și nici cheia de acces (test_app_ui_security.py). Se sare dacă nu pornește niciun browser.
"""

import pytest

from tests.app_ui_support import (  # noqa: F401 - fixture-urile se găsesc prin importul lor în modul
    CONTRAST_SCAN_JS, INTERFACE_DIR, OVERFLOW_JS, TAP_TARGET_JS, FakeAppServer, browser, capture, fake, open_app, open_page,
    playwright_instance, probe_problems, wait_js, wait_screen,
)

pytest.importorskip("playwright.sync_api")

MIN_TARGET_PX = 40  # brief: ținte tactile de cel puțin 40 px
MAX_STEADY_SHIFT_PX = 2  # cât se poate mișca butonul „Oprește” între stările rulării (rotunjiri)
MAX_LOAD_CLS = 0.02  # layout shift tolerat la încărcare (ca la site: aproape zero)
CLS_SPY = """(() => { window.__cls = 0; new PerformanceObserver((list) => { for (const e of list.getEntries()) { if (!e.hadRecentInput) window.__cls += e.value; } })
  .observe({type: 'layout-shift', buffered: true}); })();"""
FOCUS_RING_JS = "() => { const s = getComputedStyle(document.activeElement); return {style: s.outlineStyle, width: parseFloat(s.outlineWidth), color: s.outlineColor}; }"
ACCESSIBLE_NAMES_JS = r"""() => [...document.querySelectorAll('button, a[href], input:not([type="hidden"]), summary')]
  .filter((el) => el.getClientRects().length && !el.closest('.emag-dash'))
  .map((el) => { const labelled = (el.getAttribute('aria-labelledby') || '').split(' ').map((id) => (document.getElementById(id) || {}).textContent || '').join(' ').trim();
    const forLabel = el.id ? ((document.querySelector('label[for="' + el.id + '"]') || {}).textContent || '').trim() : '';
    return {tag: el.tagName, id: el.id, name: (el.getAttribute('aria-label') || labelled || forLabel || el.textContent || '').trim()}; })
  .filter((x) => !x.name)"""
HEADING_LEVELS_JS = "() => [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter((h) => h.getClientRects().length).map((h) => +h.tagName[1])"


def reach(page, fake, screen: str) -> None:
    """Aduce pagina (deschisă pe ecranul de start) pe ecranul cerut; „ready-open” deschide și opțiunile, panoul de ștergere și trei întrebări."""
    if screen == "ready":
        return
    if screen == "ready-open":
        page.click("#options summary")
        page.click("#btn-session-delete")
        for item in ("faq-ce-face", "faq-sigur", "faq-nu-merge"):
            page.click(f"#{item} summary")
        return
    page.click("#btn-start")
    wait_screen(page, "working")
    run_id = fake.started[-1]["run_id"]
    if screen == "working-login":
        fake.set_state(state="waiting_login")
        page.wait_for_selector("#work-callout[data-kind='login']")
    elif screen == "working-orders":
        fake.set_state(state="fetching_orders", progress={"phase": "orders", "done": 325, "total": 416})
        wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 325 din 416'")
    elif screen == "done":
        fake.finish_run(run_id)
        wait_screen(page, "done")
        page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    elif screen == "error":
        fake.set_state(state="error", error={"code": "x", "message": "Nu te-ai logat în timpul alocat; pornește din nou analiza."})
        wait_screen(page, "error")
    elif screen == "cancelled":
        page.click("#btn-cancel")
        wait_screen(page, "cancelled")
    else:
        raise ValueError(screen)


# ---------- contrast măsurat în pagină ----------

@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("screen", ["ready-open", "working-login", "working-orders", "error", "cancelled"])
def test_every_visible_text_meets_contrast_in_the_rendered_page(open_page, fake, theme, screen):
    """Contrastul fiecărui text vizibil (în afara raportului) ≥ 4.5:1 (3:1 la text mare), cu temă automată ca în browserul omului."""
    page, probe = open_page(scheme=theme)
    reach(page, fake, screen)
    assert page.evaluate(CONTRAST_SCAN_JS) == []
    capture(page, f"calitate_{screen}_{theme}")
    assert probe_problems(probe) == {}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("screen", ["closed-nokey", "closed-needs-app"])
def test_closed_screens_meet_contrast(browser, fake, theme, screen):
    """Ecranele de „închis” (fără cheie, din folder) au contrast bun în ambele teme."""
    if screen == "closed-nokey":
        context, page, _ = open_app(browser, fake, scheme=theme, with_token=False, wait_for=None)
    else:
        context, page, _ = open_app(browser, fake, scheme=theme, url=(INTERFACE_DIR / "aplicatie.html").as_uri(), wait_for=None)
    try:
        wait_screen(page, screen)
        assert page.evaluate(CONTRAST_SCAN_JS) == []
        capture(page, f"calitate_{screen}_{theme}")
    finally:
        context.close()


def test_the_scanner_catches_low_contrast(open_page):
    """Detectorul de contrast se vede picând pe o pagină-capcană: un text gri deschis pe alb e raportat."""
    page, _ = open_page()
    page.evaluate("""() => { const p = document.createElement('p'); p.id = 'capcana'; p.textContent = 'Text greu de citit';
      p.style.setProperty('color', '#bbbbbb'); p.style.setProperty('background-color', '#ffffff'); document.getElementById('ready-t').after(p); }""")
    found = page.evaluate(CONTRAST_SCAN_JS)
    assert [f["text"] for f in found] == ["Text greu de citit"] and found[0]["ratio"] < 2


# ---------- dimensiuni, ținte, fără scroll orizontal ----------

@pytest.mark.parametrize("width, height", [(320, 700), (390, 844), (1280, 900)])
@pytest.mark.parametrize("screen", ["ready-open", "working-login", "done", "error", "cancelled"])
def test_no_horizontal_scroll_and_every_control_is_at_least_40_px(open_page, fake, width, height, screen):
    """Fără scroll orizontal și fără element care iese din ecran; butoanele, câmpurile și titlurile din FAQ au cel puțin 40 px."""
    page, probe = open_page(width=width, height=height, touch=width < 600)
    reach(page, fake, screen)
    page.wait_for_timeout(300)
    overflow = page.evaluate(OVERFLOW_JS)
    assert overflow["scrollWidth"] <= overflow["clientWidth"], overflow
    assert overflow["outside"] == [], overflow
    assert page.evaluate(TAP_TARGET_JS, MIN_TARGET_PX) == []
    assert probe_problems(probe) == {}


@pytest.mark.parametrize("screen", ["closed-nokey", "closed-needs-app"])
def test_closed_screens_fit_a_phone(browser, fake, screen):
    """Ecranele de „închis” încap la 320 px fără scroll orizontal."""
    if screen == "closed-nokey":
        context, page, _ = open_app(browser, fake, width=320, height=700, with_token=False, wait_for=None)
    else:
        context, page, _ = open_app(browser, fake, width=320, height=700, url=(INTERFACE_DIR / "aplicatie.html").as_uri(), wait_for=None)
    try:
        wait_screen(page, screen)
        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow["scrollWidth"] <= overflow["clientWidth"] and overflow["outside"] == [], overflow
        assert page.evaluate(TAP_TARGET_JS, MIN_TARGET_PX) == []
    finally:
        context.close()


def test_the_tap_target_scanner_catches_small_controls(open_page):
    """Detectorul de ținte se vede picând: un buton de 20 px e raportat."""
    page, _ = open_page()
    page.evaluate("""() => { const b = document.createElement('button'); b.id = 'mic'; b.textContent = 'x';
      b.style.setProperty('width', '20px'); b.style.setProperty('height', '20px'); document.getElementById('ready-t').after(b); }""")
    assert [t["id"] for t in page.evaluate(TAP_TARGET_JS, MIN_TARGET_PX)] == ["mic"]


# ---------- stabilitate ----------

@pytest.mark.parametrize("width, height", [(1280, 900), (390, 844)])
def test_the_working_screen_does_not_jump_between_states(open_page, fake, width, height):
    """Butonul „Oprește” și lista de pași rămân pe loc (±2 px) prin toate stările rulării, inclusiv mesajul mare de login."""
    page, _ = open_page(width=width, height=height)
    page.click("#btn-start")
    wait_screen(page, "working")
    tops = []

    def measure(label):
        """Pozițiile verticale ale butonului, listei de pași și barei de progres, în starea curentă."""
        tops.append((label, page.evaluate("[...['btn-cancel', 'steps', 'progress'].map((id) => Math.round(document.getElementById(id).getBoundingClientRect().top))]")))

    measure("starting")
    for state, progress, label in [("waiting_login", {"done": 0, "total": None}, "Aștept să te loghezi…"),
                                   ("fetching_orders", {"done": 7, "total": None}, "Comenzi: 7 citite până acum"),
                                   ("fetching_orders", {"done": 325, "total": 416}, "Comenzi: 325 din 416"),
                                   ("fetching_returns", {"done": 12, "total": 43}, "Retururi: 12 din 43"),
                                   ("analyzing", {"done": 0, "total": None}, "Calculez raportul…")]:
        fake.set_state(state=state, progress=progress)
        wait_js(page, "(l) => document.getElementById('progress-label').textContent === l", label)
        measure(state + " " + label)
    first = tops[0][1]
    for label, positions in tops:
        assert all(abs(a - b) <= MAX_STEADY_SHIFT_PX for a, b in zip(positions, first)), f"{label}: {positions} față de {first}"


@pytest.mark.parametrize("width, height", [(1280, 900), (390, 844)])
def test_loading_the_page_causes_no_layout_shift(browser, fake, width, height):
    """De la „se verifică aplicația” la ecranul de start nu sare nimic (CLS aproape zero): FAQ-ul și subsolul așteaptă."""
    context, page, _ = open_app(browser, fake, width=width, height=height, init_script=CLS_SPY)
    try:
        page.wait_for_timeout(1200)
        assert page.evaluate("window.__cls") <= MAX_LOAD_CLS
    finally:
        context.close()


# ---------- teme ----------

def test_theme_button_cycles_automatic_light_dark_and_remembers_the_choice(open_page, fake):
    """Butonul de temă: automată → luminoasă → întunecată → automată; atributul, textul, culoarea barei și memoria în localStorage se schimbă."""
    page, _ = open_page(scheme="light")
    meta = lambda: page.evaluate("[...document.querySelectorAll('meta[name=theme-color]')].map((m) => m.content)")  # noqa: E731
    assert page.get_attribute("html", "data-theme") is None and page.inner_text("#theme-label") == "Temă: automată"
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "light" and page.inner_text("#theme-label") == "Temă: luminoasă"
    assert meta() == ["#f2f3f0", "#f2f3f0"]
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "dark" and page.inner_text("#theme-label") == "Temă: întunecată"
    assert meta() == ["#0e1114", "#0e1114"]
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(14, 17, 20)"
    assert page.evaluate("localStorage.getItem('emag-tema')") == "dark"
    page.reload()  # cheia de acces se pierde (ecran „nokey”), dar tema se aplică înainte de prima pictare
    assert page.get_attribute("html", "data-theme") == "dark"
    wait_screen(page, "closed-nokey")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(14, 17, 20)"
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") is None and page.inner_text("#theme-label") == "Temă: automată"
    assert meta() == ["#f2f3f0", "#0e1114"], "la tema automată revin culorile din HTML"


@pytest.mark.parametrize("scheme, background", [("light", "rgb(242, 243, 240)"), ("dark", "rgb(14, 17, 20)")])
def test_automatic_theme_follows_the_system_preference(open_page, scheme, background):
    """Fără alegere salvată, pagina urmează prefers-color-scheme (fără atribut data-theme)."""
    page, _ = open_page(scheme=scheme)
    assert page.get_attribute("html", "data-theme") is None
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == background


def test_the_report_follows_the_page_theme(open_page, fake):
    """Raportul (EmagDashboard) își schimbă culorile odată cu tema paginii."""
    page, _ = open_page(scheme="light")
    reach(page, fake, "done")
    token = "getComputedStyle(document.getElementById('report-root')).getPropertyValue('--ed-page').trim()"
    assert page.evaluate(token) == "#f9f9f7"
    page.click("#theme-toggle")
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "dark"
    assert page.evaluate(token) == "#0d0d0d"
    capture(page, "calitate_raport_tema_intunecata")


# ---------- mișcare, contrast forțat ----------

def test_reduced_motion_removes_animations_and_transitions(open_page, fake):
    """Cu mișcare redusă nu rulează nicio animație și nicio tranziție; fără preferință, pulsul pasului activ și bara se animă."""
    page, _ = open_page(motion="reduce")
    reach(page, fake, "working-orders")
    probe = """() => ({pulse: getComputedStyle(document.querySelector('.step[data-status=active] .step__mark'), '::after').animationName,
                       bar: getComputedStyle(document.getElementById('progress-fill')).transitionDuration,
                       button: getComputedStyle(document.getElementById('btn-cancel')).transitionDuration})"""
    assert page.evaluate(probe) == {"pulse": "none", "bar": "0s", "button": "0s"}
    other = FakeAppServer(session_saved=True).start()  # a doua pagină are aplicația ei: prima a pornit deja o rulare pe `fake`
    try:
        page2, _ = open_page(other, motion="no-preference")
        reach(page2, other, "working-orders")
        animated = page2.evaluate(probe)
    finally:
        other.stop()
    assert animated["pulse"] == "step-pulse" and animated["bar"] == "0.4s" and animated["button"] != "0s"


def test_reduced_motion_hides_the_moving_progress_segment(open_page, fake):
    """Bara indeterminată nu se mișcă la mișcare redusă: segmentul care aleargă dispare, rămâne eticheta cu text."""
    page, _ = open_page(motion="reduce")
    reach(page, fake, "working-login")
    fake.set_state(state="analyzing", progress={"done": 0, "total": None})
    wait_js(page, "document.getElementById('progress').dataset.mode === 'indeterminate'")
    assert page.evaluate("getComputedStyle(document.getElementById('progress-fill')).display") == "none"
    assert page.inner_text("#progress-label") == "Calculez raportul…"


def test_forced_colors_keep_controls_visible(open_page, fake):
    """În contrast forțat (Windows high contrast) butoanele și câmpurile au contur, iar pagina rămâne curată."""
    page, probe = open_page(forced_colors="active")
    assert page.evaluate("matchMedia('(forced-colors: active)').matches") is True
    page.click("#options summary")
    widths = page.evaluate("""() => ['btn-start', 'btn-demo', 'theme-toggle', 'threshold'].map((id) => getComputedStyle(document.getElementById(id)).borderTopWidth)""")
    assert widths == ["1px"] * 4
    capture(page, "calitate_contrast_fortat")
    reach(page, fake, "working-orders")
    assert page.evaluate("getComputedStyle(document.getElementById('progress-bar')).borderTopWidth") == "1px"
    capture(page, "calitate_contrast_fortat_progres")
    assert probe_problems(probe) == {}


# ---------- tastatură și accesibilitate ----------

def test_every_control_reached_with_tab_shows_a_visible_focus_ring(open_page):
    """Fiecare control atins cu Tab are inel de focus (contur continuu, cel puțin 2 px)."""
    page, _ = open_page()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Shift+Tab")
    seen = []
    for _ in range(12):
        page.keyboard.press("Tab")
        ring = page.evaluate(FOCUS_RING_JS)
        seen.append(ring)
        assert ring["style"] != "none" and ring["width"] >= 2, ring
    assert len(seen) == 12


def test_heading_levels_never_skip_and_there_is_one_h1(open_page, fake):
    """Titlurile vizibile: un singur h1 și nicio sărire de nivel (h1, h2, h3 … inclusiv blocurile raportului), pe start și pe raport."""
    page, _ = open_page()
    for screen in ("ready", "done"):
        reach(page, fake, screen)
        levels = page.evaluate(HEADING_LEVELS_JS)
        assert levels.count(1) == 1 and levels[0] == 1, levels
        assert all(b <= a + 1 for a, b in zip(levels, levels[1:])), levels
        assert max(levels) >= (3 if screen == "done" else 2)
        if screen == "done":  # titlul ecranului e h2, deci blocurile raportului trebuie să înceapă la h3 (headingLevel: 3)
            assert page.locator("#report-root h2").count() == 0 and page.locator("#report-root h3").count() > 0


def test_every_visible_control_has_an_accessible_name(open_page, fake):
    """Butoane, linkuri, câmpuri și rezumate vizibile au nume accesibil (text, aria-label sau etichetă), pe start, în lucru și raport."""
    page, _ = open_page()
    reach(page, fake, "ready-open")
    assert page.evaluate(ACCESSIBLE_NAMES_JS) == []
    page.click("#btn-start")
    wait_screen(page, "working")
    assert page.evaluate(ACCESSIBLE_NAMES_JS) == []
    fake.finish_run(fake.started[-1]["run_id"])
    wait_screen(page, "done")
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    assert page.evaluate(ACCESSIBLE_NAMES_JS) == []


def test_progress_and_status_regions_are_exposed_to_assistive_technology(open_page, fake):
    """Bara de progres are rol, interval și text; zonele cu mesaje sunt politicoase; titlul ecranului curent e legat de secțiune."""
    page, _ = open_page()
    reach(page, fake, "working-orders")
    assert page.get_attribute("#progress-bar", "role") == "progressbar"
    assert page.get_attribute("#progress-bar", "aria-valuemin") == "0" and page.get_attribute("#progress-bar", "aria-valuemax") == "100"
    assert page.get_attribute("#steps .step[data-status='active']", "aria-current") == "step"
    assert page.get_attribute("#screen-working", "aria-labelledby") == "working-t"
    assert page.locator("#screen-working").is_visible() and page.locator("#screen-ready").is_hidden()


def test_without_javascript_the_page_explains_itself_and_the_faq_still_reads(browser, fake):
    """Fără JavaScript: mesajul <noscript> se vede, ecranul „se verifică aplicația” nu rămâne agățat, iar FAQ-ul și subsolul se citesc (details e nativ)."""
    context, page, _ = open_app(browser, fake, javascript=False, wait_for=None)
    try:
        assert "are nevoie de JavaScript" in page.inner_text("noscript")
        assert page.locator("#screen-loading").is_hidden()
        assert page.locator(".faq").is_visible() and page.locator("footer").is_visible()
        page.click("#faq-login summary")
        assert page.locator("#faq-login .faq__body").is_visible()
        assert page.locator("button#btn-start").is_hidden(), "controalele aplicației nu se arată fără script"
        assert fake.api_requests() == []
    finally:
        context.close()
