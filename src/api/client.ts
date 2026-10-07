/**
 * API Service Layer
 * Connects to API Gateway -> Lambda -> DynamoDB
 * NO MOCK DATA - All data fetched from real AWS resources
 * 
 * API Endpoint: Uses NEXT_PUBLIC_API_BASE or defaults to production
 */

import { API_BASE, RETRY_CONFIG, DEFAULT_GSTIN } from '../config/constants';
import { fetchAuthSession } from 'aws-amplify/auth';
import { validateWaMediaSize } from '../lib/wa-media';

// Connection status tracking
let lastConnectionError: string | null = null;
let connectionStatus: 'connected' | 'disconnected' | 'unknown' = 'unknown';

export function getConnectionStatus () {
  return { status: connectionStatus, lastError: lastConnectionError };
}

/* ------------------------------------------------------------------------- *
 * Structured failure channel
 *
 * Every wrapper below collapses a failed request to `null` (or to `[]`, for the
 * list wrappers). That is convenient for callers but it destroys information:
 * an expired session, an 8s timeout and a genuinely empty table all arrive at
 * the UI as "nothing". A page cannot then choose between "Sign in again",
 * "Retry" and "No messages yet", so it shows the emptiest of the three — which
 * is how a stuck channel filter on [retired public path]/inbox looked exactly like an outage.
 *
 * `apiCall` keeps its old shape so the ~300 wrappers are untouched. The failure
 * is additionally recorded here, and `apiCallResult` / `collectApiFailures`
 * expose it to any caller that wants to tell the cases apart.
 * ------------------------------------------------------------------------- */

export type ApiFailureKind =
  /** 401 that survived a token refresh — the session is gone. */
  | 'unauthenticated'
  /** 403 — authenticated but not permitted (e.g. not in the Admin group). */
  | 'forbidden'
  /** 404 — the route itself is not deployed. */
  | 'not-found'
  /** 500 — the handler raised. */
  | 'server'
  /** 502/503 — API Gateway could not reach a healthy integration. */
  | 'unavailable'
  /** 504, or our own 8s AbortController firing. */
  | 'timeout'
  /** 429 — throttled, and the retries were exhausted. */
  | 'rate-limited'
  /** Request never produced a response: CORS, DNS, offline. */
  | 'network'
  /** Any other non-2xx status. */
  | 'http';

export interface ApiFailure {
  kind: ApiFailureKind;
  /** HTTP status, or `null` when the request never got a response at all. */
  status: number | null;
  /** Human-readable, safe to render. Never contains a token or a secret. */
  message: string;
  url: string;
  /** True when trying the same call again could plausibly succeed. */
  retryable: boolean;
  at: number;
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; failure: ApiFailure };

const RETRYABLE_KINDS: ReadonlySet<ApiFailureKind> = new Set<ApiFailureKind>( [
  'server', 'unavailable', 'timeout', 'rate-limited', 'network',
] );

let lastApiFailure: ApiFailure | null = null;
const failureListeners = new Set<( failure: ApiFailure ) => void>();

/** The most recent failure recorded by any call, or null since the last success. */
export function getLastApiFailure (): ApiFailure | null {
  return lastApiFailure;
}

function recordFailure ( kind: ApiFailureKind, status: number | null, message: string, url: string ): ApiFailure {
  const failure: ApiFailure = {
    kind,
    status,
    message,
    url,
    retryable: RETRYABLE_KINDS.has( kind ),
    at: Date.now(),
  };
  lastApiFailure = failure;
  connectionStatus = 'disconnected';
  lastConnectionError = message;
  failureListeners.forEach( listener => {
    try { listener( failure ); } catch { /* a broken listener must not fail the call */ }
  } );
  return failure;
}

/**
 * Run `load` and report any request failures it caused alongside its result.
 *
 * This is the escape hatch for the list wrappers, which return `[]` for both
 * "empty" and "broken". A page can now render an error instead of an empty
 * state:
 *
 *     const { data, failures } = await collectApiFailures( () => api.listMessages() );
 *     if ( !data.length && failures.length ) showError( failures[ 0 ] );
 *
 * Caveat, stated rather than hidden: the collector is module-scoped, so a call
 * started by some other component that fails inside this window is attributed
 * here too. It is scoped to one awaited load, which in practice is one page's
 * fetch, and it is strictly better than the `[]` it replaces. Use
 * `apiCallResult` directly where exactness matters.
 */
export async function collectApiFailures<T> ( load: () => Promise<T> ): Promise<{ data: T; failures: ApiFailure[] }> {
  const failures: ApiFailure[] = [];
  const listener = ( failure: ApiFailure ) => { failures.push( failure ); };
  failureListeners.add( listener );
  try
  {
    const data = await load();
    return { data, failures };
  } finally
  {
    failureListeners.delete( listener );
  }
}

// Helper function to delay with exponential backoff
function delay ( ms: number ): Promise<void> {
  return new Promise( resolve => setTimeout( resolve, ms ) );
}

// Get the current Cognito access token for API calls
async function getAuthToken (): Promise<string | null> {
  try
  {
    const session = await fetchAuthSession();
    return session.tokens?.accessToken?.toString() ?? null;
  } catch
  {
    return null;
  }
}

/**
 * Authenticated fetch — attaches the Cognito access token as a Bearer header.
 * Use on pages that make raw fetch() calls to protected API routes instead of
 * going through apiCall(). Unauthenticated/webhook routes simply ignore it.
 */
export async function authFetch ( input: string, init: RequestInit = {} ): Promise<Response> {
  const token = await getAuthToken();
  return fetch( input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...( init.headers as Record<string, string> || {} ),
      ...( token ? { Authorization: `Bearer ${token}` } : {} ),
    },
  } );
}

/** Verify the signed-in user has the Admin role through the live Cognito-backed API. */
export async function verifyAdminAccess (): Promise<boolean> {
  const response = await authFetch( `${API_BASE}/auth/validate`, {
    method: 'POST',
    body: JSON.stringify( { requiredRole: 'Admin' } ),
  } );
  return response.ok;
}

/**
 * Back-compat helper: an API call whose failure collapses to `null`.
 * Prefer `apiCallResult` in new code — it says *why* the call failed.
 */
async function apiCall<T> ( url: string, options?: RequestInit ): Promise<T | null> {
  const result = await apiCallResult<T>( url, options );
  return result.ok ? result.data : null;
}

/**
 * API call with retry logic that reports the reason a request failed.
 * Retries a 401 once with a refreshed token, and backs off on 429/502/503/504
 * and network errors up to `RETRY_CONFIG.maxRetries`.
 */
export async function apiCallResult<T> ( url: string, options?: RequestInit, retryCount = 0 ): Promise<ApiResult<T>> {
  try
  {
    const controller = new AbortController();
    const timeoutId = setTimeout( () => controller.abort(), 8000 ); // 8 second timeout

    // Inject Cognito auth token
    const token = await getAuthToken();
    const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    const response = await fetch( url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options?.headers,
      },
    } );

    clearTimeout( timeoutId );

    if ( response.ok )
    {
      connectionStatus = 'connected';
      lastConnectionError = null;
      lastApiFailure = null;
      return { ok: true, data: await response.json() as T };
    }

    // Handle specific HTTP errors
    let kind: ApiFailureKind = 'http';
    let message: string;

    if ( response.status === 401 )
    {
      // Token may have expired — try once with a fresh session
      if ( retryCount === 0 )
      {
        console.debug( 'Got 401, retrying with refreshed token...' );
        return apiCallResult<T>( url, options, retryCount + 1 );
      }
      kind = 'unauthenticated';
      message = 'Authentication failed - please sign in again';
    } else if ( response.status === 403 )
    {
      kind = 'forbidden';
      message = 'Access denied - check API Gateway permissions';
    } else if ( response.status === 404 )
    {
      kind = 'not-found';
      message = 'API endpoint not found';
    } else if ( response.status === 500 )
    {
      kind = 'server';
      message = 'Server error - check Lambda logs';
    } else if ( response.status === 502 || response.status === 503 || response.status === 504 )
    {
      kind = response.status === 504 ? 'timeout' : 'unavailable';
      message = response.status === 504 ? 'Lambda timeout - function took too long' : 'API Gateway error - service unavailable';
      // Retry on 502/503 errors
      if ( retryCount < RETRY_CONFIG.maxRetries )
      {
        const delayMs = Math.min(
          RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount ),
          RETRY_CONFIG.maxDelayMs
        );
        console.debug( `Retrying API call (${retryCount + 1}/${RETRY_CONFIG.maxRetries}) after ${delayMs}ms...` );
        await delay( delayMs );
        return apiCallResult<T>( url, options, retryCount + 1 );
      }
    } else if ( response.status === 429 )
    {
      // Rate limited - retry with backoff
      if ( retryCount < RETRY_CONFIG.maxRetries )
      {
        const delayMs = Math.min(
          RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount + 1 ),
          RETRY_CONFIG.maxDelayMs
        );
        console.debug( `Rate limited, retrying after ${delayMs}ms...` );
        await delay( delayMs );
        return apiCallResult<T>( url, options, retryCount + 1 );
      }
      kind = 'rate-limited';
      message = 'Rate limited - too many requests';
    } else
    {
      // Try to extract error message from response body
      try
      {
        const errBody = await response.json();
        const msg = errBody?.error?.message || errBody?.error || errBody?.message;
        message = msg ? `HTTP ${response.status}: ${msg}` : `HTTP ${response.status}: ${response.statusText}`;
      } catch
      {
        message = `HTTP ${response.status}: ${response.statusText}`;
      }
    }

    const failure = recordFailure( kind, response.status, message, url );
    console.error( `API error: ${failure.message}`, url );
    return { ok: false, failure };
  } catch ( e: any )
  {
    // Retry on network errors
    if ( retryCount < RETRY_CONFIG.maxRetries && ( e.name === 'AbortError' || e.name === 'TypeError' ) )
    {
      const delayMs = Math.min(
        RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount ),
        RETRY_CONFIG.maxDelayMs
      );
      console.debug( `Network error, retrying (${retryCount + 1}/${RETRY_CONFIG.maxRetries}) after ${delayMs}ms...` );
      await delay( delayMs );
      return apiCallResult<T>( url, options, retryCount + 1 );
    }

    let kind: ApiFailureKind;
    let message: string;
    if ( e.name === 'AbortError' )
    {
      kind = 'timeout';
      message = 'Request timeout - API took too long';
    } else if ( e.name === 'TypeError' )
    {
      kind = 'network';
      message = 'CORS error or network unavailable';
    } else
    {
      kind = 'network';
      message = e.message || 'Connection failed';
    }
    const failure = recordFailure( kind, null, message, url );
    console.error( 'API call failed:', failure.message, url, e );
    return { ok: false, failure };
  }
}

// Test API connection
export async function testConnection (): Promise<{ success: boolean; message: string; latency?: number }> {
  const start = Date.now();
  try
  {
    const token = await getAuthToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if ( token ) headers[ 'Authorization' ] = `Bearer ${token}`;

    const response = await fetch( `${API_BASE}/messages?limit=1`, { method: 'GET', headers } );
    const latency = Date.now() - start;

    if ( response.ok )
    {
      connectionStatus = 'connected';
      lastConnectionError = null;
      return { success: true, message: `Connected (${latency}ms)`, latency };
    }

    // A 401/403 means the API Gateway IS reachable — it responded, just needs a
    // valid token (auth is handled separately). Don't show "unreachable" for that.
    if ( response.status === 401 || response.status === 403 )
    {
      connectionStatus = 'connected';
      lastConnectionError = null;
      return { success: true, message: `Connected (${latency}ms, auth required)`, latency };
    }

    connectionStatus = 'disconnected';
    lastConnectionError = `HTTP ${response.status}`;
    return { success: false, message: `API returned ${response.status}: ${response.statusText}` };
  } catch ( e: any )
  {
    connectionStatus = 'disconnected';
    lastConnectionError = e.message;
    return { success: false, message: `Connection failed: ${e.message}` };
  }
}

// ============================================================================
// CONTACTS API
// ============================================================================

/**
 * The stored checkout delivery address. Mirrors what
 * `lambda_utils.ecommerce.contact_address.normalize_for_storage` returns, and every field is a
 * string there - `_text` coerces or drops, so a number never reaches storage.
 *
 * Every field is optional on the read side even though storage requires four of them: a row
 * written before a rule tightened must render rather than crash the panel.
 */
export interface CheckoutDeliveryAddress {
  addressLine1?: string;
  addressLine2?: string;
  locality?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  country?: string;
  countryCode?: string;
}

export interface Contact {
  id: string;
  contactId: string;
  name: string;
  firstName?: string;
  lastName?: string;
  phone: string;
  email?: string;
  phoneVerifiedAt?: string;
  emailVerifiedAt?: string;
  blogSubscribedAt?: string;
  // WhatsApp BSUID (Business-Scoped User ID) — unique per WABA portfolio
  bsuid?: string;
  // Parent BSUID (linked account)
  parentBsuid?: string;
  // WhatsApp username (e.g. "@pablomorales")
  username?: string;
  // Contact book name — auto-populated by Meta's contact book feature
  contactBookName?: string;
  shippingAddress?: string;
  billingAddress?: string;
  /**
   * The address the customer typed at checkout, written by `auth/customer-profile` through
   * `lambda_utils.ecommerce.contact_address` and READ-ONLY here. Structured, not a string, and
   * deliberately NOT merged into `shippingAddress`: the two answer different questions - this
   * one is what the customer gave for their own order, `shippingAddress` is what the business
   * curated - and collapsing them would let a checkout save overwrite a hand-typed CRM address.
   */
  checkoutDeliveryAddress?: CheckoutDeliveryAddress;
  /** Epoch seconds the checkout address was last written. */
  checkoutAddressUpdatedAt?: number;
  // Structured address JSON (Meta shipping_info format) — set by subscribe flow
  shippingAddressJson?: string;
  billingAddressJson?: string;
  // GSTIN for B2B invoicing
  gstin?: string;
  // Structured address fields for WhatsApp Payments shipping_info
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
  houseNumber?: string;
  buildingName?: string;
  towerNumber?: string;
  floorNumber?: string;
  // Country
  country?: string;
  pincode?: string;
  // Business/profile fields
  companyName?: string;
  designation?: string;
  preferredLanguage?: string;
  isPep?: boolean;
  pepDetails?: string;
  paidBy?: string; // self, company
  // Tracking fields (read-only, set by backend)
  lastFlowInteractionAt?: string;
  satisfactionScore?: number;
  welcomeSent?: boolean;
  welcomeSentAt?: string;
  // Opt-in fields (Requirement 3.2)
  optInWhatsApp: boolean;
  optInSms: boolean;
  optInEmail: boolean;
  // Allowlist fields (Requirement 3.2)
  allowlistWhatsApp: boolean;
  allowlistSms: boolean;
  allowlistEmail: boolean;
  lastInboundMessageAt?: string;
  tags?: string[];
  createdAt: string;
  updatedAt: string;
  deletedAt?: string;
}

export async function listContacts (): Promise<Contact[]> {
  const data = await apiCall<any>( `${API_BASE}/contacts` );
  if ( data )
  {
    const contacts = Array.isArray( data ) ? data : ( data.contacts || [] );
    return contacts.map( normalizeContact );
  }
  return [];
}

export async function getContact ( contactId: string ): Promise<Contact | null> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}` );
  if ( data )
  {
    return normalizeContact( data.contact || data );
  }
  return null;
}

export async function createContact ( contact: Partial<Contact> ): Promise<Contact | null> {
  const data = await apiCall<any>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( contact ),
  } );
  if ( data )
  {
    return normalizeContact( data.contact || data );
  }
  return null;
}

/**
 * A contact update that says WHY it failed.
 *
 * `contacts/handler.py` refuses some inputs on purpose - a phone carrying no dial code is a
 * 400 `PHONE_COUNTRY_CODE_REQUIRED` rather than a guessed `+91` - so the reason for a refusal
 * is information the operator needs. `updateContact` below collapses every one of those to
 * `null`, which a caller cannot tell apart from a 503, and the CRM's inline cell editor
 * rendered that `null` as a silent no-op. Prefer this in new code; `updateContact` stays for
 * the callers that only branch on success.
 */
export async function updateContactResult ( contactId: string, updates: Partial<Contact> ): Promise<ApiResult<Contact | null>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts/${contactId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  if ( !result.ok )
  {
    return result;
  }
  // `data` is still guarded: a 2xx with an empty body normalises to null rather than throwing
  // inside `normalizeContact`, which is exactly what `updateContact` returned before.
  const data = result.data;
  return { ok: true, data: data ? normalizeContact( data.contact || data ) : null };
}

export async function updateContact ( contactId: string, updates: Partial<Contact> ): Promise<Contact | null> {
  const result = await updateContactResult( contactId, updates );
  return result.ok ? result.data : null;
}

export async function deleteContact ( contactId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}`, {
    method: 'DELETE',
  } );
  // Check if response indicates success (not an error)
  return data !== null && !data.error;
}

