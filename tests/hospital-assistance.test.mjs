import test from 'node:test';
import assert from 'node:assert/strict';
import { HOSPITAL_CHOICES, isAssistanceReceipt } from '../src/lib/hospitalAssistance.ts';

test('any-hospital requests have an explicit unconfirmed receipt', () => {
  assert.deepEqual(HOSPITAL_CHOICES, ['Apollo Hospitals', 'Another hospital', 'Help me choose']);
  const receipt = {requestId:'550e8400-e29b-41d4-a716-446655440000',status:'REQUESTED',createdAt:1795819000,appointmentConfirmed:false};
  assert.equal(isAssistanceReceipt(receipt), true);
  for (const mutation of [{status:'CONFIRMED'},{appointmentConfirmed:true},{requestId:'invalid'},{createdAt:'1795819000'}]) {
    assert.equal(isAssistanceReceipt({...receipt,...mutation}), false);
  }
});
