"""Verificările de securitate ale serverului local al aplicației: token, Host, Origin, Content-Type, mărimea corpului, antete.

Primește: valori citite din cerere (antete, cale, id de rulare, nume de fișier). Dă înapoi: da/nu, valori parsate sau
dicționarul de antete de pus pe fiecare răspuns. Funcții pure: fără rețea, fără disc, fără stare, ca să se poată testa
fiecare regulă singură. Serverul (app_server.py) doar le cheamă, în ordinea: Host, Origin, token, apoi restul.
Ce NU face: nu ascultă pe niciun port și nu citește fișiere (app_server.py și app_runs.py).
Modelul de amenințare: o pagină web străină deschisă în același browser sau un alt program de pe calculator. Apărarea:
adresa de bază necunoscută (port ales de sistem), tokenul secret de sesiune, Host/Origin exacte, fără CORS.
"""

import hmac
import json
import re
import secrets
from urllib.parse import urlunsplit

from emag_spend import run_ids

TOKEN_HEADER = "X-App-Token"
# 32 de octeți aleatori = 256 de biți: de neghicit, chiar și cu un atacator care încearcă mii de valori pe secundă.
TOKEN_BYTES = 32

# Numele sub care browserul poate ajunge la server: doar bucla locală. „localhost” e acceptat pentru cine scrie adresa
# de mână; orice alt nume (inclusiv unul care ar rezolva tot la 127.0.0.1, ca la DNS rebinding) e refuzat.
ALLOWED_HOST_NAMES = ("127.0.0.1", "localhost")
HTTP_SCHEME = "http"
# Adresa paginii aplicației și cheia din fragment care poartă tokenul (/aplicatie.html#t=<token>). Fragmentul nu pleacă
# niciodată spre server și nu apare în jurnale; JavaScript-ul îl citește, îl ține în memorie și îl scoate din bara de adrese.
APP_PAGE_PATH = "/aplicatie.html"
TOKEN_FRAGMENT_KEY = "t"
PAGE_HOST = ALLOWED_HOST_NAMES[0]

# Corpul unei cereri POST: cel mai mare corp legitim e {"mode":"real","threshold_lei":1000000000}, sub 100 de octeți;
# 4 KiB lasă loc de câmpuri viitoare, dar un atacator nu poate umple memoria cu o cerere uriașă.
MAX_REQUEST_BODY_BYTES = 4096
# Cifrele lui Content-Length: 12 cifre ajung pentru orice corp pe care l-am citi vreodată și opresc numerele de sute de cifre.
MAX_CONTENT_LENGTH_DIGITS = 12

# Politica de conținut a paginii: fără nimic extern, fără script sau stil inline, fără formulare, fără încadrare în alte pagini.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# Antete puse pe ORICE răspuns, și pe erori. Cache-Control: no-store peste tot (nu doar pe API): după o actualizare a
# programului, o pagină veche din cache ar vorbi cu un API nou. Fără Access-Control-*: nicio pagină străină nu are voie să citească răspunsurile.
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}

# Fișierele care se pot descărca dintr-o rulare și tipul lor; analiza.json se citește doar prin ruta ei, cu limită de mărime.
DOWNLOADABLE_FILES = {
    "raport.html": "text/html; charset=utf-8",
    "produse.csv": "text/csv; charset=utf-8",
    "istoric_preturi.csv": "text/csv; charset=utf-8",
    "rezumat.txt": "text/plain; charset=utf-8",
}

# Singurele caractere dintr-o cale cerută: toate rutele (API și fișiere statice) se scriu cu ele. Orice altceva
# (%, \, :, spațiu, ;, litere cu diacritice, *) e refuzat din start, fără să mai fie decodat sau interpretat.
_PLAIN_PATH = re.compile(r"/[A-Za-z0-9_./-]*")


