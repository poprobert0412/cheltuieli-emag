// Contractul anonim al cardului și tratarea sumelor introduse în formulare.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recapData, drawRecap, RECAP_SIZE } from '../../src/cumparaturi/recap_export.js';
import { inputBani, moneyInput } from '../../src/cumparaturi/ui_dom.js';

test('sumele de formular păstrează bani întregi, zero și absența', () => {
  assert.equal(inputBani(''), null); assert.equal(inputBani('0'), 0); assert.equal(inputBani('219,99'), 21999);
  assert.equal(inputBani('219.99'), 21999); assert.equal(moneyInput(1), '0,01');
  for (const invalid of ['-1', 'NaN', '1,234', '1e3', '<img>']) assert.throws(() => inputBani(invalid));
});

test('cardul selectează numai anul și agregatele; ascunderea elimină suma', () => {
  const summary = { customer: 'NU ÎN EXPORT', by_year: [{ year: '2024', spent_bani: 12345, orders: 2, kept_units: 3, order_id: 'NU ÎN EXPORT' }] };
  assert.deepEqual(recapData(summary, '2024', false, false), { year: '2024', spent: '123,45 Lei', orders: '2', units: '3', demo: false });
  const hidden = recapData(summary, '2024', true, true);
  assert.equal(hidden.spent, null); assert.ok(!JSON.stringify(hidden).includes('NU ÎN EXPORT'));
  assert.throws(() => recapData(summary, '2023', false, false));
});

test('desenarea ascunsă nu scrie suma și păstrează dimensiunile aprobate', () => {
  const texts = [];
  const context = new Proxy({ measureText: (value) => ({ width: String(value).length * 12 }), fillText: (value) => texts.push(value) }, { get: (target, key) => target[key] ?? (() => {}) });
  const canvas = { getContext: () => context };
  drawRecap(canvas, { year: '2024', spent: null, orders: '2', units: '3', demo: true }, { paper: '#fff', ink: '#111', ink3: '#444', hl: '#ff0', rule: '#ddd', rule2: '#aaa', sans: 'sans-serif', display: 'sans-serif', mono: 'monospace' });
  assert.equal(canvas.width, RECAP_SIZE.width * RECAP_SIZE.scale); assert.equal(canvas.height, RECAP_SIZE.height * RECAP_SIZE.scale);
  assert.ok(!texts.includes('Plătit efectiv')); assert.ok(texts.includes('BILANȚUL MEU')); assert.ok(texts.includes('Exemplu cu date inventate'));
});
