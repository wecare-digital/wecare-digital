/**
 * One reusable read-only service contract panel.
 *
 * Prices are the live ProductsTable projection, not staff-editable invoices.
 * The approved WhatsApp header and ORDER_DETAILS icon are server-supplied
 * presentation metadata; no outbound send or charging originates here.
 */
import React from 'react';
import { SERVICE_CHOICES } from '../../../config/services';
import { rupeesFromPaise, type ServicePrice, type ServiceWorkspacePriceSlug } from '../../../lib/servicePricing';
import PaymentTemplateMedia from '../pay/PaymentTemplateMedia';

interface Action { label: string; href: string; external?: boolean; }

interface Props {
  slug: ServiceWorkspacePriceSlug;
  label: string;
  summary: string;
  fulfilment: string;
  price?: ServicePrice;
  loading: boolean;
  actions?: readonly Action[];
  warning?: string;
}

const money = ( paise: number ): string => `₹${rupeesFromPaise( paise )}`;

export default function ServicePriceOverview (
  { slug, label, summary, fulfilment, price, loading, actions = [], warning }: Props,
) {
  const service = SERVICE_CHOICES.find( choice => choice.slug === slug );
  const published = price?.available === true;
  const breakdown = published ? price.breakdown : undefined;
  return (
    <section className="sco-panel" aria-label={ `${label} service contract` }>
      <header className="sco-head">
        <div>
          <p className="sco-eyebrow">Service · server-owned pricing</p>
          <h1>{label}</h1>
          <p>{summary}</p>
        </div>
      </header>

      <div className="sco-facts">
        <div>
          <small>Live catalog item price</small>
          <strong>{loading ? 'Loading…' : published ? money( price.paise ) : 'Unavailable'}</strong>
        </div>
        <div>
          <small>Estimated payable</small>
          <strong>{loading ? 'Loading…' : breakdown ? money( breakdown.totalPayablePaise ) : 'At checkout'}</strong>
        </div>
        <div>
          <small>SKU</small>
          <strong className="sco-mono">{service?.sku || (slug === 'shipments-track' ? 'SHT8M5P3' : '—')}</strong>
        </div>
        <div>
          <small>After payment / action</small>
          <strong className="sco-action">{fulfilment}</strong>
        </div>
      </div>

      {!loading && !published && (
        <p className="sco-warning" role="status">
          This price is not available from the live catalog. Do not quote a fixed
          amount or request payment from this screen.
        </p>
      )}
      {warning && <p className="sco-note" role="status">{warning}</p>}

      {breakdown && (
        <div className="sco-breakdown" aria-label={ `${label} live server quote` }>
          <h2>Server pricing breakdown</h2>
          <dl>
            <div><dt>Item</dt><dd>{money(breakdown.itemSubtotalPaise)}</dd></div>
            <div><dt>Supply GST</dt><dd>{money(breakdown.supplyGstPaise)}</dd></div>
            <div><dt>Delight</dt><dd>−{money(breakdown.delightPaise)}</dd></div>
            <div><dt>Express delivery</dt><dd>{money(breakdown.expressPaise)}</dd></div>
            <div><dt>Convenience fee</dt><dd>{money(breakdown.convenienceFeePaise)}</dd></div>
            <div><dt>GST on convenience fee</dt><dd>{money(breakdown.convenienceGstPaise)}</dd></div>
            <div className="sco-total"><dt>Estimated payable</dt><dd>{money(breakdown.totalPayablePaise)}</dd></div>
          </dl>
          <p>The payment Lambda independently freezes and validates the payable amount. This is a read-only preview.</p>
        </div>
      )}
      {published && price.templates && (
        <PaymentTemplateMedia serviceLabel={label} templates={price.templates} />
      )}

      {actions.length > 0 && (
        <nav className="sco-actions" aria-label={ `${label} operational actions` }>
          {actions.map(action => (
            <a key={action.label} href={action.href}
              {...(action.external ? {target:'_blank',rel:'noopener noreferrer'} : {})}>
              {action.label}
            </a>
          ))}
        </nav>
      )}

      <p className="sco-foot">
        Staff view only. Buying, uploading, downloading, and sending a WhatsApp
        payment request remain in their existing owner-verified workflows.
      </p>
      <style jsx>{`
        .sco-panel{min-width:0;display:grid;gap:18px;max-width:1130px;padding:4px 0 40px;color:var(--text)}
        .sco-head{display:flex;justify-content:space-between;gap:16px}
        .sco-head h1{margin:0;font-size:clamp(28px,3vw,40px);letter-spacing:-.04em}
        .sco-eyebrow{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin:0 0 5px}
        .sco-head p:last-child{max-width:780px;color:var(--text-muted);line-height:1.55;margin:9px 0 0}
        .sco-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
        .sco-facts>div{min-width:0;padding:17px;border:1px solid var(--border);border-radius:12px;background:var(--surface,#fff)}
        .sco-facts small{display:block;font-size:12px;font-weight:700;color:var(--text-muted);margin-bottom:8px}
        .sco-facts strong{display:block;font-size:20px;overflow-wrap:anywhere}
        .sco-facts .sco-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px}
        .sco-facts .sco-action{font-size:14px;line-height:1.4}
        .sco-warning,.sco-note{border-radius:11px;padding:13px 15px;line-height:1.5;font-size:13px;margin:0}
        .sco-warning{background:#fff7ed;border:1px solid #fdba74;color:#9a3412}
        .sco-note{background:var(--bg-secondary,#f8faf9);border:1px solid var(--border);color:var(--text-muted)}
        .sco-breakdown{border:1px solid var(--border);border-radius:12px;padding:17px;background:#fff}
        .sco-breakdown h2{font-size:16px;margin:0 0 10px}
        .sco-breakdown dl{margin:0}
        .sco-breakdown dl>div{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-light,var(--border));font-size:13px}
        .sco-breakdown dt{color:var(--text-muted)}
        .sco-breakdown dd{font-weight:750;margin:0}
        .sco-breakdown .sco-total{font-weight:800;font-size:16px}
        .sco-breakdown p,.sco-foot{font-size:12px;color:var(--text-muted);line-height:1.5;margin:0}
        .sco-breakdown p{margin-top:12px}
        .sco-actions{display:flex;flex-wrap:wrap;gap:10px}
        .sco-actions a{display:inline-flex;align-items:center;min-height:42px;padding:0 15px;border:1px solid var(--border);border-radius:11px;color:var(--accent);background:#fff;font-size:13px;font-weight:750;text-decoration:none}
        .sco-actions a:hover{background:var(--bg-secondary,#f8faf9)}
        .sco-actions a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
        @media(max-width:850px){.sco-facts{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:470px){.sco-facts{grid-template-columns:1fr}}
      `}</style>
    </section>
  );
}
