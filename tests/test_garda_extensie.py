"""Garda extensiei Chrome: permisiunile din manifest, ce are voie codul din extensie/src și ce caractere sunt în extensie/.

Primește: extensie/manifest.json, extensie/src/** (JS, HTML, CSS) și tot ce urcă în git din extensie/ (tests.garda_support.files_to_publish).
Verifică: (1) manifestul cere exact permisiunile `storage` și `scripting` și accesul la https://www.emag.ro/*, fără scripturi de conținut, resurse accesibile din web, conectare externă sau politică de conținut proprie;
(2) în JS: `fetch` doar în colectare/page_functions.js, fără alte căi de rețea sau de cod dinamic (XMLHttpRequest, WebSocket, eval, innerHTML, chrome.cookies...), adrese în literale doar https://www.emag.ro, importuri doar relative;
(3) în HTML: fără script inline și fără resurse de pe alte gazde; în CSS: fără @import sau url() către alte gazde; (4) în tot extensie/ (fără node_modules, dist, build): fără caractere invizibile, fără NBSP și fără litere cu sedilă;
(5) nimic din extensie/ nu e ignorat de git în tăcere. Fiecare detector e probat pe un cod-capcană care trebuie să pice (și pe cod curat care nu trebuie să pice).
Ce NU face: nu e un analizor complet de JavaScript (la îndoială, e mai strict), nu citește extensia construită din dist/ și nu o rulează (asta fac testele din extensie/tests/e2e/, cu rețeaua blocată).
"""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from tests.garda_js_scan import scan_js
from tests.garda_support import PROJECT_ROOT, files_to_publish, read_text_or_none, relative
from tests.test_garda_caractere import hidden_character_problems

EXTENSION_DIR = PROJECT_ROOT / "extensie"
SOURCE_DIR = EXTENSION_DIR / "src"
MANIFEST_FILE = EXTENSION_DIR / "manifest.json"
# Singurul fișier în care are voie `fetch`: funcția injectată în fila eMAG de lucru (E5), care cere doar căi relative la originea paginii.
FETCH_FILE = "extensie/src/colectare/page_functions.js"
GIT_TIMEOUT_SECONDS = 60

# ---------- manifest ----------

MANIFEST_VERSION = 3
ALLOWED_PERMISSIONS = ["scripting", "storage"]
ALLOWED_HOST_PERMISSIONS = ["https://www.emag.ro/*"]
# Chei de manifest interzise, cu motivul (specificația §3 și §12): fiecare ar lărgi ce poate face extensia dincolo de citirea paginilor din fila de lucru.
FORBIDDEN_MANIFEST_KEYS = {
    "content_scripts": "ar rula cod în paginile eMAG fără ca omul să fi apăsat nimic; intrarea extensiei e doar iconița",
    "web_accessible_resources": "ar face fișiere ale extensiei citibile de pagini web",
    "externally_connectable": "ar lăsa alte site-uri sau extensii să vorbească cu extensia",
    "content_security_policy": "se folosește politica implicită din Manifest V3 (script-src 'self'; object-src 'self'); una proprie ar putea-o slăbi",
    "optional_permissions": "permisiuni cerute mai târziu ocolesc lista fixă de mai sus",
    "optional_host_permissions": "accese cerute mai târziu ocolesc lista fixă de mai sus",
    "update_url": "ar muta actualizările extensiei în afara magazinului",
}
# Singurele chei de nivel superior folosite azi. O cheie nouă (comenzi, pagini de înlocuire, panou lateral...) cere o verificare manuală și intrarea aici.
ALLOWED_MANIFEST_KEYS = frozenset({
    "manifest_version", "name", "description", "version", "minimum_chrome_version", "permissions", "host_permissions", "background", "action", "icons",
})
ALLOWED_BACKGROUND_KEYS = frozenset({"service_worker", "type"})


def manifest_problems(manifest: object) -> list[str]:
    """Încălcările unui manifest (obiect JSON deja citit): permisiuni, chei interzise sau necunoscute, forma lui `background`."""
    if not isinstance(manifest, dict):
        return ["manifestul nu e un obiect JSON"]
    problems = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        problems.append(f"manifest_version = {manifest.get('manifest_version')!r}: extensia e scrisă pentru Manifest V{MANIFEST_VERSION}")
    permissions = manifest.get("permissions")
    if not (isinstance(permissions, list) and all(isinstance(item, str) for item in permissions) and sorted(permissions) == ALLOWED_PERMISSIONS):
        problems.append(f"permissions = {permissions!r}: trebuie exact {ALLOWED_PERMISSIONS} (fără tabs, cookies, downloads, webRequest...)")
    if manifest.get("host_permissions") != ALLOWED_HOST_PERMISSIONS:
        problems.append(f"host_permissions = {manifest.get('host_permissions')!r}: trebuie exact {ALLOWED_HOST_PERMISSIONS} (fără <all_urls> sau alte gazde)")
    for key, reason in FORBIDDEN_MANIFEST_KEYS.items():
        if key in manifest:
            problems.append(f"cheia «{key}» e interzisă: {reason}")
    for key in manifest:
        if key not in ALLOWED_MANIFEST_KEYS and key not in FORBIDDEN_MANIFEST_KEYS:
            problems.append(f"cheie necunoscută în manifest: «{key}». Verifică ce permite și adaug-o în ALLOWED_MANIFEST_KEYS doar dacă nu lărgește accesul extensiei")
    background = manifest.get("background")
    if not isinstance(background, dict) or not set(background) <= ALLOWED_BACKGROUND_KEYS or not isinstance(background.get("service_worker"), str):
        problems.append(f"background = {background!r}: trebuie un service_worker (și opțional type), nimic altceva")
    return problems


