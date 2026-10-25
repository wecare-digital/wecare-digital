# WECARE.DIGITAL — Workspace Rebuild Charter

> **Status:** Locked scope (owner-approved, 2026-10-19/20). This is a
> **fresh-product rebuild**, not an incremental patch of the old workspace.
> **Read before implementing:** inspect the *current* repo and live AWS first —
> this document records an architecture agreed on a date; individual
> versions/deployments may have changed. Live source and AWS win over any
> written audit.

Location: `docs/workspace-rebuild/`. This folder holds the single canonical
scope for the rebuild:

- **`README.md`** (this file) — the final plan.
- **`CONTINUATION_PROMPT.md`** — paste-into-a-fresh-session prompt if this
  session is lost.

---

## 0. North-star identity/data rule

```
ONE HUMAN
  → ONE CANONICAL CUSTOMER
  → ONE VISIBLE CUSTOMER ID        (server-minted customerUuid)
  → ONE CONTACT RECORD
  → ONE PRIMARY VERIFIED PHONE / WHATSAPP IDENTITY
  → ONE ADDRESS MODEL              (checkoutDeliveryAddress)
  → ALL ACTIVITY ATTACHES HERE
```

The Customer owns: conversations, consent, short links, carts, orders,
invoices, payments, refunds, returns, service requests, Flow submissions,
documents, activity.

Internal technical IDs (`contactId`, Cognito `customerId`, BSUID, provider IDs)
remain internal/diagnostic — staff normally see **one** Customer ID.

---

## 1. Final workspace information architecture

```
WECARE.DIGITAL
├── Home
├── Customers
├── Communications
│     ├── Inbox
│     └── Manage
├── Commerce
│     ├── Orders
│     └── Catalog
├── Payments
│     ├── Collect
│     └── Ledger
├── Service
└── Platform
```

**Retire as product-navigation concepts** (fold their function in, keep old URLs
as redirects until safely retired):

- Engage, global Settings section, workspace dropdown, global sidebar
- CRM as primary navigation
- separate WhatsApp / SMS / RCS applications
- separate website-order and WhatsApp-order systems
- fragmented Pay / Commerce / Contacts duplicates
- standalone Content, Automation, Forms, Links top-level modules

Communication content/automation → **Communications → Manage**.
Product content → **Commerce → Catalog**.

### Current → target mapping (verified 2026-10-20 in `src/pages/workspace/`)

| Current route area | Disposition |
| --- | --- |
| `customers/` | **Keep** → Customers (identity foundation) |
| `contacts/` | Fold into Customers (Customer *is* Contact 360) |
| `communications/` | **Keep** → Communications |
| `engage/` (inbox, broadcast, channels, whatsapp, logs, service-ops, settings) | Split: Inbox → Communications → Inbox; the rest → Communications → Manage |
| `commerce/` | **Keep** → Commerce → Orders + Catalog |
| `payments/`, `pay/` | Merge → Payments → Collect + Ledger |
| `service/` | **Keep** → Service |
| `platform/`, `settings/platform` | **Keep** → Platform (ops only) |
| `content/` | Fold into Communications → Manage / Commerce → Catalog |
| `automation/` | Fold into Communications → Manage → Automation |
| `forms/` | Fold into Communications → Manage → Flows |
| `link/` | Fold into Communications → Manage → Links |
| `seo/`, `docs/`, `dashboard/`, `admin/`, `access/`, `task/`, `settings/` | Re-home: ops → Platform; product config → owning product; Home takes "needs attention" |

---

## 2. Global navigation

No sidebar. No workspace dropdown. Minimal chrome:
`WECARE.DIGITAL · Back/Workspace · Universal Search · Alerts/Tasks · Profile`.

Mobile permanent bottom nav: **Home | Search | Tasks | Me**.
Business areas reached from Home, search, recent activity, contextual links.

Topic nav stays tiny — **Communications:** Inbox | Manage · **Commerce:** Orders
| Catalog · **Payments:** Collect | Ledger. Channels are filters, never tabs.

---

## 3. Workspace Home

Operational launchpad, not a decorative dashboard:

- **Search anything** (universal).
- **Needs attention** — conversations, payments waiting, orders needing action,
  service requests, delivery failures, customer-data reviews. Every metric links
  to actionable work.
- **Start** — Message · Customer · Order · Collect payment · Service request.
- **Work** — the six areas.
- **Recent activity.**

---

## 4. Customers (identity foundation)

- Customer *is* Contact 360 — no separate app. Tabs: Overview, Orders, Payments,
  Messages, Service, Activity. Actions: Message, Create order, Collect payment,
  Create service request, More.
- **Offline/manual creation:** staff create walk-in/phone/offline customers with
  **no fabricated Cognito login**. Server mints the public Customer ID. Later
  online verification **links** to the existing customer — never a duplicate,
  never ownership transfer on weak phone-string similarity.
