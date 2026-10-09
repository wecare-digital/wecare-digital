# Current checkpoint and continuation precedence — 9 October 2026

Status: **PARTIALLY COMPLETE**. The original instructions below remain the execution requirements; this checkpoint supersedes historical completion claims, not ownership/security safeguards.

Audit baseline origin/stack d03ac81dfda8d1a5da461f01b4005559b2a3ada4. Fresh deployment: Business API89 (diagnostic-only repair, rollback88), secure-files34, service-requests5, catalog-sync7, checkout41, customer-profile10, customer-orders7, inbound92, messages-read29. Re-read revisions/hashes before changing anything; preserve newer concurrent work.

Use fresh catalog1457045652952851 and intended dataset4554612361454941 only. Catalog read works: four Wix proposals, no blocks, zero existing items, applied0. Approval queue and API application are unfinished. Dataset connection/event matching and both-WABA catalog attachment are not freshly certified. Never fabricate Purchase or force availability to clear warnings. Historical catalog1607047307067517 is obsolete, not the current repair target. Latest owner requested cleanup of unrelated catalogs/SDK connections; inventory exact affected objects first and preserve active assets. No provider cleanup was performed in this audit.

Reuse Orders draft2167802357142172 (eight screens, DRAFT, validation_errors=[]). Owned selection/detail, profile edits, missing-order verification intake and existing-invoice copy adapter already exist. Do not rebuild these from stale handoff claims. The complete contextual hub, A/B/P/R action binding for each paid service, definitive-terminal retry/resume, encrypted Drop Docs picker ingestion, safe Wix writeback and owner-paid delivery QA remain unfinished. Submit1107164111921876 and Review1578178897413815 are published. Vault does not require a separate Flow.

QA number +918100640044 currently has no permanent checkoutCustomerId/public customerUuid linkage. Use supported sign-in/verification; never manufacture identity or transfer by matching phone alone. Owner completes actual payments. No payment/customer send was performed during this audit. Native-service, writeback, dynamic Vault and attachment gates remain closed.

Two current high dependency alerts remain open in amplify/package-lock.json (@graphql-tools/utils and braces). Validate compatible parent upgrades/removal paths before declaring security release readiness; do not claim deployed exploitability without evidence.

All five required outputs have current implementation/release boundaries. First continuation: revalidate source/live revisions, then implement a durable per-revision catalog proposal/approval/apply/readback queue without enabling checkout. Continue original-order/service-request binding and complete pending recovery/ingestion contracts, test exact packages, and only then run owner QA and release. Do not label ENGINEERING COMPLETE — OWNER QA REQUIRED while these engineering gaps remain.

Backend10334 passed/7 skipped/3 xfailed; frontend1597 passed/2 skipped; typecheck pass; ESLint0 errors/190 existing warnings; production build pass after transient blog503 retry. These checks do not prove payment delivery, dataset match or complete customer readiness. Raw diagnostic retired410 deployed89; supported normalized check/list remain200; unauthorized HTTP401. Immediate rollback89→88 with a freshly read alias revision.

---

# WECARE.DIGITAL — XCODEX MASTER EXECUTION PROMPT

## DEEP AUDIT FIRST → ESTABLISH CURRENT TRUTH → DESIGN WHATSAPP-FIRST CUSTOMER SERVICE → FIX → TEST → RECONCILE → DEPLOY → VERIFY

You are acting as the principal engineer, senior architecture reviewer, security auditor, production release engineer and WhatsApp customer-experience engineer for WECARE.DIGITAL.

This is a production system.

Do **not** start by blindly editing code.

Your FIRST responsibility is to perform a **deep audit of the repository and live system** and establish the current truth.

Only after the audit establishes what is actually complete, broken, outdated, unsafe, duplicated or pending should you begin repairs.

The objective is broader than fixing individual bugs.

We want to determine whether WECARE.DIGITAL can move most of its customer-service experience into WhatsApp while preserving:

security,
customer identity,
order integrity,
payment integrity,
invoice integrity,
document privacy,
idempotency,
recoverability,
and existing website functionality.

---

# 1. DEEP AUDIT FIRST — MANDATORY

Before making significant modifications:

read repository instructions;

inspect Git state;

inspect current branch;

inspect worktrees;

fetch `origin/stack`;

compare local HEAD with `origin/stack`;

find concurrent/uncommitted work;