# ---------- JavaScript ----------

# Cod de rețea, de cod dinamic sau de inserare de HTML (vederea `code`: fără comentarii și fără conținutul literalelor). `fetch` are regula lui, mai jos.
JS_CODE_RULES = (
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"), (r"\bWebSocket\b", "WebSocket"), (r"\bEventSource\b", "EventSource"), (r"\bsendBeacon\b", "sendBeacon"),
    (r"\bimportScripts\b", "importScripts"), (r"\bWebTransport\b", "WebTransport"), (r"\bRTCPeerConnection\b", "WebRTC"),
    (r"(?<![\w$.])eval\s*\(", "eval()"), (r"\bnew\s+Function\b|(?<![\w$.])Function\s*\(", "Function()"),
    (r"\b(?:setTimeout|setInterval)\s*\(\s*['\"`]", "cod dat ca text la un temporizator"),
    (r"\binnerHTML\b", "innerHTML"), (r"\bouterHTML\b", "outerHTML"), (r"\binsertAdjacentHTML\b", "insertAdjacentHTML"),
    (r"\bdocument\s*\.\s*(?:write|writeln)\b", "document.write"),
    (r"\bchrome\s*\.\s*cookies\b", "chrome.cookies"), (r"\bchrome\s*\.\s*webRequest\b", "chrome.webRequest"), (r"\bchrome\s*\.\s*downloads\b", "chrome.downloads"),
)
FETCH_PATTERN = re.compile(r"(?<![\w$])fetch(?![\w$])")
# Aceleași nume scrise ca text (window['fetch']): un literal care este EXACT numele unui API interzis. Cuvinte obișnuite ca «cookies» sau «downloads» nu sunt aici (apar în liste de chei și în clase CSS);
# chrome.cookies, chrome.webRequest și chrome.downloads sunt oricum oprite de manifest (fără permisiunile lor, API-urile nici nu există).
FORBIDDEN_NAMES_AS_TEXT = frozenset({
    "fetch", "eval", "Function", "innerHTML", "outerHTML", "insertAdjacentHTML", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon",
    "importScripts", "WebTransport", "RTCPeerConnection",
})
DYNAMIC_IMPORT = re.compile(r"(?<![\w$.])import\s*\(")
# Un import dinamic permis: un literal text, relativ, spre un fișier .js, urmat de paranteza de închidere (nimic calculat).
ALLOWED_DYNAMIC_IMPORT = re.compile(r"""\s*(['"])\.{1,2}/[^'"\\$`]*\.js\1\s*\)""")
STATIC_IMPORT = re.compile(r"""(?:^|\n)\s*(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]""")
BARE_IMPORT = re.compile(r"""(?:^|\n)\s*import\s*['"]([^'"]+)['"]""")
URL_IN_TEXT = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>)\]}\\]*")
PROTOCOL_RELATIVE = re.compile(r"(?i)^//[a-z0-9][a-z0-9.-]*")
JAVASCRIPT_URL = re.compile(r"(?i)\bjavascript\s*:")
# Spații de nume XML: identificatori (de exemplu la createElementNS), nu cereri de rețea.
XML_NAMESPACE_URLS = frozenset({"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink", "http://www.w3.org/1999/xhtml"})
ALLOWED_URL_HOST = "www.emag.ro"


def _line_of(text: str, index: int) -> int:
    """Numărul liniei (de la 1) pentru poziția `index` din `text`."""
    return text.count("\n", 0, index) + 1


def is_allowed_url(url: str) -> bool:
    """True pentru https://www.emag.ro (cu sau fără cale), fără utilizator, parolă sau port, și pentru spațiile de nume XML."""
    if url in XML_NAMESPACE_URLS:
        return True
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == ALLOWED_URL_HOST and not parts.username and not parts.password and parts.port is None


def js_problems(text: str, label: str, fetch_allowed: bool = False) -> list[str]:
    """Încălcările unui fișier JS al extensiei: API-uri interzise, `fetch` în afara fișierului lui, importuri nelocale sau calculate, adrese în literale.

    `fetch_allowed` = fișierul are excepția `fetch` (FETCH_FILE): atunci trebuie să aibă exact un `fetch`, nu zero și nu mai mult de unul.
    """
    views = scan_js(text)
    problems = []
    for pattern, what in JS_CODE_RULES:
        for match in re.finditer(pattern, views.code):
            problems.append(f"{label}:{_line_of(views.code, match.start())}: {what}: extensia doar citește paginile eMAG din fila de lucru, nu face alte cereri și nu rulează cod dinamic")
    fetches = list(FETCH_PATTERN.finditer(views.code))
    if not fetch_allowed:
        for match in fetches:
            problems.append(f"{label}:{_line_of(views.code, match.start())}: fetch: singurul loc cu fetch din extensie e {FETCH_FILE}, unde cererea pleacă din fila eMAG, doar pe căi relative")
    elif len(fetches) != 1:
        problems.append(f"{label}: {len(fetches)} apariții ale lui fetch; fișierul cu excepția trebuie să aibă exact una, ca toate cererile să treacă printr-un singur loc")
    for line, literal in views.strings:
        if literal.strip() in FORBIDDEN_NAMES_AS_TEXT:
            problems.append(f"{label}:{line}: «{literal.strip()}» scris ca text: accesul la un API interzis prin paranteze pătrate (window['fetch']...) ocolește regulile de mai sus")
    for match in DYNAMIC_IMPORT.finditer(views.code):
        if not ALLOWED_DYNAMIC_IMPORT.match(views.uncommented, match.end()):
            problems.append(f"{label}:{_line_of(views.code, match.start())}: import() cu cale calculată sau nelocală: doar import('./fisier.js') sau import('../folder/fisier.js'), cu literal text")
    for pattern in (STATIC_IMPORT, BARE_IMPORT):
        for match in pattern.finditer(views.uncommented):
            if not match.group(1).startswith(("./", "../")):
                problems.append(f"{label}:{_line_of(views.uncommented, match.start(1))}: importul «{match.group(1)}» nu e relativ: extensia încarcă doar module proprii, nimic de pe internet")
    for line, literal in views.strings:
        for found in URL_IN_TEXT.finditer(literal):
            url = found.group(0).rstrip(".,;")
            if not is_allowed_url(url):
                problems.append(f"{label}:{line}: adresa «{url}»: singura adresă permisă într-un literal e https://www.emag.ro (fără utilizator, parolă sau port)")
        if PROTOCOL_RELATIVE.match(literal):
            problems.append(f"{label}:{line}: adresă fără protocol («{literal[:40]}»): ar putea duce spre altă gazdă")
        if JAVASCRIPT_URL.search(literal):
            problems.append(f"{label}:{line}: «javascript:» într-un literal: cod dat ca adresă")
    return problems


