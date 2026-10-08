/**
 * Blog Production — the publish queue.
 *
 * WHY THIS PAGE SHOWS EVERY SOURCE AND NOT JUST THE ELIGIBLE ONES.
 *
 * A release page whose only content is the rows an operator can act on leaves them with no idea
 * why the other forty are missing. So `releasable_in_batch` returns every source WITH the reason,
 * and this renders both.
 *
 * WHAT THE TWO BUTTONS ACTUALLY DO, because the difference is the whole design. "Release" records a
 * decision and performs no Wix write. "Publish" performs the one Wix mutation in this system.
 * Section 38 requires that processing completion never automatically mean publishing, and nothing
 * in the extraction, queue, QA or batch paths can reach either call.
 *
 * Publishing the same article twice cannot be undone - a duplicate post gets indexed, linked and
 * cited, and deleting it afterwards leaves a dead URL. A second release therefore resolves to the
 * job that already exists, and the QUEUED to PUBLISHING transition is a conditional write so two
 * operators pressing Publish at the same moment cannot both proceed.
 *
 * When Wix writes are switched off this page says so BEFORE anything is pressed, and a publish is
 * recorded as REFUSED without being attempted - a different state from FAILED, because "the
 * operator has writes off" and "Wix rejected the post" are different facts.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Layout from '../../../../../components/Layout';
import SEO from '../../../../../components/SEO';
import { usePromptDialog } from '../../../../../contexts/ConfirmContext';
import * as seoApi from '../../../../../api/seo';
import type { BlogPublishResponse, BlogVerifyResponse } from '../../../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; }

const td: React.CSSProperties = { padding: '8px 10px', verticalAlign: 'top' };
const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left' };

const JOB_COLOUR: Record<string, string> = {
  QUEUED: '#2563eb',
  PUBLISHING: '#d97706',
  PUBLISHED: '#16a34a',
  REFUSED: '#b45309',
  FAILED: '#b91c1c',
};

const BlogPublishQueue: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const prompt = usePromptDialog();
  const batchId = typeof router.query.batch === 'string' ? router.query.batch : '';

  const [ data, setData ] = useState<BlogPublishResponse | null>( null );
  const [ verify, setVerify ] = useState<BlogVerifyResponse | null>( null );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ busy, setBusy ] = useState( '' );

  const load = useCallback( async () => {
    setError( '' );
    try
    {
      const queue = batchId
        ? await seoApi.getBlogBatchPublishState( batchId )
        : await seoApi.getBlogPublishQueue();
      setData( queue );
      if ( batchId )
      {
        setVerify( await seoApi.getBlogBatchVerifyState( batchId ) );
      }
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'Could not load the publish queue' );
    } finally
    {
      setLoading( false );
    }
  }, [ batchId ] );

  useEffect( () => { void load(); }, [ load ] );

  async function act ( key: string, work: () => Promise<string> ) {
    setBusy( key );
    setError( '' );
    setNotice( '' );
    try
    {
      setNotice( await work() );
      await load();
    } catch ( cause )
    {
      setError( cause instanceof Error ? cause.message : 'That action failed' );
    } finally
    {
      setBusy( '' );
    }
  }

  const release = ( sourceId: string ) => act( `release-${ sourceId }`, async () => {
    const job = await seoApi.releaseBlogArticle( sourceId );
    return job.created
      ? `Queued as ${ job.jobId }. Nothing has been written to Wix.`
      : job.note;
  } );

  const publish = ( jobId: string ) => act( `publish-${ jobId }`, async () => {
    const result = await seoApi.publishBlogArticle( jobId );
    return result.note;
  } );

  // async because the reason is now collected by a modal rather than a blocking native
  // prompt. Its only caller is an onClick that discards the return value, so losing the
  // synchronous Promise.resolve() is safe.
  const withdraw = async ( jobId: string ) => {
    const reason = await prompt( {
      title: 'Withdraw this release',
      label: 'Why is this release being withdrawn?',
      required: true,
      minLength: 10,
      multiline: true,
      helper: 'At least 10 characters',
    } );
    if ( reason === null ) return;
    // Kept as a post-condition, same as the QA page: the floor is enforced in three places.
    if ( reason.trim().length < 10 ) return;
    return act( `withdraw-${ jobId }`, async () => {
      await seoApi.withdrawBlogRelease( jobId, reason );
      return 'Withdrawn. It can be released again.';
    } );
  };

  const runVerify = ( sourceId: string ) => act( `verify-${ sourceId }`, async () => {
    const result = await seoApi.verifyBlogArticle( sourceId );
    return `${ result.passed } passed, ${ result.failed } failed, ${ result.skipped } skipped`
      + ( result.failedAssertions.length ? ` — ${ result.failedAssertions.join( ', ' ) }` : '' )
      + `. ${ result.note }`;
  } );

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Publish queue — Blog Production"
        description="Release and publish articles that have been signed off" />
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
        <h1 className="inner-page-title">Publish queue</h1>
        <p style={ { color: 'rgba(0,0,0,.54)', fontSize: 14, maxWidth: 780 } }>
          Releasing records a decision and writes nothing. Publishing performs the one Wix mutation
          in this system. Nothing upstream can reach either.
        </p>

        { data?.wixWritesDisabled && (
          <div role="status" style={ { background: '#fffbeb', color: '#b45309', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 14 } }>
            <strong>Wix writes are switched off.</strong> A publish will be recorded as REFUSED
            without being attempted. Clear <code>WIX_CREDENTIALS_DISABLED</code> on the function to
            enable it; a refusal is deliberate and nothing retries past it.
          </div>
        ) }
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

        { data?.batchState && (
          <div className="card" style={ { padding: 16, marginBottom: 16, display: 'flex', gap: 24, flexWrap: 'wrap' } }>
            { ( [
              [ 'Unreleased', data.batchState.unreleased, undefined ],
              [ 'Queued', data.batchState.queued, '#2563eb' ],
              [ 'Published', data.batchState.published, '#16a34a' ],
              [ 'Refused', data.batchState.refused, '#b45309' ],
              [ 'Failed', data.batchState.failed, '#b91c1c' ],
              [ 'Verified', verify?.batchState?.verified ?? 0, '#16a34a' ],
              [ 'Live and unchecked', verify?.batchState?.awaitingVerification ?? 0, '#d97706' ],
            ] as [ string, number, string | undefined ][] ).map( ( [ label, value, tone ] ) => (
              <div key={ label } style={ { minWidth: 110 } }>
                <div style={ { fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 0.4 } }>{ label }</div>
                <div style={ { fontSize: 20, fontWeight: 700, color: value ? ( tone || '#1a1a1a' ) : '#1a1a1a' } }>{ value }</div>
              </div>
            ) ) }
          </div>
        ) }

        { data?.candidates && (
          <div className="card" style={ { overflow: 'auto', marginBottom: 16 } }>
            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
              <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 13, color: '#6b7280' } }>
                Every source in this wave, with the reason each one can or cannot be released
              </caption>
              <thead>
                <tr style={ { borderBottom: '2px solid #e5e7eb' } }>
                  <th scope="col" style={ th }>Article</th>
                  <th scope="col" style={ th }>Releasable</th>
                  <th scope="col" style={ th }>Reason</th>
                  <th scope="col" style={ th }>Job</th>
                  <th scope="col" style={ th }>Actions</th>
                </tr>
              </thead>
              <tbody>
                { data.candidates.map( candidate => (
                  <tr key={ candidate.sourceId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                    <td style={ td }>
                      <div style={ { fontWeight: 600 } }>{ candidate.title || '(untitled)' }</div>
                      <div style={ { color: '#9ca3af', fontSize: 11, wordBreak: 'break-all' } }>{ candidate.slug }</div>
                    </td>
                    <td style={ { ...td, color: candidate.releasable ? '#16a34a' : '#6b7280', fontWeight: 600 } }>
                      { candidate.releasable ? 'yes' : 'no' }
                    </td>
                    <td style={ { ...td, maxWidth: 380, color: 'rgba(0,0,0,.54)' } }>{ candidate.reason }</td>
                    <td style={ { ...td, color: JOB_COLOUR[ candidate.jobStatus ] || '#6b7280' } }>
                      { candidate.jobStatus || '—' }
                    </td>
                    <td style={ td }>
                      { candidate.releasable && (
                        <button onClick={ () => { void release( candidate.sourceId ); } }
                          disabled={ busy !== '' }
                          aria-label={ `Release ${ candidate.title || candidate.sourceId } into the publish queue` }
                          style={ { padding: '5px 12px', borderRadius: 6, border: '1px solid #1a3a2a', background: '#fff', color: '#1a3a2a', cursor: 'pointer', fontSize: 12 } }>
                          { busy === `release-${ candidate.sourceId }` ? 'Releasing…' : 'Release' }
                        </button>
                      ) }
                      <a href={ `/workspace/seo/blog-production/qa/?source=${ encodeURIComponent( candidate.sourceId ) }&batch=${ encodeURIComponent( batchId ) }` }
                        style={ { color: '#1a3a2a', marginLeft: 8 } }>QA</a>
                    </td>
                  </tr>
                ) ) }
                { data.candidates.length === 0 && (
                  <tr><td colSpan={ 5 } style={ { padding: 32, textAlign: 'center', color: '#6b7280' } }>
                    No sources in this wave.
                  </td></tr>
                ) }
              </tbody>
            </table>
          </div>
        ) }

        <div className="card" style={ { overflow: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
            <caption style={ { captionSide: 'top', textAlign: 'left', padding: '10px 12px', fontSize: 13, color: '#6b7280' } }>
              { batchId ? 'Publish jobs (all waves)' : 'Publish jobs, newest first' }
            </caption>
            <thead>
              <tr style={ { borderBottom: '2px solid #e5e7eb' } }>
                <th scope="col" style={ th }>Article</th>
                <th scope="col" style={ th }>Status</th>
                <th scope="col" style={ th }>Released by</th>
                <th scope="col" style={ th }>Attempts</th>
                <th scope="col" style={ th }>Post</th>
                <th scope="col" style={ th }>Actions</th>
              </tr>
            </thead>
            <tbody>
              { ( data?.queue || [] ).map( job => (
                <tr key={ job.jobId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                  <td style={ td }>
                    <div style={ { fontWeight: 600 } }>{ job.articleTitle || '(untitled)' }</div>
                    <div style={ { color: '#9ca3af', fontSize: 11, wordBreak: 'break-all' } }>{ job.articleSlug }</div>
                    { job.error && <div style={ { color: '#b45309', fontSize: 11 } }>{ job.error }</div> }
                  </td>
                  <td style={ { ...td, color: JOB_COLOUR[ job.status ] || '#374151', fontWeight: 600 } }>
                    { job.status }
                  </td>
                  <td style={ td }>{ job.releasedBy }</td>
                  <td style={ td }>{ job.attempts }</td>
                  <td style={ td }>
                    { job.postUrl ? (
                      <a href={ job.postUrl } target="_blank" rel="noopener noreferrer"
                        style={ { color: '#1a3a2a' } }>live post</a>
                    ) : '—' }
                  </td>
                  <td style={ td }>
                    { job.status === 'QUEUED' && (
                      <>
                        <button onClick={ () => { void publish( job.jobId ); } } disabled={ busy !== '' }
                          aria-label={ `Publish ${ job.articleTitle || job.jobId } to Wix` }
                          style={ { padding: '5px 12px', borderRadius: 6, border: 'none', background: '#1a3a2a', color: '#fff', cursor: 'pointer', fontSize: 12 } }>
                          { busy === `publish-${ job.jobId }` ? 'Publishing…' : 'Publish' }
                        </button>
                        <button onClick={ () => { void withdraw( job.jobId ); } } disabled={ busy !== '' }
                          aria-label={ `Withdraw the release of ${ job.articleTitle || job.jobId }` }
                          style={ { marginLeft: 8, background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', fontSize: 12, padding: 0 } }>
                          Withdraw
                        </button>
                      </>
                    ) }
                    { ( job.status === 'PUBLISHED' ) && (
                      <button onClick={ () => { void runVerify( job.sourceId ); } } disabled={ busy !== '' }
                        aria-label={ `Verify the live post for ${ job.articleTitle || job.jobId }` }
                        style={ { padding: '5px 12px', borderRadius: 6, border: '1px solid #1a3a2a', background: '#fff', color: '#1a3a2a', cursor: 'pointer', fontSize: 12 } }>
                        { busy === `verify-${ job.sourceId }` ? 'Verifying…' : 'Verify' }
                      </button>
                    ) }
                    { ( job.status === 'REFUSED' || job.status === 'FAILED' ) && (
                      <button onClick={ () => { void release( job.sourceId ); } } disabled={ busy !== '' }
                        aria-label={ `Release ${ job.articleTitle || job.jobId } again` }
                        style={ { padding: '5px 12px', borderRadius: 6, border: '1px solid #1a3a2a', background: '#fff', color: '#1a3a2a', cursor: 'pointer', fontSize: 12 } }>
                        { busy === `release-${ job.sourceId }` ? 'Releasing…' : 'Release again' }
                      </button>
                    ) }
                  </td>
                </tr>
              ) ) }
              { ( data?.queue || [] ).length === 0 && !loading && (
                <tr><td colSpan={ 6 } style={ { padding: 32, textAlign: 'center', color: '#6b7280' } }>
                  Nothing has been released.
                </td></tr>
              ) }
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
};

export default BlogPublishQueue;
