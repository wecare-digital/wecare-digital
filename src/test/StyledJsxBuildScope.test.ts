import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * EVERY styled-jsx-SCOPED CLASS ON A PUBLIC PAGE MUST REACH ITS ELEMENT.
 *
 * THIS GENERALISES PillButtonBuildScope.test.ts, AND IT EXISTS BECAUSE THE NARROW VERSION
 * COULD NOT SEE THE SAME DEFECT ONE COMPONENT OVER.
 *
 * That file asserts the property for `pill*` classes on `/account/sign-in/`, after the two pill
 * segments shipped unstyled and rendered as the run-together "Sign inConfirm code" the owner
 * reported. Its own docblock names the general rule: styled-jsx only stamps its scope hash onto
 * JSX in the tree it transforms, so anything lifted out of the return tree ships with a bare
 * class name against a selector that requires a hash.
 *
 * The Phase 4 audit then found the SAME defect, live, on the SAME page - on the phone field.
 * `PhoneField.tsx` declared a `DialCodeSearch` child component holding the dial-code segment, so
 * the built markup was:
 *
 *   CSS shipped     .pf-code.jsx-972b1368ee20e676{...}
 *   markup shipped  <input class="pf-code" ...>                    <- no hash
 *   the sibling     <input class="jsx-972b1368ee20e676 pf-num">    <- correctly stamped
 *
 * Measured in out/account/sign-in/index.html. Every rule for that segment was dead, so it fell
 * through to the global `input` skin: 13px radius instead of the 999px leading pill, a 2px box on
 * all four sides instead of `border:0` plus one inline-end hairline, 50px instead of 52px, 16px
 * type instead of 17px, and no `::-webkit-search-cancel-button{display:none}` so the native clear
 * glyph showed inside the field. The "one field, divided" control rendered as TWO BOXES of
 * different heights and different corner radii, on /account/sign-in/, /get/, /cart/ and the blog
 * subscribe block. That is the owner's "phone field does not match home design".
 *
 * So the lesson had been written down, pinned by a test, and the test was scoped to the one
 * component that had already failed. A guard that names the component cannot catch the next
 * component. THIS FILE NAMES NOTHING: it reads every `.<class>.jsx-<hash>` selector the page
 * inlined, and for every element carrying one of those class names, requires a matching hash.
 * A new component is covered the day it ships, with no list to update.
 *
 * THE NARROW FILE STAYS. It carries the history of the original defect and it asserts two things
 * this one deliberately does not: that the page contains the expected button text, and that the
 * label's own class is stamped rather than only the outer control. Those are claims about that
 * control, not about scoping in general.
 *
 * WHY THIS CANNOT BE A UNIT TEST. vitest does not run the styled-jsx transform, so `<style jsx>`
 * renders as a plain `<style>` with UNSCOPED selectors and jsdom sees selectors that would match.
 * The failure is unobservable in a unit test even in principle. It has to be read off the
 * artifact the browser loads.
 *
 * SKIP / FAIL BEHAVIOUR is copied from PillButtonBuildScope.test.ts verbatim in intent, because
 * the reasoning there is right and should not diverge:
 *   no `out/` at all   SKIP, with the build command in the title. A build is not a prerequisite
 *                      of any other test, so a fresh clone must not go red over an artifact
 *                      nobody asked for.
 *   `out/` is STALE    SKIP, naming the newer source. A stale artifact is no evidence either way,
 *                      and failing here would turn `npx vitest run` red for anyone who edits a
 *                      component without rebuilding - which is how an inconvenient test gets
 *                      deleted.
 *   page missing       FAIL. The export ran and did not emit a page it should have.
 *   page current       RUN.
 * CI builds immediately before vitest, so it always runs there.
 */

const OUT = join( __dirname, '..', '..', 'out' );
const SRC = join( __dirname, '..' );
const BUILD_HINT = 'run `npm run build` first';

/**
 * The pages read. Chosen as the public surfaces that render the shared interactive components
 * this sweep touched - the phone field, the pill, the resend control and the top band - rather
 * than every route, because the property is per COMPONENT and these pages between them render
 * all of them. Walking 1533 files to re-prove the same fact per route is cost without coverage.
 */
const PAGES = [
  join( 'account', 'sign-in' ),
  join( 'get' ),
  join( 'cart' ),
  join( 'orders' ),
  join( 'blog' ),
  join( 'checkout', 'status' ),
  join( 'checkout', 'success' ),
];

/**
 * Class names that legitimately appear both scoped and unscoped in the same page, so an element
 * carrying the bare name is not evidence of lost scoping.
 *
 * `:global()` IS THE WHOLE REASON THIS LIST IS NOT EMPTY. A rule written
 * `.cs-card :global(.cs-btn){...}` compiles the OUTER class with a hash and leaves the inner one
 * bare, which is exactly how a page styles a capitalised component it renders - next/link
 * forwards className to a DOM node that styled-jsx never transformed, so without :global the
 * rule could not match at all. /checkout/status/ and /checkout/success/ both say so in a comment
 * at the rule. An element carrying such a class correctly has no hash.
 *
 * Kept as exact names, not a prefix: a prefix would silently excuse a future class that happens
 * to start the same way, which is the failure mode of every allowlist.
 */
