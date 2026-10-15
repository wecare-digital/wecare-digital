import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import Cart from '../pages/cart';
import * as cart from '../lib/cart';
import type { ShopProduct } from '../content/shop';

/**
 * THE CART COUPON + GIFT-CARD UI (Section 2), built but honest while the backend gate is off.
 *
 * These pin the things Section 2 is explicit about and that would regress silently:
 *   1. The coupon and gift-card fields, Apply and Remove, exist.
 *   2. Every displayed amount - applied discount, applied gift-card amount, remaining payable -
 *      comes from the SERVER response, never from browser arithmetic. A browser-calculated
 *      discount is never trusted; the component sends a code + action, never an amount.
 *   3. With the backend gate off / endpoint absent / a network failure, the UI shows an honest
 *      unavailable state and cannot transact. A browser signal is never proof of a redemption.
 *   4. No third-party gift-card provider name appears anywhere.
 *   5. No fetch happens at render/prerender time - only on an Apply/Remove click.
 */

// Cart imports next/link only; no router mock needed. Populate localStorage so items render.
const PRODUCT: ShopProduct = {
  id: 'prod-abc-123',
  name: 'Kiosk',
  slug: 'kiosk',
  formattedPrice: '₹24,999.00',
  price: '24999.00',
  currency: 'INR',
  inStock: true,
  tagline: 'Put your location to work.',
  body: [ 'You already have the place.' ],
};

beforeEach( () => {
  window.localStorage.clear();
  cart.addItem( PRODUCT, 1 );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

const renderCart = () => render( <Cart /> );

const couponField = () => screen.getByLabelText( 'Coupon code' );
const giftCardField = () => screen.getByLabelText( 'Gift-card code' );
const applyButtons = () => screen.getAllByRole( 'button', { name: /^Apply/ } );

describe( 'the coupon and gift-card fields exist', () => {
  it( 'renders a coupon field and a gift-card field, each with an Apply', async () => {
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );
    expect( giftCardField() ).toBeInTheDocument();
    // Two Apply buttons: one per field.
    expect( applyButtons().length ).toBe( 2 );
  } );

  it( 'does not fetch at render time, so the static export is not broken', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    renderCart();
    expect( fetchMock ).not.toHaveBeenCalled();
  } );

  it( 'names no third-party gift-card provider anywhere', async () => {
    const { container } = renderCart();
    await waitFor( () => expect( giftCardField() ).toBeInTheDocument() );
    const text = ( container.textContent || '' ).toLowerCase();
    expect( text ).not.toContain( 'gift up' );
    expect( text ).not.toContain( 'giftup' );
  } );
} );

describe( 'amounts are server-authoritative, never browser math', () => {
  it( 'renders the applied coupon discount EXACTLY as the server returns it', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( {
        state: 'REDEMPTION_READY',
        couponReason: 'APPLIED',
        discountPaise: 10000,          // ₹100.00, decided by the server
        remainingPayablePaise: 2489900,
      } ),
    } ) );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'SAVE100' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => {
      expect( screen.getByText( /Applied discount:/ ).textContent ).toContain( '₹100.00' );
    } );
    // A Remove control appears once a coupon is applied.
    expect( screen.getByRole( 'button', { name: 'Remove' } ) ).toBeInTheDocument();
  } );

  it( 'sends a code + action ONLY, never an amount', async () => {
    const fetchMock = vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'REDEMPTION_READY', couponReason: 'APPLIED', discountPaise: 500 } ),
    } );
    vi.stubGlobal( 'fetch', fetchMock );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'SAVE' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 1 ) );
    const [ , init ] = fetchMock.mock.calls[ 0 ];
    const body = JSON.parse( ( init as RequestInit ).body as string );
    expect( body ).toEqual( { kind: 'coupon', action: 'apply', code: 'SAVE' } );
    // No price-like key leaves the browser.
    expect( Object.keys( body ) ).not.toContain( 'amount' );
    expect( Object.keys( body ) ).not.toContain( 'amountPaise' );
    expect( Object.keys( body ) ).not.toContain( 'discountPaise' );
  } );

  it( 'renders the applied gift-card amount and the server remaining payable balance', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( {
        state: 'REDEMPTION_READY',
        giftCardReason: 'APPLIED',
        giftCardAppliedPaise: 40000,       // ₹400.00 verified balance applied, server authority
        remainingPayablePaise: 2459900,    // ₹24,599.00 remaining, server authority
      } ),
    } ) );
    renderCart();
    await waitFor( () => expect( giftCardField() ).toBeInTheDocument() );

    fireEvent.change( giftCardField(), { target: { value: 'GC-123' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 1 ] );

    await waitFor( () => {
      expect( screen.getByText( /Applied gift card:/ ).textContent ).toContain( '₹400.00' );
    } );
    expect( screen.getByText( /Remaining payable balance:/ ).textContent ).toContain( '₹24,599.00' );
  } );

  it( 'shows a zero remaining payable for a fully gift-card-covered order (still gated)', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( {
        state: 'REDEMPTION_READY',
        giftCardReason: 'APPLIED',
        giftCardAppliedPaise: 2499900,
        remainingPayablePaise: 0,          // zero remaining - server authority, not browser math
      } ),
    } ) );
    renderCart();
    await waitFor( () => expect( giftCardField() ).toBeInTheDocument() );

    fireEvent.change( giftCardField(), { target: { value: 'FULL' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 1 ] );

    await waitFor( () => {
      expect( screen.getByText( /Remaining payable balance:/ ).textContent ).toContain( '₹0.00' );
    } );
    // A zero remaining is NOT a success/paid affordance - no such wording appears.
    expect( ( screen.getByText( /Remaining payable balance:/ ).textContent || '' ).toLowerCase() )
      .not.toMatch( /paid|complete|success|thank/ );
  } );
} );

