"""Testele clientului HTTPS al actualizărilor (emag_spend/update_http.py), fără nicio cerere reală.

Verifică: adresele permise (doar https spre gazdele GitHub din ALLOWED_HOSTS, fără utilizator, port străin sau caractere
ascunse); redirecționările verificate ÎNAINTE de cerere și plafonate; limita de octeți; traducerea erorilor în mesaje
românești (fără internet, GitHub nu răspunde, limita de cereri, certificat); descărcarea prin .part, șters la orice eroare;
deschizătorul real (doar HTTPS, certificat verificat, fără proxy). Rețeaua e un deschizător fals injectat; testul cu
deschizătorul real are socket-urile blocate. Ce NU face: nu verifică ce lansare se alege (test_update_check.py).
"""

import http.client
import inspect
import io
import json
import socket
import ssl
import time
import urllib.error
import urllib.request

import pytest

from emag_spend import update_http
from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION

API_URL = "https://api.github.com/repos/exemplu/proiect/releases/latest"
ASSET_URL = "https://github.com/exemplu/proiect/releases/download/v9.9.9/arhiva.zip"
CDN_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/1/semnat?x=1"
TIMEOUT = 7.5
LIMIT = 1000


class FakeResponse:
    """Răspuns fals cu suprafața folosită de update_http: status, headers (fără litere mari/mici), read(n), close()."""

    def __init__(self, status: int = 200, body: bytes = b"", headers: dict[str, str] | None = None,
                 read_error: BaseException | None = None, error_after: int = 0):
        self.status = status
        self.headers = http.client.HTTPMessage()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self._body = io.BytesIO(body)
        self.read_error, self.error_after = read_error, error_after
        self.read_calls = 0
        self.closed = False

    def read(self, size: int) -> bytes:
        """Următoarele `size` octeți; ridică `read_error` după `error_after` octeți dați."""
        self.read_calls += 1
        if self.read_error is not None and self._body.tell() >= self.error_after:
            raise self.read_error
        return self._body.read(size)

    def close(self) -> None:
        """Notează închiderea."""
        self.closed = True


class FakeOpener:
    """Deschizător fals: întoarce răspunsul (sau ridică excepția) înregistrat pentru fiecare adresă și notează cererile."""

    def __init__(self):
        self.routes: dict[str, object] = {}
        self.requests: list[tuple[str, str, dict[str, str], float]] = []

    def open(self, request: urllib.request.Request, timeout: float):
        """Notează (adresă, metodă, antete, timeout) și întoarce ce a pregătit testul; o adresă nepregătită pică testul."""
        self.requests.append((request.full_url, request.get_method(), dict(request.header_items()), timeout))
        if request.full_url not in self.routes:
            pytest.fail(f"cerere neașteptată spre «{request.full_url}»: clientul a cerut o adresă pe care testul nu a pregătit-o")
        outcome = self.routes[request.full_url]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @property
    def urls(self) -> list[str]:
        """Adresele cerute, în ordine."""
        return [url for url, *_ in self.requests]


@pytest.fixture
def opener(monkeypatch) -> FakeOpener:
    """Înlocuiește deschizătorul real cu unul fals: nicio cerere nu iese din test."""
    fake = FakeOpener()
    monkeypatch.setattr(update_http, "_build_opener", lambda: fake)
    return fake


def redirect(location: str, status: int = 302) -> FakeResponse:
    """Un răspuns de redirecționare spre `location`."""
    return FakeResponse(status, headers={"Location": location})


def json_reply(data: object, **headers: str) -> FakeResponse:
    """Un răspuns 200 cu `data` ca JSON."""
    return FakeResponse(200, json.dumps(data).encode("utf-8"), headers)


def with_userinfo(userinfo: str, rest: str) -> str:
    """O adresă https cu „<userinfo>@” în față, asamblată la rulare: scrisă întreagă, garda de date personale ar lua-o drept e-mail."""
    return "https://" + userinfo + chr(64) + rest


# ---------- adresele permise ----------

@pytest.mark.parametrize("url", [
    API_URL, ASSET_URL, CDN_URL, "https://objects.githubusercontent.com/x/y?sig=abc", "https://github.com:443/exemplu/proiect/releases/",
    "HTTPS://GITHUB.COM/exemplu", "https://api.github.com",
])
def test_allowed_urls(url):
    """https spre cele patru gazde GitHub (cu portul implicit sau 443 scris) trece."""
    assert update_http.is_allowed_url(url) is True


