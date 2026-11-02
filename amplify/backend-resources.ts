/**
 * Additional AWS Resources Configuration
 * 
 * This file defines AWS resources that are not directly supported by Amplify Gen 2
 * but need to be created as part of the backend infrastructure.
 */

import { Stack } from 'aws-cdk-lib';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatch_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Duration } from 'aws-cdk-lib';

const AWS_ACCOUNT_ID = process.env.AWS_ACCOUNT_ID || '';
const AWS_REGION = process.env.AWS_REGION || 'us-east-1';

export function addBackendResources ( stack: Stack ) {
  // SQS Queues
  const inboundDlq = new sqs.Queue( stack, 'InboundDLQ', {
    queueName: 'stack-wecare-digital-inbound-dlq',
    visibilityTimeout: Duration.seconds( 300 ),
    retentionPeriod: Duration.days( 7 ),
  } );

  const bulkDlq = new sqs.Queue( stack, 'BulkDLQ', {
    queueName: 'stack-wecare-digital-bulk-dlq',
    visibilityTimeout: Duration.seconds( 300 ),
    retentionPeriod: Duration.days( 7 ),
  } );

  const bulkQueue = new sqs.Queue( stack, 'BulkQueue', {
    queueName: 'stack-wecare-digital-bulk-queue',
    visibilityTimeout: Duration.seconds( 300 ),
    retentionPeriod: Duration.days( 1 ),
    deadLetterQueue: {
      queue: bulkDlq,
      maxReceiveCount: 3,
    },
  } );

  const outboundDlq = new sqs.Queue( stack, 'OutboundDLQ', {
    queueName: 'stack-wecare-digital-outbound-dlq',
    visibilityTimeout: Duration.seconds( 300 ),
    retentionPeriod: Duration.days( 7 ),
  } );

  // SNS Topic (if not already exists)
  const alarmTopic = sns.Topic.fromTopicArn(
    stack,
    'AlarmTopic',
    `arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:stack-wecare-digital`
  );

  // CloudWatch Alarms
  // Global Lambda error catch-all (Sum across the account). The previous version
  // used Average with a 0.01 threshold, which is not an error *rate* and fires on
  // noise. Per-function rate alarms below give precise coverage; this is a coarse
  // "something is broadly wrong" signal.
  const lambdaErrorAlarm = new cloudwatch.Alarm( stack, 'LambdaErrorRateAlarm', {
    alarmName: 'wecare-lambda-errors-total',
    alarmDescription: 'Total Lambda errors exceed 25 in 5 minutes (account-wide)',
    metric: new cloudwatch.Metric( {
      namespace: 'AWS/Lambda',
      metricName: 'Errors',
      statistic: 'Sum',
      period: Duration.minutes( 5 ),
    } ),
    threshold: 25,
    evaluationPeriods: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  } );
  lambdaErrorAlarm.addAlarmAction( new cloudwatch_actions.SnsAction( alarmTopic ) );

  // Global Lambda throttle alarm — concurrency exhaustion / reserved-concurrency issues.
  const lambdaThrottleAlarm = new cloudwatch.Alarm( stack, 'LambdaThrottleAlarm', {
    alarmName: 'wecare-lambda-throttles',
    alarmDescription: 'Lambda throttles detected (account-wide)',
    metric: new cloudwatch.Metric( {
      namespace: 'AWS/Lambda',
      metricName: 'Throttles',
      statistic: 'Sum',
      period: Duration.minutes( 5 ),
    } ),
    threshold: 10,
    evaluationPeriods: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  } );
  lambdaThrottleAlarm.addAlarmAction( new cloudwatch_actions.SnsAction( alarmTopic ) );

  // DLQ depth alarms — one per DLQ (previously only inbound was covered).
  const dlqDepthAlarms: cloudwatch.Alarm[] = [];
  const dlqs: Array<[ string, sqs.Queue ]> = [
    [ 'Inbound', inboundDlq ],
    [ 'Bulk', bulkDlq ],
    [ 'Outbound', outboundDlq ],
  ];
  for ( const [ label, q ] of dlqs )
  {
    const a = new cloudwatch.Alarm( stack, `DLQDepthAlarm${label}`, {
      alarmName: `wecare-dlq-depth-${label.toLowerCase()}`,
      alarmDescription: `${label} DLQ depth exceeds 10 messages`,
      metric: q.metricApproximateNumberOfMessagesVisible( { period: Duration.minutes( 5 ) } ),
      threshold: 10,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    } );
    a.addAlarmAction( new cloudwatch_actions.SnsAction( alarmTopic ) );
    dlqDepthAlarms.push( a );
  }
  const dlqDepthAlarm = dlqDepthAlarms[ 0 ]; // back-compat reference

  // Stuck-queue alarm — bulk work queue oldest message age > 15 min means the
  // bulk-worker is not draining (deploy issue, throttling, or poison messages).
  const bulkQueueAgeAlarm = new cloudwatch.Alarm( stack, 'BulkQueueAgeAlarm', {
    alarmName: 'wecare-bulk-queue-stuck',
    alarmDescription: 'Bulk queue oldest message age exceeds 15 minutes',
    metric: bulkQueue.metricApproximateAgeOfOldestMessage( { period: Duration.minutes( 5 ) } ),
    threshold: 900,
    evaluationPeriods: 2,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  } );
  bulkQueueAgeAlarm.addAlarmAction( new cloudwatch_actions.SnsAction( alarmTopic ) );

  // CloudWatch Dashboard
  new cloudwatch.Dashboard( stack, 'WECAREDashboard', {
    dashboardName: 'WECARE-DIGITAL-Dashboard',
    widgets: [
      [
        new cloudwatch.GraphWidget( {
          title: 'Message Delivery by Channel',
          left: [
            new cloudwatch.Metric( {
              namespace: 'WECARE.DIGITAL',
              metricName: 'MessagesSuccess',
              dimensionsMap: { Channel: 'WHATSAPP' },
            } ),
            new cloudwatch.Metric( {
              namespace: 'WECARE.DIGITAL',
              metricName: 'MessagesSuccess',
              dimensionsMap: { Channel: 'SMS' },
            } ),
            new cloudwatch.Metric( {
              namespace: 'WECARE.DIGITAL',
              metricName: 'MessagesSuccess',
              dimensionsMap: { Channel: 'EMAIL' },
            } ),
          ],
        } ),
      ],
      [
        new cloudwatch.GraphWidget( {
          title: 'DLQ Depth',
          left: [
            inboundDlq.metricApproximateNumberOfMessagesVisible(),
            bulkDlq.metricApproximateNumberOfMessagesVisible(),
            outboundDlq.metricApproximateNumberOfMessagesVisible(),
          ],
        } ),
      ],
    ],
  } );

  // ─── CloudWatch Log Retention Policies ───────────────────────────────
  // Set 90-day retention on all Lambda log groups to control costs.
  // Authoritative list = deployed `wecare-*` functions (aws lambda list-functions).
  const LAMBDA_FUNCTIONS = [
    'wecare-inbound-whatsapp', 'wecare-outbound-whatsapp', 'wecare-whatsapp-calling',
    'wecare-whatsapp-business-api', 'wecare-whatsapp-voice', 'wecare-whatsapp-template-management',
    'wecare-scheduled-messages', 'wecare-bulk-job-create',
    'wecare-bulk-worker', 'wecare-bulk-job-control', 'wecare-ai-query-kb',
    'wecare-ai-config-management', 'wecare-agent-action-group',
    'wecare-razorpay-webhook', 'wecare-payments-read', 'wecare-invoice-engine',
    'wecare-dlq-replay', 'wecare-contacts', 'wecare-catalog-management',
    'wecare-outbound-sms', 'wecare-outbound-email',
    'wecare-sms-aws', 'wecare-voice-aws',
    'wecare-voice-cdr-read', 'wecare-billing',
    'wecare-system-cleanup', 'wecare-product-image-gen', 'wecare-auth-middleware',
    'wecare-faq-handler', 'wecare-messages-read', 'wecare-messages-delete', 'wecare-waba-management',
    'wecare-push-notifications', 'wecare-media-cleanup', 'wecare-template-analytics',
    'wecare-rcs-send', 'wecare-rcs-dlr',
    // Previously missing from retention (orphaned, never-expiring log groups):
    'wecare-conversation-meta', 'wecare-automation-rules',
    'wecare-service-api',
    // Live functions found during the 2026-07 drift audit that were absent from
    // this list (their log groups existed with no retention policy).
    'wecare-marketing-ads', 'wecare-meta-business-agent', 'wecare-partner-onboarding',
    'wecare-partner-token-refresh', 'wecare-docs-scraper',
  ];

  for ( const fnName of LAMBDA_FUNCTIONS )
  {
    new logs.LogGroup( stack, `LogRetention-${fnName}`, {
      logGroupName: `/aws/lambda/${fnName}`,
      retention: logs.RetentionDays.THREE_MONTHS,
    } );
  }

  // ─── Per-Lambda Error Rate Alarms ──────────────────────────────────
  // Critical, customer-facing or money/data-path functions get a dedicated alarm.
  const CRITICAL_LAMBDAS = [
    'wecare-inbound-whatsapp', 'wecare-outbound-whatsapp', 'wecare-whatsapp-calling',
    'wecare-whatsapp-business-api', 'wecare-razorpay-webhook',
    'wecare-invoice-engine', 'wecare-scheduled-messages', 'wecare-bulk-worker',
    'wecare-contacts', 'wecare-service-api',
    'wecare-waba-management', 'wecare-sms-aws', 'wecare-voice-aws',
  ];

  const perLambdaAlarms: cloudwatch.Alarm[] = [];
  for ( const fnName of CRITICAL_LAMBDAS )
  {
    const alarm = new cloudwatch.Alarm( stack, `ErrorAlarm-${fnName}`, {
      alarmName: `wecare-${fnName}-errors`,
      alarmDescription: `Error rate for ${fnName} exceeds threshold`,
      metric: new cloudwatch.Metric( {
        namespace: 'AWS/Lambda',
        metricName: 'Errors',
        dimensionsMap: { FunctionName: fnName },
        statistic: 'Sum',
        period: Duration.minutes( 5 ),
      } ),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    } );
    alarm.addAlarmAction( new cloudwatch_actions.SnsAction( alarmTopic ) );
    perLambdaAlarms.push( alarm );
  }

  // ─── Webhook idempotency guardrail ─────────────────────────────────
  // lambda_utils/webhook_dedup.claim_event() fails OPEN on infra errors and logs
  // {"event":"webhook_dedup_error",...}. If the WebhookDedup table is ever missing
  // or broken, dedup silently disables and duplicate webhooks/metering get processed
  // twice. A metric filter (on the 4 webhook consumers) + alarm 'wecare-webhook-dedup-errors'
  // surfaces that immediately.
  // Managed via scripts/_create_dedup_alarm.py (boto3) because ampx cannot run in the
  // agent environment — same pattern as the DDB throttle alarms below. It already exists
  // live; do NOT re-add it here or a pipeline-deploy will fail on "already exists".

  // ─── DynamoDB per-table throttle/error alarms ──────────────────────
  // Managed via scripts/_create_alarms.py (boto3) because ampx cannot run in the
  // agent environment. They already exist live under names `wecare-ddb-throttle-*`
  // and `wecare-ddb-user-errors`. Do NOT re-add them here or a pipeline-deploy will
  // fail on "already exists". If you later fully adopt IaC, import them first.

  // ─── Amplify build-failure notification ────────────────────────────
  // The shared legacy topic delivers to the WhatsApp worker, not email.
  // Keep other alarm declarations separate from this verified email route.
  const buildFailureTopic = sns.Topic.fromTopicArn(
    stack,
    'BuildFailureTopic',
    stack.formatArn( { service: 'sns', resource: 'wecare-alarm-notifications' } )
  );
  const amplifyBuildFailedRule = new events.Rule( stack, 'AmplifyBuildFailedRule', {
    ruleName: 'wecare-amplify-build-failed',
    description: 'Notify on failed Amplify Hosting deployments',
    eventPattern: {
      source: [ 'aws.amplify' ],
      detailType: [ 'Amplify Deployment Status Change' ],
      detail: { appId: [ 'd22dm4b0jn71jw' ], jobStatus: [ 'FAILED' ] },
    },
  } );
  // Preserve the live target ID and message transformer when adopting the rule.
  const buildFailedResource = amplifyBuildFailedRule.node.defaultChild as events.CfnRule;
  buildFailedResource.targets = [ {
    id: 'sns-email',
    arn: buildFailureTopic.topicArn,
    inputTransformer: {
      inputPathsMap: {
        app: '$.detail.appId', branch: '$.detail.branchName',
        job: '$.detail.jobId', status: '$.detail.jobStatus',
      },
      inputTemplate: '"Amplify build FAILED - app <app> branch <branch> job <job> status <status>"',
    },
  } ];

  // Imported topics do not synthesize resource grants. Adopt the two verified
  // live statements together; compare the live policy before any deployment so
  // a later provider grant is not lost when CloudFormation writes this document.
  const buildFailurePolicy = new sns.TopicPolicy( stack, 'BuildFailureTopicPolicy', {
    topics: [ buildFailureTopic ],
  } );
  buildFailurePolicy.document.addStatements(
    new iam.PolicyStatement( {
      sid: '__default_statement_ID',
      principals: [ new iam.AnyPrincipal() ],
      actions: [
        'sns:GetTopicAttributes', 'sns:SetTopicAttributes', 'sns:AddPermission',
        'sns:RemovePermission', 'sns:DeleteTopic', 'sns:Subscribe',
        'sns:ListSubscriptionsByTopic', 'sns:Publish',
      ],
      resources: [ buildFailureTopic.topicArn ],
      conditions: { StringEquals: { 'AWS:SourceOwner': stack.account } },
    } ),
    new iam.PolicyStatement( {
      sid: 'AllowEventBridgeAmplifyBuildPublish',
      principals: [ new iam.ServicePrincipal( 'events.amazonaws.com' ) ],
      actions: [ 'sns:Publish' ],
      resources: [ buildFailureTopic.topicArn ],
      conditions: {
        ArnEquals: { 'aws:SourceArn': amplifyBuildFailedRule.ruleArn },
        StringEquals: { 'aws:SourceAccount': stack.account },
      },
    } )
  );

  // ─── WAF ────────────────────────────────────────────────────────────
  // Removed 2026-09-28 by owner instruction, as a cost decision. There is no
  // WAF in this account any more: the `WebhookWAF` ACL that used to be declared
  // here (ENABLE_WAF-gated, never switched on) is gone, and so are the two ACLs
  // that WERE live — `wecare-amplify-waf` and `wecare-cognito-waf`. Do not
  // re-add a web ACL here without reading
  // docs/execution/snapshots/waf-associations-before-delete-20260928.json,
  // which records what was removed and what protection went with it.
  // Restore path for the live ACLs: `python3 scripts/provision_waf.py --apply`.
  // Request filtering now rests entirely on the application: handler-level
  // require_auth, provider HMAC verification, lambda_utils/rate_limit.py, the
  // per-phone OTP probe counter, and API Gateway stage/route throttling.

  return {
    queues: {
      inboundDlq,
      bulkQueue,
      bulkDlq,
      outboundDlq,
    },
    alarms: {
      lambdaErrorAlarm,
      lambdaThrottleAlarm,
      dlqDepthAlarm,
      dlqDepthAlarms,
      bulkQueueAgeAlarm,
      perLambdaAlarms,
    },
    rules: { amplifyBuildFailedRule },
  };
}
