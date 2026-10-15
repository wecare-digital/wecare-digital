# AWS Resource Audit & Consolidation Plan

Read-only audit of the live account (`775261844268`, `us-east-1`). Goal: organize/consolidate
tables and resources **first**, then move everything into IaC. Data deletion is acceptable (per owner).

## Inventory (live)
| Service | Count | Notes |
|---|--:|---|
| DynamoDB tables | ~61 | many empty/low-traffic; strong consolidation potential |
| Lambda functions | 54 | Python 3.12, deployed via script (not IaC) |
| SQS queues | 4 | bulk-queue, bulk-dlq, inbound-dlq, outbound-dlq — fine |
| Cognito user pools | 1 | `WECARE.DIGITAL` — fine, keep |
| EventBridge rules | 3 | 1 AWS-managed + media-cleanup-daily + scheduled-messages-trigger — fine |
| Secrets Manager | 11 | well-namespaced (`wecare/...`) — fine, keep |
| S3 buckets | 2 | `app.wecare.digital` + CDK assets — fine |
| API Gateway | (see note) | HTTP APIs for wa-business / service / url-shortener |

The only service with real bloat is **DynamoDB**. Everything else is already lean.

## Bugs found during audit
1. **TTL was silently off on 19 tables** — fixed this session (enabled directly; `backend.ts` footgun removed).
2. **`backend.ts` referenced `RateLimitTracker`** (wrong) — the real table is **`RateLimitTable`**; and the attr `lastUpdatedAt` was not an expiry. Both wrong; mapping removed.
3. **Evidence/reality drift** — `_audit_evidence/dynamodb_tables.json` still lists `RcsMessagesTable`/`SmsAwsTable`, but the live account no longer has them (only backups remain). Confirms config/reality can silently diverge (the core reason to move to IaC).

## DynamoDB consolidation map (61 → ~35–40 target)

### A. Per-channel message/log tables → unify (biggest win)
Today each channel has its own inbound/outbound/log table:
`MessagesTable`, `WhatsAppInboundTable`, `WhatsAppOutboundTable`, `SmsAwsTable`, `SmsOutboundTable`,
`RcsMessagesTable`, `VoiceAwsTable`, `WhatsAppVoiceTable`, `WhatsAppCallingTable`, `VoiceCalls`,
`VoiceCDRTable`.
- **Recommendation:** one unified `Messages` table keyed by `contactId`/`conversationId` with a
  `channel` attribute (whatsapp|sms|rcs|voice) + GSIs, replacing ~10 of these. Voice CDR/call-detail
  can stay separate (different shape). This is the single largest simplification but requires handler
  refactors + a data migration (acceptable since data-loss is OK — you can cut over fresh).

### B. Cache tables → unify or drop
`CatalogCacheTable` — a cache.
- **Recommendation:** one `Cache` table with `type` prefix + TTL, or drop entirely and re-fetch. Low risk.

### C. Payment webhook logs → unify
`RazorpayWebhookLogTable` + `PayUWebhookLogTable` → one `PaymentWebhookLog` with `provider` attribute.

### D. Invoice tables → partially merge
`InvoicesTable`, `InvoiceItemsTable`, `InvoiceAssetsTable`, `InvoiceDeliveryLogTable`, `InvoiceSequenceTable`.
- Keep `InvoiceSequenceTable` (atomic counter) and `InvoicesTable`. `InvoiceItems`/`Assets` can be
  nested into the invoice item (single-table) unless queried independently. `DeliveryLog` → fold into unified Messages/log.

### E. "Empty" tables — DO NOT DELETE (evidence-based correction)
Grep of handler code proves the empty tables are **empty because the channel/feature is low-traffic,
NOT because they're dead**. Each has an active writer:
- `WhatsAppCallingTable` ← whatsapp-calling, `VoiceAwsTable` ← voice-aws,
  `WhatsAppVoiceTable` ← whatsapp-voice, `AdClickAttributionTable` ← ad-attribution,
  `CatalogCacheTable` ← catalog-management, `DLQMessagesTable` ← dlq-replay, `AuditLogsTable` ← shared audit.py,
  `Razorpay/PayUWebhookLogTable` ← the two payment webhooks.
- **Conclusion:** deleting them would break live handlers. Reduction must come from **schema consolidation
  + handler refactor (A–D)**, not from dropping "empty" tables. Only drop a table after its writer is removed.

### Additional bugs found (drift)
- **Naming mismatch:** `service_api.py` writes to `{PREFIX}-AuditLogTable` (singular) but the real table is
  `AuditLogsTable` (plural) — likely silent write failures. Same file references `AmendmentHistoryTable` /
  `AdminActionLogTable` which may not exist. Verify + fix names.
