"""Teste pentru verificările de securitate ale serverului local (emag_spend/app_security.py): funcții pure, fără rețea și fără disc.

Fiecare test spune în mesaj CE regulă s-a stricat, UNDE și DE CE contează. Valorile sunt inventate; porturile sunt arbitrare.
Modelul de amenințare: o pagină web străină sau alt program de pe calculator încearcă să vorbească cu serverul aplicației.
"""

import ast
import hmac
import inspect
import re
import textwrap

import pytest

from emag_spend import app_security, run_ids

PORT = 51234


# ---------- token ----------

def test_tokens_are_long_random_and_urlsafe():
    """Tokenul de sesiune are cel puțin 43 de caractere (256 de biți), e diferit la fiecare apel și poate sta într-un fragment de URL."""
    tokens = {app_security.new_token() for _ in range(50)}
    assert len(tokens) == 50, "două tokenuri la rând au ieșit la fel: generatorul nu e aleator, deci tokenul ar putea fi ghicit"
    assert all(len(token) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", token) for token in tokens), (
        "un token e prea scurt sau are caractere care ar trebui codate într-un URL: ar slăbi apărarea sau ar strica fragmentul #t=")


def test_token_comparison_accepts_only_the_exact_token():
    """Doar tokenul exact trece; lipsa, golul, prefixele, sufixele, alte litere mari/mici și tokenurile unui alt server sunt respinse (401 în server)."""
    token = app_security.new_token()
    assert app_security.token_matches(token, token)
    for wrong in (None, "", token[:-1], token + "x", token.upper() if token.upper() != token else token.lower(), " " + token, token + " ",
                  app_security.new_token(), "x" * len(token)):
        assert not app_security.token_matches(token, wrong), f"tokenul greșit {wrong!r} a fost acceptat: oricine ar putea comanda aplicația"


def test_an_empty_expected_token_never_authorizes_anything():
    """Dacă tokenul așteptat ar fi gol din greșeală, nici cererea fără token nu are voie să treacă."""
    assert not app_security.token_matches("", "") and not app_security.token_matches("", None)


def test_token_comparison_uses_constant_time_compare_digest(monkeypatch):
    """Comparația trece prin hmac.compare_digest (timp constant): cu `==` un atacator ar putea afla tokenul caracter cu caracter după timpul răspunsului."""
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(app_security.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
    assert app_security.token_matches("abc", "abc")
    assert calls == [(b"abc", b"abc")], "token_matches nu apelează hmac.compare_digest"
    tree = ast.parse(textwrap.dedent(inspect.getsource(app_security.token_matches)))
    equality = [node for node in ast.walk(tree) if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)]
    assert not equality, "token_matches compară cu == în loc de compare_digest: comparația ar depinde de câte caractere coincid"


# ---------- Host și Origin ----------

@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}"])
def test_host_header_accepts_only_the_two_local_names_with_the_servers_port(host):
    """Host acceptat: exact 127.0.0.1:<port> sau localhost:<port>."""
    assert app_security.is_allowed_host(host, PORT)


@pytest.mark.parametrize("host", [
    None, "", "127.0.0.1", "localhost", f"127.0.0.1:{PORT + 1}", f"127.0.0.1:{PORT} ", f" 127.0.0.1:{PORT}", f"LOCALHOST:{PORT}",
    f"evil.example:{PORT}", f"localhost.evil.example:{PORT}", f"127.0.0.1.evil.example:{PORT}", f"evil.example#127.0.0.1:{PORT}",
    f"127.1:{PORT}", f"2130706433:{PORT}", f"0.0.0.0:{PORT}", f"[::1]:{PORT}", f"127.0.0.1:{PORT}:{PORT}", f"user@127.0.0.1:{PORT}",
])
def test_host_header_rejects_everything_else_against_dns_rebinding(host):
    """Anti DNS-rebinding: un nume străin care rezolvă la 127.0.0.1, un Host fără port, alt port sau o formă „deghizată” se refuză (403)."""
    assert not app_security.is_allowed_host(host, PORT), f"Host {host!r} a fost acceptat: o pagină de pe un alt domeniu ar putea citi API-ul prin DNS rebinding"


def test_origin_is_accepted_when_absent_or_exactly_the_servers_own():
    """Origin lipsă (cerere de aceeași origine fără antet) sau exact http://127.0.0.1:<port> / http://localhost:<port> trece."""
    assert app_security.is_allowed_origin(None, PORT)
    assert app_security.is_allowed_origin(f"http://127.0.0.1:{PORT}", PORT)
    assert app_security.is_allowed_origin(f"http://localhost:{PORT}", PORT)


