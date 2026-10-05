"""Teste pentru rutele API și poarta de securitate a serverului local, pe un server REAL (127.0.0.1, port 0) cu un runner fals.

Verifică, pe cereri HTTP adevărate: token lipsă sau greșit -> 401; Host greșit -> 403; Origin străină -> 403; Content-Type greșit ->
415; corp prea mare -> 413; metode neașteptate -> 405; niciun antet CORS; antetele de securitate pe TOATE răspunsurile, inclusiv erori.
Apoi rutele din contract (hello, state, runs, cancel, analysis, files, session/delete, shutdown). Runner-ul fals notează apelurile, ca
fiecare test de siguranță să poată dovedi că acțiunea NU a fost executată. Fiecare test spune în mesaj ce s-a încălcat și de ce contează.
"""

import json
from pathlib import Path

import pytest

from emag_spend import app_security, session_cleaner
from emag_spend.app_runner import RunRequest
from emag_spend.app_server import STOP_SHUTDOWN
from tests.app_support import FAKE_RUN_ID, FakeRunner, parse_reply, running_app, wait_for, write_interface

RUN_ID = "2026-10-05_09-00-00"
ANALYSIS = {"meta": {"orders": 12}, "funnel": {"kept_bani": 345600}}
# Toate rutele API din contract: (metodă, cale). Id-ul și numele din cale sunt valide ca formă.
ALL_ROUTES = [
    ("GET", "/api/hello"), ("GET", "/api/state"), ("GET", "/api/runs"), ("POST", "/api/runs"), ("POST", "/api/runs/current/cancel"),
    ("GET", f"/api/runs/{RUN_ID}/analysis"), ("GET", f"/api/runs/{RUN_ID}/files/raport.html"), ("POST", "/api/session/delete"), ("POST", "/api/shutdown"),
]
BODY_FOR = {"/api/runs": {"mode": "demo"}, "/api/session/delete": {"confirm": "DA"}}


@pytest.fixture
def fake() -> FakeRunner:
    """Runner-ul fals al testului curent."""
    return FakeRunner()


@pytest.fixture
def app(tmp_path, fake):
    """Un server real cu runner fals, o rulare inventată în iesiri/ și o interfață inventată (aplicatie.html cu app.js și app.css)."""
    write_interface(tmp_path / "interfata")
    folder = tmp_path / "iesiri" / RUN_ID
    folder.mkdir(parents=True)
    (folder / "analiza.json").write_text(json.dumps(ANALYSIS), encoding="utf-8")
    (folder / "raport.html").write_text("<html>raport inventat</html>", encoding="utf-8")
    (folder / "comenzi.json").write_text('["date personale brute inventate"]', encoding="utf-8")
    with running_app(tmp_path, runner=fake) as running:
        yield running


def _send(app, method, path, **kwargs):
    """Trimite cererea; pe rutele POST pune corpul minim potrivit dacă testul nu dă unul."""
    if method == "POST" and "body" not in kwargs:
        kwargs["body"] = BODY_FOR.get(path, {})
    return app.call(method, path, **kwargs)


def _assert_alive(app):
    """După o cerere respinsă serverul trebuie să răspundă în continuare (cererea rea nu l-a blocat sau oprit)."""
    reply = app.call("GET", "/api/hello")
    assert reply.status == 200 and not app.stopped, "serverul nu mai răspunde sau s-a oprit după o cerere respinsă"


# ---------- token ----------

@pytest.mark.parametrize("method, path", ALL_ROUTES)
def test_every_api_route_without_a_token_is_refused_and_nothing_is_executed(app, fake, method, path):
    """Fără X-App-Token, ORICE rută API dă 401 și nu execută nimic: altfel orice program sau pagină care află portul ar comanda aplicația."""
    reply = _send(app, method, path, token=False)
    assert reply.status == 401 and reply.error_code == "unauthorized", f"{method} {path} fără token a dat {reply.status}, nu 401"
    assert fake.calls == [], f"{method} {path} fără token a executat o acțiune: {fake.calls}"
    _assert_alive(app)


@pytest.mark.parametrize("method, path", ALL_ROUTES)
def test_every_api_route_with_a_wrong_token_is_refused(app, fake, method, path):
    """Token greșit (de aceeași lungime, mai scurt, mai lung, gol): 401 pe orice rută, fără nicio acțiune."""
    for wrong in (app.token[:-1] + ("A" if app.token[-1] != "A" else "B"), app.token[:-1], app.token + "x", "", "x" * len(app.token)):
        reply = _send(app, method, path, token=wrong or None)
        assert reply.status == 401, f"{method} {path} cu tokenul greșit {wrong[:6]!r}… a dat {reply.status}, nu 401"
    assert fake.calls == []


