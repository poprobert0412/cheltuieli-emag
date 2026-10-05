"""Teste pentru raportarea progresului și anularea cooperantă (progress.py și cuiele din browser, scrapere, colector, pipeline).

Fără browser: contextul, pagina și Playwright sunt obiecte false care imită doar ce folosește codul. Valorile sunt inventate.
Verifică: raportorul implicit e inactiv (linia de comandă nu se schimbă), fazele și „făcute din total” ajung la raportor,
anularea oprește descărcările și așteptarea login-ului, iar browserul se închide curat la anulare.
"""

import asyncio
import json
from pathlib import Path

import pytest
import playwright.async_api
from playwright.async_api import Error as PlaywrightError

from emag_spend import browser_session, emag_collector, order_list_scraper, page_fetcher, return_list_scraper, run_pipeline, settings, site_demo_writer
from emag_spend.progress import (
    NO_PROGRESS, PHASE_ANALYZING, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_WAITING_LOGIN, PIPELINE_PHASES, Progress, RunCancelled,
)


class RecordingProgress(Progress):
    """Raportor activ de test: notează fiecare apel și cere oprirea după `cancel_after_advances` pași (None = niciodată)."""

    def __init__(self, cancel_after_advances: int | None = None):
        self.events: list[tuple] = []
        self.cancel_after_advances = cancel_after_advances
        self.advances = 0
        self.cancelled = False

    def phase(self, name, total=None):
        self.events.append(("phase", name, total))

    def advance(self, done, total=None):
        self.events.append(("advance", done, total))
        self.advances += 1
        if self.cancel_after_advances is not None and self.advances > self.cancel_after_advances:
            self.cancelled = True

    def message(self, text):
        self.events.append(("message", text))

    def cancel_requested(self):
        return self.cancelled


def _run(coro):
    return asyncio.run(coro)


# ---------- raportorul implicit ----------

def test_the_default_reporter_is_inactive_and_never_cancels():
    """Raportorul implicit nu face nimic și nu cere niciodată oprirea: fără el, linia de comandă s-ar schimba."""
    reporter = Progress()
    assert reporter.phase(PHASE_ANALYZING, 3) is None and reporter.advance(1, 3) is None and reporter.message("x") is None
    assert reporter.cancel_requested() is False
    reporter.raise_if_cancelled()  # nu ridică nimic
    assert isinstance(NO_PROGRESS, Progress) and not NO_PROGRESS.cancel_requested()


def test_raise_if_cancelled_raises_run_cancelled_with_a_romanian_message_only_when_asked():
    """Când oprirea e cerută, `raise_if_cancelled` ridică RunCancelled cu mesaj în română; altfel tace."""
    class Asking(Progress):
        def cancel_requested(self):
            return True

    with pytest.raises(RunCancelled, match="oprită la cererea ta"):
        Asking().raise_if_cancelled()


def test_phase_names_are_exactly_the_states_of_the_api_contract():
    """Fazele pipeline-ului sunt chiar stările din API-ul aplicației (brief, pct. 6): aplicația nu traduce nimic între ele."""
    assert PIPELINE_PHASES == ("waiting_login", "fetching_orders", "fetching_returns", "analyzing")
    assert (PHASE_WAITING_LOGIN, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_ANALYZING) == PIPELINE_PHASES


# ---------- descărcarea paginilor ----------

class FakeResponse:
    def __init__(self, status=200, text="ok", url="https://www.emag.ro/x"):
        self.status, self._text, self.url = status, text, url

    async def text(self):
        return self._text


class CountingContext:
    """Context fals de browser: numără descărcările; `request` e chiar obiectul însuși."""

    def __init__(self):
        self.calls = 0
        self.request = self

    async def get(self, url, timeout=None):
        self.calls += 1
        await asyncio.sleep(0)  # cedează bucla, ca și o cerere reală
        return FakeResponse()


def test_fetch_each_reports_zero_then_every_download_with_the_total():
    """fetch_each anunță 0 din total la început și apoi fiecare pagină descărcată, până la total."""
    progress = RecordingProgress()
    out = _run(page_fetcher.fetch_each(CountingContext(), [f"/p/{i}" for i in range(4)], lambda p, h: p, "test", progress))
    assert out == ["/p/0", "/p/1", "/p/2", "/p/3"]
    advances = [event[1:] for event in progress.events if event[0] == "advance"]
    assert advances[0] == (0, 4) and advances[-1] == (4, 4) and len(advances) == 5
    assert [a[0] for a in advances] == sorted(a[0] for a in advances), "numărul de pagini făcute nu are voie să scadă"


