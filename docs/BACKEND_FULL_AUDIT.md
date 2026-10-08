# Backend Full Audit — tables, functions, AWS resources, secrets (phased)

Companion to `FRONTEND_FULL_AUDIT.md`. Account `775261844268` · `us-east-1` · Amplify Gen 2.
Covers every Lambda, table, AWS resource, and secret, with gaps + a phased plan (autopilot-safe vs gated).

## 0. Snapshot
- **65 Lambdas** (64 `python3.12` Zip + 1 Image), deployed via `scripts/deploy_all_lambdas.py` (**outside IaC** — no CloudFormation stack owns them; `stack-wecare-digital-` is a name prefix, not a stack).
- **79 DynamoDB tables** · **8 SQS** · **2 Cognito pools** · **6 EventBridge rules** · **31 secrets** · **6 S3** · **1** HTTP API (`zllr9lrg7j`, 361 routes).
- 41 alarms + 6 DLQs + 1 dashboard + retention on all 81 log groups. **PITR ON** (67 of 79), **TTL ON**, **email alert confirmed**.

> Counts re-measured **2026-09-26** with `python scripts/aws_account_inventory.py` (0 collector errors). Do not hand-edit them — regenerate `docs/execution/aws-inventory.md` and read it there.

## 1. Lambda functions (by domain)
**Core (5):** contacts (`[retired public path 44011e36]`), messages-read (`/messages`), messages-delete, faq-handler (`[retired public path 1965ee0f]`), url-shortener (`[retired public path 21d99b11]`).
**Messaging (24):** inbound-whatsapp (`/webhook/whatsapp`, 512MB/120s), outbound-whatsapp (SQS+API), whatsapp-business-api (`/wa-business/*`), whatsapp-calling, whatsapp-voice, whatsapp-templates, template-management, waba-management, outbound-sms, sms-aws, sms-in-airtel, outbound-email, outbound-voice, voice-aws, voice-in-c2c/obd/cdr, voice-cdr-read, scheduled-messages (EventBridge), template-analytics, ad-attribution, push-notifications, meta-analytics, media-cleanup.
**AI (4):** ai-generate-response (Bedrock), ai-query-kb (KB), ai-config-management, agent-action-group (Bedrock Agent).
**Payments (4):** razorpay-webhook, payu-webhook, payments-read, invoice-engine (8 tables).
**Operations (7):** bulk-job-create, bulk-job-control, bulk-worker (SQS, 512MB/300s), dlq-replay, billing (AWS Health + Support/Trusted Advisor; Cost Explorer removed 2026-09-28), system-cleanup (EventBridge daily), sla-engine.
**Ecommerce (2):** wix-store, product-image-gen.
**Other core-dir (~8):** auth-middleware, automation-rules, conversation-meta, service-api, rcs-send, rcs-dlr, sinch-dlr, catalog-management.

Findings:
- All are wired (API GW / SQS / EventBridge / Bedrock) — **none dead**.
- Memory/timeout look reasonable (heavy: inbound-whatsapp 512/120, bulk-worker 512/300).
- **Gap:** no versions/aliases → no rollback; outside IaC → drift/no review.
- **Gap:** `push-notifications` lists no tables but `PushTokensTable` exists — verify wiring.

## 2. Naming drift (documentation vs live tables) — VERIFY, likely real bugs
The app's own infra map + some handlers reference table names that DON'T match live tables:
| Referenced in code/docs | Live table | Risk |
|---|---|---|
| `FAQTable` / env `FAQ_TABLE=…-FAQTable` | `FaqTable` | faq-handler may write to a non-existent table |
| `AuditLog` / `AuditLogTable` (service_api.py) | `AuditLogsTable` | audit writes silently fail |
| `RateLimitTracker` | `RateLimitTable` | (backend.ts TTL bug already removed) |
| `OBDCampaignTable` | `OBDCampaigns` | OBD writes may fail |
| `AdAttributionTable` | `AdClickAttributionTable` | ad-attribution writes may fail |
| `TemplateTable` | (none — templates live in Meta) | dead reference |
**Action:** grep each handler's real `os.environ.get(..., default)` and confirm the deployed env var overrides the wrong default. This is the #1 correctness risk found.

## 3. DynamoDB tables (~61) — grouped
**Core:** `ContactsTable` (GSIs: phone, email, bsuid — used by 7 fns), `UsersTable`, `SystemConfigTable`, `FaqTable`, `ShortLinksTable`/`LinkClicksTable`, `MediaFilesTable`.
**Messages:** `MessagesTable` (unified timeline), `WhatsAppInbound/Outbound` (TTL, GSIs), `WhatsAppCalling`, `WhatsAppVoice`, `WhatsAppGroup`, `ScheduledMessages`, `RcsMessages`(?).
**SMS/Voice:** `SmsAws`, `AirtelSMS`, `SmsInAirtel`, `SmsOutbound`, `DLTTemplates`, `VoiceAws`, `AirtelC2C`, `VoiceCDR`, `VoiceCalls`, `OBDCampaigns`.
**Payments:** `Payments`, `Invoices`, `InvoiceItems`, `InvoiceAssets`, `InvoiceDeliveryLog`, `InvoiceSequence`, `Razorpay/PayUWebhookLog`.
**Flows/Service:** `SubmitRequests`, `FlowRegistry`, `FlowSubmission`, `FlowLog`, `Order`, `Appointment`, `RxSlot`, `Document`, `EnterpriseAssist`, `Review`, `RequestStatusHistory`, `CallNotifications`.
**AI:** `ConversationHistory`, `AIInteractions`.
**Ops/Analytics:** `BulkJobs`, `BulkRecipients`, `DLQMessages`, `AuditLogs`, `RateLimit`, `SystemEvent`, `TemplateAnalytics`, `AdClickAttribution`, `CatalogCache`.
**Ecom/Wix:** `WixProductsCache`, `WixOrdersCache`, `WixOrderIds`.

