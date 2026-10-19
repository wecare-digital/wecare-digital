import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const SUBMIT = read( 'src/components/workspace/service/SubmitRequest.tsx' );
const API = read( 'src/api/client.ts' );

describe( 'return/refund request safety', () => {
  it( 'loads lifecycle-era orders instead of the retired active-only set', () => {
    expect( SUBMIT ).toContain( 'api.listOrders( { limit: 200 } )' );
    expect( SUBMIT ).not.toContain( "status: 'active'" );
  } );

  it( 'states that a return/refund request does not move money or cancel the order', () => {
    expect( SUBMIT ).toContain( 'Request only — this does not issue a refund, cancel the order, or change payment state.' );
    expect( SUBMIT ).toContain( 'No money moves and the order is not cancelled here.' );
    expect( SUBMIT ).toContain( 'verified provider workflow' );
  } );

  it( 'does not expose a browser paymentRequired flag on SubmitRequestPayload', () => {
    const start = API.indexOf( 'export interface SubmitRequestPayload' );
    const end = API.indexOf( 'export interface AmendRequestPayload', start );
    const payload = API.slice( start, end );
    expect( payload ).toContain( 'orderId: string' );
    expect( payload ).toContain( 'requestType: string' );
    expect( payload ).not.toContain( 'paymentRequired' );
    expect( payload ).not.toContain( 'refundId' );
  } );
} );
