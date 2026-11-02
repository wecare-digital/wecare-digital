import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { normalizeWhatsAppTemplateDetails, type NormalizedWhatsAppTemplateDetail } from '../../lib/whatsappTemplateDetails';
import { apiCall, apiCallResult, recordFailure, WA_BIZ_BASE } from '../core';
import type { ApiResult } from '../core';
import { createContact, listContacts, updateContact } from './contacts';
import type { Contact } from './contacts';
import type { Message } from './messaging';

// ============================================================================
// WHATSAPP TEMPLATES API (Meta Graph API)
// ============================================================================

export interface WhatsAppTemplate {
  fixedHeaderMedia?: string;
  id: string;
  name: string;
  language: string;
  category: 'MARKETING' | 'UTILITY' | 'AUTHENTICATION';
  status: 'APPROVED' | 'PENDING' | 'REJECTED';
  components: TemplateComponent[];
}

export interface TemplateComponent {
  type: 'HEADER' | 'BODY' | 'FOOTER' | 'BUTTONS' | 'CAROUSEL';
  format?: 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT' | 'LOCATION';
  text?: string;
  example?: { body_text?: string[][] };
  buttons?: { type: string; text: string; url?: string; phone_number?: string }[];
  cards?: any[];
}

// listWhatsAppTemplates() and getWhatsAppTemplate() removed — use listTemplates() and getTemplateDetails() instead

/**
 * Send a template message via WhatsApp
 * Templates can be sent outside the 24h window
 */
