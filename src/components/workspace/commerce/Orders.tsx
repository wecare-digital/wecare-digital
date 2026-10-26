/**
 * Canonical Commerce Orders queue
 * ORDER-CENTRIC: Order ID is the central key across the system.
 * Shows all order sources with linked submissions, payment state, fulfilment and status history.
 * Supports search, filtering, detail panels, manual creation, and status updates.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/router';
import MaybeLayout from '../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Modal from '../../../components/ui/Modal';
import Button from '../../../components/ui/Button';
import Pagination from '../../../components/ui/Pagination';
import EmptyState from '../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import type { ApiFailure } from '../../../api/client';
import ErrorState from '../../../components/ErrorState';
import {
  allowedFulfilmentTargets,
  canonicalFulfilmentStatus,
  fulfilmentLabel,
  isSendableFulfilmentStatus,
  isWhatsAppOrder,
  orderStatusFailureText,
} from '../../../lib/orderFulfilment';
import { openExternal } from '../../../lib/capacitor';

const PAGE_SIZE = 20;
const ORDER_STATUSES = [ 'pending', 'processing', 'partially-shipped', 'shipped', 'completed', 'canceled' ];
const PAYMENT_STATUSES = [ 'pending', 'captured', 'failed', 'refunded' ];
const SOURCES = [ 'manual', 'flow', 'catalog', 'integration' ];
const SUBMISSION_STATUSES = [ 'open', 'in_progress', 'resolved', 'closed', 'cancelled' ];

type ManualTrackingPatch = Pick<api.OrderPatch, 'carrierName' | 'trackingNumber' | 'trackingUrl'>;

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
  { value: '', label: 'All fulfilment' },
  ...ORDER_STATUSES.map( value => ( { value, label: fulfilmentLabel( value ) } ) ),
];
const PAYMENT_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Payments' },
  ...PAYMENT_STATUSES.map( s => ( { value: s, label: s } ) ),
];
const SOURCE_OPTIONS: SelectOption[] = SOURCES.map( s => ( { value: s, label: s } ) );
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

// Support both legacy spaced and current compact WD order-number shapes.
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

function orderFulfilment ( order: api.Order ): string {
  return canonicalFulfilmentStatus( order.fulfillmentStatus || order.orderStatus || order.status, order.paymentStatus );
}

function fulfilmentOptions ( order: api.Order ): SelectOption[] {
  const current = orderFulfilment( order );
  return [
    { value: current, label: fulfilmentLabel( current ), disabled: true },
    ...allowedFulfilmentTargets( current, order.paymentStatus )
      .map( value => ( { value, label: fulfilmentLabel( value ) } ) ),
  ];
}

function canCancelOrder ( order: api.Order ): boolean {
  if ( orderFulfilment( order ) !== 'pending' ) return false;
  const payment = String( order.paymentStatus || '' ).trim().toLowerCase().replace( /-/g, '_' );
  return ![ 'authorized', 'authorised', 'captured', 'paid', 'payment_paid', 'refunded', 'disputed' ].includes( payment );
}

const RETURN_STAGE_LABELS: Record<string, string> = {
  requested: 'Requested',
  approved: 'Approved',
  rejected: 'Rejected',
  item_received: 'Item received',
  return_waived: 'Return waived',
  refund_eligible: 'Refund eligible',
};

function returnStageOptions ( sub: api.FlowSubmissionItem ): SelectOption[] {
  const current = String( sub.returnStage || 'requested' );
  const next: Record<string, api.ReturnStage[]> = {
    requested: [ 'approved', 'rejected' ],
    approved: [ 'item_received', 'return_waived' ],
    item_received: [ 'refund_eligible' ],
    return_waived: [ 'refund_eligible' ],
    refund_eligible: [],
    rejected: [],
  };
  return [
    { value: current, label: RETURN_STAGE_LABELS[ current ] || current.replace( /_/g, ' ' ), disabled: true },
    ...( next[ current ] || [] ).map( value => ( { value, label: RETURN_STAGE_LABELS[ value ] || value } ) ),
  ];
}

function formatDateTime ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', {
    day: 'numeric', month: 'short', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  } );
}

function safeTrackingUrl ( value?: string ): string | null {
  const raw = String( value || '' ).trim();
  if ( !raw || /\s/.test( raw ) || raw.includes( '\\' ) ) return null;
  try
  {
    const parsed = new URL( raw );
    if ( parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password ) return null;
    return parsed.toString();
  } catch
  {
    return null;
  }
}

function statusColor ( status: string ): { bg: string; fg: string } {
  const map: Record<string, { bg: string; fg: string }> = {
    active: { bg: '#dbeafe', fg: '#1e40af' }, fulfilled: { bg: 'var(--lime)', fg: 'var(--accent)' },
    cancelled: { bg: '#fee2e2', fg: '#991b1b' }, pending: { bg: '#fef3c7', fg: '#92400e' },
    processing: { bg: '#dbeafe', fg: '#1e40af' }, 'partially-shipped': { bg: '#e0e7ff', fg: '#3730a3' },
    shipped: { bg: '#cffafe', fg: '#155e75' }, completed: { bg: 'var(--lime)', fg: 'var(--accent)' },
    canceled: { bg: '#fee2e2', fg: '#991b1b' },
    captured: { bg: 'var(--lime)', fg: 'var(--accent)' }, paid: { bg: 'var(--lime)', fg: 'var(--accent)' },
    failed: { bg: '#fee2e2', fg: '#991b1b' }, refunded: { bg: '#f3e8ff', fg: '#6b21a8' },
    open: { bg: '#dbeafe', fg: '#1e40af' }, in_progress: { bg: '#fef3c7', fg: '#92400e' },
    resolved: { bg: '#d1fae5', fg: '#065f46' }, closed: { bg: '#f3f4f6', fg: '#374151' },
    none: { bg: '#f3f4f6', fg: 'var(--text-muted)' },
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
      fontSize: 'var(--text-xs)', fontWeight: 600, background: c.bg, color: c.fg,
      whiteSpace: 'nowrap', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis',
    } }>
      { fulfilmentLabel( status || '—' ) }
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
        fontFamily: 'monospace', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--accent)',
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
  const confirm = useConfirm();
  const router = useRouter();

  // Data
  const [ orders, setOrders ] = useState<api.Order[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ failure, setFailure ] = useState<ApiFailure | null>( null );

  // Filters
  const [ search, setSearch ] = useState( '' );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ paymentFilter, setPaymentFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );

  useEffect( () => {
    const raw = router.query.search;
    const value = Array.isArray( raw ) ? raw[ 0 ] : raw;
    if ( value ) { setSearch( value ); setPage( 1 ); }
  }, [ router.query.search ] );

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


  // ── Data loading ──

  const loadOrders = useCallback( async () => {
    setLoading( true );
    // A failed load must read as an error, not an empty "No orders found" table.
    const { data, failures } = await api.collectApiFailures( () => api.listOrders( {
      source: sourceFilter || undefined,
      search: search || undefined,
    } ) );
    const rows = data.orders || [];
    setOrders( rows );
    setFailure( rows.length === 0 && failures.length ? failures[ 0 ] : null );
    setLoading( false );
  }, [ sourceFilter, search, toast ] );

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
      if ( tracking?.order ) setSelectedOrder( tracking.order );
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

  // A WhatsApp-paid order's status lives on WhatsApp: the customer's Order summary shows only the
  // updates Meta was sent. So it changes through the invoice engine's send, which moves this order
  // once Meta accepts. `updateOrder` writes our row alone, and the server refuses it for these.
  const handleOrderStatusUpdate = async ( order: api.Order, status: string ) => {
    if ( isWhatsAppOrder( order.checkoutMode ) )
    {
      if ( !order.invoiceId )
      {
        toast.error( 'This WhatsApp order has no linked invoice, so its status cannot be sent. Nothing was changed.' );
        return;
      }
      if ( !isSendableFulfilmentStatus( status ) )
      {
        toast.error( `${ fulfilmentLabel( status ) } cannot be sent to WhatsApp. Nothing was changed.` );
        return;
      }
      const label = fulfilmentLabel( status );
      const confirmed = await confirm( {
        title: 'Send WhatsApp order update',
        message: `Send “${ label }” to the customer on WhatsApp? Their WhatsApp order page updates to match, and a sent update cannot be withdrawn.`,
        confirmText: `Send ${ label }`,
      } );
      if ( !confirmed ) return;
      const result = await api.sendOrderStatus( order.invoiceId, status );
      if ( result.ok ) { toast.success( `Order → ${ label }. The customer was notified on WhatsApp.` ); loadOrders(); }
      else toast.error( orderStatusFailureText( result.failure ) );
      return;
    }
    const ok = await api.updateOrder( order.orderId, { status } );
    if ( ok ) { toast.success( `Order → ${status}` ); loadOrders(); }
    else toast.error( 'Update failed' );
  };

  const handleTrackingUpdate = async ( orderId: string, tracking: ManualTrackingPatch ): Promise<boolean> => {
    const ok = await api.updateOrder( orderId, tracking );
    if ( !ok )
    {
      toast.error( 'Could not save shipment tracking' );
      return false;
    }

    toast.success( 'Manual shipment tracking saved' );
    const refreshed = await api.getTrackingData( orderId ).catch( () => null );
    if ( refreshed?.order ) setSelectedOrder( refreshed.order );
    if ( refreshed )
    {
      setDetailDocs( refreshed.documents || [] );
      setDetailHistory( refreshed.statusHistory || [] );
    }
    await loadOrders();
    return true;
  };

  const handleSubmissionStatusUpdate = async ( subId: string, status: string ) => {
    const result = await api.updateSubmissionStatus( subId, status );
    if ( result?.updated )
    {
      toast.success( `Request → ${status.replace( /_/g, ' ' )}` );
      if ( selectedOrder ) openDetail( selectedOrder );
    } else toast.error( 'Update failed' );
  };

  const handleOrderCancel = async ( orderId: string, reason: string ): Promise<boolean> => {
    try
    {
      const result = await api.cancelOrder( orderId, reason );
      if ( !result?.canceled ) { toast.error( 'Cancellation was not committed' ); return false; }
      toast.success( result.idempotent ? 'Order was already cancelled' : 'Order cancelled with audit history' );
      const refreshed = await api.getTrackingData( orderId ).catch( () => null );
      if ( refreshed?.order ) setSelectedOrder( refreshed.order );
      if ( refreshed )
      {
        setDetailDocs( refreshed.documents || [] );
        setDetailHistory( refreshed.statusHistory || [] );
      }
      await loadOrders();
      return true;
    } catch
    {
      toast.error( 'Cancellation refused. Reload the order and check payment / fulfilment state.' );
      return false;
    }
  };

  const handleReturnStageUpdate = async ( subId: string, stage: api.ReturnStage, notes?: string ): Promise<boolean> => {
    try
    {
      const result = await api.updateReturnStage( subId, stage, notes );
      if ( !result?.updated ) { toast.error( 'Return stage was not updated' ); return false; }
      toast.success( `Return → ${RETURN_STAGE_LABELS[ stage ] || stage.replace( /_/g, ' ' )}` );
      if ( selectedOrder ) await openDetail( selectedOrder );
      return true;
    } catch
    {
      toast.error( 'Return transition refused. Check the required sequence and reason.' );
      return false;
    }
  };

  const handleRefundInitiation = async (
    sub: api.FlowSubmissionItem,
    reason: string,
  ): Promise<boolean> => {
    const invoiceId = String( sub.invoiceId || '' ).trim();
    if ( !invoiceId )
    {
      toast.error( 'No verified invoice is linked to this return. Reconcile the invoice before refunding.' );
      return false;
    }

    const result = await api.initiateFullRefund( invoiceId, sub.submissionId, reason );
    if ( result.outcome === 'confirmed' )
    {
      toast.success( 'Refund confirmed' );
    }
    else if ( result.outcome === 'submitted' )
    {
      toast.success( 'Refund initiated; awaiting final payment status' );
    }
    else
    {
      toast.error( result.message || 'Refund initiation was refused' );
    }

    if ( selectedOrder ) await openDetail( selectedOrder );
    return result.outcome === 'submitted' || result.outcome === 'confirmed';
  };

  const handleCreate = async () => {
    if ( !createForm.customerPhone ) { toast.error( 'Phone is required' ); return; }
    setCreating( true );
    const order = await api.createOrder( {
      customerName: createForm.customerName,
      customerPhone: createForm.customerPhone,
      source: createForm.source,
      notes: createForm.notes,
      status: 'pending',
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
    if ( statusFilter ) result = result.filter( order => orderFulfilment( order ) === statusFilter );
    if ( paymentFilter ) result = result.filter( o => o.paymentStatus === paymentFilter );
    return result;
  }, [ orders, statusFilter, paymentFilter ] );

  const totalPages = Math.ceil( filtered.length / PAGE_SIZE );
  const paged = filtered.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.orders } />
      <div className="orders-workspace" style={ { padding: '24px 32px', maxWidth: 1440 } }>

        {/* ── Header ── */ }
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 } }>
          <div>
            <h1 style={ { fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--accent)', margin: 0 } }>Orders</h1>
            <p style={ { fontSize: 'var(--text-md)', color: 'var(--text-muted)', margin: '4px 0 0' } }>
              { filtered.length } order{ filtered.length !== 1 ? 's' : '' } · Order ID is the central tracking key
            </p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>New Order</Button>
          </div>
        </div>

        {/* ── Filters ── */ }
        <div className="orders-filters" style={ { display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' } }>
          <input
            type="text" placeholder="Search order number, source ID, phone, or customer..."
            value={ search } onChange={ e => { setSearch( e.target.value ); setPage( 1 ); } }
            style={ { flex: 1, minWidth: 220, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 'var(--text-md)' } }
          />
          <Select ariaLabel="Source" value={ sourceFilter }
            onChange={ v => { setSourceFilter( v ); setPage( 1 ); } }
            options={ SOURCE_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Fulfilment status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Payment status" value={ paymentFilter }
            onChange={ v => { setPaymentFilter( v ); setPage( 1 ); } }
            options={ PAYMENT_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        {/* ── Table ── */ }
        { !loading && failure ? (
          // A failed load shows WHY, with a retry — never a misleading "No orders found".
          <div role="alert"><ErrorState message="Could not load orders" detail={ failure.message } onRetry={ failure.retryable ? loadOrders : undefined } /></div>
        ) : filtered.length === 0 && !loading ? (
          <EmptyState icon="order" title="No orders found" description="Create a manual order to get started." action={ { label: 'New Order', onClick: () => setShowCreate( true ) } } />
        ) : (
          <>
          <div className="orders-desktop-table" style={ { background: '#fff', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' } }>
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', minWidth: 900 } }>
                <thead>
                  <tr style={ { background: 'var(--bg-secondary)' } }>
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
                    <tr><td colSpan={ 8 } style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>Loading orders...</td></tr>
                  ) : paged.map( order => {
                    const short = order.orderNumber || order.shortId || extractShortId( order.orderId );
                    return (
                      <tr key={ order.orderId } style={ { borderBottom: '1px solid #f3f4f6', cursor: 'pointer' } } onClick={ () => openDetail( order ) }>
                        <td style={ tdStyle }>
                          <CopyableId id={ order.orderId } short={ short } />
                        </td>
                        <td style={ { ...tdStyle, fontSize: 'var(--text-sm)', whiteSpace: 'nowrap' } }>{ formatDate( order.createdAt ) }</td>
                        <td style={ tdStyle }>
                          <div style={ { fontWeight: 500, fontSize: 'var(--text-md)' } }>{ order.customerName || '—' }</div>
                          <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontFamily: 'monospace' } }>{ order.customerPhone || '' }</div>
                        </td>
                        <td style={ tdStyle }><Badge status={ order.source } /></td>
                        <td style={ { ...tdStyle, fontSize: 'var(--text-sm)' } }>{ order.itemCount ?? order.items?.length ?? '—' }</td>
                        <td style={ tdStyle }><Badge status={ orderFulfilment( order ) } /></td>
                        <td style={ tdStyle }><Badge status={ order.paymentStatus } /></td>
                        <td style={ { ...tdStyle, fontSize: 'var(--text-sm)', textAlign: 'center' } }>{ order.requestCount ?? '—' }</td>
                      </tr>
                    );
                  } ) }
                </tbody>
              </table>
            </div>
          </div>
          <div className="orders-mobile-list">
            { loading ? (
              <div className="orders-mobile-state">Loading orders…</div>
            ) : paged.map( order => {
              const short = order.orderNumber || order.shortId || extractShortId( order.orderId );
              return (
                <button type="button" key={ `mobile-${order.orderId}` }
                  className="orders-mobile-card" onClick={ () => openDetail( order ) }>
                  <span className="orders-mobile-top">
                    <strong>{ short }</strong>
                    <span>{ formatDate( order.createdAt ) }</span>
                  </span>
                  <span className="orders-mobile-customer">
                    <strong>{ order.customerName || 'Unnamed customer' }</strong>
                    <small>{ order.customerPhone || 'No phone' }</small>
                  </span>
                  <span className="orders-mobile-meta">
                    <span><small>Source</small>{ order.source || '—' }</span>
                    <span><small>Items</small>{ order.itemCount ?? order.items?.length ?? '—' }</span>
                    <span><small>Requests</small>{ order.requestCount ?? '—' }</span>
                  </span>
                  <span className="orders-mobile-status">
                    <Badge status={ orderFulfilment( order ) } />
                    <Badge status={ order.paymentStatus } />
                  </span>
                </button>
              );
            } ) }
          </div>
          </>
        ) }
        { totalPages > 1 && (
          <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }>
            <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
          </div>
        ) }

        {/* ── Order Detail Panel ── */ }
        <Modal isOpen={ !!selectedOrder } onClose={ () => setSelectedOrder( null ) } title="Order Details" size="xl">
          { selectedOrder && <OrderDetailPanel order={ selectedOrder } submissions={ submissions } subsLoading={ subsLoading } documents={ detailDocs } statusHistory={ detailHistory } onStatusUpdate={ handleOrderStatusUpdate } onTrackingUpdate={ handleTrackingUpdate } onSubmissionStatusUpdate={ handleSubmissionStatusUpdate } onOrderCancel={ handleOrderCancel } onReturnStageUpdate={ handleReturnStageUpdate } onRefundInitiation={ handleRefundInitiation } /> }
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
                 computed the name by walking its subtree, and a label
                 forwards clicks to its control, which can double-activate a button. */ }
            <Select label="Source" value={ createForm.source }
              onChange={ v => setCreateForm( f => ( { ...f, source: v } ) ) }
              options={ SOURCE_OPTIONS } />
            <label style={ labelStyle }>Items Summary<input type="text" value={ createForm.itemsSummary } onChange={ e => setCreateForm( f => ( { ...f, itemsSummary: e.target.value } ) ) } placeholder="e.g. Black Tee × 1, White Cap × 2" style={ inputStyle } /></label>
            <label style={ labelStyle }>Total Amount (₹)<input type="number" value={ createForm.totalAmount } onChange={ e => setCreateForm( f => ( { ...f, totalAmount: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ labelStyle }>Admin Notes<textarea value={ createForm.notes } onChange={ e => setCreateForm( f => ( { ...f, notes: e.target.value } ) ) } rows={ 2 } style={ { ...inputStyle, resize: 'vertical' } } /></label>
          </div>
        </Modal>

        <style jsx global>{`
          .orders-mobile-list{display:none}
          @media(max-width:768px){
            .orders-workspace{
              padding:
                24px max(16px,env(safe-area-inset-right,0px))
                calc(88px + env(safe-area-inset-bottom,0px))
                max(16px,env(safe-area-inset-left,0px)) !important;
            }
            .orders-filters{align-items:stretch}
            .orders-filters > input{flex:1 1 100% !important;min-width:0 !important;width:100%}
            .orders-filters > .ui-field{flex:1 1 calc(50% - 5px) !important;width:auto !important;min-width:0}
            .orders-desktop-table{display:none}
            .orders-mobile-list{display:flex;flex-direction:column;gap:12px}
            .orders-mobile-card{
              width:100%;min-width:0;min-height:44px;padding:14px;
              display:flex;flex-direction:column;gap:12px;text-align:start;
              background:#fff;border:1px solid var(--border);border-radius:14px;
              color:var(--text);cursor:pointer;
            }
            .orders-mobile-card:hover,.orders-mobile-card:focus-visible{
              background:var(--lime-tint);border-color:var(--lime);
            }
            .orders-mobile-card:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
            .orders-mobile-top,.orders-mobile-status{
              display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap
            }
            .orders-mobile-top strong{font-family:monospace;color:var(--accent);overflow-wrap:anywhere}
            .orders-mobile-top>span{font-size:var(--text-xs);color:var(--text-muted)}
            .orders-mobile-customer{display:flex;flex-direction:column;gap:3px;min-width:0}
            .orders-mobile-customer strong,.orders-mobile-customer small{overflow-wrap:anywhere}
            .orders-mobile-customer small{color:var(--text-muted)}
            .orders-mobile-meta{
              display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px
            }
            .orders-mobile-meta>span{min-width:0;display:flex;flex-direction:column;gap:2px;overflow-wrap:anywhere}
            .orders-mobile-meta small{color:var(--text-muted);font-size:var(--text-xs)}
            .orders-mobile-state{padding:32px 16px;text-align:center;color:var(--text-muted);background:#fff;border:1px solid var(--border);border-radius:14px}
          }
          @media(max-width:360px){
            .orders-workspace{padding-inline:12px !important}
            .orders-filters > .ui-field{flex-basis:100% !important}
            .orders-mobile-meta{grid-template-columns:1fr 1fr}
          }
        `}</style>
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
  onStatusUpdate: ( order: api.Order, status: string ) => void;
  onTrackingUpdate: ( orderId: string, tracking: ManualTrackingPatch ) => Promise<boolean>;
  onSubmissionStatusUpdate: ( subId: string, status: string ) => void;
  onOrderCancel: ( orderId: string, reason: string ) => Promise<boolean>;
  onReturnStageUpdate: ( subId: string, stage: api.ReturnStage, notes?: string ) => Promise<boolean>;
  onRefundInitiation: ( sub: api.FlowSubmissionItem, reason: string ) => Promise<boolean>;
}

const OrderDetailPanel: React.FC<DetailProps> = ( { order, submissions, subsLoading, documents, statusHistory, onStatusUpdate, onTrackingUpdate, onSubmissionStatusUpdate, onOrderCancel, onReturnStageUpdate, onRefundInitiation } ) => {
  const confirm = useConfirm();
  const short = order.orderNumber || order.shortId || extractShortId( order.orderId );
  const [ trackingDraft, setTrackingDraft ] = useState<ManualTrackingPatch>( {
    carrierName: order.carrierName || '',
    trackingNumber: order.trackingNumber || '',
    trackingUrl: order.trackingUrl || '',
  } );
  const [ trackingSaving, setTrackingSaving ] = useState( false );
  const [ trackingError, setTrackingError ] = useState( '' );
  const [ cancelReason, setCancelReason ] = useState( '' );
  const [ cancelSaving, setCancelSaving ] = useState( false );
  const [ returnNotes, setReturnNotes ] = useState<Record<string, string>>( {} );
  const [ returnSaving, setReturnSaving ] = useState<string | null>( null );
  const [ refundReasons, setRefundReasons ] = useState<Record<string, string>>( {} );
  const [ refundSaving, setRefundSaving ] = useState<string | null>( null );

  useEffect( () => {
    setTrackingDraft( {
      carrierName: order.carrierName || '',
      trackingNumber: order.trackingNumber || '',
      trackingUrl: order.trackingUrl || '',
    } );
    setTrackingError( '' );
  }, [ order.orderId, order.carrierName, order.trackingNumber, order.trackingUrl ] );

  const savedTrackingUrl = safeTrackingUrl( order.trackingUrl );

  const saveTracking = async () => {
    const next: ManualTrackingPatch = {
      carrierName: String( trackingDraft.carrierName || '' ).trim(),
      trackingNumber: String( trackingDraft.trackingNumber || '' ).trim(),
      trackingUrl: String( trackingDraft.trackingUrl || '' ).trim(),
    };
    if ( next.trackingUrl && !safeTrackingUrl( next.trackingUrl ) )
    {
      setTrackingError( 'Tracking URL must be a valid HTTPS URL without embedded credentials.' );
      return;
    }

    setTrackingSaving( true );
    setTrackingError( '' );
    const ok = await onTrackingUpdate( order.orderId, next );
    setTrackingSaving( false );
    if ( !ok ) setTrackingError( 'Tracking details were not saved. Reload the order and try again.' );
  };

  const cancelPendingOrder = async () => {
    const reason = cancelReason.trim();
    if ( !reason ) return;
    setCancelSaving( true );
    const ok = await onOrderCancel( order.orderId, reason );
    setCancelSaving( false );
    if ( ok ) setCancelReason( '' );
  };

  const moveReturnStage = async ( sub: api.FlowSubmissionItem, rawStage: string ) => {
    const stage = rawStage as api.ReturnStage;
    const note = String( returnNotes[ sub.submissionId ] || '' ).trim();
    if ( ( stage === 'rejected' || stage === 'return_waived' ) && !note ) return;
    setReturnSaving( sub.submissionId );
    const ok = await onReturnStageUpdate( sub.submissionId, stage, note || undefined );
    setReturnSaving( null );
    if ( ok ) setReturnNotes( current => ( { ...current, [ sub.submissionId ]: '' } ) );
  };

  const initiateFullRefund = async ( sub: api.FlowSubmissionItem ) => {
    const reason = String( refundReasons[ sub.submissionId ] || '' ).trim();
    if ( !reason || !sub.invoiceId ) return;

    const confirmed = await confirm( {
      title: 'Initiate full refund',
      message: `Initiate the full refund for ${sub.submissionNumber || sub.submissionId}? The server derives the payment and amount from the linked invoice.`,
      confirmText: 'Initiate refund',
      danger: true,
    } );
    if ( !confirmed ) return;

    setRefundSaving( sub.submissionId );
    const ok = await onRefundInitiation( sub, reason );
    setRefundSaving( null );
    if ( ok ) setRefundReasons( current => ( { ...current, [ sub.submissionId ]: '' } ) );
  };

  return (
    <div>
      {/* ── Section A: Order Details ── */ }
      <div style={ { marginBottom: 24 } }>
        <div style={ { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 } }>
          <span style={ { fontSize: 22, fontWeight: 700, fontFamily: 'monospace', color: 'var(--accent)' } }>{ short }</span>
          <Badge status={ orderFulfilment( order ) } />
          <Badge status={ order.paymentStatus } />
        </div>

        {/* Phase 2 (workspace mobile): responsive auto-fit grid - the same pattern already used
            by the sibling items grid below (line ~552) - so these 7 metadata cells reflow from
            three columns on desktop down to two then one on a phone instead of staying locked at
            three ~99px columns at 320px, which crammed the monospace order id / datetime / phone.
            auto-fit/minmax works inline (no @media needed, which an inline style cannot carry). */}
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 12 } }>
          <div><span style={ metaLabel }>Full Order ID</span><div style={ { fontSize: 'var(--text-xs)', fontFamily: 'monospace', wordBreak: 'break-all', color: '#374151' } }>{ order.orderId }</div></div>
          <div><span style={ metaLabel }>Customer</span><div style={ { fontWeight: 500 } }>{ order.customerName || '—' }</div></div>
          <div><span style={ metaLabel }>Phone</span><div style={ { fontFamily: 'monospace' } }>{ order.customerPhone || '—' }</div></div>
          { order.referenceId && <div><span style={ metaLabel }>Payment reference</span><div style={ { fontFamily: 'monospace' } }>{ order.referenceId }</div></div> }
          <div><span style={ metaLabel }>Source</span><div><Badge status={ order.source } /></div></div>
          <div><span style={ metaLabel }>Created</span><div>{ formatDateTime( order.createdAt ) }</div></div>
          <div><span style={ metaLabel }>Amount</span><div style={ { fontWeight: 600 } }>{ ( order.paymentAmount ?? order.totalAmount ) !== undefined ? `₹${ order.paymentAmount ?? order.totalAmount }` : '—' }</div></div>
        </div>

        {/* Status controls */ }
        <div style={ { display: 'flex', gap: 12, padding: 12, background: 'var(--bg-secondary)', borderRadius: 8, flexWrap: 'wrap' } }>
          { /* SHAPE (a) - wrapping <label> deleted, label passed. */ }
          <Select label="Fulfilment" value={ orderFulfilment( order ) }
            onChange={ v => onStatusUpdate( order, v ) }
            options={ fulfilmentOptions( order ) }
            disabled={ allowedFulfilmentTargets( orderFulfilment( order ), order.paymentStatus ).length === 0 }
            style={ DETAIL_SELECT_STYLE } />
          { canCancelOrder( order ) ? (
            <div style={ { flex: '1 1 280px' } }>
              <label style={ labelStyle }>
                Cancellation reason
                <input type="text" maxLength={ 500 } value={ cancelReason }
                  onChange={ e => setCancelReason( e.target.value ) }
                  placeholder="Required audit reason" style={ inputStyle } />
              </label>
              <Button variant="danger" size="sm" loading={ cancelSaving }
                disabled={ !cancelReason.trim() }
                onClick={ cancelPendingOrder }>Cancel pending order</Button>
            </div>
          ) : orderFulfilment( order ) !== 'canceled' && (
            <div style={ { flex: '1 1 260px', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', alignSelf: 'end' } }>
              Cancellation is unavailable after payment authorization/capture or fulfilment starts. Use a Return / Refund request for paid orders.
            </div>
          ) }
        </div>
      </div>

      {/* ── Shipment tracking: manual evidence only, no courier integration. ── */ }
      <div style={ { marginBottom: 24 } }>
        <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--accent)', marginBottom: 6 } }>
          Shipment tracking
        </h3>
        <p style={ { margin: '0 0 12px', color: 'var(--text-muted)', fontSize: 'var(--text-sm)' } }>
          Manual record — not synced with a courier. Save only carrier and tracking details you have confirmed.
        </p>
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 } }>
          <label style={ labelStyle }>
            Carrier
            <input type="text" maxLength={ 120 } value={ trackingDraft.carrierName || '' }
              onChange={ e => setTrackingDraft( draft => ( { ...draft, carrierName: e.target.value } ) ) }
              placeholder="e.g. Blue Dart" style={ inputStyle } />
          </label>
          <label style={ labelStyle }>
            Tracking number
            <input type="text" maxLength={ 160 } value={ trackingDraft.trackingNumber || '' }
              onChange={ e => setTrackingDraft( draft => ( { ...draft, trackingNumber: e.target.value } ) ) }
              placeholder="Carrier reference" style={ inputStyle } />
          </label>
          <label style={ labelStyle }>
            Tracking URL
            <input type="url" maxLength={ 2048 } value={ trackingDraft.trackingUrl || '' }
              onChange={ e => setTrackingDraft( draft => ( { ...draft, trackingUrl: e.target.value } ) ) }
              placeholder="https://carrier.example/track/..." style={ inputStyle } />
          </label>
        </div>
        { trackingError && <div role="alert" style={ { color: 'var(--danger, #b91c1c)', fontSize: 'var(--text-sm)', marginTop: 8 } }>{ trackingError }</div> }
        <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 12 } }>
          <Button variant="primary" loading={ trackingSaving } onClick={ saveTracking }>Save tracking</Button>
          { savedTrackingUrl && (
            <Button variant="secondary" onClick={ () => void openExternal( savedTrackingUrl ) }>Open tracking</Button>
          ) }
          { order.trackingSource === 'manual' && (
            <span style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
              Manual entry{ order.trackingUpdatedAt ? ` · updated ${formatDateTime( order.trackingUpdatedAt )}` : '' }
            </span>
          ) }
        </div>
      </div>

      {/* ── Section B: Service Requests ── */ }
      <div style={ { marginBottom: 24 } }>
        <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--accent)', marginBottom: 12 } }>
          Service Requests ({ submissions.length })
        </h3>
        { subsLoading ? (
          <p style={ { color: 'var(--text-muted)', fontSize: 'var(--text-md)' } }>Loading requests...</p>
        ) : submissions.length === 0 ? (
          <p style={ { color: 'var(--text-muted)', fontSize: 'var(--text-md)', padding: 16, background: 'var(--bg-secondary)', borderRadius: 8 } }>No service requests linked to this order.</p>
        ) : (
          <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
            { submissions.map( sub => (
              <div key={ sub.submissionId } style={ {
                padding: 14, border: '1px solid var(--border)', borderRadius: 10,
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12,
              } }>
                <div style={ { flex: 1, minWidth: 0 } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } }>
                    <span style={ { fontFamily: 'monospace', fontWeight: 600, fontSize: 'var(--text-sm)' } }>
                      { sub.submissionNumber || sub.submissionId.slice( 0, 16 ) }
                    </span>
                    <Badge status={ sub.status } />
                    <Badge status={ sub.paymentStatus } />
                  </div>
                  <div style={ { fontSize: 'var(--text-md)', fontWeight: 500, marginBottom: 2 } }>{ sub.subject || sub.requestType || '—' }</div>
                  <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
                    { sub.flowCode } · { sub.phone } · { formatDateTime( sub.createdAt ) }
                    { sub.paymentAmount ? ` · ₹${( sub.paymentAmount / 100 ).toFixed( 0 )}` : '' }
                  </div>
                </div>
                <div style={ { display: 'flex', flexDirection: 'column', gap: 8, flex: '0 1 250px' } }>
                  <Select
                    ariaLabel="Request status"
                    value={ sub.status || 'open' }
                    onChange={ v => onSubmissionStatusUpdate( sub.submissionId, v ) }
                    options={ SUBMISSION_STATUS_OPTIONS }
                    style={ ROW_SELECT_STYLE }
                  />
                  { sub.requestType === 'Return / Refund' && (
                    <>
                      <div style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-xs)' } }>
                        <span style={ { color: 'var(--text-muted)' } }>Return stage</span>
                        <Badge status={ sub.returnStage || 'requested' } />
                      </div>
                      { returnStageOptions( sub ).length > 1 && (
                        <>
                          <input type="text" maxLength={ 1000 }
                            value={ returnNotes[ sub.submissionId ] || '' }
                            onChange={ e => setReturnNotes( current => ( { ...current, [ sub.submissionId ]: e.target.value } ) ) }
                            placeholder="Review note; required for reject / waiver"
                            style={ { ...inputStyle, marginTop: 0 } } />
                          <Select
                            ariaLabel="Return stage"
                            value={ sub.returnStage || 'requested' }
                            onChange={ v => moveReturnStage( sub, v ) }
                            options={ returnStageOptions( sub ) }
                            disabled={ returnSaving === sub.submissionId }
                            style={ ROW_SELECT_STYLE }
                          />
                        </>
                      ) }
                      { ( sub.returnStage || 'requested' ) === 'refund_eligible' && (
                        <div style={ { display: 'flex', flexDirection: 'column', gap: 6 } }>
                          <input type="text" maxLength={ 500 }
                            value={ refundReasons[ sub.submissionId ] || '' }
                            onChange={ e => setRefundReasons( current => ( { ...current, [ sub.submissionId ]: e.target.value } ) ) }
                            placeholder="Refund reason (required)"
                            style={ { ...inputStyle, marginTop: 0 } } />
                          <Button variant="danger" size="sm"
                            loading={ refundSaving === sub.submissionId }
                            disabled={ !sub.invoiceId || !String( refundReasons[ sub.submissionId ] || '' ).trim() }
                            onClick={ () => void initiateFullRefund( sub ) }>
                            Initiate full refund
                          </Button>
                          { !sub.invoiceId && (
                            <span style={ { fontSize: 'var(--text-xs)', color: '#92400e' } }>
                              Link/reconcile the invoice before refunding.
                            </span>
                          ) }
                        </div>
                      ) }
                    </>
                  ) }
                </div>
              </div>
            ) ) }
          </div>
        ) }
      </div>

      {/* ── Section C: Documents ── */ }
      { documents.length > 0 && (
        <div style={ { marginBottom: 24 } }>
          <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--accent)', marginBottom: 12 } }>
            Documents ({ documents.length })
          </h3>
          <div style={ { display: 'flex', flexDirection: 'column', gap: 6 } }>
            { documents.map( ( doc: any ) => (
              <div key={ doc.documentId } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', border: '1px solid var(--border)', borderRadius: 8 } }>
                <div>
                  <div style={ { fontWeight: 500, fontSize: 'var(--text-sm)' } }>{ doc.fileName || 'Document' }</div>
                  <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ doc.type || doc.documentType || '—' } · { doc.source || doc.sourceType || '—' }</div>
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
          <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--accent)', marginBottom: 12 } }>
            Status History ({ statusHistory.length })
          </h3>
          <div style={ { position: 'relative', paddingLeft: 20 } }>
            <div style={ { position: 'absolute', left: 6, top: 4, bottom: 4, width: 2, background: 'var(--border)' } } />
            { statusHistory.slice( 0, 10 ).map( ( h: any, i: number ) => (
              <div key={ h.historyId || i } style={ { position: 'relative', paddingBottom: 14, paddingLeft: 16 } }>
                <div style={ { position: 'absolute', left: -14, top: 4, width: 10, height: 10, borderRadius: '50%', background: i === 0 ? 'var(--accent)' : '#d1d5db', border: '2px solid #fff' } } />
                <div style={ { fontSize: 'var(--text-sm)', fontWeight: 500, color: '#374151' } }>
                  { h.oldStatus && <><Badge status={ h.oldStatus } /> → </> }<Badge status={ h.newStatus } />
                </div>
                { h.notes && <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 } }>{ h.notes }</div> }
                <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', marginTop: 2 } }>{ formatDateTime( h.changedAt ) } · { h.changedByName || h.changedBy || 'system' }</div>
              </div>
            ) ) }
          </div>
        </div>
      ) }

      {/* ── Section E: Notes ── */ }
      { order.notes && (
        <div>
          <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--accent)', marginBottom: 8 } }>Admin Notes</h3>
          <div style={ { padding: 12, background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 'var(--text-md)', whiteSpace: 'pre-wrap' } }>{ order.notes }</div>
        </div>
      ) }
    </div>
  );
};

// ── Styles ──

const thStyle: React.CSSProperties = {
  padding: '12px 14px', textAlign: 'left', borderBottom: '1px solid var(--border)',
  fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
  whiteSpace: 'nowrap',
};
const tdStyle: React.CSSProperties = { padding: '12px 14px', fontSize: 'var(--text-md)' };
/* `selectStyle` went with the last native select in this file - it only ever skinned one. */
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 'var(--text-md)', marginTop: 4 };
const labelStyle: React.CSSProperties = { fontSize: 'var(--text-md)', display: 'block' };
const metaLabel: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, display: 'block', marginBottom: 2 };

export default OrdersPage;