@pytest.mark.parametrize("url", [
    "http://github.com/x", "ftp://github.com/x", "file:///etc/passwd", "data:text/plain,x", "//github.com/x", "/relativ", "",
    "https://exemplu.invalid/x", "https://github.com.exemplu.invalid/x", "https://exemplu.invalid/?u=github.com", "https://gist.github.com/x",
    "https://raw.githubusercontent.com/x", "https://githubusercontent.com/x", with_userinfo("utilizator", "github.com/x"),
    with_userinfo("utilizator:parola", "github.com/x"), with_userinfo("exemplu.invalid", "github.com/x"),
    "https://github.com@exemplu.invalid/x", "https://github.com:8443/x", "https://github.com:0/x",
    "https://github.com:abc/x", "https://github.com:99999/x", "https://github.com./x", "https://github.com/\tx", "https://git\nhub.com/x",
    "https://github.com/x y", "https://github.com\\@exemplu.invalid/x", "https://g\u0456thub.com/x", "https://github.com/é",
    "https://github.com/x\x00", "https://[::1]/x", "https://127.0.0.1/x", "https://github.com/" + "a" * update_http.MAX_URL_CHARS,
    None, 42, b"https://github.com/x",
])
def test_refused_urls(url):
    """Orice altă schemă, gazdă (inclusiv păcălitoare sau cu punct final), utilizator, port, caracter ascuns sau tip e refuzat."""
    assert update_http.is_allowed_url(url) is False


def test_allowed_hosts_are_exactly_the_four_github_hosts():
    """D5: exact api.github.com, github.com și cele două gazde de active; o gazdă în plus sau în minus e o decizie nouă."""
    assert update_http.ALLOWED_HOSTS == frozenset({"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})


def test_a_refused_url_never_reaches_the_network(opener):
    """O adresă nepermisă e oprită înainte de orice cerere."""
    with pytest.raises(UpdateError, match="nu e una permisă"):
        update_http.get_json("http://api.github.com/x", max_bytes=LIMIT, timeout=TIMEOUT)
    assert opener.requests == []


# ---------- cererea: antete, metodă, timeout ----------

def test_get_json_sends_only_the_documented_headers(opener):
    """GET cu User-Agent „cheltuieli-emag/<VERSION>” și Accept-ul API-ului GitHub; fără cookie-uri, fără autentificare (D2)."""
    opener.routes[API_URL] = json_reply({"tag_name": "v1.2.3"})
    assert update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT) == {"tag_name": "v1.2.3"}
    (url, method, headers, timeout), = opener.requests
    assert (url, method, timeout) == (API_URL, "GET", TIMEOUT)
    assert headers == {"User-agent": f"cheltuieli-emag/{VERSION}", "Accept": "application/vnd.github+json"}


def test_download_asks_for_the_binary_asset(opener, tmp_path):
    """Descărcarea cere Accept: application/octet-stream, cu același User-Agent."""
    opener.routes[ASSET_URL] = FakeResponse(200, b"continut")
    update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT)
    headers = opener.requests[0][2]
    assert headers == {"User-agent": f"cheltuieli-emag/{VERSION}", "Accept": "application/octet-stream"}


# ---------- redirecționări ----------

def test_redirects_to_allowed_hosts_are_followed_and_closed(opener, tmp_path):
    """github.com → gazda activelor (absolut) → cale relativă: fiecare pas e cerut cu același timeout, iar răspunsurile intermediare se închid."""
    hop1, hop2 = redirect(CDN_URL, 302), redirect("/github-production-release-asset/2/final", 307)
    final = FakeResponse(200, b"arhiva")
    opener.routes.update({ASSET_URL: hop1, CDN_URL: hop2, "https://release-assets.githubusercontent.com/github-production-release-asset/2/final": final})
    assert update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT) == len(b"arhiva")
    assert len(opener.urls) == 3 and all(t == TIMEOUT for *_, t in opener.requests)
    assert hop1.closed and hop2.closed and final.closed