function normalizeContact ( item: any ): Contact {
  return {
    id: item.id || item.contactId || '',
    contactId: item.contactId || item.id || '',
    name: item.name || '',
    firstName: item.firstName || '',
    lastName: item.lastName || '',
    phone: item.phone || '',
    email: item.email || '',
    phoneVerifiedAt: normalizeTimestamp( item.phoneVerifiedAt ),
    emailVerifiedAt: normalizeTimestamp( item.emailVerifiedAt ),
    blogSubscribedAt: normalizeTimestamp( item.blogSubscribedAt ),
    bsuid: item.bsuid || '',
    username: item.username || '',
    contactBookName: item.contactBookName || '',
    shippingAddress: item.shippingAddress || '',
    billingAddress: item.billingAddress || '',
    /*
     * READ-ONLY, written by `auth/customer-profile`.
     *
     * This mapper is a CLOSED whitelist and the only way a contact reaches the UI
     * (`listContacts`, `getContact`, `createContact`, `updateContact` all funnel through it),
     * so an attribute the backend already returns stays `undefined` in the browser until it is
     * named HERE. That is not hypothetical: the first attempt at this fix added both fields to
     * the `Contact` interface only, and shipped a CRM column that rendered the em-dash for every
     * contact while `tsc` and the suite stayed green.
     *
     * Carried through WHOLE rather than rebuilt field by field. The stored map also holds
     * `fullAddress` (derived by `identity.address.normalize_address`), and a second closed
     * whitelist at this layer would be a second place to forget a field — the exact failure
     * mode this comment exists to record. Only the shape is checked; `formatCheckoutAddress`
     * coerces each part, because this is server data and a legacy row may hold a number or a
     * null where a string is expected.
     */
    checkoutDeliveryAddress: normalizeCheckoutAddress( item.checkoutDeliveryAddress ),
    // Epoch SECONDS, deliberately NOT through `normalizeTimestamp`: `Contact` types this as a
    // number, and the page's `timeAgo` already handles both epoch scales.
    checkoutAddressUpdatedAt: normalizeEpochSeconds( item.checkoutAddressUpdatedAt ),
    shippingAddressJson: item.shippingAddressJson || '',
    billingAddressJson: item.billingAddressJson || '',
    gstin: item.gstin || '',
    // Structured address fields
    addressLine1: item.addressLine1 || '',
    addressLine2: item.addressLine2 || '',
    city: item.city || '',
    state: item.state || '',
    postalCode: item.postalCode || '',
    landmark: item.landmark || '',
    houseNumber: item.houseNumber || '',
    buildingName: item.buildingName || '',
    towerNumber: item.towerNumber || '',
    floorNumber: item.floorNumber || '',
    country: item.country || '',
    pincode: item.pincode || item.postalCode || '',
    companyName: item.companyName || item.contactBookName || '',
    designation: item.designation || '',
    preferredLanguage: item.preferredLanguage || '',
    isPep: item.isPep || false,
    pepDetails: item.pepDetails || '',
    paidBy: item.paidBy || '',
    lastFlowInteractionAt: normalizeTimestamp( item.lastFlowInteractionAt ),
    satisfactionScore: item.satisfactionScore || undefined,
    welcomeSent: item.welcomeSent || false,
    welcomeSentAt: normalizeTimestamp( item.welcomeSentAt ),
    // Opt-in fields
    optInWhatsApp: item.optInWhatsApp || false,
    optInSms: item.optInSms || false,
    optInEmail: item.optInEmail || false,
    // Allowlist fields (Requirement 3.2)
    allowlistWhatsApp: item.allowlistWhatsApp || false,
    allowlistSms: item.allowlistSms || false,
    allowlistEmail: item.allowlistEmail || false,
    lastInboundMessageAt: normalizeTimestamp( item.lastInboundMessageAt ),
    tags: Array.isArray( item.tags ) ? item.tags : [],
    createdAt: normalizeTimestamp( item.createdAt ) || new Date().toISOString(),
    updatedAt: normalizeTimestamp( item.updatedAt ) || new Date().toISOString(),
    deletedAt: item.deletedAt,
  };
}

/**
 * The stored checkout delivery address, or `undefined` when there is nothing usable.
 *
 * Shape check only, then pass through. An array is rejected because `typeof [] === 'object'`
 * and an array would reach `formatCheckoutAddress` as a dict of numeric keys, rendering ''
 * rather than announcing the problem. An empty object collapses to `undefined` so the caller's
 * existing `value || '—'` renders the same dash every other empty field renders.
 */
function normalizeCheckoutAddress ( value: any ): CheckoutDeliveryAddress | undefined {
  if ( !value || typeof value !== 'object' || Array.isArray( value ) ) return undefined;
  return Object.keys( value ).length ? value as CheckoutDeliveryAddress : undefined;
}

/**
 * Epoch seconds as a number, or `undefined`.
 *
 * Guards the two values `Number()` quietly turns into a real timestamp: `Number(null)` is 0 and
 * `Number('')` is 0, either of which would render as 1 January 1970 instead of a dash.
 */
function normalizeEpochSeconds ( value: any ): number | undefined {
  if ( value === null || value === undefined || value === '' ) return undefined;
  const seconds = Number( value );
  return Number.isFinite( seconds ) && seconds > 0 ? seconds : undefined;
}

/**
 * Fix #8/#12: Safely convert epoch seconds OR ISO strings to ISO string.
 * Handles: epoch seconds (number), epoch string ("1709568000"), ISO string, undefined/null.
 */
function normalizeTimestamp ( value: any ): string | undefined {
  if ( !value && value !== 0 ) return undefined;
  // If it's a number or a string that looks like an epoch (all digits)
  const num = Number( value );
  if ( !isNaN( num ) && String( value ).match( /^\d+$/ ) )
  {
    // Epoch seconds are < 10 billion; epoch millis are > 10 billion
    const ms = num < 1e12 ? num * 1000 : num;
    const d = new Date( ms );
    if ( !isNaN( d.getTime() ) ) return d.toISOString();
  }
  // Try parsing as ISO string
  const d = new Date( String( value ) );
  if ( !isNaN( d.getTime() ) ) return d.toISOString();
  return undefined;
}

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
  senderPhone?: string;
  senderName?: string;
  senderBsuid?: string;
  senderUsername?: string;
  receivingPhone?: string;
  awsPhoneNumberId?: string;
  transcription?: string;       // English transcription of voice notes
  detectedLanguage?: string;    // Detected language of voice note (e.g. "hi-IN")
  contactsPayload?: WaContactCard[] | null;  // shared contact card(s), messageType=contacts
  // Call breadcrumb fields (channel=voice, messageType=call)
  callId?: string;
  callType?: string;            // plivo | aws | whatsapp; legacy rows may read 'airtel'
  duration?: number;            // seconds
  recordingUrl?: string;
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
    callId: item.callId,
    callType: item.callType,
    duration: typeof item.duration === 'number' ? item.duration : ( item.duration ? Number( item.duration ) : undefined ),
    recordingUrl: item.recordingUrl,
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
export { WA_MEDIA_LIMITS, waMediaCategory } from '../lib/wa-media';

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

// Click-to-call initiation was removed on 2026-09-19. It posted to an endpoint
// that dialled a retired India voice provider and now answers 410. PSTN voice is
// Plivo, and outbound calling arrives with the Plivo browser softphone behind
// PSTN_BROWSER_ROUTING_ENABLED. No replacement client function is added here yet,
// so nothing can call a dialler that does not exist.

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

// Interactive message types
export interface InteractiveListSection {
  title: string;
  rows: { id: string; title: string; description?: string }[];
}

export interface InteractiveButton {
  id: string;
  title: string;
}

export interface SendInteractiveRequest {
  contactId: string;
  phoneNumberId?: string;
  recipientBsuid?: string;    // Send to BSUID recipient
  interactiveType: 'list' | 'button' | 'location_request' | 'cta_url' | 'flow' | 'product' | 'product_list';
  interactiveData: {
    header?: string;
    headerType?: 'text' | 'image' | 'video' | 'document';
    headerMedia?: string;
    headerFilename?: string;
    body: string;
    footer?: string;
    buttonText?: string;  // For list messages, CTA URL, and Flow
    sections?: any[];  // List rows OR product_list sections ({ title, productItems: [{ productRetailerId }] })
    buttons?: InteractiveButton[];  // For button messages
    url?: string;  // For CTA URL messages
    // Catalog / product fields
    catalogId?: string;
    productRetailerId?: string;  // For single product messages
    // Flow-specific fields
    flowId?: string;
    flowCta?: string;
    flowAction?: 'navigate' | 'data_exchange';
    flowToken?: string;
    flowScreen?: string;  // Initial screen to display
    screenId?: string;
    flowData?: Record<string, any>;
  };
}

// Send interactive WhatsApp message (list, buttons, location request, CTA URL, flow)
export async function sendWhatsAppInteractive ( request: SendInteractiveRequest ): Promise<{ messageId: string; status: string; interactiveType: string } | null> {
  return apiCall<{ messageId: string; status: string; interactiveType: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( {
      contactId: request.contactId,
      phoneNumberId: request.phoneNumberId,
      recipientBsuid: request.recipientBsuid,
      isInteractive: true,
      interactiveType: request.interactiveType,
      interactiveData: request.interactiveData,
    } ),
  } );
}

/**
 * Send a WhatsApp catalog message — single product or a multi-product list.
 * Requires a configured WhatsApp product catalog (catalogId) and product retailer ids.
 */
