// Teste unitare pentru extensie/src/exporturi/descarcare.js și export_files.js: fișierele pe care le descarcă omul din raport (raport.html, CSV-uri, JSON-uri, jurnal).
// Modulele de export (csv_export, price_history_csv, report_html) și analiza se înlocuiesc cu funcții false: aici se verifică legarea (ce primește fiecare,
// ce nume și ce tip MIME are fiecare fișier, ce fișiere se pot descărca la demo) și octeții scriși de pyJsonDumps; paritatea cu Python a exporturilor e în tests/paritate/.
// Un al doilea grup folosește modulele reale (exporturile lui B, analiza lui C, sursele din proiect, tests/unit/piese_reale.js): numele importate trebuie să existe, iar fișierele să iasă bune.
// Descărcarea (Blob + link cu download) rulează pe un document fals: se verifică numele, adresa blob, revocarea după pauză și octeții, cu BOM-ul păstrat.
// Ce NU face: nu pornește Chrome (descărcarea reală din pagină se probează în Edge).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { readFileSync } from 'node:fs';

import { pyJsonDumps } from '../../src/calcul/python_compat.js';
import { DEMO_FILES, REAL_FILES, buildExportFile, mimeTypeOf } from '../../src/exporturi/export_files.js';
import { REVOKE_DELAY_MS, downloadText } from '../../src/exporturi/descarcare.js';
import { loadAnalysis } from '../../src/rulare/analysis_loader.js';
import { loadReportAssets, realAnalysisLoaders } from './piese_reale.js';

const BOM = String.fromCharCode(0xfeff);
const APP_NAME = JSON.parse(readFileSync(new URL('../../manifest.json', import.meta.url), 'utf8')).name;

/** Module de export false, care notează cu ce au fost chemate. */
function fakeLoaders() {
  const calls = [];
  return {
    calls,
    loaders: {
      reportSource: async () => ({ default: { appName: APP_NAME, template: 'SABLON', css: 'CSS', js: 'JS' } }),
      reportHtml: async () => ({ buildReport: (template, css, js, summary, options) => { calls.push(['buildReport', template, css, js, summary, options]); return `<html>${JSON.stringify(summary)}</html>`; } }),
      csvExport: async () => ({ linesCsv: (lines, thresholdBani) => { calls.push(['linesCsv', lines, thresholdBani]); return `${BOM}produs;pret\r\n`; } }),
      priceHistoryCsv: async () => ({ priceHistoryCsv: (history) => { calls.push(['priceHistoryCsv', history]); return `${BOM}nume;pret\r\n`; } }),
      analysis: async () => ({
        analyze: (orders, returns, thresholdBani, generatedAt) => {
          calls.push(['analyze', orders, returns, thresholdBani, generatedAt]);
          return { summary: {}, lines: [{ marker: 'linie' }] };
        },
      }),
    },
  };
}

/** O sursă „analiză salvată” cu date inventate; `overrides` schimbă câmpurile intrării. */
function savedSource(overrides = {}) {
  return {
    kind: 'saved',
    entry: {
      schema: 1,
      extension_version: '0.1.0',
      created_at: '2026-10-14 09:30:00',
      threshold_lei: 500,
      summary: { meta: { orders: 1 }, price_history: [{ name: 'Produs inventat' }], pct: 12.5 },
      orders: [{ order_id: '100000001', blocks: [] }],
      returns: [{ return_id: '55' }],
      log_text: '2026-10-14 09:29:00,001 [run_pipeline] INFO: pornesc\n',
      ...overrides,
    },
  };
}

