# AWS account inventory

Generated 2026-10-08T16:37:10.589782+00:00 · account `775261844268` · `us-east-1` (+ ap-south-1) · regenerate with `python scripts/aws_account_inventory.py`

This is a dated inventory snapshot, not a statement of current deployment state. Subsequent changes must be verified live. A readback on 2026-10-09 confirmed 30-day retention on `/aws/lambda/wecare-customer-profile` and `/aws/lambda/wecare-customer-session`; the snapshot below predates that change. Machine-readable companion: `aws-inventory.json`. Secret **names** and metadata are recorded; no secret value is ever read. Lambda environment variable **names** are recorded, values never are.

Collector errors: **0** (a non-zero count makes this inventory PARTIAL, not authoritative).

## Headline counts

| Resource | Count |
|---|---:|
| Lambda functions | 76 |
| — with a `live` alias | 69 |
| HTTP APIs | 1 |
| REST APIs | 0 |
| HTTP API routes | 384 |
| API authorizers | 1 |
| Routes with AuthorizationType=NONE | 382 |
| DynamoDB tables | 85 |
| SQS queues | 10 |
| EventBridge rules | 7 |
| EventBridge Scheduler schedules | 1 |
| Secrets Manager secrets | 35 |
| — scheduled for deletion | 13 |
| Cognito user pools | 2 |
| S3 buckets | 7 |
| CloudFront distributions | 3 |
| WAF web ACLs (regional) | 0 |
| WAF web ACLs (CloudFront) | 0 |
| Route 53 hosted zones | 1 |
| CloudWatch alarms | 73 |
| CloudWatch log groups | 92 |
| CloudFormation stacks | 4 |
| Amplify apps | 1 |

## Lambda

Runtimes: {'python3.12': 75, None: 1}  ·  package types: {'Zip': 75, 'Image': 1}

SnapStart: {'None': 76}

Alias read errors: 0

**Without a `live` alias (7)** — `$LATEST` reaches production directly for these:

- `wecare-ad-attribution`
- `wecare-docs-scraper`
- `wecare-get-miss-redirect`
- `wecare-partner-token-refresh`
- `wecare-seo-tools`
- `wecare-sla-engine`
- `wecare-url-shortener`

## API Gateway

- **zllr9lrg7j** `wecare-digital-api` — 384 routes, 1 authorizers, stages: ['prod']
  - authorizer `workspace-mcp-staff` (JWT) ['$request.header.Authorization']

Routes with non-`NONE` authorization: **2** (one JWT authorizer and one AWS IAM route)

- `ANY /workspace/mcp` — JWT
- `POST /workspace/mcp-iam` — AWS_IAM

## DynamoDB

