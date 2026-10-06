/**
 * Blog Production — QA review and gate sign-off.
 *
 * THE PAGE WHERE READY_TO_PUBLISH BECOMES REACHABLE, AND THE ONLY ONE.
 *
 * A QA run records what every rule said about ONE EXACT VERSION of the article, with the body hash
 * it ran against and how much of the published corpus the duplication check actually covered. A
 * sign-off is a person accepting that verdict and answering the judgements no program can make.
 *
 * Four refusals the backend enforces, surfaced here so the operator meets them as guidance rather
 * than as an error:
 *
 *   - no sign-off without a named QA run;
 *   - none when the article changed after the run, because the verdict then describes different
 *     text (this page marks a stale run in place rather than hiding it);
 *   - none when the run could not load the corpus index, because a NON_DUPLICATION result
 *     compared against nothing cannot carry a signature;
 *   - none over a blocking finding. A REVIEW is judgement; a BLOCK is a mechanical fact.
 *
 * And the property worth knowing while using it: editing the body afterwards invalidates the
 * signature automatically. The gate is derived from the sign-off on every assessment and compared
 * against the live body hash, so there is no revocation step to remember.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Layout from '../../../../../components/Layout';
import SEO from '../../../../../components/SEO';
import { usePromptDialog } from '../../../../../contexts/ConfirmContext';
import * as seoApi from '../../../../../api/seo';
import type {
  BlogQaReport, BlogQaResponse, BlogSourceView,
} from '../../../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; }

const td: React.CSSProperties = { padding: '8px 10px', verticalAlign: 'top' };
const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left' };

/** The eight sections 5 and 28 declarations, with the answer the standard demands. */
const DECLARATIONS: [ string, string ][] = [
  [ 'materiallyDifferentInquiry', 'YES' ],
  [ 'titleOnlyDifference', 'NO' ],
  [ 'uniqueReaderPromise', 'YES' ],
  [ 'uniqueIntellectualMovement', 'YES' ],
  [ 'exactSlugCollision', 'NO' ],
  [ 'exactBodyDuplicate', 'NO' ],
  [ 'unresolvedConceptualDuplicate', 'NO' ],
  [ 'uniquePurposeRecorded', 'YES' ],
];

const VERDICT_COLOUR: Record<string, string> = {
  PASS: '#16a34a', REVIEW: '#d97706', BLOCKED: '#b91c1c',
};

