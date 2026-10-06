"""Instalează o versiune nouă peste folderul programului, din arhiva lansării deja descărcată și verificată (D8–D11, D14; N1, N4, N6, P2–P4 din 6 oct. 2026).

Primește: arhiva ZIP (update_download.py), rădăcina programului și versiunea așteptată. Dă înapoi: ApplyResult; ridică UpdateError,
iar după orice eroare (și după Ctrl+C) rădăcina e exact ca înainte. recover_interrupted repară o aplicare întreruptă (update_recovery.py).
Cum: sub lacăt, după o rulare oprită terminată, citește versiunea instalată (P2), validează și extrage arhiva în .actualizare/nou; cu jurnal
scris atomic, fiecare fișier vechi primește ÎNTÂI o copie de siguranță în .actualizare/vechi (legătură tare sau copie întreagă), apoi e
înlocuit printr-un singur os.replace: în rădăcină există în orice clipă fișierul vechi sau cel nou, întreg (N1). Scrie DOAR căile din
manifestul validat și nu urmează legături. Ce NU face: nu descarcă, nu verifică amprente, nu repornește; revenirea e în update_recovery.py.
"""

import logging
import os
import shutil
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from emag_spend import settings, update_archive, update_recovery
from emag_spend.update_archive import (
    ARCHIVE_READ_ERRORS, GIT_DIR_NAME, MANIFEST_PATH, MESSAGE_TOO_BIG, VERSION_FILE_PATH, ancestors, damaged, is_executable_entry,
    is_protected, parse_manifest, path_key, validate_archive, version_from_source,
)
from emag_spend.update_errors import UpdateError
from emag_spend.update_lock import LockError, UpdateLock
from emag_spend.update_recovery import (  # noqa: F401 - numele folderului de lucru și mesajul de revenire, folosite și de teste
    COPY_DIR_NAME, JOURNAL_FORMAT, JOURNAL_NAME, LOCK_NAME, MESSAGE_RECOVERED, MESSAGE_REVERT_INCOMPLETE, NEW_DIR_NAME, OLD_DIR_NAME,
    STATE_APPLYING, STATE_DONE, WORK_DIR_NAME, WORK_SUBDIRS, RecoveryError, ensure_parent, is_link, is_read_only, move, remove_tree,
    retry_on_permission_error,
)
from emag_spend.version import is_newer, parse_version

logger = logging.getLogger(__name__)

COPY_CHUNK_BYTES = 1024 * 1024
# Windows fără „căi lungi” activate: o cale are cel mult 259 de caractere (260 cu terminatorul). Se verifică pe cea mai lungă
# cale din .actualizare\vechi\ (cea mai adâncă pe care o scrie aplicarea; .actualizare\copie\ are un nume la fel de lung), înainte de orice scriere.
WINDOWS_MAX_PATH = 260
SHORT_FOLDER_HINT = r"C:\cheltuieli-emag"  # un loc scurt, sugerat utilizatorului când calea e prea lungă
READ_BITS = 0o444
PROGRESS_INSTALLING = "instalez"  # etapa raportată prin `progress` (aceeași cu starea aplicației locale)

MESSAGE_GIT_CHECKOUT = "Folderul ăsta e o copie git: actualizează cu git pull."
MESSAGE_BAD_VERSION = "Versiunea cerută («{version}») nu are forma X.Y.Z."
MESSAGE_NO_INSTALLED_VERSION = ("Nu găsesc versiunea instalată ({path}); descarcă programul din nou de pe pagina lansărilor "
                                "(datele tale din iesiri/ rămân).")
MESSAGE_NOT_NEWER = "Versiunea {version} nu e mai nouă decât cea instalată ({current}); nu o instalez."
MESSAGE_NOT_ZIP = "Arhiva actualizării nu e un fișier ZIP valid."
MESSAGE_PATH_TOO_LONG = ("Calea folderului programului e prea lungă pentru Windows ({length} de caractere cu «{path}», limita e {limit}). "
                         "Mută folderul programului mai sus, de exemplu în {hint}, și încearcă din nou.")