def new_token() -> str:
    """Un token de sesiune nou, aleator (secrets), potrivit pentru un fragment de URL și un antet HTTP."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_matches(expected: str, provided: str | None) -> bool:
    """True dacă `provided` e exact tokenul așteptat; comparația durează la fel indiferent câte caractere coincid.

    Lipsa tokenului sau un token gol nu trece niciodată (nici măcar când `expected` e gol).
    """
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


def build_app_url(port: int, token: str | None = None) -> str:
    """Adresa paginii aplicației pe `port`; cu `token`, îl pune în fragment (`#t=<token>`), fără token adresa e sigură de afișat."""
    fragment = f"{TOKEN_FRAGMENT_KEY}={token}" if token else ""
    return urlunsplit((HTTP_SCHEME, f"{PAGE_HOST}:{port}", APP_PAGE_PATH, "", fragment))


def allowed_hosts(port: int) -> frozenset[str]:
    """Valorile acceptate pentru antetul Host: `127.0.0.1:<port>` și `localhost:<port>`, cu portul serverului."""
    return frozenset(f"{name}:{port}" for name in ALLOWED_HOST_NAMES)


def is_allowed_host(host_header: str | None, port: int) -> bool:
    """True dacă Host e exact una din valorile permise (anti DNS-rebinding: un nume străin care rezolvă la 127.0.0.1 nu trece)."""
    return host_header in allowed_hosts(port)


def allowed_origins(port: int) -> frozenset[str]:
    """Originile acceptate: adresa serverului ca în Host, cu schema http (fără cale, fără slash final)."""
    return frozenset(urlunsplit((HTTP_SCHEME, host, "", "", "")) for host in allowed_hosts(port))


def is_allowed_origin(origin_header: str | None, port: int) -> bool:
    """True dacă Origin lipsește (cerere de aceeași origine fără antet) sau e exact originea serverului.

    `Origin: null` și orice origine străină se refuză: o pagină de pe alt site care trimite o cerere spre server nu trece.
    """
    return origin_header is None or origin_header in allowed_origins(port)


def is_json_content_type(value: str | None) -> bool:
    """True pentru `application/json` (cu cel mult `charset=utf-8`); orice altceva, inclusiv lipsa, e fals.

    Un formular HTML dintr-o pagină străină nu poate trimite application/json fără o verificare prealabilă CORS,
    pe care serverul n-o acceptă: asta oprește cererile „simple” (text/plain, formulare) trimise pe ascuns.
    """
    if not isinstance(value, str):
        return False
    media_type, _, parameters = value.partition(";")
    if media_type.strip().lower() != "application/json":
        return False
    for parameter in parameters.split(";"):
        parameter = parameter.strip()
        if not parameter:
            continue
        name, _, parameter_value = parameter.partition("=")
        if name.strip().lower() != "charset" or parameter_value.strip().strip('"').lower() != "utf-8":
            return False
    return True


def parse_content_length(value: str | None) -> int | None:
    """Lungimea corpului din antetul Content-Length; 0 dacă antetul lipsește, None dacă valoarea nu e un număr valid.

    Doar cifre ASCII (fără semn, fără spații, fără zecimale): „-1”, „+5”, „1e3” și „٣” (cifră arabă) sunt invalide.
    """
    if value is None:
        return 0
    if not value.isascii() or not value.isdigit() or len(value) > MAX_CONTENT_LENGTH_DIGITS:
        return None
    return int(value)


def exceeds_body_limit(length: int) -> bool:
    """True dacă un corp de `length` octeți depășește MAX_REQUEST_BODY_BYTES."""
    return length > MAX_REQUEST_BODY_BYTES


def _reject_json_constant(name: str):
    """Înlocuiește NaN/Infinity (acceptate de Python, dar nu de JSON.parse din browser) cu o eroare."""
    raise ValueError(f"constanta {name} nu e JSON valid")


def parse_strict_json(data: bytes) -> object:
    """Parsează `data` ca JSON UTF-8 strict (fără NaN/Infinity), la fel ca JSON.parse din browser.

    Ridică ValueError (și UnicodeDecodeError, care e tot ValueError) sau RecursionError (imbricare absurdă) dacă nu e valid.
    """
    return json.loads(data.decode("utf-8"), parse_constant=_reject_json_constant)


def is_plain_request_path(path: str) -> bool:
    """True dacă `path` (fără query) începe cu / și conține doar litere, cifre, `_`, `.`, `-` și `/`, fără `..` și fără `//`.

    Se verifică ÎNAINTE de orice rutare: `%2e%2e`, `\\`, `::$DATA`, nume 8.3 cu `~`, majuscule neașteptate etc. nu ajung la
    alte verificări, pentru că rutele reale nu au nevoie de aceste caractere.
    """
    return bool(_PLAIN_PATH.fullmatch(path)) and ".." not in path and "//" not in path


def is_valid_run_id(text: object) -> bool:
    """True dacă `text` e exact un id de rulare (numele unui folder din iesiri/: `<data>_<ora>` sau cu `_demo`)."""
    return run_ids.parse_run_id(text) is not None


def download_content_type(name: object) -> str | None:
    """Tipul de conținut al fișierului descărcabil `name` (exact unul din DOWNLOADABLE_FILES, cu litere mici) sau None."""
    return DOWNLOADABLE_FILES.get(name) if isinstance(name, str) else None


def security_headers() -> dict[str, str]:
    """O copie nouă a antetelor de securitate (cine o primește o poate completa fără să strice constanta)."""
    return dict(SECURITY_HEADERS)


# Cât dintr-o valoare venită din cerere (metodă, cale) intră în jurnal: destul ca s-o recunoști, nu cât să umple fișierul.
LOG_VALUE_LIMIT = 120


def loggable(value: object, limit: int = LOG_VALUE_LIMIT) -> str:
    """`value` ca text sigur pentru un singur rând de jurnal: fără CR/LF (nu se pot falsifica rânduri), caracterele
    de control înlocuite cu „?”, tăiat la `limit` caractere. Pentru tot ce vine din cerere: cale, metodă, antete."""
    text = str(value).replace("\r", "").replace("\n", "")
    return "".join(ch if ch.isprintable() else "?" for ch in text)[:limit]
