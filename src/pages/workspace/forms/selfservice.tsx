import { REVIEW_FLOW_ID, REVIEW_ENTRY_URL, REVIEW_ENTRY_KEYWORDS } from '../../../lib/reviewEntry';
/**
 * Customer-Service Hub — All WhatsApp Flow forms accessible from the admin dashboard.
 * Shows all flow submissions, allows resending flows, and manages flow configurations.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; }

type FlowSubmission = api.FlowLog;

const FLOW_TYPES = [
  { key: 'submit_request', label: 'Submit Request', icon: '📋', flowId: '1469093721293830', paid: true, price: '₹49', status: 'published', confirmation: 'Payment link + text confirmation' },
  { key: 'subscribe', label: 'Subscribe', icon: '📝', flowId: '1262971692700761', paid: false, price: 'Free', status: 'published', confirmation: 'WhatsApp text with subscriber ID' },
  { key: 'track_request', label: 'Track Request', icon: '🔍', flowId: '1486454129852338', paid: false, price: 'Free', status: 'draft', confirmation: 'Status display in flow' },
  { key: 'amend_request', label: 'Amend Request', icon: '✏️', flowId: '3678132465672138', paid: false, price: 'Free', status: 'draft', confirmation: 'Amendment confirmation' },
  { key: 'schedule_appointment', label: 'Appointment', icon: '📅', flowId: '26575380852083467', paid: false, price: 'Free', status: 'draft', confirmation: 'Booking confirmation' },
  { key: 'rx_slot', label: 'RX Slot', icon: '💊', flowId: '895208030185211', paid: false, price: 'Free', status: 'draft', confirmation: 'Slot confirmation' },
  { key: 'drop_docs', label: 'Drop Docs', icon: '📄', flowId: '1211063631104445', paid: false, price: 'Free', status: 'draft', confirmation: 'Document registered' },
  { key: 'enterprise_assist', label: 'Enterprise Assist', icon: '🏢', flowId: '1707170524029465', paid: false, price: 'Free', status: 'draft', confirmation: 'Enquiry acknowledgement' },
  { key: 'leave_review', label: 'Leave Review', icon: '⭐', flowId: REVIEW_FLOW_ID, paid: false, price: 'Free', status: 'published', confirmation: 'Private review saved' },
  { key: 'order_notes', label: 'Order Notes', icon: '📝', flowId: '1434731571172691', paid: false, price: 'Free', status: 'draft', confirmation: 'Notes saved' },
];

const MESSAGE_LINKS: Record<string, string> = {
  submit_request: 'https://wa.me/message/5DRZXKBJTZDQG1',
  subscribe: 'https://wa.me/message/APDM5HUWH26SG1',
  amend_request: 'https://wa.me/message/HD5C4LAUYOOID1',
  drop_docs: 'https://wa.me/message/BCYW2SEPI5R4D1',
  // Owner-managed short link, from src/lib/reviewEntry.ts. Resolves to WABA 1
  // (919330994400) with the prefill "Leave Review", which lowercases to the first keyword
  // below, so the customer's own message opens the published flow. Same constant as the
  // /leave-review/ page CTA, so the two cannot diverge.
  leave_review: REVIEW_ENTRY_URL,
};
/* The submissions filter, built from FLOW_TYPES so a new flow appears here for free. */
const FLOW_FILTER_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All Flows' },
  ...FLOW_TYPES.map(f => ({ value: f.key, label: f.label })),
];

const fmtDate = (ts: number) => {
  if (!ts) return '—';
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
};

