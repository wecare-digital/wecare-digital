# Current-state audit (migration step 1)

> Read-only inventory of what exists **in code** on branch `stack`, captured
> 2026-10-20. No live AWS state is asserted here — config values quoted are from
> the repo's `config/lambda-env-manifest.json`, which records intended
> deployment settings and must be re-verified against live AWS before relying.

---

## A. WhatsApp native payment — is it working? **No (not live).**

This was the headline question. The precise, code-grounded answer:

There are **two distinct native in-WhatsApp `order_details` (WhatsApp Pay /
`ORDER_DETAILS` button) paths**, with **opposite** dispositions. Neither results
in a live in-chat charge today.

### 1. Invoice-collection + catalog-**service** leg — RETAINED but OFF
- Real sender exists: `amplify/functions/ecommerce/checkout/handler.py`
  → `_send_order_details` (the *only* Meta `order_details` sender in the repo).
  `amplify/functions/core/secure-files/whatsapp_delivery.py` → `send_payment_request`
  builds the `wecare_pay` `ORDER_DETAILS` template for invoice delivery.
- **Gated off by default.** Env `CHECKOUT_INITIATION_ENABLED` is default OFF and
  **deliberately absent** in `amplify/infra/checkout.json`. On top of that,
  `payment_readiness.evaluate` must return `PAYMENT_READY` from a **live Meta
  readback**, and both readiness inputs are empty — so payment is blocked
  **independently of the flag**. The handler runs everything up to reserving a
  `PAYREF#` attempt, then returns `PAYMENT_INITIATION_DISABLED` instead of
  sending anything payable.
- Verdict: **BACKEND IMPLEMENTED / INITIATION DISABLED** — plumbing exercised
  end-to-end, no live payable message goes out.

### 2. Cart purchases — dual payment rail (PR implementation)
- Public commerce routes enter through one **Checkout** action and review the basket on `/cart/`.
- After review, the customer chooses once between **Pay on WhatsApp** (native ORDER_DETAILS /
  Review and Pay) and **Pay here** (Razorpay Standard Checkout).
- Both rails use the same authenticated customer, ProductsTable-authoritative quote, payment
  attempt/reference controls, provider-confirmed capture, and OrderTable finalization.
- The WhatsApp rail copies the session-owned `contactId` and public `customerUuid` from the
  canonical ContactsTable row onto the payment attempt so the finalized order stays attached to
  the same customer used by Subscribe, Inbox/Flows and website sign-in.

### 3. Native inbound WhatsApp catalog orders — GATED OFF
- `message.type == 'order'` is handled by `_handle_cart_order` in
  `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`, gated by env
  `WA_CATALOG_ORDERS_ENABLED` = **`"false"`** (`config/lambda-env-manifest.json`).
- The old money path is **deleted**: "`_send_payment_request` and its inner
  may-send guard are DELETED (A3.3)". A cart order now only mints a phone-bound
  hand-off row linking to `/cart/?basket=<token>`; **the website prices and
  charges**. No `order_details`/Review-and-Pay message, no total computed inbound.

### Config observed in repo (`config/lambda-env-manifest.json`)
- `CHECKOUT_MODE = "AWS_NATIVE"`
- `WA_CATALOG_ORDERS_ENABLED = "false"` — **superseded 2026-10-25:** the manifest and both
  live functions (inbound, checkout) carry `"true"`; see `whatsapp-meta-coverage.md`.
- `CHECKOUT_INITIATION_ENABLED` — absent (= off) in `amplify/infra/checkout.json`.

### Bottom line
**The authoritative live money path is the website Razorpay flow, verified by
`payments/razorpay-webhook`.** WhatsApp is the conversation/handoff surface; it is
not taking native in-chat payments in the current configuration. The honest
"WhatsApp money" beat is: *payment link / basket handoff sent over WhatsApp,
customer pays on the website.*

---

## B. Frontend workspace routes — `src/pages/workspace/`

The repo has **already partly consolidated** toward the target IA: several legacy
names are now thin redirects into the canonical hubs. Classification:

| Area | File | State | Disposition for rebuild |
| --- | --- | --- | --- |
| `customers` | `customers/index.tsx` (~1642L) | **Real feature** — full CRUD, bulk, duplicate detection, detail panel | **Keep** → Customers foundation |
| `communications` | `communications/index.tsx` (~459L) | **Real hub** — Inbox + Manage; embeds inbox, channels, templates, flows, automation, scheduled, analytics, usage | **Keep** → Communications (target already close) |
| `commerce` | `commerce/index.tsx` (~98L) | **Real hub** — Orders + Catalog | **Keep** → Commerce |
| `payments` | `payments/index.tsx` (~108L) | **Real hub** — Collect (PayFlow) + Ledger | **Keep** → Payments |
| `service` | `service/index.tsx` (~211L) | **Real hub** — Requests/Appointments/Documents + contextual actions | **Keep** → Service |
| `platform` | `platform/index.tsx` (~89L) | **Real hub** — MCP, architecture, Lambdas, repo, WA graph tools, CORS, design ref | **Keep** → Platform |
| `content` | `content/index.tsx` (~172L) | **Real hub** — Blog/SEO + **Short links** (statically imported) | Fold: links → Comms→Manage→Links; blog/SEO → Platform/Comms |
| `automation` | `automation/index.tsx` (~114L) | **Real hub** — Staff agent, Rules, Schedules, Knowledge | Fold into Communications → Manage → Automation |
| `task` | `task/index.tsx` (~400L) | **Real feature** over `conversation-meta` (no tasks backend) | Fold into Home "needs attention" / Tasks |
| `access` | `access/index.tsx` (~58L) | **Auth gate** — login → `router.replace('/workspace')` | Keep as auth entry |
| `engage` | `engage/index.tsx` (~42L) | **Redirect** → Communications (maps legacy `?tab=`) | Retire name; keep redirect |
| `contacts` | `contacts/index.tsx` (~20L) | **Redirect** → Customers | Retire name; keep redirect |
| `pay` | `pay/index.tsx` (~26L) | **Redirect** → Payments | Retire name; keep redirect |
| `link` | `link/index.tsx` (~17L) | **Redirect** → Comms→Manage→Links | Retire name; keep redirect |
| `forms` | `forms/index.tsx` (~31L) | **Redirect** → Service → requests | Retire name; keep redirect |
| `seo` | `seo/index.tsx` (~33L) | **Redirect** → Content | Re-home SEO ops → Platform |
| `docs` | `docs/index.tsx` (~18L) | **Redirect** → Service → documents | Retire name; keep redirect |
| `admin` | `admin/index.tsx` (~11L) | **Redirect** → Platform (system architecture) | Retire name; keep redirect |
| `settings` | `settings/platform/index.tsx` (~27L) | **Redirect** → Platform (no `settings/index.tsx`) | Retire; config lives with each product |
| `dashboard` | `dashboard/waba-usernames.tsx` only | **Utility page**, no index | Fold utility into Platform/Comms |

