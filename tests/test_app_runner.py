"""Teste pentru rularea în fundal a analizei (emag_spend/app_runner.py) și maparea erorilor (app_errors.py), fără Playwright.

Pipeline-ul e înlocuit cu funcții false comandate din test (opriri sincronizate cu evenimente, fără `sleep` fix). Verifică:
masina de stări, o singură rulare odată (RunnerBusy -> 409), anularea cooperantă, erorile mapate pe coduri stabile cu mesaje în
română și „ce faci”, opțiunile pasate pipeline-ului (demo fără demo-data.js) și validarea cererii de pornire. Valorile sunt inventate.
"""

import threading
from datetime import datetime
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

import ruleaza
from emag_spend import app_errors, app_runner, run_ids, settings
from emag_spend.app_runner import AppRunner, InvalidRunRequest, RunnerBusy, RunRequest
from emag_spend.browser_session import BrowserLaunchFailed, LoginTimeout
from emag_spend.page_fetcher import SessionExpired
from emag_spend.progress import NO_PROGRESS, PHASE_ANALYZING, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_WAITING_LOGIN, RunCancelled
from tests.app_support import WAIT_SECONDS, wait_for

FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0)
DEMO_REQUEST = RunRequest("demo", 500.0)
REAL_REQUEST = RunRequest("real", 750.0)


class Gate:
    """Un punct de sincronizare între test și firul rulării: firul anunță că a ajuns, apoi așteaptă permisiunea testului."""

    def __init__(self):
        self.reached = threading.Event()
        self.proceed = threading.Event()

    def pass_through(self) -> None:
        """Se cheamă din firul rulării: anunță că a ajuns și așteaptă (cu termen) ca testul să-i dea drumul."""
        self.reached.set()
        assert self.proceed.wait(WAIT_SECONDS), "testul n-a dat drumul firului rulării la timp"


class FakePipeline:
    """Pipeline fals: notează opțiunile, rulează `script(options, progress)` și, dacă scriptul nu ridică nimic, întoarce folderul rulării."""

    def __init__(self, script=None):
        self.script = script
        self.calls: list[dict] = []

    def __call__(self, options, log_path=None, progress=NO_PROGRESS):
        self.calls.append({"options": options, "log_path": log_path, "progress": progress})
        if self.script:
            self.script(options, progress)
        run_dir = Path(options.output_dir) / options.run_folder_name
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir


def make_runner(tmp_path, pipeline=None, **kwargs) -> AppRunner:
    """Un AppRunner cu foldere în `tmp_path` și ceas fix."""
    return AppRunner(outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil", pipeline=pipeline or FakePipeline(),
                     clock=lambda: FIXED_NOW, **kwargs)


def wait_for_state(runner: AppRunner, state: str) -> dict:
    """Așteaptă ca runner-ul să ajungă în `state` și întoarce instantaneul."""
    return wait_for(lambda: (snap := runner.snapshot())["state"] == state and snap, f"starea «{state}» (acum «{runner.snapshot()['state']}»)")


# ---------- validarea cererii de pornire ----------

def test_a_valid_request_is_parsed_with_the_default_threshold():
    """{"mode": "demo"} primește pragul implicit din settings; {"mode": "real", "threshold_lei": 1000} îl păstrează."""
    assert app_runner.parse_run_request({"mode": "demo"}) == RunRequest("demo", float(settings.BIG_PURCHASE_THRESHOLD_LEI))
    assert app_runner.parse_run_request({"mode": "real", "threshold_lei": 1000}) == RunRequest("real", 1000.0)
    assert app_runner.parse_run_request({"mode": "real", "threshold_lei": None}).threshold_lei == float(settings.BIG_PURCHASE_THRESHOLD_LEI)
    assert app_runner.parse_run_request({"mode": "demo", "threshold_lei": 0}).threshold_lei == 0.0
    assert app_runner.parse_run_request({"mode": "demo", "threshold_lei": settings.MAX_BIG_PURCHASE_THRESHOLD_LEI}).threshold_lei == float(settings.MAX_BIG_PURCHASE_THRESHOLD_LEI)


