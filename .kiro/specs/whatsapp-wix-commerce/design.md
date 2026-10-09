# Design — WhatsApp + Wix Headless conversational commerce

## Owner architecture decision — 2026-10-01

Use the existing self-managed Next.js/AWS headless application. WhatsApp/Razorpay collects payment externally; create the internal order and Wix order only after authoritative verification, then record the external payment without charging again. Velo and external PSP onboarding are not dependencies. Retain admin-only Cognito and WhatsApp-only receipts. Historical provider configuration claims below require live verification. See `docs/execution/headless-checkout-20261001.md` for the current partial audit and implementation gaps.

> **Superseded 2026-10-01 (website-only ruling).** Payment is collected on the website via Razorpay Standard Checkout and the receipt is a private, authenticated downloadable document on the website; in-WhatsApp payment is removed from the active purchase flow. See `requirements.md` for the authoritative wording.
>
> **Scope of "removed", clarified 2026-10-09.** It removes in-WhatsApp payment from the **CART**
> purchase flow. Native in-WhatsApp payment is retained, template-only and
> provider-readiness-gated, for **invoice collection** and **service purchases**. See the Phase 9
> re-scope note in [`tasks.md`](tasks.md) for the task-level consequences; this pointer exists so
> the two files cannot drift again.

Payment safety before wiring: reject unbound provider payments; enforce customer ownership before duplicate shortcuts; accept exact DynamoDB Decimal integers but no float coercion; pending/unknown is never retryable; prevent competing number assignments and repeating ambiguous Wix writes.


Derived from [`requirements.md`](requirements.md) and the Phase 0 findings in
[`docs/compatibility.md`](../../../docs/compatibility.md). R0 (Wix credential) is now
**closed** — the admin key is stored and catalog reads are live-verified — so the Wix
contracts below can be exercised. Cart/checkout *writes* remain unverified against the live
site and are gated behind a contract test (Phase 8 / Phase 11) before any order is created.

## Decision record

Six decisions where this design deliberately departs from the prompt.

### D1 — Extend the Python fleet; do not introduce a Node.js API

The prompt specifies `nodejs24.x` + CDK v2 + TypeScript + Powertools for TypeScript. That
runtime is GA and would be right for a greenfield build. It is wrong here.

The fleet is 64 of 64 `python3.12`, deployed by `scripts/deploy_all_lambdas.py`, which
validates that every top-level import resolves inside the package or an attached layer, and
then publishes a version and moves the `live` alias. A Node.js function would need a second
packaging path, a second dependency tree, a second Powertools, and would sit outside the
import validator and the alias publisher — the two mechanisms that currently stop broken
code and stale code reaching production.

The payment path also already exists in Python: `_build_payment_settings`, the
`order_details` and checkout-template senders, `order_status` confirmation, and the payment
lookup call. Reimplementing it in TypeScript would mean two implementations of Meta's
payment payload, and the second one would be the untested one.

**Decision.** New handlers are `python3.12`, using the existing shared layer, deployer and
alias model. Powertools for Python where it adds value. `nodejs24.x` is recorded in the
compatibility manifest as *available and rejected, with reason*, so the choice is revisited
deliberately rather than forgotten.

**Cost accepted.** Loses the prompt's TypeScript-everywhere symmetry and Zod. Zod is
replaced by explicit schema validation in the existing `shared/lambda_utils/validation.py`.

### D2 — OAuth `client_credentials`, with the API key as a migration fallback

Wix documents client credentials as the recommended way to authorize headless admin
operations. The current code uses a permanent admin API key sent raw in `Authorization`.

**Decision.** `wixAuth` mints a short-lived access token from `client_id` + `client_secret`,
caches it in the execution environment, and refreshes on a safety margin before expiry. The
secret holds both fields so the migration can store and verify the new mechanism before the
API key is removed. `scripts/set_wix_credential.py` already supports both and preserves
whichever field it was not given.

Token caching is per execution environment, not per module import — same reasoning as the
secret loader. A 401 from Wix invalidates the cached token and triggers exactly one refresh
and retry, so a mid-lifetime revocation self-heals instead of failing every request until
the sandbox recycles.

### D3 — Keep the homegrown invoice engine; use Wix receipts only if the site offers them

