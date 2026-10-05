"""Teste statice pentru pagina aplicației: interfata/aplicatie.html, assets/app.css și assets/app-*.js (fără browser).

Primește: fișierele paginii, site.css (pentru paritatea tokenilor), settings.py (valori oglindite în pagină) și index.html
(ancorele spre care trimit linkurile). Verifică: structura și accesibilitatea din HTML, politica de conținut, regulile de text
(ghilimele românești, diacritice cu virgulă, fără jargon pe ecrane), faptul că DOAR app-api.js face cereri de rețea și doar spre
/api/..., că cheia de acces nu ajunge nicăieri în afara memoriei, paritatea cu site.css, contrastul tokenilor și valorile
oglindite din settings.py. Ce NU face: nu rulează pagina (testele din test_app_ui_browser.py o rulează).
"""

import re
from html.parser import HTMLParser

import pytest

from emag_spend import settings
from tests.app_ui_contrast import contrast, parse_token_blocks
from tests.app_ui_support import CONTENT_SECURITY_POLICY
from tests.garda_js_scan import scan_js
from tests.test_garda_retea import interface_violations

INTERFACE_DIR = settings.PROJECT_ROOT / "interfata"
ASSETS_DIR = INTERFACE_DIR / "assets"
PAGE_FILE = INTERFACE_DIR / "aplicatie.html"
CSS_FILE = ASSETS_DIR / "app.css"
SITE_CSS_FILE = ASSETS_DIR / "site.css"
APP_JS_FILES = sorted(ASSETS_DIR.glob("app-*.js"))
API_FILE_NAME = "app-api.js"
THEME_FILE_NAME = "app-theme.js"

# Ordinea scripturilor din pagină: fiecare modul își găsește dependențele deja încărcate (App.dom înaintea tuturor,
# App.api înaintea poll/lifecycle...), iar app-main.js, care le pornește pe toate, e ultimul.
EXPECTED_SCRIPT_ORDER = (
    "assets/app-theme.js", "assets/dashboard.js", "assets/app-dom.js", "assets/app-format.js", "assets/app-api.js",
    "assets/app-state.js", "assets/app-screens.js", "assets/app-poll.js", "assets/app-threshold.js", "assets/app-start.js",
    "assets/app-run.js", "assets/app-history.js", "assets/app-session.js", "assets/app-download.js", "assets/app-report.js",
    "assets/app-faq.js", "assets/app-lifecycle.js", "assets/app-main.js",
)
EXPECTED_SCREENS = ("loading", "closed-needs-app", "closed-stopped", "closed-user", "closed-nokey", "ready", "working", "done", "error", "cancelled")
EXPECTED_FAQ = (
    "faq-ce-face", "faq-ce-citeste", "faq-login", "faq-durata", "faq-inchid", "faq-salvare", "faq-opresc",
    "faq-avertismente", "faq-cifre", "faq-sigur", "faq-nu-merge", "faq-internet",
)
VOID_TAGS = frozenset({"meta", "link", "input", "br", "hr", "img", "area", "base", "col", "embed", "source", "track", "wbr"})
# Cuvinte tehnice care nu au ce căuta pe ecranele aplicației (zero jargon); în FAQ au voie, explicate.
JARGON = ("token", "api", "server", "json", "http", "localhost", "endpoint", "fetch", "cookie", "proxy", "backend")
# Literele cu sedilă (s și t cu sedilă, U+015E/U+015F/U+0162/U+0163): în română se scriu cu virgulă (U+0218/U+0219/U+021A/U+021B).
CEDILLA = "".join(chr(code) for code in (0x15E, 0x15F, 0x162, 0x163))
OPEN_QUOTE, CLOSE_QUOTE = "„", "”"
# Praguri WCAG: text normal 4.5:1, componente grafice și contururi de controale 3:1.
MIN_TEXT_CONTRAST = 4.5
MIN_UI_CONTRAST = 3.0
# Tokenii comuni cu site.css: aceleași valori, ca cele două pagini să nu se depărteze una de alta pe nesimțite.
SHARED_TOKENS = ("--paper", "--paper-2", "--card", "--ink", "--ink-2", "--ink-3", "--rule", "--rule-2", "--ctl", "--hl", "--hl-wash",
                 "--on-hl", "--focus", "--ok", "--warn", "--bad", "--code-inline", "--shadow-1", "--tap")


