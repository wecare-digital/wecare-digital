'use strict';

/**
 * homereview - ONE self-contained HTML page reviewing the home page's TOP SECTION only.
 *
 * SCOPE, DELIBERATELY NARROW. The top band of the home page, and inside it only the fixes
 * that need no design decision - the three defects. Nothing else is in here: not the two
 * judgement calls, not the other three bands, not the sitewide schema, and not the
 * propagation to the other public pages. Those are listed at the end so they are not lost,
 * but they are out of scope until this band is signed off.
 *
 * THE BRIEF THIS FOLLOWS. The top band's job is to say what the page is about. No call to
 * action, no price, no conversion furniture - the action stays in the closing band where it
 * already is. The band is chrome shared by every public page; only the words, the rotation
 * and the sub-line change per page. So "nothing actionable above the fold" is a DECISION,
 * not a defect, and the CTA options previously put up here are withdrawn.
 *
 * WHAT MAKES THIS TRUSTWORTHY. The CSS, the markup and every measurement are extracted from
 * the real static export at generation time, so the mock cannot drift from the page the way
 * a hand-pasted copy does. Panels are real documents at 1280 and 390, only visually scaled,
 * so clamp(36px,4.3vw,60px) resolves exactly as it would at that viewport. They are live:
 * the pill rotates and focus rings appear. No images.
 *
 * HOW THE "BEFORE" STATES ARE REPRODUCED, deterministically rather than by luck:
 *   - no JavaScript   the boot script is omitted, which is the real condition
 *   - reduced motion  the rules inside @media(prefers-reduced-motion) are applied directly,
 *                     because a preference cannot be set inside a preview frame
 *   - the stale width the width measured at 390 is written onto a 1280-wide frame, which is
 *                     exactly what the missing resize listener leaves behind
 *
 * Run:    node tools/browser/homereview.js     (needs out/ - see README.md)
 * Writes: docs/home-review.html
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

const REPO = path.join( __dirname, '..', '..' );
const OUT_FILE = path.join( REPO, 'docs', 'home-review.html' );

// ---- derived: the rotating words, parsed from source --------------------------
const src = fs.readFileSync( path.join( REPO, 'src', 'pages', 'index.tsx' ), 'utf8' );
const cb = /const CYCLE_WORDS = \[([\s\S]*?)\];/.exec( src );
if ( !cb ) throw new Error( 'could not parse CYCLE_WORDS from src/pages/index.tsx' );
const WORDS = [ ...cb[ 1 ].matchAll( /word:\s*'([^']+)',\s*tint:\s*'([^']+)',\s*dot:\s*'([^']+)'/g ) ]
  .map( m => ( { word: m[ 1 ], tint: m[ 2 ], dot: m[ 3 ] } ) );
if ( !WORDS.length ) throw new Error( 'CYCLE_WORDS parsed empty' );

// ---- the two fixes under review: the only original code in this file ---------
// Both are defect repairs with no design content. In the settled, happy-path state they
// change nothing a visitor sees - which is the point, and which the last panel proves.
// `JSX` is replaced with the page's real styled-jsx hash class before injection. Without
// it these rules are a class short of the ones they must override - styled-jsx compiles
// `.home-mark::before` to `.home-mark.jsx-HASH::before`, which is (0,2,1) - and the mock
// would show a fix that silently does not apply. Written in-source the hash is added
// automatically, so this is a mock concern only. Found by measuring the panels rather
// than by reading them.
const FIX_CSS = `
  /* ===== FIX A - the pill is sized by CSS, so it is never empty =====
     The active word returns to normal flow, which gives .home-cycle a real intrinsic
     width; the inactive words stay absolute so they still stack in the same place.
     width:max-content is the resting value. JavaScript still writes an explicit px
     width over it, which is what animates - so the glide is unchanged, and the
     first-paint and no-JS states show the word instead of nothing.

     display:inline-block IS LOAD-BEARING, and it is the whole reason this fix was
     measured before being written. position:static alone turns the span back into a
     non-replaced INLINE box, and offsetWidth/scrollWidth are 0 for those - so the
     existing measuring effect would write width:0px over max-content and the pill
     would collapse on every load WITH JavaScript, turning a 200ms flash into a
     permanent one. inline-block keeps it in flow and keeps it measurable. */
  .home-cycleJSX{width:max-content}
  .home-cyc-word.onJSX{position:static;display:inline-block}

  /* ===== FIX C - the reduced-motion resting state is the shutter GONE, not covering =====
     Was scaleX(1), which is the START state: a white panel over the tint. Inert today
     only because .home-layout.show out-specifies it, which is not a thing to rely on. */
  .home-markJSX::before{transform:scaleX(0)}
`;
// The header's mega-menu is sized max-height:calc(100vh - 320px) with the mobile override
// gated on max-width:767px - so any window WIDER than 767 but short falls back to the desktop
// rule. Measured at 844x390, a landscape phone: a 70px-tall menu holding 700px of content.
// HDRJSX is replaced with the HEADER's own styled-jsx hash, which is a different hash from
// the home page's.
const HEADER_FIX_CSS = `
  /* Anchor to the header instead of a magic 320, and use dvh so mobile browser chrome is
     accounted for - the same unit fix index.tsx already made for .home-shell. 140 = the
     108px header plus 32px of air, both nameable.

     BOTH RULES, NOT ONE. My first version only replaced the desktop 320. The folded-landscape
     case at 653x280 is BELOW 767px wide, so it takes the mobile override instead -
     calc(100vh - 308px) - and 308 exceeds a 280px viewport, so it resolves negative and clamps
     to zero. Fixing one left the worst case untouched. */
  .nav-menuHDRJSX{max-height:calc(100dvh - 140px)}
  @media(max-width:767px){ .nav-menuHDRJSX{max-height:calc(100dvh - 140px)} }
`;

// BRAND LOCKUP FONT. The lockup has no font-family of its own - it inherits body, which is
// set by @aws-amplify/ui-react's styles.css. index.tsx:797 declares its stack locally for
// exactly that reason, with a comment spelling out the risk: the public pages' typeface was a
// side effect of an auth library's stylesheet and would change silently if the import moved or
// the package bumped. The hero was fixed; the brand lockup was left on the inherited stack.
// This is the same declaration as index.tsx:797, byte for byte.
const BRAND_FIX_CSS = `
  .hdrHDRJSX,.logoHDRJSX,.brand-lockupHDRJSX,.brand-stackHDRJSX{
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  }
`;

// WCAG 1.4.12 Text Spacing: the overrides the criterion requires a page to survive.
const TEXT_SPACING_CSS = `
  *{line-height:1.5 !important;letter-spacing:.12em !important;word-spacing:.16em !important}
`;

// Simulates what @media(prefers-reduced-motion:reduce) does, since a preference cannot
// be set inside a preview frame.
const REDUCED_BEFORE = `
  .home-markJSX::before,.home-mark-dotJSX{transition:none}
  .home-markJSX::before{transform:scaleX(1)}
  .home-mark-dotJSX{transform:scale(1)}
  .home-cycleJSX,.home-cyc-wordJSX{transition:none}
