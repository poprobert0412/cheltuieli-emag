"""Mesajele de avertisment ale analizei, într-un singur loc: textul lor și citirea lui înapoi.

Primește: valorile din mesaj (număr comandă, vânzător, sume în bani, numere). Dă înapoi: textul (`format_*`)
sau, dintr-un text, un `ParsedWarning` cu comanda, vânzătorul, tipul grupei și dacă poate afecta totalurile.
Producătorii (order_parser.py, spend_analysis.py) și consumatorul (warning_details.py) folosesc ACEST fișier;
expresiile de citire se construiesc din aceleași șabloane, deci o formulare nouă o urmează singură (teste dus-întors).
Ce NU face: nu decide ce grupe se afișează, nu citește fișiere, nu calculează sume.
"""

import re
from dataclasses import dataclass

from emag_spend.money_ro import format_lei

# Tipurile de grupe din `warnings_detail` (aceleași valori ca în schema din analiza.json).
KIND_MISSING_PAID_TOTAL = "missing_paid_total"
KIND_PENDING_RETURN = "pending_return_without_result"
KIND_COMPLETED_RETURN_NO_REFUND = "completed_return_without_refund"
KIND_HEADER_MISMATCH = "header_total_mismatch"
KIND_OTHER = "other"
ALL_KINDS = (
    KIND_MISSING_PAID_TOTAL,
    KIND_PENDING_RETURN,
    KIND_COMPLETED_RETURN_NO_REFUND,
    KIND_HEADER_MISMATCH,
    KIND_OTHER,
)

# Familiile de mesaje: începutul comun al celor despre o comandă (cu sau fără vânzător) și despre
# un retur. Mesajele despre retururi vin din return_matcher.py, care își scrie singur textul.
_ORDER_SELLER_PREFIX = "comanda {order_id}, {seller}: "
_ORDER_PREFIX = "comanda {order_id}: "
_RETURN_PREFIX = "retur {return_id}: "

# Șabloanele mesajelor. „Total platit” (fără diacritice) e textul din pagina eMAG.
_MISSING_PAID_TOTAL = _ORDER_SELLER_PREFIX + "lipsește 'Total platit'"
_MISSING_PRODUCTS_TOTAL = _ORDER_SELLER_PREFIX + "lipsește 'Total produse'"
_PRODUCTS_SUM_MISMATCH = _ORDER_SELLER_PREFIX + "suma produselor ({sum}) ≠ 'Total produse' ({total})"
_PAID_MISMATCH = _ORDER_SELLER_PREFIX + "total plătit ({paid}) ≠ componente ({expected})"
_NO_PRODUCTS = _ORDER_SELLER_PREFIX + "niciun produs găsit"
_ORDER_NUMBER_MISMATCH = _ORDER_PREFIX + "numărul din pagină ({found}) ≠ numărul cerut ({order_id})"
_NAME_COUNT_MISMATCH = (
    _ORDER_PREFIX + "{names} nume de produs în HTML ≠ {items} produse din linii; se folosesc numele din linii"
)
_NO_SELLER_SECTION = _ORDER_PREFIX + "nicio secțiune de vânzător găsită"
_UNKNOWN_STATUS = "status necunoscut la comanda {order_id} ({seller}): {status_text}"
_PENDING_RETURNS_ONE = "1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat"
_PENDING_RETURNS_MANY = "{count} retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate"
_REFUNDS_WITHOUT_AMOUNT_ONE = "1 retur finalizat fără sumă restituită afișată"
_REFUNDS_WITHOUT_AMOUNT_MANY = "{count} retururi finalizate fără sumă restituită afișată"
_HEADER_MISMATCH_ONE = "1 comandă la care totalul din antet ≠ suma blocurilor"
_HEADER_MISMATCH_MANY = "{count} comenzi la care totalul din antet ≠ suma blocurilor"
_HIGHLIGHT_MISSING = "categoria evidențiată «{name}» nu există în config/categorii.json: totalul ei apare 0"
_FUNNEL_NOT_CLOSING = "lanțul sumelor nu se închide: comandat {ordered} ≠ părți {parts}"
_UNCATEGORIZED = "{count} produse necategorizate (adaugă reguli în config/categorii.json)"


def _pattern(template: str, **fields: str) -> re.Pattern:
    """Expresia (pentru `fullmatch`) care recunoaște exact textele produse din `template`.

    Fiecare `{câmp}` din `fields` devine un grup cu numele lui (la a doua apariție, o referință la el).
    """
    escaped = re.escape(template)
    for name, group_pattern in fields.items():
        token = re.escape("{" + name + "}")
        first, *others = escaped.split(token)
        escaped = first
        for index, part in enumerate(others):
            escaped += (f"(?P<{name}>{group_pattern})" if index == 0 else f"(?P={name})") + part
    return re.compile(escaped, re.DOTALL)


