'use strict';

/**
 * uicheck - the header lockup, and the floating support pill.
 *
 * WHAT CHANGED, AND WHY THIS FILE WAS REWRITTEN. This harness used to measure TWO
 * floating widgets: `.wc-langbar` from this repo, and `#wecarewa-widget`, injected by
 * wecare-wa-widget.js from wecare-digital-get at `z-index: 2147483647` - the maximum
 * 32-bit integer, so nothing could ever be stacked above it. Every assertion here was
 * shaped by that constraint: it stubbed the external button when the script did not
 * load, checked the two circles were the same size and shared a centre line, measured
 * the gap between them, and proved the language panel could not be punched through by
 * a circle it was forbidden from covering.
 *
 * That script is retired. WhatsApp is now the left half of a single pill this repo owns
 * (src/components/SupportWidget.tsx), so all of the above is either meaningless or
 * unmeasurable: there is no second widget to align to, no gap, and no panel - the
 * language control is a native <select>, so the platform owns its popup and the page
 * cannot measure it. Keeping those assertions is what turned this file red.
 *
 * WHAT ONLY RENDERED GEOMETRY CAN STILL ANSWER.
 *
 * 1. THE BRAND LOCKUP. The logo is an <img> with a fixed height; the wordmark beside it
 *    is two lines whose height is font-size x line-height x 2. Two unrelated formulas,
 *    so they agree only by coincidence. The delta is REPORTED, not asserted - the logo
 *    being slightly taller than the wordmark is normal lockup practice and is currently
 *    a deliberate choice. What IS asserted is that the wordmark is optically centred
 *    against the logo, because an off-centre lockup is a defect under any sizing.
 *
 * 2. THE TWO CONTROLS INSIDE THE PILL. `.wc-wa` is a 44px circle; `.wc-chip` is a text
 *    chip whose height comes from font metrics and padding. Those are different
 *    formulas again, so "do they sit on one centre line inside the pill" cannot be read
 *    off the stylesheet - and a chip half a pixel low is visible at this size.
 *
 * 3. IS THE PILL ACTUALLY CLICKABLE. The retired external button won its stacking war
 *    by brute force. This one is a normal element at `z-index: 1300`, which has to clear
 *    the phone BottomNav (`z-index: 1200`, Layout.css) and the header menu (1002). Those
 *    numbers live in three files that cannot see each other, so the check here is not a
 *    number comparison but a hit test: `elementFromPoint` at the centre of each control
 *    must land inside that control. If anything is painted over the pill, that fails -
 *    whatever the reason, and regardless of which stylesheet caused it.
 *
 * 4. THE TRANSLATING STATE STAYS LIGHT. The busy signal was a dark #1a3a2a inversion of
 *    the chip and is now a lime pulse ring plus a lime sweep along the pill's bottom
 *    edge. "Not dark" is asserted on the COMPUTED background, because the requirement is
 *    about what renders, and a styled-jsx rule can be overridden by a later cascade
 *    without anyone editing SupportWidget.tsx. The pill's width is measured mid-flight
 *    too: the sweep is absolutely positioned precisely so a translation cannot resize
 *    the widget, and a regression there would make the corner of every page twitch.
 *
 * WHY NOT THE HOME PAGE. Only the lockup differs there (`homeBrand`); the pill is
 * identical, and /contact/ additionally carries the header variant most pages use. This
 * runs against /contact/ for continuity with the measurements this file has always taken.
 *
 * THE LANGUAGE API IS STUBBED. SupportWidget fetches wecare.digital/api, which sends no
 * Access-Control-Allow-Origin for 127.0.0.1, so against a local origin the fetch fails
 * and the language chip never appears. Note what that does NOT do any more: the widget
 * no longer returns null when the catalogue fails, so the WhatsApp half still renders.
 * The chip's absence is therefore a real failure rather than an ambiguous one, and it is
 * reported as such - an earlier revision of this file quietly skipped the assertion in
 * that case, which is the kind of silent pass this suite exists to prevent.
 *
 *   node tools/browser/uicheck.js
 *   BASE=http://localhost:3000 node tools/browser/uicheck.js
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );

const ROUTE = '/contact/';

/**
 * ONE SCROLL CONTAINER, AND A FOOTER THAT LANDS FLUSH.
 *
 * Layout.css used to put `height: 100%` and `overflow-y: auto` on html AND body, which made
 * two nested scrollers: the page scrolled inside body while html kept a separate leftover
 * range stacked on top, containing nothing. Scroll to the end and you travelled through
 * body's range and then through html's, and html's range was empty space - 196px of blank
 * white below the footer on a 390px phone, 623px on a 320px one with the footer pushed off
 * the top of the screen entirely.
 *
 * WHY THIS BELONGS IN A BROWSER HARNESS AND NOT ONLY IN A UNIT TEST. ScrollContainer.test.ts
 * pins the declarations, which catches the edit. It cannot catch the effect: the bug is a
 * product of viewport height against content height against a computed overflow value, and
 * the reason it survived review is that at 1440x900 html's leftover range happens to
 * compute to 0 - the widths people develop at were the widths it worked on. Only a real
 * layout at a real phone size answers it, so this asserts at every viewport in the matrix.
 */
