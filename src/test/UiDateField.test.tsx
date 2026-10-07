/**
 * src/components/ui/DateField.tsx, TimeField.tsx and DateTimeField.tsx - THE STRING CONTRACT.
 *
 * WHAT THIS FILE IS FOR, SAID FIRST. Every one of these components replaced a native input
 * whose `.value` the call site read, stored and posted. The single property that makes the 14
 * migrated date/time call sites safe is that the replacement emits and accepts the SAME STRING:
 * `YYYY-MM-DD`, `HH:MM`, `YYYY-MM-DDTHH:MM`. If that holds, no state shape, no payload and no
 * validation helper changed, and a revert is a two-line edit per site. Everything below either
 * proves that or proves one of the rules the native control could not enforce.
 *
 * jsdom HAS NO LAYOUT, AND THAT MATTERS HERE MORE THAN ANYWHERE ELSE IN THE TASK. It computes
 * no geometry and loads no stylesheet, so NOTHING in this file observes Popover's flip, its 8px
 * viewport clamp, or whether the calendar is clipped by a scroll container. Those are the three
 * properties a portalled panel exists to get right and the three this instrument cannot see.
 * They are verified ONCE, by hand in Chromium, in the second commit of this batch, on
 * /shop/merchandise/ - the only public surface in the task where a migrated Popover renders.
 * Read that as the coverage boundary, not as a gap this file could have closed.
 *
 * NO BROWSER EVIDENCE EXISTS FOR ANY SURFACE THIS BATCH MIGRATED, either. All 14 date/time
 * sites and all 3 colour sites are workspace pages or components rendered only on one, and
 * AuthShell is dynamic(..., { ssr: false }), so every src/pages/workspace/** route ships an
 * empty #__next in the static export. The appearance evidence for them is the owner's pass in
 * a signed-in Chrome.
 */
import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import DateField, {
  type DateFieldProps, displayToIso, isoToDisplay, isRealDate,
} from '../components/ui/DateField';
import TimeField, { splitTime } from '../components/ui/TimeField';
import DateTimeField, { splitLocal } from '../components/ui/DateTimeField';

/**
 * COMPILE-TIME HALF OF THE LABELLING CONTRACT, the same shape UiSelect.test.tsx uses and for
 * the same reason: `npx tsc --noEmit` reads this file, so it fails the day the union is
 * loosened enough to admit an unlabelled control.
 */
const BASE = { value: '', onChange: () => undefined };
// @ts-expect-error - at least one of label / ariaLabel / labelledBy is required
const UNLABELLED_IS_REJECTED: DateFieldProps = BASE;
const DUAL_LABELLED_IS_ACCEPTED: DateFieldProps = { ...BASE, label: 'When', ariaLabel: 'When, row 3' };
void UNLABELLED_IS_REJECTED;
void DUAL_LABELLED_IS_ACCEPTED;

/** March 2026 throughout, so the rendered month is deterministic and today is irrelevant. */
const MARCH = '2026-03-15';

interface HarnessProps {
  initial?: string;
  min?: string;
  max?: string;
  onChange?: ( iso: string ) => void;
  name?: string;
}

/**
 * A CONTROLLED harness. A test that never updates `value` cannot see the no-op clause at all -
 * the second pick of the same day would look like a change - and cannot see the display
 * following the committed value either.
 */
const Harness: React.FC<HarnessProps> = ( { initial = '', min, max, onChange, name } ) => {
  const [ value, setValue ] = useState( initial );
  return (
    <DateField
      label="Date"
      value={ value }
      min={ min }
      max={ max }
      name={ name }
      onChange={ iso => { setValue( iso ); onChange?.( iso ); } }
    />
  );
};

const input = () => screen.getByRole( 'textbox', { name: 'Date' } );
const trigger = () => screen.getByRole( 'button', { name: 'Choose date' } );

