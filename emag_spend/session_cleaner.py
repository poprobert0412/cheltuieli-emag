"""Șterge sesiunea eMAG salvată: folderul profilului de browser (implicit .profil_browser).

Primește: calea profilului și o funcție `confirm` care întreabă utilizatorul. Dă înapoi un
SessionDeleteResult (ce s-a șters, ce a rămas, de ce s-a refuzat) și mesajul lui în română.
Siguranță: șterge DOAR un folder care seamănă cu un profil Chromium și nu e rădăcină de disc, folderul
personal, profilul real de browser, folderul programului sau un părinte al lor; nu urmează legături.
Nu pornește browserul (fără Playwright) și nu schimbă parola eMAG.
"""

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from emag_spend import settings

# Răspunsul care confirmă ștergerea; orice altceva (sau lipsa răspunsului) anulează.
CONFIRMATION_WORD = "DA"

# Un profil Chromium (Edge/Chrome) are mereu fișierul «Local State» sau subfolderul «Default». Fără ele,
# folderul nu e un profil de browser: probabil EMAG_PROFILE_DIR e setat greșit și nu are voie să-l ștergem.
CHROMIUM_PROFILE_MARKERS = ("Local State", "Default")

# Unde țin Edge/Chrome profilul REAL al utilizatorului (parole, marcaje, istoric), relativ la folderul personal.
# Are semnătura Chromium, deci semnătura singură nu l-ar apăra de o setare greșită a EMAG_PROFILE_DIR;
# ștergerea lui ar fi o pagubă mult mai mare decât sesiunea eMAG. Sunt locuri fixate de sistemele de operare.
REAL_BROWSER_PROFILE_LOCATIONS = (
    ("AppData", "Local", "Microsoft", "Edge", "User Data"),
    ("AppData", "Local", "Google", "Chrome", "User Data"),
    ("Library", "Application Support", "Google", "Chrome"),
    ("Library", "Application Support", "Microsoft Edge"),
    (".config", "google-chrome"),
    (".config", "chromium"),
    (".config", "microsoft-edge"),
)


class SessionDeleteStatus(Enum):
    """Cum s-a încheiat o cerere de ștergere a sesiunii."""

    DELETED = "deleted"  # profilul a fost șters complet
    NOTHING_TO_DELETE = "nothing_to_delete"  # folderul lipsește sau e gol: nu e eroare
    CANCELLED = "cancelled"  # utilizatorul nu a confirmat: nimic șters
    REFUSED = "refused"  # cale periculoasă sau care nu seamănă a profil: nimic șters
    INCOMPLETE = "incomplete"  # unele fișiere n-au putut fi șterse (de obicei Edge deschis)


@dataclass(frozen=True)
class SessionDeleteResult:
    """Rezultatul tipizat al ștergerii; `reason` se completează doar la REFUSED."""

    status: SessionDeleteStatus
    profile_dir: Path  # calea rezolvată, exact cea arătată utilizatorului
    reason: str = ""
    deleted_files: int = 0
    deleted_folders: int = 0
    failed_entries: int = 0
    blocked_by_other_program: bool = False  # True: ștergerea a primit PermissionError (fișier în uz)
    error_text: str = ""  # prima eroare care NU e de permisiune, dacă a existat

    @property
    def succeeded(self) -> bool:
        """True dacă nu e nimic de reparat (șters, nimic de șters sau anulat); False la refuz sau ștergere incompletă."""
        return self.status in (SessionDeleteStatus.DELETED, SessionDeleteStatus.NOTHING_TO_DELETE,
                               SessionDeleteStatus.CANCELLED)


@dataclass
class _Tally:
    """Contor intern al unei ștergeri: ce s-a șters și ce a eșuat."""

    files: int = 0
    folders: int = 0
    failed: int = 0
    permission_denied: bool = False
    other_error: str = ""

    def record_failure(self, error: OSError) -> None:
        """Numără un element care n-a putut fi șters și reține tipul erorii."""
        self.failed += 1
        if isinstance(error, PermissionError):
            self.permission_denied = True
        elif not self.other_error:
            self.other_error = error.strerror or type(error).__name__


