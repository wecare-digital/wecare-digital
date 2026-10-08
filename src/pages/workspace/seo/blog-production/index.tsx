/**
 * Blog Production — production waves.
 *
 * WHY EVERY NUMBER ON THIS PAGE IS A ROLLUP AND NOT A COUNTER.
 *
 * `blog_batches` derives every total by reading the source records on each request. There is no
 * `extractedCount` on a batch for this page to render. That is a requirement rather than a
 * preference: a counter and the rows it claims to count drift apart at exactly the moment they
 * have to agree, and a worker that dies between writing a source status and incrementing a batch
 * leaves a wave reading 2,499 of 2,500 forever.
 *
 * `status` is derived here too. The stored value is shown beside it when the two disagree, because
 * a refresh reads the batch index and a global secondary index is eventually consistent - so the
 * refresh that fires immediately after the last source's write can legitimately store a stale
 * INGESTING and never run again. Showing both makes the lag visible instead of papering over it.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import * as seoApi from '../../../../api/seo';
import type { BlogBatchView } from '../../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; }

const STATUS_COLOUR: Record<string, string> = {
  OPEN: '#2563eb',
  INGESTING: '#d97706',
  READY: '#16a34a',
  CLOSED: '#6b7280',
};

const th: React.CSSProperties = { padding: '10px 12px', textAlign: 'left' };
const td: React.CSSProperties = { padding: '10px 12px', verticalAlign: 'top' };

const BlogProductionBatches: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const [ batches, setBatches ] = useState<BlogBatchView[]>( [] );
  const [ categories, setCategories ] = useState<string[]>( [] );
  const [ classes, setClasses ] = useState<string[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ busy, setBusy ] = useState( '' );
  const [ form, setForm ] = useState( { name: '', description: '', defaultCategory: '', articleClass: '' } );

  const load = useCallback( async () => {
    setError( '' );
    try
    {
      const data = await seoApi.listBlogBatches();
      setBatches( data.batches || [] );
      setCategories( data.categories || [] );
      setClasses( data.articleClasses || [] );
      setForm( previous => ( {
        ...previous,
        defaultCategory: previous.defaultCategory || ( data.categories || [] )[ 0 ] || '',
        articleClass: previous.articleClass || ( data.articleClasses || [] )[ 0 ] || '',
      } ) );
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not load batches' );
    } finally
    {
      setLoading( false );
    }
  }, [] );

  useEffect( () => { void load(); }, [ load ] );

  /* The two fetched lists, memoised. Same order, same values, same visible text as the
     <option> rows they replaced; neither had a placeholder row. */
  const categoryOptions: SelectOption[] = useMemo(
    () => categories.map( value => ( { value, label: value } ) ),
    [ categories ]
  );
  const classOptions: SelectOption[] = useMemo(
    () => classes.map( value => ( { value, label: value } ) ),
    [ classes ]
  );

  async function create () {
    setBusy( 'create' );
    setError( '' );
    try
    {
      const created = await seoApi.createBlogBatch( form );
      setForm( previous => ( { ...previous, name: '', description: '' } ) );
      await load();
      void router.push( `/workspace/seo/blog-production/batch/?id=${ encodeURIComponent( created.batchId ) }` );
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not create the batch' );
    } finally
    {
      setBusy( '' );
    }
  }

  async function close ( batchId: string ) {
    setBusy( batchId );
    setError( '' );
    try
    {
      await seoApi.closeBlogBatch( batchId );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not close the batch' );
    } finally
    {
      setBusy( '' );
    }
  }

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Blog Production" description="Production waves for the blog pipeline" />
      <div className="inner-page">
        <h1 className="inner-page-title">Blog Production</h1>
        <p style={ { color: 'rgba(0,0,0,.54)', fontSize: 14, maxWidth: 760 } }>
          A batch holds the sources for one production wave. Every total below is computed from the
          source records on each load, so it cannot disagree with them.
        </p>

        { error && (
          <div role="alert" style={ { background: '#fef2f2', color: '#b91c1c', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 14 } }>
            { error }
          </div>
        ) }

        <div className="card" style={ { marginBottom: 20, padding: 16 } }>
          <h2 style={ { fontSize: 16, margin: '0 0 12px' } }>New wave</h2>
          <div style={ { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' } }>
            <label style={ { display: 'flex', flexDirection: 'column', fontSize: 13, gap: 4 } }>
              Name
              <input value={ form.name } onChange={ event => setForm( { ...form, name: event.target.value } ) }
                style={ { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, minWidth: 240 } } />
            </label>
            { /* SHAPE (a), design 5.2 - the two wrapping <label>s are gone and Select owns the
                 pair. The wrapper was a column flex with a 4px gap and nothing else, which is
                 exactly what `.ui-field` plus `.ui-field-label` already render, so nothing had
                 to be reproduced in `style` here. */ }
            <Select label="Category" value={ form.defaultCategory }
              onChange={ v => setForm( { ...form, defaultCategory: v } ) }
              options={ categoryOptions } />
            <Select label="Article class" value={ form.articleClass }
              onChange={ v => setForm( { ...form, articleClass: v } ) }
              options={ classOptions } />
            <label style={ { display: 'flex', flexDirection: 'column', fontSize: 13, gap: 4, flex: 1, minWidth: 220 } }>
              Description
              <input value={ form.description } onChange={ event => setForm( { ...form, description: event.target.value } ) }
                style={ { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 } } />
            </label>
            <button onClick={ () => { void create(); } } disabled={ !form.name.trim() || busy === 'create' }
              style={ { padding: '9px 18px', borderRadius: 6, border: 'none', background: '#1a3a2a', color: '#fff', cursor: 'pointer', fontSize: 14 } }>
              { busy === 'create' ? 'Creating…' : 'Create wave' }
            </button>
          </div>
        </div>

        <div className="card" style={ { overflow: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
            <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 13, color: '#6b7280' } }>
              Production waves, newest first
            </caption>
            <thead>
              <tr style={ { borderBottom: '2px solid #e5e7eb' } }>
                <th scope="col" style={ th }>Wave</th>
                <th scope="col" style={ th }>Status</th>
                <th scope="col" style={ th }>Sources</th>
                <th scope="col" style={ th }>Extracted</th>
                <th scope="col" style={ th }>Pending</th>
                <th scope="col" style={ th }>Failed</th>
                <th scope="col" style={ th }>Words</th>
                <th scope="col" style={ th }>Actions</th>
              </tr>
            </thead>
            <tbody>
              { batches.map( batch => {
                const rollup = batch.rollup;
                const lagging = batch.storedStatus && batch.storedStatus !== batch.status;
                return (
                  <tr key={ batch.batchId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                    <td style={ td }>
                      <a href={ `/workspace/seo/blog-production/batch/?id=${ encodeURIComponent( batch.batchId ) }` }
                        style={ { color: '#1a3a2a', fontWeight: 600 } }>{ batch.name }</a>
                      <div style={ { color: '#6b7280', fontSize: 11 } }>
                        { batch.defaultCategory } · { batch.articleClass }
                      </div>
                      { batch.description && (
                        <div style={ { color: '#9ca3af', fontSize: 11 } }>{ batch.description }</div>
                      ) }
                    </td>
                    <td style={ { ...td, color: STATUS_COLOUR[ batch.status ] || '#374151', fontWeight: 600 } }>
                      { batch.status }
                      { /* Shown only when the cached value has fallen behind the derived one. */ }
                      { lagging && (
                        <div style={ { color: '#9ca3af', fontWeight: 400, fontSize: 11 } }>
                          cached: { batch.storedStatus }
                        </div>
                      ) }
                    </td>
                    <td style={ td }>{ rollup ? rollup.sources : '—' }</td>
                    <td style={ td }>{ rollup ? rollup.extracted : '—' }</td>
                    <td style={ td }>{ rollup ? rollup.pending : '—' }</td>
                    <td style={ { ...td, color: rollup && rollup.failed ? '#b91c1c' : '#374151' } }>
                      { rollup ? rollup.failed : '—' }
                    </td>
                    <td style={ td }>{ rollup ? rollup.words.toLocaleString() : '—' }</td>
                    <td style={ td }>
                      <a href={ `/workspace/seo/blog-production/batch/?id=${ encodeURIComponent( batch.batchId ) }` }
                        style={ { color: '#1a3a2a', marginRight: 12 } }>Open</a>
                      { batch.status !== 'CLOSED' && (
                        <button onClick={ () => { void close( batch.batchId ); } } disabled={ busy === batch.batchId }
                          aria-label={ `Close the wave ${ batch.name }` }
                          style={ { color: '#6b7280', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, padding: 0 } }>
                          { busy === batch.batchId ? 'Closing…' : 'Close' }
                        </button>
                      ) }
                    </td>
                  </tr>
                );
              } ) }
              { batches.length === 0 && !loading && (
                <tr><td colSpan={ 8 } style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>
                  No waves yet. Create one above, then upload sources in Blog Studio.
                </td></tr>
              ) }
              { loading && (
                <tr><td colSpan={ 8 } style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>Loading…</td></tr>
              ) }
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
};

export default BlogProductionBatches;
