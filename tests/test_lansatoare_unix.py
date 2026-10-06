"""Teste pentru lansatoarele de macOS și Linux: porneste.command, porneste.sh și instalare/ (pregatire.sh, mediu.sh).

Primește: fișierele, ca text și ca octeți. Verifică static: LF, UTF-8 fără BOM, interpretor POSIX, `set -eu`, că singura
descărcare e uv de la adresa oficială fixată și doar prin HTTPS, că amprenta SHA-256 se verifică ÎNAINTE de dezarhivare, că
pachetele se instalează doar gata făcute, că totul stă în folderul programului (.uv/, .venv/), că `sudo` apare doar ca sfat
afișat, nu ca o comandă rulată, și că fișierele executabile au bitul de execuție în git. Dacă există `shellcheck`, îl rulează.
La execuție, cu un `sh` POSIX (pe Windows, cel din Git for Windows) și cu programe false în folderul temporar al testului:
D14 (la codul 75 lansatorul pornește cu `exec sh` varianta lui nouă, înlocuită cât rula Python), D15 (pregatire.sh reface
.venv când Python-ul din el are altă versiune decât PYTHON_VERSION) și N12 (decis 6 oct. 2026: arhiva uv păstrată are versiunea
în nume, una rămasă cu altă amprentă se descarcă o singură dată din nou; cu un curl fals, tar și sha256sum reale; P9: după o
dezarhivare reușită nu rămâne nicio arhivă uv-*). P1 (decis 6 oct. 2026): recuperarea unei actualizări întrerupte rulează ÎNAINTEA
pregătirii, cu oprire la codul 1 și repornire o singură dată (static, cu programe false și cap-coadă: actualizare reală oprită după
instalare/versiuni.txt, apoi lansatorul și pregatire.sh reale, fără internet, cu uv și curl false).
Nu descarcă nimic și nu pornește programul (asta o face jobul „Pornire de la zero” din CI, pe fiecare sistem).
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from emag_spend import settings
from emag_spend.update_recovery import MESSAGE_RECOVERED
from emag_spend.version import VERSION
from tests.fake_uv_release_server import OFFLINE_ENV
from tests.garda_support import PROJECT_ROOT
from tests.interrupted_update_support import copy_program, install_versions, interrupt_update, release_with_versions
from tests.update_archive_support import fingerprint, work_dir_leftovers

LAUNCHERS = ("porneste.sh", "porneste.command")
PREPARE = "instalare/pregatire.sh"
ENVIRONMENT = "instalare/mediu.sh"
SHELL_FILES = LAUNCHERS + (PREPARE, ENVIRONMENT)
EXECUTABLES = LAUNCHERS + (PREPARE,)
UV_URL = "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ARHIVA"
# Ce trebuie să exporte mediu.sh: Python fără __pycache__ și cu UTF-8, plus tot ce descarcă uv și Playwright în .uv/.
ENV_REQUIRED = (
    'export UV_CACHE_DIR="$ROOT/.uv/cache"', 'export UV_PYTHON_INSTALL_DIR="$ROOT/.uv/python"',
    "export UV_PYTHON_PREFERENCE=only-managed", "export UV_NO_CONFIG=1", 'export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.uv/browsere"',
    "export PYTHONUTF8=1", "export PYTHONDONTWRITEBYTECODE=1",
)
GIT_EXECUTABLE_MODE = "100755"
RESTART_EXIT_CODE = settings.EXIT_CODE_RESTART
# D14 (decis 5 oct. 2026): la codul de repornire, shell-ul nou citește lansatorul nou de la început, cu aceleași argumente.
RESTART_LINE = 'exec sh "$LANSATOR" "$@"'
RESTART_MESSAGE = "Programul a fost actualizat. Pornesc versiunea nouă"
RUN_TIMEOUT_SECONDS = 60  # un script blocat (de exemplu o repornire fără sfârșit) nu are voie să țină testele pe loc
# Cât de sus căutăm `bin/sh.exe` pornind de la git.exe (Git\cmd\git.exe sau Git\mingw64\bin\git.exe).
GIT_FOLDER_DEPTH = 3
# Python-ul fals din .venv/bin/python, ca script sh: notează apelul (fără calea lui ruleaza.py), la primul apel înlocuiește
# lansatorul cu varianta nouă prin `mv` (rename, același apel de sistem ca os.replace al actualizării; pe Windows, Python
# nu poate redenumi peste scriptul ținut deschis de sh din Git, iar `mv` din Git da) și iese cu codurile din coduri.txt.
FAKE_PYTHON = """#!/bin/sh
DIR=$(cd "$(dirname "$0")/../.." && pwd)
shift
N=1
if [ -f "$DIR/apeluri.txt" ]; then N=$(( $(wc -l < "$DIR/apeluri.txt") + 1 )); fi
echo "$*" >> "$DIR/apeluri.txt"
if [ "$N" -eq 1 ]; then mv -f "$DIR/varianta_noua.tmp" "$DIR/$(cat "$DIR/lansator.txt")"; fi
COD=$(sed -n "${N}p" "$DIR/coduri.txt")
echo "PYTHON-FALS $N IESE CU ${COD:-99}"
exit "${COD:-99}"
"""
NEW_VARIANT_HEADER = "#!/bin/sh\n# varianta nouă: rânduri în plus la început, deci tot restul e deplasat\necho VARIANTA-NOUA-PORNITA\n"
FAKE_PREPARE = "#!/bin/sh\necho PREGATIRE-FALSA\n"


def _text(name: str) -> str:
    """Conținutul fișierului `name` din proiect."""
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def _commands(text: str) -> list[str]:
    """Rândurile cu cod (fără comentarii și fără rândurile goale), cu spațiile din margini tăiate."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


