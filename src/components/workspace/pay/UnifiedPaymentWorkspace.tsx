import React from 'react';
import {useRouter} from 'next/router';
import type {Contact} from '../../../api/client';
import ITEMS from '../../../content/invoicePresets.json';
import PayFlow from './PayFlow';
import VaultWorkbench from './VaultWorkbench';
import ContributePaymentPlan from './ContributePaymentPlan';
import PaymentCustomerPicker from './PaymentCustomerPicker';
import ItemPaymentProcess from './ItemPaymentProcess';
import ItemServicePayment from './ItemServicePayment';

const one=(value:string|string[]|undefined)=>Array.isArray(value)?value[0]:value;
export default function UnifiedPaymentWorkspace({user,signOut}:{user?:any;signOut?:()=>void}) {
  const router=useRouter();
  const [customer,setCustomer]=React.useState<Contact|null>(null);
  const requested=one(router.query.item);
  const legacy=one(router.query.view);
  const item=ITEMS.find(row=>row.id===requested)||ITEMS.find(row=>row.workflow===legacy)||ITEMS[0];
  return <div className="unified-payment">
    <section className="item-selector" aria-labelledby="payment-item-title"><div><small>PAYMENT &amp; ITEM PROCESS</small><h2 id="payment-item-title">Create a payment</h2><p>Choose any of the 29 items. Use the same customer, invoice and payment workspace.</p></div>
      <label htmlFor="payment-invoice-item">Invoice item · all 29 items<select id="payment-invoice-item" value={item.id} onChange={event=>void router.push({pathname:'/workspace/payments',query:{view:'collect',tab:'create',item:event.target.value}},undefined,{scroll:false})}>
        {ITEMS.map(row=><option value={row.id} key={row.id}>{row.name} · ₹{(row.totalPayablePaise/100).toFixed(2)}</option>)}
      </select></label>
    </section>
    <PaymentCustomerPicker customer={customer} onSelect={setCustomer}/>
    <section className="item-payment" aria-label={`${item.name} invoice and payment`}>
      <header><small>2 · INVOICE &amp; PAYMENT</small><h2>{item.name}</h2></header>
      {!customer?<p className="choose-customer">Select a customer above to prepare this item&apos;s invoice and payment.</p>:
        item.workflow==='contribute'?<ContributePaymentPlan key={item.id} customer={customer} unified/>:
          ['submit-request','request-amendment','drop-docs','request-pickup'].includes(item.workflow)?<ItemServicePayment key={item.id} itemId={item.id} itemName={item.name} serviceSlug={item.workflow} customer={customer}/>:item.workflow==='vault'?<VaultWorkbench key={item.id} customer={customer} unified workspaceView="create"/>:
            <PayFlow key={item.id} customer={customer} fixedItemId={item.id} unified signOut={signOut} user={user} embedded mode="collect"/>}
    </section>
    <ItemPaymentProcess key={item.id} itemId={item.id} itemName={item.name}/>
    <style jsx>{`
      .unified-payment{display:grid;gap:22px;min-width:0}.item-selector{display:flex;align-items:end;justify-content:space-between;gap:28px}.item-selector h2{font-size:25px;margin:6px 0 8px}.item-selector p,.choose-customer{font-size:13px;line-height:1.6;color:var(--text-muted);margin:0}small{font-size:11px;color:var(--text-muted);letter-spacing:.06em}.item-selector>label{display:grid;gap:8px;min-width:310px;font-size:12px;font-weight:650}select{width:100%;min-width:0;min-height:48px;max-width:100%;padding:10px 34px 10px 12px;border:1px solid var(--border);border-radius:9px;background:var(--surface);color:var(--text-primary);font:inherit;font-size:14px}.item-payment{min-width:0}.item-payment>header{margin:6px 0 18px}.item-payment h2{font-size:20px;margin:5px 0}.choose-customer{padding:18px;background:var(--bg-secondary);border-radius:10px}select:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:760px){.item-selector{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.item-selector label{min-width:0}.item-selector h2{font-size:22px}}
    `}</style>
  </div>;
}
