"""Numele produselor ca linkuri spre comandă și cifra mare în bani plătiți, în componenta raportului (browser real).

Primește: componenta dashboard deschisă din file:// în Edge sau Chrome (Playwright), cu date INVENTATE (tests/dashboard_samples.py:
datele demonstrative fără marcaj, deci cu numere de comandă valide). Verifică: în fiecare tabel cu produse numele e un link sigur
(validare strictă, filă nouă, noopener noreferrer, no-referrer, etichetă care spune comanda), la hover și la focus de tastatură se
face albastru (--ed-link) și subliniat, cursor de link, zonă de cel puțin 24 px; rândurile cu mai multe comenzi duc la cea mai
recentă; în date de demonstrație și la numere nevalide numele rămân text; cifra mare și categoriile sunt în bani plătiți, iar un
analiza.json vechi, fără `paid`, se desenează ca înainte. Dacă niciun browser nu pornește, testele de browser se sar.
"""

import re

import pytest

from tests import dashboard_samples as samples
from tests.test_dashboard_browser import assert_clean, browser, data, mount, money, open_page, settle  # noqa: F401

ORDER_HREF = re.compile(r"https://www\.emag\.ro/history/shoppingdetails/[0-9]{3,15}")
MIN_TARGET_PX = 24  # WCAG 2.5.8 (AA)
TOUCH_TARGET_PX = 40  # --ed-target, pe ecran tactil
LINK_RGB = {"light": "rgb(11, 87, 168)", "dark": "rgb(125, 180, 245)"}  # --ed-link în cele două teme
NBSP = chr(0xA0)
MAX_TAB_PRESSES = 400

PRODUCT_LINKS = """() => [...document.querySelectorAll('#a a.ed-plink')].map((a) => { const box = a.getBoundingClientRect(), s = getComputedStyle(a);
  return { href: a.getAttribute('href'), target: a.getAttribute('target'), rel: a.getAttribute('rel'), policy: a.getAttribute('referrerpolicy'),
           label: a.getAttribute('aria-label'), text: a.textContent, height: box.height, cursor: s.cursor,
           block: a.closest('[data-ed-block]').dataset.edBlock }; })"""
LOOK = "(a) => { const s = getComputedStyle(a); return [s.color, s.textDecorationLine]; }"


def sound(text):
    """Textul fără spații nedespărțitoare, ca asertările să nu depindă de ele."""
    return text.replace(NBSP, " ")


def open_demo(open_page, **options):
    """Pagina cu datele demonstrative ca ale unui cont real (fără marcajul demo), montate în #a și cu istoricul primului produs deschis."""
    page, probe = open_page(**options)
    assert mount(page, "demo", options="{}")["ok"] is True
    settle(page)
    return page, probe


# ---------- linkurile ----------

def test_every_table_with_products_links_each_name_to_its_order_safely(open_page, data):
    page, probe = open_demo(open_page)
    page.click("#a .ed-ph-open >> nth=0")  # istoricul primului produs: numele din fiecare comandă
    page.evaluate("document.querySelectorAll('#a details').forEach((d) => { d.open = true; })")  # produsele necategorizate
    links = page.evaluate(PRODUCT_LINKS)
    per_block = {}
    for link in links:
        per_block[link["block"]] = per_block.get(link["block"], 0) + 1
        assert ORDER_HREF.fullmatch(link["href"]), link["href"]
        assert link["target"] == "_blank" and set(link["rel"].split()) == {"noopener", "noreferrer"} and link["policy"] == "no-referrer", link
        number = link["href"].rsplit("/", 1)[1]
        assert link["label"].startswith(link["text"] + ": Deschide comanda " + number + " pe eMAG"), link["label"]
        assert link["label"].endswith(", în filă nouă")
        assert link["cursor"] == "pointer" and link["height"] >= MIN_TARGET_PX, link
    demo = data["demo"]
    assert per_block["top"] == len(demo["top_products"])
    assert per_block["big"] == min(len(demo["big"]["items"]), 100)
    assert per_block["highlights"] == sum(min(len(b["items"]), 100) for b in demo["highlights"].values())
    assert per_block["excluded"] == sum(len(b["names"]) for b in demo["paid_only"] + demo["in_progress"])
    first = demo["price_history"]["products"][0]
    assert per_block["preturi"] == min(len(demo["price_history"]["products"]), 25) + len(first["purchases"])
    assert per_block["control"] == len(demo["uncategorized"])
    assert_clean(probe)


