"""Recuperarea după o actualizare întreruptă și operațiile de disc pe care se sprijină aplicarea (decis 6 oct. 2026, N1–N4, P1–P8).

Primește: rădăcina programului (lansatoarele, prin `python -m emag_spend.update_recovery`, înaintea pregătirii, P1; ruleaza.py, pe primele
rânduri) sau jurnalul unei aplicări în curs (update_apply.py). Dă înapoi: recover_before_start → RecoveryOutcome (mesaj, eroare, ce a notat
în jurnal, P6), fără excepții; main → codul de ieșire al lansatorului; restul ridică RecoveryError, LockError sau OSError. Cum: sub lacăt,
readuce rădăcina la versiunea veche după starea de pe disc, fără să scrie prin legături (P5), apoi șterge ÎNTÂI jurnalul, apoi nou/,
vechi/, copie/ și descărcările oprite (N3, P7). Sursă unică pentru numele din .actualizare, căile protejate (D7) și ștergerea fără legături.
Ce NU face: importă doar biblioteca standard și update_lock.py (arborele poate fi amestecat, N2); nu instalează nimic și nu citește
setările. Contracte între versiuni: formatul jurnalului (JOURNAL_FORMAT) și main (nume, fără argumente, coduri de ieșire).
"""

import errno
import json
import logging
import os
import re
import stat
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from emag_spend.update_lock import LockError, UpdateLock

# Sub `python -m` modulul rulează ca „__main__”: numele din spec păstrează în jurnal numele lui real (emag_spend.update_recovery).
logger = logging.getLogger(__spec__.name if __spec__ is not None else __name__)
# Recuperarea rulează înaintea configurării jurnalului (setup_logging): fără asta, Python ar scrie avertismentele direct pe ecran,
# lângă mesajul pe care îl afișează ruleaza.py. Ce notează la pornire se ține în RecoveryOutcome.records și ajunge în logs/ (P6).
logger.addHandler(logging.NullHandler())

# ---------- folderul de lucru (contract între versiuni) ----------
WORK_DIR_NAME = ".actualizare"  # = settings.UPDATE_WORK_DIR.name (verificat de teste)
NEW_DIR_NAME = "nou"  # extragerea arhivei noi
OLD_DIR_NAME = "vechi"  # copiile de siguranță ale fișierelor vechi și fișierele șterse
# Copia de siguranță făcută fără legătură tare se scrie întâi aici și abia apoi se mută, întreagă, în vechi/ (N1). Numele are cel mult
# lungimea lui „vechi”, ca verificarea lungimii căilor din update_apply.py să rămână valabilă.
COPY_DIR_NAME = "copie"
WORK_SUBDIRS = (NEW_DIR_NAME, OLD_DIR_NAME, COPY_DIR_NAME)
DOWNLOADS_DIR_NAME = "descarcari"  # = settings.UPDATE_DOWNLOAD_DIR.name (verificat de teste): câte un folder pe descărcare (N9)
DOWNLOAD_FOLDER_PREFIX = "descarcare-"  # începutul numelui folderului unei descărcări (restul îl alege tempfile.mkdtemp)
# Folderele din .actualizare care nu au voie să fie legături: revenirea sau curățenia ar muta ori ar șterge prin ele (N4, P8).
LINK_CHECKED_SUBDIRS = (*WORK_SUBDIRS, DOWNLOADS_DIR_NAME)
# Un folder de descărcare neatins de atât timp e rămas de la un proces omorât (P7) și se șterge. O descărcare vie trăiește cel mult
# cât SHA256SUMS.txt plus arhiva, fiecare cu termenul total din update_http.DOWNLOAD_TOTAL_SECONDS (15 min), plus verificarea și
# instalarea (secunde): sub 35 de minute. O oră lasă marjă și pentru un disc lent (relația e verificată de teste).
STALE_DOWNLOAD_SECONDS = 60 * 60
JOURNAL_NAME = "jurnal.json"
JOURNAL_TEMPORARY_SUFFIX = ".tmp"
LOCK_NAME = "lacat"
JOURNAL_FORMAT = 1
STATE_APPLYING = "aplicare"  # mutările au început: la o pornire nouă se revine la versiunea veche (D11)
STATE_DONE = "gata"  # toate mutările s-au făcut: rămâne doar curățenia
# scrise = fișierele noi puse în rădăcină; existau = cele dintre ele care aveau o versiune veche (copiată în vechi/); sterse = fișierele
# vechi mutate în vechi/; foldere_noi = folderele create, de sus în jos; foldere_sterse = folderele golite și scoase ca să facă loc unui
# fișier nou (N6), de sus în jos, ca revenirea să le refacă.
JOURNAL_LISTS = ("scrise", "existau", "sterse", "foldere_noi", "foldere_sterse")

