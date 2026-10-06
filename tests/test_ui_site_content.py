"""Textele site-ului despre cele trei funcții noi (linkuri, avertismente cu detalii, prețuri) și despre aplicația locală, verificate față de cod (fără browser).

Primește: interfata/index.html, assets/site*.js, fișierele CSV ale programului (coloanele lor), porneste.bat, ruleaza.py și config/. Verifică: fiecare funcție e
descrisă în „Cum se calculează” și în întrebările frecvente, coloanele CSV scrise în pagină sunt EXACT cele din cod, formularea despre rețea e cea exactă, apelul
„Deschide aplicația” explică pasul (dublu-click pe porneste.bat) fără un link direct spre aplicatie.html (din file:// n-ar merge), afirmațiile despre lansator
se potrivesc cu fișierul, iar actualizările (cererea spre GitHub, întrebarea frecventă, comenzile) sunt spuse peste tot unde trebuie. NU deschide browserul.
"""

import html
import re

from emag_spend import csv_export, price_history_csv, settings

ROOT = settings.PROJECT_ROOT
INDEX = (ROOT / "interfata" / "index.html").read_text(encoding="utf-8")
PAGE_TEXT = html.unescape(re.sub(r"<[^>]+>", "", INDEX))
FAQ_IDS_ADDED = ("faq-aplicatie", "faq-server-local", "faq-link-comanda", "faq-avertismente-grupe", "faq-preturi", "faq-fara-retururi",
                 "faq-actualizari")
# Formularea exactă a deciziei din brief: ce iese din calculator când apeși pe un link spre o comandă.
NETWORK_SENTENCE = "Linkurile către comenzi se deschid pe emag.ro doar când apeși pe ele, în browserul tău"


def section(section_id: str) -> str:
    """HTML-ul secțiunii cu id-ul dat (de la <section id=…> până la </section>)."""
    match = re.search(rf'<section[^>]*\bid="{section_id}".*?</section>', INDEX, re.S)
    assert match, section_id
    return match.group(0)


