"""Verificări statice (fără browser) ale site-ului din interfata/: structură, linkuri, reguli oglindite din cod.

Primește: interfata/index.html, assets/site*.js și site.css, deschide_interfata.bat, README.md și codul programului.
Verifică: id-uri și linkuri interne, lipsa resurselor externe, ordinea scripturilor clasice, regulile de status
oglindite în simulator, mesajele din „Probleme și soluții” (trebuie să existe în cod), valorile implicite scrise în text.
NU deschide browserul: comportamentul din pagină (tastatură, încărcare de fișier, teme) se verifică separat, cu Playwright.
"""

import html
import importlib
import re
from html.parser import HTMLParser

import pytest

from emag_spend import block_status, settings

SITE_DIR = settings.PROJECT_ROOT / "interfata"
ASSETS_DIR = SITE_DIR / "assets"
INDEX = (SITE_DIR / "index.html").read_text(encoding="utf-8")
CSS = (ASSETS_DIR / "site.css").read_text(encoding="utf-8")
SITE_JS = {path.name: path.read_text(encoding="utf-8") for path in sorted(ASSETS_DIR.glob("site*.js"))}

REQUIRED_SECTION_IDS = (
    "start", "cum-functioneaza", "raport-demo", "calcul", "pentru-cine", "confidentialitate",
    "incarca", "fisiere", "comenzi", "intrebari", "probleme",
)
# Blocurile din contractul EmagDashboard (data-ed-block); site-ul le folosește la adnotări.
CONTRACT_BLOCKS = {
    "hero", "funnel", "tiles", "categories", "highlights", "years", "big", "top", "preturi", "sellers", "excluded", "control", "method",
}
# Spațiul de nume SVG e un identificator, nu o cerere de rețea.
ALLOWED_URLS = {"http://www.w3.org/2000/svg"}
MIN_FAQ_QUESTIONS = 10
# Cod inline mai scurt de atât (în mono, ~230 px) încape pe un rând chiar și în cea mai îngustă celulă stivuită (320 px).
MAX_NOWRAP_CODE_CHARS = 28
# Opțiuni din ruleaza.py care nu sunt comenzi pentru om (fiecare celălalt trebuie să apară pe pagină).
UNDOCUMENTED_FLAGS = {"--fara-confirmare"}  # doar pentru scripturi și teste: sare peste întrebarea de la --sterge-sesiunea
# Fragmente de mesaje REALE din program, citate în tabelul „Probleme și soluții”.
# Fiecare trebuie să existe și în cod, și în pagină: dacă mesajul se schimbă într-unul, testul spune în care.
PROBLEM_MESSAGE_FRAGMENTS = (
    "nu te-ai logat în timpul alocat; rulează din nou scriptul",
    "nu conține 'Comanda nr.' (sesiune expirată?)",
    "nu conține 'Retur #' (sesiune expirată?)",
    "redirecționat la login pentru",
    "nu am putut descărca",
    "nicio comandă pe prima pagină a listei (sesiune expirată sau pagină schimbată?)",
    "a listei nu s-a încărcat",
    "status necunoscut la comanda",
    "nu are potrivire în comanda",
    "nu e în lista citită",
    "nu are nicio comandă asociată",
    "produse necategorizate (adaugă reguli în config/categorii.json)",
    "retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate",
    "retururi finalizate fără sumă restituită afișată",
    "≠ 'Total produse'",
    "≠ componente",
    "comenzi la care totalul din antet ≠ suma blocurilor",
    "nume de produs în HTML ≠",
    "produse din linii",
    "se folosesc numele din linii",
    "lanțul sumelor nu se închide: comandat",
    "expresie regulată greșită în categoria",
    "categorie duplicată în reguli",
    "o categorie din reguli nu are nume",
    "nu are niciun model în 'patterns'",
    "(nu e un folder de rulare complet)",
    "1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat",
    "contul nu are retururi sau pagina s-a schimbat",
    "nu are produse listate",
    "lipsește 'Total produse'",
    "lipsește 'Total platit'",
    "niciun produs găsit",
    "nicio secțiune de vânzător găsită",
    "≠ numărul cerut",
    "fișierul de design",
)


