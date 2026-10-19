import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

/**
 * PAY FLOW CARRIES THE ONE ALWAYS-ON DISCOUNT, AND COMPUTES NOTHING.
 *
 * There is no coupon system and no gift-card system, and manual discount entry is retired. The
 * staff invoice form sends no coupon code and no discount: the invoice engine applies the
 * standalone Delight policy (0.5% up to ₹50) on the server. The browser never supplies a discount
 * amount; it renders only the server-owned Delight figure returned on create.
 */
const routerPush = vi.fn();
vi.mock( 'next/router', () => ( {
  useRouter: () => ( { pathname: '/workspace/payments', query: {}, push: routerPush, replace: vi.fn(), isReady: true } ),
} ) );

const confirmAction = vi.fn();
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => confirmAction } ) );

const listContacts = vi.fn();
const listInvoicesEngine = vi.fn();
const createInvoiceEngine = vi.fn();
const getInvoiceDeliveryLog = vi.fn();
const getInvoiceEngine = vi.fn();
const sendPaymentLink = vi.fn();
const sendPaymentLinkResult = vi.fn();
const cancelInvoice = vi.fn();
const deleteInvoice = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  listInvoicesEngine: ( ...a: unknown[] ) => listInvoicesEngine( ...a ),
  createInvoiceEngine: ( ...a: unknown[] ) => createInvoiceEngine( ...a ),
  getInvoiceDeliveryLog: ( ...a: unknown[] ) => getInvoiceDeliveryLog( ...a ),
  getInvoiceEngine: ( ...a: unknown[] ) => getInvoiceEngine( ...a ),
  sendPaymentLink: ( ...a: unknown[] ) => sendPaymentLink( ...a ),
  sendPaymentLinkResult: ( ...a: unknown[] ) => sendPaymentLinkResult( ...a ),
  cancelInvoice: ( ...a: unknown[] ) => cancelInvoice( ...a ),
  deleteInvoice: ( ...a: unknown[] ) => deleteInvoice( ...a ),
} ) );

import PayFlowPage from '../components/workspace/pay/PayFlow';

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
  routerPush.mockResolvedValue( true );
  window.localStorage.clear();
  confirmAction.mockResolvedValue( true );
  cancelInvoice.mockResolvedValue( { status: 'cancelled' } );
  listContacts.mockResolvedValue( [ { ...CUSTOMER } ] );
  listInvoicesEngine.mockResolvedValue( { invoices: [] } );
  getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
  createInvoiceEngine.mockResolvedValue( SERVER_CREATE );
  getInvoiceEngine.mockResolvedValue( { ...SERVER_CREATE, status: 'created', paymentStatus: 'pending', customerName: CUSTOMER.name, customerPhone: CUSTOMER.phone } );
  sendPaymentLink.mockResolvedValue( { status: 'payment_link_sent' } );
  sendPaymentLinkResult.mockImplementation( async ( ...args: unknown[] ) => { const data = await sendPaymentLink( ...args ); return data ? { ok: true, data } : { ok: false, failure: { message: 'Sending is not confirmed.' } }; } );
} );

