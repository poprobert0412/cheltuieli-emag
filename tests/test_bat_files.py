"""Teste pentru fișierele .bat din rădăcina proiectului (lansatoarele pentru utilizatori neprogramatori).

Primește: toate *.bat din rădăcină. Verifică static (din octeți): CRLF, fără BOM, `@echo off`, `chcp 65001` înainte de
orice diacritică, `pause` înainte de `exit /b` (în instaleaza.bat `pause` e condiționat doar de argumentul --fara-pauza),
nicio comandă care șterge, descarcă sau scrie în afara folderului.
Verifică la execuție (doar Windows, doar în folderul temporar al lui pytest): mesajele prietenoase când lipsește `.venv`,
Python, fișierele programului sau când calea folderului e prea lungă pentru Windows (limita din instaleaza.bat).
NU instalează nimic, nu cere internet, nu atinge proiectul real.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ruleaza
from tests.garda_support import PROJECT_ROOT

BAT_FILES = sorted(PROJECT_ROOT.glob("*.bat"))
# Numele fixe din brief: documentația spune utilizatorului să dea clic pe ele, deci nu pot lipsi sau fi redenumite.
REQUIRED_BAT_NAMES = ("instaleaza.bat", "login.bat", "ruleaza.bat", "demo.bat", "deschide_interfata.bat", "sterge_sesiunea.bat", "porneste.bat")
# Lansatoarele care pornesc Python din .venv: au reguli în plus (cd, pause, mediu). deschide_interfata.bat doar
# deschide un fișier local, deci nu intră aici (apare în testele generale).
PYTHON_LAUNCHERS = ("login.bat", "ruleaza.bat", "demo.bat", "sterge_sesiunea.bat", "porneste.bat")
# Opțiunea din ruleaza.py pe care o cheamă fiecare lansator: dacă una nu mai există, utilizatorul ar primi o eroare argparse.
LAUNCHER_OPTIONS = {
    "login.bat": "--doar-login", "ruleaza.bat": "--deschide", "demo.bat": "--demo", "sterge_sesiunea.bat": "--sterge-sesiunea",
    "porneste.bat": "--aplicatie",
}
# Un `pause` poate fi condiționat DOAR de variabila pusă de argumentul --fara-pauza al lui instaleaza.bat (o cheamă porneste.bat, care nu așteaptă o tastă).
PAUSE_LINE = re.compile(r"(?:if not defined NO_PAUSE )?pause", re.IGNORECASE)
# Câte rânduri înapoi căutăm `pause` înainte de un `exit /b`: blocul de eroare are `echo.`, `pause`, `exit /b` la rând.
PAUSE_LOOKBACK_LINES = 3
RUN_TIMEOUT_SECONDS = 60  # un .bat care așteaptă la nesfârșit o tastă ar bloca CI-ul; stdin e oricum închis
# Cea mai lungă cale completă pe care Windows o încarcă fără setări speciale: MAX_PATH = 260, din care unul e terminatorul.
WINDOWS_MAX_PATH_CHARS = 259
# Unde pune instaleaza.bat pachetele, față de rădăcina proiectului: începutul căii oricărui fișier instalat.
VENV_SITE_PACKAGES_PREFIX = "\\.venv\\Lib\\site-packages\\"
# La testul de execuție, calea folderului trece de limita din instaleaza.bat cu atâtea caractere (peste, dar sub MAX_PATH).
PATH_LIMIT_EXCESS_CHARS = 10
# Câte caractere sub MAX_PATH păstrăm la folderul de lucru al testului: cmd.exe nu poate porni într-un folder lipit de limită.
CWD_HEADROOM_CHARS = 10

# Comenzi pe care un lansator dat utilizatorilor nu are voie să le cheme: șterg, descarcă, schimbă sistemul sau
# pornesc alte programe. Ștergerea sesiunii o face Python-ul programului, cu confirmare, nu .bat-ul.
FORBIDDEN_COMMANDS = frozenset({
    "del", "erase", "rd", "rmdir", "format", "curl", "wget", "bitsadmin", "powershell", "pwsh", "certutil", "mshta",
    "wscript", "cscript", "regsvr32", "reg", "regedit", "setx", "schtasks", "netsh", "mklink", "robocopy", "xcopy",
    "copy", "move", "ren", "rename", "md", "mkdir", "taskkill", "shutdown", "diskpart", "cipher", "takeown", "icacls",
    "runas", "cmd", "sc", "net", "ftp", "tftp", "telnet", "ssh", "scp", "wmic", "msiexec", "bcdedit", "attrib", "forfiles",
})
# Locuri din afara folderului proiectului; într-un .bat apar doar ca text în `echo`, niciodată într-o comandă.
OUTSIDE_PATH_PATTERNS = (
    (re.compile(r"(?i)%(?:USERPROFILE|APPDATA|LOCALAPPDATA|TEMP|TMP|HOMEPATH|HOMEDRIVE|PROGRAMDATA|ALLUSERSPROFILE|PUBLIC|SYSTEMROOT|WINDIR|PROGRAMFILES)"), "variabilă de mediu care duce în afara proiectului"),
    (re.compile(r"(?i)(?<![\w%~])[a-z]:[\\/]"), "cale absolută de unitate (C:\\...)"),
    (re.compile(r"\\\\[^\\\s]"), "cale de rețea (UNC)"),
    (re.compile(r"\.\.[\\/]"), "ieșire din folder cu ..\\"),
)
URL_PATTERN = re.compile(r"(?i)\b(?:https?|ftp)://")
# Un `if` din batch: condiția pe care o sărim ca să ajungem la comanda de după ea.
IF_CONDITION = re.compile(
    r'^if\s+(?:/i\s+)?(?:not\s+)?(?:exist\s+(?:"[^"]*"|\S+)|errorlevel\s+\d+|defined\s+\S+'
    r'|(?:"[^"]*"|[^\s=]+)\s*==\s*(?:"[^"]*"|\S+))\s*', re.IGNORECASE)
FOR_PREFIX = re.compile(r"^for\s+.*?\s+do\s+", re.IGNORECASE)
MOJIBAKE = re.compile("[ÄÃÅÈ][\u0080-\u00bf™‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜š›œžŸ]")  # UTF-8 citit greșit ca Windows-1252


def _statements(line: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Împarte o linie de batch în comenzi și redirectări, respectând ghilimelele și escape-ul `^`.

    Întoarce (segmente separate de & sau |, [(operator, țintă)]). `2>&1` e dublare de ieșire, nu scriere într-un fișier.
    """
    segments, current, redirects = [], [], []
    quoted, i = False, 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            quoted = not quoted
            current.append(ch)
        elif quoted:
            current.append(ch)
        elif ch == "^" and i + 1 < len(line):
            current.append(line[i:i + 2])  # caracter scăpat: text, nu operator
            i += 1
        elif ch in "&|":
            segments.append("".join(current))
            current = []
            while i + 1 < len(line) and line[i + 1] in "&|":
                i += 1
        elif ch in "<>":
            operator = ch
            while i + 1 < len(line) and line[i + 1] == ">":
                operator += ">"
                i += 1
            rest = line[i + 1:]
            duplicate = re.match(r"&\d", rest)
            if duplicate:
                i += len(duplicate.group(0))
            else:
                target = re.match(r"\s*(\"[^\"]*\"|[^\s&|<>]+)", rest)
                redirects.append((operator, target.group(1).strip('"') if target else ""))
                i += target.end() if target else 0
        else:
            current.append(ch)
        i += 1
    segments.append("".join(current))
    return segments, redirects


