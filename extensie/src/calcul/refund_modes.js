// Modul de restituire al unui retur finalizat: bani înapoi (se scad din cheltuieli) sau credit eMAG (nu se scad) (portul lui emag_spend/refund_modes.py).
// Primește: obiectul din config/restituiri.json, cu listele `bani_inapoi` și `credit_emag` (textele de la „Modalitate restituire”). Dă înapoi: RefundModes, care spune despre un mod
// dacă e credit (voucher, sold) și dacă e cunoscut. De ce: un voucher restituit se folosește apoi ca reducere în altă comandă și scade deja „Total platit” al acelei comenzi; scăzut și la retur,
// aceiași bani s-ar scădea de două ori. „Generare sold” (sold eMAG) e credit, ca voucherul: decis de Robert pe 5 oct. 2026. Un mod necunoscut se tratează ca bani înapoi (cazul obișnuit),
// iar analiza scrie un avertisment. Ce NU face: nu citește fișiere (configurarea vine ca obiect, generat la build) și nu calculează sume (paid_totals.js).
import { PyValueError, pyRepr, pyStrip, sortedBy } from './python_compat.js';
import { normalizeText } from './text_normalize.js';

const LIST_KEYS = ['bani_inapoi', 'credit_emag'];

/** Adevărat pentru un obiect JSON (dict în Python): nu null, nu listă. */
function isDict(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Modurile cunoscute, normalizate (fără diacritice, litere mici), ca două mulțimi: `cash` (bani înapoi) și `credit` (voucher, sold). */
export class RefundModes {
  constructor({ cash, credit }) {
    this.cash = new Set(cash);
    this.credit = new Set(credit);
  }

  /** True dacă restituirea a fost voucher sau sold eMAG (banii nu s-au întors în cont). */
  isCredit(mode) {
    return this.credit.has(normalizeText(mode || ''));
  }

  /** True dacă modul e într-una dintre liste (altfel se tratează ca bani înapoi, cu avertisment). */
  isKnown(mode) {
    const normalized = normalizeText(mode || '');
    return this.cash.has(normalized) || this.credit.has(normalized);
  }
}

/**
 * Validează obiectul din config/restituiri.json și întoarce RefundModes; ValueError (PyValueError, cu `source`, numele configurării) la o listă lipsă, un text gol sau un mod în ambele liste.
 * Mesajele sunt cele din ValueError-ul Python, cu `source` (implicit numele fișierului din config/) în locul căii fișierului.
 */
export function loadRefundModes(data, source = 'restituiri.json') {
  if (!isDict(data)) throw new PyValueError(`${source}: trebuie să fie un obiect cu listele ${LIST_KEYS.map((key) => pyRepr(key)).join(', ')}`);
  const lists = new Map();
  for (const key of LIST_KEYS) {
    const values = Object.hasOwn(data, key) ? data[key] : undefined;
    if (!Array.isArray(values) || !values.every((value) => typeof value === 'string' && pyStrip(value) !== '')) {
      throw new PyValueError(`${source}: '${key}' trebuie să fie o listă de texte nevide`);
    }
    lists.set(key, new Set(values.map((value) => normalizeText(value))));
  }
  const both = sortedBy([...lists.get('bani_inapoi')].filter((mode) => lists.get('credit_emag').has(mode)));
  if (both.length > 0) throw new PyValueError(`${source}: un mod nu poate fi și „bani_inapoi”, și „credit_emag”: ${pyRepr(both)}`);
  return new RefundModes({ cash: lists.get('bani_inapoi'), credit: lists.get('credit_emag') });
}
