"""Ce s-a plătit într-un bloc de vânzător și cum se împarte: produsele, pe linii (după reduceri), și transportul cu taxele.

Primește: un `SellerBlock`. Dă înapoi: `BlockPayment` cu suma blocului, partea produselor pe fiecare linie, transportul
și taxele, reducerile care revin produselor și de unde vine suma (afișată de eMAG sau calculată din componente).
Reguli: la un bloc taxat (livrat, în curs, status necunoscut, plătit fără livrare) suma e „Total platit”; dacă pagina
nu o arată, se calculează din componente (produse + reduceri + transport + servicii + alte taxe). Transportul și taxele
nu se împart pe produse. Reducerile (vouchere, card cadou, linii negative de tip „Custom Discount”) se împart pe produse
proporțional cu prețul lor de listă, în bani întregi (proportional_split.py); un voucher mai mare decât produsele acoperă
și din transport. La un bloc ANULAT nu s-a plătit nimic (sau s-a restituit): valoarea produselor e prețul minus reducerile.
Ce NU face: nu știe de retururi și nu adună pe categorii (paid_totals.py, spend_analysis.py).
"""

from dataclasses import dataclass

from emag_spend import block_status
from emag_spend.models import SellerBlock
from emag_spend.proportional_split import split_proportionally

# De unde vine suma blocului: „Total platit” afișat de eMAG; calculată din componente (bloc taxat fără „Total platit”);
# sau, la un bloc anulat, valoarea produselor după reduceri (ce s-ar fi plătit), fără transport.
PAID_SHOWN = "total_platit"
PAID_FROM_COMPONENTS = "componente"
NOT_CHARGED = "anulat"


@dataclass(frozen=True)
class BlockPayment:
    """Împărțirea sumei unui bloc. Invariant: sum(line_paid_bani) + fees_bani == paid_bani, iar fiecare linie e între 0 și
    prețul ei de listă (o linie negativă valorează 0: e o reducere, nu un produs)."""

    paid_bani: int  # suma plătită a blocului (la un bloc anulat: valoarea produselor după reduceri)
    source: str  # PAID_SHOWN, PAID_FROM_COMPONENTS sau NOT_CHARGED
    list_bani: int  # prețul de listă al produselor (doar liniile pozitive)
    products_paid_bani: int  # partea produselor, după reduceri
    fees_bani: int  # transport și taxe: partea sumei care nu revine produselor
    discount_bani: int  # reducerile care revin produselor: list_bani − products_paid_bani (≥ 0)
    line_paid_bani: tuple[int, ...]  # partea plătită a fiecărui produs, în ordinea din block.items


def _declared_fees(block: SellerBlock) -> int:
    """Transportul, serviciile operaționale și celelalte taxe afișate în bloc."""
    return (block.shipping_bani or 0) + sum(block.services_bani) + sum(block.other_bani)


def block_payment(block: SellerBlock) -> BlockPayment:
    """Suma blocului și împărțirea ei pe produse (după reduceri) și pe transport cu taxe (vezi antetul modulului)."""
    list_values = [max(0, item.line_total_bani) for item in block.items]
    list_total = sum(list_values)
    lines_total = sum(item.line_total_bani for item in block.items)  # cu liniile negative (reduceri scrise ca produs)
    if block.status == block_status.CANCELLED:
        products_paid = min(max(lines_total + sum(block.vouchers_bani), 0), list_total)
        paid, source, fees = products_paid, NOT_CHARGED, 0
    else:
        declared_fees = _declared_fees(block)
        if block.paid_bani is not None:
            paid, source = block.paid_bani, PAID_SHOWN
        else:
            paid, source = lines_total + sum(block.vouchers_bani) + declared_fees, PAID_FROM_COMPONENTS
        # Produsele primesc ce rămâne după taxe, cel mult prețul lor de listă: un voucher mai mare decât produsele
        # scade și din transport, iar o sumă plătită peste produse + taxe (o taxă nerecunoscută) rămâne la taxe.
        products_paid = min(max(paid - declared_fees, 0), list_total)
        fees = paid - products_paid
    discount = list_total - products_paid
    shares = split_proportionally(discount, list_values)
    return BlockPayment(
        paid_bani=paid,
        source=source,
        list_bani=list_total,
        products_paid_bani=products_paid,
        fees_bani=fees,
        discount_bani=discount,
        line_paid_bani=tuple(value - share for value, share in zip(list_values, shares)),
    )
