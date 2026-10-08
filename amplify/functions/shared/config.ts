/**
 * WECARE.DIGITAL Shared Configuration
 * 
 * Centralized configuration for all Lambda functions.
 * Environment variables override these defaults.
 */

// AWS Region
export const AWS_REGION = process.env.AWS_REGION || 'us-east-1';
export const AWS_ACCOUNT_ID = process.env.AWS_ACCOUNT_ID || '';

// DynamoDB Tables (actual deployed names)
export const TABLES = {
  CONTACTS: process.env.CONTACTS_TABLE || 'stack-wecare-digital-ContactsTable',
  MESSAGES_INBOUND: process.env.MESSAGES_INBOUND_TABLE || 'stack-wecare-digital-WhatsAppInboundTable',
  MESSAGES_OUTBOUND: process.env.MESSAGES_OUTBOUND_TABLE || 'stack-wecare-digital-WhatsAppOutboundTable',
  BULK_JOBS: process.env.BULK_JOBS_TABLE || 'stack-wecare-digital-BulkJobsTable',
  BULK_RECIPIENTS: process.env.BULK_RECIPIENTS_TABLE || 'stack-wecare-digital-BulkRecipientsTable',
  USERS: process.env.USERS_TABLE || 'stack-wecare-digital-UsersTable',
  MEDIA_FILES: process.env.MEDIA_FILES_TABLE || 'stack-wecare-digital-MediaFilesTable',
  DLQ_MESSAGES: process.env.DLQ_MESSAGES_TABLE || 'stack-wecare-digital-DLQMessagesTable',
  AUDIT_LOGS: process.env.AUDIT_LOGS_TABLE || 'stack-wecare-digital-AuditLogsTable',
  AI_INTERACTIONS: process.env.AI_INTERACTIONS_TABLE || 'stack-wecare-digital-AIInteractionsTable',
  RATE_LIMIT: process.env.RATE_LIMIT_TABLE || 'stack-wecare-digital-RateLimitTable',
  SYSTEM_CONFIG: process.env.SYSTEM_CONFIG_TABLE || 'stack-wecare-digital-SystemConfigTable',
  VOICE_CALLS: process.env.VOICE_CALLS_TABLE || 'stack-wecare-digital-VoiceCalls',
  // SMS_AWS removed 2026-09-24: `stack-wecare-digital-SmsAwsTable` does not exist
  // in the account. SMS is stored in the canonical MessagesTable under
  // channel='sms' (see MESSAGES below if added, and messaging/sms-aws/handler.py).
  // Note this module currently has no importers - the Lambda fleet is Python and
  // reads its own os.environ defaults - so it functions as documentation, which
  // is exactly why a wrong value in it is worth correcting rather than ignoring.
  VOICE_AWS: process.env.VOICE_AWS_TABLE || 'stack-wecare-digital-VoiceAwsTable',
  WIX_PRODUCTS_CACHE: process.env.WIX_PRODUCTS_CACHE_TABLE || 'stack-wecare-digital-WixProductsCache',
  WIX_ORDERS_CACHE: process.env.WIX_ORDERS_CACHE_TABLE || 'stack-wecare-digital-WixOrdersCache',
};

// Wix Store Configuration
export const WIX_CONFIG = {
  API_BASE_URL: 'https://www.wixapis.com',
  SITE_ID: process.env.WIX_SITE_ID || '',
  ACCOUNT_ID: process.env.WIX_ACCOUNT_ID || '',
};

// S3 Buckets
export const S3_BUCKETS = {
  MEDIA: 'wecare-digital-get',
  REPORTS: 'wecare-digital-get',
};

// S3 Prefixes
// User/transactional data under stack/ (factory reset = wipe stack/ only)
// Static internal assets under stream/ (never wiped)
// Rooted under `o/` to match amplify/functions/shared/lambda_utils/media_paths.py,
// which is the canonical definition. Before the 2026-09-26 bucket merge the whole
// bucket was the public root, so these prefixes carried no root segment and the fleet
// addressed one level above its own data.
export const S3_PREFIXES = {
  MEDIA_INBOUND: 'o/stack/whatsapp-media/incoming/',
  MEDIA_OUTBOUND: 'o/stack/whatsapp-media/outgoing/',
  REPORTS: 'o/stack/reports/',
};

// WhatsApp Configuration
export const WHATSAPP_CONFIG = {
  META_API_VERSION: 'v25.0',
  PHONE_NUMBER_ID_1: process.env.WHATSAPP_PHONE_NUMBER_ID_1 || 'phone-number-id-waba1-direct-1016149501586345',
  PHONE_NUMBER_ID_2: process.env.WHATSAPP_PHONE_NUMBER_ID_2 || 'phone-number-id-waba-t-direct-1055232054343117',
  DISPLAY_PHONE_1: '+91 93309 94400',
  DISPLAY_PHONE_2: '+91 99033 00044',
  // New WABA IDs after migration
  WABA_ID_1: '2094615664435155',  // WECARE.DIGITAL (Direct API, current)
  WABA_ID_2: '2513394156072604',  // Manish Agarwal (migrated, Direct API)
  WABA_ID_3: '2094615664435155',  // WECARE.DIGITAL (Direct API, SIP calling, primary)
  RATE_LIMIT_PER_SECOND: 80,
};