@pytest.mark.parametrize("origin", [
    "null", "", "https://evil.example", f"https://127.0.0.1:{PORT}", f"http://127.0.0.1:{PORT + 1}", f"http://127.0.0.1:{PORT}/",
    f"http://127.0.0.1:{PORT}.evil.example", f"http://evil.example:{PORT}", "http://127.0.0.1", f"HTTP://127.0.0.1:{PORT}",
    f"http://127.0.0.1:{PORT}, https://evil.example", f"http://[::1]:{PORT}", "file://", "https://www.emag.ro",
])
def test_origin_rejects_foreign_pages_including_null(origin):
    """Origin străină, «null» (pagină locală sau sandbox), alt port sau altă schemă se refuză: o pagină străină nu poate trimite cereri aplicației."""
    assert not app_security.is_allowed_origin(origin, PORT), f"Origin {origin!r} a fost acceptată: o pagină de pe alt site ar putea trimite POST spre aplicație"


def test_allowed_origins_are_built_from_the_same_hosts():
    """Originile permise sunt exact cele două gazde permise, cu schema http: nu pot diverge între ele."""
    assert app_security.allowed_origins(PORT) == {f"http://{host}" for host in app_security.allowed_hosts(PORT)}


# ---------- Content-Type și corp ----------

@pytest.mark.parametrize("value", ["application/json", "Application/JSON", "application/json; charset=utf-8", "application/json;charset=UTF-8",
                                   'application/json; charset="utf-8"', "application/json;", "  application/json  "])
def test_json_content_types_are_accepted(value):
    """application/json, cu sau fără charset=utf-8, în orice scriere de litere, e acceptat."""
    assert app_security.is_json_content_type(value)


@pytest.mark.parametrize("value", [None, "", "text/plain", "text/plain; charset=utf-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                                   "application/jsonx", "application/json-patch+json", "text/json", "application/json; charset=latin-1",
                                   "application/json; boundary=x", "application/json, text/plain", "application/xml", 5])
def test_other_content_types_are_rejected_so_forms_and_text_cannot_be_smuggled(value):
    """Formularele HTML și text/plain (singurele tipuri pe care o pagină străină le poate trimite fără verificare CORS) se refuză (415)."""
    assert not app_security.is_json_content_type(value), f"Content-Type {value!r} a fost acceptat: o pagină străină ar putea trimite POST ca formular"


@pytest.mark.parametrize("value, expected", [
    (None, 0), ("0", 0), ("17", 17), ("4096", 4096), ("4097", 4097), ("000012", 12),
    ("-1", None), ("+5", None), ("1e3", None), ("1.5", None), ("", None), (" 5", None), ("5 ", None), ("0x10", None),
    ("٣", None), ("１２", None), ("9" * 13, None), ("12abc", None),
])
def test_content_length_parsing_is_strict(value, expected):
    """Content-Length: doar cifre ASCII; semne, spații, zecimale, cifre arabe/fullwidth și numere uriașe sunt invalide (400), absența înseamnă 0."""
    assert app_security.parse_content_length(value) == expected, f"Content-Length {value!r} interpretat greșit: limita de corp s-ar putea ocoli"


def test_body_limit_is_a_few_kilobytes_and_is_inclusive():
    """Limita corpului e de câțiva KB: exact limita trece, un octet în plus nu (413)."""
    limit = app_security.MAX_REQUEST_BODY_BYTES
    assert 1024 <= limit <= 16 * 1024, "limita corpului nu mai e de «câțiva KB» cerută în brief"
    assert not app_security.exceeds_body_limit(limit) and app_security.exceeds_body_limit(limit + 1)


# ---------- căi, id de rulare, nume de fișier ----------

@pytest.mark.parametrize("path", ["/", "/aplicatie.html", "/assets/app.js", "/assets/dashboard.css", "/api/state", "/api/runs/2026-10-05_12-00-00_demo/files/istoric_preturi.csv"])
def test_plain_paths_pass(path):
    """Căile rutelor reale (litere, cifre, _ . - și /) trec de verificarea de caractere."""
    assert app_security.is_plain_request_path(path)


@pytest.mark.parametrize("path", [
    "", "aplicatie.html", "/../etc/passwd", "/assets/../aplicatie.html", "/..", "//assets/app.js", "/assets//app.js", "/%2e%2e/x", "/%2E%2E%2Fx",
    "/assets%5capp.js", "/assets\\app.js", "/assets/app.js::$DATA", "/assets/app.js:stream", "/APLICA~1.HTM", "/assets/app*.js", "/assets/app.js ",
    "/assets/app.js\x00.png", "/assets/ăpp.js", "/api/state;x=1", "/a b", "/\n", "http://evil.example/x", "/assets/app.js%00",
])
def test_paths_with_traversal_encoding_or_windows_tricks_are_rejected_before_any_routing(path):
    """`..`, `//`, `%`, `\\`, `:`, `~`, `*`, spațiu, NUL și litere cu diacritice sunt respinse din start: n-au ce căuta într-o rută reală și deschid drumuri pe Windows."""
    assert not app_security.is_plain_request_path(path), f"calea {path!r} a trecut: ar putea ajunge la un fișier din afara listei albe"


