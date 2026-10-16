// Grupează avertismentele în `warnings_detail`: grupe cu titlu, explicație și lista comenzilor (portul lui emag_spend/warning_details.py).
// Primește: textele `warnings`, comenzile, retururile, comenzile cu antetul ≠ suma blocurilor și textele din config/avertismente.json (obiectul, validat de loadWarningTexts). Dă înapoi:
// grupele din schema `warnings_detail` (doar cele cu rânduri, în ordinea din ALL_KINDS), fiecare cu `count == items.length`. Mesajele despre comenzi se citesc din text; retururile
// și antetele se iau din date, nu din numărul din text. Opțional `log` (metodele info și warning, ca RunLog) primește avertismentul despre un număr care nu se potrivește cu lista.
// Ce NU face: nu calculează totaluri, nu modifică `warnings`, nu citește fișiere.
import { CANCELLED, UNKNOWN } from './block_status.js';
import { formatLei } from './money_ro.js';
import { returnUrl } from './order_links.js';
import { PyValueError, cpLength, cpSlice, minBy, pyRepr, pyStrip, sortedBy } from './python_compat.js';
import { formatterParse, pyFormat } from './python_format.js';
import { PyPattern } from './python_regex.js';
import {
  ALL_KINDS, KIND_COMPLETED_RETURN_NO_REFUND, KIND_HEADER_MISMATCH, KIND_MISSING_PAID_TOTAL, KIND_OTHER, KIND_PENDING_RETURN, parseOrderWarning,
} from './warning_messages.js';

const LOG_MODULE = 'warning_details';
// Câte nume de produs intră în rândul unui retur înainte de „încă N”: rândul rămâne scurt și când un retur are multe produse (lista completă e în retururi.json).
export const MAX_PRODUCT_NAMES_IN_TEXT = 3;
// Câmpurile pe care codul le dă șablonului `item_text` al fiecărei grupe. Un șablon editat de mână cu alt câmp ar strica raportul, deci se respinge la încărcare (cu configurarea și grupa numite).
export const ITEM_TEXT_FIELDS = Object.freeze({
  [KIND_MISSING_PAID_TOTAL]: Object.freeze(['seller', 'status']),
  [KIND_HEADER_MISMATCH]: Object.freeze(['header', 'blocks']),
  [KIND_PENDING_RETURN]: Object.freeze(['products', 'step']),
  [KIND_COMPLETED_RETURN_NO_REFUND]: Object.freeze(['products', 'mode']),
  [KIND_OTHER]: Object.freeze(['text']),
});
const GROUP_TEXT_KEYS = ['title', 'explanation', 'what_to_do', 'item_text'];
const DEFAULT_TEXT_KEYS = ['produse_lipsa', 'pas_lipsa', 'mod_lipsa', 'produse_in_plus', 'antet_cu_bloc_anulat'];
const SECTIONS = ['grupe', 'etichete_status', 'valori_implicite'];
// Numele unui câmp de șablon: identificator Python (XID_Start sau „_”, apoi XID_Continue), ca str.isidentifier().
const IDENTIFIER = /^[\p{XID_Start}_]\p{XID_Continue}*$/u;
const ISO_DAY = new PyPattern('[0-9]{4}-[0-9]{2}-[0-9]{2}');
// Câte caractere are ziua „AAAA-LL-ZZ” din data ISO a comenzii.
const DAY_LENGTH = 10;

