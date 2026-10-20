# New-session continuation prompt

> Paste the block below into a fresh session if this one is lost. The full
> locked plan lives in `docs/workspace-rebuild/README.md` in this repo.

---

I am rebuilding WECARE.DIGITAL from the current GitHub repository and live AWS
backend. Continue this as a **fresh-product rebuild, not an incremental patch**
of the old workspace. The locked plan is in
`docs/workspace-rebuild/README.md` — read it first.

**IMPORTANT:** Before making implementation decisions, inspect the CURRENT repo
and live AWS, because this prompt records the architecture agreed on
October 19–20, 2026 and individual versions/deployments may have changed. Do not
blindly trust old audit documents when live source or AWS differs.

**REPOSITORY / ENVIRONMENT**
- GitHub: `wecare-digital/wecare-digital`
- AWS region: `us-east-1`
- Use the connected GitHub and AWS tools for current evidence.
- Do NOT perform production customer sends, real payment captures/refunds,
  destructive provider changes, or blind data deletion during verification.

**CORE PRODUCT DECISION** — rebuild the workspace fresh. Do NOT retain as
product-navigation concepts: Engage; global Settings; workspace dropdown; global
sidebar; CRM as the main nav concept; separate WhatsApp/SMS/RCS apps; separate
website-order and WhatsApp-order systems; fragmented Pay/Commerce/Contacts
duplicates. Old URLs may remain as compatibility redirects until safely retired.

**FINAL WORKSPACE IA**
```
Home · Customers · Communications(Inbox|Manage) · Commerce(Orders|Catalog)
· Payments(Collect|Ledger) · Service · Platform
```
Prefer integrating communication content/automation into Communications → Manage
and catalog/product content into Commerce → Catalog rather than separate
Content/Automation/Forms/Links workspaces.

**GLOBAL NAV** — no sidebar, no workspace dropdown. Chrome: WECARE.DIGITAL ·
Back/Workspace · Universal Search · Alerts/Tasks · Profile. Mobile bottom nav:
Home | Search | Tasks | Me. Topic nav tiny: Communications Inbox|Manage, Commerce
Orders|Catalog, Payments Collect|Ledger. Channels are filters, never tabs.

**IDENTITY** — ONE HUMAN → ONE CANONICAL CUSTOMER → ONE VISIBLE CUSTOMER ID
(server-minted customerUuid) → ONE CONTACT → ONE PRIMARY VERIFIED PHONE/WHATSAPP
→ ONE ADDRESS (checkoutDeliveryAddress). Keep internal IDs (contactId, Cognito
customerId, BSUID, provider IDs) internal/diagnostic. A verified phone must never
be silently overwritten by lower-trust import/manual edit. Staff can create
offline/manual customers with NO fabricated Cognito login; later online
verification links to the existing customer, never a duplicate. Customer owns
name, phone, email, company/GST, address, consent history, conversations,
orders, invoices/payments/refunds, service requests, Flow submissions, short
links, activity.

**CLEANUP** — Customers → Manage Data (not a top-level app): duplicate
detection, reviewed merging, archive stale, resolve missing Customer IDs /
unlinked orders, invalid-phone/incomplete-address review, bulk import/export.
Merges preserve messages/orders/payments/invoices/consent/addresses/service
requests/Flow submissions/notes/provenance/activity. Bulk actions preview first
(safe / needs-review / blocked-by-financial-history). Never merge on weak name
or phone matches.

**DELETE POLICY** — hard-delete only truly unused/unreferenced draft/accidental
data. Archive/deactivate customers-with-history, used products/links, campaigns,
published resources. Never casually hard-delete paid orders, issued invoices,
captured payments, refunds, payment-attempt/idempotency evidence, reconciliation
evidence, or compliance consent history.

**CONSENT** — evidence, not a mutable boolean. Preserve channel state/history for
WhatsApp/SMS/Email/RCS, opt-outs, allowlists. Each record: customer, channel,
state, source, timestamp, purpose, evidence/reference. Bulk import = existing
consent evidence only; never manufacture opt-in for an address book. OPTED_OUT
is first-class.

**ADDRESS** — Contact owns one canonical checkoutDeliveryAddress (server-side
contact_address/payment_address authority). No competing address models in UI.

