import { afterEach, beforeEach, expect, it, vi } from 'vitest';

beforeEach( () => { window.localStorage.clear(); window.sessionStorage.clear(); vi.resetModules(); } );
afterEach( () => { vi.unstubAllGlobals(); vi.restoreAllMocks(); } );
const hint = { csrfToken: 'qa-csrf', expiresAt: Date.now() + 86_400_000, persistent: true };
const profile = { status: 'PROFILE_READY', contactId: 'contact-1' };
const response = ( body: unknown, status = 200 ) => ({ ok: status === 200, status,
  text: async () => JSON.stringify( body ), json: async () => body });

it( 'exchanges refresh custody without persisting the refresh token in browser storage', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {
    AuthenticationResult: { AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600 },
  } ) ).mockResolvedValueOnce( response( profile ) ).mockResolvedValueOnce( response( hint ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );
  await auth.submitOtp( '+910000000000', '000000', 'qa-challenge' );
  expect( fetchMock.mock.calls[1][0] ).toBe( 'https://wecare.digital/api/customer/profile' );
  expect( fetchMock.mock.calls[1][1].headers.Authorization ).toBe( 'Bearer qa-access' );
  expect( fetchMock.mock.calls[1][1].body ).toBe( '{}' );
  expect( fetchMock.mock.calls[2][0] ).toBe( '/api/ecommerce/customer-session' );
  expect( fetchMock.mock.calls[2][1].credentials ).toBe( 'same-origin' );
  expect( JSON.stringify( { ...window.localStorage, ...window.sessionStorage } ) ).not.toContain( 'qa-refresh' );
} );

/**
 * THE REGRESSION TEST FOR THE 2026-10-02 CONFIRM OUTAGE.
 *
 * Only the 200 path above was ever covered, which is the gap that let this ship. When the
 * session exchange failed, `submitOtp` threw BEFORE storing the token - so a shopper who had
 * just answered a CORRECT code was signed out and shown "Try again shortly.", because the
 * thrown Error carries name 'Error' and falls through every branch of the sign-in page's
 * messageForAuthError to its catch-all.
 *
 * The Cognito challenge has already succeeded by that point. The exchange buys PERSISTENCE,
 * not authentication, so its failure must degrade remember-me and nothing more.
 */
it( 'keeps a successful sign-in when the session exchange is refused', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {
    AuthenticationResult: { AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600 },
  } ) ).mockResolvedValueOnce( response( profile ) )
    .mockResolvedValueOnce( response( { error: 'VERIFICATION_REQUIRED' }, 401 ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );

  // It RESOLVES rather than rejecting. Before the fix this rejected.
  const session = await auth.submitOtp( '+910000000000', '000000', 'qa-challenge' );

  expect( session?.accessToken ).toBe( 'qa-access' );
  // Degraded, and marked as such, rather than failed.
  expect( session?.remembered ).toBe( false );
  // The valid token survived instead of being discarded.
  expect( auth.getSession()?.accessToken ).toBe( 'qa-access' );
  // No device-level session was claimed, so restoreSession() will ask for a fresh sign-in.
  expect( window.localStorage.getItem( 'wecare.customer.sessionHint' ) ).toBeNull();
  // The refresh token never reaches browser storage, failure path included.
  expect( JSON.stringify( { ...window.localStorage, ...window.sessionStorage } ) )
    .not.toContain( 'qa-refresh' );
} );

it( 'marks a successful exchange as remembered and writes the hint', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {
    AuthenticationResult: { AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600 },
  } ) ).mockResolvedValueOnce( response( profile ) ).mockResolvedValueOnce( response( hint ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );

  const session = await auth.submitOtp( '+910000000000', '000000', 'qa-challenge' );
  expect( session?.remembered ).toBe( true );
  expect( JSON.parse( window.localStorage.getItem( 'wecare.customer.sessionHint' ) || 'null' ).csrfToken )
    .toBe( 'qa-csrf' );
} );