### `engage/` subfolders
- `inbox/` (~1654L) — **Real** omnichannel inbox over MessagesTable; reused by
  Communications + the task queue. **This is the core asset.**
- `broadcast/` (~238L) — **Real** cross-channel campaign composer.
- `channels/` (~84L) — **Real** tabbed channel-settings hub.
- `logs/` (~503L) — **Real** unified delivery log over MessagesTable.
- `settings/` (~121L) — **Real** channel/consent settings home.
- `whatsapp/`, `service-ops/` — **Redirects** into Communications/Service.

**Read of the migration:** the hard IA work is largely done — the six hubs exist
and legacy names already redirect. The rebuild is mostly (a) finishing the fold
of `content`/`automation`/`task` into the canonical hubs, (b) the identity/
consent/cleanup depth in Customers, (c) refunds/returns/tracking in Payments/
Commerce, and (d) the device/app + public-Home passes — **not** a from-scratch
navigation rebuild.

---

## C. Backend Amplify functions — `amplify/functions/`

Confirmed present and purpose-documented (docstrings):

**ecommerce/** — `checkout` (front door; prices from ProductsTable, PaymentAttempt,
never charges), `customer-orders` (read-only own history), `customer-invoice`
(presigned own invoice), `catalog-management` (Meta/WhatsApp catalog via Graph),
`native-catalog-admin` (staff ProductsTable CRUD, delete=archive),
`meta-catalog-sync` (ProductsTable → Meta, stream-driven), `service-requests`
(intent + post-pay activation, cannot move money), `customer-session`,
`product-image-gen`.

**payments/** — `invoice-engine` (GST-compliant invoices for all 3 entry points),
`razorpay-webhook` (processes **all** Razorpay events; reconciles captures; the
authoritative capture verifier), `payments-read` (read-only). Razorpay helper
libs in `shared/lambda_utils/integrations/razorpay_*`.

**messaging/** — `inbound-whatsapp-handler` (Meta webhook ingest; cart order →
website handoff when gated off), `whatsapp-business-api` (+ `flows/` router with
modules: subscribe, submit_request, paid_submit_request, track/amend, appointment,
rx_slot, drop_docs, orders, customer_orders, catalog_services, postpay, etc.),
`outbound-whatsapp`, `outbound-sms` + `sms-aws` (**AWS End User Messaging is the
only SMS transport**; India TRAI DLT gate), `rcs-send` + `rcs-dlr` (**Sinch India**
Conversation API), `outbound-email`, plus voice/calling/analytics/scheduled/bulk.

**core/** — `url-shortener` (ShortLinksTable; `wecare.digital/r`), `contacts`
(unified CRUD/search), `conversation-meta` (task-queue backing store),
`service-api`, `crm`, `secure-files` (gated S3 tier; holds `whatsapp_delivery.py`
`send_payment_request`).

**ai/** — `ai-generate-response`, `ai-config-management`, `ai-query-kb`, `mcp`,
`workspace-mcp` (KMS-encrypted creds, no arbitrary send/payment mutation),
`agent-action-group` (read-only).

**auth/** — customer registration/profile, WhatsApp-auth custom challenge, email
verification, blog-subscribe (double opt-in), cognito-custom-message.

**operations/** — billing, bulk job create/control/worker (SQS), dlq-replay,
docs-scraper, seo-tools, sla-engine, system-cleanup.

**edge/** — `get-miss-redirect` (Lambda@Edge for private-S3 `/get/` misses).

---

## D. Net assessment vs the charter

| Charter area | Reality | Gap to close |
| --- | --- | --- |
| IA = 6 hubs + Platform | **Mostly in place**; legacy names redirect | Finish folding content/automation/task; retire redirect shells last |
| One Customer identity | Customers page is real & heavy | Formalize primary-phone protection, offline-create→link, Manage Data merge/preview |
| Consent as evidence | Settings computes opt-in from ContactsTable | Evidence model + history + import-of-evidence-only |
| One OrderTable, source=filter | checkout/webhook/orders real | Surface source filter; converge WhatsApp catalog when ungated |
| Server-authoritative payments | **Strong — preserve** | Do not rewrite for UI |
| WhatsApp native pay | **Not live** (see §A) | Leave gated; website Razorpay is the money path |
| Refunds/returns/tracking | razorpay-webhook handles refund events; no staff return/refund UX lifecycle | **Build** the lifecycles |
| Short links | Real backend; currently under `content` | Move to Comms→Manage→Links |
| Device/app/public-Home | Capacitor foundation exists | Dedicated passes per charter |
