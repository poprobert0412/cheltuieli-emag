"""Rulează analiza într-un fir de fundal și ține starea ei, pentru aplicația locală (app_server.py).

Primește: cererea de pornire (mod real sau demo, prag) și cererile de anulare / ștergere a sesiunii. Dă înapoi: starea curentă
(`snapshot`, forma din GET /api/state) și id-ul rulării pornite. O singură rulare odată (a doua cerere primește RunnerBusy).
Pipeline-ul rulează în firul lui (Playwright își face bucla asyncio acolo), raportează prin `Progress` și se oprește cooperant.
Stări: idle -> starting -> [waiting_login] -> fetching_orders -> fetching_returns -> analyzing -> done | error | cancelled; orice eroare
devine cod stabil + mesaj în română (app_errors.py). Ce NU face: nu știe de HTTP, nu scrie decât ce scrie pipeline-ul (iesiri/),
nu șterge decât sesiunea, la cerere, și la demo nu rescrie interfata/assets/demo-data.js (fișier urmărit de git)."""

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from emag_spend import run_ids, run_pipeline, session_cleaner, settings
from emag_spend.app_errors import CODE_UNEXPECTED, HUMAN_MESSAGE_ERRORS, classify_error
from emag_spend.progress import PIPELINE_PHASES, Progress, RunCancelled

logger = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_WAITING_LOGIN = "waiting_login"
STATE_FETCHING_ORDERS = "fetching_orders"
STATE_FETCHING_RETURNS = "fetching_returns"
STATE_ANALYZING = "analyzing"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_CANCELLED = "cancelled"
# Cât timp rularea e în curs: aplicația nu închide serverul și nu pornește altă rulare.
ACTIVE_STATES = frozenset({STATE_STARTING, STATE_WAITING_LOGIN, STATE_FETCHING_ORDERS, STATE_FETCHING_RETURNS, STATE_ANALYZING})
# Stările în care contorul „făcute din total” are sens în mesaj.
COUNTED_STATES = frozenset({STATE_FETCHING_ORDERS, STATE_FETCHING_RETURNS})

MODE_REAL = "real"
MODE_DEMO = "demo"
MODES = frozenset({MODE_REAL, MODE_DEMO})
ALLOWED_REQUEST_KEYS = frozenset({"mode", "threshold_lei"})

# Cât așteaptă oprirea serverului ca rularea anulată să-și închidă browserul înainte să renunțe la ea (firul e daemon:
# nu blochează ieșirea). Anularea cooperantă se vede în ~2 s (LOGIN_POLL_SECONDS) până la câteva secunde (pagină în încărcare).
DEFAULT_SHUTDOWN_JOIN_SECONDS = 15

CANCELLING_MESSAGE = "Opresc analiza… se termină în câteva secunde, apoi se închide și fereastra browserului."
STATE_MESSAGES = {
    STATE_IDLE: "Gata de pornire. Apasă «Pornește analiza».",
    STATE_STARTING: "Pornesc analiza…",
    STATE_WAITING_LOGIN: "Loghează-te în fereastra de browser care s-a deschis; parola și codul 2FA le introduci tu.",
    STATE_FETCHING_ORDERS: "Citesc comenzile din contul tău eMAG…",
    STATE_FETCHING_RETURNS: "Citesc retururile din contul tău eMAG…",
    STATE_ANALYZING: "Calculez cât ai cheltuit…",
    STATE_DONE: "Gata: raportul e pregătit.",
    STATE_ERROR: "Analiza s-a oprit cu o eroare.",
    STATE_CANCELLED: "Analiza a fost oprită la cererea ta. Ce s-a citit până atunci rămâne în folderul iesiri.",
}


class RunnerBusy(RuntimeError):
    """O rulare e deja în curs: aplicația răspunde 409 la o a doua pornire (sau la ștergerea sesiunii în timpul ei)."""


