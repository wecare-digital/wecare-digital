# AWS cost-reduction plan, 2026-10-27

Companion to `docs/audits/platform-audit-20261027.md`, which holds the evidence. Account
`775261844268`, region `us-east-1`. All dollar figures are **gross list-price charges before
credits**, computed programmatically from Cost Explorer and CloudWatch reads on 2026-10-27.

**Revision, evening of 2026-10-27.** Scenario E was corrected from $9.99 to $2.63. C1 now
accounts for #1722, another session's npm-cache change that went live on the base the same
evening. With both changes, F is $68.69 rather than $59.12. The blog-fetch cost in C2 and C10 is
now computed rather than ranged. The scenario note now gives run-rates at recent build volume,
and C10 covers the 27 October CI transfer spike.

## The honest framing

- **Cash spend today is $0.00.** Credits absorbed the entire bill in August ($61.73),
  September ($101.30) and October to date ($145.17). Every saving below extends the credit runway
  until the credits run out; only then does it become cash. Credit balance and expiry are visible
  only in the Billing console (owner).
- **Nothing in this plan has been executed against AWS.** The repository changes are on branch
  `audit/platform-performance-cost-seo-20261027` and take effect only when the owner merges and
  pushes (Amplify then builds and deploys). "Costs actually removed" by this audit is therefore
  **$0.00** today. One overlapping change from another session, #1722, went live on 27 October
  and is worth an estimated $6.57/month at October-average volume (C1).
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

Build-minute lines use October's average volume (218.6 build-minutes a day, about 50 builds).
Recent volume is higher. At the 24-26 October run-rate (81 builds a day) the build line is $89.51
instead of $65.58, and the five usage lines (builds, Amplify transfer, API Gateway, DynamoDB,
Lambda) together come to $20.97 more than in scenario A ($21.13 more at the 14-26 October
run-rate). Cost Explorer has no data for 27 October yet, so neither figure includes that day's
$2.77 of transfer.

| Scenario | What changes | Gross $/30 d | Step saving |
|---|---|---:|---:|
| A | October-average baseline, before #1722 | 175.23 | |
| B | #1722's npm download cache (live since 27 October, −26.4 s/build measured) + merge this branch (`nvm`, −51 s/build) | 155.96 | 19.27 |
| C | + path-filtered Amplify builds with a 6-hourly content rebuild | 132.42 | 23.54 |
| D | + backup account `…5408` back to Basic support | 103.42 | 29.00 |
| E | + right-sized shop/catalog images | 100.79 | 2.63 |
| F | + management account to Basic support, Lambda error alarms consolidated | 68.69 | 32.10 |

Correction 1: the first version of this table credited E with $9.99, on the assumption that
catalog images were about 65% of Amplify transfer. That came from a single sampled window on
27 October, which the new CI workflow dominated. `wecare-catalog-media` has served traffic only
since 22 October: 1,220 requests on 22-26 October at 2.4 MB each, which is $2.63 a month at that
rate. E now removes at most that amount.