export async function sendWhatsAppTemplateMessage ( request: {
  contactId?: string;
  recipientPhone?: string;    // Send by phone number — auto-creates contact if needed
  templateName: string;
  language?: string;
  components?: any[];
  phoneNumberId?: string;
  templateParams?: string[];  // Variable values like OTP code
  recipientBsuid?: string;    // Send to BSUID recipient
  headerMedia?: string;       // Public https link OR S3 key for a media header template
  headerType?: 'image' | 'video' | 'document' | 'location';  // Header format for media/location templates
  headerFilename?: string;    // Filename for document headers
  headerLocation?: { latitude: string; longitude: string; name?: string; address?: string };  // Location header params
  flowButton?: { index: number; flowToken?: string; flowActionData?: Record<string, any> };  // Flow button component (templates with a FLOW button)
  templateUrlButton?: { index: number; suffix: string };  // Dynamic URL button suffix; never pass the full template URL
  content?: string;           // Rendered preview text stored for inbox thread display
  campaignId?: string;        // Optional campaign tracking
  campaignName?: string;
} ): Promise<{ messageId: string; status: string } | null> {
  // Build template params array - include language as first param for Lambda
  const params: string[] = [];

  // Add language code as first param (Lambda will extract it)
  if ( request.language )
  {
    params.push( request.language );
  }

  // Add template variable values
  if ( request.templateParams && request.templateParams.length > 0 )
  {
    params.push( ...request.templateParams );
  }

  const payload: Record<string, any> = {
    isTemplate: true,
    templateName: request.templateName,
    templateParams: params,
    phoneNumberId: request.phoneNumberId,
    recipientBsuid: request.recipientBsuid,
  };

  // Rendered preview text so the sent template shows in the conversation thread.
  if ( request.content ) payload.content = request.content;
  if ( request.campaignId ) payload.campaignId = request.campaignId;
  if ( request.campaignName ) payload.campaignName = request.campaignName;

  // Media header (IMAGE/VIDEO/DOCUMENT) — required at send time by Meta for
  // templates whose header is a media format.
  if ( request.headerMedia )
  {
    payload.headerMedia = request.headerMedia;
    if ( request.headerType ) payload.headerType = request.headerType;
    if ( request.headerFilename ) payload.headerFilename = request.headerFilename;
  }
  // Location header — coordinates supplied at send time.
  if ( request.headerType === 'location' && request.headerLocation )
  {
    payload.headerType = 'location';
    payload.headerLocation = request.headerLocation;
  }
  // Flow button — required when the template has a FLOW button.
  if ( request.flowButton )
  {
    payload.flowButton = request.flowButton;
  }
  if ( request.templateUrlButton )
  {
    payload.templateUrlButton = request.templateUrlButton;
  }

  // Support sending by contactId or recipientPhone (auto-creates contact)
  if ( request.contactId )
  {
    payload.contactId = request.contactId;
  } else if ( request.recipientPhone )
  {
    payload.recipientPhone = request.recipientPhone;
  }

  return apiCall<{ messageId: string; status: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

function normalizeTemplate ( item: any ): WhatsAppTemplate {
  return {
    fixedHeaderMedia: item.fixedHeaderMedia || undefined,
    id: item.id || item.templateId || item.name || '',
    name: item.name || item.templateName || '',
    language: item.language || item.languageCode || 'en_US',
    category: ( item.category || 'UTILITY' ).toUpperCase() as 'MARKETING' | 'UTILITY' | 'AUTHENTICATION',
    status: ( item.status || 'APPROVED' ).toUpperCase() as 'APPROVED' | 'PENDING' | 'REJECTED',
    components: item.components || [],
  };
}


// ============================================================================
// WHATSAPP PAYMENT MESSAGE API — REMOVED
//
// `sendWhatsAppPaymentMessage`, `SendPaymentMessageRequest` and `PaymentOrderItem` stood here.
// They composed the whole Meta `order_details` payload IN THE BROWSER: the `reference_id` was
// minted client-side, and `payment_configuration` fell back to a client-side literal, which is
// exactly what requirements statement 9 forbids. A client-minted reference has no `PAYREF#` row,
// so a capture against it resolves to nothing and quarantines as PAID_BUT_NO_ORDER.
//
// No payment is composed outside `amplify/` any more, and a test asserts it. Staff surfaces raise
// an invoice (`createInvoiceEngine`) and then ask the server to send its payment request
// (`sendPaymentLink`), so identity is reserved before the send and both readiness gates apply.
// ============================================================================


// ============================================================================
// WABA MANAGEMENT API (Meta Graph API)
// ============================================================================

export interface WABAAccount {
  id: string;
  wabaId: string;
  wabaName: string;
  arn: string;
  registrationStatus: string;
  linkDate?: number;
  enableSending: boolean;
  enableReceiving: boolean;
  eventDestinations: { eventDestinationArn: string; roleArn: string }[];
  phoneNumbers?: WABAPhoneNumber[];
}

export interface WABAPhoneNumber {
  phoneNumberId: string;
  phoneNumber: string;
  displayPhoneNumber: string;
  displayPhoneNumberName: string;
  qualityRating: 'GREEN' | 'YELLOW' | 'RED' | 'UNKNOWN';
  metaPhoneNumberId: string;
  dataLocalizationRegion: string;
  arn: string;
  linkedWabaId?: string;
}

export interface WABASystemEvents {
  templateStatus: { timestamp: number; data: any }[];
  phoneQuality: { timestamp: number; data: any }[];
  accountUpdates: { timestamp: number; data: any }[];
}

/**
 * List all linked WhatsApp Business Accounts
 * API: ListLinkedWhatsAppBusinessAccounts
 */
export async function listWABAs (): Promise<WABAAccount[]> {
  const data = await apiCall<any>( `${API_BASE}/waba` );
  if ( data && data.wabas )
  {
    return data.wabas;
  }
  return [];
}

/**
 * Get WABA details including phone numbers with quality ratings
 * API: GetLinkedWhatsAppBusinessAccount
 */
export async function getWABADetails ( wabaId: string ): Promise<WABAAccount | null> {
  const data = await apiCall<any>( `${API_BASE}/waba/${wabaId}` );
  if ( data )
  {
    return data;
  }
  return null;
}

/**
 * Get phone number details including quality rating
 * API: GetLinkedWhatsAppBusinessAccountPhoneNumber
 */
export async function getPhoneNumberDetails ( phoneNumberId: string ): Promise<WABAPhoneNumber | null> {
  const data = await apiCall<any>( `${API_BASE}/waba/phone/${phoneNumberId}` );
  if ( data )
  {
    return data;
  }
  return null;
}

/**
 * Get system events (template status, phone quality, account updates)
 * Stored by inbound webhook handler
 */
export async function getWABASystemEvents ( eventType?: string ): Promise<WABASystemEvents> {
  let url = `${API_BASE}/waba/events`;
  if ( eventType ) url += `?type=${eventType}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return {
      templateStatus: data.templateStatus || [],
      phoneQuality: data.phoneQuality || [],
      accountUpdates: data.accountUpdates || [],
    };
  }
  return { templateStatus: [], phoneQuality: [], accountUpdates: [] };
}

/**
 * Delete WhatsApp media from Meta servers
 * API: DeleteWhatsAppMessageMedia
 */
export async function deleteWhatsAppMedia ( mediaId: string, phoneNumberId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/media/${mediaId}?phoneNumberId=${phoneNumberId}`, {
    method: 'DELETE',
  } );
  return data?.success === true;
}


// ============================================================================
// TEMPLATE MANAGEMENT API (Meta Graph API)
// ============================================================================

export interface TemplateDefinition {
  name: string;
  language: string;
  category: 'UTILITY' | 'MARKETING' | 'AUTHENTICATION';
  components: TemplateComponent[];
  /** Marks a MARKETING template as an order details ("Review and Pay") template. Meta's only value. */
  display_format?: 'order_details';
}

export interface MetaLibraryTemplate {
  templateId: string;
  templateName: string;
  templateCategory: string;
  templateLanguage: string;
  templateBody: string;
  templateHeader?: string;
  templateTopic?: string;
  templateUseCase?: string;
  templateIndustry?: string[];
  templateButtons?: any[];
  templateBodyExampleParams?: string[];
}

export interface CreateTemplateRequest {
  wabaId?: string;
  templateDefinition: TemplateDefinition;
}

export interface CreateFromLibraryRequest {
  wabaId?: string;
  metaLibraryTemplate: {
    libraryTemplateName: string;
    templateName: string;
    templateCategory: string;
    templateLanguage: string;
    libraryTemplateBodyInputs?: {
      addTrackPackageLink?: boolean;
      addContactNumber?: boolean;
      addLearnMoreLink?: boolean;
      addSecurityRecommendation?: boolean;
      codeExpirationMinutes?: number;
    };
    libraryTemplateButtonInputs?: any[];
  };
}

export interface UpdateTemplateRequest {
  wabaId?: string;
  templateCategory?: string;
  templateComponents?: any;
  parameterFormat?: string;
  ctaUrlLinkTrackingOptedOut?: boolean;
}

/**
 * List templates for a WABA (enhanced version)
 * API: ListWhatsAppMessageTemplates
 */
export async function listTemplates ( wabaId?: string, maxResults?: number ): Promise<WhatsAppTemplate[]> {
  let url = `${API_BASE}/whatsapp/templates`;
  const params = new URLSearchParams();
  if ( wabaId ) params.append( 'wabaId', wabaId );
  if ( maxResults ) params.append( 'maxResults', maxResults.toString() );
  if ( params.toString() ) url += `?${params}`;

  const data = await apiCall<any>( url );
  if ( data && data.templates )
  {
    return data.templates.map( normalizeTemplate );
  }
  return [];
}

/**
 * Google Maps Places — autocomplete (backend-proxied; key stays in Secrets Manager).
 * Used by location templates to resolve coordinates from a typed address.
 */
export async function placesAutocomplete ( q: string, sessionToken?: string ): Promise<{ description: string; placeId: string }[]> {
  if ( !q || q.trim().length < 3 ) return [];
  let url = `${API_BASE}/whatsapp/templates?action=places-autocomplete&q=${encodeURIComponent( q )}`;
  if ( sessionToken ) url += `&sessiontoken=${encodeURIComponent( sessionToken )}`;
  const data = await apiCall<any>( url );
  return data?.predictions || [];
}

/**
 * Google Maps Places — place details → { latitude, longitude, name, address }.
 */
export async function placeDetails ( placeId: string, sessionToken?: string ): Promise<{ latitude: number; longitude: number; name: string; address: string } | null> {
  if ( !placeId ) return null;
  let url = `${API_BASE}/whatsapp/templates?action=place-details&placeId=${encodeURIComponent( placeId )}`;
  if ( sessionToken ) url += `&sessiontoken=${encodeURIComponent( sessionToken )}`;
  const data = await apiCall<any>( url );
  return data?.place || null;
}

// ============================================================================
// CORS MANAGEMENT (admin) — view/apply allowed origins on the HTTP APIs
// ============================================================================

export interface CorsApiStatus {
  apiId: string;
  name?: string;
  endpoint?: string;
  allowOrigins?: string[];
  allowMethods?: string[];
  allowHeaders?: string[];
  allowAll?: boolean;
  error?: string;
}

export interface CorsStatus {
  apis: CorsApiStatus[];
  recommendedOrigins: string[];
  coreOrigins: string[];
}

export async function getCorsStatus (): Promise<CorsStatus | null> {
  return apiCall<CorsStatus>( `${API_BASE}/waba?action=cors-status` );
}

export async function applyCors ( request: { origins: string[] } ): Promise<{ success: boolean; allowOrigins: string[] } | null> {
  return apiCall<{ success: boolean; allowOrigins: string[] }>( `${API_BASE}/waba`, {
    method: 'POST',
    body: JSON.stringify( { action: 'cors-apply', origins: request.origins } ),
  } );
}

/**
 * Get template details
 * API: GetWhatsAppMessageTemplate
 */
export async function getTemplateDetailsResult ( templateId: string, wabaId?: string ): Promise<ApiResult<NormalizedWhatsAppTemplateDetail>> {
  let url = `${API_BASE}/whatsapp/templates/${templateId}`;
  if (wabaId) url += `?wabaId=${encodeURIComponent(wabaId)}`;
  const result = await apiCallResult<unknown>(url);
  if (!result.ok) return result;
  const template = normalizeWhatsAppTemplateDetails(result.data, templateId);
  if (!template) return {ok:false,failure:recordFailure('server',200,'Template metadata did not match the requested template. Reload to recheck.',url,'TEMPLATE_METADATA_INVALID')};
  return {ok:true,data:template};
}
export async function getTemplateDetails ( templateId: string, wabaId?: string ): Promise<NormalizedWhatsAppTemplateDetail | null> {
  const result = await getTemplateDetailsResult(templateId,wabaId);
  return result.ok ? result.data : null;
}

/**
 * Create a new template from custom definition
 * API: CreateWhatsAppMessageTemplate
 */
export async function createTemplate ( request: CreateTemplateRequest ): Promise<{ metaTemplateId: string; category: string; templateStatus: string } | null> {
  return apiCall<any>( `${API_BASE}/whatsapp/templates`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

/**
 * Create template from Meta's library
 * API: CreateWhatsAppMessageTemplateFromLibrary
 */
export async function createTemplateFromLibrary ( request: CreateFromLibraryRequest ): Promise<{ metaTemplateId: string; category: string; templateStatus: string } | null> {
  return apiCall<any>( `${API_BASE}/whatsapp/template-from-library`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

/**
 * Update an existing template
 * API: UpdateWhatsAppMessageTemplate
 */
export async function updateTemplate ( templateId: string, request: UpdateTemplateRequest ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/whatsapp/templates/${templateId}`, {
    method: 'PUT',
    body: JSON.stringify( request ),
  } );
  return data?.success === true;
}

/**
 * Delete a template
 * API: DeleteWhatsAppMessageTemplate
 */
export async function deleteTemplate ( templateName: string, wabaId?: string, deleteAllLanguages?: boolean ): Promise<boolean> {
  let url = `${API_BASE}/whatsapp/templates/${templateName}`;
  const params = new URLSearchParams();
  params.append( 'templateName', templateName );
  if ( wabaId ) params.append( 'wabaId', wabaId );
  if ( deleteAllLanguages ) params.append( 'deleteAllLanguages', 'true' );
  url += `?${params}`;

  const data = await apiCall<any>( url, { method: 'DELETE' } );
  return data?.success === true;
}

/**
 * Browse Meta's template library
 * API: ListWhatsAppTemplateLibrary
 */
export async function listTemplateLibrary ( filters?: {
  wabaId?: string;
  searchKey?: string;
  topic?: string;
  usecase?: string;
  industry?: string;
  language?: string;
  maxResults?: number;
} ): Promise<MetaLibraryTemplate[]> {
  let url = `${API_BASE}/whatsapp/template-library`;
  if ( filters )
  {
    const params = new URLSearchParams();
    Object.entries( filters ).forEach( ( [ key, value ] ) => {
      if ( value ) params.append( key, value.toString() );
    } );
    if ( params.toString() ) url += `?${params}`;
  }

  const data = await apiCall<any>( url );
  if ( data && data.templates )
  {
    return data.templates;
  }
  return [];
}

/**
 * Upload media for template headers
 * API: CreateWhatsAppMessageTemplateMedia
 */
export async function uploadTemplateMedia ( request: {
  wabaId?: string;
  mediaBase64?: string;
  s3Key?: string;
  mediaType?: string;
  filename?: string;
} ): Promise<{ metaHeaderHandle: string; s3Key: string } | null> {
  return apiCall<any>( `${API_BASE}/whatsapp/templates/media`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

/**
 * Upload media for SENDING a template message (public URL for WhatsApp to fetch).
 * Returns a CDN URL: https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/{folder}/...
 * (the bucket is `wecare-digital-get`; its name is not a hostname.)
 *
 * Supports all WhatsApp Cloud API media types:
 *   - Documents: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT (max 100MB) → docs/
 *   - Images:    JPEG, PNG (max 5MB)                                   → img/
 *   - Videos:    MP4, 3GP (max 16MB)                                   → vid/
 *   - Audio:     AAC, AMR, MP3, M4A, OGG (max 16MB)                    → aud/
 *   - Stickers:  WebP (max 500KB)                                      → stk/
 */
export async function uploadSendMedia ( request: {
  fileData: string;       // base64-encoded file content
  contentType: string;    // MIME type (e.g. "application/pdf")
  filename: string;       // original filename
} ): Promise<{
  mediaUrl: string;
  s3Key: string;
  folder: 'docs' | 'img' | 'vid' | 'aud' | 'stk';
  category: 'document' | 'image' | 'video' | 'audio' | 'sticker';
  filename: string;
  sizeBytes: number;
} | null> {
  return apiCall<any>( `${API_BASE}/whatsapp/templates/send-media`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

/** A reusable template-send media file stored in the public wa-tpl/ library. */
export interface SendMediaItem {
  s3Key: string;
  mediaUrl: string;
  filename: string;
  folder: 'docs' | 'img' | 'vid' | 'aud' | 'stk';
  category: 'document' | 'image' | 'video' | 'audio' | 'sticker';
  sizeBytes: number;
  lastModified: string | null;
}

/** List reusable template-send media. Optionally filter by category or search text. */
export async function listSendMedia ( opts?: { category?: SendMediaItem[ 'category' ]; search?: string } ): Promise<SendMediaItem[]> {
  const qs = new URLSearchParams();
  if ( opts?.category ) qs.set( 'category', opts.category );
  if ( opts?.search ) qs.set( 'search', opts.search );
  const q = qs.toString();
  const data = await apiCall<{ items: SendMediaItem[] }>(
    `${API_BASE}/whatsapp/templates/send-media${q ? '?' + q : ''}`,
    { method: 'GET' }
  );
  return data?.items || [];
}

/** Permanently delete a reusable template-send media file from the wa-tpl/ library. */
export async function deleteSendMedia ( s3KeyOrUrl: string ): Promise<boolean> {
  const data = await apiCall<any>(
    `${API_BASE}/whatsapp/templates/send-media?s3Key=${encodeURIComponent( s3KeyOrUrl )}`,
    { method: 'DELETE' }
  );
  return data !== null && ( data.success === true || !data.error );
}

/** Helper: convert a File/Blob to base64 string (without data: prefix) */
export function fileToBase64 ( file: File | Blob ): Promise<string> {
  return new Promise( ( resolve, reject ) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip "data:mime/type;base64," prefix
      const base64 = result.split( ',' )[ 1 ] || result;
      resolve( base64 );
    };
    reader.onerror = reject;
    reader.readAsDataURL( file );
  } );
}


// ============================================================================
// AI CONFIG MANAGEMENT API (Bedrock Control)
// ============================================================================

export interface BedrockAIConfig {
  enabled: boolean;
  autoReplyEnabled: boolean;
  respondToInteractive: boolean;
  respondToText: boolean;
  respondToMedia: boolean;
  respondToLocation: boolean;
  maxResponseLength: number;
  responseDelay: number;
  supportedLanguages: string[];
  defaultLanguage: string;
  agentId: string;
  agentAlias: string;
  knowledgeBaseId: string;
  modelId: string;
}

export interface AIInteraction {
  interactionId: string;
  messageId: string;
  query: string;
  response: string;
  detectedLanguage?: string;
  approved: boolean;
  timestamp: number;
}

export interface AIStats {
  totalInteractions: number;
  approvedResponses: number;
  approvalRate: number;
  byLanguage: Record<string, number>;
}

export interface SupportedLanguages {
  [ code: string ]: string;
}

/**
 * Get Bedrock AI configuration
 * API: GET /ai/config
 */
export async function getBedrockAIConfig (): Promise<BedrockAIConfig> {
  const data = await apiCall<any>( `${API_BASE}/ai/config` );
  if ( data && data.config )
  {
    return data.config;
  }
  // Return defaults if API fails
  return {
    enabled: false,
    autoReplyEnabled: false,
    respondToInteractive: true,
    respondToText: true,
    respondToMedia: false,
    respondToLocation: true,
    maxResponseLength: 500,
    responseDelay: 0,
    supportedLanguages: [ 'en', 'hi', 'hi-Latn', 'bn', 'ta', 'te', 'gu', 'mr' ],
    defaultLanguage: 'en',
    agentId: '',
    agentAlias: '',
    knowledgeBaseId: '',
    modelId: 'amazon.nova-pro-v1:0',
  };
}

/**
 * Update Bedrock AI configuration
 * API: PUT /ai/config
 */
export async function updateBedrockAIConfig ( updates: Partial<BedrockAIConfig> ): Promise<BedrockAIConfig | null> {
  const data = await apiCall<any>( `${API_BASE}/ai/config`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  if ( data && data.config )
  {
    return data.config;
  }
  return null;
}

/**
 * Get language-specific prompts
 * API: GET /ai/prompts or GET /ai/prompts/{lang}
 */
export async function getAIPrompts ( lang?: string ): Promise<Record<string, string> | string> {
  const url = lang ? `${API_BASE}/ai/prompts/${lang}` : `${API_BASE}/ai/prompts`;
  const data = await apiCall<any>( url );
  if ( data )
  {
    return lang ? ( data.prompt || '' ) : ( data.prompts || {} );
  }
  return lang ? '' : {};
}

/**
 * Update language-specific prompt
 * API: PUT /ai/prompts/{lang}
 */
export async function updateAIPrompt ( lang: string, prompt: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/ai/prompts/${lang}`, {
    method: 'PUT',
    body: JSON.stringify( { language: lang, prompt } ),
  } );
  return data?.success === true;
}

/**
 * Get language-specific fallback messages
 * API: GET /ai/fallbacks or GET /ai/fallbacks/{lang}
 */
export async function getAIFallbacks ( lang?: string ): Promise<Record<string, string> | string> {
  const url = lang ? `${API_BASE}/ai/fallbacks/${lang}` : `${API_BASE}/ai/fallbacks`;
  const data = await apiCall<any>( url );
  if ( data )
  {
    return lang ? ( data.fallback || '' ) : ( data.fallbacks || {} );
  }
  return lang ? '' : {};
}

/**
 * Update language-specific fallback message
 * API: PUT /ai/fallbacks/{lang}
 */
export async function updateAIFallback ( lang: string, fallback: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/ai/fallbacks/${lang}`, {
    method: 'PUT',
    body: JSON.stringify( { language: lang, fallback } ),
  } );
  return data?.success === true;
}

/**
 * Get AI interaction logs
 * API: GET /ai/interactions
 */
export async function getAIInteractions ( limit?: number ): Promise<AIInteraction[]> {
  let url = `${API_BASE}/ai/interactions`;
  if ( limit ) url += `?limit=${limit}`;

  const data = await apiCall<any>( url );
  if ( data && data.interactions )
  {
    return data.interactions;
  }
  return [];
}

/**
 * Get AI usage statistics
 * API: GET /ai/stats
 */
export async function getAIStats (): Promise<AIStats> {
  const data = await apiCall<any>( `${API_BASE}/ai/stats` );
  if ( data )
  {
    return {
      totalInteractions: data.totalInteractions || 0,
      approvedResponses: data.approvedResponses || 0,
      approvalRate: data.approvalRate || 0,
      byLanguage: data.byLanguage || {},
    };
  }
  return { totalInteractions: 0, approvedResponses: 0, approvalRate: 0, byLanguage: {} };
}

/**
 * Get supported languages
 * API: GET /ai/languages
 */
export async function getSupportedLanguages (): Promise<SupportedLanguages> {
  const data = await apiCall<any>( `${API_BASE}/ai/languages` );
  if ( data && data.languages )
  {
    return data.languages;
  }
  return {
    'en': 'English',
    'hi': 'Hindi',
    'hi-Latn': 'Hinglish',
    'bn': 'Bengali',
    'ta': 'Tamil',
    'te': 'Telugu',
    'gu': 'Gujarati',
    'mr': 'Marathi',
  };
}

/**
 * Test AI response generation
 * API: POST /ai/test
 */
export async function testBedrockAIResponse ( message: string ): Promise<{
  message: string; response: string; detectedLanguage: string;
  responseLanguage: string; languageSource: string; modelId: string;
} | null> {
  const data = await apiCall<any>( `${API_BASE}/ai/test`, {
    method: 'POST',
    body: JSON.stringify( { message } ),
  } );
  if ( !data || typeof data.response !== 'string' || !data.response.trim() ) return null;
  return {
    message: typeof data.message === 'string' ? data.message : message,
    response: data.response,
    detectedLanguage: data.detectedLanguage || 'und',
    responseLanguage: data.responseLanguage || '',
    languageSource: data.languageSource || '',
    modelId: data.modelId || '',
  };
}


// ============================================================================
// WABA ADVANCED MANAGEMENT API (Meta Graph API)
// ============================================================================

/**
 * Download media from WhatsApp
 * API: GetWhatsAppMessageMedia
 */
export async function getWhatsAppMedia ( mediaId: string, phoneNumberId: string, metadataOnly?: boolean ): Promise<{
  mediaId: string;
  mimeType: string;
  fileSize: number;
  s3Key?: string;
  downloadUrl?: string;
} | null> {
  let url = `${API_BASE}/waba/media/${mediaId}?phoneNumberId=${phoneNumberId}`;
  if ( metadataOnly ) url += '&metadataOnly=true';

  const data = await apiCall<any>( url );
  if ( data )
  {
    return {
      mediaId: data.mediaId || mediaId,
      mimeType: data.mimeType || '',
      fileSize: data.fileSize || 0,
      s3Key: data.s3Key,
      downloadUrl: data.downloadUrl,
    };
  }
  return null;
}

/**
 * Upload media to WhatsApp for sending
 * API: PostWhatsAppMessageMedia
 */
export async function postWhatsAppMedia ( phoneNumberId: string, s3Key: string ): Promise<{
  mediaId: string;
  s3Key: string;
} | null> {
  return apiCall<any>( `${API_BASE}/waba/media`, {
    method: 'POST',
    body: JSON.stringify( { phoneNumberId, s3Key } ),
  } );
}

/**
 * Configure event destinations for WABA
 * API: PutWhatsAppBusinessAccountEventDestinations
 */
export async function putWABAEventDestinations ( wabaId: string, eventDestinations: {
  eventDestinationArn: string;
  roleArn: string;
}[] ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/${wabaId}/events`, {
    method: 'PUT',
    body: JSON.stringify( { wabaId, eventDestinations } ),
  } );
  return data?.success === true;
}

/**
 * List tags for a WABA or phone number resource
 * API: ListTagsForResource
 */
export async function listWABATags ( resourceArn: string ): Promise<{ key: string; value: string }[]> {
  const data = await apiCall<any>( `${API_BASE}/waba/tags?resourceArn=${encodeURIComponent( resourceArn )}` );
  if ( data && data.tags )
  {
    return data.tags;
  }
  return [];
}

/**
 * Add tags to a WABA or phone number resource
 * API: TagResource
 */
export async function tagWABAResource ( resourceArn: string, tags: { key: string; value: string }[] ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/tags`, {
    method: 'POST',
    body: JSON.stringify( { resourceArn, tags } ),
  } );
  return data?.success === true;
}

/**
 * Remove tags from a WABA or phone number resource
 * API: UntagResource
 */
export async function untagWABAResource ( resourceArn: string, tagKeys: string[] ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/tags`, {
    method: 'DELETE',
    body: JSON.stringify( { resourceArn, tagKeys } ),
  } );
  return data?.success === true;
}


// ============================================================================
// WABA SNS SUBSCRIPTION API
// ============================================================================

export interface WABASNSSubscriptionStatus {
  wabaId: string;
  storedConfig: {
    wabaId?: string;
    snsTopicArn?: string;
    roleArn?: string;
    subscribedAt?: string;
    unsubscribedAt?: string;
    status?: string;
  };
  liveEventDestinations: { eventDestinationArn: string; roleArn?: string }[];
  isSubscribed: boolean;
  defaultTopicArn: string;
}

/**
 * Subscribe a WABA to SNS topic for receiving WhatsApp events
 * Sets up PutWhatsAppBusinessAccountEventDestinations
 */
export async function subscribeWABAToSNS ( wabaId: string, snsTopicArn?: string, roleArn?: string ): Promise<boolean> {
  const body: Record<string, string> = {};
  if ( snsTopicArn ) body.snsTopicArn = snsTopicArn;
  if ( roleArn ) body.roleArn = roleArn;
  const data = await apiCall<any>( `${API_BASE}/waba/${wabaId}/subscribe-sns`, {
    method: 'POST',
    body: JSON.stringify( body ),
  } );
  return data?.success === true;
}

/**
 * Unsubscribe a WABA from SNS (clears event destinations)
 */
export async function unsubscribeWABAFromSNS ( wabaId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/${wabaId}/subscribe-sns`, {
    method: 'DELETE',
    body: JSON.stringify( {} ),
  } );
  return data?.success === true;
}

/**
 * Get current SNS subscription status for a WABA
 */
export async function getWABASNSSubscriptionStatus ( wabaId: string ): Promise<WABASNSSubscriptionStatus | null> {
  return apiCall<WABASNSSubscriptionStatus>( `${API_BASE}/waba/${wabaId}/subscribe-sns` );
}


// ============================================================================
// WABA PHONE MIGRATION & REGISTRATION API
// ============================================================================

/**
 * Request OTP/PIN for phone number verification
 */
export async function requestPhoneOTP ( phoneNumberId: string, method: 'SMS' | 'VOICE' = 'SMS' ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/request-otp`, {
    method: 'POST',
    body: JSON.stringify( { phoneNumberId, method } ),
  } );
  return data?.success === true;
}

/**
 * Verify OTP/PIN code for phone number
 */
export async function verifyPhoneOTP ( phoneNumberId: string, code: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/verify-otp`, {
    method: 'POST',
    body: JSON.stringify( { phoneNumberId, code } ),
  } );
  return data?.success === true;
}

/**
 * Set or change WhatsApp two-step verification for a business phone number.
 * Meta accepts exactly six digits. The PIN is sent only to the Admin API and is never stored.
 */
export async function setPhoneTwoStepPin ( phoneNumberId: string, pin: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/two-step-pin`, {
    method: 'POST',
    body: JSON.stringify( { phoneNumberId, pin } ),
  } );
  return data?.success === true;
}