class InvalidRunRequest(ValueError):
    """Cererea de pornire are o formă greșită; `code` e codul stabil din API, iar mesajul e în română."""

    def __init__(self, code: str, message: str):
        """Reține codul stabil și mesajul în română (același text e și mesajul excepției)."""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RunRequest:
    """Ce a cerut utilizatorul: modul și pragul pentru „achiziție mare” (în lei, deja validat)."""

    mode: str
    threshold_lei: float


def parse_run_request(payload: object) -> RunRequest:
    """Validează corpul POST /api/runs (`{"mode": ..., "threshold_lei": ...?}`); ridică InvalidRunRequest cu mesaj în română.

    Pragul respectă aceleași limite ca `--prag` din linia de comandă: număr finit între 0 și settings.MAX_BIG_PURCHASE_THRESHOLD_LEI.
    Cheile necunoscute se refuză (o greșeală de scriere n-ar trebui să treacă neobservată).
    """
    if not isinstance(payload, dict):
        raise InvalidRunRequest("invalid_request", "Cererea trebuie să fie un obiect JSON, ex. {\"mode\": \"demo\"}.")
    unknown = sorted(str(key) for key in set(payload) - ALLOWED_REQUEST_KEYS)
    if unknown:
        raise InvalidRunRequest("invalid_request", f"Cererea conține câmpuri necunoscute: {', '.join(unknown)}.")
    mode = payload.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        raise InvalidRunRequest("invalid_mode", "Câmpul «mode» trebuie să fie «real» (contul tău eMAG) sau «demo» (date inventate).")
    threshold = payload.get("threshold_lei")
    if threshold is None:
        return RunRequest(mode, float(settings.BIG_PURCHASE_THRESHOLD_LEI))
    maximum = settings.MAX_BIG_PURCHASE_THRESHOLD_LEI
    valid = isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and (
        isinstance(threshold, int) or math.isfinite(threshold)) and 0 <= threshold <= maximum
    if not valid:
        limit = f"{maximum:,}".replace(",", ".")
        raise InvalidRunRequest("invalid_threshold", f"Pragul trebuie să fie un număr între 0 și {limit} de lei.")
    return RunRequest(mode, float(threshold))


def session_saved(profile_dir: Path) -> bool:
    """True dacă pe disc există un profil de browser salvat (nu garantează că sesiunea eMAG e încă validă: doar că e ceva de șters)."""
    try:
        return Path(profile_dir).is_dir() and any((Path(profile_dir) / marker).exists() for marker in session_cleaner.CHROMIUM_PROFILE_MARKERS)
    except OSError:
        return False


def describe_session_deletion(result: session_cleaner.SessionDeleteResult) -> str:
    """Mesajul în română pentru rezultatul ștergerii sesiunii, scris pentru aplicație (nu trimite la login.bat); refuzurile reiau textul din linia de comandă."""
    if result.status is session_cleaner.SessionDeleteStatus.DELETED:
        return ("Sesiunea eMAG salvată a fost ștearsă. Data viitoare te vei loga din nou când pornești analiza. "
                "Ca să invalidezi orice sesiune veche, poți schimba și parola eMAG.")
    if result.status is session_cleaner.SessionDeleteStatus.NOTHING_TO_DELETE:
        return "Nu exista nicio sesiune salvată, deci nu am șters nimic."
    return session_cleaner.describe_result(result)


class _RunnerProgress(Progress):
    """Raportorul activ: pipeline-ul îl cheamă din firul lui, iar rezultatul ajunge în starea AppRunner-ului."""

    def __init__(self, runner: "AppRunner"):
        """Leagă raportorul de runner-ul a cărui stare o actualizează."""
        self._runner = runner

    def phase(self, name: str, total: int | None = None) -> None:
        """Trece rularea în starea `name` (o fază cunoscută) și pornește contorul de la 0."""
        self._runner._set_phase(name, total)

    def advance(self, done: int, total: int | None = None) -> None:
        """Actualizează „făcute din total” al fazei curente."""
        self._runner._set_counter(done, total)

    def message(self, text: str) -> None:
        """Pune un text propriu lângă bara de progres, până la următoarea fază."""
        self._runner._set_message(text)

    def cancel_requested(self) -> bool:
        """True după ce utilizatorul a cerut oprirea."""
        return self._runner._cancel.is_set()


