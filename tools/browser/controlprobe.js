#!/usr/bin/env node
/**
 * controlprobe — the harness that can actually measure a <select>.
 *
 * WHY IT EXISTS. designsweep.js:192-194 harvests
 * `main input:not([type=hidden])…, main textarea` and NEVER a select, so until this file
 * landed NO harness in this repo measured the geometry Layer 1.3a changes. Extending
 * designsweep was rejected by the design itself: its field checks assert the home page's
 * input standard against every route, and a select is a different control with a different
 * radius and a chevron, so widening the harvest would make it fail on correct output.
 *
 * WHY IT SEEDS. /cart/ renders NONE of the affected controls without a cart.
 * cart.tsx:1682 is `const isEmpty = ready && items.length === 0`, and .cart-option,
 * .cart-qty and .cart-amount-select all live inside item rows. A fresh Playwright context
 * has an empty localStorage, so an unseeded screenshot of /cart/ shows "Your cart is empty"
 * — an image of nothing this batch touched, offered as evidence for a radius change.
 *
 * ORDER OF OPERATIONS IS THE POINT. It asserts the three controls are PRESENT AND VISIBLE
 * before it records a single number, and fails if any is missing. That one assertion catches
 * a bad seed at the gate rather than at a review, and it does not depend on the reasoning
 * about the seed being right. An earlier revision of the design seeded `crew-t-shirt`, a Wix
 * template sample that src/content/shop.ts:251 filters out of SHOP_PRODUCTS: cart.ts:113
 * would resolve it to null, availableVariantsForItem would return [], needsVariantSelection
 * would return false and .cart-option would never render.
 *
 * STANDING RULE for any product id in a seed, fixture or harness route: check it against
 * SHOP_PRODUCTS in src/content/shop.ts (8 storefront products), NEVER against
 * src/content/wix-catalog.json (21 products).
 *
 * Read-only. Serves the existing static export through lib/serve.js; mutates nothing, sends
 * nothing, and touches no payment path — it reads computed styles.
 *
 *   node tools/browser/controlprobe.js --cart
 *   node tools/browser/controlprobe.js --post <slug>
 *   BASE=http://localhost:3000 node tools/browser/controlprobe.js --cart
 *
 * --post IS BATCH 1.3c'S ONE PUBLIC SURFACE, and the slug is an argument rather than a
 * constant on purpose. post/[slug].tsx's getStaticPaths maps listPublicBlogPosts(), so the
 * exported set is BUILD-TIME DATA; a literal here would be the crew-t-shirt mistake in a
 * different file - a route that does not exist, producing a screenshot of a 404 offered as
 * evidence. Read one from the build and pass it in:
 *
 *   npm run build && node tools/browser/controlprobe.js --post "$( ls out/post | head -1 )"
 *
 * An empty out/post/ means the corpus fetch failed, and the gate fails rather than passing on
 * zero routes.
 */
'use strict';

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );
const { installVisible } = require( './lib/visible' );

const VIEWPORTS = [
  { name: 'desktop 1280x900', width: 1280, height: 900 },
  { name: 'phone 390x844', width: 390, height: 844 },
];

/**
 * The seed. TWO items, because the two selects have different gates:
 *   .cart-amount-select  isContributionItem() → productId === CONTRIBUTION_PRODUCT_ID
 *                        (src/config/contribution.ts:91)
 *   .cart-option         needsVariantSelection() → >1 in-stock variant AND no valid
 *   .cart-qty            variantId, so variantId is DELIBERATELY OMITTED. merchandise is the
 *                        only multi-variant storefront product: 10 variants, all in stock.
 * localStorage key `wecare.cart.v1` is src/lib/cart.ts:59. Written with addInitScript so it
 * exists before the app's first read.
 */
const CART_SEED = [
  {
    productId: '8514c405-3971-4786-ad0d-15406ca23407',
    variantId: 'ab4ee1a2-1568-4dc4-abe1-55e24fa51576',
    ref: '8514c405-3971-4786-ad0d-15406ca23407:ab4ee1a2-1568-4dc4-abe1-55e24fa51576',
    slug: 'contribute', name: 'Contribute', formattedPrice: '₹100.00', quantity: 1,
  },
  {
    productId: 'eca1540e-0a0e-478d-9aa7-e366be277617',
    ref: 'eca1540e-0a0e-478d-9aa7-e366be277617',
    slug: 'merchandise', name: 'Merchandise', formattedPrice: '₹1,199.00', quantity: 1,
  },
];