/** Adevărat pentru un obiect JSON (dict în Python): nu null, nu listă. */
function isDict(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Valoarea cheii `key` dintr-un obiect, sau undefined dacă lipsește (dict.get din Python). */
function getKey(object, key) {
  return Object.hasOwn(object, key) ? object[key] : undefined;
}

/** Ridică ValueError dacă șablonul are acolade greșite, formă de câmp complicată sau un câmp nepermis. */
function checkItemTemplate(source, kind, template) {
  const allowed = ITEM_TEXT_FIELDS[kind];
  let parts;
  try {
    parts = [...formatterParse(template)];
  } catch (error) {
    if (error instanceof PyValueError) throw new PyValueError(`${source}: grupa ${pyRepr(kind)}, item_text are acolade greșite (${error.message})`);
    throw error;
  }
  const fields = parts.filter(([, name]) => name !== null);
  if (fields.some(([, name, spec, conversion]) => spec !== '' || conversion !== null || !IDENTIFIER.test(name))) {
    throw new PyValueError(`${source}: grupa ${pyRepr(kind)}, item_text: folosește doar câmpuri simple, ca {${allowed[0]}}`);
  }
  const unknown = sortedBy([...new Set(fields.map(([, name]) => name))].filter((name) => !allowed.includes(name)));
  if (unknown.length > 0) {
    throw new PyValueError(`${source}: grupa ${pyRepr(kind)}, item_text are câmpuri necunoscute ${pyRepr(unknown)}; cele permise: ${pyRepr([...allowed])}`);
  }
}

/**
 * Validează obiectul din config/avertismente.json și îl întoarce; ValueError (cu `source`, implicit numele fișierului, și grupa) la o grupă sau cheie lipsă, un tip greșit sau un șablon cu un câmp pe care codul nu-l dă:
 * un text greșit nu trebuie să afle abia când apare avertismentul. `produse_in_plus` se încearcă efectiv cu `count`; formele pe care extensia nu le completează (atribut, index, specificator,
 * conversie) sunt refuzate aici, deși Python le-ar accepta.
 */
export function loadWarningTexts(data, source = 'avertismente.json') {
  if (!isDict(data) || !SECTIONS.every((key) => isDict(getKey(data, key)))) {
    throw new PyValueError(`${source}: trebuie să fie un obiect cu cheile-obiect ${SECTIONS.map((key) => pyRepr(key)).join(', ')}`);
  }
  for (const kind of ALL_KINDS) {
    const group = getKey(data.grupe, kind);
    if (!isDict(group)) throw new PyValueError(`${source}: lipsește grupa ${pyRepr(kind)} din 'grupe'`);
    for (const key of GROUP_TEXT_KEYS) {
      const value = getKey(group, key);
      if (typeof value !== 'string' || pyStrip(value) === '') throw new PyValueError(`${source}: grupa ${pyRepr(kind)} trebuie să aibă textul nevid ${pyRepr(key)}`);
    }
    if (typeof getKey(group, 'affects_totals') !== 'boolean') throw new PyValueError(`${source}: grupa ${pyRepr(kind)}: 'affects_totals' trebuie să fie true sau false`);
    checkItemTemplate(source, kind, group.item_text);
  }
  if (!Object.values(data.etichete_status).every((value) => typeof value === 'string')) {
    throw new PyValueError(`${source}: 'etichete_status' trebuie să fie un obiect cu valori text`);
  }
  for (const key of DEFAULT_TEXT_KEYS) {
    if (typeof getKey(data.valori_implicite, key) !== 'string') throw new PyValueError(`${source}: 'valori_implicite' trebuie să aibă textul ${pyRepr(key)}`);
  }
  try {
    pyFormat(data.valori_implicite.produse_in_plus, { count: 1 });
  } catch (error) {
    // KeyError, IndexError și ValueError din Python (plus formele neacceptate de extensie, care sunt Error simplu) devin aceeași ValueError, cu motivul în paranteză
    throw new PyValueError(`${source}: 'produse_in_plus' poate folosi doar câmpul {count} (${error.message})`);
  }
  return data;
}

/**
 * Avertismentele salvate pe comandă, fără „lipsește Total platit” scris în plus pentru blocuri ANULATE. Un comenzi.json salvat de o versiune veche are acel mesaj și la blocurile
 * anulate (unde „Total platit” nu există): se scot doar mesajele peste numărul blocurilor ne-anulate fără sumă ale aceluiași vânzător.
 */
export function currentOrderWarnings(order) {
  const missing = order.warnings.map((text) => [text, parseOrderWarning(text)]);
  const count = (map, key) => map.get(key) ?? 0;
  const bump = (map, key) => map.set(key, count(map, key) + 1);
  const sent = new Map();
  for (const [, parsed] of missing) if (parsed.kind === KIND_MISSING_PAID_TOTAL) bump(sent, parsed.seller);
  const legitimate = new Map();
  const cancelled = new Map();
  for (const block of order.blocks) {
    if (block.paid_bani !== null) continue;
    bump(block.status !== CANCELLED ? legitimate : cancelled, block.seller);
  }
  const toDrop = new Map([...sent].map(([seller, total]) => [seller, Math.min(count(cancelled, seller), Math.max(0, total - count(legitimate, seller)))]));
  const kept = [];
  for (const [text, parsed] of missing) {
    if (parsed.kind === KIND_MISSING_PAID_TOTAL && toDrop.get(parsed.seller) > 0) {
      toDrop.set(parsed.seller, toDrop.get(parsed.seller) - 1);
      continue;
    }
    kept.push(text);
  }
  return kept;
}

/** Retururile cerute care nu s-au finalizat și nici nu au fost anulate (produsul rămâne păstrat). */
export function returnsWithoutResult(returns) {
  return returns.filter((ret) => !ret.completed && !ret.cancelled);
}

/** Retururile finalizate la care pagina nu arată suma restituită. */
export function completedReturnsWithoutAmount(returns) {
  return returns.filter((ret) => ret.completed && ret.refund_bani === null);
}

/** Ziua „AAAA-LL-ZZ” dintr-o dată ISO, sau null dacă data lipsește sau are altă formă. */
function dayOf(placedAt) {
  const day = cpSlice(placedAt || '', 0, DAY_LENGTH);
  return ISO_DAY.fullmatch(day) !== null ? day : null;
}

/** Cea mai veche zi cunoscută dintre comenzile date (null dacă nu se știe niciuna). */
function earliestDay(orderIds, ordersById) {
  const known = orderIds.filter((id) => ordersById.has(id)).map((id) => dayOf(ordersById.get(id).placed_at)).filter((day) => day);
  return known.length > 0 ? minBy(known) : null;
}

/** Numele produselor dintr-un retur, cel mult MAX_PRODUCT_NAMES_IN_TEXT, apoi „încă N”. */
function productsText(names, defaults) {
  if (names.length === 0) return defaults.produse_lipsa;
  const shown = names.slice(0, MAX_PRODUCT_NAMES_IN_TEXT).join('; ');
  const extra = names.length - MAX_PRODUCT_NAMES_IN_TEXT;
  return shown + (extra > 0 ? `; ${pyFormat(defaults.produse_in_plus, { count: extra })}` : '');
}

/**
 * Un rând al unei grupe (schema `warnings_detail`); `return_url` e o cheie în plus: adresa returului nu se construiește din număr, deci vine gata făcută
 * (null dacă nu e retur sau calea lui nu e validă).
 */
function item(orderIds, returnId, seller, status, placedAt, text, ret = null) {
  return {
    order_ids: [...orderIds],
    return_id: returnId,
    seller,
    status,
    placed_at: placedAt,
    text,
    return_url: ret !== null ? returnUrl(ret.return_id, ret.detail_path) : null,
  };
}

/** Ordinea rândurilor: cronologic (fără dată la sfârșit), apoi după număr de comandă și retur. */
function sortKey(row) {
  const first = row.order_ids.length > 0 ? row.order_ids[0] : '';
  return [row.placed_at === null, row.placed_at || '', cpLength(first), first, row.return_id || '', row.text];
}

/** Statusul, în română, al blocului la care se referă al `occurrence`-lea mesaj despre acel vânzător (dacă vânzătorul are mai multe blocuri fără sumă, se iau pe rând). */
function blockStatusLabel(order, seller, labels, occurrence) {
  const blocks = (order ? order.blocks : []).filter((block) => block.seller === seller);
  const unpaid = blocks.filter((block) => block.paid_bani === null && block.status !== CANCELLED);
  const candidates = unpaid.length > 0 ? unpaid : blocks;
  if (candidates.length === 0) return null;
  const chosen = candidates[Math.min(occurrence, candidates.length - 1)];
  return Object.hasOwn(labels, chosen.status) ? labels[chosen.status] : chosen.status;
}

/** Rândul unui avertisment citit din text: „lipsește Total platit” sau orice alt mesaj (`seen` numără mesajele văzute pe (comandă, vânzător)). */
function warningItem(parsed, texts, ordersById, returnsById, seen) {
  const groups = texts.grupe;
  const placed = earliestDay([...parsed.order_ids], ordersById);
  if (parsed.kind === KIND_MISSING_PAID_TOTAL) {
    const key = JSON.stringify([parsed.order_ids[0], parsed.seller]);
    const order = ordersById.get(parsed.order_ids[0]);
    let status = blockStatusLabel(order, parsed.seller || '', texts.etichete_status, seen.get(key) ?? 0);
    seen.set(key, (seen.get(key) ?? 0) + 1);
    status = status || getKey(texts.etichete_status, UNKNOWN) || ''; // comanda nu e în listă: nu lăsăm paranteze goale
    const text = pyFormat(groups[parsed.kind].item_text, { seller: parsed.seller, status });
    return item(parsed.order_ids, null, parsed.seller, status, placed, text);
  }
  const ret = parsed.return_id ? returnsById.get(parsed.return_id) ?? null : null;
  const text = pyFormat(groups[KIND_OTHER].item_text, { text: parsed.text });
  return item(parsed.order_ids, parsed.return_id, parsed.seller, null, placed, text, ret);
}

/** Rândul unui retur (fără rezultat sau finalizat fără sumă), cu ultimul pas ca status. */
function returnItem(ret, kind, texts, ordersById) {
  const defaults = texts.valori_implicite;
  const step = ret.steps.length > 0 ? ret.steps[ret.steps.length - 1] : null;
  const fields = {
    products: productsText(ret.product_names, defaults),
    step: step || defaults.pas_lipsa,
    mode: ret.refund_mode || defaults.mod_lipsa,
  };
  const text = pyFormat(texts.grupe[kind].item_text, Object.fromEntries(ITEM_TEXT_FIELDS[kind].map((name) => [name, fields[name]])));
  return item(ret.order_ids, ret.return_id, null, step, earliestDay(ret.order_ids, ordersById), text, ret);
}

/** Rândul unei comenzi cu totalul din antet diferit de suma blocurilor (cu cele două sume și, dacă are un bloc anulat, explicația). */
function headerItem(entry, texts, ordersById) {
  const order = ordersById.get(entry.order_id);
  let text = pyFormat(texts.grupe[KIND_HEADER_MISMATCH].item_text, { header: formatLei(entry.header_bani), blocks: formatLei(entry.blocks_bani) });
  if (order !== undefined && order.blocks.some((block) => block.status === CANCELLED)) {
    text += `; ${texts.valori_implicite.antet_cu_bloc_anulat}`; // cauza cea mai frecventă pe conturi reale
  }
  return item([entry.order_id], null, null, null, order !== undefined ? dayOf(order.placed_at) : null, text);
}

/** O grupă gata de scris în analiza.json (rândurile sortate, `count` = numărul lor). */
function group(kind, items, texts, affectsTotals) {
  const config = texts.grupe[kind];
  const ordered = sortedBy(items, sortKey);
  return {
    kind,
    title: config.title,
    explanation: config.explanation,
    affects_totals: affectsTotals,
    what_to_do: config.what_to_do,
    count: ordered.length,
    items: ordered,
  };
}

/**
 * Grupele de avertismente cu rândurile lor; `headerMismatches` = `reconciliation.header_total_mismatches`. Un număr din mesajul „N retururi…” care nu se potrivește cu lista din date
 * se scrie în jurnal (`log`); lista din date câștigă.
 */
export function buildWarningsDetail(warnings, orders, returns, headerMismatches, texts, log = null) {
  const ordersById = new Map(orders.map((order) => [order.order_id, order]));
  const returnsById = new Map(returns.map((ret) => [ret.return_id, ret]));
  const items = new Map(ALL_KINDS.map((kind) => [kind, []]));
  const statedCounts = new Map();
  const seenMessages = new Map();
  let otherAffectsTotals = false;
  for (const text of warnings) {
    const parsed = parseOrderWarning(text);
    if (parsed.count !== null) { // lista acestor grupe vine din date, mai jos
      statedCounts.set(parsed.kind, parsed.count);
      continue;
    }
    items.get(parsed.kind).push(warningItem(parsed, texts, ordersById, returnsById, seenMessages));
    otherAffectsTotals = otherAffectsTotals || (parsed.kind === KIND_OTHER && parsed.affects_totals);
  }
  items.set(KIND_PENDING_RETURN, returnsWithoutResult(returns).map((ret) => returnItem(ret, KIND_PENDING_RETURN, texts, ordersById)));
  items.set(KIND_COMPLETED_RETURN_NO_REFUND, completedReturnsWithoutAmount(returns).map((ret) => returnItem(ret, KIND_COMPLETED_RETURN_NO_REFUND, texts, ordersById)));
  items.set(KIND_HEADER_MISMATCH, headerMismatches.map((entry) => headerItem(entry, texts, ordersById)));
  for (const [kind, stated] of statedCounts) {
    if (stated !== items.get(kind).length) log?.warning(LOG_MODULE, `avertismentul ${kind} spune ${stated}, dar lista din date are ${items.get(kind).length} rânduri`);
  }
  const groups = [];
  for (const kind of ALL_KINDS) {
    if (items.get(kind).length > 0) {
      const affects = texts.grupe[kind].affects_totals || (kind === KIND_OTHER && otherAffectsTotals);
      groups.push(group(kind, items.get(kind), texts, affects));
    }
  }
  return groups;
}
