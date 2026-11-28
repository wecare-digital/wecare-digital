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
  for(const selector of ['.wc-panel','.ps-menu','.orm-menu','.ui-popover.public-checkout-select','.vl-live-search-results','.vl-live-utility-results','.sr-action','.sr-details','.public-search-clear','.orm-more','.sr-journey-action']) assert.ok(theme.includes(selector),selector);
  for(const path of ['src/components/AddressFields.tsx','src/components/cart/CartPage.tsx','src/pages/shop/[slug].tsx'])assert.ok(read(path).includes('menuClassName="public-checkout-select"'),path);
  assert.match(read('src/components/PublicShare.tsx'),/\.ps-action\{[^}]*border-radius:50%/);
});

test('Orders action chooser keeps compact search; F004 uses an upfront bordered receipt summary',()=>{
  const menu=read('src/components/orders/OrderActionsMenu.tsx'),form=read('src/components/orders/SubmitRequestForm.tsx');
  assert.ok(menu.includes('authCountryPanelGeometry( {'));
  assert.ok(menu.includes("window.visualViewport?.addEventListener( 'resize', reposition )"));
  assert.ok(menu.includes('border-radius:var(--public-popover-radius,8px)'));
  assert.ok(menu.includes('data-public-search-field="compact"'));
  assert.ok(menu.includes('border-radius:var(--public-nav-radius)'));
  assert.doesNotMatch(menu,/\.orm-menu\{[^}]*border-radius:(?:18|24)px/);
  assert.ok(form.includes('<section className="sr-pricing" aria-label="Payment summary">'));
  assert.doesNotMatch(form, /<details|<summary/);
  assert.ok(form.includes("serviceByKind( 'SUBMIT_REQUEST' )?.sku"));
  assert.ok(form.includes("label: 'GST', paise: quote.supplyGstPaise + quote.convenienceGstPaise"));
  assert.doesNotMatch(form, /label: 'GST on|label: 'Supply GST/);
  assert.match(form, /\.sr-pricing\{[^}]*border:1px solid var\(--public-hairline\)/);
  const foundation=read('src/styles/public-commerce-foundation.css');
  assert.match(foundation, /\.sr-form textarea\s*\{[^}]*border: 1px solid var\(--public-hairline\)/);
  assert.match(foundation, /\.sr-form textarea\s*\{[^}]*border-radius: var\(--public-hover-radius\)/);
  assert.ok(form.includes('border-radius:var(--public-card-radius)}.sr-actions'));
  const journey=read('src/components/orders/SubmitRequestJourney.tsx');
  assert.ok(journey.includes("call( 'request-service-web-quote' )"));
  assert.ok(journey.includes("if ( !ready || ( paymentState !== 'idle' && paymentState !== 'failed' ) )"));
  const orders=read('src/components/orders/OrdersPage.tsx');
  assert.ok(orders.includes('{ submitOrderNumber ? <SubmitRequestJourney'));
  assert.doesNotMatch(orders, /ord-web-request/);
  assert.ok(form.includes('expectedTotalPaise: quote.totalPayablePaise'));
  assert.ok(read('scripts/verify_checkout_fixture.mjs').includes('mock-orders-request-menu'));
});

test('Orders neutral table headers and icons do not inherit a decorative lime fill',()=>{
  const orders=read('src/components/orders/OrdersPage.tsx'), foundation=read('src/styles/public-commerce-foundation.css'), menu=read('src/components/orders/OrderActionsMenu.tsx');
  assert.match(foundation,/\.ord-list\s*\{\s*border-color: var\(--public-brand-lime\)/);
  assert.match(orders,/\.ord-list\{[^}]*border:1px solid var\(--public-brand-lime\)/);
  assert.match(foundation,/\.ord-th\s*\{\s*background: var\(--public-bg\)/);
  assert.doesNotMatch(orders,/\.ord-th\s*\{[^}]*background:var\(--public-brand-lime\)/);
  assert.match(orders,/\.ord-account-action,\.ord-copy,\.ord-inv\{[^}]*background:transparent/);
  assert.match(menu,/\.orm-more\{[^}]*background:transparent/);
  assert.match(orders,/\.ord-status::before\{[^}]*background:var\(--public-brand-lime\)/);
  const fixture=read('scripts/verify_checkout_fixture.mjs');
  assert.ok(fixture.includes('Orders column headings must be white'));
  assert.ok(fixture.includes('Orders only uses lime on the outer border'));
  assert.ok(fixture.includes('Orders icon controls must be neutral at rest'));
});
