import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { validateWaMediaSize } from '../../lib/wa-media';
import { apiCall, apiCallResult, authFetch, normalizeTimestamp } from '../core';

// ============================================================================
// MESSAGES API
// ============================================================================

// A shared WhatsApp contact card, as sanitised at ingest by the inbound handler.
// Every field is optional because the extractor emits only what Meta actually sent.
export interface WaContactCard {
  name?: { formatted_name?: string; first_name?: string; last_name?: string };
  phones?: { phone?: string; type?: string; wa_id?: string }[];
  emails?: { email?: string; type?: string }[];
  org?: { company?: string; title?: string };
}
export interface Message {
  id: string;
  messageId: string;
  contactId: string;
  // VOICE is a real stored channel — message_store.VALID_CHANNELS has included it
  // since calls started leaving a breadcrumb row, and `/workspace/engage/inbox?channel=voice` is
  // now the Calls destination. Omitting it here made the type assert something false
  // about data the inbox already renders with its own badge and audio player.
  channel: 'WHATSAPP' | 'SMS' | 'EMAIL' | 'RCS' | 'VOICE';
  direction: 'INBOUND' | 'OUTBOUND';
  content: string;
  timestamp: string;
  status: string;
  errorDetails?: string;
  errorCode?: number;
  whatsappMessageId?: string;
  mediaId?: string;
  s3Key?: string;
  mediaUrl?: string;
  messageType?: string;
  templateName?: string;
  senderPhone?: string;
  senderName?: string;
  senderBsuid?: string;
  senderUsername?: string;
  receivingPhone?: string;
  awsPhoneNumberId?: string;
  transcription?: string;       // English transcription of voice notes
  detectedLanguage?: string;    // Detected language of voice note (e.g. "hi-IN")
  contactsPayload?: WaContactCard[] | null;  // shared contact card(s), messageType=contacts
  // Revoke ("delete for everyone") — written by inbound-whatsapp-handler._apply_revoke.
  // The content is never deleted or redacted; isRevoked is what the inbox renders.
  isRevoked?: boolean;
  revokedAt?: number;
  revokedByWhatsappMessageId?: string;
  // 'exact' | 'inferred' — an inferred match is a timing guess and MUST be labelled
  // as one in the UI. Present on the target row and on the revoke row itself.
  revokeResolution?: string;
  // Set on the REVOKE's own row, pointing at the message it deleted. Its presence is
  // what stops the revoke rendering as a second, standalone bubble.
  revokesMessageId?: string;
  // Call breadcrumb fields (channel=voice, messageType=call)
  callId?: string;
  callType?: string;            // current voice implementation/category
  duration?: number;            // seconds
  recordingUrl?: string;
  flowCode?: string;
  flowType?: string;
  flowScreen?: string;
  flowSubmissionId?: string;
  flowReference?: string;
  flowAnswers?: { question: string; answer: string }[];
  flowAttachments?: { key?: string; url?: string; type?: string; filename?: string }[];
  reviewId?: string;
  reviewStatus?: string;
  reviewRating?: number;
  reviewCategory?: string;
  reviewOrderId?: string;
}

export async function listMessages ( contactId?: string, channel?: string, limit: number = 1000 ): Promise<Message[]> {
  let url = `${API_BASE}/messages`;
  const params = new URLSearchParams();
  if ( contactId ) params.append( 'contactId', contactId );
  if ( channel ) params.append( 'channel', channel );
  params.append( 'limit', String( limit ) );
  if ( params.toString() ) url += `?${params}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    const messages = Array.isArray( data ) ? data : ( data.messages || [] );
    return messages.map( normalizeMessage );
  }
  return [];
}

export async function getMessage ( messageId: string ): Promise<Message | null> {
  const data = await apiCall<any>( `${API_BASE}/messages/${messageId}` );
  if ( data )
  {
    const msg = data.message || data;
    return msg && ( msg.id || msg.messageId ) ? normalizeMessage( msg ) : null;
  }
  return null;
}

export async function deleteMessage ( messageId: string, direction: 'INBOUND' | 'OUTBOUND' = 'INBOUND' ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/messages/${messageId}?direction=${direction}`, {
    method: 'DELETE',
  } );
  // Accept success if we got a response (even if success field is missing)
  return data !== null && ( data.success === true || data.messageId === messageId || !data.error );
}

