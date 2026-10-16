// Împarte o sumă întreagă (în bani) în părți proporționale cu niște ponderi, fără să se piardă sau să apară vreun ban (portul lui emag_spend/proportional_split.py).
// Primește: totalul de împărțit (întreg >= 0) și ponderile (întregi >= 0). Dă înapoi: lista părților, în ordinea ponderilor, cu suma EXACT egală cu totalul (metoda celui mai mare rest).
// Calculele merg pe BigInt: total * pondere poate depăși 2^53, unde produsul din JavaScript ar rotunji în tăcere, iar Python lucrează exact.
// Ce NU face: nu știe de comenzi, vouchere sau retururi; nu rotunjește la zecimale (lucrează doar cu întregi).

/** TypeError dacă totalul sau o pondere nu e întreg sigur: BigInt(număr cu fracții) ar da altă eroare, mai greu de înțeles. */
function assertSafeIntegers(total, weights) {
  if (!Number.isSafeInteger(total) || !weights.every(Number.isSafeInteger)) {
    throw new TypeError('împărțire proporțională: totalul și ponderile trebuie să fie întregi sigure');
  }
}

/**
 * Părțile lui `total` proporționale cu `weights`, cu suma exact `total`: fiecare primește partea întreagă, iar banii rămași merg, câte unul, la pozițiile cu cel mai mare rest
 * (la egalitate, la prima poziție). RangeError, cu mesajul din ValueError-ul Python, la total sau ponderi negative ori la un total pozitiv fără nicio pondere pozitivă.
 */
export function splitProportionally(total, weights) {
  assertSafeIntegers(total, weights);
  if (total < 0 || weights.some((weight) => weight < 0)) {
    throw new RangeError(`împărțire proporțională: totalul (${total}) și ponderile trebuie să fie ≥ 0`);
  }
  const weightSum = weights.reduce((sum, weight) => sum + BigInt(weight), 0n);
  if (weightSum === 0n) {
    if (total) throw new RangeError(`împărțire proporțională: ${total} de împărțit, dar nicio pondere pozitivă`);
    return weights.map(() => 0);
  }
  const exact = weights.map((weight) => BigInt(total) * BigInt(weight)); // numărătorii părților exacte (numitor comun: weightSum)
  const parts = exact.map((value) => value / weightSum); // valori >= 0: împărțirea BigInt trunchiază spre zero, adică e podea
  const remainders = exact.map((value) => value % weightSum);
  const remaining = Number(BigInt(total) - parts.reduce((sum, part) => sum + part, 0n));
  const byRemainder = weights.map((_, index) => index).sort((i, j) => {
    if (remainders[i] !== remainders[j]) return remainders[j] > remainders[i] ? 1 : -1; // rest mai mare întâi
    return i - j; // la egalitate, prima poziție
  });
  for (const index of byRemainder.slice(0, remaining)) parts[index] += 1n;
  return parts.map(Number);
}
