/**
 * Service Hub — [retired public path]
 * Landing page for all service modules with quick-access cards.
 */
import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; }

const SERVICE_MODULES = [
  { path: '/workspace/service/submit-request', label: 'Submit Request', icon: '📝', desc: 'Submit a new service request linked to an order', color: '#dbeafe' },
  { path: '/workspace/service/track-request', label: 'Track Request', icon: '📊', desc: 'Track all service activity for an order', color: '#d1fae5' },
  { path: '/workspace/service/amend-request', label: 'Amend Request', icon: '✏️', desc: 'Modify or add info to an existing request', color: '#fef3c7' },
  { path: '/workspace/engage/whatsapp/flow-responses', label: 'All Submissions', icon: '📋', desc: 'View all flow submissions across all types', color: '#f3e8ff' },
  { path: '/workspace/engage/whatsapp/flow-hub', label: 'Flow Hub', icon: '🔄', desc: 'Manage WhatsApp flow configurations', color: '#e0e7ff' },
  { path: '/workspace/forms/selfservice', label: 'Customer Service', icon: '🤖', desc: 'Customer service portal', color: '#fce7f3' },
];

const ServiceHubPage: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Service Hub" description="Customer service request management — submit, track, and amend requests." />
      <div style={{ padding: '24px 32px', maxWidth: 1000 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: '0 0 4px' }}>Service</h1>
        <p style={{ fontSize: 14, color: '#6b7280', margin: '0 0 24px' }}>Order-centric customer service management</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
          {SERVICE_MODULES.map(m => (
            <button
              key={m.path}
              onClick={() => router.push(m.path)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                padding: 20, border: '2px solid #f3f4f6', borderRadius: 13, background: '#fff',
                cursor: 'pointer', textAlign: 'left', transition: 'border-color 0.15s, box-shadow 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#d1f470'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.06)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = '#f3f4f6'; e.currentTarget.style.boxShadow = 'none'; }}
            >
              <div style={{ width: 40, height: 40, borderRadius: 10, background: m.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, marginBottom: 12 }}>
                {m.icon}
              </div>
              <div style={{ fontWeight: 600, fontSize: 15, color: '#1a3a2a', marginBottom: 4 }}>{m.label}</div>
              <div style={{ fontSize: 13, color: '#6b7280', lineHeight: 1.4 }}>{m.desc}</div>
            </button>
          ))}
        </div>
      </div>
    </Layout>
  );
};

export default ServiceHubPage;
