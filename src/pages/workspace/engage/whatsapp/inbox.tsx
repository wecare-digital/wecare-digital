/**
 * WhatsApp inbox — a thin wrapper over the omnichannel inbox, pre-filtered to WhatsApp.
 *
 * This file was a 1,863-line second inbox implementation against /workspace/engage/inbox's.
 * The duplication was the defect: two renderers over the same canonical MessagesTable drift,
 * and this one had already lost the conversation-meta, notes, block/unblock and
 * payment-message work the other gained.
 *
 * The import-level endpoint diff taken before this reduction (api.* symbols here minus api.*
 * symbols there) printed four names, of which exactly three are calls, and every one is
 * already reachable elsewhere, so no capability was dropped to get here:
 *   clearAllInboxData       — workspace/dashboard/index.tsx
 *   deleteContact           — workspace/contacts/index.tsx (single and batch)
 *   sendWhatsAppInteractive — components/InteractiveMessageComposer.tsx, which the
 *                             omnichannel inbox already renders
 * The fourth name, api.Contact, is not a capability: it is the exported `Contact`
 * interface used in a type assertion, has no call site in src/, and stays in api/client.ts.
 *
 * THE FILE STAYS, deliberately. src/test/CssDrivenMotion.test.tsx reads this exact path and
 * asserts it hardcodes no smooth scroll behavior — a TEXT match over the source, so this
 * docblock must not spell the literal it forbids. whatsapp/index.tsx also imports './inbox'
 * and full-screen-wraps it, and that route is a declared inner page of `communications`.
 *
 * `embedded` passes straight through rather than being hardcoded, so the omnichannel page
 * decides the shell: bare content when embedded, Layout-wrapped otherwise. That keeps this
 * a working standalone route AND keeps it embeddable.
 */
import React from 'react';
import UnifiedInbox from '../inbox';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const WhatsAppInboxPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => (
  <UnifiedInbox signOut={ signOut } user={ user } embedded={ embedded } channel="whatsapp" />
);

export default WhatsAppInboxPage;
