// Mesajele de avertisment ale analizei, într-un singur loc: textul lor și citirea lui înapoi (portul lui emag_spend/warning_messages.py).
// Primește: valorile din mesaj (număr comandă, vânzător, sume în bani, numere). Dă înapoi: textul (format*) sau, dintr-un text, un obiect cu comanda, vânzătorul,
// tipul grupei și dacă poate afecta totalurile (parseOrderWarning). Expresiile de citire se construiesc din aceleași șabloane ca textele, deci o formulare nouă o urmează singură.
// Ce NU face: nu decide ce grupe se afișează, nu citește fișiere, nu calculează sume. Sumele din mesaje apar în lei (formatLei).
import { pyInt, pyRepr, pyStrip } from './python_compat.js';
import { formatLei } from './money_ro.js';
import { PyPattern, escapePython } from './python_regex.js';

// Tipurile de grupe din `warnings_detail` (aceleași valori ca în schema din analiza.json).
export const KIND_MISSING_PAID_TOTAL = 'missing_paid_total';
export const KIND_PENDING_RETURN = 'pending_return_without_result';
export const KIND_COMPLETED_RETURN_NO_REFUND = 'completed_return_without_refund';
export const KIND_HEADER_MISMATCH = 'header_total_mismatch';
export const KIND_OTHER = 'other';
export const ALL_KINDS = Object.freeze([
  KIND_MISSING_PAID_TOTAL,
  KIND_PENDING_RETURN,
  KIND_COMPLETED_RETURN_NO_REFUND,
  KIND_HEADER_MISMATCH,
  KIND_OTHER,
]);

// Familiile de mesaje: începutul comun al celor despre o comandă (cu sau fără vânzător) și despre un retur.
// Mesajele despre retururi vin din return_matcher, care își scrie singur textul.
const ORDER_SELLER_PREFIX = 'comanda {order_id}, {seller}: ';
const ORDER_PREFIX = 'comanda {order_id}: ';
const RETURN_PREFIX = 'retur {return_id}: ';

// Șabloanele mesajelor. „Total platit” (fără diacritice) e textul din pagina eMAG.
const MISSING_PAID_TOTAL = `${ORDER_SELLER_PREFIX}lipsește 'Total platit'`;
const MISSING_PRODUCTS_TOTAL = `${ORDER_SELLER_PREFIX}lipsește 'Total produse'`;
const PRODUCTS_SUM_MISMATCH = `${ORDER_SELLER_PREFIX}suma produselor ({sum}) ≠ 'Total produse' ({total})`;
const PAID_MISMATCH = `${ORDER_SELLER_PREFIX}total plătit ({paid}) ≠ componente ({expected})`;
const NO_PRODUCTS = `${ORDER_SELLER_PREFIX}niciun produs găsit`;
const ORDER_NUMBER_MISMATCH = `${ORDER_PREFIX}numărul din pagină ({found}) ≠ numărul cerut ({order_id})`;
const NAME_COUNT_MISMATCH = `${ORDER_PREFIX}{names} nume de produs în HTML ≠ {items} produse din linii; se folosesc numele din linii`;
const NO_SELLER_SECTION = `${ORDER_PREFIX}nicio secțiune de vânzător găsită`;
const UNKNOWN_STATUS = 'status necunoscut la comanda {order_id} ({seller}): {status_text}';
const PENDING_RETURNS_ONE = '1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat';
const PENDING_RETURNS_MANY = '{count} retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate';
const REFUNDS_WITHOUT_AMOUNT_ONE = '1 retur finalizat fără sumă restituită afișată';
const REFUNDS_WITHOUT_AMOUNT_MANY = '{count} retururi finalizate fără sumă restituită afișată';
const HEADER_MISMATCH_ONE = '1 comandă la care totalul din antet ≠ suma blocurilor';
const HEADER_MISMATCH_MANY = '{count} comenzi la care totalul din antet ≠ suma blocurilor';
const UNKNOWN_REFUND_MODE = `${RETURN_PREFIX}mod de restituire necunoscut („{mode}”), tratat ca bani primiți înapoi (adaugă-l în config/restituiri.json)`;
const HIGHLIGHT_MISSING = 'categoria evidențiată «{name}» nu există în config/categorii.json: totalul ei apare 0';
const FUNNEL_NOT_CLOSING = 'lanțul sumelor nu se închide: comandat {ordered} ≠ părți {parts}';
const PAID_NOT_CLOSING = 'lanțul sumelor plătite nu se închide ({check}): {computed} ≠ părți {parts}';
// Regulile noi merg în fișierul personal: actualizarea îl păstrează, pe când config/categorii.json e un fișier al programului și se înlocuiește la fiecare versiune nouă.
const UNCATEGORIZED = '{count} produse necategorizate (adaugă reguli în config/categorii.personal.json)';

