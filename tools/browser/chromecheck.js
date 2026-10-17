'use strict';

/**
 * chromecheck - header, footer and support widget on EVERY page that ships.
 *
 * WHAT THIS EXISTS TO STOP. Those three are mounted once in src/pages/_app.tsx, and a page
 * receives them by being on the isPublic allowlist and by no other means. Three separate
 * failures have already come from that single fact, and none of them were visible in the
 * source:
 *
 *  - A page can be exported and reachable while sitting on NO router this file knows about.
 *    src/app/settings/internal-agent/page.tsx lived in an App Router directory, so it never
 *    reached _app.tsx: no Cognito wrapper, no chrome, and no stylesheet. It was served at
 *    HTTP 200 to anyone.
 *  - The existence of that app/ directory ALSO handed not-found handling to the App Router,
 *    so src/pages/404.tsx was ignored and every mistyped URL got Next's built-in shell -
 *    6.8KB, no header, no footer, no widget, and zero links out. The site's own 404 was a
 *    dead end, and nothing in the source said so.
 *  - /contact-test was on the allowlist AND wrapped itself in the authenticated Layout, so
 *    it prerendered the entire staff sidebar into public HTML.
 *
 * WHY IT READS THE BUILT EXPORT rather than the route table. Every one of the above is a
 * discrepancy between what the source implies and what the build emits. A test that reads
 * _app.tsx can only confirm the source agrees with itself. This opens out/ and asks each
 * file what it actually contains, which is the only question a visitor's browser asks.
 *
 * UNIT TESTS COVER THE INTENT, THIS COVERS THE ARTEFACT. src/test/PublicRouteRegistration.
 * test.ts asserts the allowlist and the page files agree; this asserts the HTML on disk has
 * the markup. Both are needed - the first catches a forgotten registration in a second, the
 * second catches a whole router nobody remembered.
 *
 *   node tools/browser/chromecheck.js
 */

const fs = require( 'fs' );
const path = require( 'path' );

const ROOT = path.resolve( __dirname, '..', '..' );
const OUT = path.join( ROOT, 'out' );
const APP_PATH = path.join( ROOT, 'src', 'pages', '_app.tsx' );

/**
 * The markers. Each is a CLASS ON A RENDERED ELEMENT, not an import or a component name:
 * an import proves only that a bundle contains code, and the whole point here is whether the
 * markup reached the page. The WhatsApp destination is checked separately from the widget
 * container because the container can render with the link missing - that is exactly what the
 * catalogue-failure path used to do.
 */
const MARKERS = {
  header: { re: /<header[^>]*class="[^"]*\bhdr\b/, what: 'the public header' },
  footer: { re: /<footer[^>]*class="[^"]*\bft-footer\b/, what: 'the public footer' },
  widget: { re: /class="[^"]*\bwc-langbar\b/, what: 'the support widget' },
  // The short link, not the wa.me URL it resolves to. wecare.digital/r/wa answers 302 to
  // https://wa.me/message/APDM5HUWH26SG1, so the destination is unchanged - but the markup now
  // carries the shortener path, and a marker matching the old URL would report the widget's
  // WhatsApp destination as MISSING on every page.
  whatsapp: { re: /wecare\.digital\/r\/wa/, what: "the widget's WhatsApp destination" },
  lockup: { re: /class="[^"]*\bbrand-lockup\b/, what: 'the brand lockup' },
};

/** How many orphans to open. All of them would be ~105 file reads for one repeated answer. */
const ORPHAN_SAMPLE = 8;

/**
 * Dynamic catalogue patterns can correctly have zero exported instances while ProductsTable is
 * empty. Once a fresh SKU-first catalogue creates an instance, the normal marker checks below
 * automatically apply again.
 */
const OPTIONAL_EMPTY_DYNAMIC = new Set( [ '/shop/[slug]', '/shop/page/[page]' ] );

let failures = 0;
const record = ( ok, name, detail ) => {
  if ( !ok ) failures++;
  console.log( `  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` - ${detail}` : ''}` );
};