def text_of(fragment: str) -> str:
    """Textul vizibil dintr-un fragment HTML, cu spațiile nedespărțitoare făcute spații obișnuite."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace(chr(0xA0), " ")


def identifier_codes(row_html: str) -> set[str]:
    """Textele <code> dintr-un rând care sunt identificatori de coloană (litere mici și _)."""
    return {code for code in re.findall(r'<code class="nb" translate="no">([^<]+)</code>', row_html) if re.fullmatch(r"[a-z_]+", code)}


def table_row(file_name: str) -> str:
    """Rândul din tabelul de fișiere al paginii care descrie `file_name`."""
    match = re.search(rf'<tr><th scope="row" data-label="Fișier"><code class="nb" translate="no">{re.escape(file_name)}</code></th>.*?</tr>', INDEX, re.S)
    assert match, file_name
    return match.group(0)


# ---------- cele trei funcții ----------

def test_how_it_is_calculated_describes_links_warnings_and_price_history():
    text = text_of(section("calcul"))
    for needed in ("Link către comandă", "Avertismente cu detalii", "Prețuri la același produs", "3–15 cifre", "dacă afectează totalurile",
                   "config/avertismente.json", "config/culori.json", "capacitatea sau dimensiunea", "nu dacă oferta a fost bună sau proastă", "istoric_preturi.csv"):
        assert needed in text, needed


def test_the_network_claim_is_the_exact_one_and_the_old_ambiguous_one_is_gone():
    assert text_of(INDEX).count(NETWORK_SENTENCE) >= 3, "în calcul, în confidențialitate și în întrebări"
    assert "Interfața aceasta nu face nicio cerere de rețea" not in PAGE_TEXT, "„Interfața” nu mai e doar site-ul: aplicația locală vorbește cu un server de pe calculator"
    assert "Acest site explicativ nu face nicio cerere de rețea" in PAGE_TEXT


def test_every_new_function_has_a_faq_entry_with_a_direct_link():
    for faq_id in FAQ_IDS_ADDED:
        assert f'<details id="{faq_id}">' in INDEX, faq_id
    assert 'href="#faq-aplicatie"' in INDEX


def test_price_history_never_promises_a_loss_or_a_gain():
    text = PAGE_TEXT.lower()
    scope = " ".join(text_of(section(name)).lower() for name in ("calcul", "intrebari"))
    for forbidden in ("ai pierdut", "ai câștigat", "economisit"):
        assert forbidden not in scope, forbidden
    assert "nu dacă oferta a fost bună sau proastă" in text and "promoții" in text and "înainte de vouchere" in text


def test_the_texts_edited_in_config_files_point_to_files_that_exist():
    for name in ("avertismente.json", "culori.json", "categorii.json"):
        assert (ROOT / "config" / name).is_file(), name
        assert f"config/{name}" in PAGE_TEXT, name


# ---------- coloanele CSV: exact cele din cod ----------

def test_csv_columns_described_on_the_page_are_exactly_the_ones_the_code_writes():
    assert identifier_codes(table_row("produse.csv")) == set(csv_export._HEADER)
    assert identifier_codes(table_row("istoric_preturi.csv")) == set(price_history_csv._HEADER)


def test_page_explains_the_csv_formula_protection_and_the_colour_column():
    csv_text = text_of(table_row("produse.csv")) + text_of(table_row("istoric_preturi.csv"))
    assert "apostrof" in csv_text and "formulă" in csv_text
    assert "variante_culoare" in csv_text and "mai multe culori" in csv_text and "nume_in_comanda" in csv_text


def test_run_info_row_says_the_paths_are_relative_to_the_project_folder():
    row = text_of(re.search(r'<tr><th scope="row" data-label="Fișier"><code class="nb" translate="no">run_info.json</code>.*?</tr>', INDEX, re.S).group(0))
    assert "relativ la folderul proiectului" in row and "numele contului tău Windows" in row


# ---------- accounts without returns ----------

def test_page_covers_accounts_without_returns():
    text = PAGE_TEXT
    assert "Ce se întâmplă dacă nu am niciun retur?" in text and "retururi.json" in text and "listă goală" in text


# ---------- aplicația locală ----------

def test_the_app_call_in_the_hero_and_in_how_it_works_explains_the_step_without_a_direct_link():
    hero = section("start")
    assert re.search(r'<a class="btn btn--primary btn--lg" href="#aplicatie">Deschide aplicația</a>', hero)
    assert "porneste.bat" in text_of(hero)
    how = section("cum-functioneaza")
    assert 'id="aplicatie"' in how and "dublu-click pe porneste.bat" in text_of(how)
    assert "Pornește analiza" in text_of(how) and "Încearcă cu date inventate" in text_of(how) and "Rulări anterioare" in text_of(how)
    assert 'href="aplicatie.html"' not in INDEX, "din file:// un link direct n-ar găsi serverul: pagina explică pasul, nu trimite acolo"
    assert "de ce nu e un link" in text_of(how).lower()


def test_old_sentence_that_the_interface_cannot_start_the_program_is_corrected():
    assert "Un site static nu poate porni programul în locul tău." not in PAGE_TEXT
    assert "aplicația locală, pornită cu porneste.bat, o poate face" in PAGE_TEXT


def test_the_viewer_section_points_to_the_app_for_the_easy_way():
    text = text_of(section("incarca"))
    assert "Pentru cine are deja un analiza.json" in text and "aplicația locală" in text and "porneste.bat" in text


def test_what_the_page_says_about_the_launcher_matches_the_launcher():
    launcher = (ROOT / "porneste.bat").read_text(encoding="utf-8")
    # Fără argumente pornește aplicația: direct (ruleaza.py --aplicatie) sau printr-o variabilă cu implicitul --aplicatie (din 5 oct. 2026,
    # rândul lui Python e unul singur, ultimul din fișier, ca o actualizare să nu-l poată strica).
    default = re.search(r'set "([A-Z_]+)=--aplicatie"', launcher)
    starts_app = "ruleaza.py --aplicatie" in launcher or (default is not None and f"ruleaza.py %{default.group(1)}%" in launcher)
    assert "instaleaza.bat" in launcher and starts_app
    assert "apelează instaleaza.bat" in PAGE_TEXT and "ruleaza.py --aplicatie" in PAGE_TEXT
    script = (ROOT / "ruleaza.py").read_text(encoding="utf-8")
    assert '"--aplicatie"' in script and '"--fara-browser"' in script
    assert "--fara-browser" in PAGE_TEXT


def test_the_server_description_keeps_to_the_decided_protections():
    faq = text_of(re.search(r'<details id="faq-server-local">.*?</details>', INDEX, re.S).group(0))
    for needed in ("127.0.0.1", "port ales de sistem", "cheie aleatorie de sesiune", "Host", "Origin", "listă fixă", "Se oprește singur după o perioadă fără cereri",
                   "Serverul nu trimite nimic spre exterior"):
        assert needed in faq, needed
    assert ".profil_browser/" in faq and "iesiri/" in faq and "logs/" in faq
    # Excepția spusă deschis (5 oct. 2026): procesul aplicației întreabă GitHub de versiunea nouă, dezactivabil.
    for needed in ("api.github.com", "EMAG_UPDATE_CHECK=0", "Actualizează acum"):
        assert needed in faq, needed


# ---------- actualizările (decis 5 oct. 2026) ----------

def test_every_list_of_what_leaves_the_computer_names_the_update_check():
    """Oriunde pagina spune ce pleacă de pe calculator, pomenește și cererea spre GitHub (altfel ar promite „doar emag.ro”)."""
    description = next(m.group(1) for m in re.finditer(r'<meta name="description" content="([^"]*)"', INDEX))
    places = {
        "descrierea paginii": description,
        "Ce pleacă din calculator": text_of(re.search(r'<div class="never">.*?</div>', INDEX, re.S).group(0)),
        "Funcționează pentru toți": text_of(section("pentru-cine")),
        "Datele mele pleacă undeva?": text_of(re.search(r'<details id="faq-date">.*?</details>', INDEX, re.S).group(0)),
        "Ce face aplicația locală?": text_of(re.search(r'<details id="faq-aplicatie">.*?</details>', INDEX, re.S).group(0)),
    }
    for place, text in places.items():
        assert "versiune nouă" in text or "GitHub" in text, place
    never = places["Ce pleacă din calculator"]
    assert "api.github.com" in never and "adresa ta IP" in never and "EMAG_UPDATE_CHECK=0" in never and "SHA-256" in never


def test_the_update_faq_says_what_happens_what_stays_and_the_limit():
    """„Cum primesc versiunile noi?”: cererea, ce vede GitHub, butonul, amprenta, ce rămâne, revenirea, alternativele și limita onestă."""
    faq = text_of(re.search(r'<details id="faq-actualizari">.*?</details>', INDEX, re.S).group(0))
    for needed in ("Cum primesc versiunile noi?", "api.github.com", "adresa ta IP", "versiunea programului", "Actualizează acum",
                   "Nimic nu se instalează fără să apeși tu", "cât rulează o analiză", "SHA-256", "pune la loc versiunea veche",
                   "următoarea pornire", "--actualizeaza", "git pull", "EMAG_UPDATE_CHECK=0", "nu de un cont GitHub compromis"):
        assert needed in faq, needed
    assert 'href="#faq-actualizari"' in INDEX, "lista „Ce pleacă din calculator” trimite la întrebare"


def test_the_update_commands_have_their_own_copyable_lines():
    """Comenzile --versiune și --actualizeaza au rândul lor în „Comenzi”, cu buton de copiere, iar programul chiar le are."""
    commands = section("comenzi")
    for code_id, flag in (("c-versiune", "--versiune"), ("c-actualizeaza", "--actualizeaza")):
        line = re.search(rf'<code id="{code_id}" translate="no">(.*?)</code>', commands, re.S)
        assert line and flag in text_of(line.group(1)), code_id
        assert f'data-copy-from="#{code_id}"' in commands, code_id
    script = (ROOT / "ruleaza.py").read_text(encoding="utf-8")
    assert '"--versiune"' in script and '"--actualizeaza"' in script
    text = text_of(commands)
    assert re.search(r"„Cheltuieli eMAG [0-9]+\.[0-9]+\.[0-9]+”", text), "exemplul ieșirii lui --versiune"
    assert 'PROGRAM_NAME = "Cheltuieli eMAG"' in script and 'print(f"{PROGRAM_NAME} {VERSION}")' in script, "ieșirea reală a lui --versiune"
    assert "DA" in text and "git pull" in text and "revine singur la versiunea veche" in text


def test_the_simulator_does_not_pluralize_a_count_it_prints_next_to_a_number():
    source = (ROOT / "interfata" / "assets" / "site-simulator.js").read_text(encoding="utf-8")
    assert "' produse peste prag" not in source and "Produse peste prag: " in source


# ---------- igienă a surselor interfeței ----------

# Literele ș și ț cu sedilă (U+015F, U+0163 și majusculele) sunt greșite în română: corecte sunt cele cu virgulă. Generate din cod, ca testul să nu le conțină.
CEDILLA_LETTERS = {chr(0x15E), chr(0x15F), chr(0x162), chr(0x163)}


def test_interface_sources_have_no_invisible_characters_and_no_cedilla_letters():
    """Nicio sursă din interfata/ sau templates/ nu conține caractere invizibile (combinate, de formatare, de control) sau litere cu sedilă.

    Secvențele Unicode din expresii regulate se scriu cu escape (backslash + u), nu ca semne reale: un semn real e invizibil în editor și se strică la copiere.
    """
    import unicodedata
    offenders = []
    for folder in ("interfata", "templates"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix.lower() not in {".js", ".css", ".html"} or path.name == "demo-data.js":
                continue  # demo-data.js e generat din Python (are propriul test de prospețime)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                bad = {hex(ord(c)) for c in line if unicodedata.category(c) in ("Mn", "Cf", "Cc") and c != "\t"} | {hex(ord(c)) for c in line if c in CEDILLA_LETTERS}
                if bad:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {sorted(bad)}")
    assert not offenders, offenders
