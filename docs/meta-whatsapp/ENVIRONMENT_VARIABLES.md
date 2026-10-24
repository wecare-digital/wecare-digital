# WhatsApp Environment Variables

Authoritative list also mirrored in `.env.local.example`. Secret values are NOT stored in env in production — they live in AWS Secrets Manager and are fetched at runtime by the Lambdas.

| Var | Where | Notes |
|-----|-------|-------|
| `META_GRAPH_API_VERSION` | Lambda env | `v25.0` (matches `META_API_VERSION` in handlers) |
| `WA_ACCESS_TOKEN` | Secrets Manager `wecare/meta-system-user-token.access_token` | System user token |
| `WA_APP_SECRET` | Secrets Manager (`app_secret`) | `appsecret_proof` + signature |
| `WA_VERIFY_TOKEN` | AWS End User Messaging | webhook GET verify (managed) |
| `WA_BUSINESS_ID` | config | Meta portfolio id |
| `WA_WABA_ID` | config | WABA 1 `2094615664435155`, WABA 2 `2513394156072604` |
| `WA_PHONE_NUMBER_ID` | config | WABA 1 `1016149501586345`, WABA 2 `1055232054343117` |
| `WA_CATALOG_ID` | config | only if catalog messages enabled |
| `WA_DEFAULT_LANGUAGE` | config | `en_US` (note: live templates use `en`) |
| `WA_LIVE_SMOKE_TEST` | env | gate for live sends, default `false` |
| `WA_QA_RECIPIENT` | env | QA-only recipient |
| `WA_FLOWS_ENABLED` | flag | default `true` |
| `WA_PAYMENTS_ENABLED` | flag | default `false` (Meta-gated) |
| `WA_MARKETING_MESSAGES_ENABLED` | flag | default `false` |
| `WA_CALLING_ENABLED` | flag | default `false` (Meta-gated) |
| `WA_GROUPS_ENABLED` | flag | default `false` (Meta-gated) |
| `WA_MEDIA_BUCKET` | env | `wecare-digital-get` |
| `WA_WEBHOOK_QUEUE_URL` | env | SQS inbound (if used) |
| `WA_WEBHOOK_DLQ_URL` | env | `stack-wecare-digital-inbound-dlq` |

## Secrets Manager (verified present, values not exposed)
- `wecare/meta-system-user-token` — last accessed today (live)
- `wecare/meta-app-secret`
- `wecare/flow-private-key` — Flow RSA key