class Element:
    """Un element din HTML: eticheta, atributele, linia și tot textul din interior."""

    def __init__(self, tag: str, attrs: dict, line: int):
        """Reține eticheta, atributele și linia; textul se adună pe parcurs."""
        self.tag, self.attrs, self.line, self.parts = tag, attrs, line, []

    @property
    def text(self) -> str:
        """Textul din interior, cu spațiile strânse."""
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


class Page(HTMLParser):
    """Parsează pagina într-o listă de elemente (cu text) și o listă de bucăți de text vizibil."""

    def __init__(self):
        """Pregătește listele."""
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.texts: list[tuple[str, int]] = []
        self._open: list[Element] = []

    def handle_starttag(self, tag, attrs):
        """Înregistrează elementul; cele cu conținut rămân deschise până la închidere."""
        element = Element(tag, {k.lower(): (v or "") for k, v in attrs}, self.getpos()[0])
        self.elements.append(element)
        if tag not in VOID_TAGS:
            self._open.append(element)

    def handle_startendtag(self, tag, attrs):
        """Etichetele auto-închise (ex. <path/>) nu au conținut."""
        self.elements.append(Element(tag, {k.lower(): (v or "") for k, v in attrs}, self.getpos()[0]))

    def handle_endtag(self, tag):
        """Scoate din stivă elementul închis (și orice element rămas deschis peste el)."""
        while self._open:
            if self._open.pop().tag == tag:
                break

    def handle_data(self, data):
        """Adaugă textul la toate elementele deschise; textul din script/style nu e text vizibil."""
        for element in self._open:
            element.parts.append(data)
        if data.strip() and not any(e.tag in ("script", "style") for e in self._open):
            self.texts.append((data, self.getpos()[0]))


def parse_page() -> Page:
    """Pagina aplicatie.html parsată."""
    page = Page()
    page.feed(PAGE_FILE.read_text(encoding="utf-8"))
    page.close()
    return page


PAGE = parse_page()
HTML_TEXT = PAGE_FILE.read_text(encoding="utf-8")
CSS_TEXT = CSS_FILE.read_text(encoding="utf-8")


def elements(tag: str) -> list[Element]:
    """Toate elementele cu eticheta dată."""
    return [e for e in PAGE.elements if e.tag == tag]


def by_id(element_id: str) -> Element | None:
    """Elementul cu id-ul dat sau None."""
    return next((e for e in PAGE.elements if e.attrs.get("id") == element_id), None)


# ---------- HTML: structură și accesibilitate ----------

def test_page_has_one_h1_and_the_landmarks():
    """Un singur h1; header, main și footer o dată fiecare; limba română; fără blocarea zoom-ului."""
    assert len(elements("h1")) == 1
    for tag in ("header", "main", "footer"):
        assert len(elements(tag)) == 1, f"<{tag}> trebuie să apară o singură dată"
    assert elements("html")[0].attrs.get("lang") == "ro"
    viewport = next(e for e in elements("meta") if e.attrs.get("name") == "viewport")
    assert "user-scalable" not in viewport.attrs["content"] and "maximum-scale" not in viewport.attrs["content"]


def test_page_has_nothing_inline():
    """Fără scripturi, stiluri sau atribute de eveniment inline: politica de conținut le-ar bloca."""
    assert not elements("style"), "un <style> inline ar fi blocat de style-src 'self'"
    for script in elements("script"):
        assert script.attrs.get("src", "").startswith("assets/") and not script.text.strip(), f"script inline la linia {script.line}"
    for element in PAGE.elements:
        assert "style" not in element.attrs, f"<{element.tag}> linia {element.line} are atribut style"
        inline = [name for name in element.attrs if name.startswith("on")]
        assert not inline, f"<{element.tag}> linia {element.line} are {inline}"


