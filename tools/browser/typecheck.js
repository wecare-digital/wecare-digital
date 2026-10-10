'use strict';

/**
 * typecheck - the heading ladder across every public page.
 *
 * WHAT IT IS FOR. `.kiro/steering/grahak-os-design.md` fixes one section-h2 rung for the
 * whole site: clamp(28px,3.2vw,40px) / 700 / lh 1.08 / ls -1.2px. Nothing enforces it,
 * and each public page declares its own h2 rule inside its own <style jsx>, so they drift
 * independently and silently. A unit test cannot catch it either, because the value only
 * exists once a browser has resolved the clamp against a viewport.
 *
 * WHY IT REPORTS EVERY HEADING RATHER THAN JUST FAILING. Two different faults produce
 * "the h2 is the wrong size", and they need opposite fixes:
 *   - a SECTION heading on a non-contract clamp, which is real drift; and
 *   - an element that is an <h2> in the markup but is not a section heading at all - a
 *     card title, an eyebrow, a widget label. Those are correctly small, and "fixing"
 *     them to 53.76px would be a serious visual regression.
 * So every heading is printed with its class and its text, and the assertions are scoped
 * to the ones that are genuinely section headings.
 *
 * Measured at 1280px by default because that is where the contract's clamp is pinned to its
 * ceiling: 3.2vw of 1280 is 40.96px, so the clamp reports a flat 40px. A second width is
 * sampled (900px, where it resolves to 28.8px) to show
 * whether a page is on a different clamp or merely at a different point on the same one -
 * two pages can disagree at one width and agree at another, and only the formula matters.
 *
 *   node tools/browser/typecheck.js
 *   BASE=http://localhost:3000 node tools/browser/typecheck.js
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );

/**
 * Every public route, from PUBLIC_PAGE_META in _app.tsx plus '/'. Kept in this order so
 * the four pages with hand-written heroes come first and the seven shared ProductPage
 * routes group together - if those seven ever disagree with each other, the shared
 * component is not as shared as it looks.
 */
const ROUTES = [
  '/', '/grahak-os/', '/vayulok/', '/contact/', '/terms/', '/privacy/',
  '/orders/', '/bharat-rx/',
  '/elsewhere/', '/expo-week/', '/dastavez/', '/clear-closure/',
  '/ritual-guru/', '/anew/', '/niji-setu/', '/hunar/', '/vault/',
  // '/shop/' AND '/shop/<slug>/' ARE DELIBERATELY ABSENT, for the same reason '/blog/' is.
  //
  // This harness pins the SECTION-h2 rung at 40px/700 - the contract for a page shaped as one
  // hero plus one content section, which is what every route above is. /shop/ is a card grid: its
  // h2s are the seven card titles at the 22px/700 CARD rung, because the hero owns the h1 and
  // there is no section heading between them, so h2 is the next rung with nothing skipped. Listing
  // it here would report seven correct headings as off-ladder.
  //
  // That is not the same as leaving the pages unmeasured. seocheck, sectioncheck, devicecheck,
  // lhcheck and pageaudit all carry them, and pageaudit's sweep discovers all eight.
];

const WIDTHS = [ 1280, 900 ];

/**
 * The contract's section-h2 rung, resolved per width.
 *
 * THIS WAS clamp(32px,4.2vw,54px) AND THAT VALUE EXISTED NOWHERE ON THE SITE. It resolved
 * to 53.76px at 1280px, matched four headings on /grahak-os/ and nothing else, and made
 * this harness report 86 headings as "off-ladder" while every one of them agreed with
 * every other. The steering contract has since been reconciled onto the rung the site
 * actually ships - see .kiro/steering/grahak-os-design.md, which now records why 40px won:
 * the hero h1 is clamp(36px,4.3vw,60px), so at 1280px it resolves to 55.04px and a 53.76px
 * h2 sat 1.28px below it. With the h2 also being the heavier weight, the hierarchy
 * inverted and the h2 read as the larger of the two.
 * Keep this in step with the steering file. If they disagree, one of them is lying and
 * this harness is the only one of the pair that gets measured.
 */
