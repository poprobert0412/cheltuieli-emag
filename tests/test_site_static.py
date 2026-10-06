"""Verificări statice (fără browser) ale site-ului din interfata/: structură, linkuri, reguli oglindite din cod.

Primește: interfata/index.html, assets/site*.js și site.css, deschide_interfata.bat, documentele (README, SECURITY, CONTRIBUTING,
docs/INSTALARE.md) și codul programului. Verifică: id-uri și linkuri interne, lipsa resurselor externe, ordinea scripturilor,
regulile de status oglindite în simulator, mesajele din „Probleme și soluții” (trebuie să existe în cod), valorile implicite
scrise în text, opțiunile și variabilele documentate și faptele despre actualizări (rețea, ce se păstrează) față de cod, inclusiv
cele de după reparațiile din 6 oct. 2026: ce rămâne în .actualizare, recuperarea la pornire, lansarea doar după teste, testul din
lansarea anterioară, arhiva uv și fișierele-contract din CONTRIBUTING; plus a treia rundă (P1–P10): recuperarea înaintea pregătirii
lansatorului, fișierele utilizatorului pe căile programului, retragerea doar după publicare, rândurile lui „plătit efectiv”, descărcările
oprite, folderele refuzate ca legături, arhivele uv șterse și mesajele noi. NU deschide browserul (comportamentul din pagină: Playwright).
"""

import html
import importlib
import inspect
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

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
UNDOCUMENTED_FLAGS = {"--fara-confirmare"}  # doar pentru scripturi și teste: sare peste întrebarea de la --sterge-sesiunea și --actualizeaza
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
    "produse necategorizate (adaugă reguli în config/categorii.personal.json)",
    "retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate",
    "retururi finalizate fără sumă restituită afișată",
    "≠ 'Total produse'",
    "≠ componente",
    "comenzi la care totalul din antet ≠ suma blocurilor",
    "nume de produs în HTML ≠",
    "produse din linii",
    "se folosesc numele din linii",
    "lanțul sumelor nu se închide: comandat",
    "lanțul sumelor plătite nu se închide",
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
    "mod de restituire necunoscut",
    "tratat ca bani primiți înapoi (adaugă-l în config/restituiri.json)",
    # actualizarea (update_http.py, update_download.py, update_apply.py / update_archive.py, app_update_job.py)
    "Folderul ăsta e o copie git: actualizează cu git pull.",
    "Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată.",
    "Limita de cereri GitHub a fost atinsă; încearcă peste o oră.",
    "Amprenta arhivei descărcate nu se potrivește cu SHA256SUMS.txt al lansării; am șters-o, nimic nu s-a instalat.",
    "Actualizarea nu s-a putut instala (",
    "); am revenit la versiunea ",
    ", nu s-a schimbat nimic.",
    "a fost întreruptă; am revenit la versiunea ",
    "Actualizarea nu poate porni cât rulează o analiză. Așteaptă să se termine sau oprește-o.",
    "Calea folderului programului e prea lungă pentru Windows (",
    # după reparațiile din 6 oct. 2026: lacătul de sistem (update_lock.py) și legăturile refuzate (update_apply.py, update_recovery.py)
    "O altă actualizare e în curs (alt program deschis din același folder).",
    "e o legătură spre alt loc; din siguranță, nu ",
    # a treia rundă (P1, P5): revenirea care nu se poate termina oprește pornirea (update_recovery.MESSAGE_REVERT_INCOMPLETE)
    "), iar revenirea la versiunea ",
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


def test_the_guide_has_the_interface_section():
    """Ghidul (docs/INSTALARE.md) descrie cele două pagini și pomenește lansatorul site-ului; README trimite la ghid."""
    guide = (settings.PROJECT_ROOT / "docs" / "INSTALARE.md").read_text(encoding="utf-8")
    assert "### Cele două pagini din `interfata/`" in guide and "deschide_interfata.bat" in guide
    assert "](docs/INSTALARE.md)" in (settings.PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


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
# Devenite false odată cu actualizările (5 oct. 2026): aplicația locală întreabă GitHub de versiunea nouă și o instalează la cerere.
UPDATE_FALSE_CLAIMS = (
    "nu își face singur actualizări", "are nevoie de internet doar ca să citească", "nimic nu pleacă de pe calculatorul tău",
    "nimic nu se trimite nicăieri.", "singura conexiune în afara calculatorului rămâne",
)
FALSE_CLAIMS += UPDATE_FALSE_CLAIMS
# README e scurt; detaliile stau în ghid, în regulile de calcul și în întrebările frecvente (mutate din README pe 6 oct. 2026).
DOCUMENTS = ("README.md", "SECURITY.md", "CONTRIBUTING.md", "docs/INSTALARE.md", "docs/CALCUL.md", "docs/INTREBARI.md")


def test_page_title_is_a_short_name():
    """Titlul paginii e numele, fără explicație după liniuță."""
    title = re.search(r"<title>([^<]*)</title>", INDEX).group(1)
    assert title == "Cheltuieli eMAG", title


def test_false_claims_found_by_the_audit_do_not_come_back():
    """Nicio formulare dovedită falsă nu mai apare în index.html sau în site*.js."""
    for name, text in [("index.html", INDEX)] + list(SITE_JS.items()):
        for claim in FALSE_CLAIMS:
            assert claim not in text, f"{name}: {claim!r}"


def _launcher_versions() -> dict[str, str]:
    """Valorile din instalare/versiuni.txt (rânduri CHEIE=valoare; cele cu # sunt comentarii), citite ca de lansatoare."""
    text = (settings.PROJECT_ROOT / "instalare" / "versiuni.txt").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in map(str.strip, text.splitlines()) if line and not line.startswith("#"))