@pytest.mark.parametrize("payload, code", [
    ([], "invalid_request"), ("demo", "invalid_request"), (None, "invalid_request"), ({}, "invalid_mode"),
    ({"mode": "x"}, "invalid_mode"), ({"mode": ["real"]}, "invalid_mode"), ({"mode": 1}, "invalid_mode"), ({"mode": None}, "invalid_mode"),
    ({"mode": "REAL"}, "invalid_mode"), ({"mode": "demo", "extra": 1}, "invalid_request"), ({"mode": "demo", "prag": 5}, "invalid_request"),
    ({"mode": "demo", "threshold_lei": True}, "invalid_threshold"), ({"mode": "demo", "threshold_lei": "500"}, "invalid_threshold"),
    ({"mode": "demo", "threshold_lei": -1}, "invalid_threshold"), ({"mode": "demo", "threshold_lei": -0.01}, "invalid_threshold"),
    ({"mode": "demo", "threshold_lei": float("inf")}, "invalid_threshold"), ({"mode": "demo", "threshold_lei": float("nan")}, "invalid_threshold"),
    ({"mode": "demo", "threshold_lei": 1e300}, "invalid_threshold"), ({"mode": "demo", "threshold_lei": settings.MAX_BIG_PURCHASE_THRESHOLD_LEI + 1}, "invalid_threshold"),
    ({"mode": "demo", "threshold_lei": 10 ** 400}, "invalid_threshold"), ({"mode": "demo", "threshold_lei": [5]}, "invalid_threshold"),
    ({"mode": "demo", "threshold_lei": {"a": 1}}, "invalid_threshold"),
])
def test_an_invalid_request_is_refused_with_a_stable_code_and_a_romanian_message(payload, code):
    """Cerere greșită (mod necunoscut, câmp în plus, prag nenumeric sau în afara limitelor): InvalidRunRequest cu cod stabil și mesaj în română."""
    with pytest.raises(InvalidRunRequest) as error:
        app_runner.parse_run_request(payload)
    assert error.value.code == code
    assert error.value.message and error.value.message[0].isupper() and error.value.message.endswith("."), "mesajul nu e o propoziție în română"


@pytest.mark.parametrize("text", ["0", "500", "999.5", "1e3", "1000000000", "-5", "-0.01", "1000000001", "inf", "nan", "1e400", "abc", ""])
def test_the_threshold_validation_matches_the_command_line_option(text):
    """Pragul din aplicație se validează cu aceleași limite ca --prag din linia de comandă: ce primește una, primește și cealaltă."""
    try:
        cli_value = ruleaza._threshold_lei(text)
    except Exception:
        cli_value = None
    try:
        value = float(text)
    except ValueError:
        value = None
    try:
        app_value = app_runner.parse_run_request({"mode": "demo", "threshold_lei": value}).threshold_lei if value is not None else None
    except InvalidRunRequest:
        app_value = None
    assert app_value == cli_value, f"pragul «{text}»: linia de comandă dă {cli_value}, aplicația dă {app_value}"


# ---------- starea și rularea ----------

def test_a_fresh_runner_is_idle_with_no_run(tmp_path):
    """Înainte de orice pornire: idle, fără rulare, fără eroare, progres gol, fără sesiune salvată."""
    snap = make_runner(tmp_path).snapshot()
    assert snap == {"state": "idle", "message": app_runner.STATE_MESSAGES["idle"], "progress": {"phase": "idle", "done": 0, "total": None},
                    "run_id": None, "started_at": None, "error": None, "session_saved": False}