/**
 * Register a phone number with optional PIN
 */
export async function registerPhone ( phoneNumberId: string, pin?: string ): Promise<boolean> {
  const body: Record<string, string> = { phoneNumberId };
  if ( pin ) body.pin = pin;
  const data = await apiCall<any>( `${API_BASE}/waba/register-phone`, {
    method: 'POST',
    body: JSON.stringify( body ),
  } );
  return data?.success === true;
}

/**
 * Migrate a phone number between WABAs
 * @param sendPin - If true, sends PIN via SMS/VOICE before migration
 */
export async function migratePhone ( params: {
  phoneNumberId: string;
  sourceWabaId?: string;
  targetWabaId: string;
  pin?: string;
  sendPin?: boolean;
  pinMethod?: 'SMS' | 'VOICE';
} ): Promise<{ success: boolean; pinSent?: boolean; status?: string } | null> {
  return apiCall<any>( `${API_BASE}/waba/migrate`, {
    method: 'POST',
    body: JSON.stringify( params ),
  } );
}


// The AD ATTRIBUTION API block was here: `getAdAttributionStats` and
// `getAdAttributionClicks`, both against `${API_BASE}/ad-attribution*`. Removed
// 2026-10-07 — the live HTTP API has no route under that prefix, so both calls
// could only ever resolve to a 404. Their one consumer,
// src/components/AdAttributionDashboard.tsx, went in the same change; nothing else
// in src/ referenced either function. The `wecare-ad-attribution` LAMBDA is
// untouched: retiring it is a separate, owner-gated decision, and this change only
// removes a frontend that could not reach it.


