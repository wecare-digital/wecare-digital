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
