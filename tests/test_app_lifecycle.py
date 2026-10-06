"""Teste pentru viața serverului local: legare doar la 127.0.0.1 pe port ales de sistem, oprire (buton, Ctrl+C, inactivitate), jurnal fără token.

Pe servere reale pornite în firul testului. Oprirea automată se verifică cu timpi mici injectați (fără să aștepte 30 de minute) și
cu ceas fals pentru IdleMonitor. Verifică și că: o cerere respinsă nu ține serverul treaz, o analiză în curs îl ține deschis,
tokenul nu ajunge niciodată în jurnal, cereri simultane și un client lent nu blochează serverul. Valorile sunt inventate.
"""

import socket
import threading

import pytest

from emag_spend import app_security, app_server
from emag_spend.app_server import STOP_IDLE, STOP_INTERRUPTED, STOP_SHUTDOWN, AppServer, IdleMonitor
from tests.app_support import POLL_SECONDS, WAIT_SECONDS, FakeRunner, FakeUpdateJob, running_app, wait_for, write_interface

SHORT_IDLE_SECONDS = 0.3  # timp mic injectat în loc de cele 30 de minute reale


@pytest.fixture
def app(tmp_path):
    """Server real cu runner fals, oprire automată peste o oră (testele de inactivitate dau alt timp)."""
    write_interface(tmp_path / "interfata")
    with running_app(tmp_path) as running:
        yield running


# ---------- legare ----------

def test_the_server_listens_only_on_loopback_on_a_system_chosen_port(app):
    """Serverul e legat la 127.0.0.1 (nu 0.0.0.0, nu o interfață de rețea), pe un port ales de sistem (nu unul fix)."""
    host, port = app.app._httpd.socket.getsockname()[:2]
    assert host == "127.0.0.1", f"serverul ascultă pe {host}: ar fi vizibil și din rețeaua locală"
    assert port == app.port and port > 1023, "portul nu e unul efemer ales de sistem"
    assert app_server.ANY_FREE_PORT == 0 and app_server.LOOPBACK_HOST == "127.0.0.1"


# Mai multe conexiuni decât cere pagina deodată (~20 de fișiere), toate deschise fără ca serverul să accepte vreuna.
QUEUED_CONNECTIONS = 30


def test_the_server_queues_every_connection_the_page_opens_at_once():
    """Coada de conexiuni (listen) are loc pentru toate fișierele paginii cerute deodată. Cu coada implicită de 5, pe Windows
    o conexiune în plus era refuzată pe loc, iar Edge/Chrome recente nu reîncearcă pe 127.0.0.1: un script lipsea și pagina
    rămânea la „Se verifică aplicația…”. Aici nimeni nu acceptă conexiunile, deci fiecare trebuie să încapă în coadă."""
    server = app_server._LocalHTTPServer((app_server.LOOPBACK_HOST, app_server.ANY_FREE_PORT), app_server._Handler)
    opened = []
    try:
        port = server.server_address[1]
        for _ in range(QUEUED_CONNECTIONS):
            opened.append(socket.create_connection((app_server.LOOPBACK_HOST, port), timeout=WAIT_SECONDS))
    finally:
        for connection in opened:
            connection.close()
        server.server_close()
    assert len(opened) == QUEUED_CONNECTIONS


def test_two_servers_get_different_ports(tmp_path):
    """Portul nu e fix: două servere pornite în același timp primesc porturi diferite (un port cunoscut ar fi o țintă pentru pagini străine)."""
    with running_app(tmp_path) as first, running_app(tmp_path) as second:
        assert first.port != second.port


def test_the_loopback_name_is_in_the_hosts_the_server_accepts():
    """Adresa la care se leagă serverul e una din gazdele pe care le acceptă verificarea Host (altfel propria pagină ar fi refuzată)."""
    assert app_server.LOOPBACK_HOST in app_security.ALLOWED_HOST_NAMES


def test_another_process_cannot_share_the_port_even_with_reuseaddr(app):
    """Nici un alt socket nu poate lega același port, nici cu SO_REUSEADDR (ar „fura” cereri, cu tokenul în ele).

    Windows-ul recent refuză singur asta pe aceeași adresă (eroarea 10013, verificat pe build 26300), deci testul nu poate vedea diferența
    dintre cu și fără opțiunea SO_EXCLUSIVEADDRUSE a serverului, care rămâne ca plasă de siguranță pentru versiuni mai vechi de Windows.
    """
    for reuse in (False, True):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
            if reuse:
                other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                other.bind(("127.0.0.1", app.port))


