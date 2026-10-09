# WECARE.DIGITAL current-state audit — 9 October 2026

## Executive status

**PARTIALLY COMPLETE.** This is the initial audit, written before repairs. Production customer readiness is not certified. Evidence was collected anew; historical documents are identified as historical rather than promoted to current facts. Source baseline: `53ed298e422ac7694acc19bee91551169a7fe042`, fetched during the audit. The initial source snapshot was `7a1e1e44cdc9ef894b0d5534f1f197ad1c8ef993`; concurrent work advanced it during collection.

## Authority, isolation and Git

The chat directory initially contained no repository. The discovered checkout at `/Users/wecaredigital/Documents/Codex/2026-10-08/ca/work/wecare-digital` is on stack, HEAD `624549780a00ce80cf3bf5c5b268d7c34ed27953`. It had nine modified tracked paths and six untracked paths, covering checkout, Wix store, inbound/outbound WhatsApp, paid flows, finalization, order links, catalog implementation/design and tests. None were edited, staged, discarded or committed by this audit. Its registered second worktree was detached at 7a1e1e44. Initial divergence was 0 ahead / 2,957 behind the fetched stack ref. A local read snapshot, followed by a detached checkout with Git provenance, isolates this audit.

Read local AGENTS.md and owner overrides, standing authorization, AWS rules, secret handling, alias/SnapStart deployment, QA recipient, parallel-session and single-branch rules. These local instruction files are untracked/absent in the fetched source, so their current applicability was checked against committed execution plans. The current completion plan explicitly records owner authorization for root use; therefore the connector's root ARN is not classified as an unauthorized identity. Account 775261844268 only; primary region us-east-1. No secrets were retrieved by audit tooling. Existing runtime handlers use their established lazy provider-secret references for read-only Graph queries.

Standing authority permits safe source fixes and scoped Lambda deployments with exact tests and rollback evidence. It excludes provider credentials, payment capture/refund/config mutations, broad staging, destructive history changes and live-send flag enabling. No payments, messages, provider mutations, catalog creates/deletes or purchase gates were performed/opened.

Git diff-check passed in the foreign checkout and clean detached baseline. Object storage there: 55.97 MiB packed and 4.22 MiB loose, zero garbage; it is not an unexpectedly enormous Git database. Full historical secret-value scanning was not run because its implementation retrieves provider secrets. Old exposure reports remain owner-rotation items, not freshly verified credentials. No history rewrite is proposed.

## Architecture and workflow trace

The frontend is Next/React, with a central API client and static build/artifact generation; authenticated customer account/order/Vault pages are distinct from staff workspace routes. Amplify publishes stack. HTTP API zllr9lrg7j routes to Lambda integrations; handler middleware, Cognito customer authentication, signed provider ingress and private internal Lambda invocations supply different trust boundaries. Gateway NONE is not proof of missing handler authentication.

Website checkout → server-authenticated customer → Wix Catalog V3/cart quote → frozen integer-paise snapshot/payment attempt → Razorpay provider-confirmed capture → conditional order reservation → canonical OrderTable → guarded Wix external order/payment/cart completion → invoice/receipt/fulfillment adapters. Separate initiation and writeback gates are present. `finalization.record_paid` conditions the reference and verified payment/amount pair; split tender reconciles provider-captured plus other tender against payable. Side-effect guards preserve uncertain external writes for reconciliation rather than blind retry.

WhatsApp inbound → trusted provider ingress → contact/message dedup → exact service/customer command → revalidation of stored checkoutCustomerId against Cognito sub and verified phone → customer partition query. Orders and Customer ID use permanent identity rather than an arbitrary supplied order/contact identifier. Directory replies cap at ten public order numbers and ten pages, then use authenticated website history.

Native service basket → verified contact/customer → earlier owned order (Submit Request) or selected private file (Vault) → Wix-frozen quote/live Meta readiness → stable payment claim → confirmed canonical order and Wix finalization → paid service activation. Native release remains disabled; this trace is source/test behavior, not a completed live purchase.

Paid Submit Request → stored opaque capability plus PAYREF/PAYMENTATTEMPT purchase proof → customer-owned parent selection → transaction with parent ownership condition and once-only details write → staff submission projection → guarded review send. Parent order excludes the newly purchased service order. Back does not submit through the final write. Client payment fields do not grant purchase proof.

