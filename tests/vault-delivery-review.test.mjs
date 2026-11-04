import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {build} from 'esbuild';
const built = await build({entryPoints:['src/lib/vault-delivery-review.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const mod = {exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module:mod,exports:mod.exports});
const {vaultDeliveryReview,vaultDeliveryReviewPrompt} = mod.exports;
const contact = {name:'Test Customer', phone:'+919000000001', checkoutAddressUpdatedAt:1793767500,
  checkoutDeliveryAddress:{addressLine1:'12 Example Street',city:'Kolkata',state:'West Bengal',postalCode:'700012',country:'India',countryCode:'IN'},
  addressLine1:'12 Example Street', city:'Kolkata', state:'West Bengal', postalCode:'700012', country:'India'};
test('a complete saved address yields the exact backend confirmation', () => {
  const r = vaultDeliveryReview(contact);
  assert.equal(r.ok, true);
  assert.equal(r.confirmation.confirmed, true);
  assert.equal(r.confirmation.checkoutAddressUpdatedAt, 1793767500);
  assert.match(r.addressText, /Kolkata/);
  const p = vaultDeliveryReviewPrompt({ownerName:'T',ownerPhone:'+91',fileName:'f.pdf',totalText:'₹84.97',addressText:r.addressText});
  assert.match(p.message, /CURRENT and CORRECT/);
});
test('missing contact, address or revision refuses locally', () => {
  assert.equal(vaultDeliveryReview(null).ok, false);
  assert.equal(vaultDeliveryReview({...contact, checkoutAddressUpdatedAt: undefined}).ok, false);
  assert.equal(vaultDeliveryReview({name:'x', phone:'+91'}).ok, false);
});
test('every Vault payment screen sends the shared confirmation', () => {
  for (const file of ['src/components/workspace/pay/VaultWorkspace.tsx','src/components/ws/collect/VaultPanel.tsx','src/components/workspace/pay/VaultWorkbench.tsx']) {
    const src = readFileSync(file,'utf8');
    assert.match(src, /vaultDeliveryReview\(/, file);
    assert.match(src, /requestSecureFilePayment\([^)]*(review\.confirmation|deliveryConfirmation)\s*\)/, file);
  }
});
