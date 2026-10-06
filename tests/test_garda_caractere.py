"""Garda de caractere invizibile (decis 6 oct. 2026, N16): în ce urcă în git nu există caractere care ascund sau reordonează textul.

Primește: tot ce ar ajunge în repo (tests.garda_support.files_to_publish: codul programului, testele, interfața, documentele,
configurările, lansatoarele), fără imagini și fonturi. Verifică: UTF-8 valid și niciun caracter de control (în afară de TAB, LF, CR),
de format (bidi U+202A–U+202E și U+2066–U+2069, marcajele de direcție, spațiile de lățime zero, BOM, cratima moale, etichetele
U+E0000…), separator Unicode de rând sau de paragraf, spațiu exotic, zonă privată, cod nealocat, umplutor Hangul sau selector de variantă.
De ce: un caracter bidi face codul să arate altfel decât rulează („Trojan Source”), iar unealta de scriere a agenților transformă
secvențele backslash-u în caracterul real. Un caracter necesar într-un test se scrie ca secvență (backslash, u, cod) sau cu chr(0x202E).
Fiecare detector e probat pe text-capcană. Ce NU face: nu verifică textul generat la rulare și nu judecă diacriticele sau emoji-urile.
"""

import unicodedata
from pathlib import Path

import pytest

from tests.garda_support import PROJECT_ROOT, files_to_publish, relative

# Fișiere fără text de verificat: imagini, fonturi, arhive.
BINARY_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".woff", ".woff2", ".zip", ".pdf"})
# Singurele caractere de control permise: TAB, rând nou și întoarcerea de car (fișierele .bat au CRLF).
ALLOWED_CONTROLS = frozenset({"\t", "\n", "\r"})
# Categoriile Unicode refuzate: control (Cc), format (Cf: bidi, lățime zero, BOM, cratimă moale, etichete), separatori de rând (Zl)
# și de paragraf (Zp), zonă privată (Co), surogate (Cs) și coduri nealocate (Cn).
FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
# Spațiile permise: cel obișnuit și NBSP (U+00A0). NBSP e un spațiu VIZIBIL, nu ascunde și nu reordonează nimic; dashboard.js și
# site-format.js îl pun între cifre și „lei”. Celelalte spații (subțiri, de lățime fixă, ideografic) nu au ce căuta în surse.
ALLOWED_SPACES = frozenset({" ", chr(0x00A0)})
SPACE_CATEGORY = "Zs"
# Caractere din alte categorii care se văd ca nimic: umplutorii Hangul (folosiți ca „identificatori invizibili”), „combining
# grapheme joiner” și selectorii de variantă (pot purta date ascunse lipite de o literă).
INVISIBLE_CODEPOINTS = frozenset({0x115F, 0x1160, 0x3164, 0xFFA0, 0x034F, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)})
# BOM-ul e permis DOAR ca prim caracter al unui script PowerShell: Windows PowerShell 5.1 citește un .ps1 UTF-8 fără BOM ca ANSI.
BOM = chr(0xFEFF)
BOM_FIRST_SUFFIXES = frozenset({".ps1"})
# Câte apariții se arată per fișier: destul ca să se vadă tiparul, fără un mesaj de mii de rânduri.
MAX_SHOWN_PER_FILE = 20
MIN_REASON_LENGTH = 30
# EXCEPȚII (cale, cod) -> motiv: date de test „ostile”, scrise ca atare în runda anterioară, în fișiere care nu sunt ale acestei gărzi.
# Fiecare trebuie rescrisă ca secvență (backslash-u) sau cu chr(...) și scoasă de aici; testul de necesitate de mai jos pică imediat
# ce una nu mai apare, ca lista să nu rămână deschisă.
KNOWN_OCCURRENCES = {
    ("tests/dashboard_samples.py", 0x202E):
        "nume de categorie ostil (RIGHT-TO-LEFT OVERRIDE): raportul trebuie să-l arate ca text, fără să întoarcă rândul",
    ("tests/dashboard_samples.py", 0x200B):
        "nume de categorie ostil (ZERO WIDTH SPACE), lângă cel de mai sus, pentru aceeași verificare a raportului",
    ("tests/test_order_links.py", 0x200B):
        "număr de comandă cu ZERO WIDTH SPACE la final: nu are voie să devină link spre eMAG",
    ("tests/test_demo_site_data.py", 0x2028):
        "LINE SEPARATOR într-un nume: demo-data.js generat trebuie să-l scrie ca secvență, nu ca atare",
    ("tests/test_demo_site_data.py", 0x2029):
        "PARAGRAPH SEPARATOR într-un nume: demo-data.js generat trebuie să-l scrie ca secvență, nu ca atare",
    ("tests/test_app_runs.py", 0xFEFF):
        "analiza.json care începe cu BOM: lista rulărilor trebuie să-l refuze ca JSON stricat",
}


