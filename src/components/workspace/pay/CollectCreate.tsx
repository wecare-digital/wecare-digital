import React from 'react';
import * as api from '../../../api/client';
import * as collectApi from '../../../api/collect';
import {blankCollectLine,collectDraft,collectInputKey,collectDraftIssues,latestInvoiceImage,verifiedCollectRecovery,type CollectLine} from '../../../lib/collect';
import {useConfirm} from '../../../contexts/ConfirmContext';
import PaymentCustomerPicker from './PaymentCustomerPicker';

export interface CollectPreview {src?:string;label:string;state?:'loading'|'blocked'|'error';details?:string[];}
const PENDING_KEY='wecare.collect.pending-create.v1';
export default function CollectCreate({onPreview,onCreated}:{onPreview:(p:CollectPreview|null)=>void;onCreated:()=>void}) {
  const confirm=useConfirm();
  const [customer,setCustomer]=React.useState<api.Contact|null>(null),[express,setExpress]=React.useState('');
  const [lines,setLines]=React.useState<CollectLine[]>([blankCollectLine()]);
  const [quote,setQuote]=React.useState<{key:string;value:api.InvoiceEnginePreview}|null>(null);
  const [previewRevision,setPreviewRevision]=React.useState(0),[loading,setLoading]=React.useState(false),[busy,setBusy]=React.useState(false),[notice,setNotice]=React.useState('');
  const [pending,setPending]=React.useState(''),[created,setCreated]=React.useState<api.Invoice|null>(null);
  const flight=React.useRef(false),currentKey=React.useRef('');
  const request=React.useMemo(()=>collectDraft(customer,lines,express),[customer,lines,express]);
  const key=collectInputKey(request);
  const issues=React.useMemo(()=>collectDraftIssues(customer,lines,express),[customer,lines,express]);
  React.useLayoutEffect(()=>{currentKey.current=key;},[key]);
  const ready=!!key&&quote?.key===key&&!!quote.value.previewFingerprint&&!!quote.value.previewImageBase64&&!loading;
  React.useEffect(()=>{try{const saved=sessionStorage.getItem(PENDING_KEY);if(saved)setPending(saved);}catch{/* The server reference still guards this page's intent. */}},[]);
  React.useEffect(()=>{let active=true;setQuote(null);setLoading(!!key);if(!request||!key){onPreview({state:'blocked',label:'Complete these details to preview the invoice',details:issues});return()=>{active=false;};}
    onPreview({state:'loading',label:'Rendering your invoice preview…',details:['The server is checking the customer and calculating the invoice image.']});
    const timer=setTimeout(()=>{void collectApi.quoteCollect(request).then(value=>{
      if(!active||currentKey.current!==key)return;
      if(!value?.previewFingerprint||!value.previewImageBase64){const message='Server preview could not be loaded. Refresh the preview; if saved customer details changed, reload that customer.';setNotice(message);onPreview({state:'error',label:'Invoice preview unavailable',details:[message]});return;}
      setQuote({key,value});setNotice('');onPreview({src:`data:image/png;base64,${value.previewImageBase64}`,label:'Server-rendered draft · no invoice number issued'});
    }).catch(()=>{if(active){setNotice('Server preview could not be loaded. Nothing can be confirmed yet.');onPreview({state:'error',label:'Invoice preview unavailable',details:['Refresh the server preview to try again.']});}}).finally(()=>{if(active)setLoading(false);});},350);
    return()=>{active=false;clearTimeout(timer);};
  },[key,request,onPreview,previewRevision,issues]);
  const select=(c:api.Contact|null)=>{setCustomer(c);setCreated(null);};
  const update=(index:number,field:keyof CollectLine,value:string)=>setLines(rows=>rows.map((row,n)=>n===index?{...row,[field]:value}:row));
  const showSaved=async(invoice:api.Invoice)=>{
    const image=latestInvoiceImage(invoice);
    if(image?.url){onPreview({src:image.url,label:`${invoice.invoiceNumber} · saved invoice image`});return;}
    onPreview({state:'blocked',label:`${invoice.invoiceNumber} · invoice saved`,details:['The saved image is not available yet. Open Log for receipt image recovery; do not create another invoice.']});
  };
  const refreshSaved=async()=>{if(!created||flight.current)return;flight.current=true;setBusy(true);onPreview({state:'loading',label:'Loading saved invoice image…'});try{const invoice=await collectApi.collectInvoice(created.invoiceId);setCreated(invoice);await showSaved(invoice);}catch{onPreview({state:'error',label:'Saved invoice image could not be loaded',details:['The invoice remains saved. Retry viewing it or open Log.']});}finally{flight.current=false;setBusy(false);}};
  const recover=async()=>{if(!pending||flight.current)return;flight.current=true;setBusy(true);try{const rows=await collectApi.collectInvoices(pending);if(rows.length===1){const invoice=await collectApi.collectInvoice(rows[0].invoiceId);if(!verifiedCollectRecovery(invoice,{referenceId:pending,invoiceId:rows[0].invoiceId})){setNotice('The saved invoice is incomplete or does not match this recovery reference. Keep this request pending and reconcile it in Log.');return;}setCreated(invoice);await showSaved(invoice);setPending('');sessionStorage.removeItem(PENDING_KEY);setNotice('The existing invoice was found. No new invoice or payment request was sent. Open Log to review it.');onCreated();}else setNotice('Creation is not yet reconciled. Keep this request pending and check Log; do not raise a second invoice.');}catch{setNotice('Recovery read failed. The pending request is retained.');}finally{flight.current=false;setBusy(false);}};
  const create=async()=>{if(!ready||!request||!quote||pending||flight.current)return;flight.current=true;setBusy(true);const reviewedKey=key,reviewed=quote.value;
    try{const yes=await confirm({title:'Confirm custom invoice and payment template',message:`${customer?.name} · ${customer?.phone}. Amount ₹${reviewed.total}. Create this invoice and send one approved Review and Pay template?`,confirmText:'Create & send template'});if(!yes)return;
      if(currentKey.current!==reviewedKey){setNotice('The draft changed. Review the new server preview.');return;}
      const reference='WD-PAY-'+crypto.randomUUID().replaceAll('-','').slice(0,16).toUpperCase();
      // Persist only the opaque recovery reference, never customer data or credentials.
      try{sessionStorage.setItem(PENDING_KEY,reference);}catch{setNotice('This browser cannot retain the invoice recovery reference. Enable session storage before creating.');return;}
      setPending(reference);
      const result=await collectApi.createCollectOnce({...request,referenceId:reference,confirmedPreviewFingerprint:reviewed.previewFingerprint});
      if(!result.ok){if(result.status!==null&&result.status<500){sessionStorage.removeItem(PENDING_KEY);setPending('');setQuote(null);onPreview(null);}setNotice(result.message||'Creation is unconfirmed. Check the saved invoice before another action.');return;}
      const inv=await collectApi.collectInvoice(result.invoice.invoiceId);if(!verifiedCollectRecovery(inv,{referenceId:reference,invoiceId:result.invoice.invoiceId})){setNotice('The saved invoice is incomplete or does not match this request. The recovery reference is retained; no payment request was sent.');return;}setCreated(inv);await showSaved(inv);sessionStorage.removeItem(PENDING_KEY);setPending('');onCreated();
      if(Number(inv.total).toFixed(2)!==Number(reviewed.total).toFixed(2)){setNotice('Invoice saved, but its total differs from the reviewed preview. Payment was not sent. Review Log.');return;}
      const sent=await api.sendPaymentLinkResult(inv.invoiceId);
      setNotice(sent.ok&&sent.data.status==='payment_link_sent'?'Invoice saved. The approved payment request was accepted; delivery and payment remain separate.':'Invoice saved. Payment-request delivery is not confirmed. Check Log before another send.');
    }catch{setNotice('The action outcome is unconfirmed. Use the saved recovery reference or Log before another action.');}
    finally{flight.current=false;setBusy(false);}
  };
  const reviewOrCreate=()=>{if(ready){void create();return;}setNotice(issues.length?issues.join(' '):'The server preview is not ready. Refresh it and review the image before sending.');if(request&&!loading)setPreviewRevision(n=>n+1);};
  return <div className="collect-create">
    {pending&&<div className="recovery" role="status"><strong>Creation needs reconciliation</strong><p>Reference: {pending}</p><button type="button" disabled={busy} onClick={()=>void recover()}>Check saved invoice</button></div>}
    <fieldset disabled={busy||!!pending||!!created}><PaymentCustomerPicker customer={customer} onSelect={select} requireAddress/>
      <section className="card"><small className="step">2 · INVOICE VALUES</small><h2>Custom invoice items</h2>
        {lines.map((line,index)=><div className="line" key={index}><label className="description">Description<input value={line.name} onChange={e=>update(index,'name',e.target.value)}/></label><label>Quantity<input type="number" min="1" step="1" value={line.quantity} onChange={e=>update(index,'quantity',e.target.value)}/></label><label>Unit amount ₹<input type="number" min="0.01" step="0.01" value={line.amount} onChange={e=>update(index,'amount',e.target.value)}/></label><label>GST %<input type="number" min="0" max="100" step="0.01" value={line.gstRate} onChange={e=>update(index,'gstRate',e.target.value)}/></label><button type="button" disabled={lines.length===1} aria-label={`Remove item ${index+1}`} onClick={()=>setLines(rows=>rows.filter((_,n)=>n!==index))}>×</button></div>)}
        <button type="button" onClick={()=>setLines(rows=>[...rows,blankCollectLine()])}>＋ Add item</button>
        <div className="express-charge"><label htmlFor="collect-express">Express ₹<input id="collect-express" type="number" min="0" step="0.01" inputMode="decimal" required value={express} onChange={e=>setExpress(e.target.value)} placeholder="Enter amount" aria-describedby="collect-express-help"/></label><p id="collect-express-help">Enter the Express charge for this invoice. Enter 0 when there is no Express charge. The server recalculates the breakdown and preview from this value.</p></div>
      </section>
    </fieldset>
    <section className="card"><small className="step">3 · REVIEW</small><h2>Preview &amp; confirmation</h2><p>{created?'This invoice is saved. Its actual saved image is shown on the right when available.':loading?'Updating the server quote and image…':ready?'The current server invoice image is shown on the right.': 'Select a saved customer with a complete address and enter valid invoice rows and an Express amount. Confirmation requires a current server quote and image.'}</p>
      {customer&&!request&&<ul aria-label="Details needed for invoice preview">{issues.map(issue=><li key={issue}>{issue}</li>)}</ul>}
      {ready&&quote&&<dl>{[['Item base',quote.value.subtotal],['Supply GST',quote.value.tax],['Delight −',quote.value.discount],['Express +',quote.value.shipping],['Convenience +',quote.value.convenienceFeeNet],['Fee GST +',quote.value.convenienceFeeGst],['Customer pays',quote.value.total]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>₹{value}</dd></div>)}</dl>}
      <button type="button" disabled={busy||!!pending||!!created||!request} onClick={()=>setPreviewRevision(n=>n+1)}>Refresh server preview</button>
      <button className="primary" type="button" disabled={busy||loading||!!pending||!!created} onClick={reviewOrCreate}>{busy?'Checking…':loading?'Preparing invoice preview…':ready?'Confirm invoice & send template':'Review invoice details'}</button>
      {created&&<p>Saved invoice <strong>{created.invoiceNumber}</strong>. Review payment, receipt and order evidence in Log.</p>}
      {created&&<button type="button" disabled={busy} onClick={()=>void refreshSaved()}>View saved invoice image</button>}
      {created&&<button type="button" onClick={()=>{setCreated(null);setLines([blankCollectLine()]);setExpress('');select(null);setNotice('');onPreview(null);}}>New custom invoice</button>}
      {notice&&<p role="status">{notice}</p>}
    </section>
    <style jsx>{`.collect-create{display:grid;gap:18px;min-width:0}fieldset{border:0;margin:0;padding:0;min-width:0;display:grid;gap:18px}.card,.recovery{padding:20px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}.step{display:block;font-size:10px;letter-spacing:.1em;color:var(--text-muted);font-weight:700;margin-bottom:8px}.express-charge{display:grid;grid-template-columns:160px minmax(0,1fr);gap:18px;align-items:center;margin-top:20px;padding-top:18px;border-top:1px solid var(--border)}.express-charge label{font-size:14px;font-weight:650}.express-charge p{margin:0}h2{font-size:17px;margin:0 0 16px}.line{display:grid;grid-template-columns:minmax(110px,1fr) 65px 100px 70px 28px;gap:8px;align-items:end;margin:16px 0;padding-top:14px;border-top:1px solid var(--border)}label{display:grid;gap:6px;font-size:12px}input,button{min-height:42px;border:1px solid var(--border);border-radius:8px;padding:9px 11px;background:var(--surface);color:var(--text-primary);font:inherit;min-width:0;width:100%}button{width:auto;cursor:pointer;font-size:12px}button:disabled{opacity:.45;cursor:default}.primary{background:var(--text-primary);color:var(--surface);font-weight:650}p{font-size:12px;line-height:1.7;color:var(--text-muted)}dl{margin:12px 0 20px}dl>div{display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:7px 0}dd{margin:0;font-variant-numeric:tabular-nums}@media(max-width:700px){.express-charge{grid-template-columns:1fr;gap:8px}.line{grid-template-columns:1fr 1fr}.description{grid-column:1/-1}.card{padding:16px}}`}</style>
  </div>;
}