def _command_of(segment: str) -> str:
    """Numele comenzii dintr-un segment: fără @ ( ), fără `if ...`, `else`, `for ... do`, `call`; în litere mici, fără extensie."""
    text = segment.strip()
    while True:
        text = text.lstrip("@() \t")
        if_match = IF_CONDITION.match(text)
        for_match = FOR_PREFIX.match(text)
        if if_match:
            text = text[if_match.end():]
        elif re.match(r"(?i)else\b", text):
            text = text[4:]
        elif for_match:
            text = text[for_match.end():]
        elif re.match(r"(?i)call\s", text):
            text = text[4:]
        else:
            break
    token = re.match(r'("[^"]*"|[^\s"]+)', text)
    if not token:
        return ""
    base = re.split(r"[\\/]", token.group(1).strip('"'))[-1].lower()
    builtin = re.match(r"[a-z]+", base)  # `echo.` și `echo:` sunt tot `echo`
    name = builtin.group(0) if builtin else base
    return name if name in {"echo", "rem"} else re.sub(r"\.(exe|bat|cmd|com)$", "", base)


def _code_lines(text: str) -> list[tuple[int, str]]:
    """(număr de linie, linie) pentru liniile cu cod: fără goale, fără `rem` și fără `::`."""
    lines = []
    for number, line in enumerate(text.split("\r\n"), start=1):
        stripped = line.strip()
        if stripped and not re.match(r"(?i)@?rem(\s|$)", stripped) and not stripped.startswith("::"):
            lines.append((number, stripped))
    return lines


