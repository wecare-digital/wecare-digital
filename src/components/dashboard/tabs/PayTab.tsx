/**
 * Pay Tab — Payment records with mobile card view, proper Modal, toast feedback
 */
import React, { useState } from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';
import Button from '../../../components/ui/Button';
import Modal from '../../../components/ui/Modal';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import type { DashboardData } from '../../../types/dashboard';
import { PAYMENT_CONFIG } from '../../../config/constants';
import { publicUrl } from '../../../lib/media-paths';
import type { GatewayCheckResult } from '../../../api/client';

const PAYMENT_PHONE = PAYMENT_CONFIG.phoneDisplay;
const PAYMENT_NAME = PAYMENT_CONFIG.phoneName;
/*
 * BATCH 2f - the status on a payment record in the edit modal. The four values are exactly the
 * four the <option> rows carried and they are NOT canonicalised here: this control writes
 * `status` on an edit request, and the paid-versus-captured vocabulary belongs to
 * `lambda_utils/payment_status.py` on the server. Renaming a value in the browser would send a
 * spelling the ledger does not use.
 */
const PAYMENT_STATUS_OPTIONS: SelectOption[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'captured', label: 'Captured' },
  { value: 'failed', label: 'Failed' },
  { value: 'refunded', label: 'Refunded' },
];

/**
 * The viewable invoice link for a payment row, or '' when there is none.
 *
 * Both call sites below used to interpolate `https://app.wecare.digital/${key}`
 * inline. That was broken twice over: the host was retired on 2026-09-28, and the key
 * needs the `o/` root that stored `invoiceS3Key` values predate. `publicUrl` handles
 * both, and returns '' for a gated key rather than a link that 302s.
 */
function invoiceLinkFor ( pa: { invoiceS3Key?: string; paymentReferenceId?: string } ): string {
  if ( pa.invoiceS3Key ) return publicUrl( pa.invoiceS3Key );
  if ( pa.paymentReferenceId ) return publicUrl( `invoices/${ pa.paymentReferenceId }.png` );
  return '';
}

interface PayTabProps {
  data: DashboardData;
  onRefresh: () => void;
}

