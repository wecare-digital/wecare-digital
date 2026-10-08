import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * PAY FLOW SPEAKS THE ONE COUPON SYSTEM, AND COMPUTES NOTHING.
 *
 * The staff invoice form is the surface that used to carry its own discount mechanism: a rupee
 * field labelled "Promo / Discount" whose default was '15', so EVERY Pay Flow invoice was
 * discounted by Rs.15 before anyone typed anything. That silent default was the real duplicate of
 * the coupon system, and these tests pin its removal alongside the coupon and gift-card fields
 * that replace it.
 *
 * WHAT IS ASSERTED, and why each one would regress silently otherwise:
 *   1. The coupon and gift-card inputs exist and are LABELLED, so they can be found by name.
 *   2. A create sends `couponCode` / `giftCardCode` in the request body — and sends a code and
 *      nothing else. There is no field through which an amount could leave the browser.
 *   3. Every displayed figure is the SERVER's. The success response here carries numbers that
 *      no local calculation of this form's inputs could produce, and those are the numbers that
 *      must appear. This is the test that fails the moment someone "helpfully" previews a
 *      discount client-side.
 *   4. An invalid / expired / insufficient-balance refusal renders the message for the server's
 *      typed `errorCode` and NO amount.
 *   5. There is exactly ONE address input group and no free-text address textarea acting as an
 *      input, and the preview equals `formatAddress` from the shared module.
 *   6. The brand chooser offers only WECARE.DIGITAL, and the manual adjustment defaults to 0.
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

import PayFlowPage from '../pages/workspace/pay/flow';
import { ADDRESS_FIELDS, formatAddress } from '../lib/address-format';

const CUSTOMER = {
  id: 'c_1', contactId: 'c_1', name: 'Asha Rao', phone: '+919812345678',
  email: 'asha@example.com', shippingAddress: '', billingAddress: '',
};

/** A 201 whose figures no local arithmetic over this form's inputs could produce. */
const SERVER_CREATE = {
  invoiceId: 'inv_1',
  invoiceNumber: 'WD/2026/0001',
  referenceId: 'ref_1',
  total: 1234.56,
  couponCode: 'SAVE100',
  couponDiscount: 777.77,        // not 10% of anything typed below
  giftCardAppliedPaise: 43210,   // Rs.432.10, server authority, integer paise
  amountPayable: 802.46,
  couponReason: 'APPLIED',
  giftCardReason: 'APPLIED',
};

beforeEach( () => {
  vi.clearAllMocks();
  window.localStorage.clear();
  listContacts.mockResolvedValue( [ { ...CUSTOMER } ] );
  listInvoicesEngine.mockResolvedValue( { invoices: [] } );
  getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
  createInvoiceEngineResult.mockResolvedValue( { ok: true, invoice: SERVER_CREATE } );
} );

/** Render, open the Create tab, pick the one customer, and land on the invoice form. */
const openCreateForm = async (): Promise<void> => {
  render( <PayFlowPage embedded /> );
  fireEvent.click( screen.getByRole( 'tab', { name: 'Create' } ) );
  fireEvent.click( await screen.findByText( 'Asha Rao' ) );
  await waitFor( () => expect( screen.getByLabelText( 'Coupon code' ) ).toBeInTheDocument() );
};

/** Fill one priced line so `submitInvoice` does not refuse the form. */
const priceOneItem = (): void => {
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 0 ], { target: { value: '1000' } } );
};

const submit = (): void => {
  fireEvent.click( screen.getByRole( 'button', { name: 'Create Invoice' } ) );
};

/** The request body handed to the API client on the last create. */
const lastRequest = (): any => createInvoiceEngineResult.mock.calls[ 0 ][ 0 ];

