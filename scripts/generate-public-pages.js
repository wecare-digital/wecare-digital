#!/usr/bin/env node
/**
 * Derive the `pages` array of config/public-pages.json by scanning the repository.
 *
 * WHAT PROBLEM THIS CLOSES
 * ------------------------
 * config/public-pages.json is what /mcp answers `list_pages` and `search_pages` from, and
 * what scripts/generate-llms-txt.js turns into /llms.txt. Until now its `pages` array was
 * retyped by hand, which made it the fifth hand-kept copy of the same list:
 *
 *   src/pages/*.tsx                          the pages that actually exist
 *   src/pages/_app.tsx   PUBLIC_PAGE_META    the render allowlist + the schema description
 *   scripts/generate-sitemap.js PUBLIC_EXACT the crawl allowlist
 *   src/content/products.ts, customerservice.ts  the product and request definitions
 *   config/public-pages.json                 what a machine reader is told
 *
 * A hand-kept fifth copy fails in one direction silently and in the other direction
 * embarrassingly. Miss a new page and it is invisible to every agent that reads /llms.txt or
 * calls /mcp. Leave a deleted page in and /mcp hands an agent a URL that 404s - which already
 * happened once: [retired public path] was renamed to /orders, the catalogue was updated, and the MCP
 * Lambda kept serving the old path because nothing redeployed it.
 *
 * So the array is generated. Add a page, delete a page, or reword its description, and the
 * catalogue follows on the next build with no second edit.
 *
 * WHAT IS DERIVED AND WHAT IS NOT - the honest split
 * -------------------------------------------------
 *   path         PUBLIC_EXACT, intersected with a real file under src/pages   derived
 *   name         PUBLIC_PAGE_META, else products.ts / customerservice.ts          derived
 *   description  PUBLIC_PAGE_META                                            derived
 *   group        products.ts -> services, customerservice.ts -> customerservice,
 *                content/legal -> legal, else STRUCTURAL below               declared
 *
 * `group` is the one field no scan can infer, because "is this a platform product or a
 * consumer service" is a positioning decision and nothing in the tree records it. It is
 * therefore DECLARED, and a public route that matches no rule is a hard REFUSAL printing the
 * exact line to add. That is the point rather than a shortcoming: the alternative to failing
 * the build is guessing a group, and a page filed under the wrong heading in llms.txt is
 * harder to notice than a build that stops.
 *
 * Everything else in the file - site, groups, ai_surface, usage_terms - is hand-written and is
 * read and written back untouched. This generator owns `pages` and nothing else.
 *
 * WHY IT READS SOURCE AS TEXT RATHER THAN IMPORTING IT
 * ---------------------------------------------------
 * The same reason src/test/PublicAiSurface.test.ts does: _app.tsx runs Amplify.configure at
 * module scope, products.ts is TypeScript, and this is a plain Node script in the build chain
 * before any transpile step. The values wanted are literals in the files, not runtime exports.
 *
 * RUN ORDER: before generate-llms-txt.js, and it does NOT need out/
 * ----------------------------------------------------------------
 * It reads src/ and config/ only, so it can run before `next build`. That is deliberate -
 * generate-llms-txt.js REFUSES to write when a catalogued page is missing from the export, and
 * that check is only meaningful if the catalogue was settled before the export was made.
 *
 * Run:
 *     node scripts/generate-public-pages.js            # write config/public-pages.json
 *     node scripts/generate-public-pages.js --check     # exit 1 if it would change (CI)
 *     node scripts/generate-public-pages.js --dry-run   # print the diff, write nothing
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname( fileURLToPath( import.meta.url ) );
const ROOT = path.join( __dirname, '..' );

const CATALOG_PATH = path.join( ROOT, 'config', 'public-pages.json' );
const APP_PATH = path.join( ROOT, 'src', 'pages', '_app.tsx' );
const SITEMAP_PATH = path.join( ROOT, 'scripts', 'generate-sitemap.js' );
const PRODUCTS_PATH = path.join( ROOT, 'src', 'content', 'products.ts' );
const CUSTOMERSERVICE_PATH = path.join( ROOT, 'src', 'content', 'customerservice.ts' );
const LEGAL_DIR = path.join( ROOT, 'src', 'content', 'legal' );
const PAGES_DIR = path.join( ROOT, 'src', 'pages' );

/**
 * The routes whose group cannot be read out of any content module, with the name and
 * description to use when PUBLIC_PAGE_META has no entry.
 *
 * Only two routes need the name/description fallback, and it is not an oversight that they
 * lack a PUBLIC_PAGE_META entry: '/' correctly takes the bare-WebPage fallback (a breadcrumb
 * whose only entry is the page you are on says nothing) and '/blog' declares its own <head>
 * and structured data through components/BlogIndexHead.tsx. Neither should be given a meta
 * entry to satisfy this file - that would change what those two pages emit to a crawler in
 * order to tidy a build script.
 *
 * ORDER WITHIN A GROUP IS THIS DECLARATION'S ORDER, so '/' leads. Products and requests take
 * the order their content module lists them in, which is the order the site itself uses.
 */
