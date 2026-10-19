/**
 * Canonical Payments workspace.
 *
 * Product rule: daily payment work has only two primary modes.
 * - Collect: create an authoritative server-priced invoice/payment request.
 * - Ledger: inspect billed/paid/delivery history and exceptions.
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

interface PageProps { signOut?: () => void; user?: any; }

const TABS: ShellTab[] = [
  { id: 'collect', label: 'Collect' },
  { id: 'ledger', label: 'Ledger', divider: true },
];

function mode ( raw: string | string[] | undefined ): string {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  return id === 'ledger' ? 'ledger' : 'collect';
}

const PaymentsPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const active = mode( router.query.view );

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Payments" description="Collect payments and inspect the authoritative ledger." noindex />
      <PageShell
        key={ active }
        title="Payments"
        subtitle="Collect through the server-authoritative payment flow; inspect invoices and payment evidence in one ledger."
        tabs={ TABS }
        defaultTab={ active }
      >
        { ( tab ) => (
          <>
            { tab === 'collect' && <PayFlowPage signOut={ signOut } user={ user } embedded /> }
            { tab === 'ledger' && <InvoiceRecordsPage signOut={ signOut } user={ user } embedded /> }
          </>
        ) }
      </PageShell>
    </Layout>
  );
};

export default PaymentsPage;
