# Contact deletion integrity — cross-service inventory and release gate (2026-11-04)

## Current safety contract

**Never equate removing a contact from /ws/customers with erasing all personal data.**
The existing Contacts Lambda DELETE tombstoned the contact row, retained phone/email
identity claims and references, and left S3 data and other stores untouched. Its
historical hard-delete branch was disabled and covered only two WhatsApp message
tables. That code also had an unowned S3 filename-prefix fallback.

This change intentionally makes contact DELETE **refuse with
`CONTACT_ERASURE_NOT_READY`** after existing identity-merge, legal-lock and
financial-linkage guards. Only the existing reversible **Archive** action may hide
a record from ordinary staff lists. This is a protective intermediate state,
not a claim that contact erasure has been implemented. Neither GET nor POST
nor the independent customer F001 Subscribe/checkout flow is changed.

## Read-only AWS inventory (4 November 2026)

The following DynamoDB stores exist in `us-east-1`, and can contain direct
customer references, indirect references or material needed to prove erasure.
**Existence does not imply a particular record has data in every store.**
The registry below is a checklist, not permission to truncate, scan indiscriminately
or erase the store.

| Category | Tables / relationships to investigate |
| --- | --- |
| Person and strong identity | `ContactsTable` (`id`; `phone-index`, `email-index`, `bsuid-index`), `IdentityClaimsTable` (`claimKey`), `CustomerSessionsTable` (`sidHash`) |
| Messages and scheduled communications | `MessagesTable` (`contactId-index`), `WhatsAppInboundTable`, `WhatsAppOutboundTable`, `WhatsAppVoiceTable`, `WhatsAppCallingTable`, `VoiceAwsTable`, `VoiceCDRTable`, `ScheduledMessagesTable`, `BulkRecipientsTable`, `DLQMessagesTable` |
| Forms, status and engagement | `FlowDraftTable`, `FlowLogTable`, `FlowSubmissionTable`, `RequestStatusHistoryTable`, `ServiceRequestsTable` (`customerId-createdAt-index`), `CrmActivities` (`contactId-at-index`), `CrmLeads`, `CrmOpportunities` (both `contactId-createdAt-index`) |
| Documents and downloads | `DocumentTable` (`customerPhone`, `orderId` indexes), `DocumentHistoryTable`, `DownloadGrantsTable` (`order-index`), plus associated private S3 objects |
| Carts / checkout | `CartTable` (`customerId-updatedAt-index`), `OrderTable` (`customerId-createdAt*`, `customerPhone` indexes) |
| Financial / potentially legally retained | `InvoicesTable` (`contactId-index`), `InvoiceItemsTable`, `InvoiceAssetsTable`, `InvoiceDeliveryLogTable`, `PaymentAttemptsTable`, `PaymentsTable`, and immutable commerce-idempotency data. **Do not erase statutory invoices, captured payments or audit evidence.** |

Also verify **customer Cognito identity and session state** (distinct from the
staff Cognito pool), any third-party provider identifiers and remote retention
(Meta WhatsApp contact book/BSUID, SMS/email/voice/payment providers),
CloudWatch/audit logging, exports, backups and DynamoDB PITR.

### S3 inventory and versioning

The active media bucket is `wecare-digital-get`, with versioning **Enabled**
as verified from AWS `GetBucketVersioning` on 2026-11-04. Media paths are
defined in `lambda_utils.media_paths`; relevant private customer artifacts
can be under `secure/u/` and `secure/d/public/` (including WhatsApp media,
receipts, invoice/customer images, drop-docs, service requests and transcriptions).
Some old DynamoDB rows store legacy keys that `media_paths.canonical` remaps.

A normal `DeleteObject` on a versioned bucket normally inserts a **delete
marker**. Noncurrent versions may still contain the person's data. A complete
erasure worker must enumerate **all exact object versions and delete markers**
and delete only keys proven owned by the contact and approved for erasure.
Handle object locks / legal hold, retention rules, KMS and backups as explicit
blockers. **Never** delete adjacent keys based on a filename or prefix guess:
catalog, template, invoice and shared assets might have similar prefixes.
CDN caches and any external copies also need a separately documented policy.

## Required design before enabling permanent erasure

1. **Admin approval + MFA + scoped intent.** Distinguish ordinary archive,
   personal-data erasure and statutory retention. Require a dry-run impact
   preview, actor identity, evidence, a one-use confirmation token and audit.
2. **Resolve one canonical identity.** Reconcile `contactId`, public customer
   display ID, customer UUID, checkout customer ID, strong phone/email claims,
   BSUID/parent BSUID and verified Cognito subject. Detect merged aliases.
   Missing/ambiguous references **block**, never authorize guessing.
3. **Inventory every dependency** with exact primary keys and S3 object
   versions. Prefer audited GSIs and bounded pagination; tables without the
   necessary index need an explicitly reviewed scan strategy. Include indirect
   links through order IDs and document IDs. Any unreviewed subsystem makes
   `complete=false`.
4. **Check statutory and operational retention before mutation.** The
   `contact_payment_links` and `contact_lock` guards remain authoritative.
   Preserve legally required records; where lawful, separately anonymize
   personal fields while keeping financial integrity. Do not delete invoices,
   payment trails or consent evidence merely to free a phone number.
5. **Acquire a durable, conditional erasure lease and fence *all* writers.**
   WhatsApp ingress, F001 Flow saves, website checkout, CRM imports and message
   workers must not recreate the customer during purge. A simple one-time
   frontend snapshot cannot prevent races.
6. **Execute an idempotent, resumable coordinator** (for example Step Functions
   plus a dedicated restricted worker role) across audited record keys and
   exact S3 object versions. Each stage records counts, refusals, retries and
   checkpoints. Never use a Lambda 60-second request as a best-effort cascade.
7. **Reconcile before releasing strong identities.** Check that no dependent
   record or S3 version remains except explicitly retained legal evidence,
   and prevent stale reader joins. Release `IdentityClaimsTable` claims
   conditionally **only after** full permitted erasure, never before or on
   partial failure. Deprovision customer Cognito sessions/users only on proof
   of ownership and authorization.
8. **Return explicit outcomes**: `ERASED`, `PARTIAL_REVIEW_REQUIRED` or
   `RETAINED_BY_POLICY`; never return a successful erasure response when
   any step is unconfirmed. Do not log personal data in erasure telemetry.
   Ensure CloudWatch retention, backups and external-provider limits are
   disclosed rather than falsely counted as immediately erased.

## UI and runtime behavior in this change

- `/ws/customers` and legacy `/workspace/customers` show Archive, but not
  an actionable `Delete identity` button. A disabled erasure label explains
  the missing lifecycle functionality.
- Contacts Lambda `DELETE` fails closed (after existing legal/financial
  refusals). Direct API callers cannot create new partial soft-delete
  tombstones once the separately deployed Lambda version is active.
- Single-message delete no longer searches nearby S3 filename prefixes or
  reports DynamoDB deletion success after an exception. Its response explicitly
  warns that versioned media may remain; it is **not** the contact-erasure job.
- **There is no automatic/live purge in this PR**. Deploying a complete erasure
  coordinator requires dedicated security, legal, data retention and IAM review.

## Verification / rollout

TypeScript, lint, Node and Python tests must pass; test only fixture data in
CI. Reconcile current tombstoned contacts and existing orphan data in a separate
read-only audit before any remediation run. AWS Amplify releases the frontend;
the Contacts and Messages Delete Lambdas require separate, explicitly reviewed
backend deployments and version/alias checks. Do not claim runtime enforcement
until the live Lambda aliases are verified.
