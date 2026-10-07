/**
 * THE ONLY `:indeterminate` IN THE TREE, DRIVEN THROUGH ALL THREE OF ITS STATES.
 *
 * WHAT THIS TEST IS, SAID FIRST SO IT CANNOT BE MISREAD. It is a DOM-STATE test and NOT an
 * appearance test. jsdom computes no styled-jsx and no `background-image`, so nothing here
 * observes `--control-dash`, the accent fill, or the 18px box that `form-controls.css` draws.
 * What it proves is that the three states are REACHABLE AND DISTINCT IN THE DOM — unchecked,
 * checked, and indeterminate — which is the precondition for the CSS mattering at all. The
 * appearance evidence for batch 1.3c's checkbox is the owner's pass in a signed-in Chrome, and
 * this file does not stand in for it.
 *
 * WHY A jsdom TEST AND NOT A SCREENSHOT. No harness in this repo can reach a checkbox:
 *
 *   - `/cart/` has ZERO checkboxes and zero radios, so it belongs to batch 1.3a's gate and not
 *     to this one. Putting it here would have been positive-looking coverage of nothing.
 *   - `account/sign-in.tsx`'s single checkbox sits inside the branch opened at :578, while
 *     `phase` initialises to `'phone'`, so reaching it needs a live WhatsApp OTP round trip
 *     that a harness must not do.
 *   - `DataTab` is an authenticated dashboard tab, and `AuthShell` is `dynamic(…, { ssr: false })`,
 *     so every workspace route ships an empty `#__next` in the static export.
 *
 * WHICH CHECKBOX. `DataTab` renders two kinds. `.cleanup-select-all` is an ordinary two-state
 * box. The tri-state one is the per-CATEGORY box inside `.cleanup-category-label`, whose
 * `ref={ el => { if ( el ) el.indeterminate = someCatSelected && !allCatSelected; } }` is the
 * single `:indeterminate` occurrence in the whole tree and therefore the only consumer of
 * `--control-dash`. `indeterminate` is an IDL property and never an attribute, which is exactly
 * why it has to be asserted on the element rather than found in markup.
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
 * TWO resources in ONE category, which is the smallest fixture that can produce all three
 * states: none selected is unchecked, one of two is indeterminate, both is checked. A
 * single-resource category could only ever be checked or unchecked, so the state this test
 * exists for would be unreachable and the suite would pass without ever seeing it.
 */
const RESOURCES: api.CleanupResource[] = [
  { id: 'alpha', label: 'Alpha table', category: 'Messages', type: 'dynamodb', table: 'AlphaTable', count: 2 },
  { id: 'beta', label: 'Beta table', category: 'Messages', type: 'dynamodb', table: 'BetaTable', count: 3 },
];

// DataTab reads exactly one field off `data` - `data.contacts.length` for a stat card - so the
// rest of DashboardData is irrelevant here and is not invented.
const DATA = { contacts: [] } as unknown as DashboardData;

const renderTab = () => render(
  <ToastProvider>
    <ConfirmProvider>
      <DataTab data={ DATA } onRefresh={ () => {} } />
    </ConfirmProvider>
  </ToastProvider>
);

/** The per-category tri-state box, found by its label wrapper rather than by index. */
const categoryBox = (): HTMLInputElement => {
  const label = document.querySelector( '.cleanup-category-label' );
  if ( !label ) throw new Error( 'the .cleanup-category-label wrapper did not render' );
  const el = label.querySelector( 'input[type="checkbox"]' );
  if ( !el ) throw new Error( 'the category checkbox did not render' );
  return el as HTMLInputElement;
};

const itemBox = ( label: string ): HTMLInputElement => {
  const row = [ ...document.querySelectorAll( '.cleanup-item' ) ]
    .find( r => r.textContent?.includes( label ) );
  if ( !row ) throw new Error( `the ${label} row did not render` );
  return row.querySelector( 'input[type="checkbox"]' ) as HTMLInputElement;
};

