# WhatsApp Security Checklist

| Control | Status | Notes |
|---------|--------|-------|
| Webhook GET verify | ✅ ours, fails closed | `whatsapp-calling/_verify_webhook` compares `hub.verify_token` with `hmac.compare_digest` and returns 403 when no token is available. **Not AWS-managed** — this row claimed it was until 2026-09-21; there is no linked WABA and no SNS ingress |
| Webhook X-Hub signature | ✅ ours, fails closed | All three call sites now delegate to `lambda_utils/meta_signature`, which tries both WABA app secrets and never fails open. `POST /whatsapp/inbound` enforces it since 2026-09-21; before that it accepted unsigned webhooks, partly because this checklist said signature checking was somebody else's job. `whatsapp-business-api` kept a local copy that returned **True** when no app secret was configured until 2026-09-21 — nothing called it, but this row cited it as evidence |
| Status webhook ordering | ✅ | `lambda_utils/wa_status` ranks the lifecycle and the DynamoDB write is guarded by a ConditionExpression, so a late `sent` cannot overwrite `read` |
| Webhook replay window | ✅ fails closed | Entries older than 300s rejected. Until 2026-09-21 the parser wrapped the whole traversal in one `except (ValueError, TypeError): pass`, so corrupting the timestamp field defeated the window entirely and a malformed value also aborted the traversal before a genuinely stale entry was examined. Each timestamp is now judged independently: absent is allowed, unreadable and far-future are rejected |
| `appsecret_proof` on Graph calls | ✅ | Computed HMAC-SHA256(token, app_secret) in outbound/inbound handlers |
| Secrets in Secrets Manager (not code) | ✅ | `wecare/meta-system-user-token`, `wecare/meta-app-secret`, `wecare/flow-private-key` |
| Secret values never logged | ✅ | Handlers log message ids/types, not tokens |
| Admin API auth | ✅ (app-layer) | `require_auth` (Cognito JWT + role) enforced in handlers; `wecare.digital/api` returns 401 without token |
| API Gateway authorizer | ⚠️ REVIEW | All 326 routes are `AuthorizationType=NONE` at the gateway; auth is enforced in-handler via `require_auth`. That single layer is why two separate in-handler gaps became directly internet-reachable (32 open routes, then `AUTH_SKIP_PATHS`). A gateway JWT authorizer would have contained both |
| CORS | ⚠️ REVIEW | Gateway `AllowOrigins: *`; handlers echo specific origin. Tighten gateway to known origins |
| Idempotency / dup webhooks | ⚠️ PARTIAL | dedup + DLQ + timeout-guard present; add explicit message-id dedup table if duplicates observed |
| Flow payload encryption | ✅ | RSA private key in `wecare/flow-private-key` |
| Media objects private | ✅ gated at the edge since 2026-10-25 | WhatsApp customer media (`secure/d/public/whatsapp/` `incoming/`, `outgoing/`, `voice/`, `transcriptions/`, `downloads/`, `calling-ai/`, `resumable/`), invoices and receipts are redirected by `wecare-get-miss-redirect` like the rest of `secure/`; readers get presigned URLs. List: `media_paths.PRIVATE_DELIVERABLE_PREFIXES`, edge copy checked by `verify_media_prefixes.py` |
| `AUTH_SKIP_PATHS` scope | ✅ narrowed 2026-09-21 | Only `/wa-business/flow-data` is exempt, and it self-authenticates by RSA decryption. `/wa-business/webhooks` was also exempt — it is not a Meta callback but the management surface for `subscribed_apps`, where `DELETE` stops all inbound delivery and `POST` forwards `override_callback_uri`. Matching is now exact-or-child-segment, not substring |
| Live-send gating | ✅ implemented, held off | `lambda_utils/live_smoke` enforces `WA_LIVE_SMOKE_TEST` + `WA_QA_RECIPIENT`. It is a **lockdown**: off changes nothing, on refuses every recipient but the QA number. Both vars are absent in production (measured on `wecare-outbound-whatsapp:19`) |

## Action items
1. Add Cognito JWT authorizer to non-webhook HTTP API routes (defense in depth).
2. Restrict gateway CORS from `*` to app origins.
3. Confirm S3 `public-access-block` + lifecycle on `wecare-digital-get`.
