"""Garda de parole și date personale: programul nu tastează parole, nu citește cookie-uri și nu urcă secrete.

Primește: sursele programului și tot ce urmează să urce în git (`git ls-files` sau, fără git, parcurgere cu .gitignore).
Verifică: (1) în cod (AST) nu există tastare în pagini (fill, type, press...), citire de cookie-uri, ascultarea
cererilor sau selectori de câmpuri de parolă; (2) singurele variabile de mediu citite sunt cele EMAG_* din lista albă;
(3) niciun fișier de urcat nu conține chei, token-uri, IBAN, CNP, telefoane, e-mailuri sau numele contului de Windows;
(4) nu urcă nume de fișiere cu date personale (sesiune, rezultate, cookie-uri) și .gitignore le acoperă.
Fiecare detector e probat pe date-capcană. În mesaje, valorile găsite sunt mascate: jurnalul de CI nu trebuie să le repete.
"""

import ast
import getpass
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from emag_spend import settings
from tests.garda_support import (
    GitIgnore, PROJECT_ROOT, dotted_name, files_to_publish, matches_any, parent_map, parse_source, program_sources,
    read_text_or_none, relative, string_constants, walk_respecting_gitignore,
)

# ---------- (1) programul nu poate tasta parole sau citi sesiunea ----------

# Metode de pagină care scriu în câmpuri sau acționează ca o tastatură: cu ele programul ar putea completa o parolă.
FORBIDDEN_INPUT_METHODS = frozenset({
    "fill", "type", "press", "press_sequentially", "check", "uncheck", "set_checked", "set_input_files", "select_option",
    "dispatch_event", "insert_text", "tap",
})
# Atribute prin care programul ar citi sesiunea (cookie-uri, stare salvată), ar copia date din cereri sau ar tasta.
FORBIDDEN_ATTRIBUTES = frozenset({
    "keyboard", "clipboard", "cookies", "storage_state", "add_cookies", "clear_cookies", "post_data", "post_data_buffer", "post_data_json",
})
# Ascultători de evenimente care ar vedea cererile sau fișierele: programul nu are nevoie de ele.
FORBIDDEN_EVENT_NAMES = frozenset({"request", "response", "requestfinished", "requestfailed", "websocket", "download", "filechooser"})
FORBIDDEN_EVENT_METHODS = frozenset({"on", "once", "add_listener", "expect_event"})
FORBIDDEN_WAIT_METHODS = frozenset({"expect_request", "expect_response", "expect_download", "expect_file_chooser", "wait_for_request", "wait_for_response"})
# Cod JavaScript (trimis la page.evaluate) care ar citi sesiunea sau parole din pagină.
CREDENTIAL_ACCESS_PATTERNS = (
    (r"document\s*\.\s*cookie", "document.cookie"), (r"\blocalStorage\b", "localStorage"), (r"\bsessionStorage\b", "sessionStorage"),
    (r"\bindexedDB\b", "indexedDB"), (r"navigator\s*\.\s*credentials|\bPasswordCredential\b", "API-ul de credențiale"),
    (r"""type\s*=\s*['"]?password|input\[[^\]]*password|autocomplete\s*=\s*['"]?(?:current|new)-password""", "selector de câmp de parolă"),
    (r"\.\s*value\s*=(?!=)", "scriere într-un câmp (.value =)"), (r"\bdispatchEvent\b|\bexecCommand\b|\binsertText\b", "tastare simulată în pagină"),
)