export async function sendWhatsAppCatalogProduct ( request: {
  contactId: string;
  phoneNumberId?: string;
  catalogId: string;
  productRetailerId?: string;  // single product
  sections?: { title: string; productItems: { productRetailerId: string }[] }[];  // multi-product
  body?: string;
  header?: string;
  footer?: string;
} ): Promise<{ messageId: string; status: string } | null> {
  const multi = !!( request.sections && request.sections.length );
  return sendWhatsAppInteractive( {
    contactId: request.contactId,
    phoneNumberId: request.phoneNumberId,
    interactiveType: multi ? 'product_list' : 'product',
    interactiveData: {
      body: request.body || '',
      header: request.header,
      footer: request.footer,
      catalogId: request.catalogId,
      productRetailerId: request.productRetailerId,
      sections: request.sections,
    },
  } );
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

// ============================================================================
// AI AUTOMATION API
// ============================================================================

// Old AIConfig, getAIConfig(), updateAIConfig(), testAIResponse(), getAISuggestions() removed
// Use getBedrockAIConfig(), updateBedrockAIConfig(), testBedrockAIResponse() instead

// ============================================================================
// DASHBOARD STATS API
// ============================================================================

export interface DashboardStats {
  messagesToday: number;
  messagesWeek: number;
  activeContacts: number;
  bulkJobs: number;
  deliveryRate: number;
  aiResponses: number;
  dlqDepth: number;
}

export async function getDashboardStats (): Promise<DashboardStats> {
  // Use lightweight count-only endpoints to avoid fetching all records
  try
  {
    const [ msgStats, contactStats, bulkJobs ] = await Promise.all( [
      apiCall<any>( `${API_BASE}/messages?stats=count` ),
      apiCall<any>( `${API_BASE}/contacts?stats=count` ),
      listBulkJobs(),
    ] );

    const activeBulkJobs = bulkJobs.filter( j =>
      j.status === 'PENDING' || j.status === 'IN_PROGRESS'
    ).length;

    // Try to get DLQ depth
    let dlqDepth = 0;
    try
    {
      const dlqData = await apiCall<any>( `${API_BASE}/dlq` );
      dlqDepth = dlqData?.count ?? dlqData?.messages?.length ?? 0;
    } catch { /* non-critical */ }

    return {
      messagesToday: msgStats?.messagesToday ?? 0,
      messagesWeek: msgStats?.messagesWeek ?? 0,
      activeContacts: contactStats?.activeContacts ?? 0,
      bulkJobs: activeBulkJobs,
      deliveryRate: msgStats?.deliveryRate ?? 100,
      aiResponses: 0,
      dlqDepth,
    };
  } catch
  {
    // Fallback: return safe defaults on any error
    return {
      messagesToday: 0,
      messagesWeek: 0,
      activeContacts: 0,
      bulkJobs: 0,
      deliveryRate: 100,
      aiResponses: 0,
      dlqDepth: 0,
    };
  }
}

// ============================================================================
// SYSTEM HEALTH API
// ============================================================================

export interface SystemHealth {
  whatsapp: { status: 'active' | 'warning' | 'error'; phoneNumbers: number; qualityRating: string };
  sms: { status: 'active' | 'warning' | 'error'; poolId: string };
  email: { status: 'active' | 'warning' | 'error'; verified: boolean };
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
  dlq: { depth: number; oldestMessage?: string };
}

export async function getSystemHealth (): Promise<SystemHealth> {
  // Defaults (used as fallback if any call fails)
  const defaults: SystemHealth = {
    whatsapp: { status: 'active', phoneNumbers: 2, qualityRating: 'GREEN' },
    sms: { status: 'active', poolId: 'TBD' },
    email: { status: 'active', verified: true },
    ai: {
      status: 'active',
      internalKbId: 'static-faq',
      internalAgentId: '4UUQYFWX64',
      internalAgentAlias: 'TSTALIASID',
      externalKbId: 'static-faq',
      externalAgentId: '4UUQYFWX64',
      externalAgentAlias: 'TSTALIASID'
    },
    dlq: { depth: 0 },
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
      defaults.dlq.depth = dlqData.count ?? dlqData.messages?.length ?? 0;
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
      defaults.whatsapp.phoneNumbers = wabaData.wabas.reduce(
        ( sum: number, w: any ) => sum + ( w.phoneNumbers?.length ?? 0 ), 0
      ) || defaults.whatsapp.phoneNumbers;
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

/**
 * Providers that may appear when READING a voice record.
 *
 * The retired entry is present because calls really were placed that way before
 * 2026-09-19 and the records are retained as audit evidence. Reading it must stay
 * possible; selecting it must not.
 */
export type VoiceProviderRead = 'plivo' | 'aws' | 'airtel';

/**
 * Providers that may be SELECTED for a new call. PSTN voice is Plivo; 'aws' is
 * the AWS End User Messaging voice (TTS/audio) path.
 *
 * Retired providers are absent by design, so a retired-provider call is not
 * expressible in the type system rather than merely discouraged.
 */
export type VoiceProviderSelectable = 'plivo' | 'aws';

export interface VoiceCall {
  id: string;
  callId: string;
  contactId: string;
  phoneNumber: string;
  provider: VoiceProviderRead;
  callType: 'tts' | 'audio' | 'ivr' | 'click_to_call';
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
// which sends exclusively through AWS End User Messaging and refuses a request
// naming a prohibited provider with 422.
//
// Removed 2026-09-19: a provider-specific helper that forced a prohibited SMS
// provider and a hardcoded sender header on every call. It had no callers.
// Identifier omitted so the provider-policy scan stays precise.
// See docs/provider-retirement-inventory.md.

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
  return data?.templates || [];
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

  if ( data && data.services )
  {
    return {
      totalCost: data.totalCost || 0,
      period: data.period || `${new Date().toISOString().slice( 0, 7 )}-01 to ${new Date().toISOString().slice( 0, 10 )}`,
      services: data.services,
      lastUpdated: data.lastUpdated || new Date().toISOString(),
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

  // Fallback: Return cached/estimated data
  return getEstimatedBilling();
}

// Fallback function with estimated billing data
function getEstimatedBilling (): AWSBillingData {
  const now = new Date();
  const startOfMonth = new Date( now.getFullYear(), now.getMonth(), 1 );

  const services: AWSServiceUsage[] = [
    { service: 'Amazon Bedrock', cost: 0, usage: 61, unit: 'requests', freeLimit: '3-month trial', status: 'free' },
    { service: 'AWS Lambda', cost: 0, usage: 6709, unit: 'requests', freeLimit: '1M/month', status: 'free' },
    { service: 'Amazon DynamoDB', cost: 0, usage: 22977, unit: 'operations', freeLimit: '200M/month', status: 'free' },
    { service: 'Amazon S3', cost: 0, usage: 13186, unit: 'operations', freeLimit: '20K GET', status: 'free' },
    { service: 'Amazon API Gateway', cost: 0, usage: 5157, unit: 'requests', freeLimit: '1M/month', status: 'free' },
    { service: 'Amazon CloudFront', cost: 0, usage: 1981, unit: 'requests', freeLimit: '1TB/month', status: 'free' },
    { service: 'AWS Amplify', cost: 0, usage: 774, unit: 'minutes', freeLimit: '1000 mins/month', status: 'free' },
    { service: 'Amazon SNS', cost: 0, usage: 3387, unit: 'notifications', freeLimit: '1M/month', status: 'free' },
    { service: 'Amazon SQS', cost: 0, usage: 429, unit: 'requests', freeLimit: '1M/month', status: 'free' },
    { service: 'Meta WhatsApp Cloud API', cost: 0, usage: 381, unit: 'conversations', freeLimit: '1000 free/mo', status: 'free' },
    { service: 'AWS Pinpoint (SMS/Voice)', cost: 2, usage: 47, unit: 'messages/calls', freeLimit: '$2/mo toll-free', status: 'paid' },
    { service: 'Amazon Polly', cost: 0, usage: 12, unit: 'TTS requests', freeLimit: '5M chars/month', status: 'free' },
    { service: 'AWS Secrets Manager', cost: 0.40, usage: 1, unit: 'secrets', freeLimit: '$0.40/secret/mo', status: 'paid' },
    { service: 'Amazon OpenSearch', cost: 0, usage: 182, unit: 'operations', freeLimit: 'Serverless', status: 'free' },
    { service: 'Amazon Route 53', cost: 0, usage: 94671, unit: 'queries', freeLimit: '$0.50/zone', status: 'free' },
    { service: 'Amazon Cognito', cost: 0, usage: 1, unit: 'users', freeLimit: '50K MAU', status: 'free' },
    { service: 'CloudWatch', cost: 0, usage: 370, unit: 'metrics', freeLimit: '10 metrics', status: 'free' },
  ];

  return {
    totalCost: 2.40,
    period: `${startOfMonth.toISOString().slice( 0, 10 )} to ${now.toISOString().slice( 0, 10 )}`,
    services,
    lastUpdated: now.toISOString(),
  };
}


// ============================================================================
// ADVANCED DELETE OPERATIONS
// ============================================================================

/**
 * Hard Delete - Completely removes contact, all messages, and media from S3
 * This is irreversible!
 * 
 * Uses the backend ?hard=true parameter to trigger full deletion
 */
export async function hardDeleteContact ( contactId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}?hard=true`, {
    method: 'DELETE',
  } );

  if ( data && data.success )
  {
    return true;
  }

  // Fallback: delete messages one by one, then soft delete contact
  try
  {
    const messagesDeleted = await deleteContactMessages( contactId );
    const contactDeleted = await deleteContact( contactId );
    return contactDeleted;
  } catch ( error )
  {
    console.error( 'Hard delete fallback error:', error );
    return false;
  }
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


// ============================================================================
// WHATSAPP TEMPLATES API (Meta Graph API)
// ============================================================================

export interface WhatsAppTemplate {
  id: string;
  name: string;
  language: string;
  category: 'MARKETING' | 'UTILITY' | 'AUTHENTICATION';
  status: 'APPROVED' | 'PENDING' | 'REJECTED';
  components: TemplateComponent[];
}

export interface TemplateComponent {
  type: 'HEADER' | 'BODY' | 'FOOTER' | 'BUTTONS' | 'CAROUSEL';
  format?: 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT';
  text?: string;
  example?: { body_text?: string[][] };
  buttons?: { type: string; text: string; url?: string; phone_number?: string }[];
  cards?: any[];
}

// WABA IDs for template fetching
const WABA_IDS = {
  'WECARE.DIGITAL': 'waba-e47d916f3c7a47e1a34a19653893dd4b',
  'Manish Agarwal': 'waba-dbe343f210204752b74c80a0a59631a6',
};

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
    id: item.id || item.templateId || item.name || '',
    name: item.name || item.templateName || '',
    language: item.language || item.languageCode || 'en_US',
    category: ( item.category || 'UTILITY' ).toUpperCase() as 'MARKETING' | 'UTILITY' | 'AUTHENTICATION',
    status: ( item.status || 'APPROVED' ).toUpperCase() as 'APPROVED' | 'PENDING' | 'REJECTED',
    components: item.components || [],
  };
}


// ============================================================================
// AI CHAT API (for inbox editor)
// ============================================================================

/**
 * Generate AI response using Bedrock
 * Uses the external agent for customer-facing responses
 * 
 * API: POST /ai/generate
 * Lambda: wecare-ai-generate-response
 */
export async function generateAIResponse ( message: string, context?: {
  contactName?: string;
  channel?: string;
  conversationHistory?: string[];
} ): Promise<{ response: string; sources?: string[] }> {
  try
  {
    const data = await apiCall<any>( `${API_BASE}/ai/generate`, {
      method: 'POST',
      body: JSON.stringify( {
        messageContent: message,
        context: context?.channel || 'external',  // Use external agent for inbox
      } ),
    } );

    // Handle Lambda response format (body is JSON string)
    if ( data )
    {
      // If response has body field (Lambda proxy response)
      if ( data.body )
      {
        try
        {
          const parsed = typeof data.body === 'string' ? JSON.parse( data.body ) : data.body;
          if ( parsed.suggestion )
          {
            return { response: parsed.suggestion, sources: parsed.sources || [] };
          }
          if ( parsed.suggestedResponse )
          {
            return { response: parsed.suggestedResponse, sources: parsed.sources || [] };
          }
        } catch ( e )
        {
          console.error( 'Failed to parse AI response body:', e );
        }
      }

      // Direct response format
      if ( data.suggestion )
      {
        return { response: data.suggestion, sources: data.sources || [] };
      }
      if ( data.suggestedResponse )
      {
        return { response: data.suggestedResponse, sources: data.sources || [] };
      }
    }

    // Fallback response
    return {
      response: 'Thank you for your message. How can I assist you today?',
      sources: [],
    };
  } catch ( error )
  {
    console.error( 'AI generate error:', error );
    return {
      response: 'Thank you for reaching out. How can I help you?',
      sources: [],
    };
  }
}


// ============================================================================
// WHATSAPP PAYMENT MESSAGE API (Order Details Template)
// ============================================================================

export interface PaymentOrderItem {
  name: string;
  amount: number;  // In smallest currency unit (paise for INR)
  quantity: number;
  productId?: string;
  gstRate?: number;  // Per-item GST rate (0, 3, 5, 12, 18, 28)
}

export interface SendPaymentMessageRequest {
  contactId: string;
  phoneNumberId: string;
  recipientBsuid?: string;    // Send to BSUID recipient
  templateName?: string;
  referenceId: string;
  items: PaymentOrderItem[];
  discount?: number;      // In paise
  delivery?: number;      // In paise (shipping/delivery)
  tax?: number;           // In paise (total GST from all items)
  taxDescription?: string; // e.g., "GST 18%" or "Tax"
  gstin?: string;         // GSTIN number
  currency?: string;
  headerImageUrl?: string;
  bodyText?: string;
  useInteractive?: boolean;
  paymentConfiguration?: string;
  convenienceFee?: number; // In paise (2.2% + 18% GST)
  orderId?: string;       // Order ID (blank = Offline)
}

/**
 * Send WhatsApp Payment Message using order_details
 * 
 * Fields shown in WhatsApp message:
 * - Reference ID
 * - Items (name, amount, quantity)
 * - Discount (₹)
 * - Delivery (₹)
 * - Tax (₹) - passed from frontend
 * 
 * NOTE: Convenience Fee is handled by Razorpay Fee Bearer model (not in WhatsApp message)
 */
export async function sendWhatsAppPaymentMessage ( request: SendPaymentMessageRequest ): Promise<{ messageId: string; status: string } | null> {
  const subtotal = request.items.reduce( ( sum, item ) => sum + ( item.amount * item.quantity ), 0 );
  const discount = request.discount || 0;
  const delivery = request.delivery || 0;
  const tax = request.tax || 0;

  // Build order_details payload — always physical-goods for checkout template (address + coupons)
  const orderDetails: any = {
    reference_id: request.referenceId,
    type: 'physical-goods',
    payment_configuration: request.paymentConfiguration || 'WECAREDIGITAL',
    currency: request.currency || 'INR',
    itemName: request.items[ 0 ]?.name || 'Service Fee',
    quantity: request.items[ 0 ]?.quantity || 1,
    gstin: request.gstin || DEFAULT_GSTIN,
    orderId: request.orderId || 'Offline',
    shipping_info: { country: 'IN', addresses: [] },
    order: {
      status: 'pending',
      items: request.items.map( ( item, idx ) => ( {
        retailer_id: item.productId || `ITEM_${idx + 1}`,
        name: item.name,
        amount: { value: item.amount, offset: 100 },
        quantity: item.quantity,
        gstRate: item.gstRate ?? 0,
      } ) ),
      subtotal: { value: subtotal, offset: 100 },
      discount: { value: discount, offset: 100, description: 'Promo' },
      shipping: { value: delivery, offset: 100, description: 'Express' },
      tax: { value: tax, offset: 100, description: `GSTIN: ${request.gstin || DEFAULT_GSTIN}` },
    },
  };

  // Always use checkout button template (wecare_pay) — enables address + coupons
  return apiCall<{ messageId: string; status: string }>( `${API_BASE}/whatsapp/send`, {
    method: 'POST',
    body: JSON.stringify( {
      contactId: request.contactId,
      phoneNumberId: request.phoneNumberId,
      recipientBsuid: request.recipientBsuid,
      isCheckoutTemplate: true,
      isTemplate: true,
      templateName: 'wecare_pay',
      templateParams: [],
      checkoutOrderDetails: orderDetails,
      headerImageUrl: request.headerImageUrl || 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png',
    } ),
  } );
}


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

export async function applyCors ( request: { allowAll?: boolean; origins?: string[] } ): Promise<{ success: boolean; allowOrigins: string[] } | null> {
  return apiCall<{ success: boolean; allowOrigins: string[] }>( `${API_BASE}/waba`, {
    method: 'POST',
    body: JSON.stringify( { action: 'cors-apply', allowAll: request.allowAll, origins: request.origins } ),
  } );
}

/**
 * Get template details
 * API: GetWhatsAppMessageTemplate
 */
export async function getTemplateDetails ( templateId: string, wabaId?: string ): Promise<any | null> {
  let url = `${API_BASE}/whatsapp/templates/${templateId}`;
  if ( wabaId ) url += `?wabaId=${wabaId}`;

  const data = await apiCall<any>( url );
  if ( data )
  {
    return data.template || data;
  }
  return null;
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
 * Returns a CDN URL: https://wecare.digital/get/o/public/wa-tpl/{folder}/...
 * (the bucket is `wecare-digital-get`; the old `app.wecare.digital` host, whose name
 * doubled as the bucket name, was retired on 2026-09-28.)
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
    agentId: '4UUQYFWX64',
    agentAlias: 'TSTALIASID',
    knowledgeBaseId: 'static-faq',
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
export async function testBedrockAIResponse ( message: string ): Promise<{ message: string; response: string; detectedLanguage: string }> {
  const data = await apiCall<any>( `${API_BASE}/ai/test`, {
    method: 'POST',
    body: JSON.stringify( { message } ),
  } );
  if ( data )
  {
    return {
      message: data.message || message,
      response: data.response || 'AI test response would appear here',
      detectedLanguage: data.detectedLanguage || 'en',
    };
  }
  return { message, response: 'AI service unavailable', detectedLanguage: 'en' };
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
  return { totalTemplatesSent: 0, avgDeliveryRate: 0, avgReadRate: 0, topTemplates: [], byCategory: {} };
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
  status: 'PENDING' | 'SENT' | 'FAILED' | 'CANCELLED';
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
  if ( status ) url += `?status=${status}`;

  const data = await apiCall<any>( url );
  if ( data && data.scheduledMessages )
  {
    return data.scheduledMessages.map( normalizeScheduledMessage );
  }
  return [];
}

/**
 * Cancel a scheduled message
 * API: DELETE /messages/scheduled/{scheduledId}
 */
export async function cancelScheduledMessage ( scheduledId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/scheduled/${scheduledId}`, {
    method: 'DELETE',
  } );
  return data?.success === true || data !== null;
}

/**
 * Update a scheduled message
 * API: PUT /messages/scheduled/{scheduledId}
 */
export async function updateScheduledMessage ( scheduledId: string, updates: {
  scheduledAt?: string;
  templateParams?: string[];
} ): Promise<ScheduledMessage | null> {
  const data = await apiCall<any>( `${API_BASE}/scheduled/${scheduledId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  if ( data )
  {
    return normalizeScheduledMessage( data );
  }
  return null;
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
  const data = await apiCall<any>( `${API_BASE}/ai/config?key=${configKey}` );
  if ( data && data.config )
  {
    return data.config;
  }
  return null;
}

/**
 * Update system configuration
 * Lambda: wecare-ai-config-management
 */
export async function updateSystemConfig ( configKey: string, config: any ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/ai/config`, {
    method: 'PUT',
    body: JSON.stringify( { key: configKey, config } ),
  } );
  return data !== null;
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
// CLEAR ALL DATA FUNCTIONS
// ============================================================================

/**
 * Clear all WhatsApp messages (keeps contacts)
 */
export async function clearAllWhatsAppMessages (): Promise<{ deleted: number; failed: number }> {
  try
  {
    const messages = await listMessages( undefined, 'WHATSAPP' );

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
      // Rate limit to avoid overwhelming the API
      if ( deleted % 50 === 0 )
      {
        await new Promise( r => setTimeout( r, 500 ) );
      }
    }

    return { deleted, failed };
  } catch ( error )
  {
    console.error( 'Clear all messages error:', error );
    return { deleted: 0, failed: 0 };
  }
}

/**
 * Clear all contacts (soft delete)
 */
export async function clearAllContacts (): Promise<{ deleted: number; failed: number }> {
  try
  {
    const contacts = await listContacts();

    let deleted = 0;
    let failed = 0;

    for ( const contact of contacts )
    {
      const result = await deleteContact( contact.contactId );
      if ( result )
      {
        deleted++;
      } else
      {
        failed++;
      }
    }

    return { deleted, failed };
  } catch ( error )
  {
    console.error( 'Clear all contacts error:', error );
    return { deleted: 0, failed: 0 };
  }
}

/**
 * Clear everything - messages, contacts, and media
 * WARNING: This is destructive and irreversible!
 */
export async function clearAllInboxData (): Promise<{
  messagesDeleted: number;
  messagesFailed: number;
  contactsDeleted: number;
  contactsFailed: number;
  smsDeleted: number;
  voiceDeleted: number;
}> {
  let totalMessagesDeleted = 0;
  let totalMessagesFailed = 0;
  let smsDeleted = 0;
  let voiceDeleted = 0;

  // 1. Clear WhatsApp messages
  const whatsappResult = await clearAllWhatsAppMessages();
  totalMessagesDeleted += whatsappResult.deleted;
  totalMessagesFailed += whatsappResult.failed;

  // 2. Clear SMS messages (both inbound and outbound)
  try
  {
    const smsMessages = await listMessages( undefined, 'SMS' );
    for ( const msg of smsMessages )
    {
      const result = await deleteMessage( msg.id, msg.direction );
      if ( result )
      {
        smsDeleted++;
        totalMessagesDeleted++;
      } else
      {
        totalMessagesFailed++;
      }
    }
  } catch ( error )
  {
    console.error( 'Error clearing SMS messages:', error );
  }

  // 3. Clear Voice call records
  try
  {
    const voiceCalls = await listVoiceCalls();
    for ( const call of voiceCalls )
    {
      try
      {
        // Try to delete voice call record via API
        const response = await apiCall<any>( `${API_BASE}/voice-aws/calls/${call.id}`, {
          method: 'DELETE',
        } );
        if ( response )
        {
          voiceDeleted++;
        }
      } catch ( e )
      {
        console.warn( `Failed to delete voice call ${call.id}:`, e );
      }
    }
  } catch ( error )
  {
    console.error( 'Error clearing voice calls:', error );
  }

  // 4. Clear all contacts (this also triggers media cleanup on backend)
  const contactResult = await clearAllContacts();

  return {
    messagesDeleted: totalMessagesDeleted,
    messagesFailed: totalMessagesFailed,
    contactsDeleted: contactResult.deleted,
    contactsFailed: contactResult.failed,
    smsDeleted,
    voiceDeleted,
  };
}

// ============================================================================
// WHATSAPP BUSINESS API (Profile, Flows, Webhooks, Groups)
// ============================================================================

const WA_BIZ_BASE = `${API_BASE}/wa-business`;

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
// PART 4 — TTL, Template validation/presets, Media, Send-test, Flow admin
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

// ── Template validation / presets / send-test / refresh (template-management lambda) ──
const WA_TPL_BASE = `${API_BASE}/whatsapp/templates`;

export interface TemplateValidationResult { ok: boolean; errors: string[]; warnings: string[]; }
export interface TemplatePresetSummary { name: string; category: string; language: string; hasFlowButton: boolean; }

export async function validateTemplateDefinition ( templateDefinition: any ): Promise<TemplateValidationResult | null> {
  return apiCall<TemplateValidationResult>( `${WA_TPL_BASE}/validate`, {
    method: 'POST',
    body: JSON.stringify( { templateDefinition } ),
  } );
}

export async function listTemplatePresets (): Promise<TemplatePresetSummary[]> {
  const data = await apiCall<any>( `${WA_TPL_BASE}/presets` );
  return data?.presets || [];
}

export async function getTemplatePreset ( name: string ): Promise<any> {
  const data = await apiCall<any>( `${WA_TPL_BASE}/presets/${name}` );
  return data?.preset || null;
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

export async function sendTestInteractive ( to: string, interactive: any, phoneId?: string ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/interactive`, { method: 'POST', body: JSON.stringify( { to, interactive, phoneId } ) } ) as any;
}

export async function sendTestFlow ( to: string, opts: { flowId?: string; flowName?: string; flowToken?: string; flowCta?: string; bodyText?: string; headerText?: string; footerText?: string; screen?: string; flowAction?: 'navigate' | 'data_exchange'; mode?: 'draft' | 'published'; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/flow`, { method: 'POST', body: JSON.stringify( { to, ...opts } ) } ) as any;
}

export async function sendTestContacts ( to: string, contacts: any[], phoneId?: string ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/contacts`, { method: 'POST', body: JSON.stringify( { to, contacts, phoneId } ) } ) as any;
}

export async function sendTestLocation ( to: string, latitude: number, longitude: number, opts?: { name?: string; address?: string; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/location`, { method: 'POST', body: JSON.stringify( { to, latitude, longitude, ...opts } ) } ) as any;
}

export async function sendTestProduct ( to: string, catalogId: string, opts: { productRetailerId?: string; sections?: any[]; headerText?: string; bodyText?: string; footerText?: string; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/product`, { method: 'POST', body: JSON.stringify( { to, catalogId, ...opts } ) } ) as any;
}

// Request a user's phone number (BSUID-friendly; for username-adopters whose phone is hidden).
export async function sendRequestContactInfo ( opts: { to?: string; recipient?: string; bodyText?: string; phoneId?: string } ): Promise<{ success?: boolean; messageId?: string; error?: string }> {
  return apiCall<any>( `${WA_SEND_BASE}/request-contact-info`, { method: 'POST', body: JSON.stringify( opts ) } ) as any;
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

// Interactive List Messages
export async function sendInteractiveList ( phoneId: string, to: string, bodyText: string, buttonText: string, sections: any[], headerText?: string, footerText?: string ): Promise<{ messageId: string } | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/interactive-list`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, to, bodyText, buttonText, sections, headerText, footerText } ),
  } );
  return data?.success ? { messageId: data.messageId } : null;
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

