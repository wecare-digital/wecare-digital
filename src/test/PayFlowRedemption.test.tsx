import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * PAY FLOW CARRIES THE ONE ALWAYS-ON DISCOUNT, AND COMPUTES NOTHING.
 *
 * There is no coupon system and no gift-card system, and manual discount entry is retired. The
 * staff invoice form sends no coupon code and no discount: the invoice engine applies the
 * standalone Delight policy (0.5% up to ₹50) on the server. The browser never supplies a discount
 * amount; it renders only the server-owned Delight figure returned on create.
 */
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );

const listContacts = vi.fn();
const listInvoicesEngine = vi.fn();
const createInvoiceEngine = vi.fn();
const getInvoiceDeliveryLog = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  listInvoicesEngine: ( ...a: unknown[] ) => listInvoicesEngine( ...a ),
  createInvoiceEngine: ( ...a: unknown[] ) => createInvoiceEngine( ...a ),
  getInvoiceDeliveryLog: ( ...a: unknown[] ) => getInvoiceDeliveryLog( ...a ),
} ) );

import PayFlowPage from '../components/workspace/pay/PayFlow';
import { ADDRESS_FIELDS, formatAddress } from '../lib/address-format';

const CUSTOMER = {
  id: 'c_1', contactId: 'c_1', name: 'Asha Rao', phone: '+919812345678',
  email: 'asha@example.com', shippingAddress: '', billingAddress: '',
};
const SERVER_CREATE = {
  invoiceId: 'inv_1',
  invoiceNumber: 'WD/2026/0001',
  referenceId: 'ref_1',
  total: 1234.56,
  // The server applied Delight. `couponCode` carries the fixed DELIGHT code and `couponDiscount`
  // is the rupees Delight took off — the ONLY discount an invoice can carry now.
  couponCode: 'DELIGHT',
  couponDiscount: 6.17,
};

beforeEach( () => {
  vi.clearAllMocks();
  window.localStorage.clear();
  listContacts.mockResolvedValue( [ { ...CUSTOMER } ] );
  listInvoicesEngine.mockResolvedValue( { invoices: [] } );
  getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
  createInvoiceEngine.mockResolvedValue( SERVER_CREATE );
} );

const openCreateForm = async (): Promise<void> => {
  render( <PayFlowPage embedded /> );
  fireEvent.click( screen.getByRole( 'tab', { name: 'Create' } ) );
  fireEvent.click( await screen.findByText( 'Asha Rao' ) );
  await waitFor( () => expect( screen.getByRole( 'button', { name: 'Create Invoice' } ) ).toBeInTheDocument() );
};
const priceOneItem = (): void => {
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 0 ], { target: { value: '1000' } } );
};
const submit = (): void => {
  fireEvent.click( screen.getByRole( 'button', { name: 'Create Invoice' } ) );
};
const lastRequest = (): any => createInvoiceEngine.mock.calls[ 0 ][ 0 ];

describe( 'the invoice form offers no coupon or manual-discount control', () => {
  it( 'renders neither a coupon code input nor a gift-card input', async () => {
    await openCreateForm();
    expect( screen.queryByLabelText( /Coupon code/i ) ).toBeNull();
    expect( screen.queryByLabelText( /Gift card code/i ) ).toBeNull();
  } );
  it( 'renders no manual-adjustment input', async () => {
    await openCreateForm();
    expect( screen.queryByLabelText( /Manual adjustment/i ) ).toBeNull();
    expect( screen.queryByLabelText( /Promo \/ Discount/i ) ).toBeNull();
  } );
} );

