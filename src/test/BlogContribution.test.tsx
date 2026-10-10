import fs from 'fs';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import BlogContribution, { CONTRIBUTE_CTA_HREF } from '../components/BlogContribution';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../config/contribution';
import type { ShopProduct } from '../content/shop';
import {
  addItem, basketFingerprint, cartCount, clearCart, readCart, setContribution, toLineItems,
} from '../lib/cart';

/**
 * A kiosk to stand beside a contribution, so the mixed-basket cases have something to mix.
 *
 * THE ID IS DELIBERATELY NOT UUID-SHAPED, and that is a repair rather than a style choice. It
 * used to be `00d4c72b-f694-441a-a192-e16f4b192440`, a well-formed catalogue id that
 * `KNOWN_CATALOGUE_PRODUCT_IDS` does not contain -- so `droppableUnknown` pruned this line on
 * every `readCart()` and the kiosk was never in the cart at all.
 *
 * `droppableUnknown` only drops a line whose claimed id is UUID-shaped, which is the pre-migration
 * row it exists for. A non-UUID id therefore survives reconciliation for the same reason
 * CartCheckout.test.tsx's `wix-abc-123` does, and will keep surviving the next re-mint -- which a
 * real id copied out of today's snapshot would not.
 */
const KIOSK: ShopProduct = {
  id: 'wix-kiosk-001',
  name: 'Kiosk',
  slug: 'kiosk',
  formattedPrice: '\u20B924,999.00',
  price: '24999.00',
  currency: 'INR',
  inStock: true,
  tagline: 'A kiosk.',
  body: [],
  variants: [ { id: '9f1c0e8a-1111-4222-8333-444455556666', label: 'One', inStock: true } ],
};

/**
 * The ONLY choice, so the cart cases below can name the amount without re-typing a GUID.
 *
 * STILL READ FROM THE CONFIG EVEN THOUGH THE COMPONENT NO LONGER TOUCHES IT. The cart half of
 * this file tests `src/lib/cart.ts`'s contribution line, which the server and /cart/ still own;
 * only the BLOCK stopped writing it. See the next docblock.
 */
const [ ONLY ] = CONTRIBUTION_CHOICES;

/**
 * THE "CONTRIBUTE" BLOCK, IN ISOLATION - NOW ONE WHATSAPP LINK.
 *
 * OWNER INSTRUCTION, 2026-10-10: both button-looking things in this block are gone - the ₹250
 * amount pill AND the "Contribute ₹250" submit - and the block hands the reader to WhatsApp the
 * way every other "ask us for something" surface on this site already does. So the cases that
 * drove this component changed with it, and the shape of what they assert changed too:
 *
 *   WAS: the offered amounts come from the central config; choosing one writes ONE cart line at
 *        quantity 1 and navigates to /cart/; an unconfigured build renders an honest line and no
 *        form.
 *   IS:  the block renders exactly ONE anchor, at the owner's Contribute message link, a
 *        TEXT-ONLY pill carrying the single word "Contribute" (no glyph), with a short
 *        `.bc-cta-note` microcopy line "Continue on WhatsApp →" below it - and NO form, NO radio
 *        group, NO button, and nothing written to the cart by rendering or by clicking.
 *
 * THE DESIGN MOVED TWICE, AND THE MICROCOPY IS THE SETTLED FORM. The brief asked for a muted line
 * under the pill; the owner then tried a WhatsApp glyph on the button instead; on seeing it the
 * owner found the logo inside the filled pill too busy and dropped it. The settled design is a
 * text-only pill with a very short microcopy line "Continue on WhatsApp →" below it. The chain is
 * recorded at .agents/tasks/contribute-whatsapp-cta/owner-decision.md, which is what the
 * `.bc-cta-note` presence cases below hold the component to.
 *
 * WHAT WENT, AND WHY IT IS NOT A HOLE IN COVERAGE:
 *   - Every choices/radio/submit case. There is no control left to choose with, and the
 *     "replaces rather than adds" property now belongs to `setContribution` alone, which the
 *     cart-level case below still drives directly.
 *   - The honest-unavailable case. It mocked `CONTRIBUTION_CONFIGURED: false` to prove a build
 *     with no contribution vehicle offers no button that cannot work. A static wa.me link needs
 *     no configuration, so that state no longer exists in this component; `CONTRIBUTION_CONFIGURED`
 *     itself is unchanged and still pinned by src/test/ShopCatalogue.test.tsx.
 *   - The two "no network on submit" cases. There is no submit. The render-time guard is kept
 *     below, because a static export is still what this block ships into.
 *
 * The cart and fingerprint cases are NOT removed: `src/config/contribution.ts`, the Wix
 * `Contribute` product line and /cart/'s checkout path are all untouched by this change, and
 * these are the only unit cases that drive `setContribution` end to end.
 */

