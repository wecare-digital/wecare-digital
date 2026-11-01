/**
 * WhatsApp-OTP sign-in for customers, against the customer Cognito pool.
 *
 * Why this exists instead of using Amplify Auth
 * ---------------------------------------------
 * There are two Cognito pools in this account and they are deliberately separate:
 *
 *   us-east-1_cSx0RHCIR   WECARE.DIGITAL            staff. Admin/Operator/Viewer.
 *   us-east-1_46ULYuukt   WECARE.DIGITAL-CUSTOMERS  customers. Phone-keyed, CUSTOM_AUTH.
 *
 * `aws-amplify/auth` is configured against the staff pool, so `fetchAuthSession`
 * returns a staff session and cannot speak to the customer pool at all. Pointing
 * Amplify at the customer pool instead would break every staff page.
 *
 * So this talks to the Cognito Identity Provider REST API directly. That needs no
 * SDK and no credentials: InitiateAuth and RespondToAuthChallenge are public,
 * unauthenticated endpoints, and the app client was created with
 * `GenerateSecret: false`, so no SECRET_HASH is required either.
 *
 * The OTP itself is delivered over WhatsApp by the pool's CreateAuthChallenge
 * trigger. Nothing here sees or handles the code beyond passing back what the
 * customer typed.
 *
 * Token storage
 * -------------
 * The access token goes in `sessionStorage`, not `localStorage`: it is valid for
 * 60 minutes. A server-owned session uses an HttpOnly cookie and an encrypted
 * refresh token. Only a CSRF/expiry hint is kept in localStorage; it cannot
 * authorize a request. Customers may opt out of a persistent cookie on shared
 * devices. Short access tokens remain readable by same-origin script and expire
 * quickly; customer APIs validate them against the customer pool.
 */

const REGION = process.env.NEXT_PUBLIC_COGNITO_REGION || 'us-east-1';
/** Public identifiers. Neither is a secret; both are safe in client code. */
const CLIENT_ID = process.env.NEXT_PUBLIC_CUSTOMER_CLIENT_ID || '4avmt9n4gpmkvkdk88qbtit33o';

const ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;
const TOKEN_KEY = 'wecare.customer.accessToken';
const EXPIRY_KEY = 'wecare.customer.expiresAt';

