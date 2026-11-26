import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transformSync } from 'esbuild';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
async function load(path) {
  const { code } = transformSync(read(path), { loader: 'ts', format: 'esm' });
  return import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
}
const keys = ['disclaimer', 'refunds', 'returns', 'shipping'];
const filler = /no fulfilment (?:starts|applies)|nothing (?:on|in|is) |no payment is taken (?:here|on this page)|above controls|server verifies|confirmed order controls|No cash or original-payment-method refund/i;
function check(copy) {
  assert.ok(copy);
  assert.deepEqual(Object.keys(copy).sort(), keys);
  for (const value of Object.values(copy)) {
    assert.ok(typeof value === 'string' && value.trim().length > 0);
    assert.doesNotMatch(value, filler);
  }
}
test('all registered public routes receive a policy or own an embedded disclosure', async () => {
  const { publicPolicyDetailsForRoute: resolve, EMBEDDED_POLICY_ROUTES: embedded, ORDERS_POLICY_DETAILS: orders } = await load('src/content/publicPolicyDetails.ts');
  const { pages } = JSON.parse(read('config/public-pages.json'));
  for (const path of [...pages.map(page => page.path), '/auth', '/vault', '/checkout', '/checkout/status', '/checkout/success', '/get', '/blog/page/[page]', '/blog/topic/[topic]', '/blog/topic/[topic]/page/[page]', '/post/[slug]', '/shop/page/[page]']) {
    if (embedded.has(path)) assert.equal(resolve(path), null, path);
    else check(resolve(path));
  }
  check(orders);
  assert.equal(resolve('/404'), null);
  assert.equal(resolve('/workspace'), null);
  assert.equal(resolve('/shop/[slug]'), null);
  assert.match(resolve('/post/[slug]').refunds, /contributions/i);
  assert.match(resolve('/niji-setu/parichay').disclaimer, /planned/);
  assert.match(resolve('/').refunds, /30 calendar days/);
});
test('catalogue policies cover every SKU and provide a safe fallback for a new item', async () => {
  const { PRODUCT_SKU_BY_SLUG, productPolicyCopy, PRODUCT_REFUNDS } = await load('src/content/productCommerce.ts');
  assert.match(PRODUCT_REFUNDS, /store credit valid for 30 calendar days/);
  assert.match(PRODUCT_REFUNDS, /Monetary refunds are provided where required by law/);
  for (const slug of [...Object.keys(PRODUCT_SKU_BY_SLUG), 'ritual-guru-ritva', 'new-catalog-item']) check(productPolicyCopy(slug, slug));
  assert.match(productPolicyCopy('sehat', 'Arogya Yatra').disclaimer, /not medical advice/);
  assert.match(productPolicyCopy('ritual-guru-diy-puja-kit', 'Samagri').returns, /Statutory remedies/);
  assert.match(productPolicyCopy('contribute', 'Contribute').refunds, /duplicate/);
  assert.doesNotMatch(productPolicyCopy('contribute', 'Contribute').refunds, /store credit/);
  assert.match(read('src/pages/relay-os/index.tsx'), /refunds=\{ GRAHAK_POLICY\.refunds \}/);
  assert.match(read('src/pages/shop/[slug].tsx'), /const policy = productPolicyCopy\( product\.slug, product\.name \)/);
  assert.match(read('src/components/orders/OrdersPage.tsx'), /<section className="ord-policy-section" aria-label="Order policies">/);
});
