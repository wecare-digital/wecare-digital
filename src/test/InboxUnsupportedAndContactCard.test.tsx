/**
 * Two things an agent must never be shown, pinned at the rendered output.
 *
 * 1. Meta's own error text. A message WhatsApp refuses to hand over was rendering
 *    as `[Unsupported: Message type unknown]` in the bubble AND in the conversation
 *    preview, which reads as our system failing rather than as WhatsApp withholding
 *    something. The guard that was supposed to catch it tested full-string equality
 *    against a string the extractor never produced, while missing the one it always
 *    did — so these assertions are on `container.textContent`, which covers the
 *    bubble and the preview together, and on the PREFIX.
 *
 * 2. A shared contact card with its data thrown away. Puneet's card arrived, stored
 *    and acknowledged, and the inbox showed the words "Contact card" — so the agent
 *    asked the customer to retype the number. A card with a payload must render the
 *    name and a `tel:` link; a card without one keeps the plain label, which is what
 *    the row stored before ingest captured the payload still has.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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

vi.mock( '../api/client', async () => {
  const actual = await vi.importActual<any>( '../api/client' );
  return {
    ...actual,
    listMessages: ( ...a: unknown[] ) => listMessages( ...a ),
    listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
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
function msg( over: Partial<Record<string, unknown>> = {} ) {
  return {
    id: 'm1', messageId: 'm1', contactId: 'c-1', channel: 'WHATSAPP',
    direction: 'INBOUND', content: 'hello',
    timestamp: new Date( '2026-10-06T09:00:00Z' ).toISOString(),
    status: 'received', senderPhone: '+918100640044', ...over,
  };
}

/** Open the thread so the message bubble renders, not only the list preview. */
async function openThread() {
  fireEvent.click( await screen.findByText( 'Asha' ) );
  await waitFor( () => expect( document.querySelector( '.ui-msg-bubble' ) ).toBeTruthy() );
}

beforeEach( () => {
  routerQuery = {};
  listContacts.mockResolvedValue( [ { contactId: 'c-1', name: 'Asha' } ] );
  if ( !( 'scrollIntoView' in Element.prototype ) )
  {
    ( Element.prototype as any ).scrollIntoView = () => {};
  }
} );

describe( 'an unsupported message never shows Meta error text', () => {
  it( 'replaces a legacy row that already stored Meta\'s title', async () => {
    // Rows written before the extractor changed still hold this string, which is
    // why the UI guard has to stand on its own rather than trusting the stored value.
    listMessages.mockResolvedValue( [ msg( {
      content: '[Unsupported: Message type unknown]', messageType: 'unsupported',
    } ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    expect( container.textContent ).toContain( 'Unsupported message' );
    expect( container.textContent ).not.toContain( '[Unsupported:' );
    expect( container.textContent ).not.toContain( 'Message type unknown' );
  } );

  it( 'also handles the new stable sentinel, so neither side can regress alone', async () => {
    listMessages.mockResolvedValue( [ msg( {
      content: '[Unsupported: WhatsApp did not say what this message was]',
      messageType: 'unsupported',
    } ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    expect( container.textContent ).toContain( 'Unsupported message' );
    expect( container.textContent ).not.toContain( '[Unsupported:' );
  } );
} );

describe( 'a shared contact card renders its data', () => {
  it( 'shows the name and a tel: link when the payload was stored', async () => {
    listMessages.mockResolvedValue( [ msg( {
      content: '[Contact Card] Punit Kumar · +918031830030',
      messageType: 'contacts',
      contactsPayload: [ {
        name: { formatted_name: 'Punit Kumar' },
        phones: [ { phone: '+918031830030', type: 'CELL' } ],
      } ],
    } ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    expect( container.textContent ).toContain( 'Punit Kumar' );
    const tel = container.querySelector( 'a[href="tel:+918031830030"]' );
    expect( tel ).toBeTruthy();
    // The copy button is the whole point: the agent had to ask for the number again.
    expect( container.querySelector( 'button[aria-label*="Copy phone number"]' ) ).toBeTruthy();
    // The bracket label is an internal marker, not something to show an agent.
    expect( container.textContent ).not.toContain( '[Contact Card]' );
  } );

  it( 'keeps the plain label for a row with no payload', async () => {
    // Punit's existing row. The payload was never captured, so there is nothing to
    // backfill and the fallback is the only correct rendering.
    listMessages.mockResolvedValue( [ msg( {
      content: '[Contact Card]', messageType: 'contacts',
    } ) ] );
    const { container } = render( <Inbox /> );
    await openThread();

    expect( container.textContent ).toContain( 'Contact card' );
    expect( container.querySelector( 'a[href^="tel:"]' ) ).toBeNull();
    expect( container.textContent ).not.toContain( '[Contact Card]' );
  } );
} );
