"""Actualizarea din aplicația locală: verificarea versiunii noi și aplicarea ei, fiecare într-un fir de fundal, cu starea lor.

Primește: funcțiile care fac treaba (implicit cele reale: update_check.check_for_update, update_download.download_release,
update_apply.apply_update și is_git_checkout) și, prin `attach`, întrebarea „rulează o analiză?” plus ce se face după o
aplicare reușită (serverul se oprește cu STOP_UPDATED). Dă înapoi: `snapshot()` (corpul GET /api/update) și `start_apply()`
(POST /api/update/apply; ApplyRefused cu cod și mesaj pentru 409). Toate metodele sunt sigure între fire (un singur lacăt).
Stări (decis 5 oct. 2026, D18): verificare verific → la-zi | noua | eroare | dezactivat; aplicare inactiv → descarc → verific →
instalez → gata | eroare. Fiecare aplicare descarcă într-un subfolder nou din settings.UPDATE_DOWNLOAD_DIR, șters la final oricum
s-ar fi terminat (decis 6 oct. 2026, N9: update_download.download_folder). Ce NU face: nu știe de HTTP, nu atinge rețeaua și nu
scrie fișiere singur (modulele update_*.py o fac).
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from emag_spend import settings, update_apply, update_check, update_download, version
from emag_spend.update_errors import UpdateError

logger = logging.getLogger(__name__)

# Stările verificării: „verific” e doar a aplicației (cât lucrează firul); celelalte vin din update_check.UpdateCheck.status.
CHECK_VERIFYING = "verific"
CHECK_DISABLED = update_check.STATUS_DISABLED
CHECK_ERROR = update_check.STATUS_ERROR
CHECK_NEW = update_check.STATUS_NEW

APPLY_IDLE = "inactiv"
APPLY_DOWNLOADING = "descarc"
APPLY_VERIFYING = "verific"
APPLY_INSTALLING = "instalez"
APPLY_DONE = "gata"
APPLY_ERROR = "eroare"
# Cât timp aplicarea lucrează: încă o apăsare a butonului e refuzată, iar serverul nu se oprește singur de inactivitate.
APPLY_WORKING_STATES = frozenset({APPLY_DOWNLOADING, APPLY_VERIFYING, APPLY_INSTALLING})
# Cât timp nu pornește nicio analiză: în lucru sau gata (după „gata” serverul se oprește ca să repornească varianta nouă).
APPLY_BLOCKING_STATES = APPLY_WORKING_STATES | {APPLY_DONE}
# Etapele pe care le raportează download_release prin `progress` și starea în care trec.
DOWNLOAD_STAGES = {update_download.STAGE_DOWNLOAD: APPLY_DOWNLOADING, update_download.STAGE_VERIFY: APPLY_VERIFYING}

# Pauza dintre „gata” și oprirea serverului: pagina întreabă starea la fiecare secundă cât lucrează actualizarea
# (APPLY_POLL_MS în app-update.js); 3 secunde îi lasă cel puțin două ocazii să arate „gata” și mesajul de repornire,
# iar mai mult doar ar întârzia repornirea.
RESTART_DELAY_SECONDS = 3.0

ERROR_RUN_IN_PROGRESS = "run_in_progress"
ERROR_NO_UPDATE = "no_update"
ERROR_GIT_CHECKOUT = "git_checkout"
ERROR_UPDATE_IN_PROGRESS = "update_in_progress"

MESSAGE_CHECK_NOT_STARTED = "Verificarea versiunii noi nu a pornit."
MESSAGE_CHECKING = "Verific dacă există o versiune nouă…"
MESSAGE_CHECK_FAILED = "Nu am putut verifica dacă există o versiune nouă. Programul merge mai departe la fel."
MESSAGE_DOWNLOADING = "Descarc versiunea {version}…"
MESSAGE_VERIFYING = "Verific amprenta arhivei descărcate…"
MESSAGE_INSTALLING = "Instalez versiunea {version}… Nu închide fereastra programului."
MESSAGE_DONE = ("Versiunea {version} e instalată. Aplicația repornește singură, într-o filă nouă; "
                "pagina asta se poate închide.")
MESSAGE_FAILED = ("Actualizarea nu a reușit, iar programul a rămas la versiunea {version}. "
                  "Detalii în jurnalul din folderul logs.")
MESSAGE_REFUSED_RUN = "Actualizarea nu poate porni cât rulează o analiză. Așteaptă să se termine sau oprește-o."
MESSAGE_REFUSED_NO_UPDATE = "Nu există o versiune nouă de instalat."
# Textul din decizia D9 (5 oct. 2026), din aceeași sursă cu refuzul din update_apply.py: o copie git se actualizează cu git.
MESSAGE_REFUSED_GIT = update_apply.MESSAGE_GIT_CHECKOUT
MESSAGE_REFUSED_BUSY = "Actualizarea e deja în curs."
MESSAGE_REFUSED_DONE = "Actualizarea e deja instalată; aplicația repornește."


class ApplyRefused(Exception):
    """Aplicarea nu poate porni acum; `code` e codul stabil din API (409), `message` fraza în română."""

    def __init__(self, code: str, message: str):
        """Reține codul stabil și mesajul (același text e și mesajul excepției)."""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CheckView:
    """Ce știe aplicația despre versiunea nouă: câmpurile din GET /api/update plus lansarea (pentru aplicare)."""

    status: str
    latest: str | None = None
    notes: str = ""
    published: str | None = None
    page_url: str | None = None
    message: str = ""
    release: object | None = None

    @classmethod
    def from_check(cls, check: object) -> "CheckView":
        """Copia unui update_check.UpdateCheck (sau a oricărui obiect cu aceleași câmpuri)."""
        return cls(status=check.status, latest=check.latest, notes=check.notes or "", published=check.published,
                   page_url=check.page_url, message=check.message, release=check.release)

    def public(self) -> dict:
        """Câmpurile trimise paginii (fără lansare: adresele de descărcare nu au ce căuta în pagină)."""
        return {"status": self.status, "latest": self.latest, "notes": self.notes, "published": self.published,
                "page_url": self.page_url, "message": self.message}


def _never_busy() -> bool:
    """Implicitul lui `is_run_busy` până la `attach`: nicio analiză nu rulează."""
    return False


def _nothing() -> None:
    """Implicitul lui `on_applied` până la `attach`: nimic de oprit."""


class UpdateJob:
    """Verificarea și aplicarea unei versiuni noi, cu starea lor; o singură aplicare odată."""

    def __init__(self, *, check_for_update: Callable[..., object] = update_check.check_for_update,
                 download_release: Callable[..., Path] = update_download.download_release,
                 apply_update: Callable[..., object] = update_apply.apply_update,
                 is_git_checkout: Callable[[Path], bool] = update_apply.is_git_checkout,
                 root: Path | None = None, work_dir: Path | None = None, current_version: str = version.VERSION,
                 restart_delay_seconds: float = RESTART_DELAY_SECONDS, sleep: Callable[[float], None] = time.sleep):
        """Dependențele se pot înlocui în teste (fără rețea, fără scrieri); implicit rădăcina programului și settings.UPDATE_DOWNLOAD_DIR.

        `work_dir` e folderul descărcărilor: fiecare aplicare primește în el un subfolder nou, șters la final (N9).
        """
        self._check_for_update = check_for_update
        self._download_release = download_release
        self._apply_update = apply_update
        self._is_git_checkout = is_git_checkout
        self._root = Path(root) if root is not None else settings.PROJECT_ROOT
        self._work_dir = Path(work_dir) if work_dir is not None else settings.UPDATE_DOWNLOAD_DIR
        self._current = current_version
        self._restart_delay = restart_delay_seconds
        self._sleep = sleep
        self._is_run_busy: Callable[[], bool] = _never_busy
        self._on_applied: Callable[[], None] = _nothing
        self._lock = threading.Lock()
        self._check = CheckView(status=CHECK_DISABLED, message=MESSAGE_CHECK_NOT_STARTED)
        self._check_started = False
        self._apply_state = APPLY_IDLE
        self._apply_message = ""
        self._to_version: str | None = None
        self._apply_thread: threading.Thread | None = None

    def attach(self, *, is_run_busy: Callable[[], bool], on_applied: Callable[[], None]) -> None:
        """Leagă job-ul de server: `is_run_busy()` = rulează o analiză?; `on_applied()` = cheamă după „gata” (oprește serverul)."""
        with self._lock:
            self._is_run_busy = is_run_busy
            self._on_applied = on_applied

    # ---------- citire ----------

    def snapshot(self) -> dict:
        """Corpul GET /api/update: versiunea curentă, verificarea și aplicarea (copii: cine le primește nu strică starea)."""
        with self._lock:
            return {
                "current": self._current,
                "check": self._check.public(),
                "apply": self._apply_public(),
            }

    def _apply_public(self) -> dict:
        """Starea aplicării în forma din API (apelat sub lacăt)."""
        return {"state": self._apply_state, "message": self._apply_message, "to_version": self._to_version}

    def is_blocking(self) -> bool:
        """True cât timp aplicarea lucrează sau s-a terminat cu bine: nu pornește nicio analiză și serverul nu se oprește de inactivitate."""
        with self._lock:
            return self._apply_state in APPLY_BLOCKING_STATES

    # ---------- verificarea ----------

    def start_check(self, *, enabled: bool) -> None:
        """Pornește verificarea o singură dată: în fundal dacă e permisă, altfel ia pe loc răspunsul „dezactivat” (fără rețea)."""
        with self._lock:
            if self._check_started:
                return
            self._check_started = True
            if enabled:
                self._check = CheckView(status=CHECK_VERIFYING, message=MESSAGE_CHECKING)
        if not enabled:
            self._store_check(self._run_check(enabled=False))
            return
        threading.Thread(target=lambda: self._store_check(self._run_check(enabled=True)), name="verificare-versiune", daemon=True).start()

    def _run_check(self, *, enabled: bool) -> CheckView:
        """Cheamă check_for_update și întoarce copia rezultatului; o excepție neașteptată devine „eroare” (verificarea nu oprește aplicația)."""
        try:
            return CheckView.from_check(self._check_for_update(enabled=enabled))
        except Exception:  # contractul spune „nu ridică niciodată”; dacă totuși o face, aplicația merge mai departe
            logger.exception("verificarea versiunii noi a eșuat neașteptat")
            return CheckView(status=CHECK_ERROR, message=MESSAGE_CHECK_FAILED)

    def _store_check(self, check: CheckView) -> None:
        """Reține rezultatul verificării (jurnalul îl scrie deja update_check.check_for_update)."""
        with self._lock:
            self._check = check

    # ---------- aplicarea ----------

    def start_apply(self) -> dict:
        """Pornește descărcarea și instalarea în fundal; întoarce starea aplicării (pentru 202).

        Ridică ApplyRefused (409) dacă: o aplicare e în curs sau gata, rulează o analiză, nu există o versiune nouă, ori folderul e copie git.
        Verificarea și trecerea în „descarc” se fac sub același lacăt, deci două cereri simultane nu pornesc două aplicări.
        """
        with self._lock:
            if self._apply_state in APPLY_WORKING_STATES:
                raise ApplyRefused(ERROR_UPDATE_IN_PROGRESS, MESSAGE_REFUSED_BUSY)
            if self._apply_state == APPLY_DONE:
                raise ApplyRefused(ERROR_UPDATE_IN_PROGRESS, MESSAGE_REFUSED_DONE)
            if self._is_run_busy():
                raise ApplyRefused(ERROR_RUN_IN_PROGRESS, MESSAGE_REFUSED_RUN)
            release = self._check.release
            if self._check.status != CHECK_NEW or release is None:
                raise ApplyRefused(ERROR_NO_UPDATE, MESSAGE_REFUSED_NO_UPDATE)
            if self._is_git_checkout(self._root):
                raise ApplyRefused(ERROR_GIT_CHECKOUT, MESSAGE_REFUSED_GIT)
            self._to_version = release.version
            self._apply_state, self._apply_message = APPLY_DOWNLOADING, MESSAGE_DOWNLOADING.format(version=release.version)
            self._apply_thread = threading.Thread(target=self._apply, args=(release,), name="actualizare", daemon=True)
            thread, state = self._apply_thread, self._apply_public()
        logger.info("pornesc actualizarea de la %s la %s", self._current, release.version)
        thread.start()
        return state

    def _set_apply(self, state: str, message: str) -> None:
        """Mută aplicarea în `state` cu mesajul dat."""
        with self._lock:
            self._apply_state, self._apply_message = state, message

    def _on_download_stage(self, stage: str, *_ignored) -> None:
        """`progress` dat lui download_release: „descarc” / „verific” mută starea; alte etape (sau apeluri după terminare) se ignoră."""
        state = DOWNLOAD_STAGES.get(stage)
        if state is None:
            return
        with self._lock:
            if self._apply_state not in (APPLY_DOWNLOADING, APPLY_VERIFYING):
                return
            self._apply_state = state
            self._apply_message = MESSAGE_VERIFYING if state == APPLY_VERIFYING else MESSAGE_DOWNLOADING.format(version=self._to_version)

    def _apply(self, release: object) -> None:
        """Corpul firului: descarcă, verifică, instalează; la succes „gata” și, după RESTART_DELAY_SECONDS, `on_applied`. Nu ridică nimic.

        Descărcarea are subfolderul ei (download_folder), care dispare cu arhiva din el înainte de „gata” sau „eroare”.
        """
        try:
            with update_download.download_folder(self._work_dir) as folder:
                archive = self._download_release(release, folder, progress=self._on_download_stage)
                self._set_apply(APPLY_INSTALLING, MESSAGE_INSTALLING.format(version=release.version))
                self._apply_update(archive, self._root, release.version)
        except UpdateError as error:
            logger.warning("actualizarea la %s a eșuat: %s", release.version, error)
            self._set_apply(APPLY_ERROR, str(error) or MESSAGE_FAILED.format(version=self._current))
            return
        except BaseException:  # firul nu are cine să prindă: orice rămâne necaptat ar lăsa starea blocată pe „instalez”
            logger.exception("actualizarea la %s a eșuat neașteptat", release.version)
            self._set_apply(APPLY_ERROR, MESSAGE_FAILED.format(version=self._current))
            return
        logger.info("actualizarea la %s s-a instalat; aplicația repornește", release.version)
        self._set_apply(APPLY_DONE, MESSAGE_DONE.format(version=release.version))
        self._sleep(self._restart_delay)
        with self._lock:
            on_applied = self._on_applied
        try:
            on_applied()
        except Exception:
            logger.exception("oprirea aplicației după actualizare a eșuat")

    def wait_for_install(self, timeout: float) -> bool:
        """La oprirea serverului: dacă tocmai se instalează fișierele, așteaptă (cel mult `timeout` s); True dacă nu mai e nimic în lucru.

        Descărcarea și verificarea nu se așteaptă: întrerupte, nu lasă nimic schimbat în folderul programului.
        """
        with self._lock:
            thread = self._apply_thread if self._apply_state == APPLY_INSTALLING else None
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()
