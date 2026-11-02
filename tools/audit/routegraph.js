'use strict';

/**
 * routegraph - the site's internal link graph, read from the static export.
 *
 * WHY THIS IS NOT A BROWSER HARNESS. Everything it checks - which routes exist, which
 * routes are linked, which links resolve - is a property of the emitted HTML, so it needs
 * no Chromium and no server. It remains in tools/audit/ because it verifies the
 * static export; the earlier tools/browser/ QA suite was retired separately.
 *
 * WHAT IT ANSWERS
 *   1. every route the export emits, classified public / workspace / other
 *   2. every internal href, and whether it resolves to an emitted route  -> MISSING
 *   3. every route with no inbound link from any other route             -> ORPHAN
 *   4. sitemap coverage: public routes absent from sitemap.xml, and vice versa
 *
 * HREFS ARE READ FROM RENDERED HTML, so a link only counts if it actually shipped in the
 * markup. A route reachable only through a click handler or a router.push() is invisible
 * here and will be reported as an orphan - that is the intent, since a crawler cannot see
 * those either.
 *
 * TRAILING SLASHES. next.config.js sets trailingSlash:true, so '/contact/' is the emitted
 * form and '/contact' is a redirect. Both normalise to the same key here; the raw form is
 * kept so a mixed-style link can still be reported.
 *
 * Run: node tools/audit/routegraph.js            (needs out/ - npm run build)
 *      node tools/audit/routegraph.js --json     machine-readable
 */

const fs = require( 'fs' );
const path = require( 'path' );

const OUT = path.join( __dirname, '..', '..', 'out' );
if ( !fs.existsSync( OUT ) ) {
  console.error( 'out/ not found - run npm run build first' );
  process.exit( 2 );
}

/* ---------- 1. every emitted route ---------- */

function walk( dir, acc = [] ) {
  for ( const e of fs.readdirSync( dir, { withFileTypes: true } ) ) {
    const p = path.join( dir, e.name );
    if ( e.isDirectory() ) {
      if ( e.name === '_next' || e.name === 'images' ) continue;
      walk( p, acc );
    } else if ( e.name.endsWith( '.html' ) ) {
      acc.push( p );
    }
  }
  return acc;
}

/** out/contact/index.html -> /contact/ ; out/404.html -> /404/ ; out/index.html -> / */
function routeOf( file ) {
  let r = '/' + path.relative( OUT, file ).split( path.sep ).join( '/' );
  if ( r.endsWith( '/index.html' ) ) r = r.slice( 0, -'index.html'.length );
  else r = r.replace( /\.html$/, '/' );
  return r === '' ? '/' : r;
}

const files = walk( OUT );
const routes = new Map(); // route -> absolute file path
for ( const f of files ) routes.set( routeOf( f ), f );

/* Routes the export emits that are not pages a visitor navigates to. */
const NON_PAGE = new Set( [ '/404/', '/offline/' ] );

/* Dynamic-route placeholders Next emits literally; they are templates, not pages. */
const isTemplate = r => r.includes( '[' );

const classify = r => {
  if ( r.startsWith( '/workspace/' ) ) return 'workspace';
  if ( NON_PAGE.has( r ) ) return 'non-page';
  if ( isTemplate( r ) ) return 'template';
  return 'public';
};

/* ---------- 2. every internal href ---------- */

const HREF = /(?:href|action)="([^"]+)"/g;