// ============================================================================
// TEMPLATE ANALYTICS API
// ============================================================================

export interface TemplateAnalytics {
  templateName: string;
  language: string;
  totalSent: number;
  delivered: number;
  read: number;
  failed: number;
  deliveryRate: number;
  readRate: number;
  lastSent?: string;
  buttonClicks?: Record<string, number>;
}

export interface TemplateAnalyticsSummary {
  totalTemplatesSent: number;
  avgDeliveryRate: number;
  avgReadRate: number;
  topTemplates: TemplateAnalytics[];
  byCategory: Record<string, number>;
}

/**
 * Get analytics for a specific template
 * API: GET /templates/analytics/{templateName}
 */
export async function getTemplateAnalytics ( templateName: string, wabaId?: string ): Promise<TemplateAnalytics | null> {
  let url = `${API_BASE}/templates/analytics/${templateName}`;
  if ( wabaId ) url += `?wabaId=${wabaId}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return {
      templateName: data.templateName || templateName,
      language: data.language || 'en_US',
      totalSent: data.totalSent || 0,
      delivered: data.delivered || 0,
      read: data.read || 0,
      failed: data.failed || 0,
      deliveryRate: data.deliveryRate || 0,
      readRate: data.readRate || 0,
      lastSent: data.lastSent,
      buttonClicks: data.buttonClicks,
    };
  }
  return null;
}

/**
 * Get analytics summary for all templates
 * API: GET /templates/analytics
 */
export async function getTemplateAnalyticsSummary ( wabaId?: string ): Promise<TemplateAnalyticsSummary> {
  let url = `${API_BASE}/templates/analytics`;
  if ( wabaId ) url += `?wabaId=${wabaId}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return {
      totalTemplatesSent: data.totalTemplatesSent || 0,
      avgDeliveryRate: data.avgDeliveryRate || 0,
      avgReadRate: data.avgReadRate || 0,
      topTemplates: data.topTemplates || [],
      byCategory: data.byCategory || {},
    };
  }
  throw new Error( 'Template analytics unavailable' );
}

// ============================================================================
// SCHEDULED MESSAGES API
// ============================================================================

export interface ScheduledMessage {
  id: string;
  scheduledId: string;
  contactId: string;
  contactName?: string;
  contactPhone?: string;
  templateName: string;
  templateParams: string[];
  phoneNumberId: string;
  scheduledAt: string;  // ISO timestamp
  status: 'PENDING' | 'DISPATCHING' | 'DISPATCH_UNKNOWN' | 'SENT' | 'FAILED' | 'CANCELLED';
  createdAt: string;
  sentAt?: string;
  errorMessage?: string;
}

/**
 * Schedule a template message for later delivery
 * API: POST /messages/scheduled
 */
