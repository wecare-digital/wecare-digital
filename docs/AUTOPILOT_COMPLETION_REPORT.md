# WECARE.DIGITAL — Autopilot Completion Report

**Session goal:** complete P0–P4 autonomously. **Principle applied:** execute everything
safe/additive/verifiable; stage (with ready-to-run runbooks) anything destructive or
high-blast-radius that cannot be visually verified while unattended. Nothing that could break
live traffic was fired blind. S3 versioning + KMS rotation remain de-scoped (owner decision).

---

## ✅ EXECUTED & VERIFIED THIS SESSION (live)

### P0 — closed
- **`RateLimitTable` TTL enabled** on attr `lastUpdatedAt` (now+86400 epoch). 0 rows purged
  (table transient, all values future-dated). Rate-limit data is ephemeral + fails-open → safe.
  Script: `scripts/_enable_ratelimit_ttl.py`.
- All prior P0 monitoring already live (API Gateway, EventBridge, DynamoDB, Lambda/SQS).

### P1 — observability layer (all additive, verifiable, zero risk)
Added 11 alarms + 1 dashboard (`scripts/_create_p1_observability.py`):
- `wecare-bulk-dlq-depth` — **closed a real gap** (bulk DLQ was unmonitored)
- `wecare-queue-age-bulk` — stuck-backlog detection (oldest msg > 15m)
- `wecare-lambda-throttles` — account-wide Lambda throttling
- `wecare-lambda-errors-*` — error alarms on 8 revenue/message-critical fns
  (razorpay-webhook, payu-webhook, scheduled-messages, bulk-worker, service-api,
  whatsapp-business-api, billing, invoice-engine)
- **Dashboard `wecare-platform-health`** — API 5xx/latency, Lambda errors/throttles,
  SQS DLQ depths, EventBridge failures, DynamoDB throttles in one view.

### Code hygiene
- Dead `ADMIN_ACTION_LOG_TABLE` constant removed (commit `126ce97`). Zero runtime impact
  (constant was never read) → no Lambda redeploy required.

---

## 📊 LIVE ALARM INVENTORY — 39 total → all page `one@wecare.digital` (confirmed)

| Group | Count | Notes |
|---|---|---|
| DynamoDB throttle (per-table) | 14 | hot tables |
| DynamoDB user-errors (account) | 1 | |
| API Gateway 5xx + p99 latency | 4 | both HTTP APIs |
| EventBridge FailedInvocations | 2 | both scheduler rules |
| EventBridge DLQ depth | 1 | new DLQ |
| Lambda errors (inbound/outbound + 8 critical) | 10 | |
| Lambda throttles (account) | 1 | new |
| SQS DLQ depth (inbound/outbound/bulk/eventbridge) | 4 | bulk was a gap, now closed |
| SQS queue-age (bulk) | 1 | new |
| SNS delivery failures | 1 | |
| SIP cert expiry | 1 | |
Plus the **Amplify build-failure EventBridge rule** (ENABLED).

---

## 🟡 STAGED — P1 safe-deploy (needs a maintenance window; NOT fired unattended)

**Why staged:** these repoint or version live invocation paths. A wrong alias/canary switch
can break live traffic; must be watched.

### Lambda versions + `live` alias + CodeDeploy canary w/ auto-rollback
Runbook (per critical function):
1. `aws lambda publish-version --function-name <fn>`
2. `aws lambda create-alias --function-name <fn> --name live --function-version <n>`
3. Repoint the API Gateway/SQS/EventBridge integration ARN → the `:live` alias ARN.
4. Create CodeDeploy app + deployment group (`Canary10Percent5Minutes`) with an
   alarm rollback on the function's `wecare-lambda-errors-<fn>` alarm.
> Do the 8 critical fns first. Verify each alias serves traffic before adding canary.

### Auto-remediation Lambda (DLQ redrive)
Prepared design (build + test in a window before enabling — auto-redrive risks poison-loops):
- Lambda subscribed to the alarm SNS topic; on `*-dlq-depth` ALARM, `StartMessageMoveTask`
  from DLQ → source with a **max-receive guard** so poison messages don't loop.