@pytest.mark.parametrize("location", [
    "http://objects.githubusercontent.com/x", "https://exemplu.invalid/x", "https://github.com.exemplu.invalid/x",
    with_userinfo("utilizator:parola", "github.com/x"), "https://github.com:8443/x", "//exemplu.invalid/x", "ftp://github.com/x", "file:///etc/passwd",
    "https://objects.githubusercontent.com/\tx", "https://objects.git\nhubusercontent.com/x", "https://exemplu.invalid\\@github.com/x",
    "/x y", "https://objects.githubusercontent.com/é",
])
def test_a_redirect_to_a_forbidden_place_is_refused_before_it_is_followed(opener, tmp_path, location):
    """Mutație-cheie: o redirecționare spre http, altă gazdă, utilizator sau alt port oprește totul, fără cererea spre ea."""
    opener.routes[ASSET_URL] = redirect(location)
    with pytest.raises(UpdateError, match="redirecționare spre o adresă nepermisă"):
        update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT)
    assert opener.urls == [ASSET_URL], f"clientul a urmat redirecționarea: {opener.urls}"
    assert list(tmp_path.iterdir()) == [], "a rămas un fișier pe disc după refuz"


def _redirect_chain(opener: FakeOpener, hops: int) -> str:
    """Pregătește `hops` redirecționări la rând (între gazde permise), apoi un 200; întoarce prima adresă."""
    urls = [f"https://github.com/exemplu/pas{i}" for i in range(hops + 1)]
    for current, following in zip(urls, urls[1:]):
        opener.routes[current] = redirect(following, 301)
    opener.routes[urls[-1]] = json_reply({"ok": True})
    return urls[0]


def test_exactly_max_redirects_are_followed(opener):
    """MAX_REDIRECTS (5) redirecționări la rând sunt acceptate."""
    start = _redirect_chain(opener, update_http.MAX_REDIRECTS)
    assert update_http.get_json(start, max_bytes=LIMIT, timeout=TIMEOUT) == {"ok": True}
    assert len(opener.requests) == update_http.MAX_REDIRECTS + 1


def test_one_redirect_too_many_is_refused(opener):
    """A șasea redirecționare oprește cererea (fără bucle infinite)."""
    start = _redirect_chain(opener, update_http.MAX_REDIRECTS + 1)
    with pytest.raises(UpdateError, match="Prea multe redirecționări"):
        update_http.get_json(start, max_bytes=LIMIT, timeout=TIMEOUT)
    assert len(opener.requests) == update_http.MAX_REDIRECTS + 1


def test_a_redirect_without_location_is_an_error(opener):
    """Un 302 fără Location e o eroare clară, nu o buclă."""
    opener.routes[API_URL] = FakeResponse(302)
    with pytest.raises(UpdateError, match="fără adresă"):
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)


# ---------- coduri de răspuns ----------

@pytest.mark.parametrize("status, headers, expected", [
    (403, {"X-RateLimit-Remaining": "0"}, "Limita de cereri GitHub a fost atinsă; încearcă peste o oră."),
    (403, {"Retry-After": "60"}, "Limita de cereri GitHub a fost atinsă; încearcă peste o oră."),
    (429, {}, "Limita de cereri GitHub a fost atinsă; încearcă peste o oră."),
    (403, {"X-RateLimit-Remaining": "12"}, "GitHub a refuzat cererea (răspuns 403)."),
    (404, {}, "Lansarea nu există pe GitHub (răspuns 404)."),
    (500, {}, "GitHub nu răspunde acum (eroare 500); încearcă mai târziu."),
    (503, {}, "GitHub nu răspunde acum (eroare 503); încearcă mai târziu."),
    (304, {}, "GitHub a răspuns neașteptat (cod 304)."), (204, {}, "GitHub a răspuns neașteptat (cod 204)."),
    (418, {}, "GitHub a răspuns neașteptat (cod 418)."),
])
def test_error_statuses_become_romanian_messages(opener, status, headers, expected):
    """Limita de cereri (403/429), 404, 5xx și orice alt cod devin mesaje românești exacte."""
    opener.routes[API_URL] = FakeResponse(status, b"{}", headers)
    with pytest.raises(UpdateError) as caught:
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)
    assert str(caught.value) == expected


# ---------- erori de rețea ----------

