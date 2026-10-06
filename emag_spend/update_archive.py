"""Regulile arhivei unei versiuni noi și ale căilor din ea: ce intră, ce se refuză (decis 5 oct. 2026, D7, D8; N7 din 6 oct. 2026).

Primește: arhiva ZIP deschisă (zipfile) și versiunea așteptată; căi relative din arhivă sau din manifest.
Dă înapoi: {cale relativă: intrare} pentru fișierele unei arhive valide, sau UpdateError cu motivul, în română.
Reguli: un singur prefix cheltuieli-emag-vX.Y.Z/, căi fără «..», «\\», «:», nume rezervate Windows; fără legături, duplicate, căi
protejate (datele utilizatorului, D7); fișierele obligatorii prezente; VERSION din arhivă == versiunea; manifestul == arhiva.
Căile protejate și regulile care țin o cale în program vin din update_recovery.py (sursa unică, folosită și de recuperare) și se reexportă.
Ce NU face: nu scrie nimic pe disc și nu execută nimic din arhivă (VERSION se citește din arborele AST); scrierea e în update_apply.py.
"""

import ast
import stat
import zipfile
import zlib

from emag_spend.update_errors import UpdateError
from emag_spend.update_recovery import (  # noqa: F401 - reexportate: update_apply.py și testele le iau de aici
    GIT_DIR_NAME, PROTECTED_DIRS, PROTECTED_FILES, ancestors, escape_problem, is_protected, path_key,
)

# ---------- forma arhivei (aceeași cu .github/workflows/lansare.yml) ----------
# lansare.yml: NUME="cheltuieli-emag-$ETICHETA", git archive --prefix="$NUME/"; eticheta e "v" + VERSION (D1).
ARCHIVE_PREFIX_TEMPLATE = "cheltuieli-emag-v{version}/"
MANIFEST_PATH = "instalare/fisiere.txt"  # D8: lista fișierelor din etichetă, câte o cale POSIX pe rând, LF
VERSION_FILE_PATH = "emag_spend/version.py"
VERSION_VARIABLE = "VERSION"
# Fără oricare dintre ele, versiunea nouă n-ar putea porni sau n-ar putea fi actualizată la rândul ei. Contract stabil cu versiunile
# deja instalate (decis 6 oct. 2026, N7): lansatorul VECHI cheamă după actualizare fișierele NOI (dupa_rulare.bat, instaleaza.bat,
# mediu.bat/.sh, pregatire.sh), iar ruleaza.py importă recuperarea (update_recovery.py, update_lock.py, __init__.py) înaintea oricărui
# alt modul. Un fișier scos de aici poate lăsa fără repornire sau fără recuperare toți utilizatorii unei versiuni vechi.
REQUIRED_FILES = (
    VERSION_FILE_PATH, MANIFEST_PATH, "ruleaza.py", "porneste.bat", "porneste.sh", "porneste.command",
    "instalare/dupa_rulare.bat", "instaleaza.bat", "instalare/mediu.bat", "instalare/mediu.sh", "instalare/pregatire.sh",
    "emag_spend/__init__.py", "emag_spend/update_recovery.py", "emag_spend/update_lock.py",
)

# Ce nu se atinge niciodată (D7): PROTECTED_DIRS, PROTECTED_FILES și is_protected, din update_recovery.py.

# ---------- limite ----------
# Lansarea 1.0.0 are ~200 de fișiere și ~2,5 MB dezarhivați; limitele lasă o marjă de 25× și 40× și opresc o arhivă absurdă.
MAX_ARCHIVE_ENTRIES = 5000
MAX_UNPACKED_BYTES = 100_000_000
# version.py și manifestul se citesc în memorie la validare; au câțiva KB, deci 1 MB e o marjă mare.
MAX_METADATA_BYTES = 1_000_000
EXECUTABLE_BITS = 0o111
ZIP_ENCRYPTED_FLAG = 0x1

# ---------- nume refuzate ----------
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{device}{index}" for device in ("COM", "LPT") for index in (*"123456789", "¹", "²", "³")}
)
# Nepermise în nume pe Windows (în plus față de backslash și «:», refuzate deja de update_recovery.escape_problem).
FORBIDDEN_NAME_CHARACTERS = frozenset('*?"<>|')