def test_a_row_that_gathers_several_orders_opens_the_most_recent_and_says_which(open_page, data):
    page, _ = open_demo(open_page)
    several = [p for p in data["demo"]["top_products"] if p["order_count"] > 1]
    assert several, "datele demonstrative trebuie să aibă un produs păstrat din mai multe comenzi"
    labels = page.eval_on_selector_all("#a [data-ed-block='top'] a.ed-plink", "els => els.map((a) => [a.getAttribute('href'), a.getAttribute('aria-label')])")
    by_order = dict(labels)
    for product in several:
        label = by_order["https://www.emag.ro/history/shoppingdetails/" + product["order_id"]]
        assert f"Deschide comanda {product['order_id']} pe eMAG (cea mai recentă din {product['order_count']})" in label


def test_the_price_table_keeps_a_separate_button_for_the_history(open_page, data):
    page, _ = open_demo(open_page)
    row = page.locator("#a .ed-tbl-prices tbody tr").first
    product = data["demo"]["price_history"]["products"][0]
    newest = product["purchases"][-1]["order_id"]
    assert row.locator("a.ed-plink").get_attribute("href").endswith("/" + newest)
    button = row.locator("button.ed-ph-open")
    assert button.locator(".ed-sr").inner_text() == "Arată istoricul prețurilor: " + product["name"]
    assert button.bounding_box()["height"] >= TOUCH_TARGET_PX and button.bounding_box()["width"] >= TOUCH_TARGET_PX


# ---------- aspectul: albastru la hover și la focus ----------

@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_product_name_turns_the_link_blue_and_underlined_on_hover_and_on_keyboard_focus(open_page, scheme):
    page, probe = open_demo(open_page, scheme=scheme, html_attrs=f'data-theme="{scheme}"')
    link = page.locator("#a [data-ed-block='top'] a.ed-plink").first
    link.scroll_into_view_if_needed()
    settle(page)
    page.mouse.move(1, 1)
    rest = link.evaluate(LOOK)
    assert rest[0] != LINK_RGB[scheme] and rest[1] == "none", "în repaus numele arată ca textul din jur"
    link.hover()
    assert link.evaluate(LOOK) == [LINK_RGB[scheme], "underline"]
    page.mouse.move(1, 1)
    for _ in range(MAX_TAB_PRESSES):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('ed-plink')"):
            break
    else:
        pytest.fail("Tab nu a ajuns la niciun nume de produs")
    focused = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [s.color, s.textDecorationLine, s.outlineStyle, parseFloat(s.outlineWidth)]; })()")
    assert focused[:2] == [LINK_RGB[scheme], "underline"] and focused[2] != "none" and focused[3] >= 2
    assert_clean(probe)


def test_on_a_touch_screen_names_show_a_discreet_underline_and_a_comfortable_target(open_page):
    page, probe = open_demo(open_page, width=390, height=844, touch=True)
    looks = page.eval_on_selector_all("#a [data-ed-block='top'] a.ed-plink", "els => els.map((a) => [getComputedStyle(a).textDecorationLine, a.getBoundingClientRect().height])")
    assert looks and all(line == "underline" and height >= TOUCH_TARGET_PX for line, height in looks), looks[:3]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


# ---------- unde numele rămân text ----------

def test_demo_data_keeps_every_product_name_as_plain_text(open_page, data):
    page, probe = open_page(extra_data={"flagged": samples.flagged_demo_summary()})
    mount(page, "flagged", options="{}")  # marcajul vine din date (meta.demo)
    mount(page, "demo", "b", "{ demo: true }")  # sau din opțiunea gazdei
    assert page.locator("#a a.ed-plink, #b a.ed-plink").count() == 0
    first = data["demo"]["top_products"][0]["name"]
    assert first in page.inner_text("#a [data-ed-block='top']") and first in page.inner_text("#b [data-ed-block='top']")
    assert_clean(probe)


def test_an_invalid_order_number_never_turns_a_name_into_a_link(open_page):
    page, probe = open_page(extra_data={"links": samples.hostile_links_summary()})
    assert mount(page, "links", options="{}")["ok"] is True
    page.click("#a .ed-ph-open >> nth=0")
    hrefs = page.eval_on_selector_all("#a a.ed-plink", "els => els.map((a) => a.getAttribute('href'))")
    assert all(ORDER_HREF.fullmatch(h) for h in hrefs), hrefs
    assert page.locator("#a .ed-ph-detail a.ed-plink").count() == 0, "toate cele nouă numere din istoric sunt nevalide"
    assert page.evaluate("window.__pwned === undefined")
    assert_clean(probe)


