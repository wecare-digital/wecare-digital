import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { safeLocalReturnPath } from '../src/lib/safeReturnPath.ts';
import { authStateQuery } from '../src/lib/authStateQuery.ts';

test('Arogya returns through shared /auth without accepting arbitrary return URLs', () => {
  assert.equal(safeLocalReturnPath('/elsewhere/arogya-yatra/'), '/elsewhere/arogya-yatra/');
  assert.equal(safeLocalReturnPath('/elsewhere/arogya-yatra'), '/elsewhere/arogya-yatra/');
  assert.equal(safeLocalReturnPath('//other.example/'), '/');
  assert.equal(safeLocalReturnPath('/elsewhere/arogya-yatra/?next=evil'), '/');
  const query = authStateQuery(new URLSearchParams('return=%2Felsewhere%2Farogya-yatra%2F&utm_source=test'));
  assert.equal(query.get('return'), '/elsewhere/arogya-yatra/');
  assert.equal(query.has('utm_source'), false);
});

test('public form checks shared authentication at submission; no inline OTP or snapshot catalog', () => {
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
  assert.match(read('../src/pages/elsewhere/arogya-yatra.tsx'), /<AppointmentAccess\s*\/>/);
  const gate = read('../src/components/public/AppointmentAccess.tsx');
  assert.match(gate, /return <AppointmentPlanner \/>/);
  assert.doesNotMatch(gate, /getSession|restoreSession|location\.replace/);
  const planner = read('../src/components/public/AppointmentPlanner.tsx');
  assert.match(planner, /const access = await verifyAtAction\(\)/);
  assert.match(planner, /Your form stays open here/);
  assert.doesNotMatch(read('../src/components/public/SavedAppointmentDrafts.tsx'), /requestOtp|submitOtp|ay-signin-code/);
  assert.doesNotMatch(read('../src/components/public/AppointmentPlanner.tsx'), /apolloAppointmentCatalog|GREAMS_GENERAL_SURGEONS/);
});


test('draft requests are tied to the verified form account', () => {
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
  assert.match(read('../src/components/public/AppointmentPlanner.tsx'), /pending\.current\.accountKey !== access\.accountKey/);
  assert.match(read('../src/components/public/SavedAppointmentDrafts.tsx'), /accountKey, \.\.\.request/);
  assert.match(read('../src/components/public/SavedAppointmentDrafts.tsx'), /pendingSave\.current = request/);
});