The prompt asks for Wix Invoices v4 / Receipts v1. This repo has `payments/invoice-engine`
with `Invoice`, `InvoiceItem`, `InvoiceAsset`, `InvoiceDeliveryLog` and `InvoiceSequence` —
including a per-financial-year statutory sequence, GSTIN, HSN codes and GST rates. Wix
Invoices does not model Indian GST compliance, and a standalone Wix invoice can carry its
own payment flow, which is precisely the duplicate-payable-order hazard the prompt warns
about in §17.

**Decision.** The billing document is produced by the existing invoice engine and is the
system of record for statutory numbering. `billingDocumentService` first checks whether Wix
produced an **order-linked** document and reuses it for reconciliation display if so. No
standalone Wix invoice is ever created. Whether Wix Receipts is available to this site is
`BLOCKED` pending R0 and does not change the decision.

### D4 — Backend-managed cart keyed to phone, on Wix Cart V2, with no Wix checkout page

A WhatsApp customer has no browser session, so Wix's visitor-scoped `currentCart` has no
carrier. Combined with the frontend being a static export — no middleware, no server — there
is nowhere to hold a visitor token client-side safely.

**Decision.** The cart is owned by the backend and keyed on the customer's phone. Wix cart
id and revision are stored server-side; the customer never holds a Wix identifier.

**This is an in-chat flow, so the Wix-hosted checkout page is never used.** The architecture
is `WhatsApp ⇄ backend ⇄ Wix Ecom (headless) ⇄ Meta payment gateway`: the backend builds the
cart in Wix and reads the authoritative total, the customer pays inside WhatsApp via Meta
(Razorpay underneath), and Wix produces the **order** only afterwards, recorded as an
externally collected payment. `checkoutRedirect` being reachable (probe, 2026-10-01) is
informational; this design does not redirect a customer to Wix to pay.

**Cart V2, confirmed live 2026-10-01.** The earlier revision of this design was written
against Wix **Cart V1 + Checkout V1**, which Wix will remove on **2027-02-01**. Cart V2
unifies cart and checkout into one entity: there is **no checkout step and no
`wixCheckoutId`** — the cart id identifies the unified cart; `purchaseFlowId` is the stable
correlation id across retries, and the external order is linked only after verified payment. See D7 for the
mechanics and the evidence. The consequence for this design is that the V1 `CHECKOUT#`
mapping row is removed (see the data model): before payment the join key is the Wix **cart
id**; after verified external order creation it is the Wix **orderId**. PaymentAttempt and provider-payment claims, not cart ID alone, enforce one funded order.

### D7 — Wix Cart V2 mechanics (supersedes the V1 cart/checkout assumptions)

Verified against the live site `fcd82f0c-…` on 2026-10-01 via
`scripts/probe_wix_capabilities.py` (public headless client id, anonymous visitor token, no
secret): Catalog **V3**, `wixEcommerce` **INSTALLED**, and the V2 route resolves
(`GET /ecom/v2/carts/{nonexistent}` → `404 CART_NOT_FOUND`, a semantic answer, not a
route/`501 UNIMPLEMENTED` error). `wixInvoices` is **NOT AVAILABLE**, which is consistent
with D3.

The purchase flow the backend drives, all under `/ecom/v2/carts`:

```
Create Cart            catalogItems[].catalogReference {appId, catalogItemId, options{variantId,…}}
Add / Update / Remove Line Items       (Update uses LineItemUpdate + QuantityUpdate)
Calculate Cart         → summary.priceSummary / taxSummary / paymentSummary / violations
                         and a PRICE VERIFICATION TOKEN
                       (Estimate Cart is the lightweight, flag-controlled preview; Calculate
                        is the full, checkout-level calculation used to build a payment)
Place Order            NOT USED: can enter Wix payment collection
Mark Cart As Completed for an externally-created order (our case), when Place Order is not used
```

Load-bearing V2 facts, each of which shapes a requirement below:

- **Totals are not stored on the cart.** They come from `Calculate Cart` → `summary`.
  R6's authoritative total is `summary.priceSummary` read at build time, never a cached price.
- **The price verification token** is stored privately with the immutable calculation snapshot.
  Wix validates this token in `Place Order`, which this external-payment path does not call.
  Do not claim it provides price locking for `Create Order`; compare the paid attempt snapshot
  and fresh cart calculation explicitly, and send mismatches to paid-but-blocked recovery.
- **`summary.violations`** (severity `ERROR` / `WARNING`) is the pre-order validation surface
  — `OUT_OF_STOCK`, `REMOVED_FROM_CATALOG`. An `ERROR` violation must block, which is R8's
  stock-gone case expressed in the V2 contract.
