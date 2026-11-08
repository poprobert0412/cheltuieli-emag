// Fixture-uri inventate pentru oracolul independent; nu deschid browserul sau contul real.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { campaignOracle } from '../../scripts/shopping_acceptance.mjs';

const campaign = { from: '2027-11-05', to: '2027-11-06', start_time: '07:15', end_time: '00:00', time_zone: 'Europe/Bucharest' };
/** Creează exclusiv nume/ID-uri inventate și alocări care se adună exact. */
function source(stamps) {
  const orders = stamps.map((placed_at, index) => ({ order_id: `inventat-${index}`, placed_at }));
  const allocations = orders.map((order, index) => [order.order_id, { spent_bani: (index + 1) * 101, in_progress_bani: index * 17 }]);
  return { orders, allocations };
}
test('campania include începutul precis, exclude sfârșitul și nu presupune o comandă', () => {
  const { orders, allocations } = source(['2027-11-05T07:14:59.999', '2027-11-05T07:15:00', '2027-11-05T20:00', '2027-11-06T00:00']);
  assert.deepEqual(campaignOracle(orders, allocations, campaign), { orders: 2, paid: 505, pending: 51, missingTimes: 0, missingDates: 0 });
});
test('offseturile explicite se compară în ora României; datele fără oră sunt excluse', () => {
  const { orders, allocations } = source(['2027-11-05T05:15:00Z', '2027-11-05T07:15:00+02:00', '2027-11-05', null, '2027-11-06']);
  assert.deepEqual(campaignOracle(orders, allocations, campaign), { orders: 2, paid: 303, pending: 17, missingTimes: 1, missingDates: 1 });
});
test('oracolul refuză limita locală ambiguă la DST și registrul incomplet', () => {
  assert.throws(() => campaignOracle([], [], { ...campaign, from: '2027-10-31', to: '2027-11-01', start_time: '03:30' }), /campaign_boundary_invalid/);
  const { orders } = source(['2027-11-05T08:00']);
  assert.throws(() => campaignOracle(orders, [], campaign), /ledger_allocation_missing/);
});
test('zero comenzi este un rezultat calculat, nu o stare verde inventată', () => {
  assert.deepEqual(campaignOracle([], [], campaign), { orders: 0, paid: 0, pending: 0, missingTimes: 0, missingDates: 0 });
});
