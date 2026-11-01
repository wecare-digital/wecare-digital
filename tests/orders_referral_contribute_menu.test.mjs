/**
 * Public/customer Orders entrypoints: Referral and Contribute navigation,
 * one-time authenticated Subscribe template, and unchanged Leave Review.
 *
 * Static source tests: no WhatsApp sends, payments, or customer data.
 * Run: node --test tests/orders_referral_contribute_menu.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');
const menu = read('src/components/orders/OrderActionsMenu.tsx');
const header = read('src/components/Header.tsx');
const publicShare = read('src/components/PublicShare.tsx');
const customerActions = read('src/lib/customerMenuActions.ts');
const orders = read('src/components/orders/OrdersPage.tsx');

test('Orders action order, subtexts, rupee icon and referral link are preserved', () => {
  const list = menu.match(/const OTHER_ACTIONS: readonly Action\[\] = \[([\s\S]*?)\];/);
  assert.ok(list, 'Other actions list is present');
  const labels = [...list[1].matchAll(/label: '([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(labels, ['Leave Review', 'Subscribe', 'Referral', 'Contribute']);
  assert.match(list[1], /label: 'Referral', subtitle: 'Refer & earn', href: '\/orders\/'/);
  assert.match(list[1], /label: 'Contribute', subtitle: 'Give back', href: '\/orders\/'/);
  assert.match(menu, /rupee:\s*\{[\s\S]*?path: 'M6 3h12M6 8h12m-12 5 8\.5 8/);
  assert.match(list[1], /icon: 'rupee', keywords: '[^']+'/);
  assert.match(list[1], /icon: 'referral', keywords: '[^']+'/);
});

test('Header and Orders referral navigate to authenticated Orders, not external WhatsApp', () => {
  assert.match(header, /label: 'Referral', href: '\/orders\/', match: '\/orders'/);
  assert.doesNotMatch(header, /label: 'Referral', href: 'https:\/\/wa\.me/);
  assert.match(menu, /const sendAction = menuActionForLabel\( action\.label \)/);
  assert.match(menu, /if \( !action\.external && action\.href === '\/orders\/'/);
  assert.doesNotMatch(menu, /contributionBusy|onContribute|setContribution\(/);
  assert.doesNotMatch(menu, /goToServiceAction\(|CHECKOUT_PATH/);
});

test('Contribute dock subtitle is Give back; entry opens Orders without cart or checkout', () => {
  assert.match(publicShare, /<p className="ps-menu-sub">Give back<\/p>/);
  assert.match(publicShare, /className="ps-menu-title contribute-label">Contribute<\/div>/);
  assert.match(publicShare, /href="\/orders\/"\s+aria-label="Open Orders to continue with Contribute"/);
  assert.match(publicShare, /<span className="ps-menu-name">Open Orders<\/span>/);
  assert.match(publicShare, /<span className="ps-menu-note">Give back<\/span>/);
  assert.match(publicShare, /symbol\( 'currency_rupee' \)/);
  assert.doesNotMatch(publicShare, /Review it in your cart|Review, then pay on WhatsApp/);
  assert.doesNotMatch(publicShare, /setContribution\(|goToServiceAction\(|onCheckout/);
  assert.doesNotMatch(publicShare, /<a[^>]+href="\/checkout\//);
});

test('Subscribe bell queues the one-time authenticated send only on primary activation', () => {
  assert.match(publicShare, /href=\{ CUSTOMER_MENU_HREFS\.subscribe \}/);
  assert.match(publicShare, /if \( isPrimaryMenuActivation\( event \) \) stashCustomerMenuAction\( 'subscribe' \)/);
  assert.doesNotMatch(publicShare, /SUBSCRIBE_CTA_HREF|target="_blank"\s+rel="noopener noreferrer"\s+aria-label="Subscribe/);
  assert.match(customerActions, /subscribe: '\/orders\/'/);
  assert.match(customerActions, /window\.sessionStorage\.setItem\( PENDING_KEY/);
  assert.match(customerActions, /window\.sessionStorage\.removeItem\( PENDING_KEY \)/);
  assert.match(customerActions, /const backendAction = action === 'subscribe' \? 'sendProfileUpdate' : 'sendLeaveReview'/);
  assert.match(orders, /const serviceAction = takeCustomerMenuAction\(\)/);
  assert.match(orders, /await sendCustomerMenuAction\( serviceAction, session\.accessToken \)/);
});

test('Subscribe and Leave Review remain the only template sends, and retry stays explicit', () => {
  assert.match(header, /const sendAction = menuActionForLabel\( link\.label \)/);
  assert.match(header, /stashCustomerMenuAction\( sendAction \)/);
  assert.match(menu, /onInvite\( sendAction \)/);
  assert.match(customerActions, /if \( label === 'Subscribe' \) return 'subscribe'/);
  assert.match(customerActions, /if \( label === 'Leave Review' \) return 'leave-review'/);
  assert.match(customerActions, /return null/);
  assert.doesNotMatch(publicShare, /sendCustomerMenuAction\(/);
  assert.doesNotMatch(menu, /sendCustomerMenuAction\(/);
});
