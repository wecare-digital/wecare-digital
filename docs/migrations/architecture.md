# WECARE.DIGITAL — platform architecture

**Created:** 2026-10-16 · **Account:** `775261844268` · **Region:** `us-east-1`
· **Status:** living document — bump the date on any material change.

> This is the standalone architecture reference for the platform: what each layer
> is, the real resource identifiers, and how the pieces connect. It is the
> companion to `recovery-kit/README.md` (how to rebuild it) and
> `backup-and-dr-plan.md` (how to protect and migrate it).
>
> Resource IDs below are drawn from `amplify/*.ts` and the provision scripts.
> They drift; the living sources of truth are `scripts/aws_account_inventory.py`
> and `scripts/deploy_all_lambdas.py --list`.

The platform is a multi-channel messaging + commerce system on AWS, fronted by a
Next.js admin app and a set of public pages, with ~78 single-purpose Python
Lambdas behind one shared HTTP API.

---

## Edge / delivery layer

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

## API / compute layer

- **One HTTP API `zllr9lrg7j`** ("wecare-digital-api"), stage `prod`. The retired `amplify/link-resources.ts` never owned production; there is exactly one HTTP API; the shortener's
  routes live on this shared API against the `stack-wecare-url-shortener:live`
  alias. Routes invoke Lambda `live` aliases (SnapStart), not `$LATEST`.
- **~78 Python 3.12 Lambdas** across 8 domains (`ai`, `auth`, `core`, `ecommerce`,
  `edge`, `messaging`, `operations`, `payments`) plus the `shared` library bundled
  into each. RBAC is enforced in Lambda middleware by Cognito group
  (Viewer / Operator / Admin), **not** by IAM role.

## Identity layer

- **Cognito user pool `us-east-1_cSx0RHCIR`** (app client `1j8kbi48m4v2rped3n224rlevb`),
  **identity pool** `us-east-1:471c2c38-5645-4ccd-aea1-7a008e906db5`. Referenced via
  `referenceAuth()`, never created by Amplify — so a redeploy can never replace it.
  Managed login v2 on the Cognito prefix domain (no custom ACM/Route 53 dependency).

## Data layer

- **DynamoDB** — ~76 live tables under the `stack-wecare-digital-*` naming scheme
  (snapshot 2026-10-16; ~47 of them empty), addressed by Lambdas via physical name
  through `os.environ`. TTL enforced on the physical tables; PITR is the recovery
  mechanism (see the DR plan).
- **S3 `wecare-digital-get`** — two roots: `o/` (public: `o/stack/` transactional
  data, `o/public/` Meta-fetched media, `o/stream/` static assets) and `secure/`
  (gated, presigned-only).

## Async / messaging layer

- **SQS** — `inbound-dlq`, `bulk-queue`, `bulk-dlq`, `outbound-dlq`,
  `eventbridge-dlq`. Bulk sends flow through `bulk-queue` → `bulk-worker`.
- **EventBridge** — scheduled jobs (scheduled messages, cleanup, SLA) and the
  Amplify build-failure notification rule.
- **SNS topic `stack-wecare-digital`** — the single alarm sink; every CloudWatch
  alarm and the backup/health jobs report here.

## AI layer

- **Amazon Bedrock** — foundation + inference-profile models for AI response
  generation, KB query, and the SEO tools Lambda.

## External providers (not AWS — survive a cloud move)

- WhatsApp / Meta (Business API, calling, catalog), Razorpay (payments), Plivo
  (PSTN voice), Google (Search Console / PageSpeed / Maps). These talk to the
  providers directly; only the webhook landing point is AWS-specific.

## Secrets + observability

- **Secrets Manager** (~28 secrets) → encrypted file + S3 copy + one-way GCP mirror.
- **CloudTrail** management-event trail with log-file validation; **CloudWatch**
  dashboard + per-Lambda and DLQ alarms.

---

## Diagram

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

  API --> L[~78 Python Lambdas<br/>live aliases · SnapStart<br/>8 domains]
  AUTH[Cognito pool<br/>us-east-1_cSx0RHCIR] -. RBAC groups .-> L

  L --> DDB[(DynamoDB ~76 tables<br/>stack-wecare-digital-*)]
  L --> S3
  L --> SQS[SQS queues<br/>inbound/bulk/outbound DLQ]
  SQS --> L
  EB[EventBridge schedules] --> L
  L --> BR[Amazon Bedrock<br/>AI models]
  L --> SM[Secrets Manager<br/>~28 secrets]
  L -->|API calls| External

  L --> CW[CloudWatch alarms]
  CW --> SNS[SNS stack-wecare-digital]
  CT[CloudTrail trail] -.audit.-> S3

  SM -. encrypted backup .-> BK[(Backup bucket + GCP mirror)]
```

---

## Lambda domains

The ~78 handlers live under `amplify/functions/<domain>/<name>/handler.py`. The
authoritative name → source → provisioning-script map is the `SPECS` list in
`scripts/deploy_all_lambdas.py` (`--list` prints it).

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

---

## Related documents

- `recovery-kit/README.md` — how to rebuild this from git (ordered restore runbook).
- `backup-and-dr-plan.md` — how each layer is backed up and the off-AWS migration path.