Vault → file ownership check → frozen file-bound service intent → verified purchase proof → deterministic grant → transactional file/request/grant persistence → authenticated redemption → private signed URL → delivery/result bookkeeping → guarded review. A confirmed flaw in legacy file ownership is below; existing permanent-owner checks do not cover ownerless legacy records.

Drop Docs/inbound media → safe opaque key under secure/u/whatsapp/incoming from first S3 write → private service-request copy → ownership-gated staff/customer download. Legacy public originals remain a separately documented reconciliation task. S3 privacy and CDN privacy are distinct controls.

Razorpay webhook → HMAC check → durable event lease → provider readback/amount/reference validation → canonical order finalizer → invoice engine create/dedup/render/deliver → recorded result. Invoice delivery exists in source; completeness across all real customer paths remains unverified. Review records/invitations have separate completion and send claims; paid Submit Request invites follow saved details, Vault invites follow delivery acceptance. Unit evidence is not handset delivery evidence.

Wix signed webhook → AWS catalog webhook → catalog sync rereads Wix and Meta → identity-preserving desired plan/diff → scoped variant gates → provider mutation → independent readback. Current live sync cannot pass its read stage; source now targets a different catalog than live.

Browser Meta events use the configured Pixel, with catalog IDs derived through the retailer-id contract. Latest frontend explicitly labels the shared CAPI dataset as configured, requiring link verification in Events Manager. Configured IDs do not prove provider linkage, legitimate traffic receipt or catalog match diagnostics.

## Findings

| ID | Severity | Component | State | Finding |
|---|---|---|---|---|
| AUD-001 | HIGH | Vault/private files | CONFIRMED | Ownerless files may be adopted/listed/accessed using a verified matching phone; permanent customer identity is not required for these legacy rows. |
| AUD-002 | HIGH | Catalog reconciliation | CONFIRMED | Source target 1457045652952851 differs from live sync target 1607047307067517; old target cannot be read, new target is readable but empty. |
| AUD-003 | MEDIUM | Payment diagnostic | CONFIRMED | Live payment-config/check falsely reports local_only/zero active while payment-config/list reads Active configurations. |
| AUD-004 | HIGH | Customer QA identity | CONFIRMED | QA phone has a verified Cognito user but its CRM contact lacks checkoutCustomerId and customerUuid. |
| AUD-005 | HIGH | Native release | CONFIRMED | Native purchase and Wix writeback prerequisites/gates remain closed; no real paid journey evidence. |
| AUD-006 | MEDIUM | Release documentation | CONFIRMED | Native-catalog status contradicts published Flow, nominated QA recipient, current aliases and newer catalog configuration. |
| AUD-007 | MEDIUM | Deployment parity | CONFIRMED | Ten live archives hash-verified; several bundled modules differ from latest source. Reachability/behavior must be assessed before redeploying them. |
| AUD-008 | MEDIUM | Private download TTL | CONFIRMED in source | Website defaults to 60 seconds; direct WhatsApp document link defaults to six hours. Current live configured value and exposure require separate verification. |
| AUD-009 | MEDIUM | Catalog approval workflow | NOT VERIFIED | Persistent owner approval revision/hash queue and workspace actions are not demonstrated by current source/live evidence. |
| AUD-010 | MEDIUM | Legacy public uploads | NOT VERIFIED live | Source/handoff retains legacy public originals; object-level inventory and secure migration/deletion evidence absent in this audit. |
| AUD-011 | INFO | Git/test provenance | CONFIRMED | Archive-only baseline causes two Git-dependent tests to fail; rerun in a genuine detached checkout before classifying engineering failures. |

### AUD-001

Severity: HIGH. State: CONFIRMED. Component: vault_access.bind_file and secure-files customer listing/redemption. Evidence: bind_file allows ownerCustomerId in (None, identity.customer_id) then conditionally stamps it from phone; _customer_list/_owned_active_file also accept missing permanent owner. Operator upload stores ownerPhone/cognitoUsername but no ownerCustomerId. Impact: an ownerless historical file can attach to a recreated customer account/phone successor; file identifiers and matching verified phone do not prove original permanent ownership. Root cause: legacy phone fallback. Recommended fix: bind new uploads to a server-resolved Cognito sub, require the exact permanent owner on customer access, refuse automatic legacy adoption, leave explicit staff reconciliation. Tests required: same-phone/different-sub, missing owner, foreign file, revoked file, first upload binding and replay. Live verification: exact archive tests, inert auth probe, owner QA file. Rollback: captured secure-files31/service-requests3/business79 packages and aliases; shared helper must be deployed only in reachable consumers. No legacy record reassignment/deletion.

