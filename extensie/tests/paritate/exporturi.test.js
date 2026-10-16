// Paritatea exporturilor: produse.csv, istoric_preturi.csv și raportul HTML autonom, față de emag_spend/csv_export.py, price_history_csv.py și report_html.py.
// (1) Pentru fiecare scenariu din analiza.json: liniile de registru (cu sumele pe stări din fixtură) trec prin linesCsv, istoricul de prețuri prin priceHistoryCsv, iar la scenariul `scenariu`
//     rezumatul trece prin buildReport cu șablonul și designul de azi; se cere textul identic, octet cu octet (BOM la început, CRLF, ghilimele doar la nevoie, floaturile ca în Python).
// (2) Cazuri scrise de mână pentru ce fixturile nu acoperă (formule în celule, ghilimele, caractere Unicode, pragul, erorile și capcanele raportului); valorile așteptate sunt ieșirea
//     modulelor Python (3.13), rulate pe aceleași intrări la scrierea testului. Ce NU face: nu calculează liniile sau rezumatul (le dă fixtura; calculul e al lui spend_analysis).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { LineOutcome } from '../../src/calcul/models.js';
import { PyFloat } from '../../src/calcul/python_compat.js';
import { leiCell, linesCsv, textCell } from '../../src/exporturi/csv_export.js';
import { priceHistoryCsv } from '../../src/exporturi/price_history_csv.js';
import { buildReport } from '../../src/exporturi/report_html.js';
import { FIXTURES_DIR, loadFixture, same } from '../fixturi.js';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
// Sursele unice ale raportului (șablonul și designul rămân în afara extensiei și se copiază la build): aceleași fișiere pe care le citește generatorul de fixturi prin settings.py.
const REPORT_TEMPLATE_FILE = path.join(REPO_ROOT, 'templates', 'raport.html');
const DASHBOARD_CSS_FILE = path.join(REPO_ROOT, 'interfata', 'assets', 'dashboard.css');
const DASHBOARD_JS_FILE = path.join(REPO_ROOT, 'interfata', 'assets', 'dashboard.js');
// Scenariul al cărui raport e în fixtură (restul scenariilor nu au `raport_html`).
const REPORT_SCENARIO = 'scenariu';
// UTF-8 BOM (U+FEFF): Excel îl cere ca să citească diacriticele; se verifică pe octeți, nu doar ca text.
const UTF8_BOM_BYTES = Buffer.from([0xef, 0xbb, 0xbf]);
// Pragurile apără testul de a deveni inutil: o fixtură regenerată mai mică ar trece fără să dovedească nimic.
const MIN_SCENARIOS = 8;
const MIN_LINES_IN_BIGGEST_SCENARIO = 200;
const MIN_REPORT_BYTES = 100_000;

const scenarios = loadFixture('analiza').scenarii;
const show = (value) => JSON.stringify(value);
const bytes = (text) => Buffer.from(text, 'utf8');

/** True dacă `key` e o proprietate calculată a lui LineOutcome (getter), nu un câmp: fixtura le are pe amândouă, constructorul primește doar câmpurile. */
const isComputedProperty = (key) => typeof Object.getOwnPropertyDescriptor(LineOutcome.prototype, key)?.get === 'function';

/** LineOutcome-urile unui scenariu, reconstruite din fixtură; verifică și că proprietățile calculate ies la fel ca la Python (altfel CSV-ul ar fi comparat pe intrări greșite). */
function buildLines(entries, label) {
  return entries.map((entry, index) => {
    const line = new LineOutcome(Object.fromEntries(Object.entries(entry).filter(([key]) => !isComputedProperty(key))));
    for (const key of Object.keys(entry).filter(isComputedProperty)) same(line[key], entry[key], () => `${label}, linia ${index}: ${key}`);
    return line;
  });
}

/** Îngheață adânc o structură (liste, obiecte, Map-uri): buildReport și priceHistoryCsv nu au voie să-și modifice intrarea. */
function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const item of (value instanceof Map ? [...value.values()] : Object.values(value))) deepFreeze(item);
  }
  return value;
}

/** Rezumatul scenariului din textul brut al fixturii, cu numerele scrise cu punct sau exponent ca PyFloat: JSON.parse simplu pierde diferența dintre 5.0 și 5, iar Python scrie `5.0`. */
function summaryWithFloats(name) {
  const text = readFileSync(path.join(FIXTURES_DIR, 'analiza.json'), 'utf8');
  const parsed = JSON.parse(text, (key, value, context) => (typeof value === 'number' && /[.eE]/.test(context.source) ? new PyFloat(value) : value));
  return parsed.scenarii.find((scenario) => scenario.nume === name).rezumat;
}

