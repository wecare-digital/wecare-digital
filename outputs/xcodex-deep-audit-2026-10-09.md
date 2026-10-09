# XCODEX current-state audit — 9 October 2026

Status: **PARTIALLY COMPLETE**. Initial audit established before implementation edits.

The clean worktree and origin/stack are both d03ac81dfda8d1a5da461f01b4005559b2a3ada4. The other local stack checkout is newer and is left untouched. Current provider readbacks confirm Business API live88, Secure Files34, Service Requests5, catalog sync7 and checkout41. Fresh catalog1457045652952851 reads successfully with four Wix proposals and zero existing items/applied writes. Submit Request1107164111921876 and Review1578178897413815 are PUBLISHED; Orders2167802357142172 is DRAFT with no validation errors. Native activation and Wix writeback flags remain off. QA contact has neither checkoutCustomerId nor customerUuid.

## Findings requiring current reconciliation

| ID | Severity | State | Component | Evidence | Impact and root cause | Fix and validation | Rollback |
|---|---|---|---|---|---|---|---|
| AUD-01 | P2 | FIXED | Rollout records | README and live-evidence still lead with business79/catalog6/old catalog and read_failed | Stale handoff can repeat repairs or overwrite newer deployments | Preserve snapshots; add fresh current section and machine-readable record | Revert only audit documentation commit |
| AUD-02 | P3 | FIXED | Retired payment diagnostic | IAM GET-shaped raw route on live88 returns400 phoneId required; supported check/list both200 with active configurations | Generic route masks the retired contract, although current checkout uses normalized list | Regression-test an explicit retired response directing callers to list/check; no provider/payment mutations | Restore live88 with a current alias revision guard |
| AUD-03 | P1 | CONFIRMED | Customer release | Native catalog/writeback/dynamic Vault flags off; encrypted picker and four-service checkout incomplete | Paid service rollout cannot be called ready | Complete target binding, provider terminal recovery, picker and writeback contracts; then customer QA | Keep gates off; preserve successful payment records |
| AUD-04 | P2 | CONFIRMED | Catalog availability | Four known paid proposals, no blocks; empty fresh catalog | Approval queue and item application remain engineering work, not a permission read failure | Durable per-revision approval and API apply/readback; verify both WABAs | Staged read-only config; never restore an obsolete writer without review |
| AUD-05 | P1 | CONFIRMED | QA identity | One undeleted nominated contact without permanent account link/public UUID | Cannot authenticate owner-scoped Orders/payment test | Supported sign-in/account verification and ownership reconciliation; never synthesize link | No identity write performed |
| AUD-06 | P2 | NOT VERIFIED | Customer delivery and events | No real paid QA, invoice send or handset interaction in this audit | Approval/API acceptance/build do not prove delivery, CAPI match or customer readiness | Owner-paid QA and delivery receipts; no fabricated Purchase | No financial/provider changes performed |

Superseded: catalog read_failed on old target, held business79 diagnostic deployment, missing native Orders adapter, missing invoice-copy source, Vault repayment/retry defects. Current private CDN probe returns302 to homepage without serving the file; bucket privacy is supported by the deployed edge prefix guard, not bucket policy alone. Comprehensive account-wide security and every provider-side connection are not certified by this scoped audit.

## Final repair and verification checkpoint

AUD-01: The authoritative rollout README, release-status entry, continuation prompt and live-evidence root now point to this fresh audit. Previous root evidence is retained as a historical snapshot. The user-provided master prompt is preserved verbatim beneath a new precedence checkpoint in xcodex-master-execution-prompt-updated-2026-10-09.md. No original attachment was overwritten.

AUD-02: Reproduced GET/POST legacy fallthrough in focused offline tests before repair. Added an explicit retired raw route before the generic payment-config handler, with410 and normalized list/check replacement paths. Exact deployment ZIP differs from verified live88 in handler.py only. Candidate89 readback: raw410, list200, check200, unauthenticated HTTP401, no FunctionError. Revision-guarded alias switched88→89 and live raw readback410. SHA256 r+k6k2WhMDaNbYzFfax39Zi/1e/ckqg8ad891fvCu3E=. No payment configuration mutation or messaging/financial operation. Immediate rollback: read current live alias, then guarded UpdateAlias to88; never overwrite a concurrent newer version blindly.

