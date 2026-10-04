'use strict';

/**
 * ordersreview - the review page for /orders/, generated BEFORE src/pages/orders.tsx is rebuilt.
 *
 * WHAT THIS IS. One self-contained HTML file, docs/orders-review.html, showing the /orders/ page
 * as it ships today beside the one proposal: the top band moves from RotatingHero to PageTopBand
 * and an order list with status chips goes below it. The current page is first, at 1:1, labelled
 * unmodified. There are no alternatives, because no design decision is outstanding - the band,
 * the pill and the status treatment are all specified from components and tokens that already
 * ship. If a reviewer wants an option, that is a new mock rather than a late edit to this one.
 *
 * WHY THE ORDER OF OPERATIONS IS THE WHOLE POINT. Everything below is harvested from the real
 * static export in out/ at generation time. So this generator must run while /orders/ is still
 * the un-rebuilt page: re-run it after the rebuild and the "before" panels harvest the rebuild
 * and demonstrate nothing. docs/orders-review.html is therefore the PRE-REBUILD evidence and is
 * NOT regenerated afterwards. Design 6.0c and plan decision D3.
 *
 * HARVEST, NEVER PASTE. The CSS and the markup come out of out/ through the browser:
 *   /orders/              the current band and its content   -> every "before" panel
 *   /account/sign-in/     PageTopBand, and PillButton         -> the proposal's band and pill
 *   /cart/                .cart-status / .cart-status-firm    -> the status chip
 *   /checkout/status/     .co-btn / .co-btn-quiet             -> "Show more orders"
 * A hand-pasted mock is true exactly once. The only original CSS in this file is PROPOSAL_CSS,
 * the ord-* rules for the order list, which cannot be harvested because they do not exist yet -
 * that is what FEAT-003 writes.
 *
 * STATIC MARKUP, NO JAVASCRIPT, ANYWHERE. Neither this page nor any panel inside it runs a
 * script: a mock whose panels are assembled by script shows headings and nothing else in any
 * viewer that does not run scripts, which is the exact defect class being reviewed. The
 * generator asserts the emitted file contains no <script at all.
 *
 * THE SETTLED STATE IS BAKED IN. With scripting off an un-hydrated RotatingHero renders its own
 * defect, and a panel labelled "as it ships today" that shows a broken state is a lie about the
 * baseline. So the before panels get the server-rendered first word plus the pill width
 * JavaScript measures, and the is-armed/show entrance classes are stripped because the CSS
 * default already is the finished state.
 *
 * PANELS ARE REAL-WIDTH IFRAMES at 1280x900, 390x844, 280x653 and 653x280, at 1:1, with real
 * viewport heights and no crops. The last two are the foldable postures, and they are precisely
 * what a div-in-one-document mock cannot represent: clamp(), vw and 100vh inside an iframe
 * resolve against the frame's own box.
 *
 * ASSERT THE MOCK, DO NOT LOOK AT IT. After writing the file the generator re-opens it and reads
 * computed style INSIDE every frame, checking EQUALITY with the live measurement taken from the
 * export at the same viewport - never a range, because a range hides fidelity drift while an
 * equality check fails the moment the mock stops matching the page. Per panel: the h1's
 * font-size, font-weight, letter-spacing and font-family; the band's top padding (the 108px/96px
 * header clearance); the sub-line's colour and size; and on the proposal's list panels the status
 * chip's border-inline-start width, style, colour and background. Any mismatch exits non-zero.
 *
 * THE TWO TRAPS THE SKILL RECORDS, GUARDED RATHER THAN EYEBALLED.
 *   1. styled-jsx compiles `.x::before` to `.x.jsx-HASH::before`, which is (0,2,1), so anything
 *      injected at (0,1,1) never applies. Guarded two ways: structurally, by asserting the
 *      compiled `.rh-mark.jsx-HASH:before` form is present in the harvested CSS and that the
 *      harvested markup still carries the hash; and by measuring, since every before panel
 *      asserts the ::before transform equals the live page's.
 *   2. A CSS trim that drops `*{box-sizing:border-box}` reports wrong box sizes throughout. The
 *      reset is extracted from the built chunks rather than retyped, and every panel asserts its
 *      band layout's computed box-sizing equals the live one.
 * Every string substitution into harvested markup also asserts it changed something, because a
 * silently non-matching replace is how a "before" panel ends up showing the fixed state.
 *
 * WHAT IS PUBLISHED AS NUMBERS INSTEAD OF A PANEL. forced-colors and font fallback both resolve
 * against the operating system, so this machine's rendering is not the reader's. Both are
 * measured and published as a table.
 *
 * Run:    node tools/browser/ordersreview.js      (needs out/ - run `npm run build` first)
 * Writes: docs/orders-review.html
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

const REPO = path.join( __dirname, '..', '..' );
const OUT_FILE = path.join( REPO, 'docs', 'orders-review.html' );

// Real postures, not sampled widths. 1280x900 desktop, 390x844 phone, and the two folded
// Galaxy Fold postures the device matrix exists for. Heights are viewport heights.
const VIEWPORTS = [
  { k: 'w1280', w: 1280, h: 900, label: 'Desktop — 1280×900' },
  { k: 'w390', w: 390, h: 844, label: 'Phone — 390×844' },
  { k: 'f280', w: 280, h: 653, label: 'Fold, folded portrait — 280×653' },
  { k: 'f653', w: 653, h: 280, label: 'Fold, folded landscape — 653×280' },
];

// ---------------------------------------------------------------------------------------------
// THE PROPOSAL'S OWN CSS. The only original code in this file, and only because these rules do
// not exist anywhere to harvest from yet - FEAT-003 writes them into src/pages/orders.tsx.
// Values are the site's, not invented: the h2 rung is clamp(28px,3.2vw,40px)/700/1.08/-1.2px,
// the body rung is 20px/400/1.4/-.125px at rgba(0,0,0,.898) dropping to 18px under 767px, the
// border is #e5e7eb, and colour comes from no hex outside src/styles/tokens.css. The chip, the
// pill and the quiet button are NOT here - those are harvested, so the mock cannot drift from
// what ships. No overflow:hidden and no fixed height on any rule, so WCAG 1.4.12 text spacing
// cannot clip.
// ---------------------------------------------------------------------------------------------
const SANS = "'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif";
const PROPOSAL_CSS = `
  /* color-scheme declared, not inferred: the site has no dark support anywhere, so a browser
     left to infer one would recolour form controls and scrollbars against a hardcoded light
     palette. */
  .ord-wrap{color-scheme:light;font-family:${SANS}}
  .ord-h2{
    font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;
    color:rgba(0,0,0,.95);margin:0 0 20px;font-family:${SANS};
  }
  .ord-p{
    font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
    color:rgba(0,0,0,.898);margin:0 0 20px;max-width:560px;font-family:${SANS};
  }
  .ord-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:16px}
  .ord-row{border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px;background:#fff}
  .ord-no{font-size:20px;font-weight:700;line-height:1.3;letter-spacing:-.3px;color:rgba(0,0,0,.95);margin:0}
  .ord-dl{margin:12px 0 0;display:grid;grid-template-columns:auto 1fr;gap:6px 16px;
    font-size:16px;line-height:1.5;color:rgba(0,0,0,.898)}
  .ord-dt{font-weight:600;color:#1a3a2a;margin:0}
  .ord-dd{margin:0}
  .ord-pill{margin-top:28px}
  /* The quiet secondary's own declarations are not written here - they are harvested from
     /checkout/status/ at generation time and re-scoped onto .ord-more, because they ship
     scoped to a descendant of .co-card and that card is not part of this page. See
     QUIET_CSS below, and the equality assertion that proves the re-scope actually applied. */
  .ord-more{margin-top:24px;display:inline-flex;cursor:pointer}
  @media(max-width:767px){
    .ord-p{font-size:18px}
    .ord-row{padding:16px}
  }
`;

// Copy, verbatim from design 3.9. Copy is not a harvestable asset - the page it belongs to does
// not exist yet - so it is written here and will be written again in orders.tsx.
const COPY = {
  h1: 'Your orders',
  sub: 'What you have bought from us, and what each payment is doing.',
  signedOut: 'Sign in on your WhatsApp number to see your orders.',
  pill: 'Sign in on WhatsApp',
  ordersHeading: 'Order history',
  more: 'Show more orders',
};

// Two sample rows. Amounts are what src/lib/money.ts's formatPaiseINR returns for 699900 and
// 1399900 integer paise; the order numbers and dates are plainly fictional. Both the number and
// the amount carry data-wc-no-translate, because an identifier and a sum of money must survive
// every language - the date deliberately does not, since a localised month name is an
// improvement and no decision depends on its spelling.
const ROWS = [
  {
    no: 'WD-100042', date: '3 Oct 2026', amount: '₹6,999.00',
    status: 'Paid', line: '', firm: false,
  },
  {
    no: 'WD-100041', date: '28 Sep 2026', amount: '₹13,999.00',
    status: 'Payment confirming', line: 'This usually settles within a few minutes.', firm: true,
  },
];

const esc = s => String( s ).replace( /&/g, '&amp;' ).replace( /</g, '&lt;' ).replace( />/g, '&gt;' );

/** Replace and prove it replaced. A silently non-matching replace is how a mock lies. */
function sub ( str, re, to, what ) {
  const out = str.replace( re, to );
  if ( out === str ) throw new Error( `ordersreview: substitution had no effect (${what})` );
  return out;
}

// ---------------------------------------------------------------------------------------------
// IN-PAGE READERS. Every expectation this generator asserts comes out of one of these, run
// against the real export. The key names are shared with the in-frame reader below so a frame's
// numbers can be compared to a live page's key by key.
// ---------------------------------------------------------------------------------------------

/** The current page: the "before" truth. Selectors are RotatingHero's. */
const READ_RH = () => {
  const st = ( s, p, pseudo ) => {
    const el = document.querySelector( s );
    return el ? getComputedStyle( el, pseudo || null )[ p ] : null;
  };
  const first = document.querySelectorAll( '.rh-cyc-word' )[ 0 ];
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    h1FontSize: st( '.rh-head', 'fontSize' ),
    h1FontWeight: st( '.rh-head', 'fontWeight' ),
    h1LetterSpacing: st( '.rh-head', 'letterSpacing' ),
    h1FontFamily: st( '.rh-head', 'fontFamily' ),
    bandPadTop: st( '.rh-shell', 'paddingTop' ),
    subColor: st( '.rh-sub', 'color' ),
    subFontSize: st( '.rh-sub', 'fontSize' ),
    subLineHeight: st( '.rh-sub', 'lineHeight' ),
    subLetterSpacing: st( '.rh-sub', 'letterSpacing' ),
    layoutBoxSizing: st( '.rh-layout', 'boxSizing' ),
    markBeforeTransform: st( '.rh-mark', 'transform', '::before' ),
    dotTransform: st( '.rh-mark-dot', 'transform' ),
    cycleWidth: st( '.rh-cycle', 'width' ),
    w0: first ? first.offsetWidth : null,
    h1Text: ( document.querySelector( '.rh-head' ) || {} ).textContent || '',
  };
};

/** The proposal's band and pill: PageTopBand and PillButton, live on /account/sign-in/. */
const READ_PTB = () => {
  const st = ( s, p ) => {
    const el = document.querySelector( s );
    return el ? getComputedStyle( el )[ p ] : null;
  };
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    h1FontSize: st( '.ptb-h1', 'fontSize' ),
    h1FontWeight: st( '.ptb-h1', 'fontWeight' ),
    h1LetterSpacing: st( '.ptb-h1', 'letterSpacing' ),
    h1FontFamily: st( '.ptb-h1', 'fontFamily' ),
    bandPadTop: st( '.ptb-shell', 'paddingTop' ),
    subColor: st( '.ptb-sub', 'color' ),
    subFontSize: st( '.ptb-sub', 'fontSize' ),
    subLineHeight: st( '.ptb-sub', 'lineHeight' ),
    subLetterSpacing: st( '.ptb-sub', 'letterSpacing' ),
    layoutBoxSizing: st( '.ptb-layout', 'boxSizing' ),
    pillMinHeight: st( '.pill', 'minHeight' ),
    pillBg: st( '.pill', 'backgroundColor' ),
    pillBorderWidth: st( '.pill', 'borderTopWidth' ),
    pillActionFontSize: st( '.pill-action', 'fontSize' ),
    pillActionFontWeight: st( '.pill-action', 'fontWeight' ),
  };
};

/**
 * The status chip's live values. The chip is a /cart/ notice, and the cart's export renders
 * "Loading your cart…" rather than a notice, so there is no chip element in the static HTML to
 * measure. A probe node carrying the cart's own compiled classes is appended to the cart's own
 * band and measured against the cart's own stylesheet, which is the live rule rather than a
 * retyped copy of it, then removed.
 */
const READ_CHIP = hash => {
  const host = document.querySelector( '.ptb-layout' ) || document.body;
  const p = document.createElement( 'p' );
  p.className = `${hash} cart-status`;
  p.textContent = 'probe';
  host.appendChild( p );
  const c = getComputedStyle( p );
  const out = {
    chipBorderWidth: c.borderInlineStartWidth,
    chipBorderStyle: c.borderInlineStartStyle,
    chipBorderColor: c.borderInlineStartColor,
    chipBg: c.backgroundColor,
    chipColor: c.color,
    chipFontSize: c.fontSize,
    chipLineHeight: c.lineHeight,
    chipPadTop: c.paddingTop,
    chipOverflow: c.overflow,
  };
  p.className = `${hash} cart-status cart-status-firm`;
  const f = getComputedStyle( p );
  out.chipFirmBorderWidth = f.borderInlineStartWidth;
  out.chipFirmFontWeight = f.fontWeight;
  p.remove();
  return out;
};

/**
 * The quiet secondary's live values. Same shape of problem as the chip: /checkout/status/ ships
 * the rules but renders no button in the export, and they are scoped to a descendant of
 * `.co-card`, so a probe node is appended INSIDE the harvested card - which is the only place
 * those rules apply - measured, and removed.
 */
const READ_QUIET = hash => {
  const host = document.querySelector( '.co-card' );
  if ( !host ) return {};
  const b = document.createElement( 'button' );
  b.type = 'button';
  b.className = `${hash} co-btn co-btn-quiet`;
  b.textContent = 'probe';
  host.appendChild( b );
  const c = getComputedStyle( b );
  const out = {
    quietMinHeight: c.minHeight,
    quietBg: c.backgroundColor,
    quietColor: c.color,
    quietBorderWidth: c.borderTopWidth,
    quietBorderColor: c.borderTopColor,
    quietBorderRadius: c.borderTopLeftRadius,
    quietFontSize: c.fontSize,
    quietFontWeight: c.fontWeight,
  };
  b.remove();
  return out;
};

/** The same numbers, read inside a generated panel. Selector set depends on the panel's kind. */
const READ_FRAME = () => {
  const kind = document.documentElement.dataset.kind;
  const before = kind === 'before';
  const sel = before
    ? { h1: '.rh-head', shell: '.rh-shell', sub: '.rh-sub', layout: '.rh-layout' }
    : { h1: '.ptb-h1', shell: '.ptb-shell', sub: '.ptb-sub', layout: '.ptb-layout' };
  const st = ( s, p, pseudo ) => {
    const el = document.querySelector( s );
    return el ? getComputedStyle( el, pseudo || null )[ p ] : null;
  };
  const out = {
    panel: document.documentElement.dataset.panel,
    kind,
    vw: window.innerWidth, vh: window.innerHeight,
    h1FontSize: st( sel.h1, 'fontSize' ),
    h1FontWeight: st( sel.h1, 'fontWeight' ),
    h1LetterSpacing: st( sel.h1, 'letterSpacing' ),
    h1FontFamily: st( sel.h1, 'fontFamily' ),
    bandPadTop: st( sel.shell, 'paddingTop' ),
    subColor: st( sel.sub, 'color' ),
    subFontSize: st( sel.sub, 'fontSize' ),
    subLineHeight: st( sel.sub, 'lineHeight' ),
    subLetterSpacing: st( sel.sub, 'letterSpacing' ),
    layoutBoxSizing: st( sel.layout, 'boxSizing' ),
  };
  if ( before ) {
    out.markBeforeTransform = st( '.rh-mark', 'transform', '::before' );
    out.dotTransform = st( '.rh-mark-dot', 'transform' );
    out.cycleWidth = st( '.rh-cycle', 'width' );
  }
  if ( kind === 'ready' ) {
    const chip = document.querySelector( '.cart-status:not(.cart-status-firm)' );
    const firm = document.querySelector( '.cart-status-firm' );
    if ( chip ) {
      const c = getComputedStyle( chip );
      out.chipBorderWidth = c.borderInlineStartWidth;
      out.chipBorderStyle = c.borderInlineStartStyle;
      out.chipBorderColor = c.borderInlineStartColor;
      out.chipBg = c.backgroundColor;
      out.chipColor = c.color;
      out.chipFontSize = c.fontSize;
      out.chipLineHeight = c.lineHeight;
      out.chipPadTop = c.paddingTop;
      out.chipOverflow = c.overflow;
    }
    if ( firm ) {
      const f = getComputedStyle( firm );
      out.chipFirmBorderWidth = f.borderInlineStartWidth;
      out.chipFirmFontWeight = f.fontWeight;
    }
    const more = document.querySelector( '.ord-more' );
    if ( more ) {
      const q = getComputedStyle( more );
      out.quietMinHeight = q.minHeight;
      out.quietBg = q.backgroundColor;
      out.quietColor = q.color;
      out.quietBorderWidth = q.borderTopWidth;
      out.quietBorderColor = q.borderTopColor;
      out.quietBorderRadius = q.borderTopLeftRadius;
      out.quietFontSize = q.fontSize;
      out.quietFontWeight = q.fontWeight;
    }
  }
  if ( kind === 'signedout' ) {
    out.pillMinHeight = st( '.pill', 'minHeight' );
    out.pillBg = st( '.pill', 'backgroundColor' );
    out.pillBorderWidth = st( '.pill', 'borderTopWidth' );
    out.pillActionFontSize = st( '.pill-action', 'fontSize' );
    out.pillActionFontWeight = st( '.pill-action', 'fontWeight' );
  }
  return out;
};

/**
 * Text box sizes, for the font-fallback table. Measured on the SAME element with the webfont
 * available and again with it blocked - a before/after of one string, rather than a comparison
 * of two different strings, which would measure the copy rather than the font.
 */
const READ_BOXES = sel => {
  const box = s => {
    const el = document.querySelector( s );
    if ( !el ) return '—';
    const r = el.getBoundingClientRect();
    return `${Math.round( r.width )}×${Math.round( r.height )}`;
  };
  return {
    interAvailable: !!( document.fonts && document.fonts.check( '1em Inter' ) ),
    h1: box( sel.h1 ),
    sub: box( sel.sub ),
  };
};

/** What forced-colors does to the band and the chip. Chromium only - Playwright's option is. */
const READ_FORCED = sel => {
  const st = ( s, p ) => {
    const el = document.querySelector( s );
    return el ? getComputedStyle( el )[ p ] : null;
  };
  return {
    h1Color: st( sel.h1, 'color' ),
    shellBg: st( sel.shell, 'backgroundColor' ),
    chipBorderWidth: st( '.cart-status', 'borderInlineStartWidth' ),
    chipBorderColor: st( '.cart-status', 'borderInlineStartColor' ),
    chipBg: st( '.cart-status', 'backgroundColor' ),
    chipColor: st( '.cart-status', 'color' ),
  };
};

// ---------------------------------------------------------------------------------------------

/** Harvest one page: its style blocks keyed by id, plus named outerHTML fragments. */
async function harvest ( browser, base, url, pick ) {
  const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
  const page = await ctx.newPage();
  await gotoStable( page, `${base}${url}` );
  await page.waitForTimeout( 900 );
  const data = await page.evaluate( async picks => {
    const styles = Array.from( document.querySelectorAll( 'style' ) )
      .map( s => ( { id: s.id || '', css: s.textContent } ) );
    const hrefs = Array.from( document.querySelectorAll( 'link[rel="stylesheet"]' ) )
      .map( l => l.getAttribute( 'href' ) ).filter( h => h && h.startsWith( '/_next/' ) );
    const chunks = [];
    for ( const h of hrefs ) {
      try { chunks.push( await ( await fetch( h ) ).text() ); } catch { /* ignore */ }
    }
    const frags = {};
    for ( const [ name, selector ] of Object.entries( picks ) ) {
      const el = document.querySelector( selector );
      if ( !el ) { frags[ name ] = ''; continue; }
      const clone = el.cloneNode( true );
      // DROP THE WIDTH JAVASCRIPT WROTE ONTO THE PILL. Copying it would bake a measured value
      // into the harvest and make the "no JavaScript" shape unreachable; the settled panels
      // write the per-viewport width back deliberately, a few lines further down.
      clone.querySelectorAll( '.rh-cycle' ).forEach( n => n.style.removeProperty( 'width' ) );
      // The entrance classes are JavaScript's too, and the CSS default already is the finished
      // state, so a settled static panel must not carry them.
      clone.querySelectorAll( '.rh-layout,.ptb-layout' ).forEach( n => {
        n.classList.remove( 'is-armed' ); n.classList.remove( 'show' );
      } );
      if ( clone.classList ) { clone.classList.remove( 'is-armed' ); clone.classList.remove( 'show' ); }
      frags[ name ] = clone.outerHTML;
    }
    const cls = {};
    for ( const [ name, selector ] of Object.entries( picks ) ) {
      const el = document.querySelector( selector );
      cls[ name ] = el ? el.className.replace( /\bis-armed\b|\bshow\b/g, '' ).replace( /\s+/g, ' ' ).trim() : '';
    }
    return { styles, chunks: chunks.join( '\n' ), frags, cls };
  }, pick );
  await ctx.close();
  return data;
}

function jsxHashOf ( markup, what ) {
  const m = /class="([^"]*)"/.exec( markup || '' );
  const hash = ( m ? m[ 1 ] : '' ).split( /\s+/ ).find( c => c.startsWith( 'jsx-' ) );
  if ( !hash ) throw new Error( `ordersreview: could not read the styled-jsx scoping class from ${what}` );
  return hash;
}

( async () => {
  const t = await target();
  const browser = await launch();
  const failures = [];
  const checks = [];
  /** Equality, never a range. */
  const eq = ( panel, prop, got, want ) => {
    const ok = String( got ) === String( want );
    checks.push( { panel, prop, got, want, ok } );
    if ( !ok ) failures.push( `${panel}: ${prop} is ${got}, live page says ${want}` );
  };

  try {
    // ---- harvest -------------------------------------------------------------------------
    const H_ORDERS = await harvest( browser, t.base, '/orders/', {
      header: 'header', main: 'main.rh-shell', h1: '.rh-head',
    } );
    const H_BAND = await harvest( browser, t.base, '/account/sign-in/', {
      main: 'main.ptb-shell', h1: '.ptb-h1', sub: '.ptb-sub', pill: '.pill',
      layout: '.ptb-layout', top: '.ptb-top',
    } );
    const H_CART = await harvest( browser, t.base, '/cart/', { main: 'main.ptb-shell' } );
    const H_STATUS = await harvest( browser, t.base, '/checkout/status/', { main: 'main.ptb-shell' } );

    // THE REBUILD HAS LANDED, SO THIS GENERATOR IS SPENT - and saying so is the honest answer
    // rather than a harvest error that reads like a broken harness.
    //
    // `main.rh-shell` / `.rh-head` is the RotatingHero band of the UN-REBUILT page. FEAT-003
    // replaced it with PageTopBand, so those selectors are now absent from out/ by design. The
    // artifact this file wrote - docs/orders-review.html, committed at the mock commit - IS the
    // pre-rebuild evidence and is deliberately not regenerated: re-harvesting now would pick up
    // the rebuild in the "before" panels and demonstrate nothing. Design 6.0c, plan decision D3,
    // and the new-public-page skill's own rule that a mock regenerated after its fixes is void.
    //
    // Exit 0, because nothing is wrong: the page it mocked no longer exists.
    // The two halves are the whole distinction: a PRESENT header proves out/ built and the route
    // served, so an ABSENT rh-shell means the band changed rather than that the harvest failed.
    // Both absent is a real failure and still throws below.
    if ( !H_ORDERS.frags.main && H_ORDERS.frags.header )
    {
      console.log( 'ordersreview: /orders/ no longer serves the RotatingHero band this mock was' );
      console.log( '  taken from - the rebuild has landed. docs/orders-review.html stands as the' );
      console.log( '  PRE-REBUILD evidence and is not regenerated. Nothing to do.' );
      return;
    }
    if ( !H_ORDERS.frags.main || !H_ORDERS.frags.header ) throw new Error( 'ordersreview: failed to harvest /orders/ from out/' );
    if ( !H_BAND.frags.h1 || !H_BAND.frags.pill ) throw new Error( 'ordersreview: failed to harvest PageTopBand or PillButton from /account/sign-in/' );

    const rhHash = jsxHashOf( H_ORDERS.frags.h1, 'the harvested .rh-head' );
    const ptbHash = jsxHashOf( H_BAND.frags.h1, 'the harvested .ptb-h1' );
    const pillHash = jsxHashOf( H_BAND.frags.pill, 'the harvested .pill' );

    // TRAP 1, STRUCTURALLY. styled-jsx compiles `.rh-mark::before` to a (0,2,1) selector that
    // carries the hash. Assert the compiled form is really in the harvested CSS, so a panel can
    // never be built against rules a class short of the page's own.
    const ordersCss = H_ORDERS.styles.map( s => s.css ).join( '\n' );
    const compiledBefore = new RegExp( `\\.rh-mark\\.${rhHash}:+before` ).test( ordersCss );
    if ( !compiledBefore ) throw new Error( `ordersreview: no compiled .rh-mark.${rhHash}:before rule in the harvested CSS - the styled-jsx specificity assumption is wrong` );

    const cartCss = H_CART.styles.map( s => s.css ).join( '\n' );
    const chipRule = /\.cart-status\.(jsx-[a-z0-9]+)\{/.exec( cartCss );
    if ( !chipRule ) throw new Error( 'ordersreview: could not find the compiled .cart-status rule in /cart/ CSS' );
    const cartHash = chipRule[ 1 ];
    // THE QUIET SECONDARY SHIPS AS A DESCENDANT RULE, which is the second specificity trap of the
    // day: `.co-btn-quiet` alone matches nothing, because /checkout/status/ compiles it to
    // `.co-card.jsx-HASH .co-btn-quiet`. Putting the harvested card around the button to borrow
    // its rules would draw a card the proposal does not have, so the declarations are lifted out
    // of the built CSS at generation time and re-scoped onto .ord-more. Re-scoped CSS that
    // silently fails to apply is exactly what the panel assertions exist to catch, so the ready
    // panels compare .ord-more against a probe measured inside the real .co-card.
    const statusCss = H_STATUS.styles.map( s => s.css ).join( '\n' );
    const quietRule = /\.co-card\.(jsx-[a-z0-9]+)\s+\.co-btn-quiet\{/.exec( statusCss );
    if ( !quietRule ) throw new Error( 'ordersreview: could not find the compiled .co-card ... .co-btn-quiet rule in /checkout/status/ CSS' );
    const statusHash = quietRule[ 1 ];
    const lift = ( suffix, what ) => {
      const re = new RegExp( `\\.co-card\\.${statusHash}\\s+\\.co-btn${suffix}\\{([^}]*)\\}` );
      const m = re.exec( statusCss );
      if ( !m ) throw new Error( `ordersreview: could not lift the ${what} declarations from /checkout/status/ CSS` );
      return m[ 1 ];
    };
    const QUIET_CSS = `
  .ord-more{${lift( '', 'quiet secondary base' )}}
  .ord-more{${lift( '-quiet', 'quiet secondary surface' )}}
  .ord-more:hover{${lift( '-quiet:hover', 'quiet secondary hover' )}}
  .ord-more:focus-visible{${lift( ':focus-visible', 'quiet secondary focus ring' )}}
`;

    // TRAP 2. The reset is extracted from the built chunks, not retyped. Dropping the 500KB of
    // global CSS from the frames is what keeps this file a few hundred KB instead of megabytes,
    // and `*{box-sizing:border-box}` is the one rule in it that changes every box size on the
    // page if it goes missing.
    const chunks = H_ORDERS.chunks;
    const resetMatch = /\*\{[^}]*box-sizing:border-box[^}]*\}/.exec( chunks );
    if ( !resetMatch ) throw new Error( 'ordersreview: could not extract the global box-sizing reset from the built CSS' );
    const RESET = resetMatch[ 0 ];
    // The custom properties the public pages use. The Amplify UI chunk also ships a :root block,
    // and it is 120KB on its own, so blocks are taken only while they are small enough to be
    // ours rather than a design system's.
    const roots = [ ...chunks.matchAll( /(:root[^{}]*)\{([^}]*)\}/g ) ]
      .filter( m => m[ 2 ].length < 8000 ).map( m => `${m[ 1 ]}{${m[ 2 ]}}` ).join( '\n' );
    // The body font rule. The brand lockup in the header declares no family of its own and
    // inherits body, so without this the mock renders the logo in a serif while the live page
    // renders Inter.
    const bodyFonts = [ ...chunks.matchAll( /body\{[^}]*font-family:Inter[^}]*\}/g ) ].map( m => m[ 0 ] );
    if ( !bodyFonts.length ) throw new Error( 'ordersreview: could not extract the body font rule from the built CSS' );
    const BODY_FONT = bodyFonts[ bodyFonts.length - 1 ];

    // Style blocks, deduplicated by their styled-jsx id - /cart/ and /account/sign-in/ both
    // carry the header's and PageTopBand's blocks, byte for byte.
    const mergeStyles = sources => {
      const seen = new Map();
      for ( const src of sources ) for ( const s of src.styles ) {
        const key = s.id || s.css.slice( 0, 60 );
        if ( !seen.has( key ) ) seen.set( key, s.css );
      }
      return [ ...seen.values() ].join( '\n' );
    };
    const CSS_BEFORE = [ RESET, roots, BODY_FONT, mergeStyles( [ H_ORDERS ] ) ].join( '\n' );
    const CSS_AFTER = [ RESET, roots, BODY_FONT,
      mergeStyles( [ H_BAND, H_CART, H_STATUS, H_ORDERS ] ), PROPOSAL_CSS, QUIET_CSS ].join( '\n' );

    // ---- live measurements, per viewport ------------------------------------------------
    const LIVE = {};
    for ( const vp of VIEWPORTS ) {
      const ctx = await browser.newContext( { viewport: { width: vp.w, height: vp.h } } );
      const page = await ctx.newPage();

      await gotoStable( page, `${t.base}/orders/` );
      await page.waitForTimeout( 1200 );
      const rh = await page.evaluate( READ_RH );

      await gotoStable( page, `${t.base}/account/sign-in/` );
      await page.waitForTimeout( 900 );
      const ptb = await page.evaluate( READ_PTB );

      await gotoStable( page, `${t.base}/cart/` );
      await page.waitForTimeout( 600 );
      const chip = await page.evaluate( READ_CHIP, cartHash );

      await gotoStable( page, `${t.base}/checkout/status/` );
      await page.waitForTimeout( 600 );
      const quiet = await page.evaluate( READ_QUIET, statusHash );
      if ( !quiet.quietBg ) throw new Error( 'ordersreview: the quiet-secondary probe found no .co-card on /checkout/status/' );

      await ctx.close();
      LIVE[ vp.k ] = { rh, ptb, chip, quiet };
    }

    // ---- panel bodies -------------------------------------------------------------------
    // The before panel is the harvested page, settled: the server-rendered first word already
    // carries .on, so all that is missing is the width the measuring effect writes.
    //
    // THE WIDTH BAKED IN IS THE LIVE COMPUTED WIDTH OF THE PILL, NOT THE WIDTH OF THE WORD, and
    // the difference is a real defect rather than a rounding detail. RotatingHero measures
    // offsetWidth once on mount and never again, so the number it writes is taken with the
    // fallback font still in place; when Inter arrives the word grows and nothing re-measures.
    // Measured on this page the pill is held at the pre-font width while the word now needs more,
    // so the live page clips it. Baking the word's width instead would quietly show the pill
    // FIXED in a panel labelled "as it ships today", which is the lie this whole file exists to
    // avoid - and it is the first thing the panel assertions caught.
    const settledBefore = width => sub(
      H_ORDERS.frags.main,
      /(<span class="[^"]*\brh-cycle\b[^"]*")/,
      `$1 style="width:${width}"`,
      'baking the measured pill width into the before panel'
    );

    // The proposal's band: the harvested PageTopBand, with this page's heading and sub-line.
    const bandH1 = sub( H_BAND.frags.h1, />[\s\S]*<\/h1>/, `>${esc( COPY.h1 )}</h1>`, 'the proposal h1 text' );
    const bandSub = sub( H_BAND.frags.sub, />[\s\S]*<\/p>/, `>${esc( COPY.sub )}</p>`, 'the proposal sub-line text' );
    const band = children => `<main class="${H_BAND.cls.main}" aria-label="${esc( COPY.h1 )}">`
      + `<div class="${H_BAND.cls.layout}"><div class="${H_BAND.cls.top}">${bandH1}${bandSub}</div>`
      + children + '</div></main>';

    // The sign-in control: PillButton as an anchor, which is how the page mounts it. Harvested
    // markup, retagged and relabelled - the component renders the action alone, so the visible
    // string and the accessible name are the same one string.
    const pill = ( () => {
      let p = H_BAND.frags.pill;
      p = sub( p, /^<button[^>]*?>/, `<a href="/account/sign-in/?return=/orders/" class="${pillHash} pill">`, 'retagging the pill to an anchor' );
      p = sub( p, /<\/button>$/, '</a>', 'closing the retagged pill' );
      p = sub( p, />[^<]*<\/span>/, `>${esc( COPY.pill )}</span>`, 'the pill action label' );
      return p;
    } )();

    const chipMarkup = row => {
      const cls = `${cartHash} cart-status${row.firm ? ' cart-status-firm' : ''}`;
      const body = row.line ? `${esc( row.status )} — ${esc( row.line )}` : esc( row.status );
      return `<p class="${cls}" role="status">${body}</p>`;
    };
    const rowMarkup = row => '<li class="ord-row">'
      + `<p class="ord-no" data-wc-no-translate="true">${esc( row.no )}</p>`
      + '<dl class="ord-dl">'
      + `<dt class="ord-dt">Date</dt><dd class="ord-dd">${esc( row.date )}</dd>`
      + `<dt class="ord-dt">Amount</dt><dd class="ord-dd" data-wc-no-translate="true">${esc( row.amount )}</dd>`
      + '</dl>'
      + chipMarkup( row )
      + '</li>';

    const readyChildren = '<div class="ord-wrap">'
      + `<h2 class="ord-h2">${esc( COPY.ordersHeading )}</h2>`
      + `<ul class="ord-list">${ROWS.map( rowMarkup ).join( '' )}</ul>`
      + `<button type="button" class="${statusHash} co-btn co-btn-quiet ord-more">${esc( COPY.more )}</button>`
      + '</div>';
    const signedOutChildren = '<div class="ord-wrap">'
      + `<p class="ord-p">${esc( COPY.signedOut )}</p>`
      + `<div class="ord-pill">${pill}</div>`
      + '</div>';

    const frameDoc = ( panel, kind, css, body ) =>
      `<!doctype html><html lang="en" data-panel="${panel}" data-kind="${kind}"><head>`
      + '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      + '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
      + `<style>html,body{margin:0;background:#fff}${css}</style></head><body>${body}</body></html>`;

    // Panels, declared once and used for both the emitted markup and the assertions.
    const PANELS = [];
    for ( const vp of VIEWPORTS ) {
      PANELS.push( {
        key: `before-${vp.k}`, kind: 'before', vp,
        doc: frameDoc( `before-${vp.k}`, 'before', CSS_BEFORE,
          H_ORDERS.frags.header + settledBefore( LIVE[ vp.k ].rh.cycleWidth ) ),
      } );
    }
    for ( const vp of VIEWPORTS ) {
      PANELS.push( {
        key: `ready-${vp.k}`, kind: 'ready', vp,
        doc: frameDoc( `ready-${vp.k}`, 'ready', CSS_AFTER, H_ORDERS.frags.header + band( readyChildren ) ),
      } );
    }
    for ( const vp of VIEWPORTS.slice( 0, 2 ) ) {
      PANELS.push( {
        key: `signedout-${vp.k}`, kind: 'signedout', vp,
        doc: frameDoc( `signedout-${vp.k}`, 'signedout', CSS_AFTER, H_ORDERS.frags.header + band( signedOutChildren ) ),
      } );
    }

    // 1:1, never scaled, and no max-width anywhere near the frame: a shrunk iframe reports a
    // smaller viewport and every vw unit and media query inside it resolves wrong.
    const frameHtml = p =>
      `<div class="shot" style="width:${p.vp.w}px;height:${p.vp.h}px">`
      + `<iframe title="${esc( p.key )}" scrolling="no" width="${p.vp.w}" height="${p.vp.h}" `
      + `style="width:${p.vp.w}px;height:${p.vp.h}px" srcdoc="${p.doc.replace( /"/g, '&quot;' )}"></iframe></div>`;
    const panelBlock = p => `<div class="pnl"><div class="pnlhead"><span class="collab ${p.kind === 'before' ? 'c-b' : 'c-a'}">`
      + `${p.kind === 'before' ? 'unmodified — as it ships today' : p.kind === 'ready' ? 'proposal — signed in' : 'proposal — signed out'}`
      + `</span><span class="sel">${esc( p.vp.label )} · 1:1</span></div>${frameHtml( p )}</div>`;

    const STAMP = new Date().toISOString().replace( 'T', ' ' ).slice( 0, 16 ) + 'Z';
    const pick = ( obj, keys ) => Object.fromEntries( keys.filter( k => k in obj ).map( k => [ k, obj[ k ] ] ) );
    const BAND_KEYS = [ 'h1FontSize', 'h1FontWeight', 'h1LetterSpacing', 'h1FontFamily', 'bandPadTop',
      'subColor', 'subFontSize', 'subLineHeight', 'subLetterSpacing', 'layoutBoxSizing' ];
    const RH_KEYS = [ 'markBeforeTransform', 'dotTransform', 'cycleWidth' ];
    const CHIP_KEYS = [ 'chipBorderWidth', 'chipBorderStyle', 'chipBorderColor', 'chipBg', 'chipColor',
      'chipFontSize', 'chipLineHeight', 'chipPadTop', 'chipOverflow', 'chipFirmBorderWidth', 'chipFirmFontWeight' ];
    const PILL_KEYS = [ 'pillMinHeight', 'pillBg', 'pillBorderWidth', 'pillActionFontSize', 'pillActionFontWeight' ];
    const QUIET_KEYS = [ 'quietMinHeight', 'quietBg', 'quietColor', 'quietBorderWidth', 'quietBorderColor',
      'quietBorderRadius', 'quietFontSize', 'quietFontWeight' ];

    const expectFor = p => {
      const live = LIVE[ p.vp.k ];
      if ( p.kind === 'before' ) return pick( live.rh, [ ...BAND_KEYS, ...RH_KEYS ] );
      if ( p.kind === 'ready' ) {
        return { ...pick( live.ptb, BAND_KEYS ), ...pick( live.chip, CHIP_KEYS ), ...pick( live.quiet, QUIET_KEYS ) };
      }
      return { ...pick( live.ptb, BAND_KEYS ), ...pick( live.ptb, PILL_KEYS ) };
    };

    // ---- write the file, with placeholders for what is measured from the file itself ------
    const notes = `
<section class="band">
  <div class="bhead"><span class="tag">SCOPE</span><h2>What is in this review, and what is not</h2></div>
  <div class="step">
    <p>Shown: the top band and the page below it, for the two states that have a layout — signed out, and
    signed in with orders. The band moves from <code>RotatingHero</code> to <code>PageTopBand</code>, which drops the
    word that rotates every 2400ms for as long as the page is open, and drops the four invented cycle words
    that currently describe a tracker this page is not.</p>
    <p>Not shown, deliberately rather than by omission:</p>
    <ul>
      <li><b>The details card.</b> It is <code>CheckoutIdentityCard</code>, already shipping on <code>/cart/</code>, and it
      sits between the band and the list. The cart's export server-renders <i>“Loading your cart…”</i>, so the card's
      markup is not in <code>out/</code> and cannot be harvested. A hand-pasted copy would be true exactly once, so it is
      described here instead of drawn wrongly.</li>
      <li><b>loading, empty and error.</b> Each is one line of text inside the same band, so a panel of each
      would show the band four more times and the line once. They are listed in the copy table instead.</li>
      <li><b>Hover, focus and the entrance animation.</b> Panels are static by design. The entrance is opt-in in
      CSS — the settled state is the default — so what is drawn here is what a visitor with no JavaScript,
      a blocked bundle or a reduced-motion preference sees.</li>
    </ul>
  </div>
</section>`;

    const copyTable = `
<section class="band">
  <div class="bhead"><span class="tag">COPY</span><h2>Every visible string</h2></div>
  <div class="step">
    <table>
      <tr><th>Where</th><th>Text</th></tr>
      <tr><td><code>h1</code></td><td>${esc( COPY.h1 )}</td></tr>
      <tr><td>sub</td><td>${esc( COPY.sub )}</td></tr>
      <tr><td>signed out</td><td>${esc( COPY.signedOut )}</td></tr>
      <tr><td>signed-out pill</td><td>${esc( COPY.pill )}</td></tr>
      <tr><td>loading</td><td>Loading your orders…</td></tr>
      <tr><td>orders heading</td><td>${esc( COPY.ordersHeading )}</td></tr>
      <tr><td>empty heading</td><td>No orders yet</td></tr>
      <tr><td>empty body</td><td>Anything you buy from us will show up here with its payment status.</td></tr>
      <tr><td>empty aside</td><td>Ordered over WhatsApp? Those are not listed here yet — contact us and we will check.</td></tr>
      <tr><td>session expired</td><td>Your sign-in has expired. Sign in again to see your orders.</td></tr>
      <tr><td>rate limited</td><td>Too many requests. Wait a moment and try again.</td></tr>
      <tr><td>unavailable</td><td>We could not load your orders just now. Try again shortly.</td></tr>
      <tr><td>amount unreadable</td><td>Amount unavailable</td></tr>
      <tr><td>status unknown</td><td>Status unavailable</td></tr>
      <tr><td>more</td><td>${esc( COPY.more )}</td></tr>
    </table>
    <p class="sm mut">The pill reads <b>Sign in on WhatsApp</b> and not “Send OTP on WhatsApp”: the control navigates to
    <code>/account/sign-in/?return=/orders/</code> and sends nothing. The literal string lives where a code is
    really sent.</p>
  </div>
</section>`;

    const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>/orders/ — the current page, and the one proposal</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{--ink:#1a1a1a;--mut:rgba(0,0,0,.55);--lime:#d1f470;--grn:#1a3a2a;--line:#e3e3e3;--red:#b42318;--amb:#a05a00}
  *{box-sizing:border-box}
  body{margin:0;background:#fafafa;color:var(--ink);font-size:15px;line-height:1.55;
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
  .wrap{max-width:1560px;margin:0 auto;padding:30px 22px 110px}
  h1{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;margin:0 0 10px}
  h2{font-size:24px;font-weight:700;letter-spacing:-.4px;margin:0}
  h3{font-size:16.5px;font-weight:700;letter-spacing:-.2px;margin:0 0 8px}
  p{margin:0 0 10px}
  .lede{font-size:18px;max-width:90ch}
  .mut{color:var(--mut)} .sm{font-size:13.5px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.87em;background:#f0f0f0;padding:1px 5px;border-radius:4px}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 22px}
  .card.brief{border-left:4px solid var(--lime)}
  .card.warn{border-left:4px solid var(--amb)}
  section.band{margin:0 0 26px;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .bhead{padding:17px 22px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
  .tag{display:inline-flex;align-items:center;justify-content:center;padding:3px 9px;border-radius:6px;
    background:var(--grn);color:var(--lime);font-weight:800;font-size:12px;letter-spacing:.06em;flex:none}
  .sel{font-size:13px;color:var(--mut);font-family:ui-monospace,Menlo,monospace}
  .step{padding:19px 22px;border-top:1px solid #f0f0f0}
  .step:first-child{border-top:0}
  table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 0}
  th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
  th{background:#f7f7f7;font-weight:600}
  td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  td.ok{color:#1f6f3d;font-weight:700} td.bad{color:var(--red);font-weight:700}
  ol,ul{margin:6px 0 10px;padding-left:20px} li{margin:5px 0}
  .collab{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;padding:2px 7px;border-radius:4px;display:inline-block}
  .c-b{background:#eef1f4;color:#44546a} .c-a{background:#eefaf0;color:#1f6f3d}
  .pnl{margin:0 0 18px}
  .pnlhead{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 8px}
  .shot{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
  .shot iframe{border:0;display:block}
  .frames{overflow-x:auto;padding-bottom:6px}
  footer.pg{color:var(--mut);font-size:13px;border-top:1px solid var(--line);padding-top:18px;margin-top:34px}
</style>
</head>
<body>
<div class="wrap">

<h1>/orders/ — the current page, and the one proposal</h1>
<p class="lede">Generated from the real static export in <code>out/</code>. Every panel is a real-width iframe at 1:1 with
static markup and no JavaScript; the settled state is written into the markup, so the panel labelled
<i>as it ships today</i> shows the page a visitor actually gets rather than an un-hydrated one.</p>

<div class="card brief">
  <h3>Build stamp</h3>
  <p class="sm"><b>${STAMP}</b> · generated by <code>node tools/browser/ordersreview.js</code> ·
  harvested from <code>out/orders/</code>, <code>out/account/sign-in/</code>, <code>out/cart/</code> and
  <code>out/checkout/status/</code>. If this stamp looks old, you are reading a cached copy — that is not a defect.</p>
</div>

<div class="card warn">
  <h3>This is the pre-rebuild mock. Do not regenerate it.</h3>
  <p class="sm">The <i>before</i> panels are harvested from the built export, so running this generator again after
  <code>src/pages/orders.tsx</code> is rebuilt would harvest the rebuild into them and the comparison would show
  nothing. This file is the evidence as of the stamp above and is committed deliberately unchanged.</p>
</div>

${notes}

<section class="band">
  <div class="bhead"><span class="tag">BEFORE</span><h2>The current page, unmodified</h2>
    <span class="sel">harvested from out/orders/</span></div>
  <div class="step">
    <p class="sm mut">The band is <code>RotatingHero</code>: an eyebrow badge, “Track your” plus a word that rotates
    through <i>order / delivery / request / booking</i> every 2400ms, a sub-line, then a section whose only action is
    a link to <code>/contact/</code>. There is no order data on the page at all.</p>
    <p class="sm mut"><b>The rotating pill is clipped on the live page, and the panels reproduce it.</b> The width is
    measured once on mount, which happens while the fallback font is still in place, and nothing re-measures when
    Inter arrives. Measured here:
    ${VIEWPORTS.map( v => `<code>${v.w}px</code>: pill ${esc( LIVE[ v.k ].rh.cycleWidth )}, word needs ${LIVE[ v.k ].rh.w0}px` ).join( ' · ' )}.
    The baked width is the pill's live computed width, not the word's, so these frames show the clip rather than a
    repair. The proposal removes the pill entirely, so the defect goes with it rather than being fixed.</p>
    <div class="frames">${PANELS.filter( p => p.kind === 'before' ).map( panelBlock ).join( '' )}</div>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">PROPOSAL</span><h2>Signed in, with orders</h2>
    <span class="sel">PageTopBand + the order list</span></div>
  <div class="step">
    <p class="sm mut">Band, then <code>Order history</code>, then one row per order carrying the order number, the date,
    the amount and the status. The chip is <code>/cart/</code>'s own <code>.cart-status</code> treatment, harvested:
    a lime tint with a 3px inline-start edge, stepping to 4px and weight 700 for the firmer variant. No red, and
    colour is never the only cue — every row says its status in words.</p>
    <div class="frames">${PANELS.filter( p => p.kind === 'ready' ).map( panelBlock ).join( '' )}</div>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">PROPOSAL</span><h2>Signed out — the state a crawler and a no-JS reader see</h2>
    <span class="sel">the static export of /orders/</span></div>
  <div class="step">
    <p class="sm mut">This is what ships in <code>out/orders/index.html</code> after the rebuild: the band, one line
    saying what to do, and <code>PillButton</code> as an anchor to <code>/account/sign-in/?return=/orders/</code>. No
    personal data, and no “Loading…” as the headline.</p>
    <div class="frames">${PANELS.filter( p => p.kind === 'signedout' ).map( panelBlock ).join( '' )}</div>
  </div>
</section>

${copyTable}

<section class="band">
  <div class="bhead"><span class="tag">NUMBERS</span><h2>forced-colors and font fallback — measured, not drawn</h2></div>
  <div class="step">
    <p class="sm mut">Both resolve against the operating system, so this machine's rendering is not the reader's. A
    confident panel would be worse than a table. <code>forcedColors</code> is a Chromium-only option in Playwright, so
    these are Chromium numbers and the Firefox equivalent is unverified.</p>
    <!--FORCED-->
    <!--FALLBACK-->
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">ASSERTED</span><h2>Every panel, checked inside the frame</h2></div>
  <div class="step">
    <p class="sm mut">Read with <code>getComputedStyle</code> inside each iframe and compared for <b>equality</b> with the
    same property measured on the live export at the same viewport. Equality rather than a range: a range hides
    fidelity drift, an equality check fails the moment a panel stops matching the page.</p>
    <!--ASSERTIONS-->
  </div>
</section>

<footer class="pg">
  Re-generate: <b>do not.</b> This is the pre-rebuild evidence for <code>src/pages/orders.tsx</code>; see the note at the top.<br>
  Gate for the rebuilt page: <code>node tools/browser/ordersprobe.js</code> ·
  Fonts load from Google; everything else here is self-contained. No images beyond the header's own logo.
</footer>
</div>
</body>
</html>
`;

    fs.mkdirSync( path.dirname( OUT_FILE ), { recursive: true } );
    fs.writeFileSync( OUT_FILE, html );

    // ---- assert the mock, inside every frame ---------------------------------------------
    const ctx = await browser.newContext( { viewport: { width: 1440, height: 1000 } } );
    const page = await ctx.newPage();
    await gotoStable( page, `file://${OUT_FILE}` );
    await page.waitForTimeout( 1200 );

    const readAllFrames = async pg => {
      const found = {};
      for ( const f of pg.frames() ) {
        if ( f === pg.mainFrame() ) continue;
        try {
          const r = await f.evaluate( READ_FRAME );
          if ( r && r.panel ) found[ r.panel ] = r;
        } catch { /* a frame still settling is retried by the caller */ }
      }
      return found;
    };
    let frames = await readAllFrames( page );
    if ( Object.keys( frames ).length < PANELS.length ) {
      await page.waitForTimeout( 1500 );
      frames = await readAllFrames( page );
    }

    for ( const p of PANELS ) {
      const got = frames[ p.key ];
      if ( !got ) { failures.push( `${p.key}: panel did not load, nothing could be measured` ); continue; }
      // A real-width frame, not a scaled div. If this is wrong every clamp() below it is wrong.
      eq( p.key, 'viewport width', got.vw, p.vp.w );
      eq( p.key, 'viewport height', got.vh, p.vp.h );
      const want = expectFor( p );
      for ( const [ k, v ] of Object.entries( want ) ) eq( p.key, k, got[ k ], v );
    }

    // ---- the two number tables, measured from the live page and from this file ------------
    const RH_SEL = { h1: '.rh-head', shell: '.rh-shell', sub: '.rh-sub' };
    const PTB_SEL = { h1: '.ptb-h1', shell: '.ptb-shell', sub: '.ptb-sub' };

    const fcCtx = await browser.newContext( { viewport: { width: 1280, height: 900 }, forcedColors: 'active' } );
    const fcPage = await fcCtx.newPage();
    await gotoStable( fcPage, `${t.base}/orders/` );
    await fcPage.waitForTimeout( 600 );
    const fcLive = await fcPage.evaluate( READ_FORCED, RH_SEL );
    await gotoStable( fcPage, `file://${OUT_FILE}` );
    await fcPage.waitForTimeout( 1200 );
    let fcMock = null;
    for ( const f of fcPage.frames() ) {
      if ( f === fcPage.mainFrame() ) continue;
      const which = await f.evaluate( () => document.documentElement.dataset.panel ).catch( () => null );
      if ( which === 'ready-w1280' ) { fcMock = await f.evaluate( READ_FORCED, PTB_SEL ); break; }
    }
    await fcCtx.close();

    // Font fallback: the same two elements measured with the webfont available and again with
    // every request to Google Fonts aborted. A URL predicate rather than a glob, because the
    // glob form silently matches nothing and the table then reports a fallback it never tested.
    const measureBoxes = async blocked => {
      const c = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
      if ( blocked ) {
        await c.route(
          url => url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com',
          r => r.abort()
        );
      }
      const pg = await c.newPage();
      await gotoStable( pg, `${t.base}/orders/` );
      await pg.waitForTimeout( 800 );
      const live = await pg.evaluate( READ_BOXES, RH_SEL );
      await gotoStable( pg, `file://${OUT_FILE}` );
      await pg.waitForTimeout( 1500 );
      let mock = null;
      for ( const f of pg.frames() ) {
        if ( f === pg.mainFrame() ) continue;
        const which = await f.evaluate( () => document.documentElement.dataset.panel ).catch( () => null );
        if ( which === 'ready-w1280' ) { mock = await f.evaluate( READ_BOXES, PTB_SEL ); break; }
      }
      await c.close();
      return { live, mock };
    };
    const fbWith = await measureBoxes( false );
    const fbWithout = await measureBoxes( true );
    await ctx.close();

    const row = ( label, a, b ) => `<tr><td>${esc( label )}</td><td class="n">${esc( a === null || a === undefined ? '—' : a )}</td><td class="n">${esc( b === null || b === undefined ? '—' : b )}</td></tr>`;
    const forcedTable = `
    <h3>forced-colors: active (Chromium, 1280×900)</h3>
    <table>
      <tr><th>Property</th><th>current page, live</th><th>proposal, in the panel</th></tr>
      ${row( 'h1 colour', fcLive.h1Color, fcMock && fcMock.h1Color )}
      ${row( 'band background', fcLive.shellBg, fcMock && fcMock.shellBg )}
      ${row( 'status chip inline-start width', fcLive.chipBorderWidth || 'no chip on the current page', fcMock && fcMock.chipBorderWidth )}
      ${row( 'status chip inline-start colour', fcLive.chipBorderColor || '—', fcMock && fcMock.chipBorderColor )}
      ${row( 'status chip background', fcLive.chipBg || '—', fcMock && fcMock.chipBg )}
      ${row( 'status chip text colour', fcLive.chipColor || '—', fcMock && fcMock.chipColor )}
    </table>
    <p class="sm mut">The chip keeps a measurable edge width under forced colours, which is the point of stepping the
    edge and the weight rather than changing hue: a luminance-and-weight step survives a palette the page does not
    control, and the status is stated in words regardless.</p>`;
    // If the blocked run measures identically, the generating machine is resolving Inter from its
    // own installed fonts and the table is not evidence about a reader who has none. Say so in
    // the file rather than letting a reader assume otherwise.
    const sameAll = fbWith.live.h1 === fbWithout.live.h1 && fbWith.live.sub === fbWithout.live.sub
      && fbWith.mock && fbWithout.mock && fbWith.mock.h1 === fbWithout.mock.h1;
    const fallbackTable = `
    <h3>Font fallback — the same text with Inter, and with every Google Fonts request aborted</h3>
    <table>
      <tr><th>Measurement</th><th>Inter available</th><th>webfont blocked</th></tr>
      ${row( 'current page h1 box', fbWith.live.h1, fbWithout.live.h1 )}
      ${row( 'current page sub-line box', fbWith.live.sub, fbWithout.live.sub )}
      ${row( 'proposal h1 box (panel)', fbWith.mock && fbWith.mock.h1, fbWithout.mock && fbWithout.mock.h1 )}
      ${row( 'proposal sub-line box (panel)', fbWith.mock && fbWith.mock.sub, fbWithout.mock && fbWithout.mock.sub )}
    </table>
    <p class="sm mut">The boxes are the signal, and <code>document.fonts.check('1em Inter')</code> is not: it answered
    <b>${esc( fbWith.live.interAvailable )}</b> with the webfont available and <b>${esc( fbWithout.live.interAvailable )}</b>
    with every request to it aborted, because the API answers for a name it can substitute rather than for the face it
    actually loaded. A boolean that cannot tell those apart is worse than the measurement, so it is not used as one.</p>
    <p class="sm mut">Rows are the same element measured twice, not two different strings — comparing the current h1
    against the proposal's would measure the copy rather than the typeface. Both the band and the page's own rungs
    <i>declare</i> the family rather than inheriting it, so the fallback is the declared stack and not whatever an auth
    library happens to set on <code>body</code>.</p>
    ${sameAll ? `<p class="sm mut"><b>Read this row carefully.</b> The blocked run measures identically to the
    unblocked one on this machine, which means the generating machine resolves <code>Inter</code> from its own installed
    fonts — so these numbers are <b>not</b> evidence about a reader who has no Inter at all. That is the reason this
    section is a table and not a panel: the fallback resolves against the operating system, and this one is not the
    reader's. Unverified, and stated rather than implied.</p>` : '' }`;

    const assertRows = checks.map( c =>
      `<tr><td><code>${esc( c.panel )}</code></td><td>${esc( c.prop )}</td><td class="n">${esc( c.want )}</td><td class="n">${esc( c.got )}</td><td class="${c.ok ? 'ok' : 'bad'}">${c.ok ? 'equal' : 'DRIFT'}</td></tr>` ).join( '' );
    const assertTable = `
    <p class="sm"><b>${checks.filter( c => c.ok ).length} of ${checks.length}</b> equality checks passed across
    ${PANELS.length} panels.${failures.length ? ' <b>This file was written with drift present.</b>' : ''}</p>
    <table>
      <tr><th>Panel</th><th>Property</th><th>Live page</th><th>In the panel</th><th>Result</th></tr>
      ${assertRows}
    </table>`;

    const finalHtml = html
      .replace( '<!--FORCED-->', forcedTable )
      .replace( '<!--FALLBACK-->', fallbackTable )
      .replace( '<!--ASSERTIONS-->', assertTable );

    // No JavaScript anywhere in the published artifact, panels included.
    if ( /<script/i.test( finalHtml ) ) throw new Error( 'ordersreview: the emitted page contains a <script> - the panels must be static' );
    fs.writeFileSync( OUT_FILE, finalHtml );

    const frameCount = ( finalHtml.match( /<iframe/g ) || [] ).length;
    console.log( `wrote ${path.relative( REPO, OUT_FILE )}  (${( fs.statSync( OUT_FILE ).size / 1024 ).toFixed( 0 )} KB)` );
    console.log( `  stamp: ${STAMP}` );
    console.log( `  panels: ${frameCount} real-width iframes at 1:1 — ${VIEWPORTS.map( v => `${v.w}x${v.h}` ).join( ', ' )}` );
    console.log( `  harvested: rh=${rhHash} ptb=${ptbHash} pill=${pillHash} chip=${cartHash} quiet=${statusHash}` );
    console.log( `  h1 @1280: ${LIVE.w1280.rh.h1FontSize} before / ${LIVE.w1280.ptb.h1FontSize} after · band padding ${LIVE.w1280.rh.bandPadTop} / ${LIVE.w1280.ptb.bandPadTop}` );
    console.log( `  chip: ${LIVE.w1280.chip.chipBorderWidth} ${LIVE.w1280.chip.chipBorderStyle} ${LIVE.w1280.chip.chipBorderColor} on ${LIVE.w1280.chip.chipBg}` );
    console.log( `  equality checks: ${checks.filter( c => c.ok ).length}/${checks.length} passed` );

    if ( failures.length ) {
      console.error( `\n${failures.length} panel(s) drifted from the live page:` );
      for ( const f of failures ) console.error( `  - ${f}` );
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
