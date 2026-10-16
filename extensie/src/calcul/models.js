// Structurile de date ale proiectului: produs, bloc de vânzător, comandă, retur, linie de registru (portul lui emag_spend/models.py).
// Toate sumele sunt în BANI (întregi). Structurile simple (Item, SellerBlock, Order, ReturnRequest) sunt obiecte obișnuite cu cheile din to_dict, în ordinea câmpurilor din Python,
// ca JSON-ul lor să fie identic; LineOutcome e o clasă cu aceleași câmpuri și cu proprietățile calculate ca getteri cu numele Python (kept_bani, kept_paid_bani...).
// Nu conțin date personale (parserele nu le citesc). Ce NU face: nu parsează și nu calculează totaluri (parserele și spend_analysis).
import { cpSlice, floorDivBig, maxBy, pyInt, pyRepr } from './python_compat.js';
import { splitProportionally } from './proportional_split.js';

// Câmpurile cu bucăți pe stări ale unei linii (LineOutcome), în ordinea în care se împarte valoarea ei.
const STATE_QTY_FIELDS = ['kept_qty', 'returned_qty', 'cancelled_qty', 'pending_qty', 'paid_only_qty', 'unknown_qty'];

/** KeyError din Python: mesajul este repr-ul cheii lipsă. */
export class PyKeyError extends Error {
  constructor(key) {
    super(pyRepr(key));
    this.name = 'KeyError';
  }
}

/** Numele lipsă ca în mesajele Python: 'a'; 'a' and 'b'; 'a', 'b', and 'c'. */
function listNames(names) {
  const quoted = names.map((name) => `'${name}'`);
  if (quoted.length === 1) return quoted[0];
  if (quoted.length === 2) return `${quoted[0]} and ${quoted[1]}`;
  return `${quoted.slice(0, -1).join(', ')}, and ${quoted[quoted.length - 1]}`;
}

/**
 * Construiește un obiect cu câmpurile `fieldNames` în ordinea lor, ca un dataclass din Python: `defaults` dă valorile câmpurilor opționale (funcții, ca fiecare listă să fie nouă),
 * o cheie în plus sau lipsă ridică TypeError cu mesajul din Python („Item.__init__() got an unexpected keyword argument 'x'”).
 */
function buildFields(className, fieldNames, defaults, input) {
  const unexpected = Object.keys(input).find((key) => !fieldNames.includes(key));
  if (unexpected !== undefined) throw new TypeError(`${className}.__init__() got an unexpected keyword argument ${pyRepr(unexpected)}`);
  const missing = fieldNames.filter((name) => !Object.hasOwn(input, name) && !Object.hasOwn(defaults, name));
  if (missing.length > 0) {
    throw new TypeError(`${className}.__init__() missing ${missing.length} required positional argument${missing.length > 1 ? 's' : ''}: ${listNames(missing)}`);
  }
  const fields = {};
  for (const name of fieldNames) fields[name] = Object.hasOwn(input, name) ? input[name] : defaults[name]();
  return fields;
}

const ITEM_FIELDS = ['name', 'line_total_bani', 'qty'];
const SELLER_BLOCK_FIELDS = [
  'seller', 'status', 'status_text', 'has_storno', 'items', 'products_total_bani', 'vouchers_bani', 'shipping_bani', 'services_bani', 'other_bani', 'paid_bani', 'due_bani',
];
const SELLER_BLOCK_DEFAULTS = {
  items: () => [], products_total_bani: () => null, vouchers_bani: () => [], shipping_bani: () => null, services_bani: () => [], other_bani: () => [],
  paid_bani: () => null, due_bani: () => null,
};
const ORDER_FIELDS = ['order_id', 'placed_text', 'placed_at', 'header_total_bani', 'blocks', 'warnings'];
const ORDER_DEFAULTS = { blocks: () => [], warnings: () => [] };
const RETURN_FIELDS = ['return_id', 'detail_path', 'order_ids', 'product_names', 'steps', 'refund_bani', 'refund_mode', 'completed', 'cancelled'];

/** O linie de produs dintr-o comandă: nume, total pe linie (preț x cantitate, în bani) și cantitate. */
export function makeItem(name, lineTotalBani, qty) {
  return { name, line_total_bani: lineTotalBani, qty };
}

/** Un bloc de comandă livrat de un vânzător (eMAG sau marketplace); câmpurile opționale au valorile implicite din Python (liste goale, null). */
export function makeSellerBlock(fields) {
  return buildFields('SellerBlock', SELLER_BLOCK_FIELDS, SELLER_BLOCK_DEFAULTS, fields);
}