@pytest.mark.parametrize("error, expected", [
    (urllib.error.URLError(OSError("rețea indisponibilă")), update_http.MESSAGE_NO_INTERNET),
    (urllib.error.URLError(ConnectionRefusedError()), update_http.MESSAGE_NO_INTERNET),
    (urllib.error.URLError(TimeoutError()), update_http.MESSAGE_TIMEOUT),
    (urllib.error.URLError(socket.timeout()), update_http.MESSAGE_TIMEOUT),
    (urllib.error.URLError(ssl.SSLCertVerificationError("certificat inventat")), update_http.MESSAGE_BAD_CERTIFICATE),
    (urllib.error.URLError(ssl.SSLError("tls inventat")), update_http.MESSAGE_TLS_FAILED),
    (urllib.error.URLError("unknown url type"), update_http.MESSAGE_NO_INTERNET),
    (TimeoutError(), update_http.MESSAGE_TIMEOUT), (OSError("x"), update_http.MESSAGE_NO_INTERNET),
    (http.client.RemoteDisconnected("închis"), update_http.MESSAGE_INTERRUPTED),
    (http.client.BadStatusLine("x"), update_http.MESSAGE_INTERRUPTED),
])
def test_connection_errors_become_romanian_messages(opener, error, expected):
    """Fără internet, timp expirat, certificat invalid, TLS eșuat, conexiune închisă: fiecare are mesajul lui, cauza rămâne în lanț."""
    opener.routes[API_URL] = error
    with pytest.raises(UpdateError) as caught:
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)
    assert str(caught.value) == expected
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("error, expected", [
    (TimeoutError(), update_http.MESSAGE_TIMEOUT), (ConnectionResetError(), update_http.MESSAGE_INTERRUPTED),
    (http.client.IncompleteRead(b"x", 10), update_http.MESSAGE_INTERRUPTED), (ssl.SSLError("tls"), update_http.MESSAGE_TLS_FAILED),
])
def test_errors_during_the_transfer_become_romanian_messages(opener, error, expected):
    """O eroare în timpul citirii corpului (după câțiva octeți) are mesajul de transfer întrerupt sau de timp expirat."""
    opener.routes[API_URL] = FakeResponse(200, b'{"a": 1}', read_error=error, error_after=3)
    with pytest.raises(UpdateError) as caught:
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)
    assert str(caught.value) == expected


# ---------- limita de octeți și JSON-ul ----------

def test_a_declared_size_over_the_limit_is_refused_before_reading(opener):
    """Content-Length peste limită: oprit înainte să se citească vreun octet."""
    reply = FakeResponse(200, b"{}", {"Content-Length": str(LIMIT + 1)})
    opener.routes[API_URL] = reply
    with pytest.raises(UpdateError, match=f"depășește limita de {LIMIT} octeți"):
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)
    assert reply.read_calls == 0 and reply.closed


def test_a_body_over_the_limit_without_declared_size_is_refused(opener):
    """Fără Content-Length (sau cu unul mincinos), citirea se oprește la primul octet peste limită."""
    body = b"[" + b"1," * LIMIT + b"1]"
    for headers in ({}, {"Content-Length": "2"}, {"Content-Length": "\u00b2"}):
        opener.routes[API_URL] = FakeResponse(200, body, headers)
        with pytest.raises(UpdateError, match="depășește limita"):
            update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)


def test_a_body_of_exactly_the_limit_is_accepted(opener):
    """Exact `max_bytes` octeți trec (limita e inclusivă)."""
    body = json.dumps("x" * (LIMIT - 2)).encode("utf-8")
    assert len(body) == LIMIT
    opener.routes[API_URL] = FakeResponse(200, body)
    assert update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT) == "x" * (LIMIT - 2)


@pytest.mark.parametrize("body", [b"nu e json", b"\xff\xfe{}", b"", b"[" * 100_000 + b"]" * 100_000],
                         ids=["text", "nu-utf8", "gol", "imbricare-uriasa"])
def test_invalid_json_is_an_update_error(opener, body):
    """JSON invalid, octeți care nu sunt UTF-8, corp gol sau imbricare uriașă: UpdateError, nu o excepție oarecare."""
    opener.routes[API_URL] = FakeResponse(200, body)
    with pytest.raises(UpdateError, match="nu-l înțelege"):
        update_http.get_json(API_URL, max_bytes=len(body) + 1, timeout=TIMEOUT)


