"""Teste pentru rutele de actualizare ale serverului local (GET /api/update, POST /api/update/apply), pe un server REAL (127.0.0.1, port 0).

Job-ul de actualizare e cel real (app_update_job.UpdateJob), cu dependențe false (tests/test_app_update_job.py): nimic nu iese pe internet.
Verifică: aceleași reguli ca restul API-ului (cheie 401, Host/Origin 403, Content-Type 415, corp 413, metode 405), forma răspunsurilor,
409-urile (analiză în curs, nicio versiune nouă, copie git, deja în curs), POST /api/runs refuzat cât lucrează actualizarea, excluderea
atomică dintre analiză și actualizare, oprirea serverului cu STOP_UPDATED după „gata”, verificarea pornită la serve() doar dacă e permisă,
serverul ținut treaz cât lucrează actualizarea și versiunea din /api/hello. Valorile sunt inventate.
"""

import threading
import time

import pytest

from emag_spend import app_security, app_server, update_check, version
from emag_spend.app_server import STOP_IDLE, STOP_UPDATED
from tests.app_support import WAIT_SECONDS, FakeRunner, FakeUpdateJob, running_app, wait_for, write_interface
from tests.test_app_update_job import NEW_VERSION, Fakes, make_check

UPDATE_ROUTES = [("GET", "/api/update"), ("POST", "/api/update/apply")]
SHORT_IDLE_SECONDS = 0.3  # oprirea automată, scurtată pentru test (în loc de 30 de minute)
RACE_ROUNDS = 10  # de câte ori se încearcă simultan „pornește analiza” și „actualizează acum”, fiecare pe un server nou
SLOW_START_SECONDS = 0.05  # cât „pornește” runner-ul fals: lărgește fereastra în care o verificare neatomică ar lăsa să treacă ambele


class SlowStartingRunner(FakeRunner):
    """Runner fals care devine „ocupat” abia după o clipă de la pornire, ca analiza reală care își pornește firul."""

    def start(self, request):
        """Notează cererea, așteaptă puțin, apoi trece în „ocupat” (RunnerBusy dacă era deja)."""
        run_id = super().start(request)
        time.sleep(SLOW_START_SECONDS)
        self.busy = True
        return run_id


@pytest.fixture
def fakes(tmp_path) -> Fakes:
    """Dependențele false ale job-ului (verificarea întoarce implicit o versiune nouă)."""
    return Fakes(tmp_path)


@pytest.fixture
def runner() -> FakeRunner:
    """Runner-ul fals al serverului."""
    return FakeRunner()


@pytest.fixture
def app(tmp_path, fakes, runner, monkeypatch):
    """Server real cu job real (dependențe false) și verificarea permisă; așteaptă rezultatul verificării înainte de test."""
    monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)
    write_interface(tmp_path / "interfata")
    with running_app(tmp_path, runner=runner, update_job=fakes.job()) as running:
        wait_for(lambda: running.call("GET", "/api/update").json()["check"]["status"] != "verific", "verificarea s-a terminat")
        yield running


def _post_apply(app, **kwargs):
    """POST /api/update/apply cu corpul gol implicit."""
    kwargs.setdefault("body", {})
    return app.call("POST", "/api/update/apply", **kwargs)


def _send(app, method, path, **kwargs):
    """Cererea dată; la POST pune un corp JSON gol dacă testul nu dă altul."""
    if method == "POST":
        kwargs.setdefault("body", {})
    return app.call(method, path, **kwargs)


# ---------- aceleași reguli de securitate ca restul API-ului ----------

@pytest.mark.parametrize("method, path", UPDATE_ROUTES)
def test_update_routes_without_or_with_a_wrong_key_are_refused_and_nothing_starts(app, fakes, method, path):
    """Fără cheie sau cu cheie greșită: 401 pe ambele rute, iar nicio descărcare nu pornește (o pagină străină nu poate actualiza programul)."""
    for token in (False, app.token[:-1] + ("A" if app.token[-1] != "A" else "B"), "x" * len(app.token)):
        reply = _send(app, method, path, token=token)
        assert reply.status == 401 and reply.error_code == "unauthorized", f"{method} {path} cu cheia {str(token)[:6]!r}… a dat {reply.status}"
    assert fakes.called("download") == [] and fakes.called("git") == []