/** Normalise a link to the emitted route form, or null if it is not an internal page link. */
function normalise( href ) {
  if ( !href ) return null;
  if ( /^(https?:|mailto:|tel:|whatsapp:|data:|javascript:|#)/i.test( href ) ) return null;
  if ( !href.startsWith( '/' ) ) return null;              // relative - none in this export
  let p = href.split( '#' )[ 0 ].split( '?' )[ 0 ];
  if ( p === '' ) return null;
  if ( p.startsWith( '/_next/' ) ) return null;            // build assets
  if ( /\.(xml|txt|json|png|jpg|jpeg|svg|webp|ico|webmanifest|pdf|js|css)$/i.test( p ) ) return null;
  if ( !p.endsWith( '/' ) ) p += '/';
  return p;
}

/** Routes served outside the export: infrastructure and redirect origins. */
const EXTERNAL_PREFIX = [ '/api/', '/r/' ];
const isExternallyServed = r => EXTERNAL_PREFIX.some( p => r.startsWith( p ) );

const inbound = new Map();   // route -> Set(source route)
const missing = new Map();   // unresolved route -> Set(source route)
const rawMixed = new Map();  // href without trailing slash -> Set(source route)

for ( const [ route, file ] of routes ) {
  const html = fs.readFileSync( file, 'utf8' );
  let m;
  HREF.lastIndex = 0;
  while ( ( m = HREF.exec( html ) ) ) {
    const raw = m[ 1 ];
    const target = normalise( raw );
    if ( !target || target === route ) continue;

    if ( raw.startsWith( '/' ) && !raw.split( '#' )[ 0 ].split( '?' )[ 0 ].endsWith( '/' )
         && !/\.[a-z0-9]+$/i.test( raw.split( '#' )[ 0 ].split( '?' )[ 0 ] ) ) {
      if ( !rawMixed.has( raw ) ) rawMixed.set( raw, new Set() );
      rawMixed.get( raw ).add( route );
    }

    if ( routes.has( target ) ) {
      if ( !inbound.has( target ) ) inbound.set( target, new Set() );
      inbound.get( target ).add( route );
    } else if ( !isExternallyServed( target ) ) {
      if ( !missing.has( target ) ) missing.set( target, new Set() );
      missing.get( target ).add( route );
    }
  }
}

/* ---------- 3. orphans ---------- */

const orphans = [ ...routes.keys() ]
  .filter( r => r !== '/' )
  .filter( r => classify( r ) !== 'non-page' )
  .filter( r => !( inbound.get( r ) && inbound.get( r ).size ) );

/* ---------- 4. sitemap coverage ---------- */

let sitemap = new Set();
const smPath = path.join( OUT, 'sitemap.xml' );
if ( fs.existsSync( smPath ) ) {
  const xml = fs.readFileSync( smPath, 'utf8' );
  for ( const m of xml.matchAll( /<loc>([^<]+)<\/loc>/g ) ) {
    try {
      let p = new URL( m[ 1 ] ).pathname;
      if ( !p.endsWith( '/' ) ) p += '/';
      sitemap.add( p );
    } catch { /* ignore malformed loc */ }
  }
}

const publicRoutes = [ ...routes.keys() ].filter( r => classify( r ) === 'public' ).sort();
const notInSitemap = publicRoutes.filter( r => !sitemap.has( r ) );
const sitemapNotEmitted = [ ...sitemap ].filter( r => !routes.has( r ) ).sort();
const workspaceInSitemap = [ ...sitemap ].filter( r => r.startsWith( '/workspace/' ) ).sort();

/* ---------- report ---------- */

const counts = { public: 0, workspace: 0, template: 0, 'non-page': 0 };
for ( const r of routes.keys() ) counts[ classify( r ) ]++;

if ( process.argv.includes( '--json' ) ) {
  console.log( JSON.stringify( {
    counts,
    publicRoutes,
    missing: [ ...missing ].map( ( [ r, s ] ) => ( { route: r, linkedFrom: [ ...s ] } ) ),
    orphans: orphans.map( r => ( { route: r, kind: classify( r ) } ) ),
    notInSitemap, sitemapNotEmitted, workspaceInSitemap,
    mixedSlash: [ ...rawMixed ].map( ( [ h, s ] ) => ( { href: h, from: [ ...s ] } ) ),
  }, null, 2 ) );
  process.exit( 0 );
}

const h = s => console.log( `\n=== ${s} ===` );

h( 'ROUTES EMITTED' );
console.log( `  total ${routes.size}  |  public ${counts.public}  workspace ${counts.workspace}` +
             `  template ${counts.template}  non-page ${counts[ 'non-page' ] }` );

h( `PUBLIC ROUTES (${publicRoutes.length})` );
for ( const r of publicRoutes ) {
  const n = inbound.get( r ) ? inbound.get( r ).size : 0;
  console.log( `  ${String( n ).padStart( 4 )} inbound  ${r}` );
}

h( `MISSING TARGETS - linked but not emitted (${missing.size})` );
if ( !missing.size ) console.log( '  none' );
for ( const [ r, from ] of [ ...missing ].sort() ) {
  const f = [ ...from ];
  console.log( `  ${r}\n      from ${f.length} route(s): ${f.slice( 0, 6 ).join( ', ' )}${f.length > 6 ? ` +${f.length - 6}` : ''}` );
}

h( `ORPHANS - emitted but nothing links to them (${orphans.length})` );
if ( !orphans.length ) console.log( '  none' );
const byKind = {};
for ( const r of orphans ) ( byKind[ classify( r ) ] ||= [] ).push( r );
for ( const k of Object.keys( byKind ).sort() ) {
  console.log( `  [${k}] ${byKind[ k ].length}` );
  for ( const r of byKind[ k ].sort() ) console.log( `      ${r}` );
}

h( 'SITEMAP' );
console.log( `  entries ${sitemap.size}` );
console.log( `  public routes absent from sitemap (${notInSitemap.length}): ${notInSitemap.join( ', ' ) || 'none'}` );
console.log( `  sitemap entries with no emitted page (${sitemapNotEmitted.length}): ${sitemapNotEmitted.slice( 0, 10 ).join( ', ' ) || 'none'}${sitemapNotEmitted.length > 10 ? ` +${sitemapNotEmitted.length - 10}` : ''}` );
console.log( `  workspace routes leaked into sitemap (${workspaceInSitemap.length}): ${workspaceInSitemap.join( ', ' ) || 'none'}` );

h( `MIXED TRAILING SLASH - href without the slash trailingSlash:true emits (${rawMixed.size})` );
if ( !rawMixed.size ) console.log( '  none' );
for ( const [ href, from ] of [ ...rawMixed ].sort().slice( 0, 25 ) ) {
  console.log( `  ${href}  <- ${[ ...from ].slice( 0, 3 ).join( ', ' )}` );
}

const fail = missing.size + workspaceInSitemap.length + sitemapNotEmitted.length;
console.log( `\n${fail ? `FAIL: ${fail} integrity problem(s)` : 'ok: no broken internal links'}` );
