"""Rulările anterioare din iesiri/: lista lor și citirea sigură a analizei și a fișierelor descărcabile, pentru aplicația locală.

Primește: folderul iesiri/ și, la citire, id-ul rulării (numele folderului) și numele fișierului. Dă înapoi: lista
`[{id, created_at, kind, orders, kept_bani, spent_bani, has_report}]` (`spent_bani` = „plătit efectiv” din analizele noi,
None la cele vechi, fără secțiunea `paid`), conținutul analiza.json (octeți JSON valid) sau un fișier
din lista albă (octeți + tip). Citește doar din iesiri/: ignoră folderele cu nume invalid, nu urmează legături simbolice
sau joncțiuni, verifică după `resolve` că niciun drum nu iese din iesiri/, limitează mărimea fișierelor și tolerează
fișierele lipsă sau stricate (o rulare întreruptă apare în listă fără cifre, nu strică lista).
Ce NU face: nu scrie, nu șterge și nu pornește rulări (app_runner.py).
"""

import os
import stat
import threading
from pathlib import Path

from emag_spend import app_security, run_ids

ANALYSIS_FILE = "analiza.json"
REPORT_FILE = "raport.html"

# Limita analiza.json: aceeași cu a vizualizatorului din site (MAX_BYTES = 25 MB în site-viewer.js). Un fișier mai mare
# nu l-ar deschide nici pagina, deci nu merită citit în memorie; analizele reale au zeci sau sute de KB.
MAX_ANALYSIS_BYTES = 25 * 1024 * 1024
# Limita unui fișier descărcabil (raport, CSV, rezumat): sute de KB în practică; 64 MB oprește un fișier umflat să umple memoria.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
# Câte rulări cele mai noi se listează: lista se citește la fiecare deschidere a paginii, deci o limităm la ce încape pe un ecran de istoric.
MAX_LISTED_RUNS = 200

ERROR_ANALYSIS_TOO_LARGE = "analysis_too_large"
ERROR_ANALYSIS_INVALID = "analysis_invalid"
ERROR_FILE_TOO_LARGE = "file_too_large"


class RunNotFound(LookupError):
    """Rularea sau fișierul cerut nu există (sau nu are voie să fie citit: legătură, în afara iesiri/, nume invalid)."""


class RunFileUnreadable(Exception):
    """Fișierul există, dar nu se poate servi (prea mare sau analiză stricată); `code` e un cod stabil pentru API."""

    def __init__(self, code: str, message: str):
        """Reține codul stabil și mesajul în română (același text e și mesajul excepției)."""
        super().__init__(message)
        self.code = code
        self.message = message