export async function updateMessage ( messageId: string, updates: Record<string, any> ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/messages/${messageId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return data !== null && data.success === true;
}

/**
 * Staff-only Contribute native payment request. This is deliberately NOT
 * apiCallResult: that helper retries 502/503 and network errors, which would
 * duplicate a money-related Meta send after an ambiguous response.
 *
 * Exactly one POST per staff confirmation. The server re-prices ProductsTable,
 * verifies the owned WhatsApp identity and requires an Admin/MFA session.
 * Caller supplies only a saved Contact id, NEVER an amount or template.
 */
export type StaffContributeSendResult =
  | { state: 'ACCEPTED'; paymentAttemptId: string; amountPaise: 30000 }
  | { state: 'UNCONFIRMED'; code: string; message: string }
  | { state: 'REFUSED'; code: string; message: string };

/**
 * Read-only Admin capability check. The backend defaults OFF; a successful
 * website build alone must never enable a real customer payment request.
 * No retries, no payment or WhatsApp side effects.
 */
export type StaffContributionSendReadiness = {
  sendEnabled: boolean;
  amountPaise: number;
  reason: string;
};
export async function getStaffContributionSendReadiness (): Promise<StaffContributionSendReadiness> {
  const blocked = (reason: string): StaffContributionSendReadiness =>
    ({ sendEnabled: false, amountPaise: 0, reason });
  try {
    const response = await authFetch(`${API_BASE}/ecommerce/checkout`, {
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ action: 'staff-contribute-readiness' }),
    });
    const raw: unknown = await response.json().catch(() => null);
    const row = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    if (response.ok && row.status === 'STAFF_CONTRIBUTE_READY'
        && row.sendEnabled === true && row.amountPaise === 30000
        && row.currency === 'INR' && row.reason === 'READY') {
      return { sendEnabled: true, amountPaise: 30000, reason: 'READY' };
    }
    return blocked(typeof row.reason === 'string' ? row.reason : 'BACKEND_NOT_RELEASED');
  } catch {
    return blocked('BACKEND_UNAVAILABLE');
  }
}

export type StaffItemServiceSendResult =
  | {state:'ACCEPTED';paymentAttemptId:string;amountPaise:number}
  | {state:'REFUSED'|'UNCONFIRMED';code:string;message:string};
export async function sendStaffItemServicePaymentOnce(input:{contactId:string;itemId:string;selectedOrderNumber:string;expectedTotalPaise:number}):Promise<StaffItemServiceSendResult> {
  try {
    // One explicit staff send, never the retrying apiCallResult transport.
    const response=await authFetch(`${API_BASE}/ecommerce/checkout`,{method:'POST',cache:'no-store',body:JSON.stringify({action:'staff-item-service-send',...input})});
    const data=await response.json().catch(()=>({})) as Record<string,unknown>;
    if(response.ok&&data.status==='PAYMENT_REQUEST_SENT'&&data.currency==='INR'&&data.amountPaise===input.expectedTotalPaise&&typeof data.paymentAttemptId==='string')
      return {state:'ACCEPTED',paymentAttemptId:data.paymentAttemptId,amountPaise:input.expectedTotalPaise};
    const code=typeof data.error==='string'?data.error:'SEND_NOT_CONFIRMED';
    const message=typeof data.message==='string'?data.message:`Request not sent: ${code}. Check the customer, paid order and current quote.`;
    return {state:response.status>=500||data.sendUnconfirmed===true||(response.ok&&data.status==='PAYMENT_REQUEST_SENT')?'UNCONFIRMED':'REFUSED',code,message};
  }catch{return {state:'UNCONFIRMED',code:'NETWORK_UNCONFIRMED',message:'The send outcome is unknown. Check WhatsApp and payment records before retrying.'};}
}