- **Currency** is `businessInfo.currencyCode` (the unit of every `amount`). R6.4 compares it
  explicitly against `INR`; the customer/payment currency fields are not trusted in its place.
- **`catalogReference`** for Catalog V3 is `{appId, catalogItemId, options:{variantId, …}}`;
  `variantId` is always included. This is the join between our catalog reads and the cart.

**How order creation is recorded.** After authoritative payment verification, use Wix
`Create Order` followed by `Add Payments` to record the captured payment. The writeback
allowlist excludes Cart V2 `Place Order` and all collection endpoints. Completion with
`Mark Cart As Completed`, order payload mapping, and inventory behavior still require the
Phase 11 contract; neither the live cart probe nor a price token proves those behaviors.
No order write is enabled by this change. The gates require the R0.10 confirmed site ID,
`WIX_WRITEBACK_ENABLED`, `WIX_ECOM_WRITE_CONFIRMED`, and the tested release contract
`WIX_CART_V2_WRITE_CONTRACT=cart-v2-external-v1`. These are deployment attestations, not
customer-controlled request fields.

**Implementation evidence (2026-10-01).** `cart_v2.py` uses catalog-only create/add/update/
remove/get/calculate calls. `customer_cart.py` stores `CUSTOMERCART#<E.164 phone>` rows in
existing WixOrderIds, keyed by physical `orderId`, with customer ID ownership checks,
conditional locks and durable `CARTOP#<phone digest>#<requestId>` replay records. Logical
cart expiry is 30 days; quote expiry is 5 minutes. Never enable table-wide TTL: immutable
order reservations share this table. Unknown remote outcomes retain their lock until
readback; known calculation violations allow the customer to correct the cart. The
customer route is GET/POST `/wix-store/cart`, authenticated through the customer pool and
inert unless `WIX_CART_V2_ENABLED=true`.

An isolated demo cart on the confirmed site was created, populated with one catalog variant,
read and calculated. The redacted response is `tests/fixtures/wix_cart_v2_live_demo.json`.
It returned INR 24999.00 and blocking MISSING_DELIVERY_ADDRESS / MISSING_DELIVERY_METHOD
violations. No order, payment or customer message was created. The fixture proves populated
Cart V2 shapes; it is not evidence of a successful payable checkout.

### D5 — Reuse the existing order number format, add the missing uniqueness reservation

`_generate_wd_order_number` produces `WD-ORD - <UUID8> - <DD-MM-YYYY> - <HH:MM:SS> - IST`,
and the admin UI, `Order.shortId`, dropdown formatting and `docs/order-centric-architecture.md`
all depend on it. Replacing it with `WC-<DATE>-<ULID>` would break live surfaces for no
correctness gain — a UUID8 plus a reservation is as collision-safe as a ULID plus a
reservation.

What the current implementation lacks is the reservation itself. `_get_or_create_wd_order_number`
does read-then-write, and its exception path returns an **unstored** number, which is the
one case where a duplicate is most likely. That is the defect to fix, not the format.

**Decision.** Keep the format. Add the `ORDERNO#<number> / UNIQUE` conditional reservation,
and make the failure path fail closed rather than return an unreserved number.

### D6 — One HTTP API, existing routes extended

One HTTP API exists (`zllr9lrg7j`). New routes are added to it rather than standing up a
second API, so authorizer posture, WAF association and custom domain remain single-sourced.

---

## Architecture

```
WhatsApp  ──►  HTTP API zllr9lrg7j  ──►  whatsappWebhook (fast ACK)
                                              │  verify signature (raw body, HMAC-SHA256,
                                              │  timing-safe) → validate → claim
                                              │  idempotency → enqueue → 200
                                              ▼
                            ┌────────── SQS message queue ──────────┐
                            │                                       │
                            ▼                                       ▼
                    messageProcessor                        SQS payment queue
                            │                                       │
              Wix catalog / cart / checkout                         ▼
              WhatsApp sends                          paymentReconciliation
              DynamoDB state                                        │
                                                    ┌───────────────┴───────────────┐
                                                    │ compare currency + amount      │
                                                    │ resolve reference_id → order   │
                                                    │ create/resolve Wix order ONCE  │
                                                    │ record external payment        │
                                                    │ await Wix PAID reconciliation  │
                                                    │ generate billing document      │
                                                    │ send confirmation              │
                                                    └───────────────┬───────────────┘
                                                                    ▼
                                                        DLQ on exhausted retries
```

