import type {Contact, CreateInvoiceEngineRequest, Invoice, InvoiceAsset} from '../api/client';
import {addressFieldsFromContact, contactDeliveryAddress} from './address-format';
import {countryCodeForName} from '../config/countryOptions';

export interface CollectLine {name:string;amount:string;quantity:string;gstRate:string;}
export const blankCollectLine=():CollectLine=>({name:'',amount:'',quantity:'1',gstRate:'18'});
export const collectScope=(i:Invoice)=>i.entryPoint==='pay_flow'&&!i.fixedPresetId&&!i.serviceKind;
export const capturedCollect=(i:Invoice)=>['captured','paid'].includes(i.paymentStatus.toLowerCase());
export function latestInvoiceImage(i:Invoice):InvoiceAsset|undefined {
  return [...(i.assets||[])].filter(a=>a.contentType==='image/png'&&a.s3Key)
    .sort((a,b)=>(b.version||1)-(a.version||1)||(b.generatedAt||0)-(a.generatedAt||0))[0];
}
export function collectDraft(customer:Contact|null,lines:CollectLine[],gstin:string):CreateInvoiceEngineRequest|null {
  if(!customer||!customer.name?.trim()||!customer.phone||customer.archivedAt||customer.deletedAt||!lines.length)return null;
  if(lines.some(l=>!l.name.trim()||!/^\d+(\.\d{1,2})?$/.test(l.amount)||Number(l.amount)<=0||!/^\d+$/.test(l.quantity)||Number(l.quantity)<1||!/^\d+(\.\d{1,2})?$/.test(l.gstRate)||Number(l.gstRate)>100))return null;
  const a=addressFieldsFromContact(customer);
  if(![a.addressLine1,a.city,a.state,a.postalCode,a.country].every(v=>String(v||'').trim()))return null;
  if(gstin&&!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstin))return null;
  return {collectWorkspace:true,contactId:customer.id,customerName:customer.name,customerPhone:customer.phone,
    customerEmail:customer.email||'',shippingAddress:contactDeliveryAddress(customer),billingAddress:contactDeliveryAddress(customer),
    addressLine1:a.addressLine1,addressLine2:a.addressLine2,city:a.city,state:a.state,postalCode:a.postalCode,
    landmark:a.locality,countryCode:a.countryCode||countryCodeForName(a.country),goodsType:'physical-goods',
    buyerGstin:gstin||undefined,entryPoint:'pay_flow',purpose:'WECARE.DIGITAL',
    items:lines.map(l=>({name:l.name.trim(),amount:Number(l.amount),quantity:Number(l.quantity),gstRate:Number(l.gstRate)}))};
}

// Customer GST and all invoice values are server-quoted. This fingerprint only
// binds React state to the response that produced the visible image.
export const collectInputKey=(request:CreateInvoiceEngineRequest|null)=>request?JSON.stringify(request):'';
