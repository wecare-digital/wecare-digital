/**
 * STAFF-POOL AMPLIFY CONFIGURATION, applied once, by whichever module needs Amplify Auth first.
 *
 * WHY THIS IS ITS OWN MODULE (2026-10-27). `Amplify.configure` and the I18n vocabulary used to run
 * at module scope in pages/_app.tsx, so `aws-amplify` was in the bundle every page shares. So was
 * the 285 KB API client: _app statically imported lib/pushRegistration, which imports
 * api/client.ts, for a push-token callback that only ever fires inside the native app shell. A
 * visitor reading a blog post downloaded and parsed the staff dashboard's whole API layer.
 *
 * Every consumer of Amplify Auth now imports this module for its side effect instead:
 *   - components/AuthShell.tsx, before the Authenticator renders;
 *   - api/client.ts, before any authFetch reaches fetchAuthSession;
 *   - each component or hook that calls `aws-amplify/auth` directly.
 * ES modules evaluate once per page, so the configuration still happens exactly once and always
 * before first use; it simply no longer happens on routes that never use it. Customer sign-in
 * does not depend on it at all: lib/customerAuth.ts talks to the customer pool's REST API.
 *
 * Do not import aws-amplify from pages/_app.tsx again; that puts it back on every public page.
 */
import { Amplify } from 'aws-amplify';
// I18n lives in aws-amplify/utils in v6, not on the root export.
import { I18n } from 'aws-amplify/utils';

/**
 * Plain-English labels for the MFA chooser.
 *
 * The user's preferred MFA factor is deliberately UNSET in Cognito, because the
 * API reference says: "If multiple options are activated and no preference is
 * set, a challenge to choose an MFA option will be returned during sign-in."
 * That challenge is what gives a choice of destination at sign-in instead of one
 * hardcoded channel - which matters here because the registered mobile is a
 * WhatsApp Business API number and SMS to it is the least dependable of the
 * three.
 *
 * Amplify renders it as a radio group (SelectMfaType), and its stock labels are
 * "Email Message", "Text Message" and "Authenticator App" - nouns that name a
 * technology rather than saying what is about to happen. These say what happens.
 *
 * They deliberately do NOT include the destination address or number. At this
 * point in the flow the password has been accepted, so it is not a secret from
 * the person typing - but it is rendered pre-authentication, and a masked hint
 * adds nothing a person choosing their own factor does not already know.
 *
 * Overridden through I18n rather than by replacing the component, because
 * getMfaTypeLabelByValue passes every label through translate(); swapping the
 * component would mean owning its form wiring and losing the state machine's
 * submit handling.
 */
I18n.putVocabularies( {
  en: {
    'Select MFA Type': 'How should we send your code?',
    'Email Message': 'Email me a code',
    'Text Message': 'Text me a code (SMS)',
    'Authenticator App': 'Use my authenticator app',
  },
} );

// Configure Amplify — all secrets from env vars
Amplify.configure( {
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID || '',
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID || '',
      identityPoolId: process.env.NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID || '',
      loginWith: {
        oauth: {
          domain: process.env.NEXT_PUBLIC_COGNITO_OAUTH_DOMAIN || '',
          scopes: [ 'openid', 'email', 'profile' ],
          // The apex. This is an OAuth redirect URI, which Cognito validates against a
          // registered allowlist - an unregistered host fails with redirect_mismatch and
          // sign-in stops working - so this fallback must name a REGISTERED URI.
          // https://wecare.digital/ is registered on the stack-wecare-digital-web client
          // as both a callback and a logout URL, verified against the live pool.
          //
          // This used to say retired legacy frontend host, on the reasoning that the apex was
          // only the public marketing host while the app was served from the subdomain.
          // That distinction no longer exists: Amplify maps the apex to this same branch
          // and 301s retired legacy frontend host to it, so the subdomain served nothing of its
          // own and has been retired. A redirecting host is a bad OAuth redirect URI in
          // any case - it works only as long as the 301 preserves the ?code=.
          redirectSignIn: [
            process.env.NEXT_PUBLIC_APP_URL || 'https://wecare.digital/',
          ],
          redirectSignOut: [
            process.env.NEXT_PUBLIC_APP_URL || 'https://wecare.digital/',
          ],
          responseType: 'code' as const
        },
        username: true,
        email: true
      }
    }
  }
} );

/** Importing this module is what configures Amplify; the flag is for tests and diagnostics. */
export const AMPLIFY_CONFIGURED = true;
