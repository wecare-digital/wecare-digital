/**
 * Native blog browser.
 *
 * Editorial auditing and rewriting are handled outside the Workspace. This surface only
 * lists the published native posts so operators can locate and open them.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { seoToolsFetch } from '../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface BlogPost {
  id: string;
  title: string;
  slug: string;
  category: string;
  url: string;
  publishedDate: string;
  modifiedDate: string;
  seoTitle: string;
}

const BlogManager: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const [ posts, setPosts ] = useState<BlogPost[]>( [] );
  const [ search, setSearch ] = useState( '' );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );

  const load = useCallback( async () => {
    setLoading( true );
    setError( '' );
    try {
      const response = await seoToolsFetch( 'blog-posts' );
      const data = await response.json();
      if ( !data.ok ) throw new Error( data.error || 'Could not load posts' );
      setPosts( data.posts || [] );
    } catch ( cause ) {
      setError( cause instanceof Error ? cause.message : 'Could not load posts' );
    } finally {
      setLoading( false );
    }
  }, [] );

  useEffect( () => { void load(); }, [ load ] );

  const filtered = useMemo( () => {
    const q = search.trim().toLowerCase();
    if ( !q ) return posts;
    return posts.filter( post =>
      post.title?.toLowerCase().includes( q )
      || post.slug?.toLowerCase().includes( q )
      || post.category?.toLowerCase().includes( q )
      || post.seoTitle?.toLowerCase().includes( q ) );
  }, [ posts, search ] );

  const body = (
    <div className="inner-page" style={ { maxWidth: 1200 } }>
      <div style={ { display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'end', flexWrap: 'wrap' } }>
        <div>
          <h2 style={ { margin: 0 } }>Blog</h2>
          <p style={ { margin: '6px 0 0', color: 'var(--text-muted)' } }>
            Published native posts. Editorial audits and revisions are handled separately.
          </p>
        </div>
        <input
          aria-label="Search blog posts"
          value={ search }
          onChange={ event => setSearch( event.target.value ) }
          placeholder="Search title, slug or category"
          style={ { minWidth: 280, maxWidth: '100%' } }
        />
      </div>

      { loading && <p style={ { color: 'var(--text-muted)' } }>Loading posts…</p> }
      { error && <div role="alert" style={ { color: '#b91c1c', marginTop: 16 } }>{ error }</div> }

      { !loading && !error && (
        <div style={ { marginTop: 18, overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
            <thead>
              <tr style={ { borderBottom: '2px solid var(--border)' } }>
                <th style={ { padding: 10, textAlign: 'left' } }>Title</th>
                <th style={ { padding: 10, textAlign: 'left' } }>Category</th>
                <th style={ { padding: 10, textAlign: 'left' } }>Modified</th>
                <th style={ { padding: 10, textAlign: 'left' } }></th>
              </tr>
            </thead>
            <tbody>
              { filtered.map( post => (
                <tr key={ post.id || post.slug } style={ { borderBottom: '1px solid var(--border)' } }>
                  <td style={ { padding: 10 } }>
                    <strong>{ post.title }</strong>
                    <div style={ { color: 'var(--text-muted)', fontSize: 'var(--text-xs)', overflowWrap: 'anywhere' } }>
                      { post.slug }
                    </div>
                  </td>
                  <td style={ { padding: 10 } }>{ post.category }</td>
                  <td style={ { padding: 10 } }>{ post.modifiedDate || post.publishedDate || '—' }</td>
                  <td style={ { padding: 10 } }>
                    <a href={ post.url || `/post/${ post.slug }/` } target="_blank" rel="noopener noreferrer">
                      Open
                    </a>
                  </td>
                </tr>
              ) ) }
            </tbody>
          </table>
          <p style={ { color: 'var(--text-muted)', fontSize: 'var(--text-xs)' } }>
            Showing { filtered.length } of { posts.length } posts.
          </p>
        </div>
      ) }
    </div>
  );

  if ( embedded ) return body;
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Blog" description="Published native blog posts" />
      { body }
    </Layout>
  );
};

export default BlogManager;
