import { describe, expect, it } from 'vitest';
import { formatPaiseINR } from '../lib/money';

/**
 * The cases that matter are the ones a division would get wrong or a default would hide.
 *
 * `100 -> ₹1.00` is the named regression: the owner is testing the Rs.1 case elsewhere, and a
 * formatter that drops the trailing zeros or divides its way to 0.9999999 fails exactly there.
 * `10000000 -> ₹1,00,000.00` is the Indian-grouping case - `100,000.00` would be the en-US
 * answer and is wrong for this audience.
 */
describe( 'formatPaiseINR', () => {
  it.each( [
    [ 0, '₹0.00' ],
    [ 1, '₹0.01' ],
    [ 5, '₹0.05' ],
    [ 99, '₹0.99' ],
    [ 100, '₹1.00' ],
    [ 121481, '₹1,214.81' ],
    [ 10000000, '₹1,00,000.00' ],
  ] )( 'formats %i paise as %s', ( paise, expected ) => {
    expect( formatPaiseINR( paise, 'INR' ) ).toBe( expected );
  } );

  it( 'groups by lakh rather than by thousand', () => {
    // Stated separately from the table because this is the whole reason the locale is pinned.
    expect( formatPaiseINR( 10000000, 'INR' ) ).not.toContain( '100,000' );
  } );

  it( 'refuses a null amount rather than printing a zero', () => {
    expect( formatPaiseINR( null, 'INR' ) ).toBe( '' );
  } );

  it( 'refuses a non-integer, because paise are whole', () => {
    expect( formatPaiseINR( 1.5, 'INR' ) ).toBe( '' );
    expect( formatPaiseINR( Number.NaN, 'INR' ) ).toBe( '' );
  } );

  it( 'refuses a negative amount', () => {
    expect( formatPaiseINR( -100, 'INR' ) ).toBe( '' );
  } );

  it( 'refuses a foreign currency rather than formatting it behind a rupee sign', () => {
    // The currency is compared, not defaulted. This is the behaviour formatters.ts:47 lacks.
    expect( formatPaiseINR( 121481, 'USD' ) ).toBe( '' );
    expect( formatPaiseINR( 121481, '' ) ).toBe( '' );
    expect( formatPaiseINR( 121481, 'inr' ) ).toBe( '' );
  } );
} );
