'use strict';

/**
 * navcheck - the workspace navigation against the routes the build actually emits.
 *
 * WHY THIS IS SEPARATE FROM routegraph.js. routegraph reads hrefs out of the rendered
 * HTML, and every /workspace/ page ships ZERO /workspace/ hrefs: the shell is rendered on
 * the client behind an auth gate, so the sidebar exists in no static document. Measured on
 * out/workspace/communications/index.html - 0 matches for href="/workspace. routegraph therefore
 * reports all 105 workspace routes as orphans, which is true of the crawlable graph and
 * says nothing about whether an operator can reach them.
 *
 * So the workspace's real reachability question is a SOURCE question - is the route in
 * src/config/navigation.ts - and that is what this checks. The two scripts together cover
 * the site: routegraph owns the public graph, navcheck owns the authenticated one.
 *
 * WHY THE PATHS ARE REGEX-EXTRACTED rather than imported. navigation.ts is TypeScript and
 * the app is type:module; importing it needs a transpile step, and a transpile in an audit
 * script is a dependency that can break independently of the thing being audited. Every
 * path in that file is written as a `path: '...'` literal - 113 of them - so a regex sees
 * all of them, including any a hand-maintained list would drift from.
 *
 * QUERY STRINGS ARE FILTERS, NOT ROUTES. '/workspace/engage/inbox?channel=rcs' is the inbox
 * with a selector pre-set; it resolves to the inbox page. Stripped before comparison, and
 * counted separately so the report does not claim five missing pages that are one page.
 *
 * Run: node tools/audit/navcheck.js        (needs out/ - npm run build)
 */

const fs = require( 'fs' );
const path = require( 'path' );

const REPO = path.join( __dirname, '..', '..' );
const OUT = path.join( REPO, 'out' );
const NAV = path.join( REPO, 'src', 'config', 'navigation.ts' );

if ( !fs.existsSync( OUT ) ) { console.error( 'out/ not found - run npm run build' ); process.exit( 2 ); }

/* ---------- emitted workspace routes ---------- */

function walk( dir, acc = [] ) {
  for ( const e of fs.readdirSync( dir, { withFileTypes: true } ) ) {
    const p = path.join( dir, e.name );
    if ( e.isDirectory() ) walk( p, acc );
    else if ( e.name === 'index.html' ) acc.push( p );
  }
  return acc;
}

const emitted = new Set(
  walk( path.join( OUT, 'workspace' ) ).map( f => {
    const r = '/' + path.relative( OUT, f ).split( path.sep ).join( '/' );
    return r.slice( 0, -'index.html'.length ).replace( /\/$/, '' );
  } )
);

/* ---------- paths declared in navigation.ts ---------- */

const src = fs.readFileSync( NAV, 'utf8' );
const declared = new Map(); // route (no query) -> Set(raw declaration)
const withQuery = [];

for ( const m of src.matchAll( /path:\s*'([^']+)'/g ) ) {
  const raw = m[ 1 ];
  if ( raw.includes( '?' ) ) withQuery.push( raw );
  const base = raw.split( '?' )[ 0 ].replace( /\/$/, '' );
  if ( !declared.has( base ) ) declared.set( base, new Set() );
  declared.get( base ).add( raw );
}

