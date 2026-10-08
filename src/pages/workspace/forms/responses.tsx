/**
 * Form responses — what customers actually submitted.
 *
 * Backed by `listSubmitRequests`, which is a real API returning `SubmitRequest`
 * rows: requestNumber, phone, senderName, orderId, subject, description,
 * paymentStatus, paymentAmount, invoiceNumber, daysOld, isExpired.
 *
 * WHY `daysOld` AND `isExpired` ARE SHOWN PROMINENTLY. They are computed server-side
 * and they are the whole operational point of this screen: a submitted request that
 * nobody actioned becomes a customer who paid and heard nothing. A list sorted by
 * recency buries exactly the rows that need attention, so the default sort puts the
 * oldest unpaid first and expiry is called out rather than being a column somebody
 * has to notice.
 *
 * WHAT IS DELIBERATELY NOT HERE. `resendSubmitRequestPayment` exists in the API and
 * is not wired. Resending a payment request messages a customer about money; that
 * belongs behind an explicit confirmation on a surface built for it, not one click
 * away in a list where the adjacent row is a different person. The same reasoning
 * keeps the invoice records page read-only.
 *
 * Phone numbers show the last four digits. Every log site in this codebase masks to
 * four, and a records table is no different — a full number on screen is a
 * disclosure waiting for a screenshot.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Pagination from '../../../components/ui/Pagination';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PER_PAGE = 25;

const PAY_PAINT: Record<string, { bg: string; fg: string }> = {
  captured: { bg: '#f0fdf4', fg: '#15803d' },
  paid: { bg: '#f0fdf4', fg: '#15803d' },
  pending: { bg: '#fffbeb', fg: '#b45309' },
  failed: { bg: '#fef2f2', fg: '#b91c1c' },
};

const paint = ( s?: string ) =>
  PAY_PAINT[ ( s || '' ).toLowerCase() ] || { bg: '#f9fafb', fg: 'rgba(0,0,0,.54)' };

const FormResponsesPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const toast = useToastContext();
  const [ rows, setRows ] = useState<api.SubmitRequest[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ payFilter, setPayFilter ] = useState( 'all' );
  const [ search, setSearch ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ expanded, setExpanded ] = useState<string | null>( null );

  const load = useCallback( async () => {
    setLoading( true );
    try
    {
      // No server-side filter: the API takes one paymentStatus, and filtering here
      // means switching a filter does not re-hit the endpoint.
      setRows( await api.listSubmitRequests() );
    } catch
    {
      toast.error( 'Could not load form responses' );
    } finally
    {
      setLoading( false );
    }
  }, [ toast ] );

  useEffect( () => { load(); }, [ load ] );
  useEffect( () => { setPage( 1 ); }, [ payFilter, search ] );

  const statuses = useMemo( () => {
    const set = new Set<string>();
    rows.forEach( ( r ) => {
      if ( r.paymentStatus ) set.add( r.paymentStatus.toLowerCase() );
    } );
    return Array.from( set ).sort();
  }, [ rows ] );

  /* Derived from the loaded rows, so it changes as the list does - memoised on `statuses`
     rather than rebuilt per render. 'all' is a real option, not a placeholder. */
  const payFilterOptions: SelectOption[] = useMemo( () => [
    { value: 'all', label: 'All' },
    ...statuses.map( ( s ) => ( { value: s, label: s } ) ),
  ], [ statuses ] );

  const filtered = useMemo( () => {
    const q = search.trim().toLowerCase();
    const list = rows.filter( ( r ) => {
      if ( payFilter !== 'all'
        && ( r.paymentStatus || '' ).toLowerCase() !== payFilter ) return false;
      if ( !q ) return true;
      return [ r.requestNumber, r.requestId, r.senderName, r.phone, r.orderId,
        r.subject, r.invoiceNumber ]
        .some( ( f ) => String( f || '' ).toLowerCase().includes( q ) );
    } );
    // Oldest UNPAID first. A recency sort buries the rows that need attention, and
    // an unactioned request is a customer who paid and heard nothing.
    return [ ...list ].sort( ( a, b ) => {
      const aUnpaid = ( a.paymentStatus || '' ).toLowerCase() === 'pending' ? 0 : 1;
      const bUnpaid = ( b.paymentStatus || '' ).toLowerCase() === 'pending' ? 0 : 1;
      if ( aUnpaid !== bUnpaid ) return aUnpaid - bUnpaid;
      return ( b.daysOld ?? 0 ) - ( a.daysOld ?? 0 );
    } );
  }, [ rows, payFilter, search ] );

  const totals = useMemo( () => ( {
    count: filtered.length,
    pending: filtered.filter( ( r ) =>
      ( r.paymentStatus || '' ).toLowerCase() === 'pending' ).length,
    expired: filtered.filter( ( r ) => r.isExpired ).length,
    collected: filtered
      .filter( ( r ) => [ 'captured', 'paid' ].includes(
        ( r.paymentStatus || '' ).toLowerCase() ) )
      .reduce( ( n, r ) => n + ( Number( r.paymentAmount ) || 0 ), 0 ),
  } ), [ filtered ] );

  const totalPages = Math.max( 1, Math.ceil( filtered.length / PER_PAGE ) );
  const pageRows = filtered.slice( ( page - 1 ) * PER_PAGE, page * PER_PAGE );

  const when = ( ts?: number ) => ts
    ? new Date( ts ).toLocaleDateString( 'en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit' } )
    : '—';
  const last4 = ( p?: string ) => p ? `…${String( p ).slice( -4 )}` : '—';

  const content = (
    <div className="fr-page">
      <div className="fr-inner">
        { !embedded && (
          <header className="fr-head">
            <h1 className="fr-h1">Form responses</h1>
            <p className="fr-sub">
              What customers submitted through WhatsApp flows, oldest unpaid first —
              because an unactioned request is somebody waiting.
            </p>
          </header>
        ) }

        <div className="fr-cards">
          <div className="fr-card">
            <span className="fr-n">{ totals.count }</span>
            <span className="fr-l">Responses</span>
          </div>
          <div className="fr-card">
            <span className="fr-n fr-warn">{ totals.pending }</span>
            <span className="fr-l">Awaiting payment</span>
          </div>
          <div className="fr-card">
            <span className="fr-n fr-bad">{ totals.expired }</span>
            <span className="fr-l">Expired</span>
          </div>
          <div className="fr-card">
            <span className="fr-n">
              { new Intl.NumberFormat( 'en-IN', {
                style: 'currency', currency: 'INR', maximumFractionDigits: 0,
              } ).format( totals.collected ) }
            </span>
            <span className="fr-l">Collected</span>
          </div>
        </div>

        <div className="fr-filters">
          <div className="fr-fg">
            <label htmlFor="fr-q">Search</label>
            <input id="fr-q" type="text" value={ search }
              placeholder="Request no, name, order, invoice"
              onChange={ ( e ) => setSearch( e.target.value ) } />
          </div>
          <div className="fr-fg">
            { /*
               * SHAPE (a): the external label that was bound to this control by id is gone and
               * Select owns the pair. Left in place it would have named nothing - a button
               * takes its accessible name from its contents - and the control would have
               * announced itself as "Paid", which is a payment status and not a field name.
               * The search input above keeps its own label, which still associates correctly
               * because that one is a native input.
               */ }
            <Select label="Payment" value={ payFilter }
              onChange={ ( v ) => setPayFilter( v ) }
              options={ payFilterOptions }
              /* Layout only. The trigger shows the SELECTED label where a native control
                 sized itself to its widest option, so an unsized filter re-flows the row
                 every time it is used - and this list is derived from the loaded rows, so
                 its widest member is not even knowable at author time. */
              style={ { width: 180 } } />
          </div>
          <div className="fr-actions">
            <Button variant="secondary" icon="refresh" onClick={ load }
              disabled={ loading } loading={ loading }>Refresh</Button>
          </div>
        </div>

        <div className="fr-table-wrap">
          <table className="fr-table">
            <thead>
              <tr>
                <th>Request</th>
                <th>From</th>
                <th>Subject</th>
                <th>Payment</th>
                <th>Age</th>
                <th>Submitted</th>
                <th aria-label="Detail" />
              </tr>
            </thead>
            <tbody>
              { loading ? (
                <tr><td colSpan={ 7 } className="fr-state">Loading…</td></tr>
              ) : pageRows.length === 0 ? (
                <tr>
                  <td colSpan={ 7 } className="fr-state">
                    { rows.length === 0
                      ? 'No form responses yet. Submissions from WhatsApp flows appear here.'
                      : 'Nothing matches these filters.' }
                  </td>
                </tr>
              ) : pageRows.map( ( r ) => {
                const p = paint( r.paymentStatus );
                const key = r.id || r.requestId;
                return (
                  <React.Fragment key={ key }>
                    <tr className={ r.isExpired ? 'fr-row-expired' : undefined }>
                      <td className="fr-mono">{ r.requestNumber || r.requestId }</td>
                      <td>
                        <div className="fr-from">{ r.senderName || '—' }</div>
                        <div className="fr-muted">{ last4( r.phone ) }</div>
                      </td>
                      <td className="fr-subject">{ r.subject || '—' }</td>
                      <td>
                        <span className="fr-badge"
                          style={ { background: p.bg, color: p.fg } }>
                          { r.paymentStatus || 'unknown' }
                        </span>
                        { r.isExpired && <span className="fr-exp">expired</span> }
                      </td>
                      <td className="fr-muted">
                        { typeof r.daysOld === 'number' ? `${r.daysOld}d` : '—' }
                      </td>
                      <td className="fr-when">{ when( r.createdAt ) }</td>
                      <td>
                        <button type="button" className="fr-pill"
                          onClick={ () => setExpanded( expanded === key ? null : key ) }>
                          { expanded === key ? 'Hide' : 'Detail' }
                        </button>
                      </td>
                    </tr>
                    { expanded === key && (
                      <tr className="fr-detail-row">
                        <td colSpan={ 7 }>
                          <dl className="fr-dl">
                            <dt>Description</dt>
                            <dd>{ r.description || '—' }</dd>
                            <dt>Order</dt>
                            <dd className="fr-mono">{ r.orderId || '—' }</dd>
                            <dt>Invoice</dt>
                            <dd className="fr-mono">
                              { r.invoiceNumber || r.invoiceId || '—' }
                            </dd>
                            <dt>Amount</dt>
                            <dd>
                              { typeof r.paymentAmount === 'number'
                                ? new Intl.NumberFormat( 'en-IN', {
                                  style: 'currency', currency: 'INR',
                                } ).format( r.paymentAmount )
                                : '—' }
                            </dd>
                            <dt>Transaction</dt>
                            <dd className="fr-mono">{ r.transactionId || '—' }</dd>
                          </dl>
                          { r.contactId && (
                            <Link className="fr-link"
                              href={ `/workspace/engage/inbox?contact=${encodeURIComponent( r.contactId )}` }>
                              Open the conversation
                            </Link>
                          ) }
                        </td>
                      </tr>
                    ) }
                  </React.Fragment>
                );
              } ) }
            </tbody>
          </table>
        </div>

        { totalPages > 1 && (
          <Pagination currentPage={ page } totalPages={ totalPages }
            onPageChange={ setPage } />
        ) }

        <p className="fr-note">
          Read-only. Resending a payment request messages a customer about money, so
          it stays on the surface built for it rather than one click away in a list.
          Phone numbers show the last four digits.
        </p>
      </div>

      <style jsx>{ `
        .fr-page{
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#fafafa;min-height:100%;padding:40px 0;box-sizing:border-box;
        }
        .fr-inner{max-width:1300px;margin:0 auto;padding:0 24px;box-sizing:border-box}
        .fr-head{margin:0 0 28px}
        .fr-h1{
          font-size:clamp(32px,4.2vw,54px);font-weight:700;line-height:1.04;
          letter-spacing:-1.875px;color:rgba(0,0,0,.95);margin:0 0 14px;
        }
        .fr-sub{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:0;max-width:640px;
        }

        .fr-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 22px}
        .fr-card{
          display:flex;flex-direction:column;gap:2px;background:#fff;
          border:1px solid #e5e7eb;border-radius:13px;padding:16px 18px;
        }
        .fr-n{font-size:22px;font-weight:700;color:#000;line-height:1.27;letter-spacing:-.25px}
        .fr-warn{color:#b45309}
        .fr-bad{color:#dc2626}
        .fr-l{font-size:14px;color:rgba(0,0,0,.54)}

        .fr-filters{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin:0 0 20px}
        .fr-fg{display:flex;flex-direction:column;gap:6px}
        .fr-fg label{font-size:14px;color:rgba(0,0,0,.54)}
        .fr-fg input,.fr-fg select{
          font-family:inherit;font-size:15px;color:rgba(0,0,0,.898);background:#fff;
          border:2px solid #e5e7eb;border-radius:13px;padding:9px 12px;min-height:0;
        }
        .fr-fg input{width:280px}
        .fr-fg input:focus,.fr-fg select:focus{outline:none;border-color:#d1f470}
        .fr-actions{margin-left:auto}

        .fr-table-wrap{
          background:#fff;border:1px solid #e5e7eb;border-radius:13px;
          overflow:hidden;margin:0 0 16px;
        }
        .fr-table{width:100%;border-collapse:collapse}
        .fr-table th{
          background:#fafafa;padding:11px 16px;text-align:left;font-size:14px;
          font-weight:600;color:rgba(0,0,0,.54);border-bottom:1px solid #e5e7eb;
        }
        .fr-table td{
          padding:11px 16px;border-bottom:1px solid #e5e7eb;font-size:14px;
          color:rgba(0,0,0,.898);
        }
        .fr-table tr:last-child td{border-bottom:none}
        /* A left edge, not a background wash: an expired row must be findable while
           scrolling without making its text harder to read. */
        .fr-row-expired td:first-child{box-shadow:inset 3px 0 0 #dc2626}

        .fr-mono{font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px}
        .fr-from{font-weight:500}
        .fr-subject{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .fr-muted{color:rgba(0,0,0,.54);font-size:13px}
        .fr-when{color:rgba(0,0,0,.54);font-size:13px;white-space:nowrap}
        .fr-state{text-align:center;padding:40px;color:rgba(0,0,0,.54)}
        .fr-badge{
          display:inline-flex;align-items:center;padding:4px 12px;border-radius:50px;
          font-size:13px;font-weight:600;text-transform:capitalize;
        }
        .fr-exp{margin-left:8px;font-size:12px;font-weight:600;color:#dc2626}
        .fr-pill{
          font-family:inherit;font-size:13px;font-weight:500;color:rgba(0,0,0,.898);
          background:#fff;border:2px solid #e5e7eb;border-radius:50px;
          padding:6px 14px;cursor:pointer;transition:all .2s ease;
        }
        .fr-pill:hover{border-color:#d1f470;color:#1a3a2a}
        .fr-detail-row td{background:#fafafa}
        .fr-dl{
          display:grid;grid-template-columns:150px 1fr;gap:6px 18px;margin:0 0 12px;
        }
        .fr-dl dt{font-size:14px;color:rgba(0,0,0,.54)}
        .fr-dl dd{margin:0;font-size:14px;color:rgba(0,0,0,.898)}
        .fr-link{color:#1a3a2a;text-decoration:underline;font-size:14px}
        .fr-note{
          font-size:14px;line-height:1.5;color:rgba(0,0,0,.54);margin:0;max-width:740px;
        }

        @media(max-width:900px){
          .fr-cards{grid-template-columns:repeat(2,1fr)}
          .fr-table-wrap{overflow-x:auto}
          .fr-fg input{width:100%}
          .fr-sub{font-size:17px}
          .fr-dl{grid-template-columns:1fr}
        }
        @media(prefers-reduced-motion:reduce){ .fr-pill{transition:none} }
      `}</style>
    </div>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title="Form responses"
        description="Submissions from WhatsApp flows, with payment status."
        noindex
      />
      { content }
    </Layout>
  );
};

export default FormResponsesPage;