MESSAGE_FOLDER_IN_THE_WAY = "În locul fișierului «{path}» din versiunea nouă există un folder; mută-l sau șterge-l și încearcă din nou."
MESSAGE_FILE_IN_THE_WAY = "În locul folderului «{path}» din versiunea nouă există un fișier; mută-l sau șterge-l și încearcă din nou."
MESSAGE_LINK_IN_THE_WAY = ("În locul fișierului «{path}» din versiunea nouă e o legătură spre alt loc; din siguranță, nu instalez peste ea. "
                           "Mut-o sau șterge-o și încearcă din nou.")
MESSAGE_LINKED_FOLDER = "Folderul «{path}» din program e o legătură spre alt loc; din siguranță, nu instalez peste el."
MESSAGE_DISK = "Nu pot scrie actualizarea pe disc ({detail}); n-am schimbat nimic."
MESSAGE_REVERTED = "Actualizarea nu s-a putut instala ({detail}); am revenit la versiunea {version}, nu s-a schimbat nimic."


@dataclass(frozen=True)
class ApplyResult:
    """Rezultatul unei aplicări reușite: versiunea veche, cea nouă, câte fișiere s-au scris și câte s-au șters."""

    from_version: str
    to_version: str
    written: int
    deleted: int


@dataclass(frozen=True)
class _Plan:
    """Ce face aplicarea în rădăcină, în ordinea în care o face (N6: întâi ce stă în drumul unei scrieri)."""

    from_version: str
    to_version: str
    writes: tuple[str, ...]
    existed: tuple[str, ...]  # scrierile care au o versiune veche în rădăcină: primesc întâi copia de siguranță (N1)
    first_deletes: tuple[str, ...]  # fișiere vechi în locul unui folder nou sau în folderul care devine fișier: mutate primele
    deletes: tuple[str, ...]  # restul fișierelor din manifestul vechi care lipsesc din cel nou: mutate după toate scrierile
    removed_dirs: tuple[str, ...]  # foldere golite de first_deletes, scoase ca să facă loc unui fișier nou; de sus în jos
    new_dirs: tuple[str, ...]  # foldere create; de sus în jos (părinții înaintea copiilor)


def is_git_checkout(root: Path) -> bool:
    """True dacă rădăcina programului e o copie git (`.git` folder sau fișier): actualizarea se face cu git pull (D9)."""
    return os.path.lexists(Path(root) / GIT_DIR_NAME)


def _profile_dirs_inside(root: Path) -> tuple[str, ...]:
    """Profilul de browser din setări (EMAG_PROFILE_DIR), ca folder protejat relativ la rădăcină, dacă e în rădăcină (D7)."""
    try:
        inside = Path(settings.PROFILE_DIR).resolve().relative_to(root)
    except ValueError:
        return ()
    return (path_key(inside.as_posix()) if inside.parts else "",)


def _canonical_version(text: str) -> str:
    """„1.2.3” din „1.2.3” sau „v1.2.3”; UpdateError dacă nu e o versiune X.Y.Z."""
    parsed = parse_version(text)
    if parsed is None:
        raise UpdateError(MESSAGE_BAD_VERSION.format(version=text))
    return "{}.{}.{}".format(*parsed)


