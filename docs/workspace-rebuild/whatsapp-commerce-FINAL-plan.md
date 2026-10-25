# WhatsApp Commerce Consolidation — FINAL Plan

Status: **FINAL PLAN. PLANNING ONLY — no code, config, or test changed in this pass.** This document is a fresh, independent audit re-derived from the live code on branch `stack`. It SUPERSEDES the prior two-track draft (`whatsapp-commerce-consolidation-plan.md`). Owner review required before any implementation is delegated.

Repository: `wecare-digital/wecare-digital`
Working / base branch: `stack`. Do **NOT** commit to `stack`. A later implementation pass uses a dedicated feature branch + PR. This pass writes only this plan doc and the `.agents` task state.

Goal (owner, three parts, all must hold):
1. **Works without breaking** the running production system — non-breaking, incremental, strangler migration on the `live` alias.
2. **Reduces redundancy / burden** — remove duplicated code surfaces and Lambda-to-Lambda hops in the money path.
3. **Reduces the number of deployed functions** — fewer Lambdas. This document quantifies the before/after count (section 2).

---

## 0. Security (read first, non-negotiable)

- The owner pasted a **LIVE Razorpay Key Id and Key Secret** into the task. They are deliberately NOT reproduced here or in any file. **Because the live Key Secret was pasted into a chat, the owner MUST rotate it** in the Razorpay dashboard and update the `wecare/razorpay/api` secret in AWS Secrets Manager. Treat the pasted secret as compromised.
- All Razorpay secrets come from AWS Secrets Manager (`wecare/razorpay/api` for API keys, `wecare/razorpay-webhook` for the webhook secret). Meta tokens come from Secrets Manager. The consolidation MUST preserve this. No secret value may ever be written to code, config, tests, or docs.
- Only NON-SECRET identifiers appear below: Account/MID `acc_TTFSyolquKEZEy`, WABA1 `2094615664435155` (phone +919330994400, phone_number_id `1016149501586345`), WABA2 `2513394156072604`, config names `WECAREDIGITAL` and `WECAREUPI` (UPI VPA `wecaredigitalbh511413.rzp@rxairtel`), MCC 7392, purpose code 03, Legal name WECARE.DIGITAL BHARATWORKS, Trade name WECARE.DIGITAL, PAN AAFFW7196L, GSTIN 19AAFFW7196L1Z8.

---

## 1. Deployment model (what "a function" actually is here)

There is **no single CDK/Amplify app** that owns these Lambdas. Verified on `stack`:

- `find amplify/functions -name handler.py` = **77 handler files**.
- Only **9** functions have a `resource.ts`. The rest are **zip-packaged** and deployed by `scripts/deploy_all_lambdas.py`, which bundles `handler.py` + `lambda_utils/*` + per-function `modules/` and publishes to the **`live` alias**.
- The env manifest `config/lambda-env-manifest.json` records **66 deployed `wecare-*` functions** (`"_functions": 66`, verified by counting keys).
- Several ecommerce/auth handlers are deployed by their **own provisioning scripts**, each creating a dedicated least-privilege IAM role, a published version, and a `live` alias: `scripts/provision_customer_invoice.py`, `provision_customer_orders.py`, `provision_service_requests.py`, `provision_customer_profile.py`, `provision_native_catalog_api.py`, `provision_catalog_media.py`, `provision_checkout.py`, `provision_customer_whatsapp_auth.py`, `provision_customer_registration.py`, `provision_order_status_template.py`, etc.

**Implication for this plan:** creating or retiring a function is **not** an Amplify/CDK stack edit. It means writing/removing a `provision_*.py` (role + version + `live` alias + the alias-qualified `lambda:AddPermission` for API Gateway) and updating the `deploy_all_lambdas.py` bundle wiring and `config/lambda-env-manifest.json`. Example confirmed in `provision_checkout.py`: `LIVE_ALIAS = "live"`, `ROLE_NAME = "wecare-checkout-role"`, and a documented note that a function-level invoke permission does NOT authorise an alias-qualified invoke. Every migration step below is written against this per-function model.

---