Empty tables (58): `stack-wecare-digital-AIInteractionsTable`, `stack-wecare-digital-AIProviderPolicyTable`, `stack-wecare-digital-AdClickAttributionTable`, `stack-wecare-digital-AgentApprovalsTable`, `stack-wecare-digital-AmendmentHistoryTable`, `stack-wecare-digital-AppointmentTable`, `stack-wecare-digital-AutomationRulesTable`, `stack-wecare-digital-BulkJobsTable`, `stack-wecare-digital-BulkRecipientsTable`, `stack-wecare-digital-CallNotificationsTable`, `stack-wecare-digital-CatalogCacheTable`, `stack-wecare-digital-ConversationHistoryTable`, `stack-wecare-digital-ConversationMetaTable`, `stack-wecare-digital-CouponsTable`, `stack-wecare-digital-CrmActivities`, `stack-wecare-digital-CrmLeads`, `stack-wecare-digital-CrmOpportunities`, `stack-wecare-digital-CrmPipelines`, `stack-wecare-digital-CrmStages`, `stack-wecare-digital-DLQMessagesTable`, `stack-wecare-digital-DLTTemplates`, `stack-wecare-digital-DocumentHistoryTable`, `stack-wecare-digital-DownloadGrantsTable`, `stack-wecare-digital-EnterpriseAssistTable`, `stack-wecare-digital-FaqTable`, `stack-wecare-digital-FlowDraftTable`, `stack-wecare-digital-FlowLogTable`, `stack-wecare-digital-InvoiceAssetsTable`, `stack-wecare-digital-InvoiceDeliveryLogTable`, `stack-wecare-digital-NotificationAttempts`, `stack-wecare-digital-NotificationDeliveries`, `stack-wecare-digital-NotificationEvents`, `stack-wecare-digital-NotificationOutbox`, `stack-wecare-digital-OBDCampaigns`, `stack-wecare-digital-OrderTable`, `stack-wecare-digital-PartnerLedger`, `stack-wecare-digital-PartnerWallet`, `stack-wecare-digital-PaymentAttemptsTable`, `stack-wecare-digital-PstnSoftphoneSessions`, `stack-wecare-digital-PushTokensTable`, `stack-wecare-digital-RequestStatusHistoryTable`, `stack-wecare-digital-RxSlotTable`, `stack-wecare-digital-ScheduledMessagesTable`, `stack-wecare-digital-SecureFilesTable`, `stack-wecare-digital-ServiceRequestsTable`, `stack-wecare-digital-SiteLanguageCache`, `stack-wecare-digital-SmsOutboundTable`, `stack-wecare-digital-SubmitRequestsTable`, `stack-wecare-digital-TemplateAnalyticsTable`, `stack-wecare-digital-UsersTable`, `stack-wecare-digital-VoiceAwsTable`, `stack-wecare-digital-VoiceCalls`, `stack-wecare-digital-WhatsAppCallingTable`, `stack-wecare-digital-WhatsAppGroupTable`, `stack-wecare-digital-WhatsAppPhonesTable`, `stack-wecare-digital-WhatsAppVoiceTable`, `stack-wecare-digital-WixOrdersCache`, `stack-wecare-digital-WixProductsCache`

Without point-in-time recovery (7): `stack-wecare-digital-CatalogCacheTable`, `stack-wecare-digital-PstnSoftphoneSessions`, `stack-wecare-digital-RateLimitTable`, `stack-wecare-digital-SiteLanguageCache`, `stack-wecare-digital-WebhookDedup`, `stack-wecare-digital-WixOrdersCache`, `stack-wecare-digital-WixProductsCache`

With streams (1): `stack-wecare-digital-VoiceCDRTable`

## SQS

| Queue | visible | in flight | DLQ target | maxReceive |
|---|---:|---:|---|---:|
| `stack-wecare-digital-bulk-dlq` | 0 | 0 | — | — |
| `stack-wecare-digital-bulk-queue` | 0 | 0 | `stack-wecare-digital-bulk-dlq` | 3 |
| `stack-wecare-digital-inbound-dlq` | 0 | 0 | — | — |
| `stack-wecare-digital-notification-dlq` | 0 | 0 | — | — |
| `stack-wecare-digital-notification-queue` | 0 | 0 | `stack-wecare-digital-notification-dlq` | 3 |
| `stack-wecare-digital-outbound-dlq` | 0 | 0 | — | — |
| `wecare-blog-ingest` | 0 | 0 | `wecare-blog-ingest-dlq` | 3 |
| `wecare-blog-ingest-dlq` | 0 | 0 | — | — |
| `wecare-eventbridge-dlq` | 0 | 0 | — | — |
| `wecare-lambda-async-dlq` | 0 | 0 | — | — |

Queues with no redrive policy and not DLQ-named: (none)

## EventBridge

- bus `default` — 7 rules
  - `AWSUserNotificationsManagedRule-adi3lsr` ENABLED pattern -> no target [no-dlq]
  - `wecare-amplify-build-failed` ENABLED pattern -> stack-wecare-digital [no-dlq]
  - `wecare-docs-scraper-daily` ENABLED rate(1 day) -> wecare-docs-scraper [no-dlq]
  - `wecare-media-cleanup-daily` ENABLED rate(1 day) -> wecare-media-cleanup [dlq]
  - `wecare-meta-catalog-sync-schedule` ENABLED cron(25 */6 * * ? *) -> live [no-dlq]
  - `wecare-partner-token-refresh-daily` ENABLED rate(1 day) -> wecare-partner-token-refresh [no-dlq]
  - `wecare-scheduled-messages-trigger` ENABLED rate(5 minutes) -> wecare-scheduled-messages [dlq]

EventBridge Scheduler schedules: 1 ['wecare-seo-freshness-daily']

