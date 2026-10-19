import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BrandLockup from '../BrandLockup';

describe( 'BrandLockup', () => {
  it( 'renders the canonical WECARE.DIGITAL brand', () => {
    const { container } = render( <BrandLockup /> );
    expect( screen.getByText( /WECARE/ ) ).toBeInTheDocument();
    expect( screen.getByText( 'DIGITAL' ) ).toBeInTheDocument();
    expect( container.querySelector( '.brand-lockup.full' ) ).toBeTruthy();
  } );


  it( 'provides larger public header and footer variants while keeping narrow-foldable header fallback', () => {
    const { container: header } = render( <BrandLockup className="public-header" /> );
    const headerCss = Array.from( header.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

    expect( headerCss ).toContain( '.brand-lockup.public-header img{height:64px}' );
    expect( headerCss ).toContain( '.brand-lockup.public-header .brand-copy>span{font-size:24px}' );
    expect( headerCss ).toContain( '.brand-lockup.public-header img{height:58px}' );
    expect( headerCss ).toContain( '.brand-lockup.public-header .brand-copy>span{font-size:22px}' );
    expect( headerCss ).toContain( '@media(max-width:340px)' );
    expect( headerCss ).toContain( '.brand-lockup.public-header img{height:54px}' );
    expect( headerCss ).toContain( '.brand-lockup.public-header .brand-copy>span{font-size:21px}' );

    const { container: footer } = render( <BrandLockup compact className="public-footer" /> );
    const footerCss = Array.from( footer.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

    expect( footerCss ).toContain( '.brand-lockup.public-footer.compact img{height:48px}' );
    expect( footerCss ).toContain( '.brand-lockup.public-footer.compact .brand-copy>span{font-size:19px}' );
    expect( footerCss ).toContain( '.brand-lockup.public-footer.compact img{height:44px}' );
    expect( footerCss ).toContain( '.brand-lockup.public-footer.compact .brand-copy>span{font-size:18px}' );
  } );

  it( 'uses the approved shared logo and wordmark scale, stepping down on mobile', () => {
    const { container } = render( <BrandLockup /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

    // Sized DOWN on request: 68 -> 60px logo and 26 -> 23px type on desktop, with mobile
    // scaled by the same ~0.88 to 54px/21px.
    //
    // The header still bounds the desktop value: .hdr-in is height:108px with 18px
    // padding and box-sizing:border-box, so the content box is exactly 72px and 68px was
    // the old ceiling; 60px simply sits further inside it. Mobile is 96px with 14px
    // padding, a 68px box, so 54px clears comfortably. Both header heights are pinned by
    // Header.test.tsx, so the logo is what gives, not the header.
    expect( css ).toContain( 'height:60px' );
    expect( css ).toContain( 'font-size:23px' );
    expect( css ).toContain( 'height:54px' );
    expect( css ).toContain( 'font-size:21px' );

    // THE GENERIC LADDER MUST NOT INVERT. The explicit public-header variant is allowed to use
    // 24px/22px; this assertion is about the base 23px -> 21px pair used by non-public callers.
    // 68px is the retired generic logo size and must not return.
    expect( css ).not.toContain( 'height:68px' );
  } );
} );


describe( 'BrandLockup translation protection', () => {
  /**
   * THE FAILURE THIS PINS. SupportWidget's walker collects text nodes and rewrites
   * nodeValue in place. This lockup renders "WECARE" and "DIGITAL" as two SEPARATE text
   * nodes, and with neither protected both were collected and sent to the translation
   * provider as ordinary English words. On the live site Arabic came back as
   * "نحن نهتم. رقمي" - a literal rendering of "we care" and "digital" - and Hindi produced
   * "WECARE." followed by "डिजिटल", so the wordmark came apart mid-brand.
   *
   * Measured on the built export before the fix: 4 translatable brand text nodes on every
   * route, two from the header lockup and two from the footer's compact one.
   *
   * The flag belongs on the ROOT, not on .brand-copy: `suffix` is a ReactNode a consumer
   * can pass in, and an attribute on the inner wordmark span would leave it unprotected.
   */
  it( 'marks the whole lockup data-wc-no-translate so the wordmark survives translation', () => {
    const { container } = render( <BrandLockup /> );
    const root = container.querySelector( '.brand-lockup' );
    expect( root ).toBeTruthy();
    expect( root?.getAttribute( 'data-wc-no-translate' ) ).toBe( 'true' );
  } );

  it( 'keeps the flag on the compact footer variant too', () => {
    // The footer renders <BrandLockup compact />. It is the same component, so this cannot
    // regress independently - but the footer is where the Arabic screenshot showed the
    // translated wordmark, so it is asserted explicitly rather than assumed from the above.
    const { container } = render( <BrandLockup compact /> );
    const root = container.querySelector( '.brand-lockup.compact' );
    expect( root?.getAttribute( 'data-wc-no-translate' ) ).toBe( 'true' );
  } );

  it( 'protects the wordmark at the root rather than on the inner copy span', () => {
    // Asserting WHERE the flag sits, because the walker takes the nearest flag: on
    // .brand-copy it would cover the two wordmark nodes and miss anything a caller appends.
    const { container } = render( <BrandLockup /> );
    expect( container.querySelector( '.brand-copy' )?.getAttribute( 'data-wc-no-translate' ) ).toBeNull();
    expect( container.querySelector( '.brand-lockup' )?.getAttribute( 'data-wc-no-translate' ) ).toBe( 'true' );
  } );
} );
