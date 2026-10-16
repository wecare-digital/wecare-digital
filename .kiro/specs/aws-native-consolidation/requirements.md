# Requirements — AWS-native consolidation

Reconciled 2026-10-16 against stack `568bd4d2`, repository source, the full production
export and live AWS metadata. Account 775261844268; primary region us-east-1;
Amplify app `d22dm4b0jn71jw`. Counts and operational findings are dated observations,
not permanent acceptance criteria. See `tasks.md` for the historical execution record.

## Current architecture and acceptance criteria

### A1 — Native blog
- Published content uses the existing `stack-wecare-digital-SeoToolsTable` and native
  storage modules. Do not create a parallel BlogPostsTable based on the obsolete design.
- Preserve published and draft records, rich content, author/category metadata, slugs,
  timestamps, SEO fields and media references.
- Preserve public list/detail reads and authenticated admin editing/publishing.
- A production build must fail on an incomplete API read rather than publish an empty
  or truncated blog. The fresh export contains 1,421 posts.

### A2 — Native catalog and commerce
- `stack-wecare-digital-ProductsTable` supplies catalog products, variants, integer-paise
  prices, inventory and metadata. Generate the storefront snapshot from this store.
- Reuse the existing cart, orders, payment attempts, reservation, refund and reconciliation
  implementation. Preserve idempotency, payment verification and owned customer history.
- Keep Razorpay payment identifiers, prices and settlement behavior unchanged.
- Preserve deletion protection on ProductsTable, CommerceKeys and CartTable.

### A3 — Meta publication
- Sync reads the native product catalog. New retailer IDs use `WECARE.DIGITAL:`;
  consumers accept only this namespace after the approved migration.
- Preserve approval, inspection, dry-run and inventory gates. The product stream mapping
  is enabled; do not describe sync as permanently disabled.
- The approved 21-item migration does not resolve the separate historical Contribute
  item. Establish publication eligibility and obtain a product decision before changing it.

### A4 — URL, presentation and export integrity
- Preserve public paths, menu style, canonical URLs, metadata, JSON-LD, RSS, sitemap,
  image paths and the complete blog search index.
- Apply CON1 Phase 1 without silently deciding C3/C5/C6/C8/C10/C15/C18/W8.
- Route retirement follows a separate traffic, callback and dependency audit after Phase 1.
- Build and Route auth remain informational workflows as explicitly requested by the owner.

### A5 — Operational readiness
- Report actual build, test, browser and AWS results. A green source test suite does not
  establish a healthy production deployment or an empty dead-letter queue.
- Confirm deployed package dependencies before replaying failed ingestion work.
- Preserve rollback packages/versions and configuration for each production repair.

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

### Requirement B4 — Retired credential dependencies
1. Retired provider credentials SHALL NOT be recreated or reintroduced through deployment defaults.
2. Retirement requires a consumer inventory, IaC reconciliation, recovery-window review,
   and production verification. Historical evidence is not a current runtime dependency.
3. Force-delete without a recovery window requires separate explicit approval.

### Requirement B5 — IAM cleanup
1. Remove obsolete grants only after verifying consumers and the effective policy set.
2. Preserve the shared execution role and unrelated payment, Meta, logging and infrastructure access.
3. Reconcile changes through IaC so obsolete access does not return on deployment.

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

## Workstream C — Active voice host

- The fresh live metadata shows `wecare-voice-bot-nano` running on `nano_3_0`, with the
  existing static IP attached. The old Micro migration is historical, not a pending downgrade.
- Preserve Asterisk/SIP, TLS, customer numbers, WABA identity and Meta Calling settings.
- Keep the retired SMS proxy absent. Required Plivo voice, AWS messaging and Sinch RCS
  integrations are independent of that retired proxy.
- Guest memory, swap, OOM, service and certificate health require authorized host evidence;
  API instance state alone does not prove them healthy.
- Backup/retention decisions and destructive host changes require explicit authorization.

## Cross-workstream rules

- Read-only audits do not fetch secret values. Keep provider credentials isolated by
  consumer domain and rotation lifecycle; never create one shared mega-secret.
- Do not combine unrelated credential, payment and voice changes in one deployment.
- Preserve existing users, customer data, historical invoices, media, hosting and recovery data.
- Record potential and realised cost savings separately using `scripts/aws_cost_model.py`.
