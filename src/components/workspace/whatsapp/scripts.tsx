/**
 * WhatsApp Scripts — Content library for all automated messages.
 * Configured form routes and supported responses are listed here
 * for content review, improvement, and consistency management.
 *
 * Sources: SystemConfigTable configs, hardcoded defaults in Lambda, flow trigger messages.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import MaybeLayout from '../../../components/MaybeLayout';
import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../lib/canonicalFlows';

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

    // Flow trigger messages — load from SystemConfig with fallback defaults
    const defaultFlowTriggers: Record<string, { keywords: string[]; message: { body: string; flowCta: string }; flowId: string }> = {
      submit_request: { keywords: ['submit request', 'sr'], message: { body: '📋 Start a new support request. Share the details and our team will follow up with you.', flowCta: 'Submit Request' }, flowId: canonicalFlowId('submit_request')! },
      track_request: { keywords: ['track request', 'track', 'status'], message: { body: '🔍 Check the status of your request anytime. Enter your reference ID below.', flowCta: 'Track Request' }, flowId: canonicalFlowId('track_request') ?? '-' },
      amend_request: { keywords: ['amend request', 'update request'], message: { body: '✏️ Need to make a change? Update your submitted request with the correct details.', flowCta: 'Update Request' }, flowId: canonicalFlowId('amend_request') ?? '-' },
      schedule_appointment: { keywords: ['appointment', 'book appointment'], message: { body: '📅 Schedule a consultation or service visit at a time that works best for you.', flowCta: 'Book Appointment' }, flowId: '1475722977488573' },
      sehat_appointment: { keywords: ['sehat', 'appointment', 'book appointment'], message: { body: '🩺 Book an appointment with a qualified professional.', flowCta: 'Book Appointment' }, flowId: '1892784521355352' },
      drop_docs: { keywords: ['drop docs', 'upload documents'], message: { body: '🖇️ Start Drop Docs checkout. After payment, F003 opens so you can choose the order/request and upload documents.', flowCta: 'Start Drop Docs' }, flowId: canonicalFlowId('drop_docs') ?? '-' },
      enterprise_assist: { keywords: ['enterprise', 'b2b'], message: { body: '💼 Corporate, B2B, and bulk inquiries. Tell us what you need and our team will assist you.', flowCta: 'Enterprise Support' }, flowId: '2132515287534606' },
      // flowId and keywords mirror DEFAULT_FLOW_TRIGGERS['leave_review'] in the inbound
      // handler, as the same ordered list, via src/lib/reviewEntry.ts — REVIEW_FLOW_ID is
      // WD_Leave_Review_v2, PUBLISHED on WABA 1. Guarded by
      // tests/test_leave_review_wiring.py.
      leave_review: { keywords: REVIEW_ENTRY_KEYWORDS, message: { body: '⭐ Share your experience with us and help us improve our service.', flowCta: 'Leave Feedback' }, flowId: REVIEW_FLOW_ID },
      subscribe: { keywords: ['subscribe', 'register'], message: { body: 'Save your details for faster service on WECARE.DIGITAL.', flowCta: 'Subscribe' }, flowId: canonicalFlowId('subscribe') ?? '-' },
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
      const isPaidDropDocs = key === 'drop_docs';
      items.push({
        id: `flow_${key}`,
        category: 'Flow Trigger',
        trigger: isPaidDropDocs
          ? `Keywords: ${ft.keywords.slice(0, 4).join(', ')} → paid checkout`
          : `Keywords: ${ft.keywords.slice(0, 4).join(', ')}`,
        messageType: isPaidDropDocs ? 'Paid checkout → F003 Flow' : 'Website service link',
        content: isPaidDropDocs
          ? `Body: ${ft.message.body}\nCTA: ${ft.message.flowCta}\nAfter payment: launch F003\nFlow ID: ${ft.flowId}`
          : `Body: ${ft.message.body}\nCTA: ${ft.message.flowCta}\nFlow ID: ${ft.flowId}`,
        phone: isPaidDropDocs
          ? 'Paid checkout first; F003 launches after successful payment'
          : 'Website service link; approved template forms use their own send contracts',
        editable: true,
        configKey: 'flow_triggers_config',
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
    Welcome: 'var(--lime)', Menu: '#bfdbfe', CTA: '#ddd6fe', 'Flow Trigger': '#fde68a', Pay: '#bbf7d0', 'CTA Link': '#e0e7ff', System: '#f3f4f6',
  };

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ marginBottom: 12 }}>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 8px' }}>
          Every automated message the bot sends. Use this to review content, check consistency, and improve copy.
        </p>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {CATEGORIES.map(c => (
            <button key={c} onClick={() => setFilter(c)} style={{
              padding: '4px 10px', borderRadius: 4, border: filter === c ? '1.5px solid var(--accent)' : '1px solid #d1d5db',
              background: filter === c ? 'var(--accent)' : '#fff', color: filter === c ? '#fff' : '#374151',
              fontSize: 'var(--text-xs)', fontWeight: 500, cursor: 'pointer',
            }}>{c}</button>
          ))}
          <input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)}
                 style={{ padding: '4px 10px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 'var(--text-xs)', marginLeft: 'auto', width: 160 }} />
          <span style={{ fontSize: 'var(--text-xs)', color: '#9ca3af' }}>{filtered.length} scripts</span>
        </div>
      </div>

      {loading && <p style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>Loading...</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map(s => (
          <div key={s.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: '#fff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 'var(--text-xs)', fontWeight: 600, background: catColor[s.category] || '#f3f4f6' }}>{s.category}</span>
                <span style={{ fontSize: 'var(--text-xs)', color: '#9ca3af' }}>{s.messageType}</span>
              </div>
              <span style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', fontFamily: 'monospace' }}>{s.id}</span>
            </div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>Trigger: {s.trigger}</div>
            <pre style={{ fontSize: 'var(--text-xs)', color: 'var(--accent)', margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'inherit', lineHeight: 1.5 }}>{s.content}</pre>
            <div style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', marginTop: 4 }}>Phone: {s.phone}</div>
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