- **Primary phone/WhatsApp** is a protected routing identity; a verified phone is
  never silently overwritten by a lower-trust import/manual edit. One
  unambiguous primary; secondary numbers modeled later if needed.
- **Manage Data** (under Customers, not a top-level app): find/merge duplicates,
  archive stale, resolve missing Customer IDs / unlinked orders, review invalid
  phones / incomplete addresses, bulk import/export. Merges **preserve** messages,
  orders, payments, invoices, consent, addresses, service requests, Flow
  submissions, notes, provenance, activity. Bulk actions **preview first**
  (safe / needs-review / blocked-by-financial-history); never "delete N" blindly.

---

## 5. Consent / opt-in

Consent is **evidence**, not a staff-flippable boolean. Track WhatsApp, SMS,
Email, RCS (where relevant), opt-outs, allowlists. Each record carries:
customer, channel, state, source, timestamp, purpose, evidence/reference, expiry
if applicable. Bulk import imports **existing consent evidence** only — it may
never manufacture opt-in for an address book. `OPTED_OUT` is first-class.
Consent **history** is never overwritten by a boolean.

---

## 6. Communications — Inbox | Manage

**Inbox:** one unified conversation surface; WhatsApp/SMS/RCS/Email/Voice are
filters + metadata. Thread shows customer context (orders, outstanding payment,
service case) and actions (reply, template, payment request, create order,
create service request). Phone = list → thread; tablet/desktop = adaptive
list/detail.

**Manage** (progressive disclosure, not 20 pages): Channels & identities,
Templates, Flows, Media, Campaigns, Automation, AI Agent, Scheduled sends,
Calling, Webhooks, Links, Delivery, Failures, Analytics, Usage estimates,
Provider diagnostics.

### Channel truth

- **SMS:** backend picks region (`+91` → AWS End User Messaging `ap-south-1` +
  TRAI DLT; others → default `us-east-1`). **No region selector in UI.** Do not
  show "Delivered" if receipts aren't ingested — only submission status.
- **RCS:** India = Sinch (`wecare-rcs-send` / `wecare-rcs-dlr`). Unknown
  Sinch-side properties stay **Unknown**, never assumed green. No fake global RCS.
- **WhatsApp:** accounts/numbers, profile, username/BSUID, templates, Flows,
  catalog integration, payments channel, calling, campaigns, AI Agent,
  automation, webhooks, quality, diagnostics — **nested resources**, not nav.

### WhatsApp Flows / forms

Flows are an input technology, not a CRM. Manage at Communications → Manage →
Flows (Overview, Builder, Preview, Data exchange, Publish, Responses, Analytics,
Activity). A **submission attaches to the resource it represents**: profile/
subscribe → Customer; consent → Customer consent; order info → Order; service →
Service Request; appointment → Appointment; documents → Service/Documents.
`FlowSubmission` is preserved as provenance (duplicate-protected against Meta
retries). No "Flow Responses" dead-end app.

---

## 7. Commerce — Orders | Catalog

**One OrderTable** for every source; source is a **filter**, not a separate app:
`WEBSITE · WHATSAPP_PAYMENT · WHATSAPP_CATALOG · STAFF_COMMERCE · STAFF_PAYMENT ·
SERVICE_FLOW`. All share orderId, orderNumber, customerUuid, contactId, items,
pricing snapshot, payment, address snapshot, invoice, status, fulfilment,
activity. Source never changes accounting rules.

**Order detail** carries: Customer, Items, authoritative pricing snapshot,
Payment, Invoice, address snapshot, Fulfilment, Messages, related Flows, related
Service Requests, Refund/return state, Activity. (Live route
`GET /wa-business/orders/{orderId}/submissions` feeds related submissions.)

### Entry channels converge (not separate systems)

```
          ONE CUSTOMER
   ┌──────────┼──────────┐
WEBSITE   WHATSAPP     WHATSAPP
 STORE     STORE        FLOW
   └────┬─────┘           │
   SERVER CHECKOUT        │
   (pricing/inventory/    │
    GST/delivery/Delight) │
        │                 │
   PAYMENT ATTEMPT        │
   ┌────┴────┐            │
 Website    WhatsApp      │
 Razorpay   Review&Pay    │
   └────┬────┘            │
   VERIFIED CAPTURE       │
        │                 │
     ONE ORDER ◄──────────┘ (when the Flow is paid/order work)
   ┌────┴────┐
 PHYSICAL  SERVICE
  ORDER     ORDER
```

- **Website store** stays a real public experience; browser success callback is
  **never** proof of payment. Order carries `Source = WEBSITE`; same Order staff
  see in Commerce → Orders.
