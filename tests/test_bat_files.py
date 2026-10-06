"""Teste pentru fișierele .bat (lansatoarele pentru utilizatori neprogramatori, pe Windows).

Primește: toate *.bat din rădăcină, instalare/mediu.bat și instalare/dupa_rulare.bat. Verifică static (din octeți): CRLF,
fără BOM, `@echo off`, `chcp 65001` înainte de orice diacritică, `pause` înainte de `exit /b`, nicio comandă care șterge,
descarcă sau scrie în afara folderului. Singura excepție, îngustă și motivată: instaleaza.bat descarcă uv DOAR de la adresa
oficială fixată, îl verifică cu certutil și scrie sau șterge DOAR în .uv/ și .venv/. Regula D13 (decis 5 oct. 2026): rândul
care pornește Python e ultimul din lansator și are pe el tot ce urmează, ca o actualizare care înlocuiește lansatorul cât
rulează Python să nu-l facă pe cmd să citească restul din fișierul nou.
Verifică la execuție (doar Windows, doar în folderul temporar al lui pytest, fără internet): mesajele prietenoase când
lipsește .venv sau fișierele programului, refuzul unei căi prea lungi, refacerea .venv cu alt Python, comportamentul lui
porneste.bat (pornește aplicația, pasează argumentele, păstrează codul de ieșire) și D13: lansatorul suprascris de un Python
fals cât rulează se termină curat, cu codul exact, iar la 75 porneste.bat pornește varianta nouă.
N12 (decis 6 oct. 2026), cu curl, certutil și tar reale și un github.com fals pe 127.0.0.1 (tests/fake_uv_release_server.py):
arhiva uv păstrată are versiunea în nume (una rămasă de la altă versiune nu e luată în seamă), o arhivă rămasă cu altă amprentă
se șterge și se descarcă o singură dată din nou, iar una proaspăt descărcată cu altă amprentă se șterge și oprește pregătirea;
P9: după o dezarhivare reușită nu rămâne nicio arhivă uv-*.
P1 (decis 6 oct. 2026): porneste.bat rulează recuperarea unei actualizări întrerupte ÎNAINTEA pregătirii, pe un singur rând (D13),
cu oprire la codul 1 și repornire o singură dată; static, la execuție cu programe false (ordinea, oprirea, fără buclă, lansatorul
înlocuit de recuperare) și cap-coadă: actualizare reală oprită după instalare/versiuni.txt (tests/interrupted_update_support.py),
apoi porneste.bat și instaleaza.bat reale, fără internet, cu un uv fals.
Orice .bat rulat de teste are proxy-ul lui curl spre un port mort, deci nicio rulare nu poate ieși pe internet.
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import venv
import zipfile
from pathlib import Path

import pytest

import ruleaza
from emag_spend import settings
from emag_spend.update_recovery import MESSAGE_RECOVERED
from emag_spend.version import VERSION
from tests.fake_uv_release_server import OFFLINE_ENV, FakeUvRelease, find_openssl
from tests.garda_support import PROJECT_ROOT
from tests.interrupted_update_support import copy_program, install_versions, interrupt_update, release_with_versions
from tests.update_archive_support import fingerprint, work_dir_leftovers

BAT_FILES = sorted(PROJECT_ROOT.glob("*.bat"))
ENV_BAT = PROJECT_ROOT / "instalare" / "mediu.bat"
VERSIONS_FILE = PROJECT_ROOT / "instalare" / "versiuni.txt"
# Ce urmează după Python (mesaj, pauză, cod), comun lansatorilor: îl cheamă rândul care pornește Python, pe același rând.
AFTER_RUN_BAT = PROJECT_ROOT / "instalare" / "dupa_rulare.bat"
AFTER_RUN_NAME = "instalare/dupa_rulare.bat"
# Numele fixe din documentație: utilizatorul e trimis să dea clic pe ele, deci nu pot lipsi sau fi redenumite.
REQUIRED_BAT_NAMES = ("instaleaza.bat", "login.bat", "ruleaza.bat", "demo.bat", "deschide_interfata.bat", "sterge_sesiunea.bat", "porneste.bat")
# Lansatoarele care pornesc Python din .venv: au reguli în plus (cd, mediu, pause). deschide_interfata.bat doar deschide un
# fișier local, deci nu intră aici (apare în testele generale).
PYTHON_LAUNCHERS = ("login.bat", "ruleaza.bat", "demo.bat", "sterge_sesiunea.bat", "porneste.bat")
INSTALLER = "instaleaza.bat"
# Opțiunea din ruleaza.py pe care o cheamă fiecare lansator: dacă una nu mai există, utilizatorul ar primi o eroare argparse.
LAUNCHER_OPTIONS = {
    "login.bat": "--doar-login", "ruleaza.bat": "--deschide", "demo.bat": "--demo", "sterge_sesiunea.bat": "--sterge-sesiunea",
    "porneste.bat": "--aplicatie",
}
# Un `pause` poate fi condiționat DOAR de variabila pusă de argumentul --fara-pauza al lui instaleaza.bat (o cheamă porneste.bat).
PAUSE_LINE = re.compile(r"(?:if (?:not )?defined \w+ )*pause", re.IGNORECASE)
# Câte rânduri înapoi căutăm `pause` înainte de un `exit /b`: blocul de eroare are `echo.`, `pause`, `exit /b` la rând.
PAUSE_LOOKBACK_LINES = 3
RUN_TIMEOUT_SECONDS = 60  # un .bat care așteaptă la nesfârșit o tastă ar bloca CI-ul; stdin e oricum închis
# Cea mai lungă cale completă pe care Windows o încarcă fără setări speciale: MAX_PATH = 260, din care unul e terminatorul.
WINDOWS_MAX_PATH_CHARS = 259
# Unde pune uv pachetele, față de rădăcina proiectului: începutul căii oricărui fișier instalat.
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
    "runas", "cmd", "sc", "net", "ftp", "tftp", "telnet", "ssh", "scp", "wmic", "msiexec", "bcdedit", "attrib", "forfiles", "tar",
})
# Excepția instalatorului: aceste comenzi, DOAR în instaleaza.bat, DOAR cu argumentele de mai jos (verificate în _installer_rule).
INSTALLER_COMMANDS = frozenset({"curl", "certutil", "tar", "del", "mkdir"})
# Dintre ele, programele separate (nu comenzi din cmd.exe): se cheamă doar din %SYS%, ca un fișier cu același nume din folder să nu fie luat în loc.
INSTALLER_EXTERNAL_TOOLS = frozenset({"curl", "certutil", "tar"})
# Mesajele de eroare ale instalatorului stau în variabila FAIL: sunt text afișat (pot pomeni o cale ca sfat), nu comenzi.
INSTALLER_MESSAGE = re.compile(r'(?i)^set "FAIL=')
INSTALLER_URL = "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-%UV_TINTA%.zip"
INSTALLER_SYSTEM_TOOLS = 'set "SYS=%SystemRoot%\\System32"'  # singurul loc unde apare o cale de sistem: uneltele din Windows
# Unde are voie instalatorul să scrie, să șteargă sau să creeze: doar în folderul programului, sub .uv\ și .venv\.
INSTALLER_OWN_PATHS = re.compile(r'"(?:%CD%\\\.uv\\[^"]*|%CD%\\\.venv\\[^"]*|%UV_ARHIVA%)"')
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
# Ce trebuie să pună instalare\mediu.bat: Python fără __pycache__ și cu UTF-8, plus tot ce descarcă uv și Playwright în .uv\.
ENV_REQUIRED = (
    'set "PYTHONUTF8=1"', 'set "PYTHONDONTWRITEBYTECODE=1"', 'set "UV_CACHE_DIR=%CD%\\.uv\\cache"',
    'set "UV_PYTHON_INSTALL_DIR=%CD%\\.uv\\python"', 'set "UV_PYTHON_PREFERENCE=only-managed"', 'set "UV_NO_CONFIG=1"',
    'set "PLAYWRIGHT_BROWSERS_PATH=%CD%\\.uv\\browsere"',
)
ENV_CALL = 'call ".\\instalare\\mediu.bat"'
# D12/D13 (decis 5 oct. 2026). Cum începe rândul care pornește Python: din .venv, fără condiție în față.
VENV_PYTHON = '".venv\\Scripts\\python.exe"'
# Ce trebuie să urmeze după Python, PE ACELAȘI RÂND: mesajul și pauza din instalare\dupa_rulare.bat, cu codul lui Python
# (a doua expansiune a lui `call` îl citește după ce Python s-a oprit), apoi ieșirea cu codul exact. Un `exit /b` simplu pe
# același rând ar ieși cu 0 (măsurat: `cmd /c` pierde codul), iar un rând separat ar fi citit din fișierul înlocuit.
AFTER_PYTHON_CALL = ' & call ".\\instalare\\dupa_rulare.bat" {stem} %%ERRORLEVEL%%'
EXIT_WITH_PYTHON_CODE = " & call exit /b %%ERRORLEVEL%%"
# Codul cu care programul cere repornirea după o actualizare și lansatorul care pornește atunci varianta lui nouă.
RESTART_EXIT_CODE = settings.EXIT_CODE_RESTART
RESTARTING_LAUNCHER = "porneste.bat"
RESTART_CALL = ' & (if errorlevel {code} if not errorlevel {next_code} call ".\\porneste.bat" %*)'.format(
    code=RESTART_EXIT_CODE, next_code=RESTART_EXIT_CODE + 1)
# P1 (decis 6 oct. 2026): porneste.bat rulează recuperarea unei actualizări întrerupte ÎNAINTEA pregătirii, cu Python-ul din .venv,
# pe un singur rând condiționat (jurnal + .venv, nu imediat după o recuperare). Recuperarea poate înlocui chiar porneste.bat, deci
# tot ce urmează după ea stă pe același rând (D13): la codul 1 mesaj, pauză și ieșire; altfel porneste.bat pornit din nou de la
# început, o singură dată (semnul CHELTUIELI_EMAG_DUPA_RECUPERARE), apoi ieșirea cu codul lui.
RECOVERING_LAUNCHER = "porneste.bat"
RECOVERY_MODULE = "emag_spend.update_recovery"
RECOVERY_MARKER = "CHELTUIELI_EMAG_DUPA_RECUPERARE"
RECOVERY_START = ('if not defined DUPA_RECUPERARE if exist ".actualizare\\jurnal.json" if exist ".venv\\Scripts\\python.exe" '
                  + VENV_PYTHON + " -m " + RECOVERY_MODULE)
RECOVERY_STOP = re.compile(r' & \(if errorlevel 1 if not errorlevel 2 set "RECUPERARE_ESUATA=1"\)'
                           r' & \(if defined RECUPERARE_ESUATA echo\. & echo [^&|<>()^"%]+ & echo\. & pause\)')
RECOVERY_RESTART = (f' & (if not defined RECUPERARE_ESUATA set "{RECOVERY_MARKER}=1" & call ".\\porneste.bat" %*)'
                    + EXIT_WITH_PYTHON_CODE)
# Variabilele rândului recuperării, puse la început: semnul primit de la porneste.bat de dinainte se mută în DUPA_RECUPERARE și se
# golește (nu ajunge la program și nici la o repornire după actualizare), iar RECUPERARE_ESUATA pornește gol (nu din mediu).
RECOVERY_SETUP = (f'set "DUPA_RECUPERARE=%{RECOVERY_MARKER}%"', f'set "{RECOVERY_MARKER}="', 'set "RECUPERARE_ESUATA="')
INSTALLER_CALL = 'call ".\\instaleaza.bat" --fara-pauza'
# Singurele comenzi ale lui dupa_rulare.bat: pune variabile, afișează, așteaptă tasta și iese. Nu pornește nimic altceva.
AFTER_RUN_COMMANDS = frozenset({"setlocal", "set", "chcp", "echo", "pause", "exit"})
AFTER_RUN_TAIL = "(if not defined FARA_PAUZA pause) & exit /b %COD%"


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
                redirects.append((operator, target.group(1) if target else ""))
                i += target.end() if target else 0
        else:
            current.append(ch)
        i += 1
    segments.append("".join(current))
    return segments, redirects


def _strip_prefixes(segment: str) -> str:
    """Segmentul fără @ ( ), fără condițiile `if ...`, `else`, `for ... do`, `call` din față."""
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
            return text


def _command_of(segment: str) -> str:
    """Numele comenzii dintr-un segment: fără condiții și prefixe; în litere mici, fără extensie și fără cale."""
    token = re.match(r'("[^"]*"|[^\s"]+)', _strip_prefixes(segment))
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


def _installer_rule(command: str, segment: str) -> str | None:
    """Motivul pentru care o comandă de instalare NU respectă excepția (None = permisă). Doar pentru instaleaza.bat."""
    body = _strip_prefixes(segment)
    if command in INSTALLER_EXTERNAL_TOOLS and not body.lower().startswith(f"%sys%\\{command}.exe"):
        return f"«{command}» trebuie chemat din %SYS%\\{command}.exe (uneltele din Windows), nu din PATH"
    if command == "curl":
        urls = re.findall(r"https?://\S+", body)
        if urls != [f'"{INSTALLER_URL}"'] and urls != [INSTALLER_URL]:
            if [url.strip('"') for url in urls] != [INSTALLER_URL]:
                return f"curl are voie să descarce doar {INSTALLER_URL}, găsit {urls}"
        if "--proto =https" not in body or '-o "%UV_ARHIVA%"' not in body:
            return "curl trebuie să accepte doar HTTPS și să scrie doar în %UV_ARHIVA% (sub .uv)"
    elif command == "certutil":
        if not re.fullmatch(r'(?i)%sys%\\certutil\.exe -hashfile "[^"]+" SHA256', body.strip()):
            return "certutil e permis doar ca «-hashfile ... SHA256» (calculul amprentei)"
    elif command == "tar":
        if not re.fullmatch(r'(?i)%sys%\\tar\.exe -xf "%UV_ARHIVA%" -C "%CD%\\\.uv\\bin" uv\.exe', body.strip()):
            return "tar e permis doar ca să scoată uv.exe din %UV_ARHIVA% în %CD%\\.uv\\bin"
    paths = re.findall(r'"[^"]*"', body)
    for path in paths:
        if command in {"del", "mkdir"} and not INSTALLER_OWN_PATHS.fullmatch(path):
            return f"«{command}» are voie doar în .uv\\ și .venv\\, găsit {path}"
    return None


def _violations(name: str, raw: bytes, launcher: bool, installer: bool = False, runs_python: bool = False) -> list[str]:
    """Toate încălcările regulilor statice pentru un .bat, ca mesaje în română (listă goală = curat).

    `runs_python`: lansatorul pornește Python din .venv, deci primește regula D13 (rândul Python e ultimul) în locul
    regulii „pause + exit /b la final”, care trece în instalare\\dupa_rulare.bat.
    """
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
    first_non_ascii = next((n for n, line in enumerate(lines, 1) if not line.isascii() and not re.match(r"(?i)\s*@?rem(\s|$)", line)), None)
    if first_non_ascii and (chcp_line is None or chcp_line > first_non_ascii):
        problems.append(f"{name}:{first_non_ascii}: are diacritice înainte de «chcp 65001 >nul» (sau fără chcp): în consolă s-ar vedea caractere stricate.")
    if MOJIBAKE.search(text):
        problems.append(f"{name}: conține secvențe de tip «Ã„» (UTF-8 citit ca Windows-1252): textul a fost salvat cu codare greșită.")
    code = _code_lines(text)
    for number, line in code:
        segments, redirects = _statements(line)
        for operator, target in redirects:
            own_file = installer and INSTALLER_OWN_PATHS.fullmatch(target)
            if (target.lower() != "nul" or operator not in {">", ">>"}) and not own_file:
                problems.append(f"{name}:{number}: redirectare «{operator}{target}»: un lansator nu are voie să scrie sau să citească fișiere; doar «>nul» e permis (altfel poate scrie în afara folderului).")
        if installer and line == INSTALLER_SYSTEM_TOOLS:
            continue  # singura cale de sistem permisă: de unde se iau curl, tar și certutil
        for segment in segments:
            command = _command_of(segment)
            if command in FORBIDDEN_COMMANDS:
                reason = _installer_rule(command, segment) if installer and command in INSTALLER_COMMANDS else "un lansator dat utilizatorilor nu are voie să șteargă, să descarce sau să schimbe sistemul"
                if reason:
                    problems.append(f"{name}:{number}: comandă interzisă «{command}»: {reason}.")
                continue
            if command == "echo" or (installer and INSTALLER_MESSAGE.match(_strip_prefixes(segment))):
                continue  # un URL sau o cale în textul afișat e doar text
            if URL_PATTERN.search(segment):
                problems.append(f"{name}:{number}: adresă de internet într-o comandă (nu într-un echo): niciun .bat nu are voie să descarce sau să deschidă adrese.")
            for pattern, why in OUTSIDE_PATH_PATTERNS:
                if pattern.search(segment):
                    problems.append(f"{name}:{number}: {why} într-o comandă: programul scrie doar în folderul lui.")
    if launcher:
        problems.extend(_launcher_violations(name, lines, code, runs_python))
    return problems


def _is_recovery_line(line: str) -> bool:
    """True pentru un rând care rulează recuperarea (`python -m emag_spend.update_recovery`), oricum ar fi condiționat."""
    command = _strip_prefixes(_statements(line)[0][0])
    return command.startswith(VENV_PYTHON) and command[len(VENV_PYTHON):].split()[:2] == ["-m", RECOVERY_MODULE]


def _recovery_line_problems(name: str, recovery: list[tuple[int, str]]) -> list[str]:
    """P1 + D13 pentru rândul recuperării: doar în porneste.bat, exact unul, cu condițiile, oprirea la 1 și repornirea pe același rând.

    Recuperarea poate înlocui porneste.bat cât rulează, deci după ea nu se citește nimic din fișier: rândul se termină fie cu
    ieșirea (la 1, după mesaj și pauză), fie cu porneste.bat pornit din nou de la început și ieșirea cu codul lui.
    """
    if name != RECOVERING_LAUNCHER:
        return [f"{name}:{number}: doar {RECOVERING_LAUNCHER} rulează recuperarea înaintea pregătirii (P1); ceilalți o lasă lui ruleaza.py." for number, _ in recovery]
    if len(recovery) != 1:
        return [f"{name}: trebuie exact un rând care rulează recuperarea înaintea pregătirii (P1), găsite {len(recovery)}."]
    number, line = recovery[0]
    problems = []
    if not line.startswith(RECOVERY_START):
        problems.append(f"{name}:{number}: rândul recuperării trebuie să înceapă exact cu «{RECOVERY_START}»: doar cu jurnal și cu .venv, și nu imediat după o recuperare (altfel s-ar putea relua la nesfârșit).")
    if not line.endswith(RECOVERY_RESTART):
        problems.append(f"{name}:{number}: rândul recuperării trebuie să se termine exact cu «{RECOVERY_RESTART.strip()}»: recuperarea poate înlocui {RECOVERING_LAUNCHER}, deci acesta pornește din nou de la început, o singură dată, cu codul păstrat.")
    elif line.startswith(RECOVERY_START) and not RECOVERY_STOP.fullmatch(line[len(RECOVERY_START):-len(RECOVERY_RESTART)]):
        problems.append(f"{name}:{number}: între recuperare și repornire trebuie exact oprirea la codul 1: «{RECOVERY_STOP.pattern}» (mesaj fără caractere speciale, pauză, fără repornire).")
    return problems


def _after_python_problems(name: str, code: list[tuple[int, str]]) -> list[str]:
    """Regula D13 pentru un lansator care pornește Python: după Python nu se mai citește nimic din fișier.

    Cere: un singur rând care pornește programul, necondiționat, ultimul rând cu cod, terminat exact cu lanțul de după Python
    (dupa_rulare.bat cu numele lansatorului și codul, la porneste.bat și repornirea, apoi `call exit /b` cu codul). În plus, doar
    la porneste.bat, rândul recuperării (P1), verificat de _recovery_line_problems.
    """
    stem = Path(name).stem
    expected = AFTER_PYTHON_CALL.format(stem=stem) + (RESTART_CALL if name == RESTARTING_LAUNCHER else "") + EXIT_WITH_PYTHON_CODE
    starts = [(number, line) for number, line in code if _strip_prefixes(_statements(line)[0][0]).startswith(VENV_PYTHON)]
    recovery = [(number, line) for number, line in starts if _is_recovery_line(line)]
    problems = _recovery_line_problems(name, recovery) if recovery or name == RECOVERING_LAUNCHER else []
    starts = [start for start in starts if start not in recovery]
    if len(starts) != 1:
        return problems + [f"{name}: trebuie exact un rând care pornește programul, găsite {len(starts)}: cu mai multe, unul ar fi urmat de rânduri citite din fișierul înlocuit de o actualizare."]
    number, line = starts[0]
    if not line.startswith(VENV_PYTHON):
        problems.append(f"{name}:{number}: rândul care pornește Python trebuie să înceapă direct cu {VENV_PYTHON}, fără condiție: cu condiția falsă, cmd ar citi mai departe din fișier.")
    if (number, line) != code[-1]:
        problems.append(f"{name}:{number}: după rândul care pornește Python mai urmează cod (rândul {code[-1][0]}): o actualizare înlocuiește lansatorul cât rulează Python, iar cmd ar citi rândul următor din fișierul nou, de la o poziție greșită.")
    command = _statements(line)[0][0].rstrip()  # doar comanda Python, până la primul & (fără spațiul dinaintea lui)
    if line != command + expected:
        problems.append(f"{name}:{number}: rândul care pornește Python trebuie să se termine exact cu «{expected.strip()}»: tot ce urmează după Python stă pe același rând, iar codul de ieșire se păstrează exact.")
    return problems


def _launcher_violations(name: str, lines: list[str], code: list[tuple[int, str]], runs_python: bool = False) -> list[str]:
    """Regulile în plus pentru lansatoare: folder, mediu, pause la erori și la final (la cele cu Python: regula D13)."""
    problems = []
    text = "\r\n".join(lines)
    if 'cd /d "%~dp0"' not in text:
        problems.append(f'{name}: lipsește «cd /d "%~dp0"»: dublu-clic dintr-un folder cu spații sau de pe alt disc ar rula în alt director.')
    if ENV_CALL not in text and not all(f'set "{variable}"' in text for variable in ("PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1")):
        problems.append(f'{name}: lipsește «{ENV_CALL}» (sau PYTHONDONTWRITEBYTECODE și PYTHONUTF8): fără el Python scrie __pycache__ lângă cod, nu folosește UTF-8 și nu găsește ce a descărcat uv.')
    if re.search(r"(?im)^\s*(goto|call\s+:)|^\s*:[A-Za-z_]", text):
        problems.append(f"{name}: folosește goto, call: sau o etichetă; cu diacritice UTF-8 și chcp 65001 cmd.exe poate rata eticheta, deci lansatoarele folosesc doar if.")
    for position, (number, line) in enumerate(code):
        if re.match(r"(?i)(?:if (?:not )?defined \w+ )*exit\s+/b", line):
            window = [other.strip() for _, other in code[max(0, position - PAUSE_LOOKBACK_LINES):position]]
            if not any(PAUSE_LINE.fullmatch(other) for other in window):
                problems.append(f"{name}:{number}: «{line}» fără «pause» chiar înainte: fereastra s-ar închide înainte să apuce utilizatorul să citească mesajul.")
    if runs_python:
        problems.extend(_after_python_problems(name, code))
        return problems
    tail = [line.strip() for _, line in code[-2:]]
    if len(tail) < 2 or not PAUSE_LINE.fullmatch(tail[0]) or not tail[1].lower().startswith("exit /b"):
        problems.append(f"{name}: ultimele două comenzi trebuie să fie «pause» și «exit /b ...»: utilizatorul trebuie să apuce să citească rezultatul final.")
    return problems


def _is_launcher(path: Path) -> bool:
    """True pentru lansatoarele care pornesc Python (login, ruleaza, demo, sterge_sesiunea, porneste, instaleaza)."""
    return path.name in PYTHON_LAUNCHERS or path.name == INSTALLER


def _versions() -> dict[str, str]:
    """Cheile din instalare/versiuni.txt (rânduri CHEIE=valoare; # = comentariu)."""
    pairs = {}
    for line in VERSIONS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


# ---------- reguli statice pe fișierele reale ----------

def test_every_documented_bat_file_exists():
    """Cele 7 lansatoare cu nume fix (cele din README) există în rădăcină; lipsa unuia ar lăsa utilizatorul cu un clic pe un fișier inexistent."""
    missing = [name for name in REQUIRED_BAT_NAMES if not (PROJECT_ROOT / name).is_file()]
    assert not missing, f"lipsesc din rădăcină: {', '.join(missing)}. README și INSTALARE le numesc, deci un utilizator ar da clic pe un fișier care nu există."


@pytest.mark.parametrize("path", BAT_FILES, ids=lambda p: p.name)
def test_bat_file_follows_the_static_rules(path):
    """Fiecare .bat din rădăcină respectă regulile statice; instaleaza.bat are doar excepția îngustă a descărcării lui uv."""
    problems = _violations(path.name, path.read_bytes(), _is_launcher(path), installer=path.name == INSTALLER,
                           runs_python=path.name in PYTHON_LAUNCHERS)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name", PYTHON_LAUNCHERS)
def test_nothing_is_read_from_the_launcher_after_python_starts(name):
    """D13: rândul care pornește Python e ultimul din lansator și se termină cu tot ce urmează (mesaj, pauză, cod exact).

    O actualizare înlocuiește lansatorul cât rulează Python; cmd citește un .bat pe bucăți, după poziție, deci orice rând
    de după Python ar fi citit din fișierul nou, de la o poziție greșită.
    """
    problems = _after_python_problems(name, _code_lines((PROJECT_ROOT / name).read_bytes().decode("utf-8")))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("lines, expected", [
    # Forma veche: Python pe un rând, codul și mesajul pe rândurile următoare (citite din fișierul înlocuit).
    ((VENV_PYTHON + " ruleaza.py --demo", 'set "COD=%ERRORLEVEL%"', "pause", "exit /b %COD%"), "mai urmează cod"),
    # Ieșirea fără cod pe același rând: `cmd /c` ar ieși cu 0 indiferent de codul lui Python.
    ((VENV_PYTHON + ' ruleaza.py --demo & call ".\\instalare\\dupa_rulare.bat" demo %%ERRORLEVEL%% & exit /b',), "să se termine exact"),
    # Fără mesajul și pauza de după Python: fereastra s-ar închide înainte de citire.
    ((VENV_PYTHON + " ruleaza.py --demo & call exit /b %%ERRORLEVEL%%",), "să se termine exact"),
    # Python condiționat: cu condiția falsă, cmd citește mai departe din fișier.
    (('if "%~1"=="" ' + VENV_PYTHON + " ruleaza.py --demo" + AFTER_PYTHON_CALL.format(stem="demo") + EXIT_WITH_PYTHON_CODE,), "fără condiție"),
    # Două rânduri cu Python: primul ar fi urmat de rânduri citite din fișierul înlocuit.
    ((VENV_PYTHON + " ruleaza.py --demo", VENV_PYTHON + " ruleaza.py --demo" + AFTER_PYTHON_CALL.format(stem="demo") + EXIT_WITH_PYTHON_CODE), "exact un rând"),
])
def test_after_python_rule_catches_launchers_that_read_their_file_after_python(lines, expected):
    """Capcană D13: forma veche, ieșirea care pierde codul, lipsa pauzei, Python condiționat și Python de două ori sunt prinse."""
    raw = _crlf("@echo off", "chcp 65001 >nul", 'cd /d "%~dp0"', ENV_CALL, *lines)
    problems = "\n".join(_violations("demo.bat", raw, launcher=True, runs_python=True))
    assert expected in problems, f"nu a fost prins: {lines}\n{problems}"


def test_after_python_rule_requires_the_restart_only_in_porneste():
    """Capcană: porneste.bat fără repornirea la 75 e prins; același rând cu repornire e corect doar la porneste.bat."""
    plain = VENV_PYTHON + " ruleaza.py %ARGUMENTE%" + AFTER_PYTHON_CALL.format(stem="porneste") + EXIT_WITH_PYTHON_CODE
    restarting = VENV_PYTHON + " ruleaza.py %ARGUMENTE%" + AFTER_PYTHON_CALL.format(stem="porneste") + RESTART_CALL + EXIT_WITH_PYTHON_CODE
    assert _after_python_problems("porneste.bat", [(1, RECOVERY_LINE_EXAMPLE), (2, plain)]), "porneste.bat fără repornire trebuia prins"
    assert _after_python_problems("porneste.bat", [(1, RECOVERY_LINE_EXAMPLE), (2, restarting)]) == []
    assert _after_python_problems("demo.bat", [(1, restarting.replace("porneste %%", "demo %%"))]), "repornirea e doar a lui porneste.bat"


# Un rând de recuperare corect (mesajul e inventat), pentru capcanele regulii P1.
RECOVERY_LINE_EXAMPLE = (RECOVERY_START + ' & (if errorlevel 1 if not errorlevel 2 set "RECUPERARE_ESUATA=1")'
                         " & (if defined RECUPERARE_ESUATA echo. & echo Mesaj inventat, fără caractere speciale. & echo. & pause)"
                         + RECOVERY_RESTART)
MAIN_LINE_EXAMPLE = VENV_PYTHON + " ruleaza.py %ARGUMENTE%" + AFTER_PYTHON_CALL.format(stem="porneste") + RESTART_CALL + EXIT_WITH_PYTHON_CODE


@pytest.mark.parametrize("name, lines, expected", [
    # Fără rândul recuperării: pregătirea ar citi versiuni.txt și requirements.txt dintr-un arbore amestecat (V1-1).
    ("porneste.bat", (MAIN_LINE_EXAMPLE,), "exact un rând care rulează recuperarea"),
    # Fără semnul de după recuperare: un jurnal care nu se poate șterge ar reporni porneste.bat la nesfârșit.
    ("porneste.bat", (RECOVERY_LINE_EXAMPLE.replace("if not defined DUPA_RECUPERARE ", ""), MAIN_LINE_EXAMPLE), "să înceapă exact"),
    # Fără repornire: după o recuperare care a înlocuit porneste.bat, cmd ar citi rândul următor din fișierul nou.
    ("porneste.bat", (RECOVERY_LINE_EXAMPLE[:-len(RECOVERY_RESTART)], MAIN_LINE_EXAMPLE), "să se termine exact"),
    # Ieșirea la 1 în mijlocul rândului: `cmd /c` ar pierde codul (iese cu 0), iar repornirea s-ar sări oricum.
    ("porneste.bat", (RECOVERY_LINE_EXAMPLE.replace("& pause)", "& pause & exit /b 1)"), MAIN_LINE_EXAMPLE), "exact oprirea la codul 1"),
    # O paranteză în mesaj ar închide blocul mai devreme, iar restul mesajului ar rula ca o comandă.
    ("porneste.bat", (RECOVERY_LINE_EXAMPLE.replace("Mesaj inventat,", "Mesaj (inventat),"), MAIN_LINE_EXAMPLE), "exact oprirea la codul 1"),
    # Două rânduri de recuperare: primul ar fi urmat de rânduri citite din fișierul poate înlocuit.
    ("porneste.bat", (RECOVERY_LINE_EXAMPLE, RECOVERY_LINE_EXAMPLE, MAIN_LINE_EXAMPLE), "găsite 2"),
    # Recuperarea în alt lansator decât porneste.bat: ceilalți nu cheamă pregătirea, deci o lasă lui ruleaza.py.
    ("demo.bat", (RECOVERY_LINE_EXAMPLE, VENV_PYTHON + " ruleaza.py --demo" + AFTER_PYTHON_CALL.format(stem="demo") + EXIT_WITH_PYTHON_CODE), "doar porneste.bat"),
])
def test_recovery_rule_catches_launchers_that_could_loop_or_read_their_file_after_the_recovery(name, lines, expected):
    """Capcană P1: lipsa recuperării, a semnului, a repornirii, ieșirea în mijlocul rândului, paranteza în mesaj, două rânduri și
    recuperarea în alt lansator sunt prinse; rândul corect (RECOVERY_LINE_EXAMPLE) trece (testul de mai sus)."""
    problems = "\n".join(_after_python_problems(name, list(enumerate(lines, start=1))))
    assert expected in problems, f"nu a fost prins: {lines}\n{problems}"


def _count_lines(code: list[tuple[int, str]], line: str) -> int:
    """De câte ori apare exact rândul `line` printre rândurile cu cod."""
    return sum(1 for _, other in code if other == line)


def test_porneste_recovers_after_the_environment_and_before_the_preparation():
    """P1 static: în porneste.bat, variabilele rândului recuperării se pun la început, mediul se încarcă înaintea recuperării
    (fără __pycache__ în arborele refăcut), iar rândul recuperării vine ÎNAINTEA lui instaleaza.bat (ordinea e contract)."""
    code = _code_lines((PROJECT_ROOT / RECOVERING_LAUNCHER).read_bytes().decode("utf-8"))
    position = {line: index for index, (_, line) in enumerate(code)}
    recovery = next((index for index, (_, line) in enumerate(code) if _is_recovery_line(line)), None)
    assert recovery is not None, f"{RECOVERING_LAUNCHER} nu rulează recuperarea înaintea pregătirii (P1)"
    for line in (*RECOVERY_SETUP, ENV_CALL):
        assert position.get(line, len(code)) < recovery, f"«{line}» trebuie să fie înaintea rândului recuperării"
    assert recovery < position.get(INSTALLER_CALL, -1), "recuperarea trebuie să ruleze ÎNAINTEA pregătirii (instaleaza.bat)"
    assert _count_lines(code, ENV_CALL) == 1, "mediul se încarcă o singură dată, înaintea recuperării (instaleaza.bat are setlocal propriu)"



def _after_run_code() -> list[tuple[int, str]]:
    """Rândurile cu cod din instalare\\dupa_rulare.bat."""
    return _code_lines(AFTER_RUN_BAT.read_bytes().decode("utf-8"))


def test_after_run_helper_follows_the_static_rules_and_only_shows_text():
    """instalare\\dupa_rulare.bat: regulile statice, fără goto/etichete, doar set/echo/pause/exit, iar pauza și ieșirea pe ultimul rând.

    Pauza și ieșirea stau pe același rând: dacă altă fereastră a programului face o actualizare cât aceasta așteaptă o tastă,
    după tastă cmd nu mai citește nimic din fișierul înlocuit.
    """
    raw = AFTER_RUN_BAT.read_bytes()
    problems = _violations(AFTER_RUN_NAME, raw, launcher=False)
    assert not problems, "\n".join(problems)
    text = raw.decode("utf-8")
    assert not re.search(r"(?im)^\s*(goto|call\s+:)|^\s*:[A-Za-z_]", text), "dupa_rulare.bat nu are voie să folosească goto sau etichete"
    commands = {_command_of(segment).rstrip(")") for _, line in _after_run_code() for segment in _statements(line)[0]}
    assert commands <= AFTER_RUN_COMMANDS, f"dupa_rulare.bat are voie doar să afișeze, să aștepte și să iasă, găsit: {sorted(commands - AFTER_RUN_COMMANDS)}"
    assert _after_run_code()[-1][1] == AFTER_RUN_TAIL, f"ultimul rând trebuie să fie «{AFTER_RUN_TAIL}»"
    assert 'set "COD=%~2"' in text and 'set "LANSATOR=%~1"' in text, "codul și numele lansatorului vin ca argumente (contractul stabil între versiuni)"


def test_restart_code_is_the_same_in_settings_the_helper_and_porneste():
    """Codul de repornire (75) e același în settings.EXIT_CODE_RESTART, în dupa_rulare.bat și în rândul lui porneste.bat."""
    assert f'set "COD_REPORNIRE={RESTART_EXIT_CODE}"' in AFTER_RUN_BAT.read_text(encoding="utf-8"), "dupa_rulare.bat are alt cod de repornire decât settings.py"
    assert RESTART_CALL in (PROJECT_ROOT / RESTARTING_LAUNCHER).read_text(encoding="utf-8"), "porneste.bat nu repornește la codul din settings.py"


def test_shared_environment_file_keeps_every_download_inside_the_program_folder():
    """instalare\\mediu.bat: CRLF, doar `set`, și pune cache-ul uv, Python-ul și browserul descărcate în .uv\\ din folderul programului."""
    raw = ENV_BAT.read_bytes()
    assert not _violations("instalare/mediu.bat", raw, launcher=False), _violations("instalare/mediu.bat", raw, launcher=False)
    text = raw.decode("utf-8")
    for required in ENV_REQUIRED:
        assert required in text, f"instalare\\mediu.bat nu are «{required}»: uv sau Playwright ar scrie în folderul personal sau ar folosi alt Python"
    commands = {_command_of(line) for _, line in _code_lines(text)} - {"echo"}
    assert commands <= {"set"}, f"instalare\\mediu.bat are voie doar să pună variabile, găsit: {sorted(commands)}"


@pytest.mark.parametrize("name, option", sorted(LAUNCHER_OPTIONS.items()))
def test_each_launcher_calls_its_option_and_the_option_exists(name, option):
    """Rândul de apel al fiecărui lansator pornește Python din .venv cu opțiunea lui, iar ruleaza.py cunoaște opțiunea (altfel utilizatorul vede o eroare argparse)."""
    text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
    default = re.search(r'(?m)^set "ARGUMENTE=([^"]*)"', text)  # porneste.bat: argumentele implicite, când nu primește altele
    if default:
        text = text.replace("%ARGUMENTE%", default.group(1))
    calls = [_strip_prefixes(line) for line in text.splitlines() if "ruleaza.py" in line and '".venv' in line]
    call = next((line for line in calls if option in line), "")
    assert call, f"{name} trebuie să cheme «ruleaza.py {option}», dar rândurile de apel sunt {calls}"
    assert call.startswith(r'".venv\Scripts\python.exe"'), f"{name}: Python-ul trebuie luat din .venv, nu din PATH: {call}"
    try:
        ruleaza._parse_args([option])
    except SystemExit:
        pytest.fail(f"{name} cheamă «ruleaza.py {option}», dar ruleaza.py nu cunoaște opțiunea: utilizatorul ar primi o eroare argparse.")


def test_ruleaza_bat_forwards_the_users_arguments():
    """ruleaza.bat pasează «%*» către ruleaza.py, ca opțiunile utilizatorului (ex. --prag 1000) să ajungă la program."""
    text = (PROJECT_ROOT / "ruleaza.bat").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\"\.venv\\Scripts\\python\.exe\" ruleaza\.py --deschide %\* & ", text), "ruleaza.bat trebuie să paseze «%*» mai departe (ex. ruleaza.bat --prag 1000)"


