// Citește o pagină de detalii comandă eMAG și o transformă într-un Order (portul lui emag_spend/order_parser.py).
// Primește: numărul comenzii și liniile de text ale paginii (html_lines.js), plus, opțional, numele de produs citite structural din HTML. Dă înapoi: Order (cheile din to_dict, în ordinea câmpurilor)
// cu blocuri pe vânzător, produse, status, vouchere, transport, taxe, „Total platit” și „Total de plata”. Nu citește adresa, telefonul sau e-mailul.
// Ce nu se leagă (sume diferite) devine avertisment în Order.warnings (texte din warning_messages.js), nu excepție; ValueError doar dacă pagina nu e o comandă.
// Un bloc ANULAT nu are „Total platit” (pagina lui arată „Total de plata”): lipsa lui nu e avertisment; „Total de plata” se citește separat (due_bani), nu ca taxă.
// Sumele sunt întregi în bani; peste 2^53 funcțiile refuză (RangeError) în loc să rotunjească, spre deosebire de întregii nelimitați din Python.
import { CANCELLED, classifyStatus } from './block_status.js';
import { parseRoDatetime } from './dates_ro.js';
import { makeItem, makeOrder, makeSellerBlock } from './models.js';
import { findAmount, findLastAmount, parseFullAmount, roAmountToBani } from './money_ro.js';
import { PyValueError, pyInt, pyStrip } from './python_compat.js';
import { PyPattern } from './python_regex.js';
import { normalizeText } from './text_normalize.js';
import {
  formatMissingPaidTotal, formatMissingProductsTotal, formatNameCountMismatch, formatNoProducts, formatNoSellerSection, formatOrderNumberMismatch, formatPaidMismatch, formatProductsSumMismatch,
} from './warning_messages.js';

// Expresiile sunt cele din Python, cu aceleași steaguri, rulate prin PyPattern (\d, \s și \w cu înțelesul din Python, IGNORECASE ca în re).
const ORDER_HEADER = new PyPattern(String.raw`^Comanda nr\.?\s*(\d+)`, { ignoreCase: true });
const SELLER_HEADER = new PyPattern(String.raw`^Produse vandute (?:de (?P<a>.+?) si livrate de eMAG|si livrate de (?P<b>.+))$`, { ignoreCase: true });
const QTY = new PyPattern(String.raw`^(\d+)\s*buc\.?$`, { ignoreCase: true });
const PRICE_AND_QTY = new PyPattern(String.raw`^(?P<price>-?[\d.]+,\d{2})\s*Lei\s+(?P<qty>\d+)\s*buc\.?$`, { ignoreCase: true });
const PLACED = new PyPattern(String.raw`Plasata pe:\s*(.+?)(?=\s+Total:|$)`, { ignoreCase: true });
const HEADER_TOTAL = new PyPattern(String.raw`Total:\s*(-?[\d.]+,\d{2})\s*Lei`, { ignoreCase: true });
const WORD_CHARACTER = new PyPattern(String.raw`\w`);

// Linii care stau lângă numele produsului dar nu sunt numele lui (inclusiv atributele de sub nume, ex. „garantie electronica”). Plasă de siguranță pentru cazul în care numele nu se pot citi structural din HTML.
const AUX_PREFIXES = ['acorda o nota', 'cumpara din nou', 'adauga review', 'scrie un review', 'vezi produs', 'garantie electronica', 'garantie ', 'ghidul utilizatorului'];
// Linii care încheie zona de status a unui bloc.
const STATUS_STOP_PREFIXES = ['istoric livrare', 'modalitate livrare', 'date facturare', 'modalitate de plata', 'de prezentat la livrare', 'data de livrare', 'pentru:', 'factura', 'total produse'];
// Câte linii după titlul blocului pot fi status: destule pentru mesajele reale (3-4 linii), puține cât să nu citim produsele ca status.
const MAX_STATUS_LINES = 14;

/** True dacă `text` începe cu oricare dintre prefixe (str.startswith cu tuplu din Python). */
function startsWithAny(text, prefixes) {
  return prefixes.some((prefix) => text.startsWith(prefix));
}

/** Întregul `value` doar dacă e sigur (sub 2^53); Python are întregi nelimitați, JavaScript rotunjește în tăcere, deci o sumă prea mare ridică RangeError. */
function exactInteger(value) {
  if (!Number.isSafeInteger(value)) throw new RangeError(`suma ${value} depășește 2^53 bani și nu se poate reprezenta exact`);
  return value;
}

