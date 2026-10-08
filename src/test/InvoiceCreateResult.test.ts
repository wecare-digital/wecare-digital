import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );
import { createInvoiceEngineResult, type CreateInvoiceEngineRequest } from '../api/client';

const request = { customerPhone: '+919812345678', customerName: 'Test customer',
  items: [ { name: 'Service', amount: 100, quantity: 1, gstRate: 18 } ],
  couponCode: 'SAVE100' } as CreateInvoiceEngineRequest;
afterEach( () => vi.unstubAllGlobals() );

describe( 'invoice create preserves server refusal reasons', () => {
  it( 'returns the exact applied server amounts', async () => {
    const invoice = { invoiceId: 'inv_1', couponDiscount: 42.17, amountPayable: 81.32 };
    const fetchMock = vi.fn().mockResolvedValue( new Response( JSON.stringify( invoice ), { status: 201 } ) );
    vi.stubGlobal( 'fetch', fetchMock );
    expect( await createInvoiceEngineResult( request ) ).toEqual( { ok: true, invoice } );
    const init = fetchMock.mock.calls[ 0 ][ 1 ];
    expect( JSON.parse( init.body ) ).toEqual( request );
    expect( init.headers[ 'Content-Type' ] ).toBe( 'application/json' );
  } );

  it.each( [ 'COUPON_EXPIRED', 'INSUFFICIENT_BALANCE', 'UNKNOWN_CODE' ] )( 'preserves %s from a 400', async errorCode => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( JSON.stringify( { errorCode } ), { status: 400 } ) ) );
    expect( await createInvoiceEngineResult( request ) ).toEqual( {
      ok: false, status: 400, errorCode, retryable: false,
    } );
  } );

  it( 'keeps an unavailable store distinguishable from an invalid code', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( JSON.stringify( {
      errorCode: 'COUPON_STORE_UNAVAILABLE', retryable: true,
    } ), { status: 503 } ) ) );
    expect( await createInvoiceEngineResult( request ) ).toEqual( {
      ok: false, status: 503, errorCode: 'COUPON_STORE_UNAVAILABLE', retryable: true,
    } );
  } );

  it( 'does not treat malformed success data as a created invoice', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( '{}', { status: 200 } ) ) );
    expect( ( await createInvoiceEngineResult( request ) ).ok ).toBe( false );
  } );
} );
