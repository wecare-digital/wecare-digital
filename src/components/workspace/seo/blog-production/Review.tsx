/**
 * Blog Production — source review. The page where section 2 is either honoured or ticked.
 *
 * WHAT MAKES THIS PAGE DIFFERENT FROM A CHECKBOX.
 *
 * `sourceReviewedFully` used to be a single boolean, and a boolean records that a click happened
 * rather than what was read. So the reviewer is given EVIDENCE first: which paragraphs are written
 * in the source author's first person, which sentences carry a checkable quantity or touch a
 * section 20 factual domain, which quotations have no attribution near them, which named
 * individuals create a privacy obligation, and which dates, prices and calls-to-action are the
 * obsolete wrapper section 3 wants removed. All of it derived mechanically from the extracted text,
 * so it is reproducible and is not a claim about quality.
 *
 * Three things the form insists on, each of them a refusal rather than a warning:
 *
 *   - the reviewer names the ANALYSIS VERSION they read, so a re-analysis produced while they were
 *     reading cannot become the thing they signed for;
 *   - a YES names the central distinction the source makes available, because a YES with no
 *     distinction is the shape of a tick-box;
 *   - the source text must not have changed since the analysis was produced.
 *
 * Recording the reading releases section 2 and nothing else. The eleven section 29 gates and the
 * section 30 read are a separate act on the QA page.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import * as seoApi from '../../../../api/seo';
import type {
  BlogAnalysisDetail, BlogAnalysisView, BlogSourceDetail, BlogSourceView,
} from '../../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const td: React.CSSProperties = { padding: '8px 10px', verticalAlign: 'top' };
const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left' };
const field: React.CSSProperties = {
  padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, width: '100%',
  fontFamily: 'inherit', fontSize: 'var(--text-sm)',
};

function Evidence ( { title, count, note, children }: {
  title: string; count: number; note: string; children?: React.ReactNode;
} ) {
  return (
    <div style={ { marginBottom: 14 } }>
      <h3 style={ { fontSize: 'var(--text-sm)', margin: '0 0 2px' } }>
        { title } <span style={ { color: count ? '#d97706' : '#16a34a' } }>({ count })</span>
      </h3>
      <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 6px' } }>{ note }</p>
      { children }
    </div>
  );
}

const BlogSourceReview: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const router = useRouter();
  const sourceId = typeof router.query.source === 'string' ? router.query.source : '';
  const batchId = typeof router.query.batch === 'string' ? router.query.batch : '';

  const [ queue, setQueue ] = useState<BlogSourceView[]>( [] );
  const [ source, setSource ] = useState<BlogSourceDetail | null>( null );
  const [ analysis, setAnalysis ] = useState<BlogAnalysisDetail | null>( null );
  const [ history, setHistory ] = useState<BlogAnalysisView[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ busy, setBusy ] = useState( '' );
  const [ form, setForm ] = useState( {
    centralDistinctionCandidate: '', wrapperToRemove: '', reviewNotes: '',
    originalSourceDate: '', originalSourceTitle: '',
  } );

  const load = useCallback( async () => {
    setError( '' );
    try
    {
      if ( batchId && !sourceId )
      {
        const listing = await seoApi.listBlogSourcesInBatch( batchId );
        setQueue( listing.sources || [] );
        setSource( null );
        setAnalysis( null );
        return;
      }
      if ( !sourceId ) return;
      const [ detail, analyses ] = await Promise.all( [
        seoApi.getBlogSource( sourceId ),
        seoApi.listBlogAnalyses( sourceId ),
      ] );
      setSource( detail.source );
      setHistory( analyses.history || [] );
      const current = ( analyses.history || [] )[ 0 ];
      if ( current )
      {
        const full = await seoApi.getBlogAnalysis( current.analysisId );
        setAnalysis( full.analysis );
      } else
      {
        setAnalysis( null );
      }
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not load this source' );
    } finally
    {
      setLoading( false );
    }
  }, [ sourceId, batchId ] );

  useEffect( () => { void load(); }, [ load ] );

  async function analyse () {
    setBusy( 'analyse' );
    setError( '' );
    setNotice( '' );
    try
    {
      await seoApi.analyseBlogSource( sourceId );
      await load();
      setNotice( 'A new analysis version was produced. Read it before recording anything: a new '
        + 'version does not carry a previous reading forward.' );
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not analyse this source' );
    } finally
    {
      setBusy( '' );
    }
  }

  async function record ( answer: 'YES' | 'NO' ) {
    if ( !analysis ) return;
    setBusy( answer );
    setError( '' );
    setNotice( '' );
    try
    {
      const result = await seoApi.recordBlogSourceReview( {
        analysisId: analysis.analysisId,
        sourceReviewedFully: answer,
        ...form,
      } );
      setNotice( result.note || 'Recorded.' );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not record the reading' );
    } finally
    {
      setBusy( '' );
    }
  }

  const evidence = analysis?.evidence;

  const body = (
      <div className="inner-page">
        <p style={ { fontSize: 'var(--text-sm)', margin: '0 0 8px' } }>
          <Link href="/workspace/seo/blog-production" style={ { color: 'var(--accent)' } }>← Production waves</Link>
          { batchId && (
            <>
              { ' · ' }
              <a href={ `/workspace/seo/blog-production?tab=batch&id=${ encodeURIComponent( batchId ) }` }
                style={ { color: 'var(--accent)' } }>This wave</a>
            </>
          ) }
        </p>
        <h1 className="inner-page-title">Source review</h1>

        { error && (
          <div role="alert" style={ { background: '#fef2f2', color: '#b91c1c', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 'var(--text-md)' } }>
            { error }
          </div>
        ) }
        { notice && (
          <div role="status" style={ { background: '#f0fdf4', color: '#15803d', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 'var(--text-md)' } }>
            { notice }
          </div>
        ) }
        { loading && <p style={ { color: 'var(--text-muted)' } }>Loading…</p> }

        { !sourceId && (
          <div className="card" style={ { overflow: 'auto' } }>
            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
              <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>
                { batchId ? 'Sources in this wave' : 'Name a source in the URL, or open one from a wave.' }
              </caption>
              <thead>
                <tr style={ { borderBottom: '2px solid var(--border)' } }>
                  <th scope="col" style={ th }>Source</th>
                  <th scope="col" style={ th }>Intake</th>
                  <th scope="col" style={ th }>Read</th>
                  <th scope="col" style={ th }>Article</th>
                  <th scope="col" style={ th }></th>
                </tr>
              </thead>
              <tbody>
                { queue.map( row => (
                  <tr key={ row.sourceId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                    <td style={ td }>{ row.sourceRef }</td>
                    <td style={ td }>{ row.status }</td>
                    <td style={ { ...td, color: row.pipeline.sourceReviewedFully === 'YES' ? '#16a34a' : '#d97706' } }>
                      { row.pipeline.sourceReviewedFully || 'not read' }
                    </td>
                    <td style={ td }>{ row.articleStatus || '—' }</td>
                    <td style={ td }>
                      <a href={ `/workspace/seo/blog-production?tab=review&source=${ encodeURIComponent( row.sourceId ) }&batch=${ encodeURIComponent( batchId ) }` }
                        style={ { color: 'var(--accent)' } }>Review</a>
                    </td>
                  </tr>
                ) ) }
                { queue.length === 0 && !loading && (
                  <tr><td colSpan={ 5 } style={ { padding: 32, textAlign: 'center', color: 'var(--text-muted)' } }>
                    Nothing to review here.
                  </td></tr>
                ) }
              </tbody>
            </table>
          </div>
        ) }

        { source && (
          <>
            <div className="card" style={ { padding: 16, marginBottom: 16 } }>
              <h2 style={ { fontSize: 'var(--text-md)', margin: '0 0 8px' } }>{ source.sourceRef }</h2>
              <p style={ { fontSize: 'var(--text-sm)', color: 'rgba(0,0,0,.54)', margin: 0 } }>
                { source.status } · { source.category } · { source.articleClass }
                { source.extractedWords ? ` · ${ source.extractedWords } words extracted` : '' }
              </p>
              { source.sourceUrl && (
                <p style={ { fontSize: 'var(--text-sm)', margin: '8px 0 0' } }>
                  <a href={ source.sourceUrl } target="_blank" rel="noopener noreferrer"
                    style={ { color: 'var(--accent)' } }>
                    Open the source document
                  </a>
                  <span style={ { color: 'var(--text-muted)' } }> — section 2 is about having read this.</span>
                </p>
              ) }
              <div style={ { marginTop: 12 } }>
                <button onClick={ () => { void analyse(); } } disabled={ busy === 'analyse' }
                  style={ { padding: '7px 14px', borderRadius: 6, border: '1px solid var(--accent)', background: '#fff', color: 'var(--accent)', cursor: 'pointer', fontSize: 'var(--text-sm)' } }>
                  { busy === 'analyse' ? 'Analysing…' : analysis ? 'Re-analyse' : 'Analyse this source' }
                </button>
                { history.length > 0 && (
                  <span style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: 12 } }>
                    { history.length } version{ history.length === 1 ? '' : 's' }; reading version{ ' ' }
                    { analysis?.version }
                  </span>
                ) }
              </div>
            </div>

            { source.extractPreview && (
              <details className="card" style={ { padding: 16, marginBottom: 16 } }>
                <summary style={ { cursor: 'pointer', fontSize: 'var(--text-md)', fontWeight: 600 } }>
                  Extracted text
                </summary>
                <pre style={ { whiteSpace: 'pre-wrap', fontSize: 'var(--text-xs)', lineHeight: 1.6, marginTop: 12, color: '#374151' } }>
                  { source.sourceExtract || source.extractPreview }
                </pre>
              </details>
            ) }

            { evidence && (
              <div className="card" style={ { padding: 16, marginBottom: 16 } }>
                <h2 style={ { fontSize: 'var(--text-md)', margin: '0 0 4px' } }>Evidence</h2>
                <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 14px', maxWidth: 680 } }>
                  Derived mechanically from the extracted text, so it is reproducible. None of it is
                  a judgement of quality — that is what you are here to make.
                </p>
                <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 16, fontSize: 'var(--text-xs)', color: 'rgba(0,0,0,.54)' } }>
                  <span>{ evidence.words.toLocaleString() } words</span>
                  <span>{ evidence.paragraphs } paragraphs</span>
                  <span>{ evidence.sentences } sentences</span>
                  <span>mean sentence { evidence.meanSentenceWords } words</span>
                </div>

                <Evidence title="First-person passages" count={ evidence.firstPersonPassages.length }
                  note="Section 18: a first-person story in the source must not survive as Anew's own biography. Remove, generalise or attribute each one.">
                  { evidence.firstPersonPassages.slice( 0, 6 ).map( passage => (
                    <p key={ passage.paragraph } style={ { fontSize: 'var(--text-xs)', background: '#fffbeb', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px' } }>
                      ¶{ passage.paragraph } ({ passage.markers } markers): { passage.text }
                    </p>
                  ) ) }
                </Evidence>

                <Evidence title="Checkable claims" count={ evidence.checkableClaims.length }
                  note="Section 20: a domain claim may not sit behind an N/A review. A flag here means the QA sign-off will require that review as an explicit YES.">
                  { evidence.checkableClaims.slice( 0, 6 ).map( claim => (
                    <p key={ claim.sentence } style={ { fontSize: 'var(--text-xs)', background: '#eff6ff', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px' } }>
                      { claim.reviewFlags.join( ', ' ) || 'quantity' }: { claim.text }
                    </p>
                  ) ) }
                </Evidence>

                <Evidence title="Quotations" count={ evidence.quotations.length }
                  note={ `Section 19: a quotation keeps its attribution through reconstruction. ${ evidence.unattributedQuotations } have no attribution nearby.` }>
                  { evidence.quotations.slice( 0, 5 ).map( ( quotation, index ) => (
                    <p key={ index } style={ { fontSize: 'var(--text-xs)', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px', background: quotation.attributionNearby ? '#f0fdf4' : '#fef2f2' } }>
                      { quotation.attributionNearby ? 'attributed' : 'no attribution nearby' }: “{ quotation.text }”
                    </p>
                  ) ) }
                </Evidence>

                <Evidence title="Named individuals" count={ evidence.namedIndividuals.length }
                  note="Section 19 privacy. Over-reported on purpose: a missed obligation is a disclosure, an over-report is a glance at a list.">
                  <p style={ { fontSize: 'var(--text-xs)', color: 'rgba(0,0,0,.54)', margin: 0 } }>
                    { evidence.namedIndividuals.slice( 0, 20 ).join( ' · ' ) || 'none' }
                  </p>
                </Evidence>

                <Evidence title="Obsolete wrapper" count={ evidence.obsoleteMarkers.length }
                  note="Section 3: a workshop date, a price, a phone number, a dead platform. Each is something the reconstruction has to deal with.">
                  { evidence.obsoleteMarkers.map( marker => (
                    <p key={ marker.kind } style={ { fontSize: 'var(--text-xs)', background: '#fffbeb', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px' } }>
                      <strong>{ marker.kind }</strong>: { marker.text }
                    </p>
                  ) ) }
                </Evidence>
              </div>
            ) }

            { analysis && (
              <div className="card" style={ { padding: 16 } }>
                <h2 style={ { fontSize: 'var(--text-md)', margin: '0 0 4px' } }>
                  Record the reading — version { analysis.version }
                </h2>
                <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 14px', maxWidth: 680 } }>
                  This is the only place <code>sourceReviewedFully</code> is written, and it is
                  recorded against this exact analysis version. It releases section 2 and nothing
                  else — the eleven section 29 gates are a separate act on the QA page.
                </p>
                { analysis.sourceReviewedFully && (
                  <p style={ { fontSize: 'var(--text-sm)', color: analysis.sourceReviewedFully === 'YES' ? '#15803d' : '#b45309', margin: '0 0 12px' } }>
                    Already recorded as <strong>{ analysis.sourceReviewedFully }</strong> by{ ' ' }
                    { analysis.reviewedBy } at { analysis.reviewedAt }.
                  </p>
                ) }
                <div style={ { display: 'grid', gap: 12, maxWidth: 780 } }>
                  <label style={ { fontSize: 'var(--text-sm)' } }>
                    Central distinction the source makes available
                    <span style={ { color: 'var(--text-muted)' } }> — required for a YES, at least 40 characters</span>
                    <textarea rows={ 3 } style={ { ...field, marginTop: 4 } }
                      value={ form.centralDistinctionCandidate }
                      onChange={ event => setForm( { ...form, centralDistinctionCandidate: event.target.value } ) } />
                  </label>
                  <label style={ { fontSize: 'var(--text-sm)' } }>
                    Wrapper to remove
                    <textarea rows={ 2 } style={ { ...field, marginTop: 4 } }
                      value={ form.wrapperToRemove }
                      onChange={ event => setForm( { ...form, wrapperToRemove: event.target.value } ) } />
                  </label>
                  <div style={ { display: 'flex', gap: 12, flexWrap: 'wrap' } }>
                    <label style={ { fontSize: 'var(--text-sm)', flex: 1, minWidth: 180 } }>
                      Original source date
                      <span style={ { color: 'var(--text-muted)' } }> — fills a gap only</span>
                      <input style={ { ...field, marginTop: 4 } } value={ form.originalSourceDate }
                        onChange={ event => setForm( { ...form, originalSourceDate: event.target.value } ) } />
                    </label>
                    <label style={ { fontSize: 'var(--text-sm)', flex: 1, minWidth: 180 } }>
                      Original source title
                      <input style={ { ...field, marginTop: 4 } } value={ form.originalSourceTitle }
                        onChange={ event => setForm( { ...form, originalSourceTitle: event.target.value } ) } />
                    </label>
                  </div>
                  <label style={ { fontSize: 'var(--text-sm)' } }>
                    Notes
                    <textarea rows={ 2 } style={ { ...field, marginTop: 4 } } value={ form.reviewNotes }
                      onChange={ event => setForm( { ...form, reviewNotes: event.target.value } ) } />
                  </label>
                  <div style={ { display: 'flex', gap: 12 } }>
                    <button onClick={ () => { void record( 'YES' ); } } disabled={ busy !== '' }
                      style={ { padding: '9px 18px', borderRadius: 6, border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: 'var(--text-md)' } }>
                      { busy === 'YES' ? 'Recording…' : 'I have read this source' }
                    </button>
                    <button onClick={ () => { void record( 'NO' ); } } disabled={ busy !== '' }
                      style={ { padding: '9px 18px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', color: '#374151', cursor: 'pointer', fontSize: 'var(--text-md)' } }>
                      { busy === 'NO' ? 'Recording…' : 'Not usable' }
                    </button>
                  </div>
                </div>
              </div>
            ) }

            { sourceId && !analysis && !loading && (
              <div className="card" style={ { padding: 16, color: 'var(--text-muted)', fontSize: 'var(--text-sm)' } }>
                No analysis yet. Produce one first — an analysis of nothing is exactly the artifact
                this step exists to prevent.
              </div>
            ) }
          </>
        ) }
      </div>
  );

  if ( embedded ) return body;
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Source review — Blog Production"
        description="Read the source and record that it was read" />
      { body }
    </Layout>
  );
};

export default BlogSourceReview;
