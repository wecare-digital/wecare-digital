# WhatsApp Platform Module Map

> **Part 1 deliverable** (Kiro WhatsApp Platform prompt pack). Read-only inventory + gap analysis.
> No business logic was modified to produce this map. This is an **upgrade map** for the existing
> repository — no NestJS/Prisma/PostgreSQL migration is proposed.
>
> Generated 2026-06-26 · Repo `wecare-digital/wecare-digital` (branch `stack`).
>
> The repo was recorded here as `wecaredigital/[retired-legacy-host]`, which is neither
> the current remote nor a host that resolves — and `retired legacy frontend host` is NXDOMAIN.
> Corrected 2026-09-26 to `wecare-digital/bharat-stack`, then again 2026-09-28: the
> repository was **renamed to `wecare-digital/wecare-digital` on 2026-09-27**. GitHub
> redirects the old path, so a stale URL looks fine in `git` while breaking things that
> match on the name — three IAM OIDC trust policies and the Amplify app all failed
> silently. The branch name `stack` is unchanged and is the only long-lived branch.

## Stack confirmed (preserve as-is)
Next.js + React/TypeScript frontend · AWS Amplify Gen 2 · Cognito auth ·
DynamoDB/AppSync data (`amplify/data/resource.ts`, **41+ models**) · S3 storage
(`amplify/storage/resource.ts`) · Python 3.12 Lambdas (`amplify/functions`) · Meta Graph API **v25.0**.

WABA1 `2094615664435155` (phone `1016149501586345`) · WABA2 `2513394156072604` (phone `1055232054343117`).

## Existing data models (relevant subset)
Contact, Message, WhatsAppInbound, WhatsAppOutbound, MediaFile, DLQMessage, AuditLog,
RateLimitTracker, SystemConfig, ScheduledMessage, WhatsAppVoice, WhatsAppCalling, WhatsAppGroup,
TemplateAnalytics, SubmitRequest, ConversationHistory, AIInteraction, **WebhookDedup**,
**SystemEvent**, CatalogCache, AdClickAttribution, FlowRegistry, FlowDraft, FlowSubmission,
FlowLog, Payment, Invoice(+Item/Asset/DeliveryLog/Sequence), Razorpay/PayUWebhookLog, Wix*,
Order, Appointment, RxSlot, Document, EnterpriseAssist, Review, Faq, RequestStatusHistory.
(Note: `WebhookDedup` and `SystemEvent` models **already exist** — earlier draft incorrectly flagged dedup as absent.)

## Existing tests
`tests/`: business_api, calling, catalog, content, dlq_replay, gdpr, inbound_whatsapp, logging,
meta_analytics, middleware, outbound_whatsapp, payments, privacy, rate_limit, response,
template_management, validation, webhook_signature.

---

## Module entries (12-field schema)

### M1 · Inbound webhook handler
1. **Module**: Inbound WhatsApp (messages, statuses, system events, BSUID/username)
2. **Lambda**: `messaging/inbound-whatsapp-handler/handler.py` (`wecare-inbound-whatsapp`)
3. **Models**: WhatsAppInbound, Message, Contact, MediaFile, WebhookDedup, SystemEvent, AIInteraction
4. **Frontend**: `src/pages/dm/whatsapp/inbox.tsx`, `dm/inbox`
5. **Meta doc**: Webhooks — https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
6. **Missing endpoints**: contacts webhook (`REQUEST_CONTACT_INFO`), `business_username_updates` field subscription
7. **Missing validation**: confirm `x-hub-signature-256` verification on all webhook entries (present for some paths)
8. **Missing security/audit**: ensure WebhookDedup is consistently written for every inbound event id; audit on contact auto-create
9. **Missing UX**: surface BSUID/username + contact-book name in inbox UI
10. **Missing tests**: BSUID-only (phone-absent) path; user_id_update migration; dedup replay
11. **Risk**: Medium
12. **Order**: 3 (after shared foundation)