def test_stylesheets_and_scripts_are_local_files_that_exist():
    """Fiecare script și foaie de stil din pagină e un fișier din assets/ care există pe disc."""
    refs = [e.attrs["src"] for e in elements("script")] + [e.attrs["href"] for e in elements("link") if e.attrs.get("rel") == "stylesheet"]
    assert refs
    for ref in refs:
        assert ref.startswith("assets/") and (INTERFACE_DIR / ref).is_file(), f"{ref} nu există"


def test_script_order_matches_the_modules_on_disk():
    """Scripturile sunt exact cele din ordinea așteptată, iar fiecare app-*.js de pe disc e încărcat (niciun fișier orfan)."""
    order = tuple(e.attrs["src"] for e in elements("script"))
    assert order == EXPECTED_SCRIPT_ORDER
    on_disk = {f"assets/{p.name}" for p in APP_JS_FILES}
    assert on_disk == {s for s in order if s.startswith("assets/app-")}


def test_ids_are_unique_and_every_reference_resolves():
    """Nicio id dublă; for, aria-labelledby, aria-controls, aria-describedby și linkurile #... duc la un element existent."""
    ids = [e.attrs["id"] for e in PAGE.elements if "id" in e.attrs]
    assert len(ids) == len(set(ids)), f"id-uri duble: {sorted({i for i in ids if ids.count(i) > 1})}"
    known = set(ids)
    for element in PAGE.elements:
        for name in ("for", "aria-labelledby", "aria-controls", "aria-describedby"):
            for target in element.attrs.get(name, "").split():
                assert target in known, f"<{element.tag}> linia {element.line}: {name}=\"{target}\" nu există"
        href = element.attrs.get("href", "")
        if element.tag == "a" and href.startswith("#"):
            assert href[1:] in known, f"link spre {href} fără țintă (linia {element.line})"


def test_every_control_has_an_accessible_name():
    """Butoane, linkuri și rezumate au text sau aria-label; câmpurile au <label for> sau aria-label."""
    labelled = {e.attrs["for"] for e in elements("label") if "for" in e.attrs}
    for element in PAGE.elements:
        if element.tag in ("button", "summary", "a") and (element.tag != "a" or "href" in element.attrs):
            assert element.text or element.attrs.get("aria-label"), f"<{element.tag}> linia {element.line} fără nume"
        if element.tag == "input" and element.attrs.get("type", "text") not in ("hidden",):
            assert element.attrs.get("id") in labelled or element.attrs.get("aria-label"), f"<input> linia {element.line} fără etichetă"


def test_inputs_have_names_and_no_autofill_traps():
    """Câmpurile au `name`, `autocomplete="off"` (nu sunt câmpuri de cont) și nu sunt de tip parolă."""
    for element in elements("input"):
        assert element.attrs.get("name"), f"<input> linia {element.line} fără name"
        assert element.attrs.get("autocomplete") == "off", f"<input> linia {element.line}: autocomplete trebuie să fie off"
        assert element.attrs.get("type", "text") != "password"


def test_screens_inventory_and_headings():
    """Exact cele 10 ecrane; fiecare (în afară de loading) are un titlu h2 țintă de focus (tabindex=-1) legat prin aria-labelledby."""
    screens = [e for e in PAGE.elements if e.tag == "section" and "data-screen" in e.attrs]
    assert tuple(s.attrs["data-screen"] for s in screens) == EXPECTED_SCREENS
    for screen in screens:
        if screen.attrs["data-screen"] == "loading":
            assert screen.attrs.get("aria-label")
            continue
        heading = by_id(screen.attrs["aria-labelledby"])
        assert heading is not None and heading.tag == "h2" and heading.attrs.get("tabindex") == "-1", screen.attrs["data-screen"]
        assert screen.attrs.get("hidden") is not None, f"ecranul {screen.attrs['data-screen']} trebuie să pornească ascuns"


