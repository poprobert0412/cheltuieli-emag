"""Teste în browser real (Edge sau Chrome, prin Playwright) ale ecranelor paginii aplicatie.html, pe un server FALS al aplicației.

Primește: aplicatie.html servită de serverul fals din tests/app_ui_support.py (același contract API, aceeași politică de conținut
ca în producție, deci orice stil sau script inline apare ca eroare de consolă). Verifică fiecare ecran și trecerea dintre ele:
gata de start (prag, sesiune, rulări anterioare), în lucru (pași, progres, login), raport (componenta, descărcări), eroare, anulat,
oprit, plus FAQ-ul. Ce NU face: nu verifică calitatea (contrast, ținte, layout: test_app_ui_quality.py) și nici securitatea
cheii (test_app_ui_security.py). Se sare dacă niciun browser nu pornește.
"""

from pathlib import Path

import pytest

from tests import app_ui_support
from tests.app_ui_support import (  # noqa: F401 - fixture-urile se găsesc prin importul lor în modul
    SESSION_DELETED_MESSAGE, FakeAppServer, browser, capture, current_screen, fake, open_app, open_page, playwright_instance, probe_problems,
    sample_runs, transient_os_failure, wait_js, wait_screen,
)
from tests.test_app_ui_static import EXPECTED_FAQ

pytest.importorskip("playwright.sync_api")

ACTIVE_TITLE = "#work-callout [data-active] .callout__title"
ACTIVE_TEXT = "#work-callout [data-active] .callout__text"
ACTIVE_ELEMENT_JS = "() => { const e = document.activeElement; return e.id || e.getAttribute('aria-label') || e.className.split(' ')[0] || e.tagName; }"
STEP_STATUSES_JS = "() => [...document.querySelectorAll('#steps .step')].map((e) => e.dataset.status)"
STEP_STATUS_TEXTS_JS = "() => [...document.querySelectorAll('#steps .step__status')].map((e) => e.textContent)"


@pytest.mark.parametrize("failure, transient", [
    ("net::ERR_NO_BUFFER_SPACE", True), ("net::ERR_INSUFFICIENT_RESOURCES", True),
    ("net::ERR_CONNECTION_RESET", False), ("net::ERR_CONNECTION_REFUSED", False), ("net::ERR_EMPTY_RESPONSE", False), ("net::ERR_FAILED", False),
])
def test_only_errors_given_by_the_operating_system_make_the_page_load_again(failure, transient):
    """Doar erorile date de sistem (pe Windows, WSAENOBUFS la connect) se reiau; RESET, REFUSED sau răspunsul gol pot fi greșeli ale serverului."""
    assert transient_os_failure([f"http://127.0.0.1:1/assets/app-state.js {failure}"]) is transient
    assert transient_os_failure([]) is False


def test_a_page_whose_script_hit_an_error_from_the_system_is_loaded_again(browser, fake, monkeypatch):
    """Simulat: serverul închide fără răspuns prima cerere pentru app-state.js (în Chromium: ERR_EMPTY_RESPONSE), iar eroarea aceasta e
    tratată ca eroare de sistem. open_app încarcă pagina din nou, ajunge la un ecran și nu lasă nicio urmă a primei încercări."""
    monkeypatch.setattr(app_ui_support, "TRANSIENT_OS_ERRORS", ("net::ERR_EMPTY_RESPONSE",))
    original = app_ui_support._Handler.do_GET
    dropped = []

    def drop_the_first(self):
        if self.path == "/assets/app-state.js" and not dropped:
            dropped.append(self.path)
            self.close_connection = True
            self.connection.close()
            return None
        return original(self)

    monkeypatch.setattr(app_ui_support._Handler, "do_GET", drop_the_first)
    with pytest.warns(UserWarning, match="s-a încărcat din nou"):
        context, page, probe = open_app(browser, fake)
    try:
        assert dropped == ["/assets/app-state.js"]
        assert current_screen(page) == "ready"
        assert probe_problems(probe) == {}
    finally:
        context.close()


