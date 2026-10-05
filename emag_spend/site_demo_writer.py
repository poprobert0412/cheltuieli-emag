"""Scrie `interfata/assets/demo-data.js`: analiza datelor inventate, pentru site-ul din interfata/.

Primește: nimic (datele vin din demo_data.py) și, opțional, calea fișierului de scris.
Dă înapoi: calea scrisă; conținutul e exact `window.EMAG_DEMO_DATA = <JSON analiza>;` pe un
singur rând, UTF-8, determinist (chei în ordinea din analiză, oră fixă, prag implicit).
Site-ul se deschide din file:// și nu poate citi un .json, deci datele stau într-un script clasic.
Nu calculează nimic singur: apelează aceeași `analyze()` ca rularea reală.
"""

import json
from pathlib import Path

from emag_spend import settings
from emag_spend.classifier import Classifier
from emag_spend.demo_data import DEMO_GENERATED_AT, demo_orders_and_returns
from emag_spend.spend_analysis import analyze

DEMO_DATA_JS_FILE = settings.PROJECT_ROOT / "interfata" / "assets" / "demo-data.js"
_JS_PREFIX = "window.EMAG_DEMO_DATA = "
_JS_SUFFIX = ";"
# Cheia din `meta` care spune „comenzile sunt inventate". Interfața (dashboard.js) o citește: la date de demonstrație
# numerele de comandă rămân text, fiindcă pe eMAG nu există și te-ar trimite doar la lista de comenzi.
DEMO_META_KEY = "demo"


def build_demo_summary() -> dict:
    """Analiza datelor inventate, cu pragul implicit din settings și ora generării fixă.

    Nu depinde de `--prag`, de ceas sau de regulile personale de categorii (categorii.personal.json):
    același rezultat la orice rulare, pe orice calculator.
    """
    orders, returns = demo_orders_and_returns()
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=False)
    summary = analyze(
        orders,
        returns,
        classifier,
        round(settings.BIG_PURCHASE_THRESHOLD_LEI * 100),
        generated_at=DEMO_GENERATED_AT,
        highlight_categories=settings.HIGHLIGHT_CATEGORIES,
    ).summary
    summary["meta"][DEMO_META_KEY] = True  # comenzi inventate: raportul nu face linkuri spre eMAG pentru ele
    return summary


def render_demo_data_js(summary: dict) -> str:
    """Conținutul fișierului JS: o singură linie, fără sfârșit de rând.

    "</" e scris "<\\/" (un nume de produs nu poate închide un tag <script>), iar
    separatorii U+2028/U+2029 sunt scriși escape (rupeau literalele JS înainte de ES2019).
    """
    data = json.dumps(summary, ensure_ascii=False)
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f"{_JS_PREFIX}{data}{_JS_SUFFIX}"


def expected_demo_data_js() -> str:
    """Ce ar trebui să conțină acum `demo-data.js` (folosit și de testul de prospețime)."""
    return render_demo_data_js(build_demo_summary())


def write_demo_data_js(path: Path | None = None) -> Path:
    """(Re)scrie fișierul `demo-data.js` și întoarce calea lui.

    Se scrie ca octeți UTF-8, ca Windows să nu schimbe nimic (fără BOM, fără CRLF).
    """
    target = Path(path) if path is not None else DEMO_DATA_JS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(expected_demo_data_js().encode("utf-8"))
    return target
