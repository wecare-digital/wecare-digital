> **SUPERSEDED.** This draft is retained as prior art only. The authoritative FINAL plan is [`whatsapp-commerce-FINAL-plan.md`](./whatsapp-commerce-FINAL-plan.md).

# WhatsApp Commerce Consolidation: Function Audit and Two-Track Implementation Plan

Status: PLAN ONLY (no code changes in this pass). Owner review required before any implementation is delegated. This document REPLACES the prior plan and resolves its open A-vs-B question into two concrete tracks per the owner's finalized decisions.

Repository: `wecare-digital/wecare-digital`
Working branch: `stack` (base). All implementation work MUST land on a dedicated feature branch and merge via PR. Do NOT commit to `stack`.

## 0. Scope, decisions, and security

### 0.1 Finalized owner decisions (these SUPERSEDE the prior plan's open questions)

1. **WABA1-ONLY for payments is CONFIRMED.** Do NOT re-enable WABA2 (`2513394156072604`) as a payment sender, even though the owner's dashboard shows WABA2 with `WECAREDIGITAL` + `WECAREUPI` active. `PAYMENT_SENDERS` stays `{WABA1}`. This dashboard-vs-code discrepancy is a KNOWN, BENIGN condition: the dashboard reflects what Meta has provisioned, the code reflects the owner's deliberate routing choice. Verified pin: `tests/test_transaction_whatsapp_template_allowlist.py::test_otp_manifest_has_only_waba1_sender` asserts `OTP_WABA_MAP` is exactly `{WABA1}` with `phone_number_id == 1016149501586345` and `template_name == wecare_otp`.
2. **SCOPE = FUNCTION consolidation only.** NOT table consolidation. NOT payment-flow BEHAVIOR changes, with the single exception of the fulfilment-contract restoration in Track B. The plan does NOT propose merging tables. Tables stay DECOMPOSED (one function does not equal one table). `CommerceKeys` MUST stay its own idempotency table.
3. **Architecture resolved into TWO tracks.** The prior plan's Option A (new Lambda) vs Option B (shared module) question is settled: it is not one or the other, it is both, applied to different problems. Track A does WhatsApp function consolidation (merges, shared-module extractions, internal modularization). Track B creates ONE new `wecare-commerce` Lambda that absorbs exactly three commerce Lambdas. Track A's low-risk work sequences FIRST and feeds Track B.

### 0.2 Security note (read first, non-negotiable)

- The owner pasted a LIVE Razorpay Key Id and Key Secret into the task. They are deliberately NOT reproduced anywhere in this document or any file. **Because the live Key Secret was pasted into a chat, the owner MUST rotate it** in the Razorpay dashboard and update `wecare/razorpay/api` in AWS Secrets Manager. Treat the pasted secret as compromised.
- All Razorpay secrets come from AWS Secrets Manager (`wecare/razorpay/api` for API keys, `wecare/razorpay-webhook` for the webhook secret); Meta tokens come from Secrets Manager. The consolidation MUST preserve this. No secret value may ever be written to code, config, tests, or docs.
- Only NON-SECRET identifiers appear below: Account/MID `acc_TTFSyolquKEZEy`, WABA1 `2094615664435155` (phone +919330994400), WABA2 `2513394156072604`, payment config names `WECAREDIGITAL` (Razorpay PG) and `WECAREUPI` (UPI VPA `wecaredigitalbh511413.rzp@rxairtel`), MCC 7392, purpose code 03, Legal name WECARE.DIGITAL BHARATWORKS, Trade name WECARE.DIGITAL, PAN AAFFW7196L, GSTIN 19AAFFW7196L1Z8.

### 0.3 The core finding

Do NOT merge everything into one WhatsApp Lambda. Several functions are separate because they have genuinely different trust boundaries (inbound vs outbound, public signed ingress vs reactive worker, auth vs payment, control-plane admin vs data-plane send, intent vs authoritative settlement). The audit found 4 strong consolidation opportunities and 3 areas where logic should move into shared modules rather than merging Lambdas (Track A), plus one precise 3-into-1 commerce merge (Track B).

