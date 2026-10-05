"""Punctul de intrare: calculează cât ai cheltuit pe eMAG și pe ce.

Folosire (din folderul proiectului):
    python ruleaza.py                      rulare completă (te loghezi o dată în browser)
    python ruleaza.py --prag 1000          alt prag pentru "achiziție mare" (lei, între 0 și 1.000.000.000)
    python ruleaza.py --limita-comenzi 20  test rapid pe primele 20 de comenzi
    python ruleaza.py --din-cache iesiri\\2026-10-04_14-30-00   refă raportul fără browser
    python ruleaza.py --deschide           deschide raportul în browser la final (pe orice sistem de operare)
    python ruleaza.py --doar-login         doar te loghezi și salvezi sesiunea
    python ruleaza.py --demo               comenzi INVENTATE: fără browser, fără login; rezultatul apare în
                                           iesiri/<data>_<ora>_demo/ și se rescrie interfata/assets/demo-data.js
    python ruleaza.py --sterge-sesiunea    șterge sesiunea eMAG salvată (folderul profilului de browser), după ce
                                           scrii exact DA; nu se combină cu alte opțiuni, în afară de:
    python ruleaza.py --sterge-sesiunea --fara-confirmare   fără întrebare (pentru scripturi și teste)
    python ruleaza.py --aplicatie          pornește aplicația locală cu un singur buton: un server doar pe acest calculator
                                           (127.0.0.1, port ales de sistem) și pagina lui în browser; se oprește cu Ctrl+C,
                                           cu butonul din pagină sau singură, după o perioadă fără activitate; nu se combină
                                           cu alte opțiuni, în afară de:
    python ruleaza.py --aplicatie --fara-browser   nu deschide browserul; scrie adresa COMPLETĂ (cu cheia de acces) în consolă
Rezultatele apar în iesiri/<data>_<ora>/ (raport.html, produse.csv, rezumat.txt).
"""

import argparse
import asyncio
import logging
import math
import sys
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from emag_spend import session_cleaner, settings
from emag_spend.app_opener import open_app_page
from emag_spend.app_server import STOP_IDLE, STOP_INTERRUPTED, STOP_SHUTDOWN, AppServer
from emag_spend.browser_session import login_only
from emag_spend.report_opener import open_report
from emag_spend.run_logger import setup_logging
from emag_spend.run_pipeline import RunOptions, run


