# WhatsApp Customer Service Implementation Plan

> Execute inline using superpowers:executing-plans. The owner approved the Orders blueprint and requested implementation of all tasks.

**Goal:** Complete shared customer/order self-service, safe service payment recovery, secure documents, invoices, approved catalog items and verified WhatsApp fulfillment.

**Architecture:** Reuse the website's customer identity, OrderTable and invoice records. Native Flows are views/actions over those records; the chat payment message uses a frozen server quote and a verified payment attempt. Vault uses a native list and download template, without a Flow.

**Tech Stack:** Python Lambda, DynamoDB, Cognito, S3, Meta Graph API/Flows, Wix repository, Next.js/React.

**Spec:** orders-whatsapp-flow-blueprint-20261009.md, supplied in the task workspace; service-flow-drafts/payment-artwork-check.md.

## Global constraints

- Preserve the current brand, Wix variant IDs/prices, public order-number formatting, dataset 4554612361454941 and catalog 1457045652952851.
- Every personal read/action must bind verified permanent customer identity, never a caller-supplied phone/order alone.
- Keep original order, paid service purchase, payment attempt/reference and request IDs distinct.
- No new Vault Flow. No charge for invoice copies, reviews or undefined shipment SKUs.
- Customer uploads are private from first write; public catalog artwork remains separate.
- No force push, credentials in output, unverified financial capture or fabricated customer/payment events.
- Source/test, deployment, provider approval and customer QA are separate completion states.

## Review focus

Foreign order/file/session must refuse before any send/charge; duplicate payment/webhook must repair without another collection; ambiguous send must reconcile instead of blindly retrying; paid/consumed downloads must not offer another purchase; expired/failed attempts must release only their own session lock after authoritative proof.

## Ordered tasks

1. [ ] **Vault paid-state protection.** Modify src/components/VaultFilePurchase.tsx and shared/ecommerce/service_request_store.py. Refuse a new intent for a paid/granted file, hide repayment CTA, preserve download while usable. Tests: consumed grant, missing grant, foreign file, unpaid normal purchase. Run tests/test_paid_vault.py and src/test/VaultFilePurchase.test.tsx.
2. [ ] **Safe fulfillment retry.** Modify flows/paid_vault.py. Retry only a definite rejection, with delay/count and compare-and-set ownership; unknown acceptance remains reconciliation. Test 400 retry, 502 ambiguity, concurrent/replayed accepted send.
3. [ ] **Private Drop Docs ingestion.** Align incoming path with dropdocs_storage.py without accepting arbitrary private keys. Bind source message/contact proof before promotion; preserve legacy source contract. Tests: own private upload succeeds; other customer's private upload refuses; legacy source remains.
4. [ ] **Missing-order reconciliation.** Add a shared order-reference claim store with verified customer, supplied reference, description and state AWAITING_ORDER_VERIFICATION. Never attach guessed orders or initiate another payment. Connect new service routes and CRM display.
5. [ ] **Native payment recovery.** Add bounded ids-only session recovery, requiring authoritative terminal unpaid state before releasing the customer lock. Pending/paid/unknown attempts remain blocked; compare-and-set protects replacement session. Tests: abandoned expiry, pending, late capture, replaced pointer.
6. [ ] **Orders data exchange.** Implement flows/customer_orders.py: opaque expiring session; owned profile/order summary and pagination; selected order re-read before display/action. Add orders design JSON, router entry and guarded session preparation. Test forged token/customer/order and stale sessions.
7. [ ] **Customer invoice action.** Implement owner-scoped selected-order-to-invoice association, fixed recipient, deduplicated asynchronous resend with status. Paid copy is free; missing invoice reconciles; no financial values accepted from Flow. Test foreign invoice and duplicate action.
8. [ ] **Profile updates in WhatsApp.** Reuse verified profile API, retain email verification proof, immutable phone binding and stored UUID. Preserve old order/invoice address snapshots. Test unverified email and forged phone refusal.
9. [ ] **Service checkout binding.** Freeze selected original order/request/document before price/collection. Extend native checkout to Amendment and Drop Docs only after target ownership and published fulfillment contracts validate. Test cross-owner targets and exact variant/quote.
10. [ ] **Service submission and secure picker adapter.** New Submit/Amend/Drop Flow versions route into the authoritative service records; document picker encrypted media is verified/decrypted and registered once. Test duplicate submission/file and denied storage URLs.
11. [ ] **CRM projection.** Show service/source/payment/association/status badges plus customer/original/service order/request/document refs in workspace documents/orders/contact activity. Test projection repair without duplicate authoritative records.
12. [ ] **Catalog migration and approval.** Switch provider/source configuration to the existing fresh catalog/dataset; four paid variants and six artworks are proposed through a persistent owner approval queue. Apply approved items by API and verify both WABA connections; no undefined utility price.
13. [ ] **Deployment and draft previews.** Capture live baselines, package exact-tested modules/assets/layer dependencies, deploy bounded versions and inspect provider drafts. Publish/route only versions whose fulfillment has been tested; preserve approved production review.
14. [ ] **Customer QA.** Owner-nominated customer completes real payments personally. Verify both successful and interrupted journeys, invoice delivery/download, website/CRM parity, secure ownership, order-not-found path, no duplicates and review timing. Record provider message delivery independently of API acceptance.

