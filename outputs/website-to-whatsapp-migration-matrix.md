# Website to WhatsApp migration matrix — current checkpoint, 9 October 2026

Status: **PARTIALLY COMPLETE**. Keep the website as a secure fallback while completing native customer service. Nine public routes returned200 HTML; this proves reachability only. No authenticated customer journey or real payment was performed.

| Capability / route | Backend and authority | Authentication / privacy | WhatsApp equivalent | Template / payment dependency | Classification | Current readiness |
|---|---|---|---|---|---|---|
| Home / public discovery / SEO | Public content and shared navigation | Public; no account details | Optional service keyword entry | No payment | WEB ONLY | Reachable; retain all routes/content |
| Sign-in / account recovery /account/sign-in/ | Cognito CUSTOM_AUTH and customer-profile | Verified account/OTP; permanent owner | Verify sender/account before service | Account linking required | WHATSAPP + SECURE WEB FALLBACK | Website retained; QA contact lacks permanent link |
| Customer ID / profile | customer-profile, trusted contact and Cognito owner | UUID/phone immutable; minimal summary; email proof on web | Orders draft account summary and guarded name/address edits | No payment | WHATSAPP + SECURE WEB FALLBACK | Adapter implemented; draft/handset QA pending |
| Orders /orders/ | customer-orders, singular OrderTable; /ecommerce/my-orders | Same permanent owner; pages of10; selected order base read | Orders keyword and Orders draft2167802357142172 | No payment to view existing order | WHATSAPP NATIVE | Existing text routing and draft adapter; draft not published |
| Order detail | Canonical selected order; ownership checked each action | No client order number as authorization | Owned detail/action screen | Contextual eligibility needed | WHATSAPP + SECURE WEB FALLBACK | Basic adapter exists; full service action projection remains |
| Existing invoice / receipt | InvoicesTable / InvoiceAssetsTable; /ecommerce/my-invoice | Owned canonical order, existing private asset | Existing invoice IMAGE copy to verified recipient | Approved template; per-customer/order/day claim | WHATSAPP + SECURE WEB FALLBACK | Implemented; real accepted/delivered/download QA pending |
| Submit Request /submit-request/ | ServiceRequestPurchase, service-requests, checkout | Owned A; B/P/R distinct; server frozen quote | Published paid-detail Flow1107164111921876 after confirmed payment | Separate payment message, writeback, paid resume | WHATSAPP + SECURE WEB FALLBACK | Native gates off; A/B/P/R and terminal recovery not certified |
| Request Amendment /request-amendment/ | Shared purchase component plus service eligibility | Original owned request/order must persist | Existing amendment/design drafts | Wix ₹99, same paid continuation invariants | WHATSAPP + SECURE WEB FALLBACK | Target/action binding and release tests pending |
| Drop Docs /drop-docs/ | Shared purchase plus secure-files/service request registration | Decrypted validated private owner-bound media | Existing Drop Docs draft / picker | Wix ₹350; secure attachment gate false | WHATSAPP + SECURE WEB FALLBACK | Encrypted ingestion protocol and CRM projection pending |
| Vault /vault/ | VaultFilePurchase, secure-files and download grants | Permanent file owner, active paid grant/revocation | Owned file → payment → authorized PDF/download; no separate Flow | Wix ₹49; document/download template; dynamic gate off | WHATSAPP + SECURE WEB FALLBACK | Repayment/retry guards deployed; native paid QA pending |
| Shipments /shipments/ | Owned order/shipment source | Verified selected owned shipment | Utility draft/tracking summary | No invented paid SKU | WHATSAPP + SECURE WEB FALLBACK | Tracking provider/customer contract not certified |
| Leave Review /leave-review/ | Published review1578178897413815 and submission backend | Trusted sender and correct completion association | Leave Review keyword / approved Flow template | Deduplicated milestone follow-up | WHATSAPP NATIVE | Published/approved; automatic paid-service follow-up QA pending |
| Missing order help | FlowSubmissionTable verification intake | Verified permanent owner; unknown A retained as unknown | Save reference/description for staff verification | No charge until ownership/eligibility verified | WHATSAPP + SECURE WEB FALLBACK | Generic intake built; service-specific queue/action integration pending |
| Pay outstanding balance | Authoritative positive payable balance required | Selected owned order + explicit distinct intent | Contextual pay action only when eligible | Exact independent settlement and stable reference | NOT CURRENTLY SUPPORTED | No complete native balance contract verified |
| Contact/support | Contact page and messaging workspace | Minimum contextual data | Support keyword/context handoff | Messaging window/template policy | WHATSAPP + SECURE WEB FALLBACK | Preserve working web access; contextual hub completion pending |
| Administration/finance/provider settings | Privileged workspace and IAM/role authorization | Staff only; never customer Flow | No customer equivalent | No customer capture/refund/config actions | WEB ONLY | Preserve privileged tools |

Amounts are fresh Wix variant observations; final quotes must be loaded and frozen server-side in integer INR paise. A=original order; B=paid service order; P=attempt/reference; R=request concerning A. Website and WhatsApp must read the same canonical owner/order/payment/invoice records. Wix stays an internal repository.

Keep secure web for verified identity recovery, email proof, complex address changes and sensitive downloads. Native release must pass own/foreign account denial, deleted/recreated-contact denial, pagination, missing-order intake, confirmed-payment-only fulfillment, double tap/webhook deduplication, paid downstream recovery, correct receipt/document delivery and owner-observed QA. Do not remove website capabilities or redirect every CTA merely because a draft validates.

## Latest Vault implementation boundary

Owner now requires repeated same-catalog access to the existing paid file when a temporary URL expires or download fails. This is NOT IMPLEMENTED: current consumed grant permits one redemption, paid re-entry directs to support, and catalog selection excludes paid files. Separate durable paid entitlement from short-lived sessions; preserve no-second-charge and permanent-owner checks. Approved template points to authenticated Vault/?file=<fileId>, which must resolve a fresh private S3 URL. Read vault-payment-download-implementation.md and xcodex-new-session-full-prompt.md for V1–V9 and exact acceptance tests. Link expiry does not revoke the payment or a saved PDF.

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