/** The three controls, and what each one is. */
const CONTROLS = [
  { sel: '.cart-option', what: 'variant select (merchandise row)' },
  { sel: '.cart-qty', what: 'quantity input[type=number]' },
  { sel: '.cart-amount-select', what: 'contribution amount select' },
];

const num = v => {
  const n = parseFloat( String( v ) );
  return Number.isFinite( n ) ? Math.round( n * 100 ) / 100 : null;
};

/**
 * Is this computed box-shadow an actual ring?
 *
 * `!== 'none'` IS NOT ENOUGH, and that is measured rather than defensive: on the pre-batch
 * /cart/ both controls computed `rgba(0, 0, 0, 0) 0px 0px 0px 0px` — a fully transparent,
 * zero-length shadow. It is not `none`, it paints nothing, and a check written as
 * `shadow !== 'none'` reports the ring pairing as PASS on a page where neither control has a
 * ring. A gate that passes in the safe-looking direction is worse than no gate.
 */
const hasRing = v => {
  if ( !v || v === 'none' ) return false;
  if ( /rgba\(\s*\d+,\s*\d+,\s*\d+,\s*0\s*\)/.test( v ) ) return false;   // transparent colour
  return ( v.match( /-?\d+(?:\.\d+)?px/g ) || [] ).some( n => parseFloat( n ) !== 0 );
};

