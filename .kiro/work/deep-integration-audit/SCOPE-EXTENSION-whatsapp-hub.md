# SCOPE EXTENSION — WhatsApp-first customer-service hub (owner, 2026-10-09)

This extension is BINDING for every remaining step of this workflow (investigate,
design-review, plan, build-loop, finalize). It is additive to the original A–U
integration-audit brief; all original safety rules still bind (fail-closed payments,
no secret reads/`get-secret-value` in any spelling, no gate-enabling, no fake
payment/webhook confirmations, authorized QA recipient `+918100640044` only, the
business sender `+919330994400` must never be a customer identity, read-only live
reads, read→publish→conditional-alias→rollback for any production mutation, stop at
owner/provider boundaries). This phase is primarily DESIGN/AUDIT — do not build or
enable anything that is currently gated off.

## Intended direction (state it, then prove it)
WhatsApp should become the PRIMARY customer-service hub wherever technically,
operationally and securely appropriate; the website remains where auth/recovery/
privacy/document-handling/complex-UI/regulatory/provider limits make web safer or
necessary. Do NOT force everything into WhatsApp and do NOT remove website
functionality merely because a WhatsApp path exists — require proven equivalent
security, reliability and recovery first.

## New required deliverables (in addition to findings.md + answers.md A–U)

### D1 — Homepage + customer-service entry-point map
Inspect the current website/homepage and every customer-service CTA/entry point in
`src/`. Map at least: Sign in, Customer ID, Profile, Address, Email, Phone, Orders,
Order details, Payment status, Invoice/receipt, Submit Request, Request Amendment,
Drop Docs, Vault, Shipments, Leave Review, Customer ideas, Contact/support, Payment,
Service fulfilment. Cite the real `src/...:line` of each CTA and the backend/API it calls.

### D2 — Per-experience classification
Classify each experience: `WHATSAPP NATIVE` / `WHATSAPP + SECURE WEB FALLBACK` /
`WEBSITE ONLY` / `NOT YET SUPPORTED`, with security/identity/payment justification.

### D3 — Website→WhatsApp migration matrix → `outputs/website-to-whatsapp-migration-matrix.md`
Columns: Current website action | Current backend/API | Current WhatsApp capability |
Required Flow/template/message | Identity requirement | Security risk | Payment
requirement | Recommended destination | Implementation state.

### D4 — WhatsApp Customer Service Home design → `outputs/whatsapp-customer-service-architecture.md`
Evaluate whether an EXISTING Flow/resource can be the main entry point before proposing
a new one. If a new one is genuinely warranted, name the candidate
`WD_Customer_Service_Hub_v1` but DO NOT create or publish any Flow. Show the recommended
menu (Profile, Orders, Submit Request, Request Amendment, Drop Docs, Vault, Shipments,
Invoices & Receipts, Leave Review, Contact Support). Must use the permanent verified
customer identity; phone alone never authorizes private data.

### D5 — Profile-in-WhatsApp privacy decision (inside D4 doc)
For Customer ID / Name / Email / phone / billing+shipping address / account status:
decide fully displayed / partially masked / confirmation-only / editable / web-only,
with justification. Evaluate whether Flow screens are safer than plain chat. Profile
data must come from the authoritative backend, never handset-submitted fields.

### D6 — Orders Flow design (inside D4 doc; candidate `WD_Orders_v1`, do not create)
Screens: My Orders list → select order → Order Detail. Per-order ACTIONS gated by
ACTUAL order/service state: View, Get/resend invoice, Get receipt, Pay (only if
genuinely unpaid), Submit request, Request amendment, Upload documents, Open Vault,
Track shipment, Leave review, Contact support. A paid order must NOT show "Pay again";
no Vault exposure without entitlement; invoice retrieval reuses the authoritative
invoice, never mints a second accounting document. Do not expose internal debugging IDs
unless customer-facing use is intended; preserve canonical UUID/public-order-number
relationships internally.

