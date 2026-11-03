/**
 * /ws/commerce — the fresh, mobile-first Commerce surface (FEAT-003).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * This surface intentionally exposes Orders only. The image-based Catalog management panel is
 * not part of the fresh /ws workflow. Reuse the proven embeddable Orders.tsx panel with
 * { signOut, user, embedded:true }, keeping order behaviour unchanged. Its min-width:0 /
 * overflow-x container prevents a wide table from scrolling the entire shell sideways.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';

interface PageProps { signOut?: () => void; user?: any; }
interface PanelProps { signOut?: () => void; user?: any; embedded?: boolean; }

// Reuse the existing embeddable Orders panel. ssr:false keeps its bundle out of the initial /ws payload.
const Orders = dynamic<PanelProps>(
  () => import( '../../../components/workspace/commerce/Orders' ), { ssr: false },
);

const WsCommerce: React.FC<PageProps> = ( { signOut, user } ) => {
  return (
    <>
      <SEO title="Commerce" description="WECARE workspace commerce." noindex />
      <WsShell active="commerce" user={ user } signOut={ signOut }>
        <section className="wsx">
          <header className="wsx-head">
            <p className="wsx-eyebrow">Workspace</p>
            <h1 className="wsx-title">Commerce</h1>
            <p className="wsx-sub">Review and manage customer orders.</p>
          </header>

          {/* The reused panel scrolls inside this box, so a wide table never drags the whole
              shell sideways. min-width:0 lets the box actually shrink inside the grid. */}
          <div className="wsx-panel">
            <Suspense fallback={ <div className="wsx-loading">Loading…</div> }>
              <Orders signOut={ signOut } user={ user } embedded />
            </Suspense>
          </div>
        </section>

        <style jsx>{ `
          .wsx{ width:100%; min-width:0; display:grid; gap:16px; }
          .wsx-head{ display:grid; gap:4px; }
          .wsx-eyebrow{
            margin:0; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;
            color:var(--text-muted,#6b7280);
          }
          .wsx-title{ margin:0; font-size:24px; font-weight:700; letter-spacing:-0.5px; color:var(--text,#1a1a1a); }
          .wsx-sub{ margin:0; font-size:13px; line-height:1.6; color:var(--text-muted,#6b7280); }

          .wsx-panel{
            min-width:0;
            max-width:100%;
            overflow-x:auto;
            -webkit-overflow-scrolling:touch;
          }
          .wsx-loading{ padding:48px; text-align:center; color:var(--text-muted,#6b7280); }

        ` }</style>
      </WsShell>
    </>
  );
};

export default WsCommerce;
