'use strict';
/**
 * designsweep - the Phase 4 consistency gate. Every public route, measured, against the home
 * page's own numbers.
 *
 * WHY IT EXISTS SEPARATELY FROM THE OTHER HARNESSES. uicheck, typecheck and seocheck each assert
 * one axis and none of them compares a control on one page with the same control on another, so
 * the whole suite ran green while:
 *
 *   - the dial-code half of the phone field shipped with NONE of its own styling on four public
 *     surfaces, rendering the "one field, divided" control as two boxes of different heights
 *   - the scrollbar was lime in Firefox and a 5px grey-green hairline in Chromium, Safari and
 *     every WebView, because four stylesheets declared it and the winning one carried !important
 *   - PillButton's label was font-weight:700 where every other primary on the site is 600
 *   - /blog/'s search box was the only field on the site at 12px radius instead of a full pill
 *   - /account/sign-in/ and /get/ had no way at all to ask for another OTP
 *
 * All five are cross-page facts. A per-page assertion cannot see any of them, which is the
 * argument for a harness that holds one standard and sweeps.
 *
 * THE STANDARD IS READ, NOT INVENTED. The reference is src/pages/index.tsx's .home-close-cta -
 * the home page's only call to action, and the owner's nominated button standard. This file
 * HARVESTS it from the built export at run time rather than hardcoding its numbers, so the day
 * the home page changes, the standard changes with it and nothing here goes stale. That is the
 * same harvest-never-paste rule .kiro/skills/new-public-page/SKILL.md applies to mocks, for the
 * same reason: a pasted copy is true exactly once.
 *
 * Run:  node tools/browser/designsweep.js
 *       node tools/browser/designsweep.js --firefox
 *       node tools/browser/designsweep.js /cart/ /orders/
 */

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

const ENGINE = process.argv.includes( '--firefox' ) ? 'firefox' : 'chromium';
const launchEngine = async () => (
  ENGINE === 'chromium' ? launch() : require( 'playwright-core' )[ ENGINE ].launch() );

const ARGS = process.argv.slice( 2 ).filter( a => !a.startsWith( '--' ) );

/**
 * Public routes that render an action, a field, or both. '/' is FIRST and is treated differently:
 * it supplies the standard and is never judged against it.
 */
const ROUTES = ARGS.length ? ARGS : [
  '/cart/', '/orders/', '/account/sign-in/', '/checkout/status/', '/checkout/success/',
  '/get/', '/shop/kiosk/', '/blog/', '/perks/', '/shipments/', '/contact/', '/vayulok/',
  '/refer-and-earn/', '/leave-review/', '/submit-request/', '/request-amendment/',
  '/drop-docs/', '/terms/', '/privacy/', '/404/',
];

/** The two viewports where the geometry differs: the compact scrollbar step is at 767px. */
const VIEWPORTS = [ { n: 'desktop', w: 1280, h: 900 }, { n: 'phone', w: 390, h: 844 } ];

/* ── colour ─────────────────────────────────────────────────────────────── */

function rgb ( value ) {
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.]+))?/.exec( value || '' );
  if ( !m ) return null;
  return { r: +m[ 1 ], g: +m[ 2 ], b: +m[ 3 ], a: m[ 4 ] === undefined ? 1 : +m[ 4 ] };
}

/** Composite a possibly-transparent colour over an opaque backdrop. */
function over ( fg, bg ) {
  if ( !fg ) return bg;
  if ( fg.a >= 1 ) return fg;
  return {
    r: fg.r * fg.a + bg.r * ( 1 - fg.a ),
    g: fg.g * fg.a + bg.g * ( 1 - fg.a ),
    b: fg.b * fg.a + bg.b * ( 1 - fg.a ),
    a: 1,
  };
}

function luminance ( c ) {
  const ch = v => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow( ( s + 0.055 ) / 1.055, 2.4 );
  };
  return 0.2126 * ch( c.r ) + 0.7152 * ch( c.g ) + 0.0722 * ch( c.b );
}

function contrast ( a, b ) {
  const la = luminance( a ), lb = luminance( b );
  return ( Math.max( la, lb ) + 0.05 ) / ( Math.min( la, lb ) + 0.05 );
}

