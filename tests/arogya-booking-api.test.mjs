import test from 'node:test';
import assert from 'node:assert/strict';
import { AppointmentApiError, appointmentDraftAction } from '../src/lib/arogyaBooking.ts';

test('appointment storage accepts only the regional Function URL and sends private data in POST', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({draft: {draftId: 'test', revision: 1}})};
  };
  try {
    await assert.rejects(appointmentDraftAction('https://example.com/', 'token', {}), /not available/);
    assert.equal(calls.length, 0);
    const endpoint = 'https://example.lambda-url.us-east-1.on.aws/';
    await appointmentDraftAction(endpoint, 'customer-token', {action: 'save', plan: {patientName: 'Synthetic Patient'}});
    assert.equal(calls[0].url, endpoint);
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[0].options.cache, 'no-store');
    assert.equal(calls[0].options.credentials, 'omit');
    assert.equal(calls[0].options.headers.Authorization, 'Bearer customer-token');
    assert.equal(JSON.parse(calls[0].options.body).plan.patientName, 'Synthetic Patient');
    globalThis.fetch = async () => ({ok: false, status: 401, json: async () => ({error: 'Sign in again.'})});
    await assert.rejects(appointmentDraftAction(endpoint, 'expired-token', {action:'list'}), error => error instanceof AppointmentApiError && error.status === 401);
    globalThis.fetch = async () => ({ok: false, status: 502, json: async () => { throw new SyntaxError('HTML response'); }});
    await assert.rejects(appointmentDraftAction(endpoint, 'token', {action:'list'}), error => error instanceof AppointmentApiError && error.status === 502 && /temporarily unavailable/.test(error.message));
  } finally { globalThis.fetch = original; }
});
