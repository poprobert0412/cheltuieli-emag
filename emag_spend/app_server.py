"""Serverul HTTP LOCAL al aplicației cu un singur buton (python ruleaza.py --aplicatie): API-ul JSON și pagina din interfata/.

Primește: cereri HTTP doar de pe acest calculator. Dă înapoi: răspunsuri JSON (contractul din brief, pct. 6) și fișierele din lista albă
(app_static.py). Se leagă DOAR la 127.0.0.1, port ales de sistem (port 0), niciodată la 0.0.0.0; serverul însuși nu trimite nimic spre
exterior (verificarea versiunii noi o face app_update_job.py, în fundal, doar dacă settings.update_check_enabled()).
Ordinea verificărilor: Host exact (403), Origin exactă sau absentă (403), token în X-App-Token pe /api/* (401), metodă (405), apoi pe POST
Content-Type JSON și corp limitat (415/400/413). Fără CORS; antetele de securitate (app_security.py) pleacă pe ORICE răspuns, și pe erori.
Actualizarea (decis 5 oct. 2026, D18): GET /api/update și POST /api/update/apply; analiza și actualizarea se exclud (409 una cât rulează
cealaltă), iar după o actualizare reușită serverul se oprește cu STOP_UPDATED (ruleaza.py iese cu settings.EXIT_CODE_RESTART).
Se oprește la Ctrl+C, la POST /api/shutdown și singur după o perioadă fără cereri, cât timp nu rulează o analiză sau o actualizare (variabila
de mediu opțională EMAG_APP_IDLE_MINUTES = minute fără cereri, implicit 30, între 1 și 1440).
Ce NU face: nu rulează analiza (app_runner.py), nu citește rulările (app_runs.py), nu descarcă și nu instalează (app_update_job.py)."""

import json
import logging
import os
import re
import socket
import socketserver
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from emag_spend import app_runs, app_security, app_update_job, session_cleaner, settings, version
from emag_spend.app_runner import AppRunner, InvalidRunRequest, RunnerBusy, describe_session_deletion, parse_run_request
from emag_spend.app_static import StaticFiles

logger = logging.getLogger(__name__)

# Adresa la care se leagă serverul: bucla locală, nimic altceva (un test de gardă verifică asta în cod și la execuție).
LOOPBACK_HOST = "127.0.0.1"
# Portul 0 = îl alege sistemul: un port fix ar fi o țintă cunoscută pentru o pagină străină sau pentru alt program.
ANY_FREE_PORT = 0

APP_NAME = "cheltuieli-emag"
# Versiunea afișată de /api/hello: sursa unică e emag_spend/version.py (decis 5 oct. 2026, D1).
APP_VERSION = version.VERSION
API_VERSION = 1
INTERFACE_DIR = settings.PROJECT_ROOT / "interfata"

# Oprirea automată: serverul nu rămâne deschis zile întregi dacă utilizatorul a închis fila și a uitat fereastra neagră.
# 30 de minute acoperă o pauză de citit raportul sau de căutat parola de login; sub 1 minut ar închide serverul sub mâinile
# utilizatorului, iar peste 24 de ore ar anula rostul opririi.
IDLE_ENV_VAR = "EMAG_APP_IDLE_MINUTES"
DEFAULT_IDLE_MINUTES = 30
MIN_IDLE_MINUTES = 1
MAX_IDLE_MINUTES = 24 * 60
# Cât de des se trezește bucla principală să vadă oprirea cerută, inactivitatea sau Ctrl+C: sub o secundă ca Ctrl+C să răspundă repede.
POLL_INTERVAL_SECONDS = 0.25
# O conexiune care nu trimite nimic atâta timp e închisă: nu lăsăm fire agățate de clienți care nu termină cererea.
REQUEST_TIMEOUT_SECONDS = 15
# Cât din corpul unei cereri respinse citim și aruncăm înainte să închidem conexiunea (altfel clientul poate primi „conexiune resetată”
# în loc de răspuns). Peste limită doar închidem: un client care trimite megaocteți ca să fie respins nu merită răspuns frumos.
MAX_DRAIN_BYTES = 1024 * 1024
DRAIN_CHUNK_BYTES = 64 * 1024
# La oprirea serverului în timp ce actualizarea scrie fișierele: cât o așteptăm să termine. Câteva sute de fișiere se mută în
# câteva secunde; plafonul acoperă și reîncercările la fișiere ținute o clipă de antivirus. Dacă tot nu termină, procesul iese
# oricum, iar ruleaza.py revine la versiunea veche la pornirea următoare (D11).
UPDATE_INSTALL_JOIN_SECONDS = 120

