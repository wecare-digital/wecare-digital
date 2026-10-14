# Secrets access matrix

Generated 2026-10-14T23:54:02Z by `scripts/secrets_access_matrix.py` from live metadata only (ListSecrets, IAM policy documents, Lambda configuration). No secret value was read.

Active: **19**. Scheduled for deletion: **9** (not billed; not counted as new savings).

IAM readers = roles whose policies allow `secretsmanager:GetSecretValue` on a pattern matching the secret ARN. A Lambda consumer is a function running under such a role.

| Secret | Domain | Action | IAM reader roles | Lambda consumers | Last access | KMS | Rationale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wecare/agent-connector-token` | integrations | NEEDS_OWNER_REVIEW | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 1) | 2026-10-06 | aws/secretsmanager | identify the consumer before any action |
| `wecare/aws/iam-access-keys` | security | NEEDS_OWNER_REVIEW | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 0) | 2026-10-06 | aws/secretsmanager | stored long-lived AWS keys; replace with role-based temporary credentials, then retire |
| `wecare/backup/recovery-passphrase` | security | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 0) | 2026-10-06 | aws/secretsmanager | disaster-recovery passphrase |
| `wecare/bing/api` | seo | NEEDS_OWNER_REVIEW | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 1) | 2026-10-06 | CMK 9b5b8734 | confirm an active consumer exists |
| `wecare/config/webhook-registry` | integrations | NEEDS_OWNER_REVIEW | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 0) | 2026-10-06 | aws/secretsmanager | MOVE_TO_PARAMETER_STORE only if the owner confirms no field is secret |
| `wecare/flow-private-key` | security | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 1) | 2026-10-08 | aws/secretsmanager | WhatsApp Flows RSA private key |
| `wecare/github-pat` | security | ROTATE | wecare-digital-lambda-role, wecare-workspace-mcp-runtime | 61 functions via wecare-digital-lambda-role; wecare-workspace-mcp (source files in amplify/functions: 1) | 2026-10-13 | aws/secretsmanager | classic near-full-scope PAT, description says EXPOSED 2026-08-25; replace with a fine-grained token or GitHub App |
| `wecare/google/ads` | integrations | KEEP_ISOLATED | wecare-digital-lambda-role, wecare-workspace-mcp-runtime | 61 functions via wecare-digital-lambda-role; wecare-workspace-mcp (source files in amplify/functions: 3) | 2026-10-07 | CMK 9b5b8734 | Google Ads credentials |
| `wecare/google/cloud` | integrations | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 4) | 2026-10-14 | CMK 9b5b8734 | GCP service-account key |
| `wecare/meta-system-user-token` | integrations/meta | KEEP_ISOLATED | wecare-digital-lambda-role, wecare-meta-catalog-sync-role, wecare-workspace-mcp-runtime | 61 functions via wecare-digital-lambda-role; wecare-meta-catalog-sync; wecare-workspace-mcp (source files in amplify/functions: 23) | 2026-10-14 | aws/secretsmanager | Graph system-user token and app secret |
| `wecare/meta/payments` | payments | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 0) | 2026-10-06 | aws/secretsmanager | payment configuration; owner to confirm which fields are secret |
| `wecare/otp/pepper` | security | KEEP_ISOLATED | wecare-customer-profile-role, wecare-digital-lambda-role, wecare-email-verification-role | wecare-customer-profile; 61 functions via wecare-digital-lambda-role; wecare-email-verification (source files in amplify/functions: 4) | 2026-10-06 | aws/secretsmanager | OTP hashing pepper |
| `wecare/plivo-answer` | communications | NEEDS_OWNER_REVIEW | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 1) | 2026-10-06 | aws/secretsmanager | same provider as plivo/api; group only if every reader needs both and rotation matches |
| `wecare/plivo/api` | communications | KEEP_ISOLATED | GitHubActions-wecare-digital-plivo-drift, wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 2) | 2026-10-14 | CMK 9b5b8734 | voice provider API credentials |
| `wecare/razorpay-webhook` | payments | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 5) | 2026-10-10 | aws/secretsmanager | webhook signature verification secret |
| `wecare/razorpay/api` | payments | KEEP_ISOLATED | wecare-checkout-role, wecare-digital-lambda-role, wecare-secure-files-role, wecare-workspace-mcp-runtime | wecare-checkout; 61 functions via wecare-digital-lambda-role; wecare-secure-files; wecare-workspace-mcp (source files in amplify/functions: 7) | 2026-10-14 | aws/secretsmanager | payment gateway API credentials |
| `wecare/seo/google-oauth` | seo | KEEP_ISOLATED | wecare-digital-lambda-role, wecare-workspace-mcp-runtime | 61 functions via wecare-digital-lambda-role; wecare-workspace-mcp (source files in amplify/functions: 3) | 2026-10-07 | aws/secretsmanager | Google OAuth client |
| `wecare/sinch/rcs` | communications | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 3) | 2026-10-14 | aws/secretsmanager | RCS provider credentials |
| `wecare/truecaller` | communications | KEEP_ISOLATED | wecare-digital-lambda-role | 61 functions via wecare-digital-lambda-role (source files in amplify/functions: 1) | 2026-10-06 | aws/secretsmanager | identity callback credentials |

## Scheduled for deletion

| Secret | Deletion requested | IAM readers |
| --- | --- | --- |
| `wecare/ads/account-registry` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/github-connection` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/google-api-key` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/google-maps` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/google-maps-server` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/integrations/owner-input-20261001` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/openai/api` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/plivo` | 2026-10-07 | wecare-digital-lambda-role |
| `wecare/sinch/sms` | 2026-09-20 | wecare-digital-lambda-role |

