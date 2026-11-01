/**
 * WhatsApp Flow Responses
 * View submit requests and flow interaction logs from WhatsApp Flows
 * Supports per-flow filtering via flowCode dropdown
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { MaskedPhone } from '../../../components/wa';
import Select, { type SelectOption } from '../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

/* Two DIFFERENT status vocabularies on one page, and they are not interchangeable: the flow
   submissions view lists submission states, the legacy requests view lists request states.
   Both drove `statusFilter`, and both lists are reproduced exactly as their <option> rows were. */
const SUBMISSION_STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  { value: 'open', label: 'Open' },
  { value: 'awaiting_order_verification', label: 'Awaiting order verification' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
];
const PAYMENT_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Payment' },
  { value: 'none', label: 'No Payment' },
  { value: 'pending', label: 'Pending' },
  { value: 'captured', label: 'Captured' },
  { value: 'failed', label: 'Failed' },
];
const REQUEST_STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'paid', label: 'Paid' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];
/** Layout only: the filter rows are flex, and the trigger shows the SELECTED label. */
const FILTER_SELECT_STYLE: React.CSSProperties = { flex: '0 1 220px', minWidth: 0 };

const parseFormData = ( raw?: string ): Record<string, any> => {
  if ( !raw ) return {};
  try {
    const parsed = JSON.parse( raw );
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const F002_TOPIC_LABELS: Record<string, string> = {
  feature_request: "A feature I'd love",
  improvement: 'Something to improve',
  worked_well: 'Something I liked',
  other: 'Another thought',
};

const F002SubmissionDetails: React.FC<{ submission: api.FlowSubmissionItem }> = ( { submission } ) => {
  const data = parseFormData( submission.formData );
  const rows = [
    ...( data.topic && F002_TOPIC_LABELS[ data.topic ]
      ? [ [ "What's on your mind?", F002_TOPIC_LABELS[ data.topic ] ] as const ] : [] ),
    ...( data.idea ? [ [ 'Idea', String( data.idea ) ] as const ] : [] ),
  ];
  return <details>
    <summary style={ { cursor: 'pointer' } }>{ submission.subject || 'Leave Review' }</summary>
    { rows.length > 0 && <dl style={ { margin: '8px 0 0', display: 'grid', gridTemplateColumns: 'minmax(120px, 0.7fr) minmax(180px, 1.3fr)', gap: '4px 10px' } }>
      { rows.map( ( [ label, value ] ) => <React.Fragment key={ label }>
        <dt style={ { fontWeight: 600 } }>{ label }</dt>
        <dd style={ { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }>{ value }</dd>
      </React.Fragment> ) }
    </dl> }
    { rows.length === 0 && <p style={ { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }>{ submission.description }</p> }
    <p style={ { fontSize: 'var(--text-xs)' } }>{ submission.contactId ? "Linked to this sender's contact record." : 'Contact link unavailable' }</p>
    <p style={ { fontSize: 'var(--text-xs)' } }>Saved as a private Flow response.</p>
  </details>;
};

const F004SubmissionDetails: React.FC<{ submission: api.FlowSubmissionItem }> = ( { submission } ) => {
  const data = parseFormData( submission.formData );
  const target = String( data.selected_target || submission.orderId || submission.orderReference || '' )
    .replace( /^(order|request):/, '' );
  const note = String( data.note || data.description || submission.description || '' );
  return <details>
    <summary style={ { cursor: 'pointer' } }>{ submission.subject || 'Submit Request' }</summary>
    <dl style={ { margin: '8px 0 0', display: 'grid', gridTemplateColumns: 'minmax(120px, 0.7fr) minmax(180px, 1.3fr)', gap: '4px 10px' } }>
      { target && <><dt style={ { fontWeight: 600 } }>Linked to</dt><dd style={ { margin: 0, overflowWrap: 'anywhere' } }>{ target }</dd></> }
      { note && <><dt style={ { fontWeight: 600 } }>Note</dt><dd style={ { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }>{ note }</dd></> }
      <dt style={ { fontWeight: 600 } }>Request ID</dt>
      <dd style={ { margin: 0, fontFamily: 'monospace', overflowWrap: 'anywhere' } }>{ submission.submissionNumber || submission.submissionId }</dd>
    </dl>
  </details>;
};

const F008ReferralDetails: React.FC<{ submission: api.FlowSubmissionItem }> = ( { submission } ) => {
  const data = parseFormData( submission.formData );
  const number = String( data.referred_whatsapp || '' );
  const shared = data.permission_confirmed === true || data.permission_confirmed === 'true';
  return <details>
    <summary style={ { cursor: 'pointer' } }>{ String( data.referred_name || 'Referral details' ) }</summary>
    <dl style={ { margin: '8px 0 0', display: 'grid', gridTemplateColumns: 'minmax(120px, 0.7fr) minmax(180px, 1.3fr)', gap: '4px 10px' } }>
      <dt style={ { fontWeight: 600 } }>Their name</dt>
      <dd style={ { margin: 0, overflowWrap: 'anywhere' } }>{ String( data.referred_name || '—' ) }</dd>
      <dt style={ { fontWeight: 600 } }>Their WhatsApp number</dt>
      <dd style={ { margin: 0 } }>{ number ? <MaskedPhone value={ number } allowReveal /> : '—' }</dd>
      <dt style={ { fontWeight: 600 } }>Anything we should know?</dt>
      <dd style={ { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }>{ String( data.referral_details || '—' ) }</dd>
      <dt style={ { fontWeight: 600 } }>Permission to share number</dt>
      <dd style={ { margin: 0 } }>{ shared ? 'Confirmed by referrer' : 'Not confirmed' }</dd>
    </dl>
    <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
      Submitted by the WhatsApp sender. Sharing attestation is not marketing or outreach consent.
    </p>
  </details>;
};

/** The per-row Update control. `cancelled` is in this list and in no filter list. */
const SUBMISSION_STATUS_UPDATE_OPTIONS: SelectOption[] = [
  { value: 'awaiting_order_verification', label: 'Awaiting order verification' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
  { value: 'cancelled', label: 'Cancelled' },
];
const ROW_SELECT_STYLE: React.CSSProperties = { width: 150 };

/**
 * The per-row status control, and why it owns a piece of state rather than reading the row.
 *
 * It was UNCONTROLLED - React's uncontrolled default attribute, seeded from `s.status`, with an
 * async onChange and no variable behind it. The native element kept the operator's choice
 * across a parent re-render
 * on its own. A controlled Select has nothing to keep it, and the save is followed immediately
 * by `loadSubmissions()` - so pointing `value` at `s.status` would make the cell snap back to
 * whatever the list now says, including while the request is in flight and including when it
 * fails. That is the regression FlowResponseStatus.test.tsx pins.
 *
 * `setStatus` therefore runs BEFORE the save, and the row key is the submissionId, so this
 * state survives the re-render the refresh causes.
 */
const SubmissionStatusSelect: React.FC<{
  submissionId: string;
  initial: string;
  onSaved: () => void;
}> = ( { submissionId, initial, onSaved } ) => {
  const toast = useToastContext();
  const [ status, setStatus ] = useState( initial );
  const change = async ( next: string ) => {
    setStatus( next );
    try
    {
      await api.updateSubmissionStatus( submissionId, next );
      toast.success( `Status → ${next.replace( '_', ' ' )}` );
      onSaved();
    } catch ( err: any )
    {
      toast.error( err?.message || 'Update failed' );
    }
  };
  return (
    <Select ariaLabel="Update status" value={ status } onChange={ change }
      options={ SUBMISSION_STATUS_UPDATE_OPTIONS } style={ ROW_SELECT_STYLE } />
  );
};

const FlowResponsesPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ activeSection, setActiveSection ] = useState<'requests' | 'submissions' | 'logs'>( 'submissions' );
  const [ requests, setRequests ] = useState<api.SubmitRequest[]>( [] );
  const [ submissions, setSubmissions ] = useState<api.FlowSubmissionItem[]>( [] );
  const [ logs, setLogs ] = useState<api.FlowLog[]>( [] );
  const [ registry, setRegistry ] = useState<api.FlowRegistryItem[]>( [] );
  const [ requestsLoading, setRequestsLoading ] = useState( false );
  const [ subsLoading, setSubsLoading ] = useState( false );
  const [ logsLoading, setLogsLoading ] = useState( false );
  const [ phoneFilter, setPhoneFilter ] = useState( '' );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ flowCodeFilter, setFlowCodeFilter ] = useState( '' );
  const [ paymentFilter, setPaymentFilter ] = useState( '' );
  const [ requestsError, setRequestsError ] = useState<string | null>( null );
  const [ logsError, setLogsError ] = useState<string | null>( null );

  // Load flow registry for dropdown
  useEffect( () => {
    api.listFlowRegistry().then( setRegistry ).catch( () => { } );
  }, [] );

  /* Derived from the FETCHED registry, so memoised on it rather than rebuilt inline. */
  const flowCodeOptions: SelectOption[] = useMemo( () => [
    { value: '', label: 'All Flows' },
    ...registry.map( f => ( { value: f.flowCode, label: `${ f.flowCode } — ${ f.flowName }` } ) ),
    ...(registry.some(f => f.flowCode === 'WD_IDEA') ? [] : [{ value: 'WD_IDEA', label: 'Customer ideas' }]),
  ], [ registry ] );

  const loadRequests = useCallback( async () => {
    setRequestsLoading( true );
    setRequestsError( null );
    try
    {
      const data = await api.listSubmitRequests( statusFilter || undefined );
      setRequests( data );
    } catch ( e: any )
    {
      const msg = e?.message || 'Failed to load requests';
      setRequestsError( msg );
      toast.error( msg );
    }
    setRequestsLoading( false );
  }, [ statusFilter, toast ] );

  const loadSubmissions = useCallback( async () => {
    setSubsLoading( true );
    try
    {
      setSubmissions( await api.listFlowSubmissions( {
        flowCode: flowCodeFilter || undefined,
        status: statusFilter || undefined,
        paymentStatus: paymentFilter || undefined,
      } ) );
    } catch ( e: any )
    {
      toast.error( e?.message || 'Failed to load submissions' );
    }
    setSubsLoading( false );
  }, [ flowCodeFilter, statusFilter, paymentFilter, toast ] );

  const loadLogs = useCallback( async () => {
    setLogsLoading( true );
    setLogsError( null );
    try
    {
      const data = await api.listFlowLogs( phoneFilter || undefined );
      setLogs( data );
    } catch ( e: any )
    {
      const msg = e?.message || 'Failed to load flow logs';
      setLogsError( msg );
      toast.error( msg );
    }
    setLogsLoading( false );
  }, [ phoneFilter, toast ] );

  useEffect( () => {
    if ( activeSection === 'requests' ) loadRequests();
    else if ( activeSection === 'submissions' ) loadSubmissions();
    else loadLogs();
  }, [ activeSection, loadRequests, loadSubmissions, loadLogs ] );

  const formatDate = ( ts: number ) => {
    if ( !ts ) return '-';
    return new Date( ts * 1000 ).toLocaleString();
  };

  const getStatusBadge = ( status: string ) => {
    const colors: Record<string, string> = {
      pending: '#f59e0b', paid: '#10b981', captured: '#10b981', completed: '#10b981',
      failed: '#ef4444', expired: '#9ca3af', none: 'var(--text-muted)', open: '#3b82f6',
      in_progress: '#f59e0b', resolved: '#10b981', closed: 'var(--text-muted)', cancelled: '#ef4444',
      awaiting_order_verification: '#b45309',
    };
    return (
      <span style={ { padding: '2px 8px', borderRadius: 4, fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: colors[ status ] || 'var(--text-muted)' } }>
        { status === 'awaiting_order_verification' ? 'AWAITING ORDER VERIFICATION' : status?.toUpperCase() || 'UNKNOWN' }
      </span>
    );
  };

  const getWabaBadge = ( flowToken: string ) => {
    if ( !flowToken ) return <span style={ { color: '#9ca3af', fontSize: 'var(--text-xs)' } }>—</span>;
    const isPhone2 = flowToken.includes( '-waba-2-' );
    const isPhone1 = flowToken.includes( '-waba-1-' );
    if ( isPhone2 ) return <span style={ { padding: '2px 6px', borderRadius: 4, fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: '#7c3aed' } }>Phone 2</span>;
    if ( isPhone1 ) return <span style={ { padding: '2px 6px', borderRadius: 4, fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: '#2563eb' } }>Phone 1</span>;
    return <span style={ { padding: '2px 6px', borderRadius: 4, fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: '#9ca3af' } }>Legacy</span>;
  };

  const formatPaise = ( p: number ) => p ? `₹${( p / 100 ).toFixed( 0 )}` : '—';

  const content = (
    <>
      <SEO title="Flow Responses" description="WhatsApp Flow Responses & Logs" noindex />
      <div className="inner-page-container" style={ { background: '#fff' } }>
        <h2 style={ { margin: '0 0 16px', fontSize: 20 } }>Flow Responses</h2>

        {/* Section Tabs */ }
        <div style={ { display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' } }>
          { ( [ 'submissions', 'requests', 'logs' ] as const ).map( tab => (
            <button key={ tab } onClick={ () => setActiveSection( tab ) }
              style={ { padding: '8px 16px', borderRadius: 6, border: activeSection === tab ? '2px solid var(--accent)' : '1px solid #ddd', background: activeSection === tab ? 'var(--bg-secondary)' : '#fff', cursor: 'pointer', fontSize: 'var(--text-sm)', fontWeight: activeSection === tab ? 600 : 400 } }>
              { tab === 'submissions' ? `Flow Submissions (${submissions.length})` : tab === 'requests' ? `Legacy Requests (${requests.length})` : `Interaction Logs (${logs.length})` }
            </button>
          ) ) }
        </div>

        {/* FLOW SUBMISSIONS (new primary view) */ }
        { activeSection === 'submissions' && (
          <div>
            <div style={ { display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' } }>
              <Select ariaLabel="Filter by flow" value={ flowCodeFilter }
                onChange={ v => setFlowCodeFilter( v ) }
                options={ flowCodeOptions } style={ FILTER_SELECT_STYLE } />
              <Select ariaLabel="Filter by status" value={ statusFilter }
                onChange={ v => setStatusFilter( v ) }
                options={ SUBMISSION_STATUS_FILTER_OPTIONS } style={ FILTER_SELECT_STYLE } />
              <Select ariaLabel="Filter by payment status" value={ paymentFilter }
                onChange={ v => setPaymentFilter( v ) }
                options={ PAYMENT_FILTER_OPTIONS } style={ FILTER_SELECT_STYLE } />
              <button onClick={ loadSubmissions } disabled={ subsLoading }
                style={ { padding: '6px 14px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 'var(--text-sm)' } }>
                { subsLoading ? 'Loading...' : '↻ Refresh' }
              </button>
            </div>

            { subsLoading && submissions.length === 0 ? (
              <p style={ { textAlign: 'center', padding: 40, color: '#666' } }>Loading flow submissions...</p>
            ) : submissions.length === 0 ? (
              <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
                <p style={ { fontSize: 'var(--text-base)' } }>No flow submissions found</p>
                <p style={ { fontSize: 'var(--text-sm)' } }>Submissions appear here when users complete WhatsApp Flows</p>
              </div>
            ) : (
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
                  <thead>
                    <tr style={ { borderBottom: '2px solid var(--border)', textAlign: 'left' } }>
                      <th style={ { padding: '8px 10px' } }>Phone</th>
                      <th style={ { padding: '8px 10px' } }>Flow</th>
                      <th style={ { padding: '8px 10px' } }>Ref #</th>
                      <th style={ { padding: '8px 10px' } }>Subject</th>
                      <th style={ { padding: '8px 10px' } }>Status</th>
                      <th style={ { padding: '8px 10px' } }>Update</th>
                      <th style={ { padding: '8px 10px' } }>Payment</th>
                      <th style={ { padding: '8px 10px' } }>Amount</th>
                      <th style={ { padding: '8px 10px' } }>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    { submissions.map( s => (
                      <tr key={ s.submissionId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { padding: '8px 10px', fontFamily: 'monospace' } }><MaskedPhone value={ s.phone } allowReveal /></td>
                        <td style={ { padding: '8px 10px' } }>
                          <span style={ { background: '#e0e7ff', color: '#3730a3', padding: '1px 6px', borderRadius: 9999, fontSize: 'var(--text-xs)' } }>{ s.flowCode }</span>
                        </td>
                        <td style={ { padding: '8px 10px', fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ s.submissionNumber || '-' }</td>
                        <td style={ { padding: '8px 10px', maxWidth: 280 } }>
                          {s.flowType === 'referral' || s.flowCode === 'WD-F008-REFERRAL' ? (
                            <F008ReferralDetails submission={ s } />
                          ) : s.flowType === 'customer_idea' ? (
                            <F002SubmissionDetails submission={ s } />
                          ) : s.flowCode === '01.WD_SR' ? (
                            <F004SubmissionDetails submission={ s } />
                          ) : s.flowType === 'invoice_copy' ? (
                            <details>
                              <summary style={{ cursor: 'pointer' }}>Invoice copy</summary>
                              <p>Order: {s.orderNumber}</p>
                              <p>Customer ID: {s.customerUuid || 'Not available yet'}</p>
                              <p>Copy of the existing invoice. No new payment or invoice is created.</p>
                              <p>Delivery: {s.invoiceDeliveryStatus || 'Waiting for invoice preparation'}</p>
                              <p>{s.tags?.join(' · ')}</p>
                            </details>
                          ) : s.flowType === 'order_lookup' ? (
                            <details>
                              <summary style={{ cursor: 'pointer' }}>{s.subject || 'Help finding an order'}</summary>
                              <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{s.description}</p>
                              <p>Customer reference: {s.orderReference || 'Not provided'}</p>
                              <p>Customer ID: {s.customerUuid || 'Not available yet'}</p>
                              <p>No verified order is linked. Verify ownership before requesting a service payment.</p>
                              <p>{s.tags?.join(' · ')}</p>
                            </details>
                          ) : s.subject || s.requestType || '-'}
                        </td>
                        <td style={ { padding: '8px 10px' } }>{ getStatusBadge( s.status ) }</td>
                        <td style={ { padding: '8px 10px' } }>
                          <SubmissionStatusSelect
                            submissionId={ s.submissionId }
                            initial={ s.status || 'open' }
                            onSaved={ loadSubmissions }
                          />
                        </td>
                        <td style={ { padding: '8px 10px' } }>{ getStatusBadge( s.paymentStatus ) }</td>
                        <td style={ { padding: '8px 10px' } }>{ formatPaise( s.paymentAmount || 0 ) }</td>
                        <td style={ { padding: '8px 10px', fontSize: 'var(--text-xs)', color: '#666' } }>{ formatDate( s.createdAt ) }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            ) }
          </div>
        ) }

        {/* LEGACY SUBMIT REQUESTS */ }
        { activeSection === 'requests' && (
          <div>
            <div style={ { display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' } }>
              <Select ariaLabel="Filter by status" value={ statusFilter }
                onChange={ v => setStatusFilter( v ) }
                options={ REQUEST_STATUS_FILTER_OPTIONS } style={ FILTER_SELECT_STYLE } />
              <button onClick={ loadRequests } disabled={ requestsLoading }
                style={ { padding: '6px 14px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 'var(--text-sm)' } }>
                { requestsLoading ? 'Loading...' : '↻ Refresh' }
              </button>
            </div>

            { requestsLoading && requests.length === 0 ? (
              <p style={ { textAlign: 'center', padding: 40, color: '#666' } }>Loading submit requests...</p>
            ) : requestsError && requests.length === 0 ? (
              <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
                <p style={ { fontSize: 'var(--text-base)', color: 'var(--accent)' } }>Failed to load requests</p>
                <p style={ { fontSize: 'var(--text-sm)', marginTop: 8 } }>{ requestsError }</p>
                <button onClick={ loadRequests } style={ { marginTop: 12, padding: '8px 16px', background: 'var(--lime)', color: 'var(--accent)', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 'var(--text-sm)' } }>Retry</button>
              </div>
            ) : requests.length === 0 ? (
              <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
                <p style={ { fontSize: 'var(--text-base)' } }>No submit requests yet</p>
                <p style={ { fontSize: 'var(--text-sm)' } }>Requests appear here when users complete the WhatsApp Flow</p>
              </div>
            ) : (
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
                  <thead>
                    <tr style={ { borderBottom: '2px solid var(--border)', textAlign: 'left' } }>
                      <th style={ { padding: '8px 10px' } }>Phone</th>
                      <th style={ { padding: '8px 10px' } }>Name</th>
                      <th style={ { padding: '8px 10px' } }>Request #</th>
                      <th style={ { padding: '8px 10px' } }>Invoice #</th>
                      <th style={ { padding: '8px 10px' } }>Order ID</th>
                      <th style={ { padding: '8px 10px' } }>Subject</th>
                      <th style={ { padding: '8px 10px' } }>Payment</th>
                      <th style={ { padding: '8px 10px' } }>Amount</th>
                      <th style={ { padding: '8px 10px' } }>WABA</th>
                      <th style={ { padding: '8px 10px' } }>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    { requests.map( req => (
                      <tr key={ req.id } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { padding: '8px 10px', fontFamily: 'monospace' } }><MaskedPhone value={ req.phone } allowReveal /></td>
                        <td style={ { padding: '8px 10px' } }>{ req.senderName || '-' }</td>
                        <td style={ { padding: '8px 10px', fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ req.requestNumber || '-' }</td>
                        <td style={ { padding: '8px 10px', fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ req.invoiceNumber || '-' }</td>
                        <td style={ { padding: '8px 10px' } }>{ req.orderId || '-' }</td>
                        <td style={ { padding: '8px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ req.subject || '-' }</td>
                        <td style={ { padding: '8px 10px' } }>{ getStatusBadge( req.paymentStatus ) }</td>
                        <td style={ { padding: '8px 10px' } }>{ formatPaise( ( req as any ).paymentAmount || 0 ) }</td>
                        <td style={ { padding: '8px 10px' } }>{ getWabaBadge( ( req as any ).flowToken || '' ) }</td>
                        <td style={ { padding: '8px 10px', fontSize: 'var(--text-xs)', color: '#666' } }>{ formatDate( req.createdAt ) }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            ) }
          </div>
        ) }

        {/* FLOW INTERACTION LOGS */ }
        { activeSection === 'logs' && (
          <div>
            <div style={ { display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' } }>
              <input value={ phoneFilter } onChange={ e => setPhoneFilter( e.target.value ) } placeholder="Filter by phone..."
                style={ { padding: '6px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 'var(--text-sm)', width: 200 } } />
              <button onClick={ loadLogs } disabled={ logsLoading }
                style={ { padding: '6px 14px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 'var(--text-sm)' } }>
                { logsLoading ? 'Loading...' : '↻ Refresh' }
              </button>
            </div>

            { logsLoading && logs.length === 0 ? (
              <p style={ { textAlign: 'center', padding: 40, color: '#666' } }>Loading flow logs...</p>
            ) : logsError && logs.length === 0 ? (
              <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
                <p style={ { fontSize: 'var(--text-base)', color: 'var(--accent)' } }>Failed to load flow logs</p>
                <p style={ { fontSize: 'var(--text-sm)', marginTop: 8 } }>{ logsError }</p>
                <button onClick={ loadLogs } style={ { marginTop: 12, padding: '8px 16px', background: 'var(--lime)', color: 'var(--accent)', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 'var(--text-sm)' } }>Retry</button>
              </div>
            ) : logs.length === 0 ? (
              <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
                <p style={ { fontSize: 'var(--text-base)' } }>No flow interaction logs yet</p>
                <p style={ { fontSize: 'var(--text-sm)' } }>Logs appear here when users interact with WhatsApp Flows</p>
              </div>
            ) : (
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
                  <thead>
                    <tr style={ { borderBottom: '2px solid var(--border)', textAlign: 'left' } }>
                      <th style={ { padding: '8px 10px' } }>Phone</th>
                      <th style={ { padding: '8px 10px' } }>Action</th>
                      <th style={ { padding: '8px 10px' } }>Screen</th>
                      <th style={ { padding: '8px 10px' } }>Data</th>
                      <th style={ { padding: '8px 10px' } }>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    { logs.map( log => {
                      let parsedData: Record<string, any> | null = null;
                      try { if ( log.flowData ) parsedData = JSON.parse( log.flowData ); } catch { }
                      return (
                        <tr key={ log.id } style={ { borderBottom: '1px solid #f3f4f6' } }>
                          <td style={ { padding: '8px 10px', fontFamily: 'monospace' } }><MaskedPhone value={ log.phone } allowReveal /></td>
                          <td style={ { padding: '8px 10px' } }>
                            <span style={ { padding: '2px 8px', borderRadius: 4, fontSize: 'var(--text-xs)', background: log.action === 'INIT' ? 'var(--bg-secondary)' : log.action === 'data_exchange' ? 'var(--bg-secondary)' : '#f3f4f6' } }>
                              { log.action }
                            </span>
                          </td>
                          <td style={ { padding: '8px 10px' } }>{ log.screen || '-' }</td>
                          <td style={ { padding: '8px 10px', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 'var(--text-xs)', fontFamily: 'monospace' } }>
                            { parsedData ? Object.entries( parsedData ).map( ( [ k, v ] ) => `${k}: ${v}` ).join( ', ' ) : ( log.dataKeys?.join( ', ' ) || '-' ) }
                          </td>
                          <td style={ { padding: '8px 10px', fontSize: 'var(--text-xs)', color: '#666' } }>{ formatDate( log.createdAt ) }</td>
                        </tr>
                      );
                    } ) }
                  </tbody>
                </table>
              </div>
            ) }
          </div>
        ) }
      </div>
    </>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { content }
    </Layout>
  );
};

export default FlowResponsesPage;
