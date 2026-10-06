"""Teste în browser real (Edge sau Chrome, fără fereastră, prin Playwright) pentru versiune și actualizare în aplicatie.html (D18).

Primește: pagina servită de serverul FALS din tests/app_ui_support.py (aceeași politică de conținut ca aplicația reală), cu răspunsul
GET /api/update condus de test. Verifică: versiunea mereu vizibilă și ce a aflat verificarea; banda „Versiune nouă” doar la „noua”;
„Ce e nou” ca text simplu (un <script> din notele lansării rămâne text); stările aplicării și ecranul „Versiunea nouă e instalată”;
dezactivările încrucișate cu „Pornește analiza”; erorile cu link doar spre o adresă https://github.com/; tastatura, tema întunecată,
fără scroll orizontal la 390 px, zero erori în consolă. Ce NU face: nu pornește aplicația reală (test_app_update_routes.py o face).
Se sare dacă niciun browser nu pornește. Versiunile, notele și adresele sunt inventate.
"""

import pytest

from tests.app_ui_contrast import parse_token_blocks
from tests.app_ui_support import (  # noqa: F401 - fixture-urile se găsesc prin importul lor în modul
    CONTRAST_SCAN_JS, FAKE_CURRENT_VERSION, OVERFLOW_JS, TAP_TARGET_JS, browser, capture, current_screen, fake, open_page, playwright_instance,
    probe_problems, update_state, wait_js, wait_screen,
)
from tests.test_app_ui_static import CSS_TEXT

pytest.importorskip("playwright.sync_api")

NEW_VERSION = "9.9.9"
RELEASE_PAGE = "https://github.com/exemplu-inventat/program-inventat/releases/tag/v9.9.9"
# Notele lansării vin de pe internet: un <script> sau o etichetă HTML din ele trebuie să rămână text, nu cod.
HOSTILE_NOTES = "Prima schimbare inventată <script>window.__notite = 1</script>\n<b>nu e îngroșat</b>\n- a treia linie"
QUIET_MS = 2500  # cât se așteaptă ca să se vadă că pagina NU mai întreabă (mai mult decât intervalele de interogare)
MIN_TARGET_PX = 40
APPLY_PATH = "/api/update/apply"
BAND_VISIBLE_JS = "() => !document.getElementById('update').hidden"


def new_version(**overrides) -> dict:
    """Răspunsul GET /api/update pentru o versiune nouă inventată, cu notele date."""
    options = {"latest": NEW_VERSION, "notes": HOSTILE_NOTES, "page_url": RELEASE_PAGE, "message": f"Versiune nouă: {NEW_VERSION} (ai {FAKE_CURRENT_VERSION})."}
    options.update(overrides)
    return update_state("noua", **options)


def apply_requests(fake) -> list:
    """Cererile POST /api/update/apply primite de serverul fals."""
    return [r for r in fake.api_requests() if r["method"] == "POST" and r["path"] == APPLY_PATH]


def count_requests(fake, path: str) -> int:
    """Câte cereri a primit serverul fals pe calea dată."""
    return len([r for r in fake.api_requests() if r["path"] == path])


def only_expected_http_errors(probe, status: int) -> dict:
    """Problemele sondei, fără mesajul de consolă al browserului pentru un răspuns de eroare cerut de test (ex. 409)."""
    probe.console[:] = [line for line in probe.console if f"status of {status}" not in line]
    return probe_problems(probe)


# ---------- versiunea și verificarea ----------

def test_up_to_date_shows_the_version_line_and_no_band(open_page, fake):
    """La zi: sub titlu „Versiunea X · E ultima versiune.”, fără bandă și fără buton de actualizare; consola curată."""
    page, probe = open_page()
    wait_js(page, "document.getElementById('update-check').textContent === 'E ultima versiune.'")
    assert page.inner_text("#app-version") == f"Versiunea {fake.version}"
    assert page.locator("#update").is_hidden() and page.locator("#btn-update").is_hidden()
    assert probe_problems(probe) == {}


