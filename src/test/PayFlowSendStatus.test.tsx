import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * STATE-AWARE SEND-STATUS GUIDANCE (FEAT-007 / Findings 10 + 11).
 *
 * The invoice-engine `send_payment_link` command answers with distinct verdicts and each needs
 * its own operator guidance — a terminal refusal must NOT be described as "retry", an in-flight
 * send must NOT invite a resend, and a genuinely unknown outcome must say "reconcile", not
 * "retry". All three send surfaces share ONE interpreter, so these behaviours are asserted
 * through the rendered banner. Money/delivery error banners are also sticky (no auto-dismiss),
 * and the read-only Ledger (mode='invoices') hides the mutating Send/Retry action.
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
const sendPaymentLinkResult = vi.fn();
const cancelInvoice = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  listInvoicesEngine: ( ...a: unknown[] ) => listInvoicesEngine( ...a ),
  createInvoiceEngine: ( ...a: unknown[] ) => createInvoiceEngine( ...a ),
  getInvoiceDeliveryLog: ( ...a: unknown[] ) => getInvoiceDeliveryLog( ...a ),
  getInvoiceEngine: ( ...a: unknown[] ) => getInvoiceEngine( ...a ),
  sendPaymentLinkResult: ( ...a: unknown[] ) => sendPaymentLinkResult( ...a ),
  cancelInvoice: ( ...a: unknown[] ) => cancelInvoice( ...a ),
} ) );

import PayFlowPage from '../components/workspace/pay/PayFlow';

const CUSTOMER = {
  id: 'c_1', contactId: 'c_1', name: 'Asha Rao', phone: '+919812345678',
  email: 'asha@example.com', shippingAddress: '', billingAddress: '',
};
const SERVER_CREATE = {
  invoiceId: 'inv_1', invoiceNumber: 'WD/2026/0001', referenceId: 'ref_1', total: 2.06,
};

beforeEach( () => {
  vi.clearAllMocks();
  vi.useRealTimers();
  routerPush.mockResolvedValue( true );
  window.localStorage.clear();
  confirmAction.mockResolvedValue( true );
  listContacts.mockResolvedValue( [ { ...CUSTOMER } ] );
  listInvoicesEngine.mockResolvedValue( { invoices: [] } );
  getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
  createInvoiceEngine.mockResolvedValue( SERVER_CREATE );
  cancelInvoice.mockResolvedValue( { status: 'cancelled' } );
} );

const createAndSend = async (): Promise<void> => {
  render( <PayFlowPage embedded mode="collect" /> );
  fireEvent.click( await screen.findByText( 'Asha Rao' ) );
  await waitFor( () => expect( screen.getByRole( 'button', { name: 'Save invoice for review' } ) ).toBeInTheDocument() );
  const prices = screen.getAllByRole( 'spinbutton' );
  fireEvent.change( prices[ 0 ], { target: { value: '2' } } );
  fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
};

describe( 'a terminally rejected payment request (Finding 11)', () => {
  it( 'tells the operator to cancel and re-raise, never to retry — for a 200 REJECTED claim', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: true, data: { status: 'payment_link_rejected', sendStatus: 'REJECTED' } } );
    await createAndSend();
    await screen.findByText( /Cancel and raise the collection again/, { selector: '.msg-bar' } );
    expect( screen.getByText( /was refused and was NOT sent/, { selector: '.msg-bar' } ) ).toBeInTheDocument();
    expect( screen.queryByText( /before retrying/, { selector: '.msg-bar' } ) ).toBeNull();
    expect( screen.queryByText( 'WhatsApp payment request sent.' ) ).toBeNull();
  } );

  it( 'treats a 409 refusal failure as terminal too', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: false, failure: { kind: 'http', status: 409, message: 'This payment request was refused and was not sent.', url: '/x', retryable: false, at: 0 } } );
    await createAndSend();
    await screen.findByText( /Cancel and raise the collection again — do not retry/, { selector: '.msg-bar' } );
  } );
} );

describe( 'an in-progress send (deduplicated no-op)', () => {
  it( 'tells the operator not to resend', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: true, data: { status: 'send_in_progress', deduplicated: true } } );
    await createAndSend();
    await screen.findByText( /A send is already in progress; do not resend/, { selector: '.msg-bar' } );
  } );
} );