# ---------- HTML și CSS ----------

# Etichete care încarcă conținut din altă parte sau schimbă adresa paginii.
FORBIDDEN_TAGS = frozenset({"iframe", "frame", "frameset", "embed", "object", "applet", "base", "portal", "fencedframe"})
URL_ATTRIBUTES = frozenset({"src", "srcset", "poster", "data", "background", "manifest", "codebase", "action", "formaction", "href", "xlink:href", "ping"})
# Surse permise în politica de conținut a paginii, pe directivă: `data:` doar la imagini; scriptul doar din extensie; nicio conectare.
CSP_FORBIDDEN_KEYWORDS = frozenset({"'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'", "'wasm-unsafe-eval'", "'strict-dynamic'", "*"})
CSP_DATA_ALLOWED_IN = frozenset({"img-src"})
CSP_SCHEME_OR_HOST = re.compile(r"(?i)^(?:(?:https?|wss?|ftp):|[a-z0-9*][a-z0-9*.-]*\.[a-z]{2,}(?::\d+)?(?:/.*)?$)")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE | re.DOTALL)


def is_local_reference(value: str) -> bool:
    """True pentru o referință care nu iese din extensie: gol, #fragment, cale relativă sau data:image/ (fără schemă, fără «//»)."""
    text = value.strip().lower()
    if not text or text.startswith("#") or text.startswith("data:image/"):
        return True
    return not re.match(r"^[a-z][a-z0-9+.-]*:", text) and not text.startswith(("//", "\\\\"))


def csp_problems(content: str, where: str) -> list[str]:
    """Încălcările politicii de conținut dintr-un <meta http-equiv="Content-Security-Policy">: nimic nu o slăbește față de cea implicită din Manifest V3."""
    directives: dict[str, list[str]] = {}
    for part in content.split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0].lower()] = tokens[1:]
    problems = []
    for name, sources in directives.items():
        for source in sources:
            lowered = source.lower()
            if lowered in CSP_FORBIDDEN_KEYWORDS:
                problems.append(f"{where}: politica de conținut are {source} la {name}: ar slăbi politica implicită (fără scripturi inline, eval sau surse oarecare)")
            elif lowered in {"data:", "blob:", "filesystem:"} and name not in CSP_DATA_ALLOWED_IN:
                problems.append(f"{where}: politica de conținut are {source} la {name}: schema aceasta e permisă doar la {sorted(CSP_DATA_ALLOWED_IN)}")
            elif CSP_SCHEME_OR_HOST.match(lowered):
                problems.append(f"{where}: politica de conținut are sursa {source} la {name}: extensia nu încarcă nimic de pe alte gazde")
    if directives.get("script-src") != ["'self'"]:
        problems.append(f"{where}: script-src trebuie să fie exact 'self' (am găsit {directives.get('script-src')!r})")
    if directives.get("connect-src") != ["'none'"]:
        problems.append(f"{where}: connect-src trebuie să fie exact 'none' (am găsit {directives.get('connect-src')!r}): pagina extensiei nu face cereri, cererile pleacă din fila eMAG")
    return problems


class _HtmlCollector(HTMLParser):
    """Colectează etichetele (cu atributele și linia lor) dintr-un fișier HTML."""

    def __init__(self):
        """Pregătește lista de etichete colectate."""
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str], int]] = []

    def handle_starttag(self, tag, attrs):
        """Reține eticheta, cu atributele în litere mici și valoarea goală pentru un atribut fără valoare."""
        self.tags.append((tag.lower(), {name.lower(): (value or "") for name, value in attrs}, self.getpos()[0]))

    handle_startendtag = handle_starttag


