"""Comenzile demonstrative scrise de mână: acoperă garantat fiecare caz din raport.

Primește: nimic. Dă înapoi: (planuri de comenzi, planuri de retur) INVENTATE, la fel la orice seed: televizoare
(păstrat, returnat, anulat, în curs), alcool, retur marcat „Livrare anulată”, asigurare fără livrare, produse la și peste
prag, marketplace, necategorizate, retur finalizat / anulat / fără rezultat. Pentru „Prețuri la același produs”: același
model în două culori (se unește), capacități diferite (NU se unesc), un produs mai ieftin și unul mai scump la ultima
cumpărare. Pentru avertismente: bloc fără „Total plătit”, trei antete ≠ suma blocurilor (una cu bloc anulat), retur
finalizat fără sumă. Nu calculează cifre agregate (le face spend_analysis) și nu pune numere de comandă.
"""

from emag_spend import block_status
from emag_spend.demo_builder import EMAG_SELLER, BlockPlan, LinePlan, OrderPlan, ReturnPlan
from emag_spend.demo_catalog import MARKETPLACE_SELLERS

STELARIS, NORDHAUS, AURELIAN, DUNAREA, CASA_VERDE, ZORILOR = MARKETPLACE_SELLERS
INSURER = "eMAG Asigurari"

# Produsele fără regulă în config/categorii.json: apar la „Necategorizat” și produc avertismentul.
TERMOS = "Termos inox Brenta Alpin 750 ml"
ORGANIZATOR = "Set organizator multifuncțional Solvex, 5 piese"
UNCATEGORIZED_DEMO_NAMES = (TERMOS, ORGANIZATOR)

TV_32 = "Televizor LED Norvik 32NV3000, 81 cm, HD Ready, Clasa F"
TV_43 = "Televizor LED Smart Norvik 43NV5200, 108 cm, Full HD, Clasa F"
TV_55 = "Televizor LED Smart Kelmor 55KM7100, 139 cm, Ultra HD 4K, Clasa G"
TV_OLED = "Televizor OLED Smart Tavora 55TV9500, 139 cm, Ultra HD 4K, Clasa G"
TV_QLED = "Televizor QLED Smart Altrion 50AQ6600, 126 cm, Ultra HD 4K, Clasa F"
SUPORT_TV = "Suport TV perete Brenta B400, 32 - 65 inch, fix"
WHISKY_12 = "Whisky Glenmora Highland 12 ani, 0.7L, 40%"
WHISKY_25 = "Whisky Strathvale Single Malt 25 ani, 0.7L, 43%"
VODKA = "Vodka Zarevo Clasica 1L, 40%"
GIN = "Gin Botanic Nordvik 0.7L, 42%"
VIN = "Vin roșu sec Crama Lunca Merlot 0.75L"
PROSECCO = "Prosecco Brut Valdoro DOC 0.75L"
RACHIU = "Rachiu de prune, producție locală, 0.5L, 50%"
TUICA = "Țuică de prune 52%, 1L, producție artizanală"
CONIAC = "Coniac Aurelian VSOP 0.7L, 40%"
BERE = "Bere artizanală Brumărie IPA, pachet 6 x 0.33L, 6.2%"
VERMUT = "Vermut Rosso Torrino 1L"
TELEFON_X9 = "Telefon mobil Vexor X9 Pro, Dual SIM, 256GB, 12GB RAM, 5G, Gri"
MONITOR = "Monitor LED Brenta 27 inch, Full HD, 75Hz"
GHETE = "Ghete impermeabile bărbați Kelmor Trek, maro, mărimea 42"
CASTI = "Căști wireless Lumio Buds 3, Bluetooth 5.3"
ROBOT = "Aspirator robot Solvex R5, mopping, 4000 Pa"
# Nu e în demo_catalog.py: cumpărat doar din scenariu, deci istoricul lui de preț e același la orice seed.
CAFEA_MACINATA = "Cafea măcinată Aroma Casa 500 g"

_D = block_status.DELIVERED
_C = block_status.CANCELLED
_P = block_status.IN_PROGRESS


def _price(lei: int, bani: int = 99) -> int:
    """Preț în bani din lei și bani (ex. 1299, 99 -> 129999)."""
    return lei * 100 + bani


def _line(name: str, lei: int, bani: int = 99, qty: int = 1) -> LinePlan:
    """Linie de produs cu prețul pe bucată în lei și bani."""
    return LinePlan(name, _price(lei, bani), qty)


