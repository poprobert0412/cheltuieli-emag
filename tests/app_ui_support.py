"""Ajutoare pentru testele paginii aplicatie.html: un server FALS al aplicației locale și pornirea browserului.

Primește: nimic din afară (totul e inventat). Dă înapoi: `FakeAppServer` (stdlib, 127.0.0.1, port ales de sistem), care respectă
contractul API din brief (token în X-App-Token, antet Host exact, Content-Type JSON și Origin la POST, fără CORS, aceleași
antete de securitate, fișiere statice doar din lista albă a folderului interfata/) și o stare simulată pe care testul o
conduce cu mâna (login în așteptare, progres, eroare, anulare, oprire, versiune nouă și pașii actualizării); plus `launch_browser`, `attach_probe`, `open_app`, fixture-urile
pytest `browser`, `fake` și `open_page` (importate în fiecare fișier de test) și sondele JavaScript rulate în pagină (contrast,
ținte de atingere, depășire orizontală).
Ce NU face: nu conține teste și nu pornește aplicația reală (emag_spend/app_server.py are testele lui). Serverul fals
nu scrie nimic pe disc; capturile de ecran se fac doar dacă variabila de mediu APP_UI_CAPTURES_DIR indică un folder.
"""

import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from emag_spend import settings

INTERFACE_DIR = settings.PROJECT_ROOT / "interfata"
DEMO_DATA_JS = INTERFACE_DIR / "assets" / "demo-data.js"
APP_PAGE = "/aplicatie.html"
BROWSER_CHANNELS = tuple(c for c in (settings.BROWSER_CHANNEL, "msedge", "chrome") if c)  # gol = automat: Edge, apoi Chrome
CAPTURES_ENV = "APP_UI_CAPTURES_DIR"  # folderul în care se salvează capturile (implicit: nu se salvează nimic)

# Politica de conținut din brief, aplicată de aplicația reală pe fiecare răspuns; serverul fals o trimite la fel,
# ca testele să prindă orice stil sau script inline care ar fi blocat în producție.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)
MAX_BODY_BYTES = 4096  # la POST, corpul e limitat la câțiva KB (contractul din brief)
RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
ALLOWED_FILES = ("raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt")
ACTIVE_STATES = ("starting", "waiting_login", "fetching_orders", "fetching_returns", "analyzing")
# Stările aplicării actualizării în care nu pornește nicio analiză (ca app_update_job.APPLY_BLOCKING_STATES).
UPDATE_BLOCKING_STATES = ("descarc", "verific", "instalez", "gata")
FAKE_CURRENT_VERSION = "1.0.0"
MAX_THRESHOLD_LEI = settings.MAX_BIG_PURCHASE_THRESHOLD_LEI  # aceeași regulă ca la --prag
SESSION_DELETED_MESSAGE = "Sesiunea eMAG salvată a fost ștearsă. Data viitoare te vei loga din nou când pornești analiza."
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


# Porturile pe care Chromium (Edge, Chrome) refuză să le deschidă: net::ERR_UNSAFE_PORT (lista „restricted ports” din net/base/port_util.cc,
# trecută de aici din memorie; dacă un port nou apare blocat, se adaugă). Portul 0 „ales de sistem” poate nimeri unul dintre ele
# (s-a văzut 1723 într-o rulare): serverul fals și cel real trebuie să mai ceară un port în acest caz.
BROWSER_BLOCKED_PORTS = frozenset({
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115,
    117, 119, 123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587,
    601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080,
})
MAX_BIND_ATTEMPTS = 100  # de câte ori cerem un port nou până dăm de unul acceptat de browsere (aproape niciodată mai mult de 1–2)


class _QueuedHTTPServer(ThreadingHTTPServer):
    """Ca serverul real (app_server._LocalHTTPServer): loc în coadă pentru toate fișierele paginii, cerute deodată de browser."""

    request_queue_size = 64


def _bind_to_a_port_browsers_accept(handler) -> ThreadingHTTPServer:
    """Pornește un ThreadingHTTPServer pe 127.0.0.1, cu port ales de sistem, repetând cât timp portul e unul blocat de browsere."""
    for _ in range(MAX_BIND_ATTEMPTS):
        server = _QueuedHTTPServer(("127.0.0.1", 0), handler)
        if server.server_address[1] not in BROWSER_BLOCKED_PORTS:
            return server
        server.server_close()
    raise RuntimeError("nu am primit niciun port acceptat de browsere")