// SNS Topics
export const SNS_TOPICS = {
  WHATSAPP_EVENTS: `arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital`,
};

// Cognito
//
// SSO_DOMAIN moved off the `signin.wecare.digital` custom domain on 2026-09-26 and
// onto the Cognito-provided prefix domain. The prefix domain was upgraded from
// hosted UI classic (ManagedLoginVersion 1) to managed login v2 first, so the page
// served is the same one: verified byte-for-byte equivalent apart from the hostname
// length (34,433 vs 34,441 bytes, identical <title>, zero classic-widget markers).
// Without that upgrade this move would have silently downgraded the sign-in page to
// the old classic UI.
//
// NOTE: this constant currently has NO consumers — it is the only occurrence of
// `SSO_DOMAIN` in the repository. The value that actually drives the OAuth flow is
// `NEXT_PUBLIC_COGNITO_OAUTH_DOMAIN`, read by `src/pages/_app.tsx` from the Amplify
// branch environment at BUILD time. Kept and corrected rather than deleted so it
// cannot be picked up later as a stale pointer to a removed host.
export const COGNITO_CONFIG = {
  USER_POOL_ID: 'us-east-1_cSx0RHCIR',
  APP_CLIENT_ID: '1j8kbi48m4v2rped3n224rlevb',
  SSO_DOMAIN: 'https://wecare-digital-auth.auth.us-east-1.amazoncognito.com',
};

// Bedrock AI Configuration
// Architecture:
//   - SEO Audit: InvokeModel (Claude Opus 4.6 → Nova Pro fallback) in operations/seo-tools/handler.py
//   - WhatsApp Auto-Reply: Converse API (Nova Lite) — no agent needed
//   - Internal Admin: Converse API (Nova Lite) — agent optional, Converse works standalone
//   - WhatsApp Voice/Calling: Converse API (Nova Lite) — agent fallback if configured
//
// Agent status, re-measured 2026-09-23 against account 775261844268:
//
//   NO Bedrock Agent is usable, and none is needed.
//
//   The account's single agent is an empty shell that was created and abandoned on
//   2026-04-25: agentStatus NOT_PREPARED, foundationModel null, instruction 0
//   characters, agentResourceRoleArn null, never prepared, 0 action groups, 0
//   knowledge bases. The account holds 0 knowledge bases in total. The action group
//   Lambda's resource policy grants apigateway.amazonaws.com only, with no
//   bedrock.amazonaws.com principal, so Bedrock could not have invoked it even if
//   the agent had been wired.
//
//   The earlier note here said it "needs action groups + prepare". That understates
//   it: preparing would fail outright, because there is no model, no instruction and
//   no role to prepare.
//
//   Every agent and knowledge-base identifier this file used to carry was
//   fabricated, and the LIVE Lambda environment was worse than these defaults -
//   INTERNAL_AGENT_ID=QIEEHEBTZO, ALIAS=ASCBD7YPUT, INTERNAL_KB_ID=D0JU8Q7IQS,
//   EXTERNAL_KB_ID=LYMQLKZNY7, none of which exist. 'static-faq' was never an id in
//   any format.
//
//   Both live paths use the Converse API directly and are unaffected. Provisioning a
//   real agent is new capability creation, not reconciliation, and is an owner
//   decision - see .kiro/work/phases-5-10/plan.md item 6.4.
//
// Foundation Models (confirmed working):
//   - amazon.nova-pro-v1:0: SEO audit quality (confirmed working)
//   - amazon.nova-pro-v1:0: WhatsApp/admin + SEO fallback (confirmed working)
//   - global.anthropic.claude-sonnet-4-6: PRIMARY SEO model (confirmed working)
export const BEDROCK_CONFIG = {
  // No agent or knowledge-base defaults. Both live paths use the Converse API
  // directly, and a plausible-looking default is exactly what made this surface
  // appear configured for five months. If an agent is ever provisioned, set the
  // variables explicitly rather than restoring a literal here.
  
  // Models
  FOUNDATION_MODEL: 'amazon.nova-pro-v1:0',
  FOUNDATION_MODEL_PRO: 'amazon.nova-pro-v1:0',
  SEO_MODEL: process.env.BEDROCK_MODEL_ID || 'global.anthropic.claude-sonnet-4-6',
  MODEL_ARN: 'arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0',
};

// TTL Configuration (in seconds)
export const TTL_CONFIG = {
  MESSAGES: 30 * 24 * 60 * 60,      // 30 days
  DLQ_MESSAGES: 7 * 24 * 60 * 60,   // 7 days
  AUDIT_LOGS: 180 * 24 * 60 * 60,   // 180 days
  RATE_LIMIT: 24 * 60 * 60,         // 24 hours
  VOICE_CALLS: 90 * 24 * 60 * 60,   // 90 days
};

// Rate Limits
export const RATE_LIMITS = {
  WHATSAPP_PER_SECOND: 80,
  SMS_PER_SECOND: 5,
  EMAIL_PER_SECOND: 10,
  API_PER_SECOND: 1000,
};

// CloudWatch Metrics
export const METRICS_NAMESPACE = 'WECARE.DIGITAL';
