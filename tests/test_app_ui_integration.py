"""Teste de integrare: pagina aplicatie.html pe serverul REAL (emag_spend/app_server.py), într-un browser real.

Primește: serverul real pornit în acest proces, cu iesiri/ și profilul în foldere TEMPORARE (niciodată cele ale utilizatorului) și,
unde nu trebuie browserul de login, o rulare scenarizată pusă în AppRunner (pipeline propriu: fazele, progresul și erorile le dă testul).
Verifică ecranul de la deschidere până la raport pe o rulare demo REALĂ (fișierele descărcate sunt exact cele de pe disc), mesajele
reale ale aplicației (login, progres, erori traduse în română), anularea, ștergerea sesiunii, oprirea din pagină și ce afirmă FAQ-ul
despre securitatea serverului. Ce NU face: nu pornește niciodată browserul de login eMAG (modul real folosește doar rulări scenarizate).
Se sare dacă emag_spend/app_server.py sau un browser lipsesc.
"""

import http.client
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.app_ui_support import (  # noqa: F401 - fixture-urile se găsesc prin importul lor în modul
    BROWSER_BLOCKED_PORTS, browser, capture, current_screen, open_app, playwright_instance, probe_problems, wait_js, wait_screen,
)

pytest.importorskip("playwright.sync_api")
app_server = pytest.importorskip("emag_spend.app_server")

from emag_spend.app_runner import AppRunner  # noqa: E402 - după importorskip: modulul există doar dacă serverul există
from tests.app_support import FakeUpdateJob  # noqa: E402 - job de actualizare fals: nimic nu iese pe internet
from emag_spend.browser_session import LoginTimeout  # noqa: E402
from emag_spend.page_fetcher import SessionExpired  # noqa: E402
from emag_spend.progress import PHASE_FETCHING_ORDERS, PHASE_WAITING_LOGIN  # noqa: E402

DEMO_RUN_TIMEOUT_MS = 90_000  # o rulare demo durează câteva secunde; pe un calculator încărcat, de câteva ori mai mult
SERVER_STOP_TIMEOUT_S = 20
SESSION_DELETED_PREFIX = "Sesiunea eMAG salvată a fost ștearsă"
PORT_ATTEMPTS = 50  # de câte ori refacem serverul dacă sistemul alege un port pe care browserul îl refuză


class Script:
    """Pipeline scenarizat pentru AppRunner: testul pune pași în coadă, rularea îi execută în firul ei (și poate fi oprită)."""

    def __init__(self):
        """Coada de pași, goală."""
        self.steps: queue.Queue = queue.Queue()

    def __call__(self, options, log_path=None, progress=None):
        """Execută pașii pe rând: ("phase", nume, total), ("advance", făcute, total), ("message", text), ("raise", excepție), ("finish",)."""
        while True:
            progress.raise_if_cancelled()
            try:
                step = self.steps.get(timeout=0.1)
            except queue.Empty:
                continue
            if step[0] == "phase":
                progress.phase(step[1], step[2])
            elif step[0] == "advance":
                progress.advance(step[1], step[2])
            elif step[0] == "message":
                progress.message(step[1])
            elif step[0] == "raise":
                raise step[1]
            else:
                return None

    def put(self, *step) -> None:
        """Adaugă un pas."""
        self.steps.put(step)


@dataclass
class RealApp:
    """Serverul real pornit pentru un test, cu aceeași „față” ca serverul fals (origin, token, page_url), ca open_app să-l poată folosi."""

    server: object
    thread: threading.Thread
    outputs: Path
    profile: Path
    script: Script | None = None
    stop_reasons: list = field(default_factory=list)

    @property
    def origin(self) -> str:
        """http://127.0.0.1:<port>."""
        return f"http://127.0.0.1:{self.server.port}"

    @property
    def token(self) -> str:
        """Cheia de acces a sesiunii serverului."""
        return self.server.token

    def page_url(self, with_token: bool = True, path: str = "/aplicatie.html") -> str:
        """Adresa paginii, cu cheia în fragment dacă se cere."""
        return f"{self.origin}{path}" + (f"#t={self.token}" if with_token else "")