### AUD-002

Severity: HIGH. State: CONFIRMED. Component: catalog sync/configuration. Evidence: current manifest META_CATALOG_ID=1457045652952851; live version6 env=1607047307067517. Inspect invocation returns read_failed/applied0. Independent products read of old target returns Graph100/subcode33; new target returns200/products[] on business79. Impact: current Wix changes cannot propagate to the intended source target. Root cause: runtime/source target drift; old object inaccessible. Unsupported-get response cannot distinguish deletion from missing access. Recommended fix: reconcile ownership/WABA/Pixel and writer authority before a guarded target change; do not create replacement products to evade an access failure. Tests: scoped diff/foreign-item protection/read failure/no mutation. Live verification: full new catalog ownership/connection read, approved plan then independent item readback. Rollback: original env and catalog-sync6 alias. Do not open stock availability.

### AUD-003

Severity: MEDIUM. State: CONFIRMED. Component: business API payment diagnostics. Evidence: version79 check returns local_only and activeConfigs0, list returns WECAREDIGITAL/WECAREUPI Active. Source check still sends fields filter and reads obsolete payment_gateway shape; list correctly requests unfiltered edge and flattens data[].payment_configurations. Impact: operator UI contradicts provider/payment readiness and encourages erroneous provider recreation. Root cause: partial response-contract migration. Recommended fix: share unfiltered normalization and map provider_name/provider_mid without broadening payment authorization. Tests: nested provider payload, inactive/malformed/error response, flat compatibility, no mutation and pagination boundaries. Live verification: read-only check/list agree on exact immutable deployed version. Rollback: business79 package plus current guarded alias target.

### AUD-004

Severity: HIGH. State: CONFIRMED. Component: QA onboarding. Evidence: current Contacts phone-index query returns one nondeleted contact with no checkoutCustomerId/customerUuid; current customer-pool ListUsers returns one verified phone match. Impact: WhatsApp history/native eligibility properly fail closed despite an existing account. Root cause: website/contact linking step incomplete. Recommended fix: owner signs into existing account and completes supported verified-phone linking, then re-read both sides. Tests: existing identity/link conflicts and account recreation; no direct phone-only history transfer. Live verification: read-only customer command returns correct permanent customer/order partition after linking. Rollback: no audit mutation.

### AUD-005 to AUD-011

AUD-005: closed native flag on business79 and absent writeback/confirmed-contract flags on checkout40; secure independent-payment and Drop Docs attach flags false. No real purchase evidence. Keep closed until one verified payment/order/Wix/invoice/request-or-file/workspace/review journey passes. Owner pays personally. Rollback: no gate mutation.

AUD-006: dated native-catalog-release-status says Flow DRAFT/no QA recipient; live read says PUBLISHED and local authority nominates QA0044. Correct dated status with a current reconciliation pointer, preserving original historical deployment table. Test document IDs/status against fresh evidence; no live mutation.

AUD-007: package-source-comparison.json records byte differences. Business79 handler lacks serviceDesignDrafts entry present in current source; catalog6 handler difference is documentation. Shared module drift includes finalization/writeback in webhook56. Presence in a ZIP is not import reachability; no whole-fleet redeployment justified. Require exact consumer import/read paths and regression tests. Rollback is immutable captured version per target.

AUD-008: six-hour direct bearer URL is longer than the stated short-lived download goal. Inspect runtime TTL then shorten direct-link generation within an attested delivery contract. Preserve authenticated Vault download. Test configured TTL bounds and document delivery. Rollback: secure-files31. No direct media delivery in this audit.

AUD-009: approval queue remains pending in current rollout; inventory does not prove implemented owner actions. Implement persistent revision/hash approval before customer availability changes. Require changed-price/image rejection until reapproval, idempotent actions and independent provider readback. No product mutations in this audit.

AUD-010: private first-write source is present and live S3 blocks all public ACL/policy paths. Legacy CDN-open originals require object-specific inventory; bucket public blocking alone does not prove CloudFront object privacy. Prepare inventory and reviewed migration/deletion plan. No deletion performed.

AUD-011: first broad test run on archive:10332 passed,14 skipped,3 xfailed,2 failures, both missing Git provenance. Separate initial inherited-AWS-environment run interrupted in botocore after42 passes. Test rerun isolates AWS credentials/config and restores real Git metadata; no provider credentials supplied. This is environmental evidence, not source repair.

