"""Generatorul fixturilor de paritate Python <-> JavaScript pentru extensia Chrome (nu e test pytest: numele nu începe cu test_).

Primește: calea unui folder, ca argument. Scrie acolo nouă fișiere JSON (setari, unicode, primitive, regex, regex_aleatoare, difflib, html,
parsere, analiza): pentru aceleași intrări, ieșirile EXACTE ale programului Python, care rămâne referința (decis 13.10.2026, E2); html.json
înregistrează și versiunile reale lxml/libxml2 (runtime și compilare), pentru profilul tokenizerului folosit la generare.
Testele din extensie/tests/paritate/ cer de la portul JavaScript aceleași ieșiri, la ban. Pornit de extensie/scripts/ruleaza_python.mjs
cu PYTHONHASHSEED=0; rulat de două ori, cu semințe diferite, scrie aceiași octeți (dovadă: ieșirile nu depind de ordinea seturilor).
Ce NU face: nu citește config/categorii.personal.json (titlurile lui Robert nu ies din calculator), nu face rețea, nu scrie în afara folderului primit.
"""

import dataclasses
import difflib
import json
import os
import random
import re
import struct
import sys
import unicodedata
import warnings
from pathlib import Path

# Extensia nu are variabile de mediu: fixturile poartă valorile IMPLICITE ale setărilor, nu ce are cineva în mediu (se face înainte de importuri).
for _variable in ("EMAG_FETCH_CONCURRENCY", "EMAG_LOGIN_WAIT_SECONDS"):
    os.environ.pop(_variable, None)

from emag_spend import (  # noqa: E402 - importurile vin după curățarea mediului, de mai sus
    block_status, dates_ro, money_ro, order_links, proportional_split, settings, text_normalize, warning_messages,
)
from emag_spend.models import LineOutcome, Order, ReturnRequest, order_from_dict, return_from_dict, to_dict  # noqa: E402

SCHEMA_VERSION = 1  # forma fișierelor scrise; testele JS refuză altă valoare
JSON_INDENT = 1  # ca run_store.py: același aspect ca fișierele programului, ușor de citit în diff
# Sămânța corpusurilor: fixă, ca generatorul să scrie aceiași octeți la fiecare rulare. Din Random se folosește DOAR random(),
# singura metodă a cărei secvență Python o garantează stabilă între versiuni (ca în demo_data.py).
CORPUS_SEED = 20261013
CONFIG_DIR = settings.PROJECT_ROOT / "config"

# ---------- caractere exotice, construite din coduri (garda de caractere refuză sedilele, NBSP-ul și cele invizibile în surse) ----------
S_CEDILLA, T_CEDILLA = chr(0x15F), chr(0x163)  # literele s și t cu sedilă, diferite de ș ț (cu virgulă) din textele românești corecte
S_CEDILLA_UP, T_CEDILLA_UP = chr(0x15E), chr(0x162)
NBSP, NEL, SHY = chr(0xA0), chr(0x85), chr(0xAD)
FS, US = chr(0x1C), chr(0x1F)  # separatori de control care pentru Python sunt spații (str.isspace)
THIN_SPACE, IDEOGRAPHIC_SPACE, EM_SPACE, NARROW_NBSP, OGHAM_SPACE = chr(0x2009), chr(0x3000), chr(0x2003), chr(0x202F), chr(0x1680)
LINE_SEP, PARAGRAPH_SEP = chr(0x2028), chr(0x2029)
ZWSP, ZWNJ, ZWJ, WORD_JOINER, BOM = chr(0x200B), chr(0x200C), chr(0x200D), chr(0x2060), chr(0xFEFF)
ACUTE, GRAVE, DOT_BELOW, DIAERESIS, CEDILLA_MARK, TILDE, CARON, BREVE, RING = (
    chr(0x301), chr(0x300), chr(0x323), chr(0x308), chr(0x327), chr(0x303), chr(0x30C), chr(0x306), chr(0x30A))
VARIATION_SELECTOR_16, KEYCAP = chr(0xFE0F), chr(0x20E3)
GRIN, THUMBS_UP, FLAG_R, FLAG_O = chr(0x1F600), chr(0x1F44D), chr(0x1F1F7), chr(0x1F1F4)
SKIN_TONE = chr(0x1F3FD)
MATH_BOLD_A, MATH_BOLD_ONE, MATH_BOLD_TWO = chr(0x1D400), chr(0x1D7CF), chr(0x1D7D0)
ARABIC_THREE, DEVANAGARI_TWO = chr(0x663), chr(0x968)
ARABIC_ONE, ARABIC_TWO = chr(0x661), chr(0x662)
DOTTED_CAPITAL_I, DOTLESS_SMALL_I, KELVIN, LONG_S = chr(0x130), chr(0x131), chr(0x212A), chr(0x17F)
SHARP_S, CAPITAL_SHARP_S = chr(0xDF), chr(0x1E9E)
PRIVATE_USE, NONCHARACTER, UNASSIGNED = chr(0xE000), chr(0xFFFF), chr(0x378)


def _attempt(function, *args) -> dict:
    """{"out": rezultatul} sau {"error": {"type", "message"}} dacă funcția ridică o excepție: și erorile Python sunt referință."""
    try:
        return {"out": function(*args)}
    except Exception as error:  # noqa: BLE001 - orice excepție a funcției măsurate e o ieșire de înregistrat
        return {"error": {"type": type(error).__name__, "message": str(error)}}


def _runs(codes: list[int]) -> list[list[int]]:
    """Intervalele [de la, până la] (capete incluse) ale unei liste CRESCĂTOARE de puncte de cod."""
    runs: list[list[int]] = []
    for code in codes:
        if runs and runs[-1][1] + 1 == code:
            runs[-1][1] = code
        else:
            runs.append([code, code])
    return runs


def _pick(rng: random.Random, options):
    """Un element din secvență, cu șanse egale (doar random(), vezi CORPUS_SEED)."""
    return options[int(rng.random() * len(options))]


def _between(rng: random.Random, low: int, high: int) -> int:
    """Întreg între `low` și `high`, inclusiv (doar random())."""
    return low + int(rng.random() * (high - low + 1))


# =====================================================================================================================
# setari.json: constantele din settings.py folosite de extensie și constantele de modul portate
# =====================================================================================================================

SETTINGS_USED = (
    "BASE_URL", "ORDER_LIST_FIRST_PAGE_PATH", "ORDER_LIST_PAGE_PATH", "ORDER_DETAIL_PATH", "RETURN_LIST_PATH",
    "BIG_PURCHASE_THRESHOLD_LEI", "MAX_BIG_PURCHASE_THRESHOLD_LEI", "HIGHLIGHT_CATEGORIES",
    "FETCH_CONCURRENCY", "FETCH_RETRIES", "FETCH_BACKOFF_SECONDS", "FETCH_TIMEOUT_MS",
    "LOGIN_WAIT_SECONDS", "LOGIN_POLL_SECONDS", "LIST_RENDER_TIMEOUT_SECONDS", "MAX_LIST_PAGES", "MAX_RETURN_LOAD_MORE_CLICKS",
)
# modul -> constantele lui publice portate în JS cu același nume (valoarea trebuie să fie identică)
MODULE_CONSTANTS = {
    "block_status": ("DELIVERED", "CANCELLED", "IN_PROGRESS", "PAID_ONLY", "UNKNOWN"),
    "warning_messages": ("KIND_MISSING_PAID_TOTAL", "KIND_PENDING_RETURN", "KIND_COMPLETED_RETURN_NO_REFUND", "KIND_HEADER_MISMATCH",
                         "KIND_OTHER", "ALL_KINDS", "PAID_CHECK_CHAIN", "PAID_CHECK_BLOCKS"),
    "order_links": ("ORDER_ID_PATTERN", "ORDER_URL_PREFIX"),
    "return_matcher": ("FUZZY_MATCH_MIN_RATIO", "MIN_TRUNCATED_PREFIX"),
    "price_history": ("MIN_ORDERS_PER_PRODUCT", "PERCENT_DECIMALS"),
    "spend_analysis": ("YEARLY_CHART_TOP_CATEGORIES", "OTHER_LABEL", "TOP_PRODUCTS_LIMIT", "TOP_SELLERS_LIMIT",
                       "UNCATEGORIZED_SAMPLE_LIMIT", "HIGHLIGHT_ITEMS_LIMIT", "EXTRA_NAME_CLASH_SUFFIX"),
    "warning_details": ("MAX_PRODUCT_NAMES_IN_TEXT",),
    "paid_totals": ("EXTRA_FEES", "EXTRA_CREDIT_RETURNS", "EXTRA_REFUND_DIFFERENCES", "EXTRA_ROW_NAMES", "UNKNOWN_YEAR"),
    "block_payment": ("PAID_SHOWN", "PAID_FROM_COMPONENTS", "NOT_CHARGED"),
}


def _settings_fixture() -> dict:
    """Valorile din settings.py și din modulele portate, ca testul `setari` să le compare cu cele din JavaScript."""
    import importlib  # aici, nu sus: modulele sunt importate abia după curățarea mediului

    constants = {}
    for module_name, names in MODULE_CONSTANTS.items():
        module = importlib.import_module(f"emag_spend.{module_name}")
        constants[module_name] = {name: getattr(module, name) for name in names}
    return {
        "settings": {name: getattr(settings, name) for name in SETTINGS_USED},
        "module_constants": constants,
        "paths": {
            "order_list_page": [{"page": page, "out": settings.ORDER_LIST_PAGE_PATH.format(page=page)} for page in (1, 2, 10, 500)],
            "order_detail": [{"order_id": oid, "out": settings.ORDER_DETAIL_PATH.format(order_id=oid)} for oid in ("123456789", "1", "")],
        },
    }


# =====================================================================================================================
# unicode.json: tabelele care nu au echivalent exact în JavaScript (casefold, combining, spații, \w, \d, NFKD, caractere tipăribile)
# =====================================================================================================================

def _unicode_fixture() -> dict:
    """Tabelele Unicode ale Python-ului care rulează: casefold, combining, space, word, digit, digit_zero, nfkd, assigned, nonprintable."""
    word_pattern, digit_pattern, space_pattern = re.compile(r"\w"), re.compile(r"\d"), re.compile(r"\s")
    casefold, nfkd = [], []
    combining, space, word, digit, assigned, nonprintable, decimals = [], [], [], [], [], [], {}
    unassigned_with_rules: list[int] = []
    for code in range(0x110000):
        char = chr(code)
        folded = char.casefold()
        if folded != char:
            casefold.append([code, [ord(part) for part in folded]])
        if unicodedata.combining(char):
            combining.append(code)
        if char.isspace():
            space.append(code)
        if word_pattern.fullmatch(char):
            word.append(code)
        if digit_pattern.fullmatch(char):
            digit.append(code)
        if unicodedata.category(char) != "Cn":
            assigned.append(code)
        elif folded != char or unicodedata.combining(char) or char.isspace() or unicodedata.normalize("NFKD", char) != char:
            unassigned_with_rules.append(code)
        if not char.isprintable():
            nonprintable.append(code)
        value = unicodedata.decimal(char, None)
        if value is not None:
            decimals[code] = value
        if not 0xD800 <= code <= 0xDFFF:  # surogatele singure nu au ce căuta în text valid; JSON-ul nostru nici nu le poate scrie
            decomposed = unicodedata.normalize("NFKD", char)
            if decomposed != char:
                nfkd.append([code, [ord(part) for part in decomposed]])
    # Un punct de cod neatribuit (Cn) nu are majusculă, semn combinat, spațiu sau descompunere: normalize_text îl lasă neschimbat. Portul JS se bazează pe regula asta ca să nu depindă
    # de Unicode-ul mai nou din browser (text_normalize.js), deci o verificăm aici pe tot intervalul, nu o presupunem.
    assert not unassigned_with_rules, f"puncte de cod neatribuite cu reguli în Python: {unassigned_with_rules[:10]}"
    # \s din re și str.isspace() sunt același set (spațiile cu care lucrează strip/split și \s); \d = cifrele zecimale (Nd)
    assert [code for code in range(0x10000) if space_pattern.fullmatch(chr(code))] == [c for c in space if c < 0x10000]
    assert digit == sorted(decimals), "\\d din re nu coincide cu cifrele zecimale din unicodedata"
    zeros = [code for code, value in decimals.items() if value == 0]
    for zero in zeros:  # fiecare bloc de cifre are 10 cifre consecutive, în ordine: așa le citește pyInt din JS
        assert [decimals.get(zero + step) for step in range(10)] == list(range(10)), f"bloc de cifre neregulat la U+{zero:04X}"
    return {
        "unidata_version": unicodedata.unidata_version,
        "casefold": casefold,
        "combining": _runs(combining),
        "space": space,
        "word": _runs(word),
        "digit": _runs(digit),
        "digit_zero": zeros,
        "nfkd": nfkd,
        "assigned": _runs(assigned),
        "nonprintable": _runs(nonprintable),
    }


# =====================================================================================================================
# primitive.json: normalize_text, money_ro, dates_ro, proportional_split, round, // și %, sortări, strip/split, int, json, csv, repr...
# =====================================================================================================================

def _catalog_names() -> list[str]:
    """Numele din catalogul demonstrativ, din scenariul scris de mână și din comenzile demonstrative, fără dubluri, sortate."""
    from emag_spend import demo_scenario
    from emag_spend.demo_catalog import FILLER_FAMILIES, MARKETPLACE_SELLERS
    from emag_spend.demo_data import demo_orders_and_returns

    names = {item.name for family in FILLER_FAMILIES.values() for item in family.items}
    names.update(value for key, value in vars(demo_scenario).items() if key.isupper() and isinstance(value, str))
    orders, _ = demo_orders_and_returns()
    names.update(item.name for order in orders for block in order.blocks for item in block.items)
    names.update(MARKETPLACE_SELLERS)
    return sorted(names)


def _normalize_texts() -> list[str | None]:
    """Cel puțin 300 de texte pentru normalize_text: română (virgulă și sedilă), ß, ligaturi, greacă, chirilică, emoji, spații, semne combinate, CJK."""
    texts: list[str | None] = [
        None, "", " ", "  ", "\t", "\n", " \t\r\n ", "a", "A", " a ", "a  b", "a\tb\nc", "Ab Cd", "x" + NBSP + "y", NBSP, NBSP + "x" + NBSP,
        # română: virgulă (corect), sedilă (greșit, dar întâlnit în pagini), cu și fără diacritice
        T_CEDILLA_UP + "elină  Șampon", S_CEDILLA + "ampon " + T_CEDILLA + "elină", "  ÎNCĂLȚĂMINTE\n",
        "Încălțăminte", "ÎNCĂLȚĂMINTE bărbați", "Țuică de prune 52%, 1L", "ȚUICĂ", "șțăîâ", "ȘȚĂÎÂ", S_CEDILLA_UP + T_CEDILLA_UP, "Șampon anticădere Lumio 400 ml",
        "Cremă hidratantă față", "Apă de parfum", "Hârtie igienică", "Ghete impermeabile bărbați", "Ștergătoare parbriz", "Căști wireless",
        # ß și ligaturi
        "Straße", "STRASSE", "Maße", SHARP_S, CAPITAL_SHARP_S, "Fuß" + CAPITAL_SHARP_S, chr(0xFB01) + "sh", chr(0xFB02), chr(0xFB00), chr(0xFB03), chr(0xFB06),
        chr(0x149), chr(0x1F0), chr(0x390), chr(0x1FB3), chr(0x1FBC), chr(0x1FFC), chr(0x587), chr(0x1E96),
        # greacă (casefold per caracter, fără sigma finală contextuală)
        "ΣΑΣ", "ΟΔΥΣΣΕΥΣ", "Σ", "ς", "σ", "Ελληνικά", "ΕΛΛΗΝΙΚΆ", "ᾳ",
        # chirilică și alte alfabete
        "ПРИВЕТ", "Привет", "ёЁ", "йЙ", "ԱԲԳ", "აბგ", "ΩΜΕΓΑ",
        # i cu punct și fără: Turcă
        "İstanbul", "ISTANBUL", DOTLESS_SMALL_I + DOTLESS_SMALL_I, "I", DOTTED_CAPITAL_I, "Kelvin" + KELVIN, "Long" + LONG_S + "s",
        # emoji și secvențe
        GRIN, "a" + GRIN + "b", "👨" + ZWJ + "👩" + ZWJ + "👧", FLAG_R + FLAG_O, "1" + VARIATION_SELECTOR_16 + KEYCAP, THUMBS_UP + SKIN_TONE,
        chr(0x2764) + VARIATION_SELECTOR_16, "x" + chr(0x1F9D1) + ZWJ + chr(0x1F4BB),
        # spații și invizibile
        "a" + THIN_SPACE + "b", "a" + IDEOGRAPHIC_SPACE + "b", "a" + EM_SPACE + EM_SPACE + "b", "a" + NARROW_NBSP + "b", "a" + OGHAM_SPACE + "b", "a" + NEL + "b",
        "a" + FS + "b" + US + "c", "a" + LINE_SEP + "b" + PARAGRAPH_SEP + "c", "a\x0bb\x0cc", "a" + ZWSP + "b", "a" + ZWNJ + "b" + ZWJ + "c", "a" + WORD_JOINER + "b",
        BOM + "a" + BOM, "a" + SHY + "b", "\x00a\x00", "a\x1b[0mb", " " + ZWSP + " ", "x" + NBSP + NBSP + "  \t y",
        # semne combinate (ordine canonică, mai multe, la început, izolate)
        "e" + ACUTE, "E" + ACUTE, "e" + DOT_BELOW + ACUTE, "e" + ACUTE + DOT_BELOW, "a" + RING + CARON + TILDE, "a" + "".join([ACUTE] * 20), ACUTE + "a",
        ACUTE, "a" + ACUTE + " " + ACUTE + "b", "o" + DIAERESIS + CEDILLA_MARK, "a" + BREVE, "s" + CEDILLA_MARK, "t" + CEDILLA_MARK,
        "n" + TILDE + "o", chr(0x1E9B) + chr(0x323),
        # compatibilitate (NFKD): lățime completă, jumătate, cercuri, indici, fracții, cifre romane, litere matematice
        "Ａｂｃ１２３", "ＡＢＣ" + IDEOGRAPHIC_SPACE + "ＤＥＦ", "ｶﾞ", "①②③", "x²", "H₂O", "½", "Ⅳ", "™", "℃", "㎏", "㌀", "㈱", "ǅ", "ǆ", "Ǆ",
        MATH_BOLD_A + chr(0x1D401) + chr(0x1D402), MATH_BOLD_ONE + MATH_BOLD_TWO, chr(0x2460), chr(0x24B6), "ﬁ" + "ﬂ", chr(0xFDFA), chr(0x2474),
        # CJK și Hangul (descompunere algoritmică)
        "漢字", "한글", "ㅎㅏㄴ", "日本語テキスト", "ｱｲｳ", "가", "힣",
        # cifre din alte alfabete
        ARABIC_ONE + ARABIC_TWO + ARABIC_THREE, DEVANAGARI_TWO + chr(0x969), chr(0xE51) + chr(0xE52),
        # punctuație care nu se schimbă
        "a–b", "a—b", "«x»", "„x”", "x…", "a_b", "a/b", "C++", "50%", "a.b,c;d:e", "(x)[y]{z}", "a\\b", "\"q\"", "it's",
    ]
    names = _catalog_names()
    texts.extend(names[:60])
    texts.extend(name.upper() for name in names[:25])
    texts.extend("  " + name + "\t\n" for name in names[25:40])
    texts.extend(unicodedata.normalize("NFD", name) for name in names[40:60])
    texts.extend(name.replace(" ", NBSP + " ") for name in names[60:70])
    return texts


def _coverage_texts(unicode_tables: dict) -> list[str]:
    """Pentru fiecare punct de cod cu casefold, semn combinat sau spațiu (și câte unul din 13 cu NFKD): `x<ch>Y <ch>`, ca tabelele să fie probate pe tot."""
    chosen = [code for code, _ in unicode_tables["casefold"]]
    chosen += [code for start, end in unicode_tables["combining"] for code in range(start, end + 1)]
    chosen += unicode_tables["space"]
    chosen += [code for index, (code, _) in enumerate(unicode_tables["nfkd"]) if index % 13 == 0]
    return [f"x{chr(code)}Y {chr(code)}" for code in sorted(set(chosen)) if not 0xD800 <= code <= 0xDFFF]


# Câte texte la întâmplare se adaugă la fiecare listă de texte de sume și de date, pe lângă cele alese de mână: clădite din bucăți de sume reale, deci multe ies valide, iar
# restul probează mesajele de eroare ale lui Python. Cifrele din alte alfabete și NBSP-ul sunt printre bucăți, fiindcă int() și \s le tratează altfel decât JavaScript.
RANDOM_TEXT_CASES = 1200
_AMOUNT_PREFIXES = ("", "", "", "Total: ", "pret ", " ", "x", "Reducere: ", "\t")
_AMOUNT_SIGNS = ("", "", "", "-", "+", "- ", "--")
_AMOUNT_WHOLES = ("0", "7", "12", "105", "999", "1.449", "12.345", "1.234.567", "123456", "9007199254740", "007", "1.2", "1.23", "12.3456")
_AMOUNT_FRACTIONS = (",00", ",5", ",99", ",07", ",123", "", ",", ".50", ",0", ",000", " ,5")
_AMOUNT_SUFFIXES = ("", "", " Lei", "Lei", " lei", " RON", " LEI", NBSP + "Lei", " Leii", ".", " Le", "\n", " buc")
_AMOUNT_PIECES = ("0", "1", "5", "12", "99", "105", "1.449", ".", ",", " ", "-", "Lei", "lei", "RON", "Total", ":", "x", NBSP, "+", "_", ARABIC_THREE, MATH_BOLD_ONE, "\n", "mai", "2026", "10:07")
_REFUND_WHOLES = ("0", "5", "93", "129", "249", "1", "12", "1449", "1.449", "12.345", "999999999999", "007", "")
_REFUND_FRACTIONS = (".59", ".9", ",27", ",5", ".00", ".000", ",", ".", ".5.5", "", "", "")
_DATE_PREFIXES = ("", "", "Plasata pe: ", "x ", " ", "\n")
_DATE_DAYS = ("1", "9", "26", "31", "0", "32", "99", "007", "01", ARABIC_TWO + ARABIC_THREE)
_DATE_MONTHS = ("ian", "ianuarie", "feb", "februarie", "mar", "martie", "apr", "aprilie", "mai", "iun", "iunie", "iul", "iulie", "aug", "august", "sep", "septembrie", "oct", "octombrie",
                "noi", "noiembrie", "dec", "decembrie", "IAN", "Mai", "xyz", "may", "ma", "", "ia" + ACUTE + "n", "ian.")
