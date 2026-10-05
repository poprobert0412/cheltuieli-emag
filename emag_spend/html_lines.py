"""Transformă o pagină HTML într-o listă de linii de text.

Primește: HTML (str). Dă înapoi: listă de linii, fără spații duble și fără
linii goale. O linie nouă apare doar la limitele elementelor de tip bloc
(div, p, li, titluri, linkuri, butoane, <br>); elementele inline (span, sup,
small) se lipesc, deci "222" + ",98" + "Lei" devine "222,98 Lei".
Nu interpretează conținutul (nu știe de comenzi): asta fac parserele.
"""

import re

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, Tag

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_TAGS = {
    "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "td", "th", "table", "section", "article", "header", "footer",
    "dl", "dt", "dd", "br", "button", "label", "main", "nav", "aside",
    "form", "a",
}
_SPACES = re.compile(r"\s+")


_PRODUCT_ROW_SELECTOR = ".order-items li, ul.product-list li"


def _clean_text(element) -> str:
    """Textul unui element, cu spațiile unificate."""
    return _SPACES.sub(" ", element.get_text(" ")).strip()


def extract_product_names(html: str) -> list[str]:
    """Câte un nume pentru fiecare rând de produs al comenzii (rând = `li` cu cantitate), în ordinea din pagină.

    Numele se citește din `.product-description`, nu din poziția liniilor: sub nume pot apărea
    atribute ("garantie electronica") care nu sunt numele. Un rând "Pachet" (`li.promo-bundle`)
    primește numele "Pachet: <componenta 1> + <componenta 2>".
    """
    soup = BeautifulSoup(html, "lxml")
    names: list[str] = []
    for row in soup.select(_PRODUCT_ROW_SELECTOR):
        if row.select_one(".product-quantity") is None:
            continue  # rând imbricat (componentă de pachet): cantitatea e la rândul pachetului
        parts = [text for text in (_clean_text(e) for e in row.select(".product-description")) if text]
        heading = row.select_one(".promo-heading")
        name = " + ".join(parts)
        if heading is not None and parts:
            name = f"{_clean_text(heading)}: {name}"
        names.append(name)
    return names


def html_to_lines(html: str) -> list[str]:
    """Liniile de text vizibile din HTML, în ordinea din pagină."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, NavigableString):
            if isinstance(node, (Comment, Doctype)):
                return
            parts.append(_SPACES.sub(" ", str(node)))
            return
        if not isinstance(node, Tag):
            return
        name = (node.name or "").lower()
        if name in _SKIP_TAGS:
            return
        is_block = name in _BLOCK_TAGS
        if is_block:
            parts.append("\n")
        for child in node.children:
            walk(child)
        if is_block:
            parts.append("\n")

    walk(root)
    lines = (_SPACES.sub(" ", line).strip() for line in "".join(parts).split("\n"))
    return [line for line in lines if line]