export async function scheduleTemplateMessage ( request: {
  contactId: string;
  templateName: string;
  templateParams?: string[];
  phoneNumberId?: string;
  recipientBsuid?: string;
  headerMedia?: string;
  headerType?: 'image' | 'video' | 'document' | 'location';
  headerFilename?: string;
  headerLocation?: { latitude: string; longitude: string; name?: string; address?: string };
  flowButton?: { index: number; flowToken?: string; flowActionData?: Record<string, any> };
  templateUrlButton?: { index: number; suffix: string };
  scheduledAt: string;  // ISO timestamp
} ): Promise<ScheduledMessage | null> {
  const data = await apiCall<any>( `${API_BASE}/scheduled`, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
  if ( data )
  {
    return normalizeScheduledMessage( data );
  }
  return null;
}

/**
 * List scheduled messages
 * API: GET /messages/scheduled
 */
export async function listScheduledMessages ( status?: string ): Promise<ScheduledMessage[]> {
  let url = `${API_BASE}/scheduled`;
  if ( status !== undefined ) url += `?status=${encodeURIComponent( status )}`;

  const data = await apiCall<any>( url );
  if ( !data || !Array.isArray( data.scheduledMessages ) ) throw new Error( 'Scheduled messages are unavailable' );
  if ( data && data.scheduledMessages )
  {
    return data.scheduledMessages.map( normalizeScheduledMessage );
  }
  return [];
}

/**
 * Cancel a scheduled message
 * API: DELETE /scheduled?scheduledId={scheduledId}
 */
export async function cancelScheduledMessage ( scheduledId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/scheduled?scheduledId=${encodeURIComponent( scheduledId )}`, {
    method: 'DELETE',
  } );
  return data?.success === true;
}


function normalizeScheduledMessage ( item: any ): ScheduledMessage {
  return {
    id: item.id || item.scheduledId || '',
    scheduledId: item.scheduledId || item.id || '',
    contactId: item.contactId || '',
    contactName: item.contactName,
    contactPhone: item.contactPhone,
    templateName: item.templateName || '',
    templateParams: item.templateParams || [],
    phoneNumberId: item.phoneNumberId || '',
    scheduledAt: item.scheduledAt || '',
    status: item.status || 'PENDING',
    createdAt: item.createdAt || new Date().toISOString(),
    sentAt: item.sentAt,
    errorMessage: item.errorMessage,
  };
}

// ============================================================================
// SEND CAROUSEL TEMPLATE MESSAGE
// ============================================================================

/**
 * Send a carousel template message to a contact
 * Carousel templates have multiple cards with media and buttons
 * 
 * API: POST /whatsapp/send with isTemplate=true and carousel components
 */
export async function sendCarouselTemplateMessage ( request: {
  contactId: string;
  templateName: string;
  language?: string;
  phoneNumberId?: string;
  recipientBsuid?: string;    // Send to BSUID recipient
  // Body text variables (for the main body above carousel)
  bodyParams?: string[];
  // Card-specific variables (array of arrays, one per card)
  cardParams?: string[][];
} ): Promise<{ messageId: string; status: string } | null> {
  // Build template components for carousel
  const components: any[] = [];

  // Body component with variables
  if ( request.bodyParams && request.bodyParams.length > 0 )
  {
    components.push( {
      type: 'body',
      parameters: request.bodyParams.map( text => ( { type: 'text', text } ) )
    } );
  }

  // Carousel card components
  if ( request.cardParams && request.cardParams.length > 0 )
  {
    request.cardParams.forEach( ( cardVars, cardIndex ) => {
      if ( cardVars && cardVars.length > 0 )
      {
        components.push( {
          type: 'carousel',
          card_index: cardIndex,
          components: [ {
            type: 'body',
            parameters: cardVars.map( text => ( { type: 'text', text } ) )
          } ]
        } );
      }
    } );
  }

  return apiCall<{ messageId: string; status: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( {
      contactId: request.contactId,
      isTemplate: true,
      templateName: request.templateName,
      templateParams: request.bodyParams || [],
      phoneNumberId: request.phoneNumberId,
      recipientBsuid: request.recipientBsuid,
      components: components.length > 0 ? components : undefined,
    } ),
  } );
}


// ============================================================================
// CONTACT TAGS & GROUPS API
// ============================================================================
// STARRED MESSAGES API
// ============================================================================

/**
 * Get starred message IDs
 */
export function getStarredMessages (): string[] {
  const stored = localStorage.getItem( 'starredMessages' );
  if ( stored )
  {
    try
    {
      return JSON.parse( stored );
    } catch
    {
      return [];
    }
  }
  return [];
}

/**
 * Toggle star on a message
 */
export function toggleStarMessage ( messageId: string ): boolean {
  const starred = getStarredMessages();
  const index = starred.indexOf( messageId );
  if ( index > -1 )
  {
    starred.splice( index, 1 );
  } else
  {
    starred.push( messageId );
  }
  localStorage.setItem( 'starredMessages', JSON.stringify( starred ) );
  return index === -1; // Returns true if now starred
}

/**
 * Check if message is starred
 */
export function isMessageStarred ( messageId: string ): boolean {
  return getStarredMessages().includes( messageId );
}

// ============================================================================
// EXPORT FUNCTIONS
// ============================================================================

/**
 * Export contacts to CSV
 */
export function exportContactsToCSV ( contacts: Contact[] ): string {
  const headers = [ 'Name', 'Phone', 'Email', 'BSUID', 'Username', 'Contact Book Name', 'Shipping Address', 'Billing Address', 'Tags', 'WhatsApp Opt-In', 'SMS Opt-In', 'Email Opt-In', 'Created At' ];
  const rows = contacts.map( c => [
    c.name || '',
    c.phone || '',
    c.email || '',
    c.bsuid || '',
    c.username || '',
    c.contactBookName || '',
    c.shippingAddress || '',
    c.billingAddress || '',
    ( c.tags || [] ).join( '; ' ),
    c.optInWhatsApp ? 'Yes' : 'No',
    c.optInSms ? 'Yes' : 'No',
    c.optInEmail ? 'Yes' : 'No',
    c.createdAt || '',
  ] );

  const csvContent = [
    headers.join( ',' ),
    ...rows.map( row => row.map( cell => `"${String( cell ).replace( /"/g, '""' )}"` ).join( ',' ) )
  ].join( '\n' );

  return csvContent;
}

/**
 * Export messages to CSV
 */
export function exportMessagesToCSV ( messages: Message[] ): string {
  const headers = [ 'Direction', 'Contact', 'Content', 'Status', 'Timestamp', 'Channel' ];
  const rows = messages.map( m => [
    m.direction,
    m.contactId,
    m.content?.substring( 0, 200 ) || '',
    m.status,
    m.timestamp,
    m.channel,
  ] );

  const csvContent = [
    headers.join( ',' ),
    ...rows.map( row => row.map( cell => `"${String( cell ).replace( /"/g, '""' )}"` ).join( ',' ) )
  ].join( '\n' );

  return csvContent;
}

/**
 * Export chat to text format
 */
export function exportChatToText ( messages: Message[], contactName: string ): string {
  const lines = [
    `Chat Export - ${contactName}`,
    `Exported: ${new Date().toLocaleString()}`,
    '---',
    '',
  ];

  messages.forEach( m => {
    const time = new Date( m.timestamp ).toLocaleString();
    const sender = m.direction === 'INBOUND' ? contactName : 'You';
    lines.push( `[${time}] ${sender}: ${m.content || '[Media]'}` );
  } );

  return lines.join( '\n' );
}

/**
 * Export chat to PDF format (HTML-based, opens print dialog)
 */
