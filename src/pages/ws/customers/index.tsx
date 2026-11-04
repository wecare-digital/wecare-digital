/**
 * /ws/customers — the fresh, mobile-first customer list (FEAT-003).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * The list and all of its actions live in CustomerList / CustomerActionsSheet under
 * src/components/ws/customers/. Every delete/block action is confirm()-gated and honours the
 * server ApiResult: on a refusal the server's own reason is shown via toast and the row is NOT
 * reported removed. Data flows only through the existing src/api/client.ts exports
 * (listContactsResult, softDeleteContactResult, archiveContact, updateContactResult)
 * — no new endpoints and no bare fetch. Bulk archive/delete always re-reads
 * current lock state and requires explicit staff confirmation. Bulk removal is archive-only;
 * the existing individual action sheet owns reviewed soft deletion.
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
