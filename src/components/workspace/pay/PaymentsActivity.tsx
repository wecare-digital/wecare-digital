/**
 * Payments Activity — recent authoritative money state.
 *
 * There is no separate event-stream API for every invoice mutation. This view therefore does
 * not invent one: it shows the latest stored state of each invoice, ordered by the strongest
 * timestamp available (paidAt -> updatedAt -> createdAt). Delivery evidence remains on Invoices.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';

type ActivityKind = 'captured' | 'refunded' | 'failed' | 'cancelled' | 'pending' | 'invoice';

interface ActivityRow {
  invoiceId: string;
  invoiceNumber: string;
  customer: string;
  kind: ActivityKind;
  label: string;
  amount: number;
  currency: string;
  timestamp: number;
  paymentStatus: string;
  status: string;
  source: string;
}

function epochMs ( value?: number ): number {
  if ( !value ) return 0;
  return value < 1e12 ? value * 1000 : value;
}

function amount ( value: number, currency: string ): string {
  try {
    return new Intl.NumberFormat( 'en-IN', {
      style: 'currency',
      currency: currency || 'INR',
      maximumFractionDigits: 2,
    } ).format( Number( value ) || 0 );
  } catch {
    return `${currency || 'INR'} ${( Number( value ) || 0 ).toFixed( 2 )}`;
  }
}

function latestState ( invoice: api.Invoice ): ActivityRow {
  const payment = ( invoice.paymentStatus || '' ).toLowerCase();
  const status = ( invoice.status || '' ).toLowerCase();

  let kind: ActivityKind = 'invoice';
  let label = 'Invoice recorded';
  // A later verified refund supersedes the earlier captured state. Checking
  // paid first incorrectly classified refunded-but-paid invoices as captured.
  if ( payment === 'refunded' || !!invoice.refundId || !!invoice.refundAt ) {
    kind = 'refunded';
    label = payment === 'refunded' ? 'Payment refunded' : 'Refund recorded';
  } else if ( payment === 'failed' ) {
    kind = 'failed'; label = 'Payment failed';
  } else if ( [ 'captured', 'paid' ].includes( payment ) || status === 'paid' ) {
    kind = 'captured'; label = 'Payment captured';
  } else if ( status === 'cancelled' ) {
    kind = 'cancelled'; label = 'Invoice cancelled';
  } else if ( [ 'pending', 'pending_payment', 'created', 'sent' ].includes( status )
    || [ 'pending', 'created' ].includes( payment ) ) {
    kind = 'pending'; label = 'Payment pending';
  }

  return {
    invoiceId: invoice.invoiceId,
    invoiceNumber: invoice.invoiceNumber || invoice.referenceId || invoice.invoiceId,
    customer: invoice.customerName || invoice.customerPhone || 'Customer',
    kind,
    label,
    amount: Number( invoice.total ) || 0,
    currency: invoice.currency || 'INR',
    timestamp: epochMs( invoice.refundAt ) || epochMs( invoice.paidAt ) || epochMs( invoice.updatedAt ) || epochMs( invoice.createdAt ),
    paymentStatus: invoice.paymentStatus || '',
    status: invoice.status || '',
    source: invoice.serviceKind || invoice.entryPoint || 'Invoice',
  };
}

const PaymentsActivity: React.FC = () => {
  const [ invoices, setInvoices ] = useState<api.Invoice[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );
  const [ kindFilter, setKindFilter ] = useState<ActivityKind | 'all'>( 'all' );
  const [ query, setQuery ] = useState( '' );

  const load = useCallback( async () => {
    setLoading( true );
    setError( '' );
    try {
      const result = await api.listInvoicesEngine( { limit: 500 } );
      setInvoices( result.invoices || [] );
    } catch {
      setError( 'Payment activity is unavailable right now.' );
    } finally {
      setLoading( false );
    }
  }, [] );

  useEffect( () => { void load(); }, [ load ] );

  const rows = useMemo(
    () => invoices.map( latestState ).sort( ( a, b ) => b.timestamp - a.timestamp ),
    [ invoices ],
  );
  const matching = useMemo( () => rows.filter( row => {
    const text = query.trim().toLowerCase();
    return (kindFilter === 'all' || row.kind === kindFilter)
      && (!text || [row.customer, row.invoiceNumber, row.source, row.label]
        .some( value => value.toLowerCase().includes( text ) ));
  } ), [ rows, query, kindFilter ] );
  const visibleRows = matching.slice( 0, 100 );

  return (
    <section className="pa" aria-labelledby="payment-activity-title">
      <header className="pa-head">
        <div>
          <h2 id="payment-activity-title">Activity</h2>
          <p>Latest stored state per invoice. Open Ledger → Invoices for the document and delivery evidence.</p>
        </div>
        <button type="button" onClick={ () => void load() } disabled={ loading }>
          { loading ? 'Refreshing…' : 'Refresh' }
        </button>
      </header>

      { error && (
        <div className="pa-state error">
          <span>{ error }</span>
          <button type="button" onClick={ () => void load() }>Retry</button>
        </div>
      ) }

      <div className="pa-filters" role="group" aria-label="Filter payment activity">
        <label htmlFor="pa-kind">Payment state</label>
        <select id="pa-kind" value={ kindFilter }
          onChange={ event => setKindFilter( event.target.value as ActivityKind | 'all' ) }>
          <option value="all">All states</option>
          <option value="captured">Captured</option>
          <option value="refunded">Refunded</option>
          <option value="failed">Failed</option>
          <option value="pending">Pending</option>
          <option value="cancelled">Cancelled</option>
          <option value="invoice">Invoice recorded</option>
        </select>
        <label htmlFor="pa-search">Search loaded invoices</label>
        <input id="pa-search" type="search" value={ query } onChange={ e => setQuery( e.target.value ) }
          placeholder="Customer, invoice or service" />
      </div>
      { !error && !loading && <p className="pa-context" role="status">
        Showing { Math.min( matching.length, 100 ) } of { matching.length } matching latest states
        from { invoices.length } loaded invoices. This is not a complete event history.
      </p> }
      { !error && loading && <div className="pa-state">Loading payment activity…</div> }

      { !error && !loading && matching.length === 0 && (
        <div className="pa-state">{ rows.length === 0
          ? 'No invoice or payment activity yet.'
          : 'No loaded invoices match these filters.' }</div>
      ) }

      { !error && !loading && matching.length > 0 && (
        <div className="pa-list">
          { visibleRows.map( row => (
            <Link
              key={ row.invoiceId }
              href={ `/workspace/payments?view=ledger&ledger=invoices&invoice=${encodeURIComponent( row.invoiceId )}` }
              className="pa-row"
            >
              <span className={ `pa-dot ${row.kind}` } aria-hidden="true" />
              <span className="pa-copy">
                <strong>{ row.label }</strong>
                <small>{ row.customer } · { row.invoiceNumber } · { row.source }</small>
                <small>
                  { row.timestamp ? new Date( row.timestamp ).toLocaleString( 'en-IN', {
                    day: '2-digit', month: 'short', year: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  } ) : 'Timestamp unavailable' }
                </small>
              </span>
              <span className="pa-amount">{ amount( row.amount, row.currency ) }</span>
              <span className="pa-arrow" aria-hidden="true">→</span>
            </Link>
          ) ) }
        </div>
      ) }

      <style jsx>{`
        .pa{min-width:0}
        .pa-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
        .pa-head h2{margin:0;color:var(--text);font-size:var(--h3)}
        .pa-head p{margin:4px 0 0;color:var(--text-muted);font-size:var(--text-sm);line-height:1.45}
        .pa-head button,.pa-state button{padding:8px 14px;border:1px solid var(--border);border-radius:11px;background:#fff;color:var(--text);font:inherit;font-weight:650;cursor:pointer}
        .pa-head button:disabled{opacity:.55;cursor:default}
        .pa-filters{display:flex;align-items:center;flex-wrap:wrap;gap:8px 10px;margin:0 0 12px}
        .pa-filters label{font-size:var(--text-xs);font-weight:700;color:var(--text-muted)}
        .pa-filters select,.pa-filters input{min-height:38px;min-width:0;border:1px solid var(--border);border-radius:9px;padding:7px 9px;background:var(--surface,#fff);color:var(--text);font:inherit;font-size:var(--text-sm)}
        .pa-filters input{flex:1 1 230px}
        .pa-context{font-size:var(--text-xs);color:var(--text-muted);margin:2px 0 11px}
        .pa-state{padding:24px;border:1px solid var(--border);border-radius:14px;color:var(--text-muted);display:flex;align-items:center;justify-content:space-between;gap:12px}
        .pa-state.error{color:var(--danger)}
        .pa-list{border:1px solid var(--border);border-radius:14px;overflow:hidden;background:#fff}
        .pa-row{min-height:68px;display:grid;grid-template-columns:10px minmax(0,1fr) auto 18px;align-items:center;gap:12px;padding:10px 14px;border-top:1px solid var(--border-light);color:var(--text);text-decoration:none}
        .pa-row:first-child{border-top:0}
        .pa-row:hover,.pa-row:focus-visible{background:var(--bg-secondary)}
        .pa-row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
        .pa-dot{width:8px;height:8px;border-radius:999px;background:var(--text-muted)}
        .pa-dot.captured{background:var(--success)}
        .pa-dot.failed,.pa-dot.cancelled{background:var(--danger)}
        .pa-dot.pending{background:var(--warning)}
        .pa-copy{min-width:0;display:flex;flex-direction:column;gap:2px}
        .pa-copy strong{font-size:var(--text-sm)}
        .pa-copy small{font-size:var(--text-xs);color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .pa-amount{font-size:var(--text-sm);font-weight:700;white-space:nowrap}
        .pa-arrow{color:var(--accent)}
        @media(max-width:640px){
          .pa-head{align-items:stretch;flex-direction:column}
          .pa-head button{align-self:flex-start}
          .pa-row{grid-template-columns:10px minmax(0,1fr) 18px}
          .pa-amount{grid-column:2;margin-top:2px}
          .pa-arrow{grid-column:3;grid-row:1/3}
        }
        @media(forced-colors:active){.pa-list,.pa-state,.pa-head button{border-color:CanvasText}}
      `}</style>
    </section>
  );
};

export default PaymentsActivity;