def python_credential_violations(tree: ast.Module, filename: str) -> list[str]:
    """Încălcările de tip parolă/sesiune dintr-un fișier Python (AST), ca mesaje în română; listă goală = curat."""
    problems = []

    def add(node: ast.AST, why: str) -> None:
        """Adaugă o încălcare cu fișierul și linia nodului."""
        problems.append(f"{filename}:{node.lineno}: {why}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                add(node, f".{node.attr}: programul nu are voie să tasteze, să citească cookie-uri sau să copieze date din cereri; autentificarea o face utilizatorul, manual, în browser")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method in FORBIDDEN_INPUT_METHODS:
                add(node, f".{method}(): apel care scrie în pagină sau apasă taste; cu el programul ar putea completa o parolă, iar parola nu trebuie să treacă prin program")
            if method in FORBIDDEN_WAIT_METHODS:
                add(node, f".{method}(): ascultă cererile sau fișierele browserului; ar putea vedea parole sau cookie-uri")
            if method in FORBIDDEN_EVENT_METHODS and node.args and isinstance(node.args[0], ast.Constant) \
                    and str(node.args[0].value).lower() in FORBIDDEN_EVENT_NAMES:
                add(node, f".{method}(\"{node.args[0].value}\"): ascultă traficul browserului; ar putea vedea parole trimise la login")
    for line, text, is_docstring in string_constants(tree):
        if is_docstring:
            continue
        for pattern, label in CREDENTIAL_ACCESS_PATTERNS:
            if re.search(pattern, text):
                problems.append(f"{filename}:{line}: textul conține {label}: un script trimis la page.evaluate ar putea citi sesiunea sau parole din pagină")
    return problems


# ---------- (2) variabile de mediu ----------

# Singurele variabile de mediu pe care are voie să le citească programul, cu rostul fiecăreia. Orice altă citire
# (PATH, USERNAME, TOKEN, chei din mediu) ar putea scoate secrete din calculatorul utilizatorului.
ALLOWED_ENV_VARS = {
    "EMAG_BROWSER_CHANNEL": "alege browserul instalat (msedge sau chrome)",
    "EMAG_PROFILE_DIR": "alege folderul profilului cu sesiunea eMAG",
    "EMAG_FETCH_CONCURRENCY": "câte pagini se cer simultan",
    "EMAG_LOGIN_WAIT_SECONDS": "cât așteaptă login-ul manual",
    "EMAG_APP_IDLE_MINUTES": "după câte minute fără cereri se oprește singură aplicația locală",
    "EMAG_UPDATE_CHECK": "oprește (cu «0») verificarea automată a versiunii noi la pornirea aplicației locale (decis 5 oct. 2026, D2)",
}
ENV_ACCESS_NAMES = frozenset({"os.environ", "os.environb", "os.getenv", "os.getenvb", "os.putenv", "os.unsetenv"})


def env_reads(tree: ast.Module, filename: str) -> tuple[set[str], list[str]]:
    """(variabilele citite cu cheie literală, încălcări) dintr-un fișier Python; orice folosire neanalizabilă e încălcare."""
    parents = parent_map(tree)
    keys: set[str] = set()
    problems: list[str] = []

    def add(node: ast.AST, why: str) -> None:
        """Adaugă o încălcare cu fișierul și linia nodului."""
        problems.append(f"{filename}:{node.lineno}: {why}")

    def literal_key(node: ast.AST | None) -> str | None:
        """Valoarea text a unui literal, sau None dacă nodul nu e un literal text."""
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os" and any(a.name in {"environ", "getenv", "environb", "getenvb", "putenv"} for a in node.names):
            add(node, "importă environ/getenv direct din os: citirile de mediu trebuie să se vadă ca os.environ[...] ca să poată fi verificate")
        if not isinstance(node, ast.Attribute) or dotted_name(node) not in ENV_ACCESS_NAMES:
            continue
        name, parent = dotted_name(node), parents.get(node)
        key = None
        if name == "os.environ" and isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, ast.Load):
            key = literal_key(parent.slice)
        elif name == "os.environ" and isinstance(parent, ast.Attribute) and parent.attr == "get" and isinstance(parents.get(parent), ast.Call):
            call = parents[parent]
            key = literal_key(call.args[0]) if call.args else None
        elif name == "os.environ" and isinstance(parent, ast.Compare) and parent.left is not node and literal_key(parent.left):
            key = literal_key(parent.left)
        elif name == "os.getenv" and isinstance(parent, ast.Call) and parent.func is node:
            key = literal_key(parent.args[0]) if parent.args else None
        if key is None:
            add(node, f"folosește {name} într-un mod pe care testul nu-l poate verifica (iterare, copiere, atribuire sau cheie calculată): programul poate citi doar variabile cu nume scris direct în cod")
            continue
        keys.add(key)
        if key not in ALLOWED_ENV_VARS:
            add(node, f"citește variabila de mediu «{key}», care nu e în lista albă {sorted(ALLOWED_ENV_VARS)}: programul nu are voie să citească alte variabile (ar putea conține parole sau chei ale utilizatorului)")
    return keys, problems


# ---------- (3) secrete și date personale în tot ce urcă ----------

# Gazde de e-mail rezervate pentru exemple (RFC 2606 și 6761): adrese cu ele nu aparțin nimănui.
EXAMPLE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "exemplu.invalid")
EXAMPLE_EMAIL_SUFFIXES = (".invalid", ".test", ".example", ".localhost")
# Nume de cont generice (servere de CI, conturi implicite): nu identifică un om, deci prezența lor în text nu e o scurgere.
GENERIC_ACCOUNT_NAMES = frozenset({"runner", "runneradmin", "administrator", "admin", "user", "root", "vsts", "build", "default", "public", "guest"})
MIN_ACCOUNT_NAME_LENGTH = 4  # un nume mai scurt ar da potriviri întâmplătoare în orice text
CNP_CONTROL_WEIGHTS = "279146358279"  # ponderile oficiale ale cifrei de control CNP
MAX_COUNTY_CODE = 52  # 01-46 județe, 47-48 sectoare (vechi), 51-52 Călărași și Giurgiu
IBAN_MIN_LENGTH, IBAN_MAX_LENGTH = 15, 34


@dataclass(frozen=True)
class Finding:
    """Un posibil secret sau dată personală: regula, fișierul, linia și valoarea mascată."""

    rule: str
    path: str
    line: int
    value: str  # deja mascată

    def __str__(self) -> str:
        """Rândul din mesaj: cale:linie: [regulă] valoare mascată."""
        return f"{self.path}:{self.line}: [{self.rule}] {self.value}"


