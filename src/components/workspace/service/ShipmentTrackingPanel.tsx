/**
 * Read-only shipment evidence in Workspace Service. The canonical Commerce
 * Orders and service track endpoints own the source record and carrier fields.
 * Viewing an order is not buying the separate priced Track Shipping product.
 */
import React from 'react';
import * as api from '../../../api/client';

const when = (seconds?: number): string => seconds
  ? new Date(seconds < 1e12 ? seconds * 1000 : seconds).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }) : '—';

const safeCourierLink = (raw?: string): string | null => {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
};

export default function ShipmentTrackingPanel() {
  const [orders, setOrders] = React.useState<api.Order[]>([]);
  const [search, setSearch] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [detail, setDetail] = React.useState<api.TrackingData | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState('');
  const requestId = React.useRef(0);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError('');
    const result = await api.collectApiFailures(() => api.listOrders({limit: 150}));
    if (result.failures.length) {
      setOrders([]);
      setError(result.failures[0]?.message || 'Orders could not be loaded.');
    } else {
      setOrders(result.data.orders || []);
    }
    setLoading(false);
  }, []);
  React.useEffect(() => { void load(); }, [load]);

  const lookup = React.useCallback(async (order: api.Order) => {
    const active = ++requestId.current;
    setDetail(null);
    setDetailError('');
    setDetailLoading(true);
    try {
      const found = await api.getTrackingData(order.orderId);
      if (active !== requestId.current) return;
      if (found) setDetail(found);
      else setDetailError('No verified tracking details were returned. Open Orders to check.');
    } catch {
      if (active === requestId.current) setDetailError('Could not read tracking details.');
    } finally {
      if (active === requestId.current) setDetailLoading(false);
    }
  }, []);

  const visible = orders.filter(order => {
    const needle = search.trim().toLowerCase();
    return !needle || [order.orderNumber, order.orderId, order.trackingNumber, order.customerName]
      .some(value => String(value || '').toLowerCase().includes(needle));
  }).slice(0, 30);
  const courier = safeCourierLink(detail?.order.trackingUrl);

  return (
    <section aria-labelledby="shipment-tracking-title"
      style={{maxWidth: 1120, padding: '8px 0 40px'}}>
      <h2 id="shipment-tracking-title">Existing shipment tracking</h2>
      <p>Staff read-only order status and courier evidence. No purchase or WhatsApp
        message is created by opening tracking details.</p>
      <label htmlFor="shipment-lookup" style={{display:'block',fontWeight:750}}>
        Find an order, customer or tracking number
      </label>
      <div style={{display:'flex',gap:8,margin:'8px 0 18px',flexWrap:'wrap'}}>
        <input id="shipment-lookup" value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Order or tracking number"
          style={{minHeight:44,minWidth:0,flex:'1 1 250px',padding:10,
            border:'1px solid var(--border)',borderRadius:10}} />
        <button type="button" onClick={() => {void load();}} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {loading && <p role="status">Reading orders…</p>}
      {!loading && !error && visible.length === 0 &&
        <p role="status">No matching orders among the latest {orders.length} records.</p>}
      {!loading && !error && visible.length > 0 && (
        <div style={{overflowX:'auto',border:'1px solid var(--border)',borderRadius:12}}>
          <table style={{borderCollapse:'collapse',minWidth:700,width:'100%'}}>
            <thead><tr>
              <th style={{textAlign:'left',padding:12}}>Order</th>
              <th style={{textAlign:'left',padding:12}}>Fulfilment</th>
              <th style={{textAlign:'left',padding:12}}>Carrier</th>
              <th style={{textAlign:'left',padding:12}}>Tracking number</th>
              <th style={{textAlign:'left',padding:12}}>Details</th>
            </tr></thead>
            <tbody>{visible.map(order => (
              <tr key={order.orderId}>
                <td style={{padding:12}}>{order.orderNumber || order.orderId}</td>
                <td style={{padding:12}}>{order.fulfillmentStatus || order.orderStatus || order.status || 'Unverified'}</td>
                <td style={{padding:12}}>{order.carrierName || 'Not recorded'}</td>
                <td style={{padding:12}}>{order.trackingNumber || 'Not recorded'}</td>
                <td style={{padding:12}}>
                  <button type="button" disabled={detailLoading}
                    onClick={() => {void lookup(order);}}>View evidence</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {detailLoading && <p role="status">Reading authoritative tracking evidence…</p>}
      {detailError && <p role="alert">{detailError}</p>}
      {detail && (
        <div style={{marginTop:18,border:'1px solid var(--border)',padding:17,
          borderRadius:12,background:'#fff'}}>
          <h3>{detail.order.orderNumber || detail.order.orderId}</h3>
          <p><strong>Order status:</strong> {detail.order.orderStatus || detail.order.status || 'Unknown'}</p>
          <p><strong>Fulfilment:</strong> {detail.order.fulfillmentStatus || 'Unverified'}</p>
          <p><strong>Courier:</strong> {detail.order.carrierName || 'Not recorded'}</p>
          <p><strong>Tracking:</strong> {detail.order.trackingNumber || 'Not recorded'}</p>
          {courier && <p><a href={courier} target="_blank" rel="noopener noreferrer">
            Open recorded courier link</a></p>}
          {detail.statusHistory.length > 0 && <details>
            <summary>Status history ({detail.statusHistory.length})</summary>
            <ul>{detail.statusHistory.map(row => <li key={row.historyId}>
              {when(row.changedAt)} · {row.oldStatus || '—'} → {row.newStatus}
            </li>)}</ul>
          </details>}
        </div>
      )}
      <p style={{fontSize:12,color:'var(--text-muted)',marginTop:18}}>
        Tracking data is read from the same backend as Commerce / Orders.
        A tracking number does not guarantee courier delivery.
      </p>
    </section>
  );
}
