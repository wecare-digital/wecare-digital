# WhatsApp Payment Collection — Canonical Stack

**Status:** source of truth for the WECARE.DIGITAL WhatsApp payment rail  
**Last audited:** 2026-10-26  
**Region:** `us-east-1`  
**Primary payment WABA:** `2094615664435155`

This document defines the canonical customer journey, runtime ownership, persistence, retry rules,
templates, media, catalog aliases, and the files that must be updated together when the payment rail
changes. Treat contradictions in older execution notes as historical snapshots.

## 1. Product invariant

This rail collects payment. It is not a shipping/fulfilment workflow.

For a WhatsApp `ORDER_DETAILS` payment, the Meta order lifecycle is deliberately collapsed to:

```text
pending -> processing -> completed
```

Customer wording:

- `processing`: **Payment received.**
- `completed`: **Payment complete.**

Do not introduce `partially-shipped` or `shipped` into this payment-only rail. Operational/service
work may have its own internal states, but those states must not reopen or mutate the terminal Meta
payment order.

## 2. Customer-visible sequence

```mermaid
sequenceDiagram
    participant C as Customer
    participant WA as WhatsApp / Meta
    participant CO as wecare-commerce:live
    participant RZ as Razorpay
    participant WH as wecare-razorpay-webhook:live
    participant OW as wecare-outbound-whatsapp:live
    participant DDB as DynamoDB
    participant S3 as wecare-digital-get

    CO->>OW: wecare_whatapp_native_pay_template
    OW->>WA: ORDER_DETAILS + Review and Pay
    WA->>C: Payment request
    C->>WA: Pay
    WA->>RZ: Payment gateway flow
    RZ->>WH: signed payment.captured webhook
    WH->>RZ: authoritative provider readback
    WH->>WA: payment binding / status verification
    WH->>DDB: persist captured payment + paidAt + final order/invoice

    WH->>CO: order_status processing, "Payment received."
    CO->>OW: wecare_order_status_v3
    OW->>WA: template ORDER_STATUS processing
    WA-->>OW: accepted
    CO->>DDB: waOrderStatus=processing

    WH->>CO: order_status completed, "Payment complete."
    CO->>OW: wecare_order_status_v3
    OW->>WA: template ORDER_STATUS completed
    WA-->>OW: accepted
    CO->>DDB: waOrderStatus=completed; OrderTable completed

    CO->>S3: render/store paid invoice PNG using paidAt
    WH->>CO: send invoice
    CO->>OW: wecare_default_invoice_image_template + invoice PNG + review token
    OW->>WA: invoice template
    WA->>C: Paid invoice + Leave Review Flow

    CO->>OW: cta_url "View your order" -> /orders/?o=<orderNumber> (after the invoice is accepted)
    OW->>WA: interactive cta_url (24-hour window only)
    WA->>C: Order page link
```

### Hard ordering rule

`completed` may be sent only after `processing` was accepted or is already the recorded Meta
state. Never fire both blindly in parallel. This prevents Meta error 2046 and makes webhook
redelivery idempotent.

## 3. Approved templates

| Role | Template | Meta ID | Category / subcategory | Usage |
| --- | --- | ---: | --- | --- |
| Payment request | `wecare_whatapp_native_pay_template` | `2714938845570815` | UTILITY / ORDER_DETAILS | One send before payment |
| Payment order state | `wecare_order_status_v3` | `1754227779211208` | UTILITY / ORDER_STATUS | Reused for processing and completed |
| Paid invoice | `wecare_default_invoice_image_template` | `1782246473079550` | UTILITY / CUSTOM | One send after terminal status |

The invoice template owns the **Leave Review** Flow button:

- Flow ID: `993862443003108`
- action: `NAVIGATE`
- screen: `FEEDBACK`

There is no separate review message in the payment rail.

### Order page link (owner-approved 2026-10-26)