async function measureScroll( page ) {
  return page.evaluate( () => {
    const de = document.documentElement, body = document.body;
    const range = el => el.scrollHeight - el.clientHeight;
    return {
      docRange: range( de ),
      bodyRange: range( body ),
      // Which elements could scroll at all. Anything beyond the document is a second
      // container, and the bug was body being one.
      bodyOverflowY: getComputedStyle( body ).overflowY,
      bodyHeight: getComputedStyle( body ).height,
      vh: window.innerHeight,
    };
  } );
}

/**
 * Scroll to the very end WITH REAL WHEEL INPUT, and report what sits below the footer.
 *
 * The wheel matters. A scripted `window.scrollTo` plus `body.scrollTop` drives both
 * containers to their own ends and therefore lands on the true bottom even when the bug is
 * present - which is precisely how a scripted version of this assertion passed against the
 * broken CSS while the page was visibly wrong. A wheel event goes to whichever container is
 * under the pointer and then chains, which is what a person does and what produced the
 * blank gap. Driving the real input is the difference between measuring the page and
 * measuring the harness.
 */
async function scrollToEnd( page, vp ) {
  await page.mouse.move( Math.round( vp.width / 2 ), Math.round( vp.height * 0.6 ) );
  for ( let i = 0; i < 70; i++ ) {
    await page.mouse.wheel( 0, 600 );
    await page.waitForTimeout( 35 );
  }
  await page.waitForTimeout( 600 );
  return page.evaluate( () => {
    const footer = document.querySelector( 'footer.ft-footer' );
    if ( !footer ) return { error: 'no footer.ft-footer' };
    const b = footer.getBoundingClientRect();
    const pill = document.querySelector( '.wc-pill' );
    const header = document.querySelector( 'header.hdr' );
    const p = pill ? pill.getBoundingClientRect() : null;

    /**
     * Overlap against footer CONTENT, not the footer box.
     *
     * The box spans the full width, so any bottom-right element overlaps it by definition -
     * an assertion on the box would fail forever and mean nothing. What matters is whether
     * anything a visitor reads or clicks is underneath: the lockup, the tagline, the lime
     * dash. The dash is named explicitly because it is the element that was being covered.
     */
    const covered = [];
    if ( p ) {
      for ( const el of document.querySelectorAll( '.ft-footer a, .ft-footer p, .ft-footer img, .ft-footer .ft-dash, .ft-footer .brand-copy' ) ) {
        const r = el.getBoundingClientRect();
        if ( !r.width || !r.height ) continue;
        if ( Math.min( p.right, r.right ) - Math.max( p.left, r.left ) > 0
          && Math.min( p.bottom, r.bottom ) - Math.max( p.top, r.top ) > 0 ) {
          covered.push( `${el.tagName.toLowerCase()}.${( el.className || '' ).toString().replace( /jsx-\w+/g, '' ).trim().split( /\s+/ ).join( '.' )}` );
        }
      }
    }

    return {
      footerTop: Math.round( b.top ), footerBottom: Math.round( b.bottom ),
      blankBelow: Math.round( window.innerHeight - b.bottom ),
      footerOffTop: b.bottom <= 0,
      pillBottom: p ? Math.round( p.bottom ) : null,
      pillTop: p ? Math.round( p.top ) : null,
      gapAboveFooter: p ? Math.round( b.top - p.bottom ) : null,
      underHeader: p && header ? p.top < header.getBoundingClientRect().bottom : null,
      covered: Array.from( new Set( covered ) ),
    };
  } );
}

