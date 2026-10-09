import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SERVICE_CHOICES } from '../config/services';
import { catalogContentId, trackCatalogView, trackCatalogAdd, trackCatalogPurchase,
  setMarketingConsent, META_PIXEL_ID, META_DATASET_ID } from '../lib/metaCatalogAnalytics';

const realWindow = window;
const submit = SERVICE_CHOICES.find( x => x.kind === 'SUBMIT_REQUEST' )!;
const vault = SERVICE_CHOICES.find( x => x.kind === 'VAULT' )!;
const fbq = vi.fn();
beforeEach( () => {
  realWindow.localStorage.clear(); fbq.mockClear();
  vi.stubGlobal( 'window', {
    localStorage: realWindow.localStorage, location: { hostname: 'wecare.digital' }, fbq,
    dispatchEvent: realWindow.dispatchEvent.bind( realWindow ),
  } );
} );
afterEach( () => { vi.unstubAllGlobals(); realWindow.localStorage.clear(); } );

describe( 'real catalog actions and consent', () => {
  it( 'fires into the one shared Conversions API dataset, not a separate pixel', () => {
    expect( META_DATASET_ID ).toBe( '4554612361454941' );
    expect( META_PIXEL_ID ).toBe( META_DATASET_ID );
  } );
  it( 'sends nothing before a positive consent choice or after withdrawal', () => {
    trackCatalogView( submit.path ); trackCatalogAdd( submit.variantId, 9900 );
    expect( fbq ).not.toHaveBeenCalled();
    setMarketingConsent( true ); trackCatalogView( submit.path );
    expect( fbq ).toHaveBeenCalledWith( 'trackSingle', META_PIXEL_ID, 'ViewContent',
      expect.objectContaining( { content_ids: [ catalogContentId( submit.variantId ) ] } ) );
    setMarketingConsent( false ); fbq.mockClear();
    trackCatalogAdd( submit.variantId, 9900 ); expect( fbq ).not.toHaveBeenCalled();
  } );
  it( 'uses exact Wix variant catalog IDs and does not tag unrelated products', () => {
    setMarketingConsent( true ); fbq.mockClear();
    trackCatalogView( vault.path ); trackCatalogAdd( vault.variantId, 4900 );
    expect( fbq ).toHaveBeenLastCalledWith( 'trackSingle', META_PIXEL_ID, 'AddToCart',
      expect.objectContaining( { value: 49, content_ids: [ catalogContentId( vault.variantId ) ] } ) );
    fbq.mockClear(); trackCatalogView( '/workspace/payments/' );
    trackCatalogAdd( 'not-in-catalog', 9900 ); expect( fbq ).not.toHaveBeenCalled();
  } );
  it( 'does not convert missing, malformed or unknown purchase facts into a Purchase', () => {
    setMarketingConsent( true ); fbq.mockClear();
    expect( trackCatalogPurchase( 'a' ) ).toBe( false );
    expect( trackCatalogPurchase( 'a', { currency: 'INR', amountPaise: 9900,
      contents: [ { id: 'unknown', quantity: 1 } ] } ) ).toBe( false );
    expect( fbq ).not.toHaveBeenCalled();
  } );
  it( 'deduplicates repeated paid status reads by attempt, using the server amount', () => {
    setMarketingConsent( true ); fbq.mockClear();
    const facts = { currency: 'INR', amountPaise: 10702,
      contents: [ { id: catalogContentId( submit.variantId )!, quantity: 1 } ] };
    expect( trackCatalogPurchase( 'paid-a', facts ) ).toBe( true );
    expect( trackCatalogPurchase( 'paid-a', facts ) ).toBe( false );
    expect( fbq ).toHaveBeenCalledTimes( 1 );
    expect( fbq ).toHaveBeenCalledWith( 'trackSingle', META_PIXEL_ID, 'Purchase',
      expect.objectContaining( { value: 107.02, content_type: 'product' } ),
      { eventID: 'wecare-purchase-paid-a' } );
  } );
} );
