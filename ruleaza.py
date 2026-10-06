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
    python ruleaza.py --versiune           scrie versiunea programului („Cheltuieli eMAG X.Y.Z”); nu se combină cu alte opțiuni
    python ruleaza.py --actualizeaza       caută pe GitHub o versiune nouă, arată ce e nou și, după ce scrii exact DA, o descarcă,
                                           îi verifică amprenta și o instalează (datele tale rămân); nu se combină cu alte
                                           opțiuni, în afară de:
    python ruleaza.py --actualizeaza --fara-confirmare   fără întrebare (pentru scripturi și teste)
Rezultatele apar în iesiri/<data>_<ora>/ (raport.html, produse.csv, rezumat.txt).
O actualizare întreruptă (curent căzut, fereastră închisă) se anulează la pornire. porneste.bat, porneste.sh și porneste.command o fac
înaintea pregătirii, prin `python -m emag_spend.update_recovery` (decis 6 oct. 2026, P1); aici, înaintea oricărui alt import din
emag_spend (N2), se face pentru orice altă pornire: programul revine la versiunea veche, spune asta, trece în jurnal tot ce a notat
recuperarea (P6) și face apoi comanda cerută; dacă revenirea nu se poate face acum (alt proces aplică o actualizare, jurnal deteriorat,
fișier blocat), scrie de ce (pe ecran și în logs/) și iese cu 1, fără să ruleze altceva.
--aplicatie iese cu codul 75 după o actualizare instalată din pagină: porneste.bat, porneste.command și porneste.sh îl pornesc din nou
singuri; pornit direct (python ruleaza.py --aplicatie), spune să fie pornit din nou.
"""

import argparse
import asyncio
import logging
import math
import sys
from pathlib import Path

# N2: recuperarea rulează înaintea oricărui alt import din emag_spend sau din pachete. După o actualizare întreruptă arborele poate fi
# amestecat (un modul nou care cere altul încă nemutat), iar orice import de mai jos ar putea cădea înainte ca programul să revină.
# update_recovery.py folosește doar biblioteca standard și update_lock.py (garda: tests/test_update_recovery.py).
from emag_spend.update_recovery import LOG_STARTUP_OUTCOME, LOGS_DIR_NAME, RecoveryOutcome, recover_before_start, write_startup_log

PROGRAM_FOLDER = Path(__file__).resolve().parent
STARTUP_RECOVERY: RecoveryOutcome = recover_before_start(PROGRAM_FOLDER)
if STARTUP_RECOVERY.error is not None and __name__ == "__main__":
    # Fișierele pot fi încă amestecate (sau alt proces le mută chiar acum): nimic altceva din program nu se importă sau rulează,
    # nici run_logger. Urma în logs/ (ce fișier a blocat, P6) o scrie recuperarea, tot doar cu biblioteca standard.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        write_startup_log(PROGRAM_FOLDER / LOGS_DIR_NAME, STARTUP_RECOVERY)
    except OSError:
        pass  # fără jurnal pe disc, eroarea tot se afișează
    print(f"\nEROARE: {STARTUP_RECOVERY.error}")
    raise SystemExit(1)

# Abia de aici încolo: restul programului, din versiunea întreagă (veche sau nouă) lăsată de recuperare.
from playwright.async_api import Error as PlaywrightError

from emag_spend import session_cleaner, settings
from emag_spend.app_opener import open_app_page
from emag_spend.app_server import STOP_IDLE, STOP_INTERRUPTED, STOP_SHUTDOWN, STOP_UPDATED, AppServer
from emag_spend.browser_session import login_only
from emag_spend.report_opener import open_report
from emag_spend.run_logger import setup_logging
from emag_spend.run_pipeline import RunOptions, run
from emag_spend.update_apply import MESSAGE_GIT_CHECKOUT, PROGRESS_INSTALLING, apply_update, is_git_checkout
from emag_spend.update_check import STATUS_NEW, STATUS_UP_TO_DATE, check_for_update
from emag_spend.update_download import STAGE_DOWNLOAD, STAGE_VERIFY, download_folder, download_release
from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION

PROGRAM_NAME = "Cheltuieli eMAG"
# Opțiunile care fac singure o treabă întreagă (ștergere, server, actualizare, versiune) și singurele opțiuni acceptate lângă ele:
# nu se amestecă cu nimic care citește contul sau face un raport.
EXCLUSIVE_OPTIONS = {
    "--sterge-sesiunea": ("--fara-confirmare",),
    "--aplicatie": ("--fara-browser",),
    "--actualizeaza": ("--fara-confirmare",),
    "--versiune": (),
}
# Opțiunile care au sens doar lângă una dintre cele de mai sus.
COMPANION_OPTIONS = {
    "--fara-confirmare": ("--sterge-sesiunea", "--actualizeaza"),
    "--fara-browser": ("--aplicatie",),
}
# Ce se scrie pe ecran la fiecare etapă raportată de download_release și apply_update.
UPDATE_STAGE_MESSAGES = {
    STAGE_DOWNLOAD: "Descarc arhiva versiunii noi de pe GitHub...",
    STAGE_VERIFY: "Verific amprenta SHA-256 a arhivei...",
    PROGRESS_INSTALLING: "Instalez versiunea nouă (datele tale din iesiri/, logs/ și sesiunea eMAG rămân neatinse)...",
}
UPDATE_INTERRUPTED_MESSAGE = ("Actualizarea a fost oprită cu Ctrl+C. Dacă instalarea începuse, programul a revenit la versiunea veche "
                              "(sau revine singur la pornirea următoare).")


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
                        help="doar cu --sterge-sesiunea sau --actualizeaza: nu mai întreabă (pentru scripturi și teste)")
    parser.add_argument("--aplicatie", action="store_true",
                        help="pornește aplicația locală cu un singur buton (server doar pe acest calculator, pagina în browser); nu se combină cu alte opțiuni")
    parser.add_argument("--fara-browser", action="store_true",
                        help="doar cu --aplicatie: nu deschide browserul și scrie adresa completă, cu cheia de acces (pentru teste, WSL, servere)")
    parser.add_argument("--versiune", action="store_true", help=f"scrie versiunea programului ({PROGRAM_NAME} X.Y.Z); se folosește singură")
    parser.add_argument("--actualizeaza", action="store_true",
                        help="caută o versiune nouă pe GitHub și o instalează după confirmare; nu se combină cu alte opțiuni")
    args = parser.parse_args(argv)
    used = [flag for flag, present in (
        ("--prag", args.prag is not None), ("--limita-comenzi", args.limita_comenzi is not None),
        ("--din-cache", args.din_cache is not None), ("--iesire", args.iesire is not None),
        ("--deschide", args.deschide), ("--doar-login", args.doar_login), ("--demo", args.demo),
        ("--sterge-sesiunea", args.sterge_sesiunea), ("--aplicatie", args.aplicatie), ("--actualizeaza", args.actualizeaza),
        ("--versiune", args.versiune), ("--fara-confirmare", args.fara_confirmare), ("--fara-browser", args.fara_browser)) if present]
    for option, allowed in EXCLUSIVE_OPTIONS.items():
        others = [flag for flag in used if flag != option and flag not in allowed]
        if option in used and others:
            company = f"doar cu {' sau '.join(allowed)}" if allowed else "se folosește singură"
            parser.error(f"{option} nu se combină cu {', '.join(others)} ({company})")
    for option, partners in COMPANION_OPTIONS.items():
        if option in used and not any(partner in used for partner in partners):
            parser.error(f"{option} se folosește doar împreună cu {' sau '.join(partners)}")
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
    STOP_UPDATED: ("Programul a fost actualizat. Lansatorul (porneste.bat, porneste.command, porneste.sh) îl pornește din nou singur, "
                   "cu versiunea nouă; dacă l-ai pornit altfel, pornește-l tu din nou."),
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

    Întoarce 0 la oprire normală (Ctrl+C, butonul din pagină, inactivitate), settings.EXIT_CODE_RESTART după o actualizare
    instalată din pagină (lansatorul pornește varianta nouă, D12) și 1 dacă serverul nu a putut porni.
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
    if reason == STOP_UPDATED:
        logger.info("aplicația s-a oprit după actualizare: ies cu codul %d (repornire)", settings.EXIT_CODE_RESTART)
        return settings.EXIT_CODE_RESTART
    return 0


def _confirm_update(version: str) -> bool:
    """Cere să scrii exact DA înainte de instalare; orice altceva, EOF sau Ctrl+C înseamnă „nu” (nu se schimbă nimic)."""
    word = session_cleaner.CONFIRMATION_WORD
    try:
        answer = input(f"\nScrie exact {word} (cu majuscule) ca să instalezi versiunea {version}; orice altceva anulează: ")
    except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
        print("")
        return False
    return answer.strip() == word


def _print_update_stage(stage: str) -> None:
    """Scrie pe ecran etapa actualizării (descarc, verific, instalez); o etapă necunoscută se ignoră."""
    if stage in UPDATE_STAGE_MESSAGES:
        print(UPDATE_STAGE_MESSAGES[stage])


def _run_update(skip_confirmation: bool) -> int:
    """Rulează --actualizeaza: caută ultima lansare, arată ce e nou, cere DA, descarcă, verifică amprenta și instalează (D3, D19).

    Descarcă într-un subfolder nou și unic din settings.UPDATE_DOWNLOAD_DIR (update_download.download_folder), șters la final
    oricum s-ar fi terminat (N9). Întoarce 0 după instalare (programul trebuie pornit din nou), la „ai ultima versiune” și la anulare;
    1 la orice eroare, cu mesaj în română și fără traceback. Nu repornește nimic: versiunea nouă se încarcă la următoarea pornire.
    """
    logger = logging.getLogger(__name__)
    print(f"Versiunea instalată: {VERSION}. Caut pe GitHub o versiune nouă...")
    check = check_for_update(enabled=True)
    if check.status == STATUS_UP_TO_DATE:
        print(check.message)
        return 0
    if check.status != STATUS_NEW or check.release is None:
        print(f"\nEROARE: {check.message}" + (f"\nPagina lansărilor: {check.page_url}" if check.page_url else ""))
        return 1
    published = f", publicată {check.published[:10]}" if check.published else ""
    print(f"\nVersiune nouă: {check.latest} (ai {check.current}{published}).")
    if check.notes:
        print(f"\nCe e nou:\n{check.notes}")
    if is_git_checkout(settings.PROJECT_ROOT):
        print(f"\nEROARE: {MESSAGE_GIT_CHECKOUT}")
        return 1
    if not skip_confirmation and not _confirm_update(check.latest):
        print("\nAnulat: nu am schimbat nimic.")
        return 0
    try:
        with download_folder(settings.UPDATE_DOWNLOAD_DIR) as download_dir:
            archive = download_release(check.release, download_dir, progress=_print_update_stage)
            result = apply_update(archive, settings.PROJECT_ROOT, check.release.version, progress=_print_update_stage)
    except UpdateError as error:
        logger.error("actualizare la %s eșuată: %s", check.latest, error)
        print(f"\nEROARE: {error}")
        return 1
    except KeyboardInterrupt:  # apply_update a revenit deja la versiunea veche înainte să lase Ctrl+C să treacă
        logger.warning("actualizare la %s oprită cu Ctrl+C", check.latest)
        print(f"\n{UPDATE_INTERRUPTED_MESSAGE}")
        return 1
    logger.info("actualizare: %s → %s (%d fișiere scrise, %d șterse)", result.from_version, result.to_version, result.written, result.deleted)
    print(f"\nActualizat la {result.to_version}. Pornește din nou programul.")
    return 0


def _report_startup_recovery(outcome: RecoveryOutcome) -> tuple[int | None, Path | None]:
    """Spune ce a făcut recuperarea de la pornire (N2) și o trece în jurnal; întoarce (cod de ieșire sau None, calea jurnalului sau None).

    Fără nimic de spus și nimic notat: (None, None) și niciun jurnal creat. Altfel jurnalul se configurează acum și primește întâi ce a
    notat recuperarea înaintea lui (outcome.records, cu ora lor: fișiere blocate, curățenii ratate, P6), apoi rezultatul. După o revenire:
    mesajul, iar programul continuă cu comanda cerută (modulele s-au importat abia după revenire, deci sunt toate din versiunea veche,
    întreagă). Dacă revenirea nu s-a putut face: 1.
    """
    if outcome.message is None and outcome.error is None and not outcome.records:
        return None, None
    log_path = setup_logging(settings.LOGS_DIR)
    for record in outcome.records:
        logging.getLogger(record.name).handle(record)
    logger = logging.getLogger(__name__)
    if outcome.error is not None:
        logger.error(LOG_STARTUP_OUTCOME, outcome.error)
        print(f"\nEROARE: {outcome.error}")
        return 1, log_path
    if outcome.message is not None:
        logger.warning(LOG_STARTUP_OUTCOME, outcome.message)
        print(f"\n{outcome.message}\n")
    return None, log_path


def _current_log_path() -> Path | None:
    """Fișierul de jurnal al sesiunii curente (primul FileHandler al jurnalului rădăcină), sau None; ajunge în run_info.json al rulărilor din aplicație."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def main(argv: list[str] | None = None) -> int:
    """Rulează programul; întoarce 0 la succes, 1 la eroare și settings.EXIT_CODE_RESTART când trebuie pornit din nou.

    Întâi spune ce a făcut recuperarea de la import (STARTUP_RECOVERY); dacă ea n-a reușit, iese cu 1 fără să citească opțiunile.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    stopped, recovery_log = _report_startup_recovery(STARTUP_RECOVERY)
    if stopped is not None:
        return stopped
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.versiune:
        print(f"{PROGRAM_NAME} {VERSION}")
        return 0
    log_path = recovery_log or setup_logging(settings.LOGS_DIR)
    if args.sterge_sesiunea:
        return _delete_saved_session(args.fara_confirmare)
    if args.actualizeaza:
        return _run_update(args.fara_confirmare)
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
