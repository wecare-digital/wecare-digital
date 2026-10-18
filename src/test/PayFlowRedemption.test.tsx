import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * PAY FLOW SPEAKS THE ONE COUPON SYSTEM, AND COMPUTES NOTHING.
 *
 * Gift cards are retired. The staff invoice form now carries only an optional
 * coupon code plus the separate manual adjustment. The browser never supplies a
 * coupon amount; it renders only the server-owned discount returned on create.
 */
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );

const listContacts = vi.fn();
const listInvoicesEngine = vi.fn();
const createInvoiceEngineResult = vi.fn();
const getInvoiceDeliveryLog = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  listInvoicesEngine: ( ...a: unknown[] ) => listInvoicesEngine( ...a ),
  createInvoiceEngineResult: ( ...a: unknown[] ) => createInvoiceEngineResult( ...a ),
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
  couponCode: 'SAVE100',
  couponDiscount: 777.77,
  amountPayable: 1234.56,
  couponReason: 'APPLIED',
};

beforeEach( () => {
  vi.clearAllMocks();
  window.localStorage.clear();
  listContacts.mockResolvedValue( [ { ...CUSTOMER } ] );
  listInvoicesEngine.mockResolvedValue( { invoices: [] } );
  getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
  createInvoiceEngineResult.mockResolvedValue( { ok: true, invoice: SERVER_CREATE } );
} );

const openCreateForm = async (): Promise<void> => {
  render( <PayFlowPage embedded /> );
  fireEvent.click( screen.getByRole( 'tab', { name: 'Create' } ) );
  fireEvent.click( await screen.findByText( 'Asha Rao' ) );
  await waitFor( () => expect( screen.getByLabelText( 'Coupon code' ) ).toBeInTheDocument() );
};

const priceOneItem = (): void => {
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 0 ], { target: { value: '1000' } } );
};

const submit = (): void => {
  fireEvent.click( screen.getByRole( 'button', { name: 'Create Invoice' } ) );
};

const lastRequest = (): any => createInvoiceEngineResult.mock.calls[ 0 ][ 0 ];

describe( 'the coupon-only redemption field', () => {
  it( 'renders the coupon input and no retired gift-card input', async () => {
    await openCreateForm();
    expect( screen.getByLabelText( 'Coupon code' ) ).toBeInTheDocument();
    expect( screen.queryByLabelText( 'Gift card code' ) ).toBeNull();
  } );

  it( 'sends couponCode and never giftCardCode', async () => {
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: ' save100 ' } } );
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( lastRequest().couponCode ).toBe( 'save100' );
    expect( 'giftCardCode' in lastRequest() ).toBe( false );
  } );

  it( 'omits couponCode when the field is empty', async () => {
    await openCreateForm();
    priceOneItem();
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( 'couponCode' in lastRequest() ).toBe( false );
    expect( 'giftCardCode' in lastRequest() ).toBe( false );
  } );

  it( 'sends no browser-authored redemption amount', async () => {
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'SAVE100' } } );
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    const keys = Object.keys( lastRequest() );
    expect( keys ).not.toContain( 'couponDiscount' );
    expect( keys ).not.toContain( 'discountPaise' );
    expect( keys ).not.toContain( 'giftCardAppliedPaise' );
    expect( keys ).not.toContain( 'amountPayable' );
  } );
} );

describe( 'coupon amounts are server-authoritative', () => {
  it( 'renders the coupon discount exactly as the server returned it', async () => {
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'SAVE100' } } );
    submit();

    await waitFor( () => expect( screen.getByText( /Coupon SAVE100/ ) ).toBeInTheDocument() );
    expect( screen.getByText( '−₹777.77' ) ).toBeInTheDocument();
  } );
} );

describe( 'a coupon refusal renders the server reason and no applied amount', () => {
  it.each( [
    [ 'UNKNOWN_CODE', /not valid/i ],
    [ 'COUPON_EXPIRED', /expired/i ],
    [ 'HELD_BY_ANOTHER_CART', /used elsewhere/i ],
  ] )( 'shows the %s message', async ( errorCode, fragment ) => {
    createInvoiceEngineResult.mockResolvedValue( { ok: false, status: 400, errorCode, retryable: false } );
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'X' } } );
    submit();

    await waitFor( () => expect( screen.getByText( fragment as RegExp ) ).toBeInTheDocument() );
    expect( screen.queryByText( /Applied on the last invoice/ ) ).toBeNull();
  } );

  it( 'degrades honestly on an errorCode it does not recognise', async () => {
    createInvoiceEngineResult.mockResolvedValue( { ok: false, status: 400, errorCode: 'SOMETHING_NEW', retryable: false } );
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'X' } } );
    submit();

    await waitFor( () => {
      expect( screen.getByText( 'The coupon could not be applied.' ) ).toBeInTheDocument();
    } );
  } );

  it( 'does not blame the coupon when no coupon code was sent', async () => {
    createInvoiceEngineResult.mockResolvedValue( { ok: false, status: 500, errorCode: 'CREATE_FAILED', retryable: false } );
    await openCreateForm();
    priceOneItem();
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( screen.queryByText( 'The coupon could not be applied.' ) ).toBeNull();
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

describe( 'the retired brand list and the manual adjustment', () => {
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
    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( lastRequest().purpose ).toBe( 'WECARE.DIGITAL' );
  } );

  it( 'labels the rupee field a manual adjustment and defaults it to 0', async () => {
    await openCreateForm();
    const field = screen.getByLabelText( /Manual adjustment/ ) as HTMLInputElement;
    expect( field.value ).toBe( '0' );
    // The old label is gone, so nothing reads as a second coupon mechanism.
    expect( screen.queryByLabelText( /Promo \/ Discount/ ) ).toBeNull();
  } );

  it( 'sends discount 0 when the staff member does not touch it', async () => {
    await openCreateForm();
    priceOneItem();
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( lastRequest().discount ).toBe( 0 );
  } );
} );