## Fresh live AWS

76 functions;69 live aliases;76 SnapStart ApplyOn=None. Seven functions without live alias require actual invocation-target review, especially edge associations. All configurations Active at read time. Business API $LATEST hash differs from live79; do not treat $LATEST as production. Full versions, hashes, roles, flags, layers, dates and alias revision IDs are in aws-lambda-evidence.json.

| Important function | Live version | CodeSha256 |
|---|---:|---|
| wecare-checkout |40|UvSMu1QxQappwmYrh5S2YxkSdtoceUCfk0GAFKvIxjg=|
| wecare-whatsapp-business-api |79|fGW4u2Knkc33y/ppQZylVOY5PH30hrmVVBsYJ3UJeDo=|
| wecare-inbound-whatsapp |92|uMQnayCVA6Px3rgKI5JgftfYIobT1Q4pKZqHBNe57us=|
| wecare-secure-files |31|AToCbKYvSEN9JZAZPu6K4DQMCOT5rbsotoz3CyqiA1s=|
| wecare-service-requests |3|f+NT3wxCRCSfRelSupJTAEvyYaQETGUfTrD6uXqjxDk=|
| wecare-razorpay-webhook |56|h9LRnYAhPjGkCg6tT1L8NwmYAwto2aAdNjofhsYcVEI=|
| wecare-invoice-engine |49|XPBw76dLHOAzUVsNz5drw9huk47bfHgxYpVZUi+kDbw=|
| wecare-meta-catalog-sync |6|9Nrpq65Z1Cd5ANxpCdTiHdylN9lijITni+ruPbCiKn4=|
| wecare-wix-store |37|oidx2+S1gKK/cugQkllFhtfZYu9LjBur4Tp/Pomn/Vc=|
| wecare-customer-orders |6|Isl/eyjE5ffuTIdZz5uBawQ4xZ23goQaeth69/bsYzk=|

HTTP API:384 routes/78 integrations,382 NONE/1 JWT/1 AWS_IAM,one authorizer.85 DynamoDB tables,7 buckets,7 EventBridge rules,73 metric alarms. Relevant order/payment/file/review/invoice table schemas and indexes inspected. DescribeTable ItemCount is approximate and does not certify zero records. S3 wecare-digital-get: all four public-access blocks true, policy IsPublic false, AES256 default encryption, versioning suspended, two lifecycle rules. Five relevant IAM roles and their inline/attached policies were read; broad shared-role grants are not automatically revoked without consumer mapping. No WAF/Security Hub creation is proposed.

Amplify1496 succeeded on7a1e1e44.1497 on53ed298e was RUNNING during inventory; final status requires readback. Hosting deployment success does not certify backend/source parity or a customer purchase.

## Fresh provider state

Meta developer app2238810740192680 is accessible through developer connector, admin role, business382642103987922, read/manage granted. This does not prove catalog permissions. Runtime Graph v25.0. Flow1107164111921876 PUBLISHED with no validation errors;1578178897413815 PUBLISHED; amendment3678132465672138 and Drop Docs1211063631104445 DRAFT. Three payment/download/review templates APPROVED. Read-only invocations pinned to business79. No Flow publish/change performed.

Wix sitec993128b-26be-41cd-9fcd-904abe23462f is CatalogV3, INR. Live productdf976a0a-f582-4535-b2e1-d532f348bd27 revision5; Submit Request e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b ₹99; Amendment864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b ₹99; Drop Docsdb166bc8-a763-41ec-9f65-0f718f18155a ₹350; Vaultdcff995e-448c-493a-9259-f6a82ccdc2b4 ₹49. All choices have distinct linked4096px artworks. The variants' fallback media remains the product's Submit Request artwork, so consumers must use choice-linked imagery where appropriate. Shipments/Review remain utility entries.

Pixel3411484995761247 and shared CAPI dataset4554612361454941 are source-configured. Catalog source1457045652952851 is newly readable/empty; live writer still uses old1607047307067517. Dataset linkage, event reception and legitimate Purchase/catalog-match diagnostics are NOT VERIFIED. No synthetic Purchase events sent.

## Current-question answers

