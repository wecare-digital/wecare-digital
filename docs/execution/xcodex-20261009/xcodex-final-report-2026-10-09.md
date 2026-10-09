# WECARE.DIGITAL — expanded audit and execution report, 9 October 2026

## Executive Status

**PARTIALLY COMPLETE.** The audit, five required artifacts, security repairs, regression tests and six guarded Lambda deployments are complete. The complete WhatsApp customer-service hub, selected-order action menu, native customer invoice resend and provider/customer release are still incomplete. This is not an end-to-end production readiness certification.

Source baseline53ed298e422ac7694acc19bee91551169a7fe042; scoped repair724dcc383b61a7722414659cf7d2cfea405f1718; deployment-scope follow-upc24fab39fbcaa3f01024bf5adcba226453f3a8f8; expanded profile repair is the subsequent scoped `fix: enforce permanent ownership for customer profiles` commit, recorded in current-state.json. Safe source and deployment work used the existing standing authorization. The foreign checkout and its concurrent changes were preserved.

## Deep Audit Findings

The initial audit was recorded before editing. It covers Git/worktrees, source/packaged code, customer identity, API trust, payment/finalization, Wix, Meta catalog/Flows/templates, invoices, private documents, AWS resources/IAM and31 explicit current-state questions. The expanded audit adds the actual website inventory, profile fields, native history/action gaps and full payment-recovery specification.

Confirmed repairs: permanent file owner enforcement; bounded direct document URL TTL; missing secure-files delivery module packaging; shared unfiltered/paginated payment-config diagnostics; exact profile ownership; conditional profile writes against concurrent reassignment; narrowed SEO deployment scope. Profile regressions first reproduced seven failing cases, including replacement of another customer's owner by a valid full submission.

Historical DRAFT/pending claims are superseded by live published paid/review Flows and approved templates. The initial Business deployment hold is superseded by reconciled83, preserving the pending design-draft route and members. Catalog target drift and QA contact ownership are still real blockers. The former implicit phone-only contact claim is now expressly refused. Two high dependency alerts remain unresolved; no incompatible blanket major-version override was applied.

## WhatsApp Customer Service Architecture

Adopt a hybrid architecture: signed inbound → trusted sender/contact/permanent account → server-owned session → minimal profile or canonical owned orders → state-derived contextual action → existing service/payment/invoice/document modules. Retain secure web verification and sensitive document/profile fallback. A whole customer-service replacement cannot currently be certified as native.

No complete hub or Orders Flow was observed in the25-Flow inventory or source. Candidate WD_Customer_Service_Hub_v1 / WD_Orders_v1 names are proposals, not created assets. Recheck inventory, Flow JSON and endpoint equivalence before creation. Reuse existing paid Submit Request and Review; preserve Amendment/Drop Docs/design drafts. See `whatsapp-customer-service-architecture.md` for the diagram, boundaries and staged implementation specification.

## My Profile

The website currently handles name/first/last, email plus verification, session phone, structured address and public customer UUID. Profile readers and editors now require exact permanent owner. A phone locates candidates but cannot adopt a legacy row, disclose its address/email or replace its owner. Conditional writes prevent reassignment between lookup and update. Email proof and stable public IDs retain their guarantees.

The native minimal profile adapter/edit Flow is pending. Sensitive full fields and email/address proof use secure web fallback. The QA contact remains unlinked and needs explicit staff identity evidence; no customer row was reassigned.

## My Orders

Existing WhatsApp commands provide customer ID and owned order history, ten rows/page with bounded pagination. They require the existing verified permanent account. Website order history uses the canonical customer partition and offers richer status/date/amount data.

Native selected-order detail and backend contextual action menu are pending. Action availability must derive from state: paid order suppresses Pay Again; foreign order exposes nothing; invoice resolves the existing financial document; file access checks entitlement/ownership/revocation; completed review suppresses automatic duplicate invitations. The current list projection does not imply access to full purchased product details.

## Create Request

