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

### Build checkpoint — 9 October 2026

| Task | Implementation checkpoint | Release state |
|---|---|---|
| 1 | Paid/granted Vault files refuse a new intent; paid file hides repayment CTA | Source tested; alias deployment pending |
| 2 | Definite outbound rejection retries after 30s, at most three attempts; unknown outcomes never blindly retry | Source tested; alias deployment pending |
| 3 | Private inbound message/contact/customer/S3-key proof before Drop Docs promotion | Source tested; alias deployment pending; encrypted picker is task 10 |
| 4 | Orders missing-order form saves one owner-bound `awaiting_order_verification` record per session without guessed order or payment | Source tested; service-specific integration and CRM controls pending |
| 6 | Expiring opaque Orders session, verified profile, server-owned pagination, selected-order ownership re-read and missing-order screens | Meta draft 2167802357142172 created with zero validation errors; endpoint and customer routing pending |
| 12 | Concurrent source already moved to fresh catalog/dataset; preserve those changes during merge | Live catalog population/sync and revision approval remain pending |
| 13 | Isolated draft executor 84 created over hash-verified live 83; no live alias switch | Actual Orders backend not deployed by the preview executor |
| 5,7–11,14 | Continue implementation and provider/customer validation | Not complete |

Evidence: focused Python regression 220 passed, followed by additional expiry/recreated-contact/retry-cap checks 35 passed; Vault UI 7 passed. Meta preview expires 8 November 2026. No customer send, purchase, invoice, upload or synthetic analytics event was executed by these tests.