def test_an_unknown_api_path_also_needs_the_token_so_routes_cannot_be_probed(app):
    """O cale API inexistentă dă 401 fără token (nu 404): cine nu are tokenul nu poate afla ce rute există."""
    assert app.call("GET", "/api/nu-exista", token=False).status == 401
    assert app.call("GET", "/api/nu-exista").status == 404


def test_two_token_headers_are_refused_even_if_one_is_right(app):
    """Două antete X-App-Token (unul bun, unul rău) sunt ambigue: 401, ca un proxy sau un atacator să nu strecoare un token între ele."""
    request = (f"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\n{app_security.TOKEN_HEADER}: {app.token}\r\n"
               f"{app_security.TOKEN_HEADER}: gresit\r\nConnection: close\r\n\r\n")
    assert parse_reply(app.raw(request.encode())).status == 401


# ---------- Host și Origin ----------

@pytest.mark.parametrize("method, path", [("GET", "/api/hello"), ("POST", "/api/runs"), ("GET", "/aplicatie.html"), ("GET", "/")])
def test_a_wrong_host_is_refused_with_403_even_with_a_valid_token(app, fake, method, path):
    """Host străin (DNS rebinding) -> 403 pe API și pe fișiere, chiar cu token valid: tokenul nu înlocuiește verificarea adresei."""
    for host in ("evil.example", f"evil.example:{app.port}", f"localhost.evil.example:{app.port}", "127.0.0.1", f"127.0.0.1:{app.port + 1}", "", f"0.0.0.0:{app.port}"):
        reply = _send(app, method, path, host=host)
        assert reply.status == 403 and reply.error_code == "forbidden_host", f"Host {host!r} a dat {reply.status}: o pagină străină ar putea citi aplicația prin DNS rebinding"
    assert fake.calls == []
    _assert_alive(app)


def test_a_request_without_a_host_header_is_refused(app):
    """HTTP/1.0 fără Host: 403 (nu se poate verifica adresa, deci nu se răspunde la ea)."""
    reply = parse_reply(app.raw(f"GET /api/hello HTTP/1.0\r\n{app_security.TOKEN_HEADER}: {app.token}\r\n\r\n".encode()))
    assert reply.status == 403


def test_two_host_headers_are_refused(app):
    """Două antete Host sunt ambigue (unul bun, unul străin): 403."""
    request = f"GET /api/hello HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nHost: evil.example\r\n{app_security.TOKEN_HEADER}: {app.token}\r\nConnection: close\r\n\r\n"
    assert parse_reply(app.raw(request.encode())).status == 403


def test_both_local_host_names_work(app):
    """127.0.0.1:<port> și localhost:<port> sunt singurele adrese acceptate."""
    assert app.call("GET", "/api/hello", host=f"127.0.0.1:{app.port}").status == 200
    assert app.call("GET", "/api/hello", host=f"localhost:{app.port}").status == 200


@pytest.mark.parametrize("method, path", [("GET", "/api/state"), ("POST", "/api/runs"), ("POST", "/api/shutdown"), ("GET", "/aplicatie.html")])
def test_a_foreign_origin_is_refused_with_403_and_nothing_is_executed(app, fake, method, path):
    """Origin străină sau «null» -> 403: o pagină de pe alt site nu poate trimite cereri aplicației (nici GET, nici POST), chiar cu tokenul în mână."""
    for origin in ("https://evil.example", "http://evil.example", "null", "https://www.emag.ro", f"http://127.0.0.1:{app.port + 1}", f"http://localhost.evil.example:{app.port}", ""):
        reply = _send(app, method, path, origin=origin)
        assert reply.status == 403 and reply.error_code == "forbidden_origin", f"Origin {origin!r} a dat {reply.status}: o pagină străină ar putea comanda aplicația"
    assert fake.calls == [] and not app.stopped
    _assert_alive(app)


def test_the_servers_own_origin_is_accepted(app):
    """Originea exactă a serverului (cum o trimite browserul la POST din pagina aplicației) trece, cu ambele nume de gazdă."""
    assert _send(app, "POST", "/api/runs", origin=f"http://127.0.0.1:{app.port}").status == 202
    assert app.call("GET", "/api/state", origin=f"http://localhost:{app.port}", host=f"localhost:{app.port}").status == 200


