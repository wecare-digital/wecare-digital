# Backend operations cleanup (2026-11-02)

This is a **reviewable operations change**, not a deployment. Production remains on `wecare.digital` (verify GitHub and Amplify settings before every release). Older runbooks naming `stack` as the production branch are stale and must not be used as release authority.

## Meta Commerce catalog retirement

User confirmed that Meta/WhatsApp **Commerce catalog synchronization** is no longer needed. Do **not** confuse it with WhatsApp Business messaging, message templates, conversation metadata, customer orders, native product catalog, or checkout.

The retired AI generation and Meta Commerce sync Lambdas, all their versions/aliases, the dedicated Meta sync role and its inline policy are deleted. Private KMS-encrypted rollback code/configuration and IAM snapshots were verified first. The shared role no longer grants invocation of either retired function.

Both old Meta schedules, both disabled ProductsTable stream mappings, both `/wa-business/catalog-sync` HTTP routes, and the orphan AI API integration are deleted. The native ProductsTable and its stream remain. The updated inbound and business API handlers are published on their `live` aliases after non-sending signature/retirement smoke checks.

Five unreferenced recovery tables from 2026-10-30 were removed only after dedicated DynamoDB backups reached AVAILABLE and current/live-alias consumers plus CloudFormation ownership were checked. The original Products, SEO and SystemConfig tables remain active. No customer/product rows were edited by this retirement.

The shared `lambda_utils/ecommerce/meta_catalog_sync.py` helper remains because native basket parsing, checkout analytics and website catalog generation use its retailer-ID and projection contracts. Removing that shared module would break active consumers.

The latest function inventory contains 76 Lambdas and 78 DynamoDB tables in us-east-1. Recent direct invocations and current release/rollback dependencies justify retaining checkout, invoice and catalog functions that have no HTTP route. Keep Cognito triggers, CloudFront edge handlers and scheduled/queue workers even when they have no HTTP integration. Private inventory outputs must not be committed to this public repository.

## Security

The shared Lambda execution role is used by 54 functions. Review 16 inline policies and six attached policies with IAM Access Analyzer, CloudTrail access evidence and source-code based policy generation. Do not blindly remove shared permissions or create incomplete least-privilege roles. The connected AWS API reports a root identity; validate connector credentials and the production deployment role independently before any IAM change.

## CloudWatch / logging

Historical CloudWatch logs were previously deleted at user request, including their log-based metric filters. Reconstructed essential API and selected payment/auth/WhatsApp log groups have 3, 7, or 14-day retention. Existing alarms may still depend on absent log-based custom metrics. Fourteen critical payment, Vault, WhatsApp and Flow-health metric filters were restored in live AWS on 2026-11-02. End-to-end notification delivery still needs a non-customer-impacting test; do not assume all retained alarms are healthy just because alarm definitions exist.

`scripts/ops/enforce_log_retention.py` is **dry-run by default**; use a scheduled scoped role or automation after reviewing its permissions. A least-privilege daily retention scheduler was deployed separately through CloudFormation stack `wecare-cloudwatch-retention-enforcer` on 2026-11-02. Its stack reached CREATE_COMPLETE and its EventBridge rule is enabled. It only fills missing retention and never overrides existing policies; its first live invocation test remains unverified because the AWS connector hit its session limit.

## Private inventory

The application GitHub repository is public. Full API/ARN/IAM snapshots must **never** be committed to it. Generate inventory locally with `scripts/ops/generate_backend_registry.py --expected-account <ACCOUNT_ID>`, redirect output into a restricted, encrypted location, and assign missing source paths, deploy owners, and DynamoDB consumers through code review. The scripts are version-controlled; the sensitive output is not.

## Release standards

Preserve the `live` Lambda aliases, canary checks, rollback capture, payment gates, and Amplify frontend-only builds. Do not run Gen2 backend pipeline deployment over existing manually maintained resources. Classify each resource as CDK/CloudFormation or script-managed before changing its deployment pipeline.

## Cost and analytics

October 2026 Cost Explorer unblended usage plus support was roughly $164 before approximately $164 in credits. Amplify had the largest usage cost. Credits are an offset, not evidence that services have no underlying cost. Review build frequency and failures before changing hosting.

An Athena workgroup named `wecare-analytics-governed` was provisioned with a 1 GiB query scan cutoff and enforced settings. The legacy `primary` workgroup was not modified; migrate analytics callers deliberately. Athena callers still need appropriate query result location permissions.

## Safety and acceptance

Do not apply this PR as evidence that all four phases are complete. Acceptance requires: no live Meta sync targets; API access logs flowing; payment/auth/WhatsApp critical notifications tested; IAM access review approved; registry owners assigned; release CI passes; Athena and bill reconciliation documented; no product or customer records changed.