describe( 'DateField - the ISO contract', () => {
  it( 'takes ISO in and shows DD/MM/YYYY, the India convention', () => {
    render( <Harness initial={ MARCH } /> );
    expect( input() ).toHaveValue( '15/03/2026' );
  } );

  it( 'emits ISO out, byte-identical to what the native value would have been', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '02/04/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).toHaveBeenCalledWith( '2026-04-02' );
    // And the display comes back from the committed value, not from what was typed.
    expect( input() ).toHaveValue( '02/04/2026' );
  } );

  it( 'commits on Enter as well as on blur, and never per keystroke', () => {
    const onChange = vi.fn();
    render( <Harness initial="" onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '0' } } );
    fireEvent.change( input(), { target: { value: '01/0' } } );
    fireEvent.change( input(), { target: { value: '01/01/2026' } } );
    // Nothing yet: a partial date is not a value, and emitting one would hand the caller a
    // string it would have to validate again.
    expect( onChange ).not.toHaveBeenCalled();
    fireEvent.keyDown( input(), { key: 'Enter' } );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '2026-01-01' );
  } );

  it( 'clearing the field emits the empty string, as clearing a native date input does', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '' } } );
    fireEvent.blur( input() );
    expect( onChange ).toHaveBeenCalledWith( '' );
  } );

  it( 'REJECTS 31/02/2026 rather than rolling it into March', () => {
    // The single reason parsing is a regex plus a real-calendar check and not new Date( s ):
    // new Date( 2026, 1, 31 ) is 3 March, silently, and a slot booked on a day that does not
    // exist is the failure mode that cannot be spotted downstream.
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '31/02/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).not.toHaveBeenCalled();
    // The display reverts to the last valid value; `value` was never touched.
    expect( input() ).toHaveValue( '15/03/2026' );
  } );

  it( 'rejects unparseable input and a two-digit year, reverting the display', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    for ( const typed of [ 'tomorrow', '2026-03-20', '15/3/26', '15-03-2026' ] ) {
      fireEvent.change( input(), { target: { value: typed } } );
      fireEvent.blur( input() );
    }
    expect( onChange ).not.toHaveBeenCalled();
    expect( input() ).toHaveValue( '15/03/2026' );
  } );

  it( 'does not emit when the committed date equals the current one', () => {
    // A native change event does not fire on a no-op either, and a call site that saves on
    // every change would otherwise write on a re-pick.
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '15/03/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).not.toHaveBeenCalled();
  } );

  it( 'carries the ISO value in a hidden input, so a form submission still sees it', () => {
    const { container } = render( <Harness initial={ MARCH } name="slotDate" /> );
    const hidden = container.querySelector( 'input[type="hidden"][name="slotDate"]' );
    expect( hidden ).toHaveValue( '2026-03-15' );
  } );
} );

describe( 'DateField - min and max, enforced in BOTH places', () => {
  it( 'enforces min ON TYPE-IN, which a native input does not', () => {
    // This is the half the native control never had: min/max are not enforced while typing or
    // on paste, which is what src/pages/cart.tsx records about its own control. The parse
    // boundary is the only place the rule can actually hold.
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } min="2026-03-10" onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '09/03/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).not.toHaveBeenCalled();
    expect( input() ).toHaveValue( '15/03/2026' );
  } );

  it( 'enforces max ON TYPE-IN', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } max="2026-03-20" onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '21/03/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).not.toHaveBeenCalled();
  } );

  it( 'accepts the boundary itself - min and max are inclusive, as they are natively', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } min="2026-03-10" max="2026-03-20" onChange={ onChange } /> );
    fireEvent.change( input(), { target: { value: '10/03/2026' } } );
    fireEvent.blur( input() );
    expect( onChange ).toHaveBeenCalledWith( '2026-03-10' );
  } );

  it( 'enforces min and max IN THE GRID', () => {
    render( <Harness initial={ MARCH } min="2026-03-10" max="2026-03-20" /> );
    fireEvent.click( trigger() );
    expect( screen.getByRole( 'dialog', { name: 'Choose date' } ) ).toBeInTheDocument();

    // Inside the range: selectable.
    expect( screen.getByRole( 'button', { name: '10' } ) ).not.toBeDisabled();
    expect( screen.getByRole( 'button', { name: '20' } ) ).not.toBeDisabled();
    // Outside it, both ends: disabled AND aria-disabled, so the state is conveyed to a screen
    // reader as well as to the pointer.
    for ( const day of [ '9', '1', '21', '31' ] ) {
      const cell = screen.getByRole( 'button', { name: day } );
      expect( cell, `${day} March must be out of range` ).toBeDisabled();
      expect( cell ).toHaveAttribute( 'aria-disabled', 'true' );
    }
  } );
} );