const STRUCTURAL = [
  { path: '/', group: 'start', name: 'Home',
    description: 'What WECARE.DIGITAL does, and the route into each service.' },
  { path: '/contact', group: 'start' },
  { path: '/blog', group: 'start', name: 'Blog',
    description: 'Published articles. Paginated index; individual posts live under /post/<slug>/.' },
  /*
   * THE CATALOGUE INDEX '/shop' IS WITHDRAWN, 2026-10-04, on owner instruction: it 301s to the
   * home page and src/pages/shop/index.tsx is deleted. Its entry sat here, immediately before
   * /orders, and it is gone rather than commented out because the generated
   * config/public-pages.json is READ BY THE PRODUCTION BUILD GATE: scripts/checkout_release_check.py
   * turns every catalogue path into a page to fetch from the export, so a '/shop' entry becomes a
   * read of out/shop/index.html, which no longer exists - and that failure lands AFTER
   * `next build` has succeeded, failing the Amplify build.
   *
   * The seven PRODUCT pages were never listed here and still are not: /shop/<slug>/ comes into the
   * sitemap through the '/shop/' prefix in scripts/generate-sitemap.js, and this file only carries
   * structural front doors. They keep rendering.
   *
   * Regenerate with `node scripts/generate-public-pages.js`; never hand-edit the JSON.
   *
   * RESTORED 2026-10-10, on owner instruction: '/shop' is a browsable catalogue index again, so
   * generate-sitemap.js re-added it to PUBLIC_EXACT and it needs its group back here or the
   * public-pages gate refuses the build. A 'start' front door, beside /blog and /orders, because
   * it is a way into the catalogue rather than a single service page. The matching page is
   * src/pages/shop/index.tsx; the checkout release gate reads out/shop/index.html, which that
   * page now emits again.
   */
  // The description is the FALLBACK, not the published value: buildPages() resolves
  // `fromMeta?.description || fallback.description` and PUBLIC_PAGE_META in src/pages/_app.tsx
  // carries one for /shop, so this copy is never printed. It is kept because buildPages() refuses
  // a route with no name or description from either source (/blog and / carry theirs the same
  // way), and it is kept IN STEP with _app.tsx because a second, contradicting account of the same
  // page is exactly the drift nothing would ever report.
  { path: '/shop', group: 'start', name: 'Shop',
    description: 'Every WECARE.DIGITAL product and service on one page, each linking to its own page.' },
  { path: '/orders', group: 'start' },
  // Zip is the request/delivery/pickup hub — a front door to a set of actions, like Orders and
  // Blog beside it, rather than a service page — so it sits in 'start'. Its name and description
  // come from PUBLIC_PAGE_META in _app.tsx.
  { path: '/shipments', group: 'start' },
  // Subscribe is a way to get in touch (its CTA is /contact/), so it sits in 'start' beside
  // /contact and /shipments. It is NOT in the 'customerservice' group: that group is read from
  // src/content/customerservice.ts, whose count is fixed in tests/test_mcp_server.py. Its content
  // lives in src/content/subscribe.ts. Name and description come from PUBLIC_PAGE_META.
  { path: '/subscribe', group: 'start' },
  // Perks is its own positioning group (gift cards, rewards, offers), declared in the groups[]
  // array of config/public-pages.json. It is the repaired destination for the gift-card links.
  { path: '/perks', group: 'perks' },
  // Grahak OS and VayuLok are the two platform products: they are what a business buys, as
  // against the consumer services in products.ts. Both have bespoke page files rather than
  // coming through ProductPage.tsx, which is the closest thing to a structural signal - but
  // it is not one this script should infer from, because a future platform product might
  // well be built on the shared component.
  { path: '/grahak-os', group: 'platform' },
  { path: '/vayulok', group: 'platform' },
  // Bharat Rx is a service with its own page file rather than a products.ts entry, so it has
  // to be named. Its description is in PUBLIC_PAGE_META and is load-bearing: the owner
  // corrected it once because it read as a pharmacy, which Bharat Rx is not.
  { path: '/bharat-rx', group: 'services' },
];

