# Requirements — AWS-Native Consolidation & Cost Optimization

Status: DRAFT (audit complete; implementation staged behind owner-approval gates)
Account: 775261844268 · Region: us-east-1 · Amplify app: d22dm4b0jn71jw (wecare.digital)
Default/prod branch: `stack` · Working branch: `feat/aws-native-consolidation`

This spec governs three independent workstreams that share AWS infrastructure,
credentials, and deployment workflows. They MUST NOT be combined into one
production deployment. Each has its own cutover and rollback.

- **Workstream A — Complete Wix removal** (blog + commerce → AWS-native).
- **Workstream B — Secrets Manager consolidation** (cost + least-privilege).
- **Workstream C — Lightsail Micro→Nano** feasibility / retirement.

## Verified current state (evidence, 2026-10-14)

- 77 Lambda functions, 85 DynamoDB tables, 7 S3 buckets, 1 Amplify app,
  1 Lightsail `micro_3_0` instance (`wecare-voice-bot`, 1GB/2vCPU/40GB,
  static IP `52.3.44.165`, snapshot `wecare-voice-bot-backup-20261007`).
- 22 active Secrets Manager secrets; 13 already scheduled for deletion.
- **Wix is still the authoritative runtime backend for BOTH blog and commerce.**
  There is no AWS-native blog store or product catalog-of-record. The AWS layer
  is a thin proxy/cache in front of Wix plus a DynamoDB SEO audit/draft pipeline.
- `wecare/wix/headless-api-key` was accessed 2026-10-14 — the Wix path is live.
- The commerce *transaction* backend (payment_attempt, order_keys, order_creation,
  razorpay-webhook) is already AWS-native and verified; it only reads totals from
  and writes orders back to Wix.

## Glossary of statuses

COMPLETED · IMPLEMENTED_NOT_DEPLOYED · VERIFIED_IN_TEST · READY_FOR_OWNER_APPROVAL ·
BLOCKED · NOT_STARTED.

---

## Workstream A — Wix removal

### Requirement A1 — AWS is authoritative for the blog
**User story:** As the site owner, I want blog content stored and served from AWS
so the public blog keeps working if every Wix endpoint becomes unreachable.

#### Acceptance criteria
1. WHEN the public blog list/detail is requested THEN the content SHALL be served
   from an AWS-native store (DynamoDB + S3), with no runtime call to any
   `wixapis.com` host.
2. WHEN `WIX_CREDENTIALS_DISABLED=true` AND all Wix hosts are network-blocked
   THEN `npm run build` SHALL still produce a non-empty blog and sitemap.
3. The AWS blog store SHALL hold published posts, drafts, rich content, authors,
   categories, tags, media refs, timestamps, slugs, SEO title/description,
   canonical URLs, and redirect info.
4. The existing admin Blog Studio SHALL create/edit/delete/publish against the
   AWS store with no loss of current functionality.
5. The export that seeds the store SHALL reconcile against fresh authoritative
   Wix counts (published + draft) with a checksum report.

### Requirement A2 — AWS is authoritative for the product catalog
#### Acceptance criteria
1. The AWS catalog SHALL hold products, variants/options, SKUs, prices (integer
   minor units), currency, inventory, categories, images, draft/active/archived
   state, SEO URLs, and tax classification.
2. WHEN the shop static pages are generated THEN the catalog artifact SHALL be
   produced from AWS, not from a committed Wix snapshot.
3. `src/content/wix-catalog.json` SHALL NOT remain a permanently authoritative
   Wix snapshot after cutover.
4. Content/catalog publishing SHALL NOT require a whole-site Amplify rebuild for
   routine scheduled polling.

### Requirement A3 — Provider-independent commerce
#### Acceptance criteria
1. Server-side pricing, discounts, taxes, shipping, inventory validation, stock
   reservation, checkout prep, order creation/finalization, customer history,
   refund reconciliation, and fulfillment transitions SHALL have AWS-native
   implementations that do not require Wix.
2. The authoritative payment amount SHALL come from the AWS catalog/cart, never
   from client-supplied prices, in integer minor units (INR paise).
3. Checkout and webhook processing SHALL be idempotent; no duplicate charges or
   orders; payment-signature verification preserved; order finalized only after
   confirmed payment state (except explicitly supported non-prepaid flows).
4. Existing Razorpay and Meta integrations SHALL be preserved. No second
   independent payment settlement flow SHALL be created.

### Requirement A4 — Meta/WhatsApp catalog sync reads AWS
#### Acceptance criteria
1. `wecare-meta-catalog-sync` SHALL read the AWS-native catalog.
2. Existing catalog identity, approved products, variant mappings, inventory
   correctness, and approval/dry-run gates SHALL be preserved.
3. The Wix catalog-webhook dependency SHALL be removed only after AWS-native
   product-change events are proven to drive sync.

### Requirement A5 — SEO & URL preservation
#### Acceptance criteria
1. `/blog`, `/post/[slug]`, `/shop`, `/shop/[slug]` URLs SHALL be preserved.
2. Metadata, canonical URLs, JSON-LD, sitemap, RSS, search index, image paths,
   and redirects SHALL be preserved; an old-vs-new URL diff SHALL show no mass
   404s.
3. A content-API failure SHALL NOT cause an empty blog to be published.

### Requirement A6 — Cutover gate
WHEN all of A1–A5 are proven, source data reconciled, historical orders
accessible, and production verified to operate with Wix API access blocked, THEN
and only then SHALL Wix services be revoked/canceled — and only with owner
approval.

---

## Workstream B — Secrets consolidation

