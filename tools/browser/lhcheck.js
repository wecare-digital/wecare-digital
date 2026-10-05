'use strict';

/**
 * Lighthouse over the public routes — the lab half of PageSpeed Insights, run locally.
 *
 * WHY THIS EXISTS. Everything else in this directory asserts something we already decided:
 * a rung, a rect, a contrast ratio on a control we knew about. Lighthouse runs axe-core over
 * the whole document, which is a different question — it finds the text nobody thought to
 * measure. On its first run it found four real contrast failures that five green suites and a
 * hand-written focus-ring sweep had all missed:
 *
 *   .msg-time          #667781 on #d1f470   3.74:1   the mockup's timestamp
 *   .bc [aria-current] rgba(26,58,42,.58)   3.53:1   the breadcrumb you are on
 *   .lgd-toc-num       rgba(0,0,0,.42)      3.04:1   clause numbers, x4 on /terms/
 *   .lgd-num           rgba(0,0,0,.42)      3.04:1
 *
 * None of those is an indicator or a named label, which is exactly why the focus-ring sweep
 * walked past them.
 *
 * WHY IT IS NOT PAGESPEED INSIGHTS ITSELF. The PSI API needs the URL to be publicly
 * crawlable and it is quota-limited per project; from this sandbox it returns
 * `429 Quota exceeded for quota metric 'Queries'`. PSI's lab data *is* Lighthouse, so running
 * Lighthouse against `out/` gets the same audits with none of the quota. What it cannot get is
 * the field half: CrUX real-user FCP/LCP/CLS/INP needs production traffic and is unavailable
 * locally at any quota. For that, open https://pagespeed.web.dev/ against the live origin.
 *
 * READ THE SCORES WITH THE RIGHT SCEPTICISM.
 *
 *   - **accessibility, seo, best-practices are trustworthy here.** They are static and
 *     document-shaped; a local origin does not change them.
 *   - **performance is NOT.** The export is served from localhost while fonts.googleapis.com,
 *     the media CDN, GTM and connect.facebook.net are fetched over whatever link the runner
 *     has. Measured from this sandbox, that put FCP at 4.7s and LCP at ~11s, which says more
 *     about the runner's egress than about the site. The performance *opportunities*
 *     (unused-css-rules, unused-javascript, render-blocking) are still worth reading; the
 *     millisecond totals attached to them are not.
 *   - **best-practices sits at 96 for a local-only reason.** `errors-in-console` fires because
 *     SupportWidget fetches /api/site-language/languages, which is same-origin in production
 *     and cross-origin from 127.0.0.1, so Chrome logs a CORS failure. Not a defect.
 *
 * Two findings are deliberately left red, both documented at their rule:
 *
 *   - `/blog/` scores 96 on `.pager-step.is-off` at 2.24:1. WCAG 1.4.3 exempts text in an
 *     INACTIVE component, and the markup is aria-hidden, so raising it would make
 *     "unavailable" look available. axe cannot tell the difference.
 *
 * Lighthouse lives in this directory's package.json rather than the app's, for the same reason
 * playwright-core does: the app's dependency tree and lockfile stay untouched, and the browser
 * is resolved through lib/browser.js rather than downloaded.
 *
 *   node tools/browser/lhcheck.js              # accessibility + seo + best-practices
 *   LH_PERF=1 node tools/browser/lhcheck.js    # add performance, with the caveat above
 */

const { target } = require( './lib/serve' );
const { resolveChrome } = require( './lib/browser' );

/** Public routes plus one blog post, which is a different template from the index. */
const ALL_ROUTES = [
  '/', '/grahak-os/', '/vayulok/', '/contact/', '/get/', '/orders/', '/bharat-rx/',
  '/anew/', '/dastavez/', '/elsewhere/', '/expo-week/', '/niji-setu/', '/ritual-guru/',
  '/clear-closure/', '/terms/', '/privacy/', '/blog/',
  // The two routes added on 2026-09-30. Every other ProductPage route scores 100 on the four
  // categories, so these are here to prove the two new ones do too rather than to sample a
  // shape already covered - a new page is exactly where a regression would hide.
  '/hunar/', '/vault/',
  // '/llm/' was here until 2026-09-30. The page is retired and the URL now 301s to
  // /llms.txt, which is a text file with no DOM to audit.
  // The catalogue. '/shop/' - the grid - was removed on 2026-10-04 when the owner withdrew the
  // index: it 301s to the home page, and Lighthouse auditing a redirect measures the home page a
  // second time rather than the catalogue.
  //
  // ONE product page stands for the seven, which are the same component with different strings.
  // /shop/kiosk/ is the sample because it has the most description paragraphs of the seven, so it
  // is the longest document the template produces.
  '/shop/kiosk/',
  '/post/a-break-is-still-part-of-life/', '/404.html',
];

