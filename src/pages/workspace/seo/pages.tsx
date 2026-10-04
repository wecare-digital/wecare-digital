/**
 * SEO Pages Inventory — list all crawled pages with filters
 */
import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import * as seoApi from '../../../api/seo';
import { useToastContext } from '../../../contexts/ToastContext';

interface PageProps { signOut?: () => void; user?: any; }

const SEOPages: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const toast = useToastContext();
  const [ pages, setPages ] = useState<any[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ domain, setDomain ] = useState( '' );
  const [ search, setSearch ] = useState( '' );
  const [ pageType, setPageType ] = useState( '' );

  useEffect( () => {
    loadPages();
  }, [ domain, search, pageType ] );

  async function loadPages () {
    setLoading( true );
    try
    {
      const params: Record<string, string> = {};
      if ( domain ) params.site_domain = domain;
      if ( search ) params.search = search;
      if ( pageType ) params.page_type = pageType;
      const data = await seoApi.listPages( params );
      setPages( data );
    } catch ( e )
    {
      console.error( e );
    } finally
    {
      setLoading( false );
    }
  }

  async function handleCrawl ( site: string ) {
    try
    {
      await seoApi.triggerCrawl( site );
      toast.success( `Crawl started for ${site}` );
    } catch ( e: any )
    {
      toast.error( e.message || 'Crawl failed' );
    }
  }

  const PAGE_TYPES = [
    'homepage', 'core_site', 'brand', 'brand_store', 'function_customer_service',
    'blog_hub', 'blog_post', 'product', 'legal_compliance', 'contact_support',
    'app_download', 'stack', 'unknown'
  ];

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="SEO Pages" description="Page inventory for wecare.digital" />
      <div className="inner-page">
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 } }>
          <h1 className="inner-page-title" style={ { margin: 0 } }>Pages Inventory</h1>
          <div style={ { display: 'flex', gap: 8 } }>
            <button className="btn btn-primary" onClick={ () => handleCrawl( 'wecare.digital' ) }>Crawl Site</button>
          </div>
        </div>

        <div style={ { display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' } }>
          <select value={ domain } onChange={ e => setDomain( e.target.value ) } className="input" style={ { width: 200 } }>
            <option value="">All domains</option>
            <option value="wecare.digital">wecare.digital</option>
            <option value="www.wecare.digital">www.wecare.digital (legacy)</option>
          </select>
          <select value={ pageType } onChange={ e => setPageType( e.target.value ) } className="input" style={ { width: 200 } }>
            <option value="">All types</option>
            { PAGE_TYPES.map( t => <option key={ t } value={ t }>{ t }</option> ) }
          </select>
          <input placeholder="Search URL or title..." value={ search } onChange={ e => setSearch( e.target.value ) }
            className="input" style={ { flex: 1, minWidth: 200 } } />
          <button className="btn btn-secondary" onClick={ loadPages }>Search</button>
        </div>

        { loading ? (
          <div className="card" style={ { textAlign: 'center', padding: 40, color: '#6b7280' } }>Loading pages...</div>
        ) : (
          <div className="card" style={ { overflow: 'auto' } }>
            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
              <thead>
                <tr style={ { borderBottom: '2px solid #e5e7eb', textAlign: 'left' } }>
                  <th style={ { padding: '10px 12px' } }>URL</th>
                  <th style={ { padding: '10px 12px' } }>Type</th>
                  <th style={ { padding: '10px 12px' } }>HTTP</th>
                  <th style={ { padding: '10px 12px' } }>Title</th>
                  <th style={ { padding: '10px 12px' } }>Domain</th>
                </tr>
              </thead>
              <tbody>
                { /* Rows link with ?id= rather than a path segment: the detail view is one
                     static file, so the link survives a reload. See page/index.tsx. */ }
                { pages.map( p => (
                  <tr key={ p.id } style={ { borderBottom: '1px solid #f3f4f6', cursor: 'pointer' } }
                    onClick={ () => router.push( `/workspace/seo/page/?id=${p.id}` ) }>
                    <td style={ { padding: '10px 12px', color: '#1a3a2a', fontWeight: 500, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>
                      { p.normalized_url }
                    </td>
                    <td style={ { padding: '10px 12px' } }>
                      <span style={ { background: '#f0fdf4', color: '#166534', padding: '2px 8px', borderRadius: 6, fontSize: 12 } }>{ p.page_type }</span>
                    </td>
                    <td style={ { padding: '10px 12px', color: p.http_status >= 400 ? '#dc2626' : '#1a3a2a' } }>{ p.http_status || '—' }</td>
                    <td style={ { padding: '10px 12px', maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ p.title || '—' }</td>
                    <td style={ { padding: '10px 12px', fontSize: 12, color: '#6b7280' } }>{ p.site_domain }</td>
                  </tr>
                ) ) }
                { pages.length === 0 && (
                  <tr><td colSpan={ 5 } style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>No pages found. Run a crawl first.</td></tr>
                ) }
              </tbody>
            </table>
          </div>
        ) }
        <div style={ { marginTop: 8, fontSize: 13, color: '#6b7280' } }>{ pages.length } pages</div>
      </div>
    </Layout>
  );
};

export default SEOPages;
