/**
 * Only authentication parameters belong in /auth/state. Share links and ad platforms
 * append utm_source, click IDs, etc.; forwarding them makes the strict auth API
 * reject an otherwise valid customer sign-in before a phone can be entered.
 *
 * Preserve duplicates for the backend's strict parser to reject, and preserve the
 * full PKCE/OAuth query rather than rewriting a host's signed-in flow.
 */
const OAUTH_QUERY_FIELDS = new Set( [
  'client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'resource',
  'code_challenge', 'code_challenge_method', 'ui_locales',
] );
const WEBSITE_QUERY_FIELDS = new Set( [ 'return' ] );

export function authStateQuery ( incoming: URLSearchParams ): URLSearchParams {
  const isOAuth = [ ...OAUTH_QUERY_FIELDS ].some( key => incoming.has( key ) );
  const allowed = isOAuth ? OAUTH_QUERY_FIELDS : WEBSITE_QUERY_FIELDS;
  const safe = new URLSearchParams();
  for ( const [ key, value ] of incoming ) {
    if ( allowed.has( key ) ) safe.append( key, value );
  }
  return safe;
}
