#!/usr/bin/env node
/* CommonJS, matching the rest of tools/audit - the directory's own package.json overrides the
 * repo root's "type": "module". */

/**
 * Every public page is indexable; every inner page is not. Asserted, not assumed.
 *
 * WHY THIS IS A GATE AND NOT A REPORT. Three independent mechanisms decide whether a URL can
 * reach Google's index, they live in three different files, and they fail in OPPOSITE
 * directions:
 *
 *   robots meta      src/pages/_app.tsx and each page's own <Head>   - permission to index
 *   robots.txt       public/robots.txt                               - permission to fetch
 *   sitemap.xml      scripts/generate-sitemap.js                     - the invitation
 *
 * Nothing reconciles them. So the failures are all silent:
 *
 *   noindex + in the sitemap        -> Google reports the contradiction and trusts neither
 *   indexable + absent from sitemap -> crawlable but never advertised
 *   advertised + Disallowed         -> "Indexed, though blocked by robots.txt"
 *   inner page missing its noindex  -> the authenticated dashboard's route map is published
 *
 * The last one is the expensive one, and this repository has shipped its close cousin before:
 * `/contact-test/` was in the public allowlist AND wrapped in the authenticated <Layout>, so
 * it returned HTTP 200 carrying the entire staff sidebar to anyone who asked. That was found
 * by hand on the live site. robots.txt's own header records the rule that came out of it - a
 * top-level segment belongs in exactly one of the sitemap allowlist or a Disallow - and this
 * file is that rule made executable.
 *
 * "INNER PAGES" means the authenticated dashboard: the `inner-page` class,
 * src/styles/inner-pages.css, everything under /workspace/. Those must be excluded by ALL
 * THREE mechanisms, not just one, because any single one of them can be edited away.
 *
 * PUBLIC ROUTES DELIBERATELY NOT INDEXABLE are allowlisted below with reasons.
 * The allowlist is exact and closed: any unapproved noindex public page fails
 * this check and requires review. Customer-session screens remain excluded
 * from the sitemap even as legacy flow pages are retired.
 *
 * A DECLARED DUPLICATE IS NOT AN UNADVERTISED PAGE. A page whose rel=canonical names another
 * URL is telling Google to index that URL instead, and generate-sitemap.js correctly leaves it
 * out (a sitemap lists canonical URLs only). It passes here only when its canonical target is
 * itself advertised and emitted - a duplicate pointing at nothing indexable still fails.
 *
 * Usage:  node tools/audit/indexcheck.js            (after npm run build)
 *         node tools/audit/indexcheck.js --json
 */
const fs = require( 'fs' );
const path = require( 'path' );

const OUT = path.join( __dirname, '..', '..', 'out' );
const SITE = 'https://wecare.digital';
const JSON_MODE = process.argv.includes( '--json' );

/** The authenticated dashboard. Must be excluded by robots meta AND robots.txt AND the sitemap. */
const INNER_PREFIX = '/workspace/';

/**
 * Public routes that are deliberately NOT indexable. Exact matches only, each with the reason,
 * because "we meant that one" is the whole difference between this list and a bug.
 */
const ALLOWED_NOINDEX = {
  '/404/': 'a redirect stub, not a page - src/pages/404.tsx sends the visitor to the home '
    + 'page. Indexing it would put a redirect in the index; Google reports those as "Page '
    + 'with redirect". It exists only because deleting it restores Next\'s built-in 404, '
    + 'which ships zero links.',
  // Static customer-session screens stay out of PUBLIC_PAGE_META, the sitemap and the AI manifest.
  // Customer sign-in is not static anymore: /auth is the backend-routed, noindex canonical entry.
  '/cart/': 'a noindex legacy handoff to /checkout/ for old basket links, not a payment surface.',
  '/checkout/': 'the one signed-in cart review and direct Razorpay page - session state.',
  '/checkout/status/': 'the payment-confirmation screen a customer returns to from an in-chat '
    + 'payment - meaningful only for that payment.',
  '/checkout/success/': 'the order-confirmation screen for one order - session state.',
};

/** rel=canonical, if the page declares one. */
const CANONICAL = /<link\b[^>]*\brel="canonical"[^>]*>/i;
function canonicalRoute ( html ) {
  const tag = ( html.match( CANONICAL ) || [] )[ 0 ];
  const href = tag && ( tag.match( /\bhref="([^"]+)"/i ) || [] )[ 1 ];
  if ( !href ) return '';
  try
  {
    const url = new URL( href, SITE );
    if ( url.origin !== SITE ) return href;
    return url.pathname.endsWith( '/' ) ? url.pathname : `${url.pathname}/`;
  }
  catch { return href; }
}

