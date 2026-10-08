import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../lib/reviewEntry';
/**
 * System Architecture — Project Control Center
 * Complete end-to-end dashboard for the entire WECARE.DIGITAL platform.
 * 16 tabs covering frontend, backend, infra, AWS, storage, dependencies, risks.
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; }

// ─── Auto-Refresh Hook ───
function useAutoRefresh ( intervalMs = 60000 ) {
  const [ lastRefresh, setLastRefresh ] = useState( () => new Date() );
  const [ isAutoRefresh, setIsAutoRefresh ] = useState( true );
  const timerRef = useRef<ReturnType<typeof setInterval> | null>( null );

  useEffect( () => {
    if ( isAutoRefresh )
    {
      timerRef.current = setInterval( () => setLastRefresh( new Date() ), intervalMs );
    }
    return () => { if ( timerRef.current ) clearInterval( timerRef.current ); };
  }, [ isAutoRefresh, intervalMs ] );

  const refresh = useCallback( () => setLastRefresh( new Date() ), [] );
  const toggleAutoRefresh = useCallback( () => setIsAutoRefresh( prev => !prev ), [] );

  return { lastRefresh, isAutoRefresh, refresh, toggleAutoRefresh };
}

interface PageProps { signOut?: () => void; user?: any; }

// ─── Design Tokens ───
const C = {
  bg: '#fff', bgSoft: '#f9fafb', bgDark: '#1a3a2a', lime: '#d1f470', limeDark: '#b8dc5a',
  text: '#374151', textDark: '#1a3a2a', textMuted: '#6b7280', textLight: '#9ca3af',
  border: '#f3f4f6', borderActive: '#d1f470',
  green: '#059669', greenBg: '#f0fdf4', red: '#dc2626', redBg: '#fef2f2',
  amber: '#d97706', amberBg: '#fffbeb', blue: '#2563eb', blueBg: '#eff6ff',
  radius: 13, radiusSm: 10,
};

const pill = ( bg: string, color: string ): React.CSSProperties => ( {
  display: 'inline-block', padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: bg, color,
} );

const card = ( active = false ): React.CSSProperties => ( {
  border: `2px solid ${active ? C.borderActive : C.border}`, borderRadius: C.radius, background: C.bg, padding: 16, transition: 'border-color 0.15s',
} );

const statCard = ( bg: string, color: string ): React.CSSProperties => ( {
  padding: '14px 16px', background: bg, borderRadius: C.radius, border: `2px solid ${C.border}`,
} );

const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: C.textDark, margin: '0 0 12px' };
const label: React.CSSProperties = { fontSize: 10, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em' };
const mono: React.CSSProperties = { fontFamily: 'monospace', fontSize: 12 };

// ─── Tab Definitions ───
const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'flow', label: 'Frontend → Backend' },
  { id: 'backend', label: 'Backend Services' },
  { id: 'database', label: 'Database Tables' },
  { id: 'lambda', label: 'Lambda Functions' },
  { id: 'aws', label: 'AWS Resources' },
  { id: 'aws-tree', label: 'AWS Tree' },
  { id: 'storage', label: 'Storage / Buckets' },
  { id: 'code-map', label: 'Code Map' },
  { id: 'search', label: 'Search' },
  { id: 'env', label: 'Environments' },
  { id: 'logs', label: 'Logs / History' },
  { id: 'deps', label: 'Dependencies' },
  { id: 'risks', label: 'Errors / Gaps' },
  { id: 'improvements', label: 'Improvements' },
  { id: 'lambda-detail', label: 'Lambda Admin' },
  { id: 'code-repo', label: 'Code Repo' },
];

// ─── Data: DynamoDB Tables ───
interface TableDef { name: string; purpose: string; keyFields: string; ttl?: string; usedBy: string; indexes: string; category: string; }
const DB_TABLES: TableDef[] = [
  { name: 'Contact', purpose: 'Contact records with opt-in/allowlist preferences', keyFields: 'contactId', indexes: 'phone, email, bsuid', usedBy: 'contacts, inbound-whatsapp', category: 'Core' },
  { name: 'Message', purpose: 'All inbound/outbound messages across channels', keyFields: 'messageId', ttl: '30d', indexes: 'contactId, whatsappMessageId', usedBy: 'messages-read, messages-delete', category: 'Core' },
  { name: 'BulkJob', purpose: 'Bulk messaging job tracking', keyFields: 'jobId', indexes: '-', usedBy: 'bulk-job-create, bulk-job-control', category: 'Operations' },
  { name: 'BulkRecipient', purpose: 'Individual recipient status per bulk job', keyFields: 'jobId + recipientId', indexes: '-', usedBy: 'bulk-worker', category: 'Operations' },
  { name: 'User', purpose: 'Platform users with RBAC roles', keyFields: 'userId', indexes: 'email', usedBy: 'auth-middleware', category: 'Core' },
  { name: 'MediaFile', purpose: 'WhatsApp media file metadata', keyFields: 'fileId', indexes: 'messageId', usedBy: 'inbound-whatsapp, media-cleanup', category: 'Core' },
  { name: 'DLQMessage', purpose: 'Failed message retry queue', keyFields: 'dlqMessageId', ttl: '7d', indexes: '-', usedBy: 'dlq-replay', category: 'Operations' },
  { name: 'AuditLog', purpose: 'System audit trail', keyFields: 'logId', ttl: '180d', indexes: '-', usedBy: 'all services', category: 'Core' },
  { name: 'AIInteraction', purpose: 'AI query/response logs', keyFields: 'interactionId', indexes: 'messageId', usedBy: 'ai-generate-response, ai-query-kb', category: 'AI' },
  { name: 'RateLimitTracker', purpose: 'Rate limiting counters', keyFields: 'channel + windowStart', ttl: '24h', indexes: '-', usedBy: 'outbound-whatsapp', category: 'Core' },
  { name: 'SystemConfig', purpose: 'System configuration key-value store', keyFields: 'configKey', indexes: '-', usedBy: 'ai-config-management', category: 'Core' },
  { name: 'VoiceCall', purpose: 'Voice call records', keyFields: 'callId', ttl: '90d', indexes: 'contactId, phoneNumber', usedBy: 'outbound-voice', category: 'Voice' },
  { name: 'SmsAws', purpose: 'AWS Pinpoint SMS messages', keyFields: 'messageId', ttl: '90d', indexes: 'contactId, phoneNumber', usedBy: 'sms-aws', category: 'SMS' },
  { name: 'VoiceAws', purpose: 'AWS Pinpoint voice calls', keyFields: 'callId', ttl: '90d', indexes: 'contactId, phoneNumber', usedBy: 'voice-aws', category: 'Voice' },
  { name: 'AirtelSMS', purpose: 'Airtel SMS messages (Sender: WDBEEP)', keyFields: 'messageId', ttl: '90d', indexes: 'contactId, phoneNumber, status', usedBy: 'sms-in', category: 'SMS' },
  { name: 'DLTTemplates', purpose: 'TRAI DLT template registry (live)', keyFields: 'templateId', indexes: '-', usedBy: 'sms-aws', category: 'SMS' },
  { name: 'AirtelC2C', purpose: 'Airtel Click-to-Call records', keyFields: 'callId', ttl: '90d', indexes: 'contactId, fromNumber, toNumber, status', usedBy: 'voice-in-c2c', category: 'Voice' },
  { name: 'VoiceCDR', purpose: 'Airtel voice CDR records', keyFields: 'id', ttl: '90d', indexes: 'vmSessionId, callerNumber, callType', usedBy: 'voice-cdr-read', category: 'Voice' },
  { name: 'OBDCampaign', purpose: 'Airtel OBD campaign records', keyFields: 'id', ttl: '90d', indexes: '-', usedBy: 'voice-in-obd', category: 'Voice' },
  { name: 'ScheduledMessage', purpose: 'Scheduled WhatsApp messages', keyFields: 'scheduledId', indexes: 'contactId, status', usedBy: 'scheduled-messages', category: 'WhatsApp' },
  { name: 'WhatsAppVoice', purpose: 'WhatsApp TTS/audio voice messages', keyFields: 'messageId', ttl: '90d', indexes: 'contactId', usedBy: 'whatsapp-voice', category: 'WhatsApp' },
  { name: 'Payment', purpose: 'Razorpay payment records', keyFields: 'id', indexes: 'paymentId, orderId', usedBy: 'razorpay-webhook, payments-read', category: 'Payments' },
  { name: 'WhatsAppCalling', purpose: 'WhatsApp voice/video call logs', keyFields: 'id', ttl: '90d', indexes: 'callId', usedBy: 'whatsapp-calling', category: 'WhatsApp' },
  { name: 'WhatsAppGroup', purpose: 'WhatsApp Business group tracking', keyFields: 'id', indexes: 'groupId, wabaId', usedBy: 'waba-management', category: 'WhatsApp' },
  { name: 'WhatsAppInbound', purpose: 'Inbound WhatsApp messages', keyFields: 'id', ttl: '30d', indexes: 'contactId, whatsappMessageId', usedBy: 'inbound-whatsapp-handler', category: 'WhatsApp' },
  { name: 'WhatsAppOutbound', purpose: 'Outbound WhatsApp messages', keyFields: 'id', ttl: '30d', indexes: 'contactId, whatsappMessageId, templateName', usedBy: 'outbound-whatsapp', category: 'WhatsApp' },
  { name: 'WixProductsCache', purpose: 'Cached Wix Store products', keyFields: 'productId', indexes: '-', usedBy: 'wix-store', category: 'Ecommerce' },
  { name: 'WixOrdersCache', purpose: 'Cached Wix Store orders', keyFields: 'orderId', indexes: 'buyerEmail, paymentStatus, orderNumber', usedBy: 'wix-store', category: 'Ecommerce' },
  { name: 'TemplateAnalytics', purpose: 'WhatsApp template send/delivery tracking', keyFields: 'id', indexes: 'templateName', usedBy: 'template-analytics', category: 'WhatsApp' },
  { name: 'SubmitRequest', purpose: 'WhatsApp Flow submit request submissions', keyFields: 'id', indexes: 'phone, orderId, paymentStatus, paymentReferenceId', usedBy: 'inbound-whatsapp-handler', category: 'Payments' },
  { name: 'ConversationHistory', purpose: 'AI conversation context per phone hash', keyFields: 'phoneHash', indexes: '-', usedBy: 'ai-generate-response', category: 'AI' },
  { name: 'WixOrderId', purpose: 'Wix order ID to WD-ORD number mapping', keyFields: 'wixOrderId', indexes: 'wdOrderNumber', usedBy: 'wix-store', category: 'Ecommerce' },
  { name: 'FlowRegistry', purpose: 'WhatsApp Flow config registry (type, payment, screens, A/B)', keyFields: 'flowId', indexes: 'flowCode, wabaId, category, status', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'FlowSubmission', purpose: 'All flow submissions (generic, all flow types)', keyFields: 'submissionId', indexes: 'phone, flowCode, paymentStatus, paymentRefId, submissionNumber, status, orderId, flowId', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'FlowLog', purpose: 'Audit trail for every flow screen interaction', keyFields: 'logId', ttl: '90d', indexes: 'phone, flowId, flowCode', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'Invoice', purpose: 'Invoice records', keyFields: 'invoiceId', indexes: 'contactId, status', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceItem', purpose: 'Invoice line items', keyFields: 'invoiceId + itemId', indexes: '-', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceAsset', purpose: 'Invoice generated assets (PNG/PDF)', keyFields: 'assetId', indexes: 'invoiceId', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceDeliveryLog', purpose: 'Invoice delivery tracking (WhatsApp/email)', keyFields: 'id', indexes: 'invoiceId', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceSequence', purpose: 'Auto-increment invoice number per FY', keyFields: 'fy', indexes: '-', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoicePayment', purpose: 'Invoice payment tracking', keyFields: 'id', indexes: 'invoiceId', usedBy: 'invoice-engine, razorpay-webhook', category: 'Payments' },
  { name: 'WixOrderMapping', purpose: 'Wix order to contact mapping', keyFields: 'id', indexes: '-', usedBy: 'wix-store', category: 'Ecommerce' },
  { name: 'AdClickAttribution', purpose: 'Click-to-WhatsApp ad tracking', keyFields: 'id', ttl: '180d', indexes: 'adId, contactId', usedBy: 'ad-attribution', category: 'Analytics' },
  { name: 'MetaAnalyticsLog', purpose: 'Meta conversation analytics logs', keyFields: 'id', indexes: '-', usedBy: 'meta-analytics', category: 'Analytics' },
  { name: 'RazorpayWebhookLog', purpose: 'Razorpay webhook event log', keyFields: 'id', ttl: '180d', indexes: 'paymentId, eventType', usedBy: 'razorpay-webhook', category: 'Payments' },
  { name: 'WebhookDedup', purpose: 'Webhook idempotency tracking', keyFields: 'eventId', ttl: '7d', indexes: '-', usedBy: 'inbound-whatsapp-handler', category: 'Core' },
  { name: 'SystemEvent', purpose: 'Persistent system event log', keyFields: 'id', ttl: '180d', indexes: 'eventType, wabaId', usedBy: 'system-cleanup', category: 'Core' },
  { name: 'CatalogCache', purpose: 'WhatsApp Commerce catalog cache', keyFields: 'id', ttl: '7d', indexes: 'catalogId, retailerId', usedBy: 'catalog-management', category: 'Ecommerce' },
];

// ─── Data: Lambda Functions ───
interface LambdaDef { name: string; category: string; trigger: string; tables: string; description: string; apiRoute: string; }
const LAMBDAS: LambdaDef[] = [
  { name: 'contacts', category: 'Core', trigger: 'API Gateway', tables: 'Contact, WhatsAppInbound, WhatsAppOutbound', description: 'Contact CRUD operations', apiRoute: '/workspace/contacts' },
  { name: 'auth-middleware', category: 'Core', trigger: 'API GW Authorizer', tables: 'User', description: 'Cognito token validation', apiRoute: '/auth' },
  { name: 'messages-read', category: 'Core', trigger: 'API Gateway', tables: 'WhatsAppInbound, WhatsAppOutbound', description: 'Read messages from all channels', apiRoute: '/messages' },
  { name: 'messages-delete', category: 'Core', trigger: 'API Gateway', tables: 'WhatsAppInbound, WhatsAppOutbound', description: 'Delete messages by ID', apiRoute: '/messages/{id}' },
  { name: 'faq-handler', category: 'Core', trigger: 'API Gateway', tables: 'SystemConfig', description: 'FAQ auto-response engine', apiRoute: '/faq' },
  { name: 'url-shortener', category: 'Core', trigger: 'API Gateway', tables: '-', description: 'Short link creation (wecare.digital/r)', apiRoute: '/workspace/link' },
  { name: 'inbound-whatsapp-handler', category: 'Messaging', trigger: 'API GW Webhook', tables: 'WhatsAppInbound, Contact, MediaFile, WebhookDedup', description: 'Process incoming WhatsApp messages', apiRoute: '/webhook/whatsapp' },
  { name: 'outbound-whatsapp', category: 'Messaging', trigger: 'API Gateway, SQS', tables: 'WhatsAppOutbound', description: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send' },
  { name: 'outbound-sms', category: 'Messaging', trigger: 'API Gateway', tables: 'Messages', description: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send' },
  { name: 'outbound-email', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Send email via Amazon SES', apiRoute: '/email/send' },
  { name: 'outbound-voice', category: 'Messaging', trigger: 'API Gateway', tables: 'VoiceCall', description: 'Initiate voice calls', apiRoute: '/voice/call' },
  { name: 'sms-aws', category: 'Messaging', trigger: 'API GW, SNS', tables: 'SmsAws', description: 'AWS Pinpoint SMS handler', apiRoute: '/sms-aws' },
  { name: 'sms-in', category: 'Messaging', trigger: 'API GW Webhook', tables: 'AirtelSMS', description: 'Airtel inbound SMS webhook', apiRoute: '/webhook/sms-in' },
  { name: 'voice-aws', category: 'Messaging', trigger: 'API Gateway', tables: 'VoiceAws', description: 'AWS voice call handler', apiRoute: '/voice-aws' },
  { name: 'voice-in', category: 'Messaging', trigger: 'API GW Webhook', tables: 'AirtelC2C, VoiceCDR', description: 'Airtel voice webhooks (C2C + OBD + CDR)', apiRoute: '/webhook/voice-*' },
  { name: 'voice-cdr-read', category: 'Messaging', trigger: 'API Gateway', tables: 'VoiceCDR', description: 'Read voice CDR records', apiRoute: '/voice-cdr' },
  { name: 'whatsapp-calling', category: 'Messaging', trigger: 'API GW Webhook', tables: 'WhatsAppCalling', description: 'WhatsApp voice/video call handling', apiRoute: '/whatsapp-calling' },
  { name: 'whatsapp-voice', category: 'Messaging', trigger: 'API Gateway', tables: 'WhatsAppVoice', description: 'WhatsApp voice note processing', apiRoute: '/whatsapp-voice' },
  { name: 'whatsapp-templates', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Template CRUD via Meta API', apiRoute: '/whatsapp/templates' },
  { name: 'whatsapp-template-management', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Advanced template operations', apiRoute: '/whatsapp/template-mgmt' },
  { name: 'whatsapp-business-api', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Direct Meta Cloud API operations', apiRoute: '/whatsapp/api' },
  { name: 'scheduled-messages', category: 'Messaging', trigger: 'API GW, EventBridge', tables: 'ScheduledMessage', description: 'Schedule messages at specific times', apiRoute: '/scheduled' },
  { name: 'template-analytics', category: 'Messaging', trigger: 'API Gateway', tables: 'TemplateAnalytics', description: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics' },
  { name: 'waba-management', category: 'Messaging', trigger: 'API Gateway', tables: 'WhatsAppGroup', description: 'WABA config and phone management', apiRoute: '/waba' },
  { name: 'meta-analytics', category: 'Messaging', trigger: 'API Gateway', tables: 'MetaAnalyticsLog', description: 'Meta conversation analytics', apiRoute: '/meta-analytics' },
  { name: 'media-cleanup', category: 'Messaging', trigger: 'EventBridge Daily', tables: 'MediaFile', description: 'Clean up expired media from S3', apiRoute: '-' },
  { name: 'ad-attribution', category: 'Messaging', trigger: 'API Gateway', tables: 'AdClickAttribution', description: 'Click-to-WhatsApp ad tracking', apiRoute: '/ad-attribution' },
  { name: 'push-notifications', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Web push notification delivery', apiRoute: '/push' },
  { name: 'ai-generate-response', category: 'AI', trigger: 'API Gateway', tables: 'ConversationHistory, AIInteraction', description: 'Generate AI responses via Bedrock', apiRoute: '/ai/generate' },
  { name: 'ai-query-kb', category: 'AI', trigger: 'API Gateway', tables: 'AIInteraction', description: 'Query Bedrock Knowledge Base', apiRoute: '/ai/query' },
  { name: 'ai-config-management', category: 'AI', trigger: 'API Gateway', tables: 'SystemConfig', description: 'Manage AI/bot configuration', apiRoute: '/ai/config' },
  { name: 'agent-action-group', category: 'AI', trigger: 'Bedrock Agent', tables: '-', description: 'Bedrock Agent action group handler', apiRoute: '-' },
  { name: 'razorpay-webhook', category: 'Payments', trigger: 'API GW Webhook', tables: 'RazorpayWebhookLog, Payment, InvoicePayment', description: 'Razorpay payment webhook', apiRoute: '/webhook/razorpay' },
  { name: 'payments-read', category: 'Payments', trigger: 'API Gateway', tables: 'Payment', description: 'Read payment records', apiRoute: '/payments' },
  { name: 'invoice-engine', category: 'Payments', trigger: 'API Gateway', tables: 'Invoice, InvoiceItem, InvoiceAsset, InvoicePayment, InvoiceDeliveryLog, InvoiceSequence', description: 'Invoice creation & PDF generation', apiRoute: '/invoices' },
  { name: 'bulk-job-create', category: 'Operations', trigger: 'API Gateway', tables: 'BulkJob, BulkRecipient', description: 'Create bulk messaging jobs', apiRoute: '/bulk/create' },
  { name: 'bulk-job-control', category: 'Operations', trigger: 'API Gateway', tables: 'BulkJob', description: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control' },
  { name: 'bulk-worker', category: 'Operations', trigger: 'SQS', tables: 'BulkRecipient', description: 'Process bulk message queue items', apiRoute: '-' },
  { name: 'dlq-replay', category: 'Operations', trigger: 'API Gateway', tables: 'DLQMessage', description: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay' },
  { name: 'system-cleanup', category: 'Operations', trigger: 'EventBridge Daily', tables: 'SystemEvent', description: 'TTL cleanup and maintenance', apiRoute: '-' },
  { name: 'billing', category: 'Operations', trigger: 'API GW, EventBridge', tables: '-', description: 'AWS billing and usage tracking', apiRoute: '/billing' },
  { name: 'wix-store', category: 'Ecommerce', trigger: 'API Gateway', tables: 'WixProductsCache, WixOrdersCache, WixOrderMapping', description: 'Wix ecommerce integration', apiRoute: '/store/wix' },
  { name: 'catalog-management', category: 'Ecommerce', trigger: 'API Gateway', tables: 'CatalogCache', description: 'WhatsApp catalog sync', apiRoute: '/catalog' },
  { name: 'product-image-gen', category: 'Ecommerce', trigger: 'API Gateway', tables: '-', description: 'AI product image generation', apiRoute: '/store/image-gen' },
];

// ─── Data: AWS Resources ───
interface AWSResource { name: string; type: string; purpose: string; module: string; env: string; status: string; risk: string; }
const AWS_RESOURCES: AWSResource[] = [
  { name: 'us-east-1_cSx0RHCIR', type: 'Cognito User Pool', purpose: 'User authentication & RBAC', module: 'Auth', env: 'Production', status: 'Active', risk: '' },
  { name: 'us-east-1:471c2c38-...', type: 'Cognito Identity Pool', purpose: 'Federated identity for AWS access', module: 'Auth', env: 'Production', status: 'Active', risk: '' },
  { name: 'wecare.digital/api', type: 'API Gateway (REST)', purpose: 'Main API endpoint for all Lambda functions', module: 'All', env: 'Production', status: 'Active', risk: '' },
  { name: 'wecare-digital-get', type: 'S3 Bucket', purpose: 'Media storage, invoices, voice, static assets (o/ public, secure/ gated)', module: 'Storage', env: 'Production', status: 'Active', risk: '' },
  { name: DB_TABLES.length + ' DynamoDB Tables', type: 'DynamoDB', purpose: 'Primary database (PAY_PER_REQUEST)', module: 'Data', env: 'Production', status: 'Active', risk: '' },
  { name: '42 Lambda Functions', type: 'Lambda', purpose: 'Backend compute (Python 3.12)', module: 'Backend', env: 'Production', status: 'Active', risk: '' },
  { name: 'stack-wecare-digital-bulk-queue', type: 'SQS Queue', purpose: 'Bulk message job processing', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'stack-wecare-digital-inbound-dlq', type: 'SQS DLQ', purpose: 'Failed inbound message processing', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'stack-wecare-digital-bulk-dlq', type: 'SQS DLQ', purpose: 'Failed bulk message chunks', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'stack-wecare-digital-outbound-dlq', type: 'SQS DLQ', purpose: 'Failed outbound messages', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudWatch Logs (42 groups)', type: 'CloudWatch', purpose: 'Lambda function logs (90d retention)', module: 'Monitoring', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudWatch Alarms', type: 'CloudWatch', purpose: 'Lambda error rate, DLQ depth alerts', module: 'Monitoring', env: 'Production', status: 'Active', risk: '' },
  { name: 'EventBridge Rules', type: 'EventBridge', purpose: 'Scheduled triggers (cleanup, billing, scheduled-messages)', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon SES', type: 'SES', purpose: 'Outbound email delivery', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon Pinpoint', type: 'Pinpoint', purpose: 'SMS delivery (AWS channel)', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon Bedrock', type: 'Bedrock', purpose: 'AI response generation (Claude 3 Sonnet)', module: 'AI', env: 'Production', status: 'Active', risk: '' },
  { name: 'Bedrock Knowledge Base', type: 'Bedrock KB', purpose: 'FAQ and knowledge base queries', module: 'AI', env: 'Production', status: 'Active', risk: '' },
  { name: 'Bedrock Agent', type: 'Bedrock Agent', purpose: 'Autonomous agent with action groups', module: 'AI', env: 'Production', status: 'Active', risk: '' },
  { name: 'IAM Roles (Lambda)', type: 'IAM', purpose: 'Lambda execution roles with least-privilege', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'Secrets Manager', type: 'Secrets Manager', purpose: 'API keys, webhook secrets, payment credentials', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudFront E2GP22R4BIFGQ3', type: 'CloudFront', purpose: 'Serves wecare.digital/get/<key> from wecare-digital-get', module: 'Frontend', env: 'Production', status: 'Active', risk: '' },
  { name: 'Route 53', type: 'Route 53', purpose: 'DNS for wecare.digital, wecare.digital/api, r.wecare.digital', module: 'Networking', env: 'Production', status: 'Active', risk: '' },
  { name: 'ACM Certificates', type: 'ACM', purpose: 'SSL/TLS certificates for all domains', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'SNS Topics', type: 'SNS', purpose: 'SMS delivery notifications, alerts', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon Polly', type: 'Polly', purpose: 'Text-to-speech for WhatsApp voice messages', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
];

// ─── Data: Risks & Improvements ───
interface RiskItem { id: string; title: string; description: string; priority: 'Critical' | 'Important' | 'Nice to have'; category: string; }
const RISKS: RiskItem[] = [
  // ── CRITICAL (13) — 7 FIXED ──
  { id: 'R1', title: '✅ FIXED — Browser payment password removed', description: 'Payment UI now verifies the signed-in Cognito Admin role through the live auth API; owning payment mutations require server-side authorization.', priority: 'Critical', category: 'Security' },
  { id: 'R2', title: '✅ FIXED — PayU credentials removed from source', description: 'Removed hardcoded PAYU_CLIENT_ID, PAYU_CLIENT_SECRET, PAYU_MERCHANT_KEY, PAYU_MERCHANT_SALT from payu-webhook/resource.ts and handler.py. All now require env vars. STILL NEEDED: Rotate credentials since they were in git history.', priority: 'Critical', category: 'Security' },
  { id: 'R3', title: '✅ FIXED — Airtel API key removed from comments', description: 'Removed literal Airtel HMAC signing key and app ID from c2c/handler.py comments. Now references Secrets Manager. STILL NEEDED: Rotate the key since it was in git history.', priority: 'Critical', category: 'Security' },
  { id: 'R3b', title: '✅ FIXED — PayU merchant key/salt removed', description: 'Removed PAYU_MERCHANT_KEY and PAYU_MERCHANT_SALT hardcoded defaults from payu-webhook/resource.ts. STILL NEEDED: Rotate credentials.', priority: 'Critical', category: 'Security' },
  { id: 'R4', title: '✅ FIXED — Razorpay/PayU IDs removed from source', description: 'Removed hardcoded Razorpay MID, UPI VPA, PayU MID, PayU UPI VPA from whatsapp-business-api/handler.py and outbound-whatsapp/handler.py. Also redacted from dashboard/index.tsx UI display.', priority: 'Critical', category: 'Security' },
  { id: 'R5', title: '✅ FIXED — AWS Account ID fallback removed', description: 'Removed hardcoded 775261844268 fallback from constants.ts. Now defaults to empty string if env var missing. Still exposed via NEXT_PUBLIC_ prefix — needs env var rename.', priority: 'Critical', category: 'Security' },
  { id: 'R6', title: 'Internal Lambda Function URL exposed in client', description: 'NEXT_PUBLIC_INTERNAL_AGENT_URL contains a direct Lambda Function URL. It bypasses API Gateway entirely, so stage and per-route throttling and the handler auth path do not apply. Route through API Gateway instead. (Earlier wording blamed "WAF protection" — the API never had a WAF, because WAFv2 cannot attach to an HTTP API, and as of 2026-09-28 there is no WAF in the account at all.)', priority: 'Critical', category: 'Security' },
  { id: 'R7', title: 'Primary WABA phone blocked by Meta rate limit', description: 'Primary phone +91 93309 94400 has pendingRegistration: true. All traffic falls to secondary phone. If secondary fails, messaging is completely down.', priority: 'Critical', category: 'WhatsApp' },
  { id: 'R8', title: 'No staging or dev environment', description: 'Only production environment detected. All development and testing happens against live production data.', priority: 'Critical', category: 'Infrastructure' },
  { id: 'R9', title: 'No CI/CD pipeline', description: 'No GitHub Actions or CodePipeline found. Amplify builds 85-88 all fail with "Artifacts base directory not found." Deployments are manual.', priority: 'Critical', category: 'DevOps' },
  { id: 'R10', title: 'PEM private key files in workspace root', description: 'lightsail_default_key.pem and lightsail_key.pem exist in the workspace root. While .gitignore excludes *.pem, these files are a risk.', priority: 'Critical', category: 'Security' },
  { id: 'R11', title: '✅ FIXED — Wix Account ID fallback removed', description: 'Removed hardcoded WIX_ACCOUNT_ID fallback from wix-store/resource.ts and shared/config.ts. Also redacted from dashboard/index.tsx UI display.', priority: 'Critical', category: 'Security' },
  { id: 'R12', title: '✅ FIXED — CORS wildcard replaced with specific origins', description: 'Replaced allowOrigins: ["*"] with 4 specific origins in amplify/link-resources.ts.', priority: 'Critical', category: 'Security' },

  // ── IMPORTANT (18) ──
  { id: 'R13', title: 'Silent error swallowing in 15+ catch blocks', description: 'Found 15+ empty catch blocks (catch {}, catch(() => {})) across whatsapp/scripts.tsx, auto-response.tsx, flow-responses.tsx, pay/flow/index.tsx, contacts/index.tsx, dashboard/index.tsx. Failed API calls and config loads are silently ignored, making debugging impossible.', priority: 'Important', category: 'Frontend' },
  { id: 'R14', title: 'No automated tests in entire codebase', description: 'Zero test files found (no *.test.ts, *.spec.ts, *.test.py). Only one test file exists (tests/test_response.py for CORS utils). Payment flows, webhook handlers, and auth middleware have no test coverage.', priority: 'Important', category: 'Quality' },
  { id: 'R15', title: 'Lambda functions deployed outside Amplify', description: '42 Python Lambda functions are deployed separately and not managed by Amplify Gen 2. backend.ts explicitly states "Lambda functions are deployed separately and already exist in AWS." Risk of infrastructure drift between code and deployed state.', priority: 'Important', category: 'Infrastructure' },
  { id: 'R16', title: 'DynamoDB TTL not enforced on all temporal tables', description: 'Tables like TemplateAnalytics, AdClickAttribution, MetaAnalyticsLog, FlowSubmission, FlowLog have no TTL configured despite storing temporal data. These will grow unbounded over time.', priority: 'Important', category: 'Database' },
  { id: 'R17', title: 'No backup strategy documented', description: 'DynamoDB point-in-time recovery status unknown for 41 tables. S3 versioning on wecare-digital-get is SUSPENDED (measured 2026-09-29), so an overwrite or delete in o/ is not recoverable from the bucket itself. No documented disaster recovery plan.', priority: 'Important', category: 'Infrastructure' },
  { id: 'R18', title: 'Missing API documentation', description: 'No OpenAPI/Swagger spec found. API endpoints are only documented in scattered code comments and the lambda-functions admin page. New developers have no API reference.', priority: 'Important', category: 'Documentation' },
  { id: 'R19', title: 'Amplify builds failing repeatedly', description: 'Build logs 85-88 all show the same error: "CustomerError: Artifacts base directory not found in build output." The Amplify Hosting build pipeline is broken and has been failing since at least March 29, 2026.', priority: 'Important', category: 'DevOps' },
  { id: 'R20', title: '✅ FIXED — dangerouslySetInnerHTML removed from PageShell', description: 'Replaced dangerouslySetInnerHTML with safe React text rendering in PageShell.tsx. XSS vector eliminated.', priority: 'Important', category: 'Security' },
  { id: 'R21', title: '✅ FIXED — PayU MID removed from all files', description: 'Removed hardcoded PayU MID "8629516" from handler.py, resource.ts, dashboard/index.tsx, whatsapp-business-api/handler.py, outbound-whatsapp/handler.py. All now use env vars.', priority: 'Important', category: 'Configuration' },
  { id: 'R22', title: '✅ FIXED — Hardcoded GSTIN removed from constants.ts', description: 'Removed the hardcoded DEFAULT_GSTIN fallback. Now defaults to empty string if env var missing.', priority: 'Important', category: 'Security' },
  { id: 'R23', title: '✅ FIXED — Calling verification token server-side only', description: 'The browser export and all reveal/copy controls were removed. Meta verification remains in the calling Lambda.', priority: 'Important', category: 'Security' },
  { id: 'R24', title: 'Secrets Manager references not validated at startup', description: 'Lambda functions reference 5 Secrets Manager entries (meta-system-user-token, flow-private-key, airtel/c2c, airtel/sms, airtel/obd) but there is no startup validation. If a secret is missing, the function fails at runtime.', priority: 'Important', category: 'Backend' },
  { id: 'R25', title: 'react-router-dom potentially unused', description: 'react-router-dom ^7.13.0 is installed but Next.js has built-in routing. This adds ~45KB to the bundle. Verify if it is actually used or can be removed.', priority: 'Important', category: 'Dependencies' },
  { id: 'R26', title: '✅ FIXED — @capacitor/cli moved out of production dependencies', description: 'Recorded here as cosmetic install weight, it turned out to have a security consequence: @capacitor/cli was the only path by which xcode@3.0.1 → uuid@7.0.3 entered the production tree, and a Dependabot security update for uuid then failed because no update path could reach the patched 14.0.0 (aws-amplify pins uuid ^11.1.1, xcode pins ^7.0.3). The CLI is now a devDependency, so the production tree resolves only uuid@11.1.1. The same move was applied to the --save list in deps-upgrade.yml, without which the next full-latest run would have reverted it. The advisory itself (GHSA-w5hq-g745-h8pq) is not reachable here: it affects only the v3/v5/v6 APIs with a caller-supplied buffer, and every consumer in this tree imports only v4.', priority: 'Important', category: 'Dependencies' },
  { id: 'R27', title: 'No input validation on frontend forms', description: 'Contact forms, payment forms, and GSTIN inputs have maxLength but no regex validation. Invalid data can reach the backend.', priority: 'Important', category: 'Frontend' },
  { id: 'R28', title: '✅ FIXED — Cognito OAuth domain no longer depends on our own DNS or certificate', description: 'Moved from the signin.wecare.digital custom domain to the Cognito-provided prefix domain, which AWS operates. The prefix domain was upgraded to managed login v2 first so the sign-in page is unchanged. This removes the ACM-certificate and Route 53 single point of failure for all authentication.', priority: 'Important', category: 'Auth' },
  { id: 'R29', title: 'GA and FB tracking IDs empty', description: 'NEXT_PUBLIC_GA_MEASUREMENT_ID and NEXT_PUBLIC_FB_APP_ID are empty. Analytics scripts still load (googletagmanager, connect.facebook.net) but send no data — wasted bandwidth and privacy concern.', priority: 'Important', category: 'Configuration' },
  { id: 'R30', title: '✅ FIXED — Client password comparison removed', description: 'Edit and payment gates use Cognito Admin verification; no shared unlock password is evaluated in browser code.', priority: 'Important', category: 'Security' },

  // ── NICE TO HAVE (8) ──
  { id: 'R31', title: 'Single region deployment (us-east-1)', description: 'All resources in us-east-1 (Virginia). For an India-focused service, ap-south-1 (Mumbai) would provide 50-100ms lower latency for all API calls.', priority: 'Nice to have', category: 'Infrastructure' },
  { id: 'R32', title: 'No rate limiting on frontend API calls', description: 'Frontend API client (src/api/client.ts) has retry logic but no client-side rate limiting or request deduplication. Rapid clicks can flood the backend.', priority: 'Nice to have', category: 'Frontend' },
  { id: 'R33', title: 'No service worker cache strategy', description: 'Service worker registered in _app.tsx but sw.js implementation unknown. No offline-first strategy for the PWA.', priority: 'Nice to have', category: 'Frontend' },
  { id: 'R34', title: 'Duplicate data across InfraTab and system-architecture', description: 'AWS resource data, secrets list, and table definitions exist in both dashboard/tabs/InfraTab.tsx and admin/system-architecture.tsx. Should be a single source of truth.', priority: 'Nice to have', category: 'Code Quality' },
  { id: 'R35', title: 'No request tracing across Lambda functions', description: 'No X-Ray or OpenTelemetry tracing configured. Debugging cross-function issues requires manual CloudWatch log correlation.', priority: 'Nice to have', category: 'Monitoring' },
  { id: 'R36', title: 'No feature flags system', description: 'No feature flag mechanism found. All features are either fully deployed or not. Risky for gradual rollouts.', priority: 'Nice to have', category: 'DevOps' },
  { id: 'R37', title: 'No WebSocket for real-time messaging', description: 'Frontend polls for new messages. No API Gateway WebSocket or AppSync subscription for real-time delivery.', priority: 'Nice to have', category: 'Frontend' },
  { id: 'R38', title: 'lodash and fast-xml-parser pinned via overrides', description: 'package.json uses overrides to pin lodash@4.17.21 and fast-xml-parser@5.3.4 for security. These overrides need periodic review as new CVEs emerge.', priority: 'Nice to have', category: 'Dependencies' },
];

const IMPROVEMENTS: RiskItem[] = [
  // ── CRITICAL (5) ──
  { id: 'I1', title: '✅ DONE — Removed all hardcoded secrets from source', description: 'Removed PayU client ID/secret/key/salt from payu-webhook. Removed Razorpay MID/UPI and PayU MID/UPI from whatsapp-business-api and outbound-whatsapp. Removed Airtel API key from c2c comments. Removed Wix Account ID fallback. Removed Razorpay live API key from dashboard UI. Removed all credential displays from dashboard/index.tsx. STILL NEEDED: Rotate all leaked credentials and audit git history.', priority: 'Critical', category: 'Security' },
  { id: 'I2', title: '✅ DONE — Redacted all credentials from dashboard UI', description: 'Removed Razorpay live API key (server-side Razorpay key), key secret partial, PayU API key/salt/client ID/secret, PayU MID, and Wix Account ID from dashboard/index.tsx. All now show masked placeholders referencing env vars or Secrets Manager.', priority: 'Critical', category: 'Security' },
  { id: 'I3', title: 'Add staging environment', description: 'Create a separate staging stack with isolated DynamoDB tables (stack-staging-*), S3 prefix (staging/), and Lambda aliases. Use Amplify branch-based environments or a separate AWS account.', priority: 'Critical', category: 'Infrastructure' },
  { id: 'I4', title: 'Fix Amplify build pipeline', description: 'Build logs 85-88 all fail with "Artifacts base directory not found." Fix the buildSpec to point to the correct output directory (out/ for static export). This is blocking all automated deployments.', priority: 'Critical', category: 'DevOps' },
  { id: 'I5', title: 'Implement CI/CD pipeline', description: 'Set up GitHub Actions with: lint → type-check → test → build → deploy-staging → smoke-test → deploy-production. Add branch protection rules requiring passing checks before merge.', priority: 'Critical', category: 'DevOps' },

  // ── IMPORTANT (12) ──
  { id: 'I6', title: 'Add automated tests for critical paths', description: 'Priority test targets: (1) auth-middleware token validation, (2) razorpay-webhook signature verification, (3) inbound-whatsapp message processing, (4) payment flow end-to-end, (5) contact CRUD. Use pytest for Lambda, Vitest for frontend.', priority: 'Important', category: 'Quality' },
  { id: 'I7', title: 'Enable DynamoDB point-in-time recovery', description: 'Enable PITR on critical tables: Contact, Payment, Invoice, InvoicePayment, User, SystemConfig. Cost is minimal (~$0.20/GB/month) but provides 35-day recovery window.', priority: 'Important', category: 'Database' },
  { id: 'I8', title: 'Add TTL to remaining temporal tables', description: 'Add expiresAt/ttl fields and TTL configuration to: TemplateAnalytics, AdClickAttribution, FlowSubmission, FlowLog, WixProductsCache, WixOrdersCache. Prevents unbounded table growth.', priority: 'Important', category: 'Database' },
  { id: 'I9', title: 'Generate OpenAPI spec for all endpoints', description: 'Document all 30+ API endpoints with OpenAPI 3.0. Include request/response schemas, auth requirements, error codes. Publish at /api/docs for developer customer-service.', priority: 'Important', category: 'Documentation' },
  { id: 'I10', title: '✅ DONE — Removed dangerouslySetInnerHTML from PageShell', description: 'Replaced dangerouslySetInnerHTML={{__html: tab.icon}} with safe React text rendering {tab.icon} in src/components/PageShell.tsx. XSS vector eliminated.', priority: 'Important', category: 'Security' },
  { id: 'I11', title: 'Add error handling to all empty catch blocks', description: 'Replace 15+ empty catch blocks with proper error logging. At minimum: console.error for dev, toast.error for user-facing, and structured logging for production monitoring. Files: whatsapp/scripts.tsx, auto-response.tsx, flow-responses.tsx, pay/flow/index.tsx, contacts/index.tsx, dashboard/index.tsx.', priority: 'Important', category: 'Frontend' },
  { id: 'I12', title: '✅ DONE — Fixed CORS wildcard on URL shortener API', description: 'Replaced allowOrigins: ["*"] with an explicit origin list in amplify/link-resources.ts. Now ["https://wecare.digital", "https://www.wecare.digital"] — the subdomain in the original fix was dropped when that hostname was retired.', priority: 'Important', category: 'Security' },
  { id: 'I12b', title: '✅ DONE — Added security headers to next.config.js', description: 'Added X-Content-Type-Options: nosniff, X-Frame-Options: DENY, X-XSS-Protection, Referrer-Policy: strict-origin-when-cross-origin, and Permissions-Policy headers to next.config.js.', priority: 'Important', category: 'Security' },
  { id: 'I13', title: 'Add Lambda startup validation for Secrets Manager', description: 'Add a validate_secrets() function that runs on cold start to verify all required Secrets Manager entries exist and have expected keys. Fail fast with clear error messages.', priority: 'Important', category: 'Backend' },
  { id: 'I14', title: 'Add health check endpoint', description: 'Create /health endpoint that validates: DynamoDB connectivity, S3 bucket access, Secrets Manager access, external API reachability (Meta, Razorpay, Airtel). Return structured status for monitoring.', priority: 'Important', category: 'Operations' },
  { id: 'I15', title: 'Remove or conditionally load analytics scripts', description: 'GA and FB scripts load on every page but IDs are empty. Either configure the IDs or remove the Script tags to save bandwidth and improve privacy compliance.', priority: 'Important', category: 'Frontend' },
  { id: 'I16', title: 'Add frontend input validation', description: 'Add regex validation for: phone numbers (E.164), email addresses, GSTIN (15-char alphanumeric), PIN codes (6 digits). Validate before API calls to reduce backend load.', priority: 'Important', category: 'Frontend' },
  { id: 'I17', title: 'Add request tracing with X-Ray', description: 'Enable AWS X-Ray on all Lambda functions and API Gateway. Add correlation IDs to requests for end-to-end tracing across the 42-function architecture.', priority: 'Important', category: 'Monitoring' },

  // ── NICE TO HAVE (8) ──
  { id: 'I18', title: 'Migrate to ap-south-1 (Mumbai)', description: 'All resources are in us-east-1. For an India-focused service, Mumbai region would reduce API latency by 50-100ms. Plan a phased migration starting with new resources.', priority: 'Nice to have', category: 'Infrastructure' },
  { id: 'I19', title: 'Add WebSocket for real-time messaging', description: 'Replace polling with API Gateway WebSocket or AppSync subscriptions for real-time message delivery. Reduces API calls and improves UX for the inbox.', priority: 'Nice to have', category: 'Frontend' },
  { id: 'I20', title: 'Implement feature flags', description: 'Add a feature flag system (SystemConfig table or LaunchDarkly) for safe rollouts. Priority flags: payment features, AI auto-response, new channels.', priority: 'Nice to have', category: 'DevOps' },
  { id: 'I21', title: 'Consolidate duplicate data sources', description: 'AWS resource data exists in both InfraTab.tsx and system-architecture.tsx. Create a single shared data module (src/data/architecture.ts) imported by both.', priority: 'Nice to have', category: 'Code Quality' },
  { id: 'I22', title: 'Add structured JSON logging to all Lambdas', description: 'Replace print() statements with structured JSON logging using a shared logger. Include request_id, function_name, duration, and error details for CloudWatch Insights queries.', priority: 'Nice to have', category: 'Monitoring' },
  { id: 'I23', title: '✅ DONE — @capacitor/cli is a devDependency', description: 'See R26. Done for a stronger reason than install size: it was the only route by which a vulnerable transitive uuid reached the production dependency tree.', priority: 'Nice to have', category: 'Dependencies' },
  { id: 'I24', title: 'Evaluate react-router-dom necessity', description: 'react-router-dom ^7.13.0 is installed but Next.js provides built-in routing. If not used, removing it saves ~45KB from the bundle.', priority: 'Nice to have', category: 'Dependencies' },
  { id: 'I25', title: 'Add PWA offline strategy', description: 'Implement a proper service worker cache strategy: cache-first for static assets, network-first for API calls, with offline fallback pages.', priority: 'Nice to have', category: 'Frontend' },
];

// ─── Data: Dependencies ───
interface DepInfo { name: string; version: string; type: 'prod' | 'dev'; status: 'ok' | 'outdated' | 'warning'; note: string; }
const DEPENDENCIES: DepInfo[] = [
  { name: '@aws-amplify/backend', version: '^1.8.0', type: 'prod', status: 'ok', note: 'Core Amplify Gen 2 backend' },
  { name: '@aws-amplify/ui-react', version: '^6.12.0', type: 'prod', status: 'ok', note: 'Amplify UI components (Authenticator)' },
  { name: 'aws-amplify', version: '^6.14.0', type: 'prod', status: 'ok', note: 'Amplify client library' },
  { name: 'next', version: '^16.1.6', type: 'prod', status: 'ok', note: 'Next.js framework' },
  { name: 'react', version: '^19.2.4', type: 'prod', status: 'ok', note: 'React 19 (latest)' },
  { name: 'react-dom', version: '^19.2.4', type: 'prod', status: 'ok', note: 'React DOM renderer' },
  { name: 'react-router-dom', version: '^7.13.0', type: 'prod', status: 'warning', note: 'Potentially unused — Next.js has built-in routing' },
  { name: 'flag-icons', version: '^7.5.0', type: 'prod', status: 'ok', note: 'Country flag icons' },
  { name: '@capacitor/core', version: '^8.2.0', type: 'prod', status: 'ok', note: 'Capacitor mobile framework' },
  { name: '@capacitor/android', version: '^8.2.0', type: 'prod', status: 'ok', note: 'Android native bridge' },
  { name: '@capacitor/ios', version: '^8.2.0', type: 'prod', status: 'ok', note: 'iOS native bridge' },
  { name: '@capacitor/cli', version: '^8.4.1', type: 'dev', status: 'ok', note: 'Build tool; dev-only so xcode/uuid@7 stays out of the production tree' },
  { name: '@capacitor/app', version: '^8.0.1', type: 'prod', status: 'ok', note: 'App lifecycle plugin' },
  { name: '@capacitor/browser', version: '^8.0.2', type: 'prod', status: 'ok', note: 'In-app browser plugin' },
  { name: '@capacitor/haptics', version: '^8.0.1', type: 'prod', status: 'ok', note: 'Haptic feedback plugin' },
  { name: '@capacitor/keyboard', version: '^8.0.1', type: 'prod', status: 'ok', note: 'Keyboard management plugin' },
  { name: '@capacitor/push-notifications', version: '^8.0.2', type: 'prod', status: 'ok', note: 'Push notification plugin' },
  { name: '@capacitor/splash-screen', version: '^8.0.1', type: 'prod', status: 'ok', note: 'Splash screen plugin' },
  { name: '@capacitor/status-bar', version: '^8.0.1', type: 'prod', status: 'ok', note: 'Status bar plugin' },
  { name: 'typescript', version: '^5.9.3', type: 'dev', status: 'ok', note: 'TypeScript compiler' },
  { name: '@types/node', version: '^24.3.0', type: 'dev', status: 'ok', note: 'Node.js type definitions' },
  { name: '@types/react', version: '^19.2.10', type: 'dev', status: 'ok', note: 'React type definitions' },
  { name: 'lodash (override)', version: '4.17.21', type: 'prod', status: 'ok', note: 'Security override — pinned version' },
  { name: 'fast-xml-parser (override)', version: '5.3.4', type: 'prod', status: 'ok', note: 'Security override — pinned version' },
];

// ─── Data: Storage Paths ───
interface StoragePath { path: string; purpose: string; readBy: string; writtenBy: string; }
// Every path below carries its root segment, and that is not cosmetic. These rows used
// to read `stack/...` and `stream/...`, which is one level ABOVE where the data actually
// lives — the same defect `.github/workflows/media-prefixes.yml` exists to catch. It went
// unnoticed for two days in the handlers because a key at the bucket root still returned
// HTTP 200 from the apex host, so addressing the wrong level errored nowhere.
const STORAGE_PATHS: StoragePath[] = [
  { path: 'o/stack/whatsapp-media/incoming/', purpose: 'Inbound WhatsApp media files', readBy: 'messages-read, contacts', writtenBy: 'inbound-whatsapp-handler' },
  { path: 'o/stack/whatsapp-media/outgoing/', purpose: 'Outbound WhatsApp media files', readBy: 'messages-read', writtenBy: 'outbound-whatsapp' },
  { path: 'o/stack/whatsapp-media/voice/', purpose: 'WhatsApp voice notes', readBy: 'whatsapp-voice', writtenBy: 'inbound-whatsapp-handler' },
  { path: 'o/stack/whatsapp-media/calling-ai/', purpose: 'WhatsApp calling recordings', readBy: 'whatsapp-calling', writtenBy: 'whatsapp-calling' },
  { path: 'o/stack/whatsapp-media/template-headers/', purpose: 'Template header media', readBy: 'whatsapp-templates', writtenBy: 'whatsapp-template-management' },
  { path: 'o/stack/whatsapp-media/downloads/', purpose: 'User-initiated media downloads', readBy: 'Frontend', writtenBy: 'messages-read' },
  { path: 'secure/stack/invoices/', purpose: 'Invoice PNGs and PDFs — gated: a rendered invoice carries the customer name, address, amount and GST breakdown, so it is served by presigned URL rather than from the unauthenticated o/ tree', readBy: 'invoice-engine (presigned), system-cleanup', writtenBy: 'invoice-engine, inbound-whatsapp-handler' },
  { path: 'o/stack/voice/', purpose: 'Voice recordings', readBy: 'voice-cdr-read', writtenBy: 'voice-in' },
  { path: 'o/stack/reports/', purpose: 'Bulk job reports and exports', readBy: 'Frontend', writtenBy: 'bulk-worker' },
  { path: 'o/stack/store/products/', purpose: 'Product images', readBy: 'catalog-management, Frontend', writtenBy: 'product-image-gen' },
  { path: 'o/stream/media/m/', purpose: 'Logos, branding images (static)', readBy: 'Frontend (CDN)', writtenBy: 'Manual upload' },
  { path: 'o/stream/media/fonts/', purpose: 'Invoice PDF fonts', readBy: 'invoice-engine', writtenBy: 'Manual upload' },
  { path: 'o/stream/media/ivr/', purpose: 'IVR audio files', readBy: 'voice-in-obd', writtenBy: 'Manual upload' },
  { path: 'o/stream/docs/', purpose: 'Scraped documentation (Markdown)', readBy: 'Frontend, meta-business-agent', writtenBy: 'docs-scraper' },
  { path: 'o/public/wa-tpl/', purpose: 'Template media named by Meta-APPROVED templates — do not move or rename', readBy: 'Meta (refetch at send time)', writtenBy: 'whatsapp-template-management' },
  { path: 'o/whatsapp-media/whatsapp-calling/', purpose: 'IVR greeting audio (TTS)', readBy: 'whatsapp-calling', writtenBy: 'whatsapp-calling' },
  { path: 'secure/u/', purpose: 'Gated: upload as received — presigned access only', readBy: 'Presigned URL', writtenBy: 'document upload' },
  { path: 'secure/d/', purpose: 'Gated: deliverable rendition — presigned access only', readBy: 'Presigned URL', writtenBy: 'document pipeline' },
];

// ─── Data: Environment Config ───
interface EnvVar { key: string; value: string; sensitive: boolean; category: string; risk?: string; }
const ENV_VARS: EnvVar[] = [
  // Auth
  { key: 'NEXT_PUBLIC_COGNITO_USER_POOL_ID', value: 'us-east-1_cSx0RHCIR', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_CLIENT_ID', value: '1j8kbi48m4v2rped3n224rlevb', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID', value: 'us-east-1:471c2c38-5645-4ccd-aea1-7a008e906db5', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_OAUTH_DOMAIN', value: 'wecare-digital-auth.auth.us-east-1.amazoncognito.com', sensitive: false, category: 'Auth' },
  // App
  { key: 'NEXT_PUBLIC_APP_URL', value: 'https://wecare.digital/', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_API_BASE', value: 'https://wecare.digital/api', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_SEND_MODE', value: 'LIVE', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_ENV', value: 'production', sensitive: false, category: 'App' },
  // ⚠️ SECRETS EXPOSED IN CLIENT BUNDLE
  { key: 'NEXT_PUBLIC_INTERNAL_AGENT_URL', value: '(Lambda Function URL — bypasses API Gateway)', sensitive: true, category: 'AI', risk: 'Direct Lambda URL exposed in browser, bypasses API Gateway throttling and the handler auth path' },
  { key: 'NEXT_PUBLIC_AWS_ACCOUNT_ID', value: '775261844268', sensitive: true, category: 'AWS', risk: 'AWS Account ID exposed in client bundle' },
  { key: 'NEXT_PUBLIC_AWS_REGION', value: 'us-east-1', sensitive: false, category: 'AWS' },
  { key: 'NEXT_PUBLIC_PAYMENT_UNLOCK_PASSWORD', value: '(plaintext password in JS bundle)', sensitive: true, category: 'Payment', risk: 'CRITICAL: Password shipped to every browser' },
  { key: 'NEXT_PUBLIC_DEFAULT_GSTIN', value: '(real business tax ID in code)', sensitive: true, category: 'Payment', risk: 'Real GSTIN hardcoded as fallback in constants.ts' },
  // Payment
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_ID', value: 'phone-number-id-waba-t-direct-1055232054343117', sensitive: false, category: 'Payment' },
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_DISPLAY', value: '+91 93309 94400', sensitive: false, category: 'Payment' },
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_NAME', value: 'WECARE.DIGITAL', sensitive: false, category: 'Payment' },
  // Analytics (empty)
  // CORRECTED 2026-09-30. This row read `G-S3G6REP6Q7` and presented it as live config on a
  // staff dashboard. It is not live and is not set anywhere: the Amplify branch env vars have
  // no NEXT_PUBLIC_GA_MEASUREMENT_ID at all, and the live GTM container (GTM-TXZ8JT78, version
  // 6, read through the Tag Manager API) serves only G-GNRPFFBXMF and AW-18396505964. Fetching
  // the live container JS agrees - zero occurrences of G-S3G6REP6Q7.
  //
  // The id was real once. `_app.tsx` records a direct gtag.js snippet that fired it alongside
  // the container, double-counting every pageview; the snippet was removed and the id went with
  // it. This row survived and kept asserting a value the platform had stopped using, which is
  // the specific failure this dashboard causes when it hardcodes config: a reader trusts it
  // instead of measuring, and then looks for analytics data in a property that receives none.
  { key: 'NEXT_PUBLIC_GA_MEASUREMENT_ID', value: '(unset — GA4 is fired by GTM-TXZ8JT78 as G-GNRPFFBXMF)', sensitive: false, category: 'Analytics', risk: 'Was listed as G-S3G6REP6Q7, which is retired and in no container' },
  { key: 'NEXT_PUBLIC_FB_APP_ID', value: '(empty — SDK still loads)', sensitive: false, category: 'Analytics', risk: 'FB SDK loads but sends no data' },
  // Payment identifiers — env-sourced (RAZORPAY_MID / RAZORPAY_UPI_ID), not secrets. A merchant
  // id and a UPI payee address are public by construction (they appear in every deep link and QR).
  // Authoritative values owner-confirmed 2026-09-30 against the live Meta config; the earlier
  // [retired Razorpay account] / @icici pair was stale and has been retired.
  { key: 'Razorpay MID (env RAZORPAY_MID)', value: 'acc_TTFSyolquKEZEy', sensitive: false, category: 'Payments — Identifier', risk: 'Non-secret merchant id; matched against Meta config by payment_readiness' },
  { key: 'Razorpay UPI VPA (env RAZORPAY_UPI_ID)', value: 'wecaredigitalbh511413.rzp@rxairtel', sensitive: false, category: 'Payments — Identifier', risk: 'Non-secret UPI payee address (public in deep links/QR)' },
  { key: 'Airtel API Key (in comment)', value: '(visible in c2c/handler.py comment)', sensitive: true, category: 'Voice — Hardcoded', risk: 'CRITICAL: Airtel HMAC key in code comment' },
  { key: 'Airtel App ID (hardcoded)', value: '(in c2c handler + data schema)', sensitive: true, category: 'Voice — Hardcoded', risk: 'Airtel App ID in multiple files' },
  { key: 'WIX_ACCOUNT_ID (current Headless account)', value: '478bf907-96cc-4cab-9220-bb96f1d35cbb', sensitive: false, category: 'Ecommerce — Identifier', risk: 'Current non-secret Wix Headless account identifier' },
  // Secrets Manager entries (server-side, properly stored)
  { key: 'wecare/meta-system-user-token', value: '(Secrets Manager — 7 keys)', sensitive: true, category: 'Secrets Manager ✓' },
  { key: 'wecare/flow-private-key', value: '(Secrets Manager — 1 key)', sensitive: true, category: 'Secrets Manager ✓' },
  { key: '3 retired-provider credentials', value: '(Secrets Manager — no remaining reader; pending destructive-approval deletion)', sensitive: true, category: 'Secrets Manager ✓' },
];

// ─── Data: Frontend Routes ───
interface FrontendRoute { path: string; label: string; backend: string; tables: string; }
const FRONTEND_ROUTES: FrontendRoute[] = [
  // Dashboard
  { path: '/workspace/dashboard', label: 'Dashboard Overview', backend: 'billing, meta-analytics', tables: 'MetaAnalyticsLog' },
  { path: '/workspace/dashboard/system-architecture', label: 'Project Control Center', backend: '(this page)', tables: '-' },
  { path: '/workspace/dashboard/lambda-functions', label: 'Lambda Functions', backend: '(static data)', tables: '-' },
  { path: '/workspace/dashboard/code-repo', label: 'Code Repo', backend: '(static data)', tables: '-' },
  // WhatsApp
  { path: '/workspace/engage/whatsapp', label: 'WhatsApp Inbox', backend: 'messages-read, inbound-whatsapp, outbound-whatsapp', tables: 'WhatsAppInbound, WhatsAppOutbound, Contact' },
  { path: '/workspace/engage/whatsapp/templates', label: 'WA Templates', backend: 'whatsapp-templates, whatsapp-template-management', tables: 'TemplateAnalytics' },
  { path: '/workspace/engage/whatsapp/campaign', label: 'WA Campaign', backend: 'outbound-whatsapp, bulk-job-create', tables: 'BulkJob, BulkRecipient, WhatsAppOutbound' },
  { path: '/workspace/engage/whatsapp/flows', label: 'WA Flows', backend: 'whatsapp-business-api', tables: 'FlowRegistry, FlowSubmission' },
  { path: '/workspace/engage/whatsapp/flow-hub', label: 'WA Flow Hub', backend: 'whatsapp-business-api', tables: 'FlowRegistry, FlowSubmission, FlowLog' },
  { path: '/workspace/engage/whatsapp/flow-responses', label: 'WA Flow Responses', backend: 'inbound-whatsapp-handler', tables: 'FlowSubmission, FlowLog, SubmitRequest' },
  { path: '/workspace/engage/whatsapp/calling', label: 'WA Calling', backend: 'whatsapp-calling', tables: 'WhatsAppCalling' },
  { path: '/workspace/engage/whatsapp/groups', label: 'WA Groups', backend: 'waba-management', tables: 'WhatsAppGroup' },
  { path: '/workspace/engage/whatsapp/interactive-lists', label: 'WA Interactive Lists', backend: 'outbound-whatsapp', tables: '-' },
  { path: '/workspace/engage/whatsapp/scripts', label: 'WA Scripts', backend: 'outbound-whatsapp', tables: '-' },
  { path: '/workspace/engage/whatsapp/welcome', label: 'WA Welcome', backend: 'outbound-whatsapp', tables: 'Contact' },
  { path: '/workspace/engage/whatsapp/auto-response', label: 'WA Auto Response', backend: 'ai-generate-response, ai-config-management', tables: 'ConversationHistory, SystemConfig' },
  { path: '/workspace/engage/whatsapp/ai-config', label: 'WA AI Config', backend: 'ai-config-management', tables: 'SystemConfig' },
  { path: '/workspace/engage/whatsapp/waba-dashboard', label: 'WABA Dashboard', backend: 'waba-management, meta-analytics', tables: 'MetaAnalyticsLog' },
  { path: '/workspace/engage/whatsapp/business-profile', label: 'WA Business Profile', backend: 'whatsapp-business-api', tables: '-' },
  { path: '/workspace/engage/whatsapp/webhooks', label: 'WA Webhooks', backend: 'inbound-whatsapp-handler', tables: 'WebhookDedup, SystemEvent' },
  { path: '/workspace/engage/whatsapp/migration', label: 'WA Migration', backend: 'waba-management', tables: '-' },
  { path: '/workspace/engage/logs', label: 'Message Logs (all channels)', backend: 'messages-read', tables: 'MessagesTable' },
  { path: '/workspace/engage/whatsapp/settings', label: 'WA Settings', backend: 'waba-management', tables: 'SystemConfig' },
  // SMS
  { path: '/workspace/engage/sms', label: 'SMS', backend: 'outbound-sms, sms-aws', tables: 'SmsAws, DLTTemplates, AirtelSMS (read-only history)' },
  // Voice
  { path: '/workspace/engage/voice', label: 'Voice Out', backend: 'outbound-voice, voice-aws', tables: 'VoiceCall, VoiceAws' },
  { path: '/workspace/engage/voice-in', label: 'Voice In', backend: 'voice-in, voice-cdr-read', tables: 'AirtelC2C, VoiceCDR, OBDCampaign' },
  // Email / RCS / Push
  { path: '/workspace/engage/ses', label: 'Email', backend: 'outbound-email', tables: '-' },
  { path: '/workspace/engage/rcs', label: 'RCS', backend: '(planned)', tables: '-' },
  { path: '/workspace/engage/push', label: 'Push', backend: 'push-notifications', tables: '-' },
  { path: '/workspace/engage/logs', label: 'Message Logs', backend: 'messages-read', tables: 'WhatsAppInbound, WhatsAppOutbound, SmsAws' },
  // Pay
  { path: '/workspace/pay', label: 'Payments', backend: 'payments-read, razorpay-webhook, invoice-engine', tables: 'Payment, Invoice, InvoiceItem, RazorpayWebhookLog' },
  { path: '/workspace/pay/flow', label: 'Pay Flow', backend: 'invoice-engine, razorpay-webhook', tables: 'Invoice, InvoiceItem, InvoicePayment, InvoiceDeliveryLog' },

  // Other
  { path: '/workspace/contacts', label: 'Contacts', backend: 'contacts', tables: 'Contact' },
  { path: '/workspace/commerce/catalog', label: 'Store', backend: 'wix-store, catalog-management, product-image-gen', tables: 'WixProductsCache, WixOrdersCache, CatalogCache, WixOrderId' },
  { path: '/workspace/access', label: 'Access Control', backend: 'auth-middleware', tables: 'User' },
  { path: '/workspace/link', label: 'URL Shortener', backend: 'url-shortener', tables: '-' },
  // '/workspace/link/create' ("Create Link") was listed here. Removed 2026-09-25 with the page: a
  // ComingSoon stub naming four features, never in the nav, and this row was its only
  // reference in the repo.
  { path: '/workspace/forms', label: 'Forms', backend: 'whatsapp-business-api', tables: 'FlowRegistry' },
  { path: '/workspace/forms/' + 'self' + 'service', label: 'Customer Service Hub', backend: 'whatsapp-business-api, inbound-whatsapp-handler', tables: 'FlowRegistry, FlowSubmission, FlowLog, SubmitRequest' },
  // Was '[retired public path]'. The public page was deleted on owner instruction; the faq-handler backend
  // and SystemConfig table are unchanged and are driven from the dashboard route.
  { path: '/workspace/engage/faq', label: 'FAQ', backend: 'faq-handler', tables: 'SystemConfig' },
  { path: '/grahak-os', label: 'Grahak OS', backend: '(public product page)', tables: '-' },
  // '/studio' REMOVED on owner instruction. The slug is retired and no page exists for it
  // in src/pages, so listing it here described a route that 404s - and this table is read
  // as the map of what the system actually serves. Header.test.tsx separately guards
  // "Studio" out of the public menu.
  { path: '/workspace/task', label: 'Task', backend: '(coming soon)', tables: '-' },
];

// ─── Data: Code Map ───
interface CodeFolder { path: string; purpose: string; files: string; linkedTo: string; }
const CODE_MAP: CodeFolder[] = [
  { path: 'src/pages/', purpose: 'Next.js page routes (Pages Router)', files: '~50 pages', linkedTo: 'Frontend routing' },
  { path: 'src/pages/workspace/dashboard/', purpose: 'Dashboard + Admin + Control Center', files: '6 pages', linkedTo: '/workspace/dashboard/*' },
  { path: 'src/pages/workspace/engage/whatsapp/', purpose: 'WhatsApp messaging pages (21 sub-pages)', files: '21 pages', linkedTo: '/workspace/engage/whatsapp/*' },
  { path: 'src/pages/workspace/engage/', purpose: 'Multi-channel messaging (SMS, Voice, Email, RCS, Push)', files: '~15 pages', linkedTo: '/workspace/engage/*' },
  { path: 'src/pages/workspace/pay/', purpose: 'Payment pages (overview, flow, link)', files: '3 pages', linkedTo: '/workspace/pay/*' },
  { path: 'src/pages/workspace/link/', purpose: 'URL shortener (list, create, logs)', files: '3 pages', linkedTo: '/workspace/link/*' },
  { path: 'src/components/', purpose: 'Reusable UI components', files: '~25 components', linkedTo: 'All pages' },
  { path: 'src/components/ui/', purpose: 'Base UI primitives (Button, Modal, Tabs, Table)', files: '~10 components', linkedTo: 'All pages' },
  { path: 'src/components/dashboard/', purpose: 'Dashboard-specific widgets', files: '~5 components', linkedTo: '/workspace/dashboard' },
  { path: 'src/api/client.ts', purpose: 'API service layer with retry logic', files: '1 file', linkedTo: 'API Gateway → Lambda' },
  { path: 'src/config/constants.ts', purpose: 'App constants (AWS, payment, WhatsApp config)', files: '1 file', linkedTo: 'All services' },
  { path: 'src/config/navigation.ts', purpose: 'Sidebar navigation configuration', files: '1 file', linkedTo: 'Layout' },
  { path: 'src/contexts/', purpose: 'React contexts (Toast, Confirm)', files: '2 files', linkedTo: 'All pages' },
  { path: 'src/hooks/', purpose: 'Custom hooks (keyboard, notifications, WebRTC)', files: '~3 files', linkedTo: 'Various pages' },
  { path: 'src/styles/', purpose: 'CSS modules and design tokens', files: '~8 files', linkedTo: 'All components' },
  { path: 'amplify/auth/', purpose: 'Cognito auth configuration', files: '1 file', linkedTo: 'Cognito User Pool' },
  // "49 tables" was wrong in both directions: the file declares 58 models and the
  // account holds 77 tables. It is a data-model document, not the deployed schema
  // — there are 0 AppSync APIs, so none of its models exist as tables. See the
  // header of amplify/data/resource.ts.
  { path: 'amplify/data/', purpose: 'Data model document — 58 models, 0 deployed', files: '1 file', linkedTo: 'DynamoDB' },
  { path: 'amplify/storage/', purpose: 'S3 storage + SQS queue config', files: '1 file', linkedTo: 'S3, SQS' },
  { path: 'amplify/functions/ai/', purpose: 'AI Lambda functions (4)', files: '4 dirs', linkedTo: 'Bedrock, DynamoDB' },
  { path: 'amplify/functions/core/', purpose: 'Core Lambda functions (6)', files: '6 dirs', linkedTo: 'DynamoDB, S3' },
  { path: 'amplify/functions/messaging/', purpose: 'Messaging Lambda functions (22)', files: '22 dirs', linkedTo: 'DynamoDB, S3, SQS, SES, Pinpoint' },
  { path: 'amplify/functions/payments/', purpose: 'Payment Lambda functions (3)', files: '3 dirs', linkedTo: 'DynamoDB, Razorpay' },
  { path: 'amplify/functions/operations/', purpose: 'Operations Lambda functions (6)', files: '6 dirs', linkedTo: 'DynamoDB, SQS, EventBridge' },
  { path: 'amplify/functions/ecommerce/', purpose: 'Ecommerce Lambda functions (3)', files: '3 dirs', linkedTo: 'DynamoDB, S3, Wix API' },
  { path: 'amplify/functions/shared/', purpose: 'Shared utilities and config', files: '3 files', linkedTo: 'All Lambda functions' },
];

// ─── Data: Lambda Detailed (with env vars, runtime, memory) ───
interface LambdaDetailed { name: string; displayName: string; category: string; runtime: string; timeout: number; memory: number; description: string; apiRoute: string; envVars: Record<string, string>; triggers: string[]; status: 'active' | 'warning' | 'error'; }
const LAMBDA_DETAILED: LambdaDetailed[] = [
  { name: 'wecare-contacts', displayName: 'Contacts', category: 'Core', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'CRUD operations for contacts', apiRoute: '/workspace/contacts', envVars: { CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-auth-middleware', displayName: 'Auth Middleware', category: 'Core', runtime: 'Python 3.12', timeout: 10, memory: 128, description: 'Cognito token validation for API Gateway', apiRoute: '/auth', envVars: { USER_POOL_ID: 'us-east-1_*', CLIENT_ID: '*' }, triggers: [ 'API Gateway Authorizer' ], status: 'active' },
  { name: 'wecare-messages-read', displayName: 'Messages Read', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'Read messages from all channels', apiRoute: '/messages', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-messages-delete', displayName: 'Messages Delete', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Delete messages by ID', apiRoute: '/messages/{id}', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-faq-handler', displayName: 'FAQ Handler', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'FAQ auto-response engine', apiRoute: '/faq', envVars: { FAQ_TABLE: 'stack-wecare-digital-FAQTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-url-shortener', displayName: 'URL Shortener', category: 'Core', runtime: 'Python 3.12', timeout: 10, memory: 128, description: 'Short link creation and redirect', apiRoute: '/workspace/link', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-inbound-whatsapp', displayName: 'Inbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 512, description: 'Process incoming WhatsApp messages, media, reactions', apiRoute: '/webhook/whatsapp', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-outbound-whatsapp', displayName: 'Outbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send', envVars: { OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway', 'SQS' ], status: 'active' },
  { name: 'wecare-outbound-sms', displayName: 'Outbound SMS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send', envVars: { MESSAGES_TABLE: 'stack-wecare-digital-MessagesTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-outbound-email', displayName: 'Outbound Email', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send email via Amazon SES', apiRoute: '/email/send', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-outbound-voice', displayName: 'Outbound Voice', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Initiate voice calls', apiRoute: '/voice/call', envVars: { VOICE_TABLE: 'stack-wecare-digital-VoiceCallTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-calling', displayName: 'WhatsApp Calling', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'WhatsApp voice/video call handling', apiRoute: '/whatsapp-calling', envVars: { CALLING_TABLE: 'stack-wecare-digital-WhatsAppVoiceTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-scheduled-messages', displayName: 'Scheduled Messages', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Schedule and send messages at specific times', apiRoute: '/scheduled', envVars: { SCHEDULED_TABLE: 'stack-wecare-digital-ScheduledMessageTable' }, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },
  { name: 'wecare-bulk-worker', displayName: 'Bulk Worker', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 512, description: 'Process bulk message queue items', apiRoute: '-', envVars: { QUEUE_URL: 'stack-wecare-digital-bulk-queue' }, triggers: [ 'SQS' ], status: 'active' },
  { name: 'wecare-ai-generate-response', displayName: 'AI Generate Response', category: 'AI', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Generate AI responses via Bedrock', apiRoute: '/ai/generate', envVars: { BEDROCK_MODEL_ID: 'anthropic.claude-3-sonnet' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-razorpay-webhook', displayName: 'Razorpay Webhook', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Razorpay payment webhook handler', apiRoute: '/webhook/razorpay', envVars: { WEBHOOK_SECRET: '(env var)', PAYMENTS_TABLE: 'stack-wecare-digital-RazorpayWebhookLogTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-invoice-engine', displayName: 'Invoice Engine', category: 'Payments', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Invoice creation, PDF generation, payment links', apiRoute: '/invoices', envVars: { INVOICE_TABLE: 'stack-wecare-digital-InvoiceTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-wix-store', displayName: 'Wix Store', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Wix ecommerce integration', apiRoute: '/store/wix', envVars: { WIX_API_KEY: '(env var)', WIX_SITE_ID: '(env var)' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-catalog-management', displayName: 'Catalog Management', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WhatsApp Commerce catalog sync', apiRoute: '/catalog', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-product-image-gen', displayName: 'Product Image Gen', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'AI product image generation via Bedrock', apiRoute: '/store/image-gen', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-voice', displayName: 'WhatsApp Voice', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'TTS voice notes via Polly, audio processing', apiRoute: '/whatsapp-voice', envVars: { VOICE_TABLE: 'stack-wecare-digital-WhatsAppVoiceTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-templates', displayName: 'WhatsApp Templates', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Template CRUD via Meta Graph API', apiRoute: '/whatsapp/templates', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-template-mgmt', displayName: 'Template Management', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Advanced template operations', apiRoute: '/whatsapp/template-mgmt', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-business-api', displayName: 'WhatsApp Business API', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Meta Graph API wrapper — flows, payments, checkout', apiRoute: '/whatsapp/api', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-waba-management', displayName: 'WABA Management', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WABA config, phone management, groups', apiRoute: '/waba', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-sms-aws', displayName: 'SMS AWS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS Pinpoint SMS handler', apiRoute: '/sms-aws', envVars: { SMS_TABLE: 'stack-wecare-digital-SmsAwsTable' }, triggers: [ 'API Gateway', 'SNS' ], status: 'active' },
  // `wecare-sms-in` REMOVED 2026-09-25. Listed with `status: 'active'` and route
  // `/webhook/sms-in`; measured against the account, neither the function nor the
  // route exists, and Airtel is a retired provider. Inbound SMS is not received.
  { name: 'wecare-voice-aws', displayName: 'Voice AWS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS voice call handler', apiRoute: '/voice-aws', envVars: { VOICE_TABLE: 'stack-wecare-digital-VoiceAwsTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  // `wecare-voice-in` REMOVED 2026-09-25. Listed with `status: 'active'` and route
  // `/webhook/voice-*`; no such function or route exists. The live functions are
  // `wecare-voice-in-c2c` and `wecare-voice-in-obd`, and their Airtel CDR write path
  // was removed on 2026-09-25 — they serve the operations UI, not a provider webhook.
  { name: 'wecare-voice-cdr-read', displayName: 'Voice CDR Read', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read voice CDR records', apiRoute: '/voice-cdr', envVars: { CDR_TABLE: 'stack-wecare-digital-VoiceCDRTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-template-analytics', displayName: 'Template Analytics', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-meta-analytics', displayName: 'Meta Analytics', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Meta conversation analytics', apiRoute: '/meta-analytics', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-media-cleanup', displayName: 'Media Cleanup', category: 'Messaging', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'Clean up expired media from S3', apiRoute: '-', envVars: { MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'EventBridge Daily' ], status: 'active' },
  { name: 'wecare-ad-attribution', displayName: 'Ad Attribution', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Click-to-WhatsApp ad tracking', apiRoute: '/ad-attribution', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-push-notifications', displayName: 'Push Notifications', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Web push notification delivery', apiRoute: '/push', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-ai-query-kb', displayName: 'AI Query KB', category: 'AI', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'Query Bedrock Knowledge Base', apiRoute: '/ai/query', envVars: { KB_ID: '(env var)' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-ai-config-management', displayName: 'AI Config Management', category: 'AI', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Manage AI/bot configuration', apiRoute: '/ai/config', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-agent-action-group', displayName: 'Agent Action Group', category: 'AI', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Bedrock Agent action group handler', apiRoute: '-', envVars: {}, triggers: [ 'Bedrock Agent' ], status: 'active' },
  { name: 'wecare-payments-read', displayName: 'Payments Read', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read payment records', apiRoute: '/payments', envVars: { PAYMENTS_TABLE: 'stack-wecare-digital-PaymentTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-bulk-job-create', displayName: 'Bulk Job Create', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Create bulk messaging jobs', apiRoute: '/bulk/create', envVars: { BULK_TABLE: 'stack-wecare-digital-BulkJobTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-bulk-job-control', displayName: 'Bulk Job Control', category: 'Operations', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-dlq-replay', displayName: 'DLQ Replay', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-system-cleanup', displayName: 'System Cleanup', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'TTL cleanup and maintenance', apiRoute: '-', envVars: {}, triggers: [ 'EventBridge Daily' ], status: 'active' },
  { name: 'wecare-billing', displayName: 'Billing', category: 'Operations', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS billing and usage tracking', apiRoute: '/billing', envVars: {}, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },
];
const LAMBDA_DETAIL_CATEGORIES = [ 'All', ...Array.from( new Set( LAMBDA_DETAILED.map( l => l.category ) ) ) ];

// ─── Data: Code Repository Assets ───
interface CodeAsset { id: string; category: string; name: string; description: string; path: string; type: string; status?: string; }
const CODE_ASSETS: CodeAsset[] = [
  // WhatsApp Flows
  { id: 'flow-sr', category: 'WhatsApp Flows', name: 'WD_SR_PAY — Submit Request', description: 'Multi-screen flow for order service requests with ₹49 payment.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/submit-request-flow.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-sub', category: 'WhatsApp Flows', name: 'WD Subscribe', description: 'Subscription flow collecting name, phone, email, company, shipping + billing address.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/subscribe-flow.json', type: 'Flow JSON', status: 'Published' },
  // Customer Service Flows (9 WhatsApp Flows triggered from interactive list)
  { id: 'ss-submit', category: 'Customer Service Flows', name: '📋 Submit Request', description: 'Start a new support request with optional ₹49 payment.', path: 'Flow ID: 931522532810297', type: 'WA Flow', status: 'Published' },
  { id: 'ss-track', category: 'Customer Service Flows', name: '🔍 Track Request', description: 'Check the status of an existing request by order ID.', path: 'Flow ID: 973888792200167', type: 'WA Flow', status: 'Draft' },
  { id: 'ss-amend', category: 'Customer Service Flows', name: '✏️ Amend Request', description: 'Edit or correct a previously submitted request.', path: 'Flow ID: 1533536534833353', type: 'WA Flow', status: 'Draft' },
  { id: 'ss-appt', category: 'Customer Service Flows', name: '📅 Appointment', description: 'Schedule a consultation or service visit.', path: 'Flow ID: 1475722977488573', type: 'WA Flow', status: 'Draft' },
  { id: 'ss-rx', category: 'Customer Service Flows', name: '💊 RX Slot', description: 'Schedule a medical tourism or prescription-related visit.', path: 'Flow ID: 1892784521355352', type: 'WA Flow', status: 'Draft' },
  { id: 'ss-docs', category: 'Customer Service Flows', name: '📄 Drop Docs', description: 'Send supporting documents for a request.', path: 'Flow ID: 1737801600902350', type: 'WA Flow', status: 'Draft' },
  { id: 'ss-enterprise', category: 'Customer Service Flows', name: '🏢 Enterprise Assist', description: 'Corporate, B2B, and bulk enquiries.', path: 'Flow ID: 2132515287534606', type: 'WA Flow', status: 'Draft' },
  // REVIEW_FLOW_ID = WD_Leave_Review_v2, PUBLISHED on WABA 1 (verified live 2026-10-08).
  // The id this replaced was not present on the WABA at all, so the 'Draft' status was
  // describing a flow that did not exist. Read from src/lib/reviewEntry.ts, never restated.
  { id: 'ss-review', category: 'Customer Service Flows', name: '⭐ Leave Review', description: 'Share experience and feedback.', path: `Flow ID: ${REVIEW_FLOW_ID}`, type: 'WA Flow', status: 'Published' },
  // path was '[retired public path]' with status 'Active' until 2026-09-25. The public [retired public path] page was
  // deleted on owner instruction, so that link 404'd and "Active" was a false claim in
  // the one table this project treats as its source of truth. The live FAQ surface is the
  // dashboard route below; the customer-facing answer arrives over WhatsApp, not as a page.
  { id: 'ss-faq', category: 'Customer Service Flows', name: '❓ FAQ', description: 'View frequently asked questions.', path: '/workspace/engage/faq', type: 'Page Link', status: 'Active' },
  // Frontend Pages
  { id: 'p-dashboard', category: 'Frontend Pages', name: 'Dashboard Overview', description: 'Main analytics dashboard with billing, conversation metrics.', path: 'src/pages/workspace/dashboard/index.tsx', type: 'Page' },
  { id: 'p-control', category: 'Frontend Pages', name: 'Project Control Center', description: '18-tab system architecture dashboard — single source of truth.', path: 'src/pages/workspace/dashboard/system-architecture.tsx', type: 'Page' },
  { id: 'p-wa-inbox', category: 'Frontend Pages', name: 'WhatsApp Inbox', description: 'Real-time WhatsApp message inbox with contact sidebar.', path: 'src/pages/workspace/engage/whatsapp/index.tsx', type: 'Page' },
  { id: 'p-wa-templates', category: 'Frontend Pages', name: 'WhatsApp Templates', description: 'Template management — create, edit, send, analytics.', path: 'src/pages/workspace/engage/whatsapp/templates.tsx', type: 'Page' },
  { id: 'p-wa-flows', category: 'Frontend Pages', name: 'WhatsApp Flows', description: 'Flow builder and management for WhatsApp Business Flows.', path: 'src/pages/workspace/engage/whatsapp/flows.tsx', type: 'Page' },
  { id: 'p-wa-flowhub', category: 'Frontend Pages', name: 'Flow Hub', description: 'Centralized flow registry, submissions, and analytics.', path: 'src/pages/workspace/engage/whatsapp/flow-hub.tsx', type: 'Page' },
  { id: 'p-wa-calling', category: 'Frontend Pages', name: 'WhatsApp Calling', description: 'Voice/video call logs and WebRTC integration.', path: 'src/pages/workspace/engage/whatsapp/calling.tsx', type: 'Page' },
  { id: 'p-wa-groups', category: 'Frontend Pages', name: 'WhatsApp Groups', description: 'Group management — create, participants, messaging.', path: 'src/pages/workspace/engage/whatsapp/groups.tsx', type: 'Page' },
  { id: 'p-pay', category: 'Frontend Pages', name: 'Payments', description: 'Payment dashboard — Razorpay transactions.', path: 'src/pages/workspace/pay/index.tsx', type: 'Page' },
  { id: 'p-pay-flow', category: 'Frontend Pages', name: 'Pay Flow', description: 'WhatsApp payment flow — invoice + collect via chat.', path: 'src/pages/workspace/pay/flow/index.tsx', type: 'Page' },
  { id: 'p-contacts', category: 'Frontend Pages', name: 'Contacts', description: 'Contact management with opt-in, addresses, BSUID.', path: 'src/pages/workspace/contacts/index.tsx', type: 'Page' },
  { id: 'p-store', category: 'Frontend Pages', name: 'Store', description: 'Wix store integration — products, orders, catalog.', path: 'src/pages/store/index.tsx', type: 'Page' },
  // Core Lambdas
  { id: 'l-auth', category: 'Core Lambdas', name: 'Auth Middleware', description: 'Cognito JWT validation, API Gateway authorizer.', path: 'amplify/functions/core/auth-middleware/handler.py', type: 'Lambda' },
  { id: 'l-contacts', category: 'Core Lambdas', name: 'Contacts', description: 'CRUD for contacts with structured addresses.', path: 'amplify/functions/core/contacts/handler.py', type: 'Lambda' },
  { id: 'l-msg-read', category: 'Core Lambdas', name: 'Messages Read', description: 'Read messages from all channels with media pre-signed URLs.', path: 'amplify/functions/core/messages-read/handler.py', type: 'Lambda' },
  { id: 'l-msg-del', category: 'Core Lambdas', name: 'Messages Delete', description: 'Delete messages by ID from inbound/outbound tables.', path: 'amplify/functions/core/messages-delete/handler.py', type: 'Lambda' },
  { id: 'l-faq', category: 'Core Lambdas', name: 'FAQ Handler', description: 'FAQ auto-response engine from SystemConfig.', path: 'amplify/functions/core/faq-handler/handler.py', type: 'Lambda' },
  { id: 'l-url', category: 'Core Lambdas', name: 'URL Shortener', description: 'Short link creation and redirect (wecare.digital/r; r.wecare.digital retained for links already issued).', path: 'amplify/functions/core/url-shortener/handler.py', type: 'Lambda' },
  // WhatsApp Lambdas
  { id: 'l-inbound', category: 'WhatsApp Lambdas', name: 'Inbound WhatsApp', description: 'Main webhook handler — messages, keyword triggers, flow routing, AI, media.', path: 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py', type: 'Lambda' },
  { id: 'l-outbound', category: 'WhatsApp Lambdas', name: 'Outbound WhatsApp', description: 'Send WhatsApp messages — text, media, interactive, templates, flows.', path: 'amplify/functions/messaging/outbound-whatsapp/handler.py', type: 'Lambda' },
  { id: 'l-wa-biz', category: 'WhatsApp Lambdas', name: 'WhatsApp Business API', description: 'Meta Graph API wrapper — flows, payments, checkout, business profile.', path: 'amplify/functions/messaging/whatsapp-business-api/handler.py', type: 'Lambda' },
  { id: 'l-wa-calling', category: 'WhatsApp Lambdas', name: 'WhatsApp Calling', description: 'Voice/video call webhook handler and SDP relay.', path: 'amplify/functions/messaging/whatsapp-calling/handler.py', type: 'Lambda' },
  { id: 'l-wa-voice', category: 'WhatsApp Lambdas', name: 'WhatsApp Voice', description: 'TTS voice notes via Polly, audio message processing.', path: 'amplify/functions/messaging/whatsapp-voice/handler.py', type: 'Lambda' },
  { id: 'l-wa-tmpl', category: 'WhatsApp Lambdas', name: 'WhatsApp Templates', description: 'Template CRUD via Meta Graph API.', path: 'amplify/functions/messaging/whatsapp-templates/handler.py', type: 'Lambda' },
  { id: 'l-wa-tmpl-mgmt', category: 'WhatsApp Lambdas', name: 'Template Management', description: 'Advanced template operations — clone, analytics, bulk.', path: 'amplify/functions/messaging/whatsapp-template-management/handler.py', type: 'Lambda' },
  { id: 'l-waba', category: 'WhatsApp Lambdas', name: 'WABA Management', description: 'WABA config, phone management, group operations.', path: 'amplify/functions/messaging/waba-management/handler.py', type: 'Lambda' },
  // Messaging Lambdas
  { id: 'l-sms-out', category: 'Messaging Lambdas', name: 'Outbound SMS', description: 'Send SMS via AWS End User Messaging.', path: 'amplify/functions/messaging/outbound-sms/handler.py', type: 'Lambda' },
  { id: 'l-email', category: 'Messaging Lambdas', name: 'Outbound Email', description: 'Send email via Amazon SES.', path: 'amplify/functions/messaging/outbound-email/handler.py', type: 'Lambda' },
  { id: 'l-voice-out', category: 'Messaging Lambdas', name: 'Outbound Voice', description: 'Initiate voice calls. Retired-provider backing; PSTN voice moves to Plivo.', path: 'amplify/functions/messaging/outbound-voice/handler.py', type: 'Lambda' },
  // `l-sms-in` REMOVED 2026-09-25: pointed at
  // `amplify/functions/messaging/sms-in/handler.py`, a path that does not exist.
  // `l-voice-in` REMOVED 2026-09-25: pointed at
  // `amplify/functions/messaging/voice-in/handler.py`, which does not exist. The real
  // sources are `voice-in/c2c/handler.py` and `voice-in/obd/handler.py`.
  { id: 'l-voice-in-c2c', category: 'Messaging Lambdas', name: 'Voice In (C2C)', description: 'Click-to-call operations UI; historical call reads. Airtel CDR write path removed 2026-09-25.', path: 'amplify/functions/messaging/voice-in/c2c/handler.py', type: 'Lambda' },
  { id: 'l-voice-in-obd', category: 'Messaging Lambdas', name: 'Voice In (OBD)', description: 'Outbound-campaign operations UI: text-to-speech and audio library. Campaign creation is retired and answers explicitly.', path: 'amplify/functions/messaging/voice-in/obd/handler.py', type: 'Lambda' },
  { id: 'l-scheduled', category: 'Messaging Lambdas', name: 'Scheduled Messages', description: 'Schedule and send messages at specific times.', path: 'amplify/functions/messaging/scheduled-messages/handler.py', type: 'Lambda' },
  { id: 'l-push', category: 'Messaging Lambdas', name: 'Push Notifications', description: 'Web push notification delivery.', path: 'amplify/functions/messaging/push-notifications/handler.py', type: 'Lambda' },
  // AI
  { id: 'l-ai-gen', category: 'AI', name: 'AI Generate Response', description: 'Generate AI responses using Bedrock Claude — context-aware, multi-turn.', path: 'amplify/functions/ai/ai-generate-response/handler.py', type: 'Lambda' },
  { id: 'l-ai-kb', category: 'AI', name: 'AI Query KB', description: 'Query Bedrock Knowledge Base for FAQ answers.', path: 'amplify/functions/ai/ai-query-kb/handler.py', type: 'Lambda' },
  { id: 'l-ai-config', category: 'AI', name: 'AI Config Management', description: 'Manage AI/bot configuration and auto-reply settings.', path: 'amplify/functions/ai/ai-config-management/handler.py', type: 'Lambda' },
  { id: 'l-ai-agent', category: 'AI', name: 'Agent Action Group', description: 'Bedrock Agent action group handler for autonomous tasks.', path: 'amplify/functions/ai/agent-action-group/handler.py', type: 'Lambda' },
  // Payments
  { id: 'l-razorpay', category: 'Payments', name: 'Razorpay Webhook', description: 'Razorpay payment webhook — capture, refund, dispute events.', path: 'amplify/functions/payments/razorpay-webhook/handler.py', type: 'Lambda' },
  { id: 'l-payments-read', category: 'Payments', name: 'Payments Read', description: 'Read payment records and transaction history.', path: 'amplify/functions/payments/payments-read/handler.py', type: 'Lambda' },
  { id: 'l-invoice', category: 'Payments', name: 'Invoice Engine', description: 'Invoice creation, PDF generation, WhatsApp delivery.', path: 'amplify/functions/payments/invoice-engine/handler.py', type: 'Lambda' },
  // Operations
  { id: 'l-bulk-create', category: 'Operations', name: 'Bulk Job Create', description: 'Create bulk messaging jobs with recipient lists.', path: 'amplify/functions/operations/bulk-job-create/handler.py', type: 'Lambda' },
  { id: 'l-bulk-ctrl', category: 'Operations', name: 'Bulk Job Control', description: 'Pause, resume, cancel bulk jobs.', path: 'amplify/functions/operations/bulk-job-control/handler.py', type: 'Lambda' },
  { id: 'l-bulk', category: 'Operations', name: 'Bulk Worker', description: 'Process bulk job queue — send messages in batches with rate limiting.', path: 'amplify/functions/operations/bulk-worker/handler.py', type: 'Lambda' },
  { id: 'l-dlq', category: 'Operations', name: 'DLQ Replay', description: 'Replay failed messages from dead letter queues.', path: 'amplify/functions/operations/dlq-replay/handler.py', type: 'Lambda' },
  { id: 'l-cleanup', category: 'Operations', name: 'System Cleanup', description: 'TTL cleanup, maintenance, and health checks.', path: 'amplify/functions/operations/system-cleanup/handler.py', type: 'Lambda' },
  { id: 'l-billing', category: 'Operations', name: 'Billing', description: 'AWS billing and usage tracking.', path: 'amplify/functions/operations/billing/handler.py', type: 'Lambda' },
  // Ecommerce
  { id: 'l-wix', category: 'Ecommerce', name: 'Wix Store', description: 'Wix ecommerce integration — order sync, product catalog.', path: 'amplify/functions/ecommerce/wix-store/handler.py', type: 'Lambda' },
  { id: 'l-catalog', category: 'Ecommerce', name: 'Catalog Management', description: 'WhatsApp Commerce catalog sync and product management.', path: 'amplify/functions/ecommerce/catalog-management/handler.py', type: 'Lambda' },
  { id: 'l-img-gen', category: 'Ecommerce', name: 'Product Image Gen', description: 'AI product image generation via Bedrock.', path: 'amplify/functions/ecommerce/product-image-gen/handler.py', type: 'Lambda' },
];
const CODE_ASSET_CATEGORIES = [ 'All', ...Array.from( new Set( CODE_ASSETS.map( a => a.category ) ) ) ];

// ─── Data: WhatsApp Bot Menu (Persistent Menu / Welcome Message) ───
interface BotMenuItem { row: number; section: string; icon: string; title: string; description: string; action: string; }
const BOT_MENU: BotMenuItem[] = [
  { row: 1, section: 'Start Here', icon: '🚀', title: 'Customer Service', description: 'Requests, appointments, documents, and support', action: 'Opens Self-service list' },
  { row: 2, section: 'Start Here', icon: '🔔', title: 'Subscribe for Updates', description: 'Get updates, offers, and service news', action: 'Opens subscribe form' },
  { row: 3, section: 'Start Here', icon: '🆔', title: 'Find Profile ID', description: 'Locate your subscription or profile ID', action: 'Opens ID lookup' },
  { row: 4, section: 'Start Here', icon: '💳', title: 'Make a Payment', description: 'Pay an invoice or complete a pending payment', action: 'Opens payment lookup' },
  { row: 5, section: 'Explore WECARE', icon: '🛍️', title: 'Explore Store', description: 'Browse services, brands, and offers', action: 'CTA link → wecare.digital' },
  { row: 6, section: 'Explore WECARE', icon: '🎁', title: 'Gift Cards', description: 'Send a digital gift card', action: 'CTA link → wecare.digital/perks/' },
  { row: 7, section: 'Explore WECARE', icon: '🇮🇳', title: 'WECARE.DIGITAL', description: 'Discover WECARE.DIGITAL and services', action: 'Info text + evolving services' },
  // The action was 'CTA link → wecare.digital/faq' until the public [retired public path] page was deleted;
  // that URL now 404s, so the row would have sent a WhatsApp user to a dead link. The answer
  // is delivered in chat by faq-handler from SystemConfig instead.
  { row: 8, section: 'Help & Answers', icon: '❓', title: 'FAQs', description: 'Find answers to common questions', action: 'Answered in chat by faq-handler' },
  { row: 9, section: 'Help & Answers', icon: '💛', title: 'About WECARE.DIGITAL', description: 'Learn more about WECARE.DIGITAL', action: 'CTA link → wecare.digital' },
];

// ─── Data: Customer Service Sub-Menu (WhatsApp Flow Interactive List) ───
interface CustomerServiceItem { row: number; section: string; icon: string; title: string; description: string; flowId: string; keywords: string; }
const CUSTOMERSERVICE_MENU: CustomerServiceItem[] = [
  { row: 1, section: 'New Request', icon: '📋', title: 'Submit Request', description: 'Start a new support request', flowId: '931522532810297', keywords: 'submit request, sr, raise request' },
  { row: 2, section: 'Request Status', icon: '🔍', title: 'Track Request', description: 'Check the status of your request', flowId: '973888792200167', keywords: 'track request, track, status' },
  { row: 3, section: 'Existing Request', icon: '✏️', title: 'Amend Request', description: 'Edit or correct a submitted request', flowId: '1533536534833353', keywords: 'amend request, amend, change' },
  { row: 4, section: 'Schedule', icon: '📅', title: 'Appointment', description: 'Schedule a consultation or service visit', flowId: '1475722977488573', keywords: 'appointment, schedule, meeting' },
  { row: 5, section: 'Medical Tourism', icon: '💊', title: 'RX Slot', description: 'Schedule a medical tourism or prescription-related visit', flowId: '1892784521355352', keywords: 'rx slot, rx, prescription' },
  { row: 6, section: 'Documents', icon: '📄', title: 'Drop Docs', description: 'Send supporting documents for your request', flowId: '1737801600902350', keywords: 'drop docs, documents, upload' },
  { row: 7, section: 'Business Support', icon: '🏢', title: 'Enterprise Assist', description: 'Corporate, B2B, and bulk enquiries', flowId: '2132515287534606', keywords: 'enterprise, b2b, corporate' },
  // flowId and keywords mirror DEFAULT_FLOW_TRIGGERS['leave_review'] in the inbound handler,
  // same order, via src/lib/reviewEntry.ts. Guarded by tests/test_leave_review_wiring.py.
  { row: 8, section: 'Feedback', icon: '⭐', title: 'Leave Review', description: 'Share your experience with our service', flowId: REVIEW_FLOW_ID, keywords: REVIEW_ENTRY_KEYWORDS.join(', ') },
  { row: 9, section: 'Help', icon: '❓', title: 'FAQ', description: 'View frequently asked questions', flowId: '-', keywords: 'faq, help, questions' },
];

// ─── Searchable Index ───
interface SearchEntry { type: string; name: string; detail: string; category: string; }
function buildSearchIndex (): SearchEntry[] {
  const entries: SearchEntry[] = [];
  DB_TABLES.forEach( t => entries.push( { type: 'Table', name: t.name, detail: t.purpose, category: t.category } ) );
  LAMBDAS.forEach( l => entries.push( { type: 'Lambda', name: l.name, detail: l.description, category: l.category } ) );
  AWS_RESOURCES.forEach( r => entries.push( { type: 'AWS', name: r.name, detail: r.purpose, category: r.module } ) );
  STORAGE_PATHS.forEach( s => entries.push( { type: 'Storage', name: s.path, detail: s.purpose, category: 'Storage' } ) );
  FRONTEND_ROUTES.forEach( f => entries.push( { type: 'Route', name: f.path, detail: f.label, category: 'Frontend' } ) );
  CODE_MAP.forEach( c => entries.push( { type: 'Code', name: c.path, detail: c.purpose, category: 'Codebase' } ) );
  ENV_VARS.forEach( e => entries.push( { type: 'Env', name: e.key, detail: e.value, category: e.category } ) );
  RISKS.forEach( r => entries.push( { type: 'Risk', name: r.title, detail: r.description, category: r.category } ) );
  IMPROVEMENTS.forEach( i => entries.push( { type: 'Improvement', name: i.title, detail: i.description, category: i.category } ) );
  BOT_MENU.forEach( m => entries.push( { type: 'Bot Menu', name: `${m.icon} ${m.title}`, detail: m.description, category: m.section } ) );
  CUSTOMERSERVICE_MENU.forEach( m => entries.push( { type: 'Customer Service', name: `${m.icon} ${m.title}`, detail: m.description, category: m.section } ) );
  return entries;
}

// ─── Last Scan Timestamp ───
// Dynamic — updated by auto-refresh hook

// ─── Main Component ───
const SystemArchitecturePage: React.FC<PageProps> = ( { signOut, user } ) => {
  const { lastRefresh, isAutoRefresh, refresh, toggleAutoRefresh } = useAutoRefresh( 60000 );
  const LAST_SCAN = lastRefresh.toISOString().slice( 0, 16 ).replace( 'T', ' ' );
  const [ activeTab, setActiveTab ] = useState( 'overview' );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ tableFilter, setTableFilter ] = useState( 'All' );
  const [ lambdaFilter, setLambdaFilter ] = useState( 'All' );
  const [ riskFilter, setRiskFilter ] = useState( 'All' );
  const [ expandedItems, setExpandedItems ] = useState<Set<string>>( new Set() );
  const [ lambdaDetailFilter, setLambdaDetailFilter ] = useState( 'All' );
  const [ lambdaDetailSearch, setLambdaDetailSearch ] = useState( '' );
  const [ codeRepoSearch, setCodeRepoSearch ] = useState( '' );
  const [ codeRepoCategory, setCodeRepoCategory ] = useState( 'All' );
  const [ expandedAsset, setExpandedAsset ] = useState<string | null>( null );

  const toggleExpand = useCallback( ( id: string ) => {
    setExpandedItems( prev => {
      const next = new Set( prev );
      next.has( id ) ? next.delete( id ) : next.add( id );
      return next;
    } );
  }, [] );

  const searchIndex = useMemo( () => buildSearchIndex(), [] );
  const searchResults = useMemo( () => {
    if ( !searchQuery.trim() ) return [];
    const q = searchQuery.toLowerCase();
    return searchIndex.filter( e => e.name.toLowerCase().includes( q ) || e.detail.toLowerCase().includes( q ) || e.category.toLowerCase().includes( q ) );
  }, [ searchQuery, searchIndex ] );

  // Keyboard shortcut: Ctrl+K to jump to search
  useEffect( () => {
    const handler = ( e: KeyboardEvent ) => {
      if ( ( e.ctrlKey || e.metaKey ) && e.key === 'k' )
      {
        e.preventDefault();
        setActiveTab( 'search' );
      }
    };
    window.addEventListener( 'keydown', handler );
    return () => window.removeEventListener( 'keydown', handler );
  }, [] );

  const tableCategories = useMemo( () => [ 'All', ...Array.from( new Set( DB_TABLES.map( t => t.category ) ) ) ], [] );
  const filteredTables = useMemo( () => tableFilter === 'All' ? DB_TABLES : DB_TABLES.filter( t => t.category === tableFilter ), [ tableFilter ] );

  const lambdaCategories = useMemo( () => [ 'All', ...Array.from( new Set( LAMBDAS.map( l => l.category ) ) ) ], [] );
  const filteredLambdas = useMemo( () => lambdaFilter === 'All' ? LAMBDAS : LAMBDAS.filter( l => l.category === lambdaFilter ), [ lambdaFilter ] );

  // ─── Tab Renderers ───
  const renderOverview = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 20 } }>
      {/* Stats Grid */ }
      <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 } }>
        { [
          { label: 'Lambda Functions', value: '42', color: C.greenBg, text: C.green },
          { label: 'DynamoDB Tables', value: `${DB_TABLES.length}`, color: C.blueBg, text: C.blue },
          { label: 'AWS Services', value: `${AWS_RESOURCES.length}`, color: C.amberBg, text: C.amber },
          { label: 'Frontend Routes', value: `${FRONTEND_ROUTES.length}`, color: '#f5f3ff', text: '#7c3aed' },
          { label: 'SQS Queues', value: '4', color: C.greenBg, text: C.green },
          { label: 'S3 Paths', value: `${STORAGE_PATHS.length}`, color: C.blueBg, text: C.blue },
          { label: 'Dependencies', value: `${DEPENDENCIES.length}`, color: C.amberBg, text: C.amber },
          { label: 'Bot Menu Items', value: `${BOT_MENU.length}`, color: '#f5f3ff', text: '#7c3aed' },
          { label: 'Customer Service Flows', value: `${CUSTOMERSERVICE_MENU.length}`, color: C.greenBg, text: C.green },
          { label: 'Risks Found', value: `${RISKS.length}`, color: C.redBg, text: C.red },
        ].map( s => (
          <div key={ s.label } style={ statCard( s.color, s.text ) }>
            <div style={ { fontSize: 28, fontWeight: 800, color: s.text } }>{ s.value }</div>
            <div style={ { fontSize: 12, fontWeight: 500, color: C.textMuted, marginTop: 2 } }>{ s.label }</div>
          </div>
        ) ) }
      </div>

      {/* System Summary */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>System Summary</h3>
        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, fontSize: 13, color: C.text } }>
          <div>
            <div style={ label }>Platform</div>
            <div style={ { marginTop: 4 } }>Next.js 16 + React 19 + AWS Amplify Gen 2</div>
          </div>
          <div>
            <div style={ label }>AWS Account</div>
            <div style={ { marginTop: 4, ...mono } }>775261844268 (us-east-1)</div>
          </div>
          <div>
            <div style={ label }>Domain</div>
            <div style={ { marginTop: 4 } }>wecare.digital / wecare.digital/api / r.wecare.digital</div>
          </div>
          <div>
            <div style={ label }>Authentication</div>
            <div style={ { marginTop: 4 } }>Cognito (3 roles: Viewer, Operator, Admin)</div>
          </div>
          <div>
            <div style={ label }>Backend Runtime</div>
            <div style={ { marginTop: 4 } }>Python 3.12 (42 Lambda functions)</div>
          </div>
          <div>
            <div style={ label }>Database</div>
            <div style={ { marginTop: 4 } }>DynamoDB ({ DB_TABLES.length } tables, PAY_PER_REQUEST)</div>
          </div>
          <div>
            <div style={ label }>Storage</div>
            <div style={ { marginTop: 4 } }>S3 (wecare-digital-get) — o/stack/ + o/stream/</div>
          </div>
          <div>
            <div style={ label }>Channels</div>
            <div style={ { marginTop: 4 } }>WhatsApp, SMS, Email, Voice, RCS, Push</div>
          </div>
          <div>
            <div style={ label }>Payments</div>
            <div style={ { marginTop: 4 } }>Razorpay (WhatsApp Payments)</div>
          </div>
          <div>
            <div style={ label }>AI</div>
            <div style={ { marginTop: 4 } }>Amazon Bedrock (Claude 3 Sonnet) + Knowledge Base</div>
          </div>
          <div>
            <div style={ label }>Mobile</div>
            <div style={ { marginTop: 4 } }>Capacitor (iOS + Android)</div>
          </div>
          <div>
            <div style={ label }>Last Scan</div>
            <div style={ { marginTop: 4 } }>{ LAST_SCAN }</div>
          </div>
        </div>
      </div>

      {/* Quick Risk Summary */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>Risk Summary</h3>
        <div style={ { display: 'flex', gap: 12, flexWrap: 'wrap' } }>
          <span style={ pill( C.redBg, C.red ) }>{ RISKS.filter( r => r.priority === 'Critical' ).length } Critical</span>
          <span style={ pill( C.amberBg, C.amber ) }>{ RISKS.filter( r => r.priority === 'Important' ).length } Important</span>
          <span style={ pill( C.blueBg, C.blue ) }>{ RISKS.filter( r => r.priority === 'Nice to have' ).length } Nice to have</span>
        </div>
        <div style={ { marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 } }>
          { RISKS.filter( r => r.priority === 'Critical' ).map( r => (
            <div key={ r.id } style={ { display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13 } }>
              <span style={ { color: C.red, fontSize: 10, marginTop: 4, flexShrink: 0 } }>●</span>
              <div>
                <span style={ { fontWeight: 600, color: C.textDark } }>{ r.title }</span>
                <span style={ { ...pill( '#f9fafb', C.textMuted ), marginLeft: 6 } }>{ r.category }</span>
                <div style={ { fontSize: 12, color: C.textMuted, marginTop: 2 } }>{ r.description.slice( 0, 120 ) }...</div>
              </div>
            </div>
          ) ) }
        </div>
      </div>
      {/* WhatsApp Bot Menu */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>WhatsApp Bot Menu (Persistent Menu)</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: '0 0 12px' } }>9 menu items across 3 sections — shown to users when they open the WhatsApp chat.</p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
            <thead>
              <tr style={ { borderBottom: `2px solid ${C.border}` } }>
                { [ '#', 'Section', 'Title', 'Description', 'Action' ].map( h => (
                  <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
                ) ) }
              </tr>
            </thead>
            <tbody>
              { BOT_MENU.map( m => (
                <tr key={ m.row } style={ { borderBottom: `1px solid ${C.border}` } }>
                  <td style={ { padding: '8px 10px', color: C.textMuted, fontWeight: 600 } }>{ m.row }</td>
                  <td style={ { padding: '8px 10px' } }><span style={ pill( m.section === 'Start Here' ? C.greenBg : m.section === 'Explore WECARE' ? C.blueBg : C.amberBg, m.section === 'Start Here' ? C.green : m.section === 'Explore WECARE' ? C.blue : C.amber ) }>{ m.section }</span></td>
                  <td style={ { padding: '8px 10px', fontWeight: 600, color: C.textDark } }>{ m.icon } { m.title }</td>
                  <td style={ { padding: '8px 10px', color: C.text } }>{ m.description }</td>
                  <td style={ { padding: '8px 10px', color: C.textMuted, fontSize: 12 } }>{ m.action }</td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      </div>
      {/* Customer Service Sub-Menu */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>🚀 Customer Service Menu (WhatsApp Interactive List)</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: '0 0 12px' } }>9 customer-service options — triggered when user taps &quot;🚀 Customer Service&quot; from the bot menu. Each row opens a WhatsApp Flow.</p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
            <thead>
              <tr style={ { borderBottom: `2px solid ${C.border}` } }>
                { [ '#', 'Section', 'Title', 'Description', 'Flow ID', 'Keywords' ].map( h => (
                  <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
                ) ) }
              </tr>
            </thead>
            <tbody>
              { CUSTOMERSERVICE_MENU.map( m => (
                <tr key={ m.row } style={ { borderBottom: `1px solid ${C.border}` } }>
                  <td style={ { padding: '8px 10px', color: C.textMuted, fontWeight: 600 } }>{ m.row }</td>
                  <td style={ { padding: '8px 10px' } }><span style={ pill( '#f9fafb', C.textMuted ) }>{ m.section }</span></td>
                  <td style={ { padding: '8px 10px', fontWeight: 600, color: C.textDark } }>{ m.icon } { m.title }</td>
                  <td style={ { padding: '8px 10px', color: C.text } }>{ m.description }</td>
                  <td style={ { padding: '8px 10px', ...mono, fontSize: 11, color: C.textMuted } }>{ m.flowId }</td>
                  <td style={ { padding: '8px 10px', fontSize: 11, color: C.textMuted } }>{ m.keywords }</td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  // ─── Architecture Diagram (ASCII-style visual) ───
  const renderArchitecture = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 20 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Full System Architecture</h3>
        <div style={ { background: '#000', borderRadius: C.radiusSm, padding: 20, overflowX: 'auto' } }>
          <pre style={ { color: '#e2e8f0', fontSize: 12, lineHeight: 1.6, fontFamily: 'monospace', margin: 0, whiteSpace: 'pre' } }>{ `
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              WECARE.DIGITAL ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  Web App      │    │  iOS App     │    │  Android App │    │  WhatsApp    │       │
│  │  (Next.js 16) │    │  (Capacitor) │    │  (Capacitor) │    │  (Webhooks)  │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │                   │               │
│         └───────────────────┴───────────────────┴───────────────────┘               │
│                                     │                                               │
│                          ┌──────────▼──────────┐                                    │
│                          │   CloudFront (CDN)   │                                    │
│                          │   (no WAF — removed) │                                    │
│                          └──────────┬──────────┘                                    │
│                                     │                                               │
│                          ┌──────────▼──────────┐                                    │
│                          │   Cognito Auth       │                                    │
│                          │   (3 roles: V/O/A)   │                                    │
│                          └──────────┬──────────┘                                    │
│                                     │                                               │
│                          ┌──────────▼──────────┐                                    │
│                          │   API Gateway        │                                    │
│                          │   wecare.digital/api │                                    │
│                          └──────────┬──────────┘                                    │
│                                     │                                               │
│    ┌────────────────────────────────┼────────────────────────────────┐               │
│    │                                │                                │               │
│    ▼                                ▼                                ▼               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Core (6) │  │ Msg (22) │  │ AI (4)   │  │ Pay (4)  │  │ Ops (6)  │             │
│  │ Lambda   │  │ Lambda   │  │ Lambda   │  │ Lambda   │  │ Lambda   │             │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘             │
│       │              │              │              │              │                  │
│       └──────────────┴──────────────┴──────────────┴──────────────┘                  │
│                                     │                                               │
│         ┌───────────────────────────┼───────────────────────────┐                   │
│         │                           │                           │                   │
│         ▼                           ▼                           ▼                   │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐                       │
│  │  DynamoDB     │    │  S3 Bucket        │    │  SQS Queues  │                       │
│  │  (49 tables)  │    │  wecare-digital-get│    │  (4 queues)  │                       │
│  └──────────────┘    └──────────────────┘    └──────────────┘                       │
│                                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Bedrock  │  │ SES      │  │ Pinpoint │  │ Polly    │  │ EventBr. │             │
│  │ (AI/KB)  │  │ (Email)  │  │ (SMS)    │  │ (TTS)    │  │ (Cron)   │             │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘             │
│                                                                                     │
│  External: Meta WhatsApp API │ Razorpay │ Plivo Voice │ AWS SMS │ Wix Store       │
└─────────────────────────────────────────────────────────────────────────────────────┘
          `}</pre>
        </div>
      </div>

      {/* Service Categories */ }
      <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 } }>
        { [
          { title: 'Core Services', count: 6, items: [ 'contacts', 'auth-middleware', 'messages-read', 'messages-delete', 'faq-handler', 'url-shortener' ], color: C.green },
          { title: 'Messaging', count: 22, items: [ 'inbound-whatsapp', 'outbound-whatsapp', 'outbound-sms', 'outbound-email', 'outbound-voice', 'whatsapp-calling', '...+16 more' ], color: C.blue },
          { title: 'AI / ML', count: 4, items: [ 'ai-generate-response', 'ai-query-kb', 'ai-config-management', 'agent-action-group' ], color: '#7c3aed' },
          { title: 'Payments', count: 3, items: [ 'razorpay-webhook', 'payments-read', 'invoice-engine' ], color: C.amber },
          { title: 'Operations', count: 6, items: [ 'bulk-job-create', 'bulk-job-control', 'bulk-worker', 'dlq-replay', 'system-cleanup', 'billing' ], color: '#ec4899' },
          { title: 'Ecommerce', count: 3, items: [ 'wix-store', 'catalog-management', 'product-image-gen' ], color: '#06b6d4' },
        ].map( cat => (
          <div key={ cat.title } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } }>
              <span style={ { width: 8, height: 8, borderRadius: '50%', background: cat.color } } />
              <span style={ { fontSize: 14, fontWeight: 700, color: C.textDark } }>{ cat.title }</span>
              <span style={ pill( '#f9fafb', C.textMuted ) }>{ cat.count }</span>
            </div>
            <div style={ { display: 'flex', flexDirection: 'column', gap: 4 } }>
              { cat.items.map( item => (
                <div key={ item } style={ { fontSize: 12, color: C.textMuted, ...mono } }>{ item }</div>
              ) ) }
            </div>
          </div>
        ) ) }
      </div>
    </div>
  );

  // ─── Frontend → Backend Flow ───
  const renderFlow = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Frontend → Backend → Database Flow</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: '0 0 16px' } }>Every frontend route mapped to its backend services and database tables.</p>
      </div>
      <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
        { FRONTEND_ROUTES.map( route => (
          <div key={ route.path } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' } }>
              <div style={ { minWidth: 180 } }>
                <div style={ label }>Frontend Route</div>
                <div style={ { ...mono, fontSize: 13, fontWeight: 600, color: C.textDark, marginTop: 4 } }>{ route.path }</div>
                <div style={ { fontSize: 12, color: C.textMuted } }>{ route.label }</div>
              </div>
              <div style={ { fontSize: 18, color: C.textLight, alignSelf: 'center' } }>→</div>
              <div style={ { minWidth: 200, flex: 1 } }>
                <div style={ label }>Backend Services</div>
                <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 } }>
                  { route.backend.split( ', ' ).map( b => (
                    <span key={ b } style={ pill( C.greenBg, C.green ) }>{ b }</span>
                  ) ) }
                </div>
              </div>
              <div style={ { fontSize: 18, color: C.textLight, alignSelf: 'center' } }>→</div>
              <div style={ { minWidth: 200, flex: 1 } }>
                <div style={ label }>Database Tables</div>
                <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 } }>
                  { route.tables.split( ', ' ).map( t => (
                    <span key={ t } style={ pill( C.blueBg, C.blue ) }>{ t }</span>
                  ) ) }
                </div>
              </div>
            </div>
          </div>
        ) ) }
      </div>
    </div>
  );

  // ─── Backend Services ───
  const renderBackend = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 4 } }>
        { lambdaCategories.map( cat => (
          <button key={ cat } onClick={ () => setLambdaFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${lambdaFilter === cat ? C.bgDark : C.border}`, background: lambdaFilter === cat ? C.bgDark : C.bg, color: lambdaFilter === cat ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>
            { cat } { cat !== 'All' && `(${LAMBDAS.filter( l => l.category === cat ).length})` }
          </button>
        ) ) }
      </div>
      <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>{ filteredLambdas.length } service{ filteredLambdas.length !== 1 ? 's' : '' }</p>
      { filteredLambdas.map( fn => (
        <div key={ fn.name } style={ card( expandedItems.has( fn.name ) ) }>
          <button onClick={ () => toggleExpand( fn.name ) } style={ { width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 } }>
            <span style={ { fontSize: 10, color: C.green } }>●</span>
            <div style={ { flex: 1 } }>
              <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ fn.name }</span>
                <span style={ pill( '#f9fafb', C.textMuted ) }>{ fn.category }</span>
                { fn.apiRoute !== '-' && <span style={ { ...pill( C.greenBg, C.green ), ...mono } }>{ fn.apiRoute }</span> }
              </div>
              <p style={ { margin: '4px 0 0', fontSize: 12, color: C.textMuted } }>{ fn.description }</p>
            </div>
            <span style={ { transform: expandedItems.has( fn.name ) ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', fontSize: 12, color: C.textLight } }>▶</span>
          </button>
          { expandedItems.has( fn.name ) && (
            <div style={ { marginTop: 12, paddingTop: 12, borderTop: `2px solid ${C.border}`, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 } }>
              <div><div style={ label }>Trigger</div><div style={ { fontSize: 13, marginTop: 4 } }>{ fn.trigger }</div></div>
              <div><div style={ label }>Tables</div><div style={ { fontSize: 13, marginTop: 4, ...mono } }>{ fn.tables }</div></div>
              <div><div style={ label }>Runtime</div><div style={ { fontSize: 13, marginTop: 4 } }>Python 3.12</div></div>
            </div>
          ) }
        </div>
      ) ) }
    </div>
  );

  // ─── Database Tables ───
  const renderDatabase = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 4 } }>
        { tableCategories.map( cat => (
          <button key={ cat } onClick={ () => setTableFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${tableFilter === cat ? C.bgDark : C.border}`, background: tableFilter === cat ? C.bgDark : C.bg, color: tableFilter === cat ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>
            { cat } { cat !== 'All' && `(${DB_TABLES.filter( t => t.category === cat ).length})` }
          </button>
        ) ) }
      </div>
      <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>{ filteredTables.length } table{ filteredTables.length !== 1 ? 's' : '' } — PAY_PER_REQUEST billing</p>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Table', 'Purpose', 'Key', 'TTL', 'Indexes', 'Used By', 'Category' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { filteredTables.map( t => (
              <tr key={ t.name } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ t.name }</td>
                <td style={ { padding: '10px 12px', color: C.text, maxWidth: 250 } }>{ t.purpose }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted } }>{ t.keyFields }</td>
                <td style={ { padding: '10px 12px' } }>{ t.ttl ? <span style={ pill( C.amberBg, C.amber ) }>{ t.ttl }</span> : <span style={ { color: C.textLight } }>—</span> }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted, fontSize: 11 } }>{ t.indexes }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted, fontSize: 11 } }>{ t.usedBy }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( '#f9fafb', C.textMuted ) }>{ t.category }</span></td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── Lambda Functions Tab ───
  const renderLambda = () => renderBackend();

  // ─── AWS Resources ───
  const renderAWS = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>AWS Resources ({ AWS_RESOURCES.length } services)</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>All AWS resources used by the platform. Account: 775261844268 | Region: us-east-1</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Resource', 'Type', 'Purpose', 'Module', 'Environment', 'Status' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { AWS_RESOURCES.map( ( r, i ) => (
              <tr key={ i } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono, fontSize: 12 } }>{ r.name }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.blueBg, C.blue ) }>{ r.type }</span></td>
                <td style={ { padding: '10px 12px', color: C.text, maxWidth: 250 } }>{ r.purpose }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( '#f9fafb', C.textMuted ) }>{ r.module }</span></td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.greenBg, C.green ) }>{ r.env }</span></td>
                <td style={ { padding: '10px 12px' } }><span style={ { color: C.green, fontSize: 10 } }>● </span>{ r.status }</td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── AWS Resource Tree ───
  const renderAWSTree = () => {
    const tree = [
      {
        name: 'WECARE.DIGITAL (775261844268)', children: [
          {
            name: '🔐 Authentication', children: [
              {
                name: 'Cognito User Pool (us-east-1_cSx0RHCIR)', children: [
                  { name: 'Groups: Viewer, Operator, Admin' },
                  { name: 'OAuth Domain: wecare-digital-auth.auth.us-east-1.amazoncognito.com (managed login v2)' },
                ]
              },
              { name: 'Cognito Identity Pool' },
              { name: 'IAM Roles (Lambda execution)' },
            ]
          },
          {
            name: '🌐 Networking', children: [
              {
                name: 'Route 53 (DNS)', children: [
                  // app.wecare.digital dropped 2026-09-28: record removed, host NXDOMAIN.
                  { name: 'wecare.digital' }, { name: 'wecare.digital/api' }, { name: 'r.wecare.digital' }, { name: 'mta-sts.wecare.digital' },
                ]
              },
              { name: 'CloudFront E2GP22R4BIFGQ3 (wecare.digital/get → wecare-digital-get)' },
              { name: 'ACM Certificates (SSL/TLS)' },
            ]
          },
          {
            name: '⚡ Compute — Lambda (42 functions)', children: [
              { name: 'Core (6): contacts, auth, messages, faq, url-shortener' },
              { name: 'Messaging (22): whatsapp, sms, voice, email, push' },
              { name: 'AI (4): generate-response, query-kb, config, agent' },
              { name: 'Payments (3): razorpay, payments-read, invoice' },
              { name: 'Operations (6): bulk-jobs, dlq, cleanup, billing' },
              { name: 'Ecommerce (3): wix-store, catalog, image-gen' },
            ]
          },
          {
            name: '🗄️ Database — DynamoDB (' + DB_TABLES.length + ' tables)', children: [
              { name: 'Core: Contact, Message, User, MediaFile, AuditLog, SystemConfig, WebhookDedup, ...' },
              { name: 'WhatsApp: WhatsAppInbound, WhatsAppOutbound, WhatsAppVoice, WhatsAppCalling, WhatsAppGroup, ...' },
              { name: 'SMS/Voice: SmsAws, AirtelSMS, VoiceCall, VoiceAws, AirtelC2C, VoiceCDR, OBDCampaign, DLTTemplates' },
              { name: 'Payments: Payment, Invoice, InvoiceItem, InvoiceAsset, InvoiceDeliveryLog, InvoiceSequence, RazorpayWebhookLog' },
              { name: 'Ecommerce: WixProductsCache, WixOrdersCache, WixOrderId, WixOrderMapping, CatalogCache' },
              { name: 'AI: AIInteraction, ConversationHistory' },
              { name: 'Flows: FlowRegistry, FlowSubmission, FlowLog' },
              { name: 'Operations: BulkJob, BulkRecipient, DLQMessage, ScheduledMessage, SystemEvent, ...' },
              { name: 'Analytics: TemplateAnalytics, AdClickAttribution, MetaAnalyticsLog' },
            ]
          },
          {
            name: '📦 Storage — S3', children: [
              {
                name: 'wecare-digital-get', children: [
                  { name: 'o/ (public root)' },
                  { name: 'o/stack/ (user data — factory reset wipes this)' },
                  { name: 'o/stream/ (static assets — never wiped)' },
                  { name: 'o/public/wa-tpl/ (Meta-approved template media — do not move)' },
                  { name: 'secure/ (gated at the edge — presigned access only)' },
                ]
              },
            ]
          },
          {
            name: '📨 Messaging Services', children: [
              { name: 'SQS (4 queues): bulk-queue, inbound-dlq, bulk-dlq, outbound-dlq' },
              { name: 'SNS Topics (delivery notifications)' },
              { name: 'Amazon SES (email)' },
              { name: 'Amazon Pinpoint (SMS)' },
              { name: 'Amazon Polly (TTS)' },
            ]
          },
          {
            name: '🤖 AI / ML', children: [
              { name: 'Amazon Bedrock (Claude 3 Sonnet)' },
              { name: 'Bedrock Knowledge Base' },
              { name: 'Bedrock Agent + Action Groups' },
            ]
          },
          {
            name: '📊 Monitoring', children: [
              { name: 'CloudWatch Logs (42 log groups, 90d retention)' },
              { name: 'CloudWatch Alarms (error rate, DLQ depth)' },
              { name: 'EventBridge Rules (scheduled triggers)' },
            ]
          },
          {
            name: '🔒 Security', children: [
              { name: 'Secrets Manager (API keys, webhook secrets)' },
              { name: 'Rate limiting (handler-side; WAF removed 2026-09-28)' },
              { name: 'ACM (SSL certificates)' },
            ]
          },
        ]
      },
    ];

    const renderTreeNode = ( node: any, depth = 0 ): React.ReactNode => (
      <div key={ node.name } style={ { marginLeft: depth * 20, marginBottom: 4 } }>
        <div style={ { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 6, background: depth === 0 ? C.bgDark : depth === 1 ? '#f9fafb' : 'transparent', color: depth === 0 ? C.lime : C.text, fontSize: depth <= 1 ? 13 : 12, fontWeight: depth <= 1 ? 600 : 400 } }>
          { node.children && <span style={ { fontSize: 10 } }>▸</span> }
          { node.name }
        </div>
        { node.children?.map( ( child: any ) => renderTreeNode( child, depth + 1 ) ) }
      </div>
    );

    return (
      <div style={ card() }>
        <h3 style={ sectionTitle }>AWS Resource Hierarchy</h3>
        <div style={ { maxHeight: 700, overflowY: 'auto' } }>
          { tree.map( node => renderTreeNode( node ) ) }
        </div>
      </div>
    );
  };

  // ─── Storage / Buckets ───
  const renderStorage = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>S3 Bucket: wecare-digital-get</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>Two top-level roots: <code style={ mono }>o/</code> (public) and <code style={ mono }>secure/</code> (gated at the edge, presigned access only). <code style={ mono }>o/</code> is a location, not a permission — everything outside <code style={ mono }>secure/</code> is public. Within <code style={ mono }>o/</code>: <code style={ mono }>stack/</code> is user data (wipeable) and <code style={ mono }>stream/</code> is static assets (permanent). Served as <code style={ mono }>wecare.digital/get/&lt;key&gt;</code>; the bucket name is not a hostname.</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Path', 'Purpose', 'Read By', 'Written By' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { STORAGE_PATHS.map( s => (
              <tr key={ s.path } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ s.path }</td>
                <td style={ { padding: '10px 12px', color: C.text } }>{ s.purpose }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.blueBg, C.blue ) }>{ s.readBy }</span></td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.greenBg, C.green ) }>{ s.writtenBy }</span></td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
      {/* SQS Queues */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>SQS Queues (4)</h3>
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 10 } }>
          { [
            { name: 'stack-wecare-digital-bulk-queue', purpose: 'Bulk message job processing', retention: '1 day', visibility: '5 min' },
            { name: 'stack-wecare-digital-inbound-dlq', purpose: 'Failed inbound processing', retention: '7 days', visibility: '5 min' },
            { name: 'stack-wecare-digital-bulk-dlq', purpose: 'Failed bulk chunks', retention: '7 days', visibility: '5 min' },
            { name: 'stack-wecare-digital-outbound-dlq', purpose: 'Failed outbound messages', retention: '7 days', visibility: '5 min' },
          ].map( q => (
            <div key={ q.name } style={ { padding: 12, background: C.bgSoft, borderRadius: C.radiusSm } }>
              <div style={ { ...mono, fontSize: 12, fontWeight: 600, color: C.textDark, wordBreak: 'break-all' } }>{ q.name }</div>
              <div style={ { fontSize: 12, color: C.textMuted, marginTop: 4 } }>{ q.purpose }</div>
              <div style={ { display: 'flex', gap: 6, marginTop: 6 } }>
                <span style={ pill( C.amberBg, C.amber ) }>Retention: { q.retention }</span>
                <span style={ pill( '#f9fafb', C.textMuted ) }>Visibility: { q.visibility }</span>
              </div>
            </div>
          ) ) }
        </div>
      </div>
    </div>
  );

  // ─── Code Map ───
  const renderCodeMap = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Codebase Structure</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>Monorepo: wecare.digital — Next.js frontend + Amplify Gen 2 backend</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Folder', 'Purpose', 'Files', 'Linked To' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { CODE_MAP.map( c => (
              <tr key={ c.path } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ c.path }</td>
                <td style={ { padding: '10px 12px', color: C.text } }>{ c.purpose }</td>
                <td style={ { padding: '10px 12px', color: C.textMuted } }>{ c.files }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( '#f9fafb', C.textMuted ) }>{ c.linkedTo }</span></td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── Search ───
  const renderSearch = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 16 } }>
      <div style={ { position: 'relative', maxWidth: 600 } }>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" style={ { position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' } }>
          <path stroke={ C.textDark } strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="m21 21-4.35-4.35M11 6a5 5 0 0 1 5 5m3 0a8 8 0 1 1-16 0 8 8 0 0 1 16 0" />
        </svg>
        <input
          value={ searchQuery }
          onChange={ e => setSearchQuery( e.target.value ) }
          placeholder="Search tables, Lambda functions, AWS resources, routes, env vars, risks... (Ctrl+K)"
          aria-label="Search system architecture"
          style={ { width: '100%', padding: '12px 16px 12px 40px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 14, outline: 'none', boxSizing: 'border-box' } }
          autoFocus
        />
      </div>
      { searchQuery && (
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>{ searchResults.length } result{ searchResults.length !== 1 ? 's' : '' } for &quot;{ searchQuery }&quot;</p>
      ) }
      { searchResults.length > 0 && (
        <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
          { searchResults.map( ( r, i ) => (
            <div key={ i } style={ card() }>
              <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                <span style={ pill(
                  r.type === 'Table' ? C.blueBg : r.type === 'Lambda' ? C.greenBg : r.type === 'AWS' ? C.amberBg : r.type === 'Risk' ? C.redBg : '#f9fafb',
                  r.type === 'Table' ? C.blue : r.type === 'Lambda' ? C.green : r.type === 'AWS' ? C.amber : r.type === 'Risk' ? C.red : C.textMuted
                ) }>{ r.type }</span>
                <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ r.name }</span>
                <span style={ pill( '#f9fafb', C.textMuted ) }>{ r.category }</span>
              </div>
              <p style={ { margin: '6px 0 0', fontSize: 12, color: C.textMuted } }>{ r.detail }</p>
            </div>
          ) ) }
        </div>
      ) }
      { !searchQuery && (
        <div style={ card() }>
          <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>
            Search across { searchIndex.length } indexed items: { DB_TABLES.length } tables, { LAMBDAS.length } Lambda functions, { AWS_RESOURCES.length } AWS resources, { FRONTEND_ROUTES.length } routes, { STORAGE_PATHS.length } storage paths, { CODE_MAP.length } code folders, { ENV_VARS.length } env vars, { RISKS.length } risks, { IMPROVEMENTS.length } improvements.
          </p>
        </div>
      ) }
    </div>
  );

  // ─── Eye Icon SVG ───
  const EyeIcon = ( { open }: { open: boolean } ) => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      { open ? (
        <>
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
        </>
      ) : (
        <>
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
          <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </>
      ) }
    </svg>
  );

  // ─── Environment Settings ───
  const renderEnv = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>

      <div style={ card() }>
        <h3 style={ sectionTitle }>Environment Configuration</h3>
        <div style={ { display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' } }>
          <span style={ pill( C.greenBg, C.green ) }>Production (active)</span>
          <span style={ pill( C.redBg, C.red ) }>No staging detected</span>
          <span style={ pill( C.redBg, C.red ) }>No dev detected</span>
          <span style={ pill( C.redBg, C.red ) }>{ ENV_VARS.filter( e => e.risk ).length } issues found</span>
          <span style={ pill( '#f9fafb', C.textMuted ) }>Values permanently redacted</span>
        </div>
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>Inventory contains variable names and risk metadata only. Secret values are never embedded in or revealed by the browser.</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Variable', 'Value', '', 'Category', 'Sensitive', 'Risk' ].map( ( h, i ) => (
                <th key={ h || `eye-${i}` } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, width: h === '' ? 36 : undefined } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { ENV_VARS.map( e => {
              const displayValue = e.sensitive ? 'Server-side / redacted' : e.value;
              return (
                <tr key={ e.key } style={ { borderBottom: `1px solid ${C.border}`, background: e.risk?.startsWith( 'CRITICAL' ) ? '#fef2f2' : 'transparent' } }>
                  <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono, fontSize: 12 } }>{ e.key }</td>
                  <td style={ { padding: '10px 12px', ...mono, color: e.sensitive ? C.amber : C.textMuted, fontSize: 12, wordBreak: 'break-all', maxWidth: 340 } }>{ displayValue }</td>
                  <td style={ { padding: '4px 6px', width: 36 } } />
                  <td style={ { padding: '10px 12px' } }><span style={ pill( e.category.includes( 'Hardcoded' ) ? C.redBg : e.category.includes( '✓' ) ? C.greenBg : '#f9fafb', e.category.includes( 'Hardcoded' ) ? C.red : e.category.includes( '✓' ) ? C.green : C.textMuted ) }>{ e.category }</span></td>
                  <td style={ { padding: '10px 12px' } }>{ e.sensitive ? <span style={ pill( C.amberBg, C.amber ) }>Sensitive</span> : <span style={ { color: C.textLight } }>—</span> }</td>
                  <td style={ { padding: '10px 12px', fontSize: 12, color: e.risk?.startsWith( 'CRITICAL' ) ? C.red : C.amber, fontWeight: e.risk ? 600 : 400 } }>{ e.risk || <span style={ { color: C.textLight } }>—</span> }</td>
                </tr>
              );
            } ) }
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── Logs / Change History ───
  const renderLogs = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Logs & Change History</h3>
        <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>Log sources and change tracking across the platform.</p>
      </div>
      <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 } }>
        { [
          { title: 'CloudWatch Logs', source: '42 Lambda log groups', retention: '90 days', status: 'Active', detail: 'All Lambda function execution logs. Access via AWS Console → CloudWatch → Log Groups → /aws/lambda/wecare-*' },
          { title: 'DynamoDB AuditLog', source: 'AuditLog table', retention: '180 days (TTL)', status: 'Active', detail: 'System audit trail: user actions, resource changes, API calls. Fields: userId, action, resourceType, resourceId, details.' },
          { title: 'DLQ Messages', source: 'DLQMessage table', retention: '7 days (TTL)', status: 'Active', detail: 'Failed message processing records. Includes original payload, retry count, error details.' },
          { title: 'Webhook Logs', source: 'RazorpayWebhookLog', retention: '180 days (TTL)', status: 'Active', detail: 'Payment webhook event logs for debugging payment flows.' },
          { title: 'System Events', source: 'SystemEvent table', retention: 'Short TTL', status: 'Active', detail: 'System-level events: cleanup runs, billing updates, scheduled task completions.' },
          { title: 'Meta Analytics', source: 'MetaAnalyticsLog table', retention: 'Permanent', status: 'Active', detail: 'WhatsApp conversation analytics from Meta Business API.' },
          { title: 'CloudWatch Alarms', source: 'CloudWatch Alarms', retention: 'Permanent', status: 'Active', detail: 'Alerts for Lambda error rates, DLQ depth, and per-function error tracking.' },
          { title: 'Deployment Logs', source: 'Not configured', retention: '-', status: 'Missing', detail: 'No CI/CD pipeline detected. Deployment history not tracked. Recommend adding GitHub Actions or CodePipeline.' },
        ].map( log => (
          <div key={ log.title } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } }>
              <span style={ { fontSize: 10, color: log.status === 'Active' ? C.green : C.red } }>●</span>
              <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ log.title }</span>
            </div>
            <div style={ { display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' } }>
              <span style={ pill( '#f9fafb', C.textMuted ) }>{ log.source }</span>
              <span style={ pill( C.amberBg, C.amber ) }>{ log.retention }</span>
            </div>
            <p style={ { fontSize: 12, color: C.textMuted, margin: 0 } }>{ log.detail }</p>
          </div>
        ) ) }
      </div>
    </div>
  );

  // ─── Dependencies ───
  const renderDeps = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Dependency Analysis</h3>
        <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
          <span style={ pill( C.greenBg, C.green ) }>{ DEPENDENCIES.filter( d => d.status === 'ok' ).length } OK</span>
          <span style={ pill( C.amberBg, C.amber ) }>{ DEPENDENCIES.filter( d => d.status === 'warning' ).length } Warnings</span>
          <span style={ pill( C.redBg, C.red ) }>{ DEPENDENCIES.filter( d => d.status === 'outdated' ).length } Outdated</span>
        </div>
        <p style={ { fontSize: 13, color: C.textMuted, margin: '8px 0 0' } }>Node ≥24.0.0 | npm 11.6.2 | { DEPENDENCIES.filter( d => d.type === 'prod' ).length } production, { DEPENDENCIES.filter( d => d.type === 'dev' ).length } dev dependencies</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Package', 'Version', 'Type', 'Status', 'Notes' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 11, color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { DEPENDENCIES.map( d => (
              <tr key={ d.name } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ d.name }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted } }>{ d.version }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( d.type === 'prod' ? C.blueBg : '#f9fafb', d.type === 'prod' ? C.blue : C.textMuted ) }>{ d.type }</span></td>
                <td style={ { padding: '10px 12px' } }>
                  <span style={ pill(
                    d.status === 'ok' ? C.greenBg : d.status === 'warning' ? C.amberBg : C.redBg,
                    d.status === 'ok' ? C.green : d.status === 'warning' ? C.amber : C.red
                  ) }>{ d.status }</span>
                </td>
                <td style={ { padding: '10px 12px', color: C.textMuted, fontSize: 12 } }>{ d.note }</td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── Risks / Gaps ───
  const renderRisks = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 4 } }>
        { [ 'All', 'Critical', 'Important', 'Nice to have' ].map( p => (
          <button key={ p } onClick={ () => setRiskFilter( p ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${riskFilter === p ? C.bgDark : C.border}`, background: riskFilter === p ? C.bgDark : C.bg, color: riskFilter === p ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>
            { p } { p !== 'All' && `(${RISKS.filter( r => r.priority === p ).length})` }
          </button>
        ) ) }
      </div>
      { ( riskFilter === 'All' ? RISKS : RISKS.filter( r => r.priority === riskFilter ) ).map( r => (
        <div key={ r.id } style={ card() }>
          <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
            <span style={ pill(
              r.priority === 'Critical' ? C.redBg : r.priority === 'Important' ? C.amberBg : C.blueBg,
              r.priority === 'Critical' ? C.red : r.priority === 'Important' ? C.amber : C.blue
            ) }>{ r.priority }</span>
            <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ r.title }</span>
            <span style={ pill( '#f9fafb', C.textMuted ) }>{ r.category }</span>
          </div>
          <p style={ { margin: '8px 0 0', fontSize: 13, color: C.text } }>{ r.description }</p>
        </div>
      ) ) }
    </div>
  );

  // ─── Improvements ───
  const renderImprovements = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ card() }>
        <h3 style={ sectionTitle }>Improvement Recommendations ({ IMPROVEMENTS.length })</h3>
        <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
          <span style={ pill( C.redBg, C.red ) }>{ IMPROVEMENTS.filter( i => i.priority === 'Critical' ).length } Critical</span>
          <span style={ pill( C.amberBg, C.amber ) }>{ IMPROVEMENTS.filter( i => i.priority === 'Important' ).length } Important</span>
          <span style={ pill( C.blueBg, C.blue ) }>{ IMPROVEMENTS.filter( i => i.priority === 'Nice to have' ).length } Nice to have</span>
        </div>
      </div>
      { IMPROVEMENTS.map( imp => (
        <div key={ imp.id } style={ card() }>
          <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
            <span style={ pill(
              imp.priority === 'Critical' ? C.redBg : imp.priority === 'Important' ? C.amberBg : C.blueBg,
              imp.priority === 'Critical' ? C.red : imp.priority === 'Important' ? C.amber : C.blue
            ) }>{ imp.priority }</span>
            <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ imp.title }</span>
            <span style={ pill( '#f9fafb', C.textMuted ) }>{ imp.category }</span>
          </div>
          <p style={ { margin: '8px 0 0', fontSize: 13, color: C.text } }>{ imp.description }</p>
        </div>
      ) ) }
    </div>
  );

  // ─── Lambda Admin (Detailed) ───
  const filteredLambdaDetail = useMemo( () => {
    const q = lambdaDetailSearch.toLowerCase();
    return LAMBDA_DETAILED.filter( fn => {
      const matchCat = lambdaDetailFilter === 'All' || fn.category === lambdaDetailFilter;
      const matchSearch = !q || fn.name.toLowerCase().includes( q ) || fn.displayName.toLowerCase().includes( q ) || fn.description.toLowerCase().includes( q );
      return matchCat && matchSearch;
    } );
  }, [ lambdaDetailSearch, lambdaDetailFilter ] );

  const renderLambdaDetail = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } }>
        <div style={ { position: 'relative', flex: 1, maxWidth: 400 } }>
          <input value={ lambdaDetailSearch } onChange={ e => setLambdaDetailSearch( e.target.value ) } placeholder="Search functions..." aria-label="Search Lambda functions" style={ { width: '100%', padding: '10px 14px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
        </div>
        <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap' } }>
          { LAMBDA_DETAIL_CATEGORIES.map( cat => (
            <button key={ cat } onClick={ () => setLambdaDetailFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${lambdaDetailFilter === cat ? C.bgDark : C.border}`, background: lambdaDetailFilter === cat ? C.bgDark : C.bg, color: lambdaDetailFilter === cat ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>{ cat }</button>
          ) ) }
        </div>
      </div>
      <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>{ filteredLambdaDetail.length } function{ filteredLambdaDetail.length !== 1 ? 's' : '' } — with env vars, runtime, memory, triggers</p>
      { filteredLambdaDetail.map( fn => {
        const isExp = expandedItems.has( 'ld-' + fn.name );
        return (
          <div key={ fn.name } style={ card( isExp ) }>
            <button onClick={ () => toggleExpand( 'ld-' + fn.name ) } style={ { width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 } }>
              <span style={ { fontSize: 10, color: C.green } }>●</span>
              <div style={ { flex: 1 } }>
                <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                  <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ fn.displayName }</span>
                  <span style={ pill( '#f9fafb', C.textMuted ) }>{ fn.category }</span>
                  { fn.apiRoute && fn.apiRoute !== '-' && <span style={ { ...pill( C.greenBg, C.green ), ...mono } }>{ fn.apiRoute }</span> }
                </div>
                <p style={ { margin: '4px 0 0', fontSize: 12, color: C.textMuted } }>{ fn.description }</p>
              </div>
              <span style={ { transform: isExp ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', fontSize: 12, color: C.textLight } }>▶</span>
            </button>
            { isExp && (
              <div style={ { marginTop: 12, paddingTop: 12, borderTop: `2px solid ${C.border}` } }>
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 12 } }>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Runtime</div><div style={ { fontSize: 13, fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.runtime }</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Timeout</div><div style={ { fontSize: 13, fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.timeout }s</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Memory</div><div style={ { fontSize: 13, fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.memory } MB</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Status</div><div style={ { fontSize: 13, fontWeight: 600, color: C.green, marginTop: 2 } }>{ fn.status }</div></div>
                </div>
                <div style={ { marginBottom: 10 } }><div style={ label }>Triggers</div><div style={ { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 } }>{ fn.triggers.map( t => <span key={ t } style={ pill( '#f9fafb', C.text ) }>{ t }</span> ) }</div></div>
                { Object.keys( fn.envVars ).length > 0 && (
                  <div><div style={ label }>Environment Variables</div><div style={ { background: C.bgSoft, borderRadius: C.radiusSm, padding: 10, marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 } }>
                    { Object.entries( fn.envVars ).map( ( [ k, v ] ) => (
                      <div key={ k } style={ { display: 'flex', gap: 8 } }><code style={ { ...mono, fontWeight: 600, color: C.textDark, minWidth: 160 } }>{ k }</code><code style={ { ...mono, color: C.textMuted } }>{ v }</code></div>
                    ) ) }
                  </div></div>
                ) }
              </div>
            ) }
          </div>
        );
      } ) }
    </div>
  );

  // ─── Code Repository ───
  const filteredCodeAssets = useMemo( () => {
    const q = codeRepoSearch.toLowerCase();
    return CODE_ASSETS.filter( a => {
      const matchCat = codeRepoCategory === 'All' || a.category === codeRepoCategory;
      const matchSearch = !q || a.name.toLowerCase().includes( q ) || a.description.toLowerCase().includes( q ) || a.path.toLowerCase().includes( q );
      return matchCat && matchSearch;
    } );
  }, [ codeRepoSearch, codeRepoCategory ] );

  const renderCodeRepo = () => (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
      <div style={ { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } }>
        <input value={ codeRepoSearch } onChange={ e => setCodeRepoSearch( e.target.value ) } placeholder="Search flows, lambdas, templates..." aria-label="Search code assets" style={ { flex: 1, maxWidth: 400, padding: '10px 14px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
        <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap' } }>
          { CODE_ASSET_CATEGORIES.map( cat => (
            <button key={ cat } onClick={ () => setCodeRepoCategory( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${codeRepoCategory === cat ? C.bgDark : C.border}`, background: codeRepoCategory === cat ? C.bgDark : C.bg, color: codeRepoCategory === cat ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>{ cat }</button>
          ) ) }
        </div>
      </div>
      <p style={ { fontSize: 13, color: C.textMuted, margin: 0 } }>{ filteredCodeAssets.length } asset{ filteredCodeAssets.length !== 1 ? 's' : '' }</p>
      { filteredCodeAssets.map( asset => (
        <div key={ asset.id } style={ card( expandedAsset === asset.id ) } onClick={ () => setExpandedAsset( expandedAsset === asset.id ? null : asset.id ) } role="button" tabIndex={ 0 }>
          <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
            <span style={ pill( asset.type === 'Flow JSON' ? C.lime : C.bgSoft, C.textDark ) }>{ asset.type }</span>
            <span style={ { fontSize: 14, fontWeight: 600, color: C.textDark } }>{ asset.name }</span>
            { asset.status && <span style={ pill( asset.status === 'Published' ? C.greenBg : C.amberBg, asset.status === 'Published' ? C.green : C.amber ) }>{ asset.status }</span> }
            <span style={ pill( '#f9fafb', C.textMuted ) }>{ asset.category }</span>
          </div>
          <p style={ { margin: '4px 0 0', fontSize: 12, color: C.textMuted } }>{ asset.description }</p>
          { expandedAsset === asset.id && (
            <div style={ { marginTop: 10, padding: '8px 10px', background: C.bgSoft, borderRadius: C.radiusSm } }>
              <div style={ label }>File Path</div>
              <code style={ { ...mono, color: C.textDark, fontSize: 11 } }>{ asset.path }</code>
            </div>
          ) }
        </div>
      ) ) }
    </div>
  );

  // ─── Tab Router ───
  const renderTab = () => {
    switch ( activeTab )
    {
      case 'overview': return renderOverview();
      case 'architecture': return renderArchitecture();
      case 'flow': return renderFlow();
      case 'backend': return renderBackend();
      case 'database': return renderDatabase();
      case 'lambda': return renderLambda();
      case 'aws': return renderAWS();
      case 'aws-tree': return renderAWSTree();
      case 'storage': return renderStorage();
      case 'code-map': return renderCodeMap();
      case 'search': return renderSearch();
      case 'env': return renderEnv();
      case 'logs': return renderLogs();
      case 'deps': return renderDeps();
      case 'risks': return renderRisks();
      case 'improvements': return renderImprovements();
      case 'lambda-detail': return renderLambdaDetail();
      case 'code-repo': return renderCodeRepo();
      default: return renderOverview();
    }
  };

  // ─── Main Render ───
  return (
    <Layout onSignOut={ signOut } user={ user }>
      <SEO title="Project Control Center" description="Unified admin dashboard — architecture, Lambda, code repo, risks" noindex />
      <div className="inner-page-container" style={ { background: C.bg } }>
        {/* Page Header */ }
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 } }>
          <div>
            <h2 style={ { margin: 0, fontSize: 22, fontWeight: 700, color: C.textDark } }>Project Control Center</h2>
            <p style={ { margin: '4px 0 0', fontSize: 13, color: C.textMuted } }>
              Full system architecture — { LAMBDAS.length } Lambda functions · { DB_TABLES.length } tables · { AWS_RESOURCES.length } AWS resources · { STORAGE_PATHS.length } storage paths
            </p>
          </div>
          <div style={ { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } }>
            <button onClick={ refresh } title="Refresh now" style={ { padding: '6px 12px', borderRadius: C.radius, border: `2px solid ${C.border}`, background: C.bg, color: C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 } }>
              ↻ Refresh
            </button>
            <button onClick={ toggleAutoRefresh } title={ isAutoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh' } style={ { padding: '6px 12px', borderRadius: C.radius, border: `2px solid ${isAutoRefresh ? C.borderActive : C.border}`, background: isAutoRefresh ? C.bgDark : C.bg, color: isAutoRefresh ? C.lime : C.textMuted, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>
              { isAutoRefresh ? '⏱ Auto' : '⏸ Paused' }
            </button>
            <span style={ pill( C.greenBg, C.green ) }>Scan: { LAST_SCAN }</span>
          </div>
        </div>

        {/* Tab Bar */ }
        <div style={ { overflowX: 'auto', marginBottom: 20, paddingBottom: 2 } }>
          <div style={ { display: 'flex', gap: 4, minWidth: 'max-content' } } role="tablist">
            { TABS.map( tab => (
              <button
                key={ tab.id }
                role="tab"
                aria-selected={ activeTab === tab.id }
                onClick={ () => setActiveTab( tab.id ) }
                style={ {
                  padding: '8px 16px',
                  borderRadius: C.radius,
                  border: `2px solid ${activeTab === tab.id ? C.bgDark : 'transparent'}`,
                  background: activeTab === tab.id ? C.bgDark : 'transparent',
                  color: activeTab === tab.id ? C.lime : C.textMuted,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all 0.15s',
                } }
              >
                { tab.label }
              </button>
            ) ) }
          </div>
        </div>

        {/* Tab Content */ }
        <div role="tabpanel" style={ { minHeight: 400 } }>
          { renderTab() }
        </div>
      </div>
    </Layout>
  );
};

export default SystemArchitecturePage;
