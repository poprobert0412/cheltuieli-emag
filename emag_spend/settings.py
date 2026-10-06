"""Setările proiectului, într-un singur loc.

Ce conține: adresele eMAG, calea folderelor, pragurile deciziilor de business,
depozitul și codul de repornire ale actualizărilor și valorile care depind de
mediu (citite din variabile de mediu, cu implicit documentat mai jos).
Ce NU face: nu citește fișiere, nu deschide browserul, nu conține reguli de
categorii (acelea stau în config/categorii.json și, personal, în
config/categorii.personal.json).

Variabile de mediu (toate opționale):
  EMAG_BROWSER_CHANNEL   browserul folosit de Playwright: "msedge", "chrome" sau "chromium"
                         (implicit gol = automat: primul instalat dintre ele, în această ordine)
  EMAG_PROFILE_DIR       folderul profilului de browser cu sesiunea logată
                         (implicit <proiect>/.profil_browser); ATENȚIE: cu
                         --sterge-sesiunea acest folder se șterge, deci trebuie
                         să fie un folder DEDICAT programului, nu profilul tău real
  EMAG_FETCH_CONCURRENCY câte pagini de detalii se cer simultan (implicit 3)
  EMAG_LOGIN_WAIT_SECONDS cât așteaptă scriptul să te loghezi manual (implicit 600)
  EMAG_APP_IDLE_MINUTES  după câte minute fără nicio cerere se oprește singură aplicația
                         locală (implicit 30, între 1 și 1440); se citește în app_server.py
  EMAG_UPDATE_CHECK      "0" oprește verificarea automată a versiunii noi la pornirea aplicației
                         locale (implicit pornită: o singură cerere GET spre api.github.com, fără
                         date personale); se citește la fiecare apel, în update_check_enabled()
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BASE_URL = "https://www.emag.ro"
ORDER_LIST_FIRST_PAGE_PATH = "/history/shopping?time=older"
ORDER_LIST_PAGE_PATH = "/history/shopping/{page}?time=older"
ORDER_DETAIL_PATH = "/history/shoppingdetails/{order_id}"
RETURN_LIST_PATH = "/user/return-history"

CATEGORY_RULES_FILE = PROJECT_ROOT / "config" / "categorii.json"
# Regulile personale (titluri de cărți, modele exacte, mașina proprie) stau într-un fișier LOCAL cu acest nume,
# lângă categorii.json, ca regulile publice să rămână generice. Se caută după nume lângă fișierul de reguli
# primit (nu după o cale fixă), ca un test cu reguli în folder temporar să nu citească fișierul real.
PERSONAL_CATEGORY_RULES_FILE_NAME = "categorii.personal.json"
REPORT_TEMPLATE_FILE = PROJECT_ROOT / "templates" / "raport.html"
# Designul raportului (CSS + JS al componentei) are o singură sursă, folosită și
# de site-ul din interfata/. write_report le lipește inline în raport.html, ca
# raportul generat să rămână un singur fișier autonom, fără internet.
DASHBOARD_CSS_FILE = PROJECT_ROOT / "interfata" / "assets" / "dashboard.css"
DASHBOARD_JS_FILE = PROJECT_ROOT / "interfata" / "assets" / "dashboard.js"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUTS_DIR = PROJECT_ROOT / "iesiri"

# Prag pentru "achiziție mare": un produs cu preț STRICT mai mare de atât
# (în lei) este listat separat. 500 de lei e alegerea implicită a proiectului
# (peste ei, o cumpărare se consideră mare). Se poate schimba din linia de
# comandă cu --prag, fără să se modifice codul.
BIG_PURCHASE_THRESHOLD_LEI = 500
# Plafonul acceptat la --prag: 1 miliard de lei e peste orice achiziție reală, iar în bani (×100)
# rămâne mult sub cel mai mare număr întreg sigur din JavaScript (~9·10^15), pe care îl cere
# vizualizatorul la analiza.json. Un prag mai mare (sau inf/nan) ar strica raportul, nu l-ar folosi.
MAX_BIG_PURCHASE_THRESHOLD_LEI = 1_000_000_000

# Categoriile evidențiate separat în raport (alcool și televizoare). Numele
# trebuie să existe în config/categorii.json; pentru fiecare se arată totalul
# și lista produselor.
HIGHLIGHT_CATEGORIES = ("Alcool", "Televizoare")

# Câte pagini de detalii se cer simultan. 3 e prudent: cerem câteva sute de
# pagini din propriul cont și nu vrem să încărcăm serverul eMAG.
FETCH_CONCURRENCY = int(os.environ.get("EMAG_FETCH_CONCURRENCY", "3"))
FETCH_RETRIES = 3
FETCH_BACKOFF_SECONDS = 2.0
FETCH_TIMEOUT_MS = 30_000

# Cât așteptăm ca utilizatorul să se logheze manual în fereastra de browser
# (parola și 2FA le introduce el, scriptul nu le vede). Implicit 10 minute.
LOGIN_WAIT_SECONDS = int(os.environ.get("EMAG_LOGIN_WAIT_SECONDS", "600"))
LOGIN_POLL_SECONDS = 2

# Cât așteptăm ca o pagină de listă (randată de JavaScript) să-și încarce
# comenzile, înainte să o considerăm goală.
LIST_RENDER_TIMEOUT_SECONDS = 25

# Plasă de siguranță: oprește parcurgerea listei dacă paginarea ar da erori.
MAX_LIST_PAGES = 500
MAX_RETURN_LOAD_MORE_CLICKS = 200

# Browserul controlat de program. Gol = automat: primul instalat din AUTO_BROWSER_CHANNELS (Edge există pe orice
# Windows 10/11; pe macOS și Linux de obicei Chrome; altfel Chromium, pe care lansatoarele îl descarcă în .uv/browsere).
BROWSER_CHANNEL = os.environ.get("EMAG_BROWSER_CHANNEL") or None
DOWNLOADED_BROWSER = "chromium"  # numele „browserului” descărcat de Playwright (pornit fără channel)
AUTO_BROWSER_CHANNELS = ("msedge", "chrome", DOWNLOADED_BROWSER)
# Numele implicit al folderului cu sesiunea (cookie-urile eMAG): tratează-l ca pe o parolă, nu-l trimite nimănui.
DEFAULT_PROFILE_DIR_NAME = ".profil_browser"
PROFILE_DIR = Path(os.environ.get("EMAG_PROFILE_DIR", PROJECT_ROOT / DEFAULT_PROFILE_DIR_NAME))

# ---------- actualizări (decis 5 oct. 2026, D2, D4, D10, D12) ----------
# Depozitul GitHub din ale cărui lansări publicate („latest”: fără draft și fără prerelease) vin versiunile noi.
# Un fork își pune aici depozitul lui; nicăieri altundeva în program nu e scris numele depozitului.
UPDATE_REPOSITORY = "poprobert0412/cheltuieli-emag"
# Folderul de lucru al actualizării (arhiva descărcată, extragerea, copia fișierelor vechi, jurnalul, lacătul).
# Nu se atinge niciodată la aplicare (D7) și e în .gitignore.
UPDATE_WORK_DIR = PROJECT_ROOT / ".actualizare"
# Singurul loc al descărcărilor, pentru aplicație și pentru `ruleaza.py --actualizeaza` (decis 6 oct. 2026, N9): fiecare
# descărcare primește aici un subfolder unic (tempfile.mkdtemp(dir=...)), șters la final oricum s-ar fi terminat.
# Testele care mută UPDATE_WORK_DIR îl mută și pe acesta (e calculat o singură dată, la import).
UPDATE_DOWNLOAD_DIR = UPDATE_WORK_DIR / "descarcari"
# Codul de ieșire al lui `ruleaza.py --aplicatie` după o actualizare aplicată din aplicație: lansatorul pornește din nou
# varianta NOUĂ a lui însuși. 75 = EX_TEMPFAIL din sysexits.h; cod ales ca să nu se confunde cu erorile programului, 0 și 1.
EXIT_CODE_RESTART = 75
# Valoarea lui EMAG_UPDATE_CHECK care oprește verificarea automată; orice altă valoare (sau lipsa ei) o lasă pornită.
UPDATE_CHECK_DISABLED_VALUE = "0"


def update_check_enabled() -> bool:
    """True dacă aplicația locală are voie să verifice singură versiunea nouă; False doar pentru EMAG_UPDATE_CHECK="0".

    Citește variabila la FIECARE apel (nu la import), ca testele și utilizatorul s-o poată schimba fără repornirea modulului.
    """
    return os.environ.get("EMAG_UPDATE_CHECK", "").strip() != UPDATE_CHECK_DISABLED_VALUE
