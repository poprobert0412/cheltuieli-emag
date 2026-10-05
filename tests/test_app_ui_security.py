"""Teste în browser real ale securității paginii aplicatie.html: cheia de acces, rețeaua și politica de conținut.

Primește: pagina servită de serverul fals din tests/app_ui_support.py (cu politica de conținut din brief, trimisă ca antet).
Verifică: cheia din #t=... se scoate din adresă și nu ajunge în localStorage, sessionStorage, cookie, IndexedDB, DOM sau în vreo
adresă cerută; pleacă doar în antetul X-App-Token; o cheie lipsă, greșită sau malformată duce la ecranul „nu mai are cheia de
acces”; reîncărcarea o pierde; nicio cerere în afara serverului aplicației; descărcarea folosește un link blob:, nu unul cu cheie;
politica de conținut chiar se aplică în testele astea (un stil sau eval inline e refuzat); pagina merge și fără localStorage.
Ce NU face: nu testează serverul real (emag_spend/app_server.py are testele lui). Se sare dacă niciun browser nu pornește.
"""

import json

import pytest

from tests.app_ui_support import (  # noqa: F401 - fixture-urile se găsesc prin importul lor în modul
    APP_PAGE, browser, current_screen, fake, open_page, playwright_instance, probe_problems, wait_js, wait_screen,
)

pytest.importorskip("playwright.sync_api")

# Observă (de la începutul paginii) fiecare <a> adăugat în document: descărcarea trebuie să folosească doar un link blob:.
ANCHOR_SPY = """(() => { window.__anchors = [];
  new MutationObserver((records) => { for (const r of records) for (const n of r.addedNodes) {
    if (n.nodeType === 1 && n.tagName === 'A') window.__anchors.push({href: n.getAttribute('href'), download: n.getAttribute('download')}); } })
    .observe(document, {childList: true, subtree: true}); })();"""
BLOCK_STORAGE = "(() => { for (const name of ['localStorage', 'sessionStorage']) Object.defineProperty(window, name, { get() { throw new Error('stocare blocată'); } }); })();"


def storage_snapshot(page) -> dict:
    """Tot ce poate ține pagina în browser: localStorage, sessionStorage, cookie, IndexedDB, window.name, history.state."""
    return page.evaluate("""async () => ({
        local: Object.fromEntries(Object.entries(localStorage)), session: Object.fromEntries(Object.entries(sessionStorage)),
        cookie: document.cookie, idb: (await indexedDB.databases()).length, name: window.name, state: history.state })""")


def test_the_key_is_removed_from_the_address_and_never_stored(open_page, fake):
    """După încărcare adresa nu mai are #t=...; cheia nu e în nicio stocare, în cookie-urile contextului, în DOM sau în linkuri."""
    page, probe = open_page()
    assert current_screen(page) == "ready"
    assert page.url == f"{fake.origin}{APP_PAGE}", page.url
    assert fake.token not in page.url
    snapshot = storage_snapshot(page)
    assert snapshot == {"local": {}, "session": {}, "cookie": "", "idb": 0, "name": "", "state": None}
    assert page.context.cookies() == []
    html = page.evaluate("document.documentElement.outerHTML")
    assert fake.token not in html
    assert fake.token not in json.dumps(page.evaluate("[...document.querySelectorAll('a[href]')].map((a) => a.href)"))
    assert probe_problems(probe) == {}


def test_the_only_thing_stored_in_the_browser_is_the_theme_choice(open_page, fake):
    """După ce omul schimbă tema, singurul lucru din localStorage e cheia emag-tema; cheia de acces nu apare nicăieri."""
    page, _ = open_page()
    page.click("#theme-toggle")
    snapshot = storage_snapshot(page)
    assert snapshot["local"] == {"emag-tema": "light"}
    assert snapshot["session"] == {} and snapshot["cookie"] == "" and snapshot["idb"] == 0
    assert fake.token not in json.dumps(snapshot)


def test_every_api_request_carries_the_key_in_the_header_and_never_in_the_address(open_page, fake):
    """Un ciclu complet (pornire, progres, raport, descărcare): fiecare cerere /api/* are X-App-Token; nicio cale sau antet de altă formă nu poartă cheia."""
    page, probe = open_page()
    page.click("#btn-demo")
    wait_screen(page, "working")
    run_id = fake.started[-1]["run_id"]
    fake.finish_run(run_id, kind="demo")
    wait_screen(page, "done")
    page.wait_for_selector("#report-root.emag-dash [data-ed-block]")
    with page.expect_download():
        page.click("button[data-file='produse.csv']")
    api = fake.api_requests()
    assert len(api) >= 6
    assert all(r["headers"].get("x-app-token") == fake.token for r in api)
    assert all(fake.token not in r["target"] for r in fake.requests), "cheia nu apare în nicio adresă cerută (nici în interogare)"
    assert all(r["headers"].get("x-app-token") is None for r in fake.requests if not r["path"].startswith("/api/"))
    posts = [r for r in api if r["method"] == "POST"]
    assert posts and all(r["headers"].get("content-type", "").startswith("application/json") for r in posts)
    assert all(r["headers"].get("origin") in (None, fake.origin) for r in posts)
    assert all(r["headers"].get("cookie") is None for r in fake.requests), "nicio cerere nu poartă cookie"
    assert probe_problems(probe) == {}