export function exportChatToPDF ( messages: Message[], contactName: string, wabaName?: string ): void {
  const sortedMessages = [ ...messages ].sort( ( a, b ) =>
    new Date( a.timestamp ).getTime() - new Date( b.timestamp ).getTime()
  );

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Chat Export - ${contactName}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }
    .header { text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #25D366; }
    .header h1 { font-size: 24px; color: #1a1a1a; margin-bottom: 8px; }
    .header p { color: #666; font-size: 12px; }
    .messages { display: flex; flex-direction: column; gap: 12px; }
    .message { max-width: 70%; padding: 12px 16px; border-radius: 12px; position: relative; }
    .message.inbound { align-self: flex-start; background: #f0f0f0; border-bottom-left-radius: 4px; }
    .message.outbound { align-self: flex-end; background: #dcf8c6; border-bottom-right-radius: 4px; }
    .message .sender { font-size: 11px; font-weight: 600; color: #25D366; margin-bottom: 4px; }
    .message .content { font-size: 14px; line-height: 1.4; word-wrap: break-word; }
    .message .time { font-size: 10px; color: #999; margin-top: 6px; text-align: right; }
    .message .media-tag { font-style: italic; color: #666; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e5e5; text-align: center; font-size: 11px; color: #999; }
    @media print { body { padding: 20px; } .message { break-inside: avoid; } }
  </style>
</head>
<body>
  <div class="header">
    <h1>◇ Chat with ${contactName}</h1>
    <p>${wabaName ? `WABA: ${wabaName} | ` : ''}Exported: ${new Date().toLocaleString()}</p>
    <p>${sortedMessages.length} messages</p>
  </div>
  <div class="messages">
    ${sortedMessages.map( m => {
    const time = new Date( m.timestamp ).toLocaleString();
    const sender = m.direction === 'INBOUND' ? contactName : 'You';
    const content = m.content || `<span class="media-tag">[${m.messageType || 'Media'}]</span>`;
    return `
        <div class="message ${m.direction.toLowerCase()}">
          <div class="sender">${sender}</div>
          <div class="content">${content}</div>
          <div class="time">${time}</div>
        </div>
      `;
  } ).join( '' )}
  </div>
  <div class="footer">
    <p>Generated by WECARE.DIGITAL</p>
  </div>
</body>
</html>
  `;

  // Open in new window and trigger print
  const printWindow = window.open( '', '_blank' );
  if ( printWindow )
  {
    printWindow.document.write( html );
    printWindow.document.close();
    printWindow.onload = () => {
      printWindow.print();
    };
  }
}

/**
 * Download file helper
 */
export function downloadFile ( content: string, filename: string, mimeType: string = 'text/csv' ) {
  const blob = new Blob( [ content ], { type: mimeType } );
  const url = URL.createObjectURL( blob );
  const a = document.createElement( 'a' );
  a.href = url;
  a.download = filename;
  document.body.appendChild( a );
  a.click();
  document.body.removeChild( a );
  URL.revokeObjectURL( url );
}

// ============================================================================
// BULK CONTACT IMPORT
// ============================================================================

export interface ImportResult {
  total: number;
  created: number;
  updated: number;
  failed: number;
  errors: string[];
}

/**
 * Parse CSV content to contact objects
 * All contacts auto opt-in to WhatsApp by default
 */
export function parseContactsCSV ( csvContent: string ): Partial<Contact>[] {
  const lines = csvContent.split( '\n' ).filter( line => line.trim() );
  if ( lines.length < 2 ) return [];

  const headers = lines[ 0 ].split( ',' ).map( h => h.trim().toLowerCase().replace( /"/g, '' ) );
  const contacts: Partial<Contact>[] = [];

  for ( let i = 1; i < lines.length; i++ )
  {
    const values = lines[ i ].match( /(".*?"|[^,]+)/g )?.map( v => v.replace( /^"|"$/g, '' ).trim() ) || [];
    const contact: Partial<Contact> = {
      // Auto opt-in all contacts by default
      optInWhatsApp: true,
      allowlistWhatsApp: true,
    };

    headers.forEach( ( header, index ) => {
      const value = values[ index ] || '';
      if ( header === 'name' ) contact.name = value;
      else if ( header === 'phone' ) contact.phone = value.startsWith( '+' ) ? value : `+${value}`;
      else if ( header === 'email' ) contact.email = value;
    } );

    if ( contact.phone )
    {
      contacts.push( contact );
    }
  }

  return contacts;
}

/**
 * Import contacts from parsed CSV data
 * All contacts auto opt-in to WhatsApp by default
 */
export async function importContacts ( contacts: Partial<Contact>[] ): Promise<ImportResult> {
  const result: ImportResult = {
    total: contacts.length,
    created: 0,
    updated: 0,
    failed: 0,
    errors: [],
  };

  // Fix #1: Fetch existing contacts ONCE before the loop instead of per-contact
  let existing: Contact[] = [];
  try
  {
    existing = await listContacts();
  } catch
  {
    // If we can't fetch, proceed without dedup — backend will catch duplicates
  }

  // Build a phone lookup map for O(1) dedup
  const phoneMap = new Map<string, Contact>();
  for ( const c of existing )
  {
    if ( c.phone ) phoneMap.set( c.phone, c );
  }

  // Process in batches of 5 for some parallelism without overwhelming the API
  const BATCH_SIZE = 5;
  for ( let i = 0; i < contacts.length; i += BATCH_SIZE )
  {
    const batch = contacts.slice( i, i + BATCH_SIZE );
    const promises = batch.map( async ( contact ) => {
      try
      {
        const contactWithOptIn = {
          ...contact,
          optInWhatsApp: true,
          allowlistWhatsApp: true,
        };

        const found = contact.phone ? phoneMap.get( contact.phone ) : undefined;

        if ( found )
        {
          const updated = await updateContact( found.contactId, contactWithOptIn );
          if ( updated )
          {
            result.updated++;
          } else
          {
            result.failed++;
            result.errors.push( `Failed to update: ${contact.phone}` );
          }
        } else
        {
          const created = await createContact( contactWithOptIn );
          if ( created )
          {
            result.created++;
          } else
          {
            result.failed++;
            result.errors.push( `Failed to create: ${contact.phone}` );
          }
        }
      } catch ( err: any )
      {
        result.failed++;
        result.errors.push( `Error with ${contact.phone}: ${err.message}` );
      }
    } );
    await Promise.all( promises );
  }

  return result;
}

// ============================================================================
// AUTO-REPLY PER CONTACT
// ============================================================================

/**
 * Get auto-reply setting for a contact
 */
export function getContactAutoReply ( contactId: string ): boolean {
  const stored = localStorage.getItem( `autoReply_${contactId}` );
  return stored === 'true';
}

/**
 * Set auto-reply setting for a contact
 */
export function setContactAutoReply ( contactId: string, enabled: boolean ): void {
  localStorage.setItem( `autoReply_${contactId}`, String( enabled ) );
}

/**
 * Get all contacts with auto-reply enabled
 */
export function getAutoReplyContacts (): string[] {
  const contacts: string[] = [];
  for ( let i = 0; i < localStorage.length; i++ )
  {
    const key = localStorage.key( i );
    if ( key?.startsWith( 'autoReply_' ) && localStorage.getItem( key ) === 'true' )
    {
      contacts.push( key.replace( 'autoReply_', '' ) );
    }
  }
  return contacts;
}

// ============================================================================
// AI FEEDBACK
// ============================================================================

export interface AIFeedback {
  interactionId: string;
  messageId: string;
  rating: 'good' | 'bad';
  comment?: string;
  timestamp: number;
}

/**
 * Submit feedback for an AI response
 */
export function submitAIFeedback ( feedback: Omit<AIFeedback, 'timestamp'> ): void {
  const stored = localStorage.getItem( 'aiFeedback' );
  const feedbacks: AIFeedback[] = stored ? JSON.parse( stored ) : [];
  feedbacks.push( { ...feedback, timestamp: Date.now() } );
  localStorage.setItem( 'aiFeedback', JSON.stringify( feedbacks ) );
}

/**
 * Get AI feedback history
 */
export function getAIFeedbackHistory (): AIFeedback[] {
  const stored = localStorage.getItem( 'aiFeedback' );
  return stored ? JSON.parse( stored ) : [];
}

// ============================================================================
// SYSTEM CONFIG
// ============================================================================

export interface SystemConfig {
  [ key: string ]: any;
}

/**
 * Get system configuration by key
 * Lambda: wecare-ai-config-management
 */
export async function getSystemConfig ( configKey: string ): Promise<SystemConfig | null> {
  const data = await apiCall<any>( `${API_BASE}/ai/config?key=${encodeURIComponent( configKey )}`, {cache:'no-store'} );
  if ( data && data.config )
  {
    return data.config;
  }
  return null;
}

/** Distinguish a missing setting from a failed read before offering an editor. */
export async function getSystemConfigResult ( configKey: string ): Promise<ApiResult<{ config: SystemConfig | null }>> {
  return apiCallResult<{ config: SystemConfig | null }>( `${API_BASE}/ai/config?key=${encodeURIComponent( configKey )}`, {cache:'no-store'} );
}

// The backend merges object settings, so retained keys are allowed. Arrays are
// ordered values: a different element or length means the requested save is unconfirmed.
function containsConfig ( stored: any, requested: any ): boolean {
  if ( Array.isArray( requested ) )
    return Array.isArray( stored ) && stored.length === requested.length
      && requested.every( ( value, index ) => containsConfig( stored[ index ], value ) );
  if ( requested !== null && typeof requested === 'object' )
    return stored !== null && typeof stored === 'object' && !Array.isArray( stored )
      && Object.keys( requested ).every( key => Object.prototype.hasOwnProperty.call( stored, key )
        && containsConfig( stored[ key ], requested[ key ] ) );
  return stored === requested;
}

/**
 * Update system configuration
 * Lambda: wecare-ai-config-management
 */
export async function updateSystemConfig ( configKey: string, config: any ): Promise<boolean> {
  const body = JSON.stringify( { key: configKey, config } );
  const data = await apiCall<any>( `${API_BASE}/ai/config`, { method: 'PUT', body } );
  if ( data?.success !== true ) return false;
  const stored = await getSystemConfig( configKey );
  return stored !== null && containsConfig( stored, JSON.parse( body ).config );
}

/**
 * Push ice breakers + slash commands to Meta Conversational Automation API
 * via the WABA management Lambda.
 */
export async function pushConversationalComponents ( payload: { prompts: string[]; commands: { command_name: string; command_description: string }[] } ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/waba/conversational-components`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
  return data !== null && !data?.error;
}


// ============================================================================
// WHATSAPP BUSINESS API (Profile, Flows, Webhooks, Groups)
// ============================================================================


// Business Profile
export async function getBusinessProfile ( phoneId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/profile?phoneId=${phoneId}` );
  return data?.profile || null;
}

export async function updateBusinessProfile ( phoneId: string, updates: Record<string, any> ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/profile`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...updates } ),
  } );
  return data?.success === true;
}

// Payment Gateway Check
export interface GatewayConfig {
  name: string;
  status: string;
  gateway: string;
  mid: string;
  mcc: string;
  purposeCode: string;
  canReceivePayments: boolean;
  note?: string;
}

export interface GatewayCheckResult {
  wabaId: string;
  phone: string;
  configurations: GatewayConfig[];
  totalConfigs: number;
  activeConfigs: number;
}

export async function checkPaymentGateways ( wabaId?: string ): Promise<GatewayCheckResult[]> {
  const url = wabaId
    ? `${WA_BIZ_BASE}/payment-config/check?wabaId=${wabaId}`
    : `${WA_BIZ_BASE}/payment-config/check`;
  const data = await apiCall<any>( url );
  return data?.gatewayChecks || [];
}

// ── Username Management ──

export interface UsernameInfo {
  username?: string;
  status?: string;
}

export interface UsernameSuggestions {
  suggestions: string[];
}

export async function getBusinessUsername ( phoneId: string ): Promise<UsernameInfo | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/username?phoneId=${phoneId}` );
  if ( data?.error ) return { username: undefined, status: data.error.message || 'error' };
  return data || null;
}

export async function getBusinessUsernameSuggestions ( phoneId: string ): Promise<UsernameSuggestions | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/username/suggestions?phoneId=${phoneId}` );
  if ( data?.error ) return { suggestions: [] };
  return data || { suggestions: [] };
}

export async function claimBusinessUsername ( phoneId: string, username: string, opts?: { transferAction?: 'none' | 'force_transfer'; autoForceTransfer?: boolean } ): Promise<{ success: boolean; username?: string; transferAction?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/username`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, username, transferAction: opts?.transferAction || 'none', autoForceTransfer: opts?.autoForceTransfer || false } ),
  } );
  if ( data?.error ) return { success: false, error: data.error.message || data.error.details || data.hint || 'Failed to claim username' };
  return { success: true, username: data?.username, transferAction: data?.transferAction };
}

export async function deleteBusinessUsername ( phoneId: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/username?phoneId=${phoneId}`, {
    method: 'DELETE',
  } );
  if ( data?.error ) return { success: false, error: data.error.message || 'Failed to delete username' };
  return { success: data?.success === true };
}

