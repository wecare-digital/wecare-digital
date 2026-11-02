# Pay & Flow architecture — Collect, Vault and Contribute
**Date:** 2026-11-02 · **Scope:** rebuild missing frontend modules after deletion, preserve all production financial and provider contracts.

## One workspace; three separately governed journeys

| Section / tab | Display | Create | Ledger |
| --- | --- | --- | --- |
| Collect | `CollectOverview` (read-only) | `PayFlow` invoice creation, saved-invoice review/send | Saved invoices, provider delivery evidence, payment activity |
| Vault | `VaultWorkbench` active/historical files and per-file message evidence | Private upload → confirm → exact owner-bound Review & Pay → paid Access Vault template | Verified VAULT invoices, entitlement evidence |
| Contribute | `ContributePaymentPlan` current server quote + approved shared template metadata | `ContributeStaffControls` Admin-confirmed one-shot native ₹300 send (only if backend says ready) | Commerce orders, payment activity and invoices; **no invented contribution-only invoice filter** |

The route is `/workspace/payments/?view=collect|vault|contribute&tab=display|create|ledger`.
Legacy `view=defaults`, `view=timing`, `view=ledger` bookmarks are explicitly resolved in the existing page. Display never triggers customer sends.

## Boundary 1: Collect (ordinary staff invoices)

```
Staff Collect / Create -> PayFlow
  -> server invoice-engine create / save (invoice ID, payment reference and INR breakdown)
  -> explicit staff send -> invoice-engine send-payment-link
  -> outbound-whatsapp approved template (ORDER_DETAILS)
  -> Meta acceptance / delivery webhook (not a payment state)
  -> Razorpay/webhook verification -> captured invoice / post-payment template sequence
  -> Collect Ledger: invoices, payments and delivery logs
```

- One server-owned INR calculation: item subtotal, supply GST, Delight/discount,
  shipping, convenience net and fee GST. Never mint a payment reference in React.
- Only `wecare_whatapp_native_pay_template` may issue the ORDER_DETAILS payment request.
- Message accepted/read is transport evidence, not payment capture.
- Staff saved invoices remain in Collect Create; no auto-resend after an ambiguous send.
- Do not change payment provider settings or the template's Meta ID from this UI.

## Boundary 2: Vault (private file and paid entitlement)

```
Vault / Create -> VaultWorkbench (new module in workspace/pay)
  -> /secure-files/upload-init          [staff role, backend-generated opaque key]
  -> private S3 presigned PUT           [create-if-absent]
  -> /secure-files/{fileId}/confirm    [server checks actual object]
  -> SecureFilesTable                  [single owner and exact fileId]
  -> explicit /request-payment         [only UNPAID; no renewal/duplicate send]
  -> invoice engine + approved ORDER_DETAILS template
  -> verified payment capture          [never assumed from read/accepted]
  -> entitlement in DownloadGrantsTable
  -> paid invoice/status templates
  -> approved wecare_default_download Access Vault URL template
  -> customer token /secure-files/mine or exact-file lookup
  -> backend verified /download grant redemption
```

- **Display** reads current/historical file records and `/message-log`; it has no
  create, revoke or send control. Original S3 keys, private file URLs and customer
  auth tokens are never rendered or sent over Meta.
- **Create** is a two-action journey. Upload never starts payment. A payment request
  is separately confirmed and locked after one attempt, including network uncertainty.
- New Vault file eligibility is fail-closed if `accessState` is absent,
  `PAID_UNVERIFIED`, `OPEN`, `READY` or `EXPIRED`.
- `READY`/`OPEN` can explicitly **resend** an access link without charging,
  but only the backend may authorize it. No `ready_offer`, Unlock Vault chooser,
  direct `interactive` payload, raw PDF send, or automatically fabricated renewal.
- The one configurable delay is paid-invoice acceptance → Access Vault, 0–5 sec;
  processing/completed/invoice stage ordering and capture gates are server-owned.