**COMMUNICATIONS** — Inbox | Manage only. Inbox = unified conversations
(WhatsApp/SMS/RCS/Email/Voice as filters + metadata) with customer context and
actions (reply, template, payment request, create order, create service
request); phone list→thread, tablet/desktop adaptive list/detail. Manage
(progressive disclosure): Channels & identities, Templates, Flows, Media,
Campaigns, Automation, AI Agent, Scheduled sends, Calling, Webhooks, Links,
Delivery, Failures, Analytics, Usage estimates, Provider diagnostics.

**CHANNEL TRUTH** — SMS: backend picks region (+91 → AWS EUM ap-south-1 + TRAI
DLT; others default us-east-1); NO region selector in UI; don't show "Delivered"
without ingested receipts. RCS: India = Sinch (wecare-rcs-send / wecare-rcs-dlr);
unknown Sinch properties stay Unknown; no fake global RCS. WhatsApp capabilities
nested under Manage, not primary nav.

**WHATSAPP FLOWS** — input technology, not a CRM. Manage at Communications →
Manage → Flows (Overview, Builder, Preview, Data exchange, Publish, Responses,
Analytics, Activity). A submission attaches to the resource it represents
(profile/subscribe → Customer; consent → Customer consent; order → Order;
service → Service Request; appointment → Appointment; documents →
Service/Documents). Preserve FlowSubmission as provenance (duplicate-protected).
No standalone "Flow Responses" app.

**COMMERCE** — Orders | Catalog only. One OrderTable for Website / WhatsApp
Review&Pay / WhatsApp Catalog / Staff Commerce / Staff Payment / Service orders;
source is a FILTER (WEBSITE, WHATSAPP_PAYMENT, WHATSAPP_CATALOG, STAFF_COMMERCE,
STAFF_PAYMENT, SERVICE_FLOW), same accounting rules. Order detail: customer,
items, pricing snapshot, payment, invoice, address snapshot, fulfilment,
messages, related Flows, related service requests, refund/return state, activity.
Website path: product → cart → verified customer → saved address → server quote →
Review → Razorpay → server verification → verified capture → ONE order; browser
callback is never proof of payment. WhatsApp Review&Pay converges to the same
model. WhatsApp Catalog orders: BACKEND IMPLEMENTED / PRODUCTION GATED
(WA_CATALOG_ORDERS_ENABLED last known false) — verify end-to-end before enabling;
re-check live config.

**CATALOG** — ProductsTable authoritative; owns products/variants/pricing/
inventory/media/publishing/Flow mappings/activity. Website and WhatsApp share one
catalog. Meta Catalog/feeds are publishing destinations (ProductsTable → Meta
sync/feed → WhatsApp Commerce).

**PAYMENTS** — Collect | Ledger only. Collect: customer → canonical address →
lines → SERVER quote (subtotal/GST/shipping/Delight/convenience fee/final
payable) → invoice → send Review&Pay/approved path; browser never computes
authoritative money. Delight = ONLY discount: 0.5% of collection, max ₹50,
auto-applied; no coupon/gift-card engine (retired). Payment core to preserve:
server quote → frozen snapshot → atomic inventory reservation → PaymentAttempt →
PAYREF/idempotency → Razorpay → authoritative capture verification → exactly one
Order → Invoice/reconciliation. Website/WhatsApp/Inbox/staff Pay/Commerce
converge here; never trust a browser/provider callback alone. Ledger record:
customer, order, invoice, pricing, payment attempt, provider IDs/status,
reconciliation, payment-request delivery, refund, activity; elevate exceptions
only. Refunds/returns/cancellations need completion (full+partial refunds;
return lifecycle; unpaid-cancel vs paid-cancel/refund vs shipped
return/replacement). Fulfilment inside Order (processing → partially-shipped →
shipped → completed, validated); courier integration NOT complete — truthful
manual tracking only. Preserve atomic inventory reservation.

**SERVICE** — a work queue/resource. Service Request: customer, original order,
Flow submission, payment, forms, documents, appointment, messages, amendments,
resolution, activity. Paid service orders auto-hand-off into Service.

**SHORT LINKS** — not top-level; Communications → Manage → Links. Reuse
ShortLinksTable / LinkClicksTable / URL-shortener. Attach to customer/campaign/
order/invoice/service/general; track purpose/destination/related/creator/created/
expiry/active/clicks. Lifecycle ACTIVE → INACTIVE → RETIRED; prefer deactivate
over hard-delete; inactive shows a safe destination; retain analytics in audit.

**HOME** — Public Home: deep redesign around real journeys with a STATIC core
proposition (no endless rotation). Workspace Home: universal search, actionable
needs-attention queues, start actions, the six areas, recent activity — no
decorative dashboards.