After the paid invoice template is accepted, a WhatsApp cart or catalog-service buyer gets one
free-form interactive `cta_url` message: "View your order", opening
`https://wecare.digital/orders/?o=<orderNumber>`. The page is session-gated (checkout's `order`
action answers only for the signed-in owner). Owner: invoice engine `_send_order_page_link`,
called from `send_invoice_whatsapp`.

- Never instead of the invoice, and never on a staff re-send (`force`).
- Not sent for website payments (the buyer is already on the page) or invoice-native
  `WHATSAPP_NATIVE_PG` payments (no order row).
- At most once per invoice: delivery claim `INVOICEDELIVERY#<invoiceId>#order-page-link`, kept
  on every outcome, so a failure is never retried into a duplicate.
- Free-form, so inside the 24-hour customer-service window only. Outside it, outbound refuses it
  and nothing else is sent. It is not a status message, so the template-only rule below is
  unaffected.

### Status transport invariant

Order-status delivery is **template-only**. The 24-hour customer-service window does not select an
interactive fallback. If `wecare_order_status_v3` cannot be proven APPROVED, the update is deferred
and retried; it is not silently changed into a different message type.

## 4. Media contract

| Surface | Asset |
| --- | --- |
| Large payment-template header | `https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png` |
| Small non-catalog/manual order item image | `https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png` |
| Paid invoice template header | Generated invoice PNG under `secure/d/public/Invoice/customer_invoice/` |

Meta does not allow custom item `image` together with `retailer_id` / `catalog_id`. Therefore:

- **non-catalog/manual invoice collection:** no synthetic `ITEM_n` retailer IDs; use the fixed small icon.
- **true catalog checkout:** preserve the real catalog identity and catalog-managed product image.

Do not use `wecare-catalog-icon.png` as the large payment header.

## 5. Canonical runtimes

### Write path

| Runtime | Canonical responsibility |
| --- | --- |
| `wecare-commerce:live` | Checkout, invoice engine surface, payment request construction, order-status state machine, invoice send |
| `wecare-razorpay-webhook:live` | Signed webhook verification, provider readback, capture reconciliation, post-payment orchestration, retry sweep |
| `wecare-outbound-whatsapp:live` | Final Meta payload construction and send boundary; live template approval gate |
| `wecare-whatsapp-business-api:live` | Meta payment/config/template/status reads and WhatsApp business APIs |
| `wecare-inbound-whatsapp:live` | Meta inbound webhook ingestion, carts/payment-status signals |
| `wecare-meta-catalog-sync:live` | WABA1 catalog projection |
| `wecare-meta-catalog-sync:waba2` | WABA2 catalog projection |

### Read/support path

| Runtime | Responsibility |
| --- | --- |
| `wecare-customer-invoice:live` | Customer-owned invoice read/download surface; not a fiscal writer |
| `wecare-customer-orders:live` | Customer order read surface |
| `wecare-payments-read:live` | Staff/payment read APIs |
| `wecare-service-api:live` | Workspace service/order APIs |
| `wecare-secure-files:live` | Separate secure-file entitlement/payment rail; do not merge into commerce payment collection |

### Rollback compatibility

`wecare-checkout:live` and `wecare-invoice-engine:live` may remain deployed as rollback-compatible
packages, but new source defaults and internal calls must point at `wecare-commerce:live`.
Do not add new callers to rollback runtimes.

## 6. Public API routes

Canonical API: `wecare-digital-api` (`zllr9lrg7j`).

Important payment routes:

| Route | Runtime |
| --- | --- |
| `POST /ecommerce/checkout` | `wecare-commerce:live` |
| `POST /ecommerce/prepare-checkout` | `wecare-commerce:live` |
| `POST /ecommerce/checkout/status` | `wecare-commerce:live` |
| `POST /invoices/from-payment` | `wecare-commerce:live` |
| `POST /invoices/{invoiceId}/order-status` | `wecare-commerce:live` |
| `POST /invoices/{invoiceId}/send-whatsapp` | `wecare-commerce:live` |
| `POST /invoices/{invoiceId}/generate-image` | `wecare-commerce:live` |
| `POST /razorpay-webhook` | `wecare-razorpay-webhook:live` |
| `POST /whatsapp/send` | `wecare-outbound-whatsapp:live` |
| `GET /wa-business/payment-config/check` | `wecare-whatsapp-business-api:live` |
| `POST /ecommerce/my-invoice` | `wecare-customer-invoice:live` |

If any payment write route is repointed away from `wecare-commerce:live`, update this document and
the release audit in the same change.

## 7. DynamoDB ownership

| Table | Key / important index | Authority |
| --- | --- | --- |
| `stack-wecare-digital-CommerceKeys` | PK `orderId` | Idempotency/identity claims: PAYREF, delivery claims, order binding |
| `stack-wecare-digital-PaymentAttemptsTable` | PK `paymentAttemptId`; `referenceId-index`; `status-index` | Payment attempt lifecycle and expected money |
| `stack-wecare-digital-PaymentsTable` | PK `id`; `paymentId-index`; `orderId-index` | Provider transaction projection |
| `stack-wecare-digital-OrderTable` | PK `orderId`; `orderStatus` index | Customer-facing order/payment-order projection |
| `stack-wecare-digital-InvoicesTable` | PK `invoiceId`; `referenceId-index`; `orderStatusRetry-index` | Invoice header, payment state, last accepted Meta status, deferred status |
| `stack-wecare-digital-InvoiceItemsTable` | PK `invoiceId` + SK `itemIndex` | Fiscal invoice lines |
| `stack-wecare-digital-InvoiceAssetsTable` | PK `invoiceId` + SK `assetType` | Generated PNG/PDF assets |
| `stack-wecare-digital-InvoiceSequenceTable` | PK `fy` | Statutory invoice sequence |
| `stack-wecare-digital-InvoiceDeliveryLogTable` | PK `invoiceId` + SK `timestamp` | Invoice delivery evidence |
| `stack-wecare-digital-ProductsTable` | PK `id`; DynamoDB stream enabled | AWS product authority feeding Meta catalogs |
| `stack-wecare-digital-ContactsTable` | PK `id`; `phone-index`, `bsuid-index` | Customer/WhatsApp identity |
| `stack-wecare-digital-WhatsAppOutboundTable` | PK `id`; `paymentReferenceId-index`; `whatsappMessageId-index` | Outbound message evidence |
| `stack-wecare-digital-RazorpayWebhookLogTable` | PK `id`; `paymentId-index`, `eventType-index` | Provider webhook audit |
| `stack-wecare-digital-WebhookDedup` | PK `eventId` | Webhook idempotency |
| `stack-wecare-digital-FlowSubmissionTable` | PK `submissionId`; `orderId`, `paymentRefId` indexes | Review/Flow completion linkage |
| `stack-wecare-digital-FlowRegistryTable` | PK `flowId` | Flow metadata |

Do not merge `PaymentsTable` and `PaymentAttemptsTable`: they answer different questions.
Do not collapse invoice header/items/assets/delivery/sequence tables: they separate fiscal state,
artifacts, delivery evidence and statutory numbering.

## 8. State authority

### Money

```text
PaymentAttemptsTable: PAYMENT_REQUEST_SENT -> PAYMENT_PAID
PaymentsTable:        pending -> captured
InvoicesTable:        pending_payment -> paid
paidAt:               authoritative capture timestamp
```

A paid invoice displays `paidAt` as its prominent Date/Time. `createdAt` remains the creation
timestamp and fallback for unpaid/legacy rows.

### Meta payment order

```text
pending -> processing -> completed
```

`InvoicesTable.waOrderStatus` is the last status accepted by Meta and is the authority used to
validate the next transition. It advances only after a successful Meta send.