Keep **A** original owned order, **B** new paid Submit Request service order, **P** service payment/attempt and **R** resulting request separate. R concerns A, while B/P prove purchase of the service. Verify A before pricing or accepting context. Freeze the server quote and reuse the logical attempt. Paid interrupted service details reopen without charging again.

Existing service/payment primitives and the published paid Flow are present. Native selected-order A→B→P→R binding and full recovery/customer UX remain engineering work; closed gates were preserved.

## Invoice / Receipt

Quote, payment request, WhatsApp order-details message, pro-forma, final/tax invoice and receipt are different documents. Website Get Invoice verifies the owned canonical order and reads the existing invoice asset; it does not create a second financial invoice. Authorized engine rendering may regenerate the asset for the same existing invoice without advancing another financial invoice identity.

The native customer retrieval/resend adapter is pending. It must resolve the existing invoice, derive the same verified recipient server-side, respect message-window/template rules, persist a separate delivery result and retry a definite delivery failure idempotently. Staff force-send is not a customer API. Stale/ambiguous delivery claims require reconciliation. Delivery failure never reverses PAYMENT_PAID. No invoice or customer message was created/sent during this audit.

## Payment State Machine

`whatsapp-payment-state-machine.md` maps entry, identity, eligibility, context, server quote, logical attempt/reference, separate Review & Pay message, pending and independent settlement verification. It explicitly covers every requested success/failure/cancel/expiry/unknown/abandon/resume/double-tap/resend/duplicate/delayed/timeout case and each paid downstream failure.

Each row identifies authoritative database state, attempt/reference handling, order state, customer message, retry permission, new-attempt permission, idempotency identity and staff reconciliation. Unknown/pending and captured transactions forbid a fresh payable attempt. Definitive verified failure can create a new attempt/reference with retryOf. Once captured, retry order/Wix/invoice/delivery/Flow/fulfilment work using the same payment. The source provides core primitives; full durable recovery projections and native UI remain pending.

## Website → WhatsApp Migration

`website-to-whatsapp-migration-matrix.md` classifies capabilities as WHATSAPP NATIVE, WHATSAPP + SECURE WEB FALLBACK, WEB ONLY or NOT CURRENTLY SUPPORTED, separately from implementation status. Keep homepage/SEO/legal/staff administration on web. Move routine owned order/history/review interactions toward native and use secure fallback for identity, sensitive profile/document operations and unready services.

Public GETs of homepage, Orders, Vault, Submit Request, Amendment, Drop Docs, Shipments, sign-in and Contact all returned200. This is reachability evidence only. Homepage is a general overview/contact entry, not a complete verified service hub; its operations animation is illustrative. All routes are preserved.

## Already Complete

Verified source and deployed repairs preserve existing customer partitioning, integer-paise pricing, separate attempts/orders, conditional financial identities, signed provider ingress, private-first document mechanisms, published paid/review Flow assets and approved payment/download/review templates. These are component-level facts, not a substitute for a real customer/provider journey.

The broad audit covers76 Lambda functions/69 live aliases,384 HTTP routes,85 Dynamo tables,7 S3 buckets,7 EventBridge rules and73 metric alarms in the bounded production-region snapshot. All recorded functions had SnapStart=None; handler authentication was inspected rather than treating API Gateway NONE as proof of public access.

## Changes Made

Six authorized guarded Lambda releases are listed below. Profile packages change handler.py only and preserve all member bytes elsewhere. Earlier secure-files packaging adds the declared missing delivery module and owner guards. Business pending design work was inspected byte-for-byte and preserved. No environment, role, provider configuration or availability flag was changed.

The first source push also triggered the pre-existing broad SEO CI filter, updating unversioned `$LATEST`. Investigation verified all78 member contents were unchanged from the baseline; ZIP metadata changed. A follow-up narrows paths and tests immutable diff scope, and its deploy job was independently verified SKIPPED. Actual future SEO code deployment still needs version/alias/concurrency/rollback guards. Exact old SEO ZIP rollback was unavailable because the previous workflow retained no immutable version; the limitation is recorded rather than concealed.

## Tests