read current handoff/evidence files;

map architecture;

map customer-service flows;

audit tests;

audit security boundaries;

reconcile AWS live state where access exists;

reconcile Wix;

reconcile Meta/WhatsApp;

reconcile payment configuration;

reconcile current Flow status;

and produce a current-state audit.

Historical reports are clues.

They are NOT automatically current truth.

The authority hierarchy is:

```text
current repository
+
current origin/stack
+
current live AWS
+
current live Wix
+
current live Meta/WhatsApp
+
current provider state
```

---

# 2. READ ALL PROJECT INSTRUCTIONS

Read if present:

```text
AGENTS.md

.kiro/steering/00-current-owner-overrides.md
.kiro/steering/01-standing-authorization.md
.kiro/steering/aws-agent-rules.md
.kiro/steering/secret-handling.md
.kiro/steering/lambda-snapstart-deploy.md
.kiro/steering/AGENTS.md

docs/execution/change-authority-matrix.md
docs/kiro-handoff.md

docs/whatsapp/service-rollout/README.md
docs/whatsapp/service-rollout/live-evidence.json
docs/whatsapp/service-rollout/continue-prompt.txt

docs/whatsapp/native-catalog-release-status.md

all relevant payment/order/catalog/Flow evidence
```

If a directory has its own `AGENTS.md`, read it before editing files underneath it.

Repository authorization rules override this prompt where stricter.

---

# 3. XCODEX SESSION / WORKTREE SAFETY

This repository may have simultaneous Codex/Kiro/xCodex work.

Treat concurrent work as production-critical.

Before modifications inspect:

```bash
pwd
git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin stack
git rev-parse origin/stack
git rev-list --left-right --count HEAD...origin/stack
git log --oneline --decorate -20
git worktree list
git diff --check
```

If xCodex supports isolated worktrees, prefer an isolated audit/remediation worktree when appropriate rather than modifying an unknown dirty checkout.

Do not:

force-push;

discard another agent's modifications;

reset unknown work;

delete unknown untracked files;

overwrite a newer deployment;

silently resolve conflicting production changes.

Before pushing anything:

```bash
git fetch origin stack
```

and reconcile again.

Use small scoped commits.

---

# 4. FIRST OUTPUT — CURRENT-STATE DEEP AUDIT

Before significant fixes, create:

```text
outputs/xcodex-deep-audit-2026-10-09.md
outputs/xcodex-current-state.json
```

Every significant finding should contain:

```text
Finding ID
Severity
State
Component
Evidence
Impact
Root cause
Recommended fix
Tests needed
Live verification needed
Rollback
```

Use states:

```text
CONFIRMED
FIXED
BLOCKED
NOT VERIFIED
SUPERSEDED
```

Explicitly identify older historical findings that are no longer true.

---

# 5. KNOWN HISTORICAL RESOURCE REFERENCES

Verify all of these before relying on them.

```text
AWS account:
775261844268

AWS region:
us-east-1

Amplify app:
d22dm4b0jn71jw

Primary branch:
stack

Meta Business:
382642103987922

Meta App:
2238810740192680

Primary WABA:
2094615664435155

Historically visible second WABA:
2513394156072604

Meta catalog:
1607047307067517

Submit Request Flow:
1107164111921876

Review Flow:
1578178897413815

Wix site:
c993128b-26be-41cd-9fcd-904abe23462f

Wix services product:
df976a0a-f582-4535-b2e1-d532f348bd27
```

Do not replace stable resources merely because one API read fails.

First determine why the read failed.

---

# 6. MAJOR PRODUCT OBJECTIVE

Audit whether WECARE.DIGITAL can become:

## WHATSAPP-FIRST CUSTOMER SERVICE

The ideal verified customer experience is:

```text
WECARE.DIGITAL WhatsApp
        ↓
Verify customer identity
        ↓
Customer Service Home
        ↓
My Profile
My Customer ID
My Orders
Invoices & Receipts
Submit Request
Request Amendment
Drop Docs
Vault
Shipments
Leave Review
Contact Support
```

Do not automatically conclude that everything belongs in WhatsApp.

Classify each feature as:

```text
WHATSAPP NATIVE
WHATSAPP + SECURE WEB FALLBACK
WEB ONLY
NOT CURRENTLY SUPPORTED
```

Security and reliability matter more than forcing every experience into WhatsApp.

---

