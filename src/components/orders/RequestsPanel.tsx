import React, { useEffect, useState } from 'react';
import { fetchMyRequests } from '../../lib/serviceRequests';
import type { ServiceRequestRow } from '../../lib/serviceRequests';
import { serviceByKind } from '../../config/services';
import { useCopyFeedback } from '../../lib/useCopyFeedback';
import { colors, fontSize, radius, space } from '../../lib/design-tokens';

/**
 * "Your requests" on /orders, below the profile card (Phase O-1).
 *
 * `paidReferenceIds` are the referenceIds of the page's own PAID orders: the server activates any
 * of them that bought a service before it lists, so a request whose webhook hint was missed still
 * appears here (the self-heal). The list itself is the caller's own partition, read server-side.
 *
 * Copy behaves exactly like the order-ID copy on the same page (see useCopyFeedback).
 */
interface Props {
  accessToken: string;
  paidReferenceIds: readonly string[];
  onExpired: () => void;
}

type State = 'loading' | 'ready' | 'failed';

function dateLabel ( createdAt: number | null ): string {
  if ( createdAt === null || !Number.isFinite( createdAt ) ) return '';
  return new Date( createdAt * 1000 )
    .toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: 'numeric' } );
}

const RequestsPanel: React.FC<Props> = ( { accessToken, paidReferenceIds, onExpired } ) => {
  const [ state, setState ] = useState<State>( 'loading' );
  const [ rows, setRows ] = useState<ServiceRequestRow[]>( [] );
  const { canCopy, copiedKey, failedKey, liveMessage, copy } =
    useCopyFeedback( 'Request ID copied', 'Request ID selected. Copy it with your keyboard.' );
  const referenceKey = paidReferenceIds.join( '|' );

  useEffect( () => {
    if ( !accessToken ) return undefined;
    let live = true;
    ( async () => {
      const outcome = await fetchMyRequests( accessToken, referenceKey ? referenceKey.split( '|' ) : [] );
      if ( !live ) return;
      if ( outcome.kind === 'ok' ) { setRows( outcome.requests ); setState( 'ready' ); }
      else if ( outcome.kind === 'expired' ) onExpired();
      else setState( 'failed' );
    } )();
    return () => { live = false; };
    // onExpired is the page's stable expiry handler; re-running on its identity would refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ accessToken, referenceKey ] );

  return (
    <section className="rqp" aria-labelledby="rqp-title">
      <h2 className="rqp-title" id="rqp-title">Your requests</h2>
      { state === 'loading' && <p className="rqp-p" role="status">Loading your requests…</p> }
      { state === 'failed' && <p className="rqp-p">Requests are unavailable right now.</p> }
      { state === 'ready' && rows.length === 0 && (
        <p className="rqp-p">
          No requests yet.{ ' ' }
          { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
          <a className="rqp-link" href="/submit-request/">Submit a request</a>
          { ' or ' }
          { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
          <a className="rqp-link" href="/request-amendment/">request an amendment</a>.
        </p>
      ) }
      { state === 'ready' && rows.length > 0 && (
        <ul className="rqp-list">
          { rows.map( ( row, index ) => {
            const label = serviceByKind( row.kind )?.label || row.kind;
            const idElement = `rqp-id-${ index }`;
            return (
              <li className="rqp-row" key={ row.requestId || index }>
                <div className="rqp-line">
                  <span className="rqp-id" id={ idElement } data-wc-no-translate>{ row.requestId }</span>
                  { canCopy && row.requestId && (
                    <span className="rqp-copywrap">
                      <button
                        type="button"
                        className="rqp-copy"
                        aria-label={ `Copy request ID ${ row.requestId }` }
                        onClick={ () => copy( row.requestId, row.requestId,
                          document.getElementById( idElement ) ) }
                      >
                        Copy
                      </button>
                      <span className="rqp-hint">
                        { copiedKey === row.requestId ? 'Copied'
                          : failedKey === row.requestId ? 'Press your copy key'
                            : 'Copy request ID' }
                      </span>
                    </span>
                  ) }
                </div>
                <p className="rqp-meta">
                  { label }
                  { row.createdAt !== null ? ` · ${ dateLabel( row.createdAt ) }` : '' }
                  { row.orderNumber ? ' · Order ' : '' }
                  { row.orderNumber && <span data-wc-no-translate>{ row.orderNumber }</span> }
                </p>
                { row.targetRequestId && (
                  <p className="rqp-meta">
                    Amends <span data-wc-no-translate>{ row.targetRequestId }</span>
                  </p>
                ) }
              </li>
            );
          } ) }
        </ul>
      ) }
      <p className="rqp-live" aria-live="polite">{ liveMessage }</p>
      <style jsx>{ `
        .rqp{display:flex;flex-direction:column;gap:${ space[ 3 ] }px;padding:${ space[ 5 ] }px;
          border:1px solid ${ colors.border };border-radius:${ radius.lg }px}
        .rqp-title{margin:0;font-size:${ fontSize.h4 }px;font-weight:700;color:${ colors.grey900 }}
        .rqp-p,.rqp-meta{margin:0;font-size:${ fontSize.md }px;color:${ colors.textSecondary }}
        .rqp-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:${ space[ 3 ] }px}
        .rqp-row{display:flex;flex-direction:column;gap:${ space[ 1 ] }px;min-inline-size:0}
        .rqp-line{display:flex;flex-wrap:wrap;align-items:center;gap:${ space[ 2 ] }px}
        .rqp-id{font-family:ui-monospace,monospace;font-size:${ fontSize.base }px;color:${ colors.text };overflow-wrap:anywhere}
        .rqp-copywrap{display:inline-flex;align-items:center;gap:${ space[ 2 ] }px}
        .rqp-copy{font:inherit;font-size:${ fontSize.sm }px;padding:${ space[ 1 ] }px ${ space[ 3 ] }px;
          border:1px solid ${ colors.borderDark };border-radius:${ radius.full }px;background:${ colors.white };
          color:${ colors.primary };cursor:pointer}
        .rqp-copy:focus-visible,.rqp-link:focus-visible{outline:3px solid ${ colors.primary };outline-offset:2px}
        .rqp-hint{font-size:${ fontSize.xs }px;color:${ colors.textSecondary }}
        .rqp-link{color:${ colors.primary };text-decoration:underline}
        .rqp-live{position:absolute;inline-size:1px;block-size:1px;overflow:hidden;clip:rect(0 0 0 0)}
      ` }</style>
    </section>
  );
};

export default RequestsPanel;
