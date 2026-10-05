"""Linkurile către comenzile și retururile de pe eMAG din raport: validare strictă, atribute de siguranță, vizibilitate, ținte, teme.

Primește: componenta dashboard (fișierele din interfata/assets/) deschisă din file:// în Edge sau Chrome (Playwright), cu date
INVENTATE (tests/dashboard_samples.py) și cu datele demonstrative reale ale site-ului. Verifică: paritatea constantelor Python <-> JS,
că doar numere de 3–15 cifre devin link, că fiecare link are target/rel/referrerpolicy/aria-label, că e vizibil fără hover, că are cel
puțin 24 x 24 px, focus vizibil, contrast, că un clic deschide eMAG în filă nouă fără legătură cu raportul, și că nimic ostil nu devine link.
Dacă niciun browser nu pornește, testele de browser se sar; cele statice rulează oricum.
"""

import re

import pytest

from emag_spend import order_links, settings
from emag_spend.report_html import write_report
from tests import dashboard_samples as samples
from tests.dashboard_browser_support import attach_probe, read_demo_file_data
from tests.test_dashboard_browser import assert_clean, browser, data, mount, open_page, settle  # noqa: F401

ORDER_HREF = re.compile(r"https://www\.emag\.ro/history/shoppingdetails/[0-9]{3,15}")
RETURN_HREF = re.compile(r"https://www\.emag\.ro/user/return-history/[0-9]{1,15}/[0-9]{3,15}")
MIN_TARGET_PX = 24  # WCAG 2.5.8 (AA): zona de atingere a unui link izolat
BLOCK_PAGE_ROWS = 100  # câte rânduri desenează tabelele lungi o dată (ROWS_PAGE din dashboard.js)
DASHBOARD_JS = settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8")

LINK_INFO = """() => [...document.querySelectorAll('#a a.ed-olink')].map((a) => {
  const box = a.getBoundingClientRect(), style = getComputedStyle(a), arrow = a.lastElementChild;
  return { href: a.getAttribute('href'), target: a.getAttribute('target'), rel: a.getAttribute('rel'), policy: a.getAttribute('referrerpolicy'),
           label: a.getAttribute('aria-label'), text: a.firstElementChild.textContent, arrow: arrow.textContent, arrowHidden: arrow.getAttribute('aria-hidden'),
           width: box.width, height: box.height, underline: style.textDecorationLine, visibility: style.visibility, opacity: style.opacity,
           inBlock: a.closest('[data-ed-block]').dataset.edBlock };
})"""


@pytest.fixture(scope="module")
def ui_data():
    """Seturile de date ale acestui fișier: inventate (extras, vechi, linkuri ostile) și cele reale ale site-ului (fișier)."""
    sets = {"extras": samples.extras_summary(), "legacy": samples.legacy_summary(), "links": samples.hostile_links_summary()}
    demo_file = read_demo_file_data()
    if demo_file is not None:
        sets["file"] = samples.without_demo_flag(demo_file)
    return sets


def open_with(open_page, ui_data, dataset, **options):
    """Deschide pagina cu seturile din acest fișier și montează `dataset` în #a."""
    page, probe = open_page(extra_data=ui_data, **options)
    result = mount(page, dataset, options="{}")
    settle(page)
    return page, probe, result


def open_every_group(page):
    """Deschide toate grupele de avertismente (details) din raport."""
    page.evaluate("document.querySelectorAll('#a .ed-wg').forEach((d) => { d.open = true; })")


# ---------- paritate Python <-> JS (fără browser) ----------

def test_javascript_repeats_the_python_constants_exactly():
    """dashboard.js are aceleași prefixe și același tipar de număr ca emag_spend/order_links.py: o singură sursă de adevăr, cu paritate verificată."""
    js_prefix = re.search(r"const ORDER_URL_PREFIX = '([^']+)';", DASHBOARD_JS).group(1)
    js_pattern = re.search(r"const ORDER_ID_PATTERN = '([^']+)';", DASHBOARD_JS).group(1)
    js_return_prefix = re.search(r"const RETURN_URL_PREFIX = '([^']+)';", DASHBOARD_JS).group(1)
    assert js_prefix == order_links.ORDER_URL_PREFIX == settings.BASE_URL + settings.ORDER_DETAIL_PATH.format(order_id="")
    assert js_pattern == order_links.ORDER_ID_PATTERN
    assert js_return_prefix == settings.BASE_URL + settings.RETURN_LIST_PATH + "/"