def _new_server(outputs: Path, profile: Path, script: Script | None):
    """Pornește un AppServer cu foldere temporare; îl refac dacă portul ales de sistem e unul blocat de browsere."""
    for _ in range(PORT_ATTEMPTS):
        runner = AppRunner(outputs_dir=outputs, profile_dir=profile, pipeline=script) if script is not None else None
        server = app_server.AppServer(outputs_dir=outputs, profile_dir=profile, runner=runner, idle_seconds=3600, update_job=FakeUpdateJob())
        if server.port not in BROWSER_BLOCKED_PORTS:
            return server
        server.close()
    raise RuntimeError("nu am primit niciun port acceptat de browsere")


@pytest.fixture
def make_app(tmp_path):
    """Fabrică: `make_app(script=None, profile=False)` pornește serverul real (cu rulare scenarizată dacă se dă `script`) și îl oprește la final."""
    started = []

    def _make(script: Script | None = None, profile: bool = False) -> RealApp:
        """Pornește serverul real; `profile=True` pune în folderul profilului un profil de browser fals (cu «Local State» și «Default»)."""
        outputs, profile_dir = tmp_path / "iesiri", tmp_path / "profil"
        if profile:
            (profile_dir / "Default").mkdir(parents=True)
            (profile_dir / "Local State").write_text("{}", encoding="utf-8")
            (profile_dir / "Default" / "Cookies").write_text("inventat", encoding="utf-8")
        server = _new_server(outputs, profile_dir, script)
        app = RealApp(server, threading.Thread(target=lambda: None), outputs, profile_dir, script)
        app.thread = threading.Thread(target=lambda: app.stop_reasons.append(server.serve()), daemon=True)
        app.thread.start()
        started.append(app)
        return app

    yield _make
    for app in started:
        app.server.request_stop(app_server.STOP_SHUTDOWN)
        app.thread.join(SERVER_STOP_TIMEOUT_S)
        app.server.close()


def open_real(browser, app: RealApp, **options):
    """Deschide pagina pe serverul real; întoarce (context, pagină, sondă)."""
    return open_app(browser, app, **options)


def request(app: RealApp, method: str, path: str, headers: dict | None = None, body: bytes | None = None):
    """O cerere HTTP brută spre serverul real (cu Host-ul serverului, dacă nu se dă altul); întoarce (status, antete cu litere mici, corp)."""
    connection = http.client.HTTPConnection("127.0.0.1", app.server.port, timeout=10)
    try:
        sent = {"Host": f"127.0.0.1:{app.server.port}", **(headers or {})}
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


# ---------- rulare demo reală, cap la cap ----------

def test_a_real_demo_run_from_the_start_screen_to_the_downloaded_files(browser, make_app):
    """Start → „Încearcă cu date inventate” → raportul REAL în pagină → fiecare fișier descărcat e identic cu cel de pe disc → lista de rulări îl arată."""
    app = make_app()
    context, page, probe = open_real(browser, app)
    try:
        assert current_screen(page) == "ready"
        assert page.inner_text("#session-status") == "Nu există sesiune salvată"
        assert page.inner_text("#hist-status").startswith("Nu ai rulări anterioare")
        assert app.server.runner.snapshot()["state"] == "idle"
        assert page.inner_text("#app-version") == f"Versiunea {app_server.APP_VERSION}"
        page.click("#btn-demo")
        wait_screen(page, "working")
        wait_screen(page, "done", timeout=DEMO_RUN_TIMEOUT_MS)
        page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
        assert page.locator("#report-root [data-ed-block]").count() >= 8
        assert "inventate" in page.inner_text("#report-root .ed-banner")
        runs = [p for p in app.outputs.iterdir() if p.is_dir()]
        assert len(runs) == 1 and runs[0].name.endswith("_demo")
        for name in ("raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt"):
            with page.expect_download() as info:
                page.click(f"button[data-file='{name}']")
            assert info.value.suggested_filename == name
            assert Path(info.value.path()).read_bytes() == (runs[0] / name).read_bytes() != b""
        capture(page, "integrare_raport_real")
        page.click("#btn-again")
        wait_screen(page, "ready")
        page.wait_for_selector("#hist-list li")
        row = page.locator("#hist-list li").first
        assert row.count() == 1 and "DEMO" in row.inner_text().upper() and "comenzi" in row.inner_text()
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_an_old_run_can_be_opened_from_the_list_on_the_real_server(browser, make_app):
    """După o rulare demo, „Deschide” din lista reală aduce același raport, cu data din numele folderului."""
    app = make_app()
    context, page, probe = open_real(browser, app)
    try:
        page.click("#btn-demo")
        wait_screen(page, "done", timeout=DEMO_RUN_TIMEOUT_MS)
        page.click("#btn-again")
        wait_screen(page, "ready")
        page.click("#hist-list button")
        wait_screen(page, "done")
        page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
        assert page.inner_text("#done-t").startswith("Raport din ")
        assert page.inner_text("#btn-again") == "Înapoi la început"
        assert probe_problems(probe) == {}
    finally:
        context.close()


