"""Verifică arhiva unei lansări înainte de publicare (decis 5 oct. 2026, D7, D8, D14 și D16), pentru lansare.yml.

Primește: arhiva ZIP făcută de git archive și versiunea X.Y.Z. Aplică exact regulile cu care o va verifica actualizarea
(emag_spend.update_archive.validate_archive: prefix, căi, căi protejate, manifest == arhivă, VERSION), plus lansatoarele:
fiecare .bat cu CRLF peste tot, fiecare .sh și .command doar cu LF, iar cele rulate direct au bitul de execuție (0o755).
Dă înapoi: codul 0 și un rezumat; altfel fiecare problemă pe ieșirea de erori și codul 1, ca lansarea să nu fie publicată.
Ce NU face: nu face și nu modifică arhiva, nu publică nimic.
"""

import argparse
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from emag_spend.update_archive import validate_archive  # noqa: E402  (după sys.path: scriptul rulează din .github/scripts)
from emag_spend.update_errors import UpdateError  # noqa: E402

WINDOWS_LAUNCHER_SUFFIXES = (".bat", ".cmd")
UNIX_SCRIPT_SUFFIXES = (".sh", ".command")
# Scripturile pe care utilizatorul (sau lansatorul) le rulează direct: fără bitul de execuție, „./porneste.sh” dă „Permission
# denied”. instalare/mediu.sh lipsește intenționat: se încarcă cu „.”, nu se rulează. Aceeași listă ca EXECUTABLES din
# tests/test_lansatoare_unix.py.
EXECUTED_SCRIPTS = ("porneste.sh", "porneste.command", "instalare/pregatire.sh")
EXECUTABLE_MODE = 0o755  # rwxr-xr-x: ce pune git archive pentru un fișier 100755
PERMISSION_BITS = 0o777


def launcher_problems(archive: zipfile.ZipFile) -> list[str]:
    """Problemele lansatoarelor din arhivă: .bat fără CRLF peste tot, .sh/.command cu CR, scripturi rulate direct fără 0o755.

    Căile din EXECUTED_SCRIPTS se caută după primul folder al arhivei (prefixul cheltuieli-emag-vX.Y.Z/). Listă goală = bine.
    """
    problems = []
    for info in archive.infolist():
        name = info.filename
        relative = name.split("/", 1)[1] if "/" in name else name
        if name.endswith(WINDOWS_LAUNCHER_SUFFIXES):
            data = archive.read(info)
            if not data.endswith(b"\r\n") or data.count(b"\n") != data.count(b"\r\n"):
                problems.append(f"{name}: nu are CRLF peste tot (cmd.exe s-ar încurca); verifică .gitattributes")
        elif name.endswith(UNIX_SCRIPT_SUFFIXES) and b"\r" in archive.read(info):
            problems.append(f"{name}: are CR; pe macOS și Linux scriptul n-ar porni")
        if relative in EXECUTED_SCRIPTS:
            mode = (info.external_attr >> 16) & PERMISSION_BITS
            if mode != EXECUTABLE_MODE:
                problems.append(f"{name}: are modul {oct(mode)}, trebuie {oct(EXECUTABLE_MODE)} (git add --chmod=+x)")
    missing = sorted(set(EXECUTED_SCRIPTS) - {info.filename.split("/", 1)[-1] for info in archive.infolist()})
    problems.extend(f"lipsește {name} din arhivă" for name in missing)
    return problems


def check_archive(path: Path, version: str) -> list[str]:
    """Toate problemele arhivei de la `path` pentru versiunea `version`; listă goală = poate fi publicată."""
    with zipfile.ZipFile(path) as archive:
        try:
            validate_archive(archive, version)
        except UpdateError as error:
            return [f"actualizarea ar refuza arhiva: {error}"]
        return launcher_problems(archive)


def main(argv: list[str] | None = None) -> int:
    """Linia de comandă: `release_archive_check.py ARHIVA VERSIUNE`; 0 dacă arhiva e bună, 1 cu problemele altfel."""
    parser = argparse.ArgumentParser(description="Verifică arhiva lansării cu regulile actualizării și ale lansatoarelor.")
    parser.add_argument("arhiva", type=Path, help="arhiva ZIP a lansării")
    parser.add_argument("versiune", help="versiunea X.Y.Z, fără „v”")
    args = parser.parse_args(argv)
    try:
        problems = check_archive(args.arhiva, args.versiune)
    except (OSError, zipfile.BadZipFile) as error:
        problems = [f"arhiva nu se poate citi: {error}"]
    for problem in problems:
        print(f"EROARE: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.arhiva}: bună pentru actualizarea la {args.versiune}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