def _threshold_lei(text: str) -> float:
    """Tip argparse pentru --prag: un număr finit între 0 și settings.MAX_BIG_PURCHASE_THRESHOLD_LEI.

    Respinge nan, inf, 1e400 și valorile negative sau uriașe, cu mesaj în română (nu traceback mai târziu).
    """
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"«{text}» nu e un număr (folosește punct pentru zecimale, ex. 500 sau 999.50)") from None
    if not math.isfinite(value) or not 0 <= value <= settings.MAX_BIG_PURCHASE_THRESHOLD_LEI:
        maximum = f"{settings.MAX_BIG_PURCHASE_THRESHOLD_LEI:,}".replace(",", ".")  # 1.000.000.000, ca în română
        raise argparse.ArgumentTypeError(f"«{text}» nu e un prag valid: alege un număr între 0 și {maximum} lei")
    return value


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Citește opțiunile din linia de comandă (vezi antetul fișierului)."""
    parser = argparse.ArgumentParser(description="Cheltuieli eMAG: cât și pe ce.")
    # default=None la --prag: așa se vede dacă utilizatorul l-a scris (necesar la verificarea de exclusivitate);
    # valoarea implicită reală se pune mai jos, după verificări.
    parser.add_argument("--prag", type=_threshold_lei, default=None,
                        help=f"prag în lei pentru achiziții mari (implicit {settings.BIG_PURCHASE_THRESHOLD_LEI})")
    parser.add_argument("--limita-comenzi", type=int, default=None,
                        help="citește doar primele N comenzi (pentru teste)")
    parser.add_argument("--din-cache", type=Path, default=None,
                        help="folder de rulare salvat; refă raportul fără browser")
    parser.add_argument("--iesire", type=Path, default=None, help="folderul în care se creează rularea")
    parser.add_argument("--deschide", action="store_true", help="deschide raportul la final")
    parser.add_argument("--doar-login", action="store_true",
                        help="doar te loghezi în eMAG și salvezi sesiunea (fără calcule)")
    parser.add_argument("--demo", action="store_true",
                        help="folosește comenzi inventate: fără browser, fără login; rescrie și interfata/assets/demo-data.js")
    parser.add_argument("--sterge-sesiunea", action="store_true",
                        help="șterge sesiunea eMAG salvată (profilul de browser), după confirmare; nu se combină cu alte opțiuni")
    parser.add_argument("--fara-confirmare", action="store_true",
                        help="doar cu --sterge-sesiunea: șterge fără să întrebe (pentru scripturi și teste)")
    parser.add_argument("--aplicatie", action="store_true",
                        help="pornește aplicația locală cu un singur buton (server doar pe acest calculator, pagina în browser); nu se combină cu alte opțiuni")
    parser.add_argument("--fara-browser", action="store_true",
                        help="doar cu --aplicatie: nu deschide browserul și scrie adresa completă, cu cheia de acces (pentru teste, WSL, servere)")
    args = parser.parse_args(argv)
    # --sterge-sesiunea e distructivă, iar --aplicatie pornește un server: nu se amestecă cu nimic care citește contul sau face un raport.
    given = [flag for flag, used in (
        ("--prag", args.prag is not None), ("--limita-comenzi", args.limita_comenzi is not None),
        ("--din-cache", args.din_cache is not None), ("--iesire", args.iesire is not None),
        ("--deschide", args.deschide), ("--doar-login", args.doar_login), ("--demo", args.demo),
        ("--aplicatie", args.aplicatie)) if used]
    if args.sterge_sesiunea and given:
        parser.error(f"--sterge-sesiunea nu se combină cu {', '.join(given)} (doar cu --fara-confirmare)")
    if args.fara_confirmare and not args.sterge_sesiunea:
        parser.error("--fara-confirmare se folosește doar împreună cu --sterge-sesiunea")
    other_than_app = [flag for flag in given if flag != "--aplicatie"]
    if args.aplicatie and other_than_app:
        parser.error(f"--aplicatie nu se combină cu {', '.join(other_than_app)} (doar cu --fara-browser)")
    if args.fara_browser and not args.aplicatie:
        parser.error("--fara-browser se folosește doar împreună cu --aplicatie")
    if args.prag is None:
        args.prag = settings.BIG_PURCHASE_THRESHOLD_LEI
    # --demo nu citește nimic din cont: combinațiile de mai jos n-ar avea sens, deci le refuzăm clar.
    if args.demo and (args.din_cache or args.doar_login or args.limita_comenzi is not None):
        parser.error("--demo nu se combină cu --din-cache, --doar-login sau --limita-comenzi")
    return args


def _delete_saved_session(skip_confirmation: bool) -> int:
    """Rulează --sterge-sesiunea pe profilul din settings; întoarce 0 la succes sau anulare, 1 la refuz sau ștergere incompletă."""
    confirm = (lambda path: True) if skip_confirmation else session_cleaner.confirm_on_terminal
    result = session_cleaner.delete_session(settings.PROFILE_DIR, confirm)
    logging.getLogger(__name__).info(
        "ștergere sesiune: %s (fișiere șterse %d, foldere șterse %d, eșuate %d)",
        result.status.value, result.deleted_files, result.deleted_folders, result.failed_entries)
    print("\n" + session_cleaner.describe_result(result))
    return 0 if result.succeeded else 1


# Ce se scrie la oprirea aplicației, după motiv (un motiv nou fără mesaj aici cade pe textul general).
APP_STOP_MESSAGES = {
    STOP_SHUTDOWN: "Aplicația a fost închisă din pagină.",
    STOP_IDLE: "Aplicația s-a oprit singură: nu a mai venit nicio cerere de mult timp.",
    STOP_INTERRUPTED: "Aplicația a fost oprită cu Ctrl+C.",
}
GENERIC_APP_STOP_MESSAGE = "Aplicația s-a oprit."
ROMANIAN_PLURAL_SMALL_NUMBER_LIMIT = 20  # de la 20 în sus, numărul cere „de” (20 de minute); sub 20, nu (2 minute, 15 minute)


def _minutes_text(minutes: float) -> str:
    """„1 minut”, „15 minute”, „30 de minute”: acordul în română pentru un număr întreg de minute (zecimalele se păstrează ca atare)."""
    if minutes != int(minutes):
        return f"{minutes:g} minute"
    count = int(minutes)
    if count == 1:
        return "1 minut"
    return f"{count} minute" if count % 100 < ROMANIAN_PLURAL_SMALL_NUMBER_LIMIT and count % 100 != 0 else f"{count} de minute"


def _run_application(skip_browser: bool) -> int:
    """Rulează --aplicatie: pornește serverul local, deschide (sau nu) browserul și așteaptă oprirea.

    Întoarce 0 la oprire normală (Ctrl+C, butonul din pagină, inactivitate) și 1 dacă serverul nu a putut porni.
    Adresa cu tokenul în ea se scrie doar cu print (ecranul utilizatorului), niciodată prin logger: tokenul nu intră în jurnal.
    """
    logger = logging.getLogger(__name__)
    try:
        app = AppServer(log_path=_current_log_path())
    except (OSError, ValueError) as error:
        logger.error("%s", error)
        print(f"\nEROARE: nu am putut porni aplicația locală: {error}")
        return 1
    print(f"\nAplicația rulează doar pe acest calculator, la adresa {app.page_url()}")
    if skip_browser:
        print(f"Adresa completă, cu cheia de acces (nu o da nimănui): {app.page_url(with_token=True)}")
    else:
        opened = open_app_page(app.page_url(with_token=True))
        if opened.opened:
            print("Pagina s-a deschis în browserul tău. Lasă această fereastră deschisă cât folosești aplicația.")
        else:
            print(f"Nu am putut deschide browserul automat ({opened.reason}).")
            print(f"Deschide tu în browser adresa de mai jos (conține cheia de acces; nu o da nimănui):\n  {app.page_url(with_token=True)}")
    print("Ca să oprești aplicația: apasă Ctrl+C în această fereastră sau folosește butonul «Închide aplicația» din pagină.")
    print(f"Se oprește singură după {_minutes_text(app.idle_minutes)} fără activitate.")
    try:
        reason = app.serve()
    finally:
        app.close()
    print("\n" + APP_STOP_MESSAGES.get(reason, GENERIC_APP_STOP_MESSAGE))
    return 0


def _current_log_path() -> Path | None:
    """Fișierul de jurnal al sesiunii curente (primul FileHandler al jurnalului rădăcină), sau None; ajunge în run_info.json al rulărilor din aplicație."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def main(argv: list[str] | None = None) -> int:
    """Rulează programul; întoarce 0 la succes."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    log_path = setup_logging(settings.LOGS_DIR)
    if args.sterge_sesiunea:
        return _delete_saved_session(args.fara_confirmare)
    if args.aplicatie:
        return _run_application(args.fara_browser)
    try:
        if args.doar_login:
            asyncio.run(login_only())
            return 0
        run_dir = run(
            RunOptions(
                threshold_lei=args.prag,
                max_orders=args.limita_comenzi,
                from_cache=args.din_cache,
                output_dir=args.iesire,
                demo=args.demo,
            ),
            log_path=log_path,
        )
    except (RuntimeError, FileNotFoundError, ValueError, PlaywrightError) as error:
        # erori așteptate (login neefectuat, sesiune expirată, cache lipsă, browser închis): mesaj clar, fără traceback
        logging.getLogger(__name__).error("%s", error)
        # Playwright adaugă la mesaj tot „Call log”: în blocul final de eroare doar prima linie; jurnalul de mai sus și fișierul păstrează tot.
        message = str(error).splitlines()[0] if isinstance(error, PlaywrightError) and str(error) else str(error)
        print(f"\nEROARE: {message}\nJurnal complet: {log_path}")
        return 1
    report_path = run_dir / "raport.html"
    if args.deschide and not open_report(report_path):
        print(f"Nu am putut deschide raportul automat. Deschide-l tu din folderul rulării: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
