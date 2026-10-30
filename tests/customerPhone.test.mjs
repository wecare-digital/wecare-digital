import assert from 'node:assert/strict';
import test from 'node:test';
import { contactPhoneE164, contactPhoneMatchKey } from '../src/lib/contactPhone.ts';

test('national WhatsApp numbers honor the selected visible dial code', () => {
  assert.equal(contactPhoneE164('08100640044', '+91'), '+918100640044');
  assert.equal(contactPhoneE164(' 81006 40044 ', '+91'), '+918100640044');
  assert.equal(contactPhoneE164('050 123 4567', '+971'), '+971501234567');
});

test('explicit international numbers keep their own dial code', () => {
  assert.equal(contactPhoneE164('+91 (81006) 40044', '+971'), '+918100640044');
  assert.equal(contactPhoneE164('00 91 81006 40044', '+971'), '+918100640044');
  assert.equal(contactPhoneE164('+971 50 123 4567', '+91'), '+971501234567');
});

test('missing or empty inputs never invent a phone owner', () => {
  assert.equal(contactPhoneE164('', '+91'), '');
  assert.equal(contactPhoneE164('0', '+91'), '');
  assert.equal(contactPhoneE164('+', '+91'), '');
  assert.equal(contactPhoneE164('8100640044', ''), '');
});

test('formatting does not split one existing customer into two identities', () => {
  const candidate = contactPhoneE164('08100640044', '+91');
  assert.equal(contactPhoneMatchKey(candidate), contactPhoneMatchKey('+91-81006 40044'));
  assert.notEqual(contactPhoneMatchKey(candidate), contactPhoneMatchKey('+971 81006 40044'));
});