describe( 'the create request carries no discount the browser authored', () => {
  it( 'sends neither couponCode, discount, nor giftCardCode', async () => {
    await openCreateForm();
    priceOneItem();
    submit();
    await waitFor( () => expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 ) );
    const keys = Object.keys( lastRequest() );
    expect( keys ).not.toContain( 'couponCode' );
    expect( keys ).not.toContain( 'giftCardCode' );
    expect( keys ).not.toContain( 'discount' );
    expect( keys ).not.toContain( 'couponDiscount' );
    expect( keys ).not.toContain( 'discountPaise' );
    expect( keys ).not.toContain( 'amountPayable' );
  } );
} );

describe( 'the Delight discount is server-authoritative', () => {
  it( 'previews the Delight discount exactly as the server returned it', async () => {
    await openCreateForm();
    priceOneItem();
    submit();
    await waitFor( () => expect( screen.getByText( 'Delight' ) ).toBeInTheDocument() );
    expect( screen.getByText( '−₹6.17' ) ).toBeInTheDocument();
  } );
  it( 'shows no discount line when the server applied none', async () => {
    createInvoiceEngine.mockResolvedValue( {
      invoiceId: 'inv_2', invoiceNumber: 'WD/2026/0002', referenceId: 'ref_2', total: 1.00,
    } );
    await openCreateForm();
    priceOneItem();
    submit();
    await waitFor( () => expect( screen.getByText( /Applied on the last invoice/ ) ).toBeInTheDocument() );
    expect( screen.queryByText( 'Delight' ) ).toBeNull();
  } );
} );

describe( 'one address format, one input group', () => {
  it( 'renders the eight shared fields in the customer modal and no free-text address textarea', async () => {
    render( <PayFlowPage embedded /> );
    fireEvent.click( await screen.findByRole( 'button', { name: '+ New Customer' } ) );
    for ( const spec of ADDRESS_FIELDS )
    {
      expect( screen.getByLabelText( spec.label ) ).toBeInTheDocument();
    }
    // Every address control is an <input>; no textarea is an address input any more.
    for ( const node of screen.getAllByLabelText( /Address line|Landmark|City|State|Postal Code|Country/ ) )
    {
      expect( node.tagName ).toBe( 'INPUT' );
    }
  } );
  it( 'composes the preview through formatAddress from the shared module', async () => {
    render( <PayFlowPage embedded /> );
    fireEvent.click( await screen.findByRole( 'button', { name: '+ New Customer' } ) );
    const typed = {
      addressLine1: '12 MG Road', addressLine2: 'Flat 3B', locality: 'Near the park',
      city: 'Bengaluru', state: 'Karnataka', postalCode: '560001',
      country: 'India', countryCode: 'IN',
    };
    for ( const spec of ADDRESS_FIELDS )
    {
      fireEvent.change( screen.getByLabelText( spec.label ), {
        target: { value: typed[ spec.key ] },
      } );
    }
    const preview = document.querySelector( '[data-address-preview="pf-cust-addr"]' );
    expect( preview?.textContent ).toBe( formatAddress( typed ) );
    // And the composition is a real composition, not an echo of one field.
    expect( preview?.textContent ).toBe( '12 MG Road, Flat 3B, Near the park, Bengaluru, Karnataka 560001, India' );
  } );
} );

describe( 'the retired brand list', () => {
  it( 'shows the hardcoded brand as a read-only field', async () => {
    await openCreateForm();
    const brand = screen.getByRole( 'textbox', { name: 'Brand' } ) as HTMLInputElement;
    expect( brand.value ).toBe( 'WECARE.DIGITAL' );
    expect( brand.readOnly ).toBe( true );
    expect( screen.queryByRole( 'combobox', { name: 'Brand' } ) ).toBeNull();
  } );
  it( 'ignores a retired brand list saved in local storage', async () => {
    window.localStorage.setItem( 'wecare_flow_config', JSON.stringify( {
      purposes: [ 'BNB Club', 'Ritual Guru' ],
    } ) );
    await openCreateForm();
    priceOneItem();
    submit();
    await waitFor( () => expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 ) );
    expect( lastRequest().purpose ).toBe( 'WECARE.DIGITAL' );
  } );
} );