def test_porneste_forwards_arguments_and_defaults_to_the_application():
    """porneste.bat fără argumente pornește aplicația (--aplicatie); cu argumente le pasează neschimbate (ex. porneste.bat --demo).

    La repornirea după actualizare, porneste.bat nou primește argumentele originale (%*), deci aceeași comandă.
    """
    text = (PROJECT_ROOT / "porneste.bat").read_text(encoding="utf-8")
    assert re.search(r'(?m)^set "ARGUMENTE=--aplicatie"\r?$', text), "fără argumente porneste.bat trebuie să pornească aplicația"
    assert re.search(r'(?m)^if not "%~1"=="" set ARGUMENTE=%\*\r?$', text), "cu argumente porneste.bat trebuie să le paseze cu %*"
    assert re.search(r'(?m)^"\.venv\\Scripts\\python\.exe" ruleaza\.py %ARGUMENTE% & ', text), "rândul Python trebuie să folosească ARGUMENTE"
    assert text.index('set "ARGUMENTE=--aplicatie"') < text.index('if not "%~1"=="" set ARGUMENTE=%*'), "valoarea implicită se pune înainte de argumente"


def test_installer_downloads_only_the_pinned_uv_and_checks_its_fingerprint():
    """instaleaza.bat ia versiunea și amprentele din instalare\\versiuni.txt, descarcă doar uv de la adresa oficială și compară amprenta SHA-256 înainte de dezarhivare."""
    text = (PROJECT_ROOT / INSTALLER).read_text(encoding="utf-8")
    assert 'in ("instalare\\versiuni.txt") do set "%%a=%%b"' in text, "versiunile trebuie citite din instalare\\versiuni.txt, nu scrise în .bat"
    assert INSTALLER_URL in text, "adresa de descărcare a lui uv trebuie să fie cea oficială, construită din versiunea fixată"
    check = text.index('if /i not "%GASIT%"=="%UV_AMPRENTA%" set "FAIL=')
    assert check < text.index("tar.exe -xf"), "amprenta trebuie verificată ÎNAINTE de dezarhivare"
    assert 'set "UV_AMPRENTA=%SHA256_WINDOWS_X64%"' in text and 'set "UV_AMPRENTA=%SHA256_WINDOWS_ARM64%"' in text
    assert 'set "UV_ARHIVA=%CD%\\.uv\\descarcari\\uv-%UV_VERSION%-%UV_TINTA%.zip"' in text, (
        "arhiva păstrată trebuie să aibă versiunea în nume (N12): una rămasă de la alt UV_VERSION ar da o alarmă falsă de amprentă")


