import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * THE CONTACTS FORM NOW ACTUALLY WRITES AN ADDRESS, which it never did.
 *
 * THE DEFECT, stated precisely, because the fix is only convincing next to it.
 * `src/pages/workspace/contacts/index.tsx` declared `formAddressLine1` and rendered NO INPUT
 * BOUND TO IT. The visible field labelled "Address" wrote `formBuildingName`. Both the create and
 * the update payload read:
 *
 *     address: (formAddressLine1 && formCity && formState && formPostalCode) ? { … } : undefined
 *
 * so `formAddressLine1` was permanently `''`, `address` was permanently `undefined`,
 * `contact_address.normalize_for_storage` never ran, and `checkoutDeliveryAddress` was NEVER
 * written from this form. Every downstream reader - `payment_address.for_wix`,
 * `for_meta_beneficiary`, `cart_v2.delivery_address` - therefore got nothing for a CRM-created
 * contact, which is the "you have not updated the contact page" report.
 *
 * THESE TESTS ASSERT THE PAYLOAD, NOT THE SOURCE. A test that read the file for an input element
 * would have passed against a form whose input was bound to the wrong state, which is the exact
 * fault. So the assertions are on the object handed to `api.createContact` / `api.updateContact`:
 * the one thing the server actually validates.
 */

const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };
vi.mock( '../contexts/ToastContext', () => ( { useToastContext: () => toast } ) );
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );
vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{ children }</div> } ) );
vi.mock( '../components/SEO', () => ( { default: () => null, PAGE_SEO: {} } ) );

const listContacts = vi.fn();
const createContact = vi.fn();
const updateContact = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  createContact: ( ...a: unknown[] ) => createContact( ...a ),
  updateContact: ( ...a: unknown[] ) => updateContact( ...a ),
  listFlowLogs: vi.fn().mockResolvedValue( [] ),
  listMessages: vi.fn().mockResolvedValue( [] ),
} ) );

import ContactsPage from '../pages/workspace/contacts';
import { ADDRESS_FIELDS, formatAddress } from '../lib/address-format';

/** A complete address, one value per `ADDRESS_FIELDS` entry. */
const TYPED: Record<string, string> = {
  addressLine1: '12 MG Road',
  addressLine2: 'Flat 3B',
  locality: 'Near the park',
  city: 'Bengaluru',
  state: 'Karnataka',
  postalCode: '560001',
  country: 'India',
  countryCode: 'IN',
};

beforeEach( () => {
  vi.clearAllMocks();
  listContacts.mockResolvedValue( [] );
  createContact.mockResolvedValue( { contactId: 'c_new' } );
  updateContact.mockResolvedValue( { contactId: 'c_1' } );
} );

/** Open the create dialog and return once the address fields are on screen. */
const openCreate = async (): Promise<void> => {
  render( <ContactsPage /> );
  fireEvent.click( await screen.findByRole( 'button', { name: /New Contact|Add Contact|\+ New/i } ) );
  await waitFor( () => expect( screen.getByLabelText( 'Address line 1' ) ).toBeInTheDocument() );
};

const fillAddress = ( fields: Record<string, string> = TYPED ): void => {
  for ( const spec of ADDRESS_FIELDS )
  {
    if ( !( spec.key in fields ) ) continue;
    fireEvent.change( screen.getByLabelText( spec.label ), { target: { value: fields[ spec.key ] } } );
  }
};