const CustomerServicePage: React.FC<PageProps> = ({ signOut, user }) => {
  const toast = useToastContext();
  const [activeTab, setActiveTab] = useState<'flows' | 'submissions' | 'links'>('flows');
  const [submissions, setSubmissions] = useState<FlowSubmission[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterKey, setFilterKey] = useState('all');

  const loadSubmissions = useCallback(async () => {
    setLoading(true);
    try {
      const logs = await api.listFlowLogs();
      setSubmissions(logs || []);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { if (activeTab === 'submissions') loadSubmissions(); }, [activeTab, loadSubmissions]);

  const filtered = filterKey === 'all' ? submissions : submissions.filter(s => s.type === filterKey || s.action === filterKey);

  const S = {
    tab: (active: boolean): React.CSSProperties => ({
      padding: '8px 16px', border: 'none', borderBottom: active ? '2px solid #1a3a2a' : '2px solid transparent',
      background: 'none', cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 400, color: active ? '#1a3a2a' : '#6b7280',
    }),
    card: { border: '1px solid #e5e7eb', borderRadius: 10, padding: 16, background: '#fff' } as React.CSSProperties,
  };

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Customer-Service" description="WhatsApp Flow forms and submissions" />
      <div className="inner-page" style={{ padding: '20px 24px', maxWidth: 1100 }}>
        <div style={{ marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20, color: '#1a3a2a' }}>Customer-Service Hub</h2>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#6b7280' }}>
            All WhatsApp Flow forms, submissions, and message links in one place.
          </p>
        </div>

        <div style={{ borderBottom: '1px solid #e5e7eb', marginBottom: 16, display: 'flex', gap: 4 }}>
          <button style={S.tab(activeTab === 'flows')} onClick={() => setActiveTab('flows')}>Flows</button>
          <button style={S.tab(activeTab === 'submissions')} onClick={() => setActiveTab('submissions')}>Submissions</button>
          <button style={S.tab(activeTab === 'links')} onClick={() => setActiveTab('links')}>Message Links</button>
        </div>

        {activeTab === 'flows' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {FLOW_TYPES.map(flow => (
              <div key={flow.key} style={S.card}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 24 }}>{flow.icon}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: '#1a3a2a' }}>{flow.label}</div>
                    <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>{flow.flowId}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {flow.key === 'submit_request' ? (
                    <span style={{ fontSize: 11, padding: '2px 8px', background: '#d1f470', borderRadius: 4, fontWeight: 500 }}>Published</span>
                  ) : (
                    <span style={{ fontSize: 11, padding: '2px 8px', background: '#fef3c7', borderRadius: 4, fontWeight: 500 }}>Draft</span>
                  )}
                  {MESSAGE_LINKS[flow.key] && (
                    <a href={MESSAGE_LINKS[flow.key]} target="_blank" rel="noopener noreferrer"
                       style={{ fontSize: 11, padding: '2px 8px', background: '#e0f2fe', borderRadius: 4, color: '#0369a1', textDecoration: 'none' }}>
                      wa.me link
                    </a>
                  )}
                </div>
                <div style={{ marginTop: 8, fontSize: 12, color: '#6b7280' }}>
                  Keywords: {FLOW_TYPES.find(f => f.key === flow.key) ? getKeywords(flow.key).join(', ') : '—'}
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'submissions' && (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
              {/* The old inline padding/border/radius/font-size object skinned the native
                  control and is gone: .ui-select-trigger draws the box now. Only the width
                  stays, which is layout. */}
              <Select ariaLabel="Flow" value={filterKey} onChange={v => setFilterKey(v)}
                      options={FLOW_FILTER_OPTIONS} style={{ width: 200 }} />
              <Button variant="secondary" size="sm" loading={loading} onClick={loadSubmissions}>Refresh</Button>
              <span style={{ fontSize: 12, color: '#6b7280' }}>{filtered.length} submissions</span>
            </div>
            <div className="table-container">
              <table className="inner-table" style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>ID</th><th>Type</th><th>Phone</th><th>Screen</th><th>Date</th><th>Data</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 && (
                    <tr><td colSpan={6} style={{ textAlign: 'center', padding: 24, color: '#9ca3af' }}>
                      {loading ? 'Loading...' : 'No submissions yet'}
                    </td></tr>
                  )}
                  {filtered.map(s => {
                    return (
                      <tr key={s.id}>
                        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{s.id?.slice(0, 12)}</td>
                        <td>{s.type || s.action || '—'}</td>
                        <td>{s.phone || '—'}</td>
                        <td>{s.screen || '—'}</td>
                        <td>{fmtDate(s.createdAt)}</td>
                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11, color: '#6b7280' }}>
                          {s.subject || s.order_id || s.flowData?.slice(0, 60) || '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'links' && (
          <div>
            <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
              Share these links to let users open a specific flow directly. Each link pre-fills the keyword message.
            </p>
            <div className="table-container">
              <table className="inner-table" style={{ width: '100%', fontSize: 13 }}>
                <thead><tr><th>Topic</th><th>Message Link</th><th>Keyword</th></tr></thead>
                <tbody>
                  {Object.entries(MESSAGE_LINKS).map(([key, link]) => (
                    <tr key={key}>
                      <td style={{ fontWeight: 600 }}>{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</td>
                      <td>
                        <a href={link} target="_blank" rel="noopener noreferrer" style={{ color: '#0369a1', fontSize: 12 }}>{link}</a>
                        <button onClick={() => { navigator.clipboard.writeText(link); toast.success('Copied'); }}
                                style={{ marginLeft: 6, background: 'none', border: '1px solid #d1d5db', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', fontSize: 10 }}>
                          Copy
                        </button>
                      </td>
                      {/* Full set, not a slice: the workspace has to SHOW what the
                          backend actually answers, so an operator can tell a customer
                          which words work. Wraps rather than widening the table. */}
                      <td style={{ fontSize: 12, color: '#6b7280', wordBreak: 'break-word' }}>{getKeywords(key).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};

function getKeywords(flowKey: string): string[] {
  const map: Record<string, string[]> = {
    submit_request: ['submit request', 'sr', 'raise request'],
    subscribe: ['subscribe', 'signup', 'register', 'join'],
    amend_request: ['amend request', 'amend', 'change request'],
    track_request: ['track request', 'track', 'status'],
    rx_slot: ['rx slot', 'rx', 'prescription'],
    drop_docs: ['drop docs', 'documents', 'upload docs'],
    enterprise_assist: ['enterprise assist', 'enterprise', 'b2b'],
    schedule_appointment: ['schedule appointment', 'appointment', 'meeting'],
    // Mirrors DEFAULT_FLOW_TRIGGERS['leave_review'].keywords in
    // amplify/functions/messaging/inbound-whatsapp-handler/handler.py, as the same
    // ordered list, via src/lib/reviewEntry.ts. tests/test_leave_review_wiring.py fails if
    // the two diverge.
    leave_review: REVIEW_ENTRY_KEYWORDS,
    order_notes: ['order notes', 'special instructions'],
    pay: ['pay', 'payment', 'invoice', 'bill'],
    faq: ['faq', 'help'],
  };
  return map[flowKey] || [];
}

export default CustomerServicePage;