def demo_analysis() -> dict:
    """Analiza inventată din interfata/assets/demo-data.js (`window.EMAG_DEMO_DATA = {...};`), ca obiect Python."""
    text = DEMO_DATA_JS.read_text(encoding="utf-8").strip()
    prefix = "window.EMAG_DEMO_DATA = "
    assert text.startswith(prefix) and text.endswith(";"), "demo-data.js nu mai are forma `window.EMAG_DEMO_DATA = {...};`"
    return json.loads(text[len(prefix):-1])


def idle_state(session_saved: bool = False) -> dict:
    """Starea unei aplicații în repaus, în forma din contractul GET /api/state."""
    return {"state": "idle", "message": "", "progress": {"phase": "", "done": 0, "total": None},
            "run_id": None, "started_at": None, "error": None, "session_saved": session_saved}


def update_state(status: str = "la-zi", *, latest: str | None = FAKE_CURRENT_VERSION, notes: str = "", page_url: str | None = None,
                 message: str = "", apply_state: str = "inactiv", apply_message: str = "", to_version: str | None = None) -> dict:
    """Răspunsul GET /api/update în forma din contract (app_update_job.UpdateJob.snapshot), cu valori inventate."""
    return {
        "current": FAKE_CURRENT_VERSION,
        "check": {"status": status, "latest": latest, "notes": notes, "published": None, "page_url": page_url, "message": message},
        "apply": {"state": apply_state, "message": apply_message, "to_version": to_version},
    }


def sample_runs() -> list[dict]:
    """O listă de rulări anterioare inventate, cele mai noi întâi (forma din contractul GET /api/runs).

    Prima are și `spent_bani` (analiză nouă, cu „plătit efectiv”); a doua doar `kept_bani` (analiză veche, la preț de listă).
    """
    return [
        {"id": "2026-10-05_11-07-55_demo", "created_at": "2026-10-05T11:07:55", "kind": "demo", "orders": 177, "kept_bani": 1234567,
         "spent_bani": 1200000, "has_report": True},
        {"id": "2026-10-04_17-40-47", "created_at": "2026-10-04T17:40:47", "kind": "real", "orders": 25, "kept_bani": 98765, "has_report": True},
        {"id": "2026-10-03_09-00-00", "created_at": "2026-10-03T09:00:00", "kind": "real", "orders": None, "kept_bani": None, "has_report": False},
    ]


