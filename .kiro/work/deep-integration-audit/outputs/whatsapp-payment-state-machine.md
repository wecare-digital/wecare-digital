# WhatsApp payment state machine

Grounded in the **actual current code** at `deep-integration-audit` @ `0425dce1`
(`origin/stack` `53ed298e`). Every transition cites `file:line`. Anything the current code does
**not** handle is marked **GAP** and is not invented.

Design/audit only. No payment was created, captured, refunded or simulated. No webhook was
fabricated. No gate was enabled.

Primary sources traced:

- `amplify/functions/ecommerce/checkout/handler.py` (live v40, **byte-identical to source**)
- `amplify/functions/payments/razorpay-webhook/handler.py`
- `amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py`
- `amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py`, `paid_vault.py`
- `amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py`, `order_keys.py`,
  `wix_writeback.py`
- `amplify/functions/shared/lambda_utils/payment_readiness.py`
- `amplify/functions/payments/invoice-engine/handler.py`

---

## 0. The governing principle, verified in code

> A downstream failure **after** a successful payment must not re-charge, and must leave a
> recoverable, idempotent reconciliation state.

**Verified.** Every post-capture side effect is either claimed by a conditional write or
explicitly fail-open-without-reversal, and none of them can mint a new payment reference:

| Post-capture step | Mechanism | Can it re-charge? |
|---|---|---|
| canonical order | `order_keys.claim_order_for_payment:468` | No — claim keyed on `paymentAttemptId` |
| public order number | `reserve_public_order_number:427` / `reserve_order_number:641` | No |
| paid transition | `ConditionExpression='#st <> :paid'`, `razorpay-webhook:2144` | No |
| status monotonicity | `ConditionExpression=payment_status.condition_expression()` with `:rank`, `:2027-2031` | No |
| invoice creation | `attribute_not_exists(invoiceId)` claim, `invoice-engine:849-852` | No |
| invoice WhatsApp delivery | `claim_invoice_delivery(... 'whatsapp')` → `INVOICEDELIVERY#<id>#whatsapp` | No |
| post-payment Flow send | `attribute_not_exists(postPaymentFlowSentAt)`, `:1714-1722` | No |
| review request | `claim_invoice_delivery(... 'review')`, `:2601-2604` | No |
| Wix external order | returns existing `wixOrderId` on duplicate, `wix_writeback:193-209` | No |
| settlement row | `attribute_not_exists(id)`, `:2864` | No |
| capture that cannot be placed | `record_capture_quarantine:699` | No |

The one thing that *could* cause a second charge is a second **payment reference**, and that is
claimed before any message is sent — `reserve_payment_reference:352` /
`allocate_payment_reference:399`, plus the native source-message claim
`CATALOGSERVICEMSG#<sourceMessageId>` with `attribute_not_exists(orderId)`
(`catalog_services.py:77-85`), which returns `CATALOG_SERVICE_REPLAY` on conflict.

---

## 1. Happy path

```
ENTRY
  └─ catalog item tap / keyword          catalog_services.py:41-43
VERIFY_IDENTITY
  └─ verified_identity()                 catalog_service_checkout.py (all nine conditions)
     fail → VERIFIED_CUSTOMER_REQUIRED   catalog_services.py:49-53
CHECK_ELIGIBILITY
  ├─ flag                                catalog_services.py:43 / checkout:3081
  ├─ writeback gates                     checkout:3083-3084
  └─ meta_ready(): 3 APPROVED templates + Flow PUBLISHED
                                         catalog_service_checkout.py:91-105
LOAD_RELEVANT_ORDER / CONTEXT
  ├─ SUBMIT_REQUEST → ≥1 earlier owned order
  │                                      catalog_services.py:63-70 (list_orders)
  └─ VAULT → one active, owned, unpaid, ungranted file
                                         catalog_services.py:88-96
SERVER-SIDE PRICE            Wix is the authority; no browser amount
FREEZE QUOTE                 total_payable_paise + convenience fee + GST on the fee
CREATE_OR_REUSE_PAYMENT_ATTEMPT
RESERVE_OR_REUSE_REFERENCE   order_keys.reserve/allocate_payment_reference:352,399
SEND ORDER-DETAILS / REVIEW & PAY
  └─ wecarepay_wa, ORDER_DETAILS button, 15-min order.expiration
                                         catalog_service_checkout.py:78-88
PAYMENT_PENDING
```

**Embedded Flow-payment is NOT used and NOT supported.** The implemented pattern is exactly
service selection → order-details message → Review & Pay → provider confirm → paid Flow
invitation. No in-Flow payment component exists anywhere in the tree. Whether the account could
support one is **NOT VERIFIED — META TOKEN READ UNAVAILABLE**.

