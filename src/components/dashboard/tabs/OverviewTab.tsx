/**
 * Overview Tab — Dashboard statistics and quick actions
 */
import React from 'react';
import Link from 'next/link';
import type { DashboardData } from '../../../types/dashboard';
import {
  WhatsAppIcon, PaymentIcon, InvoiceIcon, LinkIcon,
  ContactsIcon, BulkIcon, SmsIcon, EmailIcon,
} from '../../../lib/icons';

interface OverviewTabProps {
  data: DashboardData;
}

const OverviewTab: React.FC<OverviewTabProps> = ({ data }) => {
  const { contacts, messages } = data;

  const todayMessages = messages.filter(m => {
    const msgDate = new Date(m.timestamp);
    const today = new Date();
    return msgDate.toDateString() === today.toDateString();
  });
  const inboundCount = messages.filter(m => m.direction === 'INBOUND').length;
  const outboundCount = messages.filter(m => m.direction === 'OUTBOUND').length;
  const paymentMessages = messages.filter(
    m => m.messageType === 'payment' || m.messageType === 'payment_request',
  );
  const capturedPayments = paymentMessages.filter(
    m => (m as any).paymentStatus === 'captured',
  ).length;

  return (
    <div className="overview">
      <div className="section full-width">
        <h3>Statistics</h3>
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{contacts.length}</div>
            <div className="stat-label">Contacts</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{messages.length}</div>
            <div className="stat-label">Messages</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{todayMessages.length}</div>
            <div className="stat-label">Today</div>
          </div>
          <div className="stat-card accent">
            <div className="stat-value">{inboundCount}</div>
            <div className="stat-label">Inbound</div>
          </div>
          <div className="stat-card accent2">
            <div className="stat-value">{outboundCount}</div>
            <div className="stat-label">Outbound</div>
          </div>
          <div className="stat-card success">
            <div className="stat-value">{capturedPayments}</div>
            <div className="stat-label">Paid</div>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>Quick Actions</h3>
        <div className="actions-grid">
          <Link href="/workspace/communications?view=inbox&channel=whatsapp" className="action-card">
            <span className="icon"><WhatsAppIcon size={20} /></span>
            <span>WhatsApp</span>
          </Link>
          <Link href="/workspace/payments?view=collect" className="action-card">
            <span className="icon"><PaymentIcon size={20} /></span>
            <span>Pay</span>
          </Link>
          <Link href="/workspace/payments?view=invoices" className="action-card">
            <span className="icon"><InvoiceIcon size={20} /></span>
            <span>Invoice</span>
          </Link>
          <Link href="/workspace/communications?view=manage&section=links" className="action-card">
            <span className="icon"><LinkIcon size={20} /></span>
            <span>Link</span>
          </Link>
          <Link href="/workspace/customers" className="action-card">
            <span className="icon"><ContactsIcon size={20} /></span>
            <span>Contacts</span>
          </Link>
          <Link href="/workspace/engage/broadcast" className="action-card">
            <span className="icon"><BulkIcon size={20} /></span>
            <span>Campaign</span>
          </Link>
          <Link href="/workspace/engage/channels?tab=sms" className="action-card">
            <span className="icon"><SmsIcon size={20} /></span>
            <span>SMS</span>
          </Link>
          <Link href="/workspace/engage/channels?tab=email" className="action-card">
            <span className="icon"><EmailIcon size={20} /></span>
            <span>Email</span>
          </Link>
        </div>
      </div>

      <div className="section">
        <h3>WhatsApp Numbers</h3>
        <div className="phones-grid">
          <div className="phone-card">
            <div className="phone-name">WECARE.DIGITAL</div>
            <div className="phone-num">+91 93309 94400</div>
            <span className="badge">Razorpay</span>
          </div>
          <div className="phone-card">
            <div className="phone-name">Manish Agarwal</div>
            <div className="phone-num">+91 99033 00044</div>
            <span className="badge">Active</span>
          </div>
        </div>
      </div>

      <div className="section full-width">
        <div className="section-header">
          <h3>Recent Messages</h3>
          <Link href="/workspace/communications?view=inbox&channel=whatsapp" className="link">View All</Link>
        </div>
        <div className="msg-list">
          {messages.slice(0, 5).map(msg => {
            const contact = contacts.find(c => c.id === msg.contactId);
            return (
              <div key={msg.id} className={`msg-item ${msg.direction.toLowerCase()}`}>
                <span className="dir">{msg.direction === 'INBOUND' ? '↓' : '↑'}</span>
                <span className="name">{contact?.name || contact?.phone || '...'}</span>
                <span className="content">{msg.content?.slice(0, 50) || '[Media]'}</span>
                <span className="time">
                  {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            );
          })}
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-title">No messages yet</div>
              <div className="empty-state-description">Messages will appear here once you start sending or receiving.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default OverviewTab;