### Synthetics canary
- Needs: artifacts S3 bucket + IAM role + endpoint. Webhook-health GET every 5m is safe;
  admin-login canary needs a stored credential (Secrets Manager). Not created unattended
  (touches live endpoints + creates IAM).

### Cognito Advanced Security (threat protection)
- Optional/paid, single admin user. Enable to **AUDIT** mode (logs, never blocks logins):
  `aws cognito-idp update-user-pool --user-pool-id <id> --user-pool-add-ons AdvancedSecurityMode=AUDIT`
- Left as owner decision (billing change).

---

## 🟠 STAGED — P2 structural (high blast radius; supervised only)

### DynamoDB consolidation (~61 → ~35–40 tables)
- **NOT a delete job.** "Empty" tables have live writers. Requires: pick the canonical
  `Messages` timeline schema → dual-write from handlers → backfill copy → cutover reads →
  retire old table after a soak. Per-table migration scripts + verification required.
- Do **after** handler refactor; never drop a table with a writer.

### Frontend de-duplication (~120 → ~70–80 pages)
- Retire per-channel `inbox`/`campaign`/`logs` in favour of unified `dm/*` — **only after**
  confirming `dm/*` fully covers each channel + updating nav + adding redirects for indexed URLs.
- **Stub pages kept intentionally** (`carbon`, `nocode`, `task`, `studio`, `test-agent`):
  they're "Coming Soon" placeholders; `studio` has a canonical SEO URL. Deleting live routes
  blind risks nav breakage + 404s on indexed URLs. Remove only with redirect + sitemap update.

### Lambda → IaC (`cdk import`)
- Bring the 54 Python Lambdas under Amplify/CDK. **Blocked locally:** `ampx sandbox`/
  `pipeline-deploy` need Docker (absent) + run only in CI. Path: enable Docker on a CI runner,
  `cdk import` with a zero-replacement diff gate, then `ampx pipeline-deploy` via GitHub Actions.
- Confirmed safe context: backend uses **referenceAuth** (points at existing Cognito, no
  duplicate pool) and **no CFN backend stack exists** — live app runs on the standalone
  `stack-wecare-digital-*` tables + Python Lambdas.

---

## 🔵 P3/P4 — product roadmap (features, not defects) — see `gap_remediation_plan.md`
CI/CD + staging env, Embedded Signup, Marketing Messages API, CSW timer, Meta analytics
dashboards, Template Quality dashboard, OTP service, GDPR deletion endpoint, conversion
tracking. These are build efforts requiring product decisions, not autonomous infra fixes.

---

## Residual notes
- **2 critical vulns** = bundled `fast-xml-parser` in `@aws-amplify/graphql-api-construct`
  (build-time only, unreachable by `overrides`). Clears when Amplify ships an updated construct.
- Repo clean, HEAD = `origin/stack`, Amplify build **#509 SUCCEED**.
- All boto3 tooling is idempotent and re-runnable in `scripts/`.

---

## ROUND 2 — additional safe improvements (executed & verified)

- **PITR backup coverage 59% → 92%** (`scripts/_enable_pitr.py`). Enabled Point-in-Time
  Recovery on 21 business-data tables that lacked it (ScheduledMessages,
  BulkRecipients, SmsOutbound, Sms*, Voice*, WhatsAppVoice/Group, CallNotifications,
  AdClickAttribution, LinkClicks, ShortLinks, SystemEvent, AIInteractions, AIProviderPolicy,
  PushTokens, DLTTemplates). Now **58/63 tables have PITR**; the 5 remaining are intentionally
  skipped caches/ephemeral (CatalogCache, RateLimit, DLQMessages, and two since-deleted caches).
- **Cost anomaly detection** (`scripts/_create_cost_anomaly.py`) — ML per-service monitor
  → daily email digest to `one@wecare.digital` on anomalies ≥ $20 impact. Guess-free (no
  fixed budget). Closes the "no cost monitoring" gap.