/* Labels, so a report line names the thing rather than only its path. */
const labelOf = new Map();
for ( const m of src.matchAll( /path:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'/g ) ) {
  labelOf.set( m[ 1 ].split( '?' )[ 0 ].replace( /\/$/, '' ), m[ 2 ] );
}

/* ---------- page -> page edges, read from source ---------- */

/*
 * ABSENT FROM navigation.ts IS NOT THE SAME AS UNREACHABLE, and the first version of
 * this script conflated them. It reported ten absences; seven of them an operator can
 * open today, because this app reaches pages two ways the sidebar never mentions:
 *
 *   1. A HUB EMBEDS CAPABILITIES AS TABS. Current Communications and Channels
 *      routes contain the actual messaging tools; a removed compatibility
 *      redirect is not an additional feature page. Imports may be relative,
 *      so route-string search alone does not establish whether a tool exists.
 *   2. A PAGE LINKS THEM BY STRING. /workspace/index.tsx is a tile grid, and its
 *      Settings tile is the only route to settings/internal-agent.
 *
 * So resolve both kinds of edge and walk the graph from the nav rows. What survives the
 * walk is unreachable for real, and that number is the only one worth acting on.
 */

const PAGES = path.join( REPO, 'src', 'pages' );

/** route -> source file, and the reverse. */
const fileOfRoute = new Map();
for ( const r of emitted ) {
  const rel = r.replace( /^\//, '' );
  for ( const cand of [ `${rel}.tsx`, `${rel}.ts`, `${rel}/index.tsx`, `${rel}/index.ts` ] ) {
    const f = path.join( PAGES, cand );
    if ( fs.existsSync( f ) ) { fileOfRoute.set( r, f ); break; }
  }
}
const routeOfFile = new Map( [ ...fileOfRoute ].map( ( [ r, f ] ) => [ f, r ] ) );

/** Resolve an import specifier the way the bundler would, but only to a page file. */
function resolvePage( fromFile, spec ) {
  if ( !spec.startsWith( '.' ) ) return null;
  const base = path.resolve( path.dirname( fromFile ), spec );
  for ( const cand of [ `${base}.tsx`, `${base}.ts`, path.join( base, 'index.tsx' ), path.join( base, 'index.ts' ) ] ) {
    if ( routeOfFile.has( cand ) ) return routeOfFile.get( cand );
  }
  return null;
}

/** route -> [{ to, how }] */
const edges = new Map();
/** route -> the path it redirects to, when that is all the page does. */
const redirectOnly = new Map();

for ( const [ route, file ] of fileOfRoute ) {
  const code = fs.readFileSync( file, 'utf8' );
  const out = [];

  for ( const m of code.matchAll( /(?:from|import\s*\(\s*)\s*'(\.[^']+)'/g ) ) {
    const to = resolvePage( file, m[ 1 ] );
    if ( to && to !== route ) out.push( { to, how: 'embeds' } );
  }
  /* Backticks as well as quotes, and cut at the first interpolation: a row that pushes
   * `/workspace/seo/page/?id=${p.id}` is a link to /workspace/seo/page, and a quotes-only
   * matcher saw no link there at all. */
  for ( const m of code.matchAll( /[`'"](\/workspace\/[^`'"]*)/g ) ) {
    const to = m[ 1 ].split( '${' )[ 0 ].split( '?' )[ 0 ].replace( /\/$/, '' );
    if ( emitted.has( to ) && to !== route ) out.push( { to, how: 'links' } );
  }

  edges.set( route, out );

  /* A shim whose whole body is a router.replace: a bookmark catcher, not a screen. */
  const redirect = code.match( /router\.replace\(\s*'([^']+)'/ );
  if ( redirect && !/<(main|section|table|form)\b/.test( code ) && code.split( '\n' ).length < 30 ) {
    redirectOnly.set( route, redirect[ 1 ] );
  }
}

/* ---------- compare ---------- */

const navMissing = [ ...declared.keys() ]
  .filter( r => r.startsWith( '/workspace' ) )
  .filter( r => !emitted.has( r ) )
  .sort();

const notInNav = [ ...emitted ]
  .filter( r => !declared.has( r ) )
  .sort();

/* Walk out from the nav rows. Nothing else counts as a starting point: a page only
 * two orphans link to is still an orphan. */
const reachedVia = new Map(); // route -> "how, from where"
const queue = [ ...declared.keys() ].filter( r => emitted.has( r ) );
const seen = new Set( queue );
while ( queue.length ) {
  const from = queue.shift();
  for ( const { to, how } of edges.get( from ) || [] ) {
    if ( seen.has( to ) ) continue;
    seen.add( to );
    reachedVia.set( to, `${how === 'embeds' ? 'embedded by' : 'linked from'} ${from}${labelOf.has( from ) ? ` ("${labelOf.get( from )}")` : ''}` );
    queue.push( to );
  }
}

/*
 * A route with other emitted routes beneath it is a namespace parent, and those are
 * deliberately link-less: they exist so that trimming a URL resolves instead of 404ing,
 * which in a static export it otherwise does not. /workspace itself was added for exactly
 * that reason - read its docblock - and /workspace/service is the same shape, a tile grid
 * over three children that all have their own nav rows. Derived from the route tree rather
 * than listed, so a new namespace parent is not reported as a defect on the day it lands.
 *
 * Still reported, in their own group: nothing links them, so if one ever grew content of
 * its own that content would be unfindable.
 */
const isNamespaceParent = r => [ ...emitted ].some( o => o !== r && o.startsWith( r + '/' ) );

const orphaned = notInNav.filter( r =>
  !reachedVia.has( r ) && !redirectOnly.has( r ) && !isNamespaceParent( r ) && !r.includes( '[' )
);

/* A literal dynamic-route segment emitted as a real directory. */
const literalDynamic = [ ...emitted ].filter( r => r.includes( '[' ) ).sort();

/* ---------- report ---------- */

const h = s => console.log( `\n=== ${s} ===` );

h( 'COUNTS' );
console.log( `  workspace pages emitted      ${emitted.size}` );
console.log( `  distinct paths in navigation ${declared.size}  (${withQuery.length} of them query-string filters)` );

h( `NAV POINTS AT A PAGE THAT IS NOT BUILT (${navMissing.length})` );
if ( !navMissing.length ) console.log( '  none' );
for ( const r of navMissing ) console.log( `  ${r}${labelOf.has( r ) ? `   "${labelOf.get( r )}"` : ''}` );

h( `BUILT BUT ABSENT FROM navigation.ts (${notInNav.length}) - only the last group is a defect` );
const pad = r => r.padEnd( 40 );
const reachedAnyway = notInNav.filter( r => reachedVia.has( r ) );
const intentional = notInNav.filter( r => !reachedVia.has( r ) && ( redirectOnly.has( r ) || isNamespaceParent( r ) ) );
console.log( `  reachable anyway (${reachedAnyway.length}):` );
for ( const r of reachedAnyway ) console.log( `    ${pad( r )}${reachedVia.get( r )}` );
console.log( `  intentional (${intentional.length}):` );
for ( const r of intentional ) {
  console.log( `    ${pad( r )}${redirectOnly.has( r ) ? `redirect-only shim -> ${redirectOnly.get( r )}` : 'namespace parent, reached only by trimming a URL'}` );
}
console.log( `  NO WAY IN (${orphaned.length}):` );
if ( !orphaned.length ) console.log( '    none' );
for ( const r of orphaned ) console.log( `    ${pad( r )}not in nav, not embedded, not linked` );

h( `LITERAL DYNAMIC SEGMENT SERVED AS A PAGE (${literalDynamic.length})` );
if ( !literalDynamic.length ) console.log( '  none' );
for ( const r of literalDynamic ) console.log( `  ${r}   <- a real 200 at a URL containing brackets` );

h( 'QUERY-STRING NAV ENTRIES (filters, not pages)' );
for ( const q of withQuery ) console.log( `  ${q}` );

const fail = navMissing.length + orphaned.length + literalDynamic.length;
console.log( `\n${fail ? `${fail} finding(s)` : 'ok: navigation and build agree'}` );
