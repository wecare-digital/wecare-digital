import React from 'react';
import * as api from '../../../api/client';
import PaymentCustomerEditor from './PaymentCustomerEditor';

export default function PaymentCustomerPicker({customer,onSelect}:{customer:api.Contact|null;onSelect:(customer:api.Contact|null)=>void}) {
  const identity=React.useId(),searchId='payment-customer-search-'+identity,titleId='payment-customer-title-'+identity;
  const [query,setQuery]=React.useState('');
  const [rows,setRows]=React.useState<api.Contact[]>([]);
  const [loading,setLoading]=React.useState(true);
  const [error,setError]=React.useState('');
  const [editing,setEditing]=React.useState<'new'|'edit'|null>(null);
  const [revision,setRevision]=React.useState(0);
  React.useEffect(()=>{let active=true;setLoading(true);setError('');
    const timer=setTimeout(()=>{void(query.trim()?api.searchContactsResult(query,40):api.listContactsResult()).then(result=>{
      if(!active)return;if(!result.ok){setError(result.failure.message||'Customer lookup failed.');setRows([]);return;}
      // A retention lock protects identity/history from edits and deletion. It
      // does not hide an existing paying customer from a read-only selector.
      setRows(result.data.filter(row=>!!row.id&&!!row.phone&&!row.deletedAt&&!row.archivedAt));
    }).catch(()=>{if(active){setError('Customers could not be loaded. Retry the search.');setRows([]);}}).finally(()=>{if(active)setLoading(false);});},query.trim()?250:0);
    return()=>{active=false;clearTimeout(timer);};
  },[query,revision]);
  return <section className="customer-picker" aria-labelledby={titleId}>
    <header><div><small>1 · CUSTOMER</small><h2 id={titleId}>Who is this payment for?</h2></div><button type="button" onClick={()=>setEditing('new')}>New customer</button></header>
    {editing?<PaymentCustomerEditor customer={editing==='edit'?customer||undefined:undefined} onCancel={()=>setEditing(null)} onSaved={saved=>{onSelect(saved);setEditing(null);setRevision(n=>n+1);}}/>:<>
      <label htmlFor={searchId}>Search saved customers</label><div className="search"><input id={searchId} value={query} onChange={event=>setQuery(event.target.value)} placeholder="Name, WhatsApp number or email"/><button type="button" onClick={()=>setRevision(n=>n+1)} disabled={loading}>Reload</button></div>
      {error&&<p role="alert">{error}</p>}
      {customer&&<div className="selected"><div><strong>{customer.name||'Customer'}</strong><span>{customer.phone}</span>{customer.locked&&<small>Identity protected for record retention · available for payment</small>}</div><div><button type="button" onClick={()=>setEditing('edit')}>Edit customer</button><button type="button" onClick={()=>onSelect(null)}>Change customer</button></div></div>}
      {!customer&&<div className="results" aria-busy={loading}>{loading?<p role="status">Searching customers…</p>:rows.map(row=><button type="button" key={row.id} onClick={()=>onSelect(row)}><strong>{row.name||'Unnamed customer'}</strong><span>{row.phone}</span>{row.locked&&<small>Protected identity</small>}</button>)}</div>}
      {!loading&&!error&&!customer&&!rows.length&&<p role="status">No saved customer matches this search. Try their full WhatsApp number or add a customer.</p>}
    </>}
    <style jsx>{`
      .customer-picker{display:grid;gap:12px;padding:20px;border:1px solid var(--border);border-radius:14px;min-width:0}header{display:flex;align-items:center;justify-content:space-between;gap:14px}h2{font-size:19px;margin:5px 0 0}small,label{font-size:12px;color:var(--text-muted)}button,input{font:inherit;color:var(--text-primary);min-height:44px;padding:10px 13px;border:1px solid var(--border);border-radius:9px;background:var(--surface)}button{font-size:13px;cursor:pointer}input{width:100%;min-width:0}.search{display:flex;gap:10px}.results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;max-height:240px;overflow-y:auto}.results button{text-align:left;display:grid;gap:5px}.results span,.selected span{display:block;font-size:12px;color:var(--text-muted)}.selected{display:flex;justify-content:space-between;gap:16px;padding:14px;border-radius:10px;background:var(--bg-secondary)}.selected>div:last-child{display:flex;flex-wrap:wrap;gap:8px}p{font-size:13px;line-height:1.6}button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:700px){.results{grid-template-columns:1fr}.selected{flex-direction:column}header{align-items:start}h2{font-size:17px}}
    `}</style>
  </section>;
}
