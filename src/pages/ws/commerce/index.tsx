/**
 * /ws/commerce — Notion-inspired, mobile-first workspace for Orders and a
 * text-only, server-priced Catalog. The old image-based product editor is not
 * mounted here. The authenticated shell and proven Orders logic are unchanged.
 *
 * Catalog is read-only: the shared service-pricing parser validates server
 * amounts, and this page never initiates a payment or computes charges.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';

interface PageProps { signOut?: () => void; user?: any; }
interface PanelProps { signOut?: () => void; user?: any; embedded?: boolean; }
type View = 'orders' | 'catalog';

const Orders = dynamic<PanelProps>(
  () => import('../../../components/workspace/commerce/Orders'), { ssr: false },
);
const PriceCatalog = dynamic(
  () => import('../../../components/ws/commerce/PriceCatalogPanel'), { ssr: false },
);

const WsCommerce: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();
  const view: View = router.query.view === 'catalog' ? 'catalog' : 'orders';

  return (
    <>
      <SEO title="Commerce" description="WECARE workspace orders and verified price catalog." noindex />
      <WsShell active="commerce" user={user} signOut={signOut}>
        <section className="wsx">
          <header className="wsx-head">
            <p className="wsx-eyebrow">Workspace / Commerce</p>
            <h1 className="wsx-title">Commerce</h1>
            <p className="wsx-sub">Your orders and a clear, itemised pricing catalog — no product images.</p>
          </header>

          <nav className="wsx-tabs" aria-label="Commerce sections">
            <Link href="/ws/commerce" className={view === 'orders' ? 'wsx-tab on' : 'wsx-tab'}
              aria-current={view === 'orders' ? 'page' : undefined}>Orders</Link>
            <Link href="/ws/commerce?view=catalog" className={view === 'catalog' ? 'wsx-tab on' : 'wsx-tab'}
              aria-current={view === 'catalog' ? 'page' : undefined}>Pricing catalog</Link>
          </nav>

          <div className={view === 'orders' ? 'wsx-panel wsx-orders' : 'wsx-panel'}>
            <Suspense fallback={<p className="wsx-loading">Loading workspace…</p>}>
              {view === 'orders'
                ? <Orders signOut={signOut} user={user} embedded />
                : <PriceCatalog />}
            </Suspense>
          </div>
        </section>

        <style jsx>{`
          .wsx{width:100%;min-width:0;display:grid;gap:18px}
          .wsx-head{display:grid;gap:5px}
          .wsx-eyebrow{margin:0;font-size:11px;font-weight:750;letter-spacing:.07em;text-transform:uppercase;color:var(--text-muted,#6b7280)}
          .wsx-title{margin:0;font-size:clamp(26px,3vw,33px);font-weight:750;letter-spacing:-.04em;color:var(--text,#1a1a1a)}
          .wsx-sub{margin:0;font-size:13px;line-height:1.6;color:var(--text-muted,#6b7280)}
          .wsx-tabs{display:flex;flex-wrap:wrap;gap:3px;width:max-content;max-width:100%;padding:4px;border:1px solid var(--border,#e5e7eb);border-radius:10px;background:var(--bg-secondary,#f9fafb)}
          .wsx-tabs :global(.wsx-tab){min-height:42px;display:inline-flex;align-items:center;justify-content:center;padding:8px 18px;box-sizing:border-box;border-radius:7px;text-decoration:none;color:var(--text-muted,#6b7280);font-weight:650;font-size:13px}
          .wsx-tabs :global(.wsx-tab:hover){color:var(--text,#1a1a1a)}
          .wsx-tabs :global(.wsx-tab.on){background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.07);color:var(--accent,#1a3a2a)}
          .wsx-tabs :global(.wsx-tab:focus-visible){outline:2px solid var(--accent,#1a3a2a);outline-offset:1px}
          .wsx-panel{min-width:0;max-width:100%}
          .wsx-orders{overflow-x:auto;-webkit-overflow-scrolling:touch}
          .wsx-loading{margin:0;padding:48px 12px;text-align:center;color:var(--text-muted,#6b7280)}
          @media(max-width:460px){.wsx-tabs{width:100%}.wsx-tabs :global(.wsx-tab){flex:1 1 0;padding:9px 12px}}
        `}</style>
      </WsShell>
    </>
  );
};

export default WsCommerce;
