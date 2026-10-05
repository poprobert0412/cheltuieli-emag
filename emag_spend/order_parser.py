"""Citește o pagină de detalii comandă eMAG și o transformă într-un `Order`.

Primește: numărul comenzii și liniile de text ale paginii (html_lines).
Dă înapoi: `Order` cu blocuri pe vânzător, produse, status, vouchere, transport, taxe și „Total platit”.
Nu citește adresa, telefonul sau e-mailul. Ce nu se leagă (sume diferite) devine avertisment în
`Order.warnings` (texte din warning_messages.py), nu excepție; ValueError doar dacă pagina nu e o comandă.
Un bloc ANULAT nu are „Total platit” (pagina lui arată „Total de plata”, suma de plătit): lipsa lui nu e avertisment.
"""

import re

from emag_spend import warning_messages
from emag_spend.block_status import CANCELLED, classify_status
from emag_spend.dates_ro import parse_ro_datetime
from emag_spend.models import Item, Order, SellerBlock
from emag_spend.money_ro import find_amount, find_last_amount, parse_full_amount, ro_amount_to_bani
from emag_spend.text_normalize import normalize_text

_ORDER_HEADER = re.compile(r"^Comanda nr\.?\s*(\d+)", re.IGNORECASE)
_SELLER_HEADER = re.compile(
    r"^Produse vandute (?:de (?P<a>.+?) si livrate de eMAG|si livrate de (?P<b>.+))$",
    re.IGNORECASE,
)
_QTY = re.compile(r"^(\d+)\s*buc\.?$", re.IGNORECASE)
_PRICE_AND_QTY = re.compile(r"^(?P<price>-?[\d.]+,\d{2})\s*Lei\s+(?P<qty>\d+)\s*buc\.?$", re.IGNORECASE)
_PLACED = re.compile(r"Plasata pe:\s*(.+?)(?=\s+Total:|$)", re.IGNORECASE)
_HEADER_TOTAL = re.compile(r"Total:\s*(-?[\d.]+,\d{2})\s*Lei", re.IGNORECASE)

# Linii care stau lângă numele produsului dar nu sunt numele lui (inclusiv atributele
# de sub nume, ex. "garantie electronica"). Plasă de siguranță pentru cazul în care numele
# nu se pot citi structural din HTML.
_AUX_PREFIXES = (
    "acorda o nota", "cumpara din nou", "adauga review", "scrie un review", "vezi produs",
    "garantie electronica", "garantie ", "ghidul utilizatorului",
)
# Linii care încheie zona de status a unui bloc.
_STATUS_STOP_PREFIXES = (
    "istoric livrare", "modalitate livrare", "date facturare", "modalitate de plata",
    "de prezentat la livrare", "data de livrare", "pentru:", "factura", "total produse",
)
_MAX_STATUS_LINES = 14


def _seller_from_header(line: str) -> str | None:
    """Numele vânzătorului dacă linia e titlu de bloc; altfel None."""
    match = _SELLER_HEADER.match(line)
    if match:
        return (match.group("a") or match.group("b")).strip()
    return None


def _amount_for_label(lines: list[str], index: int) -> int | None:
    """Suma unei etichete ("Total produse: 222,98 Lei"), pe aceeași linie sau pe următoarea.

    "GRATUIT" înseamnă 0. Întoarce None dacă nu găsește nicio sumă.
    """
    line = lines[index]
    after = line.split(":", 1)[1] if ":" in line else ""
    if "gratuit" in normalize_text(after or line):
        return 0
    amount = find_last_amount(line)  # eticheta și suma pe aceeași linie (cu sau fără ':')
    if amount is not None:
        return amount
    if re.search(r"\w", after):
        return None  # după ':' e text propriu fără sumă (nu doar un al doilea ':'): nu citim linia următoare
    if index + 1 < len(lines):  # așezarea cu valoarea pe linia următoare
        following = lines[index + 1]
        if "gratuit" in normalize_text(following):
            return 0
        amount = parse_full_amount(following)
        if amount is None:
            amount = find_amount(following)
        return amount
    return None


def _item_name(lines: list[str], price_index: int) -> str:
    """Numele produsului: cea mai apropiată linie de dinaintea prețului care nu e auxiliară."""
    j = price_index - 1
    while j >= 0 and normalize_text(lines[j]).startswith(_AUX_PREFIXES):
        j -= 1
    return lines[j] if j >= 0 else ""


def _status_text(lines: list[str], header_index: int) -> str:
    """Liniile de status de după titlul blocului, până la primul marcaj de oprire."""
    collected: list[str] = []
    for line in lines[header_index + 1 : header_index + 1 + _MAX_STATUS_LINES]:
        if normalize_text(line).startswith(_STATUS_STOP_PREFIXES) or _seller_from_header(line):
            break
        collected.append(line)
    return " | ".join(collected)


