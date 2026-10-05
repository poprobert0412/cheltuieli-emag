"""Blocul „Prețuri la același produs” (cheia `price_history`): cifre-cheie, tabel sortabil și filtrabil, istoric extensibil, micro-diagrame.

Primește: componenta dashboard deschisă din file:// în Edge sau Chrome (Playwright), cu date INVENTATE (tests/dashboard_samples.py:
patru produse cu cifre ușor de verificat cu mâna) și cu datele demonstrative reale ale site-ului. Verifică: cifrele din rezumat, formulările
(„mai scump / mai ieftin cu X Lei”, fără „pierdut”/„câștigat”), o singură notă despre limite, sortare, căutare fără diacritice, rândul extensibil
cu istoricul și linkurile comenzilor, micro-diagrama corectă și cu etichetă, paginarea, starea goală, lipsa cheii (raport vechi), schema,
telefon la 390 px, ambele teme, date ostile, curățenia la unmount. Dacă niciun browser nu pornește, tot fișierul se sare.
"""

import pytest

from tests import dashboard_samples as samples
from tests.dashboard_browser_support import read_demo_file_data
from tests.test_dashboard_browser import BLOCKS, assert_clean, blocks, browser, data, mount, open_page, settle  # noqa: F401

NBSP = chr(0xA0)  # spațiul nedespărțitor, generat din cod
MINUS = chr(0x2212)  # semnul minus din interfață
PRICE_ROWS_PAGE = 25  # câte produse desenează tabelul o dată (PRICE_ROWS_PAGE din dashboard.js)
SEARCH_PAUSE_MS = 700  # puțin peste ANNOUNCE_DELAY_MS (500) din dashboard.js
TARGET_PX = 40  # --ed-target
BLOCK = "#a [data-ed-block='preturi']"
ROWS = "#a .ed-tbl-prices tbody tr:not(.ed-ph-detail)"


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


def names(page):
    """Numele produselor din tabel, în ordinea afișată."""
    return page.eval_on_selector_all(ROWS + " .ed-pname", "els => els.map((e) => e.textContent)")


def js_validate(page, mutation, dataset="extras"):
    """Aplică `mutation` (cod JS pe `d`) peste o copie a setului de date și întoarce rezultatul validate."""
    return page.evaluate(f"(() => {{ const d = JSON.parse(JSON.stringify(DATA['{dataset}'])); {mutation}; return EmagDashboard.validate(d); }})()")


# ---------- cifre-cheie și formulări ----------

def test_four_key_figures_come_from_the_summary(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "extras")
    assert result["ok"] is True and blocks(page) == BLOCKS
    assert page.get_attribute(BLOCK, "data-ed-title") == "Prețuri la același produs"
    tiles = [sound(t) for t in page.eval_on_selector_all(BLOCK + " .ed-tile", "els => els.map((e) => e.innerText.replace(/\\s+/g, ' ').trim())")]
    assert tiles == [
        "4 produse cumpărate în cel puțin două comenzi (9 cumpărări, 12 buc)",
        "63,00 Lei plătit în plus față de cel mai mic preț al fiecărui produs (diferența față de minim, la bucățile păstrate)",
        "1 produs la care ultimul preț e mai mare decât la cumpărarea dinainte: mai scump cu 10,00 Lei în total, la bucățile ultimei cumpărări",
        "2 produse la care ultimul preț e mai mic: mai ieftin cu 36,00 Lei în total; la 1 produs prețul e la fel",
    ]
    assert_clean(probe)