describe( 'the input that was missing', () => {
  it( 'renders an input bound to address line 1 - the defect', async () => {
    await openCreate();
    const input = screen.getByLabelText( 'Address line 1' ) as HTMLInputElement;
    expect( input.tagName ).toBe( 'INPUT' );
    // Bound, not merely present: typing has to land in the value the payload reads.
    fireEvent.change( input, { target: { value: '12 MG Road' } } );
    expect( input.value ).toBe( '12 MG Road' );
  } );

  it( 'renders all eight canonical fields and only those', async () => {
    await openCreate();
    for ( const spec of ADDRESS_FIELDS )
    {
      expect( screen.getByLabelText( spec.label ) ).toBeInTheDocument();
    }
    // The four stand-in columns are gone as inputs: nothing here can disagree with addressLine2.
    expect( screen.queryByLabelText( 'House / Unit Number' ) ).toBeNull();
    expect( screen.queryByLabelText( 'Building' ) ).toBeNull();
    // And the field that USED to be labelled "Address" while writing buildingName is gone too.
    expect( screen.queryByLabelText( 'Address' ) ).toBeNull();
  } );

  it( 'has no free-text address textarea acting as an input', async () => {
    const { container } = render( <ContactsPage /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /New Contact|Add Contact|\+ New/i } ) );
    await waitFor( () => expect( screen.getByLabelText( 'Address line 1' ) ).toBeInTheDocument() );
    expect( container.querySelector( 'textarea#contact-address' ) ).toBeNull();
  } );
} );

describe( 'a complete fill produces a structured address on the payload', () => {
  it( 'sends a non-undefined `address` object on create', async () => {
    await openCreate();
    fireEvent.change( screen.getByLabelText( 'Name' ), { target: { value: 'Asha Rao' } } );
    fireEvent.change( screen.getByLabelText( 'Phone' ), { target: { value: '9812345678' } } );
    fillAddress();
    fireEvent.click( screen.getByRole( 'button', { name: /^Create|^Save/ } ) );

    await waitFor( () => expect( createContact ).toHaveBeenCalledTimes( 1 ) );
    const body = createContact.mock.calls[ 0 ][ 0 ];
    expect( body.address ).toBeDefined();
    expect( body.address ).toMatchObject( {
      addressLine1: '12 MG Road',
      addressLine2: 'Flat 3B',
      locality: 'Near the park',
      city: 'Bengaluru',
      state: 'Karnataka',
      postalCode: '560001',
      country: 'India',
      countryCode: 'IN',
    } );
  } );

  it( 'sends the SAME composition into shippingAddress and billingAddress', async () => {
    await openCreate();
    fireEvent.change( screen.getByLabelText( 'Name' ), { target: { value: 'Asha Rao' } } );
    fireEvent.change( screen.getByLabelText( 'Phone' ), { target: { value: '9812345678' } } );
    fillAddress();
    fireEvent.click( screen.getByRole( 'button', { name: /^Create|^Save/ } ) );

    await waitFor( () => expect( createContact ).toHaveBeenCalledTimes( 1 ) );
    const body = createContact.mock.calls[ 0 ][ 0 ];
    expect( body.shippingAddress ).toBe( formatAddress( TYPED ) );
    expect( body.billingAddress ).toBe( body.shippingAddress );
  } );

  it( 'carries the landmark into `locality`, which is where the payment path reads it', async () => {
    await openCreate();
    fireEvent.change( screen.getByLabelText( 'Name' ), { target: { value: 'Asha Rao' } } );
    fireEvent.change( screen.getByLabelText( 'Phone' ), { target: { value: '9812345678' } } );
    fillAddress();
    fireEvent.click( screen.getByRole( 'button', { name: /^Create|^Save/ } ) );

    await waitFor( () => expect( createContact ).toHaveBeenCalledTimes( 1 ) );
    const body = createContact.mock.calls[ 0 ][ 0 ];
    expect( body.address.locality ).toBe( 'Near the park' );
    // The flat CRM column is still written, because other readers read it.
    expect( body.landmark ).toBe( 'Near the park' );
  } );

  it( 'leaves `address` undefined on an incomplete fill rather than sending a partial one', async () => {
    await openCreate();
    fireEvent.change( screen.getByLabelText( 'Name' ), { target: { value: 'Asha Rao' } } );
    fireEvent.change( screen.getByLabelText( 'Phone' ), { target: { value: '9812345678' } } );
    // Everything except the required city, so the server's FIELD_REQUIRED refusal is never
    // provoked and the contact still saves.
    fillAddress( { ...TYPED, city: '' } );
    fireEvent.click( screen.getByRole( 'button', { name: /^Create|^Save/ } ) );

    await waitFor( () => expect( createContact ).toHaveBeenCalledTimes( 1 ) );
    expect( createContact.mock.calls[ 0 ][ 0 ].address ).toBeUndefined();
  } );

  it( 'writes none of the four retired stand-in columns', async () => {
    await openCreate();
    fireEvent.change( screen.getByLabelText( 'Name' ), { target: { value: 'Asha Rao' } } );
    fireEvent.change( screen.getByLabelText( 'Phone' ), { target: { value: '9812345678' } } );
    fillAddress();
    fireEvent.click( screen.getByRole( 'button', { name: /^Create|^Save/ } ) );

    await waitFor( () => expect( createContact ).toHaveBeenCalledTimes( 1 ) );
    const keys = Object.keys( createContact.mock.calls[ 0 ][ 0 ] );
    // Omitted, NOT blanked: the WhatsApp subscribe flow writes these and an omitted key leaves
    // the stored value alone.
    for ( const retired of [ 'houseNumber', 'buildingName', 'towerNumber', 'floorNumber' ] )
    {
      expect( keys ).not.toContain( retired );
    }
  } );
} );

