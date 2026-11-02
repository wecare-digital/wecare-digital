/**
 * Request → Responses — the one operational queue for everything a customer submitted.
 *
 * The same submission data used to live in several Flow/forms surfaces. This component renders
 * the shared ResponsesQueue — server-backed search and filters, error-vs-empty states, masked
 * phone and per-row status mutation — and is embedded by canonical Service → Requests.
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import ResponsesQueue from '../../../components/service/ResponsesQueue';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const RequestResponsesPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  if ( embedded ) {
    return (
      <div style={{ padding: 0, maxWidth: 1200, margin: '0 auto' }}>
        <ResponsesQueue />
      </div>
    );
  }

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title="Responses | Service"
        description="One operational queue for every customer request, review and submission."
        noindex
      />
      <main style={{ padding: '24px', maxWidth: 1200, margin: '0 auto' }}>
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'rgba(0, 0, 0, 0.95)', margin: 0 }}>Responses</h1>
          <p style={{ color: '#64748b', fontSize: 'var(--text-md)', margin: '4px 0 0' }}>
            Every request, review and submission across WhatsApp Flows and the website — one queue.
          </p>
        </header>
        <ResponsesQueue />
      </main>
    </Layout>
  );
};

export default RequestResponsesPage;
