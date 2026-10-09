#!/usr/bin/env node
/**
 * Generate the PUBLIC sitemap for wecare.digital from the static export.
 *
 * THE APEX, NOT `www`, and that is not a typo correction. This header said
 * `www.wecare.digital` until 2026-09-30, while SITE_URL below has always emitted the apex.
 * The mismatch matters because Search Console's URL Inspection reports the home page as
 * "Duplicate, Google chose different canonical than user" with Google's canonical set to
 * `https://www.wecare.digital/` - a URL that 301s to the apex. Google is holding a stale
 * `www` signal, every current signal we emit says apex (canonical, og:url, this sitemap,
 * robots.txt, llms.txt - all measured at 0 `www` references), and a comment naming the
 * wrong host is exactly how somebody "helpfully" reintroduces one.
 *
 * The repository contains many authenticated dashboard pages under the same
 * static export. They must never be emitted into the public sitemap.
 */
import { execFileSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath( import.meta.url );
const __dirname = path.dirname( __filename );
const REPO_ROOT = path.join( __dirname, '..' );

const SITE_URL = 'https://wecare.digital';
const OUT_DIR = path.join( __dirname, '..', 'out' );
const OUTPUT_FILE = path.join( OUT_DIR, 'sitemap.xml' );

// EXPLICIT ALLOWLIST, deliberately - the export also contains the authenticated
// dashboard, so scanning for every index.html would leak those into a public sitemap.
// Anything added here must be a real public route AND in the isPublic allowlist in
// _app.tsx, or it will 200 with an empty body.
//
// [retired public path] and /partners were removed: both pages were deleted on owner instruction, so
// those entries described URLs that no longer build. /terms and /privacy carry real
// published documents now and are indexable, so they belong here.
const PUBLIC_EXACT = new Set( [
  '/',
  '/bharat-rx',
  '/blog',
  '/contact',
  '/grahak-os',
  '/orders',
  '/privacy',
  '/terms',
  '/vayulok',
  // The eight product pages. These must stay in step with PUBLIC_PAGE_META in _app.tsx:
  // a route missing there renders an empty body with HTTP 200, so advertising it here
  // without it there would put blank pages in front of a crawler.
  '/clear-closure',
  '/dastavez',
  '/elsewhere',
  '/expo-week',
  // Renamed '[retired public path]' -> '[retired public path]' -> '/anew'. Alphabetical, so it moved to the
  // top of this group.
  '/anew',
  '/hunar',
  '/niji-setu',
  '/ritual-guru',
  // The Customer service pages. Same rule as the product group above: these must stay in
  // step with PUBLIC_PAGE_META in _app.tsx, because a route advertised here but missing
  // there serves an empty body at HTTP 200 - i.e. it would put blank pages in front of a
  // crawler. They replaced six menu labels that all resolved to /contact/.
  '/drop-docs',
  '/leave-review',
  '/refer-and-earn',
  '/request-amendment',
  '/submit-request',
  // Vault is the return leg of Drop Docs: one page sends paperwork in, this one asks for a
  // copy back. It is NOT /get/, which stays out of the sitemap because it needs a verified
  // link to mean anything - this page is the linkable front door that points at it.
  '/vault',
  // THE CATALOGUE INDEX '/shop' IS WITHDRAWN, 2026-10-04, on owner instruction: it 301s to the
  // home page and its page file is deleted, so advertising it here would submit a URL that
  // redirects. Its PUBLIC_PAGE_META entry in _app.tsx went with it - the two are coupled by
  // src/test/PublicRouteRegistration.test.ts. The seven PRODUCT pages are NOT withdrawn: they come
  // in through the '/shop/' PREFIX below, which stays.
  // Zip (the request/delivery/pickup hub) and Perks (gift cards, rewards, offers). Same rule as
  // every group above: both are in PUBLIC_PAGE_META in _app.tsx, so they render; advertising them
  // here without that entry would put blank pages in front of a crawler. /perks is also the
  // repaired destination for the gift-card links.
  '/perks',
  '/shipments',
  // Subscribe is a way to contact us (its CTA is /contact/), added after Leave Review in the
  // Request menu. It must stay in step with PUBLIC_PAGE_META in _app.tsx, like every group above.
  '/subscribe',
] );
// '/blog/page/' is pages 2..N of the paginated blog index. It has to be a prefix rather than
// exact entries because the count moves with the corpus - 834 posts at 24 a page is 35 pages
// today and a different number after the next publish, so listing them would go stale on a
// content change rather than on a code change.
//
// THEY MUST BE IN THE SITEMAP. Before pagination every post was linked from the single /blog/
// document; now 810 of the 834 are listed only on pages 2-35, so leaving those pages out would
// leave most of the corpus with no crawlable listing at all. This is also why BlogIndexHead
// makes each page self-canonical and index,follow rather than pointing them at /blog/.
// '/blog/topic/' is one stream per non-default category. Those streams are the ONLY index pages
// listing their posts - /blog/ paginates the default category only - so leaving them out would
// advertise 824 posts and hide 40.
// '/shop/' is the seven catalogue pages. A prefix rather than seven exact entries because the set
// is enumerated from src/content/wix-catalog.json by getStaticPaths - it changes when the snapshot
// is refreshed, which is a content change, and listing the slugs here would mean a sitemap that
// goes stale on a data refresh instead of on a code change.
//
// THIS PREFIX MUST STAY, and since 2026-10-04 it is the ONLY way the product pages are advertised.
// It used to read "/shop/ links to all seven, but a product page is the page a search should land
// on" - the index was withdrawn on owner instruction that day, so there is no longer a listing
// linking to them at all and this prefix is their only crawlable route in. Note it keeps working
// because normalizeRoute('/shop/file-assist/') yields '/shop/file-assist', which still
// startsWith('/shop/'); the withdrawn index was an EXACT entry, so removing it cannot affect this.
const PUBLIC_PREFIXES = [ '/post/', '/blog/page/', '/blog/topic/', '/shop/' ];

function normalizeRoute ( base ) {
  if ( !base ) return '/';
  const route = base.startsWith( '/' ) ? base : '/' + base;
  return route.replace( /\/+$/, '' ) || '/';
}

function isPublicRoute ( route ) {
  return PUBLIC_EXACT.has( route ) || PUBLIC_PREFIXES.some( prefix => route.startsWith( prefix ) );
}

function findHtmlFiles ( dir, base = '' ) {
  const urls = [];
  if ( !fs.existsSync( dir ) ) return urls;

  const entries = fs.readdirSync( dir, { withFileTypes: true } );
  for ( const entry of entries )
  {
    const fullPath = path.join( dir, entry.name );
    const urlPath = base + '/' + entry.name;

    if ( entry.isDirectory() )
    {
      if ( entry.name.startsWith( '_' ) || entry.name.startsWith( '.' ) || entry.name === 'node_modules' ) continue;
      urls.push( ...findHtmlFiles( fullPath, urlPath ) );
    }
    else if ( entry.name === 'index.html' )
    {
      const route = normalizeRoute( base );
      if ( isPublicRoute( route ) ) urls.push( route );
    }
  }
  return urls;
}

/* ------------------------------------------------------------------------- *
 * lastmod
 *
 * THIS USED TO BE `new Date()` FOR EVERY URL, WHICH IS THE ONE WAY TO GET THE ONE
 * FIELD GOOGLE ACTUALLY READS WRONG. Measured on the live sitemap before this change:
 * 1353 URLs, 1353 of them stamped with the build date, every build. Google's own
 * guidance on the sitemaps ping deprecation is explicit that lastmod has to match
 * reality or it stops being believed - and once it stops being believed for a domain,
 * an accurate lastmod on the twenty URLs that did change is worth nothing either.
 * changefreq and priority are already ignored outright, so a fabricated lastmod left
 * the sitemap advertising 1353 URLs and telling Google nothing usable about any of them.
 *
 * Three sources, in the order they are trusted, all of them OFFLINE - no new network
 * dependency is added to the build, deliberately, because the guard further down this
 * file exists precisely because a network-dependent build step already failed silently
 * once:
 *
 *   /post/<slug>/       the page's own JSON-LD dateModified. This is the strongest
 *                       source available: it is the date the page itself states, so
 *                       the sitemap cannot contradict the document Google fetches.
 *
 *   index pages         the newest dateModified among the posts the page links. An
 *                       index page's content IS its list of posts, so it changes when
 *                       they do. Derived from the emitted HTML, so pagination moving
 *                       a post between pages is picked up without any bookkeeping.
 *
 *   static pages        the last commit date of the page's own source file.
 *
 * WHEN NONE OF THE THREE ANSWERS, THE ELEMENT IS OMITTED. lastmod is optional, and
 * omitting it costs only a hint, while guessing it costs the credibility of every
 * other date in the file. A shallow CI clone with no usable history is the realistic
 * case here, and it must degrade to silence rather than back to today's date.
 *
 * KNOWN APPROXIMATION, stated rather than hidden: a static page's commit date does not
 * move when a shared component it renders - the header, the footer, Layout - changes.
 * Tracking the full component graph would be the accurate answer and is not worth its
 * complexity; the practical effect is that a chrome-only change is under-reported,
 * which is the safe direction. Over-reporting is the failure this block replaced.
 * ------------------------------------------------------------------------- */

/** ISO 8601 as the sitemaps spec wants it, second precision. `null` stays `null`. */
function w3cDate ( value ) {
  if ( !value ) return null;
  const d = new Date( value );
  if ( Number.isNaN( d.getTime() ) ) return null;
  return d.toISOString().replace( /\.\d{3}Z$/, 'Z' );
}

/** slug -> dateModified, read out of each post page's own JSON-LD. */
function postDates () {
  const dates = new Map();
  const postsDir = path.join( OUT_DIR, 'post' );
  if ( !fs.existsSync( postsDir ) ) return dates;

  for ( const entry of fs.readdirSync( postsDir, { withFileTypes: true } ) )
  {
    if ( !entry.isDirectory() ) continue;
    const file = path.join( postsDir, entry.name, 'index.html' );
    if ( !fs.existsSync( file ) ) continue;
    const html = fs.readFileSync( file, 'utf-8' );
    // dateModified first: a post edited after publication is what a recrawl is for.
    const modified = html.match( /"dateModified"\s*:\s*"([^"]+)"/ );
    const published = html.match( /"datePublished"\s*:\s*"([^"]+)"/ );
    const iso = w3cDate( ( modified && modified[ 1 ] ) || ( published && published[ 1 ] ) );
    if ( iso ) dates.set( entry.name, iso );
  }
  return dates;
}