/** O comandă cu toate blocurile ei; `warnings` = nepotriviri găsite la parsare. */
export function makeOrder(fields) {
  return buildFields('Order', ORDER_FIELDS, ORDER_DEFAULTS, fields);
}

/** O cerere de retur, cu starea ei finală; toate câmpurile sunt obligatorii. */
export function makeReturnRequest(fields) {
  return buildFields('ReturnRequest', RETURN_FIELDS, {}, fields);
}

/** Anul comenzii (proprietatea Order.year din Python): primele 4 caractere din `placed_at` ca întreg, sau null dacă data lipsește. */
export function orderYear(order) {
  return order.placed_at ? pyInt(cpSlice(order.placed_at, 0, 4)) : null;
}

const LINE_OUTCOME_FIELDS = [
  'order_id', 'placed_at', 'seller', 'name', 'qty', 'line_total_bani', 'block_status', 'kept_qty', 'returned_qty', 'cancelled_qty', 'pending_qty', 'paid_only_qty',
  'unknown_qty', 'returned_from_cancelled_qty', 'category', 'rule', 'return_ids', 'paid_total_bani', 'credit_returned_qty',
];
const LINE_OUTCOME_DEFAULTS = {
  kept_qty: () => 0, returned_qty: () => 0, cancelled_qty: () => 0, pending_qty: () => 0, paid_only_qty: () => 0, unknown_qty: () => 0, returned_from_cancelled_qty: () => 0,
  category: () => '', rule: () => '', return_ids: () => [], paid_total_bani: () => null, credit_returned_qty: () => 0,
};

/**
 * Soarta unei linii de produs: câte unități au fost păstrate, returnate, anulate etc. Invariant: kept + returned + cancelled + pending + paid_only + unknown = qty.
 * Sumele pe stări există de două ori: la preț de listă (`*_bani`, din `line_total_bani`) și plătite (`*_paid_bani`, din `paid_value_bani`, adică după reduceri);
 * în ambele, părțile stărilor se adună exact la valoarea liniei. Se construiește cu un obiect cu numele câmpurilor din Python.
 */
export class LineOutcome {
  constructor(fields) {
    Object.assign(this, buildFields('LineOutcome', LINE_OUTCOME_FIELDS, LINE_OUTCOME_DEFAULTS, fields));
  }

  /** Câmpurile ca obiect obișnuit, în ordinea din Python (asdict); proprietățile calculate nu intră. */
  toDict() {
    const copy = {};
    for (const name of LINE_OUTCOME_FIELDS) copy[name] = Array.isArray(this[name]) ? [...this[name]] : this[name];
    return copy;
  }

  /** Partea din `totalBani` care revine la `partQty` din cele `qty` unități, rotunjită la cel mai apropiat ban; calculul e exact (BigInt) chiar dacă produsul depășește 2^53. */
  _shareOf(totalBani, partQty) {
    if (this.qty <= 0) return 0;
    const numerator = BigInt(totalBani) * BigInt(partQty) * 2n + BigInt(this.qty);
    return Number(floorDivBig(numerator, BigInt(this.qty) * 2n));
  }

  /** Partea din valoarea de listă a liniei care revine la `partQty` unități (rotunjit). */
  _share(partQty) {
    return this._shareOf(this.line_total_bani, partQty);
  }

  /** Valoarea de listă a bucăților returnate. */
  get returned_bani() {
    return this._share(this.returned_qty);
  }

  /** Valoarea de listă a bucăților anulate. */
  get cancelled_bani() {
    return this._share(this.cancelled_qty);
  }

  /** Valoarea de listă a bucăților încă în curs. */
  get pending_bani() {
    return this._share(this.pending_qty);
  }

  /** Valoarea de listă a bucăților plătite fără livrare. */
  get paid_only_bani() {
    return this._share(this.paid_only_qty);
  }

  /** Valoarea de listă a bucăților cu status nerecunoscut. */
  get unknown_bani() {
    return this._share(this.unknown_qty);
  }

  /** Restul valorii liniei (garantează că suma părților = totalul liniei). */
  get kept_bani() {
    return this.line_total_bani - this.returned_bani - this.cancelled_bani - this.pending_bani - this.paid_only_bani - this.unknown_bani;
  }

  /** Prețul de listă al liniei ca produs: o linie negativă (reducere scrisă ca produs) valorează 0. */
  get list_value_bani() {
    return Math.max(0, this.line_total_bani);
  }