def test_the_host_check_runs_before_the_token_check(app):
    """Un Host greșit dă 403 chiar fără token (nu 401): verificarea adresei e prima, deci nu se scurge nimic despre rute sau token."""
    assert app.call("GET", "/api/state", host="evil.example", token=False).status == 403
    assert app.call("GET", "/api/state", origin="https://evil.example", token=False).status == 403


# ---------- Content-Type și corp ----------

@pytest.mark.parametrize("content_type", ["text/plain", "text/plain; charset=utf-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/xml", None])
def test_post_with_a_wrong_content_type_is_refused_with_415(app, fake, content_type):
    """POST fără application/json (formular HTML sau text/plain: ce poate trimite o pagină străină fără CORS) -> 415, fără nicio acțiune."""
    reply = app.call("POST", "/api/runs", body={"mode": "demo"}, content_type=content_type)
    assert reply.status == 415 and reply.error_code == "unsupported_media_type", f"Content-Type {content_type!r} a dat {reply.status}"
    assert fake.calls == []
    _assert_alive(app)


def test_even_bodyless_posts_need_the_json_content_type(app, fake):
    """Și POST-urile fără corp (cancel, shutdown) cer application/json: o cerere fără el nu poate opri aplicația sau o analiză."""
    for path in ("/api/runs/current/cancel", "/api/shutdown"):
        assert app.call("POST", path, content_type="text/plain").status == 415
    assert fake.calls == [] and not app.stopped


def test_a_body_over_the_limit_is_refused_with_413_and_the_server_keeps_working(app, fake):
    """Un corp mai mare decât limita (câțiva KB) -> 413, nimic executat, iar serverul continuă să răspundă (corpul necitit nu blochează nimic)."""
    over = b'{"mode": "demo", "x": "' + b"a" * app_security.MAX_REQUEST_BODY_BYTES + b'"}'
    reply = app.call("POST", "/api/runs", body=over)
    assert reply.status == 413 and reply.error_code == "body_too_large", f"corp de {len(over)} octeți a dat {reply.status}"
    assert fake.calls == []
    _assert_alive(app)


def test_a_body_exactly_at_the_limit_is_read(app, fake):
    """Un corp de exact MAX_REQUEST_BODY_BYTES octeți se citește (limita e inclusă); aici nu e JSON-ul potrivit, deci 400, nu 413."""
    body = b'{"mode": "' + b"a" * (app_security.MAX_REQUEST_BODY_BYTES - len(b'{"mode": "') - 2) + b'"}'
    assert len(body) == app_security.MAX_REQUEST_BODY_BYTES
    assert app.call("POST", "/api/runs", body=body).status == 400  # mod necunoscut, dar corpul a fost citit


def test_a_huge_declared_length_is_refused_without_waiting_for_the_body(app, fake):
    """Content-Length uriaș cu corp aproape inexistent -> 413 imediat, fără așteptare până la timeout și fără acțiune."""
    request = (f"POST /api/runs HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\n{app_security.TOKEN_HEADER}: {app.token}\r\n"
               "Content-Type: application/json\r\nContent-Length: 99999999\r\nConnection: close\r\n\r\n{}")
    reply = parse_reply(app.raw(request.encode()))
    assert reply.status == 413 and fake.calls == []
    _assert_alive(app)


def test_a_megabyte_sized_body_is_refused_and_the_server_survives(app, fake):
    """Un corp de 2 MB (peste ce se golește) -> 413 sau conexiune închisă, niciodată acceptat; serverul rămâne sănătos."""
    try:
        reply = app.call("POST", "/api/runs", body=b"x" * (2 * 1024 * 1024))
        assert reply.status == 413
    except (ConnectionError, OSError):
        pass  # un client care trimite megaocteți ca să fie respins poate primi închiderea conexiunii în loc de răspuns
    assert fake.calls == []
    _assert_alive(app)


@pytest.mark.parametrize("length", ["abc", "-1", "+5", "1e3", "5 5", "", "٣", "99999999999999999999"])
def test_an_invalid_content_length_is_refused_with_400(app, fake, length):
    """Content-Length care nu e un număr întreg fără semn (sau e uriaș) -> 400/413, fără acțiune."""
    request = (f"POST /api/runs HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\n{app_security.TOKEN_HEADER}: {app.token}\r\n"
               f"Content-Type: application/json\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n{{}}")
    assert parse_reply(app.raw(request.encode("utf-8"))).status in (400, 413), f"Content-Length {length!r} a fost acceptat"
    assert fake.calls == []