def test_cancelling_stops_the_downloads_and_leaves_no_task_running():
    """După cererea de oprire nu se mai pornește nicio descărcare, RunCancelled iese la apelant, iar sarcinile rămase sunt oprite (browserul se poate închide)."""
    context = CountingContext()
    progress = RecordingProgress(cancel_after_advances=3)
    paths = [f"/p/{i}" for i in range(60)]

    async def scenario():
        with pytest.raises(RunCancelled):
            await page_fetcher.fetch_each(context, paths, lambda p, h: p, "test", progress)
        await asyncio.sleep(0.05)
        return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    leftover = _run(scenario())
    assert context.calls < len(paths), "toate cele 60 de pagini s-au descărcat deși utilizatorul a cerut oprirea"
    assert context.calls <= 3 + settings.FETCH_CONCURRENCY + 1, f"după oprire au mai pornit descărcări: {context.calls}"
    assert leftover == [], f"au rămas sarcini în fundal după anulare: {leftover}"


def test_a_failing_download_also_cancels_the_other_downloads():
    """La prima eroare (aici: sesiune expirată) descărcările celelalte se opresc; înainte rămâneau în fundal pe un browser care se închidea."""
    class OneExpires(CountingContext):
        async def get(self, url, timeout=None):
            self.calls += 1
            await asyncio.sleep(0)
            if url.endswith("/p/1"):
                return FakeResponse(url="https://auth.emag.ro/user/login")
            await asyncio.sleep(0.2)
            return FakeResponse()

    async def scenario():
        with pytest.raises(page_fetcher.SessionExpired):
            await page_fetcher.fetch_each(OneExpires(), [f"/p/{i}" for i in range(3)], lambda p, h: p, "test")
        await asyncio.sleep(0)
        return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    assert _run(scenario()) == []


# ---------- listele ----------

class FakeListPage:
    """Pagină de listă de comenzi: fiecare `goto` schimbă pagina curentă."""

    def __init__(self, pages, last_page):
        self.pages, self.last_page, self.current, self.visited = pages, last_page, 1, []

    async def goto(self, url, wait_until=None):
        marker = "/history/shopping/"
        self.current = int(url.split(marker)[1].split("?")[0]) if marker in url else 1
        self.visited.append(self.current)

    async def evaluate(self, script):
        return list(self.pages.get(self.current, [])) if "shoppingdetails" in script else self.last_page


