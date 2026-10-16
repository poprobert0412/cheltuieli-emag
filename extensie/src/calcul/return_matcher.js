// Potrivește retururile finalizate cu produsele din comenzi (portul lui emag_spend/return_matcher.py).
// Primește: registrul de linii și lista de retururi (+ opțional `log`, cu metodele info(modul, text) și warning(modul, text), ca RunLog). Modifică liniile pe loc: o unitate „păstrată” devine „returnată”.
// Dă înapoi: ReturnMatchReport cu avertismentele și statisticile (câte potriviri, ce n-a găsit loc). Doar retururile finalizate scad din total; cele anulate sau fără rezultat lasă produsul păstrat.
// Numele din retur se caută în produsele comenzii: identic sau prefix al unui nume trunchiat „[...]” de eMAG, apoi aproximativ (>= 0,88) doar dacă nu există potrivire identică.
// La marketplace eMAG marchează produsul returnat „Livrare anulata”: o unitate „anulată” găsită în retur devine „returnată”, ca să nu fie numărată ca anulare și nici scăzută a doua oară.
// Ce NU face: nu calculează sume (paid_totals.js) și nu citește pagini.
import { cpLength, pyRepr, pyRstrip } from './python_compat.js';
import { PyPattern } from './python_regex.js';
import { getCloseMatches } from './sequence_matcher.js';
import { normalizeText } from './text_normalize.js';

const LOG_MODULE = 'return_matcher';
// Sub acest scor un nume de produs din retur NU se consideră același produs.
export const FUZZY_MATCH_MIN_RATIO = 0.88;
// Semnul de trunchiere pus de eMAG la capătul unui nume lung: „[...]”, „...” sau „…”, cu spații în jur.
export const TRUNCATION_MARKER = new PyPattern(String.raw`\s*(?:\[\.\.\.\]|\.\.\.|…)\s*$`);
// Un nume trunchiat de eMAG („... [...]”) se potrivește cu numele întreg doar dacă prefixul e destul de lung.
export const MIN_TRUNCATED_PREFIX = 30;
// Caracterele scoase de la capătul prefixului după ce semnul de trunchiere a fost tăiat (rstrip(" ,") din Python).
const PREFIX_TRAILING_CHARS = ' ,';
// Din ce parte a registrului vine unitatea returnată: păstrată, sau marcată „anulat” de eMAG la marketplace.
const SOURCE_KEPT = 'kept';
const SOURCE_CANCELLED = 'cancelled';

/** Rezultatul potrivirii retururilor (aceleași câmpuri ca ReturnMatchReport din Python). */
export class ReturnMatchReport {
  constructor() {
    this.matched_units = 0;
    this.matched_from_cancelled_units = 0;
    this.warnings = [];
    this.unmatched_refund_bani = 0; // restituiri fără produs potrivit
    // Retururile finalizate cu o parte din produse potrivite și o parte nu: suma lor restituită acoperă și produse care au rămas „păstrate”,
    // deci nu se poate atribui întreagă produselor potrivite (paid_totals.js o tratează separat).
    this.partially_matched_return_ids = [];
  }
}

/** Nume identic, sau nume trunchiat de eMAG care e prefixul numelui din retur (prefixul trebuie să aibă cel puțin MIN_TRUNCATED_PREFIX caractere). */
function matchesExactly(lineName, normName) {
  const normalized = normalizeText(lineName);
  if (normalized === normName) return true;
  if (TRUNCATION_MARKER.search(normalized) !== null) {
    const prefix = pyRstrip(TRUNCATION_MARKER.sub('', normalized), PREFIX_TRAILING_CHARS);
    return cpLength(prefix) >= MIN_TRUNCATED_PREFIX && normName.startsWith(prefix);
  }
  return false;
}

/** Linia care corespunde numelui: preferă una cu unități păstrate, apoi una anulată. Întoarce [linie, 'kept' | 'cancelled'] sau [null, '']. */
function pickLine(pool, normName) {
  let candidates = pool.filter((line) => matchesExactly(line.name, normName));
  if (candidates.length === 0) {
    // Lista de nume e un set în Python (ordine oarecare); rezultatul nu depinde de ea: get_close_matches alege cel mai mare scor, iar la scor egal textul mai mare.
    const names = new Set(pool.map((line) => normalizeText(line.name)));
    const close = getCloseMatches(normName, [...names], 1, FUZZY_MATCH_MIN_RATIO);
    candidates = pool.filter((line) => close.length > 0 && normalizeText(line.name) === close[0]);
  }
  for (const line of candidates) if (line.kept_qty > 0) return [line, SOURCE_KEPT];
  for (const line of candidates) if (line.cancelled_qty > 0) return [line, SOURCE_CANCELLED];
  return [null, ''];
}

/** Aplică retururile finalizate pe liniile registrului (modifică `lines`); `log` primește rezumatul rulării, ca logger.info din Python. */
export function applyReturns(lines, returns, log = null) {
  const report = new ReturnMatchReport();
  const byOrder = new Map();
  for (const line of lines) {
    if (!byOrder.has(line.order_id)) byOrder.set(line.order_id, []);
    byOrder.get(line.order_id).push(line);
  }
  for (const ret of returns) {
    if (!ret.completed) continue;
    const label = `retur ${ret.return_id}`;
    if (ret.order_ids.length === 0) {
      report.warnings.push(`${label}: nu are nicio comandă asociată`);
      report.unmatched_refund_bani += ret.refund_bani || 0;
      continue;
    }
    const pool = ret.order_ids.flatMap((orderId) => byOrder.get(orderId) ?? []);
    if (pool.length === 0) {
      report.warnings.push(`${label}: comanda ${ret.order_ids.join(', ')} nu e în lista citită`);
      report.unmatched_refund_bani += ret.refund_bani || 0;
      continue;
    }
    if (ret.product_names.length === 0) report.warnings.push(`${label}: nu are produse listate`);
    let unmatchedHere = 0;
    for (const productName of ret.product_names) {
      const [line, source] = pickLine(pool, normalizeText(productName));
      if (line === null) {
        unmatchedHere += 1;
        report.warnings.push(`${label}: produsul ${pyRepr(productName)} nu are potrivire în comanda ${pyRepr(ret.order_ids)}`);
        continue;
      }
      if (source === SOURCE_KEPT) {
        line.kept_qty -= 1;
      } else {
        line.cancelled_qty -= 1;
        line.returned_from_cancelled_qty += 1;
        report.matched_from_cancelled_units += 1;
      }
      line.returned_qty += 1;
      line.return_ids.push(ret.return_id);
      report.matched_units += 1;
    }
    if (unmatchedHere > 0 && unmatchedHere === ret.product_names.length) report.unmatched_refund_bani += ret.refund_bani || 0;
    else if (unmatchedHere > 0) report.partially_matched_return_ids.push(ret.return_id);
  }
  log?.info(LOG_MODULE, `retururi aplicate: ${report.matched_units} unități (din care ${report.matched_from_cancelled_units} marcate 'anulat' de eMAG), ${report.warnings.length} avertismente`);
  return report;
}
