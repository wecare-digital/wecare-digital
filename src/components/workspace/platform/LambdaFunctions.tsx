/**
 * Lambda Functions Management — Admin Page
 * View all Lambda functions, their configuration, environment variables, and status.
 * Read-only by default — toggle edit mode with password.
 */

import React, { useState, useMemo } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import { verifyAdminAccess } from '../../../api/client';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

interface LambdaFunction {
  name: string;
  displayName: string;
  category: string;
  runtime: string;
  timeout: number;
  memory: number;
  description: string;
  apiRoute?: string;
  envVars: Record<string, string>;
  triggers: string[];
  status: 'active' | 'warning' | 'error';
}

const LAMBDA_FUNCTIONS: LambdaFunction[] = [
  // Core
  { name: 'wecare-contacts', displayName: 'Contacts', category: 'Core', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'CRUD operations for contacts', apiRoute: '/contacts', envVars: { CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-auth-middleware', displayName: 'Auth Middleware', category: 'Core', runtime: 'Python 3.12', timeout: 10, memory: 128, description: 'Cognito token validation for API Gateway', apiRoute: '/auth', envVars: { USER_POOL_ID: 'us-east-1_*', CLIENT_ID: '*' }, triggers: [ 'API Gateway Authorizer' ], status: 'active' },
  { name: 'wecare-messages-read', displayName: 'Messages Read', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'Read messages from all channels', apiRoute: '/messages', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-messages-delete', displayName: 'Messages Delete', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Delete messages by ID', apiRoute: '/messages/{id}', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-faq-handler', displayName: 'FAQ Handler', category: 'Core', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'FAQ auto-response engine', apiRoute: '/faq', envVars: { FAQ_TABLE: 'stack-wecare-digital-FAQTable' }, triggers: [ 'API Gateway' ], status: 'active' },

  // Messaging
  { name: 'wecare-inbound-whatsapp', displayName: 'Inbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 512, description: 'Process incoming WhatsApp messages, media, reactions', apiRoute: '/webhook/whatsapp', envVars: { INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable', CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable', MEDIA_BUCKET: 'wecare-digital-get', BOT_CONFIG_TABLE: 'stack-wecare-digital-BotConfigTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-outbound-whatsapp', displayName: 'Outbound WhatsApp', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Send WhatsApp messages via Cloud API', apiRoute: '/whatsapp/send', envVars: { OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway', 'SQS' ], status: 'active' },
  { name: 'wecare-outbound-sms', displayName: 'Outbound SMS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send SMS via AWS End User Messaging', apiRoute: '/sms/send', envVars: { SMS_TABLE: 'stack-wecare-digital-SmsAwsTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-outbound-email', displayName: 'Outbound Email', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Send email via Amazon SES', apiRoute: '/email/send', envVars: { EMAIL_TABLE: 'stack-wecare-digital-EmailTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-plivo-answer', displayName: 'Plivo Answer', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Plivo PSTN voice webhooks; writes the voice CDR', apiRoute: '/plivo/*', envVars: { VOICE_CDR_TABLE: 'stack-wecare-digital-VoiceCDRTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-sms-aws', displayName: 'SMS AWS (Pinpoint)', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS Pinpoint SMS handler', apiRoute: '/sms-aws', envVars: { SMS_TABLE: 'stack-wecare-digital-SmsAwsTable' }, triggers: [ 'API Gateway', 'SNS' ], status: 'active' },
  { name: 'wecare-voice-aws', displayName: 'Voice AWS', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'AWS voice call handler', apiRoute: '/voice-aws', envVars: { VOICE_TABLE: 'stack-wecare-digital-VoiceAwsTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-voice-cdr-read', displayName: 'Voice CDR Read', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read voice CDR records', apiRoute: '/voice-cdr-read', envVars: { CDR_TABLE: 'stack-wecare-digital-VoiceCDRTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-calling', displayName: 'WhatsApp Calling', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'WhatsApp voice/video call handling', apiRoute: '/whatsapp-calling', envVars: { CALLING_TABLE: 'stack-wecare-digital-WhatsAppVoiceTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-whatsapp-voice', displayName: 'WhatsApp Voice', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WhatsApp voice note processing', apiRoute: '/whatsapp-voice', envVars: { VOICE_TABLE: 'stack-wecare-digital-WhatsAppVoiceTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-template-management', displayName: 'WhatsApp Templates', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 512, description: 'Canonical Meta template CRUD, media, validation, library and compatibility routes', apiRoute: '/whatsapp/templates', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-whatsapp-business-api', displayName: 'WhatsApp Business API', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Direct Meta Cloud API operations', apiRoute: '/whatsapp/api', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-scheduled-messages', displayName: 'Scheduled Messages', category: 'Messaging', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Schedule and send messages at specific times', apiRoute: '/scheduled', envVars: { SCHEDULED_TABLE: 'stack-wecare-digital-ScheduledMessageTable' }, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },
  { name: 'wecare-template-analytics', displayName: 'Template Analytics', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Template performance metrics', apiRoute: '/whatsapp/template-analytics', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-waba-management', displayName: 'WABA Management', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WABA configuration and phone management', apiRoute: '/waba', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-media-cleanup', displayName: 'Media Cleanup', category: 'Messaging', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'Clean up expired media from S3', apiRoute: '', envVars: { MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'EventBridge (Daily)' ], status: 'active' },
  { name: 'wecare-push-notifications', displayName: 'Push Notifications', category: 'Messaging', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Web push notification delivery', apiRoute: '/push', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },

  // AI
  { name: 'wecare-ai-generate-response', displayName: 'AI Generate Response', category: 'AI', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Generate AI responses via Bedrock', apiRoute: '/ai/generate', envVars: { BEDROCK_MODEL_ID: 'anthropic.claude-3-sonnet', KB_ID: '*' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-ai-query-kb', displayName: 'AI Query KB', category: 'AI', runtime: 'Python 3.12', timeout: 30, memory: 256, description: 'Query the static FAQ knowledge base', apiRoute: '/ai/query', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-ai-config-management', displayName: 'AI Config Management', category: 'AI', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Manage AI/bot configuration', apiRoute: '/ai/config', envVars: { CONFIG_TABLE: 'stack-wecare-digital-BotConfigTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-agent-action-group', displayName: 'Agent Action Group', category: 'AI', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Governed internal agent action handler', apiRoute: '/ai/agent', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },

  // Payments
  { name: 'wecare-razorpay-webhook', displayName: 'Razorpay Webhook', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Razorpay payment webhook handler', apiRoute: '/webhook/razorpay', envVars: { WEBHOOK_SECRET: '***', PAYMENTS_TABLE: 'stack-wecare-digital-RazorpayWebhookLogTable' }, triggers: [ 'API Gateway (Webhook)' ], status: 'active' },
  { name: 'wecare-payments-read', displayName: 'Payments Read', category: 'Payments', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Read payment records', apiRoute: '/payments', envVars: {}, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-invoice-engine', displayName: 'Invoice Engine', category: 'Payments', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Invoice creation, PDF generation, payment links', apiRoute: '/invoices', envVars: { INVOICE_TABLE: 'stack-wecare-digital-InvoiceTable', MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },

  // Operations
  { name: 'wecare-bulk-job-create', displayName: 'Bulk Job Create', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 256, description: 'Create bulk messaging jobs', apiRoute: '/bulk/create', envVars: { BULK_TABLE: 'stack-wecare-digital-BulkJobTable', QUEUE_URL: 'stack-wecare-digital-bulk-queue' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-bulk-job-control', displayName: 'Bulk Job Control', category: 'Operations', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'Pause/resume/cancel bulk jobs', apiRoute: '/bulk/control', envVars: { BULK_TABLE: 'stack-wecare-digital-BulkJobTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-bulk-worker', displayName: 'Bulk Worker', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 512, description: 'Process bulk message queue items', apiRoute: '', envVars: { QUEUE_URL: 'stack-wecare-digital-bulk-queue' }, triggers: [ 'SQS' ], status: 'active' },
  { name: 'wecare-dlq-replay', displayName: 'DLQ Replay', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 128, description: 'Replay failed messages from DLQ', apiRoute: '/dlq/replay', envVars: { DLQ_TABLE: 'stack-wecare-digital-DLQMessageTable' }, triggers: [ 'API Gateway' ], status: 'active' },
  { name: 'wecare-system-cleanup', displayName: 'System Cleanup', category: 'Operations', runtime: 'Python 3.12', timeout: 300, memory: 256, description: 'TTL cleanup, orphan removal, maintenance', apiRoute: '', envVars: {}, triggers: [ 'EventBridge (Daily)' ], status: 'active' },
  { name: 'wecare-billing', displayName: 'Billing', category: 'Operations', runtime: 'Python 3.12', timeout: 60, memory: 128, description: 'AWS billing and usage tracking', apiRoute: '/billing', envVars: {}, triggers: [ 'API Gateway', 'EventBridge' ], status: 'active' },

  // Ecommerce
  // No API route, rule, schedule or queue reaches this function. CloudTrail (2026-10-25) shows
  // only operator invokes of :live, the fleet deploy's post-publish smoke test. Its environment
  // is empty per config/lambda-env-manifest.json; the cache table name is the code default.
  { name: 'wecare-catalog-management', displayName: 'Catalog Management', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 30, memory: 128, description: 'WhatsApp catalog sync', apiRoute: '', envVars: {}, triggers: [ 'Direct invoke (operator)' ], status: 'active' },
  { name: 'wecare-product-image-gen', displayName: 'Product Image Gen', category: 'Ecommerce', runtime: 'Python 3.12', timeout: 60, memory: 512, description: 'AI product image generation', apiRoute: '/store/image-gen', envVars: { MEDIA_BUCKET: 'wecare-digital-get' }, triggers: [ 'API Gateway' ], status: 'active' },
];

const CATEGORIES = [ 'All', 'Core', 'Messaging', 'AI', 'Payments', 'Operations', 'Ecommerce' ];

const isServerManagedSecret = ( value: string ) => /^\*+$/.test( value.trim() );

const LambdaFunctionsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const [ search, setSearch ] = useState( '' );
  const [ category, setCategory ] = useState( 'All' );
  const [ expandedFn, setExpandedFn ] = useState<string | null>( null );
  const [ editMode, setEditMode ] = useState( false );
  const toast = useToastContext();

  const filtered = useMemo( () => {
    return LAMBDA_FUNCTIONS.filter( fn => {
      const matchCat = category === 'All' || fn.category === category;
      const q = search.toLowerCase();
      const matchSearch = !q || fn.name.toLowerCase().includes( q ) || fn.displayName.toLowerCase().includes( q ) || fn.description.toLowerCase().includes( q );
      return matchCat && matchSearch;
    } );
  }, [ search, category ] );

  const stats = useMemo( () => ( {
    total: LAMBDA_FUNCTIONS.length,
    core: LAMBDA_FUNCTIONS.filter( f => f.category === 'Core' ).length,
    messaging: LAMBDA_FUNCTIONS.filter( f => f.category === 'Messaging' ).length,
    ai: LAMBDA_FUNCTIONS.filter( f => f.category === 'AI' ).length,
    payments: LAMBDA_FUNCTIONS.filter( f => f.category === 'Payments' ).length,
    operations: LAMBDA_FUNCTIONS.filter( f => f.category === 'Operations' ).length,
    ecommerce: LAMBDA_FUNCTIONS.filter( f => f.category === 'Ecommerce' ).length,
  } ), [] );

  const handleUnlock = async () => {
    try
    {
      if ( !( await verifyAdminAccess() ) )
      {
        toast.error( 'Admin access required' );
        return;
      }
      setEditMode( true );
      toast.success( 'Edit mode enabled for this session' );
    } catch
    {
      toast.error( 'Unable to verify Admin access' );
    }
  };

  const body = (
      <div className="inner-page-container" style={ { background: '#fff' } }>
        {/* Header */ }
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 } }>
          <div>
            <h2 style={ { margin: 0, fontSize: 22, fontWeight: 700, color: 'var(--accent)' } }>Lambda Functions</h2>
            <p style={ { margin: '4px 0 0', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>{ stats.total } functions across { CATEGORIES.length - 1 } categories</p>
          </div>
          <div style={ { display: 'flex', gap: 8, alignItems: 'center' } }>
            { !editMode ? (
              <button onClick={ handleUnlock } style={ { padding: '8px 16px', background: 'var(--bg-secondary)', border: '1.5px solid var(--lime)', borderRadius: 13, fontSize: 'var(--text-sm)', cursor: 'pointer', color: 'var(--text-muted)' } }>
                🔒 Read Only
              </button>
            ) : (
              <button onClick={ () => setEditMode( false ) } style={ { padding: '8px 16px', background: 'var(--lime)', border: '1.5px solid var(--accent)', borderRadius: 13, fontSize: 'var(--text-sm)', cursor: 'pointer', color: 'var(--accent)', fontWeight: 600 } }>
                🔓 Edit Mode
              </button>
            ) }
          </div>
        </div>


        {/* Stats Row */ }
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10, marginBottom: 20 } }>
          { CATEGORIES.filter( c => c !== 'All' ).map( cat => {
            const count = LAMBDA_FUNCTIONS.filter( f => f.category === cat ).length;
            return (
              <button key={ cat } onClick={ () => setCategory( category === cat ? 'All' : cat ) } style={ { padding: '12px 14px', background: category === cat ? 'var(--accent)' : 'var(--bg-secondary)', color: category === cat ? 'var(--lime)' : '#374151', border: '2px solid ' + ( category === cat ? 'var(--accent)' : '#f3f4f6' ), borderRadius: 13, cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s' } }>
                <div style={ { fontSize: 20, fontWeight: 700 } }>{ count }</div>
                <div style={ { fontSize: 'var(--text-xs)', fontWeight: 500, opacity: 0.8 } }>{ cat }</div>
              </button>
            );
          } ) }
        </div>

        {/* Search */ }
        <div style={ { position: 'relative', marginBottom: 16, maxWidth: 400 } }>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" style={ { position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' } }>
            <path stroke="var(--accent)" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="m21 21-4.35-4.35M11 6a5 5 0 0 1 5 5m3 0a8 8 0 1 1-16 0 8 8 0 0 1 16 0" />
          </svg>
          <input value={ search } onChange={ e => setSearch( e.target.value ) } placeholder="Search functions..." aria-label="Search Lambda functions" style={ { width: '100%', padding: '10px 14px 10px 36px', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 'var(--text-md)', outline: 'none', boxSizing: 'border-box' } } />
        </div>

        {/* Category pills */ }
        <div style={ { display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' } }>
          { CATEGORIES.map( cat => (
            <button key={ cat } onClick={ () => setCategory( cat ) } style={ { padding: '6px 14px', borderRadius: 13, border: '2px solid ' + ( category === cat ? 'var(--accent)' : '#f3f4f6' ), background: category === cat ? 'var(--accent)' : '#fff', color: category === cat ? 'var(--lime)' : 'var(--text-muted)', fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s' } }>
              { cat }
            </button>
          ) ) }
        </div>

        {/* Function count */ }
        <p style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 12 } }>{ filtered.length } function{ filtered.length !== 1 ? 's' : '' } shown</p>

        {/* Function Cards */ }
        <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
          { filtered.map( fn => {
            const isExpanded = expandedFn === fn.name;
            return (
              <div key={ fn.name } style={ { border: '2px solid ' + ( isExpanded ? 'var(--lime)' : '#f3f4f6' ), borderRadius: 13, background: '#fff', overflow: 'hidden', transition: 'border-color 0.15s' } }>
                {/* Card Header */ }
                <button onClick={ () => setExpandedFn( isExpanded ? null : fn.name ) } style={ { width: '100%', display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' } }>
                  <span style={ { fontSize: 'var(--text-xs)', color: fn.status === 'active' ? '#059669' : fn.status === 'warning' ? '#d97706' : '#dc2626' } }>●</span>
                  <div style={ { flex: 1, minWidth: 0 } }>
                    <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                      <span style={ { fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--accent)' } }>{ fn.displayName }</span>
                      <span style={ { fontSize: 'var(--text-xs)', padding: '2px 8px', borderRadius: 10, background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontWeight: 500 } }>{ fn.category }</span>
                      { fn.apiRoute && <span style={ { fontSize: 'var(--text-xs)', padding: '2px 8px', borderRadius: 10, background: '#f0fdf4', color: '#059669', fontFamily: 'monospace' } }>{ fn.apiRoute }</span> }
                    </div>
                    <p style={ { margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ fn.description }</p>
                  </div>
                  <span style={ { transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s', fontSize: 'var(--text-xs)', color: '#9ca3af' } }>▶</span>
                </button>

                {/* Expanded Details */ }
                { isExpanded && (
                  <div style={ { padding: '0 16px 16px', borderTop: '2px solid #f3f4f6' } }>
                    {/* Config Grid */ }
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginTop: 12 } }>
                      <div style={ { padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 10 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' } }>Runtime</div>
                        <div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: '#374151', marginTop: 2 } }>{ fn.runtime }</div>
                      </div>
                      <div style={ { padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 10 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' } }>Timeout</div>
                        <div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: '#374151', marginTop: 2 } }>{ fn.timeout }s</div>
                      </div>
                      <div style={ { padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 10 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' } }>Memory</div>
                        <div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: '#374151', marginTop: 2 } }>{ fn.memory } MB</div>
                      </div>
                      <div style={ { padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 10 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' } }>Status</div>
                        <div style={ { fontSize: 'var(--text-sm)', fontWeight: 600, color: fn.status === 'active' ? '#059669' : '#dc2626', marginTop: 2 } }>{ fn.status }</div>
                      </div>
                    </div>

                    {/* Triggers */ }
                    <div style={ { marginTop: 12 } }>
                      <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 } }>Triggers</div>
                      <div style={ { display: 'flex', gap: 6, flexWrap: 'wrap' } }>
                        { fn.triggers.map( t => (
                          <span key={ t } style={ { padding: '3px 10px', borderRadius: 10, fontSize: 'var(--text-xs)', fontWeight: 500, background: 'var(--bg-secondary)', color: '#374151', border: '1px solid var(--border)' } }>{ t }</span>
                        ) ) }
                      </div>
                    </div>

                    {/* Environment Variables */ }
                    { Object.keys( fn.envVars ).length > 0 && (
                      <div style={ { marginTop: 12 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 } }>Environment Variables { !editMode && <span style={ { fontSize: 'var(--text-xs)', color: '#d97706' } }>(read-only)</span> }</div>
                        <div style={ { background: 'var(--bg-secondary)', borderRadius: 10, padding: 10, display: 'flex', flexDirection: 'column', gap: 6 } }>
                          { Object.entries( fn.envVars ).map( ( [ key, val ] ) => (
                            <div key={ key } style={ { display: 'flex', alignItems: 'center', gap: 8 } }>
                              <code style={ { fontSize: 'var(--text-xs)', color: 'var(--accent)', fontWeight: 600, minWidth: 160, flexShrink: 0 } }>{ key }</code>
                              { isServerManagedSecret( val ) ? (
                                <code style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>Server-managed secret</code>
                              ) : editMode ? (
                                <input defaultValue={ val } style={ { flex: 1, padding: '4px 8px', border: '2px solid var(--lime)', borderRadius: 8, fontSize: 'var(--text-xs)', fontFamily: 'monospace', outline: 'none' } } onChange={ () => toast.info( 'Changes are preview-only — deploy via AWS Console' ) } />
                              ) : (
                                <code style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', wordBreak: 'break-all' } }>{ val }</code>
                              ) }
                            </div>
                          ) ) }
                        </div>
                      </div>
                    ) }

                    {/* Function Name */ }
                    <div style={ { marginTop: 12 } }>
                      <div style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 } }>Function Name</div>
                      <code style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', background: 'var(--bg-secondary)', padding: '4px 8px', borderRadius: 6, display: 'inline-block' } }>{ fn.name }</code>
                    </div>
                  </div>
                ) }
              </div>
            );
          } ) }
        </div>

        { filtered.length === 0 && (
          <div style={ { padding: 48, textAlign: 'center' } }>
            <p style={ { fontSize: 'var(--text-md)', color: 'var(--text-muted)' } }>No functions match your search</p>
            <button onClick={ () => { setSearch( '' ); setCategory( 'All' ); } } style={ { marginTop: 8, fontSize: 'var(--text-sm)', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer' } }>Clear filters</button>
          </div>
        ) }
      </div>
  );

  if ( embedded ) return body;
  return (
    <Layout onSignOut={ signOut } user={ user }>
      <SEO title="Lambda Functions" description="Manage Lambda Functions" noindex />
      { body }
    </Layout>
  );
};

export default LambdaFunctionsPage;
