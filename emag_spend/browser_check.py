"""Verifică dacă programul poate porni un browser; îl cheamă lansatoarele (instaleaza.bat, instalare/pregatire.sh).

Primește: nimic (citește EMAG_BROWSER_CHANNEL și PLAYWRIGHT_BROWSERS_PATH din mediu, ca restul programului).
Dă înapoi: cod 0 și numele browserului găsit, sau cod 1 când nu găsește niciunul (lansatorul descarcă atunci Chromium).
Pornește browserul fără fereastră și îl închide imediat. Nu deschide nicio pagină, nu scrie fișiere și nu citește nimic din cont.
Folosire: python -m emag_spend.browser_check
"""

import logging
import sys

from emag_spend import settings
from emag_spend.browser_session import find_usable_browser

BROWSER_NAMES = {
    "msedge": "Microsoft Edge",
    "chrome": "Google Chrome",
    settings.DOWNLOADED_BROWSER: "Chromium (descărcat pentru program)",
}


def main() -> int:
    """Caută un browser utilizabil și spune ce a găsit; întoarce codul de ieșire pentru lansator (0 găsit, 1 lipsă)."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    channel = find_usable_browser()
    if channel is None:
        print("Nu găsesc un browser pe care programul să-l poată porni (Edge, Chrome sau Chromium descărcat).")
        return 1
    print(f"Browser găsit: {BROWSER_NAMES.get(channel, channel)}.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
