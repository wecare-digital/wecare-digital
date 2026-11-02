/** WhatsApp view of the shared omnichannel inbox. */
import React from 'react';
import UnifiedInbox from '../../../pages/workspace/engage/inbox';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const WhatsAppInboxPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => (
  <UnifiedInbox signOut={ signOut } user={ user } embedded={ embedded } channel="whatsapp" />
);

export default WhatsAppInboxPage;
