import { beforeEach, describe, expect, it } from 'vitest';
import * as cart from '../lib/cart';
import { NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_PRODUCT_ID } from '../config/services';
import type { ShopProduct } from '../content/shop';

const [ SUBMIT, AMEND ] = SERVICE_CHOICES;
const INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f';
/**
 * The LIVE Wix price, injected. `setServiceLine` takes the line paise explicitly since
 * 2026-10-08: `src/config/services.ts` no longer declares a price (owner decision — a price is
 * editable in Wix with no deploy), so the cart row's displayed amount has to come from the live
 * figure the buy box resolved. One constant here rather than a number per call, and deliberately
 * NOT 9900: a figure that happens to match the old constant could pass for the wrong reason.
 */
const LIVE_PAISE = 14900;

const OTHER_INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60';
const KIOSK: ShopProduct = {
  id: 'wix-abc-123', name: 'Kiosk', slug: 'kiosk', formattedPrice: '₹24,999.00',
  price: '24999.00', currency: 'INR', inStock: true, tagline: 't', body: [],
};

beforeEach( () => { window.localStorage.clear(); } );

describe( 'the service cart line (Phase O-1)', () => {
  it( 'sets ONE service line at quantity 1, replacing another', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    cart.setServiceLine( AMEND.variantId, OTHER_INTENT, LIVE_PAISE );
    const services = cart.readCart().filter( cart.isServiceItem );
    expect( services ).toHaveLength( 1 );
    expect( services[ 0 ] ).toMatchObject( {
      productId: SERVICES_PRODUCT_ID, variantId: AMEND.variantId, quantity: 1,
      name: AMEND.label, formattedPrice: '₹149.00', slug: '',
    } );
  } );

  it( 'stores the intent pointer separately from the cart items', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    expect( window.localStorage.getItem( 'wecare.cart.v1' ) ).not.toContain( INTENT );
    expect( JSON.parse( window.localStorage.getItem( 'wecare.cart.serviceIntent.v1' )! ) )
      .toEqual( { variantId: SUBMIT.variantId, intentId: INTENT } );
  } );

  it( 'answers the intent only for the same single service variant', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    expect( cart.serviceIntentFor( cart.toLineItems() ) ).toBe( INTENT );
    const swapped = cart.toLineItems().map( line => ( {
      ...line,
      catalogReference: { ...line.catalogReference, options: { variantId: AMEND.variantId } },
    } ) );
    expect( cart.serviceIntentFor( swapped ) ).toBe( '' );
    expect( cart.serviceIntentFor( [] ) ).toBe( '' );
    window.localStorage.setItem( 'wecare.cart.serviceIntent.v1', '{not json' );
    expect( cart.serviceIntentFor( cart.toLineItems() ) ).toBe( '' );
  } );

  it( 'accepts all four service variants, one at a time', () => {
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toHaveLength( 0 );
    for ( const choice of SERVICE_CHOICES )
    {
      cart.setServiceLine( choice.variantId, INTENT, LIVE_PAISE );
      const services = cart.readCart().filter( cart.isServiceItem );
      expect( services ).toHaveLength( 1 );
      expect( services[ 0 ] ).toMatchObject( {
        variantId: choice.variantId, name: choice.label, quantity: 1,
        // The LIVE figure, formatted by integer division and modulo. Identical across the four
        // because the price is no longer a per-choice constant: it is whatever Wix says, and the
        // row simply renders what it was handed.
        formattedPrice: '₹149.00',
      } );
    }
  } );

  it( 'refuses a GUID that is not a variant, and a missing intent, writing nothing', () => {
    cart.setServiceLine( 'db166bc8-a763-41ec-9f65-0f718f18155b', INTENT, LIVE_PAISE );
    cart.setServiceLine( SUBMIT.variantId, '', LIVE_PAISE );
    expect( cart.readCart() ).toEqual( [] );
  } );

  it( 'refuses a line with no usable live price, writing nothing', () => {
    // FAIL CLOSED. There is no committed figure to fall back on, so a row with no amount Wix
    // priced is not written at all rather than written with an invented one.
    for ( const paise of [ 0, -1, 99.5, Number.NaN, Number.POSITIVE_INFINITY ] )
    {
      cart.setServiceLine( SUBMIT.variantId, INTENT, paise );
      expect( cart.readCart() ).toEqual( [] );
    }
  } );

  it( 'renders a price with non-zero paise without float division', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, 123450 );
    expect( cart.readCart()[ 0 ].formattedPrice ).toBe( '₹1234.50' );
    cart.setServiceLine( SUBMIT.variantId, INTENT, 1 );
    expect( cart.readCart()[ 0 ].formattedPrice ).toBe( '₹0.01' );
  } );

  it( 'keeps toLineItems price-free', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    const wire = JSON.stringify( cart.toLineItems() );
    expect( wire ).not.toMatch( /price|amount|currency|₹/i );
    expect( wire ).not.toContain( String( LIVE_PAISE ) );
    expect( cart.toLineItems() ).toEqual( [ {
      catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e',
        catalogItemId: SERVICES_PRODUCT_ID, options: { variantId: SUBMIT.variantId } },
      quantity: 1,
    } ] );
  } );

  it( 'survives the readCart reconcile', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    expect( cart.readCart() ).toHaveLength( 1 );
    expect( cart.readCart()[ 0 ].variantId ).toBe( SUBMIT.variantId );
  } );

  it( 'needs no delivery address alone, and needs one beside a physical product', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    expect( cart.cartRequiresDelivery() ).toBe( false );
    cart.addItem( KIOSK, 1 );
    expect( cart.cartRequiresDelivery() ).toBe( true );
  } );
} );
