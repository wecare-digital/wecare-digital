/**
 * API Service Layer
 * Connects to API Gateway -> Lambda -> DynamoDB
 * NO MOCK DATA - All data fetched from real AWS resources
 * 
 * API Endpoint: Uses NEXT_PUBLIC_API_BASE or defaults to production
 */

import { API_BASE, RETRY_CONFIG } from '../config/constants';
// Configures Amplify before this module's first Auth call; see lib/amplifyConfig.ts.
import '../lib/amplifyConfig';
import { fetchAuthSession } from 'aws-amplify/auth';

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
  /** The server's own refusal code (e.g. `ACCESS_WINDOW_CLOSED`), verbatim, when it sent one. */
  code?: string;
  /** Structured, safe refusal metadata returned by authenticated APIs (for example an existing contact id). */
  details?: Record<string, unknown>;
  url: string;
  /** True when trying the same call again could plausibly succeed. */
  retryable: boolean;
  /**
   * True when a write (POST/PUT/PATCH/DELETE) timed out, lost its connection or got a 5xx, so it
   * may or may not have been applied. Such a write is never re-sent automatically and is not
   * `retryable`: check the record before sending it again.
   */
  outcomeUnknown?: boolean;
  at: number;
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; failure: ApiFailure };

const RETRYABLE_KINDS: ReadonlySet<ApiFailureKind> = new Set<ApiFailureKind>( [
  'server', 'unavailable', 'timeout', 'rate-limited', 'network',
] );

/** Failure kinds after which a write may or may not have been applied. */
const UNCERTAIN_WRITE_KINDS: ReadonlySet<ApiFailureKind> = new Set<ApiFailureKind>( [
  'server', 'unavailable', 'timeout', 'network',
] );

/** The only methods that are re-sent automatically. See sendApiRequest. */
const RETRY_SAFE_METHODS: ReadonlySet<string> = new Set( [ 'GET', 'HEAD' ] );

let lastApiFailure: ApiFailure | null = null;
const failureListeners = new Set<( failure: ApiFailure ) => void>();

/** The most recent failure recorded by any call, or null since the last success. */
export function getLastApiFailure (): ApiFailure | null {
  return lastApiFailure;
}