it( 'treats a 200 with an unreadable body as a degraded session, not a failure', async () => {
  // Same class of bug as the 401: anything that throws after the challenge succeeded destroys
  // a valid sign-in, so an unparseable success body must degrade rather than reject.
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {
    AuthenticationResult: { AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600 },
  } ) ).mockResolvedValueOnce( response( profile ) ).mockResolvedValueOnce( {
    ok: true, status: 200,
    text: async () => 'not json',
    json: async () => { throw new SyntaxError( 'Unexpected token' ); },
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );

  const session = await auth.submitOtp( '+910000000000', '000000', 'qa-challenge' );
  expect( session?.accessToken ).toBe( 'qa-access' );
  expect( session?.remembered ).toBe( false );
  expect( window.localStorage.getItem( 'wecare.customer.sessionHint' ) ).toBeNull();
} );


it( 'does not turn a temporary profile-claim failure into a failed OTP sign-in', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {
    AuthenticationResult: { AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600 },
  } ) ).mockRejectedValueOnce( new TypeError( 'profile offline' ) )
    .mockResolvedValueOnce( response( hint ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );

  const session = await auth.submitOtp( '+910000000000', '000000', 'qa-challenge' );

  expect( session?.accessToken ).toBe( 'qa-access' );
  expect( session?.remembered ).toBe( true );
  expect( auth.getSession()?.accessToken ).toBe( 'qa-access' );
  expect( fetchMock.mock.calls[1][0] ).toBe( 'https://wecare.digital/api/customer/profile' );
  expect( fetchMock.mock.calls[2][0] ).toBe( '/api/ecommerce/customer-session' );
} );

it( 'restores a new tab silently and shares one refresh between simultaneous requests', async () => {
  window.localStorage.setItem( 'wecare.customer.sessionHint', JSON.stringify( hint ) );
  const fetchMock = vi.fn().mockResolvedValue( response( { accessToken: 'qa-renewed', expiresAt: Date.now() + 3_600_000 } ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );
  const sessions = await Promise.all( [ auth.restoreSession(), auth.restoreSession() ] );
  expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  expect( sessions.every( session => session?.accessToken === 'qa-renewed' ) ).toBe( true );
  expect( fetchMock.mock.calls[0][1].headers['X-Customer-CSRF'] ).toBe( 'qa-csrf' );
} );

it( 'keeps remembered login during a provider outage and removes it on definite expiry', async () => {
  window.localStorage.setItem( 'wecare.customer.sessionHint', JSON.stringify( hint ) );
  const fetchMock = vi.fn().mockResolvedValueOnce( response( {}, 503 ) ).mockResolvedValueOnce( response( {}, 401 ) );
  vi.stubGlobal( 'fetch', fetchMock );
  const auth = await import( '../lib/customerAuth' );
  await expect( auth.restoreSession() ).rejects.toThrow( /temporarily/ );
  expect( window.localStorage.getItem( 'wecare.customer.sessionHint' ) ).not.toBeNull();
  expect( await auth.restoreSession() ).toBeNull();
  expect( window.localStorage.getItem( 'wecare.customer.sessionHint' ) ).toBeNull();
} );

it( 'does not revoke remembered login merely because the access token expired', async () => {
  window.localStorage.setItem( 'wecare.customer.sessionHint', JSON.stringify( hint ) );
  const auth = await import( '../lib/customerAuth' );
  auth.storeSession( 'qa-expired', Date.now() - 1000 );
  expect( auth.getSession() ).toBeNull();
  expect( window.localStorage.getItem( 'wecare.customer.sessionHint' ) ).not.toBeNull();
} );

it( 'drops a cached token after logout in another tab', async () => {
  const auth = await import( '../lib/customerAuth' );
  auth.storeSession( 'qa-access', Date.now() + 3_600_000 );
  window.dispatchEvent( new StorageEvent( 'storage', {
    key: 'wecare.customer.sessionHint', oldValue: JSON.stringify( hint ), newValue: null,
  } ) );
  expect( auth.getSession() ).toBeNull();
} );

it( 'preserves an explicit country prefix rather than treating it as an Indian local number', async () => {
  const auth = await import( '../lib/customerAuth' );
  expect( auth.normaliseMobile( '+61 1234 5678' ) ).toBe( '+6112345678' );
  expect( auth.normaliseMobile( '9876543210' ) ).toBe( '+919876543210' );
} );