| Gate | Actual result | Scope / limitation |
|---|---|---|
| Python final source suite |10391 passed,6 skipped,3 xfailed | Fresh run after profile repairs; no live credentials supplied |
| Exact checkout ZIP |185 passed | Preserved live40 archive with the profile reader repair |
| Exact customer orders ZIP |123 passed | Preserved live6 archive; ownership/history and read-role checks |
| Exact customer profile ZIP |38 passed | Preserved live9 archive; save/proof/race/ownership behavior |
| Exact secure files ZIP |97 passed,3 unrelated Vault tests deselected | Ownership, identity and package paths |
| Exact service requests ZIP |35 passed | Reachable shared ownership helper |
| Reconciled exact Business ZIP |141 passed | Payment diagnostics plus preserved pending design route |
| SEO scope focused tests |27 passed | Real source diff gates reject unrelated deployment |
| Frontend Vitest |1582 passed,11 skipped;122 files passed,2 skipped | Earlier same-session frontend/source snapshot, before backend-only profile changes |
| Typecheck / lint | Passed;0 lint errors,191 warnings | No frontend change after these checks |
| Production build | Passed;1541 pages,1411 sitemap URLs | Network-enabled read-only content fetch; no authenticated/provider journey |
| Public routes | Nine HTTP200 responses | No login, form submission or UI/payment certification |
| Inert runtime probes | secure-files32:401; checkout41:401; orders7/profile10/service4:405 | Exact versions; method/auth/import evidence only |
| Concurrent secure34 / service5 |97 passed,3 deselected /38 passed | Fresh immutable archives; reviewed repair paths retained |
| Concurrent business86 |140 compatible existing checks +2 uncertainty/retry checks passed | One older SEND_FAILED-on502 expectation explicitly excluded after documenting the new SEND_UNKNOWN contract |

Test harness setup failures for missing local scripts/UI files and unrelated source handlers were corrected with reference paths and target-specific selections; they were not described as runtime defects or hidden as successful checks. Full source suite passes. Logs and exact manifests are retained under outputs.

## Production State

| Target | Before live | This session's release | This session's CodeSha256 | Captured rollback |
|---|---:|---:|---|---:|
| wecare-secure-files |31|32|MSP3hq5NKdhELTFojwfJDX2g5G7FIzsfmAELlADgrcY=|31|
| wecare-service-requests |3|4|4iVRen7bFz/s+SGaDXrwzwJeW9LVP0xRwlsFGj1l20Q=|3|
| wecare-whatsapp-business-api |79|83|3HYGs+lmmpdjY7Gg7Uyx+Fk4pF8tgvB/VhBYuDtZwwI=|79|
| wecare-checkout |40|41|kfqE0FcwNlzWfzpA2asO9hi8NU27YHouMTixzHFT1F8=|40|
| wecare-customer-orders |6|7|IAHVgfXGsh8H7QwhO77yWefHWhzfBJk87cuFOlv93Ew=|6|
| wecare-customer-profile |9|10|2n/OSNp6qvzBYKJdFFWRnLAZ3tRjXPm50Jv8rnn+I5w=|9|

All six readbacks establish Active/Successful and SnapStart=None at verification time. Full alias revision/hash evidence and rollback targets are in production-change-record.json. Business83 read-only check/list agree on two active configurations; no provider configuration was recreated. Secure independent payment and Drop Docs attach remain disabled; native service/writeback gates were not opened. Existing website checkout flags remain as observed, unchanged.

**Later concurrent production releases were preserved.** Final independent readback now observes secure-files34 (`6l0bIzOc/6StE2ttnhIEhZdIlSnks/PllJdyYTlRnZ8=`), service-requests5 (`mcx7erlUykCfXVRKwI1S96ZHvqevxXTjLgok2TuZvA0=`) and business-api86 (`JaFXsvh3b2s0iFPQp9CyZVsO+Ud2IpFpap8z7MZUxy8=`). Exact immutable ZIP hashes and AST comparison establish that all reviewed owner/payment-reader repairs remain present; secure34 retains the delivery module and bounded URL TTL. Business86 check/list execute86 and agree on two active configurations. The profile versions remain41/7/10. Newer unrelated package changes are not certified by the earlier32/4/83 test counts. See concurrent-release-reconciliation.json for current aliases and comparison evidence.

