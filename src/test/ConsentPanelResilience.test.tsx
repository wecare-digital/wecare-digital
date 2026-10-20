import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getConsent = vi.fn();
vi.mock( '../api/client', () => ( { getConsent: ( ...args: unknown[] ) => getConsent( ...args ) } ) );
vi.mock( '../contexts/ToastContext', () => ( { useToastContext: () => ( { success: vi.fn(), error: vi.fn() } ) } ) );
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn() } ) );
import ConsentPanel from '../components/workspace/customers/ConsentPanel';

afterEach( cleanup );
describe( 'Customer detail consent availability', () => {
  it( 'keeps the customer detail open when an older API returns a contact list', async () => {
    getConsent.mockResolvedValue( { ok: true, data: { contacts: [] } } );
    render( <ConsentPanel contactId="qa-contact" /> );
    expect( await screen.findByText( 'Consent evidence is unavailable. Refresh to try again.' ) ).toBeTruthy();
    expect( screen.getByRole( 'heading', { name: 'Consent & permissions' } ) ).toBeTruthy();
  } );
  it( 'renders no evidence for each channel when the current ledger is empty', async () => {
    getConsent.mockResolvedValue( { ok: true, data: { contactId: 'qa-contact', ledger: [], summary: {} } } );
    render( <ConsentPanel contactId="qa-contact" /> );
    expect( ( await screen.findAllByText( 'No consent evidence recorded — this channel is not sendable.' ) ).length ).toBe( 6 );
  } );
} );
