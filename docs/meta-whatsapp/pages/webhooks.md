# Build Spec — Webhooks

Meta refs: /webhooks/overview, /webhooks/reference/messages

## Architecture (this repo)

Corrected 2026-09-21. This page previously described

> Meta → AWS End User Messaging (Social/WhatsApp) → SNS topic → `wecare-inbound-whatsapp`

with GET verification and `X-Hub-Signature-256` "handled by the AWS-managed
integration". **That is not the architecture and has not been for some time.** The
AWS account has no linked WABA, there is no SNS topic subscription to
`wecare-inbound-whatsapp` in `amplify/backend.ts`, `amplify/backend-resources.ts`
or the live event-source mappings, and verification is entirely ours. Believing
this page would lead an auditor to assume signature checking was somebody else's
job — which is precisely how `POST /whatsapp/inbound` ended up accepting unsigned
webhooks.

The actual path:

```text
Meta  →  POST https://wecare.digital/api/whatsapp
      →  API Gateway zllr9lrg7j (stage `prod`; the stage appears in the path and
         is normalized by lambda_utils/http_path.normalize_path)
      →  wecare-whatsapp-calling:live          the canonical public ingress
           · GET  = hub.challenge / hub.verify_token, fails closed with 403 when
             no verify token is available
           · POST = raw-body X-Hub-Signature-256 against BOTH WABA app secrets,
             fails closed; 401 on mismatch
           · replay guard rejects entries older than 300s
           · field == 'calls'  → handled locally, Meta SIP → Asterisk
           · everything else   → forwarded to the inbound worker
      →  wecare-inbound-whatsapp:live          async lambda invoke, typed event
           · see lambda_utils/wa_internal_event for the contract
           · messages, statuses, template/account/quality/user events
```

`POST /whatsapp/inbound` also routes to the worker. It is **not** the production
path — the ingress reaches the worker by direct invoke — and since 2026-09-21 it
requires a valid `X-Hub-Signature-256` of its own.

## Handled webhook fields (inbound handler)
messages, statuses, message_template_status_update, phone_number_quality_update, account_update, user_id_update (BSUID), business_username_update, user_preferences, group_* events.

## Resilience
dedup, timeout-guard (re-queues remaining messages to DLQ), per-message try/except, DLQ `stack-wecare-digital-inbound-dlq`.

## Status
Built/present. Idempotency: PARTIAL_FIXED (add explicit message-id dedup table if duplicates seen). Live re-test pending QA inbound.