function emittedRoutes ( dir = OUT, base = '' ) {
  const out = [];
  if ( !fs.existsSync( dir ) ) return out;
  for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) )
  {
    if ( entry.name.startsWith( '_' ) || entry.name.startsWith( '.' ) ) continue;
    const full = path.join( dir, entry.name );
    if ( entry.isDirectory() ) out.push( ...emittedRoutes( full, `${base}/${entry.name}` ) );
    else if ( entry.name === 'index.html' ) out.push( base === '' ? '/' : `${base}/` );
  }
  return out;
}

function robotsDisallows () {
  for ( const candidate of [ path.join( OUT, 'robots.txt' ),
    path.join( __dirname, '..', '..', 'public', 'robots.txt' ) ] )
  {
    if ( !fs.existsSync( candidate ) ) continue;
    return fs.readFileSync( candidate, 'utf-8' ).split( '\n' )
      .filter( line => /^\s*disallow\s*:/i.test( line ) )
      .map( line => line.split( ':' ).slice( 1 ).join( ':' ).trim() )
      .filter( Boolean );
  }
  return [];
}

function sitemapRoutes () {
  const file = path.join( OUT, 'sitemap.xml' );
  if ( !fs.existsSync( file ) ) return new Set();
  const xml = fs.readFileSync( file, 'utf-8' );
  const out = new Set();
  for ( const m of xml.matchAll( /<loc>([^<]+)<\/loc>/g ) )
  {
    let p = m[ 1 ].startsWith( SITE ) ? m[ 1 ].slice( SITE.length ) : m[ 1 ];
    if ( !p.endsWith( '/' ) ) p += '/';
    out.add( p === '' ? '/' : p );
  }
  return out;
}

const META = /<meta[^>]+name="robots"[^>]+content="([^"]*)"/i;

const routes = emittedRoutes();
if ( routes.length === 0 )
{
  console.error( 'indexcheck: out/ is empty or missing - run `npm run build` first' );
  process.exit( 1 );
}

const disallows = robotsDisallows();
const advertised = sitemapRoutes();

const blockedBy = route => disallows.find( rule => rule !== '/' && route.startsWith( rule ) ) || '';

const pages = routes.map( route => {
  const file = route === '/' ? path.join( OUT, 'index.html' )
    : path.join( OUT, route.replace( /^\/|\/$/g, '' ), 'index.html' );
  const html = fs.readFileSync( file, 'utf-8' );
  const m = META.exec( html );
  const meta = m ? m[ 1 ] : '';
  const canonical = canonicalRoute( html );
  return {
    route,
    meta,
    // The URL this page asks to be indexed as, when it is not itself.
    canonicalElsewhere: canonical && canonical !== route ? canonical : '',
    noindex: /noindex/i.test( meta ),
    disallow: blockedBy( route ),
    advertised: advertised.has( route ),
    inner: route.startsWith( INNER_PREFIX ),
  };
} );

const inner = pages.filter( p => p.inner );
const publicPages = pages.filter( p => !p.inner );

