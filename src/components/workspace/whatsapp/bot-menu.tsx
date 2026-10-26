/**
 * WhatsApp bot/service menu reference.
 *
 * Extracted from the retired WhatsApp settings hub so the capability can live under the
 * canonical Communications → Manage → WhatsApp surface without keeping that hub alive.
 */
import React from 'react';
import WhatsAppServiceDirectory from '../../WhatsAppServiceDirectory';
import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../lib/canonicalFlows';

// ─── Bot Menu & Customer Service Menu Data ───
const BOT_MENU = [
  { row: 1, section: 'Start Here', icon: '🚀', title: 'Customer Service', description: 'Requests, appointments, documents, and support', action: 'Opens Customer Service list' },
  { row: 2, section: 'Start Here', icon: '🔔', title: 'Subscribe', description: 'Save your details for faster service on WECARE.DIGITAL', action: 'Opens subscribe form' },
  { row: 3, section: 'Start Here', icon: '🆔', title: 'Find Profile ID', description: 'Locate your subscription or profile ID', action: 'Opens ID lookup' },
  { row: 4, section: 'Start Here', icon: '💳', title: 'Make a Payment', description: 'Pay an invoice or complete a pending payment', action: 'Opens payment lookup' },
  { row: 5, section: 'Explore WECARE', icon: '🛍️', title: 'Explore Store', description: 'Browse services, brands, and offers', action: 'CTA link → wecare.digital' },
  { row: 6, section: 'Explore WECARE', icon: '🎁', title: 'Perks', description: 'Open Perks on WhatsApp', action: 'CTA link → wa.me/message/377GALDW4E26F1' },
  { row: 7, section: 'Explore WECARE', icon: '🇮🇳', title: 'WECARE.DIGITAL', description: 'Discover WECARE.DIGITAL and services', action: 'Info text + evolving services' },
  { row: 8, section: 'Help & Answers', icon: '❓', title: 'FAQs', description: 'Find answers to common questions', action: 'Answered in chat by faq-handler' },
  { row: 9, section: 'Help & Answers', icon: '💛', title: 'About WECARE.DIGITAL', description: 'Learn more about WECARE.DIGITAL', action: 'CTA link → wecare.digital' },
];

const CUSTOMERSERVICE_MENU = [
  { row: 1, section: 'Existing Order', icon: '📋', title: 'Submit Request', description: 'Raise a request for an existing order; the Flow is deprecated, so the website link answers', flowId: canonicalFlowId('submit_request')!, keywords: 'Submit Request' },
  // Track has no canonical Flow (served by the order tracking API + /orders/); the old staff
  // id was a DEPRECATED flow. Show a dash rather than a dead id.
  { row: 2, section: 'Request Status', icon: '🔍', title: 'Track Request', description: 'Check the status of your request', flowId: canonicalFlowId('track_request') ?? '-', keywords: 'track request, track, status' },
  { row: 3, section: 'Existing Request', icon: '✏️', title: 'Request Amendment', description: 'Edit or correct a submitted request; answered with the website link (no Flow)', flowId: canonicalFlowId('amend_request') ?? '-', keywords: 'Request Amendment' },
  { row: 4, section: 'Schedule', icon: '📅', title: 'Appointment', description: 'Schedule a consultation or service visit', flowId: '1475722977488573', keywords: 'appointment, schedule, meeting' },
  { row: 5, section: 'Medical Tourism', icon: '💊', title: 'RX Slot', description: 'Schedule a medical tourism or prescription-related visit', flowId: '1892784521355352', keywords: 'rx slot, rx, prescription' },
  { row: 6, section: 'Documents', icon: '📄', title: 'Drop Docs', description: 'Send supporting documents securely; answered with the website link (no Flow)', flowId: canonicalFlowId('drop_docs') ?? '-', keywords: 'Drop Docs' },
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

export default BotMenuTab;
