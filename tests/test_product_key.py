"""Teste pentru cheia „același produs” (product_key.py) și lista de culori (config/culori.json).

Toate numele de produse sunt inventate (mărci ca Vexor, Kelmor, Norvik nu există).
"""

import json

import pytest

from emag_spend.product_key import COLOR_WORDS_FILE, ColorWords, load_color_words, make_product_key

COLORS = load_color_words()


def _key(name: str, colors: ColorWords = COLORS) -> str:
    return make_product_key(name, colors).key


def test_same_model_in_two_colors_has_the_same_key():
    assert _key("Telefon Vexor X5, 128GB, Negru") == _key("Telefon Vexor X5, 128GB, Alb")
    assert _key("Husă Kelmor Fit, silicon, roșu") == _key("Husă Kelmor Fit, silicon, albastru")


@pytest.mark.parametrize("a, b", [
    ("Tricou Brenta alb XL", "Tricou Brenta albă XL"),  # forme de gen
    ("Pantofi Kelmor Trek, ALB, 42", "pantofi kelmor trek, alb, 42"),  # litere mari/mici
    ("Căști Lumio Buds, Roșu", "Casti Lumio Buds, rosu"),  # diacritice
    ("Căști Lumio Buds, Black", "Căști Lumio Buds, Negru"),  # englezește și românește
    ("Boxă Solvex Wave, negru/alb", "Boxă Solvex Wave"),  # două culori lipite cu „/”
    ("Rucsac Kelmor 25 L, gri închis", "Rucsac Kelmor 25 L, gri deschis"),  # fraza „gri închis” se scoate întreagă
])
def test_color_variants_collapse_to_one_key(a, b):
    assert _key(a) == _key(b)


@pytest.mark.parametrize("a, b", [
    ('Televizor Smart Norvik 43" alb', 'Televizor Smart Norvik 55" alb'),
    ("Stick USB Brenta 128GB negru", "Stick USB Brenta 256GB negru"),
    ("Telefon Vexor X5, 6GB RAM, Negru", "Telefon Vexor X5, 8GB RAM, Negru"),
    ("Tricou Brenta alb XL", "Tricou Brenta alb L"),
    ("Telefon Vexor X5, Negru", "Telefon Vexor X9, Negru"),
])
def test_capacity_size_and_model_stay_in_the_key_so_they_are_different_products(a, b):
    assert _key(a) != _key(b)


def test_colors_are_removed_as_whole_words_only():
    assert _key("Rucsac Albatros Test, Negru") == "rucsac albatros test"  # „alb” din „Albatros” rămâne
    assert _key("Aparat Grigore Test 5") == "aparat grigore test 5"  # „gri” din „Grigore” rămâne
    assert _key("Cremă hidratantă Lumio 50 ml") == "crema hidratanta lumio 50 ml"  # „cremă” ≠ culoarea „crem”
    assert _key("Set Rosetta 3 piese, Verde") == "set rosetta 3 piese"


def test_a_name_made_only_of_colors_keeps_its_words_instead_of_an_empty_key():
    assert _key("Negru") == "negru"
    assert _key("Alb / Negru") == "alb negru"
    assert make_product_key("Negru", COLORS).colors == ()


def test_removed_colors_are_reported_in_order_without_the_rest():
    result = make_product_key("Telefon Vexor X5, Negru, 128GB, gri închis", COLORS)
    assert result.colors == ("negru", "gri inchis")
    assert result.key == "telefon vexor x5 128gb"


def test_longest_phrase_wins_over_its_first_word():
    colors = ColorWords(["gri", "gri închis"])
    assert make_product_key("Geacă gri închis", colors).colors == ("gri inchis",)
    assert make_product_key("Geacă gri", colors).colors == ("gri",)


def test_punctuation_and_spaces_do_not_change_the_key():
    assert _key("Telefon  Vexor X5 ,128GB,Negru") == _key("Telefon Vexor X5, 128GB, Negru")
    assert _key("Cafea 1,5 kg") == _key("Cafea 1.5 kg")


def test_truncated_name_is_flagged_and_its_prefix_is_kept_for_matching():
    result = make_product_key("Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Ne [...]", COLORS)
    assert result.truncated is True
    assert result.prefix == "telefon mobil vexor x5, dual sim, 128gb, 6gb ram, 5g, ne"
    whole = make_product_key("Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Negru", COLORS)
    assert whole.truncated is False and whole.prefix == whole.normalized


def test_empty_or_punctuation_only_names_give_an_empty_key_that_callers_skip():
    assert _key("") == "" and _key("  ,;  ") == ""


# --- config/culori.json -----------------------------------------------------------------------------

def test_shipped_color_list_has_romanian_and_english_colors_but_no_capacities():
    for color in ("alb", "negru", "rosu", "albastru", "verde", "galben", "gri", "black", "white", "red"):
        assert COLORS.strip([color]) == ([], (color,)), color
    capacities = ["128gb", "256gb", "43", "55", "xl", "l", "x5", "5g", "ram"]
    assert COLORS.strip(capacities) == (capacities, ())  # capacitatea și dimensiunea NU sunt culori
    assert len(COLORS) >= 40


def test_shipped_file_is_valid_utf8_json_with_the_expected_shape():
    data = json.loads(COLOR_WORDS_FILE.read_text(encoding="utf-8"))
    assert isinstance(data["culori"], list) and all(isinstance(c, str) and c.strip() for c in data["culori"])


@pytest.mark.parametrize("content, expected", [
    ('{"culori": "alb"}', "listă de texte"),
    ('{"culori": [1, 2]}', "listă de texte"),
    ('{"altceva": []}', "cheia 'culori'"),
    ("[]", "cheia 'culori'"),
    ('{"culori": ["alb", "!!!"]}', "fără niciun cuvânt"),
])
def test_wrong_color_file_is_rejected_naming_the_file(tmp_path, content, expected):
    path = tmp_path / "culori.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_color_words(path)
    assert expected in str(error.value) and "culori.json" in str(error.value)


def test_broken_json_names_file_and_position(tmp_path):
    path = tmp_path / "culori.json"
    path.write_text('{"culori": [', encoding="utf-8")
    with pytest.raises(ValueError, match="culori.json.*linia 1"):
        load_color_words(path)


def test_a_color_added_by_the_user_takes_effect(tmp_path):
    path = tmp_path / "culori.json"
    path.write_text(json.dumps({"culori": ["Chihlimbar"]}), encoding="utf-8")
    custom = load_color_words(path)
    assert make_product_key("Lampă Test, Chihlimbar", custom).key == make_product_key("Lampă Test", custom).key
    assert make_product_key("Lampă Test, Negru", custom).key != make_product_key("Lampă Test", custom).key  # „negru” nu mai e în listă
