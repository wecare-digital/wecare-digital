import WhatsAppServiceDirectory from '../../../../components/WhatsAppServiceDirectory';
import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../../lib/canonicalFlows';
/**
 * WhatsApp Settings — All WhatsApp features except Inbox
 * Uses PageShell for section header + scrollable tab bar
 */

import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import Layout from '../../../../components/Layout';
import PageShell, { ShellTab } from '../../../../components/PageShell';

/**
 * Seventeen tab bodies, loaded one at a time.
 *
 * These were static imports, and the `<Suspense>` boundary below has been sitting
 * around them the whole time doing **nothing** — a static import cannot suspend, so
 * the fallback was unreachable and every visit to this page downloaded all
 * seventeen tabs to render one. Measured: **515 KB of source**, of which
 * `calling` alone is 120 KB and `ai-agent` 47 KB.
 *
 * `next/dynamic` is what the Suspense boundary was always waiting for. Nothing else
 * changes: the component names are identical, so not one line of the JSX below was
 * touched — the same reason the shell-wrapping transform was safe.
 *
 * `ssr: false` because every one of these fetches on mount and sits behind auth, so
 * there is nothing meaningful to prerender, and it keeps them out of the server
 * bundle of a statically exported page.
 */
// Generic on purpose. Annotating the loader as `Promise<any>` erased every tab's
// prop types and typecheck rejected `signOut`/`user`/`embedded` at 17 call sites -
// the helper has to carry the module's own props through, not flatten them.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const WABADashboard = lazyTab( () => import( './waba-dashboard' ) );
const TemplatesPage = lazyTab( () => import( './templates' ) );
const WelcomePage = lazyTab( () => import( './welcome' ) );
const CampaignPage = lazyTab( () => import( './campaign' ) );
// Unified logs, preset to WhatsApp. ./logs was 265 lines over the same canonical
// table as dm/logs; its error decoding, CSV export, pagination and contact-name
// resolution all moved into dm/logs rather than being dropped.
const LogsPage = lazyTab( () => import( '../logs' ) );
const InteractiveListsPage = lazyTab( () => import( './interactive-lists' ) );
const FlowsPage = lazyTab( () => import( './flows' ) );
const CallingPage = lazyTab( () => import( './calling' ) );
const GroupsPage = lazyTab( () => import( './groups' ) );
const BusinessProfilePage = lazyTab( () => import( './business-profile' ) );
const WebhooksPage = lazyTab( () => import( './webhooks' ) );
const AutoResponsePage = lazyTab( () => import( './auto-response' ) );
const ScriptsPage = lazyTab( () => import( './scripts' ) );
const FlowResponsesPage = lazyTab( () => import( './flow-responses' ) );
const FlowHubPage = lazyTab( () => import( './flow-hub' ) );
const MigrationPage = lazyTab( () => import( './migration' ) );
const AiAgentPage = lazyTab( () => import( './ai-agent' ) );

interface PageProps {
  signOut?: () => void;
  user?: any;
}

// ─── Bot Menu & Customer Service Menu Data ───
const BOT_MENU = [
  { row: 1, section: 'Start Here', icon: '🚀', title: 'Customer Service', description: 'Requests, appointments, documents, and support', action: 'Opens Customer Service list' },
  { row: 2, section: 'Start Here', icon: '🔔', title: 'Subscribe for Updates', description: 'Get updates, offers, and service news', action: 'Opens subscribe form' },
  { row: 3, section: 'Start Here', icon: '🆔', title: 'Find Profile ID', description: 'Locate your subscription or profile ID', action: 'Opens ID lookup' },
  { row: 4, section: 'Start Here', icon: '💳', title: 'Make a Payment', description: 'Pay an invoice or complete a pending payment', action: 'Opens payment lookup' },
  { row: 5, section: 'Explore WECARE', icon: '🛍️', title: 'Explore Store', description: 'Browse services, brands, and offers', action: 'CTA link → wecare.digital' },
  { row: 6, section: 'Explore WECARE', icon: '🎁', title: 'Gift Cards', description: 'Send a digital gift card', action: 'CTA link → wecare.digital/perks/' },
  { row: 7, section: 'Explore WECARE', icon: '🇮🇳', title: 'WECARE.DIGITAL', description: 'Discover WECARE.DIGITAL and services', action: 'Info text + evolving services' },
  { row: 8, section: 'Help & Answers', icon: '❓', title: 'FAQs', description: 'Find answers to common questions', action: 'CTA link → wecare.digital/faq' },
  { row: 9, section: 'Help & Answers', icon: '💛', title: 'About WECARE.DIGITAL', description: 'Learn more about WECARE.DIGITAL', action: 'CTA link → wecare.digital' },
];

