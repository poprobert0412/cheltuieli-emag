"""Clasifică numele unui produs într-o categorie, după reguli din config/.

Primește: numele produsului. Dă înapoi: (categorie, regula care a potrivit).
Regulile sunt DATE (expresii regulate pe numele normalizat), nu cod: config/categorii.json (public, generic)
și, dacă există lângă el, config/categorii.personal.json (local; regulile lui se evaluează PRIMELE).
Prima categorie care se potrivește câștigă; o categorie poate avea modele de EXCLUDERE.
Un produs fără potrivire primește categoria implicită („Necategorizat”).
Nu scrie fișiere; erorile din reguli sunt ValueError cu numele fișierului și al categoriei.
"""

import logging
import re
from pathlib import Path

from emag_spend import settings
from emag_spend.json_file import read_json
from emag_spend.text_normalize import normalize_text

logger = logging.getLogger(__name__)

_Category = tuple[str, list[re.Pattern], list[re.Pattern]]  # (nume, modele, excluderi)


def _pattern_list(value: object, source: str, category: str, key: str) -> list[str]:
    """Verifică că `value` e o listă de texte nevide; ValueError cu fișierul și categoria altfel."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{source}: în categoria {category!r}, «{key}» trebuie să fie o listă de texte")
    if any(not item.strip() for item in value):
        raise ValueError(f"{source}: categoria {category!r} are un model gol în «{key}» (ar potrivi orice produs)")
    return value


def _compile_categories(rules: dict, source: str) -> list[_Category]:
    """Compilează lista 'categories'; ValueError cu `source` (numele fișierului) dacă ceva e greșit.

    Refuză și modelele care potrivesc textul gol (ar potrivi ORICE produs: toate ar ajunge într-o singură
    categorie, un rezultat greșit care pare normal).
    """
    entries = rules.get("categories", [])
    if not isinstance(entries, list):
        raise ValueError(f"{source}: «categories» trebuie să fie o listă de categorii")
    compiled: list[_Category] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: fiecare categorie trebuie să fie un obiect cu «name» și «patterns»")
        raw_name = entry.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            raise ValueError(f"{source}: o categorie din reguli nu are nume")
        if name in seen:
            raise ValueError(f"{source}: categorie duplicată în reguli: {name!r}")
        seen.add(name)
        pattern_texts = _pattern_list(entry.get("patterns", []), source, name, "patterns")
        exclude_texts = _pattern_list(entry.get("exclude", []), source, name, "exclude")
        try:
            patterns = [re.compile(p) for p in pattern_texts]
            excludes = [re.compile(p) for p in exclude_texts]
        except re.error as error:
            raise ValueError(f"{source}: expresie regulată greșită în categoria {name!r}: {error}") from error
        if not patterns:
            raise ValueError(f"{source}: categoria {name!r} nu are niciun model în 'patterns'")
        if any(p.search("") for p in patterns + excludes):
            raise ValueError(f"{source}: categoria {name!r} are un model care potrivește orice text (ar potrivi orice produs)")
        compiled.append((name, patterns, excludes))
    return compiled


def _read_rules(path: Path) -> dict:
    """Citește un fișier de reguli; ValueError cu calea dacă JSON-ul e rupt sau nu e un obiect."""
    rules = read_json(path)
    if not isinstance(rules, dict):
        raise ValueError(f"{path}: trebuie să conțină un obiect cu cheia 'categories'")
    return rules


class Classifier:
    """Aplică regulile de categorii pe numele produselor."""

    def __init__(self, rules: dict, source: str = "regulile de categorii"):
        """Compilează regulile; ridică ValueError (cu `source` în mesaj) dacă fișierul e greșit."""
        self.default_category: str = rules.get("default_category", "Necategorizat")
        self._categories: list[_Category] = _compile_categories(rules, source)
        self.personal_source: str | None = None  # numele fișierului personal încărcat, dacă a existat

    @classmethod
    def from_file(cls, path: Path, *, include_personal: bool = True) -> "Classifier":
        """Încarcă regulile publice din `path` și, dacă există lângă el, pe cele personale (evaluate primele).

        ValueError cu numele fișierului dacă vreunul e rupt. `include_personal=False` ignoră fișierul personal
        (teste care trebuie să dea același rezultat pe orice calculator).
        """
        path = Path(path)
        classifier = cls(_read_rules(path), source=path.name)
        personal_path = path.with_name(settings.PERSONAL_CATEGORY_RULES_FILE_NAME)
        if include_personal and personal_path.is_file():
            classifier._add_personal_rules(personal_path)
        return classifier

    def _add_personal_rules(self, path: Path) -> None:
        """Pune categoriile din fișierul personal ÎNAINTEA celor publice (o categorie personală poate avea același nume)."""
        try:
            rules = _read_rules(path)
        except ValueError as error:
            raise ValueError(f"{error} (fișier cu reguli personale: corectează-l sau mută-l din folderul config)") from error
        declared = rules.get("default_category")
        if declared is not None and declared != self.default_category:
            raise ValueError(
                f"{path.name}: «default_category» se stabilește doar în categorii.json (aici ar schimba "
                f"categoria produselor fără potrivire din {self.default_category!r} în {declared!r})"
            )
        personal = _compile_categories(rules, path.name)
        self._categories = personal + self._categories
        self.personal_source = path.name
        logger.info("reguli personale încărcate din %s: %d categorii (evaluate primele)", path.name, len(personal))

    @property
    def category_names(self) -> list[str]:
        """Numele categoriilor, fără dubluri (o categorie personală poate repeta numele uneia publice)."""
        return list(dict.fromkeys(name for name, _, _ in self._categories))

    def classify(self, product_name: str) -> tuple[str, str]:
        """(categoria, modelul care a potrivit); categoria implicită dacă nu se potrivește nimic."""
        text = normalize_text(product_name)
        for name, patterns, excludes in self._categories:
            matched = next((p for p in patterns if p.search(text)), None)
            if matched and not any(e.search(text) for e in excludes):
                return name, matched.pattern
        return self.default_category, ""
