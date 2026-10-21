import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = process.cwd();
const read = ( file: string ) => fs.readFileSync( path.join( root, file ), 'utf8' );

describe( 'workspace pending-completion contracts', () => {
  it( 'global search covers operational records and preserves deep-link queries', () => {
    const search = read( 'src/components/SearchModal.tsx' );
    expect( search ).toContain( 'api.searchContacts' );
    expect( search ).toContain( 'api.listOrders' );
    expect( search ).toContain( 'api.listInvoicesEngine' );
    expect( search ).toContain( 'api.listFlowSubmissions' );
    expect( search ).toContain( "fetch( '/api/links' )" );
    expect( search ).toContain( '/workspace/customers?contact=' );
    expect( search ).toContain( '/workspace/commerce?view=orders&search=' );
    expect( search ).toContain( '/workspace/payments?view=ledger&ledger=invoices&search=' );
    expect( search ).toContain( '/workspace/service?view=requests&search=' );
  } );

  it( 'record surfaces consume universal-search deep links', () => {
    expect( read( 'src/components/workspace/commerce/Orders.tsx' ) ).toContain( 'router.query.search' );
    expect( read( 'src/components/workspace/pay/InvoiceRecords.tsx' ) ).toContain( 'router.query.search' );
    expect( read( 'src/components/service/ResponsesQueue.tsx' ) ).toContain( 'router.query.search' );
  } );

  it( 'refund initiation stays confirmed, server-derived and provider-gated', () => {
    // Refund execution remains server-derived and provider-gated. The Orders UI exposes the
    // simple full-refund path; the backend partial-refund capability remains independently tested.
    const orders = read( 'src/components/workspace/commerce/Orders.tsx' );
    const client = read( 'src/api/client.ts' );
    const handler = read( 'amplify/functions/payments/invoice-engine/handler.py' );
    const executor = read( 'amplify/functions/shared/lambda_utils/integrations/razorpay_refund.py' );

    expect( orders ).toContain( 'useConfirm' );
    expect( orders ).not.toMatch( /\bwindow\.(alert|confirm|prompt)\s*\(/ );
    expect( orders ).toContain( 'api.initiateFullRefund' );
    expect( orders ).not.toContain( 'api.initiatePartialRefund' );
    expect( orders ).not.toContain( 'api.initiateInvoiceRefund' );
    expect( client ).toContain( "'initiate-refund'" );
    expect( client ).toContain( "'initiate-partial-refund'" );
    expect( client ).toContain( 'returnSubmissionId' );
    // The server derives the payment id; the browser never chooses one on the refund POST.
    expect( client ).not.toContain( "_action: 'initiate-refund',\n      paymentId" );
    expect( handler ).toContain( 'razorpay_refund.enabled()' );
    expect( handler ).toContain( "body.get('paymentId')" );
    expect( executor ).toContain( 'REFUND_INITIATION_ENABLED' );
    expect( executor ).toContain( '== "true"' );
  } );

  it( 'customer archive and consent evidence are non-destructive', () => {
    const contacts = read( 'amplify/functions/core/contacts/handler.py' );
    const customers = read( 'src/pages/workspace/customers/index.tsx' );
    expect( contacts ).toContain( "CONSENT_HISTORY_ATTRIBUTE = 'consentHistory'" );
    expect( contacts ).toContain( 'list_append(if_not_exists(#consent_history' );
    expect( contacts ).toContain( "ARCHIVED_AT_ATTRIBUTE = 'archivedAt'" );
    expect( customers ).toContain( 'api.archiveContact' );
    expect( customers ).not.toContain( 'const result = await api.deleteContact(contactId)' );
  } );
} );