def html_problems(text: str, label: str) -> list[str]:
    """Încălcările unui fișier HTML al extensiei: script inline, resurse sau linkuri către alte gazde, etichete interzise, politică de conținut slăbită."""
    collector = _HtmlCollector()
    collector.feed(text)
    collector.close()
    problems = []
    for tag, attrs, line in collector.tags:
        where = f"{label}:{line}"
        if tag in FORBIDDEN_TAGS:
            problems.append(f"{where}: <{tag}>: pagina extensiei nu încarcă alte pagini sau obiecte încorporate")
        if tag == "script" and "src" not in attrs:
            problems.append(f"{where}: <script> inline: politica de conținut din Manifest V3 nu permite scripturi inline, iar extensia nu are voie să ceară altfel")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            problems.append(f"{where}: <meta http-equiv=refresh>: ar naviga automat în altă parte")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy":
            problems.extend(csp_problems(attrs.get("content", ""), where))
        for name, value in attrs.items():
            if name.startswith("on"):
                problems.append(f"{where}: atributul {name}= (cod inline): scripturile stau în fișiere, încărcate cu src")
            if name not in URL_ATTRIBUTES:
                continue
            if JAVASCRIPT_URL.match(value.strip()):
                problems.append(f"{where}: {name}=\"javascript:...\": cod dat ca adresă")
            elif name == "ping":
                problems.append(f"{where}: ping=: trimite o notificare la fiecare clic")
            elif name == "srcset":
                candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
                problems.extend(f"{where}: srcset cu «{candidate}»: resursă de pe altă gazdă" for candidate in candidates if not is_local_reference(candidate))
            elif tag == "a" and name == "href" and not is_local_reference(value):
                problems.extend(_emag_link_problems(value, attrs, where))
            elif not is_local_reference(value):
                problems.append(f"{where}: <{tag} {name}=\"{value}\">: resursă de pe altă gazdă; extensia trebuie să meargă fără internet")
    return problems


def _emag_link_problems(value: str, attrs: dict[str, str], where: str) -> list[str]:
    """Un link către altă gazdă: permis doar https://www.emag.ro/..., cu rel=\"noopener noreferrer\", deschis de om la clic."""
    if not is_allowed_url(value.strip()) or urlsplit(value.strip()).scheme != "https":
        return [f"{where}: <a href=\"{value}\">: singurul link extern permis e https://www.emag.ro/..."]
    rel = set(attrs.get("rel", "").lower().split())
    if not {"noopener", "noreferrer"} <= rel:
        return [f"{where}: link către eMAG fără rel=\"noopener noreferrer\": pagina eMAG ar primi legătura cu fila extensiei și adresa ei"]
    return []


def css_problems(text: str, label: str) -> list[str]:
    """Încălcările unui fișier CSS al extensiei: `@import` și `url()` către altceva decât fișiere locale."""
    stripped = CSS_COMMENT.sub(lambda comment: re.sub(r"[^\n]", " ", comment.group(0)), text)
    problems = [f"{label}:{_line_of(stripped, match.start())}: @import: CSS-ul nu aduce alt CSS din afară" for match in re.finditer(r"@import\b", stripped, re.IGNORECASE)]
    for match in CSS_URL.finditer(stripped):
        if not is_local_reference(match.group(2)):
            problems.append(f"{label}:{_line_of(stripped, match.start())}: url({match.group(2)}): CSS-ul nu încarcă imagini sau fonturi de pe alte gazde")
    return problems


# ---------- caractere ----------

NBSP = chr(0x00A0)
# Literele cu sedilă (s și t, mari și mici): în română se scriu cu virgulă. Generate din cod, ca acest fișier să nu le conțină.
CEDILLA_LETTERS = {chr(code): name for code, name in ((0x015E, "S cu sedilă"), (0x015F, "s cu sedilă"), (0x0162, "T cu sedilă"), (0x0163, "t cu sedilă"))}


def character_problems(text: str, label: str) -> list[str]:
    """Caractere invizibile (control, bidi, lățime zero, BOM...), NBSP literal și litere cu sedilă dintr-un text al extensiei, cu rândul și coloana lor."""
    problems = hidden_character_problems(text, label, suffix="")
    line, column = 1, 0
    for char in text:
        if char == "\n":
            line, column = line + 1, 0
            continue
        column += 1
        if char == NBSP:
            problems.append(f"{label}:{line}:{column}: U+00A0 NBSP literal: scrie-l ca secvență (backslash, u, 00a0), ca să se vadă în cod")
        elif char in CEDILLA_LETTERS:
            problems.append(f"{label}:{line}:{column}: U+{ord(char):04X} {CEDILLA_LETTERS[char]}: în română se scrie cu virgulă; în cod și în teste, ca secvență (backslash, u, cod)")
    return problems


# ---------- git ----------

# Ce poate fi ignorat de git în extensie/ fără să fie o greșeală: pachetele de dezvoltare și rezultatele construirii (se refac oricând).
EXPECTED_IGNORED_PREFIXES = ("extensie/node_modules/", "extensie/dist/", "extensie/build/")


def unexpectedly_ignored(listing: str) -> list[str]:
    """Din ieșirea lui `git ls-files --others --ignored --exclude-standard --directory`, căile ignorate care nu sunt pachete de dezvoltare sau rezultate de construire."""
    return [line for line in listing.splitlines() if line.strip() and not line.startswith(EXPECTED_IGNORED_PREFIXES)]


# ---------- fișierele de verificat ----------

def _extension_sources(*suffixes: str) -> list:
    """Fișierele din extensie/src cu una dintre extensiile date, sortate (fără cele ascunse)."""
    return sorted(path for path in SOURCE_DIR.rglob("*") if path.is_file() and path.suffix.lower() in suffixes and not path.name.startswith("."))


def _published_extension_text_files() -> list:
    """Fișierele text din extensie/ care urcă în git (node_modules, dist și build sunt ignorate de git), fără imagini și arhive."""
    binary = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".woff", ".woff2"}
    return [path for path in files_to_publish() if relative(path).startswith("extensie/") and path.suffix.lower() not in binary]


# Praguri împotriva unei verificări golite în tăcere (o cale greșită ar scana zero fișiere și ar trece): extensia are azi 62 de fișiere JS, 1 pagină HTML și 1 foaie CSS.
MIN_JS_FILES = 40
MIN_TEXT_FILES = 100


