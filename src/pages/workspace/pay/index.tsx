/**
 * Pay Mega Page - Flow + WhatsApp + Link as tabs
 * Uses PageShell for section header + tab bar
 */
import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

// FEAT-005: the Pay Flow composer and the Invoice records ledger moved OUT of
// src/pages/workspace/pay/** into src/components/workspace/pay/** so each stops being
// its own route.
import PayFlowPage from '../../../components/workspace/pay/PayFlow';
import InvoiceRecordsPage from '../../../components/workspace/pay/InvoiceRecords';

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

// FEAT-005: /workspace/pay?tab=<id> deep-links open the matching tab.
function resolveDefaultTab (raw: string | string[] | undefined): string {
  const id = Array.isArray(raw) ? raw[0] : raw;
  return id && TABS.some((t) => t.id === id) ? id : 'flow';
}

const PayPage: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();
  const defaultTab = resolveDefaultTab(router.query.tab);
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Pay" description="Payments — WhatsApp Pay via invoice flow & invoice records" />
      <PageShell key={defaultTab} title="Pay" subtitle="Invoices, WhatsApp Pay & the billed/paid/delivered ledger" tabs={TABS} defaultTab={defaultTab}>
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