## 2. QUANTIFIED function-reduction target (the headline)

**Baseline: 66 deployed `wecare-*` functions** (manifest source of truth).

This plan removes **3 whole deployed Lambdas** and removes **2 duplicate code surfaces** (not separate Lambdas, but real burden). It creates **1 new** Lambda (`wecare-commerce`) that absorbs 3 existing ones.

| Change | Lambdas removed | Lambdas added | Net |
|---|---|---|---|
| Merge `wecare-whatsapp-templates` → `wecare-whatsapp-template-management` (R1) | −1 | 0 | **−1** |
| Merge `wecare-checkout` + `wecare-razorpay-webhook` + `wecare-invoice-engine` → new `wecare-commerce` (R2) | −3 | +1 | **−2** |
| Remove duplicate `service_api.py` from `whatsapp-business-api` (R3) | 0 (code surface) | 0 | 0 |
| Retire secure-files payment builder (R4) | 0 (code surface; Lambda kept) | 0 | 0 |

**Function count: 66 → 63 (net −3 deployed Lambdas).**

Named removals: `wecare-whatsapp-templates`, `wecare-checkout`, `wecare-razorpay-webhook`, `wecare-invoice-engine`.
Named addition: `wecare-commerce`.
Code-surface removals (burden, no Lambda delta): `whatsapp-business-api/service_api.py`, the secure-files payment builder in `core/secure-files/whatsapp_delivery.py`.

The reduction stops at −3 on purpose. Section 5 lists the Lambdas that look mergeable but MUST stay separate for trust-boundary / least-privilege / single-writer reasons. **Reducing functions must NOT become reducing tables** (section 6).

---

## 3. Fresh audit of the WhatsApp payment / order / invoice / flow surface

All facts below were read on branch `stack`. Line numbers are current.

### 3.1 The real cross-function invocation graph (verified via grep for `wecare-*:live`)

```
inbound-whatsapp-handler ──► wecare-checkout:live            (handler.py L116, L6472)
inbound-whatsapp-handler ──► wecare-whatsapp-business-api:live (L2834, L5918, L6419)

checkout ────────────────► wecare-whatsapp-business-api:live  (handler.py L176, L2380)
checkout ────────────────► wecare-outbound-whatsapp:live      (L184, L2237)

invoice-engine ──────────► wecare-whatsapp-business-api:live  (handler.py L211)
invoice-engine ──────────► wecare-outbound-whatsapp:live      (L3817, L5546)

razorpay-webhook ────────► wecare-invoice-engine:live         (handler.py L2659)
razorpay-webhook ────────► wecare-secure-files:live           (L909)

secure-files ────────────► wecare-whatsapp-business-api:live  (whatsapp_delivery.py L52)

outbound-whatsapp ───────► wecare-whatsapp-business-api:live  (handler.py L531)
```

**The burden, stated precisely:** ONE financial state machine (`checkout → razorpay-webhook → invoice-engine`) is spread across THREE Lambdas joined by remote `live`-alias invokes. Payment intent, authoritative settlement, and GST invoicing each live in a different function, and the settlement path takes Lambda→Lambda hops (`razorpay-webhook → invoice-engine → outbound`). Every hop is a place where a payment reference, an order-number reservation, or a `contactId`/`customerUuid` can drift. This is the single biggest source of redundancy/burden to remove.

### 3.2 Per-function audit (in-scope surface)