const STRUCTURAL_BY_PATH = new Map( STRUCTURAL.map( entry => [ entry.path, entry ] ) );

/** Strip `//` line comments so a path quoted in prose is not mistaken for a declaration. */
const withoutLineComments = ( source ) => source
  .split( '\n' )
  .filter( line => !line.trim().startsWith( '//' ) && !line.trim().startsWith( '*' ) )
  .join( '\n' );

const read = ( file ) => fs.readFileSync( file, 'utf8' );

const refuse = ( ...lines ) => {
  console.error( `\npublic-pages REFUSED:\n  ${lines.join( '\n  ' )}\n` );
  process.exit( 1 );
};

// --------------------------------------------------------------------------- //
// the scans
// --------------------------------------------------------------------------- //

/** PUBLIC_EXACT from the sitemap generator: the set the catalogue is supposed to describe. */
function crawlAllowlist () {
  const source = read( SITEMAP_PATH );
  const start = source.indexOf( 'const PUBLIC_EXACT' );
  if ( start < 0 ) refuse( 'PUBLIC_EXACT not found in scripts/generate-sitemap.js' );
  const block = withoutLineComments( source.slice( start, source.indexOf( '] )', start ) ) );
  const found = new Set( Array.from( block.matchAll( /'(\/[a-z0-9-]*)'/g ) ).map( m => m[ 1 ] ) );
  if ( found.size < 5 ) refuse( `parsed only ${found.size} entries out of PUBLIC_EXACT` );
  return found;
}