Each implementation task: add failing behavioral test → observe failure → implement minimal change → run focused regression → inspect diff → explicit-path commit → update ledger. Preserve provider/account prerequisites separately and continue unaffected work.

## Execution ledger

- Baseline: 7a1e1e44; worktree clean; origin/stack refreshed before edits.
- Ruling: reuse the approved blueprint and brand; no repeated design confirmation, as owner explicitly requested execution.
- Ruling: implement locally and keep live-send gates off until contracts and customer QA pass; do not treat absent flags as functioning checkout.

### Verified build checkpoint — 9 October 2026

This is a partial release, not end-to-end customer certification. Keep unchecked tasks until their full acceptance criteria pass.

| Task | Implemented and verified | Remaining |
|---|---|---|
| 1 | Vault paid/granted intent guard in service-requests live 5; repayment CTA removed in tested source | Website release and real grant/download QA |
| 2 | Vault sends use compare-and-set claims; definite rejection retries after 30s up to three attempts; unknown outcome holds | Customer delivery/reconciliation QA |
| 3 | Secure-files live 34 proves canonical inbound message, undeleted contact, verified phone and permanent customer ownership before private promotion; exact two-table GetItem permission added | Encrypted Flow DocumentPicker adapter and gated attachment QA |
| 4 | Owner-bound missing-order record, optional reference, description, public UUID and tags; workspace exposes awaiting order verification | Connect all service-specific entry points and verify agent resolution |
| 5 | No time-only lock release added: late capture must not create a second collection | Authoritative provider terminal-unpaid proof and recovery contract |
| 6 | Business API live 88 serves expiring opaque Orders sessions, verified profile, owned pagination and selected-order reread; eight-screen Meta draft 2167802357142172 has zero errors and verified endpoint | Public publication/keyword routing and customer QA |
| 7 | Business API live 88 resolves only owned existing invoice/reference/private image, checks approved IMAGE template, fixes recipient to verified phone, claims once per customer/order/UTC day; requests and send state shown in workspace | Actual template delivery, delivery receipts and website PDF parity QA |
| 8 | Orders draft edits name/address with customer compare-and-set; immutable phone/UUID, email verification remains on website; preserves order snapshots | Verified customer preview and profile parity QA |
| 9 | Existing native code supports Submit Request/Vault but live flags remain off; original/service/payment identities stay distinct | Amendment/Drop Docs target binding and fulfillment contracts before allowing collection |
| 10 | Existing ordinary private upload ownership is protected | Verify/decrypt/register encrypted picker; exact service submission/repair integration |
| 11 | Missing-order and invoice-copy types/reference/customer UUID/tags/status exposed in workspace source | Website rollout and full service/order/document projection parity QA |
| 12 | Meta sync live 7 targets fresh catalog 1457045652952851, all four known paid variants, writes disabled/dry-run. Live inspection succeeds with four proposals, no blocked items, zero existing items/applied writes | Persistent revision approval queue, approved item creation and both WABA connection readback |
| 13 | Business 88, secure-files 34, service-requests 5 and catalog-sync 7 read back; Orders draft validated without publication | Final source deployment checks, remaining provider-contract deployment |
| 14 | Test contact exists but lacked permanent customer account link at the last read | Owner verifies +918100640044 account, personally pays, and completes real journeys |

Backend final-tree offline gate: 10,319 passed, 7 skipped, 3 expected failures. Exact ZIP import checks pass for all three customer-service candidates, including the new invoice module. Orders/invoice inert candidate invocations reject unauthorized HTTP with 403 and no function error. No actual invoice send, customer purchase, capture, refund, or fabricated Purchase event was executed by those checks.

The four Wix proposals have concise public descriptions and the original IDs/prices: Submit Request ₹99; Request Amendment ₹99; Drop Docs ₹350; Vault ₹49. All proposals remain out of stock. Their Wix image URLs are assigned; the six original ultra-HD catalog PNGs remain separately stored under `o/catalog/services/<slug>/v1/image-4096.png` in `wecare-digital-get`.

Immediate rollback: business API 87 (original pre-feature baseline 83), secure-files 32, service-requests 4, catalog-sync 6. Catalog-sync 6 restores the obsolete old catalog configuration and should only be used as an emergency rollback. Preserve later concurrent releases; refresh alias revisions before any rollback. Remove only `PrivateIncomingOwnershipProof` from the existing secure-files policy if rolling back that scoped permission.