def test_the_port_is_not_reachable_on_the_other_addresses_of_this_computer(app):
    """Pe adresele de rețea ale acestui calculator (nu 127.0.0.1) portul serverului nu răspunde: aplicația nu e vizibilă din rețeaua locală."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        pytest.skip("nu pot afla adresele de rețea ale calculatorului")
    addresses = {a for a in addresses if not a.startswith("127.")}
    if not addresses:
        pytest.skip("calculatorul nu are altă adresă IPv4 decât bucla locală")
    for address in addresses:
        try:
            with socket.create_connection((address, app.port), timeout=1):
                pytest.fail(f"serverul răspunde pe {address}:{app.port}, adică și din afara bucla locale: ar fi vizibil în rețea")
        except OSError:
            pass  # refuzat sau fără răspuns: exact ce vrem


def test_the_page_url_has_the_token_only_in_the_fragment_and_only_on_request(app):
    """page_url() fără token e sigur de afișat; cu token îl pune în fragment (#t=...), pe portul real al serverului."""
    assert app.app.page_url() == f"http://127.0.0.1:{app.port}/aplicatie.html"
    assert app.app.page_url(with_token=True) == f"http://127.0.0.1:{app.port}/aplicatie.html#t={app.token}"


# ---------- oprire ----------

def test_ctrl_c_stops_the_server_cleanly_and_stops_the_run(tmp_path, monkeypatch):
    """Ctrl+C (KeyboardInterrupt în bucla principală) oprește serverul curat: motiv «interrupted», rularea e oprită, socket-ul e închis."""
    fake = FakeRunner()
    server = AppServer(runner=fake, outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil", interface_dir=tmp_path / "interfata",
                       idle_seconds=3600, poll_seconds=POLL_SECONDS, update_job=FakeUpdateJob())
    port = server.port

    def interrupted(timeout=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(server._stop, "wait", interrupted)
    assert server.serve() == STOP_INTERRUPTED
    assert ("shutdown",) in fake.calls, "rularea în curs nu a fost oprită la Ctrl+C"
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_after_stopping_the_port_is_closed_and_the_reason_is_shutdown(tmp_path):
    """După oprire portul nu mai ascultă, iar motivul e «shutdown» când oprirea vine din buton (request_stop)."""
    with running_app(tmp_path) as app:
        port = app.port
        assert app.stop() == STOP_SHUTDOWN
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


# ---------- inactivitate ----------

def test_the_server_stops_by_itself_after_a_period_without_requests(tmp_path):
    """Fără nicio cerere, serverul se oprește singur (motiv «idle») după timpul de inactivitate și oprește și rularea (nu rămâne deschis)."""
    fake = FakeRunner()
    with running_app(tmp_path, runner=fake, idle_seconds=SHORT_IDLE_SECONDS) as app:
        wait_for(lambda: app.stopped, "oprirea automată după inactivitate", timeout=WAIT_SECONDS)
        assert app.stop_reason == STOP_IDLE and ("shutdown",) in fake.calls


def test_requests_keep_the_server_alive(tmp_path):
    """Cât vin cereri valide, serverul nu se oprește (activitatea repornește măsurătoarea); după ce încetează, se oprește."""
    with running_app(tmp_path, idle_seconds=SHORT_IDLE_SECONDS) as app:
        for _ in range(int(SHORT_IDLE_SECONDS * 3 / POLL_SECONDS / 4) + 1):
            assert app.call("GET", "/api/hello").status == 200 and not app.stopped, "serverul s-a oprit cu toate că primea cereri"
            threading.Event().wait(SHORT_IDLE_SECONDS / 4)
        wait_for(lambda: app.stopped, "oprirea după ce au încetat cererile")
        assert app.stop_reason == STOP_IDLE


def test_rejected_requests_do_not_keep_the_server_alive(tmp_path):
    """Cererile cu Host sau Origin greșite NU repornesc măsurătoarea: un program care bate la port nu poate ține aplicația deschisă la nesfârșit."""
    with running_app(tmp_path, idle_seconds=SHORT_IDLE_SECONDS) as app:
        deadline = threading.Event()
        refused = []

        def knock():
            while not app.stopped and not deadline.is_set():
                try:
                    refused.append(app.call("GET", "/api/hello", host="evil.example").status)
                except OSError:
                    break
                deadline.wait(0.02)

        thread = threading.Thread(target=knock, daemon=True)
        thread.start()
        wait_for(lambda: app.stopped, "oprirea automată în ciuda cererilor respinse")
        deadline.set()
        thread.join(WAIT_SECONDS)
        assert refused and set(refused) == {403} and app.stop_reason == STOP_IDLE


def test_a_running_analysis_keeps_the_server_open_and_the_clock_restarts_after_it(tmp_path):
    """Cât rulează o analiză serverul nu se oprește, chiar fără cereri; după ce se termină, măsurătoarea inactivității pornește de la capăt."""
    fake = FakeRunner()
    fake.busy = True
    with running_app(tmp_path, runner=fake, idle_seconds=SHORT_IDLE_SECONDS) as app:
        threading.Event().wait(SHORT_IDLE_SECONDS * 3)
        assert not app.stopped, "serverul s-a oprit în timpul unei analize: ar fi pierdut o rulare de zeci de minute"
        fake.busy = False
        wait_for(lambda: app.stopped, "oprirea după terminarea analizei")
        assert app.stop_reason == STOP_IDLE


def test_idle_monitor_counts_from_the_last_activity():
    """IdleMonitor cu ceas fals: expiră exact la timeout de la ultima activitate; note_activity() îl repornește."""
    now = [100.0]
    monitor = IdleMonitor(30, clock=lambda: now[0])
    assert not monitor.expired()
    now[0] = 129.9
    assert not monitor.expired()
    now[0] = 130.0
    assert monitor.expired()
    monitor.note_activity()
    assert not monitor.expired()
    now[0] = 159.9
    assert not monitor.expired()
    now[0] = 160.0
    assert monitor.expired()


# ---------- EMAG_APP_IDLE_MINUTES ----------

def test_the_idle_default_is_thirty_minutes_with_documented_limits():
    """Implicit 30 de minute; limitele 1 și 1440 (24 de ore) sunt constante numite, cu motivul scris lângă ele."""
    assert (app_server.DEFAULT_IDLE_MINUTES, app_server.MIN_IDLE_MINUTES, app_server.MAX_IDLE_MINUTES) == (30, 1, 1440)


def test_the_environment_variable_sets_the_idle_minutes(monkeypatch):
    """EMAG_APP_IDLE_MINUTES schimbă timpul; lipsă sau goală înseamnă implicitul; spațiile din jur se ignoră."""
    monkeypatch.delenv("EMAG_APP_IDLE_MINUTES", raising=False)
    assert app_server.idle_minutes_from_environment() == 30
    for raw, expected in (("", 30), ("   ", 30), ("1", 1), ("45", 45), (" 90 ", 90), ("1440", 1440)):
        monkeypatch.setenv("EMAG_APP_IDLE_MINUTES", raw)
        assert app_server.idle_minutes_from_environment() == expected, raw


@pytest.mark.parametrize("raw", ["0", "-5", "1441", "99999", "abc", "1.5", "1e2", "treizeci", "٣٠"])
def test_a_bad_idle_value_stops_the_start_with_a_romanian_message(monkeypatch, raw):
    """Valoare greșită (în afara limitelor sau nenumerică): ValueError în română care numește variabila și limitele, înainte să se lege orice socket."""
    monkeypatch.setenv("EMAG_APP_IDLE_MINUTES", raw)
    with pytest.raises(ValueError) as error:
        app_server.idle_minutes_from_environment()
    message = str(error.value)
    assert "EMAG_APP_IDLE_MINUTES" in message and "între 1 și 1440" in message and raw.strip() in message


def test_a_bad_environment_value_does_not_leave_a_listening_socket(tmp_path, monkeypatch):
    """Dacă variabila e greșită, AppServer ridică ValueError ÎNAINTE de a lega socket-ul (nu rămâne un port deschis fără stăpân)."""
    monkeypatch.setenv("EMAG_APP_IDLE_MINUTES", "abc")
    created = []
    real = app_server._LocalHTTPServer.__init__
    monkeypatch.setattr(app_server._LocalHTTPServer, "__init__", lambda self, *args, **kwargs: created.append(1) or real(self, *args, **kwargs))
    with pytest.raises(ValueError):
        AppServer(runner=FakeRunner(), outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil", interface_dir=tmp_path / "interfata")
    assert not created, "serverul s-a legat la un port înainte să fie verificată variabila de mediu"


# ---------- jurnal ----------

def test_the_token_never_reaches_the_log(app, caplog):
    """Tokenul (corect sau încercat de un atacator) nu apare în niciun mesaj de jurnal, nici la erori, nici la cereri respinse."""
    caplog.set_level("DEBUG")
    attacker_token = "token-incercat-de-un-atacator-1234567890"
    app.call("GET", "/api/state")
    app.call("GET", "/api/state", token=attacker_token)
    app.call("GET", "/api/state", token=False)
    app.call("POST", "/api/runs", body={"mode": "demo"}, origin="https://evil.example")
    app.call("POST", "/api/runs", body={"mode": "x"})
    app.call("POST", "/api/runs", body=b"x" * 5000)
    app.raw_get("/api/state?x=1", token=True)
    assert caplog.records, "testul n-a produs nicio linie de jurnal: nu dovedește nimic"
    logged = "\n".join(f"{record.getMessage()} {record.args!r} {record.exc_text or ''}" for record in caplog.records)
    for secret in (app.token, attacker_token):
        assert secret not in logged, "un token a ajuns în jurnal: oricine îl citește ar putea comanda aplicația cât rulează"
    assert "X-App-Token" not in logged


# ---------- robustețe ----------

def test_parallel_requests_are_all_answered(app):
    """Cereri simultane (ca o pagină cu mai multe interogări deodată) primesc toate răspuns corect, de la fire separate."""
    results = []

    def ask():
        results.append(app.call("GET", "/api/hello").status)

    threads = [threading.Thread(target=ask) for _ in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_SECONDS)
    assert results == [200] * 24


def test_a_slow_client_does_not_block_the_others(app):
    """Un client care deschide conexiunea și nu trimite nimic nu blochează serverul: celelalte cereri sunt tratate în paralel."""
    with socket.create_connection(("127.0.0.1", app.port), timeout=WAIT_SECONDS) as slow:
        slow.sendall(b"GET /api/hello HTTP/1.1\r\nHost: ")  # cerere neterminată
        assert app.call("GET", "/api/hello").status == 200