# Antivirusul poate ține un fișier deschis o clipă după ce a fost scris sau mutat: 5 încercări × 0,2 s = cel mult o secundă de așteptare.
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_SECONDS = 0.2

# ---------- ce nu se atinge niciodată (D7) ----------
# Primul nivel al căii, comparat fără litere mari/mici: rezultatele, jurnalele, sesiunea eMAG, uv + Python, pachetele, folderul
# actualizării și depozitul git. Stau aici (nu în update_archive.py, care le reexportă) pentru că recuperarea le folosește înaintea
# oricărui alt import. Profilul din EMAG_PROFILE_DIR îl adaugă update_apply.py, dacă e în rădăcină.
LOGS_DIR_NAME = "logs"  # = settings.LOGS_DIR.name (verificat de teste): aici scrie și punctul de intrare al lansatoarelor
PROTECTED_DIRS = frozenset({"iesiri", LOGS_DIR_NAME, ".profil_browser", ".uv", ".venv", WORK_DIR_NAME, ".git"})
PROTECTED_FILES = frozenset({"config/categorii.personal.json"})  # regulile personale de categorii
GIT_DIR_NAME = ".git"

# ---------- căi care ar putea numi altceva decât par ----------
ESCAPE_CHARACTERS = frozenset("\\:")  # «\» și «:» (unitate, flux NTFS) pot duce în afara folderului
SHORT_NAME_PATTERN = re.compile(r"~[0-9]")  # nume scurt 8.3 (PROFIL~1): pe Windows poate numi alt fișier, chiar unul protejat
FIRST_PRINTABLE_CODE_POINT = 32
DELETE_CODE_POINT = 127

MESSAGE_RECOVERED = "Actualizarea la versiunea {to_version} a fost întreruptă; am revenit la versiunea {from_version}. Poți încerca din nou."
MESSAGE_REVERT_INCOMPLETE = ("Actualizarea a eșuat ({detail}), iar revenirea la versiunea {version} nu s-a terminat. Pornește din nou "
                             "programul: încearcă singur să revină; dacă nu reușește, descarcă-l din nou de pe pagina lansărilor.")
MESSAGE_JOURNAL_DAMAGED = (f"Jurnalul actualizării ({WORK_DIR_NAME}/{JOURNAL_NAME}) nu se poate citi, deci nu știu ce fișiere să refac. "
                           "Descarcă programul din nou de pe pagina lansărilor (datele tale din iesiri/ rămân).")
MESSAGE_LINKED_WORK_DIR = ("Folderul «{path}» al actualizării e o legătură spre alt loc; din siguranță, nu ating nimic. Șterge legătura "
                           "și pornește din nou programul.")
MESSAGE_LINK_NOT_FOLLOWED = "e o legătură spre alt loc: n-o urmez și nu șterg nimic din ea"
MESSAGE_INTERRUPTED = "Recuperarea actualizării întrerupte a fost oprită cu Ctrl+C; pornește din nou programul ca s-o termine."
MESSAGE_UNEXPECTED = ("Nu am putut termina recuperarea unei actualizări întrerupte ({detail}). Pornește din nou programul; dacă eroarea "
                      "rămâne, descarcă-l din nou de pe pagina lansărilor (datele tale din iesiri/ rămân).")
MESSAGE_USAGE = ("Folosire: python -m emag_spend.update_recovery (fără argumente). Termină o actualizare întreruptă a programului din "
                 "folderul acestui fișier; lansatoarele îl rulează singure.")
# Rândul de jurnal cu rezultatul recuperării de la pornire, același în ruleaza.py și în punctul de intrare al lansatoarelor.
LOG_STARTUP_OUTCOME = "recuperarea actualizării întrerupte: %s"

