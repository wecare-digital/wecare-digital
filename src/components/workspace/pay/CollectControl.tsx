import React from 'react';
import PaymentFramework from './PaymentFramework';
import * as api from '../../../api/client';
export default function CollectControl(){
  const [sender,setSender]=React.useState('Checking live sender…');
  React.useEffect(()=>{let active=true;void api.getThroughput('1016149501586345').then(value=>{if(active)setSender(value.status?`${value.verifiedName} · ${value.displayPhoneNumber} · ${value.status} · ${value.qualityRating}`:'Live sender status unavailable.');}).catch(()=>{if(active)setSender('Live sender status unavailable.');});return()=>{active=false;};},[]);
  return <section><h2>Sender &amp; backend controls</h2><p>Payment and receipt sender: WECARE.DIGITAL · +91 93309 94400 · phone ID 1016149501586345.</p><pre>{sender}</pre><p>Configured Collect message waits: 0 seconds. Payment completion and provider processing take variable time; the invoice’s Log shows measured gaps separately.</p><p>Manual resend uses wecare_default_invoice_image_template (1782246473079550), the original saved recipient and the exact paid PNG. Unresolved sends retain their request identity and prevent a new send. All outbound transaction messages use approved templates.</p>
    <div className="table"><table><thead><tr><th>Action</th><th>API / function</th><th>Storage</th></tr></thead><tbody>{[
      ['Server preview / confirm','POST /invoices · _action=preview or create · invoice-engine','ContactsTable; preview writes no invoice'],
      ['Collect Log','GET /invoices?scope=collect · list_invoices','InvoicesTable; pay_flow custom invoices only'],
      ['Saved image / signed link','GET /invoices/{id} · get_invoice','InvoiceAssetsTable; private S3 object'],
      ['Paid receipt resend','POST /invoices · collect-resend · collect_receipts.resend','CommerceKeys request identity + InvoicesTable lock + InvoiceDeliveryLogTable'],
      ['Receipt image recovery','POST /invoices · collect-repair-image · ensure_invoice_image','InvoiceAssetsTable; reuse saved paid version'],
      ['Order evidence','GET /wa-business/orders/{internalOrderId} · service-api','OrderTable; invoiceId must match'],
      ['Measured message chronology','GET /invoices/{id}/delivery-log · get_delivery_log','InvoiceDeliveryLogTable; exact invoice partition'],
    ].map(row=><tr key={row[0]}>{row.map(cell=><td key={cell}>{cell}</td>)}</tr>)}</tbody></table></div><p>Physical table names use the deployment prefix stack-wecare-digital-. The invoice API provides the saved internal order ID and public order number; the UI verifies the order’s invoice link before offering Open order.</p><PaymentFramework section="collect"/>
    <style jsx>{`h2{font-size:18px}p,pre{font-size:12px;line-height:1.7;color:var(--text-muted)}pre{white-space:pre-wrap;overflow-wrap:anywhere}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:11px}th,td{padding:10px;border:1px solid var(--border);text-align:left;vertical-align:top}`}</style>
  </section>;
}