const CUSTOMERSERVICE_MENU = [
  { row: 1, section: 'Existing Order', icon: '📋', title: 'Submit Request', description: 'Raise a request for an existing order after verified payment', flowId: canonicalFlowId('submit_request')!, keywords: 'Submit Request' },
  // Track has no canonical Flow (served by the order tracking API + /orders/); the old staff
  // id was a DEPRECATED flow. Show a dash rather than a dead id.
  { row: 2, section: 'Request Status', icon: '🔍', title: 'Track Request', description: 'Check the status of your request', flowId: canonicalFlowId('track_request') ?? '-', keywords: 'track request, track, status' },
  { row: 3, section: 'Existing Request', icon: '✏️', title: 'Request Amendment', description: 'Edit or correct a submitted request; Flow remains a draft', flowId: canonicalFlowId('amend_request')!, keywords: 'Request Amendment' },
  { row: 4, section: 'Schedule', icon: '📅', title: 'Appointment', description: 'Schedule a consultation or service visit', flowId: '1475722977488573', keywords: 'appointment, schedule, meeting' },
  { row: 5, section: 'Medical Tourism', icon: '💊', title: 'RX Slot', description: 'Schedule a medical tourism or prescription-related visit', flowId: '1892784521355352', keywords: 'rx slot, rx, prescription' },
  { row: 6, section: 'Documents', icon: '📄', title: 'Drop Docs', description: 'Send supporting documents securely; Flow remains a draft', flowId: canonicalFlowId('drop_docs')!, keywords: 'Drop Docs' },
  { row: 7, section: 'Business Support', icon: '🏢', title: 'Enterprise Assist', description: 'Corporate, B2B, and bulk enquiries', flowId: '2132515287534606', keywords: 'enterprise, b2b, corporate' },
  // flowId and keywords mirror DEFAULT_FLOW_TRIGGERS['leave_review'] in the inbound handler,
  // same order, via src/lib/reviewEntry.ts — REVIEW_FLOW_ID is WD_Leave_Review_v2, PUBLISHED
  // on WABA 1. Guarded by tests/test_leave_review_wiring.py.
  { row: 8, section: 'Feedback', icon: '⭐', title: 'Leave Review', description: 'Share your experience with our service', flowId: REVIEW_FLOW_ID, keywords: REVIEW_ENTRY_KEYWORDS.join(', ') },
  { row: 9, section: 'Help', icon: '❓', title: 'FAQ', description: 'View frequently asked questions', flowId: '-', keywords: 'faq, help, questions' },
];

const pill = ( bg: string, color: string ): React.CSSProperties => ( {
  display: 'inline-block', padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: bg, color,
} );

