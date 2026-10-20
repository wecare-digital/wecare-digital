import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

import {
  rupeesFromPaise,
  rupeesToPaise,
  validatePartialRefundPaise,
} from '../components/workspace/commerce/Orders';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const ORDERS = read( 'src/components/workspace/commerce/Orders.tsx' );
const API = read( 'src/api/client.ts' );

describe( 'partial refund amount capping (UI mirror of the server cap)', () => {
  it( 'rejects non-positive and non-integer amounts', () => {
    expect( validatePartialRefundPaise( 0, 10000 ) ).toEqual( { ok: false, reason: expect.any( String ) } );
    expect( validatePartialRefundPaise( -1, 10000 ) ).toEqual( { ok: false, reason: expect.any( String ) } );
    expect( validatePartialRefundPaise( 10.5, 10000 ) ).toEqual( { ok: false, reason: expect.any( String ) } );
  } );

  it( 'rejects an amount over the known cap', () => {
    const result = validatePartialRefundPaise( 10001, 10000 );
    expect( result.ok ).toBe( false );
    if ( !result.ok ) expect( result.reason ).toContain( '100.00' );
  } );

  it( 'accepts an amount at or below the cap', () => {
    expect( validatePartialRefundPaise( 10000, 10000 ) ).toEqual( { ok: true, amountPaise: 10000 } );
    expect( validatePartialRefundPaise( 2500, 10000 ) ).toEqual( { ok: true, amountPaise: 2500 } );
  } );

  it( 'accepts any positive amount when the cap is unknown (0), leaving the server as authority', () => {
    expect( validatePartialRefundPaise( 999999, 0 ) ).toEqual( { ok: true, amountPaise: 999999 } );
  } );
} );

describe( 'rupee <-> paise conversion', () => {
  it( 'parses clean rupee strings to integer paise', () => {
    expect( rupeesToPaise( '100' ) ).toBe( 10000 );
    expect( rupeesToPaise( '100.50' ) ).toBe( 10050 );
    expect( rupeesToPaise( '0.01' ) ).toBe( 1 );
  } );

  it( 'rejects junk, empty, negative and over-precise values', () => {
    expect( rupeesToPaise( '' ) ).toBeNull();
    expect( rupeesToPaise( 'abc' ) ).toBeNull();
    expect( rupeesToPaise( '-5' ) ).toBeNull();
    expect( rupeesToPaise( '1.234' ) ).toBeNull();
  } );

  it( 'renders paise back to a two-decimal rupee string', () => {
    expect( rupeesFromPaise( 10000 ) ).toBe( '₹100.00' );
    expect( rupeesFromPaise( 1 ) ).toBe( '₹0.01' );
    expect( rupeesFromPaise( undefined ) ).toBe( '₹0.00' );
  } );
} );

describe( 'refund initiation is server-authoritative and webhook-truthful', () => {
  it( 'client posts full and partial refund actions without a browser-chosen payment id', () => {
    expect( API ).toContain( "export async function initiateFullRefund" );
    expect( API ).toContain( "export async function initiatePartialRefund" );
    expect( API ).toContain( "'initiate-refund'" );
    expect( API ).toContain( "'initiate-partial-refund'" );
    // The irreversible POST must NOT go through the auto-retrying apiCall path.
    const block = API.slice( API.indexOf( 'async function postRefundInitiation' ), API.indexOf( 'export async function initiateFullRefund' ) );
    expect( block ).toContain( 'authFetch' );
    expect( block ).not.toContain( 'apiCallResult' );
  } );

  it( 'Orders UI only claims refunded after webhook confirmation and uses no native dialog', () => {
    expect( ORDERS ).toContain( 'Awaiting webhook confirmation' );
    expect( ORDERS ).toContain( 'useConfirm' );
    // No native browser dialogs — the confirm step goes through the ConfirmContext hook.
    expect( ORDERS ).not.toMatch( /\bwindow\.(alert|confirm|prompt)\s*\(/ );
    expect( ORDERS ).toContain( 'initiatePartialRefund' );
    expect( ORDERS ).toContain( 'initiateFullRefund' );
  } );
} );
