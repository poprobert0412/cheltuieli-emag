"""Ajutoare pentru testele aplicației locale: server real pornit în fir, client HTTP, runner fals, job de actualizare fals, așteptări cu termen.

Ce face: pornește `AppServer` pe 127.0.0.1, port 0, într-un fir al testului; trimite cereri cu `http.client` sau pe socket brut
(pentru forme de cale pe care un client obișnuit le normalizează); oferă un runner fals care respectă contractul AppRunner, un job
de actualizare fals (contractul app_update_job.UpdateJob, fără nicio cerere spre internet) și o funcție de așteptare cu termen
(fără `sleep` fix). Ce NU face: nu conține teste. Valorile sunt inventate.
"""

import contextlib
import http.client
import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from emag_spend import app_update_job, session_cleaner
from emag_spend.app_runner import RunnerBusy, RunRequest
from emag_spend.app_security import TOKEN_HEADER
from emag_spend.app_server import STOP_SHUTDOWN, AppServer

WAIT_SECONDS = 10  # un test care așteaptă mai mult de atât e blocat: pică cu mesaj, nu atârnă CI-ul
CLIENT_TIMEOUT_SECONDS = 5
POLL_SECONDS = 0.02
FAKE_RUN_ID = "2026-10-05_12-00-00_demo"


@dataclass
class Reply:
    """Răspunsul unui server: status, antete (nume cu litere mici) și corp."""

    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        """Corpul ca JSON (UTF-8)."""
        return json.loads(self.body.decode("utf-8"))

    @property
    def error_code(self) -> str:
        """Codul din `{"error": {"code": ...}}`, sau text gol dacă răspunsul nu e o eroare JSON."""
        try:
            return self.json()["error"]["code"]
        except (ValueError, KeyError, TypeError):
            return ""


def wait_for(predicate, what: str, timeout: float = WAIT_SECONDS):
    """Așteaptă (cu sondări scurte) ca `predicate()` să dea ceva adevărat și îl întoarce; pică testul, în română, dacă nu vine la timp."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(POLL_SECONDS)
    pytest.fail(f"nu s-a întâmplat în {timeout} s: {what}")


class FakeRunner:
    """Runner fals cu aceeași suprafață ca AppRunner; notează apelurile și are un comportament comandat din test."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.busy = False
        self.state = {
            "state": "idle", "message": "Gata de pornire.", "progress": {"phase": "idle", "done": 0, "total": None},
            "run_id": None, "started_at": None, "error": None, "session_saved": False,
        }
        self.deletion = session_cleaner.SessionDeleteResult(session_cleaner.SessionDeleteStatus.DELETED, Path("profil-inventat"), deleted_files=3)

    def snapshot(self) -> dict:
        """Starea comandată de test."""
        return json.loads(json.dumps(self.state))

    def start(self, request: RunRequest) -> str:
        """Notează cererea; RunnerBusy dacă testul a pus `busy`."""
        self.calls.append(("start", request))
        if self.busy:
            raise RunnerBusy("o rulare e deja în curs")
        return FAKE_RUN_ID

    def cancel(self) -> bool:
        """Notează cererea și spune dacă „rula” ceva."""
        self.calls.append(("cancel",))
        return self.busy

    def is_busy(self) -> bool:
        """True cât timp testul ține runner-ul „ocupat”."""
        return self.busy

    def delete_session(self):
        """Notează cererea; RunnerBusy dacă e „ocupat”, altfel rezultatul comandat."""
        self.calls.append(("delete_session",))
        if self.busy:
            raise RunnerBusy("rulează o analiză")
        return self.deletion

    def shutdown(self, timeout: float = 0) -> bool:
        """Notează oprirea serverului."""
        self.calls.append(("shutdown",))
        return True


