/**
 * Messages Hub - Quick Actions & Overview
 * Each channel has its own page; this is the central hub
 */

import React, { Suspense, useState } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';
import { WhatsAppIcon, SmsIcon, VoiceIcon, EmailIcon, RcsIcon, LogsIcon, ContactsIcon, CreateIcon } from '../../../lib/icons';

interface PageProps { signOut?: () => void; user?: any; }

// FEAT-005: the messaging automation/tooling pages (Automation, Content Library, Analytics,
// Cost & Usage, Message Search, Meta AI Agent, Docs Scraper, Scheduled, Contact 360) are in-page
// tabs on this Messages hub now — their bodies moved OUT of the routes tree into
// src/components/workspace/messaging/** so each stops being its own route. Loaded on demand.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}
const AutomationPage = lazyTab( () => import( '../../../components/workspace/messaging/Automation' ) );
const ContentPage = lazyTab( () => import( '../../../components/workspace/messaging/Content' ) );
const AnalyticsPage = lazyTab( () => import( '../../../components/workspace/messaging/Analytics' ) );
const CostPage = lazyTab( () => import( '../../../components/workspace/messaging/Cost' ) );
const SearchPage = lazyTab( () => import( '../../../components/workspace/messaging/Search' ) );
const MetaAgentPage = lazyTab( () => import( '../../../components/workspace/messaging/MetaAgent' ) );
const DocsScraperPage = lazyTab( () => import( '../../../components/workspace/messaging/DocsScraper' ) );
const ScheduledPage = lazyTab( () => import( '../../../components/workspace/messaging/Scheduled' ) );
const Contact360Page = lazyTab( () => import( '../../../components/workspace/messaging/Contact360' ) );
// FEAT-003: Message logs is a tab on this hub now (beside Analytics), not a standalone sidebar
// destination. The body stays at ./logs (a real route the per-channel hubs also embed); here it
// renders unlocked, showing every channel. `../logs` resolves to pages/workspace/engage/logs.
const LogsPage = lazyTab( () => import( './logs' ) );

const HUB_TABS: ShellTab[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'scheduled', label: 'Scheduled', divider: true },
  { id: 'automation', label: 'Automation' },
  { id: 'content', label: 'Content Library' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'logs', label: 'Message logs' },
  { id: 'cost', label: 'Cost & Usage' },
  { id: 'search', label: 'Message Search' },
  { id: 'meta-agent', label: 'Meta AI Agent' },
  { id: 'docs', label: 'Docs Scraper' },
  { id: 'contact-360', label: 'Contact 360' },
];

// FEAT-005: /workspace/engage?tab=<id> deep-links open the matching tab.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  return id && HUB_TABS.some( ( t ) => t.id === id ) ? id : 'overview';
}

