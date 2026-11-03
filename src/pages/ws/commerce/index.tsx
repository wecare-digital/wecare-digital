/**
 * /ws/commerce — the fresh, mobile-first Commerce surface (FEAT-003).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * The CHROME is fresh and mobile-first (an Orders | Catalog segmented switch inside WsShell), but
 * the order/catalog LOGIC is NOT reimplemented: the proven embeddable panels
 * src/components/workspace/commerce/Orders.tsx and Catalog.tsx are reused as-is with
 * { signOut, user, embedded:true } (the same composition src/pages/workspace/commerce/index.tsx
 * uses). Each panel is rendered inside a min-width:0 / overflow-x container so a wide table never
 * forces the whole WsShell to scroll sideways on a phone — the panel scrolls within its own box.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';

interface PageProps { signOut?: () => void; user?: any; }
interface PanelProps { signOut?: () => void; user?: any; embedded?: boolean; }

type View = 'orders' | 'catalog';

// Reuse the existing embeddable panels; ssr:false matches the reference composition and keeps the
// heavy commerce bundles out of the initial /ws payload.
const Orders = dynamic<PanelProps>(
  () => import( '../../../components/workspace/commerce/Orders' ), { ssr: false },
);
const Catalog = dynamic<PanelProps>(
  () => import( '../../../components/workspace/commerce/Catalog' ), { ssr: false },
);

const VIEWS: { id: View; label: string }[] = [
  { id: 'orders', label: 'Orders' },
  { id: 'catalog', label: 'Catalog' },
];

const WsCommerce: React.FC<PageProps> = ( { signOut, user } ) => {
  const [ view, setView ] = React.useState<View>( 'orders' );

  return (
    <>
      <SEO title="Commerce" description="WECARE workspace commerce." noindex />
      <WsShell active="commerce" user={ user } signOut={ signOut }>
        <section className="wsx">
          <header className="wsx-head">
            <p className="wsx-eyebrow">Workspace</p>
            <h1 className="wsx-title">Commerce</h1>
            <p className="wsx-sub">One order queue and one authoritative catalog.</p>
          </header>

          <div className="wsx-tabs" role="tablist" aria-label="Commerce sections">
            { VIEWS.map( v => (
              <button
                key={ v.id }
                type="button"
                role="tab"
                aria-selected={ view === v.id }
                className={ `wsx-tab ${ view === v.id ? 'on' : '' }` }
                onClick={ () => setView( v.id ) }
              >
                { v.label }
              </button>
            ) ) }
          </div>

          {/* The reused panel scrolls inside this box, so a wide table never drags the whole
              shell sideways. min-width:0 lets the box actually shrink inside the grid. */}
          <div className="wsx-panel" role="tabpanel">
            <Suspense fallback={ <div className="wsx-loading">Loading…</div> }>
              { view === 'orders'
                ? <Orders signOut={ signOut } user={ user } embedded />
                : <Catalog signOut={ signOut } user={ user } embedded /> }
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

          /* A calm Notion segmented control matching /ws/collect: the active tab lifts to a white
             pill with forest-green text and a soft shadow, not a heavy solid-green fill. */
          .wsx-tabs{
            display:inline-flex; gap:4px; padding:4px;
            border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
            background:var(--bg-secondary,#f9fafb); align-self:start; max-width:100%; overflow-x:auto;
          }
          .wsx-tab{
            flex:0 0 auto; min-height:var(--tap-min,44px); padding:8px 24px;
            border:0; border-radius:var(--radius-full,9999px); background:transparent;
            color:var(--text-muted,#6b7280); font:inherit; font-weight:600; font-size:14px; cursor:pointer;
            transition:background var(--transition-normal,0.15s ease),color var(--transition-normal,0.15s ease);
          }
          .wsx-tab:hover:not(.on){ color:var(--text,#1a1a1a); }
          .wsx-tab.on{
            background:var(--surface,#fff); color:var(--accent,#1a3a2a); font-weight:700;
            box-shadow:var(--shadow-sm,0 1px 2px rgba(0,0,0,.04));
          }
          .wsx-tab:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

          .wsx-panel{
            min-width:0;
            max-width:100%;
            overflow-x:auto;
            -webkit-overflow-scrolling:touch;
          }
          .wsx-loading{ padding:48px; text-align:center; color:var(--text-muted,#6b7280); }

          @media (max-width:560px){
            .wsx-tabs{ display:flex; width:100%; }
            .wsx-tab{ flex:1 1 0; padding:8px 12px; }
          }

          @media (prefers-reduced-motion:reduce){
            .wsx-tab{ transition:none; }
          }
        ` }</style>
      </WsShell>
    </>
  );
};

export default WsCommerce;
