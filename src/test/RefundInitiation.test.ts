import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const ORDERS = read( 'src/components/workspace/commerce/Orders.tsx' );
const API = read( 'src/api/client.ts' );

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
    expect( ORDERS ).toContain( 'useConfirm' );
    // No native browser dialogs — the confirm step goes through the ConfirmContext hook.
    expect( ORDERS ).not.toMatch( /\bwindow\.(alert|confirm|prompt)\s*\(/ );
    expect( ORDERS ).toContain( 'initiateFullRefund' );
    expect( ORDERS ).not.toContain( 'initiatePartialRefund' );
    expect( ORDERS ).toContain( 'Refund initiated; awaiting final payment status' );
  } );

  it( 'sends the operator reason to the server so it can be persisted as the audit record', () => {
    // The shared POST includes `reason` in the request body...
    const block = API.slice( API.indexOf( 'async function postRefundInitiation' ), API.indexOf( 'export async function initiateFullRefund' ) );
    expect( block ).toContain( 'reason' );
    expect( block ).toMatch( /returnSubmissionId,\s*reason/ );
    // ...and both entry points take a reason parameter.
    expect( API ).toMatch( /initiateFullRefund[\s\S]*?reason: string/ );
    expect( API ).toMatch( /initiatePartialRefund[\s\S]*?reason: string/ );
    // The Orders UI remains full-refund-only but still sends the required audit reason.
    expect( ORDERS ).toContain( 'onRefundInitiation( sub, reason )' );
    expect( ORDERS ).toContain( 'Refund reason (required)' );
  } );
} );