| Function (repo path) | Purpose | Entry | Key tables | Real callers → callees |
|---|---|---|---|---|
| `messaging/inbound-whatsapp-handler` | Ingest Meta webhooks, parse messages, cart/order ingestion, trigger checkout | webhook/event | WhatsAppInboundTable, ContactsTable | ← Meta webhook; → checkout:live, whatsapp-business-api:live |
| `ecommerce/checkout` | Cart pricing, PaymentAttempt creation, native ORDER_DETAILS initiation, readiness gate | HTTP + internal | PaymentAttemptsTable, CommerceKeys, ProductsTable, OrderTable | ← inbound; → whatsapp-business-api:live, outbound-whatsapp:live |
| `payments/razorpay-webhook` | Razorpay signature verify, authoritative paid-state write, order finalize/recover | HTTP (public signed) | PaymentsTable, PaymentAttemptsTable, CommerceKeys, RazorpayWebhookLogTable, InvoicesTable | ← Razorpay; → invoice-engine:live, secure-files:live |
| `payments/invoice-engine` | Fiscal GST invoice creation, numbering, items, PNG render, fulfilment status, WA invoice delivery | internal | Invoices/InvoiceItems/InvoiceAssets/InvoiceSequence/InvoiceDeliveryLog, Payments, PaymentAttempts, CommerceKeys, Contacts | ← razorpay-webhook; → whatsapp-business-api:live, outbound-whatsapp:live |
| `messaging/outbound-whatsapp` | Meta transport: template/order_details/media payload build + SEND, service-window, order_status send | internal | WhatsAppOutboundTable, Contacts, MediaFiles, RateLimit | ← checkout, invoice-engine; → whatsapp-business-api:live |
| `core/secure-files` | Secure file entitlement + document delivery; (gated-off payment builder) | HTTP + internal | SecureFilesTable, DownloadGrantsTable, ServiceRequestsTable | ← razorpay-webhook; → whatsapp-business-api:live |
| `messaging/whatsapp-business-api` | WABA/Flow/payment-config/admin/provider surface; bundles `service_api.py` | HTTP + internal | FlowRegistry/FlowSubmission/FlowLog, Contacts | ← many; → (Meta Graph) |
| `messaging/whatsapp-template-management` | Template CRUD / validation / library / carousel / media | HTTP | — | control-plane |
| `messaging/whatsapp-templates` | **Duplicate** template CRUD/library/carousel/media **+ Google Places proxy** | HTTP | — | control-plane |
| `core/service-api` | Canonical `/orders /service/* /documents /faq /appointments /rx-slots /enterprise-assist /reviews` | HTTP | service/order tables | data-plane |
| `auth/customer-whatsapp-auth` | Cognito `CUSTOM_AUTH` trigger; `wecare_otp` send/verify | Cognito trigger | Contacts | security boundary |
| `auth/customer-registration` | HTTP registration, OTP throttle, creates customer + Cognito user | HTTP | Contacts | security boundary |
| `ecommerce/customer-orders` | Read-only `/orders/` history / profile projection | HTTP | OrderTable (read) | data-plane read |

### 3.3 Genuine redundancy / burden to REMOVE

- **R1 — Two template Lambdas.** `whatsapp-template-management/handler.py` (977 lines) and `whatsapp-templates/handler.py` (806 lines) BOTH independently define `META_GRAPH_URL`, `AWS_TO_META_WABA`, `_appsecret_proof`, WABA→phone resolution, Meta Graph request code, and template CRUD + library + carousel + media. Verified markers: template-management `META_GRAPH_URL` L37, `AWS_TO_META_WABA` L77, `DEFAULT_META_WABA_ID='2094615664435155'` L81, `_appsecret_proof` L98; templates (plural) `META_GRAPH_URL` L31, `AWS_TO_META_WABA` L35, `_appsecret_proof` L70. This is a whole-Lambda duplicate and the safest first removal.
  - **Caveat:** `whatsapp-templates` is the ONLY home of the Google Places proxy: `_get_gmaps_key` L157, `_places_autocomplete` L297, `_place_details` L334, `_legacy_shape_from_place_details` L258. This must NOT move into template management (see Open Question OQ1).
