/**
 * /workspace/dashboard/waba-usernames — sends the operator to BSUID & Usernames.
 *
 * This was a 217-line "WABA Business Usernames Manager" filed under Platform. Everything it
 * did, /workspace/engage/whatsapp/bsuid already does with the same two calls
 * (api.getBusinessUsername and api.claimBusinessUsername) for the same two numbers
 * (WHATSAPP_PHONES.primary and .secondary, via its phone selector), and bsuid adds what this
 * page never had: Meta's username suggestions, the business_username_updates webhook
 * subscription and the parent-BSUID lookup. Two gear rows (Platform -> WABA Usernames and
 * WhatsApp -> BSUID & Usernames) therefore opened two screens over one feature, and the one
 * under Platform was the smaller of the two.
 *
 * WHY A SIGNPOST AND NOT A DELETION: bookmarks. Nothing in the app links here any more - the
 * Platform row went on 2026-10-15 - so this only catches a typed or saved URL. Same pattern
 * as src/pages/workspace/admin/index.tsx and src/pages/workspace/engage/whatsapp/index.tsx.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const WabaUsernamesSignpost = () => {
  const router = useRouter();

  useEffect( () => {
    // replace, not push: leaving a signpost in history makes Back bounce forward again.
    router.replace( '/workspace/engage/whatsapp/bsuid' );
  }, [ router ] );

  return null;
};

export default WabaUsernamesSignpost;