def test_start_returns_a_valid_run_id_and_the_state_follows_the_phases(tmp_path):
    """Pornirea întoarce un id valid; starea trece prin starting, waiting_login, fetching_orders (cu «făcute din total»), fetching_returns, analyzing, apoi done."""
    gates = {name: Gate() for name in ("start", "login", "orders", "returns", "analysis")}

    def script(options, progress):
        gates["start"].pass_through()
        progress.phase(PHASE_WAITING_LOGIN)
        progress.message("Loghează-te acum.")
        gates["login"].pass_through()
        progress.phase(PHASE_FETCHING_ORDERS)
        progress.advance(25, 340)
        gates["orders"].pass_through()
        progress.phase(PHASE_FETCHING_RETURNS)
        progress.advance(3, 8)
        gates["returns"].pass_through()
        progress.phase(PHASE_ANALYZING)
        gates["analysis"].pass_through()

    runner = make_runner(tmp_path, FakePipeline(script))
    run_id = runner.start(DEMO_REQUEST)
    parsed = run_ids.parse_run_id(run_id)
    assert parsed is not None and parsed.demo and parsed.moment == FIXED_NOW
    wait_for(gates["start"].reached.is_set, "pipeline-ul a pornit")
    snap = runner.snapshot()
    assert snap["state"] == "starting" and snap["run_id"] == run_id and snap["started_at"] == "2026-10-05T12:00:00" and snap["error"] is None
    gates["start"].proceed.set()
    wait_for(gates["login"].reached.is_set, "faza de login")
    snap = runner.snapshot()
    assert snap["state"] == "waiting_login" and snap["message"] == "Loghează-te acum." and snap["progress"]["phase"] == "waiting_login"
    gates["login"].proceed.set()
    wait_for(gates["orders"].reached.is_set, "faza de comenzi")
    snap = runner.snapshot()
    assert snap["state"] == "fetching_orders" and snap["progress"] == {"phase": "fetching_orders", "done": 25, "total": 340}
    assert snap["message"].endswith("(25 din 340)") and "Loghează-te acum." not in snap["message"], "mesajul fazei vechi a rămas după schimbarea fazei"
    gates["orders"].proceed.set()
    wait_for(gates["returns"].reached.is_set, "faza de retururi")
    assert runner.snapshot()["progress"] == {"phase": "fetching_returns", "done": 3, "total": 8}
    gates["returns"].proceed.set()
    wait_for(gates["analysis"].reached.is_set, "faza de analiză")
    snap = runner.snapshot()
    assert snap["state"] == "analyzing" and "din" not in snap["message"], "contorul apare și la analiză, unde nu are sens"
    gates["analysis"].proceed.set()
    done = wait_for_state(runner, "done")
    assert done["run_id"] == run_id and done["error"] is None and runner.join(WAIT_SECONDS)


def test_a_second_start_while_running_is_refused_and_a_new_one_is_allowed_after_it_ends(tmp_path):
    """O singură rulare odată: a doua cerere primește RunnerBusy (409 în server), iar după terminare se poate porni alta, cu alt id."""
    gate = Gate()
    runner = make_runner(tmp_path, FakePipeline(lambda options, progress: gate.pass_through()))
    first = runner.start(DEMO_REQUEST)
    wait_for(gate.reached.is_set, "prima rulare a pornit")
    with pytest.raises(RunnerBusy):
        runner.start(REAL_REQUEST)
    assert runner.is_busy() and runner.snapshot()["run_id"] == first
    gate.proceed.set()
    wait_for_state(runner, "done")
    assert not runner.is_busy()
    second = runner.start(DEMO_REQUEST)
    assert second != first, "a doua rulare a primit același id: și-ar fi amestecat fișierele cu prima"
    wait_for_state(runner, "done")


def test_run_ids_skip_folders_that_already_exist(tmp_path):
    """Dacă folderul rulării din secunda curentă există deja (altă rulare), id-ul trece la secunda următoare."""
    outputs = tmp_path / "iesiri"
    (outputs / "2026-10-05_12-00-00_demo").mkdir(parents=True)
    (outputs / "2026-10-05_12-00-01_demo").mkdir()
    runner = make_runner(tmp_path)
    assert runner.start(DEMO_REQUEST) == "2026-10-05_12-00-02_demo"
    wait_for_state(runner, "done")
    assert runner.start(REAL_REQUEST) == "2026-10-05_12-00-00", "rularea reală nu are sufixul _demo, deci nu se ciocnește cu folderele demo"


def test_the_pipeline_receives_the_options_of_the_request(tmp_path):
    """Pipeline-ul primește pragul, modul, folderul iesiri/, numele rulării și log_path; la demo NU rescrie demo-data.js (fișier urmărit de git)."""
    pipeline = FakePipeline()
    log_path = tmp_path / "logs" / "sesiune.log"
    runner = make_runner(tmp_path, pipeline, log_path=log_path)
    demo_id = runner.start(RunRequest("demo", 321.0))
    wait_for_state(runner, "done")
    real_id = runner.start(RunRequest("real", 654.0))
    wait_for_state(runner, "done")
    demo_call, real_call = pipeline.calls
    for call, run_id, demo, threshold in ((demo_call, demo_id, True, 321.0), (real_call, real_id, False, 654.0)):
        options = call["options"]
        assert (options.demo, options.threshold_lei, options.run_folder_name) == (demo, threshold, run_id)
        assert Path(options.output_dir) == tmp_path / "iesiri" and options.from_cache is None and options.max_orders is None
        assert options.update_site_demo_data is False, "o rulare din aplicație ar rescrie interfata/assets/demo-data.js, fișier urmărit de git"
        assert call["log_path"] == log_path and call["progress"] is not NO_PROGRESS


