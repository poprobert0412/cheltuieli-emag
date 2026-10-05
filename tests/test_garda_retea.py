"""Garda de rețea: nimic nu pleacă de pe calculatorul utilizatorului, în afară de citirea paginilor eMAG.

Primește: sursele programului (`emag_spend/**/*.py`, `ruleaza.py`) și interfața (`interfata/**`, `templates/**`).
Verifică: (1) Python (AST): fără module de rețea sau de procese, Playwright doar unde trebuie, doar GET spre pagini
construite din settings.BASE_URL; (2) orice adresă din surse Python are gazda emag.ro; (3) JS/HTML/CSS: fără
cereri de rețea, resurse externe, formulare sau navigări automate (se caută tipare de COD, nu cuvinte);
(4) la execuție: fluxurile --demo, --din-cache și --sterge-sesiunea rulează cu socket-urile blocate și notate.
Fiecare detector e probat și pe un „cod-capcană” care trebuie să pice. Ce NU face: nu verifică ce primește eMAG.
"""

import ast
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from emag_spend import settings
from tests.garda_audit import FLOWS, AuditRecorder, isolated_program, prepare_flow, run_flow
from tests.garda_js_scan import scan_js
from tests.garda_support import PROGRAM_DIR, dotted_name, interface_files, parent_map, parse_source, program_sources, relative, string_constants



# ---------- Python: ce nu are voie să existe în program ----------

# Module prin care programul ar putea trimite date sau porni alte procese. Prefixele se potrivesc și cu submodulele.
FORBIDDEN_MODULES = {
    "requests": "client HTTP", "urllib.request": "client HTTP din biblioteca standard", "urllib3": "client HTTP",
    "http.client": "client HTTP", "http.server": "server HTTP", "httpx": "client HTTP", "aiohttp": "client HTTP",
    "socket": "conexiuni de rețea directe", "socketserver": "server de rețea", "ssl": "conexiuni criptate directe",
    "smtplib": "trimitere de e-mail", "imaplib": "citire de e-mail", "poplib": "citire de e-mail", "ftplib": "transfer FTP",
    "telnetlib": "Telnet", "websockets": "WebSocket", "xmlrpc": "XML-RPC peste rețea", "paramiko": "SSH",
    "subprocess": "pornirea altor programe", "ctypes": "apeluri directe în sistem",
}
# Singurul modul care are voie să importe Playwright întreg: pornește browserul pentru login și sesiune.
PLAYWRIGHT_MODULE_FILE = "browser_session.py"
# În rest, doar clasele de excepție (ca să prindă erorile de browser): ele nu pornesc nimic și nu fac cereri.
PLAYWRIGHT_EXCEPTION_NAMES = frozenset({"Error", "TimeoutError"})
# Deschiderea raportului local în browserul implicit: un singur fișier, cu o adresă file:// făcută din calea raportului.
WEBBROWSER_MODULE_FILE = "report_opener.py"
# EXCEPȚIA aplicației locale (brief, pct. 6 și 8): doar app_server.py are voie să importe modulele de server, și doar ca să asculte pe
# 127.0.0.1, port 0 (local_binding_violations și testul de la execuție de mai jos). Nu trimite nimic spre exterior: nicio conexiune
# ieșită, nicio interogare de nume (server_bind nu cheamă getfqdn). Orice alt modul rămâne fără rețea.
LOCAL_SERVER_FILE = "app_server.py"
LOCAL_SERVER_MODULES = frozenset({"http.server", "socketserver", "socket"})
# Al doilea (și ultimul) fișier care cheamă webbrowser: deschide în browser pagina aplicației locale, cu o adresă validată
# (http, 127.0.0.1, port numeric, /aplicatie.html) înainte de apel; de aceea acceptă `webbrowser.open(<variabilă>)`, nu doar `.as_uri()`.
APP_URL_OPENER_FILE = "app_opener.py"
WEBBROWSER_MODULE_FILES = frozenset({WEBBROWSER_MODULE_FILE, APP_URL_OPENER_FILE})
# Adresa la care are voie să asculte serverul local și portul cerut (0 = îl alege sistemul; un port fix ar fi o țintă cunoscută).
LOOPBACK_ADDRESS = "127.0.0.1"
FREE_PORT_VALUE = 0
# Apeluri de socket pe care nici app_server.py nu le are voie (deschid conexiuni ieșite sau trimit datagrame): serverul doar ascultă.
LOCAL_SERVER_FORBIDDEN_METHODS = frozenset({"connect", "connect_ex", "sendto", "gethostbyaddr", "getfqdn", "getnameinfo", "getservbyname"})
# Apeluri care execută cod sau programe: ocolesc verificarea importurilor, deci sunt interzise oricum ar fi scrise.
FORBIDDEN_BUILTIN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
FORBIDDEN_DOTTED_CALLS = frozenset({"os.system", "os.popen", "os.startfile", "importlib.import_module", "importlib.__import__"})
FORBIDDEN_DOTTED_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn")
# Metode care deschid conexiuni, pornesc procese sau interceptează/modifică traficul browserului.
FORBIDDEN_METHOD_NAMES = frozenset({
    "open_connection", "create_connection", "create_datagram_endpoint", "start_server", "create_server", "sock_connect",
    "getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_subprocess_exec", "create_subprocess_shell",
    "subprocess_exec", "subprocess_shell", "route", "unroute", "route_from_har", "route_web_socket", "expose_function",
    "expose_binding", "add_init_script", "set_extra_http_headers", "new_cdp_session",
})
# Singurele metode de pe `.request` (APIRequestContext din Playwright) permise: citirea paginilor. Orice trimitere
# (post, put, fetch...) ar putea duce date în afară.
ALLOWED_REQUEST_METHODS = frozenset({"get"})
# Metode care navighează sau cer o pagină: adresa lor trebuie să pornească din settings.BASE_URL.
URL_TAKING_METHODS = frozenset({"goto"})
# Cod JavaScript care ar face cereri sau navigări, dacă ar apărea într-un text trimis la `page.evaluate`.
JS_NETWORK_PATTERNS = (
    (r"\bfetch\s*\(", "fetch()"), (r"\bXMLHttpRequest\b", "XMLHttpRequest"), (r"\bsendBeacon\b", "sendBeacon"),
    (r"\bnew\s+WebSocket\b", "WebSocket"), (r"\bEventSource\b", "EventSource"), (r"\bimportScripts\b", "importScripts"),
    (r"\bnew\s+Image\b", "new Image()"), (r"\.\s*submit\s*\(", "form.submit()"), (r"\bwindow\s*\.\s*open\s*\(", "window.open()"),
    (r"\blocation\s*\.\s*(?:assign|replace)\s*\(", "location.assign/replace"), (r"\blocation(?:\s*\.\s*href)?\s*=(?!=)", "atribuire la location"),
)
# Gazdele permise în adresele din surse Python: doar eMAG, doar https.
ALLOWED_PYTHON_URL_HOSTS = frozenset({"emag.ro", "www.emag.ro"})
URL_IN_TEXT = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>)\]}]*")


def _module_hit(name: str) -> str | None:
    """Intrarea din FORBIDDEN_MODULES care acoperă `name` (exact sau ca prefix cu punct); None dacă nu e interzis."""
    for forbidden in FORBIDDEN_MODULES:
        if name == forbidden or name.startswith(forbidden + "."):
            return forbidden
    return None


def _flows_from_base_url(url_node: ast.AST, call: ast.Call, parents: dict) -> bool:
    """True dacă argumentul URL conține `settings.BASE_URL` direct sau printr-o variabilă locală asignată din el."""
    def mentions_base(node: ast.AST) -> bool:
        """True dacă nodul conține `settings.BASE_URL` oriunde în el."""
        return any(dotted_name(n) == "settings.BASE_URL" for n in ast.walk(node))

    if mentions_base(url_node):
        return True
    if isinstance(url_node, ast.Name):
        scope = call
        while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = parents[scope]
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == url_node.id for t in node.targets):
                if mentions_base(node.value):
                    return True
    return False


