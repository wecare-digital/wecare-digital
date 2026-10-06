/**
 * A reply must go out on the WABA the conversation arrived on.
 *
 * `selectedWaba` was seeded to `WABAS[0]` and never synced to the open thread, and
 * the send sites read `selectedWaba || waba` — so the correct value, derived from
 * the thread's `awsPhoneNumberId`, was unreachable and every reply to a WABA2
 * thread went out from WABA1 unless the agent changed the dropdown by hand. That
 * opens a conversation on a number the customer never wrote to, and it is what
 * produced 17 `typing_indicator_error` plus 12 code-100 "Message ID … does not
 * exist" in 30 days: the wamid belongs to the other WABA.
 *
 * These assert on the argument actually passed to the API, not on component state.
 * State being right is not the property that matters.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WHATSAPP_PHONES } from '../config/constants';

const WABA1 = WHATSAPP_PHONES.primary.id;
const WABA2 = WHATSAPP_PHONES.secondary.id;

let routerQuery: Record<string, string> = {};

vi.mock( 'next/router', () => ( {
  useRouter: () => ( {
    query: routerQuery,
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
const sendWhatsAppMessage = vi.fn();
const sendTypingIndicator = vi.fn();

vi.mock( '../api/client', async () => {
  const actual = await vi.importActual<any>( '../api/client' );
  return {
    ...actual,
    listMessages: ( ...a: unknown[] ) => listMessages( ...a ),
    listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
    sendWhatsAppMessage: ( ...a: unknown[] ) => sendWhatsAppMessage( ...a ),
    sendTypingIndicator: ( ...a: unknown[] ) => sendTypingIndicator( ...a ),
    listRcsTemplates: vi.fn().mockResolvedValue( [] ),
    getPollyVoices: vi.fn().mockResolvedValue( { voices: {} } ),
    listAutomationRules: vi.fn().mockResolvedValue( [] ),
    getConversationMeta: vi.fn().mockResolvedValue( null ),
  };
} );

import UnifiedInbox from '../pages/workspace/engage/inbox/index';
import { ToastProvider } from '../contexts/ToastContext';

const Inbox: React.FC = () => (
  <ToastProvider>
    <UnifiedInbox embedded />
  </ToastProvider>
);

/** Mirrors what the API returns: UPPERCASE channel, camelCase fields. */
function inbound( awsPhoneNumberId?: string ) {
  return {
    id: 'm1', messageId: 'm1', contactId: 'c-1', channel: 'WHATSAPP',
    direction: 'INBOUND', content: 'hello',
    timestamp: new Date( '2026-10-06T09:00:00Z' ).toISOString(),
    status: 'received', senderPhone: '+918100640044',
    whatsappMessageId: 'wamid.ORIG1',
    ...( awsPhoneNumberId ? { awsPhoneNumberId } : {} ),
  };
}

async function openThread() {
  fireEvent.click( await screen.findByText( 'Asha' ) );
  await waitFor( () => expect( document.querySelector( '.ui-msg-bubble' ) ).toBeTruthy() );
}

/** Type into the composer and press Send. */
async function sendReply( container: HTMLElement, text = 'on my way' ) {
  const input = container.querySelector( '.ui-reply-input' ) as HTMLTextAreaElement;
  expect( input ).toBeTruthy();
  fireEvent.change( input, { target: { value: text } } );
  const btn = container.querySelector( '.ui-reply-btn' ) as HTMLButtonElement;
  await waitFor( () => expect( btn.disabled ).toBe( false ) );
  fireEvent.click( btn );
  await waitFor( () => expect( sendWhatsAppMessage ).toHaveBeenCalled() );
}

function sentPhoneNumberId() {
  return ( sendWhatsAppMessage.mock.calls[ 0 ][ 0 ] as any ).phoneNumberId;
}

beforeEach( () => {
  routerQuery = {};
  sendWhatsAppMessage.mockReset();
  sendWhatsAppMessage.mockResolvedValue( { messageId: 'wamid.OUT1' } );
  sendTypingIndicator.mockReset();
  sendTypingIndicator.mockResolvedValue( {} );
  listContacts.mockResolvedValue( [ { contactId: 'c-1', name: 'Asha' } ] );
  if ( !( 'scrollIntoView' in Element.prototype ) )
  {
    ( Element.prototype as any ).scrollIntoView = () => {};
  }
} );

describe( 'a reply goes out on the conversation\'s own WABA', () => {
  it( 'answers a WABA2 thread from WABA2', async () => {
    // The regression test. On the old code this sent from WABA1, because
    // `selectedWaba` was seeded to WABAS[0] and won the `||`.
    listMessages.mockResolvedValue( [ inbound( WABA2 ) ] );
    const { container } = render( <Inbox /> );
    await openThread();
    await sendReply( container );

    expect( sentPhoneNumberId() ).toBe( WABA2 );
  } );

  it( 'answers a WABA1 thread from WABA1', async () => {
    // Guards the over-correction: the fix must not send everything on WABA2.
    listMessages.mockResolvedValue( [ inbound( WABA1 ) ] );
    const { container } = render( <Inbox /> );
    await openThread();
    await sendReply( container );

    expect( sentPhoneNumberId() ).toBe( WABA1 );
  } );

  it( 'sends the typing indicator on the thread\'s WABA, not the default', async () => {
    // The indicator carries the inbound wamid, which only exists on that WABA.
    listMessages.mockResolvedValue( [ inbound( WABA2 ) ] );
    const { container } = render( <Inbox /> );
    await openThread();
    const input = container.querySelector( '.ui-reply-input' ) as HTMLTextAreaElement;
    fireEvent.change( input, { target: { value: 'typing…' } } );

    await waitFor( () => expect( sendTypingIndicator ).toHaveBeenCalled() );
    expect( sendTypingIndicator.mock.calls[ 0 ][ 0 ] ).toBe( WABA2 );
    expect( sendTypingIndicator.mock.calls[ 0 ][ 1 ] ).toBe( 'wamid.ORIG1' );
  } );
} );

describe( 'the agent can still override the WABA', () => {
  it( 'honours a deliberate "Send from" change', async () => {
    // This is what stops the fix becoming a new bug: choosing another number is a
    // feature, not an accident, so a manual change must win over the thread.
    listMessages.mockResolvedValue( [ inbound( WABA1 ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    const select = container.querySelector( 'select.ui-wa-waba' ) as HTMLSelectElement;
    expect( select ).toBeTruthy();
    expect( select.value ).toBe( WABA1 );   // defaults to the thread's own WABA
    fireEvent.change( select, { target: { value: WABA2 } } );

    await sendReply( container );
    expect( sentPhoneNumberId() ).toBe( WABA2 );
  } );

  it( 'leaves the dropdown on a real option when the thread names no WABA', async () => {
    // Older rows carry no `awsPhoneNumberId`. The sync is guarded on membership, so
    // it must not blank the <select> or set it to a value with no <option>.
    listMessages.mockResolvedValue( [ inbound( undefined ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    const select = container.querySelector( 'select.ui-wa-waba' ) as HTMLSelectElement;
    expect( [ WABA1, WABA2 ] ).toContain( select.value );

    await sendReply( container );
    expect( [ WABA1, WABA2 ] ).toContain( sentPhoneNumberId() );
  } );
} );