def mask(value: str) -> str:
    """Primele 3 caractere și lungimea: destul ca să găsești locul, prea puțin ca să repeți secretul în jurnal."""
    return f"{value[:3]}… ({len(value)} caractere)"


def is_valid_cnp(digits: str) -> bool:
    """True dacă `digits` (13 cifre) are structura unui CNP românesc: sex, dată, județ și cifră de control corecte."""
    if len(digits) != 13 or not digits.isdigit() or digits[0] == "0":
        return False
    month, day, county = int(digits[3:5]), int(digits[5:7]), int(digits[7:9])
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1 <= county <= MAX_COUNTY_CODE):
        return False
    control = sum(int(d) * int(w) for d, w in zip(digits[:12], CNP_CONTROL_WEIGHTS)) % 11
    return (1 if control == 10 else control) == int(digits[12])


def is_valid_iban(text: str) -> bool:
    """True dacă `text` trece verificarea IBAN (mutarea primelor 4 caractere la coadă, apoi modulo 97 egal cu 1)."""
    compact = re.sub(r"\s", "", text).upper()
    if not IBAN_MIN_LENGTH <= len(compact) <= IBAN_MAX_LENGTH or not compact.isalnum():
        return False
    return int("".join(str(int(c, 36)) for c in compact[4:] + compact[:4])) % 97 == 1


def is_romanian_phone(candidate: str) -> bool:
    """True dacă `candidate` (cifre cu separatori) e un număr românesc: mobil 07x, fix 02x/03x, cu 0, +40 sau 0040."""
    digits = re.sub(r"\D", "", candidate)
    plus = candidate.lstrip().startswith("+")
    if plus and digits.startswith("40"):
        national = digits[2:]
    elif digits.startswith("0040"):
        national = digits[4:]
    elif digits.startswith("0") and not plus:
        national = digits[1:]
    else:
        return False
    return len(national) == 9 and national[0] in "723"


def _email_is_example(email: str) -> bool:
    """True pentru adrese cu gazde rezervate exemplelor: nu aparțin nimănui."""
    domain = email.rsplit("@", 1)[1].lower()
    return domain in EXAMPLE_EMAIL_DOMAINS or domain.endswith(EXAMPLE_EMAIL_SUFFIXES)