def test_live_regions_and_progressbar_are_wired():
    """Zona live globală există; bara de progres are rol, interval și etichetă; câmpurile cu mesaje au aria-live."""
    live = by_id("app-live")
    assert live is not None and live.attrs.get("aria-live") == "polite" and live.attrs.get("role") == "status"
    bar = by_id("progress-bar")
    assert bar.attrs.get("role") == "progressbar" and bar.attrs.get("aria-labelledby") == "progress-label"
    assert (bar.attrs.get("aria-valuemin"), bar.attrs.get("aria-valuemax")) == ("0", "100")
    for hint_id in ("threshold-hint", "session-msg", "dl-msg", "start-error"):
        assert by_id(hint_id).attrs.get("aria-live") == "polite", hint_id


def test_content_security_policy_meta_matches_the_server_policy():
    """Meta CSP din pagină = politica trimisă de server, fără frame-ancestors (care nu merge în meta)."""
    meta = next(e for e in elements("meta") if e.attrs.get("http-equiv") == "Content-Security-Policy")
    assert meta.attrs["content"] + "; frame-ancestors 'none'" == CONTENT_SECURITY_POLICY


def test_links_are_local_and_new_tabs_are_hardened():
    """Linkurile merg la #ancore sau la index.html; cele cu target=_blank au rel=noopener noreferrer; ancorele din index.html există."""
    index_ids = set(re.findall(r'\bid="([^"]+)"', (INTERFACE_DIR / "index.html").read_text(encoding="utf-8")))
    for link in elements("a"):
        href = link.attrs.get("href", "")
        assert href.startswith("#") or re.fullmatch(r"index\.html(#[a-z-]+)?", href), f"link neașteptat: {href}"
        if "#" in href and not href.startswith("#"):
            assert href.split("#")[1] in index_ids, f"index.html nu are ancora {href}"
        if link.attrs.get("target") == "_blank":
            assert {"noopener", "noreferrer"} <= set(link.attrs.get("rel", "").split()), f"{href}: target=_blank fără rel"


def test_every_link_to_the_explanatory_site_has_a_text_alternative():
    """Fiecare link spre index.html (care merge doar din folder) are lângă el textul alternativ pentru pagina servită de aplicație."""
    links = [e for e in elements("a") if "docs-link" in e.attrs.get("class", "")]
    alternatives = [e for e in elements("span") if "docs-alt" in e.attrs.get("class", "")]
    assert len(links) == len(alternatives) >= 4
    assert all(a.attrs["href"].startswith("index.html") for a in links)
    assert all("deschide_interfata.bat" in a.text for a in alternatives)
    assert all(a.attrs.get("href", "").startswith("#") or "docs-link" in a.attrs.get("class", "") for a in elements("a")), "orice link spre index.html trebuie să fie docs-link"


def test_faq_has_every_question_as_native_details():
    """Cele 12 întrebări din brief, ca <details> native cu <summary>, cu id-uri stabile; toate legăturile #faq-... duc la ele."""
    items = [e for e in PAGE.elements if e.tag == "details" and "faq__item" in e.attrs.get("class", "")]
    assert tuple(i.attrs["id"] for i in items) == EXPECTED_FAQ
    assert len(elements("summary")) == len(items) + 1  # +1: „Schimbă pragul” (details-ul de opțiuni)
    for link in elements("a"):
        if link.attrs.get("href", "").startswith("#faq-"):
            assert link.attrs["href"][1:] in EXPECTED_FAQ


def test_faq_honest_statements_are_present():
    """Afirmațiile oneste cerute în brief apar în FAQ: neafiliat cu eMAG, termeni, nevalidat cap-la-cap, verifică cu „Comenzile mele”."""
    text = re.sub(r"\s+", " ", "".join(t for t, _ in PAGE.texts))
    for required in ("neafiliat cu eMAG", "contrar termenilor", "nu a fost încă validată cap la cap", "Comenzile mele",
                     "fără telemetrie, fără server al autorului", "doar când apeși pe ele, în browserul tău",
                     "nu în Registry, nu în AppData, nu în folderul tău personal", "Parola nu trece prin program"):
        assert required in text, f"lipsește din pagină: {required!r}"


# ---------- reguli de text ----------

