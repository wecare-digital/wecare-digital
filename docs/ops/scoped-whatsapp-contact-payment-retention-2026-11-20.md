# Scoped WhatsApp contact and payment retention policy (2026-11-20)

**Status:** Policy change pending review and deployment. This document does not run a cleanup job or disable existing backend refusal to perform irreversible contact erasure.

## Purpose

Support operator requests to retain a specifically identified WhatsApp/CRM contact and all Razorpay/payment transaction evidence while reviewing other contacts and messages for cleanup. This is not permission to indiscriminately delete everyone else.

## Records that must be retained

1. **Selected contact and conversation.** Match the selected customer by canonical ContactsTable identity, exact full phone, business-scoped WhatsApp BSUID and verified identity/merge linkage. Names and truncated UI identifiers are not proof of identity; multiple same-name contacts are distinct until proven otherwise. Keep its identity, all messages, media, conversation context, and relationship metadata. Store the selection and approval in private audited configuration, **never in public GitHub source**.
2. **Financial evidence across all customers.** Protect legally required invoices, orders, payment attempts, captured payments, refunds, Razorpay provider IDs, payment requests, signed webhook evidence, reconciliation, dispute history, and audit/idempotency records, together with minimum necessary identity links. The payment hold applies regardless of whether the customer is the specifically selected contact.
3. **Transaction-related communications.** Protect WhatsApp messages and necessary media that relate to payment requests/links, receipts, invoices, orders, refunds, disputes and reconciliations. Use references such as paymentReferenceId, invoice/order/payment IDs and provider correlation plus relevant context. Keyword matching or lack of an ID is not sufficient to prove a message nonfinancial.
4. **Cross-system copies.** Assess DynamoDB records, S3 versions, Meta WhatsApp contact book and retained events, Razorpay/provider records, backups and exports separately. Do not claim a local deletion removed records at external providers.

## Eligibility and operations

- Classify each candidate as OPERATOR_HOLD, FINANCIAL_RETENTION, LEGAL_OR_IDENTITY_LOCK, REVIEW_REQUIRED or ELIGIBLE_FOR_APPROVED_ACTION. Unknown or ambiguous identity, unreadable data, uncertain payment linkage or incomplete inventory always means REVIEW_REQUIRED.
- Today, the existing **reversible Archive** is available for individually assessed, unlocked and otherwise eligible contacts with an operator reason. Archive retains contact identity and history. The backend refuses archive on locked contacts. The repository now dispatches approved Admin/MFA erasure requests to an independently deployed coordinator; without a configured coordinator the API returns ERASURE_COORDINATOR_UNAVAILABLE and does not delete data. The production Lambda must be deployed separately before the updated response can appear live.
- Do not bypass locks, legal/financial retention checks, delete records directly from DynamoDB, delete guessed S3 paths, bulk delete-all-except-one, or remove customer identities while their payment evidence still depends on them.
- Before future permanent cleanup, require a cross-service exact-key and S3-object-version dry run; a reviewed retention/legal decision; operator approval with MFA; a writer-fencing lease; audited, resumable deletion; and reconciliation of every dependent record. Any partial state must report a refusal rather than success.

## TTL gap verified in live AWS (2026-11-20)

DynamoDB TTL is **enabled** on expiresAt for MessagesTable, WhatsAppInboundTable and WhatsAppOutboundTable. TTL is **disabled** for PaymentsTable, PaymentAttemptsTable and InvoicesTable. A skip-manual-deletion rule alone does not prevent payment-related WhatsApp messages from expiring. To claim a durable hold, either preserve the necessary payment communication in an approved non-expiring evidence store with authenticated reference links, or implement an explicitly reviewed, minimized TTL exception for relevant new and existing messages. Do not globally disable chat retention limits without legal and privacy approval.

## Acceptance gates

Before deploying cleanup logic, prove that the exact selected contact survives, same-name contacts are not conflated, payment provenance for every customer remains reconcilable, transaction evidence survives TTL or has been copied to its approved durable retention location, locks remain effective, unverified records never enter deletion candidates, and outputs report exact retained, eligible, attempted, failed and reconciled counts. This document alone triggers no mutation or rollout.