### M2 · Outbound messaging
1. **Module**: Outbound send (text/media/template/interactive/location/contacts/reaction/contextual reply, BSUID)
2. **Lambda**: `messaging/outbound-whatsapp/handler.py` (`wecare-outbound-whatsapp`)
3. **Models**: WhatsAppOutbound, Message, TemplateAnalytics
4. **Frontend**: `dm/whatsapp/inbox.tsx`, `dm/broadcast`, `dm/whatsapp/campaign.tsx`
5. **Meta doc**: Message API — https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/message-api/
6. **Missing endpoints**: typing indicator as standalone action (now folded into read receipt); `paid_messaging_account_id` (multi-messaging-account)
7. **Missing validation**: URL percent-encoding for template URL button params; per-type payload schema checks
8. **Missing security/audit**: audit log on every send (currently logged, confirm AuditLog write)
9. **Missing UX**: send-failure error panel (code/title/fbtrace_id)
10. **Missing tests**: BSUID-only send; reaction/contextual edge cases (have base outbound tests)
11. **Risk**: Medium
12. **Order**: 4

### M3 · Business API admin surface
1. **Module**: `/wa-business/*` Graph admin (profile, webhooks, groups, calling-settings, phone-settings, username, block-users, assigned-users, **bot, assigned-wabas, schedules, commerce-settings, qr-codes, conversational-automation, link-preview, ai-pricing-policy**)
2. **Lambda**: `messaging/whatsapp-business-api/handler.py` + `service_api.py` (`wecare-whatsapp-business-api`)
3. **Models**: WhatsAppGroup, SystemConfig, AIProviderPolicyTable, FlowRegistry/Submission/Log, Order/Document/Faq/Appointment/RxSlot/EnterpriseAssist/Review
4. **Frontend**: `dashboard/wa-graph-tools.tsx`, `dashboard/waba-usernames.tsx`, `dm/whatsapp/{groups,webhooks,business-profile,calling,settings,waba-dashboard}.tsx`
5. **Meta doc**: WABA ref — https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account
6. **Missing endpoints**: QR list/get fields polish; parent-BSUID accounts API; contact-book delete API
7. **Missing validation**: graph version + ID-format validators centralized (QR id ✓, others partial)
8. **Missing security/audit**: AuditLog on assigned-user changes, webhook subscribe/unsubscribe, username claim/delete, AI-policy edits
9. **Missing UX**: curl preview + JSON request/response viewer on `wa-graph-tools`
10. **Missing tests**: schedules/commerce/qr/conversational-automation/ai-pricing endpoints (have `test_business_api`)
11. **Risk**: Medium-High (broad surface, route quota previously hit)
12. **Order**: 5 (per-endpoint hardening)

### M4 · Template management
1. **Module**: Template CRUD + validation (category/TTL/components/buttons)
2. **Lambda**: `messaging/whatsapp-template-management/handler.py` (+ `whatsapp-templates/handler.py`)
3. **Models**: TemplateAnalytics
4. **Frontend**: `dm/whatsapp/templates.tsx`
5. **Meta doc**: Templates — https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview
6. **Missing endpoints**: `message_template_components_update` webhook handling; library templates (501 today)
7. **Missing validation**: ✓ category/TTL/button-grouping added; add named-vs-positional param example checks, LTO/SPM/MPM/carousel
8. **Missing security/audit**: AuditLog on create/delete/edit
9. **Missing UX**: live template preview + TTL selector keyed to category in builder
10. **Missing tests**: TTL ranges, button grouping (have `test_template_management`)
11. **Risk**: Medium
12. **Order**: 8

### M5 · WhatsApp Flows
1. **Module**: Flows engine (12 flow types) + E2E data-exchange
2. **Lambda**: `messaging/whatsapp-business-api/flows/*` (router, common, generic, per-flow handlers + JSON)
3. **Models**: FlowRegistry, FlowDraft, FlowSubmission, FlowLog, SubmitRequest
4. **Frontend**: `dm/whatsapp/{flows,flow-hub,flow-responses}.tsx`
5. **Meta doc**: Flows — https://developers.facebook.com/documentation/business-messaging/whatsapp/flows
6. **Missing endpoints**: flow metrics/assets endpoints; `data_api_version` upgrade audit
7. **Missing validation**: per-screen payload schema validation; encryption error normalization
8. **Missing security/audit**: AuditLog on flow publish/deprecate; private-key rotation via Secrets Manager
9. **Missing UX**: flow version-health surfacing; submission export polish
10. **Missing tests**: per-flow router cases (have `test_flow_routing` in module tests)
11. **Risk**: High (E2E crypto + payments)
12. **Order**: 8

