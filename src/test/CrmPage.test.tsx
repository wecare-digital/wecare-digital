/**
 * The CRM contacts page: the legacy public route is gone, and the inline cell editor speaks the
 * same phone contract as the dialog form.
 *
 * WHY THE PHONE HALF EXISTS. `contacts/handler.py::_e164_or_error` refuses a number carrying no
 * dial code with 400 `PHONE_COUNTRY_CODE_REQUIRED` instead of guessing `+91`, because guessing
 * sends an OTP to an unrelated Indian subscriber for a ten-digit foreign number and reserves the
 * wrong identity permanently. The refusal is right; what was wrong was the caller. The phone cell
 * is inline-editable, its client guard (`isValidPhone`) accepts a bare `9876543210`, and it PUT
 * the raw cell value — so an operator retyping a national number got a 400 that `updateContact`
 * collapsed to `null`, which the page treated as a no-op. Editor already closed, stale value
 * re-rendered, no toast: the save looked like it worked.
 *
 * These two tests pin both halves of the fix, on the arguments handed to the API client rather
 * than on the wire body: the dial code is composed before sending, and a server refusal is
 * visible.
 */
import React from 'react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{ children }</div> } ) );
vi.mock( '../components/SEO', () => ( { default: () => null, PAGE_SEO: {} } ) );
const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastWarning = vi.fn();
// ONE object, not a fresh one per render. `loadContacts` is `useCallback(..., [toast])` and the
// effect that calls it depends on that callback, so a new toast reference on every render reloads
// the list forever and the table unmounts under the editor mid-test.
const TOAST = { success: toastSuccess, error: toastError, info: vi.fn(), warning: toastWarning };
vi.mock( '../contexts/ToastContext', () => ( { useToastContext: () => TOAST } ) );
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );
const listContacts = vi.fn();
const updateContactResult = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listContacts: ( ...a: unknown[] ) => listContacts( ...a ),
  updateContactResult: ( ...a: unknown[] ) => updateContactResult( ...a ),
  listFlowLogs: vi.fn().mockResolvedValue( [] ),
  listMessages: vi.fn().mockResolvedValue( [] ),
} ) );
import ContactsPage from '../pages/workspace/contacts';

/** One existing row, already stored in E.164, as `normalizeContact` hands it over. */
const ROW = {
  id: 'c_1', contactId: 'c_1', name: 'Asha', phone: '+919812345678', email: 'asha@example.com',
  tags: [], createdAt: '1700000000', updatedAt: '1700000000',
};

/** Open the inline editor on the phone cell and return its live input. */
const openPhoneEditor = async (): Promise<HTMLInputElement> => {
  render( <ContactsPage /> );
  fireEvent.doubleClick( await screen.findByText( '+919812345678' ) );
  return await screen.findByDisplayValue( '+919812345678' ) as HTMLInputElement;
};

beforeEach( () => {
  vi.clearAllMocks();
  listContacts.mockResolvedValue( [ { ...ROW } ] );
  updateContactResult.mockResolvedValue( { ok: true, data: { ...ROW } } );
} );

describe( 'legacy CRM public route', () => {
  it( 'is deleted from the public page tree', () => {
    expect( existsSync( resolve( process.cwd(), 'src/pages/crm/index.tsx' ) ) ).toBe( false );
  } );
} );

describe( 'CRM inline phone edit', () => {
  it( 'sends a +-prefixed E.164 when the operator types a bare national number', async () => {
    const input = await openPhoneEditor();
    fireEvent.change( input, { target: { value: '9876543210' } } );
    fireEvent.keyDown( input, { key: 'Enter' } );
    await waitFor( () => expect( updateContactResult ).toHaveBeenCalled() );
    // The default dial code is +91, the same one the dialog form composes with.
    expect( updateContactResult ).toHaveBeenCalledWith( 'c_1', { phone: '+919876543210' } );
    // Nothing bare reaches the server, because the server refuses it with a 400.
    const [ , updates ] = updateContactResult.mock.calls[ 0 ] as [ string, { phone: string } ];
    expect( updates.phone.startsWith( '+' ) ).toBe( true );
  } );

  it( 'leaves an already-qualified number exactly as typed', async () => {
    const input = await openPhoneEditor();
    fireEvent.change( input, { target: { value: '+6591234567' } } );
    fireEvent.keyDown( input, { key: 'Enter' } );
    await waitFor( () => expect( updateContactResult ).toHaveBeenCalled() );
    // No second dial code is prepended — the Singapore number must not become +9165...
    expect( updateContactResult ).toHaveBeenCalledWith( 'c_1', { phone: '+6591234567' } );
  } );

  it( 'shows the server refusal instead of silently reverting the cell', async () => {
    updateContactResult.mockResolvedValue( {
      ok: false,
      failure: {
        kind: 'http', status: 400, retryable: false, at: 0,
        url: 'https://wecare.digital/api/contacts/c_1',
        message: 'HTTP 400: Phone number must include a country code, e.g. +91',
      },
    } );
    const input = await openPhoneEditor();
    fireEvent.change( input, { target: { value: '9876543210' } } );
    fireEvent.keyDown( input, { key: 'Enter' } );
    await waitFor( () => expect( toastError ).toHaveBeenCalled() );
    // The operator is told WHY, not just that something failed.
    expect( String( toastError.mock.calls[ 0 ][ 0 ] ) ).toContain( 'country code' );
    // And a refusal is never reported as a success.
    expect( toastSuccess ).not.toHaveBeenCalled();
  } );
} );