def test_chunked_bodies_and_duplicate_lengths_are_refused(app, fake):
    """Corp trimis în bucăți (Transfer-Encoding) sau două Content-Length (cerere ambiguă, cunoscută la „request smuggling”) -> 400."""
    base = f"POST /api/runs HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\n{app_security.TOKEN_HEADER}: {app.token}\r\nContent-Type: application/json\r\n"
    chunked = base + "Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
    doubled = base + "Content-Length: 2\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
    assert parse_reply(app.raw(chunked.encode())).status == 400
    assert parse_reply(app.raw(doubled.encode())).status == 400
    assert fake.calls == []


@pytest.mark.parametrize("body", ["nu e json", "{", '{"mode": NaN}', "[1, 2]", "42", '"text"', "null", b"\xff\xfe\xfd", '{"mode": "demo"} {"mode": "real"}'])
def test_a_malformed_or_non_object_body_is_refused_with_400(app, fake, body):
    """Corp care nu e un obiect JSON strict (text, array, NaN, octeți invalizi, două obiecte) -> 400 invalid_json, fără acțiune."""
    reply = app.call("POST", "/api/runs", body=body)
    assert reply.status == 400 and reply.error_code == "invalid_json", f"corpul {body!r} a dat {reply.status}"
    assert fake.calls == []


def test_an_empty_body_is_accepted_where_none_is_needed(app, fake):
    """cancel și shutdown nu au nevoie de corp: un corp gol (cu Content-Type JSON) e acceptat."""
    assert app.call("POST", "/api/runs/current/cancel", body=b"").status == 200


# ---------- metode ----------

@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@pytest.mark.parametrize("path", ["/api/hello", "/api/state", "/api/runs", "/api/shutdown", f"/api/runs/{RUN_ID}/analysis"])
def test_unexpected_methods_get_405_with_allow(app, fake, method, path):
    """PUT/DELETE/PATCH/OPTIONS/HEAD -> 405 cu antetul Allow (după token); preflight-ul CORS (OPTIONS) nu primește niciun antet de permisiune."""
    reply = app.call(method, path)
    assert reply.status == 405, f"{method} {path} a dat {reply.status}, nu 405"
    assert reply.headers.get("allow") and not [name for name in reply.headers if name.startswith("access-control-")]
    assert fake.calls == []


@pytest.mark.parametrize("path", ["/api/shutdown", "/api/runs/current/cancel", "/api/session/delete"])
def test_state_changing_routes_refuse_get(app, fake, path):
    """Rutele care schimbă ceva (shutdown, cancel, ștergerea sesiunii) nu răspund la GET: o simplă legătură sau o imagine nu le poate declanșa."""
    reply = app.call("GET", path)
    assert reply.status == 405 and reply.headers["allow"] == "POST"
    assert fake.calls == [] and not app.stopped


def test_get_only_routes_refuse_post(app, fake):
    """Rutele de citire (hello, state, analysis, files) nu răspund la POST."""
    for path in ("/api/hello", "/api/state", f"/api/runs/{RUN_ID}/analysis", f"/api/runs/{RUN_ID}/files/raport.html"):
        assert _send(app, "POST", path).status == 405


def test_a_nonstandard_method_gets_a_json_501_with_the_security_headers(app):
    """O metodă necunoscută (ex. TRACE, FOO) primește tot JSON în română, cu antetele de securitate, nu pagina HTML implicită a bibliotecii."""
    reply = parse_reply(app.raw(f"TRACE /api/state HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nConnection: close\r\n\r\n".encode()))
    assert reply.status == 501 and json.loads(reply.body)["error"]["code"] == "http_501"
    assert reply.headers["x-content-type-options"] == "nosniff"


# ---------- antete pe toate răspunsurile ----------