**Entry pre-state.** The native purchase starts from an **inbound customer message**; outside
Meta's 24-hour window the handler returns `AWAITING_CUSTOMER_MESSAGE` and does **not** substitute
another template or send an unapproved invitation.

---

## 2. States and branches

Columns: **Authoritative record** · **Retry allowed** · **Customer-facing message** ·
**New reference allowed** · **Payment resendable** · **Charged again** · **Reconciliation** ·
**Idempotency key**.

### 2.1 Pre-payment

#### `VERIFY_IDENTITY` fails
Record: ContactsTable + Cognito (read-only). Retry: yes, unlimited — no state written.
Message: "Please sign in to your WECARE.DIGITAL customer account and verify this WhatsApp number
before purchasing this service" + sign-in link (`catalog_services.py:50-53`;
`customer_commands.py:81` for the Orders/Customer-ID variant).
New reference: **no** — refusal precedes reservation. Resendable: n/a. Charged again: **no**.
Reconciliation: owner action O2 (authenticated profile save writes `checkoutCustomerId`).
Key: none.

#### `CHECK_ELIGIBILITY` fails
Record: environment + live Meta readback. Retry: yes.
Messages: `NATIVE_SERVICE_ROLLOUT_DISABLED` (`checkout:3081`, `catalog_services.py:43`),
`NATIVE_SERVICE_WRITEBACK_NOT_READY` (`checkout:3083-3084`), or `meta_ready` false → no payable
reference minted. New reference: **no**. Charged again: **no**. Reconciliation: owner gates.
Key: none.

#### `LOAD_RELEVANT_ORDER` fails
Submit Request, no earlier owned order → `SUBMIT_REQUEST_PARENT_ORDER_REQUIRED`
(`catalog_services.py:63-70`) with the copy "We could not find an earlier order linked to your
verified account. **No payment has been requested.** Please message us so we can help link your
order." Vault, no eligible file → `VAULT_FILE_NOT_READY` (`:97-101`) with "There are no unpaid
documents ready for this purchase. If you already paid, open your Vault access message. **No new
payment has been requested.**"
New reference: **no** — the refusal is before reservation, which is the design's own stated fix
("Submit Request refuses payment when no earlier owned order can be fetched").
Charged again: **no**. Key: `CATALOGSERVICEMSG#<sourceMessageId>` already claimed for the session.

> **GAP (F-3, MEDIUM-HIGH, latent).** Vault eligibility at `catalog_services.py:94` is
> `file.get('ownerCustomerId') in (None, identity.customer_id)` — a file with **no** customer
> attribution qualifies on an `ownerPhone` match alone. A reassigned number could be charged for,
> and delivered, a prior holder's document. Delivery re-checks the *phone*
> (`paid_vault.py:49`), which still matches, so the second gate does not catch this case.
> Must be fixed before the native flag is enabled.

#### `DUPLICATE_CUSTOMER_TAP`
Record: `CATALOGSERVICEMSG#<sourceMessageId>` on `WixOrderIds`, claimed with
`attribute_not_exists(orderId)` (`catalog_services.py:77-85`).
Retry: harmless. Message: none (silent — `CATALOG_SERVICE_REPLAY`).
New reference: **no**. Resendable: no. Charged again: **no**.
Reconciliation: none needed. Key: `CATALOGSERVICEMSG#<sourceMessageId>`.

#### `MESSAGE_SEND_FAILED` (order-details / Review & Pay never reached the customer)
Record: the reserved `PAYREF#<referenceId>` row exists; no capture.
Retry: yes, and it **must reuse** the reserved reference —
`resolve_payment_reference:380` / `allocate_payment_reference:399` return the existing one.
Message: existing outbound failure handling; no new payment copy.
New reference: **no**. Resendable: **yes, same reference**. Charged again: **no**.
Reconciliation: reference expires unused; no money moved. Key: `PAYREF#<referenceId>`.

> **GAP (LOW).** No automatic re-send of the order-details message after a transport failure, and
> no explicit customer-facing copy for "we could not deliver your payment request". The session
> row carries `expiresAt = now + 3600` (`catalog_services.py:86`) so it self-cleans, but the
> customer is told nothing. Not a money defect.

---

### 2.2 Payment outcomes

