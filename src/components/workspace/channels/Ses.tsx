/**
 * Email Mega Page - Inbox + Campaign + Logs as tabs
 * Uses PageShell for section header + tab bar
 */
import React from 'react';
import dynamic from 'next/dynamic';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

// Loaded per tab — see the note in dm/rcs/index.tsx. Embedding the unified pages
// was right; importing all three eagerly was not.
// Generic on purpose. Annotating the loader as `Promise<any>` erased every tab's
// prop types and typecheck rejected `signOut`/`user`/`embedded` at 17 call sites -
// the helper has to carry the module's own props through, not flatten them.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

// FEAT-005: inbox/broadcast/logs stay as real routes under src/pages/workspace/engage/**,
// so this relocated component reaches back into the pages tree for them.
const UnifiedInbox = lazyTab( () => import( '../../../pages/workspace/engage/inbox' ) );
// dm/broadcast is the multi-channel superset and already sends email.
const BroadcastPage = lazyTab( () => import( '../../../pages/workspace/engage/broadcast' ) );
// Unified logs, preset to this channel. ./logs was 268 lines over the same table;
// its one unique feature, row delete, moved into dm/logs.
const MessageLogsPage = lazyTab( () => import( '../../../pages/workspace/engage/logs' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
  { id: 'inbox', label: 'Inbox' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'logs', label: 'Logs' },
];

const EmailPage: React.FC<PageProps> = ({ signOut, user, embedded }) => {
  const shellContent = (
    <PageShell title="Email" subtitle="AWS SES — Inbox, Campaigns & Logs" tabs={TABS} defaultTab="inbox">
      {(activeTab) => (
        <>
          {activeTab === 'inbox' && <UnifiedInbox signOut={signOut} user={user} embedded channel="email" />}
          {activeTab === 'campaign' && <BroadcastPage signOut={signOut} user={user} embedded />}
          {activeTab === 'logs' && <MessageLogsPage signOut={signOut} user={user} embedded channel="email" />}
        </>
      )}
    </PageShell>
  );

  if (embedded) return shellContent;

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Email" description="Email — AWS SES" />
      {shellContent}
    </Layout>
  );
};

export default EmailPage;
