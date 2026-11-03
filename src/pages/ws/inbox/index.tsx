/**
 * /ws/inbox — the fresh, mobile-first conversation inbox (FEAT-004).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * The list + thread (master/detail on mobile, side by side on desktop) live in InboxView under
 * src/components/ws/inbox/. Conversation/message data flows only through the existing
 * src/api/client.ts exports (listMessages, listContacts, getConversationMeta, and
 * sendWhatsAppMessage for the one wired reply path) — no new endpoints and no bare fetch.
 */
import React from 'react';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';
import InboxView from '../../../components/ws/inbox/InboxView';

interface PageProps { signOut?: () => void; user?: any; }

const WsInbox: React.FC<PageProps> = ( { signOut, user } ) => (
  <>
    <SEO title="Inbox" description="WECARE workspace inbox." noindex />
    <WsShell active="inbox" user={ user } signOut={ signOut }>
      <InboxView />
    </WsShell>
  </>
);

export default WsInbox;