- **R2 — Three-Lambda money state machine.** `checkout + razorpay-webhook + invoice-engine` jointly own one financial lifecycle across remote `live` invokes (3.1). This is the core burden.
- **R3 — Duplicate Service API implementation.** `core/service-api/handler.py` (49,429 bytes) is the canonical REST impl; `whatsapp-business-api/service_api.py` (34,968 bytes) is a hand-maintained duplicate exposing the same `/orders /service/* /documents /faq /appointments /rx-slots /enterprise-assist /reviews` surface. Verified `whatsapp-business-api/handler.py` imports it at L5926-5959 (`from service_api import ...`, with a 501 fallback "Service module not deployed"). Keeping two implementations aligned by hand is a documented drift risk.
- **R4 — secure-files payment builder.** `core/secure-files/whatsapp_delivery.py` has its OWN `reference_id()` L126, `send_payment_request(...)` L136, and `order_details` L156 whose own comment (L23) states the shape was COPIED from `payments/invoice-engine`. It is gated OFF (`SECURE_FILES_PAYMENT_ENABLED="false"`, verified in manifest for `wecare-secure-files`). This is a dormant second payment path.
- **R5 — Order-status send split.** `lambda_utils/ecommerce/wa_order_status.py` ALREADY owns the vocabulary + transition rules: states `PROCESSING` L31 / `PARTIALLY_SHIPPED` L33 / `SHIPPED` L35 / `COMPLETED` L37 / `CANCELED` L40, transition map L63-68, `normalise` L72, `is_valid` L84, `can_transition` L89, `default_body` L115. It is imported by invoice-engine, outbound-whatsapp, and `order_patch.py`. What it does NOT own: the Meta payload construction + actual send, which still live inline. `outbound-whatsapp` also still parses a legacy `isOrderStatus` envelope (L1191) alongside `_approved_order_status_template` (L952). Burden = two order-status code paths.
- **R6 — Multi-writer Flow completion.** `lambda_utils/flow_completion.py` provides `claim_completion(...)` L283 and documents historical multi-writer drift (docstring L8-9: `flows/common.save_flow_submission` put_item no-condition across 9 flows; `whatsapp-business-api._save_flow_submission`). A raw writer still exists: `whatsapp-business-api/flows/paid_submit_request.py` `mirror(row)` L49 → `table.put_item(Item=item)` L67.

### 3.4 Deliberate separations that MUST stay (NOT redundancy)

- **Single authoritative paid-state writer.** The Razorpay webhook logic is the ONE writer of paid state. Whether it stays its own Lambda or folds into `wecare-commerce`, the single-writer discipline MUST hold (section 4). Never let one component both create and verify its own payment state.
- **Least-privilege IAM per function.** Each `provision_*.py` grants a scoped role (e.g. `provision_checkout.py` documents checkout has NO order-creation permission; it initiates a payment that authorises itself). Merging across these boundaries would widen blast radius.
- **GST invoice normalization.** Invoices/InvoiceItems/InvoiceAssets/InvoiceSequence/InvoiceDeliveryLog are normalized fiscal tables with fiscal-year sequencing. They stay normalized (section 6).
- **Ingress vs worker, inbound vs outbound, auth vs payment, control-plane vs data-plane.** See section 5.

---

## 4. The consolidations (decisive)

### R1 — Merge `wecare-whatsapp-templates` → `wecare-whatsapp-template-management` (−1 Lambda)

Keep ONE physical Lambda `wecare-whatsapp-template-management`; modularize its source (`templates.py`, `validation.py`, `library.py`, `carousel.py`, `media.py`). Retire the `wecare-whatsapp-templates` Lambda. **Move the Google Places proxy OUT** of templates into a location/address service — do NOT fold Places into template management (OQ1). Safest first removal: no money path touched.

### R2 — Merge `checkout` + `razorpay-webhook` + `invoice-engine` → new `wecare-commerce` (−2 net)

Create ONE Lambda `wecare-commerce` with internal modules deployed as one runtime:

```
wecare-commerce/
  handler.py            # one router; internal module calls, not Lambda→Lambda
  identity.py           # resolve canonical Contact (contactId + customerUuid; LINK, never recreate)
  cart.py  pricing.py   # server-side pricing
  payment_attempt.py    # ONE active PaymentAttempt; immutable once provider-bound
  native_whatsapp_pay.py  website_pay.py
  provider_verification.py  # Razorpay signature verify = the single paid-state writer
  finalization.py       # preserves ACCEPTED_CHECKOUT_MODES guard
  order.py              # idempotent single OrderTable write
  fulfilment.py         # Meta order_status via wa_order_status (R5)
  invoice.py invoice_render.py invoice_delivery.py  # GST invoice, PNG, InvoiceDeliveryLog dedup
  idempotency.py        # CommerceKeys
```

