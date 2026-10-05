"""Construiește registrul de linii (LineOutcome) din comenzile citite.

Primește: lista de comenzi. Dă înapoi: câte o `LineOutcome` pentru fiecare
produs, cu starea de pornire dedusă din statusul blocului (livrat -> păstrat,
anulat -> anulat, în curs -> în curs, plătit fără livrare, necunoscut).
Retururile se aplică ulterior (return_matcher.py). Nu calculează totaluri.
"""

from emag_spend import block_status
from emag_spend.models import LineOutcome, Order

_STATE_FIELD = {
    block_status.DELIVERED: "kept_qty",
    block_status.CANCELLED: "cancelled_qty",
    block_status.IN_PROGRESS: "pending_qty",
    block_status.PAID_ONLY: "paid_only_qty",
    block_status.UNKNOWN: "unknown_qty",
}


def build_lines(orders: list[Order]) -> list[LineOutcome]:
    """O linie de registru pentru fiecare produs din fiecare bloc de comandă."""
    lines: list[LineOutcome] = []
    for order in orders:
        for block in order.blocks:
            for item in block.items:
                line = LineOutcome(
                    order_id=order.order_id,
                    placed_at=order.placed_at,
                    seller=block.seller,
                    name=item.name,
                    qty=item.qty,
                    line_total_bani=item.line_total_bani,
                    block_status=block.status,
                )
                setattr(line, _STATE_FIELD.get(block.status, "unknown_qty"), item.qty)
                lines.append(line)
    return lines
