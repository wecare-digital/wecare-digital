/**
 * /workspace/engage/whatsapp — compatibility route to the canonical Communications inbox, filtered to WhatsApp.
 *
 * It was a full-screen Layout around ./inbox, which is itself a thin wrapper over the
 * omnichannel inbox with channel="whatsapp". So one inbox had three URLs: the sidebar's
 * Inbox -> WhatsApp (/workspace/engage/inbox?channel=whatsapp), this page (the gear's
 * "WhatsApp Inbox" row), and /workspace/engage/whatsapp/inbox. All three rendered the
 * same component over the same MessagesTable with the same channel filter, and the
 * filter stays user-changeable in every one of them, so nothing here was unique.
 *
 * WHY A REDIRECT AND NOT A DELETION. It is the shortest WhatsApp URL there is, it was a
 * gear row until 2026-10-15, and in-app links outside the workspace pages still point at
 * it (the dashboard OverviewTab cards, the Ctrl+M shortcut in useKeyboardShortcuts). A
 * signpost keeps every one of those landing on the inbox instead of a 404.
 *
 * What still needs the inbox to RENDER is untouched: FEAT-003 folded the WhatsApp inbox
 * into the Communications WhatsApp management as its `inbox` tab (its body now lives at
 * src/components/workspace/whatsapp/inbox.tsx, which src/test/CssDrivenMotion.test.tsx reads,
 * not this file), and the `communications` module home names /workspace/communications?view=manage&section=whatsapp
 * — the WhatsApp Business hub — instead of this URL.
 *
 * Follows the precedents in src/pages/workspace/admin/index.tsx,
 * src/pages/workspace/forms/index.tsx and src/pages/workspace/service/index.tsx.
 */

import { useEffect } from 'react';
import { useRouter } from 'next/router';

const WhatsAppIndex = () => {
  const router = useRouter();

  useEffect( () => {
    // replace, not push: this is a signpost, and leaving it in history means Back
    // lands here and bounces forward again.
    router.replace( '/workspace/communications?view=inbox&channel=whatsapp' );
  }, [ router ] );

  return null;
};

export default WhatsAppIndex;