Internal actions (module calls, NOT remote Lambda invokes): `prepareNativeCart`, `prepareNativeCatalogService`, `recoverPaidOrder`, `finalizePayment`, `deliverInvoice`. Public routes: `/commerce/checkout/prepare`, `/commerce/checkout/verify`, `/commerce/webhooks/razorpay`, `/commerce/orders/{id}/fulfilment`, `GET /commerce/invoices/{id}`, `/commerce/invoices/{id}/render`, `/commerce/invoices/{id}/deliver`.

**Single-writer discipline inside one runtime:** the paid-state write stays owned by the provider-verification module only. No other module writes paid state. The webhook-vs-checkout trust boundary becomes an internal module boundary, not a weaker one: checkout modules create the expectation; `provider_verification` writes the evidence.

`wecare-commerce` calls `wecare-outbound-whatsapp:live` ONLY for the actual Meta send (it does not absorb transport — see section 5).

### R3 — Remove duplicate `service_api.py` from `whatsapp-business-api` (code surface)

Make `core/service-api` the single implementation. WhatsApp Flows call `wecare-service-api` (or a shared service-domain module) instead of `whatsapp-business-api` carrying a second REST impl. Remove `whatsapp-business-api/service_api.py` and its import block (handler.py L5926-5959) once callers are repointed. No Lambda delta; removes a documented drift risk.

### R4 — Retire the secure-files payment builder (code surface; keep the Lambda)

Delete `reference_id`/`send_payment_request`/`order_details` from `core/secure-files/whatsapp_delivery.py`. Purchases route through `wecare-commerce` (the one payment engine). **KEEP `wecare-secure-files`** for entitlement, secure media, and document delivery (`wd_file_delivery`, download links). Since the builder is already gated off (`SECURE_FILES_PAYMENT_ENABLED="false"`), removal is low-risk. `razorpay-webhook`'s invoke of `secure-files:live` for entitlement stays (it is repointed to `wecare-commerce → secure-files` after R2).

### R5 — One Meta order-status owner (shared module, no Lambda delta)

Extend `wa_order_status.py` to own the Meta payload construction + reference mapping in addition to states/transitions. `wecare-commerce` fulfilment calls `wa_order_status`; ONLY `outbound-whatsapp` actually sends. Eliminate the legacy `isOrderStatus` envelope in `outbound-whatsapp` once callers no longer send it. NOTE: `outbound-whatsapp` ALREADY has the send mechanism — `_approved_order_status_template` (L952): in-window updates go as a free-form interactive `order_status` message needing NO template; out-of-window requires an APPROVED `sub_category: ORDER_STATUS` template provisioned by `scripts/provision_order_status_template.py`. `WA_ORDER_STATUS_TEMPLATE` defaults to `''` and fails closed (L954), so out-of-window sends are currently disabled until that template is provisioned (OQ2).

### R6 — One Flow-completion writer (shared module, no Lambda delta)

Route every Flow completion through `flow_completion.claim_completion(...)`. Replace the raw `put_item` in `flows/paid_submit_request.py` `mirror()`. Keep the per-workflow Flow modules separate; unify only the persistence path so no Flow owns its own submission schema.

---

## 5. Lambdas that MUST stay separate (and why)

| Kept separate | Rationale |
|---|---|
| `inbound-whatsapp-handler` vs `outbound-whatsapp` | receive/parse/ingest vs send/service-window/money-capable transport — do not give one Lambda both |
| `whatsapp-calling` (public signed ingress) vs inbound worker | public Meta signature-verified ingress vs internal reactive processing |
| `wecare-commerce` (payment+settlement+invoice) vs `outbound-whatsapp` | payment code must not hold Meta access tokens or own general messaging |
| `customer-whatsapp-auth` / `customer-registration` vs commerce | OTP/auth security boundary; different trust + invocation models (Cognito trigger vs HTTP). Share helpers only |
| `customer-orders` (read-only) vs `wecare-commerce` (writer) | read/write split; least privilege |
| `whatsapp-business-api` (admin/provider/Flow registry) vs commerce | keep payment IAM blast radius small |
| `waba-management` (control-plane) vs `business-api`/send | account administration permission surface must not be on a message send |