Final local gates: backend10,334 passed /7 skipped /3 expected failures; focused165 passed; frontend1,597 passed /2 skipped across125 files; TypeScript passes; ESLint0 errors and190 existing warnings. Production build initially failed closed on public blog HTTP503 and passed on retry. Nine public routes return200 HTML. This confirms reachability/build behavior, not authenticated account/payment journeys. No paid customer QA, captured charge, invoice creation, refund, test message or synthetic Purchase event was performed.

AUD-03 required tests: original A versus service B separation, stable P/reference, R ownership, frozen integer quote, definite-terminal retry with lineage, pending/unknown refusal to charge again, duplicate/delayed webhook convergence, paid downstream recovery, picker decrypt/register and writeback failure recovery. Live verification is NOT COMPLETE; keep flags closed. Rollback preserves paid records and disables new entry, never rolls back successful settlement.

AUD-04 required tests: per-revision proposal/approval persistence, stale-revision rejection, exact intended variant mapping, bounded apply/readback, image fetch and both-WABA attachment. No products applied. Existing catalog read failure is superseded; source is four variants with no blocks. Approval automation is unfinished. Desired dataset4554612361454941 is not proof of an actual provider connection or100% match rate.

AUD-05 required tests: supported account verification, own/foreign/missing identity, same-phone/new-sub, deleted/recreated contact, immutable UUID/phone. No identity writes occurred. The existing nominated test customer must establish a permanent account binding before owner-paid QA.

AUD-06: handset/customer delivery, secure downloads, invoice copy, real Orders rendering, automatic review deduplication, provider event delivery and catalog matching remain NOT VERIFIED. The approved template/readiness/provider checks alone do not establish these. Owner-paid QA must finish after engineering gates are complete.

## Boundaries and next execution

This scoped audit covers nine live Lambda configurations/hashes, seven table schemas/indexes, relevant IAM simulation, private bucket/CloudFront guard, real Meta Flow inventory (49), three approved template contracts, active payment configurations on both WABAs, read-only Wix/catalog proposals, QA contact linkage, source/tests and current Amplify deployment1502 at d03ac81d. It is not an all-region resource/cost audit, every CRM record inspection, whole-site signed-in certification or full provider security assessment. IAM simulation is not actual document delivery. A stale CloudFront distribution policy reference was observed; current private-prefix guard remains effective, so no broad infrastructure change was made.

Next bounded engineering action: implement durable per-revision catalog proposal/approval/apply/readback without enabling checkout; verify the new catalog/dataset/WABA connections. Then complete service target binding, native terminal recovery, encrypted upload ingestion and safe writeback, followed by owner-paid QA. Retain website fallbacks and reuse Orders draft rather than create overlapping hubs. Overall status remains **PARTIALLY COMPLETE**.

## Dependency security follow-up

AUD-07 — P1 / CONFIRMED / amplify/package-lock.json: GitHub currently reports two open high-severity Dependabot alerts:63 for @graphql-tools/utils (GHSA-7mx3-vvmw-hjmv, first patched12.0.1), and61 for braces (GHSA-vfj7-8cjw-p6xm, no patched version listed by the API). Alert presence is confirmed; exploitability of the deployed customer journey is NOT VERIFIED. Root cause is the retained Amplify transitive dependency graph. Repair requires parent-version compatibility analysis and a targeted lockfile update/removal path, then Amplify build/schema/deployment tests and alert readback. Do not invent a fix version or blanket override. No dependency changes were made in this diagnostic patch. Rollback any future dependency repair by its scoped source commit and exact validated package, preserving financial/customer state.

## Vault follow-up audit and implementation handoff

Fresh source checkpoint e9e377ce, no origin divergence; live Business89/Secure Files34/checkout41 hashes unchanged. Fresh approved payment/download/review template contracts confirmed. DownloadGrantsTable TTL ENABLED on expiresAt; legacy grant TTL1800, web URLTTL60, direct link runtime clamp900 despite env21600. Independent secure-file paymentfalse; native/dynamic/writeback gates off. No production mutation/customer send/payment.

AUD-08 / P1 / CONFIRMED: current grant consumption occurs before actual S3 download; expired/interrupted URL has no automatic same-purchase renewal. Paid web access then directs to support and catalog selection excludes paid files. Some legacy errors say pay again. Root cause: ephemeral download redemption is coupled to paid grant consumption. Required fix: durable paid owner/file/version entitlement plus expiring renewable sessions; paid catalog/keyword and website re-entry without another charge, with revocation/identity checks and no provider/financial writes. Required tests and rollback compatibility are specified in vault-payment-download-implementation.md V1–V9. NOT IMPLEMENTED; keep release closed.

