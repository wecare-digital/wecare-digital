/**
 * The ONE operational responses queue — the merge the Phase 1 audit called for.
 *
 * Before this, the same submission data was shown four ways (forms/responses, flow-responses
 * "Legacy Requests", flow-hub "Submissions", selfservice "Submissions"), each with its own
 * fetch, filter and badge. This component is the single surface, server-backed, that the new
 * Request nav section renders and that those four pages redirect into.
 *
 * It composes the shared primitives: SearchFilters (server-backed), ServiceDataState
 * (loading/error/empty distinguished — no empty-on-error), StatusBadge/PaymentBadge, and
 * maskPhone. Per-row status mutation reuses the real updateSubmissionStatus endpoint.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/router';
import * as api from '../../api/client';
import type { ApiFailure, FlowSubmissionItem } from '../../api/client';
import { Pagination, Select } from '../ui';
import StatusBadge, { PaymentBadge } from './StatusBadge';
import ServiceDataState from './ServiceDataState';
import SearchFilters, { type FilterDef, type SearchFiltersState } from './SearchFilters';
import { maskPhone } from './mask';

const PAGE_SIZE = 25;

/** Capability labels, keyed by flowCode prefix the backend stamps on a submission. */
const CAPABILITY_FILTERS: FilterDef = {
  key: 'flowCode', label: 'Capability',
  options: [
    { value: 'submit_request', label: 'Submit Request' },
    { value: 'amend_request', label: 'Amendment' },
    { value: 'drop_docs', label: 'Drop Docs' },
    { value: 'leave_review', label: 'Review' },
    { value: 'orders', label: 'Orders' },
    { value: 'shipments', label: 'Shipments' },
    { value: 'WD-F008-REFERRAL', label: 'Refer Someone' },
  ],
};
const STATUS_FILTER: FilterDef = {
  key: 'status', label: 'Status',
  options: [
    { value: 'new', label: 'New' },
    { value: 'open', label: 'Open' },
    { value: 'in_progress', label: 'In progress' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'closed', label: 'Closed' },
    { value: 'rejected', label: 'Rejected' },
  ],
};
const PAYMENT_FILTER: FilterDef = {
  key: 'paymentStatus', label: 'Payment',
  options: [
    { value: 'pending', label: 'Pending' },
    { value: 'captured', label: 'Captured' },
    { value: 'failed', label: 'Failed' },
    { value: 'refunded', label: 'Refunded' },
  ],
};

const ROW_STATUS_OPTIONS = STATUS_FILTER.options;

/** Fields a free-text search matches, client-side, within the server-filtered result. */
const matchesSearch = ( r: FlowSubmissionItem, q: string ): boolean => {
  if ( !q ) return true;
  const hay = [
    r.senderName, r.customerName, r.phone, r.customerUuid, r.orderId, r.orderNumber,
    r.orderReference, r.submissionNumber, r.requestId, r.referenceId, r.subject,
    r.invoiceId, r.paymentRefId, r.flowCode,
  ].filter( Boolean ).join( ' ' ).toLowerCase();
  return hay.includes( q.toLowerCase() );
};

const reference = ( r: FlowSubmissionItem ): string =>
  r.submissionNumber || r.requestId || r.referenceId || r.orderNumber || r.orderId || r.submissionId;

const ReferralDetails: React.FC<{ submission: FlowSubmissionItem }> = ( { submission } ) => {
  let form: Record<string, unknown> = {};
  try {
    const decoded = JSON.parse( submission.formData || '{}' );
    if ( decoded && typeof decoded === 'object' && !Array.isArray( decoded ) ) form = decoded;
  } catch { /* Keep the queue available even for historic malformed form data. */ }
  return (
    <details style={ { marginTop: 5 } }>
      <summary style={ { cursor: 'pointer', fontSize: 12 } }>Referral details</summary>
      <div style={ { marginTop: 6, maxWidth: 260, overflowWrap: 'anywhere', fontSize: 12 } }>
        <div><strong>Their name:</strong> { String( form.referred_name || '—' ) }</div>
        <div><strong>WhatsApp:</strong> { maskPhone( String( form.referred_whatsapp || '' ) ) }</div>
        <div style={ { whiteSpace: 'pre-wrap' } }><strong>Notes:</strong> { String( form.referral_details || '—' ) }</div>
        <div><strong>Permission to share:</strong> { form.permission_confirmed === true || form.permission_confirmed === 'true' ? 'Confirmed' : 'Unverified' }</div>
        <small>Referrer is the customer above. Sharing is not marketing consent.</small>
      </div>
    </details>
  );
};