def _installed_version(root: Path) -> str:
    """Versiunea instalată în rădăcină (din emag_spend/version.py de pe disc, nu din modulul încărcat); UpdateError dacă lipsește."""
    try:
        found = version_from_source((root / VERSION_FILE_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        found = None
    if found is None or parse_version(found) is None:
        raise UpdateError(MESSAGE_NO_INSTALLED_VERSION.format(path=VERSION_FILE_PATH))
    return found


def _read_old_manifest(root: Path) -> list[str] | None:
    """Manifestul local (al versiunii instalate) sau None dacă lipsește ori e greșit: atunci nu se șterge nimic (D8)."""
    path = root / MANIFEST_PATH
    if not path.is_file():
        logger.info("actualizare: fără manifest local (%s): nu se șterge niciun fișier vechi", MANIFEST_PATH)
        return None
    try:
        # Doar aici se acceptă CRLF: un editor sau un script Windows (Add-Content) îl poate rescrie așa. Manifestul NOU rămâne strict LF.
        return parse_manifest(path.read_bytes().decode("utf-8").replace("\r\n", "\n"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        logger.warning("actualizare: manifestul local %s nu se poate folosi (%s): nu se șterge niciun fișier vechi", MANIFEST_PATH, error)
        return None


def check_path_lengths(root: Path, relatives, *, windows: bool) -> None:
    """Pe Windows: UpdateError dacă rădăcină + .actualizare\\vechi\\ + cea mai lungă cale ajunge la WINDOWS_MAX_PATH caractere."""
    if not windows or not relatives:
        return
    longest = max(relatives, key=len)
    separators = 3  # rădăcină\.actualizare\vechi\cale
    length = len(str(root)) + separators + len(WORK_DIR_NAME) + max(len(OLD_DIR_NAME), len(COPY_DIR_NAME)) + len(longest)
    if length >= WINDOWS_MAX_PATH:
        raise UpdateError(MESSAGE_PATH_TOO_LONG.format(length=length, path=longest, limit=WINDOWS_MAX_PATH - 1, hint=SHORT_FOLDER_HINT))


# ---------- extragerea și copia de siguranță ----------

def _add_execute_bits(path: Path) -> None:
    """Pe macOS/Linux: dă drept de execuție celor care au drept de citire (ca chmod +x), pentru lansatoarele din arhivă (D14)."""
    if os.name == "nt":
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    os.chmod(path, mode | ((mode & READ_BITS) >> 2))


def _extract(archive: zipfile.ZipFile, files: dict[str, zipfile.ZipInfo], destination: Path) -> None:
    """Scrie fișierele validate în `destination` (.actualizare/nou), numărând octeții reali; UpdateError la arhivă sau disc."""
    total = 0
    for relative, info in files.items():
        target = destination / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "xb") as sink:
                while chunk := source.read(COPY_CHUNK_BYTES):
                    total += len(chunk)
                    if total > update_archive.MAX_UNPACKED_BYTES:  # mărimea reală, nu doar cea anunțată în arhivă
                        raise UpdateError(MESSAGE_TOO_BIG.format(limit=update_archive.MAX_UNPACKED_BYTES))
                    sink.write(chunk)
            if is_executable_entry(info):
                _add_execute_bits(target)
        except ARCHIVE_READ_ERRORS as error:
            raise damaged(error) from error
        except OSError as error:
            raise UpdateError(MESSAGE_DISK.format(detail=error.strerror or type(error).__name__)) from error


def _backup(root: Path, relative: str) -> None:
    """N1: copia de siguranță a fișierului vechi în .actualizare/vechi, ÎNAINTE de înlocuire; fișierul din rădăcină nu se atinge.

    Întâi o legătură tare (instant, același conținut); dacă discul nu le știe (FAT32, exFAT) sau refuză, o copie completă scrisă în
    .actualizare/copie și mutată apoi întreagă în vechi/: în vechi/ nu apare niciodată o copie pe jumătate pe care revenirea s-o pună la loc.
    Un fișier „doar citire” (Windows) primește mereu copia completă: atributul e al fișierului, comun cu o legătură tare, iar înlocuirea
    îl scoate de pe țintă (P3); copia shutil.copy2 îl păstrează, deci revenirea pune la loc fișierul cu atributul lui.
    """
    work = root / WORK_DIR_NAME
    source, target = root / relative, work / OLD_DIR_NAME / relative
    ensure_parent(target)
    if is_read_only(source):
        logger.info("actualizare: %s e „doar citire”; fac o copie completă, cu atributul păstrat", relative)
    else:
        try:
            os.link(source, target)
            return
        except OSError as error:
            logger.info("actualizare: fără legătură tare pentru %s (%s); fac o copie completă", relative, error)
    temporary = work / COPY_DIR_NAME / relative
    ensure_parent(temporary)
    retry_on_permission_error(shutil.copy2, source, temporary)
    retry_on_permission_error(os.replace, temporary, target)


# ---------- planul ----------

def _old_program_folder(root: Path, relative: str, deletable: Callable[[str], bool]) -> tuple[list[str], list[str]] | None:
    """N6: dacă folderul `relative` conține doar fișiere ale versiunii vechi (de scos) și foldere, întoarce (fișierele, subfolderele de
    sus în jos); None dacă are altceva (un fișier al utilizatorului, o legătură): atunci rămâne refuzul."""
    files, folders, pending = [], [], [relative]
    while pending:
        current = pending.pop(0)
        with os.scandir(root / current) as found:
            entries = sorted(found, key=lambda entry: entry.name)
        for entry in entries:
            child = f"{current}/{entry.name}"
            if entry.is_symlink() or entry.is_junction():
                return None
            if entry.is_dir(follow_symlinks=False):
                folders.append(child)
                pending.append(child)
            elif entry.is_file(follow_symlinks=False) and deletable(child):
                files.append(child)
            else:
                return None
    return files, folders


def _plan(root: Path, files: dict[str, zipfile.ZipInfo], from_version: str, to_version: str, extra_protected: tuple[str, ...]) -> _Plan:
    """Ce se scrie, ce exista, ce se șterge (și în ce ordine) și ce foldere apar sau dispar; UpdateError dacă ceva stă în drum.

    Refuză: o legătură în locul unui fișier de scris sau ca folder-părinte (N4), un fișier sau folder al utilizatorului în drumul unei
    scrieri. Acceptă (N6) un fișier vechi în locul unui folder nou și un folder doar cu fișiere vechi în locul unui fișier nou.
    O legătură în locul unui fișier de șters se sare, cu avertisment: nu se mută și nu se urmează.
    """
    writes = tuple(sorted(files))
    new_keys = {path_key(relative) for relative in writes}
    old_manifest = _read_old_manifest(root) or []
    old_keys = {path_key(relative) for relative in old_manifest}

    def deletable(relative: str) -> bool:
        """Un fișier al versiunii vechi care lipsește din cea nouă și nu e protejat (D7, D8)."""
        key = path_key(relative)
        return key in old_keys and key not in new_keys and not is_protected(relative, extra_protected)

    existed, first_deletes, removed_dirs = [], [], []
    for relative in writes:
        for folder in ancestors(relative):
            path = root / folder
            if is_link(path):
                raise UpdateError(MESSAGE_LINKED_FOLDER.format(path=folder))
            if os.path.lexists(path) and not path.is_dir():
                if not deletable(folder):
                    raise UpdateError(MESSAGE_FILE_IN_THE_WAY.format(path=folder))
                if folder not in first_deletes:
                    first_deletes.append(folder)
        target = root / relative
        if is_link(target):
            raise UpdateError(MESSAGE_LINK_IN_THE_WAY.format(path=relative))
        if target.is_dir():
            inside = _old_program_folder(root, relative, deletable)
            if inside is None:
                raise UpdateError(MESSAGE_FOLDER_IN_THE_WAY.format(path=relative))
            first_deletes.extend(inside[0])
            removed_dirs.extend([relative, *inside[1]])
        elif os.path.lexists(target):
            existed.append(relative)
    first_keys = {path_key(relative) for relative in first_deletes}
    deletes = []
    for relative in old_manifest:
        if path_key(relative) in first_keys or not deletable(relative):
            continue  # deja mutat primul, același fișier în versiunea nouă (și cu alte litere mari/mici) sau date ale utilizatorului
        if any(is_link(root / folder) for folder in ancestors(relative)):
            logger.warning("actualizare: %s e sub o legătură; nu-l șterg", relative)
            continue
        target = root / relative
        if is_link(target):
            logger.warning("actualizare: %s e o legătură spre alt loc; n-o mut și n-o urmez", relative)
            continue
        if target.is_file():
            deletes.append(relative)
    replaced = set(first_deletes)
    new_dirs: list[str] = []
    for relative in writes:
        for folder in ancestors(relative):
            if folder not in new_dirs and (folder in replaced or not os.path.lexists(root / folder)):
                new_dirs.append(folder)
    return _Plan(from_version, to_version, writes, tuple(existed), tuple(first_deletes), tuple(deletes), tuple(removed_dirs),
                 tuple(new_dirs))


# ---------- aplicarea ----------

def _relative_name(name: object, root: Path) -> str:
    """Calea din eroare, relativă la program (fără numele contului de Windows); doar numele fișierului dacă e în afara programului."""
    try:
        return Path(os.fspath(name)).resolve().relative_to(root).as_posix()
    except (ValueError, OSError, TypeError):
        return Path(str(name)).name


def _describe(error: BaseException, root: Path) -> str:
    """O descriere scurtă a erorii pentru utilizator, cu calea relativă la program (fără numele contului de Windows).

    os.replace pune sursa în `filename` și ținta în `filename2`: se numește fișierul din program (cel blocat sau „doar citire”), nu
    copia lui din .actualizare/nou sau vechi/, pe care utilizatorul n-o cunoaște (P4); o cale din .actualizare doar dacă alta nu e.
    """
    if isinstance(error, UpdateError):
        return str(error)
    if isinstance(error, OSError):
        names = [_relative_name(name, root) for name in (error.filename, error.filename2) if name]
        in_program = [name for name in names if path_key(name.split("/")[0]) != path_key(WORK_DIR_NAME)]
        name = (in_program or names or [None])[0]
        return f"{error.strerror or type(error).__name__}{f': {name}' if name else ''}"
    return type(error).__name__


def _install(root: Path, plan: _Plan) -> None:
    """Mută fișierele sub jurnal; la ORICE excepție revine complet, apoi ridică UpdateError (sau excepția originală, la Ctrl+C).

    Ordinea (N1, N6): jurnalul; fișierele vechi din drumul scrierilor și folderele golite de ele; pentru fiecare scriere, copia de
    siguranță a fișierului vechi și UN os.replace; restul ștergerilor; jurnalul „gata”; curățenia (jurnalul primul, N3).
    """
    work = root / WORK_DIR_NAME
    new_dir, old_dir = work / NEW_DIR_NAME, work / OLD_DIR_NAME
    journal = {"format": JOURNAL_FORMAT, "de_la": plan.from_version, "la": plan.to_version, "stare": STATE_APPLYING,
               "scrise": list(plan.writes), "existau": list(plan.existed), "sterse": [*plan.first_deletes, *plan.deletes],
               "foldere_noi": list(plan.new_dirs), "foldere_sterse": list(plan.removed_dirs)}
    existed = set(plan.existed)
    try:
        update_recovery.write_journal(work, journal)
        for relative in plan.first_deletes:
            move(root / relative, old_dir / relative)
        for folder in reversed(plan.removed_dirs):
            os.rmdir(root / folder)
        for relative in plan.writes:
            if relative in existed:
                _backup(root, relative)
            move(new_dir / relative, root / relative)
        for relative in plan.deletes:
            move(root / relative, old_dir / relative)
        update_recovery.write_journal(work, {**journal, "stare": STATE_DONE})
    except BaseException as error:
        logger.error("actualizare %s → %s: eroare la mutări (%r); revin la versiunea veche", plan.from_version, plan.to_version, error)
        result = update_recovery.revert(root, journal)  # după starea de pe disc: merge și dacă nici jurnalul n-a apucat să fie scris
        if not result.failed:
            update_recovery.clear_work(work)
        if not isinstance(error, Exception):
            raise  # Ctrl+C sau oprire: după revenire, excepția originală merge mai departe
        detail = _describe(error, root)
        if result.failed:
            raise UpdateError(MESSAGE_REVERT_INCOMPLETE.format(detail=detail, version=plan.from_version)) from error
        raise UpdateError(MESSAGE_REVERTED.format(detail=detail, version=plan.from_version)) from error
    update_recovery.remove_empty_parents(root, [*plan.first_deletes, *plan.deletes])
    update_recovery.clear_work(work)


def _prepare_and_install(zip_path: Path, root: Path, version: str, progress: Callable[[str], None] | None) -> _Plan:
    """Sub lacăt: termină o rulare oprită, citește versiunea instalată și refuză una care nu e mai nouă, validează arhiva, face planul,
    verifică lungimea căilor, extrage și instalează; `progress("instalez")` după verificarea versiunii.

    Versiunea se citește abia acum (P2): înaintea lacătului, o altă aplicare (altă fereastră) ar fi putut instala între timp una mai
    nouă, iar după o rulare oprită version.py poate fi încă cel nou; `current` de aici intră în jurnal și în ApplyResult.
    """
    work = root / WORK_DIR_NAME
    extra_protected = _profile_dirs_inside(root)
    try:
        update_recovery.finish_pending(root)
    except RecoveryError as error:
        raise UpdateError(str(error)) from error
    current = _installed_version(root)
    if not is_newer(version, current):
        raise UpdateError(MESSAGE_NOT_NEWER.format(version=version, current=current))
    if progress is not None:
        progress(PROGRESS_INSTALLING)
    try:
        for name in WORK_SUBDIRS:
            remove_tree(work / name)  # resturi de la o încercare oprită sau de la o curățenie ratată: nimic din ele nu e în rădăcină
    except OSError as error:
        raise UpdateError(MESSAGE_DISK.format(detail=error.strerror or type(error).__name__)) from error
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise UpdateError(MESSAGE_NOT_ZIP) from error
    with archive:
        files = validate_archive(archive, version, extra_protected)
        plan = _plan(root, files, current, version, extra_protected)
        check_path_lengths(root, [*plan.writes, *plan.first_deletes, *plan.deletes], windows=os.name == "nt")
        logger.info("actualizare %s → %s: %d fișiere de scris (%d existau), %d de șters", current, version,
                    len(plan.writes), len(plan.existed), len(plan.first_deletes) + len(plan.deletes))
        try:
            _extract(archive, files, work / NEW_DIR_NAME)
        except BaseException:
            update_recovery.clear_work(work)
            raise
    _install(root, plan)
    return plan


def apply_update(zip_path: Path, root: Path, expected_version: str, *, progress: Callable[[str], None] | None = None) -> ApplyResult:
    """Instalează arhiva în `root` și întoarce ApplyResult; ridică UpdateError, iar după orice eroare `root` e exact ca înainte.

    Refuză: o copie git (D9), folderul de lucru (sau nou/, vechi/, copie/, descarcari/ din el) legătură, o versiune care nu e mai nouă
    decât cea instalată (citită sub lacăt, P2), o arhivă care nu trece validate_archive și o cale prea lungă pentru Windows.
    `progress("instalez")` se cheamă o dată, după verificarea versiunii, dacă e dat. După succes, în .actualizare rămâne doar
    fișierul-lacăt gol (N5); după un refuz de sub lacăt, tot doar el.
    """
    root = Path(root).resolve()
    version = _canonical_version(expected_version)
    if is_git_checkout(root):
        raise UpdateError(MESSAGE_GIT_CHECKOUT)
    work = root / WORK_DIR_NAME
    try:
        # Înaintea lacătului (care s-ar crea în ținta unei legături) și a oricărei reveniri (care ar muta fișiere din alt loc, N4).
        update_recovery.refuse_linked_work_dirs(work)
        with UpdateLock(work / LOCK_NAME):
            plan = _prepare_and_install(zip_path, root, version, progress)
    except (RecoveryError, LockError) as error:
        raise UpdateError(str(error)) from error
    logger.info("actualizare %s → %s: instalată", plan.from_version, version)
    return ApplyResult(plan.from_version, version, len(plan.writes), len(plan.first_deletes) + len(plan.deletes))


def recover_interrupted(root: Path) -> str | None:
    """Revine la versiunea veche dacă o aplicare a fost întreruptă (jurnal „aplicare”, D11), prin update_recovery.recover.

    Întoarce None dacă n-a fost nimic de spus, altfel mesajul pentru utilizator. Ridică UpdateError dacă alt proces aplică chiar acum,
    dacă jurnalul e deteriorat, dacă un folder de lucru e legătură sau dacă revenirea nu s-a putut termina (se reia la pornirea următoare).
    La pornirea programului, ruleaza.py folosește direct update_recovery.recover_before_start (fără niciun alt import, N2).
    """
    try:
        return update_recovery.recover(root)
    except (RecoveryError, LockError) as error:
        raise UpdateError(str(error)) from error
