// Paritatea analizei Python <-> JavaScript: analyze() din src/calcul/spend_analysis.js dă pe fiecare scenariu din fixtura analiza.json (scrisă de tests/paritate_export.py din
// emag_spend.spend_analysis.analyze) același `summary` și aceleași linii de registru, la ban: întregii cu Object.is (deci și zero cu semn), procentele (float în Python, PyFloat aici) cu
// Object.is pe valoare, listele în aceeași ordine, cheile obiectelor în aceeași ordine. Apoi, cu cazuri scrise de mână pe care mutation testing le-a cerut (valorile vin din rularea lui
// Python, nu din minte): validările încărcătoarelor de configurare, python_format, blocurile, cheile de produs, avertismentele comenzii, jurnalul și scenarii mici pe ramurile
// pe care cele 8 scenarii nu le ating. Ce NU face: nu verifică CSV-urile și raportul (le compară testul exporturilor, al agentului B) și nu atinge rețeaua sau browserul.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

import { blockPayment } from '../../src/calcul/block_payment.js';
import { Classifier } from '../../src/calcul/classifier.js';
import { buildLines } from '../../src/calcul/line_ledger.js';
import {
  LineOutcome, makeItem, makeOrder, makeReturnRequest, makeSellerBlock, orderFromDict, returnFromDict, toDict,
} from '../../src/calcul/models.js';
import { computePaidTotals } from '../../src/calcul/paid_totals.js';
import { ColorWords, loadColorWords, makeProductKey } from '../../src/calcul/product_key.js';
import { PyFloat } from '../../src/calcul/python_compat.js';
import { formatterParse, pyFormat } from '../../src/calcul/python_format.js';
import { RefundModes, loadRefundModes } from '../../src/calcul/refund_modes.js';
import { ReturnMatchReport } from '../../src/calcul/return_matcher.js';
import { analyze, plainSummary } from '../../src/calcul/spend_analysis.js';
import { normalizeText } from '../../src/calcul/text_normalize.js';
import {
  buildWarningsDetail, completedReturnsWithoutAmount, currentOrderWarnings, loadWarningTexts, returnsWithoutResult,
} from '../../src/calcul/warning_details.js';
import { FIXTURES_DIR, FIXTURE_SCHEMA, loadFixture } from '../fixturi.js';

const CONFIG_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'config');
// Componenta de desenare a raportului (sursa unică a designului): validate() din ea hotărăște ce rezumat primește ecranul.
const DASHBOARD_FILE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'interfata', 'assets', 'dashboard.js');
// Cele 15 proprietăți calculate ale unei linii pe care generatorul le scrie lângă câmpuri (tests/paritate_export.py, `properties`), în ordinea lui.
const LINE_PROPERTIES = [
  'returned_bani', 'cancelled_bani', 'pending_bani', 'paid_only_bani', 'unknown_bani', 'kept_bani', 'list_value_bani', 'kept_list_bani', 'paid_value_bani',
  'returned_paid_bani', 'cancelled_paid_bani', 'pending_paid_bani', 'paid_only_paid_bani', 'unknown_paid_bani', 'kept_paid_bani',
];
// Cel mult atâtea diferențe se arată într-un mesaj de eșec: destul ca să se vadă tiparul, fără un mesaj de mii de rânduri.
const MAX_SHOWN_DIFFERENCES = 8;

/** JSON.parse în care numerele scrise cu virgulă sau exponent (float în Python) devin PyFloat: `context.source` e textul exact din fișier. */
function parseKeepingFloats(text) {
  return JSON.parse(text, (_key, value, context) => (typeof value === 'number' && /[.eE]/.test(context.source) ? new PyFloat(value) : value));
}

/** Fixtura analiza.json cu floaturile marcate (loadFixture din fixturi.js pierde diferența dintre 5 și 5.0). */
function loadAnalysisFixture() {
  const file = path.join(FIXTURES_DIR, 'analiza.json');
  let text;
  try {
    text = readFileSync(file, 'utf8');
  } catch (error) {
    throw new Error(`Lipsește fixtura ${file}: rulează întâi npm run paritate:genereaza (${error.message})`);
  }
  const data = parseKeepingFloats(text);
  assert.equal(data.schema, FIXTURE_SCHEMA, `${file} are altă schemă decât testele: regenerează fixturile`);
  return data;
}

/** Configurarea din config/<name> ca obiect (BOM-ul de la început, pe care Notepad îl scrie, se ignoră ca în read_json). */
function readConfig(name) {
  return JSON.parse(readFileSync(path.join(CONFIG_DIR, name), 'utf8').replace(/^\u{feff}/u, ''));
}

const WARNING_TEXTS = loadWarningTexts(readConfig('avertismente.json'), 'avertismente.json');
const COLOR_WORDS = loadColorWords(readConfig('culori.json'), 'culori.json');
const REFUND_MODES = loadRefundModes(readConfig('restituiri.json'), 'restituiri.json');

/** Descriere scurtă a unei valori pentru mesajele de diferență (JSON, cu PyFloat ca float(…) și zero cu semn vizibil). */
function describeValue(value) {
  if (value instanceof PyFloat) return `float(${Object.is(value.value, -0) ? '-0' : value.value})`;
  if (typeof value === 'number') return Object.is(value, -0) ? 'int(-0)' : `int(${value})`;
  if (typeof value === 'object' && value !== null) return Array.isArray(value) ? `listă(${value.length})` : `obiect(${Object.keys(value).length} chei)`;
  const text = JSON.stringify(value);
  return text === undefined ? String(value) : text.slice(0, 120);
}

/**
 * Diferențele dintre `actual` (ce dă JavaScript) și `expected` (JSON-ul Python): tip, valori cu Object.is, lungimea și ordinea listelor, cheile obiectelor în aceeași ordine.
 * `actual` trebuie să fie un arbore JSON curat: obiecte simple, liste, PyFloat; un Map, o clasă sau un undefined într-un rezumat nu ar putea fi salvate în chrome.storage.
 */
function differences(actual, expected, where, found = []) {
  if (found.length >= MAX_SHOWN_DIFFERENCES) return found;
  if (expected instanceof PyFloat || actual instanceof PyFloat) {
    if (!(expected instanceof PyFloat && actual instanceof PyFloat)) found.push(`${where}: ${describeValue(actual)} în loc de ${describeValue(expected)}`);
    else if (!Object.is(actual.value, expected.value)) found.push(`${where}: ${describeValue(actual)} în loc de ${describeValue(expected)}`);
    return found;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) found.push(`${where}: ${describeValue(actual)} în loc de ${describeValue(expected)}`);
    else {
      if (actual.length !== expected.length) found.push(`${where}: lungimea ${actual.length} în loc de ${expected.length}`);
      for (let index = 0; index < Math.min(actual.length, expected.length); index += 1) differences(actual[index], expected[index], `${where}[${index}]`, found);
    }
    return found;
  }
  if (expected !== null && typeof expected === 'object') {
    if (actual === null || typeof actual !== 'object' || Array.isArray(actual) || Object.getPrototypeOf(actual) !== Object.prototype) {
      found.push(`${where}: ${describeValue(actual)} în loc de un obiect simplu`);
      return found;
    }
    const actualKeys = Object.keys(actual);
    const expectedKeys = Object.keys(expected);
    if (JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) {
      found.push(`${where}: cheile ${JSON.stringify(actualKeys)} în loc de ${JSON.stringify(expectedKeys)}`);
      return found;
    }
    for (const key of expectedKeys) differences(actual[key], expected[key], `${where}.${key}`, found);
    return found;
  }
  if (!Object.is(actual, expected)) found.push(`${where}: ${describeValue(actual)} în loc de ${describeValue(expected)}`);
  return found;
}

/** Cere identitate: la prima diferență oprește testul cu primele diferențe, fiecare cu calea ei. */
function assertIdentical(actual, expected, label) {
  const found = differences(actual, expected, label);
  assert.deepEqual(found, [], `${found.length} diferențe față de Python:\n  ${found.join('\n  ')}`);
}

/** Rulează analyze() pe intrările unui scenariu din fixtură, cu configurările din config/ (ca generatorul). */
function runScenario(scenario) {
  const orders = scenario.comenzi.map(orderFromDict);
  const returns = scenario.retururi.map(returnFromDict);
  const classifier = new Classifier(scenario.reguli, `scenariul ${scenario.nume}`);
  const result = analyze(orders, returns, classifier, scenario.prag_bani, scenario.generat_la, {
    highlightCategories: scenario.evidentiate, warningTexts: WARNING_TEXTS, colorWords: COLOR_WORDS, refundModes: REFUND_MODES,
  });
  return { orders, returns, result };
}

/** Linia de registru ca în fixtură: câmpurile (to_dict) urmate de cele 15 proprietăți calculate. */
function lineAsFixture(line) {
  assert.ok(line instanceof LineOutcome, 'analyze() trebuie să dea LineOutcome (csv_export le citește cu proprietățile lor)');
  const properties = Object.fromEntries(LINE_PROPERTIES.map((name) => [name, line[name]]));
  return { ...line.toDict(), ...properties };
}

const fixture = loadAnalysisFixture();

describe('analyze(): același summary și aceleași linii ca Python, pe fiecare scenariu', () => {
  test('fixtura are cele 8 scenarii așteptate, cu intrări și ieșiri', () => {
    assert.deepEqual(fixture.scenarii.map((scenario) => scenario.nume),
      ['scenariu', 'demo', 'din_pagini', 'capcane_sortare', 'capcane_preturi', 'capcane_retururi', 'capcane_sume', 'gol']);
    for (const scenario of fixture.scenarii) {
      assert.ok(scenario.rezumat && typeof scenario.rezumat === 'object', scenario.nume);
      assert.equal(scenario.rezumat.meta.orders, scenario.comenzi.length, scenario.nume);
    }
  });

  for (const scenario of fixture.scenarii) {
    test(`${scenario.nume}: rezumat identic (${scenario.comenzi.length} comenzi, ${scenario.retururi.length} retururi, ${scenario.linii.length} linii)`, (t) => {
      const { result } = runScenario(scenario);
      assertIdentical(result.summary, scenario.rezumat, 'rezumat');
      t.diagnostic(`${scenario.linii.length} linii, ${scenario.rezumat.warnings.length} avertismente, paid.spent_bani = ${scenario.rezumat.paid.spent_bani}`);
    });

    test(`${scenario.nume}: liniile de registru identice (câmpuri și proprietăți calculate)`, () => {
      const { result } = runScenario(scenario);
      assert.equal(result.lines.length, scenario.linii.length);
      assertIdentical(result.lines.map(lineAsFixture), scenario.linii, 'linii');
    });

    test(`${scenario.nume}: intrările nu se modifică, iar al doilea apel dă același rezultat`, () => {
      const { orders, returns, result } = runScenario(scenario);
      assert.deepEqual(toDict(orders), toDict(scenario.comenzi.map(orderFromDict)), 'comenzile s-au schimbat în timpul analizei');
      assert.deepEqual(toDict(returns), toDict(scenario.retururi.map(returnFromDict)), 'retururile s-au schimbat în timpul analizei');
      const again = runScenario(scenario).result;
      assertIdentical(again.summary, result.summary, 'al doilea apel');
    });
  }
});

// ---------- încărcătoarele de configurare: aceleași validări și mesaje ca în Python ----------

/** O copie a configurării cu mutațiile aplicate: ['set', cale, valoare], ['del', cale] sau ['root', valoare] (înlocuiește tot obiectul). */
function mutated(base, operations) {
  let data = structuredClone(base);
  for (const [kind, ...rest] of operations) {
    if (kind === 'root') {
      [data] = rest;
      continue;
    }
    const [keys, value] = rest;
    const parent = keys.slice(0, -1).reduce((node, key) => node[key], data);
    if (kind === 'set') parent[keys[keys.length - 1]] = value;
    else delete parent[keys[keys.length - 1]];
  }
  return data;
}

/** Cere o ValueError cu mesajul exact (Python scrie ValueError; extensia, PyValueError cu același nume). */
function assertValueError(action, message) {
  assert.throws(action, (error) => {
    assert.equal(error.name, 'ValueError');
    assert.equal(error.message, message);
    return true;
  });
}

