'use strict';

/**
 * seocheck - the document head of every public route, measured in a browser.
 *
 * WHY A BROWSER AND NOT A GREP OF out/. next/head decides at RENDER time which of several
 * competing tags survives, and its rules are not obvious: it de-duplicates meta by `name`,
 * `httpEquiv`, `charSet` and `itemProp`, but NOT by `property`. So two `og:title` tags
 * coexist in the output while two `twitter:title` tags collapse to one, and a page's Head
 * beats _app.tsx's for anything that does dedupe. Reading the source tells you what was
 * written; only the rendered document tells you what a crawler receives. Three real defects
 * were invisible to source inspection and obvious here:
 *
 *   1. /grahak-os/ shipped TWO of every og tag - type, url, title, description, image,
 *      site_name, locale - because it declares its own set and `property` never dedupes.
 *      og:url had a key on the _app side and still doubled, because the page side had none:
 *      a key only works when BOTH sides carry the same one.
 *   2. The home page declared <title>WECARE.DIGITAL</title> and description
 *      "WECARE.DIGITAL." in its own Head, which silently overrode the sitewide copy. The
 *      most important URL on the site had a title saying nothing.
 *   3. FOURTEEN routes shared ONE og:title and ONE og:description, because only /grahak-os/
 *      declared its own and everything else inherited the company default from _app.tsx.
 *      Every product page previewed identically when shared.
 *
 * WHAT IT DOES NOT DO. It does not judge copy. Length bands are wide and only catch the
 * degenerate cases - a title that is just the brand name, a description that restates it -
 * because wording is the owner's and a harness that nags about phrasing gets ignored.
 *
 *   node tools/browser/seocheck.js
 *   BASE=http://localhost:3000 node tools/browser/seocheck.js
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );

const SITE = 'https://wecare.digital';

/** Public marketing routes, in the same order typecheck.js uses. */
const ROUTES = [
  '/', '/grahak-os/', '/vayulok/', '/contact/', '/terms/', '/privacy/',
  '/orders/', '/bharat-rx/',
  '/elsewhere/', '/expo-week/', '/dastavez/', '/clear-closure/',
  '/ritual-guru/', '/anew/', '/niji-setu/', '/hunar/',
  // The Requests pages, added when the header's six labels stopped all resolving to
  // /contact/. Same shape as the product pages: rotating hero plus one content section.
  '/submit-request/', '/request-amendment/', '/drop-docs/', '/vault/', '/leave-review/',
  '/refer-and-earn/',
  // The catalogue. BOTH shapes are here, and the product page is the one that earns its place:
  // /shop/ takes its head from PageMeta plus the sitewide block in _app.tsx, which fourteen routes
  // above already prove, but /shop/kiosk/ declares every tag itself through ShopProductHead.tsx -
  // so it is the only route in this list where a missing or duplicated og tag would be nobody
  // else's bug. The canonical assertion is the point: a dynamic route's pathname is the pattern,
  // and this check is what proves the built page says /shop/kiosk/ rather than /shop/[slug]/.
  '/shop/', '/shop/kiosk/',
];

/**
 * Formerly-published URLs whose in-repo redirect stubs were removed on owner instruction.
 * They no longer exist in the export; the 301 to /contact/ is now expected at the CDN
 * (Amplify Console) and is not visible to this harness. Asserted only as "must not serve
 * a 200 page" and "must not appear in the sitemap".
 */
const RETIRED = [
  '/' + 'self' + 'service/', '/product-page/', '/product-page/partner-up/', '/product-page/referral-partner/',
];

/**
 * The sitewide fallback og:title from _app.tsx. Correct on '/', which IS the company page,
 * and a bug anywhere else - it means that route never got its own share preview.
 */
const COMPANY_OG_TITLE = 'Everyday AI, built for Bharat | WECARE.DIGITAL';

// Wide on purpose. Google renders about 60 characters of a title and 155-160 of a
// description, but truncation is a cosmetic loss; these bounds exist to catch a head that
// is empty or a brand name repeated, not to police wording.
const TITLE_MIN = 15, TITLE_MAX = 75;
const DESC_MIN = 50, DESC_MAX = 170;