const BlogQaReview: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const prompt = usePromptDialog();
  const sourceId = typeof router.query.source === 'string' ? router.query.source : '';
  const batchId = typeof router.query.batch === 'string' ? router.query.batch : '';

  const [ queue, setQueue ] = useState<BlogSourceView[]>( [] );
  const [ state, setState ] = useState<BlogQaResponse | null>( null );
  const [ report, setReport ] = useState<BlogQaReport | null>( null );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ busy, setBusy ] = useState( '' );
  const [ gates, setGates ] = useState<Record<string, string>>( {} );
  const [ declarations, setDeclarations ] = useState<Record<string, string>>( {} );
  const [ statement, setStatement ] = useState( '' );

  const load = useCallback( async () => {
    setError( '' );
    try
    {
      if ( batchId && !sourceId )
      {
        const listing = await seoApi.listBlogSourcesInBatch( batchId );
        setQueue( listing.sources || [] );
        setState( null );
        setReport( null );
        return;
      }
      if ( !sourceId ) return;
      const data = await seoApi.getBlogQaState( sourceId );
      setState( data );
      setGates( previous => {
        const next = { ...previous };
        for ( const gate of data.humanGates || [] )
        {
          if ( !next[ gate ] ) next[ gate ] = '';
        }
        return next;
      } );
      setDeclarations( previous => {
        const next = { ...previous };
        for ( const [ name, expected ] of DECLARATIONS )
        {
          if ( !next[ name ] ) next[ name ] = expected;
        }
        return next;
      } );
      const latest = data.state?.latestRun;
      if ( latest && 'qaRunId' in latest && latest.qaRunId )
      {
        const full = await seoApi.getBlogQaRun( latest.qaRunId );
        setReport( full.run.report );
      } else
      {
        setReport( null );
      }
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not load the QA state' );
    } finally
    {
      setLoading( false );
    }
  }, [ sourceId, batchId ] );

  useEffect( () => { void load(); }, [ load ] );

  async function runQa () {
    setBusy( 'qa' );
    setError( '' );
    setNotice( '' );
    try
    {
      const result = await seoApi.runBlogQa( sourceId );
      setNotice( `QA run recorded: ${ result.verdict }, ${ result.blockingCount } blocking, `
        + `${ result.reviewCount } review, compared against ${ result.corpusChecked } published posts.` );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not run QA' );
    } finally
    {
      setBusy( '' );
    }
  }

  async function signOff () {
    const run = state?.state?.latestRun;
    if ( !run || !( 'qaRunId' in run ) ) return;
    setBusy( 'sign' );
    setError( '' );
    setNotice( '' );
    try
    {
      const result = await seoApi.signOffBlogGate( {
        qaRunId: run.qaRunId,
        gates,
        declarations,
        statement,
      } );
      setNotice( result.note || 'Signed off.' );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not sign off' );
    } finally
    {
      setBusy( '' );
    }
  }

  async function revoke ( signoffId: string ) {
    const reason = await prompt( {
      title: 'Withdraw this signature',
      label: 'Why is this signature being withdrawn?',
      required: true,
      minLength: 10,
      multiline: true,
      helper: 'At least 10 characters',
    } );
    if ( reason === null ) return;
    // Kept as a post-condition. The 10-character floor is enforced in three places on
    // purpose: minLength disables the confirm button, helper says why, and this line is
    // the one the backend's own refusal is mirrored by.
    if ( reason.trim().length < 10 ) return;
    setBusy( 'revoke' );
    setError( '' );
    try
    {
      await seoApi.revokeBlogSignoff( signoffId, reason );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not revoke' );
    } finally
    {
      setBusy( '' );
    }
  }

  const article = state?.state;
  const run = article && 'qaRunId' in ( article.latestRun || {} ) ? article.latestRun as { qaRunId: string; verdict: string; blockingCount: number; reviewCount: number; corpusChecked: number; ranBy: string; ranAt: string } : null;
  const signoff = article && 'signoffId' in ( article.signoff || {} ) ? article.signoff as { signoffId: string; signedBy: string; signedAt: string; statement: string } : null;
  const canSign = Boolean(
    run && !article?.runStale && run.blockingCount === 0 && run.corpusChecked > 0
    && statement.trim().length >= 40
    && ( state?.humanGates || [] ).every( gate => gates[ gate ] && gates[ gate ] !== 'FAIL' ),
  );

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="QA review — Blog Production" description="Run QA and record a gate sign-off" />
      <div className="inner-page">
        <p style={ { fontSize: 13, margin: '0 0 8px' } }>
          <Link href="/workspace/seo/blog-production/" style={ { color: '#1a3a2a' } }>← Production waves</Link>
          { batchId && (
            <>
              { ' · ' }
              <a href={ `/workspace/seo/blog-production/batch/?id=${ encodeURIComponent( batchId ) }` }
                style={ { color: '#1a3a2a' } }>This wave</a>
            </>
          ) }
        </p>
        <h1 className="inner-page-title">QA review</h1>

        { error && (
          <div role="alert" style={ { background: '#fef2f2', color: '#b91c1c', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 14 } }>
            { error }
          </div>
        ) }
        { notice && (
          <div role="status" style={ { background: '#f0fdf4', color: '#15803d', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 14 } }>
            { notice }
          </div>
        ) }
        { loading && <p style={ { color: '#6b7280' } }>Loading…</p> }

        { !sourceId && (
          <div className="card" style={ { overflow: 'auto' } }>
            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
              <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 13, color: '#6b7280' } }>
                { batchId ? 'Sources in this wave' : 'Name a source in the URL, or open one from a wave.' }
              </caption>
              <thead>
                <tr style={ { borderBottom: '2px solid #e5e7eb' } }>
                  <th scope="col" style={ th }>Source</th>
                  <th scope="col" style={ th }>Article</th>
                  <th scope="col" style={ th }>QA</th>
                  <th scope="col" style={ th }>Signed</th>
                  <th scope="col" style={ th }></th>
                </tr>
              </thead>
              <tbody>
                { queue.map( row => (
                  <tr key={ row.sourceId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                    <td style={ td }>{ row.sourceRef }</td>
                    <td style={ td }>{ row.articleStatus || '—' }</td>
                    <td style={ { ...td, color: VERDICT_COLOUR[ row.pipeline.qaStatus ] || '#374151' } }>
                      { row.pipeline.qaStatus || 'not run' }
                    </td>
                    <td style={ td }>{ row.pipeline.signedOffBy || '—' }</td>
                    <td style={ td }>
                      <a href={ `/workspace/seo/blog-production/qa/?source=${ encodeURIComponent( row.sourceId ) }&batch=${ encodeURIComponent( batchId ) }` }
                        style={ { color: '#1a3a2a' } }>Review</a>
                    </td>
                  </tr>
                ) ) }
                { queue.length === 0 && !loading && (
                  <tr><td colSpan={ 5 } style={ { padding: 32, textAlign: 'center', color: '#6b7280' } }>
                    Nothing here yet.
                  </td></tr>
                ) }
              </tbody>
            </table>
          </div>
        ) }

        { article && (
          <>
            <div className="card" style={ { padding: 16, marginBottom: 16 } }>
              <div style={ { display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' } }>
                <div>
                  <h2 style={ { fontSize: 15, margin: '0 0 6px' } }>Latest QA run</h2>
                  { run ? (
                    <p style={ { fontSize: 13, color: 'rgba(0,0,0,.54)', margin: 0 } }>
                      <strong style={ { color: VERDICT_COLOUR[ run.verdict ] || '#374151' } }>{ run.verdict }</strong>
                      { ' · ' }{ run.blockingCount } blocking · { run.reviewCount } review ·
                      { ' ' }compared against { run.corpusChecked.toLocaleString() } published posts ·
                      { ' ' }{ run.ranBy } at { run.ranAt }
                    </p>
                  ) : (
                    <p style={ { fontSize: 13, color: '#6b7280', margin: 0 } }>
                      No QA run yet. Run one to record what the rules say about this exact version.
                    </p>
                  ) }
                  { article.runStale && (
                    <p style={ { fontSize: 13, color: '#b45309', margin: '8px 0 0' } }>
                      The article changed after this run, so the verdict describes different text.
                      Run QA again before signing.
                    </p>
                  ) }
                  { run && run.corpusChecked === 0 && (
                    <p style={ { fontSize: 13, color: '#b91c1c', margin: '8px 0 0' } }>
                      This run could not load the published corpus index, so its NON_DUPLICATION
                      result compared against nothing. A signature over that is a signature over
                      nothing and will be refused.
                    </p>
                  ) }
                </div>
                <button onClick={ () => { void runQa(); } } disabled={ busy !== '' }
                  style={ { padding: '9px 18px', borderRadius: 6, border: '1px solid #1a3a2a', background: '#fff', color: '#1a3a2a', cursor: 'pointer', fontSize: 14 } }>
                  { busy === 'qa' ? 'Running…' : run ? 'Run QA again' : 'Run QA' }
                </button>
              </div>
            </div>

            { report && (
              <div className="card" style={ { padding: 16, marginBottom: 16 } }>
                <h2 style={ { fontSize: 15, margin: '0 0 12px' } }>What the rules said</h2>
                <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 } }>
                  { Object.entries( report.machineGate ).map( ( [ gate, value ] ) => (
                    <span key={ gate } style={ { background: '#f3f4f6', padding: '3px 10px', borderRadius: 6, fontSize: 12 } }>
                      { gate }: <strong>{ value }</strong>
                    </span>
                  ) ) }
                </div>
                { report.blocking.length > 0 && (
                  <>
                    <h3 style={ { fontSize: 13, margin: '0 0 6px', color: '#b91c1c' } }>
                      Blocking ({ report.blocking.length }) — a mechanical fact, not something a
                      signature can accept
                    </h3>
                    { report.blocking.map( item => (
                      <p key={ item } style={ { fontSize: 12, background: '#fef2f2', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px' } }>{ item }</p>
                    ) ) }
                  </>
                ) }
                { report.review.length > 0 && (
                  <>
                    <h3 style={ { fontSize: 13, margin: '12px 0 6px', color: '#b45309' } }>
                      Review ({ report.review.length }) — judgement, which is what you are here for
                    </h3>
                    { report.review.map( item => (
                      <p key={ item } style={ { fontSize: 12, background: '#fffbeb', padding: '8px 10px', borderRadius: 6, margin: '0 0 6px' } }>{ item }</p>
                    ) ) }
                  </>
                ) }
                { report.template.checked && (
                  <p style={ { fontSize: 12, color: report.template.compliant ? '#15803d' : '#b45309', margin: '12px 0 0' } }>
                    Template { report.template.templateName }:{ ' ' }
                    { report.template.compliant ? 'compliant' : `${ report.template.findings.length } finding(s)` }
                  </p>
                ) }
                { report.blocking.length === 0 && report.review.length === 0 && (
                  <p style={ { fontSize: 13, color: '#15803d', margin: 0 } }>
                    Nothing mechanical is outstanding. The eleven judgements below are yours.
                  </p>
                ) }
              </div>
            ) }

            { signoff && !article.signoffStale && (
              <div className="card" style={ { padding: 16, marginBottom: 16, background: '#f0fdf4' } }>
                <h2 style={ { fontSize: 15, margin: '0 0 6px' } }>Signed off</h2>
                <p style={ { fontSize: 13, color: '#15803d', margin: '0 0 8px' } }>
                  { signoff.signedBy } at { signoff.signedAt }
                </p>
                <p style={ { fontSize: 13, color: '#374151', margin: '0 0 12px' } }>{ signoff.statement }</p>
                <button onClick={ () => { void revoke( signoff.signoffId ); } } disabled={ busy !== '' }
                  style={ { padding: '7px 14px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', color: '#374151', cursor: 'pointer', fontSize: 13 } }>
                  Withdraw this signature
                </button>
              </div>
            ) }
            { signoff && article.signoffStale && (
              <div className="card" style={ { padding: 16, marginBottom: 16, background: '#fffbeb' } }>
                <h2 style={ { fontSize: 15, margin: '0 0 6px' } }>The signature no longer covers this article</h2>
                <p style={ { fontSize: 13, color: '#b45309', margin: 0 } }>
                  { signoff.signedBy } signed a different version of the body. That signature was
                  invalidated automatically when the text changed — nothing had to revoke it. Run QA
                  again and sign the current version.
                </p>
              </div>
            ) }

            { run && !article.releasable && (
              <div className="card" style={ { padding: 16 } }>
                <h2 style={ { fontSize: 15, margin: '0 0 4px' } }>Sign off</h2>
                <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 14px', maxWidth: 700 } }>
                  Answering these makes the article RELEASABLE. It does not publish it, and it does
                  not survive an edit to the body.
                </p>

                <h3 style={ { fontSize: 13, margin: '0 0 8px' } }>The eleven judgements (section 29)</h3>
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 8, marginBottom: 16 } }>
                  { ( state?.humanGates || [] ).map( gate => (
                    <label key={ gate } style={ { fontSize: 12, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', background: '#f9fafb', padding: '6px 10px', borderRadius: 6 } }>
                      { gate }
                      <select value={ gates[ gate ] || '' }
                        onChange={ event => setGates( { ...gates, [ gate ]: event.target.value } ) }
                        style={ { padding: '4px 6px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 12 } }>
                        <option value="">—</option>
                        { ( state?.gateAnswers || [] ).map( answer => (
                          <option key={ answer } value={ answer }>{ answer }</option>
                        ) ) }
                      </select>
                    </label>
                  ) ) }
                </div>

                <h3 style={ { fontSize: 13, margin: '0 0 4px' } }>Declarations (sections 5 and 28)</h3>
                <p style={ { fontSize: 11, color: '#6b7280', margin: '0 0 8px' } }>
                  Each must be answered the way the standard requires. Answering one the other way
                  says this article is a duplicate, and it will be refused rather than recorded.
                </p>
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8, marginBottom: 16 } }>
                  { DECLARATIONS.map( ( [ name, expected ] ) => (
                    <label key={ name } style={ { fontSize: 12, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', background: '#f9fafb', padding: '6px 10px', borderRadius: 6 } }>
                      { name }
                      <select value={ declarations[ name ] || expected }
                        onChange={ event => setDeclarations( { ...declarations, [ name ]: event.target.value } ) }
                        style={ { padding: '4px 6px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 12 } }>
                        <option value="YES">YES</option>
                        <option value="NO">NO</option>
                      </select>
                    </label>
                  ) ) }
                </div>

                { ( report?.reviewFlagsRequired || [] ).length > 0 && (
                  <>
                    <h3 style={ { fontSize: 13, margin: '0 0 4px' } }>Factual reviews this body requires (section 20)</h3>
                    <p style={ { fontSize: 11, color: '#6b7280', margin: '0 0 8px' } }>
                      Asked only for the domains this article actually touches.
                    </p>
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8, marginBottom: 16 } }>
                      { ( report?.reviewFlagsRequired || [] ).map( flag => (
                        <label key={ flag } style={ { fontSize: 12, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', background: '#eff6ff', padding: '6px 10px', borderRadius: 6 } }>
                          { flag }
                          <select value={ declarations[ flag ] || '' }
                            onChange={ event => setDeclarations( { ...declarations, [ flag ]: event.target.value } ) }
                            style={ { padding: '4px 6px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 12 } }>
                            <option value="">—</option>
                            <option value="YES">YES</option>
                          </select>
                        </label>
                      ) ) }
                    </div>
                  </>
                ) }

                <label style={ { fontSize: 13, display: 'block', marginBottom: 12 } }>
                  What you checked and what you are accepting
                  <span style={ { color: '#6b7280' } }> — at least 40 characters; a signature with
                    no sentence behind it is a click</span>
                  <textarea rows={ 3 } value={ statement }
                    onChange={ event => setStatement( event.target.value ) }
                    style={ { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, width: '100%', fontFamily: 'inherit', fontSize: 13, marginTop: 4 } } />
                </label>

                <button onClick={ () => { void signOff(); } } disabled={ busy !== '' || !canSign }
                  style={ { padding: '9px 18px', borderRadius: 6, border: 'none', background: canSign ? '#1a3a2a' : '#9ca3af', color: '#fff', cursor: canSign ? 'pointer' : 'not-allowed', fontSize: 14 } }>
                  { busy === 'sign' ? 'Signing…' : 'Sign off' }
                </button>
                { !canSign && (
                  <p style={ { fontSize: 12, color: '#6b7280', margin: '8px 0 0' } }>
                    { article.reason }
                  </p>
                ) }
              </div>
            ) }

            { article.releasable && (
              <div className="card" style={ { padding: 16, background: '#f0fdf4' } }>
                <p style={ { fontSize: 14, color: '#15803d', margin: 0 } }>
                  This article is releasable. Releasing is an operator action on the{ ' ' }
                  <a href={ `/workspace/seo/blog-production/publish/?batch=${ encodeURIComponent( article.sourceId ? batchId : '' ) }` }
                    style={ { color: '#15803d', fontWeight: 600 } }>publish queue</a>.
                </p>
              </div>
            ) }
          </>
        ) }
      </div>
    </Layout>
  );
};

export default BlogQaReview;