Disabled rules: (none)

## Secrets Manager

Metadata only. No value was read.

| Secret | last changed | rotation | scheduled deletion |
|---|---|---|---|
| `wecare/ads/account-registry` | 2026-10-07 | no | 2026-10-07 |
| `wecare/agent-connector-token` | 2026-07-20 | no | — |
| `wecare/airtel-iq` | 2026-09-20 | no | 2026-09-20 |
| `wecare/airtel/c2c` | 2026-09-20 | no | 2026-09-20 |
| `wecare/airtel/obd` | 2026-09-20 | no | 2026-09-20 |
| `wecare/airtel/sms` | 2026-09-20 | no | 2026-09-20 |
| `wecare/aws/iam-access-keys` | 2026-09-18 | no | — |
| `wecare/backup/recovery-passphrase` | 2026-09-19 | no | — |
| `wecare/bing/api` | 2026-09-18 | no | — |
| `wecare/config/webhook-registry` | 2026-09-29 | no | — |
| `wecare/flow-private-key` | 2026-02-23 | no | — |
| `wecare/github-connection` | 2026-10-07 | no | 2026-10-07 |
| `wecare/github-pat` | 2026-08-26 | no | — |
| `wecare/google-api-key` | 2026-10-07 | no | 2026-10-07 |
| `wecare/google-maps` | 2026-10-07 | no | 2026-10-07 |
| `wecare/google-maps-server` | 2026-10-07 | no | 2026-10-07 |
| `wecare/google/ads` | 2026-10-03 | no | — |
| `wecare/google/cloud` | 2026-10-03 | no | — |
| `wecare/integrations/owner-input-20261001` | 2026-10-07 | no | 2026-10-07 |
| `wecare/meta-system-user-token` | 2026-09-30 | no | — |
| `wecare/meta/payments` | 2026-09-18 | no | — |
| `wecare/openai/api` | 2026-10-07 | no | 2026-10-07 |
| `wecare/otp/pepper` | 2026-10-03 | no | — |
| `wecare/plivo` | 2026-10-07 | no | 2026-10-07 |
| `wecare/plivo-answer` | 2026-09-19 | no | — |
| `wecare/plivo/api` | 2026-09-30 | no | — |
| `wecare/razorpay-webhook` | 2026-09-30 | no | — |
| `wecare/razorpay/api` | 2026-10-02 | no | — |
| `wecare/seo/google-oauth` | 2026-09-19 | no | — |
| `wecare/sinch/rcs` | 2026-05-05 | no | — |
| `wecare/sinch/sms` | 2026-09-20 | no | 2026-09-20 |
| `wecare/truecaller` | 2026-09-19 | no | — |
| `wecare/wix/app-oauth` | 2026-10-05 | no | — |
| `wecare/wix/catalog-webhook` | 2026-10-05 | no | — |
| `wecare/wix/headless-api-key` | 2026-10-05 | no | — |

## Cognito

- `us-east-1_46ULYuukt` **WECARE.DIGITAL-CUSTOMERS** — users≈1, MFA=OFF, advanced_security=None, deletion_protection=ACTIVE
  - clients: ['wecare-customer-whatsapp-otp']
  - groups: ['Partner']
  - lambda triggers: ['CreateAuthChallenge', 'DefineAuthChallenge', 'VerifyAuthChallengeResponse']
- `us-east-1_cSx0RHCIR` **WECARE.DIGITAL** — users≈1, MFA=OPTIONAL, advanced_security=None, deletion_protection=ACTIVE
  - clients: ['stack-wecare-digital-web']
  - groups: ['Admin', 'Operator', 'Partner', 'Viewer']
  - lambda triggers: ['CustomMessage']

Identity pools: 1

## SES

### us-east-1 — production_access=True, sending=True, quota={'Max24HourSend': 50000.0, 'MaxSendRate': 14.0, 'SentLast24Hours': 0.0}

- `one@wecare.digital` (EMAIL_ADDRESS) verified=True dkim=SUCCESS/True mail_from=None/None
- `wecare.digital` (DOMAIN) verified=True dkim=SUCCESS/True mail_from=None/None

Configuration sets: ['wecare-digital']

