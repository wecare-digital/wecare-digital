/** Short Commerce Part 1 behavioural tests for the actual TypeScript cart module.
 *
 * Runs offline using esbuild (already a devDependency) and a synthetic, in-memory
 * browser. No payment API, WhatsApp account, customer identity or live price is touched.
 */
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { buildSync } from 'esbuild';

const bundle = buildSync({
  entryPoints: ['src/lib/cart.ts'],
  bundle: true, platform: 'node', format: 'cjs', target: 'node24',
  define: { 'process.env.NODE_ENV': '"test"' },
  write: false,
});
assert.equal(bundle.outputFiles.length, 1);

const storage = new Map();
const browser = {
  localStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  },
  dispatchEvent: () => {},
  CustomEvent: class CustomEvent {},
};
const runtime = {
  module: { exports: {} }, exports: {}, window: browser,
  process: { env: { NODE_ENV: 'test' } }, console,
};
runtime.exports = runtime.module.exports;
vm.runInNewContext(bundle.outputFiles[0].text, runtime, { timeout: 3000 });
const cart = runtime.module.exports;

const kiosk = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', slug: 'kiosk',
  name: 'Kiosk', formattedPrice: '₹24,999.00',
  variants: [{ id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', label: 'Standard', inStock: true }],
};
const apparel = {
  id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', slug: 'merchandise',
  name: 'Merchandise', formattedPrice: '₹1,199.00',
  variants: [{ id: 'c0000001-0000-4000-8000-000000000001', label: 'Men / S', inStock: true }],
};
const chooseKiosk = () => cart.addItem(kiosk, 9, kiosk.variants[0].id);

// Storefront selection is one item, quantity one, even when a caller tries 9.
let selected = chooseKiosk();
assert.equal(selected.length, 1);
assert.equal(selected[0].quantity, 1);
assert.equal(cart.cartCount(), 1);

// A different unpaid selection replaces, never appends to, the cart.
selected = cart.addItem(apparel, 2, apparel.variants[0].id);
assert.equal(selected.length, 1);
assert.equal(selected[0].productId, apparel.id);
assert.equal(selected[0].quantity, 1);
assert.equal(cart.readCart().length, 1);

// Contributions and paid services use the same single-selection storage.
selected = cart.setContribution('7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a');
assert.equal(selected.length, 1);
assert.equal(selected[0].quantity, 1);
selected = cart.setServiceLine('22222222-2222-4222-8222-222222222222',
  'fake-test-intent', 7500);
assert.equal(selected.length, 1);
assert.equal(selected[0].quantity, 1);
assert.equal(cart.serviceIntentFor(cart.toLineItems(selected)), 'fake-test-intent');

// Multi-unit or multi-line WhatsApp claims are never partially imported.
const before = JSON.stringify(cart.readCart());
const one = { productId: kiosk.id, variantId: kiosk.variants[0].id, quantity: 1 };
assert.equal(cart.mergeClaimedLines([one, one]).merged, 0);
assert.equal(JSON.stringify(cart.readCart()), before);
assert.equal(cart.mergeClaimedLines([{ ...one, quantity: 2 }]).merged, 0);
assert.equal(JSON.stringify(cart.readCart()), before);
assert.equal(cart.mergeClaimedLines([one]).merged, 1);
assert.equal(cart.readCart().length, 1);
assert.equal(cart.readCart()[0].productId, kiosk.id);

// No display price, subtotal, amount, currency or other money field goes to checkout.
const outgoing = JSON.stringify(cart.toLineItems());
assert.equal(JSON.parse(outgoing).length, 1);
assert.equal(JSON.parse(outgoing)[0].quantity, 1);
for (const key of ['formattedPrice','unitPrice','amount','currency','price']) {
  assert.equal(outgoing.includes(key), false, key);
}

// A legacy multi-product browser cart is visible for manual correction, not charged.
storage.set('wecare.cart.v1', JSON.stringify([
  { productId: kiosk.id, variantId: kiosk.variants[0].id,
    ref: kiosk.id + ':' + kiosk.variants[0].id, slug: 'kiosk',
    name: 'Kiosk', formattedPrice: '₹24,999.00', quantity: 1 },
  { productId: apparel.id, variantId: apparel.variants[0].id,
    ref: apparel.id + ':' + apparel.variants[0].id, slug: 'merchandise',
    name: 'Merchandise', formattedPrice: '₹1,199.00', quantity: 1 },
]));
assert.equal(cart.readCart().length, 2);
assert.throws(() => cart.toLineItems(), /Buy one product at a time/);
assert.throws(() => cart.toLineItems([{ ref: 'one', productId: kiosk.id,
  slug: 'kiosk', name: 'Kiosk', formattedPrice: '', quantity: 2 }]),
  /Buy one product at a time/);
assert.equal(cart.removeItem(apparel.id + ':' + apparel.variants[0].id).length, 1);
assert.equal(cart.toLineItems().length, 1);

console.log('Short Commerce Part 1 cart runtime: PASS');
