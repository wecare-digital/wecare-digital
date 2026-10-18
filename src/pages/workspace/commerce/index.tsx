/**
 * Commerce — ONE page hosting the native Catalog and the Commerce engine as tabs.
 *
 * Workspace redesign (FEAT-004): Commerce 2 -> 1. The catalog page
 * (commerce/catalog) and the commerce engine view (engage/commerce) are now in-page
 * tabs here, each rendered via its `embedded` prop so every ProductsTable / order
 * ledger / src/api/client.ts call site inside them is unchanged and each route still
 * works standalone.
 *
 * NO APPLY, AND NO PAYMENT MUTATION
 * ---------------------------------
 * Storefront APPLY tools are refused in `governance.py`. Payment capture, refund and
 * payment-configuration changes are refused outright by `01-standing-authorization.md`
 * — not gated, refused.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

// FEAT-005: the catalog and commerce-engine tab bodies moved OUT of src/pages/workspace/**
// into src/components/workspace/commerce/** so each stops being its own route.
const CatalogPage = lazyTab( () => import( '../../../components/workspace/commerce/Catalog' ) );
const CommerceEnginePage = lazyTab( () => import( '../../../components/workspace/commerce/CommerceEngine' ) );

const TABS: ShellTab[] = [
  { id: 'catalog', label: 'Catalog & orders' },
  { id: 'engine', label: 'Commerce engine' },
];

// FEAT-005: /workspace/commerce?tab=<id> deep-links open the matching tab.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  return id && TABS.some( ( t ) => t.id === id ) ? id : 'catalog';
}

const CommerceHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const router = useRouter();
  const defaultTab = resolveDefaultTab( router.query.tab );
  const content = (
    <PageShell
      key={ defaultTab }
      title="Commerce"
      subtitle="Catalog, orders and store operations"
      tabs={ TABS }
      defaultTab={ defaultTab }
    >
      { ( activeTab ) => (
        <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
          { activeTab === 'catalog' && <CatalogPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'engine' && <CommerceEnginePage signOut={ signOut } user={ user } embedded /> }
        </Suspense>
      ) }
    </PageShell>
  );

  if ( embedded ) return content;
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Commerce" description="Catalog, orders and store operations in one place." noindex />
      { content }
    </Layout>
  );
};

export default CommerceHub;
