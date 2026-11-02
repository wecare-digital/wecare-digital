import React, { useState } from 'react';
import Link from 'next/link';
import ITEMS from '../../../content/invoicePresets.json';
import { formatPaiseINR } from '../../../lib/money';

/** Approved fixed prices; the owning workspace validates the final quote before sending. */
export default function FixedInvoiceItems (): React.ReactElement {
  const [ search, setSearch ] = useState( '' );
  const shown = ITEMS.filter( item => item.name.toLowerCase().includes( search.trim().toLowerCase() ) );
  const money = ( paise: number ) => formatPaiseINR( paise, 'INR' );
  const hrefFor = (item: typeof ITEMS[number]) => `/workspace/payments?view=collect&tab=create&item=${item.id}`;
  return (
    <section className="fixed-items" aria-labelledby="fixed-items-title">
      <header><div><h2 id="fixed-items-title">Invoice items <span>29</span></h2><p>Choose an item to start its payment workflow. The server verifies the final price before payment.</p></div>
        <label>Find an item<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search all 29 items" /></label>
      </header>
      <div className="fixed-table" tabIndex={0} role="region" aria-label="All fixed invoice prices, scroll horizontally for more columns">
        <table><caption>{shown.length} of 29 approved invoice items · amounts in INR</caption>
          <thead><tr><th scope="col">Item</th><th scope="col">Base</th><th scope="col">GST 18%</th><th scope="col">Delight −</th><th scope="col">Express +</th><th scope="col">Conv. +</th><th scope="col">Fee GST +</th><th scope="col">Final</th><th scope="col">Action</th></tr></thead>
          <tbody>{shown.map(item => <tr key={item.id}><th scope="row">{item.name}</th>
            {[item.basePaise,item.supplyGstPaise,item.delightPaise,item.expressPaise,item.convenienceFeePaise,item.convenienceGstPaise].map((amount,index)=><td key={index} data-wc-no-translate="true">{money(amount)}</td>)}
            <td data-wc-no-translate="true"><strong>{money(item.totalPayablePaise)}</strong></td><td><Link href={hrefFor(item)} aria-label={`Use ${item.name}`}>Use item</Link></td>
          </tr>)}</tbody>
        </table>
      </div>
      {shown.length === 0 && <p role="status">No items match. Try another name.</p>}
      <style jsx>{`
        .fixed-items{min-width:0}.fixed-items header{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:20px}.fixed-items h2{font-size:24px;margin:0 0 8px}.fixed-items h2 span{font-size:14px;padding:4px 8px;background:var(--lime);border-radius:8px}.fixed-items p{font-size:13px;line-height:1.6;color:var(--text-muted);max-width:650px}.fixed-items label{display:grid;gap:6px;font-size:12px}.fixed-items input{min-height:44px;border:1px solid var(--border);border-radius:8px;padding:10px;font:inherit;background:var(--surface);color:var(--text-primary)}.fixed-table{max-width:100%;overflow-x:auto;border:1px solid var(--border);border-radius:12px}.fixed-table:focus-visible{outline:3px solid var(--accent)}table{width:100%;border-collapse:collapse;font-size:12px}caption{text-align:left;padding:12px;color:var(--text-muted)}th,td{padding:12px;text-align:right;border-top:1px solid var(--border);white-space:nowrap}th:first-child{text-align:left;min-width:170px;white-space:normal}thead{background:var(--bg-secondary)}td :global(a){display:inline-flex;align-items:center;min-height:40px;padding:6px 10px;border:1px solid var(--border);border-radius:8px;color:var(--text-primary);text-decoration:none}td :global(a:hover){background:var(--lime)}@media(max-width:700px){.fixed-items header{display:grid;gap:12px}.fixed-items label{max-width:100%}}
      `}</style>
    </section>
  );
}