# Erorile pe care le poate da citirea unei arhive deteriorate (CRC greșit, compresie necunoscută, fișier trunchiat).
ARCHIVE_READ_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error, ValueError)

MESSAGE_DAMAGED = "Arhiva actualizării e deteriorată ({detail}); n-am schimbat nimic."
MESSAGE_BAD_ENTRY = "Arhiva actualizării are o intrare nepermisă («{name}»: {reason}); n-am schimbat nimic."
MESSAGE_PROTECTED = "Arhiva actualizării conține o cale protejată («{path}»); din siguranță, n-am schimbat nimic."
MESSAGE_MISSING = "Arhiva actualizării nu conține {path}; n-am schimbat nimic."
MESSAGE_WRONG_VERSION = "Arhiva e pentru versiunea «{found}», nu pentru {expected}; n-am schimbat nimic."
MESSAGE_BAD_MANIFEST = "Lista fișierelor din arhivă ({manifest}) nu se potrivește cu arhiva ({detail}); n-am schimbat nimic."
MESSAGE_TOO_MANY = "Arhiva actualizării are prea multe intrări (peste {limit}); n-am schimbat nimic."
MESSAGE_TOO_BIG = "Arhiva actualizării e prea mare după dezarhivare (peste {limit} de octeți); n-am schimbat nimic."


# ---------- căi ----------

def path_problem(relative: str) -> str | None:
    """Motivul, în română, pentru care o cale relativă din arhivă sau din manifest nu e permisă; None dacă e în regulă.

    Întâi regulile care țin calea în program (update_recovery.escape_problem: cale goală sau absolută, «\\», «:», control, «.», «..»,
    componente goale, punct sau spațiu la final, nume scurte 8.3), apoi cele de Windows: *?"<>| și nume rezervate (CON, NUL.txt, COM1...).
    """
    problem = escape_problem(relative)
    if problem:
        return problem
    forbidden = FORBIDDEN_NAME_CHARACTERS.intersection(relative)
    if forbidden:
        return f"caracterul «{min(forbidden)}», nepermis pe Windows"
    for part in relative.split("/"):
        if part.split(".", 1)[0].rstrip(" ").upper() in WINDOWS_RESERVED_NAMES:
            return "nume rezervat de Windows"
    return None


# ---------- versiunea și manifestul ----------

def version_from_source(text: str) -> str | None:
    """Valoarea lui VERSION dintr-un version.py, citită din arborele AST (codul din arhivă nu se execută niciodată); None dacă lipsește."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == VERSION_VARIABLE and isinstance(value, ast.Constant) and isinstance(value.value, str):
            found = value.value
    return found


def parse_manifest(text: str) -> list[str]:
    """Căile din instalare/fisiere.txt (o cale POSIX pe rând, LF); ValueError cu motivul la o cale nepermisă sau repetată."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    seen: set[str] = set()
    for line in lines:
        problem = path_problem(line)
        if problem:
            raise ValueError(f"«{line}»: {problem}")
        if path_key(line) in seen:
            raise ValueError(f"«{line}» apare de două ori")
        seen.add(path_key(line))
    return lines


# ---------- arhiva ----------

def damaged(error: BaseException) -> UpdateError:
    """UpdateError pentru o arhivă care nu se poate citi până la capăt (CRC greșit, compresie necunoscută, fișier trunchiat)."""
    return UpdateError(MESSAGE_DAMAGED.format(detail=str(error) or type(error).__name__))