# ---------- punctul de intrare al lansatoarelor (P1): contract cu lansatoarele tuturor versiunilor ----------
EXIT_RECOVERY_OK = 0  # nimic de făcut sau revenirea s-a terminat: lansatorul merge mai departe
EXIT_RECOVERY_FAILED = 1  # recuperarea nu se poate face acum: lansatorul se oprește cu mesajul afișat
EXIT_USAGE = 2  # argumente date (nu primește niciunul): nu face nimic
PROGRAM_ROOT = Path(__file__).resolve().parents[1]  # folderul programului: părintele lui emag_spend/
# Jurnalul pornirii, la fel ca run_logger.setup_logging: același format și același nume de fișier (verificat de teste). Recuperarea
# nu importă run_logger: pe un arbore amestecat, acela poate fi deja din versiunea nouă.
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_FILE_NAME_FORMAT = "%Y-%m-%d_%H-%M-%S.log"


class RecoveryError(Exception):
    """Recuperarea nu se poate face acum; `str(eroare)` e fraza pentru utilizator, în română."""


@dataclass(frozen=True)
class RecoveryOutcome:
    """Ce a făcut recuperarea de la pornire: `message` după o revenire care a schimbat ceva, `error` dacă nu s-a putut face (altfel None).

    `records` = ce a notat recuperarea în jurnal (de la INFO în sus), ținut în memorie: la pornire jurnalul programului nu e încă
    configurat, iar apelantul le scrie în logs/ după ce îl configurează (P6). Nu intră în comparații.
    """

    message: str | None = None
    error: str | None = None
    records: tuple[logging.LogRecord, ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True)
class RevertResult:
    """Rezultatul unei reveniri: câte schimbări a făcut în rădăcină și ce căi n-au putut fi refăcute."""

    changed: int
    failed: tuple[str, ...]


# ---------- căi ----------

def path_key(relative: str) -> str:
    """Cheia de comparare a unei căi: aceeași pentru «README.md» și «readme.md» și pentru formele Unicode echivalente (Windows, macOS)."""
    return unicodedata.normalize("NFC", relative).casefold()


def ancestors(relative: str) -> list[str]:
    """Folderele părinte ale unei căi relative, de sus în jos: «a/b/c.txt» → ["a", "a/b"]."""
    parts = relative.split("/")[:-1]
    return ["/".join(parts[:depth]) for depth in range(1, len(parts) + 1)]


def is_protected(relative: str, extra_dirs: tuple[str, ...] = ()) -> bool:
    """True dacă o cale relativă e a utilizatorului sau a mediului (D7): nu se scrie, nu se mută și nu se șterge niciodată.

    `extra_dirs` = alte foldere protejate, ca chei path_key relative la rădăcină (profilul din EMAG_PROFILE_DIR); "" protejează tot.
    """
    key = path_key(relative)
    parts = key.split("/")
    if parts[0] in PROTECTED_DIRS or GIT_DIR_NAME in parts or key in PROTECTED_FILES:
        return True
    return any(not folder or key == folder or key.startswith(folder + "/") for folder in extra_dirs)


def escape_problem(relative: object) -> str | None:
    """Motivul, în română, pentru care o cale relativă ar putea numi altceva decât pare (în afara folderului sau un alt fișier); None dacă e sigură.

    Refuză: cale goală sau absolută, caractere de control, «\\» și «:», componente goale, «.», «..», nume terminate în punct sau spațiu
    (Windows le taie, deci «iesiri.» ar numi «iesiri») și nume scurte 8.3 (~1). update_archive.path_problem adaugă regulile Windows.
    """
    if not isinstance(relative, str) or not relative:
        return "cale goală"
    if relative.startswith("/"):
        return "cale absolută"
    if any(ord(char) < FIRST_PRINTABLE_CODE_POINT or ord(char) == DELETE_CODE_POINT for char in relative):
        return "caractere de control"
    escaping = ESCAPE_CHARACTERS.intersection(relative)
    if escaping:
        return f"caracterul «{min(escaping)}», nepermis pe Windows"
    for part in relative.split("/"):
        if part in ("", ".", ".."):
            return "componentă goală, «.» sau «..»"
        if part[-1] in ". ":
            return "nume terminat în punct sau spațiu"
        if SHORT_NAME_PATTERN.search(part):
            return "seamănă cu un nume scurt de Windows (~1)"
    return None


# ---------- operații pe disc ----------

def is_link(path: Path) -> bool:
    """True pentru o legătură simbolică sau o joncțiune Windows (ambele duc în alt loc decât par); False dacă nu există."""
    return os.path.islink(path) or os.path.isjunction(path)


