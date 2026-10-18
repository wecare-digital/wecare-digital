import WhatsAppServiceDirectory from '../../../../components/WhatsAppServiceDirectory';
import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../../lib/canonicalFlows';
/**
 * WhatsApp Settings — All WhatsApp features except Inbox
 * Uses PageShell for section header + scrollable tab bar
 */

import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
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

// FEAT-005: the tab bodies moved OUT of the routes tree (src/pages/workspace/**) into
// src/components/workspace/whatsapp/** so the physical route count drops. The lazy-tab
// contract is unchanged — each still loads on demand and takes { signOut, user, embedded }.
// Paths are kept as string literals so webpack can statically resolve each chunk.
const WABADashboard = lazyTab( () => import( '../../../../components/workspace/whatsapp/waba-dashboard' ) );
const TemplatesPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/templates' ) );
const WelcomePage = lazyTab( () => import( '../../../../components/workspace/whatsapp/welcome' ) );
const CampaignPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/campaign' ) );
// Unified logs, preset to WhatsApp. ./logs was 265 lines over the same canonical
// table as dm/logs; its error decoding, CSV export, pagination and contact-name
// resolution all moved into dm/logs rather than being dropped. Still a real route.
const LogsPage = lazyTab( () => import( '../logs' ) );
const InteractiveListsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/interactive-lists' ) );
const FlowsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/flows' ) );
const CallingPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/calling' ) );
const GroupsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/groups' ) );
const BusinessProfilePage = lazyTab( () => import( '../../../../components/workspace/whatsapp/business-profile' ) );
const WebhooksPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/webhooks' ) );
const AutoResponsePage = lazyTab( () => import( '../../../../components/workspace/whatsapp/auto-response' ) );
const ScriptsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/scripts' ) );
const FlowResponsesPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/flow-responses' ) );
const FlowHubPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/flow-hub' ) );
const MigrationPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/migration' ) );
const AiAgentPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/ai-agent' ) );
const ConnectedAccountsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/connected-accounts' ) );
const EmbeddedSignupPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/embedded-signup' ) );
const MyAccountPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/my-account' ) );
const BsuidPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/bsuid' ) );
const TechPartnerPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/tech-partner' ) );
const TemplateBuilderPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/template-builder' ) );
const FlowPublishPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/flow-publish' ) );
const CatalogBuilderPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/catalog-builder' ) );
const SendTestPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/send-test' ) );
const ConversionsApiPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/conversions-api' ) );
const CtwaAdsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/ctwa-ads' ) );
const CostControlsPage = lazyTab( () => import( '../../../../components/workspace/whatsapp/cost-controls' ) );

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
  { row: 6, section: 'Explore WECARE', icon: '🎁', title: 'Perks', description: 'Open Perks on WhatsApp', action: 'CTA link → wa.me/message/377GALDW4E26F1' },
  { row: 7, section: 'Explore WECARE', icon: '🇮🇳', title: 'WECARE.DIGITAL', description: 'Discover WECARE.DIGITAL and services', action: 'Info text + evolving services' },
  { row: 8, section: 'Help & Answers', icon: '❓', title: 'FAQs', description: 'Find answers to common questions', action: 'Answered in chat by faq-handler' },
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
  display: 'inline-block', padding: '2px 10px', borderRadius: 10, fontSize: 'var(--text-xs)', fontWeight: 600, background: bg, color,
} );