## Remaining Engineering

Implement the verified native hub/session, owned detail/action adapter, customer existing-invoice resend job, selected-order A/B/P/R binding and durable recovery projection. Complete catalog target/approval integration without exposing foreign products or opening stock prematurely. Validate private upload/entitlement/resume contracts and legacy object inventory. Add guards to real SEO code deployments. Resolve two high dependency alerts with compatible parent-package changes and fresh build checks: graphql-tools/utils affected versions and the reported braces lock entries; no unsupported blanket override.

These are engineering tasks. Status is therefore PARTIALLY COMPLETE, not ENGINEERING COMPLETE—OWNER QA REQUIRED.

Concurrent business86 also introduces a safer delivery contract ahead of source:502 is SEND_UNKNOWN; definite rejection has bounded/backoff retry; outbound invocation uses the live alias. AUD-018 records the resulting source/test drift. Do not restore older source behavior merely to make the old502 expectation pass. Reconcile the owning session's source/test change before the next build; new independent exact86 checks prove no blind resend, preserved paid state and a3-attempt bound for definite rejection. General native invoice resend and recovery UX are still pending.

## Owner Actions

Staff/owner must reconcile the legacy QA contact with the actual existing permanent account using identity evidence; a phone-only save is refused. The nominated customer ending0044 can then perform personally authorized real payment QA at the approved boundary. Confirm any outstanding business/provider contracts and rotate historically exposed credentials if still applicable. No audit tooling retrieved secret values or performed a rotation.

## External Blockers

Source intends catalog1457045652952851, while live sync6 still targets1607047307067517. Old catalog returns Graph100/subcode33; this cannot distinguish deletion from missing access. The intended catalog is readable but empty. Catalog ownership/WABA/Pixel/writer authority must be reconciled before target/product mutations. Current primary Meta component/payment docs could not be fetched; detailed picker/payment account support remains unverified. Wix writeback requires a verified current contract before release.

## Not Verified

Authenticated browser/customer journeys; actual WhatsApp payment rendering and settlement; complete canonical/Wix/cart/invoice/service chain; native invoice/Flow delivery and paid resume; native document upload, access and revocation; shipment/review end-to-end; exact Meta picker limits/in-Flow payment support; complete legacy CDN object privacy; exploit reachability of dependency alerts. Published assets, passing tests, HTTP200 and Active Lambda state are reported at their own evidence level.

## Rollback

For each target, read the current alias and exact new immutable version, confirm the recorded hash/alias revision and no concurrent deployment, then conditionally restore the recorded old immutable version. Never overwrite a newer alias blindly. No record migration occurred, so no data undo is required. Old ownership code restores the vulnerability; rollback requires judgment about that risk.

The newer secure34/service5/business86 supersede this session's32/4/83 alias revisions. Their rollback is outside this session's captured deployment sequence: obtain the newer release's own before/after record and review it. Do not restore31/3/79 from a stale record or claim that would safely undo only this session's work.

Business rollback79 omits preserved pending design-route additions now in83; record that effect. SEO has no old immutable version/alias or retained exact prior ZIP: reconstruct prior member content from53ed298e only after a new guarded review, as documented. Do not present reconstruction as exact archive rollback.

## Next Exact Action

The next release prerequisite is explicit QA permanent-account/contact reconciliation and a read-only verification that the existing customer command returns that customer's canonical partition. Keep the native/catalog/writeback gates closed. The next engineering scope is the owned selected-order/action adapter and existing-invoice resend delivery contract described in the architecture artifact; release each action with its denial/recovery tests before creating/publishing a complete hub. Owner-observed real payment QA follows only after those engineering/provider prerequisites pass.

Automatic approval review rejected an unauthenticated production POST to `/services/request-intent` because a fail-open auth bug could create state. That probe was not retried or bypassed. Inert GETs and exact offline package tests supplied safe alternative evidence; no additional permission is needed for the completed checks.
