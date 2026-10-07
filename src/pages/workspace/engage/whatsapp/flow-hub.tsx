import React, { useState, useEffect, useMemo } from 'react';
import * as api from '../../../../api/client';
import { useToastContext } from '../../../../contexts/ToastContext';
import Spinner from '../../../../components/ui/Spinner';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { StatusBadge, MaskedPhone } from '../../../../components/wa';
import MaybeLayout from '../../../../components/MaybeLayout';

interface FlowHubProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const FLOW_TYPES = [ 'form_submit', 'order_management', 'interactive', 'data_collection', 'payment', 'booking', 'feedback' ];
const PAYMENT_STATUSES = [ 'none', 'pending', 'captured', 'failed', 'refunded' ];
const SUBMISSION_STATUSES = [ 'open', 'in_progress', 'resolved', 'closed', 'cancelled' ];

const FLOW_TYPE_OPTIONS: SelectOption[] = FLOW_TYPES.map( t => ( { value: t, label: t } ) );
const REGISTRY_STATUS_OPTIONS: SelectOption[] = [
  { value: 'DRAFT', label: 'DRAFT' },
  { value: 'PUBLISHED', label: 'PUBLISHED' },
  { value: 'DEPRECATED', label: 'DEPRECATED' },
];
/** The leading '' row is the placeholder ROW the old `<option value="">` was. */
const SUBMISSION_STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...SUBMISSION_STATUSES.map( s => ( { value: s, label: s } ) ),
];
const PAYMENT_STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Payment' },
  ...PAYMENT_STATUSES.map( s => ( { value: s, label: s } ) ),
];
/** Layout only: the filter rows are flex, and the trigger shows the SELECTED label. */
const FILTER_SELECT_STYLE: React.CSSProperties = { flex: '0 1 220px', minWidth: 0 };