- **Unified timeline already exists (partial):** `whatsapp-voice`, `voice-aws`, `whatsapp-calling` already write
  a thin "breadcrumb" row into `MessagesTable` (`UNIFIED_MESSAGES_TABLE`) while keeping the full record in the
  per-channel table. So consolidation option (A) is **already half-designed** — the target pattern is
  "per-channel detail tables + one unified `Messages` timeline." Formalizing that is lower-risk than a full merge.

### Keep as-is (distinct access patterns — do NOT merge)
`ContactsTable`, `UsersTable`, `OrderTable`, `PaymentsTable`, `ConversationHistoryTable`,
`FlowRegistry/Log/Submission`, `Appointment`, `RxSlot`, `Review`, `Document`, `Faq`, `SystemConfig`,
`RateLimitTable`, `ShortLinks/LinkClicks`, `BulkJobs/BulkRecipients`, `PushTokens`, `TemplateAnalytics`,
`DLTTemplates`, `FlowSubmission`, `SubmitRequests`, `RequestStatusHistory`.

## Lambda (54) — grouping & consolidation
Grouped by domain prefix (all `python3.12`):
- **messaging** (~24): inbound-whatsapp, outbound-whatsapp, whatsapp-business-api, whatsapp-calling,
  whatsapp-voice, whatsapp-templates, whatsapp-template-management, waba-management, outbound-sms,
  sms-aws, outbound-email, voice-aws, voice-cdr-read, plivo-answer, pstn-softphone, scheduled-messages, template-analytics, ad-attribution, push-notifications,
  media-cleanup, meta-analytics
- **ai** (4): ai-query-kb, ai-generate-response, ai-config-management, agent-action-group
- **payments** (4): invoice-engine, payments-read, razorpay-webhook, payu-webhook
- **ecommerce**: checkout, native-catalog-admin, coupons, gift-cards, customer-orders,
  customer-invoice, meta-catalog-sync, product-image-gen
- **operations** (6): system-cleanup, sla-engine, bulk-worker, bulk-job-create, dlq-replay, billing
- **core** (~10): auth-middleware, automation-rules, contacts, conversation-meta, faq-handler,
  messages-delete, messages-read, service-api, url-shortener

**Consolidation view:** Lambda count is *reasonable* for the surface area — do **not** over-merge
(micro-functions give clean IAM boundaries + independent scaling). Only obvious merge:
- `messages-read` / `messages-delete` → one `messages` CRUD function (optional).
The bigger Lambda issue is **not count, it's that they're outside IaC** (see Lambda IaC plan).

## What CAN vs CANNOT consolidate
**CAN:** per-channel message/log tables (→1 unified), cache tables (→1 or drop), payment webhook logs
(→1), empty tables (drop), a couple of read/write Lambda pairs.
**CANNOT / should not:** Cognito (1 pool already), Secrets (each a distinct credential), SQS queues +
their DLQs (need separation), S3 buckets, invoice sequence counter, and any table with a unique
access pattern / GSI shape. Merging those trades clarity for coupling.

## Phased execution plan

### Phase 0 — Baseline & safety (read-only) — 1 day
- Full live snapshot: per-table item counts + writers (grep handlers for each table name), Lambda
  configs, event mappings, IAM roles, API routes. (The audit script `scripts/_deep_aws_audit.py` does
  most of this; run it where AWS latency is low.)
- Tag every resource: `project=wecare`, `env=prod`, `owner`, `managed-by`.

### Phase 1 — Organize tables (data deletion OK) — 2–4 days
1. Grep the repo for each table name; any table with **no writer/reader** → delete.
2. Merge payment webhook logs → `PaymentWebhookLog`; caches → `Cache` (or drop).
3. Decide the unified `Messages` schema (channel attribute + GSIs); update handlers to write there;
   cut over (no back-migration needed since data-loss acceptable). Retire the per-channel tables.
Result: ~61 → ~35–40 tables, all with correct TTL + tags.

### Phase 2 — Full IaC adoption — 1–2 weeks
- Bring the (now-fewer) tables + the 54 Lambdas + queues + rules + API routes under CDK/Amplify Gen2
  via `cdk import` (adopt, never recreate). Gate on **zero-replacement `cdk diff`**. See
  `docs/LAMBDA_IAC_IMPORT_PLAN.md`.
- Move Lambda deploys from `_deploy_everything.py` to `ampx pipeline-deploy` with versions/aliases
  (instant rollback) + PR review.

### Phase 3 — CI/CD hardening
- One pipeline deploys frontend + backend + functions atomically; drift detection; alarms already exist.

## Immediate safe next step (no destructive change)
Run the writer-map: for each of the 61 tables, grep the handlers to see which are actually read/written.
That produces the definitive "dead table" list before any deletion. Say the word and I'll generate that
table→code usage map (read-only) so Phase 1 deletions are evidence-based.
