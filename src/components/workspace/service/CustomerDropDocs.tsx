/**
 * Customer Drop Docs operations (paid F003). Customer uploads originate from
 * WhatsApp's owner-bound Flow; staff NEVER upload a file from this surface.
 * Vault's SecureFiles workspace is the staff upload/publish path.
 *
 * Everything here is read-only except deliberate staff document-review actions.
 * Payment quotes, approved template names/IDs and media come from the canonical
 * /ecommerce/service-prices projection, not browser constants.
 */
import React from 'react';
import * as api from '../../../api/client';
import type { ApiFailure, Document as ServiceDocument } from '../../../api/client';
import { openExternal } from '../../../lib/capacitor';
import { fetchServicePrices, rupeesFromPaise, type ServicePrice } from '../../../lib/servicePricing';
import { useToastContext } from '../../../contexts/ToastContext';
import ServiceDataState from '../../../components/service/ServiceDataState';
import PaymentTemplateMedia from '../pay/PaymentTemplateMedia';

function maskedPhone(value?: string): string {
  const digits = (value || '').replace(/\D/g, '');
  return digits ? '••••' + digits.slice(-4) : 'Not recorded';
}

function money(paise?: number): string {
  return typeof paise === 'number' && Number.isSafeInteger(paise) && paise >= 0
    ? '₹' + rupeesFromPaise(paise) : 'Unavailable';
}