// Cele două căi pe care paid_totals recalculează plătitul efectiv, ca să-l compare cu suma părților lui.
export const PAID_CHECK_CHAIN = 'comandat − scăzute + transport și taxe';
export const PAID_CHECK_BLOCKS = 'blocuri livrate − bani primiți înapoi';

/** Înlocuiește fiecare {nume} din șablon cu valoarea câmpului (ca str.format): valorile se inserează ca atare, fără să fie reinterpretate. */
function fill(template, fields) {
  return template.replace(/\{([a-z_]+)\}/g, (_, name) => String(fields[name]));
}

/**
 * Expresia (pentru fullmatch) care recunoaște exact textele produse din `template`: fiecare {câmp} din `fields` devine un grup cu numele lui
 * (la a doua apariție, o referință la el). Textul fix se scapă ca re.escape; DOTALL, ca în Python.
 */
function buildPattern(template, fields = {}) {
  let escaped = escapePython(template);
  for (const [name, groupPattern] of Object.entries(fields)) {
    const [first, ...others] = escaped.split(escapePython(`{${name}}`));
    escaped = first;
    others.forEach((part, index) => {
      escaped += (index === 0 ? `(?P<${name}>${groupPattern})` : `(?P=${name})`) + part;
    });
  }
  return new PyPattern(escaped, { dotAll: true });
}

// Numerele de comandă și de retur: doar cifre ASCII ([0-9], nu \d: \d acceptă și alte alfabete).
const DIGITS = '[0-9]+';
const PENDING_RETURNS_RE = [buildPattern(PENDING_RETURNS_ONE), buildPattern(PENDING_RETURNS_MANY, { count: DIGITS })];
const REFUNDS_WITHOUT_AMOUNT_RE = [buildPattern(REFUNDS_WITHOUT_AMOUNT_ONE), buildPattern(REFUNDS_WITHOUT_AMOUNT_MANY, { count: DIGITS })];
const HEADER_MISMATCH_RE = [buildPattern(HEADER_MISMATCH_ONE), buildPattern(HEADER_MISMATCH_MANY, { count: DIGITS })];
const COUNT_MESSAGES = [
  [KIND_PENDING_RETURN, PENDING_RETURNS_RE],
  [KIND_COMPLETED_RETURN_NO_REFUND, REFUNDS_WITHOUT_AMOUNT_RE],
  [KIND_HEADER_MISMATCH, HEADER_MISMATCH_RE],
];
const MISSING_PAID_TOTAL_RE = buildPattern(MISSING_PAID_TOTAL, { order_id: DIGITS, seller: '.+' }); // sufixul fix ancorează sfârșitul
const UNKNOWN_STATUS_RE = buildPattern(UNKNOWN_STATUS, { order_id: DIGITS, seller: '.+?', status_text: '.*' });
const ORDER_SELLER_RE = buildPattern(`${ORDER_SELLER_PREFIX}{detail}`, { order_id: DIGITS, seller: '.+?', detail: '.*' });
const ORDER_RE = buildPattern(`${ORDER_PREFIX}{detail}`, { order_id: DIGITS, detail: '.*' });
const RETURN_RE = buildPattern(`${RETURN_PREFIX}{detail}`, { return_id: DIGITS, detail: '.*' });

