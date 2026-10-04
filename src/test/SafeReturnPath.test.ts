/**
 * `safeLocalReturnPath` decides where a customer lands after signing in.
 *
 * WHY THESE CASES AND NOT A HAPPY PATH. The regex this module replaces
 * (`src/pages/account/sign-in.tsx`, measured 2026-10-01) passed review while accepting two
 * values that matter, and both are asserted below as named cases rather than folded into a
 * list, so a future loosening names its own victim in the failure output:
 *
 *   - `'//evil'`           protocol-relative; the browser reads `evil` as a HOST, so a
 *                          "local path" check hands the visitor to another origin. Note
 *                          that `'//evil.example'` was rejected by the old regex ONLY
 *                          because `.` was missing from its character class — a
 *                          single-label host needs no dot, so the protection was an
 *                          accident of punctuation.
 *   - `'/workspace/access'` a well-formed local path, and the STAFF Cognito login. No
 *                          character class can express "not that destination"; only an
 *                          allowlist can.
 *
 * Every rejected case asserts the RETURNED STRING is `'/cart/'`, not merely that the input
 * was refused. The function returns the value to navigate to precisely so a caller cannot
 * check one string and use another, so the tests have to assert the value.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { safeLocalReturnPath } from '../lib/safeReturnPath';

const DEFAULT = '/cart/';

describe( 'safeLocalReturnPath — off-site destinations', () => {
  it( 'rejects an absolute URL', () => {
    expect( safeLocalReturnPath( 'https://evil.example/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( 'http://evil.example/cart/' ) ).toBe( DEFAULT );
  } );

  it( 'rejects a protocol-relative path WITH a dot', () => {
    expect( safeLocalReturnPath( '//evil.example' ) ).toBe( DEFAULT );
  } );

  it( 'rejects a protocol-relative path WITHOUT a dot — the gap in the old regex', () => {
    // A host label does not need a dot. `//evil` is `https://evil/` to a browser, and the
    // character-class check it replaced accepted every character in it.
    expect( safeLocalReturnPath( '//evil' ) ).toBe( DEFAULT );
  } );

  it( 'rejects extra leading slashes', () => {
    expect( safeLocalReturnPath( '///evil' ) ).toBe( DEFAULT );
  } );

  it( 'rejects backslash separators a browser normalises to /', () => {
    expect( safeLocalReturnPath( '/\\evil.example' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '\\\\evil.example' ) ).toBe( DEFAULT );
  } );

  it( 'rejects a non-navigational scheme', () => {
    expect( safeLocalReturnPath( 'javascript:alert(1)' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( 'data:text/html,x' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( 'mailto:a@b' ) ).toBe( DEFAULT );
  } );
} );

describe( 'safeLocalReturnPath — encoding, injection and traversal', () => {
  it( 'rejects percent-encoding instead of decoding it', () => {
    // The module never decodes, at any depth. `%2f%2f` decodes once to `//`, and
    // `%252f%252f` decodes to `%2f%2f` which decodes again — a decoding validator has to
    // pick a number of rounds and the attacker picks a different one.
    expect( safeLocalReturnPath( '%2f%2fevil.example' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '%252f%252fevil' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/%2f%2fevil.example' ) ).toBe( DEFAULT );
  } );

  it( 'rejects CRLF and other control characters', () => {
    expect( safeLocalReturnPath( '/cart/%0d%0aSet-Cookie:x' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/cart/\r\nSet-Cookie:x' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/cart/\u0000' ) ).toBe( DEFAULT );
  } );

  it( 'rejects whitespace anywhere in the value', () => {
    expect( safeLocalReturnPath( '/cart/\t' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/ cart/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( ' /cart/' ) ).toBe( DEFAULT );
  } );

  it( 'rejects a traversal segment', () => {
    expect( safeLocalReturnPath( '/../etc/passwd' ) ).toBe( DEFAULT );
    // First segment reads as `cart`, so the staff-segment check alone would miss it.
    expect( safeLocalReturnPath( '/cart/../workspace/access' ) ).toBe( DEFAULT );
  } );
} );

describe( 'safeLocalReturnPath — staff destinations', () => {
  it( 'rejects the staff workspace login', () => {
    expect( safeLocalReturnPath( '/workspace/access' ) ).toBe( DEFAULT );
  } );

  it( 'rejects the rest of the staff tree and its redirect shims', () => {
    for ( const staff of [
      '/workspace/dashboard/',
      '/workspace/',
      '/admin/',
      '/access/',
      '/dashboard/',
      '/settings/',
      '/engage/inbox/',
      '/contacts/',
      '/commerce/',
      '/pay/',
    ] ) {
      expect( safeLocalReturnPath( staff ), `${staff} must not be a customer return path` )
        .toBe( DEFAULT );
    }
  } );

  it( 'rejects a staff segment whatever its casing', () => {
    expect( safeLocalReturnPath( '/WorkSpace/access' ) ).toBe( DEFAULT );
  } );
} );

describe( 'safeLocalReturnPath — absent and malformed input', () => {
  it( 'falls back for an empty, null or undefined value', () => {
    expect( safeLocalReturnPath( '' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( null ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( undefined ) ).toBe( DEFAULT );
  } );

  it( 'falls back for a local path that is simply not an allowed destination', () => {
    // Reject by default is the whole design: a well-formed, harmless, local path that
    // nobody listed still does not pass.
    //
    // `/blog/` used to be this test's first example and MOVED to the accepted set on
    // 2026-10-01 when the owner narrowed `ALLOWED` — it resolves, and a plausible return
    // destination that falls back to `/cart/` is a silent wrong answer rather than a safe
    // one. `/vault/` carries the case instead: local, well-formed, resolves to nothing,
    // listed nowhere. `/terms/` is the sharper example — it is a real exported page and is
    // STILL rejected, which is the point: membership is a decision, not a consequence of
    // existing.
    expect( safeLocalReturnPath( '/vault/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/terms/' ) ).toBe( DEFAULT );
  } );
} );

describe( 'safeLocalReturnPath — the accepted set', () => {
  // '/shop/' left this set on 2026-10-04 when the owner withdrew the catalogue index. Its
  // rejection is asserted positively in the inversion block further down, rather than only by
  // absence here.
  it( 'accepts each customer destination in its slashed form', () => {
    for ( const ok of [ '/cart/', '/orders/', '/blog/', '/' ] ) {
      expect( safeLocalReturnPath( ok ) ).toBe( ok );
    }
  } );

  it( 'normalises the unslashed form rather than rejecting it', () => {
    // `trailingSlash: true`, so the unslashed form would 301 to the slashed one anyway.
    expect( safeLocalReturnPath( '/cart' ) ).toBe( '/cart/' );
    expect( safeLocalReturnPath( '/orders' ) ).toBe( '/orders/' );
    expect( safeLocalReturnPath( '/blog' ) ).toBe( '/blog/' );
  } );

  it( 'never returns a value carrying a query string or fragment', () => {
    // The returned value is re-emitted from the normalised allowlist member, so state
    // attached to the input cannot ride along into the navigation.
    for ( const smuggled of [ '/cart/?next=//evil', '/cart/#f', '/cart?x=1', '/shop/#a' ] ) {
      const out = safeLocalReturnPath( smuggled );
      expect( out ).toBe( DEFAULT );
      expect( out ).not.toContain( '?' );
      expect( out ).not.toContain( '#' );
    }
  } );

  it( 'only ever returns a member of the allowed set', () => {
    const allowed = new Set( [ '/cart/', '/orders/', '/blog/', '/' ] );
    const inputs = [
      '/cart', '/cart/', '/', '//evil', '/workspace/access', 'https://evil.example/',
      '%2f%2fevil', '/../x', '', null, undefined, '/terms/', '/cart/#f',
      '/checkout/', '/account/', '\\\\evil.example',
      // Withdrawn 2026-10-04. Both spellings, plus a product page, must come back as the
      // fallback rather than as themselves.
      '/shop/', '/shop', '/shop/file-assist/',
    ];
    for ( const input of inputs ) {
      expect( allowed.has( safeLocalReturnPath( input ) ), `${String( input )} escaped the allowlist` )
        .toBe( true );
    }
  } );
} );

/**
 * KNOWN GAP, measured 2026-10-01 by the convergence step — two of the six values this
 * function can return have NO exported page, so they answer 404 live:
 *
 *     GET https://wecare.digital/checkout/  -> 404      GET https://wecare.digital/account/  -> 404
 *
 * `src/pages/checkout/` holds only `status.tsx` and `success.tsx`; `src/pages/account/` holds
 * only `sign-in.tsx`. Neither directory has an `index`, and `output: 'export'` emits a page
 * only where a source file exists, so there is nothing for `/checkout/` or `/account/` to hit
 * but the `/<*>` -> `/404.html` catch-all.
 *
 * WHY THIS IS PINNED RATHER THAN FIXED. The allowlist was specified verbatim by the task plan
 * (section 2 step 1) and FEAT-001 implemented it faithfully; the mismatch is between that list
 * and the live page inventory, which only became visible once both halves of the task were
 * measured together. Narrowing the list and building the two pages are BOTH product decisions,
 * and `src/pages/account/**` belongs to another workstream that this change may not edit. The
 * function is also still dormant — nothing outside this test imports it — so the gap cannot
 * reach a customer today. It would reach one the moment the one-line wiring in section 7 of
 * `docs/execution/url-host-matrix-20261001.md` is applied, which is exactly why it is recorded
 * there as a precondition rather than left for that owner to discover.
 *
 * This asserts the CURRENT measured truth so the discrepancy cannot ship silently. When it is
 * resolved, INVERT this test — do not delete it: either the two entries leave `ALLOWED` (then
 * assert they fall back to `/cart/`), or the two pages land (then assert the directory has an
 * index). The same convention as
 * `tests/test_url_host_routing_rules.py::test_the_provisioner_would_strip_the_host_rule_KNOWN_HAZARD`.
 *
 * ── GAP CLOSED 2026-10-01, AND THIS BLOCK IS NOW ITS INVERSION ───────────────────────────
 *
 * The owner took the first of the two documented resolutions: `/checkout/` and `/account/`
 * LEFT `ALLOWED`, and `/blog/` joined it. Building the two pages was rejected for now, on the
 * grounds that `/checkout/` overlaps checkout work in flight and that shipping a page to
 * satisfy a validator is the tail wagging the dog. Everything above is the state that
 * prompted the decision and is kept as written; the assertions below are the inversion the
 * last paragraph prescribed, in the order it prescribed them:
 *
 *   - the two entries fall back to `/cart/` rather than being vouched for;
 *   - all FIVE remaining members are checked against the filesystem, not four;
 *   - `has no production caller` became `HAS a production caller and routes through here`.
 *
 * The caller test is the one worth reading twice. Its old job was to fail the moment the
 * wiring landed, so that this decision could not be skipped by accident — it did that job, and
 * a test that simply starts passing once wired would teach nothing and would not notice the
 * wiring being removed again. Inverted, it now pins the thing that actually matters: that the
 * permissive regex has not come back.
 */