def _violations(name: str, raw: bytes, launcher: bool) -> list[str]:
    """Toate încălcările regulilor statice pentru un .bat, ca mesaje în română (listă goală = curat)."""
    problems: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        return [f"{name}: începe cu BOM UTF-8; cmd.exe citește primul rând ca «\ufeff@echo» și dă eroare. Salvează fără BOM."]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return [f"{name}: nu e UTF-8 valid ({error}); diacriticele s-ar vedea stricat în fereastra utilizatorului."]
    if raw.count(b"\n") != raw.count(b"\r\n") or raw.count(b"\r") != raw.count(b"\r\n") or not raw.endswith(b"\r\n"):
        problems.append(f"{name}: terminatorii de rând nu sunt peste tot CRLF (sau lipsește ultimul): cmd.exe se încurcă la etichete și la linii lungi când are doar LF.")
    lines = text.split("\r\n")
    if lines[0] != "@echo off":
        problems.append(f"{name}:1: primul rând trebuie să fie exact «@echo off» (acum «{lines[0]}»): altfel fiecare comandă s-ar afișa în fereastra utilizatorului.")
    chcp_line = next((n for n, line in enumerate(lines, 1) if re.match(r"(?i)chcp\s+65001\s*>nul\s*$", line.strip())), None)
    first_non_ascii = next((n for n, line in enumerate(lines, 1) if not line.isascii()), None)
    if first_non_ascii and (chcp_line is None or chcp_line > first_non_ascii):
        problems.append(f"{name}:{first_non_ascii}: are diacritice înainte de «chcp 65001 >nul» (sau fără chcp): în consolă s-ar vedea caractere stricate.")
    if MOJIBAKE.search(text):
        problems.append(f"{name}: conține secvențe de tip «Ã„» (UTF-8 citit ca Windows-1252): textul a fost salvat cu codare greșită.")
    code = _code_lines(text)
    for number, line in code:
        segments, redirects = _statements(line)
        for operator, target in redirects:
            if target.lower() != "nul" or operator not in {">", ">>"}:
                problems.append(f"{name}:{number}: redirectare «{operator}{target}»: un lansator nu are voie să scrie sau să citească fișiere; doar «>nul» e permis (altfel poate scrie în afara folderului).")
        for segment in segments:
            command = _command_of(segment)
            if command in FORBIDDEN_COMMANDS:
                problems.append(f"{name}:{number}: comandă interzisă «{command}»: un lansator dat utilizatorilor nu are voie să șteargă, să descarce sau să schimbe sistemul.")
            if command == "echo":
                continue  # un URL sau o cale în textul afișat e doar text
            if URL_PATTERN.search(segment):
                problems.append(f"{name}:{number}: adresă de internet într-o comandă (nu într-un echo): niciun .bat nu are voie să descarce sau să deschidă adrese.")
            for pattern, why in OUTSIDE_PATH_PATTERNS:
                if pattern.search(segment):
                    problems.append(f"{name}:{number}: {why} într-o comandă: programul scrie doar în folderul lui.")
    if launcher:
        problems.extend(_launcher_violations(name, lines, code))
    return problems


def _launcher_violations(name: str, lines: list[str], code: list[tuple[int, str]]) -> list[str]:
    """Regulile în plus pentru lansatoarele care pornesc Python: folder, mediu, pause la erori și la final."""
    problems = []
    text = "\r\n".join(lines)
    if 'cd /d "%~dp0"' not in text:
        problems.append(f'{name}: lipsește «cd /d "%~dp0"»: dublu-clic dintr-un folder cu spații sau de pe alt disc ar rula în alt director.')
    for variable in ("PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1"):
        if f'set "{variable}"' not in text:
            problems.append(f'{name}: lipsește «set "{variable}"»: fără el Python scrie __pycache__ lângă cod sau nu folosește UTF-8 în consolă.')
    if re.search(r"(?im)^\s*(goto|call\s+:)|^\s*:[A-Za-z_]", text):
        problems.append(f"{name}: folosește goto, call: sau o etichetă; cu diacritice UTF-8 și chcp 65001 cmd.exe poate rata eticheta, deci lansatoarele folosesc doar blocuri if/else.")
    for position, (number, line) in enumerate(code):
        if re.match(r"(?i)exit\s+/b", line):
            window = [other.strip() for _, other in code[max(0, position - PAUSE_LOOKBACK_LINES):position]]
            if not any(PAUSE_LINE.fullmatch(other) for other in window):
                problems.append(f"{name}:{number}: «{line}» fără «pause» chiar înainte: fereastra s-ar închide înainte să apuce utilizatorul să citească mesajul.")
    tail = [line.strip() for _, line in code[-2:]]
    if len(tail) < 2 or not PAUSE_LINE.fullmatch(tail[0]) or not tail[1].lower().startswith("exit /b"):
        problems.append(f"{name}: ultimele două comenzi trebuie să fie «pause» și «exit /b ...»: utilizatorul trebuie să apuce să citească rezultatul final.")
    return problems


def _is_launcher(path: Path) -> bool:
    """True pentru lansatoarele care pornesc Python (login, ruleaza, demo, sterge_sesiunea, instaleaza)."""
    return path.name in PYTHON_LAUNCHERS or path.name == "instaleaza.bat"


# ---------- reguli statice pe fișierele reale ----------

def test_every_documented_bat_file_exists():
    """Cele 7 lansatoare cu nume fix (cele din README) există în rădăcină; lipsa unuia ar lăsa utilizatorul cu un clic pe un fișier inexistent."""
    missing = [name for name in REQUIRED_BAT_NAMES if not (PROJECT_ROOT / name).is_file()]
    assert not missing, f"lipsesc din rădăcină: {', '.join(missing)}. README și INSTALARE le numesc, deci un utilizator ar da clic pe un fișier care nu există."


@pytest.mark.parametrize("path", BAT_FILES, ids=lambda p: p.name)
def test_bat_file_follows_the_static_rules(path):
    """Fiecare .bat din rădăcină respectă regulile statice: CRLF, @echo off, chcp, fără comenzi de ștergere sau descărcare, pause la final."""
    problems = _violations(path.name, path.read_bytes(), _is_launcher(path))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name, option", sorted(LAUNCHER_OPTIONS.items()))
