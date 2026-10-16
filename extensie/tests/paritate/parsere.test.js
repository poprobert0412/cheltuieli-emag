// Paritatea parserelor de pagini: order_parser.js și return_parser.js față de emag_spend/order_parser.py și return_parser.py.
// Fiecare caz din parsere.json (paginile inventate în ambele așezări, liniile scrise de mână și variantele stricate ale lor) trece prin portul JS cu aceleași intrări ca în Python
// și se cere același rezultat: structură identică, cheile în ordinea câmpurilor din to_dict (ordinea contează pentru comenzi.json), ori aceeași eroare cu același mesaj.
// Ce NU face: nu parsează HTML (html_lines.test.js, în browser), nu verifică exporturile (exporturi.test.js) și nu compară cu paginile reale (acceptanța pe cont).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { parseOrder } from '../../src/calcul/order_parser.js';
import { pyJsonDumps } from '../../src/calcul/python_compat.js';
import { parseReturn } from '../../src/calcul/return_parser.js';
import { attempt, loadFixture, same, sameError } from '../fixturi.js';

// Pragurile apără testul de a deveni inutil: o fixtură regenerată mai mică sau fără o categorie de cazuri ar trece fără să dovedească nimic.
const MIN_CASES = 600;
const MIN_PER_KIND = 100;
const MIN_ERRORS_PER_KIND = 5;
const MIN_ORDERS_WITH_WARNINGS = 50;
const MIN_HAND_CASES = 15;

const { cazuri: cases } = loadFixture('parsere');
const show = (value) => JSON.stringify(value);
const describeCase = (c) => () => `${c.nume} (${c.tip}, ${show(c.id_sau_cale)})`;