`OrderTable.orderStatus` / `status` is updated to the same accepted state after Meta accepts.

Workspace operational/service statuses are separate and must not be used to invent a Meta
fulfilment transition.

## 9. Idempotency and retry

### Capture

Razorpay webhooks are deduplicated through `WebhookDedup` and provider/payment claims in
`CommerceKeys`. Provider readback, not webhook body alone, decides captured money.

### Order-status sends

Each `(invoiceId, targetStatus)` has a delivery claim in `CommerceKeys`.

If the approved ORDER_STATUS template is unavailable:

1. invoice stores `pendingOrderStatus`
2. invoice stores `orderStatusRetry=PENDING`
3. row appears in `orderStatusRetry-index`
4. the 5-minute `wecare-commerce-customer-links` EventBridge run invokes
   `wecare-razorpay-webhook:live`
5. its reconciliation action calls the deferred order-status retry
6. retry remains template-only

Do not create another scheduler for this retry unless the existing shared 5-minute reconciler is
intentionally decomposed.

### Invoice delivery

Invoice delivery is idempotent and independent from status delivery. A temporary Meta status
failure must not charge twice or create a second invoice. The status retry can complete later.

## 10. Catalog synchronization

Live invariant verified 2026-10-26:

| Alias | Catalog | Token field | ProductsTable stream | Backstop schedule |
| --- | ---: | --- | --- | --- |
| `wecare-meta-catalog-sync:live` | `1457045652952851` (WABA1) | `access_token` | enabled | `wecare-meta-catalog-sync-schedule` |
| `wecare-meta-catalog-sync:waba2` | `1317472650427643` (WABA2) | `access_token_waba2` | enabled | `wecare-meta-catalog-sync-waba2-schedule` |

Both stream mappings and both schedules must target aliases. Never target unqualified
`wecare-meta-catalog-sync` / `$LATEST` in production.

## 11. Release gates

The default branch carries `.github/workflows/payment-rail-ci.yml`.

### CI and production deployment

For payment-rail pull requests, the workflow must pass:

1. Python compile checks for payment/messaging/shared modules.
2. The hermetic WhatsApp payment-rail simulation.
3. Workspace TypeScript typecheck.
4. Deterministic Lambda package creation through the repository's own
   `scripts/deploy_all_lambdas.py::build_zip()`.

On a push to `wecare.digital` that touches the payment rail, the same workflow reruns all checks,
packages the tested tree, then deploys those exact packages to the eight payment-related Lambda
`live` aliases. Deployment uses short-lived GitHub OIDC credentials only; there are no static AWS
keys in GitHub.

AWS trust:

- OIDC provider: `arn:aws:iam::775261844268:oidc-provider/token.actions.githubusercontent.com`
- deployment role: `arn:aws:iam::775261844268:role/wecare-payment-deploy-oidc`
- trusted subject:
  `repo:wecare-digital@319896805/wecare-digital@1342943014:ref:refs/heads/wecare.digital`
- audience: `sts.amazonaws.com`

The deployment role is deliberately limited to Lambda read/code/version/alias operations on:

- `wecare-commerce`
- `wecare-checkout`
- `wecare-invoice-engine`
- `wecare-razorpay-webhook`
- `wecare-outbound-whatsapp`
- `wecare-whatsapp-business-api`
- `wecare-service-api`
- `wecare-ai-generate-response`

The deploy job verifies each artifact's AWS `CodeSha256`, publishes an immutable version, moves
`live`, and reads the alias hash back. A hash mismatch fails the release. Rollback-compatible
`wecare-checkout` and `wecare-invoice-engine` stay package-compatible even though new callers use
`wecare-commerce:live`.

A payment release is not ready unless all are true:

- payment template is APPROVED, UTILITY, ORDER_DETAILS, English
- order-status template is APPROVED, UTILITY, ORDER_STATUS, English
- invoice template is APPROVED, UTILITY, English
- WABA payment configuration is active and matches expected Razorpay provider MID
- packaged Lambda hashes match the release manifest
- production aliases are active
- smoke-test bypass flags are off

