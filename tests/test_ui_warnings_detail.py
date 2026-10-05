"""Avertismentele pe grupe din „Cifre de control” (cheia `warnings_detail`): acordeoane accesibile cu comenzile afectate și linkuri eMAG.

Primește: componenta dashboard deschisă din file:// în Edge sau Chrome (Playwright), cu date INVENTATE (tests/dashboard_samples.py)
și cu datele demonstrative reale ale site-ului. Verifică: o grupă = un <details> închis, cu titlu, număr de cazuri și „afectează totalurile:
da/nu”; deschisă arată explicația, „Ce faci” și lista comenzilor; un analiza.json vechi (fără cheie) rămâne cu lista simplă de texte; textele
ostile rămân text; schema (validate) acceptă lipsa cheii și respinge forme greșite; telefon la 390 px; ambele teme; fără erori în consolă.
"""

import pytest

from tests import dashboard_samples as samples
from tests.dashboard_browser_support import read_demo_file_data
from tests.test_dashboard_browser import BLOCKS, assert_clean, blocks, browser, data, mount, open_page, settle  # noqa: F401

NBSP = chr(0xA0)  # spațiul nedespărțitor, generat din cod


def sound(text):
    """Textul fără spații nedespărțitoare, ca asertările să nu depindă de ele."""
    return text.replace(NBSP, " ")


@pytest.fixture(scope="module")
def ui_data():
    """Seturile de date ale acestui fișier: inventate (extras, vechi) și cele reale ale site-ului (fișier)."""
    sets = {"extras": samples.extras_summary(), "legacy": samples.legacy_summary()}
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


def js_validate(page, mutation, dataset="extras"):
    """Aplică `mutation` (cod JS pe `d`) peste o copie a setului de date și întoarce rezultatul validate."""
    return page.evaluate(f"(() => {{ const d = JSON.parse(JSON.stringify(DATA['{dataset}'])); {mutation}; return EmagDashboard.validate(d); }})()")


# ---------- grupele ----------

def test_each_group_is_a_closed_details_with_title_case_count_and_effect_on_totals(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "extras")
    assert result["ok"] is True
    groups = page.locator("#a [data-ed-block='control'] details.ed-wg")
    assert groups.count() == 4
    assert page.eval_on_selector_all("#a .ed-wg", "els => els.map((d) => d.open)") == [False] * 4
    summaries = [sound(t) for t in page.eval_on_selector_all("#a .ed-wg > summary", "els => els.map((s) => s.innerText.replace(/\\s+/g, ' ').trim())")]
    assert summaries == [
        "Comenzi la care lipsește „Total plătit” 1 caz Afectează totalurile: nu",
        "Retururi cerute, dar fără rezultat 1 caz Afectează totalurile: da",
        "Comenzi la care totalul din antet nu e egal cu suma blocurilor 2 cazuri Afectează totalurile: nu",
        "Alte avertismente 1 caz Afectează totalurile: nu",
    ]
    assert_clean(probe)


