"""Catalogul de produse INVENTATE din care demo_data.py completează comenzile demonstrative.

Primește: nimic (doar date). Dă înapoi: familiile de produse (nume, interval de preț
în lei, cantități posibile, cât de des apar) și vânzătorii marketplace inventați.
Mărcile (Norvik, Kelmor, Lumio...) și firmele sunt inventate. Fiecare nume intră, la
clasificatorul din config/categorii.json, într-o categorie reală (o verifică un test).
Nu conține televizoare, asigurări și produse necategorizate: acelea sunt scrise de
mână în demo_scenario.py, ca să existe garantat la orice seed.
"""

from dataclasses import dataclass
from typing import NamedTuple


class CatalogItem(NamedTuple):
    """Un produs: nume și interval de preț (lei) din care se alege un preț."""

    name: str
    low_lei: int
    high_lei: int


@dataclass(frozen=True)
class Family:
    """O familie de produse: `weight` = cât de des apare în comenzile obișnuite
    (relativ la celelalte), `qty_options` = cantitățile posibile pe linie."""

    weight: int
    qty_options: tuple[int, ...]
    items: tuple[CatalogItem, ...]


# Ordinea familiilor contează: seed-ul determină datele, iar ordinea intră în calcul.
FILLER_FAMILIES: dict[str, Family] = {
    "cosmetice": Family(10, (1, 1, 2, 3), (
        CatalogItem("Șampon anticădere Lumio 400 ml", 22, 45),
        CatalogItem("Gel de duș Brenta 750 ml", 14, 30),
        CatalogItem("Cremă hidratantă față Lumio 50 ml", 35, 120),
        CatalogItem("Apă de parfum Aurelia 100 ml", 150, 420),
        CatalogItem("Pastă de dinți Brenta Whitening 100 ml", 10, 25),
    )),
    "curatenie": Family(9, (1, 1, 2, 3), (
        CatalogItem("Detergent rufe Lumio 5 L", 45, 90),
        CatalogItem("Dezinfectant suprafețe Brenta 750 ml", 10, 22),
        CatalogItem("Saci menajeri Solvex 120 L, 10 role", 12, 25),
        CatalogItem("Hârtie igienică Brenta 3 straturi, 24 role", 35, 60),
        CatalogItem("Alcool sanitar 500 ml", 6, 14),  # nu e „Alcool”: regula îl exclude
    )),
    "alimente": Family(8, (1, 1, 2, 3), (
        CatalogItem("Cafea boabe Aroma Casa 1 kg", 55, 110),
        CatalogItem("Ceai verde Solvex, 100 plicuri", 15, 35),
        CatalogItem("Miere de salcâm 900 g", 40, 75),
    )),
    "sanatate": Family(8, (1, 1, 2), (
        CatalogItem("Supliment alimentar Vitamina D3 2000 UI, 120 capsule", 25, 60),
        CatalogItem("Magneziu B6 Solvex, 90 comprimate", 20, 45),
        CatalogItem("Omega 3 Brenta 1000 mg, 100 capsule", 45, 120),
    )),
    "imbracaminte": Family(9, (1, 1, 2), (
        CatalogItem("Tricou bumbac bărbați Brenta, negru, XL", 35, 95),
        CatalogItem("Hanorac cu glugă Kelmor, gri, L", 90, 220),
        CatalogItem("Geacă de iarnă impermeabilă Brenta, verde, XL", 280, 560),
        CatalogItem("Rucsac urban impermeabil Kelmor 25 L, negru", 90, 220),
        CatalogItem("Portofel piele naturală Brenta, maro", 70, 190),
    )),
    "incaltaminte": Family(6, (1, 1, 2), (
        CatalogItem("Pantofi sport bărbați Brenta Run, negru, mărimea 43", 150, 380),
        CatalogItem("Ghete impermeabile bărbați Kelmor Trek, maro, mărimea 42", 250, 520),
        CatalogItem("Papuci de casă dame Brenta Soft, gri, mărimea 38", 35, 90),
    )),
    "casa": Family(8, (1, 1, 2), (
        CatalogItem("Set ustensile bucătărie Solvex, silicon, 12 piese", 45, 110),
        CatalogItem("Prelungitor 5 prize Brenta 3 m, cu întrerupător", 25, 60),
        CatalogItem("Bormașină cu acumulator Altrion 18V, 2 baterii", 230, 620),
        CatalogItem("Becuri LED E27 Lumio 9W, set 6 buc", 25, 60),
        CatalogItem("Covor living Brenta 160 x 230 cm", 230, 650),
        CatalogItem("Radiator electric Solvex 2000W", 120, 320),
        CatalogItem("Baterii alcaline AA Lumio, set 20 buc", 30, 60),
    )),
    "auto": Family(6, (1, 1, 2), (
        CatalogItem("Ulei motor sintetic Brenta 5W-30, 5 L", 140, 280),
        CatalogItem("Set ștergătoare parbriz Solvex 600/450 mm", 50, 130),
        CatalogItem("Cameră auto DVR Kelmor 2K, Wi-Fi", 230, 520),
        CatalogItem("Lichid parbriz vară Brenta 5 L", 12, 35),
        CatalogItem("Scaun auto copii Brenta Safe 15-36 kg", 320, 850),
        CatalogItem("Navigație GPS Solvex 7 inch, hărți Europa", 260, 700),
        CatalogItem("Cabluri de pornire Solvex 600A, 3 m", 55, 140),
    )),
    "audio": Family(4, (1,), (
        CatalogItem("Căști wireless Lumio Buds 3, Bluetooth 5.3", 180, 420),
        CatalogItem("Boxă portabilă Solvex Wave 20W", 140, 360),
        CatalogItem("Soundbar Kelmor 2.1, 200W, Bluetooth", 420, 1100),
    )),
    "accesorii_telefon": Family(6, (1, 1, 2), (
        CatalogItem("Husă protecție Vexor X5, silicon, transparent", 25, 60),
        CatalogItem("Folie protecție sticlă securizată pentru Vexor X5", 20, 50),
        CatalogItem("Încărcător rețea Brenta 65W GaN, USB-C", 80, 180),
        CatalogItem("Baterie externă Power Bank Solvex 20000 mAh, 22.5W", 110, 230),
    )),
    "calculatoare": Family(7, (1, 1, 1, 2), (
        CatalogItem("Mouse wireless Kelmor M200", 40, 110),
        CatalogItem("Tastatură mecanică Solvex K87, switch roșu", 180, 380),
        CatalogItem("SSD Brenta 1TB, NVMe, M.2", 260, 520),
        CatalogItem("Router Wi-Fi 6 Solvex AX3000", 250, 480),
        CatalogItem("Stick USB Brenta 128GB, USB 3.2", 35, 80),
        CatalogItem("Imprimantă multifuncțională laser Solvex M200", 620, 1300),
        CatalogItem("Monitor LED Brenta 27 inch, Full HD, 75Hz", 580, 980),
    )),
    "electrocasnice": Family(6, (1,), (
        CatalogItem("Friteuză cu aer cald Solvex 5.5 L, 1700W", 230, 520),
        CatalogItem("Fier de călcat cu abur Solvex SteamPro 2600W", 130, 340),
        CatalogItem("Blender de mână Brenta 800W", 90, 220),
        CatalogItem("Uscător de păr Kelmor 2200W, ionizare", 110, 330),
        CatalogItem("Espressor automat Lumio Barista, 15 bar", 1400, 3200),
        CatalogItem("Smartwatch Lumio Fit 2, GPS, AMOLED", 330, 850),
    )),
    "sport": Family(4, (1, 1, 2), (
        CatalogItem("Gantere reglabile Brenta, set 2 x 10 kg", 170, 340),
        CatalogItem("Minge fotbal Brenta Match, marimea 5", 55, 130),
        CatalogItem("Cort camping Brenta Trek, 4 persoane", 280, 620),
    )),
    "bebelusi": Family(3, (1, 1, 2, 3), (
        CatalogItem("Scutece Brenta Baby, mărimea 4, 120 buc", 70, 150),
        CatalogItem("Lapte praf Brenta Baby 2, 800 g", 55, 110),
    )),
    "animale": Family(3, (1, 1, 2), (
        CatalogItem("Hrană uscată pentru câini adulți Brenta Pet 12 kg", 130, 260),
        CatalogItem("Nisip pentru pisici Brenta Pet 10 L", 25, 55),
    )),
    "carti_jocuri": Family(4, (1, 1, 2), (
        CatalogItem("Joc de societate Kelmor Strategia, 2-5 jucători", 95, 240),
        CatalogItem("Puzzle 1000 piese Brenta Peisaj montan", 40, 95),
    )),
    "telefoane": Family(2, (1,), (
        CatalogItem("Telefon mobil Vexor X5, Dual SIM, 128GB, 6GB RAM, 5G, Negru", 1150, 2100),
        CatalogItem("Tabletă Lumio Tab 10, 10.4 inch, 64GB, Wi-Fi", 720, 1250),
    )),
    "foto": Family(1, (1, 1, 2), (
        CatalogItem("Cameră de supraveghere Brenta Wi-Fi 2K, exterior", 160, 340),
    )),
    "alcool": Family(3, (1, 1, 2, 3), (
        CatalogItem("Whisky Glenmora Highland 12 ani, 0.7L, 40%", 150, 195),
        CatalogItem("Vodka Zarevo Clasica 1L, 40%", 55, 85),
        CatalogItem("Gin Botanic Nordvik 0.7L, 42%", 75, 125),
        CatalogItem("Vin roșu sec Crama Lunca Merlot 0.75L", 35, 75),
        CatalogItem("Prosecco Brut Valdoro DOC 0.75L", 38, 65),
        CatalogItem("Rachiu de prune, producție locală, 0.5L, 50%", 60, 95),
        CatalogItem("Coniac Aurelian VSOP 0.7L, 40%", 95, 160),
        CatalogItem("Vermut Rosso Torrino 1L", 45, 80),
    )),
    "console": Family(1, (1,), (
        CatalogItem("Gamepad wireless Kelmor GX2, PC și console", 140, 320),
    )),
    "licente": Family(2, (1,), (
        CatalogItem("Licență electronică antivirus pentru 3 dispozitive, 1 an", 60, 140),
        CatalogItem("Card cadou Brenta Shop 200 Lei", 200, 200),
    )),
}

# Firme marketplace inventate (nu corespund unor firme reale).
MARKETPLACE_SELLERS: tuple[str, ...] = (
    "Stelaris Comert SRL",
    "Nordhaus Distributie SRL",
    "Aurelian Market SRL",
    "Dunarea Digital SRL",
    "Casa Verde Import SRL",
    "Zorilor Sport SRL",
)