// Flows
export async function listFlows ( wabaId: string ): Promise<any[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows?wabaId=${wabaId}` );
  if ( !data ) return [];
  if ( data.error ) throw new Error( data.error?.message || 'Failed to fetch flows' );
  return data?.flows || [];
}

export async function getFlow ( flowId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows?flowId=${flowId}` );
  return data?.flow || null;
}

export async function createFlow ( wabaId: string, name: string, categories?: string[] ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, name, categories } ),
  } );
  return data?.flow || null;
}

export async function updateFlow ( flowId: string, updates: Record<string, any> ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows`, {
    method: 'PUT',
    body: JSON.stringify( { flowId, ...updates } ),
  } );
  return data?.success === true;
}

export async function deleteFlow ( flowId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows?flowId=${flowId}`, { method: 'DELETE' } );
  return data?.success === true;
}

export async function publishFlow ( flowId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/publish`, {
    method: 'POST',
    body: JSON.stringify( { flowId } ),
  } );
  return data?.success === true;
}

export async function deprecateFlow ( flowId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/deprecate`, {
    method: 'POST',
    body: JSON.stringify( { flowId } ),
  } );
  return data?.success === true;
}

export async function getFlowPreview ( flowId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/preview`, {
    method: 'POST',
    body: JSON.stringify( { flowId } ),
  } );
  return data?.preview || null;
}

// Webhooks
export async function getWebhookSubscriptions ( wabaId: string ): Promise<any[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/webhooks?wabaId=${wabaId}` );
  return data?.subscriptions || [];
}

export async function subscribeWebhook ( wabaId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/webhooks`, {
    method: 'POST',
    body: JSON.stringify( { wabaId } ),
  } );
  return data?.success === true;
}

export async function unsubscribeWebhook ( wabaId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/webhooks?wabaId=${wabaId}`, { method: 'DELETE' } );
  return data?.success === true;
}

// Subscribe the app to specific webhook fields (e.g. business_username_updates, user_id_update).
export async function subscribeWebhookFields ( wabaId: string, fields: string[] ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/webhooks`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, subscribed_fields: fields } ),
  } );
  if ( data?.error ) return { success: false, error: data.error.message || 'Subscribe failed' };
  return { success: data?.success === true };
}

// ── BSUID: Contact Book + Parent BSUID accounts ──
export async function deleteContactBookEntry ( phoneId: string, bsuid: string ): Promise<{ success?: boolean; deleted?: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/contact-book?phoneId=${phoneId}&bsuid=${encodeURIComponent( bsuid )}`, { method: 'DELETE' } );
  if ( data?.error ) return { success: false, error: data.error.message || 'Delete failed' };
  return { success: data?.success, deleted: data?.deleted };
}

export async function getParentBsuidAccounts ( businessId: string ): Promise<{ parentBsuidAccountId?: string; enrolledBusinessPortfolios?: string[]; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/parent-bsuid-accounts?businessId=${businessId}` );
  if ( data?.error ) return { error: data.error.message || 'Failed to fetch parent BSUID accounts' };
  return { parentBsuidAccountId: data?.parentBsuidAccountId, enrolledBusinessPortfolios: data?.enrolledBusinessPortfolios };
}

// Groups
export async function listGroups ( wabaId: string, phoneId?: string ): Promise<any[]> {
  const params = new URLSearchParams( { wabaId } );
  if ( phoneId ) params.set( 'phoneId', phoneId );
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups?${params.toString()}` );
  return data?.groups || [];
}

export async function getGroup ( groupId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups?groupId=${groupId}` );
  return data?.group || null;
}

export async function createGroup ( phoneId: string, subject: string, description?: string, participants?: string[], join_approval_mode?: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, subject, description, participants, join_approval_mode } ),
  } );
  return data?.group || null;
}

export async function updateGroup ( groupId: string, updates: Record<string, any> ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups`, {
    method: 'PUT',
    body: JSON.stringify( { groupId, ...updates } ),
  } );
  return data?.success === true;
}

export async function deleteGroup ( groupId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups?groupId=${groupId}`, { method: 'DELETE' } );
  return data?.success === true;
}

export async function manageGroupParticipants ( groupId: string, participants: string[], action: 'add' | 'remove' ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/participants`, {
    method: 'POST',
    body: JSON.stringify( { groupId, participants, action } ),
  } );
  return data?.success === true;
}

export async function sendGroupMessage ( phoneId: string, groupId: string, content: string, options?: {
  type?: 'text' | 'image' | 'video' | 'document' | 'audio' | 'template';
  mediaUrl?: string; mediaId?: string; caption?: string; filename?: string;
  templateName?: string; templateLanguage?: string; templateComponents?: any[];
} ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/send`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, groupId, content, ...options } ),
  } );
  return data;
}


// ============================================================================
// PART 4 — TTL, Template validation, Media, Send-test, Flow admin
// ============================================================================

// ── Template TTL ──
export interface TtlCategoryRule {
  minSeconds: number; maxSeconds: number; minHuman: string; maxHuman: string;
  allowNeg1: boolean; neg1Meaning: string | null; description: string; recommendation?: string;
}
export interface TtlRules {
  field: string; categories: Record<string, TtlCategoryRule>; notes: string[];
}
export interface TtlValidationResult {
  ok: boolean; error: string | null; warnings: string[];
  category: string; seconds: number | null; human: string | null;
}

export async function getTemplateTtlRules (): Promise<TtlRules | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/template-ttl/rules` );
  return data?.rules || null;
}

export async function validateTemplateTtl ( category: string, ttl: number ): Promise<TtlValidationResult | null> {
  return apiCall<TtlValidationResult>( `${WA_BIZ_BASE}/template-ttl/validate`, {
    method: 'POST',
    body: JSON.stringify( { category, ttl } ),
  } );
}

export async function updateTemplateTtl ( templateId: string, ttl: number, wabaId?: string ): Promise<{ success?: boolean; error?: string; warning?: string; human?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/templates/${templateId}/ttl`, {
    method: 'POST',
    body: JSON.stringify( { ttl, wabaId } ),
  } );
  return data || { success: false, error: 'No response' };
}

// ── Template validation / send-test / refresh (template-management lambda) ──
const WA_TPL_BASE = `${API_BASE}/whatsapp/templates`;

export interface TemplateValidationResult { ok: boolean; errors: string[]; warnings: string[]; }

export async function validateTemplateDefinition ( templateDefinition: any ): Promise<TemplateValidationResult | null> {
  return apiCall<TemplateValidationResult>( `${WA_TPL_BASE}/validate`, {
    method: 'POST',
    body: JSON.stringify( { templateDefinition } ),
  } );
}


export async function sendTestTemplateMessage ( templateId: string, to: string, opts?: { templateName?: string; language?: string; components?: any[]; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_TPL_BASE}/${templateId}/send-test`, {
    method: 'POST',
    body: JSON.stringify( { to, ...opts } ),
  } );
  return data || { success: false, error: 'No response' };
}

export async function refreshTemplate ( templateId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_TPL_BASE}/${templateId}/refresh`, { method: 'POST' } );
  return data?.template || null;
}

// ── Media ──
export interface WaMediaInfo {
  mediaId: string; mimeType: string; fileSize: number; sha256?: string;
  url?: string; urlExpiresAt?: number; urlExpiresInSeconds?: number;
  s3Key?: string; downloadUrl?: string;
}

export async function uploadWaMedia ( opts: { phoneId?: string; fileData?: string; s3Key?: string; contentType?: string; filename?: string } ): Promise<{ mediaId?: string; error?: string; size?: number }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/media`, {
    method: 'POST',
    body: JSON.stringify( opts ),
  } );
  return data || { error: 'No response' };
}

export async function getWaMedia ( mediaId: string, opts?: { phoneId?: string; download?: boolean } ): Promise<WaMediaInfo | null> {
  const params = new URLSearchParams();
  if ( opts?.phoneId ) params.set( 'phoneId', opts.phoneId );
  if ( opts?.download ) params.set( 'download', 'true' );
  const qs = params.toString();
  return apiCall<WaMediaInfo>( `${WA_BIZ_BASE}/media/${mediaId}${qs ? `?${qs}` : ''}` );
}

export async function deleteWaMedia ( mediaId: string, phoneId?: string ): Promise<boolean> {
  const qs = phoneId ? `?phoneId=${phoneId}` : '';
  const data = await apiCall<any>( `${WA_BIZ_BASE}/media/${mediaId}${qs}`, { method: 'DELETE' } );
  return data?.success === true;
}

export async function startResumableMediaSession ( fileName: string, fileType: string, fileLength: number ): Promise<{ sessionId?: string; received?: number; fileLength?: number; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/media/resumable/session`, {
    method: 'POST',
    body: JSON.stringify( { fileName, fileType, fileLength } ),
  } );
  return data || { error: 'No response' };
}

export async function uploadResumableChunk ( sessionId: string, dataB64: string ): Promise<{ received?: number; fileLength?: number; complete?: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/media/resumable/${sessionId}/chunk`, {
    method: 'POST',
    body: JSON.stringify( { data: dataB64 } ),
  } );
  return data || { error: 'No response' };
}

