"""Transformă planuri de comenzi inventate în `Order` / `ReturnRequest` coerente.

Primește: planuri (`OrderPlan`, `ReturnPlan`) scrise de demo_scenario.py și demo_data.py: doar produse, prețuri, stări, vouchere.
Dă înapoi: (comenzi, retururi) cu totaluri care se leagă (produse = „Total produse”; plătit = componente; antet = suma blocurilor),
numere de comandă și de retur unice, în ordine cronologică. Planul poate cere „defecte” realiste, ca raportul să arate
avertismentele: bloc fără „Total plătit” (`paid_shown=False`), antet ≠ suma blocurilor (`header_extra_bani`), retur
finalizat fără sumă (`refund_shown=False`). Nu alege produse și nu folosește numere aleatoare: tot ce e variabil vine din plan.
"""

from dataclasses import dataclass

from emag_spend import block_status, warning_messages
from emag_spend.models import Item, Order, ReturnRequest, SellerBlock

EMAG_SELLER = "eMAG"

# Valori INVENTATE pentru demonstrație (nu sunt tarifele reale eMAG): transport
# gratuit de la 150 Lei produse, altfel o taxă diferită pentru eMAG și marketplace.
SHIPPING_FREE_FROM_BANI = 15_000
SHIPPING_FEE_EMAG_BANI = 1_499
SHIPPING_FEE_MARKETPLACE_BANI = 1_999

# Numerele de comandă și de retur pornesc de la valori verosimile și cresc cu pași
# neregulați, ca să arate ca niște numere reale (și să iasă crescătoare în timp).
_ORDER_ID_START = 100_000_000
_RETURN_ID_START = 3_000_000

_MONTHS_RO = ("ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
              "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie")

# Textele de status de la care block_status.classify_status() dă înapoi exact starea cerută.
_DEFAULT_STATUS_TEXT = {
    block_status.DELIVERED: "Produse livrate",
    block_status.CANCELLED: "Livrare anulata",
    block_status.IN_PROGRESS: "Comanda plasata",
    block_status.PAID_ONLY: "Plata acceptata",
}
_PICKUP_STATUS_TEXT = "Produse ridicate"

# Pașii cu dată dintr-un retur, după rezultat (aceleași titluri ca la return_parser).
RETURN_STEPS = {
    "completed": ["Cerere inregistrata", "Receptionare produs", "Restituire suma"],
    "cancelled": ["Cerere inregistrata", "Cerere anulata"],
    "pending": ["Cerere inregistrata", "Receptionare produs"],
}


@dataclass(frozen=True)
class LinePlan:
    """Un produs dorit: nume, preț pe bucată (bani) și cantitate."""

    name: str
    unit_bani: int
    qty: int = 1


@dataclass
class BlockPlan:
    """Un bloc de vânzător dorit. `voucher_bani` e reducerea ca număr pozitiv."""

    seller: str
    status: str  # o constantă din block_status.py
    lines: list[LinePlan]
    voucher_bani: int = 0
    services_bani: tuple[int, ...] = ()  # "Servicii operationale"
    other_bani: tuple[int, ...] = ()  # alte taxe
    pickup: bool = False  # "Produse ridicate" în loc de "Produse livrate"
    storno: bool = False  # există "Factura storno"
    status_text: str | None = None  # None = textul implicit al stării
    paid_shown: bool = True  # False = pagina nu arată "Total platit" pentru acest bloc (apare avertisment)


@dataclass
class OrderPlan:
    """O comandă dorită: data plasării (ISO "YYYY-MM-DDTHH:MM") și blocurile ei.

    `header_extra_bani` = cât adaugă (sau scade, dacă e negativ) totalul din antet față de suma
    blocurilor; 0 = se potrivesc (cazul normal). Un număr nenul produce avertismentul „totalul din antet ≠ suma blocurilor”.
    """

    placed_at: str
    blocks: list[BlockPlan]
    header_extra_bani: int = 0


@dataclass
class ReturnPlan:
    """Un retur dorit pentru produsele `names` (câte o intrare pe bucată) dintr-o comandă.

    `outcome`: "completed" (restituit), "cancelled" (cerere anulată) sau "pending"
    (cerere fără rezultat). La "completed" suma restituită e prețul produselor.
    """

    order: OrderPlan
    names: tuple[str, ...]
    outcome: str = "completed"
    mode: str = "Vreau banii inapoi"
    refund_shown: bool = True  # False = returul e finalizat, dar pagina nu arată suma restituită


def _placed_text(placed_at: str) -> str:
    """"2021-05-15T12:34" -> "15 mai 2021, 12:34" (forma din paginile eMAG)."""
    date, _, time = placed_at.partition("T")
    year, month, day = date.split("-")
    return f"{int(day)} {_MONTHS_RO[int(month) - 1]} {int(year)}, {time}"


