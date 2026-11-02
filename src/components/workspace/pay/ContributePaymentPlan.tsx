import React from 'react';
import type {Contact} from '../../../api/client';
import ContributeStaffControls from './ContributeStaffControls';
import PaymentTemplateMedia from './PaymentTemplateMedia';
import {fetchContributionPrice, rupeesFromPaise, type ServicePrice} from '../../../lib/servicePricing';

/** One live working surface. Both legacy Display/Create bookmarks reach the form. */
export default function ContributePaymentPlan(_props: {workspaceView?: 'display' | 'create';customer?:Contact|null;unified?:boolean}) {
  const [price, setPrice] = React.useState<ServicePrice>({available:false});
  const [loading, setLoading] = React.useState(true);
  const [revision, setRevision] = React.useState(0);
  const [checkedAt, setCheckedAt] = React.useState('');
  React.useEffect(() => {
    let active = true; setLoading(true); setPrice({available:false});
    void fetchContributionPrice().then(next => {if(active){setPrice(next);setCheckedAt(new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}));}})
      .catch(() => {if(active)setPrice({available:false});})
      .finally(() => {if(active)setLoading(false);});
    return () => {active=false;};
  },[revision]);
  const b = price.available ? price.breakdown : undefined;
  const money = (n: number) => (n<0?'−':'')+'₹'+rupeesFromPaise(Math.abs(n));
  return <section className="contribute-live" aria-label="Live contribution payment">
    <header className="contribute-top" style={_props.unified?{display:'none'}:undefined}><div><p>CONTRIBUTE</p><h2>Request a contribution</h2><span>Select a customer, review ₹300 and send Review &amp; Pay.</span></div><div className="contribute-amount"><small>Customer pays</small><strong>{loading?'Checking…':b?money(b.totalPayablePaise):'Unavailable'}</strong><small>{loading?'Reading live quote':checkedAt?`Checked ${checkedAt}`:'Quote unavailable'}</small></div></header>
    <div className="contribute-layout"><ContributeStaffControls customer={_props.customer} unified={_props.unified} price={price} templates={price.available?price.templates||null:null} loadingPrice={loading} refreshPrice={() => setRevision(n=>n+1)} />
      <aside className="quote-panel"><h3>Payment breakdown</h3>{b?<dl>{[['Item',b.itemSubtotalPaise],['Supply GST',b.supplyGstPaise],['Delight',-b.delightPaise],['Express',b.expressPaise],['Convenience',b.convenienceFeePaise],['GST on convenience',b.convenienceGstPaise],['Total',b.totalPayablePaise]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{money(Number(value))}</dd></div>)}</dl>:<p role="status">Live quote unavailable. Reload to continue.</p>}<button type="button" disabled={loading} onClick={()=>setRevision(n=>n+1)}>{loading?'Checking quote…':'Reload quote'}</button><p>Express, GST and fees are included in ₹300. The server verifies the amount again before sending.</p><details><summary>WhatsApp message and images</summary><p>💳 Your order is ready for payment. Tap Review and Pay to complete it securely.</p><PaymentTemplateMedia templates={price.available?price.templates||null:null} serviceLabel="Contribute" signedPreview /></details></aside>
    </div>
    <style jsx>{`
      .contribute-live{min-width:0;display:grid;gap:22px}.contribute-top{display:flex;justify-content:space-between;align-items:start;gap:20px}.contribute-top p{font-size:11px;letter-spacing:.12em;color:var(--text-muted);margin:0 0 6px}.contribute-top h2{font-size:26px;line-height:1.2;margin:0 0 8px}.contribute-top span{font-size:14px;color:var(--text-muted)}.contribute-amount{display:grid;text-align:right;gap:3px;flex-shrink:0}.contribute-amount strong{font-size:30px;color:var(--text-primary)}small{font-size:12px;color:var(--text-muted)}.contribute-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(240px,1fr);gap:22px;align-items:start}.quote-panel{min-width:0;background:var(--bg-secondary);padding:20px;border-radius:16px}.quote-panel h3{font-size:16px;margin:0 0 12px}.quote-panel dl{margin:0 0 16px}.quote-panel dl>div{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}.quote-panel dl>div:last-child{font-weight:750;font-size:16px}.quote-panel dd{margin:0;font-variant-numeric:tabular-nums}.quote-panel p{font-size:12px;line-height:1.65;color:var(--text-muted)}button{padding:9px 14px;min-height:44px;border:1px solid var(--border);border-radius:9px;background:var(--surface);font:inherit;color:var(--text-primary);cursor:pointer}summary{min-height:44px;align-content:center;font-size:13px;cursor:pointer}button:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:1050px){.contribute-layout{grid-template-columns:1fr}.contribute-top h2{font-size:23px}}@media(max-width:430px){.contribute-top{flex-wrap:wrap}.contribute-amount{text-align:left}}
    `}</style>
  </section>;
}
