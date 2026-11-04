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

test('a definitive refusal permits another reviewed request for the same unpaid file', async () => {
  const {canRequestVaultPayment} = await policy();
  assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID',lastPaymentRequestedAt:'2026-11-03T22:58:28Z',lastPaymentRequestOutcome:'PAYMENT_REQUEST_REFUSED'}),true);
});

test('sent, uncertain, missing outcomes and locally unresolved sends remain blocked', async () => {
  const {canRequestVaultPayment,isVaultPaymentRefused} = await policy();
  for (const outcome of ['PAYMENT_REQUEST_SENT','PAYMENT_REQUEST_UNCONFIRMED','NO_RESPONSE','',undefined,'UNKNOWN']) {
    assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID',lastPaymentRequestedAt:'2026-11-03T22:58:28Z',lastPaymentRequestOutcome:outcome}),false);
    assert.equal(isVaultPaymentRefused(outcome),false);
  }
  assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID',lastPaymentRequestedAt:'2026-11-03T22:58:28Z',lastPaymentRequestOutcome:'PAYMENT_REQUEST_REFUSED'},true),false);
});

test('paid, expired, unavailable and revoked files cannot be retried after a refusal', async () => {
  const {canRequestVaultPayment} = await policy();
  for (const accessState of ['OPEN','READY','EXPIRED','PAID_UNVERIFIED',undefined]) {
    assert.equal(canRequestVaultPayment({status:'active',accessState,lastPaymentRequestOutcome:'PAYMENT_REQUEST_REFUSED'}),false);
  }
  assert.equal(canRequestVaultPayment({status:'revoked',accessState:'UNPAID',lastPaymentRequestOutcome:'PAYMENT_REQUEST_REFUSED'}),false);
  assert.equal(canRequestVaultPayment(null),false);
  assert.equal(canRequestVaultPayment({status:'active',accessState:'UNPAID'}),true);
});
