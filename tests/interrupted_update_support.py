"""Un program real, întrerupt la jumătatea unei actualizări, pentru testele lansatoarelor (P1, decis 6 oct. 2026).

Ce face: copiază în folderul testului programul din arborele curent (fișierele care ar urca în git) cu manifestul lui, ca o
instalare „veche”; scrie instalare/versiuni.txt cu valorile cerute de test (uv fals, Python-ul testelor); face arhiva unei versiuni
inventate, mai noi, care schimbă doar versiunea și o valoare din versiuni.txt; rulează apply_update REAL al copiei într-un proces
copil care se oprește brusc (os._exit, ca un proces omorât, fără curățenie) imediat după ce a înlocuit instalare/versiuni.txt.
Ce NU face: nu pregătește uv-ul și .venv-ul fals (le face fiecare test de lansator, pentru sistemul lui), nu iese pe internet și
nu scrie în proiect.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from emag_spend.update_recovery import JOURNAL_NAME, STATE_APPLYING, WORK_DIR_NAME
from emag_spend.version import VERSION
from tests.garda_support import PROJECT_ROOT, files_to_publish
from tests.update_archive_support import MANIFEST, VERSION_FILE, manifest_bytes, newer_than, write_archive

VERSIONS_FILE = "instalare/versiuni.txt"
# Ultimul fișier mutat de aplicare înainte de oprire: pregătirea lansatoarelor îl citește, iar în ordinea alfabetică a scrierilor
# vine înaintea lui instaleaza.bat, porneste.*, requirements.txt și ruleaza.py (V1-1).
STOP_AFTER = VERSIONS_FILE
# Codul cu care se oprește procesul copil la punctul cerut; altul înseamnă că aplicarea nu a ajuns acolo (testul pică, nu trece).
KILLED_EXIT_CODE = 86
CHILD_TIMEOUT_SECONDS = 120
VERSION_LINE = re.compile(r'(?m)^VERSION = "[^"]*"$')

# Procesul copil: programul „vechi” din copie își aplică actualizarea; os.replace e înlocuit cu unul care, după ce mută ținta
# cerută, oprește procesul pe loc (os._exit: fără finally, fără revenire, exact ca la un proces omorât).
INTERRUPTING_CHILD = '''\
import os
import sys
from pathlib import Path

root, archive, version, stop_after, code = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
sys.path.insert(0, str(root))
target = os.path.normcase(str(root / stop_after))
real_replace = os.replace


def replace_then_stop(source, destination, *args, **kwargs):
    real_replace(source, destination, *args, **kwargs)
    if os.path.normcase(os.path.abspath(os.fspath(destination))) == target:
        os._exit(code)


os.replace = replace_then_stop
from emag_spend.update_apply import apply_update

apply_update(archive, root, version)
raise SystemExit(f"aplicarea s-a terminat fără să ajungă la {stop_after}")
'''


def copy_program(root: Path) -> dict[str, bytes]:
    """Copiază în `root` fișierele programului (ce ar urca în git) plus manifestul lor; întoarce {cale relativă: conținut}, fără manifest."""
    files = {}
    for path in files_to_publish():
        if path.is_file():
            files[path.relative_to(PROJECT_ROOT).as_posix()] = path.read_bytes()
    files.pop(MANIFEST, None)
    for relative, data in {**files, MANIFEST: manifest_bytes(files)}.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return files


def with_versions(files: dict[str, bytes], **values: str) -> bytes:
    """instalare/versiuni.txt din `files`, cu cheile date (UV_VERSION=..., PYTHON_VERSION=...) înlocuite; ridică dacă o cheie lipsește."""
    text = files[VERSIONS_FILE].decode("utf-8")
    for key, value in values.items():
        text, count = re.subn(rf"(?m)^{key}=.*$", f"{key}={value}", text)
        assert count == 1, f"{VERSIONS_FILE} nu are exact un rând {key}="
    return text.encode("utf-8")


def install_versions(root: Path, files: dict[str, bytes], **values: str) -> dict[str, bytes]:
    """Scrie în `root` versiuni.txt cu valorile date și întoarce `files` actualizat (copia „instalată” are exact aceste fișiere)."""
    content = with_versions(files, **values)
    (root / VERSIONS_FILE).write_bytes(content)
    return {**files, VERSIONS_FILE: content}


def release_with_versions(archive: Path, files: dict[str, bytes], **values: str) -> tuple[str, bytes]:
    """Arhiva versiunii inventate newer_than(VERSION): `files` cu VERSION nou și versiuni.txt schimbat.

    Întoarce (versiunea nouă, conținutul lui versiuni.txt din ea).
    """
    version = newer_than(VERSION)
    source = files[VERSION_FILE].decode("utf-8")
    assert len(VERSION_LINE.findall(source)) == 1, f"{VERSION_FILE} nu are exact un rând VERSION = \"...\""
    versions = with_versions(files, **values)
    new_files = {**files, VERSION_FILE: VERSION_LINE.sub(f'VERSION = "{version}"', source).encode("utf-8"), VERSIONS_FILE: versions}
    write_archive(archive, version, new_files)
    return version, versions


def interrupt_update(root: Path, archive: Path, version: str, new_versions: bytes, script_dir: Path) -> None:
    """Aplică arhiva peste `root` cu codul copiei și oprește procesul imediat după mutarea lui STOP_AFTER (scriptul stă în `script_dir`).

    Verifică punctul de oprire: codul KILLED_EXIT_CODE, jurnalul rămas în starea „aplicare” și versiuni.txt deja cel nou (`new_versions`).
    """
    script = script_dir / "aplicare_oprita.py"
    script.write_text(INTERRUPTING_CHILD, encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, str(script), str(root), str(archive), version, STOP_AFTER, str(KILLED_EXIT_CODE)],
                            cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=CHILD_TIMEOUT_SECONDS)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode == KILLED_EXIT_CODE, f"aplicarea nu s-a oprit după {STOP_AFTER} (cod {result.returncode}):\n{output}"
    journal = json.loads((root / WORK_DIR_NAME / JOURNAL_NAME).read_text(encoding="utf-8"))
    assert journal["stare"] == STATE_APPLYING and journal["la"] == version, journal
    assert (root / VERSIONS_FILE).read_bytes() == new_versions, f"{VERSIONS_FILE} trebuia să fie deja cel din versiunea {version}"