// Mesajele care spun că o cifră din raport poate fi greșită (produse lipsă sau cu sumă care nu se leagă, pagină greșită, status necunoscut, lanț care nu se închide,
// retur nepotrivit). Restul (total plătit ≠ componente, categorii, numărul de nume) sunt informative.
const AFFECTING_DETAIL_STARTS = ['suma produselor', 'niciun produs', 'nicio secțiune', 'numărul din pagină'];
const AFFECTING_TEXT_STARTS = ['status necunoscut la comanda', 'lanțul sumelor nu se închide', 'lanțul sumelor plătite nu se închide'];

/** Un avertisment citit înapoi din text, cu câmpurile din ParsedWarning (în ordinea lor): kind, text, order_ids, return_id, seller, count, detail, affects_totals. */
function parsedWarning(kind, text, { order_ids = [], return_id = null, seller = null, count = null, detail = '', affects_totals = false } = {}) {
  return { kind, text, order_ids, return_id, seller, count, detail, affects_totals };
}

/** Blocul nu afișează „Total platit” (suma plătită vânzătorului). */
export function formatMissingPaidTotal(orderId, seller) {
  return fill(MISSING_PAID_TOTAL, { order_id: orderId, seller });
}

/** Blocul nu afișează „Total produse”. */
export function formatMissingProductsTotal(orderId, seller) {
  return fill(MISSING_PRODUCTS_TOTAL, { order_id: orderId, seller });
}

/** Suma produselor citite ≠ „Total produse” din pagină (sumele apar în lei, nu în bani). */
export function formatProductsSumMismatch(orderId, seller, sumBani, totalBani) {
  return fill(PRODUCTS_SUM_MISMATCH, { order_id: orderId, seller, sum: formatLei(sumBani), total: formatLei(totalBani) });
}

/** „Total platit” ≠ produse + vouchere + transport + servicii (sumele apar în lei). */
export function formatPaidMismatch(orderId, seller, paidBani, expectedBani) {
  return fill(PAID_MISMATCH, { order_id: orderId, seller, paid: formatLei(paidBani), expected: formatLei(expectedBani) });
}

/** Blocul nu conține niciun produs recunoscut. */
export function formatNoProducts(orderId, seller) {
  return fill(NO_PRODUCTS, { order_id: orderId, seller });
}

/** Pagina cerută pentru o comandă arată alt număr de comandă. */
export function formatOrderNumberMismatch(requestedId, foundId) {
  return fill(ORDER_NUMBER_MISMATCH, { order_id: requestedId, found: foundId });
}

/** Numărul de nume de produs din HTML nu se potrivește cu produsele găsite din linii. */
export function formatNameCountMismatch(orderId, names, items) {
  return fill(NAME_COUNT_MISMATCH, { order_id: orderId, names, items });
}

/** Pagina comenzii nu are nicio secțiune de vânzător. */
export function formatNoSellerSection(orderId) {
  return fill(NO_SELLER_SECTION, { order_id: orderId });
}

/** Statusul blocului nu e recunoscut; textul lui apare între ghilimele (repr din Python). */
export function formatUnknownStatus(orderId, seller, statusText) {
  return fill(UNKNOWN_STATUS, { order_id: orderId, seller, status_text: pyRepr(statusText) });
}

/** Câte retururi sunt cerute dar fără rezultat (singular la 1). */
export function formatPendingReturns(count) {
  return count === 1 ? PENDING_RETURNS_ONE : fill(PENDING_RETURNS_MANY, { count });
}

/** Câte retururi finalizate nu arată suma restituită (singular la 1). */
export function formatRefundsWithoutAmount(count) {
  return count === 1 ? REFUNDS_WITHOUT_AMOUNT_ONE : fill(REFUNDS_WITHOUT_AMOUNT_MANY, { count });
}