def test_while_checking_the_page_asks_again_until_the_answer_then_stops(open_page, fake):
    """Verificarea în lucru: „Verific dacă există o versiune nouă…”; pagina întreabă din nou până la răspuns, apoi se oprește."""
    fake.set_update(update_state("verific", latest=None, message="Verific…"))
    page, probe = open_page()
    wait_js(page, "document.getElementById('update-check').textContent.startsWith('Verific dacă există')")
    fake.set_update(update_state("la-zi"))
    wait_js(page, "document.getElementById('update-check').textContent === 'E ultima versiune.'", timeout=8000)
    asked = count_requests(fake, "/api/update")
    page.wait_for_timeout(QUIET_MS)
    assert count_requests(fake, "/api/update") == asked, "pagina întreabă în continuare, deși verificarea s-a terminat"
    assert probe_problems(probe) == {}


def test_a_check_error_shows_its_message_and_a_link_to_the_releases_page(open_page, fake):
    """Verificarea a eșuat: mesajul aplicației și linkul „pagina lansărilor” (filă nouă, fără referrer), sub titlu."""
    fake.set_update(update_state("eroare", latest=None, message="Nu am putut ajunge la pagina lansărilor (inventat).",
                                 page_url="https://github.com/exemplu-inventat/program-inventat/releases/latest"))
    page, probe = open_page()
    wait_js(page, "document.getElementById('update-check').textContent.includes('Nu am putut ajunge')")
    link = page.locator("#update-check a")
    assert link.get_attribute("href") == "https://github.com/exemplu-inventat/program-inventat/releases/latest"
    assert link.get_attribute("target") == "_blank" and {"noopener", "noreferrer"} <= set(link.get_attribute("rel").split())
    assert page.locator("#update").is_hidden()
    assert probe_problems(probe) == {}


# ---------- banda „Versiune nouă” ----------

def test_the_band_appears_for_a_new_version_and_the_notes_stay_plain_text(open_page, fake):
    """La „noua”: „Versiune nouă: X (ai Y)”, „Ce e nou” pliat; notele cu <script> și <b> apar ca text (nimic nu rulează), pe rânduri."""
    fake.set_update(new_version())
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    assert page.inner_text("#update-t") == f"Versiune nouă: {NEW_VERSION} (ai {FAKE_CURRENT_VERSION})"
    assert page.inner_text("#btn-update") == "Actualizează acum" and page.get_attribute("#btn-update", "aria-disabled") is None
    assert page.locator("#update-notes-box").get_attribute("open") is None, "„Ce e nou” trebuie să pornească pliat"
    page.click("#update-notes-box summary")
    assert page.evaluate("document.getElementById('update-notes').textContent") == HOSTILE_NOTES
    assert page.evaluate("document.querySelectorAll('#update script, #update b').length") == 0, "notele au ajuns în pagină ca HTML"
    assert page.evaluate("window.__notite") is None, "un <script> din notele lansării a rulat"
    assert page.evaluate("getComputedStyle(document.getElementById('update-notes')).whiteSpace") == "pre-line"
    lines = page.evaluate("(() => { const e = document.getElementById('update-notes'); return e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight); })()")
    assert lines >= 2.5, f"rândurile din note nu s-au păstrat (înălțime de {lines:.1f} rânduri)"
    capture(page, "banda_versiune_noua")
    assert probe_problems(probe) == {}