// ===================================================================
// WIX STORE INTEGRATION
// ===================================================================

const WIX_STORE_BASE = `${API_BASE}/wix-store`;

export interface WixProduct {
  /** Compatibility ID used by the existing admin UI. Catalog V3 also returns id/revision. */
  _id: string;
  id?: string;
  revision?: string;
  name: string;
  description: string;
  price: number;
  formattedPrice: string;
  currency: string;
  sku: string;
  ribbon: string;
  brand: string;
  inStock: boolean;
  quantityInStock: number;
  productType: string;
  slug: string;
  mainMedia: any;
  mediaItems: any[];
  collections: { _id: string; name: string }[];
  customTextFields: any[];
  productOptions: any[];
  variants: any[];
  lastUpdated: string;
}

export interface WixOrder {
  _id: string;
  number: number;
  customOrderNumber?: string;
  customField?: { title: string; value: string };
  channelInfo: any;
  buyerInfo: { email: string; firstName?: string; lastName?: string; phone?: string };
  buyerNote: string;
  billingInfo: any;
  shippingInfo: any;
  lineItems: any[];
  totals: { subtotal: number; total: number; shipping: number; tax: number; discount: number };
  currency: string;
  paymentStatus: string;
  fulfillmentStatus: string;
  fulfillments: any[];
  archived: boolean;
  dateCreated: string;
  dateUpdated: string;
  // REST API enriched fields
  _summary?: any;
  _transactions?: any;
  _fulfillments?: any;
}

export interface WixCategory {
  _id: string;
  id?: string;
  name: string;
  description: string;
  mainMedia: any;
  slug: string;
}

/** Legacy UI name retained while the /collections compatibility route maps to Categories V3. */
export type WixCollection = WixCategory;

export async function listWixSites (): Promise<any[]> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/sites` );
  return data?.sites || [];
}

export async function listWixProducts ( params?: {
  limit?: number;
  search?: string;
  collectionId?: string;
} ): Promise<{ products: WixProduct[]; totalCount: number }> {
  const query = new URLSearchParams();
  if ( params?.limit ) query.set( 'limit', String( params.limit ) );
  if ( params?.search ) query.set( 'search', params.search );
  if ( params?.collectionId ) query.set( 'collectionId', params.collectionId );
  const qs = query.toString();
  const data = await apiCall<any>( `${WIX_STORE_BASE}/products${qs ? '?' + qs : ''}` );
  return { products: data?.products || [], totalCount: data?.totalCount || data?.totalResults || 0 };
}

export async function getWixProduct ( productId: string ): Promise<WixProduct | null> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/products/${productId}` );
  return data?.product || null;
}

export async function listWixOrders ( params?: {
  limit?: number;
  status?: string;
  paymentStatus?: string;
  fulfillmentStatus?: string;
  email?: string;
  orderNumber?: string;
  customOrderNumber?: string;
  dateFrom?: string;
  dateTo?: string;
} ): Promise<{ orders: WixOrder[]; totalCount: number }> {
  const query = new URLSearchParams();
  if ( params?.limit ) query.set( 'limit', String( params.limit ) );
  if ( params?.status ) query.set( 'status', params.status );
  if ( params?.paymentStatus ) query.set( 'paymentStatus', params.paymentStatus );
  if ( params?.fulfillmentStatus ) query.set( 'fulfillmentStatus', params.fulfillmentStatus );
  if ( params?.email ) query.set( 'email', params.email );
  if ( params?.orderNumber ) query.set( 'orderNumber', params.orderNumber );
  if ( params?.customOrderNumber ) query.set( 'customOrderNumber', params.customOrderNumber );
  if ( params?.dateFrom ) query.set( 'dateFrom', params.dateFrom );
  if ( params?.dateTo ) query.set( 'dateTo', params.dateTo );
  const qs = query.toString();
  const data = await apiCall<any>( `${WIX_STORE_BASE}/orders${qs ? '?' + qs : ''}` );
  return { orders: data?.orders || [], totalCount: data?.totalCount || data?.totalResults || 0 };
}

export async function getWixOrder ( orderId: string ): Promise<WixOrder | null> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/orders/${orderId}` );
  return data?.order || null;
}

export async function listWixCollections ( limit?: number ): Promise<{ collections: WixCategory[]; totalCount: number }> {
  const qs = limit ? `?limit=${limit}` : '';
  const data = await apiCall<any>( `${WIX_STORE_BASE}/collections${qs}` );
  return { collections: data?.collections || [], totalCount: data?.totalCount || data?.totalResults || 0 };
}

export async function getWixInventory ( productId: string ): Promise<any> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/inventory/${productId}` );
  return data?.inventoryItem || data?.inventoryItems || null;
}

export async function syncWixProducts (): Promise<{ message: string }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/sync/products`, { method: 'POST' } );
  return data || { message: 'Sync failed' };
}

export async function syncWixOrders (): Promise<{ message: string }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/sync/orders`, { method: 'POST' } );
  return data || { message: 'Sync failed' };
}

// Product creation / management
export async function createWixProduct ( product: Record<string, any> ): Promise<{ product: any; created: boolean }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/create-product`, {
    method: 'POST',
    body: JSON.stringify( { product } ),
  } );
  return data || { product: null, created: false };
}

export async function bulkCreateWixProducts ( products: Record<string, any>[] ): Promise<{ total: number; succeeded: number; failed: number; results: any[] }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/bulk-create-products`, {
    method: 'POST',
    body: JSON.stringify( { products } ),
  } );
  return data || { total: 0, succeeded: 0, failed: 0, results: [] };
}

export async function updateWixProduct ( productId: string, updates: Record<string, any> ): Promise<{ product: any; updated: boolean }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/update-product`, {
    method: 'POST',
    body: JSON.stringify( { productId, updates } ),
  } );
  return data || { product: null, updated: false };
}

export async function deleteWixProduct ( productId: string ): Promise<{ deleted: boolean }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/delete-product`, {
    method: 'POST',
    body: JSON.stringify( { productId } ),
  } );
  return data || { deleted: false };
}

export async function getWixSampleProducts (): Promise<{ category: string; products: any[] }> {
  const data = await apiCall<any>( `${WIX_STORE_BASE}/sample-products` );
  return data || { category: '', products: [] };
}

// ============================================================================
// INVOICE ENGINE API (Unified Invoice System)
// Lambda: wecare-invoice-engine
// ============================================================================

const INVOICE_BASE = `${API_BASE}/invoices`;

export interface InvoiceItem {
  invoiceId: string;
  itemIndex: number;
  name: string;
  amount: number;
  quantity: number;
  productId?: string;
}

export interface InvoiceAsset {
  invoiceId: string;
  assetType: 'image' | 'pdf';
  s3Key: string;
  url: string;
  contentType: string;
  version: number;
  generatedAt: number;
}

export interface InvoiceDeliveryLog {
  timestamp: number;
  channel: string;
  toNumber: string;
  waMessageId: string;
  status: string;
  error: string;
  imageUrl: string;
}

export interface Invoice {
  invoiceId: string;
  invoiceNumber: string;
  paymentId: string;
  orderId: string;
  referenceId: string;
  entryPoint: string;
  status: string;
  paymentStatus: string;
  contactId: string;
  customerName: string;
  customerPhone: string;
  paidByPhone: string;
  customerEmail: string;
  /**
   * The public customer id — a uuid4 the server mints and `invoice-engine` re-validates with
   * `customer_uuid.is_customer_uuid` before storing, so a junk value is dropped rather than
   * recorded. Optional because an invoice raised before the attribute existed carries none, and
   * absent must stay distinguishable from empty here: the invoice renderers print no Customer ID
   * row at all in that case rather than a placeholder.
   *
   * Safe to show in full. It is opaque, carries no timestamp (uuid4, deliberately not uuid7) and
   * is not a credential — which is the point: a staff member can quote it instead of the phone.
   */
  customerUuid?: string;
  shippingAddress: string;
  billingAddress: string;
  goodsType?: 'digital-goods' | 'physical-goods';
  subtotal: number;
  discount: number;
  shipping: number;
  gstRate: number;
  tax: number;
  convenienceFee: number;
  total: number;
  currency: string;
  gstin: string;
  purpose: string;
  notes: string;
  createdAt: number;
  updatedAt: number;
  paidAt: number;
  remarks?: string | InvoiceRemark[];
  items?: InvoiceItem[];
  assets?: InvoiceAsset[];
}

export interface CreateInvoiceEngineRequest {
  customerPhone: string;
  paidByPhone?: string;
  customerEmail: string;
  shippingAddress: string;
  billingAddress: string;
  customerName?: string;
  contactId?: string;
  goodsType?: 'digital-goods' | 'physical-goods';
  items: { name: string; amount: number; quantity: number; productId?: string; gstRate?: number }[];
  discount?: number;
  shipping?: number;
  gstRate?: number;       // Fallback global GST rate (used if items don't have per-item rates)
  convenienceFee?: number;
  purpose?: string;
  orderId?: string;
  referenceId?: string;
  entryPoint?: string;
  paymentId?: string;
  gstin?: string;
  currency?: string;
  /** Preferred PG. Razorpay is the only gateway; PayU was retired 2026-08-23. */
  preferredGateway?: string;
  /** Exact Meta PG config name (e.g. 'WECAREDIGITAL') — stored on invoice for keyword-triggered payments */
  paymentConfiguration?: string;
  /** Structured address fields for WhatsApp Payments shipping_info */
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
}