---

# TRACK A — WhatsApp function consolidation

All line numbers and facts below were verified by reading the files on branch `stack`.

## A0. Consolidation audit table

| Function / area | Decision | Why |
|---|---|---|
| `whatsapp-template-management` + `whatsapp-templates` | **MERGE** | Heavy duplication: Meta credentials, `_appsecret_proof`, WABA-ID conversion, WABA to phone resolution, Graph request code, template CRUD, media upload, library/carousel |
| `core/service-api` + `whatsapp-business-api/service_api.py` | **MERGE implementation** | Two REST implementations expose the same service/order/appointment/review concepts and must be kept identical by hand |
| Secure-files WhatsApp payment builder | **RETIRE payment logic** | Duplicates checkout/payment construction; should call canonical checkout instead. Already gated off |
| Legacy order-status send path | **CONSOLIDATE** | Invoice-template fulfilment plus legacy `isOrderStatus` envelope; should become one Meta `order_status` implementation |
| `whatsapp-business-api` | **SPLIT INTERNALLY** | Too many unrelated responsibilities, but not into many new Lambdas |
| Flow completion writers | **CONSOLIDATE into shared writer** | Multiple Flow modules historically wrote/projection-copied submissions |
| OTP normalization/sending helpers | **SHARE code, KEEP Lambdas separate** | Registration and Cognito auth have different invocation/trust models |
| inbound + outbound WhatsApp | **KEEP separate** | Receive/process vs send/provider boundary |
| webhook ingress/calling + inbound worker | **KEEP separate** | Public signed Meta ingress vs reactive processing |
| checkout + Razorpay webhook | **KEEP separate** | Payment intent creation vs authoritative provider settlement |
| invoice-engine + checkout | **KEEP separate** | Pricing/payment intent vs legal GST invoicing |
| WABA management + business API | **Mostly KEEP separate** | Control-plane account management deserves isolation |

## A1. MERGE the two template Lambdas (safest first whole-Lambda removal)

Both of these independently contain Meta token/secret loading, `_appsecret_proof`, WABA-ID conversion, WABA to phone-number resolution, Meta Graph request code, template CRUD, template media support, and library/carousel support:

- `amplify/functions/messaging/whatsapp-template-management/handler.py` — VERIFIED: `_appsecret_proof` (L98), `AWS_TO_META_WABA` map (L77-79), `META_GRAPH_URL` (L37), `DEFAULT_META_WABA_ID = '2094615664435155'` (WABA1, L81).
- `amplify/functions/messaging/whatsapp-templates/handler.py` — VERIFIED: `_appsecret_proof` (L70), `AWS_TO_META_WABA` (L35), `META_GRAPH_URL` (L31), template CRUD + `library` / `carousel` / `carousel-media` / `media` routing (L421-434).

**Target:** keep ONE physical Lambda `wecare-whatsapp-template-management`, and split its source into modules:

```
whatsapp-template-management/
    handler.py
    templates.py      # template CRUD
    validation.py     # template validation
    library.py        # template library / from-library
    carousel.py       # carousel + carousel-media
    media.py          # template media upload / headers
```

Then retire the physical Lambda `wecare-whatsapp-templates`.

**Google Places proxy must NOT go into template management.** The one special thing in `whatsapp-templates` is its Google Places proxy — VERIFIED `_get_gmaps_key` (L157), `_places_autocomplete` (L297), `_place_details` (L334), `_legacy_shape_from_place_details` (L258). Move that OUT into a location/address service. Do NOT put Places into the template management Lambda. **OPEN RISK (owner input needed):** exactly which service owns the location/address proxy (new small Lambda vs an existing address/contact service). See section "Open risks".

This is the safest FIRST whole-Lambda removal because it removes a duplicate without touching the money path.

## A2. MERGE the duplicated Service API implementation

Two implementations exist:

- `amplify/functions/core/service-api/handler.py` — VERIFIED it exists (49,429 bytes). This is the ONE implementation.
- `amplify/functions/messaging/whatsapp-business-api/service_api.py` — VERIFIED it exists (34,968 bytes). This maintains a duplicate.

The service surface includes `/orders`, `/service/submit`, `/service/amend`, `/service/track`, `/documents`, `/faq`, `/appointments`, `/rx-slots`, `/enterprise-assist`, `/reviews`. Keeping two handlers aligned by hand is a documented drift risk.

**Target:** keep `wecare-service-api` as the domain service. WhatsApp Flows invoke the shared service-domain module / `wecare-service-api` instead of `whatsapp-business-api` maintaining a second REST implementation.

```
WhatsApp Flow
      ↓
shared service-domain module / wecare-service-api   (one implementation)
```

Removes a documented drift risk.

## A3. RETIRE the secure-files payment builder (route through checkout)

`amplify/functions/core/secure-files/whatsapp_delivery.py` contains its own payment builder — VERIFIED `reference_id()` (L126), `send_payment_request(...)` (L136), `order_details` construction (L156) whose comment (L23) states the `order_details` shape was COPIED from `payments/invoice-engine`. It is already gated off (`SECURE_FILES_PAYMENT_ENABLED` is `"false"`, VERIFIED comment L79 and `config/lambda-env-manifest.json` L399).

**Target:** route purchases through `wecare-checkout` (and later `wecare-commerce`) so there is ONE payment engine.

```
secure-files purchase request
      ↓
wecare-checkout  →  ONE PaymentAttempt  →  WhatsApp native / website payment
      ↓
payment verified  →  secure-file entitlement
```

**KEEP secure-files** for file access, entitlement, secure media, and document delivery (`send_document` / `wd_file_delivery`, `send_download_link`). Remove ONLY the independent payment implementation.

This directly feeds Track B: once there is one payment engine, `wecare-commerce` is the home for it.

## A4. CONSOLIDATE Meta order-status into one shared module

`lambda_utils/ecommerce/wa_order_status.py` ALREADY EXISTS and already owns the fulfilment VOCABULARY and transitions — VERIFIED states `PROCESSING` (L31), `PARTIALLY_SHIPPED` (L33), `SHIPPED` (L35), `COMPLETED` (L37), `CANCELED` (L40); `normalise` (L72), `is_valid` (L84), `can_transition` (L89), `default_body` (L115). Its docstring (L17-19) already states the invoice-engine sender and the tests should read the SAME table. It is imported by `payments/invoice-engine/handler.py`, `messaging/outbound-whatsapp/handler.py`, and `shared/lambda_utils/ecommerce/order_patch.py`.

What it does NOT yet own: the Meta PAYLOAD construction, the actual send, and the reference mapping — those still live inline in invoice-engine / outbound-whatsapp, and `outbound-whatsapp` still recognizes a legacy `isOrderStatus` envelope.

**Target:** make `wa_order_status.py` the SINGLE owner of states, transition validation, Meta payload construction, and reference mapping. ONLY `outbound-whatsapp` actually sends. `invoice-engine` calls `wa_order_status.transition(...)` instead of its own messaging semantics. Eliminate the legacy `isOrderStatus` envelope in `outbound-whatsapp`.

```
payment → wa_order_status.transition(...) → Meta order_status (outbound sends) → invoice template
```

This feeds Track B: the canonical fulfilment contract (A4) is a prerequisite for `wecare-commerce`'s fulfilment module.

## A5. whatsapp-business-api: SPLIT INTERNALLY (not into many Lambdas)

VERIFIED `amplify/functions/messaging/whatsapp-business-api/handler.py` is 6,816 lines. It covers business profile, Flows, Flow encryption/data exchange, media, webhooks, groups, payment configuration, catalog, template metadata, calling settings, Instagram, Conversions API, and service APIs.

**Target:** keep `wecare-whatsapp-business-api` as one Lambda, but restructure internally:

```
business_api/
    handler.py
    payment_config.py
    flow_api.py
    flow_crypto.py
    media.py
    profile.py
    groups.py
    webhooks.py
    catalog.py
```