def python_network_violations(tree: ast.Module, filename: str) -> list[str]:
    """Încălcările de rețea dintr-un fișier Python (AST), ca mesaje în română; listă goală = curat."""
    base = Path(filename).name
    parents = parent_map(tree)
    problems: list[str] = []

    def add(node: ast.AST, why: str) -> None:
        """Adaugă o încălcare cu numele fișierului și linia nodului."""
        problems.append(f"{filename}:{node.lineno}: {why}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.level:
                continue  # import relativ, din pachetul programului
            roots = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for root in roots:
                names = [root] + ([f"{root}.{alias.name}" for alias in node.names] if isinstance(node, ast.ImportFrom) else [])
                if root == "playwright" or root.startswith("playwright."):
                    only_exceptions = isinstance(node, ast.ImportFrom) and all(a.name in PLAYWRIGHT_EXCEPTION_NAMES for a in node.names)
                    if base != PLAYWRIGHT_MODULE_FILE and not only_exceptions:
                        add(node, f"importă Playwright în afara lui {PLAYWRIGHT_MODULE_FILE}: browserul se pornește doar acolo, ca să existe un singur loc care vorbește cu el (celelalte primesc pagina ca parametru; excepție: clasele de eroare {sorted(PLAYWRIGHT_EXCEPTION_NAMES)})")
                    continue
                if root == "webbrowser" and base not in WEBBROWSER_MODULE_FILES:
                    add(node, f"importă webbrowser în afara lui {sorted(WEBBROWSER_MODULE_FILES)}: deschiderea de adrese într-un browser trebuie să stea în aceste fișiere, unde se verifică că e doar raportul local sau pagina aplicației locale")
                    continue
                for name in names:
                    hit = _module_hit(name)
                    if hit in LOCAL_SERVER_MODULES and base == LOCAL_SERVER_FILE:
                        continue  # excepția serverului local; leagă doar la 127.0.0.1 (local_binding_violations)
                    if hit:
                        add(node, f"importă «{name}» ({FORBIDDEN_MODULES[hit]}): programul nu are voie să trimită nimic în afara calculatorului în afară de citirea paginilor eMAG prin Playwright")
                        break
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTIN_CALLS:
                add(node, f"apelează {func.id}(): execută cod construit la rulare și ocolește verificarea importurilor")
            name = dotted_name(func)
            if name in FORBIDDEN_DOTTED_CALLS or name.startswith(FORBIDDEN_DOTTED_PREFIXES):
                add(node, f"apelează {name}(): pornește programe sau încarcă module pe ocolite; raportul se deschide doar prin {WEBBROWSER_MODULE_FILE}")
            if name.startswith("webbrowser."):
                single_argument = name == "webbrowser.open" and len(node.args) == 1 and not node.keywords
                local_file_uri = single_argument and isinstance(node.args[0], ast.Call) \
                    and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == "as_uri"
                validated_app_url = single_argument and base == APP_URL_OPENER_FILE and isinstance(node.args[0], ast.Name)
                if not (local_file_uri or validated_app_url):
                    add(node, f"webbrowser se apelează doar ca webbrowser.open(<cale>.as_uri()) (adresă dintr-o cale locală) sau, în {APP_URL_OPENER_FILE}, ca webbrowser.open(<variabilă>) cu adresa validată dinainte: nu un URL oarecare")
            if base == LOCAL_SERVER_FILE and isinstance(func, ast.Attribute) and func.attr in LOCAL_SERVER_FORBIDDEN_METHODS:
                add(node, f".{func.attr}(): {LOCAL_SERVER_FILE} are voie doar să asculte; nicio conexiune ieșită și nicio interogare de nume (DNS)")
            if isinstance(func, ast.Attribute) and func.attr in URL_TAKING_METHODS or name.endswith(".request.get"):
                if node.args and not _flows_from_base_url(node.args[0], node, parents):
                    add(node, "adresa navigată sau citită nu pornește din settings.BASE_URL: programul citește doar pagini eMAG, cu adresa construită din setările proiectului")
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_METHOD_NAMES:
                add(node, f".{node.attr}: deschide conexiuni, pornește procese sau interceptează traficul browserului")
            if isinstance(node.value, ast.Attribute) and node.value.attr == "request" and node.attr not in ALLOWED_REQUEST_METHODS:
                add(node, f".request.{node.attr}: din contextul de cereri se permite doar citirea (GET); orice trimitere ar putea duce date în afară")
            dotted = dotted_name(node)
            hit = _module_hit(dotted) if dotted.count(".") >= 1 else None
            if hit in LOCAL_SERVER_MODULES and base == LOCAL_SERVER_FILE:
                hit = None  # excepția serverului local (opțiuni de socket, clase de server)
            if hit and not isinstance(parents.get(node), ast.Attribute):
                add(node, f"folosește «{dotted}» ({FORBIDDEN_MODULES[hit]}) fără import vizibil: accesul la rețea trebuie să fie ușor de văzut")
    for line, text, is_docstring in string_constants(tree):
        if is_docstring:
            continue
        for pattern, label in JS_NETWORK_PATTERNS:
            if re.search(pattern, text):
                problems.append(f"{filename}:{line}: textul conține cod JavaScript de rețea ({label}): un script trimis la page.evaluate ar putea scoate date din pagină")
    return problems


def python_url_violations(tree: ast.Module, filename: str) -> list[str]:
    """Adresele din literalele text (în afara docstring-urilor) a căror gazdă nu e eMAG sau care nu sunt https."""
    problems = []
    for line, text, is_docstring in string_constants(tree):
        if is_docstring:
            continue  # documentația poate cita adrese; doar codul activ face cereri
        for match in URL_IN_TEXT.finditer(text):
            url = match.group(0)
            try:
                parts = urlsplit(url)
                host = (parts.hostname or "").lower()
            except ValueError:
                host, parts = "", None
            if parts is None or parts.scheme != "https" or host not in ALLOWED_PYTHON_URL_HOSTS or parts.username or parts.password:
                problems.append(f"{filename}:{line}: adresa «{url}» nu e https către emag.ro: programul nu are voie să contacteze alte gazde (dacă e doar un text arătat utilizatorului, scoate-l din cod sau pune-l în documentație)")
    return problems


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """Constantele de la nivelul modulului (`NUME = <literal>`), ca adresa serverului să se poată verifica și când e scrisă printr-un nume."""
    constants: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant):
            constants[node.targets[0].id] = node.value.value
    return constants


SERVER_MODULE_PREFIXES = ("http.server.", "socketserver.")


def _server_class_names(tree: ast.Module) -> set[str]:
    """Numele claselor de server din fișier: importate din http.server/socketserver (care se termină în «Server») și clasele definite aici care le moștenesc.

    `AppServer` din ruleaza.py (învelișul aplicației) nu intră aici: serverul real e creat în app_server.py, unde se verifică adresa.
    """
    names = {alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module in {"http.server", "socketserver"}
             for alias in node.names if alias.name.endswith("Server")}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                for base in node.bases:
                    dotted = dotted_name(base)
                    if dotted.rsplit(".", 1)[-1] in names or (dotted.startswith(SERVER_MODULE_PREFIXES) and dotted.endswith("Server")):
                        names.add(node.name)
                        changed = True
    return names