### M6 · WhatsApp Calling
1. **Module**: Business calling (connect/terminate, permissions, SIP)
2. **Lambda**: `messaging/whatsapp-calling/handler.py` (`wecare-whatsapp-calling`)
3. **Models**: WhatsAppCalling, CallNotifications
4. **Frontend**: `dm/whatsapp/calling.tsx`, `dm/calls`, `hooks/useWebRTCCalling.ts`
5. **Meta doc**: Cloud API calling — https://developers.facebook.com/docs/whatsapp/cloud-api
6. **Missing endpoints**: call permission via template (partial), call hours config
7. **Missing validation**: SDP/session payload checks
8. **Missing security/audit**: audit on permission grants; SIP cert-expiry alarm (exists) doc
9. **Missing UX**: call analytics polish in `dm/analytics`
10. **Missing tests**: have `test_calling`
11. **Risk**: Medium
12. **Order**: 10

### M7 · WhatsApp Voice (TTS)
1. **Module**: Polly TTS audio messages
2. **Lambda**: `messaging/whatsapp-voice/handler.py` (`wecare-whatsapp-voice`)
3. **Models**: WhatsAppVoice
4. **Frontend**: (within inbox/templates flows)
5. **Meta doc**: Media API — https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/media/media-api/
6. **Missing endpoints**: resumable upload for large media
7. **Missing validation**: mime/size guards
8. **Missing security/audit**: audit on TTS send
9. **Missing UX**: voice preview in UI
10. **Missing tests**: none dedicated
11. **Risk**: Low
12. **Order**: 12

### M8 · WABA management
1. **Module**: WABA-level ops
2. **Lambda**: `messaging/waba-management/handler.py`
3. **Models**: SystemConfig
4. **Frontend**: `dm/whatsapp/waba-dashboard.tsx`, `dm/whatsapp/migration.tsx`
5. **Meta doc**: WABA-to-number — https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account-to-number-current-status
6. **Missing endpoints**: assigned-users (now in M3), client/owned WABA APIs
7. **Missing validation**: business-id required checks
8. **Missing security/audit**: audit on WABA config change
9. **Missing UX**: consolidated WABA health view
10. **Missing tests**: none dedicated
11. **Risk**: Medium
12. **Order**: 6

### M9 · Catalog / Commerce
1. **Module**: Catalog + commerce settings
2. **Lambda**: `ecommerce/catalog-management/handler.py`; commerce-settings in M3
3. **Models**: CatalogCache, WixProductsCache
4. **Frontend**: `dm/content`, `store`
5. **Meta doc**: Commerce settings (Graph) — WABA-to-number ref
6. **Missing endpoints**: product set sync; cart webhooks
7. **Missing validation**: catalog id checks
8. **Missing security/audit**: audit on catalog mutations
9. **Missing UX**: catalog browser
10. **Missing tests**: have `test_catalog`
11. **Risk**: Low-Medium
12. **Order**: 11

### M10 · Meta analytics / pricing
1. **Module**: Pricing + conversation analytics, **AI-Provider pricing policy (AI_BOT / general_purpose_ai)**
2. **Lambda**: `messaging/meta-analytics/handler.py`; AI-policy CRUD in M3
3. **Models**: AIProviderPolicyTable, TemplateAnalytics
4. **Frontend**: `dm/analytics`, `dm/cost`, `dashboard/wa-graph-tools.tsx` (AI Pricing tab)
5. **Meta doc**: Overview/pricing — https://developers.facebook.com/documentation/business-messaging/whatsapp/overview
6. **Missing endpoints**: pricing analytics `AI_BOT` ingestion; CSV/PDF rate-card import
7. **Missing validation**: market/effective-date format
8. **Missing security/audit**: audit on policy edits
9. **Missing UX**: rate-card upload UI
10. **Missing tests**: have `test_meta_analytics`
11. **Risk**: Low
12. **Order**: 19