describe( 'editing an existing contact', () => {
  it( 'loads the address the broken field wrote, so one save repairs it', async () => {
    // A contact created through the OLD form: its real street address is in `buildingName`,
    // because that is what the input labelled "Address" wrote. `addressLine1` is empty.
    listContacts.mockResolvedValue( [ {
      id: 'c_1', contactId: 'c_1', name: 'Asha Rao', phone: '+919812345678',
      email: 'asha@example.com', buildingName: '12 MG Road', city: 'Bengaluru',
      state: 'Karnataka', postalCode: '560001', landmark: 'Near the park',
      houseNumber: '3B', tags: [], createdAt: '1700000000', updatedAt: '1700000000',
    } ] );
    render( <ContactsPage /> );
    fireEvent.click( ( await screen.findAllByRole( 'button', { name: /edit/i } ) )[ 0 ] );

    await waitFor( () => {
      expect( ( screen.getByLabelText( 'Address line 1' ) as HTMLInputElement ).value ).toBe( '12 MG Road' );
    } );
    // The house number folds into address line 2 rather than being dropped.
    expect( ( screen.getByLabelText( ADDRESS_FIELDS[ 1 ].label ) as HTMLInputElement ).value ).toBe( '3B' );
    expect( ( screen.getByLabelText( 'Landmark / Locality' ) as HTMLInputElement ).value ).toBe( 'Near the park' );
  } );

  it( 'prefers the validated stored address over every flat column', async () => {
    listContacts.mockResolvedValue( [ {
      id: 'c_1', contactId: 'c_1', name: 'Asha Rao', phone: '+919812345678',
      addressLine1: 'stale flat value', city: 'Stale', state: 'Stale', postalCode: '000000',
      checkoutDeliveryAddress: {
        addressLine1: '12 MG Road', addressLine2: 'Flat 3B', locality: 'Near the park',
        city: 'Bengaluru', state: 'Karnataka', postalCode: '560001',
        country: 'India', countryCode: 'IN',
      },
      tags: [], createdAt: '1700000000', updatedAt: '1700000000',
    } ] );
    render( <ContactsPage /> );
    fireEvent.click( ( await screen.findAllByRole( 'button', { name: /edit/i } ) )[ 0 ] );

    await waitFor( () => {
      expect( ( screen.getByLabelText( 'Address line 1' ) as HTMLInputElement ).value ).toBe( '12 MG Road' );
    } );
    expect( ( screen.getByLabelText( 'City' ) as HTMLInputElement ).value ).toBe( 'Bengaluru' );
  } );
} );
