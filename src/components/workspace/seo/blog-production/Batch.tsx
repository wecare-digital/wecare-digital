/**
 * Blog Production — one wave, with every stage's state beside the sources.
 *
 * WHY THE ID IS A QUERY STRING. The site is a static export, so a dynamic segment with no
 * `getStaticPaths` emits one file literally named `[id]` - a real HTTP 200 that renders with
 * `id === '[id]'`, and nothing at all at the URL an operator would reload. `page/index.tsx`
 * records that defect in full; this follows the fix rather than repeating the mistake.
 *
 * WHAT THIS PAGE IS FOR. Six independent questions are asked about a wave, and a dashboard that
 * merged them would hide which half of the work remains:
 *
 *   intake       did the bytes arrive and did extraction work
 *   reading      has a person actually read each source (section 2)
 *   QA           has each article been run against the rules, and signed off
 *   repetition   does the COLLECTION read as generated, even where no two articles overlap
 *   publish      what has been released, published, refused
 *   verification what does the live post actually say
 *
 * Every number is derived from the records on each load. None of them is a stored counter.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import * as seoApi from '../../../../api/seo';
import type {
  BlogBatchDetail, BlogBatchReviewState, BlogPublishResponse, BlogQaResponse,
  BlogRepetitionRunView, BlogVerifyResponse,
} from '../../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left' };
const td: React.CSSProperties = { padding: '8px 10px', verticalAlign: 'top' };

const SOURCE_COLOUR: Record<string, string> = {
  PENDING_UPLOAD: '#9ca3af',
  UPLOADED: '#2563eb',
  EXTRACTING: '#d97706',
  EXTRACTED: '#16a34a',
  EXTRACTION_FAILED: '#b91c1c',
};

function Stat ( { label, value, tone }: { label: string; value: React.ReactNode; tone?: string } ) {
  return (
    <div style={ { minWidth: 110 } }>
      <div style={ { fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 0.4 } }>{ label }</div>
      <div style={ { fontSize: 20, fontWeight: 700, color: tone || '#1a1a1a' } }>{ value }</div>
    </div>
  );
}

function Panel ( { title, subtitle, children, action }: {
  title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode;
} ) {
  return (
    <section className="card" style={ { padding: 16, marginBottom: 16 } }>
      <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 } }>
        <div>
          <h2 style={ { fontSize: 15, margin: 0 } }>{ title }</h2>
          { subtitle && <p style={ { fontSize: 12, color: '#6b7280', margin: '4px 0 0', maxWidth: 620 } }>{ subtitle }</p> }
        </div>
        { action }
      </div>
      { children }
    </section>
  );
}

const BlogProductionBatch: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const router = useRouter();
  const batchId = typeof router.query.id === 'string' ? router.query.id : '';

  const [ batch, setBatch ] = useState<BlogBatchDetail | null>( null );
  const [ review, setReview ] = useState<BlogBatchReviewState | null>( null );
  const [ qa, setQa ] = useState<BlogQaResponse | null>( null );
  const [ repetition, setRepetition ] = useState<{ implicated: number; clear: number; unchecked: number; latestRun: BlogRepetitionRunView | Record<string, never>; runs: number } | null>( null );
  const [ publish, setPublish ] = useState<BlogPublishResponse | null>( null );
  const [ verify, setVerify ] = useState<BlogVerifyResponse | null>( null );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ busy, setBusy ] = useState( '' );

  const load = useCallback( async () => {
    if ( !batchId ) return;
    setError( '' );
    try
    {
      // Six independent reads, in parallel. Each is one index query against the batch
      // partition, and serialising them would make the page feel broken on a large wave.
      const [ detail, reviewState, qaState, repetitionState, publishState, verifyState ] =
        await Promise.all( [
          seoApi.getBlogBatch( batchId, 200 ),
          seoApi.getBlogBatchReviewState( batchId ),
          seoApi.getBlogBatchQaState( batchId ),
          seoApi.getBlogRepetitionState( batchId ),
          seoApi.getBlogBatchPublishState( batchId ),
          seoApi.getBlogBatchVerifyState( batchId ),
        ] );
      setBatch( detail.batch );
      setReview( reviewState.reviewState );
      setQa( qaState );
      setRepetition( repetitionState.state );
      setPublish( publishState );
      setVerify( verifyState );
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not load this wave' );
    } finally
    {
      setLoading( false );
    }
  }, [ batchId ] );

  useEffect( () => { void load(); }, [ load ] );

  async function sweepRepetition () {
    setBusy( 'repetition' );
    setError( '' );
    try
    {
      await seoApi.runBlogRepetition( batchId );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'The repetition sweep failed' );
    } finally
    {
      setBusy( '' );
    }
  }

  if ( !batchId )
  {
    const empty = (
        <div className="inner-page">
          <h1 className="inner-page-title">Blog Production wave</h1>
          <p>No wave was named. <Link href="/workspace/seo/blog-production">Back to the wave list</Link>.</p>
        </div>
    );
    if ( embedded ) return empty;
    return (
      <Layout user={ user } onSignOut={ signOut }>
        <SEO title="Blog Production wave" description="One production wave" />
        { empty }
      </Layout>
    );
  }

  const rollup = batch?.rollup;
  const batchState = qa?.batchState;

  const body = (
      <div className="inner-page">
        <p style={ { fontSize: 13, margin: '0 0 8px' } }>
          <Link href="/workspace/seo/blog-production" style={ { color: '#1a3a2a' } }>← Production waves</Link>
        </p>
        <h1 className="inner-page-title">{ batch ? batch.name : 'Loading…' }</h1>
        { batch && (
          <p style={ { color: 'rgba(0,0,0,.54)', fontSize: 14 } }>
            { batch.defaultCategory } · { batch.articleClass } · <strong>{ batch.status }</strong>
            { batch.storedStatus !== batch.status && (
              <span style={ { color: '#9ca3af' } }> (cached: { batch.storedStatus })</span>
            ) }
          </p>
        ) }

        { error && (
          <div role="alert" style={ { background: '#fef2f2', color: '#b91c1c', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 14 } }>
            { error }
          </div>
        ) }
        { loading && <p style={ { color: '#6b7280' } }>Loading…</p> }

        { rollup && (
          <Panel title="Intake"
            subtitle="Did the bytes arrive, and did extraction work. This is about the document, not the article.">
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="Sources" value={ rollup.sources } />
              <Stat label="Extracted" value={ rollup.extracted } tone="#16a34a" />
              <Stat label="Pending" value={ rollup.pending } tone={ rollup.pending ? '#d97706' : undefined } />
              <Stat label="Failed" value={ rollup.failed } tone={ rollup.failed ? '#b91c1c' : undefined } />
              <Stat label="Words" value={ rollup.words.toLocaleString() } />
              <Stat label="Complete" value={ rollup.complete ? 'yes' : 'no' } />
            </div>
            { rollup.complete && (
              <p style={ { fontSize: 12, color: '#6b7280', margin: '12px 0 0' } }>
                Complete means every source reached a terminal intake state. It does not mean
                anything is publishable, and nothing here publishes.
              </p>
            ) }
          </Panel>
        ) }

        { review && (
          <Panel title="Source reading"
            subtitle="Section 2: an article may not be built from a title or an excerpt. Analysis produces evidence; a person recording that they read it is a separate act."
            action={ <a href={ `/workspace/seo/blog-production?tab=review&batch=${ encodeURIComponent( batchId ) }` }
              style={ { color: '#1a3a2a', fontSize: 13, fontWeight: 600 } }>Open source review →</a> }>
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="Analysed" value={ review.analysed } />
              <Stat label="Read" value={ review.reviewed } tone="#16a34a" />
              <Stat label="Awaiting analysis" value={ review.awaitingAnalysis }
                tone={ review.awaitingAnalysis ? '#d97706' : undefined } />
              <Stat label="Awaiting a reader" value={ review.awaitingReview }
                tone={ review.awaitingReview ? '#d97706' : undefined } />
              <Stat label="Analysis versions" value={ review.analysisVersions } />
            </div>
          </Panel>
        ) }

        { batchState && (
          <Panel title="QA and sign-off"
            subtitle="A QA run records what every rule said about one exact version. A sign-off is a person accepting that verdict and answering the eleven judgements no program can make."
            action={ <a href={ `/workspace/seo/blog-production?tab=qa&batch=${ encodeURIComponent( batchId ) }` }
              style={ { color: '#1a3a2a', fontSize: 13, fontWeight: 600 } }>Open QA review →</a> }>
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="QA run" value={ batchState.qaRun } />
              <Stat label="Signed off" value={ batchState.signedOff } tone="#16a34a" />
              <Stat label="Awaiting sign-off" value={ batchState.awaitingSignoff }
                tone={ batchState.awaitingSignoff ? '#d97706' : undefined } />
              <Stat label="Runs" value={ batchState.totalRuns } />
              <Stat label="Signatures" value={ batchState.totalSignoffs } />
            </div>
            { Object.keys( batchState.byVerdict ).length > 0 && (
              <div style={ { marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' } }>
                { Object.entries( batchState.byVerdict ).map( ( [ verdict, count ] ) => (
                  <span key={ verdict } style={ { background: '#f3f4f6', padding: '3px 10px', borderRadius: 6, fontSize: 12 } }>
                    { verdict }: { count }
                  </span>
                ) ) }
              </div>
            ) }
          </Panel>
        ) }

        { repetition && (
          <Panel title="Collection repetition"
            subtitle="Every article can pass the per-article gate while the wave is unmistakably generated. Advisory: nothing here blocks a release, and the reviewer decides which to send back."
            action={
              <button onClick={ () => { void sweepRepetition(); } } disabled={ busy === 'repetition' }
                style={ { padding: '7px 14px', borderRadius: 6, border: '1px solid #1a3a2a', background: '#fff', color: '#1a3a2a', cursor: 'pointer', fontSize: 13 } }>
                { busy === 'repetition' ? 'Sweeping…' : 'Run a sweep' }
              </button>
            }>
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="Implicated" value={ repetition.implicated }
                tone={ repetition.implicated ? '#d97706' : undefined } />
              <Stat label="Clear" value={ repetition.clear } tone="#16a34a" />
              <Stat label="Unchecked" value={ repetition.unchecked } />
              <Stat label="Sweeps" value={ repetition.runs } />
            </div>
            { 'articles' in repetition.latestRun && (
              <p style={ { fontSize: 12, color: '#6b7280', margin: '12px 0 0' } }>
                Last sweep: { repetition.latestRun.articles } articles,
                { ' ' }{ repetition.latestRun.nearDuplicateCount } near-duplicate pair(s),
                { ' ' }{ repetition.latestRun.dominantPatternCount } dominant pattern(s),
                { ' ' }cadence spread { repetition.latestRun.cadenceSpread }.
              </p>
            ) }
          </Panel>
        ) }

        { publish?.batchState && (
          <Panel title="Publication"
            subtitle="A release records an operator's decision and writes nothing. Publishing is a separate call."
            action={ <a href={ `/workspace/seo/blog-production?tab=publish&batch=${ encodeURIComponent( batchId ) }` }
              style={ { color: '#1a3a2a', fontSize: 13, fontWeight: 600 } }>Open publish queue →</a> }>
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="Unreleased" value={ publish.batchState.unreleased } />
              <Stat label="Queued" value={ publish.batchState.queued } tone={ publish.batchState.queued ? '#2563eb' : undefined } />
              <Stat label="Published" value={ publish.batchState.published } tone="#16a34a" />
              <Stat label="Refused" value={ publish.batchState.refused } tone={ publish.batchState.refused ? '#d97706' : undefined } />
              <Stat label="Failed" value={ publish.batchState.failed } tone={ publish.batchState.failed ? '#b91c1c' : undefined } />
            </div>
          </Panel>
        ) }

        { verify?.batchState && (
          <Panel title="Publish verification"
            subtitle="Thirteen assertions against the post that actually went live. A successful write is not evidence of a correct post.">
            <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap' } }>
              <Stat label="Published" value={ verify.batchState.published } />
              <Stat label="Verified" value={ verify.batchState.verified } tone="#16a34a" />
              <Stat label="Failed" value={ verify.batchState.failed } tone={ verify.batchState.failed ? '#b91c1c' : undefined } />
              <Stat label="Live and unchecked" value={ verify.batchState.awaitingVerification }
                tone={ verify.batchState.awaitingVerification ? '#d97706' : undefined } />
              <Stat label="Runs" value={ verify.batchState.runs } />
            </div>
          </Panel>
        ) }

        { batch && (
          <div className="card" style={ { overflow: 'auto' } }>
            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
              <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 13, color: '#6b7280' } }>
                Sources in this wave ({ batch.sources.length } shown)
              </caption>
              <thead>
                <tr style={ { borderBottom: '2px solid #e5e7eb' } }>
                  <th scope="col" style={ th }>Source</th>
                  <th scope="col" style={ th }>Intake</th>
                  <th scope="col" style={ th }>Article</th>
                  <th scope="col" style={ th }>Read</th>
                  <th scope="col" style={ th }>QA</th>
                  <th scope="col" style={ th }>Signed</th>
                  <th scope="col" style={ th }>Publish</th>
                  <th scope="col" style={ th }>Verify</th>
                  <th scope="col" style={ th }>Repetition</th>
                  <th scope="col" style={ th }>Go to</th>
                </tr>
              </thead>
              <tbody>
                { batch.sources.map( source => (
                  <tr key={ source.sourceId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                    <td style={ td }>
                      <div style={ { wordBreak: 'break-all', maxWidth: 260 } }>{ source.sourceRef }</div>
                      { source.title && <div style={ { color: '#6b7280' } }>{ source.title }</div> }
                      { source.error && <div style={ { color: '#b91c1c' } }>{ source.error }</div> }
                    </td>
                    <td style={ { ...td, color: SOURCE_COLOUR[ source.status ] || '#374151', fontWeight: 600 } }>
                      { source.status }
                    </td>
                    <td style={ td }>{ source.articleStatus || '—' }</td>
                    <td style={ td }>{ source.pipeline.sourceReviewedFully || '—' }</td>
                    <td style={ td }>{ source.pipeline.qaStatus || '—' }</td>
                    <td style={ td }>{ source.pipeline.signedOffBy || '—' }</td>
                    <td style={ td }>{ source.pipeline.publishStatus || '—' }</td>
                    <td style={ td }>{ source.pipeline.verifyStatus || '—' }</td>
                    <td style={ { ...td, color: source.pipeline.repetitionStatus === 'IMPLICATED' ? '#d97706' : '#374151' } }>
                      { source.pipeline.repetitionStatus || '—' }
                    </td>
                    <td style={ td }>
                      <a href={ `/workspace/seo/blog-production?tab=review&source=${ encodeURIComponent( source.sourceId ) }` }
                        style={ { color: '#1a3a2a', marginRight: 8 } }>Read</a>
                      <a href={ `/workspace/seo/blog-production?tab=qa&source=${ encodeURIComponent( source.sourceId ) }` }
                        style={ { color: '#1a3a2a' } }>QA</a>
                    </td>
                  </tr>
                ) ) }
                { batch.sources.length === 0 && (
                  <tr><td colSpan={ 10 } style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>
                    No sources in this wave yet. Upload them in Blog Studio with this wave selected.
                  </td></tr>
                ) }
              </tbody>
            </table>
          </div>
        ) }
      </div>
  );

  if ( embedded ) return body;
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title={ batch ? `${ batch.name } — Blog Production` : 'Blog Production wave' }
        description="One production wave and every stage's state" />
      { body }
    </Layout>
  );
};

export default BlogProductionBatch;
