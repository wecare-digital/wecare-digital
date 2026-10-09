# AWS inventory findings — 2026-09-26

Backlog item 1. Companion to the machine-generated `aws-inventory.json` /
`aws-inventory.md` (regenerate: `python scripts/aws_account_inventory.py`).
This file carries the judgement the generator cannot: **what is reusable, what
is a defect, and which backlog items the measurement just moved.**

Scope: account `775261844268`, identity `user/wecare-admin`, `us-east-1`
(+ `ap-south-1` for SES). Fourteen service families enumerated.
**Collector errors: 0**, so the counts below are authoritative rather than
partial. Secrets were read as metadata only; no secret value was retrieved.

---

> ## ⚠️ SUPERSEDED 2026-10-09 — every WAF statement in this file is pre-deletion
>
> This document is dated **2026-09-26**, two days before the owner **deleted both web
> ACLs** on 2026-09-28 as a cost decision. Re-measured live on 2026-10-09:
>
> ```
> aws wafv2 list-web-acls --scope REGIONAL   --query 'length(WebACLs)'  -> 0
> aws wafv2 list-web-acls --scope CLOUDFRONT --query 'length(WebACLs)'  -> 0
> ```
>
> So the WAF rows in the table below (Regional **1**, CloudFront-scope **1**), the
> reusable-asset note at line ~82, and the **D2 WITHDRAWN** section at lines ~144-161
> ("WAF is live on both surfaces") all describe a state that no longer exists.
> `wecare-cognito-waf` and `wecare-amplify-waf` are both gone.
>
> **The absence of WAF is NOT a gap and must not be written up as one.**
> `.kiro/steering/00-current-owner-overrides.md` withdrew "WAF must be implemented and
> live-verified" as a required target when the resource was removed. Restore path, if it
> is ever reinstated: `python3 scripts/provision_waf.py --apply`, with prior rule and
> association state preserved in
> `docs/execution/snapshots/waf-*-before-delete-20260928.json`.
>
> **What is retained deliberately**, because it will matter again if WAF ever returns:
> the measurement caveat in D2. Never read a WAF association with
> `list_resources_for_web_acl` alone — it defaults `ResourceType` to
> `APPLICATION_LOAD_BALANCER`, this account has none, and it does not enumerate Cognito
> pools, Amplify apps or CloudFront at all, so a correctly protected ACL reads as
> protecting nothing. That false reading was produced twice by two different sessions.
> Use `get_web_acl_for_resource(<arn>)` per resource, or the Amplify app's own
> `wafConfiguration`.
>
> **Consequence now in force:** there is no per-IP protection in front of public
> customer OTP sign-in. The only remaining request filtering is handler-level
> `require_auth`, provider HMAC verification on webhooks,
> `lambda_utils/rate_limit.py`, the per-phone OTP probe counter in the Cognito
> trigger, and API Gateway stage/route throttling. That is a real open exposure
> accepted by owner decision, not a solved one.
>
> Non-WAF content in this file was not invalidated by the deletion, but every dated
> count here has since drifted — re-derive with
> `python scripts/aws_account_inventory.py` rather than quoting this file.

---

## Every dated count in steering is now superseded

`00-current-owner-overrides.md` carried a baseline snapshot and instructed that
it be rediscovered rather than trusted. Rediscovered:

| Item | Dated snapshot | Measured 2026-09-26 | Direction |
|---|---:|---:|---|
| Lambda functions | 58 | **65** | +7 |
| HTTP APIs | 2 | **1** | −1 (only `zllr9lrg7j`) |
| HTTP API routes | 332 | **361** | +29 |
| API Gateway authorizers | 0 | **0** | unchanged |
| Routes `AuthorizationType=NONE` | 332 | **361** | +29 |
| Regional WAF WebACLs | 0 | ~~**1**~~ → **0** | ⚠️ SUPERSEDED — deleted 2026-09-28, live 0 on 2026-10-09 |
| CloudFront-scope WAF WebACLs | not measured | ~~**1**~~ → **0** | ⚠️ SUPERSEDED — deleted 2026-09-28, live 0 on 2026-10-09 |
| Cognito MFA | OFF | **OPTIONAL** (admin pool) | improved |
| GuardDuty detectors | 0 | not re-measured this run | — |
| Security Hub | not subscribed | not re-measured (excluded by owner) | — |

