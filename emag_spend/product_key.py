"""Cheia „același produs”: numele normalizat, fără cuvintele-culoare (config/culori.json).

Primește: numele unui produs și lista de culori. Dă înapoi un `ProductKey`: cheia (cuvintele
rămase, lipite cu spațiu), culorile scoase și numele normalizat (pentru potrivirea numelor
trunchiate). „… alb” și „… negru” au aceeași cheie; capacitatea și dimensiunea (128GB, 43", 55")
rămân în cheie, deci sunt produse diferite. Se scot doar cuvinte întregi.
Dacă după scoaterea culorilor n-ar rămâne nimic, cheia păstrează numele întreg.
Ce NU face: nu compară prețuri și nu grupează cumpărări (price_history.py).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from emag_spend import settings
from emag_spend.json_file import read_json
from emag_spend.return_matcher import _TRUNCATION_MARKER  # același semn de trunchiere ca la potrivirea retururilor
from emag_spend.text_normalize import normalize_text

COLOR_WORDS_FILE = settings.PROJECT_ROOT / "config" / "culori.json"

# Cuvintele unui nume: litere și cifre (și din alte alfabete); punctuația și „[...]” nu sunt cuvinte.
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class ProductKey:
    """Cheia unui produs. `colors` = culorile scoase, în ordinea din nume; `normalized` = numele
    întreg normalizat (cu culori și punctuație); `truncated` = numele se termină cu „[...]”;
    `prefix` = `normalized` fără acel semn (pentru potrivirea prin prefix)."""

    key: str
    colors: tuple[str, ...]
    normalized: str
    truncated: bool
    prefix: str


class ColorWords:
    """Lista de culori, gata de căutat în cuvintele unui nume (intrările cu mai multe cuvinte primele)."""

    def __init__(self, entries: Iterable[str]):
        """Normalizează intrările; ridică ValueError la o intrare care nu conține niciun cuvânt."""
        phrases = set()
        for entry in entries:
            words = tuple(_WORD.findall(normalize_text(entry)))
            if not words:
                raise ValueError(f"intrare de culoare fără niciun cuvânt: {entry!r}")
            phrases.add(words)
        self._by_first_word: dict[str, list[tuple[str, ...]]] = {}
        for phrase in sorted(phrases, key=lambda p: (-len(p), p)):  # frazele lungi se încearcă primele
            self._by_first_word.setdefault(phrase[0], []).append(phrase)

    def __len__(self) -> int:
        """Câte culori (fraze) sunt în listă."""
        return sum(len(phrases) for phrases in self._by_first_word.values())

    def strip(self, words: list[str]) -> tuple[list[str], tuple[str, ...]]:
        """(cuvintele fără culori, culorile scoase). Se potrivesc doar cuvinte întregi."""
        kept: list[str] = []
        removed: list[str] = []
        index = 0
        while index < len(words):
            phrase = next(
                (p for p in self._by_first_word.get(words[index], ()) if tuple(words[index:index + len(p)]) == p), None
            )
            if phrase is None:
                kept.append(words[index])
                index += 1
            else:
                removed.append(" ".join(phrase))
                index += len(phrase)
        return kept, tuple(removed)


def load_color_words(path: Path = COLOR_WORDS_FILE) -> ColorWords:
    """Citește config/culori.json (cheia 'culori' = listă de texte); ValueError cu calea dacă forma nu e cea așteptată."""
    data = read_json(path)
    colors = data.get("culori") if isinstance(data, dict) else None
    if not isinstance(colors, list) or not all(isinstance(c, str) for c in colors):
        raise ValueError(f"{path}: trebuie să conțină un obiect cu cheia 'culori' = listă de texte")
    try:
        return ColorWords(colors)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def make_product_key(name: str, color_words: ColorWords) -> ProductKey:
    """Cheia produsului `name`: cuvintele numelui normalizat, fără culori (sau întregi dacă n-ar rămâne nimic)."""
    normalized = normalize_text(name)
    words = _WORD.findall(normalized)
    kept, removed = color_words.strip(words)
    if not kept:  # numele e doar o culoare: o cheie goală ar uni orice cu orice
        kept, removed = words, ()
    return ProductKey(
        key=" ".join(kept),
        colors=removed,
        normalized=normalized,
        truncated=_TRUNCATION_MARKER.search(normalized) is not None,
        prefix=_TRUNCATION_MARKER.sub("", normalized).rstrip(" ,"),
    )