STOP_SHUTDOWN = "shutdown"
STOP_IDLE = "idle"
STOP_INTERRUPTED = "interrupted"
# Oprire după o actualizare aplicată din pagină: ruleaza.py iese cu settings.EXIT_CODE_RESTART, iar lansatorul pornește
# varianta nouă (decis 5 oct. 2026, D12).
STOP_UPDATED = "updated"

HTTP_ERROR_MESSAGES = {
    400: "Cererea nu are forma corectă.",
    404: "Adresa cerută nu există.",
    405: "Metoda folosită nu e permisă pentru această adresă.",
    408: "Cererea a durat prea mult.",
    411: "Cererea trebuie să aibă lungimea corpului.",
    413: "Cererea e prea mare.",
    414: "Adresa cerută e prea lungă.",
    431: "Antetele cererii sunt prea mari.",
    500: "Eroare internă a aplicației. Detalii în jurnalul din folderul logs.",
    501: "Metoda cerută nu e acceptată.",
    505: "Versiunea de HTTP nu e acceptată.",
}
GENERIC_ERROR_MESSAGE = "Cererea nu a putut fi procesată."

_RUN_ID_IN_PATH = r"([A-Za-z0-9_-]{1,64})"
_FILE_NAME_IN_PATH = r"([A-Za-z0-9_.-]{1,64})"
# (tipar de cale, metode permise, numele metodei care răspunde). Căile sunt potrivite în întregime, fără decodare.
API_ROUTES = (
    (re.compile(r"/api/hello"), ("GET",), "_api_hello"),
    (re.compile(r"/api/state"), ("GET",), "_api_state"),
    (re.compile(r"/api/runs"), ("GET", "POST"), "_api_runs"),
    (re.compile(r"/api/runs/current/cancel"), ("POST",), "_api_cancel"),
    (re.compile(rf"/api/runs/{_RUN_ID_IN_PATH}/analysis"), ("GET",), "_api_analysis"),
    (re.compile(rf"/api/runs/{_RUN_ID_IN_PATH}/files/{_FILE_NAME_IN_PATH}"), ("GET",), "_api_download"),
    (re.compile(r"/api/session/delete"), ("POST",), "_api_delete_session"),
    (re.compile(r"/api/shutdown"), ("POST",), "_api_shutdown"),
    (re.compile(r"/api/update"), ("GET",), "_api_update"),
    (re.compile(r"/api/update/apply"), ("POST",), "_api_update_apply"),
)
MESSAGE_RUN_REFUSED_UPDATING = "Se instalează o actualizare a programului; analiza poate porni după ce aplicația repornește."


def idle_minutes_from_environment() -> int:
    """Minutele de inactivitate din EMAG_APP_IDLE_MINUTES (implicit DEFAULT_IDLE_MINUTES); ValueError cu mesaj în română dacă valoarea e greșită."""
    raw = os.environ.get("EMAG_APP_IDLE_MINUTES")
    if raw is None or not raw.strip():
        return DEFAULT_IDLE_MINUTES
    problem = (f"variabila {IDLE_ENV_VAR} trebuie să fie un număr întreg de minute între {MIN_IDLE_MINUTES} și {MAX_IDLE_MINUTES}; "
               f"am găsit «{raw.strip()}»")
    if not re.fullmatch(r"[0-9]{1,6}", raw.strip()):  # cifre ASCII explicit: int() ar primi și semn, spații interne sau cifre arabe
        raise ValueError(problem)
    minutes = int(raw.strip())
    if not MIN_IDLE_MINUTES <= minutes <= MAX_IDLE_MINUTES:
        raise ValueError(problem)
    return minutes