The "2 HTTP APIs" figure was wrong or has since been reduced to one. There is a
single HTTP API, `zllr9lrg7j` / `wecare-digital-api`, stage `prod`, and zero
REST APIs.

## Reusable — do not provision these again

### The unified notification service already has its entire data layer

This is the most consequential finding. Backlog item 4 is described as one of the
biggest unresolved production risks, and its infrastructure is **already built,
correctly shaped, and completely unused**:

| Table | Hash key | GSIs | TTL | PITR | Items |
|---|---|---:|---|---|---:|
| `stack-wecare-digital-NotificationEvents` | `eventClaimKey` | 1 | ENABLED | ENABLED | **0** |
| `stack-wecare-digital-NotificationOutbox` | `jobId` | 1 | ENABLED | ENABLED | **0** |
| `stack-wecare-digital-NotificationDeliveries` | `deliveryId` | 2 | ENABLED | ENABLED | **0** |
| `stack-wecare-digital-NotificationAttempts` | `attemptId` | 1 | ENABLED | ENABLED | **0** |

All four are tagged `domain=notifications, phase=3`. The key design maps
one-to-one onto item 4's requirements: `eventClaimKey` is the parent
connected-call event's idempotency claim, `NotificationOutbox` is the
transactional outbox, `NotificationDeliveries` gives independent per-channel
(WhatsApp/SMS/RCS) delivery rows, and `NotificationAttempts` carries lease/retry
state. Transport exists too — `stack-wecare-digital-notification-queue` with
redrive to `stack-wecare-digital-notification-dlq` at `maxReceiveCount=3`.

Supporting idempotency primitives are live and in use, not empty:
`stack-wecare-digital-WebhookDedup` (`eventId`, 241 items) and
`stack-wecare-digital-RateLimitTable` (`id`, 12 items).

**Consequence: item 4 is an application-code and wiring task, not a provisioning
task.** The migration target for item 5 is also visible —
`stack-wecare-digital-CallNotificationsTable`, keyed on bare `callId` with 0
items, is the older single-table shape the canonical domain replaces.

### Other reusable infrastructure

- **SES for item 39** — `one@wecare.digital` is verified with DKIM `SUCCESS`,
  in an account with production access and a 50,000/day quota in `us-east-1`.
  Configuration set `wecare-digital` exists. No new identity needed.
  Note `ap-south-1` SES is **still sandboxed** (`production_access=False`,
  200/day) — do not send customer email from that region.
- **Cognito for items 28–48** — `us-east-1_46ULYuukt`
  (`WECARE.DIGITAL-CUSTOMERS`) already carries client
  `wecare-customer-whatsapp-otp` and all three custom-auth triggers
  (`DefineAuthChallenge`, `CreateAuthChallenge`, `VerifyAuthChallengeResponse`).
  The passwordless WhatsApp-OTP scaffolding is provisioned; ≈1 user means it is
  not yet carrying real registrations.
- **Cognito RBAC for item 114** — admin pool `us-east-1_cSx0RHCIR` already has
  groups `Admin`, `Operator`, `Partner`, `Viewer`.
- **WAF rule sets for the item 114/WAF target** — two ACLs exist with real rules,
  so the authoring work is done (see the defect below about where they point).
- **DLQ capacity** — 8 queues, 5 of them DLQs, every non-DLQ queue has a redrive
  policy. No new queue needed for item 4.

## Defects found by measurement

### D1 · Two DLQ alarms can never fire, and the notification DLQ has none — ✅ RESOLVED 2026-09-26

`HIGH`. The alarms reference a `base-wecare-digital-` queue-name prefix that no
longer exists; the real queues use `stack-wecare-digital-`:

| Alarm | Watches queue | Queue exists? |
|---|---|---|
| `wecare-inbound-dlq-depth` | `base-wecare-digital-inbound-dlq` | **no** |
| `wecare-outbound-dlq-depth` | `base-wecare-digital-outbound-dlq` | **no** |

So three DLQs are effectively unmonitored:
`stack-wecare-digital-inbound-dlq`, `stack-wecare-digital-outbound-dlq`, and
`stack-wecare-digital-notification-dlq` (which never had an alarm at all).
Inbound and outbound are the WhatsApp message paths, and the notification DLQ is
the one item 4 depends on. All three are currently empty, so nothing has been
lost yet — but a failure there would be silent.