def retry_on_permission_error(operation: Callable[..., object], *paths) -> None:
    """Rulează operația; la PermissionError (antivirus, indexare) mai încearcă de câteva ori, la pauze scurte, apoi o lasă să cadă."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            operation(*paths)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_RETRY_DELAY_SECONDS)


def ensure_parent(path: Path) -> None:
    """Creează doar folderele care lipsesc deasupra lui `path` (nicio încercare pe rădăcină sau pe foldere existente)."""
    if not path.parent.is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)


def is_read_only(path: Path) -> bool:
    """True pe Windows pentru un fișier cu atributul „doar citire” (fără să urmeze o legătură); False în rest sau dacă lipsește."""
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_READONLY)


def _replace_even_read_only(source: Path, target: Path) -> None:
    """os.replace; pe Windows, dacă ținta are atributul „doar citire” (MoveFileEx refuză s-o înlocuiască), îl scoate și reîncearcă (P3).

    Ținta e fișierul vechi al programului, care are deja copia de siguranță (o copie întreagă, cu atributul păstrat: update_apply._backup).
    """
    try:
        os.replace(source, target)
    except PermissionError:
        if not is_read_only(target):
            raise  # fișier ținut deschis sau fără drept: reîncercările din retry_on_permission_error, apoi eroarea
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        os.replace(source, target)


def move(source: Path, target: Path) -> None:
    """Mută un fișier cu un singur os.replace (atomic, niciodată scriere peste cel existent: un shell care îl rulează păstrează inode-ul vechi).

    O țintă „doar citire” (Windows) se înlocuiește și ea (P3); la o eroare, OSError are în `filename2` ținta.
    """
    ensure_parent(target)
    retry_on_permission_error(_replace_even_read_only, source, target)


def remove_file(path: Path) -> None:
    """Șterge un fișier; pe Windows scoate întâi atributul „doar citire”, care altfel blochează ștergerea."""
    try:
        retry_on_permission_error(os.remove, path)
    except PermissionError:
        if os.name != "nt":
            raise
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.remove(path)


def _remove_link(entry: os.DirEntry) -> None:
    """Scoate DOAR legătura: pe Windows os.rmdir pentru joncțiune sau legătură de folder, os.unlink pentru legătură de fișier; pe Unix os.unlink."""
    if os.name == "nt":
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        if entry.is_junction() or attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
            os.rmdir(entry.path)
            return
    os.unlink(entry.path)


def _empty_folder(folder: str) -> None:
    """Golește un folder de jos în sus, fără să coboare în vreo legătură: legăturile se scot ele însele, ținta lor rămâne neatinsă."""
    with os.scandir(folder) as found:
        entries = list(found)
    for entry in entries:
        if entry.is_symlink() or entry.is_junction():
            _remove_link(entry)
        elif entry.is_dir(follow_symlinks=False):
            _empty_folder(entry.path)
            os.rmdir(entry.path)
        else:
            remove_file(Path(entry.path))


def remove_tree(path: Path) -> None:
    """Șterge un folder de lucru cu tot ce e în el, fără să urmeze legături (N4); nimic dacă nu există.

    Un vârf care e el însuși legătură se refuză cu OSError (nici legătura, nici ținta nu se ating). Ridică OSError la prima ștergere imposibilă.
    """
    if not os.path.lexists(path):
        return
    if is_link(path):
        raise OSError(errno.EPERM, MESSAGE_LINK_NOT_FOLLOWED, str(path))
    _empty_folder(str(path))
    os.rmdir(path)


def sync_folder(folder: Path) -> None:
    """Pe macOS/Linux: scrie pe disc intrarea de folder (după os.replace), ca jurnalul să supraviețuiască unei căderi de curent."""
    if os.name == "nt":
        return
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# ---------- jurnalul (D10, D11) ----------

def write_journal(work: Path, journal: dict) -> None:
    """Scrie jurnalul atomic: fișier temporar + fsync + os.replace; la o cădere rămâne fie cel vechi, fie cel nou, întreg."""
    temporary = work / (JOURNAL_NAME + JOURNAL_TEMPORARY_SUFFIX)
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(journal, ensure_ascii=False, indent=1).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    retry_on_permission_error(os.replace, temporary, work / JOURNAL_NAME)
    sync_folder(work)


def _valid_path(item: object) -> bool:
    """True pentru o cale de jurnal care rămâne în program și nu e protejată (D7)."""
    return escape_problem(item) is None and not is_protected(item)


def read_journal(work: Path) -> dict | None:
    """Jurnalul validat sau None dacă lipsește; RecoveryError dacă e deteriorat (formă, stare, căi care ies din program sau protejate)."""
    path = work / JOURNAL_NAME
    if not os.path.lexists(path):
        return None
    try:
        journal = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise RecoveryError(MESSAGE_JOURNAL_DAMAGED) from error
    valid = (isinstance(journal, dict) and journal.get("format") == JOURNAL_FORMAT
             and journal.get("stare") in (STATE_APPLYING, STATE_DONE)
             and all(isinstance(journal.get(name), str) for name in ("de_la", "la"))
             and all(isinstance(journal.get(name), list) for name in JOURNAL_LISTS)
             and all(_valid_path(item) for name in JOURNAL_LISTS for item in journal[name]))
    if not valid:
        raise RecoveryError(MESSAGE_JOURNAL_DAMAGED)
    return journal


# ---------- revenirea ----------

def _same_file(first: Path, second: Path) -> bool:
    """True dacă cele două căi sunt același fișier pe disc (copia de siguranță e o legătură tare la fișierul încă neînlocuit)."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _undo_write(root: Path, relative: str, existed: bool) -> bool:
    """Reface un fișier scris de aplicare; True dacă a schimbat ceva în rădăcină.

    Cu versiune veche: copia din vechi/ se pune la loc (dacă fișierul din rădăcină nu e chiar el, neînlocuit încă). Doar nou: fișierul
    deja mutat în rădăcină se duce înapoi în nou/.
    """
    work = root / WORK_DIR_NAME
    current, old, new = root / relative, work / OLD_DIR_NAME / relative, work / NEW_DIR_NAME / relative
    if existed:
        if not os.path.lexists(old) or (os.path.lexists(current) and _same_file(old, current)):
            return False
        move(old, current)
        return True
    if os.path.lexists(new) or not os.path.lexists(current):
        return False
    move(current, new)
    return True


