/**
 * Unified Dashboard - WECARE.DIGITAL
 * Clean tabbed interface with Overview, Messages, Payments, Data, Billing
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import Layout from '../../../components/Layout';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { BarChart, DonutChart, Sparkline, ProgressBar, DateRangePicker } from '../../../components/Charts';
import { SkeletonStat, SkeletonCard } from '../../../components/Skeleton';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Tabs, { TabItem } from '../../../components/ui/Tabs';
import Spinner from '../../../components/ui/Spinner';
import * as api from '../../../api/client';
import {
  DashboardIcon, MessageIcon, PaymentIcon, DataIcon, BillingIcon,
  AIIcon, LinkIcon, SearchIcon, WhatsAppIcon, InvoiceIcon,
  ContactsIcon, BulkIcon, SmsIcon, EmailIcon, RefreshIcon,
  DocumentIcon, HealthIcon, AdvisorIcon
} from '../../../lib/icons';
import { AWS_ACCOUNT_ID, AWS_REGION, PAYMENT_CONFIG, PAYMENT_DETAILS, API_BASE } from '../../../config/constants';
import { InternalAIConfig, WebhookConfig, DEFAULT_AI_CONFIG, TabType, PageProps } from '../../../types/dashboard';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { useToastContext } from '../../../contexts/ToastContext';
import TabErrorBoundary from '../../../components/dashboard/TabErrorBoundary';

/**
 * Tab bodies, loaded on demand rather than all at once.
 *
 * Static imports meant the dashboard landing page pulled every tab before showing
 * the first one — `InternalChatTab` 38 KB, `AppBuilderTab` 36 KB, `SystemTab` 26 KB,
 * `PayTab` 15 KB, `DataTab` 10 KB of source. `OverviewTab` stays EAGER on purpose:
 * it is the default tab, so lazy-loading it would only add a round trip before the
 * page can show anything.
 *
 * `TabErrorBoundary` also stays eager — it has to be mounted to catch a failure in
 * the thing it wraps, and it is 1.7 KB.
 */
import OverviewTab from '../../../components/dashboard/tabs/OverviewTab';

// Generic on purpose. Annotating the loader as `Promise<any>` erased every tab's
// prop types and typecheck rejected `signOut`/`user`/`embedded` at 17 call sites -
// the helper has to carry the module's own props through, not flatten them.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const MessagesTab = lazyTab( () => import( '../../../components/dashboard/tabs/MessagesTab' ) );
const PayTab = lazyTab( () => import( '../../../components/dashboard/tabs/PayTab' ) );
const DataTab = lazyTab( () => import( '../../../components/dashboard/tabs/DataTab' ) );
const InternalChatTab = lazyTab( () => import( '../../../components/dashboard/tabs/InternalChatTab' ) );
const AppBuilderTab = lazyTab( () => import( '../../../components/dashboard/tabs/AppBuilderTab' ) );
const SystemTab = lazyTab( () => import( '../../../components/dashboard/tabs/SystemTab' ) );
import { AppBuilderIcon } from '../../../lib/icons';
import { PUBLIC_ROOT, SECURE_ROOT } from '../../../lib/media-paths';

const PAYMENT_PHONE = PAYMENT_CONFIG.phoneDisplay;
const PAYMENT_NAME = PAYMENT_CONFIG.phoneName;