# ---------- pe fișierele reale ----------

def test_the_manifest_has_exactly_the_allowed_permissions_and_no_forbidden_keys():
    """Manifestul real: exact permisiunile storage și scripting, accesul doar la www.emag.ro, fără chei care lărgesc accesul; service worker-ul există."""
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    problems = manifest_problems(manifest)
    worker = SOURCE_DIR / manifest["background"]["service_worker"]
    if not worker.is_file():
        problems.append(f"service worker-ul {relative(worker)} nu există")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", _extension_sources(".js"), ids=relative)
def test_extension_script_has_no_forbidden_api_and_only_emag_urls(path):
    """Fiecare JS din extensie/src: `fetch` doar în page_functions.js, fără alte căi de rețea sau de cod dinamic, importuri doar relative, adrese doar https://www.emag.ro."""
    label = relative(path)
    problems = js_problems(path.read_text(encoding="utf-8"), label, fetch_allowed=label == FETCH_FILE)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", _extension_sources(".html", ".htm"), ids=relative)
def test_extension_page_has_no_inline_script_and_no_foreign_resource(path):
    """Fiecare pagină HTML din extensie/src: fără script inline, fără resurse sau linkuri către alte gazde, cu politica de conținut netăiată."""
    problems = html_problems(path.read_text(encoding="utf-8"), relative(path))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", _extension_sources(".css"), ids=relative)
def test_extension_stylesheet_loads_nothing_from_other_hosts(path):
    """Fiecare foaie CSS din extensie/src: fără @import și fără url() către alte gazde."""
    problems = css_problems(path.read_text(encoding="utf-8"), relative(path))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", _published_extension_text_files(), ids=relative)
def test_extension_text_file_has_no_invisible_character_nbsp_or_cedilla(path):
    """Fiecare fișier text din extensie/ (fără node_modules, dist, build): fără caractere invizibile, fără NBSP literal și fără litere cu sedilă."""
    text = read_text_or_none(path)
    if text is None:
        pytest.skip("fișier binar sau prea mare")
    problems = character_problems(text, relative(path))
    assert not problems, "\n".join(problems)


def test_the_scans_cover_the_extension_and_the_fetch_exception_is_still_needed():
    """Verificările chiar văd extensia (destule fișiere JS și text) și excepția `fetch` mai e necesară: page_functions.js are exact un fetch; când dispare, excepția se scoate."""
    scripts = [relative(path) for path in _extension_sources(".js")]
    assert len(scripts) >= MIN_JS_FILES, f"doar {len(scripts)} fișiere JS în extensie/src: calea s-a schimbat sau fișierele au dispărut"
    assert FETCH_FILE in scripts, f"{FETCH_FILE} nu mai există: scoate excepția pentru fetch"
    assert len(FETCH_PATTERN.findall(scan_js((PROJECT_ROOT / FETCH_FILE).read_text(encoding="utf-8")).code)) == 1, f"{FETCH_FILE} nu mai are exact un fetch: scoate sau ajustează excepția"
    assert len(_extension_sources(".html")) >= 1 and len(_extension_sources(".css")) >= 1, "extensia nu mai are pagina HTML sau foaia CSS de verificat"
    assert len(_published_extension_text_files()) >= MIN_TEXT_FILES, "garda de caractere vede prea puține fișiere din extensie/"


@pytest.mark.skipif(shutil.which("git") is None, reason="git nu e instalat: nu pot afla ce ignoră")
def test_nothing_in_the_extension_is_silently_ignored_by_git():
    """În extensie/ git ignoră doar node_modules, dist și build: un folder nou cu numele unui folder ignorat (de exemplu «iesiri») ar dispărea din commit fără nicio eroare."""
    if not (PROJECT_ROOT / ".git").exists():
        pytest.skip("nu e depozit git")
    done = subprocess.run(
        [shutil.which("git"), "-C", str(PROJECT_ROOT), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "--", "extensie"],
        capture_output=True, timeout=GIT_TIMEOUT_SECONDS, check=True,
    )
    ignored = unexpectedly_ignored(done.stdout.decode("utf-8", errors="replace"))
    assert not ignored, f"fișiere sau foldere din extensie/ ignorate de git (nu ar urca în commit): {ignored}. Verifică cu git check-ignore -v"


# ---------- detectoarele văzute picând pe cod-capcană ----------

CLEAN_MANIFEST = {
    "manifest_version": 3, "name": "Test", "description": "Test", "version": "1.0.0", "minimum_chrome_version": "120",
    "permissions": ["storage", "scripting"], "host_permissions": ["https://www.emag.ro/*"],
    "background": {"service_worker": "background.js", "type": "module"}, "action": {"default_title": "Test"}, "icons": {"16": "i.png"},
}


def test_manifest_detector_accepts_the_expected_manifest():
    """Fals pozitiv: un manifest cu exact permisiunile cerute nu e o încălcare (și ordinea permisiunilor nu contează)."""
    assert manifest_problems(CLEAN_MANIFEST) == []
    assert manifest_problems({**CLEAN_MANIFEST, "permissions": ["scripting", "storage"]}) == []