def _undo_delete(root: Path, relative: str) -> bool:
    """Pune la loc un fișier vechi mutat în vechi/; True dacă l-a pus."""
    old = root / WORK_DIR_NAME / OLD_DIR_NAME / relative
    if not os.path.lexists(old):
        return False
    move(old, root / relative)
    return True


def _recreate_folder(path: Path) -> bool:
    """Reface un folder scos ca să facă loc unui fișier nou (N6); True dacă l-a creat. OSError dacă în locul lui e încă altceva."""
    if path.is_dir() and not is_link(path):
        return False
    path.mkdir(parents=True)
    return True


def _link_on_the_way(root: Path, relative: str) -> str | None:
    """Legătura (simbolică sau joncțiune) prin care revenirea ar scrie sau ar muta pentru `relative`, ca cale relativă la program; None
    dacă drumul e curat. Se uită la folderele-părinte din rădăcină și la cele din nou/, vechi/, copie/, plus calea însăși din ele (P5)."""
    work = root / WORK_DIR_NAME
    candidates = [root / folder for folder in ancestors(relative)]
    for name in WORK_SUBDIRS:
        candidates.extend(work / name / part for part in (*ancestors(relative), relative))
    for path in candidates:
        if is_link(path):
            return path.relative_to(root).as_posix()
    return None


def revert(root: Path, journal: dict) -> RevertResult:
    """Readuce rădăcina la versiunea veche după starea de pe disc; merge oricât de departe ar fi ajuns aplicarea și se poate relua.

    Ordinea: fișierele scrise (cele vechi la loc, cele doar noi înapoi în nou/), folderele create (dacă au rămas goale), folderele scoase
    pentru N6, apoi fișierele șterse. Nu ridică la un fișier blocat: îl trece în `failed` și merge mai departe. O cale care ar trece printr-o
    legătură (pusă după întrerupere în program sau în .actualizare) se sare și intră tot în `failed`: nimic nu se scrie prin ea (P5).
    """
    existed = set(journal["existau"])
    changed, failed = 0, []

    def linked(relative: str) -> bool:
        """True (și notează calea ca nerefăcută) dacă pasul pentru `relative` ar trece printr-o legătură."""
        link = _link_on_the_way(root, relative)
        if link is not None:
            logger.error("actualizare: nu refac %s: «%s» %s", relative, link, MESSAGE_LINK_NOT_FOLLOWED)
            failed.append(relative)
        return link is not None

    def attempt(relative: str, action: Callable[[], bool]) -> None:
        """Rulează un pas al revenirii; numără schimbările și notează căile care n-au putut fi refăcute."""
        nonlocal changed
        if linked(relative):
            return
        try:
            changed += action()
        except OSError as error:
            logger.error("actualizare: nu am putut reface %s: %s", relative, error)
            failed.append(relative)

    for relative in reversed(journal["scrise"]):
        attempt(relative, lambda relative=relative: _undo_write(root, relative, relative in existed))
    for folder in reversed(journal["foldere_noi"]):
        if is_link(root / folder):
            logger.error("actualizare: nu scot folderul %s: %s", folder, MESSAGE_LINK_NOT_FOLLOWED)
            failed.append(folder)
            continue
        if linked(folder):
            continue
        try:
            os.rmdir(root / folder)
        except OSError:
            pass  # nu e gol (are fișiere ale utilizatorului), nu mai există sau e încă fișierul vechi: rămâne cum e
    for folder in journal["foldere_sterse"]:
        attempt(folder, lambda folder=folder: _recreate_folder(root / folder))
    for relative in reversed(journal["sterse"]):
        attempt(relative, lambda relative=relative: _undo_delete(root, relative))
    return RevertResult(changed, tuple(failed))