The release audit must fail closed if any of these cannot be proven.

## 12. Files that must move together

When changing the payment journey, inspect/update this set in the same PR:

### Payment/status behavior
- `amplify/functions/payments/razorpay-webhook/handler.py`
- `amplify/functions/payments/invoice-engine/handler.py`
- `amplify/functions/messaging/outbound-whatsapp/handler.py`
- `amplify/functions/shared/lambda_utils/ecommerce/wa_order_status.py`
- `amplify/functions/shared/lambda_utils/ecommerce/wa_payment_request.py`

### Templates/media
- `amplify/functions/shared/lambda_utils/whatsapp_templates.py`
- `amplify/functions/shared/lambda_utils/template_media.py`
- `amplify/functions/messaging/whatsapp-template-management/handler.py`

### Invoice rendering
- `amplify/functions/payments/invoice-engine/receipt_layout.py`
- `docs/invoice-layout.md`

### UI/API
- `src/components/workspace/pay/PayFlow.tsx`
- `src/api/client.ts`
- `amplify/functions/core/service-api/handler.py`

### Internal runtime routing
- `amplify/functions/messaging/whatsapp-business-api/handler.py`
- `amplify/functions/messaging/whatsapp-business-api/flows/common.py`
- `amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py`
- `amplify/functions/ai/ai-generate-response/handler.py`
- `config/lambda-env-manifest.json`

### Infra/release/tests
- `scripts/commerce_release_audit.py`
- `scripts/verify_whatsapp_catalog_payment_rail.py`
- `scripts/provision_invoice_order_status_route.py`
- `scripts/provision_meta_catalog_sync.py`
- `scripts/provision_meta_catalog_sync_waba2.py`
- `amplify/infra/commerce-history-reconciliation.json`

If a change touches one of the three templates, the payment status sequence, payment media, or
canonical runtime target, reviewers should require this checklist before merge.

## 13. Non-regression checklist

Before production promotion, prove:

- [ ] payment request is `wecare_whatapp_native_pay_template`
- [ ] large header is `whatsapp-header.png`
- [ ] manual/non-catalog item image is `wecare-catalog-icon.png` with no synthetic retailer ID
- [ ] true catalog items retain catalog identity/image
- [ ] capture sends status template `processing` then `completed`
- [ ] zero interactive order-status messages are used
- [ ] `completed` is never attempted before `processing` acceptance/already-current
- [ ] invoice `waOrderStatus=completed`
- [ ] OrderTable projection becomes completed
- [ ] paid invoice Date/Time uses `paidAt`
- [ ] exactly one invoice template is sent
- [ ] after it, at most one "View your order" `cta_url` (WhatsApp cart/catalog-service only), never retried
- [ ] invoice Flow token is bound to order/invoice and opens FEEDBACK
- [ ] retry index remains ACTIVE and scheduled retry is working
- [ ] `live` catalog alias is WABA1; `waba2` alias is WABA2
- [ ] no catalog production trigger targets `$LATEST`
- [ ] public payment write routes point at `wecare-commerce:live`
- [ ] new internal callers do not target rollback `wecare-checkout` or `wecare-invoice-engine`
- [ ] payment CI/test/package jobs are green on the production commit
- [ ] deploy job succeeded with GitHub OIDC (no static AWS keys)
- [ ] all eight `live` aliases match the production artifact manifest `CodeSha256`

## 14. Failure policy

Fail closed on:

- template not approved / provider read unavailable
- payment configuration mismatch
- reference/payment binding mismatch
- amount mismatch
- invalid Meta status transition
- ambiguous invoice/reference resolution
- duplicate delivery claim

Never compensate a payment-message failure by minting a new reference, charging again, sending a
different message transport, or rewriting financial truth.
