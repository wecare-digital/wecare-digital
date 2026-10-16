# Recovery kit — rebuild the whole platform from git

**Created:** 2026-10-16 · **Account:** `775261844268` · **Region:** `us-east-1`
· **Status:** living document — bump the date on any material change.

> **Purpose.** If the AWS account is disabled, lost, or you need to stand the
> platform up somewhere else, this folder is the single entry point. It does not
> hold a second copy of the code — the code is already in this repo and that *is*
> the backup. It is the **index and the ordered runbook** that ties the committed
> source to the exact scripts that recreate every piece.
>
> Account `775261844268`, region `us-east-1`.

---

## Read this first: what is and isn't in git

A git folder is the right home for everything **reproducible**, and the wrong home
for anything **live or secret**. So this kit is split cleanly:

**In git (this repo) — the rebuild material:**

- All application code — `src/` (Next.js frontend).
- All **78 Lambda handlers** — `amplify/functions/**` across 9 domains.
- All infrastructure definitions — `amplify/*.ts` (CDK) and the
  `scripts/provision_*.py` fleet (boto3).
- The portable fleet deployer — `scripts/deploy_all_lambdas.py`.
- Every runbook under `docs/migrations/`.

**NOT in git, on purpose — restored from backup, never committed:**

- Secrets (AWS Secrets Manager) → encrypted backup file + S3 copy + GCP mirror.
- Runtime data (DynamoDB rows, S3 objects) → PITR / AWS Backup / S3 versioning.
- Cognito users → the periodic export in the credential-backup bucket.

Committing any of those three would be a security leak and git is the wrong tool
for them anyway. See `../backup-and-dr-plan.md` for how each is protected.

---

## Full architecture (what you are recovering)

The platform is a multi-channel messaging + commerce system on AWS, fronted by a
Next.js admin app and a set of public pages, with ~78 single-purpose Python
Lambdas behind one shared HTTP API. The pieces and how they connect:

### Edge / delivery layer

- **Amplify Hosting** serves the Next.js app and the generated public pages. It
  owns the TLS certificate for `wecare.digital` and proxies two namespaces to the
  shared API: `/r/<*>` (short links) and the service/API routes.
- **CloudFront `E2GP22R4BIFGQ3`** fronts the S3 media bucket, serving objects at
  `wecare.digital/get/<key>` (origin path `""`, so the `o/` prefix is part of the
  key). This is the only live distribution on the bucket.
- **Lambda@Edge `wecare-get-miss-redirect`** sits on that distribution. It denies
  `secure/*` at the edge (reachable only via presigned URL) and redirects misses.
  There is **no WAF** — removed 2026-09-28 as a cost decision; request filtering now
  rests on application-level auth, provider HMAC, and rate limiting.

### API / compute layer

- **One HTTP API `zllr9lrg7j`** ("wecare-digital-api"), stage `prod`. Despite what
  `link-resources.ts` declares, there is exactly one HTTP API; the shortener's
  routes live on this shared API against the `stack-wecare-url-shortener:live`
  alias. Routes invoke Lambda `live` aliases (SnapStart), not `$LATEST`.
- **~78 Python 3.12 Lambdas** across 9 domains (`ai`, `auth`, `core`, `ecommerce`,
  `edge`, `messaging`, `operations`, `payments`, plus the `shared` library bundled
  into each). RBAC is enforced in Lambda middleware by Cognito group
  (Viewer / Operator / Admin), **not** by IAM role.

### Identity layer

- **Cognito user pool `us-east-1_cSx0RHCIR`** (app client `1j8kbi48m4v2rped3n224rlevb`),
  **identity pool** `us-east-1:471c2c38-5645-4ccd-aea1-7a008e906db5`. Referenced via
  `referenceAuth()`, never created by Amplify — so a redeploy can never replace it.
  Managed login v2 on the Cognito prefix domain (no custom ACM/Route 53 dependency).

### Data layer

- **DynamoDB** — ~77 live tables under the `stack-wecare-digital-*` naming scheme,
  addressed by Lambdas via physical name through `os.environ`. TTL enforced on the
  physical tables; PITR is the recovery mechanism (see the DR plan).