# ---------- curățenia (N3, P7) ----------

def _last_change(folder: str) -> float:
    """Cea mai nouă dată de modificare dintre folder și intrările lui directe (fără să urmeze legături): cât de recent a lucrat cineva în el."""
    newest = os.lstat(folder).st_mtime
    with os.scandir(folder) as found:
        for entry in found:
            newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
    return newest


def remove_stale_downloads(downloads: Path) -> None:
    """Șterge din .actualizare/descarcari folderele descarcare-* lăsate de un proces omorât în timpul descărcării (P7).

    Doar cele neatinse de cel puțin STALE_DOWNLOAD_SECONDS: o descărcare vie din altă fereastră rămâne. Nu urmează legături (un `descarcari`
    sau un descarcare-* care e legătură rămâne neatins, la fel orice altceva din folder) și nu ridică; ce nu se poate șterge rămâne, cu avertisment.
    """
    if is_link(downloads):
        logger.warning("actualizare: %s/%s %s", WORK_DIR_NAME, DOWNLOADS_DIR_NAME, MESSAGE_LINK_NOT_FOLLOWED)
        return
    try:
        with os.scandir(downloads) as found:
            candidates = [entry for entry in found if entry.name.startswith(DOWNLOAD_FOLDER_PREFIX)]
    except OSError:
        return  # nu există (cazul obișnuit) sau nu se poate citi: nimic de șters
    oldest_live = time.time() - STALE_DOWNLOAD_SECONDS
    for entry in candidates:
        try:
            if entry.is_symlink() or entry.is_junction() or not entry.is_dir(follow_symlinks=False):
                continue
            if _last_change(entry.path) > oldest_live:
                continue  # poate fi descărcarea vie a altei ferestre
            remove_tree(Path(entry.path))
            logger.info("actualizare: am șters descărcarea oprită %s/%s/%s", WORK_DIR_NAME, DOWNLOADS_DIR_NAME, entry.name)
        except OSError as error:
            logger.warning("actualizare: descărcarea oprită %s nu s-a putut șterge (%s)", entry.name, error.strerror or type(error).__name__)


def clear_work(work: Path) -> None:
    """Șterge jurnalul (ÎNTÂI, ca o curățenie ratată să nu mai fie luată drept aplicare întreruptă), apoi nou/, vechi/, copie/, apoi
    descărcările oprite din descarcari/ (P7) și folderul descarcari dacă a rămas gol.

    Nu ridică: ce nu se poate șterge acum rămâne, inofensiv, și se șterge la aplicarea următoare; lacătul rămâne mereu (N5).
    """
    for name in (JOURNAL_NAME, JOURNAL_NAME + JOURNAL_TEMPORARY_SUFFIX):
        try:
            if os.path.lexists(work / name):
                remove_file(work / name)
        except OSError as error:
            logger.warning("actualizare: %s nu s-a putut șterge (%s); pornirea următoare doar verifică și îl șterge", name, error)
    for name in WORK_SUBDIRS:
        try:
            remove_tree(work / name)
        except OSError as error:
            logger.warning("actualizare: %s/%s nu s-a putut șterge (%s); se șterge la aplicarea următoare", WORK_DIR_NAME, name, error)
    downloads = work / DOWNLOADS_DIR_NAME
    remove_stale_downloads(downloads)
    if os.path.lexists(downloads) and not is_link(downloads):
        try:
            os.rmdir(downloads)
        except OSError:
            pass  # nu e gol: descărcarea vie a acestei sau a altei ferestre


