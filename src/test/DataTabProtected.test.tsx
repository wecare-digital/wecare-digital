/**
 * THE DATA TAB MUST NOT OFFER A ROW THE SERVER WILL REFUSE.
 *
 * WHAT THIS IS AND IS NOT. The server is the authority: `operations/system-cleanup` refuses
 * a protected table whatever the client sends, through an allow-list, an independent keyword
 * deny list, Admin + MFA, and a single-use confirmation token bound to the exact selection.
 * None of the behaviour asserted here is the safety guard. What it IS, is the guarantee that
 * an operator is never handed a destructive choice that is going to be declined — and, more
 * sharply, that "Select All" can never reach customer, financial or message history.
 *
 * WHY THAT NEEDED A TEST. Before the fix, `system-cleanup` auto-discovered every
 * `stack-wecare-digital-*` table and the tab offered all of them, so ContactsTable,
 * InvoicesTable, PaymentsTable and AuditLogsTable were one "Select All" plus one
 * "CONFIRM DELETE" away from being emptied. The tab's own code read
 * `cleanupResources.map( r => r.id )` with no notion of a row it must skip.
 *
 * `src/test/DataTabCheckbox.test.tsx` pins the tri-state `:indeterminate` behaviour of the
 * per-category box and must keep passing UNCHANGED — its fixture carries no `protected`
 * field at all, which is exactly the backwards-compatibility case asserted below.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import * as api from '../api/client';
import DataTab from '../components/dashboard/tabs/DataTab';
import { ToastProvider } from '../contexts/ToastContext';
import { ConfirmProvider } from '../contexts/ConfirmContext';
import type { DashboardData } from '../types/dashboard';

/**
 * A mixed list, shaped like the real preview response.
 *
 * `rate_limit` is on the server's allow-list. `contacts` and `invoices` match its keyword
 * deny list. `s3_media` is an S3 prefix, which the server never clears. "Protected only" is
 * its own category on purpose: a category with no selectable row at all is the edge the
 * tri-state box has to get right.
 */
const RESOURCES: api.CleanupResource[] = [
  { id: 'rate_limit', label: 'Rate Limit Trackers', category: 'System', type: 'dynamodb', table: 'RateLimitTable', count: 12, selectable: true, protected: false, protectedReason: '' },
  { id: 'template_analytics', label: 'Template Analytics', category: 'System', type: 'dynamodb', table: 'TemplateAnalyticsTable', count: 4, selectable: true, protected: false, protectedReason: '' },
  { id: 'contacts', label: 'Contacts', category: 'Contacts', type: 'dynamodb', table: 'ContactsTable', count: 940, selectable: false, protected: true, protectedReason: 'Protected: customer, financial or message history (matched "contact")' },
  { id: 'invoices', label: 'Invoices', category: 'Contacts', type: 'dynamodb', table: 'InvoicesTable', count: 57, selectable: false, protected: true, protectedReason: 'Protected: customer, financial or message history (matched "invoice")' },
  { id: 's3_media', label: 'S3: WhatsApp Media', category: 'S3 Storage', type: 's3', prefix: 'o/stack/whatsapp-media/', count: 1200, selectable: false, protected: true, protectedReason: 'S3 is never cleared here' },
];

const SELECTABLE_IDS = [ 'rate_limit', 'template_analytics' ];
const TOKEN = 'confirm-token-abc123';

const DATA = { contacts: [] } as unknown as DashboardData;

const renderTab = () => render(
  <ToastProvider>
    <ConfirmProvider>
      <DataTab data={ DATA } onRefresh={ () => {} } />
    </ConfirmProvider>
  </ToastProvider>
);

const row = ( label: string ): HTMLElement => {
  const found = [ ...document.querySelectorAll( '.cleanup-item' ) ]
    .find( r => r.textContent?.includes( label ) );
  if ( !found ) throw new Error( `the ${label} row did not render` );
  return found as HTMLElement;
};

const boxIn = ( label: string ): HTMLInputElement =>
  row( label ).querySelector( 'input[type="checkbox"]' ) as HTMLInputElement;

