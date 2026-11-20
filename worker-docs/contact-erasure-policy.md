# Contact and message erasure policy — selective retention and audited execution

**Status:** Engineering and operations control policy, updated 20 November 2026. This policy defines when a future, separately approved erasure workflow may delete customer data. It does **not** activate deletion, override the public Privacy Policy, waive statutory retention, grant operator privileges, or change a deployed API.

**Current production gate:** Until the cross-service coordinator, approvals, verified identity mapping, write fences and post-deletion verification in this policy exist, `core/contacts` must continue to return `CONTACT_ERASURE_NOT_READY`. Archiving is a separate, reversible visibility change. The existing `system-cleanup` protection for customer, contact, message, payment and audit tables must not be relaxed to accomplish an erasure request.

## 1. Permitted outcomes and decision policy

An authorized request may ask for a named customer's data to be erased, or for a **selective purge that preserves one or more specifically identified contacts and their histories**. Requests to "delete everyone except this contact" do not by themselves grant rights to erase other people's personal data or finance records.

For each data subject and record family, assess legal basis, authorization, applicable retention, disputes, locks and ownership. An eligible record may be erased only after the completed controls below. Otherwise keep it under an explicit retention basis or use a reversible staff-directory archive where authorized. A protected contact and its message, consent, order, invoice, payment and reconciliation history must never be swept into the deletion set.

The final outcome is one of `ERASED`, `PARTIAL_REVIEW_REQUIRED`, `RETAINED_BY_POLICY` or `BLOCKED`. Do not label a hidden/archived row, a DynamoDB delete marker, or a completed batch as full erasure. The public Privacy Policy and legal rights remain authoritative; counsel/privacy approval is required before implementing a new erasure basis.

## 2. Identity, preservation set and scope

1. **Build a private request manifest.** Record requester authority, case/reference ID, affected systems, purpose, retention review, explicit retained-contact identity and approved record IDs in an access-controlled audit store. Do **not** commit names, phone numbers, WhatsApp IDs, public customer IDs or transaction details to this repository.
2. **Verify the canonical person.** Resolve `ContactsTable.id`, CRM `contactId`, public-facing display IDs, Subscriber ID, `checkoutCustomerId`, customer UUID, scoped `IdentityClaimsTable` BSUID/WA-ID identity, normalized verified phone, merged/archived aliases and customer Cognito subject. A public display identifier is **not** a DynamoDB primary key; a name alone is not a safe join. Conflicting or missing identity evidence blocks that part of the request.
3. **Freeze the exact preservation set.** Record immutable primary keys and checksums for every protected contact and existing message, including inbound and outbound WhatsApp, AI standby/thread history, images and documents, plus linked orders, invoices, invoice items/assets, captured payments, payment attempts, refunds, delivery logs, entitlements, commerce keys and audit evidence. Store counts for review, but **do not treat a prior count as an upper bound**: additional legitimate messages or financial events arriving before the deletion fence must be preserved.
4. **Enumerate, do not infer, the deletion set.** Generate an explicit, independently reviewed list of per-record primary keys. Never run a scan-based `delete all where contactId != protectedId`, table truncation, wildcard prefix deletion, or a global `clear-all` against customer history. Each candidate must be linked to an authorized data subject and supported deletion basis. Unlinked, anonymous, unknown-owner or ambiguous records stay out of the delete set pending review.
5. **Protect unrelated financial records.** A record outside the protected contact's verified payment linkage is *not* thereby disposable. Preserve legally required invoices, PaymentsTable records, PaymentAttemptsTable rows, OrderTable entries, receipts, refunds, Razorpay reconciliation/webhook evidence, audit logs and associated identity references for **all** relevant customers. Where lawful and approved, remove only non-required personal fields without breaking traceability.

## 3. Required cross-service inventory

The reviewed manifest must enumerate every direct and indirect reference, not merely the two inbox tables:

- **Identity:** `ContactsTable`, `IdentityClaimsTable`, `CustomerSessionsTable`, customer Cognito and identity-merging aliases.
- **Messages and routing:** `MessagesTable`, `WhatsAppInboundTable`, `WhatsAppOutboundTable`, `ThreadOwnershipTable`, voice/SMS/email records, `ScheduledMessagesTable`, `BulkRecipientsTable`, `DLQMessagesTable`, status/retry queues, and Meta WhatsApp/AI-managed conversation copies.
- **Service and CRM:** `FlowSubmissionTable`, `CrmActivities`, CRM leads/opportunities, support requests, recordings, form submissions, delivery artifacts and consent evidence.
- **Financial and fulfillment:** `OrderTable`, `InvoicesTable`, `InvoiceItemsTable`, `InvoiceAssetsTable`, `InvoiceDeliveryLogTable`, `PaymentsTable`, `PaymentAttemptsTable`, commerce idempotency keys, documents and download grants.
- **Media:** the versioned S3 bucket, its private WhatsApp images, attachments and invoice assets, and external provider media. For each proven-owned object use `ListObjectVersions`, enumerate current versions and every **delete marker**, and check Object Lock, legal hold, KMS, backups and CDN copies. Never derive ownership from a filename or broad S3 prefix.

An unreadable table, incomplete pagination, conflicting identity claim, unavailable external deletion endpoint, or unexamined S3 version makes the inventory **incomplete**. Do not delete first and reconcile later.

## 4. Authorization, execution and rollback

**Before execution** obtain an Operator-authenticated request with fresh MFA, a separately recorded privacy/legal retention decision, and independent approval by a second authorized reviewer for any bulk/multi-person deletion. Use a short-lived, single-use confirmation token tied to the exact manifest hash, affected identities and counts. A chat instruction or a repository policy edit is not itself an execution approval.

1. Produce a **read-only dry run** with exact key inventories and a before/after preservation report. Independently verify that no proposed contact/message ID belongs to the protected identity or to a legally retained financial dependency. Recheck every candidate against current state immediately before action.
2. Take and verify point-in-time backups where applicable; test a realistic restore. Backups are not a license to delete unlawfully, and backup-retention periods must be disclosed rather than called immediate erasure.
3. Acquire a durable idempotency/erasure lease, conditional on the approved manifest revision; **fence all writers** (inbound WhatsApp, AI standby projection, checkout, CRM imports, flow submissions, automation/retries) from recreating a subject while the operation runs. Protect ongoing transactions.
4. Execute a bounded, idempotent, resumable per-subject coordinator with dedicated least-privilege roles. Conditional DynamoDB deletes require exact key/version expectations. Versioned media requires exact object and version identifiers. Do not bypass `core/contacts` deletion refusal or `system-cleanup` safeguards by direct console/SDK bulk deletion.
5. Reconcile per-record outcomes and external-provider receipts, then independently read back protected contacts, **all** preserved messages and payment evidence. Release an identity claim or customer Cognito session only when all authorized dependencies are confirmed erased and no retention/legal lock remains.
6. Record approvals, affected row counts, retained legal dependencies, errors, checkpoint, actor and verification evidence in immutable/restricted audit logs. Do not place personal data or payment credentials in public CI logs or commits. Stop on any mismatch; resume only after review.
7. Report `ERASED` only when the complete authorized scope is proven removed. Otherwise report `PARTIAL_REVIEW_REQUIRED`, `RETAINED_BY_POLICY` or `BLOCKED` with outstanding systems and deadlines, not "success".

## 5. Release requirements and current limitation

Implement the erasure coordinator, ownership proofs, least-privilege IAM, legal hold/retention decisions, write fencing, version-aware S3 handling, complete inventory and failure recovery **before** any runtime switch that allows permanent deletion. Add tests proving (a) the protected contact and all its messages survive, (b) other customers' financial evidence is retained, (c) aliases/unlinked records block unsafe joins, (d) stale manifests and concurrent writes fail closed, and (e) partial provider/S3 failures never return `ERASED`.

Do not modify the customer-facing Privacy Policy without separate legal review. This document is an internal implementation policy and must not be presented as approval to destroy production data. As of this revision, the audited cross-service erasure coordinator is **not deployed** and no bulk erasure is authorized by this document.
