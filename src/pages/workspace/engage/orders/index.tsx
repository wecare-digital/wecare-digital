/**
 * Order Management Dashboard — [retired public path]/orders
 * ORDER-CENTRIC: Order ID is the central key across the system.
 * Shows all orders with linked submissions, payments, status history.
 * Supports: search, filter, detail panel, manual creation, Wix sync, status updates.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import MaybeLayout from '../../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../../components/SEO';
import Modal from '../../../../components/ui/Modal';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import EmptyState from '../../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';

const PAGE_SIZE = 20;
const ORDER_STATUSES = [ 'active', 'fulfilled', 'cancelled' ];
const PAYMENT_STATUSES = [ 'pending', 'captured', 'failed', 'refunded' ];
const SOURCES = [ 'wix', 'manual', 'shopify', 'flow' ];
const SUBMISSION_STATUSES = [ 'open', 'in_progress', 'resolved', 'closed', 'cancelled' ];

/*
 * The option lists, hoisted so they are not rebuilt per render. Each holds exactly the
 * <option> rows it replaced, in the same order, with the same values and the same visible
 * text - including the three '' placeholder rows the filters read as "no filter".
 */
const SOURCE_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Sources' },
  ...SOURCES.map( s => ( { value: s, label: s } ) ),
];
const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...ORDER_STATUSES.map( s => ( { value: s, label: s } ) ),
];
const PAYMENT_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Payments' },
  ...PAYMENT_STATUSES.map( s => ( { value: s, label: s } ) ),
];
const SOURCE_OPTIONS: SelectOption[] = SOURCES.map( s => ( { value: s, label: s } ) );
const ORDER_STATUS_OPTIONS: SelectOption[] = ORDER_STATUSES.map( s => ( { value: s, label: s } ) );
const SUBMISSION_STATUS_OPTIONS: SelectOption[] = SUBMISSION_STATUSES.map(
  s => ( { value: s, label: s.replace( /_/g, ' ' ) } )
);

/*
 * LAYOUT ONLY - the box is drawn by .ui-select-trigger. A width is needed wherever the
 * control is a flex child, because a native select sized itself to its WIDEST option while
 * the trigger shows the SELECTED one: without it the row re-flows every time it is used.
 */
const FILTER_STYLE: React.CSSProperties = { width: 170 };
const ROW_SELECT_STYLE: React.CSSProperties = { flex: '0 0 170px' };
const DETAIL_SELECT_STYLE: React.CSSProperties = { flex: '0 0 200px' };

// ── Helpers ──

// Both order-number shapes, because the Wix sync now mints the current one:
//
//   'WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST'  → 'A1B2C3D4'  legacy spaced
//   'WD-ORD-K4M7PQR9'                                  → 'K4M7PQR9'  current
//
// Without the prefix strip the current form has no ' - ' to split on and falls through to
// the first 8 characters, rendering as 'WD-ORD — WD-ORD-K' - the prefix twice and the only
// part that identifies the order cut off.
function extractShortId ( orderId: string ): string {
  if ( !orderId ) return '';
  const parts = orderId.split( ' - ' );
  if ( parts.length >= 2 ) return parts[ 1 ];
  if ( orderId.startsWith( 'WD-ORD-' ) && orderId.length > 7 ) return orderId.slice( 7 );
  return orderId.slice( 0, 8 );
}

function extractFriendlyDateTime ( orderId: string ): string {
  if ( !orderId ) return '';
  const parts = orderId.split( ' - ' );
  if ( parts.length < 4 ) return '';
  try
  {
    const datePart = parts[ 2 ].trim(); // "22-02-2026"
    const timePart = parts[ 3 ].trim(); // "17:43:01"
    const [ dd, mm, yyyy ] = datePart.split( '-' );
    const [ hh, mi ] = timePart.split( ':' );
    const months = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];
    const monthName = months[ parseInt( mm, 10 ) - 1 ] || mm;
    const h = parseInt( hh, 10 );
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h === 0 ? 12 : ( h > 12 ? h - 12 : h );
    return `${parseInt( dd, 10 )} ${monthName} ${yyyy}, ${h12}:${mi} ${ampm}`;
  } catch { return ''; }
}

