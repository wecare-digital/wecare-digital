import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import CheckoutIdentityCard from '../components/CheckoutIdentityCard';
import type { StoredAddress } from '../components/AddressFields';

/**
 * THE FIRST TEST HERE IS A DRIFT GUARD, NOT A RENDERING TEST.
 *
 * `fullAddress` is derived server-side and is the string that reaches Wix and the invoice. If
 * anyone ever composes the Deliver line in the card from the six components instead, the card
 * starts reassuring the customer about a second rendering of the address that nothing downstream
 * uses - and the two can disagree without either side being obviously wrong.
 *
 * So the fixture is built to DISAGREE on purpose: its `fullAddress` names 7 Residency Road and
 * PIN 560002, while its components say 12 MG Road and 560001. Any composition from the components
 * produces a line this test rejects. A fixture where the two agree could not tell the difference.
 */
const ADDRESS: StoredAddress = {
  addressLine1: '12 MG Road',
  addressLine2: 'Flat 3B',
  locality: '',
  city: 'Bengaluru',
  state: 'Karnataka',
  postalCode: '560001',
  country: 'India',
  countryCode: 'IN',
  fullAddress: '7 Residency Road, Bengaluru, Karnataka, 560002, India',
};

const IDENTITY = {
  name: 'Rahul Sharma',
  email: 'rahul@example.com',
  phone: '+918100640044',
  address: ADDRESS,
};

function renderCard ( overrides: Partial<React.ComponentProps<typeof CheckoutIdentityCard>> = {} ) {
  const props = {
    identity: IDENTITY,
    onEditName: vi.fn(),
    onChangeEmail: vi.fn(),
    onEditAddress: vi.fn(),
    ...overrides,
  };
  render( <CheckoutIdentityCard { ...props } /> );
  return props;
}

/** The row element, reached through its own label so no class name is assumed. */
function row ( label: string ): HTMLElement {
  return screen.getByText( label ).parentElement as HTMLElement;
}

describe( 'CheckoutIdentityCard', () => {
  it( 'renders the Deliver line as the server fullAddress, verbatim', () => {
    renderCard();
    expect( screen.getByText( ADDRESS.fullAddress ) ).toBeInTheDocument();
    // The components would compose a different line. Neither the line-1 value nor the PIN the
    // components carry may appear, because either would mean the card composed its own string.
    const deliver = row( 'Deliver' );
    expect( deliver.textContent ).toContain( '7 Residency Road' );
    expect( deliver.textContent ).not.toContain( '12 MG Road' );
    expect( deliver.textContent ).not.toContain( '560001' );
    expect( deliver.textContent ).not.toContain( 'Flat 3B' );
  } );

  it( 'renders nothing for the Deliver line when no address is on file', () => {
    renderCard( { identity: { ...IDENTITY, address: null } } );
    expect( row( 'Deliver' ).textContent ).toBe( 'DeliverEdit address' );
  } );

  it( 'states that the email is verified', () => {
    renderCard();
    expect( row( 'Email' ).textContent ).toContain( 'verified' );
    expect( row( 'Email' ).querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
  } );

  it( 'states that the phone is verified, in the same plain copy as the email', () => {
    renderCard();
    expect( row( 'Phone' ).textContent ).toContain( 'verified' );
    expect( row( 'Phone' ).querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
    // The badge must not name the mechanism - that wording reads as internal, not as customer copy.
    expect( row( 'Phone' ).textContent ).not.toContain( 'WhatsApp' );
    expect( row( 'Phone' ).textContent ).not.toContain( 'sign-in' );
  } );

  it( 'puts no verified badge on the address, because nobody verified it', () => {
    renderCard();
    expect( row( 'Deliver' ).textContent ).not.toContain( 'verified' );
    expect( row( 'Deliver' ).textContent ).not.toContain( '✓' );
  } );

  it( 'offers no way to edit the phone, because the phone is the identity', () => {
    renderCard();
    expect( row( 'Phone' ).querySelector( 'button' ) ).toBeNull();
    expect( screen.queryByRole( 'button', { name: /phone|number/i } ) ).toBeNull();
    expect( screen.getAllByRole( 'button' ) ).toHaveLength( 3 );
  } );

  it( 'disables all three affordances while the editor is open', () => {
    renderCard( { editorOpen: true } );
    expect( screen.getByRole( 'button', { name: 'Edit name' } ) ).toBeDisabled();
    expect( screen.getByRole( 'button', { name: 'Change email' } ) ).toBeDisabled();
    expect( screen.getByRole( 'button', { name: 'Edit address' } ) ).toBeDisabled();
  } );

  it( 'reports which affordance was used when the editor is closed', () => {
    const props = renderCard();
    fireEvent.click( screen.getByRole( 'button', { name: 'Edit name' } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Change email' } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Edit address' } ) );
    expect( props.onEditName ).toHaveBeenCalledTimes( 1 );
    expect( props.onChangeEmail ).toHaveBeenCalledTimes( 1 );
    expect( props.onEditAddress ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'masks the middle of the phone without inventing digits', () => {
    renderCard();
    expect( screen.getByText( '+91 81006 ·····' ) ).toBeInTheDocument();
  } );

  /**
   * THE FOUR OPTIONAL PROPS /orders/ ADDED, ASSERTED FROM THE /cart/ SIDE.
   *
   * `/cart/` passes none of `eyebrow`, `title`, `emailVerified` or `emptyAddressLabel`, and the
   * claim that adding them has zero blast radius is only worth anything as a measurement. These
   * three tests are that measurement: one per prop that carries a default. (`emailVerified` and
   * the Deliver fallback are each also asserted in the OTHER direction by
   * `src/test/OrdersPage.test.tsx`, which is the consumer that passes them.)
   */
  it( 'keeps the checkout copy when no eyebrow or title is passed', () => {
    renderCard();
    expect( screen.getByText( 'Checkout details' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'heading', { name: 'Ready to pay' } ) ).toBeInTheDocument();
  } );

  it( 'keeps the email badge when no emailVerified is passed', () => {
    // `!== false`, not a truthiness test - so an omitted prop is today's behaviour exactly.
    renderCard();
    expect( row( 'Email' ).querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
  } );

  it( 'keeps the Deliver value empty when no emptyAddressLabel is passed', () => {
    renderCard( { identity: { ...IDENTITY, address: null } } );
    expect( row( 'Deliver' ).querySelector( '.identity-value' )!.textContent ).toBe( '' );
  } );

  it( 'suppresses the email badge, and only the email badge, on an explicit false', () => {
    renderCard( { identity: { ...IDENTITY, emailVerified: false } } );
    expect( row( 'Email' ).querySelector( '.identity-badge' ) ).toBeNull();
    // The phone badge is unconditional: the session proves the number whatever the email says.
    expect( row( 'Phone' ).querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
  } );

  it( 'renders the caller\'s copy when the four props are passed', () => {
    renderCard( {
      identity: { ...IDENTITY, address: null },
      eyebrow: 'Your details',
      title: 'What we have on file',
      emptyAddressLabel: 'No address on file',
    } );
    expect( screen.getByText( 'Your details' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'heading', { name: 'What we have on file' } ) ).toBeInTheDocument();
    expect( screen.queryByText( 'Checkout details' ) ).toBeNull();
    expect( row( 'Deliver' ).textContent ).toContain( 'No address on file' );
  } );
} );
