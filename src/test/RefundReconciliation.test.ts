import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve( __dirname, '..' );
const payFlow = fs.readFileSync( path.join( ROOT, 'components/workspace/pay/PayFlow.tsx' ), 'utf8' );
const client = fs.readFileSync( path.join( ROOT, 'api/client.ts' ), 'utf8' );

describe( 'refund reconciliation UI contract', () => {
  it( 'never presents reconciliation as a provider refund action', () => {
    expect( payFlow ).toContain( 'Reconcile Refund' );
    expect( payFlow ).toContain( 'This does not issue a refund.' );
    expect( payFlow ).toContain( 'Verify & Record Refund' );
    expect( payFlow ).not.toContain( '>Confirm Refund<' );
  } );

  it( 'requires provider evidence before refund reconciliation', () => {
    expect( payFlow ).toContain( "remarkModal.type === 'refund' && !refundId.trim()" );
    expect( payFlow ).toContain( 'Provider refund ID is required. This screen does not initiate refunds.' );
    expect( payFlow ).toContain( "refundId: refundId.trim(), paymentId: remarkModal.inv.paymentId" );
  } );

  it( 'threads provider refund and payment ids through the invoice API', () => {
    const start = client.indexOf( 'export async function addInvoiceRemark' );
    const block = client.slice( start, start + 2200 );
    expect( block ).toContain( 'evidence?: { refundId?: string; paymentId?: string }' );
    expect( block ).toContain( '{ refundId: evidence.refundId }' );
    expect( block ).toContain( '{ paymentId: evidence.paymentId }' );
  } );

  it( 'labels credit-note bookkeeping as recording, not issuing', () => {
    expect( payFlow ).toContain( 'Record Credit Note' );
    expect( payFlow ).not.toContain( 'Issue Credit Note' );
  } );
} );