function buildWdOrdDisplay ( orderId: string ): string {
  const short = extractShortId( orderId );
  const dt = extractFriendlyDateTime( orderId );
  if ( !short ) return orderId;
  return dt ? `WD-ORD — ${short} — ${dt}` : `WD-ORD — ${short}`;
}

function formatDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit' } );
}

function formatDateTime ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', {
    day: 'numeric', month: 'short', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  } );
}

function statusColor ( status: string ): { bg: string; fg: string } {
  const map: Record<string, { bg: string; fg: string }> = {
    active: { bg: '#dbeafe', fg: '#1e40af' }, fulfilled: { bg: '#d1f470', fg: '#1a3a2a' },
    cancelled: { bg: '#fee2e2', fg: '#991b1b' }, pending: { bg: '#fef3c7', fg: '#92400e' },
    captured: { bg: '#d1f470', fg: '#1a3a2a' }, paid: { bg: '#d1f470', fg: '#1a3a2a' },
    failed: { bg: '#fee2e2', fg: '#991b1b' }, refunded: { bg: '#f3e8ff', fg: '#6b21a8' },
    open: { bg: '#dbeafe', fg: '#1e40af' }, in_progress: { bg: '#fef3c7', fg: '#92400e' },
    resolved: { bg: '#d1fae5', fg: '#065f46' }, closed: { bg: '#f3f4f6', fg: '#374151' },
    none: { bg: '#f3f4f6', fg: '#6b7280' }, wix: { bg: '#e0e7ff', fg: '#3730a3' },
    manual: { bg: '#fef3c7', fg: '#92400e' }, shopify: { bg: '#d1fae5', fg: '#065f46' },
    flow: { bg: '#f3e8ff', fg: '#6b21a8' },
  };
  return map[ status ] || { bg: '#f3f4f6', fg: '#374151' };
}

function Badge ( { status }: { status: string } ) {
  const c = statusColor( status );
  return (
    <span style={ {
      display: 'inline-block', padding: '2px 8px', borderRadius: 9999,
      fontSize: 11, fontWeight: 600, background: c.bg, color: c.fg,
      whiteSpace: 'nowrap', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis',
    } }>
      { ( status || '—' ).replace( /_/g, ' ' ) }
    </span>
  );
}

