"""Generator de comenzi și retururi INVENTATE, pentru a vedea raportul fără cont eMAG.

Primește: o sămânță (seed) și câte comenzi „de umplutură” să adauge. Dă înapoi
(comenzi, retururi) deterministe: comenzile scrise de mână din demo_scenario.py
(acoperă garantat orice caz din raport, la orice seed) plus comenzi obișnuite
alese cu seed-ul din demo_catalog.py, pe ani 2017-2026.
Folosit de `python ruleaza.py --demo`, de site_demo_writer.py și de teste.
Nicio dată reală; nu scrie fișiere și nu calculează totaluri (le face spend_analysis).
"""

import random
from typing import Sequence, TypeVar

from emag_spend import block_status
from emag_spend.demo_builder import EMAG_SELLER, BlockPlan, LinePlan, OrderPlan, ReturnPlan, build_orders_and_returns
from emag_spend.demo_catalog import FILLER_FAMILIES, MARKETPLACE_SELLERS, CatalogItem
from emag_spend.demo_scenario import scripted_plans
from emag_spend.models import Order, ReturnRequest

T = TypeVar("T")

DEMO_SEED = 7
DEFAULT_FILLER_ORDERS = 120

# „Azi” în lumea demonstrației: ora generării din demo-data.js e FIXĂ ca fișierul să
# fie același la orice rulare (testul de prospețime îl compară cu ce generează Python).
# Comenzile inventate se opresc înainte de această dată.
DEMO_GENERATED_AT = "2026-10-04 12:00"
_LAST_YEAR, _LAST_MONTH = 2026, 9

# Câte comenzi obișnuite pică în fiecare an (greutăți relative): crescător, cu mai
# multe în 2020-2021, ca graficul pe ani să nu fie plat. Numărul pe an se împarte exact
# după aceste greutăți (fără zaruri), ca să nu iasă ani goi sau supraîncărcați din întâmplare.
_YEAR_WEIGHTS = ((2017, 3), (2018, 5), (2019, 8), (2020, 12), (2021, 14),
                 (2022, 12), (2023, 12), (2024, 13), (2025, 12), (2026, 8))

# Probabilități pentru comenzile obișnuite (valori alese de ochi ca rezultatul să semene
# cu un cont real: puține anulări, retururi rare, vouchere ocazionale).
_LINES_PER_ORDER = (1, 1, 1, 2, 2, 3)
_P_MARKETPLACE_ORDER = 0.27  # comanda e de la un vânzător marketplace
_P_SPLIT_ORDER = 0.30  # comanda are două blocuri: eMAG + marketplace
_P_CANCEL_EMAG = 0.03  # eMAG anulează blocul (de ex. stoc epuizat)
_P_CANCEL_MARKETPLACE = 0.12  # marketplace anulează mai des
_P_PICKUP = 0.20  # produse ridicate, nu livrate
_P_VOUCHER = 0.20
_VOUCHER_RANGE_BANI = (500, 5000)
_VOUCHER_MAX_SHARE_DIVISOR = 4  # voucherul nu depășește un sfert din produsele blocului
_P_SERVICES = 0.25  # „Servicii operationale” pe blocurile eMAG
_SERVICE_FEE_BANI = 149
_P_RETURN = 0.10  # dintr-un bloc livrat se cere un retur
_P_RETURN_CANCELLED = 0.12  # cererea de retur e anulată de client
_P_RETURN_AS_VOUCHER = 0.15  # restituirea se face prin voucher, nu în bani
_P_MARKED_CANCELLED = 0.5  # marketplace: eMAG marchează blocul returnat „Livrare anulată”
_PRICE_ENDINGS_BANI = (1, 1, 1, 10, 10, 0)  # cât se scade din lei întregi: ,99 / ,90 / ,00
# Un produs al cărui preț maxim atinge pragul de mai jos apare o singură dată în tot contul
# (nimeni nu cumpără de șase ori același telefon): comenzile obișnuite sar peste cele deja
# cumpărate, inclusiv în scenariul scris de mână.
_ONE_TIME_FROM_LEI = 800


