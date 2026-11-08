// Leagă noile ecrane de motorul existent: rezumat, achiziții păstrate și perioade cu retururi atribuite înainte de filtrare.
// Fără comenzi brute păstrează doar rezumatul/anualul existent, fără luni ori produse inventate.
// period() păstrează zilele întregi; campaign() cere ore locale RO precise și exclude sfârșitul.
import { loadAnalysis } from '../rulare/analysis_loader.js';
import { shoppingCampaign, shoppingPeriod } from './shopping_period.js';

/** Cheie structurală fără coliziuni de delimitatori; apariția este numărată înainte de eliminarea liniilor returnate. */
function purchasesOf(lines) {
  const occurrences = new Map();
  const rows = [];
  for (const line of lines) {
    const key = JSON.stringify([line.order_id, line.seller, line.name]);
    const occurrence = occurrences.get(key) ?? 0;
    occurrences.set(key, occurrence + 1);
    if (line.kept_qty <= 0 || line.paid_only_qty) continue;
    rows.push({ id: JSON.stringify([line.order_id, line.seller, line.name, occurrence]), order_id: line.order_id,
      date: line.placed_at?.slice(0, 10) ?? null, name: line.name, seller: line.seller, category: line.category,
      qty: line.kept_qty, paid_bani: line.kept_paid_bani,
      // O linie cu un rest de un ban are prețul mediu pe unitate, rotunjit; totalul exact rămâne paid_bani.
      unit_bani: Math.round(line.kept_paid_bani / line.kept_qty) });
  }
  return rows;
}

/** Reanalizează datele brute cu aceeași configurație; loader opțional pentru teste cu configurația reală din depozit. */
export async function createShoppingInsights(entry, { loader = loadAnalysis } = {}) {
  if (!entry || !entry.summary || typeof entry.summary !== 'object') throw new TypeError('analiză de cumpărături invalidă');
  const hasRaw = Array.isArray(entry.orders) && (entry.orders.length > 0 || entry.summary.meta?.orders === 0);
  let result;
  if (hasRaw) {
    if (!Array.isArray(entry.returns)) throw new TypeError('retururile analizei lipsesc');
    const threshold = entry.summary.meta?.threshold_bani ?? Math.round(entry.threshold_lei * 100);
    if (!Number.isSafeInteger(threshold) || threshold < 0) throw new TypeError('pragul analizei este invalid');
    const engine = await loader();
    result = engine.analyze(entry.orders, entry.returns, threshold, entry.created_at ?? entry.summary.meta.generated_at);
    result.summary = engine.plainSummary(result.summary);
  } else result = { summary: structuredClone(entry.summary), lines: [], paid_by_order: new Map() };
  const source = { ...result, orders: hasRaw ? structuredClone(entry.orders) : null };
  return {
    summary: result.summary, purchases: purchasesOf(result.lines),
    years: (result.summary.by_year ?? []).filter((row) => /^\d{4}$/.test(String(row.year))).map((row) => String(row.year)).sort(),
    /** Întoarce un summary compact; available=false și paid=null dacă detaliul perioadei nu există. */
    async period(from, to) { return shoppingPeriod(source, from, to); },
    /** Campania are limite cu oră RO și sfârșit exclusiv; comenzile fără oră sunt semnalate și excluse. */
    async campaign(campaign) { return shoppingCampaign(source, campaign); },
  };
}
