/**
 * `safeLocalReturnPath` — the value a post-sign-in redirect may actually navigate to.
 *
 * WHY THIS EXISTS, 2026-10-01. `src/pages/account/sign-in.tsx` reads a `return` query
 * parameter and currently validates it with
 *
 *     /^\/[a-zA-Z0-9/_-]*\/?$/.test( raw ) ? raw : '/cart/'
 *
 * which is a denylist expressed as a character class, and it leaks in two measured ways:
 *
 *   1. `//evil` passes. Every character is in the class, but a browser reads a leading
 *      `//` as protocol-relative and resolves the next segment as a HOST — so the
 *      "local path" is an off-site navigation. `//evil.example` happens to be rejected
 *      only because `.` is absent from the class, which means the protection is an
 *      accident of punctuation rather than a rule. A single-label host needs no dot.
 *   2. `/workspace/access` passes. It is a perfectly well-formed local path, and it is
 *      the STAFF Cognito login. A customer completing a consumer sign-in should never be
 *      forwarded into the internal workspace tree, and nothing in a character class can
 *      express that — it is a question about which destinations are intended, not about
 *      which characters are legal.
 *
 * So this is an ALLOWLIST: reject by default, and accept only a recognised customer
 * destination. A denylist has to enumerate every attack; an allowlist has to enumerate
 * five paths, and a new one is a deliberate edit here.
 *
 * IT RETURNS THE PATH TO USE, NEVER A BOOLEAN — the same shape as `safeHttpHref` in
 * `src/lib/randomToken.ts`, and for the same reason recorded there: a boolean lets a
 * caller validate one string and navigate to a different one, which is exactly the defect
 * that predicate was replacing. The caller writes what this returns, so what was checked
 * is what ships. The returned value is also re-emitted from the normalised allowlist
 * member rather than sliced out of the input, so an accepted value can never carry a
 * query string or fragment it smuggled in.
 *
 * THE INPUT IS NEVER URL-DECODED. Decoding is the bypass: `%2f%2fevil.example` decodes to
 * `//evil.example`, and `%252f%252f` decodes to `%2f%2f` which decodes again. Any
 * validator that decodes has to decide how many times, and the attacker picks the number.
 * `%` is therefore rejected outright and every comparison is against the raw string. A
 * legitimate customer return path in this application contains no percent sign.
 *
 * NO PRODUCTION CALLER YET, deliberately. `src/pages/account/**` belongs to the customer
 * authentication workstream and is outside this change's owned paths, so the module and
 * its tests land first and the one-line wiring is handed to that owner. An unused export
 * with tests is cheap; editing another session's file is not.
 *
 * WIRED 2026-10-01, by owner decision, and the paragraph above is now history. The
 * customer-authentication workstream that owned `src/pages/account/**` aborted before
 * reaching implementation, so there was no live owner to collide with, and the owner
 * cleared the boundary explicitly rather than leaving a live open redirect documented as a
 * handoff. `src/pages/account/sign-in.tsx` now calls this function in
 * `returnPathFromUrl()`, and `src/test/SafeReturnPath.test.ts` asserts that the caller
 * EXISTS and routes through here — the inversion of the test that used to fail the moment a
 * caller appeared. The rationale above is kept rather than deleted because it explains why
 * the module shipped dormant, which is otherwise a strange shape to find in a diff.
 */

/**
 * The only destinations a customer sign-in may return to. Stored in the slashed form
 * because `trailingSlash: true` in `next.config.js` means every extensionless path 301s
 * to add the slash anyway — returning the unslashed form would spend a redirect to arrive
 * at the same place.
 *
 * EVERY MEMBER MUST HAVE AN EXPORTED PAGE. This is not a style rule, it is the contract:
 * the function "returns the value to use", so a member with no page makes it vouch for a
 * destination that answers 404. `output: 'export'` emits a page only where a source file
 * exists, so membership here is a claim about `src/pages/**`, and
 * `src/test/SafeReturnPath.test.ts` checks that claim against the filesystem for all five.
 *
 * NARROWED 2026-10-01 from six entries to five, by owner decision, as the precondition on
 * wiring this into `sign-in.tsx`. `/checkout/` and `/account/` were REMOVED because both
 * measured **404** live: `src/pages/checkout/` holds only `status.tsx` and `success.tsx`,
 * and `src/pages/account/` holds only `sign-in.tsx` — neither directory has an `index`. The
 * original six came verbatim from the task plan, which listed intended destinations rather
 * than existing pages, and the mismatch was only visible once the list and the page
 * inventory were measured together. `/blog/` was ADDED in the same decision: it is a
 * plausible place to send a customer back to and it resolves, so excluding it would have
 * manufactured a silent redirect to `/cart/` rather than avoided one.
 *
 * Re-adding `/checkout/` or `/account/` is therefore conditional on those pages existing,
 * not a free edit — the test above will fail first, which is the intended order.
 *
 * NARROWED AGAIN 2026-10-04, from five entries to four, for exactly the reason stated above.
 * `/shop/` LEFT the set because the owner withdrew the catalogue index that day: the page file is
 * deleted, so `output: 'export'` emits nothing for it and the edge 301s the URL to the home page.
 * Keeping it would make this function vouch for a destination that no longer resolves, which is
 * the one thing the contract above forbids — and the test took the prescribed route of INVERTING
 * rather than being deleted, so `/shop/` is now asserted to fall back to `/cart/`.
 *
 * WHAT THIS CHANGES FOR A VISITOR, stated rather than left to be discovered. No in-app flow is
 * affected: `src/pages/cart.tsx:117` is the ONLY producer of a `return` value in this codebase and
 * it produces `/cart/`, so nothing here ever asked to come back to `/shop/`. The difference is
 * confined to a hand-written or externally-supplied `?return=/shop/`, which now lands on `/cart/`
 * instead of being forwarded to `/shop/` and bounced to the home page by the 301. Neither is the
 * catalogue listing, because the listing is gone; this is the one that does not spend a redirect
 * on a dead URL.
 */