export async function sendStaffContributionPaymentOnce (
  contactId: string,
): Promise<StaffContributeSendResult> {
  if (typeof contactId !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(contactId))
    return { state: 'REFUSED', code: 'CONTACT_INVALID', message: 'Choose a saved customer.' };

  try {
    // A fetch, NOT apiCallResult, so even a timeout/502 is never replayed.
    const response = await authFetch( `${API_BASE}/ecommerce/checkout`, {
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ action: 'staff-contribute-send', contactId }),
    } );
    const raw: unknown = await response.json().catch(() => null);
    const data = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    if (response.ok && data.status === 'PAYMENT_REQUEST_SENT'
        && data.currency === 'INR' && data.amountPaise === 30000
        && typeof data.paymentAttemptId === 'string' && data.paymentAttemptId) {
      return {
        state: 'ACCEPTED', amountPaise: 30000,
        paymentAttemptId: data.paymentAttemptId,
      };
    }
    const code = typeof data.error === 'string' ? data.error : 'SEND_RESPONSE_NOT_CONFIRMED';
    const message = typeof data.message === 'string'
      ? data.message.slice(0, 200) : 'Check the payment ledger and WhatsApp before retrying.';
    if (response.status >= 500 || data.sendUnconfirmed === true || (response.ok && data.status === 'PAYMENT_REQUEST_SENT'))
      return { state: 'UNCONFIRMED', code, message };
    return { state: 'REFUSED', code, message };
  } catch {
    // A network failure might happen AFTER Meta accepted the payment request.
    return {
      state: 'UNCONFIRMED',
      code: 'NETWORK_UNCONFIRMED',
      message: 'The result could not be confirmed. Check WhatsApp and the payment ledger before retrying.',
    };
  }
}

// createInvoice() removed — use createInvoiceEngine() instead

function normalizeMessage ( item: any ): Message {
  const timestamp = item.timestamp || item.createdAt;
  return {
    id: item.id || item.messageId || '',
    messageId: item.messageId || item.id || '',
    contactId: item.contactId || '',
    channel: ( item.channel || 'WHATSAPP' ).toUpperCase() as Message[ 'channel' ],
    direction: ( item.direction || 'INBOUND' ).toUpperCase() as 'INBOUND' | 'OUTBOUND',
    content: item.content || item.text || '',
    timestamp: normalizeTimestamp( timestamp ) || new Date().toISOString(),
    status: item.status || 'received',
    errorDetails: item.errorDetails,
    errorCode: typeof item.errorCode === 'number' ? item.errorCode : ( item.errorCode ? Number( item.errorCode ) : undefined ),
    whatsappMessageId: item.whatsappMessageId,
    mediaId: item.mediaId,
    s3Key: item.s3Key,
    mediaUrl: item.mediaUrl,  // Use pre-signed URL from API
    messageType: item.messageType,  // image, video, audio, document, text
    templateName: item.templateName, // approved WhatsApp template associated with outbound send
    senderPhone: item.senderPhone,
    senderName: item.senderName,
    senderBsuid: item.senderBsuid,
    senderUsername: item.senderUsername,
    receivingPhone: item.receivingPhone,
    awsPhoneNumberId: item.awsPhoneNumberId,
    transcription: item.transcription,
    detectedLanguage: item.detectedLanguage,
    // This object is built by enumeration, so an omitted field is dropped before
    // any UI sees it — the contact card cannot render without this line.
    contactsPayload: Array.isArray( item.contactsPayload ) ? item.contactsPayload : undefined,
    // Same enumeration rule as contactsPayload above: without these four lines the
    // revoke fields are dropped before any UI can read them.
    isRevoked: item.isRevoked === true,
    revokedAt: typeof item.revokedAt === 'number' ? item.revokedAt : ( item.revokedAt ? Number( item.revokedAt ) : undefined ),
    revokedByWhatsappMessageId: item.revokedByWhatsappMessageId,
    revokeResolution: item.revokeResolution,
    revokesMessageId: item.revokesMessageId,
    callId: item.callId,
    callType: item.callType,
    duration: typeof item.duration === 'number' ? item.duration : ( item.duration ? Number( item.duration ) : undefined ),
    recordingUrl: item.recordingUrl,
    flowCode: item.flowCode,
    flowType: item.flowType,
    flowScreen: item.flowScreen,
    flowSubmissionId: item.flowSubmissionId,
    flowReference: item.flowReference,
    flowAnswers: Array.isArray( item.flowAnswers ) ? item.flowAnswers : undefined,
    flowAttachments: Array.isArray( item.flowAttachments ) ? item.flowAttachments : undefined,
    reviewId: item.reviewId,
    reviewStatus: item.reviewStatus,
    reviewRating: typeof item.reviewRating === 'number' ? item.reviewRating : ( item.reviewRating ? Number( item.reviewRating ) : undefined ),
    reviewCategory: item.reviewCategory,
    reviewOrderId: item.reviewOrderId,
  };
}