@dataclass
class FakeAppServer:
    """Aplicația locală, falsă: același contract, aceeași securitate, stare condusă din test.

    Testul schimbă starea cu `set_state(...)`; cererile primite se văd în `requests` (metodă, cale, antete, corp).
    `fail_next[(metodă, cale)] = (status, cod, mesaj)` face următoarea cerere de acel fel să primească o eroare.
    """

    session_saved: bool = False
    runs: list = field(default_factory=sample_runs)
    analysis: dict = field(default_factory=demo_analysis)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    state: dict = field(default_factory=idle_state)
    requests: list = field(default_factory=list)
    started: list = field(default_factory=list)
    fail_next: dict = field(default_factory=dict)
    cancel_requests: int = 0
    deleted_sessions: int = 0
    shutdown_requested: bool = False
    version: str = "0.0-test"
    hello_override: dict | None = None
    hold_start: bool = False
    update: dict = field(default_factory=update_state)
    update_applies: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _counter: int = 0
    _bound_port: int = 0

    def __post_init__(self) -> None:
        """Starea de început arată sesiunea cerută la construire."""
        self.state = idle_state(self.session_saved)
        self.files = {name: f"conținut inventat pentru {name}\n".encode("utf-8") for name in ALLOWED_FILES}
        self.static = self._static_whitelist()

    @staticmethod
    def _static_whitelist() -> dict:
        """Numele exacte servite (listă albă): pagina aplicației, site-ul explicativ și fișierele din assets/, nimic altceva."""
        names = {APP_PAGE: INTERFACE_DIR / "aplicatie.html", "/index.html": INTERFACE_DIR / "index.html"}
        for path in (INTERFACE_DIR / "assets").iterdir():
            if path.is_file():
                names[f"/assets/{path.name}"] = path
        return names

    # ---------- pornire și oprire ----------

    def start(self) -> "FakeAppServer":
        """Pornește serverul pe 127.0.0.1, port ales de sistem (0); întoarce `self`."""
        fake = self

        class Handler(_Handler):
            owner = fake

        self._server = _bind_to_a_port_browsers_accept(Handler)
        self._server.daemon_threads = True
        self._bound_port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Oprește serverul: portul se închide, cererile următoare sunt refuzate (aplicația „s-a oprit”)."""
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    @property
    def port(self) -> int:
        """Portul ales de sistem (rămâne cunoscut și după oprire)."""
        return self._bound_port

    @property
    def origin(self) -> str:
        """Originea serverului: http://127.0.0.1:<port>."""
        return f"http://127.0.0.1:{self._bound_port}"

    def page_url(self, with_token: bool = True, path: str = APP_PAGE) -> str:
        """Adresa paginii, cu cheia în fragment (#t=...), așa cum o deschide programul."""
        return f"{self.origin}{path}" + (f"#t={self.token}" if with_token else "")

    # ---------- starea simulată ----------

    def set_state(self, **fields) -> None:
        """Schimbă câmpurile stării (state, message, progress, run_id, started_at, error, session_saved)."""
        with self._lock:
            self.state = {**self.state, **fields}

    def set_update(self, snapshot: dict) -> None:
        """Pune răspunsul GET /api/update (verificarea și starea aplicării), ca aplicația reală care avansează singură."""
        with self._lock:
            self.update = snapshot

    def api_requests(self) -> list:
        """Cererile către /api/* primite până acum."""
        with self._lock:
            return [r for r in self.requests if r["path"].startswith("/api/")]

    def next_run_id(self) -> str:
        """Un număr de rulare nou, în forma numelor de foldere din iesiri/."""
        with self._lock:
            self._counter += 1
            return f"2026-10-05_12-00-{self._counter:02d}"

    def finish_run(self, run_id: str, kind: str = "real") -> None:
        """Termină rularea: adaugă-o în listă (prima) și pune starea „done”."""
        with self._lock:
            self.runs.insert(0, {"id": run_id, "created_at": "2026-10-05T12:00:00", "kind": kind, "orders": 177, "kept_bani": 1234567, "has_report": True})
            self.state = {**self.state, "state": "done", "message": "Gata.", "run_id": run_id, "error": None}


