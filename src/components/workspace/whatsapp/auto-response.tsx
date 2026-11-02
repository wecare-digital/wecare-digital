/**
 * WhatsApp Auto-Response Manager (embedded in WhatsApp Settings)
 *
 * Manages all automated WhatsApp responses from one place:
 * - Flow Triggers: keyword → WhatsApp Flow form mapping
 * - Welcome Message: first-time greeting for new contacts
 *
 * All configs stored in SystemConfigTable, read by wecare-inbound-whatsapp Lambda.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import MaybeLayout from '../../../components/MaybeLayout';
import SubscribeSettings from './subscribe-settings';

interface Props { signOut?: () => void; user?: any; embedded?: boolean; }

/** F001's trigger is managed only in the Subscribe tab, where its launch contract is enforced. */
const F001_TRIGGER_KEY = 'subscribe';

// ── Types ──
interface FlowTrigger {
  keywords: string[];
  flowId: string;
  message: { body: string; footer: string; flowCta: string };
  enabled: boolean;
}
// ── Styles ──
const S = {
  tab: (on: boolean): React.CSSProperties => ({ padding: '7px 14px', border: 'none', borderBottom: on ? '2px solid var(--accent)' : '2px solid transparent', background: 'none', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: on ? 600 : 400, color: on ? 'var(--accent)' : 'var(--text-muted)' }),
  card: { border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 10, background: '#fff' } as React.CSSProperties,
  input: { width: '100%', padding: '7px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-xs)' } as React.CSSProperties,
  textarea: { width: '100%', padding: '7px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-xs)', minHeight: 60, resize: 'vertical' as const, fontFamily: 'inherit' } as React.CSSProperties,
  btn: { padding: '5px 12px', border: '1.5px solid #d1d5db', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' } as React.CSSProperties,
  btnP: { padding: '6px 16px', border: 'none', borderRadius: 6, background: 'var(--lime)', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' } as React.CSSProperties,
  toggle: (on: boolean): React.CSSProperties => ({ width: 34, height: 18, borderRadius: 9, border: 'none', cursor: 'pointer', background: on ? 'var(--accent)' : '#d1d5db', position: 'relative', transition: 'all 0.2s' }),
  dot: (on: boolean): React.CSSProperties => ({ position: 'absolute', top: 2, left: on ? 17 : 2, width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left 0.2s' }),
  label: { fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', marginBottom: 3, display: 'block' } as React.CSSProperties,
};

const AutoResponsePageBody: React.FC<Props> = () => {
  const toast = useToastContext();
  const [tab, setTab] = useState<'triggers' | 'welcome' | 'subscribe'>('triggers');
  const [saving, setSaving] = useState(false);

  // ── Flow Triggers ──
  const [triggers, setTriggers] = useState<Record<string, FlowTrigger>>({});
  const [trigLoading, setTrigLoading] = useState(false);
  const [editTrig, setEditTrig] = useState<string | null>(null);

  // ── Welcome ──
  const [welcomeText, setWelcomeText] = useState('');
  const [welcomeEnabled, setWelcomeEnabled] = useState(true);
  const [welLoading, setWelLoading] = useState(false);

  // Loaders
  const loadTriggers = useCallback(async () => {
    setTrigLoading(true);
    try { const r = await api.getSystemConfig('flow_triggers_config'); if (r) setTriggers(r as any); } catch {}
    setTrigLoading(false);
  }, []);
  const loadWelcome = useCallback(async () => {
    setWelLoading(true);
    try {
      const r = await api.getSystemConfig('wa_auto_response');
      if (r) { setWelcomeText((r as any).welcomeMessage || ''); setWelcomeEnabled((r as any).welcomeEnabled !== false); }
    } catch {}
    setWelLoading(false);
  }, []);

  useEffect(() => {
    if (tab === 'triggers') loadTriggers();
    if (tab === 'welcome') loadWelcome();
  }, [tab, loadTriggers, loadWelcome]);

  // Keep the draft when either the write or its read-back cannot be confirmed.
  const saveSetting = async (key: string, value: any, message: string) => {
    setSaving(true);
    try {
      if (!(await api.updateSystemConfig(key, value))) {
        throw new Error('Save could not be confirmed. Refresh before trying again.');
      }
      toast.success(message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Save could not be confirmed');
    } finally {
      setSaving(false);
    }
  };
  // The SystemConfig write replaces the whole map. F001's own entry is owned by the Subscribe
  // tab, so it is re-read at save time and written back unchanged, never from this tab's copy.
  const saveTriggers = async () => {
    const current = await api.getSystemConfigResult('flow_triggers_config');
    if (!current.ok) {
      toast.error(`Flow triggers could not be re-read, so nothing was saved: ${current.failure.message}`);
      return;
    }
    const stored = current.data.config;
    const storedSubscribe = stored && typeof stored === 'object' && !Array.isArray(stored)
      ? (stored as Record<string, unknown>)[F001_TRIGGER_KEY] : undefined;
    const next: Record<string, unknown> = { ...triggers };
    delete next[F001_TRIGGER_KEY];
    if (storedSubscribe !== undefined) next[F001_TRIGGER_KEY] = storedSubscribe;
    await saveSetting('flow_triggers_config', next, 'Flow triggers saved');
  };
  const saveWelcome = () => saveSetting('wa_auto_response', { welcomeMessage: welcomeText, welcomeEnabled }, 'Welcome saved');

  // Trigger helpers
  const updateTrig = (k: string, f: string, v: any) => setTriggers(p => ({ ...p, [k]: { ...p[k], [f]: v } }));
  const updateTrigMsg = (k: string, f: string, v: string) => setTriggers(p => ({ ...p, [k]: { ...p[k], message: { ...p[k]?.message, [f]: v } } }));
  const addTrig = () => { const id = `custom_${Date.now()}`; setTriggers(p => ({ ...p, [id]: { keywords: [''], flowId: '', message: { body: '', footer: 'WECARE.DIGITAL', flowCta: 'Open' }, enabled: true } })); setEditTrig(id); };
  const delTrig = (k: string) => setTriggers(p => { const n = { ...p }; delete n[k]; return n; });

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ borderBottom: '1px solid var(--border)', marginBottom: 14, display: 'flex', gap: 2 }}>
        <button style={S.tab(tab === 'triggers')} onClick={() => setTab('triggers')}>Flow Triggers</button>
        <button style={S.tab(tab === 'welcome')} onClick={() => setTab('welcome')}>Welcome</button>
        <button style={S.tab(tab === 'subscribe')} onClick={() => setTab('subscribe')}>Subscribe</button>
      </div>

      {tab === 'subscribe' && <SubscribeSettings />}

      {/* ── FLOW TRIGGERS ── */}
      {tab === 'triggers' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0 }}>Keyword → service website link mapping. Empty = server defaults.</p>
            <div style={{ display: 'flex', gap: 6 }}><button style={S.btn} onClick={addTrig}>+ Add</button><button style={S.btnP} onClick={saveTriggers} disabled={saving}>{saving ? '...' : 'Save'}</button></div>
          </div>
          {trigLoading && <p style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>Loading...</p>}
          {Object.keys(triggers).length === 0 && !trigLoading && <div style={{ ...S.card, textAlign: 'center', color: '#9ca3af', padding: 24 }}>No overrides. Lambda defaults active.</div>}
          {triggers[F001_TRIGGER_KEY] && (
            <div style={{ ...S.card, borderLeft: '3px solid var(--accent)' }}>
              <code style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' }}>{F001_TRIGGER_KEY}</code>
              <p style={{ margin: '4px 0 6px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                F001 Subscribe keywords, switch and copy are managed in the Subscribe tab, which enforces its launch rules. Saving here never changes them.
              </p>
              <button style={S.btn} onClick={() => setTab('subscribe')}>Open Subscribe settings</button>
            </div>
          )}
          {Object.entries(triggers).filter(([k]) => k !== F001_TRIGGER_KEY).map(([k, t]) => (
            <div key={k} style={{ ...S.card, opacity: t.enabled ? 1 : 0.5, borderLeft: `3px solid ${t.enabled ? 'var(--lime)' : '#d1d5db'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <code style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' }}>{k}</code>
                    {t.flowId && <span style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', fontFamily: 'monospace' }}>Flow: {t.flowId}</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginBottom: 3 }}>{(t.keywords || []).map((kw, i) => <span key={i} style={{ padding: '1px 5px', background: 'var(--lime)', borderRadius: 3, fontSize: 'var(--text-xs)' }}>{kw}</span>)}</div>
                  {editTrig !== k && <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{t.message?.body?.slice(0, 60)}</p>}
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <button style={S.toggle(t.enabled)} onClick={() => updateTrig(k, 'enabled', !t.enabled)}><span style={S.dot(t.enabled)} /></button>
                  <button style={{ ...S.btn, padding: '3px 7px' }} onClick={() => setEditTrig(editTrig === k ? null : k)}>{editTrig === k ? '▲' : '▼'}</button>
                  <button style={{ ...S.btn, padding: '3px 7px', color: '#dc2626' }} onClick={() => delTrig(k)}>×</button>
                </div>
              </div>
              {editTrig === k && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, padding: 10, background: 'var(--bg-secondary)', borderRadius: 6 }}>
                  <div><label style={S.label}>Keywords (comma-separated)</label><input style={S.input} value={(t.keywords || []).join(', ')} onChange={e => updateTrig(k, 'keywords', e.target.value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean))} /></div>
                  <div><label style={S.label}>Flow ID</label><input style={S.input} value={t.flowId || ''} onChange={e => updateTrig(k, 'flowId', e.target.value.trim())} placeholder="Meta Flow ID" /></div>
                  <div><label style={S.label}>Message Body</label><textarea style={S.textarea} value={t.message?.body || ''} onChange={e => updateTrigMsg(k, 'body', e.target.value)} /></div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                    <div><label style={S.label}>CTA Button</label><input style={S.input} value={t.message?.flowCta || ''} onChange={e => updateTrigMsg(k, 'flowCta', e.target.value)} /></div>
                    <div><label style={S.label}>Footer</label><input style={S.input} value={t.message?.footer || ''} onChange={e => updateTrigMsg(k, 'footer', e.target.value)} /></div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── WELCOME ── */}
      {tab === 'welcome' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0 }}>Greeting sent to brand-new contacts on first message.</p>
            <button style={S.btnP} onClick={saveWelcome} disabled={saving}>{saving ? '...' : 'Save'}</button>
          </div>
          {welLoading && <p style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>Loading...</p>}
          <div style={S.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <label style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--accent)' }}>Welcome Message</label>
              <button style={S.toggle(welcomeEnabled)} onClick={() => setWelcomeEnabled(!welcomeEnabled)}><span style={S.dot(welcomeEnabled)} /></button>
            </div>
            <textarea style={{ ...S.textarea, minHeight: 80 }} value={welcomeText} onChange={e => setWelcomeText(e.target.value)} placeholder="Hi there! 👋 Welcome to WECARE.DIGITAL..." />
            <p style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', margin: '6px 0 0' }}>This setting controls the plain-text greeting only.</p>
          </div>
        </div>
      )}
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
const AutoResponsePage: React.FC<Props> = ( props ) => (
  <MaybeLayout embedded={ props.embedded } user={ ( props as AnyShellProps ).user }
    onSignOut={ ( props as AnyShellProps ).signOut }>
    <AutoResponsePageBody { ...props } />
  </MaybeLayout>
);

export default AutoResponsePage;