describe('fixtura analiza.json: ce are nevoie testul', () => {
  test('are scenariile și liniile de care depinde paritatea exporturilor', () => {
    assert.ok(scenarios.length >= MIN_SCENARIOS, `doar ${scenarios.length} scenarii`);
    assert.ok(Math.max(...scenarios.map((scenario) => scenario.linii.length)) >= MIN_LINES_IN_BIGGEST_SCENARIO, 'niciun scenariu nu are destule linii');
    assert.ok(scenarios.some((scenario) => scenario.nume === REPORT_SCENARIO && scenario.raport_html.length >= MIN_REPORT_BYTES), `scenariul ${REPORT_SCENARIO} nu are raportul`);
  });
});

describe('produse.csv: linesCsv față de write_lines_csv', () => {
  for (const scenario of scenarios) {
    test(`${scenario.nume}: ${scenario.linii.length} linii`, () => {
      const lines = buildLines(scenario.linii, scenario.nume);
      const text = linesCsv(lines, scenario.prag_bani);
      same(text, scenario.linii_csv, () => `produse.csv, scenariul ${scenario.nume}`);
      assert.ok(bytes(text).subarray(0, UTF8_BOM_BYTES.length).equals(UTF8_BOM_BYTES), 'primii trei octeți sunt BOM-ul UTF-8');
      assert.ok(bytes(text).equals(bytes(scenario.linii_csv)), 'aceiași octeți UTF-8');
      assert.ok(text.endsWith('\r\n'), 'fiecare rând se încheie cu CRLF');
    });
  }
  test('nu modifică liniile primite și nu depinde de apelurile dinainte', () => {
    const scenario = scenarios.find((entry) => entry.linii.length > 0);
    const lines = buildLines(scenario.linii, scenario.nume);
    const before = lines.map((line) => line.toDict());
    const first = linesCsv(lines, scenario.prag_bani);
    same(lines.map((line) => line.toDict()), before, () => 'liniile după linesCsv');
    same(linesCsv(lines, scenario.prag_bani), first, () => 'al doilea apel');
  });
});

describe('istoric_preturi.csv: priceHistoryCsv față de write_price_history_csv', () => {
  for (const scenario of scenarios) {
    test(`${scenario.nume}: ${scenario.rezumat.price_history.products.length} produse repetate`, () => {
      const history = deepFreeze(structuredClone(scenario.rezumat.price_history));
      const text = priceHistoryCsv(history);
      same(text, scenario.istoric_csv, () => `istoric_preturi.csv, scenariul ${scenario.nume}`);
      assert.ok(bytes(text).subarray(0, UTF8_BOM_BYTES.length).equals(UTF8_BOM_BYTES), 'primii trei octeți sunt BOM-ul UTF-8');
    });
  }
});

describe('raport.html: buildReport față de write_report', () => {
  const template = readFileSync(REPORT_TEMPLATE_FILE, 'utf8');
  const css = readFileSync(DASHBOARD_CSS_FILE, 'utf8');
  const js = readFileSync(DASHBOARD_JS_FILE, 'utf8');
  test('raportul scenariului din fixtură, cu șablonul și designul de azi, octet cu octet', () => {
    const summary = deepFreeze(summaryWithFloats(REPORT_SCENARIO));
    const expected = scenarios.find((scenario) => scenario.nume === REPORT_SCENARIO).raport_html;
    const report = buildReport(template, css, js, summary);
    assert.equal(report.length, expected.length, 'aceeași lungime');
    same(report, expected, () => 'raport.html');
    assert.ok(bytes(report).equals(bytes(expected)), 'aceiași octeți UTF-8');
    assert.ok(!report.includes('\r'), 'sfârșituri de rând LF, ca în Python');
  });
  test('fișierele surse nu au CR (fixtura a fost scrisă cu citire în mod text; buildReport normalizează oricum)', () => {
    for (const [name, text] of [['șablon', template], ['dashboard.css', css], ['dashboard.js', js]]) assert.ok(!text.includes('\r'), `${name} are CR`);
  });
});

// ---------------------------------------------------------------------------------------------------------------------------------------------------------------
// Cazuri scrise de mână. Valorile așteptate vin din modulele Python (csv_export.text_cell / lei_cell / write_lines_csv, price_history_csv, report_html.write_report).
// ---------------------------------------------------------------------------------------------------------------------------------------------------------------