// Send WhatsApp message via Lambda
export interface SendMessageRequest {
  contactId: string;
  content?: string;
  phoneNumberId?: string;
  recipientBsuid?: string; // Send to BSUID instead of phone number
  isTemplate?: boolean;
  templateName?: string;
  templateParams?: string[];
  mediaFile?: string;
  mediaType?: string;
  mediaFileName?: string; // Real filename for documents
  isOtpTemplate?: boolean;
  otpCode?: string;
  otpButtonType?: string;
  contextMessageId?: string;  // Native reply — quote this WhatsApp message id
}

// Send WhatsApp reaction via Lambda
export interface SendReactionRequest {
  contactId: string;
  reactionMessageId: string;  // WhatsApp message ID to react to
  reactionEmoji?: string;     // Default: thumbs up
  phoneNumberId?: string;
  recipientBsuid?: string;    // Send reaction to BSUID recipient
}

/**
 * Request a presigned S3 PUT URL for direct browser→S3 media upload.
 * Avoids the API Gateway (10MB) / Lambda (6MB) base64 payload ceiling so that
 * large media (video/audio 16MB, documents up to 100MB) can be sent.
 */
export async function getMediaUploadUrl ( mediaType: string, filename: string, opts?: { reuse?: boolean } ): Promise<{ uploadMethod?: 'PUT' | 'POST'; uploadUrl: string; fields?: Record<string, string>; s3Key: string; contentType: string; publicUrl?: string; maxSize?: number } | null> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( { action: 'getUploadUrl', mediaType, filename, reuse: opts?.reuse || undefined } ),
  } );
  if ( !data?.uploadUrl || !data?.s3Key ) return null;
  return {
    uploadMethod: data.uploadMethod || 'PUT',
    uploadUrl: data.uploadUrl,
    fields: data.fields || undefined,
    s3Key: data.s3Key,
    contentType: data.contentType,
    publicUrl: data.publicUrl || undefined,
    maxSize: data.maxSize || undefined,
  };
}

/** Upload a File/Blob to S3 via a presigned POST (form fields + file). Returns true on success.
 *  Presigned POST supports a content-length-range condition so S3 itself rejects oversize files. */
export async function uploadFileViaPresignedPost ( url: string, fields: Record<string, string>, file: File | Blob ): Promise<boolean> {
  try
  {
    const form = new FormData();
    Object.entries( fields ).forEach( ( [ k, v ] ) => form.append( k, v ) );
    form.append( 'file', file );  // 'file' must be the LAST field per S3 POST policy
    const res = await fetch( url, { method: 'POST', body: form } );
    return res.ok;  // S3 returns 204 No Content on success
  } catch ( err )
  {
    console.error( 'S3 POST upload error:', err );
    return false;
  }
}

/** Upload a File/Blob directly to S3 via a presigned PUT URL. Returns true on success. */
export async function uploadFileToS3 ( uploadUrl: string, file: File | Blob, contentType: string ): Promise<boolean> {
  try
  {
    const res = await fetch( uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': contentType },
      body: file,
    } );
    return res.ok;
  } catch ( err )
  {
    console.error( 'S3 upload error:', err );
    return false;
  }
}

/**
 * Upload media to S3 (presigned) then return the S3 key to pass as `mediaFile` to
 * sendWhatsAppMessage. The backend's _upload_media auto-detects S3 keys by prefix.
 */
export async function uploadMediaForSend ( file: File | Blob, mediaType: string, filename: string ): Promise<string | null> {
  const presign = await getMediaUploadUrl( mediaType, filename );
  if ( !presign ) return null;
  const ok = await uploadFileToS3( presign.uploadUrl, file, presign.contentType );
  return ok ? presign.s3Key : null;
}

/**
 * Meta WhatsApp Cloud API media size limits and category classifier live in
 * src/lib/wa-media.ts (single source of truth). Re-exported here for callers that
 * import from the api client.
 */
export { WA_MEDIA_LIMITS, waMediaCategory } from '../../lib/wa-media';