### M11 · Ad attribution
1. **Module**: Click-to-WhatsApp attribution
2. **Lambda**: `messaging/ad-attribution/handler.py`
3. **Models**: AdClickAttribution
4. **Frontend**: `dm/analytics`
5. **Meta doc**: Overview
6–10. Minor (referral payload coverage, tests)
11. **Risk**: Low · 12. **Order**: 18

### M12 · Scheduled messages & DLQ replay
1. **Module**: Scheduling + failed-message replay
2. **Lambda**: `messaging/scheduled-messages/handler.py`, `operations/dlq-replay/handler.py`, `operations/bulk-worker`
3. **Models**: ScheduledMessage, DLQMessage, BulkJob, BulkRecipient
4. **Frontend**: `dm/scheduled`, `dm/broadcast`, `dm/logs`
5. **Meta doc**: Message API
6–10. Missing: schedules vs Meta `/schedules` (M3) reconciliation; audit on replay (have `test_dlq_replay`)
11. **Risk**: Medium · 12. **Order**: 9

---

## Cross-cutting gaps (prompt-pack Part 2 targets)

- **Shared Meta client**: each Lambda re-implements `_graph_api` / `_send_direct_api_message`
  (token cache, `appsecret_proof`, retry/backoff, pagination, error normalization). **Recommend
  `shared/lambda_utils/meta_client.py`** and migrate one module first. **Risk: Medium · Order: 1**
- **Webhook dedup**: model `WebhookDedup` exists; **recommend a shared `webhook_dedup.py`**
  idempotency helper used uniformly by inbound. **Risk: Medium · Order: 2**
- **Error normalization**: standardize Graph error → `{message,type,code,error_subcode,fbtrace_id}`
  shape across all modules.
- **Audit coverage**: ensure AuditLog write on every write/delete/publish/deprecate/refund/replay/
  unsubscribe/permission-change/secret-update.
- **Secret/ID hygiene**: move remaining hardcoded WABA/phone IDs to env/SystemConfig with
  backward-compatible defaults; never expose tokens to frontend (currently respected — all Meta
  calls are server-side).

## Cost-control feature flags (Part 1 — all default FALSE; add if missing)
`ENABLE_CLOUDFRONT`, `ENABLE_STEP_FUNCTIONS`, `ENABLE_ATHENA_ANALYTICS`,
`ENABLE_GLUE`, `ENABLE_TEXTRACT_IMPORT`, `ENABLE_BEDROCK_ASSIST`, `ENABLE_XRAY`,
`ENABLE_ADVANCED_CLOUDWATCH_DASHBOARD`, `ENABLE_RAW_WEBHOOK_ARCHIVE`.

Action: verify `amplify/backend-resources.ts` for existing WAF/SQS/CloudWatch usage; wrap any
optional paid resource creation behind these flags; keep local build independent of paid services.
Currently in use (cost-relevant, keep): DynamoDB (PAY_PER_REQUEST), Lambda, S3, SQS/DLQ, Cognito,
CloudWatch logs. No Athena/Glue/Step Functions/Textract/Bedrock/X-Ray should be enabled without a flag.

## Recommended implementation order (summary)
1. Shared Meta client → 2. Webhook dedup → 3. Inbound hardening → 4. Outbound hardening →
5. Business-API per-endpoint hardening (M3) → 6. WABA mgmt → 8. Templates + Flows (with tests) →
9. Scheduling/DLQ → 10–12. Calling/Voice/Catalog → 18–19. Attribution/Analytics → Frontend UX →
AWS/cost/testing/docs.

## Compliance with Part 1 rules
✅ Amplify Gen 2, Python Lambdas, DynamoDB/AppSync, Cognito, S3 preserved · ✅ no NestJS/Prisma/
PostgreSQL proposed · ✅ no tokens to frontend · ✅ no Meta calls from frontend · ✅ cost flags
default false · ✅ existing models reused (no duplicates proposed). Scan-only: **no business logic changed.**