def test_the_page_talks_only_to_the_app_server(open_page, fake):
    """În tot ciclul, cererile merg doar spre serverul aplicației (sau sunt data:/blob:); nimic în afară."""
    page, probe = open_page()
    page.click("#btn-start")
    wait_screen(page, "working")
    fake.set_state(state="error", error={"code": "x", "message": "Mesaj de test."})
    wait_screen(page, "error")
    assert probe.outside_requests() == []
    assert all(u.startswith((fake.origin, "data:", "blob:")) for u in probe.urls)


def test_without_a_key_the_page_asks_for_a_new_start_and_makes_no_api_request(open_page, fake):
    """Pagina deschisă fără #t=... arată „nu mai are cheia de acces” și nu trimite nicio cerere /api/*."""
    page, probe = open_page(with_token=False, wait_for=None)
    wait_screen(page, "closed-nokey")
    assert page.inner_text("#nokey-t") == "Pagina nu mai are cheia de acces"
    assert "porneste.bat" in page.inner_text("#screen-closed-nokey")
    assert fake.api_requests() == []
    assert probe_problems(probe) == {}


def test_a_wrong_key_is_refused_and_looks_like_a_missing_key(open_page, fake):
    """O cheie bine formată dar greșită primește 401 de la aplicație; pagina arată același ecran „nu mai are cheia de acces”."""
    page, _ = open_page(url=f"{fake.origin}{APP_PAGE}#t=" + "a" * 43, wait_for=None)
    wait_screen(page, "closed-nokey")
    attempts = fake.api_requests()
    assert attempts and all(r["headers"]["x-app-token"] == "a" * 43 for r in attempts)
    assert "#t=" not in page.url


def test_a_malformed_key_never_reaches_the_header(open_page, fake):
    """O valoare ciudată în #t=... (spații, semne) nu e folosită ca antet: nicio cerere, ecranul „nu mai are cheia”, fragmentul dispare din adresă."""
    page, _ = open_page(url=f"{fake.origin}{APP_PAGE}#t=cheie%20ciudata!", wait_for=None)
    wait_screen(page, "closed-nokey")
    assert fake.api_requests() == []
    assert "#t=" not in page.url and "ciudata" not in page.url


def test_reloading_the_page_loses_the_key(open_page, fake):
    """Reîncărcarea paginii pierde cheia (e doar în memorie): apare „nu mai are cheia de acces”, cum spune FAQ-ul."""
    page, _ = open_page()
    assert current_screen(page) == "ready"
    page.reload()
    wait_screen(page, "closed-nokey")


def test_the_content_security_policy_really_applies_in_these_tests(open_page, fake):
    """Canar: un stil inline și un script inline sunt refuzate de politica de conținut; fără asta, testele „fără erori de consolă” n-ar dovedi nimic."""
    page, probe = open_page()
    page.evaluate("document.body.setAttribute('style', 'color: red')")
    assert page.evaluate("getComputedStyle(document.body).color") != "rgb(255, 0, 0)"
    page.evaluate("() => { const s = document.createElement('script'); s.textContent = 'window.__inline = 1'; document.head.appendChild(s); }")
    assert page.evaluate("window.__inline") is None
    refusals = [line for line in probe.console if "Content Security Policy" in line or "Refused to" in line]
    assert len(refusals) >= 2, probe.console


def test_the_download_uses_a_blob_link_with_no_key_in_it(browser, fake):
    """Descărcarea: un singur <a> temporar cu href blob: și atributul download; nicio adresă cu cheie, nicio navigare."""
    from tests.app_ui_support import open_app
    context, page, probe = open_app(browser, fake, init_script=ANCHOR_SPY)
    try:
        page.click("#btn-demo")
        wait_screen(page, "working")
        fake.finish_run(fake.started[-1]["run_id"], kind="demo")
        wait_screen(page, "done")
        with page.expect_download():
            page.click("button[data-file='raport.html']")
        anchors = page.evaluate("window.__anchors")
        mine = [a for a in anchors if a["download"]]
        assert len(mine) == 1 and mine[0]["href"].startswith("blob:") and mine[0]["download"] == "raport.html"
        assert fake.token not in json.dumps(anchors)
        assert page.url == f"{fake.origin}{APP_PAGE}"
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_the_page_works_when_browser_storage_is_blocked(browser, fake):
    """Fără localStorage (fereastră privată, date blocate) pagina pornește, tema se schimbă pe loc și nimic nu aruncă excepții."""
    from tests.app_ui_support import open_app
    context, page, probe = open_app(browser, fake, init_script=BLOCK_STORAGE)
    try:
        assert current_screen(page) == "ready"
        page.click("#theme-toggle")
        assert page.get_attribute("html", "data-theme") == "light"
        assert probe_problems(probe) == {}
    finally:
        context.close()


def test_html_in_server_messages_and_run_data_is_never_interpreted(open_page, fake):
    """Textele venite de la aplicație (mesaje, date ale rulărilor) intră ca text: niciun element nou din ele, niciun script rulat."""
    evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>'
    fake.runs = [{"id": "2026-10-05_10-00-00", "created_at": evil, "kind": "real", "orders": 3, "kept_bani": 100, "has_report": True}]
    page, probe = open_page()
    assert page.locator("#hist-list img, #hist-list script").count() == 0
    assert evil in page.inner_text("#hist-list")
    page.click("#btn-start")
    wait_screen(page, "working")
    fake.set_state(state="error", error={"code": "x", "message": evil}, message=evil)
    wait_screen(page, "error")
    assert page.evaluate("window.__pwned") is None
    assert page.locator("#error-message img, #error-message script").count() == 0
    assert evil in page.inner_text("#error-message")
