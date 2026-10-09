# Customer service catalog and identity rollout — 9 October 2026

## Owner scope

One fresh Meta catalog, shared with eligible WECARE WABAs, with owner approval before new products go live. Wix remains the product and price authority. Public website and WhatsApp use the same canonical orders and verified customer identity. Preserve all customer, payment, request and secure-file records. Retire old catalogs only after an inventory of ownership, product data, connections and ads; permanent deletions require a concrete reviewed target list.

## Numbered work list

1. **Artwork**: six shared-template 4096px PNGs and editable SVG masters. Uploaded to existing `wecare-digital-get` under `o/catalog/services/<slug>/v1/`. Public CDN HEADs return 200 for all six. This is letter `o`, the existing public root; no new bucket or root `0/` was created.
2. **Catalog approval**: prepare proposed items from Wix identities, artwork and live prices; owner reviews them in the workspace before enabling availability. Existing two-item automatic sync is not a complete approval queue. A persistent revision/hash approval queue and workspace actions are still required. Do not claim this is complete.
3. **Fresh catalog and cleanup**: IAM-only catalog lifecycle helper inventories owned/shared catalogs and prepares one named fresh catalog without duplicate creates. It intentionally has no delete action. Cleanup target inventory, dependency readback, new catalog approval and WABA/Pixels cutover are separate steps. Do not delete the active source while a recurring writer still targets it.
4. **Orders**: exact `Orders` and aliases read the same `OrderTable.customerId-createdAt-index` as `/orders/`, after revalidating the contact's customer link against Cognito verified phone. 20 public order numbers per page, `Orders page N` for more and the website link for receipts. No phone scan and no internal UUID fallback. Existing historical rows without verified customer attribution require reconciliation; a matching phone is not sufficient to transfer ownership.
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

Business API **78**, inbound WhatsApp **92**, and message reader **29** are live. Rollback versions remain 77, 90 and 28. Focused backend checks passed **269 tests**, including actual private-media URL conversion; final website build and typecheck passed. The read-only live Orders smoke test returned `VERIFIED_CUSTOMER_REQUIRED` for the owner's test contact, which exists but has no verified checkout customer link. No customer messages or payments were sent/performed in this pass.

Catalog API inventory returned empty owned/shared collections despite visible Meta catalogs. Meta then explicitly denied management access to both catalog 1088514403989109 and the current 1607047307067517. No catalogs were deleted or created. Restore catalog permissions before permanent cleanup or replacing the sync target. The native service enable flag is absent (disabled); catalog sync 6 still limits variants to Submit Request/Vault and keeps them out of stock. Persistent owner approval actions, four-service native commerce, Wix artwork assignment and real customer QA remain pending. See `live-evidence.json` for exact hashes and boundaries.

Final routing checks also cover canonical commands in standby messages with legacy routing configuration. Service entries use the authenticated order portal while native checkout remains disabled, avoiding public-page/chat loops.
