import React from 'react';
import * as api from '../../../api/client';
import {fetchServicePrices,type ServicePrice} from '../../../lib/servicePricing';
import {useConfirm} from '../../../contexts/ConfirmContext';
import {isOrderNumber} from '../../../lib/paymentVocabulary';
import {formatPaiseINR} from '../../../lib/money';

export default function ItemServicePayment({itemId,itemName,serviceSlug,customer}:{itemId:string;itemName:string;serviceSlug:string;customer:api.Contact}) {
  const [price,setPrice]=React.useState<ServicePrice>({available:false});
  const [loading,setLoading]=React.useState(true),[revision,setRevision]=React.useState(0);
  const [orderNumber,setOrderNumber]=React.useState(''),[review,setReview]=React.useState(false),[sending,setSending]=React.useState(false),[locked,setLocked]=React.useState(false),[outcome,setOutcome]=React.useState('');
  const busy=React.useRef(false);const confirm=useConfirm();
  React.useEffect(()=>{let active=true;setLoading(true);setReview(false);void fetchServicePrices().then(prices=>{if(active)setPrice(prices[serviceSlug]||{available:false});}).catch(()=>{if(active)setPrice({available:false});}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[serviceSlug,revision]);
  React.useEffect(()=>{setReview(false);setOrderNumber('');},[customer.id]);
  const b=price.available?price.breakdown:undefined;
  const money=(value:number)=>formatPaiseINR(value,'INR');
  const ready=!loading&&!!b&&b.totalPayablePaise>0&&isOrderNumber(orderNumber.trim().toUpperCase());
  const send=async()=>{if(!ready||!review||busy.current||locked||!b)return;busy.current=true;let attempted=false;
    try{const yes=await confirm({title:`Send ${itemName} payment request?`,message:`${customer.name} · ${customer.phone}. ${orderNumber}. Total ${money(b.totalPayablePaise)}. Send one approved native Review and Pay request?`,confirmText:'Send payment request'});if(!yes)return;setSending(true);attempted=true;const result=await api.sendStaffItemServicePaymentOnce({contactId:customer.id,itemId,selectedOrderNumber:orderNumber.trim().toUpperCase(),expectedTotalPaise:b.totalPayablePaise});setLocked(result.state!=='REFUSED');setOutcome(result.state==='ACCEPTED'?'Payment request accepted. Check records for delivery and captured payment.':result.message);}catch{setLocked(attempted);setOutcome(attempted?'The send result is unknown. Check WhatsApp and records before retrying.':'The confirmation could not be opened. Nothing was sent.');}finally{busy.current=false;setSending(false);}
  };
  return <div className="service-payment"><div className="service-inputs"><label>Customer&apos;s paid order number<input value={orderNumber} onChange={event=>{setOrderNumber(event.target.value.toUpperCase());setReview(false);}} placeholder="WD-ORD-7ZTSG8X7" disabled={sending||locked}/></label><p>The backend checks that this paid order belongs to the selected customer before reserving or sending a service payment. The approved service Flow follows verified payment and the paid receipt.</p>
    {outcome&&<p role="status">{outcome}</p>}
    {!review?<button type="button" disabled={!ready||sending||locked} onClick={()=>setReview(true)}>Review payment request</button>:<div className="review"><strong>{customer.name} · {itemName}</strong><p>{orderNumber} · {b?money(b.totalPayablePaise):''}</p><button type="button" onClick={()=>void send()} disabled={!ready||sending||locked}>{sending?'Sending…':locked?'Check send outcome':'Send native Review & Pay'}</button><button type="button" disabled={sending||locked} onClick={()=>setReview(false)}>Edit review</button></div>}
  </div><aside><h3>Payment breakdown</h3>{loading?<p role="status">Checking live quote…</p>:b?<dl>{[['Base',b.itemSubtotalPaise],['Supply GST',b.supplyGstPaise],['Delight',-b.delightPaise],['Express',b.expressPaise],['Convenience',b.convenienceFeePaise],['Fee GST',b.convenienceGstPaise],['Customer pays',b.totalPayablePaise]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{Number(value)<0?'−':''}{money(Math.abs(Number(value)))}</dd></div>)}</dl>:<p role="alert">The service quote is unavailable. Reload before payment.</p>}<button type="button" disabled={loading||sending||locked} onClick={()=>setRevision(n=>n+1)}>Reload quote</button></aside>
    <style jsx>{`.service-payment{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(240px,1fr);gap:24px}.service-inputs{display:grid;gap:14px;align-content:start}label{display:grid;gap:7px;font-size:13px}input,button{font:inherit;min-height:44px;padding:10px 12px;border:1px solid var(--border);border-radius:9px;background:var(--surface);color:var(--text-primary);min-width:0}button{cursor:pointer;justify-self:start}button:disabled{opacity:.5;cursor:not-allowed}p{font-size:13px;line-height:1.65;color:var(--text-muted)}aside{padding:20px;border-radius:14px;background:var(--bg-secondary);min-width:0}h3{font-size:16px;margin:0 0 12px}dl{margin:0 0 14px}dl>div{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--border);padding:9px 0;font-size:13px}dd{margin:0;white-space:nowrap}.review{border:1px solid var(--border);padding:16px;border-radius:12px}.review button{margin-right:8px}@media(max-width:760px){.service-payment{grid-template-columns:minmax(0,1fr)}}`}</style>
  </div>;
}
