/**
 * Contribute in Pay & Flow: a proposal-only, staff readback.
 *
 * Do not turn this screen into a generic invoice or native WhatsApp sender.
 * Contributions use BLOG_CONTRIBUTION settlement, not a Vault service grant.
 * Only a backend-frozen, purpose-bound quote may enable an eventual payment action.
 */
import React from 'react';
import Link from 'next/link';
import PaymentTemplateMedia from './PaymentTemplateMedia';
import ContributeStaffControls from './ContributeStaffControls';
import {
  fetchContributionPrice, fetchServicePrices, rupeesFromPaise,
  type ServicePaymentTemplates, type ServicePrice,
} from '../../../lib/servicePricing';

const TARGET_TOTAL_PAISE = 30000;
const EXPRESS_PAISE = 1500;

/**
 * Current contribution policy is fee/tax/Delight exempt. Treat Express as an
 * INTERNAL allocation within the target, not an invented customer fee.
 * This is not the live catalog price or a payment quote.
 */
const VOLUNTARY_CONTRIBUTION_ALLOCATION_PAISE = TARGET_TOTAL_PAISE - EXPRESS_PAISE;

/**
 * Alternative worked example if Finance separately approves applying the
 * existing Vault/Collect tax + fee + Delight policy to Contribute.
 * Pre-calculated in integer paise using checkout_pricing.round_half_up and
 * default_coupon.delight_paise. NOT a client-side pricing engine.
 *
 * 235.41 + 42.37 - 1.38 + 15.00 + 7.29 + 1.31 = 300.00
 */
const TAXABLE_EXAMPLE = {
  itemPaise: 23541,
  supplyGstPaise: 4237,
  delightPaise: 138,
  expressPaise: EXPRESS_PAISE,
  conveniencePaise: 729,
  convenienceGstPaise: 131,
} as const;
const TAXABLE_EXAMPLE_TOTAL_PAISE = TAXABLE_EXAMPLE.itemPaise
  + TAXABLE_EXAMPLE.supplyGstPaise - TAXABLE_EXAMPLE.delightPaise
  + TAXABLE_EXAMPLE.expressPaise + TAXABLE_EXAMPLE.conveniencePaise
  + TAXABLE_EXAMPLE.convenienceGstPaise;

const UNAVAILABLE: ServicePrice = { available: false };
const money = (paise: number) => '₹' + rupeesFromPaise(paise);