Fulfillment runs on its own path: a Wix fulfillment event updates state, appends a timeline
event, refreshes the tracking page and optionally sends a WhatsApp `order_status` update.

**Why the split queue.** Message traffic is chatty and cheap to reprocess. Payment traffic
is rare and expensive to get wrong. Separate queues let payment reconciliation have its own
concurrency limit, its own retry policy, its own DLQ and its own alarm, and stop a catalog
browsing spike from delaying a capture.

---

## Data model

Single-table additions alongside the existing `Order`, `Payment`, `WixOrdersCache`,
`WixOrderId`, `WebhookDedup` and invoice tables. The existing tables are not restructured —
`Order` is already the order-centric record and is read by live admin UI.

| PK | SK | Purpose |
|---|---|---|
| `ORDER#<commerceOrderId>` | `METADATA` | order record and current state |
| `ORDER#<commerceOrderId>` | `EVENT#<ts>#<eventId>` | append-only timeline |
| `ORDERNO#<commerceOrderNumber>` | `UNIQUE` | **uniqueness reservation** |
| `REFERENCE#<metaReferenceId>` | `ORDER` | Meta reference → order |
| `WIXCART#<wixCartId>` | `ORDER` | Correlation to the verified-paid order; uniqueness is enforced by PaymentAttempt/provider claims |
| `WIXORDER#<wixOrderId>` | `ORDER` | Wix order → order, prevents a second Wix order |
| `PAYMENT#<providerTransactionId>` | `METADATA` | provider transaction uniqueness |
| `TRACKING#<tokenHash>` | `ORDER` | tracking token → order |
| `CUSTOMERCART#<phone>` | physical `orderId` key | Active backend cart; logical expiry, customer ownership, Wix cart ID/revision, private calculation snapshot |
| `CARTOP#<phone digest>#<requestId>` | physical `orderId` key | Durable command deduplication; never replay an ambiguous Wix write |
| `IDEMPOTENCY#<eventId>` | `EVENT` | webhook dedupe, with TTL |

Every mapping row above exists so that a duplicate inbound event resolves to an existing
order instead of creating one. GSIs are added only for admin queries that exist: by
creation date, by payment status, by reconciliation status, by fulfillment status.

---

## Identifier algorithm

**Revised 2026-09-30 for the order-after-payment rule (R2).** Nothing below mints an order
identifier while a payment is being requested.

### Before payment

```
paymentAttemptId = UUIDv7                       local, free, no storage
reference_id     = WD-PAY- + 14 CSPRNG symbols  validated against Meta's 35-char charset
reserve          = PutItem  PAYREF#<reference_id>  ->  paymentAttemptId
                   ConditionExpression: attribute_not_exists(...)
```

The `PAYREF#` row deliberately holds no order id and no order number. That is the rule expressed
in the data rather than in a comment.

### After the provider confirms capture

```
orderId = UUIDv7                                minted FIRST, locally, costs nothing

claim   = PutItem  PROVIDERPAYMENT#<txnId>   -> orderId     provider uniqueness, claimed first
          PutItem  PAYMENTATTEMPT#<attempt>  -> orderId     the idempotency anchor
          both ConditionExpression: attribute_not_exists(...)

          lost either claim  ->  read the winner's orderId, return it, create nothing

reserve = PutItem  ORDERNO#<12-char candidate>  ConditionExpression: attribute_not_exists(...)
          ConditionalCheckFailed  ->  regenerate, retry, bounded attempts
          any other error         ->  FAIL CLOSED, no number returned
          exhausted attempts      ->  FAIL CLOSED, alarm

record  = UpdateItem PAYMENTATTEMPT#<attempt>  SET orderNumber
```

**Why `orderId` is minted before the claim.** It costs nothing and touches no storage, so it can
be used *as* the claim value. That gets the ordering right: the claim decides who may create the
order, and only the winner then reserves a number — so a loser never burns one. Reserving first
and claiming second would consume a number per concurrent worker.

**Why the number is recorded separately.** It does not exist at claim time. The gap between
claiming and reserving is therefore real, and re-entry is what closes it: `PAYMENTATTEMPT#` with
no `orderNumber` means the previous run died in between, so the caller reserves one and records
it. That is recoverable; a number handed out before it was committed is not.

Idempotent re-entry is a lookup, not a generation. A payment event carrying an unknown
`reference_id` resolves to nothing, and the correct response is to fail the event for staff
attention — never to create an order from a payment event.

