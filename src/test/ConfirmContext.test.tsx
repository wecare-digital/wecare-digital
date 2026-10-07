/**
 * ConfirmContext — the free-text prompt, and the four dialogs that stopped being native.
 *
 * WHY THESE CASES AND NOT A SNAPSHOT. Every assertion here corresponds to a specific way the
 * prompt could have been got wrong while still looking right on screen:
 *
 *   - it resolves the TRIMMED string, because a reason of "   " is not a reason, and the
 *     backend's 10-character floor is measured on the trimmed value;
 *   - it resolves null on cancel, Escape and backdrop, because `window.prompt` returned null
 *     and the two call sites branch on exactly that;
 *   - `required` and `minLength` each independently disable confirm, because the floor has to
 *     hold when the other one is absent;
 *   - Enter inside a textarea must NOT submit, because the shared shell puts onKeyDown on the
 *     backdrop div, so with multiline: true the newline key would have become a submit — and
 *     a single-line prompt must still submit on Enter, which is what the native dialog did;
 *   - focus returns to the opener, which was never true before. With a text field a keyboard
 *     operator who cancels is otherwise dropped at the top of the document.
 *
 * The second describe block renders each migrated call site for real and asserts our dialog
 * appears. window.confirm and window.prompt are replaced with throwing spies for the whole
 * file, so "it still calls the global" fails loudly rather than passing silently in jsdom,
 * where the natives return undefined and every guard would simply read as "cancelled".
 */
import React, { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{ children }</div> } ) );
vi.mock( '../components/SEO', () => ( { default: () => null } ) );
vi.mock( '../contexts/ToastContext', () => ( {
  useToastContext: () => ( { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } ),
} ) );

const listTemplates = vi.fn();
const listSendMedia = vi.fn();
const deleteSendMedia = vi.fn();
const listSecureFiles = vi.fn();
const revokeSecureFile = vi.fn();
const adAccounts = vi.fn();
const pages = vi.fn();
const ads = vi.fn();
const publish = vi.fn();
vi.mock( '../api/client', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/client' )>(),
  listTemplates: ( ...a: unknown[] ) => listTemplates( ...a ),
  listSendMedia: ( ...a: unknown[] ) => listSendMedia( ...a ),
  deleteSendMedia: ( ...a: unknown[] ) => deleteSendMedia( ...a ),
  listSecureFiles: ( ...a: unknown[] ) => listSecureFiles( ...a ),
  revokeSecureFile: ( ...a: unknown[] ) => revokeSecureFile( ...a ),
  marketingAdsApi: {
    adAccounts: ( ...a: unknown[] ) => adAccounts( ...a ),
    pages: ( ...a: unknown[] ) => pages( ...a ),
    ads: ( ...a: unknown[] ) => ads( ...a ),
    publish: ( ...a: unknown[] ) => publish( ...a ),
    pause: vi.fn(),
    fullCreate: vi.fn(),
    uploadImage: vi.fn(),
    status: vi.fn(),
  },
} ) );

const seoToolsFetch = vi.fn();
vi.mock( '../api/seo', async importOriginal => ( {
  ...await importOriginal<typeof import( '../api/seo' )>(),
  seoToolsFetch: ( ...a: unknown[] ) => seoToolsFetch( ...a ),
} ) );

import { ConfirmProvider, usePromptDialog, useConfirm } from '../contexts/ConfirmContext';
import TemplateSender from '../components/TemplateSender';
import SecureFilesPage from '../pages/workspace/dashboard/secure-files';
import CtwaAdsPage from '../pages/workspace/engage/whatsapp/ctwa-ads';
import BlogSeoManager from '../pages/workspace/seo/blog-manager';

type PromptOptions = Parameters<ReturnType<typeof usePromptDialog>>[ 0 ];

/** Opens a prompt and renders whatever it resolved to, so the resolution is observable. */
const PromptHarness: React.FC<{ options: PromptOptions }> = ( { options } ) => {
  const prompt = usePromptDialog();
  const [ result, setResult ] = useState( '(pending)' );
  return (
    <>
      <button onClick={ async () => {
        const value = await prompt( options );
        setResult( value === null ? '(null)' : `[${ value }]` );
      } }>
        Open the prompt
      </button>
      <div data-testid="result">{ result }</div>
    </>
  );
};

const ConfirmHarness: React.FC<{ options: Parameters<ReturnType<typeof useConfirm>>[ 0 ] }> = ( { options } ) => {
  const confirm = useConfirm();
  const [ result, setResult ] = useState( '(pending)' );
  return (
    <>
      <button onClick={ async () => setResult( String( await confirm( options ) ) ) }>Open the confirm</button>
      <div data-testid="result">{ result }</div>
    </>
  );
};

