import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { apiCall, authFetch, normalizeTimestamp } from '../core';
import { deleteMessage, listMessages } from './messaging';
import { deleteContact } from './contacts';

// ============================================================================
// AI AUTOMATION API
// ============================================================================

// Old AIConfig, getAIConfig(), updateAIConfig(), testAIResponse(), getAISuggestions() removed
// Use getBedrockAIConfig(), updateBedrockAIConfig(), testBedrockAIResponse() instead

// ============================================================================
// SYSTEM HEALTH API
// ============================================================================

export interface SystemHealth {
  whatsapp: { status: 'active' | 'warning' | 'error'; phoneNumbers: number | null; qualityRating: string };
  sms: { status: 'active' | 'warning' | 'error'; poolId: string };
  email: { status: 'active' | 'warning' | 'error'; verified: boolean | null };
  ai: {
    status: 'active' | 'warning' | 'error';
    kbId?: string;
    internalKbId?: string;
    internalAgentId?: string;
    internalAgentAlias?: string;
    externalKbId?: string;
    externalAgentId?: string;
    externalAgentAlias?: string;
  };
  dlq: { depth: number | null; oldestMessage?: string };
}

export async function getSystemHealth (): Promise<SystemHealth> {
  // Missing evidence stays unknown; a failed read cannot certify healthy services.
  const defaults: SystemHealth = {
    whatsapp: { status: 'warning', phoneNumbers: null, qualityRating: 'UNKNOWN' },
    sms: { status: 'warning', poolId: '' },
    email: { status: 'warning', verified: null },
    ai: { status: 'warning' },
    dlq: { depth: null },
  };

  try
  {
    // Fetch real data from existing endpoints in parallel
    const [ billingData, dlqData, wabaData ] = await Promise.all( [
      apiCall<any>( `${API_BASE}/billing?health=true&advisor=false` ).catch( () => null ),
      apiCall<any>( `${API_BASE}/dlq` ).catch( () => null ),
      apiCall<any>( `${API_BASE}/waba` ).catch( () => null ),
    ] );

    // DLQ depth
    if ( dlqData )
    {
      defaults.dlq.depth = Number.isInteger( dlqData.count ) && dlqData.count >= 0
        ? dlqData.count : Array.isArray( dlqData.messages ) ? dlqData.messages.length : null;
      if ( dlqData.messages?.length > 0 )
      {
        defaults.dlq.oldestMessage = dlqData.messages[ dlqData.messages.length - 1 ]?.lastAttemptAt
          ? new Date( dlqData.messages[ dlqData.messages.length - 1 ].lastAttemptAt * 1000 ).toISOString()
          : undefined;
      }
    }

    // AWS Health status from billing endpoint
    if ( billingData?.health )
    {
      const h = billingData.health;
      if ( h.status === 'issues' || h.openIssues > 0 )
      {
        defaults.whatsapp.status = 'warning';
      }
    }

    // WABA phone quality from waba endpoint
    if ( wabaData && Array.isArray( wabaData.wabas ) )
    {
      const phones = wabaData.wabas.flatMap( ( w: any ) =>
        Array.isArray( w.phoneNumbers ) ? w.phoneNumbers : [] );
      defaults.whatsapp.phoneNumbers = phones.length;
      const ratings = phones.map( ( phone: any ) => phone.qualityRating )
        .filter( ( rating: unknown ) => typeof rating === 'string' && rating.length > 0 );
      defaults.whatsapp.qualityRating = ratings.length === phones.length && ratings.length > 0
        ? [...new Set( ratings )].join( ', ' ) : 'UNKNOWN';
      if ( phones.length > 0 && ratings.every( ( rating: string ) => rating === 'GREEN' )
        && ratings.length === phones.length && !billingData?.health?.openIssues
        && billingData?.health?.status !== 'issues' )
      {
        defaults.whatsapp.status = 'active';
      }

    }
  } catch
  {
    // Return defaults on any error
  }

  return defaults;
}


// ============================================================================
// VOICE CALLS API
// ============================================================================

/** Provider categories exposed by current voice APIs. */
export type VoiceProviderRead = 'plivo' | 'aws';

