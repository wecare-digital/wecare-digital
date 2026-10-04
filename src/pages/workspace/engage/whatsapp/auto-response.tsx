/**
 * WhatsApp Auto-Response Manager (embedded in WhatsApp Settings)
 *
 * Manages all automated WhatsApp responses from one place:
 * - Flow Triggers: keyword → WhatsApp Flow form mapping
 * - Selfservice Menu: the interactive list sent on "customerservice" keyword
 * - Main Menu: the interactive list sent on "hi" / "menu"
 * - Welcome Message: first-time greeting for new contacts
 *
 * All configs stored in SystemConfigTable, read by wecare-inbound-whatsapp Lambda.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import MaybeLayout from '../../../../components/MaybeLayout';

interface Props { signOut?: () => void; user?: any; embedded?: boolean; }

// ── Types ──
interface FlowTrigger {
  keywords: string[];
  flowId: string;
  message: { body: string; footer: string; flowCta: string };
  enabled: boolean;
}
interface MenuRow { id: string; title: string; description: string; }
interface MenuSection { title: string; rows: MenuRow[]; }
interface MenuConfig { header: string; body: string; footer: string; buttonText: string; sections: MenuSection[]; }

// ── Styles ──
const S = {
  tab: (on: boolean): React.CSSProperties => ({ padding: '7px 14px', border: 'none', borderBottom: on ? '2px solid #1a3a2a' : '2px solid transparent', background: 'none', cursor: 'pointer', fontSize: 12, fontWeight: on ? 600 : 400, color: on ? '#1a3a2a' : '#6b7280' }),
  card: { border: '1px solid #e5e7eb', borderRadius: 8, padding: 14, marginBottom: 10, background: '#fff' } as React.CSSProperties,
  input: { width: '100%', padding: '7px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 12 } as React.CSSProperties,
  textarea: { width: '100%', padding: '7px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 12, minHeight: 60, resize: 'vertical' as const, fontFamily: 'inherit' } as React.CSSProperties,
  btn: { padding: '5px 12px', border: '1.5px solid #d1d5db', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 11, fontWeight: 600, color: '#1a3a2a' } as React.CSSProperties,
  btnP: { padding: '6px 16px', border: 'none', borderRadius: 6, background: '#d1f470', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#1a3a2a' } as React.CSSProperties,
  toggle: (on: boolean): React.CSSProperties => ({ width: 34, height: 18, borderRadius: 9, border: 'none', cursor: 'pointer', background: on ? '#1a3a2a' : '#d1d5db', position: 'relative', transition: 'all 0.2s' }),
  dot: (on: boolean): React.CSSProperties => ({ position: 'absolute', top: 2, left: on ? 17 : 2, width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left 0.2s' }),
  label: { fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 3, display: 'block' } as React.CSSProperties,
};

const AutoResponsePageBody: React.FC<Props> = () => {
  const toast = useToastContext();
  const [tab, setTab] = useState<'triggers' | 'customerservice' | 'mainmenu' | 'welcome'>('triggers');
  const [saving, setSaving] = useState(false);

  // ── Flow Triggers ──
  const [triggers, setTriggers] = useState<Record<string, FlowTrigger>>({});
  const [trigLoading, setTrigLoading] = useState(false);
  const [editTrig, setEditTrig] = useState<string | null>(null);

  // ── Selfservice Menu ──
  const [ssMenu, setSsMenu] = useState<MenuConfig | null>(null);
  const [ssLoading, setSsLoading] = useState(false);

  // ── Main Menu ──
  const [mainMenu, setMainMenu] = useState<MenuConfig | null>(null);
  const [mmLoading, setMmLoading] = useState(false);

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
  const loadSsMenu = useCallback(async () => {
    setSsLoading(true);
    try { const r = await api.getSystemConfig('customerservice_menu_config'); if (r) setSsMenu(r as any); } catch {}
    setSsLoading(false);
  }, []);
  const loadMainMenu = useCallback(async () => {
    setMmLoading(true);
    try { const r = await api.getSystemConfig('welcome_message_config'); if (r) setMainMenu(r as any); } catch {}
    setMmLoading(false);
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
    if (tab === 'customerservice') loadSsMenu();
    if (tab === 'mainmenu') loadMainMenu();
    if (tab === 'welcome') loadWelcome();
  }, [tab, loadTriggers, loadSsMenu, loadMainMenu, loadWelcome]);

  // Savers
  const saveTriggers = async () => { setSaving(true); try { await api.updateSystemConfig('flow_triggers_config', triggers); toast.success('Flow triggers saved'); } catch { toast.error('Save failed'); } setSaving(false); };
  const saveSsMenu = async () => { setSaving(true); try { await api.updateSystemConfig('customerservice_menu_config', ssMenu); toast.success('Selfservice menu saved'); } catch { toast.error('Save failed'); } setSaving(false); };
  const saveMainMenu = async () => { setSaving(true); try { await api.updateSystemConfig('welcome_message_config', mainMenu); toast.success('Main menu saved'); } catch { toast.error('Save failed'); } setSaving(false); };
  const saveWelcome = async () => { setSaving(true); try { await api.updateSystemConfig('wa_auto_response', { welcomeMessage: welcomeText, welcomeEnabled }); toast.success('Welcome saved'); } catch { toast.error('Save failed'); } setSaving(false); };

  // Trigger helpers
  const updateTrig = (k: string, f: string, v: any) => setTriggers(p => ({ ...p, [k]: { ...p[k], [f]: v } }));
  const updateTrigMsg = (k: string, f: string, v: string) => setTriggers(p => ({ ...p, [k]: { ...p[k], message: { ...p[k]?.message, [f]: v } } }));
  const addTrig = () => { const id = `custom_${Date.now()}`; setTriggers(p => ({ ...p, [id]: { keywords: [''], flowId: '', message: { body: '', footer: 'WECARE.DIGITAL', flowCta: 'Open' }, enabled: true } })); setEditTrig(id); };
  const delTrig = (k: string) => setTriggers(p => { const n = { ...p }; delete n[k]; return n; });

  // Menu helpers
  const updateMenuField = (menu: MenuConfig, setMenu: (m: MenuConfig) => void, field: string, val: string) => setMenu({ ...menu, [field]: val });
  const updateRow = (menu: MenuConfig, setMenu: (m: MenuConfig) => void, si: number, ri: number, field: string, val: string) => {
    const sections = [...menu.sections]; const rows = [...sections[si].rows]; rows[ri] = { ...rows[ri], [field]: val }; sections[si] = { ...sections[si], rows }; setMenu({ ...menu, sections });
  };
  const updateSectionTitle = (menu: MenuConfig, setMenu: (m: MenuConfig) => void, si: number, val: string) => {
    const sections = [...menu.sections]; sections[si] = { ...sections[si], title: val }; setMenu({ ...menu, sections });
  };

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ borderBottom: '1px solid #e5e7eb', marginBottom: 14, display: 'flex', gap: 2 }}>
        <button style={S.tab(tab === 'triggers')} onClick={() => setTab('triggers')}>Flow Triggers</button>
        <button style={S.tab(tab === 'customerservice')} onClick={() => setTab('customerservice')}>Selfservice Menu</button>
        <button style={S.tab(tab === 'mainmenu')} onClick={() => setTab('mainmenu')}>Main Menu</button>
        <button style={S.tab(tab === 'welcome')} onClick={() => setTab('welcome')}>Welcome</button>
      </div>

      {/* ── FLOW TRIGGERS ── */}
      {tab === 'triggers' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 11, color: '#6b7280', margin: 0 }}>Keyword → WhatsApp Flow mapping. Empty = Lambda defaults.</p>
            <div style={{ display: 'flex', gap: 6 }}><button style={S.btn} onClick={addTrig}>+ Add</button><button style={S.btnP} onClick={saveTriggers} disabled={saving}>{saving ? '...' : 'Save'}</button></div>
          </div>
          {trigLoading && <p style={{ color: '#9ca3af', fontSize: 12 }}>Loading...</p>}
          {Object.keys(triggers).length === 0 && !trigLoading && <div style={{ ...S.card, textAlign: 'center', color: '#9ca3af', padding: 24 }}>No overrides. Lambda defaults active.</div>}
          {Object.entries(triggers).map(([k, t]) => (
            <div key={k} style={{ ...S.card, opacity: t.enabled ? 1 : 0.5, borderLeft: `3px solid ${t.enabled ? '#d1f470' : '#d1d5db'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <code style={{ fontSize: 12, fontWeight: 600, color: '#1a3a2a' }}>{k}</code>
                    {t.flowId && <span style={{ fontSize: 10, color: '#9ca3af', fontFamily: 'monospace' }}>Flow: {t.flowId}</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginBottom: 3 }}>{(t.keywords || []).map((kw, i) => <span key={i} style={{ padding: '1px 5px', background: '#d1f470', borderRadius: 3, fontSize: 10 }}>{kw}</span>)}</div>
                  {editTrig !== k && <p style={{ margin: 0, fontSize: 11, color: '#6b7280' }}>{t.message?.body?.slice(0, 60)}</p>}
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <button style={S.toggle(t.enabled)} onClick={() => updateTrig(k, 'enabled', !t.enabled)}><span style={S.dot(t.enabled)} /></button>
                  <button style={{ ...S.btn, padding: '3px 7px' }} onClick={() => setEditTrig(editTrig === k ? null : k)}>{editTrig === k ? '▲' : '▼'}</button>
                  <button style={{ ...S.btn, padding: '3px 7px', color: '#dc2626' }} onClick={() => delTrig(k)}>×</button>
                </div>
              </div>
              {editTrig === k && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, padding: 10, background: '#f9fafb', borderRadius: 6 }}>
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

      {/* ── CUSTOMERSERVICE MENU ── */}
      {tab === 'customerservice' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 11, color: '#6b7280', margin: 0 }}>The list message sent when user types &quot;customerservice&quot;. Empty = Lambda defaults.</p>
            <button style={S.btnP} onClick={saveSsMenu} disabled={saving}>{saving ? '...' : 'Save'}</button>
          </div>
          {ssLoading && <p style={{ color: '#9ca3af', fontSize: 12 }}>Loading...</p>}
          {ssMenu ? (
            <div>
              <div style={{ ...S.card }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  <div><label style={S.label}>Header</label><input style={S.input} value={ssMenu.header} onChange={e => updateMenuField(ssMenu, setSsMenu as any, 'header', e.target.value)} /></div>
                  <div><label style={S.label}>Button Text</label><input style={S.input} value={ssMenu.buttonText} onChange={e => updateMenuField(ssMenu, setSsMenu as any, 'buttonText', e.target.value)} /></div>
                </div>
                <div><label style={S.label}>Body</label><textarea style={S.textarea} value={ssMenu.body} onChange={e => updateMenuField(ssMenu, setSsMenu as any, 'body', e.target.value)} /></div>
                <div style={{ marginTop: 6 }}><label style={S.label}>Footer</label><input style={S.input} value={ssMenu.footer} onChange={e => updateMenuField(ssMenu, setSsMenu as any, 'footer', e.target.value)} /></div>
              </div>
              {ssMenu.sections.map((sec, si) => (
                <div key={si} style={{ ...S.card, borderLeft: '3px solid #d1f470' }}>
                  <input style={{ ...S.input, fontWeight: 600, border: 'none', padding: '3px 0', marginBottom: 6 }} value={sec.title} onChange={e => updateSectionTitle(ssMenu, setSsMenu as any, si, e.target.value)} />
                  {sec.rows.map((row, ri) => (
                    <div key={ri} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 2fr', gap: 4, marginBottom: 4 }}>
                      <input style={{ ...S.input, fontSize: 10, color: '#9ca3af' }} value={row.id} readOnly />
                      <input style={S.input} value={row.title} onChange={e => updateRow(ssMenu, setSsMenu as any, si, ri, 'title', e.target.value)} />
                      <input style={S.input} value={row.description} onChange={e => updateRow(ssMenu, setSsMenu as any, si, ri, 'description', e.target.value)} />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ) : !ssLoading && <div style={{ ...S.card, textAlign: 'center', color: '#9ca3af', padding: 24 }}>No override. Lambda defaults active.</div>}
        </div>
      )}

      {/* ── MAIN MENU ── */}
      {tab === 'mainmenu' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 11, color: '#6b7280', margin: 0 }}>The list message sent on &quot;hi&quot; / &quot;menu&quot; / &quot;start&quot;. Empty = Lambda defaults.</p>
            <button style={S.btnP} onClick={saveMainMenu} disabled={saving}>{saving ? '...' : 'Save'}</button>
          </div>
          {mmLoading && <p style={{ color: '#9ca3af', fontSize: 12 }}>Loading...</p>}
          {mainMenu ? (
            <div>
              <div style={{ ...S.card }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  <div><label style={S.label}>Header</label><input style={S.input} value={mainMenu.header} onChange={e => updateMenuField(mainMenu, setMainMenu as any, 'header', e.target.value)} /></div>
                  <div><label style={S.label}>Button Text</label><input style={S.input} value={mainMenu.buttonText} onChange={e => updateMenuField(mainMenu, setMainMenu as any, 'buttonText', e.target.value)} /></div>
                </div>
                <div><label style={S.label}>Body</label><textarea style={S.textarea} value={mainMenu.body} onChange={e => updateMenuField(mainMenu, setMainMenu as any, 'body', e.target.value)} /></div>
                <div style={{ marginTop: 6 }}><label style={S.label}>Footer</label><input style={S.input} value={mainMenu.footer} onChange={e => updateMenuField(mainMenu, setMainMenu as any, 'footer', e.target.value)} /></div>
              </div>
              {mainMenu.sections.map((sec, si) => (
                <div key={si} style={{ ...S.card, borderLeft: '3px solid #d1f470' }}>
                  <input style={{ ...S.input, fontWeight: 600, border: 'none', padding: '3px 0', marginBottom: 6 }} value={sec.title} onChange={e => updateSectionTitle(mainMenu, setMainMenu as any, si, e.target.value)} />
                  {sec.rows.map((row, ri) => (
                    <div key={ri} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 2fr', gap: 4, marginBottom: 4 }}>
                      <input style={{ ...S.input, fontSize: 10, color: '#9ca3af' }} value={row.id} readOnly />
                      <input style={S.input} value={row.title} onChange={e => updateRow(mainMenu, setMainMenu as any, si, ri, 'title', e.target.value)} />
                      <input style={S.input} value={row.description} onChange={e => updateRow(mainMenu, setMainMenu as any, si, ri, 'description', e.target.value)} />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ) : !mmLoading && <div style={{ ...S.card, textAlign: 'center', color: '#9ca3af', padding: 24 }}>No override. Lambda defaults active.</div>}
        </div>
      )}

      {/* ── WELCOME ── */}
      {tab === 'welcome' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <p style={{ fontSize: 11, color: '#6b7280', margin: 0 }}>Greeting sent to brand-new contacts on first message.</p>
            <button style={S.btnP} onClick={saveWelcome} disabled={saving}>{saving ? '...' : 'Save'}</button>
          </div>
          {welLoading && <p style={{ color: '#9ca3af', fontSize: 12 }}>Loading...</p>}
          <div style={S.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#1a3a2a' }}>Welcome Message</label>
              <button style={S.toggle(welcomeEnabled)} onClick={() => setWelcomeEnabled(!welcomeEnabled)}><span style={S.dot(welcomeEnabled)} /></button>
            </div>
            <textarea style={{ ...S.textarea, minHeight: 80 }} value={welcomeText} onChange={e => setWelcomeText(e.target.value)} placeholder="Hi there! 👋 Welcome to WECARE.DIGITAL..." />
            <p style={{ fontSize: 10, color: '#9ca3af', margin: '6px 0 0' }}>After this message, the main menu list is also sent automatically.</p>
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