const WHITE = { r: 255, g: 255, b: 255, a: 1 };

/* ── in-page probes ─────────────────────────────────────────────────────── */

/**
 * Harvest the reference from the home page. .home-close-cta is inside a band that is hidden
 * until an IntersectionObserver fires, so it is read with getComputedStyle regardless of
 * opacity - the question is what the rules say, not whether it is on screen right now.
 */
const HARVEST = () => {
  const el = document.querySelector( '.home-close-cta' );
  if ( !el ) return null;
  const s = getComputedStyle( el );
  return {
    bg: s.backgroundColor, fg: s.color, fontSize: s.fontSize, fontWeight: s.fontWeight,
    borderWidth: s.borderTopWidth, borderColor: s.borderTopColor,
    minHeight: s.minHeight, radius: s.borderTopLeftRadius,
  };
};

const PROBE = () => {
  const vis = el => {
    const s = getComputedStyle( el );
    if ( s.display === 'none' || s.visibility === 'hidden' || Number( s.opacity ) === 0 ) return false;
    const b = el.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  };
  const names = el => ( el.className || '' ).toString().split( /\s+/ )
    .filter( c => c && !c.startsWith( 'jsx-' ) );

  const html = getComputedStyle( document.documentElement );
  const sb = sel => getComputedStyle( document.documentElement, sel );

  /**
   * TYPE IS MEASURED WHERE THE TEXT IS, NOT ON THE CONTROL.
   *
   * The first version of this harness read font-weight off the <button> and reported PillButton
   * as 400 against the reference's 600 - on a control whose visible label is a <span> at 600.
   * The outer element's weight is inherited and never painted, so that was the harness being
   * wrong about a button that was right. The reference .home-close-cta carries its own text
   * directly, which is why the mistake was invisible on the home page.
   *
   * So: walk to the deepest element that still holds the control's whole trimmed text. For a
   * label-in-a-span that is the span; for a control that carries its own text it is the control.
   */
  const typeHost = el => {
    const want = ( el.textContent || '' ).trim();
    if ( !want ) return el;
    let node = el;
    for ( ;; ) {
      const next = Array.from( node.children )
        .find( c => ( c.textContent || '' ).trim() === want );
      if ( !next ) return node;
      node = next;
    }
  };

  /** The largest of the four corner radii. A segment of a divided control is square on the
   *  divider side by design, so reading only top-left reports 0 for a correct pill half. */
  const maxRadius = s => Math.max(
    parseFloat( s.borderTopLeftRadius ) || 0, parseFloat( s.borderTopRightRadius ) || 0,
    parseFloat( s.borderBottomLeftRadius ) || 0, parseFloat( s.borderBottomRightRadius ) || 0 );

  const controls = Array.from( document.querySelectorAll(
    'main button, main a[role="button"], main input[type="submit"], main .btn, main .pill,'
    + ' main .otp-resend, main [class*="-cta"], main [class*="-btn"]' ) )
    .filter( el => vis( el ) && el.tagName !== 'SPAN' )
    .map( el => {
      const s = getComputedStyle( el );
      const t = getComputedStyle( typeHost( el ) );
      return {
        cls: names( el ).join( '.' ) || el.tagName.toLowerCase(),
        text: ( el.textContent || '' ).trim().replace( /\s+/g, ' ' ).slice( 0, 40 ),
        bg: s.backgroundColor, fg: t.color, radius: `${maxRadius( s )}px`,
        borderWidth: s.borderTopWidth, borderColor: s.borderTopColor,
        fontSize: t.fontSize, fontWeight: t.fontWeight,
        h: Math.round( el.getBoundingClientRect().height ),
      };
    } );

  /**
   * A FIELD IS JUDGED ON THE OUTLINE A CUSTOMER SEES, which is not always the <input>.
   *
   * PhoneField is one outlined container holding two borderless segments - that is the whole
   * point of "one field, divided" - so the radius and the height that matter belong to `.pf`,
   * and the segments legitimately carry `border:0` and a square edge against the divider. The
   * first version of this harness measured the segments and reported the correct control as
   * broken, which is the same mistake as reading type off a button instead of its label.
   *
   * The test is structural rather than a class-name list: an input with no border of its own,
   * inside a parent that has one, is a SEGMENT, and the parent is the field.
   */
  const fieldBox = el => {
    const s = getComputedStyle( el );
    if ( parseFloat( s.borderTopWidth ) > 0 ) return el;
    const parent = el.parentElement;
    if ( !parent ) return el;
    const ps = getComputedStyle( parent );
    return parseFloat( ps.borderTopWidth ) > 0 ? parent : el;
  };

  const seen = new Set();
  const fields = [];
  for ( const el of document.querySelectorAll(
    'main input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
    + ':not([type="submit"]):not([type="file"]), main textarea' ) ) {
    if ( !vis( el ) ) continue;
    const box = fieldBox( el );
    if ( seen.has( box ) ) continue;
    seen.add( box );
    const s = getComputedStyle( box );
    const inner = getComputedStyle( el );
    fields.push( {
      cls: names( box ).join( '.' ) || box.tagName.toLowerCase(),
      radius: `${maxRadius( s )}px`, borderWidth: s.borderTopWidth,
      // The type size is the INPUT's - that is what a customer reads and what iOS zooms on -
      // even when the outline belongs to the container.
      fontSize: inner.fontSize,
      h: Math.round( box.getBoundingClientRect().height ),
    } );
  }

  // Every OTP-ish control's visible text, for the wording and resend assertions.
  const actionText = Array.from( document.querySelectorAll( 'main button, main a[role="button"]' ) )
    .filter( vis ).map( el => ( el.textContent || '' ).trim().replace( /\s+/g, ' ' ) );

  return {
    controls, fields, actionText,
    scrollbar: {
      color: html.scrollbarColor,
      width: html.scrollbarWidth,
      thumb: sb( '::-webkit-scrollbar-thumb' ).backgroundColor,
      track: sb( '::-webkit-scrollbar-track' ).backgroundColor,
      size: sb( '::-webkit-scrollbar' ).width,
    },
  };
};