@pytest.mark.parametrize("change, expected", [
    ({"permissions": ["storage", "scripting", "tabs"]}, "permissions"), ({"permissions": ["storage", "scripting", "cookies"]}, "permissions"),
    ({"permissions": ["storage", "scripting", "downloads"]}, "permissions"), ({"permissions": ["storage", "scripting", "webRequest"]}, "permissions"),
    ({"permissions": ["storage"]}, "permissions"), ({"permissions": ["storage", "scripting", "storage"]}, "permissions"), ({"permissions": "storage"}, "permissions"),
    ({"host_permissions": ["<all_urls>"]}, "host_permissions"), ({"host_permissions": ["https://www.emag.ro/*", "https://exemplu.invalid/*"]}, "host_permissions"),
    ({"host_permissions": ["https://*.emag.ro/*"]}, "host_permissions"), ({"host_permissions": ["http://www.emag.ro/*"]}, "host_permissions"),
    ({"host_permissions": []}, "host_permissions"), ({"manifest_version": 2}, "manifest_version"),
    ({"content_scripts": [{"matches": ["https://www.emag.ro/*"], "js": ["a.js"]}]}, "content_scripts"),
    ({"web_accessible_resources": [{"resources": ["a.js"], "matches": ["<all_urls>"]}]}, "web_accessible_resources"),
    ({"externally_connectable": {"matches": ["https://*/*"]}}, "externally_connectable"),
    ({"content_security_policy": {"extension_pages": "script-src 'self' 'unsafe-eval'"}}, "content_security_policy"),
    ({"optional_permissions": ["tabs"]}, "optional_permissions"), ({"optional_host_permissions": ["<all_urls>"]}, "optional_host_permissions"),
    ({"update_url": "https://exemplu.invalid/updates.xml"}, "update_url"), ({"commands": {"x": {}}}, "cheie necunoscută"), ({"side_panel": {}}, "cheie necunoscută"),
    ({"background": {"scripts": ["a.js"]}}, "background"), ({"background": {"service_worker": "a.js", "persistent": True}}, "background"),
])
def test_manifest_detector_catches_trap_manifests(change, expected):
    """Capcană: fiecare manifest cu o permisiune în plus, un acces mai larg sau o cheie interzisă trebuie să pice."""
    problems = " | ".join(manifest_problems({**CLEAN_MANIFEST, **change}))
    assert expected in problems, f"nu a fost prins «{expected}» pentru {change}: {problems or 'nimic'}"


def test_manifest_detector_rejects_a_manifest_without_the_required_keys():
    """Capcană: un manifest care nu e obiect sau care nu are permisiunile deloc pică."""
    assert manifest_problems([]) and manifest_problems("x")
    without = {key: value for key, value in CLEAN_MANIFEST.items() if key not in {"permissions", "host_permissions"}}
    assert len(manifest_problems(without)) >= 2


@pytest.mark.parametrize("source, expected", [
    ("fetch('/x');", "fetch"), ("const f = fetch;", "fetch"), ("window.fetch(u);", "fetch"), ("await root.fetch(u, { method: 'POST' });", "fetch"),
    ("var x = new XMLHttpRequest();", "XMLHttpRequest"), ("new WebSocket(u);", "WebSocket"), ("new EventSource(u);", "EventSource"),
    ("navigator.sendBeacon(u, d);", "sendBeacon"), ("importScripts('a.js');", "importScripts"), ("new WebTransport(u);", "WebTransport"),
    ("new RTCPeerConnection();", "WebRTC"), ("eval(s);", "eval()"), ("new Function('return 1')();", "Function()"), ("Function('return 1')();", "Function()"),
    ("setTimeout('x()', 1);", "cod dat ca text"), ("setInterval(`x()`, 1);", "cod dat ca text"),
    ("box.innerHTML = s;", "innerHTML"), ("box.outerHTML = s;", "outerHTML"), ("box.insertAdjacentHTML('beforeend', s);", "insertAdjacentHTML"),
    ("document.write(s);", "document.write"), ("document.writeln(s);", "document.write"),
    ("chrome.cookies.getAll({});", "chrome.cookies"), ("chrome.webRequest.onBeforeRequest.addListener(f);", "chrome.webRequest"), ("chrome.downloads.download({ url: u });", "chrome.downloads"),
    ("window['fetch'](u);", "scris ca text"), ("globalThis[\"eval\"](s);", "scris ca text"), ("el['innerHTML'] = s;", "scris ca text"),
    ("const m = await import(name);", "import() cu cale"), ("await import('https://exemplu.invalid/x.js');", "import() cu cale"), ("await import('./' + name + '.js');", "import() cu cale"),
    ("await import(`./${name}.js`);", "import() cu cale"), ("await import('../x/' + y);", "import() cu cale"), ("await import('./x.js' + z);", "import() cu cale"),
    ("import x from 'https://exemplu.invalid/x.js';", "nu e relativ"), ("import 'lodash';", "nu e relativ"), ("export { y } from '/absolut.js';", "nu e relativ"),
    ("var u = 'http://www.emag.ro/x';", "http://www.emag.ro/x"), ("var u = 'https://exemplu.invalid/x';", "exemplu.invalid"),
    ("var u = 'https://www.emag.ro.exemplu.invalid/';", "www.emag.ro.exemplu.invalid"),
    ("var u = 'https://www.emag.ro:8443/';", "www.emag.ro:8443"), ("var u = 'wss://www.emag.ro/';", "wss://www.emag.ro/"),
    ("var u = 'ftp://www.emag.ro/';", "ftp://www.emag.ro/"), ("var u = `https://exemplu.invalid/${id}`;", "exemplu.invalid"),
    ("var u = '//exemplu.invalid/x.js';", "adresă fără protocol"), ("var u = 'javascript:alert(1)';", "javascript:"),
])
def test_script_detector_catches_trap_code(source, expected):
    """Capcană: fiecare API de rețea sau de cod dinamic, fiecare import nelocal sau calculat și fiecare adresă străină dintr-un literal trebuie prinse."""
    problems = " | ".join(js_problems(source, "extensie/src/capcana.js"))
    assert expected in problems, f"nu a fost prins «{expected}» în:\n{source}\n(rezultat: {problems or 'nimic'})"


