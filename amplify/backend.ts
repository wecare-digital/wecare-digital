import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
import { data } from './data/resource';
import { storage } from './storage/resource';
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
 * - Storage: S3 (existing bucket: wecare-digital-get, public objects under `o/` and
 *   `secure/d/public/`, gated objects under the rest of `secure/`)
 *
 * Additional CDK resources:
 * - SQS Queues (4): inbound-dlq, bulk-queue, bulk-dlq, outbound-dlq
 * - CloudWatch Alarms, Dashboard, Log Retention
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

// ─── DynamoDB retention configuration ───────────────────────────────
// DynamoDB TTL was disabled on the physical WECARE tables on 2026-11-20.
// Do not re-enable it through an Amplify CDK override during a later deploy.
// Application-level expiries (sessions, signed URLs, rate limits, etc.) still
// require their own enforcement even when DynamoDB retains the rows.

// ─── Additional CDK Resources ────────────────────────────────────────
// All additional infrastructure is attached to the data stack so it
// deploys as part of the Amplify backend.
const dataStack = backend.data.resources.stacks[ 'data' ];

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