describe( 'safeLocalReturnPath — the gap is closed and the validator is wired (INVERTED)', () => {
  const PAGES_DIR = path.join( process.cwd(), 'src', 'pages' );

  /** A destination resolves only if `output: 'export'` has a source file to emit for it. */
  const pageExists = ( segment: string ): boolean =>
    fs.existsSync( path.join( PAGES_DIR, segment, 'index.tsx' ) )
    || fs.existsSync( path.join( PAGES_DIR, `${segment}.tsx` ) );

  it( 'confirms every one of the four allowed destinations really does have a page', () => {
    // `/` is `src/pages/index.tsx`. If one of these ever stops existing, the validator would
    // start handing out a 404 for a destination this test vouches for — which is exactly the
    // gap this block used to record, so the check is now total rather than partial.
    //
    // FIVE BECAME FOUR ON 2026-10-04, and this is the second use of the inversion convention the
    // header prescribes. `shop` was in this loop and the loop CAUGHT the withdrawal: the owner
    // deleted `src/pages/shop/index.tsx` that day, so `/shop/` stopped having an exported page
    // and this assertion went red - working exactly as designed, rather than letting the
    // validator keep vouching for a URL that now 301s to the home page. The prescribed
    // resolutions were "the entry leaves ALLOWED" or "the page lands"; the page is not landing,
    // because the withdrawal is the owner's instruction, so the entry left and the fallback is
    // asserted below.
    expect( fs.existsSync( path.join( PAGES_DIR, 'index.tsx' ) ), '/ must have an exported page' ).toBe( true );
    for ( const segment of [ 'cart', 'orders', 'blog' ] ) {
      expect( pageExists( segment ), `/${segment}/ must have an exported page` ).toBe( true );
    }
  } );

  it( 'no longer accepts /shop/, because the owner withdrew the catalogue index', () => {
    /*
     * THE INVERSION, in the same shape as the /checkout/ and /account/ block below it.
     *
     * Measured from the filesystem rather than trusted: src/pages/shop/ holds only [slug].tsx
     * after the withdrawal, so `output: 'export'` emits the seven PRODUCT pages and no index.
     * A `?return=/shop/` would otherwise be handed back verbatim and spend a redirect landing on
     * the home page.
     *
     * No in-app flow is affected: src/pages/cart.tsx is the only producer of a `return` value and
     * it produces /cart/. The seven product pages are unaffected by this and were never allowlist
     * members - a return path is one of a few fixed destinations, not an arbitrary product URL.
     */
    expect( pageExists( 'shop' ) ).toBe( false );
    expect( safeLocalReturnPath( '/shop/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/shop' ) ).toBe( DEFAULT );
    // And a product page is not smuggled in either, for the same reason: it is not on the list.
    expect( safeLocalReturnPath( '/shop/file-assist/' ) ).toBe( DEFAULT );
  } );

  it( 'no longer accepts /checkout/ or /account/, because neither has a page', () => {
    // The measurement that drove the narrowing, re-asserted from the filesystem rather than
    // trusted: `src/pages/checkout/` holds only status.tsx and success.tsx, `src/pages/account/`
    // only sign-in.tsx. `output: 'export'` emits a page only where a source file exists, so
    // both answered 404 live.
    expect( pageExists( 'checkout' ) ).toBe( false );
    expect( pageExists( 'account' ) ).toBe( false );

    // INVERTED: they now fall back instead of being vouched for.
    expect( safeLocalReturnPath( '/checkout/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/account/' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/checkout' ) ).toBe( DEFAULT );
    expect( safeLocalReturnPath( '/account' ) ).toBe( DEFAULT );
  } );

  it( 'HAS a production caller, and that caller routes through this validator', () => {
    // Read as text rather than imported: importing a page module executes Amplify.configure.
    //
    // INVERTED 2026-10-01. This asserted `callers` was EMPTY, so that it would fail the moment
    // the wiring landed and the decision could not be skipped by accident. The wiring has
    // landed, so the assertion flips to the property that matters from here on: the sign-in
    // page must import this function AND must not have kept the permissive regex beside it.
    const SELF = [ path.join( 'src', 'lib', 'safeReturnPath.ts' ), path.join( 'src', 'test', 'SafeReturnPath.test.ts' ) ];
    const walk = ( dir: string ): string[] => fs.readdirSync( dir, { withFileTypes: true } ).flatMap( ( entry ) => {
      const full = path.join( dir, entry.name );
      if ( entry.isDirectory() ) return walk( full );
      return /\.tsx?$/.test( entry.name ) ? [ full ] : [];
    } );
    const callers = walk( path.join( process.cwd(), 'src' ) )
      .map( ( full ) => path.relative( process.cwd(), full ) )
      .filter( ( rel ) => !SELF.includes( rel ) )
      .filter( ( rel ) => fs.readFileSync( path.join( process.cwd(), rel ), 'utf8' ).includes( 'safeLocalReturnPath' ) );

    const signIn = path.join( 'src', 'pages', 'account', 'sign-in.tsx' );
    expect( callers, 'the customer sign-in page must validate its return path through this module' )
      .toContain( signIn );

    // The regex is the defect, not merely the old implementation: it accepted `//evil` and
    // `/workspace/access`. Importing the validator while leaving the regex in place would pass
    // the check above and change nothing, so the literal is forbidden outright.
    const source = fs.readFileSync( path.join( process.cwd(), signIn ), 'utf8' );
    expect( source, 'the permissive return-path regex must not come back' )
      .not.toContain( 'a-zA-Z0-9/_-' );
    expect( source ).toContain( 'safeLocalReturnPath( raw )' );
  } );
} );