@pytest.mark.parametrize("name", SHELL_FILES)
def test_shell_files_use_lf_and_utf8_without_bom(name):
    """Pe macOS și Linux un CR la capăt de rând strică scriptul („bad interpreter”, variabile cu \\r): doar LF, UTF-8, fără BOM."""
    raw = (PROJECT_ROOT / name).read_bytes()
    assert b"\r" not in raw, f"{name} are CR: pe macOS/Linux scriptul n-ar porni"
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} începe cu BOM"
    raw.decode("utf-8")


@pytest.mark.parametrize("name", EXECUTABLES)
def test_executables_start_with_posix_sh_and_stop_at_the_first_error(name):
    """Scripturile rulate direct pornesc cu /bin/sh (există pe orice macOS și Linux) și cu `set -eu` (se opresc la prima eroare)."""
    lines = _text(name).splitlines()
    assert lines[0] == "#!/bin/sh", f"{name}: primul rând trebuie să fie «#!/bin/sh»"
    assert "set -eu" in _commands(_text(name)), f"{name}: fără «set -eu» o eroare de descărcare ar trece neobservată"


def test_the_only_download_is_the_pinned_uv_over_https():
    """pregatire.sh descarcă doar uv, de la adresa oficială construită din versiunea fixată, și doar prin HTTPS."""
    text = _text(PREPARE)
    urls = re.findall(r"https?://[^\s\"']+", "\n".join(line for line in _commands(text) if not line.startswith("echo")))
    assert urls == [UV_URL], f"singura adresă din comenzi trebuie să fie {UV_URL}, găsit {urls}"
    assert "--proto '=https'" in text and "--https-only" in text, "curl și wget trebuie să accepte doar HTTPS"
    assert 'UV_VERSION=$(valoare UV_VERSION)' in text and 'AMPRENTA_ASTEPTATA=$(valoare "SHA256_${SISTEM}_${ARH}")' in text, (
        "versiunea și amprenta se citesc din instalare/versiuni.txt, nu se scriu în script")
    assert 'ARHIVA_PASTRATA="uv-$UV_VERSION-$TINTA_ARH-$TINTA_OS.tar.gz"' in text and 'FISIER="$ROOT/.uv/descarcari/$ARHIVA_PASTRATA"' in text, (
        "arhiva păstrată trebuie să aibă versiunea în nume (N12): una rămasă de la alt UV_VERSION ar da o alarmă falsă de amprentă")


def test_fingerprint_is_checked_before_unpacking_and_a_bad_archive_is_removed():
    """Arhiva uv se compară cu amprenta SHA-256 înainte de `tar`; dacă nu se potrivește e ștearsă și scriptul se oprește."""
    text = _text(PREPARE)
    check = text.index('if [ "$(amprenta "$FISIER")" != "$AMPRENTA_ASTEPTATA" ]; then')
    assert check < text.index("tar -xzf"), "amprenta trebuie verificată ÎNAINTE de dezarhivare"
    failure = text[check:text.index("fi", check)]
    assert 'rm -f "$FISIER"' in failure and "exit 1" in failure, "arhiva greșită trebuie ștearsă și pregătirea oprită"


def test_packages_are_installed_only_from_ready_made_wheels_and_only_runtime_requirements():
    """Pachetele vin doar gata făcute (--only-binary): niciun cod de instalare de pe internet nu rulează; doar requirements.txt."""
    install = next(line for line in _commands(_text(PREPARE)) if "pip install" in line)
    assert "--only-binary :all:" in install and '-r "$ROOT/requirements.txt"' in install and "requirements-dev" not in install, install


def test_everything_stays_inside_the_program_folder():
    """mediu.sh trimite cache-ul uv, Python-ul și browserul descărcate în .uv/ din folderul programului; scripturile șterg doar acolo."""
    environment = _text(ENVIRONMENT)
    for required in ENV_REQUIRED:
        assert required in environment, f"mediu.sh nu are «{required}»"
    for name in SHELL_FILES:
        for line in _commands(_text(name)):
            if re.match(r"(?:rm|cp|mkdir|chmod)\b", line):
                targets = re.findall(r'"([^"]+)"', line)
                assert targets and all(target.startswith(("$ROOT/.uv", "$UV", "$FISIER", "$DEZARHIVAT", "$ROOT/.venv")) for target in targets), (
                    f"{name}: «{line}» lucrează în afara .uv/ și .venv/")


@pytest.mark.parametrize("name", SHELL_FILES)
def test_sudo_appears_only_as_advice_never_as_a_command(name):
    """Scripturile nu cer niciodată singure parola de administrator: `sudo` poate apărea doar într-un `echo` (sfat pentru utilizator)."""
    for line in _commands(_text(name)):
        if re.search(r"\bsudo\b", line):
            assert line.startswith("echo "), f"{name}: «{line}» rulează sudo; scriptul trebuie doar să-l recomande"


def test_launchers_prepare_then_start_the_application_or_pass_the_arguments():
    """Ambele lansatoare: încarcă mediul, rulează pregătirea, fără argumente pornesc aplicația (--aplicatie), cu argumente le pasează."""
    for name in LAUNCHERS:
        text = _text(name)
        assert '. "$ROOT/instalare/mediu.sh"' in text and 'sh "$ROOT/instalare/pregatire.sh"' in text, name
        assert '[ "$#" -gt 0 ] || set -- --aplicatie' in text, f"{name}: fără argumente trebuie să pornească aplicația"
        assert '"$ROOT/.venv/bin/python" "$ROOT/ruleaza.py" "$@"' in text, f"{name}: trebuie să ruleze ruleaza.py cu Python-ul din .venv"