// text_cell(in): apostrof în față dacă textul (sau ce rămâne după lstrip-ul Python) începe cu = + - @ TAB CR. U+0085, U+001C-U+001F, U+2028 și U+3000 sunt spații pentru Python (lstrip le scoate),
// U+FEFF și U+200B nu sunt: acolo nu se pune apostrof, ca în Python.
const TEXT_CELL_CASES = [
  { in: '', out: '' },
  { in: 'abc', out: 'abc' },
  { in: '=1+1', out: '\'=1+1' },
  { in: '+1', out: '\'+1' },
  { in: '-1', out: '\'-1' },
  { in: '-12,00', out: '\'-12,00' },
  { in: '@SUM(A1)', out: '\'@SUM(A1)' },
  { in: '\t=x', out: '\'\t=x' },
  { in: '\r=x', out: '\'\r=x' },
  { in: '\n=x', out: '\'\n=x' },
  { in: ' =x', out: '\' =x' },
  { in: '  \t=x', out: '\'  \t=x' },
  { in: '\u{a0}=x', out: '\'\u{a0}=x' },
  { in: '\u{85}=x', out: '\'\u{85}=x' },
  { in: '\u{1c}=x', out: '\'\u{1c}=x' },
  { in: '\u{1f}+x', out: '\'\u{1f}+x' },
  { in: '\u{feff}=x', out: '\u{feff}=x' },
  { in: '\u{200b}=x', out: '\u{200b}=x' },
  { in: '\u{2028}=x', out: '\'\u{2028}=x' },
  { in: 'a=b', out: 'a=b' },
  { in: 'a +b', out: 'a +b' },
  { in: ' ', out: ' ' },
  { in: '\t', out: '\'\t' },
  { in: '\'=x', out: '\'=x' },
  { in: '=', out: '\'=' },
  { in: '-', out: '\'-' },
  { in: 'x\t=', out: 'x\t=' },
  { in: '\u{1f600}=x', out: '\u{1f600}=x' },
  { in: '\u{3000}-x', out: '\'\u{3000}-x' },
  { in: '\u{1680}@x', out: '\'\u{1680}@x' },
  { in: '\u{2003}+x', out: '\'\u{2003}+x' },
  { in: '\rabc', out: '\'\rabc' }, // TAB și CR de la început sunt formulă prin ele însele, fără caracter de formulă după ele
  { in: '\tabc', out: '\'\tabc' },
];

// lei_cell(in): suma în lei cu virgulă, fără separator de mii; minus în față pentru sume negative (-5 bani -> -0,05).
const LEI_CELL_CASES = [
  { in: 0, out: '0,00' },
  { in: 1, out: '0,01' },
  { in: 5, out: '0,05' },
  { in: 99, out: '0,99' },
  { in: 100, out: '1,00' },
  { in: 101, out: '1,01' },
  { in: 144927, out: '1449,27' },
  { in: -1, out: '-0,01' },
  { in: -5, out: '-0,05' },
  { in: -99, out: '-0,99' },
  { in: -100, out: '-1,00' },
  { in: -3400, out: '-34,00' },
  { in: -144927, out: '-1449,27' },
  { in: 123456789012, out: '1234567890,12' },
  { in: -123456789012, out: '-1234567890,12' },
  { in: 9007199254740991, out: '90071992547409,91' },
  { in: 100000, out: '1000,00' },
];

describe('textCell și leiCell față de text_cell și lei_cell', () => {
  test(`textCell: ${TEXT_CELL_CASES.length} cazuri`, () => {
    for (const c of TEXT_CELL_CASES) same(textCell(c.in), c.out, () => `text_cell(${show(c.in)})`);
  });
  test(`leiCell: ${LEI_CELL_CASES.length} cazuri`, () => {
    for (const c of LEI_CELL_CASES) same(leiCell(c.in), c.out, () => `lei_cell(${c.in})`);
  });
  test('leiCell refuză ce nu e un număr întreg de bani (Python ar scrie altceva sau ar ridica o eroare)', () => {
    for (const bad of [1.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 53]) assert.throws(() => leiCell(bad), RangeError, String(bad));
  });
});