const PayTab: React.FC<PayTabProps> = ({ data, onRefresh }) => {
  const { messages } = data;
  const [editPayment, setEditPayment] = useState<any>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [gatewayChecks, setGatewayChecks] = useState<GatewayCheckResult[]>([]);
  const [gatewayLoading, setGatewayLoading] = useState(false);
  const toast = useToastContext();

  const paymentMessages = messages.filter(
    m => m.messageType === 'payment' || m.messageType === 'payment_request',
  );
  const capturedPayments = paymentMessages.filter(m => (m as any).paymentStatus === 'captured').length;
  const failedPayments = paymentMessages.filter(m => (m as any).paymentStatus === 'failed').length;
  const pendingPayments = paymentMessages.filter(m => m.status === 'pending').length;

  const handleCheckGateways = async () => {
    setGatewayLoading(true);
    try {
      const results = await api.checkPaymentGateways();
      setGatewayChecks(results);
      const totalActive = results.reduce((sum, r) => sum + r.activeConfigs, 0);
      toast.success(`Gateway check complete: ${totalActive} active configuration(s)`);
    } catch (err) {
      console.error('Gateway check error:', err);
      toast.error('Failed to check payment gateways');
    } finally {
      setGatewayLoading(false);
    }
  };

  const handleSavePayment = async () => {
    if (!editPayment) return;
    setEditSaving(true);
    try {
      const ok = await api.updateMessage(editPayment.id, {
        paymentItemName: editPayment.paymentItemName,
        paymentQuantity: Number(editPayment.paymentQuantity) || 1,
        paymentGstRate: Number(editPayment.paymentGstRate) || 18,
        paymentPurpose: editPayment.paymentPurpose,
        paymentDueRef: editPayment.paymentDueRef,
        paymentDiscount: Number(editPayment.paymentDiscount) || 0,
        paymentShipping: Number(editPayment.paymentShipping) || 0,
        status: editPayment.status,
      });
      if (ok) {
        toast.success('Payment updated successfully');
        setEditPayment(null);
        onRefresh();
      } else {
        toast.error('Failed to save payment');
      }
    } catch (err) {
      console.error('Save payment error:', err);
      toast.error('Failed to save payment. Please try again.');
    } finally {
      setEditSaving(false);
    }
  };

  const downloadInvoicePdf = (invoiceUrl: string, refId: string) => {
    const link = document.createElement('a');
    link.href = invoiceUrl;
    link.download = `invoice-${refId}.png`;
    link.target = '_blank';
    link.click();
  };

  const editFields = [
    { label: 'Item Name', key: 'paymentItemName', type: 'text' },
    { label: 'Quantity', key: 'paymentQuantity', type: 'number' },
    { label: 'GST Rate (%)', key: 'paymentGstRate', type: 'number' },
    { label: 'Purpose', key: 'paymentPurpose', type: 'text' },
    { label: 'Due Reference', key: 'paymentDueRef', type: 'text' },
    { label: 'Discount (paise)', key: 'paymentDiscount', type: 'number' },
    { label: 'Shipping (paise)', key: 'paymentShipping', type: 'number' },
  ];

  return (
    <div className="pay-tab">
      <div className="section-header">
        <h3>Payment Records</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link href="/workspace/contacts"><Button variant="secondary" size="sm">Add Customer</Button></Link>
          <Link href="/workspace/pay"><Button variant="primary" size="sm">New Payment</Button></Link>
        </div>
      </div>

      <div className="stats-grid small">
        <div className="stat-card" style={{ borderLeft: '4px solid #1a3a2a' }}>
          <div className="stat-value">{capturedPayments}</div>
          <div className="stat-label">Captured</div>
        </div>
        <div className="stat-card" style={{ borderLeft: '4px solid #1a3a2a' }}>
          <div className="stat-value">{failedPayments}</div>
          <div className="stat-label">Failed</div>
        </div>
        <div className="stat-card" style={{ borderLeft: '4px solid #1a3a2a' }}>
          <div className="stat-value">{pendingPayments}</div>
          <div className="stat-label">Pending</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{paymentMessages.length}</div>
          <div className="stat-label">Total</div>
        </div>
      </div>

      <div className="payment-info">
        <span>Payments sent from: <strong>{PAYMENT_PHONE}</strong> ({PAYMENT_NAME})</span>
      </div>

      {/* Payment Gateway Check */}
      <div style={{ margin: '16px 0', padding: 16, background: '#f9fafb', borderRadius: 12, border: '1px solid #e5e7eb' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: gatewayChecks.length ? 12 : 0 }}>
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Payment Gateway Status (Meta API)</span>
          <Button variant="secondary" size="sm" onClick={handleCheckGateways} loading={gatewayLoading}>
            Check Gateways
          </Button>
        </div>
        {gatewayChecks.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {gatewayChecks.map(waba => (
              <div key={waba.wabaId} style={{ background: '#fff', borderRadius: 8, padding: 12, border: '1px solid #e5e7eb' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{waba.phone}</span>
                  <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>WABA: {waba.wabaId}</span>
                </div>
                {waba.configurations.length === 0 ? (
                  <div style={{ color: '#9ca3af', fontSize: '0.8rem' }}>No payment configurations found</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {waba.configurations.map((cfg, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: cfg.canReceivePayments ? '#f9fafb' : '#f3f4f6', borderRadius: 6, fontSize: '0.8rem' }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: cfg.canReceivePayments ? '#1a3a2a' : cfg.status === 'local_only' ? '#1a3a2a' : '#1a3a2a', flexShrink: 0 }} />
                        <span style={{ fontWeight: 600, minWidth: 140 }}>{cfg.name}</span>
                        <span className={`badge ${cfg.canReceivePayments ? 'captured' : 'failed'}`} style={{ fontSize: '0.7rem' }}>
                          {cfg.status}
                        </span>
                        <span style={{ color: '#6b7280' }}>{cfg.gateway}</span>
                        {cfg.mid && <span style={{ color: '#9ca3af', fontFamily: 'monospace', fontSize: '0.7rem' }}>MID: {cfg.mid}</span>}
                        {cfg.mcc && <span style={{ color: '#9ca3af', fontSize: '0.7rem' }}>MCC: {cfg.mcc}</span>}
                        {cfg.note && <span style={{ color: '#1a3a2a', fontSize: '0.7rem' }}>{cfg.note}</span>}
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ marginTop: 6, fontSize: '0.75rem', color: '#6b7280' }}>
                  {waba.activeConfigs}/{waba.totalConfigs} active
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Desktop Table */}
      <div className="pay-table-desktop">
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Phone</th>
                <th>Item</th>
                <th>Total</th>
                <th>Status</th>
                <th>Invoice</th>
                <th>Time</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paymentMessages.map(p => {
                const pa = p as any;
                const total = pa.paymentTotal ? `₹${(pa.paymentTotal / 100).toFixed(2)}` : p.content;
                const invoiceUrl = invoiceLinkFor( pa );
                return (
                  <tr key={p.id} className={pa.paymentStatus || p.status}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{pa.paymentReferenceId || '-'}</td>
                    <td>{p.senderPhone || '-'}</td>
                    <td>{pa.paymentItemName || '-'}</td>
                    <td style={{ fontWeight: 600 }}>{total}</td>
                    <td><span className={`badge ${pa.paymentStatus || p.status}`}>{pa.paymentStatus || p.status}</span></td>
                    <td>
                      {invoiceUrl ? (
                        <span style={{ display: 'flex', gap: 4 }}>
                          <a href={invoiceUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-ghost" style={{ minHeight: 32, minWidth: 'auto', padding: '4px 8px' }}>View</a>
                          <button onClick={() => downloadInvoicePdf(invoiceUrl, pa.paymentReferenceId || p.id)} className="btn btn-sm btn-ghost" style={{ minHeight: 32, minWidth: 'auto', padding: '4px 8px' }}>Save</button>
                        </span>
                      ) : '-'}
                    </td>
                    <td style={{ fontSize: '0.75rem' }}>{new Date(p.timestamp).toLocaleString()}</td>
                    <td>
                      <Button variant="ghost" size="sm" onClick={() => setEditPayment({ ...pa, id: p.id })}>Edit</Button>
                    </td>
                  </tr>
                );
              })}
              {paymentMessages.length === 0 && (
                <tr><td colSpan={8} className="empty">No payment records</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="pay-cards-mobile">
        {paymentMessages.map(p => {
          const pa = p as any;
          const total = pa.paymentTotal ? `₹${(pa.paymentTotal / 100).toFixed(2)}` : p.content;
          const invoiceUrl = invoiceLinkFor( pa );
          return (
            <div key={p.id} className="pay-card">
              <div className="pay-card-header">
                <span className="pay-card-ref" style={{ fontFamily: 'monospace' }}>{pa.paymentReferenceId || '-'}</span>
                <span className={`badge ${pa.paymentStatus || p.status}`}>{pa.paymentStatus || p.status}</span>
              </div>
              <div className="pay-card-body">
                <div className="pay-card-row"><span className="pay-card-label">Phone</span><span>{p.senderPhone || '-'}</span></div>
                <div className="pay-card-row"><span className="pay-card-label">Item</span><span>{pa.paymentItemName || '-'}</span></div>
                <div className="pay-card-row"><span className="pay-card-label">Total</span><span style={{ fontWeight: 600 }}>{total}</span></div>
                <div className="pay-card-row"><span className="pay-card-label">Time</span><span style={{ fontSize: '0.75rem' }}>{new Date(p.timestamp).toLocaleString()}</span></div>
              </div>
              <div className="pay-card-actions">
                {invoiceUrl && <a href={invoiceUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-ghost">View Invoice</a>}
                <Button variant="ghost" size="sm" onClick={() => setEditPayment({ ...pa, id: p.id })}>Edit</Button>
              </div>
            </div>
          );
        })}
        {paymentMessages.length === 0 && <div className="empty-state"><div className="empty-state-title">No payment records</div><div className="empty-state-description">Create a new payment to get started.</div></div>}
      </div>

      {/* Edit Payment Modal — proper Modal component */}
      <Modal
        isOpen={!!editPayment}
        onClose={() => setEditPayment(null)}
        title={`Edit Payment — ${editPayment?.paymentReferenceId || editPayment?.id || ''}`}
        size="md"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditPayment(null)}>Cancel</Button>
            <Button variant="primary" onClick={handleSavePayment} loading={editSaving}>Save</Button>
          </>
        }
      >
        {editPayment && (
          <div>
            {editFields.map(f => (
              <div key={f.key} style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#6b7280', marginBottom: 4, fontWeight: 500 }}>{f.label}</label>
                <input
                  type={f.type}
                  value={editPayment[f.key] ?? ''}
                  onChange={e => setEditPayment((prev: any) => ({ ...prev, [f.key]: e.target.value }))}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid #d1d5db', fontSize: '0.9rem' }}
                />
              </div>
            ))}
            <div style={{ marginBottom: 12 }}>
              {/* MIGRATION SHAPE (b) - the <label> is RETAINED with an `id` and the control
                  points at it with `labelledBy`. Its inline style is the same object the eight
                  field captions above it use, which `.ui-field-label` does not reproduce, so
                  moving the caption into the component would leave one caption in the modal a
                  different size, weight and colour from the rest. The control's own inline
                  object was APPEARANCE - an 8px radius, a 1.5px grey border, 0.9rem type - and
                  that is now the shared token box; only `width: 100%` survives as layout. */}
              <label
                id="paytab-status-label"
                style={{ display: 'block', fontSize: '0.8rem', color: '#6b7280', marginBottom: 4, fontWeight: 500 }}
              >Status</label>
              <Select
                labelledBy="paytab-status-label"
                value={editPayment.status || editPayment.paymentStatus || 'pending'}
                onChange={v => setEditPayment((prev: any) => ({ ...prev, status: v }))}
                options={PAYMENT_STATUS_OPTIONS}
                style={{ width: '100%' }}
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default PayTab;
