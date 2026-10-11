/**
 * WhatsApp Scripts — Content library for all automated messages.
 * Every text, menu, flow message, CTA, and response sent by the bot is listed here
 * for content review, improvement, and consistency management.
 *
 * Sources: SystemConfigTable configs, hardcoded defaults in Lambda, flow trigger messages.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import MaybeLayout from '../../../../components/MaybeLayout';
import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../../lib/canonicalFlows';

interface Props { signOut?: () => void; user?: any; embedded?: boolean; }

interface ScriptItem {
  id: string;
  category: string;
  trigger: string;
  messageType: string;
  content: string;
  phone: string;
  editable: boolean;
  configKey?: string;
}

const CATEGORIES = ['All', 'Welcome', 'Menu', 'CTA', 'Flow Trigger', 'Pay', 'CTA Link', 'System'];

const ScriptsPageBody: React.FC<Props> = () => {
  const toast = useToastContext();
  const [scripts, setScripts] = useState<ScriptItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [editId, setEditId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');

  const loadScripts = useCallback(async () => {
    setLoading(true);
    const items: ScriptItem[] = [];

    // Load live configs from SystemConfigTable
    let welcomeConfig: any = null;
    let mainMenuConfig: any = null;
    let ssMenuConfig: any = null;
    try { welcomeConfig = await api.getSystemConfig('wa_auto_response'); } catch {}
    try { mainMenuConfig = await api.getSystemConfig('welcome_message_config'); } catch {}
    try { ssMenuConfig = await api.getSystemConfig('customerservice_menu_config'); } catch {}

    // Welcome messages — use live config or defaults
    const welcomeText = welcomeConfig?.welcomeMessage || '(Using Lambda default — no custom welcome set)';
    items.push(
      { id: 'welcome_new', category: 'Welcome', trigger: 'Brand-new contact first message', messageType: 'Interactive List', content: 'Sends main menu list directly (no separate welcome text)', phone: 'Both', editable: true, configKey: 'wa_auto_response' },
      { id: 'welcome_hi', category: 'Welcome', trigger: '"hi" / "hello" / "menu" / "start" / "need help!"', messageType: 'Interactive List', content: 'Sends main menu list directly (1 message)', phone: 'Both', editable: false },
    );

    // Main menu — use live config or show defaults
    const mmHeader = mainMenuConfig?.header || 'Welcome to WECARE.DIGITAL';
    const mmBody = mainMenuConfig?.body || "Choose what you\u2019d like to do \u2014 get started, explore our services, or find quick answers.";
    const mmButton = mainMenuConfig?.buttonText || 'Get Started';
    const mmSections = mainMenuConfig?.sections?.length || 3;
    items.push(
      { id: 'main_menu', category: 'Menu', trigger: 'hi / menu / start / Explore More button', messageType: 'Interactive List', content: `Header: ${mmHeader}\nBody: ${mmBody}\nButton: ${mmButton}\nSections: ${mmSections}`, phone: 'Both', editable: true, configKey: 'welcome_message_config' },
    );

    // Selfservice menu — use live config or show defaults
    const ssHeader = ssMenuConfig?.header || 'Selfservice';
    const ssBody = ssMenuConfig?.body || "Choose what you\u2019d like to do...";
    const ssButton = ssMenuConfig?.buttonText || 'Browse Services';
    const ssSections = ssMenuConfig?.sections?.length || 10;
    items.push(
      { id: 'ss_menu', category: 'Menu', trigger: '"customerservice" / tapping Selfservice from main menu', messageType: 'Interactive List', content: `Header: ${ssHeader}\nBody: ${ssBody}\nButton: ${ssButton}\nSections: ${ssSections}`, phone: 'Both', editable: true, configKey: 'customerservice_menu_config' },
    );

    // CTA messages (hardcoded in Lambda — shown for content review)
    items.push(
      { id: 'cta_faq', category: 'CTA', trigger: 'Tapping FAQs from main menu', messageType: 'CTA URL', content: 'Body: Find quick answers about requests, payments, appointments, business hours, the app, and more.\nButton: Open FAQs\nURL: wecare.digital/faq\nFooter: WECARE.DIGITAL', phone: 'Both', editable: false },
      { id: 'cta_store', category: 'CTA', trigger: 'Tapping Explore Store from main menu', messageType: 'CTA URL', content: 'Body: Browse WECARE.DIGITAL services, brands, and offers — all in one place.\nButton: Visit Store\nURL: wecare.digital\nFooter: WECARE.DIGITAL', phone: 'Both', editable: false },
      { id: 'cta_gift', category: 'CTA', trigger: 'Tapping Gift Cards from main menu', messageType: 'CTA URL', content: 'Body: Send a digital gift card in just a few taps — quick, easy, and thoughtful.\nButton: View Gift Cards\nURL: wecare.digital/perks/\nFooter: WECARE.DIGITAL', phone: 'Both', editable: false },
      { id: 'cta_bharat', category: 'CTA', trigger: 'Tapping WECARE.DIGITAL / typing "bharat stack"', messageType: 'CTA URL', content: 'Body: Explore WECARE.DIGITAL and discover services designed for everyday Bharat.\nButton: Explore WECARE.DIGITAL\nURL: wecare.digital\nFooter: WECARE.DIGITAL', phone: 'Both', editable: false },
      { id: 'cta_about', category: 'CTA', trigger: 'Tapping About WECARE.DIGITAL from main menu', messageType: 'Text', content: '*Building digital railroads for everyday Bharat*\n\nWECARE.DIGITAL is a network of microservice brands serving everyday Bharat — across travel, paperwork, disputes, rituals, and reflection.\n\nMade to serve what matters most.', phone: 'Both', editable: false },
    );

    // Followup buttons
    items.push(
      { id: 'followup', category: 'System', trigger: 'After every CTA / About response', messageType: 'Reply Buttons', content: 'Body: What next? 👇\nButton 1: 🧭 Explore More → Main Menu\nButton 2: 🫶 All Set → Goodbye\nFooter: WECARE.DIGITAL', phone: 'Both', editable: false },
      { id: 'followup_done', category: 'System', trigger: 'Tapping All Set button', messageType: 'Text', content: 'Awesome — you\u2019re all set for now 💛\nType hi anytime to come back.', phone: 'Both', editable: false },
      { id: 'sys_reaction', category: 'System', trigger: 'Every inbound message (except reactions)', messageType: 'Reaction + Read Receipt', content: '👍 Auto-reaction + ✅ Read receipt (blue tick)', phone: 'Both', editable: false },
    );

    // Flow trigger messages — load from SystemConfig with fallback defaults
    const defaultFlowTriggers: Record<string, { keywords: string[]; message: { body: string; flowCta: string }; flowId: string }> = {
      submit_request: { keywords: ['submit request', 'sr'], message: { body: '📋 Start a new support request. Share the details and our team will follow up with you.', flowCta: 'Submit Request' }, flowId: canonicalFlowId('submit_request')! },
      track_request: { keywords: ['track request', 'track', 'status'], message: { body: '🔍 Check the status of your request anytime. Enter your reference ID below.', flowCta: 'Track Request' }, flowId: canonicalFlowId('track_request') ?? '-' },
      amend_request: { keywords: ['amend request', 'update request'], message: { body: '✏️ Need to make a change? Update your submitted request with the correct details.', flowCta: 'Update Request' }, flowId: canonicalFlowId('amend_request')! },
      schedule_appointment: { keywords: ['appointment', 'book appointment'], message: { body: '📅 Schedule a consultation or service visit at a time that works best for you.', flowCta: 'Book Appointment' }, flowId: '1475722977488573' },
      rx_slot: { keywords: ['rx slot', 'medical visit'], message: { body: '🩺 Arrange a medical tourism or prescription-related visit quickly and easily.', flowCta: 'Book Medical Visit' }, flowId: '1892784521355352' },
      drop_docs: { keywords: ['drop docs', 'upload documents'], message: { body: '🖇️ Send your supporting documents securely to help us process your request.', flowCta: 'Upload Documents' }, flowId: canonicalFlowId('drop_docs')! },
      enterprise_assist: { keywords: ['enterprise', 'b2b'], message: { body: '💼 Corporate, B2B, and bulk inquiries. Tell us what you need and our team will assist you.', flowCta: 'Enterprise Support' }, flowId: '2132515287534606' },
      // flowId and keywords mirror DEFAULT_FLOW_TRIGGERS['leave_review'] in the inbound
      // handler, as the same ordered list, via src/lib/reviewEntry.ts — REVIEW_FLOW_ID is
      // WD_Leave_Review_v2, PUBLISHED on WABA 1. Guarded by
      // tests/test_leave_review_wiring.py.
      leave_review: { keywords: REVIEW_ENTRY_KEYWORDS, message: { body: '⭐ Share your experience with us and help us improve our service.', flowCta: 'Leave Feedback' }, flowId: REVIEW_FLOW_ID },
      subscribe: { keywords: ['subscribe', 'register'], message: { body: '🔔 Get updates, offers, and service news. Fill in your details to stay connected.', flowCta: 'Subscribe for Updates' }, flowId: canonicalFlowId('subscribe') ?? '-' },
    };

    // Load overrides from SystemConfig
    const flowTriggers = { ...defaultFlowTriggers };
    try {
      const configTriggers = await api.getSystemConfig('flow_triggers_config');
      if (configTriggers && typeof configTriggers === 'object') {
        for (const [key, val] of Object.entries(configTriggers as Record<string, any>)) {
          if (val?.message?.body && flowTriggers[key]) {
            flowTriggers[key].message.body = val.message.body;
            flowTriggers[key].message.flowCta = val.message.flowCta || flowTriggers[key].message.flowCta;
          }
          if (val?.keywords && flowTriggers[key]) flowTriggers[key].keywords = val.keywords;
          if (val?.flowId && flowTriggers[key]) flowTriggers[key].flowId = val.flowId;
        }
      }
    } catch { /* use defaults */ }

    for (const [key, ft] of Object.entries(flowTriggers)) {
      items.push({
        id: `flow_${key}`,
        category: 'Flow Trigger',
        trigger: `Keywords: ${ft.keywords.slice(0, 4).join(', ')}`,
        messageType: 'Flow Form (data_exchange)',
        content: `Body: ${ft.message.body}\nCTA: ${ft.message.flowCta}\nFlow ID: ${ft.flowId}`,
        phone: 'Phone 1: Flow form\nPhone 2: Flow form (if flowId2) or CTA link',
        editable: true,
        configKey: 'flow_triggers_config',
      });
    }

    // Pay messages
    items.push(
      { id: 'pay_pulling', category: 'Pay', trigger: '"pay" / "payment" / "invoice" (Phone 1)', messageType: 'Text', content: '👀 Pulling your pending invoice...', phone: 'Phone 1', editable: false },
      { id: 'pay_no_dues', category: 'Pay', trigger: 'No pending invoices found', messageType: 'Text', content: '✅ No pending dues!', phone: 'Phone 1', editable: false },
      { id: 'pay_cta', category: 'Pay', trigger: '"pay" (Phone 2)', messageType: 'CTA URL Button', content: 'CTA: Pay Now → wecare.digital/r/pay', phone: 'Phone 2', editable: false },
    );

    // Phone 2 CTA links
    const ctaLinks = [
      { key: 'sr', label: 'Submit Request' }, { key: 'tr', label: 'Track Request' },
      { key: 'ar', label: 'Update Request' }, { key: 'sa', label: 'Book Appointment' },
      { key: 'rx', label: 'Book Medical Visit' }, { key: 'dd', label: 'Upload Documents' },
      { key: 'ea', label: 'Enterprise Support' }, { key: 'lr', label: 'Leave Feedback' },
      { key: 'sub', label: 'Subscribe' }, { key: 'pay', label: 'Pay Now' },
    ];
    for (const cl of ctaLinks) {
      items.push({
        id: `cta_${cl.key}`,
        category: 'CTA Link',
        trigger: `Phone 2 flow fallback for ${cl.label}`,
        messageType: 'CTA URL Button',
        content: `CTA: ${cl.label} → wecare.digital/r/${cl.key}`,
        phone: 'Phone 2 only',
        editable: false,
      });
    }

    // System messages
    items.push(
      { id: 'sys_reaction', category: 'System', trigger: 'Every inbound message (except reactions)', messageType: 'Reaction', content: '👍 Auto-reaction + read receipt', phone: 'Both', editable: false },
    );

    setScripts(items);
    setLoading(false);
  }, []);

  useEffect(() => { loadScripts(); }, [loadScripts]);

  const filtered = scripts.filter(s => {
    if (filter !== 'All' && s.category !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return s.content.toLowerCase().includes(q) || s.trigger.toLowerCase().includes(q) || s.id.toLowerCase().includes(q);
    }
    return true;
  });

  const catColor: Record<string, string> = {
    Welcome: '#d1f470', Menu: '#bfdbfe', CTA: '#ddd6fe', 'Flow Trigger': '#fde68a', Pay: '#bbf7d0', 'CTA Link': '#e0e7ff', System: '#f3f4f6',
  };

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ marginBottom: 12 }}>
        <p style={{ fontSize: 12, color: '#6b7280', margin: '0 0 8px' }}>
          Every automated message the bot sends. Use this to review content, check consistency, and improve copy.
        </p>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {CATEGORIES.map(c => (
            <button key={c} onClick={() => setFilter(c)} style={{
              padding: '4px 10px', borderRadius: 4, border: filter === c ? '1.5px solid #1a3a2a' : '1px solid #d1d5db',
              background: filter === c ? '#1a3a2a' : '#fff', color: filter === c ? '#fff' : '#374151',
              fontSize: 11, fontWeight: 500, cursor: 'pointer',
            }}>{c}</button>
          ))}
          <input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)}
                 style={{ padding: '4px 10px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 11, marginLeft: 'auto', width: 160 }} />
          <span style={{ fontSize: 11, color: '#9ca3af' }}>{filtered.length} scripts</span>
        </div>
      </div>

      {loading && <p style={{ color: '#9ca3af', fontSize: 12 }}>Loading...</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map(s => (
          <div key={s.id} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, background: '#fff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600, background: catColor[s.category] || '#f3f4f6' }}>{s.category}</span>
                <span style={{ fontSize: 10, color: '#9ca3af' }}>{s.messageType}</span>
              </div>
              <span style={{ fontSize: 10, color: '#9ca3af', fontFamily: 'monospace' }}>{s.id}</span>
            </div>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Trigger: {s.trigger}</div>
            <pre style={{ fontSize: 12, color: '#1a3a2a', margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'inherit', lineHeight: 1.5 }}>{s.content}</pre>
            <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 4 }}>Phone: {s.phone}</div>
          </div>
        ))}
      </div>
    </div>
  );
};
/** Shell-only view of the props: not all six pages declare these. */
type AnyShellProps = { user?: unknown; signOut?: () => void };


/**
 * Standalone shell. This page renders no chrome of its own - it was written as an
 * embedded tab body - so as a live route it had no sidebar, no breadcrumb and no
 * back link, and the sidebar was the only way out. MaybeLayout renders children
 * bare when `embedded`, so every hub that embeds it is unaffected.
 */
const ScriptsPage: React.FC<Props> = ( props ) => (
  <MaybeLayout embedded={ props.embedded } user={ ( props as AnyShellProps ).user }
    onSignOut={ ( props as AnyShellProps ).signOut }>
    <ScriptsPageBody { ...props } />
  </MaybeLayout>
);

export default ScriptsPage;