class _Handler(BaseHTTPRequestHandler):
    """Un handler HTTP/1.0 (fără conexiuni păstrate): după `stop()` orice cerere nouă e refuzată, ca la o aplicație oprită."""

    owner: FakeAppServer
    server_version = "AppFalsa"
    sys_version = ""

    def log_message(self, format, *args) -> None:  # noqa: A002 - semnătura vine din BaseHTTPRequestHandler
        """Fără jurnal pe ecran: testele nu au nevoie de el."""

    # ----- răspunsuri -----

    def _send(self, status: int, body: bytes, content_type: str, extra: tuple = ()) -> None:
        """Trimite un răspuns cu toate antetele de securitate din contract."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        """Răspuns JSON UTF-8."""
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, code: str, message: str) -> None:
        """Eroare în forma din contract: {"error": {"code", "message"}}, mesaj în română."""
        self._json(status, {"error": {"code": code, "message": message}})

    # ----- verificări de securitate -----

    def _host_ok(self) -> bool:
        """Host exact 127.0.0.1:<port> sau localhost:<port> (anti DNS-rebinding)."""
        port = self.owner.port
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _token_ok(self) -> bool:
        """Comparație în timp constant cu cheia sesiunii."""
        given = self.headers.get("X-App-Token", "")
        return hmac.compare_digest(given.encode("utf-8"), self.owner.token.encode("utf-8"))

    def _read_raw_body(self) -> bytes | None:
        """Corpul POST, citit ÎNAINTE de orice răspuns (un corp necitit duce la resetarea conexiunii); None dacă e prea mare."""
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY_BYTES:
            self._error(413, "too_large", "Cererea e prea mare.")
            return None
        return self.rfile.read(length) if length else b""

    def _parse_json_body(self, raw: bytes):
        """Corpul POST ca obiect JSON; None (după ce a trimis eroarea) dacă tipul, originea sau forma nu sunt cele cerute."""
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._error(415, "content_type", "Cererea trebuie trimisă ca JSON.")
            return None
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.owner.origin:
            self._error(403, "origin", "Cererea vine de la o altă origine.")
            return None
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._error(400, "bad_json", "Corpul cererii nu e JSON valid.")
            return None
        if not isinstance(body, dict):
            self._error(400, "bad_json", "Corpul cererii trebuie să fie un obiect JSON.")
            return None
        return body

    # ----- rutare -----

    def _log_request(self) -> None:
        """Notează cererea (metodă, cale, ținta întreagă cu interogare, antete cu litere mici) pentru aserțiunile testelor."""
        entry = {"method": self.command, "path": urlsplit(self.path).path, "target": self.path,
                 "headers": {k.lower(): v for k, v in self.headers.items()}}
        with self.owner._lock:
            self.owner.requests.append(entry)

    def _injected_failure(self, path: str) -> bool:
        """Dacă testul a cerut o eroare pentru (metodă, cale), o trimite o singură dată și întoarce True."""
        with self.owner._lock:
            failure = self.owner.fail_next.pop((self.command, path), None)
        if failure is None:
            return False
        status, code, message = failure
        self._error(status, code, message)
        return True

    def do_GET(self) -> None:  # noqa: N802 - numele cerut de BaseHTTPRequestHandler
        """Fișiere statice din lista albă sau rute GET ale API-ului."""
        self._log_request()
        path = urlsplit(self.path).path
        if not self._host_ok():
            return self._error(403, "host", "Adresa (Host) nu e cea a aplicației.")
        if path.startswith("/api/"):
            return self._api_get(path)
        if path in self.owner.static:
            file = self.owner.static[path]
            return self._send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))
        return self._error(404, "not_found", "Nu există.")

    def do_POST(self) -> None:  # noqa: N802
        """Rute POST ale API-ului."""
        self._log_request()
        path = urlsplit(self.path).path
        if not self._host_ok():
            return self._error(403, "host", "Adresa (Host) nu e cea a aplicației.")
        raw = self._read_raw_body()
        if raw is None:
            return None
        if not path.startswith("/api/"):
            return self._error(404, "not_found", "Nu există.")
        if not self._token_ok():
            return self._error(401, "unauthorized", "Lipsește cheia de acces sau nu e bună.")
        if self._injected_failure(path):
            return None
        body = self._parse_json_body(raw)
        if body is None:
            return None
        return self._api_post(path, body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Fără CORS: nicio rută nu răspunde la preflight."""
        self._log_request()
        self._error(405, "method", "Metodă nepermisă.")

    # ----- API: GET -----

    def _api_get(self, path: str) -> None:
        """GET /api/hello, /api/state, /api/runs, /api/update, /api/runs/<id>/analysis, /api/runs/<id>/files/<nume>."""
        if not self._token_ok():
            return self._error(401, "unauthorized", "Lipsește cheia de acces sau nu e bună.")
        if self._injected_failure(path):
            return None
        owner = self.owner
        if path == "/api/hello":
            return self._json(200, owner.hello_override or {"app": "cheltuieli-emag", "version": owner.version, "api": 1})
        if path == "/api/state":
            with owner._lock:
                state = dict(owner.state)
            return self._json(200, state)
        if path == "/api/runs":
            with owner._lock:
                runs = list(owner.runs)
            return self._json(200, runs)
        if path == "/api/update":
            with owner._lock:
                update = json.loads(json.dumps(owner.update))
            return self._json(200, update)
        match = re.fullmatch(r"/api/runs/([^/]+)/(analysis|files/([^/]+))", path)
        if not match or not RUN_ID_PATTERN.match(match.group(1)):
            return self._error(404, "not_found", "Nu există.")
        run_id = match.group(1)
        with owner._lock:
            known = any(run["id"] == run_id for run in owner.runs) or owner.state.get("run_id") == run_id
        if not known:
            return self._error(404, "run_not_found", "Nu există o rulare cu acest id sau rularea nu are analiză.")
        if match.group(2) == "analysis":
            return self._json(200, owner.analysis)
        name = match.group(3)
        if name not in ALLOWED_FILES:
            return self._error(404, "file_not_found", "Fișierul cerut nu există la această rulare.")
        return self._send(200, owner.files[name], "application/octet-stream",
                          (("Content-Disposition", f'attachment; filename="{name}"'),))

    # ----- API: POST -----

    def _api_post(self, path: str, body: dict) -> None:
        """POST /api/runs, /api/runs/current/cancel, /api/session/delete, /api/update/apply, /api/shutdown."""
        owner = self.owner
        if path == "/api/runs":
            return self._start_run(body)
        if path == "/api/runs/current/cancel":
            with owner._lock:
                owner.cancel_requests += 1
                if owner.state["state"] in ACTIVE_STATES:
                    owner.state = {**owner.state, "state": "cancelled", "message": "Oprită de tine."}
            return self._json(200, {"cancel_requested": True})
        if path == "/api/session/delete":
            if body.get("confirm") != "DA":
                return self._error(400, "confirmation_required", "Ca să ștergi sesiunea trimite confirmarea «DA».")
            with owner._lock:
                owner.deleted_sessions += 1
                owner.state = {**owner.state, "session_saved": False}
            return self._json(200, {"status": "deleted", "message": SESSION_DELETED_MESSAGE, "session_saved": False})
        if path == "/api/update/apply":
            return self._apply_update()
        if path == "/api/shutdown":
            owner.shutdown_requested = True
            self._json(200, {"stopping": True})
            threading.Thread(target=owner.stop, daemon=True).start()  # ca aplicația reală: răspunde, apoi se oprește
            return None
        return self._error(404, "not_found", "Nu există.")

    def _apply_update(self) -> None:
        """POST /api/update/apply: aceleași 409 ca aplicația reală; altfel trece în „descarc” și răspunde 202 {"apply": ...}."""
        owner = self.owner
        with owner._lock:
            if owner.update["apply"]["state"] in UPDATE_BLOCKING_STATES:
                return self._error(409, "update_in_progress", "Actualizarea e deja în curs.")
            if owner.state["state"] in ACTIVE_STATES:
                return self._error(409, "run_in_progress", "Actualizarea nu poate porni cât rulează o analiză. Așteaptă să se termine sau oprește-o.")
            if owner.update["check"]["status"] != "noua":
                return self._error(409, "no_update", "Nu există o versiune nouă de instalat.")
            latest = owner.update["check"]["latest"]
            owner.update_applies += 1
            owner.update = {**owner.update, "apply": {"state": "descarc", "message": f"Descarc versiunea {latest}…", "to_version": latest}}
            apply = dict(owner.update["apply"])
        return self._json(202, {"apply": apply})

    def _start_run(self, body: dict) -> None:
        """POST /api/runs: validează ca --prag, refuză cu 409 dacă rulează deja una, altfel pornește („starting”) și răspunde 202."""
        owner = self.owner
        mode = body.get("mode")
        if mode not in ("real", "demo"):
            return self._error(400, "invalid_mode", "Câmpul «mode» trebuie să fie «real» (contul tău eMAG) sau «demo» (date inventate).")
        threshold = body.get("threshold_lei")
        if threshold is not None:
            valid = isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and 0 <= threshold <= MAX_THRESHOLD_LEI
            if not valid:
                return self._error(400, "invalid_threshold", "Pragul trebuie să fie un număr între 0 și 1.000.000.000 de lei.")
        with owner._lock:
            if owner.state["state"] in ACTIVE_STATES:
                return self._error(409, "run_in_progress", "O analiză rulează deja. Așteaptă să se termine sau oprește-o.")
            if owner.update["apply"]["state"] in UPDATE_BLOCKING_STATES:
                return self._error(409, "update_in_progress", "Se instalează o actualizare a programului; analiza poate porni după ce aplicația repornește.")
        run_id = owner.next_run_id()
        with owner._lock:
            owner.started.append({"mode": mode, "threshold_lei": threshold, "run_id": run_id})
            if not owner.hold_start:  # hold_start: aplicația a acceptat rularea, dar starea ei încă nu o arată
                owner.state = {**owner.state, "state": "starting", "message": "Pornesc…", "run_id": run_id,
                               "started_at": "2026-10-05T12:00:00", "error": None,
                               "progress": {"phase": "", "done": 0, "total": None}}
        return self._json(202, {"run_id": run_id})


