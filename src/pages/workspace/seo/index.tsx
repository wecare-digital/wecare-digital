/**
 * SEO Hub — one page with tabs for the AWS-native SEO surface.
 *
 * Workspace redesign (FEAT-004): the SEO section collapses from a launcher + nine
 * standalone pages to this hub. Tools, Blog SEO (blog-manager) and Site Pages SEO
 * (pages-manager) render here as in-page tabs via their `embedded` prop, so every
 * seoToolsFetch call site inside them is unchanged. The staged blog-production
 * pipeline (waves → source review → QA → publish) and Blog Studio stay as
 * deep-linkable sub-pages reached from the Blog pipeline tab, because they are
 * queue-shaped work that keeps its own URL.
 *
 * This is the AWS-native SeoToolsTable surface (seoToolsFetch), NOT the old Wix SEO:
 * the Wix-era seoFetch pages were retired before the redesign.
 */
import React, { Suspense, useState, useEffect } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PUBLIC_SITE = 'https://wecare.digital';
const BLOG_PUBLIC_API = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/seo-tools/blog-public`;

function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const SEOToolsPage = lazyTab( () => import( './tools' ) );
const BlogManagerPage = lazyTab( () => import( './blog-manager' ) );
const PagesManagerPage = lazyTab( () => import( './pages-manager' ) );

const TABS: ShellTab[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'tools', label: 'Tools' },
  { id: 'blog', label: 'Blog SEO' },
  { id: 'pages', label: 'Site Pages SEO' },
  { id: 'pipeline', label: 'Blog pipeline', divider: true },
];

/** The staged pipeline + studio, kept as their own deep-linkable queue pages. */
const PIPELINE = [
  { path: '/workspace/seo/blog-studio', label: 'Blog Studio', desc: 'Upload sources and draft articles', icon: '🧪' },
  { path: '/workspace/seo/blog-production', label: 'Production waves', desc: 'Intake, source reading, QA, publish, verification', icon: '🏭' },
  { path: '/workspace/seo/blog-production/review', label: 'Source review', desc: 'Read a source against its evidence (section 2)', icon: '🔍' },
  { path: '/workspace/seo/blog-production/qa', label: 'QA review', desc: 'Run QA and record the gate sign-off', icon: '✅' },
  { path: '/workspace/seo/blog-production/publish', label: 'Publish queue', desc: 'Release, publish and verify — nothing automatic', icon: '🚀' },
];

const SEOHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const [ liveStats, setLiveStats ] = useState<any>( null );
  const [ loading, setLoading ] = useState( true );

  useEffect( () => {
    async function fetchLiveStats () {
      try
      {
        const [ siteRes, blogRes ] = await Promise.all( [
          fetch( PUBLIC_SITE, { method: 'GET' } ).catch( () => null ),
          fetch( BLOG_PUBLIC_API ).then( r => r.ok ? r.json() : null ).catch( () => null ),
        ] );
        setLiveStats( {
          status: siteRes?.ok ? 'ok' : 'unknown',
          blogPosts: Array.isArray( blogRes?.posts ) ? blogRes.posts.length : 0,
          publicBase: PUBLIC_SITE.replace( 'https://', '' ),
        } );
      } catch
      {
        setLiveStats( null );
      } finally
      {
        setLoading( false );
      }
    }
    fetchLiveStats();
  }, [] );

  const content = (
    <PageShell
      title="SEO"
      subtitle="AWS-native SEO — tools, blog & site-page optimisation, blog pipeline"
      tabs={ TABS }
      defaultTab="overview"
    >
      { ( activeTab ) => (
        <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
          { activeTab === 'overview' && (
            <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 } }>
              <StatCard label="Site Status" value={ loading ? '...' : ( liveStats?.status === 'ok' ? '✅ Live' : '❌ Down' ) } />
              <StatCard label="Published Blog Posts" value={ loading ? '...' : liveStats?.blogPosts } />
              <StatCard label="Blog Source" value="AWS" />
              <StatCard label="Public Host" value={ loading ? '...' : liveStats?.publicBase } />
              <StatCard label="Frontend" value="Amplify" />
            </div>
          ) }
          { activeTab === 'tools' && <SEOToolsPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'blog' && <BlogManagerPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'pages' && <PagesManagerPage signOut={ signOut } user={ user } embedded /> }
          { activeTab === 'pipeline' && (
            <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 } }>
              { PIPELINE.map( p => (
                <Link
                  key={ p.path }
                  href={ p.path }
                  style={ {
                    display: 'flex', alignItems: 'center', gap: 14, padding: '16px 20px',
                    background: '#fff', border: '1.5px solid #e5e7eb', borderRadius: 13,
                    textDecoration: 'none',
                  } }
                >
                  <div style={ { fontSize: 24, width: 40, textAlign: 'center', flexShrink: 0 } }>{ p.icon }</div>
                  <div style={ { flex: 1 } }>
                    <div style={ { fontSize: 15, fontWeight: 600, color: '#1a1a1a' } }>{ p.label }</div>
                    <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2 } }>{ p.desc }</div>
                  </div>
                </Link>
              ) ) }
            </div>
          ) }
        </Suspense>
      ) }
    </PageShell>
  );

  if ( embedded ) return content;
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="SEO" description="SEO management hub for wecare.digital" />
      { content }
    </Layout>
  );
};

function StatCard ( { label, value }: { label: string; value: any } ) {
  return (
    <div style={ { background: '#fff', border: '1.5px solid #e5e7eb', borderRadius: 13, padding: '16px 20px' } }>
      <div style={ { fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.5px' } }>{ label }</div>
      <div style={ { fontSize: 24, fontWeight: 700, marginTop: 4, color: '#1a3a2a' } }>{ value ?? '—' }</div>
    </div>
  );
}

export default SEOHub;