/**
 * The pill's anchoring, taken from SupportWidget.tsx rather than guessed. Desktop is
 * `right:20px; bottom:20px`. Under 768px the right inset tightens and the bottom offset
 * jumps to clear the 60px BottomNav - `calc(72px + env(safe-area-inset-bottom))`, and
 * env() resolves to 0 in a headless viewport with no inset, so 72 is the number to expect
 * here. The breakpoint is max-width:767px, so 700 is mobile and 1024 is not.
 */
const PILL = {
  desktop: { right: 20, bottom: 20, slim: false },
  // bottom WAS 72, to clear the dashboard BottomNav - which no public page renders. Checked
  // at fourteen widths and absent at every one, so the pill floated above empty space here
  // while desktop sat at 20. Public pages now match desktop; the dashboard keeps 72 through
  // .is-appshell, which this harness never sees because it only loads public routes.
  mobile: { right: 16, bottom: 20, slim: true },
};

const VIEWPORTS = [
  { width: 1440, height: 900, label: 'desktop 1440', pill: PILL.desktop },
  { width: 1024, height: 800, label: 'tablet 1024', pill: PILL.desktop },
  { width: 700, height: 900, label: 'narrow 700', pill: PILL.mobile },
  { width: 390, height: 844, label: 'phone 390', pill: PILL.mobile },
];

/** The minimum comfortable touch target. Both support controls are now a true 44px. */
const TOUCH_MIN = 44;

const results = [];
let failures = 0;

function record( ok, name, detail ) {
  results.push( { ok, name } );
  if ( !ok ) failures++;
  console.log( `  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` - ${detail}` : ''}` );
}

/**
 * The BottomNav's z-index, READ OUT OF THE STYLESHEET rather than duplicated here. The
 * pill has to outrank it, and the two values live in files that never import each other -
 * src/styles/Layout.css and the styled-jsx block in SupportWidget.tsx - so a hardcoded
 * 1200 in this harness would keep passing after someone raised the bar's stacking. The
 * hit test below is the real protection; this is the diagnostic that names the culprit.
 */
function bottomNavZIndex() {
  try {
    const css = fs.readFileSync( path.join( __dirname, '..', '..', 'src', 'styles', 'Layout.css' ), 'utf8' );
    const m = /\.bottom-nav\s*\{[^}]*?z-index:\s*(\d+)/.exec( css );
    return m ? Number( m[ 1 ] ) : null;
  } catch {
    return null;
  }
}

/**
 * The exact shapes SupportWidget parses, taken from the component rather than invented:
 * /languages yields `{ languages: [{ code, name }] }` and /translate yields
 * `{ translations: [{ translatedText }] }`, one row per input text - the component throws
 * on a length mismatch, so the stub must echo the batch size. An earlier version of this
 * stub returned `{ label, native }` keys, which produced a valid 200 the component then
 * discarded: the widget stayed absent and the harness blamed the page.
 *
 * /voices is gone. Read-aloud was removed with the external script (Amazon Polly has no
 * voice for Tamil, Telugu, Bengali and most other Indic languages), so there is no second
 * catalogue request left to stub.
 */
const LANGS = [
  { code: 'en', name: 'English' },
  { code: 'hi', name: 'Hindi' },
  { code: 'bn', name: 'Bengali' },
];

/**
 * Slowing the FIRST translate batch, and only the first, is what makes the busy state
 * observable at all. Translation walks the page in batches of 30 text nodes, so on an
 * instant stub the whole run can finish inside one frame and the sweep would never be
 * catchable - a test that passes only because it never looked.
 */
const FIRST_BATCH_DELAY = 900;