async function probeCart ( browser, base ) {
  let failures = 0;
  const rows = [];
  let focusMode = null;

  for ( const vp of VIEWPORTS ) {
    const context = await browser.newContext( { viewport: { width: vp.width, height: vp.height } } );
    await installVisible( context );
    await context.addInitScript( seed => {
      localStorage.setItem( 'wecare.cart.v1', JSON.stringify( seed ) );
    }, CART_SEED );
    const page = await context.newPage();
    await gotoStable( page, `${base}/cart/` );

    // THE GATE. Present AND visible, for all three, before any number is recorded.
    const presence = await page.evaluate( sels => sels.map( sel => {
      const el = document.querySelector( sel );
      return { sel, present: !!el, visible: !!el && window.__visible( el ) };
    } ), CONTROLS.map( c => c.sel ) );

    let gateOk = true;
    for ( const p of presence ) {
      const control = CONTROLS.find( c => c.sel === p.sel );
      if ( !p.present || !p.visible ) {
        gateOk = false;
        failures++;
        console.error(
          `FAIL ${vp.name}: ${p.sel} (${control.what}) `
          + `${p.present ? 'is present but NOT VISIBLE' : 'DID NOT RENDER'} on the seeded /cart/. `
          + 'The seed did not produce the control this probe exists to measure — fix the seed, '
          + 'do not record a number.'
        );
      }
    }
    if ( !gateOk ) { await context.close(); continue; }

    // Geometry, as numbers. An image cannot distinguish 10px from 13px, which is the change.
    const geometry = await page.evaluate( sels => sels.map( sel => {
      const el = document.querySelector( sel );
      const s = getComputedStyle( el );
      return {
        sel,
        borderTopWidth: s.borderTopWidth,
        borderTopLeftRadius: s.borderTopLeftRadius,
        height: el.getBoundingClientRect().height,
        paddingInlineEnd: s.paddingInlineEnd,
        // Both selects gain a 32px end inset they did not have, so a longer future label must
        // fail this gate rather than clip quietly.
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        tag: el.tagName.toLowerCase(),
      };
    } ), CONTROLS.map( c => c.sel ) );

    for ( const g of geometry ) {
      rows.push( {
        viewport: vp.name,
        control: g.sel,
        borderTopWidth: num( g.borderTopWidth ),
        radius: num( g.borderTopLeftRadius ),
        height: num( g.height ),
        paddingInlineEnd: num( g.paddingInlineEnd ),
        overflow: g.tag === 'select' ? ( g.scrollWidth <= g.clientWidth ? 'PASS' : 'FAIL' ) : '-',
      } );
      if ( g.tag === 'select' && g.scrollWidth > g.clientWidth ) {
        failures++;
        console.error(
          `FAIL ${vp.name}: ${g.sel} overflows — scrollWidth ${g.scrollWidth} > clientWidth `
          + `${g.clientWidth}. An option label no longer fits inside the 32px chevron inset.`
        );
      }
    }

    // The focus ring, for the pairing rule. .cart-amount-select takes --focus-ring from
    // form-controls.css with !important; .cart-qty is type="number" and outside that selector,
    // so its ring is declared at the call site. The two MUST be equal: a `none` on .cart-qty
    // means the call-site declaration was dropped, a `none` on .cart-amount-select means
    // box-shadow lost its !important.
    // SETTLE AFTER FOCUS BEFORE READING, and this is a measured correction rather than caution.
    // form-controls.css transitions `box-shadow` over --transition-normal (0.15s), and the
    // controls transitioned `all` over the same 0.15s before it. A getComputedStyle taken
    // immediately after focus reads the interpolation at t=0, which Chromium reports as
    // `rgba(0, 0, 0, 0) 0px 0px 0px 0px` — the computed form of `none` — on EVERY ring, present
    // or absent. The first run of this probe reported exactly that for both controls at both
    // viewports, before and after the batch, which is a number that cannot distinguish a working
    // ring from a missing one.
    const SETTLE_MS = 300;
    const ring = {};
    for ( const sel of [ '.cart-amount-select', '.cart-qty' ] ) {
      await page.focus( sel );
      await page.waitForTimeout( SETTLE_MS );
      let shadow = await page.evaluate( s => getComputedStyle( document.querySelector( s ) ).boxShadow, sel );
      let mode = 'page.focus()';
      // If programmatic focus does not satisfy :focus-visible in this Chromium, establish
      // keyboard modality with a real Tab and focus again — and SAY which was used. No DOM is
      // inserted: Chromium grants :focus-visible to a programmatically focused control once
      // the user has used the keyboard, so one Tab is enough and the page is left as it was.
      if ( !hasRing( shadow ) ) {
        await page.keyboard.press( 'Tab' );
        await page.focus( sel );
        await page.waitForTimeout( SETTLE_MS );
        shadow = await page.evaluate( s => getComputedStyle( document.querySelector( s ) ).boxShadow, sel );
        mode = "page.keyboard.press('Tab') then page.focus()";
      }
      ring[ sel ] = shadow;
      focusMode = focusMode && focusMode !== mode ? `${focusMode} + ${mode}` : mode;
    }

    const pairOk = ring[ '.cart-amount-select' ] === ring[ '.cart-qty' ]
      && hasRing( ring[ '.cart-amount-select' ] );
    if ( !pairOk ) {
      failures++;
      console.error(
        `FAIL ${vp.name}: focus ring pairing — .cart-amount-select "${ring[ '.cart-amount-select' ]}" `
        + `vs .cart-qty "${ring[ '.cart-qty' ] }". They must be the SAME value and it must paint: `
        + 'a none, or a transparent zero-length shadow, is not a ring.'
      );
    }
    console.log(
      `${vp.name}  focus ring via ${focusMode}  `
      + `.cart-amount-select = ${ring[ '.cart-amount-select' ]}  `
      + `.cart-qty = ${ring[ '.cart-qty' ]}  ${pairOk ? 'PASS' : 'FAIL'}`
    );

    await context.close();
  }

  console.table( rows );
  return failures;
}

