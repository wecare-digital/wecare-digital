import { beforeEach, describe, expect, it } from 'vitest';
import * as cart from '../lib/cart';
import { NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_PRODUCT_ID } from '../config/services';
import type { ShopProduct } from '../content/shop';

const [ SUBMIT, AMEND ] = SERVICE_CHOICES;
const INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f';
const OTHER_INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60';
const KIOSK: ShopProduct = {
  id: 'wix-abc-123', name: 'Kiosk', slug: 'kiosk', formattedPrice: '₹24,999.00',
  price: '24999.00', currency: 'INR', inStock: true, tagline: 't', body: [],
};

beforeEach( () => { window.localStorage.clear(); } );

describe( 'the service cart line (Phase O-1)', () => {
  it( 'sets ONE service line at quantity 1, replacing another', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
    cart.setServiceLine( AMEND.variantId, OTHER_INTENT );
    const services = cart.readCart().filter( cart.isServiceItem );
    expect( services ).toHaveLength( 1 );
    expect( services[ 0 ] ).toMatchObject( {
      productId: SERVICES_PRODUCT_ID, variantId: AMEND.variantId, quantity: 1,
      name: AMEND.label, formattedPrice: `₹${ AMEND.rupees }.00`, slug: '',
    } );
  } );

  it( 'stores the intent pointer separately from the cart items', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
    expect( window.localStorage.getItem( 'wecare.cart.v1' ) ).not.toContain( INTENT );
    expect( JSON.parse( window.localStorage.getItem( 'wecare.cart.serviceIntent.v1' )! ) )
      .toEqual( { variantId: SUBMIT.variantId, intentId: INTENT } );
  } );

  it( 'answers the intent only for the same single service variant', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
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

  it( 'refuses Drop Docs, Vault and a missing intent, writing nothing', () => {
    for ( const variant of NOT_OFFERED_SERVICE_VARIANT_IDS )
    {
      cart.setServiceLine( variant, INTENT );
    }
    cart.setServiceLine( SUBMIT.variantId, '' );
    expect( cart.readCart() ).toEqual( [] );
  } );

  it( 'keeps toLineItems price-free', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
    const wire = JSON.stringify( cart.toLineItems() );
    expect( wire ).not.toMatch( /price|amount|currency|9900|₹/i );
    expect( cart.toLineItems() ).toEqual( [ {
      catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e',
        catalogItemId: SERVICES_PRODUCT_ID, options: { variantId: SUBMIT.variantId } },
      quantity: 1,
    } ] );
  } );

  it( 'survives the readCart reconcile', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
    expect( cart.readCart() ).toHaveLength( 1 );
    expect( cart.readCart()[ 0 ].variantId ).toBe( SUBMIT.variantId );
  } );

  it( 'needs no delivery address alone, and needs one beside a physical product', () => {
    cart.setServiceLine( SUBMIT.variantId, INTENT );
    expect( cart.cartRequiresDelivery() ).toBe( false );
    cart.addItem( KIOSK, 1 );
    expect( cart.cartRequiresDelivery() ).toBe( true );
  } );
} );
