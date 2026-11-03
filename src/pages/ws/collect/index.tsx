/**
 * /ws/collect — placeholder. Filled in by a later feature (FEAT-002..FEAT-004).
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); receives { signOut, user }.
 */
import React from 'react';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';

interface PageProps { signOut?: () => void; user?: any; }

const WsCollect: React.FC<PageProps> = ( { signOut, user } ) => (
  <>
    <SEO title="Collect" description="WECARE workspace collect." noindex />
    <WsShell active="collect" user={ user } signOut={ signOut }>
      <section className="ws-page">
        <h1 className="ws-page-title">Collect</h1>
        <p className="ws-page-note">Invoices, receipts and Vault are coming soon.</p>
      </section>

      <style jsx>{`
        .ws-page{ width:100%; min-width:0; }
        .ws-page-title{
          margin:0 0 8px;
          font-size:26px;
          font-weight:700;
          letter-spacing:-0.5px;
          color:var(--text,#1a1a1a);
        }
        .ws-page-note{
          margin:0;
          font-size:15px;
          color:var(--text-muted,#6b7280);
        }
      `}</style>
    </WsShell>
  </>
);

export default WsCollect;