- **WhatsApp Review & Pay** converges to the same OrderTable after authoritative
  capture.
- **WhatsApp Catalog orders:** backend + duplicate-charge protection exist, and
  `WA_CATALOG_ORDERS_ENABLED=true` is live on inbound and checkout (readback 2026-10-25;
  the earlier "false" was stale). Classify **LIVE**. End-to-end checklist: catalog mapping,
  retailer IDs, inbound order message, canonical identity, basket handoff, claim,
  address, server pricing, inventory, duplicate prevention, payment, order
  creation, customer UX. **Re-check live config before acting.**

**Catalog:** `ProductsTable` is authoritative. Owns Products, Variants, Pricing,
Inventory, Media, Publishing, Flow mappings, Activity. Website and WhatsApp read
the **same** catalog. Meta Catalog/feeds are **publishing destinations**
(`ProductsTable → Meta sync/feed → WhatsApp Commerce`), not a second master.

---

## 8. Payments — Collect | Ledger

**Collect:** Customer → canonical address → lines → **server quote**
(subtotal/GST/shipping/Delight/convenience fee/final payable) → invoice → send
Review & Pay or approved collection path. Browser never calculates authoritative
money.

**Delight** = the only discount policy: **0.5% of collection, capped ₹50, auto-
applied.** No dynamic coupon/gift-card engine (retired) unless explicitly asked.

**Payment core (preserve — do not rewrite for UI):**
`server quote → frozen snapshot → atomic inventory reservation → PaymentAttempt →
PAYREF/idempotency → Razorpay → authoritative capture verification → exactly one
Order → Invoice/reconciliation.` Website, WhatsApp, Inbox, staff Pay, Commerce
all converge here.

**Ledger:** a record shows Customer, Order, Invoice, pricing, payment attempt,
provider IDs/status, reconciliation, payment-request delivery, refund, activity.
Attempts/reconciliation are diagnostic detail. Elevate exceptions only (captured
but order missing, invoice missing, link pending, provider ambiguous, failed
payment, reconciliation mismatch).

**Refunds / returns / cancellations (need completion):**
- Refund: request → eligibility → amount/reason → approval → provider refund →
  authoritative readback/webhook → full/partial state → notify. Explicit full +
  partial semantics.
- Return: order → request → eligibility → items/reason/evidence → approve/reject
  → logistics → inspection → refund/replacement/remedy → closed.
- Cancellation: unpaid = cancel invoice/request; paid pre-fulfilment =
  cancellation/refund; shipped = return/replacement.

**Fulfilment** (inside Order): `processing → partially-shipped → shipped →
completed`, server-validated transitions. Courier integration is **not** a
complete production capability — allow truthful manual tracking (carrier, number,
URL, shipped date, note); do not advertise a fake integration.

**Inventory:** preserve atomic DynamoDB reservation/decrement. Expose available/
reserved/sold/released/low-stock/exceptions inside Product/Order and Home alerts.

---

## 9. Service

A work queue/resource, not many pages. A Service Request contains: Customer,
original Order, Flow Submission, Payment, Forms, Documents, Appointment,
Messages, Amendments, Resolution, Activity. Paid service orders hand off into
Service automatically.

---

## 10. Short links

Not a top-level module — live at **Communications → Manage → Links**. Reuse
`ShortLinksTable` / `LinkClicksTable` / URL-shortener backend. A link can attach
to Customer, Campaign, Order, Invoice/payment, Service Request, or general.
Track purpose, destination, related record, creator, created date, expiry, active
state, clicks. Lifecycle **ACTIVE → INACTIVE → RETIRED**; prefer **deactivate**
over hard-delete (links live in WhatsApp/SMS/RCS/email/QR/invoices/print).
Inactive links show a safe destination/message. Clicks/analytics retained in
audit history.

---

## 11. Deletion policy (workspace-wide)

- **Hard-delete allowed:** draft product, unused short link, empty accidental
  contact, draft Flow, draft template before provider submission, temporary
  unpublished content — with explicit confirmation + audit trail.
- **Archive/deactivate instead:** customer with history, product used by an
  order, campaign, published Flow, used link, communication automation.
- **Never destructively delete via normal UI:** paid order, issued statutory
  invoice, captured payment, refund, payment-attempt/idempotency evidence,
  reconciliation evidence, consent history required for compliance. These may be
  archived/redacted where policy permits — not casually destroyed.

---

## 12. Public Home

Deep redesign around **actual customer journeys**: a clear **static** core
proposition (not endless rotation/animation), "what do you need?", real
services/products, "how it works" (Need → Price → Pay → Track → Complete →
Support), available communication channels (where real), final CTA.

---

## 13. Universal device / mobile / app

