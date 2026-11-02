import * as api from './client';
import type {CreateInvoiceEngineRequest, Invoice} from './client';
import {authFetch} from './client';

const BASE=(process.env.NEXT_PUBLIC_API_BASE||'https://wecare.digital/api')+'/invoices';
export interface CollectCommand {state:'ACCEPTED'|'REFUSED'|'UNCONFIRMED'|'SENDING';requestId?:string;waMessageId?:string;error?:string;}
export async function collectInvoices(referenceId?:string):Promise<Invoice[]> {
  const r=await authFetch(BASE+'?scope=collect'+(referenceId?'&referenceId='+encodeURIComponent(referenceId):''),{cache:'no-store'});
  if(!r.ok)throw new Error('Invoice records could not be loaded.');
  const d=await r.json();if(!Array.isArray(d.invoices))throw new Error('Invalid invoice response.');return d.invoices;
}
export async function collectInvoice(id:string):Promise<Invoice> {
  const r=await authFetch(BASE+'/'+encodeURIComponent(id),{cache:'no-store'});
  if(!r.ok)throw new Error('Invoice details could not be loaded.');const d=await r.json();if(!d.invoice?.invoiceId)throw new Error('Invalid invoice response.');return d.invoice;
}
// No automatic retries on invoice, image or message mutations.
export async function resendCollectInvoice(input:{invoiceId:string;resendRequestId:string;previousRequestId:string;expectedAssetKey:string}):Promise<CollectCommand> {
  try {const r=await authFetch(BASE,{method:'POST',body:JSON.stringify({_action:'collect-resend',...input})});
    const d=await r.json().catch(()=>({}));
    if(r.ok&&['ACCEPTED','REFUSED','UNCONFIRMED','SENDING'].includes(d.state))return d;
    return {state:r.status>=500?'UNCONFIRMED':'REFUSED',error:d.error||'Resend was not confirmed.'};
  }catch{return {state:'UNCONFIRMED',error:'Network outcome is unknown. Refresh the receipt history before another action.'};}
}
export async function repairCollectImage(id:string):Promise<void> {
  const r=await authFetch(BASE,{method:'POST',body:JSON.stringify({_action:'collect-repair-image',invoiceId:id})});
  if(!r.ok)throw new Error('Image recovery was not confirmed. Refresh this invoice before retrying.');
}
export const quoteCollect=(req:CreateInvoiceEngineRequest)=>api.previewInvoiceEngine(req,true);
export const createCollectOnce=(req:CreateInvoiceEngineRequest)=>api.createInvoiceEngineResult(req);
export async function collectDelivery(id:string):Promise<{deliveryLogs:api.InvoiceDeliveryLog[];evidenceTimeline:api.InvoiceEvidenceTimeline|null;receiptDelivery?:{status:string}}> {
  const r=await authFetch(BASE+'/'+encodeURIComponent(id)+'/delivery-log',{cache:'no-store'});
  if(!r.ok)throw Error('Delivery evidence unavailable');const d=await r.json();if(!Array.isArray(d.deliveryLogs))throw Error('Invalid delivery evidence');return d;
}