**PLATFORM** — technical ops only (system/Lambda/API health, jobs, provider
health, integrations, deployment/version, failure queues, security/access,
diagnostics, audit). Product config stays with its product.

**DEVICE/MOBILE/APP** — one responsive codebase (Next.js → Web/PWA + Capacitor →
iOS/Android). Target phone/tablet/foldable/desktop; iOS/Android/macOS/Win/Linux;
Safari/Chrome/Firefox/Edge/Samsung current+previous; WKWebView/
SFSafariViewController, Android WebView/Custom Tabs, WhatsApp/IG/FB in-app
browsers. No horizontal scroll from 320px; fluid clamp(); viewport-fit=cover +
env safe areas; dvh/svh/lvh; foldable segments + fallback; ≥44×44 targets;
touch/mouse/pen/keyboard; 200% zoom; reduced motion; light-only color scheme;
semantic a11y; no color-only status; WebView-safe flows; responsive media;
feature detection. Tables → cards/list-detail on small screens. Mobile nav:
Home | Search | Tasks | Me + contextual sticky actions. Continue existing
Capacitor/PWA foundation; audit manifest/icons/service-worker/deep+universal
links/auth-in-WebView/push/uploads/camera/share/downloads/payments/external-
browser/safe-areas/offline/store-readiness. Do not claim store readiness until
gates pass.

**UNIVERSAL SEARCH** — name, phone, Customer ID, email, order, invoice,
payment/reference, service request, short link; plus action search (create
customer, send message, collect payment, create order, show failed sends).

**MIGRATION ORDER** — (1) re-inventory routes/components + live AWS and mark each
capability Live/Partial/Provider-blocked/Config-required/Retire; (2) lock data
contracts; (3) shared responsive design system; (4) Public Home; (5) Workspace
Home/shell; (6) Customers + identity/cleanup/consent; (7) Communications
Inbox+Manage; (8) Commerce Orders+Catalog; (9) Payments Collect+Ledger;
(10) Service; (11) Platform; (12) finish refunds/returns/tracking; (13) migrate
data/identity; (14) redirect old routes; (15) remove duplicates only after
replacements verify; (16) full device/browser/WebView/a11y pass; (17) Capacitor/
PWA/store hardening; (18) full release verification. Do NOT delete the old system
first. Reuse strong backend payment/security/idempotency work.

**VERIFICATION GATES** — not done until: `npm run build` passes (static export is
the real gate); relevant typecheck/lint/tests pass; route/nav/broken-link audit;
~320/375/768/1024/1440; portrait+landscape; no horizontal overflow; 200% zoom;
keyboard-only; reduced motion; safe areas; foldable; target browsers current+prev
where practical; ≥1 WebView context for global layout changes; no clipped
forms/dialogs/tables; no keyboard traps; no fake success controls; no
browser-authoritative pricing; no orphaned real capabilities; old deep links
redirect; backend/provider claims verified from current live state.

**KNOWN LIVE STATE (last verified 2026-10-19 — RE-CHECK):** wecare-checkout live,
CHECKOUT_INITIATION_ENABLED=true, CHECKOUT_MODE=AWS_NATIVE; active
razorpay-webhook/invoice-engine/customer-orders/service-requests/
catalog-management; OrderTable/PaymentAttemptsTable/CommerceKeys/ProductsTable
active; OrderTable customerId-createdAt-v2-index ACTIVE; EventBridge
wecare-commerce-customer-links ENABLED rate(5 min); no sampled recent errors;
payment/checkout core stronger than UI (preserve); WA_CATALOG_ORDERS_ENABLED
false; India SMS = AWS EUM ap-south-1 + TRAI DLT (others us-east-1); India RCS =
Sinch; canonical address = checkoutDeliveryAddress; Delight 0.5%/max ₹50 only
discount, coupon/gift-card retired. Treat as last-known facts, not permanent
truth.

**GENERAL RULE** — do not recreate old structure just because old components
exist. Preserve authoritative backend contracts, security/auth boundaries,
provider integrations, idempotency, immutable financial evidence, customer/
order/payment history. Replace fragmented navigation, duplicate pages, stale fake
controls, competing client calculations, multiple address interpretations,
separate order/payment/channel mini-apps, unsafe/misleading success states. The
final product should feel like one operating system for WECARE.DIGITAL: very few
workspaces, fast mobile navigation, one customer identity, one commerce/payment
model, contextual access to advanced capability.
