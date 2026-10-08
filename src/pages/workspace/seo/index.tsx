/**
 * SEO Hub — Overview + links to all SEO sub-pages
 * No internal login — matches pattern of [retired public path], /store, [retired public path]
 */
import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; }

const PUBLIC_SITE = 'https://wecare.digital';
const BLOG_PUBLIC_API = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/seo-tools/blog-public`;

const seoPages = [
  //: Listed FIRST because it is the surface that governs publication. Blog Studio uploads the
  //: sources; these five pages are where a source becomes a read source, a QA'd article, a signed
  //: article, a released one, and finally a verified live post. Nothing publishes without passing
  //: through the publish queue by hand.
  { path: '/workspace/seo/blog-production', label: 'Blog Production', desc: 'Production waves: intake, source reading, QA, repetition, publish, verification', icon: '🏭' },
  { path: '/workspace/seo/blog-production/review', label: 'Source review', desc: 'Read a source against its evidence and record that it was read (section 2)', icon: '🔍' },
  { path: '/workspace/seo/blog-production/qa', label: 'QA review', desc: 'Run QA and record the gate sign-off — the only route to READY_TO_PUBLISH', icon: '✅' },
  { path: '/workspace/seo/blog-production/publish', label: 'Publish queue', desc: 'Release, publish and verify. Nothing here happens automatically', icon: '🚀' },
  { path: '/workspace/seo/blog-manager', label: 'Blog SEO Manager', desc: 'Create AWS-native posts; AI audit, approve and apply SEO', icon: '📝' },
  { path: '/workspace/seo/pages-manager', label: 'Site Pages SEO', desc: 'AI SEO for site, system & product pages — Site / System / Products tabs', icon: '📄' },
  { path: '/workspace/seo/tools', label: 'SEO Tools', desc: 'Blog SEO, button audit, live checks, PageSpeed', icon: '🔧' },
  //: Seven tiles went from here on 2026-10-07 with the pages behind them — Pages Inventory,
  //: Issues, Search Analytics, Structured Data, Properties, Sitemaps and Tracking. All seven
  //: read from the `wecare-seo-platform` FastAPI service through `seoFetch`, which threw on
  //: every call because `NEXT_PUBLIC_SEO_API_URL` is not set on `stack`. Owner decision
  //: B1 = CUT retired the backend and the pages together; a tile that navigates to a route
  //: with no page file is a 404, so the tiles could not outlive them.
];

const SEOHub: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
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

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="SEO" description="SEO management hub for wecare.digital" />
      <div className="inner-page">
        <div style={ { marginBottom: 24 } }>
          <h1 className="inner-page-title" style={ { margin: '0 0 4px' } }>SEO</h1>
          <p style={ { fontSize: 13, color: '#6b7280', margin: 0 } }>Manage SEO for wecare.digital — pages, schema, indexing, tools</p>
        </div>

        {/* Live Stats */ }
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 28 } }>
          <StatCard label="Site Status" value={ loading ? '...' : ( liveStats?.status === 'ok' ? '✅ Live' : '❌ Down' ) } />
          <StatCard label="Published Blog Posts" value={ loading ? '...' : liveStats?.blogPosts } />
          <StatCard label="Blog Source" value="AWS" />
          <StatCard label="Public Host" value={ loading ? '...' : liveStats?.publicBase } />
          <StatCard label="Frontend" value="Amplify" />
        </div>

        {/* Sub-pages */ }
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 } }>
          { seoPages.map( p => (
            <button
              key={ p.path }
              onClick={ () => router.push( p.path ) }
              style={ {
                display: 'flex', alignItems: 'center', gap: 14, padding: '16px 20px',
                background: '#fff', border: '1.5px solid #e5e7eb', borderRadius: 13,
                cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit',
                transition: 'all 0.15s', width: '100%',
              } }
              onMouseEnter={ e => { ( e.target as HTMLElement ).style.borderColor = '#d1f470'; } }
              onMouseLeave={ e => { ( e.target as HTMLElement ).style.borderColor = '#e5e7eb'; } }
            >
              <div style={ { fontSize: 24, width: 40, textAlign: 'center', flexShrink: 0 } }>{ p.icon }</div>
              <div style={ { flex: 1 } }>
                <div style={ { fontSize: 15, fontWeight: 600, color: '#1a1a1a' } }>{ p.label }</div>
                <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2 } }>{ p.desc }</div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
            </button>
          ) ) }
        </div>
      </div>
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