## Source references (by-reference names, no values)

- `wecare/agent-connector-token`: `amplify/functions/messaging/meta-business-agent/handler.py`, `scripts/secrets_backup.py`
- `wecare/aws/iam-access-keys`: `scripts/audit_secrets_structure.py`, `scripts/sync_webhook_registry.py`
- `wecare/backup/recovery-passphrase`: `scripts/secrets_backup.py`
- `wecare/bing/api`: `amplify/functions/shared/lambda_utils/integrations/registry.py`
- `wecare/config/webhook-registry`: `scripts/sync_webhook_registry.py`
- `wecare/flow-private-key`: `wecare-whatsapp-business-api.FLOW_PRIVATE_KEY_SECRET`, `amplify/functions/messaging/whatsapp-business-api/handler.py`, `scripts/secrets_backup.py`
- `wecare/github-pat`: `amplify/functions/ai/workspace-mcp/handler.py`, `scripts/google-cloud-setup.sh`, `scripts/provision_wix_catalog_webhook.py`
- `wecare/google/ads`: `amplify/functions/ai/workspace-mcp/handler.py`, `amplify/functions/ai/workspace-mcp/provider_adapters.py`, `amplify/functions/shared/lambda_utils/integrations/registry.py`, `scripts/check_secrets_live.py`, `scripts/google_products_pull.py`, `scripts/store_provider_secret.py`
- `wecare/google/cloud`: `wecare-site-language.SITE_LANGUAGE_GOOGLE_SECRET`, `.github/workflows/build-test.yml`, `amplify/functions/core/site-language/handler.py`, `amplify/functions/core/vayulok-environment/handler.py`, `amplify/functions/core/vayulok-environment/resource.ts`, `amplify/functions/messaging/whatsapp-templates/handler.py`, `scripts/audit_secrets_structure.py`, `scripts/check_secrets_live.py`, `scripts/deploy_site_language.py`, `scripts/provision_maps_server_key.py`, `scripts/provision_vayulok_environment.py`, `scripts/store_provider_secret.py` (+1 more)
- `wecare/meta-system-user-token`: `wecare-marketing-ads.META_TOKEN_SECRET`, `wecare-meta-catalog-sync.META_TOKEN_SECRET`, `wecare-partner-onboarding.META_TOKEN_SECRET`, `wecare-partner-token-refresh.META_TOKEN_SECRET`, `wecare-whatsapp-business-api.META_TOKEN_SECRET`, `wecare-whatsapp-calling.META_TOKEN_SECRET`, `amplify/functions/ai/ai-generate-response/handler.py`, `amplify/functions/ai/workspace-mcp/handler.py`, `amplify/functions/ecommerce/catalog-management/handler.py`, `amplify/functions/ecommerce/catalog-management/resource.ts`, `amplify/functions/ecommerce/meta-catalog-sync/handler.py`, `amplify/functions/messaging/inbound-whatsapp-handler/handler.py` (+24 more)
- `wecare/otp/pepper`: `wecare-customer-profile.OTP_PEPPER_SECRET_ID`, `wecare-email-verification.OTP_PEPPER_SECRET_ID`, `amplify/functions/auth/blog-subscribe/handler.py`, `amplify/functions/auth/customer-profile/handler.py`, `amplify/functions/auth/customer-registration/handler.py`, `amplify/functions/auth/email-verification/handler.py`, `scripts/provision_blog_subscribe.py`, `scripts/provision_customer_profile.py`, `scripts/provision_customer_registration.py`, `scripts/provision_email_verification.py`
- `wecare/plivo-answer`: `amplify/functions/messaging/plivo-answer/handler.py`, `scripts/check_secrets_live.py`, `scripts/export_provider_credentials.py`, `scripts/provision_ci_plivo_drift_role.py`, `scripts/store_provider_secret.py`, `scripts/test_call_paths.py`
- `wecare/plivo/api`: `wecare-pstn-softphone.PLIVO_API_SECRET_ID`, `amplify/functions/messaging/plivo-answer/handler.py`, `amplify/functions/messaging/pstn-softphone/handler.py`, `scripts/audit_secrets_structure.py`, `scripts/check_secrets_live.py`, `scripts/export_provider_credentials.py`, `scripts/plivo-reconcile`, `scripts/plivo_control_plane.py`, `scripts/provision_ci_plivo_drift_role.py`, `scripts/provision_pstn_softphone.py`, `scripts/refresh_secret_consumers.py`, `scripts/secrets_backup.py` (+4 more)
- `wecare/razorpay-webhook`: `amplify/functions/core/secure-files/razorpay_orders.py`, `amplify/functions/messaging/partner-onboarding/handler.py`, `amplify/functions/payments/razorpay-webhook/handler.py`, `amplify/functions/shared/lambda_utils/integrations/razorpay_orders.py`, `amplify/functions/shared/lambda_utils/integrations/razorpay_verify.py`, `scripts/audit_secrets_structure.py`, `scripts/block_catastrophic.py`, `scripts/check_secrets_live.py`, `scripts/google-cloud-setup.sh`, `scripts/maintenance_report.py`, `scripts/provision_secure_files_api.py`, `scripts/razorpay_add_webhook_events.py` (+7 more)
- `wecare/razorpay/api`: `wecare-checkout.RAZORPAY_SECRET_ID`, `wecare-secure-files.RAZORPAY_SECRET_ID`, `amplify/functions/ai/workspace-mcp/handler.py`, `amplify/functions/ai/workspace-mcp/provider_adapters.py`, `amplify/functions/core/secure-files/razorpay_orders.py`, `amplify/functions/messaging/partner-onboarding/handler.py`, `amplify/functions/shared/lambda_utils/ecommerce/website_checkout.py`, `amplify/functions/shared/lambda_utils/integrations/razorpay_orders.py`, `amplify/functions/shared/lambda_utils/integrations/razorpay_verify.py`, `scripts/audit_secrets_structure.py`, `scripts/block_inline_secrets.py`, `scripts/check_secrets_live.py` (+10 more)
- `wecare/seo/google-oauth`: `amplify/functions/ai/workspace-mcp/handler.py`, `amplify/functions/shared/lambda_utils/identity/__init__.py`, `amplify/functions/shared/lambda_utils/integrations/registry.py`, `scripts/check_secrets_live.py`, `scripts/google-cloud-setup.sh`, `scripts/search_console_sitemap.py`, `scripts/store_provider_secret.py`
- `wecare/sinch/rcs`: `wecare-rcs-send.RCS_SECRET_NAME`, `amplify/functions/messaging/rcs-dlr/handler.py`, `amplify/functions/messaging/rcs-send/handler.py`, `amplify/functions/shared/lambda_utils/sinch_rcs.py`, `scripts/check-provider-policy.sh`, `scripts/check_secret_fields_present.py`, `scripts/export_provider_credentials.py`, `scripts/rcs_webhook_control_plane.py`
- `wecare/truecaller`: `amplify/functions/shared/lambda_utils/identity/__init__.py`, `scripts/store_provider_secret.py`