def test_update_now_goes_through_the_states_and_ends_on_the_installed_screen(open_page, fake):
    """„Actualizează acum”: o cerere POST cu cheia și JSON; butonul și „Pornește analiza” se dezactivează; stările apar în bandă; la „gata”,
    ecranul „Versiunea nouă e instalată” (repornire într-o filă nouă), iar pagina nu mai întreabă nimic."""
    fake.set_update(new_version())
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    page.click("#btn-update")
    wait_js(page, "document.getElementById('update-status').textContent.includes('Descarc versiunea')")
    (sent,) = apply_requests(fake)
    assert sent["headers"]["content-type"] == "application/json" and sent["headers"]["x-app-token"] == fake.token
    assert page.get_attribute("#btn-update", "aria-disabled") == "true" and page.get_attribute("#btn-update", "aria-busy") == "true"
    assert page.inner_text("#btn-update") == "Se actualizează…"
    assert page.get_attribute("#btn-start", "aria-disabled") == "true" and page.get_attribute("#btn-demo", "aria-disabled") == "true"

    runs_before = count_requests(fake, "/api/runs")
    page.click("#btn-start", force=True)  # aria-disabled: Playwright n-ar apăsa fără force, dar un om poate
    page.click("#btn-update", force=True)
    wait_js(page, "document.getElementById('app-live').textContent.includes('Se instalează o versiune nouă')")
    assert not [r for r in fake.api_requests() if r["method"] == "POST" and r["path"] == "/api/runs"] and len(apply_requests(fake)) == 1, \
        "cât lucrează actualizarea, nici analiza, nici o a doua actualizare nu au voie să pornească"
    assert count_requests(fake, "/api/runs") == runs_before

    for state, message in (("verific", "Verific amprenta arhivei descărcate…"), ("instalez", f"Instalez versiunea {NEW_VERSION}… Nu închide fereastra programului.")):
        fake.set_update(new_version(apply_state=state, apply_message=message, to_version=NEW_VERSION))
        wait_js(page, "(m) => document.getElementById('update-status').textContent === m", message)
    fake.set_update(new_version(apply_state="gata", apply_message="Gata (inventat).", to_version=NEW_VERSION))
    wait_screen(page, "closed-updated")
    assert page.inner_text("#updated-t") == "Versiunea nouă e instalată"
    assert "filă nouă" in page.inner_text("#screen-closed-updated .lead") and "se poate închide" in page.inner_text("#screen-closed-updated .lead")
    assert page.locator("#update").is_hidden()
    capture(page, "ecran_versiune_instalata")
    asked = len(fake.api_requests())
    page.wait_for_timeout(QUIET_MS)
    assert len(fake.api_requests()) == asked, "după „gata”, aplicația se oprește: pagina nu mai are voie să întrebe (ar arăta „s-a oprit”)"
    assert probe_problems(probe) == {}


@pytest.mark.parametrize("page_url, linked", [
    (RELEASE_PAGE, True),
    ("https://evil.example/releases", False),
    ("http://github.com/exemplu-inventat/program-inventat/releases", False),
    ("https://github.com.evil.example/releases", False),
    ("https://github.com@exemplu.invalid/releases", False),  # „github.com” e doar numele de utilizator; gazda e alta
    ("javascript:alert(1)", False),
    (None, False),
])
def test_a_failed_update_shows_the_message_and_links_only_to_github(open_page, fake, page_url, linked):
    """Eroare la aplicare: mesajul aplicației (roșu), „Încearcă din nou” activ și linkul spre pagina lansărilor doar pentru https://github.com/..."""
    fake.set_update(new_version(page_url=page_url, apply_state="eroare", apply_message="Amprenta arhivei nu se potrivește (inventat); am șters-o."))
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    status = page.locator("#update-status")
    assert status.inner_text() == "Amprenta arhivei nu se potrivește (inventat); am șters-o." and "is-bad" in status.get_attribute("class")
    assert page.inner_text("#btn-update") == "Încearcă din nou" and page.get_attribute("#btn-update", "aria-disabled") is None
    links = page.locator("#update a")
    if linked:
        assert links.count() == 1 and links.get_attribute("href") == RELEASE_PAGE
        assert links.get_attribute("target") == "_blank" and {"noopener", "noreferrer"} <= set(links.get_attribute("rel").split())
        assert page.locator("#update-link").is_visible()
    else:
        assert links.count() == 0, f"link spre o adresă nepermisă: {page_url!r}"
        assert page.locator("#update-link").is_hidden()
    assert probe_problems(probe) == {}