def _check_block(order_id: str, block: SellerBlock, warnings: list[str]) -> None:
    """Verifică invariantele unui bloc și notează avertismente."""
    if block.products_total_bani is None:
        warnings.append(warning_messages.format_missing_products_total(order_id, block.seller))
    else:
        as_totals = sum(item.line_total_bani for item in block.items)
        as_units = sum(item.line_total_bani * item.qty for item in block.items)
        if as_totals != block.products_total_bani:
            if as_units == block.products_total_bani:
                for item in block.items:  # prețul afișat era pe bucată, nu pe linie
                    item.line_total_bani *= item.qty
            else:
                warnings.append(warning_messages.format_products_sum_mismatch(
                    order_id, block.seller, as_totals, block.products_total_bani
                ))
    if block.paid_bani is None:
        if block.status != CANCELLED:  # la un bloc anulat „Total platit” nu există: nu e o problemă de citit
            warnings.append(warning_messages.format_missing_paid_total(order_id, block.seller))
    elif block.products_total_bani is not None and block.status != CANCELLED:
        # la blocurile anulate "Total platit" e 0 sau parțial (banii s-au rambursat): nu se verifică
        expected = (
            block.products_total_bani
            + sum(block.vouchers_bani)
            + (block.shipping_bani or 0)
            + sum(block.services_bani)
            + sum(block.other_bani)
        )
        if expected != block.paid_bani:
            warnings.append(warning_messages.format_paid_mismatch(order_id, block.seller, block.paid_bani, expected))
    if not block.items:
        warnings.append(warning_messages.format_no_products(order_id, block.seller))


def _apply_structural_names(order_id: str, blocks: list[SellerBlock], names: list[str], warnings: list[str]) -> None:
    """Pune numele citite din HTML (`.product-description`) pe produsele găsite din linii.

    Se aplică doar dacă numărul lor se potrivește cu numărul produselor; altfel rămân numele
    deduse din linii și se notează un avertisment.
    """
    items = [item for block in blocks for item in block.items]
    if len(names) != len(items):
        warnings.append(warning_messages.format_name_count_mismatch(order_id, len(names), len(items)))
        return
    for item, name in zip(items, names):
        item.name = name


def parse_order(order_id: str, lines: list[str], product_names: list[str] | None = None) -> Order:
    """Construiește `Order` din liniile paginii de detalii.

    `product_names` (opțional) = numele produselor citite structural din HTML; când sunt date și
    se potrivesc ca număr, înlocuiesc numele deduse din linii (mai sigure când sub nume apar
    atribute precum "garantie electronica").
    """
    start = next((i for i, line in enumerate(lines) if _ORDER_HEADER.match(line)), None)
    if start is None:
        raise ValueError(f"pagina comenzii {order_id} nu conține 'Comanda nr.' (sesiune expirată?)")
    warnings: list[str] = []
    found_id = _ORDER_HEADER.match(lines[start]).group(1)
    if found_id != order_id:
        warnings.append(warning_messages.format_order_number_mismatch(order_id, found_id))

    first_block = next(
        (i for i in range(start, len(lines)) if _seller_from_header(lines[i])), len(lines)
    )
    head_text = " ".join(lines[start:first_block])
    placed_match = _PLACED.search(head_text)
    placed_text = placed_match.group(1).strip() if placed_match else ""
    total_match = _HEADER_TOTAL.search(head_text)
    header_total = ro_amount_to_bani(total_match.group(1)) if total_match else None

    blocks: list[SellerBlock] = []
    current: SellerBlock | None = None
    totals_zone = False  # între "Total produse" și "Total platit"
    for i in range(first_block, len(lines)):
        line = lines[i]
        seller = _seller_from_header(line)
        if seller is not None:
            status_text = _status_text(lines, i)
            current = SellerBlock(
                seller=seller,
                status=classify_status(status_text),
                status_text=status_text,
                has_storno=False,
            )
            blocks.append(current)
            totals_zone = False
            continue
        if current is None:
            continue
        normalized = normalize_text(line)
        if "factura storno" in normalized:
            current.has_storno = True

        if current.products_total_bani is None:
            price_qty = _PRICE_AND_QTY.match(line)
            qty_only = _QTY.match(line)
            if price_qty:
                name = _item_name(lines, i)
                current.items.append(
                    Item(name, ro_amount_to_bani(price_qty.group("price")), int(price_qty.group("qty")))
                )
                continue
            if qty_only and i >= 1:
                price = parse_full_amount(lines[i - 1])
                if price is not None:
                    current.items.append(Item(_item_name(lines, i - 1), price, int(qty_only.group(1))))
                    continue

        if normalized.startswith("total produse"):
            current.products_total_bani = _amount_for_label(lines, i)
            totals_zone = True
        elif normalized.startswith("total platit"):
            current.paid_bani = _amount_for_label(lines, i)
            totals_zone = False
        elif normalized.startswith("reducere"):
            amount = _amount_for_label(lines, i)
            if amount is not None:
                current.vouchers_bani.append(amount)
        elif normalized.startswith("cost livrare"):
            current.shipping_bani = _amount_for_label(lines, i)
        elif normalized.startswith("servicii operationale"):
            amount = _amount_for_label(lines, i)
            if amount is not None:
                current.services_bani.append(amount)
        elif totals_zone and ":" in line:
            amount = find_last_amount(line)
            if amount is not None:
                current.other_bani.append(amount)

    if not blocks:
        warnings.append(warning_messages.format_no_seller_section(order_id))
    if product_names is not None:
        _apply_structural_names(order_id, blocks, product_names, warnings)
    for block in blocks:
        _check_block(order_id, block, warnings)

    return Order(
        order_id=order_id,
        placed_text=placed_text,
        placed_at=parse_ro_datetime(placed_text),
        header_total_bani=header_total,
        blocks=blocks,
        warnings=warnings,
    )
