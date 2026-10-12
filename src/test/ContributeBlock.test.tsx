import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import ContributeBlock, { CONTRIBUTE_BLOCK_AMOUNT_LABEL, CONTRIBUTE_CTA_HREF } from '../components/ContributeBlock';
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
  it( 'renders an h2 title and the one compact line with both path links - no second h1', () => {
    const { container } = render( <ContributeBlock /> );

    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2.contribute-title' )?.textContent ).toBe( 'Contribute' );
    // No copy sentence any more - the block is just the eyebrow + the one line.
    expect( container.textContent ).not.toContain( 'If this helped' );

    // The label carries the static amount; the two links are the two paths.
    expect( container.querySelector( '.contribute-label' )?.textContent )
      .toBe( `Contribute ${ CONTRIBUTE_BLOCK_AMOUNT_LABEL }` );
    const whatsapp = container.querySelector( 'a.contribute-link' )!;
    const website = container.querySelector( 'button.contribute-link-btn' )!;
    expect( whatsapp ).not.toBeNull();
    expect( website ).not.toBeNull();
    expect( whatsapp.textContent ).toBe( 'on WhatsApp' );
    expect( website.textContent ).toBe( 'on the website \u2192' );
  } );

  it( 'points the WhatsApp path at the shared Contribute link and keeps it a real anchor', () => {
    const { container } = render( <ContributeBlock /> );
    const whatsapp = container.querySelector( 'a.contribute-link' )!;

    expect( whatsapp ).toHaveAttribute( 'href', CONTRIBUTE_CTA_HREF );
    expect( CONTRIBUTE_CTA_HREF ).toBe( 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( whatsapp ).toHaveAttribute( 'target', '_blank' );
    expect( whatsapp ).toHaveAttribute( 'rel', 'noopener noreferrer' );
  } );

  it( 'gives each link an accessible name that contains its visible word (WCAG 2.5.3)', () => {
    const { container } = render( <ContributeBlock /> );
    const whatsapp = container.querySelector( 'a.contribute-link' )!;
    const website = container.querySelector( 'button.contribute-link-btn' )!;

    // The accessible name CONTAINS the visible destination word (WhatsApp / website).
    expect( whatsapp.getAttribute( 'aria-label' ) ).toContain( 'WhatsApp' );
    expect( website.getAttribute( 'aria-label' ) ).toContain( 'website' );
  } );

  it( 'shows the amount from central config as a static label, never a chooseable control', () => {
    const { container } = render( <ContributeBlock /> );

    expect( CONTRIBUTE_BLOCK_AMOUNT_LABEL ).toBe( `\u20B9${ ONLY.rupees }` );
    // The amount lives in the label as "Contribute ₹250"; there is no separate amount line now.
    expect( container.querySelector( '.contribute-label' )?.textContent )
      .toBe( `Contribute ${ CONTRIBUTE_BLOCK_AMOUNT_LABEL }` );
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

    fireEvent.click( container.querySelector( 'button.contribute-link-btn' )! );

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
