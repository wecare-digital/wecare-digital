/**
 * Changing the sender on a payment request must RE-LOCK the admin-verification gate.
 *
 * WHY THIS FILE EXISTS. `engage/inbox`'s send-from chooser was the one control the migration
 * design named individually, because its handler is the only migrated one in the payment batch
 * with TWO statements:
 *
 *     onChange={ v => { setPayPhone( v ); setPayUnlocked( false ); } }
 *
 * The second statement resets the gate. One of the two payment-enabled numbers is
 * `paymentProtected`, and the panel refuses to send from it until `Verify Admin access`
 * succeeds. A migrated handler that quietly lost `setPayUnlocked( false )` would carry a
 * verification granted for one number over to another, with nothing erroring, nothing logging
 * and the Send button still enabled - so the batch's instruction was to assert it in a test
 * rather than by reading the diff.
 *
 * TWO ASSERTIONS, BECAUSE ONE CANNOT COVER IT. The behavioural test proves the statement is
 * still CALLED: unlock the protected number, move away, come back, and the lock must be back.
 * It cannot prove the ORDER, because React batches both state writes into one render and the
 * two orderings are indistinguishable from the outside - so the order is held by a source
 * assertion on the handler body, which is the only thing that can see it.
 */
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

vi.mock( '../api/client', async () => {
  const actual = await vi.importActual<any>( '../api/client' );
  return {
    ...actual,
    listMessages: ( ...a: unknown[] ) => listMessages( ...a ),
    listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
    verifyAdminAccess: ( ...a: unknown[] ) => verifyAdminAccess( ...a ),
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
  listContacts.mockResolvedValue( [ { contactId: 'c-1', name: 'Asha' } ] );
  verifyAdminAccess.mockResolvedValue( true );
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

describe( 'the payment panel re-locks when the sender changes', () => {
  it( 'starts locked on the protected number, which is the default sender', async () => {
    await openPayPanel();
    // PAYMENT_CONFIG.phoneNumberId is the protected number, so the gate is up before anything
    // is touched. If this ever stops being true the rest of the file is measuring nothing.
    expect( paySender().textContent ).toContain( 'Protected' );
    expect( payLock() ).toBeTruthy();
  } );

  it( 'clears the lock once admin access verifies', async () => {
    await openPayPanel();
    fireEvent.click( payLock()! );
    await waitFor( () => expect( payLock() ).toBeNull() );
    expect( verifyAdminAccess ).toHaveBeenCalled();
  } );

  it( 'puts the lock BACK when the sender changes away and returns', async () => {
    await openPayPanel();
    fireEvent.click( payLock()! );
    await waitFor( () => expect( payLock() ).toBeNull() );

    // Away to the unprotected number, then back. This is the exact path the dropped statement
    // would break: with `setPayUnlocked( false )` gone, `payUnlocked` would still be true on
    // the return and the protected number would render UNLOCKED.
    chooseSender( OPEN_NUMBER );
    expect( paySender().textContent ).not.toContain( 'Protected' );

    chooseSender( PROTECTED );
    expect( paySender().textContent ).toContain( 'Protected' );
    expect( payLock() ).toBeTruthy();
  } );
} );

describe( 'the source keeps both statements, in order', () => {
  it( 'calls setPayPhone and THEN setPayUnlocked( false ) in the migrated handler', () => {
    // Comments are stripped first: the note beside the handler explains the rule and therefore
    // contains both calls verbatim, so a check against the raw source would pass on its own
    // commentary. The same trap three earlier batches recorded.
    const code = SRC
      .replace( /\/\*[\s\S]*?\*\//g, '' )
      .replace( /\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '' )
      .replace( /^\s*\/\/.*$/gm, '' );
    expect( code ).toMatch(
      /onChange=\{\s*v\s*=>\s*\{\s*setPayPhone\(\s*v\s*\);\s*setPayUnlocked\(\s*false\s*\);\s*\}\s*\}/
    );
    // And no native select is left in the file at all - the two money controls were the last.
    expect( code ).not.toMatch( /<select/ );
  } );
} );