_DATE_YEARS = ("2026", "2023", "0001", "9999", "202", "20266", "", "26")
_DATE_SEPARATORS = (" ", " ", "  ", "\t", NBSP, ".", ". ", "")
_DATE_TIMES = ("", "", ", 10:07", " 10:07", ", 1:07", ", 23:59", ", 24:00", ", 00:00", ",10:07", ", 99:99", ", 10:7", "  ,  09:46")
_DATE_TAILS = ("", "", " Total: 1,00 Lei", " x")


def _random_amount_texts(salt: int) -> list[str]:
    """RANDOM_TEXT_CASES texte de sume: jumătate aproape corecte (prefix, semn, întreg cu mii, fracție, sufix), jumătate bucăți amestecate; `salt` alege secvența de hazard."""
    rng = random.Random(CORPUS_SEED + salt)
    texts = []
    for _ in range(RANDOM_TEXT_CASES):
        if rng.random() < 0.5:
            texts.append("".join(_pick(rng, options) for options in (_AMOUNT_PREFIXES, _AMOUNT_SIGNS, _AMOUNT_WHOLES, _AMOUNT_FRACTIONS, _AMOUNT_SUFFIXES)))
        else:
            texts.append("".join(_pick(rng, _AMOUNT_PIECES) for _ in range(_between(rng, 1, 7))))
    return texts


def _format_lei_inputs() -> list[int]:
    """Sume în bani pentru format_lei: alese de mână (zero, ordine de mărime, negative, limita 2^53) și RANDOM_TEXT_CASES la întâmplare, de până la 10^15 bani, cu semn."""
    rng = random.Random(CORPUS_SEED + 34)
    hand_picked = [0, 1, 5, 9, 10, 99, 100, 101, 999, 1000, 99999, 100000, 144927, -1, -5, -99, -100, -3400, -144927, 100000000, 123456789012, 9007199254740991, -9007199254740991,
                   1234567, 12345678, 100099]
    randomized = [(1 if rng.random() < 0.5 else -1) * int(rng.random() * 10 ** _between(rng, 0, 15)) for _ in range(RANDOM_TEXT_CASES)]
    return list(dict.fromkeys(hand_picked + randomized))


def _ro_amount_inputs() -> list[str]:
    """Texte pentru ro_amount_to_bani și celelalte funcții de sume: valide, ciudate, cu cifre din alte alfabete, plus texte la întâmplare."""
    hand_picked = [
        "0,00", "0,99", "1,00", "12,34", "551,98", "1.449,27", "19.813,51", "1.000.000,00", "-34,00", "-0,05", "-0,00", "-1.234,56", " 12,34 ", "\t12,34\n",
        "12,3", "12,345", "12", "12,", ",5", ",50", "1.2.3,45", "1.234", "-", "--5", "-,5", "", " ", "abc", "12,3a", "1 234,56", "1,234.56", "1,2,3", "0", "00,00",
        "007,05", "12.34", "12,34,56", "12,3.4", "+12,34", "12,34 Lei", "1.234.567.890,12", "9007199254740,99",
        ARABIC_ONE + ARABIC_TWO + "," + ARABIC_THREE + "4", MATH_BOLD_ONE + MATH_BOLD_TWO + "," + MATH_BOLD_ONE + MATH_BOLD_TWO, DEVANAGARI_TWO + "," + DEVANAGARI_TWO + DEVANAGARI_TWO,
        "1" + ARABIC_THREE + ",5" + ARABIC_THREE, "-" + ARABIC_TWO + ",00", "1_000,00", "1,00_",
    ]
    return list(dict.fromkeys(hand_picked + _random_amount_texts(30)))


def _amount_texts() -> list[str]:
    """Texte cu sume pentru parse_full_amount, find_amount și find_last_amount, plus texte la întâmplare."""
    hand_picked = [
        "105,99 Lei", "105,99", "-34,00 Lei", "Total 1,00 Lei", "GRATUIT", "", "1.449,27 lei", "1.449,27 RON", "12,34Lei", "12,34 LEI", "12,34 Lei\n", "12,34" + NBSP + "Lei",
        "12,34 Lei ", " 12,34 Lei", "Total: 190,47 Lei", ": 1,49 Lei", "a 1,00 Lei b 2,50 Lei", "fara suma", "nimic", "12 Lei", "12,3 Lei", "x-5,00 Lei", "-5,00Lei y",
        "1.449,27RON", "Total produse: 222,98 Lei", "Cost livrare: GRATUIT", "Reducere: -34,00 Lei", "10,00 Lei 20,00 RON 30,00 lei", "1.000,00 Lei si 2,00 Lei",
        "12,34 Lei" + NBSP, "pret 99,99 Lei/buc", "99,99Lei", "0,00 Lei", "-0,00 Lei", "1.2,34 Lei", "12.345,67 Lei", "123456,78 Lei", "1,234,567 Lei",
        ARABIC_ONE + ARABIC_TWO + ",34 Lei", MATH_BOLD_ONE + ",00 Lei", "Suma 5,50 Lei, apoi 6,60 Lei.", "Lei 5,50", "5,50 lei lei", "7,00 Leii", "7,00 Le", "7,00 RON.",
        "-1.449,27 Lei", "1.449,27 Lei - 1.000,00 Lei",
    ]
    return list(dict.fromkeys(hand_picked + _random_amount_texts(31)))


def _refund_texts() -> list[str]:
    """Texte pentru parse_refund_amount (separator zecimal punct sau virgulă, mii cu punct), plus texte la întâmplare."""
    hand_picked = [
        "93.59", "129", "249.9", "1.449", "1.449,27", "0.5", "", "abc", "12.3.4", "1.449.000", "1.4", "12.345", "0,5", "1,5", ",5", "12 ", " 12", "12.", ".5", "1.449.00",
        "1,449", "10.00", "10.0", "10.000", "100.000", "1000.50", "-5", "-5.5", "5,5,5", "٣", ARABIC_ONE + ARABIC_TWO, MATH_BOLD_ONE + "." + MATH_BOLD_TWO, "1.449,2", "1.449,277",
        "0", "00", "007", "1_0", "12.5.0", "999999999999",
    ]
    rng = random.Random(CORPUS_SEED + 32)
    sign_and_spaces = ("", "", "-", " ", "  ", "+", NBSP)
    randomized = ["".join(_pick(rng, options) for options in (sign_and_spaces, _REFUND_WHOLES, _REFUND_FRACTIONS, sign_and_spaces)) for _ in range(RANDOM_TEXT_CASES)]
    return list(dict.fromkeys(hand_picked + randomized))


def _datetime_texts() -> list[str | None]:
    """Texte pentru parse_ro_datetime: luni scurte și întregi, cu și fără oră, cu diacritice, cu texte în jur, invalide."""
    months = ("ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie")
    texts: list[str | None] = [None, "", "26 mai 2026, 10:07", "9 decembrie 2023", "29 ian 2026, 09:46", "12 noi 2024, 23:59", "3 oct 2026, 18:21", "19 iulie 2026",
        "15 iun 2026, 13:15", "1 Iulie, 13:44", "fara data", "5 xyz 2026", "29 ian. 2026", "1 ian 0001", "31 dec 9999 23:59", "99 mai 2026, 99:99", "0 mai 2026",
        "26 MAI 2026", "26 Mai 2026", "26 mai2026", "26mai 2026", "26 mai 2026,10:07", "26 mai 2026 10:07", "26 mai 2026,  10:07", "26 mai 2026, 1:07", "26 mai 2026, 10:7",
        "Plasata pe: 26 mai 2026, 10:07 Total: 190,47 Lei", "x 3 sep 2026, 18:53 y 4 sep 2026", "26  mai   2026", "26\tmai\n2026", "26" + NBSP + "mai" + NBSP + "2026",
        "26 mai 20266", "26 mai 202", "126 mai 2026", "26 mai. 2026", "26 mai.2026", "26 ma 2026", "26 maiul 2026", "26 maxi 2026", "26 may 2026",
        "26 iunie 2026", "26 iulie 2026", "26 iun. 2026", "26 aprilie 2026, 00:00", "26 apr 2026, 24:00", ARABIC_TWO + ARABIC_THREE + " mai " + ARABIC_TWO + "026",
        "26 " + S_CEDILLA + "ep 2026", "26 sep" + T_CEDILLA + " 2026", "26 ia" + ACUTE + "n 2026", "26 Ianuarie 2026", "26 IANUARIE 2026, 10:07", "2026-05-26", "26.05.2026",
        "1 ian 2026, 00:00", "31 oct 2026, 23:59", "7 noiembrie 2025", "8 dec 2025, 08:08"]
    texts.extend(f"{day} {month} 2026, {day % 24:02d}:{(day * 7) % 60:02d}" for day, month in zip(range(1, 13), months))
    rng = random.Random(CORPUS_SEED + 33)
    for _ in range(RANDOM_TEXT_CASES):
        separator = _pick(rng, _DATE_SEPARATORS)
        texts.append(_pick(rng, _DATE_PREFIXES) + _pick(rng, _DATE_DAYS) + separator + _pick(rng, _DATE_MONTHS) + separator + _pick(rng, _DATE_YEARS)
                     + _pick(rng, _DATE_TIMES) + _pick(rng, _DATE_TAILS))
    return list(dict.fromkeys(texts))


def _split_cases() -> list[dict]:
    """Cazuri pentru split_proportionally: mici (sistematic), mari (inclusiv produse peste 2^53) și erori, cu mesajul Python."""
    rng = random.Random(CORPUS_SEED)
    cases: list[tuple[int, list[int]]] = [
        (0, []), (0, [0]), (0, [0, 0]), (5, []), (5, [0, 0]), (-1, [1]), (5, [-1, 6]), (5, [1, -1, 5]), (10, [1, 1, 1]), (100, [1, 2, 3]), (1, [1, 1, 1, 1]),
        (2, [1, 1, 1]), (7, [0, 0, 5]), (7, [3, 0, 0]), (1000, [999, 1]), (1, [3, 2, 2, 1]), (3, [1, 1]), (3, [2, 1, 1, 1, 1]), (50, [100000, 20000, 10000]),
        (9007199254740991, [1]), (9007199254740991, [3, 5, 7, 11]), (9007199254740991, [9007199254740991, 9007199254740990]),
        (9007199254740991, [9007199254740991, 1, 1]), (4503599627370496, [9007199254740991, 9007199254740991, 3]), (999999999999, [123456789012, 987654321, 5]),
        (123456789, [987654321, 123456789, 555555555, 1]),
    ]
    for total in range(0, 12):
        for weights in ([1, 1], [1, 2, 3], [2, 0, 1], [5, 5, 5, 5], [1, 0, 0, 1, 0]):
            cases.append((total, weights))
    for _ in range(300):
        count = _between(rng, 1, 7)
        weights = [_between(rng, 0, 100000) if rng.random() < 0.85 else 0 for _ in range(count)]
        cases.append((_between(rng, 0, 20000000), weights))
    for _ in range(60):
        count = _between(rng, 1, 5)
        weights = [_between(rng, 1, 9007199254740991) for _ in range(count)]
        cases.append((_between(rng, 0, 9007199254740991), weights))
    return [{"total": total, "weights": weights, **_attempt(proportional_split.split_proportionally, total, weights)} for total, weights in cases]


# Câte cazuri la întâmplare se adaugă pe lângă cele alese de mână la round(x, n), și cât de mare e exponentul (în baza 2) al valorilor generate: ±60 acoperă de la
# fracții mici la numere de ordinul 10^18, adică atât cazurile în care scara rotunjirii e sub ulp, cât și cele în care e peste.
ROUND_RANDOM_CASES = 2000
ROUND_RANDOM_EXPONENT = 60


def _round_cases() -> tuple[list[dict], list[dict]]:
    """Cazuri pentru round(x, n) și round(x): egalități exacte, jumătăți la par pe valoarea binară, negative, mari, mici, zero cu semn."""
    values = [12.25, 12.35, 12.45, 0.125, 0.375, 2.675, 1.005, 8.675, 0.045, 1.45, 1.55, 0.5, 1.5, 2.5, 3.5, -0.5, -1.5, -2.5, -12.25, -12.35, 0.0, -0.0,
              100.0, 1234.5678, 0.1, 0.2, 0.30000000000000004, 0.7, 5.5, 6.5, 7.5, 49 / 4, 4.25, 4.35, 99.995, 99.985, 0.995, 1e22, 1e-7, 5e-324, -5e-324,
              2.5e-8, 123456789.125, 123456789.135, 4503599627370495.5, 4503599627370497.0, 9007199254740993.0, 1e300, -1e300, 1.7976931348623157e308,
              0.049999999999999996, 0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 2.0, 3.0, -3.0, 1250.0, 1350.0, 12345.6789, -12345.6789]
    digits = [0, 1, 2, 3, 4, -1, -2, -3, 10, 20, 323, 324, -308, -309]
    rounded = [{"x": x, "ndigits": n, **_attempt(round, x, n)} for x in values for n in digits]
    rng = random.Random(CORPUS_SEED + 1)
    for _ in range(400):  # procente ca la price_history: delta * 100 / preț, cu o zecimală
        previous = _between(rng, 1, 200000)
        delta = _between(rng, -previous + 1, previous * 2)
        rounded.append({"x": delta * 100 / previous, "ndigits": 1, **_attempt(round, delta * 100 / previous, 1)})
    for _ in range(ROUND_RANDOM_CASES):
        # Două feluri de valori la întâmplare: (a) mantisă și exponent la întâmplare, adică orice scară de mărime; (b) jumătăți zecimale (k,5 / 10^n), exact locul unde rotunjirea
        # pe valoarea binară exactă (cea din Python) diferă de rotunjirea „pe zecimale”.
        if rng.random() < 0.5:
            x = (rng.random() + 0.5) * 2.0 ** _between(rng, -ROUND_RANDOM_EXPONENT, ROUND_RANDOM_EXPONENT) * (1 if rng.random() < 0.5 else -1)
        else:
            x = float(f"{_between(rng, -99999, 99999)}.5e-{_between(rng, 0, 6)}")
        ndigits = _between(rng, -3, 9)
        rounded.append({"x": x, "ndigits": ndigits, **_attempt(round, x, ndigits)})
    integers = [{"x": x, **_attempt(round, x)} for x in values if x == x and abs(x) < 1e300]
    integers += [{"x": x / 8, **_attempt(round, x / 8)} for x in range(-40, 41)]
    return rounded, integers


def _percent_cases() -> list[dict]:
    """(delta, preț) -> round(delta * 100 / preț, 1), exact ca la last_vs_prev_pct, inclusiv jumătăți exacte (49/400 = 12,25)."""
    rng = random.Random(CORPUS_SEED + 2)
    pairs = [(49, 400), (-49, 400), (1, 8), (1, 16), (3, 80), (49 * 3, 400 * 3), (1, 3), (2, 3), (1, 7), (5, 200), (1, 40), (-1, 40), (7, 800), (0, 5), (-1, 100000), (1, 100000)]
    for _ in range(600):
        previous = _between(rng, 1, 300000)
        pairs.append((_between(rng, -previous + 1, previous), previous))
    for multiple in range(1, 120):  # prețuri la care procentul are exact două zecimale 5 (jumătate la par pe valoarea binară)
        pairs.append((49 * multiple, 400 * multiple))
        pairs.append((-(21 * multiple), 400 * multiple))
    return [{"delta": delta, "previous": previous, "out": round(delta * 100 / previous, 1)} for delta, previous in pairs]