const th: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#64748b', borderBottom: '1px solid #e2e8f0', whiteSpace: 'nowrap' };
const td: React.CSSProperties = { padding: '10px 12px', fontSize: 13, color: '#1a1a1a', borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle' };

export interface ResponsesQueueProps {
  /** Lock the capability filter to one value (used by a capability page embedding the queue). */
  lockCapability?: string;
}

const ResponsesQueue: React.FC<ResponsesQueueProps> = ( { lockCapability } ) => {
  const router = useRouter();
  const [rows, setRows] = useState<FlowSubmissionItem[]>( [] );
  const [loading, setLoading] = useState( true );
  const [failure, setFailure] = useState<ApiFailure | null>( null );
  const [partial, setPartial] = useState( false );
  const [page, setPage] = useState( 1 );
  const [filters, setFilters] = useState<SearchFiltersState>( {
    search: '', flowCode: lockCapability ?? '', status: '', paymentStatus: '',
  } );

  useEffect( () => {
    const raw = router.query.search;
    const value = Array.isArray( raw ) ? raw[ 0 ] : raw;
    if ( value ) setFilters( current => ( { ...current, search: value } ) );
  }, [ router.query.search ] );

  const load = useCallback( async () => {
    setLoading( true );
    const limit = 500;
    const { data, failures } = await api.collectApiFailures( () => api.listFlowSubmissions( {
      flowCode: filters.flowCode || undefined,
      status: filters.status || undefined,
      paymentStatus: filters.paymentStatus || undefined,
      limit,
    } ) );
    setRows( data );
    // A failed load must read as an error, never as "0 results".
    setFailure( data.length === 0 && failures.length ? failures[0] : null );
    // The submissions API returns a single page; flag when it is likely truncated.
    setPartial( data.length >= limit );
    setLoading( false );
    setPage( 1 );
  }, [filters.flowCode, filters.status, filters.paymentStatus] );

  useEffect( () => { load(); }, [load] );

  const filtered = useMemo(
    () => rows.filter( r => matchesSearch( r, filters.search ) ),
    [rows, filters.search],
  );
  const totalPages = Math.max( 1, Math.ceil( filtered.length / PAGE_SIZE ) );
  const pageRows = filtered.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const onStatusChange = async ( r: FlowSubmissionItem, status: string ) => {
    // Optimistic — revert on failure.
    const prev = r.status;
    setRows( rs => rs.map( x => x.submissionId === r.submissionId ? { ...x, status } : x ) );
    const res = await api.updateSubmissionStatus( r.submissionId, status );
    if ( !res.updated ) {
      setRows( rs => rs.map( x => x.submissionId === r.submissionId ? { ...x, status: prev } : x ) );
    }
  };

  const activeFilters = lockCapability
    ? [STATUS_FILTER, PAYMENT_FILTER]
    : [CAPABILITY_FILTERS, STATUS_FILTER, PAYMENT_FILTER];

  return (
    <div>
      <SearchFilters value={filters} onChange={setFilters} filters={activeFilters} />
      <ServiceDataState
        loading={loading}
        failure={failure}
        empty={filtered.length === 0}
        emptyLabel={filters.search || filters.status || filters.paymentStatus ? 'Nothing matches these filters' : 'No responses yet'}
        emptyIcon="order"
        partial={partial}
        onRetry={load}
      >
        <div className="service-responses-table" style={{ overflowX: 'auto', background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>Customer</th>
                <th style={th}>Capability</th>
                <th style={th}>Reference</th>
                <th style={th}>Status</th>
                <th style={th}>Payment</th>
                <th style={th}>Created</th>
                <th style={th}>Set status</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map( r => (
                <tr key={r.submissionId}>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{r.senderName || r.customerName || 'Unknown'}</div>
                    <div style={{ color: '#9ca3af', fontSize: 12 }}>
                      {maskPhone( r.phone )}{r.customerUuid ? ` · ${r.customerUuid.slice( 0, 8 )}` : ''}
                    </div>
                  </td>
                  <td style={td}>{( CAPABILITY_FILTERS.options.find( o => o.value === r.flowCode )?.label ) || r.flowCode || '—'}
                     {r.flowType === 'referral' && <ReferralDetails submission={r} />}</td>
                  <td style={td}><code style={{ fontSize: 12 }}>{reference( r )}</code></td>
                  <td style={td}><StatusBadge value={r.status} /></td>
                  <td style={td}>{r.paymentRequired || r.paymentStatus ? <PaymentBadge value={r.paymentStatus} /> : <span style={{ color: '#cbd5e1' }}>—</span>}</td>
                  <td style={td} title={new Date( r.createdAt ).toLocaleString()}>{new Date( r.createdAt ).toLocaleDateString()}</td>
                  <td style={td}>
                    <div style={{ minWidth: 140 }}>
                      <Select
                        options={ROW_STATUS_OPTIONS}
                        value={r.status}
                        onChange={v => { void onStatusChange( r, v ); }}
                        ariaLabel={`Set status for ${reference( r )}`}
                      />
                    </div>
                  </td>
                </tr>
              ) )}
            </tbody>
          </table>
        </div>

        <div className="service-responses-mobile">
          { pageRows.map( r => (
            <article className="service-response-card" key={ `mobile-${r.submissionId}` }>
              <div className="service-response-head">
                <div>
                  <strong>{ r.senderName || r.customerName || 'Unknown customer' }</strong>
                  <small>{ maskPhone( r.phone ) }{ r.customerUuid ? ` · ${r.customerUuid.slice( 0, 8 )}` : '' }</small>
                </div>
                <StatusBadge value={ r.status } />
              </div>
              <dl className="service-response-meta">
                <div>
                  <dt>Capability</dt>
                  <dd>{ CAPABILITY_FILTERS.options.find( o => o.value === r.flowCode )?.label || r.flowCode || '—' }</dd>
                </div>
                <div>
                  <dt>Reference</dt>
                  <dd><code>{ reference( r ) }</code></dd>
                </div>
                <div>
                  <dt>Payment</dt>
                  <dd>{ r.paymentRequired || r.paymentStatus ? <PaymentBadge value={ r.paymentStatus } /> : '—' }</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{ new Date( r.createdAt ).toLocaleDateString() }</dd>
                </div>
              </dl>
              {r.flowType === 'referral' && <ReferralDetails submission={r} />}
              <div className="service-response-action">
                <Select
                  label="Set status"
                  options={ ROW_STATUS_OPTIONS }
                  value={ r.status }
                  onChange={ v => { void onStatusChange( r, v ); } }
                />
              </div>
            </article>
          ) ) }
        </div>
        {totalPages > 1 && (
          <div style={{ marginTop: 16 }}>
            <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        )}
      </ServiceDataState>

      <style jsx global>{`
        .service-responses-mobile{display:none}
        @media(max-width:768px){
          .service-responses-table{display:none}
          .service-responses-mobile{display:flex;flex-direction:column;gap:12px}
          .service-response-card{
            min-width:0;padding:14px;background:#fff;border:1px solid var(--border);border-radius:14px
          }
          .service-response-head{
            display:flex;align-items:flex-start;justify-content:space-between;gap:10px
          }
          .service-response-head>div{min-width:0;display:flex;flex-direction:column;gap:3px}
          .service-response-head strong,
          .service-response-head small{overflow-wrap:anywhere}
          .service-response-head small{color:var(--text-muted);font-size:var(--text-xs)}
          .service-response-meta{
            display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0
          }
          .service-response-meta div{min-width:0}
          .service-response-meta dt{
            color:var(--text-muted);font-size:var(--text-xs);text-transform:uppercase;letter-spacing:.04em
          }
          .service-response-meta dd{
            margin:3px 0 0;color:var(--text);font-size:var(--text-sm);overflow-wrap:anywhere
          }
          .service-response-meta code{white-space:normal;overflow-wrap:anywhere}
          .service-response-action .ui-field{width:100% !important}
        }
        @media(max-width:340px){
          .service-response-meta{grid-template-columns:1fr}
        }
      `}</style>
    </div>
  );
};

export default ResponsesQueue;