/** sum(values) din Python pe întregi, cu verificarea fiecărei sume parțiale (o sumă intermediară rotunjită ar putea ieși „sigură” la final). */
function sumExact(values) {
  let total = 0;
  for (const value of values) total = exactInteger(total + value);
  return total;
}

/** Numele vânzătorului dacă linia e titlu de bloc; altfel null. Un nume gol după strip() e un șir gol, fals ca în Python (la fel în status și în căutarea primului bloc). */
function sellerFromHeader(line) {
  const match = SELLER_HEADER.match(line);
  return match ? pyStrip(match.group('a') || match.group('b')) : null;
}

/** Suma unei etichete („Total produse: 222,98 Lei”), pe aceeași linie sau pe următoarea. „GRATUIT” înseamnă 0; null dacă nu găsește nicio sumă. */
function amountForLabel(lines, index) {
  const line = lines[index];
  const colon = line.indexOf(':');
  const after = colon >= 0 ? line.slice(colon + 1) : '';
  if (normalizeText(after || line).includes('gratuit')) return 0;
  const amount = findLastAmount(line); // eticheta și suma pe aceeași linie (cu sau fără „:”)
  if (amount !== null) return amount;
  if (WORD_CHARACTER.search(after) !== null) return null; // după „:” e text propriu fără sumă (nu doar un al doilea „:”): nu citim linia următoare
  if (index + 1 < lines.length) { // așezarea cu valoarea pe linia următoare
    const following = lines[index + 1];
    if (normalizeText(following).includes('gratuit')) return 0;
    const full = parseFullAmount(following);
    return full !== null ? full : findAmount(following);
  }
  return null;
}

/** Numele produsului: cea mai apropiată linie de dinaintea prețului care nu e auxiliară; gol dacă nu există. */
function itemName(lines, priceIndex) {
  let index = priceIndex - 1;
  while (index >= 0 && startsWithAny(normalizeText(lines[index]), AUX_PREFIXES)) index -= 1;
  return index >= 0 ? lines[index] : '';
}

/** Liniile de status de după titlul blocului, până la primul marcaj de oprire sau la un nou titlu de bloc, lipite cu „ | ”. */
function statusText(lines, headerIndex) {
  const collected = [];
  for (const line of lines.slice(headerIndex + 1, headerIndex + 1 + MAX_STATUS_LINES)) {
    if (startsWithAny(normalizeText(line), STATUS_STOP_PREFIXES) || sellerFromHeader(line)) break;
    collected.push(line);
  }
  return collected.join(' | ');
}

/** Verifică invariantele unui bloc și notează avertismente; poate corecta prețurile afișate pe bucată în loc de pe linie (modifică blocul). */
function checkBlock(orderId, block, warnings) {
  if (block.products_total_bani === null) {
    warnings.push(formatMissingProductsTotal(orderId, block.seller));
  } else {
    const asTotals = sumExact(block.items.map((item) => item.line_total_bani));
    const asUnits = sumExact(block.items.map((item) => exactInteger(item.line_total_bani * item.qty)));
    if (asTotals !== block.products_total_bani) {
      if (asUnits === block.products_total_bani) {
        for (const item of block.items) item.line_total_bani = exactInteger(item.line_total_bani * item.qty); // prețul afișat era pe bucată, nu pe linie
      } else {
        warnings.push(formatProductsSumMismatch(orderId, block.seller, asTotals, block.products_total_bani));
      }
    }
  }
  if (block.paid_bani === null) {
    if (block.status !== CANCELLED) warnings.push(formatMissingPaidTotal(orderId, block.seller)); // la un bloc anulat „Total platit” nu există: nu e o problemă de citit
  } else if (block.products_total_bani !== null && block.status !== CANCELLED) {
    // la blocurile anulate „Total platit” e 0 sau parțial (banii s-au rambursat): nu se verifică
    const expected = sumExact([block.products_total_bani, sumExact(block.vouchers_bani), block.shipping_bani ?? 0, sumExact(block.services_bani), sumExact(block.other_bani)]);
    if (expected !== block.paid_bani) warnings.push(formatPaidMismatch(orderId, block.seller, block.paid_bani, expected));
  }
  if (block.items.length === 0) warnings.push(formatNoProducts(orderId, block.seller));
}