/* ── assertions ─────────────────────────────────────────────────────────── */

const fails = [];
const notes = [];
const fail = ( where, msg ) => fails.push( `${where}: ${msg}` );

/** A control whose fill is the home lime is a PRIMARY and must match the reference exactly. */
const isLime = v => {
  const c = rgb( v );
  return !!c && c.a > 0.9 && c.r === 209 && c.g === 244 && c.b === 112;
};

/**
 * Fully rounded, not a specific number. The reference says 50px and PillButton says 999px; at
 * 52px tall both resolve to the same pill, so asserting one literal would fail the other for no
 * visible difference. The property is "the radius is at least half the height".
 */
const isPill = ( radius, height ) => {
  const px = parseFloat( radius );
  return Number.isFinite( px ) && height > 0 && px >= height / 2 - 0.5;
};

/** Controls that are deliberately not primary actions, with the reason. */
const EXEMPT = [
  // An ACTIVE TAB, not an action. /grahak-os/ carries its own committed design contract in
  // .kiro/steering/grahak-os-design.md and design-reference.tsx assigns lime to "active tabs".
  /\bpp-tab\b/,
  // The header's WhatsApp glyph is a 40px circular icon affordance, not a text button.
  /\bwc-wa\b/,
  // The home terminal's pause control. WCAG 2.2.2 furniture on a decorative animation.
  /\bwt-play\b/,
];

