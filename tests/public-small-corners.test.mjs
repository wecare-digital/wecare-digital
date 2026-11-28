import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=path=>readFileSync(new URL('../'+path,import.meta.url),'utf8');

test('non-Home component-specific radius tokens leave original card and hover tokens intact',()=>{
  const app=read('src/pages/_app.tsx'), tokens=read('src/styles/tokens.css'), theme=read('src/styles/public-button-theme.css');
  assert.ok(app.includes("data-public-auth-button-theme={ router.pathname === '/' ? undefined : 'active' }"));
  assert.ok(tokens.includes('--public-hover-radius: 13px;'));
  assert.ok(tokens.includes('--public-card-radius: 14px;'));
  assert.match(theme,/:root:has\(\[data-public-auth-button-theme="active"\]\)\s*\{[^}]*--public-action-radius: 6px;[^}]*--public-search-radius: 6px;[^}]*--public-option-radius: 6px;[^}]*--public-popover-radius: 8px;/);
  assert.doesNotMatch(theme,/--public-card-radius\s*:|--public-hover-radius:\s*6px/);
  for(const selector of ['.nav-menu','.wc-panel','.ps-menu','.orm-menu','.ui-popover.public-checkout-select','.vl-live-search-results','.vl-live-utility-results','.sr-action','.sr-details','.public-search-clear','.orm-more','.sr-journey-action']) assert.ok(theme.includes(selector),selector);
  for(const path of ['src/components/AddressFields.tsx','src/components/cart/CartPage.tsx','src/pages/shop/[slug].tsx'])assert.ok(read(path).includes('menuClassName="public-checkout-select"'),path);
  assert.match(read('src/components/PublicShare.tsx'),/\.ps-action\{[^}]*border-radius:50%/);
});

test('Orders action chooser and Submit Request price details use the smaller panel and shared search',()=>{
  const menu=read('src/components/orders/OrderActionsMenu.tsx'),form=read('src/components/orders/SubmitRequestForm.tsx');
  assert.ok(menu.includes('authCountryPanelGeometry( {'));
  assert.ok(menu.includes("window.visualViewport?.addEventListener( 'resize', reposition )"));
  assert.ok(menu.includes('border-radius:var(--public-popover-radius,8px)'));
  assert.ok(menu.includes('data-public-search-field="compact"'));
  assert.ok(menu.includes('border-radius:var(--public-nav-radius)'));
  assert.doesNotMatch(menu,/\.orm-menu\{[^}]*border-radius:(?:18|24)px/);
  assert.ok(form.includes('<summary className="sr-details">'));
  assert.ok(form.includes('details[open] .sr-details svg{transform:rotate(180deg)}'));
  assert.ok(form.includes('.sr-details:focus-visible{outline:2px solid var(--public-brand-green)'));
  assert.ok(form.includes('border-radius:var(--public-card-radius)}.sr-actions'));
  assert.ok(form.includes('expectedTotalPaise: quote.totalPayablePaise'));
  assert.ok(read('scripts/verify_checkout_fixture.mjs').includes('mock-orders-request-menu'));
});

test('Orders neutral table headers and icons do not inherit a decorative lime fill',()=>{
  const orders=read('src/components/orders/OrdersPage.tsx'), foundation=read('src/styles/public-commerce-foundation.css'), menu=read('src/components/orders/OrderActionsMenu.tsx');
  assert.match(foundation,/\.ord-th\s*\{\s*background: var\(--public-bg\)/);
  assert.doesNotMatch(orders,/\.ord-th\s*\{[^}]*background:var\(--public-brand-lime\)/);
  assert.match(orders,/\.ord-account-action,\.ord-copy,\.ord-inv\{[^}]*background:transparent/);
  assert.match(menu,/\.orm-more\{[^}]*background:transparent/);
  assert.match(orders,/\.ord-status::before\{[^}]*background:var\(--public-brand-lime\)/);
  const fixture=read('scripts/verify_checkout_fixture.mjs');
  assert.ok(fixture.includes('Orders column headings must be white'));
  assert.ok(fixture.includes('Orders icon controls must be neutral at rest'));
});
