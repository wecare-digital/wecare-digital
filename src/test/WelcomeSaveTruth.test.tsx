import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
const mock = vi.hoisted( () => ( { save: vi.fn(), success: vi.fn(), error: vi.fn() } ) );
vi.mock( '../api/client', () => ( { getSystemConfig: vi.fn().mockResolvedValue( null ), updateSystemConfig: mock.save } ) );
vi.mock( '../contexts/ToastContext', () => ( { useToastContext: () => ( { success: mock.success, error: mock.error } ) } ) );
vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{children}</div> } ) );
import Welcome from '../pages/workspace/engage/whatsapp/welcome';
afterEach( () => { cleanup(); vi.clearAllMocks(); } );
describe( 'welcome settings retain drafts on unconfirmed saves', () => {
  it( 'shows an error and retains the text instead of claiming success', async () => {
    mock.save.mockResolvedValue( false );
    render( <Welcome embedded /> );
    const save = await screen.findByRole( 'button', { name: 'Save Configuration' } );
    const draft = screen.getByPlaceholderText( 'Enter your welcome message for new users...' );
    fireEvent.change( draft, { target: { value: 'My unsaved welcome' } } );
    fireEvent.click( save );
    await waitFor( () => expect( mock.error ).toHaveBeenCalledWith( expect.stringContaining( 'could not be confirmed' ) ) );
    expect( mock.success ).not.toHaveBeenCalled();
    expect( draft ).toHaveValue( 'My unsaved welcome' );
    expect( save ).not.toBeDisabled();
  } );
  it( 'announces success only after the verified client succeeds', async () => {
    mock.save.mockResolvedValue( true );
    render( <Welcome embedded /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Save Configuration' } ) );
    await waitFor( () => expect( mock.success ).toHaveBeenCalledWith( 'Configuration saved!' ) );
    expect( mock.error ).not.toHaveBeenCalled();
  } );
} );