def _division_cases() -> list[dict]:
    """Cazuri pentru // și %: semne amestecate, zero, mari; împărțirea la zero se înregistrează doar ca eroare."""
    rng = random.Random(CORPUS_SEED + 3)
    pairs = [(7, 2), (-7, 2), (7, -2), (-7, -2), (0, 5), (0, -5), (6, 3), (-6, 3), (6, -3), (-6, -3), (1, 7), (-1, 7), (1, -7), (-1, -7), (100, 100), (-100, 100),
             (9007199254740991, 2), (-9007199254740991, 2), (9007199254740991, -2), (9007199254740991, 3), (9007199254740991, 9007199254740991), (-9007199254740991, 9007199254740990),
             (9007199254740990, 9007199254740991), (5, 0), (0, 0), (-5, 0), (144927, 100), (-3400, 100), (99, 100), (-99, 100), (4503599627370495, 7)]
    for _ in range(300):
        pairs.append((_between(rng, -1000000, 1000000), _pick(rng, (1, 2, 3, 7, 100, -100, -7, -2, 12345, 997))))
    cases = []
    for a, b in pairs:
        if b == 0:
            cases.append({"a": a, "b": b, "zero_division": True})
        else:
            cases.append({"a": a, "b": b, "div": a // b, "mod": a % b})
    return cases


def _sort_strings() -> list[str]:
    """Texte pentru comparări și sortări: emoji (peste U+FFFF), caractere BMP mari (U+E000, U+FFFF), diacritice, majuscule, cifre, prefixe."""
    return ["", "a", "A", "b", "B", "ab", "a" + NBSP, "a b", "a-b", "a_b", "ă", "â", "ș", "ț", "z", "Z", "é", "e" + ACUTE, "1", "10", "2", "9", "00", PRIVATE_USE, NONCHARACTER,
            GRIN, THUMBS_UP, "a" + GRIN, "a" + PRIVATE_USE, "a" + NONCHARACTER, chr(0xFF21), chr(0xFB01), chr(0x10000), chr(0x10FFFF), chr(0xD7FF), chr(0x1F600) + "a",
            chr(0x1F600) + "b", "Zebra", "zebra", "Ábaco", "ábaco", "Abaco", "ß", "ss", "ẞ", "İ", "ı", "i", "I", "日本", "中", "한"]


def _sorted_key_cases() -> dict:
    """Sortări cu chei-tuplu, stabilitate, reverse, max/min cu key= (primul maxim) și amestec de tipuri (TypeError)."""
    strings = _sort_strings()
    rng = random.Random(CORPUS_SEED + 4)
    string_orders = [{"in": strings, "out": sorted(strings)}]
    for _ in range(30):
        sample = [_pick(rng, strings) for _ in range(_between(rng, 2, 14))]
        string_orders.append({"in": sample, "out": sorted(sample)})
    compare = [{"a": a, "b": b, "out": (a > b) - (a < b)} for a in strings for b in strings[:25]]
    tuple_cases = []
    key_sets = [
        [[1, "a"], [1, "b"], [0, "z"], [1, "a"]],
        [[-5, "x", 0], [-5, "x", 1], [-6, "y", 2], [-5, "w", 3]],
        [[False, "b"], [True, "a"], [False, "a"]],
        [[0.5, 1], [0.25, 2], [0.5, 0], [1, 1]],
        [["b"], ["a"], ["ab"], [""], [GRIN], [PRIVATE_USE]],
        [[[1, 2], "x"], [[1, 1], "y"], [[1], "z"], [[], "w"], [[1, 2], "a"]],
        [[3], [3], [3], [3]],
        [[1, "a"], [1]],
        [[2, 3], [2, 3, 4], [2], [1, 9, 9]],
        [["Zebra", 1], ["zebra", 0], ["Ábaco", 2], [GRIN, 3]],
        [[3], [1], [2]],
    ]
    for _ in range(25):
        key_sets.append([[_between(rng, -3, 3), _pick(rng, ("a", "b", "")), _between(rng, 0, 2)] for _ in range(_between(rng, 2, 9))])
    for keys in key_sets:
        indices = list(range(len(keys)))
        for reverse in (False, True):
            ordered = sorted(indices, key=lambda i: tuple(keys[i]), reverse=reverse)
            tuple_cases.append({"keys": keys, "reverse": reverse, "out": ordered})
        biggest = max(indices, key=lambda i: tuple(keys[i]))
        smallest = min(indices, key=lambda i: tuple(keys[i]))
        tuple_cases.append({"keys": keys, "max_index": biggest, "min_index": smallest})
    scalar_cases = []
    for scalars in ([3, 1, 2, 1], ["b", "a", GRIN, "B"], [2.5, 1, 2, 1.5], [True, False, 1, 0], [-1, -1, 0, -2]):
        scalar_cases.append({"keys": scalars, "out": sorted(range(len(scalars)), key=lambda i: scalars[i]),
                             "max_index": max(range(len(scalars)), key=lambda i: scalars[i])})
    mixed = [{"keys": [[1], ["a"]]}, {"keys": [[1, "a"], [1, 2]]}, {"keys": [["a"], [None]]}, {"keys": [[[1]], [1]]}]
    for case in mixed:  # Python ridică TypeError la prima comparație între tipuri nepotrivite
        case.update(_attempt(lambda keys=case["keys"]: sorted(range(len(keys)), key=lambda i: tuple(keys[i]))))
    return {"strings": string_orders, "compare": compare, "tuples": tuple_cases, "scalars": scalar_cases, "mixed": mixed}


def _strip_split_cases() -> list[dict]:
    """strip()/lstrip()/rstrip()/split() cu și fără argument, pe spațiile Unicode din Python (NEL, FS-US, NBSP, U+3000...) și pe cele care NU sunt spații (U+FEFF, U+200B)."""
    texts = ["", " ", "  a  ", "a", "\t\n a b \r\n", NEL + "x" + FS, FS + US + "x", NBSP + "x" + NBSP, IDEOGRAPHIC_SPACE + "x" + IDEOGRAPHIC_SPACE, THIN_SPACE + "x" + EM_SPACE,
             BOM + "x" + BOM, ZWSP + "x" + ZWSP, "x" + ZWJ, LINE_SEP + "x" + PARAGRAPH_SEP, "a  b\tc" + NBSP + "d" + NEL + "e", "a" + BOM + "b", "a" + ZWSP + "b", "   ",
             NBSP + NBSP, "\x0b\x0cx\x0b", "a b", ",a,", " ,a, ", GRIN + "a" + GRIN, ".,;x;,.", "xx", OGHAM_SPACE + "x", "x" + chr(0x2000) + chr(0x200A) + "y", "x" + chr(0x205F) + "y",
             "x" + chr(0x180E) + "y", chr(0) + "x"]
    rng = random.Random(CORPUS_SEED + 38)
    pieces = (" ", "\t", "\n", "\r", "\x0b", "\x0c", NBSP, NEL, FS, US, IDEOGRAPHIC_SPACE, THIN_SPACE, LINE_SEP, PARAGRAPH_SEP, OGHAM_SPACE, BOM, ZWSP, ZWJ, chr(0x180E), chr(0x2000), chr(0x200A),
              "a", "b", "xy", ",", ".", GRIN, "é", "0")
    texts += list(dict.fromkeys("".join(_pick(rng, pieces) for _ in range(_between(rng, 0, 9))) for _ in range(RANDOM_TEXT_CASES // 2)))
    chars_options = [" ", " ,", ",.;", GRIN, "xy", "", "a b", NBSP, "\t\n"]
    cases = []
    for text in texts:
        case = {"in": text, "strip": text.strip(), "lstrip": text.lstrip(), "rstrip": text.rstrip(), "split": text.split()}
        case["with_chars"] = [{"chars": chars, "strip": text.strip(chars), "lstrip": text.lstrip(chars), "rstrip": text.rstrip(chars)} for chars in chars_options]
        cases.append(case)
    return cases


def _int_cases() -> list[dict]:
    """int(text): cifre din alte alfabete, semn, spații, underscore între cifre, erori (mesajul Python cu repr)."""
    texts = ["0", "7", "123", "007", " 12 ", "\t12\n", "+5", "-7", "- 7", "1_000", "1__0", "_1", "1_", "1_0_0", "-1_0", "", " ", "abc", "12a", "1.5", "1,5", "--1", "+-1", "0x10", "1e3",
             ARABIC_ONE + ARABIC_TWO + ARABIC_THREE, DEVANAGARI_TWO + chr(0x969), MATH_BOLD_ONE + MATH_BOLD_TWO, "-" + ARABIC_TWO, ARABIC_ONE + "_" + ARABIC_TWO, "1" + ARABIC_TWO, NBSP + "5" + NBSP,
             IDEOGRAPHIC_SPACE + "5", "5" + ZWSP, ZWSP + "5", "²", "½", "९९", "99999999999999999999", "9007199254740991", "9007199254740992", "-9007199254740991", "-9007199254740993",
             "٠", "0" + ARABIC_TWO, FS + "5", "5" + NEL, "ａ", "１２", "x" + "1", "1" + "x", "1 2", "1\n2", "١٢٣٤٥٦٧٨٩٠"]
    rng = random.Random(CORPUS_SEED + 35)
    spaces = ("", "", "", " ", "  ", "\t", "\n", "\x0b", "\x0c", NBSP, IDEOGRAPHIC_SPACE, ZWSP, FS, NEL, BOM)
    for _ in range(RANDOM_TEXT_CASES):
        digits = "".join(_pick(rng, "0123456789") for _ in range(_between(rng, 1, 19)))
        if rng.random() < 0.15:
            digits = "".join(_pick(rng, (ARABIC_ONE, ARABIC_TWO, ARABIC_THREE, DEVANAGARI_TWO, MATH_BOLD_ONE, "7", "0")) for _ in range(_between(rng, 1, 5)))
        if rng.random() < 0.2 and len(digits) > 1:
            cut = _between(rng, 1, len(digits) - 1)
            digits = digits[:cut] + _pick(rng, ("_", "_", "__", ".", ",", "x")) + digits[cut:]
        texts.append(_pick(rng, spaces) + _pick(rng, ("", "", "", "+", "-", "--", "- ")) + digits + _pick(rng, ("", "", "", "_", "L", ".0")) + _pick(rng, spaces))
    return [{"in": text, **_attempt(int, text)} for text in dict.fromkeys(texts)]


# Șirurile și cheile din valorile JSON la întâmplare: ghilimele, backslash, linii noi, caractere de control, separatori Unicode, emoji, </script>; cheile nu sunt șiruri de cifre,
# fiindcă un obiect JavaScript le-ar reordona (dicționarele cu chei din date se compară ca Map, în altă secțiune).
_JSON_STRINGS = ("", "a", "text", 'q"uote', "back\\slash", "new\nline", "tab\t", "cr\r", "é", "ă î ș ț", GRIN, NBSP, LINE_SEP, "</script>", chr(1), chr(0x7F), "x" * 30, "k1")
_JSON_KEYS = ("a", "b", "k", "cheie", "é", GRIN, 'q"', "x y", "", "z", "m", "n1", "back\\")


def _random_json_value(rng: random.Random, depth: int):
    """O valoare JSON la întâmplare: None, boolean, întreg sigur, șir sau (cât `depth` e pozitiv) listă ori dicționar cu până la 4 elemente."""
    roll = rng.random()
    if depth <= 0 or roll < 0.45:
        scalar = rng.random()
        if scalar < 0.15:
            return None
        if scalar < 0.3:
            return rng.random() < 0.5
        if scalar < 0.55:
            return (1 if rng.random() < 0.5 else -1) * int(rng.random() * 10 ** _between(rng, 0, 15))
        return _pick(rng, _JSON_STRINGS)
    if roll < 0.75:
        return [_random_json_value(rng, depth - 1) for _ in range(_between(rng, 0, 4))]
    keys = list(dict.fromkeys(_pick(rng, _JSON_KEYS) for _ in range(_between(rng, 0, 4))))
    return {key: _random_json_value(rng, depth - 1) for key in keys}


# Floaturi folosite la probele PyFloat (json, repr, csv): multe cu valoare întreagă (5.0), singurele pe care JavaScript nu le poate scrie fără marcaj, plus zero negativ, exponenți și limite.
_FLOAT_SAMPLES = (5.0, 0.0, -0.0, 12.5, 1e16, 1e-7, 123456789.0, 1e22, 2.0 ** 53, -3.0, 100.0, 0.1 + 0.2, 1e-5, 12345678901234567.0, 5e-324, 1.7976931348623157e308, 7.0, 10.0, 0.5, -0.5, 1.0,
                  99.99, 2.675)
# Câte liste de floaturi se scriu cu json.dumps și repr la probele PyFloat.
FLOAT_MARKED_CASES = 400
# Câte numere zecimale la întâmplare (biți la întâmplare) se adaugă pe lângă cele alese de mână la repr(float): destule cât să atingă fiecare binadă, puține cât să rămână fișierul mic.
FLOAT_REPR_RANDOM_CASES = 3000


def _json_cases() -> dict:
    """json.dumps(valoare, ensure_ascii=False, indent=1) și variantele cu separatori impliciți / numere cu fracții, pe valori cu caractere de scăpat."""
    nasty = 'a"b\\c/d\ne\rf\tg\bh\fi' + chr(1) + chr(0x1F) + chr(0x7F) + "é" + GRIN + LINE_SEP + PARAGRAPH_SEP + "</script>" + chr(0x2028)
    values = [
        None, True, False, 0, -1, 42, 9007199254740991, -9007199254740991, "", "text", nasty, "ă î ș ț Ă Î Ș Ț", S_CEDILLA + T_CEDILLA, GRIN, NBSP + BOM + ZWSP,
        [], {}, [[]], [{}], {"a": []}, {"a": {}}, [1, 2, 3], [None, True, False, "x"], {"a": 1, "b": [1, 2, {"c": None}], "d": {"e": "f"}},
        {"cheie cu \" ghilimele": "valoare \\ cu backslash", "": "gol", "é": GRIN}, {"z": 1, "a": 2, "m": 3},
        [{"order_id": "123", "blocks": [], "warnings": []}, {"order_id": "456", "blocks": [{"items": []}], "warnings": ["x"]}],
        {"nested": [[[[[1]]]], {"x": {"y": {"z": [{}]}}}]}, [nasty, [nasty], {"k": nasty}],
    ]
    rng = random.Random(CORPUS_SEED + 37)
    values += [_random_json_value(rng, _between(rng, 1, 4)) for _ in range(RANDOM_TEXT_CASES // 3)]
    plain = [{"value": value, "out": json.dumps(value, ensure_ascii=False, indent=1)} for value in values]
    plain += [{"value": value, "indent": None, "out": json.dumps(value, ensure_ascii=False)} for value in values]
    pairs_sources = [
        [["2024", 1], ["a", [1, 2]], ["10", {"x": 1}], ["", None]],
        [["necunoscut", 3], ["2026", 4], ["2025", 5]],
        [],
        [["é", GRIN], [GRIN, "é"]],
        [["1", {"2": 3}]],
    ]
    maps = [{"pairs": pairs, "out": json.dumps(dict(pairs), ensure_ascii=False, indent=1)} for pairs in pairs_sources]
    maps += [{"pairs": pairs, "indent": None, "out": json.dumps(dict(pairs), ensure_ascii=False)} for pairs in pairs_sources]
    # Doar numere cu parte fracționară: JavaScript nu poate ști că 5 era de fapt 5.0 în Python, deci un float cu valoare întreagă nu se compară la octet.
    fractional_values = [0.5, 12.2, 12.25, -0.5, 1e-05, 0.0001, 1e15 + 0.5, 123456.789, 5e-324, 0.1, 0.30000000000000004, 2.675,
                         -1e-7, 0.001, 12345678.9, 1.5e-10, 3.14159, 100.5, 99.99, 7.4, -7.4, 0.07, 0.7, 1 / 3, 2 / 3, 4.35, 8.675]
    fractions = [{"value": value, "out": json.dumps(value, ensure_ascii=False, indent=1)} for value in fractional_values]
    fractions += [{"value": fractional_values, "out": json.dumps(fractional_values, ensure_ascii=False, indent=1)},
                  {"value": fractional_values, "indent": None, "out": json.dumps(fractional_values, ensure_ascii=False)},
                  {"value": {"pct": [7.4, -0.5], "n": 3, "t": "x"}, "indent": None, "out": json.dumps({"pct": [7.4, -0.5], "n": 3, "t": "x"}, ensure_ascii=False)}]
    float_reprs = [{"x": value, "out": repr(value)} for value in fractional_values + [100.0, 5.0, -3.0, 1e16, 1e15, 12.0, 0.0, -0.0, 1e100, 123456789012345680.0, 2.0 ** 53, 1e-4, 1e-5,
                                                                                    9.999999999999999e22, 1.7976931348623157e308, 1e22 + 1e6, 1e21 + 1e5]]
    rng = random.Random(CORPUS_SEED + 6)
    target = len(float_reprs) + FLOAT_REPR_RANDOM_CASES
    while len(float_reprs) < target:
        # 64 de biți la întâmplare: orice exponent, inclusiv subnormale și numere uriașe, deci toate formele lui repr (zecimală, cu exponent, cu .0); NaN și infinitul nu au biți ai lor aici
        bits = (int(rng.random() * 2 ** 32) << 32) | int(rng.random() * 2 ** 32)
        value = struct.unpack("<d", struct.pack("<Q", bits))[0]
        if value == value and abs(value) != float("inf"):
            float_reprs.append({"x": value, "out": repr(value)})
    marked = []
    for _ in range(FLOAT_MARKED_CASES):  # liste de floaturi, deseori cu valoare întreagă (5.0): în JavaScript fiecare valoare e învelită în PyFloat
        values = [_pick(rng, _FLOAT_SAMPLES) if rng.random() < 0.6 else float(int(rng.random() * 10 ** _between(rng, 0, 18))) / 10 ** _between(rng, 0, 3) for _ in range(_between(rng, 1, 5))]
        marked.append({"values": values, "list_out": json.dumps(values, ensure_ascii=False, indent=1), "list_flat_out": json.dumps(values, ensure_ascii=False),
                       "dict_out": json.dumps({"pct": values[0], "n": 3, "xs": values[1:]}, ensure_ascii=False, indent=1), "repr_out": repr(values)})
    return {"plain": plain, "maps": maps, "fractions": fractions, "float_repr": float_reprs, "float_marked": marked}


def _csv_cases() -> list[dict]:
    """Rânduri CSV (csv.writer, delimitator `;`, CRLF): ghilimele doar la nevoie, cu `;`, `"`, CR, LF, spații la margini, formule, gol, None, numere."""
    import csv
    import io

    def row_text(fields) -> str:
        """Rândul exact cum îl scrie csv.writer(delimiter=";"), cu CRLF la sfârșit."""
        buffer = io.StringIO(newline="")
        csv.writer(buffer, delimiter=";").writerow(fields)
        return buffer.getvalue()

    rows = [
        ["a", "b", "c"], ["a;b", "c"], ['a"b', "c"], ["a\nb"], ["a\rb", "x"], ["a\r\nb"], [" a ", "b "], ["=1+1", "+2", "-3", "@x", "\tx", "'y"], ["", ""], [""], ["", "x"],
        [None, "x", None], [1, 2, 3], [-5, 0, 100], [True, False], ["a", 1, None, "b;c", 'd"e'], ['"'], ['""'], [";"], ["x" * 50, "é", GRIN, NBSP, ZWSP], ["a,b", "c.d"],
        ["a\tb"], ["linia1\nlinia2;x", 'cu "ghilimele"'], [" "], ["\n"], ["\r"], ["a'b"], ["#x", "!y", "|z", "~w"], [LINE_SEP + "x", PARAGRAPH_SEP], ["comanda", "link_comanda", "data"],
        ["123456789", "https://www.emag.ro/history/shoppingdetails/123456789", "2026-05-26", "2026", "eMAG", "Rucsac, Negru", "Altele", "", 1, "105,99", "105,99", "105,99"],
    ]
    rng = random.Random(CORPUS_SEED + 36)
    pool = ["", "", "a", "b;c", 'x"y', "l1\nl2", "r\rr", "cr\r\nlf", " pad ", "é", GRIN, NBSP, "=cmd", "'q", "\t", ";", '"', "x" * 20, None, None, 0, 7, -3, 12345, True, False, "105,99", "a,b"]
    rows += [[_pick(rng, pool) for _ in range(_between(rng, 1, 6))] for _ in range(RANDOM_TEXT_CASES // 2)]
    cases = [{"fields": fields, "out": row_text(fields)} for fields in rows]
    for _ in range(RANDOM_TEXT_CASES // 4):  # rânduri cu floaturi (PyFloat în JavaScript): `float_at` spune ce poziții sunt float, fiindcă JSON-ul nu face diferența între 5.0 și 5
        row = [_pick(rng, pool) for _ in range(_between(rng, 1, 6))]
        float_at = [index for index in range(len(row)) if rng.random() < 0.4]
        for index in float_at:
            row[index] = _pick(rng, _FLOAT_SAMPLES)
        cases.append({"fields": row, "float_at": float_at, "out": row_text(row)})
    return cases


def _status_texts() -> list[str]:
    """Texte de status pentru classify_status: fiecare regulă, cu majuscule, diacritice, în text mai lung, precedența și necunoscute."""
    hand_picked = ["Livrare anulata", "Livrare anulată", "LIVRARE ANULATA", "Am trimis cererea de anulare catre ALFA SRL. Statusul comenzii va fi actualizat. | Livrare anulata",
            "Produse ridicate", "Produse livrate", "produse livrate | Istoric", "Plata acceptata", "Comanda plasata", "Predate curierului", "Predate curierului FAN",
            "In drum spre tine", "În drum spre tine", "Produse ajunse in showroom", "Produse ajunse la easybox", "In curs de livrare", "In pregatire", "Pregatit pentru livrare",
            "Expediat", "Confirmat", "", " ", "Un status pe care programul nu-l cunoaste", "livrare", "anulat", "Produse ridicate | Livrare anulata", "Comanda plasata | Produse livrate",
            "ridicate", "PRODUSE LIVRATE", "Produse" + NBSP + "livrate", "Produse  \t livrate", "Produse livrate" + ZWSP, "Pro" + ZWSP + "duse livrate", "ajunse in", "ajunse la",
            "ajunse inainte", "pregatita", "preg" + ACUTE + "atit"]
    # Combinații la întâmplare: 1-3 bucăți (textele regulilor din block_status, cuvinte din jur, litere cu diacritice), cu majuscule și separatori diferiți, deci precedența regulilor și normalizarea.
    rng = random.Random(CORPUS_SEED + 41)
    pieces = [needle for needle, _status in block_status._RULES] + ["Am trimis cererea de anulare catre", "Istoric", "FAN Courier", "|", "ă î ș ț", "x", "Statusul comenzii", "ridicate", "livrare"]
    separators = (" ", " | ", "  ", NBSP, "\t", ZWSP, "")
    randomized = []
    for _ in range(RANDOM_TEXT_CASES // 2):
        parts = [_pick(rng, pieces) for _ in range(_between(rng, 1, 3))]
        parts = [part.upper() if rng.random() < 0.25 else (part.title() if rng.random() < 0.25 else part) for part in parts]
        randomized.append(_pick(rng, separators).join(parts))
    return list(dict.fromkeys(hand_picked + randomized))


def _warning_format_cases() -> list[dict]:
    """Fiecare funcție format_* din warning_messages, pe argumente obișnuite și ciudate (acolade, caractere speciale, singular/plural, None)."""
    cases: list[tuple[str, list]] = []
    sellers = ["eMAG", "ALFA SRL", "Firma: Test, cu virgulă", "{seller}", "{0}", "x {y} z", "É" + ACUTE, GRIN, "", "  "]
    for seller in sellers:
        cases.append(("format_missing_paid_total", ["489000001", seller]))
        cases.append(("format_missing_products_total", ["489000002", seller]))
        cases.append(("format_no_products", ["489000003", seller]))
    for sum_bani, total_bani in ((1000, 1200), (0, 0), (-5, 5), (123456789, 100), (99, 100)):
        cases.append(("format_products_sum_mismatch", ["489000004", "eMAG", sum_bani, total_bani]))
        cases.append(("format_paid_mismatch", ["489000005", "ALFA SRL", sum_bani, total_bani]))
    cases += [("format_order_number_mismatch", ["999", "489000012"]), ("format_name_count_mismatch", ["489000013", 1, 2]), ("format_name_count_mismatch", ["489000013", 0, 12]),
              ("format_no_seller_section", ["489000014"])]
    for status_text in ("Un status necunoscut", "", "cu 'apostrof'", 'cu "ghilimele"', "cu ' și \"", "linie\nnouă\ttab\\", "ă î ș ț", NBSP + "x", ZWSP, GRIN, chr(0x7F) + chr(1),
                        chr(0xFFFF), UNASSIGNED, PRIVATE_USE, LINE_SEP, "é" + ACUTE, "x" * 30, "\\", "'", '"', "'\""):
        cases.append(("format_unknown_status", ["489000015", "ALFA SRL", status_text]))
    for count in (1, 2, 3, 12, 0, 100):
        cases += [("format_pending_returns", [count]), ("format_refunds_without_amount", [count]), ("format_header_mismatches", [count]), ("format_uncategorized", [count])]
    for mode in ("Vreau banii inapoi", "Emitere voucher", None, "", "   ", "Mod necunoscut", " Mod cu spații ", "ă" + NBSP):
        cases.append(("format_unknown_refund_mode", ["3000001", mode]))
    for name in ("Alcool", "Televizoare", "Cu «ghilimele»", "", GRIN):
        cases.append(("format_highlight_category_missing", [name]))
    for ordered, parts in ((100000, 99000), (0, 0), (144927, -5), (123456789, 1)):
        cases.append(("format_funnel_not_closing", [ordered, parts]))
    for check in (warning_messages.PAID_CHECK_CHAIN, warning_messages.PAID_CHECK_BLOCKS):
        for computed, parts in ((100000, 99000), (-3400, 0)):
            cases.append(("format_paid_not_closing", [check, computed, parts]))
    return [{"fn": name, "args": args, "out": getattr(warning_messages, name)(*args)} for name, args in cases]


# Câte variante strâmbate se fac din fiecare mesaj produs de format_* la probele lui parse_order_warning.
WARNING_MUTATIONS_PER_MESSAGE = 6


def _warning_parse_texts(formatted: list[dict]) -> list[str]:
    """Texte pentru parse_order_warning: toate mesajele produse de format_*, mesajele din return_matcher.py, variații și texte care nu seamănă cu nimic."""
    texts = [case["out"] for case in formatted]
    texts += [
        "retur 3000001: nu are nicio comandă asociată", "retur 3000002: comanda 489000001, 489000002 nu e în lista citită", "retur 3000003: nu are produse listate",
        "retur 3000004: produsul 'Rucsac' nu are potrivire în comanda ['489000001']", "retur : fără număr", "retur abc: număr invalid", "retur 3000005: ",
        "comanda 489000001, eMAG: suma produselor (10,00 Lei) ≠ 'Total produse' (12,00 Lei)", "comanda 489000001, ALFA SRL: lipsește 'Total platit'",
        "comanda 489000001, ALFA: SRL: lipsește 'Total platit'", "comanda 489000001, Firma, cu virgulă: lipsește 'Total platit'", "comanda 489000001, : lipsește 'Total platit'",
        "comanda 489000001, eMAG: niciun produs găsit", "comanda 489000001: nicio secțiune de vânzător găsită", "comanda 489000001: numărul din pagină (1) ≠ numărul cerut (2)",
        "comanda 489000001: 1 nume de produs în HTML ≠ 2 produse din linii; se folosesc numele din linii", "comanda 489000001, eMAG: total plătit (1,00 Lei) ≠ componente (2,00 Lei)",
        "comanda 489000001: ceva necunoscut", "comanda: fără număr", "comanda 12a, eMAG: x", "comanda " + ARABIC_ONE + ARABIC_TWO + ", eMAG: x", "comanda 489000001, eMAG: x\ny",
        "comanda 489000001, eMAG: lipsește 'Total platit'\n", "status necunoscut la comanda 489000001 (eMAG): 'x'", "status necunoscut la comanda 489000001 (ALFA (SRL)): 'x'",
        "status necunoscut la comanda 489000001 (eMAG): ", "status necunoscut la comanda x (eMAG): y", "lanțul sumelor nu se închide: comandat 1,00 Lei ≠ părți 2,00 Lei",
        "lanțul sumelor plătite nu se închide (x): 1,00 Lei ≠ părți 2,00 Lei", "1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat",
        "0 retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate", "007 retururi finalizate fără sumă restituită afișată",
        "1 retur finalizat fără sumă restituită afișată", "1 retur finalizat fără sumă restituită afișată\n", "12 comenzi la care totalul din antet ≠ suma blocurilor",
        "1 comandă la care totalul din antet ≠ suma blocurilor", ARABIC_ONE + " comandă la care totalul din antet ≠ suma blocurilor", "x retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate",
        "categoria evidențiată «Alcool» nu există în config/categorii.json: totalul ei apare 0", "5 produse necategorizate (adaugă reguli în config/categorii.personal.json)",
        "", " ", "text oarecare", "retur", "comanda", "retur 12", "comanda 12", "lanțul sumelor nu se închide", "status necunoscut la comanda", "suma produselor",
        "niciun produs", "nicio secțiune", "numărul din pagină", "retur 3000006: mod de restituire necunoscut („Ceva”), tratat ca bani primiți înapoi (adaugă-l în config/restituiri.json)",
    ]
    rng = random.Random(CORPUS_SEED + 40)
    noise = ("a", " ", ",", ":", "(", ")", "'", "\n", "é", GRIN, ARABIC_ONE, "0", "≠", "«", "»", "„", "”")
    for message in [case["out"] for case in formatted]:  # fiecare mesaj produs de format_*, strâmbat de 1-3 ori (șters, inserat sau înlocuit un caracter), ca să probeze marginile expresiilor
        for _ in range(WARNING_MUTATIONS_PER_MESSAGE):
            chars = list(message)
            for _ in range(_between(rng, 1, 3)):
                position, roll = _between(rng, 0, len(chars)), rng.random()
                if roll < 0.4 and position < len(chars):
                    del chars[position]
                elif roll < 0.8:
                    chars.insert(position, _pick(rng, noise))
                elif position < len(chars):
                    chars[position] = _pick(rng, noise)
            texts.append("".join(chars))
    return list(dict.fromkeys(texts))


def _order_links_cases() -> list[dict]:
    """is_valid_order_id, order_url și return_url pe numere valide și ciudate (litere, gol, `..`, `/`, cifre din alte alfabete, tipuri care nu sunt text)."""
    ids = ["123", "489000001", "12", "1234567890123456", "123456789012345", "", " ", "abc", "12a", "../1", "1/2", "1\n", "\n123", "123\n", " 123", "123 ", ARABIC_ONE + ARABIC_TWO + ARABIC_THREE,
           "123" + ZWSP, "٣٣٣", "０１２", MATH_BOLD_ONE * 3, "1" * 3, "000", None, 123, 12.5, True, ["123"], {"a": 1}]
    paths = [None, "/user/return-history/1/3000001", "/user/return-history/1/489000001", "/user/return-history/12/3000001", "/user/return-history/1/3000001/", "/user/return-history/1/30",
             "/user/return-history//3000001", "/user/return-history/a/3000001", "user/return-history/1/3000001", "/user/return-history/1/3000001?x=1", "/user/return-history/1/3000001\n",
             "/user/return-history/1234567890123456/3000001", "/user/return-history/123456789012345/3000001", "/user/return-historyx/1/3000001", "/user/return-history/1/" + ARABIC_ONE * 7,
             "", 5, ["x"], "https://www.emag.ro/user/return-history/1/3000001", "/user/return-history/1/3000001%0a"]
    cases = [{"fn": "is_valid_order_id", "args": [value], "out": order_links.is_valid_order_id(value)} for value in ids]
    cases += [{"fn": "order_url", "args": [value], "out": order_links.order_url(value)} for value in ids]
    for path in paths:
        for return_id in ("3000001", "489000001", "30", None, 3000001):
            cases.append({"fn": "return_url", "args": [return_id, path], "out": order_links.return_url(return_id, path)})
    cases.append({"fn": "return_url", "args": ["3000001"], "out": order_links.return_url("3000001")})
    return cases


# Șabloanele de înlocuire la întâmplare pentru re.sub: bucăți de text, referințe la grupuri (numerice, cu nume, \g<0>), escape-uri valide și invalide; rezultatul sau eroarea lui Python
# (mesajul cu poziția) e referința. Expresiile de mai jos sunt acceptate de port; textele și numărul maxim de înlocuiri variază și ele.
SUB_TEMPLATE_CASES = 900
_TEMPLATE_PATTERNS = ("(a)(b)?", "(?P<x>\\d+)-(?P<y>\\w+)", "x", "(a)|(b)", "", "(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)(\\d)")
_TEMPLATE_TEXTS = ("ab", "a", "12-ab x", "xx", "", "b", "éa", "12345678901")
_TEMPLATE_PIECES = ("x", "-", " ", "é", GRIN, "<", ">", "\n", ARABIC_ONE, "\\1", "\\2", "\\3", "\\10", "\\11", "\\g<1>", "\\g<2>", "\\g<0>", "\\g<x>", "\\g<y>", "\\g<nope>", "\\g<>", "\\g<1", "\\g<",
                    "\\g<-1>", "\\g< 1>", "\\\\", "\\n", "\\t", "\\r", "\\f", "\\v", "\\a", "\\b", "\\&", "\\.", "\\ ", "\\q", "\\Z", "\\", "\\0", "\\01", "\\012", "\\400", "\\x41", "\\N{DIGIT ONE}",
                    "\\" + "u0041", "\\" + ARABIC_ONE)


def _sub_template_cases() -> list[dict]:
    """re.sub(șablon, text, count) pe SUB_TEMPLATE_CASES combinații la întâmplare de expresie, șablon, text și count; fiecare caz are `out` sau `error` (eroarea lui Python, cu mesaj)."""
    rng = random.Random(CORPUS_SEED + 42)
    cases = []
    for _ in range(SUB_TEMPLATE_CASES):
        source, text, count = _pick(rng, _TEMPLATE_PATTERNS), _pick(rng, _TEMPLATE_TEXTS), _pick(rng, (0, 0, 1, 2))
        template = "".join(_pick(rng, _TEMPLATE_PIECES) for _ in range(_between(rng, 1, 5)))
        cases.append({"pattern": source, "template": template, "text": text, "count": count, **_attempt(re.compile(source).sub, template, text, count)})
    return cases


def _escape_texts() -> list[str]:
    """Texte pentru re.escape: fiecare caracter ASCII tipăribil și de spațiu, plus Unicode (nu se scapă) și șabloane reale."""
    texts = [chr(code) for code in range(32, 127)] + ["\t", "\n", "\r", "\x0b", "\x0c", "", "a b", "a-b", "a_b", "(x)[y]{z}?*+|^$\\.&~# ", "é", GRIN, NBSP, ZWSP, "1.5", "§", "„x”", "≠", "≥",
             "{order_id}", "comanda {order_id}, {seller}: lipsește 'Total platit'", settings.RETURN_LIST_PATH, "Modalitate restituire", "[...]", "...", "…", "a\\b"]
    return texts


def _repr_cases() -> list[dict]:
    """repr() pe text (ghilimele, caractere de control, tipăribile / netipăribile, astrale), liste, None, bool, numere întregi și fracții."""
    strings = ["", "abc", "it's", 'say "hi"', "it's \"x\"", "\\", "\n\r\t", "\x00\x01\x1f\x7f", "é ă ș ț", "\x80\x9f", NBSP, "\xad", ZWSP, BOM, LINE_SEP, GRIN, chr(0x10FFFF), chr(0xE000), chr(0xFFFF),
               chr(0xFFFE), UNASSIGNED, chr(0x378) + "a", chr(0x1F9FF), chr(0xD7FF), chr(0xE0001), chr(0x300), "a" + ACUTE, IDEOGRAPHIC_SPACE, EM_SPACE, THIN_SPACE, "'", '"', "'\"", "\"'",
               "a'b\"c'd", "linie1\nlinie2", "tab\tx", "\x1b[0m", chr(0xA0) + chr(0xA1) + chr(0xFF) + chr(0x100), chr(0x2028) + chr(0x2029), chr(0x61C), chr(0x200E), chr(0x202E), chr(0x2066)]
    values: list = list(strings) + [[], ["a"], ["a", "b'c"], ["x", ["y", "z"]], None, True, False, 0, -5, 12345, [None, True, 3], [[]], {"k": "v"}, {}, {"a": [1, "b"]}]
    return [{"value": value, "out": repr(value)} for value in values]


def _line_outcome_cases() -> list[dict]:
    """Combinații de câmpuri pentru LineOutcome: proprietățile (kept_bani, *_paid_bani, kept_list_bani...) și to_dict, inclusiv căile de rezervă ale lui _parts_of."""
    rng = random.Random(CORPUS_SEED + 5)
    properties = ("returned_bani", "cancelled_bani", "pending_bani", "paid_only_bani", "unknown_bani", "kept_bani", "list_value_bani", "kept_list_bani",
                  "paid_value_bani", "returned_paid_bani", "cancelled_paid_bani", "pending_paid_bani", "paid_only_paid_bani", "unknown_paid_bani", "kept_paid_bani")
    state_fields = ("kept_qty", "returned_qty", "cancelled_qty", "pending_qty", "paid_only_qty", "unknown_qty")
    fixed = [
        dict(qty=1, kept_qty=1, line_total_bani=10000), dict(qty=3, kept_qty=1, returned_qty=1, cancelled_qty=1, line_total_bani=1000),
        dict(qty=3, kept_qty=0, returned_qty=2, cancelled_qty=1, line_total_bani=1), dict(qty=3, returned_qty=2, cancelled_qty=2, line_total_bani=100, paid_total_bani=1),
        dict(qty=2, kept_qty=1, pending_qty=1, line_total_bani=-5000), dict(qty=0, line_total_bani=500), dict(qty=-1, kept_qty=1, line_total_bani=500), dict(qty=1, kept_qty=1, line_total_bani=0),
        dict(qty=4, kept_qty=1, returned_qty=1, cancelled_qty=1, pending_qty=1, line_total_bani=3, paid_total_bani=1), dict(qty=5, unknown_qty=5, line_total_bani=12345),
        dict(qty=2, paid_only_qty=2, line_total_bani=50000), dict(qty=7, kept_qty=2, returned_qty=2, cancelled_qty=2, pending_qty=1, line_total_bani=9999, paid_total_bani=5000),
        dict(qty=6, returned_qty=3, cancelled_qty=3, line_total_bani=99, paid_total_bani=98), dict(qty=1, cancelled_qty=1, line_total_bani=7, paid_total_bani=None),
        dict(qty=3, kept_qty=3, line_total_bani=-1), dict(qty=3, returned_qty=1, kept_qty=1, unknown_qty=1, line_total_bani=-300, paid_total_bani=0),
    ]
    generated = []
    for _ in range(420):
        qty = _between(rng, 0, 8)
        quantities = dict.fromkeys(state_fields, 0)
        left = qty
        for field in state_fields:
            if rng.random() < 0.45 and left > 0:
                take = _between(rng, 1, left)
                quantities[field] = take
                left -= take
        quantities["kept_qty"] += left if rng.random() < 0.8 else 0
        if rng.random() < 0.08:  # invariant încălcat: sume de stări peste cantitate
            quantities[_pick(rng, state_fields)] += _between(rng, 1, 3)
        line_total = _pick(rng, (_between(rng, -20000, 200000), _between(rng, 0, 5), _between(rng, 1, 100) * 100, 99999, 100000, 1))
        paid = _pick(rng, (None, None, 0, max(line_total, 0), max(line_total, 0) // 2, max(line_total, 0) + 1, _between(rng, 0, 200000)))  # niciodată negativă (models.py)
        generated.append({"qty": qty, "line_total_bani": line_total, "paid_total_bani": paid, **quantities,
                          "returned_from_cancelled_qty": _between(rng, 0, 1), "credit_returned_qty": _between(rng, 0, 1)})
    cases = []
    for number, extra in enumerate(fixed + generated):
        fields = {"order_id": f"4890{number:05d}", "placed_at": "2026-05-26T10:07" if number % 5 else None, "seller": "eMAG" if number % 3 else "ALFA SRL",
                  "name": f"Produs {number}", "qty": 1, "line_total_bani": 0, "block_status": block_status.DELIVERED, "category": "Test" if number % 2 else "", "rule": "",
                  "return_ids": [f"30000{number % 7}"] * (number % 3)}
        fields.update(extra)
        line = LineOutcome(**fields)
        cases.append({"fields": fields, "dict": to_dict(line), "properties": {name: getattr(line, name) for name in properties}})
    return cases


def _models_dict_cases() -> list[dict]:
    """order_from_dict / return_from_dict / to_dict / Order.year: dicturi complete, vechi (fără due_bani), cu chei lipsă sau în plus (erori Python)."""
    block = {"seller": "eMAG", "status": "DELIVERED", "status_text": "Produse livrate", "has_storno": False,
             "items": [{"name": "Produs A", "line_total_bani": 1000, "qty": 2}], "products_total_bani": 1000, "vouchers_bani": [-100], "shipping_bani": 0,
             "services_bani": [149], "other_bani": [], "paid_bani": 1049, "due_bani": None}
    order = {"order_id": "489000001", "placed_text": "26 mai 2026, 10:07", "placed_at": "2026-05-26T10:07", "header_total_bani": 1049, "blocks": [block], "warnings": ["w"]}
    old_block = {key: value for key, value in block.items() if key != "due_bani"}
    old_order = {**order, "blocks": [old_block]}
    no_warnings = {key: value for key, value in order.items() if key != "warnings"}
    reverse_keys = {key: order[key] for key in reversed(list(order))}
    bad_year = {**order, "placed_at": "abcd-05-26"}
    no_date = {**order, "placed_at": None}
    ret = {"return_id": "3000001", "detail_path": "/user/return-history/1/3000001", "order_ids": ["489000001"], "product_names": ["Produs A"], "steps": ["Restituire suma"],
           "refund_bani": 1049, "refund_mode": "Vreau banii inapoi", "completed": True, "cancelled": False}
    cases: list[dict] = []
    for name, data in (("comanda", order), ("comanda_veche", old_order), ("fara_avertismente", no_warnings), ("chei_inversate", reverse_keys), ("fara_data", no_date), ("an_gresit", bad_year)):
        parsed = _attempt(order_from_dict, data)
        entry = {"name": name, "kind": "order", "dict": data}
        if "out" in parsed:
            built = parsed["out"]
            entry["out"] = to_dict(built)
            entry["year"] = _attempt(lambda o=built: o.year)
        else:
            entry["error"] = parsed["error"]
        cases.append(entry)
    for name, data in (("fara_blocks", {key: value for key, value in order.items() if key != "blocks"}),
                       ("cheie_in_plus", {**order, "extra": 1}), ("bloc_cu_cheie_in_plus", {**order, "blocks": [{**block, "extra": 2}]}),
                       ("bloc_fara_seller", {**order, "blocks": [{key: value for key, value in block.items() if key != "seller"}]}),
                       ("bloc_fara_items", {**order, "blocks": [{key: value for key, value in block.items() if key != "items"}]}),
                       ("bloc_fara_items_si_seller", {**order, "blocks": [{key: value for key, value in block.items() if key not in ("items", "seller")}]}),
                       ("produs_fara_qty", {**order, "blocks": [{**block, "items": [{"name": "x", "line_total_bani": 1}]}]}),
                       ("bloc_fara_doua", {**order, "blocks": [{key: value for key, value in block.items() if key not in ("seller", "status")}]}),
                       ("fara_trei", {**order, "blocks": [{key: value for key, value in block.items() if key not in ("seller", "status", "status_text")}]})):
        outcome = _attempt(lambda d=data: to_dict(order_from_dict(d)))
        cases.append({"name": name, "kind": "order", "dict": data, **outcome})
    for name, data in (("retur", ret), ("retur_fara_mod", {key: value for key, value in ret.items() if key != "refund_mode"}), ("retur_cheie_in_plus", {**ret, "extra": 1}),
                       ("retur_fara_doua", {key: value for key, value in ret.items() if key not in ("steps", "completed")})):
        outcome = _attempt(lambda d=data: to_dict(return_from_dict(d)))
        cases.append({"name": name, "kind": "return", "dict": data, **outcome})
    return cases


def _primitive_fixture(unicode_tables: dict) -> dict:
    """Toate cazurile de intrare/ieșire Python pentru primitivele din python_compat.js și modulele mici portate."""
    texts = _normalize_texts() + _coverage_texts(unicode_tables)
    rounded, integers = _round_cases()
    formatted = _warning_format_cases()
    return {
        "normalize_text": [{"in": text, "out": text_normalize.normalize_text(text)} for text in texts],
        "ro_amount_to_bani": [{"in": text, **_attempt(money_ro.ro_amount_to_bani, text)} for text in _ro_amount_inputs()],
        "parse_full_amount": [{"in": text, "out": money_ro.parse_full_amount(text)} for text in _amount_texts()],
        "find_amount": [{"in": text, "out": money_ro.find_amount(text)} for text in _amount_texts()],
        "find_last_amount": [{"in": text, "out": money_ro.find_last_amount(text)} for text in _amount_texts()],
        "parse_refund_amount": [{"in": text, "out": money_ro.parse_refund_amount(text)} for text in _refund_texts()],
        "format_lei": [{"in": bani, "out": money_ro.format_lei(bani)} for bani in _format_lei_inputs()],
        "parse_ro_datetime": [{"in": text, "out": dates_ro.parse_ro_datetime(text)} for text in _datetime_texts()],
        "split_proportionally": _split_cases(),
        "round_float": rounded,
        "round_int": integers,
        "percent": _percent_cases(),
        "division": _division_cases(),
        "ordering": _sorted_key_cases(),
        "strip_split": _strip_split_cases(),
        "int": _int_cases(),
        "json": _json_cases(),
        "csv_row": _csv_cases(),
        "classify_status": [{"in": text, "out": block_status.classify_status(text)} for text in _status_texts()],
        "warning_formats": formatted,
        "parse_order_warning": [{"in": text, "out": dataclasses.asdict(warning_messages.parse_order_warning(text))} for text in _warning_parse_texts(formatted)],
        "order_links": _order_links_cases(),
        "escape": [{"in": text, "out": re.escape(text)} for text in _escape_texts()],
        "sub_templates": _sub_template_cases(),
        "repr": _repr_cases(),
        "line_outcome": _line_outcome_cases(),
        "models_dict": _models_dict_cases(),
    }


# =====================================================================================================================
# regex.json: modelele din config/ pe un corpus de nume + expresiile interne ale modulelor, cu toate metodele lui re
# =====================================================================================================================

# Variantele cu care fiecare cuvânt din reguli intră în corpus: lipit de litere, cifre, _ , - , ., separat, cu majuscule, cu litere și cifre non-ASCII, cu semn combinat.
_WORD_VARIANTS = ("{t}", "x{t}", "{t}x", "{t}1", "1{t}", "{t}_", "_{t}", "a {t} b", "{t}-b", "a-{t}", "{t}.b", "{t}s", "{T}", "{t}é", "é{t}", "{t}" + ARABIC_THREE, "{t}" + ACUTE,
                  "{t}\n", "\n{t}", "{t}" + NBSP + "x")
# Texte alese de mână pentru reguli: numere cu procent și volum, ancore, scripturi străine, emoji, spații speciale.
_RULE_TRAPS = (
    "", " ", "4k tv", "tv 4k", "oled tv 55", "smart tv", "norvik tv led", "led  tv", "suport tv perete", "j&b 12", "j&b", "j&bx", "xj&b", "jack daniel's", "jack daniels", "johnnie walker black",
    "whisky 40% 0.7l", "40%, 0.7l", "12,5 % 700 ml", "0.7 l, 40%", "vin 12%", "sticla 0,75 l 13 %", "7l 40%", "40% 70 cl", "40 % 1l", "5% 330ml", "5,2%, 0,33 l", "0.7l 40%",
    ARABIC_ONE + ARABIC_TWO + "% 0." + ARABIC_THREE + " l", "cost transport", "cost transport\n", "\ncost transport", "cost transport ", "custom discount", "custom discount\n", "pachet", "pachet\n",
    "pachet: x", "garantie electronica", "ghidul utilizatorului", "licenta electronica", "licenta software x", "card cadou", "gift card", "voucher 50 lei", "asigurare rca", "asigurari",
    "ром", "ВИСКИ", "виски", "日本酒 sake", "sake日本", "ｗｈｉｓｋｙ", "wh" + chr(0x456) + "sky", "wh1sky", "whisky", "whiskey", "wiskey", "gin" + GRIN, GRIN + "gin", GRIN + " gin " + GRIN, "gin\tx", "gin" + NBSP + "tonic",
    "gin" + LINE_SEP, "begin", "gin_", "_gin", "gin5", "5gin", "ginger", "gin-tonic", "rom", "rum", "from", "drum", "romania", "vinuri", "vinil", "vin", "bere", "berea", "sake", "sakura",
    "absolut", "absolute", "campari", "baileys", "jameson", "smirnoff", "alcool sanitar", "alcool izopropilic", "fara alcool", "set pahare", "pahar vin", "cana bere", "racitor vin",
    "televizor", "televizoare", "televizorul", "smart tv suport", "tv box", "cablu hdmi tv", "antena tv", "telecomanda televizor", "led tv", "qled tv", "tv led", "tv smart", "4k tv led",
    "x" * 300, "a b c " * 60, "whisky" * 20,
)


def _rule_sources() -> list[dict]:
    """Toate modelele din config/categorii.json și din config/categorii.personal.exemplu.json (NU din fișierul personal): patterns și exclude, cu categoria lor."""
    rules = []
    for file_name in ("categorii.json", "categorii.personal.exemplu.json"):
        data = json.loads((CONFIG_DIR / file_name).read_text(encoding="utf-8"))
        for category in data["categories"]:
            for kind in ("patterns", "exclude"):
                for source in category.get(kind, []):
                    rules.append({"fisier": file_name, "categorie": category["name"], "tip": kind, "model": source})
    return rules


def _regex_corpus(rules: list[dict]) -> list[str]:
    """Cel puțin 300 de nume normalizate (catalogul demonstrativ) și capcane: fiecare cuvânt din reguli în variante lipite, separate, cu Unicode, plus texte alese de mână."""
    names = _catalog_names()
    corpus = [text_normalize.normalize_text(name) for name in names] + [name.lower() for name in names]
    words = sorted({word for rule in rules for word in re.findall(r"[a-z]{3,}", re.sub(r"\\[a-zA-Z]", " ", rule["model"]))})
    for word in words:
        corpus.extend(variant.format(t=word, T=word.upper()) for variant in _WORD_VARIANTS)
    corpus.extend(_RULE_TRAPS)
    return list(dict.fromkeys(corpus))


# Textele comune ale expresiilor interne: sume, antete, date, etichete, numere, spații speciale, litere din grupul I/İ/ı și texte care nu seamănă cu nimic.
_INTERNAL_TEXT_POOL = (
    "", " ", "a", "123", "12,34", "12,34 Lei", "1.449,27 Lei", "-34,00 Lei", "105,99 Lei 1 buc", "105,99 Lei 2 buc.", "-5,00 Lei 3 buc", "1.234,56 lei  10 BUC", "2 buc", "2 buc.", "2buc", "2 BUC", "10 Buc.",
    "Comanda nr. 489000001", "Comanda nr 489000001", "COMANDA NR. 12", "comanda nr.12", "Comanda nr.  34 x", "  Comanda nr. 5", "Comandă nr. 5", "Comanda nr. " + ARABIC_ONE + ARABIC_TWO,
    "Plasata pe: 26 mai 2026, 10:07 Total: 190,47 Lei", "Plasata pe: 26 mai 2026, 10:07", "plasata pe: 3 sep 2026 total: 1,00 lei", "Plasata pe:", "Plasata pe: Total: 1,00 Lei", "Plasata pe: 5 oct 2026, 1:07 Total:  -3,00  Lei y",
    "Total: 190,47 Lei", "Total:190,47Lei", "TOTAL: 10,00 LEI", "Total: 10,00 LE" + DOTTED_CAPITAL_I, "total: 10,00 le" + DOTLESS_SMALL_I, "Total: 1.234.567,89 Lei", "Total: -0,00 Lei", "Total: 12,3 Lei",
    "Produse vandute si livrate de eMAG", "Produse vandute de ALFA SRL si livrate de eMAG", "produse vandute de x si livrate de emag", "Produse vandute si livrate de Firma, cu virgula", "PRODUSE VANDUTE SI LIVRATE DE EMAG",
    "Produse vandute de ALFA SRL si livrate de eMAG Asigurari", "Produse vandute de si livrate de eMAG", "Produse vandute si livrate de ", "Produse vandute de A si livrate de eMAG si livrate de eMAG", "Produse vandute si livrate de x\n",
    "Retur #777", "Retur#12", "retur  # 12", "RETUR #1", "Retur #", "Retur #abc", "Retur #" + ARABIC_ONE, "Retur # 5",
    "Suma de 93.59 RON a pornit spre contul tau.", "Suma de 129 RON", "suma de1.449,27 lei", "Suma de 12,5 Lei x", "Suma de RON", "Suma de .. RON", "SUMA DE 5 ron", "Suma de 1,2.3 Lei", "Suma de 7 LE" + DOTTED_CAPITAL_I,
    "Data: 1 Iulie, 13:44", "Cerere inregistrata Data: 1 Iulie, 13:44", "data: 12 ian 2026", "Data:1 Mai", "Data: 1  Mai x | y", "Data: 1 " + DOTTED_CAPITAL_I + "yul", "Data: 12 Septembrie 2026, 10:00 | alt",
    "Data: 3 " + S_CEDILLA + "ep", "Data: 3 sep" + T_CEDILLA + "x", "Data: 3 " + chr(0x219) + "ep", "Data: 7 K" + KELVIN + "x", "Data: 7 " + chr(0x17F) + "ep", "Data: 7 ", "Data: x Mai",
    "#489000010 Produs vandut de eMAG #489000011", "#1234", "#12345", "#123456789", "x#12345y", "##12345", "# 12345", "#" + ARABIC_ONE * 6,
    "produs [...]", "produs ...", "produs …", "produs [...] ", "produs  ...  ", "[...]", "...", "…", "a [...] b [...]", "a...b...", "nume lung truncat [...]", "produs [...]\n", "produs" + NBSP + "...",
    "2026-05-26", "2026-5-26", "0000-00-00", "20260526", "2026-05-26x", "x2026-05-26", "2026-05-26\n", "٢٠٢٦-٠٥-٢٦",
    "/user/return-history/1/3000001", "/user/return-history/1/3000001/", "/user/return-history/12/489000001x", "/user/return-history//3000001", "/user/return-history/1/30", "/user/return-history/a/3000001",
    "489000001", "12", "123", "123456789012345", "1234567890123456", ARABIC_ONE + ARABIC_TWO + ARABIC_THREE, "123 ", " 123", "123\n", "0123",
    "a  b", "a\tb\nc", "a" + NBSP + "b", "a" + NEL + "b", "a" + IDEOGRAPHIC_SPACE + "b", "a" + FS + "b", "a" + BOM + "b", "\n", "  ", "x" * 5, "Ab Cd Ef",
    "foo_bar baz9 é_1 ²x", "hello world", T_CEDILLA_UP + "elină", "ȘAMPON anticădere", "gin tonic", "e" + ACUTE + "x", "a" + GRIN + "b", GRIN, "12" + GRIN + "34",
    "comanda 489000001, eMAG: lipsește 'Total platit'", "comanda 489000001, ALFA: SRL: lipsește 'Total platit'", "comanda 489000001, eMAG: niciun produs găsit", "comanda 489000001: ceva",
    "status necunoscut la comanda 489000001 (eMAG): 'x'", "status necunoscut la comanda 489000001 (A (B)): ''", "retur 3000001: nu are produse listate", "retur 3000001: ", "retur x: y",
    "1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat", "12 retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate",
    "1 retur finalizat fără sumă restituită afișată", "3 retururi finalizate fără sumă restituită afișată", "1 comandă la care totalul din antet ≠ suma blocurilor", "4 comenzi la care totalul din antet ≠ suma blocurilor",
    "Modalitate restituire: Emitere voucher", "Modalitate restituire", "  modalitate  restituire :  x", "MODALITATE RESTITUIRE Vreau banii inapoi", "Modalitate restituire:\n", "Modalitate",
)
_INTERNAL_EXPRESSIONS = (
    ("text_normalize", "_SPACES"), ("html_lines", "_SPACES"), ("money_ro", "_RO_AMOUNT"), ("money_ro", "_RO_AMOUNT_FULL"), ("money_ro", "_RO_AMOUNT_ANY"), ("dates_ro", "_DATE_RE"),
    ("order_parser", "_ORDER_HEADER"), ("order_parser", "_SELLER_HEADER"), ("order_parser", "_QTY"), ("order_parser", "_PRICE_AND_QTY"), ("order_parser", "_PLACED"), ("order_parser", "_HEADER_TOTAL"),
    ("return_parser", "_RETURN_HEADER"), ("return_parser", "_REFUND"), ("return_parser", "_ORDER_REF"), ("return_parser", "_STEP_DATE_ANYWHERE"), ("return_matcher", "_TRUNCATION_MARKER"),
    ("product_key", "_WORD"), ("warning_details", "_ISO_DAY"), ("order_links", "_ORDER_ID"), ("order_links", "_RETURN_PATH"), ("warning_messages", "_MISSING_PAID_TOTAL_RE"),
    ("warning_messages", "_UNKNOWN_STATUS_RE"), ("warning_messages", "_ORDER_SELLER_RE"), ("warning_messages", "_ORDER_RE"), ("warning_messages", "_RETURN_RE"),
    ("warning_messages", "_PENDING_RETURNS_RE"), ("warning_messages", "_REFUNDS_WITHOUT_AMOUNT_RE"), ("warning_messages", "_HEADER_MISMATCH_RE"),
)
# Expresiile scrise direct în funcții (nu există ca atribute de modul): copiate aici, cu locul din care vin.
_INLINE_EXPRESSIONS = (
    ("money_ro.parse_refund_amount (mii)", r"\d{1,3}(?:\.\d{3})+", 0),
    ("money_ro.parse_refund_amount (zecimale)", r"\d+(?:\.\d{1,2})?", 0),
    ("order_parser._amount_for_label (cuvânt)", r"\w", 0),
    ("return_parser._value_after_label (Modalitate restituire)", r"^\s*" + re.escape("Modalitate restituire") + r"\s*:?\s*", re.IGNORECASE),
    ("return_parser._value_after_label (Detalii comanda)", r"^\s*" + re.escape("Detalii comanda") + r"\s*:?\s*", re.IGNORECASE),
)
# Construcții valide în Python pe care portul le refuză (UnsupportedPattern); generatorul verifică doar că Python le acceptă. Numele construcției e verificat în testul unitar.
_REFUSED_SOURCES = (
    ("(?i)a", False), ("(?i:a)", False), ("(?s)a", False), ("(?-i:a)", False), ("(?x) a", False), ("(?a)a", False), ("(?<=a)b", False), ("(?<!a)b", False), ("\\Aa", False), ("a\\Z", False),
    ("(a)\\1", False), ("(?#c)a", False), ("(?>a)", False), ("a*+", False), ("a++", False), ("a?+", False), ("a{1,2}+", False), ("(a)(?(1)b|c)", False), ("\\N{DIGIT ONE}", False),
    ("\\0", False), ("\\012", False), ("(?=a)*", False), ("(?:(a)|b)+", False), ("(?:(a)|b){2}", False), ("(?:(a)|b){1,2}", False), ("(?:(a)|b){,2}?", False), ("(a*)*", False), ("(?P<x>a)?(?P=x)", False), ("(?:(?P<x>a)|b)(?P=x)", False), ("(?!(?P<x>a))(?P=x)", False), ("()+", False),
    ("(a*)?", False), ("(\\B){0,1}x", False), ("(a|)+", False), ("(?:|a)+", False), ("(?:|a)*", False), ("(?:x*|a)+", False), ("(?:|a)?", False), ("(?:|a){0,1}", False), ("(?:|a)+?", False),
    ("\\w", True), ("\\W", True), ("\\b", True), ("\\B", True), ("[\\w]", True), ("[^\\W]", True), ("a\\b", True), ("(?:x|\\w+)", True),
)
_INVALID_SOURCES = (
    "(", ")", "a)", "(a", "[", "[a", "[z-a]", "a**", "*a", "+", "?", "{1}", "a{2,1}", "\\q", "(?P<n", "(?P<1a>x)", "(?Px)", "(?P=zz)", "(?P<n>a)(?P<n>b)", "(?<n>a)", "(?z)", "\\", "[\\d-a]",
    "a{1,2}{3}", "(?:", "x|*", "^*", "$+", "\\b*", "(?P>x)", "(?P<>x)", "(?P=)", "(?P<n>", "(?", "(?P", "[a-", "\\xz", "\\x4", "\\u12", "\\U0011ffff", "(?=a", "(?!", "\\8", "(\\2)",
    "(?P<a>(?P=a))", "a|*b", "(*)", "a**?", "a*??", "(?i", "(?#x", "a\n(", "ab\n\n(?P<", "[\\d-\\w]", "[b-a]", "x{3,2}", "(?P<9>)", "\\i", "\\y", "[\\B]", "[\\A]",
)


def _match_info(match) -> dict | None:
    """Potrivirea ca date: intervalul (în puncte de cod, ca în Python), grupurile (None pentru cele fără participare) și grupurile cu nume."""
    return None if match is None else {"span": list(match.span()), "groups": list(match.groups()), "groupdict": match.groupdict()}


def _expression_report(name: str, pattern: re.Pattern, extra_texts: tuple[str, ...] = ()) -> dict:
    """Pentru o expresie internă: sursa, steagurile și, pe fiecare text, rezultatul fiecărei metode a lui re (search, match, fullmatch, findall, finditer, sub, split)."""
    assert pattern.flags & ~(re.IGNORECASE | re.DOTALL | re.UNICODE) == 0, f"{name}: steaguri neacoperite de port: {pattern.flags}"
    texts = []
    for text in dict.fromkeys(_INTERNAL_TEXT_POOL + extra_texts):
        texts.append({
            "text": text,
            "search": _match_info(pattern.search(text)),
            "match": _match_info(pattern.match(text)),
            "fullmatch": _match_info(pattern.fullmatch(text)),
            "findall": pattern.findall(text),
            "finditer": [_match_info(match) for match in pattern.finditer(text)],
            "sub_spatiu": pattern.sub(" ", text),
            "sub_gol_unu": pattern.sub("", text, 1),
            "split": pattern.split(text),
        })
    return {"nume": name, "sursa": pattern.pattern, "ignore_case": bool(pattern.flags & re.IGNORECASE), "dot_all": bool(pattern.flags & re.DOTALL), "texte": texts}


def _regex_fixture() -> dict:
    """regex.json: modelele de reguli pe corpus, expresiile interne ale modulelor, expresiile invalide (mesajul re.error) și cele refuzate de port."""
    import importlib

    rules = _rule_sources()
    corpus = _regex_corpus(rules)
    for rule in rules:
        compiled = re.compile(rule["model"])
        rule["potriviri"] = [index for index, text in enumerate(corpus) if compiled.search(text)]
    internal = []
    for module_name, attribute in _INTERNAL_EXPRESSIONS:
        value = getattr(importlib.import_module(f"emag_spend.{module_name}"), attribute)
        patterns = value if isinstance(value, tuple) else (value,)
        for index, pattern in enumerate(patterns):
            compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
            suffix = f"[{index}]" if isinstance(value, tuple) else ""
            internal.append(_expression_report(f"{module_name}.{attribute}{suffix}", compiled))
    for name, source, flags in _INLINE_EXPRESSIONS:
        internal.append(_expression_report(name, re.compile(source, flags)))
    invalid = []
    for source in _INVALID_SOURCES:
        try:
            re.compile(source)
        except re.error as error:
            invalid.append({"sursa": source, "mesaj": str(error)})
        else:
            raise AssertionError(f"{source!r} ar trebui să fie invalidă în Python")
    refused = []
    for source, ignore_case in _REFUSED_SOURCES:
        re.compile(source, re.IGNORECASE if ignore_case else 0)  # trebuie să fie validă în Python
        refused.append({"sursa": source, "ignore_case": ignore_case})
    return {"corpus": corpus, "modele": rules, "interne": internal, "invalide": invalid, "refuzate": refused}


# =====================================================================================================================
# regex_aleatoare.json: expresii regulate generate la întâmplare (sămânță fixă) și rezultatele lui re pe texte la întâmplare
# =====================================================================================================================

# Câte expresii se generează (inclusiv cele invalide în Python, care probează mesajele de eroare) și pe câte texte se rulează fiecare. Destule cât să prindă clase de diferențe
# pe care corpusul scris de mână nu le atinge (a prins deja două: potriviri goale la mijlocul unei perechi surogat și corpuri de repetiție care pot fi goale), puține cât
# să rămână fișierul mic. Se scrie compact, fără indentare: sunt mii de rezultate scurte.
RANDOM_REGEX_COUNT = 1600
RANDOM_REGEX_TEXTS = 4
# Adâncimea maximă a grupurilor imbricate, elementele dintr-o secvență și lungimea textelor: expresii destul de bogate, nu monștri care încetinesc Python sau JavaScript.
RANDOM_REGEX_MAX_DEPTH = 3
RANDOM_REGEX_MAX_ITEMS = 4
RANDOM_REGEX_MAX_TEXT_LENGTH = 12
# Șansele (între 0 și 1) ca un element să primească cuantificator, ca acesta să fie leneș, ca o alternanță să aibă mai multe ramuri și ca o ramură să fie goală
# (corpurile de repetiție care pot fi goale au dat diferențe între Python și JavaScript).
RANDOM_REGEX_QUANTIFIER_CHANCE = 0.35
RANDOM_REGEX_LAZY_CHANCE = 0.3
RANDOM_REGEX_ALTERNATION_CHANCE = 0.35
RANDOM_REGEX_EMPTY_BRANCH_CHANCE = 0.08
# Șansa ca o literă din expresie să fie scrisă ca escape numeric (\xhh, \uhhhh, \Uhhhhhhhh, \n): portul le traduce separat de literele simple.
RANDOM_REGEX_ESCAPE_CHANCE = 0.15
# Cel puțin atâtea expresii trebuie să fie invalide în Python și cel puțin atâtea valide, altfel generatorul s-a dereglat și fișierul n-ar mai proba mesajele de eroare sau potrivirile.
RANDOM_REGEX_MIN_PER_KIND = 200
# Literele din expresii și texte: ASCII (literele a, b, x se repetă ca potrivirile să fie dese), cifre, spațiu, cratimă, linie nouă, litere cu diacritice și din grupul I/İ/ı,
# ß, o cifră arabă, un emoji (pereche surogat) și un semn combinant.
RANDOM_REGEX_ALPHABET = ("a", "b", "c", "A", "B", "x", "x", "1", "2", "_", " ", "-", "\n", "é", SHARP_S, DOTTED_CAPITAL_I, DOTLESS_SMALL_I, ARABIC_THREE, GRIN, ACUTE)
_RANDOM_CLASS_ESCAPES = ("\\d", "\\D", "\\w", "\\W", "\\s", "\\S")
_RANDOM_QUANTIFIERS = ("*", "+", "?", "{2}", "{1,3}", "{,2}", "{2,}", "{0}", "{0,1}", "{3,3}")
_RANDOM_RANGE_ENDS = {"a": "c", "A": "C", "0": "3", "é": chr(0xFF)}
_RANDOM_FLAGS = (0, 0, re.IGNORECASE, re.DOTALL, re.IGNORECASE | re.DOTALL)
_RANDOM_TEMPLATE = "<\\g<0>>"  # înlocuirea probată la sub: referință la tot textul potrivit


class _RegexFuzzer:
    """Generează expresii regulate Python la întâmplare (doar rng.random(), vezi CORPUS_SEED) din literă, `.`, clase, paranteze, grupuri cu și fără nume, lookahead, referințe, ancore, alternanțe și cuantificatori."""

    def __init__(self, rng: random.Random):
        """`rng` e singura sursă de hazard; `names` ține numele grupurilor deja închise, ca referințele (?P=nume) să arate spre grupuri care există."""
        self.rng = rng
        self.names: list[str] = []

    def source(self) -> str:
        """O expresie nouă, cu grupuri imbricate până la RANDOM_REGEX_MAX_DEPTH adâncime."""
        self.names = []
        return self._alternation(_between(self.rng, 1, RANDOM_REGEX_MAX_DEPTH))

    def _numeric_escape(self, char: str) -> str:
        """Aceeași literă scrisă ca escape Python: \\n pentru linia nouă (uneori), altfel \\xhh, \\uhhhh sau \\Uhhhhhhhh după mărimea punctului de cod."""
        code = ord(char)
        if char == "\n" and self.rng.random() < 0.5:
            return "\\n"
        if code < 0x100 and self.rng.random() < 0.5:
            return "\\x%02x" % code
        if code < 0x10000 and self.rng.random() < 0.7:
            return "\\u%04x" % code
        return "\\U%08x" % code

    def _literal(self) -> str:
        """O literă din alfabet, scrisă simplu (cu re.escape) sau, uneori, ca escape numeric."""
        char = _pick(self.rng, RANDOM_REGEX_ALPHABET)
        return self._numeric_escape(char) if self.rng.random() < RANDOM_REGEX_ESCAPE_CHANCE else re.escape(char)

    def _bracket(self) -> str:
        """O clasă de caractere cu 1-3 părți: literă, interval sau clasă (\\d, \\w, \\s și negatele lor); `^` inițial în 30% din cazuri."""
        parts = []
        for _ in range(_between(self.rng, 1, 3)):
            roll = self.rng.random()
            if roll < 0.45:
                char = _pick(self.rng, RANDOM_REGEX_ALPHABET)
                if self.rng.random() < RANDOM_REGEX_ESCAPE_CHANCE:
                    parts.append(self._numeric_escape(char))
                else:
                    parts.append("\\" + char if char in "\\]^-[" else re.escape(char) if char in " \n" else char)
            elif roll < 0.70:
                low = _pick(self.rng, tuple(_RANDOM_RANGE_ENDS))
                parts.append(f"{low}-{_RANDOM_RANGE_ENDS[low]}")
            else:
                parts.append(_pick(self.rng, _RANDOM_CLASS_ESCAPES))
        return "[" + ("^" if self.rng.random() < 0.3 else "") + "".join(parts) + "]"

    def _atom(self, depth: int) -> str:
        """Un element fără cuantificator: literă, `.`, clasă, ancoră sau (cât `depth` e pozitiv) paranteză, grup, lookahead ori referință la un grup."""
        roll = self.rng.random()
        if roll < 0.28:
            return self._literal()
        if roll < 0.35:
            return "."
        if roll < 0.48:
            return _pick(self.rng, _RANDOM_CLASS_ESCAPES)
        if roll < 0.60:
            return self._bracket()
        if roll < 0.66:
            return _pick(self.rng, ("^", "$", "\\b", "\\B"))
        if depth <= 0:
            return self._literal()
        if roll < 0.76:
            return "(" + self._alternation(depth - 1) + ")"
        if roll < 0.82:
            return "(?:" + self._alternation(depth - 1) + ")"
        if roll < 0.87:
            name = f"g{len(self.names) + 1}"
            inner = self._alternation(depth - 1)  # numele intră în listă abia după corp: grupul nu se poate referi pe sine
            self.names.append(name)
            return f"(?P<{name}>{inner})"
        if roll < 0.92:
            return "(?=" + self._alternation(depth - 1) + ")"
        if roll < 0.96:
            return "(?!" + self._alternation(depth - 1) + ")"
        return f"(?P={_pick(self.rng, self.names)})" if self.names else self._literal()

    def _item(self, depth: int) -> str:
        """Un element, uneori urmat de un cuantificator (și de `?` pentru varianta leneșă)."""
        text = self._atom(depth)
        if self.rng.random() < RANDOM_REGEX_QUANTIFIER_CHANCE:
            text += _pick(self.rng, _RANDOM_QUANTIFIERS)
            if self.rng.random() < RANDOM_REGEX_LAZY_CHANCE:
                text += "?"
        return text

    def _sequence(self, depth: int) -> str:
        """Între 1 și RANDOM_REGEX_MAX_ITEMS elemente lipite."""
        return "".join(self._item(depth) for _ in range(_between(self.rng, 1, RANDOM_REGEX_MAX_ITEMS)))

    def _alternation(self, depth: int) -> str:
        """Una sau mai multe secvențe separate prin `|`; uneori o ramură e goală (corpuri de repetiție care pot potrivi textul gol)."""
        branches = _between(self.rng, 2, 3) if self.rng.random() < RANDOM_REGEX_ALTERNATION_CHANCE else 1
        return "|".join("" if self.rng.random() < RANDOM_REGEX_EMPTY_BRANCH_CHANCE else self._sequence(depth) for _ in range(branches))


def _random_regex_results(pattern: re.Pattern, text: str) -> dict:
    """Rezultatele lui re pe `text`: search, match, fullmatch, findall, finditer (cu grupuri), sub cu «<\\g<0>>» și split."""
    return {
        "text": text, "search": _match_info(pattern.search(text)), "match": _match_info(pattern.match(text)), "fullmatch": _match_info(pattern.fullmatch(text)),
        "findall": pattern.findall(text), "finditer": [_match_info(match) for match in pattern.finditer(text)], "sub": pattern.sub(_RANDOM_TEMPLATE, text), "sub_unu": pattern.sub(_RANDOM_TEMPLATE, text, 1), "split": pattern.split(text),
        "split_unu": pattern.split(text, 1), "split_doi": pattern.split(text, 2),
    }


def _random_regex_fixture() -> dict:
    """regex_aleatoare.json: expresii generate la întâmplare cu steaguri la întâmplare, cu rezultatele lui re pe texte la întâmplare; cele invalide în Python poartă mesajul re.error."""
    rng = random.Random(CORPUS_SEED + 21)  # +20 îl folosește deja generatorul de variante stricate ale paginilor
    fuzzer = _RegexFuzzer(rng)
    cases: list[dict] = []
    seen: set = set()
    while len(cases) < RANDOM_REGEX_COUNT:
        source, flags = fuzzer.source(), _pick(rng, _RANDOM_FLAGS)
        if (source, flags) in seen:
            continue
        seen.add((source, flags))
        entry: dict = {"sursa": source, "ignore_case": bool(flags & re.IGNORECASE), "dot_all": bool(flags & re.DOTALL)}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")  # un FutureWarning (set imbricat, diferență de seturi) arată o expresie ambiguă și în Python: se sare peste ea
                pattern = re.compile(source, flags)
        except re.error as error:
            entry["eroare"] = str(error)
            cases.append(entry)
            continue
        except Warning:
            continue
        entry["texte"] = [_random_regex_results(pattern, "".join(_pick(rng, RANDOM_REGEX_ALPHABET) for _ in range(_between(rng, 0, RANDOM_REGEX_MAX_TEXT_LENGTH))))
                          for _ in range(RANDOM_REGEX_TEXTS)]
        cases.append(entry)
    invalid = sum(1 for case in cases if "eroare" in case)
    assert invalid >= RANDOM_REGEX_MIN_PER_KIND and len(cases) - invalid >= RANDOM_REGEX_MIN_PER_KIND, f"generatorul de expresii s-a dereglat: {invalid} invalide din {len(cases)}"
    return {"sablon": _RANDOM_TEMPLATE, "cazuri": cases}


# =====================================================================================================================
# difflib.json: SequenceMatcher pe perechi de nume și get_close_matches
# =====================================================================================================================

# Câte perechi de șiruri la întâmplare se adaugă la cele din nume: alfabet mic și lungimi în jurul pragului 200 de la care pornește „autojunk”, deci potriviri lungi,
# elemente populare scoase din potrivire și perechi aproape identice, pe care numele reale (alfabet mare, texte scurte) nu le produc.
DIFFLIB_RANDOM_PAIRS = 500


def _random_difflib_pairs() -> list[tuple[str, str]]:
    """Perechi (a, b) la întâmplare: alfabet de 1-8 litere, lungimi alese dintre 10, 30, 120, 260 și 420; în 40% din cazuri b e a cu câteva litere schimbate și fără primele caractere."""
    rng = random.Random(CORPUS_SEED + 39)
    pairs = []
    for _ in range(DIFFLIB_RANDOM_PAIRS):
        alphabet = "abcdefgh"[: _between(rng, 1, 8)]
        length_a, length_b = (int(rng.random() * _pick(rng, (10, 30, 120, 260, 420))) for _ in range(2))
        a = "".join(_pick(rng, alphabet) for _ in range(length_a))
        if rng.random() < 0.4 and a:
            chars = list(a)
            for _ in range(_between(rng, 0, 5)):
                chars[_between(rng, 0, len(chars) - 1)] = _pick(rng, alphabet)
            b = "".join(chars)[_between(rng, 0, 3):]
        else:
            b = "".join(_pick(rng, alphabet) for _ in range(length_b))
        pairs.append((a, b))
    return pairs


def _difflib_pairs(names: list[str]) -> list[tuple[str, str]]:
    """Cel puțin 2.000 de perechi: toate perechile dintr-un eșantion de nume, variante (litera schimbată, coada tăiată, „[...]”, cuvinte inversate), șiruri peste 200 de caractere (autojunk) și cazuri speciale."""
    rng = random.Random(CORPUS_SEED + 10)
    normalized = [text_normalize.normalize_text(name) for name in names]
    mixed = [name if index % 2 == 0 else normalized[index] for index, name in enumerate(names)]
    sample = mixed[: min(len(mixed), 72)]
    pairs = [(sample[i], sample[j]) for i in range(len(sample)) for j in range(i + 1, len(sample))]
    for index in range(0, len(mixed), 2):
        name = mixed[index]
        words = name.split()
        position = _between(rng, 0, max(len(name) - 1, 0))
        pairs += [
            (name, name[:position] + "#" + name[position + 1:]), (name, name + " extra"), (name, name[: max(len(name) // 2, 1)]), (normalized[index], normalized[index][: max(len(name) - 8, 4)] + " [...]"),
            (name, " ".join(reversed(words))), (name, name.upper()), (normalized[index], normalized[index].replace(" ", "")), (name[: len(name) // 2], name[len(name) // 3:]),
        ]
    longs = []
    for start in range(0, max(len(mixed) - 6, 1), 3):
        longs.append(", ".join(mixed[start:start + 6]))  # șase nume lipite depășesc 200 de caractere, pragul de la care pornește „autojunk”
    for index, long_text in enumerate(longs):
        pairs += [(mixed[index % len(mixed)], long_text), (long_text, long_text[:150] + long_text[160:]), (long_text, longs[(index + 1) % len(longs)]),
                  (long_text.upper(), long_text), (long_text, mixed[(index * 7) % len(mixed)])]
    for count in (190, 199, 200, 201, 250, 400):  # în jurul pragului 200 de la care pornește „autojunk”
        pairs += [("ab" * (count // 2), "ba" * (count // 2)), ("a" * count + "b", "a" * count + "c"), ("x" + "yz" * (count // 2), "yz" * (count // 2) + "w"), (" ".join(["cuvant"] * (count // 7)), " ".join(["cuvant"] * (count // 7)) + " altul")]
    pairs += [("", ""), ("a", ""), ("", "a"), ("a", "a"), ("ab", "ba"), ("abcd", "bcde"), ("aaaa", "aaab"), ("abab", "baba"), ("a" * 10, "a" * 20), (GRIN, GRIN), (GRIN + "a" + GRIN + "b", "a" + GRIN + "b"),
              ("é", "e" + ACUTE), ("ß", "ss"), ("ăâîșț", "aaist"), (GRIN * 5, GRIN * 3), ("a" + GRIN * 120 + "b", GRIN * 120), ("Ab", "aB"), ("televizor 43", "televizor 55"), ("televizor 43 inch", "televizor 43 inch smart")]
    pairs += _random_difflib_pairs()
    assert sum(1 for a, b in pairs if len(a) > 200 or len(b) > 200) >= 20, "prea puține perechi care pornesc autojunk"
    assert len(pairs) >= 2000
    return pairs


# Scenarii pentru get_matching_blocks cu find_longest_match scriptat (coada de regiuni și unirea blocurilor adiacente): cu isjunk = None și un find_longest_match real
# blocurile nu ies niciodată adiacente (extinderea la capete le unește), deci unirea lor se poate proba doar cu răspunsuri date din afară.
SCRIPTED_BLOCK_CASES = 400
# Din ele, cel puțin atâtea trebuie să aibă blocuri care se unesc, altfel testul n-ar atinge ramura de unire.
SCRIPTED_MIN_MERGED = 60
# Lungimea maximă a secvențelor scriptate: mică, ca regiunile să se atingă des; conținutul nu contează, răspunsurile vin din tabel.
SCRIPTED_MAX_LENGTH = 24
# Șansa ca o regiune să nu aibă niciun bloc și șansele ca blocul să se lipească de începutul sau de sfârșitul regiunii (locurile unde blocurile devin adiacente).
SCRIPTED_NO_MATCH_CHANCE = 0.15
SCRIPTED_START_CHANCE = 0.3
SCRIPTED_END_CHANCE = 0.3


class _ScriptedMatcher(difflib.SequenceMatcher):
    """SequenceMatcher al cărui find_longest_match răspunde din hazard cu sămânță fixă și își notează răspunsurile, ca tabelul să-l poată relua portul JS."""

    def __init__(self, rng: random.Random, a: str, b: str):
        """Secvențele `a` și `b` (conținutul lor nu contează, doar lungimea) și sursa de hazard a răspunsurilor."""
        super().__init__(None, a, b)
        self._rng = rng
        self.script: list[list[int]] = []

    def find_longest_match(self, alo=0, ahi=None, blo=0, bhi=None):
        """Un bloc (i, j, k) în regiune sau unul gol (alo, blo, 0); regiunea și răspunsul se notează în `script`."""
        width_a, width_b = ahi - alo, bhi - blo
        longest = min(width_a, width_b)
        if longest == 0 or self._rng.random() < SCRIPTED_NO_MATCH_CHANCE:
            answer = (alo, blo, 0)
        else:
            size = _between(self._rng, 1, longest)
            i, j = alo + _between(self._rng, 0, width_a - size), blo + _between(self._rng, 0, width_b - size)
            corner = self._rng.random()
            if corner < SCRIPTED_START_CHANCE:
                i, j = alo, blo
            elif corner < SCRIPTED_START_CHANCE + SCRIPTED_END_CHANCE:
                i, j = ahi - size, bhi - size
            answer = (i, j, size)
        self.script.append([alo, ahi, blo, bhi, *answer])
        return difflib.Match(*answer)


def _scripted_block_cases() -> list[dict]:
    """Scenarii get_matching_blocks cu răspunsurile lui find_longest_match date dintr-un tabel: lungimile secvențelor, tabelul (regiune -> bloc) și blocurile din Python."""
    rng = random.Random(CORPUS_SEED + 12)
    cases = []
    for _ in range(SCRIPTED_BLOCK_CASES):
        length_a, length_b = _between(rng, 0, SCRIPTED_MAX_LENGTH), _between(rng, 0, SCRIPTED_MAX_LENGTH)
        matcher = _ScriptedMatcher(rng, "a" * length_a, "b" * length_b)
        blocks = [list(block) for block in matcher.get_matching_blocks()]
        raw_blocks = sum(1 for entry in matcher.script if entry[6] > 0)
        cases.append({"lungime_a": length_a, "lungime_b": length_b, "tabel": matcher.script, "blocuri": blocks, "unite": raw_blocks > len(blocks) - 1})
    assert sum(1 for case in cases if case["unite"]) >= SCRIPTED_MIN_MERGED, "prea puține scenarii în care blocurile adiacente se unesc"
    return cases


def _difflib_fixture() -> dict:
    """difflib.json: ratio, quick_ratio, real_quick_ratio și blocurile potrivite pe fiecare pereche, apeluri get_close_matches (n, cutoff și lista de candidați) și scenarii scriptate."""
    names = _catalog_names()
    pairs = _difflib_pairs(names)
    records = []
    for a, b in pairs:
        matcher = difflib.SequenceMatcher(None, a, b)
        records.append({"a": a, "b": b, "ratio": matcher.ratio(), "quick_ratio": matcher.quick_ratio(), "real_quick_ratio": matcher.real_quick_ratio(),
                        "blocuri": [list(block) for block in matcher.get_matching_blocks()]})
    rng = random.Random(CORPUS_SEED + 11)
    normalized = [text_normalize.normalize_text(name) for name in names]
    calls = []
    for index, word in enumerate(normalized):
        near = [name for name in normalized if name != word and name[:6] == word[:6]]
        variants = [word + "x", word[:-1], word.replace(" ", "  "), word + " [...]", word[: max(len(word) - 12, 5)] + " [...]", word.upper(), word.replace("a", "e", 1)]
        others = [_pick(rng, normalized) for _ in range(_between(rng, 0, 12))]
        pool = list(dict.fromkeys(near + variants + others + ([word] if index % 3 == 0 else [])))
        calls.append({"cuvant": word, "posibilitati": pool, "n": 1, "cutoff": 0.88})
        if index % 4 == 0:
            calls.append({"cuvant": word, "posibilitati": pool, "n": 3, "cutoff": 0.6})
        if index % 9 == 0:
            calls.append({"cuvant": word, "posibilitati": pool + pool[::-1], "n": 2, "cutoff": 0.3})
    calls += [{"cuvant": "abcd3", "posibilitati": ["abcd1", "abcd2", "abcd4", "abcd0"], "n": 5, "cutoff": 0.8}, {"cuvant": "appel", "posibilitati": ["ape", "apple", "peach", "puppy"], "n": 3, "cutoff": 0.6},
              {"cuvant": "", "posibilitati": ["", "a"], "n": 1, "cutoff": 0.0}, {"cuvant": "a", "posibilitati": [], "n": 1, "cutoff": 0.88}, {"cuvant": GRIN + "a", "posibilitati": [GRIN + "a", "a", GRIN], "n": 3, "cutoff": 0.5}]
    for call in calls:
        call["rezultat"] = difflib.get_close_matches(call["cuvant"], call["posibilitati"], call["n"], call["cutoff"])
    return {"pares": records, "apropiate": calls, "scriptate": _scripted_block_cases()}


# =====================================================================================================================
# html.json și parsere.json: pagini inventate (ambele așezări), capcane HTML, liste de linii și variante stricate ale lor
# =====================================================================================================================

# Numerele comenzilor inventate pornesc de aici și cresc cu 1 în ordinea definirii; retururile referă comenzile prin nume (vezi _ORDER_PAGES).
FIRST_FAKE_ORDER_ID = 489000001
FIRST_FAKE_RETURN_ID = 3000001
FAKE_RETURN_PATH = "/user/return-history/1/{return_id}"
# Câte variante stricate se fac din paginile de comandă și de retur (mutații cu sămânță fixă): destule cât să atingă ramurile parserelor, puține cât să rămână fixtura mică.
ORDER_MUTANTS = 420
RETURN_MUTANTS = 180


def _simple_block(**overrides) -> dict:
    """Blocul din testele parserului: eMAG, două produse, voucher, transport gratuit, serviciu, 'Total platit' care se leagă; `overrides` schimbă orice cheie."""
    block = dict(
        header="Produse vandute si livrate de eMAG", seller_label="eMAG", status=["Produse ridicate"],
        items=[("Rucsac Alfa Test, Negru", "105,99", 1), ("Rucsac Beta Test, Alb", "116,99", 1)], total_products="222,98",
        vouchers=["-34,00"], shipping="GRATUIT", services=["1,49"], paid="190,47",
    )
    block.update(overrides)
    return block


def _marketplace_block(seller: str, status: list[str], items: list, total: str, **overrides) -> dict:
    """Bloc de marketplace: titlul „Produse vandute de <vânzător> si livrate de eMAG”."""
    block = dict(header=f"Produse vandute de {seller} si livrate de eMAG", seller_label=seller, status=status, items=items, total_products=total, shipping="GRATUIT", paid=total)
    block.update(overrides)
    return block


def _to_pay_block(status_line: str) -> dict:
    """Bloc fără „Total platit”, cu „Total de plata” (ca la blocurile anulate), pe un status dat."""
    return dict(header="Produse vandute de ALFA SRL si livrate de eMAG", seller_label="ALFA SRL", status=[status_line], items=[("Produs Test Fara Total", "84,99", 1)],
                total_products="84,99", shipping="GRATUIT", to_pay="84,99")


# (nume, data plasării, total din antet, blocuri, așezări) - numerele de comandă se atribuie în ordine
_ORDER_PAGES = (
    ("simpla", "26 mai 2026, 10:07", "190,47", [_simple_block()], ("inline", "stacked")),
    ("multi_vanzator", "15 iunie 2026, 12:55", "384,97", [
        _simple_block(items=[("Pantofi Test, Negru, 42", "167,99", 1)], total_products="167,99", vouchers=["-25,00"], services=["1,99"], paid="144,98"),
        _marketplace_block("ALFA SRL", ["Am trimis cererea de anulare catre ALFA SRL. Statusul comenzii va fi actualizat.", "Livrare anulata"],
                           [("Pantofi Test Marketplace, Gri, 43", "239,99", 1)], "239,99")], ("inline", "stacked")),
    ("asigurare", "3 sep 2026, 18:53", "2.335,78", [_simple_block(header="Produse vandute si livrate de eMAG Asigurari", seller_label="eMAG Asigurari", status=["Plata acceptata"],
                                                            items=[("Asigurare Test", "2.335,78", 1)], total_products="2.335,78", vouchers=[], services=[], paid="2.335,78")], ("inline",)),
    ("cantitate_pret_unitar", "1 oct 2026, 22:27", "30,00", [_simple_block(items=[("Cablu Test", "10,00", 3)], total_products="30,00", vouchers=[], services=[], paid="30,00")], ("inline",)),
    ("cantitate_total_linie", "1 oct 2026, 22:27", "20,00", [_simple_block(items=[("Cablu Test", "20,00", 2)], total_products="20,00", vouchers=[], services=[], paid="20,00")], ("inline",)),
    ("suma_produse_gresita", "1 oct 2026, 22:27", "12,00", [_simple_block(items=[("Produs Test", "10,00", 1)], total_products="12,00", vouchers=[], services=[], paid="12,00")], ("inline",)),
    ("total_platit_gresit", "1 oct 2026, 22:27", "190,00", [_simple_block(paid="190,00")], ("inline",)),
    ("taxa_necunoscuta", "1 oct 2026, 22:27", "102,50", [_simple_block(items=[("Produs Test", "100,00", 1)], total_products="100,00", vouchers=[], services=[],
                                                                       other=[("Taxa de ambalare:", "2,50")], paid="102,50")], ("inline", "stacked")),
    ("storno", "26 mai 2026, 10:07", "190,47", [_simple_block(storno=True)], ("inline",)),
    ("anulata_fara_total_antet", "9 feb 2025, 19:54", None, [_simple_block(status=["Livrare anulata"], vouchers=[], services=[], items=[("Produs Test", "84,99", 1)], total_products="84,99", paid="84,99")], ("inline",)),
    ("atribut_sub_nume", "26 mai 2026, 10:07", "359,99", [_simple_block(items=[("Controller Test Wireless", "349,99", 1, "garantie electronica"), ("Cablu Test", "10,00", 1, "ghidul utilizatorului")],
                                                                      total_products="359,99", vouchers=[], services=[], paid="359,99")], ("inline", "stacked")),
    ("pachet", "26 mai 2026, 10:07", "35,50", [_simple_block(items=[("Pachet", "25,50", 1, None, ["Deodorant Test A, 150 ml", "Deodorant Test B, 150 ml"]), ("Cablu Test", "10,00", 1)],
                                                         total_products="35,50", vouchers=[], services=[], paid="35,50")], ("inline", "stacked")),
    ("bloc_anulat_total_zero", "9 feb 2025, 19:54", None, [_simple_block(status=["Livrare anulata"], vouchers=[], services=[], items=[("Produs Test", "84,99", 1)], total_products="84,99", paid="0,00")], ("inline",)),
    ("fara_vanzator", "26 mai 2026, 10:07", None, [], ("inline",)),
    ("anulat_fara_total_platit", "9 feb 2025, 19:54", None, [_to_pay_block("Am trimis cererea de anulare catre ALFA SRL."), ], ("inline", "stacked")),
    ("livrat_fara_total_platit", "9 feb 2025, 19:54", "84,99", [_to_pay_block("Produse livrate")], ("inline",)),
    ("in_curs_fara_total_platit", "9 feb 2025, 19:54", "84,99", [_to_pay_block("Comanda plasata")], ("inline",)),
    ("plata_fara_total_platit", "9 feb 2025, 19:54", "84,99", [_to_pay_block("Plata acceptata")], ("inline",)),
    ("necunoscut_fara_total_platit", "9 feb 2025, 19:54", "84,99", [_to_pay_block("Un status pe care programul nu-l cunoaste")], ("inline",)),
    ("livrat_si_anulat_fara_total", "15 iunie 2026, 12:55", "190,47", [_simple_block(), _to_pay_block("Livrare anulata")], ("inline",)),
    ("gratuit_servicii_vouchere", "12 noi 2024, 23:59", "290,00", [_simple_block(items=[("Ghete Test, maro, 42", "300,00", 1)], total_products="300,00", vouchers=["-20,00", "-5,00"], shipping="GRATUIT",
                                                                           services=["1,99", "3,01"], paid="280,00")], ("inline", "stacked")),
    ("transport_cu_cost", "9 decembrie 2023", "134,98", [_simple_block(items=[("Dispozitiv Test", "119,99", 1)], total_products="119,99", vouchers=[], shipping="14,99", services=[], paid="134,98")], ("inline",)),
    ("sume_mari_cu_mii", "29 ian 2026, 09:46", "13.579,35", [_simple_block(items=[("Laptop Test Mare", "12.345,67", 1), ("Monitor Test", "1.233,68", 1)], total_products="13.579,35", vouchers=[], services=[],
                                                                       paid="13.579,35")], ("inline", "stacked")),
    ("nume_cu_entitati", "26 mai 2026, 10:07", "50,00", [_simple_block(items=[("Ceai &amp; Cafea Test, &quot;Ediție&quot; &lt;mare&gt;", "20,00", 1), ("Șampon anticădere Test 400&nbsp;ml", "30,00", 1)],
                                                                    total_products="50,00", vouchers=[], services=[], paid="50,00")], ("inline",)),
    ("trei_vanzatori", "3 oct 2026, 18:21", "270,00", [
        _simple_block(items=[("Produs eMAG Test", "100,00", 1)], total_products="100,00", vouchers=[], services=[], paid="100,00"),
        _marketplace_block("BETA SRL", ["Produse livrate"], [("Produs Beta Test", "90,00", 2)], "90,00"),
        _marketplace_block("GAMMA & Fii SRL", ["Produse ridicate"], [("Produs Gamma Test", "80,00", 1)], "80,00")], ("inline", "stacked")),
    ("discount_negativ", "26 mai 2026, 10:07", "75,00", [_simple_block(items=[("Produs Test Scump", "100,00", 1), ("Custom Discount", "-25,00", 1)], total_products="75,00", vouchers=[], services=[],
                                                                  paid="75,00")], ("inline", "stacked")),
    ("cantitati_mari", "26 mai 2026, 10:07", "1.200,00", [_simple_block(items=[("Baterii Test", "12,00", 100)], total_products="1.200,00", vouchers=[], services=[], paid="1.200,00")], ("inline",)),
    ("fara_data", "data necunoscuta", "10,00", [_simple_block(items=[("Produs Test", "10,00", 1)], total_products="10,00", vouchers=[], services=[], paid="10,00")], ("inline",)),
    ("data_cu_luna_scurta", "29 ian 2026, 09:46", "10,00", [_simple_block(items=[("Produs Test", "10,00", 1)], total_products="10,00", vouchers=[], services=[], paid="10,00")], ("inline",)),
    ("fara_produse", "26 mai 2026, 10:07", "0,00", [_simple_block(items=[], total_products="0,00", vouchers=[], services=[], shipping="GRATUIT", paid="0,00")], ("inline",)),
    ("fara_total_produse", "26 mai 2026, 10:07", "10,00", [_simple_block(items=[("Produs Test", "10,00", 1)], total_products="10,00", vouchers=[], services=[], paid="10,00")], ("inline",)),
    ("status_ajuns_in_showroom", "26 mai 2026, 10:07", "10,00", [_simple_block(status=["Produse ajunse in showroom"], items=[("Produs Test", "10,00", 1)], total_products="10,00", vouchers=[], services=[], paid="10,00")], ("inline",)),
)

# (nume, produse, pași (titlu, dată), ordinea comenzilor referite (nume din _ORDER_PAGES), text de restituire, mod, titlu+dată pe aceeași linie?, pași viitori)
_COMPLETED_STEPS = [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Preluat de catre curier", "Data: 1 Iulie, 16:21"), ("Restituire suma", "Data: 1 Iulie, 16:45")]
_REFUND_TEXT = "Suma de 93.59 RON a pornit spre contul tau. Finalizarea transferului poate dura."
_RETURN_PAGES = (
    ("finalizat_cu_suma", ["Rucsac Alfa Test, Negru"], _COMPLETED_STEPS, ["simpla"], _REFUND_TEXT, "Vreau banii inapoi", (False, True), None),
    ("anulat", ["Produs Test"], [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Cerere anulata", "Data: 2 Iulie, 09:00")], ["multi_vanzator"], "", "Vreau banii inapoi", (False,), None),
    ("fara_rezultat", ["Pantofi Test, Negru, 42"], [("Cerere inregistrata", "Data: 1 Iulie, 13:44")], ["multi_vanzator"], "", "Vreau banii inapoi", (False,), None),
    ("pasi_viitori", ["Produs Test"], [("Cerere inregistrata", "Data: 19 Iunie, 13:42")], ["storno"], "", "Vreau banii inapoi", (False, True),
     ["Preluat de catre curier", "Receptionare produs", "Verificare produs", "Restituire suma"]),
    ("anulat_cu_pasi_viitori", ["Produs Test"], [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Cerere anulata", "Data: 2 Iulie, 09:00")], ["storno"], "", "Vreau banii inapoi", (False,), ["Restituire suma"]),
    ("voucher_fara_suma", ["Cablu Test"], [("Cerere inregistrata", "Data: 1 Iulie, 13:44"), ("Restituire suma", "Data: 3 Iulie, 10:00")], ["cantitate_pret_unitar"], "", "Emitere voucher", (False,), None),
    ("nume_duplicate", ["Baterii Test", "Spray Test, 200 ml", "Baterii Test", "Baterii Test"], _COMPLETED_STEPS, ["cantitati_mari"], _REFUND_TEXT, "Vreau banii inapoi", (False,), None),
    ("doua_comenzi", ["Produs eMAG Test"], _COMPLETED_STEPS, ["trei_vanzatori", "simpla"], _REFUND_TEXT, "Vreau banii inapoi", (False,), None),
    ("suma_intreaga", ["Produs Beta Test"], _COMPLETED_STEPS, ["trei_vanzatori"], "Suma de 129 RON a pornit spre contul tau.", "Vreau banii inapoi", (False,), None),
    ("suma_cu_mii", ["Laptop Test Mare"], _COMPLETED_STEPS, ["sume_mari_cu_mii"], "Suma de 12.345,67 RON a pornit spre contul tau.", "Vreau banii inapoi", (False, True), None),
    ("generare_sold", ["Produs Gamma Test"], _COMPLETED_STEPS, ["trei_vanzatori"], "", "Generare sold", (False,), None),
    ("mod_necunoscut", ["Produs Test Scump"], _COMPLETED_STEPS, ["discount_negativ"], "Suma de 75 RON a pornit spre contul tau.", "Retur la ghiseu", (False,), None),
    ("nume_cu_diacritice", ["Șampon anticădere Test 400 ml"], _COMPLETED_STEPS, ["nume_cu_entitati"], "Suma de 30 RON a pornit spre contul tau.", "Vreau banii inapoi", (False,), None),
    ("nume_aproape_identic", ["Rucsac Alfa Test Negru"], _COMPLETED_STEPS, ["simpla"], _REFUND_TEXT, "Vreau banii inapoi", (False,), None),
    ("comanda_necunoscuta", ["Produs Fantoma"], _COMPLETED_STEPS, [], _REFUND_TEXT, "Vreau banii inapoi", (False,), None),
    ("fara_produse", [], _COMPLETED_STEPS, ["simpla"], _REFUND_TEXT, "Vreau banii inapoi", (False,), None),
    ("mod_gol", ["Cablu Test"], _COMPLETED_STEPS, ["cantitate_total_linie"], "Suma de 10 RON a pornit spre contul tau.", "", (False,), None),
)

# (nume, html) - capcane pentru html_to_lines: comentarii, script/style/noscript/template/svg/head, entități, <br>, elemente inline imbricate, spații ciudate, structuri fără body, majuscule.
_HTML_TRAPS = (
    ("goala", ""), ("doar_spatii", "<div>  \n  </div>"), ("text_simplu", "text fara taguri"), ("div_imbricate", "<div>a<div>b</div>c</div>"),
    ("inline_se_lipesc", '<p><span class="money-int">222</span><sup class="money-decimal"><small>,</small>98</sup> <span class="money-currency">Lei</span></p>'),
    ("eticheta_valoare", "<p><span>Total produse:</span> <span>10,00 Lei</span></p>"), ("script_style_comentarii", "<body><script>var a='Total 1,00 Lei'</script><style>p{}</style><!-- ascuns --><p>vizibil</p></body>"),
    ("noscript_template_svg", "<body><noscript><p>ascuns</p></noscript><template><p>sablon</p></template><svg><text>grafic</text></svg><p>vizibil</p></body>"),
    ("head_cu_titlu", "<html><head><title>Titlu</title><meta charset='utf-8'></head><body><p>corp</p></body></html>"), ("doctype", "<!DOCTYPE html><html><body><p>cu doctype</p></body></html>"),
    ("majuscule", "<DIV>A<P>B</P></DIV><BR>C"), ("br_simplu", "<p>Data de livrare:<br><strong>27 mai 2026</strong></p>"), ("br_inchis", "<p>unu<br/>doi<br />trei</p>"),
    ("newline_in_bloc", "<p>Total\n    produse:\n   </p>"), ("linkuri_si_butoane", '<div><span>Produse ridicate</span><a href="#">Istoric livrare</a><button>Retur</button></div>'),
    ("entitati", "<p>a &amp; b &lt; c &gt; d &quot;e&quot; f&nbsp;g &euro; &#8364; &#x20AC; &hellip; &copy; &ensp;h</p>"), ("entitate_fara_punct_virgula", "<p>a &amp b &lt c</p>"),
    ("spatii_ciudate", "<p>a" + NBSP + "b" + THIN_SPACE + "c" + IDEOGRAPHIC_SPACE + "d" + NEL + "e" + ZWSP + "f" + BOM + "g\t\n\r h</p>"), ("emoji_si_unicode", "<p>" + GRIN + " ș ț ă î â ß ﬁ " + S_CEDILLA + "</p>"),
    ("lista", "<ul><li>unu</li><li>doi <b>bold</b> <i>it</i></li></ul>"), ("tabel", "<table><tr><th>Produs</th><th>Pret</th></tr><tr><td>A</td><td>1,00 Lei</td></tr></table>"),
    ("definitii", "<dl><dt>Eticheta</dt><dd>Valoare</dd></dl>"), ("titluri", "<h1>Unu</h1><h2>Doi</h2><h3>Trei</h3><h4>Patru</h4><h5>Cinci</h5><h6>Sase</h6>"),
    ("formular", "<form><label>Nume</label><input value='x'><button>Trimite</button></form>"), ("sectiuni", "<header>H</header><nav>N</nav><main>M</main><aside>A</aside><section>S</section><article>R</article><footer>F</footer>"),
    ("inline_imbricat_adanc", "<span><b><i><u>a</u>b</i>c</b>d</span>"), ("comentariu_in_text", "a<!-- x -->b<!-- y -->c"), ("comentariu_lung", "<p>a<!-- " + "x" * 500 + " -->b</p>"),
    ("script_in_script_text", "<p>a</p><script>if (a < b && c > d) { document.write('<p>x</p>'); }</script><p>b</p>"), ("style_in_body", "<p>a</p><style>.x{color:red}</style><p>b</p>"),
    ("fara_body_fragment", "<div>a</div>b<p>c</p>"), ("text_dupa_body", "<body><p>a</p></body>"), ("body_imbricat_adanc", "<div>" * 300 + "adanc" + "</div>" * 300),
    ("elemente_necunoscute", "<foo>a<bar>b</bar></foo><p>c</p>"), ("atribute_cu_text", '<p title="ascuns" data-x="Total 1,00 Lei">vizibil</p>'), ("img_si_input", '<p>a<img alt="poza">b<input type="text" value="v">c</p>'),
    ("pagina_comanda_mica", '<html><head><title>Contul tau</title></head><body><nav><a>Comenzile mele</a><a>Log out</a></nav><h1 class="order-hist-title">Comanda nr. 123</h1></body></html>'),
    ("rand_produs_cu_cantitate", '<ul class="product-list"><li class="clearfix"><div class="product-details"><p class="product-description">Produs  cu   spatii</p></div><span class="product-quantity">2 buc</span></li></ul>'),
    ("rand_produs_fara_cantitate", '<ul class="product-list"><li><p class="product-description">Fara cantitate</p></li></ul>'),
    ("rand_produs_fara_nume", '<ul class="product-list"><li><span class="product-quantity">1 buc</span></li></ul>'),
    ("rand_produs_doua_descrieri", '<div class="order-items"><ul><li><p class="product-description">Unu</p><p class="product-description">Doi</p><span class="product-quantity">1 buc</span></li></ul></div>'),
    ("pachet_fara_componente", '<ul class="product-list"><li class="promo-bundle"><span class="promo-heading">Pachet</span><span class="product-quantity">1 buc</span></li></ul>'),
    ("pachet_cu_componente_imbricate", '<ul class="product-list"><li class="promo-bundle"><span class="promo-heading">Pachet</span><span class="product-quantity">1 buc</span>'
     '<ul><li><p class="product-description">A</p></li><li><p class="product-description">B</p></li></ul></li></ul>'),
    ("nume_in_afara_listei", '<div class="order-items"><p class="product-description">Nu e in li</p></div>'),
)

# Linii scrise de mână (din testele parserelor): etichete lipite de valori, etichete cu text propriu, antete lipsă.
_HAND_WRITTEN_ORDER_LINES = (
    ("etichete_lipite", "777", ["Comanda nr. 777", "Plasata pe: 1 oct 2026, 22:27 Total: 30,00 Lei", "Produse vandute si livrate de eMAG", "Produse ridicate", "Istoric livrare", "Produs Test", "30,00 Lei", "1 buc",
                                "Total produse 30,00 Lei", "Cost livrare GRATUIT", "Total platit eMAG 30,00 Lei"]),
    ("eticheta_cu_text_propriu", "778", ["Comanda nr. 778", "Produse vandute si livrate de eMAG", "Produse ridicate", "Istoric livrare", "Produs Test", "30,00 Lei", "1 buc", "Total produse:", "30,00 Lei",
                                         "Cost livrare: la ridicare", "99,99 Lei", "Total platit eMAG:", "30,00 Lei"]),
    ("fara_antet", "1", ["Autentificare", "Parola"]), ("gol", "1", []), ("doar_antet", "5", ["Comanda nr. 5"]), ("antet_cu_punct", "6", ["Comanda nr.6", "Plasata pe: 3 sep 2026"]),
    ("pret_si_cantitate_pe_o_linie", "7", ["Comanda nr. 7", "Produse vandute si livrate de eMAG", "Produse livrate", "Istoric livrare", "Produs Mic", "10,00 Lei 3 buc.", "Total produse: 30,00 Lei", "Total platit eMAG: 30,00 Lei"]),
    ("numar_gresit_si_total_negativ", "8", ["Comanda nr. 9", "Plasata pe: 3 sep 2026, 18:53 Total: -5,00 Lei", "Produse vandute si livrate de eMAG", "Produse livrate", "Istoric livrare", "Produs", "-5,00 Lei 1 buc",
                                           "Total produse: -5,00 Lei", "Total platit eMAG: -5,00 Lei"]),
    ("taxa_dupa_total_produse", "10", ["Comanda nr. 10", "Produse vandute si livrate de eMAG", "Produse livrate", "Istoric livrare", "Produs", "10,00 Lei 1 buc", "Total produse: 10,00 Lei", "Taxa extra: 1,00 Lei",
                                       "Alta taxa: 2,50 Lei", "Cost livrare: 5,00 Lei", "Servicii operationale: 1,49 Lei", "Servicii operationale:: 0,51 Lei", "Total platit eMAG: 20,50 Lei"]),
    ("status_lung_cu_oprire", "11", ["Comanda nr. 11", "Produse vandute de Firma, SRL si livrate de eMAG", "Am trimis cererea", "Linia 2", "Linia 3", "Livrare anulata", "Istoric livrare", "Produs", "1,00 Lei 1 buc",
                                     "Total produse: 1,00 Lei"]),
    ("ghilimele_si_unicode", "12", ["COMANDA NR. 12", "PLASATA PE: 5 IANUARIE 2026, 07:08 TOTAL: 1.000,00 LEI", "PRODUSE VANDUTE SI LIVRATE DE EMAG", "PRODUSE LIVRATE", "Produs " + GRIN, "1.000,00 LEI 1 BUC",
                                    "TOTAL PRODUSE: 1.000,00 LEI", "TOTAL PLATIT EMAG: 1.000,00 LEI"]),
)
_HAND_WRITTEN_RETURN_LINES = (
    ("etichete_lipite", "/x", ["Retur #901", "Detalii comanda", "Produs Test", "Status retur", "Cerere inregistrata Data: 1 Iulie, 13:44", "Restituire suma Data: 1 Iulie, 16:45", "Suma de 12.50 RON a pornit spre contul tau.",
                               "Detalii de contact", "Nume Nume Fictiv", "Modalitate restituire Emitere voucher", "Produse din comanda: #489000010 Produs vandut de eMAG #489000011", "Istoricul tau de navigare"]),
    ("fara_antet", "/x", ["Autentificare"]), ("gol", "/x", []), ("doar_antet", "/x", ["Retur #5"]), ("fara_sectiuni", "/x", ["Retur #6", "Produs", "Cerere anulata Data: 1 Iulie"]),
    ("suma_cu_virgula", "/y", ["Retur #7", "Detalii comanda", "A", "B", "Status retur", "Restituire suma", "Data: 3 Iulie, 10:00", "Suma de 1.449,27 Lei a pornit", "Detalii de contact", "Modalitate restituire:", "Vreau banii inapoi",
                               "Produse din comanda:", "#12345", "#12345", "#678901", "Istoricul tau"]),
    ("pas_cu_data_pe_linia_urmatoare", "/z", ["Retur #8", "Detalii comanda", "X", "Status retur", "Cerere inregistrata", "Data: 2 Iulie, 10:00", "Data: 3 Iulie", "Cerere anulata", "Data: 4 Iulie, 11:00", "Detalii de contact"]),
)

_JUNK_LINES = ("Total: 5,00 Lei", "1 buc", "Factura storno 123", "Reducere: -1,00 Lei", "Total platit eMAG: 1,00 Lei", "Produse vandute si livrate de eMAG", "Livrare anulata", "Cost livrare: 3,00 Lei", "Data: 3 Iulie, 10:00",
               "Restituire suma", "Suma de 5 RON", "Retur #9", "Comanda nr. 3", "#123456", "Produs Junk", "12,34 Lei", "Detalii de contact", "Status retur", "Cerere anulata", "Modalitate restituire", "Emitere voucher")


def _fake_order_ids() -> dict[str, str]:
    """Numărul de comandă al fiecărei pagini de comandă, după nume (în ordinea definirii)."""
    return {name: str(FIRST_FAKE_ORDER_ID + index) for index, (name, *_rest) in enumerate(_ORDER_PAGES)}


def _page_fixture() -> tuple[list[dict], list[dict]]:
    """(html.json, intrările de bază pentru parsere.json): paginile inventate, capcanele HTML și liniile scrise de mână, cu ieșirile lui Python."""
    from emag_spend.html_lines import extract_product_names, html_to_lines
    from emag_spend.order_parser import parse_order
    from emag_spend.return_parser import parse_return
    from tests import html_builders

    ids = _fake_order_ids()
    pages: list[dict] = []
    parsed: list[dict] = []

    def add_page(name: str, html: str) -> tuple[list[str], list[str]]:
        """Adaugă pagina în html.json cu liniile și numele de produse ale lui Python; le întoarce pentru parsere."""
        lines, names = html_to_lines(html), extract_product_names(html)
        pages.append({"nume": name, "html": html, "linii": lines, "nume_produse": names})
        return lines, names

    for name, placed, header_total, blocks, layouts in _ORDER_PAGES:
        order_id = ids[name]
        for layout in layouts:
            lines, names = add_page(f"comanda_{name}_{layout}", html_builders.order_page(order_id, placed, header_total, blocks, layout))
            parsed.append({"nume": f"comanda_{name}_{layout}", "tip": "comanda", "id_sau_cale": order_id, "linii": lines, "nume_produse": names, **_parse_outcome(parse_order, order_id, lines, names)})
            if layout == layouts[0]:
                parsed.append({"nume": f"comanda_{name}_{layout}_doar_linii", "tip": "comanda", "id_sau_cale": order_id, "linii": lines, "nume_produse": None, **_parse_outcome(parse_order, order_id, lines, None)})
    return_counter = 0
    for name, products, steps, order_names, refund_text, mode, merges, future in _RETURN_PAGES:
        for merge in merges:
            return_id = str(FIRST_FAKE_RETURN_ID + return_counter)
            return_counter += 1
            order_ids = [ids[order_name] for order_name in order_names]
            html = html_builders.return_page(return_id, products, steps, order_ids, refund_text, mode, merge, future)
            page_name = f"retur_{name}_{'o_linie' if merge else 'doua_linii'}"
            lines, _ = add_page(page_name, html)
            path = FAKE_RETURN_PATH.format(return_id=return_id)
            parsed.append({"nume": page_name, "tip": "retur", "id_sau_cale": path, "linii": lines, "nume_produse": None, **_parse_outcome(parse_return, path, lines)})
    for name, html in _HTML_TRAPS:
        add_page(f"capcana_{name}", html)
    for name, order_id, lines in _HAND_WRITTEN_ORDER_LINES:
        parsed.append({"nume": f"linii_comanda_{name}", "tip": "comanda", "id_sau_cale": order_id, "linii": lines, "nume_produse": None, **_parse_outcome(parse_order, order_id, lines, None)})
    parsed.append({"nume": "linii_comanda_numar_cerut_diferit", "tip": "comanda", "id_sau_cale": "999", "linii": pages[0]["linii"], "nume_produse": pages[0]["nume_produse"],
                   **_parse_outcome(parse_order, "999", pages[0]["linii"], pages[0]["nume_produse"])})
    parsed.append({"nume": "linii_comanda_un_singur_nume", "tip": "comanda", "id_sau_cale": ids["simpla"], "linii": pages[0]["linii"], "nume_produse": ["un singur nume"],
                   **_parse_outcome(parse_order, ids["simpla"], pages[0]["linii"], ["un singur nume"])})
    for name, path, lines in _HAND_WRITTEN_RETURN_LINES:
        parsed.append({"nume": f"linii_retur_{name}", "tip": "retur", "id_sau_cale": path, "linii": lines, "nume_produse": None, **_parse_outcome(parse_return, path, lines)})
    return pages, parsed


def _parse_outcome(parser, *args) -> dict:
    """{"rezultat": to_dict(...)} sau {"eroare": {"tip", "mesaj"}}: ce dă parserul Python, inclusiv ValueError când pagina nu e o comandă / un retur."""
    try:
        return {"rezultat": to_dict(parser(*args))}
    except Exception as error:  # noqa: BLE001 - orice excepție a parserului e o ieșire de înregistrat
        return {"eroare": {"tip": type(error).__name__, "mesaj": str(error)}}


def _mutate_lines(rng: random.Random, lines: list[str]) -> list[str]:
    """Una până la trei mutații peste o listă de linii: șters, dublat, schimbat, majuscule, punct în loc de virgulă, linie în plus, tăiat, lipit, despărțit la «: »."""
    lines = list(lines)
    for _ in range(_between(rng, 1, 3)):
        if not lines:
            lines.append(_pick(rng, _JUNK_LINES))
            continue
        index = _between(rng, 0, len(lines) - 1)
        action = _between(rng, 0, 9)
        if action == 0:
            del lines[index]
        elif action == 1:
            lines.insert(index, lines[index])
        elif action == 2 and index + 1 < len(lines):
            lines[index], lines[index + 1] = lines[index + 1], lines[index]
        elif action == 3:
            lines[index] = lines[index].upper()
        elif action == 4:
            lines[index] = lines[index].lower()
        elif action == 5:
            lines[index] = lines[index].replace(",", ".")
        elif action == 6:
            lines.insert(index, _pick(rng, _JUNK_LINES))
        elif action == 7:
            lines = lines[: index + 1]
        elif action == 8 and index + 1 < len(lines):
            lines[index] = lines[index] + " " + lines.pop(index + 1)
        elif action == 9 and ": " in lines[index]:
            label, _, value = lines[index].partition(": ")
            lines[index:index + 1] = [label + ":", value]
    return lines


def _mutant_entries(base: list[dict], count: int, kind: str, parser, seed: int) -> list[dict]:
    """`count` variante stricate (mutații cu sămânță fixă) ale intrărilor de tip `kind`, cu ieșirea lui Python (rezultat sau eroare)."""
    rng = random.Random(seed)
    sources = [entry for entry in base if entry["tip"] == kind and entry["linii"]]
    entries = []
    for number in range(count):
        source = _pick(rng, sources)
        lines = _mutate_lines(rng, source["linii"])
        names = source["nume_produse"] if kind == "comanda" and rng.random() < 0.5 else None
        identifier = source["id_sau_cale"] if rng.random() < 0.9 else ("1" if kind == "comanda" else "/user/return-history/1/1")
        args = (identifier, lines, names) if kind == "comanda" else (identifier, lines)
        entries.append({"nume": f"mutant_{kind}_{number}_din_{source['nume']}", "tip": kind, "id_sau_cale": identifier, "linii": lines, "nume_produse": names, **_parse_outcome(parser, *args)})
    return entries


def _html_parser_metadata() -> dict:
    """Versiunile reale ale backendului BeautifulSoup «lxml»; runtime decide semantica, compilarea rămâne dovadă diagnostică."""
    from lxml import etree

    return {
        "backend": "lxml",
        "lxml_version": list(etree.LXML_VERSION),
        "libxml_runtime": list(etree.LIBXML_VERSION),
        "libxml_compiled": list(etree.LIBXML_COMPILED_VERSION),
    }


def _html_and_parsers_fixtures() -> tuple[dict, dict]:
    """(html.json, parsere.json): backendul HTML măsurat, paginile, capcanele și variantele stricate cu ieșirile lui Python."""
    from emag_spend.order_parser import parse_order
    from emag_spend.return_parser import parse_return

    pages, parsed = _page_fixture()
    parsed = parsed + _mutant_entries(parsed, ORDER_MUTANTS, "comanda", parse_order, CORPUS_SEED + 20) + _mutant_entries(parsed, RETURN_MUTANTS, "retur", parse_return, CORPUS_SEED + 21)
    return {"parser": _html_parser_metadata(), "pagini": pages}, {"cazuri": parsed}


# =====================================================================================================================
# analiza.json: analyze() pe scenarii (scenariul cu rezultate verificate de mână, demonstrativ, din pagini, capcane)
# =====================================================================================================================

ANALYSIS_THRESHOLD_BANI = 50000  # 500 de lei, ca în testele de analiză
ANALYSIS_GENERATED_AT = "2026-10-04 12:00"  # ora fixă a raportului demonstrativ (demo_data.DEMO_GENERATED_AT)
CAPTURE_RULES = {
    "default_category": "Necategorizat",
    "categories": [
        {"name": "Alcool", "patterns": [r"\bwhisk(?:y|ey)\b", r"\bvin\b"], "exclude": ["fara alcool"]},
        {"name": "Televizoare", "patterns": [r"\btelevizor"]},
        {"name": "Electronice", "patterns": [r"\bcasti\b", r"\bsmartwatch\b", r"\bcablu\b"]},
        {"name": "Transport și taxe", "patterns": ["^cost transport$", r"\bcustom discount\b"]},  # același nume ca rândul „Transport și taxe” din plătit: declanșează sufixul de nume
        {"name": "Diverse", "patterns": ["."]},
    ],
}


def _block(seller: str, status: str, items: list[tuple[str, int, int]], *, paid="auto", vouchers=None, shipping=0, services=None, other=None, storno=False, status_text=None, due=None, products_total="auto") -> object:
    """Un SellerBlock inventat: `items` = (nume, total linie în bani, cantitate); „Total produse” și „Total platit” se calculează din componente când sunt „auto”."""
    from emag_spend.models import Item, SellerBlock

    built = [Item(name, total, qty) for name, total, qty in items]
    products = sum(item.line_total_bani for item in built) if products_total == "auto" else products_total
    voucher_list = list(vouchers or [])
    service_list = list(services or [])
    other_list = list(other or [])
    expected = (products or 0) + sum(voucher_list) + (shipping or 0) + sum(service_list) + sum(other_list)
    return SellerBlock(seller=seller, status=status, status_text=status_text or status, has_storno=storno, items=built, products_total_bani=products, vouchers_bani=voucher_list,
                       shipping_bani=shipping, services_bani=service_list, other_bani=other_list, paid_bani=expected if paid == "auto" else paid, due_bani=due)


def _order(order_id: str, placed_at: str | None, blocks: list, *, header="auto", warnings=None) -> Order:
    """Un Order inventat; antetul se calculează ca suma blocurilor când e „auto”."""
    text = None if placed_at is None else placed_at.replace("T", " ")
    total = sum(block.paid_bani or 0 for block in blocks) if header == "auto" else header
    return Order(order_id, text or "", placed_at, total, blocks, list(warnings or []))


def _return(return_id: str, order_ids: list[str], names: list[str], *, completed=True, cancelled=False, refund=None, mode="Vreau banii inapoi", steps=None) -> ReturnRequest:
    """Un ReturnRequest inventat, cu pașii potriviți rezultatului."""
    default_steps = ["Cerere inregistrata", "Restituire suma"] if completed else (["Cerere inregistrata", "Cerere anulata"] if cancelled else ["Cerere inregistrata"])
    return ReturnRequest(return_id, f"/user/return-history/1/{return_id}", order_ids, names, steps or default_steps, refund, mode, completed, cancelled)


def _scenario_sort_ties() -> tuple[list, list]:
    """Egalități la sortare, nume cu emoji / ß / sedile, comenzi pe mai mulți ani și fără dată: ordinea după puncte de cod și cheile text cu casefold."""
    d, c = block_status.DELIVERED, block_status.CANCELLED
    orders = [
        _order("100100", "2019-03-01T10:00", [_block("eMAG", d, [("Straße Produs", 10000, 1), ("Produs " + GRIN, 5000, 1), ("Produs " + chr(0xFB01), 5000, 1), ("Alfa produs", 5000, 1)])]),
        _order("100200", "2020-04-01T11:00", [_block("Zeta SRL", d, [("STRASSE PRODUS", 10000, 1), ("produs " + GRIN, 5000, 1), ("Produs " + S_CEDILLA + "i " + T_CEDILLA, 7000, 1)])]),
        _order("100300", "2021-05-01T12:00", [_block("Alfa SRL", d, [("Ábaco Test", 3000, 3), ("Abaco Test", 3000, 3), ("abaco test", 3000, 1)])]),
        _order("100400", "2022-06-01T13:00", [_block("eMAG", d, [("Cafea Test", 2500, 1)]), _block(GRIN + " Vanzator", d, [("Ceai Test", 2500, 1)]), _block(chr(0xFB01) + " Vanzator", d, [("Miere Test", 2500, 1)])]),
        _order("100500", None, [_block("eMAG", d, [("Produs fara data", 1234, 2)])]),
        _order("100600", "2023-07-01T14:00", [_block("eMAG", c, [("Produs anulat", 9900, 1)], paid=0)]),
        _order("100700", "2024-08-01T15:00", [_block("Beta SRL", d, [("Televizor Test 43 inch", 150000, 1), ("Cost Transport", 1500, 1)])]),
        _order("100800", "2025-09-01T16:00", [_block("eMAG", d, [("Whisky Test 0.7L 40%", 9900, 2), ("Vin Test fara alcool", 1900, 1), ("Vin rosu Test", 3900, 1)])]),
        _order("100900", "2026-01-15T17:00", [_block("eMAG", d, [("Casti Test", 22000, 1), ("Smartwatch Test", 33000, 1), ("Cablu Test", 1000, 5)])]),
    ]
    returns = [_return("3100100", ["100100"], ["Produs " + GRIN], refund=5000), _return("3100200", ["100200", "100100"], ["STRASSE PRODUS", "Straße Produs"], refund=15000)]
    return orders, returns


def _scenario_prices() -> tuple[list, list]:
    """Istoric de prețuri: procente cu jumătate exactă (12,25 -> 12,2), zero negativ, nume trunchiate „[...]”, culori, cumpărări în aceeași comandă, cadouri."""
    d = block_status.DELIVERED
    long_name = "Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G"
    orders = [
        _order("200001", "2023-01-10T10:00", [_block("eMAG", d, [("Produs Procent A", 40000, 1), ("Produs Procent B", 40000, 1), ("Produs Procent C", 100000, 1), ("Produs Procent D", 800, 1)])]),
        _order("200002", "2023-02-10T10:00", [_block("eMAG", d, [("Produs Procent A", 44900, 1), ("Produs Procent B", 35100, 1), ("Produs Procent C", 99999, 1), ("Produs Procent D", 801, 1)])]),
        _order("200003", "2023-03-10T10:00", [_block("eMAG", d, [("Husa Kelmor Fit, silicon, Alb", 3000, 1), ("Telefon Vexor Y2, gri inchis, 64GB", 100000, 1), (long_name + ", Negru", 120000, 1), ("Deodorant Test", 0, 1)])]),
        _order("200004", "2023-04-10T10:00", [_block("eMAG", d, [("Husa Kelmor Fit, silicon, Negru", 2500, 1), ("Telefon Vexor Y2, gri deschis, 64GB", 95000, 1), (long_name[:35] + " [...]", 110000, 1), ("Deodorant Test", 0, 1)])]),
        _order("200005", "2023-05-10T10:00", [_block("Alfa SRL", d, [("Husa Kelmor Fit, silicon, Alb", 2500, 2), ("Husa Kelmor Fit, silicon, Alb", 2700, 1), ("Telefon Vexor Y2, gri inchis, 128GB", 105000, 1), ("Nume scurt [...]", 500, 1)])]),
        _order("200006", "2023-06-10T10:00", [_block("eMAG", d, [("Televizor Smart 43\" negru", 150000, 1), ("Televizor Smart 55\" negru", 250000, 1), ("Produs Rotunjit", 1000, 3), ("Produs Rotunjit", 1001, 3)])]),
        _order("200007", "2023-07-10T10:00", [_block("eMAG", d, [("Televizor Smart 43\" alb", 140000, 1), ("Televizor Smart 55\" alb", 260000, 1), ("Produs Rotunjit", 1003, 2)])]),
        _order("200008", None, [_block("eMAG", d, [("Husa Kelmor Fit, silicon, Rosu", 2000, 1), ("Produs Procent A", 42000, 1)])]),
        _order("200009", "2023-09-10T10:00", [_block("eMAG", d, [("Produs Mic", 1, 3), ("Produs Mic", 1, 3), ("Produs Scazut", 10000, 1), ("Produs Scazut", 9999, 1), ("Produs Scazut", 9999, 1)])]),
    ]
    return orders, [_return("3200001", ["200003"], ["Husa Kelmor Fit, silicon, Alb"], refund=3000)]


def _scenario_returns() -> tuple[list, list]:
    """Retururi: potrivire aproximativă la 0,88, prefix trunchiat de 29/30 de caractere, moduri necunoscute / credit, retur din bloc anulat, neamestecate, parțiale, fără comandă."""
    d, c = block_status.DELIVERED, block_status.CANCELLED
    thirty = "Aspirator robot Solvex R5 mopp"  # 30 de caractere
    assert len(thirty) == 30
    orders = [
        _order("300001", "2024-01-05T10:00", [_block("eMAG", d, [("Televizor Norvik 55 inch UHD", 200000, 1), ("Cablu HDMI Test 2 m", 3000, 2), ("Telecomanda Test", 5000, 1)], vouchers=[-10000], services=[149])]),
        _order("300002", "2024-02-05T10:00", [_block("Alfa SRL", c, [("Rucsac Marketplace Test", 15000, 1)], paid=0, storno=True), _block("eMAG", d, [("Casti Test Bluetooth", 22000, 1), ("Casti Test Bluetooth", 22000, 1)])]),
        _order("300003", "2024-03-05T10:00", [_block("eMAG", d, [(thirty + "ing, 4000 Pa, extra lung", 80000, 1), (thirty[:-1] + "ing, 4000 Pa", 50000, 1), ("Nume foarte lung de produs cu multe cuvinte pentru test [...]", 30000, 1)])]),
        _order("300004", "2024-04-05T10:00", [_block("eMAG", d, [("Produs Voucher", 10000, 1), ("Produs Sold", 10000, 1), ("Produs Mod Ciudat", 10000, 1), ("Produs Mod Gol", 10000, 1), ("Produs Fara Suma", 10000, 1)])]),
        _order("300005", "2024-05-05T10:00", [_block("eMAG", d, [("Produs Retur De Doua Ori", 30000, 3)]), _block("Beta SRL", d, [("Produs Beta", 7000, 2)], storno=True)]),
        _order("300006", "2024-06-05T10:00", [_block("eMAG", d, [("Produs Partial A", 10000, 1), ("Produs Partial B", 20000, 1)])]),
        _order("300007", "2024-07-05T10:00", [_block("eMAG", d, [("Produs Aproape Identic Numele Lung 123", 10000, 1), ("Produs Foarte Diferit", 10000, 1)])]),
    ]
    returns = [
        _return("3300001", ["300001"], ["Televizor Norvik 55 inch UHD"], refund=190000),
        _return("3300002", ["300001"], ["Cablu HDMI Test 2m"], refund=2900),  # aproape identic: 'Test 2 m' vs 'Test 2m'
        _return("3300003", ["300002"], ["Rucsac Marketplace Test"], refund=15000),  # bloc anulat: devine returnat din anulat
        _return("3300004", ["300002"], ["Casti Test Bluetooth", "Casti Test Bluetooth"], refund=40000),
        _return("3300005", ["300003"], [thirty + "ing, 4000 Pa, extra lung"], refund=80000),  # prefix de 30 de caractere
        _return("3300006", ["300003"], ["Nume foarte lung de produs cu multe cuvinte pentru test si inca ceva"], refund=30000),
        _return("3300007", ["300004"], ["Produs Voucher"], refund=None, mode="Emitere voucher"),
        _return("3300008", ["300004"], ["Produs Sold"], refund=None, mode="Generare sold"),
        _return("3300009", ["300004"], ["Produs Mod Ciudat"], refund=10000, mode="Mod ciudat"),
        _return("3300010", ["300004"], ["Produs Mod Gol"], refund=10000, mode=""),
        _return("3300011", ["300004"], ["Produs Fara Suma"], refund=None),
        _return("3300012", ["300005"], ["Produs Retur De Doua Ori"], refund=10000),
        _return("3300013", ["300005"], ["Produs Retur De Doua Ori", "Produs Retur De Doua Ori"], refund=19000),
        _return("3300014", ["300005"], ["Produs Retur De Doua Ori"], refund=10000),  # a patra unitate: nu mai e nimic de returnat
        _return("3300015", ["300005"], ["Produs Beta"], refund=6500),
        _return("3300016", ["300006"], ["Produs Partial A", "Produs Care Nu Exista"], refund=25000),
        _return("3300017", ["300006"], ["Produs Care Nu Exista"], refund=1000),
        _return("3300018", [], ["Produs Partial B"], refund=1000),
        _return("3300019", ["999999"], ["Produs Partial B"], refund=1000),
        _return("3300020", ["300006"], [], refund=1000),
        _return("3300021", ["300007"], ["Produs Aproape Identic Numele Lung 124"], refund=10000),
        _return("3300022", ["300007"], ["Produs Foarte Diferit Cu Totul"], refund=10000),
        _return("3300023", ["300007"], ["Produs Foarte Diferit"], completed=False, refund=None),
        _return("3300024", ["300007"], ["Produs Foarte Diferit"], completed=False, cancelled=True, refund=None),
        _return("3300025", ["300001", "300006"], ["Telecomanda Test", "Produs Partial B"], refund=30000),
    ]
    return orders, returns


def _scenario_amounts() -> tuple[list, list]:
    """Sume neobișnuite: linii negative, voucher mai mare decât produsele, bloc fără „Total platit” sau cu „Total de plata”, taxe, antet diferit, status necunoscut, cantități zero."""
    d, c, p, i, u = block_status.DELIVERED, block_status.CANCELLED, block_status.PAID_ONLY, block_status.IN_PROGRESS, block_status.UNKNOWN
    orders = [
        _order("400001", "2024-01-01T10:00", [_block("eMAG", d, [("Produs Scump Test", 100000, 1), ("Custom Discount", -2500, 1), ("Custom Discount", -1, 1)])]),
        _order("400002", "2024-02-01T10:00", [_block("eMAG", d, [("Produs Ieftin", 1000, 1), ("Cost Transport", 2000, 1)], vouchers=[-5000], shipping=1499)]),  # categoria „Transport și taxe” + rândul de taxe cu același nume
        _order("400003", "2024-03-01T10:00", [_block("eMAG", d, [("Produs Fara Total Platit", 4000, 2)], paid=None, shipping=999, services=[149, 51], other=[200])],
               warnings=["comanda 400003, eMAG: lipsește 'Total platit'"]),
        _order("400004", "2024-04-01T10:00", [_block("Alfa SRL", c, [("Produs Anulat Cu Voucher", 20000, 1)], paid=None, vouchers=[-3000], due=17000)]),
        _order("400005", "2024-05-01T10:00", [_block("eMAG", d, [("Produs Cu Taxa", 5000, 1)], other=[250, -50], shipping=None)]),
        _order("400006", "2024-06-01T10:00", [_block("eMAG", d, [("Produs Antet Diferit", 5000, 1)])], header=5200),
        _order("400007", "2024-07-01T10:00", [_block("eMAG", u, [("Produs Status Necunoscut", 5000, 1)], status_text="Un status ciudat ' \"")]),
        _order("400008", "2024-08-01T10:00", [_block("eMAG Asigurari", p, [("Asigurare Test", 50000, 1)])]),
        _order("400009", "2024-09-01T10:00", [_block("eMAG", i, [("Produs In Curs", 7000, 2)], shipping=999)]),
        _order("400010", "2024-10-01T10:00", [_block("eMAG", d, [("Produs Cantitate Zero", 5000, 0), ("Produs Normal", 1000, 1)])]),
        _order("400011", "2024-11-01T10:00", [_block("eMAG", d, [("Produs Total Mare", 123456789, 1)])]),
        _order("400012", "2024-12-01T10:00", [_block("eMAG", d, [("Produs A", 3333, 3), ("Produs B", 3334, 3)], vouchers=[-100, -200], shipping=0)]),
        _order("400013", "2025-01-01T10:00", [_block("eMAG", d, [("Produs Fara Total Produse", 1000, 1)], products_total=None, paid=1000)]),
        _order("400014", "2025-02-01T10:00", [_block("eMAG", d, [("Produs Suma Diferita", 1000, 1)], products_total=1500, paid=1500)]),
        _order("400015", "2025-03-01T10:00", [_block("Beta SRL", c, [("Marketplace Anulat Returnat", 12000, 1)], paid=0)]),
        _order("400016", "2025-04-01T10:00", []),
    ]
    returns = [_return("3400001", ["400015"], ["Marketplace Anulat Returnat"], refund=12000), _return("3400002", ["400002"], ["Produs Ieftin"], refund=0), _return("3400003", ["400012"], ["Produs A"], refund=1000)]
    return orders, returns


def _analysis_entry(name: str, orders: list, returns: list, rules: dict, highlight: tuple[str, ...], with_report: bool = False) -> dict:
    """Intrarea din analiza.json pentru un scenariu: intrările (comenzi, retururi, reguli, prag, ora, evidențiate) și toate ieșirile lui Python (rezumat, linii, CSV-uri, JSON-uri, raport)."""
    import tempfile

    from emag_spend import csv_export, price_history_csv, report_html
    from emag_spend.classifier import Classifier
    from emag_spend.product_key import load_color_words
    from emag_spend.refund_modes import load_refund_modes
    from emag_spend.spend_analysis import analyze
    from emag_spend.warning_details import load_warning_texts

    orders_dict = [to_dict(order) for order in orders]  # înainte de analiză: copiile intrărilor, nemodificate
    returns_dict = [to_dict(ret) for ret in returns]
    analysis = analyze(orders, returns, Classifier(rules), ANALYSIS_THRESHOLD_BANI, ANALYSIS_GENERATED_AT, highlight_categories=highlight,
                       warning_texts=load_warning_texts(), color_words=load_color_words(), refund_modes=load_refund_modes())
    properties = ("returned_bani", "cancelled_bani", "pending_bani", "paid_only_bani", "unknown_bani", "kept_bani", "list_value_bani", "kept_list_bani", "paid_value_bani",
                  "returned_paid_bani", "cancelled_paid_bani", "pending_paid_bani", "paid_only_paid_bani", "unknown_paid_bani", "kept_paid_bani")
    entry = {
        "nume": name, "comenzi": orders_dict, "retururi": returns_dict, "reguli": rules, "prag_bani": ANALYSIS_THRESHOLD_BANI, "generat_la": ANALYSIS_GENERATED_AT, "evidentiate": list(highlight),
        "rezumat": json.loads(json.dumps(analysis.summary, ensure_ascii=False)),
        "linii": [{**to_dict(line), **{prop: getattr(line, prop) for prop in properties}} for line in analysis.lines],
    }
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        csv_export.write_lines_csv(base / "produse.csv", analysis.lines, ANALYSIS_THRESHOLD_BANI)
        price_history_csv.write_price_history_csv(base / "istoric_preturi.csv", analysis.summary["price_history"])
        entry["linii_csv"] = (base / "produse.csv").read_bytes().decode("utf-8")  # cu BOM-ul de la început (U+FEFF)
        entry["istoric_csv"] = (base / "istoric_preturi.csv").read_bytes().decode("utf-8")
        # comenzi.json / retururi.json: textul pe care îl produce json.dumps(..., ensure_ascii=False, indent=1) din run_store.py (fără traducerea sfârșiturilor de rând a sistemului)
        entry["comenzi_json"] = json.dumps(orders_dict, ensure_ascii=False, indent=1)
        entry["retururi_json"] = json.dumps(returns_dict, ensure_ascii=False, indent=1)
        if with_report:
            report_html.write_report(base / "raport.html", settings.REPORT_TEMPLATE_FILE, analysis.summary)
            entry["raport_html"] = (base / "raport.html").read_bytes().decode("utf-8")
    return entry


def _analysis_fixture(parsed_cases: list[dict]) -> dict:
    """analiza.json: scenariile `scenariu`, `demo`, `din_pagini` și capcanele, cu intrările și ieșirile lui Python."""
    from emag_spend.demo_data import DEMO_GENERATED_AT, demo_orders_and_returns
    from tests import scenario

    assert DEMO_GENERATED_AT == ANALYSIS_GENERATED_AT, "ora demonstrativă s-a schimbat: actualizează ANALYSIS_GENERATED_AT"
    highlight = tuple(settings.HIGHLIGHT_CATEGORIES)
    repo_rules = json.loads((CONFIG_DIR / "categorii.json").read_text(encoding="utf-8"))
    demo_orders, demo_returns = demo_orders_and_returns()
    # doar paginile proiectate, într-o singură așezare (inline) și într-o singură variantă de retur: aceleași comenzi sau retururi nu intră de două ori în scenariu
    page_orders = [order_from_dict(case["rezultat"]) for case in parsed_cases
                   if case["tip"] == "comanda" and "rezultat" in case and case["nume"].startswith("comanda_") and case["nume"].endswith("_inline")]
    page_returns = [return_from_dict(case["rezultat"]) for case in parsed_cases
                    if case["tip"] == "retur" and "rezultat" in case and case["nume"].startswith("retur_") and case["nume"].endswith("_doua_linii")]
    capture_highlight = ("Alcool", "Televizoare", "Categorie Lipsa")
    scenarios = [
        _analysis_entry("scenariu", scenario.orders(), scenario.returns(), scenario.RULES, highlight, with_report=True),
        _analysis_entry("demo", demo_orders, demo_returns, repo_rules, highlight),
        _analysis_entry("din_pagini", page_orders, page_returns, repo_rules, highlight),
        _analysis_entry("capcane_sortare", *_scenario_sort_ties(), CAPTURE_RULES, capture_highlight),
        _analysis_entry("capcane_preturi", *_scenario_prices(), CAPTURE_RULES, capture_highlight),
        _analysis_entry("capcane_retururi", *_scenario_returns(), CAPTURE_RULES, capture_highlight),
        _analysis_entry("capcane_sume", *_scenario_amounts(), CAPTURE_RULES, capture_highlight),
        _analysis_entry("gol", [], [], scenario.RULES, highlight),
    ]
    return {"scenarii": scenarios}


def _write(folder: Path, name: str, payload: dict, compact: bool = False) -> None:
    """Scrie `<folder>/<name>.json` (UTF-8, LF, cheile în ordinea inserării) cu `schema` primul: indent=1, sau pe un singur rând dacă `compact` (fișierele cu mii de valori mici)."""
    options = {"separators": (",", ":")} if compact else {"indent": JSON_INDENT}
    text = json.dumps({"schema": SCHEMA_VERSION, **payload}, ensure_ascii=False, sort_keys=False, **options)
    (folder / f"{name}.json").write_bytes(text.encode("utf-8") + b"\n")


def main(folder: Path) -> None:
    """Scrie toate fișierele de fixturi în `folder` (creat dacă lipsește)."""
    folder.mkdir(parents=True, exist_ok=True)
    unicode_tables = _unicode_fixture()
    _write(folder, "setari", _settings_fixture())
    _write(folder, "unicode", unicode_tables)
    _write(folder, "primitive", _primitive_fixture(unicode_tables))
    _write(folder, "regex", _regex_fixture())
    _write(folder, "regex_aleatoare", _random_regex_fixture(), compact=True)
    _write(folder, "difflib", _difflib_fixture())
    html_fixture, parsers_fixture = _html_and_parsers_fixtures()
    _write(folder, "html", html_fixture)
    _write(folder, "parsere", parsers_fixture)
    _write(folder, "analiza", _analysis_fixture(parsers_fixture["cazuri"]))
    written = sorted(folder.glob("*.json"))
    print(f"Fixturi de paritate scrise în {folder}: {len(written)} fișiere, {sum(path.stat().st_size for path in written) / 1_000_000:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("folosire: python -m tests.paritate_export <folderul în care se scriu fixturile>")
    main(Path(sys.argv[1]).resolve())