  /**
   * `totalBani` (>= 0) împărțit exact pe stările liniei, fără parte negativă și fără ban pierdut: fiecare stare primește partea ei rotunjită la ban, iar starea „rest”
   * (păstrat, dacă există, altfel cea cu cele mai multe bucăți) primește diferența. Dacă rotunjirile ar depăși totalul, împărțirea devine cea proporțională exactă.
   */
  _partsOf(totalBani) {
    const quantities = Object.fromEntries(STATE_QTY_FIELDS.map((name) => [name, this[name]]));
    if (this.qty <= 0 || !Object.values(quantities).some((quantity) => quantity !== 0)) return Object.fromEntries(STATE_QTY_FIELDS.map((name) => [name, 0]));
    const rest = quantities.kept_qty > 0 ? 'kept_qty' : maxBy(STATE_QTY_FIELDS, (name) => quantities[name]);
    const parts = {};
    let others = 0;
    for (const name of STATE_QTY_FIELDS) {
      if (name === rest) continue;
      parts[name] = this._shareOf(totalBani, quantities[name]);
      others += parts[name];
    }
    parts[rest] = totalBani - others;
    if (parts[rest] < 0) {
      const shares = splitProportionally(totalBani, STATE_QTY_FIELDS.map((name) => quantities[name]));
      return Object.fromEntries(STATE_QTY_FIELDS.map((name, index) => [name, shares[index]]));
    }
    return parts;
  }

  /** Partea păstrată din `list_value_bani` (părțile stărilor se adună exact, niciuna negativă). */
  get kept_list_bani() {
    return this._partsOf(this.list_value_bani).kept_qty;
  }

  /** Cât s-a plătit (sau, la un bloc anulat, cât s-ar fi plătit) pe linia întreagă, după reduceri. */
  get paid_value_bani() {
    return this.paid_total_bani !== null ? this.paid_total_bani : this.list_value_bani;
  }

  /** Partea plătită a bucăților returnate (cu bani înapoi sau cu voucher/sold). */
  get returned_paid_bani() {
    return this._partsOf(this.paid_value_bani).returned_qty;
  }

  /** Partea plătită (la un bloc anulat: cât s-ar fi plătit) a bucăților anulate. */
  get cancelled_paid_bani() {
    return this._partsOf(this.paid_value_bani).cancelled_qty;
  }

  /** Partea plătită a bucăților încă în curs (nelivrate). */
  get pending_paid_bani() {
    return this._partsOf(this.paid_value_bani).pending_qty;
  }

  /** Partea plătită a bucăților plătite fără livrare de produs (de ex. asigurări). */
  get paid_only_paid_bani() {
    return this._partsOf(this.paid_value_bani).paid_only_qty;
  }

  /** Partea plătită a bucăților cu status nerecunoscut. */
  get unknown_paid_bani() {
    return this._partsOf(this.paid_value_bani).unknown_qty;
  }

  /** Partea păstrată din valoarea plătită (părțile stărilor se adună exact la `paid_value_bani`, niciuna negativă). */
  get kept_paid_bani() {
    return this._partsOf(this.paid_value_bani).kept_qty;
  }
}

/** Copie profundă JSON-serializabilă a oricărei structuri de mai sus (asdict din Python): liste, obiecte, Map-uri și LineOutcome ajung la obiecte simple. */
export function toDict(value) {
  if (value instanceof LineOutcome) return value.toDict();
  if (Array.isArray(value)) return value.map(toDict);
  if (value instanceof Map) return new Map([...value].map(([key, item]) => [key, toDict(item)]));
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, toDict(item)]));
  return value;
}

/** Valoarea cheii `key` din `data`; KeyError ca în Python dacă lipsește. */
function requireKey(data, key) {
  if (!Object.hasOwn(data, key)) throw new PyKeyError(key);
  return data[key];
}

/** Reconstruiește o comandă salvată cu toDict(); o cheie lipsă din `blocks` / `items` ridică KeyError, una în plus sau lipsă din câmpuri TypeError, ca în Python. */
export function orderFromDict(data) {
  const blocks = [];
  for (const block of requireKey(data, 'blocks')) {
    const items = requireKey(block, 'items').map((item) => buildFields('Item', ITEM_FIELDS, {}, item));
    blocks.push(buildFields('SellerBlock', SELLER_BLOCK_FIELDS, SELLER_BLOCK_DEFAULTS, { ...block, items }));
  }
  return buildFields('Order', ORDER_FIELDS, ORDER_DEFAULTS, { ...data, blocks });
}

/** Reconstruiește un retur salvat cu toDict(); toate câmpurile sunt obligatorii. */
export function returnFromDict(data) {
  return buildFields('ReturnRequest', RETURN_FIELDS, {}, data);
}