// ─── Bot Menu Tab Component ───
const BotMenuTab: React.FC = () => (
  <div style={ { padding: '0 4px' } }>
    <WhatsAppServiceDirectory />
    {/* Main Bot Menu */ }
    <h3 style={ { fontSize: 'var(--text-md)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 6px' } }>WhatsApp Bot Menu (Persistent Menu)</h3>
    <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 14px' } }>9 menu items across 3 sections — shown when users open the WhatsApp chat.</p>
    <div style={ { overflowX: 'auto', marginBottom: 28 } }>
      <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
        <thead>
          <tr style={ { borderBottom: '2px solid #f3f4f6' } }>
            { [ '#', 'Section', 'Title', 'Description', 'Action' ].map( h => (
              <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
            ) ) }
          </tr>
        </thead>
        <tbody>
          { BOT_MENU.map( m => (
            <tr key={ m.row } style={ { borderBottom: '1px solid #f3f4f6' } }>
              <td style={ { padding: '8px 10px', color: 'var(--text-muted)', fontWeight: 600 } }>{ m.row }</td>
              <td style={ { padding: '8px 10px' } }>
                <span style={ pill( m.section === 'Start Here' ? '#f0fdf4' : m.section === 'Explore WECARE' ? '#eff6ff' : '#fffbeb', m.section === 'Start Here' ? '#059669' : m.section === 'Explore WECARE' ? '#2563eb' : '#d97706' ) }>{ m.section }</span>
              </td>
              <td style={ { padding: '8px 10px', fontWeight: 600, color: 'var(--accent)' } }>{ m.icon } { m.title }</td>
              <td style={ { padding: '8px 10px', color: '#374151' } }>{ m.description }</td>
              <td style={ { padding: '8px 10px', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' } }>{ m.action }</td>
            </tr>
          ) ) }
        </tbody>
      </table>
    </div>

    {/* Customer Service Sub-Menu */ }
    <h3 style={ { fontSize: 'var(--text-md)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 6px' } }>🚀 Customer Service Menu (Interactive List)</h3>
    <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 14px' } }>Service menu reference. The directory above shows current keyword entry points and publication status.</p>
    <div style={ { overflowX: 'auto' } }>
      <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
        <thead>
          <tr style={ { borderBottom: '2px solid #f3f4f6' } }>
            { [ '#', 'Section', 'Title', 'Description', 'Flow ID', 'Keywords' ].map( h => (
              <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
            ) ) }
          </tr>
        </thead>
        <tbody>
          { CUSTOMERSERVICE_MENU.map( m => (
            <tr key={ m.row } style={ { borderBottom: '1px solid #f3f4f6' } }>
              <td style={ { padding: '8px 10px', color: 'var(--text-muted)', fontWeight: 600 } }>{ m.row }</td>
              <td style={ { padding: '8px 10px' } }><span style={ pill( 'var(--bg-secondary)', 'var(--text-muted)' ) }>{ m.section }</span></td>
              <td style={ { padding: '8px 10px', fontWeight: 600, color: 'var(--accent)' } }>{ m.icon } { m.title }</td>
              <td style={ { padding: '8px 10px', color: '#374151' } }>{ m.description }</td>
              <td style={ { padding: '8px 10px', fontFamily: 'monospace', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ m.flowId }</td>
              <td style={ { padding: '8px 10px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ m.keywords }</td>
            </tr>
          ) ) }
        </tbody>
      </table>
    </div>
  </div>
);

const TABS: ShellTab[] = [
  // Messaging
  { id: 'ai-agent', label: '🤖 AI Agent' },
  { id: 'auto-response', label: 'Auto-Response' },
  { id: 'bot-menu', label: 'Bot Menu' },
  { id: 'scripts', label: 'Scripts' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'send-test', label: 'Send Test' },
  { id: 'lists', label: 'List Msgs' },
  { id: 'welcome', label: 'Welcome' },
  { id: 'groups', label: 'Groups' },
  // Templates
  { id: 'templates', label: 'Templates', divider: true },
  { id: 'template-builder', label: 'Template Builder' },
  // Flows
  { id: 'flows', label: 'Flows', divider: true },
  { id: 'flow-hub', label: 'Flows Hub' },
  { id: 'flow-publish', label: 'Flow Publish' },
  { id: 'flow-responses', label: 'Flow Data' },
  { id: 'catalog-builder', label: 'Catalog & Flow Builder' },
  // AI / Marketing
  { id: 'ctwa-ads', label: 'Ads to WhatsApp', divider: true },
  { id: 'conversions-api', label: 'Conversions API' },
  // Account / WABA
  { id: 'waba', label: 'WABA', divider: true },
  { id: 'embedded-signup', label: 'Connect WABA' },
  { id: 'connected-accounts', label: 'Connected Accounts' },
  { id: 'my-account', label: 'My Account' },
  { id: 'profile', label: 'Profile' },
  { id: 'bsuid', label: 'BSUID & Usernames' },
  { id: 'migration', label: 'Migration' },
  { id: 'tech-partner', label: 'Tech Partner' },
  // Infra
  { id: 'webhooks', label: 'Webhooks', divider: true },
  { id: 'cost-controls', label: 'Cost Controls' },
  { id: 'calling', label: 'Calling' },
  { id: 'logs', label: 'Logs' },
];

// FEAT-005: deep-links arrive as /workspace/engage/whatsapp?tab=<id>. The query value is
// a tab id in TABS; fall back to the Bot Menu when it is absent or unrecognised.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  return id && TABS.some( ( t ) => t.id === id ) ? id : 'bot-menu';
}

const WhatsAppSettingsPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  // PageShell seeds its active tab from defaultTab once (useState). On a static export the
  // ?tab= query is only known after hydration, so key the shell on the resolved tab: when
  // the query arrives the shell remounts and opens the deep-linked tab.
  const defaultTab = resolveDefaultTab( router.query.tab );
  return (
  <Layout user={ user } onSignOut={ signOut }>
    <PageShell
      key={ defaultTab }
      title="WhatsApp"
      subtitle="Business API — Messaging, Campaigns, Templates, Bot Menu & More"
      tabs={ TABS }
      defaultTab={ defaultTab }
    >
      { ( activeTab ) => (
        <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading...</div> }>
          { activeTab === 'ai-agent' && <AiAgentPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'auto-response' && <AutoResponsePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'bot-menu' && <BotMenuTab /> }
          { activeTab === 'scripts' && <ScriptsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'campaign' && <CampaignPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'send-test' && <SendTestPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'templates' && <TemplatesPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'template-builder' && <TemplateBuilderPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'lists' && <InteractiveListsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flows' && <FlowsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flow-hub' && <FlowHubPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flow-publish' && <FlowPublishPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'flow-responses' && <FlowResponsesPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'catalog-builder' && <CatalogBuilderPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'welcome' && <WelcomePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'calling' && <CallingPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'groups' && <GroupsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'logs' && <LogsPage signOut={ signOut } user={ user } embedded channel="whatsapp" /> }
          { activeTab === 'profile' && <BusinessProfilePage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'webhooks' && <WebhooksPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'cost-controls' && <CostControlsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'ctwa-ads' && <CtwaAdsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'conversions-api' && <ConversionsApiPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'waba' && <WABADashboard signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'embedded-signup' && <EmbeddedSignupPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'connected-accounts' && <ConnectedAccountsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'my-account' && <MyAccountPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'bsuid' && <BsuidPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'migration' && <MigrationPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'tech-partner' && <TechPartnerPage signOut={ signOut } user={ user } embedded /> }
        </Suspense>
      ) }
    </PageShell>
  </Layout>
  );
};

export default WhatsAppSettingsPage;