// Create invoice directly
export async function createInvoiceEngine ( request: CreateInvoiceEngineRequest ): Promise<{ invoiceId: string; invoiceNumber: string; total: number } | null> {
  return apiCall<{ invoiceId: string; invoiceNumber: string; total: number }>( INVOICE_BASE, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

// Create invoice from Razorpay payment ID
export async function createInvoiceFromPayment ( paymentId: string, extras?: Record<string, any> ): Promise<{ invoiceId: string; invoiceNumber: string; total: number } | null> {
  return apiCall<{ invoiceId: string; invoiceNumber: string; total: number }>( `${INVOICE_BASE}/from-payment`, {
    method: 'POST',
    body: JSON.stringify( { paymentId, ...extras } ),
  } );
}

// List invoices with optional filters
export async function listInvoicesEngine ( params?: { status?: string; contactId?: string; paymentId?: string; limit?: number } ): Promise<{ invoices: Invoice[]; count: number }> {
  const query = new URLSearchParams();
  if ( params?.status ) query.set( 'status', params.status );
  if ( params?.contactId ) query.set( 'contactId', params.contactId );
  if ( params?.paymentId ) query.set( 'paymentId', params.paymentId );
  if ( params?.limit ) query.set( 'limit', String( params.limit ) );
  const qs = query.toString();
  const data = await apiCall<any>( `${INVOICE_BASE}${qs ? '?' + qs : ''}` );
  return { invoices: data?.invoices || [], count: data?.count || 0 };
}

// Get single invoice with items and assets
export async function getInvoiceEngine ( invoiceId: string ): Promise<Invoice | null> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}` );
  return data?.invoice || null;
}

// Update invoice (admin)
export async function updateInvoiceEngine ( invoiceId: string, updates: Partial<Invoice> ): Promise<boolean> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return data?.updated === true;
}

// Generate invoice image (PNG)
export async function generateInvoiceImage ( invoiceId: string ): Promise<{ invoiceId: string; imageUrl: string; s3Key: string } | null> {
  return apiCall<{ invoiceId: string; imageUrl: string; s3Key: string }>( `${INVOICE_BASE}/${invoiceId}/generate-image`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId } ),
  } );
}

// Generate invoice PDF
export async function generateInvoicePdf ( invoiceId: string ): Promise<{ invoiceId: string; pdfUrl: string; s3Key: string } | null> {
  return apiCall<{ invoiceId: string; pdfUrl: string; s3Key: string }>( `${INVOICE_BASE}/${invoiceId}/generate-pdf`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId } ),
  } );
}

// Send invoice image on WhatsApp
export async function sendInvoiceWhatsApp ( invoiceId: string, toWhatsAppNumber: string, phoneNumberId?: string ): Promise<{ invoiceId: string; waMessageId: string; status: string; imageUrl: string } | null> {
  return apiCall<{ invoiceId: string; waMessageId: string; status: string; imageUrl: string }>( `${INVOICE_BASE}/${invoiceId}/send-whatsapp`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, toWhatsAppNumber, phoneNumberId } ),
  } );
}

// Send WhatsApp interactive payment link for a pending invoice
export async function sendPaymentLink ( invoiceId: string, phoneNumberId?: string, paymentConfiguration?: string ): Promise<{ invoiceId: string; referenceId: string; status: string; toPhone: string; total: number } | null> {
  return apiCall<{ invoiceId: string; referenceId: string; status: string; toPhone: string; total: number }>( `${INVOICE_BASE}/${invoiceId}/send-payment-link`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, phoneNumberId, paymentConfiguration } ),
  } );
}

// Cancel/void an invoice
export async function cancelInvoice ( invoiceId: string, reason?: string ): Promise<{ invoiceId: string; status: string } | null> {
  return apiCall<{ invoiceId: string; status: string }>( `${INVOICE_BASE}/${invoiceId}/cancel`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, reason } ),
  } );
}

// ═══════════════════════════════════════════════════════════════════════════
// CHECKOUT BUTTON TEMPLATE — Send via outbound-whatsapp Lambda
// Per Meta docs: Checkout button templates use order_details button with
// sale_amount, shipping_info, importer_address, and payment_settings.
// ═══════════════════════════════════════════════════════════════════════════

export interface CheckoutItem {
  name: string;
  amount: { offset: number; value: number };
  sale_amount?: { offset: number; value: number };
  quantity: number;
  country_of_origin: string;
  importer_name: string;
  importer_address: {
    address_line1: string;
    address_line2?: string;
    city: string;
    zone_code: string;
    postal_code: string;
    country_code: string;
  };
}

export interface CheckoutShippingAddress {
  name: string;
  phone_number: string;
  address: string;
  city: string;
  state: string;
  in_pin_code: string;
  house_number?: string;
  tower_number?: string;
  building_name?: string;
  landmark_area?: string;
}

export interface CheckoutOrderDetails {
  reference_id: string;
  type: 'physical-goods' | 'digital-goods';
  currency: string;
  payment_settings?: Array<{
    type: string;
    payment_gateway: {
      type: string;
      configuration_name: string;
    };
  }>;
  shipping_info?: {
    country: string;
    addresses: CheckoutShippingAddress[];
  };
  order: {
    items: CheckoutItem[];
    subtotal: { offset: number; value: number };
    shipping: { offset: number; value: number };
    tax: { offset: number; value: number };
    discount?: { offset: number; value: number; description?: string };
    status: string;
    expiration?: { timestamp: string; description?: string };
  };
  total_amount: { offset: number; value: number };
  header_image_id?: string;
}

export interface SendCheckoutTemplateRequest {
  contactId: string;
  phoneNumberId: string;
  templateName: string;
  templateParams?: string[];
  checkoutOrderDetails: CheckoutOrderDetails;
  headerImageUrl?: string;
  recipientBsuid?: string;
}

/**
 * Send a checkout button template message via WhatsApp.
 * This sends a marketing template with an order_details "Buy now" button
 * that opens the native WhatsApp checkout flow with coupons + address.
 */
export async function sendCheckoutTemplate (
  request: SendCheckoutTemplateRequest
): Promise<{ messageId: string; whatsappMessageId: string; status: string; referenceId: string } | null> {
  return apiCall<{ messageId: string; whatsappMessageId: string; status: string; referenceId: string }>(
    `${API_BASE}/whatsapp/send`,
    {
      method: 'POST',
      body: JSON.stringify( {
        contactId: request.contactId,
        phoneNumberId: request.phoneNumberId,
        isTemplate: true,
        isCheckoutTemplate: true,
        templateName: request.templateName,
        templateParams: request.templateParams || [],
        checkoutOrderDetails: request.checkoutOrderDetails,
        headerImageUrl: request.headerImageUrl,
        recipientBsuid: request.recipientBsuid,
      } ),
    }
  );
}

// Get delivery log for an invoice
export async function getInvoiceDeliveryLog ( invoiceId: string ): Promise<{ deliveryLogs: InvoiceDeliveryLog[]; count: number }> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}/delivery-log` );
  return { deliveryLogs: data?.deliveryLogs || [], count: data?.count || 0 };
}

// Preview next invoice number (without incrementing)
export async function previewNextInvoiceNumber ( fy?: string ): Promise<{ nextInvoiceNumber: string; fy: string; lastSeq: number } | null> {
  return apiCall<{ nextInvoiceNumber: string; fy: string; lastSeq: number }>( `${INVOICE_BASE}/next-sequence`, {
    method: 'POST',
    body: JSON.stringify( { fy } ),
  } );
}

// Delete invoice (hard delete + optional sequence adjustment)
export async function deleteInvoice ( invoiceId: string, adjustSequence = false ): Promise<{ invoiceId: string; deleted: boolean; invoiceNumber: string } | null> {
  return apiCall<{ invoiceId: string; deleted: boolean; invoiceNumber: string }>( `${INVOICE_BASE}/${invoiceId}`, {
    method: 'DELETE',
    body: JSON.stringify( { adjustSequence } ),
  } );
}

// Add remark / refund / credit note to an invoice
export interface InvoiceRemark {
  id: string;
  type: 'remark' | 'refund' | 'credit_note';
  text: string;
  amount: number;
  author: string;
  createdAt: number;
}

export async function addInvoiceRemark ( invoiceId: string, remarkType: 'remark' | 'refund' | 'credit_note', text: string, amount = 0, author = 'admin' ): Promise<{ invoiceId: string; remark: InvoiceRemark; totalRemarks: number } | null> {
  return apiCall<{ invoiceId: string; remark: InvoiceRemark; totalRemarks: number }>( `${INVOICE_BASE}/${invoiceId}/remark`, {
    method: 'POST',
    body: JSON.stringify( { type: remarkType, text, amount, author } ),
  } );
}

// ============================================================================
// SYSTEM CLEANUP API
// ============================================================================

export interface CleanupResource {
  id: string;
  label: string;
  category: string;
  type: 'dynamodb' | 's3' | 'sqs';
  table?: string;
  prefix?: string;
  queue?: string;
  count: number;
}

export interface CleanupResult {
  id: string;
  label: string;
  deleted: number;
  elapsed?: number;
  error?: string;
}

export async function getCleanupPreview (): Promise<CleanupResource[]> {
  const data = await apiCall<any>( `${API_BASE}/system-cleanup` );
  return data?.resources || [];
}

export async function executeCleanup ( selected: string[] ): Promise<{ results: CleanupResult[]; totalDeleted: number }> {
  const data = await apiCall<any>( `${API_BASE}/system-cleanup`, {
    method: 'POST',
    body: JSON.stringify( { selected } ),
  } );
  return { results: data?.results || [], totalDeleted: data?.totalDeleted || 0 };
}

// ============================================================================
// SUBMIT REQUESTS API (WhatsApp Flow Submissions)
// ============================================================================

export interface SubmitRequest {
  id: string;
  requestId: string;
  requestNumber?: string;  // WD-SR-XXXXXXXX
  flowToken?: string;
  phone: string;
  senderName?: string;
  contactId?: string;
  orderId: string;
  subject?: string;
  description?: string;
  paymentStatus: string; // pending, captured, failed
  paymentReferenceId?: string;
  paymentAmount?: number;
  transactionId?: string;
  invoiceId?: string;
  invoiceNumber?: string;
  daysOld?: number;
  isExpired?: boolean;
  createdAt: number;
  updatedAt?: number;
}

export async function listSubmitRequests ( paymentStatus?: string ): Promise<SubmitRequest[]> {
  let url = `${API_BASE}/wa-business/submit-requests`;
  if ( paymentStatus ) url += `?paymentStatus=${paymentStatus}`;
  const data = await apiCall<any>( url );
  return data?.requests || [];
}

export interface FlowLog {
  id: string;
  type: string;
  flowToken?: string;
  phone: string;
  action: string;
  screen: string;
  dataKeys?: string[];
  requestId?: string;
  createdAt: number;
  // Enhanced flow data fields
  order_id?: string;
  subject?: string;
  description?: string;
  email?: string;
  flowData?: string; // JSON string of full submitted data
}

export async function listFlowLogs ( phone?: string ): Promise<FlowLog[]> {
  let url = `${API_BASE}/wa-business/flow-logs`;
  if ( phone ) url += `?phone=${encodeURIComponent( phone )}`;
  const data = await apiCall<any>( url );
  return data?.logs || [];
}

export async function resendSubmitRequestPayment ( invoiceId: string ): Promise<boolean> {
  try
  {
    const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}/send-payment-link`, {
      method: 'POST',
      body: JSON.stringify( { invoiceId } ),
    } );
    return !!data;
  } catch { return false; }
}

// ============================================================================
// FLOW MANAGEMENT ENGINE
// ============================================================================

export interface FlowRegistryItem {
  flowId: string;
  flowCode: string;
  flowName: string;
  flowType: string;
  flowVersion?: string;
  dataApiVersion?: string;
  wabaId?: string;
  status: string;
  category?: string;
  requiresPayment?: boolean;
  paymentAmount?: number;
  paymentDescription?: string;
  screenConfig?: string;
  contactMapping?: string;
  dataFetchers?: string;
  submissionPrefix?: string;
  endpointUri?: string;
  publishedAt?: number;
  createdAt?: number;
  updatedAt?: number;
}

export interface FlowSubmissionItem {
  submissionId: string;
  flowId: string;
  flowCode: string;
  flowType?: string;
  flowVersion?: string;
  phone: string;
  contactId?: string;
  senderName?: string;
  formData?: string;
  orderId?: string;
  requestType?: string;
  subject?: string;
  description?: string;
  submissionNumber?: string;
  flowToken?: string;
  paymentRequired?: boolean;
  paymentAmount?: number;
  paymentStatus: string;
  paymentRefId?: string;
  invoiceId?: string;
  transactionId?: string;
  paidAt?: number;
  status: string;
  assignedTo?: string;
  notes?: string;
  resolvedAt?: number;
  createdAt: number;
  updatedAt?: number;
  // Service-request (post-payment) fields
  requestId?: string;
  referenceId?: string;
  orderNumber?: string;
  product?: string;
  amount?: string;
  customerName?: string;
  shippingAddress?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
  preferredTime?: string;
  attachments?: { key?: string; url?: string; type?: string; filename?: string; mime?: string; ts?: number }[];
}

export interface FlowSubmissionStats {
  total: number;
  byStatus: Record<string, number>;
  byPaymentStatus: Record<string, number>;
  totalPaymentAmount: number;
  capturedAmount: number;
  pendingAmount: number;
}

export async function listFlowRegistry (): Promise<FlowRegistryItem[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-registry` );
  return data?.flows || [];
}

export async function upsertFlowRegistry ( item: Partial<FlowRegistryItem> ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-registry`, {
    method: 'POST',
    body: JSON.stringify( item ),
  } );
  return !!data?.success;
}

export async function listFlowSubmissions ( params?: {
  flowCode?: string; paymentStatus?: string; status?: string; phone?: string; limit?: number;
} ): Promise<FlowSubmissionItem[]> {
  const qs = new URLSearchParams();
  if ( params?.flowCode ) qs.set( 'flowCode', params.flowCode );
  if ( params?.paymentStatus ) qs.set( 'paymentStatus', params.paymentStatus );
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions${query ? '?' + query : ''}` );
  return data?.submissions || [];
}

export async function getFlowSubmissionStats ( flowCode?: string ): Promise<FlowSubmissionStats | null> {
  const qs = flowCode ? `?flowCode=${flowCode}` : '';
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/stats${qs}` );
  return data || null;
}

export async function updateSubmissionStatus ( submissionId: string, status: string, notes?: string ): Promise<{ updated: boolean; oldStatus: string; newStatus: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/update-status`, {
    method: 'POST',
    body: JSON.stringify( { submissionId, status, notes, changedBy: 'admin' } ),
  } );
  return data || { updated: false, oldStatus: '', newStatus: '' };
}

export interface CustomerJourney {
  phone: string;
  contactId: string;
  contact: Record<string, any>;
  submissions: FlowSubmissionItem[];
  logs: any[];
  summary: { flowsCompleted: string[]; totalSubmissions: number; totalPaid: number; totalInteractions: number };
}

export async function getCustomerJourney ( phone: string ): Promise<CustomerJourney | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-customer-journey?phone=${encodeURIComponent( phone )}` );
  return data || null;
}

export async function runSlaCheck ( params?: { slaDays?: number; reminderDays?: number; defaultAssignee?: string } ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/flow-sla-check`, { method: 'POST', body: JSON.stringify( params || {} ) } );
}

export async function cloneFlowToWaba ( sourceFlowCode: string, targetWabaId: string, targetFlowId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-clone`, {
    method: 'POST', body: JSON.stringify( { sourceFlowCode, targetWabaId, targetFlowId } ),
  } );
  return !!data?.success;
}

export async function exportSubmissionsCsv ( params?: { flowCode?: string; paymentStatus?: string } ): Promise<string> {
  const qs = new URLSearchParams();
  if ( params?.flowCode ) qs.set( 'flowCode', params.flowCode );
  if ( params?.paymentStatus ) qs.set( 'paymentStatus', params.paymentStatus );
  const query = qs.toString();
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/export${query ? '?' + query : ''}` );
  return data?.csv || '';
}

// `FlowVersionHealth` and `checkFlowVersionHealth` were here. Removed 2026-10-07:
// the call went to `${WA_BIZ_BASE}/flow-version-health`, i.e.
// /wa-business/flow-version-health, and no live route matches it. Its one caller was
// the Flow Hub's 'Health' tab, which swallowed the 404 in a catch and rendered an
// empty panel — so the tab went with it rather than being left to render nothing.
// The flow-submissions and flow-registry calls above and below are live and stay.

// The `WhatsApp Commerce Catalog` block — `CATALOG_BASE` (`${API_BASE}/catalog`) and
// `getCatalogProducts` — was here. Removed 2026-10-07: /catalog/products has no live
// route, and the deployment never had one, so every caller got a 404 body back. That
// is worse than an error, because `apiCall` hands the parsed body on and the callers
// read `products` off it as an empty array — the UI then said "no products in this
// catalog" when the truth was "there is no catalog endpoint". Its two consumers went
// with it: src/components/CatalogBrowser.tsx (deleted) and the inbox composer's
// 'Load products' picker. This is the CUT branch of the catalog-lookup decision; the
// catalog SEND below and in the inbox is a DIFFERENT, LIVE surface over WA_BIZ_BASE
// and deliberately stays.

// ── Catalog product admin (Meta catalog create/list/delete via WA Business API) ──
export interface CatalogProductInput {
  catalogId: string;
  retailerId: string;
  name: string;
  price: number;            // rupees
  description?: string;
  imageUrl?: string;
  url?: string;
  currency?: string;
  availability?: string;
  brand?: string;
  condition?: string;
  salePrice?: number;       // rupees
}

export async function listCatalogProductsAdmin ( catalogId: string, search?: string ): Promise<any[]> {
  const qs = new URLSearchParams( { catalogId } );
  if ( search ) qs.set( 'search', search );
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products?${qs.toString()}` );
  return data?.products || [];
}

export async function createCatalogProduct (
  input: CatalogProductInput
): Promise<{ success: boolean; productId?: string; imageFetchStatus?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products`, {
    method: 'POST', body: JSON.stringify( input ),
  } );
  if ( !data || data.error )
  {
    return { success: false, error: typeof data?.error === 'string' ? data.error : ( data?.error?.message || data?.error?.error_user_msg || 'Failed to create product' ) };
  }
  return { success: true, productId: data.productId, imageFetchStatus: data.imageFetchStatus };
}

/**
 * Update fields on an existing Meta catalog product.
 * `price` is sent in RUPEES, exactly as createCatalogProduct does — the handler owns the
 * rupees -> paise conversion for both, so the two paths share one unit contract.
 * `imageUrl` is mapped to `image_url` because that is the key Graph accepts on a product
 * edit; the handler filters to name/price/currency/availability/description/image_url/url.
 * It is a partial update: an `undefined` field is dropped by JSON.stringify, the handler
 * never sets the key, and Graph keeps the stored value. Callers rely on that to leave a
 * field they did not touch alone — notably `price`, which must not be re-sent on an edit
 * that did not change it.
 */
