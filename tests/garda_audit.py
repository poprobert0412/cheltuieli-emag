"""Notează, prin audit hook-ul Python, ce face PROGRAMUL pe disc și în rețea în timpul unui test-gardă.

Primește: numele evenimentelor de audit urmărite (`open`, `os.remove`, `socket.*`). Dă înapoi: evenimentele atribuite
programului, adică cele cu un fișier din `emag_spend/` sau `ruleaza.py` în stivă (pytest și Python scriu și ei fișiere).
Hook-ul se instalează o singură dată (nu se poate scoate) și doar notează: un `except` din cod nu poate ascunde încălcarea.
Mai conține `isolated_program` (folderele programului mutate în tmp), `block_writes_outside` (blochează scrierile din
afara lor) și `run_flow` (fluxurile --demo, --din-cache, --sterge-sesiunea pe date inventate, fără contul real).
"""

import builtins
import contextlib
import io
import logging
import os
import shutil
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import ruleaza
from emag_spend import run_store, settings, site_demo_writer
from tests import scenario
from tests.garda_support import ENTRY_POINT, PROGRAM_DIR, relative

_PROGRAM_PREFIX = os.path.normcase(os.path.abspath(PROGRAM_DIR)) + os.sep
_ENTRY_FILE = os.path.normcase(os.path.abspath(ENTRY_POINT))
# Biții din `flags` (evenimentul `open`) care înseamnă scriere, creare sau trunchiere.
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC | getattr(os, "O_EXCL", 0)

_active: list["AuditRecorder"] = []
_installed = False
_reentrancy = threading.local()


@dataclass
class AuditEvent:
    """Un eveniment de audit atribuit programului: ce s-a cerut și de unde din cod."""

    name: str
    args: tuple
    where: str  # cel mai adânc cadru din program: `emag_spend/run_store.py:23`

    def paths(self) -> list[str]:
        """Căile (ca text) din argumentele evenimentului; ignoră descriptorii de fișier și argumentele care nu sunt căi."""
        found = []
        for value in (self.args[:1] if self.name == "open" else self.args):  # la `open` al doilea argument e modul (ex. "wb"), nu o cale
            if isinstance(value, (str, bytes, os.PathLike)):
                try:
                    found.append(os.fsdecode(value))
                except (TypeError, ValueError):
                    continue
        return found

    def is_write_open(self) -> bool:
        """True dacă e un `open` care scrie, adaugă, creează sau trunchiază (după `flags`, altfel după litera din `mode`)."""
        if self.name != "open" or len(self.args) < 3:
            return False
        _, mode, flags = self.args[:3]
        if isinstance(flags, int):
            return bool(flags & _WRITE_FLAGS)
        return isinstance(mode, str) and any(letter in mode for letter in "wax+")


@dataclass
class AuditRecorder:
    """Context manager: notează evenimentele cerute cât timp e activ.

    `names` poate conține nume exacte (`open`) sau prefixe terminate în `*` (`socket.*`).
    """

    names: tuple[str, ...]
    events: list[AuditEvent] = field(default_factory=list)

    def wants(self, event: str) -> bool:
        """True dacă numele evenimentului e în lista urmărită (exact sau prin prefix cu `*`)."""
        return any(event == name or (name.endswith("*") and event.startswith(name[:-1])) for name in self.names)

    def __enter__(self) -> "AuditRecorder":
        """Pornește notarea: instalează hook-ul (o singură dată pe proces) și înscrie recorderul ca activ."""
        _install_once()
        _active.append(self)
        return self

    def __exit__(self, *exc_info) -> None:
        """Oprește notarea pentru acest recorder."""
        _active.remove(self)


def _program_frame(frame) -> str | None:
    """`fișier:linie` al celui mai adânc cadru din stivă (pornind de la `frame`) care aparține programului; None dacă nu atinge programul."""
    while frame is not None:
        filename = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
        if filename == _ENTRY_FILE or filename.startswith(_PROGRAM_PREFIX):
            return f"{relative(Path(frame.f_code.co_filename))}:{frame.f_lineno}"
        frame = frame.f_back
    return None


