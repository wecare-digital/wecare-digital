import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
import { data } from './data/resource';
import { storage } from './storage/resource';
import { addLinkResources } from './link-resources';
import { addBackendResources } from './backend-resources';
import { addSeoResources } from './seo-resources';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';

/**
 * WECARE.DIGITAL Admin Platform Backend
 *
 * AWS Account: 775261844268
 * Region: us-east-1
 *
 * This backend defines:
 * - Auth: Cognito (existing user pool via referenceAuth)
 * - Data: DynamoDB (~58 tables via AppSync)
 * - Storage: S3 (existing bucket: wecare-digital-get, public objects under `o/`,
 *   gated objects under `secure/`)
 *
 *   Corrected 2026-09-29: this used to add "though the HOST survives as a read-only
 *   alias serving this bucket through CloudFront origin path `/o`". It does not.
 *   Re-measured the same day: `get-distribution ERCXSFDL0VM8X` returns
 *   NoSuchDistribution, no distribution carries an `app.wecare.digital` alias, the
 *   DNS name resolves to no address, and `head-bucket app.wecare.digital` is 404.
 *   There is exactly one distribution on this bucket now, E2GP22R4BIFGQ3, serving
 *   `wecare.digital/get/<key>` with origin path `""`. The `o/` prefix is therefore
 *   part of the URL, and it stays mandatory for the reasons in
 *   lambda_utils/media_paths.py — not because a second host still reads it.
 *
 * Additional CDK resources:
 * - SQS Queues (4): inbound-dlq, bulk-queue, bulk-dlq, outbound-dlq
 * - CloudWatch Alarms, Dashboard, Log Retention
 * - URL Shortener (wecare.digital/r, plus the r.wecare.digital alias):
 *   API Gateway + Lambda + DynamoDB + Route53
 * - Durable Admin SEO audit/log storage and Lambda
 *
 * Lambda functions (42+ Python functions) are deployed separately
 * and already exist in AWS. They are not managed by Amplify Gen 2.
 */
const backend = defineBackend( {
  auth,
  data,
  storage,
} );

// ─── DynamoDB TTL Configuration ──────────────────────────────────────
// Enable TTL on tables that have expiresAt/ttl fields.
// Amplify Gen 2 doesn't support TTL natively, so we use CDK overrides.
// NOTE: TTL is also enforced directly on the physical tables via
// scripts/_fix_ddb_ttl.py (the CDK override below historically failed silently).
// RateLimitTracker is omitted here, but NOT for the reason this comment used to
// give. It claimed 'lastUpdatedAt' is "NOT an expiry" and that enabling TTL on it
// "would purge the entire table". Both halves are wrong, and were wrong when
// written: every writer (lambda_utils/rate_limit.py and
// outbound-whatsapp._check_rate_limit) sets it to windowStart + 86400, an absolute
// future expiry, and DescribeTimeToLive on 2026-09-25 shows TTL already ENABLED on
// lastUpdatedAt on the live table — with 143 rows present, so nothing was purged.
// It stays omitted only because the physical table already has the TTL it needs and
// this CDK override historically failed silently; the live table, not this file, is
// the thing that is right.
const TTL_CONFIG: Record<string, string> = {
  Message: 'expiresAt',
  DLQMessage: 'expiresAt',
  AuditLog: 'expiresAt',
  VoiceAws: 'expiresAt',
  VoiceCDR: 'expiresAt',
  WhatsAppVoice: 'expiresAt',
  WhatsAppInbound: 'expiresAt',
  WhatsAppOutbound: 'expiresAt',
  WebhookDedup: 'ttl',
  SystemEvent: 'ttl',
  CatalogCache: 'ttl',
  AdClickAttribution: 'ttl',
  WhatsAppCalling: 'ttl',
  RazorpayWebhookLog: 'expiresAt',
  // PayUWebhookLog removed 2026-09-20 with the model; PayU is retired and its
  // table was deleted from the account.
  // PSTN voice (Plivo). PstnCall, PstnCallEvent and PstnAgentPresence were
  // configured here until 2026-09-23. All three were removed along with their
  // declarations in data/resource.ts: none existed in the account, and nothing in
  // amplify/functions read or wrote them. A TTL entry for a model that has no
  // table is a no-op on the `if ( table )` guard below, so this block was quietly
  // configuring nothing.
  //
  // The dual-purpose presence clock survives where it is actually used: in
  // PstnSoftphoneSessions, whose expiresAt is both the DynamoDB TTL and the
  // availability cutoff, so an agent whose browser closed without signing out
  // stops being routable when the heartbeat goes stale rather than when DynamoDB
  // happens to sweep. See scripts/provision_pstn_softphone.py, which sets it.
  //
  // PstnNotificationDelivery was declared here and in data/resource.ts and
  // existed in none of the 66 live tables, so every claim against it raised
  // ClaimStoreUnavailable and the dial-events route answered 503 without
  // sending. Removed 2026-09-21 rather than materialised (NOTIF-STORE-001);
  // the replacement tables are provisioned and read back by
  // scripts/provision_notification_domain.py, which sets their own TTL.
  //
  // PstnFlowVersion and PstnRecordingAudit were listed here as deliberately
  // TTL-free - immutable routing history, and an audit record that must outlive
  // the audio it describes. Both reasons are sound and both are moot: neither
  // model had a table, and both declarations were removed on 2026-09-23. The
  // reasoning is kept in data/resource.ts so it is available if either is ever
  // built, rather than as a comment about a model that no longer exists.
};