function checkRoute ( route, viewport, ref, r ) {
  const where = `${route} @${viewport.n}`;

  /* ── 1. the scrollbar, and the two engines must agree ── */
  const thumbExpected = { r: 26, g: 58, b: 42, a: 1 };
  const trackExpected = { r: 209, g: 244, b: 112, a: 0.22 };

  if ( ENGINE === 'chromium' ) {
    const thumb = rgb( r.scrollbar.thumb );
    if ( !thumb || thumb.r !== thumbExpected.r || thumb.g !== thumbExpected.g
      || thumb.b !== thumbExpected.b ) {
      fail( where, `scrollbar thumb is ${r.scrollbar.thumb}, expected the --scrollbar-thumb `
        + 'token rgb(26, 58, 42). A competing declaration has won - check for a stray '
        + '::-webkit-scrollbar block, especially one carrying !important.' );
    }
    const size = parseFloat( r.scrollbar.size );
    const want = viewport.w <= 767 ? 7 : 10;
    if ( size !== want ) {
      fail( where, `scrollbar width is ${r.scrollbar.size}, expected ${want}px at this viewport` );
    }
  }

  // scrollbar-color is read by Firefox and reported by both engines, so it is checked on both -
  // it is the half that silently disagreed with the WebKit half for the life of the defect.
  const sc = ( r.scrollbar.color || '' ).toLowerCase();
  if ( !/26,\s*58,\s*42/.test( sc ) ) {
    fail( where, `scrollbar-color thumb is "${r.scrollbar.color}", expected rgb(26, 58, 42). `
      + 'The two engines read different properties for the same thing, so this half drifting is '
      + 'how the site ended up with one scrollbar in Firefox and another everywhere else.' );
  }
  if ( !/209,\s*244,\s*112/.test( sc ) ) {
    fail( where, `scrollbar-color track is "${r.scrollbar.color}", expected the lime state tint` );
  }
  // The thumb has to be findable against its own track - WCAG 1.4.11, 3:1 for a control boundary.
  const ratio = contrast( over( thumbExpected, WHITE ), over( trackExpected, WHITE ) );
  if ( ratio < 3 ) {
    fail( where, `scrollbar thumb-on-track contrast is ${ratio.toFixed( 2 )}:1, under the 3:1 `
      + 'WCAG 1.4.11 asks of a control boundary' );
  }

  /* ── 2. buttons ── */
  let limeSurfaces = 0;
  for ( const c of r.controls ) {
    if ( EXEMPT.some( re => re.test( c.cls ) ) ) continue;
    const at = `${where} ${c.cls} "${c.text}"`;

    if ( isLime( c.bg ) ) {
      limeSurfaces++;
      // A primary matches the reference. Each property is reported separately so a failure says
      // which number moved rather than "it differs".
      if ( c.fontWeight !== ref.fontWeight ) {
        fail( at, `font-weight ${c.fontWeight}, home standard is ${ref.fontWeight}` );
      }
      if ( c.fontSize !== ref.fontSize ) {
        notes.push( `${at}: font-size ${c.fontSize} vs home ${ref.fontSize}` );
      }
      if ( parseFloat( c.borderWidth ) !== parseFloat( ref.borderWidth ) ) {
        fail( at, `border ${c.borderWidth}, home standard is ${ref.borderWidth}` );
      }
      const bc = rgb( c.borderColor );
      if ( !bc || bc.r !== 26 || bc.g !== 58 || bc.b !== 42 ) {
        fail( at, `border colour ${c.borderColor}, home standard is rgb(26, 58, 42). A lime `
          + 'border on a lime fill contributes nothing and cannot clear WCAG 1.4.11.' );
      }
      if ( !isPill( c.radius, c.h ) ) {
        fail( at, `radius ${c.radius} at ${c.h}px tall is not fully rounded; the home standard `
          + 'is a pill' );
      }
      const fgOnBg = contrast( over( rgb( c.fg ), over( rgb( c.bg ), WHITE ) ),
        over( rgb( c.bg ), WHITE ) );
      if ( fgOnBg < 4.5 ) {
        fail( at, `label contrast ${fgOnBg.toFixed( 2 )}:1 on its own fill, under 4.5:1` );
      }
    }

    // THE TAP FLOOR APPLIES TO EVERY CONTROL, primary or not. 44px, the site's own number.
    if ( c.h > 0 && c.h < 44 ) {
      fail( at, `${c.h}px tall, under the 44px tap target this site holds everything else to` );
    }
  }

  // One primary lime surface per page, the owner's rule. Reported as a note rather than a
  // failure: a page legitimately offers one primary per independent form - the blog subscribe
  // block has a phone step and an email step - and this harness cannot see form boundaries.
  if ( limeSurfaces > 1 ) {
    notes.push( `${where}: ${limeSurfaces} lime surfaces - check each is a separate form's own `
      + 'primary and not a second action competing with the first' );
  }

  /* ── 3. fields ── */
  for ( const f of r.fields ) {
    const at = `${where} field ${f.cls}`;
    if ( !isPill( f.radius, f.h ) ) {
      fail( at, `radius ${f.radius} at ${f.h}px tall; every public field on this site is a full `
        + 'pill (.si-input, .sf-input, PhoneField, BlogSubscribe, CheckoutProfile)' );
    }
    if ( parseFloat( f.fontSize ) < 16 ) {
      fail( at, `font-size ${f.fontSize}, under the 16px floor below which iOS Safari zooms the `
        + 'viewport on focus' );
    }
    /*
     * 17px EXACTLY, because that is the site's field size and it took a measurement to find out
     * it was not being painted. .si-input, .sf-input, PhoneField's segments and BlogSearch's
     * input all DECLARE 17px - chosen so a field matches the 17px CTA it feeds - and every one
     * of them rendered at 16px, because Layout.css forced `font-size:var(--text-base)
     * !important` onto every input on the site. Four components, four deliberate declarations,
     * none reaching the page, and nothing in the suite able to see it.
     * A note rather than a failure: a legitimately dense field (a short inline code box, a
     * filter) may want the smaller rung, and the >=16px floor above is the hard rule.
     */
    if ( parseFloat( f.fontSize ) !== 17 ) {
      notes.push( `${at}: font-size ${f.fontSize}, the site's field size is 17px` );
    }
    if ( f.h > 0 && f.h < 44 ) {
      fail( at, `${f.h}px tall, under the 44px floor` );
    }
  }

  /* ── 4. OTP wording, and the resend must exist wherever a send does ── */
  const send = r.actionText.filter( t => /send .*otp|send .*code/i.test( t ) );
  for ( const t of send ) {
    if ( /email/i.test( t ) ) continue;   // the one-time email verification, not a sign-in OTP
    if ( !/on WhatsApp/i.test( t ) ) {
      fail( where, `"${t}" does not name WhatsApp. OTP is a WhatsApp-only channel on this site, `
        + 'so every OTP control reads "... OTP on WhatsApp".' );
    }
  }
  for ( const t of r.actionText ) {
    if ( /\bOTP\b/i.test( t ) && /\bemail\b/i.test( t ) ) {
      fail( where, `"${t}" offers an OTP by email. Email is the one-time VERIFICATION channel `
        + 'only, never a sign-in OTP channel.' );
    }
  }
}

