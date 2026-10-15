/**
 * WhatsApp Inbox — Full Screen with Breadcrumbs
 * The inbox fills remaining main-content height after breadcrumbs.
 * All other WhatsApp features live at /workspace/engage/whatsapp/settings
 */

import React from 'react';
import Layout from '../../../../components/Layout';
import InboxPage from './inbox';

interface PageProps {
  signOut?: () => void;
  user?: any;
}

const WhatsAppPage: React.FC<PageProps> = ({ signOut, user }) => (
  <Layout user={user} onSignOut={signOut} showBreadcrumbs={true}>
    <div style={{ flex: 1, overflow: 'hidden', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <InboxPage signOut={signOut} user={user} embedded />
    </div>
  </Layout>
);

export default WhatsAppPage;