### ap-south-1 — production_access=False, sending=True, quota={'Max24HourSend': 200.0, 'MaxSendRate': 1.0, 'SentLast24Hours': 0.0}


Configuration sets: []

## S3

| Bucket | region | encryption | PAB all | versioning | public policy |
|---|---|---|---|---|---|
| `cdk-hnb659fds-assets-775261844268-us-east-1` | us-east-1 | aws:kms | yes | Enabled | no |
| `wecare-cloudtrail-775261844268` | us-east-1 | AES256 | **no** | Enabled | no |
| `wecare-credential-backups-775261844268` | us-east-1 | aws:kms | yes | Enabled | no |
| `wecare-digital-get` | us-east-1 | AES256 | yes | Suspended | no |
| `wecare-digital-mta-sts` | us-east-1 | AES256 | yes | — | no |
| `wecare-home-fallback-logbucket-zl8wltb0on7s` | us-east-1 | AES256 | yes | — | no |
| `wecare-maintenance-reports-775261844268` | us-east-1 | aws:kms | yes | Enabled | no |

## CloudFront

- `E1SZBXLQ4XNLJ7` djbi65ldve9va.cloudfront.net aliases=['mta-sts.wecare.digital'] status=Deployed enabled=True web_acl=**none**
  - origins: ['wecare-digital-mta-sts.s3.us-east-1.amazonaws.com']
- `E1ZZ786I3YH65O` d27evp2npt2kzr.cloudfront.net aliases=['*.wecare.digital'] status=Deployed enabled=True web_acl=**none**
  - origins: ['wecare.digital']
- `E2GP22R4BIFGQ3` d1kf2rchz7yras.cloudfront.net aliases=[] status=Deployed enabled=True web_acl=**none**
  - origins: ['wecare-digital-get.s3.us-east-1.amazonaws.com']

## WAF

- **REGIONAL**: 0 web ACLs
- **CLOUDFRONT**: 0 web ACLs

## Route 53

- `wecare.digital.` (Z03939753QJGZ6ZD6BXO8) — 31 records, MX=True, types={'CNAME': 14, 'TXT': 7, 'A': 4, 'AAAA': 3, 'MX': 1, 'NS': 1, 'SOA': 1}

## CloudWatch

- alarms: 73 (composite 0)
- in ALARM: (none)
- INSUFFICIENT_DATA: 0
- alarms with no action: 0
- dashboards: ['wecare-platform-health']
- log groups: 92, stored 0.9 GB
- log groups with no retention: 2
  - `/aws/lambda/wecare-customer-profile`
  - `/aws/lambda/wecare-customer-session`

## IaC

CloudFormation stacks:

- `CDKToolkit` CREATE_COMPLETE updated=2026-02-11 drift=NOT_CHECKED
- `wecare-customer-sessions` UPDATE_COMPLETE updated=2026-10-01 drift=NOT_CHECKED
- `wecare-home-fallback` UPDATE_COMPLETE updated=2026-10-01 drift=NOT_CHECKED
- `wecare-workspace-mcp` UPDATE_COMPLETE updated=2026-10-06 drift=NOT_CHECKED

Amplify:

- `d22dm4b0jn71jw` **wecare.digital** platform=WEB custom_rules=14 repo=https://github.com/wecare-digital/wecare-digital
  - branch `stack` stage=PRODUCTION auto_build=True
    - job 1472 SUCCEED commit `88856c1936d5` 2026-10-08T13:39:04
    - job 1471 SUCCEED commit `4167680a2c2f` 2026-10-08T12:56:48
    - job 1470 SUCCEED commit `23a3a7aa3735` 2026-10-08T12:40:03

## Cross-service checks

Defects that are invisible in any single service listing.

**DLQs with no CloudWatch alarm (0)** — messages can pile up unobserved:

- `(none)`

**Alarms watching a queue that does not exist (0)** — these can never fire:

- queue `(none)` watched by []

**Alarms whose dimension names a resource that does not exist (0)** — same class, across every enumerable dimension:

- `(none)` watched by []

**Regional WAF web ACLs associated with nothing (0)**:

- `(none)`

Amplify WAF association (CloudFront-scope ACLs cannot be queried from the WAF side, so the app is asked directly):

- `d22dm4b0jn71jw` → NOT_ASSOCIATED ['']

