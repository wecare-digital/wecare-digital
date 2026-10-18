/** Manual payment requests use the approved sender and the server-owned invoice path. */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';

/*
 * THE DEFAULT EXPORT IS NOT OPTIONAL HERE, and leaving it out is how the first run of this file
 * failed. `Popover` - which the combobox menu portals through - reads the next/router SINGLETON
 * (`Router.events`) rather than `useRouter()`, because `useRouter()` throws without a mounted
 * RouterContext and this primitive is mounted by dozens of suites that provide no router. A mock
 * with only `useRouter` therefore leaves `Router` undefined and the menu cannot open at all.
 */
vi.mock( 'next/router', () => ( {
  default: { events: { on: vi.fn(), off: vi.fn(), emit: vi.fn() } },
  useRouter: () => ( {
    query: {},
    isReady: true,
    push: vi.fn(),
    pathname: '/workspace/engage/inbox',
  } ),
} ) );

vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: { accessToken: { toString: () => 't' } } } ),
} ) );

const listMessages = vi.fn();
const listContacts = vi.fn();
const verifyAdminAccess = vi.fn();
const createInvoiceEngine = vi.fn();
const sendPaymentLink = vi.fn();

vi.mock( '../api/client', async () => {
  const actual = await vi.importActual<any>( '../api/client' );
  return {
    ...actual,
    listMessages: ( ...a: unknown[] ) => listMessages( ...a ),
    listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
    verifyAdminAccess: ( ...a: unknown[] ) => verifyAdminAccess( ...a ),
    createInvoiceEngine: ( ...a: unknown[] ) => createInvoiceEngine( ...a ),
    sendPaymentLink: ( ...a: unknown[] ) => sendPaymentLink( ...a ),
    listRcsTemplates: vi.fn().mockResolvedValue( [] ),
    getPollyVoices: vi.fn().mockResolvedValue( { voices: {} } ),
    listAutomationRules: vi.fn().mockResolvedValue( [] ),
    getConversationMeta: vi.fn().mockResolvedValue( null ),
  };
} );

import UnifiedInbox from '../pages/workspace/engage/inbox/index';
import { ToastProvider } from '../contexts/ToastContext';

const SRC = fs.readFileSync(
  path.resolve( __dirname, '../pages/workspace/engage/inbox/index.tsx' ), 'utf8' );

const Inbox: React.FC = () => (
  <ToastProvider>
    <UnifiedInbox embedded />
  </ToastProvider>
);

/** The two payment-enabled numbers, by the name the chooser renders. */
const PROTECTED = '+91 99033 00044 (Manish Agarwal) [Protected]';
const OPEN_NUMBER = '+91 93309 94400 (WECARE.DIGITAL)';
const UNLOCK = 'Verify Admin access';

/**
 * The pay panel's own send-from chooser.
 *
 * SCOPED, AND NOT OUT OF TIDINESS. The reply bar above the composer has its OWN "Send from"
 * chooser - which WABA sends an outbound WhatsApp message - migrated in batch 2c. Two controls
 * carry that accessible name, so an unscoped `getByRole` matches both and the first run of this
 * file failed on exactly that. The money control is the one inside `.ui-pay`.
 */
const paySender = (): HTMLElement => {
  const panel = document.querySelector( '.ui-pay' );
  if ( !panel ) throw new Error( 'the Request payment panel is not open' );
  return within( panel as HTMLElement ).getByRole( 'combobox', { name: 'Send from' } );
};

const payLock = () => screen.queryByRole( 'button', { name: UNLOCK } );

/**
 * Open the menu and click a row - the real user action against a button-plus-listbox. The
 * option is queried from the whole document because the menu is portalled to document.body.
 */
const chooseSender = ( option: string ) => {
  fireEvent.click( paySender() );
  fireEvent.click( screen.getByRole( 'option', { name: option } ) );
};