function recordFailure (
  kind: ApiFailureKind,
  status: number | null,
  message: string,
  url: string,
  code?: string,
  details?: Record<string, unknown>,
  /** True for a POST/PUT/PATCH/DELETE: an uncertain failure then reports `outcomeUnknown`. */
  write = false,
): ApiFailure {
  const outcomeUnknown = write && UNCERTAIN_WRITE_KINDS.has( kind );
  const failure: ApiFailure = {
    kind,
    status,
    message: outcomeUnknown
      ? `${ message.replace( /\.$/, '' ) }. The result is not confirmed; check it before trying again.`
      : message,
    ...( code ? { code } : {} ),
    ...( details ? { details } : {} ),
    url,
    retryable: RETRYABLE_KINDS.has( kind ) && !outcomeUnknown,
    ...( outcomeUnknown ? { outcomeUnknown: true } : {} ),
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

// Get the current Cognito access token for API calls. `forceRefresh` asks Cognito for new
// tokens even when the cached ones have not expired yet.
async function getAuthToken ( forceRefresh = false ): Promise<string | null> {
  try
  {
    const session = await fetchAuthSession( { forceRefresh } );
    return session.tokens?.accessToken?.toString() ?? null;
  } catch
  {
    return null;
  }
}

/** Keep staff credentials within the configured API origin and path prefix. */
function trustedApiUrl ( input: string ): string {
  const base = new URL( API_BASE );
  const target = new URL( input, base );
  const prefix = base.pathname.replace( /\/$/, '' );
  if ( target.origin !== base.origin || target.username || target.password
    || ( target.pathname !== prefix && !target.pathname.startsWith( `${prefix}/` ) ) )
  {
    throw new TypeError( 'Request destination is outside the configured API' );
  }
  // Reconstruct from the trusted base; callers control only the validated path/query.
  base.pathname = target.pathname;
  base.search = target.search;
  base.hash = '';
  return base.href;
}

/* ------------------------------------------------------------------------- *
 * Write safety (WEB-2)
 *
 * A write is never re-sent automatically after a timeout, a network error or a 5xx: the first
 * attempt may have succeeded, and replays of slow sends produced duplicate WhatsApp messages and
 * the "Sending is not confirmed" payment state. Each write call carries one Idempotency-Key, so a
 * server that dedupes by key can recognise the same action; only the call's own 401 retry
 * reuses it, and a new staff action gets a new key.
 * ------------------------------------------------------------------------- */

/** API paths whose handler reads `idempotencyKey` from the JSON body (outbound-whatsapp lists it
 *  in _SEND_FIELDS). Other handlers reject unknown body fields: read the handler before adding. */
const BODY_IDEMPOTENCY_PATHS: readonly string[] = [ '/whatsapp/send' ];

function newIdempotencyKey (): string | null {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : null;
}

/**
 * The write request with this call's Idempotency-Key. A caller that sends the same action again
 * on purpose can pass its own `Idempotency-Key` header, which is kept. The header is sent only to
 * a same-origin API: the API's CORS configuration does not allow it, so a cross-origin caller
 * (the native app shell, local development) would fail its preflight. The body copy has no such
 * limit.
 */
function withIdempotencyKey ( destination: string, init: RequestInit = {} ): RequestInit {
  const headers: Record<string, string> = { ...( init.headers as Record<string, string> | undefined ) };
  const supplied = Object.keys( headers ).find( ( name ) => name.toLowerCase() === 'idempotency-key' );
  const key = supplied ? headers[ supplied ] : newIdempotencyKey();
  if ( !key ) return init;
  const target = new URL( destination );
  const prefix = new URL( API_BASE ).pathname.replace( /\/$/, '' );
  let body = init.body;
  if ( typeof body === 'string' && BODY_IDEMPOTENCY_PATHS.some( ( p ) => target.pathname === prefix + p ) )
  {
    try
    {
      const parsed: unknown = JSON.parse( body );
      if ( parsed && typeof parsed === 'object' && !Array.isArray( parsed ) && !( 'idempotencyKey' in parsed ) )
      {
        body = JSON.stringify( { ...parsed, idempotencyKey: key } );
      }
    } catch { /* not JSON: sent unchanged */ }
  }
  if ( !supplied && typeof window !== 'undefined' && target.origin === window.location.origin )
  {
    headers[ 'Idempotency-Key' ] = key;
  }
  return { ...init, body, headers };
}

function isWriteMethod ( init?: RequestInit ): boolean {
  return !RETRY_SAFE_METHODS.has( ( init?.method || 'GET' ).toUpperCase() );
}

/**
 * Authenticated fetch — attaches the Cognito access token as a Bearer header.
 * Use on pages that make raw fetch() calls to protected API routes instead of
 * going through apiCall(). Unauthenticated/webhook routes simply ignore it.
 */
export async function authFetch ( input: string, init: RequestInit = {} ): Promise<Response> {
  const destination = trustedApiUrl( input );
  const request = isWriteMethod( init ) ? withIdempotencyKey( destination, init ) : init;
  const token = await getAuthToken();
  return fetch( destination, {
    ...request,
    headers: {
      'Content-Type': 'application/json',
      ...( request.headers as Record<string, string> || {} ),
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

/** One prepared API request; see sendApiRequest. */
interface ApiRequest {
  url: string;
  destination: string;
  options?: RequestInit;
  write: boolean;
  timeoutMs: number;
  allowRetries: boolean;
}

async function sendApiRequest<T> ( request: ApiRequest, retryCount: number, tokenRefreshed: boolean ): Promise<ApiResult<T>> {
  const { url, destination, options, write, timeoutMs, allowRetries } = request;
  try
  {
    const controller = new AbortController();
    const timeoutId = setTimeout( () => controller.abort(), timeoutMs ); // Per-operation timeout; 8 seconds by default

    // Inject Cognito auth token
    const token = await getAuthToken();
    const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    const response = await fetch( destination, {
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

    // Parse a structured refusal once. Callers that need to recover from an expected 4xx
    // (for example, resolving the canonical customer behind a duplicate 409) must not have to
    // scrape a human-readable message. The body remains authenticated API data and is never
    // written to logs here.
    let errorBody: Record<string, unknown> | null = null;
    try
    {
      const parsed = await response.clone().json();
      if ( parsed && typeof parsed === 'object' && !Array.isArray( parsed ) )
      {
        errorBody = parsed as Record<string, unknown>;
      }
    } catch { /* non-JSON refusal; status text remains the fallback */ }

    // Handle specific HTTP errors
    let kind: ApiFailureKind = 'http';
    let message: string;

    if ( response.status === 401 )
    {
      // Send once more, and only with a token Cognito has just refreshed. A 401 means the
      // request was refused before the handler did anything, so this holds for writes too.
      if ( !tokenRefreshed && await getAuthToken( true ) )
      {
        console.debug( 'Got 401, retrying with a refreshed token...' );
        return sendApiRequest<T>( request, retryCount, true );
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
      if ( allowRetries && retryCount < RETRY_CONFIG.maxRetries )
      {
        const delayMs = Math.min(
          RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount ),
          RETRY_CONFIG.maxDelayMs
        );
        console.debug( `Retrying API call (${retryCount + 1}/${RETRY_CONFIG.maxRetries}) after ${delayMs}ms...` );
        await delay( delayMs );
        return sendApiRequest<T>( request, retryCount + 1, tokenRefreshed );
      }
    } else if ( response.status === 429 )
    {
      // Rate limited - retry with backoff
      if ( allowRetries && retryCount < RETRY_CONFIG.maxRetries )
      {
        const delayMs = Math.min(
          RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount + 1 ),
          RETRY_CONFIG.maxDelayMs
        );
        console.debug( `Rate limited, retrying after ${delayMs}ms...` );
        await delay( delayMs );
        return sendApiRequest<T>( request, retryCount + 1, tokenRefreshed );
      }
      kind = 'rate-limited';
      message = 'Rate limited - too many requests';
    } else
    {
      // Prefer the server's safe refusal text, while preserving the structured body below.
      const nestedError = errorBody?.error;
      const nestedMessage = (
        nestedError && typeof nestedError === 'object' && !Array.isArray( nestedError )
          ? ( nestedError as Record<string, unknown> ).message
          : undefined
      );
      const msg = (
        typeof nestedMessage === 'string' ? nestedMessage
          : typeof nestedError === 'string' ? nestedError
            : typeof errorBody?.message === 'string' ? errorBody.message
              : ''
      );
      message = msg
        ? `HTTP ${response.status}: ${msg}`
        : `HTTP ${response.status}: ${response.statusText}`;
    }

    const refusalCode = errorBody?.errorCode ?? errorBody?.code;
    const failure = recordFailure(
      kind,
      response.status,
      message,
      url,
      typeof refusalCode === 'string' ? refusalCode : undefined,
      errorBody || undefined,
      write,
    );
    console.error( `API error: ${failure.message}`, url );
    return { ok: false, failure };
  } catch ( e: any )
  {
    // Retry on network errors
    if ( allowRetries && retryCount < RETRY_CONFIG.maxRetries && ( e.name === 'AbortError' || e.name === 'TypeError' ) )
    {
      const delayMs = Math.min(
        RETRY_CONFIG.baseDelayMs * Math.pow( 2, retryCount ),
        RETRY_CONFIG.maxDelayMs
      );
      console.debug( `Network error, retrying (${retryCount + 1}/${RETRY_CONFIG.maxRetries}) after ${delayMs}ms...` );
      await delay( delayMs );
      return sendApiRequest<T>( request, retryCount + 1, tokenRefreshed );
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
    const failure = recordFailure( kind, null, message, url, undefined, undefined, write );
    console.error( 'API call failed:', failure.message, url, e );
    return { ok: false, failure };
  }
}

/**
 * API call with retry logic that reports the reason a request failed.
 *
 * GET and HEAD back off and retry on 429/502/503/504 and network errors, up to
 * `RETRY_CONFIG.maxRetries`, unless `allowRetries` is false. POST, PUT, PATCH and DELETE are
 * never retried after a timeout, a network error, a 429 or a 5xx: they carry an Idempotency-Key
 * (see withIdempotencyKey), and an uncertain failure is reported with `outcomeUnknown`. Any
 * method that gets a 401 is sent once more, and only after `fetchAuthSession({ forceRefresh:
 * true })` returned a new token.
 */
export async function apiCallResult<T> ( url: string, options?: RequestInit, retryCount = 0, timeoutMs = 8000, allowRetries = true ): Promise<ApiResult<T>> {
  let destination: string;
  try { destination = trustedApiUrl( url ); }
  catch {
    return { ok: false, failure: recordFailure(
      'http', null, 'Request destination is outside the configured API', API_BASE,
    ) };
  }
  const write = isWriteMethod( options );
  return sendApiRequest<T>( {
    url,
    destination,
    options: write ? withIdempotencyKey( destination, options ) : options,
    write,
    timeoutMs,
    allowRetries: allowRetries && !write,
  }, retryCount, false );
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


// ----------------------------------------------------------------------------
// Relocated shared declarations (FEAT-002): used by more than one domain module.
// ----------------------------------------------------------------------------

/** Shared base URL for the WhatsApp Business HTTP API (used by commerce + whatsapp domains). */
export const WA_BIZ_BASE = `${API_BASE}/wa-business`;

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

// The three pure normalizers are public (re-exported by the barrel) and are
// also consumed by the domain modules. The behavioural tests extract their
// bodies from THIS file by name (see tests/api-client-normalizers.test.mjs).
export { normalizeCheckoutAddress, normalizeEpochSeconds, normalizeTimestamp };

// Internal helpers consumed by the domain modules. These are NOT part of the
// public barrel surface; src/api/client.ts re-exports only the previously-public names.
export { apiCall, delay, getAuthToken, recordFailure };
