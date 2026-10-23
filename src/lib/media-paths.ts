/**
 * The S3 key contract for `wecare-digital-get`, browser side.
 *
 * This is the TypeScript counterpart of
 * `amplify/functions/shared/lambda_utils/media_paths.py`, which stays the canonical
 * definition. It exists because the frontend had no equivalent, so components
 * hand-built media URLs from a hostname — and when the `app.wecare.digital` bucket and
 * host were retired on 2026-09-28 every one of those hand-built URLs died silently. A
 * broken `<img>` renders as empty space, not as an error.
 *
 * Two rules carry all the weight, and both are easy to get backwards:
 *
 * 1. **The bucket name is not a hostname.** The old bucket was literally named
 *    `app.wecare.digital`, so its name doubled as a domain and interpolating it into a
 *    URL happened to work. `wecare-digital-get` is not a domain, so that same pattern
 *    now produces a URL that resolves to nothing. Keep the two apart: the bucket name
 *    is for S3 API calls, {@link CDN_DOMAIN} is for anything a browser will fetch.
 *
 * 2. **`o/` does not mean public, and `secure/` is the real boundary.** Everything
 *    outside `secure/` is public. `o/` is just the root that real objects live under.
 *    A `secure/` key is denied at the edge by the `wecare-get-miss-redirect`
 *    Lambda@Edge and only reachable through a presigned URL, so handing one to a
 *    public-URL builder is a caller mistake — {@link publicUrl} returns `''` rather
 *    than a link that will 302, which surfaces the mistake here instead of shipping a
 *    dead link to a recipient.
 *
 * Keys persisted in DynamoDB before the bucket merge lack the `o/` segment, so
 * {@link canonical} normalises on read. It is idempotent, and it never moves a key
 * between the two roots.
 */

/** Public root. Real objects live here; this is not an access-control prefix. */
export const PUBLIC_ROOT = 'o/';

/** Gated root. Denied at the edge; reachable only via a presigned URL. */
export const SECURE_ROOT = 'secure/';

/** Public-delivery subtree inside secure/d. */
export const PUBLIC_DELIVERABLE_ROOT = 'secure/d/public/';

/**
 * The media host including its path segment. Deliberately NOT the bucket name —
 * see rule 1 in the module docstring.
 */
export const CDN_DOMAIN = 'wecare.digital/get';

/**
 * Return `key` rooted in the tree it belongs to, without moving it between roots.
 *
 * A key already under `o/` or `secure/` comes back unchanged, so this is safe to apply
 * twice and safe to apply to a gated key without exposing it. An absolute URL is
 * returned untouched, because a stored value may be either a key or a full `fileUrl`
 * and prefixing the latter would corrupt it. Anything else is treated as a pre-merge
 * legacy key and rooted under `o/`.
 */
export function canonical ( key?: string | null ): string {
    if ( !key ) return '';
    const k = key.replace( /^\/+/, '' );
    if ( k.startsWith( 'http://' ) || k.startsWith( 'https://' ) ) return key;
    if ( k.startsWith( PUBLIC_ROOT ) || k.startsWith( SECURE_ROOT ) ) return k;
    return PUBLIC_ROOT + k;
}

/** True when the key lives under the gated root. */
export function isGated ( key?: string | null ): boolean {
    if ( !key ) return false;
    const k = canonical( key );
    return k.startsWith( SECURE_ROOT ) && !k.startsWith( PUBLIC_DELIVERABLE_ROOT );
}

/**
 * The public URL for a media key, or `''` when there is no usable one.
 *
 * Built from {@link canonical}, so a legacy un-prefixed key yields a URL that actually
 * resolves. Returns `''` for a gated key and for an empty key, so a caller can test
 * the result directly rather than rendering a link that redirects.
 */
export function publicUrl ( key?: string | null, cdnDomain: string = CDN_DOMAIN ): string {
    const k = canonical( key );
    if ( !k || ( k.startsWith( SECURE_ROOT ) && !k.startsWith( PUBLIC_DELIVERABLE_ROOT ) ) ) return '';
    if ( k.startsWith( 'http://' ) || k.startsWith( 'https://' ) ) return k;
    return `https://${ cdnDomain.replace( /^\/+|\/+$/g, '' ) }/${ k }`;
}