def test_url_detector_rejects_userinfo_on_an_otherwise_allowed_host(monkeypatch):
    """Utilizatorul din URL e refuzat independent de gazdă; domeniul inventat păstrează mostra clar fictivă."""
    monkeypatch.setitem(globals(), "ALLOWED_URL_HOST", "exemplu.invalid")
    assert is_allowed_url("https://exemplu.invalid/")
    assert not is_allowed_url("https://utilizator@exemplu.invalid/")
    source = "var u = 'https://utilizator@exemplu.invalid/';"
    assert "utilizator@exemplu.invalid" in " | ".join(js_problems(source, "extensie/src/capcana.js"))


@pytest.mark.parametrize("source", [
    "// fetch('/x') și eval(s) în comentariu\n/* new XMLHttpRequest() */\nvar x = 1;",
    "var t = 'Extensia nu apelează fetch() și nu folosește XMLHttpRequest, WebSocket sau innerHTML.';",
    "var r = /fetch\\(/g; var d = a / b;", "pageFetch(path); fetchEach(tabId, paths); await fetchHtml(path); const fetchedAll = true;",
    "box.textContent = text; box.append(node); box.replaceChildren();",
    "var base = 'https://www.emag.ro'; var all = 'https://www.emag.ro/history/shopping?time=older'; var port = 'https://www.emag.ro/x#a';",
    "var ns = document.createElementNS('http://www.w3.org/2000/svg', 'svg');",
    "import x from './x.js'; import { a, b } from '../calcul/y.js'; export { c } from './z.js'; import './efect.js';",
    "const [a, b] = await Promise.all([import('./a.js'), import(\"../b/c.js\")]);",
    "const worker = new Worker(new URL('./timer_worker.js', import.meta.url));",
    "var forbidden = new Set(['html', 'cookie', 'cookies', 'password']); var name = 'Descărcări'; var cls = 'downloads__list';",
    "const text = `fără ${adresă}`; // https://exemplu.invalid în comentariu",
])
def test_script_detector_allows_ordinary_code(source):
    """Fals pozitiv: comentarii, texte care doar numesc un API, nume ca pageFetch, adrese eMAG curate, importuri relative și Worker-ul cronometru nu sunt încălcări."""
    assert js_problems(source, "extensie/src/curat.js") == [], source


def test_the_fetch_exception_needs_exactly_one_fetch_in_its_file():
    """Fișierul cu excepția lui `fetch` trebuie să aibă exact unul: zero (excepția nu mai e necesară) sau două (o a doua cale de rețea) pică."""
    one = "export async function pageFetch(path) { return fetch(path); }"
    assert js_problems(one, FETCH_FILE, fetch_allowed=True) == []
    assert js_problems("export function nimic() {}", FETCH_FILE, fetch_allowed=True)
    assert js_problems(one + "\nexport function alta(p) { return fetch(p); }", FETCH_FILE, fetch_allowed=True)
    assert js_problems(one, "extensie/src/altceva.js"), "în alt fișier, același fetch pică"