describe( 'typed coupon / gift-card messages come from the server reason', () => {
  it.each( [
    [ 'INVALID', 'not valid' ],
    [ 'EXPIRED', 'expired' ],
    [ 'INELIGIBLE', 'does not apply' ],
  ] )( 'shows a coupon %s message and renders no discount', async ( reason, fragment ) => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'REDEMPTION_READY', couponReason: reason } ),
    } ) );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'X' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => {
      expect( screen.getByText( new RegExp( fragment, 'i' ) ) ).toBeInTheDocument();
    } );
    expect( screen.queryByText( /Applied discount:/ ) ).toBeNull();
  } );

  it( 'shows an insufficient-balance message for a gift card with no balance', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'REDEMPTION_READY', giftCardReason: 'INSUFFICIENT_BALANCE' } ),
    } ) );
    renderCart();
    await waitFor( () => expect( giftCardField() ).toBeInTheDocument() );

    fireEvent.change( giftCardField(), { target: { value: 'EMPTY' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 1 ] );

    await waitFor( () => {
      expect( screen.getByText( /no balance left/i ) ).toBeInTheDocument();
    } );
    expect( screen.queryByText( /Applied gift card:/ ) ).toBeNull();
  } );
} );

describe( 'degrades honestly when the gate is off / endpoint absent / offline', () => {
  it( 'shows an honest unavailable state when the backend gate is off', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true,
      json: async () => ( { state: 'PAYMENT_INITIATION_DISABLED' } ),
    } ) );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'ANY' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => {
      const off = screen.getByText( 'Discounts and gift cards are not available right now.' );
      expect( off.getAttribute( 'data-phase' ) ).toBe( 'unavailable' );
    } );
    // No discount, no success wording.
    expect( screen.queryByText( /Applied discount:/ ) ).toBeNull();
  } );

  it( 'shows the honest state when the endpoint does not exist yet (404)', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 404, json: async () => ( {} ) } ) );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'ANY' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => {
      expect( screen.getByText( 'Discounts and gift cards are not available right now.' ) ).toBeInTheDocument();
    } );
  } );

  it( 'shows the honest state on a network failure, never a success', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockRejectedValue( new Error( 'offline' ) ) );
    renderCart();
    await waitFor( () => expect( couponField() ).toBeInTheDocument() );

    fireEvent.change( couponField(), { target: { value: 'ANY' } } );
    fireEvent.click( screen.getAllByRole( 'button', { name: 'Apply' } )[ 0 ] );

    await waitFor( () => {
      expect( screen.getByText( 'Discounts and gift cards are not available right now.' ) ).toBeInTheDocument();
    } );
  } );
} );