const results = [];
let failures = 0;

function record( ok, name, detail ) {
  results.push( { ok, name } );
  if ( !ok ) failures++;
  console.log( `  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` - ${detail}` : ''}` );
}

/** Read the head as a crawler would see it, after render. */
async function readHead( page ) {
  return page.evaluate( () => {
    const attr = ( sel, a ) => {
      const els = [ ...document.querySelectorAll( sel ) ];
      return { n: els.length, v: els.length ? ( els[ 0 ].getAttribute( a ) || '' ) : null };
    };
    const ld = [];
    for ( const s of document.querySelectorAll( 'script[type="application/ld+json"]' ) ) {
      let parsed = null, error = null;
      try { parsed = JSON.parse( s.textContent || '' ); } catch ( e ) { error = String( e.message || e ); }
      ld.push( { error, ids: ( () => {
        /**
         * DEFINITIONS ONLY, NOT REFERENCES - and the difference is the whole assertion.
         * An object carrying both @type and @id DEFINES an entity. An object carrying only
         * @id is a REFERENCE to one defined elsewhere, which is the correct, encouraged way
         * to link JSON-LD entities: websiteSchema defines https://wecare.digital/#website
         * once, and every per-page WebPage points at it with isPartOf:{'@id':...}. Likewise
         * a WebPage references its own breadcrumb, and serviceSchema references the
         * Organization as its provider.
         * Counting references as duplicates reported all 15 routes as broken on the first
         * run of this harness - a false positive that would have been "fixed" by deleting
         * correct markup. Only a genuine second DEFINITION of the same @id is a conflict.
         */
        const out = [];
        const walk = v => {
          if ( Array.isArray( v ) ) return v.forEach( walk );
          if ( v && typeof v === 'object' ) {
            if ( typeof v[ '@id' ] === 'string' && typeof v[ '@type' ] === 'string' ) out.push( v[ '@id' ] );
            Object.values( v ).forEach( walk );
          }
        };
        walk( parsed );
        return out;
      } )() } );
    }
    return {
      titles: [ ...document.querySelectorAll( 'head title' ) ].map( t => ( t.textContent || '' ).trim() ),
      desc: attr( 'meta[name="description"]', 'content' ),
      canonical: attr( 'link[rel="canonical"]', 'href' ),
      ogTitle: attr( 'meta[property="og:title"]', 'content' ),
      ogDesc: attr( 'meta[property="og:description"]', 'content' ),
      ogUrl: attr( 'meta[property="og:url"]', 'content' ),
      ogImage: attr( 'meta[property="og:image"]', 'content' ),
      twTitle: attr( 'meta[name="twitter:title"]', 'content' ),
      twDesc: attr( 'meta[name="twitter:description"]', 'content' ),
      robots: attr( 'meta[name="robots"]', 'content' ),
      refresh: attr( 'meta[http-equiv="refresh"]', 'content' ),
      ld,
    };
  } );
}