// Linia de bază a capcanelor: câmpurile LineOutcome în ordinea din Python; fiecare capcană schimbă doar ce o interesează.
const trapLine = (overrides) => new LineOutcome({
  order_id: '489000001', placed_at: '2026-05-26T10:07', seller: 'eMAG', name: 'Produs', qty: 1, line_total_bani: 10000, block_status: 'DELIVERED',
  kept_qty: 0, returned_qty: 0, cancelled_qty: 0, pending_qty: 0, paid_only_qty: 0, unknown_qty: 0, returned_from_cancelled_qty: 0,
  category: '', rule: '', return_ids: [], paid_total_bani: null, credit_returned_qty: 0, ...overrides,
});
const THRESHOLD_BANI = 50000;
const makeLineTraps = () => [
  trapLine({ seller: '=HYPERLINK("http://x")', name: '@SUM(A1;A2)', qty: 2, line_total_bani: 100001, kept_qty: 1, returned_qty: 1, category: '+Categorie', rule: '-regula', return_ids: ['3000001'], paid_total_bani: 90001 }),
  trapLine({ order_id: 'ab', placed_at: null, seller: ' =x', name: 'Produs "cu ghilimele"\nși rând nou', line_total_bani: 5000, block_status: 'CANCELLED', cancelled_qty: 1 }),
  trapLine({ order_id: '489000002', placed_at: '2024-01-05T10:00', seller: 'ALFA;SRL', name: '\t=tab', qty: 0, line_total_bani: -2500, category: 'Transport și taxe', rule: 'x' }),
  trapLine({ order_id: '489000003', qty: 3, line_total_bani: 150000, kept_qty: 3, name: 'exact pe prag' }),
  trapLine({ order_id: '489000004', qty: 3, line_total_bani: 150001, kept_qty: 3, name: 'peste prag cu un ban', return_ids: ['3000001', '3000002', '3000003'] }),
  trapLine({ order_id: '489000005', name: '\r=cr', seller: '\u{85}=nel', kept_qty: 1 }),
  trapLine({ order_id: '489000006', name: '\u{feff}=bom', seller: 'Vânzător \u{1f600} \u{df} ș ț', kept_qty: 1 }),
  trapLine({ order_id: '489000007', placed_at: 'x', name: 'data scurtă', pending_qty: 1, block_status: 'IN_PROGRESS' }),
  trapLine({ order_id: '489000008', placed_at: '', name: 'fără dată', unknown_qty: 1, block_status: 'UNKNOWN' }),
  trapLine({ order_id: '48900000\u{669}', name: 'cifră Unicode în număr', kept_qty: 1 }),
  trapLine({ order_id: '1234567890123456', name: 'număr prea lung', kept_qty: 1 }),
  trapLine({ order_id: '489000009', qty: 5, line_total_bani: 9999, kept_qty: 2, returned_qty: 1, cancelled_qty: 1, pending_qty: 1, return_ids: ['3000009'], paid_total_bani: 8888, credit_returned_qty: 1, name: 'stări amestecate' }),
  trapLine({ order_id: '489000010', qty: 1, line_total_bani: 50000, kept_qty: 1, name: 'exact pe prag, unitar' }),
  trapLine({ order_id: '489000011', qty: 1, line_total_bani: 50001, kept_qty: 1, name: 'peste prag, unitar' }),
  trapLine({ order_id: '489000012', qty: 2, line_total_bani: -100000, kept_qty: 2, name: 'Custom Discount mare' }),
  trapLine({ order_id: '489000013', kept_qty: 1, block_status: '=STATUS', return_ids: ['=1', '@2'], name: 'status si retururi cu formule' }),
];
// Rândurile produse.csv (fără CRLF-ul de la capăt), scrise de write_lines_csv pe capcanele de mai sus.
const LINES_CSV_ROWS = [
  '\u{feff}comanda;link_comanda;data;an;vanzator;produs;categorie;regula_categorie;cantitate;valoare_linie_lei;platit_linie_lei;pastrat_lei;platit_pastrat_lei;returnat_lei;anulat_lei;in_curs_lei;bucati_pastrate;bucati_returnate;bucati_anulate;bucati_in_curs;status_bloc;retur_id;peste_prag',
  '489000001;https://www.emag.ro/history/shoppingdetails/489000001;2026-05-26;2026;"\'=HYPERLINK(""http://x"")";"\'@SUM(A1;A2)";\'+Categorie;\'-regula;2;1000,01;900,01;500,00;450,00;500,01;0,00;0,00;1;1;0;0;DELIVERED;3000001;da',
  'ab;;;;\' =x;"Produs ""cu ghilimele""\nși rând nou";;;1;50,00;50,00;0,00;0,00;0,00;50,00;0,00;0;0;1;0;CANCELLED;;',
  '489000002;https://www.emag.ro/history/shoppingdetails/489000002;2024-01-05;2024;"ALFA;SRL";\'\t=tab;Transport și taxe;x;0;-25,00;0,00;-25,00;0,00;0,00;0,00;0,00;0;0;0;0;DELIVERED;;',
  '489000003;https://www.emag.ro/history/shoppingdetails/489000003;2026-05-26;2026;eMAG;exact pe prag;;;3;1500,00;1500,00;1500,00;1500,00;0,00;0,00;0,00;3;0;0;0;DELIVERED;;',
  '489000004;https://www.emag.ro/history/shoppingdetails/489000004;2026-05-26;2026;eMAG;peste prag cu un ban;;;3;1500,01;1500,01;1500,01;1500,01;0,00;0,00;0,00;3;0;0;0;DELIVERED;3000001,3000002,3000003;da',
  '489000005;https://www.emag.ro/history/shoppingdetails/489000005;2026-05-26;2026;\'\u{85}=nel;"\'\r=cr";;;1;100,00;100,00;100,00;100,00;0,00;0,00;0,00;1;0;0;0;DELIVERED;;',
  '489000006;https://www.emag.ro/history/shoppingdetails/489000006;2026-05-26;2026;Vânzător \u{1f600} \u{df} ș ț;\u{feff}=bom;;;1;100,00;100,00;100,00;100,00;0,00;0,00;0,00;1;0;0;0;DELIVERED;;',
  '489000007;https://www.emag.ro/history/shoppingdetails/489000007;x;x;eMAG;data scurtă;;;1;100,00;100,00;0,00;0,00;0,00;0,00;100,00;0;0;0;1;IN_PROGRESS;;',
  '489000008;https://www.emag.ro/history/shoppingdetails/489000008;;;eMAG;fără dată;;;1;100,00;100,00;0,00;0,00;0,00;0,00;0,00;0;0;0;0;UNKNOWN;;',
  '48900000\u{669};;2026-05-26;2026;eMAG;cifră Unicode în număr;;;1;100,00;100,00;100,00;100,00;0,00;0,00;0,00;1;0;0;0;DELIVERED;;',
  '1234567890123456;;2026-05-26;2026;eMAG;număr prea lung;;;1;100,00;100,00;100,00;100,00;0,00;0,00;0,00;1;0;0;0;DELIVERED;;',
  '489000009;https://www.emag.ro/history/shoppingdetails/489000009;2026-05-26;2026;eMAG;stări amestecate;;;5;99,99;88,88;39,99;35,54;20,00;20,00;20,00;2;1;1;1;DELIVERED;3000009;',
  '489000010;https://www.emag.ro/history/shoppingdetails/489000010;2026-05-26;2026;eMAG;exact pe prag, unitar;;;1;500,00;500,00;500,00;500,00;0,00;0,00;0,00;1;0;0;0;DELIVERED;;',
  '489000011;https://www.emag.ro/history/shoppingdetails/489000011;2026-05-26;2026;eMAG;peste prag, unitar;;;1;500,01;500,01;500,01;500,01;0,00;0,00;0,00;1;0;0;0;DELIVERED;;da',
  '489000012;https://www.emag.ro/history/shoppingdetails/489000012;2026-05-26;2026;eMAG;Custom Discount mare;;;2;-1000,00;0,00;-1000,00;0,00;0,00;0,00;0,00;2;0;0;0;DELIVERED;;',
  '489000013;https://www.emag.ro/history/shoppingdetails/489000013;2026-05-26;2026;eMAG;status si retururi cu formule;;;1;100,00;100,00;100,00;100,00;0,00;0,00;0,00;1;0;0;0;\'=STATUS;\'=1,@2;',
  '',
];