def test_javascript_builds_links_only_through_the_validated_helpers():
    """Adresele comenzilor se construiesc într-un singur loc (orderUrl), cu validarea strictă dinainte; nu există alt `shoppingdetails` în cod."""
    assert DASHBOARD_JS.count("shoppingdetails") == 1
    assert DASHBOARD_JS.count("return-history") == 1
    assert "const ORDER_ID_RE = new RegExp('^' + ORDER_ID_PATTERN + '$');" in DASHBOARD_JS
    for needed in ("target: '_blank'", "rel: 'noopener noreferrer'", "referrerpolicy: 'no-referrer'"):
        assert needed in DASHBOARD_JS, needed


# ---------- linkurile din datele demonstrative reale ----------

def test_every_order_number_in_the_real_demo_data_is_a_safe_visible_link_of_the_right_size(open_page, ui_data):
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    page, probe, result = open_with(open_page, ui_data, "file")
    assert result["ok"] is True
    open_every_group(page)
    page.click("#a .ed-ph-open >> nth=0")
    links = page.evaluate(LINK_INFO)
    assert len(links) > 20
    for link in links:
        assert ORDER_HREF.fullmatch(link["href"]) or RETURN_HREF.fullmatch(link["href"]), link["href"]
        assert link["target"] == "_blank" and set(link["rel"].split()) == {"noopener", "noreferrer"} and link["policy"] == "no-referrer", link
        assert link["arrow"] == "↗" and link["arrowHidden"] == "true"
        assert link["underline"] == "underline" and link["visibility"] == "visible" and link["opacity"] == "1", link  # vizibil fără hover
        assert link["width"] >= MIN_TARGET_PX and link["height"] >= MIN_TARGET_PX, link
        number = link["href"].rsplit("/", 1)[1]
        assert link["text"] in (number, f"retur {number}") and number in link["label"]
        assert link["label"] == (f"Deschide comanda {number} pe eMAG (filă nouă)" if ORDER_HREF.fullmatch(link["href"])
                                 else f"Deschide returul {number} pe eMAG (filă nouă)")
    assert_clean(probe)


def test_each_table_that_lists_orders_links_each_row(open_page, ui_data):
    """Achiziții mari, categorii evidențiate, „Rămase în afara calculului” și istoricul de prețuri: un link pe fiecare număr de comandă afișat."""
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    file_data = ui_data["file"]
    page, _, _ = open_with(open_page, ui_data, "file")
    per_block = {}
    for link in page.evaluate(LINK_INFO):
        per_block[link["inBlock"]] = per_block.get(link["inBlock"], 0) + 1
    assert per_block["big"] == min(len(file_data["big"]["items"]), BLOCK_PAGE_ROWS)
    assert per_block["excluded"] == len(file_data["paid_only"]) + len(file_data["in_progress"])
    assert per_block["highlights"] == sum(min(len(b["items"]), BLOCK_PAGE_ROWS) for b in file_data["highlights"].values())
    assert "preturi" not in per_block, "istoricul e închis: nicio comandă nu e afișată încă"
    page.click("#a .ed-ph-open >> nth=0")
    first = file_data["price_history"]["products"][0]
    assert page.locator("#a [data-ed-block='preturi'] a.ed-olink").count() == len(first["purchases"])


def test_warning_groups_link_every_order_and_only_valid_returns(open_page, ui_data):
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    groups = ui_data["file"]["warnings_detail"]
    page, _, _ = open_with(open_page, ui_data, "file")
    open_every_group(page)
    expected_orders = sum(len(item["order_ids"]) for g in groups for item in g["items"])
    expected_returns = sum(1 for g in groups for item in g["items"] if item.get("return_url"))
    hrefs = page.eval_on_selector_all("#a .ed-wg a.ed-olink", "els => els.map((a) => a.getAttribute('href'))")
    assert sum(1 for h in hrefs if ORDER_HREF.fullmatch(h)) == expected_orders
    assert sum(1 for h in hrefs if RETURN_HREF.fullmatch(h)) == expected_returns
    assert expected_orders > 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_links_are_visible_big_enough_and_the_page_stays_clean_in_both_themes_and_widths(open_page, ui_data, scheme, width):
    page, probe, _ = open_with(open_page, ui_data, "extras", width=width, scheme=scheme, html_attrs=f'data-theme="{scheme}"')
    open_every_group(page)
    page.click("#a .ed-ph-open >> nth=0")
    links = page.evaluate(LINK_INFO)
    assert {"control", "preturi"} <= {link["inBlock"] for link in links}
    assert all(l["width"] >= MIN_TARGET_PX and l["height"] >= MIN_TARGET_PX and l["underline"] == "underline" for l in links)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    colors = page.evaluate("[...document.querySelectorAll('#a a.ed-olink')].map((a) => getComputedStyle(a).color)")
    expected = {"light": "rgb(11, 87, 168)", "dark": "rgb(125, 180, 245)"}[scheme]
    assert set(colors) == {expected}
    assert_clean(probe)