/* Push notification bell icon */
const PushIcon: React.FC<{ size?: number; color?: string }> = ({ size = 18, color = 'var(--accent)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
  </svg>
);

// WhatsApp points at the inbox filter directly. It pointed at /workspace/engage/whatsapp,
// which since 2026-10-15 is a router.replace signpost to this same URL, so the tile
// lands where it always did, minus a redirect.
const channels = [
  // FEAT-005: the per-channel routes (sms/rcs/ses/voice/push) are now tabs on the single
  // Channels hub, reached as /workspace/engage/channels?tab=<id>. WhatsApp stays an inbox
  // filter. These tiles land on the right Channels tab, minus the removed standalone routes.
  { id: 'whatsapp', label: 'WhatsApp', desc: 'Business API messaging, campaigns & templates', path: '/workspace/engage/inbox?channel=whatsapp', Icon: WhatsAppIcon, color: '#25D366', count: 0 },
  { id: 'sms', label: 'SMS', desc: 'Transactional and promotional SMS', path: '/workspace/engage/channels?tab=sms', Icon: SmsIcon, color: '#3B82F6', count: 0 },
  { id: 'voice', label: 'Voice', desc: 'Outbound calls & CDR logs', path: '/workspace/engage/channels?tab=voice', Icon: VoiceIcon, color: '#8B5CF6', count: 0 },
  { id: 'email', label: 'Email', desc: 'Amazon SES campaigns & inbox', path: '/workspace/engage/channels?tab=email', Icon: EmailIcon, color: '#EF4444', count: 0 },
  { id: 'rcs', label: 'RCS', desc: 'Rich Communication Services', path: '/workspace/engage/channels?tab=rcs', Icon: RcsIcon, color: '#F59E0B', count: 0 },
  { id: 'push', label: 'Push', desc: 'Apple APNs & Android FCM notifications', path: '/workspace/engage/channels?tab=push', Icon: PushIcon, color: '#6366F1', count: 0 },
];

const quickActions = [
  { label: 'Send Message', desc: 'Pick a contact and channel', icon: CreateIcon, action: 'send' },
  { label: 'View All Logs', desc: 'Cross-channel message history', icon: LogsIcon, action: 'logs' },
  { label: 'Contacts', desc: 'Manage your contact list', icon: ContactsIcon, action: 'contacts' },
];

const MessagesPage: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();
  const [sendOpen, setSendOpen] = useState(false);
  const [sendChannel, setSendChannel] = useState('whatsapp');
  const [sendTo, setSendTo] = useState('');
  const [sendMsg, setSendMsg] = useState('');

  const handleQuickAction = (action: string) => {
    if (action === 'send') setSendOpen(true);
    // "View All Logs — Cross-channel message history" opens the Message logs tab on this hub
    // (FEAT-003 folded the standalone engage/logs sidebar destination into a ?tab= view here).
    // It is the one logs view over MessagesTable for every channel.
    else if (action === 'logs') router.push('/workspace/engage?tab=logs');
    else if (action === 'contacts') router.push('/workspace/contacts');
  };

  const defaultTab = resolveDefaultTab(router.query.tab);

  const overview = (
      <div className="inner-page-container" style={{ maxWidth: 960 }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', margin: '0 0 4px' }}>Messages</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: 0 }}>Send and manage messages across all channels</p>
        </div>

        {/* Quick Actions */}
        <div className="dm-quick-actions">
          {quickActions.map((qa) => (
            <button key={qa.action} onClick={() => handleQuickAction(qa.action)} className="dm-qa-btn">
              <div className="dm-qa-icon"><qa.icon size={16} color="var(--accent)" /></div>
              <div>
                <div className="dm-qa-label">{qa.label}</div>
                <div className="dm-qa-desc">{qa.desc}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Channel Cards */}
        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>Channels</div>
        <div className="dm-channels">
          {channels.map((ch) => (
            <button key={ch.id} onClick={() => router.push(ch.path)} className="dm-ch-btn">
              <div className="dm-ch-icon" style={{ background: ch.color + '15' }}><ch.Icon size={18} color={ch.color} /></div>
              <div style={{ flex: 1 }}>
                <div className="dm-ch-label">{ch.label}</div>
                <div className="dm-ch-desc">{ch.desc}</div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
          ))}
        </div>
      </div>
  );

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Messages" description="Messaging hub — WhatsApp, SMS, Voice, Email, RCS" />
      <PageShell
        key={defaultTab}
        title="Messages"
        subtitle="Channels, automation, content, analytics and search in one place"
        tabs={HUB_TABS}
        defaultTab={defaultTab}
      >
        {(activeTab) => (
          <Suspense fallback={<div style={{ padding: 40, textAlign: 'center' }}>Loading…</div>}>
            {activeTab === 'overview' && overview}
            {activeTab === 'scheduled' && <ScheduledPage signOut={signOut} user={user} embedded />}
            {activeTab === 'automation' && <AutomationPage signOut={signOut} user={user} embedded />}
            {activeTab === 'content' && <ContentPage signOut={signOut} user={user} embedded />}
            {activeTab === 'analytics' && <AnalyticsPage signOut={signOut} user={user} embedded />}
            {activeTab === 'logs' && <LogsPage signOut={signOut} user={user} embedded />}
            {activeTab === 'cost' && <CostPage signOut={signOut} user={user} embedded />}
            {activeTab === 'search' && <SearchPage signOut={signOut} user={user} embedded />}
            {activeTab === 'meta-agent' && <MetaAgentPage signOut={signOut} user={user} embedded />}
            {activeTab === 'docs' && <DocsScraperPage signOut={signOut} user={user} embedded />}
            {activeTab === 'contact-360' && <Contact360Page signOut={signOut} user={user} embedded />}
          </Suspense>
        )}
      </PageShell>

      {/* Send Message Modal */}
      {sendOpen && (
        <div className="dm-modal-backdrop" onClick={() => setSendOpen(false)}>
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid rgba(209,244,112,0.3)' }}>
              <span style={{ fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--text)' }}>Send Message</span>
              <button onClick={() => setSendOpen(false)} style={{ width: 28, height: 28, borderRadius: 8, background: 'rgba(209,244,112,0.15)', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--text-base)', color: 'var(--accent)' }}>×</button>
            </div>
            <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-sm)', fontWeight: 500, color: 'var(--accent)', marginBottom: 6 }}>Channel</label>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {channels.map((ch) => (
                    <button key={ch.id} onClick={() => setSendChannel(ch.id)}
                      style={{ padding: '7px 14px', borderRadius: 10, fontSize: 'var(--text-xs)', fontWeight: sendChannel === ch.id ? 600 : 500, background: sendChannel === ch.id ? 'var(--lime)' : '#fff', color: sendChannel === ch.id ? 'var(--accent)' : 'var(--text-muted)', border: sendChannel === ch.id ? '1.5px solid var(--accent)' : '1.5px solid var(--border)', cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s' }}>
                      {ch.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-sm)', fontWeight: 500, color: 'var(--accent)', marginBottom: 6 }}>To (phone or email)</label>
                <input value={sendTo} onChange={e => setSendTo(e.target.value)} placeholder="+91 98xxx xxxxx" style={{ width: '100%', height: 42, padding: '10px 14px', fontSize: 'var(--text-md)', color: 'var(--text)', background: '#fff', border: '1.5px solid var(--lime)', borderRadius: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-sm)', fontWeight: 500, color: 'var(--accent)', marginBottom: 6 }}>Message</label>
                <textarea value={sendMsg} onChange={e => setSendMsg(e.target.value)} placeholder="Type your message..." rows={3} style={{ width: '100%', padding: '10px 14px', fontSize: 'var(--text-md)', color: 'var(--text)', background: '#fff', border: '1.5px solid var(--lime)', borderRadius: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box', resize: 'vertical' }} />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 20px', borderTop: '1px solid rgba(209,244,112,0.3)' }}>
              <button onClick={() => setSendOpen(false)} style={{ padding: '8px 16px', borderRadius: 10, fontSize: 'var(--text-sm)', fontWeight: 500, background: '#fff', color: 'var(--accent)', border: '1.5px solid var(--lime)', cursor: 'pointer', fontFamily: 'inherit' }}>Cancel</button>
              <button style={{ padding: '8px 20px', borderRadius: 10, fontSize: 'var(--text-sm)', fontWeight: 600, background: 'var(--lime)', color: 'var(--accent)', border: '1.5px solid var(--lime)', cursor: 'pointer', fontFamily: 'inherit' }}>Send</button>
            </div>
          </div>
        </div>
      )}
      {/* Responsive Styles */}
      <style jsx>{`
        .dm-quick-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px}
        .dm-qa-btn{display:flex;align-items:center;gap:12px;padding:14px 16px;background:#fff;border:1.5px solid var(--border);border-radius:13px;cursor:pointer;transition:all .15s;text-align:left;font-family:inherit;-webkit-tap-highlight-color:transparent}
        .dm-qa-btn:hover,.dm-qa-btn:active{border-color:var(--lime);box-shadow:0 2px 8px rgba(209,244,112,0.2)}
        .dm-qa-icon{width:36px;height:36px;border-radius:10px;background:rgba(209,244,112,0.15);display:flex;align-items:center;justify-content:center;flex-shrink:0}
        .dm-qa-label{font-size:var(--text-md);font-weight:600;color:var(--text)}
        .dm-qa-desc{font-size:var(--text-xs);color:var(--text-muted);margin-top:1px}
        .dm-channels{display:flex;flex-direction:column;gap:8px;margin-bottom:28px}
        .dm-ch-btn{display:flex;align-items:center;gap:14px;padding:14px 16px;background:#fff;border:1.5px solid var(--border);border-radius:13px;cursor:pointer;transition:all .15s;text-align:left;font-family:inherit;width:100%;-webkit-tap-highlight-color:transparent}
        .dm-ch-btn:hover,.dm-ch-btn:active{border-color:var(--lime);background:rgba(209,244,112,0.04)}
        .dm-ch-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
        .dm-ch-label{font-size:var(--text-md);font-weight:600;color:var(--text)}
        .dm-ch-desc{font-size:var(--text-xs);color:var(--text-muted);margin-top:1px}
        .dm-modal-backdrop{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3)}
        .dm-modal{position:relative;background:#fff;border-radius:13px;width:100%;max-width:440px;box-shadow:0 20px 60px rgba(0,0,0,0.15);border:1.5px solid var(--lime);overflow:hidden;margin:16px}
        @media(max-width:768px){
          .dm-quick-actions{grid-template-columns:1fr;gap:8px}
          .dm-qa-btn{padding:16px;min-height:56px}
          .dm-qa-label{font-size:var(--text-base)}
          .dm-qa-desc{font-size:var(--text-sm)}
          .dm-ch-btn{padding:16px;min-height:60px}
          .dm-ch-label{font-size:var(--text-base)}
          .dm-ch-desc{font-size:var(--text-sm)}
          .dm-ch-icon{width:44px;height:44px}
          .dm-modal{position:fixed;bottom:0;left:0;right:0;top:auto;max-width:100%;margin:0;border-radius:16px 16px 0 0;max-height:85vh;overflow-y:auto}
          .dm-modal-backdrop{align-items:flex-end}
        }
        @media(max-width:480px){
          .dm-qa-btn{padding:14px 12px}
          .dm-ch-btn{padding:14px 12px}
        }
      `}</style>
    </Layout>
  );
};

export default MessagesPage;