def test_each_launcher_calls_its_option_and_the_option_exists(name, option):
    """Rândul de apel al fiecărui lansator pornește Python din .venv cu opțiunea lui, iar ruleaza.py cunoaște opțiunea (altfel utilizatorul vede o eroare argparse)."""
    text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
    call = next((line for line in text.splitlines() if line.lstrip().lower().startswith(('".venv', "python", "py ")) and "ruleaza.py" in line), "")
    assert option in call, f"{name} trebuie să cheme «ruleaza.py {option}», dar rândul de apel e «{call.strip()}»"
    assert r'".venv\Scripts\python.exe"' in call, f"{name}: Python-ul trebuie luat din .venv, nu din PATH (altfel lipsesc pachetele instalate de instaleaza.bat)"
    try:
        ruleaza._parse_args([option])
    except SystemExit:
        pytest.fail(f"{name} cheamă «ruleaza.py {option}», dar ruleaza.py nu cunoaște opțiunea: utilizatorul ar primi o eroare argparse.")


def test_ruleaza_bat_forwards_the_users_arguments():
    """ruleaza.bat pasează «%*» către ruleaza.py, ca opțiunile utilizatorului (ex. --prag 1000) să ajungă la program."""
    text = (PROJECT_ROOT / "ruleaza.bat").read_text(encoding="utf-8")
    assert re.search(r"ruleaza\.py --deschide %\*\r?$", text, re.M), "ruleaza.bat trebuie să paseze «%*» mai departe (ex. ruleaza.bat --prag 1000)"