It shrinks MAINLY by giving duplicated capabilities back to their domain owners: the service API (A2) goes to `wecare-service-api`; template CRUD (A1) goes to `wecare-whatsapp-template-management`. Do NOT turn each area into its own Lambda now — that trades code complexity for IAM/deployment/network complexity. Reassess further Lambda extraction only after the duplicates are removed (possible later candidate: media management if security/scale justifies it).

## A6. CONSOLIDATE Flow completion WRITES through one writer

`lambda_utils/flow_completion.py` already provides `claim_completion(...)` — VERIFIED at L283. Its docstring (L1-15) documents the historical multi-writer drift: four writers into `FlowSubmissionTable` across two Lambdas, including `flows/common.save_flow_submission` (put_item, no condition, 9 flows) and `whatsapp-business-api._save_flow_submission`. VERIFIED a direct writer still exists: `amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py` `mirror(row)` (L49) does a raw `table.put_item(Item=item)` (L67).

**Target:** every Flow completion goes through `flow_completion.claim_completion(...)` (or one successor API). Keep the per-workflow Flow modules (`subscribe_profile.py`, `paid_submit_request.py`, `paid_vault.py`, review, appointment, track, amend) SEPARATE — they are separate business workflows. Only the persistence PATH is unified, so no Flow owns its own submission schema.

```
Flow module → flow_completion.claim_completion(...) → FlowSubmissionTable
```

## A7. OTP: SHARE helpers, KEEP the two Lambdas separate

- `amplify/functions/auth/customer-registration` — HTTP request, client IP available, OTP throttle, creates customer + Cognito user.
- `amplify/functions/auth/customer-whatsapp-auth` — Cognito `CUSTOM_AUTH` trigger, no HTTP, no client IP, challenge generation/verification.

Different trust and invocation models. **KEEP both Lambdas separate.** Consolidate ONLY helpers into a shared module: phone normalization, OTP hashing, OTP validation, template selection, WABA route resolution.

## A8-A12. KEEP SEPARATE (trust-boundary rationale)

- **A8. inbound vs outbound WhatsApp:** inbound owns incoming events / parsing / contact updates / cart-order ingestion / automation triggers; outbound owns sending / service-window enforcement / templates / media send / payment settings / provider responses. Merging would give one Lambda both incoming-event processing AND money-capable outbound messaging, weakening isolation.
- **A9. whatsapp-calling public signed ingress vs inbound worker:** `whatsapp-calling` is the public Meta ingress (signature verification, webhook verification, calling events, forwarding non-call events). Inbound does the heavy reactive processing. Public signed ingress separated from the internal worker is a good boundary.
- **A10. checkout vs razorpay-webhook:** checkout creates the expectation ("I expect Rs X from customer Y for basket Z"); the webhook provides the evidence ("Razorpay confirms Rs X actually moved"). Never let one component both create and validate its own payment state.
- **A11. invoice-engine vs checkout:** checkout answers "what should this customer pay"; invoice-engine answers "what legal GST invoice corresponds to verified money" (fiscal-year sequencing, GST calculation, invoice number allocation, captured-total checks, asset generation). Invoicing belongs after settlement.
- **A12. waba-management vs business-api:** `wecare-waba-management` performs control-plane administration (phone registration, quality, limits, subscriptions, migration management, media/account administration). A customer message send should not require that permission surface. Helper-code consolidation (Meta credential loading, Graph request client, WABA resolution) is allowed, but NOT a Lambda merge.

## A13. Recommended consolidated function map

Today (~15 in this surface):

```
inbound-whatsapp · outbound-whatsapp · whatsapp-business-api · whatsapp-calling · whatsapp-voice ·
waba-management · whatsapp-template-management · whatsapp-templates · customer-whatsapp-auth ·
customer-registration · checkout · invoice-engine · razorpay-webhook · secure-files · service-api
```

Target:

