"""Împarte o sumă întreagă (în bani) în părți proporționale cu niște ponderi, fără să se piardă sau să apară vreun ban.

Primește: totalul de împărțit (întreg ≥ 0) și ponderile (întregi ≥ 0), de exemplu reducerea unui bloc și prețurile liniilor.
Dă înapoi: lista părților, în ordinea ponderilor, cu suma EXACT egală cu totalul (metoda celui mai mare rest).
Fiecare parte diferă de partea „exactă” (total × pondere / suma ponderilor) cu mai puțin de un ban.
Ce NU face: nu știe de comenzi, vouchere sau retururi; nu rotunjește la zecimale (lucrează doar cu întregi).
"""

from typing import Sequence


def split_proportionally(total: int, weights: Sequence[int]) -> list[int]:
    """Părțile lui `total` proporționale cu `weights`, cu suma exact `total` (metoda celui mai mare rest).

    Fiecare parte primește întâi partea întreagă; banii rămași merg, câte unul, la pozițiile cu cel mai mare rest
    (la egalitate, la prima poziție). Ridică ValueError la total sau ponderi negative, ori la un total pozitiv
    fără nicio pondere pozitivă (nu ar avea unde să meargă).
    """
    if total < 0 or any(weight < 0 for weight in weights):
        raise ValueError(f"împărțire proporțională: totalul ({total}) și ponderile trebuie să fie ≥ 0")
    weight_sum = sum(weights)
    if weight_sum == 0:
        if total:
            raise ValueError(f"împărțire proporțională: {total} de împărțit, dar nicio pondere pozitivă")
        return [0] * len(weights)
    exact = [total * weight for weight in weights]  # numărătorii părților exacte (numitor comun: weight_sum)
    parts = [value // weight_sum for value in exact]
    remaining = total - sum(parts)
    by_remainder = sorted(range(len(weights)), key=lambda i: (-(exact[i] % weight_sum), i))
    for index in by_remainder[:remaining]:
        parts[index] += 1
    return parts