const GLOBAL_BY_DESIGN = new Set( [ 'co-btn', 'co-btn-primary', 'co-btn-quiet',
  'cs-btn', 'cs-btn-primary', 'cs-btn-quiet' ] );

/** Every source file whose markup these pages render, for the staleness comparison. */
function newestSource (): { path: string; at: number } | null {
  const files = [
    join( SRC, 'components', 'PhoneField.tsx' ),
    join( SRC, 'components', 'PillButton.tsx' ),
    join( SRC, 'components', 'OtpResend.tsx' ),
    join( SRC, 'components', 'PageTopBand.tsx' ),
    join( SRC, 'components', 'BlogSearch.tsx' ),
    join( SRC, 'components', 'BlogSubscribe.tsx' ),
    join( SRC, 'components', 'CheckoutProfile.tsx' ),
    join( SRC, 'pages', 'account', 'sign-in.tsx' ),
    join( SRC, 'pages', 'get.tsx' ),
    join( SRC, 'pages', 'cart.tsx' ),
    join( SRC, 'pages', 'orders.tsx' ),
  ];
  let newest: { path: string; at: number } | null = null;
  for ( const path of files ) {
    if ( !existsSync( path ) ) continue;
    const at = statSync( path ).mtimeMs;
    if ( !newest || at > newest.at ) newest = { path, at };
  }
  return newest;
}

/** class name -> the set of scope hashes its inlined selectors were written with. */
function scopedClasses ( html: string ): Map<string, Set<string>> {
  const scoped = new Map<string, Set<string>>();
  for ( const match of html.matchAll( /\.([A-Za-z][\w-]*)\.(jsx-[0-9a-f]+)/g ) ) {
    const [ , className, hash ] = match;
    if ( className.startsWith( 'jsx-' ) ) continue;
    if ( !scoped.has( className ) ) scoped.set( className, new Set() );
    scoped.get( className )!.add( hash );
  }
  return scoped;
}

function pagePath ( route: string ): string {
  return join( OUT, route, 'index.html' );
}

describe( 'styled-jsx scope hashes survive into the built markup', () => {
  const built = existsSync( OUT );
  const source = newestSource();
  // The oldest of the pages, so one un-rebuilt page is enough to call the export stale.
  const oldestPage = PAGES
    .map( pagePath )
    .filter( existsSync )
    .reduce( ( acc, p ) => Math.min( acc, statSync( p ).mtimeMs ), Number.POSITIVE_INFINITY );
  const havePages = Number.isFinite( oldestPage );
  const stale = havePages && !!source && source.at > oldestPage;

  const skipReason = !built
    ? `no build: ${ BUILD_HINT }`
    : stale
      ? `stale build: ${ source!.path } is newer than the export by `
        + `${ Math.round( ( source!.at - oldestPage ) / 1000 ) }s - ${ BUILD_HINT }`
      : null;

  const run: typeof it = skipReason === null
    ? it
    : ( ( name: string, fn: Parameters<typeof it>[ 1 ] ) =>
        it.skip( `${ name } [${ skipReason }]`, fn ) ) as typeof it;

  for ( const route of PAGES ) {
    run( `/${ route.split( /[\\/]/ ).join( '/' ) }/ stamps every class its own CSS scopes`, () => {
      const file = pagePath( route );
      expect( existsSync( file ),
        `${ file } is missing even though out/ exists - the export ran and did not emit this `
        + `page. ${ BUILD_HINT }` ).toBe( true );

      const html = readFileSync( file, 'utf8' );
      const scoped = scopedClasses( html );
      expect( scoped.size,
        'no scoped selectors found in this page at all - either the page inlines no styled-jsx '
        + 'or the build stopped emitting the scope hash, and both make this assertion vacuous' )
        .toBeGreaterThan( 0 );

      const unscoped: string[] = [];
      for ( const match of html.matchAll( /class="([^"]*)"/g ) ) {
        const value = match[ 1 ];
        const classes = value.split( /\s+/ ).filter( Boolean );
        const hashes = new Set( classes.filter( c => c.startsWith( 'jsx-' ) ) );
        for ( const className of classes ) {
          if ( className.startsWith( 'jsx-' ) ) continue;
          if ( GLOBAL_BY_DESIGN.has( className ) ) continue;
          const required = scoped.get( className );
          if ( !required ) continue;
          if ( ![ ...required ].some( hash => hashes.has( hash ) ) ) {
            unscoped.push( `.${ className } on class="${ value }" `
              + `(its CSS requires one of ${ [ ...required ].join( ', ' ) })` );
          }
        }
      }

      expect( unscoped,
        'these elements carry a class whose styled-jsx selector is scoped, but the element has '
        + 'no matching jsx-* hash - so the selector cannot match and the element ships WITH NONE '
        + 'OF ITS OWN STYLING. This is the defect that shipped twice: the pill rendering as '
        + '"Sign inConfirm code", and the phone field\'s dial-code segment rendering as a second '
        + 'box with the wrong height and radius. The cause is always the same: the JSX was lifted '
        + 'out of the return tree that holds the <style jsx> block - into a variable, a helper, a '
        + '.map, or a CHILD COMPONENT. Put it back inline. If the class genuinely has to be '
        + 'styled from outside the component that renders it, the rule must use :global() and the '
        + 'class belongs in GLOBAL_BY_DESIGN above, with a reason.' )
        .toEqual( [] );
    } );
  }
} );
