/**
 * The Service Operations shared primitives — the ones the capability pages fold into.
 *
 * These guard the two defects the Phase 1 audit named: ~9 divergent status badges, and the
 * empty-on-API-error anti-pattern where a failed load reads as "0 results". The badge tests pin
 * the money/status vocabulary; the ServiceDataState tests pin that an error ALWAYS beats empty.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// EmptyState pulls in Button; nothing here needs the client, so no api mock is required.
import StatusBadge, { PaymentBadge } from '../components/service/StatusBadge';
import ServiceDataState from '../components/service/ServiceDataState';
import { maskPhone, phoneLast4 } from '../components/service/mask';
import type { ApiFailure } from '../api/client';

describe( 'maskPhone', () => {
  it( 'shows only the last four digits', () => {
    expect( maskPhone( '919330994400' ) ).toBe( '•••• 4400' );
    expect( maskPhone( '+91 93309 94400' ) ).toBe( '•••• 4400' );
  } );
  it( 'degrades on empty or short input rather than throwing', () => {
    expect( maskPhone( '' ) ).toBe( '—' );
    expect( maskPhone( undefined ) ).toBe( '—' );
    expect( maskPhone( '12' ) ).toBe( '12' );
    expect( phoneLast4( '919330994400' ) ).toBe( '4400' );
  } );
} );

describe( 'StatusBadge vocabulary', () => {
  it( 'maps known request statuses to a human label', () => {
    render( <StatusBadge value="in_progress" /> );
    expect( screen.getByText( 'In progress' ) ).toBeTruthy();
  } );
  it( 'maps the payment ladder, including display-only states', () => {
    const { rerender } = render( <PaymentBadge value="captured" /> );
    expect( screen.getByText( 'Captured' ) ).toBeTruthy();
    rerender( <PaymentBadge value="reconciliation_required" /> );
    expect( screen.getByText( 'Reconcile' ) ).toBeTruthy();
    rerender( <PaymentBadge value="paid_but_blocked" /> );
    expect( screen.getByText( 'Paid · blocked' ) ).toBeTruthy();
  } );
  it( 'renders an unknown status verbatim rather than blank', () => {
    render( <StatusBadge value="some_new_state" /> );
    expect( screen.getByText( 'Some New State' ) ).toBeTruthy();
  } );
} );

const failure: ApiFailure = {
  kind: 'server', status: 500, message: 'boom', url: '/x', retryable: true, at: Date.now(),
};

describe( 'ServiceDataState precedence', () => {
  it( 'shows a loading state first', () => {
    render(
      <ServiceDataState loading failure={null} empty={false}><div>rows</div></ServiceDataState>,
    );
    expect( screen.queryByText( 'rows' ) ).toBeNull();
  } );

  it( 'shows an ERROR, not an empty state, when a load failed with no rows', () => {
    render(
      <ServiceDataState loading={false} failure={failure} empty onRetry={() => {}}>
        <div>rows</div>
      </ServiceDataState>,
    );
    // The whole point: a 500 must not read as "No results".
    expect( screen.getByRole( 'alert' ) ).toBeTruthy();
    expect( screen.queryByText( 'No results' ) ).toBeNull();
  } );

  it( 'shows the empty state only when the load succeeded with zero rows', () => {
    render(
      <ServiceDataState loading={false} failure={null} empty emptyLabel="No responses yet">
        <div>rows</div>
      </ServiceDataState>,
    );
    expect( screen.getByText( 'No responses yet' ) ).toBeTruthy();
  } );

  it( 'renders children (and a partial banner) when data is present', () => {
    render(
      <ServiceDataState loading={false} failure={null} empty={false} partial>
        <div>rows</div>
      </ServiceDataState>,
    );
    expect( screen.getByText( 'rows' ) ).toBeTruthy();
    expect( screen.getByRole( 'status' ) ).toBeTruthy();
  } );
} );