def _battery(app) -> dict[str, "object"]:
    """Răspunsuri de toate felurile (succes, 202, erori de client, 405, 413, 415, 422, 501, 500, fișier static) pentru verificările de antete."""
    replies = {
        "200 hello": app.call("GET", "/api/hello"),
        "200 state": app.call("GET", "/api/state"),
        "202 runs": app.call("POST", "/api/runs", body={"mode": "demo"}),
        "400 mod": app.call("POST", "/api/runs", body={"mode": "x"}),
        "401": app.call("GET", "/api/state", token=False),
        "403 host": app.call("GET", "/api/state", host="evil.example"),
        "403 origin": app.call("GET", "/api/state", origin="https://evil.example"),
        "404 api": app.call("GET", "/api/nu-exista"),
        "404 run": app.call("GET", "/api/runs/2030-01-01_00-00-00/analysis"),
        "404 static": app.call("GET", "/nu-exista.html"),
        "405": app.call("DELETE", "/api/state"),
        "413": app.call("POST", "/api/runs", body=b"x" * (app_security.MAX_REQUEST_BODY_BYTES + 1)),
        "415": app.call("POST", "/api/runs", body={"mode": "demo"}, content_type="text/plain"),
        "200 analysis": app.call("GET", f"/api/runs/{RUN_ID}/analysis"),
        "200 download": app.call("GET", f"/api/runs/{RUN_ID}/files/raport.html"),
        "200 static": app.call("GET", "/aplicatie.html"),
        "501 raw": parse_reply(app.raw(f"FOO / HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nConnection: close\r\n\r\n".encode())),
        "400 raw": parse_reply(app.raw(b"GET / VERSIUNE-GRESITA\r\n\r\n")),
    }
    return replies


def test_security_headers_are_on_every_single_response_including_errors(app):
    """Toate răspunsurile (succes și erori de orice fel) poartă EXACT antetele de securitate din brief, nu au Server și nu au Access-Control-*."""
    expected = app_security.security_headers()
    replies = _battery(app)
    assert len(replies) >= 18
    for label, reply in replies.items():
        assert reply.status > 0, f"răspunsul «{label}» nu s-a putut citi"
        for name, value in expected.items():
            assert reply.headers.get(name.lower()) == value, f"răspunsul «{label}» ({reply.status}) nu are antetul {name} = {value!r}: pe erori, o pagină ar rămâne neprotejată"
        assert "server" not in reply.headers, f"răspunsul «{label}» trimite antetul Server (spune ce versiune de Python rulează)"
        assert not [name for name in reply.headers if name.startswith("access-control-")], f"răspunsul «{label}» deschide CORS"


def test_every_error_is_json_in_the_contract_form_with_a_romanian_message(app):
    """Orice eroare e `{"error": {"code": str, "message": str}}` cu mesaj în română (nu HTML, nu text în engleză)."""
    for label, reply in _battery(app).items():
        if reply.status < 400:
            continue
        assert reply.headers["content-type"].startswith("application/json"), f"eroarea «{label}» nu e JSON: {reply.headers['content-type']}"
        error = reply.json()["error"]
        assert set(error) == {"code", "message"} and error["code"] and error["message"], f"eroarea «{label}» nu are forma din contract: {error}"
        assert error["message"][0].isupper() and error["message"].rstrip().endswith((".", "!", "?")), f"mesajul erorii «{label}» nu e o propoziție: {error['message']!r}"


def test_responses_say_no_store_and_nosniff_and_never_cors(app):
    """API-ul are Cache-Control: no-store; niciun răspuns nu trimite Access-Control-Allow-*, nici măcar la cereri cu Origin străină."""
    reply = app.call("GET", "/api/state")
    assert reply.headers["cache-control"] == "no-store" and reply.headers["x-content-type-options"] == "nosniff"
    refused = app.call("GET", "/api/state", origin="https://evil.example")
    assert refused.status == 403 and not [name for name in refused.headers if name.startswith("access-control-")]


# ---------- rutele din contract ----------

def test_hello(app):
    """GET /api/hello -> {"app": "cheltuieli-emag", "version": str, "api": 1}."""
    body = app.call("GET", "/api/hello").json()
    assert body["app"] == "cheltuieli-emag" and body["api"] == 1 and isinstance(body["version"], str) and body["version"]


def test_state_is_what_the_runner_reports(app, fake):
    """GET /api/state întoarce exact instantaneul runner-ului (aceleași chei ca în contract)."""
    fake.state.update(state="fetching_orders", message="Citesc.", run_id=FAKE_RUN_ID)
    body = app.call("GET", "/api/state").json()
    assert body == fake.snapshot() and set(body) == {"state", "message", "progress", "run_id", "started_at", "error", "session_saved"}


