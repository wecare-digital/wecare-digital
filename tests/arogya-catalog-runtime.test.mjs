import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { requestApolloCatalog, AppointmentApiError } from '../src/lib/arogyaBooking.ts';
import { productCheckoutLine } from '../src/config/productCheckout.ts';

const endpoint = 'https://synthetic.lambda-url.us-east-1.on.aws/';
const token = 'synthetic-token';
const signal = new AbortController().signal;

test('renewal response is explicit and bounded, with no options or provider token', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'renewing', retryAfter: 3 }), { status: 202 });
    assert.deepEqual(await requestApolloCatalog(endpoint, token, 'hospitals', {}, signal),
      { status: 'renewing', retryAfter: 3 });
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'renewing', retryAfter: 600 }), { status: 202 });
    await assert.rejects(requestApolloCatalog(endpoint, token, 'hospitals', {}, signal));
  } finally { globalThis.fetch = original; }
});

test('catalogue time choices are accepted only when explicitly marked preferences', async () => {
  const original = globalThis.fetch;
  try {
    const options = [{ id: '08:15', label: '08:15' }];
    globalThis.fetch = async () => new Response(JSON.stringify({ options }), { status: 200 });
    await assert.rejects(requestApolloCatalog(endpoint, token, 'times', {}, signal));
    globalThis.fetch = async () => new Response(JSON.stringify({ options, preferredOnly: true }), { status: 200 });
    assert.deepEqual(await requestApolloCatalog(endpoint, token, 'times', {}, signal), { status: 'ready', options });
    globalThis.fetch = async () => new Response('{}', { status: 401 });
    await assert.rejects(requestApolloCatalog(endpoint, token, 'times', {}, signal),
      error => error instanceof AppointmentApiError && error.status === 401);
  } finally { globalThis.fetch = original; }
});

test('ordinary Arogya checkout stays disabled until an owned appointment intent exists', () => {
  assert.equal(productCheckoutLine('sehat'), null);
  const page = readFileSync(new URL('../src/pages/elsewhere/arogya-yatra.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(page, /<ProductBuyBox/);
  assert.match(page, /No payment is taken for a draft/);
});


test('public directory handoff uses fixed official links without patient data', () => {
  const planner = readFileSync(new URL('../src/components/public/AppointmentPlanner.tsx', import.meta.url), 'utf8');
  const access = readFileSync(new URL('../src/components/public/AppointmentAccess.tsx', import.meta.url), 'utf8');
  assert.match(access, /if \( ready \) return <AppointmentPlanner/);
  assert.match(planner, /href="https:\/\/www\.apollohospitals\.com\/facilities\/hospitals" target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"/);
  assert.match(planner, /href="https:\/\/www\.apollohospitals\.com\/doctors" target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"/);
  assert.match(planner, /Availability and appointment confirmation are handled by Apollo/);
});