@pytest.mark.parametrize("method, path", UPDATE_ROUTES)
def test_update_routes_refuse_a_foreign_origin_or_host_even_with_the_key(app, fakes, method, path):
    """Origin străină (sau «null») și Host străin: 403, chiar cu cheia bună; nicio descărcare."""
    for origin in ("https://evil.example", "null", f"http://127.0.0.1:{app.port + 1}"):
        reply = _send(app, method, path, origin=origin)
        assert reply.status == 403 and reply.error_code == "forbidden_origin", f"Origin {origin!r} a dat {reply.status}"
    for host in ("evil.example", f"evil.example:{app.port}"):
        reply = _send(app, method, path, host=host)
        assert reply.status == 403 and reply.error_code == "forbidden_host", f"Host {host!r} a dat {reply.status}"
    assert fakes.called("download") == []


def test_apply_needs_the_json_content_type_and_a_small_body(app, fakes):
    """POST /api/update/apply: fără application/json -> 415; corp peste limită -> 413; corp care nu e obiect -> 400. Nimic nu pornește."""
    for content_type in ("text/plain", "application/x-www-form-urlencoded", None):
        assert _post_apply(app, content_type=content_type).status == 415
    assert _post_apply(app, body=b"x" * (app_security.MAX_REQUEST_BODY_BYTES + 1)).status == 413
    assert _post_apply(app, body="[1]").status == 400
    assert fakes.called("download") == []


def test_update_routes_answer_only_to_their_method(app, fakes):
    """GET pe ruta de aplicare (o simplă legătură sau imagine) și POST pe ruta de citire: 405 cu Allow; nimic pornit."""
    reply = app.call("GET", "/api/update/apply")
    assert reply.status == 405 and reply.headers["allow"] == "POST"
    reply = _send(app, "POST", "/api/update")
    assert reply.status == 405 and reply.headers["allow"] == "GET"
    assert fakes.called("download") == []


# ---------- GET /api/update ----------

def test_get_update_has_the_contract_shape_and_no_download_addresses(app):
    """GET /api/update: {"current", "check": {6 câmpuri}, "apply": {3 câmpuri}}, fără adresele de descărcare, cu no-store."""
    reply = app.call("GET", "/api/update")
    body = reply.json()
    assert reply.status == 200 and reply.headers["cache-control"] == "no-store"
    assert set(body) == {"current", "check", "apply"} and body["current"] == version.VERSION
    assert set(body["check"]) == {"status", "latest", "notes", "published", "page_url", "message"}
    assert body["check"]["status"] == "noua" and body["check"]["latest"] == NEW_VERSION
    assert body["apply"] == {"state": "inactiv", "message": "", "to_version": None}
    assert b"releases/download" not in reply.body


def test_hello_reports_the_program_version(app):
    """GET /api/hello are versiunea din emag_spend/version.py (sursa unică, D1)."""
    assert app.call("GET", "/api/hello").json()["version"] == version.VERSION == app_server.APP_VERSION


@pytest.mark.parametrize("env_value, enabled", [(None, True), ("1", True), ("0", False), (" 0 ", False)])
def test_serve_starts_the_check_only_when_it_is_allowed(tmp_path, fakes, monkeypatch, env_value, enabled):
    """La serve(): verificarea pornește (în fundal) doar dacă settings.update_check_enabled(); cu EMAG_UPDATE_CHECK=0 doar răspunsul „dezactivat”, fără rețea."""
    if env_value is None:
        monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)
    else:
        monkeypatch.setenv("EMAG_UPDATE_CHECK", env_value)
    fakes.check_result = make_check(update_check.STATUS_NEW if enabled else update_check.STATUS_DISABLED)
    with running_app(tmp_path, update_job=fakes.job()) as app:
        wait_for(lambda: fakes.called("check"), "serverul a pornit verificarea")
        assert fakes.called("check") == [("check", enabled)]


