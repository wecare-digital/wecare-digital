import { REVIEW_FLOW_ID, REVIEW_ENTRY_KEYWORDS } from '../../../lib/reviewEntry';
import { canonicalFlowId } from '../../../lib/canonicalFlows';
/**
 * System Architecture — Project Control Center
 * Complete end-to-end dashboard for the entire WECARE.DIGITAL platform.
 * Tabs covering frontend, backend, infra, AWS, storage and dependencies. Holds no account id,
 * physical resource name, secret name or risk list: staff chunks are downloadable without
 * signing in (audit WEB-4).
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

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

// ─── Design Tokens ───
const C = {
  bg: '#fff', bgSoft: 'var(--bg-secondary)', bgDark: 'var(--accent)', lime: 'var(--lime)', limeDark: '#b8dc5a',
  text: '#374151', textDark: 'var(--accent)', textMuted: 'var(--text-muted)', textLight: '#9ca3af',
  border: '#f3f4f6', borderActive: 'var(--lime)',
  green: '#059669', greenBg: '#f0fdf4', red: '#374151', redBg: '#f5f5f5',
  amber: '#d97706', amberBg: '#fffbeb', blue: '#2563eb', blueBg: '#eff6ff',
  radius: 13, radiusSm: 10,
};

const pill = ( bg: string, color: string ): React.CSSProperties => ( {
  display: 'inline-block', padding: '2px 10px', borderRadius: 10, fontSize: 'var(--text-xs)', fontWeight: 600, background: bg, color,
} );

const card = ( active = false ): React.CSSProperties => ( {
  border: `2px solid ${active ? C.borderActive : C.border}`, borderRadius: C.radius, background: C.bg, padding: 16, transition: 'border-color 0.15s',
} );

const statCard = ( bg: string, color: string ): React.CSSProperties => ( {
  padding: '14px 16px', background: bg, borderRadius: C.radius, border: `2px solid ${C.border}`,
} );

const sectionTitle: React.CSSProperties = { fontSize: 'var(--text-md)', fontWeight: 700, color: C.textDark, margin: '0 0 12px' };
const label: React.CSSProperties = { fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em' };
const mono: React.CSSProperties = { fontFamily: 'monospace', fontSize: 'var(--text-xs)' };

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
  { name: 'AIInteraction', purpose: 'Retired AI query/response logs (historical data)', keyFields: 'interactionId', indexes: 'messageId', usedBy: 'none (retired)', category: 'AI' },
  { name: 'RateLimitTracker', purpose: 'Rate limiting counters', keyFields: 'channel + windowStart', ttl: '24h', indexes: '-', usedBy: 'outbound-whatsapp', category: 'Core' },
  { name: 'SystemConfig', purpose: 'System configuration key-value store', keyFields: 'configKey', indexes: '-', usedBy: 'ai-config-management', category: 'Core' },
  { name: 'SmsAws', purpose: 'AWS Pinpoint SMS messages', keyFields: 'messageId', ttl: '90d', indexes: 'contactId, phoneNumber', usedBy: 'sms-aws', category: 'SMS' },
  { name: 'VoiceAws', purpose: 'AWS Pinpoint voice calls', keyFields: 'callId', ttl: '90d', indexes: 'contactId, phoneNumber', usedBy: 'voice-aws', category: 'Voice' },
  { name: 'DLTTemplates', purpose: 'TRAI DLT template registry (live)', keyFields: 'templateId', indexes: '-', usedBy: 'sms-aws', category: 'SMS' },
  { name: 'ScheduledMessage', purpose: 'Scheduled WhatsApp messages', keyFields: 'scheduledId', indexes: 'contactId, status', usedBy: 'scheduled-messages', category: 'WhatsApp' },
  { name: 'WhatsAppVoice', purpose: 'WhatsApp TTS/audio voice messages', keyFields: 'messageId', ttl: '90d', indexes: 'contactId', usedBy: 'whatsapp-voice', category: 'WhatsApp' },
  { name: 'Payment', purpose: 'Razorpay payment records', keyFields: 'id', indexes: 'paymentId, orderId', usedBy: 'razorpay-webhook, payments-read', category: 'Payments' },
  { name: 'WhatsAppCalling', purpose: 'WhatsApp voice/video call logs', keyFields: 'id', ttl: '90d', indexes: 'callId', usedBy: 'whatsapp-calling', category: 'WhatsApp' },
  { name: 'WhatsAppGroup', purpose: 'WhatsApp Business group tracking', keyFields: 'id', indexes: 'groupId, wabaId', usedBy: 'waba-management', category: 'WhatsApp' },
  { name: 'WhatsAppInbound', purpose: 'Inbound WhatsApp messages', keyFields: 'id', ttl: '30d', indexes: 'contactId, whatsappMessageId', usedBy: 'inbound-whatsapp-handler', category: 'WhatsApp' },
  { name: 'WhatsAppOutbound', purpose: 'Outbound WhatsApp messages', keyFields: 'id', ttl: '30d', indexes: 'contactId, whatsappMessageId, templateName', usedBy: 'outbound-whatsapp', category: 'WhatsApp' },
  { name: 'TemplateAnalytics', purpose: 'WhatsApp template send/delivery tracking', keyFields: 'id', indexes: 'templateName', usedBy: 'template-analytics', category: 'WhatsApp' },
  { name: 'SubmitRequest', purpose: 'WhatsApp Flow submit request submissions', keyFields: 'id', indexes: 'phone, orderId, paymentStatus, paymentReferenceId', usedBy: 'inbound-whatsapp-handler', category: 'Payments' },
  { name: 'ConversationHistory', purpose: 'AI conversation context per phone hash', keyFields: 'phoneHash', indexes: '-', usedBy: 'none (retired)', category: 'AI' },
  { name: 'FlowRegistry', purpose: 'WhatsApp Flow config registry (type, payment, screens, A/B)', keyFields: 'flowId', indexes: 'flowCode, wabaId, category, status', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'FlowSubmission', purpose: 'All flow submissions (generic, all flow types)', keyFields: 'submissionId', indexes: 'phone, flowCode, paymentStatus, paymentRefId, submissionNumber, status, orderId, flowId', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'FlowLog', purpose: 'Audit trail for every flow screen interaction', keyFields: 'logId', ttl: '90d', indexes: 'phone, flowId, flowCode', usedBy: 'inbound-whatsapp-handler', category: 'Flows' },
  { name: 'Invoice', purpose: 'Invoice records', keyFields: 'invoiceId', indexes: 'contactId, status', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceItem', purpose: 'Invoice line items', keyFields: 'invoiceId + itemId', indexes: '-', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceAsset', purpose: 'Invoice generated assets (PNG/PDF)', keyFields: 'assetId', indexes: 'invoiceId', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceDeliveryLog', purpose: 'Invoice delivery tracking (WhatsApp/email)', keyFields: 'id', indexes: 'invoiceId', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoiceSequence', purpose: 'Auto-increment invoice number per FY', keyFields: 'fy', indexes: '-', usedBy: 'invoice-engine', category: 'Payments' },
  { name: 'InvoicePayment', purpose: 'Invoice payment tracking', keyFields: 'id', indexes: 'invoiceId', usedBy: 'invoice-engine, razorpay-webhook', category: 'Payments' },
  { name: 'MetaAnalyticsLog', purpose: 'Meta conversation analytics logs', keyFields: 'id', indexes: '-', usedBy: 'meta-analytics', category: 'Analytics' },
  { name: 'RazorpayWebhookLog', purpose: 'Razorpay webhook event log', keyFields: 'id', ttl: '180d', indexes: 'paymentId, eventType', usedBy: 'razorpay-webhook', category: 'Payments' },
  { name: 'WebhookDedup', purpose: 'Webhook idempotency tracking', keyFields: 'eventId', ttl: '7d', indexes: '-', usedBy: 'inbound-whatsapp-handler', category: 'Core' },
  { name: 'SystemEvent', purpose: 'Persistent system event log', keyFields: 'id', ttl: '180d', indexes: 'eventType, wabaId', usedBy: 'system-cleanup', category: 'Core' },
  { name: 'CatalogCache', purpose: 'WhatsApp Commerce catalog cache', keyFields: 'id', ttl: '7d', indexes: 'catalogId, retailerId', usedBy: 'catalog-management', category: 'Ecommerce' },
];

// ─── Data: Lambda Functions ───
interface LambdaDef { name: string; category: string; trigger: string; tables: string; description: string; apiRoute: string; }
const LAMBDAS: LambdaDef[] = [
  { name: 'contacts', category: 'Core', trigger: 'API Gateway', tables: 'Contact, WhatsAppInbound, WhatsAppOutbound', description: 'Contact CRUD operations', apiRoute: '/contacts' },
  { name: 'auth-middleware', category: 'Core', trigger: 'API GW Authorizer', tables: 'User', description: 'Cognito token validation', apiRoute: '/auth' },
  { name: 'messages-read', category: 'Core', trigger: 'API Gateway', tables: 'WhatsAppInbound, WhatsAppOutbound', description: 'Read messages from all channels', apiRoute: '/messages' },
  { name: 'messages-delete', category: 'Core', trigger: 'API Gateway', tables: 'WhatsAppInbound, WhatsAppOutbound', description: 'Delete messages by ID', apiRoute: '/messages/{id}' },
  { name: 'faq-handler', category: 'Core', trigger: 'API Gateway', tables: 'SystemConfig', description: 'FAQ auto-response engine', apiRoute: '/faq' },
  { name: 'url-shortener', category: 'Core', trigger: 'API Gateway', tables: '-', description: 'Short link creation (wecare.digital/r)', apiRoute: '/r/{code}' },
  { name: 'inbound-whatsapp-handler', category: 'Messaging', trigger: 'API GW Webhook', tables: 'WhatsAppInbound, Contact, MediaFile, WebhookDedup', description: 'Process incoming WhatsApp messages', apiRoute: '/webhook/whatsapp' },
  { name: 'outbound-whatsapp', category: 'Messaging', trigger: 'API Gateway, SQS', tables: 'WhatsAppOutbound', description: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send' },
  { name: 'outbound-sms', category: 'Messaging', trigger: 'API Gateway', tables: 'Messages', description: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send' },
  { name: 'outbound-email', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Send email via Amazon SES', apiRoute: '/email/send' },
  { name: 'plivo-answer', category: 'Messaging', trigger: 'API GW Webhook', tables: 'VoiceCDR', description: 'Plivo PSTN voice webhooks; writes the voice CDR', apiRoute: '/plivo/*' },
  { name: 'sms-aws', category: 'Messaging', trigger: 'API GW, SNS', tables: 'SmsAws', description: 'AWS Pinpoint SMS handler', apiRoute: '/sms-aws' },
  { name: 'voice-aws', category: 'Messaging', trigger: 'API Gateway', tables: 'VoiceAws', description: 'AWS voice call handler', apiRoute: '/voice-aws' },
  { name: 'voice-cdr-read', category: 'Messaging', trigger: 'API Gateway', tables: 'VoiceCDR', description: 'Read voice CDR records', apiRoute: '/voice-cdr-read' },
  { name: 'whatsapp-calling', category: 'Messaging', trigger: 'API GW Webhook', tables: 'WhatsAppCalling', description: 'WhatsApp voice/video call handling', apiRoute: '/whatsapp-calling' },
  { name: 'whatsapp-voice', category: 'Messaging', trigger: 'API Gateway', tables: 'WhatsAppVoice', description: 'WhatsApp voice note processing', apiRoute: '/whatsapp-voice' },
  { name: 'whatsapp-template-management', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Canonical Meta template CRUD, media, validation, library and compatibility routes', apiRoute: '/whatsapp/templates' },
  { name: 'whatsapp-business-api', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Direct Meta Cloud API operations', apiRoute: '/whatsapp/api' },
  { name: 'scheduled-messages', category: 'Messaging', trigger: 'API GW, EventBridge', tables: 'ScheduledMessage', description: 'Schedule messages at specific times', apiRoute: '/scheduled' },
  { name: 'template-analytics', category: 'Messaging', trigger: 'API Gateway', tables: 'TemplateAnalytics', description: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics' },
  { name: 'waba-management', category: 'Messaging', trigger: 'API Gateway', tables: 'WhatsAppGroup', description: 'WABA config and phone management', apiRoute: '/waba' },
  { name: 'meta-analytics', category: 'Messaging', trigger: 'API Gateway', tables: 'MetaAnalyticsLog', description: 'Meta conversation analytics', apiRoute: '/meta-analytics' },
  { name: 'media-cleanup', category: 'Messaging', trigger: 'EventBridge Daily', tables: 'MediaFile', description: 'Clean up expired media from S3', apiRoute: '-' },
  { name: 'push-notifications', category: 'Messaging', trigger: 'API Gateway', tables: '-', description: 'Web push notification delivery', apiRoute: '/push' },
  { name: 'ai-config-management', category: 'Core', trigger: 'API Gateway', tables: 'SystemConfig', description: 'Generic SystemConfig settings API', apiRoute: '/ai/config' },
  { name: 'razorpay-webhook', category: 'Payments', trigger: 'API GW Webhook', tables: 'RazorpayWebhookLog, Payment, InvoicePayment', description: 'Razorpay payment webhook', apiRoute: '/webhook/razorpay' },
  { name: 'payments-read', category: 'Payments', trigger: 'API Gateway', tables: 'Payment', description: 'Read payment records', apiRoute: '/payments' },
  { name: 'invoice-engine', category: 'Payments', trigger: 'API Gateway', tables: 'Invoice, InvoiceItem, InvoiceAsset, InvoicePayment, InvoiceDeliveryLog, InvoiceSequence', description: 'Invoice creation & PDF generation', apiRoute: '/invoices' },
  { name: 'bulk-job-create', category: 'Operations', trigger: 'API Gateway', tables: 'BulkJob, BulkRecipient', description: 'Create bulk messaging jobs', apiRoute: '/bulk/create' },
  { name: 'bulk-job-control', category: 'Operations', trigger: 'API Gateway', tables: 'BulkJob', description: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control' },
  { name: 'bulk-worker', category: 'Operations', trigger: 'SQS', tables: 'BulkRecipient', description: 'Process bulk message queue items', apiRoute: '-' },
  { name: 'dlq-replay', category: 'Operations', trigger: 'API Gateway', tables: 'DLQMessage', description: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay' },
  { name: 'system-cleanup', category: 'Operations', trigger: 'EventBridge Daily', tables: 'SystemEvent', description: 'TTL cleanup and maintenance', apiRoute: '-' },
  { name: 'billing', category: 'Operations', trigger: 'API GW, EventBridge', tables: '-', description: 'AWS billing and usage tracking', apiRoute: '/billing' },
  { name: 'catalog-management', category: 'Ecommerce', trigger: 'Direct invoke (operator)', tables: 'CatalogCache', description: 'WhatsApp catalog sync', apiRoute: '-' },
  { name: 'product-image-gen', category: 'Ecommerce', trigger: 'API Gateway', tables: '-', description: 'Branded product image generation (Pillow)', apiRoute: '/store/image-gen' },
];

// ─── Data: AWS Resources ───
interface AWSResource { name: string; type: string; purpose: string; module: string; env: string; status: string; risk: string; }
const AWS_RESOURCES: AWSResource[] = [
  { name: 'Staff user pool', type: 'Cognito User Pool', purpose: 'User authentication & RBAC', module: 'Auth', env: 'Production', status: 'Active', risk: '' },
  { name: 'Identity pool', type: 'Cognito Identity Pool', purpose: 'Federated identity for AWS access', module: 'Auth', env: 'Production', status: 'Active', risk: '' },
  { name: 'wecare.digital/api', type: 'API Gateway (REST)', purpose: 'Main API endpoint for all Lambda functions', module: 'All', env: 'Production', status: 'Active', risk: '' },
  { name: 'Media bucket', type: 'S3 Bucket', purpose: 'Media storage, invoices, voice, static assets (o/ and secure/d/public/ public, rest of secure/ gated)', module: 'Storage', env: 'Production', status: 'Active', risk: '' },
  { name: DB_TABLES.length + ' DynamoDB Tables', type: 'DynamoDB', purpose: 'Primary database (PAY_PER_REQUEST)', module: 'Data', env: 'Production', status: 'Active', risk: '' },
  { name: '42 Lambda Functions', type: 'Lambda', purpose: 'Backend compute (Python 3.12)', module: 'Backend', env: 'Production', status: 'Active', risk: '' },
  { name: 'Bulk job queue', type: 'SQS Queue', purpose: 'Bulk message job processing', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'Inbound DLQ', type: 'SQS DLQ', purpose: 'Failed inbound message processing', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'Bulk DLQ', type: 'SQS DLQ', purpose: 'Failed bulk message chunks', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'Outbound DLQ', type: 'SQS DLQ', purpose: 'Failed outbound messages', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudWatch Logs (42 groups)', type: 'CloudWatch', purpose: 'Lambda function logs (90d retention)', module: 'Monitoring', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudWatch Alarms', type: 'CloudWatch', purpose: 'Lambda error rate, DLQ depth alerts', module: 'Monitoring', env: 'Production', status: 'Active', risk: '' },
  { name: 'EventBridge Rules', type: 'EventBridge', purpose: 'Scheduled triggers (cleanup, billing, scheduled-messages)', module: 'Operations', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon SES', type: 'SES', purpose: 'Outbound email delivery', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon Pinpoint', type: 'Pinpoint', purpose: 'SMS delivery (AWS channel)', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'IAM Roles (Lambda)', type: 'IAM', purpose: 'Lambda execution roles with least-privilege', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'Secrets Manager', type: 'Secrets Manager', purpose: 'API keys, webhook secrets, payment credentials', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'CloudFront media distribution', type: 'CloudFront', purpose: 'Serves wecare.digital/get/<key> from the media bucket', module: 'Frontend', env: 'Production', status: 'Active', risk: '' },
  { name: 'Route 53', type: 'Route 53', purpose: 'DNS for wecare.digital, mta-sts.wecare.digital and sip.wecare.digital', module: 'Networking', env: 'Production', status: 'Active', risk: '' },
  { name: 'ACM Certificates', type: 'ACM', purpose: 'SSL/TLS certificates for all domains', module: 'Security', env: 'Production', status: 'Active', risk: '' },
  { name: 'SNS Topics', type: 'SNS', purpose: 'SMS delivery notifications, alerts', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
  { name: 'Amazon Polly', type: 'Polly', purpose: 'Text-to-speech for WhatsApp voice messages', module: 'Messaging', env: 'Production', status: 'Active', risk: '' },
];

// ─── Risks & Improvements ───
// Kept in private docs, not in this file: it ships to the browser (audit WEB-4).

// ─── Data: Dependencies ───
interface DepInfo { name: string; version: string; type: 'prod' | 'dev'; status: 'ok' | 'outdated' | 'warning'; note: string; }
const DEPENDENCIES: DepInfo[] = [
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
// lives — the same class of defect the storage-prefix verifier catches. It went
// unnoticed for two days in the handlers because a key at the bucket root still returned
// HTTP 200 from the apex host, so addressing the wrong level errored nowhere.
const STORAGE_PATHS: StoragePath[] = [
  { path: 'secure/d/public/whatsapp/incoming/', purpose: 'Inbound WhatsApp media files', readBy: 'messages-read, contacts', writtenBy: 'inbound-whatsapp-handler' },
  { path: 'secure/d/public/whatsapp/outgoing/', purpose: 'Outbound WhatsApp media files', readBy: 'messages-read', writtenBy: 'outbound-whatsapp' },
  { path: 'secure/d/public/whatsapp/voice/', purpose: 'WhatsApp voice notes', readBy: 'whatsapp-voice', writtenBy: 'inbound-whatsapp-handler' },
  { path: 'secure/d/public/whatsapp/calling-ai/', purpose: 'WhatsApp calling recordings', readBy: 'whatsapp-calling', writtenBy: 'whatsapp-calling' },
  { path: 'secure/d/public/whatsapp/template-headers/', purpose: 'Template header media', readBy: 'whatsapp-templates', writtenBy: 'whatsapp-template-management' },
  { path: 'secure/d/public/whatsapp/downloads/', purpose: 'User-initiated media downloads', readBy: 'Frontend', writtenBy: 'messages-read' },
  { path: 'secure/d/public/Invoice/customer_invoice/', purpose: 'Invoice PNGs. Gated at the edge (customer name, address, amount and GST breakdown), so served only by presigned URL', readBy: 'invoice-engine (presigned), system-cleanup', writtenBy: 'invoice-engine, inbound-whatsapp-handler' },
  { path: 'o/stream/media/reports/', purpose: 'Bulk job reports and exports', readBy: 'Frontend', writtenBy: 'bulk-worker' },
  { path: 'secure/d/public/catalog-deploy/catalog-media/generated/', purpose: 'Product images', readBy: 'catalog-management, Frontend', writtenBy: 'product-image-gen' },
  { path: 'o/stream/media/m/', purpose: 'Logos, branding images (static)', readBy: 'Frontend (CDN)', writtenBy: 'Manual upload' },
  { path: 'secure/d/public/Invoice/fonts/', purpose: 'Invoice receipt fonts (DejaVu Sans Mono)', readBy: 'invoice-engine', writtenBy: 'Manual upload' },
  { path: 'o/stream/media/docs/', purpose: 'Scraped documentation (Markdown)', readBy: 'Frontend', writtenBy: 'docs-scraper' },
  { path: 'secure/d/public/whatsapp/wa-tpl/', purpose: 'Template media named by Meta-APPROVED templates — do not move or rename', readBy: 'Meta (refetch at send time)', writtenBy: 'whatsapp-template-management' },
  { path: 'secure/d/public/whatsapp/whatsapp-calling/', purpose: 'IVR greeting audio (TTS)', readBy: 'whatsapp-calling', writtenBy: 'whatsapp-calling' },
  { path: 'secure/u/', purpose: 'Gated: upload as received — presigned access only', readBy: 'Presigned URL', writtenBy: 'document upload' },
  { path: 'secure/d/', purpose: 'Deliverable rendition — gated, presigned access only, EXCEPT secure/d/public/, which the edge serves publicly', readBy: 'Presigned URL', writtenBy: 'document pipeline' },
];

// ─── Data: Environment Config ───
interface EnvVar { key: string; value: string; sensitive: boolean; category: string; }
const ENV_VARS: EnvVar[] = [
  // Auth
  { key: 'NEXT_PUBLIC_COGNITO_USER_POOL_ID', value: '(build environment)', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_CLIENT_ID', value: '(build environment)', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID', value: '(build environment)', sensitive: false, category: 'Auth' },
  { key: 'NEXT_PUBLIC_COGNITO_OAUTH_DOMAIN', value: '(build environment)', sensitive: false, category: 'Auth' },
  // App
  { key: 'NEXT_PUBLIC_APP_URL', value: 'https://wecare.digital/', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_API_BASE', value: 'https://wecare.digital/api', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_SEND_MODE', value: 'LIVE', sensitive: false, category: 'App' },
  { key: 'NEXT_PUBLIC_ENV', value: 'production', sensitive: false, category: 'App' },
  // Other build-time values
  { key: 'NEXT_PUBLIC_AWS_REGION', value: 'us-east-1', sensitive: false, category: 'AWS' },
  { key: 'NEXT_PUBLIC_DEFAULT_GSTIN', value: '(build environment)', sensitive: true, category: 'Payment' },
  // Payment
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_ID', value: '(build environment)', sensitive: false, category: 'Payment' },
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_DISPLAY', value: '+91 93309 94400', sensitive: false, category: 'Payment' },
  { key: 'NEXT_PUBLIC_PAYMENT_PHONE_NAME', value: 'WECARE.DIGITAL', sensitive: false, category: 'Payment' },
  // Analytics (empty)
  // CORRECTED 2026-09-30, updated 2026-10-20. The authoritative GA4 Measurement ID for the
  // WECARE.DIGITAL property (550346663, stream 16126298947) is G-6GW8JXKKT7. GA4 is fired
  // EXCLUSIVELY by the GTM container GTM-TXZ8JT78 — there is no direct gtag and
  // NEXT_PUBLIC_GA_MEASUREMENT_ID is unset by design. The previously-recorded container id
  // G-GNRPFFBXMF and the long-retired G-S3G6REP6Q7 are both superseded by G-6GW8JXKKT7.
  // MEASURED 2026-10-27: G-6GW8JXKKT7 is a destination of the Google tag AW-18396505964, so the
  // container's ONE Google tag sends both Google Ads and GA4. Container version 11 removed the
  // extra GA4 tags that version 10 had pointed at G-6GW8JXKKT7, which sent 5 page_views per
  // load. GA4 still receives nothing while all four consent signals stay denied (see the
  // change-authority-matrix entry of 2026-10-27).
  //
  // This row originally read `G-S3G6REP6Q7` and presented it as live config on a staff
  // dashboard — a value that was not live and was in no container. That id was real once:
  // `_app.tsx` records a direct gtag.js snippet that fired it alongside the container,
  // double-counting every pageview; the snippet was removed and the id went with it. The
  // lesson stands: a dashboard must not present stale ids as live — a reader trusts it
  // instead of measuring, and then looks for analytics data in a property that receives none.
  { key: 'NEXT_PUBLIC_GA_MEASUREMENT_ID', value: '(unset — GA4 is fired by GTM-TXZ8JT78; authoritative Measurement ID G-6GW8JXKKT7)', sensitive: false, category: 'Analytics' },
  { key: 'NEXT_PUBLIC_FB_APP_ID', value: '(unused; the Facebook SDK is not loaded)', sensitive: false, category: 'Analytics' },
  // Payment identifiers — env-sourced (RAZORPAY_MID / RAZORPAY_UPI_ID), not secrets. A merchant
  // id and a UPI payee address are public by construction (they appear in every deep link and QR).
  // Authoritative values owner-confirmed 2026-09-30 against the live Meta config; an earlier
  // merchant-id / UPI-VPA pair was stale and has been retired.
  { key: 'Razorpay MID (env RAZORPAY_MID)', value: '(server-side)', sensitive: false, category: 'Payments — Identifier' },
  { key: 'Razorpay UPI VPA', value: '(env RAZORPAY_UPI_ID)', sensitive: false, category: 'Payments — Identifier' },
  // Secrets Manager entries (server-side, properly stored)
  { key: 'Meta system-user token', value: '(Secrets Manager)', sensitive: true, category: 'Secrets Manager ✓' },
  { key: 'WhatsApp Flow private key', value: '(Secrets Manager)', sensitive: true, category: 'Secrets Manager ✓' },
];

// ─── Data: Frontend Routes ───
interface FrontendRoute { path: string; label: string; backend: string; tables: string; }
const FRONTEND_ROUTES: FrontendRoute[] = [
  // Platform — canonical workspace. Static inventory rows are labelled as snapshots, not live control-plane readback.
  { path: '/workspace/platform?view=system-architecture', label: 'Architecture snapshot', backend: '(this page)', tables: '-' },
  { path: '/workspace/platform?view=lambda-functions', label: 'Lambda inventory snapshot', backend: '(static data)', tables: '-' },
  { path: '/workspace/platform?view=code-repo', label: 'Code Repo', backend: '(static data)', tables: '-' },
  // WhatsApp
  { path: '/workspace/communications?view=inbox&channel=whatsapp', label: 'WhatsApp Inbox', backend: 'messages-read, inbound-whatsapp, outbound-whatsapp', tables: 'WhatsAppInbound, WhatsAppOutbound, Contact' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=templates', label: 'WA Templates', backend: 'whatsapp-templates, whatsapp-template-management', tables: 'TemplateAnalytics' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=campaign', label: 'WA Campaign', backend: 'outbound-whatsapp, bulk-job-create', tables: 'BulkJob, BulkRecipient, WhatsAppOutbound' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=flows', label: 'WA Flows', backend: 'whatsapp-business-api', tables: 'FlowRegistry, FlowSubmission' },
  { path: '/workspace/communications?view=manage&section=flows', label: 'WA Flow Hub', backend: 'whatsapp-business-api', tables: 'FlowRegistry, FlowSubmission, FlowLog' },
  { path: '/workspace/communications?view=manage&section=flows', label: 'WA Flow Responses', backend: 'inbound-whatsapp-handler', tables: 'FlowSubmission, FlowLog, SubmitRequest' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=calling', label: 'WA Calling', backend: 'whatsapp-calling', tables: 'WhatsAppCalling' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=groups', label: 'WA Groups', backend: 'waba-management', tables: 'WhatsAppGroup' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=scripts', label: 'WA Scripts', backend: 'outbound-whatsapp', tables: '-' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=auto-response', label: 'WA Auto Response', backend: 'ai-config-management', tables: 'SystemConfig' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=waba', label: 'WABA Dashboard', backend: 'waba-management, meta-analytics', tables: 'MetaAnalyticsLog' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=profile', label: 'WA Business Profile', backend: 'whatsapp-business-api', tables: '-' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=webhooks', label: 'WA Webhooks', backend: 'inbound-whatsapp-handler', tables: 'WebhookDedup, SystemEvent' },
  { path: '/workspace/communications?view=manage&section=whatsapp&tool=migration', label: 'WA Migration', backend: 'waba-management', tables: '-' },
  { path: '/workspace/engage/logs', label: 'Message Logs (all channels)', backend: 'messages-read', tables: 'MessagesTable' },
  { path: '/workspace/communications?view=manage&section=whatsapp', label: 'WA Management', backend: 'waba-management', tables: 'SystemConfig' },
  // SMS
  // Voice
  { path: '/workspace/engage/channels?tab=voice', label: 'Voice Out', backend: 'voice-aws', tables: 'VoiceAws' },
  // Email / RCS / Push
  { path: '/workspace/engage/channels?tab=email', label: 'Email', backend: 'outbound-email', tables: '-' },
  { path: '/workspace/engage/channels?tab=rcs', label: 'RCS', backend: '(planned)', tables: '-' },
  { path: '/workspace/engage/channels?tab=push', label: 'Push', backend: 'push-notifications', tables: '-' },
  { path: '/workspace/engage/logs', label: 'Message Logs', backend: 'messages-read', tables: 'WhatsAppInbound, WhatsAppOutbound, SmsAws' },
  // Pay
  { path: '/workspace/payments?view=collect', label: 'Payments', backend: 'payments-read, razorpay-webhook, invoice-engine', tables: 'Payment, Invoice, InvoiceItem, RazorpayWebhookLog' },
  { path: '/workspace/payments?view=collect', label: 'Pay Flow', backend: 'invoice-engine, razorpay-webhook', tables: 'Invoice, InvoiceItem, InvoicePayment, InvoiceDeliveryLog' },

  // Other
  { path: '/workspace/customers', label: 'Contacts', backend: 'contacts', tables: 'Contact' },
  { path: '/workspace/access', label: 'Access Control', backend: 'auth-middleware', tables: 'User' },
  { path: '/workspace/communications?view=manage&section=links', label: 'URL Shortener', backend: 'url-shortener', tables: '-' },
  // '/workspace/link/create' ("Create Link") was listed here. Removed 2026-09-25 with the page: a
  // ComingSoon stub naming four features, never in the nav, and this row was its only
  // reference in the repo.
  { path: '/workspace/service?view=requests', label: 'Forms', backend: 'whatsapp-business-api', tables: 'FlowRegistry' },
  { path: '/workspace/service?view=requests', label: 'Customer Service Hub', backend: 'whatsapp-business-api, inbound-whatsapp-handler', tables: 'FlowRegistry, FlowSubmission, FlowLog, SubmitRequest' },
  // Was '[retired public path]'. The public page was deleted on owner instruction; the faq-handler backend
  // and SystemConfig table are unchanged and are driven from the dashboard route.
  { path: '/workspace/service?view=requests&action=faq', label: 'FAQ', backend: 'faq-handler', tables: 'SystemConfig' },
  { path: '/relay-os', label: 'Relay OS', backend: '(public product page)', tables: '-' },
  // '/studio' REMOVED on owner instruction. The slug is retired and no page exists for it
  // in src/pages, so listing it here described a route that 404s - and this table is read
  // as the map of what the system actually serves. Header.test.tsx separately guards
  // "Studio" out of the public menu.
  { path: '/workspace/task', label: 'Task', backend: 'conversation-meta', tables: 'ConversationMetaTable' },
];

// ─── Data: Code Map ───
interface CodeFolder { path: string; purpose: string; files: string; linkedTo: string; }
const CODE_MAP: CodeFolder[] = [
  { path: 'src/pages/', purpose: 'Next.js page routes (Pages Router)', files: 'generated routes', linkedTo: 'Frontend routing' },
  { path: 'src/pages/workspace/platform/', purpose: 'Canonical Platform workspace hub', files: '1 page', linkedTo: '/workspace/platform' },
  { path: 'src/components/workspace/platform/', purpose: 'Platform tools embedded by the canonical hub', files: '7 components', linkedTo: '/workspace/platform?view=*' },
  { path: 'src/components/workspace/whatsapp/', purpose: 'WhatsApp tools embedded by Communications', files: 'shared components', linkedTo: '/workspace/communications?view=manage&section=whatsapp' },
  { path: 'src/pages/workspace/engage/', purpose: 'Active channels, inbox, logs and partner account pages', files: 'active routes', linkedTo: '/workspace/engage/channels?tab=sms' },
  { path: 'src/components/', purpose: 'Reusable UI components', files: '~25 components', linkedTo: 'All pages' },
  { path: 'src/components/ui/', purpose: 'Base UI primitives (Button, Modal, Tabs, Table)', files: '~10 components', linkedTo: 'All pages' },
  { path: 'src/components/dashboard/', purpose: 'Shared workspace widgets', files: '~5 components', linkedTo: '/workspace/*' },
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
  { path: 'amplify/functions/ai/', purpose: 'MCP servers and the settings API (5)', files: '5 dirs', linkedTo: 'DynamoDB' },
  { path: 'amplify/functions/core/', purpose: 'Core Lambda functions (6)', files: '6 dirs', linkedTo: 'DynamoDB, S3' },
  { path: 'amplify/functions/messaging/', purpose: 'Messaging Lambda functions (22)', files: '22 dirs', linkedTo: 'DynamoDB, S3, SQS, SES, Pinpoint' },
  { path: 'amplify/functions/payments/', purpose: 'Payment Lambda functions (3)', files: '3 dirs', linkedTo: 'DynamoDB, Razorpay' },
  { path: 'amplify/functions/operations/', purpose: 'Operations Lambda functions (6)', files: '6 dirs', linkedTo: 'DynamoDB, SQS, EventBridge' },
  { path: 'amplify/functions/ecommerce/', purpose: 'Ecommerce Lambda functions (3)', files: '3 dirs', linkedTo: 'DynamoDB, S3' },
  { path: 'amplify/functions/shared/', purpose: 'Shared utilities and config', files: '3 files', linkedTo: 'All Lambda functions' },
];

// ─── Data: Lambda Detailed (with env vars, runtime, memory) ───
interface LambdaDetailed { name: string; displayName: string; category: string; runtime: string; timeout: number; memory: number; description: string; apiRoute: string; envVars: Record<string, string>; triggers: string[]; status: 'active' | 'warning' | 'error'; }
const LAMBDA_DETAILED: LambdaDetailed[] = [
  { name: 'contacts', displayName: 'Contacts', category: 'Core', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'CRUD operations for contacts', apiRoute: '/contacts', envVars: { CONTACTS_TABLE: 'Contacts table', INBOUND_TABLE: 'WhatsAppInbound table', OUTBOUND_TABLE: 'WhatsAppOutbound table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'auth-middleware', displayName: 'Auth Middleware', category: 'Core', runtime: 'Python 3.12', timeout: 10, memory: 128, description: 'Cognito token validation for API Gateway', apiRoute: '/auth', envVars: { USER_POOL_ID: '(staff user pool)', CLIENT_ID: '*' }, triggers: [ 'API Gateway Authorizer' ], status: 'active' },
  { name: 'messages-read', displayName: 'Messages Read', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'Read messages from all channels', apiRoute: '/messages', envVars: { INBOUND_TABLE: 'WhatsAppInbound table', OUTBOUND_TABLE: 'WhatsAppOutbound table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'messages-delete', displayName: 'Messages Delete', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Delete messages by ID', apiRoute: '/messages/{id}', envVars: { INBOUND_TABLE: 'WhatsAppInbound table', OUTBOUND_TABLE: 'WhatsAppOutbound table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'faq-handler', displayName: 'FAQ Handler', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'FAQ auto-response engine', apiRoute: '/faq', envVars: { FAQ_TABLE: 'FAQ table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'inbound-whatsapp', displayName: 'Inbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 512, description: 'Process incoming WhatsApp messages, media, reactions', apiRoute: '/webhook/whatsapp', envVars: { INBOUND_TABLE: 'WhatsAppInbound table', CONTACTS_TABLE: 'Contacts table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'outbound-whatsapp', displayName: 'Outbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send', envVars: { OUTBOUND_TABLE: 'WhatsAppOutbound table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway', 'SQS' ], status: 'active' },
  { name: 'outbound-sms', displayName: 'Outbound SMS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send', envVars: { MESSAGES_TABLE: 'Messages table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'outbound-email', displayName: 'Outbound Email', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send email via Amazon SES', apiRoute: '/email/send', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'plivo-answer', displayName: 'Plivo Answer', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Plivo PSTN voice webhooks; writes the voice CDR', apiRoute: '/plivo/*', envVars: { VOICE_CDR_TABLE: 'VoiceCDR table' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'whatsapp-calling', displayName: 'WhatsApp Calling', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'WhatsApp voice/video call handling', apiRoute: '/whatsapp-calling', envVars: { CALLING_TABLE: 'WhatsAppVoice table' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'scheduled-messages', displayName: 'Scheduled Messages', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Schedule and send messages at specific times', apiRoute: '/scheduled', envVars: { SCHEDULED_TABLE: 'ScheduledMessage table' }, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },
  { name: 'bulk-worker', displayName: 'Bulk Worker', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 512, description: 'Process bulk message queue items', apiRoute: '-', envVars: { QUEUE_URL: 'bulk job queue' }, triggers: [ 'SQS' ], status: 'active' },
  { name: 'razorpay-webhook', displayName: 'Razorpay Webhook', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Razorpay payment webhook handler', apiRoute: '/webhook/razorpay', envVars: { WEBHOOK_SECRET: '(env var)', PAYMENTS_TABLE: 'RazorpayWebhookLog table' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'invoice-engine', displayName: 'Invoice Engine', category: 'Payments', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Invoice creation, PDF generation, payment links', apiRoute: '/invoices', envVars: { INVOICE_TABLE: 'Invoice table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'catalog-management', displayName: 'Catalog Management', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WhatsApp Commerce catalog sync', apiRoute: '-', envVars: {}, triggers: [ 'Direct invoke (operator)' ], status: 'active' },
  { name: 'product-image-gen', displayName: 'Product Image Gen', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Branded product image generation (Pillow)', apiRoute: '/store/image-gen', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'whatsapp-voice', displayName: 'WhatsApp Voice', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'TTS voice notes via Polly, audio processing', apiRoute: '/whatsapp-voice', envVars: { VOICE_TABLE: 'WhatsAppVoice table', MEDIA_BUCKET: 'media bucket' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'whatsapp-templates', displayName: 'WhatsApp Templates', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Template CRUD via Meta Graph API', apiRoute: '/whatsapp/templates', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'whatsapp-template-mgmt', displayName: 'Template Management', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Advanced template operations', apiRoute: '/whatsapp/template-mgmt', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'whatsapp-business-api', displayName: 'WhatsApp Business API', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Meta Graph API wrapper — flows, payments, checkout', apiRoute: '/whatsapp/api', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'waba-management', displayName: 'WABA Management', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WABA config, phone management, groups', apiRoute: '/waba', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'sms-aws', displayName: 'SMS AWS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS Pinpoint SMS handler', apiRoute: '/sms-aws', envVars: { SMS_TABLE: 'SmsAws table' }, triggers: [ 'API Gateway', 'SNS' ], status: 'active' },
  { name: 'voice-aws', displayName: 'Voice AWS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS voice call handler', apiRoute: '/voice-aws', envVars: { VOICE_TABLE: 'VoiceAws table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'voice-cdr-read', displayName: 'Voice CDR Read', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read voice CDR records', apiRoute: '/voice-cdr-read', envVars: { CDR_TABLE: 'VoiceCDR table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'template-analytics', displayName: 'Template Analytics', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'media-cleanup', displayName: 'Media Cleanup', category: 'Messaging', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'Clean up expired media from S3', apiRoute: '-', envVars: { MEDIA_BUCKET: 'media bucket' }, triggers: [ 'EventBridge Daily' ], status: 'active' },
  { name: 'push-notifications', displayName: 'Push Notifications', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Web push notification delivery', apiRoute: '/push', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'ai-config-management', displayName: 'Settings API', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Generic SystemConfig settings API', apiRoute: '/ai/config', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'payments-read', displayName: 'Payments Read', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read payment records', apiRoute: '/payments', envVars: { PAYMENTS_TABLE: 'Payment table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'bulk-job-create', displayName: 'Bulk Job Create', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Create bulk messaging jobs', apiRoute: '/bulk/create', envVars: { BULK_TABLE: 'BulkJob table' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'bulk-job-control', displayName: 'Bulk Job Control', category: 'Operations', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'dlq-replay', displayName: 'DLQ Replay', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'system-cleanup', displayName: 'System Cleanup', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'TTL cleanup and maintenance', apiRoute: '-', envVars: {}, triggers: [ 'EventBridge Daily' ], status: 'active' },
  { name: 'billing', displayName: 'Billing', category: 'Operations', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS billing and usage tracking', apiRoute: '/billing', envVars: {}, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },
];
const LAMBDA_DETAIL_CATEGORIES = [ 'All', ...Array.from( new Set( LAMBDA_DETAILED.map( l => l.category ) ) ) ];

// ─── Data: Code Repository Assets ───
interface CodeAsset { id: string; category: string; name: string; description: string; path: string; type: string; status?: string; }
const CODE_ASSETS: CodeAsset[] = [
  // WhatsApp Flows
  { id: 'flow-sub', category: 'WhatsApp Flows', name: 'F001 · Subscribe / Profile', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/subscribe.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-review', category: 'WhatsApp Flows', name: 'F002 · Leave Review', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/f002-leave-review.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-drop', category: 'WhatsApp Flows', name: 'F003 · Drop Docs', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/f003-drop-docs.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-submit', category: 'WhatsApp Flows', name: 'F004 · Submit Request', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/submit-request.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-amend', category: 'WhatsApp Flows', name: 'Request Amendment', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/request-amendment.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-pickup', category: 'WhatsApp Flows', name: 'Pickup Request', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/request-pickup.json', type: 'Flow JSON', status: 'Published' },
  { id: 'flow-shipping', category: 'WhatsApp Flows', name: 'F006 · Track Shipment', description: 'Retained canonical published Meta Flow asset.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/published/shipments.json', type: 'Flow JSON', status: 'Published' },
  // Track Request is a service endpoint, not a Meta Flow.
  { id: 'ss-track', category: 'Customer Service Flows', name: 'Track Request', description: 'Order/request status via service API and /orders/.', path: 'GET /wa-business/service/track/{orderId}', type: 'API', status: 'Active' },
  { id: 'ss-faq', category: 'Customer Service Flows', name: 'FAQ', description: 'Help from the Workspace FAQ configuration.', path: '/workspace/service?view=requests&action=faq', type: 'Page Link', status: 'Active' },
  // Frontend Pages
  { id: 'p-control', category: 'Frontend Pages', name: 'Project Control Center', description: '18-tab system architecture dashboard, single source of truth.', path: 'src/components/workspace/platform/SystemArchitecture.tsx', type: 'Component' },
  { id: 'p-wa-inbox', category: 'Frontend Pages', name: 'WhatsApp Inbox', description: 'Unified inbox component embedded in Communications.', path: 'src/components/workspace/whatsapp/inbox.tsx', type: 'Component' },
  { id: 'p-wa-templates', category: 'Frontend Pages', name: 'WhatsApp Templates', description: 'Template management — create, edit, send, analytics.', path: 'src/components/workspace/whatsapp/templates.tsx', type: 'Component' },
  { id: 'p-wa-flows', category: 'Frontend Pages', name: 'WhatsApp Flows', description: 'Flow builder and management for WhatsApp Business Flows.', path: 'src/components/workspace/whatsapp/flows.tsx', type: 'Component' },
  { id: 'p-wa-flowhub', category: 'Frontend Pages', name: 'Flow Hub', description: 'Centralized flow registry, submissions, and analytics.', path: 'src/components/workspace/whatsapp/flow-hub.tsx', type: 'Component' },
  { id: 'p-wa-calling', category: 'Frontend Pages', name: 'WhatsApp Calling', description: 'Voice/video call logs and WebRTC integration.', path: 'src/components/workspace/whatsapp/calling.tsx', type: 'Component' },
  { id: 'p-wa-groups', category: 'Frontend Pages', name: 'WhatsApp Groups', description: 'Group management — create, participants, messaging.', path: 'src/components/workspace/whatsapp/groups.tsx', type: 'Component' },
  { id: 'p-pay', category: 'Frontend Pages', name: 'Payments', description: 'Payment dashboard — Razorpay transactions.', path: 'src/pages/workspace/payments/index.tsx', type: 'Page' },
  { id: 'p-pay-flow', category: 'Frontend Pages', name: 'Pay Flow', description: 'WhatsApp payment flow — invoice + collect via chat.', path: 'src/components/workspace/pay/PayFlow.tsx', type: 'Component' },
  { id: 'p-contacts', category: 'Frontend Pages', name: 'Contacts', description: 'Contact management with opt-in, addresses, BSUID.', path: 'src/pages/workspace/customers/index.tsx', type: 'Page' },
  { id: 'p-store', category: 'Frontend Pages', name: 'Shop', description: 'Public Shop catalogue.', path: 'src/pages/shop/index.tsx', type: 'Page' },
  // Core Lambdas
  { id: 'l-auth', category: 'Core Lambdas', name: 'Auth Middleware', description: 'Cognito JWT validation, API Gateway authorizer.', path: 'amplify/functions/core/auth-middleware/handler.py', type: 'Lambda' },
  { id: 'l-contacts', category: 'Core Lambdas', name: 'Contacts', description: 'CRUD for contacts with structured addresses.', path: 'amplify/functions/core/contacts/handler.py', type: 'Lambda' },
  { id: 'l-msg-read', category: 'Core Lambdas', name: 'Messages Read', description: 'Read messages from all channels with media pre-signed URLs.', path: 'amplify/functions/core/messages-read/handler.py', type: 'Lambda' },
  { id: 'l-msg-del', category: 'Core Lambdas', name: 'Messages Delete', description: 'Delete messages by ID from inbound/outbound tables.', path: 'amplify/functions/core/messages-delete/handler.py', type: 'Lambda' },
  { id: 'l-faq', category: 'Core Lambdas', name: 'FAQ Handler', description: 'FAQ auto-response engine from SystemConfig.', path: 'amplify/functions/core/faq-handler/handler.py', type: 'Lambda' },
  { id: 'l-url', category: 'Core Lambdas', name: 'URL Shortener', description: 'Short link creation and redirect through wecare.digital/r.', path: 'amplify/functions/core/url-shortener/handler.py', type: 'Lambda' },
  // WhatsApp Lambdas
  { id: 'l-inbound', category: 'WhatsApp Lambdas', name: 'Inbound WhatsApp', description: 'Main webhook handler — messages, keyword triggers, flow routing, AI, media.', path: 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py', type: 'Lambda' },
  { id: 'l-outbound', category: 'WhatsApp Lambdas', name: 'Outbound WhatsApp', description: 'Send WhatsApp messages — text, media and approved templates.', path: 'amplify/functions/messaging/outbound-whatsapp/handler.py', type: 'Lambda' },
  { id: 'l-wa-biz', category: 'WhatsApp Lambdas', name: 'WhatsApp Business API', description: 'Meta Graph API wrapper — flows, payments, checkout, business profile.', path: 'amplify/functions/messaging/whatsapp-business-api/handler.py', type: 'Lambda' },
  { id: 'l-wa-calling', category: 'WhatsApp Lambdas', name: 'WhatsApp Calling', description: 'Voice/video call webhook handler and SDP relay.', path: 'amplify/functions/messaging/whatsapp-calling/handler.py', type: 'Lambda' },
  { id: 'l-wa-voice', category: 'WhatsApp Lambdas', name: 'WhatsApp Voice', description: 'TTS voice notes via Polly, audio message processing.', path: 'amplify/functions/messaging/whatsapp-voice/handler.py', type: 'Lambda' },
  { id: 'l-wa-tmpl-mgmt', category: 'WhatsApp Lambdas', name: 'WhatsApp Template Management', description: 'Canonical Meta template lifecycle — CRUD, validation, library, carousel, media, analytics, and batch operations.', path: 'amplify/functions/messaging/whatsapp-template-management/handler.py', type: 'Lambda' },
  { id: 'l-waba', category: 'WhatsApp Lambdas', name: 'WABA Management', description: 'WABA config, phone management, group operations.', path: 'amplify/functions/messaging/waba-management/handler.py', type: 'Lambda' },
  // Messaging Lambdas
  { id: 'l-sms-out', category: 'Messaging Lambdas', name: 'Outbound SMS', description: 'Send SMS via AWS End User Messaging.', path: 'amplify/functions/messaging/outbound-sms/handler.py', type: 'Lambda' },
  { id: 'l-email', category: 'Messaging Lambdas', name: 'Outbound Email', description: 'Send email via Amazon SES.', path: 'amplify/functions/messaging/outbound-email/handler.py', type: 'Lambda' },
  { id: 'l-plivo-answer', category: 'Messaging Lambdas', name: 'Plivo Answer', description: 'Plivo PSTN voice webhooks; writes the voice CDR.', path: 'amplify/functions/messaging/plivo-answer/handler.py', type: 'Lambda' },
  { id: 'l-scheduled', category: 'Messaging Lambdas', name: 'Scheduled Messages', description: 'Schedule and send messages at specific times.', path: 'amplify/functions/messaging/scheduled-messages/handler.py', type: 'Lambda' },
  { id: 'l-push', category: 'Messaging Lambdas', name: 'Push Notifications', description: 'Web push notification delivery.', path: 'amplify/functions/messaging/push-notifications/handler.py', type: 'Lambda' },
  // AI
  { id: 'l-ai-config', category: 'Core', name: 'Settings API', description: 'Generic SystemConfig settings API', path: 'amplify/functions/ai/ai-config-management/handler.py', type: 'Lambda' },
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
  { id: 'l-catalog', category: 'Ecommerce', name: 'Catalog Management', description: 'WhatsApp Commerce catalog sync and product management.', path: 'amplify/functions/ecommerce/catalog-management/handler.py', type: 'Lambda' },
  { id: 'l-img-gen', category: 'Ecommerce', name: 'Product Image Gen', description: 'Branded product image generation (Pillow).', path: 'amplify/functions/ecommerce/product-image-gen/handler.py', type: 'Lambda' },
];
const CODE_ASSET_CATEGORIES = [ 'All', ...Array.from( new Set( CODE_ASSETS.map( a => a.category ) ) ) ];

// ─── Data: WhatsApp Bot Menu (Persistent Menu / Welcome Message) ───
interface BotMenuItem { row: number; section: string; icon: string; title: string; description: string; action: string; }
const BOT_MENU: BotMenuItem[] = [
  { row: 1, section: 'Start Here', icon: '🚀', title: 'Customer Service', description: 'Requests, appointments, documents, and support', action: 'Opens Self-service list' },
  { row: 2, section: 'Start Here', icon: '🔔', title: 'Subscribe', description: 'Save your details for faster service on WECARE.DIGITAL', action: 'Opens subscribe form' },
  { row: 3, section: 'Start Here', icon: '🆔', title: 'Find Profile ID', description: 'Locate your subscription or profile ID', action: 'Opens ID lookup' },
  { row: 4, section: 'Start Here', icon: '💳', title: 'Make a Payment', description: 'Pay an invoice or complete a pending payment', action: 'Opens payment lookup' },
  { row: 5, section: 'Explore WECARE', icon: '🛍️', title: 'Explore Store', description: 'Browse services, brands, and offers', action: 'CTA link → wecare.digital' },
  { row: 6, section: 'Explore WECARE', icon: '🎁', title: 'Perks', description: 'Open Perks on WhatsApp', action: 'CTA link → wa.me/message/377GALDW4E26F1' },
  { row: 7, section: 'Explore WECARE', icon: '🇮🇳', title: 'WECARE.DIGITAL', description: 'Discover WECARE.DIGITAL and services', action: 'Info text + evolving services' },
  // The action was 'CTA link → wecare.digital/faq' until the public [retired public path] page was deleted;
  // that URL now 404s, so the row would have sent a WhatsApp user to a dead link. The answer
  // is delivered in chat by faq-handler from SystemConfig instead.
  { row: 8, section: 'Help & Answers', icon: '❓', title: 'FAQs', description: 'Find answers to common questions', action: 'Answered in chat by faq-handler' },
  { row: 9, section: 'Help & Answers', icon: '💛', title: 'About WECARE.DIGITAL', description: 'Learn more about WECARE.DIGITAL', action: 'CTA link → wecare.digital' },
];

// ─── Data: Customer service forms and website links ───
interface CustomerServiceItem { row: number; section: string; icon: string; title: string; description: string; flowId: string; keywords: string; }
const CUSTOMER_SERVICE_FORMS: CustomerServiceItem[] = [
  { row: 1, section: 'New Request', icon: '📋', title: 'Submit Request', description: 'Start a new support request', flowId: canonicalFlowId('submit_request')!, keywords: 'submit request, sr, raise request' },
  { row: 2, section: 'Request Status', icon: '🔍', title: 'Track Request', description: 'Check the status of your request', flowId: canonicalFlowId('track_request') ?? '-', keywords: 'track request, track, status' },
  { row: 3, section: 'Existing Request', icon: '✏️', title: 'Amend Request', description: 'Edit or correct a submitted request', flowId: canonicalFlowId('amend_request') ?? '-', keywords: 'amend request, amend, change' },
  { row: 4, section: 'Schedule', icon: '📅', title: 'Appointment', description: 'Schedule a consultation or service visit', flowId: '-', keywords: 'appointment, schedule, meeting' },
  { row: 5, section: 'Medical Tourism', icon: '💊', title: 'RX Slot', description: 'Schedule a medical tourism or prescription-related visit', flowId: '-', keywords: 'rx slot, rx, prescription' },
  { row: 6, section: 'Documents', icon: '📄', title: 'Drop Docs', description: 'Send supporting documents for your request', flowId: canonicalFlowId('drop_docs') ?? '-', keywords: 'drop docs, documents, upload' },
  { row: 7, section: 'Business Support', icon: '🏢', title: 'Enterprise Assist', description: 'Corporate, B2B, and bulk enquiries', flowId: '-', keywords: 'enterprise, b2b, corporate' },
  // flowId and keywords mirror DEFAULT_FLOW_TRIGGERS['leave_review'] in the inbound handler,
  // same order, via src/lib/reviewEntry.ts.
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
  BOT_MENU.forEach( m => entries.push( { type: 'Bot Menu', name: `${m.icon} ${m.title}`, detail: m.description, category: m.section } ) );
  CUSTOMER_SERVICE_FORMS.forEach( m => entries.push( { type: 'Customer Service', name: `${m.icon} ${m.title}`, detail: m.description, category: m.section } ) );
  return entries;
}

// ─── Last Scan Timestamp ───
// Dynamic — updated by auto-refresh hook

// ─── Main Component ───
const SystemArchitecturePage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const { lastRefresh, isAutoRefresh, refresh, toggleAutoRefresh } = useAutoRefresh( 60000 );
  const LAST_SCAN = lastRefresh.toISOString().slice( 0, 16 ).replace( 'T', ' ' );
  const [ activeTab, setActiveTab ] = useState( 'overview' );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ tableFilter, setTableFilter ] = useState( 'All' );
  const [ lambdaFilter, setLambdaFilter ] = useState( 'All' );
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
          { label: 'Customer Service Flows', value: `${CUSTOMER_SERVICE_FORMS.length}`, color: C.greenBg, text: C.green },
        ].map( s => (
          <div key={ s.label } style={ statCard( s.color, s.text ) }>
            <div style={ { fontSize: 'var(--h1)', fontWeight: 800, color: s.text } }>{ s.value }</div>
            <div style={ { fontSize: 'var(--text-xs)', fontWeight: 500, color: C.textMuted, marginTop: 2 } }>{ s.label }</div>
          </div>
        ) ) }
      </div>

      {/* System Summary */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>System Summary</h3>
        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, fontSize: 'var(--text-sm)', color: C.text } }>
          <div>
            <div style={ label }>Platform</div>
            <div style={ { marginTop: 4 } }>Next.js 16 + React 19 + AWS Amplify Gen 2</div>
          </div>
          <div>
            <div style={ label }>AWS Account</div>
            <div style={ { marginTop: 4 } }>Production account (us-east-1)</div>
          </div>
          <div>
            <div style={ label }>Domain</div>
            <div style={ { marginTop: 4 } }>wecare.digital / wecare.digital/api</div>
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
            <div style={ { marginTop: 4 } }>S3 media bucket — secure/u/ + secure/d/public/ + o/stream/media/</div>
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
            <div style={ label }>Mobile</div>
            <div style={ { marginTop: 4 } }>Capacitor (iOS + Android)</div>
          </div>
          <div>
            <div style={ label }>Last Scan</div>
            <div style={ { marginTop: 4 } }>{ LAST_SCAN }</div>
          </div>
        </div>
      </div>

      {/* WhatsApp Bot Menu */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>WhatsApp Bot Menu (Persistent Menu)</h3>
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: '0 0 12px' } }>9 menu items across 3 sections — shown to users when they open the WhatsApp chat.</p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
            <thead>
              <tr style={ { borderBottom: `2px solid ${C.border}` } }>
                { [ '#', 'Section', 'Title', 'Description', 'Action' ].map( h => (
                  <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
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
                  <td style={ { padding: '8px 10px', color: C.textMuted, fontSize: 'var(--text-xs)' } }>{ m.action }</td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      </div>
      {/* Customer Service Sub-Menu */ }
      <div style={ card() }>
        <h3 style={ sectionTitle }>🚀 Customer service forms and website links</h3>
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: '0 0 12px' } }>9 customer-service options — triggered when user taps &quot;🚀 Customer Service&quot; from the bot menu. Each row opens a WhatsApp Flow.</p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
            <thead>
              <tr style={ { borderBottom: `2px solid ${C.border}` } }>
                { [ '#', 'Section', 'Title', 'Description', 'Flow ID', 'Keywords' ].map( h => (
                  <th key={ h } style={ { textAlign: 'left', padding: '8px 10px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
                ) ) }
              </tr>
            </thead>
            <tbody>
              { CUSTOMER_SERVICE_FORMS.map( m => (
                <tr key={ m.row } style={ { borderBottom: `1px solid ${C.border}` } }>
                  <td style={ { padding: '8px 10px', color: C.textMuted, fontWeight: 600 } }>{ m.row }</td>
                  <td style={ { padding: '8px 10px' } }><span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ m.section }</span></td>
                  <td style={ { padding: '8px 10px', fontWeight: 600, color: C.textDark } }>{ m.icon } { m.title }</td>
                  <td style={ { padding: '8px 10px', color: C.text } }>{ m.description }</td>
                  <td style={ { padding: '8px 10px', ...mono, fontSize: 'var(--text-xs)', color: C.textMuted } }>{ m.flowId }</td>
                  <td style={ { padding: '8px 10px', fontSize: 'var(--text-xs)', color: C.textMuted } }>{ m.keywords }</td>
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
          <pre style={ { color: '#e2e8f0', fontSize: 'var(--text-xs)', lineHeight: 1.6, fontFamily: 'monospace', margin: 0, whiteSpace: 'pre' } }>{ `
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
│                          │   (Amplify Hosting)  │                                    │
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
│  │ Core (6) │  │ Msg (22) │  │ AI (3)   │  │ Pay (4)  │  │ Ops (6)  │             │
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
│  │  (49 tables)  │    │  (media files)    │    │  (4 queues)  │                       │
│  └──────────────┘    └──────────────────┘    └──────────────┘                       │
│                                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                           │
│  │ SES      │  │ Pinpoint │  │ Polly    │  │ EventBr. │                           │
│  │ (Email)  │  │ (SMS)    │  │ (TTS)    │  │ (Cron)   │                           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                           │
│                                                                                     │
│  External: Meta WhatsApp API │ Razorpay │ Plivo Voice │ AWS SMS                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
          `}</pre>
        </div>
      </div>

      {/* Service Categories */ }
      <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 } }>
        { [
          { title: 'Core Services', count: 6, items: [ 'contacts', 'auth-middleware', 'messages-read', 'messages-delete', 'faq-handler', 'url-shortener' ], color: C.green },
          { title: 'Messaging', count: 22, items: [ 'inbound-whatsapp', 'outbound-whatsapp', 'outbound-sms', 'outbound-email', 'plivo-answer', 'whatsapp-calling', '...+16 more' ], color: C.blue },
          { title: 'Payments', count: 3, items: [ 'razorpay-webhook', 'payments-read', 'invoice-engine' ], color: C.amber },
          { title: 'Operations', count: 6, items: [ 'bulk-job-create', 'bulk-job-control', 'bulk-worker', 'dlq-replay', 'system-cleanup', 'billing' ], color: '#6b7280' },
          { title: 'Ecommerce', count: 3, items: [ 'native-catalog-admin', 'catalog-management', 'product-image-gen' ], color: '#06b6d4' },
        ].map( cat => (
          <div key={ cat.title } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } }>
              <span style={ { width: 8, height: 8, borderRadius: '50%', background: cat.color } } />
              <span style={ { fontSize: 'var(--text-md)', fontWeight: 700, color: C.textDark } }>{ cat.title }</span>
              <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ cat.count }</span>
            </div>
            <div style={ { display: 'flex', flexDirection: 'column', gap: 4 } }>
              { cat.items.map( item => (
                <div key={ item } style={ { fontSize: 'var(--text-xs)', color: C.textMuted, ...mono } }>{ item }</div>
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
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: '0 0 16px' } }>Every frontend route mapped to its backend services and database tables.</p>
      </div>
      <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
        { FRONTEND_ROUTES.map( route => (
          <div key={ `${ route.path }:${ route.label }` } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' } }>
              <div style={ { minWidth: 180 } }>
                <div style={ label }>Frontend Route</div>
                <div style={ { ...mono, fontSize: 'var(--text-sm)', fontWeight: 600, color: C.textDark, marginTop: 4 } }>{ route.path }</div>
                <div style={ { fontSize: 'var(--text-xs)', color: C.textMuted } }>{ route.label }</div>
              </div>
              <div style={ { fontSize: 'var(--text-xl)', color: C.textLight, alignSelf: 'center' } }>→</div>
              <div style={ { minWidth: 200, flex: 1 } }>
                <div style={ label }>Backend Services</div>
                <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 } }>
                  { route.backend.split( ', ' ).map( b => (
                    <span key={ b } style={ pill( C.greenBg, C.green ) }>{ b }</span>
                  ) ) }
                </div>
              </div>
              <div style={ { fontSize: 'var(--text-xl)', color: C.textLight, alignSelf: 'center' } }>→</div>
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
          <button key={ cat } onClick={ () => setLambdaFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${lambdaFilter === cat ? C.bgDark : C.border}`, background: lambdaFilter === cat ? C.bgDark : C.bg, color: lambdaFilter === cat ? C.lime : C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>
            { cat } { cat !== 'All' && `(${LAMBDAS.filter( l => l.category === cat ).length})` }
          </button>
        ) ) }
      </div>
      <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>{ filteredLambdas.length } service{ filteredLambdas.length !== 1 ? 's' : '' }</p>
      { filteredLambdas.map( fn => (
        <div key={ fn.name } style={ card( expandedItems.has( fn.name ) ) }>
          <button onClick={ () => toggleExpand( fn.name ) } style={ { width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 } }>
            <span style={ { fontSize: 'var(--text-xs)', color: C.green } }>●</span>
            <div style={ { flex: 1 } }>
              <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: C.textDark } }>{ fn.name }</span>
                <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ fn.category }</span>
                { fn.apiRoute !== '-' && <span style={ { ...pill( C.greenBg, C.green ), ...mono } }>{ fn.apiRoute }</span> }
              </div>
              <p style={ { margin: '4px 0 0', fontSize: 'var(--text-xs)', color: C.textMuted } }>{ fn.description }</p>
            </div>
            <span style={ { transform: expandedItems.has( fn.name ) ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', fontSize: 'var(--text-xs)', color: C.textLight } }>▶</span>
          </button>
          { expandedItems.has( fn.name ) && (
            <div style={ { marginTop: 12, paddingTop: 12, borderTop: `2px solid ${C.border}`, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 } }>
              <div><div style={ label }>Trigger</div><div style={ { fontSize: 'var(--text-sm)', marginTop: 4 } }>{ fn.trigger }</div></div>
              <div><div style={ label }>Tables</div><div style={ { fontSize: 'var(--text-sm)', marginTop: 4, ...mono } }>{ fn.tables }</div></div>
              <div><div style={ label }>Runtime</div><div style={ { fontSize: 'var(--text-sm)', marginTop: 4 } }>Python 3.12</div></div>
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
          <button key={ cat } onClick={ () => setTableFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${tableFilter === cat ? C.bgDark : C.border}`, background: tableFilter === cat ? C.bgDark : C.bg, color: tableFilter === cat ? C.lime : C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>
            { cat } { cat !== 'All' && `(${DB_TABLES.filter( t => t.category === cat ).length})` }
          </button>
        ) ) }
      </div>
      <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>{ filteredTables.length } table{ filteredTables.length !== 1 ? 's' : '' } — PAY_PER_REQUEST billing</p>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Table', 'Purpose', 'Key', 'TTL', 'Indexes', 'Used By', 'Category' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
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
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted, fontSize: 'var(--text-xs)' } }>{ t.indexes }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted, fontSize: 'var(--text-xs)' } }>{ t.usedBy }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ t.category }</span></td>
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
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>All AWS resources used by the platform. Region: us-east-1</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Resource', 'Type', 'Purpose', 'Module', 'Environment', 'Status' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { AWS_RESOURCES.map( ( r, i ) => (
              <tr key={ i } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono, fontSize: 'var(--text-xs)' } }>{ r.name }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.blueBg, C.blue ) }>{ r.type }</span></td>
                <td style={ { padding: '10px 12px', color: C.text, maxWidth: 250 } }>{ r.purpose }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ r.module }</span></td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( C.greenBg, C.green ) }>{ r.env }</span></td>
                <td style={ { padding: '10px 12px' } }><span style={ { color: C.green, fontSize: 'var(--text-xs)' } }>● </span>{ r.status }</td>
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
        name: 'WECARE.DIGITAL (production)', children: [
          {
            name: '🔐 Authentication', children: [
              {
                name: 'Cognito User Pool (staff)', children: [
                  { name: 'Groups: Viewer, Operator, Admin' },
                  { name: 'OAuth domain (Cognito-hosted, managed login v2)' },
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
                  { name: 'wecare.digital' }, { name: 'mta-sts.wecare.digital' }, { name: 'sip.wecare.digital' },
                ]
              },
              { name: 'CloudFront (wecare.digital/get → media bucket)' },
              { name: 'ACM Certificates (SSL/TLS)' },
            ]
          },
          {
            name: '⚡ Compute — Lambda (42 functions)', children: [
              { name: 'Core (6): contacts, auth, messages, faq, url-shortener' },
              { name: 'Messaging (22): whatsapp, sms, voice, email, push' },
              { name: 'AI (3): query-kb, config, agent' },
              { name: 'Payments (3): razorpay, payments-read, invoice' },
              { name: 'Operations (6): bulk-jobs, dlq, cleanup, billing' },
              { name: 'Ecommerce (3): native-catalog-admin, catalog, image-gen' },
            ]
          },
          {
            name: '🗄️ Database — DynamoDB (' + DB_TABLES.length + ' tables)', children: [
              { name: 'Core: Contact, Message, User, MediaFile, AuditLog, SystemConfig, WebhookDedup, ...' },
              { name: 'WhatsApp: WhatsAppInbound, WhatsAppOutbound, WhatsAppVoice, WhatsAppCalling, WhatsAppGroup, ...' },
              { name: 'Payments: Payment, Invoice, InvoiceItem, InvoiceAsset, InvoiceDeliveryLog, InvoiceSequence, RazorpayWebhookLog' },
              { name: 'Flows: FlowRegistry, FlowSubmission, FlowLog' },
              { name: 'Operations: BulkJob, BulkRecipient, DLQMessage, ScheduledMessage, SystemEvent, ...' },
              { name: 'Analytics: TemplateAnalytics, MetaAnalyticsLog' },
            ]
          },
          {
            name: '📦 Storage — S3', children: [
              {
                name: 'Media bucket', children: [
                  { name: 'o/stream/media/ (static/CDN assets: m/, ivr/, reports/, docs/)' },
                  { name: 'secure/u/ (uploads as received — gated, presigned access only)' },
                  { name: 'secure/d/public/ (deliverables: Invoice/, receipts/, whatsapp/, blog/, catalog-deploy/ — served publicly)' },
                  { name: 'secure/d/public/whatsapp/wa-tpl/ (Meta-approved template media — do not move)' },
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
            name: '📊 Monitoring', children: [
              { name: 'CloudWatch Logs (42 log groups, 90d retention)' },
              { name: 'CloudWatch Alarms (error rate, DLQ depth)' },
              { name: 'EventBridge Rules (scheduled triggers)' },
            ]
          },
          {
            name: '🔒 Security', children: [
              { name: 'Secrets Manager (API keys, webhook secrets)' },
              { name: 'Rate limiting (handler-side)' },
              { name: 'ACM (SSL certificates)' },
            ]
          },
        ]
      },
    ];

    const renderTreeNode = ( node: any, depth = 0 ): React.ReactNode => (
      <div key={ node.name } style={ { marginLeft: depth * 20, marginBottom: 4 } }>
        <div style={ { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 6, background: depth === 0 ? C.bgDark : depth === 1 ? 'var(--bg-secondary)' : 'transparent', color: depth === 0 ? C.lime : C.text, fontSize: depth <= 1 ? 13 : 12, fontWeight: depth <= 1 ? 600 : 400 } }>
          { node.children && <span style={ { fontSize: 'var(--text-xs)' } }>▸</span> }
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
        <h3 style={ sectionTitle }>S3 media bucket</h3>
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>Two top-level roots: <code style={ mono }>o/</code> (public) and <code style={ mono }>secure/</code> (gated at the edge, presigned access only). <code style={ mono }>o/</code> is a location, not a permission — everything outside <code style={ mono }>secure/</code> is public. Within <code style={ mono }>o/</code>: <code style={ mono }>stack/</code> is user data (wipeable) and <code style={ mono }>stream/</code> is static assets (permanent). Served as <code style={ mono }>wecare.digital/get/&lt;key&gt;</code>; the bucket name is not a hostname.</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Path', 'Purpose', 'Read By', 'Written By' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
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
            { name: 'Bulk job queue', purpose: 'Bulk message job processing', retention: '1 day', visibility: '5 min' },
            { name: 'Inbound DLQ', purpose: 'Failed inbound processing', retention: '7 days', visibility: '5 min' },
            { name: 'Bulk DLQ', purpose: 'Failed bulk chunks', retention: '7 days', visibility: '5 min' },
            { name: 'Outbound DLQ', purpose: 'Failed outbound messages', retention: '7 days', visibility: '5 min' },
          ].map( q => (
            <div key={ q.name } style={ { padding: 12, background: C.bgSoft, borderRadius: C.radiusSm } }>
              <div style={ { ...mono, fontSize: 'var(--text-xs)', fontWeight: 600, color: C.textDark, wordBreak: 'break-all' } }>{ q.name }</div>
              <div style={ { fontSize: 'var(--text-xs)', color: C.textMuted, marginTop: 4 } }>{ q.purpose }</div>
              <div style={ { display: 'flex', gap: 6, marginTop: 6 } }>
                <span style={ pill( C.amberBg, C.amber ) }>Retention: { q.retention }</span>
                <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>Visibility: { q.visibility }</span>
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
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>Monorepo: wecare.digital — Next.js frontend + Amplify Gen 2 backend</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Folder', 'Purpose', 'Files', 'Linked To' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { CODE_MAP.map( c => (
              <tr key={ c.path } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ c.path }</td>
                <td style={ { padding: '10px 12px', color: C.text } }>{ c.purpose }</td>
                <td style={ { padding: '10px 12px', color: C.textMuted } }>{ c.files }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ c.linkedTo }</span></td>
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
          placeholder="Search tables, Lambda functions, AWS resources, routes, env vars... (Ctrl+K)"
          aria-label="Search system architecture"
          style={ { width: '100%', padding: '12px 16px 12px 40px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 'var(--text-md)', outline: 'none', boxSizing: 'border-box' } }
          autoFocus
        />
      </div>
      { searchQuery && (
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>{ searchResults.length } result{ searchResults.length !== 1 ? 's' : '' } for &quot;{ searchQuery }&quot;</p>
      ) }
      { searchResults.length > 0 && (
        <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
          { searchResults.map( ( r, i ) => (
            <div key={ i } style={ card() }>
              <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                <span style={ pill(
                  r.type === 'Table' ? C.blueBg : r.type === 'Lambda' ? C.greenBg : r.type === 'AWS' ? C.amberBg : r.type === 'Risk' ? C.redBg : 'var(--bg-secondary)',
                  r.type === 'Table' ? C.blue : r.type === 'Lambda' ? C.green : r.type === 'AWS' ? C.amber : r.type === 'Risk' ? C.red : C.textMuted
                ) }>{ r.type }</span>
                <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: C.textDark } }>{ r.name }</span>
                <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ r.category }</span>
              </div>
              <p style={ { margin: '6px 0 0', fontSize: 'var(--text-xs)', color: C.textMuted } }>{ r.detail }</p>
            </div>
          ) ) }
        </div>
      ) }
      { !searchQuery && (
        <div style={ card() }>
          <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>
            Search across { searchIndex.length } indexed items: { DB_TABLES.length } tables, { LAMBDAS.length } Lambda functions, { AWS_RESOURCES.length } AWS resources, { FRONTEND_ROUTES.length } routes, { STORAGE_PATHS.length } storage paths, { CODE_MAP.length } code folders, { ENV_VARS.length } env vars.
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
          <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>Values permanently redacted</span>
        </div>
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>Inventory contains variable names only. Values are never embedded in or revealed by the browser.</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Variable', 'Value', '', 'Category', 'Sensitive' ].map( ( h, i ) => (
                <th key={ h || `eye-${i}` } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, width: h === '' ? 36 : undefined } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { ENV_VARS.map( e => {
              const displayValue = e.sensitive ? 'Server-side / redacted' : e.value;
              return (
                <tr key={ e.key } style={ { borderBottom: `1px solid ${C.border}` } }>
                  <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono, fontSize: 'var(--text-xs)' } }>{ e.key }</td>
                  <td style={ { padding: '10px 12px', ...mono, color: e.sensitive ? C.amber : C.textMuted, fontSize: 'var(--text-xs)', wordBreak: 'break-all', maxWidth: 340 } }>{ displayValue }</td>
                  <td style={ { padding: '4px 6px', width: 36 } } />
                  <td style={ { padding: '10px 12px' } }><span style={ pill( e.category.includes( 'Hardcoded' ) ? C.redBg : e.category.includes( '✓' ) ? C.greenBg : 'var(--bg-secondary)', e.category.includes( 'Hardcoded' ) ? C.red : e.category.includes( '✓' ) ? C.green : C.textMuted ) }>{ e.category }</span></td>
                  <td style={ { padding: '10px 12px' } }>{ e.sensitive ? <span style={ pill( C.amberBg, C.amber ) }>Sensitive</span> : <span style={ { color: C.textLight } }>—</span> }</td>
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
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>Log sources and change tracking across the platform.</p>
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
          { title: 'Deployment Logs', source: 'Amplify Hosting', retention: 'Service history', status: 'Active', detail: 'Production deployment history is tracked by Amplify jobs for the wecare.digital branch.' },
        ].map( log => (
          <div key={ log.title } style={ card() }>
            <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } }>
              <span style={ { fontSize: 'var(--text-xs)', color: log.status === 'Active' ? C.green : C.red } }>●</span>
              <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: C.textDark } }>{ log.title }</span>
            </div>
            <div style={ { display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' } }>
              <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ log.source }</span>
              <span style={ pill( C.amberBg, C.amber ) }>{ log.retention }</span>
            </div>
            <p style={ { fontSize: 'var(--text-xs)', color: C.textMuted, margin: 0 } }>{ log.detail }</p>
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
        <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: '8px 0 0' } }>Node ≥24.0.0 | npm 11.6.2 | { DEPENDENCIES.filter( d => d.type === 'prod' ).length } production, { DEPENDENCIES.filter( d => d.type === 'dev' ).length } dev dependencies</p>
      </div>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
          <thead>
            <tr style={ { borderBottom: `2px solid ${C.border}` } }>
              { [ 'Package', 'Version', 'Type', 'Status', 'Notes' ].map( h => (
                <th key={ h } style={ { textAlign: 'left', padding: '10px 12px', fontSize: 'var(--text-xs)', color: C.textLight, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 } }>{ h }</th>
              ) ) }
            </tr>
          </thead>
          <tbody>
            { DEPENDENCIES.map( d => (
              <tr key={ d.name } style={ { borderBottom: `1px solid ${C.border}` } }>
                <td style={ { padding: '10px 12px', fontWeight: 600, color: C.textDark, ...mono } }>{ d.name }</td>
                <td style={ { padding: '10px 12px', ...mono, color: C.textMuted } }>{ d.version }</td>
                <td style={ { padding: '10px 12px' } }><span style={ pill( d.type === 'prod' ? C.blueBg : 'var(--bg-secondary)', d.type === 'prod' ? C.blue : C.textMuted ) }>{ d.type }</span></td>
                <td style={ { padding: '10px 12px' } }>
                  <span style={ pill(
                    d.status === 'ok' ? C.greenBg : d.status === 'warning' ? C.amberBg : C.redBg,
                    d.status === 'ok' ? C.green : d.status === 'warning' ? C.amber : C.red
                  ) }>{ d.status }</span>
                </td>
                <td style={ { padding: '10px 12px', color: C.textMuted, fontSize: 'var(--text-xs)' } }>{ d.note }</td>
              </tr>
            ) ) }
          </tbody>
        </table>
      </div>
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
          <input value={ lambdaDetailSearch } onChange={ e => setLambdaDetailSearch( e.target.value ) } placeholder="Search functions..." aria-label="Search Lambda functions" style={ { width: '100%', padding: '10px 14px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 'var(--text-md)', outline: 'none', boxSizing: 'border-box' } } />
        </div>
        <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap' } }>
          { LAMBDA_DETAIL_CATEGORIES.map( cat => (
            <button key={ cat } onClick={ () => setLambdaDetailFilter( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${lambdaDetailFilter === cat ? C.bgDark : C.border}`, background: lambdaDetailFilter === cat ? C.bgDark : C.bg, color: lambdaDetailFilter === cat ? C.lime : C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>{ cat }</button>
          ) ) }
        </div>
      </div>
      <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>{ filteredLambdaDetail.length } function{ filteredLambdaDetail.length !== 1 ? 's' : '' } — with env vars, runtime, memory, triggers</p>
      { filteredLambdaDetail.map( fn => {
        const isExp = expandedItems.has( 'ld-' + fn.name );
        return (
          <div key={ fn.name } style={ card( isExp ) }>
            <button onClick={ () => toggleExpand( 'ld-' + fn.name ) } style={ { width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 } }>
              <span style={ { fontSize: 'var(--text-xs)', color: C.green } }>●</span>
              <div style={ { flex: 1 } }>
                <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                  <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: C.textDark } }>{ fn.displayName }</span>
                  <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ fn.category }</span>
                  { fn.apiRoute && fn.apiRoute !== '-' && <span style={ { ...pill( C.greenBg, C.green ), ...mono } }>{ fn.apiRoute }</span> }
                </div>
                <p style={ { margin: '4px 0 0', fontSize: 'var(--text-xs)', color: C.textMuted } }>{ fn.description }</p>
              </div>
              <span style={ { transform: isExp ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', fontSize: 'var(--text-xs)', color: C.textLight } }>▶</span>
            </button>
            { isExp && (
              <div style={ { marginTop: 12, paddingTop: 12, borderTop: `2px solid ${C.border}` } }>
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 12 } }>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Runtime</div><div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.runtime }</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Timeout</div><div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.timeout }s</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Memory</div><div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: C.text, marginTop: 2 } }>{ fn.memory } MB</div></div>
                  <div style={ { padding: '10px 12px', background: C.bgSoft, borderRadius: C.radiusSm } }><div style={ label }>Status</div><div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: C.green, marginTop: 2 } }>{ fn.status }</div></div>
                </div>
                <div style={ { marginBottom: 10 } }><div style={ label }>Triggers</div><div style={ { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 } }>{ fn.triggers.map( t => <span key={ t } style={ pill( 'var(--bg-secondary)', C.text ) }>{ t }</span> ) }</div></div>
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
        <input value={ codeRepoSearch } onChange={ e => setCodeRepoSearch( e.target.value ) } placeholder="Search flows, lambdas, templates..." aria-label="Search code assets" style={ { flex: 1, maxWidth: 400, padding: '10px 14px', border: `2px solid ${C.border}`, borderRadius: C.radius, fontSize: 'var(--text-md)', outline: 'none', boxSizing: 'border-box' } } />
        <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap' } }>
          { CODE_ASSET_CATEGORIES.map( cat => (
            <button key={ cat } onClick={ () => setCodeRepoCategory( cat ) } style={ { padding: '6px 14px', borderRadius: C.radius, border: `2px solid ${codeRepoCategory === cat ? C.bgDark : C.border}`, background: codeRepoCategory === cat ? C.bgDark : C.bg, color: codeRepoCategory === cat ? C.lime : C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>{ cat }</button>
          ) ) }
        </div>
      </div>
      <p style={ { fontSize: 'var(--text-sm)', color: C.textMuted, margin: 0 } }>{ filteredCodeAssets.length } asset{ filteredCodeAssets.length !== 1 ? 's' : '' }</p>
      { filteredCodeAssets.map( asset => (
        <div key={ asset.id } style={ card( expandedAsset === asset.id ) } onClick={ () => setExpandedAsset( expandedAsset === asset.id ? null : asset.id ) } role="button" tabIndex={ 0 }>
          <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
            <span style={ pill( asset.type === 'Flow JSON' ? C.lime : C.bgSoft, C.textDark ) }>{ asset.type }</span>
            <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: C.textDark } }>{ asset.name }</span>
            { asset.status && <span style={ pill( asset.status === 'Published' ? C.greenBg : C.amberBg, asset.status === 'Published' ? C.green : C.amber ) }>{ asset.status }</span> }
            <span style={ pill( 'var(--bg-secondary)', C.textMuted ) }>{ asset.category }</span>
          </div>
          <p style={ { margin: '4px 0 0', fontSize: 'var(--text-xs)', color: C.textMuted } }>{ asset.description }</p>
          { expandedAsset === asset.id && (
            <div style={ { marginTop: 10, padding: '8px 10px', background: C.bgSoft, borderRadius: C.radiusSm } }>
              <div style={ label }>File Path</div>
              <code style={ { ...mono, color: C.textDark, fontSize: 'var(--text-xs)' } }>{ asset.path }</code>
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
      case 'lambda-detail': return renderLambdaDetail();
      case 'code-repo': return renderCodeRepo();
      default: return renderOverview();
    }
  };

  // ─── Main Render ───
  const body = (
      <div className="inner-page-container" style={ { background: C.bg } }>
        {/* Page Header */ }
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 } }>
          <div>
            <h2 style={ { margin: 0, fontSize: 22, fontWeight: 700, color: C.textDark } }>Project Control Center</h2>
            <p style={ { margin: '4px 0 0', fontSize: 'var(--text-sm)', color: C.textMuted } }>
              Full system architecture — { LAMBDAS.length } Lambda functions · { DB_TABLES.length } tables · { AWS_RESOURCES.length } AWS resources · { STORAGE_PATHS.length } storage paths
            </p>
          </div>
          <div style={ { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } }>
            <button onClick={ refresh } title="Refresh now" style={ { padding: '6px 12px', borderRadius: C.radius, border: `2px solid ${C.border}`, background: C.bg, color: C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 } }>
              ↻ Refresh
            </button>
            <button onClick={ toggleAutoRefresh } title={ isAutoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh' } style={ { padding: '6px 12px', borderRadius: C.radius, border: `2px solid ${isAutoRefresh ? C.borderActive : C.border}`, background: isAutoRefresh ? C.bgDark : C.bg, color: isAutoRefresh ? C.lime : C.textMuted, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>
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
                  fontSize: 'var(--text-xs)',
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
  );

  if ( embedded ) return body;
  return (
    <Layout onSignOut={ signOut } user={ user }>
      <SEO title="Project Control Center" description="Unified admin dashboard — architecture, Lambda, code repo, risks" noindex />
      { body }
    </Layout>
  );
};

export default SystemArchitecturePage;