# ---------- browser ----------

@dataclass
class Probe:
    """Ce a văzut pagina: erori de consolă, excepții necaptate și cererile făcute."""

    origin: str
    console: list = field(default_factory=list)
    page_errors: list = field(default_factory=list)
    urls: list = field(default_factory=list)

    def outside_requests(self) -> list:
        """Cererile care nu merg spre serverul aplicației și nu sunt locale (data:, blob:, about:, file:)."""
        return [u for u in self.urls if not u.startswith((self.origin, "data:", "blob:", "about:", "file:"))]


def probe_problems(probe: Probe) -> dict:
    """Tot ce ar trebui să fie gol pentru o pagină curată: erori de consolă (inclusiv încălcări CSP), excepții, cereri în afara serverului."""
    problems = {"console": probe.console, "pageerror": probe.page_errors, "outside": probe.outside_requests()}
    return {name: found for name, found in problems.items() if found}


def launch_browser(playwright):
    """Pornește primul browser instalat din BROWSER_CHANNELS; ridică RuntimeError dacă niciunul nu pornește."""
    errors = []
    for channel in dict.fromkeys(BROWSER_CHANNELS):
        try:
            return playwright.chromium.launch(channel=channel)
        except Exception as exc:  # Playwright ridică Error generic dacă browserul lipsește
            errors.append(f"{channel}: {str(exc).splitlines()[0]}")
    raise RuntimeError("niciun browser nu a pornit (" + "; ".join(errors) + ")")