def local_binding_violations(tree: ast.Module, filename: str) -> list[str]:
    """Orice server creat sau `.bind(...)` din sursă trebuie să primească exact `(127.0.0.1, 0)`, direct sau prin constante de modul.

    Prinde 0.0.0.0, «», «::», «localhost», un port fix, un nume calculat (gethostname) și orice adresă pe care testul n-o poate verifica:
    o adresă „ciudată” într-un server local ar putea face aplicația vizibilă în rețea.
    """
    constants = _module_constants(tree)
    unknown = object()

    def value_of(node: ast.AST) -> object:
        """Valoarea literală a unui nod (literal sau nume de constantă de modul), sau `unknown`."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        return unknown

    server_classes = _server_class_names(tree)
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func) or (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        last = name.rsplit(".", 1)[-1]
        creates_server = last in server_classes or (name.startswith(SERVER_MODULE_PREFIXES) and last.endswith("Server"))
        if not (creates_server or last == "bind"):
            continue
        address = node.args[0] if node.args else None
        if not isinstance(address, ast.Tuple) or len(address.elts) != 2:
            problems.append(f"{filename}:{node.lineno}: {last}(...) fără adresa (gazdă, port) scrisă direct: nu pot verifica unde ascultă")
            continue
        host, port = (value_of(element) for element in address.elts)
        if host != LOOPBACK_ADDRESS:
            shown_host = "o valoare pe care testul n-o poate verifica" if host is unknown else repr(host)
            problems.append(f"{filename}:{node.lineno}: {last}(...) ascultă pe {shown_host}: serverul local are voie doar pe {LOOPBACK_ADDRESS}, altfel ar fi vizibil în rețea")
        elif port is unknown or isinstance(port, bool) or port != FREE_PORT_VALUE:
            shown_port = "o valoare pe care testul n-o poate verifica" if port is unknown else repr(port)
            problems.append(f"{filename}:{node.lineno}: {last}(...) cere portul {shown_port}: trebuie portul 0 (ales de sistem), nu unul fix")
    return problems


# ---------- JS / HTML / CSS: ce nu are voie să existe în interfață ----------

# Gazda externă permisă: linkurile către comenzile din cont, ca <a href> deschis DOAR la clic-ul utilizatorului.
ALLOWED_LINK_HOSTS = frozenset({"www.emag.ro"})
# Spații de nume XML: sunt identificatori (ex. la createElementNS), nu cereri de rețea.
XML_NAMESPACE_URLS = frozenset({"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink", "http://www.w3.org/1999/xhtml"})
# Extensiile pe care le așteptăm în interfață; altceva (ex. .exe, .wasm, .php) cere o verificare manuală.
EXPECTED_INTERFACE_SUFFIXES = frozenset({".html", ".htm", ".css", ".js", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".txt", ".md"})
# EXCEPȚIA clientului aplicației locale (brief, pct. 6): pagina aplicatie.html vorbește cu serverul local prin fetch() spre /api/..., dintr-un SINGUR
# fișier. Regula „interfața nu face cereri de rețea” rămâne pentru orice alt fișier (site-ul explicativ rămâne static, fără cereri).
# Ce se verifică în plus la acest fișier: un singur fetch(path, ...), iar fiecare request(...) pornește dintr-un literal «/api/...» (app_api_client_problems).
APP_API_CLIENT_FILE = "interfata/assets/app-api.js"
APP_API_PATH_PREFIX = "/api/"
APP_API_CLIENT_ALLOWED_RULES = ("fetch()",)
# Etichete care încarcă conținut din altă parte sau schimbă adresa paginii: nu au ce căuta într-o pagină locală.
FORBIDDEN_TAGS = frozenset({"iframe", "frame", "frameset", "embed", "object", "applet", "base", "portal", "fencedframe"})
URL_ATTRIBUTES = frozenset({"src", "srcset", "poster", "data", "background", "manifest", "codebase", "action", "formaction", "href", "xlink:href", "ping"})
# Cod de rețea sau de navigare în JavaScript (vederea `code`: fără comentarii și fără conținutul literalelor).
JS_CODE_RULES = (
    (r"\bfetch\s*\(", "fetch()"), (r"\bXMLHttpRequest\b", "XMLHttpRequest"), (r"\bWebSocket\b", "WebSocket"),
    (r"\bEventSource\b", "EventSource"), (r"\bsendBeacon\b", "sendBeacon"), (r"(?<![\w$.])import\s*\(", "import() dinamic"),
    (r"\bimportScripts\b", "importScripts"), (r"\bnew\s+(?:Shared)?Worker\b", "Worker"), (r"\bserviceWorker\b", "service worker"),
    (r"\bRTCPeerConnection\b", "WebRTC"), (r"\bnew\s+Image\b", "new Image()"),
    (r"\.\s*open\s*\(|(?<![\w$.])open\s*\(", "open() (fereastră nouă sau XHR)"),
    (r"\blocation\s*\.\s*(?:assign|replace|reload)\s*\(", "navigare prin location"),
    (r"\blocation\s*\.\s*(?:href|pathname|search|host|hostname|origin|protocol|port)\s*=(?!=)", "navigare prin atribuire la location"),
    (r"(?<![\w$.])location\s*=(?!=)", "navigare prin atribuire la location"),
    (r"\bdocument\s*\.\s*(?:write|writeln)\s*\(", "document.write"), (r"\beval\s*\(", "eval"),
    (r"\bnew\s+Function\b|(?<![\w$.])Function\s*\(", "Function()"), (r"\b(?:setTimeout|setInterval)\s*\(\s*['\"`]", "cod dat ca text la un temporizator"),
    (r"\.\s*(?:src|srcset|action|formAction|poster|ping)\s*=(?!=)", "atribuire de resursă (.src, .action...)"),
)
# Tipare care au nevoie de textul literalelor (vederea `uncommented`): numele etichetei sau al atributului e într-un literal.
JS_LITERAL_RULES = (
    (r"""\.\s*setAttribute\s*\(\s*['"`](?:src|srcset|action|formaction|poster|ping|data)['"`]""", "setAttribute pe un atribut care încarcă resurse"),
    (r"""\.\s*createElement(?:NS)?\s*\([^)]*['"`](?:script|iframe|link|img|embed|object|form|audio|video|source|track|base|meta)['"`]""", "creează o etichetă care încarcă resurse"),
)
# Etichete HTML care, scrise într-un literal JS (innerHTML etc.), ar încărca resurse din altă parte.
HTML_IN_TEXT_PATTERN = re.compile(r"<\s*(?:script|iframe|embed|object|link|img|base|frame|source|track|video|audio)\b", re.IGNORECASE)
# Cod care face linkuri în pagină (atribuire la .href, atribute, elemente noi, HTML inserat) și text care conține un <a> sau href=.
LINK_BUILDING_CODE = r"\.\s*href\s*=(?!=)|\bsetAttribute\b|\bcreateElement(?:NS)?\b|\binnerHTML\b|\binsertAdjacentHTML\b|\bouterHTML\b"
LINK_BUILDING_LITERAL = r"(?i)<\s*a\b|\bhref\s*="
ABSOLUTE_URL = re.compile(r"(?i)\b(?:https?|ftp|wss?)://[^\s\"'<>)\]}\\]*")
CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE | re.DOTALL)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _is_local_reference(value: str) -> bool:
    """True pentru o referință care nu iese din fișierele locale: gol, #fragment, cale relativă sau data:image/."""
    text = value.strip().lower()
    if not text or text.startswith("#") or text.startswith("data:image/"):
        return True
    return not re.match(r"^[a-z][a-z0-9+.-]*:", text) and not text.startswith(("//", "\\\\"))


def _allowed_emag_url(url: str) -> bool:
    """True pentru https://www.emag.ro/<cale> fără utilizator, parolă, parametri sau fragment (decizia 4: fără parametri în URL)."""
    parts = urlsplit(url)
    return (parts.scheme == "https" and (parts.hostname or "").lower() in ALLOWED_LINK_HOSTS and not parts.username
            and not parts.password and not parts.query and not parts.fragment and parts.port is None)


def _url_violations_in_text(text: str, where: str) -> list[str]:
    """Adresele absolute din `text` (literal JS, atribut, CSS) care nu sunt spații de nume XML sau linkuri eMAG curate."""
    problems = []
    for match in ABSOLUTE_URL.finditer(text):
        url = match.group(0).rstrip(".,;")
        if url in XML_NAMESPACE_URLS or _allowed_emag_url(url):
            continue
        problems.append(f"{where}: adresa «{url}»: singura gazdă externă permisă e https://www.emag.ro/ (fără parametri), pentru linkurile deschise la clic; orice altceva ar fi o cerere sau o ieșire din calculator")
    return problems


def js_violations(text: str, label: str, line_offset: int = 0, allowed: tuple[str, ...] = ()) -> list[str]:
    """Încălcările dintr-un text JavaScript: tipare de cod, resurse create din literale, adrese și etichete în literale.

    `allowed` = etichetele regulilor de cod care nu se aplică (doar pentru excepția clientului API, vezi APP_API_CLIENT_FILE).
    """
    views = scan_js(text)
    problems = []
    for pattern, what in JS_CODE_RULES:
        if what in allowed:
            continue
        for match in re.finditer(pattern, views.code):
            line = views.code.count("\n", 0, match.start()) + 1 + line_offset
            problems.append(f"{label}:{line}: {what}: interfața nu are voie să facă cereri de rețea sau să navigheze singură; ea citește doar fișiere pe care le dă utilizatorul")
    for pattern, what in JS_LITERAL_RULES:
        for match in re.finditer(pattern, views.uncommented):
            line = views.uncommented.count("\n", 0, match.start()) + 1 + line_offset
            problems.append(f"{label}:{line}: {what}: ar încărca o resursă din afara fișierelor locale")
    for line, literal in views.strings:
        where = f"{label}:{line + line_offset}"
        problems.extend(_url_violations_in_text(literal, where))
        if HTML_IN_TEXT_PATTERN.search(literal):
            problems.append(f"{where}: un literal conține o etichetă HTML care încarcă resurse (script, img, iframe, link...): s-ar face o cerere la inserarea ei în pagină")
        if re.search(r"(?i)\bjavascript\s*:", literal) or re.search(r"(?i)\bsrc\s*=\s*['\"]?\s*(?:https?:)?//", literal):
            problems.append(f"{where}: un literal conține «javascript:» sau un src extern")
        if re.search(r"(?i)@import\b|url\(\s*['\"]?\s*(?:https?:)?//", literal):
            problems.append(f"{where}: un literal conține CSS care încarcă din afară (@import sau url(//...))")
    return problems


def css_violations(text: str, label: str, line_offset: int = 0) -> list[str]:
    """Încălcările dintr-un text CSS: `@import` și `url()` către altceva decât fișiere locale."""
    stripped = CSS_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    problems = []
    for match in re.finditer(r"@import\b", stripped, re.IGNORECASE):
        problems.append(f"{label}:{stripped.count(chr(10), 0, match.start()) + 1 + line_offset}: @import: CSS-ul nu are voie să aducă alt CSS din afară")
    for match in CSS_URL.finditer(stripped):
        if not _is_local_reference(match.group(2)):
            problems.append(f"{label}:{stripped.count(chr(10), 0, match.start()) + 1 + line_offset}: url({match.group(2)}): CSS-ul nu are voie să încarce imagini sau fonturi din afară")
    return problems