def test_link_has_a_visible_focus_ring_when_reached_by_keyboard(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    open_every_group(page)
    for _ in range(400):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('ed-olink')"):
            break
    else:
        pytest.fail("Tab nu a ajuns la niciun link")
    ring = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, parseFloat(s.outlineWidth)]; })()")
    assert ring[0] != "none" and ring[1] >= 2


def test_clicking_a_link_opens_emag_in_a_new_tab_that_cannot_reach_back_and_gets_no_referrer(open_page):
    page, _ = open_page()
    mount(page, "demo", options="{}")
    settle(page)
    seen = []

    def stub(route):
        """Nicio cerere nu iese de pe calculator în test: eMAG e înlocuit cu o pagină goală, iar antetele se rețin."""
        seen.append(route.request.headers)
        route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>stub</title>")

    page.context.route("https://www.emag.ro/**", stub)
    first_url = page.url
    with page.context.expect_page() as opened:
        page.click("#a [data-ed-block='big'] a.ed-olink >> nth=0")
    popup = opened.value
    popup.wait_for_load_state()
    assert ORDER_HREF.fullmatch(popup.url)
    assert popup.evaluate("window.opener") is None
    assert page.url == first_url, "raportul nu navighează: linkul se deschide în filă nouă"
    assert all("referer" not in headers for headers in seen), seen


# ---------- nimic ostil nu devine link ----------

def test_hostile_numbers_and_return_addresses_never_become_links(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "links")
    assert result["ok"] is True
    open_every_group(page)
    page.click("#a .ed-ph-open >> nth=0")
    hrefs = page.eval_on_selector_all("#a a", "els => els.map((a) => a.getAttribute('href'))")
    leaked = [h for h in hrefs if h and not (ORDER_HREF.fullmatch(h) or RETURN_HREF.fullmatch(h))]
    assert leaked == []
    # numerele ostile rămân text (tăiat), fără link; nu apare niciun link de retur din adresele greșite
    group = page.locator("#a .ed-wg", has_text="Retururi cerute")
    assert group.locator("a.ed-olink").count() == 0
    assert "javascript:alert(1)" in group.inner_text()
    detail = page.locator("#a .ed-ph-detail")
    assert detail.locator("a.ed-olink").count() == 0, "toate cele nouă numere din istoric sunt nevalide"
    assert page.evaluate("window.__pwned === undefined")
    assert_clean(probe)


def test_return_link_needs_the_exact_address_with_the_number_of_that_row(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    open_every_group(page)
    returns = page.eval_on_selector_all("#a .ed-wg a[href*='return-history']", "els => els.map((a) => [a.getAttribute('href'), a.textContent])")
    assert returns == [["https://www.emag.ro/user/return-history/1/3000001", "retur 3000001↗"]]


def test_hostile_dataset_with_long_numbers_stays_inside_the_screen(open_page):
    page, probe = open_page(width=390, height=900)
    mount(page, "hostile", options="{}")
    settle(page)
    page.evaluate("document.querySelectorAll('#a .ed-wg').forEach((d) => { d.open = true; })")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("window.__pwned === undefined")
    assert_clean(probe)


def test_old_analysis_without_the_new_keys_still_links_the_order_numbers_it_has(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "legacy")
    assert result["ok"] is True
    assert page.locator("#a [data-ed-block='preturi']").count() == 0
    assert page.locator("#a .ed-wg").count() == 0
    assert_clean(probe)


# ---------- contrast (fără browser) ----------

def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_link_color_has_text_contrast_on_every_background_it_meets_in_both_themes():
    """--ed-link are cel puțin 4,5:1 pe pagină, pe suprafață și pe fundalul de hover, în ambele teme."""
    from tests.test_dashboard_static_rules import DARK_AUTO_TOKENS, DARK_FORCED_TOKENS, LIGHT_TOKENS, _blend_over
    assert DARK_AUTO_TOKENS["--ed-link"] == DARK_FORCED_TOKENS["--ed-link"]
    for name, tokens in (("lumină", LIGHT_TOKENS), ("întuneric", {**LIGHT_TOKENS, **DARK_AUTO_TOKENS})):
        for ground in ("--ed-page", "--ed-surface"):
            assert _contrast(tokens["--ed-link"].strip(), tokens[ground].strip()) >= 4.5, f"{name}: link pe {ground}"
            hovered = _blend_over(tokens["--ed-ghost-2"].strip(), tokens[ground].strip())
            assert _contrast(tokens["--ed-link"].strip(), hovered) >= 4.5, f"{name}: link la hover pe {ground}"


# ---------- raportul generat de Python (un singur fișier, din file://) ----------

def test_generated_report_file_has_the_links_the_price_block_and_the_warning_groups(browser, tmp_path):
    """Raportul scris de write_report (șablon + CSS + JS + date, într-un singur fișier) arată linkurile, prețurile și avertismentele pe grupe, în ambele teme."""
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, samples.extras_summary())
    for scheme in ("light", "dark"):
        context = browser.new_context(viewport={"width": 390, "height": 900}, color_scheme=scheme)
        try:
            page = context.new_page()
            probe = attach_probe(page)
            page.goto(out.as_uri())
            page.wait_for_selector("#raport [data-ed-block='preturi']")
            page.evaluate("document.querySelectorAll('#raport .ed-wg').forEach((d) => { d.open = true; })")
            hrefs = page.eval_on_selector_all("#raport a.ed-olink", "els => els.map((a) => a.getAttribute('href'))")
            assert hrefs and all(ORDER_HREF.fullmatch(h) or RETURN_HREF.fullmatch(h) for h in hrefs), hrefs
            assert page.locator("#raport .ed-wg").count() == 4
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not any(probe.problems().values()), probe.problems()
        finally:
            context.close()