#### `PAYMENT_VERIFIED`
Record: the order row transitioned under `ConditionExpression='#st <> :paid'`
(`razorpay-webhook:2144`), plus a monotonic rank guard (`:2027-2031`). Entry to the webhook is
signature-gated: `_verify_signature:322-340` — fail-closed on a missing secret (`:324-328`),
fail-closed on a missing header (`:329-331`), `hmac.compare_digest` (`:338`), and a mismatch log
carrying only `bodyLen` (`:343-347`).
Retry: idempotent. Message: receipt/invoice + (once) review.
New reference: **no**. Resendable: no. Charged again: **no**.
Reconciliation: none. Key: `paymentAttemptId` → `claim_order_for_payment:468`.

#### `PAYMENT_FAILED`
Record: payment-attempt row, status set under the rank guard.
Retry: yes — a new attempt. Message: existing failure copy.
New reference: **yes**, a new attempt gets a new reference. Resendable: yes, as a new attempt.
Charged again: **no** — the failed attempt collected nothing.
Reconciliation: none. Key: new `paymentAttemptId`.

#### `PAYMENT_CANCELLED`
Same as `PAYMENT_FAILED` — the current code does not distinguish customer cancellation from
provider failure at the state level.

> **GAP (LOW).** No distinct `PAYMENT_CANCELLED` state or distinct copy. Both land in the generic
> non-paid branch. Operationally equivalent (nothing collected, retry allowed); it is a reporting
> gap, not a money gap.

#### `PAYMENT_EXPIRED`
Record: `order.expiration` is set to `now + 900` in the order-details payload
(`catalog_service_checkout.py:88`, "Complete payment within 15 minutes"); the native session row
carries `expiresAt = now + 3600` (`catalog_services.py:86`).
Retry: yes — a new catalog tap, which is a new `sourceMessageId` and therefore a new session.
Message: none proactive. New reference: **yes** (new session). Charged again: **no**.
Reconciliation: expired rows age out. Key: new `CATALOGSERVICEMSG#<sourceMessageId>`.

> **GAP (LOW).** Expiry is enforced by Meta's order-details timer and by the session TTL, not by a
> server-side sweep that marks the attempt expired. No "your payment request expired" message is
> sent. Benign — an expired reference cannot be captured — but the attempt row's terminal state is
> implicit rather than recorded.

#### `CUSTOMER_ABANDONED`
Record: reserved reference, no capture. Retry: yes, same reference while unexpired.
Message: **none, deliberately** — chasing a payment is a marketing send and would need an approved
template plus the 24-hour window. New reference: no (reuse). Charged again: **no**.
Reconciliation: none. Key: `PAYREF#<referenceId>`.

#### `PROVIDER_TIMEOUT`
Record: whatever the provider has; locally the attempt stays non-paid.
Retry: the provider retries the webhook; the handler is idempotent.
Message: none. New reference: **no**. Charged again: **no**.
Reconciliation: the capture arrives later and settles once (`:2144`); if it cannot be placed,
`record_capture_quarantine:699`. Key: `paymentAttemptId` / `provider_transaction_id` via
`resolve_order_for_provider_payment:579`.

> Historical note, resolved: the old `C4` deadlock — nothing ever wrote `providerPaymentId` /
> `providerOrderId`, so every reconciliation raised `RazorpayUnavailable` — is addressed by
> `resolve_order_for_provider_payment:579` plus `record_capture_quarantine:699`. Both exist in
> current source. **Verified present; not exercised live in this read-only step.**

#### `DUPLICATE_CALLBACK` (webhook replay)
Record: unchanged. Retry: inherently. Message: none.
New reference: **no**. Resendable: no. Charged again: **no**.
Reconciliation: none. Keys: `#st <> :paid` (`:2144`), rank guard (`:2027-2031`),
`attribute_not_exists(invoiceId)` (`invoice-engine:849-852`),
`INVOICEDELIVERY#<invoiceId>#whatsapp`, `INVOICEDELIVERY#<invoiceId>#review`,
`attribute_not_exists(postPaymentFlowSentAt)` (`:1714`), `attribute_not_exists(id)` for
settlements (`:2864`).
Conditional failures are logged at **info**, not error (`:2149-2152`, `:1721`) — "expected and
correct: a stale or out-of-order delivery".

> **GAP (F-5, LOW).** Six of those detections are substring matches on exception prose —
> `'ConditionalCheckFailedException' in str(e)` at `razorpay-webhook:1719,2036,2149,2746,2866` and
> `invoice-engine:853` — while `order_keys.is_conditional_failure:177` already provides the
> structural test. A botocore message change would silently reclassify a race as an error, or at
> `:2149` an error as a race, on the money path.

---

### 2.3 Post-payment failures — the critical class

All of these occur **after** money is collected. None may re-charge. None may reverse the paid
state.