// Istoricul de prețuri de capcană: formule, ghilimele, dată lipsă sau goală, un produs fără cumpărări, un preț sub minim (diferență negativă) și caractere Unicode.
const makeHistoryTrap = () => ({
  products: [
    {
      name: '=Produs 1', category: '+cat', min_unit_bani: 10000, color_variants: true, purchases: [
        { date: '2026-05-26', order_id: '489000001', seller: 'eMAG', name: 'Nume ; cu punct-virgula', qty: 2, unit_bani: 12500 },
        { date: null, order_id: 'ab', seller: '@x', name: 'cu "ghilimele"', qty: 1, unit_bani: 10000 },
        { date: '', order_id: '489000002', seller: ' -y', name: '\t=z', qty: 3, unit_bani: 10001 },
      ],
    },
    { name: 'Fără cumpărări', category: '', purchases: [], min_unit_bani: 0, color_variants: false },
    { name: 'Sub minim', category: 'Cat', min_unit_bani: 100, color_variants: false, purchases: [{ date: '2025-01-02', order_id: '100100', seller: 'S', name: 'n', qty: 3, unit_bani: 99 }] },
    {
      name: 'Cu emoji \u{1f600}\u{85}', category: 'Ț', min_unit_bani: 123456, color_variants: false,
      purchases: [{ date: '2025-01-03', order_id: '100200', seller: '\u{85}=s', name: '\u{feff}n', qty: 1, unit_bani: 123456 }],
    },
    { name: 'Comanda cu formula', category: '', min_unit_bani: 100, color_variants: false, purchases: [{ date: '2025-02-02', order_id: '=1+1', seller: '', name: '', qty: 1, unit_bani: 100 }] },
  ],
});
const HISTORY_CSV_ROWS = [
  '\u{feff}produs;categorie;data;comanda;link_comanda;vanzator;nume_in_comanda;bucati_pastrate;pret_bucata_lei;pret_minim_lei;peste_minim_lei;variante_culoare',
  '\'=Produs 1;\'+cat;2026-05-26;489000001;https://www.emag.ro/history/shoppingdetails/489000001;eMAG;"Nume ; cu punct-virgula";2;125,00;100,00;50,00;da',
  '\'=Produs 1;\'+cat;;ab;;\'@x;"cu ""ghilimele""";1;100,00;100,00;0,00;da',
  '\'=Produs 1;\'+cat;;489000002;https://www.emag.ro/history/shoppingdetails/489000002;\' -y;\'\t=z;3;100,01;100,00;0,03;da',
  'Sub minim;Cat;2025-01-02;100100;https://www.emag.ro/history/shoppingdetails/100100;S;n;3;0,99;1,00;-0,03;',
  'Cu emoji \u{1f600}\u{85};Ț;2025-01-03;100200;https://www.emag.ro/history/shoppingdetails/100200;\'\u{85}=s;\u{feff}n;1;1234,56;1234,56;0,00;',
  'Comanda cu formula;;2025-02-02;\'=1+1;;;;1;1,00;1,00;0,00;',
  '',
];

