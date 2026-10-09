# WECARE.DIGITAL — ChatGPT continuation prompt

## Current executive status

**PARTIALLY COMPLETE.** Vault V1/V2 engineering is built, tested and deployed, but customer-facing Vault/native/Wix gates remain closed pending owner-paid end-to-end QA. Do not call the whole program complete.

## Current Git checkpoint

Source checkpoint before this handoff-doc commit: `3b9faffd3686c0c5be51a8f046592a8c4680087c` on `stack`. Re-fetch `origin/stack` before any mutation and preserve newer concurrent work.

## Vault V1/V2 completed

- Durable non-TTL `VAULT_ENTITLEMENT` separated from expiring `VAULT_DOWNLOAD_SESSION`.
- Historical paid/consumed grants can migrate lazily only when paid evidence, permanent customer and file ownership match.
- Repeated authenticated access creates a fresh session/presigned URL without another payment.
- Paid files remain visible on website as **Download / Refresh Access**; native catalog has a paid refresh branch but remains gated.
- Revoked/deleted/foreign-owner files still refuse access.
- Verified payment creates/links entitlement; temporary transport failure cannot erase purchase.
- Vault review milestone is first authenticated access, not payment; persisted `vaultReviewStatus` suppresses duplicate invitations.

## Production

- `wecare-secure-files:live` → **v35**, SHA `TsxFbPJSg+w+LQ6FOKJfvb/HP5j6x0Ldx/4Fk5e9yF0=`; rollback v34.
- `wecare-whatsapp-business-api:live` → **v92**, SHA `vdj3fItIrPi3Hb3x4PthvTDpyC01yDVG88cwtx+pFfQ=`; rollback v91.
- Both aliases matched `$LATEST`, Active/Successful after deployment.
- Deployment used repository `scripts/deploy_all_lambdas.py`; temporary OIDC role/workflow were deleted afterward.

## Release gates

Keep closed until real owner QA:
- `SECURE_FILES_PAYMENT_ENABLED=false`
- `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` unset
- `WHATSAPP_CATALOG_SERVICES_ENABLED` unset
- `WIX_WRITEBACK_ENABLED` unset
- `WIX_ECOM_WRITE_CONFIRMED` unset
- `DROPDOCS_ATTACH_ENABLED=false`

## Tests

- Full Python: **10,376 passed / 7 skipped / 3 xfailed**
- Focused Vault deployment suite: **124 passed**
- Frontend: **126 files, 1,607 passed / 2 skipped**
- Production build PASS; typecheck PASS; lint 0 errors / 191 warnings.
- Contact map harness remains the known report-only 12/13 check; unrelated to Vault.

## Provider contracts freshly read back after deployment

- Submit Flow `1107164111921876` PUBLISHED, validation_errors=[]
- `wecarepay_wa` `1783774039408860` APPROVED, IMAGE + ORDER_DETAILS
- `wecare_default_download` `1410998911012572` APPROVED, IMAGE + URL `https://wecare.digital/vault/?file={{1}}`
- `wecare_leave_review` `1801972550682516` APPROVED, IMAGE + FLOW to `1578178897413815`, screen FEEDBACK

## Wix freshly verified

Product `df976a0a-f582-4535-b2e1-d532f348bd27`, revision 5:
- Submit Request `e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b` ₹99
- Request Amendment `864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b` ₹99
- Drop Docs `db166bc8-a763-41ec-9f65-0f718f18155a` ₹350
- Vault `dcff995e-448c-493a-9259-f6a82ccdc2b4` ₹49

## Owner QA still required

Owner must personally prove with the authorized QA customer:
identity → owned unpaid file → ₹49 payment → provider settlement → one canonical order (and Wix only after writeback gate is intentionally enabled) → entitlement → receipt/download notification → authenticated Vault → actual download → expire/interrupt → return to same file → fresh access → **no second charge**.

No real customer message/payment was executed in the engineering session.

## Remaining program work

After Vault owner QA, continue the master execution order: Orders/profile contextual actions; Submit A/B/P/R full E2E; Request Amendment; encrypted/private Drop Docs ingestion; catalog approval/apply/readback + WABA/dataset verification; Wix writeback release; Shipments/remaining customer-service integration. Do not fabricate identity, Purchase events, utility prices, provider readiness, delivery or settlement.

## Files to read first

1. `outputs/xcodex-current-state.json`
2. `outputs/xcodex-deep-audit-2026-10-09.md`
3. `outputs/vault-payment-download-implementation.md`
4. `docs/whatsapp/service-rollout/live-evidence.json`
5. `docs/whatsapp/service-rollout/continue-prompt.txt`
6. the current master execution prompt

## Exact next action

Re-fetch `stack`, re-read live v35/v92 aliases/hashes and closed flags, then run the owner-authorized Vault end-to-end QA without enabling unrelated gates. If QA passes, record exact evidence before selectively opening only the proven release controls.


## 2026-10-09 12:50 UTC continuation delta

Current source checkpoint before this documentation update: `8109471f74e09dcef4958d34343f9ca923ac740a`.

- Business API production is now **v93**, SHA `erEMzmiJg7rNjwU1iTb+vR1aEQ4FDTjqfAfSW5lujAQ=`, rollback v92. This includes backend-owned Orders contextual actions/support behavior.
- Meta catalog sync production is now **v8**, SHA `he0Y8MPVNwBY4r2dZnD5cEEvIfkwVHsd6j+kUex4fNQ=`, rollback v7. The exact approved-plan hash interlock is deployed but catalog writes remain closed: enabled=false, dry-run=true, force-out-of-stock=true, approval hash unset.
- Secure Files remains v35; checkout v42; invoice-engine v50.
- Fresh provider readback: Submit Flow 1107164111921876 PUBLISHED; payment/download/review templates APPROVED. Orders 2167802357142172, Amendment 3678132465672138, Drop Docs 1211063631104445 and Shipments 849713848195607 remain DRAFT with validation_errors=[].
- Fresh Wix V3 readback reconfirmed product df976a0a-f582-4535-b2e1-d532f348bd27 revision 5, visible/in stock, and exact prices: Submit ₹99, Amendment ₹99, Drop Docs ₹350, Vault ₹49.
- The one-shot deploy workflow and exact-scope OIDC role were deleted after successful deployment.
- No real customer payment/send, Flow publication, catalog apply, Wix writeback or synthetic Purchase event occurred. Overall status remains PARTIALLY COMPLETE.

Exact next engineering action: finish the catalog proposal → durable approval → apply/readback mechanism while keeping the live sync gates closed by default, then continue Submit A/B/P/R and Request Amendment/Drop Docs engineering. Owner-paid Vault E2E QA is still mandatory before customer release.
