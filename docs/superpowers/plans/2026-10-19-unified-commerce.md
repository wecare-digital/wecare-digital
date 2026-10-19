# Unified Commerce Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. User explicitly approved autonomous execution of the complete sequence.

**Goal:** Complete existing order projection and verified ownership across website and WhatsApp.
**Architecture:** Reuse shared payment and identity stores, extract resumable invoice projection, and attach eligible historical orders only after a proven account/contact binding. Migrate the read index beside its predecessor.
**Tech Stack:** Python 3.12 Lambda, DynamoDB, Next.js, pytest, AWS MCP.
**Spec:** docs/superpowers/specs/2026-10-19-unified-commerce.md

## Global Constraints
- One existing OrderTable and ContactsTable; integer INR paise.
- No new financial transaction, replacement claim, or outbound message during recovery.
- No fabricated phone verification; no cross-account ownership transfer.
- Isolated checkout; preserve original concurrent edits.

## Review Focus
- Duplicate webhook/recovery preserves fulfillment and order identity.
- Unverified/mismatched/deleted contact never links orders.
- Pagination and partial failure are retryable without reporting false completion.
- Existing index remains serving until replacement is ACTIVE.
- Recovery cannot accept forged provider/order evidence.

### Task 1: Resumable invoice projection
Files: shared ecommerce/paid_invoice_order.py, razorpay-webhook/handler.py, tests/test_paid_invoice_order.py, IAM-only recovery arm in razorpay-webhook/handler.py.
Interface: materialize(invoices, items, contacts, attempts, keys, orders, reference_id, now) -> order summary; requires saved matching verified evidence and existing claim.
- [ ] Add failing tests for UUID propagation, exact evidence, existing claim, pagination, replay and fulfillment preservation.
- [ ] Implement shared materialization and delegate the webhook/private recovery action to it.
- [ ] Run targeted tests and commit.

### Task 2: Verified historical ownership link
Files: shared ecommerce/customer_order_link.py, auth/customer-profile/handler.py, scripts/provision_customer_profile.py, tests/test_customer_order_link.py.
Interface: link(orders, contact, customer_id) -> number promoted; reads proven contact ownership, conditionally promotes only eligible contact-owned rows.
- [ ] Add failing behavioral tests for verified owner, mismatched/deleted contact, pagination, races and replay.
- [ ] Wire successful profile save to the shared linker and add narrowly scoped IAM grants.
- [ ] Run identity, profile and IAM tests and commit.

### Task 3: History index and regression verification
Files: scripts/provision_customer_orders.py, tests/test_customer_orders_iam.py, tests/test_payment_reconciliation_safety.py.
- [ ] Add failing projection assertion covering channel and customerUuid.
- [ ] Include both attributes in v2; repair stale invoice validation fixture without weakening validation.
- [ ] Run full Python suite and relevant frontend tests; inspect changes and commit.

### Task 4: Deploy, migrate and recover
- [ ] Snapshot current aliases/index/IAM and build deterministic packages.
- [ ] Create v2 and scoped grants using AWS MCP; wait ACTIVE; configure reader index.
- [ ] Deploy/publish affected handlers with IAM-only recovery; verify immutable live hashes.
- [ ] Invoke recovery for the sole stored verified 467-paise attempt; replay to prove identity/fulfillment stability.
- [ ] Verify invoice, attempt, contact, staff/Flow and authenticated history index behavior. Report any genuine remaining human verification requirement.
- [ ] Save release evidence and push an isolated reviewable GitHub branch/PR.
