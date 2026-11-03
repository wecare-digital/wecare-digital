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
export function collectDraft(customer:Contact|null,lines:CollectLine[],express:string):CreateInvoiceEngineRequest|null {
  if(collectDraftIssues(customer,lines,express).length||!customer)return null;
  // The buyer GSTIN is no longer entered on the form; it is read from the saved
  // customer record so a B2B invoice still carries it, and a customer with none omits it.
  const gstin=(customer as (Contact&{gstin?:string})).gstin||'';
  const a=addressFieldsFromContact(customer);
  return {collectWorkspace:true,collectSavedAddress:collectAddressSnapshot(customer),contactId:customer.id,customerName:customer.name,customerPhone:customer.phone,
    customerEmail:customer.email||'',shippingAddress:contactDeliveryAddress(customer),billingAddress:contactDeliveryAddress(customer),
    addressLine1:a.addressLine1,addressLine2:a.addressLine2,city:a.city,state:a.state,postalCode:a.postalCode,
    landmark:a.locality,countryCode:a.countryCode||countryCodeForName(a.country),goodsType:'physical-goods',
    shipping:Number(express),buyerGstin:gstin||undefined,entryPoint:'pay_flow',purpose:'WECARE.DIGITAL',
    items:lines.map(l=>({name:l.name.trim(),amount:Number(l.amount),quantity:Number(l.quantity),gstRate:Number(l.gstRate)}))};
}

/** Explain the same prerequisites used by the serializer, beside the preview. */
export function collectDraftIssues(customer:Contact|null,lines:CollectLine[],express:string):string[]{
  const gstin=(customer as (Contact&{gstin?:string})|null)?.gstin||'';
  const issues:string[]=[];
  if(!customer)issues.push('Select or save a customer.');
  else{
    if(!customer.name?.trim()||!customer.phone||customer.archivedAt||customer.deletedAt)issues.push('Select an active customer with a name and WhatsApp number.');
    const a=addressFieldsFromContact(customer);
    const missing=([['addressLine1','street'],['city','city'],['state','state'],['postalCode','postal code'],['country','country']] as const).filter(([key])=>!String(a[key]||'').trim()).map(([,label])=>label);
    if(missing.length)issues.push('Edit customer to add: '+missing.join(', ')+'.');
  }
  if(!lines.length)issues.push('Add an invoice item.');
  lines.forEach((line,index)=>{
    if(!line.name.trim())issues.push(`Item ${index+1}: enter a description.`);
    if(!/^\d+(\.\d{1,2})?$/.test(line.amount)||Number(line.amount)<=0)issues.push(`Item ${index+1}: enter a unit amount greater than 0.`);
    if(!/^\d+$/.test(line.quantity)||Number(line.quantity)<1)issues.push(`Item ${index+1}: quantity must be a whole number of at least 1.`);
    if(!/^\d+(\.\d{1,2})?$/.test(line.gstRate)||Number(line.gstRate)>100)issues.push(`Item ${index+1}: GST must be from 0 to 100%.`);
  });
  if(!/^\d+(\.\d{1,2})?$/.test(express)||!Number.isFinite(Number(express))||Number(express)<0)issues.push('Enter Express, including 0 if no charge applies.');
  if(gstin&&!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstin))issues.push('Enter a valid 15-character GSTIN, or leave it empty.');
  return issues;
}

// Customer GST and all invoice values are server-quoted. This fingerprint only
// binds React state to the response that produced the visible image.
export const collectInputKey=(request:CreateInvoiceEngineRequest|null)=>request?JSON.stringify(request):'';

export function collectAddressSnapshot(contact:Contact):Record<string,unknown>{
  const source=contact as unknown as Record<string,unknown>;
  const clean=(value:unknown):unknown=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).map(([k,v])=>[k,clean(v)]).filter(([,v])=>v!==''&&v!==null&&JSON.stringify(v)!=='{}')):String(value||'').trim();
  if(source.checkoutDeliveryAddress&&typeof source.checkoutDeliveryAddress==='object'&&Object.keys(source.checkoutDeliveryAddress).length)return {checkoutDeliveryAddress:clean(source.checkoutDeliveryAddress)};
  return clean(Object.fromEntries(['shippingAddressJson','addressLine1','addressLine2','landmark','city','state','postalCode','country','countryCode','houseNumber','buildingName','towerNumber','floorNumber'].map(k=>[k,source[k]]))) as Record<string,unknown>;
}