// [nume, mutații ale config/avertismente.json, mesajul ValueError din load_warning_texts (cu x.json în loc de cale) | null dacă configurarea rămâne validă]; valorile vin din rularea lui Python.
const WARNING_TEXT_CASES = [
  ['radacina lista', [['root', []]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['radacina text', [['root', 'x']], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['lipseste grupe', [['del', ['grupe']]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['grupe nu e obiect', [['set', ['grupe'], []]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['lipseste etichete_status', [['del', ['etichete_status']]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['valori_implicite null', [['set', ['valori_implicite'], null]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['etichete_status lista', [['set', ['etichete_status'], []]], "x.json: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'"],
  ['lipseste grupa prima', [['del', ['grupe', 'missing_paid_total']]], "x.json: lipsește grupa 'missing_paid_total' din 'grupe'"],
  ['lipseste grupa a patra', [['del', ['grupe', 'header_total_mismatch']]], "x.json: lipsește grupa 'header_total_mismatch' din 'grupe'"],
  ['lipsesc doua grupe, prima in ordine', [['del', ['grupe', 'other']], ['del', ['grupe', 'pending_return_without_result']]], "x.json: lipsește grupa 'pending_return_without_result' din 'grupe'"],
  ['grupa nu e obiect', [['set', ['grupe', 'other'], 'x']], "x.json: lipsește grupa 'other' din 'grupe'"],
  ['lipseste titlul', [['del', ['grupe', 'pending_return_without_result', 'title']]], "x.json: grupa 'pending_return_without_result' trebuie să aibă textul nevid 'title'"],
  ['titlu gol', [['set', ['grupe', 'other', 'title'], '']], "x.json: grupa 'other' trebuie să aibă textul nevid 'title'"],
  ['explicatie alba', [['set', ['grupe', 'other', 'explanation'], '  \t ']], "x.json: grupa 'other' trebuie să aibă textul nevid 'explanation'"],
  ['what_to_do numar', [['set', ['grupe', 'other', 'what_to_do'], 5]], "x.json: grupa 'other' trebuie să aibă textul nevid 'what_to_do'"],
  ['what_to_do null', [['set', ['grupe', 'other', 'what_to_do'], null]], "x.json: grupa 'other' trebuie să aibă textul nevid 'what_to_do'"],
  ['lipseste item_text', [['del', ['grupe', 'completed_return_without_refund', 'item_text']]], "x.json: grupa 'completed_return_without_refund' trebuie să aibă textul nevid 'item_text'"],
  ['affects_totals text', [['set', ['grupe', 'other', 'affects_totals'], 'true']], "x.json: grupa 'other': 'affects_totals' trebuie să fie true sau false"],
  ['affects_totals numar', [['set', ['grupe', 'other', 'affects_totals'], 1]], "x.json: grupa 'other': 'affects_totals' trebuie să fie true sau false"],
  ['affects_totals lipsa', [['del', ['grupe', 'header_total_mismatch', 'affects_totals']]], "x.json: grupa 'header_total_mismatch': 'affects_totals' trebuie să fie true sau false"],
  ['titlu lipsa dar si alta grupa gresita', [['del', ['grupe', 'missing_paid_total', 'title']], ['del', ['grupe', 'other']]], "x.json: grupa 'missing_paid_total' trebuie să aibă textul nevid 'title'"],
  ['eticheta numar', [['set', ['etichete_status', 'DELIVERED'], 1]], "x.json: 'etichete_status' trebuie să fie un obiect cu valori text"],
  ['eticheta null', [['set', ['etichete_status', 'UNKNOWN'], null]], "x.json: 'etichete_status' trebuie să fie un obiect cu valori text"],
  ['valori_implicite lipsa produse_lipsa', [['del', ['valori_implicite', 'produse_lipsa']]], "x.json: 'valori_implicite' trebuie să aibă textul 'produse_lipsa'"],
  ['valori_implicite pas_lipsa numar', [['set', ['valori_implicite', 'pas_lipsa'], 3]], "x.json: 'valori_implicite' trebuie să aibă textul 'pas_lipsa'"],
  ['valori_implicite mod_lipsa null', [['set', ['valori_implicite', 'mod_lipsa'], null]], "x.json: 'valori_implicite' trebuie să aibă textul 'mod_lipsa'"],
  ['valori_implicite produse_in_plus lipsa', [['del', ['valori_implicite', 'produse_in_plus']]], "x.json: 'valori_implicite' trebuie să aibă textul 'produse_in_plus'"],
  ['valori_implicite antet lipsa', [['del', ['valori_implicite', 'antet_cu_bloc_anulat']]], "x.json: 'valori_implicite' trebuie să aibă textul 'antet_cu_bloc_anulat'"],
  ['valori_implicite produse_lipsa gol e ok', [['set', ['valori_implicite', 'produse_lipsa'], '']], null],
  ["item_text missing_paid_total '{seller'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (expected '}' before end of string)"],
  ["item_text missing_paid_total 'a } b'", [['set', ['grupe', 'missing_paid_total', 'item_text'], 'a } b']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (Single '}' encountered in format string)"],
  ["item_text missing_paid_total 'abc {'", [['set', ['grupe', 'missing_paid_total', 'item_text'], 'abc {']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (Single '{' encountered in format string)"],
  ["item_text missing_paid_total '{foo}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{foo}']], "x.json: grupa 'missing_paid_total', item_text are câmpuri necunoscute ['foo']; cele permise: ['seller', 'status']"],
  ["item_text missing_paid_total '{zeta} {alfa} {seller}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{zeta} {alfa} {seller}']], "x.json: grupa 'missing_paid_total', item_text are câmpuri necunoscute ['alfa', 'zeta']; cele permise: ['seller', 'status']"],
  ["item_text missing_paid_total '{seller:>5}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller:>5}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{seller!r}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller!r}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{seller.x}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller.x}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{seller[0]}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller[0]}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{0}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{0}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{{literal}} {seller} {status}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{{literal}} {seller} {status}']], null],
  ["item_text missing_paid_total '{seller:{status}}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller:{status}}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{seller!}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller!}']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (unmatched '{' in format spec)"],
  ["item_text missing_paid_total '{seller!r'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller!r']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (unmatched '{' in format spec)"],
  ["item_text missing_paid_total '{seller!x}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller!x}']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{seller!rr}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller!rr}']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (expected ':' after conversion specifier)"],
  ["item_text missing_paid_total '{se{ller}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{se{ller}']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (unexpected '{' in field name)"],
  ["item_text missing_paid_total '{ seller }'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{ seller }']], "x.json: grupa 'missing_paid_total', item_text: folosește doar câmpuri simple, ca {seller}"],
  ["item_text missing_paid_total '{ăă}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{ăă}']], "x.json: grupa 'missing_paid_total', item_text are câmpuri necunoscute ['ăă']; cele permise: ['seller', 'status']"],
  ["item_text missing_paid_total '{seller}}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller}}']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (Single '}' encountered in format string)"],
  ["item_text missing_paid_total '{{seller}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{{seller}']], "x.json: grupa 'missing_paid_total', item_text are acolade greșite (Single '}' encountered in format string)"],
  ["item_text missing_paid_total 'x{{'", [['set', ['grupe', 'missing_paid_total', 'item_text'], 'x{{']], null],
  ["item_text missing_paid_total '}}{{'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '}}{{']], null],
  ["item_text missing_paid_total '{seller}{status}{seller}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{seller}{status}{seller}']], null],
  ["item_text missing_paid_total '{status}'", [['set', ['grupe', 'missing_paid_total', 'item_text'], '{status}']], null],
  ["item_text other '{text}'", [['set', ['grupe', 'other', 'item_text'], '{text}']], null],
  ["item_text other '{text} {text}'", [['set', ['grupe', 'other', 'item_text'], '{text} {text}']], null],
  ["item_text other '{seller}'", [['set', ['grupe', 'other', 'item_text'], '{seller}']], "x.json: grupa 'other', item_text are câmpuri necunoscute ['seller']; cele permise: ['text']"],
  ["item_text other 'text fix'", [['set', ['grupe', 'other', 'item_text'], 'text fix']], null],
  ["item_text other '{text:}'", [['set', ['grupe', 'other', 'item_text'], '{text:}']], null],
  ["item_text other '{text!s:}'", [['set', ['grupe', 'other', 'item_text'], '{text!s:}']], "x.json: grupa 'other', item_text: folosește doar câmpuri simple, ca {text}"],
  ["item_text other '{text!s}'", [['set', ['grupe', 'other', 'item_text'], '{text!s}']], "x.json: grupa 'other', item_text: folosește doar câmpuri simple, ca {text}"],
  ["item_text other '{text:{text}}'", [['set', ['grupe', 'other', 'item_text'], '{text:{text}}']], "x.json: grupa 'other', item_text: folosește doar câmpuri simple, ca {text}"],
  ["item_text header_total_mismatch '{header} {blocks}'", [['set', ['grupe', 'header_total_mismatch', 'item_text'], '{header} {blocks}']], null],
  ["item_text header_total_mismatch '{blocks} / {header} / {nume}'", [['set', ['grupe', 'header_total_mismatch', 'item_text'], '{blocks} / {header} / {nume}']], "x.json: grupa 'header_total_mismatch', item_text are câmpuri necunoscute ['nume']; cele permise: ['header', 'blocks']"],
  ["item_text header_total_mismatch '{header}{'", [['set', ['grupe', 'header_total_mismatch', 'item_text'], '{header}{']], "x.json: grupa 'header_total_mismatch', item_text are acolade greșite (Single '{' encountered in format string)"],
  ["item_text pending_return_without_result '{products} {step}'", [['set', ['grupe', 'pending_return_without_result', 'item_text'], '{products} {step}']], null],
  ["item_text pending_return_without_result '{step}'", [['set', ['grupe', 'pending_return_without_result', 'item_text'], '{step}']], null],
  ["item_text pending_return_without_result '{products} {mode}'", [['set', ['grupe', 'pending_return_without_result', 'item_text'], '{products} {mode}']], "x.json: grupa 'pending_return_without_result', item_text are câmpuri necunoscute ['mode']; cele permise: ['products', 'step']"],
  ["item_text completed_return_without_refund '{products} {mode}'", [['set', ['grupe', 'completed_return_without_refund', 'item_text'], '{products} {mode}']], null],
  ["item_text completed_return_without_refund '{mode} {step}'", [['set', ['grupe', 'completed_return_without_refund', 'item_text'], '{mode} {step}']], "x.json: grupa 'completed_return_without_refund', item_text are câmpuri necunoscute ['step']; cele permise: ['products', 'mode']"],
  ["item_text completed_return_without_refund '{mode}}'", [['set', ['grupe', 'completed_return_without_refund', 'item_text'], '{mode}}']], "x.json: grupa 'completed_return_without_refund', item_text are acolade greșite (Single '}' encountered in format string)"],
  ["produse_in_plus 'încă {nume}'", [['set', ['valori_implicite', 'produse_in_plus'], 'încă {nume}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} ('nume')"],
  ["produse_in_plus '{}'", [['set', ['valori_implicite', 'produse_in_plus'], '{}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 0 out of range for positional args tuple)"],
  ["produse_in_plus '{0}'", [['set', ['valori_implicite', 'produse_in_plus'], '{0}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 0 out of range for positional args tuple)"],
  ["produse_in_plus '{1}'", [['set', ['valori_implicite', 'produse_in_plus'], '{1}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 1 out of range for positional args tuple)"],
  ["produse_in_plus '{007}'", [['set', ['valori_implicite', 'produse_in_plus'], '{007}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 7 out of range for positional args tuple)"],
  ["produse_in_plus '{٣}'", [['set', ['valori_implicite', 'produse_in_plus'], '{٣}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 3 out of range for positional args tuple)"],
  ["produse_in_plus '{'", [['set', ['valori_implicite', 'produse_in_plus'], '{']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Single '{' encountered in format string)"],
  ["produse_in_plus '}'", [['set', ['valori_implicite', 'produse_in_plus'], '}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Single '}' encountered in format string)"],
  ["produse_in_plus '{count'", [['set', ['valori_implicite', 'produse_in_plus'], '{count']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (expected '}' before end of string)"],
  ["produse_in_plus '{count} {x}'", [['set', ['valori_implicite', 'produse_in_plus'], '{count} {x}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} ('x')"],
  ["produse_in_plus '{{count}}'", [['set', ['valori_implicite', 'produse_in_plus'], '{{count}}']], null],
  ["produse_in_plus '{x}{count'", [['set', ['valori_implicite', 'produse_in_plus'], '{x}{count']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} ('x')"],
  ["produse_in_plus '{count} }'", [['set', ['valori_implicite', 'produse_in_plus'], '{count} }']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Single '}' encountered in format string)"],
  ["produse_in_plus '{count}'", [['set', ['valori_implicite', 'produse_in_plus'], '{count}']], null],
  ["produse_in_plus 'total: {count}{count}'", [['set', ['valori_implicite', 'produse_in_plus'], 'total: {count}{count}']], null],
  ["produse_in_plus '{ count }'", [['set', ['valori_implicite', 'produse_in_plus'], '{ count }']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (' count ')"],
  ["produse_in_plus '{.real}'", [['set', ['valori_implicite', 'produse_in_plus'], '{.real}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 0 out of range for positional args tuple)"],
  ["produse_in_plus '{[0]}'", [['set', ['valori_implicite', 'produse_in_plus'], '{[0]}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 0 out of range for positional args tuple)"],
  ["produse_in_plus '{count}{}'", [['set', ['valori_implicite', 'produse_in_plus'], '{count}{}']], "x.json: 'produse_in_plus' poate folosi doar câmpul {count} (Replacement index 0 out of range for positional args tuple)"],
];

describe('loadWarningTexts: aceleași validări și mesaje ca load_warning_texts din Python', () => {
  const base = readConfig('avertismente.json');

  for (const [name, operations, message] of WARNING_TEXT_CASES) {
    test(name, () => {
      const data = mutated(base, operations);
      if (message === null) assert.equal(loadWarningTexts(data, 'x.json'), data, 'configurarea validă se întoarce neschimbată (același obiect)');
      else assertValueError(() => loadWarningTexts(data, 'x.json'), message);
    });
  }

  test('config/avertismente.json din depozit e validă, iar numele și sursa se pun în mesaje', () => {
    assert.equal(loadWarningTexts(base, 'x.json'), base);
    assertValueError(() => loadWarningTexts([], 'configurarea mea'), "configurarea mea: trebuie să fie un obiect cu cheile-obiect 'grupe', 'etichete_status', 'valori_implicite'");
  });

  test('produse_in_plus cu specificator, conversie, atribut sau index: Python le acceptă, extensia le refuză (nu le completează)', () => {
    for (const template of ['încă {count:>3}', 'încă {count!r}', 'încă {count.real}', 'încă {count[0]}']) {
      const data = mutated(base, [['set', ['valori_implicite', 'produse_in_plus'], template]]);
      assert.throws(() => loadWarningTexts(data, 'x.json'), (error) => {
        assert.equal(error.name, 'ValueError');
        assert.ok(error.message.startsWith("x.json: 'produse_in_plus' poate folosi doar câmpul {count} (formatare neacceptată în extensie"), error.message);
        return true;
      });
    }
  });
});

// ---------- python_format: Formatter().parse și str.format(count=1), cu aceleași rezultate și erori ca în CPython ----------

// [șablon, ce dă string.Formatter().parse (lista de tupluri sau { eroare }), ce dă șablon.format(count=1) (textul sau { eroare: 'Tip: mesaj' })]; valorile vin din rularea lui Python 3.13.
const FORMAT_CASES = [
  ['', [], ''],
  ['text fix fara campuri', [['text fix fara campuri', null, null, null]], 'text fix fara campuri'],
  ['a {{b}} c', [['a {', null, null, null], ['b}', null, null, null], [' c', null, null, null]], 'a {b} c'],
  ['{{', [['{', null, null, null]], '{'],
  ['}}', [['}', null, null, null]], '}'],
  ['{{}}', [['{', null, null, null], ['}', null, null, null]], '{}'],
  ['{count}', [['', 'count', '', null]], '1'],
  ['încă {count}!', [['încă ', 'count', '', null], ['!', null, null, null]], 'încă 1!'],
  ['x{count}y{count}z', [['x', 'count', '', null], ['y', 'count', '', null], ['z', null, null, null]], 'x1y1z'],
  ['{{{count}}}', [['{', null, null, null], ['', 'count', '', null], ['}', null, null, null]], '{1}'],
  ['{', { eroare: "Single '{' encountered in format string" }, { eroare: "ValueError: Single '{' encountered in format string" }],
  ['}', { eroare: "Single '}' encountered in format string" }, { eroare: "ValueError: Single '}' encountered in format string" }],
  ['a{', { eroare: "Single '{' encountered in format string" }, { eroare: "ValueError: Single '{' encountered in format string" }],
  ['a}', { eroare: "Single '}' encountered in format string" }, { eroare: "ValueError: Single '}' encountered in format string" }],
  ['{}}', { eroare: "Single '}' encountered in format string" }, { eroare: 'IndexError: Replacement index 0 out of range for positional args tuple' }],
  ['{}', [['', '', '', null]], { eroare: 'IndexError: Replacement index 0 out of range for positional args tuple' }],
  ['{0}', [['', '0', '', null]], { eroare: 'IndexError: Replacement index 0 out of range for positional args tuple' }],
  ['{007}', [['', '007', '', null]], { eroare: 'IndexError: Replacement index 7 out of range for positional args tuple' }],
  ['{٣}', [['', '٣', '', null]], { eroare: 'IndexError: Replacement index 3 out of range for positional args tuple' }],
  ['{99999999999999999999999}', [['', '99999999999999999999999', '', null]], { eroare: 'ValueError: Too many decimal digits in format string' }],
  ['{x}', [['', 'x', '', null]], { eroare: "KeyError: 'x'" }],
  ['{ count}', [['', ' count', '', null]], { eroare: "KeyError: ' count'" }],
  ['{count', { eroare: "expected '}' before end of string" }, { eroare: "ValueError: expected '}' before end of string" }],
  ['{!', { eroare: 'end of string while looking for conversion specifier' }, { eroare: 'ValueError: end of string while looking for conversion specifier' }],
  ['{:', { eroare: "unmatched '{' in format spec" }, { eroare: "ValueError: unmatched '{' in format spec" }],
  ['{!!.', { eroare: "expected ':' after conversion specifier" }, { eroare: "ValueError: expected ':' after conversion specifier" }],
  ['{]{', { eroare: "unexpected '{' in field name" }, { eroare: "ValueError: unexpected '{' in field name" }],
  ['{x}}', { eroare: "Single '}' encountered in format string" }, { eroare: "KeyError: 'x'" }],
  ['{count}}', { eroare: "Single '}' encountered in format string" }, { eroare: "ValueError: Single '}' encountered in format string" }],
  ['{x}{count', { eroare: "expected '}' before end of string" }, { eroare: "KeyError: 'x'" }],
  ['{a[}]b}', [['', 'a[}]b', '', null]], { eroare: "KeyError: 'a'" }],
  ['{a!r:>5}', [['', 'a', '>5', 'r']], { eroare: "KeyError: 'a'" }],
  ['{a!}', { eroare: "unmatched '{' in format spec" }, { eroare: "ValueError: unmatched '{' in format spec" }],
  ['😀{count}😀', [['😀', 'count', '', null], ['😀', null, null, null]], '😀1😀'],
  ['{12}', [['', '12', '', null]], { eroare: 'IndexError: Replacement index 12 out of range for positional args tuple' }],
  ['{3000000000}', [['', '3000000000', '', null]], { eroare: 'IndexError: Replacement index 3000000000 out of range for positional args tuple' }],
  ['{9223372036854775807}', [['', '9223372036854775807', '', null]], { eroare: 'IndexError: Replacement index 9223372036854775807 out of range for positional args tuple' }],
  ['{9223372036854775808}', [['', '9223372036854775808', '', null]], { eroare: 'ValueError: Too many decimal digits in format string' }],
  ['{a:{b}}', [['', 'a', '{b}', null]], { eroare: "KeyError: 'a'" }],
  ['{a:{b}', { eroare: "unmatched '{' in format spec" }, { eroare: "ValueError: unmatched '{' in format spec" }],
  ['{a:{b}}}', { eroare: "Single '}' encountered in format string" }, { eroare: "KeyError: 'a'" }],
  ['{.a}', [['', '.a', '', null]], { eroare: 'IndexError: Replacement index 0 out of range for positional args tuple' }],
  ['{[0]}', [['', '[0]', '', null]], { eroare: 'IndexError: Replacement index 0 out of range for positional args tuple' }],
  ['{a.b.c}', [['', 'a.b.c', '', null]], { eroare: "KeyError: 'a'" }],
  ['{a!r}', [['', 'a', '', 'r']], { eroare: "KeyError: 'a'" }],
  ['{a!rr}', { eroare: "expected ':' after conversion specifier" }, { eroare: "ValueError: expected ':' after conversion specifier" }],
  ['{count}\n{count}', [['', 'count', '', null], ['\n', 'count', '', null]], '1\n1'],
  ['a\n{', { eroare: "Single '{' encountered in format string" }, { eroare: "ValueError: Single '{' encountered in format string" }],
];

describe('python_format: string.Formatter().parse și str.format cu câmpuri simple', () => {
  for (const [template, parsed, formatted] of FORMAT_CASES) {
    test(JSON.stringify(template), () => {
      if (parsed.eroare === undefined) assert.deepEqual([...formatterParse(template)], parsed);
      else assertValueError(() => [...formatterParse(template)], parsed.eroare);
      if (typeof formatted === 'string') {
        assert.equal(pyFormat(template, { count: 1 }), formatted);
      } else {
        const separator = formatted.eroare.indexOf(': ');
        const [type, message] = [formatted.eroare.slice(0, separator), formatted.eroare.slice(separator + 2)];
        assert.throws(() => pyFormat(template, { count: 1 }), (error) => {
          assert.equal(error.name, type);
          assert.equal(error.message, message);
          return true;
        });
      }
    });
  }

  test('formele pe care extensia nu le completează (atribut, index, specificator, conversie) sunt refuzate cu o eroare clară', () => {
    for (const template of ['{count.real}', '{count[0]}', '{count:>5}', '{count!r}', '{count!s:5}']) {
      assert.throws(() => pyFormat(template, { count: 1 }), /^Error: formatare neacceptată în extensie/);
    }
  });

  test('valorile text și întregi se scriu ca str(): textul ca atare, întregul fără zecimale', () => {
    assert.equal(pyFormat('{a}|{b}|{a}', { a: 'text {b}', b: 42 }), 'text {b}|42|text {b}');
    assert.equal(pyFormat('{{{b}}}', { b: -7 }), '{-7}');
  });
});

// ---------- modurile de restituire ----------

// [nume, intrarea (config/restituiri.json mutat), mesajul ValueError din load_refund_modes (x.json) | null]
const REFUND_MODE_CASES = [
  ['nu e obiect', [], "x.json: trebuie să fie un obiect cu listele 'bani_inapoi', 'credit_emag'"],
  ['obiect gol', {}, "x.json: 'bani_inapoi' trebuie să fie o listă de texte nevide"],
  ['credit_emag nu e listă', { bani_inapoi: ['a'], credit_emag: 'b' }, "x.json: 'credit_emag' trebuie să fie o listă de texte nevide"],
  ['credit_emag cu text gol', { bani_inapoi: ['a'], credit_emag: [''] }, "x.json: 'credit_emag' trebuie să fie o listă de texte nevide"],
  ['credit_emag cu text alb', { bani_inapoi: ['a'], credit_emag: ['   '] }, "x.json: 'credit_emag' trebuie să fie o listă de texte nevide"],
  ['credit_emag cu număr', { bani_inapoi: ['a'], credit_emag: [1] }, "x.json: 'credit_emag' trebuie să fie o listă de texte nevide"],
  ['bani_inapoi null', { bani_inapoi: null, credit_emag: ['a'] }, "x.json: 'bani_inapoi' trebuie să fie o listă de texte nevide"],
  ['un mod în ambele liste (după normalizare)', { bani_inapoi: ['Emitere voucher', 'z'], credit_emag: ['emitere  VOUCHER', 'a'] }, "x.json: un mod nu poate fi și „bani_inapoi”, și „credit_emag”: ['emitere voucher']"],
  ['două moduri în ambele liste, sortate', { bani_inapoi: ['Zeta', 'Alfa', 'x'], credit_emag: ['alfa', 'ZETA'] }, "x.json: un mod nu poate fi și „bani_inapoi”, și „credit_emag”: ['alfa', 'zeta']"],
  ['valid', { bani_inapoi: [' Vreau Banii Înapoi '], credit_emag: [] }, null],
];

describe('loadRefundModes și RefundModes', () => {
  for (const [name, data, message] of REFUND_MODE_CASES) {
    test(name, () => {
      if (message === null) assert.doesNotThrow(() => loadRefundModes(data, 'x.json'));
      else assertValueError(() => loadRefundModes(data, 'x.json'), message);
    });
  }

  test('modurile se normalizează (fără diacritice, litere mici, spații unice): RefundModes(cash={vreau banii inapoi})', () => {
    const modes = loadRefundModes({ bani_inapoi: [' Vreau Banii Înapoi '], credit_emag: [] }, 'x.json');
    assert.deepEqual([...modes.cash], ['vreau banii inapoi']);
    assert.deepEqual([...modes.credit], []);
  });

  test('isCredit și isKnown: normalizează modul; gol, null și nespecificat nu sunt credit și nu sunt cunoscute', () => {
    const modes = loadRefundModes(readConfig('restituiri.json'), 'x.json');
    assert.equal(modes.isCredit('Emitere voucher'), true);
    assert.equal(modes.isCredit('  EMITERE   VOUCHER '), true);
    assert.equal(modes.isCredit('Generare sold'), true);
    assert.equal(modes.isCredit('Vreau banii inapoi'), false);
    assert.equal(modes.isKnown('Vreau banii înapoi'), true);
    assert.equal(modes.isKnown('Generare sold'), true);
    assert.equal(modes.isKnown('Mod ciudat'), false);
    for (const empty of ['', null, undefined]) {
      assert.equal(modes.isCredit(empty), false);
      assert.equal(modes.isKnown(empty), false);
    }
  });

  test('RefundModes se poate construi direct cu seturi normalizate, ca în testele Python', () => {
    const modes = new RefundModes({ cash: [], credit: ['vreau banii inapoi'] });
    assert.equal(modes.isCredit('Vreau banii înapoi'), true);
    assert.equal(modes.isKnown('Vreau banii înapoi'), true);
  });
});

// ---------- culorile și cheia de produs ----------

// [nume, intrarea (config/culori.json mutat), mesajul ValueError din load_color_words (x.json) | null]
const COLOR_WORD_CASES = [
  ['nu e obiect', [], "x.json: trebuie să conțină un obiect cu cheia 'culori' = listă de texte"],
  ['rădăcina null', null, "x.json: trebuie să conțină un obiect cu cheia 'culori' = listă de texte"],
  ['lipsește cheia', {}, "x.json: trebuie să conțină un obiect cu cheia 'culori' = listă de texte"],
  ['culori nu e listă', { culori: 'x' }, "x.json: trebuie să conțină un obiect cu cheia 'culori' = listă de texte"],
  ['o intrare nu e text', { culori: ['alb', 1] }, "x.json: trebuie să conțină un obiect cu cheia 'culori' = listă de texte"],
  ['intrare fără niciun cuvânt', { culori: ['alb', ' - '] }, "x.json: intrare de culoare fără niciun cuvânt: ' - '"],
  ['intrare doar „_” (nu e cuvânt)', { culori: ['_'] }, "x.json: intrare de culoare fără niciun cuvânt: '_'"],
  ['intrare goală', { culori: [''] }, "x.json: intrare de culoare fără niciun cuvânt: ''"],
  ['valid', { culori: ['Alb', 'gri închis', 'gri'] }, null],
];

// [nume produs, lista de culori ('real' = config/culori.json, 'mici' = lista scrisă mai jos), cheia, culorile scoase, trunchiat, prefix]; ieșirile lui make_product_key din Python.
const PRODUCT_KEY_CASES = [
  ['Husa Kelmor Fit, silicon, Alb', 'real', 'husa kelmor fit silicon', ['alb'], false, 'husa kelmor fit, silicon, alb'],
  ['Husa Kelmor Fit, silicon, Alb', 'mici', 'husa kelmor fit silicon', ['alb'], false, 'husa kelmor fit, silicon, alb'],
  ['Husa Kelmor Fit, silicon, Negru', 'real', 'husa kelmor fit silicon', ['negru'], false, 'husa kelmor fit, silicon, negru'],
  ['Husa Kelmor Fit, silicon, Negru', 'mici', 'husa kelmor fit silicon negru', [], false, 'husa kelmor fit, silicon, negru'],
  ['husa kelmor fit silicon NEGRU', 'real', 'husa kelmor fit silicon', ['negru'], false, 'husa kelmor fit silicon negru'],
  ['husa kelmor fit silicon NEGRU', 'mici', 'husa kelmor fit silicon negru', [], false, 'husa kelmor fit silicon negru'],
  ['Telefon Vexor Y2, gri închis, 64GB', 'real', 'telefon vexor y2 64gb', ['gri inchis'], false, 'telefon vexor y2, gri inchis, 64gb'],
  ['Telefon Vexor Y2, gri închis, 64GB', 'mici', 'telefon vexor y2 64gb', ['gri inchis'], false, 'telefon vexor y2, gri inchis, 64gb'],
  ['Telefon Vexor Y2, gri deschis, 64GB', 'real', 'telefon vexor y2 64gb', ['gri deschis'], false, 'telefon vexor y2, gri deschis, 64gb'],
  ['Telefon Vexor Y2, gri deschis, 64GB', 'mici', 'telefon vexor y2 64gb', ['gri deschis'], false, 'telefon vexor y2, gri deschis, 64gb'],
  ['Televizor Smart 43" negru', 'real', 'televizor smart 43', ['negru'], false, 'televizor smart 43" negru'],
  ['Televizor Smart 43" negru', 'mici', 'televizor smart 43 negru', [], false, 'televizor smart 43" negru'],
  ['Televizor Smart 55" alb', 'real', 'televizor smart 55', ['alb'], false, 'televizor smart 55" alb'],
  ['Televizor Smart 55" alb', 'mici', 'televizor smart 55', ['alb'], false, 'televizor smart 55" alb'],
  ['alb', 'real', 'alb', [], false, 'alb'],
  ['alb', 'mici', 'alb', [], false, 'alb'],
  ['Alb Negru', 'real', 'alb negru', [], false, 'alb negru'],
  ['Alb Negru', 'mici', 'negru', ['alb'], false, 'alb negru'],
  ['negru, alb', 'real', 'negru alb', [], false, 'negru, alb'],
  ['negru, alb', 'mici', 'negru', ['alb'], false, 'negru, alb'],
  ['Produs  cu   spatii', 'real', 'produs cu spatii', [], false, 'produs cu spatii'],
  ['Produs  cu   spatii', 'mici', 'produs cu spatii', [], false, 'produs cu spatii'],
  ['Produs_cu_underscore alb', 'real', 'produs cu underscore', ['alb'], false, 'produs_cu_underscore alb'],
  ['Produs_cu_underscore alb', 'mici', 'produs cu underscore', ['alb'], false, 'produs_cu_underscore alb'],
  ['a-b c.d', 'real', 'a b c d', [], false, 'a-b c.d'],
  ['a-b c.d', 'mici', 'a b c d', [], false, 'a-b c.d'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test [...]', 'real', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test [...]', 'mici', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test ...', 'real', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test ...', 'mici', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test …', 'real', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume foarte lung de produs cu multe cuvinte pentru test …', 'mici', 'nume foarte lung de produs cu multe cuvinte pentru test', [], true, 'nume foarte lung de produs cu multe cuvinte pentru test'],
  ['Nume scurt [...]', 'real', 'nume scurt', [], true, 'nume scurt'],
  ['Nume scurt [...]', 'mici', 'nume scurt', [], true, 'nume scurt'],
  ['Nume scurt   [...]  ', 'real', 'nume scurt', [], true, 'nume scurt'],
  ['Nume scurt   [...]  ', 'mici', 'nume scurt', [], true, 'nume scurt'],
  ['Nume cu virgula, [...]', 'real', 'nume cu virgula', [], true, 'nume cu virgula'],
  ['Nume cu virgula, [...]', 'mici', 'nume cu virgula', [], true, 'nume cu virgula'],
  ['Nume cu virgula , ... ', 'real', 'nume cu virgula', [], true, 'nume cu virgula'],
  ['Nume cu virgula , ... ', 'mici', 'nume cu virgula', [], true, 'nume cu virgula'],
  ['Telefon Vexor Y2, gri închis [...]', 'real', 'telefon vexor y2', ['gri inchis'], true, 'telefon vexor y2, gri inchis'],
  ['Telefon Vexor Y2, gri închis [...]', 'mici', 'telefon vexor y2', ['gri inchis'], true, 'telefon vexor y2, gri inchis'],
  ['[...]', 'real', '', [], true, ''],
  ['[...]', 'mici', '', [], true, ''],
  ['...', 'real', '', [], true, ''],
  ['...', 'mici', '', [], true, ''],
  ['', 'real', '', [], false, ''],
  ['', 'mici', '', [], false, ''],
  ['Cafea țărană 100 g', 'real', 'cafea tarana 100 g', [], false, 'cafea tarana 100 g'],
  ['Cafea țărană 100 g', 'mici', 'cafea tarana 100 g', [], false, 'cafea tarana 100 g'],
  ['Straße produs', 'real', 'strasse produs', [], false, 'strasse produs'],
  ['Straße produs', 'mici', 'strasse produs', [], false, 'strasse produs'],
  ['Produs 😀 alb', 'real', 'produs', ['alb'], false, 'produs 😀 alb'],
  ['Produs 😀 alb', 'mici', 'produs', ['alb'], false, 'produs 😀 alb'],
  ['Space Gray phone', 'real', 'phone', ['space gray'], false, 'space gray phone'],
  ['Space Gray phone', 'mici', 'phone', ['space gray'], false, 'space gray phone'],
  ['rose gold ring', 'real', 'ring', ['rose gold'], false, 'rose gold ring'],
  ['rose gold ring', 'mici', 'rose gold ring', [], false, 'rose gold ring'],
  ['Black  Friday white', 'real', 'friday', ['black', 'white'], false, 'black friday white'],
  ['Black  Friday white', 'mici', 'black friday white', [], false, 'black friday white'],
  ['gri închis', 'real', 'gri inchis', [], false, 'gri inchis'],
  ['gri închis', 'mici', 'gri inchis', [], false, 'gri inchis'],
  ['gri', 'real', 'gri', [], false, 'gri'],
  ['gri', 'mici', 'gri', [], false, 'gri'],
  ['Telefon gri gri închis alb', 'real', 'telefon', ['gri', 'gri inchis', 'alb'], false, 'telefon gri gri inchis alb'],
  ['Telefon gri gri închis alb', 'mici', 'telefon', ['gri', 'gri inchis', 'alb'], false, 'telefon gri gri inchis alb'],
  ['128GB negru 128GB alb', 'real', '128gb 128gb', ['negru', 'alb'], false, '128gb negru 128gb alb'],
  ['128GB negru 128GB alb', 'mici', '128gb negru 128gb', ['alb'], false, '128gb negru 128gb alb'],
  ['Televizor 43 inch alb', 'real', 'televizor 43 inch', ['alb'], false, 'televizor 43 inch alb'],
  ['Televizor 43 inch alb', 'mici', 'televizor 43 inch', ['alb'], false, 'televizor 43 inch alb'],
  ['produs ٣٤ alb', 'real', 'produs ٣٤', ['alb'], false, 'produs ٣٤ alb'],
  ['produs ٣٤ alb', 'mici', 'produs ٣٤', ['alb'], false, 'produs ٣٤ alb'],
  ['x² alb', 'real', 'x2', ['alb'], false, 'x2 alb'],
  ['x² alb', 'mici', 'x2', ['alb'], false, 'x2 alb'],
  ['café à la crème', 'real', 'cafe a la creme', [], false, 'cafe a la creme'],
  ['café à la crème', 'mici', 'cafe a la creme', [], false, 'cafe a la creme'],
  ['Produs 5% reducere negru', 'real', 'produs 5 reducere', ['negru'], false, 'produs 5% reducere negru'],
  ['Produs 5% reducere negru', 'mici', 'produs 5 reducere negru', [], false, 'produs 5% reducere negru'],
  ['100% bumbac alb', 'real', '100 bumbac', ['alb'], false, '100% bumbac alb'],
  ['100% bumbac alb', 'mici', '100 bumbac', ['alb'], false, '100% bumbac alb'],
  ['A+B alb', 'real', 'a b', ['alb'], false, 'a+b alb'],
  ['A+B alb', 'mici', 'a b', ['alb'], false, 'a+b alb'],
  ['Produs (negru) mare', 'real', 'produs mare', ['negru'], false, 'produs (negru) mare'],
  ['Produs (negru) mare', 'mici', 'produs negru mare', [], false, 'produs (negru) mare'],
  ["Produs 'alb' mic", 'real', 'produs mic', ['alb'], false, "produs 'alb' mic"],
  ["Produs 'alb' mic", 'mici', 'produs mic', ['alb'], false, "produs 'alb' mic"],
];
// ColorWords.strip: [cuvintele, cuvintele rămase, culorile scoase] cu lista „mici”; ieșirile lui ColorWords.strip din Python.
const STRIP_CASES = [
  [['x', 'y', 'z'], [], ['x y z']],
  [['x', 'y'], [], ['x y']],
  [['x'], [], ['x']],
  [['x', 'y', 'w'], ['w'], ['x y']],
  [['gri', 'închis'], ['închis'], ['gri']],
  [['gri', 'deschis', 'alb'], [], ['gri deschis', 'alb']],
  [['alb', 'alb'], [], ['alb', 'alb']],
  [[], [], []],
  [['space', 'gray', 'x', 'y', 'z', 'x'], [], ['space gray', 'x y z', 'x']],
  [['albastru', 'închis'], ['albastru', 'închis'], []],
  [['roșu'], ['roșu'], []],
  [['rosu'], [], ['rosu']],
];
const SMALL_COLOR_LIST = ['gri', 'gri închis', 'gri deschis', 'alb', 'Roșu', 'albastru închis', 'space gray', 'x y z', 'x y', 'x'];

describe('loadColorWords, ColorWords și makeProductKey', () => {
  for (const [name, data, message] of COLOR_WORD_CASES) {
    test(`loadColorWords: ${name}`, () => {
      if (message === null) assert.doesNotThrow(() => loadColorWords(data, 'x.json'));
      else assertValueError(() => loadColorWords(data, 'x.json'), message);
    });
  }

  const real = loadColorWords(readConfig('culori.json'), 'x.json');
  const small = new ColorWords(SMALL_COLOR_LIST);

  test('len(ColorWords): 77 de culori în config/culori.json, 10 în lista mică (dublurile dispar)', () => {
    assert.equal(real.length, 77);
    assert.equal(small.length, 10);
    assert.equal(new ColorWords(['alb', 'Alb', ' ALB ']).length, 1);
  });

  test('o intrare fără cuvinte din constructor: ValueError fără sursă', () => {
    assertValueError(() => new ColorWords(['alb', '...']), "intrare de culoare fără niciun cuvânt: '...'");
  });

  for (const [words, kept, removed] of STRIP_CASES) {
    test(`ColorWords.strip(${JSON.stringify(words)})`, () => {
      assert.deepEqual(small.strip(words), [kept, removed]);
    });
  }

  test(`makeProductKey pe ${PRODUCT_KEY_CASES.length} de nume: cheia, culorile, trunchierea și prefixul ca în Python`, () => {
    for (const [name, list, key, colors, truncated, prefix] of PRODUCT_KEY_CASES) {
      const got = makeProductKey(name, list === 'real' ? real : small);
      assert.deepEqual({ key: got.key, colors: [...got.colors], normalized: got.normalized, truncated: got.truncated, prefix: got.prefix },
        { key, colors, normalized: normalizeText(name), truncated, prefix }, `${JSON.stringify(name)} cu lista ${list}`);
    }
  });
});

// ---------- block_payment pe blocuri scrise de mână ----------

// [nume, câmpurile blocului, BlockPayment din Python]; „items” = [nume, total linie în bani, cantitate].
const BLOCK_PAYMENT_CASES = [
  ['livrat, suma afisata', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 10000, 1], ['B', 5000, 2]], paid_bani: 16499, vouchers_bani: [], shipping_bani: 1499, services_bani: [], other_bani: [] }, { paid_bani: 16499, source: 'total_platit', list_bani: 15000, products_paid_bani: 15000, fees_bani: 1499, discount_bani: 0, line_paid_bani: [10000, 5000] }],
  ['livrat, fara total platit: din componente', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 10000, 1], ['B', 5000, 2]], paid_bani: null, vouchers_bani: [-1500], shipping_bani: 999, services_bani: [149, 51], other_bani: [200] }, { paid_bani: 14899, source: 'componente', list_bani: 15000, products_paid_bani: 13500, fees_bani: 1399, discount_bani: 1500, line_paid_bani: [9000, 4500] }],
  ['anulat cu voucher', { seller: 'eMAG', status: 'CANCELLED', items: [['A', 20000, 1], ['B', 3000, 1]], paid_bani: 0, vouchers_bani: [-3000], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 20000, source: 'anulat', list_bani: 23000, products_paid_bani: 20000, fees_bani: 0, discount_bani: 3000, line_paid_bani: [17391, 2609] }],
  ['anulat, voucherul acopera tot', { seller: 'eMAG', status: 'CANCELLED', items: [['A', 2000, 1]], paid_bani: null, vouchers_bani: [-5000], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 0, source: 'anulat', list_bani: 2000, products_paid_bani: 0, fees_bani: 0, discount_bani: 2000, line_paid_bani: [0] }],
  ['livrat, voucher mai mare decat produsele', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 1000, 1]], paid_bani: -2501, vouchers_bani: [-5000], shipping_bani: 1499, services_bani: [], other_bani: [] }, { paid_bani: -2501, source: 'total_platit', list_bani: 1000, products_paid_bani: 0, fees_bani: -2501, discount_bani: 1000, line_paid_bani: [0] }],
  ['livrat, linie negativa', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 100000, 1], ['Custom Discount', -2500, 1], ['Custom Discount', -1, 1]], paid_bani: 97499, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 97499, source: 'total_platit', list_bani: 100000, products_paid_bani: 97499, fees_bani: 0, discount_bani: 2501, line_paid_bani: [97499, 0, 0] }],
  ['livrat, suma peste produse si taxe', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 5000, 1]], paid_bani: 6200, vouchers_bani: [], shipping_bani: 999, services_bani: [], other_bani: [] }, { paid_bani: 6200, source: 'total_platit', list_bani: 5000, products_paid_bani: 5000, fees_bani: 1200, discount_bani: 0, line_paid_bani: [5000] }],
  ['livrat, fara produse', { seller: 'eMAG', status: 'DELIVERED', items: [], paid_bani: 2000, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 2000, source: 'total_platit', list_bani: 0, products_paid_bani: 0, fees_bani: 2000, discount_bani: 0, line_paid_bani: [] }],
  ['in curs, fara total platit', { seller: 'eMAG', status: 'IN_PROGRESS', items: [['A', 7000, 2]], paid_bani: null, vouchers_bani: [], shipping_bani: 999, services_bani: [], other_bani: [] }, { paid_bani: 7999, source: 'componente', list_bani: 7000, products_paid_bani: 7000, fees_bani: 999, discount_bani: 0, line_paid_bani: [7000] }],
  ['livrat, restul cel mai mare', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 3333, 3], ['B', 3334, 3], ['C', 3333, 1]], paid_bani: 9700, vouchers_bani: [-100, -200], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 9700, source: 'total_platit', list_bani: 10000, products_paid_bani: 9700, fees_bani: 0, discount_bani: 300, line_paid_bani: [3233, 3234, 3233] }],
  ['livrat, alte taxe negative', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 5000, 1]], paid_bani: 5200, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [250, -50] }, { paid_bani: 5200, source: 'total_platit', list_bani: 5000, products_paid_bani: 5000, fees_bani: 200, discount_bani: 0, line_paid_bani: [5000] }],
  ['anulat, linie negativa', { seller: 'eMAG', status: 'CANCELLED', items: [['A', 8000, 1], ['Reducere', -3000, 1]], paid_bani: 0, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 5000, source: 'anulat', list_bani: 8000, products_paid_bani: 5000, fees_bani: 0, discount_bani: 3000, line_paid_bani: [5000, 0] }],
  ['plata fara livrare', { seller: 'eMAG', status: 'PAID_ONLY', items: [['Asigurare', 50000, 1]], paid_bani: 50000, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 50000, source: 'total_platit', list_bani: 50000, products_paid_bani: 50000, fees_bani: 0, discount_bani: 0, line_paid_bani: [50000] }],
  ['status necunoscut', { seller: 'eMAG', status: 'UNKNOWN', items: [['A', 1000, 1]], paid_bani: 1000, vouchers_bani: [], shipping_bani: 0, services_bani: [], other_bani: [] }, { paid_bani: 1000, source: 'total_platit', list_bani: 1000, products_paid_bani: 1000, fees_bani: 0, discount_bani: 0, line_paid_bani: [1000] }],
  ['totul zero', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 0, 1]], paid_bani: 0, vouchers_bani: [], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 0, source: 'total_platit', list_bani: 0, products_paid_bani: 0, fees_bani: 0, discount_bani: 0, line_paid_bani: [0] }],
  ['anulat, voucher pozitiv', { seller: 'eMAG', status: 'CANCELLED', items: [['A', 10000, 1]], paid_bani: 0, vouchers_bani: [500], shipping_bani: null, services_bani: [], other_bani: [] }, { paid_bani: 10000, source: 'anulat', list_bani: 10000, products_paid_bani: 10000, fees_bani: 0, discount_bani: 0, line_paid_bani: [10000] }],
  ['livrat, suma afisata mai mica decat taxele', { seller: 'eMAG', status: 'DELIVERED', items: [['A', 5000, 1]], paid_bani: 500, vouchers_bani: [], shipping_bani: 999, services_bani: [], other_bani: [] }, { paid_bani: 500, source: 'total_platit', list_bani: 5000, products_paid_bani: 0, fees_bani: 500, discount_bani: 5000, line_paid_bani: [0] }],
];

/** SellerBlock din câmpurile unui caz (liniile devin Item-uri; statusul se repetă ca text de status). */
function blockOf(fields) {
  return makeSellerBlock({
    seller: fields.seller, status: fields.status, status_text: fields.status, has_storno: false, items: fields.items.map(([name, total, qty]) => makeItem(name, total, qty)),
    paid_bani: fields.paid_bani, vouchers_bani: fields.vouchers_bani, shipping_bani: fields.shipping_bani, services_bani: fields.services_bani, other_bani: fields.other_bani,
  });
}

describe('blockPayment: suma blocului și împărțirea ei, ca în Python', () => {
  for (const [name, fields, expected] of BLOCK_PAYMENT_CASES) {
    test(name, () => {
      const payment = blockPayment(blockOf(fields));
      assert.deepEqual(payment, expected);
      assert.equal(payment.line_paid_bani.reduce((total, value) => total + value, 0) + payment.fees_bani, payment.paid_bani, 'invariant: liniile + taxele = suma blocului');
      assert.ok(Object.isFrozen(payment) && Object.isFrozen(payment.line_paid_bani), 'rezultatul e înghețat, ca dataclass-ul frozen din Python');
    });
  }

  test('blocul primit nu se modifică', () => {
    const block = blockOf(BLOCK_PAYMENT_CASES[1][1]);
    const before = structuredClone(block);
    blockPayment(block);
    assert.deepEqual(block, before);
  });
});

// ---------- current_order_warnings, returns_without_result, completed_returns_without_amount ----------

// [nume, blocurile ([vânzător, status, paid_bani]), avertismentele comenzii, ce întoarce current_order_warnings din Python]
const ORDER_WARNING_CASES = [
  ['fara avertismente', [['eMAG', 'DELIVERED', 100]], [], []],
  ['un bloc anulat fara suma: mesajul se scoate', [['Alfa', 'CANCELLED', null], ['eMAG', 'DELIVERED', 100]], ["comanda 500100, Alfa: lipsește 'Total platit'", 'alt mesaj'], ['alt mesaj']],
  ['un bloc legitim fara suma: mesajul ramane', [['Alfa', 'DELIVERED', null]], ["comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['doua mesaje, un bloc anulat si unul livrat fara suma', [['Alfa', 'CANCELLED', null], ['Alfa', 'DELIVERED', null]], ["comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['trei mesaje, doua blocuri anulate', [['Alfa', 'CANCELLED', null], ['Alfa', 'CANCELLED', null]], ["comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['mesaj pentru un vanzator fara blocuri', [['eMAG', 'DELIVERED', 100]], ["comanda 500100, Necunoscut: lipsește 'Total platit'"], ["comanda 500100, Necunoscut: lipsește 'Total platit'"]],
  ["bloc anulat cu suma 0: nu e 'fara suma'", [['Alfa', 'CANCELLED', 0]], ["comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['doi vanzatori, doar unul anulat', [['Alfa', 'CANCELLED', null], ['Beta', 'DELIVERED', null]], ["comanda 500100, Beta: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Beta: lipsește 'Total platit'"], ["comanda 500100, Beta: lipsește 'Total platit'", "comanda 500100, Beta: lipsește 'Total platit'"]],
  ['un mesaj, un bloc anulat si unul livrat fara suma: mesajul ramane', [['Alfa', 'CANCELLED', null], ['Alfa', 'DELIVERED', null]], ["comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['trei mesaje, un bloc livrat si doua anulate fara suma: se scoate unul', [['Alfa', 'DELIVERED', null], ['Alfa', 'CANCELLED', null], ['Alfa', 'CANCELLED', null]], ["comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'", "comanda 500100, Alfa: lipsește 'Total platit'"], ["comanda 500100, Alfa: lipsește 'Total platit'"]],
  ['ordinea mesajelor se pastreaza', [['Alfa', 'CANCELLED', null]], ['zeta', "comanda 500100, Alfa: lipsește 'Total platit'", 'alfa', 'comanda 500100, Alfa: niciun produs găsit'], ['zeta', 'alfa', 'comanda 500100, Alfa: niciun produs găsit']],
];

describe('avertismentele comenzii și selecțiile de retururi', () => {
  for (const [name, blockSpecs, warnings, expected] of ORDER_WARNING_CASES) {
    test(`currentOrderWarnings: ${name}`, () => {
      const blocks = blockSpecs.map(([seller, status, paid]) => makeSellerBlock({ seller, status, status_text: status, has_storno: false, paid_bani: paid }));
      const order = makeOrder({ order_id: '500100', placed_text: '', placed_at: '2024-01-01T10:00', header_total_bani: null, blocks, warnings });
      assert.deepEqual(currentOrderWarnings(order), expected);
      assert.deepEqual(order.warnings, warnings, 'avertismentele comenzii nu se modifică');
    });
  }

  test('returnsWithoutResult: cerute, nefinalizate și neanulate; completedReturnsWithoutAmount: finalizate fără sumă (0 e sumă)', () => {
    const base = { detail_path: '/user/return-history/1/1', order_ids: [], product_names: [], steps: [], refund_mode: '' };
    const returns = [
      makeReturnRequest({ ...base, return_id: '1', refund_bani: null, completed: false, cancelled: false }),
      makeReturnRequest({ ...base, return_id: '2', refund_bani: null, completed: false, cancelled: true }),
      makeReturnRequest({ ...base, return_id: '3', refund_bani: null, completed: true, cancelled: false }),
      makeReturnRequest({ ...base, return_id: '4', refund_bani: 0, completed: true, cancelled: false }),
      makeReturnRequest({ ...base, return_id: '5', refund_bani: 100, completed: true, cancelled: false }),
    ];
    assert.deepEqual(returnsWithoutResult(returns).map((ret) => ret.return_id), ['1']);
    assert.deepEqual(completedReturnsWithoutAmount(returns).map((ret) => ret.return_id), ['3']);
  });
});

// ---------- jurnalul (log) și argumentele lui analyze() ----------

// Mesajele pe care le scrie Python (logging) la analyze() pe scenariile din fixtură: [modul, nivel, text].
const LOG_CASES = [
  ['scenariu', null, [
    ['return_matcher', 'INFO', "retururi aplicate: 2 unități (din care 1 marcate 'anulat' de eMAG), 0 avertismente"],
    ['spend_analysis', 'INFO', 'analiză: 7 comenzi, plătit efectiv 308001 bani (păstrat la preț de listă 313001 bani), 0 avertismente'],
  ]],
  ['capcane_retururi', null, [
    ['return_matcher', 'INFO', "retururi aplicate: 20 unități (din care 1 marcate 'anulat' de eMAG), 7 avertismente"],
    ['spend_analysis', 'INFO', 'analiză: 7 comenzi, plătit efectiv 80749 bani (păstrat la preț de listă 65000 bani), 12 avertismente'],
  ]],
  ['capcane_sume', null, [
    ['return_matcher', 'INFO', "retururi aplicate: 3 unități (din care 1 marcate 'anulat' de eMAG), 0 avertismente"],
    ['spend_analysis', 'INFO', 'analiză: 16 comenzi, plătit efectiv 123578253 bani (păstrat la preț de listă 123583844 bani), 6 avertismente'],
  ]],
  ['gol', null, [
    ['return_matcher', 'INFO', "retururi aplicate: 0 unități (din care 0 marcate 'anulat' de eMAG), 0 avertismente"],
    ['spend_analysis', 'INFO', 'analiză: 0 comenzi, plătit efectiv 0 bani (păstrat la preț de listă 0 bani), 0 avertismente'],
  ]],
  // un mesaj „N retururi…” scris de o versiune veche pe comandă, fără nicio listă în date: lista câștigă, iar nepotrivirea ajunge în jurnal
  ['scenariu', "5 retururi cu cerere înregistrată dar fără rezultat: produsele lor rămân numărate ca păstrate", [
    ['return_matcher', 'INFO', "retururi aplicate: 2 unități (din care 1 marcate 'anulat' de eMAG), 0 avertismente"],
    ['warning_details', 'WARNING', 'avertismentul pending_return_without_result spune 5, dar lista din date are 0 rânduri'],
    ['spend_analysis', 'INFO', 'analiză: 7 comenzi, plătit efectiv 308001 bani (păstrat la preț de listă 313001 bani), 1 avertismente'],
  ]],
];

describe('analyze(): jurnalul și argumentele', () => {
  for (const [name, extraWarning, expected] of LOG_CASES) {
    test(`jurnalul ca în Python: ${name}${extraWarning ? ' (cu un număr din mesaj care nu se potrivește cu lista)' : ''}`, () => {
      const scenario = structuredClone(fixture.scenarii.find((candidate) => candidate.nume === name));
      if (extraWarning) scenario.comenzi[0].warnings.push(extraWarning);
      const records = [];
      const log = { info: (module, text) => records.push([module, 'INFO', text]), warning: (module, text) => records.push([module, 'WARNING', text]) };
      analyze(scenario.comenzi.map(orderFromDict), scenario.retururi.map(returnFromDict), new Classifier(scenario.reguli, 'reguli'), scenario.prag_bani, scenario.generat_la, {
        highlightCategories: scenario.evidentiate, warningTexts: WARNING_TEXTS, colorWords: COLOR_WORDS, refundModes: REFUND_MODES, log,
      });
      assert.deepEqual(records, expected);
    });
  }

  test('fără `log` analiza rulează la fel (jurnalul e opțional)', () => {
    const scenario = fixture.scenarii.find((candidate) => candidate.nume === 'scenariu');
    const withoutLog = runScenario(scenario).result;
    assertIdentical(withoutLog.summary, scenario.rezumat, 'rezumat');
  });

  test('textele avertismentelor, culorile și modurile de restituire sunt obligatorii (în extensie nu există fișierele din care le-ar citi Python)', () => {
    const classifier = new Classifier({ categories: [] }, 'reguli');
    const complete = { warningTexts: WARNING_TEXTS, colorWords: COLOR_WORDS, refundModes: REFUND_MODES };
    for (const missing of ['warningTexts', 'colorWords', 'refundModes']) {
      const options = { ...complete, [missing]: undefined };
      assert.throws(() => analyze([], [], classifier, 50000, '2026-01-01 00:00', options), (error) => error instanceof TypeError && error.message.includes(missing), missing);
    }
    assert.throws(() => analyze([], [], classifier, 50000, '2026-01-01 00:00'), TypeError);
    assert.equal(analyze([], [], classifier, 50000, '2026-01-01 00:00', complete).summary.meta.orders, 0);
  });

  test('categoriile evidențiate lipsă dau avertisment și total zero; categoria implicită există mereu', () => {
    const classifier = new Classifier({ categories: [{ name: 'Alcool', patterns: ['vin'] }] }, 'reguli');
    const { summary } = analyze([], [], classifier, 0, '2026-01-01 00:00', { highlightCategories: ['Alcool', 'Necategorizat', 'Lipsa'], warningTexts: WARNING_TEXTS, colorWords: COLOR_WORDS, refundModes: REFUND_MODES });
    assert.deepEqual(summary.warnings, ["categoria evidențiată «Lipsa» nu există în config/categorii.json: totalul ei apare 0"]);
    assert.deepEqual(Object.keys(summary.highlights), ['Alcool', 'Necategorizat', 'Lipsa']);
    assert.equal(summary.highlights.Lipsa.totals.name, 'Lipsa');
    assert.equal(summary.highlights.Lipsa.totals.kept_bani, 0);
  });
});

// ---------- scenarii mici: ramurile pe care cele 8 scenarii din fixtură nu le ating (găsite prin mutation testing) ----------

/** Un float din Python în rezultatul așteptat (procentele din istoricul prețurilor): comparat cu Object.is pe valoare. */
const fl = (value) => new PyFloat(value);

// Fiecare scenariu: comenzi și retururi în formă compactă, regulile de categorii, și DOAR cheile rezumatului pe care le-a dat Python pentru ele (cele care arată ramura).
// Comandă: [număr, data ISO | null, totalul din antet, [blocuri], avertismente]; bloc: [vânzător, status, [[nume, total linie, cantitate]], total plătit | null, vouchere, transport | null,
// servicii, alte taxe, storno, text status, de plată | null, total produse | null]; retur: [număr, [comenzi], [produse], finalizat, anulat, suma | null, modul, pașii].
const HAND_SCENARIOS = [
  {
    nume: 'status nou: bucățile se numără ca necunoscute',
    comenzi: [['100001', '2024-01-01T10:00', 5000, [['eMAG', 'STATUS_NOU', [['Produs Test', 5000, 2]], 5000, [], null, [], [], false, 'STATUS_NOU', null, 5000]], []]],
    retururi: [],
    asteptat: {
      orders: { total: 1, kept_all: 0, kept_partial: 0, returned_all: 0, cancelled_all: 0, in_progress: 0, paid_only: 0, unknown: 1, no_items: 0 },
      funnel: { ordered_bani: 5000, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 5000, kept_bani: 0, ordered_units: 2, cancelled_units: 0, returned_units: 0, pending_units: 0, unknown_units: 2, kept_units: 0 },
      warnings: ['1 produse necategorizate (adaugă reguli în config/categorii.personal.json)'],
    },
  },
  {
    nume: 'retur: nume trunchiat la limita de 30 de caractere, cu virgulă, cu „…”, la mijloc și nume foarte lung',
    comenzi: [['200001', '2024-01-01T10:00', 5000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyza [...]', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200002', '2024-01-02T10:00', 5000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzab [...]', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200003', '2024-01-03T10:00', 5000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzabc [...]', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200004', '2024-01-04T10:00', 5000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzab, [...]', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200005', '2024-01-05T10:00', 5000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzabcd ef…', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200006', '2024-01-06T10:00', 5000, [['eMAG', 'DELIVERED', [['klmnopqrst uvwxyzabcd efghijklmn [...]', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []], ['200007', '2024-01-07T10:00', 5000, [['eMAG', 'DELIVERED', [['lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime unic', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [['3000001', ['200001'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000002', ['200002'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000003', ['200003'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000004', ['200004'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000005', ['200005'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000006', ['200006'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000007', ['200007'], ['lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime lungime unic'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      returns: { matched_units: 5, matched_from_cancelled_units: 0, unmatched_refund_bani: 10000 },
      warnings: ["retur 3000001: produsul 'abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx' nu are potrivire în comanda ['200001']", "retur 3000006: produsul 'abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrstuvwx' nu are potrivire în comanda ['200006']", '7 produse necategorizate (adaugă reguli în config/categorii.personal.json)'],
      funnel: { ordered_bani: 35000, cancelled_bani: 0, returned_bani: 25000, pending_bani: 0, unknown_bani: 0, kept_bani: 10000, ordered_units: 7, cancelled_units: 0, returned_units: 5, pending_units: 0, unknown_units: 0, kept_units: 2 },
    },
  },
  {
    nume: 'retur: nume identic și nume trunchiat în aceeași comandă',
    comenzi: [['210001', '2024-02-01T10:00', 5000, [['Alfa SRL', 'CANCELLED', [['abcdefghij klmnopqrst uvwxyzabcd [...]', 5000, 1]], 0, [], null, [], [], false, 'CANCELLED', null, 5000], ['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrst', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [['3000050', ['210001'], ['abcdefghij klmnopqrst uvwxyzabcd efghijklmn opqrst'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      returns: { matched_units: 1, matched_from_cancelled_units: 0, unmatched_refund_bani: 0 },
      funnel: { ordered_bani: 10000, cancelled_bani: 5000, returned_bani: 5000, pending_bani: 0, unknown_bani: 0, kept_bani: 0, ordered_units: 2, cancelled_units: 1, returned_units: 1, pending_units: 0, unknown_units: 0, kept_units: 0 },
      paid: { spent_bani: 0, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [], funnel: { ordered_bani: 10000, cancelled_bani: 5000, returned_bani: 5000, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 0, ordered_units: 2, cancelled_units: 1, returned_units: 1, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 5000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 5000, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 0, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: [], values: { '2024': {} } } },
    },
  },
  {
    nume: 'retur: comenzile lui lipsesc din lista citită',
    comenzi: [],
    retururi: [['3000100', ['111', '222'], ['Produs X'], true, false, 700, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      warnings: ['retur 3000100: comanda 111, 222 nu e în lista citită'],
      returns: { matched_units: 0, matched_from_cancelled_units: 0, unmatched_refund_bani: 700 },
      reconciliation: { paid_delivered_bani: 0, vouchers_delivered_bani: 0, shipping_delivered_bani: 0, services_delivered_bani: 0, returns_total: 1, returns_completed: 1, returns_cancelled: 0, returns_pending: 0, refunds_bani: 700, refunds_without_amount: 0, refund_modes: { 'Vreau banii inapoi': 1 }, header_total_mismatches: [], orders_with_storno: [] },
    },
  },
  {
    nume: 'retur peste un bloc anulat și unul livrat',
    comenzi: [['300001', '2024-02-01T10:00', 22000, [['Alfa SRL', 'CANCELLED', [['Rucsac Alfa', 15000, 1]], 0, [], null, [], [], false, 'CANCELLED', null, 15000], ['eMAG', 'DELIVERED', [['Casti Beta', 22000, 1]], 22000, [], null, [], [], false, 'DELIVERED', null, 22000]], []]],
    retururi: [['3000200', ['300001'], ['Rucsac Alfa', 'Casti Beta'], true, false, 30000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      paid: { spent_bani: 0, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [], funnel: { ordered_bani: 37000, cancelled_bani: 0, returned_bani: 37000, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 0, ordered_units: 2, cancelled_units: 0, returned_units: 2, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 22000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 22000, estimated_refunds_bani: 22000, estimated_refunds: 1, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 0, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 15000, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: -7000 }, by_year_category: { years: ['2024'], series: [], values: { '2024': {} } } },
    },
  },
  {
    nume: 'retur pe o linie de valoare zero',
    comenzi: [['300002', '2024-03-01T10:00', 0, [['eMAG', 'DELIVERED', [['Cadou Test', 0, 1]], 0, [], null, [], [], false, 'DELIVERED', null, 0]], []]],
    retururi: [['3000300', ['300002'], ['Cadou Test'], true, false, 500, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      paid: { spent_bani: -500, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: -500, extra_rows: [{ key: 'refund_differences', name: 'Diferențe la restituiri', bani: -500 }], funnel: { ordered_bani: 0, cancelled_bani: 0, returned_bani: 500, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: -500, ordered_units: 1, cancelled_units: 0, returned_units: 1, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 0, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 500, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: -500, spent_bani: -500, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Altele'], values: { '2024': { Altele: -500 } } } },
    },
  },
  {
    nume: 'retur în așteptare cu mod necunoscut',
    comenzi: [['300003', '2024-03-02T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs Test', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [['3000400', ['300003'], ['Produs Test'], false, false, null, 'Mod ciudat', ['Cerere inregistrata']]],
    asteptat: {
      warnings: ['1 retur cu cerere înregistrată dar fără rezultat: produsul lui rămâne numărat ca păstrat', '1 produse necategorizate (adaugă reguli în config/categorii.personal.json)'],
    },
  },
  {
    nume: 'un bloc livrat fără produse creează anul',
    comenzi: [['300004', '2018-05-05T10:00', 0, [['eMAG', 'DELIVERED', [], 0, [], null, [], [], false, 'DELIVERED', null, 0]], []]],
    retururi: [],
    asteptat: {
      by_year: [{ year: '2018', orders: 1, orders_with_kept: 0, ordered_bani: 0, kept_bani: 0, kept_units: 0, returned_bani: 0, cancelled_bani: 0, paid_ordered_bani: 0, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0, paid_unknown_bani: 0, paid_fees_bani: 0, spent_bani: 0 }],
      paid: { spent_bani: 0, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [], funnel: { ordered_bani: 0, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 0, ordered_units: 0, cancelled_units: 0, returned_units: 0, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 0, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 0, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2018'], series: [], values: { '2018': {} } } },
    },
  },
  {
    nume: 'două retururi pe aceeași linie',
    comenzi: [['300005', '2024-04-01T10:00', 30000, [['eMAG', 'DELIVERED', [['Produs Trei', 30000, 3]], 30000, [], null, [], [], false, 'DELIVERED', null, 30000]], []]],
    retururi: [['3000500', ['300005'], ['Produs Trei', 'Produs Trei'], true, false, null, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000501', ['300005'], ['Produs Trei'], true, false, 9000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      paid: { spent_bani: 1000, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 1000, extra_rows: [{ key: 'refund_differences', name: 'Diferențe la restituiri', bani: 1000 }], funnel: { ordered_bani: 30000, cancelled_bani: 0, returned_bani: 29000, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 1000, ordered_units: 3, cancelled_units: 0, returned_units: 3, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 30000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 29000, estimated_refunds_bani: 20000, estimated_refunds: 1, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 1000, spent_bani: 1000, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Diferențe la restituiri'], values: { '2024': { 'Diferențe la restituiri': 1000 } } } },
    },
  },
  {
    nume: 'același număr de retur de două ori',
    comenzi: [['300006', '2024-04-02T10:00', 20000, [['eMAG', 'DELIVERED', [['Produs Doi', 20000, 2]], 20000, [], null, [], [], false, 'DELIVERED', null, 20000]], []]],
    retururi: [['3000600', ['300006'], ['Produs Doi'], true, false, 1000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000600', ['300006'], ['Produs Doi'], true, false, 2000, 'Emitere voucher', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      paid: { spent_bani: 20000, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 20000, credit_returns_units: 2, refund_differences_bani: 0, extra_rows: [{ key: 'credit_returns', name: 'Retururi cu voucher sau sold eMAG', bani: 20000 }], funnel: { ordered_bani: 20000, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 20000, ordered_units: 2, cancelled_units: 0, returned_units: 0, credit_units: 2, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 20000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 20000, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 20000, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Retururi cu voucher sau sold eMAG'], values: { '2024': { 'Retururi cu voucher sau sold eMAG': 20000 } } } },
    },
  },
  {
    nume: 'istoric: prețul pe bucată rotunjit la zero bani e un cadou',
    comenzi: [['400001', '2024-01-01T10:00', 1, [['eMAG', 'DELIVERED', [['Produs Mic', 1, 3]], 1, [], null, [], [], false, 'DELIVERED', null, 1]], []], ['400002', '2024-02-01T10:00', 1, [['eMAG', 'DELIVERED', [['Produs Mic', 1, 3]], 1, [], null, [], [], false, 'DELIVERED', null, 1]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 0, purchases: 0, units: 0, overpaid_vs_min_bani: 0, last_vs_prev: { cheaper_products: 0, pricier_products: 0, same_products: 0, cheaper_bani: 0, pricier_bani: 0 } }, products: [] },
    },
  },
  {
    nume: 'istoric: prefix trunchiat de exact 30 de caractere, cu punctuație care nu intră în cheie',
    comenzi: [['410001', '2024-01-01T10:00', 10000, [['eMAG', 'DELIVERED', [['abcdefghij,.klmnopqrst,.uvwxyz more words here', 10000, 1]], 10000, [], null, [], [], false, 'DELIVERED', null, 10000]], []], ['410002', '2024-02-01T10:00', 12000, [['eMAG', 'DELIVERED', [['abcdefghij,.klmnopqrst,.uvwxyz [...]', 12000, 1]], 12000, [], null, [], [], false, 'DELIVERED', null, 12000]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 2000, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 2000 } }, products: [{ key: 'abcdefghij klmnopqrst uvwxyz more words here', name: 'abcdefghij,.klmnopqrst,.uvwxyz more words here', category: 'Necategorizat', purchases: [{ date: '2024-01-01', order_id: '410001', seller: 'eMAG', name: 'abcdefghij,.klmnopqrst,.uvwxyz more words here', qty: 1, unit_bani: 10000 }, { date: '2024-02-01', order_id: '410002', seller: 'eMAG', name: 'abcdefghij,.klmnopqrst,.uvwxyz [...]', qty: 1, unit_bani: 12000 }], kept_units: 2, first_unit_bani: 10000, last_unit_bani: 12000, min_unit_bani: 10000, max_unit_bani: 12000, last_vs_prev_unit_bani: 2000, last_vs_prev_pct: fl(20.0), last_vs_prev_impact_bani: 2000, overpaid_vs_min_bani: 2000, color_variants: false }] },
    },
  },
  {
    nume: 'istoric: prefixul cheii de exact 30 de caractere, cu punctuație în nume',
    comenzi: [['420001', '2024-01-01T10:00', 10000, [['eMAG', 'DELIVERED', [['abcdefghij klmnopqrst uvwxyzabcd efghij', 10000, 1]], 10000, [], null, [], [], false, 'DELIVERED', null, 10000]], []], ['420002', '2024-02-01T10:00', 11000, [['eMAG', 'DELIVERED', [['abcdefghij, klmnopqrst, uvwxyzab [...]', 11000, 1]], 11000, [], null, [], [], false, 'DELIVERED', null, 11000]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 1000, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 1000 } }, products: [{ key: 'abcdefghij klmnopqrst uvwxyzabcd efghij', name: 'abcdefghij klmnopqrst uvwxyzabcd efghij', category: 'Necategorizat', purchases: [{ date: '2024-01-01', order_id: '420001', seller: 'eMAG', name: 'abcdefghij klmnopqrst uvwxyzabcd efghij', qty: 1, unit_bani: 10000 }, { date: '2024-02-01', order_id: '420002', seller: 'eMAG', name: 'abcdefghij, klmnopqrst, uvwxyzab [...]', qty: 1, unit_bani: 11000 }], kept_units: 2, first_unit_bani: 10000, last_unit_bani: 11000, min_unit_bani: 10000, max_unit_bani: 11000, last_vs_prev_unit_bani: 1000, last_vs_prev_pct: fl(10.0), last_vs_prev_impact_bani: 1000, overpaid_vs_min_bani: 1000, color_variants: false }] },
    },
  },
  {
    nume: 'istoric: nume trunchiat care se potrivește cu două grupe rămâne separat',
    comenzi: [['430001', '2024-01-01T10:00', 10000, [['eMAG', 'DELIVERED', [['alpha beta gamma delta epsilon zeta eta theta 128gb', 10000, 1]], 10000, [], null, [], [], false, 'DELIVERED', null, 10000]], []], ['430002', '2024-02-01T10:00', 11000, [['eMAG', 'DELIVERED', [['alpha beta gamma delta epsilon zeta eta theta 256gb', 11000, 1]], 11000, [], null, [], [], false, 'DELIVERED', null, 11000]], []], ['430003', '2024-03-01T10:00', 12000, [['eMAG', 'DELIVERED', [['alpha beta gamma delta epsilon zeta eta [...]', 12000, 1]], 12000, [], null, [], [], false, 'DELIVERED', null, 12000]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 0, purchases: 0, units: 0, overpaid_vs_min_bani: 0, last_vs_prev: { cheaper_products: 0, pricier_products: 0, same_products: 0, cheaper_bani: 0, pricier_bani: 0 } }, products: [] },
    },
  },
  {
    nume: 'istoric: la aceeași dată, numărul mai scurt de comandă e mai vechi',
    comenzi: [['9', '2024-05-05T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs Ordine', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['10', '2024-05-05T10:00', 2000, [['eMAG', 'DELIVERED', [['Produs Ordine', 2000, 1]], 2000, [], null, [], [], false, 'DELIVERED', null, 2000]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 1000, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 1000 } }, products: [{ key: 'produs ordine', name: 'Produs Ordine', category: 'Necategorizat', purchases: [{ date: '2024-05-05', order_id: '9', seller: 'eMAG', name: 'Produs Ordine', qty: 1, unit_bani: 1000 }, { date: '2024-05-05', order_id: '10', seller: 'eMAG', name: 'Produs Ordine', qty: 1, unit_bani: 2000 }], kept_units: 2, first_unit_bani: 1000, last_unit_bani: 2000, min_unit_bani: 1000, max_unit_bani: 2000, last_vs_prev_unit_bani: 1000, last_vs_prev_pct: fl(100.0), last_vs_prev_impact_bani: 1000, overpaid_vs_min_bani: 1000, color_variants: false }] },
    },
  },
  {
    nume: 'istoric: categoria vine de la ultima cumpărare',
    comenzi: [['440001', '2024-01-01T10:00', 3000, [['eMAG', 'DELIVERED', [['Husa Test Negru', 3000, 1]], 3000, [], null, [], [], false, 'DELIVERED', null, 3000]], []], ['440002', '2024-02-01T10:00', 3500, [['eMAG', 'DELIVERED', [['Husa Test Rosu', 3500, 1]], 3500, [], null, [], [], false, 'DELIVERED', null, 3500]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Rosii', patterns: ['\\brosu\\b'] }] },
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 500, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 500 } }, products: [{ key: 'husa test', name: 'Husa Test Rosu', category: 'Rosii', purchases: [{ date: '2024-01-01', order_id: '440001', seller: 'eMAG', name: 'Husa Test Negru', qty: 1, unit_bani: 3000 }, { date: '2024-02-01', order_id: '440002', seller: 'eMAG', name: 'Husa Test Rosu', qty: 1, unit_bani: 3500 }], kept_units: 2, first_unit_bani: 3000, last_unit_bani: 3500, min_unit_bani: 3000, max_unit_bani: 3500, last_vs_prev_unit_bani: 500, last_vs_prev_pct: fl(16.7), last_vs_prev_impact_bani: 500, overpaid_vs_min_bani: 500, color_variants: true }] },
    },
  },
  {
    nume: 'istoric: același nume trunchiat în două comenzi',
    comenzi: [['450001', '2024-01-01T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs foarte lung de test cu multe cuvinte aici [...]', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['450002', '2024-02-01T10:00', 1200, [['eMAG', 'DELIVERED', [['Produs foarte lung de test cu multe cuvinte aici [...]', 1200, 1]], 1200, [], null, [], [], false, 'DELIVERED', null, 1200]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 200, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 200 } }, products: [{ key: 'produs foarte lung de test cu multe cuvinte aici', name: 'Produs foarte lung de test cu multe cuvinte aici [...]', category: 'Necategorizat', purchases: [{ date: '2024-01-01', order_id: '450001', seller: 'eMAG', name: 'Produs foarte lung de test cu multe cuvinte aici [...]', qty: 1, unit_bani: 1000 }, { date: '2024-02-01', order_id: '450002', seller: 'eMAG', name: 'Produs foarte lung de test cu multe cuvinte aici [...]', qty: 1, unit_bani: 1200 }], kept_units: 2, first_unit_bani: 1000, last_unit_bani: 1200, min_unit_bani: 1000, max_unit_bani: 1200, last_vs_prev_unit_bani: 200, last_vs_prev_pct: fl(20.0), last_vs_prev_impact_bani: 200, overpaid_vs_min_bani: 200, color_variants: false }] },
    },
  },
  {
    nume: 'istoric: un nume trunchiat nu se alătură unei grupe formate doar din nume trunchiate',
    comenzi: [['460001', '2024-01-01T10:00', 1000, [['eMAG', 'DELIVERED', [['alpha beta gamma delta epsilon zeta eta theta iota [...]', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['460002', '2024-02-01T10:00', 1100, [['eMAG', 'DELIVERED', [['alpha beta gamma delta epsilon zeta eta [...]', 1100, 1]], 1100, [], null, [], [], false, 'DELIVERED', null, 1100]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 0, purchases: 0, units: 0, overpaid_vs_min_bani: 0, last_vs_prev: { cheaper_products: 0, pricier_products: 0, same_products: 0, cheaper_bani: 0, pricier_bani: 0 } }, products: [] },
    },
  },
  {
    nume: 'avertismente: eticheta blocului fără sumă, pe rând, și comanda care lipsește din listă',
    comenzi: [['500001', '2024-03-01T10:00', 0, [['Alfa', 'CANCELLED', [['P1', 1000, 1]], 0, [], null, [], [], false, 'CANCELLED', null, 1000], ['Alfa', 'DELIVERED', [['P2', 1000, 1]], null, [], null, [], [], false, 'DELIVERED', null, 1000], ['Alfa', 'IN_PROGRESS', [['P3', 1000, 1]], null, [], null, [], [], false, 'IN_PROGRESS', null, 1000]], ["comanda 500001, Alfa: lipsește 'Total platit'", "comanda 500001, Alfa: lipsește 'Total platit'", "comanda 999999, Alfa: lipsește 'Total platit'"]]],
    retururi: [],
    asteptat: {
      warnings_detail: [{ kind: 'missing_paid_total', title: 'Comenzi la care lipsește „Total plătit”', explanation: 'Pagina comenzii nu arată suma plătită pentru un vânzător, deși produsele au fost livrate, ridicate sau sunt în curs. La un bloc livrat sau ridicat, suma plătită se calculează atunci din componente (produse, reduceri, transport și taxe) și intră așa în „cât ai cheltuit”; programul nu o poate verifica cu pagina.', affects_totals: false, what_to_do: 'Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo. De obicei suma din componente e exactă; poate diferi doar dacă pagina are o reducere sau o taxă pe care programul nu o recunoaște.', count: 3, items: [{ order_ids: ['500001'], return_id: null, seller: 'Alfa', status: 'livrat sau ridicat', placed_at: '2024-03-01', text: 'Alfa: blocul nu afișează „Total plătit” (livrat sau ridicat)', return_url: null }, { order_ids: ['500001'], return_id: null, seller: 'Alfa', status: 'în curs, încă nelivrat', placed_at: '2024-03-01', text: 'Alfa: blocul nu afișează „Total plătit” (în curs, încă nelivrat)', return_url: null }, { order_ids: ['999999'], return_id: null, seller: 'Alfa', status: 'status necunoscut', placed_at: null, text: 'Alfa: blocul nu afișează „Total plătit” (status necunoscut)', return_url: null }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: false, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 1, items: [{ order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '3 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }] }],
    },
  },
  {
    nume: 'avertismente: retururi cu exact 3 produse, fără pași, fără mod, cu produse în plus, pe două comenzi',
    comenzi: [['510001', '2024-03-01T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs A', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['510002', '2024-01-05T10:00', 2000, [['eMAG', 'DELIVERED', [['Produs B', 2000, 1]], 2000, [], null, [], [], false, 'DELIVERED', null, 2000]], []]],
    retururi: [['3000700', ['510002', '510001'], ['P A', 'P B', 'P C'], false, false, null, 'Vreau banii inapoi', []], ['3000701', ['510001'], ['P A', 'P B', 'P C', 'P D'], true, false, null, '', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      warnings_detail: [{ kind: 'pending_return_without_result', title: 'Retururi cerute, dar fără rezultat', explanation: 'Ai înregistrat o cerere de retur, dar pagina ei nu arată încă pasul „Restituire suma” și nici anularea cererii. Până când se termină, produsul rămâne numărat ca păstrat.', affects_totals: true, what_to_do: 'Verifică starea returului pe eMAG. Când e finalizat, rulează din nou programul: produsul va fi trecut la „returnat” și totalurile se vor corecta.', count: 1, items: [{ order_ids: ['510002', '510001'], return_id: '3000700', seller: null, status: null, placed_at: '2024-01-05', text: 'cerere de retur pentru P A; P B; P C; ultimul pas înregistrat: necunoscut', return_url: 'https://www.emag.ro/user/return-history/1/3000700' }] }, { kind: 'completed_return_without_refund', title: 'Retururi finalizate fără sumă restituită afișată', explanation: 'Returul e finalizat, dar pagina lui nu spune ce sumă s-a restituit. Produsul trece la „returnat”. Dacă banii s-au întors în cont, „cât ai cheltuit” presupune că ți s-a restituit partea plătită a produsului (prețul minus partea lui din reduceri), cum face eMAG la retururile cu sumă afișată; estimarea e numărată separat în cifrele de control. La un retur cu voucher sau sold eMAG suma nu contează: nu se scade nimic.', affects_totals: false, what_to_do: 'Dacă vrei să verifici, deschide returul pe eMAG și compară suma restituită cu partea plătită a produsului.', count: 1, items: [{ order_ids: ['510001'], return_id: '3000701', seller: null, status: 'Restituire suma', placed_at: '2024-03-01', text: 'retur finalizat pentru P A; P B; P C; încă 1; mod de restituire: nespecificat', return_url: 'https://www.emag.ro/user/return-history/1/3000701' }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: true, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 6, items: [{ order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '2 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }, { order_ids: [], return_id: '3000701', seller: null, status: null, placed_at: null, text: 'retur 3000701: mod de restituire necunoscut („necompletat”), tratat ca bani primiți înapoi (adaugă-l în config/restituiri.json)', return_url: 'https://www.emag.ro/user/return-history/1/3000701' }, { order_ids: [], return_id: '3000701', seller: null, status: null, placed_at: null, text: "retur 3000701: produsul 'P A' nu are potrivire în comanda ['510001']", return_url: 'https://www.emag.ro/user/return-history/1/3000701' }, { order_ids: [], return_id: '3000701', seller: null, status: null, placed_at: null, text: "retur 3000701: produsul 'P B' nu are potrivire în comanda ['510001']", return_url: 'https://www.emag.ro/user/return-history/1/3000701' }, { order_ids: [], return_id: '3000701', seller: null, status: null, placed_at: null, text: "retur 3000701: produsul 'P C' nu are potrivire în comanda ['510001']", return_url: 'https://www.emag.ro/user/return-history/1/3000701' }, { order_ids: [], return_id: '3000701', seller: null, status: null, placed_at: null, text: "retur 3000701: produsul 'P D' nu are potrivire în comanda ['510001']", return_url: 'https://www.emag.ro/user/return-history/1/3000701' }] }],
    },
  },
  {
    nume: 'categorii: la aceeași sumă plătită, mai întâi cea cu valoare de listă mai mare',
    comenzi: [['520001', '2024-01-01T10:00', 10000, [['eMAG', 'DELIVERED', [['Produs zeta', 15000, 1]], 10000, [-5000], null, [], [], false, 'DELIVERED', null, 15000]], []], ['520002', '2024-01-02T10:00', 10000, [['eMAG', 'DELIVERED', [['Produs alfa', 10000, 1]], 10000, [], null, [], [], false, 'DELIVERED', null, 10000]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Zeta', patterns: ['zeta'] }, { name: 'Alfa', patterns: ['alfa'] }] },
    asteptat: {
      by_category: [{ name: 'Zeta', ordered_bani: 15000, ordered_units: 1, kept_bani: 15000, kept_units: 1, returned_bani: 0, returned_units: 0, cancelled_bani: 0, cancelled_units: 0, pending_bani: 0, paid_ordered_bani: 10000, paid_kept_bani: 10000, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0 }, { name: 'Alfa', ordered_bani: 10000, ordered_units: 1, kept_bani: 10000, kept_units: 1, returned_bani: 0, returned_units: 0, cancelled_bani: 0, cancelled_units: 0, pending_bani: 0, paid_ordered_bani: 10000, paid_kept_bani: 10000, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0 }],
    },
  },
  {
    nume: 'top produse: la aceeași dată, numărul mai lung de comandă e mai nou',
    comenzi: [['9', '2024-06-06T12:00', 1000, [['eMAG', 'DELIVERED', [['Produs Top', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['10', '2024-06-06T12:00', 1000, [['eMAG', 'DELIVERED', [['Produs Top', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []]],
    retururi: [],
    asteptat: {
      top_products: [{ name: 'Produs Top', category: 'Necategorizat', units: 2, bani: 2000, paid_bani: 2000, order_id: '10', order_count: 2 }],
    },
  },
  {
    nume: 'top produse: același număr de comandă de două ori, data cea mai târzie',
    comenzi: [['600001', '2024-03-01T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs Dub', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['600002', '2024-02-01T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs Dub', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['600001', '2024-01-01T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs Dub', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []]],
    retururi: [],
    asteptat: {
      top_products: [{ name: 'Produs Dub', category: 'Necategorizat', units: 3, bani: 3000, paid_bani: 3000, order_id: '600001', order_count: 2 }],
    },
  },
  {
    nume: 'achiziții mari: bucata returnată din anulat și cea rămasă anulată',
    comenzi: [['700001', '2024-04-01T10:00', 0, [['Alfa SRL', 'CANCELLED', [['Televizor Mare', 200000, 2]], 0, [], null, [], [], false, 'CANCELLED', null, 200000]], []]],
    retururi: [['3000800', ['700001'], ['Televizor Mare'], true, false, 100000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      big: { threshold_bani: 50000, items: [{ order_id: '700001', date: '2024-04-01', name: 'Televizor Mare', seller: 'Alfa SRL', category: 'Necategorizat', qty: 1, unit_bani: 100000, amount_bani: 100000, paid_amount_bani: 100000, state: 'returned', returned_from_cancelled: true }, { order_id: '700001', date: '2024-04-01', name: 'Televizor Mare', seller: 'Alfa SRL', category: 'Necategorizat', qty: 1, unit_bani: 100000, amount_bani: 100000, paid_amount_bani: 100000, state: 'cancelled', returned_from_cancelled: false }], kept_bani: 0, returned_bani: 100000, cancelled_bani: 100000, pending_bani: 0, unknown_bani: 0, kept_units: 0, returned_units: 1, cancelled_units: 1, pending_units: 0, unknown_units: 0, kept_paid_bani: 0, returned_paid_bani: 100000, cancelled_paid_bani: 100000, pending_paid_bani: 0, unknown_paid_bani: 0 },
    },
  },
  {
    nume: 'comenzi: în curs și necunoscut în aceeași comandă',
    comenzi: [['710001', '2024-05-01T10:00', 2000, [['eMAG', 'IN_PROGRESS', [['P1', 1000, 1]], 1000, [], null, [], [], false, 'IN_PROGRESS', null, 1000], ['eMAG', 'UNKNOWN', [['P2', 1000, 1]], 1000, [], null, [], [], false, 'UNKNOWN', null, 1000]], []]],
    retururi: [],
    asteptat: {
      orders: { total: 1, kept_all: 0, kept_partial: 0, returned_all: 0, cancelled_all: 0, in_progress: 1, paid_only: 0, unknown: 0, no_items: 0 },
    },
  },
  {
    nume: 'control: comenzile cu storno, sortate',
    comenzi: [['720002', '2024-01-01T10:00', 1000, [['eMAG', 'DELIVERED', [['P1', 1000, 1]], 1000, [], null, [], [], true, 'DELIVERED', null, 1000]], []], ['720001', '2024-02-01T10:00', 1000, [['eMAG', 'DELIVERED', [['P2', 1000, 1]], 1000, [], null, [], [], true, 'DELIVERED', null, 1000]], []]],
    retururi: [],
    asteptat: {
      reconciliation: { paid_delivered_bani: 2000, vouchers_delivered_bani: 0, shipping_delivered_bani: 0, services_delivered_bani: 0, returns_total: 0, returns_completed: 0, returns_cancelled: 0, returns_pending: 0, refunds_bani: 0, refunds_without_amount: 0, refund_modes: {}, header_total_mismatches: [], orders_with_storno: ['720001', '720002'] },
    },
  },
  {
    nume: 'retururi fără sumă: comanda lipsă și fără comenzi',
    comenzi: [],
    retururi: [['3000101', ['333'], ['Y'], true, false, null, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000102', [], ['Z'], true, false, null, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']], ['3000103', [], ['W'], true, false, 300, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      warnings: ['retur 3000101: comanda 333 nu e în lista citită', 'retur 3000102: nu are nicio comandă asociată', 'retur 3000103: nu are nicio comandă asociată', '2 retururi finalizate fără sumă restituită afișată'],
      returns: { matched_units: 0, matched_from_cancelled_units: 0, unmatched_refund_bani: 300 },
    },
  },
  {
    nume: 'un an doar cu o comandă fără blocuri: sumele plătite ale anului sunt zero',
    comenzi: [['310001', '2022-02-02T10:00', 0, [], []], ['310002', '2023-03-03T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs Test', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [],
    asteptat: {
      by_year: [{ year: '2022', orders: 1, orders_with_kept: 0, ordered_bani: 0, kept_bani: 0, kept_units: 0, returned_bani: 0, cancelled_bani: 0, paid_ordered_bani: 0, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0, paid_unknown_bani: 0, paid_fees_bani: 0, spent_bani: 0 }, { year: '2023', orders: 1, orders_with_kept: 1, ordered_bani: 5000, kept_bani: 5000, kept_units: 1, returned_bani: 0, cancelled_bani: 0, paid_ordered_bani: 5000, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0, paid_unknown_bani: 0, paid_fees_bani: 0, spent_bani: 5000 }],
    },
  },
  {
    nume: 'comandă fără dată: achiziție mare, categorie evidențiată, plată fără livrare, în curs',
    comenzi: [['320001', null, 205000, [['eMAG', 'DELIVERED', [['Televizor Mare', 200000, 1]], 200000, [], null, [], [], false, 'DELIVERED', null, 200000], ['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['eMAG', 'IN_PROGRESS', [['Cablu Test', 2000, 1]], 2000, [], null, [], [], false, 'IN_PROGRESS', null, 2000]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Televizoare', patterns: ['televizor'] }] },
    evidentiate: ['Televizoare'],
    asteptat: {
      big: { threshold_bani: 50000, items: [{ order_id: '320001', date: '', name: 'Televizor Mare', seller: 'eMAG', category: 'Televizoare', qty: 1, unit_bani: 200000, amount_bani: 200000, paid_amount_bani: 200000, state: 'kept', returned_from_cancelled: false }], kept_bani: 200000, returned_bani: 0, cancelled_bani: 0, pending_bani: 0, unknown_bani: 0, kept_units: 1, returned_units: 0, cancelled_units: 0, pending_units: 0, unknown_units: 0, kept_paid_bani: 200000, returned_paid_bani: 0, cancelled_paid_bani: 0, pending_paid_bani: 0, unknown_paid_bani: 0 },
      highlights: { Televizoare: { totals: { name: 'Televizoare', ordered_bani: 200000, ordered_units: 1, kept_bani: 200000, kept_units: 1, returned_bani: 0, returned_units: 0, cancelled_bani: 0, cancelled_units: 0, pending_bani: 0, paid_ordered_bani: 200000, paid_kept_bani: 200000, paid_returned_bani: 0, paid_cancelled_bani: 0, paid_pending_bani: 0 }, items: [{ order_id: '320001', date: '', name: 'Televizor Mare', qty: 1, amount_bani: 200000, paid_amount_bani: 200000, state: 'kept' }], items_total: 1 } },
      paid_only: [{ order_id: '320001', date: '', seller: 'eMAG Asigurari', names: ['Asigurare Test'], products_bani: 3000, paid_bani: 3000, status_text: 'PAID_ONLY' }],
      in_progress: [{ order_id: '320001', date: '', seller: 'eMAG', names: ['Cablu Test'], products_bani: 2000, paid_bani: 2000, status_text: 'IN_PROGRESS' }],
    },
  },
  {
    nume: 'avertismente: date stricate, retur fără produse, retur necunoscut, status fără etichetă',
    comenzi: [['330001', '2024-3-5T10:00', 1234, [['eMAG', 'DELIVERED', [['Produs A', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['330002', null, 1500, [['eMAG', 'DELIVERED', [['Produs B', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['330003', '2024-04-04T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs C', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], ["retur 3009999: produsul 'X' nu are potrivire în comanda ['330003']"]], ['330004', '2024-05-05T10:00', 0, [['Alfa', 'STATUS_NOU', [['Produs D', 1000, 1]], null, [], null, [], [], false, 'STATUS_NOU', null, 1000]], ["comanda 330004, Alfa: lipsește 'Total platit'"]]],
    retururi: [['3000900', ['330001'], [], false, false, null, 'Vreau banii inapoi', ['Cerere inregistrata']]],
    asteptat: {
      warnings_detail: [{ kind: 'missing_paid_total', title: 'Comenzi la care lipsește „Total plătit”', explanation: 'Pagina comenzii nu arată suma plătită pentru un vânzător, deși produsele au fost livrate, ridicate sau sunt în curs. La un bloc livrat sau ridicat, suma plătită se calculează atunci din componente (produse, reduceri, transport și taxe) și intră așa în „cât ai cheltuit”; programul nu o poate verifica cu pagina.', affects_totals: false, what_to_do: 'Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo. De obicei suma din componente e exactă; poate diferi doar dacă pagina are o reducere sau o taxă pe care programul nu o recunoaște.', count: 1, items: [{ order_ids: ['330004'], return_id: null, seller: 'Alfa', status: 'STATUS_NOU', placed_at: '2024-05-05', text: 'Alfa: blocul nu afișează „Total plătit” (STATUS_NOU)', return_url: null }] }, { kind: 'pending_return_without_result', title: 'Retururi cerute, dar fără rezultat', explanation: 'Ai înregistrat o cerere de retur, dar pagina ei nu arată încă pasul „Restituire suma” și nici anularea cererii. Până când se termină, produsul rămâne numărat ca păstrat.', affects_totals: true, what_to_do: 'Verifică starea returului pe eMAG. Când e finalizat, rulează din nou programul: produsul va fi trecut la „returnat” și totalurile se vor corecta.', count: 1, items: [{ order_ids: ['330001'], return_id: '3000900', seller: null, status: 'Cerere inregistrata', placed_at: null, text: 'cerere de retur pentru produsele nu sunt listate; ultimul pas înregistrat: Cerere inregistrata', return_url: 'https://www.emag.ro/user/return-history/1/3000900' }] }, { kind: 'header_total_mismatch', title: 'Comenzi la care totalul din antet nu e egal cu suma blocurilor', explanation: 'Totalul scris în partea de sus a comenzii diferă de suma sumelor plătite ale vânzătorilor din ea. Cauza cea mai frecventă: comanda are un bloc anulat, iar antetul include încă „Total de plată” al acelui bloc (atunci nu e o problemă). Alte cauze posibile: o reducere sau o taxă pe care programul nu a recunoscut-o, un bloc fără „Total plătit” sau o comandă modificată după plasare.', affects_totals: false, what_to_do: 'La comenzile fără bloc anulat, deschide comanda pe eMAG și verifică totalul. „Cât ai cheltuit” se calculează din „Total plătit” al fiecărui bloc, nu din antet; diferența afectează doar această verificare.', count: 2, items: [{ order_ids: ['330001'], return_id: null, seller: null, status: null, placed_at: null, text: 'total din antet 12,34 Lei, suma blocurilor 10,00 Lei', return_url: null }, { order_ids: ['330002'], return_id: null, seller: null, status: null, placed_at: null, text: 'total din antet 15,00 Lei, suma blocurilor 10,00 Lei', return_url: null }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: true, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 2, items: [{ order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '4 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }, { order_ids: [], return_id: '3009999', seller: null, status: null, placed_at: null, text: "retur 3009999: produsul 'X' nu are potrivire în comanda ['330003']", return_url: null }] }],
    },
  },
  {
    nume: 'avertismente: fără etichete de status în configurare',
    comenzi: [['340001', '2024-06-06T10:00', 0, [['Alfa', 'DELIVERED', [['Produs E', 1000, 1]], null, [], null, [], [], false, 'DELIVERED', null, 1000]], ["comanda 340001, Alfa: lipsește 'Total platit'", "comanda 349999, Alfa: lipsește 'Total platit'"]]],
    retururi: [],
    etichete: {},
    asteptat: {
      warnings_detail: [{ kind: 'missing_paid_total', title: 'Comenzi la care lipsește „Total plătit”', explanation: 'Pagina comenzii nu arată suma plătită pentru un vânzător, deși produsele au fost livrate, ridicate sau sunt în curs. La un bloc livrat sau ridicat, suma plătită se calculează atunci din componente (produse, reduceri, transport și taxe) și intră așa în „cât ai cheltuit”; programul nu o poate verifica cu pagina.', affects_totals: false, what_to_do: 'Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo. De obicei suma din componente e exactă; poate diferi doar dacă pagina are o reducere sau o taxă pe care programul nu o recunoaște.', count: 2, items: [{ order_ids: ['340001'], return_id: null, seller: 'Alfa', status: 'DELIVERED', placed_at: '2024-06-06', text: 'Alfa: blocul nu afișează „Total plătit” (DELIVERED)', return_url: null }, { order_ids: ['349999'], return_id: null, seller: 'Alfa', status: '', placed_at: null, text: 'Alfa: blocul nu afișează „Total plătit” ()', return_url: null }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: false, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 1, items: [{ order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '1 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }] }],
    },
  },
  {
    nume: 'avertismente: mai multe mesaje decât blocuri fără sumă, contor pe comandă, bloc cu suma afișată, vânzător cu toate sumele afișate',
    comenzi: [['350001', '2024-07-01T10:00', 1000, [['Alfa', 'DELIVERED', [['P1', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000], ['Alfa', 'IN_PROGRESS', [['P2', 1000, 1]], null, [], null, [], [], false, 'IN_PROGRESS', null, 1000], ['Alfa', 'DELIVERED', [['P3', 1000, 1]], null, [], null, [], [], false, 'DELIVERED', null, 1000], ['Alfa', 'UNKNOWN', [['P4', 1000, 1]], null, [], null, [], [], false, 'UNKNOWN', null, 1000]], ["comanda 350001, Alfa: lipsește 'Total platit'", "comanda 350001, Alfa: lipsește 'Total platit'", "comanda 350001, Alfa: lipsește 'Total platit'", "comanda 350001, Alfa: lipsește 'Total platit'", "comanda 350001, Alfa: lipsește 'Total platit'"]], ['350002', '2024-07-02T10:00', 0, [['Alfa', 'IN_PROGRESS', [['P5', 1000, 1]], null, [], null, [], [], false, 'IN_PROGRESS', null, 1000], ['Alfa', 'DELIVERED', [['P6', 1000, 1]], null, [], null, [], [], false, 'DELIVERED', null, 1000]], ["comanda 350002, Alfa: lipsește 'Total platit'"]], ['350003', '2024-07-03T10:00', 1000, [['Beta', 'DELIVERED', [['P7', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], ["comanda 350003, Beta: lipsește 'Total platit'"]]],
    retururi: [],
    asteptat: {
      warnings_detail: [{ kind: 'missing_paid_total', title: 'Comenzi la care lipsește „Total plătit”', explanation: 'Pagina comenzii nu arată suma plătită pentru un vânzător, deși produsele au fost livrate, ridicate sau sunt în curs. La un bloc livrat sau ridicat, suma plătită se calculează atunci din componente (produse, reduceri, transport și taxe) și intră așa în „cât ai cheltuit”; programul nu o poate verifica cu pagina.', affects_totals: false, what_to_do: 'Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo. De obicei suma din componente e exactă; poate diferi doar dacă pagina are o reducere sau o taxă pe care programul nu o recunoaște.', count: 7, items: [{ order_ids: ['350001'], return_id: null, seller: 'Alfa', status: 'livrat sau ridicat', placed_at: '2024-07-01', text: 'Alfa: blocul nu afișează „Total plătit” (livrat sau ridicat)', return_url: null }, { order_ids: ['350001'], return_id: null, seller: 'Alfa', status: 'status necunoscut', placed_at: '2024-07-01', text: 'Alfa: blocul nu afișează „Total plătit” (status necunoscut)', return_url: null }, { order_ids: ['350001'], return_id: null, seller: 'Alfa', status: 'status necunoscut', placed_at: '2024-07-01', text: 'Alfa: blocul nu afișează „Total plătit” (status necunoscut)', return_url: null }, { order_ids: ['350001'], return_id: null, seller: 'Alfa', status: 'status necunoscut', placed_at: '2024-07-01', text: 'Alfa: blocul nu afișează „Total plătit” (status necunoscut)', return_url: null }, { order_ids: ['350001'], return_id: null, seller: 'Alfa', status: 'în curs, încă nelivrat', placed_at: '2024-07-01', text: 'Alfa: blocul nu afișează „Total plătit” (în curs, încă nelivrat)', return_url: null }, { order_ids: ['350002'], return_id: null, seller: 'Alfa', status: 'în curs, încă nelivrat', placed_at: '2024-07-02', text: 'Alfa: blocul nu afișează „Total plătit” (în curs, încă nelivrat)', return_url: null }, { order_ids: ['350003'], return_id: null, seller: 'Beta', status: 'livrat sau ridicat', placed_at: '2024-07-03', text: 'Beta: blocul nu afișează „Total plătit” (livrat sau ridicat)', return_url: null }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: true, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 2, items: [{ order_ids: ['350001'], return_id: null, seller: 'Alfa', status: null, placed_at: '2024-07-01', text: "status necunoscut la comanda 350001 (Alfa): 'UNKNOWN'", return_url: null }, { order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '7 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }] }],
    },
  },
  {
    nume: 'retur nepotrivit și fără sumă',
    comenzi: [['360001', '2024-08-01T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs Existent', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [['3000950', ['360001'], ['Produs Inexistent Complet Diferit'], true, false, null, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      returns: { matched_units: 0, matched_from_cancelled_units: 0, unmatched_refund_bani: 0 },
      warnings: ["retur 3000950: produsul 'Produs Inexistent Complet Diferit' nu are potrivire în comanda ['360001']", '1 retur finalizat fără sumă restituită afișată', '1 produse necategorizate (adaugă reguli în config/categorii.personal.json)'],
    },
  },
  {
    nume: 'categorii: una cu totul returnată nu apare în graficul pe ani',
    comenzi: [['370001', '2024-09-01T10:00', 10000, [['eMAG', 'DELIVERED', [['Produs alfa', 10000, 1]], 10000, [], null, [], [], false, 'DELIVERED', null, 10000]], []], ['370002', '2024-09-02T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs beta', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [['3000960', ['370002'], ['Produs beta'], true, false, 5000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    reguli: { categories: [{ name: 'Alfa', patterns: ['alfa'] }, { name: 'Beta', patterns: ['beta'] }] },
    asteptat: {
      by_year_category: { years: ['2024'], series: ['Alfa'], values: { '2024': { Alfa: 10000 } } },
      paid: { spent_bani: 10000, spent_units: 1, list_kept_bani: 10000, discounts_kept_bani: 0, products_kept_bani: 10000, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [], funnel: { ordered_bani: 15000, cancelled_bani: 0, returned_bani: 5000, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 10000, ordered_units: 2, cancelled_units: 0, returned_units: 1, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 1 }, reconciliation: { paid_delivered_bani: 15000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 5000, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 10000, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Alfa'], values: { '2024': { Alfa: 10000 } } } },
    },
  },
  {
    nume: 'clasament: la aceeași sumă, numele hotărăște între o categorie și un rând de transport',
    comenzi: [['380001', '2024-10-01T10:00', 2000, [['eMAG', 'DELIVERED', [['Produs zeta', 1000, 1]], 2000, [], 1000, [], [], false, 'DELIVERED', null, 1000]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Zeta', patterns: ['zeta'] }] },
    asteptat: {
      paid: { spent_bani: 2000, spent_units: 1, list_kept_bani: 1000, discounts_kept_bani: 0, products_kept_bani: 1000, fees_bani: 1000, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [{ key: 'fees', name: 'Transport și taxe', bani: 1000 }], funnel: { ordered_bani: 1000, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 1000, spent_bani: 2000, ordered_units: 1, cancelled_units: 0, returned_units: 0, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 1 }, reconciliation: { paid_delivered_bani: 2000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 2000, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Transport și taxe', 'Zeta'], values: { '2024': { 'Transport și taxe': 1000, Zeta: 1000 } } } },
    },
  },
  {
    nume: 'clasament: un rând care nu e produs de exact un ban',
    comenzi: [['390001', '2024-11-01T10:00', 5001, [['eMAG', 'DELIVERED', [['Produs alfa', 5000, 1]], 5001, [], null, [], [1], false, 'DELIVERED', null, 5000]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Alfa', patterns: ['alfa'] }] },
    asteptat: {
      paid: { spent_bani: 5001, spent_units: 1, list_kept_bani: 5000, discounts_kept_bani: 0, products_kept_bani: 5000, fees_bani: 1, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [{ key: 'fees', name: 'Transport și taxe', bani: 1 }], funnel: { ordered_bani: 5000, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 1, spent_bani: 5001, ordered_units: 1, cancelled_units: 0, returned_units: 0, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 1 }, reconciliation: { paid_delivered_bani: 5001, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 5001, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Alfa', 'Transport și taxe'], values: { '2024': { Alfa: 5000, 'Transport și taxe': 1 } } } },
    },
  },
  {
    nume: 'vânzători: la aceeași sumă plătită, mai întâi cel cu valoare de listă mai mare',
    comenzi: [['391001', '2024-11-02T10:00', 1000, [['Alfa SRL', 'DELIVERED', [['Produs a', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['391002', '2024-11-03T10:00', 1000, [['Zeta Market', 'DELIVERED', [['Produs z', 1500, 1]], 1000, [-500], null, [], [], false, 'DELIVERED', null, 1500]], []]],
    retururi: [],
    asteptat: {
      by_seller: [{ seller: 'Zeta Market', units: 1, bani: 1500, paid_bani: 1000 }, { seller: 'Alfa SRL', units: 1, bani: 1000, paid_bani: 1000 }],
    },
  },
  {
    nume: 'retur peste două linii de valoare zero, cu sumă afișată',
    comenzi: [['395001', '2024-12-01T10:00', 0, [['eMAG', 'DELIVERED', [['Cadou Unu', 0, 1], ['Cadou Doi', 0, 1]], 0, [], null, [], [], false, 'DELIVERED', null, 0]], []]],
    retururi: [['3000970', ['395001'], ['Cadou Unu', 'Cadou Doi'], true, false, 500, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      paid: { spent_bani: -500, spent_units: 0, list_kept_bani: 0, discounts_kept_bani: 0, products_kept_bani: 0, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: -500, extra_rows: [{ key: 'refund_differences', name: 'Diferențe la restituiri', bani: -500 }], funnel: { ordered_bani: 0, cancelled_bani: 0, returned_bani: 500, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: -500, ordered_units: 2, cancelled_units: 0, returned_units: 2, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 0, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 500, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: -500, spent_bani: -500, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Altele'], values: { '2024': { Altele: -500 } } } },
    },
  },
  {
    nume: 'istoric: un produs returnat integral într-o a doua comandă nu intră în istoric',
    comenzi: [['396001', '2024-01-01T10:00', 3000, [['eMAG', 'DELIVERED', [['Produs Revenit', 3000, 1]], 3000, [], null, [], [], false, 'DELIVERED', null, 3000]], []], ['396002', '2024-02-01T10:00', 3200, [['eMAG', 'DELIVERED', [['Produs Revenit', 3200, 1]], 3200, [], null, [], [], false, 'DELIVERED', null, 3200]], []]],
    retururi: [['3000980', ['396002'], ['Produs Revenit'], true, false, 3200, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      price_history: { summary: { products: 0, purchases: 0, units: 0, overpaid_vs_min_bani: 0, last_vs_prev: { cheaper_products: 0, pricier_products: 0, same_products: 0, cheaper_bani: 0, pricier_bani: 0 } }, products: [] },
    },
  },
  {
    nume: 'istoric: prețul de exact un ban pe bucată e un preț',
    comenzi: [['397001', '2024-01-01T10:00', 1, [['eMAG', 'DELIVERED', [['Produs Ban', 1, 1]], 1, [], null, [], [], false, 'DELIVERED', null, 1]], []], ['397002', '2024-02-01T10:00', 1, [['eMAG', 'DELIVERED', [['Produs Ban', 1, 1]], 1, [], null, [], [], false, 'DELIVERED', null, 1]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 0, last_vs_prev: { cheaper_products: 0, pricier_products: 0, same_products: 1, cheaper_bani: 0, pricier_bani: 0 } }, products: [{ key: 'produs ban', name: 'Produs Ban', category: 'Necategorizat', purchases: [{ date: '2024-01-01', order_id: '397001', seller: 'eMAG', name: 'Produs Ban', qty: 1, unit_bani: 1 }, { date: '2024-02-01', order_id: '397002', seller: 'eMAG', name: 'Produs Ban', qty: 1, unit_bani: 1 }], kept_units: 2, first_unit_bani: 1, last_unit_bani: 1, min_unit_bani: 1, max_unit_bani: 1, last_vs_prev_unit_bani: 0, last_vs_prev_pct: fl(0.0), last_vs_prev_impact_bani: 0, overpaid_vs_min_bani: 0, color_variants: false }] },
    },
  },
  {
    nume: 'istoric: ordinea cronologică când prima cifră a anului diferă',
    comenzi: [['398001', '2024-05-05T10:00', 2000, [['eMAG', 'DELIVERED', [['Produs Vechi', 2000, 1]], 2000, [], null, [], [], false, 'DELIVERED', null, 2000]], []], ['398002', '1999-05-05T10:00', 1000, [['eMAG', 'DELIVERED', [['Produs Vechi', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []]],
    retururi: [],
    asteptat: {
      price_history: { summary: { products: 1, purchases: 2, units: 2, overpaid_vs_min_bani: 1000, last_vs_prev: { cheaper_products: 0, pricier_products: 1, same_products: 0, cheaper_bani: 0, pricier_bani: 1000 } }, products: [{ key: 'produs vechi', name: 'Produs Vechi', category: 'Necategorizat', purchases: [{ date: '1999-05-05', order_id: '398002', seller: 'eMAG', name: 'Produs Vechi', qty: 1, unit_bani: 1000 }, { date: '2024-05-05', order_id: '398001', seller: 'eMAG', name: 'Produs Vechi', qty: 1, unit_bani: 2000 }], kept_units: 2, first_unit_bani: 1000, last_unit_bani: 2000, min_unit_bani: 1000, max_unit_bani: 2000, last_vs_prev_unit_bani: 1000, last_vs_prev_pct: fl(100.0), last_vs_prev_impact_bani: 1000, overpaid_vs_min_bani: 1000, color_variants: false }] },
    },
  },
  {
    nume: 'comenzi: plata fără livrare, singură și împreună cu fiecare altă stare',
    comenzi: [['400101', '2024-01-01T10:00', 3000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000]], []], ['400102', '2024-01-02T10:00', 4000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['eMAG', 'DELIVERED', [['P1', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['400103', '2024-01-03T10:00', 4000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['eMAG', 'IN_PROGRESS', [['P2', 1000, 1]], 1000, [], null, [], [], false, 'IN_PROGRESS', null, 1000]], []], ['400104', '2024-01-04T10:00', 4000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['eMAG', 'UNKNOWN', [['P3', 1000, 1]], 1000, [], null, [], [], false, 'UNKNOWN', null, 1000]], []], ['400105', '2024-01-05T10:00', 3000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['Alfa SRL', 'CANCELLED', [['P4', 1000, 1]], 0, [], null, [], [], false, 'CANCELLED', null, 1000]], []], ['400106', '2024-01-06T10:00', 4000, [['eMAG Asigurari', 'PAID_ONLY', [['Asigurare Test', 3000, 1]], 3000, [], null, [], [], false, 'PAID_ONLY', null, 3000], ['eMAG', 'DELIVERED', [['P5', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []]],
    retururi: [['3000990', ['400106'], ['P5'], true, false, 1000, 'Vreau banii inapoi', ['Cerere inregistrata', 'Restituire suma']]],
    asteptat: {
      orders: { total: 6, kept_all: 1, kept_partial: 0, returned_all: 1, cancelled_all: 1, in_progress: 1, paid_only: 1, unknown: 1, no_items: 0 },
    },
  },
  {
    nume: 'o singură comandă datată: prima și ultima comandă sunt aceeași',
    comenzi: [['400201', '2024-03-03T09:30', 1000, [['eMAG', 'DELIVERED', [['Produs Unic', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000]], []], ['400202', null, 500, [['eMAG', 'DELIVERED', [['Produs Fara Data', 500, 1]], 500, [], null, [], [], false, 'DELIVERED', null, 500]], []]],
    retururi: [],
    asteptat: {
      meta: { generated_at: '2026-10-14 12:00', threshold_bani: 50000, first_order: '2024-03-03', last_order: '2024-03-03', orders: 2, blocks: 2, lines: 2 },
    },
  },
  {
    nume: 'avertismente: un singur bloc fără sumă între altele cu sumă afișată',
    comenzi: [['350004', '2024-07-04T10:00', 1000, [['Alfa', 'DELIVERED', [['P8', 1000, 1]], 1000, [], null, [], [], false, 'DELIVERED', null, 1000], ['Alfa', 'IN_PROGRESS', [['P9', 1000, 1]], null, [], null, [], [], false, 'IN_PROGRESS', null, 1000]], ["comanda 350004, Alfa: lipsește 'Total platit'"]]],
    retururi: [],
    asteptat: {
      warnings_detail: [{ kind: 'missing_paid_total', title: 'Comenzi la care lipsește „Total plătit”', explanation: 'Pagina comenzii nu arată suma plătită pentru un vânzător, deși produsele au fost livrate, ridicate sau sunt în curs. La un bloc livrat sau ridicat, suma plătită se calculează atunci din componente (produse, reduceri, transport și taxe) și intră așa în „cât ai cheltuit”; programul nu o poate verifica cu pagina.', affects_totals: false, what_to_do: 'Deschide comanda pe eMAG și compară-o cu „Total plătit” de acolo. De obicei suma din componente e exactă; poate diferi doar dacă pagina are o reducere sau o taxă pe care programul nu o recunoaște.', count: 1, items: [{ order_ids: ['350004'], return_id: null, seller: 'Alfa', status: 'în curs, încă nelivrat', placed_at: '2024-07-04', text: 'Alfa: blocul nu afișează „Total plătit” (în curs, încă nelivrat)', return_url: null }] }, { kind: 'other', title: 'Alte avertismente', explanation: 'Mesaje care nu intră în celelalte grupe: o sumă care nu se potrivește, un status necunoscut, produse fără categorie sau o greșeală de configurare. Grupa e marcată ca „afectează totalurile” doar dacă vreun mesaj din ea spune că o cifră din raport poate fi greșită.', affects_totals: false, what_to_do: 'Citește fiecare rând. Dacă numește o comandă, deschide-o pe eMAG și compară-o cu ce arată raportul; dacă vorbește de categorii, adaugă regula în config/categorii.personal.json, fișierul tău, pe care actualizarea îl păstrează.', count: 1, items: [{ order_ids: [], return_id: null, seller: null, status: null, placed_at: null, text: '2 produse necategorizate (adaugă reguli în config/categorii.personal.json)', return_url: null }] }],
    },
  },
  {
    nume: 'categorii: un produs de exact un ban păstrat intră în graficele pe ani',
    comenzi: [['380101', '2024-10-01T10:00', 1, [['eMAG', 'DELIVERED', [['Produs alfa', 1, 1]], 1, [], null, [], [], false, 'DELIVERED', null, 1]], []], ['380102', '2024-10-02T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs beta', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []]],
    retururi: [],
    reguli: { categories: [{ name: 'Alfa', patterns: ['alfa'] }, { name: 'Beta', patterns: ['beta'] }] },
    asteptat: {
      by_year_category: { years: ['2024'], series: ['Beta', 'Alfa'], values: { '2024': { Beta: 5000, Alfa: 1 } } },
      paid: { spent_bani: 5001, spent_units: 2, list_kept_bani: 5001, discounts_kept_bani: 0, products_kept_bani: 5001, fees_bani: 0, credit_returns_bani: 0, credit_returns_units: 0, refund_differences_bani: 0, extra_rows: [], funnel: { ordered_bani: 5001, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 5001, ordered_units: 2, cancelled_units: 0, returned_units: 0, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 2 }, reconciliation: { paid_delivered_bani: 5001, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 5001, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 }, by_year_category: { years: ['2024'], series: ['Beta', 'Alfa'], values: { '2024': { Beta: 5000, Alfa: 1 } } } },
    },
  },
];
const LONG_LIST_HIGHLIGHT = { items_total: 85, items: 80, ultimul: 'Whisky Test 079' };
const LONG_LIST_UNCATEGORIZED = { uncategorized_count: 45, uncategorized: 40, primul: 'Produs Necunoscut 044', ultimul: 'Produs Necunoscut 005' };
const CRAFTED_LINES_EXPECTED = { spent_bani: 0, warnings: ['lanțul sumelor plătite nu se închide (comandat − scăzute + transport și taxe): 50,00 Lei ≠ părți 0,00 Lei', 'lanțul sumelor plătite nu se închide (blocuri livrate − bani primiți înapoi): 50,00 Lei ≠ părți 0,00 Lei'], funnel: { ordered_bani: 5000, cancelled_bani: 0, returned_bani: 0, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 0, ordered_units: 1, cancelled_units: 0, returned_units: 1, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 5000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 0, estimated_refunds_bani: 0, estimated_refunds: 0, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 0, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 } };
const CRAFTED_UNKNOWN_RETURN_EXPECTED = { spent_bani: 0, warnings: [], funnel: { ordered_bani: 5000, cancelled_bani: 0, returned_bani: 5000, pending_bani: 0, unknown_bani: 0, fees_bani: 0, spent_bani: 0, ordered_units: 1, cancelled_units: 0, returned_units: 1, credit_units: 0, pending_units: 0, unknown_units: 0, spent_units: 0 }, reconciliation: { paid_delivered_bani: 5000, rebuilt_blocks: 0, rebuilt_bani: 0, cash_refunds_bani: 5000, estimated_refunds_bani: 5000, estimated_refunds: 1, credit_returns_delivered_bani: 0, credit_returns_added_bani: 0, refund_differences_bani: 0, spent_bani: 0, in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0, cancelled_cash_returns_bani: 0, cancelled_cash_refunds_shown_bani: 0, unattributed_refunds_bani: 0 } };
const HEADER_UNKNOWN_ORDER_EXPECTED = [{ kind: 'header_total_mismatch', title: 'Comenzi la care totalul din antet nu e egal cu suma blocurilor', explanation: 'Totalul scris în partea de sus a comenzii diferă de suma sumelor plătite ale vânzătorilor din ea. Cauza cea mai frecventă: comanda are un bloc anulat, iar antetul include încă „Total de plată” al acelui bloc (atunci nu e o problemă). Alte cauze posibile: o reducere sau o taxă pe care programul nu a recunoscut-o, un bloc fără „Total plătit” sau o comandă modificată după plasare.', affects_totals: false, what_to_do: 'La comenzile fără bloc anulat, deschide comanda pe eMAG și verifică totalul. „Cât ai cheltuit” se calculează din „Total plătit” al fiecărui bloc, nu din antet; diferența afectează doar această verificare.', count: 1, items: [{ order_ids: ['555'], return_id: null, seller: null, status: null, placed_at: null, text: 'total din antet 10,00 Lei, suma blocurilor 5,00 Lei', return_url: null }] }];


/** SellerBlock din tuplul compact al unui bloc (vezi mai sus). */
function blockFromTuple([seller, status, items, paid, vouchers, shipping, services, other, storno, statusText, due, productsTotal]) {
  return makeSellerBlock({
    seller, status, status_text: statusText, has_storno: storno, items: items.map(([name, total, qty]) => makeItem(name, total, qty)), products_total_bani: productsTotal, vouchers_bani: vouchers,
    shipping_bani: shipping, services_bani: services, other_bani: other, paid_bani: paid, due_bani: due,
  });
}

/** Order din tuplul compact al unei comenzi; textul datei e data ISO cu spațiu în loc de „T” (gol dacă lipsește), ca la Order din generator. */
function orderFromTuple([orderId, placedAt, header, blocks, warnings]) {
  return makeOrder({ order_id: orderId, placed_text: placedAt === null ? '' : placedAt.replace('T', ' '), placed_at: placedAt, header_total_bani: header, blocks: blocks.map(blockFromTuple), warnings });
}

/** ReturnRequest din tuplul compact al unui retur; calea paginii e cea a generatorului (/user/return-history/1/<număr>). */
function returnFromTuple([returnId, orderIds, productNames, completed, cancelled, refund, mode, steps]) {
  return makeReturnRequest({
    return_id: returnId, detail_path: `/user/return-history/1/${returnId}`, order_ids: orderIds, product_names: productNames, steps, refund_bani: refund, refund_mode: mode, completed, cancelled,
  });
}

/** Rezumatul lui analyze() pe intrările compacte, cu configurările din config/ și ora fixă a scenariilor. */
function analyzeTuples(orderTuples, returnTuples, rules, thresholdBani, highlightCategories = [], warningTexts = WARNING_TEXTS) {
  return analyze(orderTuples.map(orderFromTuple), returnTuples.map(returnFromTuple), new Classifier(rules, 'reguli'), thresholdBani, '2026-10-14 12:00', {
    highlightCategories, warningTexts, colorWords: COLOR_WORDS, refundModes: REFUND_MODES,
  }).summary;
}

describe('scenarii mici, cu cheile rezumatului date de Python', () => {
  for (const scenario of HAND_SCENARIOS) {
    test(scenario.nume, () => {
      const texts = scenario.etichete === undefined ? WARNING_TEXTS : { ...structuredClone(WARNING_TEXTS), etichete_status: scenario.etichete };
      const summary = analyzeTuples(scenario.comenzi, scenario.retururi, scenario.reguli ?? { categories: [] }, scenario.prag ?? 50000, scenario.evidentiate ?? [], texts);
      for (const [key, expected] of Object.entries(scenario.asteptat)) assertIdentical(summary[key], expected, key);
    });
  }

  test('listele lungi se taie la limită: 85 de produse evidențiate dau 80 de rânduri, 45 de necategorizate dau 40', () => {
    const simple = (id, name, total) => [id, '2024-01-01T10:00', total, [['eMAG', 'DELIVERED', [[name, total, 1]], total, [], null, [], [], false, 'DELIVERED', null, total]], []];
    const whisky = Array.from({ length: 85 }, (_, index) => simple(String(800000 + index), `Whisky Test ${String(index).padStart(3, '0')}`, 1000 + index));
    const highlighted = analyzeTuples(whisky, [], { categories: [{ name: 'Alcool', patterns: ['whisky'] }] }, 50000, ['Alcool']).highlights.Alcool;
    assert.deepEqual({ items_total: highlighted.items_total, items: highlighted.items.length, ultimul: highlighted.items.at(-1).name }, LONG_LIST_HIGHLIGHT);
    const unknown = Array.from({ length: 45 }, (_, index) => simple(String(810000 + index), `Produs Necunoscut ${String(index).padStart(3, '0')}`, 1000 + index));
    const summary = analyzeTuples(unknown, [], { categories: [] }, 50000);
    assert.deepEqual({ uncategorized_count: summary.uncategorized_count, uncategorized: summary.uncategorized.length, primul: summary.uncategorized[0].name, ultimul: summary.uncategorized.at(-1).name },
      LONG_LIST_UNCATEGORIZED);
  });

  test('linii construite de mână, cu o bucată returnată fără număr de retur: lanțul sumelor nu se închide, cu aceleași avertismente ca în Python', () => {
    const orders = [orderFromTuple(['900001', '2024-07-01T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs Fals', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []])];
    const lines = buildLines(orders);
    lines[0].kept_qty = 0;
    lines[0].returned_qty = 1;
    const totals = computePaidTotals(orders, lines, [], new ReturnMatchReport(), REFUND_MODES);
    assertIdentical({ spent_bani: totals.summary.spent_bani, warnings: totals.warnings, funnel: totals.summary.funnel, reconciliation: totals.summary.reconciliation }, CRAFTED_LINES_EXPECTED, 'paid');
  });

  test('o bucată returnată cu un număr de retur care lipsește din lista de retururi: nu e credit, nu are sumă afișată, ca în Python', () => {
    const orders = [orderFromTuple(['900001', '2024-07-01T10:00', 5000, [['eMAG', 'DELIVERED', [['Produs Fals', 5000, 1]], 5000, [], null, [], [], false, 'DELIVERED', null, 5000]], []])];
    const lines = buildLines(orders);
    lines[0].kept_qty = 0;
    lines[0].returned_qty = 1;
    lines[0].return_ids = ['999'];
    const totals = computePaidTotals(orders, lines, [], new ReturnMatchReport(), REFUND_MODES);
    assertIdentical({ spent_bani: totals.summary.spent_bani, warnings: totals.warnings, funnel: totals.summary.funnel, reconciliation: totals.summary.reconciliation }, CRAFTED_UNKNOWN_RETURN_EXPECTED, 'paid');
  });

  test('buildWarningsDetail: o comandă din lista de antete care nu e în lista de comenzi apare fără dată', () => {
    const groups = buildWarningsDetail([], [], [], [{ order_id: '555', header_bani: 1000, blocks_bani: 500 }], WARNING_TEXTS);
    assertIdentical(groups, HEADER_UNKNOWN_ORDER_EXPECTED, 'warnings_detail');
  });
});

// ---------- plainSummary: copia fără PyFloat, pentru chrome.storage și dashboard.js ----------

/** True dacă undeva în arbore a rămas un PyFloat (obiect care nu se salvează ca număr și pe care dashboard.js îl refuză). */
function containsPyFloat(value) {
  if (value instanceof PyFloat) return true;
  if (Array.isArray(value)) return value.some(containsPyFloat);
  return value !== null && typeof value === 'object' && Object.values(value).some(containsPyFloat);
}

describe('plainSummary: rezumatul cu numere simple', () => {
  // aceeași fixtură, citită fără marcarea floaturilor: JSON.parse dă numere simple (inclusiv zero cu semn la „-0.0”)
  const plainScenarios = JSON.parse(readFileSync(path.join(FIXTURES_DIR, 'analiza.json'), 'utf8')).scenarii;

  for (const [index, scenario] of fixture.scenarii.entries()) {
    test(`${scenario.nume}: egal cu rezumatul din fixtură citit ca JSON simplu, fără niciun PyFloat`, () => {
      const { summary } = runScenario(scenario).result;
      const plain = plainSummary(summary);
      assert.deepStrictEqual(plain, plainScenarios[index].rezumat);
      assert.equal(containsPyFloat(plain), false);
      assert.equal(JSON.stringify(plain), JSON.stringify(plainScenarios[index].rezumat), 'și ca text JSON');
    });
  }

  test('rezumatul original rămâne cu PyFloat (raportul și analiza.json le scriu ca în Python), iar copia nu împarte obiecte cu el', () => {
    const scenario = fixture.scenarii.find((candidate) => candidate.nume === 'capcane_preturi');
    const { summary } = runScenario(scenario).result;
    const plain = plainSummary(summary);
    assert.equal(containsPyFloat(summary), true);
    assert.notEqual(plain.price_history, summary.price_history);
    assert.notEqual(plain.price_history.products[0], summary.price_history.products[0]);
    assert.ok(summary.price_history.products[0].last_vs_prev_pct instanceof PyFloat);
    assert.equal(typeof plain.price_history.products[0].last_vs_prev_pct, 'number');
  });

  test('dashboard.js: rezumatul simplu trece de EmagDashboard.validate, cel cu PyFloat e refuzat la procentul din istoricul prețurilor', () => {
    const sandbox = { window: {}, console };
    vm.runInNewContext(readFileSync(DASHBOARD_FILE, 'utf8'), sandbox);
    const { validate } = sandbox.window.EmagDashboard;
    let refused = 0;
    for (const scenario of fixture.scenarii) {
      const { summary } = runScenario(scenario).result;
      const accepted = validate(plainSummary(summary));
      // rezultatul vine dintr-un alt context V8 (vm): se verifică câmpurile, nu identitatea obiectelor
      assert.equal(accepted.ok, true, `${scenario.nume}: ${accepted.errors.join(' / ')}`);
      assert.equal(accepted.errors.length, 0, scenario.nume);
      const raw = validate(summary);
      if (summary.price_history.products.length > 0) {
        refused += 1;
        assert.equal(raw.ok, false, `${scenario.nume}: dashboard.js ar fi trebuit să refuze PyFloat`);
        assert.match(raw.errors[0], /last_vs_prev_pct/);
      } else {
        assert.equal(raw.ok, true, scenario.nume);
      }
    }
    assert.ok(refused >= 3, `doar ${refused} scenarii cu istoric al prețurilor: testul nu dovedește destul`);
  });

  test('valorile simple trec neschimbate: null, text, întreg, zero cu semn, liste și obiecte goale', () => {
    assert.equal(plainSummary(null), null);
    assert.equal(plainSummary('text'), 'text');
    assert.equal(plainSummary(5), 5);
    assert.ok(Object.is(plainSummary(new PyFloat(-0)), -0));
    assert.deepStrictEqual(plainSummary({ a: [], b: {}, c: [new PyFloat(5), { d: new PyFloat(1.5) }] }), { a: [], b: {}, c: [5, { d: 1.5 }] });
  });
});


// ---------- classify() pe corpusul din regex.json (scris de generator): aici, nu în classifier.test.js, fiindcă depinde de fixturi generate ----------

// Fișierul din regex.json la care se raportează corpusul: regulile publice ale programului.
const REPO_RULES_FILE_NAME = 'categorii.json';
// Câte texte din corpus (10142) trebuie comparate cel puțin, și câte dintre ele cu o categorie: sub aceste praguri testul ar trece fără să dovedească nimic (azi: 8671 și 2222).
const MIN_COMPARED_CORPUS_TEXTS = 8000;
const MIN_CATEGORIZED_CORPUS_TEXTS = 2000;

describe('classify() pe corpusul din regex.json: categoria și modelul urmează rezultatele lui re.search din Python', () => {
  const fixture = loadFixture('regex');
  const rules = fixture.modele.filter((model) => model.fisier === REPO_RULES_FILE_NAME);

  /** Categoria și modelul așteptate pentru textul de la indicele `index`, din potrivirile înregistrate de Python pentru fiecare model, în ordinea fișierului. */
  function expectedFor(index) {
    const order = [...new Set(rules.map((model) => model.categorie))];
    for (const category of order) {
      const own = rules.filter((model) => model.categorie === category);
      const matched = own.find((model) => model.tip === 'patterns' && model.potriviri.includes(index));
      if (matched && !own.some((model) => model.tip === 'exclude' && model.potriviri.includes(index))) return [category, matched.model];
    }
    return ['Necategorizat', ''];
  }

  test('fiecare text din corpus al cărui text normalizat e tot în corpus (Python a căutat modelele exact în acela)', (t) => {
    const classifier = new Classifier(readConfig(REPO_RULES_FILE_NAME), REPO_RULES_FILE_NAME);
    const indexOf = new Map(fixture.corpus.map((text, index) => [text, index]));
    let compared = 0;
    let categorized = 0;
    fixture.corpus.forEach((text, index) => {
      // classify() normalizează întâi numele, iar Python a înregistrat potrivirile doar pe textele din corpus: se compară textele a căror formă normalizată e în corpus
      const normalizedIndex = indexOf.get(normalizeText(text));
      if (normalizedIndex === undefined) return;
      const expected = expectedFor(normalizedIndex);
      assert.deepEqual(classifier.classify(text), expected, `corpus[${index}] = ${JSON.stringify(text)}`);
      compared += 1;
      if (expected[0] !== 'Necategorizat') categorized += 1;
    });
    t.diagnostic(`${compared} texte comparate din ${fixture.corpus.length}, ${categorized} cu categorie`);
    assert.ok(compared >= MIN_COMPARED_CORPUS_TEXTS, `doar ${compared} texte comparate din ${fixture.corpus.length}`);
    assert.ok(categorized >= MIN_CATEGORIZED_CORPUS_TEXTS, `doar ${categorized} texte cu categorie: testul nu dovedește destul`);
  });
});
