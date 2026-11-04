import React from 'react';
import * as api from '../../../api/client';
import {ADDRESS_FIELDS, EMPTY_ADDRESS_FIELDS, addressComplete, addressPayload, addressFieldsFromContact, formatAddress} from '../../../lib/address-format';
import {SETUP_INCOMPLETE_MESSAGE, completeCustomerSetup, ensureCustomerSetup, partialCreateContactId, type CustomerSetupOutcome} from '../../../lib/customer-setup';

export default function PaymentCustomerEditor({customer,onSaved,onCancel,requireAddress=false}:{customer?:api.Contact;onSaved:(c:api.Contact)=>void;onCancel:()=>void;requireAddress?:boolean}) {
  const [name,setName]=React.useState(customer?.name||'');
  const [phone,setPhone]=React.useState(customer?.phone||'');
  const [address,setAddress]=React.useState(customer?addressFieldsFromContact(customer):{...EMPTY_ADDRESS_FIELDS});
  const [saving,setSaving]=React.useState(false);const [error,setError]=React.useState('');const busy=React.useRef(false);
  // Set when the contact is saved but its customer account link is not: the next submit
  // completes setup for THIS record instead of creating another customer.
  const [pendingSetupId,setPendingSetupId]=React.useState('');
  const finish=(outcome:CustomerSetupOutcome)=>{if(outcome.ok){setPendingSetupId('');onSaved(outcome.contact);return;}setPendingSetupId(outcome.pendingContactId);setError(outcome.message);};
  const save=async(event:React.FormEvent)=>{event.preventDefault();if(busy.current)return;
    if(pendingSetupId){busy.current=true;setSaving(true);setError('');
      try{finish(await completeCustomerSetup(pendingSetupId,api.provisionContactIdentityResult));}finally{busy.current=false;setSaving(false);}
      return;}
    if(!name.trim()||!/^\+[1-9]\d{7,14}$/.test(phone.replace(/[\s()-]/g,''))){setError('Enter a full name and WhatsApp number including + and country code.');return;}
    const touched=ADDRESS_FIELDS.some(f=>f.key!=='country'&&String(address[f.key]||'').trim());
    if((requireAddress||touched)&&!addressComplete(address)){setError(requireAddress?'Complete the street, city, state, postal code and country for this invoice.':'Complete the street, city, state, postal code and country, or leave the address empty.');return;}
    busy.current=true;setSaving(true);setError('');
    try{const full=formatAddress(address);const payload:api.ContactMutation={name:name.trim(),phone:phone.replace(/[\s()-]/g,''),...(touched?{address:{...addressPayload(address),addressLine1:address.addressLine1,city:address.city,state:address.state,postalCode:address.postalCode},shippingAddress:full,billingAddress:full}:{})};
      const result=customer?.id?await api.updateContactResult(customer.id,payload):await api.createContactResult(payload);
      if(!result.ok){const partial=partialCreateContactId(result.failure);
        if(partial){setPendingSetupId(partial);setError(SETUP_INCOMPLETE_MESSAGE);return;}
        setError(result.failure.message||'Customer could not be saved.');return;}
      if(!result.data?.id){setError('The save returned no customer record. Search before trying again.');return;}
      finish(await ensureCustomerSetup(result.data,api.provisionContactIdentityResult));
    }catch{setError('Customer save could not be confirmed. Search for the number before trying again.');}finally{busy.current=false;setSaving(false);}
  };
  return <form className="payment-customer-editor" onSubmit={event=>{void save(event);}} aria-label={customer?'Edit payment customer':'New payment customer'}>
    <h4>{customer?'Edit customer':'New customer'}</h4><div className="customer-fields"><label>Full name<input required value={name} onChange={e=>setName(e.target.value)} autoComplete="name" /></label><label>WhatsApp number<input required type="tel" value={phone} onChange={e=>setPhone(e.target.value)} placeholder="+91…" autoComplete="tel" /></label></div>
    <details open={requireAddress||!!customer}><summary>Delivery address</summary><div className="customer-fields">{ADDRESS_FIELDS.map(f=><label key={f.key}>{f.label}<input value={address[f.key]||''} maxLength={f.maxLength} onChange={e=>setAddress(v=>({...v,[f.key]:e.target.value,...(f.key==='country'?{countryCode:''}:{})}))} placeholder={f.placeholder} /></label>)}</div></details>
    {error&&<p role="alert">{error}</p>}<div className="customer-actions"><button type="submit" disabled={saving}>{saving?'Saving…':pendingSetupId?'Complete customer setup':'Save & select customer'}</button><button type="button" disabled={saving} onClick={onCancel}>Cancel</button></div><small>Saving a contact does not mark their phone verified or send a message.</small>
    <style jsx>{`.payment-customer-editor{padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--bg-secondary);display:grid;gap:12px}h4{margin:0;font-size:16px}.customer-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}label{display:grid;gap:5px;font-size:12px}input{width:100%;min-height:44px;box-sizing:border-box;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-primary);padding:9px 11px;font:inherit}.customer-actions{display:flex;gap:9px;flex-wrap:wrap}button{min-height:44px;padding:9px 13px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-primary);font:inherit;cursor:pointer}button[type=submit]{background:var(--accent);color:var(--button-primary-text,#fff)}small{font-size:11px;color:var(--text-muted)}summary{min-height:44px;align-content:center;cursor:pointer;font-size:13px}p{font-size:12px;color:var(--error,#a32626)}@media(max-width:600px){.customer-fields{grid-template-columns:1fr}}`}</style>
  </form>;
}
