import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import ContributeBlock, { CONTRIBUTE_BLOCK_AMOUNT_LABEL } from '../components/ContributeBlock';
import { CONTRIBUTE_CTA_HREF } from '../components/BlogContribution';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../config/contribution';
import { isContributionItem, readCart } from '../lib/cart';

/**
 * MINIMAL CONFIRMATION THAT ContributeBlock RENDERS AND BOTH PATHS WORK.
 *
 * The owner will place this block on specific pages later; for now this only confirms it renders
 * the pair of CTAs, points the WhatsApp path at the shared Contribute link, and that the checkout
 * path writes the central-config contribution line and navigates to /cart/ WITHOUT sending any
 * amount from the browser.
 */

const [ ONLY ] = CONTRIBUTION_CHOICES;

beforeEach( () => {
  window.localStorage.clear();
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
} );

describe( 'ContributeBlock', () => {
  it( 'renders an h2 title, the copy, and both CTAs - no second h1', () => {
    const { container } = render( <ContributeBlock /> );

    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2.contribute-title' )?.textContent ).toBe( 'Contribute' );
    expect( container.textContent ).toContain(
      'If this helped, consider a small voluntary contribution.'
    );

    const primary = container.querySelector( 'a.contribute-cta-primary' )!;
    const secondary = container.querySelector( 'button.contribute-cta-secondary' )!;
    expect( primary ).not.toBeNull();
    expect( secondary ).not.toBeNull();
    expect( primary.textContent ).toBe( 'Continue on WhatsApp →' );
    expect( secondary.textContent ).toBe( 'Continue to checkout →' );
  } );

  it( 'points the WhatsApp path at the shared Contribute link and keeps it a real anchor', () => {
    const { container } = render( <ContributeBlock /> );
    const primary = container.querySelector( 'a.contribute-cta-primary' )!;

    expect( primary ).toHaveAttribute( 'href', CONTRIBUTE_CTA_HREF );
    expect( CONTRIBUTE_CTA_HREF ).toBe( 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( primary ).toHaveAttribute( 'target', '_blank' );
    expect( primary ).toHaveAttribute( 'rel', 'noopener noreferrer' );
  } );

  it( 'gives each control an accessible name that contains its visible word (WCAG 2.5.3)', () => {
    const { container } = render( <ContributeBlock /> );
    const primary = container.querySelector( 'a.contribute-cta-primary' )!;
    const secondary = container.querySelector( 'button.contribute-cta-secondary' )!;

    // The accessible name CONTAINS the visible label, so voice input "click Continue" reaches it.
    expect( primary.getAttribute( 'aria-label' ) ).toContain( 'Continue on WhatsApp' );
    expect( secondary.getAttribute( 'aria-label' ) ).toContain( 'Continue to checkout' );
  } );

  it( 'shows the amount from central config as a static label, never a chooseable control', () => {
    const { container } = render( <ContributeBlock /> );

    expect( CONTRIBUTE_BLOCK_AMOUNT_LABEL ).toBe( `\u20B9${ ONLY.rupees }` );
    expect( container.querySelector( '.contribute-amount' )?.textContent )
      .toBe( `${ CONTRIBUTE_BLOCK_AMOUNT_LABEL } \u00B7 voluntary` );
    // Nothing to CHOOSE: no form, radio group, input or select.
    expect( container.querySelectorAll( 'form, input, select, textarea, [role="radiogroup"]' ) )
      .toHaveLength( 0 );
  } );

  it( 'writes the central-config contribution line and navigates to /cart/ on checkout', () => {
    const assign = vi.fn();
    vi.stubGlobal( 'location', { ...window.location, assign } );

    const { container } = render( <ContributeBlock /> );
    // Nothing in the cart until the reader acts.
    expect( readCart() ).toHaveLength( 0 );

    fireEvent.click( container.querySelector( 'button.contribute-cta-secondary' )! );

    // Exactly one contribution line, the single committed choice, at quantity 1 - no amount sent.
    const cart = readCart();
    const contributions = cart.filter( isContributionItem );
    expect( contributions ).toHaveLength( 1 );
    expect( contributions[ 0 ].productId ).toBe( CONTRIBUTION_PRODUCT_ID );
    expect( contributions[ 0 ].variantId ).toBe( ONLY.variantId );
    expect( contributions[ 0 ].quantity ).toBe( 1 );

    // And it goes to the one checkout.
    expect( assign ).toHaveBeenCalledWith( '/cart/' );
  } );

  it( 'drops its own top rule when embedded, and keeps it otherwise', () => {
    const { container: embedded } = render( <ContributeBlock embedded /> );
    expect( embedded.querySelector( 'section' )!.className ).toContain( 'is-embedded' );

    const { container: standalone } = render( <ContributeBlock /> );
    expect( standalone.querySelector( 'section' )!.className ).not.toContain( 'is-embedded' );
  } );
} );