```
1.  wecare-whatsapp-ingress / calling
2.  wecare-inbound-whatsapp
3.  wecare-outbound-whatsapp
4.  wecare-whatsapp-business-api        (modularized internally — A5)
5.  wecare-waba-management
6.  wecare-whatsapp-voice
7.  wecare-whatsapp-template-management ← absorbs whatsapp-templates (A1)
8.  wecare-service-api                  ← owns the service API once (A2)
9.  wecare-customer-registration
10. wecare-customer-whatsapp-auth
11. wecare-checkout                     (later absorbed by Track B wecare-commerce)
12. wecare-razorpay-webhook             (later absorbed by Track B wecare-commerce)
13. wecare-invoice-engine               (later absorbed by Track B wecare-commerce)
14. wecare-secure-files                 ← entitlement / delivery only, NOT payment (A3)
```

First round removes at least one whole Lambda (`whatsapp-templates`) and removes duplicate domain implementations from two others, without weakening any security boundary.

## A14. Recommended consolidation ORDER

1. Merge `whatsapp-templates` into `whatsapp-template-management` (A1); move Places out.
2. Choose `core/service-api` as the one service implementation; remove the duplicate `whatsapp-business-api/service_api.py` behavior (A2).
3. Remove payment-building responsibility from `secure-files`; route purchases through checkout (A3).
4. Create the one canonical Meta order-status module and eliminate the legacy parallel semantics (A4).
5. Move all Flow completion persistence through one writer (A6).
6. Break `whatsapp-business-api` into internal modules after the duplicate responsibilities are removed (A5).
7. Only after those changes, reassess whether any more physical Lambdas can safely disappear.

This is the function-consolidation plan to approve before touching tables or enabling the native-payment rollout.

---

# TRACK B — safe commerce consolidation

Track B keeps the external-money verification boundary independent. The final target is:

- **NEW `wecare-commerce`** absorbs checkout business orchestration + invoice/order/fulfilment orchestration.
- **KEEP `wecare-razorpay-webhook` separate** as the thin, independent verifier of external money.
- **KEEP `wecare-outbound-whatsapp` separate** as Meta transport.
- Retire `wecare-checkout` and `wecare-invoice-engine` only after parity and route/caller migration.

This replaces the older 3-into-1 proposal. A component that creates the expected payment must not also be the component that independently proves the provider moved money.

## B0. Live commerce responsibilities

| Function | Responsibility now | Final decision |
|---|---|---|
| `wecare-checkout` | pricing, PaymentAttempt, rail preparation | **ABSORB into `wecare-commerce`** |
| `wecare-razorpay-webhook` | signature/provider verification, dedup, paid evidence | **KEEP SEPARATE; thin it** |
| `wecare-invoice-engine` | GST invoice, rendering, delivery, fulfilment orchestration | **ABSORB into `wecare-commerce`** |
| `wecare-outbound-whatsapp` | Meta transport | **KEEP SEPARATE** |
| `wecare-inbound-whatsapp` | inbound ingestion | **KEEP SEPARATE** |
| `wecare-whatsapp-business-api` | provider/admin/Flow surface | **KEEP SEPARATE** |
| customer auth/read Lambdas | auth and read-only projections | **KEEP SEPARATE** |

## B1. Target state machine

```
Cart / offer
   ↓
resolve ONE ContactsTable identity
   ↓
server-side quote
   ↓
choose payment rail
   ↓
ONE active PaymentAttempt
   ├── WhatsApp ORDER_DETAILS
   └── Website Razorpay
             ↓
      Razorpay provider event
             ↓
   wecare-razorpay-webhook
   HMAC + provider verification
   replay/idempotency protection
             ↓
        VERIFIED_PAID
             ↓
       wecare-commerce
             ↓
          ONE Order
             ↓
 Meta order_status=processing
             ↓
       GST invoice once
             ↓
secure/Invoice/customer_invoice/
             ↓
wecare_default_invoice_image_template
  IMAGE + embedded Leave Review Flow
```

Later `processing → shipped → completed` changes Meta fulfilment state only. It does not issue or resend another GST invoice.