def test_an_opened_group_shows_explanation_what_to_do_and_the_affected_orders_with_links(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    group = page.locator("#a .ed-wg", has_text="Comenzi la care totalul din antet")
    group.locator("summary").click()
    assert group.evaluate("d => d.open") is True
    body = sound(group.inner_text())
    assert "Totalul din antet diferă de suma blocurilor." in body and "Ce faci: Verifică totalul comenzii pe eMAG." in body
    rows = group.locator("tbody tr")
    assert rows.count() == 2
    first = [sound(t) for t in rows.nth(0).locator("td").all_inner_texts()]
    assert first[0] == "08.10.2024" and first[1] == "total din antet 110,39 Lei, suma blocurilor 104,89 Lei"
    assert rows.nth(0).locator("a.ed-olink").get_attribute("href") == "https://www.emag.ro/history/shoppingdetails/100000601"
    assert rows.nth(1).locator("a.ed-olink").get_attribute("href") == "https://www.emag.ro/history/shoppingdetails/100000701"


def test_a_group_opens_and_closes_from_the_keyboard(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.locator("#a .ed-wg > summary").first.focus()
    page.keyboard.press("Enter")
    assert page.evaluate("document.querySelector('#a .ed-wg').open") is True
    page.keyboard.press("Space")
    assert page.evaluate("document.querySelector('#a .ed-wg').open") is False


def test_a_return_row_shows_the_return_number_as_a_link_next_to_its_order(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    group = page.locator("#a .ed-wg", has_text="Retururi cerute")
    group.locator("summary").click()
    row = group.locator("tbody tr")
    assert row.locator("a.ed-olink").count() == 2
    assert row.locator("a.ed-olink").nth(0).get_attribute("aria-label") == "Deschide comanda 100000501 pe eMAG (filă nouă)"
    assert row.locator("a.ed-olink").nth(1).get_attribute("aria-label") == "Deschide returul 3000001 pe eMAG (filă nouă)"
    assert "Recepționare produs" in row.inner_text()


def test_a_group_without_orders_in_its_rows_still_shows_the_text(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    group = page.locator("#a .ed-wg", has_text="Alte avertismente")
    group.locator("summary").click()
    assert group.locator("a.ed-olink").count() == 0
    assert "2 produse necategorizate" in group.inner_text()


def test_brand_name_in_group_texts_is_not_translated(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    outside = page.evaluate("""() => { const found = []; const walker = document.createTreeWalker(document.querySelector('#a .ed-wgroups'), NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) { const node = walker.currentNode; if (/eMAG/.test(node.nodeValue) && !node.parentElement.closest('[translate=no]')) found.push(node.nodeValue.slice(0, 50)); }
      return found; }""")
    assert outside == []
    assert page.locator("#a .ed-wgroups [translate=no]", has_text="eMAG").count() >= 3


def test_group_texts_come_from_the_data_not_from_the_code(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.extras)); d.warnings_detail[0].title = 'Titlu schimbat în date'; d.warnings_detail[0].affects_totals = true; DATA.renamed = d; }""")
    mount(page, "renamed", "b", options="{}")
    assert "Titlu schimbat în date" in page.locator("#b .ed-wg > summary").first.inner_text()
    assert page.get_attribute("#b .ed-wg", "data-affects") == "true"


# ---------- date vechi, goale, ostile ----------

def test_old_analysis_keeps_the_plain_list_of_warning_texts(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "legacy")
    assert result["ok"] is True
    assert page.locator("#a .ed-wg").count() == 0
    summary = page.locator("#a [data-ed-block='control'] details > summary", has_text="avertismente de verificat")
    assert sound(summary.inner_text()) == "2 avertismente de verificat"
    summary.click()
    texts = page.locator("#a [data-ed-block='control'] details[open] li").all_inner_texts()
    assert "comanda 100000401, Vânzător Test SRL: lipsește 'Total platit'" in texts
    assert page.locator("#a [data-ed-block='control'] details[open] a").count() == 0, "textul liber nu se transformă în linkuri"
    assert_clean(probe)


def test_no_warnings_at_all_shows_the_all_clear_line(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.evaluate("() => { const d = JSON.parse(JSON.stringify(DATA.extras)); d.warnings = []; d.warnings_detail = []; DATA.clean = d; }")
    mount(page, "clean", "b", options="{}")
    assert "Niciun avertisment: verificările interne de sume au trecut." in page.inner_text("#b [data-ed-block='control']")
    assert page.locator("#b .ed-wg").count() == 0


def test_group_text_from_the_account_stays_plain_text(open_page):
    page, probe = open_page(width=390, height=900)
    mount(page, "hostile", options="{}")
    settle(page)
    page.evaluate("document.querySelectorAll('#a .ed-wg').forEach((d) => { d.open = true; })")
    first = page.locator("#a .ed-wg").first
    assert samples.HOSTILE_ALERT in first.locator("summary").inner_text()
    assert page.evaluate("window.__pwned === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


# ---------- datele reale ale site-ului ----------

def test_real_demo_data_groups_match_the_file(open_page, ui_data):
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    groups = ui_data["file"]["warnings_detail"]
    page, probe, _ = open_with(open_page, ui_data, "file")
    assert page.locator("#a .ed-wg").count() == len(groups)
    page.evaluate("document.querySelectorAll('#a .ed-wg').forEach((d) => { d.open = true; })")
    rows = page.eval_on_selector_all("#a .ed-wg", "els => els.map((d) => d.querySelectorAll('tbody tr').length)")
    assert rows == [len(g["items"]) for g in groups]
    kinds_with_totals = [g["affects_totals"] for g in groups]
    labels = page.eval_on_selector_all("#a .ed-wg .ed-wg-aff", "els => els.map((e) => e.textContent)")
    assert labels == [f"Afectează totalurile: {'da' if flag else 'nu'}" for flag in kinds_with_totals]
    assert_clean(probe)


# ---------- teme, telefon ----------

@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_groups_are_clean_and_fit_in_both_themes_and_widths(open_page, ui_data, scheme, width):
    page, probe, _ = open_with(open_page, ui_data, "extras", width=width, scheme=scheme, html_attrs=f'data-theme="{scheme}"')
    page.evaluate("document.querySelectorAll('#a .ed-wg').forEach((d) => { d.open = true; })")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    over = page.evaluate("[...document.querySelectorAll('#a .ed-wg .ed-tbl-wrap')].map((w) => w.scrollWidth - w.clientWidth)")
    assert all(x <= 1 for x in over), over
    # fiecare rezumat e o țintă de cel puțin 40 px (aceeași regulă ca la restul controalelor)
    heights = page.eval_on_selector_all("#a .ed-wg > summary", "els => els.map((e) => e.getBoundingClientRect().height)")
    assert all(h >= 40 for h in heights), heights
    assert_clean(probe)


def test_affecting_group_is_marked_with_words_not_only_with_color(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    texts = page.eval_on_selector_all("#a .ed-wg[data-affects='true'] .ed-wg-aff", "els => els.map((e) => e.textContent)")
    assert texts == ["Afectează totalurile: da"]


# ---------- schema ----------

def test_validate_accepts_a_file_without_the_new_keys_and_with_empty_groups(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    assert js_validate(page, "delete d.warnings_detail; delete d.price_history") == {"ok": True, "errors": []}
    assert js_validate(page, "d.warnings_detail = []") == {"ok": True, "errors": []}
    assert js_validate(page, "d.warnings_detail[1].items.forEach((i) => { delete i.return_url; delete i.status; delete i.seller; delete i.placed_at; delete i.return_id; })") == {"ok": True, "errors": []}
    assert js_validate(page, "d.warnings_detail[0].cheie_viitoare = 1; d.warnings_detail[0].items[0].alta = [1]") == {"ok": True, "errors": []}


def test_validate_rejects_wrong_shapes_and_names_the_path(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    wrong_type = js_validate(page, "d.warnings_detail[0].count = 'multe'")
    assert wrong_type["ok"] is False and "warnings_detail[0].count" in wrong_type["errors"][0]
    not_a_list = js_validate(page, "d.warnings_detail = 'nu'")
    assert not_a_list["ok"] is False and "warnings_detail" in not_a_list["errors"][0]
    missing = js_validate(page, "delete d.warnings_detail[1].title")
    assert missing["ok"] is False and "title" in missing["errors"][0]
    bad_ids = js_validate(page, "d.warnings_detail[0].items[0].order_ids = [123]")
    assert bad_ids["ok"] is False and "order_ids[0]" in bad_ids["errors"][0]


def test_a_file_with_malformed_groups_shows_the_error_state_not_a_broken_page(open_page, ui_data):
    page, probe = open_page(extra_data=ui_data)
    page.evaluate("() => { const d = JSON.parse(JSON.stringify(DATA.extras)); d.warnings_detail[0].items = 5; DATA.broken = d; }")
    result = mount(page, "broken", options="{}")
    assert result["ok"] is False
    assert page.locator("#a [role=alert]").count() == 1 and page.locator("#a .ed-wg").count() == 0
    assert_clean(probe)


def test_blocks_of_a_new_format_file_include_prices_and_an_old_one_does_not(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    assert blocks(page) == BLOCKS
    mount(page, "legacy", "b", options="{}")
    assert blocks(page, "b") == [b for b in BLOCKS if b != "preturi"]
