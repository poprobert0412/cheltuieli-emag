import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareProduct } from '../../src/panou/product_comparison.js';

const product = { name: 'Veioză exemplu 40 cm, roșie' };
const row = (id, name, date, unit_bani) => ({ id, name, date, unit_bani, qty: 1 });
test('egalitate integrală cu spații/case normalizate; păstrează dimensiune, capacitate și culoare', () => {
  const purchases = [row('1', ' veioză   EXEMPLU 40 cm, roșie ', '2026-10-02', 21000), row('2', product.name, '2026-11-01', 28999), row('3', `${product.name} set`, '2026-11-02', 99), row('4', 'Veioză exemplu 60 cm, roșie', '2026-11-03', 99), row('5', 'Veioză exemplu 40 cm, albă', '2026-11-03', 99)];
  const result = compareProduct(product, purchases);
  assert.equal(result.count, 2);
  assert.equal(result.minimum.unit_bani, 21000);
  assert.equal(result.last.unit_bani, 28999);
  assert.equal(result.match, 'name');
});
test('lipsa istoricului și prețurile nevalide nu inventează potriviri', () => {
  assert.equal(compareProduct(product, []).status, 'no-history');
  assert.equal(compareProduct(product, [row('1', product.name, '2026-10-01', NaN)]).status, 'no-history');
});
test('în aceeași zi prețurile distincte nu au ordine cunoscută; minimul rămâne valid', () => {
  const result = compareProduct(product, [row('1', product.name, '2026-11-01', 21000), row('2', product.name, '2026-11-01', 22000)]);
  assert.equal(result.last, null);
  assert.equal(result.minimum.unit_bani, 21000);
});
test('o achiziție fără dată nu este declarată ultima cumpărare', () => {
  const result = compareProduct(product, [row('1', product.name, null, 21000), row('2', product.name, '2026-11-01', 22000)]);
  assert.equal(result.last, null);
  assert.equal(result.minimum.unit_bani, 21000);
});