/** Câte comenzi au totalul din antet diferit de suma blocurilor (singular la 1). */
export function formatHeaderMismatches(count) {
  return count === 1 ? HEADER_MISMATCH_ONE : fill(HEADER_MISMATCH_MANY, { count });
}

/** Modul de restituire al unui retur finalizat nu e în config/restituiri.json (se tratează ca bani înapoi); un mod gol apare ca „necompletat”. */
export function formatUnknownRefundMode(returnId, mode) {
  return fill(UNKNOWN_REFUND_MODE, { return_id: returnId, mode: pyStrip(mode || '') || 'necompletat' });
}

/** Categoria evidențiată nu există în regulile de categorii. */
export function formatHighlightCategoryMissing(name) {
  return fill(HIGHLIGHT_MISSING, { name });
}

/** Lanțul comandat → păstrat (la preț de listă) nu se închide (sumele apar în lei). */
export function formatFunnelNotClosing(orderedBani, partsBani) {
  return fill(FUNNEL_NOT_CLOSING, { ordered: formatLei(orderedBani), parts: formatLei(partsBani) });
}

/** Plătitul efectiv recalculat pe calea `check` (PAID_CHECK_*) ≠ suma părților lui (sumele apar în lei). */
export function formatPaidNotClosing(check, computedBani, partsBani) {
  return fill(PAID_NOT_CLOSING, { check, computed: formatLei(computedBani), parts: formatLei(partsBani) });
}

/** Câte produse nu au categorie. */
export function formatUncategorized(count) {
  return fill(UNCATEGORIZED, { count });
}

/** True dacă familia mesajului (după începutul textului) poate schimba o cifră din raport. */
function affectsTotals(text, detail, isReturnMessage = false) {
  return isReturnMessage || AFFECTING_TEXT_STARTS.some((start) => text.startsWith(start)) || AFFECTING_DETAIL_STARTS.some((start) => detail.startsWith(start));
}

/**
 * Citește un mesaj produs de format*; nu ridică excepții: un text necunoscut devine KIND_OTHER, fără comandă. Vânzătorul poate conține „:” sau virgule.
 * Mesajele „retur <număr>: …” (din return_matcher) se recunosc după început.
 */
export function parseOrderWarning(text) {
  for (const [kind, patterns] of COUNT_MESSAGES) {
    for (const pattern of patterns) {
      const match = pattern.fullmatch(text);
      if (match) return parsedWarning(kind, text, { count: pyInt(match.groupdict().count || '1') });
    }
  }
  let match = MISSING_PAID_TOTAL_RE.fullmatch(text);
  if (match) return parsedWarning(KIND_MISSING_PAID_TOTAL, text, { order_ids: [match.group('order_id')], seller: match.group('seller') });
  match = UNKNOWN_STATUS_RE.fullmatch(text);
  if (match) {
    return parsedWarning(KIND_OTHER, text, {
      order_ids: [match.group('order_id')], seller: match.group('seller'), detail: match.group('status_text'), affects_totals: affectsTotals(text, ''),
    });
  }
  match = ORDER_SELLER_RE.fullmatch(text);
  if (match) {
    return parsedWarning(KIND_OTHER, text, {
      order_ids: [match.group('order_id')], seller: match.group('seller'), detail: match.group('detail'), affects_totals: affectsTotals(text, match.group('detail')),
    });
  }
  match = ORDER_RE.fullmatch(text);
  if (match) {
    return parsedWarning(KIND_OTHER, text, { order_ids: [match.group('order_id')], detail: match.group('detail'), affects_totals: affectsTotals(text, match.group('detail')) });
  }
  match = RETURN_RE.fullmatch(text);
  if (match) {
    return parsedWarning(KIND_OTHER, text, {
      return_id: match.group('return_id'), detail: match.group('detail'), affects_totals: affectsTotals(text, match.group('detail'), true),
    });
  }
  return parsedWarning(KIND_OTHER, text, { detail: text, affects_totals: affectsTotals(text, text) });
}