AUD-09 / P2 / CONFIRMED: legacy S3 link message incorrectly claims single use; only application grant redemption is one-time, presigned URL can be reused until expiry. Payment alone is not universal proof of open messaging window. Use approved template and verified inbound window; distinguish link issuance/accepted send from actual download. Config TTL drift is bounded in runtime, not proven six-hour exposure. Required word/contract/config repairs and live verification remain pending.

Follow-up targeted regression check:121 existing tests passed (paid Vault, secure files, native catalog orchestration and catalog checkout). No renewal implementation tests passed because feature is not yet built. Read outputs/xcodex-new-session-full-prompt.md for complete executable continuation; latest priority is V1/V2 durable paid access and safe renewal before catalog activation. Overall PARTIALLY COMPLETE.

## Owner-authorized Flow retirement

Nine unused published Flows retired and independently read back across both WABAs.59 total; after2 published/22 draft/35 deprecated. Retained six exact IDs and18 unused-draft boundary in flow-retirement-2026-10-09.md/.json. Fixed deprecation endpoint/WABA context and list pagination; deployed Business90 with rollback89. Full backend10339/7 skipped/3 xfailed; focused135. No customer send/payment/publication/draft deletion or gate enablement.

AUD-10 / P2 / CONFIRMED: legacy Subscribe route/UI still reference the now-retired Profile IDs. Disable/replace with verified Orders/profile path and inspect old template dependencies before customer release. Provider deprecation completed; full stale-routing/draft cleanup not complete. Do not rebuild/republish deprecated legacy versions from stale handoff.

## ChatGPT Vault V1/V2 production update — 2026-10-09 11:04 UTC

Status: **PARTIALLY COMPLETE** — Vault V1/V2 engineering is deployed; real owner/customer payment and recovery QA is still required before customer-facing gates may open.

- Source checkpoint before handoff docs: `3b9faffd3686c0c5be51a8f046592a8c4680087c`.
- Implemented durable non-TTL `VAULT_ENTITLEMENT` records, separate TTL `VAULT_DOWNLOAD_SESSION` records, lazy migration of historical paid/consumed grants, website **Download / Refresh Access**, and native paid-file refresh routing.
- Transport expiry/interruption no longer consumes the financial purchase; every refresh rechecks permanent customer identity, file ownership/status and active entitlement.
- Verified-payment finalization now creates/links entitlement once. Duplicate webhook/idempotency behavior remains pinned by tests.
- Vault review invitation moved from payment/notification time to the first authenticated download-session milestone and uses persisted `vaultReviewStatus` duplicate suppression.
- Production deploy: `wecare-secure-files` **v35**, SHA `TsxFbPJSg+w+LQ6FOKJfvb/HP5j6x0Ldx/4Fk5e9yF0=`, rollback **v34**; `wecare-whatsapp-business-api` **v92**, SHA `vdj3fItIrPi3Hb3x4PthvTDpyC01yDVG88cwtx+pFfQ=`, rollback **v91**. Both `live` aliases match `$LATEST`, State Active, LastUpdateStatus Successful.
- Release controls remain closed: `SECURE_FILES_PAYMENT_ENABLED=false`; `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`, `WHATSAPP_CATALOG_SERVICES_ENABLED`, `WIX_WRITEBACK_ENABLED`, `WIX_ECOM_WRITE_CONFIRMED` unset.
- Tests: full Python **10,376 passed / 7 skipped / 3 xfailed**; focused Vault deploy suite **124 passed**; frontend **126 files / 1,607 passed / 2 skipped**; production build and typecheck PASS; lint **0 errors / 191 warnings**. The known Contact map check remains report-only at 12/13.
- Fresh live provider readback after deploy: Submit Flow `1107164111921876` PUBLISHED; templates `wecarepay_wa` `1783774039408860`, `wecare_default_download` `1410998911012572`, and `wecare_leave_review` `1801972550682516` all APPROVED. Download URL contract remains `https://wecare.digital/vault/?file={{1}}` with authoritative `fileId`.
- Fresh Wix V3 readback: product `df976a0a-f582-4535-b2e1-d532f348bd27` revision 5; Submit ₹99 `e9f0...`, Amendment ₹99 `864f...`, Drop Docs ₹350 `db166...`, Vault ₹49 `dcff...`, all visible/in stock.
- No real customer message or payment was sent in this implementation session. Owner QA must prove ₹49 settlement → canonical order/Wix where enabled → entitlement → authenticated download → expiry/interruption → refresh with **no second charge** before opening customer-facing release gates.