beforeEach( () => {
  // localStorage persists across cases in one jsdom environment, and most of these cases assert
  // on the cart's CONTENTS -- so a leftover line from the previous case would be read as this
  // one's result.
  window.localStorage.clear();
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
} );

const renderBlock = () =>
  render( <BlogContribution postId="post-1" slug="a-clear-question" /> );

const SOURCE = fs.readFileSync(
  path.resolve( __dirname, '../components/BlogContribution.tsx' ), 'utf8' );

describe( 'BlogContribution is one WhatsApp link', () => {
  it( 'renders exactly one anchor, at the owner Contribute message link', () => {
    const { container } = renderBlock();
    const links = Array.from( container.querySelectorAll( 'a' ) );
    expect( links ).toHaveLength( 1 );
    // The exact URL, pinned as a literal as well as through the exported constant: the constant
    // proves the markup cannot drift from one source, the literal proves that source is still
    // the link the owner gave. Modelled on SubscribePage.test.tsx / ShipmentsPage.test.tsx.
    expect( CONTRIBUTE_CTA_HREF ).toBe( 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( links[ 0 ] ).toHaveAttribute( 'href', 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( container.querySelectorAll( 'a[href*="wa.me"]' ) ).toHaveLength( 1 );
    // And it is not the SUBSCRIBE conversation, which is a different Meta message link living on
    // the same page. Merging the two is the one mistake that would look right on screen.
    expect( links[ 0 ].getAttribute( 'href' ) ).not.toContain( 'WUDPTMYSO6XII1' );
  } );

  it( 'is the Subscribe button\'s twin: a text-only pill plus "Continue on WhatsApp" microcopy', () => {
    const { container } = renderBlock();
    const link = container.querySelector( 'a' )!;

    // ONE WORD on the pill, exactly as .blog-wa-subscribe carries one word. TEXT ONLY - the
    // owner dropped the glyph because the logo inside the filled pill read as too busy.
    expect( link.querySelector( 'span' )?.textContent ).toBe( 'Contribute' );
    expect( link.textContent ).toBe( 'Contribute' );
    // NO glyph on the button any more.
    expect( link.querySelector( 'svg' ) ).toBeNull();

    // THE MICROCOPY carries the destination the button no longer shows, in three words and a
    // trailing arrow. aria-hidden because the anchor's accessible name already says
    // "on WhatsApp"; see owner-decision.md for the design chain.
    const note = container.querySelector( '.bc-cta-note' );
    expect( note ).not.toBeNull();
    expect( note!.textContent ).toBe( 'Continue on WhatsApp \u2192' );
    expect( note!.getAttribute( 'aria-hidden' ) ).toBe( 'true' );
    // The old "no subtext" assertion is retired: there is now one copy line above the pill and
    // one microcopy line below it, and no radio-era .bc-note remains.
    expect( container.querySelector( '.bc-note' ) ).toBeNull();
    expect( container.querySelectorAll( 'p' ) ).toHaveLength( 2 );
    expect( container.querySelector( 'p' )!.className ).toContain( 'bc-copy' );
  } );

  it( 'opens WhatsApp the way the Subscribe anchor on the same page does', () => {
    // Matched to the SIBLING on the post page (a.blog-wa-subscribe), not to the /subscribe/ page
    // CTA: two WhatsApp buttons 44px apart behaving differently is the drift this change removes.
    const link = renderBlock().container.querySelector( 'a' )!;
    expect( link ).toHaveAttribute( 'target', '_blank' );
    expect( link ).toHaveAttribute( 'rel', 'noopener noreferrer' );
    // WCAG 2.5.3 Label in Name: the accessible name CONTAINS the visible word, so "click
    // Contribute" by voice reaches it. Same contract as "Subscribe on WhatsApp" above it.
    expect( link ).toHaveAttribute( 'aria-label', 'Contribute on WhatsApp' );
    expect( link.getAttribute( 'aria-label' ) ).toContain( link.textContent );
  } );

  it( 'has NO form, radio group, field or button, and offers no amount to choose', () => {
    const { container } = renderBlock();
    expect( container.querySelectorAll( 'form, input, textarea, select, button' ) ).toHaveLength( 0 );
    expect( container.querySelector( '[role="radiogroup"]' ) ).toBeNull();
    expect( container.querySelector( 'fieldset' ) ).toBeNull();
    // The retired amount pill and its furniture, by class as well as by element.
    expect( container.querySelector( '.bc-choice-face' ) ).toBeNull();
    expect( container.querySelector( '.bc-radio' ) ).toBeNull();
    // No rupee figure anywhere: the amount is settled in the conversation now, so a number on
    // this block would be a price the reader has not been quoted.
    expect( container.textContent || '' ).not.toContain( '\u20B9' );
    expect( container.textContent || '' ).not.toMatch( /choose an amount/i );
  } );

  it( 'adds NOTHING to the cart, on render or on clicking through', () => {
    const assign = vi.fn();
    vi.stubGlobal( 'location', { ...window.location, assign } );
    const { container } = renderBlock();
    container.querySelector( 'a' )!.click();

    expect( readCart() ).toHaveLength( 0 );
    // And it does not navigate: the anchor's own href is the whole behaviour.
    expect( assign ).not.toHaveBeenCalled();
  } );

  it( 'uses an h2 heading, keeps the mandated copy line, and stays attributable', () => {
    const { container } = renderBlock();
    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( container.querySelector( 'h2' )?.id ).toBe( 'bc-title' );
    expect( container.textContent ).toContain(
      'If you found this useful, you\u2019re welcome to make a small voluntary contribution.'
    );
    // data-post-id survives the rewrite: the attribution-shape cases elsewhere find this block
    // by it, and the props are unchanged on purpose.
    const section = container.querySelector( 'section.bc' )!;
    expect( section.getAttribute( 'data-post-id' ) ).toBe( 'post-1' );
    expect( section.getAttribute( 'aria-labelledby' ) ).toBe( 'bc-title' );
  } );

  it( 'drops its own top rule when embedded, and keeps it otherwise', () => {
    const { container } = render( <BlogContribution postId="p" slug="s" embedded /> );
    expect( container.querySelector( 'section' )!.className ).toContain( 'is-embedded' );
    expect( renderBlock().container.querySelector( 'section' )!.className )
      .not.toContain( 'is-embedded' );
  } );

  it( 'keeps the palette, the opaque focus ring and the reduced-motion block', () => {
    expect( SOURCE ).toMatch( /prefers-reduced-motion:reduce/ );
    expect( SOURCE ).toMatch( /#d1f470/ );
    expect( SOURCE ).toMatch( /#1a3a2a/ );
    // 3px offset now, not 2px: the control is the site's pill object, which rings OUTSIDE itself
    // (PillButton and .blog-wa-subscribe both do). The 2px offset belonged to the amount pill's
    // hidden radio, which is gone.
    expect( SOURCE ).toMatch( /outline:3px solid #1a3a2a;outline-offset:3px/ );
  } );

  it( 'puts NO fee or price disclosure under the CTA', () => {
    // OWNER DECISION [PHASE2-FEE-001] is answered fee-exempt, and this block now quotes no
    // figure at all, so any sentence about a fee would be its own small untruth.
    const text = renderBlock().container.textContent || '';
    expect( text ).not.toMatch( /fee/i );
    expect( text ).not.toMatch( /convenience/i );
    expect( text ).not.toMatch( /GST/ );
  } );
} );

describe( 'the second payment implementation is GONE, not disabled', () => {
  /**
   * T12. The claim is now stronger than it was: this component used to POST to an endpoint that
   * answered 404, then it put a line in the cart and navigated. It does NEITHER. There is no
   * fetch, no cart write and no payment state in it, because a second money path is the failure
   * this guard exists to prevent.
   */
  it( 'names no contribution endpoint, no cart write and no navigation in its source', () => {
    // A source pin, because an unused import is the step before a reinstated form.
    expect( SOURCE ).not.toMatch( /CONTRIBUTION_INITIATE_URL/ );
    // The endpoint PATH is deliberately not asserted absent: the docblock explaining what this
    // component no longer does necessarily names the old path, and a text search cannot tell an
    // explanation from a call site. What is asserted is the absence of anything that could USE
    // one - the fetch, the state machine, the cart writer and the navigation.
    expect( SOURCE ).not.toMatch( /\bfetch\s*\(/ );
    expect( SOURCE ).not.toMatch( /CHECKOUT_OPTIONS_READY/ );
    expect( SOURCE ).not.toMatch( /PAYMENT_INITIATION_DISABLED/ );
    expect( SOURCE ).not.toMatch( /useState/ );
    // `setContribution` and `location.assign` are NOT asserted absent from the source for the
    // same reason as the endpoint path: the docblock that records what this block stopped doing
    // names both. Their absence is asserted where it is observable instead - the cart is empty
    // and nothing navigates after a click, two cases up.
    expect( SOURCE ).not.toMatch( /from '\.\.\/lib\/cart'/ );
    expect( SOURCE ).not.toMatch( /from '\.\.\/config\/contribution'/ );
  } );

  it( 'writes nothing for a variant that is not a committed choice', () => {
    // Unreachable from this component - it has no control at all now - and reachable from a cart
    // written by an older build or a console call. Membership is the only check left.
    expect( setContribution( '00000000-0000-4000-8000-000000000000' ) ).toHaveLength( 0 );
    expect( readCart() ).toHaveLength( 0 );
  } );

  it( 'writes ONE cart line at QUANTITY 1 when the cart layer is asked directly', () => {
    // THE BLOCK NO LONGER CALLS THIS, and the line it writes is still the one /cart/ and the
    // server price. Driven at the library rather than through a control, which is where the
    // behaviour now lives.
    setContribution( ONLY.variantId );
    const cart = readCart();
    expect( cart ).toHaveLength( 1 );
    // QUANTITY 1, not the rupee figure: the amount is the variant's own price, so nothing about
    // the amount is carried by the quantity.
    expect( cart[ 0 ].quantity ).toBe( 1 );
    expect( cart[ 0 ].productId ).toBe( CONTRIBUTION_PRODUCT_ID );
    expect( cart[ 0 ].variantId ).toBe( ONLY.variantId );
    expect( cart[ 0 ].name ).toBe( `Contribute \u20B9${ ONLY.rupees }` );
    expect( cart[ 0 ].formattedPrice ).toBe( `\u20B9${ ONLY.rupees }.00` );
    // Empty slug, so the cart row does NOT link to a /shop/contribute/ page that SHOP_PRODUCTS
    // deliberately excludes.
    expect( cart[ 0 ].slug ).toBe( '' );
  } );

  it( 'REPLACES rather than adds when the same amount is set twice', () => {
    // `setContribution` does not reuse `addItem`, which INCREMENTS -- and two contribution lines,
    // or one at quantity 2, is a basket the server refuses rather than a bigger contribution.
    setContribution( ONLY.variantId );
    setContribution( ONLY.variantId );
    const cart = readCart();
    expect( cart ).toHaveLength( 1 );
    expect( cart[ 0 ].variantId ).toBe( ONLY.variantId );
    expect( cart[ 0 ].quantity ).toBe( 1 );
  } );

  it( 'offers one fixed price in the config, which is the whole set the server accepts', () => {
    // The paise figures are what `blog_contribution.CONTRIBUTION_CHOICES_PAISE` holds, and
    // tests/test_blog_contribution.py pins the two declarations equal. This side asserts the
    // rupee/paise pair is internally consistent, so a typo in one of the two numbers cannot pass
    // by agreeing with the Python copy of the same typo. The CONFIG is untouched by the WhatsApp
    // change: the cart line and the checkout path it describes are still live.
    for ( const choice of CONTRIBUTION_CHOICES ) {
      expect( choice.paise ).toBe( choice.rupees * 100 );
      expect( choice.variantId ).toMatch( /^[0-9a-f-]{36}$/ );
    }
    expect( CONTRIBUTION_CHOICES ).toHaveLength( 1 );
    expect( new Set( CONTRIBUTION_CHOICES.map( c => c.variantId ) ).size ).toBe( 1 );
  } );
} );

describe( 'cartCount and basketFingerprint, which the header and the request key read', () => {
  it( 'counts a contribution as ONE, which is now its real quantity', () => {
    // Under the retired amount-as-quantity model this needed a special case in `cartCount`, or a
    // ₹400 contribution rendered "Shopping Bag, 400 items". The line is quantity 1 now, so the
    // plain sum is the honest answer and the special case is gone.
    setContribution( ONLY.variantId );
    expect( cartCount() ).toBe( 1 );
    expect( readCart()[ 0 ].quantity ).toBe( 1 );
  } );

  it( 'counts a contribution plus a kiosk at quantity 2 as THREE', () => {
    setContribution( ONLY.variantId );
    addItem( KIOSK, 2 );
    expect( cartCount() ).toBe( 3 );
  } );

  it( 'is stable across two calls on an unchanged cart', () => {
    setContribution( ONLY.variantId );
    expect( basketFingerprint() ).toBe( basketFingerprint() );
  } );

  it( 'is order-independent for the same lines added either way', () => {
    addItem( KIOSK, 1 );
    setContribution( ONLY.variantId );
    const forwards = basketFingerprint();
    clearCart();
    setContribution( ONLY.variantId );
    addItem( KIOSK, 1 );
    expect( basketFingerprint() ).toBe( forwards );
  } );

  it( 'CHANGES when the contribution basket changes', () => {
    // A changed basket IS a changed intent: `intent_fingerprint` covers `total_payable_paise`, so
    // resuming the old reservation for it is exactly the refusal the scoping removes.
    setContribution( ONLY.variantId );
    const before = basketFingerprint();
    addItem( KIOSK, 1 );
    expect( basketFingerprint() ).not.toBe( before );
  } );

  it( 'carries a digest, a length and a line count, and the count is the real one', () => {
    setContribution( ONLY.variantId );
    addItem( KIOSK, 1 );
    const fingerprint = basketFingerprint();
    expect( fingerprint ).toMatch( /^[0-9a-z]+\.[0-9a-z]+\.\d+$/ );
    expect( Number( fingerprint.split( '.' )[ 2 ] ) ).toBe( toLineItems().length );
  } );

  it( 'agrees between the explicit and default forms, and the explicit one describes its argument', () => {
    setContribution( ONLY.variantId );
    const payload = toLineItems();
    expect( basketFingerprint( payload ) ).toBe( basketFingerprint() );
    // Mutate storage WITHOUT re-reading: the explicit form must still describe the array it was
    // handed, which is the property that stops the post-save retry keying a basket it is not
    // sending.
    addItem( KIOSK, 1 );
    expect( basketFingerprint( payload ) ).not.toBe( basketFingerprint() );
    expect( basketFingerprint( payload ) ).toBe( basketFingerprint( payload ) );
  } );
} );

describe( 'BlogContribution does not fetch at render time', () => {
  it( 'does not fetch at render time, so the static export is not broken', () => {
    // STILL MEANINGFUL, and now trivially true by construction: the block is one anchor, so
    // there is no state, no effect and nothing to call. Kept because the thing it guards - a
    // static export that prerenders this block on every post - has not changed.
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    renderBlock();
    expect( fetchMock ).not.toHaveBeenCalled();
  } );
} );