// AWS Resource ARNs for billing display - uses centralized AWS_ACCOUNT_ID and AWS_REGION
// Comprehensive list including used and available services for future updates
const AWS_RESOURCES: Record<string, { arn: string; accountId: string; details?: string[] }> = {
  // COMPUTE
  'AWS Lambda': {
    arn: `arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [
      'wecare-outbound-whatsapp',
      'wecare-inbound-whatsapp',
      'wecare-contacts-create',
      'wecare-contacts-delete',
      'wecare-contacts-search',
      'wecare-messages-read',
      'wecare-messages-delete',
      'wecare-whatsapp-templates',
      'wecare-ai-generate-response',
      'wecare-ai-query-kb',
      'wecare-outbound-sms',
      'wecare-bulk-job-control',
      'wecare-dlq-replay',
      'wecare-sms-aws (Pinpoint SMS v2)',
      'wecare-voice-aws (Pinpoint Voice v2)',
      'wecare-voice-in-c2c (retired provider — historical reads)',
      'wecare-voice-in-obd (retired provider — historical reads)',
      'wecare-voice-cdr (voice CDR — also written by Plivo)',
      'wecare-billing',
      'wecare-scheduled-messages',
      'wecare-template-analytics',
      'wecare-waba-management',
      'wecare-ai-config-management',
      'wecare-ai-agent-action-group',
      'wecare-wix-store (Wix Stores + Velo bridge)',
      'wecare-product-image-gen (Product image generator)'
    ]
  },
  'Amazon EC2': {
    arn: `arn:aws:ec2:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon ECS': {
    arn: `arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'AWS Fargate': {
    arn: `arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // DATABASE
  'Amazon DynamoDB': {
    arn: `arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [
      'stack-wecare-digital-ContactsTable',
      'stack-wecare-digital-WhatsAppInboundTable',
      'stack-wecare-digital-WhatsAppOutboundTable',
      'stack-wecare-digital-WhatsAppCallingTable',
      'stack-wecare-digital-WhatsAppVoiceTable',
      'stack-wecare-digital-WhatsAppGroupTable',
      'stack-wecare-digital-MessagesTable (Legacy)',
      'stack-wecare-digital-MediaFilesTable',
      'stack-wecare-digital-BulkJobsTable',
      'stack-wecare-digital-BulkRecipientsTable',
      'stack-wecare-digital-DLQMessagesTable',
      'stack-wecare-digital-SmsAwsTable (Pinpoint SMS)',
      'stack-wecare-digital-AirtelSMSTable (legacy SMS history — read-only)',
      'stack-wecare-digital-DLTTemplates (TRAI DLT registry — live)',
      'stack-wecare-digital-VoiceAwsTable (Pinpoint Voice)',
      'stack-wecare-digital-AirtelC2CTable (legacy C2C history — read-only)',
      'stack-wecare-digital-VoiceCDRTable (voice CDR — live, shared with Plivo)',
      'stack-wecare-digital-OBDCampaigns (legacy OBD history — read-only)',
      'stack-wecare-digital-ScheduledMessagesTable',
      'stack-wecare-digital-TemplateAnalyticsTable',
      'stack-wecare-digital-InvoicesTable',
      'stack-wecare-digital-InvoiceItemsTable',
      'stack-wecare-digital-InvoiceAssetsTable',
      'stack-wecare-digital-InvoiceDeliveryLogTable',
      'stack-wecare-digital-InvoiceSequenceTable',
      'stack-wecare-digital-PaymentsTable',
      'stack-wecare-digital-RazorpayWebhookLogTable',
      'stack-wecare-digital-SubmitRequestsTable',
      'stack-wecare-digital-ConversationHistoryTable',
      'stack-wecare-digital-AIInteractionsTable',
      'stack-wecare-digital-SystemConfigTable',
      'stack-wecare-digital-FAQTable',
      'stack-wecare-digital-ShortLinksTable',
      'stack-wecare-digital-AdAttributionTable',
      'stack-wecare-digital-CatalogCacheTable',
      'stack-wecare-digital-EmailTable',
      'stack-wecare-digital-AuditLog',
      'stack-wecare-digital-RateLimitTracker',
      'stack-wecare-digital-WixProductsCache',
      'stack-wecare-digital-WixOrdersCache',
      'stack-wecare-digital-WixOrderIds',
      'stack-wecare-digital-UsersTable',
    ]
  },
  'Amazon RDS': {
    arn: `arn:aws:rds:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon Aurora': {
    arn: `arn:aws:rds:${AWS_REGION}:${AWS_ACCOUNT_ID}:cluster:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon ElastiCache': {
    arn: `arn:aws:elasticache:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // STORAGE
  'Amazon S3': {
    arn: 'arn:aws:s3:::wecare-digital-get',
    accountId: AWS_ACCOUNT_ID,
    details: [
      'wecare-digital-get - single media bucket',
      'o/ - public root (media, invoices, voice, brand assets)',
      'secure/ - gated root, presigned access only'
    ]
  },
  'Amazon EBS': {
    arn: `arn:aws:ec2:${AWS_REGION}:${AWS_ACCOUNT_ID}:volume/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon EFS': {
    arn: `arn:aws:elasticfilesystem:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // NETWORKING & CDN
  'Amazon CloudFront': {
    arn: `arn:aws:cloudfront::${AWS_ACCOUNT_ID}:distribution/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'CDN for static assets' ]
  },
  'Amazon Route 53': {
    arn: 'arn:aws:route53:::hostedzone/*',
    accountId: AWS_ACCOUNT_ID,
    // app.wecare.digital removed 2026-09-28: the record is gone from zone
    // Z03939753QJGZ6ZD6BXO8 and the host is NXDOMAIN. Media is served from
    // wecare.digital/get instead.
    details: [ 'wecare.digital', 'www.wecare.digital', 'mta-sts.wecare.digital', 'sip.wecare.digital' ]
  },
  'Amazon VPC': {
    arn: `arn:aws:ec2:${AWS_REGION}:${AWS_ACCOUNT_ID}:vpc/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Default VPC' ]
  },
  'Elastic Load Balancing': {
    arn: `arn:aws:elasticloadbalancing:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // API & INTEGRATION
  'Amazon API Gateway': {
    arn: `arn:aws:apigateway:${AWS_REGION}::/restapis/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'wecare.digital/api - HTTP API (prod stage, auto-deploy)', 'Routes: /contacts, /messages, /whatsapp/*, /sms-aws/*, /voice-aws/*, /voice-in/*, /voice-cdr-webhook, /sms-in/*, /billing, /ai/*, /templates/*, /waba/*, /wix-store/*' ]
  },
  'AWS AppSync': {
    arn: `arn:aws:appsync:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon EventBridge': {
    arn: `arn:aws:events:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'AWS Step Functions': {
    arn: `arn:aws:states:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // MESSAGING
  'Amazon SNS': {
    arn: `arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'wecare-whatsapp-inbound-topic' ]
  },
  'Amazon SQS': {
    arn: `arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'wecare-whatsapp-dlq' ]
  },
  'Amazon SES': {
    arn: `arn:aws:ses:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Email sending service' ]
  },
  'Amazon Pinpoint': {
    arn: `arn:aws:sms-voice:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [
      'SMS: Pinpoint SMS v2 (us-east-1, account default)',
      'Voice: +18444891209 (Toll-Free, Intl enabled)',
      'Voice: +18444891209 (Toll-Free, Intl enabled, PENDING)',
      'Pool: TBD (pending toll-free approval)',
      'Protect Config: protect-b137924dfb934c32b1d10c28b737d08c (account default)',
      'Tables: SmsAwsTable, VoiceAwsTable'
    ]
  },
  'WhatsApp Business API (Direct)': {
    arn: `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:wecare/meta-system-user-token*`,
    accountId: AWS_ACCOUNT_ID,
    details: [
      '+91 93309 94400 (WECARE.DIGITAL) - Direct API, Razorpay + UPI',
      '+91 99033 00044 (Manish Agarwal) - Direct API, Razorpay + UPI',
      'WABA1: 2094615664435155 (WECARE.DIGITAL, Direct API)',
      'WABA2: 2513394156072604 (Manish Agarwal, Direct API)',
      'App: WECARE.DIGITAL (2238810740192680)',
      'All messaging via Meta Graph API v25.0',
    ]
  },

  // AI/ML
  'Amazon Bedrock': {
    arn: `arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Knowledge Base: wecare-digital-kb', 'Agent: wecare-digital-agent', 'Model: Claude' ]
  },
  'Amazon OpenSearch': {
    arn: `arn:aws:aoss:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Serverless collection for Bedrock KB vector store' ]
  },
  'Amazon SageMaker': {
    arn: `arn:aws:sagemaker:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon Comprehend': {
    arn: `arn:aws:comprehend:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon Rekognition': {
    arn: `arn:aws:rekognition:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon Transcribe': {
    arn: `arn:aws:transcribe:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'Amazon Polly': {
    arn: `arn:aws:polly:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'TTS for Pinpoint Voice calls (Voice ID: RAVEENA)' ]
  },
  'Amazon Translate': {
    arn: `arn:aws:translate:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },

  // SECURITY & IDENTITY
  'Amazon Cognito': {
    arn: `arn:aws:cognito-idp:${AWS_REGION}:${AWS_ACCOUNT_ID}:userpool/*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'User Pool for authentication' ]
  },
  'AWS IAM': {
    arn: `arn:aws:iam::${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'wecare-digital-lambda-role', 'amplify-service-role' ]
  },
  'AWS Secrets Manager': {
    arn: `arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ '31 secrets. 3 retired-provider credentials have no remaining reader and await destructive-approval deletion (see docs/provider-retirement-inventory.md). Paths are not listed here.' ]
  },
  'AWS KMS': {
    arn: `arn:aws:kms:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Default encryption keys' ]
  },
  // MONITORING & MANAGEMENT
  'CloudWatch': {
    arn: `arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:log-group:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [
      '/aws/lambda/wecare-outbound-whatsapp',
      '/aws/lambda/wecare-inbound-whatsapp',
      '/aws/lambda/wecare-* (all functions)'
    ]
  },
  'AWS X-Ray': {
    arn: `arn:aws:xray:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
  'AWS CloudTrail': {
    arn: `arn:aws:cloudtrail:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'API activity logging' ]
  },

  // DEVELOPER TOOLS
  'AWS Amplify': {
    arn: `arn:aws:amplify:${AWS_REGION}:${AWS_ACCOUNT_ID}:apps/d22dm4b0jn71jw`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'App: d22dm4b0jn71jw', 'Branch: stack', 'Domain: wecare.digital' ]
  },
  'AWS CodeBuild': {
    arn: `arn:aws:codebuild:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Amplify build process' ]
  },
  'AWS CodePipeline': {
    arn: `arn:aws:codepipeline:${AWS_REGION}:${AWS_ACCOUNT_ID}:*`,
    accountId: AWS_ACCOUNT_ID,
    details: [ 'Not currently used' ]
  },
};

const Dashboard: React.FC<PageProps> = ( { signOut, user } ) => {
  const confirm = useConfirm();
  const toast = useToastContext();
  const [ activeTab, setActiveTab ] = useState<TabType>( 'overview' );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ apiConnected, setApiConnected ] = useState( false );
  const [ apiLatency, setApiLatency ] = useState<number | null>( null );

  // Data
  const [ contacts, setContacts ] = useState<api.Contact[]>( [] );
  const [ messages, setMessages ] = useState<api.Message[]>( [] );
  const [ billingData, setBillingData ] = useState<api.AWSBillingData | null>( null );

  // UI State
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ selectedContact, setSelectedContact ] = useState( '' );
  const [ lastRefresh, setLastRefresh ] = useState<Date>( new Date() );
  const lastMessageCount = useRef( 0 );

  // Delete state
  const [ deleteMode, setDeleteMode ] = useState<'messages' | 'hard' | 'clearAll' | 'systemCleanup' | null>( null );
  const [ selectedMessages, setSelectedMessages ] = useState<string[]>( [] );
  const [ deleting, setDeleting ] = useState( false );
  const [ confirmText, setConfirmText ] = useState( '' );

  // System cleanup state
  const [ cleanupResources, setCleanupResources ] = useState<api.CleanupResource[]>( [] );
  const [ cleanupSelected, setCleanupSelected ] = useState<Set<string>>( new Set() );
  const [ cleanupLoading, setCleanupLoading ] = useState( false );
  const [ cleanupRunning, setCleanupRunning ] = useState( false );
  const [ cleanupResults, setCleanupResults ] = useState<api.CleanupResult[] | null>( null );

  // Payment edit state
  const [ editPayment, setEditPayment ] = useState<any>( null );
  const [ editSaving, setEditSaving ] = useState( false );

  // Billing expanded rows
  const [ expandedServices, setExpandedServices ] = useState<Set<string>>( new Set() );

  // AI Config state
  const [ aiConfig, setAiConfig ] = useState<InternalAIConfig>( DEFAULT_AI_CONFIG );
  const [ aiLoading, setAiLoading ] = useState( false );
  const [ aiSaving, setAiSaving ] = useState( false );
  const [ testMessage, setTestMessage ] = useState( '' );
  const [ testResult, setTestResult ] = useState<string | null>( null );

  // Webhook state
  const [ webhooks, setWebhooks ] = useState<WebhookConfig[]>( [] );
  const [ webhookLoading, setWebhookLoading ] = useState( false );
  const [ newWebhook, setNewWebhook ] = useState( { name: '', url: '', events: [ 'message.received', 'message.sent' ] } );
  const [ showWebhookForm, setShowWebhookForm ] = useState( false );

  // Bot Flow state
  const [ botFlowConfigs, setBotFlowConfigs ] = useState<Record<string, any>>( {} );
  const [ botFlowLoading, setBotFlowLoading ] = useState( false );
  const [ botFlowSaving, setBotFlowSaving ] = useState( false );
  const [ botFlowEditKey, setBotFlowEditKey ] = useState( '' );
  const [ botFlowEditValue, setBotFlowEditValue ] = useState( '' );

  // Flow JSON state (inner pages control)
  const [ flowJson, setFlowJson ] = useState<any>( null );
  const [ flowJsonLoading, setFlowJsonLoading ] = useState( false );
  const [ flowJsonSaving, setFlowJsonSaving ] = useState( false );
  const [ flowJsonEditMode, setFlowJsonEditMode ] = useState( false );
  const [ flowJsonEditValue, setFlowJsonEditValue ] = useState( '' );
  const [ flowJsonExpandedScreen, setFlowJsonExpandedScreen ] = useState<string | null>( null );

  // Submit Requests state
  const [ submitRequests, setSubmitRequests ] = useState<api.SubmitRequest[]>( [] );
  const [ requestsLoading, setRequestsLoading ] = useState( false );
  const [ resendingPayment, setResendingPayment ] = useState<string | null>( null );
  // Flow Logs state
  const [ flowLogs, setFlowLogs ] = useState<api.FlowLog[]>( [] );
  const [ flowLogsLoading, setFlowLogsLoading ] = useState( false );
  const loadData = useCallback( async ( silent = false ) => {
    if ( !silent ) { setLoading( true ); setLoadError( false ); }

    const connectionTest = await api.testConnection();
    setApiConnected( connectionTest.success );
    setApiLatency( connectionTest.latency || null );

    if ( !connectionTest.success )
    {
      if ( !silent ) { setLoading( false ); setLoadError( true ); }
      return;
    }

    try
    {
      const [ contactsData, messagesData, billingResult ] = await Promise.all( [
        api.listContacts(),
        api.listMessages(),
        api.getAWSBilling()
      ] );

      setContacts( contactsData );
      lastMessageCount.current = messagesData.length;
      setMessages( messagesData );
      setBillingData( billingResult );
      setLastRefresh( new Date() );
    } catch ( err )
    {
      console.error( 'Load error:', err );
      if ( !silent ) setLoadError( true );
    } finally
    {
      if ( !silent ) setLoading( false );
    }
  }, [] );

  useEffect( () => {
    loadData();
  }, [ loadData ] );

  // Auto-refresh every 30 seconds
  useEffect( () => {
    const interval = setInterval( () => loadData( true ), 30000 );
    return () => clearInterval( interval );
  }, [ loadData ] );

  // Load submit requests and flow logs when tab is activated
  useEffect( () => {
    if ( activeTab === 'requests' && submitRequests.length === 0 )
    {
      setRequestsLoading( true );
      api.listSubmitRequests().then( setSubmitRequests ).catch( console.error ).finally( () => setRequestsLoading( false ) );
      setFlowLogsLoading( true );
      api.listFlowLogs().then( setFlowLogs ).catch( console.error ).finally( () => setFlowLogsLoading( false ) );
    }
  }, [ activeTab ] );

  const handleResendPayment = async ( req: api.SubmitRequest ) => {
    if ( !req.invoiceId ) { toast.error( 'No linked invoice - cannot resend payment' ); return; }
    setResendingPayment( req.id );
    try
    {
      const ok = await api.resendSubmitRequestPayment( req.invoiceId );
      if ( ok )
      {
        toast.success( 'Payment link resent successfully' );
        setSubmitRequests( await api.listSubmitRequests() );
      } else { toast.error( 'Failed to resend payment link' ); }
    } catch ( err ) { console.error( 'Resend payment error:', err ); toast.error( 'Error resending payment' ); }
    finally { setResendingPayment( null ); }
  };

  const handleDeleteMessages = async () => {
    if ( selectedMessages.length === 0 ) return;
    setDeleting( true );
    try
    {
      for ( const msgId of selectedMessages )
      {
        const msg = messages.find( m => m.id === msgId );
        if ( msg ) await api.deleteMessage( msgId, msg.direction );
      }
      setSelectedMessages( [] );
      setDeleteMode( null );
      await loadData();
    } catch ( err )
    {
      console.error( 'Delete error:', err );
    } finally
    {
      setDeleting( false );
    }
  };

  const handleSavePayment = async () => {
    if ( !editPayment ) return;
    setEditSaving( true );
    try
    {
      const ok = await api.updateMessage( editPayment.id, {
        paymentItemName: editPayment.paymentItemName,
        paymentQuantity: Number( editPayment.paymentQuantity ) || 1,
        paymentGstRate: Number( editPayment.paymentGstRate ) || 18,
        paymentPurpose: editPayment.paymentPurpose,
        paymentDueRef: editPayment.paymentDueRef,
        paymentDiscount: Number( editPayment.paymentDiscount ) || 0,
        paymentShipping: Number( editPayment.paymentShipping ) || 0,
        status: editPayment.status,
      } );
      if ( ok )
      {
        setEditPayment( null );
        await loadData( true );
      } else
      {
        toast.error( 'Update failed' );
      }
    } catch ( err )
    {
      console.error( 'Save payment error:', err );
      toast.error( 'Error saving' );
    } finally
    {
      setEditSaving( false );
    }
  };

  const downloadInvoicePdf = ( invoiceUrl: string, refId: string ) => {
    const link = document.createElement( 'a' );
    link.href = invoiceUrl;
    link.download = `invoice-${refId}.png`;
    link.target = '_blank';
    link.click();
  };

  const handleHardDelete = async () => {
    if ( !selectedContact ) return;
    const ok = await confirm( {
      title: 'Hard Delete Contact',
      message: (
        <div>
          <p>This will permanently delete:</p>
          <ul style={ { margin: '8px 0 8px 20px', lineHeight: 1.6 } }>
            <li>Contact: { contacts.find( c => c.id === selectedContact )?.name || selectedContact }</li>
            <li>{ contactMessages.length } messages</li>
            <li>{ contactMessages.filter( m => m.s3Key ).length } media files from S3</li>
          </ul>
          <p style={ { color: '#0f2a1d', fontWeight: 500 } }>This action cannot be undone!</p>
        </div>
      ),
      confirmInput: 'DELETE',
      confirmText: 'Hard Delete',
      danger: true,
    } );
    if ( !ok ) return;
    setDeleting( true );
    try
    {
      const result = await api.hardDeleteContact( selectedContact );
      if ( !result.ok )
      {
        // A refusal is not a failure, and must not be swallowed. Say which refusal it was,
        // then offer the action that IS available - archiving keeps the record and every
        // payment link intact, which is what the guard is protecting.
        await _offerArchiveInstead( selectedContact, result );
        await loadData();
        return;
      }
      setSelectedContact( '' );
      setDeleteMode( null );
      setConfirmText( '' );
      await loadData();
    } catch ( err )
    {
      console.error( 'Delete error:', err );
    } finally
    {
      setDeleting( false );
    }
  };

  /** Explain a hard-delete refusal and, where it helps, archive instead. */
  const _offerArchiveInstead = async ( contactId: string, result: api.HardDeleteResult ) => {
    if ( result.ok ) return;
    if ( result.code === 'ERROR' )
    {
      toast.error( 'Delete failed — please try again' );
      return;
    }
    const headline = result.code === 'CONTACT_LOCKED'
      ? 'This contact is locked and cannot be deleted or archived'
      : result.code === 'CONTACT_HAS_PAYMENTS'
        ? 'This contact has payment or order history and cannot be deleted or archived'
        : 'Payment history could not be checked, so the delete was refused';
    toast.error( headline );
    if ( !result.archiveInstead ) return;
    const archive = await confirm( {
      title: 'Archive instead?',
      message: (
        <div>
          <p>{ headline }.</p>
          { result.reason && <p style={ { color: 'rgba(0,0,0,.54)', fontSize: 13 } }>{ result.reason }</p> }
          <p>Archiving hides the contact from the CRM list and keeps the record, the messages
            and every payment link intact. It can be restored by an admin.</p>
        </div>
      ),
      confirmText: 'Archive',
    } );
    if ( !archive ) return;
    const archived = await api.deleteContact( contactId );
    if ( archived )
    {
      toast.success( 'Contact archived' );
      setSelectedContact( '' );
      setDeleteMode( null );
      setConfirmText( '' );
    } else
    {
      toast.error( 'Archive failed — please try again' );
    }
  };

  // Clear ALL data across all channels - SMS, Voice, WhatsApp, S3, etc.
  const handleClearAllData = async () => {
    const ok = await confirm( {
      title: 'Clear All Data',
      message: (
        <div>
          <p style={ { color: '#0f2a1d', fontWeight: 500, marginBottom: 12 } }>WARNING: This will permanently delete ALL data:</p>
          <ul style={ { margin: '0 0 12px 20px', lineHeight: 1.6 } }>
            <li>All WhatsApp messages (inbound &amp; outbound)</li>
            <li>All SMS messages (inbound &amp; outbound)</li>
            <li>All SMS IN messages</li>
            <li>All Voice call records (inbound &amp; outbound)</li>
            <li>All Voice IN call records</li>
            <li>All { contacts.length } contacts</li>
            <li>All { messages.filter( m => m.s3Key ).length } media files from S3</li>
          </ul>
          <p style={ { color: '#0f2a1d', fontWeight: 500 } }>This action cannot be undone!</p>
        </div>
      ),
      confirmInput: 'DELETE ALL',
      confirmText: 'Clear Everything',
      danger: true,
    } );
    if ( !ok ) return;
    setDeleting( true );
    try
    {
      // Clear all inbox data (messages + contacts)
      const result = await api.clearAllInboxData();
      setDeleteMode( null );
      setConfirmText( '' );
      await loadData();
    } catch ( err )
    {
      console.error( 'Clear all error:', err );
    } finally
    {
      setDeleting( false );
    }
  };

  // System Cleanup handlers
  // Fallback resource list when backend isn't available
  const CLEANUP_FALLBACK: api.CleanupResource[] = [
    { id: 'whatsapp_inbox', label: 'WhatsApp Inbox (Inbound)', category: 'Messages', type: 'dynamodb', table: 'WhatsAppInboundTable', count: -1 },
    { id: 'whatsapp_outbox', label: 'WhatsApp Outbox (Outbound)', category: 'Messages', type: 'dynamodb', table: 'WhatsAppOutboundTable', count: -1 },
    { id: 'scheduled_messages', label: 'Scheduled Messages', category: 'Messages', type: 'dynamodb', table: 'ScheduledMessagesTable', count: -1 },
    { id: 'contacts', label: 'Contacts', category: 'Contacts', type: 'dynamodb', table: 'ContactsTable', count: -1 },
    { id: 'media_files', label: 'Media Files (DB records)', category: 'Media', type: 'dynamodb', table: 'MediaFilesTable', count: -1 },
    { id: 'conversation_history', label: 'AI Conversation History', category: 'AI', type: 'dynamodb', table: 'ConversationHistoryTable', count: -1 },
    { id: 'ai_interactions', label: 'AI Interactions Log', category: 'AI', type: 'dynamodb', table: 'AIInteractionsTable', count: -1 },
    { id: 'whatsapp_calling', label: 'WhatsApp Call Logs', category: 'Voice', type: 'dynamodb', table: 'WhatsAppCallingTable', count: -1 },
    { id: 'voice_cdr', label: 'Voice CDR Records', category: 'Voice', type: 'dynamodb', table: 'VoiceCDRTable', count: -1 },
    { id: 'voice_calls', label: 'Voice Calls (legacy)', category: 'Voice', type: 'dynamodb', table: 'VoiceCalls', count: -1 },
    { id: 'voice_aws', label: 'Voice AWS (Pinpoint)', category: 'Voice', type: 'dynamodb', table: 'VoiceAwsTable', count: -1 },
    { id: 'whatsapp_voice_log', label: 'WhatsApp Voice (TTS) Log', category: 'Voice', type: 'dynamodb', table: 'WhatsAppVoiceTable', count: -1 },
    { id: 'obd_campaigns', label: 'OBD Campaigns', category: 'Voice', type: 'dynamodb', table: 'OBDCampaigns', count: -1 },
    { id: 'legacy_c2c', label: 'C2C Records (legacy)', category: 'Voice', type: 'dynamodb', table: 'AirtelC2CTable', count: -1 },
    { id: 'sms_aws', label: 'SMS AWS (Pinpoint)', category: 'SMS', type: 'dynamodb', table: 'SmsAwsTable', count: -1 },
    { id: 'legacy_sms', label: 'SMS Messages (legacy providers)', category: 'SMS', type: 'dynamodb', table: 'AirtelSMSTable', count: -1 },
    { id: 'invoices', label: 'Invoices', category: 'Invoices & Payments', type: 'dynamodb', table: 'InvoicesTable', count: -1 },
    { id: 'invoice_items', label: 'Invoice Line Items', category: 'Invoices & Payments', type: 'dynamodb', table: 'InvoiceItemsTable', count: -1 },
    { id: 'invoice_assets', label: 'Invoice Assets (PDFs)', category: 'Invoices & Payments', type: 'dynamodb', table: 'InvoiceAssetsTable', count: -1 },
    { id: 'invoice_delivery_log', label: 'Invoice Delivery Log', category: 'Invoices & Payments', type: 'dynamodb', table: 'InvoiceDeliveryLogTable', count: -1 },
    { id: 'invoice_sequence', label: 'Invoice Sequence Counter', category: 'Invoices & Payments', type: 'dynamodb', table: 'InvoiceSequenceTable', count: -1 },
    { id: 'payments', label: 'Payments', category: 'Invoices & Payments', type: 'dynamodb', table: 'PaymentsTable', count: -1 },
    { id: 'razorpay_webhook_log', label: 'Razorpay Webhook Log', category: 'Invoices & Payments', type: 'dynamodb', table: 'RazorpayWebhookLogTable', count: -1 },
    { id: 'bulk_jobs', label: 'Bulk Jobs', category: 'Bulk', type: 'dynamodb', table: 'BulkJobsTable', count: -1 },
    { id: 'bulk_recipients', label: 'Bulk Recipients', category: 'Bulk', type: 'dynamodb', table: 'BulkRecipientsTable', count: -1 },
    // Rooted to match what the backend actually deletes: system-cleanup builds these with
    // media_paths.public(...) / .secure(...), which yield `o/stack/...` and `secure/stack/...`.
    // These rows read `stack/...` until 2026-09-29 — one level above the data, and this list is
    // the fallback shown when the live preview is unreachable, so there was nothing to
    // cross-check the wrong path against. Same hazard applies to the root: a row naming the
    // wrong root reports 0 objects, and 0 reads as "nothing to clean" rather than as an error.
    //
    // Invoices are SECURE_ROOT, not PUBLIC_ROOT — a rendered invoice carries the customer's
    // name, address, amount and GST breakdown, so it moved off the unauthenticated `o/` tree.
    { id: 's3_invoices', label: 'S3: Invoice Files', category: 'S3 Storage', type: 's3', prefix: `${SECURE_ROOT}stack/invoices/`, count: -1 },
    { id: 's3_whatsapp_media', label: 'S3: WhatsApp Media', category: 'S3 Storage', type: 's3', prefix: `${PUBLIC_ROOT}stack/whatsapp-media/`, count: -1 },
    { id: 's3_voice_recordings', label: 'S3: Voice Recordings', category: 'S3 Storage', type: 's3', prefix: `${PUBLIC_ROOT}stack/voice/`, count: -1 },
    { id: 's3_whatsapp_voice', label: 'S3: WhatsApp Voice (TTS)', category: 'S3 Storage', type: 's3', prefix: `${PUBLIC_ROOT}stack/whatsapp-media/voice/`, count: -1 },
  ];

  const loadCleanupPreview = async () => {
    setCleanupLoading( true );
    setCleanupResults( null );
    try
    {
      const resources = await api.getCleanupPreview();
      if ( resources && resources.length > 0 )
      {
        setCleanupResources( resources );
      } else
      {
        setCleanupResources( CLEANUP_FALLBACK );
      }
    } catch ( err )
    {
      setCleanupResources( CLEANUP_FALLBACK );
    } finally
    {
      setCleanupLoading( false );
    }
  };

  const toggleCleanupItem = ( id: string ) => {
    setCleanupSelected( prev => {
      const next = new Set( prev );
      if ( next.has( id ) ) next.delete( id );
      else next.add( id );
      return next;
    } );
  };

  const toggleCleanupCategory = ( category: string ) => {
    const categoryItems = cleanupResources.filter( r => r.category === category );
    const allSelected = categoryItems.every( r => cleanupSelected.has( r.id ) );
    setCleanupSelected( prev => {
      const next = new Set( prev );
      categoryItems.forEach( r => {
        if ( allSelected ) next.delete( r.id );
        else next.add( r.id );
      } );
      return next;
    } );
  };

  const selectAllCleanup = () => {
    if ( cleanupSelected.size === cleanupResources.length )
    {
      setCleanupSelected( new Set() );
    } else
    {
      setCleanupSelected( new Set( cleanupResources.map( r => r.id ) ) );
    }
  };

  const executeSystemCleanup = async () => {
    const ok = await confirm( {
      title: 'System Cleanup',
      message: `Permanently delete ${cleanupSelected.size} resource${cleanupSelected.size !== 1 ? 's' : ''}? This action cannot be undone.`,
      confirmInput: 'CONFIRM DELETE',
      confirmText: 'Permanently Delete',
      danger: true,
    } );
    if ( !ok ) return;
    setCleanupRunning( true );
    const selected = Array.from( cleanupSelected );
    const results: api.CleanupResult[] = [];

    try
    {
      // Try the dedicated Lambda endpoint first
      const response = await api.executeCleanup( selected );
      if ( response.results && response.results.length > 0 )
      {
        setCleanupResults( response.results );
        setCleanupSelected( new Set() );
        await loadCleanupPreview();
        await loadData();
        return;
      }
    } catch
    {
      // Lambda not deployed — fall back to existing APIs
    }

    // Helper: delete messages in a loop with stale-detection
    // If the same count comes back after a pass, messages aren't actually being deleted
    const deleteAllMessages = async ( channel?: string, dirFilter?: string ): Promise<number> => {
      let totalDeleted = 0;
      let prevCount = -1;
      let staleRuns = 0;
      for ( let pass = 0; pass < 30; pass++ )
      {
        const msgs = await api.listMessages( undefined, channel );
        const filtered = dirFilter ? msgs.filter( m => m.direction === dirFilter ) : msgs;
        if ( filtered.length === 0 ) break;
        // Detect stale loop: if count didn't decrease after a full pass, deletes aren't working
        if ( filtered.length === prevCount )
        {
          staleRuns++;
          if ( staleRuns >= 2 )
          {
            console.warn( `deleteAllMessages stale after ${pass} passes (${filtered.length} msgs remain). Trying both directions...` );
            // Last resort: try deleting each message from BOTH tables
            for ( const m of filtered )
            {
              try { await api.deleteMessage( m.id, 'INBOUND' ); } catch { /* skip */ }
              try { await api.deleteMessage( m.id, 'OUTBOUND' ); } catch { /* skip */ }
              totalDeleted++;
            }
            // Check if that worked
            const check = await api.listMessages( undefined, channel );
            const checkFiltered = dirFilter ? check.filter( m => m.direction === dirFilter ) : check;
            if ( checkFiltered.length >= filtered.length ) break; // truly stuck, bail out
            prevCount = checkFiltered.length;
            staleRuns = 0;
            continue;
          }
        } else
        {
          staleRuns = 0;
        }
        prevCount = filtered.length;
        for ( const m of filtered )
        {
          try { await api.deleteMessage( m.id, m.direction ); totalDeleted++; } catch { /* skip */ }
        }
      }
      return totalDeleted;
    };

    // Helper: call a bulk clear-logs endpoint and parse the result
    const bulkClear = async ( url: string, method: string = 'DELETE', body?: any ): Promise<number> => {
      const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
      if ( body ) opts.body = JSON.stringify( body );
      const res = await fetch( url, opts );
      if ( !res.ok ) throw new Error( `HTTP ${res.status}` );
      const data = await res.json();
      return data.totalDeleted ?? data.deletedCount ?? data.deleted ?? 0;
    };

    // Helper: try bulk clear, return -1 if endpoint not found (404). Tries POST as fallback.
    const tryBulkClear = async ( url: string, method: string = 'DELETE', body?: any ): Promise<number> => {
      try { return await bulkClear( url, method, body ); } catch ( e: any )
      {
        if ( e.message?.includes( '404' ) && method === 'DELETE' )
        {
          // API Gateway may not have DELETE configured — try POST as fallback
          try { return await bulkClear( url, 'POST', body || { clearAll: true } ); } catch ( e2: any )
          {
            if ( e2.message?.includes( '404' ) ) return -1;
            throw e2;
          }
        }
        if ( e.message?.includes( '404' ) ) return -1;
        throw e;
      }
    };

    // Reorder: process contacts FIRST so hardDeleteContact clears their messages + media
    const contactsFirst = [ 'contacts' ];
    const orderedSelected = [
      ...selected.filter( id => contactsFirst.includes( id ) ),
      ...selected.filter( id => !contactsFirst.includes( id ) ),
    ];

    // Fallback: use existing client-side delete functions + bulk clear-logs where available
    for ( const id of orderedSelected )
    {
      const t0 = Date.now();
      const res = CLEANUP_FALLBACK.find( r => r.id === id );
      const label = res?.label || id;
      try
      {
        let deleted = 0;
        // A REFUSAL is not a FAILURE. A contact the server protected because it has payments
        // is a correct outcome the operator needs told about; an error is something to retry.
        // Collapsing the two into one number is how "nothing happened" reads as success.
        let refused = 0;
        let failed = 0;
        if ( id === 'contacts' )
        {
          // Hard delete contacts FIRST — this also deletes their messages + media from S3.
          //
          // A refused contact is COUNTED, not skipped, and the pass loop stops as soon as a
          // pass deletes nothing. Both matter now that the server can refuse: `listContacts`
          // keeps returning a contact with payments forever, so the old loop ran all 20
          // passes re-requesting the same refusals and counted each one as a deletion.
          for ( let pass = 0; pass < 20; pass++ )
          {
            const allContacts = await api.listContacts();
            if ( allContacts.length === 0 ) break;
            const deletedBefore = deleted;
            for ( const c of allContacts )
            {
              try
              {
                const result = await api.hardDeleteContact( c.contactId );
                if ( result.ok ) { deleted++; } else if ( result.code === 'ERROR' ) { failed++; }
                else { refused++; }
              } catch { failed++; }
            }
            if ( deleted === deletedBefore ) break; // nothing moved — every remaining row is refused
          }
        } else if ( id === 'whatsapp_inbox' )
        {
          // Try bulk clear-all first (wipes both inbound + outbound tables at once)
          const bulk = await tryBulkClear( `${API_BASE}/messages/clear-all` );
          if ( bulk >= 0 )
          {
            deleted = bulk;
            // Mark outbox as done too since clear-all wipes both tables
            if ( orderedSelected.includes( 'whatsapp_outbox' ) )
            {
              results.push( { id: 'whatsapp_outbox', label: 'WhatsApp Outbox (Outbound)', deleted: 0, elapsed: 0 } );
            }
          } else
          {
            deleted = await deleteAllMessages( 'WHATSAPP', 'INBOUND' );
          }
        } else if ( id === 'whatsapp_outbox' )
        {
          // Skip if already cleared by whatsapp_inbox's clear-all
          if ( results.some( r => r.id === 'whatsapp_outbox' ) ) continue;
          deleted = await deleteAllMessages( 'WHATSAPP', 'OUTBOUND' );
        } else if ( id === 'sms_aws' )
        {
          // Try bulk clear-logs, fall back to one-by-one
          const bulk = await tryBulkClear( `${API_BASE}/sms-aws/clear-logs` );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            for ( let pass = 0; pass < 20; pass++ )
            {
              const msgs = await api.listSmsAwsMessages();
              if ( msgs.length === 0 ) break;
              for ( const m of msgs ) { try { await api.authFetch( `${API_BASE}/sms-aws/messages/${m.messageId}`, { method: 'DELETE' } ); deleted++; } catch { /* skip */ } }
            }
          }
        } else if ( id === 'voice_aws' )
        {
          deleted = await bulkClear( `${API_BASE}/voice-aws/clear-logs` );
        } else if ( id === 'whatsapp_calling' )
        {
          deleted = await bulkClear( `${API_BASE}/whatsapp` );
        } else if ( id === 'obd_campaigns' )
        {
          deleted = await bulkClear( `${API_BASE}/voice-in/obd`, 'POST', { clearAll: true } );
        } else if ( id === 'legacy_sms' )
        {
          // Legacy history purge requires the table name as a typed confirmation
          // server-side, because these rows are DLT audit evidence.
          const bulk = await tryBulkClear( `${API_BASE}/sms-aws/legacy-history`, 'DELETE', { confirmTable: 'stack-wecare-digital-AirtelSMSTable' } );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            results.push( { id, label, deleted: 0, error: 'Legacy history purge refused or route unavailable' } ); continue;
          }
        } else if ( id === 'legacy_c2c' )
        {
          const bulk = await tryBulkClear( `${API_BASE}/voice-in/c2c`, 'DELETE', { clearAll: true } );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            results.push( { id, label, deleted: 0, error: 'API route not deployed — redeploy voice-in/c2c Lambda' } ); continue;
          }
        } else if ( id === 'voice_cdr' || id === 'voice_calls' )
        {
          // Try voice-in/cdr first (POST with clearAll works), then voice-cdr-webhook
          let bulk = await tryBulkClear( `${API_BASE}/voice-in/cdr`, 'POST', { clearAll: true } );
          if ( bulk < 0 ) bulk = await tryBulkClear( `${API_BASE}/voice-cdr-webhook`, 'DELETE', { clearAll: true } );
          if ( bulk < 0 ) bulk = await tryBulkClear( `${API_BASE}/voice-cdr-webhook`, 'POST', { clearAll: true, _action: 'clear-logs' } );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            results.push( { id, label, deleted: 0, error: 'API route not deployed — redeploy voice-cdr Lambda' } ); continue;
          }
        } else if ( id === 'invoices' || id === 'invoice_items' || id === 'invoice_assets' || id === 'invoice_delivery_log' || id === 'invoice_sequence' || id === 'payments' || id === 'razorpay_webhook_log' || id === 's3_invoices' )
        {
          const invoiceIds = [ 'invoices', 'invoice_items', 'invoice_assets', 'invoice_delivery_log', 'invoice_sequence', 'payments', 'razorpay_webhook_log', 's3_invoices' ];
          const alreadyDone = results.some( r => invoiceIds.includes( r.id ) && !r.error );
          if ( alreadyDone ) { results.push( { id, label, deleted: 0, elapsed: 0 } ); continue; }
          // Try bulk clear-all, fall back to one-by-one for invoices only
          let bulk = await tryBulkClear( `${API_BASE}/invoices/clear-all` );
          // If route not configured, try POST to /invoices with _action body param
          if ( bulk < 0 ) bulk = await tryBulkClear( `${API_BASE}/invoices`, 'POST', { _action: 'clear-all' } );
          if ( bulk >= 0 ) { deleted = bulk; } else if ( id === 'invoices' )
          {
            for ( let pass = 0; pass < 20; pass++ )
            {
              const inv = await api.listInvoicesEngine();
              if ( inv.invoices.length === 0 ) break;
              for ( const i of inv.invoices ) { try { await api.deleteInvoice( i.invoiceId ); deleted++; } catch { /* skip */ } }
            }
          } else
          {
            results.push( { id, label, deleted: 0, error: 'Redeploy invoice-engine Lambda for clear-all' } ); continue;
          }
        } else if ( id === 'conversation_history' || id === 'ai_interactions' )
        {
          const aiIds = [ 'conversation_history', 'ai_interactions' ];
          const alreadyDone = results.some( r => aiIds.includes( r.id ) && !r.error );
          if ( alreadyDone ) { results.push( { id, label, deleted: 0, elapsed: 0 } ); continue; }
          let bulk = await tryBulkClear( `${API_BASE}/ai/clear-logs` );
          // If route not configured, try PUT to existing AI config endpoint with _action body param
          if ( bulk < 0 ) bulk = await tryBulkClear( `${API_BASE}/ai/internal/config`, 'PUT', { _action: 'clear-logs' } );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            results.push( { id, label, deleted: 0, error: 'Redeploy ai-config Lambda for clear-logs' } ); continue;
          }
        } else if ( id === 'bulk_jobs' )
        {
          for ( let pass = 0; pass < 20; pass++ )
          {
            const jobs = await api.listBulkJobs();
            if ( jobs.length === 0 ) break;
            for ( const j of jobs ) { try { await api.deleteBulkJob( j.id ); deleted++; } catch { /* skip */ } }
          }
        } else if ( id === 'whatsapp_voice_log' )
        {
          const bulk = await tryBulkClear( `${API_BASE}/whatsapp-voice/clear-logs` );
          if ( bulk >= 0 ) { deleted = bulk; } else
          {
            results.push( { id, label, deleted: 0, error: 'API route not deployed — redeploy whatsapp-voice Lambda' } ); continue;
          }
        } else if ( id === 'scheduled_messages' )
        {
          // Use the scheduled messages API, not the WhatsApp messages API
          for ( let pass = 0; pass < 20; pass++ )
          {
            const scheduled = await api.listScheduledMessages();
            if ( scheduled.length === 0 ) break;
            for ( const s of scheduled )
            {
              try { await api.cancelScheduledMessage( s.scheduledId ); deleted++; } catch { /* skip */ }
            }
          }
          // The `system-cleanup` POST fallback that stood here has been removed. It was a
          // SECOND written path to the destructive endpoint, posting a bare
          // `{ selected: [ id ] }` with no server preview and no confirmation token — and
          // it named `s3_whatsapp_media`, `s3_voice_recordings` and `s3_whatsapp_voice`,
          // none of which the endpoint will clear any more (S3 is never selectable; see
          // `operations/system-cleanup`). The whole block it sits in is dead code —
          // `executeSystemCleanup` and `selectAllCleanup` each occur exactly once in this
          // file, at their own definitions, and the rendered Data tab is
          // `components/dashboard/tabs/DataTab`, lazy-loaded at line 52. Deleting the
          // remaining ~400 dead lines is the right follow-up; doing it inside a safety fix
          // would bury the guard in an unreviewable diff.
        } else
        {
          results.push( { id, label, deleted: 0, error: 'No cleanup endpoint available' } );
          continue;
        }
        results.push( {
          id, label, deleted,
          elapsed: Math.round( ( Date.now() - t0 ) / 1000 * 10 ) / 10,
          ...( refused ? { refused } : {} ),
          ...( failed ? { error: `${failed} failed` } : {} ),
        } );
      } catch ( err: any )
      {
        results.push( { id, label, deleted: 0, error: err?.message || 'Failed' } );
      }
    }

    setCleanupResults( results );
    setCleanupSelected( new Set() );
    // Surfaced as a toast as well as in the result rows: a sweep that silently left rows
    // behind is indistinguishable from one that finished.
    const totalRefused = results.reduce( ( sum, r ) => sum + ( r.refused || 0 ), 0 );
    if ( totalRefused > 0 )
    {
      toast.error( `${totalRefused} contact${totalRefused === 1 ? '' : 's'} kept — they have payments and can only be archived` );
    }
    await loadData();
    setCleanupRunning( false );
  };

  const toggleServiceExpand = ( service: string ) => {
    setExpandedServices( prev => {
      const next = new Set( prev );
      if ( next.has( service ) ) next.delete( service );
      else next.add( service );
      return next;
    } );
  };

  // AI Config handlers
  const loadAiConfig = async () => {
    setAiLoading( true );
    try
    {
      const res = await fetch( `${API_BASE}/ai/internal/config` );
      if ( res.ok )
      {
        const data = await res.json();
        if ( data.config )
        {
          setAiConfig( { ...DEFAULT_AI_CONFIG, ...data.config } );
        }
      }
    } catch ( error )
    {
      // Using default internal AI config
    }
    setAiLoading( false );
  };

  const handleSaveAiConfig = async () => {
    setAiSaving( true );
    try
    {
      const res = await fetch( `${API_BASE}/ai/internal/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( aiConfig ),
      } );
      if ( !res.ok ) console.error( 'Failed to save AI config' );
    } catch ( error )
    {
      console.error( 'Failed to save AI config' );
    }
    setAiSaving( false );
  };

  const handleTestAi = async () => {
    if ( !testMessage.trim() ) return;
    setAiSaving( true );
    setTestResult( null );
    try
    {
      const res = await fetch( `${API_BASE}/ai/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          messageContent: testMessage,
          context: 'internal-admin',
        } ),
      } );
      const data = await res.json();
      const body = typeof data.body === 'string' ? JSON.parse( data.body ) : data;
      setTestResult( body.suggestedResponse || body.suggestion || 'No response' );
    } catch ( error )
    {
      setTestResult( 'Error: Failed to get AI response' );
    }
    setAiSaving( false );
  };

  // Webhook handlers
  const loadWebhooks = async () => {
    setWebhookLoading( true );
    try
    {
      const res = await fetch( `${API_BASE}/webhooks` );
      if ( res.ok )
      {
        const data = await res.json();
        setWebhooks( data.webhooks || [] );
      }
    } catch ( error )
    {
      // No webhooks configured
    }
    setWebhookLoading( false );
  };

  const handleCreateWebhook = async () => {
    if ( !newWebhook.name || !newWebhook.url ) return;
    try
    {
      const res = await fetch( `${API_BASE}/webhooks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( newWebhook ),
      } );
      if ( res.ok )
      {
        setNewWebhook( { name: '', url: '', events: [ 'message.received', 'message.sent' ] } );
        setShowWebhookForm( false );
        loadWebhooks();
      }
    } catch ( error )
    {
      console.error( 'Failed to create webhook' );
    }
  };

  const handleToggleWebhook = async ( id: string, enabled: boolean ) => {
    try
    {
      await fetch( `${API_BASE}/webhooks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { enabled } ),
      } );
      loadWebhooks();
    } catch ( error )
    {
      console.error( 'Failed to toggle webhook' );
    }
  };

  const handleDeleteWebhook = async ( id: string ) => {
    try
    {
      await fetch( `${API_BASE}/webhooks/${id}`, { method: 'DELETE' } );
      loadWebhooks();
    } catch ( error )
    {
      console.error( 'Failed to delete webhook' );
    }
  };

  const loadBotFlowConfigs = async () => {
    setBotFlowLoading( true );
    try
    {
      const res = await fetch( `${API_BASE}/ai/botflow` );
      if ( res.ok )
      {
        const data = await res.json();
        setBotFlowConfigs( data.configs || {} );
      }
    } catch ( error )
    {
      // Failed to load bot flow configs
    }
    setBotFlowLoading( false );
  };

  const loadFlowJson = async () => {
    setFlowJsonLoading( true );
    try
    {
      const cfg = await api.getSystemConfig( 'whatsapp_flow_json' );
      if ( cfg ) setFlowJson( cfg );
    } catch ( error )
    {
      // Failed to load flow JSON
    }
    setFlowJsonLoading( false );
  };

  // Load AI config and webhooks when switching to those tabs
  useEffect( () => {
    if ( activeTab === 'ai' ) loadAiConfig();
    if ( activeTab === 'webhook' ) loadWebhooks();
    if ( activeTab === 'botflow' )
    {
      loadBotFlowConfigs();
      loadFlowJson();
    }
  }, [ activeTab ] );

  const handleSaveBotFlowConfig = async ( configKey: string, configValue: any ) => {
    setBotFlowSaving( true );
    try
    {
      const res = await fetch( `${API_BASE}/ai/botflow`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { configKey, configValue } ),
      } );
      if ( res.ok )
      {
        setBotFlowConfigs( prev => ( { ...prev, [ configKey ]: configValue } ) );
        setBotFlowEditKey( '' );
        setBotFlowEditValue( '' );
      }
    } catch ( error )
    {
      console.error( 'Failed to save bot flow config' );
    }
    setBotFlowSaving( false );
  };

  const handleSaveFlowJson = async () => {
    setFlowJsonSaving( true );
    try
    {
      const parsed = JSON.parse( flowJsonEditValue );
      const ok = await api.updateSystemConfig( 'whatsapp_flow_json', parsed );
      if ( ok )
      {
        setFlowJson( parsed );
        setFlowJsonEditMode( false );
        setFlowJsonEditValue( '' );
      }
    } catch
    {
      toast.error( 'Invalid JSON' );
    }
    setFlowJsonSaving( false );
  };

  // Stats
  const todayMessages = messages.filter( m => {
    const msgDate = new Date( m.timestamp );
    const today = new Date();
    return msgDate.toDateString() === today.toDateString();
  } );
  const inboundCount = messages.filter( m => m.direction === 'INBOUND' ).length;
  const outboundCount = messages.filter( m => m.direction === 'OUTBOUND' ).length;
  const paymentMessages = messages.filter( m => m.messageType === 'payment' || m.messageType === 'payment_request' );
  const capturedPayments = paymentMessages.filter( m => ( m as any ).paymentStatus === 'captured' ).length;
  const failedPayments = paymentMessages.filter( m => ( m as any ).paymentStatus === 'failed' ).length;
  const pendingPayments = paymentMessages.filter( m => m.status === 'pending' ).length;

  // Derived once so the two billing branches stay mutually exclusive by
  // construction rather than by keeping `=== false` and `!== false` in step.
  const costReportingOff = billingData?.costReportingEnabled === false;

  // Filter messages
  const filteredMessages = searchQuery.trim()
    ? messages.filter( m =>
      m.content?.toLowerCase().includes( searchQuery.toLowerCase() ) ||
      contacts.find( c => c.id === m.contactId )?.name?.toLowerCase().includes( searchQuery.toLowerCase() ) ||
      contacts.find( c => c.id === m.contactId )?.phone?.includes( searchQuery )
    )
    : messages;

  const contactMessages = selectedContact
    ? filteredMessages.filter( m => m.contactId === selectedContact )
    : filteredMessages;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title={ PAGE_SEO.dashboard.title }
        description={ PAGE_SEO.dashboard.description }
        keywords={ PAGE_SEO.dashboard.keywords }
        canonical="/workspace/dashboard"
        noindex={ true }
      />


      <div className="dash">
        {/* API Connection Error Banner */ }
        { loadError && !loading && (
          <div style={ { padding: '16px 20px', marginBottom: 16, background: '#fef2f2', border: '2px solid #fecaca', borderRadius: 13, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 } }>
            <div>
              <p style={ { margin: 0, fontSize: 14, fontWeight: 600, color: '#991b1b' } }>Unable to connect to API</p>
              <p style={ { margin: '4px 0 0', fontSize: 12, color: '#b91c1c' } }>Check that the API Gateway is reachable at { API_BASE }</p>
            </div>
            <button onClick={ () => loadData() } style={ { padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer' } }>Retry</button>
          </div>
        ) }

        {/* Header */ }
        <header className="dash-header">
          <div className="dash-brand">
            <h1>Overview</h1>
            <Link href="/workspace/dashboard/mcp-connections/">MCP Connections & Playground</Link>
            <div className="dash-status">
              <span className={ `status-dot ${apiConnected ? 'online' : 'offline'}` } />
              <span>{ apiConnected ? `${apiLatency}ms` : 'Offline' }</span>
              <span className="sep">•</span>
              <span>{ lastRefresh.toLocaleTimeString() }</span>
            </div>
          </div>
          <button className="refresh-btn" onClick={ () => loadData() } disabled={ loading }>
            { loading ? '...' : <RefreshIcon size={ 18 } /> }
          </button>
        </header>

        {/* Tabs */ }
        <nav className="dash-tabs">
          { ( [ 'overview', 'messages', 'pay', 'factoryreset', 'billing', 'health', 'advisor', 'ai', 'internalchat', 'botflow', 'webhook', 'guide', 'search', 'requests', 'appbuilder', 'system' ] as TabType[] ).map( tab => (
            <button
              key={ tab }
              className={ `tab ${activeTab === tab ? 'active' : ''}` }
              onClick={ () => setActiveTab( tab ) }
            >
              { tab === 'overview' && <DashboardIcon size={ 16 } /> }
              { tab === 'messages' && <MessageIcon size={ 16 } /> }
              { tab === 'pay' && <PaymentIcon size={ 16 } /> }
              { tab === 'factoryreset' && <DataIcon size={ 16 } /> }
              { tab === 'billing' && <BillingIcon size={ 16 } /> }
              { tab === 'health' && <HealthIcon size={ 16 } /> }
              { tab === 'advisor' && <AdvisorIcon size={ 16 } /> }
              { tab === 'ai' && <AIIcon size={ 16 } /> }
              { tab === 'internalchat' && <MessageIcon size={ 16 } /> }
              { tab === 'botflow' && <WhatsAppIcon size={ 16 } /> }
              { tab === 'webhook' && <LinkIcon size={ 16 } /> }
              { tab === 'guide' && <DocumentIcon size={ 16 } /> }
              { tab === 'search' && <SearchIcon size={ 16 } /> }
              { tab === 'requests' && <DocumentIcon size={ 16 } /> }
              { tab === 'appbuilder' && <AppBuilderIcon size={ 16 } /> }
              { tab === 'system' && <DataIcon size={ 16 } /> }
              <span>{ tab === 'ai' ? 'AI' : tab === 'internalchat' ? 'Internal Chat' : tab === 'botflow' ? 'Bot Flow' : tab === 'webhook' ? 'Webhook' : tab === 'guide' ? 'Guide' : tab === 'health' ? 'Health' : tab === 'advisor' ? 'Advisor' : tab === 'requests' ? 'Requests' : tab === 'factoryreset' ? 'Factory Reset' : tab === 'appbuilder' ? 'App Builder' : tab === 'system' ? 'System' : tab.charAt( 0 ).toUpperCase() + tab.slice( 1 ) }</span>
            </button>
          ) ) }
        </nav>

        {/* Tab Content */ }
        <div className="tab-content">
          {/* OVERVIEW TAB */ }
          { activeTab === 'overview' && (
            <TabErrorBoundary tabName="Overview">
              <OverviewTab data={ { contacts, messages, billingData, apiConnected, apiLatency, lastRefresh, loading } } />
            </TabErrorBoundary>
          ) }

          {/* MESSAGES TAB */ }
          { activeTab === 'messages' && (
            <TabErrorBoundary tabName="Messages">
              <MessagesTab data={ { contacts, messages, billingData, apiConnected, apiLatency, lastRefresh, loading } } />
            </TabErrorBoundary>
          ) }

          {/* PAY TAB */ }
          { activeTab === 'pay' && (
            <TabErrorBoundary tabName="Pay">
              <PayTab data={ { contacts, messages, billingData, apiConnected, apiLatency, lastRefresh, loading } } onRefresh={ () => loadData() } />
            </TabErrorBoundary>
          ) }

          {/* FACTORY RESET TAB */ }
          { activeTab === 'factoryreset' && (
            <TabErrorBoundary tabName="Factory Reset">
              <DataTab data={ { contacts, messages, billingData, apiConnected, apiLatency, lastRefresh, loading } } onRefresh={ () => loadData() } />
            </TabErrorBoundary>
          ) }
          {/* BILLING TAB */ }
          { activeTab === 'billing' && (
            <TabErrorBoundary tabName="Billing">
              <div className="billing-tab">
                <div className="section-header">
                  <h3>AWS Billing & Usage</h3>
                  <button className="refresh-btn" onClick={ () => loadData() } disabled={ loading }><RefreshIcon size={ 18 } /></button>
                </div>

                { loading && !billingData && (
                  <div style={ { textAlign: 'center', padding: '3rem' } }>
                    <div style={ { fontSize: '2rem', marginBottom: '1rem' } }>⏳</div>
                    <p style={ { color: '#6b7280' } }>Loading billing data...</p>
                  </div>
                ) }

                { !loading && !billingData && (
                  <div style={ { background: '#f9fafb', borderRadius: '8px', textAlign: 'center', padding: '3rem', border: '1px solid #e5e7eb' } }>
                    <div style={ { fontSize: '2rem', marginBottom: '1rem' } }>—</div>
                    <h3 style={ { color: '#0f2a1d', margin: '0 0 0.5rem' } }>Unable to Load Billing Data</h3>
                    <p style={ { color: '#6b7280', margin: 0 } }>Check API connection or try refreshing.</p>
                  </div>
                ) }

                { billingData && costReportingOff && (
                  <div style={ { background: '#f9fafb', borderRadius: '8px', textAlign: 'center', padding: '3rem', border: '1px solid #e5e7eb' } }>
                    <div aria-hidden="true" style={ { fontSize: '2rem', marginBottom: '1rem' } }>—</div>
                    <h3 style={ { color: '#0f2a1d', margin: '0 0 0.5rem' } }>{ billingData.unavailable ? 'Unable to Load Billing Data' : 'Cost Reporting Disabled' }</h3>
                    <p style={ { color: '#6b7280', margin: 0 } }>
                      { billingData.note || 'AWS cost reporting is disabled for this account.' }
                    </p>
                    <div style={ { color: '#6b7280', marginTop: '0.75rem', fontSize: '0.875rem' } }>
                      { billingData.period }
                    </div>
                    <div style={ { color: '#6b7280', fontSize: '0.875rem' } }>Account: { AWS_ACCOUNT_ID }</div>
                  </div>
                ) }

                { billingData && !costReportingOff && (
                  <>
                    <div className="billing-summary">
                      <div className="billing-total">
                        <span className="amount">${ billingData.totalCost.toFixed( 2 ) }</span>
                        <span className="label">Estimated Cost</span>
                      </div>
                      <div className="billing-meta">
                        <div className="period">{ billingData.period }</div>
                        <div className="account">Account: { AWS_ACCOUNT_ID }</div>
                      </div>
                    </div>

                    <table className="billing-table">
                      <thead>
                        <tr>
                          <th></th>
                          <th>Service</th>
                          <th>Usage</th>
                          <th>Free Limit</th>
                          <th>Cost</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        { billingData.services.map( ( svc, idx ) => {
                          const resource = AWS_RESOURCES[ svc.service ] || {
                            arn: `arn:aws:*:${AWS_REGION}:${AWS_ACCOUNT_ID}:${svc.service.toLowerCase().replace( /\s+/g, '-' )}/*`,
                            accountId: AWS_ACCOUNT_ID
                          };
                          const isExpanded = expandedServices.has( svc.service );
                          return (
                            <React.Fragment key={ idx }>
                              <tr className={ `billing-row ${svc.status}` }>
                                <td className="expand-cell">
                                  <button className="expand-btn" onClick={ () => toggleServiceExpand( svc.service ) }>
                                    { isExpanded ? '−' : '+' }
                                  </button>
                                </td>
                                <td className="service-name">{ svc.service }</td>
                                <td>{ svc.usage.toLocaleString() } <small>{ svc.unit }</small></td>
                                <td>{ svc.freeLimit }</td>
                                <td>${ svc.cost.toFixed( 4 ) }</td>
                                <td>
                                  <span className={ `badge ${svc.status}` }>
                                    { svc.status === 'free' ? 'Free' : svc.status === 'warning' ? 'Near' : 'Paid' }
                                  </span>
                                </td>
                              </tr>
                              { isExpanded && (
                                <tr className="resource-row">
                                  <td></td>
                                  <td colSpan={ 5 }>
                                    <div className="resource-details">
                                      <div><strong>Account ID:</strong> { resource.accountId }</div>
                                      <div><strong>Resource ARN:</strong> <code>{ resource.arn }</code></div>
                                      { resource.details && resource.details.length > 0 && (
                                        <div className="resource-list">
                                          <strong>Resources:</strong>
                                          <ul>
                                            { resource.details.map( ( detail, i ) => (
                                              <li key={ i }>{ detail }</li>
                                            ) ) }
                                          </ul>
                                        </div>
                                      ) }
                                    </div>
                                  </td>
                                </tr>
                              ) }
                            </React.Fragment>
                          );
                        } ) }
                      </tbody>
                    </table>
                  </>
                ) }
              </div>
            </TabErrorBoundary>
          ) }

          {/* HEALTH TAB */ }
          { activeTab === 'health' && (
            <TabErrorBoundary tabName="Health">
              <div className="health-tab">
                <div className="section-header">
                  <h3>AWS Health</h3>
                  <button className="refresh-btn" onClick={ () => loadData() } disabled={ loading }><RefreshIcon size={ 18 } /></button>
                </div>

                { loading && !billingData?.health && (
                  <div className="loading-state">
                    <div className="loading-icon"><RefreshIcon size={ 32 } /></div>
                    <p>Loading health data...</p>
                  </div>
                ) }

                { !loading && billingData?.health && (
                  <>
                    <div className="stats-grid small">
                      <div className={ `stat-card ${billingData?.health?.openIssues === 0 ? 'success' : 'error'}` }>
                        <div className="stat-value">
                          { billingData?.health?.openIssues ?? 0 }
                        </div>
                        <div className="stat-label">Open Issues</div>
                      </div>
                      <div className="stat-card accent">
                        <div className="stat-value">
                          { billingData?.health?.scheduledChanges ?? 0 }
                        </div>
                        <div className="stat-label">Scheduled Changes</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value">{ billingData?.health?.otherNotifications ?? 0 }</div>
                        <div className="stat-label">Notifications</div>
                      </div>
                      <div className={ `stat-card ${billingData?.health?.status === 'healthy' ? 'success' : 'warning'}` }>
                        <div className="stat-value status-icon">
                          { billingData?.health?.status === 'healthy' ? <HealthIcon size={ 24 } /> : <AdvisorIcon size={ 24 } /> }
                        </div>
                        <div className="stat-label">Status</div>
                      </div>
                    </div>

                    { billingData?.health?.events && billingData.health.events.length > 0 && (
                      <div className="section issues-section">
                        <h4>Open Issues</h4>
                        { billingData.health.events.map( ( event: any, idx: number ) => (
                          <div key={ idx } className="issue-card error">
                            <div className="issue-card-header">
                              <strong>{ event.service }</strong>
                              <span className="issue-badge error">{ event.statusCode }</span>
                            </div>
                            <p>{ event.eventTypeCode }</p>
                            <div className="meta">Region: { event.region }</div>
                            <a href="https://health.aws.amazon.com/health/home" target="_blank" rel="noopener noreferrer" className="resolve-btn">
                              View & Resolve
                            </a>
                          </div>
                        ) ) }
                      </div>
                    ) }

                    { ( billingData.health.openIssues === 0 && billingData.health.scheduledChanges === 0 ) && (
                      <div className="health-status-card healthy">
                        <div className="status-icon"><HealthIcon size={ 48 } /></div>
                        <h3>All Systems Healthy</h3>
                        <p>No open issues or scheduled changes.</p>
                      </div>
                    ) }
                  </>
                ) }

                { !loading && !billingData?.health && (
                  <div className="health-status-card info">
                    <div className="status-icon"><DataIcon size={ 48 } /></div>
                    <h3>Health Data Unavailable</h3>
                    <p>AWS Health API requires Business or Enterprise Support plan.</p>
                  </div>
                ) }

                <div className="info-banner-blue">
                  <p>
                    AWS Health provides personalized information about events that can affect your AWS infrastructure.
                    <a href="https://health.aws.amazon.com/health/home" target="_blank" rel="noopener noreferrer">
                      Open AWS Health Dashboard
                    </a>
                  </p>
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* ADVISOR TAB */ }
          { activeTab === 'advisor' && (
            <TabErrorBoundary tabName="Advisor">
              <div className="advisor-tab">
                <div className="section-header">
                  <h3>Trusted Advisor</h3>
                  <button className="refresh-btn" onClick={ () => loadData() } disabled={ loading }><RefreshIcon size={ 18 } /></button>
                </div>

                { loading && !billingData?.trustedAdvisor && (
                  <div className="loading-state">
                    <div className="loading-icon"><RefreshIcon size={ 32 } /></div>
                    <p>Loading Trusted Advisor data...</p>
                  </div>
                ) }

                { !loading && billingData?.trustedAdvisor && (
                  <>
                    <div className="stats-grid small">
                      <div className="stat-card error">
                        <div className="stat-value">{ billingData?.trustedAdvisor?.actionRecommended ?? 0 }</div>
                        <div className="stat-label">Action Required</div>
                      </div>
                      <div className="stat-card warning">
                        <div className="stat-value">{ billingData?.trustedAdvisor?.investigationRecommended ?? 0 }</div>
                        <div className="stat-label">Investigation</div>
                      </div>
                      <div className="stat-card success">
                        <div className="stat-value">{ billingData?.trustedAdvisor?.noProblemsDetected ?? 0 }</div>
                        <div className="stat-label">No Problems</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value">{ billingData?.trustedAdvisor?.notAvailable ?? 0 }</div>
                        <div className="stat-label">Not Available</div>
                      </div>
                    </div>

                    { billingData?.trustedAdvisor?.categories && Object.keys( billingData.trustedAdvisor.categories ).length > 0 && (
                      <div className="category-grid">
                        { Object.entries( billingData.trustedAdvisor.categories ).map( ( [ key, counts ]: [ string, any ] ) => (
                          <div key={ key } className="category-card">
                            <div className="category-icon">
                              { key === 'cost_optimizing' ? <BillingIcon size={ 24 } /> :
                                key === 'security' ? <AdvisorIcon size={ 24 } /> :
                                  key === 'fault_tolerance' ? <HealthIcon size={ 24 } /> :
                                    key === 'performance' ? <AIIcon size={ 24 } /> :
                                      <DataIcon size={ 24 } /> }
                            </div>
                            <div className="category-name">{ key.replace( '_', ' ' ) }</div>
                            <div className="category-counts">
                              { counts.error > 0 && <span className="count-badge error">{ counts.error }</span> }
                              { counts.warning > 0 && <span className="count-badge warning">{ counts.warning }</span> }
                              { counts.ok > 0 && <span className="count-badge ok">{ counts.ok }</span> }
                            </div>
                          </div>
                        ) ) }
                      </div>
                    ) }

                    { billingData?.trustedAdvisor?.checks && billingData.trustedAdvisor.checks.length > 0 && (
                      <div className="section issues-section">
                        <h4>Checks Requiring Attention</h4>
                        { billingData.trustedAdvisor.checks.map( ( check: any, idx: number ) => (
                          <div key={ idx } className={ `issue-card ${check.status === 'error' ? 'error' : 'warning'}` }>
                            <div className="issue-card-header">
                              <strong>{ check.name }</strong>
                              <span className={ `issue-badge ${check.status === 'error' ? 'error' : 'warning'}` }>
                                { check.status === 'error' ? 'Action' : 'Warning' }
                              </span>
                            </div>
                            <p>{ check.description }</p>
                            <div className="meta">Resources: { check.resourcesFlagged }</div>
                            <a href={ `https://console.aws.amazon.com/trustedadvisor/home#/category/${check.category}` }
                              target="_blank" rel="noopener noreferrer" className="resolve-btn">
                              View & Resolve
                            </a>
                          </div>
                        ) ) }
                      </div>
                    ) }

                    { ( billingData.trustedAdvisor.actionRecommended === 0 && billingData.trustedAdvisor.investigationRecommended === 0 ) && (
                      <div className="health-status-card healthy">
                        <div className="status-icon"><AdvisorIcon size={ 48 } /></div>
                        <h3>All Checks Passed</h3>
                        <p>No action or investigation recommended.</p>
                      </div>
                    ) }
                  </>
                ) }

                { !loading && !billingData?.trustedAdvisor && (
                  <div className="health-status-card info">
                    <div className="status-icon"><DataIcon size={ 48 } /></div>
                    <h3>Trusted Advisor Data Unavailable</h3>
                    <p>Full Trusted Advisor access requires Business or Enterprise Support plan.</p>
                  </div>
                ) }

                <div className="info-banner-blue">
                  <p>
                    AWS Trusted Advisor inspects your AWS environment and provides recommendations.
                    <a href="https://console.aws.amazon.com/trustedadvisor/home" target="_blank" rel="noopener noreferrer">
                      Open Trusted Advisor Console
                    </a>
                  </p>
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* AI ASSISTANT TAB */ }
          { activeTab === 'ai' && (
            <TabErrorBoundary tabName="AI Assistant">
              <div className="ai-tab">
                <div className="section-header">
                  <h3>Internal AI Assistant</h3>
                  <span className="subtitle">Configure the FloatingAgent AI for admin tasks</span>
                </div>

                {/* Info Cards */ }
                <div className="stats-grid small" style={ { marginBottom: '1.5rem' } }>
                  <div className="stat-card">
                    <div className="stat-label">Agent ID</div>
                    <div className="stat-value" style={ { fontFamily: 'monospace', fontSize: '0.85rem' } }>{ aiConfig.agentId }</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Agent Alias</div>
                    <div className="stat-value" style={ { fontFamily: 'monospace', fontSize: '0.85rem' } }>{ aiConfig.agentAlias }</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Knowledge Base</div>
                    <div className="stat-value" style={ { fontFamily: 'monospace', fontSize: '0.85rem' } }>{ aiConfig.knowledgeBaseId }</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Model</div>
                    <div className="stat-value" style={ { fontSize: '0.85rem' } }>Nova Lite</div>
                  </div>
                </div>

                {/* Configuration */ }
                <div className="section" style={ { background: 'white', padding: '1.5rem', borderRadius: '0.5rem', marginBottom: '1.5rem' } }>
                  <h4 style={ { marginBottom: '1rem' } }>Configuration</h4>

                  <div style={ { marginBottom: '1rem' } }>
                    <label style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' } }>
                      <input
                        type="checkbox"
                        checked={ aiConfig.enabled }
                        onChange={ ( e ) => setAiConfig( { ...aiConfig, enabled: e.target.checked } ) }
                        style={ { width: '1.25rem', height: '1.25rem' } }
                      />
                      <span style={ { fontWeight: 600 } }>Enable Internal AI Assistant</span>
                    </label>
                  </div>

                  <div style={ { display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem', marginBottom: '1rem' } }>
                    <div>
                      <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Max Tokens</label>
                      <input
                        type="number"
                        value={ aiConfig.maxTokens }
                        onChange={ ( e ) => setAiConfig( { ...aiConfig, maxTokens: parseInt( e.target.value ) || 1024 } ) }
                        min={ 256 }
                        max={ 4096 }
                        style={ { width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '0.375rem' } }
                      />
                    </div>
                    <div>
                      <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Temperature</label>
                      <input
                        type="number"
                        value={ aiConfig.temperature }
                        onChange={ ( e ) => setAiConfig( { ...aiConfig, temperature: parseFloat( e.target.value ) || 0.7 } ) }
                        min={ 0 }
                        max={ 1 }
                        step={ 0.1 }
                        style={ { width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '0.375rem' } }
                      />
                    </div>
                  </div>

                  <div style={ { marginBottom: '1rem' } }>
                    <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>System Prompt</label>
                    <textarea
                      value={ aiConfig.systemPrompt }
                      onChange={ ( e ) => setAiConfig( { ...aiConfig, systemPrompt: e.target.value } ) }
                      rows={ 6 }
                      style={ { width: '100%', padding: '0.75rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', fontFamily: 'monospace', fontSize: '0.85rem' } }
                    />
                  </div>

                  <Button
                    variant="primary"
                    onClick={ handleSaveAiConfig }
                    disabled={ aiSaving }
                    loading={ aiSaving }
                  >
                    Save Configuration
                  </Button>
                </div>

                {/* Test Section */ }
                <div className="section" style={ { background: 'white', padding: '1.5rem', borderRadius: '0.5rem' } }>
                  <h4 style={ { marginBottom: '1rem' } }>Test Internal AI</h4>
                  <p style={ { color: '#666', fontSize: '0.9rem', marginBottom: '1rem' } }>
                    Test how the internal AI responds to admin commands.
                  </p>

                  <div style={ { marginBottom: '1rem' } }>
                    <textarea
                      value={ testMessage }
                      onChange={ ( e ) => setTestMessage( e.target.value ) }
                      rows={ 2 }
                      style={ { width: '100%', padding: '0.75rem', border: '1px solid #d1d5db', borderRadius: '0.375rem' } }
                      placeholder="Try: 'Show today's stats' or 'Find contact +919330994400'"
                    />
                  </div>

                  <Button
                    variant="primary"
                    onClick={ handleTestAi }
                    disabled={ aiSaving || !testMessage.trim() }
                    loading={ aiSaving }
                    style={ { marginBottom: '1rem' } }
                  >
                    Test Response
                  </Button>

                  { testResult && (
                    <div style={ { padding: '1rem', background: '#f9fafb', borderRadius: '0.5rem', border: '1px solid #e5e7eb' } }>
                      <div style={ { fontWeight: 500, marginBottom: '0.5rem' } }>AI Response:</div>
                      <div style={ { whiteSpace: 'pre-wrap' } }>{ testResult }</div>
                    </div>
                  ) }
                </div>

                {/* Architecture Info */ }
                <div style={ { marginTop: '1.5rem', padding: '1rem', background: '#f8fafc', borderRadius: '0.5rem', fontSize: '0.85rem', color: '#666' } }>
                  <strong>Architecture Note:</strong> This is the Internal AI used by the FloatingAgent for admin tasks.
                  For WhatsApp auto-reply AI (customer-facing), go to Messages → WhatsApp → AI Config.
                </div>

              </div>
            </TabErrorBoundary>
          ) }

          {/* INTERNAL CHAT TAB */ }
          { activeTab === 'internalchat' && (
            <TabErrorBoundary tabName="Internal Chat">
              <InternalChatTab />
            </TabErrorBoundary>
          ) }

          {/* BOT FLOW TAB */ }
          { activeTab === 'botflow' && (
            <TabErrorBoundary tabName="Bot Flow">
              <div className="botflow-tab">
                <div className="section-header">
                  <h3>WhatsApp Bot Flow Config</h3>
                  <div style={ { display: 'flex', gap: '0.5rem' } }>
                    <Button variant="secondary" onClick={ async () => {
                      if ( !( await confirm( 'Reset ALL bot flow configs to Lambda defaults? This deletes all custom configs.' ) ) ) return;
                      try
                      {
                        const res = await fetch( `${API_BASE}/ai/botflow`, { method: 'DELETE' } );
                        if ( res.ok )
                        {
                          setBotFlowConfigs( {} );
                        }
                      } catch ( error )
                      {
                        console.error( 'Failed to reset bot flow configs' );
                      }
                    } }>
                      Reset to Defaults
                    </Button>
                    <Button variant="secondary" onClick={ loadBotFlowConfigs } loading={ botFlowLoading }>
                      <RefreshIcon size={ 14 } /> Refresh
                    </Button>
                  </div>
                </div>
                <p style={ { color: '#666', marginBottom: '1rem', fontSize: '0.9rem' } }>
                  Manage welcome messages, menus, options, rating, and language picker configs stored in SystemConfigTable.
                </p>

                { botFlowLoading ? (
                  <SkeletonCard />
                ) : (
                  <>
                    {/* Config cards */ }
                    { [
                      { key: 'flow_triggers_config', label: 'Flow Triggers (Keywords + Messages)', desc: 'Keyword-to-flow mapping: keywords, message body, footer, CTA, flow ID, enable/disable' },
                      { key: 'welcome_message_config', label: 'Welcome / Main Menu', desc: 'Header, body, footer, button text, sections & rows for the main menu' },
                      { key: 'bot_options_config', label: 'Options Menu', desc: 'Do more / Done buttons shown after each action' },
                      { key: 'bot_rating_config', label: 'Rating Menu', desc: 'Feedback buttons shown when user is done' },
                      { key: 'bot_language_picker_config', label: 'Language Picker', desc: 'Language selection list' },
                      { key: 'bot_flow_config', label: 'Full Bot Flow', desc: 'Complete bot flow config (welcome, menus, responses, flows, toggles)' },
                    ].map( item => (
                      <div key={ item.key } style={ { marginBottom: '1.5rem', padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '0.5rem', background: '#fff' } }>
                        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' } }>
                          <div>
                            <strong>{ item.label }</strong>
                            <div style={ { fontSize: '0.8rem', color: '#888' } }>{ item.desc }</div>
                            <div style={ { fontSize: '0.75rem', color: '#aaa', fontFamily: 'monospace' } }>key: { item.key }</div>
                          </div>
                          <div style={ { display: 'flex', gap: '0.5rem' } }>
                            <Button
                              variant="secondary"
                              onClick={ () => {
                                setBotFlowEditKey( item.key );
                                setBotFlowEditValue( JSON.stringify( botFlowConfigs[ item.key ] || {}, null, 2 ) );
                              } }
                            >
                              { botFlowConfigs[ item.key ] ? 'Edit' : 'Create' }
                            </Button>
                          </div>
                        </div>

                        {/* Friendly display for flow_triggers_config */ }
                        { item.key === 'flow_triggers_config' && (
                          <div style={ { marginTop: '0.5rem' } }>
                            { ( () => {
                              const cfg = botFlowConfigs[ item.key ] || {};
                              const hasConfig = Object.keys( cfg ).length > 0;
                              return (
                                <>
                                  { !hasConfig && (
                                    <div style={ { padding: '0.5rem', color: '#999', fontSize: '0.85rem' } }>
                                      Not configured — using Lambda defaults (keywords: submit request, sr, raise request | Flow ID: 25854716414220116)
                                    </div>
                                  ) }
                                  { hasConfig && Object.entries( cfg ).map( ( [ flowKey, trigger ]: [ string, any ] ) => (
                                    <div key={ flowKey } style={ { padding: '0.75rem', background: '#f8fafc', borderRadius: '0.375rem', marginBottom: '0.5rem', fontSize: '0.85rem' } }>
                                      <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' } }>
                                        <strong style={ { color: '#1a3a2a' } }>{ flowKey }</strong>
                                        <span style={ {
                                          padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 600,
                                          background: trigger?.enabled !== false ? '#f3f4f6' : '#f3f4f6',
                                          color: trigger?.enabled !== false ? '#0f2a1d' : '#6b7280',
                                        } }>
                                          { trigger?.enabled !== false ? '● Enabled' : '○ Disabled' }
                                        </span>
                                      </div>
                                      <div style={ { display: 'grid', gridTemplateColumns: '120px 1fr', gap: '4px 12px', fontSize: '0.8rem' } }>
                                        <span style={ { color: '#888' } }>Flow ID:</span>
                                        <span style={ { fontFamily: 'monospace', fontSize: '0.75rem' } }>{ trigger?.flowId || '(default)' }</span>
                                        <span style={ { color: '#888' } }>Keywords:</span>
                                        <span>{ ( trigger?.keywords || [] ).map( ( k: string ) => `"${k}"` ).join( ', ' ) || '(default)' }</span>
                                        <span style={ { color: '#888' } }>Body:</span>
                                        <span style={ { maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ trigger?.message?.body || '(default)' }</span>
                                        <span style={ { color: '#888' } }>Footer:</span>
                                        <span>{ trigger?.message?.footer || '(default)' }</span>
                                        <span style={ { color: '#888' } }>CTA:</span>
                                        <span>{ trigger?.message?.flowCta || '(default)' }</span>
                                        { trigger?.message?.header && (
                                          <>
                                            <span style={ { color: '#888' } }>Header:</span>
                                            <span>{ trigger?.message?.header }</span>
                                          </>
                                        ) }
                                      </div>
                                    </div>
                                  ) ) }
                                </>
                              );
                            } )() }
                          </div>
                        ) }

                        {/* Generic JSON display for other configs */ }
                        { item.key !== 'flow_triggers_config' && botFlowConfigs[ item.key ] && (
                          <pre style={ { background: '#f8fafc', padding: '0.75rem', borderRadius: '0.375rem', fontSize: '0.75rem', maxHeight: '200px', overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' } }>
                            { JSON.stringify( botFlowConfigs[ item.key ], null, 2 ) }
                          </pre>
                        ) }
                        { item.key !== 'flow_triggers_config' && !botFlowConfigs[ item.key ] && (
                          <div style={ { padding: '0.5rem', color: '#999', fontSize: '0.85rem' } }>
                            Not configured — using Lambda defaults
                          </div>
                        ) }
                      </div>
                    ) ) }

                    {/* Edit modal */ }
                    { botFlowEditKey && (
                      <div style={ { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } }>
                        <div style={ { background: '#fff', borderRadius: '0.75rem', padding: '1.5rem', width: '90%', maxWidth: '700px', maxHeight: '80vh', overflow: 'auto' } }>
                          <h4 style={ { marginBottom: '0.5rem' } }>Edit: { botFlowEditKey }</h4>
                          <p style={ { fontSize: '0.8rem', color: '#888', marginBottom: '1rem' } }>Paste valid JSON. This will be stored in SystemConfigTable.</p>
                          <textarea
                            value={ botFlowEditValue }
                            onChange={ ( e ) => setBotFlowEditValue( e.target.value ) }
                            rows={ 20 }
                            style={ { width: '100%', fontFamily: 'monospace', fontSize: '0.8rem', padding: '0.75rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', resize: 'vertical' } }
                          />
                          <div style={ { display: 'flex', gap: '0.5rem', marginTop: '1rem', justifyContent: 'flex-end' } }>
                            <Button variant="secondary" onClick={ () => { setBotFlowEditKey( '' ); setBotFlowEditValue( '' ); } }>
                              Cancel
                            </Button>
                            <Button
                              variant="primary"
                              loading={ botFlowSaving }
                              onClick={ () => {
                                try
                                {
                                  const parsed = JSON.parse( botFlowEditValue );
                                  handleSaveBotFlowConfig( botFlowEditKey, parsed );
                                } catch
                                {
                                  toast.error( 'Invalid JSON' );
                                }
                              } }
                            >
                              Save
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) }
                  </>
                ) }

                <div style={ { marginTop: '1rem', padding: '1rem', background: '#f8fafc', borderRadius: '0.5rem', fontSize: '0.85rem', color: '#666' } }>
                  <strong>How it works:</strong> Configs stored here override Lambda defaults. The inbound handler reads these on each message.
                  Leave empty to use the hardcoded defaults in the Lambda code.
                </div>

                {/* Flow JSON — Inner Pages Control */ }
                <div style={ { marginTop: '2rem', padding: '1.25rem', border: '1px solid #1a3a2a', borderRadius: '0.75rem', background: '#fff' } }>
                  <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' } }>
                    <div>
                      <h4 style={ { margin: 0, color: '#1a3a2a' } }>Flow JSON — Inner Pages</h4>
                      <p style={ { margin: '4px 0 0', fontSize: '0.8rem', color: '#888' } }>
                        Full control of WhatsApp Flow screens (ORDER_SELECT, SUBMIT_REQUEST_FORM, TERMS, REVIEW, THANK_YOU). Stored in SystemConfigTable.
                      </p>
                    </div>
                    <div style={ { display: 'flex', gap: '0.5rem' } }>
                      { flowJson && !flowJsonEditMode && (
                        <Button variant="secondary" onClick={ () => {
                          setFlowJsonEditMode( true );
                          setFlowJsonEditValue( JSON.stringify( flowJson, null, 2 ) );
                        } }>
                          Edit JSON
                        </Button>
                      ) }
                      { !flowJson && !flowJsonEditMode && (
                        <Button variant="primary" onClick={ () => {
                          setFlowJsonEditMode( true );
                          setFlowJsonEditValue( '' );
                        } }>
                          Initialize
                        </Button>
                      ) }
                      <Button variant="secondary" onClick={ loadFlowJson } loading={ flowJsonLoading }>
                        <RefreshIcon size={ 14 } /> Refresh
                      </Button>
                    </div>
                  </div>

                  { flowJsonLoading && <SkeletonCard /> }

                  { !flowJsonLoading && !flowJson && !flowJsonEditMode && (
                    <div style={ { padding: '1.5rem', color: '#666', fontSize: '0.85rem', textAlign: 'center', background: '#f9fafb', borderRadius: '0.5rem', border: '1px dashed #1a3a2a' } }>
                      <div style={ { fontSize: '1.5rem', marginBottom: '0.5rem' } }>—</div>
                      <div style={ { fontWeight: 600, marginBottom: '0.25rem', color: '#0f2a1d' } }>No Flow JSON stored yet</div>
                      <div>Click &quot;Initialize&quot; above, then paste the full WhatsApp Flow JSON from <code>submit-request-flow-v3.json</code> to enable screen-level control.</div>
                    </div>
                  ) }

                  { !flowJsonLoading && flowJson && !flowJsonEditMode && (
                    <>
                      {/* Routing Model */ }
                      <div style={ { marginBottom: '1rem', padding: '0.75rem', background: '#f9fafb', borderRadius: '0.375rem' } }>
                        <strong style={ { fontSize: '0.85rem', color: '#1a3a2a' } }>Routing Model</strong>
                        <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' } }>
                          { flowJson.routing_model && Object.entries( flowJson.routing_model ).map( ( [ from, toArr ]: [ string, any ] ) => (
                            <div key={ from } style={ { display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem' } }>
                              <span style={ { padding: '2px 8px', background: '#f9fafb', borderRadius: '8px', fontFamily: 'monospace', fontWeight: 600, color: '#1a3a2a' } }>{ from }</span>
                              { toArr && toArr.length > 0 ? (
                                <>
                                  <span style={ { color: '#888' } }>→</span>
                                  { toArr.map( ( t: string ) => (
                                    <span key={ t } style={ { padding: '2px 8px', background: '#f3f4f6', borderRadius: '8px', fontFamily: 'monospace', color: '#1a3a2a' } }>{ t }</span>
                                  ) ) }
                                </>
                              ) : (
                                <span style={ { color: '#999', fontSize: '0.75rem' } }>(terminal)</span>
                              ) }
                            </div>
                          ) ) }
                        </div>
                      </div>

                      {/* Screens */ }
                      <div style={ { fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem', color: '#333' } }>
                        Screens ({ flowJson.screens?.length || 0 })
                      </div>
                      { ( flowJson.screens || [] ).map( ( screen: any, idx: number ) => (
                        <div key={ screen.id || idx } style={ { marginBottom: '0.5rem', border: '1px solid #e5e7eb', borderRadius: '0.5rem', overflow: 'hidden' } }>
                          <div
                            style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.6rem 0.75rem', background: '#fafafa', cursor: 'pointer' } }
                            onClick={ () => setFlowJsonExpandedScreen( flowJsonExpandedScreen === screen.id ? null : screen.id ) }
                          >
                            <div style={ { display: 'flex', alignItems: 'center', gap: '0.5rem' } }>
                              <span style={ { fontFamily: 'monospace', fontWeight: 600, color: '#1a3a2a', fontSize: '0.85rem' } }>{ screen.id }</span>
                              { screen.title && <span style={ { color: '#888', fontSize: '0.8rem' } }>— { screen.title }</span> }
                              { screen.terminal && <span style={ { padding: '1px 6px', background: '#f9fafb', color: '#0f2a1d', borderRadius: '8px', fontSize: '10px', fontWeight: 600 } }>TERMINAL</span> }
                            </div>
                            <div style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.75rem', color: '#888' } }>
                              { screen.data && <span>{ Object.keys( screen.data ).length } data fields</span> }
                              { screen.layout?.children && <span>{ screen.layout.children.length } components</span> }
                              <span style={ { fontSize: '14px' } }>{ flowJsonExpandedScreen === screen.id ? '▼' : '▶' }</span>
                            </div>
                          </div>
                          { flowJsonExpandedScreen === screen.id && (
                            <div style={ { padding: '0.75rem', background: '#fff' } }>
                              {/* Data schema */ }
                              { screen.data && Object.keys( screen.data ).length > 0 && (
                                <div style={ { marginBottom: '0.75rem' } }>
                                  <div style={ { fontSize: '0.8rem', fontWeight: 600, color: '#555', marginBottom: '4px' } }>Data Schema</div>
                                  <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.5rem' } }>
                                    { Object.entries( screen.data ).map( ( [ key, val ]: [ string, any ] ) => (
                                      <span key={ key } style={ { padding: '2px 8px', background: '#f3e8ff', borderRadius: '8px', fontFamily: 'monospace', fontSize: '0.75rem', color: '#6b21a8' } }>
                                        { key }: { val?.type || 'object' }
                                      </span>
                                    ) ) }
                                  </div>
                                </div>
                              ) }
                              {/* Layout components */ }
                              { screen.layout?.children && (
                                <div>
                                  <div style={ { fontSize: '0.8rem', fontWeight: 600, color: '#555', marginBottom: '4px' } }>Layout Components</div>
                                  { screen.layout.children.map( ( comp: any, ci: number ) => (
                                    <div key={ ci } style={ { padding: '4px 8px', marginBottom: '2px', background: '#f8fafc', borderRadius: '4px', fontSize: '0.8rem', display: 'flex', gap: '0.5rem', alignItems: 'center' } }>
                                      <span style={ { fontWeight: 600, color: '#0369a1', minWidth: '100px' } }>{ comp.type }</span>
                                      { comp.text && <span style={ { color: '#666', maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ typeof comp.text === 'string' ? comp.text.substring( 0, 80 ) : '(dynamic)' }</span> }
                                      { comp.label && <span style={ { color: '#666' } }>label: { comp.label }</span> }
                                      { comp.name && <span style={ { color: '#888', fontFamily: 'monospace', fontSize: '0.75rem' } }>name={ comp.name }</span> }
                                      { comp.src && <span style={ { color: '#888', fontSize: '0.75rem' } }>[image]</span> }
                                      { comp.children && <span style={ { color: '#888', fontSize: '0.75rem' } }>({ comp.children.length } children)</span> }
                                    </div>
                                  ) ) }
                                </div>
                              ) }
                            </div>
                          ) }
                        </div>
                      ) ) }

                      {/* Meta info */ }
                      <div style={ { marginTop: '0.75rem', display: 'flex', gap: '1rem', fontSize: '0.75rem', color: '#888' } }>
                        { flowJson.version && <span>Flow version: { flowJson.version }</span> }
                        { flowJson.data_api_version && <span>Data API: { flowJson.data_api_version }</span> }
                      </div>
                    </>
                  ) }

                  {/* Edit modal */ }
                  { flowJsonEditMode && (
                    <div style={ { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } }>
                      <div style={ { background: '#fff', borderRadius: '0.75rem', padding: '1.5rem', width: '90%', maxWidth: '800px', maxHeight: '85vh', overflow: 'auto' } }>
                        <h4 style={ { marginBottom: '0.5rem', color: '#1a3a2a' } }>Edit Flow JSON — Inner Pages</h4>
                        <p style={ { fontSize: '0.8rem', color: '#888', marginBottom: '1rem' } }>
                          Paste the full WhatsApp Flow JSON (screens, routing_model, version). Stored in SystemConfigTable under key <code>whatsapp_flow_json</code>.
                        </p>
                        <textarea
                          value={ flowJsonEditValue }
                          onChange={ ( e ) => setFlowJsonEditValue( e.target.value ) }
                          rows={ 25 }
                          placeholder='Paste the full WhatsApp Flow JSON here (from submit-request-flow-v3.json)...'
                          style={ { width: '100%', fontFamily: 'monospace', fontSize: '0.75rem', padding: '0.75rem', border: '1px solid #d1d5db', borderRadius: '0.375rem', resize: 'vertical' } }
                        />
                        <div style={ { display: 'flex', gap: '0.5rem', marginTop: '1rem', justifyContent: 'flex-end' } }>
                          <Button variant="secondary" onClick={ () => { setFlowJsonEditMode( false ); setFlowJsonEditValue( '' ); } }>
                            Cancel
                          </Button>
                          <Button variant="primary" loading={ flowJsonSaving } onClick={ handleSaveFlowJson }>
                            Save Flow JSON
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) }
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* WEBHOOK TAB */ }
          { activeTab === 'webhook' && (
            <TabErrorBoundary tabName="Webhook">
              <div className="webhook-tab">
                {/* Razorpay Webhook Section */ }
                <div className="section" style={ { background: '#ffffff', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1rem', color: '#1a1a1a', border: '1px solid #1a3a2a' } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' } }>
                    <div style={ { width: '40px', height: '40px', background: '#f9fafb', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #e5e7eb' } }>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <h3 style={ { margin: 0, fontSize: '1.25rem', color: '#1a1a1a' } }>Razorpay Webhook</h3>
                      <span className="badge" style={ { background: '#f3f4f6', color: '#1a1a1a', marginTop: '4px' } }>Active</span>
                    </div>
                  </div>

                  <div style={ { background: '#f9fafb', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1rem', border: '1px solid #e5e7eb' } }>
                    <div style={ { marginBottom: '0.75rem' } }>
                      <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Webhook URL</label>
                      <code style={ { fontSize: '0.85rem', wordBreak: 'break-all', color: '#1a1a1a' } }>https://wecare.digital/api/razorpay-webhook</code>
                    </div>
                    <div>
                      <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Credentials</label>
                      <code style={ { fontSize: '0.85rem', color: '#1a1a1a' } }>Managed server-side; values are never exposed in the browser.</code>
                    </div>
                  </div>

                  <div>
                    <label style={ { fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block', color: '#1a1a1a' } }>Supported Events</label>
                    <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.5rem' } }>
                      { [
                        { event: 'payment.captured', desc: 'Payment successful', color: '#1a3a2a' },
                        { event: 'payment.failed', desc: 'Payment failed', color: '#6b7280' },
                        { event: 'payment.authorized', desc: 'Payment authorized', color: '#1a3a2a' },
                        { event: 'refund.created', desc: 'Refund initiated', color: '#6b7280' },
                        { event: 'refund.processed', desc: 'Refund completed', color: '#1a3a2a' },
                        { event: 'order.paid', desc: 'Order paid', color: '#1a3a2a' },
                        { event: 'payment_link.paid', desc: 'Payment link used', color: '#1a3a2a' },
                        { event: 'payment.dispute.*', desc: 'Dispute events', color: '#6b7280' },
                        { event: 'settlement.*', desc: 'Settlement events', color: '#1a3a2a' },
                      ].map( ( { event, desc, color } ) => (
                        <div key={ event } style={ { background: '#f3f4f6', padding: '0.5rem 0.75rem', borderRadius: '0.375rem', fontSize: '0.8rem', border: '1px solid #e5e7eb' } }>
                          <div style={ { display: 'flex', alignItems: 'center', gap: '0.5rem' } }>
                            <span style={ { width: '8px', height: '8px', borderRadius: '50%', background: color } } />
                            <span style={ { fontFamily: 'monospace', color: '#1a1a1a' } }>{ event }</span>
                          </div>
                          <div style={ { fontSize: '0.7rem', color: '#6b7280', marginTop: '2px' } }>{ desc }</div>
                        </div>
                      ) ) }
                    </div>
                  </div>
                </div>

                {/* Razorpay API Reference */ }
                <div className="section" style={ { background: '#E8F5E9', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1.5rem', border: '1px solid #C8E6C9' } }>
                  <h4 style={ { margin: '0 0 1rem 0', fontSize: '1rem', color: '#2E7D32' } }>Razorpay API Reference</h4>

                  <div style={ { marginBottom: '0.75rem' } }>
                    <div style={ { fontWeight: 600, fontSize: '0.8rem', color: '#2E7D32', marginBottom: '4px' } }>Authentication: Basic Auth</div>
                    <div style={ { fontSize: '0.75rem', color: '#6b7280' } }>All Razorpay APIs use HTTP Basic Auth with key_id:key_secret (base64 encoded).</div>
                    <pre style={ { fontSize: '0.7rem', color: '#1a1a1a', background: '#fff', padding: '0.5rem', borderRadius: '4px', overflow: 'auto', margin: '4px 0' } }>{ `# Basic Auth header
Authorization: Basic base64(YOUR_KEY_ID:YOUR_KEY_SECRET)

# curl example
curl -u YOUR_KEY_ID:YOUR_KEY_SECRET \\
  https://api.razorpay.com/v1/payments/pay_XXXXX`}</pre>
                  </div>

                  <div style={ { marginBottom: '0.75rem' } }>
                    <div style={ { fontWeight: 600, fontSize: '0.8rem', color: '#2E7D32', marginBottom: '4px' } }>Base URL</div>
                    <div style={ { display: 'flex', gap: '0.5rem', flexWrap: 'wrap' } }>
                      <code style={ { fontSize: '0.75rem', background: '#fff', padding: '2px 6px', borderRadius: '4px' } }>v1: https://api.razorpay.com/v1</code>
                      <code style={ { fontSize: '0.75rem', background: '#fff', padding: '2px 6px', borderRadius: '4px' } }>v2: https://api.razorpay.com/v2 (Route/Linked Accounts)</code>
                    </div>
                  </div>

                  <div style={ { marginBottom: '0.75rem' } }>
                    <div style={ { fontWeight: 600, fontSize: '0.8rem', color: '#2E7D32', marginBottom: '4px' } }>Key API Endpoints</div>
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.5rem' } }>
                      { [
                        { method: 'POST', path: '/v1/orders', desc: 'Create Order' },
                        { method: 'GET', path: '/v1/orders/{id}', desc: 'Fetch Order' },
                        { method: 'GET', path: '/v1/orders/{id}/payments', desc: 'Fetch Payments for Order' },
                        { method: 'GET', path: '/v1/payments/{id}', desc: 'Fetch Payment' },
                        { method: 'POST', path: '/v1/payments/{id}/capture', desc: 'Capture Payment' },
                        { method: 'GET', path: '/v1/payments', desc: 'Fetch All Payments' },
                        { method: 'POST', path: '/v1/payments/{id}/refund', desc: 'Create Refund' },
                        { method: 'GET', path: '/v1/refunds/{id}', desc: 'Fetch Refund' },
                        { method: 'POST', path: '/v1/payment_links', desc: 'Create Payment Link' },
                        { method: 'GET', path: '/v1/payment_links/{id}', desc: 'Fetch Payment Link' },
                        { method: 'POST', path: '/v1/invoices', desc: 'Create Invoice' },
                        { method: 'GET', path: '/v1/settlements', desc: 'Fetch Settlements' },
                      ].map( ( { method, path, desc } ) => (
                        <div key={ `${method}${path}` } style={ { background: '#fff', padding: '0.35rem 0.5rem', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '0.5rem' } }>
                          <span style={ { color: method === 'POST' ? '#1a3a2a' : '#1d4ed8', fontWeight: 600, fontSize: '0.65rem', fontFamily: 'monospace', minWidth: '32px' } }>{ method }</span>
                          <code style={ { fontSize: '0.7rem', color: '#1a1a1a' } }>{ path }</code>
                          <span style={ { fontSize: '0.65rem', color: '#9ca3af', marginLeft: 'auto' } }>{ desc }</span>
                        </div>
                      ) ) }
                    </div>
                  </div>

                  <div style={ { marginBottom: '0.75rem' } }>
                    <div style={ { fontWeight: 600, fontSize: '0.8rem', color: '#2E7D32', marginBottom: '4px' } }>Webhook Verification</div>
                    <div style={ { fontSize: '0.75rem', color: '#6b7280' } }>Razorpay signs webhooks with HMAC SHA-256 using your webhook secret.</div>
                    <pre style={ { fontSize: '0.7rem', color: '#1a1a1a', background: '#fff', padding: '0.5rem', borderRadius: '4px', overflow: 'auto', margin: '4px 0' } }>{ `# Verify webhook signature
expected = hmac.new(webhook_secret, request_body, sha256).hexdigest()
# Compare with X-Razorpay-Signature header`}</pre>
                    <div style={ { fontSize: '0.75rem', color: '#6b7280', marginTop: '2px' } }>Webhook payloads are JSON. Retries on non-200 response. Use ports 80/443 only.</div>
                  </div>

                  <div>
                    <div style={ { fontWeight: 600, fontSize: '0.8rem', color: '#2E7D32', marginBottom: '4px' } }>Rate Limiting</div>
                    <div style={ { fontSize: '0.75rem', color: '#6b7280' } }>Watch for HTTP 429. Use exponential backoff with jitter. Pagination: <code style={ { fontSize: '0.7rem' } }>count</code> (default 10) + <code style={ { fontSize: '0.7rem' } }>skip</code> params.</div>
                  </div>

                  <div style={ { display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' } }>
                    <a href="https://razorpay.com/docs/api" target="_blank" rel="noopener noreferrer" style={ { display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.4rem 0.75rem', background: '#d1f470', color: '#1a3a2a', borderRadius: '6px', fontSize: '0.75rem', textDecoration: 'none', fontWeight: 500 } }>
                      API Docs
                    </a>
                    <a href="https://dashboard.razorpay.com" target="_blank" rel="noopener noreferrer" style={ { display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.4rem 0.75rem', background: '#d1f470', color: '#1a3a2a', borderRadius: '6px', fontSize: '0.75rem', textDecoration: 'none', fontWeight: 500 } }>
                      Razorpay Dashboard
                    </a>
                    <a href="https://www.postman.com/razorpaydev" target="_blank" rel="noopener noreferrer" style={ { display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.4rem 0.75rem', background: '#E65100', color: '#fff', borderRadius: '6px', fontSize: '0.75rem', textDecoration: 'none', fontWeight: 500 } }>
                      Postman Workspace
                    </a>
                  </div>
                </div>

                {/* Razorpay Data Captured */ }
                <div className="section" style={ { background: 'white', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1.5rem', border: '1px solid #1a3a2a' } }>
                  <h4 style={ { marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#1a1a1a' } }>
                    <DataIcon size={ 18 } />
                    Data Captured for Payments
                  </h4>
                  <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' } }>
                    { [
                      { field: 'paymentId', desc: 'Razorpay Payment ID' },
                      { field: 'orderId', desc: 'Razorpay Order ID' },
                      { field: 'referenceId', desc: 'Custom Reference ID' },
                      { field: 'amount', desc: 'Amount in paise' },
                      { field: 'amountInRupees', desc: 'Amount in rupees' },
                      { field: 'currency', desc: 'Currency (INR)' },
                      { field: 'method', desc: 'UPI, Card, Netbanking, Wallet' },
                      { field: 'contact', desc: 'Customer phone' },
                      { field: 'email', desc: 'Customer email' },
                      { field: 'status', desc: 'captured, failed, etc.' },
                      { field: 'notes', desc: 'Custom metadata' },
                      { field: 'createdAt', desc: 'Timestamp' },
                    ].map( ( { field, desc } ) => (
                      <div key={ field } style={ { padding: '0.75rem', background: '#f9fafb', borderRadius: '0.375rem', borderLeft: '3px solid #1a3a2a' } }>
                        <code style={ { fontSize: '0.85rem', color: '#1a3a2a' } }>{ field }</code>
                        <div style={ { fontSize: '0.75rem', color: '#6b7280', marginTop: '2px' } }>{ desc }</div>
                      </div>
                    ) ) }
                  </div>
                </div>

                {/* Retired payment gateway — section removed 2026-09-26.
                    It documented PayU's live OAuth and payment-link endpoints
                    (accounts.payu.in, oneapi.payu.in), its webhook URL and its
                    Lambda name. All of that is gone: the function, route, table
                    and secret were deleted, the secret's 30-day recovery window
                    expired 2026-09-25, and Razorpay is the only gateway. Leaving
                    it would tell an operator to call an API this platform no
                    longer has credentials for.
                    See docs/execution/aws-inventory-findings.md and
                    docs/provider-retirement-inventory.md. */ }

                {/* Retired India SMS provider — section removed 2026-09-19.
                    It documented a retired provider's live send endpoints, DLT
                    payloads and credential headers. Leaving it would tell an
                    operator to call an API this platform no longer uses. The
                    TRAI DLT registry itself is live and is administered at
                    /dm/sms -> DLT Templates; historical messages are read-only
                    under /dm/sms -> Legacy history.
                    See docs/provider-retirement-inventory.md. */ }

                {/* AWS Pinpoint SMS & Voice Section */ }
                <div className="section" style={ { background: '#ffffff', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1.5rem', color: '#1a1a1a', border: '1px solid #1a3a2a' } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' } }>
                    <div style={ { width: '40px', height: '40px', background: '#f9fafb', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #e5e7eb' } }>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                        <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <h3 style={ { margin: 0, fontSize: '1.25rem', color: '#1a1a1a' } }>AWS Pinpoint SMS & Voice v2</h3>
                      <span className="badge" style={ { background: '#f3f4f6', color: '#0f2a1d', marginTop: '4px' } }>us-east-1 | Active</span>
                    </div>
                  </div>

                  <div style={ { background: '#f9fafb', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1rem', border: '1px solid #e5e7eb' } }>
                    <h4 style={ { margin: '0 0 0.75rem 0', fontSize: '0.9rem', color: '#0f2a1d' } }>API Endpoints</h4>
                    { [
                      { label: 'Send SMS', method: 'POST', path: '/sms-aws/send' },
                      { label: 'List SMS Messages', method: 'GET', path: '/sms-aws/messages' },
                      { label: 'Delete SMS Message', method: 'DELETE', path: '/sms-aws/messages/{messageId}' },
                      { label: 'Clear SMS Logs', method: 'DELETE', path: '/sms-aws/clear-logs' },
                      { label: 'Make Voice Call (TTS)', method: 'POST', path: '/voice-aws/call' },
                      { label: 'List Voice Calls', method: 'GET', path: '/voice-aws/calls' },
                      { label: 'Delete Voice Call', method: 'DELETE', path: '/voice-aws/calls/{callId}' },
                      { label: 'Clear Voice Logs', method: 'DELETE', path: '/voice-aws/clear-logs' },
                    ].map( ( { label, method, path } ) => (
                      <div key={ path } style={ { marginBottom: '0.5rem' } }>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>{ label }</label>
                        <code style={ { fontSize: '0.8rem', color: '#1a1a1a', background: '#fff', padding: '0.35rem 0.5rem', display: 'inline-block', borderRadius: '4px', marginTop: '2px' } }>
                          <span style={ { color: method === 'POST' ? '#1a3a2a' : method === 'DELETE' ? '#6b7280' : '#1d4ed8', fontWeight: 600 } }>{ method }</span> https://wecare.digital/api{ path }
                        </code>
                      </div>
                    ) ) }
                  </div>

                  <div style={ { background: '#FFF3E0', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1rem', border: '1px solid #FFE0B2' } }>
                    <h4 style={ { margin: '0 0 0.5rem 0', fontSize: '0.9rem', color: '#E65100' } }>Phone Numbers & Configuration</h4>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' } }>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Voice (Toll-Free, Intl)</label>
                        <code style={ { fontSize: '0.85rem', color: '#1a1a1a' } }>+1 (844) 489-1209</code>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Toll-Free Status</label>
                        <code style={ { fontSize: '0.85rem', color: '#1a1a1a' } }>PENDING Registration</code>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>SMS Sender ID</label>
                        <code style={ { fontSize: '0.85rem', color: '#1a1a1a' } }>WECARE</code>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>TTS Voice</label>
                        <code style={ { fontSize: '0.85rem', color: '#1a1a1a' } }>RAVEENA (Indian English)</code>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Pool ID</label>
                        <code style={ { fontSize: '0.75rem', color: '#1a1a1a' } }>TBD (pending toll-free approval)</code>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>Protect Config</label>
                        <code style={ { fontSize: '0.75rem', color: '#1a1a1a' } }>protect-b137924dfb934c32b1d10c28b737d08c</code>
                      </div>
                    </div>
                  </div>

                  <div>
                    <label style={ { fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block', color: '#1a1a1a' } }>Lambda Functions</label>
                    <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.5rem' } }>
                      { [
                        { name: 'wecare-sms-aws', desc: 'SMS send + CRUD', color: '#1a3a2a' },
                        { name: 'wecare-voice-aws', desc: 'Voice call + CRUD', color: '#1a3a2a' },
                      ].map( ( { name, desc, color } ) => (
                        <div key={ name } style={ { background: '#f9fafb', padding: '0.5rem 0.75rem', borderRadius: '0.375rem', fontSize: '0.8rem', border: '1px solid #e5e7eb' } }>
                          <div style={ { display: 'flex', alignItems: 'center', gap: '0.5rem' } }>
                            <span style={ { width: '8px', height: '8px', borderRadius: '50%', background: color } } />
                            <span style={ { fontFamily: 'monospace', color: '#1a1a1a', fontWeight: 500 } }>{ name }</span>
                          </div>
                          <div style={ { fontSize: '0.7rem', color: '#6b7280', marginTop: '2px' } }>{ desc }</div>
                        </div>
                      ) ) }
                    </div>
                  </div>
                </div>

                {/* WhatsApp Inbound Messages Webhook */ }
                <div className="section" style={ { background: '#ffffff', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1.5rem', color: '#1a1a1a', border: '1px solid #25D366' } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' } }>
                    <div style={ { width: '40px', height: '40px', background: '#f9fafb', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #e5e7eb' } }>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" stroke="#25D366" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </div>
                    <div>
                      <h3 style={ { margin: 0, fontSize: '1.25rem', color: '#1a1a1a' } }>WhatsApp Inbound Messages</h3>
                      <span className="badge" style={ { background: '#f3f4f6', color: '#0f2a1d', marginTop: '4px' } }>Direct Meta Graph API | Active</span>
                    </div>
                  </div>

                  <div style={ { background: '#f9fafb', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1rem', border: '1px solid #e5e7eb' } }>
                    <h4 style={ { margin: '0 0 0.75rem 0', fontSize: '0.9rem', color: '#0f2a1d' } }>Webhook Configuration</h4>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.85rem' } }>
                      <div><span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block' } }>Verify Token</span><code style={ { color: '#1a1a1a' } }>Configured server-side</code></div>
                      <div><span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block' } }>Subscribed Fields</span><code style={ { color: '#1a1a1a' } }>messages, calls</code></div>
                      <div><span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block' } }>Lambda</span><code style={ { color: '#1a1a1a' } }>wecare-whatsapp-calling</code></div>
                      <div><span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block' } }>Meta App ID</span><code style={ { color: '#1a1a1a' } }>2238810740192680 (WECARE.DIGITAL)</code></div>
                      <div><span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block' } }>DynamoDB Table</span><code style={ { color: '#1a1a1a' } }>WhatsAppCallingTable</code></div>
                    </div>

                    <div style={ { marginTop: '0.75rem' } }>
                      <span style={ { color: '#6b7280', fontSize: '0.75rem', display: 'block', marginBottom: '0.25rem' } }>API Routes (all on wecare.digital/api)</span>
                      <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.25rem', fontSize: '0.8rem' } }>
                        { [
                          { m: 'GET', p: '/whatsapp', d: 'Webhook verify' },
                          { m: 'POST', p: '/whatsapp', d: 'Call + message events from Meta' },
                          { m: 'GET', p: '/whatsapp/active', d: 'Active/ringing calls' },
                          { m: 'GET', p: '/whatsapp/logs', d: 'Call event logs' },
                          { m: 'POST', p: '/whatsapp/accept', d: 'Accept call (SDP answer)' },
                          { m: 'POST', p: '/whatsapp/reject', d: 'Reject ringing call' },
                          { m: 'POST', p: '/whatsapp/hangup', d: 'Hang up active call' },
                          { m: 'POST', p: '/whatsapp/outbound', d: 'Outbound call / permission' },
                          { m: 'GET', p: '/whatsapp/config', d: 'Auto-pickup config' },
                          { m: 'POST', p: '/whatsapp/config', d: 'Update config' },
                          { m: 'DELETE', p: '/whatsapp', d: 'Clear logs' },
                        ].map( ( { m, p, d } ) => (
                          <div key={ `${m}${p}` } style={ { background: '#fff', padding: '0.25rem 0.5rem', borderRadius: '4px' } }>
                            <code><span style={ { color: m === 'POST' ? '#1a3a2a' : m === 'DELETE' ? '#6b7280' : '#1d4ed8', fontWeight: 600, fontSize: '0.7rem' } }>{ m }</span> <span style={ { fontSize: '0.75rem' } }>{ p }</span></code>
                            <span style={ { fontSize: '0.65rem', color: '#9ca3af', marginLeft: '4px' } }>{ d }</span>
                          </div>
                        ) ) }
                      </div>
                    </div>
                  </div>

                  <div style={ { background: '#FFF3E0', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1rem', border: '1px solid #FFE0B2' } }>
                    <h4 style={ { margin: '0 0 0.5rem 0', fontSize: '0.9rem', color: '#E65100' } }>Phone Numbers (Calling + SIP Ready)</h4>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' } }>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>+91 93309 94400 (WECARE.DIGITAL)</label>
                        <code style={ { fontSize: '0.8rem', color: '#1a1a1a' } }>Meta ID: 1016149501586345</code>
                        <div style={ { fontSize: '0.7rem', color: '#25D366' } }>SIP: sip.wecare.digital:5061 · SDES</div>
                      </div>
                      <div>
                        <label style={ { fontSize: '0.75rem', color: '#6b7280', display: 'block' } }>+91 99033 00044 (Manish Agarwal)</label>
                        <code style={ { fontSize: '0.8rem', color: '#1a1a1a' } }>Meta ID: 1055232054343117</code>
                        <div style={ { fontSize: '0.7rem', color: '#25D366' } }>SIP: sip.wecare.digital:5061 · SDES</div>
                      </div>
                    </div>
                  </div>

                  <div style={ { display: 'flex', gap: '0.5rem', flexWrap: 'wrap' } }>
                    <button onClick={ () => { navigator.clipboard.writeText( 'https://wecare.digital/api/whatsapp' ); toast.success( 'Callback URL copied' ); } }
                      style={ { padding: '0.5rem 1rem', background: '#25D366', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 500 } }>
                      Copy Callback URL
                    </button>
                    <a href="https://developers.facebook.com/apps/891766673609917/webhooks/" target="_blank" rel="noopener noreferrer"
                      style={ { padding: '0.5rem 1rem', background: '#1877F2', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 500, textDecoration: 'none', display: 'inline-block' } }>
                      Open Meta App Dashboard
                    </a>
                  </div>
                </div>

                {/* Wix Headless Commerce Section */ }
                <div className="section" style={ { background: '#ffffff', padding: '1.5rem', borderRadius: '0.75rem', marginBottom: '1.5rem', color: '#1a1a1a', border: '1px solid #1a3a2a' } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' } }>
                    <div style={ { width: '40px', height: '40px', background: '#f9fafb', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #d1d5db' } }>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /><line x1="3" y1="6" x2="21" y2="6" stroke="#1a3a2a" strokeWidth="2" /><path d="M16 10a4 4 0 01-8 0" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </div>
                    <div>
                      <h3 style={ { margin: 0, fontSize: '1.25rem', color: '#1a1a1a' } }>Wix Headless Commerce</h3>
                      <span className="badge" style={ { background: '#f9fafb', color: '#1a3a2a', marginTop: '4px' } }>API-only | Catalog V3</span>
                    </div>
                  </div>

                  <p style={ { fontSize: '0.85rem', color: '#6b7280', lineHeight: 1.6, margin: '0 0 1rem' } }>
                    WECARE.DIGITAL is the only codebase and Amplify is the public frontend. Wix is used as a clean commerce backend for
                    catalog, inventory, cart and orders. The deleted Wix Editor/Velo repository is not part of the target architecture.
                  </p>

                  <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.5rem', fontSize: '0.8rem' } }>
                    { [
                      [ 'Products', 'Catalog V3' ],
                      [ 'Categories', 'Categories V3' ],
                      [ 'Inventory', 'Inventory Items V3' ],
                      [ 'Cart', 'eCommerce Cart V2' ],
                      [ 'Orders', 'eCommerce Orders' ],
                      [ 'Payment UI', 'AWS + Razorpay' ],
                    ].map( ( [ label, value ] ) => (
                      <div key={ label } style={ { background: '#f9fafb', padding: '0.6rem', borderRadius: '0.5rem', border: '1px solid #e5e7eb' } }>
                        <div style={ { color: '#6b7280', fontSize: '0.7rem' } }>{ label }</div>
                        <div style={ { fontWeight: 600, color: '#1a3a2a', marginTop: 2 } }>{ value }</div>
                      </div>
                    ) ) }
                  </div>

                  <div style={ { marginTop: '1rem', background: '#f9fafb', padding: '0.75rem', borderRadius: '0.5rem', fontSize: '0.8rem', color: '#374151' } }>
                    Runtime adapter: <code>amplify/functions/ecommerce/wix-store/handler.py</code>. Product prices and SKUs are variant-level;
                    product updates use Wix revisions; inventory is queried separately.
                  </div>
                </div>

                {/* Custom Webhooks Section */ }
                <div className="section-header" style={ { marginTop: '2rem' } }>
                  <h3>Custom Webhooks</h3>
                  <Button variant={ showWebhookForm ? 'secondary' : 'primary' } onClick={ () => setShowWebhookForm( !showWebhookForm ) }>
                    { showWebhookForm ? 'Cancel' : '+ Add Webhook' }
                  </Button>
                </div>

                {/* Add Webhook Form */ }
                { showWebhookForm && (
                  <div className="section" style={ { background: 'white', padding: '1.5rem', borderRadius: '0.5rem', marginBottom: '1.5rem' } }>
                    <h4 style={ { marginBottom: '1rem' } }>New Webhook</h4>

                    <div style={ { marginBottom: '1rem' } }>
                      <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>Name</label>
                      <input
                        type="text"
                        value={ newWebhook.name }
                        onChange={ ( e ) => setNewWebhook( { ...newWebhook, name: e.target.value } ) }
                        placeholder="My Webhook"
                        style={ { width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '0.375rem' } }
                      />
                    </div>

                    <div style={ { marginBottom: '1rem' } }>
                      <label style={ { display: 'block', marginBottom: '0.25rem', fontWeight: 500 } }>URL</label>
                      <input
                        type="url"
                        value={ newWebhook.url }
                        onChange={ ( e ) => setNewWebhook( { ...newWebhook, url: e.target.value } ) }
                        placeholder="https://your-server.com/webhook"
                        style={ { width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '0.375rem' } }
                      />
                    </div>

                    <div style={ { marginBottom: '1rem' } }>
                      <label style={ { display: 'block', marginBottom: '0.5rem', fontWeight: 500 } }>Events</label>
                      <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.5rem' } }>
                        { [ 'message.received', 'message.sent', 'message.delivered', 'message.read', 'payment.captured', 'payment.failed', 'contact.created', 'contact.updated' ].map( event => (
                          <label key={ event } style={ { display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.25rem 0.5rem', background: '#f3f4f6', borderRadius: '0.25rem', cursor: 'pointer' } }>
                            <input
                              type="checkbox"
                              checked={ newWebhook.events.includes( event ) }
                              onChange={ ( e ) => {
                                if ( e.target.checked )
                                {
                                  setNewWebhook( { ...newWebhook, events: [ ...newWebhook.events, event ] } );
                                } else
                                {
                                  setNewWebhook( { ...newWebhook, events: newWebhook.events.filter( ev => ev !== event ) } );
                                }
                              } }
                            />
                            <span style={ { fontSize: '0.85rem' } }>{ event }</span>
                          </label>
                        ) ) }
                      </div>
                    </div>

                    <Button variant="primary" onClick={ handleCreateWebhook } disabled={ !newWebhook.name || !newWebhook.url }>
                      Create Webhook
                    </Button>
                  </div>
                ) }

                {/* Webhooks List */ }
                { webhookLoading ? (
                  <div style={ { textAlign: 'center', padding: '2rem' } }>Loading webhooks...</div>
                ) : webhooks.length === 0 ? (
                  <div className="empty-state">
                    <span className="icon"><LinkIcon size={ 32 } /></span>
                    <p>No custom webhooks configured</p>
                    <p style={ { fontSize: '0.85rem', color: '#666' } }>Add a webhook to receive real-time notifications</p>
                  </div>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>URL</th>
                        <th>Events</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      { webhooks.map( wh => (
                        <tr key={ wh.id }>
                          <td>{ wh.name }</td>
                          <td style={ { fontFamily: 'monospace', fontSize: '0.85rem' } }>{ wh.url }</td>
                          <td>
                            <div style={ { display: 'flex', flexWrap: 'wrap', gap: '0.25rem' } }>
                              { wh.events.slice( 0, 3 ).map( ev => (
                                <span key={ ev } className="badge">{ ev }</span>
                              ) ) }
                              { wh.events.length > 3 && <span className="badge">+{ wh.events.length - 3 }</span> }
                            </div>
                          </td>
                          <td>
                            <span className={ `badge ${wh.enabled ? 'success' : ''}` }>
                              { wh.enabled ? 'Active' : 'Disabled' }
                            </span>
                          </td>
                          <td>
                            <div style={ { display: 'flex', gap: '0.5rem' } }>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={ () => handleToggleWebhook( wh.id, !wh.enabled ) }
                              >
                                { wh.enabled ? 'Disable' : 'Enable' }
                              </Button>
                              <Button
                                variant="danger"
                                size="sm"
                                onClick={ () => handleDeleteWebhook( wh.id ) }
                              >
                                Delete
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ) ) }
                    </tbody>
                  </table>
                ) }

                {/* Info */ }
                <div style={ { marginTop: '1.5rem', padding: '1rem', background: '#f8fafc', borderRadius: '0.5rem', fontSize: '0.85rem', color: '#666' } }>
                  <strong>Webhook Info:</strong> Webhooks send HTTP POST requests to your URL when events occur.
                  Each request includes a signature header (X-Razorpay-Signature) for HMAC SHA256 verification.
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* USER GUIDE TAB */ }
          { activeTab === 'guide' && (
            <TabErrorBoundary tabName="User Guide">
              <div className="guide-tab">
                <div className="section">
                  <h3>Welcome to WECARE.DIGITAL</h3>
                  <p style={ { color: 'var(--notion-text-secondary)', marginBottom: '24px' } }>
                    Your multi-channel messaging platform for WhatsApp, SMS, Email, and Voice communications.
                  </p>
                </div>

                <div className="section">
                  <h3>Getting Started</h3>
                  <div className="guide-cards">
                    <div className="guide-card">
                      <span className="guide-icon"><WhatsAppIcon size={ 24 } /></span>
                      <h4>WhatsApp Messaging</h4>
                      <p>Send and receive WhatsApp messages. Go to Messages → WhatsApp to start conversations.</p>
                    </div>
                    <div className="guide-card">
                      <span className="guide-icon"><PaymentIcon size={ 24 } /></span>
                      <h4>Payments</h4>
                      <p>Send payment requests via WhatsApp using Razorpay integration. Navigate to Pay → WhatsApp Pay.</p>
                    </div>
                    <div className="guide-card">
                      <span className="guide-icon"><ContactsIcon size={ 24 } /></span>
                      <h4>Contacts</h4>
                      <p>Manage your contact list. Import/export contacts and organize them for campaigns.</p>
                    </div>
                    <div className="guide-card">
                      <span className="guide-icon"><BulkIcon size={ 24 } /></span>
                      <h4>Bulk Messaging</h4>
                      <p>Send messages to multiple recipients at once. Use templates for consistent communication.</p>
                    </div>
                  </div>
                </div>

                <div className="section">
                  <h3>Key Features</h3>
                  <ul className="guide-list">
                    <li><strong>Multi-Channel:</strong> WhatsApp, SMS (AWS Pinpoint, IN SMS), Email (SES), Voice calls</li>
                    <li><strong>Templates:</strong> Create and manage WhatsApp message templates</li>
                    <li><strong>AI Assistant:</strong> Get AI-powered response suggestions</li>
                    <li><strong>Webhooks:</strong> Integrate with external systems via webhooks</li>
                    <li><strong>Billing:</strong> Track AWS resource usage and costs</li>
                    <li><strong>Bulk Operations:</strong> Send campaigns to multiple contacts</li>
                  </ul>
                </div>

                <div className="section">
                  <h3>WhatsApp Numbers</h3>
                  <div className="phones-grid">
                    <div className="phone-card">
                      <div className="phone-name">WECARE.DIGITAL</div>
                      <div className="phone-num">+91 93309 94400</div>
                      <span className="badge">Razorpay + UPI</span>
                    </div>
                    <div className="phone-card">
                      <div className="phone-name">Manish Agarwal</div>
                      <div className="phone-num">+91 99033 00044</div>
                      <span className="badge">Active</span>
                    </div>
                  </div>
                </div>

                <div className="section">
                  <h3>Need Help?</h3>
                  <p style={ { color: 'var(--notion-text-secondary)' } }>
                    Use the AI Assistant tab for quick answers, or contact support for technical issues.
                  </p>
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* SEARCH TAB */ }
          { activeTab === 'search' && (
            <TabErrorBoundary tabName="Search">
              <div className="search-tab">
                <div className="search-bar large">
                  <input
                    type="text"
                    placeholder="Search contacts, messages, content..."
                    value={ searchQuery }
                    onChange={ e => setSearchQuery( e.target.value ) }
                    autoFocus
                  />
                  { searchQuery && <button onClick={ () => setSearchQuery( '' ) }>×</button> }
                </div>

                { searchQuery.trim() && (
                  <>
                    {/* Contact Results */ }
                    { contacts.filter( c =>
                      c.name?.toLowerCase().includes( searchQuery.toLowerCase() ) ||
                      c.phone?.includes( searchQuery )
                    ).length > 0 && (
                        <div className="section">
                          <h3>Contacts</h3>
                          <div className="search-results">
                            { contacts.filter( c =>
                              c.name?.toLowerCase().includes( searchQuery.toLowerCase() ) ||
                              c.phone?.includes( searchQuery )
                            ).slice( 0, 10 ).map( c => (
                              <div key={ c.id } className="result-item contact">
                                <span className="icon"><ContactsIcon size={ 18 } /></span>
                                <span className="name">{ c.name || 'Unknown' }</span>
                                <span className="phone">{ c.phone }</span>
                              </div>
                            ) ) }
                          </div>
                        </div>
                      ) }

                    {/* Message Results */ }
                    { filteredMessages.length > 0 && (
                      <div className="section">
                        <h3>Messages ({ filteredMessages.length })</h3>
                        <div className="msg-list full">
                          { filteredMessages.slice( 0, 20 ).map( msg => {
                            const contact = contacts.find( c => c.id === msg.contactId );
                            return (
                              <div key={ msg.id } className={ `msg-item ${msg.direction.toLowerCase()}` }>
                                <span className="dir">{ msg.direction === 'INBOUND' ? '↓' : '↑' }</span>
                                <span className="name">{ contact?.name || contact?.phone || '...' }</span>
                                <span className="content">{ msg.content?.slice( 0, 60 ) || '[Media]' }</span>
                                <span className="time">{ new Date( msg.timestamp ).toLocaleString() }</span>
                              </div>
                            );
                          } ) }
                        </div>
                      </div>
                    ) }

                    {/* No Results */ }
                    { contacts.filter( c =>
                      c.name?.toLowerCase().includes( searchQuery.toLowerCase() ) ||
                      c.phone?.includes( searchQuery )
                    ).length === 0 && filteredMessages.length === 0 && (
                        <div className="empty-state">
                          <span className="icon"><SearchIcon size={ 32 } /></span>
                          <p>No results for &quot;{ searchQuery }&quot;</p>
                        </div>
                      ) }
                  </>
                ) }

                { !searchQuery.trim() && (
                  <div className="empty-state">
                    <span className="icon"><SearchIcon size={ 32 } /></span>
                    <p>Type to search contacts and messages</p>
                  </div>
                ) }
              </div>
            </TabErrorBoundary>
          ) }

          {/* REQUESTS TAB */ }
          { activeTab === 'requests' && (
            <TabErrorBoundary tabName="Requests">
              <div className="requests-tab">
                <div className="section">
                  <div className="section-header" style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                    <h3>Submit Requests (WhatsApp Flow)</h3>
                    <button className="refresh-btn" onClick={ async () => {
                      setRequestsLoading( true );
                      try { setSubmitRequests( await api.listSubmitRequests() ); } catch ( e ) { console.error( e ); }
                      finally { setRequestsLoading( false ); }
                    } } disabled={ requestsLoading }>
                      { requestsLoading ? '...' : <RefreshIcon size={ 16 } /> }
                    </button>
                  </div>

                  { submitRequests.length === 0 && !requestsLoading && (
                    <div className="empty-state">
                      <span className="icon"><DocumentIcon size={ 32 } /></span>
                      <p>No submit requests yet. Requests will appear here when users complete the WhatsApp Flow.</p>
                    </div>
                  ) }

                  { submitRequests.length === 0 && requestsLoading && (
                    <div style={ { display: 'flex', justifyContent: 'center', padding: '3rem 0' } }>
                      <Spinner size="lg" />
                    </div>
                  ) }

                  { submitRequests.length > 0 && (
                    <div className="table-wrapper" style={ { overflowX: 'auto' } }>
                      <table className="data-table" style={ { width: '100%', borderCollapse: 'collapse', fontSize: '13px' } }>
                        <thead>
                          <tr style={ { borderBottom: '2px solid var(--border)', textAlign: 'left' } }>
                            <th style={ { padding: '8px 12px' } }>Phone</th>
                            <th style={ { padding: '8px 12px' } }>Name</th>
                            <th style={ { padding: '8px 12px' } }>Request #</th>
                            <th style={ { padding: '8px 12px' } }>Invoice #</th>
                            <th style={ { padding: '8px 12px' } }>Payment Ref</th>
                            <th style={ { padding: '8px 12px' } }>Order ID</th>
                            <th style={ { padding: '8px 12px' } }>Subject</th>
                            <th style={ { padding: '8px 12px' } }>Description</th>
                            <th style={ { padding: '8px 12px' } }>Amount</th>
                            <th style={ { padding: '8px 12px' } }>Payment</th>
                            <th style={ { padding: '8px 12px' } }>Txn ID</th>
                            <th style={ { padding: '8px 12px' } }>Date</th>
                            <th style={ { padding: '8px 12px' } }>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          { submitRequests.map( req => (
                            <tr key={ req.id } style={ { borderBottom: '1px solid var(--border)' } }>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace' } }>{ req.phone }</td>
                              <td style={ { padding: '8px 12px' } }>{ req.senderName || '—' }</td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px', color: '#1a3a2a' } }>{ req.requestNumber || '—' }</td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px', color: '#1a3a2a' } }>{ req.invoiceNumber || '—' }</td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px', color: '#1a3a2a' } }>{ req.paymentReferenceId || '—' }</td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px' } }>{ req.orderId }</td>
                              <td style={ { padding: '8px 12px' } }>{ req.subject || '—' }</td>
                              <td style={ { padding: '8px 12px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } } title={ req.description }>{ req.description || '—' }</td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px' } }>
                                { req.paymentAmount ? `₹${( req.paymentAmount / 100 ).toFixed( 2 )}` : '—' }
                              </td>
                              <td style={ { padding: '8px 12px' } }>
                                <span style={ {
                                  padding: '2px 8px',
                                  borderRadius: '12px',
                                  fontSize: '11px',
                                  fontWeight: 600,
                                  background: req.paymentStatus === 'captured' ? '#f3f4f6' : req.paymentStatus === 'failed' ? '#f3f4f6' : '#f9fafb',
                                  color: req.paymentStatus === 'captured' ? '#0f2a1d' : req.paymentStatus === 'failed' ? '#6b7280' : '#0f2a1d',
                                } }>
                                  { req.paymentStatus === 'captured' ? '✓ Paid' : req.paymentStatus === 'failed' ? '✗ Failed' : '⏳ Pending' }
                                </span>
                              </td>
                              <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '11px', color: '#1a3a2a' } }>{ req.transactionId || '—' }</td>
                              <td style={ { padding: '8px 12px', fontSize: '12px', color: 'var(--text-secondary)' } }>
                                <div>{ req.createdAt ? new Date( req.createdAt * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) : '—' }</div>
                                <div style={ { display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap' } }>
                                  { req.isExpired && (
                                    <span style={ { padding: '1px 6px', borderRadius: 10, fontSize: 10, fontWeight: 600, background: '#f9fafb', color: '#0f2a1d' } }>Expired</span>
                                  ) }
                                  { typeof req.daysOld === 'number' && req.daysOld > 0 && (
                                    <span style={ { fontSize: 10, color: req.daysOld > 7 ? '#1a3a2a' : '#1a3a2a' } }>{ req.daysOld }d old</span>
                                  ) }
                                </div>
                              </td>
                              <td style={ { padding: '8px 12px' } }>
                                { req.paymentStatus !== 'captured' && req.invoiceId && (
                                  <button
                                    onClick={ () => handleResendPayment( req ) }
                                    disabled={ resendingPayment === req.id }
                                    style={ {
                                      padding: '4px 10px', fontSize: '11px', fontWeight: 600,
                                      border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer',
                                      background: resendingPayment === req.id ? '#f3f4f6' : '#fff',
                                      color: '#1a3a2a', whiteSpace: 'nowrap',
                                    } }
                                  >
                                    { resendingPayment === req.id ? '...' : 'Resend' }
                                  </button>
                                ) }
                              </td>
                            </tr>
                          ) ) }
                        </tbody>
                      </table>
                    </div>
                  ) }
                </div>

                {/* Flow Interaction Logs */ }
                <div className="section" style={ { marginTop: '2rem' } }>
                  <div className="section-header" style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                    <h3>Flow Interaction Logs</h3>
                    <button className="refresh-btn" onClick={ async () => {
                      setFlowLogsLoading( true );
                      try { setFlowLogs( await api.listFlowLogs() ); } catch ( e ) { console.error( e ); }
                      finally { setFlowLogsLoading( false ); }
                    } } disabled={ flowLogsLoading }>
                      { flowLogsLoading ? '...' : <RefreshIcon size={ 16 } /> }
                    </button>
                  </div>
                  <p style={ { color: '#888', fontSize: '0.85rem', marginBottom: '0.75rem' } }>
                    Every flow screen interaction is logged here — see who opened the flow, which screen they reached, and if they completed or abandoned.
                  </p>

                  { flowLogs.length === 0 && !flowLogsLoading && (
                    <div className="empty-state">
                      <span className="icon"><DocumentIcon size={ 32 } /></span>
                      <p>No flow logs yet. Logs appear when users interact with WhatsApp Flows.</p>
                    </div>
                  ) }

                  { flowLogs.length > 0 && (
                    <div className="table-wrapper" style={ { overflowX: 'auto' } }>
                      <table className="data-table" style={ { width: '100%', borderCollapse: 'collapse', fontSize: '13px' } }>
                        <thead>
                          <tr style={ { borderBottom: '2px solid var(--border)', textAlign: 'left' } }>
                            <th style={ { padding: '8px 12px' } }>Phone</th>
                            <th style={ { padding: '8px 12px' } }>Action</th>
                            <th style={ { padding: '8px 12px' } }>Screen</th>
                            <th style={ { padding: '8px 12px' } }>Order ID</th>
                            <th style={ { padding: '8px 12px' } }>Subject</th>
                            <th style={ { padding: '8px 12px' } }>Description</th>
                            <th style={ { padding: '8px 12px' } }>Data</th>
                            <th style={ { padding: '8px 12px' } }>Date</th>
                          </tr>
                        </thead>
                        <tbody>
                          { flowLogs.map( log => {
                            // Parse flowData JSON if available
                            let parsedData: Record<string, any> | null = null;
                            if ( log.flowData )
                            {
                              try { parsedData = JSON.parse( log.flowData ); } catch { }
                            }
                            const extraKeys = parsedData
                              ? Object.keys( parsedData ).filter( k => ![ 'order_id', 'subject', 'description', 'email' ].includes( k ) )
                              : [];
                            return (
                              <tr key={ log.id } style={ { borderBottom: '1px solid var(--border)' } }>
                                <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px' } }>{ log.phone || '—' }</td>
                                <td style={ { padding: '8px 12px' } }>
                                  <span style={ {
                                    padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 600,
                                    background: log.action === 'INIT' ? '#f3f4f6' : log.action === 'data_exchange' ? '#f3e8ff' : '#f1f5f9',
                                    color: log.action === 'INIT' ? '#1a3a2a' : log.action === 'data_exchange' ? '#6b21a8' : '#475569',
                                  } }>
                                    { log.action }
                                  </span>
                                </td>
                                <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px' } }>
                                  { log.screen || '—' }
                                </td>
                                <td style={ { padding: '8px 12px', fontFamily: 'monospace', fontSize: '12px' } }>
                                  { log.order_id || ( parsedData?.order_id ) || '—' }
                                </td>
                                <td style={ { padding: '8px 12px', fontSize: '12px' } }>
                                  { log.subject || ( parsedData?.subject ) || '—' }
                                </td>
                                <td style={ { padding: '8px 12px', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px' } } title={ log.description || parsedData?.description || '' }>
                                  { log.description || ( parsedData?.description ) || '—' }
                                </td>
                                <td style={ { padding: '8px 12px', fontSize: '11px', color: '#888' } }>
                                  { extraKeys.length > 0
                                    ? extraKeys.map( k => `${k}: ${parsedData![ k ]}` ).join( ', ' )
                                    : ( log.dataKeys?.join( ', ' ) || '—' ) }
                                </td>
                                <td style={ { padding: '8px 12px', fontSize: '12px', color: 'var(--text-secondary)' } }>
                                  { log.createdAt ? new Date( log.createdAt * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) : '—' }
                                </td>
                              </tr>
                            );
                          } ) }
                        </tbody>
                      </table>
                    </div>
                  ) }
                </div>
              </div>
            </TabErrorBoundary>
          ) }

          {/* APP BUILDER TAB */ }
          { activeTab === 'appbuilder' && (
            <TabErrorBoundary tabName="App Builder">
              <AppBuilderTab data={ { contacts, messages, billingData, apiConnected, apiLatency, lastRefresh, loading } } />
            </TabErrorBoundary>
          ) }

          {/* SYSTEM TAB */ }
          { activeTab === 'system' && (
            <TabErrorBoundary tabName="System">
              <SystemTab />
            </TabErrorBoundary>
          ) }
        </div>
      </div>

      {/* Billing table expand styles - other styles in Dashboard.css */ }
      <style jsx>{ `
        .billing-row.warning { background: #f9fafb; }
        .billing-row.paid { background: #f9fafb; }
        .expand-cell { width: 30px; }
        .expand-btn { width: 28px; height: 28px; border: 1px solid var(--notion-border, #e9e9e7); border-radius: 6px; background: var(--notion-bg, #fff); cursor: pointer; font-size: 16px; color: var(--notion-text-secondary, #787774); }
        .expand-btn:hover { background: var(--notion-bg-hover, #efefef); color: var(--notion-text, #37352f); }
        .resource-row { background: var(--notion-bg-secondary, #f7f6f3); }
        .resource-details { padding: 12px 0; font-size: 14px; }
        .resource-details div { margin: 6px 0; color: var(--notion-text-secondary, #787774); }
        .resource-details strong { color: var(--notion-text, #37352f); }
        .resource-details code { background: var(--notion-bg-hover, #efefef); padding: 4px 8px; border-radius: 4px; font-size: 13px; word-break: break-all; font-family: var(--font-mono, monospace); }
        .resource-list { margin-top: 12px; }
        .resource-list ul { margin: 8px 0 0 20px; padding: 0; }
        .resource-list li { margin: 4px 0; color: var(--notion-text-secondary, #787774); font-family: var(--font-mono, monospace); font-size: 13px; }
      `}</style>
    </Layout>
  );
};

export default Dashboard;