| # | Question | Evidence-based answer |
|---|---|---|
|1|Local commit|Foreign stack62454978; isolated audit53ed298e.|
|2|origin/stack|53ed298e after second successful fetch; concurrent changes require final fetch.|
|3|Parallel/dirty work|Yes, protected foreign paths/worktree; current chat tool found no other active listed Codex chat, which does not exclude Kiro activity.|
|4|Complete work|Published paid/review Flows; approved templates; Wix prices/variants/images; private first-write source; existing canonical order/receipt implementations. Scope-specific, not E2E.|
|5|Historical pending now fixed|Raw checkout reader replaced by list contract; paid Flow publication; QA nomination; invoice-send source exists.|
|6|Genuinely pending|Permanent file ownership repair, diagnostic consistency, catalog runtime reconciliation/approval, QA link, controlled paid journeys.|
|7|Live versions|Table and full fresh JSON above.|
|8|Source matches?|Important handlers mostly match; business entry drift and multiple shared module differences. Byte comparison preserved; full fleet parity not claimed.|
|9|Flags|Native/writeback closed; secure payment/dropdocs attach false; sync enabled/dry-runfalse/force-out-of-stocktrue.|
|10|payment-config/raw|Retired caller; current list route works; raw still falls to phoneId-required generic route. No current caller uses raw.|
|11|Meta payment state|Active gateway/UPI returned by list; check diagnostic defective; no real charge readiness certification.|
|12|Catalog read_failed why?|Old target Graph100/subcode33 inaccessible; source/live target drift confirmed; deletion-versus-permission not determined.|
|13|Catalog accessible?|Old target no; new source target yes, empty products. Ownership/connections unverified.|
|14|Wix propagated to Meta?|No current evidence; sync0 applied/read_failed.|
|15|Wix prices/IDs|Fresh live revision5 confirms99/99/350/49 and original four variant IDs.|
|16|QA verified?|Phone verified in Cognito; CRM checkout identity/UUID linkage missing.|
|17|Paid Flow|PUBLISHED, no validation errors, live endpoint.|
|18|Review Flow|PUBLISHED, no validation errors.|
|19|Native safe to enable?|No: security/identity/writeback/real journey gates incomplete.|
|20|Writeback safe to enable?|Not attested live; remain closed.|
|21|One payment/one order?|Source conditional reservation and replay tests; no real live payment verification in this run.|
|22|Submit parent linkage|Transactional permanent-owner condition in source; live QA absent.|
|23|Vault correct file?|Bound purchase/grant conditions exist; legacy phone adoption remains a confirmed defect.|
|24|Private uploads?|New inbound secure first-write source; bucket private settings verified; legacy object/CDN inventory pending.|
|25|Invoices correct/dedup?|Source send/render/dedup paths and current tests; real path/delivery absent.|
|26|Review dedup?|Persisted send/completion claims and tests; no live qualifying-event/handset check.|
|27|Workspace once/order?|Canonical association/projection source exists; real customer replay/browser rows not verified.|
|28|Tracking IDs correct?|Current source IDs identified; external dataset/WABA/catalog linkage and legitimate traffic unverified.|
|29|Owner actions|Sign into existing QA account/link verified WhatsApp; personally pay after gates; credential rotation/restricted decisions remain owner-only.|
|30|Provider blockers|Old catalog inaccessible; new catalog connection/ownership and write contract attestation need provider evidence.|
|31|Engineering responsibility|Permanent file ownership, diagnostic contract, source/runtime catalog reconciliation, approval queue, exact package parity and release evidence.|

## Tests and boundaries

Fresh frontend Vitest:1582 passed/11 skipped,122 files passed/2 skipped. TypeScript noEmit exit0. Fresh offline broad Python archive:10332 passed/14 skipped/3 xfailed/2 Git-provenance failures. Genuine Git checkout rerun in progress when this initial audit was written. Previously quoted totals are not substituted for fresh runs. No production/customer browser journey, real payment, webhook replay against production, customer send or provider write was performed. Ten live ZIP hashes verified; member comparisons do not prove all76 runtime import closures. Full all-region infrastructure, full secret history scan, complete IAM reachability, legacy file data reconciliation and legitimate Meta analytics diagnostics remain explicitly unverified.

## Repair order and rollback boundary

First tighten permanent private-file ownership and add regressions, then correct the demonstrated read-only payment diagnostic; reconcile source/tests/documentation. Use preserved live archives and exact-member overlays only where standing authority applies. Re-fetch stack and re-read code/alias revisions before any upload. If live revisions/hashes changed, stop that deployment and reconcile. Any production change must have a separate before/after record; none occurred before this initial audit.