export async function updateCatalogProduct (
  productId: string,
  updates: { name?: string; price?: number; currency?: string; availability?: string; description?: string; imageUrl?: string; url?: string }
): Promise<boolean> {
  const { imageUrl, ...rest } = updates;
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products`, {
    method: 'PUT',
    body: JSON.stringify( { productId, ...rest, ...( imageUrl ? { image_url: imageUrl } : {} ) } ),
  } );
  return data?.success === true;
}

export async function deleteCatalogProduct ( productId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products?productId=${encodeURIComponent( productId )}`, { method: 'DELETE' } );
  return data?.success === true;
}

// ============================================================================
// ORDERS API
// ============================================================================

export interface Order {
  orderId: string;
  shortId?: string;
  orderDate?: string;
  orderTime?: string;
  orderDateIST?: string;
  source: string; // wix, manual, shopify, flow
  sourceOrderId?: string;
  sourceOrderNumber?: string;
  customerPhone?: string;
  customerName?: string;
  customerEmail?: string;
  totalAmount?: number;
  currency?: string;
  itemsSummary?: string;
  itemsJson?: string;
  items?: OrderItem[];
  itemCount?: number;
  orderStatus?: string; // active, fulfilled, cancelled
  status: string; // alias for orderStatus
  paymentStatus: string; // pending, captured, failed, refunded
  paymentAmount?: number;
  fulfillmentStatus?: string;
  requestCount?: number;
  notes?: string;
  adminNotes?: string;
  wixOrderId?: string;
  invoiceId?: string;
  createdAt: number;
  updatedAt?: number;
  syncedAt?: number;
}

export interface OrderItem {
  productId?: string;
  name: string;
  quantity: number;
  price: number;
  sku?: string;
  imageUrl?: string;
}

const ORDERS_BASE = `${WA_BIZ_BASE}/orders`;

export async function listOrders ( params?: {
  status?: string;
  source?: string;
  phone?: string;
  search?: string;
  limit?: number;
} ): Promise<{ orders: Order[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.search ) qs.set( 'search', params.search );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${ORDERS_BASE}${query ? '?' + query : ''}` );
  return data || { orders: [], count: 0 };
}

export async function getOrder ( orderId: string ): Promise<Order | null> {
  return apiCall<Order>( `${ORDERS_BASE}/${orderId}` );
}

export async function createOrder ( order: Partial<Order> ): Promise<Order | null> {
  return apiCall<Order>( ORDERS_BASE, {
    method: 'POST',
    body: JSON.stringify( order ),
  } );
}

export async function updateOrder ( orderId: string, updates: Partial<Order> ): Promise<boolean> {
  const data = await apiCall<any>( `${ORDERS_BASE}/${encodeURIComponent( orderId )}`, {
    method: 'PATCH',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function syncOrders (): Promise<{ message: string; synced?: number }> {
  const data = await apiCall<any>( `${ORDERS_BASE}/sync`, { method: 'POST' } );
  return data || { message: 'Sync failed' };
}

export async function getOrderSubmissions ( orderId: string ): Promise<FlowSubmissionItem[]> {
  const data = await apiCall<any>( `${ORDERS_BASE}/${encodeURIComponent( orderId )}/submissions` );
  return data?.submissions || [];
}

// ============================================================================
// DOCUMENTS API (Drop Docs)
// ============================================================================

export interface Document {
  documentId: string;
  documentRef?: string; // WD-DOC-XXXXXXXX
  customerPhone?: string;
  customerName?: string;
  contactId?: string;
  orderId?: string;
  source: string; // whatsapp, upload, manual
  type: string; // prescription, id_proof, invoice, photo, other
  status: string; // pending, uploaded, approved, rejected, reupload_requested
  fileName?: string;
  mimeType?: string;
  fileUrl?: string;
  storageKey?: string;
  s3Bucket?: string;
  fileSize?: number;
  notes?: string;
  reviewedBy?: string;
  reviewedAt?: number;
  createdAt: number;
  updatedAt?: number;
}

const DOCUMENTS_BASE = `${WA_BIZ_BASE}/documents`;

export async function listDocuments ( params?: {
  status?: string;
  source?: string;
  type?: string;
  phone?: string;
  limit?: number;
} ): Promise<{ documents: Document[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.type ) qs.set( 'type', params.type );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${DOCUMENTS_BASE}${query ? '?' + query : ''}` );
  return data || { documents: [], count: 0 };
}

export async function getDocument ( documentId: string ): Promise<Document | null> {
  return apiCall<Document>( `${DOCUMENTS_BASE}/${documentId}` );
}

export async function updateDocument ( documentId: string, updates: Partial<Document> ): Promise<boolean> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function getDocumentDownloadUrl ( documentId: string ): Promise<string | null> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}/download` );
  return data?.url || null;
}

export async function createDocument ( doc: Partial<Document> ): Promise<Document | null> {
  return apiCall<Document>( DOCUMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( doc ),
  } );
}

// ============================================================================
// FAQ API
// ============================================================================

export interface FaqEntry {
  faqId: string;
  question: string;
  answer: string;
  category: string;
  sortOrder: number;
  active: boolean;
  tags?: string[];
  createdAt: number;
  updatedAt?: number;
}

const FAQ_BASE = `${WA_BIZ_BASE}/faq`;

export async function listFaqs ( params?: {
  category?: string;
  active?: boolean;
} ): Promise<{ faqs: FaqEntry[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.category ) qs.set( 'category', params.category );
  if ( params?.active !== undefined ) qs.set( 'active', String( params.active ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${FAQ_BASE}${query ? '?' + query : ''}` );
  return data || { faqs: [], count: 0 };
}

export async function createFaq ( faq: Partial<FaqEntry> ): Promise<FaqEntry | null> {
  return apiCall<FaqEntry>( FAQ_BASE, {
    method: 'POST',
    body: JSON.stringify( faq ),
  } );
}

export async function updateFaq ( faqId: string, updates: Partial<FaqEntry> ): Promise<boolean> {
  const data = await apiCall<any>( `${FAQ_BASE}/${faqId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function deleteFaq ( faqId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${FAQ_BASE}/${faqId}`, { method: 'DELETE' } );
  return !!data;
}

// ============================================================================
// APPOINTMENTS API
// ============================================================================

export interface Appointment {
  appointmentId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  type: string;
  scheduledAt: number;
  duration?: number; // minutes
  status: string; // scheduled, confirmed, in_progress, completed, cancelled, no_show
  provider?: string;
  location?: string;
  notes?: string;
  createdAt: number;
  updatedAt?: number;
}

const APPOINTMENTS_BASE = `${WA_BIZ_BASE}/appointments`;

export async function listAppointments ( params?: {
  status?: string;
  type?: string;
  from?: string;
  to?: string;
} ): Promise<{ appointments: Appointment[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.type ) qs.set( 'type', params.type );
  if ( params?.from ) qs.set( 'from', params.from );
  if ( params?.to ) qs.set( 'to', params.to );
  const query = qs.toString();
  const data = await apiCall<any>( `${APPOINTMENTS_BASE}${query ? '?' + query : ''}` );
  return data || { appointments: [], count: 0 };
}

export async function updateAppointment ( appointmentId: string, updates: Partial<Appointment> ): Promise<boolean> {
  const data = await apiCall<any>( `${APPOINTMENTS_BASE}/${appointmentId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

// ============================================================================
// RX SLOTS API
// ============================================================================

export interface RxSlot {
  slotId: string;
  date: string; // YYYY-MM-DD
  time: string; // HH:mm
  duration?: number;
  provider?: string;
  status: string; // available, booked, blocked, completed
  patientName?: string;
  patientPhone?: string;
  contactId?: string;
  appointmentId?: string;
  notes?: string;
  createdAt: number;
  updatedAt?: number;
}

const RX_SLOTS_BASE = `${WA_BIZ_BASE}/rx-slots`;

export async function listRxSlots ( params?: {
  status?: string;
  date?: string;
  provider?: string;
} ): Promise<{ slots: RxSlot[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.date ) qs.set( 'date', params.date );
  if ( params?.provider ) qs.set( 'provider', params.provider );
  const query = qs.toString();
  const data = await apiCall<any>( `${RX_SLOTS_BASE}${query ? '?' + query : ''}` );
  return data || { slots: [], count: 0 };
}

export async function updateRxSlot ( slotId: string, updates: Partial<RxSlot> ): Promise<boolean> {
  const data = await apiCall<any>( `${RX_SLOTS_BASE}/${slotId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function createRxSlot ( slot: Partial<RxSlot> ): Promise<RxSlot | null> {
  return apiCall<RxSlot>( RX_SLOTS_BASE, {
    method: 'POST',
    body: JSON.stringify( slot ),
  } );
}

// ============================================================================
// ENTERPRISE ASSIST API
// ============================================================================

export interface EnterpriseCase {
  caseId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  subject: string;
  description?: string;
  category?: string;
  priority: string; // low, medium, high, critical
  status: string; // open, in_progress, waiting, resolved, closed
  assignedTo?: string;
  resolution?: string;
  resolvedAt?: number;
  createdAt: number;
  updatedAt?: number;
}

const ENTERPRISE_BASE = `${WA_BIZ_BASE}/enterprise-assist`;

export async function listEnterpriseCases ( params?: {
  status?: string;
  priority?: string;
  assignedTo?: string;
} ): Promise<{ cases: EnterpriseCase[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.priority ) qs.set( 'priority', params.priority );
  if ( params?.assignedTo ) qs.set( 'assignedTo', params.assignedTo );
  const query = qs.toString();
  const data = await apiCall<any>( `${ENTERPRISE_BASE}${query ? '?' + query : ''}` );
  return data || { cases: [], count: 0 };
}

export async function updateEnterpriseCase ( caseId: string, updates: Partial<EnterpriseCase> ): Promise<boolean> {
  const data = await apiCall<any>( `${ENTERPRISE_BASE}/${caseId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

// ============================================================================
// REVIEWS API
// ============================================================================

export interface Review {
  reviewId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  rating: number; // 1-5
  comment?: string;
  source: string; // whatsapp, web, google, manual
  status: string; // pending, approved, hidden, flagged
  response?: string;
  respondedAt?: number;
  orderId?: string;
  productId?: string;
  createdAt: number;
  updatedAt?: number;
}

const REVIEWS_BASE = `${WA_BIZ_BASE}/reviews`;

export async function listReviews ( params?: {
  status?: string;
  source?: string;
  minRating?: number;
} ): Promise<{ reviews: Review[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.minRating ) qs.set( 'minRating', String( params.minRating ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${REVIEWS_BASE}${query ? '?' + query : ''}` );
  return data || { reviews: [], count: 0 };
}

export async function updateReview ( reviewId: string, updates: Partial<Review> ): Promise<boolean> {
  const data = await apiCall<any>( `${REVIEWS_BASE}/${reviewId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}


// ============================================================================
// SERVICE REQUEST API (Submit / Track / Amend — Order-Centric)
// ============================================================================

export interface SubmitRequestPayload {
  orderId: string;
  requestType: string;
  subject: string;
  description: string;
  paymentRequired?: boolean;
}

export interface AmendRequestPayload {
  submissionId: string;
  orderId: string;
  amendmentType: string;
  description: string;
  attachments?: string[];
}

export interface TrackingData {
  order: Order;
  submissions: FlowSubmissionItem[];
  statusHistory: StatusHistoryEntry[];
  documents: Document[];
}

export interface StatusHistoryEntry {
  historyId: string;
  submissionId: string;
  orderId?: string;
  oldStatus: string;
  newStatus: string;
  changedBy: string;
  changedByName?: string;
  notes?: string;
  changedAt: number;
}

export interface DraftData {
  draftKey: string;
  phone: string;
  flowCode: string;
  screen: string;
  formData: string;
  updatedAt: number;
}

const SERVICE_BASE = `${WA_BIZ_BASE}/service`;

export async function submitRequest ( payload: SubmitRequestPayload ): Promise<{ submissionId: string; submissionNumber: string } | null> {
  return apiCall<{ submissionId: string; submissionNumber: string }>( `${SERVICE_BASE}/submit`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

export async function amendRequest ( payload: AmendRequestPayload ): Promise<{ success: boolean; amendmentId?: string } | null> {
  return apiCall<{ success: boolean; amendmentId?: string }>( `${SERVICE_BASE}/amend`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

export async function getTrackingData ( orderId: string ): Promise<TrackingData | null> {
  return apiCall<TrackingData>( `${SERVICE_BASE}/track/${encodeURIComponent( orderId )}` );
}

export async function getStatusHistory ( params: { orderId?: string; submissionId?: string } ): Promise<StatusHistoryEntry[]> {
  const qs = new URLSearchParams();
  if ( params.orderId ) qs.set( 'orderId', params.orderId );
  if ( params.submissionId ) qs.set( 'submissionId', params.submissionId );
  const query = qs.toString();
  const data = await apiCall<any>( `${SERVICE_BASE}/history${query ? '?' + query : ''}` );
  return data?.history || [];
}

export async function saveDraft ( draft: Partial<DraftData> ): Promise<boolean> {
  const data = await apiCall<any>( `${SERVICE_BASE}/drafts`, {
    method: 'POST',
    body: JSON.stringify( draft ),
  } );
  return !!data;
}

export async function getDraft ( flowCode: string ): Promise<DraftData | null> {
  return apiCall<DraftData>( `${SERVICE_BASE}/drafts/${encodeURIComponent( flowCode )}` );
}

export async function deleteDraft ( flowCode: string ): Promise<boolean> {
  const data = await apiCall<any>( `${SERVICE_BASE}/drafts/${encodeURIComponent( flowCode )}`, { method: 'DELETE' } );
  return !!data;
}

export async function createAppointment ( appointment: Partial<Appointment> ): Promise<Appointment | null> {
  return apiCall<Appointment>( APPOINTMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( appointment ),
  } );
}

export async function createEnterpriseCase ( caseData: Partial<EnterpriseCase> ): Promise<EnterpriseCase | null> {
  return apiCall<EnterpriseCase>( ENTERPRISE_BASE, {
    method: 'POST',
    body: JSON.stringify( caseData ),
  } );
}

export async function createReview ( review: Partial<Review> ): Promise<Review | null> {
  return apiCall<Review>( REVIEWS_BASE, {
    method: 'POST',
    body: JSON.stringify( review ),
  } );
}

// ============================================================================
// AUTOMATION RULES API (cross-channel auto-reply rules)
// ============================================================================

export interface AutomationRule {
  id: string;
  name: string;
  enabled: boolean;
  channel: 'any' | 'whatsapp' | 'sms' | 'rcs' | 'email';
  triggerType: 'keyword' | 'any';
  triggerValue: string;
  actionType: 'reply' | 'ai';
  actionValue: string;
  priority: number;
  createdAt?: number;
  updatedAt?: number;
}

export async function listAutomationRules (): Promise<AutomationRule[]> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules` );
  return ( data && data.rules ) ? data.rules : [];
}

export async function createAutomationRule ( rule: Partial<AutomationRule> ): Promise<AutomationRule | null> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules`, {
    method: 'POST',
    body: JSON.stringify( rule ),
  } );
  return data?.rule || null;
}

export async function updateAutomationRule ( id: string, updates: Partial<AutomationRule> ): Promise<AutomationRule | null> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules/${id}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return data?.rule || null;
}

export async function deleteAutomationRule ( id: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules/${id}`, { method: 'DELETE' } );
  return !!( data && ( data.success || data.deleted ) );
}

// ============================================================================
// CONVERSATION META API (team-inbox: status / assignee / tags / internal notes)
// ============================================================================

export interface ConversationNote { text: string; by: string; at: number; }
export interface ConversationMeta {
  conversationId: string;
  status: 'open' | 'pending' | 'resolved';
  assignee: string;
  tags: string[];
  notes: ConversationNote[];
  updatedAt?: number;
}

export async function getConversationMeta ( conversationId: string ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}` );
  return data?.meta || null;
}

export async function listConversationMeta (): Promise<ConversationMeta[]> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta` );
  return ( data && data.meta ) ? data.meta : [];
}

export async function updateConversationMeta ( conversationId: string, updates: { status?: string; assignee?: string; tags?: string[] } ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}`, {
    method: 'PUT', body: JSON.stringify( updates ),
  } );
  return data?.meta || null;
}

export async function addConversationNote ( conversationId: string, text: string, by?: string ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}/note`, {
    method: 'POST', body: JSON.stringify( { text, by: by || 'agent' } ),
  } );
  return data?.meta || null;
}

