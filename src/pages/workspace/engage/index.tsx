/**
 * Messages Hub - Quick Actions & Overview
 * Each channel has its own page; this is the central hub
 */

import React, { useState } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { WhatsAppIcon, SmsIcon, VoiceIcon, EmailIcon, RcsIcon, LogsIcon, ContactsIcon, CreateIcon } from '../../../lib/icons';

interface PageProps { signOut?: () => void; user?: any; }

/* Push notification bell icon */
const PushIcon: React.FC<{ size?: number; color?: string }> = ({ size = 18, color = '#1a3a2a' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
  </svg>
);

// WhatsApp points at the inbox filter directly. It pointed at /workspace/engage/whatsapp,
// which since 2026-10-15 is a router.replace signpost to this same URL, so the tile
// lands where it always did, minus a redirect.
const channels = [
  { id: 'whatsapp', label: 'WhatsApp', desc: 'Business API messaging, campaigns & templates', path: '/workspace/engage/inbox?channel=whatsapp', Icon: WhatsAppIcon, color: '#25D366', count: 0 },
  { id: 'sms', label: 'SMS', desc: 'Transactional and promotional SMS', path: '/workspace/engage/sms', Icon: SmsIcon, color: '#3B82F6', count: 0 },
  { id: 'voice', label: 'Voice', desc: 'Outbound calls & CDR logs', path: '/workspace/engage/voice', Icon: VoiceIcon, color: '#8B5CF6', count: 0 },
  { id: 'email', label: 'Email', desc: 'Amazon SES campaigns & inbox', path: '/workspace/engage/ses', Icon: EmailIcon, color: '#EF4444', count: 0 },
  { id: 'rcs', label: 'RCS', desc: 'Rich Communication Services', path: '/workspace/engage/rcs', Icon: RcsIcon, color: '#F59E0B', count: 0 },
  { id: 'push', label: 'Push', desc: 'Apple APNs & Android FCM notifications', path: '/workspace/engage/push', Icon: PushIcon, color: '#6366F1', count: 0 },
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
    // "View All Logs — Cross-channel message history" is engage/logs, the one logs view
    // over MessagesTable for every channel. This went to /workspace/engage/whatsapp, a
    // WhatsApp-only inbox, which kept neither half of the promise; that URL is now a
    // signpost, so following it would only have added a redirect to the same mismatch.
    else if (action === 'logs') router.push('/workspace/engage/logs');
    else if (action === 'contacts') router.push('/workspace/contacts');
  };

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Messages" description="Messaging hub — WhatsApp, SMS, Voice, Email, RCS" />
      <div className="inner-page-container" style={{ maxWidth: 960 }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#1a1a1a', margin: '0 0 4px' }}>Messages</h1>
          <p style={{ fontSize: 13, color: '#6b7280', margin: 0 }}>Send and manage messages across all channels</p>
        </div>

        {/* Quick Actions */}
        <div className="dm-quick-actions">
          {quickActions.map((qa) => (
            <button key={qa.action} onClick={() => handleQuickAction(qa.action)} className="dm-qa-btn">
              <div className="dm-qa-icon"><qa.icon size={16} color="#1a3a2a" /></div>
              <div>
                <div className="dm-qa-label">{qa.label}</div>
                <div className="dm-qa-desc">{qa.desc}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Channel Cards */}
        <div style={{ fontSize: 12, fontWeight: 600, color: '#1a3a2a', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>Channels</div>
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

      {/* Send Message Modal */}
      {sendOpen && (
        <div className="dm-modal-backdrop" onClick={() => setSendOpen(false)}>
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid rgba(209,244,112,0.3)' }}>
              <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>Send Message</span>
              <button onClick={() => setSendOpen(false)} style={{ width: 28, height: 28, borderRadius: 8, background: 'rgba(209,244,112,0.15)', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, color: '#1a3a2a' }}>×</button>
            </div>
            <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#1a3a2a', marginBottom: 6 }}>Channel</label>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {channels.map((ch) => (
                    <button key={ch.id} onClick={() => setSendChannel(ch.id)}
                      style={{ padding: '7px 14px', borderRadius: 10, fontSize: 12, fontWeight: sendChannel === ch.id ? 600 : 500, background: sendChannel === ch.id ? '#d1f470' : '#fff', color: sendChannel === ch.id ? '#1a3a2a' : '#6b7280', border: sendChannel === ch.id ? '1.5px solid #1a3a2a' : '1.5px solid #e5e7eb', cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s' }}>
                      {ch.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#1a3a2a', marginBottom: 6 }}>To (phone or email)</label>
                <input value={sendTo} onChange={e => setSendTo(e.target.value)} placeholder="+91 98xxx xxxxx" style={{ width: '100%', height: 42, padding: '10px 14px', fontSize: 14, color: '#1a1a1a', background: '#fff', border: '1.5px solid #d1f470', borderRadius: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#1a3a2a', marginBottom: 6 }}>Message</label>
                <textarea value={sendMsg} onChange={e => setSendMsg(e.target.value)} placeholder="Type your message..." rows={3} style={{ width: '100%', padding: '10px 14px', fontSize: 14, color: '#1a1a1a', background: '#fff', border: '1.5px solid #d1f470', borderRadius: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box', resize: 'vertical' }} />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 20px', borderTop: '1px solid rgba(209,244,112,0.3)' }}>
              <button onClick={() => setSendOpen(false)} style={{ padding: '8px 16px', borderRadius: 10, fontSize: 13, fontWeight: 500, background: '#fff', color: '#1a3a2a', border: '1.5px solid #d1f470', cursor: 'pointer', fontFamily: 'inherit' }}>Cancel</button>
              <button style={{ padding: '8px 20px', borderRadius: 10, fontSize: 13, fontWeight: 600, background: '#d1f470', color: '#1a3a2a', border: '1.5px solid #d1f470', cursor: 'pointer', fontFamily: 'inherit' }}>Send</button>
            </div>
          </div>
        </div>
      )}
      {/* Responsive Styles */}
      <style jsx>{`
        .dm-quick-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px}
        .dm-qa-btn{display:flex;align-items:center;gap:12px;padding:14px 16px;background:#fff;border:1.5px solid #e5e7eb;border-radius:13px;cursor:pointer;transition:all .15s;text-align:left;font-family:inherit;-webkit-tap-highlight-color:transparent}
        .dm-qa-btn:hover,.dm-qa-btn:active{border-color:#d1f470;box-shadow:0 2px 8px rgba(209,244,112,0.2)}
        .dm-qa-icon{width:36px;height:36px;border-radius:10px;background:rgba(209,244,112,0.15);display:flex;align-items:center;justify-content:center;flex-shrink:0}
        .dm-qa-label{font-size:14px;font-weight:600;color:#1a1a1a}
        .dm-qa-desc{font-size:11px;color:#6b7280;margin-top:1px}
        .dm-channels{display:flex;flex-direction:column;gap:8px;margin-bottom:28px}
        .dm-ch-btn{display:flex;align-items:center;gap:14px;padding:14px 16px;background:#fff;border:1.5px solid #e5e7eb;border-radius:13px;cursor:pointer;transition:all .15s;text-align:left;font-family:inherit;width:100%;-webkit-tap-highlight-color:transparent}
        .dm-ch-btn:hover,.dm-ch-btn:active{border-color:#d1f470;background:rgba(209,244,112,0.04)}
        .dm-ch-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
        .dm-ch-label{font-size:15px;font-weight:600;color:#1a1a1a}
        .dm-ch-desc{font-size:12px;color:#6b7280;margin-top:1px}
        .dm-modal-backdrop{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3)}
        .dm-modal{position:relative;background:#fff;border-radius:13px;width:100%;max-width:440px;box-shadow:0 20px 60px rgba(0,0,0,0.15);border:1.5px solid #d1f470;overflow:hidden;margin:16px}
        @media(max-width:768px){
          .dm-quick-actions{grid-template-columns:1fr;gap:8px}
          .dm-qa-btn{padding:16px;min-height:56px}
          .dm-qa-label{font-size:16px}
          .dm-qa-desc{font-size:13px}
          .dm-ch-btn{padding:16px;min-height:60px}
          .dm-ch-label{font-size:16px}
          .dm-ch-desc{font-size:13px}
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