### D7 — Payment state machine → `outputs/whatsapp-payment-state-machine.md`
States: ENTRY → VERIFY_IDENTITY → CHECK_ELIGIBILITY → LOAD_RELEVANT_ORDER/CONTEXT →
SERVER-SIDE PRICE → FREEZE QUOTE → CREATE_OR_REUSE_PAYMENT_ATTEMPT →
RESERVE_OR_REUSE_REFERENCE → SEND ORDER-DETAILS/REVIEW&PAY → PAYMENT_PENDING. Branches:
PAYMENT_VERIFIED, PAYMENT_FAILED, PAYMENT_CANCELLED, PAYMENT_EXPIRED,
CUSTOMER_ABANDONED, MESSAGE_SEND_FAILED, PROVIDER_TIMEOUT, DUPLICATE_CALLBACK,
DUPLICATE_CUSTOMER_TAP, ORDER_CREATION_FAILED_AFTER_PAYMENT,
WIX_WRITEBACK_FAILED_AFTER_PAYMENT, INVOICE_SEND_FAILED_AFTER_PAYMENT,
SERVICE_FLOW_INVITATION_FAILED, FULFILMENT_FAILED. For each state: authoritative record,
allowed retry, customer-facing message, whether a new payment reference is allowed,
whether payment can be resent, whether the customer is charged again, reconciliation
action, idempotency key. GROUND every transition in the ACTUAL current code (checkout +
razorpay webhook + inbound handler), cite `file:line`, and mark anything the code does
NOT handle as a GAP — do not invent behavior. Core principle to verify in code: a
downstream failure after successful payment must NOT re-charge and must leave a
recoverable/idempotent reconciliation state (persist payment success; retry the side
effect idempotently).

### D8 — Overall feasibility verdict
State and justify: fully WhatsApp-native / mostly WhatsApp-native with secure web
fallbacks / hybrid — grounded in current Meta capabilities and current code. Verify
whether embedded Flow-payment is actually supported by the current Meta account vs the
historical "selection → order-details message → Review & Pay → provider confirm → paid
Flow invitation" pattern; do not claim embedded Flow-payment unless proven. If a claim
needs a live Meta token read this run is prohibited from making, mark it
`NOT VERIFIED — META TOKEN READ UNAVAILABLE` and continue.

## Expanded FINAL-REPORT format (finalize step must use this)
`final-report.md` (and `outputs/kiro-deep-audit-2026-10-09.md`) must contain, in order:
Executive status (COMPLETE / ENGINEERING COMPLETE — OWNER QA REQUIRED / PARTIALLY
COMPLETE / BLOCKED + one paragraph); Deep audit findings (ID|Severity|Component|State|
Finding); WhatsApp customer-service feasibility (D8 verdict); Customer Service Home
design (D4 menu); Orders Flow design (D6 screens/data/actions); Payment-start scenario
(D7 state machine); Invoice/receipt flow (create/retrieve/resend rules); Website→
WhatsApp migration (D3 what moves / what stays web); What was already complete; What you
fixed; Tests (exact commands/results); Production state (AWS/Meta/Wix/Flow/payment/
gates); Remaining engineering work; Owner actions; External/provider blockers; Not
verified; Rollback (exact per production change); Next exact action (no vague
"more testing recommended").

## Output file set (create outputs/ dir)
`outputs/kiro-deep-audit-2026-10-09.md`, `outputs/kiro-current-state.json`,
`outputs/whatsapp-customer-service-architecture.md`,
`outputs/whatsapp-payment-state-machine.md`,
`outputs/website-to-whatsapp-migration-matrix.md`. Update authoritative existing
evidence (`docs/whatsapp/service-rollout/live-evidence.json`, `continue-prompt.txt`,
`docs/execution/change-authority-matrix.md`) only with re-verified facts; do not create
competing truth files.