/** Pune numele citite din HTML (`.product-description`) pe produsele găsite din linii, doar dacă numărul lor se potrivește cu numărul produselor; altfel rămân numele din linii și se notează un avertisment. */
function applyStructuralNames(orderId, blocks, names, warnings) {
  const items = blocks.flatMap((block) => block.items);
  if (names.length !== items.length) {
    warnings.push(formatNameCountMismatch(orderId, names.length, items.length));
    return;
  }
  items.forEach((item, index) => {
    item.name = names[index];
  });
}

/**
 * Construiește Order din liniile paginii de detalii; ValueError (PyValueError) dacă pagina nu are „Comanda nr.” (sesiune expirată?).
 * `productNames` (opțional) = numele produselor citite structural din HTML; când sunt date și se potrivesc ca număr, înlocuiesc numele deduse din linii.
 */
export function parseOrder(orderId, lines, productNames = null) {
  const start = lines.findIndex((line) => ORDER_HEADER.match(line) !== null);
  if (start < 0) throw new PyValueError(`pagina comenzii ${orderId} nu conține 'Comanda nr.' (sesiune expirată?)`);
  const warnings = [];
  const foundId = ORDER_HEADER.match(lines[start]).group(1);
  if (foundId !== orderId) warnings.push(formatOrderNumberMismatch(orderId, foundId));

  let firstBlock = lines.length;
  for (let index = start; index < lines.length; index += 1) {
    if (sellerFromHeader(lines[index])) {
      firstBlock = index;
      break;
    }
  }
  const headText = lines.slice(start, firstBlock).join(' ');
  const placedMatch = PLACED.search(headText);
  const placedText = placedMatch ? pyStrip(placedMatch.group(1)) : '';
  const totalMatch = HEADER_TOTAL.search(headText);
  const headerTotal = totalMatch ? roAmountToBani(totalMatch.group(1)) : null;

  const blocks = [];
  let current = null;
  let totalsZone = false; // între „Total produse” și „Total platit”
  for (let index = firstBlock; index < lines.length; index += 1) {
    const line = lines[index];
    const seller = sellerFromHeader(line);
    if (seller !== null) {
      const blockStatusText = statusText(lines, index);
      current = makeSellerBlock({ seller, status: classifyStatus(blockStatusText), status_text: blockStatusText, has_storno: false });
      blocks.push(current);
      totalsZone = false;
      continue;
    }
    if (current === null) continue;
    const normalized = normalizeText(line);
    if (normalized.includes('factura storno')) current.has_storno = true;

    if (current.products_total_bani === null) {
      const priceQty = PRICE_AND_QTY.match(line);
      const qtyOnly = QTY.match(line);
      if (priceQty) {
        current.items.push(makeItem(itemName(lines, index), roAmountToBani(priceQty.group('price')), pyInt(priceQty.group('qty'))));
        continue;
      }
      if (qtyOnly && index >= 1) {
        const price = parseFullAmount(lines[index - 1]);
        if (price !== null) {
          current.items.push(makeItem(itemName(lines, index - 1), price, pyInt(qtyOnly.group(1))));
          continue;
        }
      }
    }

    if (normalized.startsWith('total produse')) {
      current.products_total_bani = amountForLabel(lines, index);
      totalsZone = true;
    } else if (normalized.startsWith('total platit')) {
      current.paid_bani = amountForLabel(lines, index);
      totalsZone = false;
    } else if (normalized.startsWith('total de plata')) {
      current.due_bani = amountForLabel(lines, index);
      totalsZone = false;
    } else if (normalized.startsWith('reducere')) {
      const amount = amountForLabel(lines, index);
      if (amount !== null) current.vouchers_bani.push(amount);
    } else if (normalized.startsWith('cost livrare')) {
      current.shipping_bani = amountForLabel(lines, index);
    } else if (normalized.startsWith('servicii operationale')) {
      const amount = amountForLabel(lines, index);
      if (amount !== null) current.services_bani.push(amount);
    } else if (totalsZone && line.includes(':')) {
      const amount = findLastAmount(line);
      if (amount !== null) current.other_bani.push(amount);
    }
  }

  if (blocks.length === 0) warnings.push(formatNoSellerSection(orderId));
  if (productNames !== null) applyStructuralNames(orderId, blocks, productNames, warnings);
  for (const block of blocks) checkBlock(orderId, block, warnings);

  return makeOrder({ order_id: orderId, placed_text: placedText, placed_at: parseRoDatetime(placedText), header_total_bani: headerTotal, blocks, warnings });
}