def _visible_strings() -> list[tuple[str, str]]:
    """(unde, text) pentru tot ce vede omul: textul din HTML, titlul filei, descrierea și aria-label-urile."""
    found = [(f"aplicatie.html:{line}", text) for text, line in PAGE.texts]
    for element in PAGE.elements:
        for name in ("aria-label", "title"):
            if element.attrs.get(name):
                found.append((f"aplicatie.html:{element.line} ({name})", element.attrs[name]))
        if element.tag == "meta" and element.attrs.get("name") == "description":
            found.append((f"aplicatie.html:{element.line} (description)", element.attrs["content"]))
    return found


def _is_user_text(literal: str) -> bool:
    """True pentru un literal JS care arată a text pentru om (nu selector, nume de atribut sau cheie)."""
    return " " in literal and not re.search(r"[\[\]=#{}]|^[.#]", literal)


def _copy_problems(where: str, text: str) -> list[str]:
    """Încălcările regulilor de text: ghilimele drepte, trei puncte, sedilă, ghilimele românești dezechilibrate."""
    problems = []
    if '"' in text:
        problems.append(f'{where}: ghilimele drepte în text vizibil: {text!r} (folosește „ ”)')
    if "..." in text:
        problems.append(f"{where}: trei puncte în loc de … : {text!r}")
    if any(ch in text for ch in CEDILLA):
        problems.append(f"{where}: s sau t cu sedilă în loc de virgulă: {text!r}")
    if "“" in text or text.count(OPEN_QUOTE) != text.count(CLOSE_QUOTE):
        problems.append(f"{where}: ghilimele românești nepotrivite („ … ”): {text!r}")
    return problems