@pytest.mark.parametrize("html, expected", [
    ("<script>alert(1)</script>", "<script> inline"), ("<script type='module'>import './a.js';</script>", "<script> inline"),
    ("<script src='https://exemplu.invalid/x.js'></script>", "resursă de pe altă gazdă"), ("<script src='//exemplu.invalid/x.js'></script>", "resursă de pe altă gazdă"),
    ("<link rel='stylesheet' href='https://exemplu.invalid/x.css'>", "resursă de pe altă gazdă"), ("<img src='https://exemplu.invalid/x.png'>", "resursă de pe altă gazdă"),
    ("<img src='https://www.emag.ro/x.png'>", "resursă de pe altă gazdă"), ("<img srcset='a.png 1x, https://exemplu.invalid/b.png 2x'>", "srcset"),
    ("<iframe src='x.html'></iframe>", "<iframe>"), ("<object data='x.swf'></object>", "<object>"), ("<embed src='x.swf'>", "<embed>"), ("<base href='x/'>", "<base>"),
    ("<form action='https://exemplu.invalid/'></form>", "resursă de pe altă gazdă"), ("<button formaction='https://exemplu.invalid/'>x</button>", "resursă de pe altă gazdă"),
    ("<a href='https://exemplu.invalid/'>x</a>", "singurul link extern"), ("<a href='https://www.emag.ro/x'>x</a>", "fără rel"),
    ("<a href='https://www.emag.ro/x' rel='noopener'>x</a>", "fără rel"), ("<a href='http://www.emag.ro/x' rel='noopener noreferrer'>x</a>", "singurul link extern"),
    ("<a href='javascript:alert(1)'>x</a>", "javascript:"), ("<a href='#x' ping='https://exemplu.invalid/'>x</a>", "ping"),
    ("<button onclick=\"alert(1)\">x</button>", "cod inline"), ("<body onload='x()'>", "cod inline"),
    ("<meta http-equiv='refresh' content='0;url=x'>", "refresh"),
    ("<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'none'\">", "'unsafe-inline'"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self' 'unsafe-eval'; connect-src 'none'\">", "'unsafe-eval'"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self' https://exemplu.invalid; connect-src 'none'\">", "sursa https://exemplu.invalid"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self' cdn.exemplu.invalid; connect-src 'none'\">", "sursa cdn.exemplu.invalid"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src * ; connect-src 'none'\">", "la script-src"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self' data:; connect-src 'none'\">", "data:"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self'; connect-src 'self'\">", "connect-src trebuie"),
    ("<meta http-equiv='Content-Security-Policy' content=\"script-src 'self'\">", "connect-src trebuie"),
    ("<meta http-equiv='Content-Security-Policy' content=\"connect-src 'none'\">", "script-src trebuie"),
])
def test_page_detector_catches_trap_pages(html, expected):
    """Capcană: script inline, resurse și linkuri străine, etichete interzise, cod în atribute și o politică de conținut slăbită trebuie prinse."""
    problems = " | ".join(html_problems(html, "extensie/src/capcana.html"))
    assert expected in problems, f"nu a fost prins «{expected}» în:\n{html}\n(rezultat: {problems or 'nimic'})"


@pytest.mark.parametrize("html", [
    "<script src='ecrane/main.js' type='module'></script><script src='partajat/dashboard.js'></script>",
    "<link rel='stylesheet' href='extensie.css'><link rel='icon' type='image/png' href='iconite/icon-32.png'>",
    "<a href='#faq-nu-merge'>x</a><a href='aplicatie.html'>y</a><a href='' >z</a>",
    "<a href='https://www.emag.ro/history/shoppingdetails/1' target='_blank' rel='noopener noreferrer'>x</a>",
    "<img src='data:image/png;base64,AAAA'><img src='iconite/a.png' srcset='iconite/a.png 1x, iconite/b.png 2x'>",
    "<p>Text cu https://exemplu.invalid și fetch() în paragraf, <b>fără</b> resurse.</p>",
    "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'\">",
    "<form id='f' novalidate><button type='submit'>x</button></form>",
])
def test_page_detector_allows_ordinary_pages(html):
    """Fals pozitiv: scripturi și foi de stil locale, linkuri locale sau eMAG curate, imagini data:image și politica de conținut a paginii de azi nu sunt încălcări."""
    assert html_problems(html, "extensie/src/curat.html") == [], html


@pytest.mark.parametrize("css, expected", [
    ("@import 'x.css';", "@import"), ("@import url(https://exemplu.invalid/x.css);", "@import"),
    ("a { background: url(https://exemplu.invalid/x.png); }", "url(https://exemplu.invalid/x.png)"), ("a { background: url(//exemplu.invalid/x.png); }", "url(//exemplu.invalid/x.png)"),
    ("@font-face { src: url('https://exemplu.invalid/f.woff2'); }", "url(https://exemplu.invalid/f.woff2)"),
])
def test_stylesheet_detector_catches_trap_styles(css, expected):
    """Capcană: @import și url() către alte gazde trebuie prinse."""
    problems = " | ".join(css_problems(css, "extensie/src/capcana.css"))
    assert expected in problems, f"nu a fost prins «{expected}» în:\n{css}\n(rezultat: {problems or 'nimic'})"


def test_stylesheet_detector_allows_local_references_and_comments():
    """Fals pozitiv: url() local, data:image, #fragment și un comentariu care numește o adresă nu sunt încălcări."""
    clean = "/* url(https://exemplu.invalid/x.png) @import 'x'; */ a { background: url(img/x.png); } b { fill: url(#g); } c { background: url(data:image/png;base64,AAAA); }"
    assert css_problems(clean, "extensie/src/curat.css") == []


@pytest.mark.parametrize("char, expected", [
    (chr(0x200B), "U+200B"), (chr(0x202E), "U+202E"), (chr(0x2066), "U+2066"), (chr(0xFEFF), "U+FEFF"), (chr(0x00AD), "U+00AD"), (chr(0x2028), "U+2028"),
    (chr(0x0007), "U+0007"), (chr(0x3164), "U+3164"), (chr(0x2003), "U+2003"), (chr(0xE000), "U+E000"),
    (NBSP, "NBSP"), (chr(0x015F), "U+015F"), (chr(0x0163), "U+0163"), (chr(0x015E), "U+015E"), (chr(0x0162), "U+0162"),
])
def test_character_detector_catches_trap_characters(char, expected):
    """Capcană: fiecare caracter invizibil, NBSP literal și fiecare literă cu sedilă, scrise ca atare în text, trebuie prinse."""
    problems = " | ".join(character_problems(f"const t = 'a{char}b';\n", "extensie/src/capcana.js"))
    assert expected in problems, f"nu a fost prins «{expected}»: {problems or 'nimic'}"


def test_character_detector_allows_romanian_comma_letters_escapes_and_ordinary_whitespace():
    """Fals pozitiv: literele cu virgulă, secvențele de tip backslash-u, tab, rând nou și întoarcere de car nu sunt încălcări."""
    comma_letters = "".join(chr(code) for code in (0x0218, 0x0219, 0x021A, 0x021B, 0x0103, 0x00E2, 0x00EE))
    text = f"// {comma_letters} cu virgulă\n\tconst a = '\\u015f \\u0163 \\u00a0';\r\nconst b = \"aceasta e o linie\";\n"
    assert character_problems(text, "extensie/src/curat.js") == []


def test_the_ignored_files_detector_catches_a_silently_ignored_folder():
    """Capcană: un folder din extensie/ cu numele unuia ignorat de git pică; node_modules, dist și build sunt așteptate."""
    expected = "extensie/node_modules/\nextensie/dist/\nextensie/build/\nextensie/node_modules/playwright-core/index.js\n"
    assert unexpectedly_ignored(expected) == []
    assert unexpectedly_ignored(expected + "extensie/src/iesiri/\n") == ["extensie/src/iesiri/"]
    assert unexpectedly_ignored("extensie/tests/e2e/rezultate/comenzi.json\n") == ["extensie/tests/e2e/rezultate/comenzi.json"]
    assert unexpectedly_ignored("\n  \n") == []
