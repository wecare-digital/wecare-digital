import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );
import { createInvoiceEngineResult, type CreateInvoiceEngineRequest } from '../api/client';

// No coupon or gift-card code travels on this request any more — the only discount is the
// server's always-on Delight policy, applied by the engine itself. What this file still guards is
// the RESULT WRAPPER: `createInvoiceEngineResult` must preserve the server's typed `errorCode` on
// a 4xx/503 rather than collapsing every non-2xx to `null`, so a create failure is reported
// honestly (a create can still fail for non-discount reasons).
const request = { customerPhone: '+919812345678', customerName: 'Test customer',
  customerEmail: '', shippingAddress: '', billingAddress: '',
  items: [ { name: 'Service', amount: 100, quantity: 1, gstRate: 18 } ] } as CreateInvoiceEngineRequest;
afterEach( () => vi.unstubAllGlobals() );

describe( 'invoice create preserves server result and refusal reasons', () => {
  it( 'returns the exact applied server amounts, including the Delight discount', async () => {
    // couponCode is the fixed DELIGHT code the engine echoes back; couponDiscount is its figure.
    const invoice = { invoiceId: 'inv_1', couponCode: 'DELIGHT', couponDiscount: 42.17 };
    const fetchMock = vi.fn().mockResolvedValue( new Response( JSON.stringify( invoice ), { status: 201 } ) );
    vi.stubGlobal( 'fetch', fetchMock );
    expect( await createInvoiceEngineResult( request ) ).toEqual( { ok: true, invoice } );
    const init = fetchMock.mock.calls[ 0 ][ 1 ];
    expect( JSON.parse( init.body ) ).toEqual( request );
    expect( init.headers[ 'Content-Type' ] ).toBe( 'application/json' );
  } );

  it.each( [ 'PAYABLE_BELOW_GATEWAY_MINIMUM', 'VALIDATION_FAILED', 'INVOICE_TOTAL_MISMATCH' ] )( 'preserves %s from a 400', async errorCode => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( JSON.stringify( { errorCode } ), { status: 400 } ) ) );
    expect( await createInvoiceEngineResult( request ) ).toEqual( {
      ok: false, status: 400, errorCode, retryable: false,
    } );
  } );

  it( 'keeps a retryable server failure distinguishable from a hard refusal', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( JSON.stringify( {
      errorCode: 'SERVICE_UNAVAILABLE', retryable: true,
    } ), { status: 503 } ) ) );
    expect( await createInvoiceEngineResult( request ) ).toEqual( {
      ok: false, status: 503, errorCode: 'SERVICE_UNAVAILABLE', retryable: true,
    } );
  } );

  it( 'does not treat malformed success data as a created invoice', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( new Response( '{}', { status: 200 } ) ) );
    expect( ( await createInvoiceEngineResult( request ) ).ok ).toBe( false );
  } );
} );
