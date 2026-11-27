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
  assert.ok(share.includes('Review, then pay on website'));
  assert.ok(!share.includes("stashCustomerMenuAction( 'contribute' )"));
  assert.ok(menu.includes('contribute: CONTRIBUTE_CTA_HREF'));
  assert.ok(menu.includes("if ( action === 'contribute' ) return { kind: 'blocked' };"));
  assert.ok(!menu.includes('/ecommerce/checkout'));
});

test('contribution review protects cart and keeps payment server-priced', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  for (const marker of ["query.get( 'contribute' ) === '1'", 'Replace cart and review contribution','Keep current cart','finishContributionReview( true )','setContribution( choice.variantId )','!contributionReview && !contributionQuoteMismatch',"chosenChannel === 'whatsapp' && currentItems.some( isContributionItem )",'expectedTotalPaise !== CONTRIBUTION_CHOICES[0]?.paise','{ !hasContribution && (',"void proceed( 'website' )",'VERIFY_CHECKOUT_URL']) assert.ok(cart.includes(marker), marker);
});