def attach_probe(page, origin: str) -> Probe:
    """Atașează ascultători care completează o `Probe` cât trăiește pagina."""
    probe = Probe(origin)
    page.on("console", lambda msg: probe.console.append(f"{msg.type}: {msg.text}") if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda exc: probe.page_errors.append(str(exc)))
    page.on("request", lambda req: probe.urls.append(req.url))
    return probe


def open_app(browser, fake: FakeAppServer, *, width: int = 1280, height: int = 900, scheme: str = "light", motion: str = "reduce",
             touch: bool = False, with_token: bool = True, url: str | None = None, init_script: str | None = None,
             forced_colors: str = "none", javascript: bool = True, wait_for: str | None = "html[data-current-screen]:not([data-current-screen='loading'])"):
    """Deschide pagina aplicației (cu cheia în fragment, sau la `url`) într-un context nou; întoarce (context, pagină, sondă)."""
    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion=motion,
                                  forced_colors=forced_colors, has_touch=touch, accept_downloads=True, java_script_enabled=javascript)
    if init_script:
        context.add_init_script(init_script)
    page = context.new_page()
    probe = attach_probe(page, fake.origin)
    failed = []  # cererile căzute în rețea: un app-*.js pierdut ținea pagina pe „loading”, iar adnotarea din CI arată doar selectorul
    page.on("requestfailed", lambda request: failed.append(f"{request.url} {request.failure}"))
    page.goto(url or fake.page_url(with_token=with_token))
    if wait_for:
        try:
            page.wait_for_selector(wait_for, state="attached")
        except Exception as error:  # aceeași așteptare; la eșec spune și ce a văzut pagina
            error.add_note(f"cereri căzute: {failed or 'niciuna'}; excepții în pagină: {probe.page_errors or 'niciuna'}")
            raise
    return context, page, probe


# ---------- fixture-uri pytest (se importă în fișierele de test) ----------

@pytest.fixture(scope="module")
def playwright_instance():
    """Un singur driver Playwright pentru tot fișierul; se sare dacă Playwright nu e instalat."""
    sync_api = pytest.importorskip("playwright.sync_api")
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
def fake():
    """O aplicație falsă pornită pentru un test (cu sesiune salvată), oprită la final."""
    server = FakeAppServer(session_saved=True).start()
    yield server
    server.stop()


@pytest.fixture
def open_page(browser, fake):
    """Fabrică de pagini: `open_page(**opțiuni)` deschide aplicația și întoarce (pagină, sondă); contextele se închid la final."""
    contexts = []

    def _open(server: FakeAppServer | None = None, **options):
        """Deschide pagina pe serverul dat (implicit `fake`)."""
        context, page, probe = open_app(browser, server or fake, **options)
        contexts.append(context)
        return page, probe

    yield _open
    for context in contexts:
        context.close()


def wait_screen(page, name: str, timeout: int = 8000) -> None:
    """Așteaptă până când ecranul `name` e cel afișat (atributul data-current-screen de pe <html>)."""
    page.wait_for_selector(f"html[data-current-screen='{name}']", state="attached", timeout=timeout)


def current_screen(page) -> str:
    """Ecranul afișat acum."""
    return page.locator("html").get_attribute("data-current-screen")


POLL_INTERVAL_MS = 50  # cât se așteaptă între două verificări în wait_js


