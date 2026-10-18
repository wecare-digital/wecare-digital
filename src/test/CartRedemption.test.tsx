import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The public cart STATES the one always-on discount, and computes nothing.
 *
 * There is no coupon system and no gift-card system any more. Delight is a fixed owner policy
 * (0.5% of the order, capped at ₹50) the server applies at checkout — no code, no Apply/Remove
 * workflow, no redemption endpoint from the browser. The panel shows the policy as an ACTIVE
 * lime-green pill (not an amber "unavailable" placeholder) and never a per-cart rupee figure.
 */
describe( 'Cart states the always-on Delight discount, status-only', () => {
  const source = readFileSync(
    resolve( process.cwd(), 'src/components/cart/CartPage.tsx' ),
    'utf8',
  );

  it( 'shows the active lime-green Delight pill and no retired gift-card surface', () => {
    expect( source ).toContain( '<strong>Delight</strong>' );
    expect( source ).toContain(
      'Applied automatically at checkout. Every order gets a little back, on us.',
    );
    // Active green, not the old amber "temporarily unavailable" placeholder.
    expect( source ).toContain( '.cart-capability-delight{background:#ecfdf3}' );
    expect( source ).not.toContain(
      'Temporarily unavailable. No discount has been applied to this cart.',
    );
    expect( source ).not.toContain( '<strong>Gift cards</strong>' );
    expect( source ).not.toContain( 'cart-capability-gift' );
  } );

  it( 'has no browser redemption endpoint, Apply/Remove form, or code field', () => {
    expect( source ).not.toContain( 'REDEMPTION_URL' );
    expect( source ).not.toContain( '/ecommerce/redemption' );
    expect( source ).not.toContain( 'Coupon code' );
    expect( source ).not.toContain( 'Gift-card code' );
    expect( source ).not.toContain( 'COUPON_MESSAGES' );
  } );

  it( 'keeps the Delight panel out of contribution baskets', () => {
    expect( source ).toContain(
      '{ !items.some( isContributionItem ) && <RedemptionPanel /> }',
    );
  } );

  it( 'does not name or embed a retired gift-card provider', () => {
    const lower = source.toLowerCase();
    expect( lower ).not.toContain( 'gift up' );
    expect( lower ).not.toContain( 'giftup' );
    expect( lower ).not.toContain( 'gift-card code' );
  } );
} );