This is why the alarm count looked healthy: 42 alarms, 0 in `ALARM`, 0
`INSUFFICIENT_DATA`, 0 without an action. A stale dimension produces a
permanently green alarm, which reads as success. Directly relevant to item 214.

**Resolution.** `scripts/provision_alarm_coverage.py --apply` repointed both
alarms and created `wecare-notification-dlq-depth`. Two defects were fixed
together, because repointing an alarm that is also statistically wrong just moves
the wrongness:

| | before | after |
|---|---|---|
| dimension | `base-wecare-digital-*` | `stack-wecare-digital-*` |
| statistic | `Sum` | `Maximum` |
| condition | `>= 1` | `> 0` |

`ApproximateNumberOfMessagesVisible` is a gauge, not a counter. SQS emits it
several times per period, so `Sum` over 300s adds unrelated samples together and
the threshold stops meaning "messages present". `Maximum` is the correct
reduction, and it is what `wecare-bulk-dlq-depth` already used.

Proof the old configuration was broken, and the new one is not — datapoints over
a 6-hour window:

    base-wecare-digital-inbound-dlq        0 datapoints   <- could never evaluate
    base-wecare-digital-outbound-dlq       0 datapoints   <- could never evaluate
    stack-wecare-digital-inbound-dlq      15 datapoints
    stack-wecare-digital-outbound-dlq     14 datapoints
    stack-wecare-digital-notification-dlq 15 datapoints

Independently confirmed through the inventory collector's separate code path:
`dlqs_without_alarm` and `alarms_watching_nonexistent_queue` are both now empty.
Re-check any time with `--verify`, which exits 1 on drift.

**Not proven:** no message was injected to watch an alarm actually transition to
`ALARM` and deliver an email. The metric-datapoint evidence above shows the
alarms can now evaluate, which is what was broken; end-to-end firing remains
unverified by choice, to keep the probe inert.

### ~~D2 · `wecare-cognito-waf` protects nothing~~ — WITHDRAWN 2026-09-26

> **⚠️ SUPERSEDED 2026-10-09.** Both web ACLs named below were **deleted by the owner on
> 2026-09-28**; live `list-web-acls` returns **0** in REGIONAL and CLOUDFRONT scope. Read
> this section as a historical record of a collector bug, not as current state. The
> measurement lesson it teaches is still live and is the reason the section is kept.

**This finding was wrong, and it was my collector's bug rather than an account
defect.** WAF is live on both surfaces. *(True when written on 2026-09-26; the ACLs no
longer exist — see the stamp above.)*

`ListResourcesForWebACL` defaults `ResourceType` to
`APPLICATION_LOAD_BALANCER`. This account has no load balancers, so a single
unparameterised call returns `[]` for every regional web ACL — which reads as
"associated with nothing". Asked the correct way, per resource:

    get_web_acl_for_resource(us-east-1_cSx0RHCIR) -> wecare-cognito-waf   # staff
    get_web_acl_for_resource(us-east-1_46ULYuukt) -> wecare-cognito-waf   # customers

`wecare-cognito-waf` (3 rules: `auth-rate-limit-per-ip`,
`AWSManagedRulesAmazonIpReputationList`, `AWSManagedRulesCommonRuleSet`) is
attached to **both** Cognito user pools. `wecare-amplify-waf` (4 rules, adding
`AWSManagedRulesKnownBadInputsRuleSet`) reports `ASSOCIATION_SUCCESS` on the
Amplify app. The owner-override target "WAF must be implemented and
live-verified" is met on both surfaces, not half met.

The trap was already documented by another session in change-authority entry
282, which recorded that `list_resources_for_web_acl` does not enumerate Cognito
pools, Amplify apps or CloudFront and returns an empty list for a correctly
associated ACL. The collector has since been corrected to iterate
`ResourceType`, and its docstring keeps this as a warning: a cross-check that
reports a defect which does not exist costs more than no check at all.

The three CloudFront distributions in this account
(`E1SZBXLQ4XNLJ7` mta-sts, `E2GP22R4BIFGQ3` wecare-digital-get,
`ERCXSFDL0VM8X` app.wecare.digital) genuinely have no web ACL. That is accurate
and unchanged — they serve the MTA-STS policy document, the secure-file download
origin, and an S3 origin. The Amplify-managed distribution is AWS-owned and not
among them, which is why the app-side query is the only readable proof.