const categoryBox = ( category: string ): HTMLInputElement => {
  const label = [ ...document.querySelectorAll( '.cleanup-category-label' ) ]
    .find( l => l.textContent?.includes( category ) );
  if ( !label ) throw new Error( `the ${category} category did not render` );
  return label.querySelector( 'input[type="checkbox"]' ) as HTMLInputElement;
};

const selectAllBox = (): HTMLInputElement =>
  document.querySelector( '.cleanup-select-all input[type="checkbox"]' ) as HTMLInputElement;

const loaded = () => waitFor( () =>
  expect( document.querySelector( '.cleanup-category-label' ) ).not.toBeNull() );

describe( 'DataTab - protected rows cannot be selected', () => {
  beforeEach( () => {
    vi.restoreAllMocks();
    vi.spyOn( api, 'getCleanupPreview' ).mockResolvedValue( RESOURCES );
    vi.spyOn( api, 'lastCleanupConfirmation' ).mockReturnValue(
      { token: TOKEN, selectableIds: SELECTABLE_IDS } );
  } );

  it( 'renders a protected row with a disabled checkbox and the server reason', async () => {
    renderTab();
    await loaded();

    expect( boxIn( 'Contacts' ).disabled ).toBe( true );
    expect( boxIn( 'Contacts' ).checked ).toBe( false );
    // The reason is TEXT in the row, not a colour. A colour change alone is unreadable to a
    // screen reader and to anyone who cannot distinguish the two greys.
    expect( row( 'Contacts' ).textContent ).toContain( 'matched "contact"' );
    expect( row( 'Contacts' ).getAttribute( 'aria-disabled' ) ).toBe( 'true' );

    // And a clearable row is untouched by all of this.
    expect( boxIn( 'Rate Limit Trackers' ).disabled ).toBe( false );
    expect( row( 'Rate Limit Trackers' ).getAttribute( 'aria-disabled' ) ).toBeNull();
  } );

  it( 'still shows the protected row and its live count', async () => {
    renderTab();
    await loaded();
    // Hiding them would answer "what is in this system" with a lie. The operator needs to
    // see that ContactsTable holds 940 rows AND that they are not reachable from here.
    expect( row( 'Contacts' ).textContent ).toContain( '940' );
    expect( screen.getByText( 'S3: WhatsApp Media' ) ).toBeTruthy();
  } );

  it( 'clicking a protected row changes nothing', async () => {
    renderTab();
    await loaded();
    fireEvent.click( boxIn( 'Invoices' ) );
    await waitFor( () => expect( boxIn( 'Invoices' ).checked ).toBe( false ) );
    expect( document.querySelector( '.cleanup-count' )?.textContent ).toContain( '0 of 2' );
  } );

  it( 'SELECT ALL reaches only the selectable rows', async () => {
    renderTab();
    await loaded();

    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( boxIn( 'Rate Limit Trackers' ).checked ).toBe( true ) );

    expect( boxIn( 'Template Analytics' ).checked ).toBe( true );
    expect( boxIn( 'Contacts' ).checked ).toBe( false );
    expect( boxIn( 'Invoices' ).checked ).toBe( false );
    expect( boxIn( 'S3: WhatsApp Media' ).checked ).toBe( false );

    // "2 of 2", not "5 of 5": the denominator is the selectable set, so Select All reads as
    // complete without having touched protected data.
    const count = document.querySelector( '.cleanup-count' )?.textContent || '';
    expect( count ).toContain( '2 of 2' );
    // 12 + 4, NOT 12 + 4 + 940 + 57 + 1200. The figure quoted in the confirmation dialog is
    // what would actually be deleted.
    expect( count ).toContain( '16' );
    expect( count ).not.toContain( '2,213' );
  } );

  it( 'the select-all box reads checked once every selectable row is selected', async () => {
    renderTab();
    await loaded();
    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( selectAllBox().checked ).toBe( true ) );
    // Protected rows must not hold it permanently unchecked, or Select All never settles and
    // an operator keeps clicking it.
    expect( boxIn( 'Contacts' ).checked ).toBe( false );
  } );

  it( 'a category of only protected rows is neither checked nor indeterminate', async () => {
    renderTab();
    await loaded();
    const box = categoryBox( 'S3 Storage' );
    expect( box.checked ).toBe( false );
    // `items.every(...)` over an empty selectable list returns true, so the naive version of
    // this reported CHECKED for a category nothing in it can select.
    expect( box.indeterminate ).toBe( false );
    expect( box.disabled ).toBe( true );
  } );

  it( 'the category box ignores protected rows when deciding its three states', async () => {
    renderTab();
    await loaded();

    // "Contacts" holds two rows, both protected, so its box can never leave unchecked.
    fireEvent.click( categoryBox( 'Contacts' ) );
    await waitFor( () => expect( categoryBox( 'Contacts' ).checked ).toBe( false ) );
    expect( boxIn( 'Contacts' ).checked ).toBe( false );
    expect( boxIn( 'Invoices' ).checked ).toBe( false );

    // "System" holds two selectable rows, so it still drives all three states — the
    // behaviour DataTabCheckbox.test.tsx pins, which this change must not disturb.
    fireEvent.click( boxIn( 'Rate Limit Trackers' ) );
    await waitFor( () => expect( categoryBox( 'System' ).indeterminate ).toBe( true ) );
    expect( categoryBox( 'System' ).checked ).toBe( false );
    fireEvent.click( boxIn( 'Template Analytics' ) );
    await waitFor( () => expect( categoryBox( 'System' ).checked ).toBe( true ) );
    expect( categoryBox( 'System' ).indeterminate ).toBe( false );
  } );

  it( 'treats a response with no protected fields as fully selectable', async () => {
    // An older backend sends neither `selectable` nor `protected`. Reading absent as
    // protected would render the whole tab inert against an un-upgraded deployment, and the
    // guard that matters is the server's. This is also why
    // DataTabCheckbox.test.tsx's fixture — which has no such fields — keeps working.
    vi.spyOn( api, 'getCleanupPreview' ).mockResolvedValue( [
      { id: 'alpha', label: 'Alpha table', category: 'Messages', type: 'dynamodb', table: 'AlphaTable', count: 2 },
    ] );
    renderTab();
    await loaded();
    expect( boxIn( 'Alpha table' ).disabled ).toBe( false );
    fireEvent.click( boxIn( 'Alpha table' ) );
    await waitFor( () => expect( boxIn( 'Alpha table' ).checked ).toBe( true ) );
  } );
} );

