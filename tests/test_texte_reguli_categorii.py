"""Unde trimit textele pentru regulile proprii de categorii (decis 6 oct. 2026, N15): doar la config/categorii.personal.json.

Primește: toate textele pe care le vede utilizatorul (mesajele programului, config/avertismente.json, interfața și raportul,
README, INSTALARE, SECURITY, CONTRIBUTING, CHANGELOG, corpul lansării) și regulile actualizării din cod.
Verifică: niciun text nu spune să adaugi sau să editezi reguli în config/categorii.json (fișier al programului, înlocuit la
fiecare actualizare); promisiunile despre ce rămâne după o actualizare spun exact fraza N15; codul face ce spune fraza.
Ce NU face: nu rulează o actualizare (o face tests/test_update_apply.py) și nu deschide browserul.
"""

import html
import importlib
import json
import re
import sys

import pytest

from emag_spend import settings, update_archive
from tests.garda_support import PROJECT_ROOT, files_to_publish, interface_files, parse_source, program_sources, relative, string_constants

# Căile, din setări (nu scrise de mână): regulile publice ale programului și fișierul personal de lângă ele.
PUBLIC_RULES = relative(settings.CATEGORY_RULES_FILE)
PERSONAL_RULES = relative(settings.CATEGORY_RULES_FILE.parent / settings.PERSONAL_CATEGORY_RULES_FILE_NAME)
# Fraza decisă (N15), exact: promisiunea despre regulile de categorii la o actualizare.
PROMISE = f"regulile din {PERSONAL_RULES} rămân; modificările făcute direct în {PUBLIC_RULES} se pierd la actualizare"
# Promisiunea veche, vagă, care l-a făcut pe utilizator să-și piardă regulile scrise în fișierul public: nu are voie să revină.
VAGUE_PROMISE = re.compile(r"(?i)regulile tale(?: de categorii)? (?:rămân|sunt păstrate)")
# Verbele cu care un text îi spune omului să scrie reguli într-un fișier („adaugă reguli în…”, „le editezi în…”, „deschide … și…”).
EDIT_VERBS = r"adaug\w*|adăug\w*|edit\w*|deschi[dz]\w*|pui|pune(?:-le)?|scrii|scrie|modifici|schimbi"
# Cât de departe de verb poate sta calea în aceeași propoziție (în raport, între ele stă și un h('code', …) din dashboard.js).
VERB_TO_PATH_MAX_CHARS = 80
# Verb, apoi, fără punct, punct și virgulă sau rând nou între ele, calea PUBLICĂ: un punct din calea personală oprește potrivirea,
# deci „adaugă în config/categorii.personal.json, nu în config/categorii.json” nu e prins.
SENDS_TO_PUBLIC_FILE = re.compile(rf"(?i)\b(?:{EDIT_VERBS})\b[^.;!?\n]{{0,{VERB_TO_PATH_MAX_CHARS}}}?{re.escape(PUBLIC_RULES)}")
DOCUMENTS = ("README.md", "SECURITY.md", "CONTRIBUTING.md", "docs/INSTALARE.md", "docs/CALCUL.md", "docs/INTREBARI.md", "CHANGELOG.md")
SCRIPTS = PROJECT_ROOT / ".github" / "scripts"


def _plain(text: str) -> str:
    """Textul fără marcaje: etichete HTML, entități, `cod` și **îngroșat** din Markdown; spațiile (și NBSP) devin unul singur."""
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace(chr(0xA0), " ")
    return re.sub(r"\s+", " ", text.replace("`", "").replace("**", ""))


def _json_strings(value) -> list[str]:
    """Toate textele dintr-o valoare JSON (dicționare și liste parcurse în adâncime)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _json_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _json_strings(item)]
    return []


def _load_script(name: str):
    """Scriptul .github/scripts/<name>.py ca modul (folderul lui intră în sys.path, ca la rularea din lansare.yml)."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


def _release_body() -> str:
    """Corpul lansării de acum, compus ca în lansare.yml, din secțiunea versiunii din CHANGELOG (amprenta inventată)."""
    from emag_spend.version import VERSION
    notes = _load_script("changelog_section").changelog_section((PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), VERSION)
    return _load_script("release_body").release_body(VERSION, notes, "proprietar-inventat/depozit", f"{'ab' * 32}  arhiva.zip\n")


def user_texts() -> dict[str, str]:
    """{sursă: text} pentru tot ce vede utilizatorul: literalele programului (fără docstring-uri), avertismentele, interfața, documentele."""
    texts = {}
    for path in program_sources():
        literals = [value for _, value, is_docstring in string_constants(parse_source(path)) if not is_docstring]
        texts[relative(path)] = "\n".join(literals)
    warning_texts = json.loads((PROJECT_ROOT / "config" / "avertismente.json").read_text(encoding="utf-8"))
    texts["config/avertismente.json"] = "\n".join(_json_strings(warning_texts))
    for path in interface_files(".html", ".js"):
        texts[relative(path)] = path.read_text(encoding="utf-8")
    for name in DOCUMENTS:
        texts[name] = (PROJECT_ROOT / name).read_text(encoding="utf-8")
    texts["corpul lansării (.github/scripts/release_body.py)"] = _release_body()
    return texts


