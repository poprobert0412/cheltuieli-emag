"""Teste ale logicii pure din pagină (mașina de stări a ecranului, formatări, validarea pragului), rulate în browser real.

Primește: aplicatie.html deschisă din folder (modulele se încarcă, ecranul rămâne „are nevoie de aplicația locală”, nu e nevoie de
server). Verifică prin page.evaluate: `App.state.computeScreen` pe modele inventate (inclusiv închiderea unei stări terminale și rularea
acceptată dar încă nevăzută), `App.format` (sume, numere, date, pluralul românesc) și `App.threshold.parse`.
Ce NU face: nu pornește servere și nu testează desenarea (test_app_ui_screens.py). Se sare dacă niciun browser nu pornește.
"""

import pytest

from tests.app_ui_support import INTERFACE_DIR, browser, playwright_instance  # noqa: F401 - fixture-urile se găsesc prin import

pytest.importorskip("playwright.sync_api")

PAGE_URL = (INTERFACE_DIR / "aplicatie.html").as_uri()


@pytest.fixture
def page(browser):
    """Pagina aplicației deschisă din folder, cu modulele App.* încărcate."""
    context = browser.new_context()
    opened = context.new_page()
    opened.goto(PAGE_URL)
    opened.wait_for_selector("html[data-current-screen='closed-needs-app']", state="attached")
    yield opened
    context.close()


def screen_for(page, model: dict, now: int = 0) -> str:
    """Ecranul calculat de App.state.computeScreen pentru un model dat (cheile lipsă se completează cu valorile de început)."""
    base = {"server": None, "closed": None, "viewRun": None, "dismissedKey": None, "pendingRunId": None, "pendingSince": 0}
    return page.evaluate("([model, now]) => App.state.computeScreen(model, now)", [{**base, **model}, now])


def server(state: str, run_id: str | None = "r1", started: str | None = "t1", error: dict | None = None) -> dict:
    """O stare de aplicație minimală, în forma din contract."""
    return {"state": state, "run_id": run_id, "started_at": started, "error": error}


@pytest.mark.parametrize("state", ["starting", "waiting_login", "fetching_orders", "fetching_returns", "analyzing"])
def test_every_active_state_is_the_working_screen(page, state):
    """Orice stare activă a aplicației înseamnă ecranul „în lucru”."""
    assert screen_for(page, {"server": server(state)}) == "working"


@pytest.mark.parametrize("state, screen", [("idle", "ready"), ("done", "done"), ("error", "error"), ("cancelled", "cancelled"), ("neprevazut", "ready")])
def test_resting_and_terminal_states_map_to_their_screen(page, state, screen):
    """Repaus = start; gata/eroare/anulat = ecranul lor; o stare necunoscută nu strică pagina (start)."""
    assert screen_for(page, {"server": server(state)}) == screen


def test_nothing_known_yet_is_the_loading_screen(page):
    """Până la primul răspuns al aplicației ecranul e „loading”."""
    assert screen_for(page, {}) == "loading"


def test_closed_wins_over_everything_else(page):
    """Dacă aplicația nu mai poate fi folosită, ecranul de „închis” are prioritate peste orice altă stare."""
    full = {"server": server("analyzing"), "viewRun": {"id": "x"}, "pendingRunId": "r9"}
    for reason in ("needs-app", "stopped", "user", "nokey"):
        assert screen_for(page, {**full, "closed": reason}) == f"closed-{reason}"


def test_a_dismissed_terminal_state_stays_dismissed_until_a_new_run(page):
    """După „Rulează din nou”/„Înapoi” starea terminală închisă nu revine; o rulare nouă (altă cheie) o readuce."""
    finished = server("done", run_id="r1", started="t1")
    key = page.evaluate("(s) => App.state.keyOf(s)", finished)
    assert screen_for(page, {"server": finished}) == "done"
    assert screen_for(page, {"server": finished, "dismissedKey": key}) == "ready"
    assert screen_for(page, {"server": server("done", run_id="r2", started="t2"), "dismissedKey": key}) == "done"
    failed = server("error", run_id=None, started=None, error={"code": "a", "message": "m"})
    failed_key = page.evaluate("(s) => App.state.keyOf(s)", failed)
    assert screen_for(page, {"server": failed, "dismissedKey": failed_key}) == "ready"
    other = server("error", run_id=None, started=None, error={"code": "b", "message": "m"})
    assert screen_for(page, {"server": other, "dismissedKey": failed_key}) == "error"


def test_an_old_run_opened_from_the_list_shows_the_report_screen(page):
    """O rulare veche deschisă din listă arată ecranul cu raport chiar dacă aplicația e în repaus."""
    assert screen_for(page, {"server": server("idle", None, None), "viewRun": {"id": "x", "kind": "real"}}) == "done"