# Numerele de comandă și de retur: doar cifre ASCII ([0-9], nu \d: \d acceptă și alte alfabete).
_DIGITS = "[0-9]+"
_PENDING_RETURNS_RE = (_pattern(_PENDING_RETURNS_ONE), _pattern(_PENDING_RETURNS_MANY, count=_DIGITS))
_REFUNDS_WITHOUT_AMOUNT_RE = (_pattern(_REFUNDS_WITHOUT_AMOUNT_ONE), _pattern(_REFUNDS_WITHOUT_AMOUNT_MANY, count=_DIGITS))
_HEADER_MISMATCH_RE = (_pattern(_HEADER_MISMATCH_ONE), _pattern(_HEADER_MISMATCH_MANY, count=_DIGITS))
_COUNT_MESSAGES = (
    (KIND_PENDING_RETURN, _PENDING_RETURNS_RE),
    (KIND_COMPLETED_RETURN_NO_REFUND, _REFUNDS_WITHOUT_AMOUNT_RE),
    (KIND_HEADER_MISMATCH, _HEADER_MISMATCH_RE),
)
_MISSING_PAID_TOTAL_RE = _pattern(_MISSING_PAID_TOTAL, order_id=_DIGITS, seller=".+")  # sufixul fix ancorează sfârșitul
_UNKNOWN_STATUS_RE = _pattern(_UNKNOWN_STATUS, order_id=_DIGITS, seller=".+?", status_text=".*")
_ORDER_SELLER_RE = _pattern(_ORDER_SELLER_PREFIX + "{detail}", order_id=_DIGITS, seller=".+?", detail=".*")
_ORDER_RE = _pattern(_ORDER_PREFIX + "{detail}", order_id=_DIGITS, detail=".*")
_RETURN_RE = _pattern(_RETURN_PREFIX + "{detail}", return_id=_DIGITS, detail=".*")

# Mesajele care spun că o cifră din raport poate fi greșită (produse lipsă sau cu sumă care nu
# se leagă, pagină greșită, status necunoscut, lanț care nu se închide, retur nepotrivit). Restul
# (suma plătită, categorii, numărul de nume) sunt informative: totalul „păstrat” nu depinde de ele.
_AFFECTING_DETAIL_STARTS = ("suma produselor", "niciun produs", "nicio secțiune", "numărul din pagină")
_AFFECTING_TEXT_STARTS = ("status necunoscut la comanda", "lanțul sumelor nu se închide")


@dataclass(frozen=True)
class ParsedWarning:
    """Un avertisment citit înapoi din text.

    `kind` = grupa (una din ALL_KINDS); `order_ids` / `return_id` / `seller` = ce se poate
    afla din text (gol sau None dacă mesajul nu le conține); `count` = numărul din mesajele
    de forma „N retururi…”; `detail` = restul mesajului după „comanda X, vânzător:”;
    `affects_totals` = mesajul spune că o cifră din raport poate fi greșită.
    """

    kind: str
    text: str
    order_ids: tuple[str, ...] = ()
    return_id: str | None = None
    seller: str | None = None
    count: int | None = None
    detail: str = ""
    affects_totals: bool = False


def format_missing_paid_total(order_id: str, seller: str) -> str:
    """Blocul nu afișează „Total platit” (suma plătită vânzătorului)."""
    return _MISSING_PAID_TOTAL.format(order_id=order_id, seller=seller)


def format_missing_products_total(order_id: str, seller: str) -> str:
    """Blocul nu afișează „Total produse”."""
    return _MISSING_PRODUCTS_TOTAL.format(order_id=order_id, seller=seller)


def format_products_sum_mismatch(order_id: str, seller: str, sum_bani: int, total_bani: int) -> str:
    """Suma produselor citite ≠ „Total produse” din pagină (sumele apar în lei, nu în bani)."""
    return _PRODUCTS_SUM_MISMATCH.format(
        order_id=order_id, seller=seller, sum=format_lei(sum_bani), total=format_lei(total_bani)
    )


def format_paid_mismatch(order_id: str, seller: str, paid_bani: int, expected_bani: int) -> str:
    """„Total platit” ≠ produse + vouchere + transport + servicii (sumele apar în lei)."""
    return _PAID_MISMATCH.format(
        order_id=order_id, seller=seller, paid=format_lei(paid_bani), expected=format_lei(expected_bani)
    )


def format_no_products(order_id: str, seller: str) -> str:
    """Blocul nu conține niciun produs recunoscut."""
    return _NO_PRODUCTS.format(order_id=order_id, seller=seller)