#### `ORDER_CREATION_FAILED_AFTER_PAYMENT`
Record: the capture is real; the canonical order is not placed.
Retry: yes, idempotently — `claim_order_for_payment:468` is keyed on `paymentAttemptId`, so a
retry either creates the one order or finds it.
Message: no "pay again" copy is reachable — the paid state is already recorded by the time this
step runs. New reference: **no**. Charged again: **no**.
Reconciliation: `record_capture_quarantine:699` records a capture that could not be placed, and
`resolve_order_for_provider_payment:579` re-resolves from the provider transaction id.
Key: `paymentAttemptId`.

#### `WIX_WRITEBACK_FAILED_AFTER_PAYMENT`
Record: canonical order is authoritative; `wixOrderId` absent or unverified.
Retry: yes — `wix_writeback` returns the existing `wixOrderId` with `created: false` from the claim
row (`:193-209`), so a retry cannot create a second Wix order.
Message: none. New reference: **no**. Charged again: **no**.
Reconciliation: documented and deliberate — a created Wix order whose total/currency disagrees with
the frozen quote **retains the provider order id and stops fulfilment**, and re-entry cannot create
another order. Ambiguous external creates are left **claimed for provider readback and staff
reconciliation** and are **not** automatically retried.
Key: the writeback claim row (`:239`).
Currently unreachable: `is_enabled()` is false (`:118-130`; both flags absent, site id pinned to
`c993128b-26be-41cd-9fcd-904abe23462f` at `:82`).

#### `INVOICE_SEND_FAILED_AFTER_PAYMENT`
Record: the invoice exists and stays deliverable.
Retry: yes — the engine **releases its claim when a send does not land**, so a retry re-claims
rather than being permanently blocked.
Message: none. New reference: **no**. Charged again: **no**.
Reconciliation: dispatch is async `Event` precisely "so a delivery failure must not fail the
webhook and make Razorpay retry a whole captured payment" (`:2462-2469`); the error log carries
the exception **type only** (`:2463-2467`).
Key: `INVOICEDELIVERY#<invoiceId>#whatsapp`.
**Must never mint a second invoice** — creation consumes a GST sequence
(`invoice-engine:829-852`), with a compensating decrement guarded by `lastSeq > :zero` (`:3342`).

#### `SERVICE_FLOW_INVITATION_FAILED`
Record: `postPaymentFlowSentAt` absent, so the invitation is still owed.
Retry: yes — claimed by `attribute_not_exists(postPaymentFlowSentAt)` (`:1714-1718`); a replay logs
`post_payment_flow_skipped … (idempotent)` (`:1721`).
Message: outside the 24-hour window the handler returns `AWAITING_CUSTOMER_MESSAGE` and does
**not** substitute a review template or send an unapproved Flow invitation.
New reference: **no**. Charged again: **no**.
Reconciliation: the invitation is re-sendable on the next inbound message.
Key: `postPaymentFlowSentAt`.

#### `FULFILMENT_FAILED` (service request row, Vault grant, workspace projection)
Record: paid state and canonical order stand.
Retry: yes — `paid_submit_request.prepare_and_send` requires
`store.activate(...)` to return `ACTIVATED` **or `ALREADY_ACTIVE`**, so a retry converges instead
of duplicating; the native finalisation step returns
`NATIVE_SERVICE_FINALIZED` / `NATIVE_SERVICE_FINALIZATION_PENDING` (`checkout:3080`) and
`prepare_and_send` refuses to proceed on anything but `NATIVE_SERVICE_FINALIZED`.
Message: none automatic. New reference: **no**. Charged again: **no**.
Reconciliation: `NATIVE_SERVICE_FINALIZATION_PENDING` is the recoverable marker; retry is
idempotent. Key: `paymentAttemptId` → `resolve_order_for_payment:607`.

#### Review invitation after fulfilment
Record: three independent claims. Retry: each idempotent **individually**.
Charged again: **no** (no money on this path).