describe( 'DateField - the calendar', () => {
  it( 'opens on the selected month and marks the selected day', () => {
    render( <Harness initial={ MARCH } /> );
    fireEvent.click( trigger() );
    expect( screen.getByText( 'March 2026' ) ).toBeInTheDocument();

    // aria-selected is on the GRIDCELL and not on the day button: role="button" does not
    // support aria-selected, role="gridcell" does, and that is where the APG datepicker
    // pattern puts it. design 5.3 wrote it on the button; this is the one place this
    // implementation deviates from that line, and it deviates toward the spec.
    const day = screen.getByRole( 'button', { name: '15' } );
    expect( day ).not.toHaveAttribute( 'aria-selected' );
    expect( day ).toHaveAttribute( 'data-selected', 'true' );
    expect( day.closest( '[role="gridcell"]' ) ).toHaveAttribute( 'aria-selected', 'true' );
    // And exactly one cell claims it.
    expect(
      screen.getAllByRole( 'gridcell' ).filter( c => c.getAttribute( 'aria-selected' ) === 'true' )
    ).toHaveLength( 1 );
  } );

  it( 'commits the clicked day as ISO and closes', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'button', { name: '21' } ) );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '2026-03-21' );
    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
  } );

  it( 'moves by a day with the arrows and commits with Enter', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.click( trigger() );
    const grid = screen.getByRole( 'grid' );
    fireEvent.keyDown( grid, { key: 'ArrowRight' } );
    fireEvent.keyDown( grid, { key: 'ArrowDown' } );   // +1 then +7 = 23 March
    fireEvent.keyDown( grid, { key: 'Enter' } );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '2026-03-23' );
  } );

  it( 'pages a month with PageDown and a year with Shift+PageDown', () => {
    render( <Harness initial={ MARCH } /> );
    fireEvent.click( trigger() );
    const grid = screen.getByRole( 'grid' );
    fireEvent.keyDown( grid, { key: 'PageDown' } );
    expect( screen.getByText( 'April 2026' ) ).toBeInTheDocument();
    fireEvent.keyDown( grid, { key: 'PageDown', shiftKey: true } );
    expect( screen.getByText( 'April 2027' ) ).toBeInTheDocument();
  } );

  it( 'the arrow keys cannot walk past min', () => {
    // The roving focus is CLAMPED rather than allowed to land on a disabled day, because a
    // disabled button cannot take focus and the operator would be stranded on <body>.
    const onChange = vi.fn();
    render( <Harness initial="2026-03-11" min="2026-03-10" onChange={ onChange } /> );
    fireEvent.click( trigger() );
    const grid = screen.getByRole( 'grid' );
    for ( let i = 0; i < 5; i += 1 ) fireEvent.keyDown( grid, { key: 'ArrowLeft' } );
    fireEvent.keyDown( grid, { key: 'Enter' } );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '2026-03-10' );
  } );

  it( 'Esc closes and RESTORES FOCUS TO THE TRIGGER', () => {
    // DOM focus is inside the portalled panel while the calendar is open, and the panel is a
    // child of <body>. Without the restore, Esc drops the operator on <body> with no way back
    // to the control by keyboard.
    render( <Harness initial={ MARCH } /> );
    fireEvent.click( trigger() );
    expect( screen.getByRole( 'dialog' ) ).toBeInTheDocument();
    fireEvent.keyDown( screen.getByRole( 'grid' ), { key: 'Escape' } );
    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
    expect( document.activeElement ).toBe( trigger() );
  } );

  it( 'Esc discards: the value is untouched by opening and closing', () => {
    const onChange = vi.fn();
    render( <Harness initial={ MARCH } onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.keyDown( screen.getByRole( 'grid' ), { key: 'ArrowRight' } );
    fireEvent.keyDown( screen.getByRole( 'grid' ), { key: 'Escape' } );
    expect( onChange ).not.toHaveBeenCalled();
    expect( input() ).toHaveValue( '15/03/2026' );
  } );

  it( 'navigates months with the two header buttons', () => {
    render( <Harness initial={ MARCH } /> );
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'button', { name: 'Previous month' } ) );
    expect( screen.getByText( 'February 2026' ) ).toBeInTheDocument();
    fireEvent.click( screen.getByRole( 'button', { name: 'Next month' } ) );
    expect( screen.getByText( 'March 2026' ) ).toBeInTheDocument();
  } );
} );