`whatsapp-business-api` (6,816 lines, verified) is NOT merged; it is modularized internally and shrinks by giving the duplicated Service API back to `service-api` (R3) and template CRUD to template-management (R1). Do not split it into many new Lambdas now — that trades code complexity for IAM/deploy/network complexity.

---

## 6. Tables: NO merges

Function reduction does NOT become table reduction. One function ≠ one table. These stay decomposed:

- **Identity:** `ContactsTable` (one identity, `contactId` + `customerUuid`, LINK not recreate on website WhatsApp-OTP / Cognito sub), `IdentityClaimsTable`.
- **Checkout/payment:** `PaymentAttemptsTable`, `PaymentsTable`, **`CommerceKeys`**, `RazorpayWebhookLogTable`.
- **Commerce:** `OrderTable` — SINGULAR. The `ORDERS_TABLE` env var is PLURAL and maps to the singular `OrderTable` (manifest `ORDERS_TABLE=stack-wecare-digital-OrderTable` L125; `checkout/handler.py` L145 `ORDERS_TABLE = shared_tables.orders_table_name()`). Documented trap — do NOT "fix" the env name.
- **Fiscal invoice:** `InvoicesTable`, `InvoiceItemsTable`, `InvoiceAssetsTable`, `InvoiceSequenceTable`, `InvoiceDeliveryLogTable`.
- **WhatsApp/Flow:** inbound/outbound message logs, `FlowRegistryTable`, `FlowSubmissionTable`, `FlowLogTable`.

**`CommerceKeys` MUST NOT merge into `OrderTable`.** It answers concurrency/idempotency questions (has reference X been used; has payment Y created an order; has this invoice been sent; does this cart already have a payable attempt; has this webhook won the race). It is the primary protection against duplicate charges/orders/invoices (used in `order_keys.py`).

---

## 7. Invariants the migration MUST preserve

1. **Never charge twice:** exactly ONE active `PaymentAttempt` across both rails; immutable once a WhatsApp ORDER_DETAILS message OR a Razorpay gateway order is issued. `PAYMENT_SENDERS = frozenset({PHONE_NUMBER_ID_1})` (WABA1-only, `wa_payment_request.py` L83). `CommerceKeys` idempotency on reference/payment/order.
2. **Never duplicate an invoice:** `InvoiceDeliveryLogTable` dedup (invoice-engine dedup-by-referenceId/paymentId, L818/L916) must carry into `wecare-commerce.invoice_delivery`.
3. **Single paid-state writer:** only the provider-verification path writes paid state.
4. **Settlement-mode guard:** `finalization.ACCEPTED_CHECKOUT_MODES = {AWS_NATIVE, WEBSITE_RAZORPAY_STANDARD, WHATSAPP_NATIVE_CART}` (`finalization.py` L28); `WHATSAPP_NATIVE_PG` is deliberately EXCLUDED because the native leg settles via the webhook, not cart finalization. Preserve this exclusion.
5. **Allowlist test contract** (`tests/test_transaction_whatsapp_template_allowlist.py`) must keep passing: `OTP_WABA_MAP == {WABA1}` with phone `1016149501586345` + template `wecare_otp`; webhook must NOT contain `postpay_request_v1`, `wecare_leave_review`, `isInteractive`, nor `POST_PAYMENT_FLOW_WABA1/WABA2`, `POST_PAYMENT_REQUEST_TEMPLATE`, `WA_REVIEW_TEMPLATE`; invoice-engine must NOT contain the literal `'flowButton':`.
6. **Retained response contracts** until callers migrate: `PAYMENT_REQUEST_SENT` (payment_attempt state, rank 30, `payment_attempt.py` L65) with its monotonic guard (`checkout/handler.py` L2282-2297).

### 7.1 Owner's fixed fulfilment contract to RESTORE

```
PAYMENT_PAID → Meta order_status = processing → wecare_default_invoice_image_template
```