def test_phase_calls_outside_a_run_or_with_unknown_names_are_ignored(tmp_path):
    """Un apel de fază cu nume necunoscut sau după terminarea rulării nu strică starea."""
    captured = {}
    runner = make_runner(tmp_path, FakePipeline(lambda options, progress: captured.update(progress=progress) or progress.phase("nu_exista")))
    runner.start(DEMO_REQUEST)
    wait_for_state(runner, "done")
    captured["progress"].phase(PHASE_FETCHING_ORDERS)
    captured["progress"].advance(5, 9)
    captured["progress"].message("întârziat")
    snap = runner.snapshot()
    assert snap["state"] == "done" and snap["progress"]["done"] == 0 and "întârziat" not in snap["message"]


# ---------- anulare ----------

def test_cancel_is_cooperative_and_ends_in_the_cancelled_state(tmp_path):
    """Anularea: starea își schimbă mesajul imediat, pipeline-ul primește cererea prin raportor, iar la RunCancelled starea devine cancelled (nu error)."""
    gate = Gate()

    def script(options, progress):
        gate.pass_through()
        progress.raise_if_cancelled()
        pytest.fail("pipeline-ul n-a văzut cererea de anulare")

    runner = make_runner(tmp_path, FakePipeline(script))
    runner.start(DEMO_REQUEST)
    wait_for(gate.reached.is_set, "rularea a pornit")
    assert runner.cancel() is True
    assert runner.snapshot()["message"] == app_runner.CANCELLING_MESSAGE and runner.is_busy()
    gate.proceed.set()
    snap = wait_for_state(runner, "cancelled")
    assert snap["error"] is None and snap["message"] == app_runner.STATE_MESSAGES["cancelled"] and not runner.is_busy()
    assert runner.join(WAIT_SECONDS)


def test_cancel_with_nothing_running_does_nothing(tmp_path):
    """Anulare fără rulare în curs (la început sau după terminare) întoarce False și nu schimbă starea."""
    runner = make_runner(tmp_path)
    assert runner.cancel() is False and runner.snapshot()["state"] == "idle"
    runner.start(DEMO_REQUEST)
    wait_for_state(runner, "done")
    assert runner.cancel() is False and runner.snapshot()["state"] == "done"


def test_a_new_run_after_a_cancelled_one_starts_clean(tmp_path):
    """După o anulare, o rulare nouă pornește cu cererea de anulare ștearsă (altfel s-ar opri imediat)."""
    gate = Gate()
    calls = []

    def script(options, progress):
        calls.append(progress.cancel_requested())
        if len(calls) == 1:
            gate.pass_through()
            progress.raise_if_cancelled()

    runner = make_runner(tmp_path, FakePipeline(script))
    runner.start(DEMO_REQUEST)
    wait_for(gate.reached.is_set, "prima rulare")
    runner.cancel()
    gate.proceed.set()
    wait_for_state(runner, "cancelled")
    runner.start(DEMO_REQUEST)
    wait_for_state(runner, "done")
    assert calls == [False, False], "a doua rulare a pornit cu anularea încă cerută"


def test_shutdown_cancels_the_running_analysis_and_waits_for_it(tmp_path):
    """La oprirea aplicației rularea în curs primește cererea de oprire și i se așteaptă sfârșitul (browserul se închide)."""
    started = threading.Event()

    def script(options, progress):
        started.set()
        while True:
            progress.raise_if_cancelled()
            threading.Event().wait(0.005)

    runner = make_runner(tmp_path, FakePipeline(script))
    runner.start(DEMO_REQUEST)
    wait_for(started.is_set, "rularea a pornit")
    assert runner.shutdown(WAIT_SECONDS) is True
    assert runner.snapshot()["state"] == "cancelled"


# ---------- erori ----------

MISSING_BROWSER = BrowserLaunchFailed(
    "BrowserType.launch_persistent_context: Chromium distribution 'msedge' is not found at C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\n"
    "Run \"playwright install msedge\"")
PROFILE_LOCKED = BrowserLaunchFailed(
    "BrowserType.launch_persistent_context: Target page, context or browser has been closed\nCall log:\n  - <launching> msedge\n  - Opening in existing browser session.")