## B2. `wecare-commerce` internal modules

```
commerce/
    handler.py
    identity.py
    cart.py
    pricing.py
    payment_attempt.py
    native_whatsapp_pay.py
    website_pay.py
    finalization.py
    orders.py
    fulfilment.py
    invoice.py
    invoice_render.py
    invoice_delivery.py
    idempotency.py
```

Commerce owns business state transitions. It does **not** own Meta credentials or the Razorpay webhook-signing trust boundary.

## B3. Razorpay webhook final shape

The webhook is intentionally small:

```
signed Razorpay event
    ↓
verify HMAC
    ↓
deduplicate / replay guard
    ↓
resolve OUR PaymentAttempt/reference
    ↓
authoritative provider verification
    ↓
emit VERIFIED_PAID / VERIFIED_REFUNDED
    ↓
invoke commerce finalization
```

It must not become the home for:
- invoice rendering;
- review Flow sends;
- business fulfilment policy;
- a second order-construction implementation.

## B4. One PaymentAttempt rule

The UI may offer two rails, but it must not create two simultaneous payable attempts.

```
frozen CheckoutIntent
       ↓
choose rail
       ↓
ONE active PaymentAttempt
```

Before provider initiation, a rail switch may explicitly supersede/cancel and replace the attempt. Once ORDER_DETAILS has been sent or a Razorpay gateway order has been created, that provider-bound attempt is immutable.

## B5. Fulfilment and invoice contract

The canonical sequence is now explicit:

```
VERIFIED_PAID
  → ONE Order
  → Meta order_status=processing
  → issue/render GST invoice once
  → wecare_default_invoice_image_template
```

The invoice template's embedded Flow button is the only automatic Leave Review entry. Commerce sends no standalone `wecare_leave_review`, no post-payment review interactive message, and no free-form payment confirmation.

## B6. Tables remain decomposed

Do not merge DynamoDB tables just because functions are reduced. Keep distinct entities for identity, PaymentAttempts, provider payments, idempotency keys, Orders, GST invoice header/items/assets/sequence/delivery, Flow records, and message transport.

`CommerceKeys` remains separate from `OrderTable`; it is a concurrency/idempotency ledger, not an order record.

## B7. Safe strangler migration

1. Keep the current production routes/functions live.
2. Extract/reuse shared identity, pricing, PaymentAttempt, finalization and invoice domain code behind compatibility contracts.
3. Deploy `wecare-commerce` beside existing functions with no live customer routes.
4. Route checkout preparation to commerce first; retain old response shapes.
5. Verify website rail and native ORDER_DETAILS each produce one provider-bound PaymentAttempt.
6. Keep Razorpay webhook route unchanged; after verification it calls commerce finalization.
7. Verify duplicate webhook replay cannot create a second Order.
8. Verify `VERIFIED_PAID → order_status=processing → invoice template`.
9. Move invoice API/internal callers to commerce one-by-one.
10. After parity/readback, retire `wecare-checkout`.
11. After all invoice callers/routes are migrated, retire `wecare-invoice-engine`.
12. Keep `wecare-razorpay-webhook` as the independent external-money verifier.

No big-bang route swap is allowed.

## B8. Non-negotiable regression gates

- exactly one active/provider-bound PaymentAttempt per purchase;
- only provider-verified evidence may produce `PAYMENT_PAID`;
- duplicate Razorpay webhook → no second Order;
- duplicate Meta event → no second payable attempt;
- exactly one fiscal invoice number for one paid Order;
- invoice delivery retry → no duplicate customer receipt;
- shipped/completed → status update only, no second invoice;
- WABA1 remains the payment sender;
- invoice template remains the only automatic review prompt.

---

# Relationship between the tracks and overall sequencing

Track A's A3 (retire the secure-files payment builder) and A4 (one order-status implementation) feed the safe commerce strangler. The Razorpay webhook remains outside commerce as the independent verifier. Sequence Track A's low-risk whole-Lambda removal (A1 templates merge) and the shared-module extractions (A2, A3, A4, A6) FIRST, then Track B's commerce consolidation (which depends on the one-order-status-module and the one-payment-engine decisions).