// ============================================================================
// WA GRAPH ADMIN MODULES (schedules, commerce, QR, conversational automation,
// link preview, assigned users/WABAs, bot details, AI pricing policy)
// ============================================================================

export interface CampaignSchedule {
  id?: string;
  name?: string;
  description?: string;
  delivery_time?: number;
  status?: 'COMPLETED' | 'FAILED' | 'SCHEDULED' | 'SENDING';
}

export async function listSchedules ( wabaId: string ): Promise<CampaignSchedule[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/schedules?wabaId=${encodeURIComponent( wabaId )}` );
  return data?.schedules || [];
}

export async function createSchedule ( wabaId: string, body: Record<string, unknown> ): Promise<{ success: boolean; id?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/schedules`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, ...body } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true, id: data?.id };
}

export interface CommerceSettings { is_cart_enabled?: boolean; is_catalog_visible?: boolean; id?: string; }

export async function getCommerceSettings ( phoneId: string ): Promise<CommerceSettings> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/commerce-settings?phoneId=${phoneId}` );
  return data?.commerceSettings || {};
}

export async function updateCommerceSettings ( phoneId: string, settings: CommerceSettings ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/commerce-settings`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...settings } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface QrCode { code: string; prefilled_message: string; deep_link_url: string; qr_image_url?: string; }

export async function listQrCodes ( phoneId: string ): Promise<QrCode[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes?phoneId=${phoneId}&fields=${encodeURIComponent( 'code,prefilled_message,deep_link_url,qr_image_url.format(PNG)' )}` );
  return data?.qrCodes || [];
}

export async function createQrCode ( phoneId: string, prefilledMessage: string, format: 'PNG' | 'SVG' = 'PNG' ): Promise<{ success: boolean; qrCode?: QrCode; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, prefilled_message: prefilledMessage, generate_qr_image: format } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true, qrCode: data?.qrCode };
}

export async function deleteQrCode ( phoneId: string, qrId: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes?phoneId=${phoneId}&qrId=${qrId}`, { method: 'DELETE' } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface BotCommand { command_name: string; command_description: string; }

export async function configureConversationalAutomation (
  phoneId: string,
  config: { enable_welcome_message?: boolean; prompts?: string[]; commands?: BotCommand[] }
): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/conversational-automation`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...config } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface ConversationalAutomation {
  phoneId: string;
  prompts: string[];
  commands: BotCommand[];
  enable_welcome_message: boolean;
}

export async function getConversationalAutomation ( phoneId: string ): Promise<ConversationalAutomation> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/conversational-automation?phoneId=${encodeURIComponent( phoneId )}` );
  return {
    phoneId,
    prompts: data?.prompts || [],
    commands: data?.commands || [],
    enable_welcome_message: !!data?.enable_welcome_message,
  };
}

export interface ThroughputInfo {
  phoneId: string;
  displayPhoneNumber: string;
  verifiedName: string;
  status: string;
  platformType: string;
  qualityRating: string;
  throughputLevel: string;
  messagesPerSecond: number | null;
}

export async function getThroughput ( phoneId: string ): Promise<ThroughputInfo> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/throughput?phoneId=${encodeURIComponent( phoneId )}` );
  return {
    phoneId,
    displayPhoneNumber: data?.displayPhoneNumber || '',
    verifiedName: data?.verifiedName || '',
    status: data?.status || '',
    platformType: data?.platformType || '',
    qualityRating: data?.qualityRating || '',
    throughputLevel: data?.throughputLevel || '',
    messagesPerSecond: data?.messagesPerSecond ?? null,
  };
}

export interface DirectSendButton { type: 'reply' | 'url'; text: string; id?: string; url?: string; }

// `betaGated` and `restricted` are DIFFERENT conditions and must stay separate.
// betaGated  = Graph code 100 whose error_data.details says the category requires
//              Direct Send, i.e. this WABA is not onboarded yet.
// restricted = 139200 / 131064, i.e. access existed and Meta enforcement blocked or
//              capped it. Conflating the two is what made the not-onboarded case
//              impossible to explain in the UI.
export interface DirectSendResult { success: boolean; error?: string; directSendHint?: string; betaGated?: boolean; restricted?: boolean; result?: any; }

export async function directSend (
  phoneId: string,
  payload: { to: string; category: 'utility' | 'authentication'; text: string; templateName?: string; ttlSeconds?: number; buttons?: DirectSendButton[] }
): Promise<DirectSendResult> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/direct-send`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...payload } ),
  } );
  if ( data?.error )
  {
    const msg = typeof data.error === 'string' ? data.error : ( data.error?.message || data.error?.error?.message || JSON.stringify( data.error ) );
    return { success: false, error: msg, directSendHint: data.directSendHint, betaGated: data.betaGated, restricted: data.restricted };
  }
  return { success: true, result: data?.result };
}

// `directSendUploadSample` was removed on 2026-10-06. It POSTed to
// /{waba_id}/message_samples, which appears in none of Meta's Direct Send
// documentation and could not be corroborated. The backend route now answers 410.

export interface GeneratedTemplate { name: string; status: string; category: string; correct_category?: string; source: string; language: string; }

export async function listGeneratedTemplates ( wabaId: string ): Promise<{ total: number; templates: GeneratedTemplate[] }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/direct-send/templates?wabaId=${encodeURIComponent( wabaId )}` );
  return { total: data?.total || 0, templates: data?.templates || [] };
}

export async function getMmOnboardingStatus ( wabaId: string ): Promise<{ onboardingStatus: string; time: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/mm-onboarding-status?wabaId=${encodeURIComponent( wabaId )}` );
  return { onboardingStatus: data?.onboardingStatus || '', time: data?.time || '' };
}

export interface CatalogFlowEntry { flowIdWaba1?: string; flowIdWaba2?: string; flowCode?: string; cta?: string; body?: string; }

export async function getCatalogFlowMap (): Promise<Record<string, CatalogFlowEntry>> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-flow-map` );
  return data?.map || {};
}

export async function upsertCatalogFlowMap (
  entry: { retailerId: string; flowIdWaba1?: string; flowIdWaba2?: string; flowCode?: string; cta?: string; body?: string; delete?: boolean }
): Promise<{ success: boolean; map?: Record<string, CatalogFlowEntry>; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-flow-map`, {
    method: 'POST', body: JSON.stringify( entry ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true, map: data?.map };
}

export async function sendMarketingMessage (
  phoneId: string,
  payload: { to: string; templateName: string; language?: string; params?: string[]; messageActivitySharing?: boolean }
): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/marketing-message`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...payload } ),
  } );
  if ( data?.error )
  {
    const msg = typeof data.error === 'string' ? data.error : ( data.error?.message || data.error?.error?.message || JSON.stringify( data.error ) );
    return { success: false, error: msg };
  }
  return { success: true };
}

export interface LinkPreviewResult { url: string; ok: boolean; og: Record<string, string>; warnings: string[]; note?: string; }

export async function checkLinkPreview ( url: string ): Promise<LinkPreviewResult> {
  const data = await apiCall<LinkPreviewResult>( `${WA_BIZ_BASE}/link-preview`, {
    method: 'POST',
    body: JSON.stringify( { url } ),
  } );
  return data || { url, ok: false, og: {}, warnings: [ 'No response from server' ] };
}

export interface AssignedUser { id: string; name: string; user_type?: string; }

export async function listAssignedUsers ( wabaId: string, business: string ): Promise<{ users: AssignedUser[]; total: number }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users?wabaId=${wabaId}&business=${encodeURIComponent( business )}` );
  return { users: data?.users || data?.data || [], total: data?.summary?.total_count || 0 };
}

export async function addAssignedUser ( wabaId: string, user: string, tasks: string[] ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users`, {
    method: 'POST', body: JSON.stringify( { wabaId, user, tasks } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function removeAssignedUser ( wabaId: string, user: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users?wabaId=${wabaId}`, {
    method: 'DELETE', body: JSON.stringify( { wabaId, user } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function listAssignedWabas ( userId: string ): Promise<Array<{ id: string; name?: string }>> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-wabas?userId=${userId}` );
  return data?.wabas || [];
}

export interface AiPolicyMarket { countryCode: string; country?: string; effectiveDate?: string; active?: boolean; note?: string; }

export async function listAiPolicyMarkets (): Promise<{ markets: AiPolicyMarket[]; activeCount: number; analyticsPricingCategory: string; webhookPricingCategory: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy` );
  return {
    markets: data?.markets || [],
    activeCount: data?.activeCount || 0,
    analyticsPricingCategory: data?.analyticsPricingCategory || 'AI_BOT',
    webhookPricingCategory: data?.webhookPricingCategory || 'general_purpose_ai',
  };
}

export async function upsertAiPolicyMarket ( market: AiPolicyMarket ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy`, {
    method: 'POST', body: JSON.stringify( market ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function deleteAiPolicyMarket ( countryCode: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy?countryCode=${encodeURIComponent( countryCode )}`, { method: 'DELETE' } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

// ═══════════════════════════════════════════════════════════════════
// Meta Business AI Agent — management API (POST ${API_BASE}/meta-agent)
// The Lambda dispatches on `action`; every call takes a WABA entity.
// ═══════════════════════════════════════════════════════════════════

export type WabaKey = 'WABA1' | 'WABA2';

export interface AgentSettings {
  agent_id?: string;
  channel?: string;
  rollout?: { enabled: boolean };
  handoff?: { enabled: boolean; message?: string };
  followup?: { enabled: boolean; followup_interval_in_seconds?: number; message?: string };
  ai_audience?: 'ALLOWLISTED_ONLY' | 'EVERYONE';
}

export interface AgentBusinessInfo {
  payment_method?: string;
  return_policy?: string;
  purchase_info?: string;
  delivery_and_shipping?: string;
  business_description?: string;
  contact_info?: { email?: string; hours_of_operation?: string; address?: string };
}

export interface AgentFaq {
  id?: string;
  question: string;
  answer: string;
  created_at?: number;
}

export interface AgentAllowlistEntry {
  id: string;
  consumer_phone_number: string;
}

async function metaAgent<T> ( action: string, params: Record<string, unknown> = {} ): Promise<T | null> {
  return apiCall<T>( `${API_BASE}/meta-agent`, {
    method: 'POST',
    body: JSON.stringify( { action, ...params } ),
  } );
}

export const aiAgentApi = {
  eligibility: ( waba: WabaKey ) =>
    metaAgent<{ eligibility: { is_eligible?: boolean }; entityId: string }>( 'eligibility', { waba } ),

  getSettings: ( waba: WabaKey ) =>
    metaAgent<{ settings: AgentSettings[] | AgentSettings; entityId: string }>( 'settings', { waba } ),

  updateSettings: ( waba: WabaKey, settings: Partial<AgentSettings> & { enabled?: boolean; aiAudience?: string } ) =>
    metaAgent<{ settings: AgentSettings; entityId: string }>( 'settings_update', { waba, ...settings } ),

  enable: ( waba: WabaKey ) => metaAgent<unknown>( 'enable', { waba } ),
  disable: ( waba: WabaKey ) => metaAgent<unknown>( 'disable', { waba } ),

  getBusinessInfo: ( waba: WabaKey ) =>
    metaAgent<{ business_info: AgentBusinessInfo; entityId: string }>( 'business_info', { waba } ),

  updateBusinessInfo: ( waba: WabaKey, businessInfo: AgentBusinessInfo ) =>
    metaAgent<{ business_info: AgentBusinessInfo; entityId: string }>( 'business_info_update', { waba, businessInfo } ),

  listFaqs: ( waba: WabaKey ) =>
    metaAgent<{ faqs: AgentFaq[]; entityId: string }>( 'faq', { waba } ),

  createFaq: ( waba: WabaKey, question: string, answer: string ) =>
    metaAgent<{ faq: AgentFaq; entityId: string }>( 'faq_create', { waba, question, answer } ),

  updateFaq: ( waba: WabaKey, faqId: string, question: string, answer: string ) =>
    metaAgent<{ faq: AgentFaq; entityId: string }>( 'faq_update', { waba, faqId, question, answer } ),

  deleteFaq: ( waba: WabaKey, faqId: string ) =>
    metaAgent<{ deleted: boolean }>( 'faq_delete', { waba, faqId } ),

  listAllowlist: ( waba: WabaKey ) =>
    metaAgent<{ allowlist: AgentAllowlistEntry[]; entityId: string }>( 'allowlist', { waba } ),

  addAllowlist: ( waba: WabaKey, consumerPhoneNumber: string ) =>
    metaAgent<{ entry: AgentAllowlistEntry }>( 'allowlist_add', { waba, consumerPhoneNumber } ),

  removeAllowlist: ( waba: WabaKey, entryId: string ) =>
    metaAgent<{ deleted: boolean }>( 'allowlist_remove', { waba, entryId } ),

  listWebsites: ( waba: WabaKey ) =>
    metaAgent<{ websites: AgentWebsite[]; entityId: string }>( 'websites', { waba } ),

  addWebsite: ( waba: WabaKey, url: string ) =>
    metaAgent<{ website: AgentWebsite; entityId: string }>( 'websites_add', { waba, url } ),

  removeWebsite: ( waba: WabaKey, websiteId: string ) =>
    metaAgent<{ deleted: boolean }>( 'websites_remove', { waba, websiteId } ),

  listSkills: ( waba: WabaKey ) =>
    metaAgent<{ skills: AgentSkill[]; entityId: string }>( 'skills', { waba } ),

  createSkill: ( waba: WabaKey, title: string, description: string, skill: string ) =>
    metaAgent<{ skill: AgentSkill; entityId: string }>( 'skills_create', { waba, title, description, skill } ),

  updateSkill: ( waba: WabaKey, skillId: string, title: string, description: string, skill: string ) =>
    metaAgent<{ skill: AgentSkill; entityId: string }>( 'skills_update', { waba, skillId, title, description, skill } ),

  deleteSkill: ( waba: WabaKey, skillId: string ) =>
    metaAgent<{ deleted: boolean }>( 'skills_delete', { waba, skillId } ),

  // ── Connectors + Tools (agent_connectors) — enterprise/Tech-Provider ──
  listConnectors: ( waba: WabaKey ) =>
    metaAgent<{ connectors: AgentConnector[] | { error?: unknown }; entityId: string }>( 'connectors', { waba } ),

  addConnector: ( waba: WabaKey, connector: AgentConnectorInput ) =>
    metaAgent<{ created: AgentConnector | { error?: unknown }; entityId: string }>( 'connectors_add', { waba, connector } ),

  removeConnector: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ deleted: boolean; detail?: unknown }>( 'connectors_remove', { waba, connectorId } ),

  listTools: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ tools: AgentTool[] | { error?: unknown }; entityId: string }>( 'tools', { waba, connectorId } ),

  addTool: ( waba: WabaKey, connectorId: string, tool: Record<string, unknown> ) =>
    metaAgent<{ created: AgentTool | { error?: unknown }; entityId: string }>( 'tools_add', { waba, connectorId, tool } ),

  removeTool: ( waba: WabaKey, connectorId: string, toolId: string ) =>
    metaAgent<{ deleted: boolean; detail?: unknown }>( 'tools_remove', { waba, connectorId, toolId } ),

  runTool: ( waba: WabaKey, connectorId: string, toolId: string, input: string ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'tools_run', { waba, connectorId, toolId, input } ),

  // ── Tech Provider panel extras ──
  getConnector: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ connector: AgentConnector; entityId: string }>( 'connector_get', { waba, connectorId } ),

  connectorLogs: ( waba: WabaKey, connectorId: string, includeStats = true ) =>
    metaAgent<{ logs: AgentConnectorLogs | { error?: unknown }; entityId: string }>( 'connector_logs', { waba, connectorId, includeStats } ),

  upsertConnectorApiKey: ( waba: WabaKey, connectorId: string, headerName: string, headerValue: string, prefix?: string ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'connector_upsert_apikey', { waba, connectorId, headerName, headerValue, prefix } ),

  upsertConnectorOAuth: ( waba: WabaKey, connectorId: string, auth: Record<string, unknown> ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'connector_upsert_oauth', { waba, connectorId, auth } ),

  // Consolidated Tech Provider overview for both WABAs (or one, if waba passed)
  providerStatus: ( waba?: WabaKey ) =>
    metaAgent<{ providers: AgentProviderStatus[] }>( 'provider_status', waba ? { waba } : {} ),

  // Tech Partner upgrade readiness — live measurement of the 4 eligibility gates.
  techPartnerReadiness: () =>
    metaAgent<TechPartnerReadiness>( 'tp_eligibility' ),
};

