"""Teste pentru clasificarea statusurilor și pentru clasificatorul de categorii."""

import pytest

from emag_spend import block_status, settings
from emag_spend.classifier import Classifier


@pytest.mark.parametrize("text,expected", [
    ("Produse ridicate", block_status.DELIVERED),
    ("Produse livrate", block_status.DELIVERED),
    ("Produse livrate electronic", block_status.DELIVERED),
    ("Livrare anulata", block_status.CANCELLED),
    ("Am trimis cererea de anulare catre X. Statusul comenzii va fi actualizat. | Livrare anulata", block_status.CANCELLED),
    ("Livrare anulata | - actualizat | 22 iunie 2026", block_status.CANCELLED),
    ("Plata acceptata", block_status.PAID_ONLY),
    ("Comanda plasata", block_status.IN_PROGRESS),
    ("Produse predate curierului | AWB: 123", block_status.IN_PROGRESS),
    ("Produse in drum spre showroom", block_status.IN_PROGRESS),
    ("Produse ajunse in showroom", block_status.IN_PROGRESS),  # sosite la punctul de ridicare, încă neridicate
    ("Produse ajunse în easybox", block_status.IN_PROGRESS),
    ("Produse ajunse la punctul de ridicare", block_status.IN_PROGRESS),
    ("Produse ajunse in showroom | Produse ridicate", block_status.DELIVERED),  # după ridicare contează „ridicate”
    ("Am trimis cererea de anulare catre X (fara confirmare)", block_status.UNKNOWN),
    ("ceva nou si necunoscut", block_status.UNKNOWN),
    ("", block_status.UNKNOWN),
])
def test_classify_status(text, expected):
    assert block_status.classify_status(text) == expected


_RULES = {
    "default_category": "Necategorizat",
    "categories": [
        {"name": "Televizoare", "patterns": [r"\btelevizor"], "exclude": ["suport"]},
        {"name": "Alcool", "patterns": [r"\bwhisk(?:y|ey)\b", r"\bvin\b"], "exclude": ["alcool sanitar", "pahar"]},
        {"name": "Curățenie", "patterns": [r"\balcool sanitar\b"]},
    ],
}


def test_first_matching_category_wins_and_rule_is_reported():
    category, rule = Classifier(_RULES).classify("Televizor Alfa Smart LED 55 inch")
    assert category == "Televizoare"
    assert rule == r"\btelevizor"


def test_exclude_patterns_block_a_category():
    classifier = Classifier(_RULES)
    assert classifier.classify("Suport televizor de perete")[0] == "Necategorizat"
    assert classifier.classify("Alcool sanitar 70% 500 ml")[0] == "Curățenie"
    assert classifier.classify("Pahar de vin")[0] == "Necategorizat"


def test_matching_ignores_case_and_diacritics():
    assert Classifier(_RULES).classify("WHISKY Învechit 0.7L")[0] == "Alcool"
    assert Classifier(_RULES).classify("Vin roșu sec")[0] == "Alcool"


def test_word_boundaries_prevent_partial_matches():
    assert Classifier(_RULES).classify("Vinete proaspete")[0] == "Necategorizat"


def test_unmatched_product_gets_default_category_with_empty_rule():
    assert Classifier(_RULES).classify("Ceva fara reguli") == ("Necategorizat", "")


@pytest.mark.parametrize("rules,message", [
    ({"categories": [{"name": "", "patterns": ["a"]}]}, "nu are nume"),
    ({"categories": [{"name": "A", "patterns": ["a"]}, {"name": "A", "patterns": ["b"]}]}, "duplicată"),
    ({"categories": [{"name": "A", "patterns": ["("]}]}, "expresie regulată greșită"),
    ({"categories": [{"name": "A", "patterns": []}]}, "niciun model"),
])
def test_invalid_rules_are_rejected_with_clear_message(rules, message):
    with pytest.raises(ValueError, match=message):
        Classifier(rules)


def test_real_rules_file_loads_and_highlight_categories_exist():
    # include_personal=False: același rezultat pe orice calculator, cu sau fără fișier personal de reguli
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    for name in settings.HIGHLIGHT_CATEGORIES:
        assert name in classifier.category_names


@pytest.mark.parametrize("name,expected", [
    ("Televizor LED Smart Samsung 55 inch 4K", "Televizoare"),
    ("Suport TV de perete 32-65 inch", None),
    ("Whisky Jameson 0.7L", "Alcool"),
    ("Vodka Absolut 1L", "Alcool"),
    ("Alcool sanitar Fernova 70%, 500 ml", "Curățenie și menaj"),  # procentul de alcool NU face din el băutură
    ("Pahar de vin set 6 buc", None),
])
def test_real_rules_on_representative_names(name, expected):
    category, _ = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False).classify(name)
    if expected is None:
        assert category not in ("Televizoare", "Alcool")
    else:
        assert category == expected
