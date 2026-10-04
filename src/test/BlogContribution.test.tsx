import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import BlogContribution from '../components/BlogContribution';
import {
  CONTRIBUTION_PRESETS_PAISE,
  CONTRIBUTION_PURPOSE,
  paiseToRupees,
} from '../config/contribution';

/**
 * THE "SUPPORT THIS WORK" CONTRIBUTION COMPONENT, IN ISOLATION.
 *
 * These cases pin the common contribution contract:
 *   1. The three amounts come from src/config/contribution.ts, not literals in the markup.
 *   2. No custom "Other" option is rendered.
 *   3. With the backend gate off / unavailable / absent, the UI shows an honest non-error state
 *      and renders NO success affordance. A browser signal is never treated as proof of payment.
 */

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

const renderBlock = () =>
  render( <BlogContribution postId="post-1" slug="a-clear-question" /> );

describe( 'BlogContribution presets', () => {
  it( 'renders exactly the three common presets from central config', () => {
    const { container } = renderBlock();
    const faces = Array.from( container.querySelectorAll( '.bc-choice-face' ) )
      .map( n => n.textContent || '' );

    // One face per preset, carrying the rupee value derived from the config's paise.
    for ( const paise of CONTRIBUTION_PRESETS_PAISE ) {
      expect( faces.some( f => f.includes( String( paiseToRupees( paise ) ) ) ) ).toBe( true );
    }
    expect( faces ).toEqual( [ '₹100', '₹250', '₹500' ] );
    expect( faces.some( f => f.includes( 'Other' ) ) ).toBe( false );

    expect( container.querySelectorAll( 'input[type="radio"]' ) )
      .toHaveLength( CONTRIBUTION_PRESETS_PAISE.length );
  } );

  it( 'uses an h2 heading and the mandated primary copy, never an h1', () => {
    const { container } = renderBlock();
    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( container.textContent ).toContain(
      'If you found this useful, you\u2019re welcome to make a small voluntary contribution.'
    );
  } );
} );

describe( 'BlogContribution degrades honestly and never fabricates success', () => {
  it( 'sends the chosen preset, the purpose, postId and slug when a valid amount is submitted', async () => {
    const fetchMock = vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'PAYMENT_INITIATION_DISABLED' } ),
    } );
    vi.stubGlobal( 'fetch', fetchMock );
    renderBlock();

    // First preset is selected by default; submit it.
    fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );

    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 1 ) );
    const [ , init ] = fetchMock.mock.calls[ 0 ];
    const body = JSON.parse( ( init as RequestInit ).body as string );
    expect( init ).toMatchObject( { method: 'POST' } );
    expect( body ).toMatchObject( {
      purpose: CONTRIBUTION_PURPOSE,
      postId: 'post-1',
      slug: 'a-clear-question',
      amountPaise: CONTRIBUTION_PRESETS_PAISE[ 0 ],
      currency: 'INR',
    } );
  } );

  it( 'shows an honest unavailable state when the backend gate is off', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'PAYMENT_INITIATION_DISABLED' } ),
    } ) );
    renderBlock();

    fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );

    await waitFor( () => {
      expect( screen.getByRole( 'status' ).textContent )
        .toBe( 'Contributions are not available right now.' );
    } );
    const status = screen.getByRole( 'status' );
    expect( status.getAttribute( 'data-phase' ) ).toBe( 'unavailable' );
    // NO success affordance: no receipt, no thank-you, no "paid"/"verified" wording.
    expect( status.textContent?.toLowerCase() ).not.toMatch( /paid|verified|thank|receipt|success/ );
  } );

  it( 'shows the same honest state when the endpoint does not exist yet (404)', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: false,
      status: 404,
      json: async () => ( {} ),
    } ) );
    renderBlock();

    fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );

    await waitFor( () => {
      expect( screen.getByRole( 'status' ).textContent )
        .toBe( 'Contributions are not available right now.' );
    } );
  } );

  it( 'shows the honest state on a network failure, never a success', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockRejectedValue( new Error( 'offline' ) ) );
    renderBlock();

    fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );

    await waitFor( () => {
      expect( screen.getByRole( 'status' ).textContent )
        .toBe( 'Contributions are not available right now.' );
    } );
    expect( screen.getByRole( 'status' ).getAttribute( 'data-phase' ) ).toBe( 'unavailable' );
  } );

  it( 'treats CHECKOUT_REJECTED / CHECKOUT_AMBIGUOUS / unknown as unavailable, not success', async () => {
    for ( const state of [ 'CHECKOUT_REJECTED', 'CHECKOUT_AMBIGUOUS', 'SOMETHING_ELSE' ] ) {
      vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
        ok: true,
        json: async () => ( { state } ),
      } ) );
      const { unmount } = renderBlock();

      fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );
      await waitFor( () => {
        expect( screen.getByRole( 'status' ).getAttribute( 'data-phase' ) ).toBe( 'unavailable' );
      } );
      unmount();
      vi.unstubAllGlobals();
    }
  } );

  it( 'does not render a receipt even when the backend reports it is ready', async () => {
    // CHECKOUT_OPTIONS_READY means the server is live and issued a gateway order - it is NOT
    // proof of payment. The component may indicate it is opening a payment, but it must never
    // show a thank-you/receipt, which only an authoritative capture (FEAT-004) can justify.
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( {
        state: 'CHECKOUT_OPTIONS_READY',
        keyId: 'rzp_test_public',
        orderId: 'order_123',
        amountPaise: CONTRIBUTION_PRESETS_PAISE[ 0 ],
        currency: 'INR',
      } ),
    } ) );
    renderBlock();

    fireEvent.click( screen.getByRole( 'button', { name: 'Contribute' } ) );

    await waitFor( () => {
      expect( screen.getByRole( 'status' ).getAttribute( 'data-phase' ) ).toBe( 'ready' );
    } );
    const status = screen.getByRole( 'status' );
    // No fabricated success: "ready" never reads as paid/thank-you/verified.
    expect( status.textContent?.toLowerCase() ).not.toMatch( /paid|verified|thank|receipt|success/ );
  } );

  it( 'does not fetch at render time, so the static export is not broken', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    renderBlock();
    // The default server-rendered state is the available-presets form; a call happens only on a
    // user action, never during render/prerender.
    expect( fetchMock ).not.toHaveBeenCalled();
  } );
} );