export interface TechPartnerGate { pass: boolean; label: string; }
export interface TechPartnerReadiness {
  eligible: boolean;
  checkedAt: number;
  gates: {
    provider: TechPartnerGate & { detail?: string };
    quality: TechPartnerGate & {
      byWaba: Record<string, { phone?: string; rating?: string; status?: string; ok: boolean }>;
    };
    volume: TechPartnerGate & {
      avgPerDay: number; threshold: number; total7d: number;
      byWaba: Record<string, { total7d: number; points: number }>;
    };
    clients: TechPartnerGate & {
      active: number; threshold: number; error?: string;
      ownedWabas?: number; testCount?: number;
      clientList?: Array<{ id: string; name: string; isTest: boolean }>;
    };
  };
}

// ═══════════════════════════════════════════════════════════════════
// Marketing Ads — Ads that Click to WhatsApp (CTWA) via the Marketing API
// (POST ${API_BASE}/marketing-ads, dispatched on `action`). Everything is
// created PAUSED; publishing an ad is an explicit, separate call.
// ═══════════════════════════════════════════════════════════════════
export interface AdAccount { id: string; account_id: string; name: string; account_status: number; currency: string; }
export interface FbPage { id: string; name: string; }
export interface AdEntity { id: string; name?: string; status?: string; effective_status?: string; objective?: string; adset_id?: string; campaign_id?: string; created_time?: string; }

async function marketingAds<T> ( action: string, params: Record<string, unknown> = {} ): Promise<T | null> {
  return apiCall<T>( `${API_BASE}/marketing-ads`, {
    method: 'POST',
    body: JSON.stringify( { action, ...params } ),
  } );
}

export const marketingAdsApi = {
  adAccounts: () => marketingAds<{ adAccounts: { data?: AdAccount[] } }>( 'ad_accounts' ),
  pages: () => marketingAds<{ pages: { data?: FbPage[] } }>( 'pages' ),
  campaigns: ( adAccountId?: string ) =>
    marketingAds<{ campaigns: { data?: AdEntity[] } }>( 'campaigns', adAccountId ? { adAccountId } : {} ),
  ads: ( adAccountId?: string ) =>
    marketingAds<{ ads: { data?: AdEntity[] } }>( 'ads', adAccountId ? { adAccountId } : {} ),
  uploadImage: ( imageData: string, contentType = 'image/jpeg', adAccountId?: string ) =>
    marketingAds<{ imageHash: string | null; raw: unknown }>( 'upload_image', { imageData, contentType, adAccountId } ),
  // One-shot create of campaign+adset+creative+ad (all PAUSED).
  fullCreate: ( input: MarketingAdInput ) =>
    marketingAds<{ created?: Record<string, { id?: string; error?: unknown }>; error?: string; steps?: unknown }>( 'full_create', input as unknown as Record<string, unknown> ),
  publish: ( adId: string ) => marketingAds<{ updated: unknown; status: string }>( 'ad_publish', { adId } ),
  pause: ( adId: string ) => marketingAds<{ updated: unknown; status: string }>( 'ad_pause', { adId } ),
  adStatus: ( adId: string ) => marketingAds<{ ad: AdEntity }>( 'ad_status', { adId } ),
};

export interface MarketingAdInput {
  name: string;
  objective?: 'OUTCOME_ENGAGEMENT' | 'OUTCOME_LEADS' | 'OUTCOME_SALES' | 'OUTCOME_TRAFFIC';
  optimizationGoal?: string;
  waba?: WabaKey;
  adAccountId?: string;
  pageId?: string;
  whatsappPhoneNumber?: string;
  dailyBudget: number;          // minor units (paise for INR); must be > ~9600
  headline?: string;
  primaryText?: string;
  description?: string;
  greeting?: string;
  autofill?: string;
  imageHash?: string;
  targeting?: Record<string, unknown>;
}

// ── Meta Business Agent connectors (external APIs the agent can call) ──
export interface AgentConnector {
  id: string;
  name: string;
  description?: string;
  base_url?: string;
  auth_type?: 'OAUTH2_CLIENT_CREDENTIALS' | 'API_KEY' | 'NONE' | string;
  connection_status?: { status?: string; error_message?: string };
}

export interface AgentConnectorInput {
  name: string;                 // letters/numbers/underscores only
  description: string;
  base_url: string;
  auth_type: 'API_KEY' | 'NONE' | 'OAUTH2_CLIENT_CREDENTIALS';
  auth_config?: {
    api_key?: {
      headers?: { field_name: string; value: string; prefix?: string }[];
      query_params?: { field_name: string; value: string; prefix?: string }[];
      body_params?: { field_name: string; value: string; prefix?: string }[];
    };
  };
}

export interface AgentTool {
  id?: string;
  name?: string;
  description?: string;
  [ k: string ]: unknown;
}

export interface AgentConnectorLogs {
  data?: Array<Record<string, unknown>>;
  stats?: {
    total?: number;
    success?: number;
    error?: number;
    success_rate?: number;
    [ k: string ]: unknown;
  };
  [ k: string ]: unknown;
}

export interface AgentProviderStatusConnector {
  id: string;
  name?: string;
  status?: string;
  authType?: string;
  baseUrl?: string;
}

export interface AgentProviderStatus {
  waba: WabaKey;
  entityId: string;
  wabaId: string;
  eligible: boolean;
  eligibilityStatus: number;
  eligibility?: unknown;
  connectorsReadable: boolean;
  workspaceProvisioned: boolean;
  connectorCount: number;
  connectors: AgentProviderStatusConnector[];
}

export interface AgentWebsite {
  id: string;
  url: string;
  crawl_status?: string;
}

export interface AgentSkill {
  id?: string;
  title?: string;
  description?: string;
  skill: string;
  created_at?: number;
}

// ── AI Hybrid Routing (which triggers the bot handles vs the Meta AI) ──
export interface AiRoutingConfig {
  enabled: boolean;
  keywords: string[];
  contains: string[];
  types: string[];
  commandPrefix: string;
}

export async function getAiRouting (): Promise<{ routing: AiRoutingConfig; defaults: AiRoutingConfig } | null> {
  return apiCall<{ routing: AiRoutingConfig; defaults: AiRoutingConfig }>( `${API_BASE}/wa-business/ai-routing` );
}

export async function updateAiRouting ( cfg: Partial<AiRoutingConfig> ): Promise<{ success: boolean; routing: AiRoutingConfig } | null> {
  return apiCall<{ success: boolean; routing: AiRoutingConfig }>( `${API_BASE}/wa-business/ai-routing`, {
    method: 'POST', body: JSON.stringify( cfg ),
  } );
}

// ============================================================================
// Conversions API for Business Messaging (Click-to-WhatsApp)
// Uses whatsapp_business_manage_events. Logs in-thread conversions (Purchase,
// LeadSubmitted, ...) to Meta so CTWA ad campaigns can optimize & measure.
// ============================================================================
export interface CapiCapturedClick {
  ctwaClid?: string;
  phone?: string;
  wabaId?: string;
  sourceType?: string;
  sourceId?: string;
  headline?: string;
  ts?: number;
}
export interface CapiEventLogEntry {
  ts?: number;
  wabaId?: string;
  event?: string;
  ctwaClid?: string;
  phone?: string;
  value?: number;
  currency?: string;
  ok?: boolean;
  response?: any;
}
export interface CapiStatus {
  wabaId: string;
  partnerAgent: string;
  dataset: { datasetId?: string; wabaId?: string; cached?: boolean; error?: any };
  supportedEvents: string[];
  capturedClicks: CapiCapturedClick[];
  recentEvents: CapiEventLogEntry[];
}

export async function getCapiStatus ( wabaId?: string ): Promise<CapiStatus | null> {
  const qs = wabaId ? `?wabaId=${encodeURIComponent( wabaId )}` : '';
  return apiCall<CapiStatus>( `${API_BASE}/wa-business/capi${qs}` );
}

export async function createCapiDataset ( wabaId: string ): Promise<{ success: boolean; datasetId?: string; error?: any } | null> {
  return apiCall<{ success: boolean; datasetId?: string; error?: any }>( `${API_BASE}/wa-business/capi/dataset`, {
    method: 'POST', body: JSON.stringify( { wabaId } ),
  } );
}

export async function logCapiEvent ( input: {
  wabaId?: string; eventName: string; phone?: string; ctwaClid?: string;
  value?: number; currency?: string; orderId?: string;
} ): Promise<{ success: boolean; datasetId?: string; eventName?: string; result?: any; error?: any } | null> {
  return apiCall<{ success: boolean; datasetId?: string; eventName?: string; result?: any; error?: any }>(
    `${API_BASE}/wa-business/capi/event`, { method: 'POST', body: JSON.stringify( input ) } );
}

// ─────────────────────────────────────────────────────────────────────────────
// Secure file sharing — wecare.digital/get/secure
//
// Two tiers live on the same bucket. `o/` is open and needs no API at all; these
// calls are the gated `secure/` tier, where a named customer verifies over
// WhatsApp OTP and pays per download.
//
// The S3 key never appears in any of these payloads. Objects are stored under an
// opaque `wecare-digital-<uuid>-<uuid>` name and the backend is the only thing
// that knows which key belongs to whom, so the UI works purely in `fileId`.
// ─────────────────────────────────────────────────────────────────────────────

export interface SecureFile {
  fileId: string;
  displayName: string;
  originalFilename: string;
  contentType: string;
  sizeBytes: number;
  pricePaise: number;
  status: 'pending' | 'active' | 'revoked';
  createdAt: string;
  downloadCount: number;
  /** Admin views only — masked to the last four digits, never the full number. */
  ownerName?: string;
  ownerPhoneMasked?: string;
  uploadedBy?: string;
}

export interface SecureUploadTicket {
  fileId: string;
  uploadUrl: string;
  expiresInSeconds: number;
  contentType: string;
}

/**
 * Step 1 of an admin upload: register the customer and the file, and get a
 * presigned PUT back.
 *
 * This is also what creates the Cognito customer, so the mobile number given here
 * is the number that will receive the WhatsApp OTP. Get it wrong and the customer
 * cannot reach the file.
 */
export async function initSecureUpload ( input: {
  name: string;
  mobile: string;
  displayName?: string;
  originalFilename: string;
  contentType: string;
  sizeBytes: number;
} ): Promise<ApiResult<SecureUploadTicket>> {
  return apiCallResult<SecureUploadTicket>( `${API_BASE}/secure-files/upload-init`, {
    method: 'POST',
    body: JSON.stringify( input ),
  } );
}

/**
 * Step 2: PUT the bytes straight to S3.
 *
 * Deliberately a bare `fetch`, not `authFetch` — the presigned URL carries its own
 * SigV4 signature, and adding our Cognito Authorization header would make S3
 * reject the request as having two conflicting auth mechanisms.
 */
export async function uploadSecureFileBytes (
  uploadUrl: string,
  file: File,
  contentType: string,
): Promise<boolean> {
  const response = await fetch( uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: file,
  } );
  return response.ok;
}

/**
 * Step 3: flip the record from pending to active.
 *
 * Separate from step 1 on purpose: the backend re-heads the object before
 * activating, so a browser upload that died half way leaves a pending record the
 * customer can never be charged for rather than a broken active one.
 */
export async function confirmSecureUpload ( fileId: string ): Promise<ApiResult<{
  fileId: string; status: string; sizeBytes: number;
}>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/confirm`, {
    method: 'POST',
  } );
}

/** Admin listing. Pass a mobile number to scope it to one customer via the GSI. */
export async function listSecureFiles ( mobile?: string ): Promise<ApiResult<{
  files: SecureFile[]; count: number;
}>> {
  const qs = mobile ? `?mobile=${encodeURIComponent( mobile )}` : '';
  return apiCallResult( `${API_BASE}/secure-files${qs}` );
}

/** Revoke rather than delete, so the record of who was charged survives. */
export async function revokeSecureFile ( fileId: string ): Promise<ApiResult<{
  fileId: string; status: string;
}>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/revoke`, {
    method: 'POST',
  } );
}

/**
 * Customer-token fetch, for the three routes below.
 *
 * These must NOT go through `apiCall`/`authFetch`. Those attach the Amplify
 * session, which belongs to the **staff** pool (us-east-1_cSx0RHCIR). A customer
 * signs in against a different pool entirely (us-east-1_46ULYuukt) via WhatsApp
 * OTP, and their token lives in sessionStorage rather than in Amplify.
 *
 * Sending a staff token to a customer route does not fail cleanly either: the
 * backend validates it, sees the wrong issuer, and answers 401 - which looks
 * exactly like an expired customer session and would send the customer round the
 * verification loop forever.
 */
async function customerApiCall<T> ( url: string, options?: RequestInit ): Promise<ApiResult<T>> {
  const { getSession, restoreSession } = await import( '../lib/customerAuth' );
  let session;
  try { session = getSession() || await restoreSession(); }
  catch {
    return { ok: false, failure: {
      kind: 'unavailable', status: 503,
      message: 'Sign-in is temporarily unavailable. Please try again.',
      url, retryable: true, at: Date.now(),
    } };
  }

  if ( !session )
  {
    return {
      ok: false,
      failure: {
        kind: 'unauthenticated',
        status: 401,
        message: 'Verification required',
        url,
        retryable: false,
        at: Date.now(),
      },
    };
  }

  try
  {
    const response = await fetch( url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...( options?.headers as Record<string, string> || {} ),
        Authorization: `Bearer ${session.accessToken}`,
      },
    } );

    const text = await response.text();
    const parsed = text ? JSON.parse( text ) : {};

    if ( !response.ok )
    {
      return {
        ok: false,
        failure: {
          // 403 stays `forbidden` rather than collapsing into `http`: it is the
          // status the backend uses for both "not your file" and "grant not
          // redeemable", and the page needs to tell those from a transport error.
          kind: response.status === 401
            ? 'unauthenticated'
            : response.status === 403 ? 'forbidden' : 'http',
          status: response.status,
          message: parsed.message || parsed.error || `Request failed (${response.status})`,
          url,
          retryable: false,
          at: Date.now(),
        },
      };
    }
    return { ok: true, data: parsed as T };
  } catch ( err: any )
  {
    return {
      ok: false,
      failure: {
        kind: 'network',
        status: null,
        message: err?.message || 'Network error',
        url,
        retryable: true,
        at: Date.now(),
      },
    };
  }
}

/** The signed-in customer's own files. Requires a customer-pool token. */
export async function listMySecureFiles (): Promise<ApiResult<{
  files: SecureFile[]; count: number; pricePaise: number;
}>> {
  return customerApiCall( `${API_BASE}/secure-files/mine` );
}

/**
 * Start a paid download. Returns 503 PAYMENT_DISABLED while the backend flag is
 * off, which is the current state — enabling paid downloads is an owner action.
 */
export async function createSecureFileOrder ( fileId: string ): Promise<ApiResult<{
  grantId: string; orderId: string; amountPaise: number; currency: string; keyId: string;
}>> {
  return customerApiCall( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/order`, {
    method: 'POST',
  } );
}

/**
 * Redeem a paid grant for a short-lived download URL.
 *
 * Single use: the backend spends the grant with a conditional write, so calling
 * this twice fails the second time by design. Do not retry on a 403.
 */
export async function redeemSecureFileDownload ( fileId: string, grantId: string ): Promise<ApiResult<{
  downloadUrl: string; expiresInSeconds: number;
}>> {
  return customerApiCall(
    `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/download`
    + `?grant=${encodeURIComponent( grantId )}`,
  );
}

/**
 * Send the ₹49 request to the customer's own WhatsApp as an approved template.
 *
 * This is the primary payment path. The customer pays inside WhatsApp via the
 * `wecare_pay` template's ORDER_DETAILS button, and the file is then delivered on
 * WhatsApp too — so the browser has nothing left to do once this returns 202.
 *
 * It takes no phone number. The backend sends only to the number on the verified
 * token; accepting one here would make this a way to send WhatsApp messages to
 * arbitrary people.
 */
export async function requestFilePaymentOnWhatsApp ( fileId: string ): Promise<ApiResult<{
  grantId: string; reference: string; amountPaise: number; sentTo: string; message: string;
}>> {
  return customerApiCall( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/whatsapp-pay`, {
    method: 'POST',
  } );
}
