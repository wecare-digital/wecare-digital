# AWS cost-reduction plan, 2026-10-27

Companion to `docs/audits/platform-audit-20261027.md`, which holds the evidence. Account
`775261844268`, region `us-east-1`. All dollar figures are **gross list-price charges before
credits**, computed programmatically from Cost Explorer and CloudWatch reads on 2026-10-27.

## The honest framing

- **Cash spend today is $0.00.** Credits absorbed the entire bill in August ($61.73),
  September ($101.30) and October to date ($145.17). Every saving below extends the credit runway
  until the credits run out; only then does it become cash. Credit balance and expiry are visible
  only in the Billing console (owner).
- **Nothing in this plan has been executed against AWS.** The repository changes are on branch
  `audit/platform-performance-cost-seo-20261027` and take effect only when the owner merges and
  pushes (Amplify then builds and deploys). "Costs actually removed" is therefore **$0.00** today.
- Labels: **ACTUAL** = measured; **ESTIMATE** = modelled from measured rates; **OWNER DECISION** =
  needs explicit authorization because it is a production, billing, provider, IAM or
  destructive change.

## Baseline (ACTUAL)

| Period | Usage | Support | Gross | Net after credits |
|---|---:|---:|---:|---:|
| September 2026 (complete) | 72.30 | 29.00 | 101.30 | 0.00 |
| October 1-26 | 102.36 | 42.81 | 145.17 | 0.00 |
| Cost Explorer forecast, October | | | 169.84 | |
| Cost Explorer forecast, November | | | 147.04 | |

## Next 30 days, by scenario (ESTIMATE)

Build-minute lines use October's average volume (218.6 build-minutes a day, about 50 builds). The
last week ran nearer 70 builds a day, which would add about $27 to scenario A.

| Scenario | What changes | Gross $/30 d | Step saving |
|---|---|---:|---:|
| A | Nothing deployed | 175.23 | |
| B | Merge the branch (Amplify build overhead −94 s/build) | 151.83 | 23.40 |
| C | + path-filtered Amplify builds with a 6-hourly content rebuild | 130.21 | 21.62 |
| D | + backup account `…5408` back to Basic support | 101.21 | 29.00 |
| E | + right-sized shop/catalog images | 91.22 | 9.99 |
| F | + management account to Basic support, Lambda error alarms consolidated | 59.12 | 32.10 |

Scenario F is about **$116.11 a month below A**. What remains in F is usage-dependent or
production baseline: Amplify builds and hosting (~$27.92), Secrets Manager ($6.97), Lightsail SIP
server ($5.32), alarms ($4.49), KMS ($4.10), API Gateway, messaging, DynamoDB, Lambda, S3,
Route 53 and ECR. A literal $0 is not reachable without removing production services, and this
plan does not propose that.

## Changes

### C1. Amplify build overhead (repository change, done on branch)

