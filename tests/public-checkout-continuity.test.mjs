import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseCheckoutQuote } from '../src/lib/checkoutQuote.ts';

const quote = () => ({ status: 'QUOTE_READY', quote: { currency: 'INR', items: [{ name: 'Contribution', quantity: 1, unitPricePaise: 23541, totalPaise: 23541 }], charges: { merchandisePaise: 23541, supplyGstPaise: 4237, discountPaise: 138, deliveryPaise: 1500, convenienceFeePaise: 729, convenienceGstPaise: 131, totalPaise: 30000 } } });
test('server-owned contribution quote reconciles to INR 300, rejects mismatch and malformed quantity', () => {
  assert.equal(parseCheckoutQuote(quote())?.charges.totalPaise, 30000);
  const mismatch = quote(); mismatch.quote.charges.totalPaise = 29999;
  assert.equal(parseCheckoutQuote(mismatch), null);
  const quantity = quote(); quantity.quote.items[0].quantity = 2;
  assert.equal(parseCheckoutQuote(quantity), null);
});
const cart = readFileSync(new URL('../src/components/cart/CartPage.tsx', import.meta.url), 'utf8');
const profile = readFileSync(new URL('../src/components/CheckoutProfile.tsx', import.meta.url), 'utf8');
test('non-shipping checkout has explicit name-only recovery and expired-session action', () => {
  assert.ok(cart.includes("cartRequiresDelivery( items ) ? 'create' : 'name'"));
  assert.ok(cart.includes('allowIdentityBootstrap={ !cartRequiresDelivery( items ) }'));
  assert.ok(profile.includes("reply.code === 'ADDRESS_REQUIRED'"));
  assert.ok(profile.includes('const bootstrap = await save( {} )'));
  assert.ok(cart.includes('onSessionExpired={ () => {'));
});
test('website payment preserves modal and status recovery guards', () => {
  assert.ok(cart.includes('disabled={ busy || modalOpen || !quoteReady }'));
  assert.ok(cart.includes('goToCheckoutStatus( pendingAttempt )'));
  assert.ok(cart.includes('modalOpenRef.current || proceedInFlightRef.current || railTerminalRef.current'));
  assert.ok(cart.includes('expectedTotalPaise !== CONTRIBUTION_CHOICES[0]?.paise'));
});