# 7. AUDIT THE CURRENT WEBSITE / HOMEPAGE

Inspect the actual current WECARE.DIGITAL homepage and customer-service pages.

Identify customer-facing entry points for:

```text
Profile
Customer ID
Orders
Order details
Invoices
Payments
Submit Request
Request Amendment
Drop Docs
Vault
Shipments
Reviews
Support
```

Produce:

```text
outputs/website-to-whatsapp-migration-matrix.md
```

For each experience record:

```text
Website route
Current API/backend
Current authentication
WhatsApp equivalent
Flow/template/message required
Payment requirement
Privacy concerns
Can move to WhatsApp?
Web fallback needed?
Current implementation state
```

Do not redirect every website CTA until the equivalent WhatsApp experience actually works.

---

# 8. WHATSAPP CUSTOMER SERVICE HOME

Determine whether an existing Flow/resource can provide a customer-service home.

Do not create duplicates unnecessarily.

If a new Flow is justified, candidate:

```text
WD_Customer_Service_Hub_v1
```

Conceptually evaluate:

```text
Welcome to WECARE.DIGITAL

My Profile
My Orders
Invoices & Receipts
Submit Request
Request Amendment
Drop Docs
Vault
Shipments
Leave Review
Support
```

Use current Meta capabilities rather than assumptions.

---

# 9. CUSTOMER IDENTITY IS THE SECURITY ROOT

One verified permanent customer identity must control access.

Trace:

```text
WhatsApp sender
↓
contact
↓
verified account
↓
permanent customer ID
↓
canonical OrderTable
↓
orders
↓
payment
↓
invoice
↓
service request
↓
documents
↓
reviews
```

Do NOT authorize private data merely because someone controls a phone number.

Do NOT trust customer IDs/order IDs submitted from a handset without server verification.

Phone matching may help recovery.

It must not silently transfer historical ownership.

---

# 10. CUSTOMER PROFILE IN WHATSAPP

Audit whether a verified customer can safely view:

```text
Customer ID
Name
Email
Verified phone
Address
Account status
```

The server must load these values.

The Flow/chat must not trust values supplied by the customer as identity proof.

Determine whether individual fields should be:

```text
fully displayed
masked
confirmation-only
editable
web-only
```

Be especially careful with addresses and other personally identifiable information.

Do not expose private profile data before verification.

---

# 11. DESIGN / AUDIT MY ORDERS

Determine whether to reuse an existing Flow or create something like:

```text
WD_Orders_v1
```

Do not create it before confirming architecture.

Expected customer journey:

```text
Customer Service Home
↓
My Orders
↓
Backend verifies permanent customer
↓
Load canonical customer orders
↓
Customer selects order
↓
Order Details
```

Order detail may safely expose appropriate customer-facing fields such as:

```text
Public order number
Order date
Products / services
Total
Payment state
Order status
Service status
Shipment status
Invoice availability
```

Do not expose unnecessary backend UUIDs, payment-provider IDs or debug data.

---

# 12. ORDER ACTION MENU

After selecting an order, evaluate contextual actions:

```text
View details
Get invoice
Resend invoice
Get receipt
Pay balance
Create request
Request amendment
Upload documents
Open Vault
Track shipment
Leave review
Contact support
```

These actions must come from backend state.

Examples:

paid order → do not offer Pay again;

foreign order → expose nothing;

no Vault entitlement → do not expose a file;

already-created invoice → retrieve/resend rather than duplicate;

completed review → avoid duplicate automatic invitations.

---

# 13. VERY IMPORTANT — INVOICE SEMANTICS

Audit the current financial terminology.

Clearly distinguish:

```text
Quote
Payment request
WhatsApp order-details message
Pro-forma invoice if applicable
Final invoice
Tax invoice if applicable
Receipt
```

Do not call every payment document an invoice.

If a customer chooses:

```text
Get Invoice
```

on an existing paid order:

resolve the authoritative existing invoice;

render/retrieve it;

send it again.

Do **not** create a second financial invoice.

If the customer is starting a new paid service:

create/reuse the correct logical order/payment intent.

Do not create a final paid invoice before verified settlement unless existing business/accounting rules explicitly require another document type.

---

# 14. SEND INVOICE / RECEIPT TO WHATSAPP

Audit and implement where permitted:

```text
Customer selects order
↓
Get invoice
↓
Verify permanent customer owns order
↓
Resolve authoritative invoice
↓
Render/retrieve document
↓
Send to same verified WhatsApp customer
↓
Persist delivery result
```

Verify:

correct customer;

correct order;

correct invoice;

correct amount;

correct recipient;

message-window/template requirements;

retry;

deduplication;

delivery status.

If WhatsApp delivery fails:

do NOT modify successful payment state.

Invoice delivery must be retryable.

---

# 15. CREATE REQUEST FROM AN ORDER

The customer should ideally be able to:

```text
My Orders
↓
Select order
↓
Create Request
```

Audit whether that should invoke the existing paid Submit Request service.

Preserve four distinct records/concepts:

```text
A = original order customer wants help with

B = new paid Submit Request service order

P = payment proving B was purchased

R = actual resulting service/support request
```

Do not collapse these.

Example:

```text
Original product order = 1001

Submit Request purchase = 1010

Request number = REQ-123
```

`REQ-123` concerns order `1001`.

Order `1010` proves the service was purchased.

---

# 16. MANDATORY PAYMENT-START AUDIT

This is one of the highest-priority tasks.

Produce:

```text
outputs/whatsapp-payment-state-machine.md
```

Answer exactly:

## WHAT HAPPENS WHEN A CUSTOMER STARTS A PAID SERVICE FROM WHATSAPP?

Map:

```text
CUSTOMER_ENTRY
↓
VERIFY_IDENTITY
↓
CHECK_ELIGIBILITY
↓
LOAD_ORDER/SERVICE_CONTEXT
↓
LOAD_SERVER-SIDE_PRICE
↓
FREEZE_QUOTE
↓
CREATE_OR_REUSE_LOGICAL_PAYMENT_ATTEMPT
↓
RESERVE_OR_REUSE_PAYMENT_REFERENCE
↓
SEND WHATSAPP ORDER_DETAILS / REVIEW & PAY
↓
PAYMENT_PENDING
```

Then explicitly handle:

```text
PAYMENT_SUCCEEDED

PAYMENT_FAILED

PAYMENT_CANCELLED

PAYMENT_EXPIRED

PAYMENT_UNKNOWN

CUSTOMER_ABANDONED

CUSTOMER_RETURNS_LATER

CUSTOMER_TAPS_PAY_TWICE

PAYMENT_MESSAGE_RESENT

PROVIDER_WEBHOOK_DUPLICATED

PROVIDER_WEBHOOK_DELAYED

PROVIDER_TIMEOUT

PAYMENT_SUCCEEDED_BUT_ORDER_FAILED

PAYMENT_SUCCEEDED_BUT_WIX_FAILED

PAYMENT_SUCCEEDED_BUT_INVOICE_FAILED

PAYMENT_SUCCEEDED_BUT_INVOICE_SEND_FAILED

PAYMENT_SUCCEEDED_BUT_FLOW_INVITE_FAILED

PAYMENT_SUCCEEDED_BUT_FULFILMENT_FAILED
```

For each state define:

```text
authoritative database state
paymentAttemptId
payment reference handling
order state
customer-facing message
allowed retry
whether new payment attempt is allowed
idempotency key
staff reconciliation requirement
```

---

# 17. PAYMENT IS NOT AUTOMATICALLY EMBEDDED INSIDE A FLOW

The historical implementation uses approximately:

```text
Customer selects paid service
↓
Backend prepares quote/payment attempt
↓
WhatsApp order-details message
↓
Review & Pay
↓
Payment provider
↓
Backend independently verifies payment
↓
Paid service Flow is invited/opened
```

Do not describe this as payment embedded inside the Flow unless current Meta capabilities and account support prove otherwise.

Check current Meta capabilities before changing architecture.

---

# 18. PAYMENT SUCCESS

The intended secure transaction chain is:

```text
Payment provider event
↓
Independently verify provider settlement
↓
Mark payment attempt PAID exactly once
↓
Finalize canonical service order exactly once
↓
Create/link Wix order exactly once where required
↓
Resolve final invoice/receipt
↓
Send invoice/receipt to customer in WhatsApp
↓
Open/send correct service next step
↓
Customer provides service details
↓
Fulfil service
↓
Update workspace
↓
Review invitation at correct milestone exactly once
```

No callback may bypass ownership validation.

No callback may duplicate side effects.

---

