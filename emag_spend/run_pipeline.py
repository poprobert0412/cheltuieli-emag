"""Rulează tot fluxul: colectare (sau cache) -> analiză -> fișiere de ieșire.

Primește: opțiunile din linia de comandă (și, de la aplicația locală: un raportor de progres, un nume de folder ales dinainte, demo fără rescrierea lui demo-data.js).
Dă înapoi: folderul rulării (`iesiri/<data>_<ora>[_demo]/`) cu comenzi.json, retururi.json, analiza.json, raport.html, produse.csv, istoric_preturi.csv, rezumat.txt și run_info.json (căi relative la proiect, fără numele contului de Windows).
Datele se scriu pe măsură ce sosesc: o rulare care pică la retururi lasă comenzile pe disc. Cu `demo=True` comenzile vin din datele inventate (demo_data.py), regulile personale de categorii se ignoră, iar la final se rescrie `interfata/assets/demo-data.js` (site_demo_writer.py), în afară de `update_site_demo_data=False`.
Regulile de categorii, textele avertismentelor și culorile produselor se verifică ÎNAINTE de colectare: o greșeală oprește rularea în secunde, nu după ore."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from emag_spend import run_ids, run_store, settings
from emag_spend.classifier import Classifier
from emag_spend.csv_export import write_lines_csv
from emag_spend.demo_data import demo_orders_and_returns
from emag_spend.emag_collector import collect_all
from emag_spend.price_history_csv import write_price_history_csv
from emag_spend.product_key import COLOR_WORDS_FILE, load_color_words
from emag_spend.progress import NO_PROGRESS, PHASE_ANALYZING, Progress
from emag_spend.report_html import write_report
from emag_spend.site_demo_writer import DEMO_META_KEY, write_demo_data_js
from emag_spend.spend_analysis import analyze
from emag_spend.summary_text import build_summary_text
from emag_spend.warning_details import WARNING_TEXTS_FILE, load_warning_texts

logger = logging.getLogger(__name__)


@dataclass
class RunOptions:
    """Opțiunile unei rulări."""

    threshold_lei: float = settings.BIG_PURCHASE_THRESHOLD_LEI
    max_orders: int | None = None  # doar pentru teste rapide pe câteva comenzi
    from_cache: Path | None = None  # folder de rulare salvat: fără browser
    output_dir: Path | None = None
    demo: bool = False  # comenzi inventate, fără browser și fără login
    demo_data_js: Path | None = None  # doar la demo: unde se scrie demo-data.js (None = cel din interfata/)
    update_site_demo_data: bool = True  # False = la demo nu se rescrie demo-data.js (aplicația locală; linia de comandă îl rescrie)
    run_folder_name: str | None = None  # numele folderului rulării, ales dinainte (id din run_ids.py); None = se alege la start


def _project_relative(path: Path) -> str:
    """Calea relativă la rădăcina proiectului; în afara proiectului doar numele fișierului sau folderului.

    Pentru run_info.json: o cale absolută de Windows conține numele contului local.
    """
    try:
        return str(Path(path).resolve().relative_to(settings.PROJECT_ROOT))
    except ValueError:
        return Path(path).name


def _load_classifier(include_personal: bool = True) -> Classifier:
    """Citește regulile de categorii și verifică că fiecare categorie evidențiată există în ele.

    Ridică ValueError dacă una lipsește: altfel raportul ar arăta „0,00 Lei, niciun produs” la ea,
    un rezultat greșit care pare normal. `include_personal=False` ignoră regulile personale
    (la demo: comenzile inventate se clasifică la fel pe orice calculator).
    """
    classifier = Classifier.from_file(settings.CATEGORY_RULES_FILE, include_personal=include_personal)
    known = set(classifier.category_names) | {classifier.default_category}  # și „Necategorizat” are totaluri reale
    missing = [name for name in settings.HIGHLIGHT_CATEGORIES if name not in known]
    if missing:
        names = ", ".join(f"«{name}»" for name in missing)
        raise ValueError(
            f"categoria evidențiată {names} nu există în {settings.CATEGORY_RULES_FILE.name}: "
            "adaug-o în reguli sau scoate-o din HIGHLIGHT_CATEGORIES (emag_spend/settings.py)"
        )
    return classifier


def _new_run_dir(base: Path | None, demo: bool = False, folder_name: str | None = None) -> Path:
    """Creează folderul rulării: `<iesiri>/<data>_<ora>[_demo]/`, sortabil cronologic.

    `folder_name` (dacă e dat) trebuie să fie un id valid din run_ids.py: ajunge în calea unui folder, deci altceva se refuză.
    """
    if folder_name is not None and run_ids.parse_run_id(folder_name) is None:
        raise ValueError(f"numele folderului rulării «{folder_name}» nu are forma <data>_<ora>[_demo]")
    stamp = folder_name or run_ids.new_run_id(datetime.now(), demo)
    folder = (base or settings.OUTPUTS_DIR) / stamp
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run(options: RunOptions, log_path: Path | None = None, progress: Progress = NO_PROGRESS) -> Path:
    """Execută fluxul complet și întoarce folderul cu rezultatele.

    `progress` primește fazele rulării (login, comenzi, retururi, analiză) și poate cere oprirea (RunCancelled).
    """
    started = datetime.now()
    classifier = _load_classifier(include_personal=not options.demo)  # înainte de colectare și de crearea folderului: o greșeală de reguli nu lasă nimic pe disc
    warning_texts = load_warning_texts(WARNING_TEXTS_FILE)  # la fel: un config/avertismente.json greșit oprește rularea înainte să înceapă
    color_words = load_color_words(COLOR_WORDS_FILE)  # idem pentru config/culori.json
    run_dir = _new_run_dir(options.output_dir, options.demo, options.run_folder_name)
    logger.info("folder rulare: %s", run_dir)
    threshold_bani = round(options.threshold_lei * 100)

    if options.demo:
        orders, returns = demo_orders_and_returns()
        logger.info("mod demonstrație: %d comenzi și %d retururi inventate", len(orders), len(returns))
        run_store.save_orders(run_dir, orders)
        run_store.save_returns(run_dir, returns)
    elif options.from_cache:
        orders, returns = run_store.load_run(options.from_cache)
        logger.info("date încărcate din %s: %d comenzi, %d retururi", options.from_cache, len(orders), len(returns))
        run_store.save_orders(run_dir, orders)
        run_store.save_returns(run_dir, returns)
    else:
        orders, returns = asyncio.run(
            collect_all(
                max_orders=options.max_orders,
                on_orders=lambda o: run_store.save_orders(run_dir, o),
                on_returns=lambda r: run_store.save_returns(run_dir, r),
                progress=progress,
            )
        )

    progress.phase(PHASE_ANALYZING)
    analysis = analyze(
        orders,
        returns,
        classifier,
        threshold_bani,
        generated_at=f"{datetime.now():%Y-%m-%d %H:%M}",
        highlight_categories=settings.HIGHLIGHT_CATEGORIES,
        warning_texts=warning_texts,
        color_words=color_words,
    )
    if options.demo:
        analysis.summary["meta"][DEMO_META_KEY] = True  # comenzi inventate: raportul nu face linkuri spre eMAG pentru ele
    run_store.save_json(run_dir, "analiza.json", analysis.summary)
    write_report(run_dir / "raport.html", settings.REPORT_TEMPLATE_FILE, analysis.summary)
    write_lines_csv(run_dir / "produse.csv", analysis.lines, threshold_bani)
    write_price_history_csv(run_dir / "istoric_preturi.csv", analysis.summary["price_history"])
    text = build_summary_text(analysis.summary)
    (run_dir / "rezumat.txt").write_text(text, encoding="utf-8")
    run_store.save_json(run_dir, "run_info.json", {
        "pornit": f"{started:%Y-%m-%d %H:%M:%S}",
        "terminat": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "prag_lei": options.threshold_lei,
        "limita_comenzi": options.max_orders,
        "din_cache": _project_relative(options.from_cache) if options.from_cache else None,
        "demo": options.demo,
        "comenzi": len(orders),
        "retururi": len(returns),
        "regulile_de_categorii": _project_relative(settings.CATEGORY_RULES_FILE),
        "reguli_personale": classifier.personal_source,  # numele fișierului personal folosit, sau None (la --demo: niciodată)
        "textele_avertismentelor": _project_relative(WARNING_TEXTS_FILE),
        "culorile_produselor": _project_relative(COLOR_WORDS_FILE),
        "jurnal": _project_relative(log_path) if log_path else None,
    })
    if options.demo and options.update_site_demo_data:
        logger.info("demo-data.js pentru site rescris: %s", write_demo_data_js(options.demo_data_js))
    print("\n" + text + f"\n\nRaport: {run_dir / 'raport.html'}")
    return run_dir