async function stubLanguageApi( page ) {
  let translateCalls = 0;
  // MATCHED ON THE PATH, NOT THE HOST. This pattern was
  // /api\.wecare\.digital\/site-language\/.../ and it silently stopped matching when the
  // frontend moved to wecare.digital/api - SupportWidget's fetch went unstubbed, the
  // catalogue never arrived, .wc-chip never rendered, and four assertions failed with
  // "the language catalogue stub did not satisfy SupportWidget". The stub was pointing at
  // an address the app no longer calls. /site-language/ is the stable part of the contract,
  // so it is what this keys on; the host is free to move again.
  await page.route( /\/site-language\/(languages|translate)/, async route => {
    const headers = { 'access-control-allow-origin': '*' };
    if ( /\/translate/.test( route.request().url() ) ) {
      const body = route.request().postDataJSON() || {};
      const texts = Array.isArray( body.texts ) ? body.texts : [];
      if ( translateCalls++ === 0 ) await new Promise( resolve => setTimeout( resolve, FIRST_BATCH_DELAY ) );
      // A marker prefix rather than real Hindi: this proves the node was rewritten with
      // whatever came back, without pretending the stub can translate.
      return route.fulfill( {
        status: 200, contentType: 'application/json', headers,
        body: JSON.stringify( { translations: texts.map( text => ( { translatedText: `\u00b7${text}` } ) ) } ),
      } );
    }
    return route.fulfill( {
      status: 200, contentType: 'application/json', headers,
      body: JSON.stringify( { languages: LANGS } ),
    } );
  } );
}

async function measureLockup( page ) {
  return page.evaluate( () => {
    const lockup = document.querySelector( '.brand-lockup' );
    if ( !lockup ) return { error: 'no .brand-lockup' };
    const img = lockup.querySelector( 'img' );
    const copy = lockup.querySelector( '.brand-copy' );
    if ( !img || !copy ) return { error: `missing parts (img=${!!img} copy=${!!copy})` };
    const r = el => { const b = el.getBoundingClientRect(); return {
      top: Math.round( b.top * 100 ) / 100, bottom: Math.round( b.bottom * 100 ) / 100,
      h: Math.round( b.height * 100 ) / 100, w: Math.round( b.width * 100 ) / 100 }; };
    const i = r( img ), c = r( copy );
    return {
      img: i, copy: c,
      fontSize: getComputedStyle( copy.firstElementChild ).fontSize,
      delta: Math.round( ( i.h - c.h ) * 100 ) / 100,
      // Space above and below the wordmark relative to the logo box. Equal = centred.
      spaceAbove: Math.round( ( c.top - i.top ) * 100 ) / 100,
      spaceBelow: Math.round( ( i.bottom - c.bottom ) * 100 ) / 100,
    };
  } );
}

/**
 * The pill and the two controls inside it, plus the hit test at each control's centre.
 *
 * The hit test is the assertion that matters most in here. It answers "can a thumb
 * actually reach this" rather than "is the z-index numerically larger", and it catches
 * every cause of the same defect - a raised BottomNav, an overlay that forgot to unmount,
 * a sticky CTA, a cookie bar - without this file having to know any of them exist.
 */
async function measurePill( page ) {
  return page.evaluate( () => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const box = el => { const b = el.getBoundingClientRect(); return {
      w: Math.round( b.width ), h: Math.round( b.height ),
      left: Math.round( b.left ), right: Math.round( b.right ),
      top: Math.round( b.top ), bottomEdge: Math.round( b.bottom ),
      fromRight: Math.round( vw - b.right ), fromBottom: Math.round( vh - b.bottom ),
      // Unrounded centres: rounding first would hide a sub-pixel misalignment, which at
      // A square 44px control is the canonical touch floor and must stay round.
      centerX: Math.round( ( b.left + b.width / 2 ) * 100 ) / 100,
      centerY: Math.round( ( b.top + b.height / 2 ) * 100 ) / 100,
    }; };

    const bar = document.querySelector( '.wc-langbar' );
    const pill = document.querySelector( '.wc-pill' );
    const wa = document.querySelector( '.wc-pill .wc-wa' );
    const chip = document.querySelector( '.wc-pill .wc-chip' );
    const sweep = document.querySelector( '.wc-pill .wc-sweep' );
    const status = document.querySelector( '.wc-langbar .wc-sr' );

    /**
     * The chip's OWN text, not textContent. The chip contains the native <select>, and
     * textContent happily concatenates every <option> label into the result - the first
     * run of this assertion read "HIEnglishবাংলা — Bengaliहिन्दी — Hindi" and reported a
     * defect that did not exist. Direct child text nodes only.
     */
    const ownText = el => Array.from( el.childNodes )
      .filter( node => node.nodeType === Node.TEXT_NODE )
      .map( node => node.textContent )
      .join( '' ).trim();

    /** Does elementFromPoint at this element's centre land inside it? */
    const reachable = el => {
      if ( !el ) return null;
      const b = el.getBoundingClientRect();
      const hit = document.elementFromPoint( b.left + b.width / 2, b.top + b.height / 2 );
      if ( !hit ) return { ok: false, hit: '(nothing - outside the viewport?)' };
      const name = `${hit.tagName.toLowerCase()}${hit.className && typeof hit.className === 'string' ? `.${hit.className.trim().split( /\s+/ ).join( '.' )}` : ''}`;
      return { ok: el.contains( hit ), hit: name };
    };

    return {
      zIndex: bar ? getComputedStyle( bar ).zIndex : null,
      pill: pill ? box( pill ) : null,
      wa: wa ? box( wa ) : null,
      chip: chip ? box( chip ) : null,
      chipText: chip ? ownText( chip ) : null,
      chipBg: chip ? getComputedStyle( chip ).backgroundColor : null,
      chipBusy: chip ? chip.classList.contains( 'is-busy' ) : null,
      arrowShown: ( () => {
        const arw = document.querySelector( '.wc-pill .wc-arw' );
        return arw ? getComputedStyle( arw ).display !== 'none' : false;
      } )(),
      sweep: !!sweep,
      status: status ? status.textContent.trim() : null,
      waReach: reachable( wa ),
      chipReach: reachable( chip ),
    };
  } );
}