// ─── Bot Menu Tab Component ───
const BotMenuTab: React.FC = () => (
  <div style={ { padding: '0 4px' } }>
    <WhatsAppServiceDirectory />
    {/* Main Bot Menu */ }
    <h3 style={ { fontSize: 15, fontWeight: 700, color: '#1a3a2a', margin: '0 0 6px' } }>WhatsApp Bot Menu (Persistent Menu)</h3>
    <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 14px' } }>9 menu items across 3 sections — shown when users open the WhatsApp chat.</p>
    <div style={ { overflowX: 'auto', marginBottom: 28 } }>
      <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
        <thead>
          <tr style={ { borderBottom: '2px solid #f3f4f6' } }>
            { [ '#', 'Section', 'Title', 'Description', 'Action' ].map( h => (
              <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
            ) ) }
          </tr>
        </thead>
        <tbody>
          { BOT_MENU.map( m => (
            <tr key={ m.row } style={ { borderBottom: '1px solid #f3f4f6' } }>
              <td style={ { padding: '8px 10px', color: '#6b7280', fontWeight: 600 } }>{ m.row }</td>
              <td style={ { padding: '8px 10px' } }>
                <span style={ pill( m.section === 'Start Here' ? '#f0fdf4' : m.section === 'Explore WECARE' ? '#eff6ff' : '#fffbeb', m.section === 'Start Here' ? '#059669' : m.section === 'Explore WECARE' ? '#2563eb' : '#d97706' ) }>{ m.section }</span>
              </td>
              <td style={ { padding: '8px 10px', fontWeight: 600, color: '#1a3a2a' } }>{ m.icon } { m.title }</td>
              <td style={ { padding: '8px 10px', color: '#374151' } }>{ m.description }</td>
              <td style={ { padding: '8px 10px', color: '#6b7280', fontSize: 12 } }>{ m.action }</td>
            </tr>
          ) ) }
        </tbody>
      </table>
    </div>

    {/* Customer Service Sub-Menu */ }
    <h3 style={ { fontSize: 15, fontWeight: 700, color: '#1a3a2a', margin: '0 0 6px' } }>🚀 Customer Service Menu (Interactive List)</h3>
    <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 14px' } }>Service menu reference. The directory above shows current keyword entry points and publication status.</p>
    <div style={ { overflowX: 'auto' } }>
      <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
        <thead>
          <tr style={ { borderBottom: '2px solid #f3f4f6' } }>
            { [ '#', 'Section', 'Title', 'Description', 'Flow ID', 'Keywords' ].map( h => (
              <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
            ) ) }
          </tr>
        </thead>
        <tbody>
          { CUSTOMERSERVICE_MENU.map( m => (
            <tr key={ m.row } style={ { borderBottom: '1px solid #f3f4f6' } }>
              <td style={ { padding: '8px 10px', color: '#6b7280', fontWeight: 600 } }>{ m.row }</td>
              <td style={ { padding: '8px 10px' } }><span style={ pill( '#f9fafb', '#6b7280' ) }>{ m.section }</span></td>
              <td style={ { padding: '8px 10px', fontWeight: 600, color: '#1a3a2a' } }>{ m.icon } { m.title }</td>
              <td style={ { padding: '8px 10px', color: '#374151' } }>{ m.description }</td>
              <td style={ { padding: '8px 10px', fontFamily: 'monospace', fontSize: 11, color: '#6b7280' } }>{ m.flowId }</td>
              <td style={ { padding: '8px 10px', fontSize: 11, color: '#6b7280' } }>{ m.keywords }</td>
            </tr>
          ) ) }
        </tbody>
      </table>
    </div>
  </div>
);

const TABS: ShellTab[] = [
  { id: 'ai-agent', label: '🤖 AI Agent' },
  { id: 'auto-response', label: 'Auto-Response' },
  { id: 'bot-menu', label: 'Bot Menu' },
  { id: 'scripts', label: 'Scripts' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'templates', label: 'Templates' },
  { id: 'lists', label: 'List Msgs', divider: true },
  { id: 'flows', label: 'Flows' },
  { id: 'flow-hub', label: 'Flows Hub' },
  { id: 'flow-responses', label: 'Flow Data' },
  { id: 'welcome', label: 'Welcome' },
  { id: 'calling', label: 'Calling', divider: true },
  { id: 'groups', label: 'Groups' },
  { id: 'logs', label: 'Logs', divider: true },
  { id: 'profile', label: 'Profile', divider: true },
  { id: 'webhooks', label: 'Webhooks' },
  { id: 'waba', label: 'WABA' },
  { id: 'migration', label: 'Migration' },
];

const WhatsAppSettingsPage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut }>
    <PageShell
      title="WhatsApp"
      subtitle="Business API — Messaging, Campaigns, Templates, Bot Menu & More"
      tabs={ TABS }
      defaultTab="bot-menu"
    >
      { ( activeTab ) => (
        <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading...</div> }>
          { activeTab === 'ai-agent' && <AiAgentPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'auto-response' && <AutoResponsePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'bot-menu' && <BotMenuTab /> }
          { activeTab === 'scripts' && <ScriptsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'campaign' && <CampaignPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'templates' && <TemplatesPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'lists' && <InteractiveListsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flows' && <FlowsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flow-hub' && <FlowHubPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flow-responses' && <FlowResponsesPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'welcome' && <WelcomePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'calling' && <CallingPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'groups' && <GroupsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'logs' && <LogsPage signOut={ signOut } user={ user } embedded channel="whatsapp" /> }
          { activeTab === 'profile' && <BusinessProfilePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'webhooks' && <WebhooksPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'waba' && <WABADashboard signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'migration' && <MigrationPage signOut={ signOut } user={ user } embedded /> }
        </Suspense>
      ) }
    </PageShell>
  </Layout>
);

export default WhatsAppSettingsPage;