def _refuse(name: str, reason: str) -> UpdateError:
    """UpdateError pentru o intrare nepermisă din arhivă."""
    return UpdateError(MESSAGE_BAD_ENTRY.format(name=name, reason=reason))


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Conținutul unei intrări mici din arhivă (manifest, version.py); UpdateError dacă e prea mare sau arhiva e deteriorată."""
    if info.file_size > MAX_METADATA_BYTES:
        raise _refuse(info.filename, f"e prea mare (peste {MAX_METADATA_BYTES} de octeți)")
    try:
        return archive.read(info)
    except (*ARCHIVE_READ_ERRORS, OSError) as error:
        raise damaged(error) from error


def is_executable_entry(info: zipfile.ZipInfo) -> bool:
    """True dacă intrarea are bitul de execuție în arhivă (`external_attr >> 16 & 0o111`, ca lansatoarele .sh și .command)."""
    return bool((info.external_attr >> 16) & EXECUTABLE_BITS)


def _check_manifest(data: bytes, archive_files: set[str]) -> None:
    """Manifestul nou trebuie să fie exact lista fișierelor din arhivă (nici în plus, nici în minus); altfel UpdateError."""
    try:
        listed = parse_manifest(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise UpdateError(MESSAGE_BAD_MANIFEST.format(manifest=MANIFEST_PATH, detail=str(error))) from error
    missing, extra = sorted(archive_files - set(listed)), sorted(set(listed) - archive_files)
    if missing or extra:
        detail = f"lipsește din listă «{missing[0]}»" if missing else f"«{extra[0]}» nu e în arhivă"
        raise UpdateError(MESSAGE_BAD_MANIFEST.format(manifest=MANIFEST_PATH, detail=detail))


def _entry_path(info: zipfile.ZipInfo, prefix: str) -> str:
    """Calea relativă a unei intrări (fără prefix și fără «/» final la foldere); UpdateError pentru intrarea nepermisă ca formă."""
    name = info.orig_filename
    if name != info.filename:  # zipfile taie la NUL și transformă «\» în «/» pe Windows: numele real e altul decât pare
        raise _refuse(name, "conține NUL sau «\\»")
    if not name.startswith(prefix):
        raise _refuse(name, f"nu e în folderul {prefix}")
    if info.flag_bits & ZIP_ENCRYPTED_FLAG:
        raise _refuse(name, "e criptată")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise _refuse(name, "e o legătură simbolică")
    if not info.is_dir() and mode and not stat.S_ISREG(mode):
        raise _refuse(name, "nu e un fișier obișnuit")
    relative = name[len(prefix):]
    return relative[:-1] if info.is_dir() else relative


def validate_archive(archive: zipfile.ZipFile, version: str, extra_protected: tuple[str, ...] = ()) -> dict[str, zipfile.ZipInfo]:
    """Verifică toată arhiva fără să scrie nimic și întoarce {cale relativă: intrare} pentru fișiere; ridică UpdateError.

    Reguli: un singur prefix cheltuieli-emag-v{version}/; căi permise (path_problem); fără legături simbolice, fișiere speciale,
    intrări criptate, duplicate (și fără litere mari/mici) sau o cale care e și fișier, și folder; limite de număr și mărime;
    fără căi protejate; fișierele REQUIRED_FILES prezente; VERSION din version.py == `version`; manifestul == fișierele arhivei.
    """
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise UpdateError(MESSAGE_TOO_MANY.format(limit=MAX_ARCHIVE_ENTRIES))
    prefix = ARCHIVE_PREFIX_TEMPLATE.format(version=version)
    files: dict[str, zipfile.ZipInfo] = {}
    file_keys: set[str] = set()
    folder_keys: set[str] = set()
    total = 0
    for info in infos:
        relative = _entry_path(info, prefix)
        if info.is_dir() and not relative:
            continue  # folderul-rădăcină al arhivei
        problem = path_problem(relative)
        if problem:
            raise _refuse(info.orig_filename, problem)
        if is_protected(relative, extra_protected):
            raise UpdateError(MESSAGE_PROTECTED.format(path=relative))
        key = path_key(relative)
        if info.is_dir():
            folder_keys.add(key)
            continue
        if key in file_keys:
            raise _refuse(info.orig_filename, "apare de două ori")
        file_keys.add(key)
        files[relative] = info
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise UpdateError(MESSAGE_TOO_BIG.format(limit=MAX_UNPACKED_BYTES))
    for relative in files:
        clash = next((folder for folder in ancestors(relative) if path_key(folder) in file_keys), None)
        if clash is None and path_key(relative) in folder_keys:
            clash = relative
        if clash is not None:
            raise _refuse(prefix + clash, "e și fișier, și folder")
    for required in REQUIRED_FILES:
        if required not in files:
            raise UpdateError(MESSAGE_MISSING.format(path=required))
    found = version_from_source(_read_member(archive, files[VERSION_FILE_PATH]).decode("utf-8", errors="replace"))
    if found != version:
        raise UpdateError(MESSAGE_WRONG_VERSION.format(found=found or "necunoscută", expected=version))
    _check_manifest(_read_member(archive, files[MANIFEST_PATH]), set(files))
    return files