def test_instaleaza_installs_only_runtime_requirements_without_cache_or_compilation():
    """instaleaza.bat instalează doar requirements.txt, fără cache și doar din pachete gata făcute (nu rulează cod de instalare de pe internet)."""
    text = (PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8")
    install = next((line for line in text.splitlines() if "pip install" in line and not line.lstrip().lower().startswith("rem")), "")
    assert "-r requirements.txt" in install and "requirements-dev" not in install, "instaleaza.bat instalează doar requirements.txt (pytest nu e pentru utilizatori)"
    assert "--no-cache-dir" in install, "fără --no-cache-dir pip scrie memoria lui în AppData, în afara folderului programului"
    assert "--only-binary=:all:" in install, "fără --only-binary pip poate rula cod de instalare (setup.py) de pe internet pe calculatorul utilizatorului"


def test_instaleaza_skips_every_pause_only_through_the_documented_flag():
    """În instaleaza.bat orice `pause` e condiționat de NO_PAUSE, care pornește gol și se pune pe 1 doar din argumentul --fara-pauza (nu din mediul utilizatorului)."""
    text = (PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8")
    assert 'set "NO_PAUSE="' in text, "NO_PAUSE trebuie golit la început: altfel o variabilă din mediul utilizatorului ar sări peste toate pauzele"
    assert text.count('set "NO_PAUSE=1"') == 1 and 'if /i "%~1"=="--fara-pauza" set "NO_PAUSE=1"' in text, "NO_PAUSE se pune pe 1 doar din argumentul --fara-pauza"
    pauses = [line.strip() for line in text.splitlines() if re.fullmatch(r"\s*(?:if not defined NO_PAUSE )?pause\s*", line, re.IGNORECASE)]
    assert len(pauses) >= 6 and all(line == "if not defined NO_PAUSE pause" for line in pauses), f"un pause scapă de condiție: {pauses}"
    assert "if not defined NO_PAUSE (" in text and text.index("echo Ce urmează:") > text.index("if not defined NO_PAUSE ("), "mesajul «Ce urmează» trebuie să dispară la apelul din porneste.bat"


def test_porneste_installs_with_the_flag_and_stops_when_the_installer_fails():
    """porneste.bat cheamă `call instaleaza.bat --fara-pauza` și, dacă instalarea eșuează, se oprește cu mesaj și pause, fără să pornească aplicația."""
    text = (PROJECT_ROOT / "porneste.bat").read_text(encoding="utf-8")
    call = 'call ".\\instaleaza.bat" --fara-pauza'  # cu cale explicită: unde Windows nu mai caută în folderul curent, «call instaleaza.bat» nu ar fi găsit
    assert re.search(re.escape(call) + r'\r?\n\s*if errorlevel 1 set "INSTALL_FAILED=1"', text), "porneste.bat trebuie să verifice rezultatul instalării chiar după apel"
    install_failure = text.split(call, 1)[1].split("Pornesc aplicația", 1)[0]
    assert "pause" in install_failure and "exit /b 1" in install_failure, "la eșecul instalării trebuie pause și exit /b 1 înainte de pornirea aplicației"


def _max_folder_path() -> int:
    """Limita de lungime a căii folderului, citită din `set "MAX_FOLDER_PATH=..."` din instaleaza.bat (o singură sursă pentru .bat și test)."""
    text = (PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8")
    match = re.search(r'(?m)^set "MAX_FOLDER_PATH=(\d+)"', text)
    assert match, "instaleaza.bat nu definește MAX_FOLDER_PATH: fără limită, într-un folder cu cale lungă import-ul din .venv pică cu «DLL load failed … filename too long»"
    assert re.search(r"-c .*os\.getcwd\(\).*%MAX_FOLDER_PATH%", text), "instaleaza.bat definește MAX_FOLDER_PATH, dar nu o compară cu lungimea folderului curent"
    return int(match.group(1))


def _longest_binary_in_runtime_requirements() -> tuple[int, str]:
    """(lungimea căii, fișierul) pentru cel mai lung .pyd/.dll de încărcat din pachetele din requirements.txt, față de rădăcina proiectului.

    Citește fișierele din instalarea curentă (importlib.metadata); omite folderele `tests`, pe care programul nu le încarcă.
    Întoarce (0, "") dacă pachetele nu sunt instalate sau n-au binare (alt sistem de operare).
    """
    from importlib import metadata

    longest = (0, "")
    for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        found = re.match(r"^([A-Za-z0-9_.-]+)==", line)
        if not found:
            continue
        try:
            files = metadata.distribution(found.group(1)).files or []
        except metadata.PackageNotFoundError:
            continue
        for file in files:
            if file.suffix.lower() in {".pyd", ".dll"} and "tests" not in file.parts:
                length = len(VENV_SITE_PACKAGES_PREFIX) + len(str(file).replace("/", "\\"))
                longest = max(longest, (length, str(file)))
    return longest


def test_instaleaza_path_limit_leaves_room_for_the_longest_installed_binary():
    """Limita de cale din instaleaza.bat + cel mai lung .pyd/.dll din requirements.txt încape sub MAX_PATH (altfel Windows nu-l încarcă, deși pip l-a scris)."""
    limit = _max_folder_path()
    longest, name = _longest_binary_in_runtime_requirements()
    if not longest:
        pytest.skip("pachetele din requirements.txt nu sunt instalate aici sau n-au binare Windows: nu pot măsura")
    assert limit + longest <= WINDOWS_MAX_PATH_CHARS, (
        f"MAX_FOLDER_PATH={limit} din instaleaza.bat + {longest} caractere pentru «{name}» = {limit + longest} > {WINDOWS_MAX_PATH_CHARS}: "
        "într-un folder cu calea la limită, Windows n-ar putea încărca acel fișier, deci programul n-ar porni. Scade MAX_FOLDER_PATH (și comentariul lui).")


# ---------- cele mai greșite .bat posibile: regulile statice trebuie să le prindă ----------

def _crlf(*lines: str) -> bytes:
    """Un .bat sintetic corect (CRLF, fără BOM) din rândurile date."""
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


@pytest.mark.parametrize("line, expected", [
    ("del /q fisier.txt", "comandă interzisă «del»"),
    ('if exist ".profil_browser" rmdir /s /q ".profil_browser"', "comandă interzisă «rmdir»"),
    ("echo ok & powershell -enc AAAA", "comandă interzisă «powershell»"),
    ("curl https://exemplu.invalid/x -o y", "comandă interzisă «curl»"),
    ("reg add HKCU\\Software\\X /f", "comandă interzisă «reg»"),
    ("setx ceva 1", "comandă interzisă «setx»"),
    ('".venv\\Scripts\\python.exe" ruleaza.py > rezultat.txt', "redirectare"),
    ("echo salvat > C:\\Users\\x\\fisier.txt", "redirectare"),
    ('copy "%~dp0x" "%APPDATA%\\y"', "comandă interzisă «copy»"),
    ('cd /d "%USERPROFILE%"', "variabilă de mediu"),
    ('".venv\\Scripts\\python.exe" ..\\alt\\script.py', "ieșire din folder"),
    ("start https://exemplu.invalid", "adresă de internet"),
])
def test_static_rules_catch_dangerous_commands(line, expected):
    """Capcană: fiecare comandă periculoasă (ștergere, descărcare, Registry, redirectare spre alt loc, adresă în comandă) trebuie prinsă de regulile statice."""
    raw = _crlf("@echo off", line)
    assert any(expected in problem for problem in _violations("sintetic.bat", raw, launcher=False)), line


def test_static_rules_allow_text_with_urls_and_python_code_with_special_characters():
    """Fals pozitiv: o adresă în `echo` și o comandă Python cu caractere speciale (>=, ^, paranteze) nu sunt încălcări."""
    raw = _crlf(
        "@echo off",
        "echo Deschide https://www.python.org/downloads/ si descarca Python ^(ultima versiune^)",
        'py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>&1',
        "if not errorlevel 1 set \"PYTHON_CMD=py -3\"",
    )
    assert _violations("sintetic.bat", raw, launcher=False) == []


@pytest.mark.parametrize("raw, expected", [
    (b"\xef\xbb\xbf@echo off\r\n", "BOM"),
    (b"@echo off\necho x\n", "CRLF"),
    (b"@echo off\r\necho x\r", "CRLF"),
    (b"echo off\r\n", "primul rând"),
    ("@echo off\r\necho Dacă\r\n".encode("utf-8"), "chcp 65001"),
    ("@echo off\r\nchcp 65001 >nul\r\necho Ã„ stricat\r\n".encode("utf-8"), "UTF-8 citit ca Windows-1252"),
    (b"@echo off\r\necho \xe9\r\n", "UTF-8 valid"),
])
def test_static_rules_catch_encoding_and_line_ending_mistakes(raw, expected):
    """Capcană: BOM, LF în loc de CRLF, lipsa @echo off, diacritice înainte de chcp, mojibake și octeți non-UTF-8 trebuie prinse."""
    assert any(expected in problem for problem in _violations("sintetic.bat", raw, launcher=False)), raw


def test_launcher_rules_catch_missing_pause_missing_cd_and_labels():
    """Capcană: un lansator fără cd /d, fără PYTHONDONTWRITEBYTECODE, cu goto sau fără pause înainte de exit trebuie prins."""
    raw = _crlf("@echo off", "chcp 65001 >nul", "echo salut", "goto :sus", ":sus", "exit /b 1")
    problems = "\n".join(_violations("sintetic.bat", raw, launcher=True))
    for expected in ('cd /d "%~dp0"', "PYTHONDONTWRITEBYTECODE", "goto", "fără «pause»", "ultimele două comenzi"):
        assert expected in problems, f"nu a fost prins: {expected}\n{problems}"


# ---------- execuție reală, doar în folderul temporar al lui pytest ----------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="lansatoarele .bat rulează doar pe Windows")


def _run_bat(folder: Path, name: str, path_env: str | None = None) -> subprocess.CompletedProcess:
    """Rulează `folder\\name` prin cmd.exe, cu stdin închis (ca la un clic) și fără fereastră proprie.

    CREATE_NO_WINDOW: `chcp 65001` din .bat schimbă consola procesului, nu consola în care rulează pytest.
    """
    env = dict(os.environ)
    if path_env is not None:
        env["PATH"] = path_env
    return subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", f".\\{name}"],
        cwd=folder, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=RUN_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _copy_bats(folder: Path, *names: str) -> None:
    """Copiază doar .bat-urile cerute în `folder` (fără restul programului)."""
    for name in names:
        shutil.copy(PROJECT_ROOT / name, folder / name)


def _listing(folder: Path) -> list[str]:
    """Toate căile din `folder`, relative și sortate: pentru a dovedi că rularea n-a creat nimic."""
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def _output(result: subprocess.CompletedProcess) -> str:
    """Ieșirea unui .bat decodată UTF-8 (după `chcp 65001`)."""
    return (result.stdout + result.stderr).decode("utf-8", errors="replace")


@windows_only
@pytest.mark.parametrize("name", PYTHON_LAUNCHERS)
def test_launchers_without_venv_explain_what_to_do_and_create_nothing(tmp_path, name):
    """La execuție: fără .venv fiecare lansator spune să rulezi instaleaza.bat, iese cu cod 1 și nu creează nimic în folder."""
    _copy_bats(tmp_path, name)
    (tmp_path / "ruleaza.py").write_text("raise SystemExit('nu trebuie rulat')\n", encoding="utf-8")
    before = _listing(tmp_path)
    result = _run_bat(tmp_path, name)
    output = _output(result)
    assert result.returncode == 1, output
    assert "instaleaza.bat" in output and "Traceback" not in output, output
    assert _listing(tmp_path) == before, "lansatorul fără .venv nu are voie să creeze fișiere sau foldere"


@windows_only
@pytest.mark.parametrize("name", PYTHON_LAUNCHERS + ("instaleaza.bat",))
def test_launchers_run_from_inside_a_zip_say_to_extract_first(tmp_path, name):
    """La execuție: un .bat rulat din ZIP (fără restul programului) spune să extragi tot și nu creează nimic."""
    _copy_bats(tmp_path, name)  # ca după un dublu-clic pe .bat din ZIP: doar fișierul lui, fără restul programului
    result = _run_bat(tmp_path, name)
    output = _output(result)
    assert result.returncode == 1, output
    assert "Extract All" in output and "Extrage tot" in output, output
    assert _listing(tmp_path) == [name]


@windows_only
def test_instaleaza_without_python_shows_the_download_steps_and_creates_nothing(tmp_path):
    """La execuție: pe un calculator fără Python, instaleaza.bat arată pașii de descărcare de pe python.org și nu creează nimic."""
    _copy_bats(tmp_path, "instaleaza.bat")
    (tmp_path / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    empty = tmp_path / "gol"
    empty.mkdir()
    path_env = f"{os.environ.get('SystemRoot', 'C:/Windows')}\\System32;{empty}"
    if shutil.which("py", path=path_env) or shutil.which("python", path=path_env):
        pytest.skip("Python se găsește chiar și cu un PATH minim: nu pot simula calculatorul fără Python")
    before = _listing(tmp_path)
    result = _run_bat(tmp_path, "instaleaza.bat", path_env)
    output = _output(result)
    assert result.returncode == 1, output
    assert "python.org" in output and "Add python.exe to PATH" in output and "Traceback" not in output, output
    assert _listing(tmp_path) == before


@windows_only
def test_instaleaza_refuses_a_python_that_answers_with_an_error_and_creates_no_venv(tmp_path):
    """Un `py` și un `python` care EXISTĂ dar răspund cu cod de eroare (un Python prea vechi răspunde cu 3 la aceeași probă).

    Executabilele false sunt copii ale lui where.exe din Windows, redenumite py.exe și python.exe: primesc `-c ...`,
    nu le înțeleg și ies cu eroare. Un .bat fals n-ar merge: un .bat care cheamă alt .bat fără `call` nu mai revine.
    """
    system32 = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
    stand_in = system32 / "where.exe"
    if not stand_in.is_file():
        pytest.skip("where.exe nu există: nu pot simula un Python care răspunde cu eroare")
    _copy_bats(tmp_path, "instaleaza.bat")
    (tmp_path / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    fakes = tmp_path / "false"
    fakes.mkdir()
    for fake in ("py.exe", "python.exe"):
        shutil.copy(stand_in, fakes / fake)
    result = _run_bat(tmp_path, "instaleaza.bat", f"{fakes};{system32}")
    output = _output(result)
    assert result.returncode == 1, output
    assert "Python 3.10 sau mai nou" in output and "python.org" in output, output
    assert not (tmp_path / ".venv").exists()


@windows_only
def test_instaleaza_refuses_a_folder_whose_path_is_too_long_and_creates_no_venv(tmp_path):
    """La execuție: într-un folder cu calea peste limita din instaleaza.bat, scriptul spune să muți folderul și nu creează .venv.

    Fără verificarea asta, pip instalează fără erori, dar la prima rulare Python dă «DLL load failed … filename too long».
    """
    if not (shutil.which("py") or shutil.which("python")):
        pytest.skip("nu există Python în PATH: instaleaza.bat ar opri mai devreme, la mesajul despre Python")
    limit = _max_folder_path()
    padding = max(limit + PATH_LIMIT_EXCESS_CHARS - len(str(tmp_path)) - 1, 1)  # -1: separatorul dinaintea folderului nou
    folder = tmp_path / ("x" * padding)
    if not limit < len(str(folder)) < WINDOWS_MAX_PATH_CHARS - CWD_HEADROOM_CHARS:
        pytest.skip(f"calea de test ({len(str(folder))} caractere) nu poate fi făcută mai lungă decât limita {limit} și totuși rulabilă")
    folder.mkdir()
    _copy_bats(folder, "instaleaza.bat")
    (folder / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    before = _listing(folder)
    result = _run_bat(folder, "instaleaza.bat")
    output = _output(result)
    assert result.returncode == 1, output
    assert "prea lungă" in output and "mută folderul" in output and "Traceback" not in output, output
    assert _listing(folder) == before and not (folder / ".venv").exists(), "nu are voie să creeze .venv într-un folder cu cale prea lungă"


@windows_only
def test_instaleaza_path_probe_accepts_exactly_the_limit_and_refuses_one_more(tmp_path):
    """Proba de lungime din instaleaza.bat (aceeași comandă Python, extrasă din fișier) trece la exact MAX_FOLDER_PATH caractere și pică la unul în plus.

    Fără rețea și fără instalare: rulează doar proba, cu Python-ul testelor, în foldere cu calea de lungime exactă (greșeala clasică: un `<` în loc de `<=`).
    """
    limit = _max_folder_path()
    text = (PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8")
    found = re.search(r'-c "([^"]*%MAX_FOLDER_PATH%[^"]*)"', text)
    assert found, "nu găsesc în instaleaza.bat comanda Python care compară lungimea folderului cu %MAX_FOLDER_PATH%"
    probe = found.group(1).replace("%MAX_FOLDER_PATH%", str(limit))
    for extra, expected_code in ((0, 0), (1, 4)):
        padding = limit + extra - len(str(tmp_path)) - 1  # -1: separatorul dinaintea folderului nou
        if padding < 1:
            pytest.skip(f"folderul temporar al testului are deja {len(str(tmp_path))} caractere: nu pot construi o cale de {limit + extra}")
        folder = tmp_path / ("x" * padding)
        folder.mkdir()
        assert len(str(folder)) == limit + extra, f"testul n-a construit calea cerută: {len(str(folder))} în loc de {limit + extra}"
        done = subprocess.run([sys.executable, "-c", probe], cwd=folder, capture_output=True, timeout=RUN_TIMEOUT_SECONDS)
        assert done.returncode == expected_code, (
            f"cu o cale de {limit + extra} caractere (limita e {limit}) proba trebuia să iasă cu {expected_code}, a ieșit cu {done.returncode}: "
            f"{done.stderr.decode('utf-8', 'replace')}")


def test_porneste_has_no_exit_inside_nested_blocks():
    """În porneste.bat nicio comandă `exit /b` nu stă într-un bloc imbricat (adâncime 2+): pe unele versiuni de Windows (văzut pe build 26300) codul de ieșire se pierde și devine 0."""
    depth = 0
    for number, line in _code_lines((PROJECT_ROOT / "porneste.bat").read_text(encoding="utf-8")):
        if line.startswith(")"):
            depth -= 1
        if re.match(r"(?i)exit\s+/b", line):
            assert depth <= 1, f"porneste.bat:{number}: «{line}» e în bloc imbricat (adâncime {depth}): codul de ieșire se poate pierde; aplatizează cu «if a if b (» sau cu o variabilă"
        if line.endswith("("):
            depth += 1


def _copy_venv_python(folder: Path) -> None:
    """Pune în `folder/.venv/Scripts/python.exe` o copie a Python-ului testelor (cu pyvenv.cfg), ca un mediu .venv funcțional; sare testul dacă nu se poate."""
    if sys.prefix == sys.base_prefix or not (Path(sys.prefix) / "pyvenv.cfg").is_file():
        pytest.skip("testele nu rulează într-un mediu virtual: nu pot copia un .venv funcțional")
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    shutil.copy(sys.executable, folder / ".venv" / "Scripts" / "python.exe")
    shutil.copy(Path(sys.prefix) / "pyvenv.cfg", folder / ".venv" / "pyvenv.cfg")


def _stub_program(folder: Path) -> None:
    """Un ruleaza.py fals care doar spune ce argumente a primit (nu pornește nimic)."""
    (folder / "ruleaza.py").write_text("import sys\nprint('ARGUMENTE-PRIMITE:', ' '.join(sys.argv[1:]))\n", encoding="utf-8")


@windows_only
def test_porneste_with_an_existing_venv_goes_straight_to_the_application(tmp_path):
    """Cu .venv existent, porneste.bat nu cheamă instaleaza.bat și pornește `ruleaza.py --aplicatie`; la oprire normală iese cu 0."""
    _copy_bats(tmp_path, "porneste.bat")
    (tmp_path / "instaleaza.bat").write_bytes(b"@echo off\r\necho INSTALATORUL-A-RULAT\r\nexit /b 1\r\n")
    _stub_program(tmp_path)
    _copy_venv_python(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 0, output
    assert "ARGUMENTE-PRIMITE: --aplicatie" in output and "INSTALATORUL-A-RULAT" not in output, output
    assert "Traceback" not in output


@windows_only
def test_porneste_stops_with_exit_code_1_when_the_installer_fails_and_never_starts_the_app(tmp_path):
    """Fără .venv, porneste.bat cheamă instaleaza.bat cu --fara-pauza; dacă aceasta pică, iese cu 1 și cu mesaj, fără să pornească aplicația."""
    _copy_bats(tmp_path, "porneste.bat")
    (tmp_path / "instaleaza.bat").write_bytes(b"@echo off\r\necho INSTALATOR-ARGUMENTE: %*\r\nexit /b 1\r\n")
    _stub_program(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 1, output
    assert "INSTALATOR-ARGUMENTE: --fara-pauza" in output and "Instalarea nu s-a terminat" in output, output
    assert "ARGUMENTE-PRIMITE" not in output and not (tmp_path / ".venv").exists()


@windows_only
def test_porneste_starts_the_application_after_a_successful_install(tmp_path):
    """Fără .venv și cu o instalare reușită (instalator fals care creează .venv), porneste.bat pornește `ruleaza.py --aplicatie`."""
    if sys.prefix == sys.base_prefix:
        pytest.skip("testele nu rulează într-un mediu virtual: nu pot copia un .venv funcțional")
    _copy_bats(tmp_path, "porneste.bat")
    installer = (
        "@echo off\r\necho INSTALATOR-ARGUMENTE: %*\r\n"
        f'md ".venv\\Scripts"\r\ncopy "{sys.executable}" ".venv\\Scripts\\python.exe" >nul\r\ncopy "{Path(sys.prefix) / "pyvenv.cfg"}" ".venv\\pyvenv.cfg" >nul\r\nexit /b 0\r\n')
    (tmp_path / "instaleaza.bat").write_bytes(installer.encode("utf-8"))
    _stub_program(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 0, output
    assert "INSTALATOR-ARGUMENTE: --fara-pauza" in output and "ARGUMENTE-PRIMITE: --aplicatie" in output, output


@windows_only
def test_porneste_passes_a_nonzero_exit_code_of_the_application_through(tmp_path):
    """Dacă aplicația iese cu eroare, porneste.bat spune că s-a oprit cu o eroare și iese cu același cod (nu îl pierde)."""
    _copy_bats(tmp_path, "porneste.bat")
    (tmp_path / "ruleaza.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    _copy_venv_python(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 7 and "s-a oprit cu o eroare" in output, output


@windows_only
def test_instaleaza_with_the_flag_does_not_wait_for_a_key(tmp_path):
    """Cu --fara-pauza instaleaza.bat iese fără `pause` (nu așteaptă o tastă); fără argument textul e același, plus cererea de tastă."""
    _copy_bats(tmp_path, "instaleaza.bat")
    plain = _output(_run_bat(tmp_path, "instaleaza.bat"))
    flagged_result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", ".\\instaleaza.bat", "--fara-pauza"], cwd=tmp_path, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=RUN_TIMEOUT_SECONDS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    flagged = _output(flagged_result)
    assert flagged_result.returncode == 1, flagged
    assert "Extract All" in flagged and plain.startswith(flagged.rstrip()) and len(plain) > len(flagged.rstrip()), (
        f"cu --fara-pauza nu trebuia să apară cererea de tastă.\nfără argument:\n{plain!r}\ncu argument:\n{flagged!r}")


def test_every_launcher_is_covered_by_the_static_rules():
    """Un .bat nou în rădăcină intră automat în testele statice; dacă pornește Python, trebuie adăugat la PYTHON_LAUNCHERS."""
    unknown = [p.name for p in BAT_FILES if p.name not in REQUIRED_BAT_NAMES and p.name != "instaleaza.bat"]
    for name in unknown:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8").lower()
        assert "python" not in text, f"{name} pornește Python, dar nu e în PYTHON_LAUNCHERS din {Path(__file__).name}: adaugă-l ca să i se aplice și regulile de lansator."