function when(ts?: number): string {
  if (!ts) return 'Not recorded';
  return new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function CustomerDropDocs() {
  const toast = useToastContext();
  const [rows, setRows] = React.useState<ServiceDocument[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [failure, setFailure] = React.useState<ApiFailure | null>(null);
  const [price, setPrice] = React.useState<ServicePrice | null>(null);
  const [priceLoading, setPriceLoading] = React.useState(true);
  const [saving, setSaving] = React.useState('');

  const refresh = React.useCallback(async () => {
    setLoading(true);
    const { data, failures } = await api.collectApiFailures(
      () => api.listDocuments({ source: 'flow' }),
    );
    const documents = data.documents || [];
    // Never mix manual Vault uploads or unrelated Flows into paid F003.
    const paidF003 = documents.filter(doc =>
      doc.source === 'flow' && !!doc.dropDocsRequestId
      && !!doc.dropDocsPaymentAttemptId,
    );
    setRows(paidF003);
    setFailure(documents.length === 0 && failures.length ? failures[0] : null);
    setLoading(false);
  }, []);

  React.useEffect(() => { void refresh(); }, [refresh]);
  React.useEffect(() => {
    let active = true;
    void fetchServicePrices().then(prices => {
      if (active) { setPrice(prices['drop-docs'] || null); setPriceLoading(false); }
    }).catch(() => { if (active) { setPrice(null); setPriceLoading(false); } });
    return () => { active = false; };
  }, []);

  const review = async (doc: ServiceDocument, status: string) => {
    if (saving) return;
    setSaving(doc.documentId);
    try {
      const ok = await api.updateDocument(doc.documentId, { status });
      if (!ok) { toast.error('Could not update the document review status'); return; }
      toast.success('Document review status updated');
      await refresh();
    } finally { setSaving(''); }
  };

  const download = async (doc: ServiceDocument) => {
    const url = await api.getDocumentDownloadUrl(doc.documentId);
    if (url) void openExternal(url);
    else toast.error('Private document download unavailable');
  };

  const live = price?.available === true;
  const breakdown = live ? price.breakdown : undefined;
  const templates = live ? price.templates : undefined;
  const ids = templates?.templateIds;
  const journey = [
    { label: 'Review & Pay', template: templates?.nativePay, id: ids?.nativePay,
      gate: 'Customer authorizes one server-priced payment' },
    { label: 'Order status: processing → completed', template: templates?.orderStatus, id: ids?.orderStatus,
      gate: 'Provider-verified capture; two distinct status sends' },
    { label: 'GST invoice image + Leave Review', template: templates?.receipt, id: ids?.receipt,
      gate: 'One paid invoice; captured payment and stored image' },
    { label: 'Customer uploads documents (F003)', template: templates?.delivery, id: ids?.delivery,
      gate: 'Only after invoice-send gate; owner-bound paid Flow session' },
  ];

  return (
    <section className="cdd">
      <header className="cdd-head">
        <div>
          <p className="cdd-eyebrow">Service / Drop Docs / Customer uploads</p>
          <h1>Drop Docs</h1>
          <p>Customers upload their own documents through the paid WhatsApp Drop Docs Flow. Staff review received files here. <strong>Staff file uploads and publication belong in Vault.</strong></p>
        </div>
        <button type="button" onClick={() => { void refresh(); }} disabled={loading}>Refresh submissions</button>
      </header>

      <section className="cdd-panel" aria-label="Live Drop Docs price and payable amount">
        <h2>Live customer amount</h2>
        <div className="cdd-prices">
          <div><small>Catalog price (one service)</small><strong>{priceLoading ? 'Loading…' : live ? money(price.paise) : 'Unavailable'}</strong></div>
          <div><small>Estimated total payable</small><strong>{priceLoading ? 'Loading…' : breakdown ? money(breakdown.totalPayablePaise) : 'At checkout'}</strong></div>
        </div>
        {breakdown && (
          <dl className="cdd-breakdown">
            <div><dt>GST on service</dt><dd>{money(breakdown.supplyGstPaise)}</dd></div>
            <div><dt>Delight discount</dt><dd>−{money(breakdown.delightPaise)}</dd></div>
            <div><dt>Express</dt><dd>{money(breakdown.expressPaise)}</dd></div>
            <div><dt>Convenience fee</dt><dd>{money(breakdown.convenienceFeePaise)}</dd></div>
            <div><dt>GST on fee</dt><dd>{money(breakdown.convenienceGstPaise)}</dd></div>
          </dl>
        )}
        <p>Read-only ProductsTable quote. The checkout independently verifies the exact amount in paise; no payment can start from this screen.</p>
      </section>

      <section className="cdd-panel" aria-label="WhatsApp customer templates, IDs and timing">
        <h2>Payment, invoice and customer-upload sequence</h2>
        <ol className="cdd-journey">
          {journey.map(step => (
            <li key={step.label}>
              <strong>{step.label}</strong>
              <span>{step.template || 'Server template unavailable'} · Registered Meta ID: {step.id || 'Not available'}</span>
              <small>{step.gate}</small>
            </li>
          ))}
        </ol>
        <p><strong>Timing:</strong> Transitions are triggered by verified payment and invoice state, not a promised number of seconds. Provider acceptance, delivery and read are different events; any message spacing cannot guarantee handset order.</p>
        <p>Registered template IDs are read-only audit metadata; a listed ID does not prove current Meta approval or that its Flow button points to a working published Flow.</p>
        <PaymentTemplateMedia serviceLabel="Drop Docs" templates={templates} />
      </section>

      <section className="cdd-panel" aria-label="Customer-submitted Drop Docs files">
        <div className="cdd-rowhead">
          <div><h2>Customer-submitted files</h2>
            <p>Only F003 document records linked to a paid request, payment attempt and customer are shown. Manual Vault uploads are excluded.</p>
          </div>
          <span>{loading ? 'Loading…' : String(rows.length) + ' document(s)'}</span>
        </div>
        <ServiceDataState loading={loading} failure={failure}
          empty={rows.length === 0} emptyLabel="No paid customer Drop Docs uploads found" onRetry={refresh}>
          <div className="cdd-records">
            {rows.map(doc => (
              <article className="cdd-record" key={doc.documentId}>
                <div className="cdd-record-main">
                  <strong>{doc.fileName || doc.documentRef || 'Customer document'}</strong>
                  <small>{doc.customerName || 'Customer'} · {maskedPhone(doc.customerPhone)} · {when(doc.createdAt)}</small>
                  <small>Request {doc.dropDocsRequestId} · {doc.orderNumber || 'Order linked to request'} · Status: {doc.status || 'unknown'}</small>
                  {doc.notes && <p>{doc.notes}</p>}
                </div>
                <div className="cdd-record-actions">
                  <button type="button" onClick={() => { void download(doc); }}>Download for review</button>
                  {!doc.archivedAt && doc.status !== 'approved' && (
                    <button type="button" disabled={!!saving}
                      onClick={() => { void review(doc, 'approved'); }}>Approve</button>
                  )}
                  {!doc.archivedAt && doc.status !== 'rejected' && (
                    <button type="button" disabled={!!saving}
                      onClick={() => { void review(doc, 'rejected'); }}>Reject</button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </ServiceDataState>
      </section>
      <style jsx>{`
        .cdd{max-width:1150px;display:grid;gap:18px;color:var(--text)}
        .cdd-head{display:flex;align-items:start;justify-content:space-between;gap:18px}
        .cdd-head h1{font-size:32px;margin:3px 0 9px}
        .cdd-head p{line-height:1.55;max-width:760px;color:var(--text-muted)}
        .cdd-eyebrow{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}
        .cdd button{cursor:pointer;border:1px solid var(--border);background:var(--surface);padding:10px 13px;border-radius:9px;font-weight:650;color:var(--text)}
        .cdd button:disabled{opacity:.5;cursor:not-allowed}
        .cdd-panel{border:1px solid var(--border);border-radius:13px;padding:18px;background:var(--surface)}
        .cdd-panel h2{font-size:19px;margin:0 0 14px}
        .cdd-panel p{color:var(--text-muted);line-height:1.5;margin:12px 0}
        .cdd-prices{display:flex;flex-wrap:wrap;gap:25px}
        .cdd-prices div{display:grid;gap:4px}
        .cdd-prices small,.cdd-journey small{color:var(--text-muted)}
        .cdd-prices strong{font-size:25px}
        .cdd-breakdown{display:flex;flex-wrap:wrap;gap:8px 22px;margin:14px 0}
        .cdd-breakdown div{display:flex;gap:8px}
        .cdd-breakdown dt{color:var(--text-muted)}
        .cdd-breakdown dd{margin:0;font-weight:700}
        .cdd-journey{display:grid;gap:9px;padding-left:22px}
        .cdd-journey li{padding:10px 12px;background:var(--bg-secondary);border-radius:9px}
        .cdd-journey li strong,.cdd-journey li span,.cdd-journey li small{display:block;line-height:1.55}
        .cdd-journey li span{overflow-wrap:anywhere;font-size:13px}
        .cdd-rowhead{display:flex;align-items:start;justify-content:space-between;gap:12px}
        .cdd-rowhead h2{margin-bottom:2px}
        .cdd-records{display:grid;gap:10px}
        .cdd-record{display:flex;justify-content:space-between;gap:14px;padding:14px;border:1px solid var(--border);border-radius:10px}
        .cdd-record-main{display:grid;gap:5px;min-width:0;overflow-wrap:anywhere}
        .cdd-record-main small{color:var(--text-muted)}
        .cdd-record-main p{margin:4px 0}
        .cdd-record-actions{display:flex;align-items:start;flex-wrap:wrap;gap:7px}
        @media(max-width:700px){.cdd-head,.cdd-record{flex-direction:column}.cdd-record-actions{width:100%}}
      `}</style>
    </section>
  );
}