# Prefixe asamblate la rulare: așa fișierul acesta nu conține el însuși tiparele pe care le caută.
_PEM_MARKER = "-----" + "BEGIN"
SECRET_PATTERNS = (
    ("cheie privată sau certificat (PEM)", re.compile(re.escape(_PEM_MARKER))),
    ("antet Authorization: Bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("cheie AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("token Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("cheie de tip sk-", re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("cheie Google API", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("token JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")),
    ("cheie Stripe live", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    ("token PyPI", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}")),
    ("token npm", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("antet Cookie cu valoare", re.compile(r"(?im)^\s*(?:set-)?cookie\s*:\s*[^\s=]+=\S{8,}")),
    ("IBAN românesc", re.compile(r"\bRO\d{2}(?:\s?[0-9A-Z]{4}){5}\b|\bRO\d{2}[A-Z]{4}[0-9A-Z]{16}\b")),
    ("atribuire de parolă, token sau cheie cu valoare scrisă", re.compile(
        r"""(?i)["']?\b(?:password|passwd|parola|token|secret|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token)\b["']?[ \t]*[:=][ \t]*(["'])[^"'\r\n]+\1""")),
)
# Atribuiri în stil .env (NUME_SECRET=valoare): doar în fișiere de configurare, nu în Python/JS, unde constante precum
# LIGHT_TOKENS sau SECRET_PATTERNS sunt nume obișnuite, nu secrete.
ENV_STYLE_SECRET = ("variabilă de mediu de tip secret cu valoare", re.compile(
    r"(?m)^\s*(?:export\s+|set\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*[ \t]*=[ \t]*[^\s#\"'$%{<][^\s#]*"))
CONFIG_FILE_SUFFIXES = frozenset({"", ".env", ".sh", ".bat", ".cmd", ".ps1", ".ini", ".cfg", ".conf", ".toml", ".yml", ".yaml", ".properties", ".txt", ".md"})
IBAN_CANDIDATE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){2,7}(?:\s?[0-9A-Z]{1,3})?\b")
CNP_CANDIDATE = re.compile(r"(?<![\d.])[1-9]\d{12}(?![\d])")
PHONE_CANDIDATE = re.compile(r"(?<![\w+.])\+?\d[\d \t.-]{7,16}\d(?![\w])")
EMAIL_CANDIDATE = re.compile(r"(?i)[A-Z0-9][A-Z0-9._%+-]*@[A-Z0-9-]+(?:\.[A-Z0-9-]+)*\.[A-Z]{2,}")


def _account_names() -> list[str]:
    """Numele contului de Windows și al folderului personal, dacă sunt personale (nu generice, nu scurte)."""
    names = set()
    for getter in (getpass.getuser, lambda: os.environ.get("USERNAME", ""), lambda: Path.home().name):
        try:
            value = (getter() or "").strip()
        except (OSError, KeyError, ImportError, RuntimeError):
            continue
        if len(value) >= MIN_ACCOUNT_NAME_LENGTH and value.lower() not in GENERIC_ACCOUNT_NAMES:
            names.add(value)
    return sorted(names)


def scan_text(path: str, text: str, account_names: list[str] | None = None) -> list[Finding]:
    """Toate posibilele secrete și date personale dintr-un text (valorile mascate); fără excepții aplicate."""
    findings: list[Finding] = []

    def line_of(index: int) -> int:
        """Numărul liniei (de la 1) pentru poziția dată din text."""
        return text.count("\n", 0, index) + 1

    def add(rule: str, match: re.Match) -> None:
        """Notează o potrivire ca Finding, cu valoarea mascată."""
        findings.append(Finding(rule, path, line_of(match.start()), mask(match.group(0).strip())))

    patterns = SECRET_PATTERNS + ((ENV_STYLE_SECRET,) if Path(path).suffix.lower() in CONFIG_FILE_SUFFIXES else ())
    for rule, pattern in patterns:
        for match in pattern.finditer(text):
            add(rule, match)
    for match in IBAN_CANDIDATE.finditer(text):
        if is_valid_iban(match.group(0)):
            add("IBAN valid (suma de control corectă)", match)
    for match in CNP_CANDIDATE.finditer(text):
        if is_valid_cnp(match.group(0)):
            add("CNP valid (cifra de control corectă)", match)
    for match in PHONE_CANDIDATE.finditer(text):
        if is_romanian_phone(match.group(0)):
            add("număr de telefon românesc", match)
    for match in EMAIL_CANDIDATE.finditer(text):
        if not _email_is_example(match.group(0)):
            add("adresă de e-mail", match)
    for name in (_account_names() if account_names is None else account_names):
        for match in re.finditer(rf"(?i)(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text):
            add("numele contului tău de Windows", match)
    return findings


@dataclass(frozen=True)
class AllowedFinding:
    """O excepție scrisă și motivată: regula, fișierul, un tipar pentru valoarea găsită și DE CE e în regulă."""

    rule: str
    path: str
    reason: str


# Excepții de la scanarea de secrete: niciun fișier de urcat nu are voie să conțină chei, IBAN, CNP, telefoane sau
# e-mailuri reale. O excepție se adaugă DOAR cu motiv scris (ce e valoarea, de ce nu e o dată reală) și cu acordul lui Robert.
ALLOWED_FINDINGS: tuple[AllowedFinding, ...] = (
    AllowedFinding(
        "număr de telefon românesc", "tests/html_builders.py",
        "FAKE_PHONE e un număr evident fals (după prefix, doar zerouri), pus de testele de browser ca valoare inventată "
        "în paginile-capcană ale raportului; nu aparține nimănui.",
    ),
)
MIN_REASON_LENGTH = 30


def _allowed(finding: Finding) -> bool:
    """True dacă există o excepție scrisă (regulă + fișier) pentru acest finding."""
    return any(a.rule == finding.rule and a.path == finding.path for a in ALLOWED_FINDINGS)


def scan_publishable_files(files: list[Path]) -> list[Finding]:
    """Findings (după excepții) pentru toate fișierele text din `files`."""
    findings = []
    for path in files:
        text = read_text_or_none(path)
        if text is not None:
            findings.extend(f for f in scan_text(relative(path), text) if not _allowed(f))
    return findings


# ---------- (4) nume de fișiere care nu au ce căuta în repo ----------

# Date personale și secrete după nume (oglindă a pasului din secrete.yml): sesiunea, rezultatele, cookie-urile, mediul.
FORBIDDEN_FILE_PATTERNS = (
    ".profil_browser", "iesiri", "logs", "comenzi.json", "retururi.json", "analiza.json", "run_info.json", "produse.csv",
    "istoric_preturi.csv", ".env", ".env.*", "*.har", "Local State", "Login Data", "Cookies", "categorii.personal.json",
    "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", "*.kdbx",
)
# Fișiere cu aceste nume sunt șabloane fără date și pot urca.
ALLOWED_TEMPLATE_NAMES = frozenset({".env.example"})
# Căi care par personale, pe care .gitignore trebuie să le acopere (plasa dinaintea lui `git add .`). Fișierele cu
# comenzi, retururi, analiză, produse, istoric de prețuri și run_info le scrie programul DOAR în iesiri/<data>_<ora>/
# (run_pipeline.py), deci le listăm acolo, unde chiar apar, iar `iesiri/` din .gitignore le acoperă. Același nume în
# rădăcina proiectului nu e produs de program și nu cere regulă în .gitignore; dacă totuși ajunge acolo (copiat de mână
# sau cu --iesire .), îl oprește `test_no_file_with_personal_data_or_keys_would_be_published` (după nume, la orice
# adâncime) și pasul «fisiere-personale» din secrete.yml.
_RUN_FOLDER = "iesiri/2026-10-04_10-00-00"
SAMPLE_SENSITIVE_PATHS = (
    (".profil_browser/Default/Cookies", False), ("logs/2026-10-04.log", False), (".env", False),
    ("config/categorii.personal.json", False), ("export.har", False),
    *((f"{_RUN_FOLDER}/{name}", False) for name in (
        "comenzi.json", "retururi.json", "analiza.json", "run_info.json", "produse.csv", "istoric_preturi.csv")),
)


def forbidden_names(files: list[Path], root: Path = PROJECT_ROOT) -> list[str]:
    """Fișierele din `files` ale căror nume sau foldere părinte (relativ la `root`) sunt pe lista de date personale/secrete."""
    hits = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if Path(rel).name.lower() in ALLOWED_TEMPLATE_NAMES:
            continue
        for part in Path(rel).parts:
            if matches_any(part, FORBIDDEN_FILE_PATTERNS):
                hits.append(f"{rel}: «{part}» e pe lista de date personale sau secrete")
                break
    return hits


# ---------- teste pe codul real ----------

@pytest.mark.parametrize("path", program_sources(), ids=relative)
def test_program_cannot_type_passwords_or_read_the_session(path):
    """Niciun modul al programului nu tastează în pagini, nu citește cookie-uri și nu ascultă traficul browserului."""
    problems = python_credential_violations(parse_source(path), relative(path))
    assert not problems, "\n".join(problems)


def test_program_reads_only_the_whitelisted_environment_variables():
    """Programul citește exact variabilele EMAG_* din lista albă, nici mai multe, nici mai puține."""
    read, problems = set(), []
    for path in program_sources():
        keys, found = env_reads(parse_source(path), relative(path))
        read |= keys
        problems += found
    assert not problems, "\n".join(problems)
    assert read == set(ALLOWED_ENV_VARS), (
        f"variabilele citite de program {sorted(read)} nu coincid cu lista albă din test {sorted(ALLOWED_ENV_VARS)}: "
        "adaugă în listă (cu rostul ei) sau scoate din ea ce nu se mai citește")


def test_whitelisted_environment_variables_are_documented_in_settings():
    """Lista albă din test coincide cu variabilele documentate în antetul lui settings.py."""
    documented = set(re.findall(r"^\s*(EMAG_[A-Z_]+)\b", settings.__doc__ or "", re.MULTILINE))
    assert documented == set(ALLOWED_ENV_VARS), (
        f"settings.py documentează {sorted(documented)}, lista albă are {sorted(ALLOWED_ENV_VARS)}: utilizatorul și garda trebuie să audă același lucru")


def test_nothing_that_would_be_published_contains_a_secret_or_personal_data():
    """Niciun fișier care ar urca în repo nu conține chei, token-uri, IBAN, CNP, telefoane, e-mailuri sau numele contului de Windows."""
    files = files_to_publish()
    assert files, "nu am găsit niciun fișier de verificat: testul n-ar dovedi nimic"
    findings = scan_publishable_files(files)
    assert not findings, (
        "Posibile secrete sau date personale în fișiere care ar urca în repo (valorile sunt mascate):\n  "
        + "\n  ".join(map(str, findings))
        + "\nScoate valoarea din fișier. Dacă e un exemplu inventat, folosește unul clar fals (ex. adresa @exemplu.invalid); "
        "o excepție se adaugă în ALLOWED_FINDINGS doar cu motiv scris.")


def test_no_file_with_personal_data_or_keys_would_be_published():
    """Niciun fișier care ar urca în repo nu are numele unei date personale sau al unui secret (sesiune, rezultate, cookie-uri, chei)."""
    hits = forbidden_names(files_to_publish())
    assert not hits, (
        "Fișiere care ar urca în repo, deși conțin sau pot conține date personale ori secrete:\n  " + "\n  ".join(hits)
        + "\nAdaugă tiparul în .gitignore și, dacă fișierul e deja urmărit de git, scoate-l cu «git rm --cached».")


def test_gitignore_covers_the_personal_data_and_secret_paths():
    """.gitignore acoperă căile unde apar sesiunea, rezultatele, jurnalele, mediul și regulile personale."""
    ignore = GitIgnore((PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8"))
    missing = [path for path, is_dir in SAMPLE_SENSITIVE_PATHS if not ignore.is_ignored(path, is_dir)]
    assert not missing, (
        f".gitignore nu acoperă: {missing}. Fără ele, un «git add .» ar putea urca sesiunea eMAG, comenzile sau cheile "
        "(secrete.yml ar prinde-o, dar abia după push, când istoricul e deja public).")


def test_allowed_findings_are_justified_and_still_needed():
    """Fiecare excepție din ALLOWED_FINDINGS are motiv scris și mai e necesară (altfel se scoate)."""
    for allowed in ALLOWED_FINDINGS:
        assert len(allowed.reason.strip()) >= MIN_REASON_LENGTH, f"excepția {allowed.rule} pentru {allowed.path} nu are motiv scris"
    findings = {(f.rule, f.path) for f in (scan_text(relative(p), read_text_or_none(p) or "") for p in files_to_publish()) for f in f}
    stale = [a for a in ALLOWED_FINDINGS if (a.rule, a.path) not in findings]
    assert not stale, f"excepții care nu mai sunt necesare (scoate-le): {stale}"


# ---------- detectoarele văzute picând pe date-capcană ----------

def _py(source: str) -> list[str]:
    """Încălcările de tip parolă/sesiune dintr-un fragment de cod Python."""
    return python_credential_violations(ast.parse(source), "emag_spend/capcana.py")


@pytest.mark.parametrize("source, expected", [
    ("async def f(p):\n    await p.fill('#parola', 'x')", ".fill()"), ("async def f(p):\n    await p.type('#a', 'x')", ".type()"),
    ("async def f(p):\n    await p.press('#a', 'Enter')", ".press()"), ("async def f(l):\n    await l.press_sequentially('x')", "press_sequentially"),
    ("async def f(l):\n    await l.check()", ".check()"), ("async def f(l):\n    await l.set_input_files('x')", "set_input_files"),
    ("async def f(p):\n    await p.keyboard.press('a')", ".keyboard"), ("async def f(c):\n    return await c.cookies()", ".cookies"),
    ("async def f(c):\n    await c.storage_state(path='x')", ".storage_state"), ("def f(r):\n    return r.post_data", ".post_data"),
    ("def f(p):\n    p.on('request', print)", "ascultă traficul"), ("def f(p):\n    p.on('response', print)", "ascultă traficul"),
    ("async def f(p):\n    await p.wait_for_response('x')", "wait_for_response"),
    ("async def f(p):\n    await p.evaluate('() => document.cookie')", "document.cookie"),
    ("async def f(p):\n    await p.evaluate('() => localStorage.getItem(\"a\")')", "localStorage"),
    ("async def f(p):\n    await p.evaluate('() => document.querySelector(\"input[type=password]\").value')", "câmp de parolă"),
    ("async def f(p):\n    await p.evaluate('() => { a.value = \"x\"; }')", ".value ="),
])
def test_credential_detector_catches_trap_code(source, expected):
    """Capcană: fill, type, press, keyboard, cookies, storage_state, ascultarea cererilor și JS care citește sesiunea trebuie prinse."""
    problems = " | ".join(_py(source))
    assert expected in problems, f"nu a fost prins «{expected}» în:\n{source}\n(rezultat: {problems or 'nimic'})"


def test_credential_detector_allows_reading_page_text_and_clicking():
    """Fals pozitiv: citirea textului paginii, click-ul și goto nu sunt încălcări."""
    clean = (
        "async def f(page):\n    text = await page.evaluate('() => document.body.innerText')\n    await page.locator('.x').first.click()\n"
        "    await page.goto('https://www.emag.ro/')\n    return 'parola și codul 2FA le introduci tu'\n"
    )
    assert _py(clean) == []


def _env(source: str) -> tuple[set[str], list[str]]:
    """Citirile de mediu și încălcările dintr-un fragment de cod Python."""
    return env_reads(ast.parse(source), "emag_spend/capcana.py")


@pytest.mark.parametrize("source, expected", [
    ("import os\nx = os.environ['PATH']", "PATH"), ("import os\nx = os.environ.get('USERNAME')", "USERNAME"), ("import os\nx = os.getenv('TOKEN')", "TOKEN"),
    ("import os\nx = os.environ.get(name)", "nu-l poate verifica"), ("import os\nx = dict(os.environ)", "nu-l poate verifica"),
    ("import os\nfor k in os.environ: pass", "nu-l poate verifica"), ("import os\nos.environ['EMAG_X'] = '1'", "nu-l poate verifica"),
    ("import os\nos.putenv('A', 'b')", "os.putenv"), ("from os import environ", "importă environ"), ("import os\nx = os.environ['EMAG_ALTA']", "EMAG_ALTA"),
])
def test_environment_detector_catches_trap_code(source, expected):
    """Capcană: citirea oricărei variabile din afara listei albe, sau într-un mod neanalizabil, trebuie prinsă."""
    keys, problems = _env(source)
    assert expected in " | ".join(problems), f"nu a fost prins «{expected}» în:\n{source}"


def test_environment_detector_reads_literal_whitelisted_keys():
    """Citirile cu cheie literală (get, [], getenv, in) din lista albă sunt recunoscute și nu dau încălcări."""
    keys, problems = _env("import os\na = os.environ.get('EMAG_PROFILE_DIR', 'x')\nb = os.environ['EMAG_BROWSER_CHANNEL']\nc = os.getenv('EMAG_FETCH_CONCURRENCY')\nd = 'EMAG_LOGIN_WAIT_SECONDS' in os.environ")
    assert problems == [] and keys == {"EMAG_PROFILE_DIR", "EMAG_BROWSER_CHANNEL", "EMAG_FETCH_CONCURRENCY", "EMAG_LOGIN_WAIT_SECONDS"}


def _secret_samples() -> dict[str, str]:
    """Exemple de secrete și date personale asamblate la rulare din bucăți: fișierul de test nu le conține întregi."""
    def cnp() -> str:
        """Un CNP inventat, cu cifra de control corectă, calculat la rulare."""
        body = "1" + "800101" + "41" + "001"  # S=1, 1980-01-01, județul 41, nr. 001 (valori inventate)
        control = sum(int(d) * int(w) for d, w in zip(body, CNP_CONTROL_WEIGHTS)) % 11
        return body + str(1 if control == 10 else control)

    def iban() -> str:
        """Un IBAN românesc inventat, cu cifre de control corecte, calculat la rulare."""
        bban = "EXMP" + "0" * 16  # bancă inventată; cifrele de control se calculează
        check = 98 - int("".join(str(int(c, 36)) for c in bban + "RO00")) % 97
        return f"RO{check:02d}{bban}"

    return {
        "pem": "-----" + "BEGIN PRIVATE KEY-----", "bearer": "Authorization: Bearer " + "a" * 24, "aws": "AK" + "IA" + "A" * 16,
        "github": "gh" + "p_" + "a" * 36, "slack": "xo" + "xb-" + "1" * 12, "sk": "sk" + "-" + "b" * 24, "google": "AI" + "za" + "c" * 35,
        "jwt": "ey" + "J" + "a" * 12 + ".ey" + "J" + "b" * 12 + ".sig",
        "assign_py": 'password = "' + "hunter2" + '"', "assign_json": '{"api_key": "' + "abcdef" + '"}', "assign_env": "DB_PASS" + "WORD=" + "hunter2",
        "iban_ro": iban(), "cnp": cnp(), "phone_mobile": "07" + "21 234 567", "phone_intl": "+40 " + "721 234 567", "phone_fix": "021" + " 123 4567",
        "email": "ion.popescu" + "@" + "firma.ro", "cookie": "Cookie: sessionid" + "=" + "a" * 20,
    }


@pytest.mark.parametrize("key", sorted(_secret_samples()))
def test_secret_scanner_catches_every_kind_of_trap(key):
    """Scanerul prinde fiecare tip de secret și de dată personală (PEM, token-uri, IBAN, CNP, telefon, e-mail, cookie, atribuiri)."""
    sample = _secret_samples()[key]
    assert scan_text("capcana.txt", f"text înainte\n{sample}\ntext după", account_names=[]), f"scanerul nu a prins «{key}»: {mask(sample)}"


def test_secret_scanner_catches_the_account_name_of_the_current_user():
    """Numele contului de Windows e prins ca cuvânt întreg, dar nu ca parte dintr-un cuvânt mai lung."""
    assert scan_text("capcana.md", "Calea: C:\\Users\\" + "Ionescu" + "\\Desktop", account_names=["Ionescu"])
    assert not scan_text("capcana.md", "Ionescuvalue", account_names=["Ionescu"]), "numele ca parte dintr-un cuvânt mai lung nu e o scurgere"


def test_secret_scanner_has_no_false_positives_on_ordinary_project_text():
    """Fals pozitiv: text obișnuit al proiectului (sume, versiuni, adrese-exemplu, linkuri eMAG) nu e raportat."""
    cnp_like_but_invalid = "1234567890123"
    ordinary = "\n".join([
        "Comanda 123456789 din 2026-10-04, total 1.234,56 Lei, 7922305 bani.",
        "Versiunea playwright==1.62.0, lxml 6.0.2, Python 3.13 și 3.14.",
        "Parola și codul 2FA le introduci tu; programul nu cere parola. token și secret ca simple cuvinte.",
        'password = ""', "TOKEN =", 'var token = getToken();', "api_key = os.environ['X']",
        "Contact: contact@" + "exemplu.invalid, " + "test@" + "example.com", "https://www.emag.ro/history/shoppingdetails/123456789",
        "Timp: 1759570000000 ms; cod " + cnp_like_but_invalid, "RO este codul țării; ROMANIA2024", "data 04.10.2026 sau 04-10-2026 sau 2026.10.04",
        "Bearer token e un termen; Bearer scurt", "Cookie: doar numele", "sk-learn și task-force",
    ])
    assert scan_text("curat.txt", ordinary, account_names=[]) == []


def test_validators_accept_real_structures_and_reject_near_misses():
    """Validatoarele de CNP, IBAN și telefon acceptă structuri reale și resping aproximările."""
    cnp = _secret_samples()["cnp"]
    wrong_control = cnp[:-1] + str((int(cnp[-1]) + 1) % 10)
    assert is_valid_cnp(cnp) and not is_valid_cnp(wrong_control)
    assert not is_valid_cnp("0000000000000") and not is_valid_cnp("123")
    iban = _secret_samples()["iban_ro"]
    broken_iban = iban[:2] + str((int(iban[2]) + 1) % 10) + iban[3:]
    assert is_valid_iban(iban) and not is_valid_iban(broken_iban)
    samples = _secret_samples()
    assert is_romanian_phone(samples["phone_mobile"]) and is_romanian_phone(samples["phone_intl"]) and is_romanian_phone(samples["phone_fix"])
    assert is_romanian_phone("00" + "40" + "721234567")
    assert not is_romanian_phone("1234567890") and not is_romanian_phone("2026-10-04") and not is_romanian_phone("+1 " + "721 234 5678")


def test_forbidden_name_detector_catches_personal_data_files(tmp_path):
    """Detectorul de nume prinde toate fișierele-capcană (sesiune, rezultate, chei, .env) și lasă README și .env.example."""
    names = [".profil_browser/Default/Cookies", "iesiri/x/raport.html", "logs/a.log", "comenzi.json", "sub/analiza.json", "export.har",
             "Local State", "Login Data", "config/categorii.personal.json", ".env", ".env.local", "chei/id_rsa", "cert.pem", "istoric_preturi.csv"]
    files = []
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        files.append(target)
    ok = tmp_path / "README.md"
    template = tmp_path / ".env.example"
    ok.write_text("x", encoding="utf-8")
    template.write_text("x", encoding="utf-8")
    hits = forbidden_names([ok, template] + files, root=tmp_path)
    flagged = {hit.split(":")[0] for hit in hits}
    assert flagged == set(names), f"capcane neprinse: {sorted(set(names) - flagged)}; prinse în plus: {sorted(flagged - set(names))}"


# ---------- fără git, parcurgerea trebuie să respecte .gitignore ca git ----------

GITIGNORE_SAMPLE = "\n".join([
    ".venv/", "__pycache__/", "# comentariu", "", ".profil_browser/", "iesiri/", "logs/", "*.log", "!pastrat.log", "/radacina.txt",
    "doc/**/adanc.txt", "*.har", "config/categorii.personal.json", "date?.csv", "[ab]x.txt",
])
SAMPLE_TREE = (
    "README.md", "radacina.txt", "sub/radacina.txt", "a.log", "pastrat.log", "sub/b.log", "iesiri/x/comenzi.json", "logs/z.txt",
    ".profil_browser/Default/Cookies", "sub/iesiri/y.txt", "doc/adanc.txt", "doc/a/b/adanc.txt", "doc/alt.txt", "export.har", "sub/x.har",
    "config/categorii.json", "config/categorii.personal.json", "date1.csv", "date12.csv", "ax.txt", "cx.txt", "emag_spend/__pycache__/m.pyc", "emag_spend/m.py",
)


def _materialize(root: Path) -> None:
    """Creează într-un folder un .gitignore și un arbore de probă pentru testele de parcurgere fără git."""
    (root / ".gitignore").write_text(GITIGNORE_SAMPLE, encoding="utf-8")
    for name in SAMPLE_TREE:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x", encoding="utf-8")


def test_walk_without_git_respects_gitignore(tmp_path):
    """Parcurgerea fără git respectă .gitignore (negări, ancorare, **, ?, clase de caractere) ca git."""
    _materialize(tmp_path)
    found = {p.relative_to(tmp_path).as_posix() for p in walk_respecting_gitignore(tmp_path)}
    kept = {"README.md", ".gitignore", "sub/radacina.txt", "pastrat.log", "doc/alt.txt", "config/categorii.json",
            "date12.csv", "cx.txt", "emag_spend/m.py"}
    ignored = {"radacina.txt", "a.log", "sub/b.log", "iesiri/x/comenzi.json", "sub/iesiri/y.txt", "logs/z.txt", ".profil_browser/Default/Cookies", "doc/adanc.txt",
               "doc/a/b/adanc.txt", "export.har", "sub/x.har", "config/categorii.personal.json", "date1.csv", "ax.txt", "emag_spend/__pycache__/m.pyc"}
    assert kept <= found, f"fișiere care trebuiau păstrate dar lipsesc: {sorted(kept - found)} (notă: «!pastrat.log» readmite, «/radacina.txt» ignoră doar rădăcina, «iesiri/» ignoră folderul la orice adâncime)"
    assert not ignored & found, f"fișiere care trebuiau ignorate dar apar: {sorted(ignored & found)}"


@pytest.mark.skipif(shutil.which("git") is None, reason="git nu e instalat: nu pot compara cu git însuși")
def test_walk_without_git_gives_the_same_files_as_git(tmp_path):
    """Parcurgerea fără git dă exact aceeași listă ca `git ls-files` pe același arbore."""
    _materialize(tmp_path)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env, capture_output=True)
    listed = subprocess.run(["git", "-C", str(tmp_path), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            check=True, env=env, capture_output=True).stdout.decode("utf-8").split("\0")
    git_files = {name for name in listed if name}
    walked = {p.relative_to(tmp_path).as_posix() for p in walk_respecting_gitignore(tmp_path)}
    assert walked == git_files, f"parcurgerea fără git diferă de git: doar ea {sorted(walked - git_files)}, doar git {sorted(git_files - walked)}"
