/**
 * /ws/customers — the fresh, mobile-first customer list (FEAT-003).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * The list and all of its actions live in CustomerList / CustomerActionsSheet under
 * src/components/ws/customers/. Archive is confirm()-gated and honours the
 * server ApiResult. Full customer erasure is explicitly unavailable until all linked
 * storage, identity and legal-retention records can be processed together.
 * Data flows only through the existing src/api/client.ts exports
 * (listContactsResult, archiveContact, updateContactResult) — no bare fetch.
 * Bulk archive re-reads current lock state and requires staff confirmation.
 * Individual deletion is also unavailable until full erasure is audited.
 */
import React from 'react';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';
import CustomerList from '../../../components/ws/customers/CustomerList';

interface PageProps { signOut?: () => void; user?: any; }

const WsCustomers: React.FC<PageProps> = ( { signOut, user } ) => (
  <>
    <SEO title="Customers" description="WECARE workspace customers." noindex />
    <WsShell active="customers" user={ user } signOut={ signOut }>
      <CustomerList />
    </WsShell>
  </>
);

export default WsCustomers;