/**
 * --post: THE RADIO, PUBLICLY AND FOR REAL. The only checkbox-or-radio surface in this repo a
 * harness can reach at all.
 *
 * WHAT IS ON THE PAGE. post/[slug].tsx:533 renders <BlogContribution> with no gate, and the
 * component renders CONTRIBUTION_CHOICES' three radios unconditionally while initialising
 * variantId to the first choice - so ONE radio is checked and TWO are not, both states on
 * screen in one shot, at both viewports, with no seeding and no interaction.
 *
 * THE GATE IS NOT "PRESENT AND VISIBLE" ON THE RADIO, AND THAT IS A CORRECTION RATHER THAN A
 * RELAXATION. The design asked for `input[type="radio"]` to be asserted present AND VISIBLE.
 * Measured, that assertion cannot pass on this surface and never could:
 * BlogContribution.tsx:233 is `.bc-radio{position:absolute;opacity:0;width:1px;height:1px}`,
 * so the radio is visually hidden BY CONSTRUCTION and the control a visitor actually sees is
 * the sibling `.bc-choice-face` pill. A probe written to the letter would fail on correct
 * output, which is the one thing a gate must not do. So it asserts the four things that are
 * both true and worth proving, and fails before recording a single number if any is wrong:
 *
 *   1. exactly THREE input[type="radio"] are present - the page really rendered the widget
 *   2. ALL THREE carry [data-ui-raw] - the opt-out batch 1.3c adds is actually on the element
 *   3. the three .bc-choice-face pills are present AND VISIBLE - the control a user sees
 *   4. exactly ONE radio is checked - so checked and unchecked are both on screen
 *
 * AND THEN THE NUMBERS THAT PROVE THE OPT-OUT WORKS. The opt-out is tested on the properties
 * form-controls.css DECLARES - `appearance: none`, a 2px border and a 9999px radius, all three
 * with !important - and NOT on the element's width.
 *
 * WIDTH WAS THE FIRST ATTEMPT AND IT WAS WRONG, which is worth keeping because it failed in the
 * direction that looks like a bug in the code under test. The reasoning was: our rule draws an
 * 18px box, `.bc-radio` declares 1px, so width > 2 means the skin leaked past [data-ui-raw].
 * Measured, the hidden radio computes 1x32 at 1280px and 44x32 at 390px - and the 44 is
 * tokens.css:581's PRE-EXISTING `@media (max-width: 768px) { input[type="radio"] { min-width:
 * 44px } }`, which has nothing to do with this batch and which `min-width` beats a 1px `width`
 * with regardless of who declared it. So the first run reported a leak that was not there, on a
 * rule that predates the task. Measured on the same control, `appearance`, `border-width` and
 * `border-radius` are all still the UA's, which is the actual question.
 *
 * The width and height are still RECORDED, because they corroborate something the design could
 * only derive: Layout.css:127's `min-height: 32px` really does beat tokens.css:581's 44px at
 * EVERY viewport, phone included - the height is 32px at 390px - while the unopposed
 * `min-width: 44px` really does hold there. That is half of the cascade claim batch 1.3c's
 * media block exists to correct, measured on a public route rather than predicted.
 */
const POST_RADIO = 'input[type="radio"]';
const POST_FACE = '.bc-choice-face';