describe('export_files: ce fișiere se descarcă și cum se construiesc', () => {
  test('lista fișierelor: șapte la o analiză reală, două la demo (raport.html și analiza.json)', () => {
    assert.deepEqual(REAL_FILES, ['raport.html', 'produse.csv', 'istoric_preturi.csv', 'analiza.json', 'comenzi.json', 'retururi.json', 'jurnal.txt']);
    assert.deepEqual(DEMO_FILES, ['raport.html', 'analiza.json']);
  });

  test('tipurile MIME: HTML, CSV, JSON și text, toate cu UTF-8', () => {
    assert.equal(mimeTypeOf('raport.html'), 'text/html;charset=utf-8');
    assert.equal(mimeTypeOf('produse.csv'), 'text/csv;charset=utf-8');
    assert.equal(mimeTypeOf('istoric_preturi.csv'), 'text/csv;charset=utf-8');
    assert.equal(mimeTypeOf('analiza.json'), 'application/json;charset=utf-8');
    assert.equal(mimeTypeOf('jurnal.txt'), 'text/plain;charset=utf-8');
  });

  test('analiza.json: json.dumps(indent=1) din Python, cu procentele ca float', async () => {
    const source = savedSource();
    const { text, mime } = await buildExportFile('analiza.json', source, fakeLoaders().loaders);
    assert.equal(text, pyJsonDumps(source.entry.summary, { fractions: true }));
    assert.match(text, /"pct": 12\.5/);
    assert.equal(mime, 'application/json;charset=utf-8');
  });

  test('comenzi.json și retururi.json: listele salvate, scrise ca json.dumps din Python (fără fracții)', async () => {
    const source = savedSource();
    const orders = await buildExportFile('comenzi.json', source, fakeLoaders().loaders);
    const returns = await buildExportFile('retururi.json', source, fakeLoaders().loaders);
    assert.equal(orders.text, pyJsonDumps(source.entry.orders));
    assert.equal(returns.text, pyJsonDumps(source.entry.returns));
  });

  test('jurnal.txt: jurnalul salvat, neschimbat', async () => {
    const source = savedSource();
    const { text, mime } = await buildExportFile('jurnal.txt', source, fakeLoaders().loaders);
    assert.equal(text, source.entry.log_text);
    assert.equal(mime, 'text/plain;charset=utf-8');
  });

  test('raport.html: șablonul, designul și analiza ajung la buildReport', async () => {
    const { loaders, calls } = fakeLoaders();
    const source = savedSource();
    const { text, mime } = await buildExportFile('raport.html', source, loaders);
    assert.deepEqual(calls, [['buildReport', 'SABLON', 'CSS', 'JS', source.entry.summary, { context: 'extension', appName: APP_NAME }]]);
    assert.ok(text.startsWith('<html>'));
    assert.equal(mime, 'text/html;charset=utf-8');
  });

  test('istoric_preturi.csv: din price_history al analizei, cu BOM-ul păstrat', async () => {
    const { loaders, calls } = fakeLoaders();
    const source = savedSource();
    const { text } = await buildExportFile('istoric_preturi.csv', source, loaders);
    assert.deepEqual(calls, [['priceHistoryCsv', source.entry.summary.price_history]]);
    assert.ok(text.startsWith(BOM));
  });

  test('produse.csv: registrul se recalculează din comenzile și retururile salvate, cu pragul în bani rotunjit ca în Python', async () => {
    const { loaders, calls } = fakeLoaders();
    const source = savedSource({ threshold_lei: 0.025 }); // 0,025 lei × 100 = 2,5 bani: round() din Python dă 2 (jumătatea la par), Math.round ar da 3
    const { text } = await buildExportFile('produse.csv', source, loaders);
    assert.deepEqual(calls[0], ['analyze', source.entry.orders, source.entry.returns, 2, '2026-10-14 09:30']);
    assert.deepEqual(calls[1], ['linesCsv', [{ marker: 'linie' }], 2]);
    assert.ok(text.startsWith(BOM));
  });

  test('la demo se descarcă doar raport.html și analiza.json (din datele inventate); restul se refuză', async () => {
    const { loaders, calls } = fakeLoaders();
    const source = { kind: 'demo', summary: { meta: { demo: true } } };
    assert.equal((await buildExportFile('analiza.json', source, loaders)).text, pyJsonDumps(source.summary, { fractions: true }));
    await buildExportFile('raport.html', source, loaders);
    assert.equal(calls[0][4], source.summary);
    for (const name of ['produse.csv', 'istoric_preturi.csv', 'comenzi.json', 'retururi.json', 'jurnal.txt']) {
      await assert.rejects(buildExportFile(name, source, loaders), RangeError, name);
    }
  });

  test('un nume necunoscut se refuză (RangeError), nu se ghicește', async () => {
    await assert.rejects(buildExportFile('parola.txt', savedSource(), fakeLoaders().loaders), RangeError);
  });
});