```
Track A low-risk consolidation → commerce strangler (checkout + invoice orchestration) while Razorpay verification stays separate
```

---

# Config / identifier changes (non-secret only)

- **Stale docstring cleanup:** `ecommerce/checkout/handler.py` — VERIFIED `INITIATION_ENABLED = True` (L199); the comment block (L195-199) already notes the old `CHECKOUT_INITIATION_ENABLED` toggle is deleted and that `payment_readiness.evaluate` (`EXPECTED_CONFIGURATION_NAME` / `EXPECTED_PROVIDER_MID`, populated `WECAREDIGITAL` / `acc_TTFSyolquKEZEy`) still governs sends. Any remaining stale docstring prose (prior plan flagged L30-57) and `scripts/provision_checkout.py` should be corrected/retired during the relevant feature.
- **Order-status template wiring:** populate/confirm `WA_ORDER_STATUS_TEMPLATE` only after the owner confirms the exact approved mechanism (B6). Fails closed today.
- **Secrets:** unchanged — Razorpay API keys via `wecare/razorpay/api`, webhook secret via `wecare/razorpay-webhook`, Meta tokens via Secrets Manager. Owner MUST rotate the pasted live Key Secret.

---

# Test impact

Existing tests that GATE this work (must keep passing; some need updates):

- Allowlist / policy pins: `tests/test_transaction_whatsapp_template_allowlist.py` (`test_otp_manifest_has_only_waba1_sender` pins `OTP_WABA_MAP` to `{WABA1}` with phone `1016149501586345` / `wecare_otp`; `test_webhook_has_no_extra_post_payment_template_configuration` forbids the three POST_PAYMENT_* vars plus `WA_REVIEW_TEMPLATE`; forbids `postpay_request_v1` / `wecare_leave_review` / `isInteractive` and the `'flowButton':` literal in invoice-engine; asserts `wecare_whatapp_native_pay_template` + `wecare_default_invoice_image_template` in invoice-engine; `test_runtime_deploy_includes_customer_whatsapp_auth`).
- Invariants: `tests/test_whatsapp_payments_are_template_only.py`, `tests/test_whatsapp_order_cannot_charge_twice.py`, `tests/test_invoice_reaches_the_whatsapp_customer.py`, `tests/test_invoice_image_only.py`, `tests/test_inbound_whatsapp_payment_superseded.py`, `tests/test_invoice_totals_the_capture_exactly.py`.
- IAM pins: `tests/test_customer_orders_iam.py`, `tests/test_customer_invoice_iam.py`, `tests/test_commerce_keys_iam_alignment.py`.
- Checkout/readiness: `tests/test_checkout_gate_contract.py`, `tests/test_checkout_handler.py`, `tests/test_checkout_native_mode.py`, `tests/test_catalog_service_checkout.py`, `tests/test_checkout_service_prices_aws_only.py`, `tests/test_checkout_release_check.py`.
- Identity spine: `tests/test_customer_identity.py`, `tests/test_identity_claim_unblocks_downstream.py`, `tests/test_customer_order_link.py`, `tests/test_customer_uuid_reaches_the_order.py`, `tests/test_customer_uuid_on_the_invoice.py`, `tests/test_reconcile_customer_identity_links.py`, `tests/test_checkout_identity_seam_drift.py`.
- Invoice/order: `tests/test_invoice_order_cross_link.py`, `tests/test_central_order_directory.py`, `tests/test_invoice_number_reservation.py`, `tests/test_order_status_transitions.py`, `tests/test_order_finalization_requires_identity.py`.
- Flows: `tests/test_leave_review_wiring.py`, `tests/test_flow_submission_links_to_order.py`, `tests/test_customer_invoice_flow.py`, `tests/test_customer_orders_flow.py`, `tests/test_canonical_flow_ids.py`, `tests/test_flow_json_schema.py`, `tests/test_flow_inbox_projection.py`.

New tests needed:

- **(A2)** A test asserting there is exactly ONE service-API implementation path (the duplicate in `whatsapp-business-api/service_api.py` no longer serves the REST surface).
- **(A1)** A test asserting `whatsapp-templates` no longer exists as a function after the merge (deploy workflow / manifest no longer reference `wecare-whatsapp-templates`).
- **(A1)** A test asserting the Google Places proxy moved OUT of template management (`_get_gmaps_key` / `_places_autocomplete` / `_place_details` are not in the template-management Lambda).
- **(B8)** A test asserting the webhook env (and the new `wecare-commerce` env) no longer contains `POST_PAYMENT_FLOW_WABA1` / `POST_PAYMENT_FLOW_WABA2` / `POST_PAYMENT_REQUEST_TEMPLATE`.
- **(A4)** A test asserting a single Meta order-status payload/send path and no legacy `isOrderStatus` envelope in outbound.
- **(A6)** A test asserting every Flow completion writes through `flow_completion.claim_completion` (no direct `put_item` into `FlowSubmissionTable`, e.g. the `paid_submit_request.mirror` raw put is removed).
- **(B5)** A test asserting a single active PaymentAttempt per basket and immutability once a provider order has been issued.
- **(B7)** A test asserting the invoice send is `wecare_default_invoice_image_template` with IMAGE header + Flow button index 0 and no standalone `wecare_leave_review` send.
- **(B6)** A test asserting PAYMENT_PAID yields Meta `order_status = processing` then the invoice image template, and that later shipped/completed transitions do NOT re-send a GST invoice.

---

# Open risks and questions still needing owner input

1. **Google Places / location service home (A1):** where the Places proxy (`_get_gmaps_key` / `_places_autocomplete` / `_place_details`) should live after it leaves `whatsapp-templates` — a new small location/address Lambda, or an existing address/contact service. Must be decided before A1 can fully retire `whatsapp-templates`.
2. **Meta order_status send mechanism / approved payload (B6, A4):** named template vs native `order_status` message, and the exact approved payload. `WA_ORDER_STATUS_TEMPLATE` fails closed today. Do NOT invent a Meta template name.
3. **Rail-switch replace/cancel rule (B5):** the precise rule for replacing/cancelling a PaymentAttempt when the user switches rail before provider initiation (window, trigger, resulting state of the superseded attempt).
4. **Live secret rotation:** owner must rotate the pasted Razorpay Key Secret and update `wecare/razorpay/api` in Secrets Manager (treat as compromised).
5. **Live-vs-repo config drift (B8):** confirm the live `wecare-razorpay-webhook` POST_PAYMENT_* vars are cleaned up as part of retiring that function, not copied into `wecare-commerce`.
6. **secure-files pay retirement (A3):** confirm no remaining caller depends on `whatsapp_delivery.send_payment_request` before removal (gated off but present).
7. **Service checkout exclusion:** services remain website-only (`WEBSITE_RAZORPAY_STANDARD`); confirm they are intentionally excluded from the WhatsApp-native pay path inside `wecare-commerce`.

---

## Appendix A: Live template vocabulary (do not invent new names)

| Purpose | Template |
|---|---|
| OTP | `wecare_otp` |
| Native order/payment (ORDER_DETAILS) | `wecare_whatapp_native_pay_template` |
| Invoice image (IMAGE header + FLOW button "Leave Review" index 0) | `wecare_default_invoice_image_template` |
| Leave a review | `wecare_leave_review` (NOT used as a separate send; review is the invoice template's Flow button) |
| Download | `wecare_default_download` |
| Location sharing | `wecare_location_share_pin` |

## Appendix B: Verified reference example (non-secret)

- Order `WD-ORD-9NMB2KT3`; linked invoice `WD/2627/00007`; invoice PNG at `secure/Invoice/customer_invoice/`. Both invoice delivery-dedup records marked delivered, so webhook retries do not re-send the invoice. `wecare_default_invoice_image_template` (English) requires an IMAGE header + a FLOW button "Leave Review" at index 0.