describe('linesCsv și priceHistoryCsv pe capcane (formule, ghilimele, Unicode, prag)', () => {
  test('produse.csv: rândurile scrise de Python pe cele 16 linii de capcană', () => {
    const traps = makeLineTraps();
    const text = linesCsv(traps, THRESHOLD_BANI);
    same(text.split('\r\n'), LINES_CSV_ROWS, () => 'rândurile produse.csv');
    same(text, LINES_CSV_ROWS.join('\r\n'), () => 'textul produse.csv');
  });
  test('produse.csv: fără linii, doar capul de tabel, cu BOM', () => {
    same(linesCsv([], THRESHOLD_BANI), `${LINES_CSV_ROWS[0]}\r\n`, () => 'produse.csv gol');
  });
  test('produse.csv: peste_prag compară valoarea liniei cu pragul înmulțit cu cantitatea, strict mai mare; cantitatea zero nu e niciodată peste prag', () => {
    const edge = (qty, total) => linesCsv([trapLine({ qty, line_total_bani: total, kept_qty: qty })], THRESHOLD_BANI).split('\r\n')[1].split(';').pop();
    same([edge(3, 150000), edge(3, 150001), edge(1, 50000), edge(1, 50001), edge(0, 999999)], ['', 'da', '', 'da', ''], () => 'pragul');
  });
  test('istoric_preturi.csv: rândurile scrise de Python pe istoricul de capcană', () => {
    const history = deepFreeze(makeHistoryTrap());
    const text = priceHistoryCsv(history);
    same(text.split('\r\n'), HISTORY_CSV_ROWS, () => 'rândurile istoric_preturi.csv');
    same(text, HISTORY_CSV_ROWS.join('\r\n'), () => 'textul istoric_preturi.csv');
  });
  test('istoric_preturi.csv: fără produse repetate, doar capul de tabel, cu BOM', () => {
    same(priceHistoryCsv({ products: [] }), `${HISTORY_CSV_ROWS[0]}\r\n`, () => 'istoric gol');
  });
});

// ---------- raportul: șablon, înlocuiri, verificări ----------

// Rezumat de capcană (scris de mână, ca dicționarul din Python): floaturi (inclusiv cu valoare întreagă), "<" în nume, marcajele raportului în nume, secvențe $ speciale pentru String.replace, Unicode, control, liste și obiecte goale.
const makeReportSummary = () => ({
  meta: { orders: 2, ratio: new PyFloat(12.25), pct: new PyFloat(5), big: new PyFloat(1e16), tiny: new PyFloat(1e-7), neg: new PyFloat(-0), huge: new PyFloat(1e22), mid: new PyFloat(123456789) },
  names: ['</script><!--', 'a < b > c', '/*__DATE_ANALIZA__*/null', '/*__DASHBOARD_JS__*/ $& $1 $$', 'ț ș ă î â', 'emoji \u{1f600}', 'ghilimele " și \\ backslash', 'control \u{1} și DEL \u{7f}', 'NBSP\u{a0}x', 'sep \u{2028} \u{2029}'],
  empty_list: [], empty_dict: {}, flags: [true, false, null], nested: { a: { b: [1, [2, { c: [] }]] } },
});
// json.dumps(summary, ensure_ascii=False) cu "<" înlocuit prin \u003c, scris de write_report pe rezumatul de mai sus.
const REPORT_DATA_JSON = '{"meta": {"orders": 2, "ratio": 12.25, "pct": 5.0, "big": 1e+16, "tiny": 1e-07, "neg": -0.0, "huge": 1e+22, "mid": 123456789.0}, "names": ["\\u003c/script>\\u003c!--", "a \\u003c b > c", "/*__DATE_ANALIZA__*/null", "/*__DASHBOARD_JS__*/ $& $1 $$", "ț ș ă î â", "emoji \u{1f600}", "ghilimele \\" și \\\\ backslash", "control \\u0001 și DEL \u{7f}", "NBSP\u{a0}x", "sep \u{2028} \u{2029}"], "empty_list": [], "empty_dict": {}, "flags": [true, false, null], "nested": {"a": {"b": [1, [2, {"c": []}]]}}}';
const CSS_MARK = '/*__DASHBOARD_CSS__*/';
const JS_MARK = '/*__DASHBOARD_JS__*/';
const DATA_MARK = '/*__DATE_ANALIZA__*/null';
const REPORT_TEMPLATE = `<style>${CSS_MARK}</style>\n<script id="d" type="application/json">${DATA_MARK}</script>\n<script>${JS_MARK}</script>\n`;
/** Raportul așteptat: șablonul de mai sus cu designul (deja cu sfârșituri de rând LF) și datele de Python. */
const expectedReport = (css, js) => `<style>${css}</style>\n<script id="d" type="application/json">${REPORT_DATA_JSON}</script>\n<script>${js}</script>\n`;