describe( 'the date helpers, exercised directly where the edge is arithmetic', () => {
  it( 'isRealDate rejects the impossible and accepts the leap day', () => {
    expect( isRealDate( 2026, 2, 31 ) ).toBe( false );
    expect( isRealDate( 2026, 2, 29 ) ).toBe( false );   // 2026 is not a leap year
    expect( isRealDate( 2028, 2, 29 ) ).toBe( true );    // 2028 is
    expect( isRealDate( 2026, 13, 1 ) ).toBe( false );
    expect( isRealDate( 2026, 0, 1 ) ).toBe( false );
  } );

  it( 'the display round-trip is lossless in both directions', () => {
    expect( isoToDisplay( '2026-03-05' ) ).toBe( '05/03/2026' );
    expect( displayToIso( '05/03/2026' ) ).toBe( '2026-03-05' );
    // A single-digit day or month typed without padding is accepted and PADDED on the way out,
    // so what the caller receives is always fixed-width.
    expect( displayToIso( '5/3/2026' ) ).toBe( '2026-03-05' );
    expect( isoToDisplay( '' ) ).toBe( '' );
    expect( isoToDisplay( 'nonsense' ) ).toBe( '' );
    expect( displayToIso( '31/02/2026' ) ).toBeNull();
  } );
} );

describe( 'TimeField - HH:MM in, HH:MM out', () => {
  const TimeHarness: React.FC<{ initial?: string; onChange?: ( t: string ) => void; step?: number }> = (
    { initial = '', onChange, step }
  ) => {
    const [ value, setValue ] = useState( initial );
    return (
      <TimeField
        label="Time"
        value={ value }
        step={ step }
        onChange={ t => { setValue( t ); onChange?.( t ); } }
      />
    );
  };

  it( 'splits and shows the two parts', () => {
    render( <TimeHarness initial="09:30" /> );
    expect( screen.getByRole( 'combobox', { name: 'Hours' } ) ).toHaveTextContent( '09' );
    expect( screen.getByRole( 'combobox', { name: 'Minutes' } ) ).toHaveTextContent( '30' );
  } );

  it( 'emits HH:MM once both halves are chosen, and NOTHING before that', () => {
    // Incomplete means empty, as the native control behaves: a time with no minute must not be
    // silently committed as the top of the hour on a scheduled send.
    const onChange = vi.fn();
    render( <TimeHarness initial="" onChange={ onChange } /> );
    fireEvent.click( screen.getByRole( 'combobox', { name: 'Hours' } ) );
    fireEvent.click( screen.getByRole( 'option', { name: '14' } ) );
    expect( onChange ).not.toHaveBeenCalled();
    fireEvent.click( screen.getByRole( 'combobox', { name: 'Minutes' } ) );
    fireEvent.click( screen.getByRole( 'option', { name: '45' } ) );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '14:45' );
  } );

  it( 'KEEPS a stored minute the step cannot generate, rather than showing an empty field', () => {
    // The 5-minute step cannot EXPRESS 09:07 - that tradeoff is accepted and documented - but
    // losing a value already in state is a different failure and is not accepted. 07 is
    // injected into the options in sorted position.
    render( <TimeHarness initial="09:07" /> );
    expect( screen.getByRole( 'combobox', { name: 'Minutes' } ) ).toHaveTextContent( '07' );
    fireEvent.click( screen.getByRole( 'combobox', { name: 'Minutes' } ) );
    const minutes = screen.getAllByRole( 'option' ).map( o => o.textContent );
    expect( minutes ).toContain( '07' );
    expect( minutes.indexOf( '07' ) ).toBe( minutes.indexOf( '05' ) + 1 );
  } );

  it( 'step: 1 offers every minute', () => {
    render( <TimeHarness initial="09:00" step={ 1 } /> );
    fireEvent.click( screen.getByRole( 'combobox', { name: 'Minutes' } ) );
    expect( screen.getAllByRole( 'option' ) ).toHaveLength( 60 );
  } );

  it( 'splitTime refuses an out-of-range or malformed string rather than half-reading it', () => {
    expect( splitTime( '09:30' ) ).toEqual( { hour: '09', minute: '30' } );
    expect( splitTime( '24:00' ) ).toEqual( { hour: '', minute: '' } );
    expect( splitTime( '09:60' ) ).toEqual( { hour: '', minute: '' } );
    expect( splitTime( '9:30' ) ).toEqual( { hour: '', minute: '' } );
    expect( splitTime( '' ) ).toEqual( { hour: '', minute: '' } );
  } );
} );