/**
 * Audits that are red for a reason recorded in the code, so the run stays honest without
 * being noisy. Each entry must say why, and "it is inconvenient" is not a why.
 */
const EXPECTED = {
  'errors-in-console':
    'SupportWidget fetches /api/site-language/languages, which is same-origin in production '
    + 'and cross-origin from 127.0.0.1. A local-harness artefact, not a page defect.',
  'bf-cache':
    'Back/forward cache is blocked by the third-party tags the site loads; not something this '
    + 'export controls.',
};

/** axe flags these, and the markup is correct. Keep the reason with the id. */
const JUSTIFIED_CONTRAST = {
  '/blog/':
    '.pager-step.is-off is the disabled end of the pager at 2.24:1. WCAG 1.4.3 exempts text in '
    + 'an inactive component and the span is aria-hidden; raising it would make "unavailable" '
    + 'look available.',
};

/**
 * The four metrics worth printing when LH_PERF is on, with the units Lighthouse reports them
 * in. CLS is the one that is NOT egress-dependent — it is layout, measured in the same
 * viewport whatever the link speed — so it is the one number from this category that a local
 * run can be held to. The rest are printed to show movement, not to be believed absolutely.
 */
const METRICS = [
  [ 'first-contentful-paint', 'FCP' ],
  [ 'largest-contentful-paint', 'LCP' ],
  [ 'total-blocking-time', 'TBT' ],
  [ 'cumulative-layout-shift', 'CLS' ],
];

/**
 * Performance audits are listed, never counted.
 *
 * WHY. The header of this file already says the millisecond totals measure the runner's
 * egress rather than the site: `out/` is served from 127.0.0.1 while fonts.googleapis.com,
 * the media CDN, GTM and connect.facebook.net come over whatever link the sandbox has. So a
 * timing audit failing locally is not evidence of a defect, and `LH_PERF=1` counting them as
 * unexplained made the flag unusable as a gate — it could only ever exit 1.
 *
 * It is still worth READING: `unused-javascript`, `unused-css-rules`,
 * `unminified-javascript` and `legacy-javascript` report BYTES, which localhost does not
 * distort at all. Those are the audits Phase 6 acted on.
 */
const isPerfAudit = ( lhr, id ) =>
  ( lhr.categories.performance?.auditRefs || [] ).some( r => r.id === id );