describe( 'an unknown / PENDING outcome (502)', () => {
  it( 'tells the operator to reconcile before retrying', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: false, failure: { kind: 'unavailable', status: 502, message: 'Bad gateway', url: '/x', retryable: true, at: 0 } } );
    await createAndSend();
    await screen.findByText( /Outcome unknown. Reconcile in the ledger before retrying/, { selector: '.msg-bar' } );
  } );

  it( 'also reconciles a 200 whose sendStatus is PENDING and whose command status is unresolved', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: true, data: { status: 'accepted', sendStatus: 'PENDING', deduplicated: false } } );
    getInvoiceDeliveryLog.mockResolvedValue( { deliveryLogs: [] } );
    await createAndSend();
    await screen.findByText( /Outcome unknown. Reconcile in the ledger before retrying/, { selector: '.msg-bar' } );
  } );
} );

describe( 'banner stickiness (Finding 10c)', () => {
  it( 'keeps an error banner past the 4s success auto-dismiss window', async () => {
    sendPaymentLinkResult.mockResolvedValue( { ok: true, data: { status: 'payment_link_rejected', sendStatus: 'REJECTED' } } );
    await createAndSend();
    // Let the real send resolve and the error banner paint.
    await screen.findByText( /was refused and was NOT sent/, { selector: '.msg-bar' } );
    const errorBar = document.querySelector( '.msg-bar.error' );
    expect( errorBar ).not.toBeNull();
    // Advance real time well past the 4s success window; the error banner must still be mounted
    // because showMsg never arms a dismiss timer for errors.
    await new Promise( resolve => setTimeout( resolve, 50 ) );
    expect( document.querySelector( '.msg-bar.error' ) ).not.toBeNull();
    expect( document.querySelector( '.msg-bar.error' )?.textContent ).toContain( 'do not retry' );
  } );

  it( 'auto-dismisses a success banner', async () => {
    vi.useFakeTimers();
    try {
      sendPaymentLinkResult.mockResolvedValue( { ok: true, data: { status: 'payment_link_sent' } } );
      render( <PayFlowPage embedded mode="collect" /> );
      await act( async () => { await Promise.resolve(); } );
      fireEvent.click( screen.getByText( 'Asha Rao' ) );
      await act( async () => { await Promise.resolve(); } );
      const prices = screen.getAllByRole( 'spinbutton' );
      fireEvent.change( prices[ 0 ], { target: { value: '2' } } );
      fireEvent.click( screen.getByRole( 'button', { name: 'Create and send payment request' } ) );
      await act( async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); } );
      expect( document.querySelector( '.msg-bar.success' ) ).not.toBeNull();
      await act( async () => { vi.advanceTimersByTime( 4100 ); } );
      expect( document.querySelector( '.msg-bar.success' ) ).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  } );
} );

const pendingInvoice = {
  ...SERVER_CREATE, status: 'pending_payment', paymentStatus: 'pending',
  customerName: CUSTOMER.name, customerPhone: CUSTOMER.phone, createdAt: 1770000000,
};

describe( 'read-only Ledger (Finding 10a)', () => {
  it( 'hides the Send/Retry payment-request action in mode="invoices"', async () => {
    listInvoicesEngine.mockResolvedValue( { invoices: [ pendingInvoice ] } );
    render( <PayFlowPage embedded mode="invoices" /> );
    fireEvent.click( await screen.findByText( 'ref_1' ) );
    expect( await screen.findByText( 'Invoice Detail' ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: 'Retry payment request' } ) ).toBeNull();
    expect( screen.queryByRole( 'button', { name: 'Send payment request' } ) ).toBeNull();
    // Non-mutating evidence/export stays available.
    expect( screen.getByRole( 'button', { name: 'Generate Image' } ) ).toBeInTheDocument();
  } );

  it( 'keeps the Send/Retry action available in the standalone Collect-owning PayFlow', async () => {
    listInvoicesEngine.mockResolvedValue( { invoices: [ pendingInvoice ] } );
    // Non-embedded, default mode='collect': the Invoices tab still offers the mutating action.
    render( <PayFlowPage /> );
    fireEvent.click( await screen.findByText( 'Invoices' ) );
    fireEvent.click( await screen.findByText( 'ref_1' ) );
    expect( await screen.findByRole( 'button', { name: 'Retry payment request' } ) ).toBeInTheDocument();
  } );
} );