def remove_empty_parents(root: Path, relatives) -> None:
    """După ștergerea fișierelor vechi, scoate folderele lor rămase goale (niciodată unul cu fișiere: os.rmdir refuză).

    Nu scoate nimic sub o legătură sau legătura însăși: os.rmdir ar goli un folder din alt loc (N4).
    """
    for relative in relatives:
        folders = ancestors(relative)
        if any(is_link(root / folder) for folder in folders):
            continue
        for folder in reversed(folders):
            try:
                os.rmdir(root / folder)
            except OSError:
                break


def refuse_linked_work_dirs(work: Path) -> None:
    """RecoveryError dacă .actualizare sau nou/, vechi/, copie/, descarcari/ din el sunt legături: revenirea sau curățenia ar muta ori ar
    șterge fișiere din alt loc (N4, P8)."""
    for path in (work, *(work / name for name in LINK_CHECKED_SUBDIRS)):
        if is_link(path):
            raise RecoveryError(MESSAGE_LINKED_WORK_DIR.format(path=Path(path).relative_to(work.parent).as_posix()))


def finish_pending(root: Path) -> str | None:
    """Termină ce a lăsat o rulare oprită (cu lacătul deja luat): „aplicare” → revenire; „gata” → doar curățenie.

    Întoarce mesajul pentru utilizator doar dacă revenirea a schimbat ceva în rădăcină (N3); altfel None. RecoveryError dacă jurnalul
    e deteriorat sau dacă revenirea nu s-a terminat (jurnalul rămâne și se reia la pornirea următoare).
    """
    work = root / WORK_DIR_NAME
    journal = read_journal(work)
    if journal is None:
        return None
    if journal["stare"] == STATE_DONE:
        remove_empty_parents(root, journal["sterse"])
        clear_work(work)
        logger.info("actualizare: curățenia după instalarea versiunii %s s-a terminat acum", journal["la"])
        return None
    result = revert(root, journal)
    if result.failed:
        detail = f"{len(result.failed)} căi nerefăcute (fișier blocat sau legătură spre alt loc), ex. «{result.failed[0]}»"
        raise RecoveryError(MESSAGE_REVERT_INCOMPLETE.format(detail=detail, version=journal["de_la"]))
    clear_work(work)
    if not result.changed:
        logger.info("actualizare: aplicarea %s → %s se oprise înainte să schimbe ceva; am curățat doar urmele", journal["de_la"], journal["la"])
        return None
    logger.warning("actualizare: aplicarea întreruptă %s → %s a fost anulată (%d schimbări refăcute)",
                   journal["de_la"], journal["la"], result.changed)
    return MESSAGE_RECOVERED.format(to_version=journal["la"], from_version=journal["de_la"])


def recover(root: Path) -> str | None:
    """Recuperarea, sub lacăt: None dacă n-a fost nimic de spus, altfel mesajul. Ridică RecoveryError sau LockError (lacăt ocupat).

    Fără jurnal nu face nimic și nu scrie nimic (nici .actualizare, nici lacătul).
    """
    root = Path(root).resolve()
    work = root / WORK_DIR_NAME
    if not os.path.lexists(work / JOURNAL_NAME):
        return None
    refuse_linked_work_dirs(work)
    with UpdateLock(work / LOCK_NAME):
        return finish_pending(root)