def format_order_number_mismatch(requested_id: str, found_id: str) -> str:
    """Pagina cerută pentru o comandă arată alt număr de comandă."""
    return _ORDER_NUMBER_MISMATCH.format(order_id=requested_id, found=found_id)


def format_name_count_mismatch(order_id: str, names: int, items: int) -> str:
    """Numărul de nume de produs din HTML nu se potrivește cu produsele găsite din linii."""
    return _NAME_COUNT_MISMATCH.format(order_id=order_id, names=names, items=items)


def format_no_seller_section(order_id: str) -> str:
    """Pagina comenzii nu are nicio secțiune de vânzător."""
    return _NO_SELLER_SECTION.format(order_id=order_id)


def format_unknown_status(order_id: str, seller: str, status_text: str) -> str:
    """Statusul blocului nu e recunoscut; textul lui apare între ghilimele (repr)."""
    return _UNKNOWN_STATUS.format(order_id=order_id, seller=seller, status_text=repr(status_text))


def format_pending_returns(count: int) -> str:
    """Câte retururi sunt cerute dar fără rezultat (singular la 1)."""
    return _PENDING_RETURNS_ONE if count == 1 else _PENDING_RETURNS_MANY.format(count=count)


def format_refunds_without_amount(count: int) -> str:
    """Câte retururi finalizate nu arată suma restituită (singular la 1)."""
    return _REFUNDS_WITHOUT_AMOUNT_ONE if count == 1 else _REFUNDS_WITHOUT_AMOUNT_MANY.format(count=count)


def format_header_mismatches(count: int) -> str:
    """Câte comenzi au totalul din antet diferit de suma blocurilor (singular la 1)."""
    return _HEADER_MISMATCH_ONE if count == 1 else _HEADER_MISMATCH_MANY.format(count=count)


def format_highlight_category_missing(name: str) -> str:
    """Categoria evidențiată nu există în regulile de categorii."""
    return _HIGHLIGHT_MISSING.format(name=name)


def format_funnel_not_closing(ordered_bani: int, parts_bani: int) -> str:
    """Lanțul comandat → păstrat nu se închide (sumele apar în lei)."""
    return _FUNNEL_NOT_CLOSING.format(ordered=format_lei(ordered_bani), parts=format_lei(parts_bani))


def format_uncategorized(count: int) -> str:
    """Câte produse nu au categorie."""
    return _UNCATEGORIZED.format(count=count)


def _affects_totals(text: str, detail: str, is_return_message: bool = False) -> bool:
    """True dacă familia mesajului (după începutul textului) poate schimba o cifră din raport."""
    return (
        is_return_message
        or text.startswith(_AFFECTING_TEXT_STARTS)
        or detail.startswith(_AFFECTING_DETAIL_STARTS)
    )


def parse_order_warning(text: str) -> ParsedWarning:
    """Citește un mesaj produs de `format_*`; nu ridică excepții: un text necunoscut devine `KIND_OTHER`, fără comandă.

    Vânzătorul poate conține „:” sau virgule. Mesajele „retur <număr>: …” (din return_matcher.py) se recunosc după început.
    """
    for kind, patterns in _COUNT_MESSAGES:
        for pattern in patterns:
            match = pattern.fullmatch(text)
            if match:
                return ParsedWarning(kind, text, count=int(match.groupdict().get("count") or 1))
    match = _MISSING_PAID_TOTAL_RE.fullmatch(text)
    if match:
        return ParsedWarning(KIND_MISSING_PAID_TOTAL, text, (match["order_id"],), seller=match["seller"])
    match = _UNKNOWN_STATUS_RE.fullmatch(text)
    if match:
        return ParsedWarning(KIND_OTHER, text, (match["order_id"],), seller=match["seller"],
                             detail=match["status_text"], affects_totals=_affects_totals(text, ""))
    match = _ORDER_SELLER_RE.fullmatch(text)
    if match:
        return ParsedWarning(KIND_OTHER, text, (match["order_id"],), seller=match["seller"],
                             detail=match["detail"], affects_totals=_affects_totals(text, match["detail"]))
    match = _ORDER_RE.fullmatch(text)
    if match:
        return ParsedWarning(KIND_OTHER, text, (match["order_id"],), detail=match["detail"],
                             affects_totals=_affects_totals(text, match["detail"]))
    match = _RETURN_RE.fullmatch(text)
    if match:
        return ParsedWarning(KIND_OTHER, text, return_id=match["return_id"], detail=match["detail"],
                             affects_totals=_affects_totals(text, match["detail"], is_return_message=True))
    return ParsedWarning(KIND_OTHER, text, detail=text, affects_totals=_affects_totals(text, text))
