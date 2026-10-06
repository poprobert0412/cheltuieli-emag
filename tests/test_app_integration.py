"""Test de integrare cap-la-cap al aplicației locale: server REAL pe 127.0.0.1 (port 0), runner real, pipeline real în modul demo.

Pornește serverul în firul testului, rulează `mode=demo` cu rezultatele în folder temporar, urmărește /api/state până la «done»,
citește /api/runs/<id>/analysis și descarcă fișierele; apoi aceleași lucruri prin `python ruleaza.py --aplicatie` (cu --fara-browser și
fără), cu jurnalul verificat să nu conțină tokenul. Fără browser real, fără cont eMAG; valorile sunt inventate (demo_data.py).
"""

import hashlib
import json
import re
import threading

import pytest

import ruleaza
from emag_spend import site_demo_writer
from emag_spend.app_runner import AppRunner
from emag_spend.browser_session import LoginTimeout
from emag_spend.demo_data import demo_orders_and_returns
from emag_spend.progress import PHASE_FETCHING_ORDERS, PHASE_WAITING_LOGIN
from tests.app_support import WAIT_SECONDS, running_app, wait_for, write_interface
from tests.garda_audit import isolated_program
from tests.test_app_runner import FakePipeline, Gate

REAL_DEMO_DATA_JS = site_demo_writer.DEMO_DATA_JS_FILE  # calea reală, memorată înainte ca vreun test s-o mute
DEMO_TIMEOUT_SECONDS = 60  # un demo durează sub o secundă; 60 de secunde înseamnă blocat