class IdleMonitor:
    """Măsoară de cât timp n-a venit nicio cerere; ceasul se poate înlocui în teste."""

    def __init__(self, timeout_seconds: float, clock: Callable[[], float] = time.monotonic):
        """`timeout_seconds` = cât timp fără cereri înseamnă „inactiv”."""
        self._timeout = timeout_seconds
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()

    def note_activity(self) -> None:
        """Notează o cerere (sau o rulare în curs) chiar acum."""
        with self._lock:
            self._last = self._clock()

    def expired(self) -> bool:
        """True dacă au trecut cel puțin `timeout_seconds` de la ultima activitate."""
        with self._lock:
            return self._clock() - self._last >= self._timeout


class _LocalHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer fără reutilizarea adresei (pe Windows ar lăsa alt program să se lege de același port) și cu erori de conexiune tăcute."""

    allow_reuse_address = False
    daemon_threads = True
    app: "AppServer"

    def server_bind(self) -> None:
        """Pe Windows cere acces EXCLUSIV la port (SO_EXCLUSIVEADDRUSE), înainte de legare.

        Fără el, pe versiuni mai vechi de Windows un alt program ar putea lega același port cu SO_REUSEADDR și ar primi cereri (cu tokenul în ele);
        cele recente refuză asta singure (nu se poate dovedi cu test pe ele), iar pe celelalte sisteme un port aflat în ascultare nu poate fi legat de alt proces oricum.
        Sare peste `HTTPServer.server_bind`, care întreabă DNS-ul cum se numește adresa (socket.getfqdn): nicio interogare de rețea la pornire.
        """
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port

    def handle_error(self, request, client_address) -> None:
        """O conexiune întreruptă de browser (închis, reîncărcat) nu e o problemă: nimic pe ecran, doar în jurnal la nivel de depanare."""
        logger.debug("eroare de conexiune cu clientul local", exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    """Tratează o cerere: verificările de securitate, apoi API-ul sau fișierele statice. Fără stare între cereri."""

    protocol_version = "HTTP/1.0"  # o conexiune = o cerere: nicio cerere nu poate fi amestecată cu corpul rămas necitit al alteia
    timeout = REQUEST_TIMEOUT_SECONDS
    server: _LocalHTTPServer
    _body_read = False  # True după ce corpul cererii a fost citit; altfel o cerere respinsă îl golește (_discard_unread_body)

    # ---------- răspunsuri ----------

    def log_message(self, format, *args) -> None:
        """Nu scrie nimic pentru fiecare cerere (interfața interoghează starea la câteva secunde); respingerile se jurnalizează separat."""

    def send_response(self, code, message=None) -> None:
        """Ca în stdlib, dar FĂRĂ antetul Server (nu spunem ce versiune de Python rulează)."""
        self.send_response_only(code, message)
        self.send_header("Date", self.date_time_string())

    def end_headers(self) -> None:
        """Adaugă antetele de securitate pe orice răspuns (inclusiv cele generate de stdlib pentru cereri greșite) și închide antetele."""
        for name, value in app_security.security_headers().items():
            self.send_header(name, value)
        super().end_headers()

    def _use_status_line_and_headers(self) -> None:
        """Stdlib trimite doar corpul (fără linie de stare și fără antete) pentru cereri rupte sau în stil „HTTP/0.9”; aici forțăm răspunsuri complete."""
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"

    def send_error(self, code, message=None, explain=None) -> None:
        """Erorile generate de stdlib (cerere ruptă, metodă necunoscută) devin tot JSON în română, cu aceleași antete."""
        self._use_status_line_and_headers()
        self.close_connection = True
        self._send_json(int(code), {"error": {"code": f"http_{int(code)}", "message": HTTP_ERROR_MESSAGES.get(int(code), GENERIC_ERROR_MESSAGE)}})

    def _send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        """Trimite un răspuns complet (fără corp la HEAD)."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: object, headers: dict[str, str] | None = None) -> None:
        """Trimite `payload` ca JSON UTF-8."""
        self._send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers)

    def _reject(self, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
        """Răspunde cu eroarea `{"error": {"code", "message"}}`, jurnalizează respingerile de securitate și golește corpul necitit al cererii."""
        self.close_connection = True
        self._send_json(status, {"error": {"code": code, "message": message}}, headers)
        if status in (401, 403):
            # Metoda și calea vin de la client: trec prin loggable (fără CR/LF), ca nimeni să nu poată scrie rânduri false în jurnal.
            logger.warning("cerere respinsă: %s %r -> %d (%s)", app_security.loggable(self.command), app_security.loggable(self.path), status, code)
        if self.command == "POST" and not self._body_read:
            self._discard_unread_body()

    def _discard_unread_body(self) -> None:
        """Citește și aruncă (până la MAX_DRAIN_BYTES) corpul declarat al unei cereri respinse, după ce răspunsul a plecat."""
        length = app_security.parse_content_length(self.headers.get("Content-Length"))
        if not length or length > MAX_DRAIN_BYTES:
            return
        remaining = length
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, DRAIN_CHUNK_BYTES))
                if not chunk:
                    return
                remaining -= len(chunk)
        except OSError:
            return

    # ---------- intrarea cererilor ----------

    def _handle_any(self) -> None:
        """Punctul comun pentru toate metodele: orice excepție devine 500 generic (fără detalii), nu o conexiune lăsată în aer."""
        self._body_read = False
        self._use_status_line_and_headers()
        try:
            self._process()
        except (ConnectionError, TimeoutError):
            self.close_connection = True  # clientul a plecat: nu mai are cui să-i răspundem
        except Exception:
            logger.exception("eroare internă la tratarea cererii %s %r", app_security.loggable(self.command), app_security.loggable(self.path))
            self.close_connection = True
            try:
                self._send_json(500, {"error": {"code": "internal_error", "message": HTTP_ERROR_MESSAGES[500]}})
            except OSError:
                pass

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _handle_any

    def _process(self) -> None:
        """Verificările în ordine (Host, Origin, cale, token) și apoi API sau fișier static."""
        app = self.server.app
        port = self.server.server_port
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or not app_security.is_allowed_host(hosts[0], port):
            return self._reject(403, "forbidden_host", "Adresa folosită pentru a ajunge la aplicație nu e permisă.")
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1 or not app_security.is_allowed_origin(origins[0] if origins else None, port):
            return self._reject(403, "forbidden_origin", "Cererea vine de pe o altă pagină decât aplicația și a fost refuzată.")
        app.note_activity()
        path = self.path.partition("?")[0]
        if not app_security.is_plain_request_path(path):
            return self._reject(404, "not_found", HTTP_ERROR_MESSAGES[404])
        if path.startswith("/api/"):
            tokens = self.headers.get_all(app_security.TOKEN_HEADER) or []
            if len(tokens) != 1 or not app_security.token_matches(app.token, tokens[0]):
                return self._reject(401, "unauthorized", "Lipsește sau e greșită cheia de acces. Deschide aplicația din nou cu porneste.bat sau python ruleaza.py --aplicatie.")
            return self._handle_api(app, path)
        return self._handle_static(app, path)

    def _handle_static(self, app: "AppServer", path: str) -> None:
        """Fișierele statice: doar GET, doar adrese exacte din lista albă."""
        if self.command != "GET":
            return self._reject(405, "method_not_allowed", HTTP_ERROR_MESSAGES[405], {"Allow": "GET"})
        found = app.static.read(path)
        if found is None:
            return self._reject(404, "not_found", HTTP_ERROR_MESSAGES[404])
        body, content_type = found
        self._send_bytes(200, body, content_type)

    def _handle_api(self, app: "AppServer", path: str) -> None:
        """Alege ruta API după cale și metodă; pe POST citește și validează corpul JSON înainte de a o chema."""
        for pattern, methods, handler_name in API_ROUTES:
            matched = pattern.fullmatch(path)
            if not matched:
                continue
            if self.command not in methods:
                return self._reject(405, "method_not_allowed", HTTP_ERROR_MESSAGES[405], {"Allow": ", ".join(methods)})
            handler = getattr(self, handler_name)
            if self.command == "POST":
                body = self._read_json_body()
                if body is None:
                    return None
                return handler(app, body, *matched.groups())
            return handler(app, *matched.groups())
        return self._reject(404, "not_found", HTTP_ERROR_MESSAGES[404])

    def _read_json_body(self) -> dict | None:
        """Corpul unui POST ca dicționar ({} dacă e gol); la orice problemă trimite eroarea și întoarce None.

        Verifică Content-Type (415), lungimea declarată (400/413) și JSON-ul strict (400); nu citește niciodată mai mult de MAX_REQUEST_BODY_BYTES.
        """
        content_types = self.headers.get_all("Content-Type") or []
        if len(content_types) != 1 or not app_security.is_json_content_type(content_types[0]):
            self._reject(415, "unsupported_media_type", "Cererea trebuie să aibă Content-Type: application/json.")
            return None
        if self.headers.get("Transfer-Encoding") is not None:
            self._reject(400, "bad_request", "Corpul trimis în bucăți (chunked) nu e acceptat; trimite Content-Length.")
            return None
        lengths = self.headers.get_all("Content-Length") or []
        length = None if len(lengths) > 1 else app_security.parse_content_length(lengths[0] if lengths else None)
        if length is None:  # antet dublu sau valoare care nu e un număr întreg fără semn
            self._reject(400, "bad_request", "Antetul Content-Length lipsește sau nu e un număr valid.")
            return None
        if app_security.exceeds_body_limit(length):
            self._reject(413, "body_too_large", f"Cererea depășește {app_security.MAX_REQUEST_BODY_BYTES} de octeți.")
            return None
        try:
            raw = self.rfile.read(length) if length else b""
        except TimeoutError:
            self._reject(408, "request_timeout", HTTP_ERROR_MESSAGES[408])
            return None
        self._body_read = True
        if len(raw) != length:
            self._reject(400, "bad_request", "Corpul cererii e incomplet.")
            return None
        if not raw.strip():
            return {}
        try:
            payload = app_security.parse_strict_json(raw)
        except (ValueError, RecursionError):
            self._reject(400, "invalid_json", "Corpul cererii nu e JSON valid.")
            return None
        if not isinstance(payload, dict):
            self._reject(400, "invalid_json", "Corpul cererii trebuie să fie un obiect JSON.")
            return None
        return payload

    # ---------- rutele API ----------

    def _api_hello(self, app: "AppServer") -> None:
        """GET /api/hello: cine sunt și ce versiune de API vorbesc."""
        self._send_json(200, {"app": APP_NAME, "version": APP_VERSION, "api": API_VERSION})

    def _api_state(self, app: "AppServer") -> None:
        """GET /api/state: starea rulării curente."""
        self._send_json(200, app.runner.snapshot())

    def _api_runs(self, app: "AppServer", body: dict | None = None) -> None:
        """GET /api/runs: lista rulărilor anterioare; POST /api/runs: pornește o rulare (202 + id, 400 la cerere greșită,
        409 dacă una e în curs sau dacă se instalează o actualizare)."""
        if self.command == "GET":
            return self._send_json(200, app.runs.list_runs())
        try:
            request = parse_run_request(body)
            with app.start_lock:  # verificarea actualizării și pornirea analizei, atomic față de POST /api/update/apply
                if app.update_job.is_blocking():
                    return self._reject(409, app_update_job.ERROR_UPDATE_IN_PROGRESS, MESSAGE_RUN_REFUSED_UPDATING)
                run_id = app.runner.start(request)
        except InvalidRunRequest as error:
            return self._reject(400, error.code, error.message)
        except RunnerBusy:
            return self._reject(409, "run_in_progress", "O analiză rulează deja. Așteaptă să se termine sau oprește-o.")
        return self._send_json(202, {"run_id": run_id})

    def _api_cancel(self, app: "AppServer", body: dict) -> None:
        """POST /api/runs/current/cancel: cere oprirea rulării în curs (200 și dacă nu rula nimic)."""
        self._send_json(200, {"cancel_requested": app.runner.cancel()})

    def _api_analysis(self, app: "AppServer", run_id: str) -> None:
        """GET /api/runs/<id>/analysis: conținutul analiza.json (404 dacă nu există, 422 dacă e prea mare sau stricat)."""
        try:
            data = app.runs.read_analysis(run_id)
        except app_runs.RunNotFound:
            return self._reject(404, "run_not_found", "Nu există o rulare cu acest id sau rularea nu are analiză.")
        except app_runs.RunFileUnreadable as error:
            return self._reject(422, error.code, error.message)
        self._send_bytes(200, data, "application/json; charset=utf-8")

    def _api_download(self, app: "AppServer", run_id: str, name: str) -> None:
        """GET /api/runs/<id>/files/<nume>: descarcă un fișier din lista albă (attachment); 404 pentru orice altceva."""
        try:
            data, content_type = app.runs.read_download(run_id, name)
        except app_runs.RunNotFound:
            return self._reject(404, "file_not_found", "Fișierul cerut nu există la această rulare.")
        except app_runs.RunFileUnreadable as error:
            return self._reject(422, error.code, error.message)
        self._send_bytes(200, data, content_type, {"Content-Disposition": f'attachment; filename="{name}"'})

    def _api_delete_session(self, app: "AppServer", body: dict) -> None:
        """POST /api/session/delete cu {"confirm": "DA"}: șterge sesiunea salvată (409 cât rulează o analiză sau dacă ștergerea eșuează)."""
        if body.get("confirm") != session_cleaner.CONFIRMATION_WORD:
            return self._reject(400, "confirmation_required", f"Ca să ștergi sesiunea trimite confirmarea «{session_cleaner.CONFIRMATION_WORD}».")
        try:
            result = app.runner.delete_session()
        except RunnerBusy:
            return self._reject(409, "run_in_progress", "Sesiunea nu se poate șterge cât rulează o analiză. Oprește analiza și încearcă din nou.")
        message = describe_session_deletion(result)
        if not result.succeeded:
            return self._reject(409, "session_delete_failed", message)
        self._send_json(200, {"status": result.status.value, "message": message, "session_saved": app.runner.snapshot()["session_saved"]})

    def _api_shutdown(self, app: "AppServer", body: dict) -> None:
        """POST /api/shutdown: răspunde, apoi oprește serverul (butonul «Închide aplicația»)."""
        self._send_json(200, {"stopping": True})
        app.request_stop(STOP_SHUTDOWN)

    def _api_update(self, app: "AppServer") -> None:
        """GET /api/update: versiunea curentă, rezultatul verificării și starea aplicării (forma din app_update_job.UpdateJob.snapshot)."""
        self._send_json(200, app.update_job.snapshot())

    def _api_update_apply(self, app: "AppServer", body: dict) -> None:
        """POST /api/update/apply: pornește actualizarea (202 {"apply": ...}); 409 dacă rulează o analiză, nu e versiune nouă,
        folderul e copie git sau actualizarea e deja în curs. Corpul nu contează (doar trebuie să fie un obiect JSON)."""
        try:
            with app.start_lock:  # atomic față de POST /api/runs: niciodată analiză și actualizare în același timp
                apply = app.update_job.start_apply()
        except app_update_job.ApplyRefused as refused:
            return self._reject(409, refused.code, refused.message)
        self._send_json(202, {"apply": apply})