def _shipping_bani(plan: BlockPlan, products_bani: int) -> int:
    """Transportul unui bloc: 0 la servicii fără livrare sau peste pragul gratuit, altfel taxa vânzătorului."""
    if plan.status == block_status.PAID_ONLY or products_bani >= SHIPPING_FREE_FROM_BANI:
        return 0
    return SHIPPING_FEE_EMAG_BANI if plan.seller == EMAG_SELLER else SHIPPING_FEE_MARKETPLACE_BANI


def _make_block(plan: BlockPlan) -> SellerBlock:
    """Construiește `SellerBlock`. Un bloc anulat arată ca în eMAG: total plătit 0, fără costuri."""
    items = [Item(line.name, line.unit_bani * line.qty, line.qty) for line in plan.lines]
    products = sum(item.line_total_bani for item in items)
    if plan.status == block_status.CANCELLED:
        vouchers: list[int] = []
        shipping, services, other, paid = 0, [], [], 0
    else:
        vouchers = [-plan.voucher_bani] if plan.voucher_bani else []
        shipping = _shipping_bani(plan, products)
        services, other = list(plan.services_bani), list(plan.other_bani)
        paid = products + sum(vouchers) + shipping + sum(services) + sum(other)
    default_text = _PICKUP_STATUS_TEXT if plan.pickup and plan.status == block_status.DELIVERED \
        else _DEFAULT_STATUS_TEXT[plan.status]
    return SellerBlock(
        seller=plan.seller,
        status=plan.status,
        status_text=plan.status_text or default_text,
        has_storno=plan.storno,
        items=items,
        products_total_bani=products,
        vouchers_bani=vouchers,
        shipping_bani=shipping,
        services_bani=services,
        other_bani=other,
        paid_bani=paid if plan.paid_shown else None,
    )


def _make_order(order_id: str, plan: OrderPlan) -> Order:
    """Construiește `Order`; totalul din antet lipsește când toate blocurile sunt anulate (ca în eMAG).

    Un bloc ne-anulat fără „Total platit” primește pe comandă același avertisment ca la citirea paginii.
    """
    blocks = [_make_block(block) for block in plan.blocks]
    all_cancelled = all(block.status == block_status.CANCELLED for block in blocks)
    header = None if all_cancelled else sum(block.paid_bani or 0 for block in blocks) + plan.header_extra_bani
    warnings = [
        warning_messages.format_missing_paid_total(order_id, block.seller)
        for block in blocks if block.paid_bani is None and block.status != block_status.CANCELLED
    ]
    return Order(order_id, _placed_text(plan.placed_at), plan.placed_at, header, blocks, warnings)


def _refund_bani(plan: ReturnPlan) -> int:
    """Suma restituită = prețul pe bucată al fiecărui produs returnat. Ridică ValueError dacă produsul nu e în comandă."""
    total = 0
    for name in plan.names:
        unit = next((line.unit_bani for block in plan.order.blocks for line in block.lines if line.name == name), None)
        if unit is None:
            raise ValueError(f"produsul {name!r} din retur nu e în comanda din {plan.order.placed_at}")
        total += unit
    return total


def build_orders_and_returns(
    plans: list[OrderPlan], return_plans: list[ReturnPlan]
) -> tuple[list[Order], list[ReturnRequest]]:
    """Comenzile și retururile finale, sortate cronologic, cu numere unice.

    Ridică ValueError dacă un retur trimite la o comandă care nu e în `plans`.
    """
    chronological = sorted(range(len(plans)), key=lambda i: (plans[i].placed_at, i))
    order_ids: dict[int, str] = {}
    orders: list[Order] = []
    for position, index in enumerate(chronological):
        plan = plans[index]
        order_id = str(_ORDER_ID_START + position * 937 + (position * position * 7) % 311)
        order_ids[id(plan)] = order_id
        orders.append(_make_order(order_id, plan))

    returns: list[ReturnRequest] = []
    ordered_returns = sorted(range(len(return_plans)), key=lambda i: (return_plans[i].order.placed_at, i))
    for n, index in enumerate(ordered_returns):
        plan = return_plans[index]
        if id(plan.order) not in order_ids:
            raise ValueError("un retur trimite la o comandă care nu face parte din lista de comenzi")
        return_id = str(_RETURN_ID_START + n * 1291 + (n * n * 5) % 401)
        completed = plan.outcome == "completed"
        returns.append(ReturnRequest(
            return_id=return_id,
            detail_path=f"/user/return-history/1/{return_id}",
            order_ids=[order_ids[id(plan.order)]],
            product_names=list(plan.names),
            steps=list(RETURN_STEPS[plan.outcome]),
            refund_bani=_refund_bani(plan) if completed and plan.refund_shown else None,
            refund_mode=plan.mode,
            completed=completed,
            cancelled=plan.outcome == "cancelled",
        ))
    return orders, returns