describe( 'the coupon and gift-card fields', () => {
  it( 'render on the invoice create form, each with a label', async () => {
    await openCreateForm();
    expect( screen.getByLabelText( 'Coupon code' ) ).toBeInTheDocument();
    expect( screen.getByLabelText( 'Gift card code' ) ).toBeInTheDocument();
  } );

  it( 'sends couponCode and giftCardCode on the create', async () => {
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: ' save100 ' } } );
    fireEvent.change( screen.getByLabelText( 'Gift card code' ), { target: { value: 'GC-ABCD' } } );
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( lastRequest().couponCode ).toBe( 'save100' );
    expect( lastRequest().giftCardCode ).toBe( 'GC-ABCD' );
  } );

  it( 'omits both keys entirely when no code was typed, so the no-codes path is untouched', async () => {
    await openCreateForm();
    priceOneItem();
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( 'couponCode' in lastRequest() ).toBe( false );
    expect( 'giftCardCode' in lastRequest() ).toBe( false );
  } );

  it( 'sends no amount-shaped redemption field, ever', async () => {
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

describe( 'amounts are server-authoritative, never browser math', () => {
  it( 'renders the coupon discount, gift-card amount and payable EXACTLY as the server returned them', async () => {
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'SAVE100' } } );
    fireEvent.change( screen.getByLabelText( 'Gift card code' ), { target: { value: 'GC-ABCD' } } );
    submit();

    // Rs.777.77 is the server's figure and is not derivable from the Rs.1000 line above.
    await waitFor( () => expect( screen.getByText( /Coupon SAVE100/ ) ).toBeInTheDocument() );
    expect( screen.getByText( '\u2212\u20B9777.77' ) ).toBeInTheDocument();
    // 43210 integer paise, formatted without a division.
    expect( screen.getByText( '\u2212\u20B9432.10' ) ).toBeInTheDocument();
    expect( screen.getByText( '\u20B9802.46' ) ).toBeInTheDocument();
  } );

  it( 'never echoes the gift-card code back into a visible label', async () => {
    const { container } = render( <PayFlowPage embedded /> );
    fireEvent.click( screen.getByRole( 'tab', { name: 'Create' } ) );
    fireEvent.click( await screen.findByText( 'Asha Rao' ) );
    await waitFor( () => expect( screen.getByLabelText( 'Gift card code' ) ).toBeInTheDocument() );
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Gift card code' ), { target: { value: 'GC-ABCD' } } );
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    await waitFor( () => expect( container.textContent || '' ).not.toContain( 'GC-ABCD' ) );
  } );
} );

describe( 'a refusal renders the server reason and no amount', () => {
  it.each( [
    [ 'UNKNOWN_CODE', /not valid/i ],
    [ 'COUPON_EXPIRED', /expired/i ],
    [ 'INSUFFICIENT_BALANCE', /no balance left/i ],
    [ 'HELD_BY_ANOTHER_CART', /used elsewhere/i ],
  ] )( 'shows the %s message', async ( errorCode, fragment ) => {
    createInvoiceEngineResult.mockResolvedValue( { ok: false, status: 400, errorCode, retryable: false } );
    await openCreateForm();
    priceOneItem();
    fireEvent.change( screen.getByLabelText( 'Coupon code' ), { target: { value: 'X' } } );
    fireEvent.change( screen.getByLabelText( 'Gift card code' ), { target: { value: 'Y' } } );
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
      expect( screen.getByText( 'The coupon or gift card could not be applied.' ) ).toBeInTheDocument();
    } );
  } );

  it( 'does NOT blame the coupon for a failure on a create that carried no code', async () => {
    createInvoiceEngineResult.mockResolvedValue( { ok: false, status: 500, errorCode: 'CREATE_FAILED', retryable: false } );
    await openCreateForm();
    priceOneItem();
    submit();

    await waitFor( () => expect( createInvoiceEngineResult ).toHaveBeenCalledTimes( 1 ) );
    expect( screen.queryByText( 'The coupon or gift card could not be applied.' ) ).toBeNull();
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
