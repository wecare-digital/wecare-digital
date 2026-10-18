/**
 * SEO Hub — one page with tabs for the AWS-native SEO surface.
 *
 * Workspace redesign (FEAT-004): the SEO section collapses from a launcher + nine
 * standalone pages to this hub. Tools, Blog SEO (blog-manager) and Site Pages SEO
 * (pages-manager) render here as in-page tabs via their `embedded` prop, so every
 * seoToolsFetch call site inside them is unchanged. The staged blog-production
 * pipeline (waves → wave detail → source review → QA → publish) folded (FEAT-006)
 * into one /workspace/seo/blog-production hub with step tabs, reached from the Blog
 * pipeline tab; Blog Studio stays as its own SSG sub-page.
 *
 * This is the AWS-native SeoToolsTable surface (seoToolsFetch), NOT the old Wix SEO:
 * the Wix-era seoFetch pages were retired before the redesign.
 */
import React, { Suspense, useState, useEffect } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PUBLIC_SITE = 'https://wecare.digital';
const BLOG_PUBLIC_API = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/seo-tools/blog-public`;

function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

// FEAT-005: the Tools/Blog SEO/Site Pages SEO tab bodies moved OUT of src/pages/workspace/seo/**
// into src/components/workspace/seo/** so each stops being its own route. Every seoToolsFetch
// call inside them is unchanged.
const SEOToolsPage = lazyTab( () => import( '../../../components/workspace/seo/Tools' ) );
const BlogManagerPage = lazyTab( () => import( '../../../components/workspace/seo/BlogManager' ) );
const PagesManagerPage = lazyTab( () => import( '../../../components/workspace/seo/PagesManager' ) );

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
  // FEAT-006: the staged pipeline folded into one hub with step tabs; each stage is a
  // ?tab= deep-link on /workspace/seo/blog-production.
  { path: '/workspace/seo/blog-production?tab=review', label: 'Source review', desc: 'Read a source against its evidence (section 2)', icon: '🔍' },
  { path: '/workspace/seo/blog-production?tab=qa', label: 'QA review', desc: 'Run QA and record the gate sign-off', icon: '✅' },
  { path: '/workspace/seo/blog-production?tab=publish', label: 'Publish queue', desc: 'Release, publish and verify — nothing automatic', icon: '🚀' },
];

// FEAT-005: /workspace/seo?tab=<id> deep-links open the matching tab.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
  const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
  return id && TABS.some( ( t ) => t.id === id ) ? id : 'overview';
}

const SEOHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const router = useRouter();
  const defaultTab = resolveDefaultTab( router.query.tab );
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
      key={ defaultTab }
      title="SEO"
      subtitle="AWS-native SEO — tools, blog & site-page optimisation, blog pipeline"
      tabs={ TABS }
      defaultTab={ defaultTab }
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
                    background: 'var(--surface)', border: '1.5px solid var(--border)', borderRadius: 13,
                    textDecoration: 'none',
                  } }
                >
                  <div style={ { fontSize: 'var(--text-3xl)', width: 40, textAlign: 'center', flexShrink: 0 } }>{ p.icon }</div>
                  <div style={ { flex: 1 } }>
                    <div style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text)' } }>{ p.label }</div>
                    <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 } }>{ p.desc }</div>
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
    <div style={ { background: 'var(--surface)', border: '1.5px solid var(--border)', borderRadius: 13, padding: '16px 20px' } }>
      <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' } }>{ label }</div>
      <div style={ { fontSize: 'var(--text-3xl)', fontWeight: 700, marginTop: 4, color: 'var(--accent)' } }>{ value ?? '—' }</div>
    </div>
  );
}

export default SEOHub;
