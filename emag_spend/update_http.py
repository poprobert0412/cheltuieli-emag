"""Singurul client HTTPS al programului: citește lansările de pe GitHub pentru actualizări (decis 5 oct. 2026, D5).

Primește: o adresă https spre o gazdă din ALLOWED_HOSTS, o limită de octeți și un timeout (constantele stau la apelanți).
Dă înapoi: JSON-ul răspunsului (get_json) sau fișierul descărcat (download_to: scris în <țintă>.part, apoi mutat cu os.replace).
Reguli: doar https, certificat verificat, fiecare redirecționare verificată (schemă + gazdă) ÎNAINTE să fie urmată, cel mult
MAX_REDIRECTS; fără proxy, fără cookie-uri, fără autentificare; timeout pe fiecare operație și, la descărcare, un termen total
(DOWNLOAD_TOTAL_SECONDS). Orice eșec devine UpdateError cu mesaj în română.
Ce NU face: nu alege ce se descarcă și nu verifică amprente (update_check.py, update_download.py).
"""

import http.client
import json
import os
import re
import ssl
import time
import urllib.error
from contextlib import closing
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPSHandler, OpenerDirector, Request, UnknownHandler

from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION

# Gazdele permise, exact (D5): API-ul lansărilor, pagina lansărilor și cele două gazde la care GitHub redirecționează
# descărcarea activelor. Orice altă gazdă, inclusiv într-o redirecționare, oprește cererea.
ALLOWED_HOSTS = frozenset({"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})
ALLOWED_SCHEME = "https"
HTTPS_PORT = 443
# GitHub trimite o redirecționare de la github.com la gazda activelor; 5 lasă loc pentru încă un ocol fără să permită bucle.
MAX_REDIRECTS = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
OK_STATUS = 200
NOT_FOUND_STATUS = 404
RATE_LIMIT_STATUS = 429
FORBIDDEN_STATUS = 403
FIRST_SERVER_ERROR_STATUS = 500
# Adresele semnate ale activelor GitHub au ~1-2 mii de caractere; 8192 le acoperă cu marjă și oprește adrese absurde.
MAX_URL_CHARS = 8192
# Cât se citește odată din răspuns: destul de mare pentru viteză, destul de mic cât limita de octeți să fie respectată fin.
READ_CHUNK_BYTES = 64 * 1024
USER_AGENT = f"cheltuieli-emag/{VERSION}"
JSON_ACCEPT = "application/vnd.github+json"
DOWNLOAD_ACCEPT = "application/octet-stream"
PART_SUFFIX = ".part"
# Termenul TOTAL al unei descărcări (decis 6 oct. 2026, N11), peste timeout-ul pe operație, care pornește din nou la fiecare
# bloc primit și deci nu oprește un transfer care tot curge, oricât de încet. Arhiva are câțiva MB (câteva secunde pe o rețea
# obișnuită); 15 minute trec și de limita de 100 MB a lui update_download la ~115 KB/s, dar nu țin un fir agățat o zi.
DOWNLOAD_TOTAL_SECONDS = 15 * 60
# Content-Length anunțat: doar cifre ASCII (str.isdigit acceptă și „²”, pe care int() nu-l mai înțelege); 20 de cifre trec de orice mărime reală.
_DECIMAL = re.compile(r"[0-9]{1,20}")

MESSAGE_BAD_URL = "Adresa cerută nu e una permisă (doar https spre GitHub); din siguranță, nu continui."
MESSAGE_BAD_REDIRECT = "GitHub a trimis o redirecționare spre o adresă nepermisă; din siguranță, nu continui."
MESSAGE_NO_LOCATION = "GitHub a trimis o redirecționare fără adresă; încearcă mai târziu."
MESSAGE_TOO_MANY_REDIRECTS = f"Prea multe redirecționări (peste {MAX_REDIRECTS}); din siguranță, nu continui."
MESSAGE_NO_INTERNET = "Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată."
MESSAGE_TIMEOUT = "GitHub nu răspunde (a expirat timpul de așteptare); încearcă mai târziu."
MESSAGE_BAD_CERTIFICATE = "Conexiunea la GitHub nu are un certificat valid; din siguranță, nu continui."
MESSAGE_TLS_FAILED = "Conexiunea securizată la GitHub a eșuat; încearcă mai târziu."
MESSAGE_INTERRUPTED = "Conexiunea la GitHub s-a întrerupt în timpul transferului; încearcă din nou."
MESSAGE_RATE_LIMIT = "Limita de cereri GitHub a fost atinsă; încearcă peste o oră."
MESSAGE_NOT_FOUND = "Lansarea nu există pe GitHub (răspuns 404)."
MESSAGE_SERVER_ERROR = "GitHub nu răspunde acum (eroare {status}); încearcă mai târziu."
MESSAGE_REFUSED = "GitHub a refuzat cererea (răspuns {status})."
MESSAGE_UNEXPECTED_STATUS = "GitHub a răspuns neașteptat (cod {status})."
MESSAGE_TOO_BIG = "Răspunsul GitHub depășește limita de {limit} octeți; din siguranță, nu continui."
MESSAGE_BAD_JSON = "GitHub a trimis un răspuns pe care programul nu-l înțelege."
MESSAGE_DISK = "Nu pot scrie fișierul descărcat pe disc ({detail})."
MESSAGE_TOTAL_TIMEOUT = (f"Descărcarea de pe GitHub a durat peste {DOWNLOAD_TOTAL_SECONDS // 60} min, așa că am oprit-o; "
                         "încearcă din nou mai târziu.")


def _is_plain_ascii(text: str) -> bool:
    """True dacă `text` are doar ASCII vizibil, fără „\\”: urlsplit și urljoin scot în tăcere TAB și rândul nou, deci se verifică înainte."""
    return all("!" <= char <= "~" and char != "\\" for char in text)


def is_allowed_url(url: object) -> bool:
    """True doar pentru https://<gazdă din ALLOWED_HOSTS>[:443]/..., ASCII vizibil, fără utilizator/parolă; altfel False, fără excepții."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS or not _is_plain_ascii(url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == ALLOWED_SCHEME and (parts.hostname or "") in ALLOWED_HOSTS and "@" not in parts.netloc
            and parts.username is None and parts.password is None and port in (None, HTTPS_PORT))


def _build_opener() -> OpenerDirector:
    """Deschizătorul urllib cu DOAR handler-ul HTTPS (certificat și nume verificate) și cel pentru scheme necunoscute.

    Fără ProxyHandler (nicio conexiune spre alt calculator decât GitHub și nicio citire a setărilor de proxy din sistem),
    fără cookie-uri, fără http/ftp/file/data și fără redirecționări automate: _follow le verifică una câte una.
    """
    opener = OpenerDirector()
    opener.addheaders = []  # fără antetul implicit „Python-urllib”: User-Agent-ul îl pune _open_once
    opener.add_handler(HTTPSHandler(context=ssl.create_default_context()))
    opener.add_handler(UnknownHandler())
    return opener


def _connection_error(error: BaseException, *, during_transfer: bool) -> UpdateError:
    """Traduce o eroare de rețea (urllib, ssl, socket, http.client) în UpdateError cu mesaj pentru utilizator."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return UpdateError(MESSAGE_BAD_CERTIFICATE)
    if isinstance(reason, TimeoutError):
        return UpdateError(MESSAGE_TIMEOUT)
    if isinstance(reason, ssl.SSLError):
        return UpdateError(MESSAGE_TLS_FAILED)
    if during_transfer or isinstance(reason, http.client.HTTPException):
        return UpdateError(MESSAGE_INTERRUPTED)
    return UpdateError(MESSAGE_NO_INTERNET)


def _open_once(url: str, accept: str, timeout: float):
    """O singură cerere GET (fără să urmeze redirecționări); întoarce răspunsul, oricare ar fi codul lui. Ridică UpdateError."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept}, method="GET")
    try:
        return _build_opener().open(request, timeout=timeout)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise _connection_error(error, during_transfer=False) from error


def _check_deadline(deadline) -> None:
    """Ridică UpdateError(MESSAGE_TOTAL_TIMEOUT) dacă termenul total a trecut; `deadline` = None (fără termen) sau (ceas, ora limită)."""
    if deadline is None:
        return
    clock, limit = deadline
    if clock() > limit:
        raise UpdateError(MESSAGE_TOTAL_TIMEOUT)


def _follow(url: str, accept: str, timeout: float, deadline=None):
    """Cere `url` și urmează redirecționările, fiecare verificată cu is_allowed_url înainte de cerere; întoarce răspunsul final.

    `deadline` (vezi _check_deadline) se verifică înaintea fiecărei cereri, deci și a fiecărei redirecționări.
    """
    if not is_allowed_url(url):
        raise UpdateError(MESSAGE_BAD_URL)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_deadline(deadline)
        response = _open_once(current, accept, timeout)
        if response.status not in REDIRECT_STATUSES:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise UpdateError(MESSAGE_NO_LOCATION)
        if not _is_plain_ascii(location):  # înainte de urljoin, care ar scoate caracterele ascunse și ar „curăța” adresa
            raise UpdateError(MESSAGE_BAD_REDIRECT)
        current = urljoin(current, location)
        if not is_allowed_url(current):
            raise UpdateError(MESSAGE_BAD_REDIRECT)
    raise UpdateError(MESSAGE_TOO_MANY_REDIRECTS)


def _require_ok(response) -> None:
    """Ridică UpdateError dacă răspunsul final nu e 200 (limita de cereri GitHub, 404, 5xx, alt cod)."""
    status = response.status
    if status == OK_STATUS:
        return
    headers = response.headers
    rate_limited = status == RATE_LIMIT_STATUS or (
        status == FORBIDDEN_STATUS and (headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After") is not None))
    if rate_limited:
        raise UpdateError(MESSAGE_RATE_LIMIT)
    if status == NOT_FOUND_STATUS:
        raise UpdateError(MESSAGE_NOT_FOUND)
    if status >= FIRST_SERVER_ERROR_STATUS:
        raise UpdateError(MESSAGE_SERVER_ERROR.format(status=status))
    if status == FORBIDDEN_STATUS:
        raise UpdateError(MESSAGE_REFUSED.format(status=status))
    raise UpdateError(MESSAGE_UNEXPECTED_STATUS.format(status=status))


def _read_limited(response, max_bytes: int, sink, deadline=None) -> int:
    """Citește corpul pe bucăți și le dă lui `sink`; ridică UpdateError peste `max_bytes` (anunțat sau primit), la rețea căzută
    sau, după fiecare bloc, dacă a trecut termenul total `deadline` (vezi _check_deadline)."""
    declared = (response.headers.get("Content-Length") or "").strip()
    if _DECIMAL.fullmatch(declared) and int(declared) > max_bytes:
        raise UpdateError(MESSAGE_TOO_BIG.format(limit=max_bytes))
    total = 0
    while True:
        try:
            chunk = response.read(min(READ_CHUNK_BYTES, max_bytes + 1 - total))
        except (OSError, http.client.HTTPException) as error:
            raise _connection_error(error, during_transfer=True) from error
        if not chunk:
            return total
        total += len(chunk)
        if total > max_bytes:
            raise UpdateError(MESSAGE_TOO_BIG.format(limit=max_bytes))
        sink(chunk)
        _check_deadline(deadline)


def get_json(url: str, *, max_bytes: int, timeout: float) -> object:
    """GET pe `url` (API-ul GitHub) și JSON-ul din corp; ridică UpdateError la orice problemă (rețea, cod, mărime, JSON invalid)."""
    chunks: list[bytes] = []
    with closing(_follow(url, JSON_ACCEPT, timeout)) as response:
        _require_ok(response)
        _read_limited(response, max_bytes, chunks.append)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise UpdateError(MESSAGE_BAD_JSON) from error


def _remove_quietly(path: Path) -> None:
    """Șterge `path` dacă există; o eroare la ștergere nu ascunde eroarea care a dus aici."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def download_to(url: str, target: Path, *, max_bytes: int, timeout: float, total_seconds: float = DOWNLOAD_TOTAL_SECONDS,
                clock=time.monotonic) -> int:
    """Descarcă `url` în `target` și întoarce numărul de octeți; ridică UpdateError.

    Scrie întâi în `<target>.part` și abia la final îl mută peste `target` (os.replace): un transfer întrerupt nu lasă
    niciodată un fișier pe jumătate cu numele final. La ORICE eroare (inclusiv întrerupere de la tastatură) .part se șterge.
    Termenul total (`total_seconds`, măsurat cu `clock` din momentul apelului) se verifică înaintea fiecărei cereri și după
    fiecare bloc: îl poate depăși doar blocul în curs, cât îl lasă `timeout`. Folderul lui `target` îl creează apelantul.
    """
    target = Path(target)
    part = target.with_name(target.name + PART_SUFFIX)
    deadline = (clock, clock() + total_seconds)
    try:
        try:
            with open(part, "wb") as handle:
                with closing(_follow(url, DOWNLOAD_ACCEPT, timeout, deadline)) as response:
                    _require_ok(response)
                    written = _read_limited(response, max_bytes, handle.write, deadline)
            os.replace(part, target)
        except OSError as error:
            # Erorile de rețea sunt deja UpdateError (_open_once, _read_limited): un OSError ajuns aici vine de la disc.
            raise UpdateError(MESSAGE_DISK.format(detail=error.strerror or type(error).__name__)) from error
    except BaseException:
        _remove_quietly(part)
        raise
    return written
