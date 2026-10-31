/**
 * Public Orders more-actions menu: Referral and Contribute after Subscribe.
 *
 * Static checks: no backend sends, customer data, or external network calls.
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
const contribution = read('src/config/contribution.ts');
const publicShare = read('src/components/PublicShare.tsx');

test('More Actions displays Referral and Contribute immediately after Subscribe', () => {
  const list = menu.match(/const OTHER_ACTIONS: readonly Action\[\] = \[([\s\S]*?)\];/);
  assert.ok(list, 'Other actions list is present');
  const labels = [...list[1].matchAll(/label: '([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(labels, ['Leave Review', 'Subscribe', 'Referral', 'Contribute']);
  assert.match(list[1], /label: 'Referral', subtitle: 'Refer & earn'/);
  assert.match(list[1], /label: 'Contribute', subtitle: 'Give back', href: CHECKOUT_PATH/);
});

test('Referral reuses the existing public header WhatsApp link', () => {
  const referral = header.match(/label: 'Referral', href: '([^']+)'/);
  assert.ok(referral, 'Referral already exists in the public header');
  assert.ok(menu.includes("href: '" + referral[1] + "'"));
  assert.match(menu, /icon: 'referral', keywords: '[^']+', external: true/);
});

test('Contribute uses a rupee-shaped vector icon', () => {
  assert.match(menu, /rupee:\s*\{[\s\S]*?path: 'M6 3h12M6 8h12m-12 5 8\.5 8/);
  assert.match(menu, /icon: 'rupee', keywords: '[^']+'/);
  assert.match(menu, /<button key=\{ action.label \} type="button"\s+className="orm-item orm-contribute-item"/);
  assert.match(menu, /onClick=\{ onContribute \}/);
});

test('Contribute follows the existing gated contribution checkout, not a WhatsApp invite', () => {
  assert.match(menu, /setContribution\( choice\.variantId \)/);
  assert.match(menu, /await goToServiceAction\( router, \{/);
  assert.match(menu, /destination: CHECKOUT_PATH/);
  assert.match(menu, /channel: 'whatsapp'/);
  assert.match(menu, /productId: CONTRIBUTION_PRODUCT_ID/);
  assert.match(menu, /label: 'Contribute'/);
  assert.match(menu, /contributionError &&/);
  assert.match(publicShare, /setContribution\( SUGGESTED\.variantId \)/);
  assert.match(publicShare, /await goToServiceAction\( router, \{/);
  assert.match(contribution, /CONTRIBUTION_CHOICES/);
  const contributeFn = menu.split('const onContribute = () => {')[1].split('\n\n  return (')[0];
  assert.doesNotMatch(contributeFn, /onInvite\(|sendCustomerMenuAction\(|payment\s*\(/);
});

test('Existing Leave Review and Subscribe template-send dispatch is preserved', () => {
  assert.match(menu, /const sendAction = menuActionForLabel\( action.label \)/);
  assert.match(menu, /if \( sendAction \) \{[\s\S]*?onInvite\( sendAction \)/);
  assert.match(menu, /if \( !action\.external && action\.href === '\/orders\/'/);
});