class _Dice:
    """Zaruri deterministe. Folosește DOAR `random()` din `Random(seed)`, singura
    metodă a cărei secvență Python o garantează stabilă între versiuni (randint/choice nu).
    """

    def __init__(self, seed: int):
        """Pornește generatorul cu `seed`."""
        self._rng = random.Random(seed)

    def chance(self, probability: float) -> bool:
        """True cu probabilitatea dată."""
        return self._rng.random() < probability

    def between(self, low: int, high: int) -> int:
        """Întreg între `low` și `high`, inclusiv."""
        return low + int(self._rng.random() * (high - low + 1))

    def pick(self, options: Sequence[T]) -> T:
        """Un element din secvență, cu șanse egale."""
        return options[int(self._rng.random() * len(options))]

    def weighted(self, pairs: Sequence[tuple[T, int]]) -> T:
        """Un element din perechi (valoare, greutate), proporțional cu greutatea."""
        threshold = self._rng.random() * sum(weight for _, weight in pairs)
        running = 0
        for value, weight in pairs:
            running += weight
            if threshold < running:
                return value
        return pairs[-1][0]


def _years_for(n_orders: int) -> list[int]:
    """Un an pentru fiecare comandă obișnuită, împărțit proporțional cu `_YEAR_WEIGHTS`.

    Metoda celui mai mare rest: fiecare an primește partea întreagă, iar comenzile rămase
    merg la anii cu cele mai mari resturi (la egalitate, anul mai nou).
    """
    total = sum(weight for _, weight in _YEAR_WEIGHTS)
    counts = {year: n_orders * weight // total for year, weight in _YEAR_WEIGHTS}
    by_remainder = sorted(_YEAR_WEIGHTS, key=lambda yw: (-(n_orders * yw[1] % total), -yw[0]))
    for year, _ in by_remainder[: n_orders - sum(counts.values())]:
        counts[year] += 1
    return [year for year, _ in _YEAR_WEIGHTS for _ in range(counts[year])]


def _random_date(dice: _Dice, year: int) -> str:
    """Data și ora unei comenzi obișnuite din `year`, ISO "YYYY-MM-DDTHH:MM", înainte de DEMO_GENERATED_AT."""
    month = dice.between(1, _LAST_MONTH if year == _LAST_YEAR else 12)
    return f"{year}-{month:02d}-{dice.between(1, 28):02d}T{dice.between(7, 22):02d}:{dice.between(0, 59):02d}"


def _unit_price_bani(dice: _Dice, item: CatalogItem) -> int:
    """Preț pe bucată în bani, cu terminație de preț de magazin (,99 / ,90 / ,00)."""
    lei = dice.between(item.low_lei, item.high_lei)
    if item.low_lei == item.high_lei:  # preț fix (de ex. card cadou)
        return lei * 100
    return lei * 100 - dice.pick(_PRICE_ENDINGS_BANI)


def _random_lines(dice: _Dice, bought: set[str]) -> list[LinePlan]:
    """1-3 produse distincte din familiile catalogului, cu preț și cantitate.

    `bought` = numele deja cumpărate; se completează cu produsele scumpe alese acum.
    """
    wanted = dice.pick(_LINES_PER_ORDER)
    family_weights = [(family, FILLER_FAMILIES[family].weight) for family in FILLER_FAMILIES]
    lines: list[LinePlan] = []
    while len(lines) < wanted:
        family = FILLER_FAMILIES[dice.weighted(family_weights)]
        item = dice.pick(family.items)
        if any(line.name == item.name for line in lines):
            continue  # același produs de două ori în aceeași comandă nu are sens
        expensive = item.high_lei >= _ONE_TIME_FROM_LEI
        if expensive and item.name in bought:
            continue
        if expensive:
            bought.add(item.name)
        lines.append(LinePlan(item.name, _unit_price_bani(dice, item), dice.pick(family.qty_options)))
    return lines


def _block_plan(dice: _Dice, seller: str, lines: list[LinePlan]) -> BlockPlan:
    """Un bloc: anulat, sau livrat (cu eventual voucher, serviciu, ridicare)."""
    cancel = _P_CANCEL_EMAG if seller == EMAG_SELLER else _P_CANCEL_MARKETPLACE
    if dice.chance(cancel):
        return BlockPlan(seller, block_status.CANCELLED, lines)
    products = sum(line.unit_bani * line.qty for line in lines)
    voucher = 0
    if dice.chance(_P_VOUCHER) and products // _VOUCHER_MAX_SHARE_DIVISOR >= _VOUCHER_RANGE_BANI[0]:
        voucher = min(dice.between(*_VOUCHER_RANGE_BANI), products // _VOUCHER_MAX_SHARE_DIVISOR)
    services = (_SERVICE_FEE_BANI,) if seller == EMAG_SELLER and dice.chance(_P_SERVICES) else ()
    return BlockPlan(seller, block_status.DELIVERED, lines, voucher_bani=voucher,
                     services_bani=services, pickup=dice.chance(_P_PICKUP))


def _blocks_for(dice: _Dice, lines: list[LinePlan]) -> list[BlockPlan]:
    """Împarte produsele pe vânzători: de obicei un singur bloc, uneori eMAG + marketplace."""
    marketplace_order = dice.chance(_P_MARKETPLACE_ORDER)
    seller = dice.pick(MARKETPLACE_SELLERS) if marketplace_order else EMAG_SELLER
    if len(lines) >= 2 and dice.chance(_P_SPLIT_ORDER):
        return [_block_plan(dice, EMAG_SELLER, lines[:-1]), _block_plan(dice, dice.pick(MARKETPLACE_SELLERS), lines[-1:])]
    return [_block_plan(dice, seller, lines)]


def _maybe_return(dice: _Dice, order: OrderPlan, block: BlockPlan) -> ReturnPlan | None:
    """Uneori cere retur pentru o bucată din blocul livrat; modifică blocul (storno, „anulat de eMAG”)."""
    if block.status != block_status.DELIVERED or not dice.chance(_P_RETURN):
        return None
    line = dice.pick(block.lines)
    if dice.chance(_P_RETURN_CANCELLED):
        return ReturnPlan(order, (line.name,), outcome="cancelled")
    mode = "Emitere voucher" if dice.chance(_P_RETURN_AS_VOUCHER) else "Vreau banii inapoi"
    block.storno = True
    # La marketplace, eMAG marchează „Livrare anulata” blocul returnat integral (o singură bucată).
    if block.seller != EMAG_SELLER and len(block.lines) == 1 and line.qty == 1 and dice.chance(_P_MARKED_CANCELLED):
        block.status = block_status.CANCELLED
    return ReturnPlan(order, (line.name,), mode=mode)


def _filler_plans(dice: _Dice, n_orders: int, bought: set[str]) -> tuple[list[OrderPlan], list[ReturnPlan]]:
    """`n_orders` comenzi obișnuite (și retururile lor), alese cu `dice`; `bought` = nume deja cumpărate."""
    plans: list[OrderPlan] = []
    returns: list[ReturnPlan] = []
    for year in _years_for(n_orders):
        placed_at = _random_date(dice, year)
        plan = OrderPlan(placed_at, _blocks_for(dice, _random_lines(dice, bought)))
        plans.append(plan)
        for block in plan.blocks:
            planned_return = _maybe_return(dice, plan, block)
            if planned_return:
                returns.append(planned_return)
    return plans, returns


def demo_orders_and_returns(
    seed: int = DEMO_SEED, n_orders: int = DEFAULT_FILLER_ORDERS
) -> tuple[list[Order], list[ReturnRequest]]:
    """Generează (comenzi, retururi) deterministe: cele scrise de mână + `n_orders` obișnuite din `seed`."""
    scripted_orders, scripted_returns = scripted_plans()
    bought = {line.name for plan in scripted_orders for block in plan.blocks for line in block.lines}
    filler_orders, filler_returns = _filler_plans(_Dice(seed), n_orders, bought)
    return build_orders_and_returns(scripted_orders + filler_orders, scripted_returns + filler_returns)
