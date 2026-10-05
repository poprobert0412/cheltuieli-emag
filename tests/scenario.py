"""Scenariu inventat de comenzi și retururi, folosit de testele de analiză.

Cifrele sunt alese ca rezultatele să se poată verifica cu mâna. Toate
sumele sunt în bani. Detaliul fiecărei comenzi e în comentariul ei.
"""

from emag_spend import block_status
from emag_spend.classifier import Classifier
from emag_spend.models import Item, Order, ReturnRequest, SellerBlock

RULES = {
    "default_category": "Necategorizat",
    "categories": [
        {"name": "Televizoare", "patterns": [r"\btelevizor"]},
        {"name": "Alcool", "patterns": [r"\bwhisk(?:y|ey)\b"]},
        {"name": "Diverse", "patterns": ["."]},
    ],
}


def classifier() -> Classifier:
    return Classifier(RULES)


def _block(status, items, paid=None, vouchers=None, seller="eMAG", storno=False):
    total = sum(i.line_total_bani for i in items)
    return SellerBlock(
        seller=seller, status=status, status_text=status, has_storno=storno, items=items,
        products_total_bani=total, vouchers_bani=vouchers or [], shipping_bani=0, services_bani=[],
        paid_bani=total + sum(vouchers or []) if paid is None else paid,
    )


def _order(order_id, placed, blocks):
    header = sum(b.paid_bani or 0 for b in blocks)
    return Order(order_id, placed, placed, header, blocks)


def orders() -> list[Order]:
    return [
        # A (2024): televizor 2000 + whisky 100, voucher -50 => plătit 2050
        _order("A", "2024-03-10T10:00", [_block(block_status.DELIVERED, [Item("Televizor Alfa 55 inch", 200000, 1), Item("Whisky Test 0.7L", 10000, 1)], vouchers=[-5000])]),
        # B (2025): 2 huse a 30 = 60, una returnată
        _order("B", "2025-06-01T10:00", [_block(block_status.DELIVERED, [Item("Husa telefon X", 6000, 2)])]),
        # C (2025): marketplace anulat 700
        _order("C", "2025-07-01T10:00", [_block(block_status.CANCELLED, [Item("Ceva scump", 70000, 1)], seller="Alfa SRL")]),
        # D (2026): marketplace marcat anulat dar returnat (150)
        _order("D", "2026-01-01T10:00", [_block(block_status.CANCELLED, [Item("Rucsac Test", 15000, 1)], seller="Beta SRL")]),
        # E (2026): în curs, whisky 80
        _order("E", "2026-02-01T10:00", [_block(block_status.IN_PROGRESS, [Item("Whisky nou 0.7L", 8000, 1)])]),
        # F (2026): asigurare plătită fără livrare 500
        _order("F", "2026-03-01T10:00", [_block(block_status.PAID_ONLY, [Item("Asigurare Test", 50000, 1)], seller="eMAG Asigurari")]),
        # G (2026): laptop exact 500,00 (nu depășește pragul) + monitor 500,01 (depășește)
        _order("G", "2026-04-01T10:00", [_block(block_status.DELIVERED, [Item("Laptop Test", 50000, 1), Item("Monitor Test", 50001, 1)])]),
    ]


def returns() -> list[ReturnRequest]:
    return [
        ReturnRequest("R1", "/user/return-history/1/R1", ["B"], ["Husa telefon X"], ["Restituire suma"], 3000, "Vreau banii inapoi", True, False),
        ReturnRequest("R2", "/user/return-history/1/R2", ["D"], ["Rucsac Test"], ["Restituire suma"], 15000, "Vreau banii inapoi", True, False),
        ReturnRequest("R3", "/user/return-history/1/R3", ["A"], ["Whisky Test 0.7L"], ["Cerere anulata"], None, "Vreau banii inapoi", False, True),
    ]