# ---------- cifra mare și categoriile, în bani plătiți ----------

def test_hero_shows_the_paid_total_and_what_it_is_made_of(open_page, data):
    page, probe = open_demo(open_page)
    paid = data["demo"]["paid"]
    shown = page.inner_text("#a .ed-big") + page.inner_text("#a .ed-cents")
    assert sound(shown) == money(paid["spent_bani"]) + " Lei"
    assert "Banii plătiți efectiv" in page.inner_text("#a .ed-lead")
    parts = [sound(p) for p in page.locator("#a .ed-hero-parts li").all_inner_texts()]
    assert parts[0] == "La preț de listă " + money(paid["list_kept_bani"]) + " Lei"
    assert parts[2] == "transport și taxe +" + money(paid["fees_bani"]) + " Lei"
    assert page.get_attribute("#a [data-ed-block='funnel']", "data-ed-title") == "De la comandat la plătit"
    assert_clean(probe)


def test_category_rows_with_the_rows_that_are_not_products_add_up_to_the_paid_total(open_page, data):
    page, _ = open_demo(open_page)
    paid = data["demo"]["paid"]
    names = page.eval_on_selector_all("#a [data-ed-block='categories'] .ed-bar-row .ed-bar-name", "els => els.map((e) => e.textContent)")
    extra = [r["name"] for r in paid["extra_rows"] if r["bani"]]
    assert names[-len(extra):] == extra and "Transport și taxe" in extra
    page.click("#a [data-ed-block='categories'] .ed-toggle")
    footer = page.locator("#a [data-ed-block='categories'] tfoot td").all_inner_texts()
    assert sound(footer[1]) == money(paid["spent_bani"]) + " Lei"


def test_an_analysis_without_paid_is_drawn_at_list_price_as_before(open_page):
    old = samples.pre_paid_summary()
    page, probe = open_page(extra_data={"old": old})
    assert mount(page, "old", options="{}")["ok"] is True
    settle(page)
    shown = page.inner_text("#a .ed-big") + page.inner_text("#a .ed-cents")
    assert sound(shown) == money(old["funnel"]["kept_bani"]) + " Lei"
    assert "la preț de listă" in page.inner_text("#a .ed-lead") and page.locator("#a .ed-hero-parts").count() == 0
    assert page.get_attribute("#a [data-ed-block='funnel']", "data-ed-title") == "De la comandat la păstrat"
    assert page.locator("#a [data-ed-block='top'] a.ed-plink").count() == 0  # analizele vechi nu au comanda produsului
    assert_clean(probe)


def test_a_file_with_paid_but_rows_without_paid_amounts_is_rejected(open_page):
    page, _ = open_page()
    result = page.evaluate("(() => { const d = JSON.parse(JSON.stringify(DATA.demo)); delete d.by_category[0].paid_kept_bani; return EmagDashboard.validate(d); })()")
    assert result["ok"] is False
    assert any("by_category[0]" in e and "paid_kept_bani" in e for e in result["errors"]), result["errors"]
    broken = page.evaluate("(() => { const d = JSON.parse(JSON.stringify(DATA.demo)); d.paid.spent_bani = '1,00'; return EmagDashboard.validate(d); })()")
    assert broken["ok"] is False and "paid.spent_bani" in broken["errors"][0]


# ---------- contrast (fără browser) ----------

def test_link_color_keeps_text_contrast_on_the_highlighted_table_row_in_both_themes():
    """La hover rândul de tabel primește --ed-ghost peste suprafață; albastrul linkului trebuie să rămână ≥ 4,5:1 și acolo."""
    from tests.test_dashboard_static_rules import DARK_AUTO_TOKENS, LIGHT_TOKENS, _blend_over, _contrast
    for name, tokens in (("lumină", LIGHT_TOKENS), ("întuneric", {**LIGHT_TOKENS, **DARK_AUTO_TOKENS})):
        for ground in ("--ed-page", "--ed-surface"):
            row = _blend_over(tokens["--ed-ghost"].strip(), tokens[ground].strip())
            assert _contrast(tokens["--ed-link"].strip(), row) >= 4.5, f"{name}: link pe rândul evidențiat, peste {ground}"