beforeEach( () => {
  listMessages.mockResolvedValue( [ {
    id: 'm1', messageId: 'm1', contactId: 'c-1', channel: 'WHATSAPP',
    direction: 'INBOUND', content: 'hello', status: 'received',
    timestamp: new Date( '2026-10-06T09:00:00Z' ).toISOString(),
    senderPhone: '+918100640044',
  } ] );
  listContacts.mockResolvedValue( [ { contactId: 'c-1', name: 'Asha', phone: '+919999999999' } ] );
  vi.clearAllMocks();
  verifyAdminAccess.mockResolvedValue( true );
  createInvoiceEngine.mockResolvedValue( { invoiceId: 'inv-manual', invoiceNumber: 'WD-TEST', total: 100 } );
  sendPaymentLink.mockResolvedValue( { status: 'sent' } );
  if ( !( 'scrollIntoView' in Element.prototype ) ) {
    ( Element.prototype as any ).scrollIntoView = () => {};
  }
} );

/** Reach the "Request payment" panel: pick the conversation, then the pay tool. */
async function openPayPanel () {
  render( <Inbox /> );
  fireEvent.click( await screen.findByText( 'Asha' ) );
  fireEvent.click( await screen.findByTitle( 'Request payment' ) );
  expect( await screen.findByText( 'Request payment' ) ).toBeTruthy();
}

describe( 'manual invoice-backed payment collection', () => {
  it( 'offers only the primary payment sender while normal conversation senders stay separate', async () => {
    await openPayPanel();
    expect( paySender().textContent ).toContain( OPEN_NUMBER );
    expect( payLock() ).toBeNull();
    fireEvent.click( paySender() );
    expect( screen.queryByRole( 'option', { name: PROTECTED } ) ).toBeNull();
    expect( screen.getByRole( 'option', { name: OPEN_NUMBER } ) ).toBeTruthy();
  } );

  it( 'raises an invoice before sending and leaves discount/configuration decisions to the server', async () => {
    await openPayPanel();
    fireEvent.change( screen.getByPlaceholderText( 'Item / service' ), { target: { value: 'Consultation' } } );
    fireEvent.change( screen.getByPlaceholderText( '₹ Amount' ), { target: { value: '100' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send payment request' } ) );
    await waitFor( () => expect( sendPaymentLink ).toHaveBeenCalledWith(
      'inv-manual', 'phone-number-id-waba1-direct-1016149501586345' ) );
    expect( createInvoiceEngine.mock.calls[ 0 ][ 0 ] ).toMatchObject( {
      goodsType: 'digital-goods', entryPoint: 'inbox', items: [ { name: 'Consultation', amount: 100 } ],
    } );
    expect( createInvoiceEngine.mock.calls[ 0 ][ 0 ] ).not.toHaveProperty( 'discount' );
    expect( createInvoiceEngine.mock.calls[ 0 ][ 0 ] ).not.toHaveProperty( 'paymentConfiguration' );
    expect( createInvoiceEngine.mock.invocationCallOrder[ 0 ] ).toBeLessThan( sendPaymentLink.mock.invocationCallOrder[ 0 ] );
  } );

  it( 'does not send if invoice creation is refused', async () => {
    createInvoiceEngine.mockResolvedValue( null );
    await openPayPanel();
    fireEvent.change( screen.getByPlaceholderText( 'Item / service' ), { target: { value: 'Consultation' } } );
    fireEvent.change( screen.getByPlaceholderText( '₹ Amount' ), { target: { value: '100' } } );
    const before = sendPaymentLink.mock.calls.length;
    fireEvent.click( screen.getByRole( 'button', { name: 'Send payment request' } ) );
    await screen.findByText( 'Could not raise the invoice. Check Pay → Invoices before trying again.' );
    expect( sendPaymentLink.mock.calls.length ).toBe( before );
  } );
  it( 'reuses the retained invoice when delivery is refused instead of creating another collection', async () => {
    sendPaymentLink.mockResolvedValueOnce( null ).mockResolvedValue( { status: 'sent' } );
    await openPayPanel();
    fireEvent.change( screen.getByPlaceholderText( 'Item / service' ), { target: { value: 'Consultation' } } );
    fireEvent.change( screen.getByPlaceholderText( '₹ Amount' ), { target: { value: '100' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send payment request' } ) );
    await screen.findByText( /Invoice WD-TEST is retained/ );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send payment request' } ) );
    await waitFor( () => expect( sendPaymentLink ).toHaveBeenCalledTimes( 2 ) );
    expect( createInvoiceEngine ).toHaveBeenCalledTimes( 1 );
    expect( sendPaymentLink.mock.calls.map( call => call[ 0 ] ) ).toEqual( [ 'inv-manual', 'inv-manual' ] );
  } );

} );
