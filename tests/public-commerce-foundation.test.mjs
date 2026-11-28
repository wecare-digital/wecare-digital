import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const css = read('src/styles/public-commerce-foundation.css');
const gate = ':root:has([data-public-auth-button-theme="active"])';

test('commerce presentation never reaches Home or workspace', () => {
  const app = read('src/pages/_app.tsx');
  assert.ok(app.includes("import '../styles/public-commerce-foundation.css';"));
  assert.ok(app.includes("data-public-auth-button-theme={ router.pathname === '/' ? undefined : 'active' }"));
  assert.ok(read('src/components/public/CustomerVaultChrome.tsx').includes('data-public-auth-button-theme="active"'));
  const selectors = css.replace(/\/\*[\s\S]*?\*\//g, '').split(/[{}]/).map(s => s.trim()).filter(s => s.startsWith(':'));
  assert.ok(selectors.length > 30);
  for (const selector of selectors) {
    let depth = 0, start = 0;
    for (let i = 0; i < selector.length; i++) {
      if (selector[i] === '(') depth++;
      if (selector[i] === ')') depth--;
      if (selector[i] === ',' && depth === 0) {
        assert.ok(selector.slice(start, i).trim().startsWith(gate), selector);
        start = i + 1;
      }
    }
    assert.ok(selector.slice(start).trim().startsWith(gate), selector);
  }
  assert.doesNotMatch(css, /\.home-close-cta|\.ps-action|\.cb-cta/);
});

test('public commerce fields inherit Auth focus, accessible pickers and mobile sizing', () => {
  const auth = read('src/pages/auth.tsx');
  assert.match(auth, /\.code-control:focus\{[^}]*box-shadow:0 2px 0 0 var\(--public-brand-green\)/);
  for (const token of ['min-block-size: 54px','--control-h: 52px','var(--public-mobile-form-font-size)','border-block-end: 1px solid var(--public-hairline)','box-shadow: 0 2px 0 0 var(--public-brand-green)',':focus-visible','outline: 2px solid Highlight','prefers-reduced-motion: reduce','[aria-invalid="true"]','[aria-disabled="true"]','--control-arrow-pad','--control-box: 20px']) assert.ok(css.includes(token), token);
  for (const [path, marker] of [
    ['src/components/CheckoutProfile.tsx','checkout-profile-grid'],
    ['src/components/AddressFields.tsx','address-fields'],
    ['src/components/cart/CartPage.tsx','cart-option'],
    ['src/pages/shop/[slug].tsx','shopd-options'],
    ['src/components/public/AppointmentPlanner.tsx','data-public-field-group="appointment"'],
    ['src/components/orders/SubmitRequestForm.tsx','sr-form']
  ]) {
    assert.ok(read(path).includes(marker), path);
    assert.ok(css.includes(marker), marker);
  }
  const address = read('src/components/AddressFields.tsx');
  assert.ok(address.includes('padding-inline-end:var(--control-arrow-pad) !important'));
  assert.ok(address.includes('background-color:transparent !important'));
  assert.doesNotMatch(address, /background:transparent !important/);
  assert.doesNotMatch(read('src/styles/public-button-theme.css'),/button:not\(/);
  assert.ok(read('src/styles/form-controls.css').includes('--control-tick'));
});

test('checkout summary, verified totals, status, Orders and Vault have bounded layouts', () => {
  for (const [path, marker] of [
    ['src/components/cart/CartPage.tsx','cart-review-grid'],
    ['src/components/cart/CheckoutReceipt.tsx','receipt-total'],
    ['src/pages/checkout/status.tsx','co-facts'],
    ['src/components/orders/OrdersPage.tsx','ord-tablewrap'],
    ['src/components/get/GetPage.tsx','sf-payment-total'],
    ['src/components/orders/SubmitRequestForm.tsx','sr-total']
  ]) {
    assert.ok(read(path).includes(marker), path);
    assert.ok(css.includes('.' + marker), marker);
  }
  for (const token of ['grid-template-columns: minmax(0,1fr)','overflow-wrap: anywhere','overflow-x: auto','font-variant-numeric: tabular-nums','@media (max-width: 279px)','var(--public-card-padding-reflow)']) assert.ok(css.includes(token), token);
  const cart = read('src/components/cart/CartPage.tsx');
  assert.ok(cart.includes('disabled={ busy || modalOpen || !quoteReady }'));
  assert.ok(cart.includes('goToCheckoutStatus( pendingAttempt.id, pendingAttempt.basket )'));
  assert.match(cart, /\.cart-quiet-refresh:disabled\{color:var\(--text-muted\);opacity:1/);
  const receipt = read('src/components/cart/CheckoutReceipt.tsx');
  for (const marker of ['charges.merchandisePaise','charges.supplyGstPaise','charges.discountPaise','charges.deliveryPaise','charges.convenienceFeePaise','charges.convenienceGstPaise','charges.totalPaise']) assert.ok(receipt.includes(marker));
  const orders = read('src/components/orders/OrdersPage.tsx');
  assert.ok(orders.includes('<th scope="col"'));
  assert.ok(orders.includes('<th scope="row"'));
});
