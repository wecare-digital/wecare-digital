/**
 * Infrastructure Dashboard Tab
 * Complete project architecture view — Lambda functions, DynamoDB tables,
 * AWS resources, environment variables, API endpoints, and their connections.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { API_BASE, AWS_ACCOUNT_ID, AWS_REGION } from '../../../config/constants';
import { useToastContext } from '../../../contexts/ToastContext';

// ── Data Definitions ──

interface LambdaInfo {
  name: string;
  category: string;
  purpose: string;
  apiRoute: string;
  tables: string[];
  triggers: string[];
  runtime: string;
  timeout: number;
  memory: number;
  envVars: Record<string, string>;
  status?: 'ok' | 'error' | 'unknown';
  statusMsg?: string;
}

interface TableInfo {
  name: string;
  displayName: string;
  category: string;
  partitionKey: string;
  sortKey?: string;
  gsis: string[];
  ttlField?: string;
  usedBy: string[];
}

interface ApiEndpoint {
  method: string;
  path: string;
  lambda: string;
  auth: boolean;
  purpose: string;
  status?: number;
}

interface SecretInfo {
  name: string;
  purpose: string;
  keys: string[];
  usedBy: string[];
}

const LAMBDAS: LambdaInfo[] = [
  // Core
  { name: 'wecare-contacts', category: 'Core', purpose: 'Contact CRUD + search + duplicate detection', apiRoute: '/workspace/contacts', tables: ['ContactsTable', 'WhatsAppInboundTable', 'WhatsAppOutboundTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: { CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' } },
  { name: 'wecare-messages-read', category: 'Core', purpose: 'Read messages from WhatsApp Inbound/Outbound tables', apiRoute: '/messages', tables: ['WhatsAppInboundTable', 'WhatsAppOutboundTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 256, envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' } },
  { name: 'wecare-messages-delete', category: 'Core', purpose: 'Delete messages by ID', apiRoute: '/messages/{id}', tables: ['WhatsAppInboundTable', 'WhatsAppOutboundTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-faq-handler', category: 'Core', purpose: 'FAQ auto-response engine', apiRoute: '/faq', tables: ['FAQTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: { FAQ_TABLE: 'stack-wecare-digital-FAQTable' } },
  { name: 'wecare-url-shortener', category: 'Core', purpose: 'Short link creation and redirect', apiRoute: '/workspace/link', tables: ['ShortLinksTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 10, memory: 128, envVars: { LINKS_TABLE: 'stack-wecare-digital-ShortLinksTable' } },
  // Messaging
  { name: 'wecare-inbound-whatsapp', category: 'Messaging', purpose: 'Process incoming WhatsApp messages, media, reactions, auto-reply, AI, subscribe flow', apiRoute: '/webhook/whatsapp', tables: ['ContactsTable', 'WhatsAppInboundTable', 'MediaFilesTable', 'SystemConfigTable', 'AIInteractionsTable', 'SubmitRequestsTable', 'WhatsAppGroupTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 120, memory: 512, envVars: { CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', MESSAGES_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', SYSTEM_CONFIG_TABLE: 'stack-wecare-digital-SystemConfigTable' } },
  { name: 'wecare-outbound-whatsapp', category: 'Messaging', purpose: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send', tables: ['ContactsTable', 'WhatsAppOutboundTable', 'MediaFilesTable', 'RateLimitTable'], triggers: ['API Gateway', 'SQS'], runtime: 'Python 3.12', timeout: 60, memory: 512, envVars: { CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', MESSAGES_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable' } },
  { name: 'wecare-whatsapp-business-api', category: 'Messaging', purpose: 'WhatsApp Flows, profile, groups, webhooks, subscribe flow data exchange', apiRoute: '/wa-business/*', tables: ['ContactsTable', 'SubmitRequestsTable', 'FlowRegistryTable', 'FlowSubmissionTable', 'FlowLogTable', 'WixOrdersCache', 'WixOrderIds'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 256, envVars: { META_TOKEN_SECRET: 'wecare/meta-system-user-token', SUBMIT_REQUESTS_TABLE: 'stack-wecare-digital-SubmitRequestsTable', FLOW_REGISTRY_TABLE: 'stack-wecare-digital-FlowRegistryTable' } },
  { name: 'wecare-whatsapp-calling', category: 'Messaging', purpose: 'WhatsApp voice/video call handling, IVR, auto-pickup', apiRoute: '/whatsapp', tables: ['WhatsAppCallingTable', 'SystemConfigTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: { CALL_LOG_TABLE: 'stack-wecare-digital-WhatsAppCallingTable', SYSTEM_CONFIG_TABLE: 'stack-wecare-digital-SystemConfigTable', META_TOKEN_SECRET: 'wecare/meta-system-user-token' } },
  { name: 'wecare-whatsapp-voice', category: 'Messaging', purpose: 'WhatsApp TTS/audio voice note processing', apiRoute: '/whatsapp-voice', tables: ['ContactsTable', 'WhatsAppOutboundTable', 'WhatsAppVoiceTable', 'WhatsAppInboundTable', 'SystemConfigTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-whatsapp-templates', category: 'Messaging', purpose: 'Template CRUD via Meta API', apiRoute: '/whatsapp/templates', tables: ['TemplateTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-waba-management', category: 'Messaging', purpose: 'WABA config, phone management, media upload/download', apiRoute: '/waba', tables: ['SystemConfigTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 256, envVars: { SYSTEM_CONFIG_TABLE: 'stack-wecare-digital-SystemConfigTable' } },
  { name: 'wecare-outbound-sms', category: 'Messaging', purpose: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send', tables: ['ContactsTable', 'MessagesTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-outbound-email', category: 'Messaging', purpose: 'Send email via Amazon SES', apiRoute: '/email/send', tables: ['ContactsTable', 'MessagesTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-sms-aws', category: 'Messaging', purpose: 'AWS End User Messaging sender, DLT registry, legacy history', apiRoute: '/sms-aws', tables: ['ContactsTable', 'SmsAwsTable', 'DLTTemplates', 'AirtelSMSTable'], triggers: ['API Gateway', 'SNS'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-voice-aws', category: 'Messaging', purpose: 'AWS Pinpoint voice call handler', apiRoute: '/voice-aws', tables: ['ContactsTable', 'VoiceAwsTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-voice-in-c2c', category: 'Messaging', purpose: 'Click-to-Call webhook (retired provider, historical reads)', apiRoute: '/webhook/voice-c2c', tables: ['AirtelC2CTable', 'VoiceCDRTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-voice-in-obd', category: 'Messaging', purpose: 'OBD campaign webhook (retired provider, historical reads)', apiRoute: '/webhook/voice-obd', tables: ['OBDCampaignTable', 'VoiceCDRTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-voice-in-cdr', category: 'Messaging', purpose: 'Voice call detail records', apiRoute: '/webhook/voice-cdr', tables: ['VoiceCDRTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-scheduled-messages', category: 'Messaging', purpose: 'Schedule and send messages at specific times', apiRoute: '/scheduled', tables: ['ScheduledMessagesTable', 'ContactsTable'], triggers: ['API Gateway', 'EventBridge'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: {} },
  { name: 'wecare-template-analytics', category: 'Messaging', purpose: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics', tables: ['TemplateAnalyticsTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-ad-attribution', category: 'Messaging', purpose: 'Click-to-WhatsApp ad tracking', apiRoute: '/ad-attribution', tables: ['AdAttributionTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-push-notifications', category: 'Messaging', purpose: 'Web push notification delivery', apiRoute: '/push', tables: [], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  // AI
  { name: 'wecare-ai-generate-response', category: 'AI', purpose: 'Generate AI responses via Bedrock, subscribe flow, payment flow', apiRoute: '/ai/generate', tables: ['ConversationHistoryTable', 'ContactsTable', 'SystemConfigTable', 'WhatsAppInboundTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: {} },
  { name: 'wecare-ai-query-kb', category: 'AI', purpose: 'Query Bedrock Knowledge Base', apiRoute: '/ai/query', tables: [], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 256, envVars: {} },
  { name: 'wecare-ai-config-management', category: 'AI', purpose: 'Manage AI/bot configuration', apiRoute: '/ai/config', tables: ['SystemConfigTable', 'AIInteractionsTable', 'ConversationHistoryTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-agent-action-group', category: 'AI', purpose: 'Bedrock Agent action group handler', apiRoute: '', tables: ['ContactsTable', 'WhatsAppInboundTable', 'WhatsAppOutboundTable'], triggers: ['Bedrock Agent'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: {} },
  // Payments
  { name: 'wecare-razorpay-webhook', category: 'Payments', purpose: 'Razorpay payment webhook handler', apiRoute: '/webhook/razorpay', tables: ['PaymentsTable', 'InvoicesTable', 'RazorpayWebhookLogTable'], triggers: ['API Gateway (Webhook)'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-payments-read', category: 'Payments', purpose: 'Read payment records', apiRoute: '/payments', tables: ['PaymentsTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-invoice-engine', category: 'Payments', purpose: 'Invoice creation, PDF generation, payment links', apiRoute: '/invoices', tables: ['InvoicesTable', 'InvoiceItemsTable', 'InvoiceSequenceTable', 'InvoiceAssetsTable', 'InvoiceDeliveryLogTable', 'PaymentsTable', 'ContactsTable', 'SystemConfigTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: {} },
  // Operations
  { name: 'wecare-bulk-job-create', category: 'Operations', purpose: 'Create bulk messaging jobs', apiRoute: '/bulk/create', tables: ['BulkJobsTable', 'BulkRecipientsTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 256, envVars: {} },
  { name: 'wecare-bulk-job-control', category: 'Operations', purpose: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control', tables: ['BulkJobsTable', 'BulkRecipientsTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-bulk-worker', category: 'Operations', purpose: 'Process bulk message queue items', apiRoute: '', tables: ['BulkJobsTable', 'BulkRecipientsTable', 'ContactsTable', 'WhatsAppOutboundTable'], triggers: ['SQS'], runtime: 'Python 3.12', timeout: 300, memory: 512, envVars: {} },
  { name: 'wecare-dlq-replay', category: 'Operations', purpose: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay', tables: ['DLQMessagesTable'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 128, envVars: {} },
  { name: 'wecare-billing', category: 'Operations', purpose: 'AWS Health and Support/Trusted Advisor status tracking (Cost Explorer removed 2026-09-28)', apiRoute: '/billing', tables: [], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 128, envVars: {} },
  { name: 'wecare-system-cleanup', category: 'Operations', purpose: 'TTL cleanup, orphan removal, maintenance', apiRoute: '', tables: [], triggers: ['EventBridge (Daily)'], runtime: 'Python 3.12', timeout: 300, memory: 256, envVars: {} },
  // Ecommerce
  { name: 'wecare-wix-store', category: 'Ecommerce', purpose: 'Wix ecommerce integration', apiRoute: '/store/wix', tables: ['WixProductsCache', 'WixOrdersCache'], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 30, memory: 128, envVars: {} },
  { name: 'wecare-product-image-gen', category: 'Ecommerce', purpose: 'AI product image generation', apiRoute: '/store/image-gen', tables: [], triggers: ['API Gateway'], runtime: 'Python 3.12', timeout: 60, memory: 512, envVars: {} },
];

const TABLES: TableInfo[] = [
  { name: 'ContactsTable', displayName: 'Contacts', category: 'Core', partitionKey: 'id', gsis: ['phone-index', 'email-index', 'bsuid-index'], usedBy: ['wecare-contacts', 'wecare-inbound-whatsapp', 'wecare-outbound-whatsapp', 'wecare-whatsapp-business-api', 'wecare-ai-generate-response', 'wecare-invoice-engine', 'wecare-bulk-worker'] },
  { name: 'WhatsAppInboundTable', displayName: 'WhatsApp Inbound', category: 'Messages', partitionKey: 'id', gsis: ['contactId-index', 'whatsappMessageId-index'], ttlField: 'expiresAt', usedBy: ['wecare-inbound-whatsapp', 'wecare-messages-read', 'wecare-contacts'] },
  { name: 'WhatsAppOutboundTable', displayName: 'WhatsApp Outbound', category: 'Messages', partitionKey: 'id', gsis: ['contactId-index', 'whatsappMessageId-index', 'templateName-index'], ttlField: 'expiresAt', usedBy: ['wecare-outbound-whatsapp', 'wecare-messages-read', 'wecare-contacts'] },
  { name: 'WhatsAppCallingTable', displayName: 'WhatsApp Calling', category: 'Messages', partitionKey: 'id', gsis: ['callId-index'], ttlField: 'ttl', usedBy: ['wecare-whatsapp-calling'] },
  { name: 'WhatsAppVoiceTable', displayName: 'WhatsApp Voice (TTS)', category: 'Messages', partitionKey: 'messageId', gsis: ['contactId-index'], ttlField: 'expiresAt', usedBy: ['wecare-whatsapp-voice'] },
  { name: 'WhatsAppGroupTable', displayName: 'WhatsApp Groups', category: 'Messages', partitionKey: 'id', gsis: ['groupId-index', 'wabaId-index'], usedBy: ['wecare-inbound-whatsapp'] },
  { name: 'SystemConfigTable', displayName: 'System Config', category: 'Core', partitionKey: 'id', gsis: [], usedBy: ['wecare-inbound-whatsapp', 'wecare-whatsapp-calling', 'wecare-waba-management', 'wecare-ai-config-management', 'wecare-invoice-engine'] },
  { name: 'SmsAwsTable', displayName: 'SMS AWS (Pinpoint)', category: 'SMS', partitionKey: 'messageId', gsis: ['contactId-index', 'phoneNumber-index'], ttlField: 'expiresAt', usedBy: ['wecare-sms-aws'] },
  { name: 'AirtelSMSTable', displayName: 'Legacy SMS history (retired providers)', category: 'SMS', partitionKey: 'messageId', gsis: ['contactId-index', 'phoneNumber-index', 'status-index'], ttlField: 'expiresAt', usedBy: ['wecare-sms-aws (read-only)'] },
  { name: 'DLTTemplates', displayName: 'TRAI DLT registry', category: 'SMS', partitionKey: 'templateId', gsis: [], usedBy: ['wecare-sms-aws'] },
  { name: 'VoiceAwsTable', displayName: 'Voice AWS (Pinpoint)', category: 'Voice', partitionKey: 'callId', gsis: ['contactId-index', 'phoneNumber-index'], ttlField: 'expiresAt', usedBy: ['wecare-voice-aws'] },
  { name: 'AirtelC2CTable', displayName: 'C2C history (retired provider)', category: 'Voice', partitionKey: 'callId', gsis: ['contactId-index', 'fromNumber-index', 'toNumber-index', 'status-index'], ttlField: 'expiresAt', usedBy: ['wecare-voice-in-c2c'] },
  { name: 'VoiceCDRTable', displayName: 'Voice CDR', category: 'Voice', partitionKey: 'id', gsis: ['vmSessionId-index', 'callerNumber-index', 'callType-index'], ttlField: 'expiresAt', usedBy: ['wecare-voice-in-cdr', 'wecare-voice-in-c2c', 'wecare-voice-in-obd'] },
  { name: 'OBDCampaignTable', displayName: 'OBD Campaigns', category: 'Voice', partitionKey: 'id', gsis: [], ttlField: 'ttl', usedBy: ['wecare-voice-in-obd'] },
  { name: 'ScheduledMessagesTable', displayName: 'Scheduled Messages', category: 'Messages', partitionKey: 'scheduledId', gsis: ['contactId-index', 'status-index'], usedBy: ['wecare-scheduled-messages'] },
  { name: 'TemplateAnalyticsTable', displayName: 'Template Analytics', category: 'Analytics', partitionKey: 'id', gsis: ['templateName-index'], usedBy: ['wecare-template-analytics'] },
  { name: 'AdAttributionTable', displayName: 'Ad Attribution', category: 'Analytics', partitionKey: 'id', gsis: [], ttlField: 'ttl', usedBy: ['wecare-ad-attribution'] },
  { name: 'PaymentsTable', displayName: 'Payments', category: 'Payments', partitionKey: 'id', gsis: ['paymentId-index', 'orderId-index'], usedBy: ['wecare-razorpay-webhook', 'wecare-payments-read', 'wecare-invoice-engine'] },
  { name: 'InvoicesTable', displayName: 'Invoices', category: 'Payments', partitionKey: 'id', gsis: [], usedBy: ['wecare-invoice-engine', 'wecare-razorpay-webhook'] },
  { name: 'InvoiceItemsTable', displayName: 'Invoice Items', category: 'Payments', partitionKey: 'id', gsis: [], usedBy: ['wecare-invoice-engine'] },
  { name: 'InvoiceAssetsTable', displayName: 'Invoice Assets', category: 'Payments', partitionKey: 'id', gsis: [], usedBy: ['wecare-invoice-engine'] },
  { name: 'InvoiceDeliveryLogTable', displayName: 'Invoice Delivery Log', category: 'Payments', partitionKey: 'id', gsis: [], usedBy: ['wecare-invoice-engine'] },
  { name: 'InvoiceSequenceTable', displayName: 'Invoice Sequence', category: 'Payments', partitionKey: 'id', gsis: [], usedBy: ['wecare-invoice-engine'] },
  { name: 'RazorpayWebhookLogTable', displayName: 'Razorpay Webhook Log', category: 'Payments', partitionKey: 'id', gsis: [], ttlField: 'expiresAt', usedBy: ['wecare-razorpay-webhook'] },
  { name: 'BulkJobsTable', displayName: 'Bulk Jobs', category: 'Operations', partitionKey: 'jobId', gsis: [], usedBy: ['wecare-bulk-job-create', 'wecare-bulk-job-control', 'wecare-bulk-worker'] },
  { name: 'BulkRecipientsTable', displayName: 'Bulk Recipients', category: 'Operations', partitionKey: 'jobId', sortKey: 'recipientId', gsis: [], usedBy: ['wecare-bulk-job-create', 'wecare-bulk-job-control', 'wecare-bulk-worker'] },
  { name: 'DLQMessagesTable', displayName: 'DLQ Messages', category: 'Operations', partitionKey: 'dlqMessageId', gsis: [], ttlField: 'expiresAt', usedBy: ['wecare-dlq-replay'] },
  { name: 'AuditLog', displayName: 'Audit Logs', category: 'Operations', partitionKey: 'logId', gsis: [], ttlField: 'expiresAt', usedBy: [] },
  { name: 'RateLimitTracker', displayName: 'Rate Limit', category: 'Operations', partitionKey: 'channel', sortKey: 'windowStart', gsis: [], ttlField: 'lastUpdatedAt', usedBy: ['wecare-outbound-whatsapp'] },
  { name: 'ConversationHistoryTable', displayName: 'AI Conversation History', category: 'AI', partitionKey: 'phoneHash', gsis: [], usedBy: ['wecare-ai-generate-response', 'wecare-ai-config-management'] },
  { name: 'AIInteractionsTable', displayName: 'AI Interactions', category: 'AI', partitionKey: 'interactionId', gsis: ['messageId-index'], usedBy: ['wecare-ai-config-management', 'wecare-inbound-whatsapp'] },
  { name: 'SubmitRequestsTable', displayName: 'Flow Submit Requests', category: 'Flows', partitionKey: 'id', gsis: ['phone-index', 'orderId-index', 'paymentStatus-index', 'paymentReferenceId-index'], usedBy: ['wecare-whatsapp-business-api', 'wecare-inbound-whatsapp'] },
  { name: 'FlowRegistryTable', displayName: 'Flow Registry', category: 'Flows', partitionKey: 'flowId', gsis: [], usedBy: ['wecare-whatsapp-business-api'] },
  { name: 'FlowSubmissionTable', displayName: 'Flow Submissions', category: 'Flows', partitionKey: 'submissionId', gsis: [], usedBy: ['wecare-whatsapp-business-api'] },
  { name: 'FlowLogTable', displayName: 'Flow Logs', category: 'Flows', partitionKey: 'logId', gsis: [], usedBy: ['wecare-whatsapp-business-api'] },
  { name: 'FAQTable', displayName: 'FAQ', category: 'Core', partitionKey: 'id', gsis: [], usedBy: ['wecare-faq-handler'] },
  { name: 'ShortLinksTable', displayName: 'Short Links', category: 'Core', partitionKey: 'id', gsis: [], usedBy: ['wecare-url-shortener'] },
  { name: 'MediaFilesTable', displayName: 'Media Files', category: 'Core', partitionKey: 'fileId', gsis: ['messageId-index'], usedBy: ['wecare-inbound-whatsapp', 'wecare-outbound-whatsapp'] },
  { name: 'WixProductsCache', displayName: 'Wix Products', category: 'Ecommerce', partitionKey: 'productId', gsis: [], usedBy: ['wecare-wix-store'] },
  { name: 'WixOrdersCache', displayName: 'Wix Orders', category: 'Ecommerce', partitionKey: 'orderId', gsis: ['buyerEmail-index', 'paymentStatus-index', 'orderNumber-index'], usedBy: ['wecare-wix-store', 'wecare-whatsapp-business-api'] },
  { name: 'WixOrderIds', displayName: 'Wix Order IDs', category: 'Ecommerce', partitionKey: 'id', gsis: [], usedBy: ['wecare-whatsapp-business-api'] },
  { name: 'UsersTable', displayName: 'Users', category: 'Core', partitionKey: 'userId', gsis: ['email-index'], usedBy: [] },
  { name: 'EmailTable', displayName: 'Email Messages', category: 'Messages', partitionKey: 'id', gsis: [], usedBy: ['wecare-outbound-email'] },
];

const SECRETS: SecretInfo[] = [
  { name: 'wecare/meta-system-user-token', purpose: 'Meta Graph API access token + app secret for both WABAs', keys: ['access_token', 'access_token_waba2', 'app_secret', 'app_secret_waba2', 'client_token', 'waba_t_id', 'waba_t_phone_meta_id'], usedBy: ['wecare-inbound-whatsapp', 'wecare-outbound-whatsapp', 'wecare-whatsapp-business-api', 'wecare-whatsapp-calling', 'wecare-waba-management', 'wecare-whatsapp-templates'] },
  { name: 'wecare/flow-private-key', purpose: 'WhatsApp Flow encryption private key for data exchange', keys: ['private_key'], usedBy: ['wecare-whatsapp-business-api'] },
  // Three retired-provider credentials still exist in Secrets Manager with no
  // remaining reader. They are deleted under separate destructive approval, per
  // docs/provider-retirement-inventory.md; secret paths are not listed here.
  { name: '3 retired-provider credentials', purpose: 'Retired India voice/SMS provider - no remaining reader. Pending destructive-approval deletion.', keys: [], usedBy: [] },
];