Template pipeline: `wecare_otp` → `wecare_whatapp_native_pay_template` → `wecare_default_invoice_image_template`. Invoice image at S3 `secure/d/public/Invoice/customer_invoice/`. Review entry = the invoice template's OWN Flow button ("Leave Review", index 0, IMAGE header) ONLY — no separate `wecare_leave_review` send, no post-payment interactive Flow, no free-form confirmation. Later `processing → shipped → completed` updates Meta fulfilment WITHOUT sending a new GST invoice. Verified manifest: `wecare-invoice-engine` carries `WA_PAY_TEMPLATE=wecare_whatapp_native_pay_template` and `WA_INVOICE_TEMPLATE=wecare_default_invoice_image_template`.

### 7.2 Live-vs-repo drift to CLEAN UP (do not copy)

`POST_PAYMENT_FLOW_WABA1/WABA2` and `POST_PAYMENT_REQUEST_TEMPLATE` are ABSENT from the repo (`grep` across `amplify/ config/ scripts/` returns nothing) and the allowlist test forbids them. The LIVE `wecare-razorpay-webhook` still carries them. The retirement of `wecare-razorpay-webhook` (R2) MUST STRIP these from live and `wecare-commerce` must NOT inherit them. Also note the STALE docstring in `checkout/handler.py` L30-57 referencing the deleted `CHECKOUT_INITIATION_ENABLED` toggle (actual code: `INITIATION_ENABLED = True` L199; readiness still governed independently by `EXPECTED_CONFIGURATION_NAME=WECAREDIGITAL` / `EXPECTED_PROVIDER_MID=acc_TTFSyolquKEZEy`) — fix the docstring during R2.

---

## 8. Non-breaking migration sequence (strangler, per-function `live` alias)

Do low-risk shared-module and whole-Lambda removals first; do the money merge last.

**Phase 1 — low-risk, feeds the money merge:**
1. **R1** merge templates: build `whatsapp-template-management` with the modular source + add template routes; cut `whatsapp-templates` callers over; move Places out (OQ1); after a monitoring window, retire the `wecare-whatsapp-templates` Lambda (remove its `provision`/bundle wiring + manifest entry).
2. **R3** service-api: repoint Flow callers to `wecare-service-api`; delete `whatsapp-business-api/service_api.py` + its import block.
3. **R4** secure-files: delete the payment builder; keep entitlement/delivery.
4. **R5** order-status: move Meta payload/mapping into `wa_order_status`; remove the legacy `isOrderStatus` path from `outbound`.
5. **R6** flow completion: route all writers through `claim_completion`; remove the raw `mirror()` put_item.

