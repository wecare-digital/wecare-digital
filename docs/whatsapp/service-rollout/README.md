# Customer service catalog and identity rollout — 9 October 2026

## Current master audit checkpoint — supersedes older snapshots below

Status: **PARTIALLY COMPLETE**. Source baseline d03ac81d; fresh provider/source audit and diagnostic-only repair deployed Business API89 (rollback88). Secure Files34, Service Requests5, catalog sync7 and checkout41 remain current. Catalog1457045652952851 is readable and empty: four Wix create proposals, no blocks, applied0. Sync is disabled/dry-run/out-of-stock. Native service/writeback/dynamic Vault gates remain off, attachments false. Intended dataset4554612361454941 connection/event matching is not verified.

Orders2167802357142172 is an eight-screen DRAFT with zero validation errors and implemented profile/owned-order/missing-order/existing-invoice adapters. Paid Submit1107164111921876 and Review1578178897413815 remain PUBLISHED. QA contact lacks permanent account link/public UUID. Catalog approval/apply, native A/B/P/R binding, terminal payment recovery, encrypted ingestion, writeback and owner-paid delivery QA remain unfinished. Do not call engineering complete.

Master audit outputs: [audit](../../../outputs/xcodex-deep-audit-2026-10-09.md), [current state](../../../outputs/xcodex-current-state.json), [architecture](../../../outputs/whatsapp-customer-service-architecture.md), [payment recovery](../../../outputs/whatsapp-payment-state-machine.md), [migration](../../../outputs/website-to-whatsapp-migration-matrix.md). Backend10334/7 skipped/3 xfailed; frontend1597/2 skipped; typecheck/build pass; lint0 errors/190 warnings. No customer sends/payments performed.

The following sections are preserved historical evidence; their older versions/read_failed/pending-adapter statements are not current facts.


## Fresh audit reconciliation — 9 October 2026

Source baseline `53ed298e` and live AWS/Meta/Wix were re-read before repairs.
Status: **PARTIALLY COMPLETE**. Secure Files live32 and Service Requests live4
now enforce permanent file/grant ownership; their tested ZIPs preserve every old
member. Secure Files adds its missing whatsapp_delivery.py dependency and bounds
direct WhatsApp links to 60–900 seconds. Payment/Drop Docs flags remain false.
Rollback targets are31 and3. Unauthenticated GET /secure-files/mine on32 returns401.

The payment diagnostic contract is repaired in source and its exact package passes135
checks. Business live79 has a different pending $LATEST package, so deployment is held
to preserve concurrent work. No readiness gate was enabled. QA phone verification
exists, but the contact still lacks checkoutCustomerId/customerUuid; complete the
supported account link before a purchase. No messages or real payments were performed.

Paid Submit Request1107164111921876 and Review1578178897413815 are PUBLISHED.
The four Wix variants/prices and revision5 artwork links were independently read back.
Live catalog sync6 still targets1607047307067517 and returns read_failed/applied0;
current source targets1457045652952851, which is readable but empty. Ownership,
WABA/Pixel connections, approval queue and controlled writeback remain release gates.
Amplify1497 succeeded on53ed298e. Full source Python10365passed/6skipped/3xfailed;
Vitest1582passed/11skipped; typecheck/build passed; lint0errors/191warnings.

Current reconciliation is in live-evidence.json.codexAuditReconciliation; exact
before/after revisions, hashes, tests and rollback are in
[codex-audit-evidence-20261009.json](codex-audit-evidence-20261009.json).
The older sections below are dated evidence, not current alias or test assertions.


## Owner scope

One fresh Meta catalog, shared with eligible WECARE WABAs, with owner approval before new products go live. Wix remains the product and price authority. Public website and WhatsApp use the same canonical orders and verified customer identity. Preserve all customer, payment, request and secure-file records. Retire old catalogs only after an inventory of ownership, product data, connections and ads; permanent deletions require a concrete reviewed target list.

## Numbered work list