# ---------- date de demonstrație: numerele de comandă sunt inventate, deci rămân text simplu ----------

ANY_EMAG_LINK = "document.querySelectorAll('%s a[href*=\"shoppingdetails\"], %s a[href*=\"return-history\"]').length"


def test_demo_marker_in_the_data_turns_every_order_number_into_plain_text(open_page):
    """Cu `meta.demo` (cum scrie programul la --demo) numerele de comandă rămân vizibile, dar nu sunt link: pe eMAG nu există și te-ar trimite la lista de comenzi."""
    page, probe = open_page(extra_data={"flagged": samples.flagged_demo_summary()})
    mount(page, "flagged", options="{}")  # fără opțiunea `demo` a gazdei: marcajul vine doar din date
    settle(page)
    assert page.evaluate(ANY_EMAG_LINK % ("#a", "#a")) == 0
    assert page.locator("#a .ed-banner").count() == 1, "raportul de demonstrație trebuie să spună că datele sunt inventate"
    assert page.locator("#a .ed-orderline").count() > 0, "numerele de comandă rămân vizibile, ca text"
    assert_clean(probe)


def test_host_demo_option_also_turns_order_numbers_into_plain_text(open_page, ui_data):
    """Opțiunea `demo` a gazdei (site-ul o dă ferestrei demonstrative) are același efect, chiar dacă datele n-au marcaj."""
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    page, probe = open_page(extra_data=ui_data)
    mount(page, "file", options="{ demo: true }")
    settle(page)
    assert page.evaluate(ANY_EMAG_LINK % ("#a", "#a")) == 0
    assert page.locator("#a .ed-orderline").count() > 0
    assert_clean(probe)


def test_data_without_the_demo_marker_keeps_its_order_links(open_page, ui_data):
    """Un cont real (fără marcaj, fără opțiune) are linkuri la numerele de comandă: garda de mai sus nu le stinge pe ale lui."""
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    page, probe, _ = open_with(open_page, ui_data, "file")
    assert page.evaluate(ANY_EMAG_LINK % ("#a", "#a")) > 0
    assert page.locator("#a .ed-banner").count() == 0
    assert_clean(probe)


def test_generated_demo_report_file_has_the_banner_and_no_order_links(browser, tmp_path):
    """Raportul scris la `--demo` (un singur fișier) spune că datele sunt inventate și nu face linkuri spre comenzi care nu există."""
    out = tmp_path / "raport.html"
    write_report(out, settings.REPORT_TEMPLATE_FILE, samples.flagged_demo_summary())
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        probe = attach_probe(page)
        page.goto(out.as_uri())
        settle(page)
        assert page.locator("#raport .ed-banner").count() == 1
        assert page.evaluate(ANY_EMAG_LINK % ("#raport", "#raport")) == 0
        assert page.locator("#raport .ed-orderline").count() > 0
        assert not any(probe.problems().values()), probe.problems()
    finally:
        context.close()
