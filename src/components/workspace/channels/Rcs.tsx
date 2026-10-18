/**
 * RCS Mega Page - Inbox + Campaign + Logs as tabs
 * Uses PageShell for section header + tab bar
 */
import React from 'react';
import dynamic from 'next/dynamic';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

// Loaded per tab. The consolidation made these hubs embed the unified pages rather
// than ship their own copies, which was the right call - but a static import means
// opening the RCS hub downloads the inbox, the broadcast composer AND the logs view
// before showing any of them. `dm/inbox` alone is the largest page in the app.
// Generic on purpose. Annotating the loader as `Promise<any>` erased every tab's
// prop types and typecheck rejected `signOut`/`user`/`embedded` at 17 call sites -
// the helper has to carry the module's own props through, not flatten them.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

// FEAT-005: inbox/broadcast/logs stay as real routes under src/pages/workspace/engage/**,
// so this relocated component reaches back into the pages tree for them. The RCS-only
// send/templates bodies moved alongside this file into components/workspace/channels/**.
const UnifiedInbox = lazyTab( () => import( '../../../pages/workspace/engage/inbox' ) );
const RcsSendPage = lazyTab( () => import( './RcsSend' ) );
const RcsTemplatesPage = lazyTab( () => import( './RcsTemplates' ) );
// dm/broadcast is the multi-channel superset. ./campaign made no send call at
// all - it was campaign history synthesised from listMessages.
const BroadcastPage = lazyTab( () => import( '../../../pages/workspace/engage/broadcast' ) );
// Unified logs, preset to this channel. ./logs was 119 lines calling the same
// api.listMessages as dm/logs against the same canonical table.
const MessageLogsPage = lazyTab( () => import( '../../../pages/workspace/engage/logs' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
  { id: 'inbox', label: 'Inbox' },
  { id: 'send', label: 'Send' },
  { id: 'templates', label: 'Templates' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'logs', label: 'Logs' },
];

const RcsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const shellContent = (
    <PageShell title="RCS" subtitle="Rich Communication Services — Inbox, Campaigns & Logs" tabs={ TABS } defaultTab="inbox">
      { ( activeTab ) => (
        <>
          { activeTab === 'inbox' && <UnifiedInbox signOut={ signOut } user={ user } embedded channel="rcs" /> }
          { activeTab === 'send' && <RcsSendPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'templates' && <RcsTemplatesPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'campaign' && <BroadcastPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'logs' && <MessageLogsPage signOut={ signOut } user={ user } embedded channel="rcs" /> }
        </>
      ) }
    </PageShell>
  );

  if ( embedded ) return shellContent;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="RCS" description="RCS Business Messaging" />
      { shellContent }
    </Layout>
  );
};

export default RcsPage;
