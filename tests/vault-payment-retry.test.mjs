import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

async function policy() {
  const built = await build({entryPoints:['src/lib/vault-payment.ts'],bundle:true,platform:'node',format:'cjs',write:false});
  const result = {exports:{}};
  vm.runInNewContext(built.outputFiles[0].text,{module:result,exports:result.exports});
  return result.exports;
}

test('staff can send or resend any active unpaid file with no limit', async () => {
  const {canRequestVaultPayment} = await policy();
  for (const outcome of ['PAYMENT_REQUEST_SENT','PAYMENT_REQUEST_UNCONFIRMED','PAYMENT_REQUEST_REFUSED','NATIVE_SERVICE_PAYMENT_ALREADY_IN_PROGRESS','',undefined]) {
    assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID',lastPaymentRequestedAt:'2026-11-04T05:51:20Z',lastPaymentRequestOutcome:outcome}),true);
  }
  assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID'}),true);
});
test('only a request still awaiting its answer waits', async () => {
  const {canRequestVaultPayment} = await policy();
  assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID'},true),false);
});
test('paid, open, expired, unverified and revoked files are never sold again', async () => {
  const {canRequestVaultPayment} = await policy();
  for (const accessState of ['OPEN','READY','EXPIRED','PAID_UNVERIFIED',undefined]) {
    assert.equal(canRequestVaultPayment({status:'active',accessState}),false);
  }
  assert.equal(canRequestVaultPayment({status:'revoked',accessState:'UNPAID'}),false);
  assert.equal(canRequestVaultPayment(null),false);
});
test('each blocking state has its own reason, never one grouped warning', async () => {
  const {vaultPaymentBlock,vaultPaymentBlockMessage} = await policy();
  const cases = {OPEN:'ACCESS_OPEN', READY:'ACCESS_READY', EXPIRED:'ACCESS_EXPIRED', PAID_UNVERIFIED:'PAID_UNVERIFIED'};
  const seen = new Set();
  for (const [accessState, code] of Object.entries(cases)) {
    assert.equal(vaultPaymentBlock({status:'active',accessState}), code);
    const message = vaultPaymentBlockMessage(code);
    assert.ok(message && !seen.has(message)); seen.add(message);
  }
  assert.equal(vaultPaymentBlock({status:'revoked',accessState:'UNPAID'}), 'INACTIVE');
  assert.equal(vaultPaymentBlock({status:'active',accessState:'UNPAID'}, true), 'PENDING_LOCAL');
  assert.equal(vaultPaymentBlock({status:'active',accessState:'UNPAID'}), '');
  assert.match(vaultPaymentBlockMessage('PENDING_LOCAL', Date.UTC(2026,10,4,10,0,0)), /this browser started/i);
  assert.doesNotMatch(vaultPaymentBlockMessage('PENDING_LOCAL'), /paid, expired, unverified/);
});
test('the local marker is reconciled with the server-recorded answer', async () => {
  const {parseLocalPending,localPendingValue,serverAnsweredSince} = await policy();
  assert.equal(parseLocalPending(null), null);
  assert.equal(parseLocalPending('requested'), 0);
  const at = Date.UTC(2026,10,4,10,11,30);
  assert.equal(parseLocalPending(localPendingValue(at)), at);
  const answered = {lastPaymentRequestedAt:'2026-11-04T10:11:40Z', lastPaymentRequestOutcome:'PAYMENT_REQUEST_SENT'};
  assert.equal(serverAnsweredSince(answered, at), true);
  assert.equal(serverAnsweredSince(answered, 0), true);
  // An older answer belongs to an earlier send, not to this pending one.
  assert.equal(serverAnsweredSince({...answered, lastPaymentRequestedAt:'2026-11-04T09:00:00Z'}, at), false);
  assert.equal(serverAnsweredSince({lastPaymentRequestedAt:'', lastPaymentRequestOutcome:''}, at), false);
});