def test_the_fake_job_used_by_the_other_app_tests_never_checks_online(tmp_path):
    """Serverele din celelalte teste (running_app fără update_job) primesc un job fals: verificarea e doar notată, nimic nu iese pe internet."""
    with running_app(tmp_path) as app:
        wait_for(lambda: app.app.update_job.calls, "serverul a pornit verificarea")
        assert isinstance(app.app.update_job, FakeUpdateJob)


# ---------- POST /api/update/apply ----------

def test_apply_answers_202_then_the_server_stops_for_the_restart(app, fakes):
    """POST /api/update/apply -> 202 {"apply": {"state": "descarc"...}}; după instalare, serverul se oprește singur cu STOP_UPDATED."""
    reply = _post_apply(app)
    assert reply.status == 202 and reply.json() == {"apply": {"state": "descarc", "message": f"Descarc versiunea {NEW_VERSION}…", "to_version": NEW_VERSION}}
    wait_for(lambda: app.stopped, "serverul s-a oprit după actualizare")
    assert app.stop_reason == STOP_UPDATED, f"motivul opririi după actualizare: {app.stop_reason}"
    assert len(fakes.called("apply")) == 1


def test_the_page_sees_every_state_while_the_update_works(app, fakes):
    """Cât lucrează: GET /api/update arată „descarc”, „verific”, „instalez”, apoi „gata” cu mesajul de repornire (înainte de oprire)."""
    fakes.download_gate, fakes.verify_gate, fakes.apply_gate = threading.Event(), threading.Event(), threading.Event()
    fakes.sleep_gate = threading.Event()  # „gata” rămâne vizibil cât vrea testul (pauza dinaintea opririi)
    assert _post_apply(app).status == 202
    seen = [app.call("GET", "/api/update").json()["apply"]["state"]]
    for gate, state in ((fakes.download_gate, "verific"), (fakes.verify_gate, "instalez"), (fakes.apply_gate, "gata")):
        gate.set()
        wait_for(lambda: app.call("GET", "/api/update").json()["apply"]["state"] == state, f"starea „{state}”")
        seen.append(state)
    assert seen == ["descarc", "verific", "instalez", "gata"]
    assert "repornește" in app.call("GET", "/api/update").json()["apply"]["message"] and not app.stopped
    fakes.sleep_gate.set()
    wait_for(lambda: app.stopped, "serverul s-a oprit după „gata”")
    assert app.stop_reason == STOP_UPDATED


def test_apply_is_409_while_an_analysis_runs(app, fakes, runner):
    """Cât rulează o analiză: 409 run_in_progress, cu mesaj în română; nicio descărcare."""
    runner.busy = True
    reply = _post_apply(app)
    assert reply.status == 409 and reply.error_code == "run_in_progress" and "analiză" in reply.json()["error"]["message"]
    assert fakes.called("download") == []


def test_apply_is_409_without_a_new_version(tmp_path, fakes, monkeypatch):
    """Verificarea a spus „la-zi”: 409 no_update."""
    monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)
    fakes.check_result = make_check(update_check.STATUS_UP_TO_DATE)
    with running_app(tmp_path, update_job=fakes.job()) as app:
        wait_for(lambda: app.call("GET", "/api/update").json()["check"]["status"] == "la-zi", "verificarea s-a terminat")
        reply = _post_apply(app)
        assert reply.status == 409 and reply.error_code == "no_update"
    assert fakes.called("download") == []


def test_apply_is_409_in_a_git_checkout_with_the_decided_message(app, fakes):
    """Copie git: 409 git_checkout cu mesajul din D9; nicio descărcare."""
    fakes.git = True
    reply = _post_apply(app)
    assert reply.status == 409 and reply.error_code == "git_checkout" and reply.json()["error"]["message"] == "Folderul ăsta e o copie git: actualizează cu git pull."
    assert fakes.called("download") == []


def test_a_second_apply_while_one_works_is_409(app, fakes):
    """A doua apăsare cât lucrează prima: 409 update_in_progress; o singură descărcare."""
    fakes.download_gate = threading.Event()
    assert _post_apply(app).status == 202
    reply = _post_apply(app)
    assert reply.status == 409 and reply.error_code == "update_in_progress"
    fakes.download_gate.set()
    wait_for(lambda: app.stopped, "serverul s-a oprit după actualizare")
    assert len(fakes.called("download")) == 1