/**
 * Providers that may be SELECTED for a new call. PSTN voice is Plivo; 'aws' is
 * the AWS End User Messaging voice (TTS/audio) path. No other provider is
 * expressible in the type system.
 */
export type VoiceProviderSelectable = 'plivo' | 'aws';

export interface VoiceCall {
  id: string;
  callId: string;
  contactId: string;
  phoneNumber: string;
  provider: VoiceProviderRead;
  callType: 'tts' | 'audio' | 'ivr';
  status: string;
  direction: 'INBOUND' | 'OUTBOUND';
  duration: number;
  recordingUrl?: string;
  createdAt: string;
  updatedAt: string;
}

// `MakeVoiceCallRequest` was declared here, as the body type for `makeVoiceCall`
// below. Both went on 2026-10-07: the function posted to `${API_BASE}/voice/call`
// and the live routes are GET and DELETE `/voice/calls`, PLURAL — there is no
// singular POST route to reach. Nothing in src/ called it. The read path either
// side of it (`listVoiceCalls`, `getVoiceCall`, `normalizeVoiceCall`) is live and
// stays.

export async function listVoiceCalls ( contactId?: string, provider?: string ): Promise<VoiceCall[]> {
  let url = `${API_BASE}/voice/calls`;
  const params = new URLSearchParams();
  if ( contactId ) params.append( 'contactId', contactId );
  if ( provider ) params.append( 'provider', provider );
  if ( params.toString() ) url += `?${params}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    const calls = Array.isArray( data ) ? data : ( data.calls || [] );
    return calls.map( normalizeVoiceCall );
  }
  return [];
}

export async function getVoiceCall ( callId: string ): Promise<VoiceCall | null> {
  const calls = await listVoiceCalls();
  return calls.find( call => call.callId === callId || call.id === callId ) || null;
}

function normalizeVoiceCall ( item: any ): VoiceCall {
  return {
    id: item.id || item.callId || '',
    callId: item.callId || item.id || '',
    contactId: item.contactId || '',
    phoneNumber: item.phoneNumber || '',
    provider: item.provider || 'aws',
    callType: item.callType || 'tts',
    status: item.status || 'unknown',
    direction: ( item.direction || 'OUTBOUND' ).toUpperCase() as 'INBOUND' | 'OUTBOUND',
    duration: item.duration || 0,
    recordingUrl: item.recordingUrl,
    createdAt: normalizeTimestamp( item.createdAt ) || new Date().toISOString(),
    updatedAt: normalizeTimestamp( item.updatedAt ) || new Date().toISOString(),
  };
}


// ============================================================================
// SMS AWS API (Pinpoint/SNS)
// ============================================================================

export interface SmsAwsMessage {
  messageId: string;
  contactId: string;
  phoneNumber: string;
  content: string;
  status: string;
  direction: string;
  messageType: string;
  senderId?: string;
  providerMessageId?: string;
  timestamp: number;
  createdAt: number;
}

export interface SendSmsAwsRequest {
  contactId?: string;
  phoneNumber?: string;
  content: string;
  messageType?: 'TRANSACTIONAL' | 'PROMOTIONAL';
  senderId?: string;
}

export async function listSmsAwsMessages ( contactId?: string, status?: string ): Promise<SmsAwsMessage[]> {
  let url = `${API_BASE}/sms-aws/messages`;
  const params = new URLSearchParams();
  if ( contactId ) params.append( 'contactId', contactId );
  if ( status ) params.append( 'status', status );
  if ( params.toString() ) url += `?${params}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return data.messages || [];
  }
  return [];
}

