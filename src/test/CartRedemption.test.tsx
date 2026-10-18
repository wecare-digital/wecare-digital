import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The public cart deliberately exposes redemption CAPABILITY STATUS only.
 *
 * Delight is not seeded in the live coupon authority and gift-card payment is not provisioned,
 * so the browser must not render an Apply/Remove workflow or call a redemption endpoint. When
 * checkout owns pricing + reservation + settlement for those instruments, this test should be
 * replaced together with that real payment path rather than weakened around a UI-only control.
 */
describe( 'Cart redemption capability is status-only', () => {
  const source = readFileSync(
    resolve( process.cwd(), 'src/components/cart/CartPage.tsx' ),
    'utf8',
  );

  it( 'shows truthful Delight and gift-card availability copy', () => {
    expect( source ).toContain( '<strong>Delight</strong>' );
    expect( source ).toContain(
      'Temporarily unavailable. No discount has been applied to this cart.',
    );
    expect( source ).toContain( '<strong>Gift cards</strong>' );
    expect( source ).toContain(
      'Not available yet. A gift-card code cannot be used for payment right now.',
    );
  } );

  it( 'has no browser redemption endpoint or Apply/Remove form', () => {
    expect( source ).not.toContain( 'REDEMPTION_URL' );
    expect( source ).not.toContain( '/ecommerce/redemption' );
    expect( source ).not.toContain( 'Coupon code' );
    expect( source ).not.toContain( 'Gift-card code' );
    expect( source ).not.toContain( 'COUPON_MESSAGES' );
  } );

  it( 'keeps the status panel out of contribution baskets', () => {
    expect( source ).toContain(
      '{ !items.some( isContributionItem ) && <RedemptionPanel /> }',
    );
  } );

  it( 'does not name or embed a third-party gift-card provider', () => {
    const lower = source.toLowerCase();
    expect( lower ).not.toContain( 'gift up' );
    expect( lower ).not.toContain( 'giftup' );
  } );
} );