/** PUBLIC_PAGE_META: path -> { name, description }. The render allowlist and schema source. */
function renderAllowlist () {
  const source = read( APP_PATH );
  const start = source.indexOf( 'const PUBLIC_PAGE_META' );
  if ( start < 0 ) refuse( 'PUBLIC_PAGE_META not found in src/pages/_app.tsx' );
  const end = source.indexOf( '\nconst ', start + 10 );
  const block = source.slice( start, end === -1 ? undefined : end );
  const entries = new Map();
  const line = /^\s*'(\/[a-z0-9-]+)'\s*:\s*\{\s*name:\s*'((?:[^'\\]|\\.)*)'[^}]*?description:\s*'((?:[^'\\]|\\.)*)'/gm;
  for ( const match of block.matchAll( line ) ) {
    entries.set( match[ 1 ], {
      name: match[ 2 ].replace( /\\'/g, "'" ),
      description: match[ 3 ].replace( /\\'/g, "'" ),
    } );
  }
  if ( entries.size < 5 ) refuse( `parsed only ${entries.size} PUBLIC_PAGE_META entries` );
  return entries;
}

/**
 * Routes the render chains admit by a bare pathname comparison.
 *
 * BOTH chains, not just `isPublic`. `/blog` qualifies through `isContentPublic` - it declares
 * its own <head> through BlogIndexHead.tsx and so has no PUBLIC_PAGE_META entry - and reading
 * only the `isPublic` declaration reported it as unrenderable, which it plainly is not.
 */
function isPublicLiterals () {
  const source = read( APP_PATH );
  const found = new Set();
  for ( const name of [ 'const isContentPublic', 'const isPublic' ] ) {
    const start = source.indexOf( name );
    if ( start < 0 ) refuse( `${name} was not found in src/pages/_app.tsx` );
    const block = source.slice( start, source.indexOf( ';', start ) );
    for ( const match of block.matchAll( /router\.pathname === '([^']+)'/g ) ) found.add( match[ 1 ] );
  }
  if ( found.size < 3 ) refuse( `parsed only ${found.size} literal public routes out of _app.tsx` );
  return found;
}

/** `slug` and `name` pairs out of an exported ProductDef array, in declaration order. */
function contentModule ( file, exportName ) {
  const source = withoutLineComments( read( file ) );
  const start = source.indexOf( `export const ${exportName}` );
  if ( start < 0 ) refuse( `${exportName} not found in ${path.relative( ROOT, file )}` );
  const block = source.slice( start );
  const out = [];
  // slug then name, in that order, which is the shape ProductDef declares and both files use.
  for ( const match of block.matchAll( /slug:\s*'([a-z0-9-]+)'[\s\S]{0,200}?name:\s*'((?:[^'\\]|\\.)*)'/g ) ) {
    out.push( { path: `/${match[ 1 ]}`, name: match[ 2 ].replace( /\\'/g, "'" ) } );
  }
  if ( out.length === 0 ) refuse( `parsed no entries out of ${exportName}` );
  return out;
}

/** The legal pages, from the presence of their content module rather than from a list. */
function legalPages () {
  if ( !fs.existsSync( LEGAL_DIR ) ) return [];
  return fs.readdirSync( LEGAL_DIR )
    .filter( file => file.endsWith( '.ts' ) && file !== 'types.ts' )
    .map( file => ( { path: `/${file.replace( /\.ts$/, '' )}` } ) )
    .sort( ( a, b ) => a.path.localeCompare( b.path ) );
}

/**
 * Does a route have a file that Next will emit?
 *
 * This is the check that makes a DELETED page disappear from the catalogue rather than
 * lingering as a published dead link. generate-llms-txt.js makes the stronger version of the
 * same check against out/, but only at the end of a build; catching it here means the
 * catalogue is right before anything reads it.
 */
function hasPageFile ( routePath ) {
  const slug = routePath === '/' ? 'index' : routePath.replace( /^\//, '' );
  return [ `${slug}.tsx`, path.join( slug, 'index.tsx' ), `${slug}.ts`, path.join( slug, 'index.ts' ) ]
    .some( candidate => fs.existsSync( path.join( PAGES_DIR, candidate ) ) );
}

// --------------------------------------------------------------------------- //
// assembly
// --------------------------------------------------------------------------- //

function buildPages ( catalog ) {
  const allowed = crawlAllowlist();
  const meta = renderAllowlist();
  const chain = isPublicLiterals();
  const groupOrder = ( catalog.groups || [] ).map( group => group.id );
  if ( groupOrder.length === 0 ) refuse( 'the catalogue declares no groups' );

  // group -> the routes in it, in the order that group should list them.
  const grouped = new Map( groupOrder.map( id => [ id, [] ] ) );
  const assign = ( entry, group ) => {
    if ( !grouped.has( group ) ) {
      refuse( `'${entry.path}' wants group '${group}', which config/public-pages.json does not declare.`,
        `Declared groups: ${groupOrder.join( ', ' )}` );
    }
    grouped.get( group ).push( entry );
  };

  // Order of these three passes decides within-group order, so they run in the order the
  // groups themselves are declared rather than alphabetically.
  for ( const entry of STRUCTURAL ) assign( entry, entry.group );
  for ( const entry of contentModule( PRODUCTS_PATH, 'PRODUCTS' ) ) assign( entry, 'services' );
  for ( const entry of contentModule( CUSTOMERSERVICE_PATH, 'CUSTOMERSERVICE' ) ) assign( entry, 'customerservice' );
  for ( const entry of legalPages() ) assign( entry, 'legal' );

  const claimed = new Map();
  for ( const [ group, entries ] of grouped ) {
    for ( const entry of entries ) {
      if ( claimed.has( entry.path ) ) {
        refuse( `'${entry.path}' is claimed by two groups: '${claimed.get( entry.path )}' and '${group}'.` );
      }
      claimed.set( entry.path, group );
    }
  }

  // REFUSE on a route the allowlist publishes that no rule here can place. This is the
  // add-a-page case, and the message is the whole value of the refusal: it names the file to
  // edit and the line to add, so the fix is shorter than reading this script.
  const unplaced = [ ...allowed ].filter( route => !claimed.has( route ) ).sort();
  if ( unplaced.length > 0 ) {
    refuse(
      `${unplaced.length} public route(s) are in PUBLIC_EXACT but no rule here gives them a group:`,
      ...unplaced.map( route => `    ${route}` ),
      '',
      'A group cannot be inferred from the tree - it is a positioning decision. Either add the',
      'route to a content module (src/content/products.ts -> services,',
      'src/content/customerservice.ts -> customerservice), or add a line to STRUCTURAL in this file:',
      ...unplaced.map( route => `    { path: '${route}', group: 'services' },` ),
      '',
      'Guessing one would file the page under the wrong heading in /llms.txt and in every',
      'answer /mcp gives, which is far harder to notice than this failure.',
    );
  }

  // REFUSE on a route this script would publish that the crawl allowlist does not. The two
  // disagreeing means a content module or STRUCTURAL is ahead of generate-sitemap.js, and
  // publishing it here would advertise a page that is not in the sitemap - or, if it is also
  // missing from PUBLIC_PAGE_META, one that renders the staff sign-in shell at HTTP 200.
  const unadvertised = [ ...claimed.keys() ].filter( route => !allowed.has( route ) ).sort();
  if ( unadvertised.length > 0 ) {
    refuse(
      `${unadvertised.length} route(s) would be catalogued but are absent from PUBLIC_EXACT`,
      'in scripts/generate-sitemap.js:',
      ...unadvertised.map( route => `    ${route}` ),
      '',
      'Add them there (and to PUBLIC_PAGE_META in src/pages/_app.tsx, or they render the staff',
      'sign-in screen at HTTP 200), or remove them from the source this script read them from.',
    );
  }

  // REFUSE on a catalogued route with no page file. A deleted page should vanish from here,
  // and it does - but only once its entry is out of PUBLIC_EXACT too, so say which.
  const fileless = [ ...claimed.keys() ].filter( route => !hasPageFile( route ) ).sort();
  if ( fileless.length > 0 ) {
    refuse(
      `${fileless.length} route(s) have no file under src/pages:`,
      ...fileless.map( route => `    ${route}  (expected src/pages${route === '/' ? '/index' : route}.tsx)` ),
      '',
      'If the page was deleted, remove it from PUBLIC_EXACT in scripts/generate-sitemap.js and',
      'from PUBLIC_PAGE_META in src/pages/_app.tsx; this file will then drop it on its own.',
      'If it should exist, the build did not create it, which is the serious case.',
    );
  }

  // REFUSE on a catalogued route that cannot render. PUBLIC_PAGE_META or the isPublic chain
  // is the ONLY thing that makes a page render at all; a route missing from both serves the
  // staff sign-in screen at HTTP 200 - "a 404 that does not look like one".
  const unrenderable = [ ...claimed.keys() ]
    .filter( route => !meta.has( route ) && !chain.has( route ) )
    .sort();
  if ( unrenderable.length > 0 ) {
    refuse(
      `${unrenderable.length} route(s) are in neither PUBLIC_PAGE_META nor the isPublic chain`,
      'in src/pages/_app.tsx, so they render the staff sign-in screen at HTTP 200:',
      ...unrenderable.map( route => `    ${route}` ),
    );
  }

  // Descriptions come from PUBLIC_PAGE_META, which is also what feeds WebPage.description in
  // the schema graph - so a crawler and an agent reading /llms.txt get the same sentence
  // rather than two accounts of one page.
  const pages = [];
  const undescribed = [];
  for ( const [ group, entries ] of grouped ) {
    for ( const entry of entries ) {
      const fromMeta = meta.get( entry.path );
      const fallback = STRUCTURAL_BY_PATH.get( entry.path ) || {};
      const name = fromMeta?.name || entry.name || fallback.name;
      const description = fromMeta?.description || fallback.description;
      if ( !name || !description ) { undescribed.push( entry.path ); continue; }
      pages.push( { path: entry.path, group, name, description } );
    }
  }
  if ( undescribed.length > 0 ) {
    refuse(
      `${undescribed.length} route(s) have no name or description available:`,
      ...undescribed.map( route => `    ${route}` ),
      '',
      'Add a PUBLIC_PAGE_META entry in src/pages/_app.tsx - that is where the sentence belongs,',
      'because it is also the WebPage.description a crawler reads. Only add a name/description',
      'to STRUCTURAL here for a page that deliberately declares its own <head> instead.',
    );
  }

  if ( pages.length < 5 ) refuse( `built only ${pages.length} pages; that cannot be right` );
  return pages;
}

// --------------------------------------------------------------------------- //

const args = new Set( process.argv.slice( 2 ) );
const checkOnly = args.has( '--check' );
const dryRun = args.has( '--dry-run' );

const before = read( CATALOG_PATH );
const catalog = JSON.parse( before );
catalog.pages = buildPages( catalog );
const after = `${JSON.stringify( catalog, null, 2 )}\n`;

if ( before === after ) {
  console.log( `public-pages: ${catalog.pages.length} pages — config/public-pages.json is current` );
  process.exit( 0 );
}

const summarise = ( source ) => new Set(
  ( JSON.parse( source ).pages || [] ).map( page => `${page.group} ${page.path} ${page.description}` ),
);
const wasSet = summarise( before );
const isSet = summarise( after );
const added = [ ...isSet ].filter( entry => !wasSet.has( entry ) );
const removed = [ ...wasSet ].filter( entry => !isSet.has( entry ) );
for ( const entry of removed ) console.log( `  - ${entry}` );
for ( const entry of added ) console.log( `  + ${entry}` );

if ( checkOnly ) {
  console.error(
    '\npublic-pages CHECK FAILED: config/public-pages.json is not what a fresh scan produces.'
    + '\n  The committed catalogue disagrees with the pages that actually exist, so /llms.txt and'
    + '\n  /mcp are describing a site that is not the one in this tree.'
    + '\n\n  Regenerate and commit:  node scripts/generate-public-pages.js\n',
  );
  process.exit( 1 );
}
if ( dryRun ) {
  console.log( `\npublic-pages: WOULD write ${catalog.pages.length} pages (dry run)` );
  process.exit( 0 );
}

fs.writeFileSync( CATALOG_PATH, after, 'utf8' );
console.log( `public-pages: wrote ${catalog.pages.length} pages -> config/public-pages.json` );
console.log(
  '  NOTE: /mcp carries a COPY of this file in its deployment zip. Redeploy it, or the'
  + '\n  endpoint keeps describing the old page set: python scripts/deploy_mcp_server.py',
);