### D7 · 33 of 41 alarms could not reach a human — ✅ RESOLVED 2026-09-26

`HIGH`, found while resolving D1, and larger than D1.

SNS topic `stack-wecare-digital` has exactly one subscriber: the
`wecare-inbound-whatsapp` Lambda. **33 of 41 alarms published only to that
topic**, and no topic subscription anywhere reaches a person for them. Among
them: `wecare-lambda-errors-wecare-razorpay-webhook`,
`wecare-ddb-throttle-PaymentsTable`, both `wecare-apigw-5xx-*`,
`wecare-bulk-dlq-depth`, `wecare-lambda-async-dlq-depth`,
`wecare-eventbridge-failed-*` and `wecare-lambda-throttles`.

Only `wecare-alarm-notifications` has a confirmed human subscription (one email
to the owner), and just 8 alarms used it.

The chain is worth stating because each link looks fine alone:

1. 33 alarms → topic `stack-wecare-digital`
2. that topic's only subscriber is `wecare-inbound-whatsapp`, a Meta webhook
   handler
3. it used to **crash** on those deliveries — `AttributeError: 'str' object has
   no attribute 'get'` at `wa_internal_event.py:80` in `_from_legacy_sns`, nine
   times in seven days, all on 2026-09-23 between 01:36 and 02:00, confirmed from
   the function's own logs
4. that crash was fixed in `wa_internal_event.py`, which made the handler
   **skip** unparsable records instead of raising
5. so the alarm notifications stopped crashing and started being silently
   discarded

Step 4 is correct on its own terms — `parse` promises never to raise, because
raising at the top of an async worker sends a poison event to the DLQ on every
retry. But it converted a noisy failure into a silent one, and the noise was the
only evidence the wiring was wrong.

The fix is deployed: `scripts/check_deployed_source.py wecare-inbound-whatsapp
--file wa_internal_event.py` reports v51 byte-identical to the tree. The alias was
published 00:42 UTC and the commit landed 00:48 UTC, so this was a
deploy-then-commit, not an undeployed fix.

**Resolution.** `wecare-alarm-notifications` was **added** to the `AlarmActions`
and `OKActions` of all 33, so every alarm in the account now has at least one path
to a person. The Lambda subscription was deliberately left in place — it may be
intentional, and removing it is a separate decision from making sure a human also
finds out.

`PutMetricAlarm` rewrites an alarm wholesale, so the change was verified by
diffing all 41 alarms before and after across 16 non-action fields: **0 changed**,
41 before and 41 after with none added or removed, and the one metric-math alarm
(`wecare-apigw-latency-wecare-digital-api`) retained all 3 of its `Metrics`
entries. All 41 remained `OK`, so no alert storm followed.

**Still open:** why an alarm topic is subscribed to a message handler at all.
Nothing documents it, and the handler now discards the payloads. Either give that
topic a real consumer or remove the subscription — but that is a design question,
not drift.

### D8 · PayU alarms outlived the provider — ✅ RESOLVED 2026-09-26

`MEDIUM`, item 8. Two alarms named `FunctionName=wecare-payu-webhook`, a Lambda
that does not exist:

| Alarm | Metric | State |
|---|---|---|
| `wecare-lambda-errors-wecare-payu-webhook` | `Errors` Sum > 3 | `OK` |
| `wecare-url-hit-wecare-payu-webhook` | `UrlRequestCount` Sum > 0 | `OK` |

The second is the more interesting one: a deliberate tripwire meant to catch
anyone still calling the retired PayU webhook. Because its target is absent the
metric never reports, so it read `OK` — the same false comfort as D1, one service
over. A tripwire on a deleted resource is not a tripwire.

Both deleted after exporting their definitions
(`.scratch/payu-alarms-before-20260926.json`). Alarm count 42 → 41 (−2 PayU,
+1 notification DLQ). No `payu`-named alarm remains.

Found by generalising the D1 cross-check from `QueueName` to every enumerable
dimension. Restricting it to queues found two broken alarms and missed two more.
The generalised check now also confirms the 15 `wecare-ddb-throttle-*` alarms all
name live tables — a concern worth checking rather than assuming, since they use
short table names while every table is prefixed `stack-wecare-digital-`.

