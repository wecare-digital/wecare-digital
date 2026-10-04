import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * GUARDS THE ONE MISTAKE THAT SHIPS A LOGIN WALL TO THE PUBLIC.
 *
 * Header and Footer are rendered ONCE, centrally, in _app.tsx - but only inside
 * `if ( isPublic )`. `isPublic` is an EXACT-MATCH allowlist, so creating a file under
 * src/pages is NOT enough to make a page public. A route that is missing from the
 * allowlist falls through to the authenticated branch and renders the STAFF SIGN-IN
 * SCREEN at HTTP 200 - no header, no footer, no page. _app.tsx calls this "a 404 that
 * does not look like one", and records that it reached the live site exactly that way
 * when the file-collection page was at /files.
 *
 * Nothing caught that until somebody loaded the URL. These tests do, at build time.
 *
 * WHY ROOT-LEVEL FILES ONLY. Authenticated surfaces live in directories
 * (dm/, dashboard/, pay/, seo/, service/, ...), while a new marketing or customer-facing
 * page is created as src/pages/<name>.tsx. Scanning the root is therefore the check with
 * signal and no false alarms; a directory-wide scan would flag the entire dashboard.
 * If a root-level page is ever deliberately authenticated, add it to
 * INTENTIONALLY_NOT_PUBLIC below with the reason, so the exemption is a decision on the
 * record rather than a silently passing test.
 *
 * THESE READ SOURCE AS TEXT rather than importing _app.tsx. Importing it would execute
 * Amplify.configure and the analytics side-effects at module scope, and the values being
 * asserted are literals in the file, not runtime exports. It is the same technique
 * GrahakOsPage.test.tsx and BottomNav.test.tsx already use.
 */

const PAGES_DIR = path.join( process.cwd(), 'src', 'pages' );
const APP_PATH = path.join( PAGES_DIR, '_app.tsx' );
const SITEMAP_PATH = path.join( process.cwd(), 'scripts', 'generate-sitemap.js' );

/** Root-level pages that are deliberately NOT public. Empty today - keep it that way. */
const INTENTIONALLY_NOT_PUBLIC: Record<string, string> = {};

/**
 * Directory-backed pages that do NOT use the dashboard Layout and are still deliberately
 * staff-only. All three are redirects rather than pages - they mount, call router.replace
 * and render nothing a visitor would read - which is why they have no Layout and would
 * otherwise look public-shaped to the scan below.
 */
const INTENTIONALLY_NOT_PUBLIC_DIRS: Record<string, string> = {
  access: 'redirect shim, not a page',
  admin: 'redirect shim, not a page',
  forms: 'redirect shim, not a page',
};

const appSource = fs.readFileSync( APP_PATH, 'utf8' );

/**
 * The routes _app.tsx treats as public, assembled the same two ways the component does:
 * the keys of PUBLIC_PAGE_META, plus the bare `router.pathname === '...'` comparisons in
 * the isPublic chain (which is how '/' and '/get' qualify), plus the isContentPublic chain
 * (which is how '/blog' and '/post/[slug]' qualify).
 */
const readAllowlist = (): Set<string> => {
  const metaStart = appSource.indexOf( 'const PUBLIC_PAGE_META' );
  expect( metaStart, 'PUBLIC_PAGE_META not found in _app.tsx - this guard needs updating' ).toBeGreaterThan( -1 );
  // The map ends at the declaration that follows it; slice to the next top-level `const`
  // so a route added at the bottom of the map is still seen.
  const metaEnd = appSource.indexOf( '\nconst ', metaStart + 10 );
  const metaBlock = appSource.slice( metaStart, metaEnd === -1 ? undefined : metaEnd );
  const metaRoutes = Array.from( metaBlock.matchAll( /^\s*'(\/[a-z0-9-]+)'\s*:/gm ) ).map( m => m[ 1 ] );

  const gateStart = appSource.indexOf( 'const isPublic' );
  expect( gateStart, 'isPublic not found in _app.tsx - this guard needs updating' ).toBeGreaterThan( -1 );
  const gateBlock = appSource.slice( gateStart, appSource.indexOf( ';', gateStart ) );
  const literalRoutes = Array.from( gateBlock.matchAll( /router\.pathname === '([^']+)'/g ) ).map( m => m[ 1 ] );

  /**
   * The third source, which this used to miss: isContentPublic, a separate const that
   * isPublic ORs in. /blog and /post/[slug] qualify only through it, so an allowlist built
   * from the two sources above reported /blog as unregistered - a false alarm that the
   * older assertions happened to dodge by exempting anything starting with /blog or /post.
   */
  const contentStart = appSource.indexOf( 'const isContentPublic' );
  expect( contentStart, 'isContentPublic not found in _app.tsx - this guard needs updating' ).toBeGreaterThan( -1 );
  const contentBlock = appSource.slice( contentStart, appSource.indexOf( ';', contentStart ) );
  const contentRoutes = Array.from( contentBlock.matchAll( /router\.pathname === '([^']+)'/g ) ).map( m => m[ 1 ] );

  return new Set( [ ...metaRoutes, ...literalRoutes, ...contentRoutes ] );
};