class _HtmlCollector(HTMLParser):
    """Colectează etichetele (cu linia) și conținutul blocurilor <script> și <style>."""

    def __init__(self):
        """Pregătește listele de etichete și de blocuri <script>/<style> colectate."""
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str], int]] = []
        self.blocks: list[tuple[str, str, int, dict[str, str]]] = []  # (script|style, text, linia etichetei, atribute)
        self._open: tuple[str, int, dict[str, str]] | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        """Reține eticheta; la <script>/<style> începe colectarea conținutului."""
        attributes = {name.lower(): (value or "") for name, value in attrs}
        self.tags.append((tag.lower(), attributes, self.getpos()[0]))
        if tag.lower() in {"script", "style"}:
            self._open, self._buffer = (tag.lower(), self.getpos()[0], attributes), []

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        """Adună textul din interiorul unui <script> sau <style>."""
        if self._open:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        """La </script> sau </style> încheie blocul colectat."""
        if self._open and tag.lower() == self._open[0]:
            kind, line, attributes = self._open
            self.blocks.append((kind, "".join(self._buffer), line, attributes))
            self._open = None


def html_violations(text: str, label: str) -> list[str]:
    """Încălcările dintr-un fișier HTML/SVG: etichete interzise, resurse și formulare externe, linkuri, JS și CSS inline."""
    collector = _HtmlCollector()
    collector.feed(text)
    collector.close()
    problems = []
    for tag, attrs, line in collector.tags:
        where = f"{label}:{line}"
        if tag in FORBIDDEN_TAGS:
            problems.append(f"{where}: <{tag}>: o pagină locală nu încarcă alte pagini sau obiecte încorporate")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            problems.append(f"{where}: <meta http-equiv=refresh>: ar naviga automat în altă parte")
        if tag in {"form", "button", "input"}:
            for name in ("action", "formaction"):
                if attrs.get(name, "#") not in {"", "#"}:
                    problems.append(f"{where}: <{tag} {name}=\"{attrs[name]}\">: un formular din interfață nu trimite nimic, nici local (datele se citesc cu JavaScript, din fișierul dat de utilizator)")
        for name, value in attrs.items():
            if name.startswith("on"):
                problems.extend(js_violations(value, f"{where} ({name})"))
            if name == "style":
                problems.extend(css_violations(f"x{{{value}}}", f"{where} (style)"))
            if name not in URL_ATTRIBUTES:
                continue
            if re.match(r"(?i)\s*javascript:", value):
                problems.append(f"{where}: {name}=\"javascript:...\": cod în adresă")
            elif tag in {"a", "area"} and name == "href":
                problems.extend(_link_violations(value, attrs, where))
            elif name == "ping":
                problems.append(f"{where}: ping=: trimite o notificare la fiecare clic")
            elif name == "srcset":
                candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
                problems.extend(f"{where}: srcset cu «{c}»: resursă din afara fișierelor locale" for c in candidates if not _is_local_reference(c))
            elif not _is_local_reference(value):
                problems.append(f"{where}: <{tag} {name}=\"{value}\">: încarcă o resursă din afara fișierelor locale; interfața trebuie să meargă fără internet")
    for kind, content, line, attrs in collector.blocks:
        label = f"{label}:{line} (<{kind}> inline)"
        if kind == "style":
            problems.extend(css_violations(content, label.split(" (")[0], line - 1))
        elif attrs.get("type", "text/javascript").lower() in {"text/javascript", "module", "application/javascript", ""}:
            problems.extend(js_violations(content, label.split(" (")[0], line - 1))
    return problems


def _link_violations(value: str, attrs: dict[str, str], where: str) -> list[str]:
    """Regulile pentru <a href>: local, #fragment sau https://www.emag.ro/... cu rel=noopener noreferrer."""
    text = value.strip()
    if _is_local_reference(text) and not text.lower().startswith("data:"):
        problems = []
    elif _allowed_emag_url(text):
        rel = set(attrs.get("rel", "").lower().split())
        privacy = "noreferrer" in rel or attrs.get("referrerpolicy", "").lower() == "no-referrer"
        problems = [] if "noopener" in rel and privacy else [
            f"{where}: link către eMAG fără rel=\"noopener noreferrer\" (sau referrerpolicy=\"no-referrer\"): pagina eMAG ar primi legătura cu fereastra ta și adresa din care vii"]
    else:
        problems = [f"{where}: <a href=\"{text}\">: singurele linkuri externe permise sunt https://www.emag.ro/... fără parametri; altceva scoate utilizatorul din interfață fără ca programul să știe unde"]
    if attrs.get("target", "").lower() == "_blank" and "noopener" not in attrs.get("rel", "").lower().split():
        problems.append(f"{where}: link cu target=\"_blank\" fără rel=\"noopener\"")
    return problems


def emag_link_hardening_problems(text: str, label: str) -> list[str]:
    """Un fișier JS care CONSTRUIEȘTE linkuri (spre eMAG sau cu target=_blank) trebuie să ceară și rel=noopener, și fără referrer.

    Linkurile construite în JavaScript nu se văd la analiza HTML; măcar existența cuvintelor în același fișier se poate verifica.
    Un fișier de DATE (ex. demo-data.js: o atribuire de obiect cu adrese ca text, fără cod care face linkuri) nu intră aici:
    adresele lui sunt verificate separat, una câte una, ca orice literal.
    """
    views = scan_js(text)
    builds_links = re.search(LINK_BUILDING_CODE, views.code) or any(re.search(LINK_BUILDING_LITERAL, literal) for _, literal in views.strings)
    mentions_emag = any("https://www.emag.ro/" in literal for _, literal in views.strings)
    opens_new_tab = any("_blank" in literal for _, literal in views.strings)
    if not builds_links or not (mentions_emag or opens_new_tab):
        return []
    problems = []
    if "noopener" not in views.uncommented:
        problems.append(f"{label}: construiește linkuri (către eMAG sau în filă nouă), dar nu apare «noopener» (rel=\"noopener noreferrer\"): pagina deschisă ar primi legătura cu fereastra ta")
    if "noreferrer" not in views.uncommented and "no-referrer" not in views.uncommented:
        problems.append(f"{label}: construiește linkuri (către eMAG sau în filă nouă), dar nu apare «noreferrer» sau referrerpolicy=\"no-referrer\": pagina deschisă ar afla adresa din care vii")
    return problems


def app_api_client_problems(text: str, label: str) -> list[str]:
    """Regulile pentru singurul fișier JS care are voie `fetch()`: un singur apel, cu calea dată de `request(...)`, iar fiecare `request(...)` pornește dintr-un literal «/api/...».

    Așa pagina vorbește doar cu aplicația locală de pe aceeași origine (căi relative /api/...): nicio adresă externă, nicio cale calculată din ce vine de afară.
    """
    views = scan_js(text)
    problems = []
    code_fetches = len(re.findall(r"\bfetch\s*\(", views.code))
    path_fetches = len(re.findall(r"\bfetch\s*\(\s*path\s*,", views.uncommented))
    if code_fetches != 1 or path_fetches != 1:
        problems.append(
            f"{label}: trebuie exact un fetch(path, ...), în funcția `request` (am găsit {code_fetches} apeluri în cod și {path_fetches} cu `path`): "
            "toate cererile trebuie să treacă printr-un singur loc, ca să se vadă unde pleacă")
    for match in re.finditer(r"(?<!function )(?<![\w$.])request\s*\(", views.uncommented):
        tail = views.uncommented[match.end():match.end() + 80]
        if not re.match(r"\s*['\"](?:GET|POST)['\"]\s*,\s*['\"]" + re.escape(APP_API_PATH_PREFIX), tail):
            line = views.uncommented.count("\n", 0, match.start()) + 1
            problems.append(f"{label}:{line}: un apel `request(...)` nu pornește dintr-un literal «{APP_API_PATH_PREFIX}…»: pagina n-are voie să ceară altceva decât API-ul aplicației locale")
    return problems


def interface_violations(path: Path) -> list[str]:
    """Încălcările unui fișier din interfata/ sau templates/, după extensie (JS, CSS, HTML/SVG)."""
    label = relative(path)
    suffix = path.suffix.lower()
    if suffix not in EXPECTED_INTERFACE_SUFFIXES:
        return [f"{label}: extensie neașteptată «{suffix}» în interfață: o interfață locală conține doar HTML, CSS, JS, imagini și fonturi; verifică manual ce e și de ce e aici"]
    if suffix not in {".js", ".css", ".html", ".htm", ".svg"}:
        return []
    text = path.read_text(encoding="utf-8")
    if suffix == ".js" and label == APP_API_CLIENT_FILE:
        return js_violations(text, label, allowed=APP_API_CLIENT_ALLOWED_RULES) + app_api_client_problems(text, label) + emag_link_hardening_problems(text, label)
    if suffix == ".js":
        return js_violations(text, label) + emag_link_hardening_problems(text, label)
    if suffix == ".css":
        return css_violations(text, label)
    return html_violations(text, label)