async function main () {
  const t = await target();
  const lighthouse = ( await import( 'lighthouse/core/index.js' ) ).default;
  const chromeLauncher = await import( 'chrome-launcher/dist/index.js' );

  const chrome = await chromeLauncher.launch( {
    chromePath: resolveChrome(),
    chromeFlags: [ '--headless=new', '--no-sandbox', '--disable-gpu' ],
  } );

  const categories = [ 'accessibility', 'seo', 'best-practices' ];
  if ( process.env.LH_PERF ) categories.push( 'performance' );

  // A full pass is 22 routes x ~30s and performance work is iterative: measure, change one
  // thing, re-measure. LH_ROUTES narrows the sweep to a comma-separated subset so a single
  // page can be re-run in half a minute. It does NOT replace the full pass — the gate is the
  // whole list — it just makes the loop in between usable.
  const ROUTES = process.env.LH_ROUTES
    ? process.env.LH_ROUTES.split( ',' ).map( s => s.trim() ).filter( Boolean )
    : ALL_ROUTES;

  console.log( `lhcheck - Lighthouse over ${ROUTES.length} routes on ${t.base}` );
  console.log( `  categories: ${categories.join( ', ' )}` );
  if ( !process.env.LH_PERF ) console.log( '  performance omitted - set LH_PERF=1, and read the caveat at the top of this file' );
  console.log( '' );

  let unexplained = 0;

  for ( const route of ROUTES ) {
    let lhr;
    try {
      const res = await lighthouse( t.base + route, {
        port: chrome.port, output: 'json', logLevel: 'error',
        onlyCategories: categories, formFactor: 'mobile',
        screenEmulation: { mobile: true, width: 412, height: 823, deviceScaleFactor: 1.75, disabled: false },
      } );
      lhr = res.lhr;
    } catch ( err ) {
      console.log( `  ERROR  ${route} - ${err.message.slice( 0, 80 )}` );
      unexplained += 1;
      continue;
    }

    const score = k => {
      const c = lhr.categories[ k ];
      return c && c.score !== null ? String( Math.round( c.score * 100 ) ).padStart( 3 ) : ' na';
    };
    const failed = Object.values( lhr.audits ).filter( a =>
      a.score !== null && a.score < 1
      && ![ 'notApplicable', 'informative' ].includes( a.scoreDisplayMode ) );

    const surprising = failed.filter( a => {
      if ( EXPECTED[ a.id ] ) return false;
      if ( a.id === 'color-contrast' && JUSTIFIED_CONTRAST[ route ] ) return false;
      if ( process.env.LH_PERF && isPerfAudit( lhr, a.id ) ) return false;
      return true;
    } );

    console.log(
      `  a11y=${score( 'accessibility' )} seo=${score( 'seo' )} bp=${score( 'best-practices' )}`
      + ( process.env.LH_PERF ? ` perf=${score( 'performance' )}` : '' )
      + `  ${route.padEnd( 40 )} ${surprising.length ? surprising.map( a => a.id ).join( ', ' ) : 'clean'}`
    );

    for ( const a of surprising ) {
      unexplained += 1;
      // details.items is an array for the table/opportunity audits and ABSENT or a plain
      // object for the newer "insight" audits (checklist, treemap-data). Iterating it blind
      // threw `object is not iterable` and aborted the whole LH_PERF run on route one.
      const items = a.details && a.details.items;
      for ( const item of Array.isArray( items ) ? items : [] ) {
        const why = ( item.node && item.node.explanation ) || item.description;
        if ( why ) console.log( `        ${String( why ).replace( /\s+/g, ' ' ).slice( 0, 140 )}` );
      }
    }

    if ( process.env.LH_PERF ) {
      const m = METRICS
        .map( ( [ id, label ] ) => `${label}=${( lhr.audits[ id ] || {} ).displayValue || 'na'}` )
        .join( '  ' );
      console.log( `        ${m}` );

      // Byte-denominated opportunities only. These are the ones localhost cannot distort,
      // so they are the actionable half of the performance category.
      const bytes = [ 'unused-javascript', 'unused-css-rules', 'unminified-javascript',
        'unminified-css', 'legacy-javascript', 'modern-image-formats', 'uses-text-compression' ];
      for ( const id of bytes ) {
        const a = lhr.audits[ id ];
        const kb = a && a.details && a.details.overallSavingsBytes;
        if ( kb ) console.log( `        ${id.padEnd( 24 )} ${Math.round( kb / 1024 )} kB wasted` );
      }
    }
  }

  console.log( '\n  red for a recorded reason, not counted:' );
  if ( process.env.LH_PERF ) {
    console.log( '    every performance audit - localhost egress, not the site. Read the bytes, '
      + 'not the milliseconds; see the note at isPerfAudit.' );
  }
  for ( const [ id, why ] of Object.entries( EXPECTED ) ) console.log( `    ${id} - ${why}` );
  for ( const [ route, why ] of Object.entries( JUSTIFIED_CONTRAST ) ) console.log( `    color-contrast on ${route} - ${why}` );

  console.log( unexplained
    ? `\n${unexplained} unexplained finding(s) - each is either a real defect or needs a recorded reason above.`
    : '\nNo unexplained findings.' );

  await chrome.kill();
  await t.close();
  process.exitCode = unexplained ? 1 : 0;
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