/** Route a root-level page file resolves to. index.tsx is the root itself. */
const routeForFile = ( file: string ): string =>
  file === 'index.tsx' ? '/' : `/${file.replace( /\.tsx$/, '' )}`;

const rootPageFiles = fs.readdirSync( PAGES_DIR )
  .filter( entry => entry.endsWith( '.tsx' ) && !entry.startsWith( '_' ) )
  .sort();

/**
 * One level of directory-backed pages: src/pages/<name>/index.tsx. /grahak-os, /vayulok
 * and /blog are all this shape, so "root-level files only" left a public page shape
 * completely unguarded. Deeper nesting (dm/whatsapp/..., seo/page/) is skipped:
 * it is dashboard territory and every one of those would be a false alarm.
 */
const dirPages = fs.readdirSync( PAGES_DIR, { withFileTypes: true } )
  .filter( entry => entry.isDirectory() && entry.name !== 'api' && !entry.name.startsWith( '_' ) )
  .filter( entry => fs.existsSync( path.join( PAGES_DIR, entry.name, 'index.tsx' ) ) )
  .map( entry => ( { dir: entry.name, file: path.join( PAGES_DIR, entry.name, 'index.tsx' ) } ) )
  .sort( ( a, b ) => a.dir.localeCompare( b.dir ) );

/**
 * Does this page file wrap itself in the authenticated dashboard shell? That import is the
 * single most reliable signal of intent in src/pages: 102 of the 123 page files have it and
 * every one of them is staff-only, while no public page needs it - _app.tsx already
 * supplies the public Header and Footer.
 */
const importsDashboardLayout = ( file: string ): boolean =>
  /import\s+\w+\s+from\s+'[^']*components\/(Layout|MaybeLayout)'/.test( fs.readFileSync( file, 'utf8' ) );