function FlowHubPageBody ( { embedded }: FlowHubProps ) {
  const toast = useToastContext();
  const [ activeTab, setActiveTab ] = useState<'registry' | 'submissions' | 'payments' | 'stats' | 'journey' | 'health'>( 'registry' );

  // Registry state
  const [ registry, setRegistry ] = useState<api.FlowRegistryItem[]>( [] );
  const [ registryLoading, setRegistryLoading ] = useState( false );

  // Submissions state
  const [ submissions, setSubmissions ] = useState<api.FlowSubmissionItem[]>( [] );
  const [ subsLoading, setSubsLoading ] = useState( false );
  const [ subsFlowFilter, setSubsFlowFilter ] = useState( '' );
  const [ subsStatusFilter, setSubsStatusFilter ] = useState( '' );
  const [ subsPaymentFilter, setSubsPaymentFilter ] = useState( '' );
  const [ expandedSub, setExpandedSub ] = useState<string | null>( null );

  // Stats state
  const [ stats, setStats ] = useState<api.FlowSubmissionStats | null>( null );
  const [ statsLoading, setStatsLoading ] = useState( false );
  const [ statsFlowFilter, setStatsFlowFilter ] = useState( '' );

  // Customer Journey state
  const [ journeyPhone, setJourneyPhone ] = useState( '' );
  const [ journey, setJourney ] = useState<api.CustomerJourney | null>( null );
  const [ journeyLoading, setJourneyLoading ] = useState( false );

  // Version Health state
  const [ versionHealth, setVersionHealth ] = useState<api.FlowVersionHealth[]>( [] );
  const [ healthLoading, setHealthLoading ] = useState( false );
  const [ recommendedVersion, setRecommendedVersion ] = useState( '' );

  // SLA check state
  const [ slaRunning, setSlaRunning ] = useState( false );
  const [ slaResult, setSlaResult ] = useState<any>( null );

  // CSV export state
  const [ exporting, setExporting ] = useState( false );

  /* Derived from the FETCHED registry, so memoised on it rather than rebuilt inline. Shared by
     the submissions filter and the stats filter, which listed the same flows. */
  const flowFilterOptions: SelectOption[] = useMemo( () => [
    { value: '', label: 'All Flows' },
    ...registry.map( f => ( { value: f.flowCode, label: `${ f.flowCode } — ${ f.flowName }` } ) ),
  ], [ registry ] );

  // Register flow form
  const [ showRegForm, setShowRegForm ] = useState( false );
  const [ regForm, setRegForm ] = useState<Partial<api.FlowRegistryItem>>( {
    flowType: 'form_submit', status: 'DRAFT', flowVersion: '7.3', dataApiVersion: '4.0',
    requiresPayment: false, paymentAmount: 0, submissionPrefix: 'WD',
  } );

  const loadRegistry = async () => {
    setRegistryLoading( true );
    try { setRegistry( await api.listFlowRegistry() ); }
    catch ( e ) { console.error( e ); toast.error( 'Failed to load flow registry' ); }
    finally { setRegistryLoading( false ); }
  };

  const loadSubmissions = async () => {
    setSubsLoading( true );
    try
    {
      setSubmissions( await api.listFlowSubmissions( {
        flowCode: subsFlowFilter || undefined,
        status: subsStatusFilter || undefined,
        paymentStatus: subsPaymentFilter || undefined,
      } ) );
    } catch ( e ) { console.error( e ); toast.error( 'Failed to load submissions' ); }
    finally { setSubsLoading( false ); }
  };

  const loadStats = async () => {
    setStatsLoading( true );
    try { setStats( await api.getFlowSubmissionStats( statsFlowFilter || undefined ) ); }
    catch ( e ) { console.error( e ); }
    finally { setStatsLoading( false ); }
  };

  useEffect( () => { loadRegistry(); }, [] );
  useEffect( () => { if ( activeTab === 'submissions' ) loadSubmissions(); }, [ activeTab, subsFlowFilter, subsStatusFilter, subsPaymentFilter ] );
  useEffect( () => { if ( activeTab === 'stats' || activeTab === 'payments' ) loadStats(); }, [ activeTab, statsFlowFilter ] );

  const loadJourney = async () => {
    if ( !journeyPhone ) { toast.error( 'Enter a phone number' ); return; }
    setJourneyLoading( true );
    try { setJourney( await api.getCustomerJourney( journeyPhone ) ); }
    catch ( e ) { console.error( e ); toast.error( 'Failed to load journey' ); }
    finally { setJourneyLoading( false ); }
  };

  const loadVersionHealth = async () => {
    setHealthLoading( true );
    try
    {
      const data = await api.checkFlowVersionHealth();
      if ( data ) { setVersionHealth( data.flows || [] ); setRecommendedVersion( data.recommendedVersion || '' ); }
    } catch ( e ) { console.error( e ); }
    finally { setHealthLoading( false ); }
  };

  useEffect( () => { if ( activeTab === 'health' ) loadVersionHealth(); }, [ activeTab ] );

  const handleSlaCheck = async () => {
    setSlaRunning( true );
    try { const r = await api.runSlaCheck(); setSlaResult( r ); toast.success( 'SLA check complete' ); }
    catch ( e ) { console.error( e ); toast.error( 'SLA check failed' ); }
    finally { setSlaRunning( false ); }
  };

  const handleExportCsv = async () => {
    setExporting( true );
    try
    {
      const csv = await api.exportSubmissionsCsv( { flowCode: subsFlowFilter || undefined, paymentStatus: subsPaymentFilter || undefined } );
      if ( csv )
      {
        const blob = new Blob( [ csv ], { type: 'text/csv' } );
        const url = URL.createObjectURL( blob );
        const a = document.createElement( 'a' );
        a.href = url; a.download = `flow-submissions-${new Date().toISOString().slice( 0, 10 )}.csv`;
        a.click(); URL.revokeObjectURL( url );
        toast.success( 'CSV exported' );
      }
    } catch ( e ) { console.error( e ); toast.error( 'Export failed' ); }
    finally { setExporting( false ); }
  };

  const handleRegisterFlow = async () => {
    if ( !regForm.flowId || !regForm.flowCode || !regForm.flowName )
    {
      toast.error( 'Flow ID, Code, and Name are required' ); return;
    }
    const ok = await api.upsertFlowRegistry( regForm );
    if ( ok ) { toast.success( 'Flow registered' ); setShowRegForm( false ); loadRegistry(); }
    else toast.error( 'Failed to register flow' );
  };

  const formatPaise = ( p: number ) => `₹${( p / 100 ).toFixed( 0 )}`;
  const formatDate = ( ts: number ) => ts ? new Date( ts * 1000 ).toLocaleString( 'en-IN' ) : '—';
  const statusColor = ( s: string ) => {
    const m: Record<string, string> = { open: '#3b82f6', in_progress: '#f59e0b', resolved: '#10b981', closed: '#6b7280', cancelled: '#ef4444' };
    return m[ s ] || '#6b7280';
  };
  const payColor = ( s: string ) => {
    const m: Record<string, string> = { none: '#9ca3af', pending: '#f59e0b', captured: '#10b981', failed: '#ef4444', refunded: '#8b5cf6' };
    return m[ s ] || '#9ca3af';
  };

  return (
    <div style={ { padding: embedded ? 0 : '1.5rem' } }>
      { !embedded && <h2 style={ { marginBottom: '1rem' } }>Flows Hub</h2> }

      {/* Tabs */ }
      <div style={ { display: 'flex', gap: '0.5rem', marginBottom: '1rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.5rem' } }>
        { ( [ 'registry', 'submissions', 'payments', 'stats', 'journey', 'health' ] as const ).map( tab => (
          <button key={ tab } onClick={ () => setActiveTab( tab ) }
            style={ {
              padding: '0.5rem 1rem', border: 'none', borderRadius: '0.375rem 0.375rem 0 0', cursor: 'pointer',
              background: activeTab === tab ? '#0f2a1d' : '#f3f4f6', color: activeTab === tab ? '#fff' : '#374151',
              fontWeight: activeTab === tab ? 600 : 400, fontSize: '0.85rem',
            } }>
            { tab === 'registry' ? 'Registry' : tab === 'submissions' ? 'Submissions' : tab === 'payments' ? 'Payments' : tab === 'stats' ? 'Analytics' : tab === 'journey' ? 'Journey' : 'Health' }
          </button>
        ) ) }
      </div>

      {/* Registry Tab */ }
      { activeTab === 'registry' && (
        <div>
          <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' } }>
            <span style={ { fontSize: '0.85rem', color: '#6b7280' } }>{ registry.length } flows registered</span>
            <div style={ { display: 'flex', gap: '0.5rem' } }>
              <button onClick={ loadRegistry } disabled={ registryLoading }
                style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fff' } }>
                { registryLoading ? 'Loading...' : 'Refresh' }
              </button>
              <button onClick={ () => setShowRegForm( !showRegForm ) }
                style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: 'none', borderRadius: '0.375rem', cursor: 'pointer', background: '#0f2a1d', color: '#fff' } }>
                + Register Flow
              </button>
            </div>
          </div>

          { showRegForm && (
            <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '1rem', marginBottom: '1rem' } }>
              <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem', fontSize: '0.8rem' } }>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Flow ID (Meta)</label>
                  <input value={ regForm.flowId || '' } onChange={ e => setRegForm( { ...regForm, flowId: e.target.value } ) }
                    placeholder="1484164182716509" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Flow Code</label>
                  <input value={ regForm.flowCode || '' } onChange={ e => setRegForm( { ...regForm, flowCode: e.target.value } ) }
                    placeholder="01.WD_SR" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Flow Name</label>
                  <input value={ regForm.flowName || '' } onChange={ e => setRegForm( { ...regForm, flowName: e.target.value } ) }
                    placeholder="Submit Request" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Flow Type</label>
                  <Select ariaLabel="Flow Type" value={ regForm.flowType || '' }
                    onChange={ v => setRegForm( { ...regForm, flowType: v } ) }
                    options={ FLOW_TYPE_OPTIONS } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>WABA ID</label>
                  <input value={ regForm.wabaId || '' } onChange={ e => setRegForm( { ...regForm, wabaId: e.target.value } ) }
                    placeholder="2094615664435155" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Submission Prefix</label>
                  <input value={ regForm.submissionPrefix || '' } onChange={ e => setRegForm( { ...regForm, submissionPrefix: e.target.value } ) }
                    placeholder="WD-SR" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Status</label>
                  <Select ariaLabel="Status" value={ regForm.status || 'DRAFT' }
                    onChange={ v => setRegForm( { ...regForm, status: v } ) }
                    options={ REGISTRY_STATUS_OPTIONS } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Preferred Gateway</label>
                  <input value={ ( regForm as any ).preferredGateway || '' } onChange={ e => setRegForm( { ...regForm, preferredGateway: e.target.value } as any ) }
                    placeholder="razorpay" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Payment Config Name</label>
                  <input value={ ( regForm as any ).paymentConfigName || '' } onChange={ e => setRegForm( { ...regForm, paymentConfigName: e.target.value } as any ) }
                    placeholder="WECAREDIGITAL" style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                </div>
                <div>
                  <label style={ { display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.2rem' } }>
                    <input type="checkbox" checked={ regForm.requiresPayment || false }
                      onChange={ e => setRegForm( { ...regForm, requiresPayment: e.target.checked } ) } />
                    Requires Payment
                  </label>
                </div>
                { regForm.requiresPayment && (
                  <div>
                    <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Amount (paise)</label>
                    <input type="number" value={ regForm.paymentAmount || 0 }
                      onChange={ e => setRegForm( { ...regForm, paymentAmount: parseInt( e.target.value ) || 0 } ) }
                      style={ { width: '100%', padding: '0.4rem', border: '1px solid #d1d5db', borderRadius: '0.25rem' } } />
                  </div>
                ) }
              </div>
              <div style={ { marginTop: '0.75rem', display: 'flex', gap: '0.5rem' } }>
                <button onClick={ handleRegisterFlow }
                  style={ { padding: '0.4rem 1rem', fontSize: '0.8rem', border: 'none', borderRadius: '0.375rem', cursor: 'pointer', background: '#10b981', color: '#fff' } }>
                  Save
                </button>
                <button onClick={ () => setShowRegForm( false ) }
                  style={ { padding: '0.4rem 1rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fff' } }>
                  Cancel
                </button>
              </div>
            </div>
          ) }

          { registryLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }

          { !registryLoading && registry.length > 0 && (
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' } }>
                <thead>
                  <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Code</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Name</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Type</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Version</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Status</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Payment</th>
                    <th style={ { padding: '8px 12px', textAlign: 'left' } }>Flow ID</th>
                  </tr>
                </thead>
                <tbody>
                  { registry.map( f => (
                    <tr key={ f.flowId } style={ { borderBottom: '1px solid #e5e7eb' } }>
                      <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontWeight: 600 } }>{ f.flowCode }</td>
                      <td style={ { padding: '8px 12px' } }>{ f.flowName }</td>
                      <td style={ { padding: '8px 12px' } }>
                        <span style={ { background: '#e0e7ff', color: '#3730a3', padding: '2px 8px', borderRadius: '9999px', fontSize: '0.7rem' } }>
                          { f.flowType }
                        </span>
                      </td>
                      <td style={ { padding: '8px 12px', fontFamily: 'monospace' } }>{ f.flowVersion || '—' }</td>
                      <td style={ { padding: '8px 12px' } }>
                        <StatusBadge status={ f.status } />
                      </td>
                      <td style={ { padding: '8px 12px' } }>
                        { f.requiresPayment ? formatPaise( f.paymentAmount || 0 ) : '—' }
                      </td>
                      <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '0.7rem', color: '#6b7280' } }>{ f.flowId }</td>
                    </tr>
                  ) ) }
                </tbody>
              </table>
            </div>
          ) }

          { !registryLoading && registry.length === 0 && (
            <div style={ { textAlign: 'center', padding: '3rem', color: '#9ca3af' } }>
              No flows registered yet. Click &quot;Register Flow&quot; to add your first flow.
            </div>
          ) }
        </div>
      ) }

      {/* Submissions Tab */ }
      { activeTab === 'submissions' && (
        <div>
          <div style={ { display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' } }>
            <Select ariaLabel="Filter by flow" value={ subsFlowFilter }
              onChange={ v => setSubsFlowFilter( v ) }
              options={ flowFilterOptions } style={ FILTER_SELECT_STYLE } />
            <Select ariaLabel="Filter by status" value={ subsStatusFilter }
              onChange={ v => setSubsStatusFilter( v ) }
              options={ SUBMISSION_STATUS_FILTER_OPTIONS } style={ FILTER_SELECT_STYLE } />
            <Select ariaLabel="Filter by payment status" value={ subsPaymentFilter }
              onChange={ v => setSubsPaymentFilter( v ) }
              options={ PAYMENT_STATUS_FILTER_OPTIONS } style={ FILTER_SELECT_STYLE } />
            <button onClick={ loadSubmissions } disabled={ subsLoading }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fff' } }>
              { subsLoading ? 'Loading...' : 'Refresh' }
            </button>
            <button onClick={ handleExportCsv } disabled={ exporting }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#f0fdf4', color: '#166534' } }>
              { exporting ? 'Exporting...' : '📥 CSV' }
            </button>
            <button onClick={ handleSlaCheck } disabled={ slaRunning }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fef3c7', color: '#92400e' } }>
              { slaRunning ? 'Running...' : '⏰ SLA Check' }
            </button>
            { slaResult && (
              <span style={ { fontSize: '0.75rem', color: '#6b7280', alignSelf: 'center' } }>
                Auto-assigned: { slaResult?.actions?.auto_assigned || 0 }, Escalated: { slaResult?.actions?.escalated || 0 }, Overdue: { slaResult?.actions?.overdue_payments || 0 }
              </span>
            ) }
            <span style={ { fontSize: '0.8rem', color: '#6b7280', alignSelf: 'center' } }>{ submissions.length } results</span>
          </div>

          { subsLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }

          { !subsLoading && submissions.length > 0 && (
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' } }>
                <thead>
                  <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Phone</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Flow</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Ref #</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Subject</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Status</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Payment</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Amount</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>WABA</th>
                    <th style={ { padding: '6px 10px', textAlign: 'left' } }>Date</th>
                  </tr>
                </thead>
                <tbody>
                  { submissions.map( s => {
                    // Determine WABA from flowToken
                    const ft = ( s as any ).flowToken || '';
                    const wabaLabel = ft.includes( '-waba-2-' ) ? 'Phone 2' : ft.includes( '-waba-1-' ) ? 'Phone 1' : '—';
                    const wabaColor = ft.includes( '-waba-2-' ) ? '#7c3aed' : ft.includes( '-waba-1-' ) ? '#2563eb' : '#9ca3af';
                    const d = s as any;
                    const isOpen = expandedSub === s.submissionId;
                    const attachments: any[] = Array.isArray( d.attachments ) ? d.attachments : [];
                    const addrParts = [ d.shippingAddress || d.addressLine1, d.landmark, d.city, d.state, d.postalCode || d.pin ]
                      .filter( Boolean );
                    return (
                      <React.Fragment key={ s.submissionId }>
                        <tr onClick={ () => setExpandedSub( isOpen ? null : s.submissionId ) }
                          style={ { borderBottom: '1px solid #f3f4f6', cursor: 'pointer', background: isOpen ? '#f5f3ff' : 'transparent' } }>
                          <td style={ { padding: '6px 10px', fontFamily: 'monospace' } }><MaskedPhone value={ s.phone } allowReveal /></td>
                          <td style={ { padding: '6px 10px' } }>
                            <span style={ { background: '#e0e7ff', color: '#3730a3', padding: '1px 6px', borderRadius: '9999px', fontSize: '0.7rem' } }>
                              { s.flowCode }
                            </span>
                          </td>
                          <td style={ { padding: '6px 10px', fontFamily: 'monospace', fontSize: '0.7rem' } }>{ ( d.requestId || s.submissionNumber ) || '—' }</td>
                          <td style={ { padding: '6px 10px' } }>{ s.subject || s.requestType || d.product || '—' }</td>
                          <td style={ { padding: '6px 10px' } }>
                            <span style={ { color: statusColor( s.status ), fontWeight: 600, fontSize: '0.75rem' } }>{ s.status }</span>
                          </td>
                          <td style={ { padding: '6px 10px' } }>
                            <span style={ { color: payColor( s.paymentStatus ), fontWeight: 600, fontSize: '0.75rem' } }>{ s.paymentStatus }</span>
                          </td>
                          <td style={ { padding: '6px 10px' } }>{ s.paymentAmount ? formatPaise( s.paymentAmount ) : '—' }</td>
                          <td style={ { padding: '6px 10px' } }>
                            <span style={ { color: wabaColor, fontWeight: 600, fontSize: '0.7rem' } }>{ wabaLabel }</span>
                          </td>
                          <td style={ { padding: '6px 10px', fontSize: '0.7rem', color: '#6b7280' } }>{ formatDate( s.createdAt ) }{ isOpen ? ' ▲' : ' ▼' }</td>
                        </tr>
                        { isOpen && (
                          <tr style={ { background: '#faf5ff' } }>
                            <td colSpan={ 9 } style={ { padding: '10px 16px', borderBottom: '2px solid #e5e7eb' } }>
                              <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px', fontSize: '0.78rem' } }>
                                <div><b>Request ID:</b> { d.requestId || s.submissionNumber || '—' }</div>
                                <div><b>Customer:</b> { d.customerName || '—' }</div>
                                <div style={ { gridColumn: '1 / -1' } }><b>Address:</b> { addrParts.length ? addrParts.join( ', ' ) : '—' }</div>
                                <div style={ { gridColumn: '1 / -1' } }><b>Description:</b> { d.description || '—' }</div>
                                <div><b>Preferred time:</b> { d.preferredTime || '—' }</div>
                                <div><b>Order #:</b> { d.orderNumber || d.referenceId || '—' }</div>
                              </div>
                              <div style={ { marginTop: 10 } }>
                                <b style={ { fontSize: '0.78rem' } }>Attachments { attachments.length ? `(${attachments.length})` : '' }:</b>
                                { attachments.length === 0 && <span style={ { color: '#9ca3af', fontSize: '0.75rem', marginLeft: 6 } }>none</span> }
                                <div style={ { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 } }>
                                  { attachments.map( ( a: any, i: number ) => {
                                    const url = typeof a === 'string' ? a : ( a.url || a.link || '' );
                                    const isImg = /\.(png|jpe?g|gif|webp)(\?|$)/i.test( url ) || ( a.type || '' ).startsWith( 'image' );
                                    return isImg
                                      ? <a key={ i } href={ url } target="_blank" rel="noreferrer"><img src={ url } alt="attachment" style={ { width: 72, height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #e5e7eb' } } /></a>
                                      : <a key={ i } href={ url } target="_blank" rel="noreferrer" style={ { fontSize: '0.75rem', color: '#7c3aed', textDecoration: 'underline' } }>{ ( a.filename || a.name || `File ${i + 1}` ) }</a>;
                                  } ) }
                                </div>
                              </div>
                            </td>
                          </tr>
                        ) }
                      </React.Fragment>
                    );
                  } ) }
                </tbody>
              </table>
            </div>
          ) }

          { !subsLoading && submissions.length === 0 && (
            <div style={ { textAlign: 'center', padding: '3rem', color: '#9ca3af' } }>No submissions found.</div>
          ) }
        </div>
      ) }

      {/* Payments Tab */ }
      { activeTab === 'payments' && (
        <div>
          { statsLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }
          { stats && (
            <>
              <div style={ { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' } }>
                <div style={ { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '0.5rem', padding: '1rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.5rem', fontWeight: 700, color: '#166534' } }>{ formatPaise( stats.capturedAmount ) }</div>
                  <div style={ { fontSize: '0.75rem', color: '#15803d' } }>Captured</div>
                </div>
                <div style={ { background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '0.5rem', padding: '1rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.5rem', fontWeight: 700, color: '#92400e' } }>{ formatPaise( stats.pendingAmount ) }</div>
                  <div style={ { fontSize: '0.75rem', color: '#b45309' } }>Pending</div>
                </div>
                <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '1rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.5rem', fontWeight: 700, color: '#374151' } }>{ stats.total }</div>
                  <div style={ { fontSize: '0.75rem', color: '#6b7280' } }>Total Submissions</div>
                </div>
                <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '1rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.5rem', fontWeight: 700, color: '#374151' } }>
                    { stats.byPaymentStatus?.captured || 0 }/{ ( stats.byPaymentStatus?.captured || 0 ) + ( stats.byPaymentStatus?.pending || 0 ) }
                  </div>
                  <div style={ { fontSize: '0.75rem', color: '#6b7280' } }>Conversion</div>
                </div>
              </div>

              <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' } }>
                <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '1rem' } }>
                  <div style={ { fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.85rem' } }>By Status</div>
                  { Object.entries( stats.byStatus ).map( ( [ k, v ] ) => (
                    <div key={ k } style={ { display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', fontSize: '0.8rem' } }>
                      <span style={ { color: statusColor( k ) } }>{ k }</span>
                      <span style={ { fontWeight: 600 } }>{ v }</span>
                    </div>
                  ) ) }
                </div>
                <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '1rem' } }>
                  <div style={ { fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.85rem' } }>By Payment</div>
                  { Object.entries( stats.byPaymentStatus ).map( ( [ k, v ] ) => (
                    <div key={ k } style={ { display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', fontSize: '0.8rem' } }>
                      <span style={ { color: payColor( k ) } }>{ k }</span>
                      <span style={ { fontWeight: 600 } }>{ v }</span>
                    </div>
                  ) ) }
                </div>
              </div>
            </>
          ) }
        </div>
      ) }

      {/* Stats/Analytics Tab */ }
      { activeTab === 'stats' && (
        <div>
          <div style={ { display: 'flex', gap: '0.5rem', marginBottom: '1rem' } }>
            <Select ariaLabel="Filter by flow" value={ statsFlowFilter }
              onChange={ v => setStatsFlowFilter( v ) }
              options={ flowFilterOptions } style={ FILTER_SELECT_STYLE } />
            <button onClick={ loadStats } disabled={ statsLoading }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fff' } }>
              { statsLoading ? 'Loading...' : 'Refresh' }
            </button>
          </div>
          { statsLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }
          { stats && !statsLoading && (
            <div style={ { fontSize: '0.85rem', color: '#374151' } }>
              <p>Total submissions: { stats.total }</p>
              <p>Captured revenue: { formatPaise( stats.capturedAmount ) }</p>
              <p>Pending revenue: { formatPaise( stats.pendingAmount ) }</p>
            </div>
          ) }
        </div>
      ) }

      {/* Customer Journey Tab */ }
      { activeTab === 'journey' && (
        <div>
          <div style={ { display: 'flex', gap: '0.5rem', marginBottom: '1rem' } }>
            <input value={ journeyPhone } onChange={ e => setJourneyPhone( e.target.value ) }
              placeholder="Phone number (e.g. 919876543210)"
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.25rem', width: '250px' } }
              onKeyDown={ e => e.key === 'Enter' && loadJourney() } />
            <button onClick={ loadJourney } disabled={ journeyLoading }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: 'none', borderRadius: '0.375rem', cursor: 'pointer', background: '#0f2a1d', color: '#fff' } }>
              { journeyLoading ? 'Loading...' : 'View Journey' }
            </button>
          </div>
          { journeyLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }
          { journey && !journeyLoading && (
            <div>
              <div style={ { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1rem' } }>
                <div style={ { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '0.5rem', padding: '0.75rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.25rem', fontWeight: 700 } }>{ journey.summary.totalSubmissions }</div>
                  <div style={ { fontSize: '0.7rem', color: '#6b7280' } }>Submissions</div>
                </div>
                <div style={ { background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '0.5rem', padding: '0.75rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.25rem', fontWeight: 700 } }>{ journey.summary.flowsCompleted.length }</div>
                  <div style={ { fontSize: '0.7rem', color: '#6b7280' } }>Flows Used</div>
                </div>
                <div style={ { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '0.5rem', padding: '0.75rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.25rem', fontWeight: 700 } }>{ formatPaise( journey.summary.totalPaid ) }</div>
                  <div style={ { fontSize: '0.7rem', color: '#6b7280' } }>Total Paid</div>
                </div>
                <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '0.75rem', textAlign: 'center' } }>
                  <div style={ { fontSize: '1.25rem', fontWeight: 700 } }>{ journey.summary.totalInteractions }</div>
                  <div style={ { fontSize: '0.7rem', color: '#6b7280' } }>Interactions</div>
                </div>
              </div>
              { journey.contact && Object.keys( journey.contact ).length > 0 && (
                <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '0.5rem', padding: '0.75rem', marginBottom: '1rem', fontSize: '0.8rem' } }>
                  <div style={ { fontWeight: 600, marginBottom: '0.5rem' } }>Contact Profile</div>
                  <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.25rem' } }>
                    { journey.contact.name && <span>Name: { journey.contact.name }</span> }
                    { journey.contact.email && <span>Email: { journey.contact.email }</span> }
                    { journey.contact.city && <span>City: { journey.contact.city }</span> }
                    { journey.contact.pincode && <span>Pincode: { journey.contact.pincode }</span> }
                    { journey.contact.companyName && <span>Company: { journey.contact.companyName }</span> }
                  </div>
                </div>
              ) }
              { journey.submissions.length > 0 && (
                <div style={ { marginBottom: '1rem' } }>
                  <div style={ { fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' } }>Submissions ({ journey.submissions.length })</div>
                  <div style={ { overflowX: 'auto' } }>
                    <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' } }>
                      <thead><tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Flow</th>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Ref</th>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Subject</th>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Status</th>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Payment</th>
                        <th style={ { padding: '6px 8px', textAlign: 'left' } }>Date</th>
                      </tr></thead>
                      <tbody>{ journey.submissions.map( s => (
                        <tr key={ s.submissionId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                          <td style={ { padding: '4px 8px' } }><span style={ { background: '#e0e7ff', color: '#3730a3', padding: '1px 6px', borderRadius: '9999px', fontSize: '0.7rem' } }>{ s.flowCode }</span></td>
                          <td style={ { padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.7rem' } }>{ s.submissionNumber || '—' }</td>
                          <td style={ { padding: '4px 8px' } }>{ s.subject || s.requestType || '—' }</td>
                          <td style={ { padding: '4px 8px', color: statusColor( s.status ), fontWeight: 600, fontSize: '0.75rem' } }>{ s.status }</td>
                          <td style={ { padding: '4px 8px', color: payColor( s.paymentStatus ), fontWeight: 600, fontSize: '0.75rem' } }>{ s.paymentStatus }</td>
                          <td style={ { padding: '4px 8px', fontSize: '0.7rem', color: '#6b7280' } }>{ formatDate( s.createdAt ) }</td>
                        </tr>
                      ) ) }</tbody>
                    </table>
                  </div>
                </div>
              ) }
              <div style={ { fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' } }>Flows Used: { journey.summary.flowsCompleted.join( ', ' ) || 'None' }</div>
            </div>
          ) }
          { !journey && !journeyLoading && (
            <div style={ { textAlign: 'center', padding: '3rem', color: '#9ca3af' } }>Enter a phone number to view the customer&apos;s complete flow journey.</div>
          ) }
        </div>
      ) }

      {/* Version Health Tab */ }
      { activeTab === 'health' && (
        <div>
          <div style={ { display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' } }>
            <button onClick={ loadVersionHealth } disabled={ healthLoading }
              style={ { padding: '0.4rem 0.8rem', fontSize: '0.8rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', cursor: 'pointer', background: '#fff' } }>
              { healthLoading ? 'Checking...' : 'Check Health' }
            </button>
            { recommendedVersion && <span style={ { fontSize: '0.8rem', color: '#6b7280' } }>Recommended: v{ recommendedVersion }</span> }
          </div>
          { healthLoading && <div style={ { textAlign: 'center', padding: '2rem' } }><Spinner size="lg" /></div> }
          { !healthLoading && versionHealth.length > 0 && (
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' } }>
                <thead><tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                  <th style={ { padding: '8px 12px', textAlign: 'left' } }>Flow</th>
                  <th style={ { padding: '8px 12px', textAlign: 'left' } }>Version</th>
                  <th style={ { padding: '8px 12px', textAlign: 'left' } }>Data API</th>
                  <th style={ { padding: '8px 12px', textAlign: 'left' } }>Status</th>
                  <th style={ { padding: '8px 12px', textAlign: 'left' } }>Action</th>
                </tr></thead>
                <tbody>{ versionHealth.map( f => (
                  <tr key={ f.flowId } style={ { borderBottom: '1px solid #e5e7eb', background: f.versionStatus === 'frozen' ? '#fef2f2' : f.versionStatus === 'outdated' ? '#fffbeb' : 'transparent' } }>
                    <td style={ { padding: '8px 12px' } }><span style={ { fontFamily: 'monospace', fontWeight: 600 } }>{ f.flowCode }</span> — { f.flowName }</td>
                    <td style={ { padding: '8px 12px', fontFamily: 'monospace' } }>{ f.flowVersion }</td>
                    <td style={ { padding: '8px 12px', fontFamily: 'monospace' } }>{ f.dataApiVersion }</td>
                    <td style={ { padding: '8px 12px' } }>
                      <span style={ {
                        padding: '2px 8px', borderRadius: '9999px', fontSize: '0.7rem', fontWeight: 600,
                        background: f.versionStatus === 'ok' ? '#d1fae5' : f.versionStatus === 'frozen' ? '#fee2e2' : '#fef3c7',
                        color: f.versionStatus === 'ok' ? '#065f46' : f.versionStatus === 'frozen' ? '#991b1b' : '#92400e',
                      } }>{ f.versionStatus.toUpperCase() }</span>
                    </td>
                    <td style={ { padding: '8px 12px', fontSize: '0.75rem', color: '#6b7280' } }>{ f.message }</td>
                  </tr>
                ) ) }</tbody>
              </table>
            </div>
          ) }
          { !healthLoading && versionHealth.length === 0 && (
            <div style={ { textAlign: 'center', padding: '3rem', color: '#9ca3af' } }>Click &quot;Check Health&quot; to scan all registered flows.</div>
          ) }
        </div>
      ) }
    </div>
  );
}
/** Shell-only view of the props: not all six pages declare these. */
type AnyShellProps = { user?: unknown; signOut?: () => void };


/**
 * Standalone shell. This page renders no chrome of its own - it was written as an
 * embedded tab body - so as a live route it had no sidebar, no breadcrumb and no
 * back link, and the sidebar was the only way out. MaybeLayout renders children
 * bare when `embedded`, so every hub that embeds it is unaffected.
 */
const FlowHubPage: React.FC<FlowHubProps> = ( props ) => (
  <MaybeLayout embedded={ props.embedded } user={ ( props as AnyShellProps ).user }
    onSignOut={ ( props as AnyShellProps ).signOut }>
    <FlowHubPageBody { ...props } />
  </MaybeLayout>
);

export default FlowHubPage;