const CONTRACT = {
  clamp: 'clamp(28px,3.2vw,40px)',
  weight: '700',
  at: w => Math.min( 40, Math.max( 28, w * 0.032 ) ),
};

const results = [];
let failures = 0;

function record( ok, name, detail ) {
  results.push( { ok, name } );
  if ( !ok ) failures++;
  console.log( `  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` - ${detail}` : ''}` );
}

async function readHeadings( page ) {
  return page.evaluate( () => {
    const out = [];
    for ( const el of document.querySelectorAll( 'h1,h2,h3' ) ) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle( el );
      // Skip anything not rendered - a visually-hidden heading has no bearing on the
      // visible ladder and would pad the report with noise.
      if ( r.width === 0 && r.height === 0 ) continue;
      if ( cs.display === 'none' || cs.visibility === 'hidden' ) continue;
      out.push( {
        tag: el.tagName.toLowerCase(),
        // styled-jsx adds a jsx-<hash> class to every element; it changes whenever the
        // stylesheet changes, so it is stripped to keep this output diffable.
        cls: ( typeof el.className === 'string' ? el.className : '' )
          .split( /\s+/ ).filter( c => c && !/^jsx-/.test( c ) ).join( '.' ),
        text: ( el.textContent || '' ).trim().replace( /\s+/g, ' ' ).slice( 0, 44 ),
        size: Math.round( parseFloat( cs.fontSize ) * 100 ) / 100,
        weight: cs.fontWeight,
        lh: cs.lineHeight,
        ls: cs.letterSpacing,
      } );
    }
    return out;
  } );
}