describe( 'DataTab - the tri-state category checkbox', () => {
  beforeEach( () => {
    vi.restoreAllMocks();
    vi.spyOn( api, 'getCleanupPreview' ).mockResolvedValue( RESOURCES );
  } );

  it( 'drives unchecked, indeterminate and checked, and the three are distinct', async () => {
    renderTab();
    // The preview loads on mount, so wait for the category to exist before touching it.
    await waitFor( () => expect( document.querySelector( '.cleanup-category-label' ) ).not.toBeNull() );

    // 1. UNCHECKED. Nothing selected: not checked, and NOT indeterminate - the distinction that
    //    matters, because an indeterminate box with nothing selected would paint a dash where a
    //    user has made no choice at all.
    expect( categoryBox().checked ).toBe( false );
    expect( categoryBox().indeterminate ).toBe( false );

    // 2. INDETERMINATE. One of the two items selected. This is the state no harness here can
    //    see and the only consumer of --control-dash in the tree.
    fireEvent.click( itemBox( 'Alpha table' ) );
    await waitFor( () => expect( categoryBox().indeterminate ).toBe( true ) );
    // Still NOT checked: the ref sets `indeterminate` while `checked` stays bound to
    // allCatSelected, so the two properties disagree on purpose. A box that reported both would
    // be drawn with the tick, not the dash, because :checked and :indeterminate are separate
    // rules in form-controls.css and :checked wins on source order.
    expect( categoryBox().checked ).toBe( false );

    // 3. CHECKED. Both items selected: checked, and indeterminate is withdrawn.
    fireEvent.click( itemBox( 'Beta table' ) );
    await waitFor( () => expect( categoryBox().checked ).toBe( true ) );
    expect( categoryBox().indeterminate ).toBe( false );

    // And back down through indeterminate, so the transition is not one-way.
    fireEvent.click( itemBox( 'Beta table' ) );
    await waitFor( () => expect( categoryBox().indeterminate ).toBe( true ) );
    expect( categoryBox().checked ).toBe( false );
  } );

  it( 'reaches the same three states from the category box itself', async () => {
    renderTab();
    await waitFor( () => expect( document.querySelector( '.cleanup-category-label' ) ).not.toBeNull() );

    // Clicking the category box selects the whole category, so it goes straight to checked
    // without passing through indeterminate - which is the correct behaviour for a select-all
    // and is asserted so a future change to toggleCleanupCategory cannot leave it half-set.
    fireEvent.click( categoryBox() );
    await waitFor( () => expect( categoryBox().checked ).toBe( true ) );
    expect( categoryBox().indeterminate ).toBe( false );

    fireEvent.click( categoryBox() );
    await waitFor( () => expect( categoryBox().checked ).toBe( false ) );
    expect( categoryBox().indeterminate ).toBe( false );
  } );

  it( 'resolves the attribute surface form-controls.css selects on', async () => {
    renderTab();
    await waitFor( () => expect( document.querySelector( '.cleanup-category-label' ) ).not.toBeNull() );
    const box = categoryBox();

    // The shared skin reaches this control, so none of the three opt-outs may be present. If a
    // later edit added data-ui-raw here it would fall out of the skin silently, and nothing
    // else in this repo would notice.
    expect( box.getAttribute( 'type' ) ).toBe( 'checkbox' );
    expect( box.hasAttribute( 'data-ui-raw' ) ).toBe( false );
    expect( box.hasAttribute( 'data-public-ui' ) ).toBe( false );
    expect( box.className ).not.toContain( 'amplify-input' );

    // `indeterminate` is an IDL property, never an attribute - which is why the assertions above
    // read it off the element. Pinned so nobody "fixes" the ref into a JSX attribute that React
    // would not forward and CSS would never see.
    expect( box.getAttribute( 'indeterminate' ) ).toBeNull();

    // Every checkbox in this panel is reached by the same selector, and the select-all box is a
    // plain two-state control rather than a second tri-state one.
    const selectAll = document.querySelector( '.cleanup-select-all input[type="checkbox"]' ) as HTMLInputElement;
    expect( selectAll ).not.toBeNull();
    expect( selectAll.indeterminate ).toBe( false );
    expect( screen.getByText( 'Select All' ) ).toBeTruthy();
  } );
} );
