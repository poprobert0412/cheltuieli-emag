// Ore inventate: limite half-open și schimbări DST, independente de fusul calculatorului.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isShoppingTime, validateCampaign, orderTimestamp } from '../../src/cumparaturi/campaign_time.js';

const campaign = { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' };

test('orele HH:MM și intervalul exclud capătul final și refuză date/offseturi invalide', () => {
  for (const value of ['00:00', '08:20', '23:59']) assert.equal(isShoppingTime(value), true);
  for (const value of ['24:00', '12:60', '8:20', '', null]) assert.equal(isShoppingTime(value), false);
  const bounds = validateCampaign(campaign);
  assert.equal(bounds.start_ms, Date.parse('2031-05-09T05:20:00Z'));
  assert.equal(bounds.end_ms, Date.parse('2031-05-09T21:00:00Z'));
  assert.throws(() => validateCampaign({ ...campaign, to: campaign.from, end_time: '08:20' }), /sfârșitul.*început/i);
  assert.throws(() => validateCampaign({ ...campaign, from: '2031-02-30' }), /dată|interval/i);
  assert.throws(() => validateCampaign({ ...campaign, time_zone: 'UTC' }), /fus/i);
  assert.throws(() => validateCampaign({ ...campaign, start_time: null }), /ore/i);
  assert.equal(validateCampaign({ ...campaign, start_time: null, end_time: null }).time_required, true);
  assert.equal(orderTimestamp('2031-05-09T08:20+24:99'), null);
  assert.equal(orderTimestamp('2031-02-30T08:20'), null);
});

test('ora locală RO și instanțele explicite respectă DST, fără timezone al sistemului', () => {
  assert.equal(orderTimestamp('2031-05-09T08:20'), Date.parse('2031-05-09T05:20:00Z'));
  assert.equal(orderTimestamp('2031-01-09T08:20'), Date.parse('2031-01-09T06:20:00Z'));
  assert.equal(orderTimestamp('2031-05-09T05:20:00Z'), orderTimestamp('2031-05-09T08:20+03:00'));
  assert.equal(orderTimestamp('2031-05-09'), null);
  assert.equal(orderTimestamp(null), null);
});

test('limitele într-o oră DST inexistentă sau ambiguă sunt refuzate explicit', () => {
  assert.throws(() => validateCampaign({ ...campaign, from: '2031-03-30', to: '2031-03-31', start_time: '03:30' }), /inexistentă/i);
  assert.throws(() => validateCampaign({ ...campaign, from: '2031-10-26', to: '2031-10-27', start_time: '03:30' }), /ambiguă/i);
  assert.equal(orderTimestamp('2031-03-30T03:30'), null);
  assert.equal(orderTimestamp('2031-10-26T03:30'), null);
  assert.notEqual(orderTimestamp('2031-10-26T03:30+03:00'), orderTimestamp('2031-10-26T03:30+02:00'));
});