def test_honest_statements_are_present():
    """Ce trebuie spus deschis: starea testării, cererile ferestrei de browser, textul liber salvat, pauzele dintre cereri."""
    assert "a rulat cap-coadă pe un singur cont real, pe Windows" in INDEX and "testată doar cu pagini inventate" in INDEX
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
    """README și regulile de calcul nu mai spun că testele nu deschid browserul și nu definesc „în curs” prin plată (programul nu
    o verifică); regulile de calcul spun asta, iar CONTRIBUTING spune că testele de interfață pornesc browserul."""
    readme = (settings.PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    calculation = (settings.PROJECT_ROOT / "docs" / "CALCUL.md").read_text(encoding="utf-8")
    for claim in FALSE_CLAIMS + ("plătit dar nelivrat",):
        assert claim not in readme and claim not in calculation, claim
    assert "Programul nu verifică plata" in calculation
    assert "pornesc Edge sau Chrome" in (settings.PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")


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


# Lansatoarele care pregătesc singure mediul când lipsește: nu trimit omul la porneste.bat, deci nu au mesajul de mai jos.
SELF_INSTALLING_LAUNCHERS = {"instaleaza.bat", "porneste.bat"}


def test_install_facts_on_the_pages_match_the_launchers():
    """Pagina descrie pregătirea așa cum o fac lansatoarele: fișierele numite există, versiunea de Python e cea fixată în
    instalare/versiuni.txt, iar nicio pagină nu mai cere Python instalat de mână (mesajele vechi ar trimite omul greșit)."""
    text = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
    for launcher in ("porneste.bat", "porneste.command", "porneste.sh", "instaleaza.bat", "instalare/pregatire.sh", "instalare/versiuni.txt"):
        assert (settings.PROJECT_ROOT / launcher).is_file(), launcher
        assert launcher in text, launcher
    assert f"Python {_launcher_versions()['PYTHON_VERSION']}" in text, "versiunea de Python din pagină trebuie să fie cea din instalare/versiuni.txt"
    for needed in (".uv/", ".venv/", "SHA-256", "„Deschide oricum”", "Windows 10", "Apple Silicon", "x86_64", "arm64", "Chromium"):
        assert needed in text, needed
    app = (SITE_DIR / "aplicatie.html").read_text(encoding="utf-8")
    for page_name, page in (("index.html", INDEX), ("aplicatie.html", app)):
        for outdated in ("Python 3.10", "3.10 sau mai nou", "pip install -r requirements.txt", "python.org", "nu este instalat încă", "Doar prima instalare"):
            assert outdated not in page, f"{page_name}: {outdated}"


def test_missing_environment_message_is_the_one_the_launchers_print():
    """Rândul din „Probleme și soluții” pentru lipsa mediului .venv citează exact mesajul din lansatoare (cele care nu-l pregătesc singure)."""
    message = "Programul nu este pregătit încă. Dă mai întâi dublu-clic pe porneste.bat: pregătește singur tot ce lipsește."
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
    """Bonul numără toate rândurile deodată, iar „plătit efectiv” se deduce din celelalte (cu transportul adunat): fără decalaje între rânduri."""
    code = _strip_js_comments(SITE_JS["site-hero.js"])
    assert "COUNT_STAGGER_MS" not in code and "TOTAL_KEY" in code and "ORDERED_KEY" in code and "ADDED_KEYS" in code
    assert 'data-key="spent_bani"' in INDEX and 'data-key="fees_bani"' in INDEX, "bonul arată lanțul în bani plătiți"


# ---------- documentația actualizărilor, față de cod (decis 5 oct. 2026) ----------

def _document(name: str) -> str:
    """Textul unui document al proiectului (README.md, SECURITY.md, CONTRIBUTING.md, docs/INSTALARE.md)."""
    return (settings.PROJECT_ROOT / name).read_text(encoding="utf-8")


def _command_line_flags() -> set[str]:
    """Opțiunile declarate în ruleaza.py (add_argument("--…"))."""
    source = (settings.PROJECT_ROOT / "ruleaza.py").read_text(encoding="utf-8")
    return set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', source))


def _environment_variables() -> set[str]:
    """Variabilele EMAG_* din antetul lui settings.py (singura lor listă documentată în cod)."""
    return set(re.findall(r"^\s+(EMAG_[A-Z_]+)\s", settings.__doc__ or "", re.M))


def _visible(fragment: str) -> str:
    """Textul vizibil dintr-un fragment HTML, cu spațiile nedespărțitoare făcute spații obișnuite."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace(chr(0xA0), " ")


def test_documents_do_not_repeat_the_claims_made_false_by_the_updates():
    """README, SECURITY, CONTRIBUTING și INSTALARE nu mai spun că programul nu iese pe internet decât spre eMAG sau că nu se actualizează."""
    for name in DOCUMENTS:
        text = _document(name)
        for claim in UPDATE_FALSE_CLAIMS:
            assert claim not in text, f"{name}: {claim!r}"


def test_install_guide_documents_every_option_and_every_environment_variable():
    """Tabelele din docs/INSTALARE.md au fiecare opțiune din ruleaza.py și fiecare variabilă din antetul lui settings.py."""
    guide = _document("docs/INSTALARE.md")
    flags = _command_line_flags()
    assert {"--versiune", "--actualizeaza", "--aplicatie"} <= flags, flags
    missing_flags = sorted(flag for flag in flags if f"`{flag}" not in guide)
    assert not missing_flags, f"opțiuni nedocumentate în docs/INSTALARE.md: {missing_flags}"
    variables = _environment_variables()
    assert {"EMAG_UPDATE_CHECK", "EMAG_PROFILE_DIR"} <= variables, variables
    missing_variables = sorted(name for name in variables if f"| `{name}` |" not in guide)
    assert not missing_variables, f"variabile lipsă din tabelul docs/INSTALARE.md: {missing_variables}"


def test_the_network_facts_about_updates_are_the_ones_in_the_code():
    """SECURITY.md citează exact cererea de verificare (adresă, antete), gazdele permise și limita de redirecționări din cod."""
    from emag_spend import update_check, update_http
    security = _document("SECURITY.md")
    api_url = update_check.LATEST_RELEASE_API_URL.format(repository=settings.UPDATE_REPOSITORY)
    assert urlsplit(api_url).hostname == "api.github.com" and "api.github.com" in update_http.ALLOWED_HOSTS
    assert f"GET {api_url}" in security
    assert f"Accept: {update_http.JSON_ACCEPT}" in security
    assert update_http.USER_AGENT.startswith("cheltuieli-emag/") and "User-Agent: cheltuieli-emag/<versiune>" in security
    assert all(f"`{host}`" in security for host in update_http.ALLOWED_HOSTS), sorted(update_http.ALLOWED_HOSTS)
    assert f"cel mult {update_http.MAX_REDIRECTS}" in security
    asset_prefix = update_check.ASSET_URL_PREFIX.format(repository=settings.UPDATE_REPOSITORY, tag="vX.Y.Z")
    assert asset_prefix in security and update_check.ZIP_NAME_TEMPLATE.format(tag="vX.Y.Z") in security and update_check.SUMS_NAME in security
    assert "nu de un cont GitHub compromis" in security, "limita onestă: amprenta vine din același loc ca arhiva"


def test_the_switch_that_stops_the_update_check_is_the_one_settings_reads(monkeypatch):
    """EMAG_UPDATE_CHECK=0, scris în pagină și în documente, chiar oprește verificarea; altă valoare n-o oprește."""
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "0")
    assert settings.update_check_enabled() is False
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "1")
    assert settings.update_check_enabled() is True
    for name in ("README.md", "SECURITY.md", "docs/INSTALARE.md"):
        assert "EMAG_UPDATE_CHECK=0" in _document(name), name
    assert "EMAG_UPDATE_CHECK=0" in _visible(INDEX)


def test_what_the_documents_say_an_update_keeps_is_really_protected():
    """Fiecare folder și fișier despre care paginile spun că rămâne neatins e protejat de cod; SECURITY.md le numește pe toate."""
    from emag_spend import update_archive
    kept = ("iesiri/", "logs/", ".profil_browser/", ".uv/", ".venv/", "config/categorii.personal.json")
    for path in kept:
        assert update_archive.is_protected(path + "raport.html" if path.endswith("/") else path), path
    faq = _visible(re.search(r'<details id="faq-actualizari">.*?</details>', INDEX, re.S).group(0))
    readme = _document("README.md")
    for path in kept:
        assert path in faq and f"`{path}`" in readme, path
    security = _document("SECURITY.md")
    for folder in update_archive.PROTECTED_DIRS:
        assert f"`{folder}/`" in security, folder
    for file_name in update_archive.PROTECTED_FILES:
        assert f"`{file_name}`" in security, file_name
    assert f"`{update_archive.MANIFEST_PATH}`" in security and settings.UPDATE_WORK_DIR.name == ".actualizare"


def test_the_app_texts_quoted_by_the_documents_exist_in_the_app():
    """Butonul, banda și mesajele din aplicație citate în documente și în pagină există în aplicatie.html sau în app-update.js."""
    app = (SITE_DIR / "aplicatie.html").read_text(encoding="utf-8") + (ASSETS_DIR / "app-update.js").read_text(encoding="utf-8")
    for text in ("Actualizează acum", "Versiune nouă: ", "Verificarea versiunilor noi e oprită."):
        assert text in app, text
    assert "„Actualizează acum”" in _visible(INDEX)
    assert "Verificarea versiunilor noi e oprită." in _document("docs/INSTALARE.md")
    from emag_spend import session_cleaner
    assert session_cleaner.CONFIRMATION_WORD == "DA" and "confirmi cu `DA`" in _document("README.md")


# ---------- documentele, față de comportamentul de după reparațiile din 6 oct. 2026 (N1–N14) ----------

# Formulări adevărate înainte de reparații și false acum: nu au voie să reapară în documente, pe site sau în aplicație.
STALE_AFTER_REPAIRS = (
    "cel mult arhiva",  # N9: fiecare descărcare are folderul ei, șters la final; în .actualizare rămâne doar lacătul gol
    "cu arhiva versiunii noi",
    "fiecare fișier vechi se mută în",  # N1: întâi copia de siguranță, apoi un singur os.replace (fișierul nu lipsește nicio clipă)
    "pornește singur din nou programul",  # N2: după o revenire programul face comanda cerută, fără repornire (fără codul 75)
    "porneste.* pornește singur din nou",
    "după revenirea de la una întreruptă",
    "în cod nu există Path.home, tempfile, winreg",  # garda de scriere permite acum tempfile.mkdtemp(dir=…), N9
)
# Paginile citite pentru afirmațiile de mai sus: documentele, site-ul și aplicația.
TEXTS_ABOUT_UPDATES = DOCUMENTS + ("CHANGELOG.md", "interfata/index.html", "interfata/aplicatie.html")


def _plain_document(name: str) -> str:
    """Textul unui document sau al unei pagini, fără marcaje (etichetele unei pagini .html, `cod`, **îngroșat**), cu spațiile strânse.

    Într-un .md etichetele rămân: acolo `<versiune>` sau `<rulare>` sunt text, nu HTML.
    """
    text = _document(name)
    text = _visible(text) if name.endswith(".html") else text.replace(chr(0xA0), " ")
    return re.sub(r"\s+", " ", text.replace("`", "").replace("**", ""))


def _row(text: str, start: str) -> str:
    """Rândul de tabel (Markdown sau HTML) care începe cu `start`: de la `start` până la sfârșitul rândului."""
    assert start in text, start
    rest = text[text.index(start):]
    return rest[:rest.index("\n")] if "\n" in rest else rest


def test_the_claims_made_false_by_the_repairs_do_not_come_back():
    """Nicio pagină nu mai spune că în .actualizare rămâne arhiva, că fișierul vechi e mutat înainte de înlocuire sau că lansatorul
    repornește după revenirea de la o actualizare întreruptă."""
    found = [f"{name}: {claim!r}" for name in TEXTS_ABOUT_UPDATES for claim in STALE_AFTER_REPAIRS if claim in _plain_document(name)]
    assert not found, found


def _update_folder_places() -> dict[str, str]:
    """Locurile care spun ce conține .actualizare, ca fragment brut (rând de tabel, arbore sau întrebare din aplicatie.html)."""
    return {
        "SECURITY.md": _row(_document("SECURITY.md"), "| `.actualizare/` |"),
        "docs/INSTALARE.md": _document("docs/INSTALARE.md").split("└─ .actualizare/", 1)[1].split("```", 1)[0],
        "index.html": _row(INDEX, '<tr><th scope="row" data-label="Loc"><code class="nb" translate="no">.actualizare/</code>'),
        "aplicatie.html": re.search(r'<details class="faq__item" id="faq-salvare">.*?</details>',
                                    (SITE_DIR / "aplicatie.html").read_text(encoding="utf-8"), re.S).group(0),
    }


def _flat(fragment: str) -> str:
    """Textul vizibil al unui fragment (HTML sau Markdown), fără `cod` și **îngroșat**, cu spațiile strânse."""
    return re.sub(r"\s+", " ", _visible(fragment).replace("`", "").replace("**", ""))


def test_every_page_says_what_stays_in_the_update_folder_after_an_update():
    """N5, N9: după o actualizare, în .actualizare rămâne doar fișierul-lacăt, gol; SECURITY numește tot ce apare acolo cât ține ea."""
    from emag_spend import update_recovery
    after = f"rămâne doar fișierul gol {update_recovery.LOCK_NAME}"
    places = _update_folder_places()
    for place, text in places.items():
        assert after in _flat(text), f"{place}: lipsește «{after}»"
    security_row = places["SECURITY.md"]
    names = [*update_recovery.WORK_SUBDIRS, settings.UPDATE_DOWNLOAD_DIR.name]
    assert settings.UPDATE_DOWNLOAD_DIR.parent == settings.UPDATE_WORK_DIR, "descărcările stau în folderul actualizării"
    assert all(f"`{name}/`" in security_row for name in names), names
    assert f"`{update_recovery.JOURNAL_NAME}`" in security_row and f"`{update_recovery.LOCK_NAME}`" in security_row


def test_the_backup_described_in_security_is_the_one_the_code_makes():
    """N1: SECURITY spune că fișierul vechi primește întâi o copie de siguranță (legătură tare sau copie) și abia apoi e înlocuit."""
    source = (settings.PROJECT_ROOT / "emag_spend" / "update_apply.py").read_text(encoding="utf-8")
    backup = source[source.index("def _backup("):source.index("def _old_program_folder(")]
    assert "os.link(source, target)" in backup and "shutil.copy2" in backup, "copia de siguranță din cod s-a schimbat"
    # P3: un fișier „doar citire” primește copia întreagă (cu atributul), iar înlocuirea îi scoate atributul de pe țintă.
    assert "if is_read_only(source):" in backup, "fișierul „doar citire” nu mai primește copia întreagă"
    security = _plain_document("SECURITY.md")
    for needed in ("legătură tare", "un singur os.replace", "nu lipsește nicio clipă", "pentru fișierele „doar citire”"):
        assert needed in security, needed


def test_the_pages_say_the_program_goes_on_after_undoing_an_interrupted_update():
    """N2: recuperarea rulează la pornire, înaintea oricărui alt import din program, iar apoi programul face ce i s-a cerut
    (fără repornire); paginile spun asta, nu că lansatorul pornește din nou."""
    entry = (settings.PROJECT_ROOT / "ruleaza.py").read_text(encoding="utf-8")
    assert entry.index("from emag_spend.update_recovery import") < entry.index("from playwright"), "recuperarea nu mai e prima"
    for name in ("README.md", "docs/INSTALARE.md", "interfata/index.html"):
        assert "ce i-ai cerut" in _plain_document(name), name


def test_the_lock_wait_written_in_the_guide_is_the_one_in_the_code():
    """N5: ghidul spune cât așteaptă programul o altă actualizare din același folder înainte de mesajul „O altă actualizare e în curs”."""
    from emag_spend import update_lock
    guide = _plain_document("docs/INSTALARE.md")
    assert update_lock.MESSAGE_BUSY.startswith("O altă actualizare e în curs") and "„O altă actualizare e în curs" in guide
    wait = f"{update_lock.LOCK_WAIT_SECONDS:g} secunde"
    for name, text in (("docs/INSTALARE.md", guide), ("index.html", _plain_document("interfata/index.html"))):
        assert wait in text, f"{name}: {wait}"


def _workflow(name: str) -> str:
    """Textul unui workflow din .github/workflows/."""
    return (settings.PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_the_documents_say_a_release_is_published_only_after_the_tests_and_withdrawn_if_the_update_test_fails():
    """N13: în lansare.yml, publicarea așteaptă teste.yml și pornire.yml, iar jobul „retrage” o face prerelease dacă testul
    actualizării nu reușește; SECURITY și CONTRIBUTING spun la fel."""
    release = _workflow("lansare.yml")
    assert "uses: ./.github/workflows/teste.yml" in release and "uses: ./.github/workflows/pornire.yml" in release
    assert re.search(r"(?m)^  lansare:\n(?:    .*\n)*?    needs: \[teste, pornire\]", release), "publicarea nu mai așteaptă testele"
    assert "gh release edit" in release and "--prerelease" in release
    for name in ("SECURITY.md", "CONTRIBUTING.md"):
        text = _plain_document(name)
        for needed in ("teste.yml", "pornire.yml", "prerelease", "nu se publică nimic"):
            assert needed in text, f"{name}: {needed}"
    assert "și cel care o retrage" in _plain_document("SECURITY.md"), "dreptul de scriere al jobului care retrage lansarea"


def test_the_documents_say_the_update_test_also_starts_from_the_previous_release():
    """N14: actualizare.yml ia și lansarea publicată anterioară, neîmbătrânită, pe ambele căi; documentele spun asta."""
    update_test = _workflow("actualizare.yml")
    assert "--exclude-pre-releases" in update_test and "anterioara-a" in update_test and "anterioara-b" in update_test
    for name in ("SECURITY.md", "CONTRIBUTING.md", "docs/INSTALARE.md"):  # README, scurt, nu descrie testele lansării
        assert "lansarea anterioară" in _plain_document(name), name


def test_the_uv_archive_name_in_the_guide_is_the_one_the_launchers_keep():
    """N12: arhiva uv păstrată în .uv/descarcari are versiunea în nume, iar una rămasă cu altă amprentă se descarcă încă o dată."""
    windows = (settings.PROJECT_ROOT / "instaleaza.bat").read_text(encoding="utf-8")
    unix = (settings.PROJECT_ROOT / "instalare" / "pregatire.sh").read_text(encoding="utf-8")
    assert r"\.uv\descarcari\uv-%UV_VERSION%-%UV_TINTA%.zip" in windows
    assert 'ARHIVA_PASTRATA="uv-$UV_VERSION-$TINTA_ARH-$TINTA_OS.tar.gz"' in unix and '"$ROOT/.uv/descarcari/$ARHIVA_PASTRATA"' in unix
    guide = _plain_document("docs/INSTALARE.md")
    assert ".uv/descarcari/uv-<versiune>-" in guide and "se descarcă încă o dată" in guide


def test_contributing_lists_every_file_and_format_the_installed_versions_rely_on():
    """N7: CONTRIBUTING numește fiecare fișier-contract (update_archive.REQUIRED_FILES), formatul jurnalului și al manifestului
    și codul de repornire, ca nimeni să nu le schimbe fără să știe că le citesc versiunile deja instalate."""
    from emag_spend import update_archive, update_recovery
    contributing = _document("CONTRIBUTING.md")
    missing = [path for path in update_archive.REQUIRED_FILES if f"`{path}`" not in contributing]
    assert not missing, f"fișiere-contract nenumite în CONTRIBUTING.md: {missing}"
    for needed in (f"`{update_recovery.WORK_DIR_NAME}/{update_recovery.JOURNAL_NAME}`", "`JOURNAL_FORMAT`", f"`{update_archive.MANIFEST_PATH}`",
                   f"`{update_recovery.WORK_DIR_NAME}/{update_recovery.LOCK_NAME}`", f"codul {settings.EXIT_CODE_RESTART}"):
        assert needed in contributing, needed


def test_security_names_every_guard_test_and_the_narrow_exceptions_they_allow():
    """SECURITY spune ce garantează fiecare tests/test_garda_*.py, inclusiv excepțiile înguste de acum: tempfile.mkdtemp(dir=…)
    pentru folderul unei descărcări și linkul spre pagina lansărilor de pe github.com, doar din app-update.js."""
    readme = _document("SECURITY.md")  # lista s-a mutat din README în SECURITY (6 oct. 2026)
    guards = sorted(path.name for path in (settings.PROJECT_ROOT / "tests").glob("test_garda_*.py"))
    assert {"test_garda_parole.py", "test_garda_retea.py", "test_garda_scriere.py", "test_garda_caractere.py"} <= set(guards), guards
    assert not [name for name in guards if f"`tests/{name}`" not in readme], guards
    download = (settings.PROJECT_ROOT / "emag_spend" / "update_download.py").read_text(encoding="utf-8")
    assert "tempfile.mkdtemp(prefix=DOWNLOAD_FOLDER_PREFIX, dir=base)" in download and "`tempfile.mkdtemp(dir=…)`" in readme
    network_guard = (settings.PROJECT_ROOT / "tests" / "test_garda_retea.py").read_text(encoding="utf-8")
    assert 'RELEASES_LINK_FILE = "interfata/assets/app-update.js"' in network_guard and 'RELEASES_LINK_HOST = "github.com"' in network_guard
    plain = _plain_document("SECURITY.md")
    assert "pagina lansărilor de pe github.com" in plain and "app-update.js" in plain


# ---------- documentele, față de codul de după a treia rundă de reparații (P1–P10, decis 6 oct. 2026) ----------

# Fraza decisă (P10, din P1): lansatoarele desfac o actualizare întreruptă înaintea pregătirii, iar ruleaza.py înaintea restului.
RECOVERY_ORDER = "înaintea pregătirii lansatorului și a restului programului"
# Fraza decisă (P10, din V2-3) și limita ei: actualizarea scrie toate fișierele versiunii noi (D8), deci și peste un fișier al tău.
USER_FILE_PROMISE = "orice fișier pus de tine pe o cale pe care programul nu o folosește"
USER_FILE_LIMIT = "pe o cale adusă de versiunea nouă"
# Fraza decisă (P10, din V2-4): retragerea vine doar din testul de după publicare (jobul „retrage” din lansare.yml).
WEEKLY_RUN_ONLY_SIGNALS = "rularea săptămânală doar semnalează"
# P7: cum numesc textele folderul unei descărcări rămas de la un program închis cât descărca.
STOPPED_DOWNLOAD = "o descărcare oprită la mijloc"
# P9: arhivele uv nu mai rămân în .uv/descarcari după ce uv a fost scos din ele.
UV_ARCHIVES_DELETED = "după o dezarhivare reușită"
# P4: rândurile „Actualizarea nu s-a putut instala (…)” trimit la fișierul din program numit în mesaj, nu la copia din .actualizare.
FILE_NAMED_IN_THE_MESSAGE = "numit în mesaj"
# Ce rulează lansatoarele pentru recuperare (P1) și semnul pus pentru lansatorul repornit imediat după ea.
RECOVERY_ENTRY = "-m emag_spend.update_recovery"
RECOVERY_SIGN = "CHELTUIELI_EMAG_DUPA_RECUPERARE"
# Pasul de pregătire din fiecare lansator care desface singur o actualizare întreruptă (recuperarea trebuie să fie înaintea lui).
LAUNCHER_PREPARATION = {
    "porneste.bat": 'call ".\\instaleaza.bat"',
    "porneste.sh": 'sh "$ROOT/instalare/pregatire.sh"',
    "porneste.command": 'sh "$ROOT/instalare/pregatire.sh"',
}
# Condiția cu care fiecare lansator rulează recuperarea: există jurnalul și Python-ul din .venv (altfel întâi pregătirea).
LAUNCHER_RECOVERY_CONDITION = {
    "porneste.bat": 'if exist ".actualizare\\jurnal.json" if exist ".venv\\Scripts\\python.exe"',
    "porneste.sh": '[ -e "$ROOT/.actualizare/jurnal.json" ] && [ -x "$ROOT/.venv/bin/python" ]',
    "porneste.command": '[ -e "$ROOT/.actualizare/jurnal.json" ] && [ -x "$ROOT/.venv/bin/python" ]',
}
# Mesajul lansatoarelor când recuperarea de dinaintea pregătirii iese cu 1 (update_recovery.EXIT_RECOVERY_FAILED).
LAUNCHER_RECOVERY_STOP = "Pornirea s-a oprit: actualizarea întreruptă nu a putut fi desfăcută."
# Formulări adevărate înainte de P1–P9 (sau mai largi decât codul) și false acum: nu au voie să reapară.
STALE_AFTER_THIRD_REPAIRS = (
    "înaintea oricărui alt cod al programului",  # P1: lansatorul încarcă întâi mediul; fraza decisă e RECOVERY_ORDER
    "înainte de orice altceva, programul vede",
    "care nu face parte din program",  # V2-3: un fișier al tău aflat pe o cale adusă de versiunea nouă e înlocuit
    "care nu sunt în listă, nu se ating",
    "orice fișier pus de tine care nu e în listă",
    "iar o lansare care pică acest test e retrasă",  # V2-4: rularea săptămânală nu retrage nimic
    "Arhiva rămâne în",  # P9: arhivele uv se șterg după dezarhivare
    "(sau un folder din el) care e legătură",  # P8: SECURITY numește exact folderele verificate
)


def _code_lines(source: str, comment: str) -> str:
    """Doar rândurile de cod ale unui script (fără cele care încep cu `comment`), ca o explicație să nu treacă drept comandă."""
    return "\n".join(line for line in source.splitlines() if not line.lstrip().lower().startswith(comment))


def _launcher_code(name: str) -> str:
    """Codul unui lansator din program (`rem` la .bat, `#` la .sh și .command), fără comentarii."""
    source = (settings.PROJECT_ROOT / name).read_text(encoding="utf-8")
    return _code_lines(source, "rem " if name.endswith(".bat") else "#")


def _duration(seconds: int) -> str:
    """O durată în ore întregi, cum o scriu documentele: «o oră», «2 ore»."""
    hours, rest = divmod(seconds, 3600)
    assert hours and not rest, f"{seconds} s nu e un număr întreg de ore: textele ar trebui scrise altfel"
    return "o oră" if hours == 1 else f"{hours} ore"


def test_the_claims_made_false_by_the_third_repairs_do_not_come_back():
    """P1–P9: nicio pagină nu mai spune că recuperarea vine înaintea oricărui alt cod, că orice fișier al tău rămâne, că rularea
    săptămânală retrage o lansare, că arhiva uv rămâne sau că „un folder din .actualizare” oarecare e verificat ca legătură."""
    found = [f"{name}: {claim!r}" for name in TEXTS_ABOUT_UPDATES for claim in STALE_AFTER_THIRD_REPAIRS if claim in _plain_document(name)]
    assert not found, found


def test_the_pages_say_the_recovery_runs_before_the_launcher_prepares_anything():
    """P1: porneste.bat, porneste.sh și porneste.command rulează `python -m emag_spend.update_recovery` (când există jurnalul și Python-ul
    din .venv) înaintea pregătirii; README, SECURITY și ghidul spun fraza decisă, iar SECURITY și ghidul și cazul fără .venv."""
    from emag_spend import update_recovery
    for launcher, preparation in LAUNCHER_PREPARATION.items():
        code = _launcher_code(launcher)
        assert RECOVERY_ENTRY in code and preparation in code and LAUNCHER_RECOVERY_CONDITION[launcher] in code, launcher
        assert code.index(RECOVERY_ENTRY) < code.index(preparation), f"{launcher}: recuperarea nu mai e înaintea pregătirii"
    module = (settings.PROJECT_ROOT / "emag_spend" / "update_recovery.py").read_text(encoding="utf-8")
    assert callable(update_recovery.main) and 'if __name__ == "__main__":\n    raise SystemExit(main())' in module
    for name in ("README.md", "SECURITY.md", "docs/INSTALARE.md"):
        assert RECOVERY_ORDER in _plain_document(name), name
    for name in ("SECURITY.md", "docs/INSTALARE.md"):
        assert "imediat după pregătire" in _plain_document(name), f"{name}: cazul fără .venv"
    assert f"python {RECOVERY_ENTRY}" in _plain_document("SECURITY.md"), "SECURITY numește ce rulează lansatoarele"


def test_contributing_names_the_recovery_entry_point_and_its_exit_codes_as_a_contract():
    """P1: punctul de intrare al lansatoarelor e contract între versiuni (nume, fără argumente, coduri de ieșire, semnul lansatorului
    repornit); CONTRIBUTING le numește pe toate, cu valorile din cod, iar lansatoarele se opresc exact la codul de eșec."""
    from emag_spend import update_recovery
    contributing = _plain_document("CONTRIBUTING.md")
    assert f"python {RECOVERY_ENTRY}" in contributing and "fără argumente" in contributing
    meanings = {update_recovery.EXIT_RECOVERY_OK: "nimic de făcut", update_recovery.EXIT_RECOVERY_FAILED: "recuperarea nu se poate face acum",
                update_recovery.EXIT_USAGE: "a primit argumente"}
    assert len(meanings) == 3, "două coduri de ieșire au aceeași valoare"
    missing = [f"{code} = {meaning}" for code, meaning in meanings.items() if f"{code} = {meaning}" not in contributing]
    assert not missing, f"CONTRIBUTING nu spune codurile: {missing}"
    assert RECOVERY_SIGN in contributing and all(RECOVERY_SIGN in _launcher_code(name) for name in LAUNCHER_PREPARATION)
    failed = update_recovery.EXIT_RECOVERY_FAILED
    assert f"if errorlevel {failed} if not errorlevel {failed + 1}" in _launcher_code("porneste.bat")
    for launcher in ("porneste.sh", "porneste.command"):
        assert f'[ "$COD" -eq {failed} ]' in _launcher_code(launcher), launcher


def test_the_documents_promise_only_the_user_files_on_paths_the_program_does_not_use(tmp_path):
    """V2-3 (D8): actualizarea scrie toate fișierele versiunii noi, deci un fișier al utilizatorului aflat pe o cale adusă de ea e
    înlocuit, iar unul de pe altă cale rămâne; locurile care spun ce rămâne au fraza decisă și limita ei."""
    from emag_spend.update_apply import apply_update
    from emag_spend.version import VERSION
    from tests.update_archive_support import install_program, newer_than, program_files, write_archive
    root = tmp_path / "program"
    install_program(root, VERSION)
    taken, free = "docs/notitele_mele.md", "notitele_mele.txt"  # nume inventate; primul îl aduce și versiunea nouă
    for name in (taken, free):
        (root / name).write_text("notițe inventate ale utilizatorului\n", encoding="utf-8")
    new = newer_than(VERSION)
    archive = write_archive(tmp_path / "arhiva.zip", new, program_files(new, extra={taken: b"pagina versiunii noi\n"}))
    apply_update(archive, root, new)
    assert (root / taken).read_bytes() == b"pagina versiunii noi\n", "fișierul de pe calea adusă de versiunea nouă nu e înlocuit"
    assert (root / free).read_text(encoding="utf-8") == "notițe inventate ale utilizatorului\n", "fișierul de pe altă cale s-a schimbat"
    places = {
        "SECURITY.md": _row(_document("SECURITY.md"), "- se șterg doar fișierele pe care lista versiunii vechi"),
        "docs/INSTALARE.md: Ce se păstrează": _document("docs/INSTALARE.md").split("### Ce se păstrează", 1)[1].split("\n### ", 1)[0],
        "index.html: Cum primesc versiunile noi?": re.search(r'<details id="faq-actualizari">.*?</details>', INDEX, re.S).group(0),
    }
    for place, text in places.items():
        flat = _flat(text)
        assert USER_FILE_PROMISE in flat, f"{place}: lipsește «{USER_FILE_PROMISE}»"
        assert USER_FILE_LIMIT in flat, f"{place}: lipsește limita «{USER_FILE_LIMIT}»"


def test_only_the_test_after_publishing_withdraws_a_release_and_the_weekly_run_only_signals():
    """V2-4: jobul „retrage” există doar în lansare.yml, după publicare; actualizare.yml (cu rularea lui săptămânală) are doar drept
    de citire și nu retrage nimic. Documentele care pomenesc rularea săptămânală spun că ea doar semnalează."""
    release, update_test = _workflow("lansare.yml"), _workflow("actualizare.yml")
    assert re.search(r"(?m)^  retrage:\n(?:    .*\n)*?    needs: \[lansare, actualizare\]", release), "jobul care retrage lansarea"
    assert re.search(r"(?m)^  schedule:\n    - cron: ", update_test), "rularea săptămânală a testului actualizării"
    assert "--prerelease" not in update_test and "contents: write" not in update_test, "actualizare.yml ar putea retrage singur"
    for name in ("SECURITY.md", "CONTRIBUTING.md", "docs/INSTALARE.md"):  # README, scurt, nu pomenește rularea săptămânală
        assert WEEKLY_RUN_ONLY_SIGNALS in _plain_document(name), name


def test_the_paid_definition_names_every_row_the_code_adds_up():
    """V2-5: plătit efectiv = produse păstrate + transport și taxe + retururi cu voucher sau sold + diferențe la restituiri
    (paid_totals); definiția din README și din pagină numește fiecare rând ca în raport, iar orice „să se adune exact” pomenește și
    retururile cu voucher."""
    from emag_spend import paid_totals
    year = paid_totals._Year(ordered_bani=1000, kept_bani=1, fees_bani=2, credit_bani=4, differences_bani=8)
    assert year.spent_bani == 1 + 2 + 4 + 8, "plătitul efectiv nu mai e suma celor patru părți"
    rows = [paid_totals.EXTRA_ROW_NAMES[key]
            for key in (paid_totals.EXTRA_FEES, paid_totals.EXTRA_CREDIT_RETURNS, paid_totals.EXTRA_REFUND_DIFFERENCES)]
    page = re.search(r"<dt>[^\n]*?Plătit efectiv</dt><dd>.*?</dd>", INDEX)
    assert page, "definiția „Plătit efectiv” lipsește din pagină"
    for place, definition in (("docs/CALCUL.md", _flat(_row(_document("docs/CALCUL.md"), "- **Plătit efectiv** ="))), ("index.html", _flat(page.group(0)))):
        assert "produsele păstrate" in definition, place
        missing = [row for row in rows if f"„{row}”" not in definition]
        assert not missing, f"{place}: definiția nu numește rândurile {missing}"
    for name in ("docs/CALCUL.md", "interfata/index.html"):
        parts = [part for part in re.split(r"(?<=[.;:])\s", _plain_document(name)) if "se adune exact" in part]
        assert parts and all("voucher" in part for part in parts), (name, parts)


def test_every_page_says_when_a_stopped_download_is_removed():
    """P7: un folder de descărcare lăsat de un program închis cât descărca se șterge la începutul unei descărcări sau la curățenie,
    dacă e neatins de STALE_DOWNLOAD_SECONDS; fiecare loc care spune ce rămâne în .actualizare spune și asta, cu durata din cod."""
    from emag_spend import update_download, update_recovery
    assert "update_recovery.remove_stale_downloads(base)" in inspect.getsource(update_download.download_folder)
    assert "remove_stale_downloads(downloads)" in inspect.getsource(update_recovery.clear_work)
    wait = f"după cel puțin {_duration(update_recovery.STALE_DOWNLOAD_SECONDS)}"
    for place, text in _update_folder_places().items():
        flat = _flat(text)
        assert STOPPED_DOWNLOAD in flat and wait in flat, f"{place}: lipsește «{STOPPED_DOWNLOAD}» … «{wait}»"


def test_security_names_every_update_folder_refused_as_a_link():
    """P8 (și N4, P5): .actualizare și descarcari/ se verifică înaintea oricărei descărcări, nou/, vechi/, copie/ înaintea oricărei
    mutări, iar revenirea nu scrie prin legături; rândul din SECURITY numește exact aceste foldere."""
    from emag_spend import update_download, update_recovery
    assert set(update_recovery.LINK_CHECKED_SUBDIRS) == {*update_recovery.WORK_SUBDIRS, update_recovery.DOWNLOADS_DIR_NAME}
    download = inspect.getsource(update_download.download_folder)
    assert download.index("_refuse_linked_folders(base)") < download.index("_new_download_folder(base)"), "refuzul a ajuns după mkdir"
    bullet = _flat(_row(_document("SECURITY.md"), "- legăturile simbolice și joncțiunile nu se urmează"))
    missing = [name for name in update_recovery.LINK_CHECKED_SUBDIRS if f"{name}/" not in bullet]
    assert not missing, f"SECURITY nu numește folderele verificate ca legături: {missing}"
    for needed in ("înainte de orice descărcare", "revenirea"):
        assert needed in bullet, needed


def test_the_documents_say_the_uv_archives_are_deleted_after_unpacking():
    """P9: după o dezarhivare reușită, instaleaza.bat și pregatire.sh șterg toate arhivele uv-* din .uv/descarcari; SECURITY și ghidul
    spun asta (arhiva cu versiunea în nume rămâne doar de la o pornire oprită înainte de dezarhivare)."""
    windows, unix = _launcher_code("instaleaza.bat"), _launcher_code("instalare/pregatire.sh")
    delete_windows, delete_unix = 'del /q "%CD%\\.uv\\descarcari\\uv-*"', 'rm -f "$ROOT/.uv/descarcari"/uv-* || true'
    assert f"if defined UV_DEZARHIVAT if not defined FAIL {delete_windows}" in windows, "ștergerea nu mai cere dezarhivarea reușită"
    assert windows.index("tar.exe -xf") < windows.index(delete_windows) and unix.index("tar -xzf") < unix.index(delete_unix)
    places = {"SECURITY.md": _row(_document("SECURITY.md"), "- **Prima pornire.**"),
              "docs/INSTALARE.md": _row(_document("docs/INSTALARE.md"), "| **uv** (instalatorul de Python")}
    for place, text in places.items():
        flat = _flat(text).casefold()  # fraza poate deschide propoziția
        assert UV_ARCHIVES_DELETED in flat and ".uv/descarcari/" in flat, place


def test_the_guide_and_the_page_explain_a_recovery_that_cannot_finish():
    """P1, P5, P6: o revenire care nu se termină (fișier blocat sau legătură pusă în drum) oprește pornirea; lansatorul spune
    LAUNCHER_RECOVERY_STOP, iar căile nerefăcute ajung în logs/. Rândul din ghid și cel din pagină spun mesajul, cauza și unde e urma."""
    from emag_spend import update_recovery
    for launcher in LAUNCHER_PREPARATION:
        assert LAUNCHER_RECOVERY_STOP in _launcher_code(launcher), launcher
    assert "nu s-a terminat" in update_recovery.MESSAGE_REVERT_INCOMPLETE
    assert "legătură spre alt loc" in inspect.getsource(update_recovery.finish_pending)
    assert "write_startup_log(Path(root) / LOGS_DIR_NAME, outcome)" in inspect.getsource(update_recovery.main)
    assert update_recovery.LOGS_DIR_NAME == settings.LOGS_DIR.name
    page = re.search(r'<tr><th scope="row" data-label="Mesaj"><code translate="no">Actualizarea a eșuat \(…\), iar revenirea.*?</tr>', INDEX)
    assert page, "pagina nu are rândul pentru revenirea care nu s-a terminat"
    rows = {"docs/INSTALARE.md": _flat(_row(_document("docs/INSTALARE.md"), "| „…revenirea la versiunea … nu s-a terminat”")),
            "index.html": _flat(page.group(0))}
    for place, row in rows.items():
        for needed in (LAUNCHER_RECOVERY_STOP, "legătură", f"{update_recovery.LOGS_DIR_NAME}/"):
            assert needed in row, f"{place}: lipsește «{needed}»"


def test_the_install_error_rows_send_the_user_to_the_file_named_in_the_message(tmp_path):
    """P4: când înlocuirea pică, mesajul numește fișierul din program (ținta lui os.replace), nu copia lui din .actualizare/nou;
    rândurile din ghid și din pagină trimit omul la fișierul numit în mesaj."""
    from emag_spend import update_apply
    root = tmp_path.resolve()
    error = PermissionError(13, "acces refuzat", str(root / ".actualizare" / "nou" / "README.md"), None, str(root / "README.md"))
    assert update_apply._describe(error, root) == "acces refuzat: README.md"
    rows = {"docs/INSTALARE.md": _row(_document("docs/INSTALARE.md"), "| „Actualizarea nu s-a putut instala (…)"),
            "index.html": _row(INDEX, '<tr><th scope="row" data-label="Mesaj"><code translate="no">Actualizarea nu s-a putut instala (…)')}
    for place, row in rows.items():
        assert FILE_NAMED_IN_THE_MESSAGE in _flat(row), place


def test_security_says_the_installed_version_is_read_under_the_lock():
    """P2: versiunea instalată se citește sub lacăt, după terminarea unei rulări oprite, ca două ferestre care actualizează deodată să
    nu poată pune una mai veche peste una mai nouă; SECURITY spune asta lângă regula „fără downgrade”."""
    from emag_spend import update_apply
    prepare = inspect.getsource(update_apply._prepare_and_install)
    order = [prepare.index(step) for step in ("finish_pending(root)", "_installed_version(root)", "is_newer(version, current)")]
    assert order == sorted(order), "versiunea instalată nu mai e citită după terminarea rulării oprite"
    apply = inspect.getsource(update_apply.apply_update)
    assert apply.index("with UpdateLock(") < apply.index("_prepare_and_install("), "versiunea nu mai e citită sub lacăt"
    assert "versiunea instalată se citește sub lacăt" in _plain_document("SECURITY.md")