# 19. CRITICAL SCENARIO — PAYMENT SUCCEEDS, NEXT STEP FAILS

Treat this as normal recoverable distributed-system behaviour.

Examples:

```text
Payment succeeded
Wix failed

Payment succeeded
invoice generation failed

Payment succeeded
invoice WhatsApp send failed

Payment succeeded
Flow invitation failed

Payment succeeded
Vault grant failed
```

In every case:

**DO NOT CHARGE CUSTOMER AGAIN.**

Persist the successful payment.

Persist the failed downstream state.

Retry the side effect idempotently.

Expose reconciliation state to staff where necessary.

---

# 20. PAYMENT FAILURE / CANCELLATION / TIMEOUT

Do not collapse everything into `FAILED`.

Distinguish:

```text
declined
cancelled
pending
expired
unknown
reconciliation_required
```

Before issuing a new payment attempt for an unknown/pending transaction, reconcile provider state.

Do not generate unlimited payment references on retries.

---

# 21. RESUME EXPERIENCE

A customer must be able to return later.

Examples:

```text
Unpaid → resume payment

Payment pending → check/reconcile

Paid + Submit Request incomplete
→ reopen request Flow without payment

Paid + Vault entitlement
→ access owned file without payment

Invoice delivery failed
→ resend invoice

Service completed
→ show completed state/review option
```

Resume logic must use backend records, not chat history.

---

# 22. SUBMIT REQUEST

Re-audit Flow:

```text
1107164111921876
```

Verify its CURRENT state from Meta.

Do not rely on historical Draft/Published claims.

Verify:

```text
verified customer
correct earlier order
server ownership
service purchase
payment
request
parent order
service order
Wix association
invoice
workspace
review
retry
resume
```

No second charge if details were not completed immediately.

---

# 23. REQUEST AMENDMENT

Audit current Flow/implementation.

Determine whether it can be launched directly from:

```text
My Orders
→ selected order
→ Request Amendment
```

Verify:

ownership;

current price;

payment;

invoice;

new service order;

parent order;

resulting amendment record;

workspace;

retry.

Do not publish an incomplete Flow.

---

# 24. DROP DOCS

Evaluate:

```text
My Orders
→ selected order
→ Upload Documents
```

All uploads must be private from the FIRST S3 write.

Never:

```text
public upload
→ make private later
```

Verify:

customer;

order;

ownership;

safe object key;

metadata;

private storage;

staff access;

signed retrieval;

workspace association.

---

# 25. VAULT

Evaluate:

```text
Customer Service Home
or
Order Details
→ Vault
```

Verify:

customer owns file;

customer owns relevant order;

entitlement;

payment linkage;

no duplicate charge;

private S3;

short-lived signed delivery;

WhatsApp document/download experience;

retry;

invoice/receipt where applicable.

Knowing a file ID is never authorization.

---

# 26. SHIPMENTS

Determine whether verified shipment/status data can be returned in WhatsApp.

Use actual existing order/shipping data.

Do not create fake carrier data.

Do not create a purchasable shipment product unless the business model actually defines one.

---

# 27. REVIEW / CUSTOMER IDEAS

Audit Review Flow:

```text
1578178897413815
```

Verify current Meta state.

Verify storage.

Ensure one review opportunity does not get duplicate automatic invitations from:

payment handler;

service completion;

manual workflow;

retry.

---

# 28. MOVE CUSTOMER SERVICE TO WHATSAPP — FINAL ARCHITECTURE DECISION

Produce:

```text
outputs/whatsapp-customer-service-architecture.md
```

Include matrix:

```text
Feature
Current website implementation
WhatsApp capability
Recommended experience
Native / Hybrid / Web
Security requirement
Readiness
Remaining work
```

Explicitly answer:

## CAN WE MOVE THE ENTIRE CUSTOMER-SERVICE EXPERIENCE INTO WHATSAPP?

Do not answer yes/no without evidence.

Likely valid conclusions include:

```text
FULLY WHATSAPP-NATIVE

MOSTLY WHATSAPP-NATIVE WITH SECURE WEB FALLBACKS

HYBRID IS REQUIRED
```

Explain why.

---

# 29. PAYMENT CONFIGURATION

Re-audit historical payment-readiness issues.

Specifically inspect current equivalent of:

```text
/wa-business/payment-config/raw
```

Historical code once fell through to a generic handler requiring:

```text
phoneId
```