Correction 2: B assumed this branch removes 94 s per build (51 s `nvm` plus 43 s of
`node_modules` cache). Another session's #1722 has since replaced that cache with npm's download
cache on the base, measured at −26.4 s per build, and the merge keeps it. B is now $6.57 (#1722,
already live) plus $12.70 (this branch's `nvm` change). C, D, E and F carry the higher build line
forward.

Scenario F is about **$106.54 a month below A**. What remains in F is usage-dependent or
production baseline: Amplify builds and hosting (~$37.49), Secrets Manager ($6.97), Lightsail SIP
server ($5.32), alarms ($4.49), KMS ($4.10), API Gateway, messaging, DynamoDB, Lambda, S3,
Route 53 and ECR. A literal $0 is not reachable without removing production services, and this
plan does not propose that.

## Changes

### C1. Amplify build overhead (part live on the base, part on this branch)

| | |
|---|---|
| Current state | Every BUILD step re-installs 1,692 default global npm packages via `nvm install` (51 s). Until job 281 it also round-tripped a `node_modules` cache that `npm ci` deletes (~43 s); #1722 on the base replaced that with npm's download cache |
| Live evidence | Build logs of jobs 276-278; BUILD step mean 256.9 s for jobs 255-280 (24 builds, standard deviation 17.7 s) and 230.4 s for jobs 281-285 after #1722; cache upload about 35 s before, about 12.5 s after; Cost Explorer `USE1-BuildDuration` 5,683.8 min ($56.84) Oct 1-26 |
| Repo evidence | `amplify.yml` preBuild and `cache.paths` |
| Monthly cost | $65.58 build minutes at October's average volume, before #1722 |
| Proposed state | `nvm install --skip-default-packages 24` and a Node ≥ 24 assertion (this branch), with #1722's `.npm` cache kept. This branch originally removed the cache block; the merge drops that in favour of #1722, which is measured and is pinned by `tests/test_platform_audit_remediations.py` |
| Expected saving | **$19.27/month** at October-average volume, ESTIMATE: $6.57 already live from #1722 (26.4 s) plus $12.70 from the `nvm` change (51 s). At 24-26 October's 81 builds a day: $10.69 plus $20.66 |
| Not adopted | Removing the cache entirely could save at most the new cache's measured 16.8 s per build (4.3 s restore, 12.5 s upload), less whatever `npm ci` gains from it. That is unmeasured, so the merge keeps #1722 |
| Implementation | Commit `02f1e9ee5` on the audit branch; merge `485933cdb` resolves `amplify.yml` |
| Risk | Low. If a command needed a global package the build fails before deploy and the previous deployment stays live. The new assertion fails the build instead of silently using another Node |
| Rollback | Revert the commit |
| Validation | First Amplify build after merge: BUILD step about 51 s below the 230 s now seen; log shows no "Installing default global packages"; `node -v` v24.x |
| Owner approval | **Yes**: merging and pushing to `wecare.digital` is a production deploy |

### C2. Path-filtered Amplify builds

| | |
|---|---|
| Current state | Auto-build on every push; 136 of 256 recent successful builds changed only backend, docs or tests, and 4 changed nothing |
| Live evidence | Amplify job list joined to `git diff` between consecutive built commits |
| Monthly cost | $46.31 builds after C1 at October-average volume. The builds' blog fetches add $8.67/month at 24-26 October's 81 builds a day (1,433 requests per build × $0.0000024890 per request across API Gateway, Lambda, DynamoDB and Amplify transfer) |
| Proposed state | Disable auto-build on the `wecare.digital` branch; a GitHub Actions workflow triggers `amplify start-job` only when a frontend input changes (`src/`, `public/`, `content/`, `shared/`, `config/`, `package*.json`, `next.config.js`, `tsconfig.json`, `amplify.yml`, `customHttp.yml`, `.nvmrc`, `scripts/generate-*.js`, `scripts/blog-merges.js`, `scripts/guard_braces_depth.cjs`, `scripts/checkout_release_check.py`, `scripts/sync_faq.py`, `scripts/verify_public_bundle_secrets.py`, `amplify/functions/core/faq-handler/**`), plus a scheduled rebuild every 6 hours, because blog posts reach the static site only through a build and nothing else triggers one |
| Expected saving | **~$23.54/month** at October-average volume (ESTIMATE). The build line falls from $46.31 to $24.71: $46.31 × 116/256 = $20.99, plus $3.72 for four scheduled rebuilds a day. API Gateway, DynamoDB and Lambda fall by $1.94. At 24-26 October's volume (81 → 40.7 builds a day), the blog-fetch part alone falls by about $4.31/month |
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
| Live evidence | S3 listing of `secure/d/public/catalog-deploy/catalog/products/`; Lighthouse `/shop/` 14.6 MB images; CloudWatch: `wecare-catalog-media` served 1,220 requests on 22-26 October (it has data only from 22 October) and 5,706 on 27 October by 15:00 UTC; the 27 October 05:00-07:00 UTC window measured 2.4 MB per request (3.03 GB in the access log over 1,265 requests in CloudWatch) |
| Monthly cost | $2.63/month of Amplify transfer at the 22-26 October rate. On 27 October, requests rose to 5,706 (about 13.7 GB, $2.05) by 15:00 UTC, 5,231 of them in the hours the new CI workflow ran |
| Proposed state | Generate 512 px and 1024 px WebP derivatives next to each master (same prefix, new keys, masters untouched); allow those names in `catalog-media`'s `NAME` regex; render `srcset`/`sizes` on shop cards |
| Expected saving | Up to $2.63/month at the 22-26 October rate (ESTIMATE; corrected from ~$10). The main value is `/shop/` performance: the page loads 14.6 MB of images today. Derivatives would also shrink the harness's media loads |
| Risk | Low: new objects only; nothing a Meta-approved template references is moved or renamed |
| Rollback | Revert the front-end change; the masters never moved |
| Validation | `/shop/` image bytes < 1 MB in Lighthouse; derivative URLs return 200 |
| Owner approval | **Yes**: uploads to the production media bucket and a Lambda deploy |

Interim, repository-only alternative: have the browser harness (`tools/browser/lib/browser.js`)
answer `wecare.digital/api/catalog-media/*` and `/get/o/stream/media/*` with local placeholders of
the same dimensions, which removes the CI-driven share of that egress without touching
production. This is now the larger saving: on 27 October the catalog-media requests in the hours
the CI workflow ran (01:00-09:00 UTC) came to about 12.5 GB ($1.88) (C10).

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

### C10. Builds and CI against the production blog API and media (workstream decision)

| | |
|---|---|
| Current state | Every build fetches the blog corpus through the Amplify `/api` proxy (1,433 requests per build, measured). The Public UI compliance workflow, added on 27 October, builds in both of its jobs and then runs browser checks that load production media |
| Live evidence | `wecare-blog-public` averaged 162,440 invocations a day on 14-26 October (90% of API Gateway requests); 99.5% of sampled blog requests came from GitHub Actions or AWS addresses. On 27 October, Amplify served 18.46 GB by 15:00 UTC against 2.99 GB in the same hours on an average prior day, tracking the workflow's runs (R² 0.98, about 0.26 GB per run). A CI build failed on HTTP 429 from the blog API |
| Monthly cost | Blog API: about $12.13/month at the 14-26 October rate (ESTIMATE from measured unit rates): API Gateway $4.87, DynamoDB $3.42, Amplify transfer $2.86, Lambda $0.97 (rounded). The workflow's transfer: about $0.04 per run, so about $11-12/month at 10 runs a day and $74-78 at 66 |
| Proposed state | (1) Harness answers production media URLs with local placeholders (C4). (2) Build once per CI run and share `out/` with the test jobs. (3) Fetch the blog listing once per build and share it between the generators. (4) Cache the corpus in CI per hour. (5) Later, a paginated bulk endpoint so a build makes about six requests |
| Expected saving | (1) removes the workflow's media transfer, about $0.04 per run. (2) halves CI fetches. (3) $1.64/month of DynamoDB reads. (5) removes most of the $5.84/month that scales with request count (API Gateway and Lambda). DynamoDB and transfer ($6.28) fall only with fewer corpus fetches, through (2), (4) and C2. Also no more 429 build failures. All ESTIMATE |
| Risk | Low for the workflow change; the corpus cache must never be used by the Amplify production build |
| Rollback | Revert the workflow change |
| Validation | Amplify `BytesDownloaded` in hours with CI runs back near the 0.16 GB an hour seen without them; access logs show one corpus fetch per CI run; no 429 in build logs |
| Owner approval | Workflow and harness changes: no AWS approval, but they are another workstream's active files, so agree them with that workstream. Bulk endpoint: Lambda deploy |

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
5a. Harness media placeholders, CI build-once and corpus caching (C10), agreed with the harness
    workstream. On 27 October this was the fastest-growing cost.
6. Create an AWS Budget (none exists) so a credit lapse or a build storm is noticed.
7. Not a cost item, but needs the same deploy path: rebuild the Pillow (13.0.0) and cryptography
   (50.0.2) layers and move `product-image-gen` off the third-party layer (platform audit,
   section 8a).
