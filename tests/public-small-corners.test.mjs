import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=path=>readFileSync(new URL('../'+path,import.meta.url),'utf8');

test('non-Home public corners are scoped at root, including portalled dropdowns',()=>{
  const app=read('src/pages/_app.tsx'), tokens=read('src/styles/tokens.css'), theme=read('src/styles/public-button-theme.css');
  assert.ok(app.includes("data-public-auth-button-theme={ router.pathname === '/' ? undefined : 'active' }"));
  assert.ok(tokens.includes('--public-hover-radius: 13px;'));
  assert.ok(tokens.includes('--public-card-radius: 14px;'));
  assert.match(theme,/:root:has\(\[data-public-auth-button-theme="active"\]\)\s*\{[^}]*--public-hover-radius: 6px;[^}]*--public-card-radius: 8px;[^}]*--public-popover-radius: 8px;/);
  for(const selector of ['.nav-menu','.wc-panel','.ps-menu','.orm-menu','.ui-popover','.vl-live-search-results','.vl-live-utility-results','.sr-form','.ord-list','.co-card','.sf-card']) assert.ok(theme.includes(selector),selector);
  assert.ok(theme.includes('.public-search-clear, .orm-more, .sr-journey-action'));
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