def test_no_text_tells_the_user_to_write_rules_in_the_file_that_updates_replace():
    """N15: „adaugă reguli în…”, „le editezi în…”, „deschide … și adaugă” trimit doar la fișierul personal, niciodată la cel public."""
    found = []
    for source, text in user_texts().items():
        for candidate in (text, _plain(text)):
            found.extend(f"{source}: …{match.group(0)}…" for match in SENDS_TO_PUBLIC_FILE.finditer(candidate))
    assert not found, sorted(set(found))


def test_no_text_makes_the_old_vague_promise_about_the_category_rules():
    """„regulile tale (de categorii) rămân” a promis și regulile scrise în fișierul public; promisiunea spune acum ce fișier rămâne."""
    found = [f"{source}: {match.group(0)}" for source, text in user_texts().items() for match in VAGUE_PROMISE.finditer(_plain(text))]
    assert not found, found


def _between(text: str, start: str, end: str) -> str:
    """Bucata din `text` de la prima apariție a lui `start` până la prima apariție a lui `end` de după el (pytest.fail dacă lipsesc)."""
    if start not in text:
        pytest.fail(f"nu găsesc {start!r}")
    rest = text[text.index(start):]
    return rest[:rest.index(end, len(start))] if end in rest[len(start):] else rest


def _promise_places() -> dict[str, str]:
    """Locurile care spun ce rămâne după o actualizare sau unde pui regulile tale: textul fiecăruia, fără marcaje."""
    from emag_spend.version import VERSION
    root = PROJECT_ROOT
    index = (root / "interfata" / "index.html").read_text(encoding="utf-8")
    app = (root / "interfata" / "aplicatie.html").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "INSTALARE.md").read_text(encoding="utf-8")
    questions = (root / "docs" / "INTREBARI.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    places = {
        "index.html: Cum primesc versiunile noi?": _between(index, '<details id="faq-actualizari">', "</details>"),
        "index.html: Cum adaug categorii?": _between(index, '<details id="faq-categorii">', "</details>"),
        "index.html: Actualizează din terminal": _between(index, "<h3>Actualizează din terminal</h3>", "</div>"),
        "aplicatie.html: lângă „Actualizează acum”": _between(app, '<p class="hint" id="update-about">', "</p>"),
        "README.md: Actualizări": _between(readme, "## Actualizări", "\n## "),
        "docs/INTREBARI.md: Cum actualizez?": _between(questions, "<summary><strong>Cum actualizez?</strong></summary>", "</details>"),
        "docs/INTREBARI.md: cum adaug o categorie": _between(questions, "cum adaug o categorie?</strong></summary>", "</details>"),
        "docs/INSTALARE.md: Ce se păstrează": _between(guide, "### Ce se păstrează", "\n### "),
        f"CHANGELOG.md: {VERSION}": _between(changelog, f"## {VERSION} — ", "\n## "),
        "corpul lansării": _release_body(),
    }
    return {place: _plain(text) for place, text in places.items()}


@pytest.mark.parametrize("place", sorted(_promise_places()))
def test_every_promise_about_what_an_update_keeps_says_the_decided_sentence(place):
    """N15: fiecare loc care spune ce rămâne la actualizare (sau unde îți pui regulile) are exact fraza decisă."""
    assert PROMISE in _promise_places()[place], f"{place}: lipsește «{PROMISE}»"


def test_the_promise_is_what_the_update_really_does():
    """Fraza N15 e adevărată: fișierul public e al programului (urcă în lansare și nu e protejat, deci actualizarea îl înlocuiește),
    iar cel personal e protejat de actualizare și nu urcă în git (nu ajunge în nicio lansare)."""
    published = {relative(path) for path in files_to_publish()}
    assert PUBLIC_RULES in published and not update_archive.is_protected(PUBLIC_RULES), PUBLIC_RULES
    assert PERSONAL_RULES not in published and update_archive.is_protected(PERSONAL_RULES), PERSONAL_RULES
    assert PERSONAL_RULES in update_archive.PROTECTED_FILES


@pytest.mark.parametrize("text", [
    "3 produse necategorizate (adaugă reguli în config/categorii.json)",
    "Le editezi în <code class=\"nb\" translate=\"no\">config/categorii.json</code> și refaci raportul.",
    "Deschide config/categorii.json și adaugă o intrare.",
    "'Regulile de categorii se pot edita în ', h('code', { translate: 'no' }, 'config/categorii.json'), '.'",
    "Pune-le în `config/categorii.json`.",
])
def test_the_detector_catches_a_text_that_sends_the_user_to_the_public_file(text):
    """Capcană: fiecare formulare care a trimis omul la fișierul public e prinsă (și în HTML sau în sursa raportului)."""
    assert SENDS_TO_PUBLIC_FILE.search(text) or SENDS_TO_PUBLIC_FILE.search(_plain(text)), text


@pytest.mark.parametrize("text", [
    f"3 produse necategorizate (adaugă reguli în {PERSONAL_RULES})",
    f"Pune-le în {PERSONAL_RULES}, nu în {PUBLIC_RULES}.",
    f"Regulile generice stau în {PUBLIC_RULES}.",
    PROMISE,
    f"Adaugă reguli. Programul citește și {PUBLIC_RULES}.",
])
def test_the_detector_leaves_alone_texts_that_send_the_user_to_the_personal_file(text):
    """Fals pozitiv: trimiterea la fișierul personal, o descriere a fișierului public și fraza N15 nu sunt prinse."""
    assert not SENDS_TO_PUBLIC_FILE.search(text) and not SENDS_TO_PUBLIC_FILE.search(_plain(text)), text