**Phase 2 — the money merge (R2), build-beside / dual-run / one caller at a time:**
6. Build `wecare-commerce` beside the three live functions with NO live routes (new `provision_commerce.py`: least-privilege role union scoped per module, version, `live` alias, API-GW alias permission).
7. Move pricing/identity/PaymentAttempt/finalization/order/invoice into its modules; run the EXISTING checkout/webhook/invoice tests against them; baseline green.
8. Repoint `checkout prepare` (inbound's `wecare-checkout:live` call at inbound L116/L6472) to `wecare-commerce`; verify Rs 1 prepare/send.
9. Repoint the Razorpay webhook route to `wecare-commerce`; verify captured payment → exactly ONE Order (CommerceKeys + single-writer).
10. Enable Meta `order_status = processing` via `wa_order_status`→outbound; render invoice PNG to `secure/d/public/Invoice/customer_invoice/`; send `wecare_default_invoice_image_template` (IMAGE + Flow button index 0). InvoiceDeliveryLog dedup must hold.
11. Move invoice API routes to `wecare-commerce`; repoint `razorpay-webhook → secure-files` entitlement invoke to `wecare-commerce → secure-files`.
12. After a monitoring window with the money/invoice invariants green, retire `wecare-checkout`, `wecare-razorpay-webhook`, `wecare-invoice-engine` (remove provision/bundle wiring + manifest entries).
13. Strip the live POST_PAYMENT_* drift (7.2); fix the stale checkout docstring; confirm the allowlist test still passes against the new layout.

Caller repointing summary (from the graph in 3.1): `inbound → checkout:live` becomes `inbound → wecare-commerce`; `checkout/invoice-engine → outbound:live` becomes `wecare-commerce → outbound:live`; `razorpay-webhook → invoice-engine:live` becomes an internal module call inside `wecare-commerce`; `razorpay-webhook → secure-files:live` becomes `wecare-commerce → secure-files:live`.

---

## 9. Risk register + rollback

| Step | Blast radius | Failure detection | Rollback |
|---|---|---|---|
| R1 templates merge | template CRUD (control-plane; no money) | template API 5xx / missing routes; Places endpoint 404 | repoint callers back to `wecare-whatsapp-templates` alias (not retired until window passes) |
| R3 service-api dedup | Flow service calls | `/service/*`,`/orders` Flow responses fail; 501 "Service module not deployed" | keep `service_api.py` + import until callers confirmed on `wecare-service-api` |
| R4 secure-files payment removal | none (gated off) | n/a (already false) | re-add module from git if entitlement delivery regresses |
| R5 order-status | fulfilment notifications | order_status not sent / wrong payload; `order_status_template_not_configured` logs | keep inline path until shared payload verified; `live` alias revert on outbound |
| R6 flow completion | Flow submissions | duplicate/missing FlowSubmission rows | revert `mirror()` change; `claim_completion` is idempotent |
| R2 money merge (per step 8-12) | **CRITICAL** — charges, orders, invoices | double charge (2 PaymentAttempts), duplicate order (CommerceKeys miss), duplicate invoice (InvoiceDeliveryLog miss), missing paid-state write, wrong `contactId`/`customerUuid` | each caller repoint is a `live` alias cutover — revert the alias/route to the old function; old three functions stay deployed until step 12 |
| step 13 drift strip | webhook env | allowlist test fails | re-run `env_manifest.py`; manifest is source of truth |

Every cutover is a `live`-alias or API-GW route change and is individually reversible because the superseded function stays deployed through the monitoring window.

---

## 10. Open questions needing owner input

- **OQ1 — Location/Places home.** Where does the Google Places proxy (`_get_gmaps_key`/`_places_autocomplete`/`_place_details` in `whatsapp-templates`) land? Options: a new small location Lambda, or an existing address/contact service. It must NOT go into template management. (Note: `scripts/provision_maps_server_key.py` exists — may inform the home.)
- **OQ2 — Meta `order_status` out-of-window send.** `WA_ORDER_STATUS_TEMPLATE` is empty and fails closed. In-window uses the free-form interactive `order_status` message (no template). For out-of-window, do we provision the approved `sub_category: ORDER_STATUS` template via `scripts/provision_order_status_template.py`, and what is its approved name? Do NOT invent a Meta template name.
- **OQ3 — Rail-switch rule.** Exact replace/cancel rule when a user switches payment rail BEFORE provider initiation: the window, who may trigger it, and the state the superseded `PaymentAttempt` lands in. After provider binding the attempt is immutable (no question there).
- **OQ4 — Razorpay secret rotation (ACTION REQUIRED).** The pasted live Key Secret must be rotated in the Razorpay dashboard and `wecare/razorpay/api` updated in Secrets Manager. Treat as compromised until done.

---

## 11. Final recommended sequence and before→after

```
Phase 1 (shared-module + 1 whole-Lambda removal): R1 → R3 → R4 → R5 → R6
Phase 2 (money merge, strangler): build wecare-commerce → dual-run → cut over
         checkout → webhook → invoice/order_status → retire 3 → strip drift
```

**Function count: 66 → 63 (net −3 deployed Lambdas).**
- Removed: `wecare-whatsapp-templates`, `wecare-checkout`, `wecare-razorpay-webhook`, `wecare-invoice-engine`.
- Added: `wecare-commerce`.
- Code-surface burden removed (no Lambda delta): `whatsapp-business-api/service_api.py`, secure-files payment builder.
- Tables: unchanged (no merges). `CommerceKeys` stays its own idempotency table; GST invoice tables stay normalized.