@pytest.mark.parametrize("error, code", [
    (LoginTimeout("nu te-ai logat în timpul alocat; rulează din nou scriptul"), "login_timeout"),
    (SessionExpired("redirecționat la login pentru /x"), "session_expired"),
    (MISSING_BROWSER, "browser_missing"),
    (PlaywrightError("BrowserType.launch: Executable doesn't exist at C:\\x\\chrome.exe\nRun playwright install"), "browser_missing"),
    (PROFILE_LOCKED, "profile_in_use"),
    (BrowserLaunchFailed("BrowserType.launch_persistent_context: user data directory is already in use"), "profile_in_use"),
    (PlaywrightError("Page.goto: Target page, context or browser has been closed"), "unexpected"),
    (PlaywrightError("Page.evaluate: ceva neașteptat"), "unexpected"),
    (RuntimeError("nu am putut descărca /x: HTTP 500"), "unexpected"),
    (ValueError("categoria evidențiată «Alcool» nu există"), "unexpected"),
    (FileNotFoundError("lipsește un fișier"), "unexpected"),
    (KeyError("cheie"), "unexpected"),
    (ZeroDivisionError("x"), "unexpected"),
])
def test_errors_map_to_stable_codes_with_romanian_messages_that_say_what_to_do(tmp_path, error, code):
    """Fiecare eroare cunoscută are cod stabil; toate mesajele sunt în română și spun «Ce faci»; starea rulării devine error cu același cod."""
    mapped = app_errors.classify_error(error)
    assert mapped.code == code, f"{type(error).__name__} mapat la «{mapped.code}», se aștepta «{code}»"
    assert "Ce faci:" in mapped.message and mapped.message.endswith(("»." , ".")) and mapped.code in app_errors.ERROR_CODES
    runner = make_runner(tmp_path, FakePipeline(lambda options, progress: (_ for _ in ()).throw(error)))
    runner.start(DEMO_REQUEST)
    snap = wait_for_state(runner, "error")
    assert snap["error"] == {"code": code, "message": mapped.message} and snap["message"] == mapped.message
    assert runner.join(WAIT_SECONDS) and not runner.is_busy()


def test_the_error_codes_are_exactly_the_documented_stable_set():
    """Codurile de eroare din contract: login_timeout, session_expired, browser_missing, profile_in_use, unexpected (interfața se bazează pe ele)."""
    assert app_errors.ERROR_CODES == ("login_timeout", "session_expired", "browser_missing", "profile_in_use", "unexpected")


def test_an_unexpected_error_shows_the_first_line_of_a_human_message_but_only_the_type_of_a_programming_error():
    """La erori cu mesaj scris pentru oameni se arată prima linie (fără «Call log»); la erori de program (KeyError...) doar tipul, nu valorile."""
    with_detail = app_errors.classify_error(RuntimeError("prima linie\nal doilea rând secret"))
    assert "prima linie" in with_detail.message and "al doilea rând" not in with_detail.message
    only_type = app_errors.classify_error(KeyError("valoare-interna"))
    assert "KeyError" in only_type.message and "valoare-interna" not in only_type.message
    long_message = app_errors.classify_error(RuntimeError("x" * 5000)).message
    assert len(long_message) < app_errors.MAX_DETAIL_CHARS + 400, "un mesaj uriaș ar umple ecranul"


def test_the_login_timeout_message_uses_the_configured_wait(monkeypatch):
    """Mesajul de login expirat spune cât s-a așteptat, din settings.LOGIN_WAIT_SECONDS (nu un număr scris în cod)."""
    monkeypatch.setattr(settings, "LOGIN_WAIT_SECONDS", 600)
    assert "10 minute" in app_errors.classify_error(LoginTimeout("x")).message
    monkeypatch.setattr(settings, "LOGIN_WAIT_SECONDS", 90)
    assert "90 de secunde" in app_errors.classify_error(LoginTimeout("x")).message