const ALLOWED: ReadonlySet<string> = new Set( [
  '/cart/',
  '/orders/',
  '/blog/',
  // Phase O-1: the two service pages send a signed-out customer to sign in and back.
  '/submit-request/',
  '/request-amendment/',
  '/',
] );

/**
 * First path segments that are staff surfaces or redirect shims into them. Belt and
 * braces: none of these is in `ALLOWED`, so the allowlist alone already rejects them.
 * They are named explicitly so that adding a customer destination to `ALLOWED` in future
 * cannot accidentally open a staff tree sharing its prefix, and so the rejection reason
 * in a test failure says "staff surface" rather than "not on the list".
 */
const BLOCKED_FIRST_SEGMENTS: ReadonlySet<string> = new Set( [
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

/** Where a rejected or absent value goes. The cart is the only producer of `return`. */
const DEFAULT_RETURN = '/cart/';

/**
 * Characters that must not appear anywhere in the raw value.
 *
 *   `\`            Windows-style separator; browsers and some servers treat it as `/`,
 *                  so `/\evil.example` is protocol-relative to a browser.
 *   whitespace     a tab or newline is stripped by the browser before resolution, so it
 *                  can hide a scheme or a separator from a naive check; `\r\n` in a value
 *                  that reaches a header is response splitting.
 *   control chars  same reasoning, including NUL used to truncate a comparison.
 *   `%`            see the header: no decoding, so no encoded bypass.
 *   `?` `#`        a query or fragment is not part of the destination this decides, and
 *                  allowing one would let an accepted path carry attacker-chosen state.
 *   `:`            a scheme separator; `javascript:` and `data:` must never get this far.
 */
const FORBIDDEN_CHARS = /[\\\s\u0000-\u001f\u007f%?#:]/;

export function safeLocalReturnPath ( raw: string | null | undefined ): string {
  if ( typeof raw !== 'string' || raw.length === 0 ) return DEFAULT_RETURN;

  // Order matters, and these run BEFORE any allowlist comparison so that a hostile value
  // is never normalised into something that looks acceptable.

  // Exactly one leading slash. Anything else is absolute (`https://...`), scheme-relative
  // (`//host`, `///host`), backslash-relative (`/\host`, `\\host`) or schemeless
  // (`javascript:`, `mailto:`), and all of those are off-site or non-navigational.
  if ( raw.charCodeAt( 0 ) !== 0x2f /* '/' */ ) return DEFAULT_RETURN;
  if ( raw.length > 1 && ( raw[ 1 ] === '/' || raw[ 1 ] === '\\' ) ) return DEFAULT_RETURN;

  if ( FORBIDDEN_CHARS.test( raw ) ) return DEFAULT_RETURN;

  // Traversal. `/cart/../workspace/access` is a staff path whose first segment reads as
  // `cart`, so the segment check below is not sufficient on its own.
  const segments = raw.split( '/' );
  if ( segments.includes( '..' ) ) return DEFAULT_RETURN;

  const first = segments[ 1 ] ?? '';
  if ( BLOCKED_FIRST_SEGMENTS.has( first.toLowerCase() ) ) return DEFAULT_RETURN;

  // Normalise to the slashed form and compare. `/cart` and `/cart/` are the same
  // destination; `/` is already its own slashed form.
  const normalised = raw.endsWith( '/' ) ? raw : `${raw}/`;
  return ALLOWED.has( normalised ) ? normalised : DEFAULT_RETURN;
}
