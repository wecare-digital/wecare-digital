/** Read-only operational snapshot of invoices created from Collect.
 * This is a scoped overview, not a payment-event stream or alternate ledger.
 */
import React from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';

const isRefunded = (row: api.Invoice): boolean =>
  (row.paymentStatus || '').toLowerCase() === 'refunded'
  || Boolean(row.refundId) || Boolean(row.refundAt);

const isCaptured = (row: api.Invoice): boolean =>
  !isRefunded(row) && ([ 'captured', 'paid' ].includes((row.paymentStatus || '').toLowerCase())
    || (row.status || '').toLowerCase() === 'paid');

const isPending = (row: api.Invoice): boolean =>
  !isCaptured(row) && !isRefunded(row) &&
  [ 'created', 'pending', 'pending_payment' ].includes((row.status || '').toLowerCase());

function money(value: number, currency = 'INR'): string {
  try {
    return new Intl.NumberFormat('en-IN', {style: 'currency', currency: currency || 'INR',
      maximumFractionDigits: 2}).format(value);
  } catch {
    return `${currency || 'INR'} ${value.toFixed(2)}`;
  }
}

function timestamp(value: number | undefined): number {
  if (!value) return 0;
  return value > 1e12 ? value : value * 1000;
}

const CollectOverview: React.FC = () => {
  const [rows, setRows] = React.useState<api.Invoice[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [refresh, setRefresh] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void api.listInvoicesEngine({limit: 500})
      .then(result => {
        if (!active) return;
        const loaded = result.invoices || [];
        // This page must never label Vault or Contribute invoices as Collect.
        setRows(loaded.filter(row => (row.entryPoint || '').toLowerCase() === 'pay_flow'));
      })
      .catch(() => { if (active) setError('Could not load Collect invoice overview.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);

  const recent = React.useMemo(() => [...rows]
    .sort((a, b) => timestamp(b.updatedAt || b.createdAt) - timestamp(a.updatedAt || a.createdAt))
    .slice(0, 8), [rows]);

  const captured = rows.filter(isCaptured);
  const pending = rows.filter(isPending);
  const refunded = rows.filter(isRefunded);
  const billed = rows.reduce((acc, row) => acc + (Number(row.total) || 0), 0);

  return (
    <section className="co" aria-labelledby="collect-overview-title">
      <header className="co-head">
        <div>
          <p className="co-kicker">COLLECT / DISPLAY</p>
          <h2 id="collect-overview-title">Collect overview</h2>
          <p>Read-only snapshot of Collect-created invoices in the latest 500 loaded records.
            Service-specific Vault and Contribute records remain in their own ledgers.</p>
        </div>
        <button type="button" className="co-refresh" onClick={() => setRefresh(x => x + 1)}
          disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
      </header>
      {error && <p className="co-error" role="alert">{error}</p>}
      <div className="co-stats" aria-label="Loaded Collect invoice counts">
        <div><small>Invoices</small><strong>{loading ? '—' : rows.length}</strong></div>
        <div><small>Captured</small><strong>{loading ? '—' : captured.length}</strong></div>
        <div><small>Pending</small><strong>{loading ? '—' : pending.length}</strong></div>
        <div><small>Refunded</small><strong>{loading ? '—' : refunded.length}</strong></div>
      </div>
      <div className="co-shortcuts">
        <Link href="/workspace/payments?view=collect&tab=create">Create a collection</Link>
        <Link href="/workspace/payments?view=collect&tab=create&invoices=saved">Review &amp; send saved invoices</Link>
        <Link href="/workspace/payments?view=ledger&ledger=invoices">Open invoice ledger</Link>
        <Link href="/workspace/payments?view=ledger&ledger=activity">Review payment activity</Link>
      </div>
      <section className="co-recent" aria-labelledby="co-recent-title">
        <header>
          <h3 id="co-recent-title">Recent Collect invoices</h3>
          <span>Latest stored state · not a complete event timeline</span>
        </header>
        {!loading && !error && rows.length === 0 &&
          <p className="co-empty">No Collect-created invoices in the loaded results. Older records may still be in Ledger.</p>}
        {loading && <p className="co-empty">Loading invoice records…</p>}
        {!loading && recent.length > 0 && (
          <div className="co-tablewrap">
            <table>
              <thead><tr><th>Invoice</th><th>Customer</th><th>State</th><th>Stored total</th><th></th></tr></thead>
              <tbody>
                {recent.map(row => (
                  <tr key={row.invoiceId}>
                    <td><strong>{row.invoiceNumber || row.referenceId || row.invoiceId}</strong></td>
                    <td>{row.customerName || 'Customer'}</td>
                    <td>{isRefunded(row) ? 'Refunded' : isCaptured(row) ? 'Captured' :
                      isPending(row) ? 'Pending' : (row.paymentStatus || row.status || 'Unknown')}</td>
                    <td>{money(Number(row.total) || 0, row.currency)}</td>
                    <td><Link href={`/workspace/payments?view=ledger&ledger=invoices&invoice=${encodeURIComponent(row.invoiceId)}`}>Details</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!loading && !error && <p className="co-foot">
        Stored amount across loaded Collect invoices: <strong>{money(billed)}</strong>.
        Totals are not a full financial reconciliation; use the ledger and gateway evidence for money decisions.
      </p>}
      <style jsx>{`
        .co{display:grid;gap:16px;max-width:1250px;min-width:0;padding:8px 0 28px;color:var(--text-primary)}
        .co-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}
        .co-kicker{color:var(--text-muted);font-size:11px;letter-spacing:.08em;font-weight:800;margin:0 0 5px}
        .co-head h2{margin:0 0 7px;font-size:clamp(22px,3vw,30px)}
        .co-head p:not(.co-kicker){color:var(--text-muted);font-size:13px;line-height:1.6;max-width:780px;margin:0}
        .co-refresh{border:1px solid var(--border);background:var(--surface);border-radius:9px;padding:10px 18px;min-height:44px;font:inherit;cursor:pointer}
        .co-refresh:disabled{opacity:.6;cursor:default}
        .co-error{color:#a52626;font-size:13px}
        .co-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
        .co-stats>div{padding:18px;border:1px solid var(--border);border-radius:13px;background:var(--surface);display:grid;gap:6px}
        .co-stats small{font-size:12px;color:var(--text-muted)}
        .co-stats strong{font-size:24px;line-height:1.2;font-weight:800}
        .co-shortcuts{display:flex;gap:10px;flex-wrap:wrap}
        .co-shortcuts :global(a){min-height:44px;border:1px solid var(--border);border-radius:10px;padding:11px 16px;color:var(--text-primary);text-decoration:none;font-size:13px;font-weight:700;display:inline-flex;align-items:center}
        .co-shortcuts :global(a:first-child){background:var(--lime)}
        .co-recent{border:1px solid var(--border);border-radius:13px;background:var(--surface);padding:16px;min-width:0}
        .co-recent header{display:flex;justify-content:space-between;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:11px}
        .co-recent h3{font-size:16px;margin:0}
        .co-recent header span{font-size:12px;color:var(--text-muted)}
        .co-tablewrap{overflow-x:auto}
        table{width:100%;border-collapse:collapse;text-align:left}
        td,th{padding:11px 9px;border-bottom:1px solid var(--border);font-size:12px;white-space:nowrap}
        th{color:var(--text-muted);font-weight:700}
        .co-tablewrap :global(a){color:var(--accent);font-weight:700}
        .co-empty,.co-foot{font-size:13px;color:var(--text-muted);line-height:1.6}
        .co-foot{margin:0}
        .co-refresh:focus-visible,.co-shortcuts :global(a:focus-visible),.co-tablewrap :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:740px){.co-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.co-head{display:grid}.co-shortcuts{display:grid}.co-shortcuts :global(a){justify-content:center}}
      `}</style>
    </section>
  );
};

export default CollectOverview;
