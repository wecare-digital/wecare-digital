/**
 * WhatsApp Interactive List Messages
 * Send guided menus / option lists to users
 * Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages
 */
import React, { useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { WHATSAPP_PHONES } from '../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

interface ListRow { id: string; title: string; description?: string; }
interface ListSection { title: string; rows: ListRow[]; }

const PHONES = [
  { metaId: WHATSAPP_PHONES.primary.metaPhoneId, display: WHATSAPP_PHONES.primary.display, name: WHATSAPP_PHONES.primary.name },
  { metaId: WHATSAPP_PHONES.secondary.metaPhoneId, display: WHATSAPP_PHONES.secondary.display, name: WHATSAPP_PHONES.secondary.name },
];

const PRESETS: { name: string; headerText: string; bodyText: string; footerText: string; buttonText: string; sections: ListSection[] }[] = [
  {
    name: 'Customer Support Menu',
    headerText: 'How can we help?',
    bodyText: 'Please select an option below to get started.',
    footerText: 'Reply anytime for help',
    buttonText: 'View Options',
    sections: [
      { title: 'Support', rows: [
        { id: 'billing', title: 'Billing & Payments', description: 'Invoice, refund, payment issues' },
        { id: 'technical', title: 'Technical Support', description: 'App issues, bugs, errors' },
        { id: 'account', title: 'Account Help', description: 'Login, password, profile' },
      ]},
      { title: 'Sales', rows: [
        { id: 'pricing', title: 'Pricing Info', description: 'Plans and pricing details' },
        { id: 'demo', title: 'Request Demo', description: 'Schedule a product demo' },
      ]},
    ],
  },
  {
    name: 'Product Catalog',
    headerText: 'Our Products',
    bodyText: 'Browse our product categories below.',
    footerText: 'Powered by WECARE.DIGITAL',
    buttonText: 'Browse',
    sections: [
      { title: 'Categories', rows: [
        { id: 'electronics', title: 'Electronics', description: 'Phones, laptops, accessories' },
        { id: 'clothing', title: 'Clothing', description: 'Men, women, kids apparel' },
        { id: 'home', title: 'Home & Living', description: 'Furniture, decor, kitchen' },
      ]},
    ],
  },
];

const InteractiveListsPage: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const toast = useToastContext();
  const [selectedPhone, setSelectedPhone] = useState(PHONES[0]);
  const [to, setTo] = useState('');
  const [headerText, setHeaderText] = useState('');
  const [bodyText, setBodyText] = useState('');
  const [footerText, setFooterText] = useState('');
  const [buttonText, setButtonText] = useState('View Options');
  const [sections, setSections] = useState<ListSection[]>([{ title: 'Options', rows: [{ id: 'opt1', title: '', description: '' }] }]);
  const [sending, setSending] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);
  const [jsonPreview, setJsonPreview] = useState(false);

  const addSection = () => setSections([...sections, { title: '', rows: [{ id: `row_${Date.now()}`, title: '', description: '' }] }]);
  const removeSection = (si: number) => setSections(sections.filter((_, i) => i !== si));
  const updateSection = (si: number, field: string, val: string) => {
    const s = [...sections]; (s[si] as any)[field] = val; setSections(s);
  };
  const addRow = (si: number) => {
    const s = [...sections]; s[si].rows.push({ id: `row_${Date.now()}`, title: '', description: '' }); setSections(s);
  };
  const removeRow = (si: number, ri: number) => {
    const s = [...sections]; s[si].rows = s[si].rows.filter((_, i) => i !== ri); setSections(s);
  };
  const updateRow = (si: number, ri: number, field: string, val: string) => {
    const s = [...sections]; (s[si].rows[ri] as any)[field] = val; setSections(s);
  };

  const loadPreset = (preset: typeof PRESETS[0]) => {
    setHeaderText(preset.headerText);
    setBodyText(preset.bodyText);
    setFooterText(preset.footerText);
    setButtonText(preset.buttonText);
    setSections(JSON.parse(JSON.stringify(preset.sections)));
    toast.success(`Loaded: ${preset.name}`);
  };

  const handleSend = async () => {
    if (!to.trim()) { toast.error('Recipient phone number required'); return; }
    if (!bodyText.trim()) { toast.error('Body text required'); return; }
    const validSections = sections.filter(s => s.rows.some(r => r.title.trim()));
    if (!validSections.length) { toast.error('At least one section with rows required'); return; }

    // Clean sections: ensure row IDs are unique
    const cleanSections = validSections.map(s => ({
      title: s.title,
      rows: s.rows.filter(r => r.title.trim()).map((r, i) => ({
        id: r.id || `row_${i}`,
        title: r.title.substring(0, 24),
        ...(r.description ? { description: r.description.substring(0, 72) } : {}),
      })),
    }));

    setSending(true);
    try {
      const result = await api.sendInteractiveList(
        selectedPhone.metaId, to.trim(), bodyText, buttonText || 'Options',
        cleanSections, headerText || undefined, footerText || undefined,
      );
      if (result) { toast.success(`List message sent! ID: ${result.messageId}`); setLastResult(result); }
      else toast.error('Send failed');
    } catch (e) { toast.error('Send failed'); }
    setSending(false);
  };

  const getPayloadPreview = () => {
    const interactive: any = { type: 'list', body: { text: bodyText }, action: { button: buttonText || 'Options', sections } };
    if (headerText) interactive.header = { type: 'text', text: headerText };
    if (footerText) interactive.footer = { text: footerText };
    return { messaging_product: 'whatsapp', to, type: 'interactive', interactive };
  };

  const cs = { card: { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: '16px 20px', marginBottom: 12 } as React.CSSProperties };

  const content = (
    <>
      <SEO title="Interactive Lists" description="WhatsApp Interactive List Messages" noindex />
      <div className="inner-page-container" style={{ background: '#fff' }}>
        <h2 style={{ margin: '0 0 6px', fontSize: 20 }}>WhatsApp Interactive List Messages</h2>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: '#666' }}>
          Send guided menus with up to 10 sections and 10 rows each. Users tap a button to see the list and select an option.
        </p>

        {/* Limits info */}
        <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: 14, marginBottom: 20, fontSize: 13 }}>
          <strong>Limits:</strong> Max 10 sections, 10 rows per section. Row title max 24 chars, description max 72 chars. Body text max 1024 chars. Button text max 20 chars. Header text max 60 chars. Footer max 60 chars.
        </div>

        {/* Phone selector */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {PHONES.map(p => (
            <button key={p.metaId} onClick={() => setSelectedPhone(p)}
              style={{ padding: '8px 16px', borderRadius: 6, border: selectedPhone.metaId === p.metaId ? '2px solid #1a3a2a' : '1px solid #ddd', background: selectedPhone.metaId === p.metaId ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 }}>
              {p.name} ({p.display})
            </button>
          ))}
        </div>

        {/* Presets */}
        <div style={{ ...cs.card, background: '#f9fafb' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Quick Presets</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {PRESETS.map((p, i) => (
              <button key={i} onClick={() => loadPreset(p)}
                style={{ padding: '6px 14px', background: '#fff', border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}>
                {p.name}
              </button>
            ))}
          </div>
        </div>

        {/* Compose Form */}
        <div style={cs.card}>
          <div style={{ display: 'grid', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>Recipient Phone Number</label>
              <input value={to} onChange={e => setTo(e.target.value)} placeholder="919330994400"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>Header Text (optional, max 60)</label>
                <input value={headerText} onChange={e => setHeaderText(e.target.value)} maxLength={60} placeholder="Menu Header"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>Button Text (max 20)</label>
                <input value={buttonText} onChange={e => setButtonText(e.target.value)} maxLength={20} placeholder="View Options"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }} />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>Body Text (required, max 1024)</label>
              <textarea value={bodyText} onChange={e => setBodyText(e.target.value)} maxLength={1024} rows={3} placeholder="Please select an option below."
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14, resize: 'vertical' }} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>Footer Text (optional, max 60)</label>
              <input value={footerText} onChange={e => setFooterText(e.target.value)} maxLength={60} placeholder="Powered by WECARE"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }} />
            </div>
          </div>
        </div>

        {/* Sections Builder */}
        <div style={{ ...cs.card }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Sections & Rows</span>
            <button onClick={addSection} style={{ padding: '4px 12px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}>+ Add Section</button>
          </div>
          {sections.map((section, si) => (
            <div key={si} style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: 14, marginBottom: 10 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
                <input value={section.title} onChange={e => updateSection(si, 'title', e.target.value)} placeholder={`Section ${si + 1} title`}
                  style={{ flex: 1, padding: '6px 10px', border: '1px solid #ddd', borderRadius: 6, fontSize: 13, fontWeight: 500 }} />
                {sections.length > 1 && (
                  <button onClick={() => removeSection(si)} style={{ padding: '4px 10px', background: '#f9fafb', color: '#1a3a2a', border: '1px solid #e5e7eb', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}>Remove</button>
                )}
              </div>
              {section.rows.map((row, ri) => (
                <div key={ri} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6, marginLeft: 16 }}>
                  <input value={row.id} onChange={e => updateRow(si, ri, 'id', e.target.value)} placeholder="row_id" style={{ width: 80, padding: '5px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }} />
                  <input value={row.title} onChange={e => updateRow(si, ri, 'title', e.target.value)} placeholder="Row title (max 24)" maxLength={24}
                    style={{ flex: 1, padding: '5px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }} />
                  <input value={row.description || ''} onChange={e => updateRow(si, ri, 'description', e.target.value)} placeholder="Description (max 72)" maxLength={72}
                    style={{ flex: 2, padding: '5px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }} />
                  {section.rows.length > 1 && (
                    <button onClick={() => removeRow(si, ri)} style={{ padding: '2px 8px', background: 'none', color: '#1a3a2a', border: 'none', cursor: 'pointer', fontSize: 14 }}>×</button>
                  )}
                </div>
              ))}
              <button onClick={() => addRow(si)} style={{ marginLeft: 16, padding: '3px 10px', background: '#fff', border: '1px solid #d1d5db', borderRadius: 4, cursor: 'pointer', fontSize: 11, marginTop: 4 }}>+ Add Row</button>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20 }}>
          <button onClick={handleSend} disabled={sending}
            style={{ padding: '10px 24px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14, fontWeight: 600 }}>
            {sending ? 'Sending...' : 'Send List Message'}
          </button>
          <button onClick={() => setJsonPreview(!jsonPreview)}
            style={{ padding: '10px 16px', background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, cursor: 'pointer', fontSize: 13 }}>
            {jsonPreview ? 'Hide' : 'Show'} JSON Preview
          </button>
        </div>

        {/* JSON Preview */}
        {jsonPreview && (
          <div style={cs.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>API Payload Preview</span>
              <button onClick={() => { navigator.clipboard.writeText(JSON.stringify(getPayloadPreview(), null, 2)); toast.success('Copied'); }}
                style={{ padding: '4px 10px', background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: 4, cursor: 'pointer', fontSize: 11 }}>Copy</button>
            </div>
            <pre style={{ background: '#000', color: '#e2e8f0', padding: 14, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 300 }}>
              {JSON.stringify(getPayloadPreview(), null, 2)}
            </pre>
          </div>
        )}

        {/* Last Result */}
        {lastResult && (
          <div style={{ ...cs.card, background: '#f9fafb', border: '1px solid #e5e7eb' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f2a1d' }}>Last Send Result</span>
            <pre style={{ margin: '8px 0 0', fontSize: 12, color: '#0f2a1d' }}>{JSON.stringify(lastResult, null, 2)}</pre>
          </div>
        )}

        {/* API Reference */}
        <div style={{ ...cs.card, marginTop: 8 }}>
          <h4 style={{ margin: '0 0 8px', fontSize: 14 }}>API Reference</h4>
          <div style={{ fontSize: 13, color: '#666', lineHeight: 1.8 }}>
            <div>Endpoint: <code style={{ fontSize: 12, background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>POST /{'<PHONE_NUMBER_ID>'}/messages</code></div>
            <div>Type: <code style={{ fontSize: 12, background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>interactive → list</code></div>
            <div>Docs: <a href="https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages" target="_blank" rel="noopener noreferrer" style={{ color: '#1a3a2a' }}>Meta Interactive List Messages ↗</a></div>
          </div>
        </div>
      </div>
    </>
  );

  if (embedded) return content;

  return (
    <Layout user={user} onSignOut={signOut}>
      {content}
    </Layout>
  );
};

export default InteractiveListsPage;