async function main() {
  const t = await target();
  const browser = await launch();
  console.log( `typecheck - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}` );

  // route -> width -> headings
  const all = {};

  try {
    for ( const width of WIDTHS ) {
      const context = await browser.newContext( { viewport: { width, height: 900 } } );
      const page = await context.newPage();
      for ( const route of ROUTES ) {
        // gotoStable, not waitUntil:'networkidle' - see lib/browser.js. networkidle timed
        // this suite out in CI at 30 navigations while the shorter suites passed.
        const res = await gotoStable( page, t.base + route );
        if ( !res || res.status() !== 200 ) {
          record( false, `${route} responds 200 @${width}`, `got ${res ? res.status() : 'no response'}` );
          continue;
        }
        all[ route ] = all[ route ] || {};
        all[ route ][ width ] = await readHeadings( page );
      }
      await context.close();
    }

    // ---- Report -------------------------------------------------------------
    for ( const width of WIDTHS ) {
      const expected = Math.round( CONTRACT.at( width ) * 100 ) / 100;
      console.log( `\n@${width}px  (contract section h2 = ${expected}px / 700)` );
      for ( const route of ROUTES ) {
        const hs = ( all[ route ] || {} )[ width ];
        if ( !hs ) continue;
        const h2s = hs.filter( h => h.tag === 'h2' );
        if ( !h2s.length ) { console.log( `  ${route.padEnd( 16 )} (no visible h2)` ); continue; }
        const summary = h2s.map( h => `${h.size}/${h.weight}${h.cls ? ` .${h.cls}` : ''}` ).join( '  |  ' );
        console.log( `  ${route.padEnd( 16 )} ${summary}` );
      }
    }

    // ---- Distinct h2 sizes, and who owns them -------------------------------
    console.log( '\nDistinct visible h2 sizes @1280, with owners' );
    const bySize = new Map();
    for ( const route of ROUTES ) {
      for ( const h of ( ( all[ route ] || {} )[ 1280 ] || [] ).filter( h => h.tag === 'h2' ) ) {
        const key = `${h.size}/${h.weight}`;
        if ( !bySize.has( key ) ) bySize.set( key, [] );
        bySize.get( key ).push( `${route}${h.cls ? ` .${h.cls}` : ''} "${h.text}"` );
      }
    }
    for ( const [ key, owners ] of [ ...bySize.entries() ].sort( ( a, b ) => parseFloat( b[ 0 ] ) - parseFloat( a[ 0 ] ) ) ) {
      console.log( `  ${key.padEnd( 12 )} x${String( owners.length ).padStart( 2 )}  ${owners[ 0 ]}` );
      for ( const o of owners.slice( 1 ) ) console.log( `  ${' '.repeat( 12 )}      ${o}` );
    }

    /**
     * SECTION HEADINGS ONLY. An <h2> that belongs to a card, a widget or an overlay is
     * not on this rung and must not be dragged onto it. The distinction is by class,
     * because that is what the design contract itself is written in terms of.
     */
    /**
     * `-toc-` is in here for a specific reason worth stating. .lgd-toc-title is the
     * "Contents" label above the table of contents on /terms/ and /privacy/, and it
     * measures 14px/600 uppercase with .04em tracking - which is the site's EYEBROW
     * pattern, not a heading. It is an <h2> in the markup only because it labels the ToC
     * region. Counting it as a section heading is what produced the puzzling "14" in the
     * set of reported h2 sizes; scaling it to 40px or 53.76px would be a bad regression.
     * If anything it should be a <p>, or move onto the documented 12px/700/.08em eyebrow
     * rung - a small semantic tidy, not a type-scale question.
     */
    const NON_SECTION = /(-card|-chip|card-|widget|wa-|fa-|sr-only|visually|cl-card|-toc-|^pbp-h$)/;

    // `.pbp-h` labels ProductBlogPanel's compact right-hand blog reader on /anew/.
    // It belongs to an <aside> widget, not the page's section-h2 ladder; keeping its compact
    // 28px treatment avoids turning a utility panel heading into a second page-section heading.

    /**
     * DOCUMENTED EXCEPTIONS: headings that ARE section headings and are deliberately NOT on
     * the shared rung. This is a different category from NON_SECTION above, and conflating
     * the two was hiding a real distinction.
     *
     * NON_SECTION means "not a section heading at all" - a card title, a widget label, an
     * eyebrow marked up as an h2. Those are correctly small and scaling them would be a
     * regression.
     *
     * An entry here is a genuine section heading with a deliberate, recorded reason to sit
     * off the rung. Each one needs a justification, because the default answer is no: an
     * exception with no reason is just drift with a comment on it.
     */
    const RUNG_EXCEPTIONS = [
      {
        match: /(^|\.)lgd-h2(\.|$)/,
        why: '/terms/ and /privacy/ carry 71 numbered legal sections between them - 47 and 24. At 40px '
          + 'each one reads as a page title and the documents become a wall of headings; at '
          + '28px they read as the clause headings they are. Density, not drift.',
      },
    ];
    const exceptionFor = cls => RUNG_EXCEPTIONS.find( e => e.match.test( cls ) );

    console.log( '\nSection-h2 conformance @1280' );
    const expected1280 = Math.round( CONTRACT.at( 1280 ) * 100 ) / 100;
    const offLadder = [];
    const excepted = new Map();
    for ( const route of ROUTES ) {
      for ( const h of ( ( all[ route ] || {} )[ 1280 ] || [] ).filter( h => h.tag === 'h2' ) ) {
        if ( NON_SECTION.test( h.cls ) ) continue;
        if ( Math.abs( h.size - expected1280 ) > 0.75 || h.weight !== CONTRACT.weight ) {
          const exc = exceptionFor( h.cls );
          if ( exc ) {
            // Grouped by class and size so 45 legal headings report as one line rather
            // than burying the real failures under themselves.
            const key = `.${h.cls} = ${h.size}px/${h.weight}`;
            if ( !excepted.has( key ) ) excepted.set( key, { why: exc.why, routes: new Set(), n: 0 } );
            const rec = excepted.get( key );
            rec.routes.add( route );
            rec.n++;
            continue;
          }
          offLadder.push( `${route} .${h.cls || '(no class)'} = ${h.size}px/${h.weight}` );
        }
      }
    }
    /**
     * PER-PAGE CONSISTENCY, which is decision-independent. Whichever rung the site
     * settles on, a single page carrying two different sizes for the same job is wrong
     * either way. This caught `/`, where .home-flow-title resolved to 33.28px while
     * .home-close-title beside it resolved to 40px.
     */
    const inconsistentPages = [];
    for ( const route of ROUTES ) {
      const sizes = new Set(
        ( ( all[ route ] || {} )[ 1280 ] || [] )
          .filter( h => h.tag === 'h2' && !NON_SECTION.test( h.cls ) )
          .map( h => h.size ) );
      if ( sizes.size > 1 ) inconsistentPages.push( `${route} has ${[ ...sizes ].join( '/' )}px` );
    }
    record( inconsistentPages.length === 0,
      'no single page carries two different section-h2 sizes',
      inconsistentPages.length ? inconsistentPages.join( '; ' ) : 'every page internally consistent' );

    /**
     * THE DE-FACTO RUNG IS ONE DECLARATION, not a coincidence. clamp(28px,3.2vw,40px)
     * with weight 700, line-height 1.08 and letter-spacing -1.2px appears identically
     * under five different class names in five files. Asserting the whole declaration
     * matches - not just the size - is what proves it is a deliberate shared rung rather
     * than several near-misses that happen to agree at one width.
     */
    const rung = ( ( all[ '/contact/' ] || {} )[ 1280 ] || [] ).find( h => h.cls === 'cl-h2' );
    const rungPeers = [];
    for ( const route of ROUTES ) {
      for ( const h of ( ( all[ route ] || {} )[ 1280 ] || [] ) ) {
        if ( h.tag !== 'h2' || NON_SECTION.test( h.cls ) ) continue;
        if ( Math.abs( h.size - 40 ) > 0.75 ) continue;
        if ( rung && ( h.weight !== rung.weight || h.lh !== rung.lh || h.ls !== rung.ls ) ) {
          rungPeers.push( `${route} .${h.cls} = ${h.size}/${h.weight}/${h.lh}/${h.ls}` );
        }
      }
    }
    record( !!rung && rungPeers.length === 0,
      'the 40px rung is one identical declaration wherever it appears',
      rung ? `${rung.size}px/${rung.weight}/lh ${rung.lh}/ls ${rung.ls}` + ( rungPeers.length ? ` - divergent: ${rungPeers.join( '; ' )}` : '' ) : 'reference .cl-h2 not found' );

    // Contract conformance. This assertion used to be expected-red: the steering file
    // specified a rung no page shipped, and tuning the harness green would have hidden a
    // real disagreement. Both sides are now reconciled onto clamp(28px,3.2vw,40px), so a
    // failure here is once again a genuine signal - a page has drifted off the rung, or
    // someone has changed the contract without changing the site.
    record( offLadder.length === 0,
      `every section h2 is on the contract rung (${expected1280}px/700)`,
      offLadder.length ? `${offLadder.length} off-ladder: ${offLadder.slice( 0, 4 ).join( '; ' )}${offLadder.length > 4 ? ` (+${offLadder.length - 4} more)` : ''}` : 'all conform, or covered by a documented exception' );

    if ( excepted.size ) {
      console.log( '\n  Off the rung by documented exception (reported, not failed):' );
      for ( const [ key, rec ] of excepted ) {
        console.log( `    - ${key}  x${rec.n} on ${[ ...rec.routes ].join( ', ' )}` );
        console.log( `      ${rec.why}` );
      }
    }

    // Non-section h2s are reported, never failed - they are legitimately smaller.
    const nonSection = [];
    for ( const route of ROUTES ) {
      for ( const h of ( ( all[ route ] || {} )[ 1280 ] || [] ).filter( h => h.tag === 'h2' ) ) {
        if ( NON_SECTION.test( h.cls ) ) nonSection.push( `${route} .${h.cls} = ${h.size}px/${h.weight} "${h.text}"` );
      }
    }
    if ( nonSection.length ) {
      console.log( '\n  Not on the section rung by design (card/widget headings, reported not failed):' );
      for ( const n of nonSection ) console.log( `    - ${n}` );
    }
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `\n${results.length - failures}/${results.length} assertions passed` );
  if ( failures ) { console.log( `${failures} FAILED` ); process.exit( 1 ); }
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