1. **Artwork**: six shared-template 4096px PNGs and editable SVG masters. Uploaded to existing `wecare-digital-get` under `o/catalog/services/<slug>/v1/`. Public CDN HEADs return 200 for all six. This is letter `o`, the existing public root; no new bucket or root `0/` was created.
2. **Catalog approval**: prepare proposed items from Wix identities, artwork and live prices; owner reviews them in the workspace before enabling availability. Existing two-item automatic sync is not a complete approval queue. A persistent revision/hash approval queue and workspace actions are still required. Do not claim this is complete.
3. **Fresh catalog and cleanup**: IAM-only catalog lifecycle helper inventories owned/shared catalogs and prepares one named fresh catalog without duplicate creates. It intentionally has no delete action. Cleanup target inventory, dependency readback, new catalog approval and WABA/Pixels cutover are separate steps. Do not delete the active source while a recurring writer still targets it.
4. **Orders**: exact `Orders` and aliases read the same `OrderTable.customerId-createdAt-index` as `/orders/`, after revalidating the contact's customer link against Cognito verified phone. 10 public order numbers per page, `Orders page N` through page 10; further history uses the authenticated website and the website link for receipts. No phone scan and no internal UUID fallback. Existing historical rows without verified customer attribution require reconciliation; a matching phone is not sufficient to transfer ownership.
5. **Customer ID**: `Customer ID` returns stored canonical UUIDv4 `customerUuid`. It does not mint a new identifier or expose the internal Cognito subject. Customer UUID is already displayed on website order rows and receipts; legacy missing UUIDs are handled explicitly.
6. **Service doors**: exact Submit Request, Request Amendment, Drop Docs, Vault and Shipments keywords route to their public authenticated service experiences while unpublished or gated native journeys are under review. Leave Review retains the existing published review flow. Website service buttons open chat with the same named keyword. This does not claim the native four-service checkout is complete.
7. **Secure customer uploads**: new inbound media is written directly under `secure/u/whatsapp/incoming/`; open-request copies stay under `secure/u/service-requests/`. Inbox read generates five-minute signed URLs for gated media and does not log bearer URLs. Existing public originals are not deleted or migrated in this change. Staff document records keep private storage keys.
8. **Flows**: verified live Submit Request Paid `1107164111921876` and Review `1578178897413815` are PUBLISHED, no validation errors. Request Amendment `3678132465672138` and Drop Docs `1211063631104445` already exist as DRAFT; inspect and repair their legacy phone lookup before publication. Vault does not need another form. Shipments is an order lookup entry; carrier booking is not implemented by an artwork card.
9. **QA**: owner authorized personal number ending 0044 for customer QA. Business number ending 4400 is deliberately excluded from checkout. Customer must sign in and personally complete payments. Verify one canonical order, one Wix association, one receipt, correct parent-order/request/file linkage, secure upload visibility, no duplicate delivery and a single review invitation. No synthetic Purchase events.
10. **SDK**: owner initially kept SDK app 2238810740192680; later requested cleanup. Automatic review refused preparation because it retained the earlier keep decision. A specific updated choice is pending. Website Pixel 3411484995761247 remains the website event source.

## Product and entry matrix

| Entry | Customer copy | Commerce authority | Current Flow |
|---|---|---|---|
| Submit Request | Get help with your existing order. | Existing Wix variant e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b | Published paid Flow, opens only after payment |
| Request Amendment | Request a change to your existing order. | Existing Wix variant 864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b | Existing draft |
| Drop Docs | Upload documents for your order. | Existing Wix variant db166bc8-a763-41ec-9f65-0f718f18155a | Existing draft |
| Vault | Access and download your documents. | Existing Wix variant dcff995e-448c-493a-9259-f6a82ccdc2b4 | Owned file selection, no extra Flow |
| Shipments | Track your orders and deliveries. | Utility entry; do not invent a purchasable SKU or price | Orders lookup |
| Leave Review | Share your experience. Help us improve. | Utility entry; do not invent a purchasable SKU or price | Published review |

## Source and deployment safeguards

Current source baseline 310b78fe5e9026da38fa6adfd1a4b847f9e81214. Initial live aliases: business API 77, inbound 90, messages read 28, catalog sync 6, checkout 40. Business API and message-read live handlers exactly match the committed baseline. Inbound differs only by a missing explanatory history-replay comment; behavior matches. Preserve deployed ZIP members and overlay only named tested handlers/modules. Capture rollback aliases, guard code updates by revision/hash, then move aliases conditionally.

QA authorization is not evidence that a customer purchase occurred. Product images and deployed code are not end-to-end release certification.

## Verified deployment and blockers

Business API **79**, inbound WhatsApp **92**, and message reader **29** are live. The immediate business API rollback is 78; the original rollback versions 77, 90 and 28 remain retained. Focused backend checks passed **277 tests**, including actual private-media URL conversion; final website build and typecheck passed. The read-only live Orders smoke test returned `VERIFIED_CUSTOMER_REQUIRED` for the owner's test contact, which exists but has no verified checkout customer link. No customer messages or payments were sent/performed in this pass.

Catalog API inventory returned empty owned/shared collections despite visible Meta catalogs. Meta then explicitly denied management access to both catalog 1088514403989109 and the current 1607047307067517. No catalogs were deleted or created. Restore catalog permissions before permanent cleanup or replacing the sync target. The native service enable flag is absent (disabled); catalog sync 6 still limits variants to Submit Request/Vault and keeps them out of stock. Persistent owner approval actions, four-service native commerce, Meta artwork assignment and real customer QA remain pending. See `live-evidence.json` for exact hashes and boundaries.

Final routing checks also cover canonical commands in standby messages with legacy routing configuration. Service entries use the authenticated order portal while native checkout remains disabled, avoiding public-page/chat loops.

## Audited integration follow-up

The business API follow-up signs approved private submission attachment keys for five minutes in staff responses without persisting or logging bearer URLs. Order replies use ten complete rows and at most ten pages; further history opens the authenticated website. The exact two-member package passed 17 regression fixtures, and the full offline Python suite passed 10,328 tests (6 skipped, 3 expected failures). Runtime 79 is Active with a verified package hash and a conditional alias move. Six redundant raster release copies were externalized after byte-for-byte S3 verification; SVG masters, preview, checksums and recovery guidance remain in catalog-design/services/. No customer sends, payments, catalog creation or deletion were performed in this follow-up.

Wix Media Manager accepted all six artworks; all six URLs return HTTP 200. Product df976a0a-f582-4535-b2e1-d532f348bd27 now links each of its four service choices to a verified 4096px image. Variant IDs and prices are unchanged (99/99/350/49 INR). Its revision 5 description is short customer copy. Wix webhook delivery is visible in CloudWatch, but catalog sync returns read_failed with applied=0; propagation into Meta remains unverified. The website snapshot reflects the four verified choice images and customer copy without changing the global catalog fetch date. Catalog snapshot checks passed 93 tests. Keyword/directory Amplify job 1488 succeeded.
