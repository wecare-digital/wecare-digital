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
 *   BASE=http://localhost:3000 node tools/browser/controlprobe.js --cart
 *
 * --post is reserved for batch 1.3c's checkbox/radio surface and is not implemented here.
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

( async () => {
  const modes = process.argv.slice( 2 );
  if ( !modes.includes( '--cart' ) ) {
    console.error( 'usage: node tools/browser/controlprobe.js --cart' );
    console.error( '  --post is reserved for batch 1.3c and is not implemented yet.' );
    process.exit( 2 );
  }

  const site = await target();
  const browser = await launch();
  let failures = 0;
  try {
    failures += await probeCart( browser, site.base );
  } finally {
    await browser.close();
    await site.close();
  }

  console.log( failures === 0 ? '\ncontrolprobe: PASS' : `\ncontrolprobe: ${failures} FAILURE(S)` );
  process.exit( failures === 0 ? 0 : 1 );
} )().catch( err => { console.error( err ); process.exit( 2 ); } );