const openCreateForm = async (): Promise<void> => {
  render( <PayFlowPage embedded mode="collect" /> );
  fireEvent.click( await screen.findByText( 'Asha Rao' ) );
  await waitFor( () => expect( screen.getByRole( 'button', { name: 'Save invoice for review' } ) ).toBeInTheDocument() );
};
const priceOneItem = (): void => {
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 0 ], { target: { value: '1000' } } );
};
const submit = (): void => {
  fireEvent.click( screen.getByRole( 'button', { name: 'Save invoice for review' } ) );
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

describe( 'Collect does not recreate Customers', () => {
  it( 'uses an existing canonical customer and offers no second customer editor', async () => {
    render( <PayFlowPage embedded mode="collect" /> );
    expect( await screen.findByText( 'Asha Rao' ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: '+ New Customer' } ) ).toBeNull();
    expect( screen.queryByLabelText( 'Address line 1' ) ).toBeNull();
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


it( 'preserves a zero GST rate instead of replacing it with the default rate', async () => {
  await openCreateForm();
  priceOneItem();
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 2 ], { target: { value: '0' } } );
  submit();
  await waitFor( () => expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 ) );
  expect( lastRequest().items[ 0 ].gstRate ).toBe( 0 );
  expect( lastRequest() ).not.toHaveProperty( 'paymentConfiguration' );
} );


describe( 'created invoices lead to canonical review', () => {
  it( 'routes the saved invoice to Payments / Invoices without creating or sending another request', async () => {
    await openCreateForm();
    priceOneItem();
    submit();
    const next = await screen.findByRole( 'button', { name: 'Review and send payment request' } );
    expect( screen.getByText( /Invoice saved without sending a WhatsApp payment request/ ) ).toBeInTheDocument();
    expect( sendPaymentLink ).not.toHaveBeenCalled();
    fireEvent.click( next );
    await waitFor( () => expect( routerPush ).toHaveBeenCalledWith( {
      pathname: '/workspace/payments',
      query: { view: 'invoices', invoice: 'inv_1' },
    } ) );
    expect( getInvoiceEngine ).not.toHaveBeenCalled();
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
  } );
  it( 'retains recovery action when canonical navigation itself fails', async () => {
    routerPush.mockRejectedValueOnce( new Error( 'navigation failed' ) );
    await openCreateForm();
    priceOneItem();
    submit();
    fireEvent.click( await screen.findByRole( 'button', { name: 'Review and send payment request' } ) );
    await screen.findByText( /Could not open Invoices/ );
    expect( screen.getByRole( 'button', { name: 'Review and send payment request' } ) ).toBeInTheDocument();
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
    expect( sendPaymentLink ).not.toHaveBeenCalled();
  } );
} );


describe( 'explicit create and send', () => {
  it( 'creates once, then sends that invoice from the primary number', async () => {
    await openCreateForm(); priceOneItem();
    fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
    await waitFor( () => expect( sendPaymentLink ).toHaveBeenCalledWith( 'inv_1', 'phone-number-id-waba1-direct-1016149501586345' ) );
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
    expect( createInvoiceEngine.mock.invocationCallOrder[ 0 ] ).toBeLessThan( sendPaymentLink.mock.invocationCallOrder[ 0 ] );
    await screen.findByText( 'WhatsApp payment request sent.', { selector: 'p' } );
  } );
  it( 'retains the saved invoice when sending is unconfirmed and does not create a replacement', async () => {
    sendPaymentLink.mockResolvedValue( null );
    await openCreateForm(); priceOneItem();
    fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
    await screen.findByText( /Sending is not confirmed. Open this saved invoice/ );
    fireEvent.click( screen.getByRole( 'button', { name: 'View invoice and delivery status' } ) );
    await waitFor( () => expect( routerPush ).toHaveBeenCalledWith( {
      pathname: '/workspace/payments',
      query: { view: 'invoices', invoice: 'inv_1' },
    } ) );
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
    expect( sendPaymentLink ).toHaveBeenCalledTimes( 1 );
  } );
  it( 'does not label an in-progress dispatch as sent', async () => {
    sendPaymentLink.mockResolvedValue( { status: 'send_in_progress' } );
    await openCreateForm(); priceOneItem();
    fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
    await screen.findByText( /Sending is not confirmed. Open this saved invoice/ );
    expect( screen.queryByText( 'WhatsApp payment request sent.' ) ).toBeNull();
  } );
  it( 'blocks duplicate clicks while invoice creation is pending', async () => {
    let finish: ( value: typeof SERVER_CREATE ) => void = () => {};
    createInvoiceEngine.mockReturnValue( new Promise( resolve => { finish = resolve; } ) );
    await openCreateForm(); priceOneItem();
    const create = screen.getByRole( 'button', { name: 'Create and send payment request' } );
    fireEvent.click( create ); fireEvent.click( create );
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
    expect( screen.getByRole( 'button', { name: 'Save invoice for review' } ) ).toBeDisabled();
    finish( SERVER_CREATE );
    await waitFor( () => expect( sendPaymentLink ).toHaveBeenCalledTimes( 1 ) );
  } );
  it( 'does not send if invoice creation is refused', async () => {
    createInvoiceEngine.mockResolvedValue( null );
    await openCreateForm(); priceOneItem();
    fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
    await screen.findByText( 'Create failed' );
    expect( sendPaymentLink ).not.toHaveBeenCalled();
  } );
} );

const existingInvoice = ( extra: Record<string, unknown> = {} ) => ( {
  ...SERVER_CREATE, status: 'pending_payment', paymentStatus: 'pending',
  customerName: CUSTOMER.name, customerPhone: CUSTOMER.phone, createdAt: 1770000000,
  ...extra,
} );

describe( 'cancellation replaces withdrawn invoice deletion', () => {
  it( 'cancels an unpaid invoice and hides it from Active without deleting its record', async () => {
    const invoice = existingInvoice();
    listInvoicesEngine.mockResolvedValue( { invoices: [ invoice ] } );
    cancelInvoice.mockImplementation( async () => {
      listInvoicesEngine.mockResolvedValue( { invoices: [ { ...invoice, status: 'cancelled', paymentStatus: 'cancelled' } ] } );
      return { invoiceId: invoice.invoiceId, status: 'cancelled' };
    } );
    render( <PayFlowPage embedded mode="invoices" /> );
    const row = ( await screen.findByText( 'ref_1' ) ).closest( 'tr' )!;
    expect( screen.queryByRole( 'button', { name: 'Delete' } ) ).toBeNull();
    fireEvent.click( within( row ).getByRole( 'button', { name: 'Cancel Invoice' } ) );
    await waitFor( () => expect( cancelInvoice ).toHaveBeenCalledWith( 'inv_1' ) );
    await waitFor( () => expect( screen.queryByText( 'ref_1' ) ).toBeNull() );
    expect( deleteInvoice ).not.toHaveBeenCalled();
    fireEvent.click( screen.getByRole( 'button', { name: /^Cancelled$/ } ) );
    expect( await screen.findByText( 'ref_1' ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: 'Cancel Invoice' } ) ).toBeNull();
  } );
  it.each( [ 'captured', 'paid', 'refunded', 'disputed' ] )( 'does not offer cancellation for payment status %s', async paymentStatus => {
    listInvoicesEngine.mockResolvedValue( { invoices: [ existingInvoice( { paymentStatus } ) ] } );
    render( <PayFlowPage embedded mode="invoices" /> );
    fireEvent.click( await screen.findByText( 'ref_1' ) );
    expect( screen.queryByRole( 'button', { name: 'Cancel Invoice' } ) ).toBeNull();
    expect( screen.queryByRole( 'button', { name: 'Delete' } ) ).toBeNull();
  } );
  it( 'leaves an invoice unchanged when cancellation is declined', async () => {
    confirmAction.mockResolvedValue( false );
    listInvoicesEngine.mockResolvedValue( { invoices: [ existingInvoice() ] } );
    render( <PayFlowPage embedded mode="invoices" /> );
    const row = ( await screen.findByText( 'ref_1' ) ).closest( 'tr' )!;
    fireEvent.click( within( row ).getByRole( 'button', { name: 'Cancel Invoice' } ) );
    await waitFor( () => expect( confirmAction ).toHaveBeenCalled() );
    expect( cancelInvoice ).not.toHaveBeenCalled();
    expect( deleteInvoice ).not.toHaveBeenCalled();
  } );
} );


it( 'shows the actionable server refusal instead of a generic send failure', async () => {
  sendPaymentLinkResult.mockResolvedValue( { ok: false, failure: { message: 'Save a valid six-digit delivery PIN before requesting payment.' } } );
  await openCreateForm(); priceOneItem();
  fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
  await screen.findByText( /Save a valid six-digit delivery PIN.*Open this saved invoice/ );
  expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
} );


it( 'creates physical invoices and offers no digital bypass', async () => {
  await openCreateForm();
  expect( screen.queryByRole( 'combobox', { name: 'Goods type' } ) ).toBeNull();
  priceOneItem();
  submit();
  await waitFor( () => expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 ) );
  expect( lastRequest().goodsType ).toBe( 'physical-goods' );
} );