def test_installer_installs_only_runtime_requirements_from_ready_made_packages():
    """instaleaza.bat instalează doar requirements.txt (nu pachetele de test) și doar pachete gata făcute (nu rulează cod de instalare de pe internet)."""
    text = (PROJECT_ROOT / INSTALLER).read_text(encoding="utf-8")
    install = next((line for line in text.splitlines() if "pip install" in line and not line.lstrip().lower().startswith("rem")), "")
    assert '-r "%CD%\\requirements.txt"' in install and "requirements-dev" not in install, "se instalează doar requirements.txt"
    assert "--only-binary :all:" in install, "fără --only-binary uv poate rula cod de instalare (setup.py) de pe internet pe calculatorul utilizatorului"


def test_installer_skips_every_pause_only_through_the_documented_flag():
    """În instaleaza.bat orice `pause` e condiționat de NO_PAUSE, care pornește gol și se pune pe 1 doar din argumentul --fara-pauza (nu din mediul utilizatorului)."""
    text = (PROJECT_ROOT / INSTALLER).read_text(encoding="utf-8")
    assert 'set "NO_PAUSE="' in text, "NO_PAUSE trebuie golit la început: altfel o variabilă din mediul utilizatorului ar sări peste toate pauzele"
    assert text.count('set "NO_PAUSE=1"') == 1 and 'if /i "%~1"=="--fara-pauza" set "NO_PAUSE=1"' in text, "NO_PAUSE se pune pe 1 doar din argumentul --fara-pauza"
    pauses = [line.strip() for line in text.splitlines() if re.fullmatch(r"\s*(?:if (?:not )?defined \w+ )*pause\s*", line, re.IGNORECASE)]
    assert len(pauses) >= 2 and all("if not defined NO_PAUSE pause" in line for line in pauses), f"un pause scapă de condiție: {pauses}"
    assert re.search(r"(?m)^if not defined NO_PAUSE echo Ce urmează", text), "mesajul «Ce urmează» trebuie să dispară la apelul din porneste.bat"


