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

## Frontend migration and build repair

- Build #510 failed after `src/components/workspace/service/` and
  `src/components/workspace/seo/` were deleted while still imported.
  PR #2193 **independently restored those modules** and production Amplify
  build #511 succeeded on 2 November 2026. This proposal does **not** delete
  or degrade the restored Blog, SEO, Drop Docs, shipment or service tools.
- The new canonical Vault UI lives at
  `src/components/workspace/pay/VaultWorkbench.tsx`, linked from Pay & Flow
  and any lingering Service/Vault route during its client-side redirect.
- Service/Contribute opens the existing read-only
  `ContributePaymentPlan` rather than the legacy Contribute creator;
  Contribute/Create is exclusively `/workspace/payments?view=contribute&tab=create`.
- The historical journey metadata adapter in
  `src/components/workspace/pay/VaultJourneyPreview.ts` is display-only:
  it excludes retired `ready_offer` steps and cannot send anything.
- The earlier Service and SEO components remain for their other, separately
  authorized operations until an independently reviewed migration retires
  their full feature contracts.
- No infrastructure, files, payment attempts, messages, Meta templates,
  customer entitlements or DynamoDB financial records are deleted by this PR.

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

## Read-only framework inspection

`/workspace/payments?view=collect|vault|contribute&tab=display&panel=framework`
opens the framework for the selected section. The section cards preserve this
panel; Display/Create/Ledger links leave it for the owning operating view.

The framework lists distinct templates versus planned template sends, ordered
staff/provider/customer stages, event gates, configured spacing, variable input
ownership, outgoing payload families, incoming response/event types and known
evidence/recovery gaps. It reads template registry details and, for Vault, the
saved timing configuration. It cannot send, upload, change timing or grant access.
Registry lookup status is separate from the sender's component/readiness checks
and from per-customer acceptance, delivery and capture evidence.

Vault Processing → Completed has a fixed one-second pause only after a newly
accepted Processing send. The paid-invoice → Access gap is 0–5 seconds (four-second
backend fallback). These are deliberate spacings, not measured end-to-end latency
or a guarantee of handset message order. Deferred status work may return while
the paid receipt path proceeds; inspect stage evidence independently.

## Supported outbound transport and exact message inspection

Standalone rich-message send implementations, client helpers, dedicated route
entries, test-console controls and menu editors are deleted. Message transport
accepts only text, approved templates, supported media, contacts, location and
reactions, plus the existing read/typing control envelope. Unknown message types
or fields are rejected by the generic transport contract; there are no dedicated
compatibility endpoints for deleted senders. Sign-in uses its approved OTP
template. Service keywords use plain website links without creating a Flow session.

Approved template ORDER_DETAILS, ORDER_STATUS, embedded FLOW/URL buttons and
incoming form submissions remain. Incoming provider schema names are retained
where required to parse those approved template replies.

The Framework's full-content panel shows the complete public header/thumbnail
links, exact body/footer/button definitions and dynamic-field ownership. Its
fallback snapshot was read from the selected WECARE.DIGITAL messaging account on
2026-11-02 at 04:20 UTC; a matching current template read takes precedence.
Registration-example image URLs are labeled separately from send-time media.
Paid invoice headers use a generated private PNG uploaded as a WhatsApp media ID,
so no universal public invoice-header URL is invented.