| | |
|---|---|
| Current state | Every BUILD step (~252 s) re-installs 1,692 default global npm packages via `nvm install` (51 s) and round-trips a `node_modules` cache that `npm ci` deletes (~43 s) |
| Live evidence | Build logs of jobs 276-278; Cost Explorer `USE1-BuildDuration` 5,683.8 min ($56.84) Oct 1-26 |
| Repo evidence | `amplify.yml` preBuild and `cache.paths` |
| Monthly cost | $65.58 build minutes at October's average volume |
| Proposed state | `nvm install --skip-default-packages 24`, a Node ≥ 24 assertion, no `cache:` block |
| Expected saving | **$23.40/month** (up to $32.90 at the last week's volume), ESTIMATE; also ~1.5 min faster deploys |
| Implementation | Commit `02f1e9ee5` on the audit branch |
| Risk | Low. If a command needed a global package the build fails before deploy and the previous deployment stays live. The new assertion fails the build instead of silently using another Node |
| Rollback | Revert the commit |
| Validation | First Amplify build after merge: BUILD step ≤ ~170 s; log shows no "Installing default global packages"; `node -v` v24.x |
| Owner approval | **Yes**: merging and pushing to `wecare.digital` is a production deploy |

### C2. Path-filtered Amplify builds

| | |
|---|---|
| Current state | Auto-build on every push; 136 of 256 recent successful builds changed only backend, docs or tests, and 4 changed nothing |
| Live evidence | Amplify job list joined to `git diff` between consecutive built commits |
| Monthly cost | $42.18 builds after C1 + about $2.3 of API Gateway/Lambda/DynamoDB from each build's blog fetch |
| Proposed state | Disable auto-build on the `wecare.digital` branch; a GitHub Actions workflow triggers `amplify start-job` only when a frontend input changes (`src/`, `public/`, `content/`, `shared/`, `config/`, `package*.json`, `next.config.js`, `tsconfig.json`, `amplify.yml`, `customHttp.yml`, `.nvmrc`, `scripts/generate-*.js`, `scripts/blog-merges.js`, `scripts/guard_braces_depth.cjs`, `scripts/checkout_release_check.py`, `scripts/sync_faq.py`, `scripts/verify_public_bundle_secrets.py`, `amplify/functions/core/faq-handler/**`), plus a scheduled rebuild every 6 hours, because blog posts reach the static site only through a build and nothing else triggers one |
| Expected saving | **~$21.62/month** (ESTIMATE: builds ×116/256 = $19.11, plus $3.39 for four scheduled rebuilds a day, plus a smaller share of build-time API Gateway/Lambda/DynamoDB) |
| Implementation | A GitHub OIDC role allowed only `amplify:StartJob` on `arn:aws:amplify:us-east-1:775261844268:apps/d22dm4b0jn71jw/branches/wecare.digital/jobs/*`; branch `enableAutoBuild=false` |
| Risk | Medium: a missed path in the filter means a frontend change does not deploy until the next scheduled rebuild. Mitigation: the filter errs broad, and a manual `workflow_dispatch` stays available |
| Rollback | Re-enable auto-build on the branch (one setting) |
| Validation | A backend-only push creates no Amplify job; a `src/` push does; the 6-hourly job runs |
| Owner approval | **Yes**: IAM role creation and an Amplify branch setting change |

Native `AMPLIFY_DIFF_DEPLOY` was considered and rejected: it diffs a single root, so it cannot
express this repository's frontend inputs, and skipped diff builds have been reported failing on a
missing artifact ([amplify-hosting#3268](https://github.com/aws-amplify/amplify-hosting/issues/3268)).

### C3. Business Support+ on two accounts (OWNER DECISION)

| | |
|---|---|
| Current state | Business Support+ ($29/month minimum per account) on the management account and, since Oct 17, on the backup account `…5408` |
| Live evidence | Cost Explorer `RECORD_TYPE=Support` by linked account: $29.00 (4268) and $13.81 prorated (5408) in October |
| Monthly cost | $58.00 from November |
| Proposed state | Owner chooses: keep both; keep only the management account; or Basic on both |
| Expected saving | $29.00/month per account moved to Basic |
| Risk | Losing 24×7 technical cases and the Support API on that account. The backup account holds replicas, so its incident exposure is low; Business-level support for the production account is a business-continuity choice |
| Rollback | Re-subscribe (30-day minimum commitment applies again) |
| Note | Developer and legacy Business plans end on 2027-01-01, so Basic or Business Support+ are the choices ([AWS Support plans](https://docs.aws.amazon.com/awssupport/latest/user/aws-support-plans.html)) |

### C4. Right-sized shop and catalog images

| | |
|---|---|
| Current state | 28 product images exist only as 4096×4096 PNG masters (2.0-2.6 MB each, 72 MB) and `/shop/` renders them as cards; `/get/` logo (1080×1080, 30 KB) shown at 60 px |
| Live evidence | S3 listing of `secure/d/public/catalog-deploy/catalog/products/`; Lighthouse `/shop/` 14.6 MB images; access-log hour with 3.03 GB of catalog-media egress |
| Monthly cost | Most of Amplify's $15.37/month data transfer, plus catalog-media Lambda time |
| Proposed state | Generate 512 px and 1024 px WebP derivatives next to each master (same prefix, new keys, masters untouched); allow those names in `catalog-media`'s `NAME` regex; render `srcset`/`sizes` on shop cards |
| Expected saving | ~$10/month (ESTIMATE: ~65% of transfer) and the largest real-user win on `/shop/` |
| Risk | Low: new objects only; nothing a Meta-approved template references is moved or renamed |
| Rollback | Revert the front-end change; the masters never moved |
| Validation | `/shop/` image bytes < 1 MB in Lighthouse; derivative URLs return 200 |
| Owner approval | **Yes**: uploads to the production media bucket and a Lambda deploy |

Interim, repository-only alternative: have the browser harness (`tools/browser/lib/browser.js`)
answer `wecare.digital/api/catalog-media/*` and `/get/o/stream/media/*` with local placeholders of
the same dimensions, which removes the CI-driven share of that egress without touching
production.

### C5. CloudWatch alarms (OWNER DECISION)

| | |
|---|---|
| Current state | 85 alarms (10 free, 75 × $0.10), all `OK`: 32 AWS/Lambda, 26 custom, 13 DynamoDB, 7 SQS, others |
| Monthly cost | $7.59 |
| Proposed state | Replace the 32 per-function Lambda error alarms with one account-level `AWS/Lambda Errors` alarm plus a handful kept for payment and webhook functions |
| Expected saving | ~$3.10/month |
| Risk | Less specific alerts: the notification says "a Lambda failed", not which one, for the consolidated set |
| Rollback | Re-run `scripts/provision_lambda_alarms.py` |

Log ingestion (3.76 GB in 30 days) is inside the CloudWatch free tier and costs $0; no logging
cut is proposed for cost. Hygiene items that cost nothing: set 30-day retention on the 8 CodeBuild
log groups that have none and on the `us-west-1` Lambda@Edge replica group; delete the orphan
`/aws/lambda/wecare-coupons` group (owner).

### C6. Secrets Manager (OWNER DECISION, keep secrets secret)

| | |
|---|---|
| Current state | 17 active secrets ($0.40 each), 10 scheduled for deletion (not billed) |
| Monthly cost | $6.97 |
| Candidates | `wecare/plivo-answer` + `wecare/plivo/api`, and `wecare/razorpay-webhook` + `wecare/razorpay/api`, are two families each; `wecare/meta/payments` has no runtime reference under `amplify/` (2 operational references) |
| Expected saving | $0.80-1.20/month if two or three are merged |
| Risk | A consumer missed during a merge fails closed. Merge only with `scripts/secrets_access_matrix.py` and `scripts/verify_secret_consumption.py` evidence |
| Not proposed | Moving any credential to SSM, env vars or config to save $0.40 |

### C7. ECR lifecycle for `wecare-docs-scraper` (OWNER DECISION)

13 images, 12.0 GB, no lifecycle policy; the function pins one digest. A policy keeping the
deployed digest and the newest three saves an estimated $0.20-1.00/month. Deletes images, so it
needs approval; rollback is a rebuild from source.

### C8. Meta catalog sync stream batching (OWNER DECISION, no cost change)

Both `meta-catalog-sync` mappings use BatchSize 1, so each product edit triggers two full
reconciles. Raising BatchSize to 100 with a 30-60 s window coalesces bursts; each invocation
reconciles the whole catalog anyway, so no record is lost. Cost impact is negligible ($0.10/month);
the value is fewer Meta Graph reads.

### C9. Items reviewed and deliberately left alone

| Resource | Why it stays |
|---|---|
| Lightsail nano + static IP ($5.32) | Serves `sip.wecare.digital` (SIP/TLS 5061, RTP 10000-60000/udp); real-time media needs a long-lived host. The micro standby is already gone |
| KMS, 4 keys ($4.10) | All four show use in CloudTrail in 30 days (signing, two OAuth custody keys, the Secrets Manager key). Moving five secrets to `aws/secretsmanager` would save $1 and remove key-policy separation |
| Six MCP HTTP APIs | Separate security boundaries by design; HTTP APIs have no fixed charge |
| DynamoDB, 76 tables | All on-demand; 11.7 MB total; empty tables cost $0. `AdClickAttributionTable` is a hygiene retirement candidate, not a saving |
| Lambda arm64 migration | ~$0.25/month saving against a redeploy of 70 functions plus layer rebuilds |
| Toll-free number (…1209, $2.00) | Carries outbound SMS (October message fees exist) |
| CloudTrail bucket requests (~$0.58) | Security audit trail; already on a 7-day lifecycle |

## Owner approvals, in order of value

1. Merge and push the audit branch (production deploy) - enables C1 and the performance and SEO
   fixes.
2. Business Support+ choice for `…5408` and for the management account (C3).
3. Path-filtered builds: OIDC role + `enableAutoBuild=false` (C2).
4. Derivative image upload and `catalog-media` deploy (C4).
5. Alarm consolidation (C5), secret merges (C6), ECR lifecycle (C7), ESM batching (C8).
6. Create an AWS Budget (none exists) so a credit lapse or a build storm is noticed.
