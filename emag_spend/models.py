"""Structurile de date ale proiectului: produs, bloc de vânzător, comandă, retur, linie de registru.

Toate sumele sunt în BANI (int). Structurile se salvează în JSON (to_dict) și
se reîncarcă (order_from_dict / return_from_dict), ca raportul să poată fi
refăcut fără browser; câmpurile adăugate mai târziu au valori implicite, deci un
fișier salvat de o versiune veche se încarcă la fel. Nu conțin date personale
(adresă, telefon, e-mail): parserele nu le citesc.
"""

from dataclasses import asdict, dataclass, field

from emag_spend.proportional_split import split_proportionally

# Câmpurile cu bucăți pe stări ale unei linii (LineOutcome), în ordinea în care se împarte valoarea ei.
_STATE_QTY_FIELDS = ("kept_qty", "returned_qty", "cancelled_qty", "pending_qty", "paid_only_qty", "unknown_qty")


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
    # "Total de plata <vânzător>": suma de plătit, afișată în locul lui „Total platit” (de ex. la un bloc anulat).
    # Lipsește din fișierele salvate de versiunile vechi, care o puneau, greșit, în other_bani.
    due_bani: int | None = None


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
    anulate etc. Se completează în line_ledger.py, return_matcher.py și paid_totals.py.

    Invariant: kept + returned + cancelled + pending + paid_only + unknown = qty.
    Sumele pe stări există de două ori: la preț de listă (`*_bani`, din `line_total_bani`) și
    plătite (`*_paid_bani`, din `paid_value_bani`, adică după reduceri); în ambele, părțile
    stărilor se adună exact la valoarea liniei.
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
    return_ids: list[str] = field(default_factory=list)  # câte o intrare pe unitate returnată (numărul returului)
    # Valoarea liniei după partea ei din reducerile blocului (block_payment.py), niciodată negativă; None = necalculată,
    # atunci contează prețul de listă (o linie negativă, de ex. „Custom Discount”, valorează 0: e o reducere, nu un produs).
    paid_total_bani: int | None = None
    credit_returned_qty: int = 0  # din returned_qty: bucăți restituite ca voucher sau sold eMAG (banii nu s-au întors în cont)

    def _share_of(self, total_bani: int, part_qty: int) -> int:
        """Partea din `total_bani` care revine la `part_qty` din cele `qty` unități (rotunjit la cel mai apropiat ban)."""
        if self.qty <= 0:
            return 0
        return (total_bani * part_qty * 2 + self.qty) // (self.qty * 2)

    def _share(self, part_qty: int) -> int:
        """Partea din valoarea de listă a liniei care revine la `part_qty` unități (rotunjit)."""
        return self._share_of(self.line_total_bani, part_qty)

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

    # ---------- valoarea de produs la preț de listă (liniile negative sunt reduceri, deci 0) ----------

    @property
    def list_value_bani(self) -> int:
        """Prețul de listă al liniei ca produs: o linie negativă (reducere scrisă ca produs) valorează 0."""
        return max(0, self.line_total_bani)

    def _parts_of(self, total_bani: int) -> dict[str, int]:
        """`total_bani` (≥ 0) împărțit exact pe stările liniei, fără parte negativă și fără ban pierdut.

        Fiecare stare primește partea ei rotunjită la ban (ca restituirea eMAG pe bucată), iar starea „rest” (păstrat, dacă
        există, altfel cea cu cele mai multe bucăți) primește diferența. Dacă rotunjirile ar depăși totalul (posibil doar cu mai
        mult de două stări pe linie), împărțirea devine cea proporțională exactă (proportional_split.py).
        """
        qtys = {name: getattr(self, name) for name in _STATE_QTY_FIELDS}
        if self.qty <= 0 or not any(qtys.values()):
            return dict.fromkeys(qtys, 0)
        rest = "kept_qty" if qtys["kept_qty"] > 0 else max(qtys, key=lambda name: qtys[name])
        parts = {name: self._share_of(total_bani, qty) for name, qty in qtys.items() if name != rest}
        parts[rest] = total_bani - sum(parts.values())
        if parts[rest] < 0:
            parts = dict(zip(qtys, split_proportionally(total_bani, list(qtys.values()))))
        return parts

    @property
    def kept_list_bani(self) -> int:
        """Partea păstrată din `list_value_bani` (părțile stărilor se adună exact, niciuna negativă)."""
        return self._parts_of(self.list_value_bani)["kept_qty"]

    # ---------- sume plătite: după partea liniei din reducerile blocului ----------

    @property
    def paid_value_bani(self) -> int:
        """Cât s-a plătit (sau, la un bloc anulat, cât s-ar fi plătit) pe linia întreagă, după reduceri."""
        return self.paid_total_bani if self.paid_total_bani is not None else self.list_value_bani

    @property
    def returned_paid_bani(self) -> int:
        """Partea plătită a bucăților returnate (cu bani înapoi sau cu voucher/sold)."""
        return self._parts_of(self.paid_value_bani)["returned_qty"]

    @property
    def cancelled_paid_bani(self) -> int:
        """Partea plătită (la un bloc anulat: cât s-ar fi plătit) a bucăților anulate."""
        return self._parts_of(self.paid_value_bani)["cancelled_qty"]

    @property
    def pending_paid_bani(self) -> int:
        """Partea plătită a bucăților încă în curs (nelivrate)."""
        return self._parts_of(self.paid_value_bani)["pending_qty"]

    @property
    def paid_only_paid_bani(self) -> int:
        """Partea plătită a bucăților plătite fără livrare de produs (de ex. asigurări)."""
        return self._parts_of(self.paid_value_bani)["paid_only_qty"]

    @property
    def unknown_paid_bani(self) -> int:
        """Partea plătită a bucăților cu status nerecunoscut."""
        return self._parts_of(self.paid_value_bani)["unknown_qty"]

    @property
    def kept_paid_bani(self) -> int:
        """Partea păstrată din valoarea plătită (părțile stărilor se adună exact la `paid_value_bani`, niciuna negativă)."""
        return self._parts_of(self.paid_value_bani)["kept_qty"]


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
