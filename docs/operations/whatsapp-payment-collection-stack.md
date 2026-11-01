# WhatsApp Payment Collection — Canonical Stack

**Status:** PRODUCTION SIGNED-OFF / FROZEN — source of truth for the WECARE.DIGITAL WhatsApp payment rail  
**Last audited:** 2026-10-26  
**Region:** `us-east-1`  
**Primary payment WABA:** `2094615664435155`

This document defines the canonical customer journey, runtime ownership, persistence, retry rules,
templates, media, catalog aliases, and the files that must be updated together when the payment rail
changes. Treat contradictions in older execution notes as historical snapshots.

## 0. Production sign-off and freeze

The payment rail was production signed-off on **2026-10-26** with a fresh real Razorpay payment:

- reference: `WD-PAY-A18274BA`
- invoice: `WD/2627/00012`
- payment attempt: `01a1771f-3cf2-79ed-81aa-134d21866f12`
- Razorpay payment: `pay_TsSVLCxB84eWvl`
- amount: **INR 1.22**
- order: `WD-ORD-88R23BNB`

Observed production sequence:

```text
payment request accepted
-> Razorpay payment.captured
-> PaymentAttemptsTable PAYMENT_PAID
-> invoice paymentStatus=captured + paidAt
-> wecare_order_status_v3 processing (template channel)
-> wecare_order_status_v3 completed (template channel)
-> invoice waOrderStatus=completed
-> OrderTable completed
-> paid invoice image generated
-> paid invoice sent on WhatsApp
```

The two order-status messages used the **template channel even with `withinWindow=true`**, proving
the payment rail no longer depends on the 24-hour customer-service window for status transport.

All six dedicated payment alarms remained `OK` after the real-money test:

- `wecare-payment-order-status-deferred`
- `wecare-payment-order-status-uncertain`
- `wecare-payment-order-completed-blocked`
- `wecare-payment-order-status-retry-error`
- `wecare-payment-order-status-retry-query-failed`
- `wecare-payment-invoice-delivery-failed`

The first manual sign-off invocation intentionally hit the sender boundary with a bare Meta phone
ID and was refused `WA_PAY_SENDER_NOT_PERMITTED`; retrying with the production Direct-API sender
ID succeeded. This is evidence that the sender allowlist fails closed.

### Freeze rule

This architecture is now **frozen**. Do not change payment state semantics, template transport,
payment sender identity, idempotency claims, table ownership, or canonical runtime routing during
ordinary feature work.

Unfreeze only for one of:

1. a confirmed production incident,
2. a Meta/Razorpay breaking change,
3. a statutory/accounting requirement,
4. an owner-approved architecture RFC with migration and rollback plans.

Any unfreeze PR must follow manual payment-rail validation in
`docs/operations/repository-validation.md`, update this runbook, and include a
fresh production sign-off plan before merge. Retired CI/tests must not be restored.

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

    Note over C,WA: No additional free-form interactive messages after invoice
    Note over C,DDB: Authenticated Orders history remains at wecare.digital/orders/
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

### Template-only post-payment policy (31 October 2026)

The prior owner-approved (26 October) free-form interactive `cta_url` "View your
order" message has been **retired** at the invoice engine. The customer explicitly
requested that automated payment follow-ups use only approved WECARE.DIGITAL
message templates, not ordinary `type=interactive` messages.

- **Before payment:** use the approved `wecare_whatapp_native_pay_template`
  (Meta wire `type=template` with the required `ORDER_DETAILS` **Review and Pay**
  button). The button itself is a Meta interactive *component inside a template*;
  it is NOT a separate free-form interactive message.
- **After capture:** retain `wecare_order_status_v3` processing then completed,
  followed by exactly one `wecare_default_invoice_image_template` paid-invoice
  PNG and its existing Leave Review Flow button. Meta's payment status sequence,
  GST invoice and one-send claims are unchanged.