## ChatGPT Orders/catalog production update — 2026-10-09 12:50 UTC

Status remains **PARTIALLY COMPLETE**. Vault V1/V2 remains deployed and closed for owner QA; this phase deployed the next backend-only increments without opening customer-facing gates.

- Current reconciled source checkpoint before this documentation update: `8109471f74e09dcef4958d34343f9ca923ac740a`.
- Orders/customer profile: backend-owned contextual actions and owner-scoped support handling are now deployed in `wecare-whatsapp-business-api:live` **v93**, SHA `erEMzmiJg7rNjwU1iTb+vR1aEQ4FDTjqfAfSW5lujAQ=`; rollback **v92**.
- Meta catalog sync: exact approved-plan hash interlock is deployed in `wecare-meta-catalog-sync:live` **v8**, SHA `he0Y8MPVNwBY4r2dZnD5cEEvIfkwVHsd6j+kUex4fNQ=`; rollback **v7**. Runtime remains fail-closed: `META_CATALOG_SYNC_ENABLED=false`, `META_CATALOG_SYNC_DRY_RUN=true`, `META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true`, approval hash unset.
- Fresh Meta readback through live Business API: Submit Flow `1107164111921876` PUBLISHED with validation_errors=[]; `wecarepay_wa` `1783774039408860`, `wecare_default_download` `1410998911012572`, and `wecare_leave_review` `1801972550682516` remain APPROVED. Orders `2167802357142172`, Amendment `3678132465672138`, Drop Docs `1211063631104445`, Shipments `849713848195607` remain DRAFT with validation_errors=[].
- Fresh Wix Catalog V3 readback: product `df976a0a-f582-4535-b2e1-d532f348bd27` revision 5, visible/in stock. Exact variants/prices confirmed: Submit ₹99 `e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b`; Amendment ₹99 `864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b`; Drop Docs ₹350 `db166bc8-a763-41ec-9f65-0f718f18155a`; Vault ₹49 `dcff995e-448c-493a-9259-f6a82ccdc2b4`.
- Deployment was preceded by focused regression tests in the one-shot workflow; the deployment completed SUCCESS. Temporary workflow and exact-scope OIDC role were deleted afterward.
- Customer release remains closed. No real customer payment, send, Flow publication, Meta catalog item write, Wix order writeback, or synthetic Purchase event was performed.


## ChatGPT durable catalog approval control — 2026-10-09 13:05 UTC

Status remains **PARTIALLY COMPLETE**. This phase completed the catalog proposal/approval control plane without opening catalog sales or writing a Meta item.

- Business API production: **v94**, SHA `iqljVpqYVcJAXbuMs83Efd2aDQAW4EAAgGhQ4eAiJeY=`; rollback v93.
- Meta catalog sync production: **v9**, SHA `cdjjFw5B2v9f8kT0nAUXeBlMXInYo+eh8FNgUrW+BgM=`; rollback v8.
- New authenticated Workspace routes: `GET /wa-business/catalog-sync` (route `ktbob4d`) and `POST /wa-business/catalog-sync` (route `aqr2wkn`), both reusing the existing Business API live integration. Application auth revalidates Cognito Admin and configured Admin MFA; anonymous smoke returned HTTP 401.
- Durable exact-plan records use existing `stack-wecare-digital-AgentApprovalsTable` with namespaced key `META_CATALOG_SYNC#<sha256>`. Catalog rows omit `expiresTtl`; the Lambda role has only GetItem/PutItem/UpdateItem on that table. Scan/Delete remain denied.
- Background schedule/webhook executions cannot spend an approval. Apply requires an explicit Admin action, exact current plan, durable APPROVED state, enabled=true and dryRun=false.
- Live read-only plan: hash `19b8290495af210b94d819d2bdd3640805bd770fa640d6bb46cda46ae31064d5`; create=4, update=0, retire=0, foreign=0, blockers=[]; all desired items held out of stock.
- Release controls remain closed: enabled=false, dryRun=true, force-out-of-stock=true. Approval table item count remained 0 after smoke tests. No proposal, approval, Meta item write, Wix write, payment, customer send or synthetic event was performed.
- Focused backend security tests, TypeScript and focused Workspace tests passed before deployment. The one-shot deploy workflow and temporary OIDC role were deleted after successful verification.
