import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { apiCall, authFetch, normalizeTimestamp } from '../core';
import { deleteMessage, listMessages } from './messaging';
import { deleteContact } from './contacts';




// ============================================================================
// VOICE CALLS API
// ============================================================================

/** Provider categories exposed by current voice APIs. */
type VoiceProviderRead = 'plivo' | 'aws';


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

interface SmsAwsMessage {
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

interface SendSmsAwsRequest {
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

interface SendRcsRequest {
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




// ============================================================================
// VOICE AWS API (Connect/Polly)
// ============================================================================

interface VoiceAwsCall {
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

interface MakeVoiceAwsCallRequest {
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



interface SendWhatsAppTTSRequest {
  contactId?: string;
  phoneNumber?: string;
  messageText: string;
  voiceId?: string;
  languageCode?: string;
  engine?: string;
  phoneNumberId?: string;
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




// ============================================================================
// AWS BILLING API
// ============================================================================

interface AWSServiceUsage {
  service: string;
  cost: number;
  usage: number;
  unit: string;
  freeLimit: string;
  status: 'free' | 'paid' | 'warning';
}

interface CostRecommendation {
  id: string;
  severity: 'high' | 'medium' | 'low' | 'info';
  title: string;
  description: string;
  potentialSavings: number;
  action: string;
  link?: string;
}

interface AWSHealthData {
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

interface TrustedAdvisorData {
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
type HardDeleteRefusalCode = 'CONTACT_HAS_PAYMENTS' | 'PAYMENT_LINKAGE_UNKNOWN' | 'CONTACT_LOCKED' | 'ERROR';

type HardDeleteResult =
  | { ok: true; messagesDeleted: number; mediaDeleted: number }
  | { ok: false; code: HardDeleteRefusalCode; reason?: string; archiveInstead: boolean };

/**
 * Legacy hard-delete wrapper. The server refuses hard deletion because a full,
 * version-aware cross-service erasure coordinator has not been deployed.
 * This function must never be used to claim that a customer's data was wiped.
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