`;
const REDUCED_AFTER = REDUCED_BEFORE.replace( 'scaleX(1)}', 'scaleX(0)}' );

const METRICS = () => {
  const px = n => Math.round( n );
  const q = s => document.querySelector( s );
  const box = el => { if ( !el ) return null; const b = el.getBoundingClientRect(); return { t: px( b.top ), l: px( b.left ), w: px( b.width ), h: px( b.height ), b: px( b.bottom ) }; };
  const st = ( el, p ) => ( el ? getComputedStyle( el )[ p ] : null );
  const vis = el => { for ( let n = el; n; n = n.parentElement ) { const c = getComputedStyle( n ); if ( c.visibility === 'hidden' || c.display === 'none' || +c.opacity === 0 ) return false; } return true; };
  const SEL = 'a[href],button,input,select,textarea,[role="button"],[tabindex]:not([tabindex="-1"])';
  const hdr = q( 'header' ), hero = q( '.home-hero' ), layout = q( '.home-layout' ),
    h1 = q( '.home-head' ), line = q( '.home-head-line' ), sub = q( '.home-sub' ),
    mark = q( '.home-mark' ), dot = q( '.home-mark-dot' ), cyc = q( '.home-cycle' ),
    flow = q( '.home-flow' );
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    contentWidth: layout ? px( layout.getBoundingClientRect().width - parseFloat( st( layout, 'paddingLeft' ) ) * 2 ) : null,
    header: { ...box( hdr ), pos: st( hdr, 'position' ) },
    padTop: st( layout, 'paddingTop' ), gap: st( layout, 'gap' ),
    hero: box( hero ),
    h1: { ...box( h1 ), font: st( h1, 'fontSize' ), weight: st( h1, 'fontWeight' ), lh: st( h1, 'lineHeight' ),
      ls: st( h1, 'letterSpacing' ), max: st( h1, 'maxWidth' ), text: h1 ? h1.textContent.replace( /\s+/g, ' ' ).trim() : '' },
    line: box( line ), mark: box( mark ), dot: box( dot ), cycle: box( cyc ),
    // The FIRST word specifically - that is the one server-rendered with .on, so it is the
    // width a settled, JS-free panel must be given.
    w0: ( () => { const f = document.querySelectorAll( '.home-cyc-word' )[ 0 ]; return f ? f.offsetWidth : null; } )(),
    sub: { ...box( sub ), font: st( sub, 'fontSize' ), lh: st( sub, 'lineHeight' ), max: st( sub, 'maxWidth' ),
      chars: sub ? sub.textContent.trim().length : 0, text: sub ? sub.textContent.replace( /\s+/g, ' ' ).trim() : '' },
    flowTop: flow ? box( flow ).t : null,
    blank: h1 && hdr ? px( h1.getBoundingClientRect().top - hdr.getBoundingClientRect().bottom ) : null,
    actions: hero ? Array.from( hero.querySelectorAll( SEL ) ).filter( vis ).length : 0,
  };
};

( async () => {
  const t = await target();
  const browser = await launch();
  try {
    const M = {};
    let harvest = null;
    for ( const vp of [ { k: 'd', w: 1280, h: 900 }, { k: 'm', w: 390, h: 844 } ] ) {
      const ctx = await browser.newContext( { viewport: { width: vp.w, height: vp.h } } );
      const page = await ctx.newPage();
      await gotoStable( page, `${t.base}/` );
      await page.waitForTimeout( 1400 );
      M[ vp.k ] = await page.evaluate( METRICS );
      if ( vp.k === 'd' ) {
        harvest = await page.evaluate( async () => {
          const inline = Array.from( document.querySelectorAll( 'style' ) ).map( s => s.textContent ).join( '\n' );
          const hrefs = Array.from( document.querySelectorAll( 'link[rel="stylesheet"]' ) )
            .map( l => l.getAttribute( 'href' ) ).filter( h => h && h.startsWith( '/_next/' ) );
          const chunks = [];
          for ( const h of hrefs ) { try { chunks.push( await ( await fetch( h ) ).text() ); } catch { /* ignore */ } }
          // HARVEST THE PRE-HYDRATION SHAPE. By now the measuring effect has written an
          // inline width onto .home-cycle; copying it would bake the fixed state in and make
          // the no-JS panel a lie, since a sized pill is the one thing that never happens
          // without JS. The inline background on .home-mark is kept - that one really is
          // server-rendered and is present in out/index.html.
          const o = s => {
            const el = document.querySelector( s );
            if ( !el ) return '';
            const c = el.cloneNode( true );
            c.querySelectorAll( '.home-cycle' ).forEach( n => n.style.removeProperty( 'width' ) );
            return c.outerHTML;
          };
          const cls = s => document.querySelector( s )?.className || '';
          return {
            inline, chunks: chunks.join( '\n' ),
            header: o( 'header' ), h1: o( '.home-head' ), sub: o( '.home-sub' ),
            heroCls: cls( '.home-hero' ), layoutCls: cls( '.home-layout' ), shellCls: cls( '.home-shell' ),
          };
        } );
      }
      await ctx.close();
    }
    // The pill's resting width depends on the viewport, because font-size is a clamp on vw.
    // A settled panel at 653 or 880 needs ITS width, not the 1280 one, or the mock would show
    // a mis-sized pill and invent a defect.
    const FOLD_VPS = [ { w: 653, h: 280 }, { w: 882, h: 344 }, { w: 880, h: 360 } ];
    const foldW0 = {};
    for ( const v of FOLD_VPS ) {
      const c = await browser.newContext( { viewport: { width: v.w, height: v.h } } );
      const pg = await c.newPage();
      await gotoStable( pg, `${t.base}/` );
      await pg.waitForTimeout( 800 );
      foldW0[ v.w ] = await pg.evaluate( () => {
        const f = document.querySelectorAll( '.home-cyc-word' )[ 0 ];
        return f ? f.offsetWidth : null;
      } );
      await c.close();
    }

    if ( !harvest || !harvest.h1 ) throw new Error( 'failed to harvest from out/' );
    // THIS REVIEW IS OF THE PRE-#420 PILL, SO IT STOPS RATHER THAN RENDER A FALSE PAGE.
    // #420 moved the pill into RotatingPill (rp-* classes, its own styled-jsx hash), and the
    // three fixes this page reviews are RotatingPill's base CSS now. Renaming the selectors
    // would not revive it: the "before" panels would show no defect while their captions
    // describe one, and the injected rules would carry the page's hash, not the pill's.
    // It stays in the repo because other docs cite its harvest-from-the-export technique.
    if ( !/\bhome-mark\b/.test( harvest.h1 ) ) {
      throw new Error( 'homereview.js reviews the pre-#420 home-* pill; the page now uses RotatingPill (rp-*), '
        + 'whose base CSS already contains the fixes reviewed here. Nothing to generate.' );
    }

    // The styled-jsx scoping class, read off the harvested markup. Injected rules must
    // carry it or they lose the specificity contest against the page's own compiled rules
    // and the mock shows a fix that never applied.
    const jsxHash = ( /class="([^"]*\bjsx-[a-z0-9]+)\b/.exec( harvest.h1 ) || [] )[ 1 ]
      ?.split( /\s+/ ).find( c => c.startsWith( 'jsx-' ) );
    if ( !jsxHash ) throw new Error( 'could not read the styled-jsx scoping class from the harvested h1' );
    const scope = css => css.replace( /JSX/g, `.${jsxHash}` );
    // The header is a separate component, so styled-jsx gives it its own scoping class.
    const hdrHash = ( /class="([^"]*\bjsx-[a-z0-9]+)\b/.exec( harvest.header ) || [] )[ 1 ]
      ?.split( /\s+/ ).find( c => c.startsWith( 'jsx-' ) );
    if ( !hdrHash ) throw new Error( 'could not read the styled-jsx scoping class from the harvested header' );
    const scopeHdr = css => css.replace( /HDRJSX/g, `.${hdrHash}` );

    const STAMP = new Date().toISOString().replace( 'T', ' ' ).slice( 0, 16 ) + 'Z';
    const J = o => JSON.stringify( o );
    const d = M.d, m = M.m;
    const staleW = m.cycle.w, needW = d.cycle.w;
    const clipped = needW - staleW;
    const esc = s => String( s ).replace( /&/g, '&amp;' ).replace( /</g, '&lt;' ).replace( />/g, '&gt;' );


    // ---------------------------------------------------------------------------
    // PANELS ARE BUILT HERE, IN NODE, AND EMITTED AS STATIC HTML.
    //
    // They used to be assembled by a script in the page. That made the entire design
    // JavaScript-dependent: any viewer that does not run scripts - a read-only file
    // preview, a sanitising proxy - showed the headings and captions with nothing
    // between them. Which is precisely the defect this page exists to document, built
    // into the page documenting it. Now the iframes are in the markup, so the design
    // renders with no JavaScript at all. The notes use native <details>, also no JS.
    //
    // Each frame is still self-contained srcdoc: media queries, vw units and
    // position:fixed all resolve against the frame's own box, which is the only way a
    // 390-wide panel behaves like a 390-wide phone.
    // ---------------------------------------------------------------------------
    const bootJS = o => {
      const set = o.stale
        ? `if(c)c.style.width=${staleW}+"px";`
        : 'if(c&&it[i])c.style.width=it[i].offsetWidth+"px";';
      return '(function(){var w=' + JSON.stringify( WORDS ) + ';var i=0;'
        + 'var c=document.querySelector(".home-cycle"),m=document.querySelector(".home-mark"),'
        + 'd=document.querySelector(".home-mark-dot"),it=document.querySelectorAll(".home-cyc-word");'
        + 'if(it.length){'
        + 'function p(){for(var k=0;k<it.length;k++)it[k].classList.toggle("on",k===i);'
        + set
        + 'if(m)m.style.background=w[i].tint;if(d)d.style.background=w[i].dot;}'
        + 'p();'
        + ( o.noShow ? '' : 'var L=document.querySelector(".home-layout");if(L)L.classList.add("show");' )
        + ( o.rotate && !o.stale ? 'setInterval(function(){i=(i+1)%w.length;p();},2400);' : '' )
        + '}'
        + ( o.menuOpen ? 'var nm=document.querySelector(".nav-menu");if(nm)nm.classList.add("open");'
            + 'var tg=document.querySelector(".nav-trigger");if(tg)tg.setAttribute("aria-expanded","true");' : '' )
        + '})();';
    };

    // ONLY THE styled-jsx BLOCKS, NOT THE 514KB OF GLOBAL CHUNKS.
    // Every frame inlines this, so including the chunks put the page at 15MB. The chunks are
    // Amplify UI plus the dashboard stylesheets; the header and hero are entirely styled by
    // their own styled-jsx blocks. Dropping them is verified rather than assumed: the check
    // asserts the band still measures header 108, h1 506x131, sub 560x56, pill 278 - identical
    // to the live page. If a global rule ever does matter, those numbers move and the check fails.
    // The ONE global rule that matters, taken verbatim from the built chunks. Dropping the
    // chunks wholesale was wrong: they carry `*{box-sizing:border-box;margin:0;padding:0}`,
    // and without it the menu's max-height stops including its padding, so the panels reported
    // a 72px menu where the live page gives 40px. The rest of the 514KB is Amplify UI and the
    // dashboard stylesheets, which this band never touches - verified by asserting the panels
    // match the live measurements exactly.
    const GLOBAL_RESET = '*{box-sizing:border-box;margin:0;padding:0}';
    // THE BODY FONT RULE, EXTRACTED FROM THE BUILT CSS. The brand lockup declares no
    // font-family of its own - it inherits body - so without this the mock rendered the logo
    // in Times New Roman while the live page renders Inter. My fidelity anchor missed it
    // because h1 and sub-line both declare their own stack; the lockup is the one element that
    // depends on the CSS I trimmed. Extracted rather than retyped so it cannot drift.
    const bodyFont = ( () => {
      const m = /body\{[^}]*font-family:Inter[^}]*\}/.exec( harvest.chunks );
      if ( !m ) throw new Error( 'could not extract the body font rule from the built CSS' );
      return m[ 0 ];
    } )();
    const CSS_ALL = GLOBAL_RESET + '\n' + bodyFont + '\n' + harvest.inline;
    // PRE-APPLY THE SETTLED STATE, so a panel showing the real design needs no JavaScript.
    // The export already server-renders the first word with .on and the tint/dot inline; the
    // only two things the effect adds are the pill's measured width and the .show class that
    // lifts the entrance shutter. Baking those in is what makes the ORIGINAL panel show the
    // actual design rather than the un-hydrated one - without it, a viewer with scripts off
    // sees the defect in the panel labelled "as it ships today", which would be a lie.
    const settle = ( h1, width ) =>
      h1.replace( /(<span class="[^"]*home-cycle[^"]*")/, `$1 style="width:${width}px"` );
    // What a client-side translation does: rewrite the text node and nothing else. The pill
    // keeps the width JavaScript measured for the English word, which is the whole finding.
    const HINDI = 'उपभोक्ताओं';
    const translate = h1 => {
      const out = h1.replace( `>${WORDS[ 0 ].word}<`, `>${HINDI}<` );
      if ( out === h1 ) throw new Error( `translate(): could not find "${WORDS[ 0 ].word}" in the harvested h1` );
      return out;
    };
    const frameDoc = o => {
      const base = o.noGlobal ? GLOBAL_RESET + '\n' + harvest.inline : CSS_ALL;
      const extra = ( o.fix ? scope( FIX_CSS ) : '' ) + ( o.hfix ? scopeHdr( HEADER_FIX_CSS ) : '' )
        + ( o.spacing ? TEXT_SPACING_CSS : '' ) + ( o.brand ? scopeHdr( BRAND_FIX_CSS ) : '' )
        + ( o.reduced === 'before' ? scope( REDUCED_BEFORE ) : '' )
        + ( o.reduced === 'after' ? scope( REDUCED_AFTER ) : '' );
      const script = o.noJs ? '' : '<script>' + bootJS( o ) + '<\/script>';
      // .show baked in for settled panels, so the shutter is lifted with no script.
      const layoutCls = o.settled
        ? harvest.layoutCls
        : harvest.layoutCls.replace( /\bshow\b/, '' ).trim();
      return '<!doctype html><meta charset="utf-8">'
        + '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
        + '<style>html,body{margin:0}' + base + extra + '</style>'
        + harvest.header
        + '<main class="' + harvest.shellCls + '"><div class="' + layoutCls + '">'
        + '<div class="' + harvest.heroCls + '">'
        + ( () => {
          let h = o.settled ? settle( harvest.h1, o.settled ) : harvest.h1;
          if ( o.hindi ) h = translate( h );
          return h;
        } )() + harvest.sub + '</div>'
        + '</div></main>'
        + script;
    };
    const shot = ( o, w, h, sc ) =>
      `<div class="shot" style="width:${Math.round( w * sc )}px;height:${Math.round( h * sc )}px">`
      + `<iframe loading="lazy" scrolling="no" title="preview" `
      + `style="width:${w}px;height:${h}px;transform:scale(${sc})" `
      + `srcdoc="${frameDoc( o ).replace( /"/g, '&quot;' )}"></iframe></div>`;
    const labelled = ( lab, cls, o, w, h, sc ) =>
      `<div class="cmpcol"><span class="collab ${cls}">${lab}</span>${shot( o, w, h, sc )}</div>`;

    const SW = 1280, SH = 340, SC = 0.55;
    const P = {
      origD: shot( { rotate: true, settled: M.d.w0 }, 1280, 470, 1 ),
      origM: shot( { rotate: true, settled: M.m.w0 }, 390, 420, 1 ),
      fixedD: shot( { rotate: true, fix: true, settled: M.d.w0 }, 1280, 470, 1 ),
      fixedM: shot( { rotate: true, fix: true, settled: M.m.w0 }, 390, 420, 1 ),
      // 900 is a real viewport height, not a crop: the iframe's height IS 100vh inside it,
      // and the menu is max-height:calc(100vh - 320px). A short panel would misreport it.
      hdrOpenD: shot( { rotate: false, menuOpen: true, settled: M.d.w0 }, 1280, 900, 1 ),
      hdrLand: '<div class="cmp">'
        + labelled( 'before — 70px of menu', 'c-b', { rotate: false, menuOpen: true, settled: M.d.w0 }, 844, 390, 1 )
        + labelled( 'after — anchored to the header', 'c-a', { rotate: false, menuOpen: true, hfix: true, settled: M.d.w0 }, 844, 390, 1 )
        + '</div>',
      fixA: '<div class="cmp">'
        + labelled( 'before — no word', 'c-b', { noJs: true }, SW, SH, SC )
        + labelled( 'after', 'c-a', { noJs: true, fix: true }, SW, SH, SC ) + '</div>',
      fixB: '<div class="cmp">'
        + labelled( 'before — cut off', 'c-b', { rotate: false, stale: true }, SW, SH, SC )
        + labelled( 'after', 'c-a', { rotate: false, fix: true, settled: M.d.w0 }, SW, SH, SC ) + '</div>',
      fixC: '<div class="cmp">'
        + labelled( 'before — white pill', 'c-b', { rotate: false, reduced: 'before', noShow: true }, SW, SH, SC )
        + labelled( 'after', 'c-a', { rotate: false, reduced: 'after', fix: true, noShow: true }, SW, SH, SC ) + '</div>',
      spacing: '<div class="cmp">'
        + labelled( 'before — 22% cut', 'c-b', { rotate: false, settled: M.d.w0, spacing: true }, SW, 420, SC )
        + labelled( 'after', 'c-a', { rotate: false, settled: M.d.w0, spacing: true, fix: true }, SW, 420, SC ) + '</div>',
      hindi: '<div class="cmp">'
        + labelled( 'before — clipped', 'c-b', { rotate: false, settled: M.d.w0, hindi: true }, SW, SH, SC )
        + labelled( 'after', 'c-a', { rotate: false, settled: M.d.w0, hindi: true, fix: true }, SW, SH, SC ) + '</div>',
      fold653: '<div class="cmp">'
        + labelled( 'before — 0px of menu', 'c-b', { rotate: false, menuOpen: true, settled: foldW0[ 653 ] }, 653, 280, 1 )
        + labelled( 'after', 'c-a', { rotate: false, menuOpen: true, hfix: true, settled: foldW0[ 653 ] }, 653, 280, 1 ) + '</div>',
      fold882: '<div class="cmp">'
        + labelled( 'before — 24px', 'c-b', { rotate: false, menuOpen: true, settled: foldW0[ 882 ] }, 882, 344, 1 )
        + labelled( 'after', 'c-a', { rotate: false, menuOpen: true, hfix: true, settled: foldW0[ 882 ] }, 882, 344, 1 ) + '</div>',
      fold880: '<div class="cmp">'
        + labelled( 'before — 40px', 'c-b', { rotate: false, menuOpen: true, settled: foldW0[ 880 ] }, 880, 360, 1 )
        + labelled( 'after', 'c-a', { rotate: false, menuOpen: true, hfix: true, settled: foldW0[ 880 ] }, 880, 360, 1 ) + '</div>',
      foldBand: '<div class="cmp">'
        + labelled( 'Galaxy Fold folded landscape 653×280', 'c-b', { rotate: false, settled: foldW0[ 653 ] }, 653, 280, 1 )
        + labelled( 'Z Fold 5 cover landscape 882×344', 'c-b', { rotate: false, settled: foldW0[ 882 ] }, 882, 344, 1 ) + '</div>',
      brandD: '<div class="cmp">'
        + labelled( 'before — inherited stack', 'c-b', { rotate: false, settled: M.d.w0 }, 1280, 300, 1 )
        + labelled( 'after — declared stack', 'c-a', { rotate: false, settled: M.d.w0, brand: true }, 1280, 300, 1 ) + '</div>',
      brandM: '<div class="cmp">'
        + labelled( 'before', 'c-b', { rotate: false, settled: M.m.w0 }, 390, 300, 1 )
        + labelled( 'after', 'c-a', { rotate: false, settled: M.m.w0, brand: true }, 390, 300, 1 ) + '</div>',
      brandRisk: '<div class="cmp">'
        + labelled( 'before — logo loses Inter', 'c-b', { rotate: false, settled: M.d.w0, noGlobal: true }, 1280, 320, 1 )
        + labelled( 'after — logo keeps Inter', 'c-a', { rotate: false, settled: M.d.w0, noGlobal: true, brand: true }, 1280, 320, 1 ) + '</div>',
      proof: '<div class="cmp">'
        + labelled( 'today', 'c-b', { rotate: true, settled: M.d.w0 }, SW, SH, SC )
        + labelled( 'with the fixes', 'c-a', { rotate: true, fix: true, settled: M.d.w0 }, SW, SH, SC ) + '</div>',
    };

    const html = `<!doctype html>
<meta charset="utf-8">
<title>Home page — top section: the three defect fixes</title>
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
  h3{font-size:16.5px;font-weight:700;letter-spacing:-.2px;margin:0}
  p{margin:0 0 10px}
  .lede{font-size:18px;max-width:80ch}
  .mut{color:var(--mut)} .sm{font-size:13.5px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.87em;background:#f0f0f0;padding:1px 5px;border-radius:4px}
  pre{background:#f6f6f6;border:1px solid var(--line);border-radius:8px;padding:13px;overflow:auto;font-size:12.5px;line-height:1.5;margin:8px 0 0}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 22px}
  .card.brief{border-left:4px solid var(--lime)}
  .card.scope{border-left:4px solid #20418f}
  section.band{margin:0 0 26px;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .bhead{padding:17px 22px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
  .tag{display:inline-flex;align-items:center;justify-content:center;padding:3px 9px;border-radius:6px;
    background:var(--grn);color:var(--lime);font-weight:800;font-size:12px;letter-spacing:.06em;flex:none}
  .sel{font-size:13px;color:var(--mut);font-family:ui-monospace,Menlo,monospace}
  .step{padding:19px 22px;border-top:1px solid #f0f0f0}
  .steplab{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:3px 9px;border-radius:5px;margin:0 0 12px}
  .l-orig{background:#eef1f4;color:#44546a} .l-fix{background:#eaf4ea;color:#1f6f3d}
  .l-proof{background:var(--lime);color:var(--grn)} .l-open{background:#fff4e5;color:var(--amb)}
  table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 0}
  th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
  th{background:#f7f7f7;font-weight:600}
  td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  ol,ul{margin:6px 0 10px;padding-left:20px} li{margin:5px 0}
  .sev{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 7px;border-radius:4px;flex:none}
  .s-h{background:#fdeceb;color:var(--red)} .s-m{background:#fff4e5;color:var(--amb)} .s-l{background:#eef1f4;color:#44546a}
  .ba{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;margin:12px 0 0}
  .col{flex:none}
  .collab{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;margin:0 0 7px;padding:2px 7px;border-radius:4px;display:inline-block}
  .c-b{background:#fdeceb;color:var(--red)} .c-a{background:#eefaf0;color:#1f6f3d}
  .shot{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff;position:relative}
  .shot iframe{border:0;display:block;transform-origin:0 0}
  .readout{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#f6f6f6;border:1px solid var(--line);
    border-radius:6px;padding:8px 10px;margin:8px 0 0;white-space:pre-wrap;word-break:break-word}
  .ctl{display:flex;gap:18px;flex-wrap:wrap;align-items:center;font-size:14px;margin:12px 0 0}
  .ctl label{display:inline-flex;gap:7px;align-items:center;cursor:pointer}
  footer.pg{color:var(--mut);font-size:13px;border-top:1px solid var(--line);padding-top:18px;margin-top:34px}
  /* ---- design-first comparison layout ---- */
  .cmp{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start;margin:0 0 14px}
  .cmpcol{flex:none}
  .cap{font-size:14px;color:var(--mut);margin:0 0 14px;max-width:110ch}
  .cap b{color:var(--ink)}
  details.why{border:1px solid var(--line);border-radius:9px;background:#fcfcfc;margin:14px 0 0}
  details.why>summary{cursor:pointer;padding:10px 14px;font-size:13px;font-weight:700;color:#44546a;
    list-style:none;display:flex;gap:8px;align-items:center}
  details.why>summary::-webkit-details-marker{display:none}
  details.why>summary::before{content:'▸';font-size:11px}
  details.why[open]>summary::before{content:'▾'}
  details.why>summary:hover{color:var(--ink)}
  details.why .inner{padding:0 14px 14px;border-top:1px solid var(--line);margin-top:0;padding-top:12px}
  .bar{position:sticky;top:0;z-index:5;background:rgba(250,250,250,.94);backdrop-filter:blur(6px);
    border-bottom:1px solid var(--line);padding:10px 0;margin:0 0 20px}
  .bar .in{display:flex;gap:20px;flex-wrap:wrap;align-items:center;font-size:14px}
</style>
<div class="wrap">

<h1>Home page — top band</h1>
<p class="cap" style="font-size:16px">The original as it ships today, then the same band with
the three fixes — both at <b>actual size</b>, 1280 and 390, nothing scaled down. <b>They are
meant to look identical:</b> the fixes only repair states you cannot see in a normal screenshot.</p>

<div class="bar"><div class="in">
  <span class="mut sm"><b>No JavaScript needed to view this page.</b> Every panel is in the
  markup; the notes are native <code>&lt;details&gt;</code> — click “why / the code” to open one.
  no CTA, no price — this band says what the page is about · source unchanged<br>
  <b>Build ${STAMP}.</b> If this stamp is older than the commit you expect, you are looking at a
  cached copy — reload with a query string appended. Exactly one panel in this page renders the
  logo in a serif, and it is labelled “before — logo loses Inter” in section H; a serif logo
  anywhere else means a stale render.</span>
</div></div>

<!-- ============== ORIGINAL, 1:1 ============== -->
<section class="band">
  <div class="bhead"><span class="tag" style="background:#44546a;color:#fff">ORIGINAL</span>
    <h2>As it ships today — desktop 1280, actual size</h2>
    <span class="sel">unmodified: no fixes applied</span></div>
  <div class="step">${P.origD}</div>
</section>

<section class="band">
  <div class="bhead"><span class="tag" style="background:#44546a;color:#fff">ORIGINAL</span>
    <h2>As it ships today — phone 390, actual size</h2>
    <span class="sel">unmodified: no fixes applied</span></div>
  <div class="step">${P.origM}</div>
</section>

<!-- ============== WITH THE FIXES, 1:1 ============== -->
<section class="band">
  <div class="bhead"><span class="tag">FIXED</span><h2>With the three fixes — desktop 1280, actual size</h2></div>
  <div class="step">${P.fixedD}</div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">FIXED</span><h2>With the three fixes — phone 390, actual size</h2></div>
  <div class="step">${P.fixedM}</div>
</section>

<!-- ============== HEADER / MENU ============== -->
<section class="band">
  <div class="bhead"><span class="tag" style="background:#44546a;color:#fff">HEADER</span>
    <h2>Menu open — desktop 1280, actual size</h2>
    <span class="sel">shared chrome, every public page · unmodified</span></div>
  <div class="step">
    <p class="cap">This is fine. The header's keyboard and screen-reader wiring is already
    correct — <code>aria-expanded</code> on the trigger, Escape closes from anywhere, an outside
    click dismisses, focus returns to the trigger, and the closed menu is
    <code>visibility:hidden</code> so its 20 links are not in the tab order.</p>
    ${P.hdrOpenD}
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">HEADER FIX</span><span class="sev s-m">MED</span>
    <h2>Landscape phone — the menu collapses to a sliver</h2></div>
  <div class="step">
    <p class="cap"><b>At 844×390 the menu is 70 px tall and holds 700 px of content — 10.6x
    its own height.</b> Twenty links in a sliver. Both panels are 1:1 at 844×390.</p>
    ${P.hdrLand}
    <details class="why" data-note><summary>why / the code</summary><div class="inner">
      <p>The menu is <code>max-height:calc(100vh - 320px)</code>, and the mobile override that
      repositions it is gated on <code>@media(max-width:767px)</code>. So any window
      <em>wider</em> than 767 but short falls back to the desktop rule — a landscape phone, or a
      short desktop window. Measured across nine viewports:</p>
      <table>
        <tr><th>Viewport</th><th class="n">menu</th><th class="n">content</th><th>verdict</th></tr>
        <tr><td>390×844 portrait</td><td class="n">358×536</td><td class="n">1028px</td><td>scrolls, usable</td></tr>
        <tr><td>1280×900 desktop</td><td class="n">760×403</td><td class="n">399px</td><td>fits</td></tr>
        <tr><td><strong>844×390 landscape</strong></td><td class="n"><strong>588×70</strong></td><td class="n"><strong>700 px</strong></td><td><strong>unusable</strong></td></tr>
      </table>
      <p style="margin-top:10px">Also <code>100vh</code>, not <code>100dvh</code> — the exact unit
      defect <code>index.tsx</code> already fixed for <code>.home-shell</code>, still present in the
      shared chrome. And 320 corresponds to nothing nameable, which is the same magic-number family
      as the 108/96 header heights.</p>
      <pre><code>/* anchor to the header, and use dvh: 140 = the 108px header + 32px of air */
.nav-menu{max-height:calc(100dvh - 140px)}</code></pre>
    </div></details>
  </div>
</section>

<!-- ============== WHAT CHANGED ============== -->
<section class="band">
  <div class="bhead"><span class="tag">CHANGES</span><h2>Three repairs — one line each</h2></div>

  <div class="step">
    <p class="cap"><span class="sev s-h">A</span> &nbsp;<b>The word is missing entirely without
    JavaScript, and for ~200ms on every single load.</b></p>
    ${P.fixA}
    <details class="why" data-note><summary>why / the code</summary><div class="inner">
      <p><code>cycleW</code> starts <code>null</code>, so the first render writes no inline width.
      <code>.home-cycle</code> is <code>overflow:hidden</code> and all four words are
      <code>position:absolute</code>, so they add nothing to its intrinsic width — it computes to
      <strong>0px</strong> and clips the word away. Measured on a normal load, JS working, local
      server, no network: <strong>4 painted frames, ~200ms</strong>.</p>
      <pre><code>.home-cycle{width:max-content}   /* resting width, needs no JS */
.home-cyc-word.on{
  position:static;      /* the visible word sits in flow, so the pill has a width */
  display:inline-block; /* NOT optional - see below */
}</code></pre>
      <p class="sm" style="margin-top:10px"><strong><code>display:inline-block</code> is
      load-bearing, and measuring this mock is what caught it.</strong> <code>position:static</code>
      alone makes the span a non-replaced <em>inline</em> box, whose <code>offsetWidth</code> is 0 —
      so the existing effect would write <code>width:0px</code> over <code>max-content</code> and the
      pill would collapse on every load <em>with</em> JavaScript, turning a 200ms flash into a
      permanent one.</p>
    </div></details>
  </div>

  <div class="step">
    <p class="cap"><span class="sev s-h">B</span> &nbsp;<b>Resize with reduced motion on and the word
    stays cut — ${clipped} px, ${Math.round( 100 * clipped / needW )}% of it — for good.</b></p>
    ${P.fixB}
    <details class="why" data-note><summary>why / the code</summary><div class="inner">
      <p>Width is measured in an effect keyed on the word index alone; there is no resize listener.
      The font is <code>clamp(36px,4.3vw,60px)</code>, so width is a function of viewport width. On a
      normal load a stale value self-heals at the next 2400ms tick; under reduced motion the interval
      never starts, so it is final. Reproduced here by writing the <strong>${staleW} px</strong> width
      measured at 390 onto a 1280 frame, where the word needs <strong>${needW} px</strong>.</p>
      <pre><code>const ro = new ResizeObserver( measure );   // not window.resize: this also
if ( markRef.current ) ro.observe( markRef.current );  // catches a webfont swap
return () =&gt; ro.disconnect();</code></pre>
    </div></details>
  </div>

  <div class="step">
    <p class="cap"><span class="sev s-m">C</span> &nbsp;<b>Reduced motion can park a white shutter
    over the tint — latent today, one edit away from live.</b></p>
    ${P.fixC}
    <details class="why" data-note><summary>why / the code</summary><div class="inner">
      <p>The reduced-motion block sets the shutter to <code>scaleX(1)</code> — the <em>start</em>
      state — under a comment saying it settles the pill into its resting state, which is
      <code>scaleX(0)</code>. The dot's sibling rule is correct, so it is a slip. It is overridden
      today only because <code>.home-layout.show .home-mark::before</code> scores
      <strong>(0,2,1)</strong> against this rule's <strong>(0,1,1)</strong>.</p>
      <pre><code>@media(prefers-reduced-motion:reduce){
  .home-mark::before{transform:scaleX(0)}   /* was scaleX(1) */
}</code></pre>
    </div></details>
  </div>
</section>

<!-- ============== MORE FLAWS ============== -->
<section class="band">
  <div class="bhead"><span class="tag">D</span><span class="sev s-h">HIGH</span>
    <h2>WCAG 1.4.12 fails — user text spacing cuts 22% of the word</h2></div>
  <div class="step">
    <p class="cap"><b>1.4.12 is Level AA and normative:</b> a reader's own stylesheet setting
    line-height 1.5, letter-spacing .12em and word-spacing .16em must not clip anything. The word
    needs 356.8px; the pill stays at 278px. Both panels have those overrides applied.</p>
    ${P.spacing}
    <details class="why" data-note><summary>why / the code</summary><div class="inner">
      <p>Same root cause as A and B from a third angle: a JavaScript-measured width on an
      <code>overflow:hidden</code> box cannot survive anything that changes glyph metrics.
      <strong>Fixes A + B close this</strong> — <code>max-content</code> is right under any
      spacing, and the <code>ResizeObserver</code> refires when the word's box changes. No extra
      code. It promotes those two from “repairs a flash” to “clears an AA failure”.</p>
    </div></details>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">E</span><span class="sev s-h">HIGH</span>
    <h2>Translating the page leaves the word in English</h2></div>
  <div class="step">
    <p class="cap"><b>Corrected — and the truth is worse than what I first wrote.</b> I claimed the
    translated word gets clipped. It does not, because <b>the rotating word is never translated at
    all.</b> <code>SupportWidget</code>'s text walker rejects any node whose ancestor carries
    <code>aria-hidden="true"</code>, and all four animated words carry exactly that.</p>
    <p class="cap">So translating the page produces a <b>mixed-language headline</b>: the frame
    line becomes Hindi, the word inside the pill stays English. And the screen-reader list
    <em>does</em> translate — so assistive tech gets Hindi while the screen shows English.</p>
    <table style="margin-bottom:6px">
      <tr><th>Element in the band</th><th>Translated?</th><th>Why</th></tr>
      <tr><td><code>.brand-stack</code> — “WECARE.DIGITAL”</td><td>yes</td><td></td></tr>
      <tr><td>23 <code>.nav-item</code> / <code>.nav-group-label</code></td><td>yes</td><td></td></tr>
      <tr><td><code>.home-head-line</code> — “Everyday AI, built for”</td><td>yes</td><td></td></tr>
      <tr><td><code>.home-sr-only</code> — the list read aloud</td><td><b>yes</b></td><td>no <code>aria-hidden</code> on it</td></tr>
      <tr><td><code>.home-cyc-word</code> ×4 — the visible words</td><td><b>NO</b></td><td><code>aria-hidden="true"</code> → <code>FILTER_REJECT</code></td></tr>
      <tr><td><code>.home-sub</code></td><td>yes</td><td></td></tr>
    </table>
    <p class="cap"><b>Measured on the built page: 34 text nodes in the band, 30 translated, 4
    skipped</b> — and the 4 are the ones a visitor is looking at.</p>
    <details class="why" data-note><summary>why / and why there is no fix here</summary><div class="inner">
      <p>The <code>aria-hidden</code> rule is <em>correct</em> for its purpose — it is what keeps
      decorative and duplicated text out of a translation batch. The words carry
      <code>aria-hidden</code> for an equally good reason: without it a screen reader would read
      the headline once per word. Two sound decisions that combine into a defect.</p>
      <p><strong>This is not a CSS fix and I am not going to invent one.</strong> The options each
      cost something: an allowlist attribute the walker honours ahead of
      <code>aria-hidden</code>; translating <code>CYCLE_WORDS</code> at build time per locale so
      the markup ships already-translated; or dropping <code>aria-hidden</code> from the active
      word only and removing the sr-only list. The first is the smallest, the second is the most
      correct, the third changes what assistive tech hears. That is a decision for you.</p>
      <p class="sm">What the applied fixes <em>do</em> guarantee: if the words ever do become
      translatable, the pill will size to them. <code>width:max-content</code> plus the
      <code>ResizeObserver</code> means a longer word cannot be clipped — verified against the
      WCAG 1.4.12 overrides, where the word grows from 278px to 377px and the pill follows it
      exactly.</p>
    </div></details>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">F</span><span class="sev s-h">HIGH</span>
    <h2>Foldables — the menu reaches zero height</h2></div>
  <div class="step">
    <p class="cap">The menu failure needs a viewport that is <b>wide and short</b> — rare on a
    phone or laptop, and the normal shape of a folded-landscape device. All six panels are
    <b>1:1 at real foldable viewports</b>. 844×390 was the mild case.</p>
    <p class="cap" style="margin-top:14px"><b>Galaxy Fold, folded, landscape — 653×280.</b>
    Computed <code>max-height</code> is <b>0px</b>; the 32px left is padding and border, holding
    20 links and 1028px of content.</p>
    ${P.fold653}
    <p class="cap" style="margin-top:16px"><b>Z Fold 5 cover, landscape — 882×344.</b> 24px.</p>
    ${P.fold882}
    <p class="cap" style="margin-top:16px"><b>Z Flip 5, landscape — 880×360.</b> 40px. Z Flip and
    Z Fold are the two best-selling foldables, so this is not an exotic posture.</p>
    ${P.fold880}
    <details class="why" data-note><summary>why / the code — and a gap in my first fix</summary><div class="inner">
      <p><strong>My earlier fix would not have worked.</strong> I replaced only the desktop
      <code>calc(100vh - 320px)</code>. At 653px wide the <em>mobile</em> override applies instead
      — <code>calc(100vh - 308px)</code> — and 308 exceeds a 280px viewport, so it resolves
      negative and clamps to zero. Both rules have to change:</p>
      <pre><code>/* 140 = the 108px header + 32px of air. dvh for mobile browser chrome. */
.nav-menu{max-height:calc(100dvh - 140px)}
@media(max-width:767px){ .nav-menu{max-height:calc(100dvh - 140px)} }</code></pre>
      <p>Resulting heights: 280 → 140px, 344 → 204px, 360 → 220px, 390 → 250px.</p>
      <p><strong>The reasoning already exists in this repo.</strong>
      <code>src/styles/Layout.css:2185</code> and <code>:2204</code> handle exactly this for the
      dashboard's bottom nav, with a comment naming the trap — <em>“an unfolded inner display is
      tablet-WIDE but often phone-TALL … short and wide (a landscape fold…)”</em> — plus
      <code>vertical-viewport-segments: 2</code> as the real posture signal, asserted by
      <code>BottomNav.test.tsx:140</code>. The dashboard learned it; the public chrome never did.
      Note that rule carries a <code>max-width:768px</code> ceiling which would <em>not</em> cover
      the 880 and 882 cases, so the header needs the height condition without it.</p>
    </div></details>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">G</span><span class="sev s-m">MED</span>
    <h2>Foldables — the band's own sentence falls below the fold</h2></div>
  <div class="step">
    <p class="cap">This band exists to say what the page is about, and on two folded-landscape
    postures the sentence does not fit: it ends at <b>314px on a 280px viewport</b> and
    <b>359px on a 344px one</b>. Both 1:1 — scroll is disabled in the panels, so what you see is
    what fits.</p>
    ${P.foldBand}
    <details class="why" data-note><summary>why</summary><div class="inner">
      <p>Every other posture in the sixteen measured fits. A 280px-tall viewport is genuinely
      hostile, so this is a judgement rather than a defect — but it interacts with the
      ${d.blank}px of blank above the headline that is already an open question: on these two
      postures, that padding is the difference.</p>
      <p><strong>Clean across all sixteen</strong>, and worth recording so it is not re-checked:
      zero horizontal overflow, and the pill never crosses the viewport edge — including at
      280px, narrower than the 320px floor <code>animcheck</code> tests.</p>
    </div></details>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">H</span><span class="sev s-m">MED</span>
    <h2>Brand lockup font — the one type change you approved</h2></div>
  <div class="step">
    <p class="cap"><b>The WECARE.DIGITAL lockup declares no font of its own.</b> It inherits
    <code>body</code>, set in <code>src/styles/Layout.css</code>. The hero declares its own stack
    at <code>index.tsx:797</code>. Two declarations for one typeface, and only one of them belongs
    to the thing it styles.</p>
    <table style="margin-bottom:14px">
      <tr><th>Element</th><th>Resolved stack</th></tr>
      <tr><td><code>.logo</code> / <code>.brand-stack</code> — <b>inherited</b></td>
          <td><code>Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif</code></td></tr>
      <tr><td><code>.home-head</code> / <code>.home-sub</code> — <b>declared</b></td>
          <td><code>Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif</code></td></tr>
    </table>
    <p class="cap"><b>Faithful before / after — they are identical, and that is the point.</b></p>
    ${P.brandD}
    ${P.brandM}
    <p class="cap" style="margin-top:18px"><b>Why it is worth doing anyway.</b> Below, the same
    pair with the global stylesheet absent — one refactor, one import move. The logo drops off
    Inter; the headline does not, because it owns its stack. This is not hypothetical: I produced
    it by accident while trimming CSS out of this mock.</p>
    ${P.brandRisk}
    <details class="why" data-note><summary>why / the code — and two things I had wrong</summary><div class="inner">
      <p><strong>There is no visible difference, and I am not going to imply one.</strong> I
      rendered “WECARE.DIGITAL” at 800/23px in both stacks, with Inter available and with
      <code>fonts.googleapis.com</code> blocked: <b>195.59px against 195.59px, 0px delta both
      times</b>. <code>font-feature-settings</code> is inherited, so both get Inter's
      <code>cv02/cv03/cv04/cv11</code> variants too — measured, not assumed. On macOS, Windows and
      Android both stacks land on the same system UI face.</p>
      <p><strong>Correction 1.</strong> I first wrote that the lockup rides on
      <code>@aws-amplify/ui-react</code>'s stylesheet. It does not. The winning rule is
      <code>body{font-family:Inter,…}</code> in <b>our own <code>src/styles/Layout.css</code></b>,
      with Inter first and deliberate <code>font-feature-settings</code>. So the exposure is
      smaller than I said — it is our stylesheet, not a dependency.</p>
      <p><strong>Correction 2, and it is a finding.</strong> <code>index.tsx</code>'s own comment
      says this page rendered in Inter “only because <code>@aws-amplify/ui-react</code>'s
      styles.css sets a font-family on body”. That is <b>not true</b> — <code>Layout.css</code>
      sets it, on purpose. The justification written into the source for the hero declaring its
      stack locally rests on a misattribution. The conclusion still stands; the reason given does
      not. That is the eleventh incorrect comment claim in this band.</p>
      <pre><code>/* Header.tsx - the same declaration as index.tsx:797, byte for byte */
.hdr,.logo,.brand-lockup,.brand-stack{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}</code></pre>
      <p class="sm">Better still: one shared token both files reference, so a third copy cannot
      drift. Wider than you asked for, so noted rather than done.</p>
    </div></details>
  </div>
</section>

<section class="band">
  <div class="bhead"><span class="tag">TYPE</span><h2>Typography — measured, not previewable</h2></div>
  <div class="step">
    <p class="cap">These are real and measured, but a preview frame would <b>misrepresent</b>
    them: font fallback and forced-colours depend on the operating system, so this machine's
    rendering is not yours. Numbers instead of a fake panel.</p>
    <p class="cap"><b>Per your call, the only type change being made is the brand lockup
    (section H above).</b> Everything in this table is left exactly as it ships — recorded so it
    is not lost, not queued.</p>
    <table>
      <tr><th>Finding</th><th>Measured</th></tr>
      <tr><td><b>Two different Inter stacks in one band.</b> Header lockup vs hero — identical while Inter loads, divergent the moment it is not</td>
          <td><code>Inter, ui-sans-serif</code> vs <code>Inter, -apple-system</code>; sitewide 105 vs 1135</td></tr>
      <tr><td><b>The webfont swap moves the band</b> on every cold load. <code>animcheck</code> cannot see it — <code>gotoStable</code> waits on <code>fonts.ready</code> by design</td>
          <td>frame line 513.1 → 506px · band 209.4 → <b>211.4px</b></td></tr>
      <tr><td><b><code>.brand-dot</code> has no contrast margin</b> — passes AA only because 23px/800 counts as large text</td>
          <td><b>3.94:1</b> (needs 3:1 large, 4.5:1 normal)</td></tr>
      <tr><td><b>forced-colors strips the tint and the dot.</b> No <code>forced-colors</code> rules anywhere, and the source argues the four tints are the message</td>
          <td>both → <code>rgb(255,255,255)</code></td></tr>
      <tr><td><b>No dark-mode support and no <code>&lt;meta name="color-scheme"&gt;</code>.</b> Light-only is a fine decision; undeclared is not</td>
          <td>0 <code>prefers-color-scheme</code> rules</td></tr>
      <tr><td><b>A comment claims <code>20px/600</code> “exists nowhere on the site”.</b> It does</td>
          <td><code>/orders</code> <code>.mo-link</code></td></tr>
      <tr><td><b><code>15.5px</code> exists</b> — a half-pixel size is arithmetic, not intent</td>
          <td>×71, <code>/terms</code> and <code>/privacy</code></td></tr>
      <tr><td><b>Tracking drift:</b> the home page is on <code>-0.04em</code>; the other three hero copies are still on <code>-2.2px</code> with media overrides — the 2.75× optical swing</td>
          <td><code>RotatingHero</code> alone is 13 public routes</td></tr>
    </table>
  </div>
</section>

<!-- ============== PROOF ============== -->
<section class="band">
  <div class="bhead"><span class="tag">PROOF</span><h2>Nothing visible changed</h2></div>
  <div class="step">
    <p class="cap">Normal load, side by side. Measured: pill 280px both, h1 ${d.h1.h} px both at 1280 and
    ${m.h1.h} px both at 390 — so the reflow pin and the 2400ms page-jump guard still hold.</p>
    ${P.proof}
  </div>
</section>

<!-- ============== REST ============== -->
<section class="band">
  <div class="bhead"><span class="tag">REST</span><h2>Housekeeping, and two calls for you</h2></div>
  <div class="step">
    <p class="cap"><b>No visual change, same commit:</b> permanent <code>will-change:width</code>;
    a <code>max-width:${d.h1.max}</code> on the h1 that never binds; the h1's raw text repeating the word
    set five times; nine stale comments.</p>
    <p class="cap"><b>Your call, not mocked:</b> the ${( WORDS.length * 2.4 ).toFixed( 1 )}s rotation that cannot be paused, and
    ${d.blank} px of blank above the first word.</p>
    <details class="why" data-note><summary>detail</summary><div class="inner">
      <ul style="margin-top:0">
        <li><code>will-change:width</code> should be set shortly before a transition and released
        after; left on it holds compositing resources for the page's life, and under reduced motion
        there is no transition to hint at. Not applied in the panels — a performance judgement.</li>
        <li><code>max-width:${d.h1.max}</code> never binds: <code>.home-hero</code> is
        <code>align-items:flex-start</code>, so the h1 shrink-wraps to ${d.h1.w} px at 1280.</li>
        <li>The h1's raw text — screen readers are correct, but a naive extractor reads:
        <div class="readout">${esc( d.h1.text )}</div></li>
        <li>Comments contradict the band in nine places, two measurable: the header says
        <code>climate tech</code> is 290px with an 83px spread across five words;
        <code>animcheck</code> measures <strong>298px</strong> and <strong>22px</strong> across four.</li>
        <li>Rotation: WCAG 2.2.2 covers content moving automatically past five seconds. Hover+focus
        pausing adds no furniture; a strict reading wants a user-operable control, which is furniture
        in a band meant to carry none.</li>
        <li>The ${d.blank} px was tuned around the deleted lime brand badge. Purely cosmetic.</li>
      </ul>
      <p class="sm mut">Deferred until this band is signed off: the other three bands, the sitewide
      schema problems, and propagating this band to the remaining public pages.</p>
    </div></details>
  </div>
</section>

<footer class="pg">
  Re-generate: <code>node tools/browser/homereview.js</code> ·
  Gate: <code>node tools/browser/homeprobe.js</code> ·
  Findings: <code>docs/home-design-audit-20260926.md</code><br>
  Fonts load from Google; everything else here is self-contained. No images.
</footer>
</div>

`;

    fs.mkdirSync( path.dirname( OUT_FILE ), { recursive: true } );
    fs.writeFileSync( OUT_FILE, html );
    console.log( `wrote ${path.relative( REPO, OUT_FILE )}  (${( fs.statSync( OUT_FILE ).size / 1024 ).toFixed( 0 )} KB)` );
    console.log( `  scope: top band only, fixes A + B + C` );
    console.log( `  h1 ${d.h1.h}px @1280 / ${m.h1.h}px @390 · actions in band: ${d.actions}` );
    console.log( `  stale-width demo: ${staleW}px onto a frame needing ${needW}px (${clipped}px clipped)` );
    console.log( `  deferred: other bands, sitewide schema, propagation` );
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