class FakeUpdateJob:
    """Job de actualizare fals cu aceeași suprafață ca app_update_job.UpdateJob: starea o pune testul, nimic nu iese pe internet.

    `refusal` (ApplyRefused) face ca `start_apply` să refuze; `blocking` = „actualizarea lucrează sau e gata”; apelurile se notează în `calls`.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.blocking = False
        self.refusal: app_update_job.ApplyRefused | None = None
        self.is_run_busy = None
        self.on_applied = None
        self.state = {
            "current": "1.0.0",
            "check": {"status": "la-zi", "latest": "1.0.0", "notes": "", "published": None, "page_url": None, "message": "Ai ultima versiune."},
            "apply": {"state": "inactiv", "message": "", "to_version": None},
        }

    def attach(self, *, is_run_busy, on_applied) -> None:
        """Reține legăturile date de server (testul le poate chema ca să simuleze sfârșitul unei actualizări)."""
        self.is_run_busy, self.on_applied = is_run_busy, on_applied

    def start_check(self, *, enabled: bool) -> None:
        """Notează pornirea verificării (fără rețea)."""
        self.calls.append(("start_check", enabled))

    def snapshot(self) -> dict:
        """Starea comandată de test (copie)."""
        return json.loads(json.dumps(self.state))

    def start_apply(self) -> dict:
        """Notează cererea; ridică `refusal` dacă testul l-a pus, altfel trece în „descarc” și întoarce starea aplicării."""
        self.calls.append(("start_apply",))
        if self.refusal is not None:
            raise self.refusal
        self.blocking = True
        self.state["apply"] = {"state": "descarc", "message": "Descarc versiunea 9.9.9…", "to_version": "9.9.9"}
        return dict(self.state["apply"])

    def is_blocking(self) -> bool:
        """True cât timp testul ține actualizarea „în lucru”."""
        return self.blocking

    def wait_for_install(self, timeout: float) -> bool:
        """Notează așteptarea de la oprirea serverului."""
        self.calls.append(("wait_for_install",))
        return True


class RunningApp:
    """Un AppServer care servește într-un fir; `call` trimite o cerere HTTP și întoarce un Reply."""

    def __init__(self, app: AppServer):
        self.app = app
        self.port = app.port
        self.token = app.token
        self.stop_reason: str | None = None
        self._thread = threading.Thread(target=self._serve, name="test-server", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        """Corpul firului: servește până la oprire și reține motivul."""
        self.stop_reason = self.app.serve()

    @property
    def stopped(self) -> bool:
        """True după ce `serve()` a terminat."""
        return not self._thread.is_alive()

    def call(self, method: str, path: str, *, token: str | None | bool = True, host: str | None = "default", origin: str | None = None,
             content_type: str | None = "application/json", body: bytes | str | dict | None = None, headers: dict[str, str] | None = None) -> Reply:
        """Trimite o cerere. `token=True` pune tokenul corect, `False`/None nu pune niciunul, un text pune acel text.

        `host="default"` pune `127.0.0.1:<port>`; None nu pune Host; un text îl pune ca atare. Un dict ca `body` se trimite ca JSON.
        `content_type` se pune doar când există corp sau metoda e POST (None = fără antet).
        """
        sent = {}
        if host is not None:
            sent["Host"] = f"127.0.0.1:{self.port}" if host == "default" else host
        if token is True:
            sent[TOKEN_HEADER] = self.token
        elif token:
            sent[TOKEN_HEADER] = token
        if origin is not None:
            sent["Origin"] = origin
        if isinstance(body, dict):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        if content_type is not None and (body is not None or method == "POST"):
            sent["Content-Type"] = content_type
        sent.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=CLIENT_TIMEOUT_SECONDS)
        try:
            connection.request(method, path, body=body, headers=sent, encode_chunked=False)
            response = connection.getresponse()
            return Reply(response.status, {name.lower(): value for name, value in response.getheaders()}, response.read())
        finally:
            connection.close()

    def raw(self, data: bytes) -> bytes:
        """Trimite octeți bruți pe un socket și întoarce tot ce răspunde serverul (pentru căi pe care `http.client` le-ar schimba)."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=CLIENT_TIMEOUT_SECONDS) as connection:
            connection.sendall(data)
            chunks = []
            while True:
                try:
                    chunk = connection.recv(65536)
                except (ConnectionResetError, socket.timeout):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks)

    def raw_get(self, request_target: str, token: bool = True, extra_headers: str = "") -> tuple[int, bytes]:
        """GET cu ținta EXACTĂ dată (ex. `//x`, `/%2e%2e/x`, `/a\\b`); întoarce (status, răspuns complet)."""
        header = f"{TOKEN_HEADER}: {self.token}\r\n" if token else ""
        request = f"GET {request_target} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n{header}{extra_headers}Connection: close\r\n\r\n"
        reply = self.raw(request.encode("utf-8", errors="surrogateescape"))
        status_line = reply.split(b"\r\n", 1)[0].decode("latin-1")
        parts = status_line.split()
        return (int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0), reply

    def stop(self) -> str | None:
        """Cere oprirea, așteaptă firul și întoarce motivul."""
        self.app.request_stop(STOP_SHUTDOWN)
        self._thread.join(WAIT_SECONDS)
        return self.stop_reason


@contextlib.contextmanager
def running_app(tmp_path: Path, **overrides):
    """Pornește un AppServer de test (foldere în `tmp_path`, runner și job de actualizare false dacă nu se dau altele) și îl oprește la ieșire.

    Parametrii se pot suprascrie (`runner=`, `update_job=`, `interface_dir=`, `idle_seconds=`...). Întoarce RunningApp.
    """
    options = {
        "runner": FakeRunner(), "update_job": FakeUpdateJob(), "outputs_dir": tmp_path / "iesiri", "profile_dir": tmp_path / "profil",
        "interface_dir": tmp_path / "interfata", "idle_seconds": 3600, "poll_seconds": POLL_SECONDS,
    }
    options.update(overrides)
    app = AppServer(**options)
    running = RunningApp(app)
    try:
        yield running
    finally:
        if not running.stopped:
            running.stop()
        app.close()


def write_interface(folder: Path, page_references: str = '<script src="assets/app.js"></script><link rel="stylesheet" href="assets/app.css">') -> Path:
    """Un folder interfata/ inventat: aplicatie.html cu referințele date, fișierele lor și câteva fișiere care NU trebuie servite."""
    (folder / "assets").mkdir(parents=True, exist_ok=True)
    (folder / "aplicatie.html").write_text(f"<!doctype html><title>Aplicație</title>{page_references}", encoding="utf-8")
    (folder / "assets" / "app.js").write_text("console.log('aplicatia');", encoding="utf-8")
    (folder / "assets" / "app.css").write_text("body{margin:0}", encoding="utf-8")
    (folder / "assets" / "demo-data.js").write_text("window.EMAG_DEMO_DATA = {};", encoding="utf-8")
    (folder / "assets" / "site.js").write_text("console.log('site');", encoding="utf-8")
    (folder / "index.html").write_text("<!doctype html><title>Site</title>", encoding="utf-8")
    return folder


def parse_reply(data: bytes) -> Reply:
    """Descompune un răspuns HTTP brut (linia de stare, antete, corp) în Reply; status 0 dacă nu seamănă a răspuns HTTP."""
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return Reply(status, headers, body)
