/**
 * Pay Mega Page - Flow + WhatsApp + Link as tabs
 * Uses PageShell for section header + tab bar
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

import PayFlowPage from './flow';

interface PageProps { signOut?: () => void; user?: any; }

// Only the Flow path is kept: it goes through the invoice engine, reserves a reference_id
// and collects via the approved WhatsApp order_details template. The old "Link" tab built a
// raw upi:// deep link client-side, bypassing Razorpay, the invoice engine and reconciliation
// — and WhatsApp payments must route through the template, never a raw link — so it was removed.
const TABS: ShellTab[] = [
  { id: 'flow', label: 'Flow' },
];

const PayPage: React.FC<PageProps> = ({ signOut, user }) => {
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Pay" description="Payments — WhatsApp Pay via invoice flow" />
      <PageShell title="Pay" subtitle="Invoices & WhatsApp Pay" tabs={TABS} defaultTab="flow">
        {(activeTab) => (
          <>
            {activeTab === 'flow' && <PayFlowPage signOut={signOut} user={user} embedded />}
          </>
        )}
      </PageShell>
    </Layout>
  );
};

export default PayPage;