### D9 · PayU environment variables survive on a live function — ✅ RESOLVED 2026-09-26

`LOW`, item 8 and item 230. `wecare-whatsapp-business-api` carried `PAYU_MID` and
`PAYU_UPI_ID` in its deployed environment. No code read either — verified across
the function package and the whole repository, with no `os.environ`/`getenv`
reference to either name anywhere. Dead configuration, not a live dependency.

Removed: 18 env vars → 16, `live` alias v41 → v42, `CodeSha256` **identical**
before and after, so this was configuration-only and nothing about message
handling moved. Version published and alias moved per the deploy rule.

`config/lambda-env-manifest.json` also listed both keys, and my first reading of
that was wrong: it is not a recreation path. `scripts/env_manifest.py` never
deploys — it records live state so drift shows in a diff. The manifest is a
mirror, so the order is remove-from-AWS-then-re-export. Re-exported; the drift
check reports `IN SYNC`, 0 differences across 65 functions.

Full retirement evidence, including the recovery-window proof and every retained
reference with its justification: `docs/payu-retirement-manifest.md`.

The remaining PayU artifact in AWS is the log group
`/aws/lambda/wecare-payu-webhook` — 8 KB, 90-day retention, last event
2026-07-17, auto-expires ~2026-10-15. Left to expire rather than deleted:
discarding payment-gateway logs early is a worse default than letting retention
do it, and it needs no action.

### D3 · No declarative source reproduces production infrastructure

`HIGH` for items 196, 218–225 and 226. `stack-wecare-digital-` is a **naming
prefix, not a CloudFormation stack**. Evidence:

- 7 CloudFormation stacks exist in total (including every non-active status):
  `CDKToolkit`, five `wecare-elevenlabs-*`, and `wecare-temp-code-inspector`.
- Zero stacks named `amplify-*` or `stack-wecare*`.
- `wecare-contacts` carries **no tags at all** — no
  `aws:cloudformation:stack-name`.

The 65 Lambdas, 79 DynamoDB tables and 8 queues were created imperatively by the
scripts in `scripts/`. The `amplify/` tree is source-of-truth for function
**code**, deployed by `scripts/deploy_all_lambdas.py` via
`update-function-code`; the Amplify app `d22dm4b0jn71jw` is frontend hosting
only (`platform=WEB`, 23 custom rules). No `cdk synth` or `terraform plan`
reproduces the account, so item 196 cannot be satisfied by validating the
existing `amplify/` definitions, and the DR drills in items 218–225 must be
written against scripts plus Lambda alias rollback rather than stack rollback.

`wecare-temp-code-inspector` and the five `wecare-elevenlabs-*` stacks are
leftovers and belong in item 226's cleanup scope.

### D4 · API-Gateway-level authorization is still entirely absent

`HIGH`, item 6. All **361 of 361** routes report `AuthorizationType=NONE` and
the API has **0 authorizers**. The route count grew by 29 against the dated
snapshot, so the surface widened while authorization stayed at zero. Per
steering this must be read carefully — handler-level authentication and provider
signature verification may well exist — but there is no gateway-level control on
any route, so item 6's "separate intentionally public signed webhooks from
accidentally public APIs" cannot be answered from gateway configuration alone
and requires the handler-level audit.

### D5 · Lambda alias coverage drifted again, as predicted

`INFORMATIONAL`. 58 of 65 functions have a `live` alias. The 7 without, where
`$LATEST` reaches production directly: `wecare-ad-attribution`,
`wecare-docs-scraper`, `wecare-get-miss-redirect`,
`wecare-partner-token-refresh`, `wecare-seo-tools`, `wecare-sla-engine`,
`wecare-url-shortener`.

`lambda-snapstart-deploy.md` records 56/6 then 53/9 and warns the ratio drifts as
aliases are provisioned. It is now 58/7. Three of the seven
(`docs-scraper`, `get-miss-redirect`, `seo-tools`) are documented deliberate
exceptions. The other four are not yet explained.

SnapStart remains `None` on all 65 functions, confirming that steering file's
correction. Runtime is `python3.12` on 64 of 65; the exception is
`wecare-docs-scraper` (`PackageType=Image`).

### D6 · 67 of 79 DynamoDB tables are empty