def _sha256(path) -> str:
    """Amprenta unui fișier (pentru a dovedi că nu a fost atins)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_for_final_state(app, token=True):
    """Sondează /api/state până într-o stare finală și întoarce lista stărilor văzute (în ordine, fără repetări) și ultimul răspuns."""
    seen: list[str] = []

    def poll():
        body = app.call("GET", "/api/state", token=token).json()
        if not seen or seen[-1] != body["state"]:
            seen.append(body["state"])
        return body if body["state"] in ("done", "error", "cancelled") else None

    final = wait_for(poll, "starea finală a rulării", timeout=DEMO_TIMEOUT_SECONDS)
    return seen, final


@pytest.fixture
def real_app(tmp_path, monkeypatch):
    """Server real cu runner real; demo-data.js al site-ului mutat în tmp (dacă ar fi rescris, nu ar atinge fișierul din proiect)."""
    moved = tmp_path / "site" / "demo-data.js"
    monkeypatch.setattr(site_demo_writer, "DEMO_DATA_JS_FILE", moved)
    write_interface(tmp_path / "interfata")
    runner = AppRunner(outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil")
    with running_app(tmp_path, runner=runner) as app:
        app.moved_demo_data = moved
        yield app


def test_a_demo_run_goes_from_the_button_to_the_report_over_real_http(real_app, tmp_path):
    """POST /api/runs {"mode": "demo"} -> 202; /api/state ajunge la «done»; analiza, lista și descărcările sunt cele ale rulării; fișierele merg doar în iesiri/ din tmp."""
    before = _sha256(REAL_DEMO_DATA_JS)
    started = real_app.call("POST", "/api/runs", body={"mode": "demo", "threshold_lei": 1000})
    assert started.status == 202
    run_id = started.json()["run_id"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_demo", run_id)

    seen, final = _wait_for_final_state(real_app)
    assert final["state"] == "done" and final["run_id"] == run_id and final["error"] is None, f"stări văzute: {seen}; final: {final}"
    assert seen[0] in ("starting", "analyzing", "done") and seen[-1] == "done"

    orders, _ = demo_orders_and_returns()
    analysis = real_app.call("GET", f"/api/runs/{run_id}/analysis")
    assert analysis.status == 200
    body = analysis.json()
    assert body["meta"]["orders"] == len(orders) and body["meta"]["threshold_bani"] == 100000, "analiza nu e cea a rulării cerute (prag 1000 lei)"
    for key in ("funnel", "by_category", "price_history", "warnings_detail", "warnings"):
        assert key in body, f"analiza citită prin API nu are cheia {key}"

    (listed,) = real_app.call("GET", "/api/runs").json()
    assert listed["id"] == run_id and listed["kind"] == "demo" and listed["orders"] == len(orders) and listed["has_report"] is True
    assert listed["kept_bani"] == body["funnel"]["kept_bani"] and listed["spent_bani"] == body["paid"]["spent_bani"]

    report = real_app.call("GET", f"/api/runs/{run_id}/files/raport.html")
    assert report.status == 200 and b"<html" in report.body.lower() and report.headers["content-disposition"].startswith("attachment")
    assert real_app.call("GET", f"/api/runs/{run_id}/files/produse.csv").status == 200
    assert real_app.call("GET", f"/api/runs/{run_id}/files/istoric_preturi.csv").status == 200
    assert "PĂSTRAT" in real_app.call("GET", f"/api/runs/{run_id}/files/rezumat.txt").body.decode("utf-8")
    assert real_app.call("GET", f"/api/runs/{run_id}/files/comenzi.json").status == 404, "datele brute ale rulării s-au putut descărca"

    assert (tmp_path / "iesiri" / run_id / "analiza.json").is_file()
    assert not real_app.moved_demo_data.exists(), "rularea din aplicație a rescris demo-data.js al site-ului"
    assert _sha256(REAL_DEMO_DATA_JS) == before, "fișierul real interfata/assets/demo-data.js (urmărit de git) a fost modificat de o rulare din aplicație"


def test_a_second_demo_run_after_the_first_gets_its_own_folder(real_app):
    """Două rulări demo una după alta (poate în aceeași secundă) primesc id-uri și foldere diferite, fără să-și suprascrie fișierele."""
    ids = []
    for _ in range(2):
        reply = real_app.call("POST", "/api/runs", body={"mode": "demo"})
        assert reply.status == 202, reply.body
        ids.append(reply.json()["run_id"])
        _wait_for_final_state(real_app)
    assert ids[0] != ids[1]
    assert {run["id"] for run in real_app.call("GET", "/api/runs").json()} == set(ids)


def test_cancel_and_errors_travel_through_http(tmp_path, monkeypatch):
    """Cu un pipeline fals în runner-ul real: starea de lucru se vede prin HTTP, POST cancel o oprește (cancelled), iar o eroare apare cu cod și mesaj în română."""
    gate = Gate()

    def slow(options, progress):
        progress.phase(PHASE_FETCHING_ORDERS)
        progress.advance(5, 100)
        gate.pass_through()
        progress.raise_if_cancelled()

    runner = AppRunner(outputs_dir=tmp_path / "iesiri", profile_dir=tmp_path / "profil", pipeline=FakePipeline(slow))
    write_interface(tmp_path / "interfata")
    with running_app(tmp_path, runner=runner) as app:
        assert app.call("POST", "/api/runs", body={"mode": "real"}).status == 202
        wait_for(gate.reached.is_set, "pipeline-ul fals a ajuns la comenzi")
        state = app.call("GET", "/api/state").json()
        assert state["state"] == "fetching_orders" and state["progress"] == {"phase": "fetching_orders", "done": 5, "total": 100}
        assert app.call("POST", "/api/runs", body={"mode": "demo"}).status == 409, "a doua rulare a pornit cât prima era în curs"
        assert app.call("POST", "/api/runs/current/cancel", body={}).json() == {"cancel_requested": True}
        gate.proceed.set()
        seen, final = _wait_for_final_state(app)
        assert final["state"] == "cancelled" and final["error"] is None

    def login_expired(options, progress):
        progress.phase(PHASE_WAITING_LOGIN)
        raise LoginTimeout("nu te-ai logat în timpul alocat; rulează din nou scriptul")

    runner = AppRunner(outputs_dir=tmp_path / "iesiri2", profile_dir=tmp_path / "profil", pipeline=FakePipeline(login_expired))
    with running_app(tmp_path, runner=runner) as app:
        assert app.call("POST", "/api/runs", body={"mode": "real"}).status == 202
        seen, final = _wait_for_final_state(app)
        assert final["state"] == "error" and final["error"]["code"] == "login_timeout" and "Ce faci:" in final["error"]["message"]


# ---------- prin linia de comandă ----------

def _run_cli_in_a_thread(argv):
    """Rulează `ruleaza.main(argv)` într-un fir; întoarce (firul, lista în care ajunge codul de ieșire)."""
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(ruleaza.main(argv)), daemon=True)
    thread.start()
    return thread, result


def _wait_for_output(capsys, collected: list[str], pattern: str) -> str:
    """Strânge ce scrie programul pe ecran până apare `pattern` (o expresie regulată); întoarce tot textul de până atunci."""
    def look():
        collected.append(capsys.readouterr().out)
        return "".join(collected) if re.search(pattern, "".join(collected)) else None

    return wait_for(look, f"în consolă apare «{pattern}»")


def test_aplicatie_with_fara_browser_prints_the_full_url_and_stops_cleanly(tmp_path, monkeypatch, capsys):
    """`--aplicatie --fara-browser`: nu deschide nimic, scrie URL-ul COMPLET (cu token) în consolă; adresa merge cu tokenul; /api/shutdown -> cod 0; jurnalul nu are tokenul."""
    monkeypatch.setenv("EMAG_APP_IDLE_MINUTES", "5")
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "0")  # aplicația reală: fără verificarea versiunii noi (niciun test nu iese pe internet)
    with isolated_program(monkeypatch, tmp_path) as layout:
        thread, result = _run_cli_in_a_thread(["--aplicatie", "--fara-browser"])
        collected: list[str] = []
        text = _wait_for_output(capsys, collected, r"cu cheia de acces[^\n]*http://127\.0\.0\.1:\d+/aplicatie\.html#t=\S+")
        url = re.search(r"(http://127\.0\.0\.1:(\d+)/aplicatie\.html)#t=(\S+)", text)
        base, port, token = url.group(1), int(url.group(2)), url.group(3)
        assert layout.opened == [], "cu --fara-browser nu are voie să deschidă nimic"
        assert "5 minute fără activitate" in text and "Ctrl+C" in text

        import http.client

        def call(method, path, headers=None, body=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
            reply = connection.getresponse()
            return reply.status, reply.read()

        assert call("GET", "/api/hello")[0] == 401
        status, body = call("GET", "/api/hello", {"X-App-Token": token})
        assert status == 200 and json.loads(body)["app"] == "cheltuieli-emag"
        assert call("POST", "/api/shutdown", {"X-App-Token": token, "Content-Type": "application/json"}, "{}")[0] == 200
        thread.join(WAIT_SECONDS)
        assert result == [0], f"codul de ieșire al aplicației oprite din pagină: {result}"
        collected.append(capsys.readouterr().out)
        assert "Aplicația a fost închisă din pagină." in "".join(collected)
    log_text = next(layout.logs.glob("*.log")).read_text(encoding="utf-8")
    assert token not in log_text, "tokenul a ajuns în jurnalul din folderul logs"
    assert f"127.0.0.1:{port}" in log_text and "aplicația s-a oprit (shutdown)" in log_text


def test_aplicatie_opens_the_browser_with_the_token_but_prints_a_url_without_it(tmp_path, monkeypatch, capsys):
    """Fără --fara-browser: browserul primește adresa cu token, iar consola arată adresa FĂRĂ token (tokenul nu rămâne pe ecran)."""
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "0")  # aplicația reală: fără verificarea versiunii noi (niciun test nu iese pe internet)
    with isolated_program(monkeypatch, tmp_path) as layout:
        thread, result = _run_cli_in_a_thread(["--aplicatie"])
        collected: list[str] = []
        text = _wait_for_output(capsys, collected, r"Pagina s-a deschis în browserul tău")
        wait_for(lambda: layout.opened, "browserul a primit o adresă")
        (opened,) = layout.opened
        found = re.fullmatch(r"http://127\.0\.0\.1:(\d+)/aplicatie\.html#t=(\S+)", opened)
        assert found, f"adresa dată browserului nu e cea așteptată: {opened!r}"
        port, token = int(found.group(1)), found.group(2)
        assert token not in text and "#t=" not in text, "tokenul a rămas pe ecran în consolă, deși browserul s-a deschis"
        assert f"http://127.0.0.1:{port}/aplicatie.html" in text

        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", "/api/shutdown", body="{}", headers={"Host": f"127.0.0.1:{port}", "X-App-Token": token, "Content-Type": "application/json"})
        assert connection.getresponse().status == 200
        thread.join(WAIT_SECONDS)
        assert result == [0]
    assert token not in next(layout.logs.glob("*.log")).read_text(encoding="utf-8")