function CopyableId ( { id, short }: { id: string; short?: string } ) {
  const display = short || extractShortId( id ) || id.slice( 0, 8 );
  const handleCopy = () => {
    navigator.clipboard.writeText( id ).catch( () => { } );
  };
  return (
    <span
      onClick={ handleCopy }
      title={ `Click to copy: ${id}` }
      style={ {
        fontFamily: 'monospace', fontSize: 13, fontWeight: 600, color: '#1a3a2a',
        cursor: 'pointer', borderBottom: '1px dashed #9ca3af',
        whiteSpace: 'nowrap',
      } }
    >
      { display }
    </span>
  );
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const OrdersPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();

  // Data
  const [ orders, setOrders ] = useState<api.Order[]>( [] );
  const [ loading, setLoading ] = useState( true );

  // Filters
  const [ search, setSearch ] = useState( '' );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ paymentFilter, setPaymentFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );

  // Detail panel
  const [ selectedOrder, setSelectedOrder ] = useState<api.Order | null>( null );
  const [ submissions, setSubmissions ] = useState<api.FlowSubmissionItem[]>( [] );
  const [ subsLoading, setSubsLoading ] = useState( false );
  const [ detailDocs, setDetailDocs ] = useState<api.Document[]>( [] );
  const [ detailHistory, setDetailHistory ] = useState<api.StatusHistoryEntry[]>( [] );

  // Create modal
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ createForm, setCreateForm ] = useState( {
    customerName: '', customerPhone: '', source: 'manual',
    itemsSummary: '', totalAmount: '', notes: '',
  } );

  // Sync
  const [ syncing, setSyncing ] = useState( false );

  // ── Data loading ──

  const loadOrders = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listOrders( {
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        search: search || undefined,
      } );
      setOrders( data.orders || [] );
    } catch
    {
      toast.error( 'Failed to load orders' );
    }
    setLoading( false );
  }, [ statusFilter, sourceFilter, search, toast ] );

  useEffect( () => { loadOrders(); }, [ loadOrders ] );

  // ── Detail panel ──

  const openDetail = useCallback( async ( order: api.Order ) => {
    setSelectedOrder( order );
    setSubsLoading( true );
    try
    {
      const [ subs, tracking ] = await Promise.all( [
        api.getOrderSubmissions( order.orderId ),
        api.getTrackingData( order.orderId ).catch( () => null ),
      ] );
      setSubmissions( subs );
      setDetailDocs( tracking?.documents || [] );
      setDetailHistory( tracking?.statusHistory || [] );
    } catch
    {
      setSubmissions( [] );
      setDetailDocs( [] );
      setDetailHistory( [] );
    }
    setSubsLoading( false );
  }, [] );

  // ── Actions ──

  const handleOrderStatusUpdate = async ( orderId: string, status: string ) => {
    const ok = await api.updateOrder( orderId, { status } );
    if ( ok ) { toast.success( `Order → ${status}` ); loadOrders(); }
    else toast.error( 'Update failed' );
  };

  const handleSubmissionStatusUpdate = async ( subId: string, status: string ) => {
    const result = await api.updateSubmissionStatus( subId, status );
    if ( result?.updated )
    {
      toast.success( `Request → ${status.replace( /_/g, ' ' )}` );
      if ( selectedOrder ) openDetail( selectedOrder );
    } else toast.error( 'Update failed' );
  };

  const handleSync = async () => {
    setSyncing( true );
    try
    {
      const result = await api.syncOrders();
      toast.success( result.message || 'Sync complete' );
      loadOrders();
    } catch { toast.error( 'Sync failed' ); }
    setSyncing( false );
  };

  const handleCreate = async () => {
    if ( !createForm.customerPhone ) { toast.error( 'Phone is required' ); return; }
    setCreating( true );
    const order = await api.createOrder( {
      customerName: createForm.customerName,
      customerPhone: createForm.customerPhone,
      source: createForm.source,
      notes: createForm.notes,
      status: 'active',
      paymentStatus: 'pending',
    } );
    if ( order )
    {
      toast.success( 'Order created' );
      setShowCreate( false );
      setCreateForm( { customerName: '', customerPhone: '', source: 'manual', itemsSummary: '', totalAmount: '', notes: '' } );
      loadOrders();
    } else toast.error( 'Failed to create order' );
    setCreating( false );
  };

  // ── Filtering + pagination ──

  const filtered = useMemo( () => {
    let result = orders;
    if ( paymentFilter ) result = result.filter( o => o.paymentStatus === paymentFilter );
    return result;
  }, [ orders, paymentFilter ] );

  const totalPages = Math.ceil( filtered.length / PAGE_SIZE );
  const paged = filtered.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.orders } />
      <div style={ { padding: '24px 32px', maxWidth: 1440 } }>

        {/* ── Header ── */ }
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>Order Management</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>
              { filtered.length } order{ filtered.length !== 1 ? 's' : '' } · Order ID is the central tracking key
            </p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" loading={ syncing } onClick={ handleSync }>Wix Sync</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>New Order</Button>
          </div>
        </div>

        {/* ── Filters ── */ }
        <div style={ { display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' } }>
          <input
            type="text" placeholder="Search order number, Wix ID, phone, or customer..."
            value={ search } onChange={ e => { setSearch( e.target.value ); setPage( 1 ); } }
            style={ { flex: 1, minWidth: 220, padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14 } }
          />
          <Select ariaLabel="Source" value={ sourceFilter }
            onChange={ v => { setSourceFilter( v ); setPage( 1 ); } }
            options={ SOURCE_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Order status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Payment status" value={ paymentFilter }
            onChange={ v => { setPaymentFilter( v ); setPage( 1 ); } }
            options={ PAYMENT_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        {/* ── Table ── */ }
        { filtered.length === 0 && !loading ? (
          <EmptyState icon="order" title="No orders found" description="Create a manual order or sync from Wix to get started." action={ { label: 'New Order', onClick: () => setShowCreate( true ) } } />
        ) : (
          <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' } }>
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', minWidth: 900 } }>
                <thead>
                  <tr style={ { background: '#f9fafb' } }>
                    <th style={ thStyle }>Order ID</th>
                    <th style={ thStyle }>Date</th>
                    <th style={ thStyle }>Customer</th>
                    <th style={ thStyle }>Source</th>
                    <th style={ thStyle }>Items</th>
                    <th style={ thStyle }>Status</th>
                    <th style={ thStyle }>Payment</th>
                    <th style={ thStyle }>Requests</th>
                  </tr>
                </thead>
                <tbody>
                  { loading ? (
                    <tr><td colSpan={ 8 } style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>Loading orders...</td></tr>
                  ) : paged.map( order => {
                    const short = order.orderNumber || order.shortId || extractShortId( order.orderId );
                    return (
                      <tr key={ order.orderId } style={ { borderBottom: '1px solid #f3f4f6', cursor: 'pointer' } } onClick={ () => openDetail( order ) }>
                        <td style={ tdStyle }>
                          <CopyableId id={ order.orderId } short={ short } />
                        </td>
                        <td style={ { ...tdStyle, fontSize: 13, whiteSpace: 'nowrap' } }>{ formatDate( order.createdAt ) }</td>
                        <td style={ tdStyle }>
                          <div style={ { fontWeight: 500, fontSize: 14 } }>{ order.customerName || '—' }</div>
                          <div style={ { fontSize: 12, color: '#6b7280', fontFamily: 'monospace' } }>{ order.customerPhone || '' }</div>
                        </td>
                        <td style={ tdStyle }><Badge status={ order.source } /></td>
                        <td style={ { ...tdStyle, fontSize: 13 } }>{ order.itemCount ?? order.items?.length ?? '—' }</td>
                        <td style={ tdStyle }><Badge status={ order.status } /></td>
                        <td style={ tdStyle }><Badge status={ order.paymentStatus } /></td>
                        <td style={ { ...tdStyle, fontSize: 13, textAlign: 'center' } }>{ order.requestCount ?? '—' }</td>
                      </tr>
                    );
                  } ) }
                </tbody>
              </table>
            </div>
          </div>
        ) }
        { totalPages > 1 && (
          <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }>
            <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
          </div>
        ) }

        {/* ── Order Detail Panel ── */ }
        <Modal isOpen={ !!selectedOrder } onClose={ () => setSelectedOrder( null ) } title="Order Details" size="xl">
          { selectedOrder && <OrderDetailPanel order={ selectedOrder } submissions={ submissions } subsLoading={ subsLoading } documents={ detailDocs } statusHistory={ detailHistory } onStatusUpdate={ handleOrderStatusUpdate } onSubmissionStatusUpdate={ handleSubmissionStatusUpdate } /> }
        </Modal>

        {/* ── Create Order Modal ── */ }
        <Modal isOpen={ showCreate } onClose={ () => setShowCreate( false ) } title="Create Manual Order" size="md" footer={
          <><Button variant="secondary" onClick={ () => setShowCreate( false ) }>Cancel</Button><Button variant="primary" loading={ creating } onClick={ handleCreate }>Create Order</Button></>
        }>
          <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
            <label style={ labelStyle }>Customer Name<input type="text" value={ createForm.customerName } onChange={ e => setCreateForm( f => ( { ...f, customerName: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ labelStyle }>Phone *<input type="text" value={ createForm.customerPhone } onChange={ e => setCreateForm( f => ( { ...f, customerPhone: e.target.value } ) ) } placeholder="+91..." style={ inputStyle } /></label>
            { /* SHAPE (a), design 5.2: the wrapping <label> is gone and Select owns the pair.
                 A <button> is a labelable element too, so leaving the wrapper would have
                 computed the name by walking its subtree - "Source wix" - and a label
                 forwards clicks to its control, which can double-activate a button. */ }
            <Select label="Source" value={ createForm.source }
              onChange={ v => setCreateForm( f => ( { ...f, source: v } ) ) }
              options={ SOURCE_OPTIONS } />
            <label style={ labelStyle }>Items Summary<input type="text" value={ createForm.itemsSummary } onChange={ e => setCreateForm( f => ( { ...f, itemsSummary: e.target.value } ) ) } placeholder="e.g. Black Tee × 1, White Cap × 2" style={ inputStyle } /></label>
            <label style={ labelStyle }>Total Amount (₹)<input type="number" value={ createForm.totalAmount } onChange={ e => setCreateForm( f => ( { ...f, totalAmount: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ labelStyle }>Admin Notes<textarea value={ createForm.notes } onChange={ e => setCreateForm( f => ( { ...f, notes: e.target.value } ) ) } rows={ 2 } style={ { ...inputStyle, resize: 'vertical' } } /></label>
          </div>
        </Modal>
      </div>
    </MaybeLayout>
  );
};

// ── Order Detail Panel (inside modal) ──

interface DetailProps {
  order: api.Order;
  submissions: api.FlowSubmissionItem[];
  subsLoading: boolean;
  documents: api.Document[];
  statusHistory: api.StatusHistoryEntry[];
  onStatusUpdate: ( orderId: string, status: string ) => void;
  onSubmissionStatusUpdate: ( subId: string, status: string ) => void;
}

const OrderDetailPanel: React.FC<DetailProps> = ( { order, submissions, subsLoading, documents, statusHistory, onStatusUpdate, onSubmissionStatusUpdate } ) => {
  const short = order.orderNumber || order.shortId || extractShortId( order.orderId );

  return (
    <div>
      {/* ── Section A: Order Details ── */ }
      <div style={ { marginBottom: 24 } }>
        <div style={ { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 } }>
          <span style={ { fontSize: 22, fontWeight: 700, fontFamily: 'monospace', color: '#1a3a2a' } }>{ short }</span>
          <Badge status={ order.status } />
          <Badge status={ order.paymentStatus } />
        </div>

        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 12 } }>
          <div><span style={ metaLabel }>Full Order ID</span><div style={ { fontSize: 12, fontFamily: 'monospace', wordBreak: 'break-all', color: '#374151' } }>{ order.orderId }</div></div>
          <div><span style={ metaLabel }>Customer</span><div style={ { fontWeight: 500 } }>{ order.customerName || '—' }</div></div>
          <div><span style={ metaLabel }>Phone</span><div style={ { fontFamily: 'monospace' } }>{ order.customerPhone || '—' }</div></div>
          { order.wixOrderId && <div><span style={ metaLabel }>Wix Order ID</span><div style={ { fontSize: 12, fontFamily: 'monospace', overflowWrap: 'anywhere' } }>{ order.wixOrderId }</div></div> }
          { order.referenceId && <div><span style={ metaLabel }>Payment reference</span><div style={ { fontFamily: 'monospace' } }>{ order.referenceId }</div></div> }
          <div><span style={ metaLabel }>Source</span><div><Badge status={ order.source } /></div></div>
          <div><span style={ metaLabel }>Created</span><div>{ formatDateTime( order.createdAt ) }</div></div>
          <div><span style={ metaLabel }>Amount</span><div style={ { fontWeight: 600 } }>{ ( order.paymentAmount ?? order.totalAmount ) !== undefined ? `₹${ order.paymentAmount ?? order.totalAmount }` : '—' }</div></div>
        </div>

        {/* Status controls */ }
        <div style={ { display: 'flex', gap: 12, padding: 12, background: '#f9fafb', borderRadius: 8 } }>
          { /* SHAPE (a) - wrapping <label> deleted, label passed. */ }
          <Select label="Order Status" value={ order.status }
            onChange={ v => onStatusUpdate( order.orderId, v ) }
            options={ ORDER_STATUS_OPTIONS } style={ DETAIL_SELECT_STYLE } />
        </div>
      </div>

      {/* ── Section B: Service Requests ── */ }
      <div style={ { marginBottom: 24 } }>
        <h3 style={ { fontSize: 16, fontWeight: 600, color: '#1a3a2a', marginBottom: 12 } }>
          Service Requests ({ submissions.length })
        </h3>
        { subsLoading ? (
          <p style={ { color: '#6b7280', fontSize: 14 } }>Loading requests...</p>
        ) : submissions.length === 0 ? (
          <p style={ { color: '#6b7280', fontSize: 14, padding: 16, background: '#f9fafb', borderRadius: 8 } }>No service requests linked to this order.</p>
        ) : (
          <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
            { submissions.map( sub => (
              <div key={ sub.submissionId } style={ {
                padding: 14, border: '1px solid #e5e7eb', borderRadius: 10,
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12,
              } }>
                <div style={ { flex: 1, minWidth: 0 } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } }>
                    <span style={ { fontFamily: 'monospace', fontWeight: 600, fontSize: 13 } }>
                      { sub.submissionNumber || sub.submissionId.slice( 0, 16 ) }
                    </span>
                    <Badge status={ sub.status } />
                    <Badge status={ sub.paymentStatus } />
                  </div>
                  <div style={ { fontSize: 14, fontWeight: 500, marginBottom: 2 } }>{ sub.subject || sub.requestType || '—' }</div>
                  <div style={ { fontSize: 12, color: '#6b7280' } }>
                    { sub.flowCode } · { sub.phone } · { formatDateTime( sub.createdAt ) }
                    { sub.paymentAmount ? ` · ₹${( sub.paymentAmount / 100 ).toFixed( 0 )}` : '' }
                  </div>
                </div>
                <Select
                  ariaLabel="Request status"
                  value={ sub.status || 'open' }
                  onChange={ v => onSubmissionStatusUpdate( sub.submissionId, v ) }
                  options={ SUBMISSION_STATUS_OPTIONS }
                  style={ ROW_SELECT_STYLE }
                />
              </div>
            ) ) }
          </div>
        ) }
      </div>

      {/* ── Section C: Documents ── */ }
      { documents.length > 0 && (
        <div style={ { marginBottom: 24 } }>
          <h3 style={ { fontSize: 16, fontWeight: 600, color: '#1a3a2a', marginBottom: 12 } }>
            Documents ({ documents.length })
          </h3>
          <div style={ { display: 'flex', flexDirection: 'column', gap: 6 } }>
            { documents.map( ( doc: any ) => (
              <div key={ doc.documentId } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', border: '1px solid #e5e7eb', borderRadius: 8 } }>
                <div>
                  <div style={ { fontWeight: 500, fontSize: 13 } }>{ doc.fileName || 'Document' }</div>
                  <div style={ { fontSize: 12, color: '#6b7280' } }>{ doc.type || doc.documentType || '—' } · { doc.source || doc.sourceType || '—' }</div>
                </div>
                <Badge status={ doc.status || doc.verificationStatus || 'uploaded' } />
              </div>
            ) ) }
          </div>
        </div>
      ) }

      {/* ── Section D: Status History ── */ }
      { statusHistory.length > 0 && (
        <div style={ { marginBottom: 24 } }>
          <h3 style={ { fontSize: 16, fontWeight: 600, color: '#1a3a2a', marginBottom: 12 } }>
            Status History ({ statusHistory.length })
          </h3>
          <div style={ { position: 'relative', paddingLeft: 20 } }>
            <div style={ { position: 'absolute', left: 6, top: 4, bottom: 4, width: 2, background: '#e5e7eb' } } />
            { statusHistory.slice( 0, 10 ).map( ( h: any, i: number ) => (
              <div key={ h.historyId || i } style={ { position: 'relative', paddingBottom: 14, paddingLeft: 16 } }>
                <div style={ { position: 'absolute', left: -14, top: 4, width: 10, height: 10, borderRadius: '50%', background: i === 0 ? '#1a3a2a' : '#d1d5db', border: '2px solid #fff' } } />
                <div style={ { fontSize: 13, fontWeight: 500, color: '#374151' } }>
                  { h.oldStatus && <><Badge status={ h.oldStatus } /> → </> }<Badge status={ h.newStatus } />
                </div>
                { h.notes && <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2 } }>{ h.notes }</div> }
                <div style={ { fontSize: 11, color: '#9ca3af', marginTop: 2 } }>{ formatDateTime( h.changedAt ) } · { h.changedByName || h.changedBy || 'system' }</div>
              </div>
            ) ) }
          </div>
        </div>
      ) }

      {/* ── Section E: Notes ── */ }
      { order.notes && (
        <div>
          <h3 style={ { fontSize: 16, fontWeight: 600, color: '#1a3a2a', marginBottom: 8 } }>Admin Notes</h3>
          <div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ order.notes }</div>
        </div>
      ) }
    </div>
  );
};

// ── Styles ──

const thStyle: React.CSSProperties = {
  padding: '12px 14px', textAlign: 'left', borderBottom: '1px solid #e5e7eb',
  fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase',
  whiteSpace: 'nowrap',
};
const tdStyle: React.CSSProperties = { padding: '12px 14px', fontSize: 14 };
/* `selectStyle` went with the last native select in this file - it only ever skinned one. */
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };
const labelStyle: React.CSSProperties = { fontSize: 14, display: 'block' };
const metaLabel: React.CSSProperties = { fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600, display: 'block', marginBottom: 2 };

export default OrdersPage;