def test_porneste_prepares_with_the_flag_and_stops_when_preparation_fails():
    """porneste.bat cheamă `call instaleaza.bat --fara-pauza` și, dacă pregătirea eșuează, se oprește cu mesaj și pause, fără să pornească aplicația."""
    text = (PROJECT_ROOT / "porneste.bat").read_text(encoding="utf-8")
    call = 'call ".\\instaleaza.bat" --fara-pauza'  # cu cale explicită: unde Windows nu mai caută în folderul curent, «call instaleaza.bat» nu ar fi găsit
    assert re.search(re.escape(call) + r'\r?\n\s*if errorlevel 1 set "INSTALL_FAILED=1"', text), "porneste.bat trebuie să verifice rezultatul pregătirii chiar după apel"
    failure = text.split(call, 1)[1].split("Pornesc aplicația", 1)[0]
    assert "pause" in failure and "exit /b 1" in failure, "la eșecul pregătirii trebuie pause și exit /b 1 înainte de pornirea aplicației"


def test_versions_file_has_a_pinned_uv_python_and_a_fingerprint_for_every_platform():
    """instalare/versiuni.txt fixează uv și Python și are câte o amprentă SHA-256 (64 de caractere hex) pentru fiecare sistem suportat."""
    values = _versions()
    assert re.fullmatch(r"\d+\.\d+\.\d+", values.get("UV_VERSION", "")), "UV_VERSION trebuie să fie o versiune exactă (ex. 0.12.23)"
    assert re.fullmatch(r"3\.\d+", values.get("PYTHON_VERSION", "")), "PYTHON_VERSION trebuie să fie de forma 3.13"
    for platform in ("WINDOWS_X64", "WINDOWS_ARM64", "MACOS_X64", "MACOS_ARM64", "LINUX_X64", "LINUX_ARM64"):
        assert re.fullmatch(r"[0-9a-f]{64}", values.get(f"SHA256_{platform}", "")), f"lipsește amprenta SHA-256 pentru {platform}"


def _max_folder_path() -> int:
    """Limita de lungime a căii folderului, citită din `set "MAX_FOLDER_PATH=..."` din instaleaza.bat (o singură sursă pentru .bat și test)."""
    text = (PROJECT_ROOT / INSTALLER).read_text(encoding="utf-8")
    match = re.search(r'(?m)^set "MAX_FOLDER_PATH=(\d+)"', text)
    assert match, "instaleaza.bat nu definește MAX_FOLDER_PATH: fără limită, într-un folder cu cale lungă import-ul din .venv pică cu «DLL load failed … filename too long»"
    assert 'call set "PREA_LUNG=%%CD:~%MAX_FOLDER_PATH%,1%%"' in text, "instaleaza.bat definește MAX_FOLDER_PATH, dar nu o compară cu lungimea folderului curent"
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


def test_installer_path_limit_leaves_room_for_the_longest_installed_binary():
    """Limita de cale din instaleaza.bat + cel mai lung .pyd/.dll din requirements.txt încape sub MAX_PATH (altfel Windows nu-l încarcă, deși s-a instalat)."""
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
    ('tar -xf "x.zip" -C "C:\\Windows"', "comandă interzisă «tar»"),
])
def test_static_rules_catch_dangerous_commands(line, expected):
    """Capcană: fiecare comandă periculoasă (ștergere, descărcare, Registry, redirectare spre alt loc, adresă în comandă) trebuie prinsă de regulile statice."""
    raw = _crlf("@echo off", line)
    assert any(expected in problem for problem in _violations("sintetic.bat", raw, launcher=False)), line


@pytest.mark.parametrize("line, expected", [
    ('if defined NEED_UV %SYS%\\curl.exe --proto =https -fsSL -o "%UV_ARHIVA%" "https://exemplu.invalid/uv.zip"', "curl are voie să descarce doar"),
    ('if defined NEED_UV curl.exe --proto =https -fsSL -o "%UV_ARHIVA%" "' + INSTALLER_URL + '"', "din %SYS%"),
    ('del /q "%CD%\\requirements.txt"', "are voie doar în .uv"),
    ('mkdir "%CD%\\altundeva"', "are voie doar în .uv"),
    ('%SYS%\\tar.exe -xf "%UV_ARHIVA%" -C "%CD%"', "tar e permis doar"),
    ('%SYS%\\certutil.exe -urlcache -f https://exemplu.invalid/x y', "certutil e permis doar"),
    ('echo x >"%CD%\\config\\categorii.json"', "redirectare"),
])
def test_installer_exception_is_narrow(line, expected):
    """Capcană pentru excepția instalatorului: altă adresă, unealtă din PATH, ștergere sau scriere în afara .uv\\ și .venv\\ trebuie prinse."""
    raw = _crlf("@echo off", line)
    problems = "\n".join(_violations(INSTALLER, raw, launcher=False, installer=True))
    assert expected in problems, f"nu a fost prins: {line}\n{problems}"


def test_installer_exception_allows_exactly_the_real_commands():
    """Fals pozitiv: comenzile reale din instaleaza.bat (descărcare fixată, amprentă, dezarhivare, ștergeri în .uv și .venv) nu sunt încălcări."""
    raw = _crlf(
        "@echo off", 'set "SYS=%SystemRoot%\\System32"',
        f'if defined NEED_UV if not exist "%UV_ARHIVA%" %SYS%\\curl.exe --proto =https --tlsv1.2 -fsSL --retry 3 -o "%UV_ARHIVA%" "{INSTALLER_URL}"',
        'if defined NEED_UV del /q "%UV_ARHIVA%"', 'if defined NEED_UV if not exist "%CD%\\.uv\\bin" mkdir "%CD%\\.uv\\bin"',
        'if defined NEED_UV %SYS%\\tar.exe -xf "%UV_ARHIVA%" -C "%CD%\\.uv\\bin" uv.exe',
        'if not defined FAIL >"%CD%\\.venv\\cerinte.sha256" echo %CERINTE%',
    )
    assert _violations(INSTALLER, raw, launcher=False, installer=True) == []