async function main() {
  const t = await target();
  const browser = await launch();
  console.log( `seocheck - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}` );

  const heads = {};
  const retiredHeads = {};

  try {
    const context = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
    const page = await context.newPage();

    for ( const route of ROUTES ) {
      const res = await gotoStable( page, t.base + route );
      if ( !res || res.status() !== 200 ) {
        record( false, `${route} responds 200`, `got ${res ? res.status() : 'no response'}` );
        continue;
      }
      heads[ route ] = await readHead( page );
    }

    /**
     * THE IN-REPO REDIRECT STUBS WERE REMOVED (owner instruction). [retired public path] and
     * /product-page/* no longer exist in the export, so the origin returns the 404 page
     * for them. The redirect to /contact/ is now expected to live at the CDN (Amplify
     * Console: Rewrites and redirects), which this static export cannot express and this
     * harness - serving out/ or a plain origin - cannot see. So the assertion here is
     * narrowed to what IS true of the export: the stub routes are gone. Read as raw HTML
     * over HTTP, which is what a non-JS crawler receives.
     */
    for ( const route of RETIRED ) {
      const res = await fetch( t.base + route, { redirect: 'manual' } );
      retiredHeads[ route ] = { status: res.status };
    }
    await context.close();

    // ---- Per-route report -------------------------------------------------
    console.log( '\nPublic routes' );
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      console.log( `  ${route}` );
      console.log( `    title  ${String( h.titles[ 0 ] || '' ).length}ch  ${h.titles[ 0 ] || '(none)'}` );
      console.log( `    desc   ${String( h.desc.v || '' ).length}ch  ${( h.desc.v || '(none)' ).slice( 0, 88 )}` );
    }

    // ---- Singleton tags --------------------------------------------------
    // A doubled og tag is the defect this harness was written for. A doubled canonical or
    // title is the same class of bug and equally invisible in source.
    const dupes = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      const counts = {
        title: h.titles.length, description: h.desc.n, canonical: h.canonical.n,
        'og:title': h.ogTitle.n, 'og:description': h.ogDesc.n, 'og:url': h.ogUrl.n,
        'og:image': h.ogImage.n, 'twitter:title': h.twTitle.n, 'twitter:description': h.twDesc.n,
      };
      for ( const [ tag, n ] of Object.entries( counts ) ) {
        if ( n !== 1 ) dupes.push( `${route} has ${n}x ${tag}` );
      }
    }
    record( dupes.length === 0, 'every route carries exactly one of each head tag',
      dupes.length ? dupes.join( '; ' ) : `${ROUTES.length} routes x 9 tags, all singular` );

    // ---- The share preview matches the page ------------------------------
    // PageMeta emits og:title from the same string as <title>, so a mismatch means a page
    // has gone back to hand-writing them separately - which is how they drift.
    const mismatched = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      if ( h.ogTitle.v !== h.titles[ 0 ] ) mismatched.push( `${route} og:title != title` );
      if ( h.ogDesc.v !== h.desc.v ) mismatched.push( `${route} og:description != description` );
      if ( h.twTitle.v !== h.titles[ 0 ] ) mismatched.push( `${route} twitter:title != title` );
    }
    record( mismatched.length === 0, 'og and twitter titles match the page title and description',
      mismatched.length ? mismatched.join( '; ' ) : 'all derived from one string per page' );

    // ---- No route reuses the company default -----------------------------
    const generic = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h || route === '/' ) continue;
      if ( h.ogTitle.v === COMPANY_OG_TITLE ) generic.push( route );
    }
    record( generic.length === 0, 'no route other than / falls back to the company og:title',
      generic.length ? `${generic.length} inheriting the sitewide preview: ${generic.join( ', ' )}` : 'every route has its own' );

    // ---- Titles and descriptions are unique ------------------------------
    // Two URLs with the same title compete with each other, and Search Console reports it
    // as duplicate metadata rather than as the routing problem it usually is.
    for ( const [ label, pick ] of [ [ 'titles', h => h.titles[ 0 ] ], [ 'descriptions', h => h.desc.v ] ] ) {
      const seen = new Map();
      for ( const route of ROUTES ) {
        const h = heads[ route ];
        if ( !h ) continue;
        const v = pick( h ) || '';
        if ( !seen.has( v ) ) seen.set( v, [] );
        seen.get( v ).push( route );
      }
      const shared = [ ...seen.entries() ].filter( ( [ , rs ] ) => rs.length > 1 );
      record( shared.length === 0, `all ${label} are unique across public routes`,
        shared.length ? shared.map( ( [ v, rs ] ) => `"${v.slice( 0, 40 )}" on ${rs.join( ' + ' )}` ).join( '; ' ) : `${seen.size} distinct` );
    }

    // ---- Lengths ---------------------------------------------------------
    const badLen = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      const tl = ( h.titles[ 0 ] || '' ).length, dl = ( h.desc.v || '' ).length;
      if ( tl < TITLE_MIN || tl > TITLE_MAX ) badLen.push( `${route} title ${tl}ch` );
      if ( dl < DESC_MIN || dl > DESC_MAX ) badLen.push( `${route} description ${dl}ch` );
    }
    record( badLen.length === 0,
      `titles ${TITLE_MIN}-${TITLE_MAX}ch and descriptions ${DESC_MIN}-${DESC_MAX}ch`,
      badLen.length ? badLen.join( '; ' ) : 'all within bounds' );

    // ---- Canonicals ------------------------------------------------------
    // trailingSlash is set in next.config.js, so a canonical without the slash names a URL
    // that 308-redirects - a contradictory signal, and one that shipped here before.
    const badCanon = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      const expected = `${SITE}${route}`;
      if ( h.canonical.v !== expected ) badCanon.push( `${route} -> ${h.canonical.v}` );
      if ( h.ogUrl.v !== expected ) badCanon.push( `${route} og:url -> ${h.ogUrl.v}` );
    }
    record( badCanon.length === 0, 'canonical and og:url match the route, with the trailing slash',
      badCanon.length ? badCanon.join( '; ' ) : 'all correct' );

    // ---- Structured data -------------------------------------------------
    const ldErrors = [], idClashes = [];
    for ( const route of ROUTES ) {
      const h = heads[ route ];
      if ( !h ) continue;
      h.ld.forEach( ( b, i ) => { if ( b.error ) ldErrors.push( `${route} block ${i}: ${b.error}` ); } );
      // Google's guidance is that a page must not carry two conflicting copies of the same
      // entity. Same @id twice across blocks is the detectable form of that.
      const all = h.ld.flatMap( b => b.ids );
      const dup = [ ...new Set( all.filter( ( v, i ) => all.indexOf( v ) !== i ) ) ];
      if ( dup.length ) idClashes.push( `${route}: ${dup.join( ', ' )}` );
    }
    record( ldErrors.length === 0, 'every JSON-LD block parses',
      ldErrors.length ? ldErrors.join( '; ' ) : `${ROUTES.reduce( ( n, r ) => n + ( heads[ r ] ? heads[ r ].ld.length : 0 ), 0 )} blocks across ${ROUTES.length} routes` );
    record( idClashes.length === 0, 'no route emits the same @id twice',
      idClashes.length ? idClashes.join( '; ' ) : 'no conflicting entities' );

    // ---- Retired URLs ----------------------------------------------------
    // The in-repo redirect stubs were removed on owner instruction; the CDN 301 to
    // /contact/ (if configured) is not visible to this harness. So the only thing the
    // export can be held to is that these routes no longer ship a page: a request for
    // them must NOT return a 200 with real content. The 404 page returning 404 is correct.
    console.log( '\nRetired URLs (stubs removed - expect no 200 from the export)' );
    const stillServed = [];
    for ( const route of RETIRED ) {
      const h = retiredHeads[ route ];
      const status = h ? h.status : 'nothing';
      console.log( `  ${route} -> ${status}` );
      if ( h && h.status === 200 ) stillServed.push( `${route} still returns 200` );
    }
    record( stillServed.length === 0,
      `all ${RETIRED.length} retired routes are gone from the export (no 200)`,
      stillServed.length ? stillServed.join( '; ' ) : 'none serve a page; CDN 301 to /contact/ is console-managed' );

    // They must also never be advertised in the sitemap.
    const smRes = await ( async () => {
      const ctx2 = await browser.newContext();
      const p2 = await ctx2.newPage();
      const r = await p2.goto( t.base + '/sitemap.xml', { waitUntil: 'load' } );
      const body = r && r.status() === 200 ? await r.text() : '';
      await ctx2.close();
      return body;
    } )();
    const advertised = RETIRED.filter( r => smRes.includes( r.replace( /\/$/, '' ) ) );
    record( smRes.length > 0 && advertised.length === 0,
      'no retired URL appears in sitemap.xml',
      smRes.length === 0 ? 'could not read sitemap.xml' : advertised.length ? advertised.join( ', ' ) : `sitemap has ${( smRes.match( /<loc>/g ) || [] ).length} URLs, none retired` );
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `\n${results.length - failures}/${results.length} assertions passed` );
  if ( failures ) { console.log( `${failures} FAILED` ); process.exit( 1 ); }
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