export async function finishResumableMedia ( sessionId: string, opts?: { target?: 'handle' | 'media'; phoneId?: string } ): Promise<{ headerHandle?: string; mediaId?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/media/resumable/${sessionId}/finish`, {
    method: 'POST',
    body: JSON.stringify( opts || {} ),
  } );
  return data || { error: 'No response' };
}

// ── Send test messages ──
const WA_SEND_BASE = `${WA_BIZ_BASE}/messages/send`;

export async function sendTestText ( to: string, text: string, opts?: { phoneId?: string; previewUrl?: boolean } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/text`, { method: 'POST', body: JSON.stringify( { to, text, ...opts } ) } ) as any;
}

export async function sendTestTemplate ( to: string, templateName: string, opts?: { language?: string; components?: any[]; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/template`, { method: 'POST', body: JSON.stringify( { to, templateName, ...opts } ) } ) as any;
}

export async function sendTestMedia ( to: string, mediaType: 'image' | 'video' | 'document' | 'audio' | 'sticker', opts: { mediaId?: string; mediaUrl?: string; caption?: string; filename?: string; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/media`, { method: 'POST', body: JSON.stringify( { to, mediaType, ...opts } ) } ) as any;
}


export async function sendTestContacts ( to: string, contacts: any[], phoneId?: string ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/contacts`, { method: 'POST', body: JSON.stringify( { to, contacts, phoneId } ) } ) as any;
}

export async function sendTestLocation ( to: string, latitude: number, longitude: number, opts?: { name?: string; address?: string; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/location`, { method: 'POST', body: JSON.stringify( { to, latitude, longitude, ...opts } ) } ) as any;
}


// ── Flow admin (assets / migrate / sync) ──
export async function uploadFlowAsset ( flowId: string, flowJson: any, opts?: { assetType?: string; name?: string; wabaId?: string } ): Promise<{ success?: boolean; validationErrors?: any[]; hasErrors?: boolean; error?: any }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/assets?flowId=${flowId}`, {
    method: 'POST',
    body: JSON.stringify( { flowId, flowJson, ...opts } ),
  } );
  return data || { error: 'No response' };
}

export async function migrateFlows ( sourceWabaId: string, destWabaId: string, opts?: { sourceFlowNames?: string[]; migrationBatchId?: string } ): Promise<{ migratedFlows?: any[]; failedFlows?: any[]; migrationBatchId?: string; error?: any }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/migrate`, {
    method: 'POST',
    body: JSON.stringify( { sourceWabaId, destWabaId, ...opts } ),
  } );
  return data || { error: 'No response' };
}

export async function syncFlows ( wabaId: string ): Promise<{ success?: boolean; synced?: number; total?: number; error?: any }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flows/sync?wabaId=${wabaId}`, {
    method: 'POST',
    body: JSON.stringify( { wabaId } ),
  } );
  return data || { error: 'No response' };
}

// ── Cost-control feature flags ──
export interface CostFlagMeta { risk: 'low' | 'medium' | 'high'; service: string; }
export interface CostFlagsResponse { flags: Record<string, boolean>; meta: Record<string, CostFlagMeta>; }

export async function getCostFlags (): Promise<CostFlagsResponse | null> {
  return apiCall<CostFlagsResponse>( `${WA_BIZ_BASE}/cost-flags` );
}

export async function updateGroupSettings ( groupId: string, settings: {
  subject?: string; description?: string;
  messaging_permission?: 'all' | 'admins';
  member_visibility?: 'all' | 'admins';
  join_approval_mode?: 'auto_approve' | 'approval_required';
} ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups`, {
    method: 'PUT',
    body: JSON.stringify( { groupId, ...settings } ),
  } );
  return data?.success === true;
}

export async function setGroupImage ( groupId: string, imageUrl: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/image`, {
    method: 'POST',
    body: JSON.stringify( { groupId, imageUrl } ),
  } );
  return data?.success === true;
}

export async function getGroupInviteLink ( groupId: string ): Promise<string> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/invite-link?groupId=${groupId}` );
  return data?.invite_link || '';
}

export async function resetGroupInviteLink ( groupId: string ): Promise<string> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/invite-link`, {
    method: 'POST',
    body: JSON.stringify( { groupId } ),
  } );
  return data?.invite_link || '';
}

export async function getGroupJoinRequests ( groupId: string ): Promise<any[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/groups/join-requests?groupId=${groupId}` );
  return data?.join_requests || [];
}

export async function approveGroupJoinRequests ( groupId: string, joinRequestIds: string[] ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/groups/join-requests`, {
    method: 'POST',
    body: JSON.stringify( { groupId, join_requests: joinRequestIds } ),
  } );
}

export async function rejectGroupJoinRequests ( groupId: string, joinRequestIds: string[] ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/groups/join-requests`, {
    method: 'DELETE',
    body: JSON.stringify( { groupId, join_requests: joinRequestIds } ),
  } );
}

// Phone Settings
export async function getPhoneSettings ( phoneId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/phone-settings?phoneId=${phoneId}` );
  return data?.settings || null;
}


export interface WhatsAppFlowEncryptionStatus {
  phoneId: string;
  configured: boolean;
  signatureStatus: string;
}

export async function getWhatsAppFlowEncryptionStatus ( phoneId: string ): Promise<WhatsAppFlowEncryptionStatus | null> {
  return apiCall<WhatsAppFlowEncryptionStatus>(
    `${API_BASE}/wa-business/flow-encryption-status?phoneId=${encodeURIComponent( phoneId )}`
  );
}

export interface WhatsAppPreverifiedNumber {
  id?: string;
  display_phone_number?: string;
  country_prefix?: string;
  verification_status?: string;
  availability_status?: string;
  country_code?: string;
  region?: string;
}

export async function listWhatsAppPreverifiedNumbers (
  businessId: string,
  options: { countryCode?: string; verificationStatus?: string; availabilityStatus?: string; limit?: number } = {},
): Promise<WhatsAppPreverifiedNumber[]> {
  const qs = new URLSearchParams( { businessId } );
  if ( options.countryCode ) qs.set( 'countryCode', options.countryCode );
  if ( options.verificationStatus ) qs.set( 'verificationStatus', options.verificationStatus );
  if ( options.availabilityStatus ) qs.set( 'availabilityStatus', options.availabilityStatus );
  if ( options.limit ) qs.set( 'limit', String( options.limit ) );
  const data = await apiCall<any>( `${API_BASE}/wa-business/preverified-numbers?${qs.toString()}` );
  return Array.isArray( data?.numbers ) ? data.numbers : [];
}

// Official Business Account status, rolled up per WABA. READ-ONLY: the green tick is
// granted by a Meta review started in Business Suite and there is no API to request it.
// The rollup is four-valued — UNKNOWN is not NOT_OFFICIAL.
// Returns null until GET /wa-business/oba-status exists (deploy-time work), which is why
// the dashboard row renders "unavailable" rather than throwing.
export interface ObaPhone {
  phoneId: string;
  displayPhoneNumber: string;
  verifiedName: string;
  qualityRating: string;
  codeVerificationStatus: string;
  nameStatus: string;
  isOfficialBusinessAccount: boolean;
}
export interface ObaStatus {
  wabaId: string;
  obaStatus: 'OFFICIAL' | 'PARTIAL' | 'NOT_OFFICIAL' | 'UNKNOWN';
  phones: ObaPhone[];
  note?: string;
}

export async function getObaStatus ( wabaId: string ): Promise<ObaStatus | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/oba-status?wabaId=${encodeURIComponent( wabaId )}` );
  if ( !data?.obaStatus ) return null;
  return { wabaId: data.wabaId || wabaId, obaStatus: data.obaStatus, phones: data.phones || [], note: data.note || '' };
}

export async function updatePhoneSettings ( phoneId: string, settings: Record<string, any> ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/phone-settings`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...settings } ),
  } );
  return data?.success === true;
}

// Block Users API (per Meta BSUID docs — block/unblock by phone or BSUID)
export interface BlockUser {
  phone?: string;
  user_id?: string; // BSUID
}

export async function blockUsers ( wabaId: string, users: BlockUser[] ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/block-users`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, users } ),
  } );
}

export async function unblockUsers ( wabaId: string, users: BlockUser[] ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/unblock-users`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, users } ),
  } );
}

export async function getBlockedUsers ( wabaId: string ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/block-users?wabaId=${wabaId}` );
}


// Calling Settings (Enable/Disable calling on phone number)
export async function getCallingSettings ( phoneId: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/calling-settings?phoneId=${phoneId}` );
  return data?.settings || null;
}

export async function updateCallingSettings ( phoneId: string, settings: {
  callIconVisibility?: 'default' | 'disable_all';
  restrictToCountries?: string[];
  callIcons?: string[] | { restrict_to_user_countries: string[] };
  audioCodecs?: Array<'PCMA' | 'PCMU'>;
  callHours?: Record<string, any>;
  voicemail?: Record<string, any>;
  callbackRequest?: { enabled: boolean; bodyText?: string };
  sip?: { status: 'ENABLED' | 'DISABLED'; servers?: Array<{ hostname: string; port?: string; request_uri_user_params?: Record<string, string> }> };
  srtpKeyExchangeProtocol?: 'DTLS' | 'SDES';
  status?: 'ENABLED' | 'DISABLED';
  callbackPermissionStatus?: 'ENABLED' | 'DISABLED';
} ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/calling-settings`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...settings } ),
  } );
  return data?.success === true;
}

