import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve( __dirname, '..' );
const payments = fs.readFileSync( path.join( ROOT, 'pages/workspace/payments/index.tsx' ), 'utf8' );
const payFlow = fs.readFileSync( path.join( ROOT, 'components/workspace/pay/PayFlow.tsx' ), 'utf8' );
const activity = fs.readFileSync( path.join( ROOT, 'components/workspace/pay/PaymentsActivity.tsx' ), 'utf8' );

describe( 'canonical Payments architecture', () => {
  it( 'exposes exactly Collect, Invoices and Activity as primary modes', () => {
    const tabBlock = payments.slice( payments.indexOf( 'const TABS' ), payments.indexOf( 'function mode' ) );
    const labels = [ ...tabBlock.matchAll( /label: '([^']+)'/g ) ].map( m => m[ 1 ] );
    expect( labels ).toEqual( [ 'Collect', 'Invoices', 'Activity' ] );
    expect( tabBlock ).not.toContain( 'Ledger' );
  } );

  it( 'keeps the embedded PayFlow on Collect rather than restoring its mini CRM', () => {
    const tabBlock = payFlow.slice( payFlow.indexOf( 'const TABS' ), payFlow.indexOf( 'const CFG_KEY' ) );
    const labels = [ ...tabBlock.matchAll( /label: '([^']+)'/g ) ].map( m => m[ 1 ] );
    expect( labels ).toEqual( [ 'Collect' ] );
    expect( payFlow ).toContain( "useState( 'create' )" );
    expect( payFlow ).toContain( 'showChrome={ !embedded }' );
  } );

  it( 'does not add packing or notification fee rows in the browser', () => {
    expect( payFlow ).not.toContain( '+ Green Packing & Notification Fee' );
    expect( payFlow ).not.toContain( 'Auto-append Green Packing + Notification Fee' );
    expect( payFlow ).toContain( "shipping: '0'" );
  } );

  it( 'does not present browser-calculated subtotal, GST or final totals as invoice truth', () => {
    expect( payFlow ).not.toContain( 'calcSubtotal()' );
    expect( payFlow ).not.toContain( 'calcTax()' );
    expect( payFlow ).not.toContain( '>Preview</h4>' );
    expect( payFlow ).toContain( 'calculated and stored by the invoice engine' );
  } );

  it( 'labels Activity as latest stored state rather than inventing an event stream', () => {
    expect( activity ).toContain( 'latest stored state of each invoice' );
    expect( activity ).toContain( 'listInvoicesEngine' );
    expect( activity ).not.toContain( 'mock' );
    expect( activity ).not.toContain( 'Coming Soon' );
  } );
} );