# ---------- teste pe fișierele reale ----------

@pytest.mark.parametrize("path", program_sources(), ids=relative)
def test_program_source_has_no_network_or_process_access(path):
    """Fiecare sursă a programului: fără module de rețea sau de procese, Playwright doar în browser_session.py, doar citiri spre pagini eMAG."""
    problems = python_network_violations(parse_source(path), relative(path))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", program_sources(), ids=relative)
def test_every_url_in_program_source_points_to_emag(path):
    """Orice adresă din codul activ (nu din docstring) e https spre emag.ro, fără utilizator sau parolă în ea."""
    problems = python_url_violations(parse_source(path), relative(path))
    assert not problems, "\n".join(problems)


def test_the_only_base_url_is_https_emag():
    """settings.BASE_URL e exact https://www.emag.ro, pentru că toate cererile programului pornesc din el."""
    parts = urlsplit(settings.BASE_URL)
    assert parts.scheme == "https" and parts.hostname == "www.emag.ro" and not parts.path.strip("/") and not parts.query, \
        f"settings.BASE_URL = «{settings.BASE_URL}»: toate cererile pornesc de aici, deci trebuie să fie exact https://www.emag.ro"


@pytest.mark.parametrize("path", interface_files(*sorted(EXPECTED_INTERFACE_SUFFIXES)), ids=relative)
def test_interface_file_makes_no_requests_and_loads_nothing_external(path):
    """Fiecare fișier din interfata/ și templates/ rămâne fără cereri de rețea sau resurse externe (singura excepție: linkuri spre emag.ro deschise la clic)."""
    problems = interface_violations(path)
    assert not problems, "\n".join(problems)


def test_interface_has_no_file_with_an_unexpected_extension():
    """Interfața conține doar fișiere de tipuri așteptate; altceva (ex. .exe, .php) cere verificare manuală."""
    unknown = [relative(p) for folder in (settings.PROJECT_ROOT / "interfata", settings.PROJECT_ROOT / "templates")
               for p in folder.rglob("*") if p.is_file() and p.suffix.lower() not in EXPECTED_INTERFACE_SUFFIXES]
    assert not unknown, f"fișiere cu extensie neașteptată în interfață: {unknown}. O interfață locală conține doar HTML, CSS, JS, imagini și fonturi; verifică manual ce sunt."


@pytest.mark.parametrize("path", program_sources(), ids=relative)
def test_program_source_listens_only_on_loopback_on_a_system_chosen_port(path):
    """Fiecare sursă: orice server sau `.bind` primește exact (127.0.0.1, 0); serverul local nu poate deveni vizibil în rețea printr-o adresă schimbată din greșeală."""
    problems = local_binding_violations(parse_source(path), relative(path))
    assert not problems, "\n".join(problems)


def test_the_local_server_exception_is_justified_and_still_needed():
    """Excepția de rețea a lui app_server.py există doar cât timp fișierul chiar e serverul (importă http.server) și chiar ascultă în cod; altfel se scoate."""
    source = PROGRAM_DIR / LOCAL_SERVER_FILE
    assert source.is_file(), f"excepția pentru {LOCAL_SERVER_FILE}: fișierul nu mai există; scoate excepția"
    tree = parse_source(source)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and not node.level}
    assert "http.server" in imported, "app_server.py nu mai importă http.server: excepția de rețea nu mai e necesară"
    assert any(isinstance(node, ast.Call) and (dotted_name(node.func) or "").rsplit(".", 1)[-1].endswith("Server") for node in ast.walk(tree)), (
        "app_server.py nu mai creează niciun server: scoate excepția")
    for other in program_sources():
        if other.name != LOCAL_SERVER_FILE:
            names = {alias.name for node in ast.walk(parse_source(other)) if isinstance(node, ast.Import) for alias in node.names}
            names |= {node.module for node in ast.walk(parse_source(other)) if isinstance(node, ast.ImportFrom) and node.module and not node.level}
            assert not [name for name in names if _module_hit(name) in LOCAL_SERVER_MODULES], f"{relative(other)} importă un modul de server, dar doar {LOCAL_SERVER_FILE} are voie"


# ---------- detectoarele văzute picând pe cod-capcană ----------

def _py(source: str, filename: str = "emag_spend/capcana.py") -> list[str]:
    """Încălcările de rețea găsite într-un fragment de cod Python, tratat ca un fișier al programului."""
    return python_network_violations(ast.parse(source), filename)


@pytest.mark.parametrize("source, expected", [
    ("import requests", "requests"), ("import urllib.request", "urllib.request"), ("from urllib import request", "urllib.request"),
    ("import socket", "socket"), ("from socket import create_connection", "socket"), ("import subprocess", "subprocess"),
    ("import ctypes", "ctypes"), ("import smtplib", "smtplib"), ("import http.client", "http.client"), ("import xmlrpc.client", "xmlrpc"),
    ("import websockets", "websockets"), ("import httpx", "httpx"), ("import aiohttp", "aiohttp"), ("import ssl", "ssl"),
    ("import ftplib", "ftplib"), ("import telnetlib", "telnetlib"), ("import webbrowser", "webbrowser"),
    ("from playwright.async_api import async_playwright", "Playwright"), ("import playwright", "Playwright"),
    ("import os\nos.system('x')", "os.system"), ("import os\nos.popen('x')", "os.popen"), ("import os\nos.startfile('x')", "os.startfile"),
    ("eval('1')", "eval"), ("__import__('socket')", "__import__"), ("import importlib\nimportlib.import_module('socket')", "import_module"),
    ("import urllib\nurllib.request.urlopen('x')", "urllib.request"),
    ("async def f(c):\n    await c.request.post('https://www.emag.ro/x')", ".request.post"),
    ("async def f(p):\n    await p.route('**', None)", ".route"), ("def f(p):\n    p.expose_function('x', None)", "expose_function"),
    ("def f(p):\n    p.add_init_script('x')", "add_init_script"),
    ("import asyncio\nasync def f():\n    await asyncio.open_connection('x', 1)", "open_connection"),
    ("async def f(p):\n    await p.evaluate('() => fetch(\"x\")')", "fetch()"),
    ("async def f(p):\n    await p.evaluate('() => navigator.sendBeacon(\"x\")')", "sendBeacon"),
    ("async def f(p, u):\n    await p.goto(u)", "settings.BASE_URL"),
    ("async def f(c):\n    await c.request.get('https://www.emag.ro/x')", "settings.BASE_URL"),
])
def test_network_detector_catches_trap_code(source, expected):
    """Capcană: fiecare import sau apel periculos de rețea (requests, socket, os.system, route, goto fără BASE_URL...) trebuie prins de detector."""
    problems = " | ".join(_py(source))
    assert expected in problems, f"nu a fost prins «{expected}» în:\n{source}\n(rezultat: {problems or 'nimic'})"


def test_network_detector_allows_the_documented_exceptions():
    """Fals pozitiv: excepțiile documentate (clasele de eroare Playwright, browser_session, report_opener, adrese din settings.BASE_URL) nu sunt încălcări."""
    allowed = [
        ("from playwright.async_api import Error, TimeoutError as T", "emag_spend/ceva.py"),
        ("from playwright.async_api import async_playwright", "emag_spend/browser_session.py"),
        ("import webbrowser\nwebbrowser.open(path.as_uri())", "emag_spend/report_opener.py"),
        ("from emag_spend import settings\nasync def f(c, p):\n    url = settings.BASE_URL + p\n    await c.request.get(url)", "emag_spend/x.py"),
        ("from emag_spend import settings\nasync def f(page):\n    await page.goto(settings.BASE_URL + '/a')", "emag_spend/x.py"),
    ]
    for source, filename in allowed:
        assert python_network_violations(ast.parse(source), filename) == [], source


@pytest.mark.parametrize("text, hit", [
    ("URL = 'http://www.emag.ro/x'", True), ("URL = 'https://exemplu.invalid/x'", True), ("URL = 'https://www.emag.ro.exemplu.invalid/'", True),
    ("URL = 'https://evil.example/?u=www.emag.ro'", True), ("URL = 'https://user@evil.example/'", True), ("URL = 'ftp://www.emag.ro/'", True),
    ("URL = 'https://www.emag.ro/history'", False), ("URL = 'https://emag.ro/'", False), ("'''doc https://exemplu.invalid'''", False),
    ("def f():\n    '''doc https://exemplu.invalid'''", False),
])
def test_url_detector_flags_every_host_but_emag(text, hit):
    """Detectorul de adrese acceptă doar https către emag.ro și respinge http, alte gazde, gazde păcălitoare și adrese cu utilizator."""
    assert bool(python_url_violations(ast.parse(text), "x.py")) is hit, text