- **S3 `wecare-digital-get`** — two roots: `o/` (public: `o/stack/` transactional
  data, `o/public/` Meta-fetched media, `o/stream/` static assets) and `secure/`
  (gated, presigned-only).

### Async / messaging layer

- **SQS** — `inbound-dlq`, `bulk-queue`, `bulk-dlq`, `outbound-dlq`,
  `eventbridge-dlq`. Bulk sends flow through `bulk-queue` → `bulk-worker`.
- **EventBridge** — scheduled jobs (scheduled messages, cleanup, SLA) and the
  Amplify build-failure notification rule.
- **SNS topic `stack-wecare-digital`** — the single alarm sink; every CloudWatch
  alarm and the backup/health jobs report here.

### AI layer

- **Amazon Bedrock** — foundation + inference-profile models for AI response
  generation, KB query, and the SEO tools Lambda.

### External providers (not AWS — survive a cloud move)

- WhatsApp / Meta (Business API, calling, catalog), Razorpay (payments), Plivo
  (PSTN voice), Google (Search Console / PageSpeed / Maps). These talk to the
  providers directly; only the webhook landing point is AWS-specific.

### Secrets + observability

- **Secrets Manager** (~30 secrets) → encrypted file + S3 copy + one-way GCP mirror.
- **CloudTrail** management-event trail with log-file validation; **CloudWatch**
  dashboard + per-Lambda and DLQ alarms.

### Diagram

```mermaid
flowchart TD
  subgraph External["External providers (non-AWS)"]
    WA[WhatsApp / Meta]
    RP[Razorpay]
    PL[Plivo PSTN]
    GG[Google APIs]
  end

  User[Browser / Admin app] --> AMP[Amplify Hosting<br/>Next.js + public pages]
  User --> CF[CloudFront E2GP22R4BIFGQ3]
  CF --> EDGE[Lambda@Edge<br/>get-miss-redirect]
  CF --> S3[(S3 wecare-digital-get<br/>o/ public · secure/ gated)]

  AMP -->|/r/* and /api/*| API[HTTP API zllr9lrg7j<br/>stage prod]
  WA -->|webhooks| API
  RP -->|webhooks| API
  PL -->|dial events| API

  API --> L[~78 Python Lambdas<br/>live aliases · SnapStart<br/>9 domains]
  AUTH[Cognito pool<br/>us-east-1_cSx0RHCIR] -. RBAC groups .-> L

  L --> DDB[(DynamoDB ~77 tables<br/>stack-wecare-digital-*)]
  L --> S3
  L --> SQS[SQS queues<br/>inbound/bulk/outbound DLQ]
  SQS --> L
  EB[EventBridge schedules] --> L
  L --> BR[Amazon Bedrock<br/>AI models]
  L --> SM[Secrets Manager<br/>~30 secrets]
  L -->|API calls| External

  L --> CW[CloudWatch alarms]
  CW --> SNS[SNS stack-wecare-digital]
  CT[CloudTrail trail] -.audit.-> S3

  SM -. encrypted backup .-> BK[(Backup bucket + GCP mirror)]
```

---

## The 78 Lambdas, and how each one is recreated

Every function's source lives under `amplify/functions/<domain>/<name>/handler.py`.
The authoritative map of **function name → source dir → the script that creates
it** is the `SPECS` list in `scripts/deploy_all_lambdas.py`. Two script roles:

- **`provisioned_by`** — the `provision_*.py` (or CloudFormation) script that must
  **create** the function the first time (role, env, routes, triggers).
- **`deploy_all_lambdas.py`** — updates the code of a function that already exists,
  for the whole fleet or a named subset, then publishes via `snapstart_publish.py`.

So "redeploy from scratch" = run each function's `provisioned_by` once, then
`deploy_all_lambdas.py` to push current code. The function domains:

| Domain | Dir | What it covers |
|--------|-----|----------------|
| `ai` | `amplify/functions/ai/` | KB query, response generation, config, agent action group, MCP |
| `auth` | `amplify/functions/auth/` | customer registration/profile, WhatsApp OTP, email verification, Cognito custom message |
| `core` | `amplify/functions/core/` | contacts, CRM, messages, service API, auth middleware, URL shortener, secure files |
| `ecommerce` | `amplify/functions/ecommerce/` | checkout, catalog, coupons, gift cards, invoices, orders, product image gen |
| `edge` | `amplify/functions/edge/` | Lambda@Edge get-miss redirect |
| `messaging` | `amplify/functions/messaging/` | WhatsApp in/out, SMS, email, voice, RCS, bulk, templates, Meta/Plivo integrations |
| `operations` | `amplify/functions/operations/` | billing, SLA, bulk workers, DLQ replay, SEO tools, system cleanup, docs scraper |
| `payments` | `amplify/functions/payments/` | Razorpay webhook, invoice engine, payments read |
| `shared` | `amplify/functions/shared/lambda_utils/` | shared library bundled into every function |

List the live map any time:

```bash
python scripts/deploy_all_lambdas.py --list
```

---

## Restore order (in-place: same AWS account recovered)

Dependencies run top-down. Do them in this order; each step is idempotent.

1. **Credentials.** Recover AWS access first (IAM console / SSO) — the secrets
   backup cannot bootstrap AWS auth because reading it needs AWS auth. Then confirm
   secrets exist, or restore them:
   ```bash
   python scripts/secrets_backup.py verify     # decrypt-check the local artifact
   python scripts/secrets_backup.py restore     # list field names (no values printed)
   ```
2. **Identity.** Cognito user pool. If deleted, recreate and import users from the
   export (users re-verify; passwords never transfer).
3. **Data stores.** DynamoDB tables + S3 bucket. Restore tables from PITR / AWS
   Backup; restore S3 objects from a version or the replica. The provision scripts
   create empty tables — the *data* comes from backup, not from code.
   ```bash
   python scripts/aws_account_inventory.py       # confirm what exists vs what should
   ```
4. **Infrastructure.** Queues, alarms, dashboard, URL shortener, SEO store — the CDK
   backend plus the provision scripts:
   ```bash
   python scripts/provision_*.py --apply          # run the ones your account is missing
   ```
5. **Lambda fleet.** Create any missing functions via their `provisioned_by`
   script, then push current code and publish:
   ```bash
   python scripts/deploy_all_lambdas.py           # whole fleet + publish aliases
   python scripts/deploy_all_lambdas.py wecare-contacts   # or a single function
   ```
6. **Routes / edge / DNS.** Re-register HTTP API routes and the edge redirect, then
   repoint DNS last so traffic only arrives once the stack is healthy.
7. **Verify.**
   ```bash
   python scripts/post_deploy_health.py
   python scripts/check_deployed_source.py
   ```

---

## Rebuild somewhere else (off-AWS migration)

The full phased approach is in `../backup-and-dr-plan.md` §7. The short version:

- **Frontend, S3, secrets** are the easy, portable parts — secrets already mirror
  to GCP (`scripts/google-cloud-setup.sh mirror-secrets`).
- **DynamoDB, Cognito, and AWS-event-shaped Lambdas** are the real work — they need
  a data-model mapping and a client swap, not just a lift.
- The Lambdas address tables by **physical name via `os.environ`**, so repointing
  data access is an env + client change per function, not a framework rewrite.
- Keep the old environment running and billable, cut over with one reversible
  lever, delete nothing until a clean window plus sign-off — the discipline already
  proven in the Lightsail runbooks here.

---

## Keeping this kit honest

This README names counts (78 handlers, 9 domains) that are true at the time of
writing but will drift. The living sources of truth are:

- `scripts/deploy_all_lambdas.py --list` — the real function map.
- `scripts/aws_account_inventory.py` — the real account contents.

Trust those two over any number written here. If you add a Lambda, it belongs in
the `SPECS` list with its `provisioned_by` script — that is what keeps it inside
the recovery path automatically, instead of being a function nobody can redeploy.
