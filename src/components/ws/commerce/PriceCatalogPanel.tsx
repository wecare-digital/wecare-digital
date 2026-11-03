/**
 * Notion-inspired, image-free service price catalog for /ws/.
 * Every financial value is copied from the validated, read-only ProductsTable-backed
 * service-prices endpoint. Never calculate fees or submit payments here.
 */
import React from 'react';
import { SERVICE_CHOICES } from '../../../config/services';
import {
  fetchServiceWorkspacePrices, rupeesFromPaise,
  type ServicePrice, type ServiceWorkspacePriceSlug,
} from '../../../lib/servicePricing';

interface Item {
  slug: ServiceWorkspacePriceSlug;
  title: string;
  category: string;
  sku: string;
  description: string;
}

const ITEMS: readonly Item[] = [
  ...SERVICE_CHOICES.map(choice => ({
    slug: choice.slug,
    title: choice.label,
    category: choice.kind === 'VAULT' ? 'Private file' : 'Service',
    sku: choice.sku,
    description: choice.kind === 'VAULT'
      ? 'Access to a specific owner-verified private file. A generic Collect invoice cannot grant access.'
      : 'Catalog-priced service with a separately verified payment and fulfilment process.',
  })),
  { slug: 'shipments-track', title: 'Track Shipping', category: 'Shipping', sku: '—',
    description: 'A separate paid catalog item. Viewing a shipment in Orders is not a purchase.' },
  { slug: 'contribute', title: 'Contribute', category: 'Contribution', sku: '—',
    description: 'A voluntary catalog payment; not a request service or Vault entitlement.' },
];

const money = (paise: number) => '₹' + rupeesFromPaise(paise);