---

## State machine

Two machines, not one, because payment state and order state answer different questions and
conflating them is what allowed a pre-payment order to exist at all.

### Payment attempt

```
CREATED → PAYMENT_CONFIG_CHECK → PAYMENT_REQUEST_BUILDING
        → PAYMENT_REQUEST_SENT → PAYMENT_PENDING

then exactly one of:
   PAYMENT_PAID · PAYMENT_FAILED · PAYMENT_CANCELLED · PAYMENT_EXPIRED
```

Only `PAYMENT_PAID` may proceed, and only after an independent provider readback — a webhook is a
trigger to verify, not proof. The three terminal failures create nothing and stay in payment
history.

### Order — reachable only from PAYMENT_PAID

```
ORDER_ID_RESERVING → ORDER_CREATING → ORDER_CREATED
   → WIX_ORDER_CREATING → WIX_ORDER_CREATED
   → WIX_PAYMENT_RECORDING → WIX_PAYMENT_RECORDED
   → RECEIPT_GENERATING → RECEIPT_READY
   → WHATSAPP_CONFIRMATION_SENDING → CONFIRMED
   → FULFILLMENT_PENDING → SHIPPED → DELIVERED

side exits: REFUNDED · RECONCILIATION_FAILED
```

Note what is absent from the order machine: there is no `CANCELLED`, because an order that could
be cancelled before payment would be an order that existed before payment. A customer abandoning
checkout leaves a payment attempt, not a cancelled order.

Every failure after capture is recoverable and none of them may ask the customer to pay again.

Transitions are applied with `ConditionExpression` on the current state, so a concurrent or
replayed worker attempting the same transition fails harmlessly rather than double-applying
its side effect. `RECONCILIATION_FAILED` is recoverable: a staff retry re-enters at the
last confirmed state, never at the beginning.

**Status vocabulary must be unified.** `payment_status.py` records that `InvoicesTable` and
`OrderTable` say `paid` where `PaymentsTable` says `captured`, and that `PaymentsTable`
currently holds zero rows. A reconciliation built on top of two vocabularies will produce
disagreeing dashboards. One vocabulary is chosen and the mapping to each legacy table is
explicit and single-sourced.

---

## Reconciliation

Ordered, and the order is the design:

1. Verify Meta signature on the raw body.
2. Claim the idempotency key. An already-claimed key returns the existing outcome.
3. Resolve `reference_id` → order. No mapping means no order; do not create one from a
   payment event.
4. Load the authoritative total from Wix **Calculate Cart** (`summary.priceSummary`) for the
   bound cart. Compare currency (`businessInfo.currencyCode`), then amount in minor units,
   then customer. Any mismatch fails closed. (Cart V2: totals are not stored on the cart.)
5. Create or resolve the Wix order **once**, guarded by `WIXORDER#<id>`, from the bound Wix
   cart via `Create Order`; record the external payment and complete the cart only after
   the Phase 11 mapping/inventory contract is verified. Never call `Place Order`.
6. Record the externally collected payment against that order. This records; it does not
   collect. No Wix V2 call that could charge again is reachable from this path (asserted by
   the Phase 11 test enumerating every reachable call).
7. Wait for Wix to reconcile payment state. Poll with backoff; do not assume.
8. Generate the billing document, guarded so exactly one exists.
9. Send the customer confirmation, guarded against duplicate customer-visible messages.

Steps 5-9 each carry their own guard, so a retry that failed at step 7 does not redo 5 or 6.

**Warm-sandbox caveat.** A function caches its secrets on first use, so replacing a value in
Secrets Manager does not change what a warm sandbox serves. Publishing a new version has no
warm environments; `scripts/refresh_secret_consumers.py` exists for exactly this and must be
run after any credential change, with `scripts/check_secrets_live.py` confirming the provider
accepts the new value.

---

## Billing document flow

```
payment confirmed AND Wix reconciled
        │
        ▼
does Wix hold an ORDER-LINKED document?  ── yes ──► record its ids, reuse for display
        │ no
        ▼
invoice-engine generates the statutory document (per-FY sequence, GSTIN, HSN)
        │
        ▼
persist ids + status ──► deliver ──► record sentAt / viewedAt
```

A standalone Wix invoice is never created, because it can carry its own payment flow and
would risk a second payable order. Delivery never exposes a permanent Wix URL: the document
is proxied through an authenticated API, or copied to a private S3 object and served by a
short-lived signed URL.

---

## Tracking security