@pytest.mark.parametrize("name", EXECUTABLES)
def test_executables_are_marked_executable_in_git(name):
    """În git, lansatoarele au bitul de execuție (100755): altfel, după descărcare, `./porneste.sh` dă „Permission denied”."""
    if not (PROJECT_ROOT / ".git").exists():
        pytest.skip("proiectul nu e un depozit git aici")
    listed = subprocess.run(["git", "ls-files", "-s", "--", name], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout
    if not listed:
        pytest.skip(f"{name} nu e încă în indexul git")
    assert listed.split()[0] == GIT_EXECUTABLE_MODE, f"{name} are modul {listed.split()[0]} în git, trebuie {GIT_EXECUTABLE_MODE} (git add --chmod=+x)"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck nu e instalat aici (în CI pe Linux este)")
def test_shellcheck_finds_no_problems():
    """shellcheck (verificatorul standard de scripturi shell) nu găsește probleme în niciun script, ca POSIX sh."""
    result = subprocess.run(["shellcheck", "--shell=sh", "--external-sources", *SHELL_FILES], cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------- D14: repornirea după actualizare ----------

@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_restart_their_new_version_at_the_restart_code(name):
    """La codul din settings.EXIT_CODE_RESTART, lansatorul face `exec sh` pe calea lui absolută, cu aceleași argumente, înainte de mesajul final."""
    text = _text(name)
    assert f"COD_REPORNIRE={RESTART_EXIT_CODE}" in _commands(text), f"{name}: codul de repornire trebuie să fie cel din settings.py ({RESTART_EXIT_CODE})"
    assert 'LANSATOR="$ROOT/$(basename "$0")"' in _commands(text), f"{name}: repornirea trebuie să folosească o cale absolută"
    run = text.index('"$ROOT/.venv/bin/python" "$ROOT/ruleaza.py" "$@" || COD=$?')
    check = text.index('if [ "$COD" -eq "$COD_REPORNIRE" ]; then', run)
    assert run < check < text.index(RESTART_LINE, check) < text.index("Gata. Rezultatele", check), (
        f"{name}: repornirea trebuie să vină imediat după Python și înaintea mesajului final")


def _posix_shell() -> str | None:
    """Un `sh` POSIX: din PATH pe macOS/Linux; pe Windows, `bin/sh.exe` din Git for Windows (lângă git.exe). None dacă lipsește."""
    if sys.platform != "win32":
        return shutil.which("sh")
    git = shutil.which("git")
    if not git:
        return None
    for folder in Path(git).resolve().parents[:GIT_FOLDER_DEPTH]:
        candidate = folder / "bin" / "sh.exe"
        if candidate.is_file():
            return str(candidate)
    return None


POSIX_SHELL = _posix_shell()
needs_sh = pytest.mark.skipif(POSIX_SHELL is None, reason="nu există un sh POSIX aici (pe Windows: Git for Windows)")


def _write_script(path: Path, text: str) -> None:
    """Scrie un script sh cu LF și bitul de execuție (pe Windows, sh din Git îl recunoaște după «#!»)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    path.chmod(0o755)


def _run_sh(folder: Path, script: str, tools: Path | None = None, args: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Rulează `sh script args` în `folder`, cu stdin închis (ca dintr-o fereastră fără tastatură), cu limită de timp.

    `tools`: un folder cu unelte false pus PRIMUL în PATH, din interiorul lui sh (sh din Git își pune singur /usr/bin în față,
    deci un PATH dat din afară n-ar ajunge primul). Proxy-ul e mereu un port mort (OFFLINE_ENV): nimic nu poate ieși pe internet.
    """
    command = [POSIX_SHELL, script, *args]
    env = {**os.environ, **OFFLINE_ENV}
    if tools is not None:
        env["UNELTE_FALSE"] = tools.as_posix()
        convert = '$(cygpath -u "$UNELTE_FALSE")' if sys.platform == "win32" else '$UNELTE_FALSE'
        command = [POSIX_SHELL, "-c", f'PATH="{convert}:$PATH"; export PATH; exec sh "$0" "$@"', script, *args]
    return subprocess.run(command, cwd=folder, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=RUN_TIMEOUT_SECONDS)


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
@pytest.mark.parametrize("codes", ((RESTART_EXIT_CODE, 0), (RESTART_EXIT_CODE, 7), (0,), (7,)), ids=str)
def test_launcher_replaced_while_python_runs_restarts_its_new_version(tmp_path, name, codes):
    """D14 la execuție: Python-ul fals înlocuiește lansatorul (redenumire) și iese cu 75 → pornește varianta nouă, care reface
    pregătirea, iar codul ei ajunge neschimbat la final; cu alt cod, rularea veche se termină normal și varianta nouă nu rulează."""
    shutil.copy(PROJECT_ROOT / name, tmp_path / name)
    (tmp_path / "instalare").mkdir()
    shutil.copy(PROJECT_ROOT / ENVIRONMENT, tmp_path / ENVIRONMENT)
    _write_script(tmp_path / PREPARE, FAKE_PREPARE)
    _write_script(tmp_path / ".venv" / "bin" / "python", FAKE_PYTHON)
    (tmp_path / "lansator.txt").write_bytes(name.encode("ascii"))
    (tmp_path / "coduri.txt").write_bytes("".join(f"{code}\n" for code in codes).encode("ascii"))
    (tmp_path / "varianta_noua.tmp").write_bytes(NEW_VARIANT_HEADER.encode("utf-8") + (PROJECT_ROOT / name).read_bytes())
    result = _run_sh(tmp_path, name)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    restarts = len(codes) - 1
    calls = (tmp_path / "apeluri.txt").read_text(encoding="utf-8").splitlines()
    assert result.returncode == codes[-1], f"cod {result.returncode}, așteptat {codes[-1]}:\n{output}"
    assert calls == ["--aplicatie"] * len(codes), f"apelurile lui Python: {calls}\n{output}"
    assert output.count("VARIANTA-NOUA-PORNITA") == restarts and output.count(RESTART_MESSAGE) == restarts, output
    assert output.count("PREGATIRE-FALSA") == len(codes), f"varianta nouă trebuie să refacă pregătirea:\n{output}"
    final = "Gata. Rezultatele" if codes[-1] == 0 else f"(cod {codes[-1]})"
    assert output.count(final) == 1, f"mesajul final trebuie să apară o singură dată, de la ultima rulare:\n{output}"


# ---------- P1: recuperarea înaintea pregătirii ----------

# P1 (decis 6 oct. 2026): cu jurnal și .venv, recuperarea rulează ÎNAINTEA pregătirii; la 1 lansatorul se oprește, altfel pornește
# din nou, cu `exec sh`, lansatorul de pe disc (recuperarea poate să-l fi înlocuit), o singură dată (semnul de mai jos).
RECOVERY_MARKER = "CHELTUIELI_EMAG_DUPA_RECUPERARE"
RECOVERY_SETUP = (f"DUPA_RECUPERARE=${{{RECOVERY_MARKER}:-}}", f"unset {RECOVERY_MARKER}")
RECOVERY_CONDITION = 'if [ -z "$DUPA_RECUPERARE" ] && [ -e "$ROOT/.actualizare/jurnal.json" ] && [ -x "$ROOT/.venv/bin/python" ]; then'
RECOVERY_RUN = '"$ROOT/.venv/bin/python" -m emag_spend.update_recovery || COD=$?'
# Blocul recuperării, rând cu rând; ECHO_LINE ține locul unui `echo` (mesajul poate fi reformulat fără să se schimbe testul).
ECHO_LINE = "echo"
RECOVERY_BLOCK = (
    RECOVERY_CONDITION, "COD=0", RECOVERY_RUN,
    'if [ "$COD" -eq 1 ]; then', ECHO_LINE, ECHO_LINE, "asteapta_enter", "exit 1", "fi",
    f"export {RECOVERY_MARKER}=1", RESTART_LINE, "fi",
)
PREPARE_CALL = 'if ! sh "$ROOT/instalare/pregatire.sh"; then'


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_recover_before_preparing_and_restart_only_once(name):
    """P1 static: semnul se citește și se golește la început; recuperarea (cu jurnal și .venv, nu imediat după o recuperare)
    rulează după mediu și ÎNAINTEA pregătirii; la codul 1 lansatorul se oprește cu mesaj, altfel pornește din nou, cu semnul pus."""
    commands = _commands(_text(name))
    assert RECOVERY_CONDITION in commands, f"{name}: lipsește recuperarea înaintea pregătirii (P1): «{RECOVERY_CONDITION}»"
    recovery = commands.index(RECOVERY_CONDITION)
    block = commands[recovery:recovery + len(RECOVERY_BLOCK)]
    matches = [line.startswith(ECHO_LINE) if expected == ECHO_LINE else line == expected for line, expected in zip(block, RECOVERY_BLOCK)]
    assert len(block) == len(RECOVERY_BLOCK) and all(matches), f"{name}: blocul recuperării trebuie să fie exact {RECOVERY_BLOCK}, găsit {block}"
    for line in (*RECOVERY_SETUP, '. "$ROOT/instalare/mediu.sh"', "asteapta_enter() {"):
        assert line in commands[:recovery], f"{name}: «{line}» trebuie să fie înaintea recuperării"
    assert PREPARE_CALL in commands[recovery:], f"{name}: recuperarea trebuie să ruleze ÎNAINTEA pregătirii (pregatire.sh)"


# Python-ul fals pentru P1 (.venv/bin/python, script sh): la `-m` e recuperarea (înlocuiește lansatorul dacă scrie în lansator.txt,
# șterge jurnalul dacă nu există jurnal_ramane.txt, iese cu codul din cod_recuperare.txt); altfel e programul. Amândouă spun dacă
# au primit semnul repornirii, ca testul să vadă că nu ajunge la program.
FAKE_RECOVERING_PYTHON = """#!/bin/sh
DIR=$(cd "$(dirname "$0")/../.." && pwd)
if [ "$1" = "-m" ]; then
  echo "RECUPERARE-FALSA $2"
  if [ -f "$DIR/lansator.txt" ]; then mv -f "$DIR/varianta_noua.tmp" "$DIR/$(cat "$DIR/lansator.txt")"; fi
  if [ ! -f "$DIR/jurnal_ramane.txt" ]; then rm -f "$DIR/.actualizare/jurnal.json"; fi
  exit "$(cat "$DIR/cod_recuperare.txt")"
fi
shift
echo "PROGRAM-FALS $* ${CHELTUIELI_EMAG_DUPA_RECUPERARE:-fara-semn}"
"""
RECOVERY_SHOWN = "RECUPERARE-FALSA emag_spend.update_recovery"
PREPARE_SHOWN = "PREGATIRE-FALSA"
PROGRAM_SHOWN = "PROGRAM-FALS --aplicatie fara-semn"
RECOVERY_FAILED_MESSAGE = "Pornirea s-a oprit"
OTHER_RECOVERY_CODE = 3  # orice alt cod decât 1: se merge mai departe, ca înainte de P1


def _recovering_folder(folder: Path, name: str, code: int, *, journal: bool = True, venv: bool = True, journal_stays: bool = False,
                       replace: bool = False) -> None:
    """Pregătește în `folder` lansatorul real `name`, mediul real, pregătirea falsă, jurnalul și Python-ul fals de mai sus."""
    shutil.copy(PROJECT_ROOT / name, folder / name)
    (folder / "instalare").mkdir()
    shutil.copy(PROJECT_ROOT / ENVIRONMENT, folder / ENVIRONMENT)
    _write_script(folder / PREPARE, FAKE_PREPARE)
    if venv:
        _write_script(folder / ".venv" / "bin" / "python", FAKE_RECOVERING_PYTHON)
    if journal:
        (folder / ".actualizare").mkdir()
        (folder / ".actualizare" / "jurnal.json").write_bytes(b'{"inventat": true}\n')
    (folder / "cod_recuperare.txt").write_bytes(f"{code}\n".encode("ascii"))
    if journal_stays:
        (folder / "jurnal_ramane.txt").write_bytes(b"")
    if replace:
        (folder / "lansator.txt").write_bytes(name.encode("ascii"))
        (folder / "varianta_noua.tmp").write_bytes(NEW_VARIANT_HEADER.encode("utf-8") + (PROJECT_ROOT / name).read_bytes())


def _run_recovering(folder: Path, name: str, code: int, **options) -> tuple[subprocess.CompletedProcess, str]:
    """Rulează lansatorul `name` pregătit de _recovering_folder; întoarce (rezultatul, ieșirea)."""
    _recovering_folder(folder, name, code, **options)
    result = _run_sh(folder, name)
    return result, (result.stdout + result.stderr).decode("utf-8", errors="replace")


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_recovers_an_interrupted_update_before_preparing(tmp_path, name):
    """P1 la execuție: cu jurnal și .venv, recuperarea rulează ÎNAINTEA pregătirii, o dată, apoi pregătirea și programul (fără
    semnul repornirii); cod 0."""
    result, output = _run_recovering(tmp_path, name, 0)
    order = [output.find(mark) for mark in (RECOVERY_SHOWN, PREPARE_SHOWN, PROGRAM_SHOWN)]
    assert result.returncode == 0, output
    assert -1 < order[0] < order[1] < order[2], f"ordinea trebuie să fie recuperare, pregătire, program:\n{output}"
    assert [output.count(mark) for mark in (RECOVERY_SHOWN, PREPARE_SHOWN, PROGRAM_SHOWN)] == [1, 1, 1], output


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_stops_with_the_message_when_the_recovery_fails(tmp_path, name):
    """P1 la execuție: la codul 1 al recuperării lansatorul se oprește cu mesaj și cod 1, fără pregătire și fără program."""
    result, output = _run_recovering(tmp_path, name, 1, journal_stays=True)
    assert result.returncode == 1 and RECOVERY_SHOWN in output and RECOVERY_FAILED_MESSAGE in output, output
    assert PREPARE_SHOWN not in output and "PROGRAM-FALS" not in output, f"după o recuperare eșuată nu se pregătește nimic:\n{output}"


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
@pytest.mark.parametrize("code, journal_stays", [(0, True), (OTHER_RECOVERY_CODE, True)], ids=("jurnal-ramas", "alt-cod"))
def test_launcher_tries_the_recovery_only_once_and_otherwise_goes_on_as_before(tmp_path, name, code, journal_stays):
    """P1 la execuție: un jurnal rămas sau alt cod decât 1 nu repornesc lansatorul la nesfârșit: recuperarea o dată, apoi ca înainte."""
    result, output = _run_recovering(tmp_path, name, code, journal_stays=journal_stays)
    assert result.returncode == 0, output
    assert [output.count(mark) for mark in (RECOVERY_SHOWN, PREPARE_SHOWN, PROGRAM_SHOWN)] == [1, 1, 1], output


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
@pytest.mark.parametrize("journal, venv", [(False, True), (True, False)], ids=("fara-jurnal", "fara-venv"))
def test_launcher_without_a_journal_or_a_venv_prepares_first_as_before(tmp_path, name, journal, venv):
    """P1 la execuție: fără jurnal nu rulează nicio recuperare; fără .venv pregătirea merge întâi, ca înainte."""
    result, output = _run_recovering(tmp_path, name, 0, journal=journal, venv=venv)
    assert "RECUPERARE-FALSA" not in output and PREPARE_SHOWN in output, output
    if venv:
        assert result.returncode == 0 and PROGRAM_SHOWN in output, output


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_replaced_by_the_recovery_starts_again_from_the_beginning(tmp_path, name):
    """P1 la execuție: recuperarea înlocuiește lansatorul (ca la revenirea unui lansator nou la cel vechi); cel de pe disc pornește
    din nou de la început, o singură dată, apoi pregătirea și programul."""
    result, output = _run_recovering(tmp_path, name, 0, replace=True)
    assert result.returncode == 0, output
    assert output.count("VARIANTA-NOUA-PORNITA") == 1, f"lansatorul de pe disc trebuia pornit o dată, de la început:\n{output}"
    assert [output.count(mark) for mark in (RECOVERY_SHOWN, PREPARE_SHOWN, PROGRAM_SHOWN)] == [1, 1, 1], output


# ---------- P1 cap-coadă: actualizare reală oprită după versiuni.txt, apoi lansatorul și pregatire.sh reale, fără internet ----------

# Versiunile lui uv din test sunt inventate: E2E_UV_VERSION e cea „instalată” (uv-ul fals o raportează), E2E_NEW_UV_VERSION cea cerută
# de versiunea nouă (pregatire.sh ar descărca-o, dar curl-ul fals nu are rețea).
E2E_UV_VERSION = "9.8.7"
E2E_NEW_UV_VERSION = "9.8.8"
TEST_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"
NEXT_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor + 1}"  # Python-ul cerut de versiunea nouă: uv-ul fals nu-l poate aduce
# Ce schimbă versiunea nouă în instalare/versiuni.txt: fiecare face pregătirea să pice fără internet, pe arborele amestecat.
NEW_RELEASE_CHANGES = {"uv-nou": {"UV_VERSION": E2E_NEW_UV_VERSION}, "python-nou": {"PYTHON_VERSION": NEXT_PYTHON}}
# uv fals: la --version spune versiunea, orice altă comandă pică (nu descarcă și nu creează nimic).
FAILING_UV = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "uv {version}"; exit 0; fi
echo "uv fals: nu pot face $*" >&2
exit 2
"""
OFFLINE_CURL = """#!/bin/sh
echo "curl fals: (6) rețea indisponibilă" >&2
exit 6
"""
# Folderele care se schimbă oricum la o pornire: lucrul actualizării (rămâne doar lacat) și jurnalele (recuperarea lasă urmă).
CHANGING_DIRS = (".actualizare", "logs")
PROGRAM_NAME = "Cheltuieli eMAG"  # ce scrie `ruleaza.py --versiune` înaintea versiunii


def _ready_environment(root: Path) -> Path:
    """Mediu gata, ca după o primă pornire, fără internet: uv fals în versiunea din versiuni.txt, .venv/bin/python = Python-ul
    testelor (cu pachetele lor), amprenta cerințelor potrivită, browserul marcat gata; întoarce uneltele false (uname, curl fără rețea)."""
    _write_script(root / ".venv" / "bin" / "python", f"#!/bin/sh\nexec '{Path(sys.executable).as_posix()}' \"$@\"\n")
    _write_script(root / ".uv" / "bin" / "uv", FAILING_UV.format(version=E2E_UV_VERSION))
    (root / ".venv" / "cerinte.sha256").write_bytes(hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest().encode("ascii") + b"\n")
    (root / ".uv" / "browser.ok").write_bytes(b"")
    tools = root.parent / "unelte"
    _write_script(tools / "uname", FAKE_UNAME)
    _write_script(tools / "curl", OFFLINE_CURL)
    return tools


@needs_sh
@pytest.mark.parametrize("name", LAUNCHERS)
@pytest.mark.parametrize("change", sorted(NEW_RELEASE_CHANGES))
def test_launcher_recovers_a_real_interrupted_update_offline_before_the_real_preparation(tmp_path, name, change):
    """P1 cap-coadă (V1-1): actualizarea reală e oprită brusc imediat după instalare/versiuni.txt (schimbat de versiunea nouă), apoi
    lansatorul real, fără internet: revine la versiunea veche ÎNAINTEA lui pregatire.sh, afișează versiunea veche, cod 0, mesajul
    revenirii o dată, arborele identic cu cel dinainte și în .actualizare doar lacat. Înainte de P1: cod 1, pregătire picată."""
    root = tmp_path / "p"
    root.mkdir()
    files = install_versions(root, copy_program(root), UV_VERSION=E2E_UV_VERSION, PYTHON_VERSION=TEST_PYTHON)
    tools = _ready_environment(root)
    shown = f"{PROGRAM_NAME} {VERSION}"
    calibration = _run_sh(root, name, tools, ("--versiune",))
    calibration_output = (calibration.stdout + calibration.stderr).decode("utf-8", errors="replace")
    assert calibration.returncode == 0 and shown in calibration_output, f"mediul pregătit nu merge fără internet:\n{calibration_output}"
    before = fingerprint(root, skip=CHANGING_DIRS)
    archive = tmp_path / "lansare.zip"
    version, new_versions = release_with_versions(archive, files, **NEW_RELEASE_CHANGES[change])
    interrupt_update(root, archive, version, new_versions, tmp_path)
    result = _run_sh(root, name, tools, ("--versiune",))
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode == 0, f"cod {result.returncode}:\n{output}"
    assert shown in output and f"{PROGRAM_NAME} {version}" not in output, output
    assert output.count(MESSAGE_RECOVERED.format(to_version=version, from_version=VERSION)) == 1, output
    assert "Pregătirea nu s-a terminat" not in output and "EROARE" not in output, output
    assert fingerprint(root, skip=CHANGING_DIRS) == before, "după recuperare, programul trebuie să fie exact cel dinainte de actualizare"
    assert work_dir_leftovers(root) == [], "în .actualizare trebuie să rămână doar lacat"


# ---------- D15: .venv refăcut când Python-ul din el are altă versiune ----------

def test_prepare_checks_the_python_version_of_the_venv():
    """pregatire.sh verifică .venv cu PYTHON_VERSION dat ca argument (nu lipit în codul Python) și compară major.minor."""
    text = _text(PREPARE)
    assert "sys.version_info[:2]" in text and "sys.argv[1]" in text, "verificarea trebuie să compare major.minor cu argumentul"
    assert 'if [ ! -x "$PY" ] || ! "$PY" -c "$VERIFICARE_VENV" "$PYTHON_VERSION" >/dev/null 2>&1; then' in text


FAKE_UV = """#!/bin/sh
DIR=$(cd "$(dirname "$0")/../.." && pwd)
if [ "$1" = "--version" ]; then echo "uv {version}"; exit 0; fi
echo "$*" >> "$DIR/uv-apeluri.txt"
"""
# Un `uname` fals de Linux x86_64, primul în PATH-ul rulării: pe Windows, sh din Git spune MINGW64 și pregatire.sh (corect)
# refuză alt sistem decât macOS/Linux; pe macOS și Linux face ținta lui uv aceeași peste tot (deci și amprenta din test).
FAKE_UNAME = '#!/bin/sh\ncase "$1" in -m) echo x86_64 ;; *) echo Linux ;; esac\n'
FAKE_UV_TARGET = "x86_64-unknown-linux-gnu"  # ținta lui uv pentru FAKE_UNAME, ca în pregatire.sh
FAKE_UV_FINGERPRINT_KEY = "SHA256_LINUX_X64"
# curl fals: notează adresa (ultimul argument) în descarcari.txt și copiază în fișierul de după -o răspunsul pregătit de test
# pentru acea adresă (raspunsuri/<adresa fără https:// și cu / înlocuit de _>); fără răspuns iese cu 22, ca `curl -f` la 404.
FAKE_CURL = """#!/bin/sh
AICI=$(cd "$(dirname "$0")" && pwd)
IESIRE=
while [ "$#" -gt 1 ]; do
  if [ "$1" = "-o" ]; then IESIRE=$2; shift; fi
  shift
done
echo "$1" >> "$AICI/descarcari.txt"
RASPUNS="$AICI/raspunsuri/$(echo "$1" | sed 's#^https://##; s#/#_#g')"
if [ ! -f "$RASPUNS" ]; then echo "curl fals: (22) nicio arhivă pentru $1" >&2; exit 22; fi
cp "$RASPUNS" "$IESIRE"
"""


def _response_name(url: str) -> str:
    """Numele fișierului din unelte/raspunsuri/ pe care FAKE_CURL îl servește pentru `url`."""
    return url.removeprefix("https://").replace("/", "_")


def _prepare_folder(folder: Path, pinned_python: str, uv_version: str | None = None, fingerprint: str | None = None) -> Path:
    """Pregătește în `folder` un program cu pregatire.sh real și unelte false (uv notează apelurile, Python e cel al testelor).

    PYTHON_VERSION devine `pinned_python`; browserul e marcat gata, iar cerințele ca instalate. Fără `uv_version`, uv fals e deja
    instalat în versiunea din versiuni.txt; cu `uv_version`, versiuni.txt primește UV_VERSION = `uv_version` și amprenta Linux x64
    = `fingerprint`, iar uv lipsește (pregatire.sh îl descarcă prin curl-ul fals). Întoarce folderul cu unelte false (uname, curl)
    de pus primul în PATH.
    """
    (folder / "instalare").mkdir()
    shutil.copy(PROJECT_ROOT / PREPARE, folder / PREPARE)
    shutil.copy(PROJECT_ROOT / ENVIRONMENT, folder / ENVIRONMENT)
    versions = (PROJECT_ROOT / "instalare" / "versiuni.txt").read_text(encoding="utf-8")
    versions = re.sub(r"(?m)^PYTHON_VERSION=.*$", f"PYTHON_VERSION={pinned_python}", versions)
    if uv_version is None:
        installed = re.search(r"(?m)^UV_VERSION=(.*)$", versions).group(1).strip()
        _write_script(folder / ".uv" / "bin" / "uv", FAKE_UV.format(version=installed))
    else:
        versions = re.sub(r"(?m)^UV_VERSION=.*$", f"UV_VERSION={uv_version}", versions)
        versions = re.sub(rf"(?m)^{FAKE_UV_FINGERPRINT_KEY}=.*$", f"{FAKE_UV_FINGERPRINT_KEY}={fingerprint}", versions)
    (folder / "instalare" / "versiuni.txt").write_bytes(versions.encode("utf-8"))
    _write_script(folder / ".venv" / "bin" / "python", f"#!/bin/sh\nexec '{Path(sys.executable).as_posix()}' \"$@\"\n")
    (folder / ".uv" / "browser.ok").parent.mkdir(parents=True, exist_ok=True)
    (folder / ".uv" / "browser.ok").write_bytes(b"")
    requirements = b"pachet==1.0\n"
    (folder / "requirements.txt").write_bytes(requirements)
    (folder / ".venv" / "cerinte.sha256").write_bytes(hashlib.sha256(requirements).hexdigest().encode("ascii") + b"\n")
    _write_script(folder / "unelte" / "uname", FAKE_UNAME)
    _write_script(folder / "unelte" / "curl", FAKE_CURL)
    return folder / "unelte"


@needs_sh
@pytest.mark.parametrize("same_version", (True, False), ids=("aceeasi-versiune", "alta-versiune"))
def test_prepare_rebuilds_the_venv_only_when_its_python_has_another_version(tmp_path, same_version):
    """D15 la execuție: cu Python-ul fixat, pregatire.sh păstrează .venv; cu altă versiune major.minor îl reface (uv venv --clear) și reinstalează pachetele."""
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    pinned = current if same_version else f"{sys.version_info.major}.{sys.version_info.minor - 1}"
    tools = _prepare_folder(tmp_path, pinned)
    result = _run_sh(tmp_path, PREPARE, tools)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode == 0, output
    log = tmp_path / "uv-apeluri.txt"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    rebuilt = [call for call in calls if call.startswith(f"venv --quiet --clear --python {pinned} ")]
    if same_version:
        assert calls == [], f"cu Python {current} fixat, .venv trebuia păstrat: {calls}\n{output}"
    else:
        assert rebuilt and any(call.startswith("pip install ") for call in calls), (
            f"Python {current} în .venv, fixat {pinned}: .venv trebuia refăcut și pachetele reinstalate: {calls}\n{output}")


# ---------- N12: arhiva uv păstrată, cu versiunea în nume ----------

# Versiunea lui uv din aceste teste e inventată (numele arhivei vine din versiuni.txt); OLDER_UV_VERSION e „cea de dinainte”, ca
# la o arhivă rămasă după o actualizare a programului care a schimbat UV_VERSION.
INVENTED_UV_VERSION = "9.8.7"
OLDER_UV_VERSION = "9.8.6"
# Ce e deja în .uv/descarcari (tipul numelui → ce arhivă), ce servește curl-ul fals, câte descărcări trebuie să fie și dacă uv
# trebuie să treacă de amprentă. Tipul numelui: "versiune" = cu UV_VERSION, "veche" = cu OLDER_UV_VERSION, "fara-versiune" =
# numele vechi, fără versiune. Aceleași cazuri ca în tests/test_bat_files.py (UV_DOWNLOAD_CASES).
UV_DOWNLOAD_CASES = {
    "ramasa-stricata": ({"versiune": "alta"}, "buna", 1, True),
    "ramase-de-la-alta-versiune": ({"veche": "alta", "fara-versiune": "alta"}, "buna", 1, True),
    "deja-buna": ({"versiune": "buna"}, "buna", 0, True),
    "descarcata-stricata": ({}, "alta", 1, False),
    "ramasa-si-descarcata-stricate": ({"versiune": "alta"}, "alta", 1, False),
    "ramasa-veche-si-descarcata-stricata": ({"veche": "alta"}, "alta", 1, False),
}
# P9 (decis 6 oct. 2026): după o dezarhivare reușită nu rămâne nicio arhivă uv-* în .uv/descarcari (nici cea tocmai folosită),
# iar un fișier care nu e arhivă uv rămâne; fără dezarhivare reușită, arhivele de la alte versiuni rămân neatinse.
UV_ARCHIVE_PREFIX = "uv-"
UNRELATED_DOWNLOAD = "altceva.txt"


def _uv_archives(folder: Path) -> list[str]:
    """Numele arhivelor uv-* rămase în `folder` (.uv/descarcari), sortate."""
    return sorted(path.name for path in folder.iterdir() if path.name.startswith(UV_ARCHIVE_PREFIX))


def _uv_tarball(uv_script: str) -> bytes:
    """O arhivă ca cea oficială pentru Linux x64: uv-<țintă>/uv (scriptul dat, executabil), comprimată gzip."""
    data = uv_script.encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"uv-{FAKE_UV_TARGET}/uv")
        member.size, member.mode = len(data), 0o755
        archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


@needs_sh
@pytest.mark.parametrize("case", sorted(UV_DOWNLOAD_CASES))
def test_prepare_keeps_uv_under_its_version_and_downloads_a_bad_leftover_only_once(tmp_path, case):
    """N12 la execuție: arhiva păstrată are versiunea în nume, deci cele rămase de la altă versiune nu contează; una rămasă cu
    altă amprentă se șterge și se descarcă o singură dată din nou; una deja bună nu se descarcă; o arhivă proaspăt descărcată
    cu altă amprentă se șterge și oprește pregătirea, fără a doua descărcare.
    P9: după o dezarhivare reușită se șterg toate arhivele uv-* (și cea folosită), iar altceva din .uv/descarcari rămâne;
    fără dezarhivare reușită, arhivele de la alte versiuni rămân."""
    present, served, downloads_expected, accepted = UV_DOWNLOAD_CASES[case]
    good_uv = FAKE_UV.format(version=INVENTED_UV_VERSION)
    archives = {"buna": _uv_tarball(good_uv), "alta": _uv_tarball(FAKE_UV.format(version=OLDER_UV_VERSION))}
    names = {kind: f"uv-{version}{FAKE_UV_TARGET}.tar.gz" for kind, version in
             (("versiune", f"{INVENTED_UV_VERSION}-"), ("veche", f"{OLDER_UV_VERSION}-"), ("fara-versiune", ""))}
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    tools = _prepare_folder(tmp_path, current, INVENTED_UV_VERSION, hashlib.sha256(archives["buna"]).hexdigest())
    downloads = tmp_path / ".uv" / "descarcari"
    downloads.mkdir(parents=True)
    for kind, archive in present.items():
        (downloads / names[kind]).write_bytes(archives[archive])
    (downloads / UNRELATED_DOWNLOAD).write_bytes(b"nu e o arhiva uv\n")
    url = f"https://github.com/astral-sh/uv/releases/download/{INVENTED_UV_VERSION}/uv-{FAKE_UV_TARGET}.tar.gz"
    (tools / "raspunsuri").mkdir()
    (tools / "raspunsuri" / _response_name(url)).write_bytes(archives[served])
    result = _run_sh(tmp_path, PREPARE, tools)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    log = tools / "descarcari.txt"
    made = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    uv = tmp_path / ".uv" / "bin" / "uv"
    assert made == [url] * downloads_expected, f"descărcări: {made}, așteptat {downloads_expected}:\n{output}"
    assert (downloads / UNRELATED_DOWNLOAD).is_file(), "curățenia arhivelor uv nu are voie să atingă alte fișiere din .uv/descarcari"
    if accepted:
        assert result.returncode == 0 and "amprenta SHA-256" not in output, output
        assert uv.read_bytes() == good_uv.encode("utf-8"), "în .uv/bin trebuie să ajungă uv din arhiva bună"
        assert _uv_archives(downloads) == [], "după o dezarhivare reușită nu rămâne nicio arhivă uv-* (P9), nici cea tocmai folosită"
    else:
        assert result.returncode == 1 and "amprenta SHA-256" in output and "NU o folosesc" in output, output
        assert not uv.exists(), "arhiva cu altă amprentă nu se dezarhivează"
        left = sorted(names[kind] for kind in present if kind != "versiune")
        assert _uv_archives(downloads) == left, "arhiva cu altă amprentă se șterge; fără dezarhivare reușită, celelalte rămân (P9)"