def wait_js(page, expression: str, arg=None, timeout: int = 8000):
    """Așteaptă până când expresia JavaScript întoarce o valoare adevărată; o întoarce. La expirare ridică AssertionError cu ultima valoare.

    Înlocuiește page.wait_for_function: acela compilează predicatul cu eval, pe care politica de conținut a paginii (script-src 'self')
    îl refuză, iar testele nu opresc politica (bypass_csp): tocmai ea prinde stilurile și scripturile inline.
    """
    waited, last = 0, None
    while waited <= timeout:
        last = page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)
        if last:
            return last
        page.wait_for_timeout(POLL_INTERVAL_MS)
        waited += POLL_INTERVAL_MS
    raise AssertionError(f"expresia nu a devenit adevărată în {timeout} ms: {expression} (ultima valoare: {last!r})")


# ---------- sonde JavaScript rulate în pagină ----------

# Contrastul fiecărui text vizibil (în afara raportului, care are testele lui): culoarea textului față de fundalul efectiv
# (straturile semitransparente se compun în sus până la primul fundal opac; textul peste gradient se sare). Pragul: 4.5, sau 3 la text mare (≥24 px sau ≥18.66 px îngroșat).
CONTRAST_SCAN_JS = r"""() => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const mix = (f, b) => ({r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1});
  const out = []; const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode; if (!node.textContent.trim()) continue;
    const el = node.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    if (el.closest('script, style, noscript, .sr-only, .emag-dash, [hidden], :disabled, [aria-disabled="true"]')) continue;
    const style = getComputedStyle(el); const rect = el.getBoundingClientRect();
    if (style.visibility === 'hidden' || style.display === 'none' || rect.width === 0 || rect.height === 0) continue;
    const layers = []; let cur = el; let imageBehind = false;
    while (cur) { const cs = getComputedStyle(cur); if (cs.backgroundImage !== 'none') { imageBehind = true; break; }
      const bg = parse(cs.backgroundColor); if (bg && bg.a > 0) { layers.push(bg); if (bg.a >= 1) break; } cur = cur.parentElement; }
    if (imageBehind) continue; // gradient sau imagine sub text (markerul galben): nu se poate măsura aici; perechea de culori are testul ei static
    let base = {r: 255, g: 255, b: 255, a: 1}; let start = layers.length;
    if (layers.length && layers[layers.length - 1].a >= 1) { base = layers[layers.length - 1]; start = layers.length - 1; }
    let bg = base; for (let i = start - 1; i >= 0; i--) bg = mix(layers[i], bg);
    const fg = mix(parse(style.color), bg);
    const ratio = (Math.max(lum(fg), lum(bg)) + 0.05) / (Math.min(lum(fg), lum(bg)) + 0.05);
    const size = parseFloat(style.fontSize); const bold = parseInt(style.fontWeight, 10) >= 700;
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
    if (ratio < need) out.push({text: node.textContent.trim().slice(0, 50), ratio: Math.round(ratio * 100) / 100, need: need});
  }
  return out; }"""

# Controalele vizibile (în afara raportului) mai mici de 40 px pe oricare dimensiune; linkurile din text curg și nu intră aici.
TAP_TARGET_JS = r"""(min) => [...document.querySelectorAll('button, input:not([type="hidden"]), summary')]
  .filter((el) => !el.closest('.emag-dash, .sr-only, [hidden]') && el.getClientRects().length)
  .map((el) => { const r = el.getBoundingClientRect(); return {id: el.id || el.textContent.trim().slice(0, 30), w: Math.round(r.width), h: Math.round(r.height)}; })
  .filter((t) => t.w < min || t.h < min)"""

# Elemente (în afara raportului) care ies din ecran în lateral, plus lățimea de derulare a paginii.
OVERFLOW_JS = r"""() => { const width = document.documentElement.clientWidth;
  const out = [...document.querySelectorAll('body *')].filter((el) => !el.closest('.emag-dash, .sr-only, [hidden], svg') && el.getClientRects().length)
    .map((el) => ({el, r: el.getBoundingClientRect()})).filter((x) => x.r.width > 0 && (x.r.right > width + 1 || x.r.left < -1))
    .map((x) => (x.el.id || x.el.className || x.el.tagName) + ' ' + Math.round(x.r.left) + '..' + Math.round(x.r.right));
  return {scrollWidth: document.documentElement.scrollWidth, clientWidth: width, outside: out.slice(0, 10)}; }"""


def capture(page, name: str) -> None:
    """Salvează o captură de ecran în folderul din APP_UI_CAPTURES_DIR, dacă variabila e setată (altfel nu face nimic)."""
    folder = os.environ.get(CAPTURES_ENV)
    if not folder:
        return
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target / f"{name}.png"), full_page=False)