class _RecordCollector(logging.Handler):
    """Ține în memorie ce notează recuperarea de la pornire (de la INFO în sus), cât jurnalul programului nu e încă configurat (P6)."""

    def __init__(self) -> None:
        """Un colector gol, de la nivelul INFO."""
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Păstrează înregistrarea, neformatată, pentru jurnalul scris mai târziu."""
        self.records.append(record)


def _recover_quietly(root: Path) -> RecoveryOutcome:
    """recover() cu orice problemă transformată în RecoveryOutcome(error=...), fără excepții (nici la Ctrl+C)."""
    try:
        return RecoveryOutcome(message=recover(root))
    except (RecoveryError, LockError) as error:
        return RecoveryOutcome(error=str(error))
    except KeyboardInterrupt:
        return RecoveryOutcome(error=MESSAGE_INTERRUPTED)
    except Exception as error:  # granița de la pornire: o eroare neprevăzută devine mesaj, nu traceback înaintea programului
        logger.exception("actualizare: recuperarea a eșuat neprevăzut")
        return RecoveryOutcome(error=MESSAGE_UNEXPECTED.format(detail=getattr(error, "strerror", None) or type(error).__name__))


def recover_before_start(root: Path) -> RecoveryOutcome:
    """Primul lucru la pornire (lansatoarele prin main, ruleaza.py înaintea oricărui alt import din emag_spend, N2): termină o
    actualizare întreruptă.

    Nu ridică niciodată (nici la Ctrl+C): întoarce RecoveryOutcome(mesaj, None) după o revenire, RecoveryOutcome(None, eroare) dacă
    recuperarea nu se poate face acum (lacăt ocupat, jurnal deteriorat, fișier blocat, legătură) și RecoveryOutcome() dacă n-a fost nimic
    de făcut. Ce notează între timp (de la INFO în sus) nu se pierde: vine în `records` (P6); colectorul se scoate la final oricum.
    """
    collector, level = _RecordCollector(), logger.level
    logger.addHandler(collector)
    logger.setLevel(min(logger.getEffectiveLevel(), logging.INFO))
    try:
        outcome = _recover_quietly(root)
    finally:
        logger.removeHandler(collector)
        logger.setLevel(level)
    return replace(outcome, records=tuple(collector.records))


def write_startup_log(logs_dir: Path, outcome: RecoveryOutcome) -> Path | None:
    """Scrie în logs/<data>_<ora>.log (ca run_logger) ce a notat recuperarea și rezultatul ei; întoarce calea sau None dacă n-a fost nimic.

    Pentru cine rulează fără jurnalul programului: main (înaintea pregătirii) și ruleaza.py când recuperarea a eșuat (acolo nu se mai
    importă nimic, nici run_logger). OSError dacă logs/ nu se poate scrie (apelanții o prind). Handler-ul se scoate și se închide la final.
    """
    if outcome.message is None and outcome.error is None and not outcome.records:
        return None
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / time.strftime(LOG_FILE_NAME_FORMAT)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    try:
        for record in outcome.records:
            handler.handle(record)
        if outcome.error is not None:
            logger.error(LOG_STARTUP_OUTCOME, outcome.error)
        elif outcome.message is not None:
            logger.warning(LOG_STARTUP_OUTCOME, outcome.message)
    finally:
        logger.removeHandler(handler)
        handler.close()
    return path


def main(argv: list[str] | None = None, root: Path = PROGRAM_ROOT) -> int:
    """Punctul de intrare al lansatoarelor (P1): `"<python din .venv>" -m emag_spend.update_recovery`, din folderul programului, rulat
    ÎNAINTEA pregătirii (instaleaza.bat, instalare/pregatire.sh) când există .actualizare/jurnal.json.

    Termină o actualizare întreruptă (recover_before_start) pe programul din `root` (implicit părintele lui emag_spend/) și întoarce
    codul de ieșire, contract cu lansatoarele tuturor versiunilor (nu se schimbă):
      0 = EXIT_RECOVERY_OK: nimic de făcut (nu afișează nimic) sau recuperarea s-a terminat; după o revenire care a schimbat ceva
          afișează mesajul (MESSAGE_RECOVERED), între două rânduri goale. Lansatorul merge mai departe.
      1 = EXIT_RECOVERY_FAILED: recuperarea nu se poate face acum (alt proces aplică o actualizare, jurnal deteriorat, fișier blocat,
          legătură spre alt loc, Ctrl+C); afișează un rând gol și «EROARE: <motiv>». Lansatorul se oprește, fără să ruleze altceva.
      2 = EXIT_USAGE: a primit argumente (nu primește niciunul); afișează MESSAGE_USAGE și nu face nimic.
    Dacă a găsit un jurnal sau o eroare, lasă urma în logs/<data>_<ora>.log (write_startup_log). Nu ridică.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # consola Windows sau un pipe: diacriticele mesajului ajung întregi
    if arguments:
        print(MESSAGE_USAGE)
        return EXIT_USAGE
    outcome = recover_before_start(root)
    try:
        write_startup_log(Path(root) / LOGS_DIR_NAME, outcome)
    except OSError as error:  # fără jurnal pe disc rezultatul tot se afișează: e mai important decât urma
        print(f"(Jurnalul pornirii nu s-a putut scrie în {LOGS_DIR_NAME}/: {error.strerror or type(error).__name__}.)")
    if outcome.error is not None:
        print(f"\nEROARE: {outcome.error}")
        return EXIT_RECOVERY_FAILED
    if outcome.message is not None:
        print(f"\n{outcome.message}\n")
    return EXIT_RECOVERY_OK


if __name__ == "__main__":
    raise SystemExit(main())