class _Page(HTMLParser):
    """Strânge din index.html ce interesează testele: id-uri, linkuri, scripturi, <code>, text vizibil."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs, self.srcs, self.scripts, self.codes = [], [], [], [], []
        self.metas, self.text, self.details_ids = [], [], []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "details" and attrs.get("id"):
            self.details_ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.hrefs.append(attrs["href"])
        if tag in ("link",) and "href" in attrs:
            self.srcs.append(attrs["href"])
        if tag in ("script", "img", "source", "iframe") and "src" in attrs:
            self.srcs.append(attrs["src"])
        if tag == "script":
            self.scripts.append(attrs)
        if tag in ("code", "kbd", "pre"):
            self.codes.append((tag, attrs, any(flag for _, flag in self._stack)))
        if tag == "meta":
            self.metas.append(attrs)
        void = tag in ("meta", "link", "br", "img", "input", "hr", "path", "circle", "rect", "i")
        if not void:
            self._stack.append((tag, attrs.get("translate") == "no" or tag in ("code", "kbd", "pre")))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        tags = {t for t, _ in self._stack}
        if not tags & {"script", "style", "code", "pre", "kbd", "textarea", "title"}:
            self.text.append(data)


PAGE = _Page()
PAGE.feed(INDEX)


def _strip_js_comments(source: str) -> str:
    """JS fără comentarii (blocuri /* */ și linii //), ca interdicțiile să nu se declanșeze pe explicații."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_every_required_section_has_a_stable_id():
    """Cele 11 secțiuni din cuprins există cu id-ul stabil, plus antetul, conținutul și subsolul."""
    for section_id in REQUIRED_SECTION_IDS + ("antet", "continut", "subsol"):
        assert section_id in PAGE.ids, f"lipsește id-ul #{section_id}"


def test_ids_are_unique():
    """Niciun id nu apare de două ori (linkurile directe ar duce la locul greșit)."""
    duplicates = sorted({i for i in PAGE.ids if PAGE.ids.count(i) > 1})
    assert not duplicates, duplicates


def test_internal_links_point_to_existing_ids():
    """Fiecare href="#token" (sau "#token/sub") duce la un id existent."""
    missing = sorted({h for h in PAGE.hrefs if h.startswith("#") and len(h) > 1 and h[1:].split("/")[0] not in PAGE.ids})
    assert not missing, missing


def test_site_uses_no_external_resources():
    """Nicio cerere către internet: fără URL-uri absolute, fonturi sau @import în HTML, CSS și JS."""
    for name, text in [("index.html", INDEX), ("site.css", CSS)] + list(SITE_JS.items()):
        found = {u for u in re.findall(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s\"'`)<>]*", text) if u not in ALLOWED_URLS}
        found = {u for u in found if not u.startswith(("//www.emag", "//emag"))}
        assert not found, f"{name}: {sorted(found)}"
    assert "@import" not in CSS and "@font-face" not in CSS
    for src in PAGE.srcs:
        assert not re.match(r"^(?:[a-z]+:)?//", src) and not src.startswith(("http:", "https:")), src


def test_scripts_are_classic_existing_and_in_dependency_order():
    """Scripturi clasice (nu merg modulele pe file://), toate există; componenta și datele vin înaintea site-ului."""
    sources = []
    for attrs in PAGE.scripts:
        if "src" not in attrs:
            continue
        assert attrs.get("type") != "module", attrs
        assert (SITE_DIR / attrs["src"]).is_file(), attrs["src"]
        sources.append(attrs["src"])
    names = [s.rsplit("/", 1)[-1] for s in sources]
    assert names[0] == "site-boot.js", "scriptul din <head> (clasa js, tema salvată) rulează înaintea tuturor"
    assert names[1:3] == ["dashboard.js", "demo-data.js"]
    assert names[-1] == "site.js"
    for needed_first in ("site-dom.js", "site-format.js", "site-state.js"):
        assert names.index(needed_first) < names.index("site-theme.js")
    on_disk = {path.name for path in ASSETS_DIR.glob("site*.js")}
    assert on_disk == {n for n in names if n.startswith("site")}, "un fișier site*.js nu e încărcat (sau invers)"


def test_theme_color_is_declared_for_both_schemes():
    """meta theme-color există pentru schema luminoasă și pentru cea întunecată."""
    medias = sorted(m.get("media", "") for m in PAGE.metas if m.get("name") == "theme-color")
    assert medias == ["(prefers-color-scheme: dark)", "(prefers-color-scheme: light)"]


def test_viewport_does_not_block_zoom():
    """Fără user-scalable=no și fără maximum-scale."""
    content = next(m["content"] for m in PAGE.metas if m.get("name") == "viewport")
    assert "user-scalable" not in content and "maximum-scale" not in content


def test_code_elements_are_marked_do_not_translate():
    """Toate <code>, <kbd> și <pre> au translate="no" (sau stau într-un element cu translate="no")."""
    bare = [(tag, attrs) for tag, attrs, inside in PAGE.codes if attrs.get("translate") != "no" and not inside]
    assert not bare, bare[:3]


def test_visible_text_uses_curly_quotes_and_real_ellipsis():
    """În text vizibil: ghilimele românești și „…”, nu ghilimele drepte sau trei puncte."""
    text = " ".join(PAGE.text)
    assert '"' not in text, re.findall(r'.{20}".{20}', text)[:3]
    assert "..." not in text


def test_simulator_status_rules_mirror_block_status():
    """Lista de fraze din simulator e identică (conținut și ordine) cu block_status._RULES."""
    source = SITE_JS["site-simulator.js"]
    body = re.search(r"var STATUS_RULES = \[(.*?)\];", source, re.S).group(1)
    pairs = re.findall(r"\['([^']+)',\s*'([A-Z_]+)'\]", body)
    assert pairs == list(block_status._RULES)
    assert {name for _, name in pairs} <= {block_status.DELIVERED, block_status.CANCELLED, block_status.IN_PROGRESS, block_status.PAID_ONLY}


def test_problem_messages_exist_in_code_and_in_the_page():
    """Mesajele citate în tabelul de probleme sunt cele reale din program (și invers: nu s-au schimbat în cod)."""
    code = "\n".join(path.read_text(encoding="utf-8") for path in (settings.PROJECT_ROOT / "emag_spend").glob("*.py"))
    page_text = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    for fragment in PROBLEM_MESSAGE_FRAGMENTS:
        assert fragment in code, f"nu mai există în cod: {fragment!r}"
        assert fragment in page_text, f"lipsește din pagină: {fragment!r}"


def test_defaults_written_in_the_text_match_the_settings(monkeypatch):
    """Valorile implicite din text (10 minute, câte 3 odată, 3 încercări, prag 500, limită 25 MB) coincid cu setările."""
    for name in ("EMAG_LOGIN_WAIT_SECONDS", "EMAG_FETCH_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    fresh = importlib.reload(settings)
    try:
        assert fresh.LOGIN_WAIT_SECONDS == 600 and "10&nbsp;minute" in INDEX
        assert fresh.FETCH_CONCURRENCY == 3 and "câte 3 odată" in INDEX
        assert fresh.FETCH_RETRIES == 3 and "de 3 ori la rând" in INDEX
        assert fresh.LIST_RENDER_TIMEOUT_SECONDS == 25 and "25 de secunde" in INDEX and "în 25s" in INDEX
        assert fresh.BIG_PURCHASE_THRESHOLD_LEI == 500 and 'data-bind="threshold">500<' in INDEX
    finally:
        importlib.reload(settings)
    max_bytes = re.search(r"var MAX_BYTES = (\d+) \* 1024 \* 1024;", SITE_JS["site-viewer.js"])
    assert max_bytes and int(max_bytes.group(1)) == 25 and "25&nbsp;MB" in INDEX


def test_annotations_cover_exactly_the_contract_blocks():
    """Adnotările folosesc exact cele 13 valori data-ed-block din contract, iar componenta le și desenează."""
    used = re.findall(r"\{ slug: '[a-z]+', block: '([a-z]+)'", SITE_JS["site-annotations.js"])
    assert sorted(used) == sorted(CONTRACT_BLOCKS)
    dashboard = settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8")
    for name in CONTRACT_BLOCKS:
        assert f"block('{name}'" in dashboard, f"dashboard.js nu desenează blocul {name}"
    slugs = re.findall(r"slug: '([a-z]+)'", SITE_JS["site-annotations.js"])
    assert len(slugs) == len(set(slugs)) == len(CONTRACT_BLOCKS)


def test_faq_has_enough_questions_with_direct_links():
    """Cel puțin 10 întrebări <details>, fiecare cu id faq-… pentru linkuri directe."""
    faq_ids = [i for i in PAGE.details_ids if i.startswith("faq-")]
    assert len(faq_ids) >= MIN_FAQ_QUESTIONS
    assert set(PAGE.details_ids) - set(faq_ids) == {"paste"}, "un <details> din afara întrebărilor nu are id faq-…"


def test_site_scripts_make_no_network_calls_and_never_use_innerhtml():
    """Fără fetch/XHR/WebSocket/eval și fără innerHTML: numele din analiza.json sunt date neîncrezute."""
    forbidden = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "eval(", "new Function", "innerHTML", "outerHTML", "document.write", "import(")
    for name, source in SITE_JS.items():
        code = _strip_js_comments(source)
        for token in forbidden:
            assert token not in code, f"{name}: {token}"


def test_every_site_script_starts_with_a_header_comment():
    """Fiecare site*.js începe cu un antet care îi spune numele, ce face, ce primește și ce nu e treaba lui."""
    for name, source in SITE_JS.items():
        assert source.startswith(f"/* {name} —"), name
        header = source.split("*/", 1)[0]
        assert 3 <= header.count("\n") <= 9, f"{name}: antetul are {header.count(chr(10))} rânduri"


def test_css_follows_the_interface_rules():
    """Teme duble, mișcare redusă, focus vizibil; fără transition: all și fără outline: none neînlocuit."""
    assert ':root:not([data-theme="light"])' in CSS and ':root[data-theme="dark"]' in CSS
    assert "prefers-reduced-motion: reduce" in CSS and "prefers-reduced-motion: no-preference" in CSS
    assert ":focus-visible" in CSS and "color-scheme: dark" in CSS and "color-scheme: light" in CSS
    assert not re.search(r"transition\s*:\s*all", CSS)
    for match in re.finditer(r"([^{}]*)\{[^{}]*outline\s*:\s*none", CSS):
        assert ":focus:not(:focus-visible)" in match.group(1) or "main:focus" in match.group(1), match.group(1).strip()
    assert "touch-action" in CSS or "touch-action" in "".join(SITE_JS.values())
    assert "text-wrap: balance" in CSS and "tabular-nums" in CSS


def test_launcher_is_crlf_and_opens_the_site():
    """deschide_interfata.bat are sfârșituri de rând CRLF și deschide interfata/index.html."""
    data = (settings.PROJECT_ROOT / "deschide_interfata.bat").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b'start "" "%~dp0interfata\\index.html"' in data, "cale absolută: merge și pe un share de rețea"
    assert b"cd /d" not in data and b'if not exist "%~dp0interfata\\index.html"' in data, "fără cd (pică pe UNC) și cu verificare că fișierul există"


def test_readme_has_the_interface_section():
    """README.md are secțiunea „Interfața” și pomenește lansatorul."""
    readme = (settings.PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Interfața" in readme and "deschide_interfata.bat" in readme


@pytest.mark.parametrize("name", sorted(SITE_JS))
def test_site_scripts_are_plain_scripts(name):
    """Fără import/export la nivel de fișier: scripturile clasice nu pot fi module pe file://."""
    code = _strip_js_comments(SITE_JS[name])
    assert not re.search(r"(?m)^\s*(import|export)\s", code), name


# Formulări găsite false (sau înșelătoare) la auditul de adevăr: nu au voie să reapară în pagină sau în scripturi.
FALSE_CLAIMS = (
    "Singurul server", "singura ieșire", "face cereri doar către", "Nimic nu pleacă din calculator",
    "Mai jos e lista completă", "Lipește mesajul tău", "nu deschid browserul", "ritm redus",
    "Autentificare, o singură dată", "în curs aqua", "Anterioara", "Totul rulează în browser",
    "Cum e garantat în cod", "Nimic din cont.", "Cele mai scumpe produse păstrate", "os.startfile",
)


def test_page_title_is_a_short_name():
    """Titlul paginii e numele, fără explicație după liniuță."""
    title = re.search(r"<title>([^<]*)</title>", INDEX).group(1)
    assert title == "Cheltuieli eMAG", title


def test_false_claims_found_by_the_audit_do_not_come_back():
    """Nicio formulare dovedită falsă nu mai apare în index.html sau în site*.js."""
    for name, text in [("index.html", INDEX)] + list(SITE_JS.items()):
        for claim in FALSE_CLAIMS:
            assert claim not in text, f"{name}: {claim!r}"


def test_honest_statements_are_present():
    """Ce trebuie spus deschis: starea testării, cererile ferestrei Edge, textul liber salvat, pauzele dintre cereri."""
    assert "nu a fost rulată încă de la cap la coadă pe un cont real" in INDEX
    assert "testele au trecut pe Python 3.13 și 3.14; 3.10–3.12 nu au fost încercate" in INDEX
    assert "3.13 și 3.14" in (settings.PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8"), "instaleaza.bat și pagina spun același lucru despre versiuni"
    assert "contactează și serviciile lor" in INDEX and "Programul nu controlează aceste cereri" in INDEX
    assert "câteva câmpuri se salvează ca text liber" in INDEX and "Ce face parserul" in INDEX
    assert "fără pauze între ele (pauză doar după o eroare)" in INDEX
    assert "Profilul complet de" in INDEX and "nu accepta salvarea parolelor sau a cardurilor" in INDEX


def test_unstyled_lists_keep_their_list_semantics():
    """Fiecare <ul>/<ol> din pagină are role="list": toate au list-style: none, iar Safari/VoiceOver le scoate altfel din arborele de accesibilitate."""
    tags = re.findall(r"<(?:ul|ol)\b[^>]*>", INDEX)
    assert len(tags) >= 9, tags
    assert all('role="list"' in tag for tag in tags), [t for t in tags if 'role="list"' not in t]


def test_annotation_dom_order_follows_the_focus_order():
    """Lista, apoi explicația, apoi raportul: de la o adnotare, focusul nu trece prin tot raportul înainte de butoane."""
    positions = [INDEX.index(f'id="{name}"') for name in ("demo-rail", "demo-win", "demo-caption", "demo-scroll")]
    assert positions == sorted(positions)


def test_hotspots_are_outside_the_tab_order_and_the_accessibility_tree():
    """Punctele numerotate dublează lista: tabindex -1 și aria-hidden, ca să nu dubleze nici opririle de tastatură."""
    code = _strip_js_comments(SITE_JS["site-annotations.js"])
    block = code[code.index("function buildHotspots"):code.index("function buildCaption")]
    assert "tabindex: '-1'" in block and "'aria-hidden': 'true'" in block


def test_report_headings_sit_one_level_below_the_section_title():
    """Raportul montat în pagină cere headingLevel 3: altfel ar adăuga 12 titluri h2 la fiecare montare."""
    for name in ("site-annotations.js", "site-viewer.js"):
        code = _strip_js_comments(SITE_JS[name])
        assert re.search(r"REPORT_HEADING_LEVEL = 3;", code), name
        assert "headingLevel: REPORT_HEADING_LEVEL" in code, name


def test_every_module_starts_in_isolation_from_one_list():
    """site.js pornește fiecare modul dintr-o listă, cu căutarea lui Site.<nume> în try: un script lipsă nu oprește restul."""
    source = _strip_js_comments(SITE_JS["site.js"])
    startup = re.findall(r"'([a-z]+)'", re.search(r"var STARTUP = \[(.*?)\];", source, re.S).group(1))
    modules = {name[len("site-"):-len(".js")] for name in SITE_JS if name.startswith("site-")} - {"dom", "format", "boot"}
    assert modules <= set(startup), sorted(modules - set(startup))
    assert startup[-2:] == ["state", "hash"], "adresa pornește după toate modulele, apoi pagina se așază la #hash"
    assert not re.search(r"safely\('[a-z]+',\s*Site\.", source), "Site.<nume> evaluat înaintea lui try"


def test_inline_styles_go_through_cssom_for_a_strict_csp():
    """Fără atribute style în HTML și fără setAttribute('style'): stilul se pune prin CSSOM (merge și sub style-src 'self')."""
    assert not re.search(r"\sstyle=", INDEX)
    assert "el.style.cssText" in _strip_js_comments(SITE_JS["site-dom.js"])
    for name, source in SITE_JS.items():
        assert "setAttribute('style'" not in _strip_js_comments(source), name


def test_page_declares_a_content_security_policy_and_has_no_inline_code():
    """Politica din <meta> (default-src 'none'; script/style doar 'self') face din „nicio cerere de rețea” o garanție a browserului."""
    policy = next((m["content"] for m in PAGE.metas if m.get("http-equiv", "").lower() == "content-security-policy"), "")
    directives = {part.split()[0]: part.split()[1:] for part in policy.split(";") if part.strip()}
    assert directives.get("default-src") == ["'none'"], policy
    assert directives.get("script-src") == ["'self'"] and directives.get("style-src") == ["'self'"], policy
    assert directives.get("img-src") == ["data:"], "doar pictograma din pagină (data:), nicio imagine de pe internet"
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert PAGE.scripts and all("src" in attrs for attrs in PAGE.scripts), "script inline în index.html"
    assert PAGE.scripts[0]["src"] == "assets/site-boot.js"
    assert not re.search(r"<style[\s>]", INDEX) and not re.search(r"\son[a-z]+=", INDEX), "stil sau handler inline"
    boot = _strip_js_comments(SITE_JS["site-boot.js"])
    assert "classList.add('js')" in boot and "emag-tema" in boot


def test_readme_does_not_repeat_the_false_claims():
    """README.md nu mai spune că testele nu deschid browserul și nu definește „în curs” prin plată (programul nu o verifică)."""
    readme = (settings.PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for claim in FALSE_CLAIMS + ("plătit dar nelivrat",):
        assert claim not in readme, claim
    assert "Programul nu verifică plata" in readme and "pornesc Edge sau Chrome" in readme


def test_every_command_line_option_is_documented_on_the_page():
    """Fiecare opțiune din ruleaza.py (în afară de cele pentru scripturi) apare în pagină: o opțiune nouă fără explicație pică testul."""
    source = (settings.PROJECT_ROOT / "ruleaza.py").read_text(encoding="utf-8")
    flags = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', source))
    assert {"--prag", "--demo", "--sterge-sesiunea"} <= flags, flags
    page_text = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    missing = sorted(flag for flag in flags - UNDOCUMENTED_FLAGS if flag not in page_text)
    assert not missing, f"opțiuni nedocumentate în pagină: {missing}"


def test_every_launcher_in_the_project_root_is_documented_on_the_page():
    """Fiecare *.bat din rădăcina proiectului apare în pagină: un lansator nou fără explicație pică testul."""
    page_text = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    launchers = sorted(path.name for path in settings.PROJECT_ROOT.glob("*.bat"))
    assert {"login.bat", "ruleaza.bat", "deschide_interfata.bat"} <= set(launchers), launchers
    missing = [name for name in launchers if name not in page_text]
    assert not missing, f"lansatoare nedocumentate în pagină: {missing}"


# Lansatoarele care instalează singure mediul când lipsește: nu mai trimit omul la instaleaza.bat, deci nu au mesajul de mai jos.
SELF_INSTALLING_LAUNCHERS = {"instaleaza.bat", "porneste.bat"}


def test_missing_environment_message_is_the_one_the_launchers_print():
    """Rândul din „Probleme și soluții” pentru lipsa mediului .venv citează exact mesajul din lansatoare (cele care nu-l instalează singure)."""
    message = "Programul nu este instalat încă. Rulează mai întâi instaleaza.bat, apoi încearcă din nou."
    assert message in html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    needing_env = [path for path in settings.PROJECT_ROOT.glob("*.bat")
                   if path.name not in SELF_INSTALLING_LAUNCHERS and ".venv\\Scripts\\python.exe" in path.read_text(encoding="utf-8")]
    assert needing_env, "niciun lansator nu folosește .venv?"
    assert all(message in path.read_text(encoding="utf-8") for path in needing_env), [p.name for p in needing_env]


def test_error_lines_described_on_the_page_are_what_ruleaza_prints():
    """Pagina spune că erorile așteptate, inclusiv cele de browser (Playwright), apar ca „EROARE: …” + „Jurnal complet: …”."""
    source = (settings.PROJECT_ROOT / "ruleaza.py").read_text(encoding="utf-8")
    # clauza except care prinde erorile de browser (alte clauze, de ex. la scrierea aplicației, prind altceva)
    caught = re.search(r"except \(([^)]*PlaywrightError[^)]*)\)", source).group(1)
    assert "PlaywrightError" in caught and "RuntimeError" in caught, caught
    assert "EROARE: {message}" in source and "Jurnal complet: {log_path}" in source
    page_text = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    assert "„EROARE: …”" in page_text and "„Jurnal complet: …”" in page_text and "prima linie a erorii Playwright" in page_text


def test_nowrap_code_is_short_enough_for_a_phone():
    """Cod cu class="nb" (nowrap) de peste 28 de caractere n-ar încăpea într-o celulă de 320 px: ar ieși din ecran."""
    too_long = [text for text in re.findall(r'<code class="nb" translate="no">([^<]+)</code>', INDEX) if len(re.sub(r"&[a-z]+;", "x", text)) > MAX_NOWRAP_CODE_CHARS]
    assert not too_long, too_long


def test_short_inline_code_is_marked_nowrap():
    """Cod inline fără spații și de cel mult 28 de caractere poartă class="nb": „--din-cache” nu se rupe la cratimă, nici căile la „/”."""
    loose = [text for text in re.findall(r'<code translate="no">([^<\s]+)</code>', INDEX) if len(re.sub(r"&[a-z]+;", "x", text)) <= MAX_NOWRAP_CODE_CHARS]
    assert not loose, loose


def test_css_fixes_from_the_visual_audit_stay_in_place():
    """Reguli al căror ordin sau context a fost cauza defectului (tabele, marker, bară laterală, bon, fără JS, semne în summary)."""
    assert re.search(r"@media \(min-width: 760px\) \{\s*\.tbl--problems tbody th \{ width: 34%; \}\s*\}", CSS), "lățimea coloanei bate stivuirea"
    assert ".tbl--stack caption:not(.sr-only)" in CSS
    marker = re.search(r"\.marker \{([^}]*)\}", CSS).group(1)
    assert "color: var(--on-hl)" in marker and "white-space: nowrap" in marker and "58%" not in marker
    assert re.search(r"\.site-head__actions \{ order: 2;", CSS) and re.search(r"\.site-nav \{\s*order: 3;", CSS)
    assert re.search(r"\.ticket__row, \.ticket__total \{[^}]*flex-wrap: wrap", CSS) and re.search(r"\.chain__row \{[^}]*flex-wrap: wrap", CSS), "rândurile bonului și ale lanțului se rup doar când nu mai încap"
    assert all(f"html:not(.js) {selector}" in CSS for selector in (".annot ~ .note", "[data-copy-from]", ".flow__pause")), "controale moarte fără JS"
    assert "html:not(.js) .hero__piece" in CSS and re.search(r"html:not\(\.js\) \.site-head \{ position: static; \}", CSS)
    assert CSS.count('content: "+" / ""') == 2 and CSS.count('content: "−" / ""') == 2
    assert re.search(r"a, button, summary, label, input", CSS) and "touch-action: manipulation" in CSS


def test_threshold_field_is_text_so_it_does_not_depend_on_the_browser_language():
    """Câmpul de prag e text cu parsare proprie („1.000”, „499,99”), plafonat; nu <input type=number>."""
    field = re.search(r'<input class="field__input" id="sim-threshold"[^>]*>', INDEX).group(0)
    assert 'type="text"' in field and 'inputmode="decimal"' in field and 'type="number"' not in field
    code = _strip_js_comments(SITE_JS["site-simulator.js"])
    assert re.search(r"var MAX_THRESHOLD_LEI = \d+;", code) and "function parseLei" in code


def test_hero_counts_every_row_with_the_same_progress():
    """Bonul numără toate rândurile deodată, iar „păstrat” se deduce din celelalte: fără decalaje între rânduri."""
    code = _strip_js_comments(SITE_JS["site-hero.js"])
    assert "COUNT_STAGGER_MS" not in code and "KEPT_KEY" in code and "ORDERED_KEY" in code
