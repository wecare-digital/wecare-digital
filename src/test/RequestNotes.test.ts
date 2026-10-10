import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import { CUSTOMERSERVICE } from '../content/customerservice';

/**
 * The boundary note on the request pages, and the rule that renders it.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * Five of the six request pages carry a `note` that is the page's legal boundary - what a
 * third party controls, what we never want sent, how long a document is held, that nothing
 * is published without asking, that a referral is not a fixed rate. `submit-request` has
 * none, deliberately: it asks for nothing and promises nothing. A copy edit that drops a
 * note, or adds one to `submit-request`, changes what the page commits to and nothing else
 * in the suite would notice - `ReviewCta.test.tsx` reads this content file but only asserts
 * `slug`, `ctaLabel` and `ctaHref`.
 *
 * The second half guards the surface. `.pdp-note` is a quiet near-white card BECAUSE lime on
 * this site means actionable: #d1f470 belongs to the CTA and rgba(209,244,112,.22) is
 * already the numbered markers' treatment on the same page. Painting a boundary statement
 * lime would make it compete with the button next to it, which is why the rule and the
 * component header both say so. Asserted on the source, the pattern `SubscribePage.test.tsx`
 * and `ReviewCta.test.tsx` already use, because styled-jsx emits nothing measurable in jsdom.
 */

const ROOT = path.join( __dirname, '..', '..' );
const PRODUCT_PAGE = fs.readFileSync(
  path.join( ROOT, 'src', 'components', 'ProductPage.tsx' ), 'utf8' );

/** The `.pdp-note` declaration block on its own, so a lime value elsewhere cannot pass for it. */
const NOTE_RULE = ( /\.pdp-note\{([^}]*)\}/.exec( PRODUCT_PAGE ) ?? [] )[ 1 ];

const WITH_NOTE = [ 'request-amendment', 'drop-docs', 'vault', 'leave-review', 'refer-and-earn' ];

describe( 'request-page boundary notes', () => {
  it( 'gives all five request pages a note and leaves submit-request without one', () => {
    for ( const slug of WITH_NOTE ) {
      const page = CUSTOMERSERVICE.find( p => p.slug === slug );
      expect( page, slug ).toBeDefined();
      expect( typeof page!.note, slug ).toBe( 'string' );
      expect( page!.note!.trim().length, slug ).toBeGreaterThan( 0 );
    }
    const submit = CUSTOMERSERVICE.find( p => p.slug === 'submit-request' );
    expect( submit ).toBeDefined();
    expect( submit!.note ).toBeUndefined();
  } );
} );

describe( '.pdp-note surface', () => {
  it( 'is the near-white card, not a lime one', () => {
    expect( NOTE_RULE ).toBeDefined();
    expect( NOTE_RULE ).toContain( 'background:#fcfdfb' );
    expect( NOTE_RULE ).not.toContain( '#d1f470' );
    expect( NOTE_RULE ).not.toContain( '209,244,112' );
  } );
} );