def test_post_runs_starts_a_run_and_returns_202_with_the_id(app, fake):
    """POST /api/runs {"mode", "threshold_lei"} -> 202 {"run_id"}; runner-ul primește modul și pragul validate."""
    reply = app.call("POST", "/api/runs", body={"mode": "real", "threshold_lei": 750})
    assert reply.status == 202 and reply.json() == {"run_id": FAKE_RUN_ID}
    assert fake.calls == [("start", RunRequest("real", 750.0))]


@pytest.mark.parametrize("body, code", [({"mode": "x"}, "invalid_mode"), ({}, "invalid_mode"), ({"mode": "demo", "threshold_lei": -3}, "invalid_threshold"),
                                        ({"mode": "demo", "threshold_lei": "mult"}, "invalid_threshold"), ({"mode": "demo", "alt": 1}, "invalid_request")])
def test_post_runs_with_a_bad_request_is_400_with_a_stable_code(app, fake, body, code):
    """Cerere de pornire greșită -> 400 cu cod stabil (invalid_mode / invalid_threshold / invalid_request), fără să pornească nimic."""
    reply = app.call("POST", "/api/runs", body=body)
    assert reply.status == 400 and reply.error_code == code
    assert fake.calls == []


def test_post_runs_while_one_is_running_is_409(app, fake):
    """A doua pornire cât rulează una -> 409 run_in_progress, cu mesaj în română."""
    fake.busy = True
    reply = app.call("POST", "/api/runs", body={"mode": "demo"})
    assert reply.status == 409 and reply.error_code == "run_in_progress" and "rulează deja" in reply.json()["error"]["message"]


def test_cancel_reports_whether_something_was_running(app, fake):
    """POST /api/runs/current/cancel -> 200 {"cancel_requested": bool}: true dacă rula ceva, false altfel (nu e o eroare)."""
    assert app.call("POST", "/api/runs/current/cancel", body={}).json() == {"cancel_requested": False}
    fake.busy = True
    assert app.call("POST", "/api/runs/current/cancel", body={}).json() == {"cancel_requested": True}
    assert fake.calls == [("cancel",), ("cancel",)]


def test_runs_list_reads_the_outputs_folder(app):
    """GET /api/runs -> lista rulărilor din iesiri/ în forma din contract."""
    runs = app.call("GET", "/api/runs").json()
    assert runs == [{"id": RUN_ID, "created_at": "2026-10-05T09:00:00", "kind": "real", "orders": 12, "kept_bani": 345600, "has_report": True}]


def test_analysis_is_returned_as_json(app):
    """GET /api/runs/<id>/analysis -> conținutul analiza.json."""
    reply = app.call("GET", f"/api/runs/{RUN_ID}/analysis")
    assert reply.status == 200 and reply.json() == ANALYSIS and reply.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("run_id", ["2030-01-01_00-00-00", "..", "x", "2026-10-05_09-00-00_DEMO", "%2e%2e", "2026-10-05_09-00-00%2f..", "a" * 64])
def test_analysis_of_an_unknown_or_invalid_id_is_404(app, run_id):
    """Id inexistent sau invalid (traversare, majuscule, codat) -> 404, nu 500 și nu un fișier din altă parte."""
    reply = app.call("GET", f"/api/runs/{run_id}/analysis")
    assert reply.status == 404, f"id-ul {run_id!r} a dat {reply.status}"


def test_a_broken_analysis_is_422_with_a_stable_code(app, tmp_path):
    """Analiză stricată sau peste limită -> 422 cu cod stabil și mesaj în română (nu 500)."""
    (tmp_path / "iesiri" / RUN_ID / "analiza.json").write_text("nu e json", encoding="utf-8")
    reply = app.call("GET", f"/api/runs/{RUN_ID}/analysis")
    assert reply.status == 422 and reply.error_code == "analysis_invalid" and "stricat" in reply.json()["error"]["message"]


@pytest.mark.parametrize("name, content_type", [("raport.html", "text/html; charset=utf-8"), ("produse.csv", "text/csv; charset=utf-8"),
                                                ("istoric_preturi.csv", "text/csv; charset=utf-8"), ("rezumat.txt", "text/plain; charset=utf-8")])