`INFORMATIONAL`, feeds items 227 and 234. Empty is not the same as unused — a
cache or a table behind an unreleased feature is legitimately empty — but 85% of
the table estate holding nothing is the measurement item 227 needs. 12 tables
lack point-in-time recovery; most are caches (`CatalogCacheTable`,
`SiteLanguageCache`, `WixProductsCache`, `WixOrdersCache`), but
`SecureFilesTable`, `DownloadGrantsTable`, `PstnSoftphoneSessions`,
`WhatsAppPhonesTable`, `FlowDraftTable`, `WebhookDedup` and `RateLimitTable`
also lack it.

**Re-measured 2026-09-29: 7 of 79, and the remaining 7 are ➖ NOT REQUIRED.** Five of
the twelve gained PITR with the 2026-09-26 audit. Every one of the seven left is
either empty or entirely TTL-governed:

| Table | Items | TTL |
|---|---:|---|
| `CatalogCacheTable` | 0 | ENABLED on `ttl` |
| `PstnSoftphoneSessions` | 0 | ENABLED on `expiresAt` |
| `RateLimitTable` | 210 | ENABLED on `lastUpdatedAt` |
| `SiteLanguageCache` | 175 | ENABLED on `expiresAt` |
| `WebhookDedup` | 181 | ENABLED on `ttl` |
| `WixOrdersCache` | 0 | **DISABLED** |
| `WixProductsCache` | 0 | **DISABLED** |

PITR on a table whose every row deletes itself buys a continuous backup of data that
is designed not to persist. And it would not defend the one case that sounds alarming:
`WebhookDedup` is the replay guard, but **PITR restores to a NEW table**, so recovering
it would not stop a replay inside the dedup window — every consumer would have to be
repointed first. The actual protection there is downstream idempotency, not backup.
Calling this a gap and "fixing" it would buy cost and a false sense of a control.