> **GAP (F-2, MEDIUM, latent).** Three senders of `wecare_leave_review` with three **unrelated**
> claim namespaces: `razorpay-webhook:2467-2469` → `INVOICEDELIVERY#<invoiceId>#review`;
> `paid_submit_request.py:96` → `requestReviewStatus` on the ServiceRequests row;
> `paid_vault.py:87` → `vaultReviewStatus` on the same row. The webhook arm's only guard is
> `if contact and invoice_id:` and its comment states "**BOTH legs ask** … deliberate" — correct
> for the website/WhatsApp split it was written for, but it predates the native paths. So one
> native purchase sends the review template **twice**: once at capture, once after
> details/delivery. Contradicts `service-rollout/README.md` §9 ("a single review invitation") and
> `native-catalog-release-status.md` ("once-only `wecare_leave_review`"). Latent only because
> `WHATSAPP_CATALOG_SERVICES_ENABLED` is absent; a hard prerequisite for enabling it.
>
> Review-send failure posture is otherwise correct and deliberately asymmetric: the review claim
> **fails open toward not sending** (`:2628-2636` — "an unclaimed send is the duplicate this claim
> exists to prevent"), while the invoice claim **fails closed toward not sending**. Stated at
> `:2608-2615`: "a missing review request costs nothing, a duplicate GST invoice is a compliance
> artifact."

---

## 3. Invariant table

| Invariant | Enforced at | Why there |
|---|---|---|
| Payments fail closed | `payment_readiness.py:68,80-96,168-169` — `BLOCKING_STATES` **enumerated**, not derived from `!= PAYMENT_READY` | A new state cannot become permissive by being added |
| An unreachable provider is never "fine" | `payment_readiness.py:228` → `META_UNAVAILABLE` | Indistinguishable from misconfigured, so treated as blocking |
| "We did not compare" is a refusal | `payment_readiness.py:244-248` → `CONFIGURATION_UNVERIFIED` | An empty expected MID must not skip the check |
| The provider MID is compared, never adopted | `payment_readiness.py:39,312-316` | Prevents silently paying a different merchant |
| Webhook authenticity | `razorpay-webhook:322-340` | `compare_digest`; fail closed on missing secret *or* missing header; mismatch log carries only `bodyLen` |
| One reference per intent | `order_keys:352,399` | Before any send, so a resend cannot create a second charge |
| One order per payment | `order_keys:468` | Keyed on `paymentAttemptId` |
| Paid is terminal and monotonic | `razorpay-webhook:2144`, `:2027-2031` | A replay or out-of-order delivery cannot settle twice or downgrade |
| One invoice per payment | `invoice-engine:849-852` | Claim **before** numbering, because numbering consumes a GST sequence |
| One delivery per channel | `claim_invoice_delivery` | Fails closed; a throttle raises rather than reading as "already delivered" |
| Phone alone never grants ownership | **`catalog_services.py:94` — currently VIOLATED (F-3)** | Selection owns the entitlement decision because money moves there; delivery only re-derives |
| Catalog sync can never delete | `meta_catalog_sync.py:558-572` | A customer's in-flight cart holds a `product_retailer_id`; a missing item fails at checkout, not at browse |
| No price is ever typed twice | `src/config/services.ts` declares **no** price; Wix is the authority | A stale constant becomes a wrong charge |
| Amounts are integer paise via `Decimal` | `wix_ecom.to_paise:145-157`, `meta_catalog_sync:275-298` | **No float anywhere.** A non-exact paise value raises `AmountNotWhole` rather than rounding |

**Float check — explicit.** `to_paise` uses `Decimal(str(value))` and raises on a value that is not
a whole number of paise; `_slim_product` keeps the Wix price as the **decimal string** Wix sent
("No coercion to a float, here or anywhere"); `_variant_price_paise` refuses a missing variant
price rather than falling back to a product-level minimum (`require_variant_price=True` on the live
path), because `WECARE.DIGITAL Services` spans 49–350 and the product minimum would be wrong for
most variants. Expected service prices in paise: submit-request 9900, request-amendment 9900,
drop-docs 35000, vault 4900. Shipments and Leave Review are utility entries with **no price**.

---

## 4. Consolidated GAP list

| # | Gap | Severity | Reachable today |
|---|---|---|---|
| G1 | Vault selection admits `ownerCustomerId == None` on a phone match (`catalog_services.py:94`) | MEDIUM-HIGH | No — native flag absent |
| G2 | Review invitation duplicated across webhook and native paths (`razorpay-webhook:2467` vs `paid_submit_request.py:96` / `paid_vault.py:87`) | MEDIUM | No — native flag absent |
| G3 | Conditional-failure detection by exception substring (6 sites) | LOW | **Yes** |
| G4 | No distinct `PAYMENT_CANCELLED` state or copy | LOW | Yes |
| G5 | No server-side expiry sweep; no "payment request expired" message | LOW | Yes |
| G6 | No re-send and no customer copy on `MESSAGE_SEND_FAILED` | LOW | Yes |
| G7 | `list_users` Filter built by string concat without the UUID guard at 3 of 4 sites | LOW | Yes |

None of G3–G7 can cause a double charge. G1 and G2 are the two that must close before the native
flag is enabled.