def test_interface_detectors_catch_trap_pages():
    """Capcană: ~40 de pagini, scripturi și foi CSS cu cereri sau resurse externe trebuie toate prinse de detectoarele interfeței."""
    traps = {
        "fetch": ("a.js", "fetch('/x');"), "root_fetch": ("a.js", "root.fetch(u);"), "xhr": ("a.js", "var x = new XMLHttpRequest();"),
        "ws": ("a.js", "new WebSocket(u);"), "beacon": ("a.js", "navigator.sendBeacon(u, d);"), "import": ("a.js", "import('x.js');"),
        "open": ("a.js", "root.open(u);"), "img": ("a.js", "new Image().src = u;"), "location": ("a.js", "root.location.href = u;"),
        "tpl": ("a.js", "var t = `${fetch(u)}`;"), "evalx": ("a.js", "eval(s);"), "timer": ("a.js", "setTimeout('x()', 1);"),
        "setattr": ("a.js", "e.setAttribute('src', u);"), "create": ("a.js", "document.createElement('script');"),
        "url_in_string": ("a.js", "var u = 'https://exemplu.invalid/x';"), "img_in_string": ("a.js", "box.innerHTML = '<img src=x>';"),
        "css_import": ("a.css", "@import 'x.css';"), "css_url": ("a.css", "a { background: url(https://exemplu.invalid/x.png); }"),
        "css_url2": ("a.css", "a { background: url(//exemplu.invalid/x.png); }"),
        "script_src": ("a.html", "<script src='https://exemplu.invalid/x.js'></script>"), "script_src2": ("a.html", "<script src='//exemplu.invalid/x.js'></script>"),
        "link": ("a.html", "<link rel=stylesheet href='https://exemplu.invalid/x.css'>"), "img": ("a.html", "<img src='https://exemplu.invalid/x.png'>"),
        "emag_img": ("a.html", "<img src='https://www.emag.ro/x.png'>"), "iframe": ("a.html", "<iframe src='x.html'></iframe>"),
        "form": ("a.html", "<form action='https://exemplu.invalid/'></form>"), "formaction": ("a.html", "<button formaction='https://exemplu.invalid/'>x</button>"),
        "link_ext": ("a.html", "<a href='https://exemplu.invalid/'>x</a>"), "link_emag_bare": ("a.html", "<a href='https://www.emag.ro/x'>x</a>"),
        "link_emag_query": ("a.html", "<a href='https://www.emag.ro/x?a=1' rel='noopener noreferrer'>x</a>"), "mailto": ("a.html", "<a href='mailto:x@exemplu.invalid'>x</a>"),
        "jsurl": ("a.html", "<a href='javascript:alert(1)'>x</a>"), "ping": ("a.html", "<a href='#' ping='https://exemplu.invalid/'>x</a>"),
        "blank": ("a.html", "<a href='x.html' target='_blank'>x</a>"), "onclick": ("a.html", "<button onclick=\"fetch('x')\">x</button>"),
        "inline_script": ("a.html", "<script>fetch('x');</script>"), "inline_style": ("a.html", "<style>a{background:url(https://exemplu.invalid/x)}</style>"),
        "style_attr": ("a.html", "<div style='background:url(https://exemplu.invalid/x)'>x</div>"), "refresh": ("a.html", "<meta http-equiv='refresh' content='0;url=x'>"),
        "base": ("a.html", "<base href='x/'>"), "svg_image": ("a.svg", "<svg><image href='https://exemplu.invalid/x.png'/></svg>"),
    }
    def run(name, text):
        """Rulează detectorul potrivit extensiei din numele dat."""
        if name.endswith(".js"):
            return js_violations(text, name)
        return css_violations(text, name) if name.endswith(".css") else html_violations(text, name)
    missed = [key for key, (name, text) in traps.items() if not run(name, text)]
    assert not missed, f"capcane neprinse: {missed}"


def test_emag_link_hardening_detector():
    """Un JS care construiește linkuri spre eMAG trebuie să ceară și noopener, și noreferrer în cod, nu doar într-un comentariu."""
    bare = "var base = 'https://www.emag.ro/history/shoppingdetails/'; a.href = base + id;"
    hardened = bare + " a.rel = 'noopener noreferrer'; a.target = '_blank';"
    assert len(emag_link_hardening_problems(bare, "x.js")) == 2
    assert emag_link_hardening_problems(hardened, "x.js") == []
    assert emag_link_hardening_problems("var t = 'fără linkuri'; // noopener", "x.js") == []
    assert len(emag_link_hardening_problems(bare + " // rel noopener noreferrer", "x.js")) == 2, "un comentariu nu înlocuiește codul"
    data_only = 'window.EMAG_DEMO_DATA = {"warnings": [{"link": "https://www.emag.ro/user/return-history/1/2"}]};'
    assert emag_link_hardening_problems(data_only, "date.js") == [], "un fișier de date cu adrese ca text nu construiește linkuri"
    new_tab = "var a = document.createElement('a'); a.target = '_blank'; a.href = u;"
    assert len(emag_link_hardening_problems(new_tab, "x.js")) == 2, "un link care se deschide în filă nouă cere noopener și noreferrer chiar dacă adresa vine din date"
    assert emag_link_hardening_problems(new_tab + " a.rel = 'noopener noreferrer';", "x.js") == []


def test_interface_detectors_ignore_words_in_text_and_allow_the_documented_cases():
    """Fals pozitiv: cuvinte ca fetch în texte, expresii regulate, spații de nume SVG și linkuri eMAG curate nu sunt încălcări."""
    clean = {
        "prose_js": ("a.js", "var t = 'Pagina nu apelează fetch() și nu folosește XMLHttpRequest sau WebSocket.'; // fetch(x)\n/* sendBeacon */"),
        "regex_js": ("a.js", "var r = /fetch\\(/g; var d = a / b;"),
        "svg_ns": ("a.js", "document.createElementNS('http://www.w3.org/2000/svg', 'svg');"),
        "emag_link_js": ("a.js", "var base = 'https://www.emag.ro/history/shoppingdetails/';"),
        "local_storage": ("a.js", "root.localStorage.setItem('k', v); root.location.hash = '#x'; navigator.clipboard.writeText(t);"),
        "css_data": ("a.css", "a { background: url(data:image/png;base64,AAAA); } b { fill: url(#g); } c { background: url(img/x.png); }"),
        "html_local": ("a.html", "<link rel=stylesheet href='assets/a.css'><script src='assets/a.js'></script><img src='data:image/png;base64,AAAA'><a href='#x'>x</a><a href='b.html'>b</a>"),
        "html_emag": ("a.html", "<a href='https://www.emag.ro/history/shoppingdetails/123' target='_blank' rel='noopener noreferrer'>x</a>"),
        "html_text_url": ("a.html", "<p>Descarcă Python de pe https://www.python.org/downloads/ și caută fetch() în documentație.</p>"),
        "json_script": ("a.html", "<script type='application/json'>{\"u\": \"https://exemplu.invalid\"}</script>"),
    }
    for key, (name, text) in clean.items():
        found = js_violations(text, name) if name.endswith(".js") else css_violations(text, name) if name.endswith(".css") else html_violations(text, name)
        assert not found, f"fals pozitiv pe «{key}»: {found}"


# ---------- la execuție: fluxurile programului cu socket-urile blocate ----------