describe('export_files cu modulele reale de export și de analiză (fără build): numele importate se potrivesc, iar fișierele ies bune', () => {
  const { demoSummary, reportSource } = loadReportAssets();
  const realLoaders = {
    reportSource: async () => ({ default: reportSource }),
    reportHtml: () => import('../../src/exporturi/report_html.js'),
    csvExport: () => import('../../src/exporturi/csv_export.js'),
    priceHistoryCsv: () => import('../../src/exporturi/price_history_csv.js'),
    analysis: () => loadAnalysis(realAnalysisLoaders()),
  };
  /** O analiză „salvată” cu rezumatul de demonstrație și fără comenzi sau retururi (analiza reală are ce recalcula, dar nimic de scris în registru). */
  const demoEntry = () => ({
    kind: 'saved',
    entry: { schema: 1, extension_version: '0.1.0', created_at: '2026-10-14 09:30:00', threshold_lei: 500, summary: demoSummary(), orders: [], returns: [], log_text: '' },
  });

  test('raport.html: pagină completă, fără marcaje rămase, cu rezumatul în blocul JSON (citit înapoi e egal cu rezumatul)', async () => {
    const summary = demoSummary();
    const { text } = await buildExportFile('raport.html', { kind: 'demo', summary }, realLoaders);
    assert.match(text, /^<!doctype html>/);
    assert.doesNotMatch(text, /\/\*__(DATE_ANALIZA|DASHBOARD_JS|DASHBOARD_CSS)__\*\//);
    const block = /<script id="date-analiza" type="application\/json">([\s\S]*?)<\/script>/.exec(text);
    assert.ok(block, 'blocul JSON cu datele lipsește');
    assert.deepEqual(JSON.parse(block[1]), summary);
  });

  test('analiza.json: rezumatul scris ca json.dumps(indent=1) din Python se citește înapoi la fel', async () => {
    const summary = demoSummary();
    const { text } = await buildExportFile('analiza.json', { kind: 'demo', summary }, realLoaders);
    assert.deepEqual(JSON.parse(text), summary);
    assert.ok(text.startsWith('{\n "meta": {'), 'indent 1, ca în Python');
  });

  test('istoric_preturi.csv: din price_history al analizei salvate, cu BOM și cel puțin un rând pe produs', async () => {
    const source = demoEntry();
    const { text } = await buildExportFile('istoric_preturi.csv', source, realLoaders);
    assert.ok(text.startsWith(BOM));
    const rows = text.split(/\r?\n/).filter((row) => row !== '');
    assert.ok(rows.length > source.entry.summary.price_history.products.length, `${rows.length} rânduri`);
  });

  test('produse.csv: analiza reală se recalculează din comenzile și retururile salvate (aici niciuna) și dă antetul din Python, cu BOM', async () => {
    const { text } = await buildExportFile('produse.csv', demoEntry(), realLoaders);
    assert.ok(text.startsWith(BOM));
    assert.match(text.slice(BOM.length), /^comanda;link_comanda;data;an;vanzator;produs;categorie/);
  });
});

/** Document și URL false: notează ce s-a făcut cu linkul de descărcare. */
function fakeEnvironment() {
  const events = [];
  const link = {
    hidden: false,
    href: '',
    download: '',
    click() { events.push(['click', this.href, this.download]); },
    remove() { events.push(['remove']); },
  };
  const blobs = [];
  return {
    events,
    blobs,
    timers: [],
    env: {
      document: {
        createElement(tag) { events.push(['createElement', tag]); return link; },
        body: { appendChild(node) { events.push(['append', node === link]); } },
      },
      URL: {
        createObjectURL(blob) { blobs.push(blob); return 'blob:chrome-extension://test/1234'; },
        revokeObjectURL(url) { events.push(['revoke', url]); },
      },
      setTimeout(callback, delay) { this.timers.push([callback, delay]); },
    },
  };
}

describe('downloadText: Blob și link cu download, fără permisiunea downloads', () => {
  test('creează un link ascuns cu numele fișierului și adresa blob, îl apasă și îl scoate', () => {
    const fake = fakeEnvironment();
    fake.env.timers = fake.timers;
    downloadText('produse.csv', 'a;b\r\n', 'text/csv;charset=utf-8', fake.env);
    assert.deepEqual(fake.events, [
      ['createElement', 'a'], ['append', true], ['click', 'blob:chrome-extension://test/1234', 'produse.csv'], ['remove'],
    ]);
  });

  test('adresa blob se revocă după REVOKE_DELAY_MS (Firefox are nevoie de câteva secunde ca să înceapă salvarea)', () => {
    const fake = fakeEnvironment();
    fake.env.timers = fake.timers;
    downloadText('x.json', '{}', 'application/json', fake.env);
    assert.equal(fake.timers.length, 1);
    assert.equal(fake.timers[0][1], REVOKE_DELAY_MS);
    assert.ok(fake.events.every(([name]) => name !== 'revoke'), 'încă nu s-a revocat');
    fake.timers[0][0]();
    assert.deepEqual(fake.events.at(-1), ['revoke', 'blob:chrome-extension://test/1234']);
  });

  test('octeții sunt textul în UTF-8, cu BOM-ul de la început păstrat (Excel citește diacriticele din CSV după el), și tipul MIME dat', async () => {
    const fake = fakeEnvironment();
    fake.env.timers = fake.timers;
    downloadText('produse.csv', `${BOM}prețul;ș\r\n`, 'text/csv;charset=utf-8', fake.env);
    const blob = fake.blobs[0];
    assert.equal(blob.type, 'text/csv;charset=utf-8');
    const bytes = new Uint8Array(await blob.arrayBuffer());
    assert.deepEqual([...bytes.slice(0, 3)], [0xef, 0xbb, 0xbf]);
    assert.equal(new TextDecoder().decode(bytes.slice(3)), 'prețul;ș\r\n');
  });
});