class AppRunner:
    """Pornește și urmărește o rulare odată, în fir de fundal; toate metodele sunt sigure între fire."""

    def __init__(self, *, outputs_dir: Path, profile_dir: Path,
                 pipeline: Callable[..., Path] | None = None, log_path: Path | None = None,
                 clock: Callable[[], datetime] = datetime.now):
        """`pipeline` se poate înlocui în teste (implicit run_pipeline.run, căutat la fiecare rulare); `log_path` ajunge în run_info.json."""
        self._outputs_dir = Path(outputs_dir)
        self._profile_dir = Path(profile_dir)
        self._pipeline = pipeline
        self._log_path = log_path
        self._clock = clock
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = STATE_IDLE
        self._custom_message: str | None = None
        self._done = 0
        self._total: int | None = None
        self._run_id: str | None = None
        self._started_at: str | None = None
        self._error: dict | None = None

    # ---------- citire ----------

    def _current_message(self) -> str:
        """Mesajul stării curente (sub lacăt): oprirea cerută, textul propriu al fazei sau textul standard, cu contorul unde are sens."""
        if self._state in ACTIVE_STATES and self._cancel.is_set():
            return CANCELLING_MESSAGE
        if self._state == STATE_ERROR and self._error:
            return self._error["message"]
        text = self._custom_message or STATE_MESSAGES[self._state]
        if self._state in COUNTED_STATES and self._total:
            text += f" ({self._done} din {self._total})"
        return text

    def snapshot(self) -> dict:
        """Starea curentă în forma din GET /api/state (copie: cine o primește n-o poate strica pe a runner-ului)."""
        with self._lock:
            state = {
                "state": self._state,
                "message": self._current_message(),
                "progress": {"phase": self._state, "done": self._done, "total": self._total},
                "run_id": self._run_id,
                "started_at": self._started_at,
                "error": dict(self._error) if self._error else None,
            }
        state["session_saved"] = session_saved(self._profile_dir)
        return state

    def is_busy(self) -> bool:
        """True cât timp o rulare e în curs (serverul nu se oprește singur în acest timp)."""
        with self._lock:
            return self._state in ACTIVE_STATES

    # ---------- comenzi ----------

    def _free_run_id(self, demo: bool) -> str:
        """Un id de rulare care nu există încă în iesiri/ (două rulări în aceeași secundă n-ar avea voie să-și amestece fișierele)."""
        moment = self._clock().replace(microsecond=0)
        while (self._outputs_dir / run_ids.new_run_id(moment, demo)).exists():
            moment += timedelta(seconds=1)
        return run_ids.new_run_id(moment, demo)

    def start(self, request: RunRequest) -> str:
        """Pornește rularea în fundal și întoarce id-ul ei; ridică RunnerBusy dacă alta e în curs."""
        with self._lock:
            if self._state in ACTIVE_STATES:
                raise RunnerBusy("o rulare e deja în curs")
            run_id = self._free_run_id(request.mode == MODE_DEMO)
            self._cancel.clear()
            self._state, self._custom_message = STATE_STARTING, None
            self._done, self._total = 0, None
            self._run_id, self._error = run_id, None
            self._started_at = self._clock().isoformat(timespec="seconds")
            self._thread = threading.Thread(target=self._work, args=(run_id, request), name=f"analiza-{run_id}", daemon=True)
            thread = self._thread
        logger.info("pornesc rularea %s (mod %s, prag %s lei)", run_id, request.mode, request.threshold_lei)
        thread.start()
        return run_id

    def cancel(self) -> bool:
        """Cere oprirea rulării în curs; True dacă era una (oprirea se face cooperant, nu pe loc), False dacă nu rula nimic."""
        with self._lock:
            if self._state not in ACTIVE_STATES:
                return False
            self._cancel.set()
        logger.info("oprirea rulării a fost cerută de utilizator")
        return True

    def join(self, timeout: float | None = None) -> bool:
        """Așteaptă sfârșitul firului de rulare (cel mult `timeout` secunde); True dacă s-a terminat sau nu rula."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def shutdown(self, timeout: float = DEFAULT_SHUTDOWN_JOIN_SECONDS) -> bool:
        """La oprirea aplicației: cere oprirea rulării în curs și așteaptă să-și închidă browserul; False dacă n-a apucat în `timeout`."""
        self.cancel()
        return self.join(timeout)

    def delete_session(self) -> session_cleaner.SessionDeleteResult:
        """Șterge sesiunea eMAG salvată (aceleași garanții ca --sterge-sesiunea); RunnerBusy cât o rulare folosește profilul.

        Confirmarea („DA”) o verifică apelantul; lacătul rămâne luat cât durează ștergerea, ca nicio rulare să nu pornească pe un profil pe jumătate șters.
        """
        with self._lock:
            if self._state in ACTIVE_STATES:
                raise RunnerBusy("sesiunea nu se poate șterge cât rulează o analiză")
            result = session_cleaner.delete_session(self._profile_dir, lambda path: True)
        logger.info("ștergere sesiune din aplicație: %s (fișiere șterse %d, eșuate %d)",
                    result.status.value, result.deleted_files, result.failed_entries)
        return result

    # ---------- apelate din firul rulării (prin _RunnerProgress) ----------

    def _set_phase(self, name: str, total: int | None) -> None:
        """Mută rularea în faza `name`; fazele necunoscute sau apelurile după terminare se ignoră."""
        with self._lock:
            if name in PIPELINE_PHASES and self._state in ACTIVE_STATES:
                self._state, self._custom_message = name, None
                self._done, self._total = 0, total

    def _set_counter(self, done: int, total: int | None) -> None:
        """Actualizează contorul fazei curente."""
        with self._lock:
            if self._state in ACTIVE_STATES:
                self._done, self._total = done, total

    def _set_message(self, text: str) -> None:
        """Reține textul propriu al fazei curente."""
        with self._lock:
            if self._state in ACTIVE_STATES:
                self._custom_message = text

    def _finish(self, state: str, error: dict | None = None) -> None:
        """Încheie rularea în starea `state` (done, error sau cancelled)."""
        with self._lock:
            self._state, self._custom_message, self._error = state, None, error

    def _work(self, run_id: str, request: RunRequest) -> None:
        """Corpul firului: rulează pipeline-ul și transformă rezultatul sau eroarea într-o stare finală; nu ridică nimic în afară."""
        options = run_pipeline.RunOptions(
            threshold_lei=request.threshold_lei,
            output_dir=self._outputs_dir,
            demo=request.mode == MODE_DEMO,
            update_site_demo_data=False,
            run_folder_name=run_id,
        )
        pipeline = self._pipeline or run_pipeline.run
        try:
            pipeline(options, log_path=self._log_path, progress=_RunnerProgress(self))
        except RunCancelled:
            logger.info("rularea %s a fost oprită la cererea utilizatorului", run_id)
            self._finish(STATE_CANCELLED)
        except BaseException as error:  # firul nu are cine să prindă: orice rămâne necaptat ar lăsa starea blocată pe „în curs”
            run_error = classify_error(error)
            if run_error.code == CODE_UNEXPECTED and not isinstance(error, HUMAN_MESSAGE_ERRORS):
                logger.exception("rularea %s a eșuat neașteptat", run_id)
            else:
                logger.error("rularea %s a eșuat (%s): %s", run_id, run_error.code, str(error).splitlines()[0] if str(error) else type(error).__name__)
            self._finish(STATE_ERROR, {"code": run_error.code, "message": run_error.message})
        else:
            logger.info("rularea %s s-a terminat", run_id)
            self._finish(STATE_DONE)