const openPrompt = ( options: PromptOptions ) => {
  render( <ConfirmProvider><PromptHarness options={ options } /></ConfirmProvider> );
  const opener = screen.getByRole( 'button', { name: 'Open the prompt' } );
  // fireEvent.click does not move focus in jsdom, and the provider captures
  // document.activeElement, so the opener is focused explicitly first.
  opener.focus();
  fireEvent.click( opener );
  return opener;
};

const result = () => screen.getByTestId( 'result' ).textContent;

beforeEach( () => {
  // A native dialog in jsdom returns undefined, so a surviving window.confirm would read as
  // "the operator cancelled" and every test below would pass for the wrong reason.
  vi.spyOn( window, 'confirm' ).mockImplementation( () => { throw new Error( 'native window.confirm was called' ); } );
  vi.spyOn( window, 'prompt' ).mockImplementation( () => { throw new Error( 'native window.prompt was called' ); } );
  vi.spyOn( window, 'alert' ).mockImplementation( () => { throw new Error( 'native window.alert was called' ); } );
} );

afterEach( () => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); } );

describe( 'usePromptDialog', () => {
  it( 'resolves the trimmed string on confirm', async () => {
    openPrompt( { label: 'Why is this being withdrawn?' } );
    const field = await screen.findByLabelText( 'Why is this being withdrawn?' );
    fireEvent.change( field, { target: { value: '   it duplicated an existing post   ' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Confirm' } ) );
    await waitFor( () => expect( result() ).toBe( '[it duplicated an existing post]' ) );
  } );

  it( 'resolves null on cancel, on Escape and on a backdrop click', async () => {
    openPrompt( { label: 'Reason' } );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Cancel' } ) );
    await waitFor( () => expect( result() ).toBe( '(null)' ) );
    cleanup();

    openPrompt( { label: 'Reason' } );
    fireEvent.keyDown( await screen.findByRole( 'dialog' ), { key: 'Escape' } );
    await waitFor( () => expect( result() ).toBe( '(null)' ) );
    cleanup();

    openPrompt( { label: 'Reason' } );
    fireEvent.click( await screen.findByRole( 'dialog' ) );
    await waitFor( () => expect( result() ).toBe( '(null)' ) );
  } );

  it( 'disables confirm on an empty value when required, with no minLength in play', async () => {
    openPrompt( { label: 'Reason' } );   // required defaults to true, minLength to 0
    const button = await screen.findByRole( 'button', { name: 'Confirm' } );
    expect( button ).toBeDisabled();
    fireEvent.change( screen.getByLabelText( 'Reason' ), { target: { value: '   ' } } );
    expect( button ).toBeDisabled();     // whitespace is not an answer
    fireEvent.change( screen.getByLabelText( 'Reason' ), { target: { value: 'x' } } );
    expect( button ).toBeEnabled();
  } );

  it( 'disables confirm below minLength even when required is off', async () => {
    openPrompt( { label: 'Reason', required: false, minLength: 10 } );
    const button = await screen.findByRole( 'button', { name: 'Confirm' } );
    expect( button ).toBeDisabled();
    fireEvent.change( screen.getByLabelText( 'Reason' ), { target: { value: 'too short' } } );
    expect( button ).toBeDisabled();
    fireEvent.change( screen.getByLabelText( 'Reason' ), { target: { value: 'long enough now' } } );
    expect( button ).toBeEnabled();
  } );

  it( 'defaults the helper to the minLength hint and points the field at it', async () => {
    openPrompt( { label: 'Reason', minLength: 10 } );
    const field = await screen.findByLabelText( 'Reason' );
    const helperId = field.getAttribute( 'aria-describedby' );
    expect( helperId ).toBeTruthy();
    expect( document.getElementById( helperId as string )?.textContent ).toBe( 'At least 10 characters' );
  } );

  it( 'inserts a newline rather than submitting when Enter is pressed in a textarea', async () => {
    openPrompt( { label: 'Reason', minLength: 10, multiline: true } );
    const field = await screen.findByLabelText( 'Reason' );
    expect( field.tagName ).toBe( 'TEXTAREA' );
    fireEvent.change( field, { target: { value: 'a long enough reason' } } );
    expect( screen.getByRole( 'button', { name: 'Confirm' } ) ).toBeEnabled();

    // The handler must decline to act AND must not cancel the event, which is what leaves
    // the browser free to insert the newline. jsdom does not perform that default itself,
    // so both halves are asserted rather than the resulting text.
    const enter = new KeyboardEvent( 'keydown', { key: 'Enter', bubbles: true, cancelable: true } );
    field.dispatchEvent( enter );
    expect( enter.defaultPrevented ).toBe( false );
    expect( screen.getByRole( 'dialog' ) ).toBeTruthy();
    expect( result() ).toBe( '(pending)' );

    // Shift+Enter is ignored for the same reason, on a single-line field too.
    fireEvent.keyDown( field, { key: 'Enter', shiftKey: true } );
    expect( result() ).toBe( '(pending)' );
  } );

  it( 'keeps Enter-to-confirm on a single-line prompt, which is what window.prompt did', async () => {
    openPrompt( { label: 'Reason' } );
    const field = await screen.findByLabelText( 'Reason' );
    expect( field.tagName ).toBe( 'INPUT' );
    fireEvent.change( field, { target: { value: 'a reason' } } );
    fireEvent.keyDown( field, { key: 'Enter' } );
    await waitFor( () => expect( result() ).toBe( '[a reason]' ) );
  } );

  it( 'returns focus to the element that opened it', async () => {
    const opener = openPrompt( { label: 'Reason' } );
    const field = await screen.findByLabelText( 'Reason' );
    expect( document.activeElement ).toBe( field );   // autoFocus lands on the field
    fireEvent.click( screen.getByRole( 'button', { name: 'Cancel' } ) );
    await waitFor( () => expect( document.activeElement ).toBe( opener ) );
  } );

  it( 'sets aria-describedby only when there is a message to describe', async () => {
    openPrompt( { label: 'Reason' } );
    expect( ( await screen.findByRole( 'dialog' ) ).hasAttribute( 'aria-describedby' ) ).toBe( false );
    expect( document.getElementById( 'confirm-msg' ) ).toBeNull();
    cleanup();

    openPrompt( { label: 'Reason', message: 'Some context.' } );
    const dialog = await screen.findByRole( 'dialog' );
    expect( dialog.getAttribute( 'aria-describedby' ) ).toBe( 'confirm-msg' );
    expect( document.getElementById( 'confirm-msg' )?.textContent ).toBe( 'Some context.' );
  } );

  it( 'applies initialValue and the 500-character default cap', async () => {
    openPrompt( { label: 'Reason', initialValue: 'prefilled' } );
    const field = await screen.findByLabelText( 'Reason' ) as HTMLInputElement;
    expect( field.value ).toBe( 'prefilled' );
    expect( field.getAttribute( 'maxlength' ) ).toBe( '500' );
  } );
} );

describe( 'useConfirm is unchanged by the widened context value', () => {
  it( 'still resolves a boolean and still honours type-to-confirm', async () => {
    render( <ConfirmProvider><ConfirmHarness options={ { message: 'Gone forever', confirmInput: 'DELETE', confirmText: 'Delete', danger: true } } /></ConfirmProvider> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open the confirm' } ) );
    const button = await screen.findByRole( 'button', { name: 'Delete' } );
    expect( button ).toBeDisabled();
    fireEvent.change( screen.getByPlaceholderText( 'DELETE' ), { target: { value: 'DELETE' } } );
    expect( button ).toBeEnabled();
    fireEvent.click( button );
    await waitFor( () => expect( result() ).toBe( 'true' ) );
  } );

  it( 'resolves false on cancel', async () => {
    render( <ConfirmProvider><ConfirmHarness options={ { message: 'Proceed?' } } /></ConfirmProvider> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open the confirm' } ) );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Cancel' } ) );
    await waitFor( () => expect( result() ).toBe( 'false' ) );
  } );
} );

describe( 'the four migrated confirm sites render a dialog instead of calling a global', () => {
  it( 'TemplateSender asks before permanently deleting a library file', async () => {
    listTemplates.mockResolvedValue( [ {
      id: 't1', name: 'promo_image', language: 'en', status: 'APPROVED', category: 'MARKETING',
      components: [ { type: 'HEADER', format: 'IMAGE' }, { type: 'BODY', text: 'Hello {{1}}' } ],
    } ] );
    listSendMedia.mockResolvedValue( [ { s3Key: 'k1', mediaUrl: 'https://example.test/a.png', filename: 'poster.png', sizeBytes: 1024 } ] );

    render(
      <ConfirmProvider>
        <TemplateSender
          contactName="Asha" phoneNumberId="any"
          onClose={ vi.fn() } onSent={ vi.fn() } onError={ vi.fn() }
        />
      </ConfirmProvider>,
    );

    fireEvent.click( await screen.findByText( 'promo_image' ) );
    fireEvent.click( await screen.findByRole( 'button', { name: '📁 Choose from library' } ) );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Permanently delete poster.png' } ) );

    const dialog = await screen.findByRole( 'dialog' );
    expect( dialog.textContent ).toContain( 'Permanently delete "poster.png"?' );
    expect( dialog.textContent ).toContain( 'This removes the file from storage for everyone.' );
    expect( dialog.textContent ).toContain( 'This cannot be undone.' );
    expect( within( dialog ).getByRole( 'button', { name: 'Delete' } ) ).toBeTruthy();

    // Cancelling must leave the file alone.
    fireEvent.click( within( dialog ).getByRole( 'button', { name: 'Cancel' } ) );
    await waitFor( () => expect( screen.queryByRole( 'dialog' ) ).toBeNull() );
    expect( deleteSendMedia ).not.toHaveBeenCalled();
  } );

  it( 'secure-files asks before revoking, and revokes once confirmed', async () => {
    listSecureFiles.mockResolvedValue( {
      ok: true,
      data: {
        count: 1,
        files: [ {
          fileId: 'f1', displayName: 'Invoice.pdf', originalFilename: 'invoice.pdf',
          contentType: 'application/pdf', sizeBytes: 2048, pricePaise: 100, status: 'active',
          createdAt: '2026-01-01T00:00:00Z', downloadCount: 0, ownerPhoneMasked: '0044',
        } ],
      },
    } );
    revokeSecureFile.mockResolvedValue( { ok: true, data: { fileId: 'f1', status: 'revoked' } } );

    render( <ConfirmProvider><SecureFilesPage /></ConfirmProvider> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Revoke' } ) );

    const dialog = await screen.findByRole( 'dialog' );
    expect( dialog.textContent ).toContain( 'Revoke "Invoice.pdf"?' );
    expect( dialog.textContent ).toContain( 'The customer will no longer be able to download it.' );
    expect( dialog.textContent ).toContain( 'The record is kept so the history of who was charged survives.' );

    fireEvent.click( within( dialog ).getByRole( 'button', { name: 'Revoke' } ) );
    await waitFor( () => expect( revokeSecureFile ).toHaveBeenCalledWith( 'f1' ) );
  } );

  it( 'ctwa-ads requires the operator to TYPE PUBLISH before any ad spend starts', async () => {
    // DELIBERATE, OWNER-APPROVED BEHAVIOUR CHANGE, and the only one in this batch. Publishing
    // commits ad spend, so the typed verb is the point rather than an accident of reusing
    // useConfirmDanger. If this assertion is ever "simplified" to a plain confirm, read
    // design.md section 3.3 first.
    adAccounts.mockResolvedValue( { adAccounts: { data: [ { account_id: 'act1', name: 'Main' } ] } } );
    pages.mockResolvedValue( { pages: { data: [] } } );
    ads.mockResolvedValue( { ads: { data: [ { id: 'ad1', name: 'Diwali', status: 'PAUSED', effective_status: 'PAUSED' } ] } } );
    publish.mockResolvedValue( { status: 'ACTIVE' } );

    render( <ConfirmProvider><CtwaAdsPage /></ConfirmProvider> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Publish' } ) );

    const dialog = await screen.findByRole( 'dialog' );
    expect( dialog.textContent ).toContain( 'Publish this ad?' );
    expect( dialog.textContent ).toContain( 'It goes to Meta review and, once approved, will start spending your daily budget.' );
    expect( dialog.textContent ).toContain( 'Type "PUBLISH" to confirm' );

    const commit = screen.getAllByRole( 'button', { name: 'PUBLISH' } )[ 0 ];
    expect( commit ).toBeDisabled();
    expect( publish ).not.toHaveBeenCalled();

    fireEvent.change( screen.getByPlaceholderText( 'PUBLISH' ), { target: { value: 'PUBLISH' } } );
    expect( commit ).toBeEnabled();
    fireEvent.click( commit );
    await waitFor( () => expect( publish ).toHaveBeenCalledWith( 'ad1' ) );
  } );

  it( 'blog-manager keeps the verbatim leading clause as the title and types CLEAN', async () => {
    seoToolsFetch.mockImplementation( ( path: string ) => Promise.resolve( {
      json: async () => ( path === 'blog-posts'
        ? { ok: true, total: 2, posts: [ { id: '1', slug: 'a', title: 'A' }, { id: '2', slug: 'b', title: 'B' } ] }
        : { ok: true, audits: [], logs: [] } ),
    } ) );

    render( <ConfirmProvider><BlogSeoManager /></ConfirmProvider> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Clean All 2 Posts' } ) );

    const dialog = await screen.findByRole( 'dialog' );
    // The title is the native string's leading clause, ALL capitalised as the author wrote it
    // and the count preserved. "Clean all posts" is the BUTTON label, not the title.
    expect( dialog.textContent ).toContain( 'Clean ALL 2 posts?' );
    expect( dialog.textContent ).toContain( 'This wipes all existing SEO data.' );
    expect( dialog.textContent ).toContain( 'Type "CLEAN" to confirm' );
    expect( screen.getByRole( 'button', { name: 'Clean all posts' } ) ).toBeDisabled();
  } );
} );