const SESSION_ENDPOINT = '/api/ecommerce/customer-session';
const PROFILE_ENDPOINT = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/customer/profile`;
const SESSION_HINT_KEY = 'wecare.customer.sessionHint';
const SESSION_HINT_COOKIE = 'wc_customer_session_hint';
interface SessionHint { csrfToken: string; expiresAt: number; persistent: boolean; }
let refreshInFlight: Promise<CustomerSession | null> | null = null;

// Logout in another tab invalidates this tab's cached access token as well.
if ( typeof window !== 'undefined' ) window.addEventListener( 'storage', event => {
  if ( event.key === SESSION_HINT_KEY && event.newValue === null ) {
    window.sessionStorage.removeItem( TOKEN_KEY );
    window.sessionStorage.removeItem( EXPIRY_KEY );
  }
} );

function sessionHint (): SessionHint | null {
  if ( typeof window === 'undefined' ) return null;
  try {
    let hint = JSON.parse( window.localStorage.getItem( SESSION_HINT_KEY ) || 'null' ) as SessionHint | null;
    if ( !hint?.csrfToken ) {
      const raw = document.cookie.split( '; ' ).find( row => row.startsWith( `${ SESSION_HINT_COOKIE }=` ) )?.slice( SESSION_HINT_COOKIE.length + 1 );
      if ( raw ) {
        hint = JSON.parse( decodeURIComponent( raw ) ) as SessionHint;
        if ( hint?.csrfToken && hint.expiresAt > Date.now() ) {
          window.localStorage.setItem( SESSION_HINT_KEY, JSON.stringify( hint ) );
        }
        document.cookie = `${ SESSION_HINT_COOKIE }=; Path=/; Max-Age=0; SameSite=Lax; Secure`;
      }
    }
    if ( !hint?.csrfToken || hint.expiresAt <= Date.now() ) return null;
    return hint;
  } catch {
    document.cookie = `${ SESSION_HINT_COOKIE }=; Path=/; Max-Age=0; SameSite=Lax; Secure`;
    return null;
  }
}

/** Restore the server-owned session. A transient failure keeps the hint for a later retry. */
export async function restoreSession (): Promise<CustomerSession | null> {
  const current = getSession();
  if ( current ) return current;
  const hint = sessionHint();
  if ( !hint ) return null;
  if ( refreshInFlight ) return refreshInFlight;
  refreshInFlight = ( async () => {
    const response = await fetch( SESSION_ENDPOINT, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Customer-CSRF': hint.csrfToken },
      body: JSON.stringify( { action: 'refresh' } ),
    } );
    if ( response.status === 401 ) {
      window.localStorage.removeItem( SESSION_HINT_KEY );
      return null;
    }
    if ( !response.ok ) throw new Error( 'Sign-in is temporarily unavailable. Please try again.' );
    const renewed = await response.json() as CustomerSession;
    if ( !renewed.accessToken || renewed.expiresAt <= Date.now() ) throw new Error( 'Sign-in could not be renewed.' );
    storeSession( renewed.accessToken, renewed.expiresAt );
    return renewed;
  } )();
  try { return await refreshInFlight; } finally { refreshInFlight = null; }
}

export interface OtpChallenge {
  session: string;
  /** Masked by the Cognito trigger, e.g. `********0044`. Never the full number. */
  destination: string;
  expiresInSeconds: number;
  /**
   * Whether this number is a registered customer.
   *
   * Cognito returns a challenge either way, so without this the caller cannot tell
   * "wrong number" from "message is slow" — and for an unregistered number no code
   * is ever sent, so they wait forever. The trigger sets this explicitly.
   *
   * It does make the endpoint enumerable; see the note in the Cognito trigger.
   */
  registered: boolean;
}

export interface CustomerSession {
  accessToken: string;
  expiresAt: number;
  /**
   * Whether the server-owned "keep me signed in" session was established. Additive and
   * optional: `restoreSession` and `getSession` never read it, so an absent value is the
   * same as before this field existed.
   *
   * `false` means the shopper IS signed in for this tab but the device will not be
   * remembered past the access token's hour. See `submitOtp`.
   */
  remembered?: boolean;
}

async function cognito<T> ( target: string, body: unknown ): Promise<T> {
  const response = await fetch( ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify( body ),
  } );

  const text = await response.text();
  const parsed = text ? JSON.parse( text ) : {};

  if ( !response.ok )
  {
    // Cognito puts the useful part in __type, e.g. NotAuthorizedException.
    const kind = String( parsed.__type || '' ).split( '#' ).pop() || 'RequestFailed';
    const error = new Error( parsed.message || kind );
    error.name = kind;
    throw error;
  }
  return parsed as T;
}

/**
 * Ask for an OTP over WhatsApp.
 *
 * `PreventUserExistenceErrors` is enabled on the app client, so an unknown number
 * still returns a challenge with a masked destination rather than an error. That is
 * deliberate - it stops this endpoint being used to discover which numbers are
 * registered - and it means "no code arrived" is indistinguishable here from "not a
 * customer". The UI must say so rather than claiming a code was sent.
 */
export async function requestOtp ( mobile: string ): Promise<OtpChallenge> {
  const normalised = normaliseMobile( mobile );
  const result = await cognito<{
    Session?: string;
    ChallengeParameters?: Record<string, string>;
  }>( 'InitiateAuth', {
    ClientId: CLIENT_ID,
    AuthFlow: 'CUSTOM_AUTH',
    AuthParameters: { USERNAME: normalised },
  } );

  return {
    session: result.Session || '',
    destination: result.ChallengeParameters?.destination || '',
    expiresInSeconds: Number( result.ChallengeParameters?.expiresInSeconds || 600 ),
    // Absent means an older deployed trigger; treat that as registered so the flow
    // still works rather than wrongly telling a real customer they are unknown.
    registered: result.ChallengeParameters?.registered !== 'false',
  };
}

/**
 * Submit the code. Returns null when it was wrong but attempts remain, so the UI
 * can invite a retry; throws when Cognito has failed the whole attempt.
 */
export async function submitOtp (
  mobile: string,
  code: string,
  session: string,
  persistent = true,
): Promise<CustomerSession | null> {
  const normalised = normaliseMobile( mobile );
  const result = await cognito<{
    AuthenticationResult?: { AccessToken?: string; RefreshToken?: string; ExpiresIn?: number };
    Session?: string;
    ChallengeName?: string;
  }>( 'RespondToAuthChallenge', {
    ClientId: CLIENT_ID,
    ChallengeName: 'CUSTOM_CHALLENGE',
    Session: session,
    ChallengeResponses: { USERNAME: normalised, ANSWER: code.trim() },
  } );

  const token = result.AuthenticationResult?.AccessToken;
  if ( !token )
  {
    // Cognito rotates the challenge session after a wrong code; preserve it for the next try.
    if ( result.Session ) {
      const mismatch = new Error( 'Check the code and try again.' ) as Error & { session: string };
      mismatch.name = 'CodeMismatchException';
      mismatch.session = result.Session;
      throw mismatch;
    }
    return null;
  }

  const expiresAt = Date.now() + ( result.AuthenticationResult?.ExpiresIn || 3600 ) * 1000;
  const refreshToken = result.AuthenticationResult?.RefreshToken;

  /*
   * THE TOKEN IS STORED BEFORE THE EXCHANGE, AND THE ORDER IS THE WHOLE POINT.
   *
   * By this line the Cognito challenge has already succeeded and `token` is a valid access
   * token - the shopper IS authenticated. The exchange below buys PERSISTENCE ("keep me
   * signed in on this device"), not authentication.
   *
   * This used to throw on a failed exchange, BEFORE storing anything, which converted a
   * degraded remember-me into a total sign-in failure and discarded a valid token. It also
   * produced the owner's reported outage: the thrown Error carries name 'Error', which matches
   * none of the patterns in the sign-in page's messageForAuthError, so it fell through to the
   * catch-all MSG.TRY_LATER and the page said "Try again shortly." after a CORRECT code.
   * Measured in a real browser on 2026-10-02: alert "Try again shortly.", no navigation, and
   * sessionStorage empty despite a successful RespondToAuthChallenge.
   *
   * So: store first, then attempt the exchange, and report a failed exchange as a degraded
   * session rather than an exception. `restoreSession()` already treats a missing hint as
   * "sign in again", so `remembered: false` is a state the library already models.
   */
  storeSession( token, expiresAt );

  /*
   * CLAIM THE EXISTING WHATSAPP CONTACT IMMEDIATELY AFTER AUTHENTICATION.
   *
   * The customer-profile endpoint owns the evidence-checked `checkoutCustomerId` claim and the
   * conditional promotion of any `NEEDS_CUSTOMER_LINK` orders. An empty body is intentional:
   * for an existing WhatsApp-first contact it changes no customer-entered profile field; it only
   * lets the authenticated Cognito subject claim that exact verified-phone row and promotes the
   * already-paid order to website ownership.
   *
   * Best-effort is load-bearing. The Cognito challenge has already succeeded, so a temporary
   * profile/index outage must never turn a correct OTP into a failed sign-in. Customer-profile
   * save and the scheduled reconciler remain idempotent fallbacks.
   */
  // Profile ownership linking and remember-device exchange both require the
  // already-valid Cognito access token, but neither needs the other's result.
  // Start linking now; let the secure refresh-token exchange run alongside it.
  // We still await linking before a successful return, so existing checkout and
  // WhatsApp-first ownership behavior remains intact.
  const profileLinkPromise = ( async () => {
    try {
      await fetch( PROFILE_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          Authorization: `Bearer ${ token }`,
        },
        body: JSON.stringify( {} ),
      } );
    } catch {
      // Authentication succeeded. Linking can retry on profile save / scheduled reconciliation.
    }
  } )();

  if ( refreshToken )
  {
    // Launch the exchange before awaiting the independent profile bootstrap:
    // latency after OTP is the slower operation, not the sum of both.
    const response = await fetch( SESSION_ENDPOINT, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify( { action: 'exchange', refreshToken, persistent } ),
    } );
    await profileLinkPromise;
    if ( !response.ok ) return { accessToken: token, expiresAt, remembered: false };
    // A 200 with an unreadable body is the same class of failure as a non-ok response and must
    // not be allowed to throw either - otherwise the one path this change exists to protect
    // still destroys a valid sign-in.
    const hint = await response.json().catch( () => null ) as SessionHint | null;
    if ( !hint?.csrfToken ) return { accessToken: token, expiresAt, remembered: false };
    window.localStorage.setItem( SESSION_HINT_KEY, JSON.stringify( hint ) );
    return { accessToken: token, expiresAt, remembered: true };
  }

  // No refresh token: preserve the same profile-link completion guarantee.
  await profileLinkPromise;
  return { accessToken: token, expiresAt, remembered: false };
}

/** The session Cognito returns alongside a rejected code, for the next attempt. */
export function nextSessionFrom ( error: unknown ): string {
  return String( ( error as { session?: string } )?.session || '' );
}

export function storeSession ( accessToken: string, expiresAt: number ): void {
  if ( typeof window === 'undefined' ) return;
  window.sessionStorage.setItem( TOKEN_KEY, accessToken );
  window.sessionStorage.setItem( EXPIRY_KEY, String( expiresAt ) );
}

/** The stored token, or null when absent or expired. */
export function getSession (): CustomerSession | null {
  if ( typeof window === 'undefined' ) return null;
  const accessToken = window.sessionStorage.getItem( TOKEN_KEY );
  const expiresAt = Number( window.sessionStorage.getItem( EXPIRY_KEY ) || 0 );
  if ( !accessToken || !expiresAt ) return null;
  // Treat a token inside its last 30 seconds as gone, so a request cannot expire
  // mid-flight and surface as a confusing 401.
  if ( Date.now() > expiresAt - 30_000 )
  {
    window.sessionStorage.removeItem( TOKEN_KEY );
    window.sessionStorage.removeItem( EXPIRY_KEY );
    return null;
  }
  return { accessToken, expiresAt };
}

export function clearSession (): void {
  if ( typeof window === 'undefined' ) return;
  const hint = sessionHint();
  window.sessionStorage.removeItem( TOKEN_KEY );
  window.sessionStorage.removeItem( EXPIRY_KEY );
  window.localStorage.removeItem( SESSION_HINT_KEY );
  if ( hint ) void fetch( SESSION_ENDPOINT, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Customer-CSRF': hint.csrfToken },
    body: JSON.stringify( { action: 'logout' } ),
  } ).catch( () => undefined );
}

/**
 * Digits to E.164, matching the backend's normalisation exactly.
 *
 * If these two ever disagree, a customer signs in successfully and then owns
 * nothing, because the file was registered against a differently-formatted number.
 */
export function normaliseMobile ( raw: string ): string {
  const digits = String( raw || '' ).replace( /\D/g, '' );
  const explicitCountry = String( raw || '' ).trim().startsWith( '+' );
  const withCountry = !explicitCountry && digits.length === 10 && /^[6-9]/.test( digits ) ? `91${digits}` : digits;
  if ( withCountry.length < 10 || withCountry.length > 15 )
  {
    throw new Error( 'Enter a valid mobile number' );
  }
  return `+${withCountry}`;
}