class AppServer:
    """Serverul local: se leagă la creare, servește la `serve()` până la oprire și întoarce motivul opririi."""

    def __init__(self, *, runner=None, runs: app_runs.RunsStore | None = None, interface_dir: Path | None = None,
                 outputs_dir: Path | None = None, profile_dir: Path | None = None, log_path: Path | None = None,
                 idle_seconds: float | None = None, poll_seconds: float = POLL_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.monotonic, token: str | None = None,
                 update_job: app_update_job.UpdateJob | None = None):
        """Pregătește serverul și îl leagă la 127.0.0.1, port ales de sistem.

        Implicit totul vine din settings (iesiri/, profilul, interfata/) și din EMAG_APP_IDLE_MINUTES; testele dau valori proprii.
        `update_job` (implicit app_update_job.UpdateJob cu modulele reale) se poate înlocui în teste, ca nimic să nu iasă pe internet.
        Ridică ValueError dacă EMAG_APP_IDLE_MINUTES e greșită (înainte să se lege orice) și OSError dacă legarea eșuează.
        """
        timeout = idle_seconds if idle_seconds is not None else idle_minutes_from_environment() * 60
        outputs = Path(outputs_dir) if outputs_dir is not None else settings.OUTPUTS_DIR
        profile = Path(profile_dir) if profile_dir is not None else settings.PROFILE_DIR
        self.runner = runner if runner is not None else AppRunner(outputs_dir=outputs, profile_dir=profile, log_path=log_path)
        self.runs = runs if runs is not None else app_runs.RunsStore(outputs)
        self.static = StaticFiles(Path(interface_dir) if interface_dir is not None else INTERFACE_DIR)
        self.token = token if token is not None else app_security.new_token()
        self.update_job = update_job if update_job is not None else app_update_job.UpdateJob()
        self.update_job.attach(is_run_busy=self.runner.is_busy, on_applied=self._stop_for_update)
        # Ține împreună „verifică cealaltă activitate” și „pornește-o pe a ta” la POST /api/runs și POST /api/update/apply.
        self.start_lock = threading.Lock()
        self._idle = IdleMonitor(timeout, clock)
        self._idle_seconds = timeout
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._stop_reason: str | None = None
        self._stop_lock = threading.Lock()
        self._httpd = _LocalHTTPServer((LOOPBACK_HOST, ANY_FREE_PORT), _Handler)
        self._httpd.app = self

    @property
    def port(self) -> int:
        """Portul ales de sistem."""
        return self._httpd.server_port

    @property
    def idle_minutes(self) -> float:
        """După câte minute fără cereri se oprește serverul (pentru mesajul din consolă)."""
        return self._idle_seconds / 60

    def page_url(self, with_token: bool = False) -> str:
        """Adresa paginii aplicației; cu `with_token` conține tokenul în fragment (de arătat doar în browser sau la --fara-browser)."""
        return app_security.build_app_url(self.port, self.token if with_token else None)

    def note_activity(self) -> None:
        """O cerere validă a sosit: repornește măsurarea inactivității."""
        self._idle.note_activity()

    def request_stop(self, reason: str) -> None:
        """Cere oprirea serverului (prima cerere decide motivul); bucla din `serve()` o vede în cel mult o perioadă de sondare."""
        with self._stop_lock:
            if self._stop_reason is None:
                self._stop_reason = reason
        self._stop.set()

    def _stop_for_update(self) -> None:
        """Chemată de job după o actualizare reușită: oprește serverul cu STOP_UPDATED, ca lansatorul să pornească varianta nouă."""
        self.request_stop(STOP_UPDATED)

    def _idle_expired(self) -> bool:
        """True dacă a trecut timpul fără cereri; cât rulează o analiză sau o actualizare, serverul nu se oprește (și ceasul se repornește)."""
        if self.runner.is_busy() or self.update_job.is_blocking():
            self._idle.note_activity()
            return False
        return self._idle.expired()

    def serve(self) -> str:
        """Servește până la oprire și întoarce motivul (STOP_SHUTDOWN, STOP_IDLE, STOP_UPDATED sau STOP_INTERRUPTED la Ctrl+C).

        Pornește verificarea versiunii noi în fundal (doar dacă settings.update_check_enabled()). La final oprește rularea în curs
        (browserul se închide), așteaptă o actualizare care tocmai scrie fișierele, oprește firul serverului și închide socket-ul.
        """
        thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": self._poll_seconds},
                                  name="server-aplicatie", daemon=True)
        thread.start()
        logger.info("aplicația ascultă pe %s:%d (oprire automată după %g minute fără cereri)", LOOPBACK_HOST, self.port, self.idle_minutes)
        self.update_job.start_check(enabled=settings.update_check_enabled())
        reason = STOP_INTERRUPTED
        try:
            while True:
                if self._stop.wait(self._poll_seconds):
                    reason = self._stop_reason or STOP_SHUTDOWN
                    break
                if self._idle_expired():
                    reason = STOP_IDLE
                    break
        except KeyboardInterrupt:
            reason = STOP_INTERRUPTED
        finally:
            self._httpd.shutdown()
            thread.join()
            if not self.runner.shutdown():
                logger.warning("rularea în curs nu s-a oprit la timp; închid aplicația oricum")
            if not self.update_job.wait_for_install(UPDATE_INSTALL_JOIN_SECONDS):
                logger.warning("actualizarea nu a terminat de scris fișierele la timp; la pornirea următoare se revine la versiunea veche")
            self._httpd.server_close()
        logger.info("aplicația s-a oprit (%s)", reason)
        return reason

    def close(self) -> None:
        """Închide socket-ul fără să fi servit (pentru cine creează serverul și renunță înainte de `serve`)."""
        self._httpd.server_close()