@pytest.mark.parametrize("run_id", ["2026-10-05_12-00-00", "2026-10-05_12-00-00_demo", "2024-02-29_23-59-59"])
def test_valid_run_ids(run_id):
    """Un id valid e exact numele unui folder de rulare: data, ora și, la demo, sufixul _demo."""
    assert app_security.is_valid_run_id(run_id)


@pytest.mark.parametrize("run_id", [
    "", "..", ".", "../x", "..\\x", "2026-10-05_12-00-00/..", "2026-10-05_12-00-00/", "2026-10-05_12-00-00_demo/x", "2026-10-05_12-00-00_DEMO",
    "2026-10-05_12-00-00_demo_demo", "2026-10-05_12-00-00 ", " 2026-10-05_12-00-00", "2026-10-05_12-00-00\n", "2026-13-05_12-00-00", "2026-02-30_12-00-00",
    "2026-10-05_25-00-00", "2026-10-05_12-00-00%2f", "２０２６-10-05_12-00-00", "2026-10-05_12-00-00::$DATA", "2026-10-5_12-00-00", "x" * 200,
    None, 5, ["2026-10-05_12-00-00"], b"2026-10-05_12-00-00",
])
def test_invalid_run_ids_never_reach_a_filesystem_path(run_id):
    """Orice id care nu e EXACT un nume de folder de rulare (traversare, separatori, litere mari, cifre fullwidth, date inexistente, alt tip) se respinge."""
    assert not app_security.is_valid_run_id(run_id), f"id-ul {run_id!r} a fost acceptat: ar putea construi un drum în afara folderului iesiri/"


def test_run_id_validation_matches_the_pipeline_folder_names():
    """Id-urile pe care le produce pipeline-ul (run_ids.new_run_id) trec de validare: cele două nu pot diverge."""
    from datetime import datetime

    for demo in (False, True):
        assert app_security.is_valid_run_id(run_ids.new_run_id(datetime(2026, 10, 5, 12, 0, 0), demo))


def test_only_the_four_whitelisted_files_can_be_downloaded_with_exact_names():
    """Descărcările: exact raport.html, produse.csv, istoric_preturi.csv, rezumat.txt, cu nume exact (litere mici, fără extra)."""
    assert set(app_security.DOWNLOADABLE_FILES) == {"raport.html", "produse.csv", "istoric_preturi.csv", "rezumat.txt"}
    for name in app_security.DOWNLOADABLE_FILES:
        assert app_security.download_content_type(name)


@pytest.mark.parametrize("name", [
    "analiza.json", "comenzi.json", "retururi.json", "run_info.json", "RAPORT.HTML", "Raport.html", "raport.html ", " raport.html", "raport.html.",
    "raport.html:stream", "raport.html::$DATA", "../raport.html", "..\\raport.html", "sub/raport.html", "RAPORT~1.HTM", "raport.htm", "raport", "",
    "produse.csv\x00", None, 5,
])
def test_other_names_are_not_downloadable_even_if_they_look_like_whitelisted_ones(name):
    """Datele brute (comenzi.json...), variante cu majuscule, spații, ADS Windows, nume 8.3 sau cu cale nu se pot descărca."""
    assert app_security.download_content_type(name) is None, f"numele {name!r} a fost acceptat pentru descărcare: ar putea scoate date din afara listei albe"


# ---------- antete, adresa paginii ----------

def test_security_headers_are_exactly_the_ones_in_the_brief_plus_hardening():
    """Antetele din brief (CSP exactă, nosniff, Referrer-Policy, CORP, no-store) sunt prezente; niciunul nu deschide CORS."""
    headers = app_security.security_headers()
    assert headers["Content-Security-Policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert headers["Cache-Control"] == "no-store"
    assert not [name for name in headers if name.lower().startswith("access-control-")], "un antet Access-Control-* ar deschide API-ul către alte pagini"


def test_security_headers_return_a_copy_so_callers_cannot_weaken_the_constant():
    """Cine primește antetele le poate schimba fără să slăbească constanta folosită de restul cererilor."""
    first = app_security.security_headers()
    first["Content-Security-Policy"] = "default-src *"
    assert app_security.security_headers()["Content-Security-Policy"].startswith("default-src 'none'")


def test_the_page_url_carries_the_token_only_in_the_fragment_and_can_be_built_without_it():
    """Adresa paginii: tokenul stă în fragment (#t=...), care nu pleacă spre server; fără token adresa e sigură de afișat."""
    assert app_security.build_app_url(PORT) == f"http://127.0.0.1:{PORT}/aplicatie.html"
    with_token = app_security.build_app_url(PORT, "abc_DEF-123")
    assert with_token == f"http://127.0.0.1:{PORT}/aplicatie.html#t=abc_DEF-123"
    assert "?" not in with_token, "tokenul în query ar pleca spre server și ar ajunge în jurnale"