/**
 * Relative luminance of a computed colour string, used for one thing only: proving the
 * chip does not go dark while translating. Asserting "is not rgb(26, 58, 42)" would pass
 * for any other dark fill, which is not the requirement - the requirement is that the
 * corner of the page stays light while work is in flight.
 */
function luminance( colour ) {
  const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec( colour || '' );
  if ( !m ) return null;
  const [ r, g, b ] = m.slice( 1, 4 ).map( Number ).map( channel => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow( ( c + 0.055 ) / 1.055, 2.4 );
  } );
  return Math.round( ( 0.2126 * r + 0.7152 * g + 0.0722 * b ) * 1000 ) / 1000;
}

async function main() {
  const t = await target();
  const browser = await launch();
  const navZ = bottomNavZIndex();
  console.log( `uicheck - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}` );
  console.log( `route ${ROUTE}` );
  console.log( navZ === null
    ? 'could not read .bottom-nav z-index from src/styles/Layout.css'
    : `.bottom-nav z-index is ${navZ} (read from src/styles/Layout.css); the pill must outrank it\n` );

  try {
    for ( const vp of VIEWPORTS ) {
      const context = await browser.newContext( { viewport: { width: vp.width, height: vp.height } } );
      const page = await context.newPage();
      await stubLanguageApi( page );
      await gotoStable( page, t.base + ROUTE );

      const policyTranslatedFit = await page.evaluate( () => {
        const summary = document.querySelector( '.wc-policy summary' );
        if ( !summary ) return null;
        const original = summary.textContent;
        summary.textContent = 'تفاصيل سياسة الشحن والإرجاع والاسترداد والإلغاء';
        const box = summary.getBoundingClientRect();
        const parent = summary.parentElement?.getBoundingClientRect();
        const overflow = document.documentElement.scrollWidth - window.innerWidth;
        summary.textContent = original;
        return {
          fits: !!parent && box.width <= parent.width + 1 && box.left >= -1 && box.right <= window.innerWidth + 1,
          width: Math.round( box.width ),
          parent: parent ? Math.round( parent.width ) : null,
          overflow,
        };
      } );

      console.log( `${vp.label}` );
      if ( policyTranslatedFit ) {
        record( policyTranslatedFit.fits && policyTranslatedFit.overflow <= 0,
          `${vp.label}: translated Policy details trigger stays contained`,
          `${policyTranslatedFit.width}px in ${policyTranslatedFit.parent}px parent, overflow ${policyTranslatedFit.overflow}px` );
      }

      const lk = await measureLockup( page );
      if ( lk.error ) {
        record( false, `${vp.label}: lockup measurable`, lk.error );
      } else {
        console.log( `  lockup: logo ${lk.img.w}x${lk.img.h}, wordmark ${lk.copy.w}x${lk.copy.h} @${lk.fontSize} -> logo taller by ${lk.delta}px (reported, not a failure)` );
        record( Math.abs( lk.spaceAbove - lk.spaceBelow ) <= 0.5,
          `${vp.label}: wordmark optically centred against the logo`,
          `${lk.spaceAbove}px above / ${lk.spaceBelow}px below` );
      }

      // The pill is client-rendered, and the chip appears only once the (stubbed)
      // catalogue resolves - so wait for the chip, which implies the pill.
      let haveChip = true;
      try {
        await page.waitForSelector( '.wc-pill .wc-chip', { timeout: 15000 } );
      } catch {
        haveChip = false;
        const pillOnly = await page.$( '.wc-pill' );
        record( false, `${vp.label}: support pill rendered with its language chip`,
          pillOnly
            ? 'the pill is there but .wc-chip is missing - the language catalogue stub did not satisfy SupportWidget, or fewer than 2 languages parsed'
            : 'no .wc-pill at all - SupportWidget did not mount on this route' );
      }

      if ( haveChip ) {
        const m = await measurePill( page );

        console.log( `  pill   ${m.pill.w}x${m.pill.h} at right:${m.pill.fromRight} bottom:${m.pill.fromBottom}, z-index ${m.zIndex}` );
        console.log( `  wa     ${m.wa.w}x${m.wa.h} centre y ${m.wa.centerY}   chip ${m.chip.w}x${m.chip.h} centre y ${m.chip.centerY}  label "${m.chipText}"` );

        record( Math.abs( m.wa.centerY - m.chip.centerY ) <= 0.5,
          `${vp.label}: WhatsApp button and language chip share one centre line`,
          `${m.wa.centerY} vs ${m.chip.centerY}` );

        /**
         * THE WHATSAPP BUTTON IS A CIRCLE, AND THIS IS NOT A TAUTOLOGY. It carries
         * `border-radius: 50%`, which draws a circle only while the box is square - on a
         * 44x40 box it draws an ellipse. This assertion is here because it FAILED on first
         * run at 700px and 390px, and the cause was invisible from SupportWidget.tsx:
         * tokens.css raises `min-width`/`min-height` to 44px for every button, a and select
         * under 768px (a reasonable touch-target floor), and then Layout.css:94 resets
         * `min-height` to 32px unconditionally for the same selector list - later in the
         * cascade, same specificity, so it wins. It never resets `min-width`. The floor
         * therefore applied to ONE axis, stretching the older 40px circle into a 44x40 oval on
         * exactly the devices the widget matters most on. Neither file mentions the widget
         * and the widget mentions neither file, so only rendered geometry could find it.
         */
        record( m.wa.w === m.wa.h, `${vp.label}: WhatsApp button is round, not an oval`,
          `${m.wa.w}x${m.wa.h}${m.wa.w === m.wa.h ? '' : ' - border-radius:50% on a non-square box draws an ellipse; check the min-width floor in tokens.css'}` );

        // Containment, not a padding number: whatever the padding is, neither control may
        // poke out of the rounded pill, and overflow:hidden would clip it if it did.
        const contained = m.wa.left >= m.pill.left && m.chip.right <= m.pill.right
          && m.wa.top >= m.pill.top && m.chip.top >= m.pill.top
          && m.wa.bottomEdge <= m.pill.bottomEdge && m.chip.bottomEdge <= m.pill.bottomEdge;
        record( contained, `${vp.label}: both controls sit inside the pill`,
          `pill x ${m.pill.left}..${m.pill.right} y ${m.pill.top}..${m.pill.bottomEdge}; wa x ${m.wa.left}..${m.wa.right}; chip x ${m.chip.left}..${m.chip.right}` );

        record( m.pill.fromRight === vp.pill.right && m.pill.fromBottom === vp.pill.bottom,
          `${vp.label}: pill anchored where SupportWidget.tsx says`,
          `right:${m.pill.fromRight} bottom:${m.pill.fromBottom} (expected right:${vp.pill.right} bottom:${vp.pill.bottom})` );

        record( m.pill.left >= 8 && m.pill.top >= 0,
          `${vp.label}: pill stays fully on screen`,
          `left edge ${m.pill.left}px, top ${m.pill.top}px` );

        record( m.pill.h >= TOUCH_MIN, `${vp.label}: pill clears the ${TOUCH_MIN}px touch target`, `${m.pill.h}px tall` );

        /**
         * SLIM ON PHONES. The language arrow still drops away below 768px so the now-larger
         * 44px controls do not waste width on an extra chevron. The chevron
         * earns its place on a pointer device, where it is the only hint that the chip opens
         * something; a tap opens the OS language picker regardless.
         *
         * THE 44px CONTROLS ARE ASSERTED SEPARATELY AND DELIBERATELY. The mockup for this
         * shrank them to 36px, which would have put the tap target below the 44px floor on
         * the device where that matters most. Width was the complaint, so width is what was
         * spent; the controls did not move.
         */
        record( m.arrowShown === !vp.pill.slim,
          `${vp.label}: language chevron ${vp.pill.slim ? 'hidden on phones' : 'shown on pointer widths'}`,
          `arrow ${m.arrowShown ? 'shown' : 'hidden'}` );

        record( vp.pill.slim ? m.pill.w <= 105 : m.pill.w >= 104,
          `${vp.label}: pill is ${vp.pill.slim ? 'slim' : 'full width'}`,
          `${m.pill.w}px wide, ${Math.round( m.pill.w / vp.width * 1000 ) / 10}% of the screen` );

        record( m.wa.w === 44 && m.wa.h === 44,
          `${vp.label}: WhatsApp control stays 44px at every width`,
          `${m.wa.w}x${m.wa.h} - 44px is the app-first touch floor` );

        record( m.chip.h === 44,
          `${vp.label}: language control stays 44px tall`,
          `${m.chip.w}x${m.chip.h}` );

        // The two hit tests. See measurePill's note on why these beat comparing z-indexes.
        record( m.waReach.ok, `${vp.label}: nothing is painted over the WhatsApp button`,
          m.waReach.ok ? `centre hits ${m.waReach.hit}` : `centre hits ${m.waReach.hit}${navZ !== null ? ` - the pill is z-index ${m.zIndex}, .bottom-nav is ${navZ}` : ''}` );
        record( m.chipReach.ok, `${vp.label}: nothing is painted over the language chip`,
          `centre hits ${m.chipReach.hit}` );

        // ===== TRANSLATING =====
        /**
         * Switch to Hindi through the SEARCH PANEL and look at the pill while the first batch
         * is in flight.
         *
         * This was one selectOption call against a native <select>. The select is gone, and
         * what replaced it is a custom combobox - so this now drives the real path a visitor
         * takes: open the chip, type, confirm with the keyboard. Doing it by keyboard rather
         * than by clicking the row is deliberate: the keyboard is the half that a screenshot
         * cannot check and the half that the native control used to provide for free.
         */
        let switched = true;
        try {
          await page.click( '.wc-pill .wc-chip' );
          await page.waitForSelector( '.wc-panel .wc-search input', { timeout: 5000 } );
          await page.fill( '.wc-panel .wc-search input', 'hi' );
          await page.waitForTimeout( 200 );
          const first = await page.evaluate( () => {
            const row = document.querySelector( '.wc-row' );
            return row ? row.querySelector( '.wc-row-code' ).textContent.trim() : null;
          } );
          record( first === 'HI', `${vp.label}: typing a code puts that language first`, `first row is ${first}` );
          await page.keyboard.press( 'Enter' );
        } catch ( err ) {
          switched = false;
          record( false, `${vp.label}: language panel is operable`, err.message.split( '\n' )[ 0 ] );
        }

        if ( switched ) {
          let busy = null;
          try {
            await page.waitForSelector( '.wc-pill .wc-sweep', { timeout: 8000 } );
            busy = await measurePill( page );
          } catch {
            record( false, `${vp.label}: progress sweep shows while translating`,
              'no .wc-sweep appeared - the only signal that batches are in flight' );
          }

          if ( busy ) {
            const lum = luminance( busy.chipBg );
            console.log( `  translating: chip background ${busy.chipBg} (luminance ${lum}), is-busy ${busy.chipBusy}, pill ${busy.pill.w}px wide` );

            record( busy.sweep && busy.chipBusy === true,
              `${vp.label}: progress sweep and pulse ring both show while translating`,
              `sweep ${busy.sweep}, chip .is-busy ${busy.chipBusy}` );

            record( lum !== null && lum > 0.5,
              `${vp.label}: translating state stays light, no dark inversion`,
              `${busy.chipBg} -> luminance ${lum}${lum !== null && lum <= 0.5 ? ' - this is the #1a3a2a inversion that was removed' : ''}` );

            record( Math.abs( busy.pill.w - m.pill.w ) <= 2,
              `${vp.label}: pill does not resize while translating`,
              `${m.pill.w}px idle vs ${busy.pill.w}px busy` );
          }

          // Now let it finish. The status line is the honest end-to-end signal: the catch
          // in applyLanguage writes "Translation is unavailable right now." and restores
          // the English text, so a successful-looking run with a broken response shape
          // would still be caught here.
          let done = null;
          try {
            await page.waitForSelector( '.wc-pill .wc-sweep', { state: 'detached', timeout: 30000 } );
            done = await measurePill( page );
          } catch {
            record( false, `${vp.label}: translation finishes and the sweep clears`, 'the sweep was still running after 30s' );
          }

          if ( done ) {
            record( done.chipText === 'HI', `${vp.label}: chip reports the language now showing`, `reads "${done.chipText}"` );
            record( /Page translated to Hindi/.test( done.status || '' ),
              `${vp.label}: screen reader status announces the finished translation`,
              `"${done.status}"` );
            record( Math.abs( done.pill.w - m.pill.w ) <= 2,
              `${vp.label}: pill width unchanged after switching language`,
              `${m.pill.w}px as EN vs ${done.pill.w}px as HI` );
          }
        }
      }

      // ===== SCROLL CONTAINER =====
      const sc = await measureScroll( page );
      console.log( `  scroll: document range ${sc.docRange}px, body range ${sc.bodyRange}px (body overflow-y ${sc.bodyOverflowY}, height ${sc.bodyHeight})` );

      record( sc.bodyRange === 0,
        `${vp.label}: body is not a second scroll container`,
        sc.bodyRange === 0
          ? 'the document is the only scroller'
          : `body can scroll ${sc.bodyRange}px of its own - this is the two-scroller bug; check html/body in Layout.css` );

      record( sc.docRange > 0,
        `${vp.label}: the document is the scroller`,
        `${sc.docRange}px of range${sc.docRange > 0 ? '' : ' - nothing can scroll the page, so End/Home and window.scrollTo do nothing'}` );

      const end = await scrollToEnd( page, vp );
      if ( end.error ) {
        record( false, `${vp.label}: footer measurable at the end of the page`, end.error );
      } else {
        console.log( `  page end: footer y ${end.footerTop}..${end.footerBottom}, ${end.blankBelow}px below it; pill y ${end.pillTop}..${end.pillBottom}, ${end.gapAboveFooter}px above the footer` );
        record( !end.footerOffTop && end.blankBelow <= 1,
          `${vp.label}: footer lands flush at the end of the page`,
          end.footerOffTop
            ? 'the footer scrolled off the TOP of the screen - the page scrolls past its own end'
            : `${end.blankBelow}px of blank space below the footer` );

        /**
         * THE ASSERTION THE WHOLE FOOTER CHANGE EXISTS FOR. Before it, the pill covered
         * 34px of the 56px lime dash at 1440 and hid it ENTIRELY at 768, and on phones it
         * landed inside the footer at all seven sizes. Two fixes answer it: the dash moved
         * out of the bottom-right column into the brand block, and below 768px the pill
         * parks above the footer instead of descending into it.
         */
        record( end.covered.length === 0,
          `${vp.label}: pill covers no footer content at the end of the page`,
          end.covered.length ? `covers ${end.covered.join( ', ' )}` : 'nothing underneath it' );

        if ( vp.pill.slim ) {
          // Parking is mobile-only: above 768px the footer is short enough that the pill
          // clears it at its resting offset now the dash has moved out of that corner.
          record( end.gapAboveFooter >= 12,
            `${vp.label}: pill parks above the footer rather than sliding into it`,
            `${end.gapAboveFooter}px of clear air` );
          record( end.underHeader === false,
            `${vp.label}: parked pill stays clear of the fixed header`,
            end.underHeader ? 'it parked BEHIND the header - the ceiling clamp is not working' : 'below the header' );
        }
      }

      await context.close();
      console.log( '' );
    }
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `${results.length - failures}/${results.length} assertions passed` );
  if ( failures ) { console.log( `${failures} FAILED` ); process.exit( 1 ); }
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