const PriceCatalogPanel: React.FC = () => {
  const [prices, setPrices] = React.useState<Record<ServiceWorkspacePriceSlug, ServicePrice> | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [refreshToken, setRefreshToken] = React.useState(0);
  const [selectedSlug, setSelectedSlug] = React.useState<ServiceWorkspacePriceSlug>(ITEMS[0].slug);
  const [search, setSearch] = React.useState('');
  const [checkedAt, setCheckedAt] = React.useState<Date | null>(null);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    void fetchServiceWorkspacePrices().then(result => {
      if (!active) return;
      setPrices(result);
      setCheckedAt(new Date());
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refreshToken]);

  const query = search.trim().toLowerCase();
  const matches = ITEMS.filter(item => !query || [item.title, item.category, item.sku, item.slug]
    .some(value => value.toLowerCase().includes(query)));
  const selected = ITEMS.find(item => item.slug === selectedSlug) || ITEMS[0];
  const price = prices?.[selected.slug];
  const breakdown = price?.available === true ? price.breakdown : undefined;
  const priced = ITEMS.filter(item => prices?.[item.slug]?.available === true).length;
  const complete = ITEMS.filter(item => {
    const value = prices?.[item.slug];
    return value?.available === true && !!value.breakdown;
  }).length;

  return (
    <section className="pc" aria-label="Text-only pricing catalog">
      <header className="pc-head">
        <div>
          <p className="pc-eyebrow">DATABASE / SERVER-VERIFIED PRICING</p>
          <h2>Pricing catalog</h2>
          <p>Choose a service to see the complete price breakup, without product images.</p>
        </div>
        <span className="pc-updated" role="status">
          <span className="pc-dot" aria-hidden="true" />
          {loading ? 'Loading live prices…'
            : checkedAt ? 'Checked ' + checkedAt.toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'}) : 'Live prices'}
        </span>
      </header>

      <div className="pc-counts" aria-label="Catalog summary">
        <span><strong>{ITEMS.length}</strong> entries</span>
        <span><strong>{loading ? '—' : priced}</strong> priced</span>
        <span><strong>{loading ? '—' : complete}</strong> complete bills</span>
      </div>

      <div className="pc-grid">
        <section className="pc-table" aria-label="Service database">
          <div className="pc-toolbar">
            <label>
              <span>Search</span>
              <input type="search" placeholder="Find a service or SKU…" value={search}
                onChange={event => setSearch(event.target.value)} />
            </label>
            <button type="button" disabled={loading}
              onClick={() => setRefreshToken(value => value + 1)}>
              {loading ? 'Refreshing…' : '↻ Refresh'}
            </button>
          </div>
          <div className="pc-columns" aria-hidden="true">
            <span>Name</span><span>Item price</span><span>Final estimate</span>
          </div>
          <div role="list" aria-label="Select service" className="pc-list">
            {matches.map(item => {
              const current = prices?.[item.slug];
              const detail = current?.available === true ? current.breakdown : undefined;
              return (
                <div key={item.slug} role="listitem">
                  <button type="button" aria-pressed={selectedSlug === item.slug}
                    className={selectedSlug === item.slug ? 'pc-row selected' : 'pc-row'}
                    onClick={() => setSelectedSlug(item.slug)}>
                    <span className="pc-name">
                      <span className="pc-page-icon" aria-hidden="true">≡</span>
                      <span><strong>{item.title}</strong>
                        <small>{item.category} · {loading ? 'Checking'
                          : current?.available !== true ? 'Unavailable'
                          : detail ? 'Full breakup' : 'Item price only'}</small>
                      </span>
                    </span>
                    <span className="pc-amount" data-wc-no-translate="true">
                      {loading ? '…' : current?.available === true ? money(current.paise) : '—'}
                    </span>
                    <span className="pc-amount pc-emphasis" data-wc-no-translate="true">
                      {loading ? '…' : detail ? money(detail.totalPayablePaise) : '—'}
                    </span>
                  </button>
                </div>
              );
            })}
            {!matches.length && <p className="pc-empty">No services match your search.</p>}
          </div>
          <footer className="pc-table-foot">Amounts are read-only catalog estimates, not issued invoices or payment requests.</footer>
        </section>

        <aside className="pc-detail" aria-label={selected.title + ' price breakdown'}>
          <div className="pc-detail-heading">
            <span className="pc-label">PRICE DETAILS</span>
            <h3>{selected.title}</h3>
            <p>{selected.description}</p>
            {selected.sku !== '—' && <span className="pc-sku">SKU · {selected.sku}</span>}
          </div>
          <div className="pc-highlights">
            <div><small>Catalog item price</small><strong data-wc-no-translate="true">
              {loading ? '…' : price?.available === true ? money(price.paise) : 'Unavailable'}
            </strong></div>
            <div><small>Final payable estimate</small><strong data-wc-no-translate="true">
              {loading ? '…' : breakdown ? money(breakdown.totalPayablePaise) : 'At checkout'}
            </strong></div>
          </div>
          {loading ? (
            <p role="status" className="pc-message">Reading the live pricing service…</p>
          ) : price?.available !== true ? (
            <p role="status" className="pc-message">Live pricing is unavailable. Do not quote a price or request a payment from this screen.</p>
          ) : !breakdown ? (
            <p role="status" className="pc-message">A catalog price exists, but no validated full breakdown was returned. Taxes, discounts and fees are not estimated here.</p>
          ) : (
            <div className="pc-bill">
              <h4>Full price breakup <small>SERVER QUOTE</small></h4>
              <dl>
                <div><dt>Base item price</dt><dd data-wc-no-translate="true">{money(breakdown.itemSubtotalPaise)}</dd></div>
                <div><dt>Supply GST (18%)</dt><dd data-wc-no-translate="true">+{money(breakdown.supplyGstPaise)}</dd></div>
                <div className="pc-discount"><dt>DELIGHT discount</dt><dd data-wc-no-translate="true">−{money(breakdown.delightPaise)}</dd></div>
                <div><dt>Express</dt><dd data-wc-no-translate="true">+{money(breakdown.expressPaise)}</dd></div>
                <div className="pc-subtotal"><dt>Before convenience fee</dt><dd data-wc-no-translate="true">{money(breakdown.collectionBeforeConveniencePaise)}</dd></div>
                <div><dt>Convenience fee</dt><dd data-wc-no-translate="true">+{money(breakdown.convenienceFeePaise)}</dd></div>
                <div><dt>GST on convenience fee (18%)</dt><dd data-wc-no-translate="true">+{money(breakdown.convenienceGstPaise)}</dd></div>
                <div className="pc-total"><dt>Final payable <small>Estimated customer amount</small></dt>
                  <dd data-wc-no-translate="true">{money(breakdown.totalPayablePaise)}</dd></div>
              </dl>
              <p className="pc-legal">Checkout independently verifies and freezes the exact payable amount.</p>
            </div>
          )}
          <div className="pc-tip">
            <strong>Read-only price reference</strong>
            <p>DELIGHT, Express, GST and fees are server-owned. Collect invoices and Vault file access retain their separate verified payment workflows.</p>
          </div>
        </aside>
      </div>
      {!loading && complete === 0 && (
        <p role="status" className="pc-empty">No complete live price breakups are available. Refresh or check an official checkout quote.</p>
      )}

      <style jsx>{`
        .pc{display:grid;gap:16px;min-width:0;color:var(--text,#1f2937)}
        .pc-head{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px}
        .pc-head h2{margin:0;font-size:clamp(24px,3vw,30px);font-weight:750;letter-spacing:-.045em}
        .pc-head p:last-child{max-width:580px;margin:7px 0 0;color:var(--text-muted,#6b7280);font-size:13px;line-height:1.55}
        .pc-eyebrow{font-size:10px;letter-spacing:.11em;font-weight:750;color:var(--text-muted,#6b7280);margin:0 0 5px}
        .pc-updated{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--text-muted,#6b7280);padding-top:4px}
        .pc-dot{width:7px;height:7px;background:var(--accent,#1a3a2a);border-radius:50%}
        .pc-counts{display:flex;flex-wrap:wrap;gap:9px;font-size:12px;color:var(--text-muted,#6b7280)}
        .pc-counts span{padding:5px 9px;background:#fff;border:1px solid var(--border,#e5e7eb);border-radius:7px}
        .pc-counts strong{color:var(--text,#1f2937)}
        .pc-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0;align-items:start}
        .pc-table,.pc-detail{min-width:0;background:var(--surface,#fff);border:1px solid var(--border,#e5e7eb);border-radius:12px;overflow:hidden}
        .pc-toolbar{display:flex;align-items:end;gap:9px;padding:13px;border-bottom:1px solid var(--border,#e5e7eb)}
        .pc-toolbar label{display:grid;gap:5px;flex:1;min-width:0;font-size:11px;color:var(--text-muted,#6b7280);font-weight:650}
        .pc-toolbar input{width:100%;min-width:0;box-sizing:border-box;padding:10px 11px;background:#fff;border:1px solid var(--border,#e5e7eb);border-radius:7px;font:inherit;font-size:13px;color:var(--text,#1f2937)}
        .pc-toolbar button{min-height:40px;border:1px solid var(--border,#e5e7eb);border-radius:7px;padding:0 12px;background:#fff;color:var(--text,#1f2937);font-size:12px;font-weight:650;cursor:pointer}
        .pc-toolbar button:disabled{cursor:default;opacity:.6}
        .pc-toolbar input:focus-visible,.pc-toolbar button:focus-visible,.pc-row:focus-visible{outline:2px solid var(--accent,#1a3a2a);outline-offset:-2px}
        .pc-columns,.pc-row{display:grid;grid-template-columns:minmax(120px,1fr) minmax(75px,.46fr) minmax(92px,.58fr);gap:8px;align-items:center}
        .pc-columns{background:var(--bg-secondary,#f9fafb);border-bottom:1px solid var(--border,#e5e7eb);padding:9px 13px;color:var(--text-muted,#6b7280);font-size:10px;font-weight:750}
        .pc-columns span:not(:first-child){text-align:right}
        .pc-row{width:100%;min-height:61px;border:0;border-bottom:1px solid var(--border,#e5e7eb);padding:11px 13px;background:#fff;color:var(--text,#1f2937);cursor:pointer;text-align:left;font:inherit}
        .pc-list>div:last-child .pc-row{border-bottom:0}
        .pc-row:hover{background:var(--bg-secondary,#f9fafb)}.pc-row.selected{background:var(--lime-tint,rgba(209,244,112,.22))}
        .pc-name{display:flex;align-items:center;gap:9px;min-width:0}
        .pc-page-icon{display:grid;place-items:center;flex:0 0 auto;width:26px;height:29px;border:1px solid var(--border,#e5e7eb);border-radius:5px;background:#fff;font-size:16px;color:var(--text-muted,#6b7280)}
        .pc-name>span:last-child{display:grid;gap:3px;min-width:0}
        .pc-name strong{font-size:12px;overflow-wrap:anywhere}.pc-name small{font-size:10px;line-height:1.3;color:var(--text-muted,#6b7280)}
        .pc-amount{font-size:12px;font-weight:650;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
        .pc-emphasis{font-weight:800;color:var(--accent,#1a3a2a)}
        .pc-table-foot{padding:12px 13px;background:var(--bg-secondary,#f9fafb);color:var(--text-muted,#6b7280);font-size:11px;line-height:1.6}
        .pc-detail{padding:17px;display:grid;gap:17px}
        .pc-detail-heading{display:grid;gap:7px}
        .pc-label{width:max-content;border:1px solid var(--border,#e5e7eb);border-radius:5px;font-size:10px;font-weight:750;letter-spacing:.08em;padding:4px 7px;color:var(--text-muted,#6b7280)}
        .pc-detail-heading h3{font-size:24px;letter-spacing:-.04em;margin:0}
        .pc-detail-heading p{font-size:12px;line-height:1.6;color:var(--text-muted,#6b7280);margin:0}
        .pc-sku{font-size:11px;color:var(--text-muted,#6b7280);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        .pc-highlights{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
        .pc-highlights>div{display:grid;gap:7px;min-width:0;background:var(--bg-secondary,#f9fafb);border:1px solid var(--border,#e5e7eb);border-radius:9px;padding:12px}
        .pc-highlights small{font-size:11px;color:var(--text-muted,#6b7280)}.pc-highlights strong{font-size:clamp(15px,2vw,21px);font-variant-numeric:tabular-nums;white-space:nowrap}
        .pc-message{margin:0;padding:16px;border:1px dashed var(--border,#e5e7eb);border-radius:9px;color:var(--text-muted,#6b7280);font-size:12px;line-height:1.6}
        .pc-bill{border:1px solid var(--border,#e5e7eb);border-radius:9px;padding:14px}
        .pc-bill h4{display:flex;justify-content:space-between;gap:8px;margin:0 0 8px;font-size:14px}
        .pc-bill h4 small{font-size:9px;letter-spacing:.08em;color:var(--text-muted,#6b7280)}
        .pc-bill dl{margin:0}.pc-bill dl>div{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--border,#e5e7eb);font-size:12px}
        .pc-bill dt{color:var(--text-muted,#6b7280)}.pc-bill dd{margin:0;text-align:right;white-space:nowrap;font-weight:670;font-variant-numeric:tabular-nums}
        .pc-bill dl>.pc-discount dd{color:#176440}.pc-bill dl>.pc-subtotal{border-bottom-style:dashed}
        .pc-bill dl>.pc-total{margin-top:10px;padding:14px 11px;border:0;border-radius:8px;background:var(--lime-tint,rgba(209,244,112,.22));align-items:center}
        .pc-bill dl>.pc-total dt{font-size:14px;font-weight:780;color:var(--text,#1f2937)}
        .pc-bill dl>.pc-total dt small{display:block;margin-top:3px;font-size:10px;font-weight:500;color:var(--text-muted,#6b7280)}
        .pc-bill dl>.pc-total dd{font-size:24px;font-weight:800;color:var(--accent,#1a3a2a);letter-spacing:-.035em}
        .pc-legal{margin:13px 0 0;font-size:10px;line-height:1.5;color:var(--text-muted,#6b7280)}
        .pc-tip{border-left:3px solid var(--border,#e5e7eb);padding-left:12px}
        .pc-tip strong{font-size:12px}.pc-tip p{margin:5px 0 0;font-size:11px;line-height:1.55;color:var(--text-muted,#6b7280)}
        .pc-empty{margin:0;padding:18px 13px;font-size:12px;color:var(--text-muted,#6b7280)}
        @media(min-width:1050px){.pc-grid{grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr)}.pc-detail{position:sticky;top:14px}}
        @media(max-width:560px){.pc-row,.pc-columns{grid-template-columns:minmax(100px,1fr) 73px 87px;gap:4px}.pc-row{padding:11px 8px}.pc-columns{padding:9px 8px}.pc-page-icon{display:none}.pc-amount,.pc-name strong{font-size:11px}.pc-name small{font-size:9px}.pc-detail{padding:14px}.pc-highlights{grid-template-columns:1fr}.pc-bill dl>.pc-total dd{font-size:20px}}
      `}</style>
    </section>
  );
};

export default PriceCatalogPanel;
