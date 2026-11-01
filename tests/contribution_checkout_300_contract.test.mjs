/**
 * Contribute ₹300 checkout contract across the dock, cart, generated projections
 * and server-side allowlist. The actual price remains ProductsTable-authoritative.
 *
 * Static test only: no payment, customer lookup, external API, or catalogue write.
 * Run: node --test tests/contribution_checkout_300_contract.test.mjs
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const file = p => readFileSync(resolve(root, p), 'utf8');
const config = file('src/config/contribution.ts');
const snap = file('src/content/catalogSnapshot.ts');
const listings = file('src/content/shopProducts.ts');
const server = file('amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py');
const checkout = file('amplify/functions/ecommerce/checkout/handler.py');
const dock = file('src/components/PublicShare.tsx');

test('one contribution variant costs ₹300 in frontend and backend contracts', () => {
  assert.match(config, /variantId:'CNT5Q2M8', rupees:300, paise:30000/);
  assert.match(config, /CONTRIBUTION_AMOUNT_LABEL = '₹300'/);
  assert.match(config, /variantId:'7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a', rupees:300, paise:30000/);
  assert.match(server, /CONTRIBUTION_PRESETS_PAISE: Tuple\[int, \.\.\.\] = \(30000,\)/);
  assert.match(server, /"CNT5Q2M8": 30000/);
  assert.doesNotMatch(config, /₹250|rupees:250|paise:25000/);
  assert.doesNotMatch(server, /"CNT5Q2M8": 25000/);
});

test('catalogue and hidden Shop listing project ₹300 for same current SKU', () => {
  const product = snap.split("id:'24fa0f39-330b-5365-b7eb-9caf27ad37f1'")[1];
  assert.ok(product, 'Contribute product is present in production snapshot');
  const row = product.split('\n  },')[0];
  assert.match(row, /formattedPrice:'₹300\.00', price:'300\.00'/);
  assert.match(row, /variants:\[\{ id:'CNT5Q2M8', label:'Standard', inStock:true \}\]/);
  assert.match(listings, /slug:'contribute'[^\n]*sku:'CNT5Q2M8'[^\n]*formattedPrice:'₹300\.00'/);
});

test('Contribute popup contains exactly Checkout, not Open Orders', () => {
  const pop = dock.split('id="ps-contribute-menu"')[1].split('id="ps-share-menu"')[0];
  assert.match(pop, /Contribute \$\{CONTRIBUTION_AMOUNT_LABEL\}/);
  assert.match(pop, /<p className="ps-menu-sub">Give back<\/p>/);
  assert.match(pop, /onClick=\{ onCheckout \}/);
  assert.match(pop, /shopping_cart_checkout/);
  assert.match(pop, /Review, then pay on WhatsApp/);
  assert.equal((pop.match(/className="ps-menu-item"/g) || []).length, 1);
  assert.doesNotMatch(pop, /Open Orders|href="\/orders\/"/);
  assert.match(dock, /setContribution\( SUGGESTED\.variantId \)/);
  assert.match(dock, /await goToServiceAction\( router, \{/);
  assert.match(dock, /destination: CHECKOUT_PATH/);
});

test('checkout re-reads ProductsTable and exempts contribution from fees', () => {
  assert.match(checkout, /def _contribution_quote\(/);
  assert.match(checkout, /if variant_id not in CONTRIBUTION_CHOICES_PAISE:/);
  assert.match(checkout, /base = native_checkout\.quote_native_cart\(/);
  assert.match(checkout, /quote = checkout_pricing\.exempt_quote\(/);
  assert.match(checkout, /reader = _native_product_reader\(\)/);
  assert.doesNotMatch(dock, /amountPaise: 30000|totalPaise: 30000/);
});
