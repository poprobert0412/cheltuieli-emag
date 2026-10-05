"""Structurile de date ale proiectului: produs, bloc de vânzător, comandă, retur.

Toate sumele sunt în BANI (int). Structurile se salvează în JSON (to_dict) și
se reîncarcă (order_from_dict / return_from_dict), ca raportul să poată fi
refăcut fără browser. Nu conțin date personale (adresă, telefon, e-mail):
parserele nu le citesc.
"""

from dataclasses import asdict, dataclass, field


@dataclass
class Item:
    """O linie de produs dintr-o comandă. `line_total_bani` = total pe linie
    (preț × cantitate)."""

    name: str
    line_total_bani: int
    qty: int


@dataclass
class SellerBlock:
    """Un bloc de comandă livrat de un vânzător (eMAG sau marketplace)."""

    seller: str
    status: str  # una dintre constantele din block_status.py
    status_text: str  # liniile de status originale, lipite cu " | "
    has_storno: bool  # există "Factura storno" (semn de retur/anulare facturată)
    items: list[Item] = field(default_factory=list)
    products_total_bani: int | None = None  # "Total produse"
    vouchers_bani: list[int] = field(default_factory=list)  # reduceri (negative)
    shipping_bani: int | None = None  # "Cost livrare"
    services_bani: list[int] = field(default_factory=list)  # "Servicii operationale"
    other_bani: list[int] = field(default_factory=list)  # alte taxe necunoscute
    paid_bani: int | None = None  # "Total platit <vânzător>"


@dataclass
class Order:
    """O comandă cu toate blocurile ei. `warnings` = nepotriviri găsite la parsare."""

    order_id: str
    placed_text: str
    placed_at: str | None  # ISO "YYYY-MM-DDTHH:MM"
    header_total_bani: int | None  # "Total" din antet (lipsește la anulate)
    blocks: list[SellerBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def year(self) -> int | None:
        return int(self.placed_at[:4]) if self.placed_at else None


@dataclass
class ReturnRequest:
    """O cerere de retur, cu starea ei finală."""

    return_id: str
    detail_path: str
    order_ids: list[str]
    product_names: list[str]
    steps: list[str]  # titlurile pașilor din "Status retur"
    refund_bani: int | None  # suma anunțată ca restituită
    refund_mode: str  # "Vreau banii inapoi", "Emitere voucher", ...
    completed: bool  # s-a ajuns la "Restituire suma"
    cancelled: bool  # cererea a fost anulată (și nu s-a restituit nimic)


@dataclass
class LineOutcome:
    """Soarta unei linii de produs: câte unități au fost păstrate, returnate,
    anulate etc. Se completează în line_ledger.py și return_matcher.py.

    Invariant: kept + returned + cancelled + pending + paid_only + unknown = qty.
    """

    order_id: str
    placed_at: str | None
    seller: str
    name: str
    qty: int
    line_total_bani: int
    block_status: str
    kept_qty: int = 0
    returned_qty: int = 0
    cancelled_qty: int = 0
    pending_qty: int = 0
    paid_only_qty: int = 0
    unknown_qty: int = 0
    returned_from_cancelled_qty: int = 0  # returnate, dar marcate "anulat" de eMAG
    category: str = ""
    rule: str = ""
    return_ids: list[str] = field(default_factory=list)

    def _share(self, part_qty: int) -> int:
        """Partea din valoarea liniei care revine la `part_qty` unități (rotunjit)."""
        if self.qty <= 0:
            return 0
        return (self.line_total_bani * part_qty * 2 + self.qty) // (self.qty * 2)

    @property
    def returned_bani(self) -> int:
        return self._share(self.returned_qty)

    @property
    def cancelled_bani(self) -> int:
        return self._share(self.cancelled_qty)

    @property
    def pending_bani(self) -> int:
        return self._share(self.pending_qty)

    @property
    def paid_only_bani(self) -> int:
        return self._share(self.paid_only_qty)

    @property
    def unknown_bani(self) -> int:
        return self._share(self.unknown_qty)

    @property
    def kept_bani(self) -> int:
        """Restul valorii liniei (garantează că suma părților = totalul liniei)."""
        return (
            self.line_total_bani
            - self.returned_bani
            - self.cancelled_bani
            - self.pending_bani
            - self.paid_only_bani
            - self.unknown_bani
        )


def to_dict(obj) -> dict:
    """Dicționar JSON-serializabil pentru orice structură de mai sus."""
    return asdict(obj)


def order_from_dict(data: dict) -> Order:
    """Reconstruiește o comandă salvată cu to_dict()."""
    blocks = []
    for block in data["blocks"]:
        items = [Item(**item) for item in block["items"]]
        blocks.append(SellerBlock(**{**block, "items": items}))
    return Order(**{**data, "blocks": blocks})


def return_from_dict(data: dict) -> ReturnRequest:
    """Reconstruiește un retur salvat cu to_dict()."""
    return ReturnRequest(**data)