/**
 * Upload a template-header attachment to the REUSABLE public folder (wa-tpl/) and
 * return a stable public CDN URL. Uses a presigned PUT so large files (docs up to
 * 100MB, video/audio 16MB) bypass the API Gateway/Lambda payload ceiling.
 *
 * Enforces Meta's per-type size limits client-side first (the presigned PUT goes
 * straight to S3, so the server can't reject an oversize file). Throws an Error
 * with a human-readable message if the file is too large for its type.
 *
 * Why this over uploadMediaForSend for template headers:
 *  - WhatsApp fetches the public URL directly, so EVERY attachment type sends with
 *    its correct content type (PDF, DOCX, XLSX, PPTX, TXT, PNG, JPEG, MP4, 3GP...),
 *    avoiding the "document always treated as application/pdf" mismatch.
 *  - The returned URL is stable and reusable — the same attachment can be sent
 *    across many template messages without re-uploading to Meta each time.
 */
export async function uploadReusableHeaderMedia ( file: File | Blob, mediaType: string, filename: string ): Promise<string | null> {
  const check = validateWaMediaSize( { size: file.size, type: mediaType, name: filename }, mediaType );
  if ( !check.ok )
  {
    throw new Error( check.message );
  }
  const presign = await getMediaUploadUrl( mediaType, filename, { reuse: true } );
  if ( !presign ) return null;
  // Reuse uploads come back as a presigned POST (server enforces the size limit
  // via a content-length-range condition). Fall back to PUT if POST isn't returned.
  let ok: boolean;
  if ( presign.uploadMethod === 'POST' && presign.fields )
  {
    ok = await uploadFileViaPresignedPost( presign.uploadUrl, presign.fields, file );
  } else
  {
    ok = await uploadFileToS3( presign.uploadUrl, file, presign.contentType );
  }
  return ok ? ( presign.publicUrl || null ) : null;
}

export async function sendWhatsAppMessage ( request: SendMessageRequest ): Promise<{ messageId: string; status: string } | null> {
  // (POST /{PHONE_NUMBER_ID}/messages with status:"read" + typing_indicator object)
  // The read receipt approach is used as a proxy for typing indicators.

  // Ensure mediaFile is properly formatted
  const payload = {
    ...request,
    // If mediaFile is provided, ensure it's base64 encoded
    mediaFile: request.mediaFile ? ( typeof request.mediaFile === 'string' ? request.mediaFile : request.mediaFile ) : undefined,
  };

  return apiCall<{ messageId: string; status: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

/**
 * Block / unblock / list blocked WhatsApp users (Meta block_users API).
 * Only users who messaged in the last 24h can be blocked (Meta rule).
 */
export async function blockWhatsAppUser ( request: { contactId?: string; phoneNumber?: string; phoneNumberId?: string } ): Promise<{ success: boolean; result?: any } | null> {
  return apiCall<{ success: boolean; result?: any }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( { blockAction: 'block', contactId: request.contactId, recipientPhone: request.phoneNumber, blockUsers: request.phoneNumber ? [ request.phoneNumber ] : undefined, phoneNumberId: request.phoneNumberId } ),
  } );
}

export async function unblockWhatsAppUser ( request: { contactId?: string; phoneNumber?: string; phoneNumberId?: string } ): Promise<{ success: boolean; result?: any } | null> {
  return apiCall<{ success: boolean; result?: any }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( { blockAction: 'unblock', contactId: request.contactId, recipientPhone: request.phoneNumber, blockUsers: request.phoneNumber ? [ request.phoneNumber ] : undefined, phoneNumberId: request.phoneNumberId } ),
  } );
}

export async function listBlockedWhatsAppUsers ( request: { contactId?: string; phoneNumberId?: string } ): Promise<{ success: boolean; result?: any } | null> {
  return apiCall<{ success: boolean; result?: any }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( { blockAction: 'list', contactId: request.contactId, phoneNumberId: request.phoneNumberId } ),
  } );
}

// Send a reaction to a WhatsApp message
export async function sendWhatsAppReaction ( request: SendReactionRequest ): Promise<{ messageId: string; status: string; emoji: string } | null> {
  return apiCall<{ messageId: string; status: string; emoji: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( {
      contactId: request.contactId,
      isReaction: true,
      reactionMessageId: request.reactionMessageId,
      reactionEmoji: request.reactionEmoji || '\uD83D\uDC4D',  // Default: thumbs up
      phoneNumberId: request.phoneNumberId,
      recipientBsuid: request.recipientBsuid,
    } ),
  } );
}

/**
 * Send a native WhatsApp typing indicator + read receipt.
 * Meta requires the WAMID of the customer's most recent inbound message.
 * Shows a typing bubble for up to 25s (or until a message is sent).
 */