- **Services:** after the paid invoice is accepted, send only the verified
  *service-specific approved template* (Vault's `wecare_default_download`
  owner-bound URL, Drop Docs' F003 upload Flow, etc.), once and only after
  payment and entitlement checks.
- **Ordinary catalog/cart orders:** do not invent an unapproved Orders template
  and do not fall back to an interactive `cta_url`. The customer may always
  sign in at `https://wecare.digital/orders/` to see their owned purchases;
  the merchant can submit a new dedicated URL-button template for Meta approval
  in a future, separately reviewed release.
- The retired `_send_order_page_link` function, its order-page-link
  constants, and the post-invoice caller have been deleted from source.
  Previously recorded `INVOICEDELIVERY#<invoiceId>#order-page-link` rows
  remain historical audit evidence only and must never trigger resends.

No direct raw Vault PDF, standalone review Flow, generic Orders CTA or new
payment prompt is automatically sent after a verified paid Vault invoice.
This policy concerns the automated payment **journey**; it does not disable
approved standalone manually initiated customer-support operations.

### Status transport invariant

Order-status delivery is **template-only**. The 24-hour customer-service window does not select an
interactive fallback. If `wecare_order_status_v3` cannot be proven APPROVED, the update is deferred
and retried; it is not silently changed into a different message type.

## 4. Media contract

| Surface | Asset |
| --- | --- |
| Default ORDER_DETAILS item thumbnail | `https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png` |
| Normal item rows | One default WECARE thumbnail on every normal item row |
| Fee / shipping / GST / Delight rows | No item thumbnail |
| Paid invoice template header | Generated invoice PNG under `secure/d/public/Invoice/customer_invoice/` |

Meta's item `image` is optional. The payment rail therefore uses this simpler rule:

- **normal order item:** use one default WECARE thumbnail through `order.items[].image.link`.
- **Convenience Fee / shipping / GST / Delight:** remain image-free.
- **no catalog/product-specific image selection:** this payment-order presentation path does not choose a product image by catalog identity.

The thumbnail is presentation only and does not invent or require a catalog retailer ID.

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

### Invoice coverage across purchase entry points

All genuine commerce purchases converge on the same invoice engine and post-capture receipt guarantee:

| Entry point | Invoice behavior |
| --- | --- |
| Website checkout | Verified Razorpay capture creates/deduplicates the fiscal invoice and guarantees a PNG; the owner can download it through `/ecommerce/my-invoice`, and a verified WhatsApp recipient may also receive the invoice template. |
| WhatsApp catalog/cart checkout | Verified capture creates/deduplicates the invoice, guarantees the PNG, advances the payment-order state, and delivers the invoice template once. |
| Workspace Pay / Inbox / Commerce manual collection | A numbered invoice may be raised before payment so the payment request can be sent; verified capture settles that same invoice and guarantees its paid PNG. |
| Paid WhatsApp Flows / Submit Request | The Flow creates the invoice through `wecare-commerce:live`; verified capture settles it and guarantees the same customer PNG. |
| ChatGPT customer-commerce connector | When the guarded Pay on WhatsApp option is enabled, it delegates to `wecare-commerce:live`; ChatGPT does not collect money itself. Verified Razorpay capture remains the only route to a paid invoice. |
| Modern Vault / paid service checkout | Uses the canonical commerce PaymentAttempt/service-intent path and therefore receives the normal fiscal invoice after verified capture. |

The `secure_file_download` early return in the Razorpay webhook is retained only for historical legacy secure-file gateway orders that predate canonical commerce checkout. Wallet top-ups and voluntary blog contributions are also intentionally non-invoice commerce exceptions.

A verified paid commerce invoice must have at least one `image` / `image#vN` asset even if WhatsApp delivery is unavailable. The webhook calls the invoice engine's internal `ensure-image` action on every verified capture. That action reuses an existing image and renders only when no image exists, so webhook replay does not create duplicate renditions. The customer-invoice download service remains read-only and never advances the GST sequence.

## 5A. Duplicate-send prevention and Meta Message History audit

Customer-visible payment messages use layered idempotency. The layers have different authority and
must not be collapsed:

1. **Business-action claim first.** Payment requests use the PaymentAttempt/send reservation;
   invoice/status/order-page deliveries use CommerceKeys invoice-delivery claims. A lost race means
   no send.
2. **Stable final-boundary key.** Payment-rail callers pass `idempotencyKey` to
   `wecare-outbound-whatsapp:live`:
   - `payment-request:<referenceId>`
   - `order-status:<invoiceId>:processing`
   - `order-status:<invoiceId>:completed`
   - `invoice-receipt:<invoiceId>`
   - historical only: `order-page-link:<invoiceId>` (no new sends after the template-only policy)
   The outbound Lambda hashes this value into its internal message row id. If that row already has
   a Meta WAMID, a replay returns the existing WAMID without another Graph send. A row whose
   outcome is still ambiguous is refused as `MESSAGE_SEND_IN_FLIGHT`. A definite `failed` or
   `rejected` row remains retryable after the higher-level claim is released.
3. **Webhook/status evidence.** `WhatsAppOutboundTable` stores the Meta WAMID and monotonically
   advances accepted/sent/delivered/read/error state from Meta webhooks.
4. **Meta Message History is secondary audit evidence only.** The authenticated
   `GET /wa-business/message-history/events` route reads
   `/{Message-History-ID}/events` with bounded fields/status filters/pagination. The internal
   `messageHistoryForWamid` action first resolves a known WAMID through
   `/{Phone-Number-ID}/message_history`, then reads its events. Neither path sends a message,
   releases a delivery claim, or authorizes a retry.

A Meta history event in `ACCEPTED`, `SENT`, `DELIVERED`, or `READ` proves that Meta has
already accepted that WAMID and is a strong reconciliation signal to suppress a human/operator
re-send. It is **not** sufficient as the primary exactly-once mechanism: if a network timeout
occurs before WECARE learns the WAMID, Message History cannot be safely searched by WECARE's
internal invoice/reference id. In that ambiguous case the existing business claim remains held and
the system fails closed rather than blindly sending a second customer message.

Operator read-only helper:

```text
python scripts/audit_whatsapp_message_history.py --wamid <Meta-WAMID>
```

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

### Meta Message History audit (secondary evidence)

The primary duplicate-prevention mechanism is still the server-owned DynamoDB delivery claim:
one claim per invoice/channel and one claim per `order-status:<target>`. A send is not made
conditional on Meta Message History availability.

For operational reconciliation, `wecare-whatsapp-business-api` exposes a **GET-only** read of
Meta's Message History events for an explicit provider `messageHistoryId`. It supports the
provider delivery states `ACCEPTED`, `SENT`, `DELIVERED`, `READ`, and `ERROR`, plus
cursor pagination. The route uses fixed fields and never sends or mutates a message.

Do not infer a Message History ID from a WAMID. They are separate provider identifiers; the
history read is used only when an explicit history ID is available. If Meta history is
temporarily unavailable, payment/order/invoice sending continues to rely on the existing
claim + WAMID/webhook evidence model.


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

GitHub Actions CI is retired. Payment-rail releases use explicit validation and controlled
deployment instead of repository workflows.

Before release, all of these must pass on the exact tree being deployed:

1. Python compile checks for payment/messaging/shared modules.
2. Manual payment capture, authorization/refusal, webhook, replay and invoice
   readback using an owner-approved staged/controlled verification plan.
3. Workspace TypeScript typecheck.
4. Deterministic Lambda package creation through
   `scripts/deploy_all_lambdas.py::build_zip()`.
No retired automated test suite or GitHub Actions workflow is required.

After validation, deploy only through the repository's documented Lambda release tooling. Publish
immutable versions, move the `live` aliases deliberately, then read back every alias/code hash.
Do not deploy unqualified `$LATEST`.

A payment release is not ready unless all are true:

- payment template is APPROVED, UTILITY, ORDER_DETAILS, English
- order-status template is APPROVED, UTILITY, ORDER_STATUS, English
- invoice template is APPROVED, UTILITY, English
- WABA payment configuration is active and matches expected Razorpay provider MID
- packaged Lambda hashes match the reviewed release artifacts
- production aliases resolve to those hashes

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

### Infra and controlled release
- `scripts/commerce_release_audit.py`
- `scripts/provision_invoice_order_status_route.py`
- `scripts/provision_meta_catalog_sync.py`
- `scripts/provision_meta_catalog_sync_waba2.py`
- `amplify/infra/commerce-history-reconciliation.json`

If a change touches one of the three templates, the payment status sequence, payment media, or
canonical runtime target, reviewers should require this checklist before merge.

## 13. Non-regression checklist

Before production promotion, prove:

- [ ] payment request is `wecare_whatapp_native_pay_template`
- [ ] every normal ORDER_DETAILS item row uses `WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png`
- [ ] Convenience Fee / shipping / GST / Delight rows remain image-free
- [ ] no catalog/product-specific image selection is used for this payment-order thumbnail contract
- [ ] capture sends status template `processing` then `completed`
- [ ] zero interactive order-status messages are used
- [ ] `completed` is never attempted before `processing` acceptance/already-current
- [ ] invoice `waOrderStatus=completed`
- [ ] OrderTable projection becomes completed
- [ ] paid invoice Date/Time uses `paidAt`
- [ ] exactly one invoice template is sent
- [ ] after it, **zero free-form interactive** `cta_url` messages or new order-page-link claims; approved service templates only
- [ ] invoice Flow token is bound to order/invoice and opens FEEDBACK
- [ ] retry index remains ACTIVE and scheduled retry is working
- [ ] `live` catalog alias is WABA1; `waba2` alias is WABA2
- [ ] no catalog production trigger targets `$LATEST`
- [ ] public payment write routes point at `wecare-commerce:live`
- [ ] new internal callers do not target rollback `wecare-checkout` or `wecare-invoice-engine`
- [ ] release-scoped manual payment safety checks and deterministic packaging
      are reviewed against the exact production commit
- [ ] controlled deployment used an approved scoped identity (no static AWS keys)
- [ ] all nine `live` aliases match the production artifact manifest `CodeSha256`

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