async function probePost ( browser, base, slug ) {
  let failures = 0;
  const rows = [];

  for ( const vp of VIEWPORTS ) {
    const context = await browser.newContext( { viewport: { width: vp.width, height: vp.height } } );
    await installVisible( context );
    const page = await context.newPage();
    await gotoStable( page, `${base}/post/${slug}/` );

    const state = await page.evaluate( ( [ radioSel, faceSel ] ) => {
      const radios = [ ...document.querySelectorAll( radioSel ) ];
      const faces = [ ...document.querySelectorAll( faceSel ) ];
      const read = el => {
        const s = getComputedStyle( el );
        return {
          width: s.width, height: s.height, opacity: s.opacity,
          appearance: s.appearance || s.webkitAppearance,
          borderTopWidth: s.borderTopWidth, borderTopLeftRadius: s.borderTopLeftRadius,
          backgroundImage: s.backgroundImage === 'none' ? 'none' : 'image',
        };
      };
      return {
        radioCount: radios.length,
        optedOut: radios.filter( r => r.hasAttribute( 'data-ui-raw' ) ).length,
        checked: radios.filter( r => r.checked ).length,
        faceCount: faces.length,
        facesVisible: faces.filter( f => window.__visible( f ) ).length,
        radio: radios.length ? read( radios[ 0 ] ) : null,
        face: faces.length ? read( faces[ 0 ] ) : null,
        checkedFace: faces.length ? read( faces[ 0 ] ) : null,
      };
    }, [ POST_RADIO, POST_FACE ] );

    // THE GATE, all four parts, before any number is recorded.
    const problems = [];
    if ( state.radioCount !== 3 ) {
      problems.push( `expected 3 ${POST_RADIO}, found ${state.radioCount} - BlogContribution did not render` );
    }
    if ( state.optedOut !== state.radioCount || state.radioCount === 0 ) {
      problems.push( `${state.optedOut} of ${state.radioCount} radios carry [data-ui-raw] - the opt-out is missing from the call site` );
    }
    if ( state.faceCount !== 3 || state.facesVisible !== 3 ) {
      problems.push( `expected 3 visible ${POST_FACE} pills, found ${state.faceCount} present / ${state.facesVisible} visible` );
    }
    if ( state.checked !== 1 ) {
      problems.push( `expected exactly 1 checked radio, found ${state.checked} - checked and unchecked are not both on screen` );
    }
    if ( problems.length ) {
      failures += problems.length;
      for ( const p of problems ) console.error( `FAIL ${vp.name}: ${p}` );
      await context.close();
      continue;
    }

    // THE OPT-OUT TEST, on the three properties form-controls.css declares with !important.
    // If any of them is ours, the skin reached a control a call site deliberately hid and is
    // drawing a second one on top of the pill.
    const leaks = [];
    if ( state.radio.appearance === 'none' ) leaks.push( 'appearance: none' );
    if ( parseFloat( state.radio.borderTopWidth ) > 0 ) leaks.push( `border ${state.radio.borderTopWidth}` );
    if ( parseFloat( state.radio.borderTopLeftRadius ) > 0 ) leaks.push( `radius ${state.radio.borderTopLeftRadius}` );
    if ( state.radio.backgroundImage !== 'none' ) leaks.push( 'a drawn indicator' );
    if ( leaks.length ) {
      failures++;
      console.error(
        `FAIL ${vp.name}: the hidden radio has taken ${leaks.join( ', ' )} - form-controls.css `
        + 'reached it despite [data-ui-raw], so a second control is being drawn over the pill.'
      );
    }

    rows.push( {
      viewport: vp.name,
      control: POST_RADIO + ' (hidden, data-ui-raw)',
      width: num( state.radio.width ), height: num( state.radio.height ),
      opacity: state.radio.opacity,
      appearance: state.radio.appearance,
      borderTopWidth: num( state.radio.borderTopWidth ),
      radius: num( state.radio.borderTopLeftRadius ),
      indicator: state.radio.backgroundImage,
      optOut: leaks.length ? 'FAIL' : 'PASS',
    } );
    rows.push( {
      viewport: vp.name,
      control: POST_FACE + ' (the control a user sees)',
      width: num( state.face.width ), height: num( state.face.height ),
      opacity: state.face.opacity,
      appearance: state.face.appearance,
      borderTopWidth: num( state.face.borderTopWidth ),
      radius: num( state.face.borderTopLeftRadius ),
      indicator: state.face.backgroundImage,
      optOut: '-',
    } );

    console.log(
      `${vp.name}  /post/${slug}/  3 radios, 3 with [data-ui-raw], `
      + `${state.checked} checked, 3 visible pills, hidden radio ${num( state.radio.width )}x`
      + `${num( state.radio.height )} appearance:${state.radio.appearance} border:`
      + `${num( state.radio.borderTopWidth )}  ${leaks.length ? 'FAIL' : 'PASS'}`
    );
    await context.close();
  }

  console.table( rows );
  return failures;
}

( async () => {
  const argv = process.argv.slice( 2 );
  const postIndex = argv.indexOf( '--post' );
  const wantCart = argv.includes( '--cart' );
  const slug = postIndex >= 0 ? argv[ postIndex + 1 ] : null;

  if ( !wantCart && postIndex < 0 ) {
    console.error( 'usage: node tools/browser/controlprobe.js --cart' );
    console.error( '       node tools/browser/controlprobe.js --post <slug>' );
    console.error( '  the slug is build-time data - read one with `ls out/post | head -1`.' );
    process.exit( 2 );
  }
  if ( postIndex >= 0 && ( !slug || slug.startsWith( '--' ) ) ) {
    console.error( '--post needs a slug, e.g. --post "$( ls out/post | head -1 )".' );
    console.error( '  An empty out/post/ means the corpus fetch failed; that is a FAILURE, not zero work.' );
    process.exit( 2 );
  }

  const site = await target();
  const browser = await launch();
  let failures = 0;
  try {
    if ( wantCart ) failures += await probeCart( browser, site.base );
    if ( slug ) failures += await probePost( browser, site.base, slug );
  } finally {
    await browser.close();
    await site.close();
  }

  console.log( failures === 0 ? '\ncontrolprobe: PASS' : `\ncontrolprobe: ${failures} FAILURE(S)` );
  process.exit( failures === 0 ? 0 : 1 );
} )().catch( err => { console.error( err ); process.exit( 2 ); } );