**The real defect under this heading is the two DISABLED TTLs**, and it is not PITR.
`WixOrdersCache` and `WixProductsCache` are caches by name and intent with nothing to
expire their rows. They read as clean only because both are empty, and both are empty
only because Wix writes are switched off — so this is latent, not absent. It is already
registered as improvement **I8** in `src/pages/workspace/dashboard/system-architecture.tsx`
("Add TTL to remaining temporal tables … WixProductsCache, WixOrdersCache. Prevents
unbounded table growth").

Deliberately **not** half-fixed here. Enabling TTL on a table alone does nothing:
DynamoDB only expires an item that carries the TTL attribute, and neither the
`amplify/data/resource.ts` model nor `ecommerce/wix-store/handler.py`'s `_sync_products`
/ `_sync_orders` writes one. Switching TTL on without the model field and the writer
would produce a control that cannot act — the same shape as the alarms that were
permanently green on a stale dimension. All three changes belong in one change, with
the writer first.

## Provider retirement — exact recovery-window evidence

From CloudTrail `DeleteSecret` events (60-day lookback), which gives the precise
dates items 8–12 require:

| Secret | Deleted | Window | Permanent deletion | State today |
|---|---|---:|---|---|
| `wecare/payu` | 2026-08-26 10:10:20Z | 30d | **2026-09-25 10:10:20Z** | ✅ **permanently gone** |
| `wecare/airtel-iq` | 2026-09-20 01:46:18Z | 30d | 2026-10-20 01:46:18Z | ⏳ recoverable |
| `wecare/airtel/c2c` | 2026-09-20 01:46:18Z | 30d | 2026-10-20 01:46:18Z | ⏳ recoverable |
| `wecare/airtel/obd` | 2026-09-20 01:46:18Z | 30d | 2026-10-20 01:46:18Z | ⏳ recoverable |
| `wecare/airtel/sms` | 2026-09-20 01:46:19Z | 30d | 2026-10-20 01:46:19Z | ⏳ recoverable |
| `wecare/sinch/sms` | 2026-09-20 01:46:19Z | 30d | 2026-10-20 01:46:19Z | ⏳ recoverable |
| `wecare/elevenlabs` | 2026-09-20 08:50:01Z | force | 2026-09-20 08:50:01Z | ✅ gone (forced) |
| `wecare/wix-api-key` | 2026-09-23 02:36:45Z | force | 2026-09-23 02:36:45Z | ✅ gone (forced) |

**Item 8's secret-layer requirement is now provable and met.** `ListSecrets`
with `IncludePlannedDeletion=True` returns 31 secrets and **zero** matching
`payu`. Its 30-day window expired 2026-09-25, one day before this measurement,
so `wecare/payu` is permanently deleted and unrecoverable. Razorpay remains,
as `wecare/razorpay/api` and `wecare/razorpay-webhook`.

This also reconciles the "six already scheduled" figure in standing
authorization: five provider secrets plus `wecare/elevenlabs`, which was
subsequently force-deleted, leaving five scheduled.

**Items 9, 10, 11 and 12 cannot yet claim permanent deletion.** The four Airtel
secrets and `wecare/sinch/sms` stay recoverable until **2026-10-20**. Per
standing authorization these are to be left to complete — never cancelled, never
rescheduled. `wecare/sinch/rcs` is present and untouched, which is correct: item
11 retires Sinch SMS only.

## Healthy, no action needed

- **S3** — all 6 buckets encrypted (3 `aws:kms`, 3 `AES256`), full public-access
  block on every one, no public bucket policy, versioning on 5 of 6
  (`wecare-digital-mta-sts` is the exception and holds only the public MTA-STS
  policy document).
- **CloudWatch logs** — 81 log groups, **zero without a retention policy**,
  0.16 GB stored total.
- **Route 53** — single zone `wecare.digital.` (`Z03939753QJGZ6ZD6BXO8`), 42
  records, exactly one MX, 7 TXT. Consistent with the fail-closed email posture;
  nothing in this inventory touched it.
- **EventBridge** — 6 rules, all `ENABLED`, no disabled rules. Two of the four
  scheduled rules have a target DLQ (`media-cleanup`, `scheduled-messages`); the
  other two (`docs-scraper-daily`, `partner-token-refresh-daily`) do not, which
  is a minor gap rather than a defect.
- **Amplify `stack` branch** — production, auto-build on, three most recent jobs
  all `SUCCEED`, latest job 896 at commit `5653a12a0f5a` (2026-09-26 03:05Z).

## What this changes in the backlog

| Item | Effect of this measurement |
|---|---|
| 1 | Complete. `aws-inventory.{json,md}` + this file are the deliverable; regenerable in ~150s with 0 errors. |
| 4 | Re-scoped from "build the notification service" to "write the code against four already-correct tables and an existing queue/DLQ pair". |
| 5 | Migration source identified: `CallNotificationsTable` (`callId`, 0 items). |
| 6 | Quantified: 361/361 `NONE`, 0 authorizers. Gateway config alone cannot classify the routes; needs the handler audit. |
| 8 | **Closed.** No PayU Lambda, route, table, secret, alarm or env var; secret's recovery window expired 2026-09-25; all live source and UI references removed; no recreation path. Guards, tombstones and remediation history retained on purpose. Manifest: `docs/payu-retirement-manifest.md`. |
| 9–12 | Blocked on the 2026-10-20 window expiry, by design. Exact ARNs and dates now recorded. |
| 39 | SES layer satisfied in `us-east-1`; `ap-south-1` is sandboxed and must not be used for customer email. |
| 113/114 | Admin MFA is `OPTIONAL` not `OFF`; RBAC groups already exist. |
| 196/218–225 | Must be designed against imperative scripts — no stack reproduces production. |
| 213/214 | **Resolved.** Every DLQ alarmed on the correct dimension and statistic (D1), every alarm routable to a human (D7), no alarm naming an absent resource (D8). Re-checkable with `provision_alarm_coverage.py --verify` and the inventory cross-checks. |
| 226/227/234 | Baseline captured: 7 stacks (6 stale), 67 empty tables. |

## Reproducing this

    python scripts/aws_account_inventory.py            # all 14 families, ~150s
    python scripts/aws_account_inventory.py --only lambda,api_gateway
    python scripts/aws_account_inventory.py --json-only

The collector counts its own failures and reports `error_count`; a non-zero
count marks the inventory PARTIAL. This is deliberate — an earlier alias census
read 34/28 instead of 53/9 because failed API calls were silently treated as
"resource absent". Treat any run with `error_count > 0` as unusable for
decisions.

`--only` writes to `aws-inventory.partial.{json,md}` (gitignored) and leaves the
committed full inventory alone. That separation matters for the same reason: in a
single-collector run every other family serialises as `null`, which is
indistinguishable from "this account has no queues" once the file is read back a
week later.