# ---------- rulări scenarizate: mesajele reale ale aplicației ----------

def test_real_login_progress_and_error_messages_reach_the_page(browser, make_app):
    """Fazele, contorul și o eroare de login, produse de AppRunner real: login, „Comenzi: 325 din 416”, mesajul de eroare tradus în română."""
    script = Script()
    app = make_app(script)
    context, page, probe = open_real(browser, app)
    try:
        page.click("#btn-start")
        wait_screen(page, "working")
        script.put("phase", PHASE_WAITING_LOGIN, None)
        page.wait_for_selector("#work-callout[data-kind='login']")
        script.put("phase", PHASE_FETCHING_ORDERS, None)
        script.put("message", "Caut comenzile în cont: pagina 2 din 5")
        wait_js(page, "document.getElementById('work-detail').textContent === 'Caut comenzile în cont: pagina 2 din 5'")
        script.put("phase", PHASE_FETCHING_ORDERS, 416)
        script.put("advance", 325, 416)
        wait_js(page, "document.getElementById('progress-label').textContent === 'Comenzi: 325 din 416'")
        assert page.evaluate("[...document.querySelectorAll('#steps .step')].map((e) => e.dataset.status)") == ["done", "active", "pending", "pending"]
        capture(page, "integrare_progres_real")
        script.put("raise", LoginTimeout("timp depășit"))
        wait_screen(page, "error")
        message = page.inner_text("#error-message")
        assert message.startswith("Nu te-ai logat în cele ") and "Pornește analiza" in message
        capture(page, "integrare_eroare_reala")
        page.click("#screen-error [data-action='back']")
        wait_screen(page, "ready")
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_real_session_expired_message(browser, make_app):
    """O sesiune expirată în timpul citirii apare cu mesajul real al aplicației, în română."""
    script = Script()
    app = make_app(script)
    context, page, _ = open_real(browser, app)
    try:
        page.click("#btn-start")
        wait_screen(page, "working")
        script.put("raise", SessionExpired("redirecționat la login"))
        wait_screen(page, "error")
        assert "Sesiunea eMAG a expirat în timpul citirii" in page.inner_text("#error-message")
    finally:
        context.close()


def test_real_cancel_stops_the_run_and_the_page_shows_it(browser, make_app):
    """„Oprește” → aplicația cere oprirea cooperantă → starea „cancelled” → ecranul „Analiza a fost oprită”."""
    script = Script()
    app = make_app(script)
    context, page, probe = open_real(browser, app)
    try:
        page.click("#btn-start")
        wait_screen(page, "working")
        script.put("phase", PHASE_WAITING_LOGIN, None)
        page.wait_for_selector("#work-callout[data-kind='login']")
        page.click("#btn-cancel")
        wait_screen(page, "cancelled", timeout=15000)
        assert page.inner_text("#cancelled-t") == "Analiza a fost oprită"
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_real_server_refuses_a_second_run_while_one_is_in_progress(browser, make_app):
    """Cât rulează o analiză, un POST /api/runs primește 409; pagina deschisă în alt browser arată progresul rulării în curs."""
    script = Script()
    app = make_app(script)
    context, page, _ = open_real(browser, app)
    try:
        page.click("#btn-start")
        wait_screen(page, "working")
        status, _, body = request(app, "POST", "/api/runs", {"X-App-Token": app.token, "Content-Type": "application/json"}, b'{"mode": "demo"}')
        assert status == 409 and b"run_in_progress" in body
        second, page2, _ = open_real(browser, app)
        try:
            assert current_screen(page2) == "working"
        finally:
            second.close()
    finally:
        context.close()


