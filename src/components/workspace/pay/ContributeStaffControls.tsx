import React from 'react';
import * as api from '../../../api/client';
import {useConfirm} from '../../../contexts/ConfirmContext';
import PaymentCustomerEditor from './PaymentCustomerEditor';
import type {ServicePrice,ServicePaymentTemplates} from '../../../lib/servicePricing';
interface Props{customer?:api.Contact|null;unified?:boolean;price:ServicePrice;templates:ServicePaymentTemplates|null;loadingPrice:boolean;refreshPrice:()=>void;}
const usable=(c:api.Contact)=>!!c.id&&!!c.phone&&!c.deletedAt&&!c.archivedAt;
export default function ContributeStaffControls({price,templates,loadingPrice,refreshPrice,customer,unified=false}:Props){
 const [contacts,setContacts]=React.useState<api.Contact[]>([]),[query,setQuery]=React.useState(''),[selected,setSelected]=React.useState<api.Contact|null>(null);
 const [loading,setLoading]=React.useState(true),[error,setError]=React.useState(''),[editing,setEditing]=React.useState<'new'|'edit'|null>(null),[refresh,setRefresh]=React.useState(0);
 const [readiness,setReadiness]=React.useState<'checking'|'ready'|'blocked'>('checking'),[reason,setReason]=React.useState(''),[approved,setApproved]=React.useState(false),[templateReason,setTemplateReason]=React.useState('');
 const [review,setReview]=React.useState(false),[sending,setSending]=React.useState(false),[locked,setLocked]=React.useState(false),[outcome,setOutcome]=React.useState('');
 const busy=React.useRef(false);const confirm=useConfirm();
 React.useEffect(()=>{if(unified){setSelected(customer||null);setReview(false);}},[customer,unified]);

 React.useEffect(()=>{if(unified)return;let active=true;setLoading(true);setError('');setContacts([]);
  const timer=setTimeout(()=>{void (query.trim()?api.searchContactsResult(query,40):api.listContactsResult()).then(result=>{if(!active)return;if(!result.ok){setError(result.failure.message||'Customer lookup failed.');return;}setContacts(result.data.filter(usable));}).catch(()=>{if(active)setError('Customers could not be loaded. Reload to retry.');}).finally(()=>{if(active)setLoading(false);});},query.trim()?250:0);
  return()=>{active=false;clearTimeout(timer);};
 },[query,refresh,unified]);
 React.useEffect(()=>{let active=true;setReadiness('checking');setApproved(false);
  void Promise.all([api.getStaffContributionSendReadiness(),templates?.templateIds?.nativePay?api.getTemplateDetailsResult(templates.templateIds.nativePay):Promise.resolve(null)]).then(([ready,result])=>{if(!active)return;const t=result?.ok?result.data:null;setTemplateReason(result&&!result.ok?result.failure.message:!templates?.templateIds?.nativePay?'Payment template reference is missing.':'');setReadiness(ready.sendEnabled&&ready.amountPaise===30000?'ready':'blocked');setReason(ready.reason);const parts=Array.isArray(t?.components)?t.components:[];setApproved(t?.status==='APPROVED'&&t?.name===templates?.nativePay&&(!t?.id||String(t.id)===templates?.templateIds?.nativePay)&&parts.some((p:any)=>p.type==='HEADER'&&p.format==='IMAGE')&&parts.some((p:any)=>p.type==='BUTTONS'&&p.buttons?.some((b:any)=>b.type==='ORDER_DETAILS')));}).catch(()=>{if(active){setReadiness('blocked');setReason('Payment checks unavailable.');}});
  return()=>{active=false;};
 },[templates?.templateIds?.nativePay,templates?.nativePay,refresh]);
 const b=price.available?price.breakdown:undefined;
 const exact=price.available&&price.paise===30000&&b?.totalPayablePaise===30000&&b.itemSubtotalPaise===23541&&b.supplyGstPaise===4237&&b.delightPaise===138&&b.expressPaise===1500&&b.convenienceFeePaise===729&&b.convenienceGstPaise===131&&b.collectionBeforeConveniencePaise===29140;
 const canReview=!!selected&&exact&&!loadingPrice&&!editing&&!locked&&!sending;
 const send=async()=>{if(busy.current||!review||!canReview||readiness!=='ready'||!approved||!selected)return;busy.current=true;let attempted=false;
  try{const yes=await confirm({title:'Send ₹300 payment request?',message:`${selected.name} · ${selected.phone}. Total ₹300 including GST, Express and fees. Send one approved WhatsApp Review and Pay request?`,confirmText:'Send ₹300 request'});if(!yes)return;setSending(true);setOutcome('');
   attempted=true;const result=await api.sendStaffContributionPaymentOnce(selected.id);setLocked(result.state!=='REFUSED');
   if(result.state==='ACCEPTED')setOutcome('Payment request accepted. Check the customer chat and records for delivery and capture.');
   else if(result.state==='UNCONFIRMED')setOutcome('Send outcome unknown. Check the chat and records before any retry.');
   else setOutcome(result.message||`Request refused: ${result.code}. No confirmed payment request.`);
  }catch{if(attempted){setLocked(true);setOutcome('Send outcome could not be confirmed. Check the chat and records before retrying.');}else{setOutcome('The confirmation could not be opened. Nothing was sent; you can try opening it again.');}}finally{busy.current=false;setSending(false);}
 };
 const select=(c:api.Contact)=>{setSelected(c);setReview(false);setError('');};
 const reload=()=>{setReview(false);refreshPrice();setRefresh(n=>n+1);};
 return <section className="contribution-controls" aria-label="Contribution customer and payment controls">
  {!unified&&<><header><h3>1. Customer</h3><button type="button" onClick={()=>{setEditing('new');setReview(false);}} disabled={sending||locked}>New customer</button></header>
  {editing?<PaymentCustomerEditor customer={editing==='edit'?selected||undefined:undefined} onCancel={()=>setEditing(null)} onSaved={c=>{select(c);setContacts(rows=>[c,...rows.filter(r=>r.id!==c.id)]);setEditing(null);}}/>:<>
   <label htmlFor="contribution-search">Find by name, WhatsApp number or email</label><div className="search-row"><input id="contribution-search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search all saved customers" autoComplete="off"/><button type="button" disabled={loading} onClick={()=>setRefresh(n=>n+1)}>{loading?'Loading…':'Reload customers'}</button></div>
   {error&&<p role="alert">{error}</p>}
   {selected?<div className="selected-customer"><div><strong>{selected.name||'Customer'}</strong><span>{selected.phone}</span></div><div><button type="button" onClick={()=>{setEditing('edit');setReview(false);}} disabled={sending||locked}>Edit details</button><button type="button" onClick={()=>{setSelected(null);setReview(false);}} disabled={sending||locked}>Change</button></div></div>:null}
   <div className="customer-results" aria-busy={loading}>{loading?<p role="status">Loading customers…</p>:contacts.length?contacts.slice(0,40).map(c=><button key={c.id} type="button" aria-pressed={selected?.id===c.id} onClick={()=>select(c)} disabled={sending||locked}><strong>{c.name||'Unnamed customer'}</strong><span>{c.phone}</span></button>):!error?<p>No matching saved customers. Add a new customer above.</p>:null}</div>
  </>}
  </>}
  <div className="payment-checks"><h3>2. Review &amp; send</h3><p role="status">{loadingPrice||readiness==='checking'?'Checking payment availability…':!exact?'The live quote is unavailable or changed. Reload before sending.':readiness!=='ready'?`Payment unavailable: ${reason}`:!approved?(templateReason||'Payment template approval or native payment button does not match. Reload to recheck.'):'Payment service ready · ₹300 final'}</p><button type="button" onClick={reload} disabled={sending||loadingPrice}>Recheck payment availability</button></div>
  {review&&selected&&<div className="review" aria-live="polite"><strong>{selected.name} · {selected.phone}</strong><p>Customer pays ₹300.00 including all fees and taxes.</p><p>💳 Your order is ready for payment. Tap Review and Pay to complete it securely.</p><small>Button: Review and Pay · WECARE.DIGITAL</small><button type="button" disabled={sending||locked} onClick={()=>setReview(false)}>Edit selection</button></div>}
  <div className="send-actions">{!review?<button className="primary" type="button" disabled={!canReview} onClick={()=>setReview(true)}>Review ₹300 request</button>:<button className="primary" type="button" disabled={!canReview||readiness!=='ready'||!approved} onClick={()=>{void send();}}>{sending?'Sending…':locked?'Check send outcome':'Send ₹300 Review & Pay'}</button>}</div>
  {outcome&&<p role="status" className="outcome">{outcome}</p>}
  <small>Sending requires Admin access and a verified customer. Saving a new contact alone does not verify their WhatsApp identity.</small>
  <style jsx>{`
   .contribution-controls{display:grid;gap:14px;min-width:0}header{display:flex;align-items:center;justify-content:space-between;gap:10px}h3{font-size:16px;margin:0}label{font-size:12px;color:var(--text-muted)}button,input{font:inherit;color:var(--text-primary);min-height:44px;border:1px solid var(--border);border-radius:9px;background:var(--surface);padding:9px 12px}button{cursor:pointer;font-size:12px}button:disabled{opacity:.55;cursor:not-allowed}input{width:100%;min-width:0;font-size:14px}.search-row{display:flex;gap:8px}.search-row button{flex-shrink:0}.customer-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:260px;overflow-y:auto}.customer-results button{display:grid;gap:3px;text-align:left;min-width:0}.customer-results button[aria-pressed=true]{border-color:var(--accent);background:var(--bg-secondary)}.customer-results span,.selected-customer span{display:block;font-size:12px;color:var(--text-muted);overflow-wrap:anywhere}.selected-customer{display:flex;justify-content:space-between;gap:12px;padding:14px;background:var(--bg-secondary);border-radius:12px}.selected-customer>div:last-child{display:flex;gap:6px;flex-wrap:wrap}.payment-checks{border-top:1px solid var(--border);padding-top:20px}.payment-checks p,p{font-size:13px;line-height:1.6}.review{padding:16px;border:1px solid var(--border);border-radius:12px}.review button{display:block;margin-top:10px}small{font-size:11px;color:var(--text-muted);line-height:1.6}.primary{background:var(--accent);color:var(--button-primary-text,#fff);font-weight:750;min-height:48px;padding:12px 20px}.outcome{padding:12px;background:var(--bg-secondary);border-radius:9px}button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:600px){.customer-results{grid-template-columns:1fr}.search-row,.selected-customer{flex-direction:column}}
  `}</style>
 </section>;
}