/** Resolve a public allowlist route to the page file that serves it, if one exists. */
const fileForRoute = ( route: string ): string | null => {
  const candidates = route === '/'
    ? [ path.join( PAGES_DIR, 'index.tsx' ) ]
    : [
      path.join( PAGES_DIR, `${route.replace( /^\//, '' )}.tsx` ),
      path.join( PAGES_DIR, route.replace( /^\//, '' ), 'index.tsx' ),
    ];
  return candidates.find( candidate => fs.existsSync( candidate ) ) || null;
};

describe( 'public route registration', () => {
  it( 'finds root-level page files to check', () => {
    // A sanity check on the scan itself. If a refactor moves every page into a directory
    // this drops to zero and the assertions below would pass vacuously - the exact
    // failure mode of a gate that protects nothing.
    expect( rootPageFiles.length ).toBeGreaterThan( 5 );
    expect( rootPageFiles ).toContain( 'index.tsx' );
  } );

  it( 'registers every root-level page in the isPublic allowlist', () => {
    const allowlist = readAllowlist();
    const unregistered = rootPageFiles
      .map( file => ( { file, route: routeForFile( file ) } ) )
      .filter( ( { file, route } ) =>
        !allowlist.has( route ) && !( file in INTENTIONALLY_NOT_PUBLIC )
      );

    expect(
      unregistered.map( u => `${u.file} -> ${u.route}` ),
      'These pages exist but are NOT in the isPublic allowlist in _app.tsx, so they render '
      + 'the staff sign-in screen at HTTP 200 instead of the page - with no header and no '
      + 'footer. Add each route to PUBLIC_PAGE_META (marketing pages, which also gets it '
      + 'structured data and a sitemap entry) or to the router.pathname chain in isPublic '
      + '(public but non-marketing, as /get does).'
    ).toEqual( [] );
  } );

  it( 'keeps the allowlist free of routes that have no page file', () => {
    // The mirror of the test above. A route left in the allowlist after its page is
    // deleted advertises structured data, and possibly a sitemap entry, for a URL that
    // 404s - which is how [retired public path] and /studio came to be listed long after deletion.
    const allowlist = readAllowlist();
    const rootRoutes = new Set( rootPageFiles.map( routeForFile ) );
    /*
     * Directory-backed public routes. These resolve to <dir>/index.tsx rather than a
     * root-level file, so they are checked against the directory instead.
     *
     * TIGHTENED 2026-10-04 TO REQUIRE index.tsx, not merely the directory. The old test was
     * `existsSync( dir ) && statSync( dir ).isDirectory()`, which asks whether the FOLDER exists
     * and never whether anything in it serves the route. That is the `[retired path]` defect by
     * name: when the /shop index was withdrawn, src/pages/shop/ stayed on disk because
     * [slug].tsx lives in it, so '/shop' would have remained classified dir-backed and this
     * orphan test would have passed with a deleted page still advertised in the allowlist and
     * the sitemap - the exact failure the test exists to catch.
     *
     * The same file already does it correctly for `dirPages` above, which filters on
     * index.tsx. All four currently dir-backed allowlist routes (/blog, /grahak-os, /vayulok,
     * and /shop before its withdrawal) have an index.tsx, so this breaks nothing that renders.
     */
    const dirBacked = Array.from( allowlist ).filter( route => {
      const dir = path.join( PAGES_DIR, route.replace( /^\//, '' ) );
      return route !== '/' && fs.existsSync( path.join( dir, 'index.tsx' ) );
    } );

    /**
     * DYNAMIC ROUTES ARE NOW RESOLVED TO A FILE INSTEAD OF EXEMPTED BY PREFIX.
     *
     * This used to skip anything starting with /post or /blog, on the grounds that "dynamic and
     * content routes are matched by pattern, not by a literal file name". The prefix was the
     * problem: it exempted five real routes from the only check that notices a route left in the
     * allowlist after its page is deleted - which is the exact failure this test exists for, and
     * the one that left [retired public path] and /studio advertised long after deletion.
     *
     * fileForRoute already resolves a bracketed pattern, because the path segments are literal
     * directory and file names on disk: '/shop/[slug]' is src/pages/shop/[slug].tsx and
     * '/blog/topic/[topic]/page/[page]' is src/pages/blog/topic/[topic]/page/[page].tsx. Measured
     * on this tree, all five dynamic routes in the allowlist resolve, so nothing needs exempting.
     */
    const orphaned = Array.from( allowlist ).filter( route =>
      !rootRoutes.has( route )
      && !dirBacked.includes( route )
      && fileForRoute( route ) === null
    );

    expect(
      orphaned,
      'These routes are in the _app.tsx public allowlist but have no page file, so they '
      + 'are advertised (structured data, and possibly the sitemap) while returning 404.'
    ).toEqual( [] );
  } );

  it( 'registers every directory-backed page that is not on the dashboard', () => {
    // The hole the root-level scan left. /grahak-os, /vayulok and /contact-test are all
    // src/pages/<name>/index.tsx, so a new public page created in that shape and forgotten
    // in the allowlist shipped the staff sign-in screen with nothing to catch it.
    //
    // "Not on the dashboard" is read off the Layout import rather than guessed from the
    // path, because the path says nothing: /store and [retired public path] are staff, /grahak-os and
    // /vayulok are marketing, and all four are a directory with an index.tsx.
    const allowlist = readAllowlist();
    const unregistered = dirPages
      .filter( ( { dir, file } ) =>
        !( dir in INTENTIONALLY_NOT_PUBLIC_DIRS )
        && !importsDashboardLayout( file )
        && !allowlist.has( `/${dir}` )
      )
      .map( ( { dir } ) => `/${dir}` );

    expect(
      unregistered,
      'These pages do not use the dashboard Layout, so they are public in shape, but they '
      + 'are missing from the isPublic allowlist in _app.tsx - which means they render the '
      + 'staff sign-in screen at HTTP 200 with no header, footer or support widget. Add each '
      + 'route to PUBLIC_PAGE_META, or to INTENTIONALLY_NOT_PUBLIC_DIRS with a reason if it '
      + 'really is staff-only.'
    ).toEqual( [] );
  } );

  it( 'never lets a public route render the dashboard Layout', () => {
    // THIS IS THE ONE THAT WAS ALREADY BROKEN IN PRODUCTION, and it is the sharpest check
    // in this file because it needs no heuristic - being in the allowlist and importing
    // Layout is a contradiction on its face.
    //
    // /contact-test was both. The export is prerendered with no session, so Layout rendered
    // in full and https://wecare.digital/contact-test/ served the entire staff sidebar -
    // Inbox, Contacts, Broadcast, Payments, Service Ops, Store, Forms, Tasks - plus the page
    // search box and BottomNav, at HTTP 200, to anyone. It sat alongside the public Header
    // and Footer that _app.tsx adds, so the page also carried two brand lockups.
    //
    // Nothing flagged it: it is directory-backed, so the root-level scan never saw it, and
    // it WAS in the allowlist, so the orphan check was satisfied too.
    const allowlist = readAllowlist();
    const leaking = Array.from( allowlist )
      .map( route => ( { route, file: fileForRoute( route ) } ) )
      .filter( ( { file } ) => file !== null && importsDashboardLayout( file ) )
      .map( ( { route, file } ) => `${route} -> ${path.relative( process.cwd(), file as string )}` );

    expect(
      leaking,
      'These routes are public AND wrap themselves in the authenticated dashboard Layout. '
      + 'Because pages are prerendered without a session, that exports the whole staff '
      + 'sidebar and page search into public HTML, on top of the Header and Footer _app.tsx '
      + 'already adds. A public page must not import Layout - _app.tsx supplies its chrome.'
    ).toEqual( [] );
  } );

  it( 'keeps PUBLIC_PAGE_META and the sitemap allowlist in step', () => {
    // generate-sitemap.js carries its own explicit allowlist and its comment requires the
    // two to match: "a route missing there renders an empty body with HTTP 200, so
    // advertising it here without it there would put blank pages in front of a crawler."
    // The reverse - a marketing page that renders but is never submitted - is the silent
    // half, and is what this asserts.
    //
    // NOT a two-way equality: the sitemap deliberately carries /blog, and /get is
    // deliberately public WITHOUT being in the sitemap.
    const sitemapSource = fs.readFileSync( SITEMAP_PATH, 'utf8' );
    const exactStart = sitemapSource.indexOf( 'PUBLIC_EXACT' );
    expect( exactStart, 'PUBLIC_EXACT not found in generate-sitemap.js' ).toBeGreaterThan( -1 );
    const exactBlock = sitemapSource.slice( exactStart, sitemapSource.indexOf( '] )', exactStart ) );
    const sitemapRoutes = new Set(
      Array.from( exactBlock.matchAll( /'(\/[a-z0-9-]*)'/g ) ).map( m => m[ 1 ] )
    );

    const metaStart = appSource.indexOf( 'const PUBLIC_PAGE_META' );
    const metaEnd = appSource.indexOf( '\nconst ', metaStart + 10 );
    const metaBlock = appSource.slice( metaStart, metaEnd === -1 ? undefined : metaEnd );
    const metaRoutes = Array.from( metaBlock.matchAll( /^\s*'(\/[a-z0-9-]+)'\s*:/gm ) ).map( m => m[ 1 ] );

    const missingFromSitemap = metaRoutes.filter( route => !sitemapRoutes.has( route ) );

    expect(
      missingFromSitemap,
      'These marketing routes are in PUBLIC_PAGE_META but missing from PUBLIC_EXACT in '
      + 'scripts/generate-sitemap.js, so they render for visitors but are never submitted '
      + 'to search engines.'
    ).toEqual( [] );
  } );
} );


/**
 * THE THREE PIECES THAT MUST BE ON EVERY PAGE — header, footer, support widget.
 *
 * Until now this was a convention held up by the fact that nobody had edited the two
 * return statements in _app.tsx. Nothing asserted it, so any refactor that moved Header
 * into a single page, or dropped Footer from the public branch while tidying the JSX,
 * would have shipped. The tests above guarantee a page REACHES the public branch; these
 * guarantee the branch still has chrome in it once the page gets there.
 *
 * There are three surfaces, not two, and the third is the one that gets forgotten because
 * it is not a route: AuthGate, the sign-in screen, which every visitor without a session
 * sees - including everyone who mistypes a URL, since anything outside the allowlist falls
 * through to it.
 *
 * WHAT IS DELIBERATELY NOT ASSERTED: that the authenticated dashboard carries the public
 * Header and Footer. It carries neither, by design. Layout.tsx has its own top bar, its own
 * sidebar and no footer at all; a second position:fixed header would collide with both and
 * a footer would have to clear the 60px BottomNav plus the safe-area inset. The widget is
 * the piece that IS common to all three, and PublicWidgets.test.tsx counts its mounts.
 */
describe( 'common chrome on every public surface', () => {
  const publicBranch = ( (): string => {
    const start = appSource.indexOf( 'if ( isPublic )' );
    const end = appSource.indexOf( '// Protected pages', start );
    expect( start, 'the isPublic branch was not found in _app.tsx - this guard needs updating' ).toBeGreaterThan( -1 );
    expect( end, 'the authenticated branch marker was not found in _app.tsx' ).toBeGreaterThan( start );
    return appSource.slice( start, end );
  } )();

  const authGate = ( (): string => {
    const start = appSource.indexOf( 'const AuthGate' );
    const end = appSource.indexOf( '\nexport default function App', start );
    expect( start, 'AuthGate was not found in _app.tsx - this guard needs updating' ).toBeGreaterThan( -1 );
    return appSource.slice( start, end === -1 ? undefined : end );
  } )();

  it( 'renders header, footer and widget inside the public branch', () => {
    // Sliced to the branch rather than searched for in the whole file on purpose: Header
    // and Footer are also rendered by AuthGate, so a file-wide toContain would keep passing
    // after they were deleted from here - the exact regression this is meant to catch.
    expect( publicBranch, 'the public branch must render <Header>' ).toContain( '<Header ' );
    expect( publicBranch, 'the public branch must render <Footer />' ).toContain( '<Footer />' );
    expect( publicBranch, 'the public branch must render <SupportWidget />' ).toContain( '<SupportWidget />' );
  } );

  it( 'gives the sign-in screen the same three pieces', () => {
    // AuthGate is public-facing whether or not it is a route. Somebody who cannot sign in
    // needs a way to reach us from the screen that is refusing them, which is why the
    // widget belongs here and not only on the marketing pages.
    expect( authGate, 'AuthGate must render <Header>' ).toContain( '<Header />' );
    expect( authGate, 'AuthGate must render <Footer />' ).toContain( '<Footer />' );
    expect( authGate, 'AuthGate must render <SupportWidget />' ).toContain( '<SupportWidget />' );
  } );

  it( 'keeps all three imported and mounted centrally, never per page', () => {
    // The invariant that makes "every new page gets chrome automatically" true: chrome is
    // mounted in _app.tsx and NOWHERE ELSE. A page that imported Header itself would render
    // a second one on top of the first, and - worse - would make the layout look fine on
    // that page while it silently broke for every page that did not copy the import.
    for ( const component of [ 'Header', 'Footer', 'SupportWidget' ] ) {
      expect( appSource ).toContain( `import ${component} from '../components/${component}'` );
    }

    const offenders: string[] = [];
    const walk = ( dir: string ): void => {
      for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
        const full = path.join( dir, entry.name );
        if ( entry.isDirectory() ) {
          if ( entry.name !== 'api' ) walk( full );
        } else if ( entry.name.endsWith( '.tsx' ) && !entry.name.startsWith( '_' ) ) {
          const source = fs.readFileSync( full, 'utf8' );
          if ( /from\s+'[^']*components\/(Header|Footer|SupportWidget)'/.test( source ) ) {
            offenders.push( path.relative( process.cwd(), full ) );
          }
        }
      }
    };
    walk( PAGES_DIR );

    expect(
      offenders,
      'These page files import Header, Footer or SupportWidget directly. All three are '
      + 'mounted once in _app.tsx so that every page - including every page created in '
      + 'future - inherits them without being edited. Importing one into a page renders it '
      + 'twice on that page and does nothing for any other.'
    ).toEqual( [] );
  } );
} );
