"""Grupează avertismentele în `warnings_detail`: grupe cu titlu, explicație și lista comenzilor.

Primește: textele `warnings`, comenzile, retururile, comenzile cu antetul ≠ suma blocurilor și textele din
config/avertismente.json. Dă înapoi: grupele din schema `warnings_detail` (doar cele cu rânduri, în ordinea
din `ALL_KINDS`), fiecare cu `count == len(items)`. Mesajele despre comenzi se citesc din text; retururile și
antetele se iau din date, nu din numărul din text. Ce NU face: nu calculează totaluri, nu modifică `warnings`.
"""

import logging
import re
import string
from collections import Counter
from pathlib import Path

from emag_spend import block_status, settings
from emag_spend.json_file import read_json
from emag_spend.models import Order, ReturnRequest
from emag_spend.money_ro import format_lei
from emag_spend.order_links import return_url
from emag_spend.warning_messages import (
    ALL_KINDS, KIND_COMPLETED_RETURN_NO_REFUND, KIND_HEADER_MISMATCH, KIND_MISSING_PAID_TOTAL, KIND_OTHER,
    KIND_PENDING_RETURN, ParsedWarning, parse_order_warning,
)

logger = logging.getLogger(__name__)

WARNING_TEXTS_FILE = settings.PROJECT_ROOT / "config" / "avertismente.json"

# Câte nume de produs intră în rândul unui retur înainte de „încă N”: rândul rămâne scurt și când
# un retur are multe produse (lista completă e în retururi.json).
MAX_PRODUCT_NAMES_IN_TEXT = 3

# Câmpurile pe care codul le dă șablonului `item_text` al fiecărei grupe. Un șablon editat de mână
# cu alt câmp ar strica raportul, deci se respinge la încărcare (cu fișierul și grupa numite).
ITEM_TEXT_FIELDS = {
    KIND_MISSING_PAID_TOTAL: ("seller", "status"),
    KIND_HEADER_MISMATCH: ("header", "blocks"),
    KIND_PENDING_RETURN: ("products", "step"),
    KIND_COMPLETED_RETURN_NO_REFUND: ("products", "mode"),
    KIND_OTHER: ("text",),
}
_GROUP_TEXT_KEYS = ("title", "explanation", "what_to_do", "item_text")
_DEFAULT_TEXT_KEYS = ("produse_lipsa", "pas_lipsa", "mod_lipsa", "produse_in_plus", "antet_cu_bloc_anulat")
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _check_item_template(path: Path, kind: str, template: str) -> None:
    """Ridică ValueError dacă șablonul are acolade greșite, formă de câmp complicată sau un câmp nepermis."""
    allowed = ITEM_TEXT_FIELDS[kind]
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as error:
        raise ValueError(f"{path}: grupa {kind!r}, item_text are acolade greșite ({error})") from error
    fields = [(name, spec, conversion) for _, name, spec, conversion in parts if name is not None]
    if any(spec or conversion or not name.isidentifier() for name, spec, conversion in fields):
        raise ValueError(f"{path}: grupa {kind!r}, item_text: folosește doar câmpuri simple, ca {{{allowed[0]}}}")
    unknown = sorted({name for name, _, _ in fields} - set(allowed))
    if unknown:
        raise ValueError(
            f"{path}: grupa {kind!r}, item_text are câmpuri necunoscute {unknown}; cele permise: {list(allowed)}"
        )


def load_warning_texts(path: Path = WARNING_TEXTS_FILE) -> dict:
    """Citește config/avertismente.json; ValueError (cu fișierul și grupa) la o grupă sau cheie lipsă, un tip greșit
    sau un șablon cu un câmp pe care codul nu-l dă: un text greșit nu trebuie să afle abia când apare avertismentul.
    """
    data = read_json(path)
    sections = ("grupe", "etichete_status", "valori_implicite")
    if not isinstance(data, dict) or not all(isinstance(data.get(key), dict) for key in sections):
        raise ValueError(f"{path}: trebuie să fie un obiect cu cheile-obiect {', '.join(repr(k) for k in sections)}")
    for kind in ALL_KINDS:
        group = data["grupe"].get(kind)
        if not isinstance(group, dict):
            raise ValueError(f"{path}: lipsește grupa {kind!r} din 'grupe'")
        for key in _GROUP_TEXT_KEYS:
            if not isinstance(group.get(key), str) or not group[key].strip():
                raise ValueError(f"{path}: grupa {kind!r} trebuie să aibă textul nevid {key!r}")
        if not isinstance(group.get("affects_totals"), bool):
            raise ValueError(f"{path}: grupa {kind!r}: 'affects_totals' trebuie să fie true sau false")
        _check_item_template(path, kind, group["item_text"])
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in data["etichete_status"].items()):
        raise ValueError(f"{path}: 'etichete_status' trebuie să fie un obiect cu valori text")
    for key in _DEFAULT_TEXT_KEYS:
        if not isinstance(data["valori_implicite"].get(key), str):
            raise ValueError(f"{path}: 'valori_implicite' trebuie să aibă textul {key!r}")
    try:
        data["valori_implicite"]["produse_in_plus"].format(count=1)
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(f"{path}: 'produse_in_plus' poate folosi doar câmpul {{count}} ({error})") from error
    return data


