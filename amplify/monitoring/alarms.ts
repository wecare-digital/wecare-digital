/**
 * CloudWatch Alarms Configuration for WECARE.DIGITAL
 * 
 * Requirements: 13.9, 14.7
 * 
 * Defines CloudWatch alarms for:
 * - Lambda error rate > 1%
 * - DLQ depth > 10
 * - WhatsApp tier limit > 80%
 * - API error rate > 5%
 * - Bulk job failure rate > 10%
 * 
 * Note: These alarms are configured via AWS CDK/CloudFormation
 * and should be deployed as part of the Amplify backend.
 */

const AWS_ACCOUNT_ID = process.env.AWS_ACCOUNT_ID || '';
const AWS_REGION = process.env.AWS_REGION || 'us-east-1';

export const ALARM_CONFIG = {
  namespace: 'WECARE.DIGITAL',
  // Not `stack-wecare-digital`: that is the WhatsApp event topic, and its only
  // subscriber (the inbound WhatsApp Lambda) drops alarm messages (audit AWS-5).
  snsTopicArn: `arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:wecare-alarm-notifications`,
  
  alarms: {
    // Lambda Error Rate Alarm
    lambdaErrorRate: {
      name: 'wecare-lambda-error-rate',
      description: 'Lambda error rate exceeds 1%',
      metricName: 'Errors',
      namespace: 'AWS/Lambda',
      statistic: 'Average',
      period: 300, // 5 minutes
      evaluationPeriods: 2,
      threshold: 0.01, // 1%
      comparisonOperator: 'GreaterThanThreshold',
      treatMissingData: 'notBreaching',
    },
    
    // DLQ Depth Alarm
    dlqDepth: {
      name: 'wecare-dlq-depth',
      description: 'DLQ depth exceeds 10 messages',
      metricName: 'ApproximateNumberOfMessagesVisible',
      namespace: 'AWS/SQS',
      statistic: 'Maximum',
      period: 300,
      evaluationPeriods: 1,
      threshold: 10,
      comparisonOperator: 'GreaterThanThreshold',
      treatMissingData: 'notBreaching',
    },
    
    // WhatsApp Tier Limit Alarm
    whatsappTierLimit: {
      name: 'wecare-whatsapp-tier-limit',
      description: 'WhatsApp tier limit usage exceeds 80%',
      metricName: 'WhatsAppTierUsagePercent',
      namespace: 'WECARE.DIGITAL',
      statistic: 'Maximum',
      period: 300,
      evaluationPeriods: 1,
      threshold: 80,
      comparisonOperator: 'GreaterThanThreshold',
      treatMissingData: 'notBreaching',
    },
    
    // API Error Rate Alarm
    apiErrorRate: {
      name: 'wecare-api-error-rate',
      description: 'API error rate exceeds 5%',
      metricName: 'MessagesFailed',
      namespace: 'WECARE.DIGITAL',
      statistic: 'Sum',
      period: 300,
      evaluationPeriods: 2,
      threshold: 5, // 5% of total
      comparisonOperator: 'GreaterThanThreshold',
      treatMissingData: 'notBreaching',
    },
    
    // Bulk Job Failure Rate Alarm
    bulkJobFailureRate: {
      name: 'wecare-bulk-job-failure-rate',
      description: 'Bulk job failure rate exceeds 10%',
      metricName: 'BulkJobFailed',
      namespace: 'WECARE.DIGITAL',
      statistic: 'Sum',
      period: 300,
      evaluationPeriods: 1,
      threshold: 10, // 10% threshold
      comparisonOperator: 'GreaterThanThreshold',
      treatMissingData: 'notBreaching',
    },
  },
};

/**
 * CloudWatch Alarm Actions
 * 
 * These actions are triggered when alarms enter ALARM state.
 * All alarms publish to the email alarm topic `wecare-alarm-notifications`.
 */
export const ALARM_ACTIONS = {
  ok: [`arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:wecare-alarm-notifications`],
  alarm: [`arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:wecare-alarm-notifications`],
  insufficientData: [],
};

/**
 * Dashboard Configuration
 * 
 * CloudWatch dashboard widgets for monitoring.
 */
export const DASHBOARD_CONFIG = {
  name: 'WECARE-DIGITAL-Dashboard',
  widgets: [
    {
      type: 'metric',
      title: 'Message Delivery by Channel',
      metrics: [
        ['WECARE.DIGITAL', 'MessagesSuccess', 'Channel', 'WHATSAPP'],
        ['WECARE.DIGITAL', 'MessagesSuccess', 'Channel', 'SMS'],
        ['WECARE.DIGITAL', 'MessagesSuccess', 'Channel', 'EMAIL'],
      ],
    },
    {
      type: 'metric',
      title: 'Message Failures',
      metrics: [
        ['WECARE.DIGITAL', 'MessagesFailed', 'Channel', 'WHATSAPP'],
        ['WECARE.DIGITAL', 'MessagesFailed', 'Channel', 'SMS'],
        ['WECARE.DIGITAL', 'MessagesFailed', 'Channel', 'EMAIL'],
      ],
    },
    {
      type: 'metric',
      title: 'Bulk Job Performance',
      metrics: [
        ['WECARE.DIGITAL', 'BulkJobDuration'],
        ['WECARE.DIGITAL', 'BulkJobThroughput'],
      ],
    },
    {
      type: 'metric',
      title: 'DLQ Depth',
      metrics: [
        ['WECARE.DIGITAL', 'DLQDepth', 'QueueName', 'inbound-dlq'],
        ['WECARE.DIGITAL', 'DLQDepth', 'QueueName', 'bulk-dlq'],
      ],
    },
    {
      type: 'metric',
      title: 'WhatsApp Tier Usage',
      metrics: [
        ['WECARE.DIGITAL', 'WhatsAppTierUsagePercent'],
      ],
    },
  ],
};