def test_whitelisted_files_download_as_attachments(app, tmp_path, name, content_type):
    """GET /api/runs/<id>/files/<nume> pentru cele 4 nume din lista albă -> 200 cu Content-Disposition: attachment și tipul potrivit."""
    (tmp_path / "iesiri" / RUN_ID / name).write_text(f"conținut inventat pentru {name}", encoding="utf-8")
    reply = app.call("GET", f"/api/runs/{RUN_ID}/files/{name}")
    assert reply.status == 200 and reply.headers["content-disposition"] == f'attachment; filename="{name}"'
    assert reply.headers["content-type"] == content_type and reply.body.decode("utf-8") == f"conținut inventat pentru {name}"


@pytest.mark.parametrize("name", ["comenzi.json", "retururi.json", "analiza.json", "run_info.json", "RAPORT.HTML", "raport.html.", "..%2fanaliza.json", "raport.htm"])
def test_files_outside_the_whitelist_are_404_even_when_they_exist(app, name):
    """comenzi.json (date personale brute) și orice alt nume din afara listei albe -> 404, deși fișierul există pe disc."""
    reply = app.call("GET", f"/api/runs/{RUN_ID}/files/{name}")
    assert reply.status == 404, f"fișierul {name!r} a dat {reply.status}: date din afara listei albe ar putea ieși din aplicație"
    assert b"date personale brute inventate" not in reply.body


def test_session_delete_needs_the_exact_confirmation(app, fake):
    """POST /api/session/delete fără «DA» exact (sau cu alt text) -> 400 confirmation_required, fără ștergere."""
    for body in ({}, {"confirm": "da"}, {"confirm": "DA "}, {"confirm": True}, {"confirm": ["DA"]}, {"confirm": "NU"}):
        reply = app.call("POST", "/api/session/delete", body=body)
        assert reply.status == 400 and reply.error_code == "confirmation_required", f"confirmarea {body} a fost acceptată"
    assert fake.calls == []


def test_session_delete_with_confirmation_succeeds(app, fake):
    """Cu {"confirm": "DA"} sesiunea se șterge: 200 cu starea, mesajul în română și session_saved."""
    reply = app.call("POST", "/api/session/delete", body={"confirm": "DA"})
    assert reply.status == 200 and fake.calls == [("delete_session",)]
    body = reply.json()
    assert body["status"] == "deleted" and "ștearsă" in body["message"] and body["session_saved"] is False


def test_session_delete_is_409_while_a_run_is_in_progress(app, fake):
    """Cât rulează o analiză, ștergerea sesiunii -> 409 run_in_progress."""
    fake.busy = True
    reply = app.call("POST", "/api/session/delete", body={"confirm": "DA"})
    assert reply.status == 409 and reply.error_code == "run_in_progress"


def test_a_failed_session_delete_is_409_with_the_reason(app, fake):
    """Ștergere refuzată (ex. folder care nu e profil de browser) -> 409 session_delete_failed, cu motivul în română."""
    fake.deletion = session_cleaner.SessionDeleteResult(session_cleaner.SessionDeleteStatus.REFUSED, Path("profil-inventat"), reason="Folderul nu seamănă cu un profil de browser")
    reply = app.call("POST", "/api/session/delete", body={"confirm": "DA"})
    assert reply.status == 409 and reply.error_code == "session_delete_failed" and "nu seamănă" in reply.json()["error"]["message"]


def test_shutdown_answers_then_stops_the_server_and_the_runner(app, fake):
    """POST /api/shutdown -> 200, apoi serverul se oprește singur (motiv «shutdown») și oprește și rularea în curs."""
    reply = app.call("POST", "/api/shutdown", body={})
    assert reply.status == 200 and reply.json() == {"stopping": True}
    wait_for(lambda: app.stopped, "serverul s-a oprit după /api/shutdown")
    assert app.stop_reason == STOP_SHUTDOWN and ("shutdown",) in fake.calls


def test_an_internal_error_is_a_generic_500_without_details_and_the_server_survives(app, fake, monkeypatch):
    """O excepție neprevăzută într-o rută -> 500 generic (fără mesajul excepției, fără traceback), cu antetele de securitate; serverul rămâne în picioare."""
    def broken():
        raise RuntimeError("detaliu-intern-secret")

    monkeypatch.setattr(fake, "snapshot", broken)
    reply = app.call("GET", "/api/state")
    assert reply.status == 500 and reply.error_code == "internal_error"
    assert b"detaliu-intern-secret" not in reply.body and b"Traceback" not in reply.body, "un 500 nu are voie să scoată detalii interne"
    assert reply.headers["content-security-policy"] == app_security.CONTENT_SECURITY_POLICY
    _assert_alive(app)
