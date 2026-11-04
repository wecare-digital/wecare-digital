import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';

const built = await build({entryPoints:['src/lib/vault-payment-status.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const result = {exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module:result,exports:result.exports});
const {vaultPaymentStatusMessage} = result.exports;

test('current open access replaces the old instruction to complete payment', () => {
  const message = vaultPaymentStatusMessage({fileId:'paid-file',accessState:'OPEN',vaultPaymentStatus:'PAID',downloadCount:1});
  assert.match(message,/Payment verified/);
  assert.match(message,/Access is open/);
  assert.match(message,/Downloads: 1/);
  assert.doesNotMatch(message,/Waiting|Complete Review|request sent/i);
});

test('ready and expired access acknowledge the payment without selling it again', () => {
  assert.match(vaultPaymentStatusMessage({fileId:'ready',accessState:'READY',downloadCount:0}),/Payment verified.*ready/i);
  assert.match(vaultPaymentStatusMessage({fileId:'expired',accessState:'EXPIRED',downloadCount:1}),/Payment verified.*expired.*Do not request another payment/i);
  assert.match(vaultPaymentStatusMessage({fileId:'ready',accessState:'READY',downloadCount:0}),/Downloads: 0/);
  assert.match(vaultPaymentStatusMessage({fileId:'expired',accessState:'EXPIRED',downloadCount:1}),/Downloads: 1/);
});

test('missing and unpaid records never claim payment or access succeeded', () => {
  for (const file of [undefined,{fileId:'unpaid',accessState:'UNPAID',downloadCount:0}]) {
    assert.equal(vaultPaymentStatusMessage(file),'Payment request sent. Waiting for verified payment on WhatsApp.');
  }
  assert.match(vaultPaymentStatusMessage({fileId:'reconcile',accessState:'PAID_UNVERIFIED',downloadCount:0}),/reconciliation/i);
});