try
{
  const dataStack = backend.data.resources.cfnResources;
  for ( const [ modelName, ttlAttribute ] of Object.entries( TTL_CONFIG ) )
  {
    const table = dataStack.amplifyDynamoDbTables[ modelName ];
    if ( table )
    {
      ( table as any ).addPropertyOverride( 'TimeToLiveSpecification', {
        AttributeName: ttlAttribute,
        Enabled: true,
      } );
    }
  }
} catch ( e )
{
  // TTL override may fail in some Amplify Gen 2 versions — log and continue
  console.warn( 'TTL CDK override skipped:', e );
}

// ─── Additional CDK Resources ────────────────────────────────────────
// All additional infrastructure is attached to the data stack so it
// deploys as part of the Amplify backend.
const dataStack = backend.data.resources.stacks[ 'data' ];

/**
 * URL Shortener Resources
 * DynamoDB tables, the HTTP API and the Lambda integration.
 *
 * No longer creates anything for `r.wecare.digital`: that host was retired on
 * 2026-09-28 and short links are served on the apex `/r/<*>` path instead.
 */
addLinkResources( dataStack );

/**
 * Backend Infrastructure Resources
 * Creates SQS queues, CloudWatch alarms/dashboard, log retention,
 * and per-Lambda error alarms.
 */
addBackendResources( dataStack );

/**
 * SEO Tools Resources
 * Creates retained durable audit/log state. The Admin-only SEO Lambda is
 * Amplify-managed, while routes are registered separately after canary approval.
 */
const { table: seoTable, function: seoLambda } = addSeoResources( dataStack );
seoTable.grantReadWriteData( seoLambda );
seoLambda.addEnvironment(
  'COGNITO_USER_POOL_ID',
  backend.auth.resources.userPool.userPoolId,
);

const dedupTable = dynamodb.Table.fromTableName(
  dataStack,
  'SeoAdminDedupTable',
  'stack-wecare-digital-WebhookDedup',
);
dedupTable.grantWriteData( seoLambda );

seoLambda.addToRolePolicy( new iam.PolicyStatement( {
  actions: [ 'bedrock:InvokeModel' ],
  resources: [
    'arn:aws:bedrock:*::foundation-model/*',
    `arn:aws:bedrock:*:${dataStack.account}:inference-profile/*`,
    `arn:aws:bedrock:*:${dataStack.account}:application-inference-profile/*`,
  ],
} ) );
seoLambda.addToRolePolicy( new iam.PolicyStatement( {
  actions: [ 'cognito-idp:GetUser', 'cognito-idp:AdminListGroupsForUser' ],
  resources: [ backend.auth.resources.userPool.userPoolArn ],
} ) );

export default backend;