def _hook(event: str, args: tuple) -> None:
    """Hook-ul de audit: atribuie evenimentul programului și îl notează la recorderele interesate."""
    if not _active or getattr(_reentrancy, "busy", False):
        return
    _reentrancy.busy = True  # fără asta, apelurile făcute de hook (abspath, relative) ar declanșa alte evenimente
    try:
        interested = [recorder for recorder in _active if recorder.wants(event)]
        if not interested:
            return
        where = _program_frame(sys._getframe(1))  # 0 = _hook; 1 = cadrul Python care a cerut operația (hook-ul e chemat din C)
        if where is None:
            return
        for recorder in interested:
            recorder.events.append(AuditEvent(event, args, where))
    finally:
        _reentrancy.busy = False


def _install_once() -> None:
    """Instalează hook-ul o singură dată pe proces (un hook de audit nu se poate dezinstala)."""
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def is_inside(path: str, roots: tuple[Path, ...]) -> bool:
    """True dacă `path` (relativ sau absolut, existent sau nu) se află în sau e egal cu unul dintre `roots`."""
    resolved = Path(os.path.realpath(path))
    return any(resolved == base or base in resolved.parents for base in (Path(os.path.realpath(r)) for r in roots))


@dataclass
class Layout:
    """Folderele temporare în care rulează programul într-un test și ce a cerut să deschidă."""

    root: Path
    out: Path  # în locul lui iesiri/ (se dă și prin --iesire)
    logs: Path  # în locul lui logs/
    site_file: Path  # în locul lui interfata/assets/demo-data.js
    profile: Path  # în locul lui .profil_browser/
    opened: list[str] = field(default_factory=list)  # adrese sau căi cerute la webbrowser.open / os.startfile

    @property
    def writable_roots(self) -> tuple[Path, ...]:
        """Singurele locuri în care programul are voie să scrie: rapoarte, jurnal, demo-data.js (folderul lui) și profil."""
        return self.out, self.logs, self.site_file.parent, self.profile


@contextlib.contextmanager
def isolated_program(monkeypatch, root: Path):
    """Redirecționează folderele programului în `root` și înlocuiește deschiderea browserului cu o înregistrare.

    La ieșire readuce jurnalul rădăcină la starea de dinainte: `setup_logging` scoate handler-ele existente
    (inclusiv cele ale pytest) și lasă un FileHandler deschis, care pe Windows ar bloca ștergerea folderului.
    """
    layout = Layout(root, root / "iesiri", root / "logs", root / "site" / "demo-data.js", root / "profil")
    monkeypatch.setattr(settings, "OUTPUTS_DIR", layout.out)
    monkeypatch.setattr(settings, "LOGS_DIR", layout.logs)
    monkeypatch.setattr(settings, "PROFILE_DIR", layout.profile)
    monkeypatch.setattr(site_demo_writer, "DEMO_DATA_JS_FILE", layout.site_file)

    def record_open(target, *args, **kwargs):
        """Înlocuiește deschiderea browserului: notează ținta cerută, fără să deschidă nimic."""
        layout.opened.append(str(target))
        return True

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, record_open)
    monkeypatch.setattr(os, "startfile", record_open, raising=False)  # doar pe Windows există
    root_logger = logging.getLogger()
    saved_handlers, saved_level = list(root_logger.handlers), root_logger.level
    try:
        yield layout
    finally:
        for handler in list(root_logger.handlers):
            if handler not in saved_handlers:
                handler.close()
        root_logger.handlers[:] = saved_handlers
        root_logger.setLevel(saved_level)


# Operațiile care schimbă sau șterg ceva pe disc: (modul, nume, pozițiile argumentelor care sunt căi AFECTATE).
# La copiere doar destinația e afectată (sursa se citește), la mutare și redenumire ambele.
_DESTRUCTIVE_OPERATIONS = (
    (os, "remove", (0,)), (os, "unlink", (0,)), (os, "rmdir", (0,)), (os, "mkdir", (0,)), (os, "rename", (0, 1)), (os, "replace", (0, 1)),
    (os, "chmod", (0,)), (os, "truncate", (0,)), (shutil, "rmtree", (0,)), (shutil, "move", (0, 1)), (shutil, "copyfile", (1,)), (shutil, "copy", (1,)),
)