### Requirement B1 — Standard, not a single mega-secret
#### Acceptance criteria
1. There SHALL be one secret-management standard (naming, access helper, IAM
   pattern) — NOT one JSON object holding every provider credential.
2. Grouping SHALL occur only where every consuming role legitimately needs every
   field AND rotation lifecycles are compatible.
3. Security-sensitive items (payment API creds, webhook verification secrets, OTP
   pepper, signing/encryption keys, admin creds, backup passphrase, privileged
   GitHub creds) SHALL remain isolated.

### Requirement B2 — Dependency inventory & access matrix
#### Acceptance criteria
1. Every active secret SHALL be documented: name, region, purpose, owning
   service, consuming Lambdas, IAM roles, rotation support/status, last-access,
   KMS arrangement, required availability, candidate action.
2. Candidate action SHALL be one of KEEP_ISOLATED, GROUP_WITH_SAME_SECURITY_DOMAIN,
   MOVE_TO_PARAMETER_STORE, ROTATE, RETIRE_AFTER_CUTOVER, NEEDS_OWNER_REVIEW.
3. Secret VALUES SHALL NOT be retrieved during discovery or written anywhere.

### Requirement B3 — Centralized access helper
#### Acceptance criteria
1. A shared, typed secrets-access library SHALL provide logical naming,
   env-aware config, least-privilege IAM, cached runtime retrieval, rotation
   awareness, no secret values in logs, explicit failure on missing values, and
   no fallback to hardcoded credentials. Unit tests SHALL use synthetic fixtures.
2. If the existing shared library already satisfies this, broad refactoring SHALL
   be avoided.

### Requirement B4 — Wix secret retirement (gated)
#### Acceptance criteria
1. `wecare/wix/headless-api-key`, `wecare/wix/catalog-webhook`,
   `wecare/wix/app-oauth` SHALL remain until Workstream A passes acceptance.
2. After approval: consumers removed, deployment vars removed, IAM grants removed,
   provider access disabled, no remaining callers verified, deletion scheduled
   with a recovery window, and production confirmed to no longer need them.
3. Force-delete without a recovery window SHALL NOT occur unless separately and
   explicitly approved.

### Requirement B5 — IAM cleanup
#### Acceptance criteria
1. Wix-specific grants (e.g. GetSecretValue on `wecare/wix/headless-api-key`) on
   `wecare-checkout-role`, `wecare-meta-catalog-sync-role`,
   `wecare-wix-catalog-webhook-role`, `wecare-digital-lambda-role` SHALL be
   removed only after confirming the apps no longer need them.
2. The shared Lambda execution role SHALL NOT be deleted/disabled.
3. Non-Wix grants (payment, Meta, logging, infra) SHALL be preserved.
4. IAM changes SHALL be reconciled through IaC so obsolete access does not
   reappear on next deploy.

### Requirement B6 — Backup hygiene
#### Acceptance criteria
1. Future backup archives (`scripts/secrets_backup.py` →
   `wecare-credential-backups-775261844268`) SHALL exclude retired credentials.
2. Older S3 object versions and any local encrypted copies SHALL be reviewed
   under an approved retention policy; provider keys revoked so historical copies
   cannot authenticate.
3. No backup deletion SHALL occur without explicit authorization; the shared
   backup bucket SHALL NOT be deleted.

### Requirement B7 — GitHub PAT review
#### Acceptance criteria
1. The claim that `wecare/github-pat` is historically exposed and over-privileged
   SHALL be verified WITHOUT printing/retrieving the token.
2. IF still active and compromised THEN an urgent rotation/replacement plan
   (narrower scopes or GitHub App) SHALL be presented; any rotation requires
   explicit approval and workflow coordination.

---

## Workstream C — Lightsail Micro→Nano

### Requirement C1 — Evidence-based capacity verdict
#### Acceptance criteria
1. A read-only capacity audit (free -m, df -h, lsblk, vmstat, ps, systemctl, ss,
   Asterisk status, swap/OOM history, cert renewal) SHALL be collected IF
   authorized host access exists; otherwise the assessment SHALL be marked
   INCOMPLETE. Low CPU alone SHALL NOT justify a downgrade.
2. Active service inventory SHALL distinguish required (Asterisk/SIP for Meta
   WhatsApp Calling) from legacy (Airtel SMS proxy on :8899).

### Requirement C2 — Fresh-Nano migration, never in-place downgrade
#### Acceptance criteria
1. Because Lightsail cannot restore a larger snapshot onto a smaller bundle, the
   plan SHALL provision a FRESH nano and migrate workload/config/certs/data.
2. Scripts SHALL live in `scripts/lightsail-nano-migration/`, be idempotent where
   possible, support dry-run, validate params, verify account/region, embed no
   secrets, perform no unauthorized destructive ops, checksum transfers, and
   include a rollback runbook.

### Requirement C3 — Gated cutover
#### Acceptance criteria
1. The static IP SHALL move only during an approved cutover; Micro SHALL be kept
   for rollback until acceptance; retirement SHALL be a separate approved step.
2. No silent changes to customer phone numbers, WABA registration, or Meta
   Calling settings.

---

## Cross-workstream & cost

### Requirement X1 — Sequencing safety
Audits → CI → Wix export/archive → AWS blog/catalog data → store/checkout →
e2e tests → gated Wix cutover → Wix secret/IAM cleanup → unrelated secret
consolidation → Lightsail (independent) → final cost audit. Shared-infra
invariants in design §Shared rules.

### Requirement X2 — Honest cost model
A deterministic script (`scripts/aws_cost_model.py`) SHALL compute every cost
figure; POTENTIAL and REALISED savings SHALL be reported separately; marginal
recurring savings SHALL be shown against migration effort.