def test_visible_html_text_follows_the_copy_rules():
    """Textul din HTML: fără ghilimele drepte, fără „...”, ș/ț cu virgulă, ghilimele românești în pereche."""
    problems = [p for where, text in _visible_strings() for p in _copy_problems(where, text)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", APP_JS_FILES, ids=lambda p: p.name)
def test_user_visible_strings_in_scripts_follow_the_copy_rules(path):
    """Textele scrise în JavaScript pentru om respectă aceleași reguli ca textul din HTML."""
    views = scan_js(path.read_text(encoding="utf-8"))
    problems = [p for line, literal in views.strings if _is_user_text(literal) for p in _copy_problems(f"{path.name}:{line}", literal)]
    assert not problems, "\n".join(problems)


def test_screens_have_no_technical_jargon():
    """Pe ecrane (în afara FAQ-ului) nu apar cuvinte tehnice: token, API, server, JSON, HTTP, localhost, cookie, proxy..."""
    problems = []
    for screen in (e for e in PAGE.elements if e.tag == "section" and "data-screen" in e.attrs):
        words = set(re.findall(r"[a-zăâîșț]+", screen.text.lower()))
        problems += [f"{screen.attrs['data-screen']}: «{w}»" for w in JARGON if w in words]
    assert not problems, "\n".join(problems)


def test_no_script_text_with_technical_jargon_in_visible_messages():
    """Mesajele scrise în JavaScript pentru om (în afara FAQ-ului) nu conțin cuvinte tehnice."""
    problems = []
    for path in APP_JS_FILES:
        for line, literal in scan_js(path.read_text(encoding="utf-8")).strings:
            if _is_user_text(literal):
                words = set(re.findall(r"[a-zăâîșț]+", literal.lower()))
                problems += [f"{path.name}:{line}: «{w}» în «{literal}»" for w in JARGON if w in words]
    assert not problems, "\n".join(problems)


# ---------- JavaScript: rețea, stocare, cheie ----------

def _code(path) -> str:
    """Vederea de cod a unui fișier JS (fără comentarii și fără conținutul literalelor)."""
    return scan_js(path.read_text(encoding="utf-8")).code


def test_only_the_api_client_makes_network_requests_and_only_to_api_paths():
    """`fetch(` apare o singură dată, în app-api.js; fiecare cerere pornește dintr-o cale literală /api/...; fără XHR, WebSocket, beacon."""
    forbidden = re.compile(r"\b(?:XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts)\b|(?<![\w$.])import\s*\(")
    for path in APP_JS_FILES:
        code = _code(path)
        assert not forbidden.search(code), f"{path.name}: cerere de rețea în afara lui fetch"
        calls = len(re.findall(r"\bfetch\s*\(", code))
        assert calls == (1 if path.name == API_FILE_NAME else 0), f"{path.name}: {calls} apeluri fetch"
    api_text = (ASSETS_DIR / API_FILE_NAME).read_text(encoding="utf-8")
    api_calls = re.findall(r"\brequest\(\s*'(GET|POST)'\s*,\s*'(/api/[^']*)'", api_text)
    assert len(api_calls) >= 9, "app-api.js: cererile trebuie să pornească din căi literale /api/..."
    assert len(api_calls) == len(re.findall(r"\brequest\(\s*'", api_text)), "o cerere nu pornește dintr-o cale literală"
    assert not re.search(r"https?://|//127\.|localhost", _code(ASSETS_DIR / API_FILE_NAME) + " ".join(l for _, l in scan_js(api_text).strings))


def test_the_access_key_stays_in_memory_and_leaves_only_in_the_header():
    """Cheia: scoasă din adresă cu replaceState, trimisă doar în X-App-Token; niciun fișier în afară de app-api.js n-o atinge, nimic nu o scrie în storage."""
    api = (ASSETS_DIR / API_FILE_NAME).read_text(encoding="utf-8")
    api_code = scan_js(api).code
    assert "replaceState" in api_code and "X-App-Token" in api
    assert not re.search(r"localStorage|sessionStorage|document\s*\.\s*cookie|indexedDB|window\s*\.\s*name\b", api_code)
    for path in APP_JS_FILES:
        if path.name == API_FILE_NAME:
            continue
        code = _code(path)
        assert not re.search(r"\btoken\b", code), f"{path.name} nu are ce căuta la cheia de acces"
        if path.name != "app-faq.js":
            assert not re.search(r"location\s*\.\s*hash", code), f"{path.name} citește fragmentul adresei, unde stă cheia"
    # cheia nu se lipește niciodată de un text (adresă, interogare, mesaj): doar se pune în antet
    assert not re.search(r"\+\s*token\b|\btoken\s*\+|\$\{\s*token", scan_js(api).uncommented)


def test_browser_storage_is_used_only_for_the_theme():
    """localStorage/sessionStorage/cookie/IndexedDB apar doar în app-theme.js, și acolo doar cu cheia 'emag-tema'."""
    pattern = re.compile(r"localStorage|sessionStorage|document\s*\.\s*cookie|indexedDB|caches\b")
    for path in APP_JS_FILES:
        found = pattern.findall(_code(path))
        if path.name == THEME_FILE_NAME:
            assert found and "'emag-tema'" in path.read_text(encoding="utf-8")
        else:
            assert not found, f"{path.name} scrie sau citește din stocarea browserului"


def test_no_html_injection_or_dynamic_code_in_scripts():
    """Fără innerHTML/outerHTML/insertAdjacentHTML/document.write/eval/Function și fără atribut style scris ca text: textul intră prin textContent."""
    forbidden = re.compile(r"\binnerHTML\b|\bouterHTML\b|\binsertAdjacentHTML\b|\bdocument\s*\.\s*write\b|\beval\s*\(|\bnew\s+Function\b|\bcssText\b|setAttribute\(\s*['\"]style")
    for path in APP_JS_FILES:
        found = forbidden.findall(_code(path)) + forbidden.findall(" ".join(l for _, l in scan_js(path.read_text(encoding="utf-8")).strings))
        assert not found, f"{path.name}: {found}"


# ---------- compatibilitate cu garda de rețea ----------

@pytest.mark.parametrize("path", [PAGE_FILE, CSS_FILE, *APP_JS_FILES], ids=lambda p: p.name)
def test_page_scripts_and_stylesheet_pass_the_network_guard(path):
    """Garda de rețea (test_garda_retea.interface_violations, cu excepția ei pentru app-api.js) nu găsește nimic în pagină, în CSS și în app-*.js."""
    assert interface_violations(path) == []


# ---------- CSS ----------

def test_css_has_no_unsafe_patterns():
    """Fără @import și url() externe, fără `transition: all`; outline: none doar pe ținte de focus mutate prin script; există reduced-motion și forced-colors."""
    assert "@import" not in CSS_TEXT and "url(" not in CSS_TEXT
    assert not re.search(r"transition\s*:\s*all\b", CSS_TEXT)
    for selector in re.findall(r"([^{}]+)\{[^{}]*outline\s*:\s*none", CSS_TEXT):
        assert "focus" in selector and "focus-visible" not in selector, f"outline: none fără înlocuitor: {selector.strip()}"
    assert ":focus-visible" in CSS_TEXT
    assert "@media (prefers-reduced-motion: reduce)" in CSS_TEXT and "@media (forced-colors: active)" in CSS_TEXT
    assert "touch-action: manipulation" in CSS_TEXT


def test_tokens_shared_with_the_site_stylesheet_have_the_same_values():
    """Tokenii comuni cu site.css (hârtie, cerneală, focus, stări...) au aceleași valori în cele trei teme."""
    app = parse_token_blocks(CSS_TEXT)
    site = parse_token_blocks(SITE_CSS_FILE.read_text(encoding="utf-8"))
    differences = []
    for theme in ("light", "dark-auto", "dark"):
        for name in SHARED_TOKENS:
            if app[theme].get(name) != site[theme].get(name):
                differences.append(f"{theme} {name}: app.css={app[theme].get(name)} site.css={site[theme].get(name)}")
    assert not differences, "app.css s-a depărtat de site.css (aliniază valorile):\n" + "\n".join(differences)


def test_automatic_dark_theme_equals_forced_dark_theme():
    """Tema întunecată automată (media query) și cea forțată (data-theme=dark) definesc aceiași tokeni cu aceleași valori."""
    blocks = parse_token_blocks(CSS_TEXT)
    assert blocks["dark-auto"] == blocks["dark"]
    light_colors = {name for name, value in blocks["light"].items() if re.match(r"^(#|rgba?\()", value)}
    assert light_colors == set(blocks["dark"]), "fiecare token de culoare trebuie redefinit în tema întunecată (și doar ei)"


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_text_and_control_colors_meet_wcag_contrast(theme):
    """Perechile de culori folosite pentru text ating 4.5:1, iar focusul și conturul controalelor 3:1, în ambele teme."""
    t = parse_token_blocks(CSS_TEXT)[theme]
    text_pairs = [
        ("--ink", "--paper"), ("--ink", "--card"), ("--ink-2", "--paper"), ("--ink-2", "--card"), ("--ink-3", "--paper"),
        ("--ink-3", "--card"), ("--ok", "--paper"), ("--ok", "--card"), ("--bad", "--paper"), ("--bad", "--card"),
        ("--warn", "--paper"), ("--warn", "--card"), ("--paper", "--ink"), ("--on-hl", "--hl"), ("--on-bad", "--bad"),
        ("--ink", "--code-inline"),
    ]
    failures = []
    for foreground, background in text_pairs:
        under = t["--paper"] if background == "--code-inline" else None
        ratio = contrast(t[foreground], t[background], under)
        if ratio < MIN_TEXT_CONTRAST:
            failures.append(f"{theme} {foreground} pe {background}: {ratio:.2f}:1 (minim {MIN_TEXT_CONTRAST}:1)")
    for background_token in ("--paper", "--card"):
        ratio = contrast(t["--ink"], t["--hl-wash"], t[background_token])
        if ratio < MIN_TEXT_CONTRAST:
            failures.append(f"{theme} --ink pe --hl-wash peste {background_token}: {ratio:.2f}:1")
    for foreground, background in (("--focus", "--paper"), ("--focus", "--card"), ("--ctl", "--card"), ("--ctl", "--paper"), ("--on-ok", "--ok")):
        ratio = contrast(t[foreground], t[background])
        if ratio < MIN_UI_CONTRAST:
            failures.append(f"{theme} {foreground} pe {background}: {ratio:.2f}:1 (minim {MIN_UI_CONTRAST}:1 pentru controale)")
    assert not failures, "\n".join(failures)


# ---------- valori oglindite din settings.py ----------

def _js_constant(file_name: str, constant: str) -> int:
    """Valoarea numerică a unei constante `const NUME = valoare;` dintr-un fișier JS."""
    match = re.search(rf"const {constant} = ([0-9_]+);", (ASSETS_DIR / file_name).read_text(encoding="utf-8"))
    assert match, f"{file_name}: nu găsesc constanta {constant}"
    return int(match.group(1))


def test_threshold_constants_mirror_settings():
    """Pragul implicit și plafonul din pagină sunt cele din settings.py (aceeași regulă ca la --prag)."""
    assert _js_constant("app-threshold.js", "DEFAULT_THRESHOLD_LEI") == settings.BIG_PURCHASE_THRESHOLD_LEI
    assert _js_constant("app-threshold.js", "MAX_THRESHOLD_LEI") == settings.MAX_BIG_PURCHASE_THRESHOLD_LEI


def _settings_default(variable: str) -> int:
    """Valoarea IMPLICITĂ dintr-un `os.environ.get("NUME", "valoare")` din settings.py (nu cea din mediul de acum)."""
    match = re.search(rf'os\.environ\.get\("{variable}",\s*"(\d+)"\)', (settings.PROJECT_ROOT / "emag_spend" / "settings.py").read_text(encoding="utf-8"))
    assert match, f"settings.py: nu găsesc implicitul lui {variable}"
    return int(match.group(1))


def test_faq_numbers_match_the_documented_defaults():
    """FAQ-ul spune „10 minute” de login și „câte 3 pagini odată”: exact implicitele documentate în settings.py."""
    text = re.sub(r"\s+", " ", "".join(t for t, _ in PAGE.texts)).replace("\xa0", " ")
    assert f"{_settings_default('EMAG_LOGIN_WAIT_SECONDS') // 60} minute (implicit)" in text
    assert f"câte {_settings_default('EMAG_FETCH_CONCURRENCY')} pagini odată" in text


def test_faq_idle_shutdown_matches_the_server_default():
    """FAQ-ul spune „30 de minute” de inactivitate: exact DEFAULT_IDLE_MINUTES din app_server.py (dacă serverul există)."""
    server_file = settings.PROJECT_ROOT / "emag_spend" / "app_server.py"
    if not server_file.exists():
        pytest.skip("emag_spend/app_server.py nu există")
    match = re.search(r"^DEFAULT_IDLE_MINUTES = (\d+)", server_file.read_text(encoding="utf-8"), re.M)
    assert match, "nu găsesc DEFAULT_IDLE_MINUTES în app_server.py"
    text = re.sub(r"\s+", " ", "".join(t for t, _ in PAGE.texts))
    assert f"după {match.group(1)} de minute fără nicio cerere" in text


def test_app_api_and_expected_hello_match_the_contract():
    """Numele aplicației și versiunea de API așteptate la /api/hello sunt cele din contract."""
    text = (ASSETS_DIR / "app-lifecycle.js").read_text(encoding="utf-8")
    assert "const EXPECTED_APP = 'cheltuieli-emag';" in text and "const EXPECTED_API_VERSION = 1;" in text
    api = (ASSETS_DIR / API_FILE_NAME).read_text(encoding="utf-8")
    for name in ("raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt"):
        assert f"'{name}'" in api
        assert f'data-file="{name}"' in HTML_TEXT


def test_porneste_bat_named_in_the_page_exists():
    """Pagina trimite omul la porneste.bat: fișierul trebuie să existe în rădăcina proiectului (îl scrie alt agent)."""
    if not (settings.PROJECT_ROOT / "porneste.bat").exists():
        pytest.skip("porneste.bat nu există încă (îl scrie agentul «aplicatie-server»)")
    assert (settings.PROJECT_ROOT / "porneste.bat").is_file()