def test_an_accepted_run_keeps_the_working_screen_until_the_state_catches_up_or_times_out(page):
    """După 202, „în lucru” se vede imediat; se oprește când starea arată rularea (sau după PENDING_RUN_TIMEOUT_MS)."""
    idle = server("idle", None, None)
    waiting = {"server": idle, "pendingRunId": "r1", "pendingSince": 1000}
    assert screen_for(page, waiting, now=1500) == "working"
    assert screen_for(page, waiting, now=1000 + 9999) == "working"
    assert screen_for(page, waiting, now=1000 + 10000) == "ready", "limita există: rularea care nu apare nu ține pagina blocată"
    arrived = {"server": server("analyzing", "r1"), "pendingRunId": "r1", "pendingSince": 1000}
    assert screen_for(page, arrived, now=1500) == "working"
    finished_fast = {"server": server("done", "r1"), "pendingRunId": "r1", "pendingSince": 1000}
    assert screen_for(page, finished_fast, now=1500) == "done"


@pytest.mark.parametrize("bani, text", [(123456, "1.234,56\xa0Lei"), (5, "0,05\xa0Lei"), (0, "0,00\xa0Lei"), (100, "1,00\xa0Lei"),
                                       (-250, "−2,50\xa0Lei"), (99999999999, "999.999.999,99\xa0Lei")])
def test_money_is_formatted_in_romanian_with_a_non_breaking_space(page, bani, text):
    """Sumele din bani: separator de mii cu punct, zecimale cu virgulă, spațiu nedespărțitor înainte de „Lei”."""
    assert page.evaluate("(b) => App.format.lei(b)", bani) == text


@pytest.mark.parametrize("value", [None, "12", float("nan")])
def test_money_and_counts_survive_values_that_are_not_numbers(page, value):
    """O valoare lipsă sau care nu e număr devine „—”, nu „NaN” sau o excepție."""
    assert page.evaluate("(v) => App.format.lei(v)", value) == "—"
    assert page.evaluate("(v) => App.format.count(v)", value) == "—"


@pytest.mark.parametrize("n, text", [(0, "0 comenzi"), (1, "1 comandă"), (2, "2 comenzi"), (19, "19 comenzi"), (20, "20 de comenzi"),
                                    (101, "101 comenzi"), (120, "120 de comenzi"), (1234, "1.234 de comenzi")])
def test_romanian_plural_forms(page, n, text):
    """Pluralul românesc cu trei forme: 1 comandă, 19 comenzi, 20 de comenzi."""
    forms = {"one": "comandă", "few": "comenzi", "other": "de comenzi"}
    assert page.evaluate("([n, f]) => App.format.counted(n, f)", [n, forms]) == text


@pytest.mark.parametrize("text, shown", [("2026-10-05 11:07:55", "5 oct. 2026, 11:07"), ("2026-10-05T09:00:00", "5 oct. 2026, 09:00"),
                                        ("2026-01-31", "31 ian. 2026"), ("necunoscut", "necunoscut"), ("", "—")])
def test_dates_are_shown_as_written_without_time_zone_shifts(page, text, shown):
    """Data se afișează în română, cu ora așa cum e scrisă (fără conversie de fus); textul neînțeles rămâne cum e."""
    assert page.evaluate("(t) => App.format.dateTime(t)", text) == shown


@pytest.mark.parametrize("typed, expected", [
    ("", {"ok": True, "value": None}), ("   ", {"ok": True, "value": None}), ("500", {"ok": True, "value": None}),
    ("500,00", {"ok": True, "value": None}), ("999,50", {"ok": True, "value": 999.5}), ("999.5", {"ok": True, "value": 999.5}),
    ("0", {"ok": True, "value": 0}), ("1000000000", {"ok": True, "value": 1000000000}), ("750", {"ok": True, "value": 750}),
])
def test_threshold_values_that_are_accepted(page, typed, expected):
    """Pragul gol sau egal cu implicitul nu se trimite (null); virgula și punctul merg; limitele 0 și 1 miliard sunt incluse."""
    assert page.evaluate("(t) => App.threshold.parse(t)", typed) == expected


@pytest.mark.parametrize("typed", ["abc", "-1", "1000000001", "1,2,3", "5 000", "1e3", "NaN", "Infinity", "0x10", "٣"])
def test_threshold_values_that_are_refused(page, typed):
    """Ce nu e un număr simplu sau iese din interval primește un mesaj în română."""
    result = page.evaluate("(t) => App.threshold.parse(t)", typed)
    assert result["ok"] is False and result["message"].endswith(".")