def block_writes_outside(monkeypatch, allowed_roots: tuple[Path, ...]) -> list[str]:
    """Blochează (și notează) orice scriere sau ștergere făcută de PROGRAM în afara folderelor permise.

    Înlocuiește `open` (în builtins și io) și operațiile de ștergere/mutare/creare cu variante care, dacă în stivă e cod din
    program și calea e în afara `allowed_roots`, ridică PermissionError și adaugă o linie în lista întoarsă. Alt cod
    (pytest, Python) trece nestingherit. De ce blochează, nu doar notează: fluxul `--sterge-sesiunea` șterge un folder;
    dacă o regresie l-ar îndrepta spre sesiunea reală a utilizatorului, testul ar distruge-o înainte să apuce să pice.
    """
    violations: list[str] = []

    def check(operation: str, paths: tuple) -> None:
        """Notează și blochează (PermissionError) o operație a programului asupra unei căi din afara folderelor permise."""
        where = _program_frame(sys._getframe(2))  # 0 = check, 1 = wrapperul (guarded...), 2 = codul care a cerut operația
        if where is None:
            return
        for path in paths:
            if path is None or isinstance(path, int):
                continue
            try:
                text = os.fsdecode(path)
            except (TypeError, ValueError):
                continue
            if not is_inside(text, allowed_roots):
                violations.append(f"{operation}: {text} (la {where})")
                raise PermissionError(f"blocat de test: programul nu are voie să scrie sau să șteargă «{text}» (operația {operation})")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        """open() care verifică calea doar când modul scrie, adaugă, creează sau trunchiază."""
        if isinstance(mode, str) and any(letter in mode for letter in "wax+"):
            check(f"open({mode})", (file,))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)

    def guard(module, name: str, positions: tuple[int, ...]) -> None:
        """Înlocuiește o operație de ștergere, mutare sau creare cu varianta care verifică întâi căile afectate."""
        real = getattr(module, name)

        def guarded(*args, **kwargs):
            """Verifică căile afectate, apoi cheamă operația reală."""
            check(f"{module.__name__}.{name}", tuple(args[i] for i in positions if i < len(args)))
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, guarded)

    for module, name, positions in _DESTRUCTIVE_OPERATIONS:
        guard(module, name, positions)
    return violations


# Fluxurile programului care se rulează sub observație; toate pe date inventate (scenario.py, demo_data.py).
FLOWS = ("demo", "demo_si_deschide", "din_cache", "sterge_sesiunea")


def seed_cache(folder: Path) -> Path:
    """Un folder de rulare salvat, cu date inventate (scenario.py), ca sursă pentru --din-cache."""
    run_store.save_orders(folder, scenario.orders())
    run_store.save_returns(folder, scenario.returns())
    return folder


def seed_profile(profile: Path) -> None:
    """Un profil fals de browser (cu «Local State» și «Default») pe care --sterge-sesiunea are voie să-l șteargă."""
    profile.mkdir(parents=True)
    (profile / "Local State").write_text("{}", encoding="utf-8")
    (profile / "Default").mkdir()
    (profile / "Default" / "Cookies").write_text("inventat", encoding="utf-8")


def prepare_flow(flow: str, layout: Layout) -> list[str]:
    """Pregătește datele inventate ale fluxului și întoarce argumentele pentru `ruleaza.main`.

    Se cheamă ÎNAINTE de orice blocaj de scriere: pregătirea (ex. salvarea cache-ului cu run_store) scrie în afara
    folderelor permise programului, dar nu e treaba programului în timpul fluxului.
    """
    if flow == "demo":
        return ["--demo", "--iesire", str(layout.out)]
    if flow == "demo_si_deschide":
        return ["--demo", "--deschide", "--iesire", str(layout.out)]
    if flow == "din_cache":
        return ["--din-cache", str(seed_cache(layout.root / "cache")), "--iesire", str(layout.out)]
    if flow == "sterge_sesiunea":
        seed_profile(layout.profile)
        return ["--sterge-sesiunea", "--fara-confirmare"]
    raise ValueError(f"flux necunoscut: {flow}")


def run_flow(arguments: list[str]) -> int:
    """Rulează `ruleaza.main` cu argumentele pregătite de `prepare_flow`; întoarce codul de ieșire."""
    return ruleaza.main(arguments)
