// Comparația personală folosește numai denumirea integrală și prețul unitar deja calculat în registru.
// Nu elimină culoare, dimensiune, capacitate sau semne și nu pretinde identificarea sigură a modelului.
/** Compară produsul cu achizițiile păstrate; întoarce ultima cumpărare și minimul personal sau starea lipsă. */
export function compareProduct(product, purchases) {
  const normalize = (value) => String(value ?? '').trim().replace(/\s+/g, ' ').toLocaleLowerCase('ro');
  const matches = purchases.filter((item) => normalize(item.name) === normalize(product.name)
    && Number.isSafeInteger(item.unit_bani) && item.unit_bani >= 0 && item.qty > 0);
  if (!matches.length) return { status: 'no-history' };
  matches.sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(b.id).localeCompare(String(a.id)));
  const latestDate = matches[0].date;
  const latest = matches.filter((item) => item.date === latestDate);
  // Fără oră/ordine sigură în aceeași zi, două prețuri distincte nu definesc „ultima dată”.
  const datesKnown = matches.every((item) => typeof item.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(item.date));
  const last = datesKnown && new Set(latest.map((item) => item.unit_bani)).size === 1 ? latest[0] : null;
  const minimum = matches.reduce((a, b) => a.unit_bani <= b.unit_bani ? a : b);
  return { status: 'matched', last, minimum, count: matches.length, match: 'name' };
}
