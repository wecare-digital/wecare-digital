/** Read-only source contracts. Registry IDs are lookup references, never send authority. */
export type FrameworkSection = 'collect' | 'vault' | 'contribute';
export type TemplateRole = 'payment' | 'status' | 'invoice' | 'access';
export const FRAMEWORK_TEMPLATES: Record<TemplateRole, {name: string; id: string; shape: string; variables: string}> = {
  payment: {name: 'wecare_whatapp_native_pay_template', id: '2714938845570815',
    shape: 'Template · IMAGE header · ORDER_DETAILS button',
    variables: 'Body: 0. Server supplies item lines, INR/paise totals, tax, discount, Express, payment reference and approved media.'},
  status: {name: 'wecare_order_status_v3', id: '1754227779211208',
    shape: 'Template · ORDER_STATUS component',
    variables: 'Server supplies reference_id, order_status (processing/completed) and description. Reuses the same template twice.'},
  invoice: {name: 'wecare_default_invoice_image_template', id: '1782246473079550',
    shape: 'Template · paid-invoice IMAGE header · FLOW button 0',
    variables: 'Body: 0. Server supplies paid invoice PNG and opaque, order-bound review Flow token.'},
  access: {name: 'wecare_default_download', id: '1410998911012572',
    shape: 'Template · IMAGE header · URL button 0',
    variables: 'Body: 0. URL suffix {{1}} = owner-bound file ID. Fixed /vault/?file={{1}} URL; no S3 URL or auth token.'},
};
export interface FrameworkStage {name: string; direction: string; type: string; role?: TemplateRole; gate: string; timing: string; response: string;}
export interface FrameworkInput {field: string; source: string; control: string;}
export const FRAMEWORK_INPUTS: Record<FrameworkSection, FrameworkInput[]> = {
  collect: [
    {field: 'Customer, verified phone and delivery address', source: 'Saved Contacts / customer profile', control: 'Staff selects and reviews; backend validates payable identity and address.'},
    {field: 'Invoice item names, quantities, unit prices and tax choices', source: 'Collect invoice composer or saved invoice', control: 'Staff input; canonical server calculates the final invoice and fees.'},
    {field: 'Express amount', source: 'Collect Create → Express ₹', control: 'Staff enters an amount or 0 explicitly. Changing it requires a fresh server quote and invoice image.'},
    {field: 'Discount / Delight, convenience and GST totals', source: 'Invoice engine quote and saved invoice', control: 'Review server values. A displayed amount is not payment capture.'},
    {field: 'Invoice ID, payment reference and approved media', source: 'Existing invoice/create/payment contracts', control: 'Not a template-variable editor. See the reference/idempotency discrepancy under Gaps.'},
  ],
  vault: [
    {field: 'Customer name and WhatsApp mobile', source: 'Vault Create upload form', control: 'Staff input; backend binds and verifies the exact owner.'},
    {field: 'Private PDF, JPEG or PNG', source: 'Vault Create file chooser', control: 'Upload-init → private PUT → confirm. Upload alone sends no payment or access message.'},
    {field: 'Opaque file ID, invoice/reference and paid entitlement', source: 'Secure-files and payment backend', control: 'Read-only in message construction. UNPAID payment request; READY/OPEN access resend only.'},
    {field: 'Invoice accepted → Access Vault gap', source: 'vault_delivery_timing_v1', control: 'Only editable journey delay: integer 0–5 seconds, server fallback 4. Use Access delay settings.'},
  ],
  contribute: [
    {field: 'Saved customer', source: 'Contacts selector', control: 'Staff selects; backend re-verifies identity and phone.'},
    {field: 'Reference (3–60 characters), note (up to 240)', source: 'Create review draft', control: 'Local staff review only. Neither value is submitted to the payment sender or WhatsApp body.'},
    {field: '₹300.00 exact total, including ₹15 Express', source: 'Catalog product and canonical taxable quote', control: 'Not editable. Every fee/tax line must match the frozen server contract.'},
    {field: 'Admin/MFA, template approval and backend readiness', source: 'Staff authorization and provider/backend reads', control: 'All required again at send time; a successful preview cannot authorize payment.'},
  ],
};
export function frameworkStages(section: FrameworkSection): FrameworkStage[] {
  const stages: FrameworkStage[] = [{name: 'Prepare and review', direction: 'Staff → backend', type: 'Workspace form / read APIs',
    gate: section === 'vault' ? 'Private upload is confirmed; exact file and owner reviewed.' : section === 'contribute' ? 'Saved recipient, exact ₹300 quote, Admin/MFA and payment readiness.' : 'New or saved invoice, customer, address and server totals reviewed.',
    timing: 'Staff-controlled. No automatic customer send from Display.', response: 'Saved/verified record or explicit validation failure.'},
  {name: 'Review & Pay', direction: 'Outgoing → customer', type: 'template', role: 'payment',
    gate: 'Explicit staff confirmation and backend payment/template validation.', timing: 'No configured wait; API/provider latency varies.',
    response: 'Customer opens native checkout. Payment is established by verified provider capture, not a button tap.'},
  {name: 'Payment result', direction: 'Incoming → backend', type: 'Verified payment-provider webhook',
    gate: 'Reference, amount, currency and capture must reconcile.', timing: 'Customer/provider dependent; no fixed payment completion time.', response: 'Captured, pending, failed or unknown money state; transport status remains separate.'},
  {name: 'Processing', direction: 'Outgoing → customer', type: 'template', role: 'status',
    gate: 'Verified capture and eligible native ORDER_DETAILS invoice/reference.', timing: 'No deliberate wait after capture; processing/network latency remains.', response: 'Provider acceptance and message-status evidence.'},
  {name: 'Completed', direction: 'Outgoing → customer', type: 'template', role: 'status',
    gate: 'Processing accepted or already recorded; legal payment-order transition.', timing: 'Fixed half a second (0.5s) after a newly accepted Processing, on every journey. Replay/already-current path may skip the sleep.', response: 'Payment lifecycle complete; service/shipment fulfilment is separate.'},
  {name: 'Paid GST invoice', direction: 'Outgoing → customer', type: 'template', role: 'invoice',
    gate: 'Paid numbered invoice, rendered asset and verified recipient. Status attempts run before receipt; deferred status does not necessarily block receipt.',
    timing: '0 seconds deliberately added after status attempts; invoice creation/render/send adds variable time.', response: 'Receipt evidence. Embedded Leave Review Flow is optional.'}];
  if (section === 'vault') stages.push({name: 'Access Vault', direction: 'Outgoing → customer', type: 'template', role: 'access',
    gate: 'Paid invoice accepted, exact-file paid entitlement, verified owner/contact.', timing: 'Saved access gap 0–5 seconds; server fallback 4. Actual end-to-end time is not measured here.',
    response: 'URL opens the website. Owner signs in; authorized download redeems the entitlement. URL click is not a WhatsApp reply.'});
  stages.push({name: 'Optional review response', direction: 'Incoming → backend', type: 'interactive.nfm_reply / signed Flow submission',
    gate: 'Customer chooses invoice Flow button; backend validates order-bound token and submission.', timing: 'Customer-controlled; no automatic follow-up timer.', response: 'Review/feedback submission. No separate automatic review template.'});
  return stages;
}
export function frameworkCounts(section: FrameworkSection): {templates: number; messages: number} {
  const sends = frameworkStages(section).filter(stage => stage.role);
  return {templates: new Set(sends.map(stage => stage.role)).size, messages: sends.length};
}
export const FRAMEWORK_GAPS = [
  {title: 'Live execution versus design', detail: 'This map documents source contracts. A template lookup can confirm its current registry status; it cannot prove a particular customer received or paid. Check per-invoice/file evidence.'},
  {title: 'No unified elapsed-time trace', detail: 'The workspace does not yet combine capture, Processing, Completed, invoice acceptance, Access Vault and first download timestamps into one measured journey. Configured spacing is not an actual delivery SLA.'},
  {title: 'Status and receipt recovery', detail: 'Processing/Completed are attempted before receipt. Deferred or failed status work can return while receipt delivery continues. Provider handset order is not guaranteed; expose each stage independently during reconciliation.'},
  {title: 'Template references and approval', detail: 'Stored IDs are source registry references. Current approval and required components must be verified by the sender; framework lookup status does not enable sending.'},
  {title: 'Uncertain sends and reloads', detail: 'Browser attempt locks are scoped to mounted components. Durable backend send claims govern replay, navigation, reloads and other staff clients. Unknown outcomes require reconciliation.'},
  {title: 'Collect reference ownership', detail: 'Architecture says references are server-owned, while Collect currently supplies a browser reference for invoice deduplication. Coordinate a backend idempotency migration before changing that existing contract.'},
  {title: 'Contribute evidence is spread across records', detail: 'Catalog orders, payment activity and invoice references must be correlated. A matching name or ₹300 amount alone is insufficient evidence of a contribution.'},
  {title: 'Release verification', detail: 'Authenticated live QA and provider readiness require per-release verification. The locked TypeScript version is compatible with the lint parser; source checks do not prove customer delivery.'},
];
