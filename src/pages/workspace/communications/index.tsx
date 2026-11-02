/**
 * Canonical Communications workspace.
 *
 * Product rule: operators work by job, not by transport. Communications therefore has only
 * two primary modes: Inbox and Manage. WhatsApp/SMS/RCS/email/voice/push are filters or managed
 * capabilities inside those modes, never another top-level navigation tree.
 *
 * Migration note: the existing proven channel/tool components are embedded here first. Their old
 * Active /workspace/engage/inbox, channels, logs and settings routes remain until each one is replaced by a redirect.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

type EmbeddedProps = PageProps & { channel?: string };

function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

// The unified inbox is already the canonical cross-channel message reader. Keep its implementation
// intact while moving its product destination away from the retired Engage namespace.
const UnifiedInbox = lazyTab<EmbeddedProps>( () => import( '../engage/inbox' ) );

const SmsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/channels/Sms' ) );
const RcsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/channels/Rcs' ) );
const EmailPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/channels/Ses' ) );
const VoicePanel = lazyTab<PageProps>( () => import( '../../../components/workspace/channels/Voice' ) );
const PushPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/channels/Push' ) );

const TemplatesPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Content' ) );
const FlowsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/flow-hub' ) );
const AutomationPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Automation' ) );
const ScheduledPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Scheduled' ) );
const AnalyticsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Analytics' ) );
const UsagePanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Cost' ) );
const SearchPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Search' ) );
const LogsPanel = lazyTab<PageProps>( () => import( '../engage/logs' ) );
const DocsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/DocsScraper' ) );
const LinksPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/messaging/Links' ) );

const WhatsAppProfilePanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/business-profile' ) );
const CallingPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/calling' ) );
const WebhooksPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/webhooks' ) );
const AiAgentPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/ai-agent' ) );
const WabaPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/waba-dashboard' ) );
const EmbeddedSignupPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/embedded-signup' ) );
const ConnectedAccountsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/connected-accounts' ) );
const MyAccountPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/my-account' ) );
const BsuidPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/bsuid' ) );
const MigrationPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/migration' ) );
const SendTestPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/send-test' ) );
const CampaignPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/campaign' ) );
const ListsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/interactive-lists' ) );
const AutoResponsePanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/auto-response' ) );
const ConversionsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/conversions-api' ) );
const CtwaPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/ctwa-ads' ) );
const TechPartnerPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/tech-partner' ) );
const WhatsAppTemplatesPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/templates' ) );
const TemplateBuilderPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/template-builder' ) );
const CatalogBuilderPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/catalog-builder' ) );
const WhatsAppFlowsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/flows' ) );
const FlowPublishPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/flow-publish' ) );
const GroupsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/groups' ) );
const CostControlsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/cost-controls' ) );
const ScriptsPanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/scripts' ) );
const WelcomePanel = lazyTab<PageProps>( () => import( '../../../components/workspace/whatsapp/welcome' ) );
const BotMenuPanel = lazyTab<{}>( () => import( '../../../components/workspace/whatsapp/bot-menu' ) );

type SectionId =
  | 'whatsapp'
  | 'sms'
  | 'rcs'
  | 'email'
  | 'voice'
  | 'push'
  | 'templates'
  | 'flows'
  | 'automation'
  | 'scheduled'
  | 'ai'
  | 'delivery'
  | 'analytics'
  | 'usage'
  | 'search'
  | 'docs'
  | 'links'
  | 'calling'
  | 'webhooks';

type WhatsAppTool =
  | 'waba'
  | 'embedded-signup'
  | 'connected-accounts'
  | 'my-account'
  | 'profile'
  | 'bsuid'
  | 'migration'
  | 'tech-partner'
  | 'send-test'
  | 'campaign'
  | 'lists'
  | 'welcome'
  | 'bot-menu'
  | 'auto-response'
  | 'scripts'
  | 'templates'
  | 'template-builder'
  | 'flows'
  | 'flow-publish'
  | 'flow-responses'
  | 'catalog-builder'
  | 'groups'
  | 'calling'
  | 'webhooks'
  | 'cost-controls'
  | 'ctwa-ads'
  | 'conversions-api'
  | 'ai-agent';

const MANAGE_GROUPS: Array<{
  title: string;
  hint: string;
  items: Array<{ id: SectionId; label: string; detail: string; status?: string }>;
}> = [
  {
    title: 'Channels & identities',
    hint: 'Provider identity, routing and channel operations.',
    items: [
      { id: 'whatsapp', label: 'WhatsApp', detail: 'Business profile and account identity' },
      { id: 'sms', label: 'SMS', detail: 'AWS End User Messaging · India routing stays server-owned' },
      { id: 'rcs', label: 'RCS', detail: 'Sinch India messaging and delivery events' },
      { id: 'email', label: 'Email', detail: 'Email sending and activity' },
      { id: 'voice', label: 'Voice', detail: 'Voice operations and call records' },
      { id: 'push', label: 'Push', detail: 'Registered devices and notification delivery' },
    ],
  },
  {
    title: 'Content & journeys',
    hint: 'Reusable communication content and customer journeys.',
    items: [
      { id: 'templates', label: 'Templates', detail: 'Cross-channel content library' },
      { id: 'flows', label: 'Flows', detail: 'WhatsApp Flow registry, submissions and journeys' },
      { id: 'scheduled', label: 'Scheduled sends', detail: 'Upcoming scheduled communication' },
    ],
  },
  {
    title: 'Automation',
    hint: 'Rules and assisted communication.',
    items: [
      { id: 'automation', label: 'Rules', detail: 'Cross-channel automation rules' },
      { id: 'ai', label: 'AI Agent', detail: 'Customer-facing agent configuration and routing' },
    ],
  },
  {
    title: 'Operations',
    hint: 'Delivery, observability and provider controls.',
    items: [
      { id: 'delivery', label: 'Delivery & logs', detail: 'Cross-channel message history and failures' },
      { id: 'webhooks', label: 'Webhooks', detail: 'WhatsApp webhook subscriptions and health' },
      { id: 'calling', label: 'Calling', detail: 'WhatsApp Business Calling' },
      { id: 'analytics', label: 'Analytics', detail: 'Cross-channel volume and delivery metrics' },
      { id: 'usage', label: 'Usage estimate', detail: 'Planning estimate, not provider billing' },
      { id: 'search', label: 'Message search', detail: 'Find message history across channels' },
      { id: 'links', label: 'Short links', detail: 'Tracked links and click analytics' },
      { id: 'docs', label: 'Knowledge sync', detail: 'Documentation ingestion tools' },
    ],
  },
];

const WHATSAPP_GROUPS: Array<{
  title: string;
  items: Array<{ id: WhatsAppTool; label: string; detail: string }>;
}> = [
  {
    title: 'Business & account',
    items: [
      { id: 'waba', label: 'Business accounts', detail: 'WABA dashboard and account state' },
      { id: 'embedded-signup', label: 'Connect WABA', detail: 'Embedded signup and onboarding' },
      { id: 'connected-accounts', label: 'Connected accounts', detail: 'Staff-managed business connections' },
      { id: 'my-account', label: 'My WhatsApp account', detail: 'Own-account partner surface and payment readiness' },
      { id: 'profile', label: 'Business profile', detail: 'Business identity presented to customers' },
      { id: 'bsuid', label: 'BSUID & usernames', detail: 'Business-scoped identity and username operations' },
      { id: 'migration', label: 'Migration', detail: 'Number and WABA migration tools' },
      { id: 'tech-partner', label: 'Tech Partner readiness', detail: 'Partner and app readiness checks' },
    ],
  },
  {
    title: 'Messaging & campaigns',
    items: [
      { id: 'send-test', label: 'Send test', detail: 'Authorized provider test actions' },
      { id: 'campaign', label: 'Campaigns', detail: 'WhatsApp campaign composer' },
      { id: 'lists', label: 'Interactive lists', detail: 'Interactive list messages' },
      { id: 'welcome', label: 'Welcome', detail: 'Welcome-message behavior' },
      { id: 'bot-menu', label: 'Bot & service menu', detail: 'Customer entry points and service menu reference' },
      { id: 'auto-response', label: 'Auto response', detail: 'Keyword and automatic response rules' },
      { id: 'scripts', label: 'Scripts', detail: 'WhatsApp automation script configuration' },
      { id: 'ai-agent', label: 'AI Agent', detail: 'WhatsApp customer-agent configuration' },
    ],
  },
  {
    title: 'Templates, Flows & commerce',
    items: [
      { id: 'templates', label: 'WhatsApp templates', detail: 'Template inventory and provider state' },
      { id: 'template-builder', label: 'Create template', detail: 'Template creation workflow' },
      { id: 'flows', label: 'Flows', detail: 'Flow inventory and lifecycle' },
      { id: 'flow-publish', label: 'Flow publish', detail: 'Publication checks and actions' },
      { id: 'catalog-builder', label: 'Catalog & Flow mapping', detail: 'WhatsApp catalog and Flow mapping tools' },
    ],
  },
  {
    title: 'Operations',
    items: [
      { id: 'groups', label: 'Groups', detail: 'WhatsApp Groups operations' },
      { id: 'calling', label: 'Calling', detail: 'WhatsApp Business Calling' },
      { id: 'webhooks', label: 'Webhooks', detail: 'Webhook subscriptions and diagnostics' },
      { id: 'cost-controls', label: 'Cost controls', detail: 'WhatsApp-specific usage controls' },
      { id: 'ctwa-ads', label: 'Ads to WhatsApp', detail: 'CTWA setup and operations' },
      { id: 'conversions-api', label: 'Conversions API', detail: 'Conversion event configuration' },
    ],
  },
];

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

const CommunicationsPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const view = one( router.query.view ) === 'manage' ? 'manage' : 'inbox';
  const rawSection = one( router.query.section );
  const rawTool = one( router.query.tool );
  const section = rawSection as SectionId;
  const whatsappTool = rawTool as WhatsAppTool;

  const go = ( nextView: 'inbox' | 'manage', nextSection?: SectionId, nextTool?: WhatsAppTool ) => {
    const query: Record<string, string> = { view: nextView };
    if ( nextSection ) query.section = nextSection;
    if ( nextTool ) query.tool = nextTool;
    void router.push( { pathname: '/workspace/communications', query } );
  };

  const openManageItem = ( id: SectionId ) => {
    go( 'manage', id );
  };

  const renderWhatsApp = () => {
    if ( !whatsappTool ) {
      return (
        <div className="wa-directory">
          { WHATSAPP_GROUPS.map( ( group ) => (
            <section className="wa-group" key={ group.title }>
              <h3>{ group.title }</h3>
              <div className="manage-list">
                { group.items.map( ( item ) => (
                  <button key={ item.id } type="button" className="manage-row"
                    onClick={ () => go( 'manage', 'whatsapp', item.id ) }>
                    <span><strong>{ item.label }</strong><small>{ item.detail }</small></span>
                    <span aria-hidden="true">›</span>
                  </button>
                ) ) }
              </div>
            </section>
          ) ) }
        </div>
      );
    }

    switch ( whatsappTool ) {
      case 'waba': return <WabaPanel signOut={ signOut } user={ user } embedded />;
      case 'embedded-signup': return <EmbeddedSignupPanel signOut={ signOut } user={ user } embedded />;
      case 'connected-accounts': return <ConnectedAccountsPanel signOut={ signOut } user={ user } embedded />;
      case 'my-account': return <MyAccountPanel signOut={ signOut } user={ user } embedded />;
      case 'profile': return <WhatsAppProfilePanel signOut={ signOut } user={ user } embedded />;
      case 'bsuid': return <BsuidPanel signOut={ signOut } user={ user } embedded />;
      case 'migration': return <MigrationPanel signOut={ signOut } user={ user } embedded />;
      case 'tech-partner': return <TechPartnerPanel signOut={ signOut } user={ user } embedded />;
      case 'send-test': return <SendTestPanel signOut={ signOut } user={ user } embedded />;
      case 'campaign': return <CampaignPanel signOut={ signOut } user={ user } embedded />;
      case 'lists': return <ListsPanel signOut={ signOut } user={ user } embedded />;
      case 'welcome': return <WelcomePanel signOut={ signOut } user={ user } embedded />;
      case 'bot-menu': return <BotMenuPanel />;
      case 'auto-response': return <AutoResponsePanel signOut={ signOut } user={ user } embedded />;
      case 'scripts': return <ScriptsPanel signOut={ signOut } user={ user } embedded />;
      case 'templates': return <WhatsAppTemplatesPanel signOut={ signOut } user={ user } embedded />;
      case 'template-builder': return <TemplateBuilderPanel signOut={ signOut } user={ user } embedded />;
      case 'flows': return <WhatsAppFlowsPanel signOut={ signOut } user={ user } embedded />;
      case 'flow-publish': return <FlowPublishPanel signOut={ signOut } user={ user } embedded />;
      case 'flow-responses': return <UnifiedInbox signOut={ signOut } user={ user } embedded channel="whatsapp" />;
      case 'catalog-builder': return <CatalogBuilderPanel signOut={ signOut } user={ user } embedded />;
      case 'groups': return <GroupsPanel signOut={ signOut } user={ user } embedded />;
      case 'calling': return <CallingPanel signOut={ signOut } user={ user } embedded />;
      case 'webhooks': return <WebhooksPanel signOut={ signOut } user={ user } embedded />;
      case 'cost-controls': return <CostControlsPanel signOut={ signOut } user={ user } embedded />;
      case 'ctwa-ads': return <CtwaPanel signOut={ signOut } user={ user } embedded />;
      case 'conversions-api': return <ConversionsPanel signOut={ signOut } user={ user } embedded />;
      case 'ai-agent': return <AiAgentPanel signOut={ signOut } user={ user } embedded />;
      default: return null;
    }
  };

  const renderSection = () => {
    switch ( section ) {
      case 'whatsapp': return renderWhatsApp();
      case 'sms': return <SmsPanel signOut={ signOut } user={ user } embedded />;
      case 'rcs': return <RcsPanel signOut={ signOut } user={ user } embedded />;
      case 'email': return <EmailPanel signOut={ signOut } user={ user } embedded />;
      case 'voice': return <VoicePanel signOut={ signOut } user={ user } embedded />;
      case 'push': return <PushPanel signOut={ signOut } user={ user } embedded />;
      case 'templates': return <TemplatesPanel signOut={ signOut } user={ user } embedded />;
      case 'flows': return <FlowsPanel signOut={ signOut } user={ user } embedded />;
      case 'automation': return <AutomationPanel signOut={ signOut } user={ user } embedded />;
      case 'scheduled': return <ScheduledPanel signOut={ signOut } user={ user } embedded />;
      case 'ai': return <AiAgentPanel signOut={ signOut } user={ user } embedded />;
      case 'delivery': return <LogsPanel signOut={ signOut } user={ user } embedded />;
      case 'webhooks': return <WebhooksPanel signOut={ signOut } user={ user } embedded />;
      case 'calling': return <CallingPanel signOut={ signOut } user={ user } embedded />;
      case 'analytics': return <AnalyticsPanel signOut={ signOut } user={ user } embedded />;
      case 'usage': return <UsagePanel signOut={ signOut } user={ user } embedded />;
      case 'search': return <SearchPanel signOut={ signOut } user={ user } embedded />;
      case 'docs': return <DocsPanel signOut={ signOut } user={ user } embedded />;
      case 'links': return <LinksPanel signOut={ signOut } user={ user } embedded />;
      default: return null;
    }
  };

  const selected = rawSection && MANAGE_GROUPS.flatMap( ( g ) => g.items )
    .find( ( item ) => item.id === rawSection );
  const selectedWhatsAppTool = rawTool
    ? WHATSAPP_GROUPS.flatMap( ( group ) => group.items ).find( ( item ) => item.id === rawTool )
    : undefined;

  return (
    <>
      <SEO title="Communications" description="Unified customer communications workspace." noindex />

      <main className="comms-page">
        <header className="comms-head">
          <div>
            <p className="comms-eyebrow">Workspace</p>
            <h1>Communications</h1>
            <p>One inbox for daily work. One manage surface for everything behind it.</p>
          </div>
        </header>

        <nav className="comms-tabs" aria-label="Communications">
          <button type="button" className={ view === 'inbox' ? 'active' : '' }
            aria-current={ view === 'inbox' ? 'page' : undefined }
            onClick={ () => go( 'inbox' ) }>Inbox</button>
          <button type="button" className={ view === 'manage' ? 'active' : '' }
            aria-current={ view === 'manage' ? 'page' : undefined }
            onClick={ () => go( 'manage' ) }>Manage</button>
        </nav>

        <Suspense fallback={ <div className="comms-loading">Loading…</div> }>
          { view === 'inbox' && (
            <section aria-label="Unified inbox">
              <UnifiedInbox signOut={ signOut } user={ user } embedded />
            </section>
          ) }

          { view === 'manage' && !selected && (
            <section className="manage-home" aria-label="Manage communications">
              { MANAGE_GROUPS.map( ( group ) => (
                <div className="manage-group" key={ group.title }>
                  <div className="manage-group-head">
                    <h2>{ group.title }</h2>
                    <p>{ group.hint }</p>
                  </div>
                  <div className="manage-list">
                    { group.items.map( ( item ) => (
                      <button key={ item.id } type="button" className="manage-row"
                        onClick={ () => openManageItem( item.id ) }>
                        <span>
                          <strong>{ item.label }</strong>
                          <small>{ item.detail }</small>
                        </span>
                        <span aria-hidden="true">›</span>
                      </button>
                    ) ) }
                  </div>
                </div>
              ) ) }
            </section>
          ) }

          { view === 'manage' && selected && (
            <section aria-label={ selected.label }>
              <button type="button" className="manage-back"
                onClick={ () => selectedWhatsAppTool ? go( 'manage', 'whatsapp' ) : go( 'manage' ) }>
                ← { selectedWhatsAppTool ? 'WhatsApp' : 'Manage' }
              </button>
              <div className="manage-section-head">
                <h2>{ selectedWhatsAppTool?.label || selected.label }</h2>
                <p>{ selectedWhatsAppTool?.detail || selected.detail }</p>
              </div>
              { renderSection() }
            </section>
          ) }
        </Suspense>
      </main>

      <style jsx>{`
        .comms-page{width:min(100%,1240px);margin:0 auto;padding:clamp(16px,3vw,32px);box-sizing:border-box;min-width:0}
        .comms-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:18px}
        .comms-eyebrow{margin:0 0 4px;color:var(--text-muted);font-size:var(--text-xs);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
        .comms-head h1{margin:0;font-size:clamp(28px,5vw,48px);line-height:1.05;letter-spacing:-.035em;color:var(--text)}
        .comms-head p:not(.comms-eyebrow){margin:8px 0 0;color:var(--text-muted);font-size:var(--text-md);max-width:680px}
        .comms-tabs{display:flex;gap:6px;padding:4px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:14px;width:max-content;max-width:100%;margin-bottom:20px}
        .comms-tabs button{min-width:108px;min-height:44px;border:0;border-radius:10px;background:transparent;color:var(--text-muted);font:inherit;font-weight:700;cursor:pointer;padding:8px 18px}
        .comms-tabs button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
        .manage-home{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
        .manage-group{min-width:0;background:#fff;border:1px solid var(--border);border-radius:16px;overflow:hidden}
        .manage-group-head{padding:18px 18px 12px}
        .manage-group-head h2,.manage-section-head h2{margin:0;color:var(--text);font-size:var(--h4)}
        .manage-group-head p,.manage-section-head p{margin:4px 0 0;color:var(--text-muted);font-size:var(--text-sm)}
        .manage-list{border-top:1px solid var(--border-light)}
        .manage-row{width:100%;min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;text-align:left;padding:12px 16px;border:0;border-top:1px solid var(--border-light);background:#fff;color:var(--text);font:inherit;cursor:pointer}
        .manage-row:first-child{border-top:0}
        .manage-row:hover,.manage-row:focus-visible{background:var(--bg-secondary)}
        .manage-row span:first-child{min-width:0;display:flex;flex-direction:column;gap:2px}
        .manage-row strong{font-size:var(--text-md)}
        .manage-row small{font-size:var(--text-xs);color:var(--text-muted);line-height:1.4}
        .manage-row span:last-child{font-size:24px;color:var(--text-muted)}
        .manage-back{min-height:44px;border:0;background:transparent;color:var(--accent);font:inherit;font-weight:700;cursor:pointer;padding:8px 0;margin-bottom:6px}
        .manage-section-head{margin-bottom:14px}
        .wa-directory{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
        .wa-group{min-width:0;background:#fff;border:1px solid var(--border);border-radius:16px;overflow:hidden}
        .wa-group h3{margin:0;padding:16px 16px 12px;font-size:var(--text-md);color:var(--text)}

        .comms-loading{padding:48px;text-align:center;color:var(--text-muted)}
        @media(max-width:800px){
          .manage-home,.wa-directory{grid-template-columns:1fr}
          .comms-page{padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right));padding-bottom:max(24px,env(safe-area-inset-bottom))}
          .comms-head{align-items:flex-start}
          .comms-tabs{width:100%}
          .comms-tabs button{flex:1;min-width:0}
        }
        @media(max-width:420px){
          .comms-page{padding-top:14px}
          .comms-head h1{font-size:30px}
          .manage-row{padding:12px}
        }
        @media(prefers-reduced-motion:reduce){
          .manage-row,.comms-tabs button{scroll-behavior:auto}
        }
      `}</style>
    </>
  );
};

export default CommunicationsPage;