def test_the_button_is_disabled_while_an_analysis_runs(open_page, fake):
    """Cât rulează o analiză: banda rămâne, „Actualizează acum” e dezactivat cu explicația lângă el; un clic nu trimite nimic."""
    fake.set_update(new_version())
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    fake.set_state(state="fetching_orders", run_id="2026-10-05_12-00-01", started_at="2026-10-05T12:00:01",
                   progress={"phase": "fetching_orders", "done": 3, "total": 10})
    wait_screen(page, "working")
    wait_js(page, "document.getElementById('btn-update').getAttribute('aria-disabled') === 'true'")
    assert page.locator("#update-run-hint").is_visible() and page.locator("#update").is_visible()
    page.click("#btn-update", force=True)  # aria-disabled: Playwright n-ar apăsa fără force, dar un om poate
    wait_js(page, "document.getElementById('app-live').textContent.includes('după ce se termină analiza')")
    assert apply_requests(fake) == []
    fake.set_state(state="done", run_id="2026-10-05_12-00-01")
    wait_js(page, "document.getElementById('btn-update').getAttribute('aria-disabled') === null")
    assert page.locator("#update-run-hint").is_hidden()
    assert probe_problems(probe) == {}


def test_a_refused_update_shows_the_reason_and_the_button_works_again(open_page, fake):
    """Aplicația refuză (409, ex. copie git): mesajul ei apare în bandă, iar butonul rămâne folosibil."""
    fake.set_update(new_version())
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    fake.fail_next[("POST", APPLY_PATH)] = (409, "git_checkout", "Folderul ăsta e o copie git: actualizează cu git pull.")
    page.click("#btn-update")
    wait_js(page, "document.getElementById('update-status').textContent.includes('copie git')")
    assert "is-bad" in page.get_attribute("#update-status", "class")
    assert page.get_attribute("#btn-update", "aria-disabled") is None and page.inner_text("#btn-update") == "Actualizează acum"
    assert page.get_attribute("#btn-start", "aria-disabled") is None, "un refuz nu are voie să lase „Pornește analiza” dezactivat"
    assert only_expected_http_errors(probe, 409) == {}


# ---------- tastatură, temă, ecran îngust ----------

def test_the_band_works_from_the_keyboard(open_page, fake):
    """Din „Pornește analiza” (focusul inițial), Shift+Tab ajunge la „Actualizează acum”, apoi la „Ce e nou”; Enter le folosește pe amândouă."""
    fake.set_update(new_version())
    page, probe = open_page()
    wait_js(page, BAND_VISIBLE_JS)
    page.focus("#btn-start")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.id") == "btn-update"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.tagName") == "SUMMARY"
    page.keyboard.press("Enter")
    assert page.locator("#update-notes-box").get_attribute("open") is not None
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    wait_js(page, "document.getElementById('update-status').textContent.includes('Descarc')")
    assert len(apply_requests(fake)) == 1
    assert probe_problems(probe) == {}


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_band_follows_the_theme_fits_390px_and_keeps_contrast(open_page, fake, scheme):
    """Tema luminoasă și cea întunecată: banda are fondul de card al temei, contrastul textelor trece, nimic nu iese din ecran la 390 px."""
    long_word = "cuvânt" * 40
    fake.set_update(new_version(notes=f"{long_word}\n- încă o linie inventată", apply_state="eroare", apply_message=f"Eroare inventată {long_word}."))
    page, probe = open_page(width=390, height=844, scheme=scheme)
    wait_js(page, BAND_VISIBLE_JS)
    page.click("#update-notes-box summary")
    card = parse_token_blocks(CSS_TEXT)["dark" if scheme == "dark" else "light"]["--card"].lstrip("#")
    expected = "rgb({}, {}, {})".format(*(int(card[i:i + 2], 16) for i in (0, 2, 4)))
    assert page.evaluate("getComputedStyle(document.getElementById('update')).backgroundColor") == expected
    overflow = page.evaluate(OVERFLOW_JS)
    assert overflow["scrollWidth"] <= overflow["clientWidth"] and overflow["outside"] == [], f"scroll orizontal la 390 px: {overflow}"
    low = [item for item in page.evaluate(CONTRAST_SCAN_JS)]
    assert low == [], f"contrast prea mic ({scheme}): {low}"
    small = [t for t in page.evaluate(TAP_TARGET_JS, MIN_TARGET_PX) if t["id"] in ("btn-update", "Ce e nou")]
    assert small == [], f"controale ale benzii mai mici de {MIN_TARGET_PX} px: {small}"
    capture(page, f"banda_390_{scheme}")
    assert probe_problems(probe) == {}