const problems = {
  innerIndexable: inner.filter( p => !p.noindex )
    .map( p => `${p.route} has no noindex (meta="${p.meta || 'none'}")` ),
  innerNotDisallowed: inner.filter( p => !p.disallow )
    .map( p => `${p.route} is not covered by any robots.txt Disallow` ),
  innerAdvertised: inner.filter( p => p.advertised )
    .map( p => `${p.route} is in sitemap.xml` ),
  publicNoindex: publicPages.filter( p => p.noindex && !( p.route in ALLOWED_NOINDEX ) )
    .map( p => `${p.route} carries noindex and is not on the allowlist (meta="${p.meta}")` ),
  publicDisallowed: publicPages.filter( p => p.disallow )
    .map( p => `${p.route} is Disallowed by "${p.disallow}"` ),
  contradicted: publicPages.filter( p => p.advertised && ( p.noindex || p.disallow ) )
    .map( p => `${p.route} is advertised AND suppressed (noindex=${p.noindex} disallow="${p.disallow}")` ),
  unadvertised: publicPages.filter( p => !p.advertised && !p.noindex && !p.disallow && !p.canonicalElsewhere )
    .map( p => `${p.route} is indexable but absent from sitemap.xml` ),
  // A declared duplicate must point at a URL that is both advertised and emitted; otherwise the
  // "index that one instead" it declares leads nowhere indexable.
  badCanonicalTarget: publicPages.filter( p => !p.noindex && p.canonicalElsewhere
      && !( advertised.has( p.canonicalElsewhere ) && routes.includes( p.canonicalElsewhere ) ) )
    .map( p => `${p.route} canonicalises to ${p.canonicalElsewhere}, which is not an advertised, emitted page` ),
  // ...and a declared duplicate must not ALSO be advertised: the sitemap lists canonicals only.
  advertisedDuplicate: publicPages.filter( p => p.advertised && p.canonicalElsewhere )
    .map( p => `${p.route} is in sitemap.xml but canonicalises to ${p.canonicalElsewhere}` ),
  // An allowlisted page that stopped being noindex is also a failure: the allowlist records a
  // decision, and silently reverting it is the regression this catches in the other direction.
  allowlistDrift: Object.keys( ALLOWED_NOINDEX )
    .filter( route => {
      const page = pages.find( p => p.route === route );
      return page && !page.noindex;
    } )
    .map( route => `${route} is allowlisted as noindex but no longer carries it` ),
  sitemapOrphans: [ ...advertised ].filter( r => !routes.includes( r ) )
    .map( r => `${r} is in sitemap.xml but no page was emitted` ),
};

const checks = [
  [ 'every inner page carries noindex', problems.innerIndexable ],
  [ 'every inner page is robots-Disallowed', problems.innerNotDisallowed ],
  [ 'no inner page is in the sitemap', problems.innerAdvertised ],
  [ 'no unapproved public page carries noindex', problems.publicNoindex ],
  [ 'no public page is robots-Disallowed', problems.publicDisallowed ],
  [ 'no page is advertised and suppressed at once', problems.contradicted ],
  [ 'every indexable public page is in the sitemap', problems.unadvertised ],
  [ 'every declared duplicate canonicalises to an advertised page', problems.badCanonicalTarget ],
  [ 'no declared duplicate is advertised', problems.advertisedDuplicate ],
  [ 'allowlisted noindex pages still carry it', problems.allowlistDrift ],
  [ 'every sitemap URL has an emitted page', problems.sitemapOrphans ],
];

if ( JSON_MODE )
{
  console.log( JSON.stringify( {
    emitted: pages.length, inner: inner.length, public: publicPages.length,
    sitemap: advertised.size, disallows, allowedNoindex: Object.keys( ALLOWED_NOINDEX ),
    problems,
  }, null, 2 ) );
}
else
{
  console.log( `indexcheck - ${pages.length} emitted pages: ${inner.length} inner, ${publicPages.length} public` );
  console.log( `  sitemap entries   ${advertised.size}` );
  console.log( `  robots.txt Disallow  ${[ ...new Set( disallows ) ].join( ', ' ) || '(none)'}` );
  console.log( `  indexable public pages  ${publicPages.filter( p => !p.noindex && !p.disallow ).length}` );
  console.log( '\nDELIBERATELY NOT INDEXABLE (allowlisted)' );
  for ( const [ route, why ] of Object.entries( ALLOWED_NOINDEX ) )
  {
    const page = pages.find( p => p.route === route );
    console.log( `  ${route}  ${page ? `meta="${page.meta}"` : 'NOT EMITTED'}` );
    console.log( `      ${why.replace( /\s+/g, ' ' ).slice( 0, 150 )}` );
  }
  console.log( '\nASSERTIONS' );
  for ( const [ label, list ] of checks )
  {
    console.log( `  ${list.length === 0 ? 'ok  ' : 'FAIL'} ${label}${list.length ? ` (${list.length})` : ''}` );
    for ( const line of list.slice( 0, 6 ) ) console.log( `         ${line}` );
    if ( list.length > 6 ) console.log( `         +${list.length - 6} more` );
  }
}

const total = checks.reduce( ( n, [ , list ] ) => n + list.length, 0 );
if ( !JSON_MODE )
{
  console.log( total
    ? `\nFAIL: ${total} indexability problem(s)`
    : '\nok: every public page is indexable, every inner page is excluded three ways' );
}
process.exit( total ? 1 : 0 );