# ---------- sesiunea salvată ----------

def test_saved_session_is_shown_and_deleted_from_the_page(browser, make_app):
    """Cu un profil (fals, temporar) pe disc: „Ești conectat de data trecută”; ștergerea cu DA golește folderul și arată mesajul aplicației."""
    app = make_app(profile=True)
    context, page, probe = open_real(browser, app)
    try:
        assert page.inner_text("#session-status") == "Ești conectat de data trecută"
        page.click("#btn-session-delete")
        page.fill("#session-word", "da")
        page.keyboard.press("Enter")
        wait_js(page, "document.getElementById('session-status').textContent === 'Nu există sesiune salvată'")
        assert page.inner_text("#session-note").startswith(SESSION_DELETED_PREFIX)
        assert not any(app.profile.glob("*")), "profilul temporar a fost șters"
        assert probe_problems(probe) == {}
    finally:
        context.close()


# ---------- oprirea din pagină ----------

def test_close_the_app_button_stops_the_real_server(browser, make_app):
    """„Închide aplicația” oprește serverul real (motivul: shutdown), iar portul nu mai răspunde."""
    app = make_app()
    context, page, _ = open_real(browser, app)
    try:
        port = app.server.port
        page.click("#btn-shutdown")
        wait_screen(page, "closed-user")
        app.thread.join(SERVER_STOP_TIMEOUT_S)
        assert not app.thread.is_alive() and app.stop_reasons == [app_server.STOP_SHUTDOWN]
        with pytest.raises(OSError):
            http.client.HTTPConnection("127.0.0.1", port, timeout=2).request("GET", "/api/hello")
    finally:
        context.close()


# ---------- ce afirmă FAQ-ul despre server ----------

def test_the_real_server_behaves_as_the_faq_says(make_app):
    """Fără cheie: 401; cheia greșită: 401; Host sau Origin străin: 403; fără CORS; antetele de securitate pe pagină; site-ul explicativ nu se servește."""
    app = make_app()
    port = app.server.port
    assert request(app, "GET", "/api/state")[0] == 401
    assert request(app, "GET", "/api/state", {"X-App-Token": app.token[::-1]})[0] == 401  # aceeași lungime, altă valoare
    status, headers, body = request(app, "GET", "/api/hello", {"X-App-Token": app.token})
    assert status == 200 and b'"cheltuieli-emag"' in body and "access-control-allow-origin" not in headers
    assert request(app, "GET", "/api/hello", {"X-App-Token": app.token, "Host": f"evil.example:{port}"})[0] == 403
    assert request(app, "GET", "/api/hello", {"X-App-Token": app.token, "Origin": "http://evil.example"})[0] == 403
    assert request(app, "POST", "/api/shutdown", {"X-App-Token": app.token, "Content-Type": "text/plain"}, b"{}")[0] == 415
    status, headers, _ = request(app, "GET", "/aplicatie.html")
    assert status == 200 and headers["content-security-policy"].startswith("default-src 'none'")
    assert headers["x-content-type-options"] == "nosniff" and headers["referrer-policy"] == "no-referrer"
    assert request(app, "GET", "/assets/app-api.js")[0] == 200
    assert request(app, "GET", "/index.html")[0] == 404, "site-ul explicativ nu se servește din aplicație: de aceea linkurile din pagină sunt doar din folder"
    assert request(app, "GET", "/assets/demo-data.js")[0] == 404


def test_every_asset_the_page_asks_for_is_served_by_the_real_server(make_app):
    """Fiecare script și foaie de stil din aplicatie.html e în lista albă a serverului real (altfel pagina ar rămâne fără cod sau fără stil)."""
    import re
    app = make_app()
    page_text = (Path(__file__).resolve().parent.parent / "interfata" / "aplicatie.html").read_text(encoding="utf-8")
    wanted = re.findall(r'(?:src|href)="(assets/[^"]+)"', page_text)
    assert len(wanted) >= 15
    for asset in wanted:
        assert request(app, "GET", "/" + asset)[0] == 200, asset