export async function sendTypingIndicator ( phoneNumberId: string, messageId: string ): Promise<boolean> {
  if ( !messageId ) return false;
  try
  {
    const data = await apiCall<any>( `${API_BASE}/whatsapp/send`, {
      method: 'POST',
      body: JSON.stringify( { isTypingIndicator: true, phoneNumberId, messageId } ),
    } );
    return data?.success === true;
  } catch
  {
    return false;
  }
}

// ============================================================================
// CAROUSEL TEMPLATE API
// ============================================================================

export interface CarouselCardButton {
  type: 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER';
  text: string;
  url?: string;
  phoneNumber?: string;
}

export interface CarouselCard {
  headerHandle?: string;  // From uploadCarouselCardMedia
  headerType?: 'image' | 'video';
  bodyText: string;
  buttons?: CarouselCardButton[];
}

export interface CreateCarouselTemplateRequest {
  name: string;
  language?: string;
  category?: 'MARKETING' | 'UTILITY';
  bodyText: string;
  cards: CarouselCard[];
  wabaId?: string;
}

// Upload media for carousel card header
export async function uploadCarouselCardMedia (
  mediaBase64: string,
  contentType: string = 'image/jpeg',
  cardIndex: number = 0,
  wabaId?: string
): Promise<{ headerHandle: string; s3Key: string; cardIndex: number } | null> {
  const params = new URLSearchParams();
  if ( wabaId ) params.append( 'wabaId', wabaId );

  return apiCall<{ headerHandle: string; s3Key: string; cardIndex: number }>(
    `${API_BASE}/whatsapp/templates/carousel-media${params.toString() ? '?' + params : ''}`,
    {
      method: 'POST',
      body: JSON.stringify( { mediaBase64, contentType, cardIndex } ),
    }
  );
}

// Create carousel template
export async function createCarouselTemplate (
  request: CreateCarouselTemplateRequest
): Promise<{ metaTemplateId: string; templateStatus: string; templateType: string; cardCount: number } | null> {
  const params = new URLSearchParams();
  if ( request.wabaId ) params.append( 'wabaId', request.wabaId );

  return apiCall<{ metaTemplateId: string; templateStatus: string; templateType: string; cardCount: number }>(
    `${API_BASE}/whatsapp/templates/carousel${params.toString() ? '?' + params : ''}`,
    {
      method: 'POST',
      body: JSON.stringify( {
        name: request.name,
        language: request.language || 'en',
        category: request.category || 'MARKETING',
        bodyText: request.bodyText,
        cards: request.cards,
      } ),
    }
  );
}

// sendSmsMessage() removed — use sendSmsAws() instead

export async function sendEmailMessage ( contactId: string, subject: string, content: string, htmlContent?: string ): Promise<{ messageId: string; status: string } | null> {
  return apiCall<{ messageId: string; status: string }>( `${API_BASE}/email/send`, {
    method: 'POST',
    body: JSON.stringify( { contactId, subject, content, htmlContent } ),
  } );
}

// ============================================================================
// BULK JOBS API
// ============================================================================

export interface BulkJob {
  id: string;
  jobId: string;
  createdBy: string;
  channel: 'WHATSAPP' | 'SMS' | 'EMAIL';
  totalRecipients: number;
  sentCount: number;
  failedCount: number;
  status: 'PENDING' | 'IN_PROGRESS' | 'PAUSED' | 'COMPLETED' | 'CANCELLED' | 'FAILED';
  createdAt: string;
  updatedAt: string;
}

export async function listBulkJobs ( channel?: string ): Promise<BulkJob[]> {
  let url = `${API_BASE}/bulk/jobs`;
  if ( channel ) url += `?channel=${channel}`;
  const data = await apiCall<any>( url );
  if ( data )
  {
    return Array.isArray( data ) ? data : ( data.jobs || [] );
  }
  return [];
}

export async function createBulkJob ( job: Partial<BulkJob> ): Promise<BulkJob | null> {
  return apiCall<BulkJob>( `${API_BASE}/bulk/jobs`, {
    method: 'POST',
    body: JSON.stringify( job ),
  } );
}

export async function updateBulkJobStatus ( jobId: string, status: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/bulk/jobs/${jobId}`, {
    method: 'PUT',
    body: JSON.stringify( { status } ),
  } );
  return data !== null;
}

export async function deleteBulkJob ( jobId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/bulk/jobs/${jobId}`, {
    method: 'DELETE',
  } );
  return data !== null;
}

