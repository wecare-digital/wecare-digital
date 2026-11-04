# Vault and Collect: payment architecture and recovery

Maintained audit reference, updated 4 November 2026. This document describes code
boundaries and evidence needed to operate them. The deployment table is a dated
snapshot; always read the current `live` aliases and packages before a release.

## Product and payment boundaries

| Concern | Vault | Collect |
| --- | --- | --- |
| Purpose | Paid access to one private, permanently owner-bound file | A custom customer invoice and payment request |
| Staff route | `/workspace/vault/` | `/workspace/collect/` |
| Additional staff implementation | Existing service/workbench and `/ws/collect` Vault views | `/ws/collect` create, control and log panels |
| Initiation | secure-files → business-api `catalogService/sendPayment` → commerce `prepareNativeCatalogService` | invoice-engine create/preview → `send_payment_link` |
| Checkout mode | `AWS_NATIVE` for native catalog services | `WHATSAPP_NATIVE_PG` |
| Current staff goods type | `physical-goods` | `physical-goods` for the custom staff collection |
| Delivery requirements | Current payable saved address, explicit confirmation, current revision/digest, recipient phone | Saved customer/address validation; reviewed invoice snapshot and recipient phone |
| Identity of a purchase | Customer + exact file + service intent/session + payment attempt/reference | Saved customer + opaque creation reference + issued invoice + payment attempt/reference |
| Paid result | Order/invoice plus exact-file entitlement and Access Vault link | Order/invoice, saved receipt asset and payment/status messages |

Both rails use the approved `wecare_whatapp_native_pay_template` and the existing
shared pricing, provider verification and commerce tables. A send acknowledgement
never establishes payment. A filename, a staff preview, an invoice image or a
browser flag cannot establish paid access.

Vault's goods classification and mandatory address are product rules. Never make
Vault digital or assume a saved address constitutes confirmation to bypass a
refusal. Native service initiation must not be rerouted through a new Collect
invoice simply to recover a failed send.

## Vault lifecycle

1. Register an owner-bound private file; upload and verify its original S3 bytes.
   `pending` metadata is not a verified upload. Staff preview links do not redeem
   customer access or open the download window.
2. Read the authoritative ProductsTable quote. The reviewed total travels as
   `expectedTotalPaise`; commerce checks it again. The observed QA quote was
   ₹84.97, including ₹25 Express. This is an observation, not a replacement for
   the price service or a frozen issued invoice.
3. Review the customer's current saved physical address. The confirmation is
   bound to its revision and canonical digest and revalidated before the native
   prepare claim. Missing/changed confirmation refuses before sending.
4. Build shipping data from the trusted contact. Meta requires recipient
   `phone_number` inside `shipping_info.addresses[0]`, as well as the address
   fields. Emit canonical international digits without `+`; reject a missing or
   invalid country-qualified phone before pricing/reservation. Do not truncate a
   malformed number into apparent validity.
5. The native session/intent binds the exact file and customer. Commerce owns the
   frozen quote, payment attempt, PAYREF reservation and keyed template send.
   `payment-request:<reference>` is the sender idempotency identity.
6. Provider-confirmed payment enters native commerce finalization. The purchased
   snapshot and service request bind the paid file. Native finalization uses
   `accept_paid`; `finalizeNativeCatalogService` verifies finalization before
   closing the native purchase lock. Order, invoice and entitlement evidence must
   stay bound to this purchase.
7. Access is `READY` after paid entitlement creation. The first authenticated
   customer download opens the 24-hour window (`OPEN`). Download counts represent
   customer access, not staff previews. `EXPIRED` remains a paid file; it is not a
   renewal sale. `PAID_UNVERIFIED` requires reconciliation, never another charge.

Historical Vault invoices carrying `vaultFileId` / `vaultCustomerId` have a
separate compatibility settlement dispatch in razorpay-webhook:
`vaultSettleFromInvoice` → secure-files provider reconfirmation → grant/entitlement
and Access Vault delivery. That path must not be described as the sole current
native lifecycle. Receipt delivery must not gate paid-product settlement in the
compatibility path; receipt recovery and paid access are separate concerns.

## Collect lifecycle and document completeness

1. The browser serializes saved customer details, items and an explicitly entered
   Express amount (including zero). It requests a server-rendered, unnumbered
   preview. The server fingerprint binds the reviewed draft; edits invalidate it.
2. Before creating, retain one opaque `WD-PAY-…` recovery reference in session
   storage. An unreadable response is unresolved creation, not permission to
   allocate another identity or invoice number.
3. invoice-engine deduplicates by reference/payment identity and conditionally
   creates a deterministic `claiming` row before allocating a statutory number.
   A concurrent or unfinished claim is not an invoice: return
   `503 INVOICE_CREATE_IN_PROGRESS`, with a strongly consistent conflict read.