describe( 'DateTimeField - YYYY-MM-DDTHH:MM in and out', () => {
  const DtHarness: React.FC<{ initial?: string; onChange?: ( v: string ) => void }> = (
    { initial = '', onChange }
  ) => {
    const [ value, setValue ] = useState( initial );
    return (
      <DateTimeField
        label="When"
        value={ value }
        onChange={ v => { setValue( v ); onChange?.( v ); } }
      />
    );
  };

  it( 'splits the native string into its two halves', () => {
    expect( splitLocal( '2026-03-15T09:30' ) ).toEqual( { date: '2026-03-15', time: '09:30' } );
    // `datetime-local` renders seconds only when `step` asks for them, and neither live call
    // site does - but a stored value that carries them must still read correctly.
    expect( splitLocal( '2026-03-15T09:30:00' ) ).toEqual( { date: '2026-03-15', time: '09:30' } );
    expect( splitLocal( '' ) ).toEqual( { date: '', time: '' } );
  } );

  it( 'shows both halves and recomposes the exact native string', () => {
    const onChange = vi.fn();
    render( <DtHarness initial="2026-03-15T09:30" onChange={ onChange } /> );
    expect( screen.getByRole( 'textbox', { name: 'Date' } ) ).toHaveValue( '15/03/2026' );
    expect( screen.getByRole( 'combobox', { name: 'Hours' } ) ).toHaveTextContent( '09' );

    fireEvent.change( screen.getByRole( 'textbox', { name: 'Date' } ), { target: { value: '16/03/2026' } } );
    fireEvent.blur( screen.getByRole( 'textbox', { name: 'Date' } ) );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '2026-03-16T09:30' );
  } );

  it( 'emits the empty string while either half is unset', () => {
    const onChange = vi.fn();
    render( <DtHarness initial="" onChange={ onChange } /> );
    fireEvent.change( screen.getByRole( 'textbox', { name: 'Date' } ), { target: { value: '16/03/2026' } } );
    fireEvent.blur( screen.getByRole( 'textbox', { name: 'Date' } ) );
    // The date landed but the time has not, so the composed value is still '' - and because the
    // caller's value was ALREADY '', no onChange fires at all. The half-filled state lives in
    // the component until it can emit something the caller can use.
    expect( onChange ).not.toHaveBeenCalled();
    expect( screen.getByRole( 'textbox', { name: 'Date' } ) ).toHaveValue( '16/03/2026' );
  } );
} );
