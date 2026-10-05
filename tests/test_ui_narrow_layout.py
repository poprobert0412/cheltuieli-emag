"""Aspectul raportului pe lățime mică (390 px): etichetele din rândurile-bară nu se rup în mijlocul cuvintelor.

Primește: componenta dashboard deschisă din file:// în Edge sau Chrome (Playwright), cu datele demonstrative reale ale site-ului și cu date
INVENTATE. Verifică: la 390 px (și 360) niciun cuvânt din numele categoriilor și ale vânzătorilor nu e rupt pe două rânduri (înainte: „Calculatoar/e”),
un cuvânt mai lung decât un rând întreg se rupe totuși (nu iese din ecran), iar pagina nu are scroll orizontal. Dacă niciun browser nu pornește, se sare.
"""

import pytest

from tests.dashboard_browser_support import read_demo_file_data
from tests.test_dashboard_browser import assert_clean, browser, data, mount, open_page, settle  # noqa: F401

# Pentru fiecare cuvânt (secvență fără spații) din etichetele rândurilor-bară: câte rânduri vizuale ocupă. Peste unul = cuvânt rupt.
BROKEN_WORDS = """() => {
  const broken = [];
  document.querySelectorAll('#a .ed-bar-name').forEach((el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, text = node.nodeValue;
      for (const match of text.matchAll(/\\S+/g)) {
        const range = document.createRange();
        range.setStart(node, match.index); range.setEnd(node, match.index + match[0].length);
        const lines = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
        if (lines.size > 1) broken.push(match[0]);
      }
    }
  });
  return broken;
}"""
LONG_WORD = "Supercalifragilisticexpialidocious" * 4  # mai lung decât un rând de 330 px: trebuie să se rupă, nu să iasă din ecran


@pytest.fixture(scope="module")
def demo_file():
    """Datele demonstrative reale ale site-ului; testul se sare dacă fișierul lipsește."""
    loaded = read_demo_file_data()
    if loaded is None:
        pytest.skip("interfata/assets/demo-data.js nu există")
    return loaded


@pytest.mark.parametrize("width", [360, 390])
def test_bar_labels_are_never_cut_in_the_middle_of_a_word_on_a_phone(open_page, demo_file, width):
    page, probe = open_page(width=width, height=900, extra_data={"file": demo_file})
    mount(page, "file")
    settle(page)
    names = page.eval_on_selector_all("#a .ed-bar-name", "els => els.map((e) => e.textContent)")
    assert len(names) > 10 and any(len(n.split()) > 2 for n in names), "datele n-au etichete lungi: testul n-ar dovedi nimic"
    assert page.evaluate(BROKEN_WORDS) == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert_clean(probe)


def test_on_a_phone_the_label_gets_the_full_row_and_the_figures_sit_below_it(open_page, demo_file):
    page, _ = open_page(width=390, height=900, extra_data={"file": demo_file})
    mount(page, "file")
    settle(page)
    layout = page.evaluate("""() => { const row = document.querySelector("#a [data-ed-block='categories'] .ed-bar-row");
      const name = row.querySelector('.ed-bar-name').getBoundingClientRect(), value = row.querySelector('.ed-bar-val').getBoundingClientRect();
      return { fullWidth: name.width >= row.clientWidth - 20, valueBelow: value.top >= name.bottom - 1 }; }""")
    assert layout == {"fullWidth": True, "valueBelow": True}


def test_wide_layout_keeps_label_and_figures_on_one_line(open_page, demo_file):
    page, _ = open_page(width=1280, height=900, extra_data={"file": demo_file})
    mount(page, "file")
    settle(page)
    same_line = page.evaluate("""() => { const row = document.querySelector("#a [data-ed-block='categories'] .ed-bar-row");
      const name = row.querySelector('.ed-bar-name').getBoundingClientRect(), value = row.querySelector('.ed-bar-val').getBoundingClientRect();
      return Math.abs(name.top - value.top) < 12; }""")
    assert same_line


def test_a_word_longer_than_a_whole_row_still_breaks_instead_of_leaving_the_screen(open_page, demo_file):
    page, probe = open_page(width=390, height=900, extra_data={"file": demo_file})
    page.evaluate("(long) => { const d = JSON.parse(JSON.stringify(DATA.file)); d.by_category[0].name = long; d.by_seller[0].seller = long; DATA.long = d; }", LONG_WORD)
    mount(page, "long")
    settle(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    over = page.evaluate("[...document.querySelectorAll('#a .ed-bar-name')].map((e) => e.scrollWidth - e.clientWidth)")
    assert all(x <= 1 for x in over), over
    assert_clean(probe)