# ---------- descărcarea în fișier ----------

def test_download_writes_through_part_and_returns_the_size(opener, tmp_path):
    """Fișierul final are exact octeții primiți; .part nu mai există după succes."""
    body = bytes(range(256)) * 10
    opener.routes[ASSET_URL] = FakeResponse(200, body)
    target = tmp_path / "a.zip"
    assert update_http.download_to(ASSET_URL, target, max_bytes=len(body), timeout=TIMEOUT) == len(body)
    assert target.read_bytes() == body
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.zip"]


@pytest.mark.parametrize("reply", [
    FakeResponse(200, b"x" * 50, read_error=ConnectionResetError(), error_after=20),
    FakeResponse(200, b"x" * (LIMIT + 5)), FakeResponse(500), redirect("https://exemplu.invalid/x"),
])
def test_a_failed_download_leaves_neither_part_nor_target(opener, tmp_path, reply):
    """Transfer întrerupt, prea mare, cod de eroare sau redirecționare refuzată: nici .part, nici fișierul final."""
    opener.routes[ASSET_URL] = reply
    with pytest.raises(UpdateError):
        update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT)
    assert list(tmp_path.iterdir()) == []


def test_a_failed_download_keeps_an_existing_target_untouched(opener, tmp_path):
    """Un fișier existent cu numele final rămâne neatins dacă noua descărcare pică (se înlocuiește doar la succes)."""
    target = tmp_path / "a.zip"
    target.write_bytes(b"vechi")
    opener.routes[ASSET_URL] = FakeResponse(200, b"x" * 50, read_error=ConnectionResetError(), error_after=20)
    with pytest.raises(UpdateError):
        update_http.download_to(ASSET_URL, target, max_bytes=LIMIT, timeout=TIMEOUT)
    assert target.read_bytes() == b"vechi" and not (tmp_path / "a.zip.part").exists()


def test_an_interruption_from_the_keyboard_still_removes_the_part_file(opener, tmp_path):
    """Și la Ctrl+C (KeyboardInterrupt, care nu e Exception) .part se șterge, iar întreruperea trece mai departe."""
    opener.routes[ASSET_URL] = FakeResponse(200, b"x" * 50, read_error=KeyboardInterrupt(), error_after=20)
    with pytest.raises(KeyboardInterrupt):
        update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT)
    assert list(tmp_path.iterdir()) == []


def test_a_disk_error_is_reported_as_such(opener, tmp_path):
    """Folder inexistent: mesaj despre disc, nu „fără internet”, și nicio cerere de rețea făcută degeaba."""
    opener.routes[ASSET_URL] = FakeResponse(200, b"x")
    with pytest.raises(UpdateError, match="Nu pot scrie fișierul descărcat pe disc"):
        update_http.download_to(ASSET_URL, tmp_path / "lipsa" / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT)
    assert opener.requests == []


# ---------- termenul total al descărcării (decis 6 oct. 2026, N11) ----------

class FakeClock:
    """Ceas monoton fals: fiecare citire întoarce ora curentă și o mută cu `step` secunde (nicio așteptare reală)."""

    def __init__(self, step: float):
        self.now = 0.0
        self.step = step
        self.reads = 0

    def __call__(self) -> float:
        """Ora „acum”; apelul următor vede ora mutată cu `step`."""
        self.reads += 1
        value = self.now
        self.now += self.step
        return value


def test_a_download_that_keeps_trickling_past_the_total_deadline_is_stopped(opener, tmp_path):
    """Datele vin, dar încet: după DOWNLOAD_TOTAL_SECONDS descărcarea se oprește cu mesajul ei, fără .part și fără fișier final.

    Fără termenul total, timeout-ul pe operație (care pornește din nou la fiecare bloc primit) n-ar opri-o niciodată.
    """
    chunks = 10
    body = b"x" * (update_http.READ_CHUNK_BYTES * chunks)
    reply = FakeResponse(200, body)
    opener.routes[ASSET_URL] = reply
    clock = FakeClock(step=update_http.DOWNLOAD_TOTAL_SECONDS / 4)
    with pytest.raises(UpdateError) as caught:
        update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=len(body), timeout=TIMEOUT, clock=clock)
    assert str(caught.value) == update_http.MESSAGE_TOTAL_TIMEOUT
    # Ceasul: 0 la pornire (termen = DOWNLOAD_TOTAL_SECONDS), 1/4 la cerere, apoi 2/4, 3/4, 4/4 (încă nu e „peste”) și 5/4 după
    # al patrulea bloc: oprirea vine exact la primul bloc citit după termen, nu mai târziu.
    assert reply.read_calls == 4 < chunks, f"oprit după {reply.read_calls} blocuri, nu la primul bloc de după termen"
    assert list(tmp_path.iterdir()) == []