def _is_link_like(path: Path) -> bool:
    """True pentru legături simbolice și joncțiuni Windows (orice reparse point); nu le urmează și nu ridică excepții."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _plain_int(value: object) -> int | None:
    """`value` dacă e un număr întreg (nu bool, nu zecimal), altfel None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class RunsStore:
    """Rulările dintr-un folder iesiri/, citite în siguranță; sigur de folosit din mai multe fire (serverul e multi-fir)."""

    def __init__(self, outputs_dir: Path):
        """`outputs_dir` poate să nu existe încă (prima rulare): lista e atunci goală."""
        self._outputs_dir = Path(outputs_dir)
        self._summaries: dict[str, tuple[tuple[int, int], tuple[int | None, int | None, int | None]]] = {}
        self._lock = threading.Lock()

    def _base(self) -> Path | None:
        """Folderul iesiri/ rezolvat (reperul pentru toate verificările), sau None dacă nu există."""
        try:
            base = self._outputs_dir.resolve()
        except (OSError, RuntimeError):
            return None
        return base if base.is_dir() else None

    def _run_dir(self, run_id: object) -> Path | None:
        """Folderul rulării `run_id`, doar dacă id-ul e valid, folderul e real (nu legătură) și se află direct în iesiri/; altfel None."""
        base = self._base()
        if base is None or not app_security.is_valid_run_id(run_id):
            return None
        candidate = base / str(run_id)
        if _is_link_like(candidate) or not candidate.is_dir():
            return None
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if resolved.parent != base or resolved.name != run_id:
            return None
        return resolved

    def _read_file(self, run_dir: Path, name: str, max_bytes: int) -> bytes | None:
        """Octeții fișierului `name` din `run_dir`; None dacă lipsește, nu e fișier obișnuit sau e o legătură.

        Ridică RunFileUnreadable(file_too_large) peste `max_bytes`. Citește cel mult max_bytes + 1 octeți, ca un fișier
        care crește între verificare și citire să nu ocolească limita.
        """
        path = run_dir / name
        if _is_link_like(path):
            return None
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                return None
            if path.resolve(strict=True).parent != run_dir:
                return None
            with open(path, "rb") as handle:
                data = handle.read(max_bytes + 1)
        except (OSError, RuntimeError):
            return None
        if len(data) > max_bytes:
            raise RunFileUnreadable(ERROR_FILE_TOO_LARGE, f"Fișierul {name} e prea mare ca să fie deschis în aplicație.")
        return data

    def read_analysis(self, run_id: object) -> bytes:
        """Conținutul analiza.json al rulării (JSON valid, sub MAX_ANALYSIS_BYTES), ca octeți gata de trimis.

        Ridică RunNotFound dacă rularea sau fișierul lipsesc și RunFileUnreadable dacă fișierul e prea mare sau nu e JSON valid.
        """
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            raise RunNotFound(f"nu există rularea {run_id!r}")
        try:
            data = self._read_file(run_dir, ANALYSIS_FILE, MAX_ANALYSIS_BYTES)
        except RunFileUnreadable as error:
            raise RunFileUnreadable(ERROR_ANALYSIS_TOO_LARGE, "Analiza acestei rulări e prea mare ca să fie deschisă în aplicație.") from error
        if data is None:
            raise RunNotFound(f"rularea {run_id!r} nu are {ANALYSIS_FILE}")
        try:
            parsed = app_security.parse_strict_json(data)
        except (ValueError, RecursionError) as error:  # UnicodeDecodeError e tot ValueError
            raise RunFileUnreadable(ERROR_ANALYSIS_INVALID, "Fișierul analiza.json al acestei rulări e stricat. Rulează din nou analiza.") from error
        if not isinstance(parsed, dict):
            raise RunFileUnreadable(ERROR_ANALYSIS_INVALID, "Fișierul analiza.json al acestei rulări nu are forma așteptată. Rulează din nou analiza.")
        return data

    def read_download(self, run_id: object, name: object) -> tuple[bytes, str]:
        """(octeți, tip de conținut) pentru un fișier din lista albă a rulării; RunNotFound dacă numele nu e în listă sau fișierul lipsește."""
        content_type = app_security.download_content_type(name)
        run_dir = self._run_dir(run_id)
        if content_type is None or run_dir is None:
            raise RunNotFound(f"nu există fișierul {name!r} la rularea {run_id!r}")
        data = self._read_file(run_dir, str(name), MAX_DOWNLOAD_BYTES)
        if data is None:
            raise RunNotFound(f"rularea {run_id!r} nu are fișierul {name!r}")
        return data, content_type

    def _summary(self, run_dir: Path, run_id: str) -> tuple[int | None, int | None, int | None]:
        """(comenzi, bani păstrați, bani plătiți efectiv) din analiza.json; None pe fiecare câmp care lipsește, iar (None, None, None)
        dacă fișierul lipsește, e prea mare ori stricat. Analizele vechi n-au secțiunea `paid`: acolo „plătit efectiv” e None.

        Reține rezultatul după (data modificării, mărime): lista se cere des, iar analiza nu se schimbă după ce se scrie.
        """
        empty: tuple[int | None, int | None, int | None] = (None, None, None)
        path = run_dir / ANALYSIS_FILE
        try:
            info = os.lstat(path)
        except OSError:
            return empty
        if not stat.S_ISREG(info.st_mode) or _is_link_like(path) or info.st_size > MAX_ANALYSIS_BYTES:
            return empty
        signature = (info.st_mtime_ns, info.st_size)
        with self._lock:
            cached = self._summaries.get(run_id)
        if cached and cached[0] == signature:
            return cached[1]
        result = empty
        try:
            data = self._read_file(run_dir, ANALYSIS_FILE, MAX_ANALYSIS_BYTES)
            parsed = app_security.parse_strict_json(data) if data is not None else None
            if isinstance(parsed, dict):
                meta, funnel, paid = parsed.get("meta"), parsed.get("funnel"), parsed.get("paid")
                result = (
                    _plain_int(meta.get("orders")) if isinstance(meta, dict) else None,
                    _plain_int(funnel.get("kept_bani")) if isinstance(funnel, dict) else None,
                    _plain_int(paid.get("spent_bani")) if isinstance(paid, dict) else None,
                )
        except (RunFileUnreadable, ValueError, RecursionError):
            result = empty
        with self._lock:
            self._summaries[run_id] = (signature, result)
        return result

    def list_runs(self) -> list[dict]:
        """Rulările valide din iesiri/, cele mai noi întâi (cel mult MAX_LISTED_RUNS), ca dicționare gata de trimis ca JSON."""
        base = self._base()
        if base is None:
            return []
        try:
            with os.scandir(base) as scanner:
                names = [entry.name for entry in scanner if app_security.is_valid_run_id(entry.name)]
        except OSError:
            return []
        runs = []
        for run_id in sorted(names, reverse=True):
            if len(runs) >= MAX_LISTED_RUNS:
                break
            run_dir = self._run_dir(run_id)
            parsed = run_ids.parse_run_id(run_id)
            if run_dir is None or parsed is None:
                continue
            orders, kept_bani, spent_bani = self._summary(run_dir, run_id)
            report = run_dir / REPORT_FILE
            runs.append({
                "id": run_id,
                "created_at": parsed.moment.isoformat(timespec="seconds"),
                "kind": "demo" if parsed.demo else "real",
                "orders": orders,
                "kept_bani": kept_bani,
                "spent_bani": spent_bani,
                "has_report": report.is_file() and not _is_link_like(report),
            })
        return runs
