/**
 * Customer destinations that the shared `/auth` flow may return to.
 *
 * Keep this list identical to `WEBSITE_RETURNS` in the customer-commerce auth
 * backend. `tools/customer-commerce/prepare_release.py` compares them and also
 * verifies that every configured service path is represented here.
 */
export const ALLOWED_CUSTOMER_RETURN_PATHS = [
  '/',
  '/checkout/',
  '/orders/',
  '/blog/',
  '/vault/',
] as const;

const ALLOWED = new Set<string>( ALLOWED_CUSTOMER_RETURN_PATHS );
const DEFAULT_RETURN = '/';

/** Staff-only or internal first path segments may never be customer returns. */
const BLOCKED_FIRST_SEGMENTS = new Set( [
  'workspace',
  'admin',
  'access',
  'dashboard',
  'dm',
  'engage',
  'settings',
  'task',
  'seo',
  'commerce',
  'pay',
  'forms',
  'service',
  'contacts',
  'docs',
] );

/**
 * Return a normalized, allowlisted same-site destination.
 *
 * The raw value is intentionally never URL-decoded. Percent escapes, query
 * strings, fragments, controls, whitespace, schemes, protocol-relative paths,
 * backslashes and traversal segments are rejected before normalization.
 */
export function safeLocalReturnPath ( raw: string | null | undefined ): string {
  if ( typeof raw !== 'string' || raw.length === 0 ) return DEFAULT_RETURN;

  // Retired service and bare /get page destinations are not valid auth returns.
  // Unknown returns lead Home; explicit /checkout/ and exact-file /vault/
  // remain supported without adding public landing pages.
  if ( raw[ 0 ] !== '/' || raw.startsWith( '//' ) || raw.startsWith( '/\\' ) ) {
    return DEFAULT_RETURN;
  }
  if ( /[\\\s\u0000-\u001f\u007f%?#:]/.test( raw ) ) return DEFAULT_RETURN;

  const segments = raw.split( '/' );
  if ( segments.includes( '..' ) ) return DEFAULT_RETURN;
  if ( BLOCKED_FIRST_SEGMENTS.has( ( segments[ 1 ] || '' ).toLowerCase() ) ) {
    return DEFAULT_RETURN;
  }

  const normalized = raw.endsWith( '/' ) ? raw : `${ raw }/`;
  return ALLOWED.has( normalized ) ? normalized : DEFAULT_RETURN;
}