/** The newest post date on an index page, from the /post/ links it actually shipped. */
function indexPageDate ( route, dates ) {
  const rel = route.replace( /^\/+/, '' );
  const file = rel ? path.join( OUT_DIR, rel, 'index.html' ) : path.join( OUT_DIR, 'index.html' );
  if ( !fs.existsSync( file ) ) return null;

  const html = fs.readFileSync( file, 'utf-8' );
  let newest = null;
  for ( const match of html.matchAll( /\/post\/([^"'/\s]+)\//g ) )
  {
    const iso = dates.get( match[ 1 ] );
    if ( iso && ( newest === null || iso > newest ) ) newest = iso;
  }
  return newest;
}

/** Last commit date of a static page's source file, or null when git cannot say. */
const gitDateCache = new Map();
function gitDate ( route ) {
  if ( gitDateCache.has( route ) ) return gitDateCache.get( route );

  const rel = route === '/' ? 'index' : route.replace( /^\/+/, '' );
  const candidates = [
    path.join( 'src', 'pages', `${rel}.tsx` ),
    path.join( 'src', 'pages', rel, 'index.tsx' ),
  ];
  let iso = null;
  for ( const candidate of candidates )
  {
    if ( !fs.existsSync( path.join( REPO_ROOT, candidate ) ) ) continue;
    try
    {
      const out = execFileSync(
        'git', [ 'log', '-1', '--format=%cI', '--', candidate ],
        { cwd: REPO_ROOT, encoding: 'utf-8', stdio: [ 'ignore', 'pipe', 'ignore' ] }
      ).trim();
      iso = w3cDate( out );
    }
    catch { /* no git, no history, or a shallow clone - fall through to null */ }
    if ( iso ) break;
  }
  gitDateCache.set( route, iso );
  return iso;
}

function lastmodFor ( route, dates ) {
  if ( route.startsWith( '/post/' ) )
  {
    return dates.get( route.slice( '/post/'.length ) ) || null;
  }
  if ( route === '/blog' || route.startsWith( '/blog/' ) )
  {
    return indexPageDate( route, dates );
  }
  return gitDate( route );
}

function generateSitemap ( routes ) {
  const dates = postDates();
  const unique = [ ...new Set( routes ) ].sort();
  const lastmods = new Map( unique.map( route => [ route, lastmodFor( route, dates ) ] ) );

  const entries = unique.map( route => {
    const pathname = route === '/' ? '/' : route + '/';
    const lastmod = lastmods.get( route );
    return `  <url>
    <loc>${SITE_URL}${pathname}</loc>${lastmod ? `
    <lastmod>${lastmod}</lastmod>` : ''}
    <changefreq>${route.startsWith( '/post/' ) ? 'monthly' : 'weekly'}</changefreq>
    <priority>${route === '/' ? '1.0' : route === '/blog' ? '0.8' : '0.7'}</priority>
  </url>`;
  } ).join( '\n' );

  reportLastmod( lastmods );

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries}
</urlset>`;
}

/**
 * Report the lastmod spread, and shout if it collapses back to one value.
 *
 * The defect this file used to have was invisible: the sitemap was well-formed, the
 * build passed, and every URL claimed to have changed today. The only way to see it is
 * to count distinct dates, so that count is printed on every build. A single distinct
 * value across a corpus of this size cannot be true, and is the exact signature of the
 * bug coming back - most plausibly via a clone with no history, where every static page
 * falls to null and every post date is read from the export instead. Warn rather than
 * fail: a legitimately tiny export would trip a hard check, and a sitemap with a weak
 * lastmod is still better than no sitemap.
 */
function reportLastmod ( lastmods ) {
  const values = [ ...lastmods.values() ];
  const dated = values.filter( Boolean );
  const distinctDays = new Set( dated.map( v => v.slice( 0, 10 ) ) );

  console.log(
    `Sitemap lastmod: ${dated.length}/${values.length} URLs dated, `
    + `${distinctDays.size} distinct day(s)`
  );

  const undated = [ ...lastmods.entries() ].filter( ( [ , v ] ) => !v ).map( ( [ r ] ) => r );
  if ( undated.length > 0 )
  {
    console.warn(
      `  ${undated.length} URL(s) carry no lastmod (the element is omitted rather than\n`
      + '  invented). Usually a page whose source file git cannot date:\n'
      + `    ${undated.slice( 0, 12 ).join( ', ' )}`
      + ( undated.length > 12 ? ` +${undated.length - 12} more` : '' )
    );
  }
  if ( dated.length > 20 && distinctDays.size === 1 )
  {
    console.warn(
      `\n  SITEMAP WARNING: all ${dated.length} dated URLs share one lastmod day`
      + ` (${[ ...distinctDays ][ 0 ]}).\n`
      + '  That is the signature of the build-date bug this generator was fixed for.\n'
      + '  Google stops trusting lastmod it can see is fabricated, and it stops trusting\n'
      + '  it for the whole property, not just the URLs that are wrong. Check that the\n'
      + '  post pages still emit JSON-LD dateModified and that git history is available.\n'
    );
  }
}

/**
 * Two consistency checks the allowlist cannot make on its own.
 *
 * 1. AN ALLOWLIST ENTRY THAT DOES NOT EXIST IN THE EXPORT IS DROPPED SILENTLY.
 *    findHtmlFiles only emits routes it actually finds, which is the safe direction —
 *    but it means renaming or deleting a public page leaves a dead entry here and the
 *    sitemap just gets quietly shorter. '[retired public path]' -> '[retired public path]' -> '/anew'
 *    already happened once. Warn, do not fail: a legitimately removed page should not
 *    block a deploy, it should be noticed.
 *
 * 2. A URL CANNOT BE IN THE SITEMAP AND DISALLOWED IN robots.txt AT THE SAME TIME.
 *    That pair tells a crawler to index a page and not to fetch it, and Search Console
 *    reports it as "Indexed, though blocked by robots.txt". The dashboard lives in the
 *    same static export as the marketing pages and is held out of the index by robots
 *    alone, so a single wrong allowlist entry is all it takes to advertise an
 *    authenticated route. This one FAILS the build, because it can only be a mistake.
 */
function robotsDisallows () {
  // Next copies public/robots.txt into the export; prefer the built copy, since that is
  // what will actually be served.
  for ( const candidate of [ path.join( OUT_DIR, 'robots.txt' ),
                             path.join( __dirname, '..', 'public', 'robots.txt' ) ] )
  {
    if ( !fs.existsSync( candidate ) ) continue;
    return fs.readFileSync( candidate, 'utf-8' )
      .split( '\n' )
      .filter( line => /^\s*disallow\s*:/i.test( line ) )
      .map( line => line.split( ':' ).slice( 1 ).join( ':' ).trim() )
      .filter( Boolean );
  }
  return [];
}

const routes = findHtmlFiles( OUT_DIR );
const postRoutes = routes.filter( route => route.startsWith( '/post/' ) );

const missing = [ ...PUBLIC_EXACT ].filter( route => !routes.includes( route ) );
if ( missing.length > 0 )
{
  console.warn(
    `\nSITEMAP WARNING: ${missing.length} allowlisted route(s) were not found in the export:\n`
    + missing.map( route => `    ${route}` ).join( '\n' )
    + '\n  Either the page was removed (delete it from PUBLIC_EXACT) or the build did not\n'
    + '  emit it (which is the serious case, and silent until now).\n'
  );
}

const disallows = robotsDisallows();
const contradicted = routes
  .map( route => ( { route, pathname: route === '/' ? '/' : route + '/' } ) )
  .filter( ( { pathname } ) => disallows.some(
    rule => rule !== '/' && pathname.startsWith( rule )
  ) );
if ( contradicted.length > 0 )
{
  console.error(
    `\nSITEMAP REFUSED: ${contradicted.length} URL(s) are both allowlisted here and`
    + ' Disallowed in robots.txt:\n'
    + contradicted.map( ( { route, pathname } ) => `    ${route}  (blocked by a rule matching ${pathname})` ).join( '\n' )
    + '\n\n  A crawler told to index a page it may not fetch reports it as "Indexed,\n'
    + '  though blocked by robots.txt". Remove the route from PUBLIC_EXACT if it is\n'
    + '  authenticated, or remove the Disallow if it is genuinely public.\n'
  );
  process.exit( 1 );
}

/**
 * REFUSE to write a sitemap with no blog posts in it.
 *
 * Observed on 2026-09-24, twice in a row on this machine: one build emitted 125
 * URLs with 109 post pages, the next emitted 16 with none, from an unchanged
 * tree. The blog is not in the repository - `/post/[slug]` calls
 * listPublicBlogPosts() in getStaticPaths, which fetches
 * wecare.digital/api/seo-tools/blog-public at build time and, on ANY failure,
 * returns [] from a bare catch. So a two-second network blip produces zero blog
 * pages, an empty paths array, a 16-URL sitemap, and `next build` exiting 0.
 * Amplify would then deploy it and 109 live, indexed pages would vanish with no
 * error anywhere - and it would present later as an unexplained ranking drop
 * rather than as a failed build.
 *
 * The endpoint was verified healthy at the time (HTTP 200, 109 posts, ~2s, three
 * consecutive calls), and the live sitemap still had all 125, so nothing bad had
 * shipped. This guard is so that stays true.
 *
 * Checked here rather than by making listPublicBlogPosts() throw, because that
 * function also runs in the browser, where returning [] for an unreachable API is
 * the right behaviour - an empty blog list beats a crashed page. The build wants
 * the opposite. Asserting on the OUTCOME keeps both.
 *
 * Deliberately a floor of 1, not a percentage of some remembered total: the
 * failure mode is all-or-nothing, so 0 is the only value that is always wrong.
 * ALLOW_EMPTY_BLOG=1 exists for a genuinely offline build, and has to be typed on
 * purpose.
 */
if ( postRoutes.length === 0 && process.env.ALLOW_EMPTY_BLOG !== '1' )
{
  console.error(
    '\nSITEMAP REFUSED: 0 blog post pages were exported.\n' +
    `  public routes found: ${routes.length}\n` +
    '  /post/ pages found: 0\n\n' +
    '  getStaticPaths for /post/[slug] fetches the blog list at build time and\n' +
    '  swallows failures, so this is almost certainly a transient fetch error\n' +
    '  rather than an empty blog. Re-run the build. Confirm the API first with:\n' +
    '    curl -s https://wecare.digital/api/seo-tools/blog-public | head -c 200\n\n' +
    '  Writing this sitemap would drop every published post from the index.\n' +
    '  If the blog really is empty, set ALLOW_EMPTY_BLOG=1 deliberately.\n'
  );
  process.exit( 1 );
}

const sitemapXml = generateSitemap( routes );
fs.writeFileSync( OUTPUT_FILE, sitemapXml, 'utf-8' );
console.log(
  `Public sitemap: ${routes.length} URLs `
  + `(${postRoutes.length} blog posts) -> ${OUTPUT_FILE}`
);