def current_order_warnings(order: Order) -> list[str]:
    """Avertismentele salvate pe comandă, fără „lipsește Total platit” scris în plus pentru blocuri ANULATE.

    Un comenzi.json salvat de o versiune veche are acel mesaj și la blocurile anulate (unde „Total platit”
    nu există): se scot doar mesajele peste numărul blocurilor ne-anulate fără sumă ale aceluiași vânzător.
    """
    missing = [(text, parse_order_warning(text)) for text in order.warnings]
    sent = Counter(parsed.seller for _, parsed in missing if parsed.kind == KIND_MISSING_PAID_TOTAL)
    legitimate = Counter(b.seller for b in order.blocks if b.paid_bani is None and b.status != block_status.CANCELLED)
    cancelled = Counter(b.seller for b in order.blocks if b.paid_bani is None and b.status == block_status.CANCELLED)
    to_drop = {seller: min(cancelled[seller], max(0, count - legitimate[seller])) for seller, count in sent.items()}
    kept = []
    for text, parsed in missing:
        if parsed.kind == KIND_MISSING_PAID_TOTAL and to_drop[parsed.seller] > 0:
            to_drop[parsed.seller] -= 1
            continue
        kept.append(text)
    return kept


def returns_without_result(returns: list[ReturnRequest]) -> list[ReturnRequest]:
    """Retururile cerute care nu s-au finalizat și nici nu au fost anulate (produsul rămâne păstrat)."""
    return [r for r in returns if not r.completed and not r.cancelled]


def completed_returns_without_amount(returns: list[ReturnRequest]) -> list[ReturnRequest]:
    """Retururile finalizate la care pagina nu arată suma restituită."""
    return [r for r in returns if r.completed and r.refund_bani is None]


def _day(placed_at: str | None) -> str | None:
    """Ziua „YYYY-MM-DD” dintr-o dată ISO, sau None dacă data lipsește sau are altă formă."""
    day = (placed_at or "")[:10]
    return day if _ISO_DAY.fullmatch(day) else None


def _earliest_day(order_ids: list[str], orders_by_id: dict[str, Order]) -> str | None:
    """Cea mai veche zi cunoscută dintre comenzile date (None dacă nu se știe niciuna)."""
    known = [day for day in (_day(orders_by_id[o].placed_at) for o in order_ids if o in orders_by_id) if day]
    return min(known) if known else None


def _products_text(names: list[str], defaults: dict) -> str:
    """Numele produselor dintr-un retur, cel mult MAX_PRODUCT_NAMES_IN_TEXT, apoi „încă N”."""
    if not names:
        return defaults["produse_lipsa"]
    shown = "; ".join(names[:MAX_PRODUCT_NAMES_IN_TEXT])
    extra = len(names) - MAX_PRODUCT_NAMES_IN_TEXT
    return shown + (f"; {defaults['produse_in_plus'].format(count=extra)}" if extra > 0 else "")


def _item(order_ids, return_id, seller, status, placed_at, text, ret: ReturnRequest | None = None) -> dict:
    """Un rând al unei grupe (schema `warnings_detail`); `return_url` e o cheie în plus: adresa returului nu se
    construiește din număr, deci vine gata făcută (None dacă nu e retur sau calea lui nu e validă)."""
    return {
        "order_ids": list(order_ids),
        "return_id": return_id,
        "seller": seller,
        "status": status,
        "placed_at": placed_at,
        "text": text,
        "return_url": return_url(ret.return_id, ret.detail_path) if ret is not None else None,
    }


def _sort_key(item: dict) -> tuple:
    """Ordinea rândurilor: cronologic (fără dată la sfârșit), apoi după număr de comandă și retur."""
    first = item["order_ids"][0] if item["order_ids"] else ""
    return (item["placed_at"] is None, item["placed_at"] or "", len(first), first, item["return_id"] or "", item["text"])


def _block_status_label(order: Order | None, seller: str, labels: dict, occurrence: int) -> str | None:
    """Statusul, în română, al blocului la care se referă al `occurrence`-lea mesaj despre acel vânzător.

    Mesajul „lipsește Total platit” privește un bloc ne-anulat fără sumă; dacă vânzătorul are mai multe, se iau pe rând.
    """
    blocks = [b for b in (order.blocks if order else []) if b.seller == seller]
    candidates = [b for b in blocks if b.paid_bani is None and b.status != block_status.CANCELLED] or blocks
    if not candidates:
        return None
    chosen = candidates[min(occurrence, len(candidates) - 1)]
    return labels.get(chosen.status, chosen.status)


