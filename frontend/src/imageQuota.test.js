import test from 'node:test';
import assert from 'node:assert/strict';
import { imageQuotaMessage } from './imageQuota.js';

test('rolling reset is formatted in Jakarta by default, with exact date and time', () => {
  const value = imageQuotaMessage({reset_at: '2026-11-18T07:30:00+00:00'});
  assert.match(value, /18 November 2026/);
  assert.match(value, /14[.:]30[.:]00/);
  assert.match(value, /24 jam bergulir/);
  assert.match(value, /Chat biasa tetap bisa digunakan/);
});
test('explicit timezone and invalid timezone fallback', () => {
  const event = {reset_at: '2026-11-18T07:30:00Z'};
  assert.match(imageQuotaMessage(event, 'UTC'), /07[.:]30/);
  assert.equal(imageQuotaMessage(event, 'invalid'), imageQuotaMessage(event));
});
test('uncertain reservation never invents reset time', () => {
  const value = imageQuotaMessage({pending:true, reset_at:null});
  assert.match(value, /menunggu konfirmasi/);
  assert.match(value, /sedang diproses/);
  assert.doesNotMatch(value, /1970/);
});
