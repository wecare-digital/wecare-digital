# Backend operations cleanup (2026-11-02)

This is a **reviewable operations change**, not a deployment. Production remains on `wecare.digital` (verify GitHub and Amplify settings before every release). Older runbooks naming `stack` as the production branch are stale and must not be used as release authority.

## Meta Commerce catalog retirement

User confirmed that Meta/WhatsApp **Commerce catalog synchronization** is no longer needed. Do **not** confuse it with WhatsApp Business messaging, message templates, conversation metadata, customer orders, native product catalog, or checkout.

In AWS, both retired scheduled sync rules and their targets were deleted on 2026-11-02 after verifying they targeted only Meta catalog sync. A follow-up full event-source inventory found **two still-enabled DynamoDB stream mappings** on the alias-qualified `live` and `waba2` functions. Both mappings were disabled on 2026-11-02 and **verified Disabled**. The ProductsTable and its stream are unchanged. The sync's drift/failure alarms had already been removed. The Lambda and aliases remain with reserved concurrency **0**. The active WhatsApp Business API still contains an admin proxy and there are residual deployment/IAM references; coordinate their removal in a separate backend release before deleting the function. Do not change concurrency without explicit release approval. No product or customer records were changed.

The route-free API Gateway integration for the retired AI generation function was also deleted, with absence verified afterward. The AI Lambda remains blocked at concurrency **0**. The inbound handler still contains unused invocation helpers; remove those and complete rollback/deployment review before deleting it. Neither Lambda was invoked to test this cleanup.

### Dependency review required before code removal

The retired Meta provisioning, WABA2 schedule, write-gate and alias-promotion operator scripts have been removed from the active repository (recoverable from Git history). The uncalled CDK `addCatalogStreamTrigger` builder was also removed; the native `addCatalogResources` declaration is retained. Check active references to `wecare-meta-catalog-sync`, `META_CATALOG_SYNC_*`, `meta_catalog_sync`, `META_CATALOG_ID`, and `generate_shop_listings.py`. A scheduled-rule check alone is insufficient: always enumerate **alias-qualified** Lambda event-source mappings. Do not delete `ProductsTable`, native catalog handlers, `wecare-catalog-media`, or WhatsApp messaging APIs.

Before deleting the remaining Meta sync Lambda and runtime modules: prove no **enabled** event-source mapping, EventBridge target, API route, direct invocation, workflow, UI link, CI test, or stack dependency requires them. Review the remaining WhatsApp Business admin proxy and IAM invoke grants, test native checkout/WhatsApp flows, and retire the Lambda only in a separate reviewed production release. Disabled mappings are deliberately preserved for rollback until this review is complete.

## Fresh production inventory (2026-11-02)

The `us-east-1` audit enumerated **78 Lambda functions, 83 DynamoDB tables, seven HTTP APIs, 378 primary API routes, 75 fully routed primary API integrations and eight SQS queues**. No orphan integration remained in the primary API. The five recovery-named DynamoDB tables contain data and lack PITR and deletion protection: retain them until a written recovery/backup decision, not a filename-based deletion. The one Lambda with zero 30-day invocations still has a configured API route. The notification-worker SQS mapping is disabled, but its queue was empty at inspection; investigate delivery architecture before enabling it.

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
