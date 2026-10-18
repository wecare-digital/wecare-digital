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
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';
import { featureFlags } from '../../../config/featureFlags';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

/**
 * Commerce is a module home behind NEXT_PUBLIC_ENABLE_COMMERCE_MODULE, and OFF. When the flag
 * is off this panel + the native-page list say WHY (every capability already works at its own
 * page) and link the working pages rather than shadowing them — the master-prompt rule the
 * FeatureFlags contract pins. The working catalog/engine tabs below still render, so turning
 * the flag on only removes this explanation; it does not add the tabs.
 */
const ModuleHomeOff: React.FC = () => (
  <div style={ { display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 760, marginBottom: 20 } }>
    <div style={ {
      padding: 20, border: '1px solid var(--border)', borderLeft: '3px solid #b45309',
      borderRadius: 13, background: '#fffbeb',
    } }>
      <div style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: '#78350f', marginBottom: 6 } }>
        The Commerce module is switched off
      </div>
      <p style={ { fontSize: 'var(--text-sm)', color: '#92400e', lineHeight: 1.6, margin: '0 0 10px' } }>
        Not because it is unfinished, but because every capability it would gather already works
        at its own page. Turning this on adds a second way to do the same things rather than a
        better one, so it should be opened on purpose.
      </p>
      <p style={ { fontSize: 'var(--text-sm)', color: '#92400e', lineHeight: 1.6, margin: 0 } }>
        Set
        <code style={ { margin: '0 4px', padding: '1px 6px', borderRadius: 4, background: 'var(--bg)', fontSize: 'var(--text-xs)' } }>NEXT_PUBLIC_ENABLE_COMMERCE_MODULE=true</code>
        to gather them here.
      </p>
    </div>
    <div>
      <p style={ { fontSize: 'var(--text-sm)', color: 'var(--text)', lineHeight: 1.6, marginTop: 0 } }>
        These already work. Listed rather than duplicated:
      </p>
      <div style={ { border: '1px solid var(--border)', borderRadius: 13, overflow: 'hidden', background: 'var(--bg)' } }>
        { ( [
          { href: '/workspace/commerce?tab=catalog', label: 'Catalog', note: 'Products, brands and offers' },
          { href: '/workspace/commerce?tab=engine', label: 'Commerce engine', note: 'Store operations' },
          { href: '/workspace/pay', label: 'Payments overview', note: 'Links, flows and status' },
          { href: '/workspace/pay?tab=records', label: 'Invoice records', note: 'The billed/paid/delivered ledger' },
        ] ).map( ( item, i ) => (
          <Link key={ item.href } href={ item.href } style={ {
            display: 'block', padding: '13px 16px', textDecoration: 'none',
            borderTop: i === 0 ? 'none' : '1px solid var(--border)',
          } }>
            <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--accent)' } }>{ item.label }</span>
            <span style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginLeft: 8 } }>{ item.note }</span>
          </Link>
        ) ) }
      </div>
    </div>
  </div>
);

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
          { !featureFlags.commerceModule && <ModuleHomeOff /> }
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