def test_static_rules_allow_text_with_urls_and_python_code_with_special_characters():
    """Fals pozitiv: o adresă în `echo` și o comandă Python cu caractere speciale (>=, ^, paranteze) nu sunt încălcări."""
    raw = _crlf(
        "@echo off",
        "echo Deschide https://www.google.com/chrome/ si instaleaza ^(ultima versiune^)",
        '".venv\\Scripts\\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>&1',
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
    """Capcană: un lansator fără cd /d, fără mediu, cu goto sau fără pause înainte de exit trebuie prins."""
    raw = _crlf("@echo off", "chcp 65001 >nul", "echo salut", "goto :sus", ":sus", "exit /b 1")
    problems = "\n".join(_violations("sintetic.bat", raw, launcher=True))
    for expected in ('cd /d "%~dp0"', "instalare\\mediu.bat", "goto", "fără «pause»", "ultimele două comenzi"):
        assert expected in problems, f"nu a fost prins: {expected}\n{problems}"


# ---------- execuție reală, doar în folderul temporar al lui pytest, fără internet ----------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="lansatoarele .bat rulează doar pe Windows")


def _run_bat(folder: Path, name: str, *args: str, path_env: str | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Rulează `folder\\name` prin cmd.exe, cu stdin închis (ca la un clic) și fără fereastră proprie.

    CREATE_NO_WINDOW: `chcp 65001` din .bat schimbă consola procesului, nu consola în care rulează pytest. Proxy-ul lui curl
    e mereu un port mort (OFFLINE_ENV), ca un instalator ajuns la descărcare să nu iasă pe internet; `extra_env` îl poate
    îndrepta spre github.com-ul fals (FakeUvRelease.curl_env).
    """
    env = {**os.environ, **OFFLINE_ENV, **(extra_env or {})}
    if path_env is not None:
        env["PATH"] = path_env
    return subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", f".\\{name}", *args],
        cwd=folder, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=RUN_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _copy_bats(folder: Path, *names: str) -> None:
    """Copiază .bat-urile cerute în `folder`, plus instalare\\ (mediul comun, versiunile, ce urmează după Python), fără restul programului."""
    for name in names:
        shutil.copy(PROJECT_ROOT / name, folder / name)
    (folder / "instalare").mkdir(exist_ok=True)
    shutil.copy(ENV_BAT, folder / "instalare" / "mediu.bat")
    shutil.copy(VERSIONS_FILE, folder / "instalare" / "versiuni.txt")
    shutil.copy(AFTER_RUN_BAT, folder / "instalare" / "dupa_rulare.bat")


def _listing(folder: Path) -> list[str]:
    """Toate căile din `folder`, relative și sortate: pentru a dovedi că rularea n-a creat nimic."""
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def _output(result: subprocess.CompletedProcess) -> str:
    """Ieșirea unui .bat decodată UTF-8 (după `chcp 65001`)."""
    return (result.stdout + result.stderr).decode("utf-8", errors="replace")


def _uv_target() -> str:
    """Ținta uv pentru procesorul acestui calculator, ca în instaleaza.bat (UV_TINTA)."""
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "")
    return "aarch64-pc-windows-msvc" if arch.upper() == "ARM64" else "x86_64-pc-windows-msvc"


def _uv_archive_name(version: str) -> str:
    """Numele sub care instaleaza.bat păstrează arhiva uv în .uv\\descarcari: cu versiunea în nume (N12)."""
    return f"uv-{version}-{_uv_target()}.zip"


def _uv_url_path(version: str) -> str:
    """Calea de pe github.com de unde descarcă instaleaza.bat uv `version` (numele oficial, fără versiune)."""
    return f"/astral-sh/uv/releases/download/{version}/uv-{_uv_target()}.zip"


def _skip_if_installer_refuses_the_path(folder: Path) -> None:
    """Sare testul dacă `folder` are deja calea mai lungă decât MAX_FOLDER_PATH: instaleaza.bat s-ar opri, corect, la verificarea
    lungimii, înainte de partea testată (se întâmplă când folderul temporar al lui pytest e adânc)."""
    limit = _max_folder_path()
    if len(str(folder)) > limit:
        pytest.skip(f"folderul temporar al testului are {len(str(folder))} caractere, peste limita {limit} din instaleaza.bat")


@pytest.fixture(scope="module")
def fake_github(tmp_path_factory):
    """github.com fals pe 127.0.0.1 (HTTPS), pentru descărcarea lui uv din instaleaza.bat; sare fără Windows sau fără openssl."""
    if sys.platform != "win32":
        pytest.skip("instaleaza.bat rulează doar pe Windows")
    openssl = find_openssl()
    if openssl is None:
        pytest.skip("nu există openssl aici (pe Windows vine cu Git for Windows): nu pot face certificatul serverului fals")
    server = FakeUvRelease(tmp_path_factory.mktemp("github_fals"), openssl)
    yield server
    server.close()


@windows_only
@pytest.mark.parametrize("name", PYTHON_LAUNCHERS[:-1])
def test_launchers_without_venv_say_to_run_porneste_and_create_nothing(tmp_path, name):
    """La execuție: fără .venv fiecare lansator spune să dai dublu-clic pe porneste.bat, iese cu cod 1 și nu creează nimic."""
    _copy_bats(tmp_path, name)
    (tmp_path / "ruleaza.py").write_text("raise SystemExit('nu trebuie rulat')\n", encoding="utf-8")
    before = _listing(tmp_path)
    result = _run_bat(tmp_path, name)
    output = _output(result)
    assert result.returncode == 1, output
    assert "porneste.bat" in output and "Traceback" not in output, output
    assert _listing(tmp_path) == before, "lansatorul fără .venv nu are voie să creeze fișiere sau foldere"


@windows_only
@pytest.mark.parametrize("name", PYTHON_LAUNCHERS + (INSTALLER,))
def test_launchers_run_from_inside_a_zip_say_to_extract_first(tmp_path, name):
    """La execuție: un .bat rulat din ZIP (fără restul programului) spune să extragi tot și nu creează nimic."""
    shutil.copy(PROJECT_ROOT / name, tmp_path / name)  # ca după un dublu-clic pe .bat din ZIP: doar fișierul lui
    result = _run_bat(tmp_path, name)
    output = _output(result)
    assert result.returncode == 1, output
    assert "Extract All" in output and "Extrage tot" in output, output
    assert _listing(tmp_path) == [name]


@windows_only
def test_installer_deletes_an_archive_with_the_wrong_fingerprint_and_installs_nothing(tmp_path, fake_github):
    """La execuție, cu versiuni.txt real și github.com fals: o arhivă uv rămasă cu altă amprentă se șterge și se descarcă o dată
    din nou; dacă și cea descărcată are altă amprentă, se șterge, nu se dezarhivează și nu apare .venv."""
    _skip_if_installer_refuses_the_path(tmp_path)
    fake_github.reset()
    _copy_bats(tmp_path, INSTALLER)
    (tmp_path / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    version = _versions()["UV_VERSION"]
    downloads = tmp_path / ".uv" / "descarcari"
    downloads.mkdir(parents=True)
    (downloads / _uv_archive_name(version)).write_bytes(b"nu e uv, e o arhiva falsa")
    fake_github.serve(_uv_url_path(version), b"nici asta nu e uv, e alta arhiva falsa")
    result = _run_bat(tmp_path, INSTALLER, "--fara-pauza", extra_env=fake_github.curl_env(tmp_path / "curl_fals"))
    output = _output(result)
    assert result.returncode == 1, output
    assert "amprenta SHA-256" in output and "NU o folosesc" in output, output
    assert fake_github.requests == [_uv_url_path(version)], f"arhiva rămasă trebuia descărcată exact o dată din nou: {fake_github.requests}"
    assert not (downloads / _uv_archive_name(version)).exists(), "arhiva cu amprentă greșită trebuie ștearsă"
    assert not (tmp_path / ".uv" / "bin" / "uv.exe").exists() and not (tmp_path / ".venv").exists()


# N12 (decis 6 oct. 2026): versiunea lui uv din aceste teste e inventată (arată că numele arhivei vine din versiuni.txt), iar
# OLDER_UV_VERSION e „versiunea de dinainte”, ca la o arhivă rămasă după o actualizare a programului care a schimbat UV_VERSION.
INVENTED_UV_VERSION = "9.8.7"
OLDER_UV_VERSION = "9.8.6"
# Conținutul lui uv.exe din arhiva bună. Nu e un program: după dezarhivare `uv venv` pică, deci pregătirea se oprește la pasul 2,
# iar testul vede exact ce uv.exe a ajuns în .uv\bin.
FAKE_UV_EXE = b"uv.exe inventat, din arhiva buna"
OTHER_UV_EXE = b"uv.exe inventat, din alta arhiva (stricata sau de la alta versiune)"
NEXT_STEP_MESSAGE = "nu am putut pregăti Python"  # mesajul pasului 2: uv a trecut de amprentă și a fost dezarhivat
# Ce e deja în .uv\descarcari (tipul numelui → ce arhivă), ce servește github.com-ul fals, câte descărcări trebuie să fie
# și dacă uv trebuie să treacă de amprentă. Tipul numelui: "versiune" = cu UV_VERSION, "veche" = cu OLDER_UV_VERSION,
# "fara-versiune" = numele vechi, fără versiune.
UV_DOWNLOAD_CASES = {
    "ramasa-stricata": ({"versiune": "alta"}, "buna", 1, True),
    "ramase-de-la-alta-versiune": ({"veche": "alta", "fara-versiune": "alta"}, "buna", 1, True),
    "deja-buna": ({"versiune": "buna"}, "buna", 0, True),
    "descarcata-stricata": ({}, "alta", 1, False),
    "ramasa-si-descarcata-stricate": ({"versiune": "alta"}, "alta", 1, False),
    "ramasa-veche-si-descarcata-stricata": ({"veche": "alta"}, "alta", 1, False),
}
# P9 (decis 6 oct. 2026): după o dezarhivare reușită nu rămâne nicio arhivă uv-* în .uv\descarcari (nici cea tocmai folosită),
# iar un fișier care nu e arhivă uv rămâne; fără dezarhivare reușită, arhivele de la alte versiuni rămân neatinse.
UV_ARCHIVE_PREFIX = "uv-"
UNRELATED_DOWNLOAD = "altceva.txt"


def _uv_archives(folder: Path) -> list[str]:
    """Numele arhivelor uv-* rămase în `folder` (.uv\\descarcari), sortate."""
    return sorted(path.name for path in folder.iterdir() if path.name.startswith(UV_ARCHIVE_PREFIX))


def _uv_zip(uv_exe: bytes) -> bytes:
    """O arhivă ca cea oficială pentru Windows: uv.exe la rădăcina ZIP-ului (cu conținutul dat)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("uv.exe", uv_exe)
    return buffer.getvalue()


def _write_versions(folder: Path, uv_version: str, fingerprint: str) -> None:
    """instalare\\versiuni.txt din proiect, cu UV_VERSION = `uv_version` și amprentele Windows = `fingerprint`."""
    text = VERSIONS_FILE.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^UV_VERSION=.*$", f"UV_VERSION={uv_version}", text)
    text = re.sub(r"(?m)^(SHA256_WINDOWS_(?:X64|ARM64))=.*$", lambda match: f"{match.group(1)}={fingerprint}", text)
    (folder / "instalare" / "versiuni.txt").write_bytes(text.encode("utf-8"))


@windows_only
@pytest.mark.parametrize("case", sorted(UV_DOWNLOAD_CASES))
def test_installer_keeps_uv_under_its_version_and_downloads_a_bad_leftover_only_once(tmp_path, fake_github, case):
    """N12 la execuție: arhiva păstrată are versiunea în nume, deci cele rămase de la altă versiune nu contează; una rămasă cu
    altă amprentă se șterge și se descarcă o singură dată din nou; una deja bună nu se descarcă; o arhivă proaspăt descărcată
    cu altă amprentă se șterge și oprește pregătirea, fără a doua descărcare.
    P9: după o dezarhivare reușită se șterg toate arhivele uv-* (și cea folosită), iar altceva din .uv\\descarcari rămâne;
    fără dezarhivare reușită, arhivele de la alte versiuni rămân."""
    present, served, downloads_expected, accepted = UV_DOWNLOAD_CASES[case]
    archives = {"buna": _uv_zip(FAKE_UV_EXE), "alta": _uv_zip(OTHER_UV_EXE)}
    names = {"versiune": _uv_archive_name(INVENTED_UV_VERSION), "veche": _uv_archive_name(OLDER_UV_VERSION), "fara-versiune": f"uv-{_uv_target()}.zip"}
    program = tmp_path / "p"
    program.mkdir()
    _skip_if_installer_refuses_the_path(program)
    fake_github.reset()
    _copy_bats(program, INSTALLER)
    (program / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    _write_versions(program, INVENTED_UV_VERSION, hashlib.sha256(archives["buna"]).hexdigest())
    downloads = program / ".uv" / "descarcari"
    downloads.mkdir(parents=True)
    for kind, archive in present.items():
        (downloads / names[kind]).write_bytes(archives[archive])
    (downloads / UNRELATED_DOWNLOAD).write_bytes(b"nu e o arhiva uv\n")
    fake_github.serve(_uv_url_path(INVENTED_UV_VERSION), archives[served])
    result = _run_bat(program, INSTALLER, "--fara-pauza", extra_env=fake_github.curl_env(tmp_path / "curl_fals"))
    output = _output(result)
    uv_exe = program / ".uv" / "bin" / "uv.exe"
    assert fake_github.requests == [_uv_url_path(INVENTED_UV_VERSION)] * downloads_expected, (
        f"descărcări: {fake_github.requests}, așteptat {downloads_expected}:\n{output}")
    assert result.returncode == 1, output  # și la reușită: uv.exe inventat nu poate face .venv (pasul 2)
    assert (downloads / UNRELATED_DOWNLOAD).is_file(), "curățenia arhivelor uv nu are voie să atingă alte fișiere din .uv\\descarcari"
    if accepted:
        assert "amprenta SHA-256" not in output and NEXT_STEP_MESSAGE in output, output
        assert uv_exe.read_bytes() == FAKE_UV_EXE, "în .uv\\bin trebuie să ajungă uv.exe din arhiva bună"
        assert _uv_archives(downloads) == [], "după o dezarhivare reușită nu rămâne nicio arhivă uv-* (P9), nici cea tocmai folosită"
    else:
        assert "amprenta SHA-256" in output and "NU o folosesc" in output, output
        assert not uv_exe.exists(), "arhiva cu altă amprentă nu se dezarhivează"
        left = sorted(names[kind] for kind in present if kind != "versiune")
        assert _uv_archives(downloads) == left, "arhiva cu altă amprentă se șterge; fără dezarhivare reușită, celelalte rămân (P9)"


@windows_only
def test_installer_refuses_a_folder_whose_path_is_too_long_and_creates_nothing(tmp_path):
    """La execuție: într-un folder cu calea peste limita din instaleaza.bat, scriptul spune să muți folderul și nu descarcă nimic.

    Fără verificarea asta, instalarea reușește, dar la prima rulare Python dă «DLL load failed … filename too long».
    """
    limit = _max_folder_path()
    padding = max(limit + PATH_LIMIT_EXCESS_CHARS - len(str(tmp_path)) - 1, 1)  # -1: separatorul dinaintea folderului nou
    folder = tmp_path / ("x" * padding)
    if not limit < len(str(folder)) < WINDOWS_MAX_PATH_CHARS - CWD_HEADROOM_CHARS:
        pytest.skip(f"calea de test ({len(str(folder))} caractere) nu poate fi făcută mai lungă decât limita {limit} și totuși rulabilă")
    folder.mkdir()
    _copy_bats(folder, INSTALLER)
    (folder / "requirements.txt").write_text("# gol\n", encoding="utf-8")
    before = _listing(folder)
    result = _run_bat(folder, INSTALLER, "--fara-pauza")
    output = _output(result)
    assert result.returncode == 1, output
    assert "prea lungă" in output and "Mută folderul" in output and "Traceback" not in output, output
    assert _listing(folder) == before, "nu are voie să descarce sau să creeze ceva într-un folder cu cale prea lungă"


@windows_only
def test_installer_path_check_accepts_exactly_the_limit_and_refuses_one_more(tmp_path):
    """Verificarea de lungime trece la exact MAX_FOLDER_PATH caractere și pică la unul în plus (greșeala clasică: `<` în loc de `<=`).

    Fără internet: la limită scriptul trece de verificare și se oprește abia la descărcarea lui uv (proxy-ul mort din _run_bat).
    """
    limit = _max_folder_path()
    for extra, expected in ((0, "nu am putut descărca uv"), (1, "prea lungă")):
        padding = limit + extra - len(str(tmp_path / f"p{extra}")) - 1
        if padding < 1:
            pytest.skip(f"folderul temporar al testului are deja {len(str(tmp_path))} caractere: nu pot construi o cale de {limit + extra}")
        folder = tmp_path / f"p{extra}" / ("x" * padding)
        folder.mkdir(parents=True)
        assert len(str(folder)) == limit + extra, f"testul n-a construit calea cerută: {len(str(folder))} în loc de {limit + extra}"
        _copy_bats(folder, INSTALLER)
        (folder / "requirements.txt").write_text("# gol\n", encoding="utf-8")
        output = _output(_run_bat(folder, INSTALLER, "--fara-pauza"))
        assert expected in output, f"cu o cale de {limit + extra} caractere (limita e {limit}) mă așteptam la «{expected}»:\n{output}"


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
    """Pune în `folder/.venv/Scripts/python.exe` un Python funcțional, doar cu biblioteca standard (programele false nu cer mai mult).

    În mediul virtual al proiectului: copia lansatorului lui, cu pyvenv.cfg. În afara unuia (CI cu setup-python): un mediu
    virtual nou, fără pip. Sare testul dacă nici așa nu apare python.exe.
    """
    if sys.prefix != sys.base_prefix and (Path(sys.prefix) / "pyvenv.cfg").is_file():
        (folder / ".venv" / "Scripts").mkdir(parents=True)
        shutil.copy(sys.executable, folder / ".venv" / "Scripts" / "python.exe")
        shutil.copy(Path(sys.prefix) / "pyvenv.cfg", folder / ".venv" / "pyvenv.cfg")
    else:
        venv.create(folder / ".venv", with_pip=False)
    if not (folder / ".venv" / "Scripts" / "python.exe").is_file():
        pytest.skip("nu pot pregăti un .venv funcțional aici")


def _stub_program(folder: Path) -> None:
    """Un ruleaza.py fals care doar spune ce argumente a primit (nu pornește nimic)."""
    (folder / "ruleaza.py").write_text("import sys\nprint('ARGUMENTE-PRIMITE:', ' '.join(sys.argv[1:]))\n", encoding="utf-8")


def _stub_installer(folder: Path, code: int) -> None:
    """Un instaleaza.bat fals care spune ce argumente a primit și iese cu `code` (fără descărcări)."""
    (folder / INSTALLER).write_bytes(f"@echo off\r\necho INSTALATOR-ARGUMENTE: %*\r\nexit /b {code}\r\n".encode("utf-8"))


@windows_only
def test_porneste_prepares_then_starts_the_application(tmp_path):
    """porneste.bat cheamă pregătirea cu --fara-pauza, apoi pornește `ruleaza.py --aplicatie`; la oprire normală iese cu 0."""
    _copy_bats(tmp_path, "porneste.bat")
    _stub_installer(tmp_path, 0)
    _stub_program(tmp_path)
    _copy_venv_python(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 0, output
    assert "INSTALATOR-ARGUMENTE: --fara-pauza" in output and "ARGUMENTE-PRIMITE: --aplicatie" in output and "Traceback" not in output, output


@windows_only
def test_porneste_passes_the_users_arguments_instead_of_the_application(tmp_path):
    """Cu argumente (ex. porneste.bat --demo), porneste.bat le pasează la ruleaza.py și nu mai pornește aplicația."""
    _copy_bats(tmp_path, "porneste.bat")
    _stub_installer(tmp_path, 0)
    _stub_program(tmp_path)
    _copy_venv_python(tmp_path)
    output = _output(_run_bat(tmp_path, "porneste.bat", "--demo"))
    assert "ARGUMENTE-PRIMITE: --demo" in output and "--aplicatie" not in output, output


@windows_only
def test_porneste_stops_with_exit_code_1_when_preparation_fails_and_never_starts_the_app(tmp_path):
    """Dacă pregătirea pică, porneste.bat iese cu 1 și cu mesaj, fără să pornească aplicația."""
    _copy_bats(tmp_path, "porneste.bat")
    _stub_installer(tmp_path, 1)
    _stub_program(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 1, output
    assert "INSTALATOR-ARGUMENTE: --fara-pauza" in output and "Pregătirea nu s-a terminat" in output, output
    assert "ARGUMENTE-PRIMITE" not in output


@windows_only
def test_porneste_passes_a_nonzero_exit_code_of_the_application_through(tmp_path):
    """Dacă aplicația iese cu eroare, porneste.bat spune că s-a oprit cu o eroare și iese cu același cod (nu îl pierde)."""
    _copy_bats(tmp_path, "porneste.bat")
    _stub_installer(tmp_path, 0)
    (tmp_path / "ruleaza.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    _copy_venv_python(tmp_path)
    result = _run_bat(tmp_path, "porneste.bat")
    output = _output(result)
    assert result.returncode == 7 and "s-a oprit cu o eroare" in output, output


@windows_only
def test_installer_with_the_flag_does_not_wait_for_a_key(tmp_path):
    """Cu --fara-pauza instaleaza.bat iese fără `pause` (nu așteaptă o tastă); fără argument textul e același, plus cererea de tastă."""
    shutil.copy(PROJECT_ROOT / INSTALLER, tmp_path / INSTALLER)
    plain = _output(_run_bat(tmp_path, INSTALLER))
    flagged_result = _run_bat(tmp_path, INSTALLER, "--fara-pauza")
    flagged = _output(flagged_result)
    assert flagged_result.returncode == 1, flagged
    assert "Extract All" in flagged and plain.startswith(flagged.rstrip()) and len(plain) > len(flagged.rstrip()), (
        f"cu --fara-pauza nu trebuia să apară cererea de tastă.\nfără argument:\n{plain!r}\ncu argument:\n{flagged!r}")


# ---------- D12/D13 la execuție: lansatorul înlocuit cât rulează Python, ca la o actualizare din aplicație ----------

# Python-ul fals (ruleaza.py rulat de o copie a interpretorului testelor): la primul apel înlocuiește lansatorul cu varianta
# nouă pregătită de test (os.replace, exact ca actualizarea reală), apoi iese cu codurile din plan.json, în ordine (la
# repornire: 75, apoi codul variantei noi). Fiecare apel se notează în apeluri.txt, cu argumentele lui.
FAKE_UPDATING_PROGRAM = '''\
import json
import os
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
plan = json.loads((here / "plan.json").read_text(encoding="utf-8"))
calls = here / "apeluri.txt"
earlier = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
with calls.open("a", encoding="utf-8") as file:
    file.write(" ".join(sys.argv[1:]) + "\\n")
if not earlier:
    os.replace(here / "varianta_noua.tmp", here / plan["launcher"])
code = plan["codes"][len(earlier)]
print("PYTHON-FALS", len(earlier) + 1, "IESE CU", code)
raise SystemExit(code)
'''
# Rândurile puse la începutul variantei noi (deplasează tot restul). Ocupă cel puțin cât lansatorul vechi, deci un cmd care ar
# citi mai departe de la poziția veche ar nimeri în ele și ar afișa încă o dată ultimul lor rând: așa se vede orice comandă
# „străină”, chiar și una tăiată la jumătate.
NEW_VARIANT_LINE = "echo VARIANTA-NOUA-RAND-{:04d}"
# Codurile încercate: succes, eroare, o eroare oarecare (codul trebuie să ajungă neschimbat) și „actualizat, pornește din nou”.
REPLACEMENT_EXIT_CODES = (0, 1, 7, RESTART_EXIT_CODE)
# Codul cu care iese varianta nouă după repornire: 0 și unul nenul, ca să se vadă că ajunge neschimbat prin tot lanțul.
AFTER_RESTART_EXIT_CODES = (0, 7)
# Mesajele din instalare\dupa_rulare.bat: (la succes, la eroare); None = lansatorul nu spune nimic la succes.
AFTER_RUN_MESSAGES = {
    "porneste": ("Gata. Rezultatele rămân în folderul iesiri.", "Programul s-a oprit cu o eroare."),
    "ruleaza": ("Gata. Raportul s-a deschis în browser", "Rularea s-a oprit cu o eroare."),
    "login": ("Pasul următor: ruleaza.bat", "Login-ul nu s-a încheiat cu succes."),
    "demo": ("Gata. Raportul demonstrativ", "Demonstrația s-a oprit cu o eroare."),
    "sterge_sesiunea": (None, "Sesiunea nu a fost ștearsă"),
}
RESTART_MESSAGE = "Programul a fost actualizat. Pornesc versiunea nouă"
RUN_AGAIN_MESSAGE = "Programul a fost actualizat; pornește-l din nou."


def _replacement_cases() -> list[tuple[str, tuple[int, ...]]]:
    """(lansator, codurile lui Python în ordine) pentru testul D13; la porneste.bat, 75 e urmat de rularea variantei noi."""
    cases = []
    for name in PYTHON_LAUNCHERS:
        for code in REPLACEMENT_EXIT_CODES:
            if name == RESTARTING_LAUNCHER and code == RESTART_EXIT_CODE:
                cases.extend((name, (code, after)) for after in AFTER_RESTART_EXIT_CODES)
            else:
                cases.append((name, (code,)))
    return cases


def _run_replaced_launcher(folder: Path, name: str, launcher: bytes, codes: tuple[int, ...]) -> tuple[subprocess.CompletedProcess, list[str], int, int]:
    """Rulează lansatorul `name` (conținut `launcher`) cu Python-ul fals care îl înlocuiește cât rulează.

    Varianta nouă = rândurile-marcaj + lansatorul. Întoarce (rezultatul, argumentele fiecărui apel Python, de câte ori s-a
    afișat primul rând-marcaj, de câte ori ultimul).
    """
    _copy_bats(folder)
    (folder / name).write_bytes(launcher)
    _stub_installer(folder, 0)
    _copy_venv_python(folder)
    (folder / "ruleaza.py").write_text(FAKE_UPDATING_PROGRAM, encoding="utf-8")
    (folder / "plan.json").write_text(json.dumps({"launcher": name, "codes": list(codes)}), encoding="utf-8")
    line_bytes = len(NEW_VARIANT_LINE.format(1)) + 2  # + CRLF
    count = len(launcher) // line_bytes + 2  # rândurile-marcaj acoperă tot lansatorul vechi, cu un rând în plus
    block = "".join(NEW_VARIANT_LINE.format(i) + "\r\n" for i in range(1, count + 1)).encode("ascii")
    (folder / "varianta_noua.tmp").write_bytes(b"@echo off\r\n" + block + launcher)
    result = _run_bat(folder, name)
    shown = [line.strip() for line in _output(result).splitlines()]
    calls = (folder / "apeluri.txt").read_text(encoding="utf-8").splitlines() if (folder / "apeluri.txt").exists() else []
    first, last = NEW_VARIANT_LINE.format(1)[5:], NEW_VARIANT_LINE.format(count)[5:]  # fără «echo »
    return result, calls, shown.count(first), shown.count(last)


@windows_only
@pytest.mark.parametrize("name, codes", _replacement_cases(), ids=lambda value: str(value))
def test_launcher_replaced_while_python_runs_finishes_cleanly_with_the_exact_code(tmp_path, name, codes):
    """D13: lansatorul suprascris cât rulează Python (ca la o actualizare) se termină curat, fără comenzi din fișierul nou, cu codul exact.

    La 75, porneste.bat pornește varianta nouă de la început (care reface pregătirea), iar codul ei ajunge neschimbat la final;
    ceilalți lansatori spun să fie porniți din nou.
    """
    result, calls, first, last = _run_replaced_launcher(tmp_path, name, (PROJECT_ROOT / name).read_bytes(), codes)
    output = _output(result)
    fresh_starts = len(codes) - 1  # de câte ori trebuie să ruleze varianta nouă de la început: doar la repornire
    assert result.returncode == codes[-1], f"cod {result.returncode}, așteptat {codes[-1]}:\n{output}"
    assert result.stderr == b"", f"cmd a scris erori (comenzi străine executate?):\n{output}"
    assert (first, last) == (fresh_starts, fresh_starts), (
        f"rândurile variantei noi s-au afișat de {first}/{last} ori, așteptat {fresh_starts}: cmd a citit din fișierul înlocuit:\n{output}")
    assert len(calls) == len(codes), f"Python a pornit de {len(calls)} ori, așteptat {len(codes)}: {calls}\n{output}"
    if fresh_starts:
        assert calls == ["--aplicatie"] * len(codes), calls
        assert RESTART_MESSAGE in output and output.count("INSTALATOR-ARGUMENTE: --fara-pauza") == len(codes), (
            f"la repornire varianta nouă trebuie să refacă pregătirea:\n{output}")
    elif codes[0] == RESTART_EXIT_CODE:
        assert RUN_AGAIN_MESSAGE in output, output


@windows_only
def test_replacement_harness_catches_a_launcher_that_reads_its_file_after_python(tmp_path):
    """Calibrare: același ham, pe un lansator în forma veche (rânduri după Python), vede comenzile citite din fișierul nou."""
    old_style = _crlf("@echo off", "chcp 65001 >nul", 'cd /d "%~dp0"', ENV_CALL, VENV_PYTHON + " ruleaza.py --demo",
                      'set "COD=%ERRORLEVEL%"', "echo Gata.", "pause", "exit /b %COD%")
    result, calls, first, last = _run_replaced_launcher(tmp_path, "vechi.bat", old_style, (7,))
    assert last >= 1 and first == 0, f"hamul n-a văzut citirea din fișierul nou (început {first}, sfârșit {last}):\n{_output(result)}"


@windows_only
@pytest.mark.parametrize("launcher", sorted(AFTER_RUN_MESSAGES))
@pytest.mark.parametrize("code", REPLACEMENT_EXIT_CODES)
def test_after_run_helper_shows_the_launchers_message_and_keeps_the_exact_code(tmp_path, launcher, code):
    """instalare\\dupa_rulare.bat: mesajul potrivit lansatorului și codului, apoi iese cu exact codul primit."""
    shutil.copy(AFTER_RUN_BAT, tmp_path / "dupa_rulare.bat")
    result = _run_bat(tmp_path, "dupa_rulare.bat", launcher, str(code))
    output = _output(result)
    success, failure = AFTER_RUN_MESSAGES[launcher]
    assert result.returncode == code and result.stderr == b"", output
    if code == 0:
        assert (success is None or success in output) and failure not in output, output
    elif code == RESTART_EXIT_CODE:
        expected = RESTART_MESSAGE if f"{launcher}.bat" == RESTARTING_LAUNCHER else RUN_AGAIN_MESSAGE
        assert expected in output and failure not in output, output
    else:
        assert failure in output and (success is None or success not in output), output


@windows_only
def test_after_run_helper_skips_the_pause_only_when_porneste_restarts(tmp_path):
    """La 75, porneste nu așteaptă tasta (porneste.bat pornește singur varianta nouă, care așteaptă la final); ceilalți așteaptă.

    Pauza afișează un rând (textul depinde de limba Windows): la repornire, ultimul rând trebuie să fie mesajul, nu pauza.
    """
    shutil.copy(AFTER_RUN_BAT, tmp_path / "dupa_rulare.bat")
    restarting = [line for line in _output(_run_bat(tmp_path, "dupa_rulare.bat", "porneste", str(RESTART_EXIT_CODE))).splitlines() if line.strip()]
    waiting = [line for line in _output(_run_bat(tmp_path, "dupa_rulare.bat", "ruleaza", str(RESTART_EXIT_CODE))).splitlines() if line.strip()]
    assert restarting[-1].startswith(RESTART_MESSAGE), f"la repornire nu trebuie pauză: {restarting}"
    assert waiting[-1] != RUN_AGAIN_MESSAGE and RUN_AGAIN_MESSAGE in waiting, f"ceilalți lansatori trebuie să aștepte o tastă: {waiting}"


# ---------- P1 la execuție: recuperarea înaintea pregătirii, cu programe false ----------

# Recuperarea falsă (emag_spend/update_recovery.py în folderul testului, rulată cu `python -m`): spune că a rulat, face ce scrie în
# recuperare.json (înlocuiește lansatorul cu varianta nouă, lasă sau nu jurnalul) și iese cu codul cerut.
FAKE_RECOVERY = '''\
import json
import os
import sys
from pathlib import Path

here = Path(__file__).resolve().parents[1]
plan = json.loads((here / "recuperare.json").read_text(encoding="utf-8"))
print("RECUPERARE-FALSA", " ".join(sys.argv[1:]))
if plan["replace"]:
    os.replace(here / "varianta_noua.tmp", here / plan["replace"])
if not plan["journal_stays"]:
    os.remove(here / ".actualizare" / "jurnal.json")
raise SystemExit(plan["code"])
'''
RECOVERY_SHOWN = "RECUPERARE-FALSA"
INSTALLER_SHOWN = "INSTALATOR-ARGUMENTE: --fara-pauza"
PROGRAM_SHOWN = "ARGUMENTE-PRIMITE: --aplicatie"
RECOVERY_FAILED_MESSAGE = "Pornirea s-a oprit"
RECOVERY_ERROR_CODE = 1  # singurul cod la care porneste.bat se oprește după recuperare (P1)
OTHER_RECOVERY_CODE = 3  # orice alt cod (de exemplu Python-ul din .venv care nu pornește): se merge mai departe, ca înainte de P1


def _stub_recovery(folder: Path, code: int, *, journal_stays: bool = False, replace: str | None = None) -> None:
    """Pune în `folder` jurnalul unei aplicări întrerupte și recuperarea falsă (FAKE_RECOVERY) care iese cu `code`."""
    (folder / "emag_spend").mkdir()
    (folder / "emag_spend" / "__init__.py").write_bytes(b"")
    (folder / "emag_spend" / "update_recovery.py").write_text(FAKE_RECOVERY, encoding="utf-8")
    (folder / "recuperare.json").write_text(json.dumps({"code": code, "journal_stays": journal_stays, "replace": replace}), encoding="utf-8")
    (folder / ".actualizare").mkdir()
    (folder / ".actualizare" / "jurnal.json").write_text('{"inventat": true}\n', encoding="utf-8")


def _recovering_launcher(folder: Path, code: int, **recovery) -> tuple[subprocess.CompletedProcess, str]:
    """porneste.bat real, cu instalatorul, programul și recuperarea false; întoarce (rezultatul, ieșirea)."""
    _copy_bats(folder, RECOVERING_LAUNCHER)
    _stub_installer(folder, 0)
    _stub_program(folder)
    _copy_venv_python(folder)
    _stub_recovery(folder, code, **recovery)
    result = _run_bat(folder, RECOVERING_LAUNCHER)
    return result, _output(result)


def _order(output: str, *marks: str) -> list[int]:
    """Pozițiile primei apariții a fiecărui semn în ieșire (-1 dacă lipsește), ca să se vadă ordinea în care au rulat."""
    return [output.find(mark) for mark in marks]


@windows_only
def test_porneste_recovers_an_interrupted_update_before_preparing(tmp_path):
    """P1: cu jurnal și .venv, recuperarea rulează ÎNAINTEA pregătirii, o singură dată, apoi pregătirea și programul; cod 0."""
    result, output = _recovering_launcher(tmp_path, 0)
    recovery, installer, program = _order(output, RECOVERY_SHOWN, INSTALLER_SHOWN, PROGRAM_SHOWN)
    assert result.returncode == 0 and result.stderr == b"", output
    assert -1 < recovery < installer < program, f"ordinea trebuie să fie recuperare, pregătire, program:\n{output}"
    assert output.count(RECOVERY_SHOWN) == 1 and output.count(INSTALLER_SHOWN) == 1 and output.count(PROGRAM_SHOWN) == 1, output
    recovery_lines = [line.strip() for line in output.splitlines() if RECOVERY_SHOWN in line]
    assert recovery_lines == [RECOVERY_SHOWN] and "Traceback" not in output, f"recuperarea nu primește argumentele utilizatorului:\n{output}"


@windows_only
def test_porneste_stops_with_the_message_when_the_recovery_fails(tmp_path):
    """P1: la codul 1 al recuperării porneste.bat se oprește cu mesaj și cod 1, fără pregătire și fără program."""
    result, output = _recovering_launcher(tmp_path, RECOVERY_ERROR_CODE, journal_stays=True)
    assert result.returncode == RECOVERY_ERROR_CODE, output
    assert RECOVERY_SHOWN in output and RECOVERY_FAILED_MESSAGE in output, output
    assert INSTALLER_SHOWN not in output and "ARGUMENTE-PRIMITE" not in output, f"după o recuperare eșuată nu se pregătește nimic:\n{output}"


@windows_only
@pytest.mark.parametrize("code, journal_stays", [(0, True), (OTHER_RECOVERY_CODE, True), (OTHER_RECOVERY_CODE, False)],
                         ids=("jurnal-ramas", "alt-cod", "alt-cod-fara-jurnal"))
def test_porneste_tries_the_recovery_only_once_and_otherwise_goes_on_as_before(tmp_path, code, journal_stays):
    """P1: un jurnal care rămâne după recuperare sau alt cod decât 1 nu repornesc porneste.bat la nesfârșit: recuperarea
    rulează o dată, apoi pregătirea și programul, ca înainte (recuperarea o mai încearcă ruleaza.py); semnul nu ajunge la program."""
    result, output = _recovering_launcher(tmp_path, code, journal_stays=journal_stays)
    assert result.returncode == 0, output
    assert output.count(RECOVERY_SHOWN) == 1, f"recuperarea trebuia încercată o singură dată:\n{output}"
    assert output.count(INSTALLER_SHOWN) == 1 and output.count(PROGRAM_SHOWN) == 1 and RECOVERY_FAILED_MESSAGE not in output, output


@windows_only
@pytest.mark.parametrize("journal, venv", [(False, True), (True, False)], ids=("fara-jurnal", "fara-venv"))
def test_porneste_without_a_journal_or_a_venv_prepares_first_as_before(tmp_path, journal, venv):
    """P1: fără jurnal nu rulează nicio recuperare; fără .venv pregătirea merge întâi (o pregătire eșuată oprește, ca înainte)."""
    _copy_bats(tmp_path, RECOVERING_LAUNCHER)
    _stub_installer(tmp_path, 0 if venv else 1)
    _stub_program(tmp_path)
    if venv:
        _copy_venv_python(tmp_path)
    _stub_recovery(tmp_path, 0)
    if not journal:
        (tmp_path / ".actualizare" / "jurnal.json").unlink()
    result = _run_bat(tmp_path, RECOVERING_LAUNCHER)
    output = _output(result)
    assert RECOVERY_SHOWN not in output and INSTALLER_SHOWN in output, output
    assert result.returncode == (0 if venv else 1), output


@windows_only
def test_porneste_replaced_by_the_recovery_starts_again_from_the_beginning(tmp_path):
    """P1 + D13: recuperarea înlocuiește porneste.bat (ca la revenirea unui lansator nou la cel vechi); cmd nu citește nimic din
    fișierul nou de la poziția veche: porneste.bat pornește din nou de la început, o singură dată, apoi pregătirea și programul."""
    launcher = (PROJECT_ROOT / RECOVERING_LAUNCHER).read_bytes()
    line_bytes = len(NEW_VARIANT_LINE.format(1)) + 2  # + CRLF
    count = len(launcher) // line_bytes + 2  # rândurile-marcaj acoperă tot lansatorul vechi, cu un rând în plus
    block = "".join(NEW_VARIANT_LINE.format(i) + "\r\n" for i in range(1, count + 1)).encode("ascii")
    (tmp_path / "varianta_noua.tmp").write_bytes(b"@echo off\r\n" + block + launcher)
    result, output = _recovering_launcher(tmp_path, 0, replace=RECOVERING_LAUNCHER)
    shown = [line.strip() for line in output.splitlines()]
    first, last = NEW_VARIANT_LINE.format(1)[5:], NEW_VARIANT_LINE.format(count)[5:]  # fără «echo »
    assert result.returncode == 0 and result.stderr == b"", f"cmd a scris erori (comenzi străine executate?):\n{output}"
    assert (shown.count(first), shown.count(last)) == (1, 1), f"varianta nouă trebuia citită o dată, de la început:\n{output}"
    assert output.count(RECOVERY_SHOWN) == 1 and output.count(INSTALLER_SHOWN) == 1 and output.count(PROGRAM_SHOWN) == 1, output


# ---------- P1 cap-coadă: actualizare reală oprită după versiuni.txt, apoi porneste.bat și instaleaza.bat reale, fără internet ----------

# Versiunile lui uv din test sunt inventate: E2E_UV_VERSION e cea „instalată” (uv-ul fals o raportează), E2E_NEW_UV_VERSION cea cerută
# de versiunea nouă (instaleaza.bat ar descărca-o, dar proxy-ul e mort: „rețea indisponibilă”).
E2E_UV_VERSION = "9.8.7"
E2E_NEW_UV_VERSION = "9.8.8"
TEST_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"
NEXT_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor + 1}"  # Python-ul cerut de versiunea nouă: uv-ul fals nu-l poate aduce
# Ce schimbă versiunea nouă în instalare\versiuni.txt: fiecare face pregătirea să pice fără internet, pe arborele amestecat.
NEW_RELEASE_CHANGES = {"uv-nou": {"UV_VERSION": E2E_NEW_UV_VERSION}, "python-nou": {"PYTHON_VERSION": NEXT_PYTHON}}
# uv fals pentru Windows (un .exe făcut cu ScriptMaker din distlib-ul lui pip, ca scripturile instalate de pip): la --version spune
# versiunea, orice altă comandă pică (nu descarcă și nu creează nimic).
FAKE_UV_SCRIPT = """#!python
import sys
if sys.argv[1:] == ["--version"]:
    print("uv {version} (fals)")
    raise SystemExit(0)
print("uv fals: nu pot face", " ".join(sys.argv[1:]))
raise SystemExit(2)
"""
# Folderele care se schimbă oricum la o pornire: lucrul actualizării (rămâne doar lacat) și jurnalele (recuperarea lasă urmă, §9).
CHANGING_DIRS = (".actualizare", "logs")


def _fake_uv_exe(folder: Path, version: str, work: Path) -> None:
    """Pune în `folder` un uv.exe fals (FAKE_UV_SCRIPT) care raportează `version`; sursa lui stă în `work`, în afara programului."""
    try:
        from pip._vendor.distlib.scripts import ScriptMaker
    except ImportError:
        pytest.skip("pip (cu distlib) nu e instalat aici: nu pot face un uv.exe fals")
    source = work / "uv_fals_sursa"
    source.mkdir()
    (source / "uv").write_text(FAKE_UV_SCRIPT.format(version=version), encoding="utf-8")
    folder.mkdir(parents=True, exist_ok=True)
    maker = ScriptMaker(str(source), str(folder))
    maker.executable = sys.executable
    maker.variants = {""}
    maker.make("uv")
    if not (folder / "uv.exe").is_file():
        pytest.skip("distlib nu a făcut uv.exe aici")


def _ready_environment(root: Path, work: Path) -> None:
    """Mediu gata, ca după o primă pornire, fără internet: uv fals în versiunea din versiuni.txt, .venv cu Python-ul testelor și
    pachetele lor (printr-un .pth), amprenta cerințelor potrivită și browserul marcat gata. Așa instaleaza.bat real nu are ce face."""
    _copy_venv_python(root)
    site_packages = root / ".venv" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    paths = sysconfig.get_paths()
    (site_packages / "zz_pachete_teste.pth").write_text("".join(f"{path}\n" for path in {paths["purelib"], paths["platlib"]}), encoding="utf-8")
    _fake_uv_exe(root / ".uv" / "bin", E2E_UV_VERSION, work)
    (root / ".venv" / "cerinte.sha256").write_text(hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest() + "\n", encoding="ascii")
    (root / ".uv" / "browser.ok").write_bytes(b"")


@windows_only
@pytest.mark.parametrize("change", sorted(NEW_RELEASE_CHANGES))
def test_porneste_recovers_a_real_interrupted_update_offline_before_the_real_installer(tmp_path, change):
    """P1 cap-coadă (V1-1): actualizarea reală e oprită brusc imediat după instalare\\versiuni.txt (schimbat de versiunea nouă), apoi
    porneste.bat real, fără internet: revine la versiunea veche ÎNAINTEA lui instaleaza.bat, afișează versiunea veche, cod 0,
    mesajul revenirii o dată, arborele identic cu cel dinainte și în .actualizare doar lacat. Înainte de P1: cod 1, pregătire picată."""
    root = tmp_path / "p"
    root.mkdir()
    _skip_if_installer_refuses_the_path(root)
    files = install_versions(root, copy_program(root), UV_VERSION=E2E_UV_VERSION, PYTHON_VERSION=TEST_PYTHON)
    _ready_environment(root, tmp_path)
    shown = f"{ruleaza.PROGRAM_NAME} {VERSION}"
    calibration = _run_bat(root, RECOVERING_LAUNCHER, "--versiune")
    assert calibration.returncode == 0 and shown in _output(calibration), f"mediul pregătit nu merge fără internet:\n{_output(calibration)}"
    before = fingerprint(root, skip=CHANGING_DIRS)
    archive = tmp_path / "lansare.zip"
    version, new_versions = release_with_versions(archive, files, **NEW_RELEASE_CHANGES[change])
    interrupt_update(root, archive, version, new_versions, tmp_path)
    result = _run_bat(root, RECOVERING_LAUNCHER, "--versiune")
    output = _output(result)
    assert result.returncode == 0, f"cod {result.returncode}:\n{output}"
    assert shown in output and f"{ruleaza.PROGRAM_NAME} {version}" not in output, output
    assert output.count(MESSAGE_RECOVERED.format(to_version=version, from_version=VERSION)) == 1, output
    assert "Pregătirea nu s-a terminat" not in output and "EROARE" not in output, output
    assert fingerprint(root, skip=CHANGING_DIRS) == before, "după recuperare, programul trebuie să fie exact cel dinainte de actualizare"
    assert work_dir_leftovers(root) == [], "în .actualizare trebuie să rămână doar lacat"


# ---------- D15: .venv refăcut când Python-ul din el are altă versiune decât PYTHON_VERSION ----------

def _venv_check_line() -> str:
    """Rândul din instaleaza.bat care decide dacă .venv e bun (pune VENV_BUN)."""
    lines = [line for line in (PROJECT_ROOT / INSTALLER).read_text(encoding="utf-8").splitlines() if 'set "VENV_BUN=1"' in line]
    assert len(lines) == 1, f"instaleaza.bat trebuie să aibă un singur rând care pune VENV_BUN, găsite {lines}"
    return lines[0]


def test_installer_checks_the_python_version_of_the_venv():
    """Verificarea lui .venv din instaleaza.bat primește PYTHON_VERSION ca argument (nu lipit în codul Python) și compară major.minor."""
    line = _venv_check_line()
    assert '"%PY%" -c "' in line and "sys.version_info[:2]" in line and "%PYTHON_VERSION%" in line, line
    assert "'%PYTHON_VERSION%'" not in line, "versiunea se dă ca argument, nu în interiorul codului Python"


@windows_only
@pytest.mark.parametrize("same_version", (True, False), ids=("aceeasi-versiune", "alta-versiune"))
def test_installer_keeps_the_venv_only_when_its_python_has_the_pinned_version(tmp_path, same_version):
    """D15 la execuție: rândul real din instaleaza.bat păstrează .venv cu Python-ul fixat și îl dă la refăcut când major.minor diferă."""
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    pinned = current if same_version else f"{sys.version_info.major}.{sys.version_info.minor - 1}"
    (tmp_path / "verifica.bat").write_bytes(_crlf(
        "@echo off", 'set "FAIL="', f'set "PY={sys.executable}"', f'set "PYTHON_VERSION={pinned}"', 'set "VENV_BUN="',
        _venv_check_line(), "if defined VENV_BUN echo VENV-BUN", "if not defined VENV_BUN echo VENV-DE-REFACUT"))
    output = _output(_run_bat(tmp_path, "verifica.bat"))
    assert ("VENV-BUN" if same_version else "VENV-DE-REFACUT") in output, f"Python {current}, fixat {pinned}:\n{output}"


def test_every_launcher_is_covered_by_the_static_rules():
    """Un .bat nou în rădăcină intră automat în testele statice; dacă pornește Python, trebuie adăugat la PYTHON_LAUNCHERS."""
    unknown = [p.name for p in BAT_FILES if p.name not in REQUIRED_BAT_NAMES]
    for name in unknown:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8").lower()
        assert "python" not in text, f"{name} pornește Python, dar nu e în PYTHON_LAUNCHERS din {Path(__file__).name}: adaugă-l ca să i se aplice și regulile de lansator."