4. Stage the full allocated invoice with `status: claiming`, its number,
   reference, customer and monetary fields before writing items. Persist all item
   rows before publishing its completed status. A failed item write keeps this
   durable staged evidence without exposing a completed invoice. Before numbering,
   the caller's own unfinished claim
   can be conditionally released; after numbering it is retained for
   reconciliation so replay cannot consume another number.
5. Only adopt a complete, correctly bound issued invoice in the browser. Recovery
   must read full details, not assume a list-row match is complete. Keep the
   pending reference on unfinished or mismatched details. Payment sending also
   refuses claiming or missing-number documents.
6. Send the one keyed native payment request for that invoice/reference. A proven
   rejection and an ambiguous result have different recovery rules below.
7. Verified capture drives the existing shared order/invoice projection, saved
   receipt asset and outbound status messages. Financial records and their issued
   image versions are retained; viewing or resending a saved receipt is not
   permission to regenerate financial values or create another invoice.

An interrupted numbered claim deliberately requires reconciliation. This release
prevents false completion; it does not automatically reissue the document, repair
historical partially published invoices or erase numbering evidence.

## Retry and evidence rules

| Observation | Meaning and permitted next step |
| --- | --- |
| Explicit pre-send validation refusal | Correct the customer/address/quote/config issue and review again. Preserve the audit. |
| Vault `PAYMENT_REQUEST_REFUSED`, `VAULT_QUOTE_CHANGED`, `VAULT_DELIVERY_CONFIRMATION_REQUIRED` | The existing UI whitelist permits a manual reviewed retry only for an active UNPAID file without a local unresolved send. |
| `PAYMENT_REQUEST_NOT_SENT` | Backend has explicit unsent evidence. The current UI does not automatically clear historical/local guards; inspect Log and the original attempt. Do not broaden retry rules by guessing from an error. |
| Sender 5xx, unreadable response, Lambda crash/FunctionError, transport timeout, `MESSAGE_SEND_IN_FLIGHT` | Unconfirmed: Meta may have accepted. Keep the original attempt/reference and purchase/send claim. Reconcile that identity; do not cancel and raise a fresh collection solely because of uncertainty. |
| Collect `202`, `state: UNCONFIRMED`, `sendStatus: PENDING` | Acknowledges an unresolved operation. It is not confirmed delivery or payment. |
| `PAYMENT_REQUEST_SENT` / outbound acceptance / WAMID | Request accepted, payment still pending. Use provider status evidence for delivered/read. |
| Provider read status | The message was read; it does not establish payment. |
| Verified `PAYMENT_PAID`, linked paid invoice/order and exact-file entitlement | Payment/access evidence. Do not sell the paid Vault file again. |
| `OPEN`, download count > 0 | Paid access has been used. The first customer download opened the window. |

The frontend's local `requested` marker is intentionally retained on uncertainty.
Do not delete it, delete a server lock or upload a duplicate file to bypass an
unresolved send. A receipt resend has its own request identity/CAS rules and must
not recreate the payment attempt.

The current Vault Create notice tracks only an accepted request's exact file. It
performs read-only refreshes every five seconds, for at most 120 completed reads,
while visible. It replaces the original send text with current READY/OPEN/EXPIRED
status and download count. Customer/file changes cancel the old observer. Errors
or missing rows never become proof of payment; no refresh sends a message or
clears a retry guard.

## Incident findings and regression protections

| Confirmed failure | Protection |
| --- | --- |
| Staff confirmation was not forwarded into native checkout | Revalidate revision/digest, then pass trusted `deliveryConfirmed`; stale/missing proof refuses before claim. |
| Meta 400 required-property error at shipping address | Canonical recipient phone in the native shipping packet; behavioral builder and pre-reservation tests. Collect's shipping builder already included the phone. |
| Refusal timestamp permanently disabled a file | Shared active/UNPAID eligibility whitelist; audit retained; sent/uncertain/local-pending requests remain blocked. |
| Send notice remained after payment/download | Exact-file read-only status observer and paid-state message tests. |
| Sender 5xx/in-flight conflicts became definitive rejection | Native caller, catalog outcome mapper and Collect retain unconfirmed identity/claims. Tests cover timeout, malformed payload, server errors and keyed in-flight responses. |
| Collect claim placeholder returned successful creation | Consistent read, explicit in-progress response and completion guards. |
| Final invoice published before all item rows | Stage durable numbered invoice evidence as unfinished; publish completed status after item persistence. Injected second-item failure remains unresolved. |
| Diagnostic reason lost across Lambda boundaries | Preserve machine reason/status through native prepare; reject free-form customer/provider text from the diagnostic log. |
| Ten-line handler accidentally committed during an edit | Verify full source diff, compile handlers, run semantic tests and use committed package/hash checks before promotion. A compilation failure must stop the release. |

## Deployment snapshot and release discipline

Observed on 4 November 2026 in account `775261844268`, region `us-east-1`:

| Function | `live` version | Code SHA-256 (base64) |
| --- | --- | --- |
| wecare-secure-files | 197 | 8Smcf6xPglSoPF7AoqeC+33rJ4wh4lla4exIjDHi52k= |
| wecare-whatsapp-business-api | 417 | PfXKFtCWgau7z+wFbWZEJzIxeXy/GVkwXjDJ/xXIFQA= |
| wecare-commerce | 197 | zkuMnTb9q7Hftt8KEHMXx9JkapO+ZRHG0qxA+c5uhJs= |
| wecare-checkout | 315 | zkuMnTb9q7Hftt8KEHMXx9JkapO+ZRHG0qxA+c5uhJs= |
| wecare-invoice-engine | 292 | /R+das0BVM0JQVSLevS2K+rFUKl8mnAjhjv6Evsc/LU= |

All inspected functions were Active / Successful. A QA native request after the
shipping fix was accepted, read, paid, linked to a completed order and paid
entitlement; customer download was subsequently observed. This is evidence for
that transaction, not a claim that every historical record is healthy.

At this audit's source base (`88a87ac80`), the shipping-phone fix was live but
missing from the default branch. This hardening change restores and tests it in
source. The new ambiguity and invoice-completeness protections are prepared source
changes until their owning backend packages are explicitly released and read back.
Do not infer those protections are live from this dated document or a frontend
merge. PRs #2324 and #2326 respectively contain the retry and current-status UI
changes; verify the Amplify job's exact commit before calling them deployed.

Use the established committed-source packager and owning backend release route.
`wecare-commerce` and `wecare-checkout` use the same checkout source; compare both
live package hashes after release. Frontend Amplify builds do not release Lambda
code. Never use `amplify:deploy` as a blanket backend release.

For each release: inspect the exact diff; run handler compilation and behavioral
regressions; compare the built package hash to the promoted alias's GetFunction
hash; record previous aliases for rollback; confirm related functions are coherent.
A branch name, `$LATEST`, successful upload or claimed version number is not proof
of what the alias runs. Keep local `.github`/`.kiro` ignore edits out of the release;
the repository's gitignore safety guard rejects protected-directory masking.

## Read-first recovery runbook

1. Identify the exact customer-bound file or invoice, original reference and
   attempt. Retain local recovery markers; do not create a replacement identity.
2. Read the current live aliases and packages. Follow the original request across
   each service's own records using timestamps, request IDs and trace/reference
   IDs. Searching only application keywords can miss START/END/REPORT invocations.
3. Read the attempt and PAYREF binding, exact outbound WAMID/status, issued invoice
   and item rows, linked order and (for Vault) exact paid grant/entitlement. Keep
   accepted, read, paid and downloaded as separate observations.
4. For unconfirmed sends, use the existing keyed-send reconciliation and provider
   evidence. Do not release the claim or advise raising another collection until
   a definitive outcome is known.
5. For claiming/incomplete invoices, retain the same reference/numbering evidence
   and reconcile persistence. No manual paid-status edits, sequence rollback,
   claiming-row deletion or new number allocation as a shortcut.
6. For paid but missing receipt/access, use the established receipt or grant
   recovery path with the exact verified binding and authorized action. Repair
   delivery independently of collection. Never mark an unpaid record paid to make
   the UI green, and never resend a payment merely to obtain a missing receipt.
7. Re-read the resulting evidence and state what was actually repaired. A live
   payment test or message send requires explicit authorization; offline tests
   must not send or charge anything.

## Validation and key implementation files

CI runs Node tests, TypeScript, ESLint, pytest and the production-data safety guard.
For this release also run `python scripts/check_collect_contract.py`, compile the
changed Lambda handlers and run the complete `npm run build` chain. Tests must
exercise behavior and injected failures, not merely look for source strings.

- `amplify/functions/core/secure-files/handler.py`: owner/storage/payment/access guards and staff-facing diagnostics.
- `amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py`: exact-file native session, lock, outcome mapping and sanitized machine diagnostics.
- `amplify/functions/ecommerce/checkout/handler.py`: native shipping, quote/reservation/send, capture/finalization boundary.
- `amplify/functions/payments/invoice-engine/handler.py`: Collect document creation, item persistence, payment send and saved receipt paths.
- `amplify/functions/payments/razorpay-webhook/handler.py`: verified capture orchestration, order/invoice/status/receipt work and historical Vault settlement dispatch.
- `amplify/functions/shared/lambda_utils/ecommerce/wa_payment_request.py`: attempt/send claim and shared native template rules.
- `src/lib/vault-payment.ts`, `src/lib/vault-payment-status.ts`, `src/lib/collect.ts`: UI eligibility, current status and Collect draft/recovery contracts.
- `tests/python/test_vault_payment_boundary.py`, `test_vault_payment_outcomes.py`, `test_collect_failure_boundaries.py`: offline failure-boundary regressions.