export async function sendSmsAws ( request: SendSmsAwsRequest ): Promise<{ messageId: string; status: string; providerMessageId?: string } | null> {
  return apiCall<{ messageId: string; status: string; providerMessageId?: string }>( `${API_BASE}/sms-aws/send`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}


// ============================================================================
// SMS SENDING
// ============================================================================
// There is no provider-specific SMS client function. SMS goes to POST /sms/send,
// which sends exclusively through AWS End User Messaging.

// ============================================================================
// SINCH RCS API (Conversation API)
// ============================================================================

export interface SendRcsRequest {
  phoneNumber: string;
  templateId?: string;
  text?: string;
  parameters?: Record<string, string>;
  language?: string;
  metadata?: string;
}

export async function sendRcs ( request: SendRcsRequest ): Promise<{ success: boolean; messageId?: string; channel?: string; error?: string } | null> {
  return apiCall<{ success: boolean; messageId?: string; channel?: string; error?: string }>( `${API_BASE}/rcs/send`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

export async function listRcsTemplates (): Promise<any[]> {
  const data = await apiCall<any>( `${API_BASE}/rcs/send`, {
    method: 'POST',
    body: JSON.stringify( { action: 'templates' } ),
  } );
  if ( !Array.isArray( data?.templates ) ) throw new Error( 'RCS templates unavailable' );
  return data.templates;
}

export async function createRcsTemplate ( name: string, text: string, type?: string, suggestions?: any[] ): Promise<any> {
  return apiCall<any>( `${API_BASE}/rcs/send`, {
    method: 'POST',
    body: JSON.stringify( { action: 'create_template', name, text, type: type || 'text_message', suggestions } ),
  } );
}

export async function listRcsMessages ( phoneNumber?: string, limit: number = 500 ): Promise<any[]> {
  const payload: any = { action: 'list', limit };
  if ( phoneNumber ) payload.phoneNumber = phoneNumber;
  const data = await apiCall<any>( `${API_BASE}/rcs/send`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
  return data?.messages || [];
}

export async function deleteRcsTemplate ( name: string ): Promise<any> {
  return apiCall<any>( `${API_BASE}/rcs/send`, {
    method: 'POST',
    body: JSON.stringify( { action: 'delete_template', name } ),
  } );
}


// ============================================================================
// VOICE AWS API (Connect/Polly)
// ============================================================================

export interface VoiceAwsCall {
  id: string;
  callId: string;
  contactId: string;
  phoneNumber: string;
  callType: 'tts' | 'audio';
  status: string;
  direction: string;
  duration: number;
  voiceId?: string;
  messageText?: string;
  connectContactId?: string;
  createdAt: number;
  updatedAt: number;
}

export interface MakeVoiceAwsCallRequest {
  contactId?: string;
  phoneNumber?: string;
  callType: 'tts' | 'audio';
  messageText?: string;
  voiceId?: string;
  audioUrl?: string;
}

export async function listVoiceAwsCalls ( contactId?: string, status?: string ): Promise<VoiceAwsCall[]> {
  let url = `${API_BASE}/voice-aws/calls`;
  const params = new URLSearchParams();
  if ( contactId ) params.append( 'contactId', contactId );
  if ( status ) params.append( 'status', status );
  if ( params.toString() ) url += `?${params}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return data.calls || [];
  }
  return [];
}

export async function makeVoiceAwsCall ( request: MakeVoiceAwsCallRequest ): Promise<{ callId: string; status: string; providerCallId?: string } | null> {
  return apiCall<{ callId: string; status: string; providerCallId?: string }>( `${API_BASE}/voice-aws/call`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}


// ============================================================================
// WHATSAPP VOICE (TTS via Polly + Audio Messages)
// ============================================================================

export interface WhatsAppVoiceLog {
  messageId: string;
  contactId: string;
  phoneNumber: string;
  messageText: string;
  voiceId: string;
  languageCode: string;
  audioSize: number;
  s3Key: string;
  whatsappMessageId: string;
  status: string;
  type: 'tts' | 'recording';
  createdAt: number;
}

export interface SendWhatsAppTTSRequest {
  contactId?: string;
  phoneNumber?: string;
  messageText: string;
  voiceId?: string;
  languageCode?: string;
  engine?: string;
  phoneNumberId?: string;
  recipientBsuid?: string;    // Send to BSUID recipient
}

export interface SendWhatsAppAudioRequest {
  contactId?: string;
  phoneNumber?: string;
  phoneNumberId?: string;
  s3Key?: string;
  audioBase64?: string;
  contentType?: string;
  recipientBsuid?: string;    // Send to BSUID recipient
}

export async function sendWhatsAppTTS ( request: SendWhatsAppTTSRequest ): Promise<{
  messageId: string; whatsappMessageId?: string; s3Key: string; audioSize: number; status: string;
} | null> {
  return apiCall<any>( `${API_BASE}/whatsapp-voice/tts`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

export async function sendWhatsAppAudioMessage ( request: SendWhatsAppAudioRequest ): Promise<{
  messageId: string; whatsappMessageId?: string; s3Key: string; status: string;
} | null> {
  return apiCall<any>( `${API_BASE}/whatsapp-voice/send`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

export async function listWhatsAppVoiceLogs (): Promise<WhatsAppVoiceLog[]> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp-voice/logs` );
  return data?.logs || [];
}

export async function getPollyVoices (): Promise<{
  voices: Record<string, { id: string; gender: string; engine: string }[]>;
  transcribeLanguages?: Record<string, string>;
}> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp-voice/voices` );
  return {
    voices: data?.voices || {},
    transcribeLanguages: data?.transcribeLanguages || {},
  };
}

// The on-demand voice-note transcription call and its result type were removed here.
// The live account exposes seven /whatsapp-voice/* routes — clear-logs, language-config
// (GET and PUT), logs, voices, send and tts — and no transcribe route, so the button that
// invoked this 404'd in both inboxes. A transcription that arrives from the backend on a
// message is still rendered; only the never-working on-demand trigger went.

// Voice language configuration
export interface VoiceLanguageConfig {
  autoTranscribe: boolean;
  enabledLanguages: string[];
  defaultVoices: Record<string, string>;
  autoReplyWithVoice: boolean;
  transcribeLanguages: string[];
}

export async function getVoiceLanguageConfig (): Promise<VoiceLanguageConfig | null> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp-voice/language-config` );
  return data?.config || null;
}

export async function updateVoiceLanguageConfig ( config: Partial<VoiceLanguageConfig> ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp-voice/language-config`, {
    method: 'PUT',
    body: JSON.stringify( { config } ),
  } );
  return data?.success === true;
}

// ============================================================================
// DLQ API
// ============================================================================

export interface DLQMessage {
  id: string;
  queueName: string;
  retryCount: number;
  lastAttemptAt: number;
  error: string;
}

export async function listDLQMessages (): Promise<DLQMessage[]> {
  const data = await apiCall<any>( `${API_BASE}/dlq` );
  if ( data )
  {
    return data.messages || [];
  }
  return [];
}

export async function replayDLQMessages ( queueName: string, batchSize?: number ): Promise<{ processed: number; succeeded: number; failed: number } | null> {
  return apiCall<{ processed: number; succeeded: number; failed: number }>( `${API_BASE}/dlq/replay`, {
    method: 'POST',
    body: JSON.stringify( { queueName, batchSize: batchSize || 10 } ),
  } );
}


// ============================================================================
// AWS BILLING API
// ============================================================================

export interface AWSServiceUsage {
  service: string;
  cost: number;
  usage: number;
  unit: string;
  freeLimit: string;
  status: 'free' | 'paid' | 'warning';
}

export interface CostRecommendation {
  id: string;
  severity: 'high' | 'medium' | 'low' | 'info';
  title: string;
  description: string;
  potentialSavings: number;
  action: string;
  link?: string;
}

export interface AWSHealthData {
  openIssues: number;
  scheduledChanges: number;
  otherNotifications: number;
  events: any[];
  scheduledEvents: any[];
  notifications: any[];
  lastChecked: string;
  status: 'healthy' | 'issues' | 'unknown';
  error?: string;
}

export interface TrustedAdvisorData {
  actionRecommended: number;
  investigationRecommended: number;
  noProblemsDetected: number;
  notAvailable: number;
  checks: any[];
  categories: Record<string, { ok: number; warning: number; error: number }>;
  lastChecked: string;
  error?: string;
}

export interface AWSBillingData {
  totalCost: number;
  period: string;
  services: AWSServiceUsage[];
  lastUpdated: string;
  accountId?: string;
  currency?: string;
  previousMonthCost?: number;
  previousMonthPeriod?: string;
  recommendations?: CostRecommendation[];
  health?: AWSHealthData;
  trustedAdvisor?: TrustedAdvisorData;
  // False when the backend cannot measure spend (Cost Explorer was removed on
  // 2026-09-28 because it bills per request). A zero totalCost then means "not
  // measured", not "spent nothing" -- the dashboard must not show it as a bill.
  costReportingEnabled?: boolean;
  // True when the billing call itself could not be answered, so nothing in this
  // payload is a measurement. Distinct from costReportingEnabled === false,
  // which means the backend answered and told us spend is not measured.
  unavailable?: boolean;
  note?: string;
}

// AWS Free Tier limits for reference
const FREE_TIER_LIMITS: Record<string, { limit: string; unit: string }> = {
  'AWS Lambda': { limit: '1M requests/month', unit: 'requests' },
  'Amazon DynamoDB': { limit: '25GB + 200M requests', unit: 'operations' },
  'Amazon S3': { limit: '5GB + 20K GET', unit: 'operations' },
  'Amazon API Gateway': { limit: '1M REST calls/month', unit: 'requests' },
  'Amazon CloudFront': { limit: '1TB transfer/month', unit: 'requests' },
  'AWS Amplify': { limit: '1000 build mins/month', unit: 'minutes' },
  'Amazon SNS': { limit: '1M publishes/month', unit: 'notifications' },
  'Amazon SQS': { limit: '1M requests/month', unit: 'requests' },
  'Amazon Cognito': { limit: '50K MAU', unit: 'users' },
  'AmazonCloudWatch': { limit: '10 metrics free', unit: 'metrics' },
  'Amazon Bedrock': { limit: '3-month trial', unit: 'requests' },
  'Amazon OpenSearch Service': { limit: 'Serverless free tier', unit: 'operations' },
  'Meta WhatsApp Cloud API': { limit: 'Pay per conversation', unit: 'conversations' },
  'Amazon Route 53': { limit: '$0.50/zone', unit: 'queries' },
  'AWS Certificate Manager': { limit: 'Free public certs', unit: 'certificates' },
  'AWS CloudFormation': { limit: 'Free', unit: 'stacks' },
  'AWS Secrets Manager': { limit: '$0.40/secret/month', unit: 'secrets' },
  'AWS Key Management Service': { limit: '20K free requests', unit: 'requests' },
  'AWS Glue': { limit: 'Pay per DPU-hour', unit: 'operations' },
  'AWS Step Functions': { limit: '4K free transitions', unit: 'transitions' },
  'Amazon Simple Email Service': { limit: '62K emails/month (from EC2)', unit: 'emails' },
  'Amazon Location Service': { limit: '10K requests/month', unit: 'requests' },
};

export async function getAWSBilling ( monthOffset: number = 0 ): Promise<AWSBillingData> {
  // Try to fetch from our billing API endpoint with month parameter
  const url = monthOffset === 0
    ? `${API_BASE}/billing`
    : `${API_BASE}/billing?month=${monthOffset}`;

  const data = await apiCall<any>( url );

  if ( data && Array.isArray( data.services ) )
  {
    return {
      totalCost: data.totalCost || 0,
      period: data.period || '',
      services: data.services,
      lastUpdated: data.lastUpdated || '',
      accountId: data.accountId,
      currency: data.currency || 'USD',
      previousMonthCost: data.previousMonthCost,
      previousMonthPeriod: data.previousMonthPeriod,
      recommendations: data.recommendations || [],
      health: data.health,
      trustedAdvisor: data.trustedAdvisor,
      // Absent means enabled, so a real bill renders exactly as before.
      costReportingEnabled: data.costReportingEnabled !== false,
      note: data.note,
    };
  }

  // A failed read supplies no evidence of spend, usage or measurement time.
  // Keep the numeric interface, but the dashboard must hide it behind these flags.
  return {
    totalCost: 0,
    period: '',
    services: [],
    lastUpdated: '',
    costReportingEnabled: false,
    unavailable: true,
    note: 'Billing data is unavailable. Check the connection or refresh to try again.',
  };
}


// ============================================================================
// ADVANCED DELETE OPERATIONS
// ============================================================================

/**
 * Why a hard delete can be REFUSED, and what the caller must do about it.
 *
 * `CONTACT_HAS_PAYMENTS`      the contact is tied to a captured invoice or to an order, so the
 *                             row is the provenance record for that money. Archive instead.
 * `PAYMENT_LINKAGE_UNKNOWN`   the server could not read one of the two indexes. It refuses
 *                             rather than guessing, because "cannot determine" is not "no
 *                             payments". Retrying later is reasonable; archiving is safe now.
 * `ERROR`                     anything else: a 404, a network failure, a 500.
 */
export type HardDeleteRefusalCode = 'CONTACT_HAS_PAYMENTS' | 'PAYMENT_LINKAGE_UNKNOWN' | 'CONTACT_LOCKED' | 'ERROR';

export type HardDeleteResult =
  | { ok: true; messagesDeleted: number; mediaDeleted: number }
  | { ok: false; code: HardDeleteRefusalCode; reason?: string; archiveInstead: boolean };

/**
 * Hard Delete - permanently removes a contact, all its messages, and its media from S3.
 * Irreversible, and the server may now refuse it.
 *
 * THE FALLBACK THAT USED TO BE HERE IS DELETED, DELIBERATELY. On a falsy `success` this
 * function called `deleteContactMessages` and then `deleteContact` - so a SERVER REFUSAL
 * destroyed the paid contact's entire message history and soft-deleted the row anyway, which
 * is the exact opposite of what the refusal is for. The guard it defeats is in
 * `core/contacts._hard_delete_refusal`.
 *
 * Returns a discriminated result rather than a boolean, because "refused because this
 * customer has paid" and "the request failed" need different words in front of an operator.
 *
 * Uses `authFetch` rather than `apiCall` on purpose: `apiCall` collapses a non-2xx to `null`
 * and the refusal CODE lives in the 409 body, which is the one thing this caller needs.
 */
export async function hardDeleteContact ( contactId: string ): Promise<HardDeleteResult> {
  let response: Response;
  try
  {
    response = await authFetch( `${API_BASE}/contacts/${contactId}?hard=true`, {
      method: 'DELETE',
    } );
  } catch ( error )
  {
    console.error( 'Hard delete request failed:', error );
    return { ok: false, code: 'ERROR', archiveInstead: false };
  }

  let data: any = null;
  try { data = await response.json(); } catch { data = null; }

  if ( response.ok && data && data.success )
  {
    return {
      ok: true,
      messagesDeleted: Number( data.messagesDeleted ) || 0,
      mediaDeleted: Number( data.mediaDeleted ) || 0,
    };
  }

  const serverCode = typeof data?.error === 'string' ? data.error : '';
  const code: HardDeleteRefusalCode =
    serverCode === 'CONTACT_HAS_PAYMENTS' || serverCode === 'PAYMENT_LINKAGE_UNKNOWN' || serverCode === 'CONTACT_LOCKED'
      ? serverCode
      : 'ERROR';

  return {
    ok: false,
    code,
    reason: typeof data?.reason === 'string' ? data.reason : undefined,
    archiveInstead: data?.archiveInstead === true,
  };
}

/**
 * Delete all messages for a contact (keeps the contact)
 * Deletes messages one by one since there's no bulk endpoint
 */
export async function deleteContactMessages ( contactId: string ): Promise<boolean> {
  try
  {
    // Fetch all messages for this contact
    const messages = await listMessages( contactId );

    if ( messages.length === 0 )
    {
      return true; // No messages to delete
    }

    let deleted = 0;
    let failed = 0;

    for ( const msg of messages )
    {
      const result = await deleteMessage( msg.id, msg.direction );
      if ( result )
      {
        deleted++;
      } else
      {
        failed++;
      }
    }

    return deleted > 0 || messages.length === 0;
  } catch ( error )
  {
    console.error( 'Delete contact messages error:', error );
    return false;
  }
}

/**
 * Bulk delete multiple messages
 */
export async function bulkDeleteMessages ( messageIds: string[], direction: 'INBOUND' | 'OUTBOUND' = 'INBOUND' ): Promise<{ deleted: number; failed: number }> {
  let deleted = 0;
  let failed = 0;

  for ( const msgId of messageIds )
  {
    const result = await deleteMessage( msgId, direction );
    if ( result )
    {
      deleted++;
    } else
    {
      failed++;
    }
  }

  return { deleted, failed };
}

/**
 * Bulk delete multiple contacts
 */
export async function bulkDeleteContacts ( contactIds: string[] ): Promise<{ deleted: number; failed: number }> {
  let deleted = 0;
  let failed = 0;

  for ( const contactId of contactIds )
  {
    const result = await deleteContact( contactId );
    if ( result )
    {
      deleted++;
    } else
    {
      failed++;
    }
  }

  return { deleted, failed };
}