The frontend is a static export, so it has no server and cannot validate anything. All token
handling is in Lambda.

- Token is 256 bits from a CSPRNG. `secrets` / `os.urandom`, never `random`.
- Only a hash is stored, under `TRACKING#<tokenHash>`. The plaintext token exists only in
  the link sent to the customer.
- An invalid token and a token for a non-existent order return the same response, so the
  endpoint is not an order-existence oracle.
- The order number alone grants nothing.

---

## Error matrix

| Condition | Response | Retry | Customer sees | Alarm |
|---|---|---|---|---|
| Bad webhook signature | reject, do not enqueue | no | nothing | yes |
| Duplicate webhook | ACK, no side effect | no | nothing | metric only |
| Amount or currency mismatch | fail closed | no | payment under review | yes |
| Wix unavailable pre-payment | fail request | yes | try again shortly | on sustained |
| Wix unavailable post-capture | `RECONCILIATION_FAILED`, order preserved | yes, staff-retryable | payment received, order confirming | yes |
| Wix order already exists | resolve, continue | n/a | nothing unusual | metric only |
| Stock gone after capture | fail closed, refund path | no | staff contact + refund | yes |
| Billing document fails | order stays confirmed | yes | confirmation without document link | yes |
| Confirmation send fails | retry, guarded | yes | delayed message | on exhaustion |
| DLQ non-empty | — | staff | nothing | yes |

The distinction that matters: a failure **before** capture may fail the customer's request;
a failure **after** capture may never lose the order and may never charge again.

---

## IAM

Per-function least privilege, no shared role:

- `whatsappWebhook` — `sqs:SendMessage` on its two queues, conditional `dynamodb:PutItem`
  on the idempotency table, read on the Meta app-secret secret. No Wix access at all.
- `messageProcessor` — read on the Wix credential secret, read/write on cart and order
  items, `lambda:InvokeFunction` on the sender.
- `paymentReconciliation` — read on Wix and Meta secrets, read/write on order, payment,
  timeline and mapping items, write to the billing bucket.
- Admin API — read on order/payment/timeline; write only through the named retry
  operations.

Bucket policies distinguish `arn:...:bucket` from `arn:...:bucket/*`. Conditional
`aws:SourceAccount` / `aws:SourceArn` on any service trust policy created.

---

## Retry strategy

| Layer | Policy |
|---|---|
| SQS message queue | 3 receives, exponential backoff, then DLQ |
| SQS payment queue | 5 receives, longer visibility timeout, then DLQ with alarm |
| Wix API | bounded retry on 5xx and 429; never on 4xx except a single 401 token refresh |
| Meta API | honour the documented retry flag per error code; `131056` pair rate limit backs off 4^n |
| Wix payment-state poll | bounded backoff, then `RECONCILIATION_FAILED` rather than indefinite wait |
| Staff retry | idempotent, re-enters at last confirmed state |

Batch processing reports partial failures so one bad message does not fail its whole batch.

---

## Open questions

Several of these were answered by the live capability probe on 2026-10-01
(`scripts/probe_wix_capabilities.py`, public client id, no secret); the answers are recorded
here rather than deleted, so the reasoning survives.

1. ~~Is the site's Stores catalog actually V3?~~ **Answered: CATALOG_V3** (stores/v1 → `501
   UNIMPLEMENTED`; stores/v3 responds).
2. Are Wix Invoices/Receipts available? **Partly answered: `wixInvoices` NOT AVAILABLE**
   (`invoices/v2` → 404), so the billing document is self-issued (D3). Whether Wix produces
   an order-linked receipt for an externally collected payment is confirmable only with the
   admin scope at order-creation time (Phase 11).
3. Which inventory adjustment does V2 order creation perform, and does it require a manual
   decrement? R8 cannot be closed until this is measured against the live contract (Phase 11).
4. ~~Does the Wix cart/checkout contract match the shapes assumed here?~~ **Answered: use
   Cart V2** (`/ecom/v2/carts` resolves live; V1 removed 2027-02-01). See D7. The exact
   `Calculate Cart` response is now covered by a redacted live demo fixture. Create Order,
   Add Payments and cart completion still need the Phase 11 contract before any order write.
5. Is `+919330994400` connected? **Answered: yes** — `docs/compatibility.md` re-measured it
   healthy (quality GREEN, WABA `APPROVED`) on 2026-09-30; the `inbound-whatsapp-handler`
   "disconnected" comment was stale and is corrected.