One responsive codebase (Next.js → Web/PWA + Capacitor → iOS/Android). No
separate mobile logic. Hard requirements: no horizontal scroll from 320px;
fluid grid/flex/`clamp()`; `viewport-fit=cover` + `env(safe-area-inset-*)`;
`dvh`/`svh`/`lvh`; foldable viewport-segment support + fallback; ≥44×44 targets;
touch/mouse/pen/keyboard; 200% zoom; `prefers-reduced-motion`; light-only color
scheme (dark mode intentionally unused); semantic a11y; no color-only status;
WebView-safe critical flows; responsive media; feature detection with `@supports`.
Tables become cards/list-detail on small screens; foldables/tablets use adaptive
list-detail panes.

**Mobile nav:** global **Home | Search | Tasks | Me**; contextual sticky actions
— Customer: Message/Order/Pay · Order: Message/Fulfil/More · Payment:
Message/payment-action/More · Service: Message/Assign/Resolve.

**App:** continue the existing Capacitor/PWA foundation. Audit manifest, icons/
screenshots, service worker/private caching, deep/universal/app links, auth/
session in WebViews, push, uploads/camera/share, downloads, payments, external
browser handling, safe areas, offline behavior, store readiness. Do not claim
store readiness until verification gates pass.

---

## 14. Platform

Technical **operations**, not a settings dump: system/Lambda/API health, jobs,
provider health, integrations, deployment/version, failure queues,
security/access, diagnostics, audit. Product config stays with its product
(WhatsApp → Communications, Catalog → Commerce, payments → Payments).

---

## 15. Universal search

Searches name, phone, Customer ID, email, order, invoice, payment/reference,
service request, short link. Action search: create customer, send message,
collect payment, create order, show failed sends. Search replaces the large menu
tree.

---

## 16. Migration order

1. Re-inventory current Next.js routes/components + live backend/AWS; mark every
   real capability **Live / Partial / Provider-blocked / Config-required / Retire**.
2. Lock canonical data contracts.
3. Build shared responsive design system.
4. Rebuild Public Home.
5. Rebuild Workspace Home + global shell.
6. Customers (+ identity/cleanup/consent).
7. Communications (Inbox + Manage).
8. Commerce (Orders + Catalog).
9. Payments (Collect + Ledger).
10. Service.
11. Platform operational surfaces.
12. Finish refunds/returns/tracking gaps.
13. Migrate data/identity carefully.
14. Redirect old routes.
15. Remove duplicate implementations **only after** replacements verify.
16. Full phone/tablet/foldable/browser/WebView/a11y pass.
17. Capacitor/PWA/store-readiness hardening.
18. Full release verification.

Do **not** delete the old system first. Reuse strong backend
payment/security/idempotency work rather than rewriting it for visual
consistency.

---

## 17. Definition of done

Nothing is done until: `npm run build` passes (static export is the real gate);
relevant typecheck/lint/tests pass; route/nav/broken-link audit passes;
~320/375/768/1024/1440 pass; portrait + landscape; no horizontal overflow; 200%
zoom; keyboard-only; reduced motion; safe areas; foldable behavior; current +
previous major of Safari/Chrome/Firefox/Edge/Samsung Internet where practical;
≥1 WebView/in-app-browser context for global layout changes; no clipped
forms/dialogs/tables; no keyboard traps; **no fake controls, no fake success
states, no browser-authoritative money, no orphaned real capabilities, no broken
old deep links, no production customer sends during verification**; and live
backend/provider state re-read before claiming something is operational.

---

## 18. Known live state — last verified 2026-10-19 (RE-CHECK before relying)

- `wecare-checkout` live, `CHECKOUT_INITIATION_ENABLED=true`,
  `CHECKOUT_MODE=AWS_NATIVE`.
- Active: `wecare-razorpay-webhook`, `wecare-invoice-engine`,
  `wecare-customer-orders`, `wecare-service-requests`, `wecare-catalog-management`.
- Tables active: `OrderTable`, `PaymentAttemptsTable`, `CommerceKeys`,
  `ProductsTable`; `OrderTable customerId-createdAt-v2-index` ACTIVE.
- EventBridge `wecare-commerce-customer-links` ENABLED `rate(5 minutes)`.
- No sampled recent errors in checkout/webhook/invoice/customer-orders/
  service-request functions.
- Payment/checkout core is materially stronger than the current UI — **preserve**.
- Native WhatsApp catalog handling is live; `WA_CATALOG_ORDERS_ENABLED=true` (verified 2026-10-25).
- India SMS = AWS End User Messaging `ap-south-1` + TRAI DLT; other SMS default
  `us-east-1`. India RCS = Sinch. Canonical address = `checkoutDeliveryAddress`.
  Delight = 0.5% / max ₹50, only discount policy; coupon/gift-card architecture
  retired.

Treat these as last-known facts, not permanent truth.
