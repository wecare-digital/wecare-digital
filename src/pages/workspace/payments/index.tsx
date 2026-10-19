/**
 * Canonical Payments workspace.
 *
 * Product rule: daily payment work has three primary modes.
 * - Collect: create a server-authoritative invoice/payment request.
 * - Invoices: inspect the statutory invoice records and delivery evidence.
 * - Activity: review the latest stored money state without inventing an event stream.
 *
 * The proven PayFlow and InvoiceRecords components are reused first; their old /workspace/pay
 * wrapper becomes a compatibility redirect after this page lands.
 */
import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';
import PayFlowPage from '../../../components/workspace/pay/PayFlow';
import InvoiceRecordsPage from '../../../components/workspace/pay/InvoiceRecords';
import PaymentsActivity from '../../../components/workspace/pay/PaymentsActivity';

interface PageProps { signOut?: () => void; user?: any; }

const TABS: ShellTab[] = [
  { id: 'collect', label: 'Collect' },
  { id: 'invoices', label: 'Invoices', divider: true },
  { id: 'activity', label: 'Activity' },
];

type PaymentsView = 'collect' | 'invoices' | 'activity';

function mode ( raw: string | string[] | undefined ): PaymentsView {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  if ( id === 'invoices' || id === 'ledger' ) return 'invoices';
  if ( id === 'activity' ) return 'activity';
  return 'collect';
}

const PaymentsPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const active = mode( router.query.view );

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Payments" description="Collect payments, inspect invoices and review recent payment activity." noindex />
      <PageShell
        key={ active }
        title="Payments"
        subtitle="Collect through the invoice engine, inspect invoice records, and review recent stored payment state."
        tabs={ TABS }
        activeTab={ active }
        defaultTab={ active }
        onTabChange={ next => {
          const view = mode( next );
          void router.push( { pathname: '/workspace/payments', query: { view } } );
        } }
      >
        { ( tab ) => (
          <>
            { tab === 'collect' && <PayFlowPage signOut={ signOut } user={ user } embedded /> }
            { tab === 'invoices' && <InvoiceRecordsPage signOut={ signOut } user={ user } embedded /> }
            { tab === 'activity' && <PaymentsActivity /> }
          </>
        ) }
      </PageShell>
    </Layout>
  );
};

export default PaymentsPage;
