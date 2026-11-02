/**
 * IAM Policies for Lambda Functions
 * 
 * Defines the permissions required for each Lambda function to access AWS services.
 */

const AWS_ACCOUNT_ID = process.env.AWS_ACCOUNT_ID || '';
const AWS_REGION = process.env.AWS_REGION || 'us-east-1';

export const IAM_POLICIES = {
  // Common permissions for all Lambda functions
  common: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        Resource: `arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:log-group:/stack-wecare-digital/*`,
      },
      {
        Effect: 'Allow',
        Action: [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:DeleteItem',
          'dynamodb:Query',
          'dynamodb:Scan',
          'dynamodb:DescribeTable',
        ],
        Resource: [
          `arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/stack-wecare-digital-*`,
          `arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/stack-wecare-digital-*/index/*`,
        ],
      },
      {
        // Historical S3 locations remain readable during migration, but no runtime may
        // create, overwrite, or delete objects there. Broad legacy role grants are
        // intentionally overridden by this explicit deny.
        Sid: 'DenyLegacyMediaWrites',
        Effect: 'Deny',
        Action: [
          's3:PutObject',
          's3:DeleteObject',
        ],
        Resource: [
          'arn:aws:s3:::wecare-digital-get/secure/Invoice/customer_invoice/*',
          'arn:aws:s3:::wecare-digital-get/secure/Invoice/fonts/*',
          'arn:aws:s3:::wecare-digital-get/o/stack/whatsapp-media/*',
          'arn:aws:s3:::wecare-digital-get/stack/whatsapp-media/*',
        ],
      },
      {
        // Account-level action (not resource-scoped) — needed for factory-reset discovery
        Effect: 'Allow',
        Action: [
          'dynamodb:ListTables',
        ],
        Resource: '*',
      },
      {
        Effect: 'Allow',
        Action: [
          'cloudwatch:PutMetricData',
        ],
        Resource: '*',
        Condition: {
          StringEquals: {
            'cloudwatch:namespace': 'WECARE.DIGITAL',
          },
        },
      },
    ],
  },

  // WhatsApp-specific permissions
  whatsapp: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'secretsmanager:GetSecretValue',
        ],
        Resource: [
          // Meta API tokens for Direct API (all WABAs)
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/meta-system-user-token*`,
        ],
      },
      {
        Effect: 'Allow',
        Action: [
          's3:GetObject',
          's3:PutObject',
          's3:DeleteObject',
          's3:ListBucket',
        ],
        // `wecare-digital-get` until 2026-09-28, when that bucket was deleted. The
        // live inline policy `wecare-digital-lambda-permissions` was corrected by hand
        // the same day; this file was not, so a redeploy from here would have replaced
        // a working grant with one naming a bucket that does not exist — turning every
        // media read and write into AccessDenied rather than a loud NoSuchBucket.
        // Before-state: docs/execution/snapshots/iam-lambda-role-before-get-bucket-20260928.json
        Resource: [
          'arn:aws:s3:::wecare-digital-get',
          'arn:aws:s3:::wecare-digital-get/*',
        ],
      },
    ],
  },

  // AWS End User Messaging (pinpoint-sms-voice-v2) — the ONLY normal SMS
  // provider for every country. India -> ap-south-1, else us-east-1.
  //
  // Reconciled 2026-09-19 with the deployed inline policy
  // `wecare-digital-lambda-permissions` statement `PinpointSMSVoice`, which this
  // file had drifted away from in two ways that both mattered:
  //
  //  1. The resource was pinned to `${AWS_REGION}`, i.e. us-east-1. That reads as
  //     "India sends are denied", and it was recorded as a likely blocker for the
  //     India cutover. It was not real: the deployed statement uses `*`, and
  //     simulate_principal_policy against the live role returns ALLOWED in both
  //     regions and on sender-id/WDBEEP/IN. IaC was narrower than reality, which
  //     is the more dangerous direction to drift — it hides a real grant and
  //     invents a fake problem.
  //  2. Only two actions were listed, so anyone reading this file would conclude
  //     delivery receipts and the SMS dashboard were merely unbuilt. In fact the
  //     role could not create an event destination or read spend limits at all,
  //     so they were unbuildable. Twelve actions were added to the live policy by
  //     scripts/iam_sync_comms_permissions.py.
  //
  // Resource stays `*` deliberately. The Describe* family are account-level list
  // operations with no per-resource ARN to scope to, and narrowing the Send*
  // actions to specific phone-number and sender-id ARNs is a change to a live
  // send path that belongs in its own commit alongside its own test.
  sms: {
    Version: '2012-10-17',
    Statement: [
      {
        Sid: 'PinpointSMSVoice',
        Effect: 'Allow',
        Action: [
          // sending
          'sms-voice:SendTextMessage',
          'sms-voice:SendVoiceMessage',
          'sms-voice:SendMediaMessage',
          // inventory the SMS dashboard needs to report honestly
          'sms-voice:DescribePhoneNumbers',
          'sms-voice:DescribePools',
          'sms-voice:DescribeSenderIds',
          'sms-voice:DescribeSpendLimits',
          'sms-voice:DescribeRegistrations',
          'sms-voice:DescribeOptOutLists',
          'sms-voice:DescribeOptedOutNumbers',
          // delivery receipts — without these the consumer cannot be created
          'sms-voice:CreateConfigurationSet',
          'sms-voice:DescribeConfigurationSets',
          'sms-voice:CreateEventDestination',
          'sms-voice:UpdateEventDestination',
          'sms-voice:DeleteEventDestination',
        ],
        Resource: '*',
      },
    ],
  },

  // Email-specific permissions
  email: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'ses:SendEmail',
          'ses:SendRawEmail',
        ],
        Resource: `arn:aws:ses:${AWS_REGION}:${AWS_ACCOUNT_ID}:identity/one@wecare.digital`,
      },
    ],
  },

  // SQS permissions
  sqs: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'sqs:SendMessage',
          'sqs:ReceiveMessage',
          'sqs:DeleteMessage',
          'sqs:GetQueueAttributes',
        ],
        Resource: [
          `arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital-inbound-dlq`,
          `arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital-bulk-queue`,
          `arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital-bulk-dlq`,
          `arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital-outbound-dlq`,
        ],
      },
    ],
  },

  // SNS permissions
  sns: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'sns:Publish',
        ],
        Resource: `arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital`,
      },
    ],
  },

  // Bedrock AI permissions
  bedrock: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'bedrock:InvokeModel',
          'bedrock:InvokeAgent',
          'bedrock:Retrieve',
        ],
        Resource: [
          `arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:knowledge-base/*`,
          `arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:agent/*`,
          'arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0',
        ],
      },
      {
        Effect: 'Allow',
        Action: [
          's3:GetObject',
          's3:PutObject',
        ],
        // See the note on the WhatsApp statement above: the old bucket is deleted and
        // the live role already grants `wecare-digital-get`.
        Resource: 'arn:aws:s3:::wecare-digital-get/*',
      },
    ],
  },

  // Health + Trusted Advisor permissions (for the billing dashboard).
  //
  // Cost Explorer (`ce:*`) was deliberately REMOVED on 2026-09-28. The CE API bills
  // $0.01 per request and this function was responsible for effectively all of the
  // $14.97/month Cost Explorer charge. Withholding the IAM grant is the durable half
  // of that fix: a reintroduced `ce` call now fails with AccessDenied instead of
  // quietly re-establishing a per-request bill. Do not add `ce:*` back here.
  billing: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'health:DescribeEvents',
          'health:DescribeEventDetails',
          'health:DescribeAffectedEntities',
        ],
        Resource: '*',
      },
      {
        Effect: 'Allow',
        Action: [
          'support:DescribeTrustedAdvisorChecks',
          'support:DescribeTrustedAdvisorCheckSummaries',
          'support:DescribeTrustedAdvisorCheckResult',
          'support:RefreshTrustedAdvisorCheck',
        ],
        Resource: '*',
      },
    ],
  },

  // Cognito permissions
  cognito: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'cognito-idp:AdminGetUser',
          'cognito-idp:AdminListGroupsForUser',
          'cognito-idp:GetUser',
        ],
        Resource: `arn:aws:cognito-idp:${AWS_REGION}:${AWS_ACCOUNT_ID}:userpool/us-east-1_cSx0RHCIR`,
      },
    ],
  },

  // Secrets Manager permissions for server-side integrations. The live shared role carries this
  // allowlist as the managed policy `wecare-shared-role-scoped-access`
  // (scripts/scope_shared_lambda_role.py, 2026-10-25); `wecare/otp/pepper` is read only by
  // functions on their own roles.
  secrets: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'secretsmanager:GetSecretValue',
        ],
        Resource: [
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/agent-connector-token-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/bing/api-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/flow-private-key-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/google/ads-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/google/cloud-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/meta-system-user-token-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/partners/*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/plivo-answer-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/plivo/api-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/razorpay/api-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/razorpay-webhook-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/seo/google-oauth-*`,
          `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/sinch/rcs-*`,
        ],
      },
    ],
  },

  // S3 permissions (for non-WhatsApp S3 access — voice recordings, product images, bulk-job files, etc.)
  s3: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          's3:GetObject',
          's3:PutObject',
          's3:DeleteObject',
          's3:ListBucket',
        ],
        // `wecare-digital-get` until 2026-09-28, when that bucket was deleted. The
        // live inline policy `wecare-digital-lambda-permissions` was corrected by hand
        // the same day; this file was not, so a redeploy from here would have replaced
        // a working grant with one naming a bucket that does not exist — turning every
        // media read and write into AccessDenied rather than a loud NoSuchBucket.
        // Before-state: docs/execution/snapshots/iam-lambda-role-before-get-bucket-20260928.json
        Resource: [
          'arn:aws:s3:::wecare-digital-get',
          'arn:aws:s3:::wecare-digital-get/*',
        ],
      },
    ],
  },

  // Amazon Polly permissions (for TTS)
  polly: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'polly:SynthesizeSpeech',
          'polly:DescribeVoices',
        ],
        Resource: '*',
      },
    ],
  },

  // Lambda invoke permissions: the functions the fleet invokes, never `function:wecare-*`. Each
  // is granted bare and qualified (the `live` alias). Live as `wecare-shared-role-scoped-access`
  // (scripts/scope_shared_lambda_role.py `INVOKE_TARGETS`, 2026-10-25).
  lambdaInvoke: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Action: [
          'lambda:InvokeFunction',
        ],
        Resource: [
          'ai-query-kb', 'billing', 'bulk-worker', 'checkout', 'commerce',
          'inbound-whatsapp', 'meta-catalog-sync', 'outbound-email', 'outbound-sms',
          'outbound-whatsapp', 'razorpay-webhook', 'rcs-send', 'scheduled-messages', 'secure-files',
          'service-requests', 'sms-aws', 'voice-aws', 'voice-cdr-read', 'whatsapp-business-api',
          'whatsapp-voice',
        ].flatMap((name) => [
          `arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:wecare-${name}`,
          `arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:wecare-${name}:*`,
        ]),
      },
    ],
  },
};

/**
 * Function-specific policy mappings
 * 
 * Maps each Lambda function to the policies it requires.
 * Naming: use full Lambda function name (wecare-* prefix) for deployed functions,
 * short names for Amplify-managed functions.
 */
export const FUNCTION_POLICIES: Record<string, string[]> = {
  // === Core ===
  'wecare-auth-middleware': [ 'common', 'cognito' ],
  'wecare-contacts': [ 'common' ],  // Unified contacts handler
  'wecare-messages-read': [ 'common' ],
  'wecare-messages-delete': [ 'common' ],

  // === WhatsApp ===
  'wecare-inbound-whatsapp': [ 'common', 'whatsapp', 'sqs', 'sns', 'lambdaInvoke' ],
  'wecare-outbound-whatsapp': [ 'common', 'whatsapp', 'sqs' ],
  'wecare-whatsapp-calling': [ 'common', 'whatsapp', 'secrets', 'lambdaInvoke' ],
  'wecare-whatsapp-voice': [ 'common', 'whatsapp', 'polly' ],
  'wecare-whatsapp-template-management': [ 'common', 'whatsapp', 'secrets' ],
  'wecare-whatsapp-business-api': [ 'common', 'secrets', 's3' ],
  'wecare-waba-management': [ 'common', 'whatsapp', 'sns' ],
  'wecare-media-cleanup': [ 'common', 'whatsapp' ],
  'wecare-template-analytics': [ 'common' ],

  // === SMS ===
  'wecare-outbound-sms': [ 'common', 'sms', 'sqs' ],
  'wecare-outbound-email': [ 'common', 'email', 'sqs' ],
  'wecare-sms-aws': [ 'common', 'sms' ],

  // === Voice (AWS End User Messaging) ===
  'wecare-voice-aws': [ 'common', 'sms' ],

  // === PSTN voice (Plivo) ===
  // Reads two secrets at request time: the diagnostic answer-URL token and the
  // account auth token used as the V3 signature key. It also writes VoiceCDRTable
  // and invokes wecare-sms-aws for the post-call follow-up.
  //
  // Added 2026-09-19. This function was absent from this map while already doing
  // all of the above in production, so its declared permissions did not describe
  // what it actually needs. It runs on the shared wecare-digital-lambda-role
  // (verified live), so it was working by virtue of that role being broad rather
  // than by being granted anything - which is exactly the state this map exists
  // to make visible.
  'wecare-plivo-answer': [ 'common', 'secrets', 'lambdaInvoke' ],

  // === Voice operations ===
  // Reads (and, on DELETE, clears) VoiceCDRTable. plivo-answer is its only writer.
  'wecare-voice-cdr-read': [ 'common' ],

  // === Scheduled & Bulk ===
  'wecare-scheduled-messages': [ 'common', 'lambdaInvoke' ],
  'wecare-bulk-job-create': [ 'common', 'sqs' ],
  'wecare-bulk-worker': [ 'common', 'sqs', 'whatsapp', 'sms', 'email' ],
  'wecare-bulk-job-control': [ 'common', 'sqs', 's3' ],

  // === AI ===
  'wecare-ai-query-kb': [ 'common', 'bedrock' ],
  'wecare-ai-config-management': [ 'common' ],
  'wecare-agent-action-group': [ 'common', 'bedrock', 'lambdaInvoke' ],

  // === Operations ===
  'wecare-dlq-replay': [ 'common', 'sqs', 'sns' ],
  'wecare-billing': [ 'common', 'billing' ],

  // === Payments ===
  'wecare-razorpay-webhook': [ 'common', 'lambdaInvoke' ],

  'wecare-payments-read': [ 'common' ],
  'wecare-invoice-engine': [ 'common', 'whatsapp', 'lambdaInvoke' ],

  // === Ecommerce ===
  'wecare-product-image-gen': [ 'common', 's3' ],

  // === Operations (additional) ===
  'wecare-system-cleanup': [ 'common', 'sqs', 's3' ],

  // === Core (additional) ===
  'wecare-faq-handler': [ 'common' ],

  // === Analytics ===

  // === Ecommerce (additional) ===
  'wecare-catalog-management': [ 'common', 'secrets' ],

  // === Ads ===

  // === RCS ===
  'wecare-rcs-send': [ 'common', 'secrets' ],
  'wecare-rcs-dlr': [ 'common' ],
};