def forbidden_reason(char: str) -> str | None:
    """De ce e refuzat `char` (în cuvinte), sau None dacă e permis. Nu știe de BOM-ul permis la .ps1 (îl tratează apelantul)."""
    if char in ALLOWED_CONTROLS or char in ALLOWED_SPACES:
        return None
    category = unicodedata.category(char)
    if category in FORBIDDEN_CATEGORIES:
        return f"caracter de categoria {category}"
    if category == SPACE_CATEGORY:
        return "spațiu exotic"
    if ord(char) in INVISIBLE_CODEPOINTS:
        return "caracter care se vede ca nimic"
    return None


def hidden_character_problems(text: str, label: str, suffix: str, allowed: frozenset[int] = frozenset()) -> list[str]:
    """Aparițiile caracterelor refuzate din `text`, cu rândul, coloana, codul și numele lor; `allowed` = coduri iertate în acest fișier.

    Un BOM ca prim caracter e iertat doar pentru extensiile din BOM_FIRST_SUFFIXES. Arată cel mult MAX_SHOWN_PER_FILE apariții.
    """
    problems = []
    line, column = 1, 0
    for index, char in enumerate(text):
        if char == "\n":
            line, column = line + 1, 0
            continue
        column += 1
        reason = forbidden_reason(char)
        if reason is None or ord(char) in allowed or (char == BOM and index == 0 and suffix in BOM_FIRST_SUFFIXES):
            continue
        name = unicodedata.name(char, "fără nume")
        problems.append(f"{label}:{line}:{column}: U+{ord(char):04X} {name} ({reason}): scrie-l ca secvență sau cu chr(0x{ord(char):X})")
    if len(problems) > MAX_SHOWN_PER_FILE:
        problems = problems[:MAX_SHOWN_PER_FILE] + [f"{label}: încă {len(problems) - MAX_SHOWN_PER_FILE} apariții"]
    return problems


def file_problems(path: Path) -> list[str]:
    """Încălcările unui fișier publicat: UTF-8 invalid sau caractere refuzate (cu excepțiile din KNOWN_OCCURRENCES ale lui)."""
    label = relative(path)
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        return [f"{label}: nu e UTF-8 valid (octetul {error.start}): garda nu poate verifica ce nu poate citi"]
    allowed = frozenset(code for (name, code) in KNOWN_OCCURRENCES if name == label)
    return hidden_character_problems(text, label, path.suffix.lower(), allowed)


def _text_files() -> list[Path]:
    """Fișierele publicate care au text: tot în afară de BINARY_SUFFIXES."""
    return [path for path in files_to_publish() if path.suffix.lower() not in BINARY_SUFFIXES]


# ---------- pe fișierele reale ----------

@pytest.mark.parametrize("path", _text_files(), ids=relative)
def test_published_text_file_has_no_hidden_characters(path):
    """Niciun fișier care urcă în git nu are caractere de control, bidi, BOM, lățime zero sau alte caractere invizibile."""
    problems = file_problems(path)
    assert not problems, "\n".join(problems)


def test_the_scan_covers_the_program_the_tests_and_the_interface():
    """Lista verificată conține chiar sursele programului, testele, interfața și lansatoarele (altfel garda n-ar dovedi nimic)."""
    scanned = {relative(path) for path in _text_files()}
    for needed in ("ruleaza.py", "emag_spend/update_http.py", "tests/conftest.py", "tests/test_garda_caractere.py",
                   "interfata/assets/app-update.js", "interfata/aplicatie.html", "porneste.bat"):
        assert needed in scanned, f"{needed} nu e verificat de garda de caractere"


def test_known_occurrences_are_justified_and_still_needed():
    """Fiecare excepție are motiv scris și caracterul ei încă apare în fișier; când apariția dispare, excepția se scoate."""
    for (name, code), reason in KNOWN_OCCURRENCES.items():
        assert len(reason.strip()) >= MIN_REASON_LENGTH, f"excepția {name}/U+{code:04X} nu are motiv scris"
        path = PROJECT_ROOT / name
        assert path.is_file(), f"excepția {name}: fișierul nu mai există; scoate-o"
        assert chr(code) in path.read_text(encoding="utf-8"), f"{name} nu mai conține U+{code:04X}: scoate excepția din KNOWN_OCCURRENCES"