def test_the_block_sits_after_the_top_products_and_before_the_sellers(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    order = blocks(page)
    assert order.index("top") + 1 == order.index("preturi") == order.index("sellers") - 1


def test_change_is_worded_as_dearer_or_cheaper_never_as_loss_or_gain(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    rows = {r[0]: r for r in ([sound(c) for c in cells] for cells in
                              page.eval_on_selector_all(ROWS, "rows => rows.map((tr) => [tr.querySelector('.ed-pname').textContent, tr.children[6].innerText.replace(/\\s+/g, ' ').trim()])"))}
    assert rows["Mouse wireless Test M1, negru"][1] == f"▼ mai ieftin cu 30,00 Lei {MINUS}25,0 %"
    assert rows["Șampon Test 400 ml"][1] == f"▼ mai ieftin cu 6,00 Lei {MINUS}20,0 %"
    assert rows["Cafea boabe Aroma Test 1 kg"][1] == "▲ mai scump cu 10,00 Lei +22,2 %"
    assert rows["Baterii Test AA, set 20 buc"][1] == "la fel"
    text = page.inner_text(BLOCK).lower()
    for forbidden in ("ai pierdut", "ai câștigat", "pierdere", "câștig", "economisit", "păgubit"):
        assert forbidden not in text, forbidden


def test_one_single_note_below_the_table_states_the_limits(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    notes = page.locator(BLOCK + " .ed-ph-limits")
    assert notes.count() == 1
    text = sound(notes.inner_text())
    for needed in ("promoții", "înainte de vouchere", "vânzători diferiți", "Culorile din nume se ignoră", "capacitatea sau dimensiunea", "nu se ignoră"):
        assert needed in text, needed
    assert page.evaluate("""() => { const note = document.querySelector("#a [data-ed-block='preturi'] .ed-ph-limits"), table = document.querySelector("#a .ed-tbl-prices");
      return !!(table.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING); }""")
    assert "Cum se citește" not in page.inner_text(BLOCK).replace(notes.inner_text(), "")


# ---------- tabel: coloane, sortare, căutare ----------

def test_table_columns_and_the_default_order_follow_the_data(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    heads = [sound(h) for h in page.eval_on_selector_all("#a .ed-tbl-prices thead th", "els => els.map((e) => e.textContent)")]
    assert heads == ["Produs", "Cumpărări", "Primul preț (Lei)", "Ultimul preț (Lei)", "Preț minim (Lei)", "Preț maxim (Lei)",
                     "Ultimul preț față de precedentul", "Plătit peste minim", "Evoluție"]
    assert names(page) == [p["name"] for p in ui_data["extras"]["price_history"]["products"]]
    mouse = [sound(c) for c in page.locator(ROWS).first.locator("td").all_inner_texts()]
    assert mouse[2:6] == ["120,00", "90,00", "90,00", "120,00"] and mouse[7] == "30,00 Lei"
    assert mouse[1].replace("\n", " ") == "2 2 buc"


@pytest.mark.parametrize("option, expected_first, expected_last", [
    ("overpaid", "Mouse wireless Test M1, negru", "Baterii Test AA, set 20 buc"),
    ("rise", "Cafea boabe Aroma Test 1 kg", "Mouse wireless Test M1, negru"),
    ("drop", "Mouse wireless Test M1, negru", "Cafea boabe Aroma Test 1 kg"),
    ("times", "Cafea boabe Aroma Test 1 kg", None),
    ("name", "Baterii Test AA, set 20 buc", "Șampon Test 400 ml"),
])
def test_sorting_by_each_criterion(open_page, ui_data, option, expected_first, expected_last):
    page, probe, _ = open_with(open_page, ui_data, "extras")
    page.select_option("#a [name='ordine-produse']", option)
    shown = names(page)
    assert sorted(shown) == sorted(p["name"] for p in ui_data["extras"]["price_history"]["products"])
    assert shown[0] == expected_first
    if expected_last:
        assert shown[-1] == expected_last
    assert_clean(probe)


def test_search_ignores_case_and_diacritics_and_says_how_many_it_found(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    box = page.locator("#a [name='cauta-produs']")
    box.fill("SAMPON")
    assert names(page) == ["Șampon Test 400 ml"]
    assert sound(page.inner_text(BLOCK + " .ed-note")).startswith("1 produs din 4, căutare: „SAMPON”.")
    box.fill("test  mouse")  # mai multe cuvinte, în orice ordine
    assert names(page) == ["Mouse wireless Test M1, negru"]
    box.fill("nu există")
    assert names(page) == [] and "Niciun produs nu se potrivește cu căutarea." in page.inner_text(BLOCK)
    assert page.locator("#a .ed-tbl-prices").count() == 0
    box.fill("")
    assert len(names(page)) == 4


def test_the_number_found_is_announced_after_a_pause_in_typing_not_on_every_key(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    live = "#a .ed-sr[role=status]"
    page.locator("#a [name='cauta-produs']").press_sequentially("caf", delay=30)
    assert page.inner_text(live) == "", "anunțul așteaptă o pauză în tastare"
    page.wait_for_timeout(SEARCH_PAUSE_MS)
    assert sound(page.inner_text(live)) == "1 produs din 4, căutare: „caf”."


def test_search_and_sort_controls_have_labels_and_are_tall_enough(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    labels = page.eval_on_selector_all(BLOCK + " label.ed-field", "els => els.map((l) => [l.querySelector('.ed-field-label').textContent, !!l.querySelector('input, select')])")
    assert labels == [["Caută produs", True], ["Ordonează după", True]]
    box = page.locator("#a [name='cauta-produs']")
    assert box.get_attribute("type") == "search" and box.get_attribute("autocomplete") == "off" and box.get_attribute("spellcheck") == "false"
    assert box.get_attribute("placeholder").endswith("…")
    heights = page.eval_on_selector_all(BLOCK + " .ed-input", "els => els.map((e) => e.getBoundingClientRect().height)")
    assert all(h >= TARGET_PX for h in heights), heights


# ---------- rândul extensibil cu istoricul ----------

def test_a_row_expands_to_the_history_with_original_names_and_order_links(open_page, ui_data):
    page, probe, _ = open_with(open_page, ui_data, "extras")
    row = page.locator(ROWS).first  # produsul cu culori diferite, prima cumpărare fără dată
    button = row.locator(".ed-ph-open")
    assert button.get_attribute("aria-expanded") == "false"
    detail = page.locator("#a .ed-ph-detail")
    assert detail.count() == 0, "istoricul nu se construiește până nu e cerut"
    button.click()
    assert button.get_attribute("aria-expanded") == "true"
    assert detail.count() == 1 and detail.is_visible()
    history = [[sound(c) for c in cells] for cells in detail.locator("tbody tr").evaluate_all("rows => rows.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\\s+/g, ' ').trim()))")]
    assert history == [
        ["", "Mouse wireless Test M1, alb", "eMAG", "1", "120,00 Lei cel mai mare", "100000404 ↗"],
        ["01.06.2025", "Mouse wireless Test M1, negru", "eMAG", "1", "90,00 Lei cel mai mic", "100000505 ↗"],
    ]
    hrefs = detail.locator("a.ed-olink").evaluate_all("els => els.map((a) => a.getAttribute('href'))")
    assert hrefs == ["https://www.emag.ro/history/shoppingdetails/100000404", "https://www.emag.ro/history/shoppingdetails/100000505"]
    assert "Numele diferă între comenzi (de exemplu altă culoare)" in detail.inner_text()
    button.click()
    assert button.get_attribute("aria-expanded") == "false" and not detail.is_visible()
    assert_clean(probe)


def test_the_colour_note_appears_only_for_products_bought_in_several_colours(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.locator(ROWS + " .ed-ph-open").nth(2).click()  # cafea: același nume la toate cumpărările
    assert "Numele diferă între comenzi" not in page.inner_text(BLOCK)


def test_the_toggle_works_from_the_keyboard_and_announces_itself(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    button = page.locator(ROWS + " .ed-ph-open").first
    button.focus()
    page.keyboard.press("Enter")
    assert button.get_attribute("aria-expanded") == "true"
    assert page.inner_text("#a .ed-sr[role=status]") == "Istoricul prețurilor e afișat."
    page.keyboard.press("Space")
    assert button.get_attribute("aria-expanded") == "false"
    assert "(arată istoricul prețurilor)" in button.inner_text() or button.locator(".ed-sr").count() == 1


def test_open_rows_stay_open_after_sorting_and_filtering(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.locator(ROWS + " .ed-ph-open").nth(2).click()  # cafea
    page.select_option("#a [name='ordine-produse']", "name")
    cafea = page.locator(ROWS, has_text="Cafea boabe")
    assert cafea.locator(".ed-ph-open").get_attribute("aria-expanded") == "true"
    assert page.locator("#a .ed-ph-detail").is_visible()
    page.locator("#a [name='cauta-produs']").fill("mouse")
    assert page.locator("#a .ed-ph-detail").count() == 0
    page.locator("#a [name='cauta-produs']").fill("")
    assert page.locator(ROWS, has_text="Cafea boabe").locator(".ed-ph-open").get_attribute("aria-expanded") == "true"


# ---------- micro-diagrama ----------

def test_each_row_has_a_sparkline_with_an_accessible_label_with_the_real_figures(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    sparks = page.eval_on_selector_all(ROWS, """rows => rows.map((tr) => { const s = tr.querySelector('svg.ed-spark');
      return { name: tr.querySelector('.ed-pname').textContent, role: s.getAttribute('role'), label: s.getAttribute('aria-label'), w: s.getAttribute('width'), h: s.getAttribute('height'),
               circles: s.querySelectorAll('circle').length, min: s.querySelectorAll('.ed-spark-min').length, last: s.querySelectorAll('.ed-spark-last').length,
               points: (s.querySelector('polyline') || { getAttribute: () => '' }).getAttribute('points') }; })""")
    by_name = {s["name"]: s for s in sparks}
    mouse, coffee = by_name["Mouse wireless Test M1, negru"], by_name["Cafea boabe Aroma Test 1 kg"]
    assert mouse["role"] == "img" and mouse["w"] == "96" and mouse["h"] == "28"
    assert sound(mouse["label"]) == "Prețul pe bucată: de la 120,00 Lei la 90,00 Lei (01.06.2025); minim 90,00 Lei, maxim 120,00 Lei."
    assert sound(coffee["label"]) == "Prețul pe bucată: de la 50,00 Lei (10.01.2023) la 55,00 Lei (14.03.2025); minim 45,00 Lei, maxim 55,00 Lei."
    assert mouse["points"] == "4.0,4.0 92.0,24.0"  # preț mare sus, preț mic jos; fără dată la prima cumpărare: puncte la distanțe egale
    for spark, product in ((mouse, 2), (coffee, 3)):
        assert spark["circles"] == product and spark["last"] == 1
    assert coffee["min"] == 1 and mouse["min"] == 0, "minimul e inel doar dacă nu coincide cu ultimul preț (la mouse, minimul e ultimul)"


def test_sparkline_follows_the_dates_when_all_are_known(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    page.evaluate("""() => { const d = JSON.parse(JSON.stringify(DATA.extras)); const p = d.price_history.products.find((x) => x.key === 'cafea boabe aroma test 1 kg');
      p.purchases[0].date = '2020-01-01'; p.purchases[1].date = '2020-01-11'; p.purchases[2].date = '2021-01-01'; DATA.dated = d; }""")
    mount(page, "dated", "b", options="{}")
    points = page.evaluate("""() => { const tr = [...document.querySelectorAll('#b .ed-tbl-prices tbody tr')].find((r) => r.textContent.includes('Cafea boabe'));
      return tr.querySelector('polyline').getAttribute('points').split(' ').map((p) => parseFloat(p.split(',')[0])); }""")
    assert points[0] == 4.0 and points[2] == 92.0 and 5 < points[1] < 8, points  # 10 zile din 366: lângă început, nu la mijloc (48)


def test_a_product_with_equal_prices_gets_a_flat_line_in_the_middle(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    flat = page.evaluate("""() => { const tr = [...document.querySelectorAll('#a .ed-tbl-prices tbody tr')].find((r) => r.textContent.includes('Baterii'));
      return tr.querySelector('polyline').getAttribute('points'); }""")
    assert flat == "4.0,14.0 92.0,14.0"


# ---------- date reale, paginare, stări ----------

def test_real_demo_data_is_paged_a_screen_at_a_time_and_every_product_is_reachable(open_page, ui_data):
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    products = ui_data["file"]["price_history"]["products"]
    assert len(products) > PRICE_ROWS_PAGE, "datele demonstrative trebuie să aibă mai multe produse decât o pagină"
    page, probe, _ = open_with(open_page, ui_data, "file")
    assert len(names(page)) == PRICE_ROWS_PAGE
    more = page.locator(BLOCK + " .ed-more")
    remaining = len(products) - PRICE_ROWS_PAGE
    assert sound(more.inner_text()) == f"Arată încă {min(PRICE_ROWS_PAGE, remaining)} ({remaining} rămase)"
    more.click()
    assert len(names(page)) == min(2 * PRICE_ROWS_PAGE, len(products))
    while page.locator(BLOCK + " .ed-more").count():
        page.locator(BLOCK + " .ed-more").click()
    assert names(page) == [p["name"] for p in products]
    assert_clean(probe)


def test_real_demo_data_figures_match_the_file(open_page, ui_data):
    if "file" not in ui_data:
        pytest.skip("interfata/assets/demo-data.js nu există")
    summary = ui_data["file"]["price_history"]["summary"]
    page, _, _ = open_with(open_page, ui_data, "file")
    tiles = page.eval_on_selector_all(BLOCK + " .ed-tile-num", "els => els.map((e) => e.textContent)")
    assert tiles[0] == str(summary["products"])
    whole, frac = divmod(summary["overpaid_vs_min_bani"], 100)
    assert sound(tiles[1]) == f"{whole:,}".replace(",", ".") + f",{frac:02d} Lei"
    assert tiles[2] == str(summary["last_vs_prev"]["pricier_products"]) and tiles[3] == str(summary["last_vs_prev"]["cheaper_products"])


def test_no_repeated_products_gives_an_empty_state_not_a_broken_block(open_page):
    page, probe = open_page()
    mount(page, "small", options="{}")
    settle(page)
    assert page.locator(BLOCK).count() == 1
    assert "Niciun produs n-a fost păstrat din cel puțin două comenzi diferite." in page.inner_text(BLOCK)
    assert page.locator(BLOCK + " table, " + BLOCK + " input, " + BLOCK + " .ed-tile").count() == 0
    assert_clean(probe)


def test_an_old_analysis_without_price_history_has_no_price_block(open_page, ui_data):
    page, probe, result = open_with(open_page, ui_data, "legacy")
    assert result["ok"] is True and "preturi" not in blocks(page)
    assert "Prețuri la același produs" not in page.inner_text("#a")
    assert_clean(probe)


def test_hostile_names_stay_text_and_long_numbers_are_cut(open_page):
    page, probe = open_page(width=390, height=900)
    mount(page, "hostile", options="{}")
    settle(page)
    assert samples.HOSTILE_ALERT in page.inner_text(BLOCK)
    page.locator(ROWS + " .ed-ph-open").first.click()
    shown = page.locator("#a .ed-ph-detail td[data-label='Comanda']").all_inner_texts()
    assert shown and all(len(t) <= 30 for t in shown), shown
    assert page.evaluate("window.__pwned === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


def test_unmounting_while_a_search_announcement_is_pending_leaves_nothing_behind(open_page, ui_data):
    page, probe, _ = open_with(open_page, ui_data, "extras")
    page.locator("#a [name='cauta-produs']").fill("caf")
    page.evaluate("window.H.a.unmount()")
    page.wait_for_timeout(SEARCH_PAUSE_MS)
    assert page.evaluate("document.getElementById('a').children.length") == 0
    assert_clean(probe)


# ---------- teme și telefon ----------

@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_block_is_clean_and_fits_in_both_themes_and_widths(open_page, ui_data, scheme, width):
    page, probe, _ = open_with(open_page, ui_data, "extras", width=width, scheme=scheme, html_attrs=f'data-theme="{scheme}"')
    page.locator(ROWS + " .ed-ph-open").first.click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    wrap = page.evaluate("(() => { const w = document.querySelector('#a [data-ed-block=preturi] .ed-tbl-wrap'); return [w.scrollWidth - w.clientWidth, getComputedStyle(w.querySelector('table')).display]; })()")
    assert wrap[0] <= 1
    assert wrap[1] == ("block" if width == 390 else "table"), "pe telefon tabelul devine listă de carduri"
    tall = page.eval_on_selector_all(BLOCK + " .ed-ph-open", "els => els.map((e) => e.getBoundingClientRect().height)")
    assert all(h >= TARGET_PX for h in tall), tall
    assert_clean(probe)


def test_select_has_explicit_colors_so_it_is_readable_in_dark_mode(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras", scheme="dark", html_attrs='data-theme="dark"')
    colors = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('#a [name=ordine-produse]')); return [s.backgroundColor, s.color]; })()")
    assert colors == ["rgb(26, 26, 25)", "rgb(255, 255, 255)"]


def test_card_layout_on_a_phone_keeps_every_column_label(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras", width=390, height=900)
    labels = page.evaluate("[...document.querySelector('#a .ed-tbl-prices tbody tr').children].map((td) => td.dataset.label)")
    heads = page.eval_on_selector_all("#a .ed-tbl-prices thead th", "els => els.map((e) => e.textContent)")
    assert labels == heads
    page.locator(ROWS + " .ed-ph-open").first.click()
    assert page.evaluate("document.querySelector('#a .ed-ph-cell').getBoundingClientRect().width > 250")


# ---------- schema ----------

def test_validate_accepts_missing_optional_parts_and_null_percent(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    assert js_validate(page, "delete d.price_history") == {"ok": True, "errors": []}
    assert js_validate(page, "d.price_history.products.forEach((p) => { p.last_vs_prev_pct = null; delete p.category; delete p.color_variants; delete p.last_vs_prev_impact_bani; })") == {"ok": True, "errors": []}
    assert js_validate(page, "d.price_history.products = []") == {"ok": True, "errors": []}
    assert js_validate(page, "d.price_history.cheie_viitoare = 1; d.price_history.products[0].alta = 'x'") == {"ok": True, "errors": []}
    assert js_validate(page, "d.price_history.products[0].purchases[0].date = null") == {"ok": True, "errors": []}


def test_validate_rejects_wrong_shapes_and_names_the_path(open_page, ui_data):
    page, _, _ = open_with(open_page, ui_data, "extras")
    bad_money = js_validate(page, "d.price_history.products[0].purchases[1].unit_bani = '12,00'")
    assert bad_money["ok"] is False and "price_history.products[0].purchases[1].unit_bani" in bad_money["errors"][0]
    no_summary = js_validate(page, "delete d.price_history.summary")
    assert no_summary["ok"] is False and "summary" in no_summary["errors"][0]
    not_object = js_validate(page, "d.price_history = []")
    assert not_object["ok"] is False and "price_history" in not_object["errors"][0]
    bad_pct = js_validate(page, "d.price_history.products[0].last_vs_prev_pct = 'mult'")
    assert bad_pct["ok"] is False and "last_vs_prev_pct" in bad_pct["errors"][0]
    no_purchases = js_validate(page, "d.price_history.products[0].purchases = 7")
    assert no_purchases["ok"] is False


def test_a_malformed_price_block_shows_the_error_state(open_page, ui_data):
    page, probe = open_page(extra_data=ui_data)
    page.evaluate("() => { const d = JSON.parse(JSON.stringify(DATA.extras)); d.price_history.products[0].purchases[0] = null; DATA.broken = d; }")
    result = mount(page, "broken", options="{}")
    assert result["ok"] is False and page.locator("#a [role=alert]").count() == 1
    assert_clean(probe)