def _is_link(path: Path) -> bool:
    """True pentru legături simbolice și joncțiuni Windows (orice reparse point); nu le urmează."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _delete_file(path: Path) -> None:
    """Șterge un fișier; pe Windows scoate întâi atributul „doar citire”, care altfel blochează ștergerea."""
    try:
        os.unlink(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)


def _delete_link(path: Path) -> None:
    """Șterge LEGĂTURA, nu ținta ei: joncțiunile și legăturile de folder pe Windows se scot cu rmdir, restul cu unlink."""
    is_folder_link = bool(getattr(os.lstat(path), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY)
    (os.rmdir if is_folder_link else os.unlink)(path)


def _remove_tree(root: Path) -> _Tally:
    """Șterge `root` și tot ce conține, fără să urmeze legături; continuă după erori și le numără.

    Parcurgere proprie (nu os.walk / shutil.rmtree): pe Windows os.walk intră în joncțiuni, deci ar șterge
    conținutul altui folder. Un folder rămâne dacă a eșuat ceva în el (nu încercăm rmdir pe un folder nevid).
    """
    tally = _Tally()
    folders: list[Path] = []  # în ordinea descoperirii: părinții înaintea copiilor
    blocked: set[Path] = set()  # foldere în care a rămas ceva, deci nu se pot șterge
    pending = [root]
    while pending:
        folder = pending.pop()
        folders.append(folder)
        try:
            with os.scandir(folder) as scanner:
                entries = [(Path(entry.path), entry.is_dir(follow_symlinks=False)) for entry in scanner]
        except OSError as error:
            tally.record_failure(error)
            blocked.add(folder)
            continue
        for path, is_dir in entries:
            link = _is_link(path)
            if is_dir and not link:
                pending.append(path)
                continue
            try:
                (_delete_link if link else _delete_file)(path)
                tally.files += 1
            except OSError as error:
                tally.record_failure(error)
                blocked.add(folder)
    for folder in reversed(folders):  # copiii înaintea părinților
        if folder not in blocked:
            try:
                os.rmdir(folder)
                tally.folders += 1
                continue
            except OSError as error:
                tally.record_failure(error)
        if folder != root:
            blocked.add(folder.parent)
    return tally


def _is_inside_or_equal(path: Path, base: Path) -> bool:
    """True dacă `path` e `base` sau se află în interiorul lui."""
    return path == base or base in path.parents


def _forbidden_reason(resolved: Path, project_root: Path, home_dir: Path) -> str | None:
    """Motivul pentru care calea nu are voie să fie ștearsă (în română), sau None dacă e în regulă."""
    if resolved.parent == resolved:
        return "Calea e rădăcina unui disc"
    for label, protected in (("folderul tău personal", home_dir), ("folderul programului", project_root)):
        protected = protected.resolve()
        if _is_inside_or_equal(protected, resolved):
            return f"Calea e {label} sau un folder care îl conține"
    for parts in REAL_BROWSER_PROFILE_LOCATIONS:
        real_profile = home_dir.joinpath(*parts).resolve()
        if _is_inside_or_equal(resolved, real_profile) or _is_inside_or_equal(real_profile, resolved):
            return "Calea e profilul tău real de Edge/Chrome (parole, marcaje, istoric), nu sesiunea programului"
    return None


def delete_session(
    profile_dir: Path,
    confirm: Callable[[Path], bool],
    *,
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> SessionDeleteResult:
    """Șterge profilul de browser de la `profile_dir`, doar dacă toate verificările de siguranță trec.

    `confirm(cale_completă)` se cheamă ultimul, doar când e ceva de șters, și trebuie să întoarcă exact True.
    `project_root` și `home_dir` se pot da în teste; implicit: folderul programului și folderul personal.
    Nu ridică excepții pentru erori de fișiere: le întoarce în rezultat (status REFUSED sau INCOMPLETE).
    """
    project = Path(project_root) if project_root is not None else settings.PROJECT_ROOT
    try:
        home = Path(home_dir) if home_dir is not None else Path.home()
        given = Path(os.path.abspath(profile_dir))  # absolută, dar fără să urmeze legăturile
        resolved = given.resolve()
        forbidden = _forbidden_reason(resolved, project, home)
    except (OSError, ValueError, RuntimeError) as error:
        # RuntimeError: Path.home() nu știe folderul personal; mai bine refuzăm decât să ghicim
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, Path(str(profile_dir)),
                                   reason=f"Nu pot verifica calea ({error})")
    if forbidden:
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, resolved, reason=forbidden)
    if _is_link(given):
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, resolved,
                                   reason="Calea e o legătură simbolică sau o joncțiune; n-o urmez ca să nu șterg alt folder")
    if not resolved.exists():
        return SessionDeleteResult(SessionDeleteStatus.NOTHING_TO_DELETE, resolved)
    if not resolved.is_dir():
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, resolved, reason="Calea nu e un folder")
    try:
        has_content = any(True for _ in resolved.iterdir())
    except OSError as error:
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, resolved,
                                   reason=f"Nu pot citi folderul ({error.strerror or type(error).__name__})")
    if not has_content:
        return SessionDeleteResult(SessionDeleteStatus.NOTHING_TO_DELETE, resolved)
    if not any((resolved / marker).exists() for marker in CHROMIUM_PROFILE_MARKERS):
        markers = " sau ".join(f"«{marker}»" for marker in CHROMIUM_PROFILE_MARKERS)
        return SessionDeleteResult(SessionDeleteStatus.REFUSED, resolved,
                                   reason=f"Folderul nu seamănă cu un profil de browser (nu conține {markers})")
    if confirm(resolved) is not True:
        return SessionDeleteResult(SessionDeleteStatus.CANCELLED, resolved)
    tally = _remove_tree(resolved)
    status = SessionDeleteStatus.INCOMPLETE if tally.failed else SessionDeleteStatus.DELETED
    return SessionDeleteResult(status, resolved, deleted_files=tally.files, deleted_folders=tally.folders,
                               failed_entries=tally.failed, blocked_by_other_program=tally.permission_denied,
                               error_text=tally.other_error)


def confirm_on_terminal(
    path: Path,
    ask: Callable[[str], str] | None = None,
    say: Callable[[str], None] | None = None,
) -> bool:
    """Arată calea completă și cere să scrii exact DA; orice altceva, EOF sau Ctrl+C înseamnă „nu”.

    `ask` și `say` se pot înlocui în teste; implicit input și print, căutate la apel (nu la definiție).
    """
    ask = ask or input
    say = say or print
    say("Urmează să se șteargă DEFINITIV sesiunea eMAG salvată pe acest calculator (folderul de mai jos și tot ce conține):")
    say(f"    {path}")
    say("Ștergerea nu se poate anula; data viitoare va trebui să te loghezi din nou.")
    try:
        answer = ask(f"Scrie exact {CONFIRMATION_WORD} (cu majuscule) ca să continui; orice altceva anulează: ")
    except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
        # fără terminal (stdin închis, pythonw) sau Ctrl+C: nu putem fi siguri că utilizatorul a vrut, deci nu ștergem
        say("")
        return False
    return answer.strip() == CONFIRMATION_WORD


def describe_result(result: SessionDeleteResult) -> str:
    """Mesajul în română pentru utilizator, potrivit rezultatului (fără traceback, cu pasul următor)."""
    counts = f"fișiere: {result.deleted_files}, foldere: {result.deleted_folders}"
    path_line = f"Folderul vizat: {result.profile_dir}"
    if result.status is SessionDeleteStatus.DELETED:
        return (
            f"Sesiunea eMAG salvată a fost ștearsă.\nCe s-a șters: folderul {result.profile_dir} ({counts}).\n"
            "Pentru a invalida orice sesiune veche poți schimba parola eMAG.\n"
            "Data viitoare va trebui să te loghezi din nou (login.bat sau: python ruleaza.py --doar-login)."
        )
    if result.status is SessionDeleteStatus.NOTHING_TO_DELETE:
        return "Nu există nicio sesiune salvată (folderul profilului lipsește sau e gol). Nu am șters nimic."
    if result.status is SessionDeleteStatus.CANCELLED:
        return "Anulat: nu am șters nimic."
    if result.status is SessionDeleteStatus.REFUSED:
        return (
            f"EROARE: nu am șters nimic. {result.reason}.\n{path_line}\n"
            f"Sesiunea programului e în folderul {settings.DEFAULT_PROFILE_DIR_NAME} din folderul programului; "
            "dacă ai setat variabila de mediu EMAG_PROFILE_DIR, verific-o."
        )
    leftover = f"Șterse până acum: {counts}. Rămase: {result.failed_entries}.\n{path_line}"
    if result.blocked_by_other_program:
        return (
            f"EROARE: nu am putut șterge toată sesiunea: {result.failed_entries} elemente sunt folosite de alt program.\n"
            f"Închide fereastra Edge deschisă de program și rulează din nou.\n{leftover}"
        )
    return f"EROARE: nu am putut șterge toată sesiunea ({result.error_text}).\n{leftover}"