/* ── run ────────────────────────────────────────────────────────────────── */

( async () => {
  const t = await target();
  const browser = await launchEngine();
  let ref = null;

  try {
    for ( const viewport of VIEWPORTS ) {
      const page = await browser.newPage( { viewport: { width: viewport.w, height: viewport.h } } );

      await gotoStable( page, `${t.base}/` );
      const harvested = await page.evaluate( HARVEST );
      if ( !harvested ) {
        fails.push( '/: .home-close-cta not found, so the button standard cannot be harvested. '
          + 'Either the home CTA was renamed - update this harness - or the home page failed to '
          + 'render, in which case nothing below means anything.' );
        await page.close();
        break;
      }
      if ( !ref ) ref = harvested;
      // The home page itself is never judged; it IS the standard.
      const home = await page.evaluate( PROBE );
      notes.push( `/ @${viewport.n}: reference lime=${harvested.bg} fg=${harvested.fg} `
        + `${harvested.fontSize}/${harvested.fontWeight} r=${harvested.radius} `
        + `b=${harvested.borderWidth} ${harvested.borderColor} h=${harvested.minHeight}` );
      // The scrollbar IS asserted on the home page - it is shared chrome, not page design.
      checkRoute( '/', viewport, harvested, { ...home, controls: [], fields: [], actionText: [] } );

      for ( const route of ROUTES ) {
        const res = await gotoStable( page, t.base + route );
        if ( res && res.status() >= 400 && route !== '/404/' ) {
          fails.push( `${route}: HTTP ${res.status()}` );
          continue;
        }
        checkRoute( route, viewport, harvested, await page.evaluate( PROBE ) );
      }
      await page.close();
    }
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `designsweep (${ENGINE}) - ${ROUTES.length} routes x ${VIEWPORTS.length} viewports` );
  for ( const n of notes ) console.log( `  note  ${n}` );
  if ( fails.length ) {
    console.log( `\n${fails.length} FAILURE(S)` );
    for ( const f of fails ) console.log( `  FAIL  ${f}` );
    process.exit( 1 );
  }
  console.log( '\nPASS' );
} )();