// Cazuri scrise de mână, cu ieșirea lui Python (3.13) la scrierea testului, pentru ramurile pe care fixtura nu le atinge (le-a arătat testarea prin mutație): cel mult 14 linii de status,
// prefixele auxiliare „garantie ” și „cumpara din nou”, „gratuit” doar după „:”, zona de totaluri care se închide la „Total platit”, vânzătorul curățat de spații (și vânzătorul gol, care e fals ca în Python),
// data cu spațiu la sfârșit, „Factura storno” în felurile ei, „Detalii de contact” dinaintea lui „Status retur”, pașii anulat + restituit, litere românești în luna unui pas, titlu de pas cu text în plus.
const HAND_CASES = [
  { nume: 'mana_status_cu_20_de_linii', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Linie de status 1', 'Linie de status 2', 'Linie de status 3', 'Linie de status 4', 'Linie de status 5', 'Linie de status 6', 'Linie de status 7', 'Linie de status 8', 'Linie de status 9', 'Linie de status 10', 'Linie de status 11', 'Linie de status 12', 'Linie de status 13', 'Linie de status 14', 'Linie de status 15', 'Linie de status 16', 'Linie de status 17', 'Linie de status 18', 'Linie de status 19', 'Linie de status 20', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'UNKNOWN', status_text: 'Linie de status 1 | Linie de status 2 | Linie de status 3 | Linie de status 4 | Linie de status 5 | Linie de status 6 | Linie de status 7 | Linie de status 8 | Linie de status 9 | Linie de status 10 | Linie de status 11 | Linie de status 12 | Linie de status 13 | Linie de status 14', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_nume_peste_garantie_extinsa', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', 'Garantie extinsa 24 luni', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_nume_peste_cumpara_din_nou', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', 'Cumpara din nou', 'Adauga review', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_gratuit_inainte_de_doua_puncte', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '100,99 Lei 1 buc', 'Total produse: 100,99 Lei', 'Cost livrare gratuit: 5,00 Lei', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10099, qty: 1 }], products_total_bani: 10099, vouchers_bani: [], shipping_bani: 500, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_linie_cu_suma_dupa_total_platit', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei', 'Informatie extra: 5,00 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_vanzator_cu_spatii_in_jur', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute de   ALFA SRL   si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Total platit ALFA SRL: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'ALFA SRL', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_vanzator_gol_dupa_strip', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute de   si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [], warnings: ['comanda 489000001: nicio secțiune de vânzător găsită'] } },
  { nume: 'mana_data_cu_linie_goala_dupa', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07', '', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: null, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: false, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_storno_la_sfarsit_de_linie', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'Factura storno', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: true, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_storno_cu_majuscule_si_doua_puncte', tip: 'comanda', id_sau_cale: '489000001', linii: ['Comanda nr. 489000001', 'Plasata pe: 26 mai 2026, 10:07 Total: 105,99 Lei', 'Produse vandute si livrate de eMAG', 'Produse ridicate', 'Istoric livrare', 'Produs Alfa Test', '105,99 Lei 1 buc', 'FACTURA STORNO:', 'Total produse: 105,99 Lei', 'Cost livrare: GRATUIT', 'Total platit eMAG: 105,99 Lei'], nume_produse: null, rezultat: { order_id: '489000001', placed_text: '26 mai 2026, 10:07', placed_at: '2026-05-26T10:07', header_total_bani: 10599, blocks: [{ seller: 'eMAG', status: 'DELIVERED', status_text: 'Produse ridicate', has_storno: true, items: [{ name: 'Produs Alfa Test', line_total_bani: 10599, qty: 1 }], products_total_bani: 10599, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [], paid_bani: 10599, due_bani: null }], warnings: [] } },
  { nume: 'mana_contact_inainte_de_status', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000001', 'Detalii de contact', 'Nume Nume Fictiv', 'Detalii comanda', 'Produs Alfa Test', 'Status retur', 'Cerere inregistrata Data: 1 Iulie, 13:44', 'Restituire suma Data: 2 Iulie, 10:00', 'Suma de 10 RON a pornit spre contul tau.', 'Modalitate restituire', 'Vreau banii inapoi'], nume_produse: null, rezultat: { return_id: '3000001', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: ['Produs Alfa Test'], steps: ['Cerere inregistrata', 'Restituire suma'], refund_bani: 1000, refund_mode: 'Vreau banii inapoi', completed: true, cancelled: false } },
  { nume: 'mana_anulat_si_restituit', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000002', 'Detalii comanda', 'Produs Alfa Test', 'Status retur', 'Cerere anulata Data: 1 Iulie, 13:44', 'Restituire suma Data: 2 Iulie, 10:00', 'Detalii de contact'], nume_produse: null, rezultat: { return_id: '3000002', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: ['Produs Alfa Test'], steps: ['Cerere anulata', 'Restituire suma'], refund_bani: null, refund_mode: '', completed: true, cancelled: false } },
  { nume: 'mana_luna_cu_litera_romaneasca', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000003', 'Detalii comanda', 'Produs Alfa Test', 'Status retur', 'Cerere inregistrata Data: 1 \u{162}arina, 13:44', 'Cerere anulata Data: 3 Țara', 'Detalii de contact'], nume_produse: null, rezultat: { return_id: '3000003', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: ['Produs Alfa Test'], steps: ['Cerere inregistrata', 'Cerere anulata'], refund_bani: null, refund_mode: '', completed: false, cancelled: true } },
  { nume: 'mana_titlu_cu_text_in_plus', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000004', 'Detalii comanda', 'Produs Alfa Test', 'Status retur', 'Pas 3: Restituire suma Data: 1 Iulie, 13:44', 'Detalii de contact'], nume_produse: null, rezultat: { return_id: '3000004', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: ['Produs Alfa Test'], steps: ['Pas 3: Restituire suma'], refund_bani: null, refund_mode: '', completed: true, cancelled: false } },
  { nume: 'mana_eticheta_cu_valoare_pe_linia_urmatoare_cu_spatii', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000005', 'Detalii comanda', 'Produs Alfa Test', 'Status retur', 'Cerere inregistrata Data: 1 Iulie, 13:44', 'Detalii de contact', 'Modalitate restituire', '   Emitere voucher   '], nume_produse: null, rezultat: { return_id: '3000005', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: ['Produs Alfa Test'], steps: ['Cerere inregistrata'], refund_bani: null, refund_mode: 'Emitere voucher', completed: false, cancelled: false } },
  { nume: 'mana_eticheta_pe_ultima_linie', tip: 'retur', id_sau_cale: '/user/return-history/1/3000001', linii: ['Retur #3000006', 'Status retur', 'Modalitate restituire'], nume_produse: null, rezultat: { return_id: '3000006', detail_path: '/user/return-history/1/3000001', order_ids: [], product_names: [], steps: [], refund_bani: null, refund_mode: '', completed: false, cancelled: false } },
];

/** Rulează parserul cazului cu intrările înghețate: o modificare pe loc a listei de linii sau a numelor din parser ridică TypeError și pică testul. */
function run(c) {
  const lines = Object.freeze([...c.linii]);
  const names = c.nume_produse === null ? null : Object.freeze([...c.nume_produse]);
  return attempt(() => (c.tip === 'comanda' ? parseOrder(c.id_sau_cale, lines, names) : parseReturn(c.id_sau_cale, lines)));
}

/** Nicio listă din rezultat nu e una dintre listele înghețate de intrare: ca în Python (feliile sunt copii), rezultatul nu partajează liste cu liniile date. */
function assertNoSharedLists(value, label) {
  if (Array.isArray(value)) {
    assert.equal(Object.isFrozen(value), false, `${label}: rezultatul partajează o listă cu intrarea`);
    value.forEach((item) => assertNoSharedLists(item, label));
  } else if (value !== null && typeof value === 'object') {
    Object.values(value).forEach((item) => assertNoSharedLists(item, label));
  }
}

/** Compară rezultatul cazului: valori identice (deepStrictEqual) și același text JSON, deci aceleași chei în aceeași ordine; sau aceeași eroare ValueError cu același mesaj. */
function checkCase(c) {
  const got = run(c);
  if (c.eroare !== undefined) { // fixtura scrie eroarea ca { tip, mesaj }; sameError cere { type, message }
    sameError(got, { type: c.eroare.tip, message: c.eroare.mesaj }, describeCase(c));
    same(got.error.type, c.eroare.tip, () => `${describeCase(c)()}: tipul erorii (ValueError exact, nu RangeError sau Error)`);
    return;
  }
  assert.equal(got.error, undefined, `${describeCase(c)()}: eroare neașteptată ${show(got.error)}`);
  same(got, { out: c.rezultat }, describeCase(c));
  same(pyJsonDumps(got.out), pyJsonDumps(c.rezultat), () => `${describeCase(c)()}: ordinea cheilor (comenzi.json / retururi.json)`);
  assertNoSharedLists(got.out, describeCase(c)());
}

/** Un test pe grupă: rulează `checkCase` pe fiecare caz și spune câte cazuri au fost identice cu Python; o grupă sub `minimum` cazuri nu dovedește nimic. */
function eachGroup(name, group, minimum) {
  test(`${name} (${group.length} cazuri)`, (t) => {
    assert.ok(group.length >= minimum, `grupa ${name} are doar ${group.length} cazuri (minimum ${minimum})`);
    for (const c of group) checkCase(c);
    t.diagnostic(`${group.length} cazuri identice cu Python`);
  });
}

describe('fixtura parsere.json', () => {
  test('are destule cazuri din fiecare fel, cu rezultat și cu eroare', () => {
    assert.ok(cases.length >= MIN_CASES, `doar ${cases.length} cazuri`);
    for (const kind of ['comanda', 'retur']) {
      const ofKind = cases.filter((c) => c.tip === kind);
      assert.ok(ofKind.filter((c) => c.eroare === undefined).length >= MIN_PER_KIND, `prea puține ${kind} cu rezultat`);
      assert.ok(ofKind.filter((c) => c.eroare !== undefined).length >= MIN_ERRORS_PER_KIND, `prea puține ${kind} cu eroare`);
    }
    const withWarnings = cases.filter((c) => c.tip === 'comanda' && c.rezultat?.warnings.length > 0);
    assert.ok(withWarnings.length >= MIN_ORDERS_WITH_WARNINGS, `doar ${withWarnings.length} comenzi cu avertismente: ramurile de verificare a blocurilor nu sunt acoperite`);
  });
});

describe('parseOrder și parseReturn față de Python', () => {
  eachGroup('comenzi parsate (pagini, linii scrise de mână, variante stricate)', cases.filter((c) => c.tip === 'comanda' && c.eroare === undefined), MIN_PER_KIND);
  eachGroup('comenzi care ridică ValueError', cases.filter((c) => c.tip === 'comanda' && c.eroare !== undefined), MIN_ERRORS_PER_KIND);
  eachGroup('retururi parsate (pagini, linii scrise de mână, variante stricate)', cases.filter((c) => c.tip === 'retur' && c.eroare === undefined), MIN_PER_KIND);
  eachGroup('retururi care ridică ValueError', cases.filter((c) => c.tip === 'retur' && c.eroare !== undefined), MIN_ERRORS_PER_KIND);
});

/** Primul caz de comandă parsată al cărei prim bloc are produse (are ce modifica în testele de independență). */
const orderWithItems = () => cases.find((c) => c.tip === 'comanda' && c.rezultat !== undefined && c.rezultat.blocks.length > 0 && c.rezultat.blocks[0].items.length > 0);

describe('forma rezultatelor', () => {
  test('Order și ReturnRequest au cheile din to_dict, în ordinea câmpurilor', () => {
    const gotOrder = run(orderWithItems()).out;
    assert.deepEqual(Object.keys(gotOrder), ['order_id', 'placed_text', 'placed_at', 'header_total_bani', 'blocks', 'warnings']);
    assert.deepEqual(Object.keys(gotOrder.blocks[0]), ['seller', 'status', 'status_text', 'has_storno', 'items', 'products_total_bani', 'vouchers_bani', 'shipping_bani', 'services_bani', 'other_bani', 'paid_bani', 'due_bani']);
    assert.deepEqual(Object.keys(gotOrder.blocks[0].items[0]), ['name', 'line_total_bani', 'qty']);
    const gotReturn = run(cases.find((c) => c.tip === 'retur' && c.rezultat !== undefined)).out;
    assert.deepEqual(Object.keys(gotReturn), ['return_id', 'detail_path', 'order_ids', 'product_names', 'steps', 'refund_bani', 'refund_mode', 'completed', 'cancelled']);
  });
  test('două apeluri la rând dau rezultate independente (nicio stare rămasă între apeluri, nicio listă partajată)', () => {
    const c = orderWithItems();
    const first = run(c).out;
    const second = run(c).out;
    same(first, second, () => c.nume);
    assert.notEqual(first.blocks, second.blocks);
    assert.notEqual(first.blocks[0].items, second.blocks[0].items);
    first.blocks[0].items[0].name = 'schimbat';
    first.warnings.push('schimbat');
    same(run(c).out, c.rezultat, () => `${c.nume}: o modificare a rezultatului nu are voie să se vadă la apelul următor`);
  });
});

describe('cazuri scrise de mână pentru ramurile neatinse de fixtură', () => {
  test(`${HAND_CASES.length} cazuri: același rezultat ca Python, cu cheile în aceeași ordine`, (t) => {
    assert.ok(HAND_CASES.length >= MIN_HAND_CASES, `doar ${HAND_CASES.length} cazuri scrise de mână`);
    assert.equal(new Set(HAND_CASES.map((c) => c.nume)).size, HAND_CASES.length, 'numele cazurilor trebuie să fie unice');
    for (const c of HAND_CASES) checkCase(c);
    t.diagnostic(`${HAND_CASES.length} cazuri identice cu Python`);
  });
});