def _warning_item(parsed: ParsedWarning, texts: dict, orders_by_id: dict, returns_by_id: dict, seen: Counter) -> dict:
    """Rândul unui avertisment citit din text: „lipsește Total platit” sau orice alt mesaj (`seen` numără mesajele văzute)."""
    groups = texts["grupe"]
    placed = _earliest_day(list(parsed.order_ids), orders_by_id)
    if parsed.kind == KIND_MISSING_PAID_TOTAL:
        key = (parsed.order_ids[0], parsed.seller)
        order = orders_by_id.get(parsed.order_ids[0])
        status = _block_status_label(order, parsed.seller or "", texts["etichete_status"], seen[key])
        seen[key] += 1
        status = status or texts["etichete_status"].get(block_status.UNKNOWN, "")  # comanda nu e în listă: nu lăsăm paranteze goale
        text = groups[parsed.kind]["item_text"].format(seller=parsed.seller, status=status)
        return _item(parsed.order_ids, None, parsed.seller, status, placed, text)
    ret = returns_by_id.get(parsed.return_id) if parsed.return_id else None
    text = groups[KIND_OTHER]["item_text"].format(text=parsed.text)
    return _item(parsed.order_ids, parsed.return_id, parsed.seller, None, placed, text, ret)


def _return_item(ret: ReturnRequest, kind: str, texts: dict, orders_by_id: dict) -> dict:
    """Rândul unui retur (fără rezultat sau finalizat fără sumă), cu ultimul pas ca status."""
    defaults = texts["valori_implicite"]
    step = ret.steps[-1] if ret.steps else None
    fields = {
        "products": _products_text(ret.product_names, defaults),
        "step": step or defaults["pas_lipsa"],
        "mode": ret.refund_mode or defaults["mod_lipsa"],
    }
    text = texts["grupe"][kind]["item_text"].format(**{name: fields[name] for name in ITEM_TEXT_FIELDS[kind]})
    return _item(ret.order_ids, ret.return_id, None, step, _earliest_day(ret.order_ids, orders_by_id), text, ret)


def _header_item(entry: dict, texts: dict, orders_by_id: dict) -> dict:
    """Rândul unei comenzi cu totalul din antet diferit de suma blocurilor (cu cele două sume și, dacă are un bloc anulat, explicația)."""
    order = orders_by_id.get(entry["order_id"])
    template = texts["grupe"][KIND_HEADER_MISMATCH]["item_text"]
    text = template.format(header=format_lei(entry["header_bani"]), blocks=format_lei(entry["blocks_bani"]))
    if order is not None and any(block.status == block_status.CANCELLED for block in order.blocks):
        text += "; " + texts["valori_implicite"]["antet_cu_bloc_anulat"]  # cauza cea mai frecventă pe conturi reale
    return _item([entry["order_id"]], None, None, None, _day(order.placed_at) if order else None, text)


def _group(kind: str, items: list[dict], texts: dict, affects_totals: bool) -> dict:
    """O grupă gata de scris în analiza.json (rândurile sortate, `count` = numărul lor)."""
    config = texts["grupe"][kind]
    ordered = sorted(items, key=_sort_key)
    return {
        "kind": kind,
        "title": config["title"],
        "explanation": config["explanation"],
        "affects_totals": affects_totals,
        "what_to_do": config["what_to_do"],
        "count": len(ordered),
        "items": ordered,
    }


def build_warnings_detail(
    warnings: list[str],
    orders: list[Order],
    returns: list[ReturnRequest],
    header_mismatches: list[dict],
    texts: dict,
) -> list[dict]:
    """Grupele de avertismente cu rândurile lor; `header_mismatches` = `reconciliation["header_total_mismatches"]`.

    Un număr din mesajul „N retururi…” care nu se potrivește cu lista din date se scrie în jurnal; lista din date câștigă.
    """
    orders_by_id = {o.order_id: o for o in orders}
    returns_by_id = {r.return_id: r for r in returns}
    items: dict[str, list[dict]] = {kind: [] for kind in ALL_KINDS}
    stated_counts: dict[str, int] = {}
    seen_messages: Counter = Counter()
    other_affects_totals = False
    for text in warnings:
        parsed = parse_order_warning(text)
        if parsed.count is not None:  # lista acestor grupe vine din date, mai jos
            stated_counts[parsed.kind] = parsed.count
            continue
        items[parsed.kind].append(_warning_item(parsed, texts, orders_by_id, returns_by_id, seen_messages))
        other_affects_totals = other_affects_totals or (parsed.kind == KIND_OTHER and parsed.affects_totals)
    items[KIND_PENDING_RETURN] = [
        _return_item(r, KIND_PENDING_RETURN, texts, orders_by_id) for r in returns_without_result(returns)
    ]
    items[KIND_COMPLETED_RETURN_NO_REFUND] = [
        _return_item(r, KIND_COMPLETED_RETURN_NO_REFUND, texts, orders_by_id) for r in completed_returns_without_amount(returns)
    ]
    items[KIND_HEADER_MISMATCH] = [_header_item(entry, texts, orders_by_id) for entry in header_mismatches]
    for kind, stated in stated_counts.items():
        if stated != len(items[kind]):
            logger.warning("avertismentul %s spune %d, dar lista din date are %d rânduri", kind, stated, len(items[kind]))
    groups = []
    for kind in ALL_KINDS:
        if items[kind]:
            affects = texts["grupe"][kind]["affects_totals"] or (kind == KIND_OTHER and other_affects_totals)
            groups.append(_group(kind, items[kind], texts, affects))
    return groups
