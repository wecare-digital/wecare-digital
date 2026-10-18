/**
 * Track Request — [retired public path]/track-request
 * Order-centric tracking: select order → view all requests, status, timeline, payments, outcomes.
 * Uses Order ID as the primary customer-facing key.
 */
import React, { useState, useEffect, useCallback } from 'react';
import MaybeLayout from '../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import EmptyState from '../../../components/ui/EmptyState';
import ErrorState from '../../../components/ErrorState';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

function extractShortId ( orderId: string ): string {
  const parts = orderId.split( '-' );
  return parts.length >= 3 ? parts[ parts.length - 1 ] : orderId.slice( 0, 8 );
}

function formatOrderLabel ( o: api.Order ): string {
  const short = o.shortId || extractShortId( o.orderId );
  return `${short} — ${o.orderDateIST || o.orderDate || ''}`;
}

function fmtDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' } );
}

function statusColor ( status: string ): { bg: string; fg: string } {
  const map: Record<string, { bg: string; fg: string }> = {
    open: { bg: '#dbeafe', fg: '#1e40af' },
    in_progress: { bg: '#fef3c7', fg: '#92400e' },
    resolved: { bg: 'var(--lime)', fg: 'var(--accent)' },
    closed: { bg: '#f3f4f6', fg: '#374151' },
    cancelled: { bg: '#fee2e2', fg: '#991b1b' },
    pending: { bg: '#fef3c7', fg: '#92400e' },
    captured: { bg: '#d1fae5', fg: '#065f46' },
    paid: { bg: '#d1fae5', fg: '#065f46' },
    failed: { bg: '#fee2e2', fg: '#991b1b' },
  };
  return map[ status ] || { bg: '#f3f4f6', fg: '#374151' };
}

function Badge ( { label }: { label: string } ) {
  const c = statusColor( label );
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 'var(--text-xs)', fontWeight: 600, background: c.bg, color: c.fg } }>{ label.replace( /_/g, ' ' ) }</span>;
}

const TrackRequestPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ orders, setOrders ] = useState<api.Order[]>( [] );
  const [ loadingOrders, setLoadingOrders ] = useState( true );
  const [ ordersFailed, setOrdersFailed ] = useState( false );
  const [ selectedOrder, setSelectedOrder ] = useState<api.Order | null>( null );
  const [ tracking, setTracking ] = useState<api.TrackingData | null>( null );
  const [ loadingTracking, setLoadingTracking ] = useState( false );
  const [ orderSearch, setOrderSearch ] = useState( '' );

  const loadOrders = useCallback( async () => {
    setLoadingOrders( true );
    setOrdersFailed( false );
    try
    {
      const data = await api.listOrders( { limit: 200 } );
      setOrders( data.orders || [] );
    } catch
    {
      setOrdersFailed( true );
      toast.error( 'Failed to load orders' );
    }
    setLoadingOrders( false );
  }, [ toast ] );

  useEffect( () => { loadOrders(); }, [ loadOrders ] );

  const loadTracking = useCallback( async ( order: api.Order ) => {
    setSelectedOrder( order );
    setLoadingTracking( true );
    try
    {
      const data = await api.getTrackingData( order.orderId );
      setTracking( data );
    } catch { toast.error( 'Failed to load tracking data' ); }
    setLoadingTracking( false );
  }, [ toast ] );

  const filteredOrders = orders.filter( o => {
    if ( !orderSearch.trim() ) return true;
    const q = orderSearch.toLowerCase();
    return formatOrderLabel( o ).toLowerCase().includes( q ) || ( o.customerName || '' ).toLowerCase().includes( q ) || o.orderId.toLowerCase().includes( q );
  } );

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.trackRequest } />
      <div style={ { padding: '24px 32px', maxWidth: 1200 } }>
        <h1 style={ { fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 4px' } }>Track Request</h1>
        <p style={ { fontSize: 'var(--text-md)', color: 'var(--text-muted)', margin: '0 0 24px' } }>Select an order to view all service activity</p>

        <div style={ { display: 'grid', gridTemplateColumns: selectedOrder ? '340px 1fr' : '1fr', gap: 24 } }>
          {/* Order List */ }
          <div style={ cardStyle }>
            <input
              type="text"
              placeholder="Search orders..."
              value={ orderSearch }
              onChange={ e => setOrderSearch( e.target.value ) }
              style={ { ...inputStyle, marginBottom: 12 } }
            />
            <div style={ { maxHeight: selectedOrder ? 'calc(100vh - 280px)' : 500, overflowY: 'auto' } }>
              { loadingOrders ? (
                <div style={ { textAlign: 'center', padding: 24, color: 'var(--text-muted)' } }>Loading...</div>
              ) : ordersFailed ? (
                <div role="alert"><ErrorState message="Could not load orders" onRetry={ loadOrders } /></div>
              ) : filteredOrders.length === 0 ? (
                <EmptyState icon="default" title="No orders" description="No orders found" />
              ) : (
                filteredOrders.map( o => (
                  <button
                    key={ o.orderId }
                    onClick={ () => loadTracking( o ) }
                    style={ {
                      display: 'block', width: '100%', padding: '10px 14px', border: '2px solid',
                      borderColor: selectedOrder?.orderId === o.orderId ? 'var(--lime)' : '#f3f4f6',
                      borderRadius: 10, background: selectedOrder?.orderId === o.orderId ? '#f0fdf4' : '#fff',
                      cursor: 'pointer', marginBottom: 6, textAlign: 'left', transition: 'border-color 0.15s',
                    } }
                  >
                    <div style={ { fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--accent)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }>
                      { formatOrderLabel( o ) }
                    </div>
                    <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2, display: 'flex', gap: 8, alignItems: 'center' } }>
                      <span>{ o.customerName || 'Customer' }</span>
                      <Badge label={ o.orderStatus || 'active' } />
                    </div>
                  </button>
                ) )
              ) }
            </div>
          </div>

          {/* Tracking Detail */ }
          { selectedOrder && (
            <div>
              { loadingTracking ? (
                <div style={ { ...cardStyle, textAlign: 'center', padding: 40, color: 'var(--text-muted)' } }>Loading tracking data...</div>
              ) : !tracking ? (
                <div style={ { ...cardStyle, textAlign: 'center', padding: 40 } }>
                  <EmptyState icon="default" title="No tracking data" description="No service activity found for this order" />
                </div>
              ) : (
                <>
                  {/* Order Summary */ }
                  <div style={ { ...cardStyle, marginBottom: 16 } }>
                    <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 12px' } }>Order Details</h3>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 } }>
                      <div><span style={ metaLabel }>Order ID</span><div style={ { fontWeight: 600, fontSize: 'var(--text-md)' } }>{ selectedOrder.shortId || extractShortId( selectedOrder.orderId ) }</div></div>
                      <div><span style={ metaLabel }>Date</span><div>{ selectedOrder.orderDateIST || selectedOrder.orderDate || '—' }</div></div>
                      <div><span style={ metaLabel }>Customer</span><div>{ selectedOrder.customerName || '—' }</div></div>
                      <div><span style={ metaLabel }>Order Status</span><div><Badge label={ selectedOrder.orderStatus || 'active' } /></div></div>
                      <div><span style={ metaLabel }>Payment</span><div><Badge label={ selectedOrder.paymentStatus || 'pending' } /></div></div>
                      <div><span style={ metaLabel }>Total</span><div style={ { fontWeight: 600 } }>{ selectedOrder.currency || '₹' }{ selectedOrder.totalAmount || '—' }</div></div>
                    </div>
                    { selectedOrder.itemsSummary && (
                      <div style={ { marginTop: 12, padding: '8px 12px', background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 'var(--text-sm)', color: '#374151' } }>
                        { selectedOrder.itemsSummary }
                      </div>
                    ) }
                  </div>

                  {/* Service Requests */ }
                  <div style={ { ...cardStyle, marginBottom: 16 } }>
                    <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 12px' } }>
                      Service Requests ({ tracking.submissions?.length || 0 })
                    </h3>
                    { ( !tracking.submissions || tracking.submissions.length === 0 ) ? (
                      <div style={ { padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-md)' } }>No service requests for this order</div>
                    ) : (
                      tracking.submissions.map( ( sub: any ) => (
                        <div key={ sub.submissionId } style={ { padding: '12px 16px', border: '1px solid #f3f4f6', borderRadius: 10, marginBottom: 8 } }>
                          <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 } }>
                            <div style={ { fontWeight: 600, fontSize: 'var(--text-md)', color: 'var(--accent)' } }>{ sub.subject || sub.requestType || sub.flowCode }</div>
                            <Badge label={ sub.status || 'open' } />
                          </div>
                          <div style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 4 } }>{ sub.description?.slice( 0, 120 ) || '—' }</div>
                          <div style={ { display: 'flex', gap: 16, fontSize: 'var(--text-xs)', color: '#9ca3af' } }>
                            <span>Ref: { sub.submissionNumber || sub.submissionId?.slice( 0, 8 ) }</span>
                            <span>{ fmtDate( sub.createdAt ) }</span>
                            { sub.paymentStatus && sub.paymentStatus !== 'none' && <span>Payment: <Badge label={ sub.paymentStatus } /></span> }
                          </div>
                        </div>
                      ) )
                    ) }
                  </div>

                  {/* Status Timeline */ }
                  { tracking.statusHistory && tracking.statusHistory.length > 0 && (
                    <div style={ { ...cardStyle, marginBottom: 16 } }>
                      <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 12px' } }>Timeline</h3>
                      <div style={ { position: 'relative', paddingLeft: 20 } }>
                        <div style={ { position: 'absolute', left: 6, top: 4, bottom: 4, width: 2, background: 'var(--border)' } } />
                        { tracking.statusHistory.map( ( h: api.StatusHistoryEntry, i: number ) => (
                          <div key={ h.historyId || i } style={ { position: 'relative', paddingBottom: 16, paddingLeft: 16 } }>
                            <div style={ { position: 'absolute', left: -14, top: 4, width: 10, height: 10, borderRadius: '50%', background: i === 0 ? 'var(--accent)' : '#d1d5db', border: '2px solid #fff' } } />
                            <div style={ { fontSize: 'var(--text-sm)', fontWeight: 500, color: '#374151' } }>
                              { h.oldStatus && <><Badge label={ h.oldStatus } /> → </> }<Badge label={ h.newStatus } />
                            </div>
                            { h.notes && <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 } }>{ h.notes }</div> }
                            <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', marginTop: 2 } }>{ fmtDate( h.changedAt ) } · { h.changedByName || h.changedBy }</div>
                          </div>
                        ) ) }
                      </div>
                    </div>
                  ) }

                  {/* Linked Documents */ }
                  { tracking.documents && tracking.documents.length > 0 && (
                    <div style={ cardStyle }>
                      <h3 style={ { fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--accent)', margin: '0 0 12px' } }>Documents ({ tracking.documents.length })</h3>
                      { tracking.documents.map( ( doc: api.Document ) => (
                        <div key={ doc.documentId } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', border: '1px solid #f3f4f6', borderRadius: 8, marginBottom: 6 } }>
                          <div>
                            <div style={ { fontWeight: 500, fontSize: 'var(--text-sm)' } }>{ doc.fileName || 'Document' }</div>
                            <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ doc.type } · { doc.source }</div>
                          </div>
                          <Badge label={ doc.status } />
                        </div>
                      ) ) }
                    </div>
                  ) }
                </>
              ) }
            </div>
          ) }
        </div>
      </div>
    </MaybeLayout>
  );
};

const cardStyle: React.CSSProperties = { border: '2px solid #f3f4f6', borderRadius: 13, padding: 20, background: '#fff' };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 'var(--text-md)', boxSizing: 'border-box' };
const metaLabel: React.CSSProperties = { display: 'block', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 2 };

export default TrackRequestPage;