def test_the_total_deadline_also_counts_the_time_spent_on_redirects(opener, tmp_path):
    """Termenul pornește la prima cerere: o redirecționare care ajunge după termen nu mai e urmată."""
    opener.routes[ASSET_URL] = redirect(CDN_URL)
    opener.routes[CDN_URL] = FakeResponse(200, b"arhiva")
    clock = FakeClock(step=update_http.DOWNLOAD_TOTAL_SECONDS)
    with pytest.raises(UpdateError) as caught:
        update_http.download_to(ASSET_URL, tmp_path / "a.zip", max_bytes=LIMIT, timeout=TIMEOUT, clock=clock)
    assert str(caught.value) == update_http.MESSAGE_TOTAL_TIMEOUT
    assert opener.urls == [ASSET_URL] and list(tmp_path.iterdir()) == []


def test_a_download_inside_the_total_deadline_is_untouched(opener, tmp_path):
    """Un transfer care se încheie înainte de termen (aici: ceasul stă pe loc) se termină normal, cu toți octeții."""
    body = b"y" * (update_http.READ_CHUNK_BYTES * 3 + 7)
    opener.routes[ASSET_URL] = FakeResponse(200, body)
    target = tmp_path / "a.zip"
    assert update_http.download_to(ASSET_URL, target, max_bytes=len(body), timeout=TIMEOUT, clock=FakeClock(step=0.0)) == len(body)
    assert target.read_bytes() == body


def test_the_total_deadline_is_the_named_constant_and_longer_than_one_operation():
    """download_to folosește implicit DOWNLOAD_TOTAL_SECONDS și ceasul monoton; termenul total e mult peste timeout-ul pe o operație."""
    from emag_spend import update_download

    parameters = inspect.signature(update_http.download_to).parameters
    assert parameters["total_seconds"].default == update_http.DOWNLOAD_TOTAL_SECONDS
    assert parameters["clock"].default is time.monotonic
    assert update_http.DOWNLOAD_TOTAL_SECONDS > 10 * update_download.DOWNLOAD_TIMEOUT_SECONDS


# ---------- deschizătorul real ----------

def test_the_real_opener_speaks_only_verified_https_without_proxy_or_redirects():
    """Deschizătorul real: doar HTTPSHandler (certificat obligatoriu, numele verificat) și UnknownHandler; fără proxy,
    fără cookie-uri, fără http/ftp/file/data, fără redirecționări automate și fără antetul implicit Python-urllib."""
    opener = update_http._build_opener()
    kinds = sorted(type(handler).__name__ for handler in opener.handlers)
    assert kinds == ["HTTPSHandler", "UnknownHandler"]
    https = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
    assert https._context.verify_mode == ssl.CERT_REQUIRED and https._context.check_hostname is True
    assert opener.addheaders == []


def test_the_real_client_tries_only_api_github_com_443_and_reports_no_internet(monkeypatch):
    """Cu deschizătorul REAL și socket-urile blocate: o singură încercare, spre ('api.github.com', 443), iar eroarea e „fără internet”."""
    attempts: list[tuple] = []

    def refuse(address, *args, **kwargs):
        """Notează adresa cerută și refuză conexiunea (nicio cerere nu iese din test)."""
        attempts.append(address)
        raise OSError("rețea blocată de test")

    def refuse_lookup(*args, **kwargs):
        """Orice interogare de nume e și ea refuzată și notată."""
        attempts.append(("getaddrinfo", args[:2]))
        raise OSError("rețea blocată de test")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse_lookup)
    with pytest.raises(UpdateError) as caught:
        update_http.get_json(API_URL, max_bytes=LIMIT, timeout=TIMEOUT)
    assert str(caught.value) == update_http.MESSAGE_NO_INTERNET
    assert attempts == [("api.github.com", 443)]