def test_the_browser_missing_message_names_the_configured_browser(monkeypatch):
    """Mesajul «browser lipsă» numește browserul din settings.BROWSER_CHANNEL și spune ce faci (instalezi Edge sau treci pe Chrome)."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", "chrome")
    message = app_errors.classify_error(MISSING_BROWSER).message
    assert "«chrome»" in message and "EMAG_BROWSER_CHANNEL" in message


@pytest.mark.parametrize("raised", [SystemExit(3), GeneratorExit(), KeyboardInterrupt()])
def test_even_a_base_exception_in_the_run_thread_ends_in_error_not_in_a_stuck_state(tmp_path, raised):
    """Orice excepție din firul rulării (chiar și BaseException) duce la starea error; altfel aplicația ar rămâne „în curs” pentru totdeauna."""
    runner = make_runner(tmp_path, FakePipeline(lambda options, progress: (_ for _ in ()).throw(raised)))
    runner.start(DEMO_REQUEST)
    snap = wait_for_state(runner, "error")
    assert snap["error"]["code"] == "unexpected" and not runner.is_busy()


def test_the_log_never_receives_a_request_token_and_the_runner_never_needs_one(tmp_path, caplog):
    """Runner-ul nu primește niciodată tokenul de sesiune: în jurnalul lui apar doar id-ul, modul și pragul."""
    caplog.set_level("DEBUG")
    runner = make_runner(tmp_path)
    runner.start(DEMO_REQUEST)
    wait_for_state(runner, "done")
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "rularea" in text and "token" not in text.lower()


# ---------- sesiunea salvată ----------

def make_profile(folder: Path) -> Path:
    """Un profil Chromium inventat, cu semnătura pe care o recunoaște session_cleaner."""
    (folder / "Default").mkdir(parents=True)
    (folder / "Local State").write_text("{}", encoding="utf-8")
    (folder / "Default" / "Cookies").write_bytes(b"cookie-inventat")
    return folder


def test_session_saved_follows_the_profile_on_disk_and_deletion_removes_it(tmp_path):
    """session_saved e True doar cât există un profil de browser; ștergerea din aplicație îl elimină și raportează rezultatul."""
    runner = make_runner(tmp_path)
    assert runner.snapshot()["session_saved"] is False
    make_profile(tmp_path / "profil")
    assert runner.snapshot()["session_saved"] is True
    result = runner.delete_session()
    assert result.status.value == "deleted" and not (tmp_path / "profil").exists()
    assert runner.snapshot()["session_saved"] is False
    assert "a fost ștearsă" in app_runner.describe_session_deletion(result) and "login.bat" not in app_runner.describe_session_deletion(result)


def test_the_session_cannot_be_deleted_while_an_analysis_runs(tmp_path):
    """Cât rulează o analiză (browserul folosește profilul) ștergerea sesiunii e refuzată cu RunnerBusy, iar profilul rămâne."""
    make_profile(tmp_path / "profil")
    gate = Gate()
    runner = make_runner(tmp_path, FakePipeline(lambda options, progress: gate.pass_through()))
    runner.start(DEMO_REQUEST)
    wait_for(gate.reached.is_set, "rularea a pornit")
    with pytest.raises(RunnerBusy):
        runner.delete_session()
    assert (tmp_path / "profil" / "Local State").is_file(), "profilul a fost șters în timpul unei rulări"
    gate.proceed.set()
    wait_for_state(runner, "done")


def test_deleting_a_folder_that_is_not_a_browser_profile_is_refused(tmp_path):
    """Un folder care nu seamănă a profil de browser (ex. EMAG_PROFILE_DIR setat greșit) nu se șterge: rezultat refuzat, fișierele rămân."""
    folder = tmp_path / "profil"
    folder.mkdir()
    (folder / "document.txt").write_text("important", encoding="utf-8")
    result = make_runner(tmp_path).delete_session()
    assert not result.succeeded and (folder / "document.txt").is_file()
    assert "EROARE" in app_runner.describe_session_deletion(result)


# ---------- Playwright în firul de fundal ----------

def test_the_playwright_driver_starts_inside_the_background_thread_with_its_own_event_loop():
    """Premisa rulării în fundal: `asyncio.run` + driverul Playwright (fără să lanseze vreun browser) merg într-un fir care nu e cel principal, ca în AppRunner."""
    import asyncio

    outcome: dict = {}

    def work():
        async def main():
            from playwright.async_api import async_playwright

            async with async_playwright() as playwright:
                outcome["knows_chromium"] = bool(playwright.chromium.executable_path)

        try:
            asyncio.run(main())
            outcome["finished"] = True
        except BaseException as error:  # noqa: BLE001 - orice eșec trebuie raportat de test, nu pierdut în fir
            outcome["error"] = repr(error)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(WAIT_SECONDS * 3)
    assert not thread.is_alive(), "driverul Playwright nu a pornit în 30 s în firul de fundal"
    assert outcome == {"knows_chromium": True, "finished": True}, f"Playwright nu merge într-un fir de fundal: {outcome}"