# ---------- detectorul văzut picând pe text-capcană ----------

@pytest.mark.parametrize("code", [
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x061C,
    0x200B, 0x200C, 0x200D, 0x2060, 0x2062, 0xFEFF, 0x00AD, 0x180E, 0xE0041, 0xFFF9,
    0x0000, 0x0007, 0x000B, 0x000C, 0x001B, 0x007F, 0x0085, 0x009B,
    0x2028, 0x2029, 0x2002, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000, 0x1680,
    0xE000, 0xF8FF, 0xFFFE, 0x0378,
    0x115F, 0x1160, 0x3164, 0xFFA0, 0x034F, 0xFE00, 0xFE0F, 0xE0100,
])
def test_the_detector_catches_every_kind_of_hidden_character(code):
    """Capcană: bidi, marcaje de direcție, lățime zero, BOM în mijloc, cratimă moale, etichete, control C0/C1, separatori de rând,
    spații exotice, zonă privată, cod nealocat, umplutori Hangul și selectori de variantă: fiecare e prins, cu rândul și coloana."""
    text = "x = 1\nnume = 'ab" + chr(code) + "c'\n"
    problems = hidden_character_problems(text, "capcana.py", ".py")
    assert len(problems) == 1 and problems[0].startswith(f"capcana.py:2:11: U+{code:04X}"), problems


def test_the_detector_allows_ordinary_text():
    """Fals pozitiv: diacritice, ghilimele românești, emoji fără selector, NBSP, TAB și CRLF nu sunt caractere ascunse."""
    text = "\tșțăîâ ȘȚĂÎÂ „citat” – … € 😀 1" + chr(0x00A0) + "234 lei\r\nrând nou\n"
    assert hidden_character_problems(text, "curat.py", ".py") == []


def test_a_bom_is_allowed_only_at_the_start_of_a_powershell_script():
    """BOM la început: permis doar în .ps1 (Windows PowerShell 5.1 îl cere); într-un .py sau în mijlocul unui .ps1 e refuzat."""
    assert hidden_character_problems(BOM + "Write-Host 'x'\n", "a.ps1", ".ps1") == []
    assert hidden_character_problems(BOM + "print('x')\n", "a.py", ".py")
    assert hidden_character_problems("Write-Host 'x'" + BOM + "\n", "a.ps1", ".ps1")


def test_an_allowed_code_is_forgiven_only_where_it_is_listed():
    """Excepțiile sunt pe (fișier, cod): un cod iertat într-un fișier nu iartă un alt cod din același fișier."""
    text = "a = '" + chr(0x202E) + chr(0x200B) + "'\n"
    problems = hidden_character_problems(text, "x.py", ".py", allowed=frozenset({0x202E}))
    assert len(problems) == 1 and "U+200B" in problems[0]


def test_exceptions_apply_only_to_their_own_file(tmp_path):
    """Un cod din KNOWN_OCCURRENCES e iertat doar în fișierul lui: același caracter în orice alt fișier e raportat."""
    code = next(iter(KNOWN_OCCURRENCES))[1]
    path = tmp_path / "alt_fisier.py"
    path.write_text("nume = 'a" + chr(code) + "b'\n", encoding="utf-8")
    problems = file_problems(path)
    assert len(problems) == 1 and f"U+{code:04X}" in problems[0], problems


def test_invalid_utf8_is_reported(tmp_path):
    """Un fișier care nu e UTF-8 valid e raportat (garda nu-l poate citi, deci nu-l poate declara curat)."""
    path = tmp_path / "stricat.txt"
    path.write_bytes(b"ok \xff\xfe nu")
    problems = file_problems(path)
    assert len(problems) == 1 and "nu e UTF-8 valid" in problems[0]


def test_long_reports_are_capped():
    """Un fișier plin de caractere ascunse dă cel mult MAX_SHOWN_PER_FILE rânduri, plus unul cu restul."""
    problems = hidden_character_problems(chr(0x200B) * (MAX_SHOWN_PER_FILE + 5), "plin.txt", ".txt")
    assert len(problems) == MAX_SHOWN_PER_FILE + 1 and problems[-1].endswith("încă 5 apariții")