def _order(placed_at: str, *blocks: BlockPlan, header_extra_bani: int = 0) -> OrderPlan:
    """Comandă cu unul sau mai multe blocuri; `header_extra_bani` ≠ 0 face totalul din antet diferit de suma blocurilor."""
    return OrderPlan(placed_at, list(blocks), header_extra_bani)


def _emag(*lines: LinePlan, status: str = _D, **options) -> BlockPlan:
    """Bloc vândut și livrat de eMAG."""
    return BlockPlan(EMAG_SELLER, status, list(lines), **options)


def scripted_plans() -> tuple[list[OrderPlan], list[ReturnPlan]]:
    """Comenzile și retururile scrise de mână (aceleași la orice seed)."""
    orders: list[OrderPlan] = []
    returns: list[ReturnPlan] = []

    def add(order: OrderPlan) -> OrderPlan:
        """Adaugă comanda în listă și o întoarce (retururile trimit la ea)."""
        orders.append(order)
        return order

    # --- 2017: începutul ---
    add(_order("2017-03-14T10:42", _emag(
        _line("Căști wireless Lumio Buds 1, Bluetooth 4.2", 189),
        _line("Husă protecție Vexor X5, silicon, transparent", 29, 90))))
    add(_order("2017-09-02T19:15", BlockPlan(STELARIS, _D, [_line("Tabletă Lumio Tab 8, 8 inch, 16GB, Wi-Fi", 549)])))
    add(_order("2017-11-24T08:05", _emag(_line(TV_32, 799), voucher_bani=5000)))  # Black Friday

    # --- 2018 ---
    add(_order("2018-02-10T13:30", _emag(
        _line("Pantofi sport bărbați Brenta Run, negru, mărimea 43", 219),
        _line("Tricou bumbac bărbați Brenta, negru, XL", 49, qty=2), pickup=True)))
    add(_order("2018-12-20T17:48", _emag(
        _line(WHISKY_12, 159), _line(VIN, 44, 90, qty=2), _line(PROSECCO, 49, qty=2), services_bani=(149,))))

    # --- 2019: un televizor anulat de vânzător, recumpărat de la eMAG ---
    add(_order("2019-04-06T09:22", BlockPlan(NORDHAUS, _C, [_line(TV_43, 1349)])))
    add(_order("2019-04-08T21:10", _emag(_line(TV_43, 1399))))
    add(_order("2019-06-18T11:05", _emag(_line("Smartwatch Lumio Fit 2, GPS, AMOLED", 649))))
    add(_order("2019-12-22T20:15", _emag(
        _line(GIN, 89), _line(PROSECCO, 49, qty=2), _line(CONIAC, 119), voucher_bani=2500)))

    # --- 2020: muncă de acasă ---
    add(_order("2020-03-28T14:12", _emag(
        _line("Laptop Kelmor Slim 14, 14 inch, Full HD, 8GB RAM, 256GB SSD", 2199),
        _line("Mouse wireless Kelmor M200", 59),
        _line("Rucsac urban impermeabil Kelmor 25 L, negru", 129))))
    monitors = add(_order("2020-04-02T10:40", _emag(
        _line(MONITOR, 649, qty=2), _line("Tastatură mecanică Solvex K87, switch roșu", 249), storno=True)))
    returns.append(ReturnPlan(monitors, (MONITOR,)))  # retur parțial: 1 din 2 bucăți
    add(_order("2020-05-09T16:25", BlockPlan(DUNAREA, _D, [_line("Router Wi-Fi 6 Solvex AX3000", 329)])))
    add(_order("2020-11-27T07:55", _emag(
        _line(CASTI, 249), _line("Baterie externă Power Bank Solvex 20000 mAh, 22.5W", 159), voucher_bani=4000)))

    # --- 2021: anul de vârf (renovare) ---
    add(_order("2021-05-15T12:34", _emag(_line(TV_55, 2549), _line(SUPORT_TV, 89), other_bani=(200,))))
    add(_order("2021-06-20T18:02", _emag(_line("Frigider cu două uși Kelmor, 280 L, Clasa E", 2399), voucher_bani=10000)))
    add(_order("2021-08-03T13:18", _emag(_line("Aer condiționat Kelmor Inverter 12000 BTU, Wi-Fi", 2299))))
    add(_order("2021-09-01T09:45", _emag(
        _line("Mașină de spălat rufe Brenta 8 kg, 1400 rpm, Clasa A", 1899),
        _line("Detergent rufe Lumio 5 L", 64, qty=2), services_bani=(149,))))
    add(_order("2021-09-18T14:05", _emag(
        _line("Cuptor electric încorporabil Altrion 60 cm, 71 L, Clasa A", 1649),
        _line("Mașină de spălat vase Brenta 60 cm, 13 seturi, Clasa E", 1399))))
    add(_order("2021-10-11T15:20", _emag(
        _line("Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Negru", 1599),
        _line("Husă protecție Vexor X5, silicon, transparent", 39, 90),
        _line("Încărcător rețea Brenta 65W GaN, USB-C", 109))))
    add(_order("2021-11-02T20:14", _emag(_line("Licență electronică antivirus pentru 3 dispozitive, 1 an", 89))))
    add(_order("2021-03-27T10:05", BlockPlan(  # pagina nu arată „Total plătit” la acest vânzător: avertisment
        NORDHAUS, _D, [_line("Baterii alcaline AA Lumio, set 20 buc", 44, 90)], paid_shown=False)))
    add(_order("2021-12-21T19:30", _emag(_line(WHISKY_25, 689), _line(VODKA, 69, qty=2))))

    # --- 2022 ---
    add(_order("2022-01-15T11:00", _emag(_line(TERMOS, 89, 90))))
    add(_order("2022-04-12T18:20", _emag(  # același model ca cel negru din 2018 (se unește); mărimea L e alt produs
        _line("Tricou bumbac bărbați Brenta, alb, XL", 44, 90, qty=2), _line("Tricou bumbac bărbați Brenta, alb, L", 44, 90))))
    add(_order("2022-05-03T08:50", _emag(_line(CAFEA_MACINATA, 24, 90, qty=2))))
    add(_order("2022-10-08T12:30", _emag(  # antetul arată cu 5,50 Lei mai mult decât suma blocurilor
        _line("Set ustensile bucătărie Solvex, silicon, 12 piese", 89, 90)), header_extra_bani=550))
    add(_order("2022-03-05T10:10", _emag(  # exact la prag: NU e „peste prag”
        _line("Aspirator vertical fără fir Kelmor V12, 150 AW", 500, 0))))
    add(_order("2022-06-18T12:44", BlockPlan(AURELIAN, _D, [_line(RACHIU, 74, 90, qty=3), _line(TUICA, 99, 90)])))
    add(_order("2022-07-02T08:30", BlockPlan(CASA_VERDE, _C, [_line(VODKA, 69, qty=6)])))  # anulat, fără retur
    ghete = add(_order("2022-09-14T17:00", BlockPlan(  # marcat „Livrare anulată”, dar returnat
        ZORILOR, _C, [_line(GHETE, 389)], storno=True)))
    returns.append(ReturnPlan(ghete, (GHETE,), mode="Emitere voucher"))
    add(_order("2022-11-25T06:58", _emag(
        _line("Laptop Altrion Book 15, 15.6 inch, Full HD, 8 nuclee, 16GB RAM, 512GB SSD", 3499),
        _line("Stick USB Brenta 128GB, USB 3.2", 49), _line("SSD Brenta 1TB, NVMe, M.2", 349), voucher_bani=15000)))

    # --- 2023 ---
    add(_order("2023-02-12T20:20", _emag(_line("Bicicletă pliabilă Kelmor Urban 20 inch", 1299))))
    add(_order("2023-09-10T14:25", _emag(_line("Prelungitor 5 prize Brenta 3 m, cu întrerupător", 39, 90)),
               BlockPlan(STELARIS, _C, [_line("Becuri LED E27 Lumio 9W, set 6 buc", 34, 90)]),
               header_extra_bani=3490))  # ca în conturile reale: antetul include încă „Total de plată” al blocului anulat
    add(_order("2023-03-18T11:40", _emag(  # stick-ul 128GB mai ieftin decât în 2022; mouse-ul, aceeași marcă, în negru
        _line("Stick USB Brenta 128GB, USB 3.2", 45, 90), _line("Mouse wireless Kelmor M200, Negru", 54, 90))))
    add(_order("2023-05-07T11:11", _emag(
        _line("Friteuză cu aer cald Solvex 5.5 L, 1700W", 349),
        _line("Espressor automat Lumio Barista, 15 bar", 1899), pickup=True)))
    add(_order("2023-08-19T09:09", _emag(_line("Tabletă Lumio Tab 10, 10.4 inch, 64GB, Wi-Fi", 899))))
    add(_order("2023-11-24T07:30", _emag(_line(TV_OLED, 4299), voucher_bani=30000, services_bani=(149,))))
    add(_order("2023-12-23T18:10", _emag(
        _line(VODKA, 69, qty=2), _line(BERE, 44, qty=2), _line(VERMUT, 59))))

    # --- 2024: retururi mari ---
    add(_order("2024-03-02T15:10", _emag(  # antetul arată cu 10 Lei mai puțin decât suma blocurilor
        _line("Prelungitor 5 prize Brenta 3 m, cu întrerupător", 39, 90), _line("Becuri LED E27 Lumio 9W, set 6 buc", 34, 90)),
        header_extra_bani=-1000))
    qled = add(_order("2024-02-03T14:40", _emag(_line(TV_QLED, 2199), storno=True)))
    returns.append(ReturnPlan(qled, (TV_QLED,)))
    add(_order("2024-09-05T13:05", _emag(  # stick-ul de 256GB NU se unește cu cel de 128GB; mouse-ul în alb
        _line("Stick USB Brenta 256GB, USB 3.2", 79, 90), _line("Mouse wireless Kelmor M200, Alb", 49, 90))))
    x9 = add(_order("2024-05-14T10:25", BlockPlan(  # marcat „Livrare anulată” de eMAG, dar returnat
        NORDHAUS, _C, [_line(TELEFON_X9, 3499)], storno=True)))
    returns.append(ReturnPlan(x9, (TELEFON_X9,)))
    add(_order("2024-07-21T16:50", _emag(_line("Aparat foto mirrorless Altrion Z50, 24 MP", 4299))))
    add(_order("2024-10-09T12:00", _emag(_line("Trotinetă electrică Kelmor T5, 25 km/h", 1799))))
    whisky = add(_order("2024-12-20T19:05", _emag(
        _line(WHISKY_12, 174), _line(PROSECCO, 52, qty=2), storno=True)))
    returns.append(ReturnPlan(whisky, (WHISKY_12,)))  # sticlă spartă la livrare

    # --- 2025: retur cerut apoi anulat ---
    headphones = add(_order("2025-03-16T10:05", _emag(_line(CASTI, 279))))
    returns.append(ReturnPlan(headphones, (CASTI,), outcome="cancelled"))
    add(_order("2025-06-08T13:33", _emag(
        _line("Cort camping Brenta Trek, 4 persoane", 459), _line("Gantere reglabile Brenta, set 2 x 10 kg", 219))))
    add(_order("2025-02-14T09:30", _emag(_line(CAFEA_MACINATA, 31, 90, qty=2))))  # mai scumpă decât în 2022 (ultima cumpărare)
    dryer = add(_order("2025-09-27T09:00", _emag(
        _line("Uscător de păr Kelmor 2200W, ionizare", 179), _line("Apă de parfum Aurelia 100 ml", 289), storno=True)))
    returns.append(ReturnPlan(dryer, ("Uscător de păr Kelmor 2200W, ionizare",), refund_shown=False))  # finalizat, fără sumă afișată
    add(_order("2025-10-20T16:10", _emag(_line("Stick USB Brenta 256GB, USB 3.2", 74, 90))))
    add(_order("2025-12-12T15:45", _emag(_line("Card cadou Brenta Shop 200 Lei", 200, 0))))

    # --- 2026: în curs, fără rezultat, asigurare ---
    add(_order("2026-03-09T12:20", _emag(_line("Cameră de supraveghere Brenta Wi-Fi 2K, exterior", 229, qty=2))))
    robot = add(_order("2026-08-11T15:15", _emag(_line(ROBOT, 1099))))
    returns.append(ReturnPlan(robot, (ROBOT,), outcome="pending"))  # cerut, fără „Restituire suma”
    add(_order("2026-09-03T18:53", BlockPlan(INSURER, block_status.PAID_ONLY, [_line("Asigurare RCA autoturism, 12 luni", 1846, 0)])))
    add(_order("2026-09-20T10:30", _emag(_line(ORGANIZATOR, 119, 90))))
    add(_order("2026-09-30T16:20", _emag(
        _line(TV_55, 2399), _line(PROSECCO, 49, qty=2),
        status=_P, status_text="Produsele au fost predate curierului")))
    add(_order("2026-10-02T09:12", BlockPlan(DUNAREA, _P, [
        _line("Tastatură mecanică Solvex K87, switch roșu", 259), _line("Mouse wireless Kelmor M200", 54)])))
    return orders, returns