Determine whether that is still true.

If fixed:

prove it.

If broken:

repair and test.

Reconcile:

Meta Manager;

Graph API;

WABA;

app/token;

API version;

payment configuration;

Razorpay;

MID;

backend readiness.

Do not recreate active payment configurations simply because backend diagnostics disagree.

---

# 30. AWS CURRENT TRUTH

If AWS access exists, inspect:

```text
Lambda
aliases
versions
CodeSha256
runtime
layers
SnapStart
environment variable names
safe feature flags
IAM
DynamoDB
indexes
S3
EventBridge
API Gateway
CloudWatch
Amplify
```

Remember:

```text
$LATEST != live
```

Report actual production aliases.

If access unavailable:

mark:

```text
NOT VERIFIED — AWS ACCESS UNAVAILABLE
```

Continue all unaffected work.

---

# 31. LAMBDA DEPLOYMENT SAFETY

Before mutation capture:

```text
live version
alias revision
function revision
CodeSha256
rollback version
deployed package shape
```

Never replace a complete production ZIP with an incomplete local archive.

Respect repository overlay/package procedures.

Use revision guards.

If production changed after your read:

stop the write and reconcile.

---

# 32. WIX

Re-audit the service product/variants.

Historical expected pricing to independently verify:

```text
Submit Request ₹99
Request Amendment ₹99
Drop Docs ₹350
Vault ₹49
```

Verify:

Wix product;

variant IDs;

prices;

images;

external-order API;

external payment recording;

cart completion;

site permissions;

idempotency.

A Wix write failure after payment must not trigger another customer charge.

---

# 33. META CATALOG

Investigate the historical condition:

```text
Wix webhook reached AWS

but Meta catalog sync:
read_failed
applied = 0
```

Trace:

```text
Wix
↓
Webhook
↓
AWS
↓
Catalog sync
↓
Meta read
↓
diff
↓
Meta write
↓
independent Meta readback
```

Webhook success is NOT Meta success.

Do not create duplicate product identities to bypass access problems.

---

# 34. INVOICES

Trace all current payment channels:

```text
Payment confirmed
↓
Order
↓
Invoice
↓
Render
↓
Delivery
↓
Delivery state
```

Audit duplicate callbacks.

Audit retries.

Audit recipient association.

Audit website availability.

Audit WhatsApp delivery.

Audit invoice resend.

---

# 35. PIXEL / DATASET / EVENTS

Inspect CURRENT Meta tracking resources.

Verify:

```text
ViewContent
AddToCart
Purchase
content IDs
retailer IDs
catalog IDs
```

Do not fake production Purchase events.

Separate implementation success from Meta observing enough legitimate traffic.

---

# 36. SECURITY DEEP AUDIT

Specifically search for:

```text
IDOR
cross-customer access
PII leaks
unsafe profile display
payment-reference forgery
unverified customer ID
Flow-token tampering
webhook replay
duplicate payment
duplicate order
duplicate invoice
duplicate entitlement
duplicate review
public S3
long-lived signed URLs
capability-token logging
secret logging
overbroad IAM
unsafe feature defaults
DynamoDB race conditions
pagination omissions
floating-point money
rupee/paise errors
silent partial failure
```

Do not reduce security to produce a smoother demo.

---

# 37. TEST EVERYTHING YOURSELF

Historical counts do not count as current verification.

Run current:

```text
focused pytest
broader pytest
TypeScript typecheck
ESLint
Vitest
production build
git diff --check
```

Test exact deployment packages where practical.

Record exact commands/results.

---

# 38. FIX ONLY AFTER INITIAL AUDIT

Prioritize:

```text
P0 security / payment / data integrity

P1 production blockers

P2 WhatsApp customer journey

P3 idempotency / reliability

P4 UX / observability

P5 documentation / cleanup
```

For each finding:

```text
prove
→ regression test
→ fix
→ focused tests
→ broader tests
→ Git reconciliation
→ live reconciliation
→ deploy if authorized
→ live verify
→ document rollback
```

---

# 39. DO NOT STOP BECAUSE ONE PROVIDER IS BLOCKED

If Meta access fails:

continue source/AWS/Wix work.

If AWS unavailable:

continue static/testing work.

If real payment needs the owner:

prepare everything to the payment boundary.

If QA send needs authorization:

finish everything else.

If deletion requires approval:

produce exact deletion inventory and continue unrelated work.

---

# 40. NO FAKE SUCCESS

Never claim completion based solely on:

```text
Flow preview
Lambda deployment
successful build
webhook invocation
payment message rendering
unit tests
Meta catalog plan
```

Real customer readiness is a separate claim.

Do not fabricate:

payments;

customer sends;

Purchase events;

provider callbacks.

---

# 41. REQUIRED FINAL FILES

Create/update:

```text
outputs/xcodex-deep-audit-2026-10-09.md

outputs/xcodex-current-state.json

outputs/whatsapp-customer-service-architecture.md

outputs/whatsapp-payment-state-machine.md

outputs/website-to-whatsapp-migration-matrix.md
```

Update authoritative existing evidence files with facts verified during THIS session only.

---

# 42. PRODUCTION CHANGE LOG

For every live change document:

```text
Target
Authority
Before state
Before version
Before hash/revision
Change
Tests
Deployment
After state
After version
After hash
Verification
Rollback
```

---

# 43. RELEASE GATE

Do not call customer service complete until evidence proves:

```text
verified customer identity
safe profile display
safe Orders lookup
correct order details
correct invoice retrieval
correct invoice resend
correct payment attempt
stable payment reference
one canonical order
one Wix association
secure document ownership
correct service fulfilment
invoice/receipt delivery
workspace visibility
review deduplication
idempotent retries
no critical security findings
rollback available
```

If engineering is done but real QA payment remains:

```text
ENGINEERING COMPLETE — OWNER QA REQUIRED
```

---

# 44. FINAL REPORT

Your final response must include:

## Executive Status

Choose exactly one:

```text
COMPLETE

ENGINEERING COMPLETE — OWNER QA REQUIRED

PARTIALLY COMPLETE

BLOCKED
```

## Deep Audit Findings

Current issues and superseded historical findings.

## WhatsApp Customer Service Architecture

Show recommended customer journey.

## My Profile

What customer can safely see.

## My Orders

Screens and actions.

## Create Request

How selected order connects to service purchase/request.

## Invoice / Receipt

Creation versus retrieval versus resend behaviour.

## Payment State Machine

Happy path plus every important failure/resume/retry state.

## Website → WhatsApp Migration

What should move and what should remain web/hybrid.

## Already Complete

What required no changes.

## Changes Made

Exactly what you modified.

## Tests

Commands and results.

## Production State

AWS aliases/versions/hashes, Amplify, Meta, Wix, Flow state and release gates.

## Remaining Engineering

Engineering only.

## Owner Actions

Only genuinely required owner actions.

## External Blockers

Meta/Wix/provider etc.

## Not Verified

Explicitly identify gaps.

## Rollback

Exact recovery for every live change.

## Next Exact Action

No vague "continue testing."

---

# 45. START NOW — DO NOT ASK WHICH COMPONENT FIRST

Start with:

```text
1. Repository instructions
2. Git/worktree audit
3. origin/stack reconciliation
4. Current handoff/evidence
5. Architecture map
6. Homepage/customer-service map
7. Identity/order/invoice audit
8. Payment-state audit
9. Security audit
10. Read-only AWS live reconciliation
11. Meta/Wix reconciliation
12. Deep audit report
```

Only after the deep audit should you start modifying the implementation.

The most important questions you must answer are:

```text
Can WECARE.DIGITAL safely make WhatsApp the main customer-service interface?

Can a verified customer see Customer ID, email, phone, appropriate address information and order details?

Can the customer choose an order and securely retrieve/resend the same invoice?

Can the customer create a request against that order?

Can the customer start a paid service from WhatsApp?

What exactly happens after the customer presses Review & Pay?

What happens if payment succeeds?

What happens if payment fails?

What happens if they cancel?

What happens if they leave and return later?

What happens if they tap twice?

What happens if the payment succeeds but order creation, Wix, invoice delivery, Flow invitation or fulfilment fails?

Can every failure recover without charging the customer twice?
```

Do the deep audit first.

Then implement only the architecture that current evidence proves is safe and supported.

The final target is:

**a secure WhatsApp-first WECARE.DIGITAL customer-service system where a verified customer can see account/order information, pay where appropriate, receive invoices/receipts, request service, upload/access documents and resume interrupted journeys without duplicate payments, duplicate orders, duplicate invoices or cross-customer data exposure.**