describe( 'DataTab - the confirmation token and the result list', () => {
  beforeEach( () => {
    vi.restoreAllMocks();
    vi.spyOn( api, 'getCleanupPreview' ).mockResolvedValue( RESOURCES );
    vi.spyOn( api, 'lastCleanupConfirmation' ).mockReturnValue(
      { token: TOKEN, selectableIds: SELECTABLE_IDS } );
  } );

  /** Walk the real confirm dialog: type the phrase, press the confirm button. */
  const confirmTheDialog = async () => {
    await waitFor( () => expect( document.querySelector( '[role="dialog"]' ) ).not.toBeNull() );
    const typed = document.querySelector( '[role="dialog"] input[type="text"]' ) as HTMLInputElement;
    expect( typed ).not.toBeNull();
    fireEvent.change( typed, { target: { value: 'CONFIRM DELETE' } } );
    fireEvent.click( screen.getByText( 'Permanently Delete' ) );
  };

  it( 'sends the preview token and only selectable ids', async () => {
    const execute = vi.spyOn( api, 'executeCleanup' ).mockResolvedValue( {
      results: [ { id: 'rate_limit', label: 'Rate Limit Trackers', deleted: 12 } ],
      totalDeleted: 12, protected: 0, skipped: 0,
    } );
    renderTab();
    await loaded();

    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( boxIn( 'Rate Limit Trackers' ).checked ).toBe( true ) );
    fireEvent.click( screen.getByText( /Deep Clean 2 Resources/ ) );
    await confirmTheDialog();

    await waitFor( () => expect( execute ).toHaveBeenCalled() );
    const [ sent, token ] = execute.mock.calls[ 0 ];
    expect( [ ...sent ].sort() ).toEqual( SELECTABLE_IDS );
    // Without the token the server refuses 400, so a UI that forgot to thread it would look
    // broken rather than dangerous — but it would still be broken.
    expect( token ).toBe( TOKEN );
  } );

  it( 'disables Deep Clean when the server could not mint a token', async () => {
    // The confirmation store being unreachable must fail CLOSED: the preview still renders
    // its counts and nothing can be deleted.
    vi.spyOn( api, 'lastCleanupConfirmation' ).mockReturnValue( {
      token: '', selectableIds: SELECTABLE_IDS,
      warning: 'Confirmation store unavailable — counts are live but nothing can be deleted until it recovers.',
    } );
    renderTab();
    await loaded();
    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( boxIn( 'Rate Limit Trackers' ).checked ).toBe( true ) );

    const button = screen.getByText( /Deep Clean 2 Resources/ ).closest( 'button' );
    expect( button?.disabled ).toBe( true );
    expect( screen.getByText( /Confirmation store unavailable/ ) ).toBeTruthy();
  } );

  it( 'renders a protected result as kept, visually distinct from an error', async () => {
    vi.spyOn( api, 'executeCleanup' ).mockResolvedValue( {
      results: [
        { id: 'rate_limit', label: 'Rate Limit Trackers', deleted: 12, elapsed: 0.4 },
        { id: 'contacts', label: 'Contacts', deleted: 0, protected: true, protectedReason: 'Protected: customer history' },
        { id: 'broken', label: 'Broken thing', deleted: 0, error: 'ResourceNotFound' },
      ],
      totalDeleted: 12, protected: 1, skipped: 1,
    } );
    renderTab();
    await loaded();
    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( boxIn( 'Rate Limit Trackers' ).checked ).toBe( true ) );
    fireEvent.click( screen.getByText( /Deep Clean 2 Resources/ ) );
    await confirmTheDialog();

    await waitFor( () => expect( document.querySelector( '.cleanup-results' ) ).not.toBeNull() );

    // Three outcomes, three classes. A protected row is a CORRECT result: folding it into
    // the error style is how a sweep that properly refused reads as broken, and how somebody
    // then "fixes" the refusal.
    const kept = document.querySelector( '.cleanup-result-kept' );
    expect( kept ).not.toBeNull();
    expect( kept?.textContent ).toContain( 'Kept' );
    expect( kept?.textContent ).toContain( 'Protected: customer history' );
    expect( document.querySelector( '.cleanup-result-error' )?.textContent ).toContain( 'ResourceNotFound' );
    expect( document.querySelector( '.cleanup-result-success' )?.textContent ).toContain( '12 deleted' );
  } );

  it( 'reports the SERVER counts for deleted, protected and skipped', async () => {
    vi.spyOn( api, 'executeCleanup' ).mockResolvedValue( {
      results: [ { id: 'rate_limit', label: 'Rate Limit Trackers', deleted: 12 } ],
      totalDeleted: 12, protected: 3, skipped: 4,
    } );
    renderTab();
    await loaded();
    fireEvent.click( selectAllBox() );
    await waitFor( () => expect( boxIn( 'Rate Limit Trackers' ).checked ).toBe( true ) );
    fireEvent.click( screen.getByText( /Deep Clean 2 Resources/ ) );
    await confirmTheDialog();

    await waitFor( () => expect( document.querySelector( '.cleanup-results-summary' ) ).not.toBeNull() );
    const summary = document.querySelector( '.cleanup-results-summary' )?.textContent || '';
    // `protected` and `skipped` are the two numbers a client cannot compute for itself, and
    // they are the ones that say whether the sweep deliberately left something behind.
    expect( summary ).toContain( '12 deleted' );
    expect( summary ).toContain( '3 protected and kept' );
    expect( summary ).toContain( '4 skipped' );
  } );
} );