def test_a_failed_update_keeps_the_server_running_and_allows_analyses(app, fakes, runner):
    """O actualizare eșuată: „eroare” cu mesajul ei, serverul merge mai departe, iar analiza poate porni (202)."""
    from emag_spend.update_errors import UpdateError

    fakes.download_error = UpdateError("Amprentă inventată greșită; am șters arhiva.")
    assert _post_apply(app).status == 202
    wait_for(lambda: app.call("GET", "/api/update").json()["apply"]["state"] == "eroare", "starea „eroare”")
    assert app.call("GET", "/api/update").json()["apply"]["message"] == "Amprentă inventată greșită; am șters arhiva."
    assert app.call("POST", "/api/runs", body={"mode": "demo"}).status == 202 and not app.stopped


# ---------- analiza și actualizarea se exclud ----------

def test_starting_an_analysis_while_the_update_works_is_409_and_nothing_starts(app, fakes, runner):
    """POST /api/runs cât lucrează actualizarea: 409 update_in_progress, cu mesaj în română; runner-ul nu e chemat."""
    fakes.download_gate = threading.Event()
    assert _post_apply(app).status == 202
    reply = app.call("POST", "/api/runs", body={"mode": "demo"})
    assert reply.status == 409 and reply.error_code == "update_in_progress" and "actualizare" in reply.json()["error"]["message"]
    assert [call for call in runner.calls if call[0] == "start"] == [], "analiza a pornit cât se instala o actualizare"
    fakes.download_gate.set()


def test_an_analysis_and_an_update_started_together_never_both_start(tmp_path, monkeypatch):
    """„Pornește analiza” și „Actualizează acum” trimise în același timp: exact una pornește (202), cealaltă primește 409."""
    monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)
    write_interface(tmp_path / "interfata")
    for round_number in range(RACE_ROUNDS):
        fakes = Fakes(tmp_path / f"runda{round_number}")
        fakes.download_gate = threading.Event()
        runner = SlowStartingRunner()
        with running_app(tmp_path, runner=runner, update_job=fakes.job()) as app:
            wait_for(lambda: app.call("GET", "/api/update").json()["check"]["status"] == "noua", "verificarea s-a terminat")
            barrier = threading.Barrier(2)
            replies = {}

            def press(name, method, path, body):
                barrier.wait(WAIT_SECONDS)
                replies[name] = app.call(method, path, body=body).status

            threads = [threading.Thread(target=press, args=("analiza", "POST", "/api/runs", {"mode": "demo"})),
                       threading.Thread(target=press, args=("actualizare", "POST", "/api/update/apply", {}))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(WAIT_SECONDS)
            fakes.download_gate.set()
            assert sorted(replies.values()) == [202, 409], f"runda {round_number}: {replies} (analiză și actualizare au pornit amândouă sau niciuna)"


# ---------- viața serverului ----------

def test_a_working_update_keeps_the_server_awake_and_the_clock_restarts_after_it(tmp_path):
    """Cât lucrează actualizarea, oprirea automată nu vine (ar întrerupe instalarea); după, serverul se oprește singur de inactivitate."""
    job = FakeUpdateJob()
    job.blocking = True
    with running_app(tmp_path, update_job=job, idle_seconds=SHORT_IDLE_SECONDS) as app:
        time.sleep(SHORT_IDLE_SECONDS * 4)
        assert not app.stopped, "serverul s-a oprit de inactivitate în timpul actualizării"
        job.blocking = False
        wait_for(lambda: app.stopped, "serverul s-a oprit de inactivitate după actualizare")
        assert app.stop_reason == STOP_IDLE


def test_stopping_the_server_waits_for_an_install_in_progress(tmp_path):
    """La oprire, serverul întreabă job-ul dacă instalează (wait_for_install), ca fișierele să nu rămână pe jumătate mutate."""
    job = FakeUpdateJob()
    with running_app(tmp_path, update_job=job) as app:
        app.stop()
    assert ("wait_for_install",) in job.calls