BLOCKED_SOCKET_FUNCTIONS = ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr")
BLOCKED_SOCKET_METHODS = ("connect", "connect_ex", "sendto")
# Evenimentele de audit prin care s-ar vedea o cerere de rețea sau un proces nou, chiar dacă cineva ocolește funcțiile de mai sus.
NETWORK_AUDIT_EVENTS = ("socket.*", "urllib.Request", "http.client.*", "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "ctypes.*")


@pytest.fixture
def blocked_network(monkeypatch):
    """Înlocuiește funcțiile de rețea din `socket` cu unele care notează încercarea și ridică eroare.

    Notarea contează: un `except Exception` din cod ar putea înghiți eroarea și testul ar trece fals.
    """
    attempts: list[str] = []

    def refuse(name):
        """Fabrică o funcție care notează încercarea de rețea și ridică OSError."""
        def blocked(*args, **kwargs):
            """Înlocuiește funcția de rețea: notează încercarea și refuză."""
            attempts.append(f"{name}{args[1:2] if args else ''}")
            raise OSError(f"rețea blocată de test ({name})")
        return blocked

    for name in BLOCKED_SOCKET_FUNCTIONS:
        monkeypatch.setattr(socket, name, refuse(f"socket.{name}"))
    for name in BLOCKED_SOCKET_METHODS:
        monkeypatch.setattr(socket.socket, name, refuse(f"socket.socket.{name}"))
    return attempts


def test_audit_recorder_attributes_network_events_to_the_program_and_ignores_other_code():
    """Un `bind` local (fără trafic) cerut din cod care pretinde că e din program trebuie notat; același apel din test, nu."""
    namespace: dict = {}
    source = "import socket\ndef leaga():\n    with socket.socket() as s:\n        s.bind(('127.0.0.1', 0))\n"
    exec(compile(source, str(Path(settings.PROJECT_ROOT) / "emag_spend" / "capcana.py"), "exec"), namespace)  # noqa: S102 - cod fix, scris în test
    with AuditRecorder(NETWORK_AUDIT_EVENTS) as audit:
        namespace["leaga"]()
        with socket.socket() as own:  # același tip de operație, dar făcută de test, nu de program
            own.bind(("127.0.0.1", 0))
    assert [e.name for e in audit.events].count("socket.bind") == 1, f"trebuia notat un singur bind (al programului): {[e.name for e in audit.events]}"
    assert all(e.where.startswith("emag_spend/capcana.py:") for e in audit.events)


def test_the_network_block_really_blocks_and_records(blocked_network):
    """Blocajul de rețea din test chiar oprește create_connection, connect și getaddrinfo și notează încercările (altfel testele de flux n-ar dovedi nimic)."""
    with pytest.raises(OSError, match="rețea blocată"):
        socket.create_connection(("exemplu.invalid", 80))
    with pytest.raises(OSError, match="rețea blocată"):
        socket.socket().connect(("192.0.2.1", 80))
    with pytest.raises(OSError, match="rețea blocată"):
        socket.getaddrinfo("exemplu.invalid", 80)
    assert len(blocked_network) == 3


@pytest.mark.parametrize("flow", FLOWS)
def test_program_flows_make_no_network_call_and_open_only_the_local_report(flow, tmp_path, monkeypatch, blocked_network):
    """La execuție: fluxurile --demo, --din-cache și --sterge-sesiunea nu ating rețeaua și deschid cel mult raportul local generat."""
    with isolated_program(monkeypatch, tmp_path) as layout, AuditRecorder(NETWORK_AUDIT_EVENTS) as audit:
        code = run_flow(prepare_flow(flow, layout))
    assert code == 0, f"fluxul {flow} nu s-a terminat cu succes, deci testul n-ar fi dovedit nimic"
    if flow != "sterge_sesiunea":
        assert any(layout.out.rglob("raport.html")), "fluxul nu a produs raportul: testul n-ar fi dovedit nimic"
    assert not blocked_network, f"programul a încercat să folosească rețeaua în fluxul {flow}: {blocked_network}"
    assert not audit.events, "evenimente de rețea sau de procese atribuite programului: " + "; ".join(f"{e.name} la {e.where}" for e in audit.events)
    reports = {report.resolve().as_uri() for report in layout.out.rglob("raport.html")}
    for target in layout.opened:
        assert target in reports, f"programul a cerut să deschidă «{target}», nu raportul local pe care tocmai l-a generat ({sorted(reports)})"
    if flow == "demo_si_deschide":
        assert len(layout.opened) == 1, f"trebuia să ceară o singură deschidere (raportul), a cerut: {layout.opened}"
    else:
        assert layout.opened == [], f"fără --deschide programul nu are voie să deschidă nimic, dar a cerut: {layout.opened}"



# ---------- excepția serverului local: văzută funcționând și picând ----------

def _py_in(source: str, filename: str) -> list[str]:
    """Încălcările de rețea dintr-un fragment de cod, tratat ca fișierul `filename` al programului."""
    return python_network_violations(ast.parse(source), filename)


@pytest.mark.parametrize("source", [
    "import http.server", "from http.server import ThreadingHTTPServer", "import socketserver", "from socketserver import ThreadingMixIn",
    "import socket", "import socket\nx = socket.SO_EXCLUSIVEADDRUSE", "from socket import SOL_SOCKET",
])
def test_the_server_modules_are_allowed_only_in_app_server(source):
    """Modulele de server (http.server, socketserver, socket) trec în app_server.py și sunt prinse în ORICE alt fișier al programului."""
    assert _py_in(source, "emag_spend/app_server.py") == [], f"excepția nu funcționează în app_server.py pentru: {source}"
    for other in ("emag_spend/app_runner.py", "emag_spend/browser_session.py", "ruleaza.py", "emag_spend/capcana.py"):
        assert _py_in(source, other), f"«{source}» a trecut în {other}: orice alt modul trebuie să rămână fără rețea"


@pytest.mark.parametrize("source, expected", [
    ("import ssl", "ssl"), ("import subprocess", "subprocess"), ("import urllib.request", "urllib.request"), ("import requests", "requests"),
    ("import http.client", "http.client"), ("import smtplib", "smtplib"), ("import ctypes", "ctypes"),
    ("import socket\ndef f(s):\n    s.connect(('exemplu.invalid', 80))", ".connect()"),
    ("import socket\ndef f(s):\n    s.connect_ex(('exemplu.invalid', 80))", ".connect_ex()"),
    ("import socket\ndef f(s):\n    s.sendto(b'x', ('exemplu.invalid', 80))", ".sendto()"),
    ("import socket\nsocket.create_connection(('exemplu.invalid', 80))", "create_connection"),
    ("import socket\nsocket.getaddrinfo('exemplu.invalid', 80)", "getaddrinfo"),
    ("import socket\nsocket.gethostbyaddr('127.0.0.1')", ".gethostbyaddr()"), ("import socket\nsocket.getfqdn('127.0.0.1')", ".getfqdn()"),
])
def test_even_app_server_gets_no_outgoing_connections_or_other_network_modules(source, expected):
    """Chiar și în app_server.py: nicio conexiune ieșită, nicio interogare de nume (DNS) și niciun alt modul de rețea (ssl, requests, subprocess...)."""
    problems = " | ".join(_py_in(source, "emag_spend/app_server.py"))
    assert expected in problems, f"nu a fost prins «{expected}» în app_server.py:\n{source}\n(rezultat: {problems or 'nimic'})"


@pytest.mark.parametrize("source", [
    "import http.server\nhttp.server.ThreadingHTTPServer(('0.0.0.0', 0), H)", "import http.server\nhttp.server.ThreadingHTTPServer(('', 0), H)",
    "import http.server\nhttp.server.ThreadingHTTPServer(('::', 0), H)", "import http.server\nhttp.server.ThreadingHTTPServer(('localhost', 0), H)",
    "import http.server\nhttp.server.ThreadingHTTPServer(('127.0.0.1', 8080), H)", "import http.server\nhttp.server.ThreadingHTTPServer(('127.0.0.1', 80), H)",
    "import http.server\nHOST = '0.0.0.0'\nhttp.server.ThreadingHTTPServer((HOST, 0), H)", "import http.server\nPORT = 8000\nhttp.server.ThreadingHTTPServer(('127.0.0.1', PORT), H)",
    "import http.server, socket\nhttp.server.ThreadingHTTPServer((socket.gethostname(), 0), H)", "import http.server\ndef f(host):\n    http.server.ThreadingHTTPServer((host, 0), H)",
    "import http.server\nhttp.server.ThreadingHTTPServer(address, H)", "import http.server\nhttp.server.ThreadingHTTPServer()", "import http.server\nhttp.server.HTTPServer(('0.0.0.0', 0), H)",
    "import socketserver\nsocketserver.TCPServer(('0.0.0.0', 0), H)", "import socket\ns = socket.socket()\ns.bind(('0.0.0.0', 0))", "import socket\ns = socket.socket()\ns.bind(('', 0))",
    "import socket\ns = socket.socket()\ns.bind(('::', 0))", "import socket\ns = socket.socket()\ns.bind(('localhost', 0))", "import socket\ns = socket.socket()\ns.bind(('127.0.0.1', 5000))",
    "import socket\ns = socket.socket()\ns.bind(addr)", "import http.server\nclass _S(http.server.ThreadingHTTPServer):\n    pass\n_S(('0.0.0.0', 0), H)",
    "from http.server import ThreadingHTTPServer as T\nclass _S(T):\n    pass\nclass _U(_S):\n    pass\n_U(('0.0.0.0', 0), H)",
    "import http.server\nhttp.server.ThreadingHTTPServer(('127.0.0.1', True), H)",
])
def test_binding_detector_catches_every_address_but_loopback_with_port_zero(source):
    """Capcană: 0.0.0.0, «», «::», «localhost», un port fix, o adresă calculată sau necunoscută și orice altceva decât (127.0.0.1, 0) trebuie prinse (testul pică la ele)."""
    assert local_binding_violations(ast.parse(source), "emag_spend/app_server.py"), f"adresa nu a fost prinsă în:\n{source}"


@pytest.mark.parametrize("source", [
    "import http.server\nhttp.server.ThreadingHTTPServer(('127.0.0.1', 0), H)",
    "import http.server\nLOOPBACK_HOST = '127.0.0.1'\nANY_FREE_PORT = 0\nhttp.server.ThreadingHTTPServer((LOOPBACK_HOST, ANY_FREE_PORT), H)",
    "import http.server\nLOOPBACK_HOST = '127.0.0.1'\nclass _L(http.server.ThreadingHTTPServer):\n    pass\n_L((LOOPBACK_HOST, 0), H)",
    "import socket\ns = socket.socket()\ns.bind(('127.0.0.1', 0))", "x = 1\nprint(x)",
])
def test_binding_detector_accepts_loopback_with_port_zero(source):
    """Fals pozitiv: exact (127.0.0.1, 0), direct sau prin constante de modul, nu e încălcare; codul fără servere nu e atins."""
    assert local_binding_violations(ast.parse(source), "emag_spend/app_server.py") == []


def test_webbrowser_may_open_only_a_validated_variable_and_only_in_the_app_opener():
    """webbrowser.open(<variabilă>) trece doar în app_opener.py; în report_opener.py rămâne doar `.as_uri()`, iar un URL scris în cod sau alte metode sunt prinse oriunde."""
    assert _py_in("import webbrowser\ndef f(url):\n    webbrowser.open(url)", "emag_spend/app_opener.py") == []
    assert _py_in("import webbrowser\ndef f(path):\n    webbrowser.open(path.as_uri())", "emag_spend/report_opener.py") == []
    assert _py_in("import webbrowser\ndef f(url):\n    webbrowser.open(url)", "emag_spend/report_opener.py"), "o variabilă oarecare a trecut în report_opener.py"
    assert _py_in("import webbrowser\ndef f(url):\n    webbrowser.open(url)", "emag_spend/capcana.py"), "importul de webbrowser a trecut într-un fișier neautorizat"
    for bad in ("webbrowser.open('https://exemplu.invalid')", "webbrowser.open(url, new=2)", "webbrowser.open_new(url)", "webbrowser.open_new_tab(url)",
                "webbrowser.open(url + '/x')", "webbrowser.get().open(url)"):
        assert _py_in(f"import webbrowser\ndef f(url):\n    {bad}", "emag_spend/app_opener.py"), f"«{bad}» a trecut în app_opener.py"


def test_the_two_opener_files_exist_and_still_need_their_exceptions():
    """Excepțiile pentru webbrowser acoperă fișiere care există și chiar îl importă (altfel se scot)."""
    for name in WEBBROWSER_MODULE_FILES:
        source = PROGRAM_DIR / name
        assert source.is_file(), f"excepția webbrowser pentru {name}: fișierul nu mai există; scoate-o"
        assert "webbrowser" in {alias.name for node in ast.walk(parse_source(source)) if isinstance(node, ast.Import) for alias in node.names}, (
            f"{name} nu mai importă webbrowser: scoate excepția")


# ---------- la execuție: serverul local ascultă doar pe 127.0.0.1 și nu face nicio cerere spre exterior ----------

def test_the_running_local_server_binds_only_to_loopback_port_zero_and_makes_no_outgoing_network_call(tmp_path, monkeypatch, blocked_network):
    """Serverul REAL, pornit sub observație: toate legările de socket atribuite programului sunt (127.0.0.1, 0), iar conexiuni ieșite sau interogări de nume nu apar deloc."""
    from emag_spend.app_server import AppServer

    audited = ("socket.bind", "socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.gethostbyname_ex", "socket.sendto",
               "socket.getnameinfo", "urllib.Request", "http.client.*", "subprocess.Popen")
    with AuditRecorder(audited) as audit:
        server = AppServer(outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil", interface_dir=tmp_path / "interfata")
        server.close()
    binds = [event for event in audit.events if event.name == "socket.bind"]
    assert len(binds) == 1, f"trebuia o singură legare de socket din program, am văzut {[(e.name, e.args[1:]) for e in audit.events]}: hook-ul nu prinde nimic sau serverul face mai mult decât ascultă"
    assert binds[0].args[1] == (LOOPBACK_ADDRESS, FREE_PORT_VALUE), f"serverul s-a legat la {binds[0].args[1]!r}, nu la (127.0.0.1, 0)"
    others = [event for event in audit.events if event.name != "socket.bind"]
    assert not others, "serverul local a făcut conexiuni sau interogări de nume: " + "; ".join(f"{e.name} la {e.where}" for e in others)
    assert not blocked_network, f"serverul a încercat să folosească rețeaua blocată de test: {blocked_network}"


# ---------- excepția clientului API al paginii aplicației ----------

GOOD_CLIENT = (
    "function request(method, path, options) { return root.fetch(path, { method: method }); }\n"
    "function a() { return request('GET', '/api/state'); }\n"
    "function b(id) { return request('GET', '/api/runs/' + id + '/analysis', { timeoutMs: 5 }); }\n"
    "function c() { return request(\"POST\", \"/api/runs\", { body: {} }); }\n"
    "// fetch('https://exemplu.invalid') într-un comentariu nu contează\n"
    "var t = 'text care menționează fetch(x) fără să-l apeleze';\n"
)


def _client(source: str) -> list[str]:
    """Toate încălcările pe care garda de interfață le-ar găsi într-un fișier JS tratat ca clientul API al aplicației."""
    return js_violations(source, APP_API_CLIENT_FILE, allowed=APP_API_CLIENT_ALLOWED_RULES) + app_api_client_problems(source, APP_API_CLIENT_FILE)


def test_the_api_client_exception_accepts_the_expected_shape():
    """Fals pozitiv: un client cu un singur fetch(path, ...) și request(...) doar spre «/api/...» (și cu comentarii sau texte care pomenesc fetch) nu e încălcare."""
    assert _client(GOOD_CLIENT) == []


@pytest.mark.parametrize("source, expected", [
    (GOOD_CLIENT + "function d() { return request('GET', 'https://exemplu.invalid/x'); }", "request(...)"),
    (GOOD_CLIENT + "function d(u) { return request('GET', u); }", "request(...)"),
    (GOOD_CLIENT + "function d(m, u) { return request(m, '/api/x'); }", "request(...)"),
    (GOOD_CLIENT + "function d() { return request('DELETE', '/api/x'); }", "request(...)"),
    (GOOD_CLIENT + "function d() { return request('GET', '/alt/x'); }", "request(...)"),
    (GOOD_CLIENT + "function d() { return request('GET', '//exemplu.invalid/api/x'); }", "request(...)"),
    (GOOD_CLIENT + "function d(u) { return root.fetch(u, {}); }", "fetch(path"),
    (GOOD_CLIENT + "function d() { return root.fetch('/api/state'); }", "fetch(path"),
    (GOOD_CLIENT.replace("root.fetch(path,", "root.fetch(url,"), "fetch(path"),
    (GOOD_CLIENT.replace("return root.fetch(path, { method: method });", "return null;"), "fetch(path"),
    (GOOD_CLIENT + "var x = new XMLHttpRequest();", "XMLHttpRequest"), (GOOD_CLIENT + "var s = new WebSocket(u);", "WebSocket"),
    (GOOD_CLIENT + "navigator.sendBeacon(u, d);", "sendBeacon"), (GOOD_CLIENT + "var u = 'https://exemplu.invalid/x';", "adresa"),
    (GOOD_CLIENT + "root.location.href = u;", "navigare"), (GOOD_CLIENT + "eval(s);", "eval"), (GOOD_CLIENT + "import('x.js');", "import()"),
])
def test_the_api_client_exception_is_narrow(source, expected):
    """Capcană: în clientul API tot ce iese din forma «un fetch(path), request(...) spre /api/...» (adresă externă, cale calculată, al doilea fetch, XHR, WebSocket, navigare) pică."""
    problems = " | ".join(_client(source))
    assert expected in problems, f"nu a fost prins «{expected}» în clientul API:\n{source}\n(rezultat: {problems or 'nimic'})"


def test_fetch_is_refused_in_every_interface_file_except_the_api_client():
    """Orice alt fișier JS din interfață (site-ul explicativ, componenta de raport, restul paginii aplicației) rămâne fără fetch(): excepția e doar pentru un fișier."""
    for path in interface_files(".js"):
        if relative(path) == APP_API_CLIENT_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        assert not [p for p in js_violations(text, relative(path)) if "fetch()" in p], f"{relative(path)} cheamă fetch(): doar {APP_API_CLIENT_FILE} are voie"
    assert js_violations("fetch('/api/state');", "interfata/assets/app-alt.js"), "un fetch într-un alt fișier al aplicației ar trebui prins"
    assert js_violations("fetch('/api/state');", "interfata/assets/site-viewer.js"), "un fetch în site-ul explicativ ar trebui prins"


def test_the_api_client_exception_is_still_needed():
    """Excepția pentru app-api.js există doar cât timp fișierul chiar cheamă fetch (altfel se scoate și interfața rămâne fără nicio cerere)."""
    path = PROGRAM_DIR.parent / APP_API_CLIENT_FILE
    if not path.is_file():
        pytest.skip(f"{APP_API_CLIENT_FILE} nu există încă (îl scrie agentul paginii aplicației); excepția rămâne neverificată")
    assert re.search(r"\bfetch\s*\(", scan_js(path.read_text(encoding="utf-8")).code), f"{APP_API_CLIENT_FILE} nu mai cheamă fetch: scoate excepția din garda de rețea"
