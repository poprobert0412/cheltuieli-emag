"""Compară, pe contul real, ce a citit și a calculat extensia Chrome cu ce citește și calculează programul Python.

Primește: folderul unei rulări a programului (cu comenzi.json, retururi.json) și folderul cu fișierele descărcate din
extensie (comenzi.json, retururi.json, analiza.json). Dă înapoi: codul 0 dacă totul e identic, 1 altfel; pe ecran doar
numărători și căile cheilor care diferă (fără nume de produse, sume sau numere de comandă).
Comparații: (1) comenzile și retururile citite, câmp cu câmp (parsarea paginilor reale: lxml față de parserul HTML5);
(2) analiza: Python recalculează din comenzile EXTENSIEI, fără regulile personale de categorii (extensia nu le are în v1),
și se compară cu analiza.json a extensiei (data generării nu contează).
Rulat de extensie/scripts/cont_real.mjs (modul acceptanta); nu e test pytest (nu începe cu test_) și nu scrie nimic.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from emag_spend import settings  # noqa: E402  (după sys.path: scriptul rulează din tests/)
from emag_spend.classifier import Classifier  # noqa: E402
from emag_spend.product_key import load_color_words  # noqa: E402
from emag_spend.refund_modes import load_refund_modes  # noqa: E402
from emag_spend.run_store import load_run  # noqa: E402
from emag_spend.spend_analysis import analyze  # noqa: E402
from emag_spend.warning_details import load_warning_texts  # noqa: E402

# Câte căi diferite arătăm; restul doar se numără (o diferență de structură le-ar repeta pe sute de rânduri).
MAX_SHOWN_DIFFERENCES = 25
# Cheile care diferă legitim între două rulări: momentul generării.
IGNORED_META_KEYS = ("generated_at",)


def _differences(left, right, path: str, found: list[str]) -> None:
    """Adaugă în `found` căile la care `left` și `right` diferă (fără valori: pot fi date personale)."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                found.append(f"{path}.{key} (lipsește într-una)")
            else:
                _differences(left[key], right[key], f"{path}.{key}", found)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            found.append(f"{path} (lungimi {len(left)} / {len(right)})")
        for index, (a, b) in enumerate(zip(left, right)):
            _differences(a, b, f"{path}[{index}]", found)
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)) and not isinstance(left, bool) and not isinstance(right, bool):
        if left != right:  # 5 și 5.0 sunt același număr; extensia poate scrie oricare
            found.append(path)
    elif left != right:
        found.append(path)


def _read_json(path: Path):
    """Conținutul unui fișier JSON; SystemExit cu calea dacă lipsește."""
    if not path.is_file():
        raise SystemExit(f"lipsește {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _report(title: str, found: list[str]) -> bool:
    """Tipărește rezultatul unei comparații; True dacă e identic."""
    if not found:
        print(f"{title}: identic")
        return True
    print(f"{title}: {len(found)} diferențe")
    for item in found[:MAX_SHOWN_DIFFERENCES]:
        print(f"  {item}")
    if len(found) > MAX_SHOWN_DIFFERENCES:
        print(f"  … și încă {len(found) - MAX_SHOWN_DIFFERENCES}")
    return False


def compare(program_run: Path, extension_files: Path) -> bool:
    """Rulează cele două comparații și tipărește rezultatul; True dacă totul e identic."""
    program_orders = _read_json(program_run / "comenzi.json")
    program_returns = _read_json(program_run / "retururi.json")
    extension_orders = _read_json(extension_files / "comenzi.json")
    extension_returns = _read_json(extension_files / "retururi.json")
    extension_summary = _read_json(extension_files / "analiza.json")
    print(f"comenzi: program {len(program_orders)}, extensie {len(extension_orders)}; "
          f"retururi: program {len(program_returns)}, extensie {len(extension_returns)}")

    found: list[str] = []
    _differences(program_orders, extension_orders, "comenzi", found)
    _differences(program_returns, extension_returns, "retururi", found)
    reading_ok = _report("citirea paginilor (comenzi.json, retururi.json)", found)

    orders, returns = load_run(extension_files)
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    expected = analyze(
        orders, returns, classifier, round(settings.BIG_PURCHASE_THRESHOLD_LEI * 100),
        generated_at=extension_summary.get("meta", {}).get("generated_at", ""),
        highlight_categories=settings.HIGHLIGHT_CATEGORIES,
        warning_texts=load_warning_texts(), color_words=load_color_words(), refund_modes=load_refund_modes(),
    ).summary
    expected = json.loads(json.dumps(expected, ensure_ascii=False))  # aceleași tipuri ca un fișier citit
    for key in IGNORED_META_KEYS:
        expected.get("meta", {}).pop(key, None)
        extension_summary.get("meta", {}).pop(key, None)
    found = []
    _differences(expected, extension_summary, "analiza", found)
    analysis_ok = _report("analiza (Python din comenzile extensiei, fără reguli personale)", found)
    return reading_ok and analysis_ok


def main(argv: list[str] | None = None) -> int:
    """Punctul de intrare: două foldere, codul 0 sau 1."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program_run", type=Path, help="folderul rulării programului (iesiri/.../<data>_<ora>)")
    parser.add_argument("extension_files", type=Path, help="folderul cu fișierele descărcate din extensie")
    args = parser.parse_args(argv)
    return 0 if compare(args.program_run, args.extension_files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