- Old Vault records and paid entitlements are not deleted or reset by a frontend
  rebuild. A separate audited retirement/revocation is mandatory.

## Boundary 3: Contribute (catalog purchase, not Vault or request service)

```
Contribute / Display -> ProductsTable-driven exact quote via service pricing
Contribute / Create  -> verified saved contact
                    -> server read-only staff-contribute-readiness
                    -> Meta approved payment template verification
                    -> Admin confirmation and one non-retried POST:
                       /ecommerce/checkout action staff-contribute-send
                    -> server re-price / verify identity / reserve attempt
                    -> shared native WhatsApp Review & Pay
                    -> webhook capture -> Commerce order, receipt and payment records
Contribute / Ledger -> existing Commerce Orders + payment activity + invoice references
```

- Expected target **₹300.00 inclusive**; Express **₹15.00 inside** total,
  not a separate add-on. The browser example is a presentation only:
  ₹235.41 + GST ₹42.37 − Delight ₹1.38 + Express ₹15
  + convenience ₹7.29 + fee GST ₹1.31 = ₹300.00.
- Any mismatch between server breakdown, template approval, Admin/MFA,
  saved contact or current backend readiness disables sending.
- Request-accepted, read and paid are distinct states. Unknown outcome
  locks the draft and requires ledger reconciliation before any retry.
- No dedicated Contribute payment Meta template or mutable browser amount.

## Approved template contract, unchanged

| Role | Approved template |
| --- | --- |
| Native payment | `wecare_whatapp_native_pay_template` |
| Payment processing and completed | `wecare_order_status_v3` |
| Paid GST invoice (review Flow button **inside** template) | `wecare_default_invoice_image_template` |
| Paid Vault access URL | `wecare_default_download` |

The approved FLOW button embedded inside a `type=template` message is legal and
is **not** a standalone `type=interactive` send. Do not create a second payable
template, use a retired Vault offer or modify the canonical payment rail.

## Removed-frontend directory migration and safeguards

- `src/components/workspace/service/` and `src/components/workspace/seo/`
  were deleted. Do **not** silently restore old interactive menu/payment code.
- New Vault UI resides at `src/components/workspace/pay/VaultWorkbench.tsx`.
  Historical journey metadata adapter is read-only:
  `src/components/workspace/pay/VaultJourneyPreview.ts`.
- `src/pages/workspace/service/index.tsx` retains read-only server prices,
  invoice ledgers, F003 document evidence and links to canonical Pay & Flow.
  It does not pretend a deleted review/upload tool still exists.
- `src/pages/workspace/content/index.tsx` keeps its route and short links,
  but marks deleted Blog/SEO editors as retired instead of importing missing
  modules or inventing editing APIs.
- Runtime web production remains on the **last successful Amplify release**
  until a new branch passes `npx tsc --noEmit` and the Amplify build gates.
- No infrastructure, secure files, payment attempts, messages, templates,
  customer entitlements or DynamoDB financial records are deleted here.

## Release validation checklist

1. `python3 -m compileall -q` on customer-profile, inbound WhatsApp, secure
   files and shared integration handlers.
2. `PYTHONPATH=amplify/functions/shared python3 -m unittest discover -s tests
   -p 'test_*contribut*.py' -v` for frozen ₹300 quote.
3. `npm ci`, `npx tsc --noEmit`, `npm run build` on Node 24 and npm 11.6.2;
   review private diagnostic output and static export.
4. Collect: initial and saved-invoice forms + ledger compile; no client-side
   ORDERS payment construction or duplicate send.
5. Vault: read-only register, active/historical split, private upload preview,
   exact-file eligibility, provider evidence, 4-stage approved templates,
   no interactive menu, no receipt-before-capture.
6. Contribute: read-only price, exact ₹300 quote and Admin readiness; send
   disabled if any check is uncertain. No test sends to live customers.
7. Only merge after successful preview build and controlled QA. Backend Lambda
   deployments and old-route retirements are separate, explicitly reviewed jobs.
