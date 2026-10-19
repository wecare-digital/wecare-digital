/**
 * Canonical Commerce workspace.
 *
 * Commerce owns exactly two primary jobs:
 * - Orders: every order source and fulfilment state in one queue.
 * - Catalog: ProductsTable, variants, inventory and publishing.
 *
 * Payment collection belongs to Payments; channel delivery belongs to Communications.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type View = 'orders' | 'catalog';

function lazyPanel<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const Orders = lazyPanel<PageProps>( () => import( '../../../components/workspace/commerce/Orders' ) );
const Catalog = lazyPanel<PageProps>( () => import( '../../../components/workspace/commerce/Catalog' ) );

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function resolveView ( query: Record<string, string | string[] | undefined> ): View {
  const view = one( query.view );
  if ( view === 'catalog' ) return 'catalog';

  // Compatibility for the old Commerce hub query contract.
  const legacyTab = one( query.tab );
  if ( legacyTab === 'catalog' ) return 'catalog';

  return 'orders';
}

const CommercePage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const view = resolveView( router.query );

  const go = ( next: View ) => {
    void router.push( { pathname: '/workspace/commerce', query: { view: next } } );
  };

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Commerce" description="Orders and catalog operations." noindex />
      <div className="commerce-page">
        <header className="commerce-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Commerce</h1>
            <p>One order queue and one authoritative catalog.</p>
          </div>
        </header>

        <nav className="commerce-tabs" aria-label="Commerce">
          <button type="button" className={ view === 'orders' ? 'active' : '' }
            aria-current={ view === 'orders' ? 'page' : undefined }
            onClick={ () => go( 'orders' ) }>Orders</button>
          <button type="button" className={ view === 'catalog' ? 'active' : '' }
            aria-current={ view === 'catalog' ? 'page' : undefined }
            onClick={ () => go( 'catalog' ) }>Catalog</button>
        </nav>

        <Suspense fallback={ <div className="commerce-loading">Loading…</div> }>
          { view === 'orders'
            ? <Orders signOut={ signOut } user={ user } embedded />
            : <Catalog signOut={ signOut } user={ user } embedded /> }
        </Suspense>
      </div>

      <style jsx>{`
        .commerce-page{width:min(100%,1360px);margin:0 auto;padding:clamp(16px,3vw,32px);box-sizing:border-box;min-width:0}
        .commerce-head{margin-bottom:18px}
        .eyebrow{margin:0 0 4px;color:var(--text-muted);font-size:var(--text-xs);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
        .commerce-head h1{margin:0;color:var(--text);font-size:clamp(28px,5vw,48px);line-height:1.05;letter-spacing:-.035em}
        .commerce-head>div>p:last-child{margin:8px 0 0;color:var(--text-muted);font-size:var(--text-md)}
        .commerce-tabs{display:flex;gap:6px;padding:4px;width:max-content;max-width:100%;background:var(--bg-secondary);border:1px solid var(--border);border-radius:14px;margin-bottom:18px}
        .commerce-tabs button{min-height:44px;min-width:120px;padding:8px 18px;border:0;border-radius:10px;background:transparent;color:var(--text-muted);font:inherit;font-weight:700;cursor:pointer}
        .commerce-tabs button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
        .commerce-loading{padding:48px;text-align:center;color:var(--text-muted)}
        @media(max-width:760px){
          .commerce-page{padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));padding-bottom:max(24px,env(safe-area-inset-bottom))}
          .commerce-tabs{width:100%}
          .commerce-tabs button{flex:1;min-width:0}
        }
        @media(forced-colors:active){.commerce-tabs{border-color:CanvasText}}
      `}</style>
    </Layout>
  );
};

export default CommercePage;
