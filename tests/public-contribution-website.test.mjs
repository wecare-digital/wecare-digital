import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CONTRIBUTE_CTA_HREF, CONTRIBUTION_CHOICES } from '../src/config/contribution.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('public contribution points to website review, never automatic WhatsApp payment', () => {
  assert.equal(CONTRIBUTE_CTA_HREF, '/checkout/?contribute=1');
  assert.equal(CONTRIBUTION_CHOICES.length, 1);
  assert.equal(CONTRIBUTION_CHOICES[0].paise, 30000);
  const share = read('src/components/PublicShare.tsx');
  const menu = read('src/lib/customerMenuActions.ts');
  assert.ok(share.includes('href={ CUSTOMER_MENU_HREFS.contribute }'));
  assert.ok(share.includes('A gesture of appreciation'));
  assert.ok(!share.includes("stashCustomerMenuAction( 'contribute' )"));
  assert.ok(menu.includes('contribute: CONTRIBUTE_CTA_HREF'));
  assert.ok(menu.includes("if ( action === 'contribute' ) return { kind: 'blocked' };"));
  assert.ok(!menu.includes('/ecommerce/checkout'));
});

test('Shop and Orders contribution entry use the same non-mutating checkout review', () => {
  const shop = read('src/pages/shop/[slug].tsx');
  const orders = read('src/components/orders/OrderActionsMenu.tsx');
  assert.match(shop, /if \( product\.id === CONTRIBUTION_PRODUCT_ID \) \{[\s\S]*?await router\.push\( CONTRIBUTE_CTA_HREF \);\s*return;\s*\}\s*const chosenVariant/);
  assert.doesNotMatch(shop, /setContribution/);
  assert.match(orders, /label: 'Contribute', subtitle: 'Give back', href: CUSTOMER_MENU_HREFS\.contribute/);
});

test('contribution review protects cart and keeps payment server-priced', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  for (const marker of ["query.get( 'contribute' ) === '1'", 'Replace cart and review contribution','Keep current cart','finishContributionReview( true )','setContribution( choice.variantId )','!contributionReview && !contributionQuoteMismatch',"chosenChannel === 'whatsapp' && currentItems.some( isContributionItem )",'expectedTotalPaise !== CONTRIBUTION_CHOICES[0]?.paise','{ !hasContribution && (',"void proceed( 'website' )",'VERIFY_CHECKOUT_URL','!ready || contributionReview || items.length === 0']) assert.ok(cart.includes(marker), marker);
});

test('a fixed contribution can be removed or repaired to one, never increased', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  assert.match(cart, /if \( item && isContributionItem\( item \) && quantity !== 1 \) return;/);
  const fixedBranch = /\{ isContributionItem\( item \) \? \(([\s\S]*?)\) : \(\s*<div className="cart-qty" role="group"/.exec(cart);
  assert.ok(fixedBranch, 'contribution has separate fixed-quantity controls');
  assert.match(fixedBranch[1], /item\.quantity !== 1[\s\S]*?changeQuantity\( item\.ref, 1 \)/);
  assert.doesNotMatch(fixedBranch[1], /item\.quantity\s*[+-]/);
  assert.match(cart, /className="cart-remove"[\s\S]*?onClick=\{ \(\) => drop\( item\.ref \) \}/);
});

test('opening contribution review resets the old basket quote and notice', () => {
  const source = read('src/components/cart/CartPage.tsx');
  assert.match(source, /if \( !ready \|\| contributionReview \|\| items\.length === 0 \|\| cartUnavailable \) \{\s*setQuote\( null \);\s*setQuoteFor\( '' \);\s*setQuoteNotice\( '' \);/);
});
