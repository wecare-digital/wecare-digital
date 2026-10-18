/**
 * Pay Mega Page - Flow + WhatsApp + Link as tabs
 * Uses PageShell for section header + tab bar
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

import PayFlowPage from './flow';
import InvoiceRecordsPage from './records';

interface PageProps { signOut?: () => void; user?: any; }

// Payments 3->1 (FEAT-004): the Flow composer and the Invoice records ledger are now
// in-page tabs on this one page, each rendering the existing `embedded` page so every
// invoice-engine call site is unchanged. The old client-side "Link" tab stays removed:
// it built a raw upi:// deep link, bypassing Razorpay, the invoice engine and
// reconciliation — WhatsApp payments must route through the order_details template.
const TABS: ShellTab[] = [
  { id: 'flow', label: 'Pay Flow' },
  { id: 'records', label: 'Invoice records', divider: true },
];

const PayPage: React.FC<PageProps> = ({ signOut, user }) => {
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Pay" description="Payments — WhatsApp Pay via invoice flow & invoice records" />
      <PageShell title="Pay" subtitle="Invoices, WhatsApp Pay & the billed/paid/delivered ledger" tabs={TABS} defaultTab="flow">
        {(activeTab) => (
          <>
            {activeTab === 'flow' && <PayFlowPage signOut={signOut} user={user} embedded />}
            {activeTab === 'records' && <InvoiceRecordsPage signOut={signOut} user={user} embedded />}
          </>
        )}
      </PageShell>
    </Layout>
  );
};

export default PayPage;