@pytest.mark.parametrize("module", ["faq", "download", "history", "update"])
def test_a_module_whose_script_does_not_load_does_not_stop_the_page(browser, fake, module):
    """Un app-*.js care nu se încarcă (pe Windows: conexiune refuzată) nu ține pagina la „Se verifică aplicația…”: ceilalți pornesc,
    pagina ajunge la un ecran, iar consola numește modulul căzut."""
    context = browser.new_context()
    try:
        context.route(f"**/assets/app-{module}.js", lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(fake.page_url())
        page.wait_for_selector("html[data-current-screen]:not([data-current-screen='loading'])", state="attached")
        assert current_screen(page) == "ready"
        assert any(f"modulul {module} nu a pornit" in text for text in errors), errors
    finally:
        context.close()


def start_run(page, fake, mode="real"):
    """Apasă butonul potrivit și așteaptă ecranul „în lucru”; întoarce numărul rulării pornite."""
    page.click("#btn-start" if mode == "real" else "#btn-demo")
    wait_screen(page, "working")
    return fake.started[-1]["run_id"]


def live_text_contains(page, text, timeout=5000):
    """Așteaptă până când zona live globală conține `text`."""
    wait_js(page, "(t) => document.getElementById('app-live').textContent.includes(t)", text, timeout)


# ---------- (b) gata de start ----------

def test_ready_screen_is_the_first_screen_and_loads_clean(open_page, fake):
    """Cu aplicația pornită, pagina arată „Gata de start”, cu starea sesiunii, rulările anterioare și versiunea; fără erori de consolă."""
    page, probe = open_page()
    assert current_screen(page) == "ready"
    assert page.title() == "Gata de start · Cheltuieli eMAG"
    assert page.locator("#ready-t").inner_text() == "Gata de start"
    assert page.locator("#session-status").inner_text() == "Ești conectat de data trecută"
    assert page.locator("#hist-list li").count() == len(fake.runs)
    assert fake.version in page.locator("#app-version").inner_text()
    assert page.locator("#threshold").input_value() == "500"
    capture(page, "ecran_gata_de_start")
    assert probe_problems(probe) == {}


def test_the_start_button_has_the_initial_focus_and_enter_starts_the_run(open_page, fake):
    """Focusul inițial e pe „Pornește analiza”; Enter pornește rularea, iar focusul trece pe titlul ecranului „în lucru”."""
    page, _ = open_page()
    assert page.evaluate(ACTIVE_ELEMENT_JS) == "btn-start"
    page.keyboard.press("Enter")
    wait_screen(page, "working")
    assert fake.started[0]["mode"] == "real"
    wait_js(page, "document.activeElement.id === 'working-t'")


def test_tab_order_follows_the_reading_order(open_page):
    """Tab parcurge: sari la conținut, temă, Pornește, opțiuni, demo, ștergerea sesiunii, rulările, Închide aplicația, FAQ."""
    page, _ = open_page()
    backwards = []
    for _ in range(2):  # focusul inițial e pe „Pornește analiza”: două Shift+Tab ajung la începutul paginii
        page.keyboard.press("Shift+Tab")
        backwards.append(page.evaluate(ACTIVE_ELEMENT_JS))
    assert backwards == ["theme-toggle", "skip-link"]
    order = ["skip-link"]
    for _ in range(11):
        page.keyboard.press("Tab")
        order.append(page.evaluate(ACTIVE_ELEMENT_JS))
    assert order[:6] == ["skip-link", "theme-toggle", "btn-start", "SUMMARY", "btn-demo", "btn-session-delete"]
    opens = [i for i, name in enumerate(order) if name.startswith("Deschide raportul")]
    assert len(opens) == 2 and opens == [6, 7], order  # a treia rulare nu are raport: fără buton
    assert order[8] == "btn-shutdown" and order[9] == "SUMMARY"


@pytest.mark.parametrize("value", ["abc", "-5", "1000000001", "12,3,4", "5 000"])
def test_an_invalid_threshold_is_refused_next_to_the_field_and_nothing_starts(open_page, fake, value):
    """Prag invalid: mesaj lângă câmp, aria-invalid, focus pe câmp, opțiunile se deschid, nicio cerere de pornire."""
    page, _ = open_page()
    page.click("#options summary")
    page.fill("#threshold", value)
    page.press("#threshold", "Enter")
    assert current_screen(page) == "ready"
    assert page.get_attribute("#threshold", "aria-invalid") == "true"
    assert "is-bad" in page.get_attribute("#threshold-hint", "class")
    assert page.inner_text("#threshold-hint") != ""
    assert page.evaluate(ACTIVE_ELEMENT_JS) == "threshold"
    assert fake.started == []
    page.fill("#threshold", "700")
    assert page.get_attribute("#threshold", "aria-invalid") is None, "eroarea dispare imediat ce omul scrie"


@pytest.mark.parametrize("typed, sent", [
    ("999,50", 999.5), ("1000", 1000), ("0", 0), ("1000000000", 1000000000), ("  750.25 ", 750.25),
    ("500", None), ("", None), ("500,00", None),
])
def test_the_threshold_is_sent_only_when_it_differs_from_the_default(open_page, fake, typed, sent):
    """Pragul scris (virgulă sau punct) pleacă ca număr; gol sau egal cu implicitul nu pleacă deloc (aplicația folosește implicitul ei)."""
    page, _ = open_page()
    page.click("#options summary")
    page.fill("#threshold", typed)
    page.click("#btn-start")
    wait_screen(page, "working")
    assert fake.started[0]["threshold_lei"] == sent


def test_demo_button_starts_a_demo_run_without_login(open_page, fake):
    """„Încearcă cu date inventate” cere mode=demo; pașii 1–3 arată „nu e nevoie”, iar la final raportul are bannerul de date inventate."""
    page, probe = open_page()
    run_id = start_run(page, fake, "demo")
    assert fake.started[0]["mode"] == "demo"
    assert page.evaluate(STEP_STATUSES_JS) == ["skipped", "skipped", "skipped", "active"]
    assert page.evaluate(STEP_STATUS_TEXTS_JS) == ["nu e nevoie", "nu e nevoie", "nu e nevoie", "în lucru"]
    fake.set_state(state="analyzing")
    wait_screen(page, "working")
    wait_js(page, "document.querySelector('#work-callout [data-active] .callout__text').textContent.includes('inventate')")
    fake.finish_run(run_id, kind="demo")
    wait_screen(page, "done")
    page.wait_for_selector("#report-root .ed-banner")
    assert "inventate" in page.inner_text("#report-root .ed-banner")
    assert page.inner_text("#done-sub") == "Rulare de probă, cu date inventate."
    assert probe_problems(probe) == {}


# ---------- (c) în lucru ----------

def test_a_real_run_shows_steps_progress_and_the_login_message(open_page, fake):
    """Pașii trec din „în așteptare” în „în lucru” și „gata”; progresul are numere; login-ul are mesajul mare; schimbările se anunță."""
    page, probe = open_page()
    run_id = start_run(page, fake)
    assert page.evaluate(STEP_STATUSES_JS) == ["active", "pending", "pending", "pending"]
    assert page.title() == "Analiza e în lucru · Cheltuieli eMAG"

    fake.set_state(state="waiting_login", message="Aștept login-ul")
    page.wait_for_selector("#work-callout[data-kind='login']")
    assert "loghează-te" in page.inner_text(ACTIVE_TITLE)
    assert "programul n-o vede" in page.inner_text(ACTIVE_TEXT)
    assert page.inner_text("#progress-label") == "Aștept să te loghezi…"
    live_text_contains(page, "S-a deschis o fereastră de browser")
    assert page.inner_text("#work-detail") == "", "la login mesajul serverului ar repeta mesajul mare: nu se arată"
    capture(page, "ecran_in_lucru_login")

    fake.set_state(state="fetching_orders", message="Caut comenzile în cont: pagina 3 din 12", progress={"phase": "fetching_orders", "done": 7, "total": None})
    wait_js(page, "document.getElementById('progress').dataset.mode === 'indeterminate'")
    assert page.inner_text("#progress-label") == "Comenzi: 7 citite până acum"
    assert page.inner_text("#work-detail") == "Caut comenzile în cont: pagina 3 din 12", "fără total, mesajul serverului spune ceva în plus"

    fake.set_state(progress={"phase": "orders", "done": 325, "total": 416})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 325 din 416'")
    assert page.evaluate(STEP_STATUSES_JS) == ["done", "active", "pending", "pending"]
    assert page.inner_text("#work-detail") == "", "cu total cunoscut cifrele sunt în bară: mesajul serverului nu le mai repetă"
    bar = page.locator("#progress-bar")
    assert bar.get_attribute("aria-valuenow") == "78" and bar.get_attribute("aria-valuetext") == "Comenzi: 325 din 416"
    assert page.evaluate("document.getElementById('progress-fill').style.transform") == "scaleX(0.78)"
    live_text_contains(page, "Pasul 2 din 4: Comenzi.")
    capture(page, "ecran_in_lucru_comenzi")

    fake.set_state(state="fetching_returns", progress={"phase": "returns", "done": 12, "total": 43})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Retururi: 12 din 43'")
    assert page.evaluate(STEP_STATUSES_JS) == ["done", "done", "active", "pending"]

    fake.set_state(state="analyzing", progress={"phase": "calc", "done": 0, "total": None})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Calculez raportul…'")
    assert page.evaluate(STEP_STATUSES_JS) == ["done", "done", "done", "active"]
    assert page.get_attribute("#progress-bar", "aria-valuenow") is None, "bara indeterminată nu pretinde o valoare"

    fake.finish_run(run_id)
    wait_screen(page, "done")
    assert page.inner_text("#done-t") == "Raportul tău"
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    assert page.locator("#report-root [data-ed-block]").count() >= 8
    assert page.get_attribute("#report-root", "data-ed-state") == "ready"
    assert probe_problems(probe) == {}


def test_large_progress_numbers_use_romanian_grouping(open_page, fake):
    """Numerele de peste o mie se scriu cu punct: „1.234 din 2.000”."""
    page, _ = open_page()
    start_run(page, fake)
    fake.set_state(state="fetching_orders", progress={"phase": "orders", "done": 1234, "total": 2000})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 1.234 din 2.000'")


def test_progress_is_announced_only_at_quarter_steps(open_page, fake):
    """Cititoarele de ecran aud schimbarea de pas și apoi cifrele din sfert în sfert, nu la fiecare interogare."""
    page, _ = open_page()
    start_run(page, fake)
    fake.set_state(state="fetching_orders", progress={"phase": "orders", "done": 10, "total": 100})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 10 din 100'")
    live_text_contains(page, "Pasul 2 din 4")
    fake.set_state(progress={"phase": "orders", "done": 15, "total": 100})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 15 din 100'")
    assert "Pasul 2 din 4" in page.inner_text("#app-live"), "15% e tot în primul sfert: nu se anunță din nou cifrele"
    fake.set_state(progress={"phase": "orders", "done": 60, "total": 100})
    live_text_contains(page, "Comenzi: 60 din 100")


def test_a_temporary_connection_failure_shows_a_warning_and_recovers(open_page, fake):
    """O eroare trecătoare la /api/state arată „Conexiunea s-a întrerupt” și dispare singură la următorul răspuns bun."""
    page, _ = open_page()
    start_run(page, fake)
    fake.set_state(state="fetching_orders", progress={"phase": "orders", "done": 5, "total": 10})
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 5 din 10'")
    fake.fail_next[("GET", "/api/state")] = (500, "internal", "Eroare internă de test.")
    page.wait_for_selector("#work-callout[data-kind='warn']")
    assert "Conexiunea cu aplicația s-a întrerupt" in page.inner_text(ACTIVE_TITLE)
    page.wait_for_selector("#work-callout[data-kind='info']", timeout=6000)
    assert current_screen(page) == "working"


def test_cancel_button_stops_the_run_and_shows_the_cancelled_screen(open_page, fake):
    """„Oprește” cere oprirea o singură dată (butonul își schimbă textul) și duce la ecranul „Analiza a fost oprită”."""
    page, probe = open_page()
    start_run(page, fake)
    page.click("#btn-cancel")
    wait_screen(page, "cancelled")
    assert fake.cancel_requests == 1
    assert page.inner_text("#cancelled-t") == "Analiza a fost oprită"
    wait_js(page, "document.activeElement.id === 'cancelled-t'")
    assert "Nu s-a creat niciun raport" in page.inner_text("#screen-cancelled")
    capture(page, "ecran_anulat")
    page.click("#screen-cancelled [data-action='back']")
    wait_screen(page, "ready")
    assert probe_problems(probe) == {}


def test_cancel_button_label_while_the_request_is_in_flight(open_page, fake):
    """După clic, butonul spune „Se oprește…” și nu mai cere încă o dată."""
    page, _ = open_page()
    start_run(page, fake)
    fake.set_state(state="fetching_orders")
    page.click("#btn-cancel")
    # Al doilea clic direct pe element: un clic Playwright (chiar forțat) pică dacă pagina a trecut deja la „oprită” și butonul
    # s-a ascuns (cursă văzută sub încărcare, în CI); handler-ul trebuie să ignore clicul oricum, vizibil sau nu.
    page.evaluate("document.getElementById('btn-cancel').click()")
    wait_screen(page, "cancelled")
    assert fake.cancel_requests == 1


def test_a_run_already_in_progress_is_shown_instead_of_an_error(open_page, fake):
    """La 409 (rulează deja una) pagina arată progresul ei, nu o eroare."""
    page, _ = open_page()
    fake.set_state(state="fetching_orders", run_id="2026-10-05_11-59-00", started_at="2026-10-05 11:59:00",
                   progress={"phase": "orders", "done": 3, "total": 9})
    page.evaluate("document.getElementById('btn-start').click()")
    wait_screen(page, "working")
    wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 3 din 9'")
    assert fake.started == []
    assert page.inner_text("#start-error") == ""


def test_the_working_screen_shows_immediately_while_the_state_catches_up(open_page, fake):
    """Aplicația a acceptat rularea (202) dar /api/state încă n-o arată: pagina rămâne pe „în lucru”, nu sare înapoi pe start."""
    fake.hold_start = True
    page, _ = open_page()
    page.click("#btn-demo")
    wait_screen(page, "working")
    page.wait_for_timeout(3200)  # peste un ciclu de interogare (2,5 s în repaus)
    assert current_screen(page) == "working"
    run_id = fake.started[0]["run_id"]
    fake.set_state(state="analyzing", run_id=run_id, started_at="2026-10-05 12:00:00")
    fake.finish_run(run_id, kind="demo")
    wait_screen(page, "done")


def test_the_page_opened_during_a_run_goes_straight_to_the_working_screen(open_page, fake):
    """Pagina deschisă cât rulează o analiză (stare activă) arată direct „în lucru”, fără să treacă pe ecranul de start."""
    fake.set_state(state="waiting_login", run_id="2026-10-05_11-59-00", started_at="2026-10-05 11:59:00")
    page, probe = open_page()
    assert current_screen(page) == "working"
    page.wait_for_selector("#work-callout[data-kind='login']")
    assert probe_problems(probe) == {}


# ---------- (d) raport, descărcări, rulări repetate ----------

def finish_and_open_report(page, fake, kind="real"):
    """Pornește o rulare, o termină și așteaptă raportul; întoarce numărul rulării."""
    run_id = start_run(page, fake, "real" if kind == "real" else "demo")
    fake.finish_run(run_id, kind=kind)
    wait_screen(page, "done")
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    return run_id


@pytest.mark.parametrize("name", ["raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt"])
def test_download_buttons_fetch_with_the_key_and_save_the_file(open_page, fake, name):
    """Fiecare buton descarcă fișierul cu fetch + cheie în antet (Blob), sub numele lui; adresa nu conține cheia."""
    page, probe = open_page()
    run_id = finish_and_open_report(page, fake)
    before = len(fake.api_requests())
    with page.expect_download() as info:
        page.click(f"button[data-file='{name}']")
    download = info.value
    assert download.suggested_filename == name
    assert Path(download.path()).read_bytes() == fake.files[name]
    request = [r for r in fake.api_requests()[before:] if r["path"] == f"/api/runs/{run_id}/files/{name}"]
    assert len(request) == 1 and request[0]["headers"]["x-app-token"] == fake.token
    assert fake.token not in request[0]["target"] and "?" not in request[0]["target"]
    assert "A pornit descărcarea fișierului " + name in page.inner_text("#dl-msg")
    assert probe_problems(probe) == {}


def test_a_failed_download_shows_the_servers_message(open_page, fake):
    """Dacă aplicația refuză fișierul, mesajul ei apare lângă butoane și pagina rămâne utilizabilă."""
    page, _ = open_page()
    run_id = finish_and_open_report(page, fake)
    fake.fail_next[("GET", f"/api/runs/{run_id}/files/produse.csv")] = (404, "file_missing", "Fișierul produse.csv nu există pentru această rulare.")
    page.click("button[data-file='produse.csv']")
    wait_js(page, "document.getElementById('dl-msg').textContent.includes('nu există pentru această rulare')")
    assert "is-bad" in page.get_attribute("#dl-msg", "class")
    assert current_screen(page) == "done"


def test_run_again_returns_to_start_and_the_finished_run_does_not_come_back(open_page, fake):
    """„Rulează din nou” duce la start; starea „gata” rămasă la aplicație nu readuce raportul la următoarea interogare."""
    page, probe = open_page()
    finish_and_open_report(page, fake)
    page.click("#btn-again")
    wait_screen(page, "ready")
    page.wait_for_timeout(3200)
    assert current_screen(page) == "ready"
    assert page.locator("#report-root").inner_html() == "", "raportul vechi a fost dezmontat"
    assert page.locator("#hist-list li").count() == len(fake.runs), "lista de rulări s-a reîncărcat, cu rularea nouă prima"
    assert probe_problems(probe) == {}


def test_a_second_run_after_the_first_one_shows_its_own_report(open_page, fake):
    """După o rulare terminată și închisă, o rulare nouă trece iar prin „în lucru” și ajunge la raportul ei."""
    page, _ = open_page()
    first = finish_and_open_report(page, fake)
    page.click("#btn-again")
    wait_screen(page, "ready")
    second = start_run(page, fake)
    assert second != first
    fake.finish_run(second)
    wait_screen(page, "done")
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    assert any(r["path"] == f"/api/runs/{second}/analysis" for r in fake.api_requests())


def test_the_report_is_unmounted_when_the_screen_is_left(open_page, fake):
    """La ieșirea din ecranul cu raport, componenta se dezmontează (rădăcina rămâne goală, fără clasa emag-dash)."""
    page, _ = open_page()
    finish_and_open_report(page, fake)
    page.click("#btn-again")
    wait_screen(page, "ready")
    assert page.evaluate("document.getElementById('report-root').className") == "report"
    assert page.evaluate("document.getElementById('report-root').childElementCount") == 0


def test_a_missing_report_shows_an_error_message_not_a_blank_screen(open_page, fake):
    """Dacă analiza nu poate fi citită, ecranul spune de ce și rămâne utilizabil (butonul de întoarcere funcționează)."""
    page, _ = open_page()
    run_id = start_run(page, fake)
    fake.fail_next[("GET", f"/api/runs/{run_id}/analysis")] = (404, "run_not_found", "Rularea cerută nu mai există.")
    fake.finish_run(run_id)
    wait_screen(page, "done")
    wait_js(page, "document.getElementById('report-status').textContent.includes('Rularea cerută nu mai există.')")
    assert "is-bad" in page.get_attribute("#report-status", "class")
    page.click("#btn-again")
    wait_screen(page, "ready")


# ---------- (e) eroare ----------

def test_error_screen_shows_the_servers_message_as_text_and_a_way_out(open_page, fake):
    """Eroarea: mesajul aplicației (ca text, nu HTML), „ce faci acum”, link către FAQ care se deschide, întoarcere la start."""
    page, probe = open_page()
    start_run(page, fake)
    nasty = "Nu te-ai logat în timpul alocat <img src=x onerror=alert(1)> pornește din nou."
    fake.set_state(state="error", error={"code": "login_timeout", "message": nasty})
    wait_screen(page, "error")
    assert page.inner_text("#error-message") == nasty
    assert page.locator("#error-message img").count() == 0
    wait_js(page, "document.activeElement.id === 'error-t'")
    assert page.title() == "Analiza s-a oprit din cauza unei probleme · Cheltuieli eMAG"
    capture(page, "ecran_eroare")
    page.click("#screen-error [data-faq-link]")
    assert page.evaluate("document.getElementById('faq-nu-merge').open") is True
    assert page.evaluate("document.activeElement.parentElement.id") == "faq-nu-merge"
    page.click("#screen-error [data-action='back']")
    wait_screen(page, "ready")
    page.wait_for_timeout(3200)
    assert current_screen(page) == "ready", "eroarea închisă nu revine la următoarea interogare"
    assert probe_problems(probe) == {}


def test_error_without_a_message_uses_the_state_message_or_a_fallback(open_page, fake):
    """Fără mesaj de eroare, pagina arată mesajul stării sau un text de rezervă în română."""
    page, _ = open_page()
    start_run(page, fake)
    fake.set_state(state="error", error=None, message="")
    wait_screen(page, "error")
    assert "Jurnalul din folderul logs" in page.inner_text("#error-message")


# ---------- (a) închis ----------

def test_the_page_opened_from_a_folder_asks_for_the_local_app(browser, fake):
    """Deschisă din file://, pagina arată „are nevoie de aplicația locală”, cu porneste.bat și link spre explicații; nicio cerere de rețea."""
    from tests.app_ui_support import INTERFACE_DIR, open_app
    context, page, probe = open_app(browser, fake, url=(INTERFACE_DIR / "aplicatie.html").as_uri())
    try:
        wait_screen(page, "closed-needs-app")
        assert page.inner_text("#needs-app-t") == "Pagina asta are nevoie de aplicația locală"
        assert "porneste.bat" in page.inner_text("#screen-closed-needs-app")
        assert page.get_attribute("#screen-closed-needs-app a[href='index.html']", "target") == "_blank"
        assert page.locator("#screen-closed-needs-app [data-action='recheck']").is_hidden()
        assert [u for u in probe.urls if u.startswith("http")] == [], "din folder nu se face nicio cerere HTTP"
        assert fake.requests == []
        capture(page, "ecran_inchis_fara_aplicatie")
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_the_app_stopping_while_the_page_is_open_shows_the_stopped_screen(open_page, fake):
    """Dacă aplicația se oprește cât pagina e deschisă, după câteva încercări apare „Aplicația s-a oprit”, cu „Verifică din nou”."""
    page, _ = open_page()
    assert current_screen(page) == "ready"
    fake.stop()
    wait_screen(page, "closed-stopped", timeout=15000)
    assert page.inner_text("#stopped-t") == "Aplicația s-a oprit"
    assert "porneste.bat" in page.inner_text("#screen-closed-stopped .lead")
    wait_js(page, "document.activeElement.id === 'stopped-t' || document.activeElement === document.body")
    capture(page, "ecran_aplicatia_s_a_oprit")
    page.click("#screen-closed-stopped [data-action='recheck']")
    wait_js(page, "document.getElementById('app-live').textContent.includes('încă nu răspunde')")
    assert current_screen(page) == "closed-stopped"


def test_close_the_app_button_stops_it_and_shows_the_closed_screen(open_page, fake):
    """„Închide aplicația” cere oprirea; pagina spune că aplicația a fost închisă și nu mai interoghează nimic."""
    page, _ = open_page()
    page.click("#btn-shutdown")
    wait_screen(page, "closed-user")
    assert fake.shutdown_requested
    assert page.inner_text("#user-closed-t") == "Aplicația a fost închisă"
    count = len(fake.api_requests())
    page.wait_for_timeout(3200)
    assert len(fake.api_requests()) == count, "după închidere pagina nu mai interoghează aplicația"


def test_a_connection_failure_right_after_the_shutdown_request_still_means_closed(open_page, fake):
    """Aplicația răspunde la oprire și se închide imediat: pagina nu arată eroare, ci „închisă”."""
    page, probe = open_page()
    page.click("#btn-shutdown")
    wait_screen(page, "closed-user")
    assert [p for p in probe.page_errors] == []


# ---------- gata de start: sesiune și rulări anterioare ----------

def test_session_status_without_a_saved_session(open_page, fake):
    """Fără sesiune salvată: „Nu există sesiune salvată” și niciun buton de ștergere."""
    fake.session_saved = False
    fake.set_state(session_saved=False)
    page, _ = open_page()
    assert page.inner_text("#session-status") == "Nu există sesiune salvată"
    assert page.locator("#btn-session-delete").is_hidden()


def test_deleting_the_session_needs_the_word_da_typed_in_the_page(open_page, fake):
    """Ștergerea: panou în pagină (nu confirm()), cuvânt greșit = mesaj și nimic trimis, „da” sau „DA” = trimis ca DA, starea se actualizează."""
    page, probe = open_page()
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.click("#btn-session-delete")
    assert page.get_attribute("#btn-session-delete", "aria-expanded") == "true"
    assert page.evaluate(ACTIVE_ELEMENT_JS) == "session-word"
    page.fill("#session-word", "nu")
    page.click("#btn-session-confirm")
    assert "Scrie DA" in page.inner_text("#session-msg") and fake.deleted_sessions == 0
    assert page.get_attribute("#session-word", "aria-invalid") == "true"
    page.fill("#session-word", " da ")
    page.keyboard.press("Enter")
    wait_js(page, "document.getElementById('session-status').textContent === 'Nu există sesiune salvată'")
    assert fake.deleted_sessions == 1
    sent = [r for r in fake.api_requests() if r["path"] == "/api/session/delete"]
    assert len(sent) == 1
    assert page.locator("#btn-session-delete").is_hidden() and page.locator("#session-confirm").is_hidden()
    assert page.evaluate(ACTIVE_ELEMENT_JS) == "session-status", "focusul nu se pierde când butonul dispare"
    assert page.inner_text("#session-note") == SESSION_DELETED_MESSAGE, "mesajul aplicației (ce s-a șters, ce urmează) apare sub starea sesiunii"
    live_text_contains(page, "Sesiunea eMAG salvată a fost ștearsă")
    assert dialogs == [], "confirmarea e în pagină, nu cu fereastra confirm()"
    assert probe_problems(probe) == {}


def test_cancelling_the_session_deletion_closes_the_panel_and_returns_focus(open_page, fake):
    """„Renunț” închide panoul, nu șterge nimic și duce focusul înapoi pe butonul „Șterge sesiunea salvată”."""
    page, _ = open_page()
    page.click("#btn-session-delete")
    page.click("#btn-session-cancel")
    assert page.locator("#session-confirm").is_hidden()
    assert page.evaluate(ACTIVE_ELEMENT_JS) == "btn-session-delete"
    assert fake.deleted_sessions == 0


def test_a_session_deletion_error_is_shown_in_the_panel(open_page, fake):
    """Dacă aplicația nu poate șterge (ex. browserul programului e deschis), mesajul ei apare în panou, iar panoul rămâne deschis."""
    page, _ = open_page()
    fake.fail_next[("POST", "/api/session/delete")] = (409, "profile_in_use", "Închide fereastra de browser a programului și încearcă din nou.")
    page.click("#btn-session-delete")
    page.fill("#session-word", "DA")
    page.click("#btn-session-confirm")
    wait_js(page, "document.getElementById('session-msg').textContent.includes('Închide fereastra de browser')")
    assert page.locator("#session-confirm").is_visible()
    assert page.inner_text("#session-status") == "Ești conectat de data trecută"


def test_history_lists_the_runs_and_marks_demo_and_missing_reports(open_page, fake):
    """Rulările: data, „Demo”, număr de comenzi, cât ai plătit (sau, la o analiză veche, cât ai păstrat); „Deschide” doar unde există raport."""
    page, _ = open_page()
    rows = page.locator("#hist-list li")
    assert rows.count() == 3
    first = rows.nth(0).inner_text()
    assert "5 oct. 2026, 11:07" in first and "DEMO" in first.upper() and "177 de comenzi" in first and "plătit: 12.000,00\xa0Lei" in first
    assert "păstrat:" not in first, "o analiză nouă arată banii plătiți, nu valoarea de listă"
    assert "25 de comenzi" in rows.nth(1).inner_text() and "păstrat: 987,65\xa0Lei" in rows.nth(1).inner_text()  # analiză veche, fără spent_bani
    assert "fără raport" in rows.nth(2).inner_text() and rows.nth(2).locator("button").count() == 0
    assert page.inner_text("#hist-status") == "3 rulări, cele mai noi primele."


def test_history_empty_and_error_states(open_page, fake):
    """Fără rulări: mesaj clar. Cu eroare la citire: mesajul aplicației și „Încearcă din nou”, care funcționează."""
    fake.runs = []
    fake.fail_next[("GET", "/api/runs")] = (500, "internal", "Nu pot citi folderul iesiri.")
    page, _ = open_page()
    wait_js(page, "document.getElementById('hist-status').textContent.includes('Nu pot citi folderul iesiri.')")
    assert page.locator("#hist-retry").is_visible()
    page.click("#hist-retry")
    wait_js(page, "document.getElementById('hist-status').textContent.startsWith('Nu ai rulări anterioare')")
    assert page.locator("#hist-retry").is_hidden()


def test_history_shows_ten_runs_and_a_show_more_button(open_page, fake):
    """O listă lungă arată primele 10 rânduri și „Arată încă”, care adaugă restul."""
    fake.runs = [{"id": f"2026-09-{day:02d}_10-00-00", "created_at": f"2026-09-{day:02d} 10:00:00", "kind": "real",
                  "orders": day, "kept_bani": day * 100, "has_report": True} for day in range(28, 16, -1)]
    page, _ = open_page()
    assert page.locator("#hist-list li").count() == 10
    page.click("#hist-more")
    assert page.locator("#hist-list li").count() == 12 and page.locator("#hist-more").is_hidden()


def test_opening_an_old_run_shows_its_report_and_back_returns_to_start(open_page, fake):
    """„Deschide” aduce analiza rulării vechi; titlul spune data, butonul spune „Înapoi la început”; întoarcerea dezmontează raportul."""
    page, probe = open_page()
    page.click("button[aria-label^='Deschide raportul din 5 oct. 2026, 11:07']")
    wait_screen(page, "done")
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    assert page.inner_text("#done-t") == "Raport din 5 oct. 2026, 11:07"
    assert page.inner_text("#btn-again") == "Înapoi la început"
    assert page.inner_text("#done-sub") == "Rulare de probă, cu date inventate."
    assert "inventate" in page.inner_text("#report-root .ed-banner")
    assert any(r["path"] == "/api/runs/2026-10-05_11-07-55_demo/analysis" for r in fake.api_requests())
    with page.expect_download() as info:
        page.click("button[data-file='rezumat.txt']")
    assert info.value.suggested_filename == "rezumat.txt"
    assert any(r["path"] == "/api/runs/2026-10-05_11-07-55_demo/files/rezumat.txt" for r in fake.api_requests())
    page.click("#btn-again")
    wait_screen(page, "ready")
    assert page.evaluate("document.getElementById('report-root').childElementCount") == 0
    assert probe_problems(probe) == {}


# ---------- focus: nu se fură ----------

def test_focus_is_not_stolen_from_the_faq_when_the_screen_changes_by_itself(open_page, fake):
    """Dacă omul citește FAQ-ul și o rulare începe în altă parte, ecranul se schimbă, dar focusul rămâne unde era; schimbarea se anunță."""
    page, _ = open_page()
    page.focus("#faq-durata summary")
    fake.set_state(state="fetching_orders", run_id="2026-10-05_11-59-00", started_at="2026-10-05 11:59:00")
    wait_screen(page, "working")
    assert page.evaluate("document.activeElement.parentElement.id") == "faq-durata"
    live_text_contains(page, "Analiza e în lucru")


# ---------- linkuri spre site-ul explicativ ----------

def test_docs_links_are_replaced_by_the_way_to_open_the_site_when_served_by_the_app(open_page):
    """Servită de aplicație, pagina nu trimite spre index.html (ar da 404: aplicația servește doar ce cere aplicatie.html): arată deschide_interfata.bat."""
    page, _ = open_page()
    assert page.evaluate("document.documentElement.dataset.served") == "app"
    assert page.evaluate("[...document.querySelectorAll('.docs-link')].every((a) => getComputedStyle(a).display === 'none')")
    page.click("#faq-ce-citeste summary")
    alt = page.locator("#faq-ce-citeste .docs-alt")
    assert alt.is_visible() and "deschide_interfata.bat" in alt.inner_text()
    assert page.locator("footer .docs-alt").is_visible()


def test_docs_links_work_when_the_page_is_opened_from_a_folder(browser, fake):
    """Deschisă din folder, pagina arată linkul spre index.html (se deschide în filă nouă, din același folder) și ascunde textul alternativ."""
    from tests.app_ui_support import INTERFACE_DIR, open_app
    context, page, _ = open_app(browser, fake, url=(INTERFACE_DIR / "aplicatie.html").as_uri(), wait_for=None)
    try:
        wait_screen(page, "closed-needs-app")
        assert page.evaluate("document.documentElement.dataset.served") == "file"
        link = page.locator("#screen-closed-needs-app .docs-link")
        assert link.is_visible() and page.locator("#screen-closed-needs-app .docs-alt").is_hidden()
        with context.expect_page() as opened:
            link.click()
        assert opened.value.url.endswith("/interfata/index.html")
    finally:
        context.close()


# ---------- FAQ ----------

@pytest.mark.parametrize("item", EXPECTED_FAQ)
def test_every_faq_item_opens_with_a_click_and_closes_with_the_keyboard(open_page, item):
    """Fiecare întrebare se deschide cu clic (răspunsul devine vizibil) și se închide cu Enter pe titlu."""
    page, _ = open_page()
    page.click(f"#{item} summary")
    assert page.evaluate(f"document.getElementById('{item}').open") is True
    assert page.locator(f"#{item} .faq__body").is_visible()
    page.keyboard.press("Enter")
    assert page.evaluate(f"document.getElementById('{item}').open") is False


def test_a_faq_hash_opens_the_question(open_page):
    """O adresă cu #faq-... (la încărcare sau la schimbarea hash-ului) deschide întrebarea și mută focusul pe titlul ei."""
    page, _ = open_page()
    page.evaluate("location.hash = '#faq-durata'")
    wait_js(page, "document.getElementById('faq-durata').open === true")
    assert page.evaluate("document.activeElement.parentElement.id") == "faq-durata"


def test_faq_shows_the_measured_duration_with_its_caveat(open_page):
    """La „Cât durează?” apare durata măsurată, cu precizarea că a fost măsurată o singură dată."""
    page, _ = open_page()
    page.click("#faq-durata summary")
    text = page.inner_text("#faq-durata .faq__body")
    assert "între 2 și 3\xa0minute" in text and "măsurat o singură dată" in text