Status: **TTL enabled on 19** (fixed this cycle); **PITR ON** (key tables); most per-channel tables are low-traffic/empty (NOT dead — have writers). Consolidation target ~61 → ~35–40 (see `AWS_CONSOLIDATION_AUDIT.md`).
Per-table risks: single-table GSIs mostly fine; verify **PAY_PER_REQUEST** billing on all (throttle-free).

## 4. Other AWS resources
- **SQS (8):** bulk-queue → bulk-dlq and notification-queue → notification-dlq (both maxReceive 3), plus inbound-dlq, outbound-dlq, wecare-eventbridge-dlq, wecare-lambda-async-dlq.
  **Corrected 2026-09-26:** the claim that DLQ-depth alarms "exist. Good." was false. Two named a `base-wecare-digital-` queue prefix that no longer existed and returned **zero datapoints over 6 hours**, and the notification DLQ had no alarm at all. All six now alarm on `Maximum > 0` against a real queue — see `scripts/provision_alarm_coverage.py --verify`.
- **EventBridge (6):** media-cleanup-daily, scheduled-messages (5-min), docs-scraper-daily, partner-token-refresh-daily, amplify-build-failed, + AWS-managed notifications. `FailedInvocations` alarms now exist for media-cleanup and scheduled-messages; docs-scraper-daily and partner-token-refresh-daily still have **no target DLQ**.
- **Cognito (2):** `WECARE.DIGITAL` (staff, MFA `OPTIONAL`, deletion protection ACTIVE, groups Admin/Operator/Partner/Viewer) and `WECARE.DIGITAL-CUSTOMERS` (public passwordless WhatsApp OTP, MFA OFF, deletion protection INACTIVE). Both are behind the `wecare-cognito-waf` web ACL. **Gap: Advanced Security is `None` on both; no user-export DR.**
- **API Gateway:** HTTP APIs for wa-business / service / url-shortener. **Gap: no 5xx/latency alarms.**
- **S3 (6):** `app.wecare.digital`, CDK assets, `wecare-digital-get`, `wecare-digital-mta-sts`, `wecare-credential-backups-*`, `wecare-maintenance-reports-*`. All encrypted, all with a full public-access block, versioning on 5 of 6.
- **SNS:** `stack-wecare-digital` alarm topic — email `one@wecare.digital` **confirmed**.
- **KMS:** keys present. (Rotation de-scoped by owner.)

## 5. Secrets Manager (11) — all used, well-namespaced
`meta-app-secret`, `meta-system-user-token` (rotated Apr), `airtel-iq`, `airtel/obd`, `airtel/c2c`, `airtel/sms`, `flow-private-key`, `seo/google-oauth`, `wix-api-key`, `sinch/sms`, `sinch/rcs`.
- **Gap:** static tokens, no auto-rotation (most are external-provider tokens that can't auto-rotate). **Action:** monitor `LastAccessedDate` for stale secrets; ensure least-privilege resource policies. No secrets in code (all via Secrets Manager) — good.

## 6. Gaps summary (backend)
1. **Naming drift** (§2) — highest correctness risk; verify handler env defaults vs live table names.
2. **Lambdas outside IaC** — no rollback/review/drift-detection.
3. **No DynamoDB / API GW alarms**; **EventBridge no DLQ**.
4. **No Lambda versions/aliases** (no instant rollback).
5. **Cognito hardening** unverified.
6. **Table proliferation** (~61) — consolidation opportunity.

## 7. Phased plan (autopilot-safe vs gated)

### Phase 1 — READ-ONLY / ADDITIVE (autopilot-safe: no risk to live traffic)
- **1a. Verify naming drift** — grep every handler's `os.environ.get('X_TABLE', default)` + compare to live tables; produce a bug list. (read-only)
- **1b. Verify billing mode** = PAY_PER_REQUEST on all tables. (read-only)
- **1c. Add alarms in IaC** (`backend-resources.ts`): DynamoDB throttle/system/user errors; API GW 5xx/latency; Amplify build-failed; EventBridge FailedInvocations + target DLQ. (additive; applies on `ampx pipeline-deploy`)
- **1d. Cognito check** — Advanced Security / MFA / deletion protection status. (read-only)

### Phase 2 — GATED (needs review + maintenance window)
- **2a. Fix any naming-drift bugs** (correct env vars / handler defaults) → deploy the affected functions.
- **2b. Lambda versions + `live` alias + CodeDeploy canary auto-rollback.**
- **2c. Auto-remediation** (alarm → EventBridge → auto-redrive DLQ).

### Phase 3 — STRUCTURAL (largest, gated)
- **3a. DynamoDB consolidation** ~61 → ~35–40 (unify per-channel into `Messages` timeline; caches; payment webhook logs).
- **3b. Lambda → IaC** via `cdk import` (zero-replacement diff gate) + `ampx pipeline-deploy` with PR review.

### Autopilot guidance
- **Safe to run in Autopilot:** Phase 1 (all read-only or additive-IaC), plus the `_verify_ddb_ttl.py` / `_check_resilience.py` drift checks on a schedule.
- **Require Supervised + confirmation:** Phase 2 & 3 (deploys, alias cutover, table consolidation, cdk import) — they can delete data or replace live functions.

## Note (your local git — screenshot)
Your local shows `package.json` + `package-lock.json` modified — that's your `npm install` regenerating a *different* (95-vuln) lock than the committed clean 46-vuln one. **Discard both** (`git checkout -- package.json package-lock.json`); do not commit them, or you'll regress the clean lock that's already deployed.
