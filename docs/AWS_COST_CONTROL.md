# AWS Cost Control

How WECARE.DIGITAL keeps the Amplify Gen 2 backend cheap and predictable. Optional
paid services are **off by default** and gated behind feature flags read by
`amplify/functions/shared/lambda_utils/cost_flags.py` (`is_enabled()` / `all_flags()`).

## Current resources in the repo

| Resource | Where | Required? | Cost risk | Notes |
|---|---|---|---|---|
| Lambda (Python) | `amplify/functions/**` | Required | Low | Pay-per-invoke |
| DynamoDB tables | `amplify/data/resource.ts` | Required | Low | `PAY_PER_REQUEST` (on-demand) |
| AppSync / Data | `amplify/data/resource.ts` | Required | Low | userPool auth |
| Cognito | `amplify/auth/resource.ts` | Required | Low | Admin auth |
| S3 | `amplify/storage/resource.ts` (`wecare-digital-get`) | Required | Low | Media + assets; add lifecycle rules |
| SQS / DLQ | `amplify/backend-resources.ts` | Required where present | Low | Inbound/outbound/bulk DLQs |
| CloudWatch Logs | `backend-resources.ts` | Required | Low | 3-month retention |
| CloudWatch Alarms (critical) | `backend-resources.ts` | Required | Low | Errors on critical Lambdas |

## Optional resources — feature flags

Each is disabled unless its env flag is `true` (see `cost_flags.py`).

| Flag | Service | Cost risk | Enable when | Disable / safer alternative |
|---|---|---|---|---|
| `ENABLE_CLOUDFRONT` | CloudFront | Medium | Global static caching needed | Serve via Amplify hosting / S3 directly |
| `ENABLE_STEP_FUNCTIONS` | Step Functions | Medium | Long multi-step orchestration | Chained Lambda + DynamoDB state |
| `ENABLE_ATHENA_ANALYTICS` | Athena | High | Ad-hoc SQL over large logs | Pre-aggregate in DynamoDB / CloudWatch |
| `ENABLE_GLUE` | Glue | High | ETL catalog needed | CSV import scripts |
| `ENABLE_TEXTRACT_IMPORT` | Textract | High | OCR of pricing PDFs | **CSV import first** |
| `ENABLE_BEDROCK_ASSIST` | Bedrock | High | AI assist explicitly wanted | Keep disabled; never send PII |
| `ENABLE_XRAY` | X-Ray | Medium | Deep tracing during incident | CloudWatch logs + structured logging |
| `ENABLE_ADVANCED_CLOUDWATCH_DASHBOARD` | CW dashboards / metric filters | Medium | Ops review period | Basic alarms only |
| `ENABLE_RAW_WEBHOOK_ARCHIVE` | S3 raw payload archive | Medium | Debugging webhook issues | Masked metadata logs only |

## WAF (removed 2026-09-28)

WAF is gone from this account. Owner decision, taken as a cost decision.

- **What was deleted:** `wecare-cognito-waf` (REGIONAL, both Cognito pools) and
  `wecare-amplify-waf` (CLOUDFRONT, Amplify app `d22dm4b0jn71jw`). The
  `ENABLE_WAF`-gated `WebhookWAF` declaration was also removed from
  `backend-resources.ts`; it had never been switched on, so deleting it changed
  nothing live.
- **Saving, stated honestly:** roughly $18/month at list price, but **$0.00 realised
  today** because credits absorb it. The saving arrives only if credits lapse.
- **What replaced it:** nothing at the edge. Request filtering is now entirely
  application-side — `require_auth`, provider HMAC verification,
  `lambda_utils/rate_limit.py`, the per-phone OTP probe counter, and API Gateway
  stage/route throttling. Public customer OTP sign-in has **no per-IP protection**
  any more.
- **Restore:** `python3 scripts/provision_waf.py --apply`. That script is retained
  precisely so this is one command. Prior state is in
  `docs/execution/snapshots/waf-associations-before-delete-20260928.json`.
- **Do not re-add a web ACL in CDK.** If WAF comes back it comes back through
  `provision_waf.py`, so the two ACLs keep their deliberately different postures.

## Standing cost notes

- **DynamoDB:** all tables use `PAY_PER_REQUEST`; no provisioned capacity.
- **CloudWatch retention:** log groups default to 3 months; do not raise without reason.
- **S3 lifecycle:** add expiry rules for `secure/d/public/whatsapp/downloads/` and
  `secure/d/public/whatsapp/resumable/` staging keys; raw archives (if ever enabled) must have lifecycle + encryption.
- **Bedrock / Textract / Athena:** highest cost; keep disabled. Never send PII to
  Bedrock; add redaction before enabling.

## When to enable / disable
Enable a paid resource only for a defined need and time window; disable immediately
after. The UI Cost Controls page surfaces `all_flags()` and warns before enabling.