@pytest.fixture
def fast_lists(monkeypatch):
    """Fără pauze reale în scrapere: testele nu așteaptă secunde."""
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(order_list_scraper.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(return_list_scraper.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(settings, "LIST_RENDER_TIMEOUT_SECONDS", 0.3)


def test_order_list_stops_between_pages_when_cancelled(fast_lists):
    """Oprirea cerută după prima pagină oprește parcurgerea listei înainte de pagina 2."""
    page = FakeListPage({1: ["10", "9"], 2: ["8"], 3: ["7"]}, last_page=3)
    progress = RecordingProgress()
    original = page.goto

    async def goto_then_cancel(url, wait_until=None):
        await original(url, wait_until)
        progress.cancelled = True

    page.goto = goto_then_cancel
    with pytest.raises(RunCancelled):
        _run(order_list_scraper.collect_order_ids(page, progress=progress))
    assert page.visited == [1], "după oprire nu mai are voie să deschidă pagina 2"


def test_order_list_tells_the_user_which_page_it_is_on(fast_lists):
    """La paginile următoare, mesajul de progres spune pagina curentă și totalul cunoscut."""
    page = FakeListPage({1: ["10", "9"], 2: ["8", "7"]}, last_page=2)
    progress = RecordingProgress()
    _run(order_list_scraper.collect_order_ids(page, progress=progress))
    messages = [e[1] for e in progress.events if e[0] == "message"]
    assert any("pagina 2 din 2" in text for text in messages), messages


def test_return_list_stops_before_the_first_load_more_click_when_cancelled(fast_lists):
    """Oprirea cerută în lista de retururi oprește apăsările pe „Vezi mai mult”."""
    class Page:
        clicks = 0

        async def goto(self, url, wait_until=None):
            return None

        async def wait_for_selector(self, selector, timeout=None):
            return None

        async def evaluate(self, script):
            return ["/user/return-history/1/1"]

        def locator(self, selector):
            page = self

            class Button:
                first = None

                async def count(self):
                    return 1

                async def is_visible(self):
                    return True

                async def click(self):
                    page.clicks += 1

            button = Button()
            button.first = button
            return button

    progress = RecordingProgress()
    progress.cancelled = True
    page = Page()
    with pytest.raises(RunCancelled):
        _run(return_list_scraper.collect_return_paths(page, progress))
    assert page.clicks == 0


# ---------- login ----------

class LoggedOutPage:
    """Pagină care nu e niciodată logată: `evaluate` întoarce un text fără «Log out»."""

    def __init__(self):
        self.visits = 0

    async def goto(self, url, wait_until=None):
        self.visits += 1

    async def evaluate(self, script):
        return "Autentificare"


def test_waiting_for_login_announces_the_phase_and_stops_when_cancelled(monkeypatch):
    """În așteptarea login-ului: faza waiting_login apare la raportor, iar oprirea cerută iese cu RunCancelled în loc să aștepte tot timpul."""
    monkeypatch.setattr(settings, "LOGIN_POLL_SECONDS", 0.01)
    progress = RecordingProgress()

    original = progress.message

    def message_then_cancel(text):
        original(text)
        progress.cancelled = True  # utilizatorul apasă „Oprește” cât așteaptă login-ul

    progress.message = message_then_cancel
    # termen scurt (3 s): dacă anularea nu s-ar verifica în așteptare, testul ar pica repede cu LoginTimeout, nu ar aștepta zece minute
    with pytest.raises(RunCancelled):
        _run(browser_session.ensure_logged_in(LoggedOutPage(), wait_seconds=3, progress=progress))
    assert ("phase", PHASE_WAITING_LOGIN, None) in progress.events


def test_login_timeout_keeps_the_exact_message_and_stays_a_runtime_error(monkeypatch):
    """Expirarea login-ului ridică LoginTimeout, tot RuntimeError cu mesajul vechi: linia de comandă afișează exact ce afișa."""
    monkeypatch.setattr(settings, "LOGIN_POLL_SECONDS", 0)
    with pytest.raises(browser_session.LoginTimeout) as error:
        _run(browser_session.ensure_logged_in(LoggedOutPage(), wait_seconds=0))
    assert isinstance(error.value, RuntimeError)
    assert str(error.value) == "nu te-ai logat în timpul alocat; rulează din nou scriptul"


def test_an_active_session_does_not_announce_a_login_phase():
    """Cu sesiunea deja activă nu apare faza de login: aplicația trece direct la comenzi."""
    class LoggedInPage(LoggedOutPage):
        async def evaluate(self, script):
            return "Comenzile mele Log out"

    progress = RecordingProgress()
    _run(browser_session.ensure_logged_in(LoggedInPage(), progress=progress))
    assert not [event for event in progress.events if event[0] == "phase"]


# ---------- browserul ----------

class FakeBrowserContext:
    """Context de browser fals: reține dacă a fost închis și dă o pagină."""

    def __init__(self):
        self.closed = False
        self.pages = [object()]

    async def close(self):
        self.closed = True


class FakePlaywrightManager:
    """`async_playwright()` fals: lansarea întoarce contextul fals sau ridică eroarea dată."""

    def __init__(self, context=None, launch_error=None):
        self.context, self.launch_error = context, launch_error
        self.chromium = self

    async def launch_persistent_context(self, *args, **kwargs):
        if self.launch_error:
            raise self.launch_error
        return self.context

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def test_the_browser_closes_cleanly_when_the_run_is_cancelled(monkeypatch, tmp_path):
    """La RunCancelled ridicat în așteptarea login-ului, contextul browserului e închis (altfel rămânea o fereastră Edge agățată) și excepția ajunge la apelant."""
    context = FakeBrowserContext()
    monkeypatch.setattr(playwright.async_api, "async_playwright", lambda: FakePlaywrightManager(context))
    monkeypatch.setattr(settings, "PROFILE_DIR", tmp_path / "profil")

    async def cancelled_while_waiting(page, wait_seconds=0, progress=NO_PROGRESS):
        raise RunCancelled("oprit")

    monkeypatch.setattr(browser_session, "ensure_logged_in", cancelled_while_waiting)

    async def scenario():
        async with browser_session.logged_in_browser():
            pytest.fail("nu trebuia să ajungă în corpul blocului: login-ul a fost anulat")

    with pytest.raises(RunCancelled):
        _run(scenario())
    assert context.closed, "contextul browserului nu s-a închis la anulare"


def test_a_launch_failure_keeps_playwrights_message_and_class_family(monkeypatch, tmp_path):
    """Eroarea de la pornirea browserului devine BrowserLaunchFailed, tot PlaywrightError și cu același mesaj: linia de comandă afișează la fel ca înainte."""
    original = PlaywrightError("BrowserType.launch_persistent_context: eroare inventată\nCall log:\n  - detaliu")
    monkeypatch.setattr(playwright.async_api, "async_playwright", lambda: FakePlaywrightManager(launch_error=original))
    monkeypatch.setattr(settings, "PROFILE_DIR", tmp_path / "profil")

    async def scenario():
        async with browser_session.logged_in_browser():
            pytest.fail("nu trebuia să ajungă în corpul blocului")

    with pytest.raises(browser_session.BrowserLaunchFailed) as error:
        _run(scenario())
    assert isinstance(error.value, PlaywrightError) and str(error.value) == str(original)
    assert error.value.__cause__ is original


# ---------- colectorul ----------

def test_collect_all_announces_orders_then_returns_and_passes_the_reporter_down(monkeypatch):
    """Colectorul anunță fazele în ordine (comenzi, retururi) și dă același raportor scraperelor și descărcătorului."""
    seen = {}

    class FakeBrowser:
        def __init__(self, progress):
            seen["browser_progress"] = progress

        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, *exc_info):
            return False

    async def fake_order_ids(page, max_orders=None, progress=NO_PROGRESS):
        seen["orders_progress"] = progress
        return ["111", "222"]

    async def fake_return_paths(page, progress=NO_PROGRESS):
        seen["returns_progress"] = progress
        return ["/user/return-history/1/5"]

    async def fake_fetch_each(context, paths, handler, label, progress=NO_PROGRESS):
        seen.setdefault("fetch_progress", []).append((label, len(paths), progress))
        return []

    monkeypatch.setattr(emag_collector, "logged_in_browser", FakeBrowser)
    monkeypatch.setattr(emag_collector, "collect_order_ids", fake_order_ids)
    monkeypatch.setattr(emag_collector, "collect_return_paths", fake_return_paths)
    monkeypatch.setattr(emag_collector, "fetch_each", fake_fetch_each)
    progress = RecordingProgress()
    _run(emag_collector.collect_all(progress=progress))
    phases = [event[1] for event in progress.events if event[0] == "phase"]
    assert phases == [PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS]
    assert all(seen[key] is progress for key in ("browser_progress", "orders_progress", "returns_progress"))
    assert [(label, count) for label, count, _ in seen["fetch_progress"]] == [("comenzi", 2), ("retururi", 1)]
    assert all(given is progress for _, _, given in seen["fetch_progress"])


# ---------- pipeline ----------

@pytest.fixture
def isolated_site_file(tmp_path, monkeypatch):
    """demo-data.js al site-ului mutat în folderul temporar: testul nu atinge fișierul urmărit de git."""
    target = tmp_path / "site" / "demo-data.js"
    monkeypatch.setattr(site_demo_writer, "DEMO_DATA_JS_FILE", target)
    return target


def test_a_demo_run_announces_the_analysis_phase(tmp_path, isolated_site_file):
    """La demo (fără browser) raportorul primește faza analyzing, ca aplicația să arate un pas real."""
    progress = RecordingProgress()
    run_dir = run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=tmp_path / "out"), progress=progress)
    assert [event[1] for event in progress.events if event[0] == "phase"] == [PHASE_ANALYZING]
    assert (run_dir / "analiza.json").is_file()