const ContributePaymentPlan: React.FC = () => {
  const [price, setPrice] = React.useState<ServicePrice>(UNAVAILABLE);
  const [templates, setTemplates] = React.useState<ServicePaymentTemplates | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [refreshSeq, setRefreshSeq] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    void Promise.all([fetchContributionPrice(), fetchServicePrices()])
      .then(([nextPrice, allPrices]) => {
        if (!active) return;
        setPrice(nextPrice);
        // This is the existing, shared, server-declared payment template/media,
        // not a new contribution-specific registered template or a send token.
        setTemplates(allPrices.vault?.available ? allPrices.vault.templates || null : null);
      })
      .catch(() => { if (active) { setPrice(UNAVAILABLE); setTemplates(null); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refreshSeq]);

  return (
    <section className="contribute-pay" aria-label="Contribute native payment proposal">
      <header className="contribute-header">
        <p>PAY &amp; FLOW / CONTRIBUTE</p>
        <h2>Contribute · Review &amp; Pay</h2>
        <span>Proposed customer total: <strong>{money(TARGET_TOTAL_PAISE)}</strong></span>
      </header>

      <div className="contribute-notice" role="status">
        <strong>Planning preview only — payment sending is not enabled.</strong>
        <p>The live Contribute catalogue still sets its own price and uses a voluntary-contribution,
          fee-exempt checkout. These worked examples do not change the catalog, freeze a quote,
          reserve a payment, generate an invoice, or send a WhatsApp message.</p>
      </div>

      <ContributeStaffControls
        price={price}
        templates={templates}
        loadingPrice={loading}
        refreshPrice={() => setRefreshSeq(current => current + 1)}
      />

      <div className="contribute-grid">
        <article>
          <h3>Existing contribution accounting</h3>
          <p>Keep the existing tax and fee exemptions. Allocate Express internally from the
            customer's fixed {money(TARGET_TOTAL_PAISE)}, rather than charge it again.</p>
          <dl>
            <div><dt>Contribution allocation</dt><dd>{money(VOLUNTARY_CONTRIBUTION_ALLOCATION_PAISE)}</dd></div>
            <div><dt>Express allocation (within total)</dt><dd>{money(EXPRESS_PAISE)}</dd></div>
            <div><dt>Delight</dt><dd>₹0</dd></div>
            <div><dt>Convenience and fee GST</dt><dd>₹0</dd></div>
            <div className="total"><dt>Customer total</dt><dd>{money(TARGET_TOTAL_PAISE)}</dd></div>
          </dl>
        </article>

        <article>
          <h3>Alternative: Vault-style taxable calculation</h3>
          <p>Use this example only if Finance establishes that Contribute is a taxable supply
            eligible for the existing GST, Delight and convenience-fee treatment.</p>
          <dl>
            <div><dt>Item base</dt><dd>{money(TAXABLE_EXAMPLE.itemPaise)}</dd></div>
            <div><dt>Supply GST (18%)</dt><dd>+{money(TAXABLE_EXAMPLE.supplyGstPaise)}</dd></div>
            <div><dt>Delight (0.5%)</dt><dd>−{money(TAXABLE_EXAMPLE.delightPaise)}</dd></div>
            <div><dt>Express</dt><dd>+{money(TAXABLE_EXAMPLE.expressPaise)}</dd></div>
            <div><dt>Convenience (2.5%)</dt><dd>+{money(TAXABLE_EXAMPLE.conveniencePaise)}</dd></div>
            <div><dt>GST on convenience (18%)</dt><dd>+{money(TAXABLE_EXAMPLE.convenienceGstPaise)}</dd></div>
            <div className="total"><dt>Illustrative customer total</dt><dd>{money(TAXABLE_EXAMPLE_TOTAL_PAISE)}</dd></div>
          </dl>
          {TAXABLE_EXAMPLE_TOTAL_PAISE !== TARGET_TOTAL_PAISE &&
            <p className="contribute-error" role="alert">This sample does not reconcile to the target.</p>}
        </article>
      </div>

      <section className="contribute-template" aria-label="Existing Meta native payment template reference">
        <h3>Native WhatsApp Review &amp; Pay template</h3>
        <p>The existing approved template is reusable. Its actual order details and payable
          amount must be constructed by the canonical server, never entered into a generic
          template picker or copied from these examples.</p>
        <dl>
          <div><dt>Server-listed template</dt><dd><code>{templates?.nativePay || 'Not verified by pricing API'}</code></dd></div>
          <div><dt>Server-listed Meta ID</dt><dd><code>{templates?.templateIds?.nativePay || 'Not verified by pricing API'}</code></dd></div>
          <div><dt>Live Contribute catalog item</dt><dd>{loading ? 'Loading…' : price.available ? money(price.paise) : 'Unavailable'}</dd></div>
          <div><dt>Proposed customer payable</dt><dd>{money(TARGET_TOTAL_PAISE)} · not yet quoted by backend</dd></div>
        </dl>
        <details>
          <summary>View shared payment header and order-item image</summary>
          <PaymentTemplateMedia templates={templates} serviceLabel="Contribute reference" signedPreview />
        </details>
      </section>

      <div className="contribute-footer">
        <p>Before enabling Send: agree the contribution tax classification; update the live
          catalog and purpose-specific frozen quote; verify exact {money(TARGET_TOTAL_PAISE)}
          in the payment request, capture ledger and customer receipt; preserve the existing
          contribution settlement and duplicate-send protections. No customer should receive
          a payment request from this preview.</p>
        <Link href="/workspace/service?view=contribute">See current Contribute catalog and payments</Link>
      </div>

      <style jsx>{`
        .contribute-pay{max-width:1070px;min-width:0;display:grid;gap:16px;padding:12px 0 32px}
        .contribute-header p{margin:0 0 6px;font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--text-muted)}
        .contribute-header h2{margin:0 0 8px;font-size:clamp(22px,3vw,30px);color:var(--text-primary)}
        .contribute-header span{color:var(--text-muted);font-size:14px}
        .contribute-header span strong{color:var(--text-primary);font-size:18px}
        .contribute-notice{border:1px solid #cabf9c;border-radius:12px;padding:14px;background:var(--surface)}
        .contribute-notice strong{font-size:13px}
        .contribute-notice p,.contribute-grid p,.contribute-template p,.contribute-footer p{font-size:13px;line-height:1.6;color:var(--text-muted);margin:7px 0 0}
        .contribute-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
        .contribute-grid article,.contribute-template,.contribute-footer{min-width:0;border:1px solid var(--border);border-radius:13px;padding:17px;background:var(--surface)}
        h3{font-size:16px;line-height:1.4;margin:0 0 8px;color:var(--text-primary)}
        dl{display:grid;gap:0;margin:14px 0 0}
        dl>div{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}
        dl>div:last-child{border-bottom:0}
        dt{min-width:0;font-size:12px;color:var(--text-muted)}
        dd{margin:0;text-align:right;font-size:13px;font-weight:750;color:var(--text-primary);overflow-wrap:anywhere}
        .total{border-top:2px solid var(--border)}
        .total dt,.total dd{font-size:15px;font-weight:800;color:var(--text-primary)}
        .contribute-error{color:#a32626!important;font-weight:750}
        .contribute-template details{margin-top:14px}
        .contribute-template summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-size:13px;font-weight:700}
        .contribute-template code{font-size:11px}
        .contribute-footer{display:grid;justify-items:start;gap:12px}
        .contribute-footer a{min-height:44px;display:inline-flex;align-items:center;padding:7px 14px;border-radius:10px;border:1px solid var(--border);font-size:13px;font-weight:750;text-decoration:none;color:var(--text-primary)}
        .contribute-footer a:focus-visible,.contribute-template summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:680px){.contribute-grid{grid-template-columns:1fr}.contribute-grid article,.contribute-template,.contribute-footer{padding:13px}.contribute-footer a{width:100%;box-sizing:border-box;justify-content:center}}
      `}</style>
    </section>
  );
};

export default ContributePaymentPlan;