/**
 * The allowlist, assembled the same THREE ways _app.tsx assembles it. Missing the third -
 * isContentPublic, which is how /blog and /post/[slug] qualify - is a mistake already made
 * once in this repo's own guard, where it reported /blog as unregistered.
 */
function readAllowlist( app ) {
  const metaStart = app.indexOf( 'const PUBLIC_PAGE_META' );
  const metaEnd = app.indexOf( '\nconst ', metaStart + 10 );
  const meta = Array.from( app.slice( metaStart, metaEnd ).matchAll( /^\s*'(\/[a-z0-9-]+(?:\/[a-z0-9-]+)*)'\s*:/gm ) ).map( m => m[ 1 ] );

  const literals = block => Array.from( block.matchAll( /router\.pathname === '([^']+)'/g ) ).map( m => m[ 1 ] );
  const gateAt = app.indexOf( 'const isPublic' );
  const contentAt = app.indexOf( 'const isContentPublic' );

  return Array.from( new Set( [
    ...meta,
    ...literals( app.slice( gateAt, app.indexOf( ';', gateAt ) ) ),
    ...literals( app.slice( contentAt, app.indexOf( ';', contentAt ) ) ),
  ] ) ).sort();
}

const htmlFor = route => {
  const file = route === '/'
    ? path.join( OUT, 'index.html' )
    : path.join( OUT, route.replace( /^\//, '' ), 'index.html' );
  return fs.existsSync( file ) ? fs.readFileSync( file, 'utf8' ) : null;
};

/** Every exported page, as routes. */
function exportedRoutes() {
  const found = [];
  const walk = ( dir, prefix ) => {
    for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
      if ( entry.name.startsWith( '_' ) ) continue;
      const full = path.join( dir, entry.name );
      if ( entry.isDirectory() ) walk( full, `${prefix}/${entry.name}` );
      else if ( entry.name === 'index.html' ) found.push( prefix || '/' );
    }
  };
  walk( OUT, '' );
  return found;
}

function main() {
  if ( !fs.existsSync( OUT ) ) {
    console.error( `No export at ${OUT}. Run \`npm run build\` first.` );
    process.exit( 1 );
  }
  const app = fs.readFileSync( APP_PATH, 'utf8' );
  const allowlist = readAllowlist( app );

  console.log( 'chromecheck - header, footer and widget in the built export\n' );

  // Anti-vacuous: if the allowlist parse breaks, everything below would pass over an empty
  // list and report success while checking nothing.
  record( allowlist.length >= 15, 'allowlist parsed from _app.tsx', `${allowlist.length} public routes` );
  record( allowlist.includes( '/404' ),
    'the 404 page is registered as public',
    allowlist.includes( '/404' )
      ? 'so it receives the chrome like any other page'
      : 'an unregistered 404 falls to the authenticated branch, or to Next\'s built-in shell with no links out' );

  console.log( `\n${allowlist.length} allowlisted public routes` );
  for ( const route of allowlist ) {
    // Dynamic routes are patterns. Check a real exported instance instead of the pattern,
    // which has no file of its own.
    let target = route, via = '';
    if ( route.includes( '[' ) ) {
      /**
       * THE DIRECTORY IS EVERY SEGMENT BEFORE THE PARAMETER, not just the first one.
       *
       * This read `route.split('/')[1]` until 2026-09-28, which silently assumed every
       * dynamic route is exactly two segments deep. That held while `/post/[slug]` was the
       * only one. `/blog/page/[page]` then failed with "no exported instance" even though
       * the export was correct and contained 35 of them: the lookup resolved to `out/blog`
       * and searched its children for an `index.html`, the only child being `page/`, which
       * has none — `/blog/page/1/` is deliberately never emitted because page 1 is `/blog/`.
       * So a correct export was reported as a missing route, and `Build and test` went red
       * on a harness bug rather than a defect.
       */
      const parts = route.split( '/' ).filter( Boolean );
      const paramAt = parts.findIndex( p => p.startsWith( '[' ) );
      const prefix = parts.slice( 0, paramAt );
      const dir = path.join( OUT, ...prefix );
      const instance = fs.existsSync( dir )
        ? fs.readdirSync( dir ).find( d => fs.existsSync( path.join( dir, d, 'index.html' ) ) )
        : null;
      if ( !instance )
      {
        if ( OPTIONAL_EMPTY_DYNAMIC.has( route ) )
        {
          record( true, `${route}`, 'no exported instance while the catalogue is empty' );
          continue;
        }
        record( false, `${route}`, 'no exported instance of this dynamic route' );
        continue;
      }
      target = `/${prefix.join( '/' )}/${instance}`;
      via = ` (via ${target})`;
    }

    const html = htmlFor( target );
    if ( !html ) { record( false, `${route}`, 'NO EXPORTED HTML - the route is advertised but nothing was built' ); continue; }

    const missing = Object.entries( MARKERS ).filter( ( [ , m ] ) => !m.re.test( html ) );
    record( missing.length === 0, `${route}${via}`,
      missing.length ? `MISSING ${missing.map( ( [ , m ] ) => m.what ).join( ', ' )}` : `${Math.round( html.length / 1024 )}kb` );
  }

  /**
   * ORPHANS - exported, not on the public allowlist.
   *
   * `/workspace/*` is intentionally excluded from the public-chrome assertion. AuthShell is
   * `ssr:false`: authenticated pages deliberately ship an empty app root and hydrate the staff
   * sign-in/workspace shell on the client. Requiring public Header/Footer/SupportWidget markup in
   * their static HTML directly contradicts that security/rendering contract.
   *
   * Other non-public exports are still sampled below because an unexpected customer-facing orphan
   * must not become a dead-end page.
   */
  const allow = new Set( allowlist );
  const exported = exportedRoutes();
  const workspaceRoutes = exported.filter( r => r === '/workspace' || r.startsWith( '/workspace/' ) );
  record( workspaceRoutes.length > 0, 'authenticated workspace exports are present',
    `${workspaceRoutes.length} workspace routes use the client-only AuthShell contract` );

  const orphans = exported.filter( r =>
    !allow.has( r )
    && !r.startsWith( '/post/' )
    && !r.startsWith( '/blog/' )
    && r !== '/workspace'
    && !r.startsWith( '/workspace/' ) );
  console.log( `\n${orphans.length} exported routes not on the allowlist - sampling ${Math.min( ORPHAN_SAMPLE, orphans.length )}` );

  for ( const route of orphans.slice( 0, ORPHAN_SAMPLE ) ) {
    const html = htmlFor( route ) || '';
    const missing = Object.entries( MARKERS ).filter( ( [ , m ] ) => !m.re.test( html ) );
    record( missing.length === 0, `${route}`,
      missing.length ? `MISSING ${missing.map( ( [ , m ] ) => m.what ).join( ', ' )}` : 'sign-in screen with full chrome' );
  }

  /**
   * NO SECOND ROUTER. An app/ directory takes not-found handling away from the Pages Router
   * and gives its own pages no access to _app.tsx, so a single file in it can silently
   * remove the chrome from that page AND from the site's 404 at the same time. That is not a
   * hypothetical: it is what src/app/settings/internal-agent/page.tsx did here.
   */
  const appDirs = [ path.join( ROOT, 'app' ), path.join( ROOT, 'src', 'app' ) ].filter( d => fs.existsSync( d ) );
  record( appDirs.length === 0, 'no App Router directory alongside src/pages',
    appDirs.length
      ? `${appDirs.map( d => path.relative( ROOT, d ) ).join( ', ' )} exists - its pages bypass _app.tsx entirely, and its presence makes Next ignore src/pages/404.tsx`
      : 'every route goes through _app.tsx' );

  console.log( `\n${failures ? `${failures} FAILED` : 'every exported page carries the header, the footer and the widget' }` );
  if ( failures ) process.exit( 1 );
}

main();
