/**
 * Request → Responses — the one operational queue for everything a customer submitted.
 *
 * This is the merge the Phase 1 audit asked for. The same submission data used to live in four
 * places (forms/responses, engage/whatsapp/flow-responses "Legacy Requests", flow-hub
 * "Submissions", forms/selfservice "Submissions"), each a separate fetch/filter/badge. This page
 * renders the shared ResponsesQueue — server-backed search and filters, error-vs-empty states,
 * masked phone, per-row status mutation — and the old surfaces redirect here.
 *
 * noindex: a staff operations screen must never be crawled or ranked.
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import ResponsesQueue from '../../../components/service/ResponsesQueue';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const RequestResponsesPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const content = (
    <main style={{ padding: embedded ? 0 : '24px', maxWidth: 1200, margin: '0 auto' }}>
      {!embedded && (
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'rgba(0,0,0,.95)', margin: 0 }}>Responses</h1>
          <p style={{ color: '#64748b', fontSize: 14, margin: '4px 0 0' }}>
            Every request, review and submission across WhatsApp Flows and the website — one queue.
          </p>
        </header>
      )}
      <ResponsesQueue />
    </main>
  );
  if ( embedded ) return content;
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO
        title="Responses | Service Operations"
        description="One operational queue for every customer request, review and submission."
        noindex
      />
      {content}
    </Layout>
  );
};

export default RequestResponsesPage;
