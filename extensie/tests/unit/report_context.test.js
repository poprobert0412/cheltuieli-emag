// Contextul raportului: desktop implicit, extensie explicită, fără schimbarea datelor sau a HTML-ului implicit față de Python.
// Verifică serializarea sigură a opțiunilor și refuzul marcajelor lipsă/dublate; randarea reală este în e2e/report_context.test.js.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildReport } from '../../src/exporturi/report_html.js';
import { loadReportAssets } from './piese_reale.js';

const OPTIONS = '/*__REPORT_OPTIONS__*/{}';
const NOSCRIPT = '<!--__REPORT_NOSCRIPT__-->';
const TEMPLATE = `<style>/*__DASHBOARD_CSS__*/</style><noscript>${NOSCRIPT}Desktop<!--__REPORT_NOSCRIPT_END__--></noscript><script>var options=${OPTIONS};</script><script id="date-analiza" type="application/json">/*__DATE_ANALIZA__*/null</script><script>/*__DASHBOARD_JS__*/</script>`;

test('opțiunile absente păstrează marcajul desktop și exact aceleași date', () => {
  const html = buildReport(TEMPLATE, 'body{}', 'var x=1;', { value: 42 });
  assert.equal(html, `<style>body{}</style><noscript>${NOSCRIPT}Desktop<!--__REPORT_NOSCRIPT_END__--></noscript><script>var options=${OPTIONS};</script><script id="date-analiza" type="application/json">{"value": 42}</script><script>var x=1;</script>`);
});

test('contextul extensiei intră ca JSON sigur, fără să modifice rezumatul sau un marker aflat în date', () => {
  const summary = { name: '</script><!--', marker: OPTIONS, value: 42 };
  const snapshot = JSON.stringify(summary);
  const html = buildReport(TEMPLATE, 'body{}', 'var x=1;', summary, { context: 'extension', appName: '</script><h1>$&' });
  const options = /var options=([^;]+);/.exec(html)?.[1];
  assert.deepEqual(JSON.parse(options), { context: 'extension', appName: '</script><h1>$&' });
  assert.doesNotMatch(options, /</);
  assert.equal(JSON.stringify(summary), snapshot);
  const data = /<script id="date-analiza" type="application\/json">([\s\S]*?)<\/script>/.exec(html)?.[1];
  assert.deepEqual(JSON.parse(data), summary);
  assert.ok(html.includes('Poți descărca aceleași date din extensie în format JSON.'));
  assert.ok(!html.includes('rezumat.txt'));
});

test('exportul extensiei refuză marcajul de opțiuni lipsă sau dublat', () => {
  for (const template of [TEMPLATE.replace(OPTIONS, '{}'), TEMPLATE + OPTIONS]) {
    assert.throws(() => buildReport(template, '', '', {}, { context: 'extension' }), /REPORT_OPTIONS.*exact o dată/);
  }
});

test('exportul extensiei refuză limite noscript lipsă sau dublate', () => {
  for (const template of [TEMPLATE.replace(NOSCRIPT, ''), TEMPLATE + NOSCRIPT]) {
    assert.throws(() => buildReport(template, '', '', {}, { context: 'extension' }), /REPORT_NOSCRIPT.*exact o dată/);
  }
});

test('validarea extensiei nu indică fișiere desktop; validarea implicită păstrează ajutorul desktop', () => {
  const { validate } = loadReportAssets();
  for (const data of [null, [], {}]) {
    const extension = validate(data, { context: 'extension' });
    assert.equal(extension.ok, false);
    assert.doesNotMatch(extension.errors.join(' '), /iesiri|aplicația locală|--din-cache/);
    assert.match(extension.errors.join(' '), /Pornește din nou analiza/);
    assert.match(validate(data).errors.join(' '), /iesiri/);
  }
});