def test_the_demo_data_file_is_rewritten_by_default_and_skipped_when_asked(tmp_path, isolated_site_file):
    """Implicit (linia de comandă) demo rescrie demo-data.js; cu update_site_demo_data=False (aplicația) fișierul urmărit de git nu e atins."""
    run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=tmp_path / "out1"))
    assert isolated_site_file.is_file(), "implicit, demo trebuie să rescrie demo-data.js (comportamentul liniei de comandă)"
    isolated_site_file.unlink()
    run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=tmp_path / "out2", update_site_demo_data=False))
    assert not isolated_site_file.exists(), "cu update_site_demo_data=False, rularea nu are voie să rescrie demo-data.js"


def test_a_chosen_folder_name_is_used_and_a_bad_one_is_refused_before_anything_is_written(tmp_path, isolated_site_file):
    """Numele de folder dat dinainte devine folderul rulării; unul care nu e un id valid (ex. cu ..) se refuză fără să creeze nimic."""
    out = tmp_path / "out"
    run_dir = run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=out, run_folder_name="2026-01-02_03-04-05_demo", update_site_demo_data=False))
    assert run_dir == out / "2026-01-02_03-04-05_demo"
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    assert info["demo"] is True
    for bad in ("..", "../x", "2026-13-02_03-04-05", "a", "2026-01-02_03-04-05_DEMO"):
        with pytest.raises(ValueError, match="nu are forma"):
            run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=tmp_path / "out_bad", run_folder_name=bad, update_site_demo_data=False))
    assert not (tmp_path / "out_bad").exists()


def test_the_default_folder_name_is_the_same_format_as_before(tmp_path, isolated_site_file):
    """Fără nume dat, folderul rămâne <data>_<ora> (și _demo la demo), exact ca înainte de aplicația locală."""
    from emag_spend import run_ids

    run_dir = run_pipeline.run(run_pipeline.RunOptions(demo=True, output_dir=tmp_path / "out"))
    parsed = run_ids.parse_run_id(run_dir.name)
    assert parsed is not None and parsed.demo is True
    assert Path(run_dir).parent == tmp_path / "out"