### Deferred (with reason, NOT done)
- **`datetime.utcnow()` deprecation** — spread across 25+ sites in 5-6 handler files. NOT a
  safe blind replace: `utcnow().isoformat()` emits a naive string while the recommended
  `now(timezone.utc).isoformat()` emits an offset-bearing string, which would break string
  comparisons against stored timestamps (e.g. url-shortener expiry). Needs a behavior-preserving
  helper + full retest + redeploy of affected functions. Low urgency (Python 3.12 still supports
  it). Deserves its own tested PR — do not rush.
- **Cognito sign-in anomaly alarm** — skipped; those metrics require Advanced Security (Plus
  tier), which is on hold.

### Verified this round
- 550 backend tests pass · Amplify build #510 SUCCEED · 55 Lambdas Active · 63 tables ACTIVE
- Alarm total remains 39 + health dashboard; email confirmed.

---

## ROUND 3 — DLQ recovery tooling (safe form of auto-remediation)

- **`scripts/dlq_redrive.py`** — operator-run DLQ inspect + redrive tool. Delivers the recovery
  capability of "auto-remediation" WITHOUT the poison-loop risk: a human runs it after fixing
  root cause. Uses SQS-native `StartMessageMoveTask` (redrive-to-source) with a 10 msg/s rate cap.
  Modes: inspect (all DLQ depths), `--peek` (sample without delete), `--redrive` (move back to source).
  Verified in inspect mode: all 4 DLQs at depth 0 (healthy).

### Why the AUTOMATIC auto-remediation is still NOT done
Auto-redrive on alarm can re-trigger the same failure in a loop (poison messages). The operator
tool is the safe equivalent; a fully-automatic version needs a max-receive guard + testing against
a real failed message before it can run unattended.

### Honest status on the remaining structural items (no safe unattended path)
- **Lambda `live` alias + canary** — NOT a toggle. The current deploy path
  (`_deploy_everything.py`) does direct `update_function_code` on `$LATEST`; a CodeDeploy canary
  requires reworking the deploy pipeline to shift alias traffic. Supervised infra effort.
- **Synthetics canary** — creates IAM + S3 + hits endpoints (login needs a stored credential).
- **DynamoDB consolidation** — data migration (dual-write → backfill → cutover → soak).
- **Frontend de-dup** — deletes/merges live routes; SEO/nav/404 risk; needs visual verification.
- **Lambda → IaC** — hard-blocked locally (needs Docker + CI runner).
- **P3/P4 features** — product builds requiring Meta API access + product decisions.

---

## ROUND 4 — Function URL security resolution + tripwires

- **`ai-generate-response` URL locked `NONE`→`AWS_IAM`** — resolved the Bedrock cost-abuse
  exposure (unused: 0 req/30d; callers use boto3 invoke). Reversible.
- **PayU webhook fail-open → fail-closed** (committed, 10/10 payments tests pass).
- **4 `UrlRequestCount` tripwire alarms** (`scripts/_create_url_tripwire_alarms.py`) on all public
  Function URLs → SNS. Any hit is flagged (abuse attempt, or reveals a provider actually uses
  the URL). **Alarm total: 43.**

### Still needs a 2-min human dashboard check before I remove them (payment-critical)
- `razorpay-webhook` / `payu-webhook` Function URLs — confirm Razorpay/PayU POST to the API
  Gateway route (not the lambda-url host), then the redundant URLs can be deleted.

## FINAL: everything safely-completable is DONE
Remaining items are all gated by a hard blocker: **supervised live cutover** (Lambda alias+canary
needs deploy-pipeline rework; frontend de-dup; DynamoDB migration), **Docker+CI** (Lambda→IaC),
**billing decision** (Cognito Plus), **product scoping** (P3/P4 features), or a **2-min dashboard
check** (3 leftover Function URLs). None is blocked by unfinished analysis.