// Cazuri cu rezultat: (css, js, șablon) -> raportul scris de Python; css și js așteptate sunt cele de după citirea în mod text (CRLF și CR devin LF).
const REPORT_OUTPUT_CASES = [
  { nume: 'normal', css: 'a{b:c}', js: 'var x = 1;', out: ['a{b:c}', 'var x = 1;'] },
  { nume: 'dolari în design ($& $1 $$ $` $\' nu au înțeles special)', css: 'a::after{content:\'$& $1 $$ $` $\\\'\'}', js: 'var s = \'$&\' + "$1" + `$$` + \'$`\' + "$\'";', out: ['a::after{content:\'$& $1 $$ $` $\\\'\'}', 'var s = \'$&\' + "$1" + `$$` + \'$`\' + "$\'";'] },
  { nume: 'CRLF și CR în șablon și design devin LF', template: REPORT_TEMPLATE.replaceAll('\n', '\r\n'), css: 'a{b:c}\r\nd{e:f}\r\n', js: 'var x = 1;\r\nvar y = 2;\rvar z = 3;\n', out: ['a{b:c}\nd{e:f}\n', 'var x = 1;\nvar y = 2;\nvar z = 3;\n'] },
  { nume: '</script în CSS e permis (doar </style e interzis acolo)', css: 'a{content:\'</script>\'}', js: 'x', out: ['a{content:\'</script>\'}', 'x'] },
  { nume: '</style în JS e permis (doar </script e interzis acolo)', css: 'a{b:c}', js: 'var a = \'</style>\';', out: ['a{b:c}', 'var a = \'</style>\';'] },
  { nume: 'marcajul CSS în JS rămâne ca atare (CSS-ul s-a completat deja)', css: 'a{b:c}', js: 'var m = \'/*__DASHBOARD_CSS__*/\';', out: ['a{b:c}', 'var m = \'/*__DASHBOARD_CSS__*/\';'] },
  { nume: 'İ nu devine i la verificare (Python: "</scrİpt" nu conține "</script")', css: 'a{b:c}', js: 'var a = \'</scr\u{130}pt>\';', out: ['a{b:c}', 'var a = \'</scr\u{130}pt>\';'] },
  { nume: 'ligatura ﬁ și ſ nu devin litere ASCII la verificare', css: 'a{b:c}', js: 'var a = \'</scr\u{fb01}pt>\' + \'\u{17f}cript\';', out: ['a{b:c}', 'var a = \'</scr\u{fb01}pt>\' + \'\u{17f}cript\';'] },
];
// Cazuri cu eroare: mesajul lui Python, cu numele fișierului în locul căii (JS primește texte, nu căi: șablonul, designul CSS și designul JS se numesc după rolul lor).
const REPORT_ERROR_CASES = [
  { nume: 'fără marcaj CSS', template: REPORT_TEMPLATE.replace(CSS_MARK, ''), css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${CSS_MARK} exact o dată (am găsit 0)` },
  { nume: 'marcaj CSS de două ori', template: REPORT_TEMPLATE + CSS_MARK, css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${CSS_MARK} exact o dată (am găsit 2)` },
  { nume: 'fără marcaj JS', template: REPORT_TEMPLATE.replace(JS_MARK, ''), css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${JS_MARK} exact o dată (am găsit 0)` },
  { nume: 'marcaj JS de trei ori', template: REPORT_TEMPLATE + JS_MARK + JS_MARK, css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${JS_MARK} exact o dată (am găsit 3)` },
  { nume: 'fără marcaj date', template: REPORT_TEMPLATE.replace(DATA_MARK, 'null'), css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${DATA_MARK} exact o dată (am găsit 0)` },
  { nume: 'marcaj date de două ori', template: REPORT_TEMPLATE + DATA_MARK, css: 'a{b:c}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${DATA_MARK} exact o dată (am găsit 2)` },
  { nume: '</style în CSS (majuscule)', css: 'a{b:c}</STYLE>', js: 'x', message: '<d.css> conține „</style” și nu poate fi lipit inline în raport' },
  { nume: '</style în CSS (majuscule mixte)', css: 'a{b:c}/* </StYlE */', js: 'x', message: '<d.css> conține „</style” și nu poate fi lipit inline în raport' },
  { nume: '<!-- în CSS', css: 'a{b:c}<!-- x', js: 'x', message: '<d.css> conține „<!--” și nu poate fi lipit inline în raport' },
  { nume: '</script în JS (majuscule mixte)', css: 'a{b:c}', js: 'var a = \'</Script>\';', message: '<d.js> conține „</script” și nu poate fi lipit inline în raport' },
  { nume: 'CSS și JS invalide deodată: prima eroare e cea a CSS-ului', css: 'a{b:c}</style>', js: 'var a = \'</script>\';', message: '<d.css> conține „</style” și nu poate fi lipit inline în raport' },
  { nume: '<!-- în JS', css: 'a{b:c}', js: 'var a = \'<!--\';', message: '<d.js> conține „<!--” și nu poate fi lipit inline în raport' },
  { nume: 'marcajul datelor în CSS (apare de două ori după completare)', css: 'a{content:\'/*__DATE_ANALIZA__*/null\'}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${DATA_MARK} exact o dată (am găsit 2)` },
  { nume: 'marcajul datelor în JS', css: 'a{b:c}', js: 'var m = \'/*__DATE_ANALIZA__*/null\';', message: `șablonul <t.html> trebuie să conțină ${DATA_MARK} exact o dată (am găsit 2)` },
  { nume: 'marcajul JS în CSS (CSS-ul se completează înaintea JS-ului)', css: 'a{content:\'/*__DASHBOARD_JS__*/\'}', js: 'x', message: `șablonul <t.html> trebuie să conțină ${JS_MARK} exact o dată (am găsit 2)` },
];
/** Mesajul lui Python cu numele fișierelor din ele înlocuite cu rolul lor: JS-ul primește texte, nu căi (șablonul raportului, designul CSS, designul JS). */
const withRoles = (message) => message.replace('șablonul <t.html>', 'șablonul raportului').replace('<d.css>', 'designul CSS').replace('<d.js>', 'designul JS');

describe('buildReport pe capcane (față de write_report)', () => {
  for (const c of REPORT_OUTPUT_CASES) {
    test(`rezultat: ${c.nume}`, () => {
      const summary = deepFreeze(makeReportSummary());
      same(buildReport(c.template ?? REPORT_TEMPLATE, c.css, c.js, summary), expectedReport(...c.out), () => c.nume);
    });
  }
  for (const c of REPORT_ERROR_CASES) {
    test(`eroare: ${c.nume}`, () => {
      assert.throws(
        () => buildReport(c.template ?? REPORT_TEMPLATE, c.css, c.js, makeReportSummary()),
        (error) => error instanceof Error && error.name === 'ValueError' && error.message === withRoles(c.message),
        c.nume,
      );
    });
  }
  test('datele se pun ultimele: un marcaj scris într-un nume de produs nu mai are ce înlocui', () => {
    const report = buildReport(REPORT_TEMPLATE, 'a{b:c}', 'x', makeReportSummary());
    assert.equal(report.split(DATA_MARK).length - 1, 1, 'marcajul datelor din nume rămâne o singură dată, în date');
    assert.ok(report.includes('"/*__DASHBOARD_JS__*/ $& $1 $$"'), 'numele cu marcaj și cu $ rămâne neschimbat');
  });
  test('fără design sau șablon text: ValueError cu rolul lipsă (în Python: fișierul de design lipsește)', () => {
    const named = (message) => (error) => error instanceof Error && error.name === 'ValueError' && error.message === message;
    assert.throws(() => buildReport(REPORT_TEMPLATE, undefined, 'x', {}), named('fișierul de design CSS lipsește'));
    assert.throws(() => buildReport(REPORT_TEMPLATE, 'a{b:c}', null, {}), named('fișierul de design JS lipsește'));
    assert.throws(() => buildReport(undefined, 'a{b:c}', 'x', {}), named('șablonul raportului lipsește'));
  });
  test('numerele din date: întregul simplu iese ca întreg, PyFloat ca float (5.0), fracția simplă ca float; un rezumat pe care JSON-ul Python nu-l poate scrie ridică eroare', () => {
    // json.dumps({"a": 5, "b": 5.0, "c": 1.5, "d": -3}) în Python: {"a": 5, "b": 5.0, "c": 1.5, "d": -3}
    const report = buildReport(REPORT_TEMPLATE, 'a{b:c}', 'x', { a: 5, b: new PyFloat(5), c: 1.5, d: -3 });
    assert.ok(report.includes('<script id="d" type="application/json">{"a": 5, "b": 5.0, "c": 1.5, "d": -3}</script>'), report);
    assert.throws(() => buildReport(REPORT_TEMPLATE, 'a{b:c}', 'x', { value: undefined }), TypeError);
    assert.throws(() => buildReport(REPORT_TEMPLATE, 'a{b:c}', 'x', { value: 2 ** 60 }), TypeError, 'un întreg peste 2^53 nu se scrie rotunjit');
  });
});
