/**
 * src/components/ui/Select.tsx - THE CONTRACT 159 CALL SITES ARE ABOUT TO DEPEND ON.
 *
 * NO CALL SITE USES THIS COMPONENT YET, AND THAT IS WHY THIS FILE EXISTS. The component
 * lands and is proven in isolation first, so a failure in a later migration batch is a
 * failure of that call site rather than an open question about the primitive.
 *
 * WHAT THIS TEST IS, SAID FIRST SO IT CANNOT BE MISREAD. It is a DOM-state, value-semantics
 * and accessible-name test, not an appearance test. jsdom computes no layout and loads no
 * stylesheet, so nothing here observes the drawn chevron, the 44px floor, the focus ring or
 * the flip-above-when-there-is-no-room-below geometry. The appearance evidence for Layer 2 is
 * an owner pass in a signed-in Chrome; this file does not stand in for it.
 *
 * WHAT IT CAN PROVE, AND THESE ARE THE PARTS THAT BREAK SILENTLY:
 *   - the five labelling rows, through the COMPUTED accessible name;
 *   - the five value-semantics clauses, including the no-op that must NOT fire onChange;
 *   - every row of the keyboard table, because a custom listbox either implements them or
 *     quietly loses the muscle memory a native <select> gave for free.
 *
 * EVERY ACCESSIBLE-NAME ASSERTION GOES THROUGH getByRole( 'combobox', { name } ) AND NEVER
 * toHaveAttribute( 'aria-labelledby', ... ). The distinction is the whole reason the fifth
 * and sixth cases earn their place: the attribute assertion passes on an id typo and on a
 * labelledBy pointing at an element that does not exist, and BOTH of those render a combobox
 * with no accessible name at all. The last test in this file demonstrates that directly.
 */
import React, { useState } from 'react';
import Router from 'next/router';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

import Select, { type SelectGroup, type SelectOption, type SelectProps } from '../components/ui/Select';

/**
 * COMPILE-TIME HALF OF THE LABELLING CONTRACT, asserted here because tsc reads this file.
 * `npx tsc --noEmit` fails if the @ts-expect-error line stops erroring - that is, the day the
 * union is loosened enough to admit an unlabelled combobox.
 */
const BASE = { value: '', onChange: () => undefined, options: [] as SelectOption[] };
// @ts-expect-error - at least one of label / ariaLabel / labelledBy is required
const UNLABELLED_IS_REJECTED: SelectProps = BASE;
const DUAL_LABELLED_IS_ACCEPTED: SelectProps = { ...BASE, label: 'Channel', ariaLabel: 'Channel for row 3' };
void UNLABELLED_IS_REJECTED;
void DUAL_LABELLED_IS_ACCEPTED;

/**
 * `banana` is disabled, and it sits in the MIDDLE rather than at an end - the only position
 * from which "skipping disabled" is distinguishable from "clamping at the edge".
 */
const OPTIONS: SelectOption[] = [
  { value: 'apple', label: 'Apple' },
  { value: 'avocado', label: 'Avocado' },
  { value: 'banana', label: 'Banana', disabled: true },
  { value: 'cherry', label: 'Cherry' },
];

/** Fifteen, because a PageDown of 10 cannot be observed on a list of four. */
const LONG: SelectOption[] = Array.from( { length: 15 }, ( _unused, i ) => ( {
  value: `v${ i }`,
  label: `Item ${ i }`,
} ) );

const GROUPED: SelectGroup[] = [
  { label: 'Citrus', options: [ { value: 'lemon', label: 'Lemon' }, { value: 'lime', label: 'Lime' } ] },
  { label: 'Berries', options: [ { value: 'fig', label: 'Fig' } ] },
];

interface HarnessProps {
  initial?: string;
  options?: SelectOption[] | SelectGroup[];
  onChange?: ( value: string ) => void;
  name?: string;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * A controlled harness, because `Select` is controlled by design and a test that never
 * updates `value` cannot see clause 2 (no onChange on a no-op) at all - the second pick of
 * the same row would look like a change.
 *
 * Props are passed one by one rather than spread: the labelling type is a union, and a spread
 * of an optional-everything object widens it back to "none required", which would disarm the
 * compile-time assertion above.
 */
const Harness: React.FC<HarnessProps> = ( {
  initial = '',
  options = OPTIONS,
  onChange,
  name,
  placeholder = 'Choose a fruit',
  disabled = false,
} ) => {
  const [ value, setValue ] = useState( initial );
  return (
    <Select
      ariaLabel="Fruit"
      value={ value }
      options={ options }
      name={ name }
      placeholder={ placeholder }
      disabled={ disabled }
      onChange={ next => { setValue( next ); onChange?.( next ); } }
    />
  );
};

const trigger = () => screen.getByRole( 'combobox', { name: 'Fruit' } );
const menu = () => screen.queryByRole( 'listbox' );
const activeRow = () => document.querySelector( '[data-active="true"]' );
const hidden = () => document.querySelector<HTMLInputElement>( 'input[type="hidden"]' );

afterEach( () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
} );

describe( 'Select - opening and closing', () => {
  it( 'opens on click, closes on a second click, and reports it on aria-expanded', () => {
    render( <Harness /> );
    expect( trigger() ).toHaveAttribute( 'aria-expanded', 'false' );
    expect( menu() ).toBeNull();

    fireEvent.click( trigger() );
    expect( trigger() ).toHaveAttribute( 'aria-expanded', 'true' );
    expect( menu() ).not.toBeNull();

    // ANCHOR RE-CLICK is the anchor's own toggle and not Popover's outside-press handler, for
    // the reason Popover.tsx records: pointerdown precedes click, so closing on the press
    // would let the click reopen immediately.
    fireEvent.click( trigger() );
    expect( trigger() ).toHaveAttribute( 'aria-expanded', 'false' );
    expect( menu() ).toBeNull();
  } );

  it( 'closes on an outside press and leaves no listener behind', () => {
    render( <Harness /> );
    fireEvent.click( trigger() );
    expect( menu() ).not.toBeNull();

    fireEvent.pointerDown( document.body );
    expect( menu() ).toBeNull();

    // A second outside press with the menu already closed must be inert - which is the
    // observable consequence of the listeners being removed on close rather than on unmount.
    fireEvent.pointerDown( document.body );
    expect( menu() ).toBeNull();
  } );

  it( 'closes on a route change, keeping the current value', () => {
    // Driven through the next/router SINGLETON's emitter, which is what Popover listens to -
    // `useRouter()` throws when no RouterContext is mounted, so the singleton is both the
    // safe choice in a component and the only one a unit test can exercise. On
    // routeChangeStart rather than Complete: at Start the old tree is still attached, so the
    // menu is gone before the next page paints instead of hanging over it for a frame.
    const onChange = vi.fn();
    render( <Harness initial="apple" onChange={ onChange } /> );
    fireEvent.click( trigger() );
    expect( menu() ).not.toBeNull();

    act( () => { Router.events.emit( 'routeChangeStart', '/shop/merchandise/' ); } );
    expect( menu() ).toBeNull();
    expect( onChange ).not.toHaveBeenCalled();
    expect( trigger() ).toHaveTextContent( 'Apple' );
  } );

  it( 'adds its scroll and resize listeners on open and removes them on close', () => {
    // Asserted on the REGISTRATION rather than on a moved panel, because jsdom lays nothing
    // out: every getBoundingClientRect() is zero, so a reposition cannot be observed. What can
    // be observed is the bookkeeping the portal decision costs - and leaving it out is the
    // mistake that produces a menu detached from its trigger after a scroll.
    const add = vi.spyOn( window, 'addEventListener' );
    const remove = vi.spyOn( window, 'removeEventListener' );
    render( <Harness /> );

    fireEvent.click( trigger() );
    const added = add.mock.calls.map( call => call[ 0 ] );
    expect( added ).toContain( 'scroll' );
    expect( added ).toContain( 'resize' );
    // capture: true, or a scroll inside a workspace panel never reaches this listener.
    expect( add.mock.calls.some( call => call[ 0 ] === 'scroll' && call[ 2 ] === true ) ).toBe( true );

    fireEvent.click( trigger() );
    const removed = remove.mock.calls.map( call => call[ 0 ] );
    expect( removed ).toContain( 'scroll' );
    expect( removed ).toContain( 'resize' );
    expect( remove.mock.calls.some( call => call[ 0 ] === 'scroll' && call[ 2 ] === true ) ).toBe( true );
  } );

  it( 'styles the portalled panel from classes, with only computed geometry inline', () => {
    // THE PORTAL ESCAPES styled-jsx's SCOPE HASH, so the panel's appearance has to come from
    // form-controls.css. This asserts the shape of that decision where it is observable: the
    // class is present, and the inline style carries nothing but position and the two
    // computed custom properties.
    render( <Harness /> );
    fireEvent.click( trigger() );
    const panel = document.querySelector<HTMLElement>( '[data-ui-popover]' );
    expect( panel ).not.toBeNull();
    expect( panel! ).toHaveClass( 'ui-popover' );
    expect( panel!.parentElement ).toBe( document.body );

    const inline = Array.from( { length: panel!.style.length }, ( _unused, i ) => panel!.style.item( i ) );
    const allowed = new Set( [ 'top', 'left', 'width', '--ui-popover-z', '--ui-popover-max-h' ] );
    expect( inline.filter( property => !allowed.has( property ) ) ).toEqual( [] );
    // The layer, from src/lib/design-tokens.ts rather than a literal in the component.
    expect( panel!.style.getPropertyValue( '--ui-popover-z' ) ).toBe( '1500' );
  } );
} );

describe( 'Select - the keyboard table', () => {
  it( 'Enter opens with the active option on the selected one, and commits on Enter', () => {
    const onChange = vi.fn();
    render( <Harness initial="avocado" onChange={ onChange } /> );

    fireEvent.keyDown( trigger(), { key: 'Enter' } );
    expect( menu() ).not.toBeNull();
    expect( activeRow() ).toHaveTextContent( 'Avocado' );

    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( activeRow() ).toHaveTextContent( 'Cherry' );

    fireEvent.keyDown( trigger(), { key: 'Enter' } );
    expect( menu() ).toBeNull();
    expect( onChange ).toHaveBeenCalledWith( 'cherry' );
    expect( trigger() ).toHaveFocus();
  } );

  it( 'Space opens and commits, exactly as Enter does', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.keyDown( trigger(), { key: ' ' } );
    expect( menu() ).not.toBeNull();
    fireEvent.keyDown( trigger(), { key: ' ' } );
    expect( onChange ).toHaveBeenCalledWith( 'apple' );
  } );

  it( 'ArrowDown and ArrowUp open when closed, and move the active option by one when open', () => {
    render( <Harness initial="avocado" /> );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( menu() ).not.toBeNull();
    expect( activeRow() ).toHaveTextContent( 'Avocado' );

    fireEvent.keyDown( trigger(), { key: 'ArrowUp' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );
    // Clamped at the first option rather than wrapping, as the native control is.
    fireEvent.keyDown( trigger(), { key: 'ArrowUp' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );
  } );

  it( 'Alt+ArrowDown opens', () => {
    render( <Harness /> );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown', altKey: true } );
    expect( menu() ).not.toBeNull();
  } );

  it( 'skips disabled options in both directions and never commits one', () => {
    const onChange = vi.fn();
    render( <Harness initial="avocado" onChange={ onChange } /> );
    fireEvent.keyDown( trigger(), { key: 'Enter' } );

    // avocado -> (banana is disabled) -> cherry
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( activeRow() ).toHaveTextContent( 'Cherry' );
    // and back the other way, over the same hole
    fireEvent.keyDown( trigger(), { key: 'ArrowUp' } );
    expect( activeRow() ).toHaveTextContent( 'Avocado' );

    // A click on the disabled row is inert too, not merely unreachable by keyboard.
    fireEvent.click( screen.getByRole( 'option', { name: 'Banana' } ) );
    expect( onChange ).not.toHaveBeenCalled();
    expect( menu() ).not.toBeNull();
  } );

  it( 'Home and End open at the first and last ENABLED option', () => {
    const last: SelectOption[] = [ ...OPTIONS, { value: 'date', label: 'Date', disabled: true } ];
    render( <Harness options={ last } /> );

    fireEvent.keyDown( trigger(), { key: 'End' } );
    expect( menu() ).not.toBeNull();
    // Not "Date": the last option is disabled, so End lands on the last ENABLED one.
    expect( activeRow() ).toHaveTextContent( 'Cherry' );

    fireEvent.keyDown( trigger(), { key: 'Home' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );
  } );

  it( 'PageDown and PageUp move the active option by ten', () => {
    render( <Harness options={ LONG } initial="v0" /> );
    fireEvent.keyDown( trigger(), { key: 'Enter' } );
    expect( activeRow() ).toHaveTextContent( 'Item 0' );

    fireEvent.keyDown( trigger(), { key: 'PageDown' } );
    expect( activeRow() ).toHaveTextContent( 'Item 10' );

    fireEvent.keyDown( trigger(), { key: 'PageUp' } );
    expect( activeRow() ).toHaveTextContent( 'Item 0' );

    // Clamped at the end of the list rather than running off it.
    fireEvent.keyDown( trigger(), { key: 'End' } );
    fireEvent.keyDown( trigger(), { key: 'PageDown' } );
    expect( activeRow() ).toHaveTextContent( 'Item 14' );
  } );

  it( 'Escape closes, discards, and returns focus to the trigger', () => {
    const onChange = vi.fn();
    render( <Harness initial="apple" onChange={ onChange } /> );
    fireEvent.keyDown( trigger(), { key: 'Enter' } );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( activeRow() ).toHaveTextContent( 'Avocado' );

    fireEvent.keyDown( trigger(), { key: 'Escape' } );
    expect( menu() ).toBeNull();
    expect( onChange ).not.toHaveBeenCalled();
    expect( trigger() ).toHaveFocus();
    expect( trigger() ).toHaveTextContent( 'Apple' );
  } );

  it( 'Tab closes, keeps the current value, and does not preventDefault', () => {
    const onChange = vi.fn();
    render( <Harness initial="apple" onChange={ onChange } /> );
    fireEvent.keyDown( trigger(), { key: 'Enter' } );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );

    // fireEvent returns false when the event was cancelled; Tab must let focus move on.
    const notCancelled = fireEvent.keyDown( trigger(), { key: 'Tab' } );
    expect( notCancelled ).toBe( true );
    expect( menu() ).toBeNull();
    expect( onChange ).not.toHaveBeenCalled();
    expect( trigger() ).toHaveTextContent( 'Apple' );
  } );

  it( 'a printable character selects the first match while CLOSED', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.keyDown( trigger(), { key: 'c' } );
    expect( onChange ).toHaveBeenCalledWith( 'cherry' );
    expect( menu() ).toBeNull();
  } );

  it( 'drives a type-ahead buffer while OPEN, and resets it after 600ms', () => {
    vi.useFakeTimers();
    render( <Harness /> );
    fireEvent.keyDown( trigger(), { key: 'Enter' } );

    // 'a' then 'v' inside the window is "av" - Avocado, not Apple.
    fireEvent.keyDown( trigger(), { key: 'a' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );
    fireEvent.keyDown( trigger(), { key: 'v' } );
    expect( activeRow() ).toHaveTextContent( 'Avocado' );

    // After the reset the same 'a' starts a new buffer and lands on Apple again. Without the
    // reset the buffer would read "ava" and match nothing, leaving the row where it was -
    // which is the failure this assertion exists for.
    vi.advanceTimersByTime( 600 );
    fireEvent.keyDown( trigger(), { key: 'a' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );

    // Case-insensitive, and the first ENABLED match: 'b' is Banana, which is disabled, so the
    // active row must not move onto it.
    vi.advanceTimersByTime( 600 );
    fireEvent.keyDown( trigger(), { key: 'B' } );
    expect( activeRow() ).toHaveTextContent( 'Apple' );
  } );

  it( 'tracks the active option with aria-activedescendant and drops it on close', () => {
    render( <Harness /> );
    expect( trigger() ).not.toHaveAttribute( 'aria-activedescendant' );

    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    // Compared against the live active row's id rather than a hardcoded string, so the test
    // cannot pass on a dangling reference - which is the same failure mode that makes the
    // accessible-name tests below use getByRole instead of an attribute check.
    expect( activeRow() ).not.toBeNull();
    expect( trigger().getAttribute( 'aria-activedescendant' ) ).toBe( activeRow()!.id );

    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( trigger().getAttribute( 'aria-activedescendant' ) ).toBe( activeRow()!.id );

    fireEvent.keyDown( trigger(), { key: 'Escape' } );
    expect( trigger() ).not.toHaveAttribute( 'aria-activedescendant' );
  } );
} );

describe( 'Select - value semantics, the five clauses', () => {
  it( '1. an option whose value is the empty string is a selectable placeholder ROW', () => {
    const onChange = vi.fn();
    const withEmptyRow: SelectOption[] = [ { value: '', label: 'Any fruit' }, ...OPTIONS ];
    render( <Harness options={ withEmptyRow } initial="apple" onChange={ onChange } /> );

    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'option', { name: 'Any fruit' } ) );
    expect( onChange ).toHaveBeenCalledWith( '' );
  } );

  it( '2. onChange does NOT fire when the committed value equals the current one', () => {
    // A native `change` does not fire on a no-op either, and a call site that saves on every
    // selection would otherwise write to the API on a re-pick of the same row.
    const onChange = vi.fn();
    render( <Harness initial="apple" onChange={ onChange } /> );

    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'option', { name: 'Apple' } ) );
    expect( menu() ).toBeNull();
    expect( onChange ).not.toHaveBeenCalled();

    // The same commit path DOES fire for a different row, so the assertion above is not
    // passing because nothing is wired up.
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'option', { name: 'Cherry' } ) );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( 'cherry' );
  } );

  it( '3. a value matching no option shows the placeholder and the hidden input KEEPS it', () => {
    // The component never silently rewrites state it was given: a stale id from an API still
    // round-trips through a form submission, so the server sees the value the page held.
    render( <Harness initial="durian" name="fruit" /> );
    expect( trigger() ).toHaveTextContent( 'Choose a fruit' );
    expect( hidden() ).toHaveValue( 'durian' );
  } );

  it( '4. duplicate values warn once in development, with a COUNT and no option text', () => {
    const warn = vi.spyOn( console, 'warn' ).mockImplementation( () => undefined );
    const duplicated: SelectOption[] = [
      { value: 'apple', label: 'Apple' },
      { value: 'apple', label: 'Apple again' },
      { value: 'cherry', label: 'Cherry' },
      { value: 'cherry', label: 'Cherry again' },
    ];
    render( <Harness options={ duplicated } initial="apple" /> );

    expect( warn ).toHaveBeenCalledTimes( 1 );
    const message = String( warn.mock.calls[ 0 ][ 0 ] );
    expect( message ).toContain( '2 duplicate' );
    // NO OPTION TEXT. An option label can carry a customer name, and a console line is a log
    // line like any other.
    expect( message ).not.toContain( 'Apple' );
    expect( message ).not.toContain( 'Cherry' );

    // The first of each wins for display.
    fireEvent.click( trigger() );
    const chosen = document.querySelectorAll( '[aria-selected="true"]' );
    expect( chosen ).toHaveLength( 1 );
    expect( chosen[ 0 ] ).toHaveTextContent( 'Apple' );
  } );

  it( '5. an empty options array disables the trigger and the menu never opens', () => {
    render( <Harness options={ [] } /> );
    const control = trigger();
    expect( control ).toHaveAttribute( 'aria-disabled', 'true' );
    expect( control ).toBeDisabled();
    expect( control ).toHaveTextContent( 'Choose a fruit' );

    fireEvent.click( control );
    fireEvent.keyDown( control, { key: 'Enter' } );
    fireEvent.keyDown( control, { key: 'ArrowDown' } );
    expect( menu() ).toBeNull();
    expect( control ).toHaveAttribute( 'aria-expanded', 'false' );
  } );
} );

describe( 'Select - the hidden input', () => {
  it( 'is emitted only when name is set, and carries the current value', () => {
    const { unmount } = render( <Harness initial="apple" /> );
    expect( hidden() ).toBeNull();
    unmount();

    render( <Harness initial="apple" name="fruit" /> );
    expect( hidden() ).toHaveValue( 'apple' );
    expect( hidden() ).toHaveAttribute( 'name', 'fruit' );
  } );

  it( 'round-trips through new FormData( form )', () => {
    // HONEST JUSTIFICATION, matching the census: across all 162 select elements, ZERO set
    // name, form, required, onBlur or ref. There is no current instance of the failure this
    // prevents - the prop is defensive design for the next form, and this test is what makes
    // the claim checkable rather than asserted.
    render(
      <form data-testid="fruit-form">
        <Harness initial="apple" name="fruit" />
      </form>
    );
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'option', { name: 'Cherry' } ) );

    const data = new FormData( screen.getByTestId( 'fruit-form' ) as HTMLFormElement );
    expect( data.get( 'fruit' ) ).toBe( 'cherry' );
  } );
} );

describe( 'Select - groups', () => {
  it( 'names each group and keeps one flat navigation order across them', () => {
    render( <Harness options={ GROUPED } /> );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );

    expect( screen.getByRole( 'group', { name: 'Citrus' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'group', { name: 'Berries' } ) ).toBeInTheDocument();

    // Lemon -> Lime -> Fig: the second group is not a separate keyboard territory.
    expect( activeRow() ).toHaveTextContent( 'Lemon' );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( activeRow() ).toHaveTextContent( 'Lime' );
    fireEvent.keyDown( trigger(), { key: 'ArrowDown' } );
    expect( activeRow() ).toHaveTextContent( 'Fig' );
  } );
} );

/**
 * THE FIVE LABELLING ROWS, one test each, plus the sixth that shows why they are written this
 * way. design 5.2's table is the source; every case resolves the control by its COMPUTED
 * ACCESSIBLE NAME.
 */
describe( 'Select - the accessible name computes, one case per labelling row', () => {
  const noop = () => undefined;

  it( 'row 1 - label renders a visible span and names the combobox', () => {
    render( <Select label="Channel" value="" options={ OPTIONS } onChange={ noop } /> );
    expect( screen.getByRole( 'combobox', { name: 'Channel' } ) ).toBeInTheDocument();
    // The visible text is the component's own, which is what lets the 18 wrapping-<label>
    // call sites delete their wrapper.
    expect( screen.getByText( 'Channel' ) ).toBeInTheDocument();
  } );

  it( 'row 2 - ariaLabel names the combobox with no visible text', () => {
    render( <Select ariaLabel="Phone type" value="" options={ OPTIONS } onChange={ noop } /> );
    expect( screen.getByRole( 'combobox', { name: 'Phone type' } ) ).toBeInTheDocument();
    expect( screen.queryByText( 'Phone type' ) ).toBeNull();
  } );

  it( 'row 3 - labelledBy pointing at an external <span id> takes that element\'s text', () => {
    render(
      <>
        <span id="external-span">Assignee</span>
        <Select labelledBy="external-span" value="" options={ OPTIONS } onChange={ noop } />
      </>
    );
    expect( screen.getByRole( 'combobox', { name: 'Assignee' } ) ).toBeInTheDocument();
  } );

  it( 'row 4 - label + ariaLabel: aria-label WINS, the span still renders, no aria-labelledby', () => {
    // THE ROW A ONE-OF-THREE UNION COULD NOT EXPRESS. cart.tsx:1720-1727 renders the same
    // visible "Choose option" on every cart row with a PER-ITEM aria-label, and
    // CartCheckout.test.tsx:506 resolves the control by that per-item name - the test standing
    // in front of a wrong-amount order. aria-labelledby OUTRANKS aria-label, so emitting both
    // would hand the name back to the shared visible text and lose the per-item one.
    render(
      <Select
        label="Choose option"
        ariaLabel="Choose option for Merchandise"
        value=""
        options={ OPTIONS }
        onChange={ noop }
      />
    );
    const control = screen.getByRole( 'combobox', { name: 'Choose option for Merchandise' } );
    expect( control ).toBeInTheDocument();
    // The visible span is still there, presentational in this combination.
    expect( screen.getByText( 'Choose option' ) ).toBeInTheDocument();
    // A NEGATIVE about the attribute, which is a different claim from "the name computes" and
    // is the mechanism that would silently lose the per-item name.
    expect( control ).not.toHaveAttribute( 'aria-labelledby' );
    // And the shared visible text must NOT resolve the control, or the per-item name is not
    // actually what a screen reader would announce.
    expect( screen.queryByRole( 'combobox', { name: 'Choose option' } ) ).toBeNull();
  } );

  it( 'row 5 - labelledBy pointing at a RETAINED external <label id> - migration shape (b)', () => {
    // Tested rather than reviewed because it is the one branch with NO VISIBLE FAILURE MODE:
    // both elements stay in place and only the wiring changes. Shape (a) is self-evident in a
    // diff - a <label> disappears and a label= appears - whereas this one looks identical
    // whether or not the association survived.
    //
    // The <label> deliberately carries NO htmlFor: it no longer labels a labelable control,
    // and per HTML-AAM a <button>'s name comes from its contents, so a `for` pointing at the
    // trigger would name nothing while looking like it did.
    render(
      <>
        <label id="retained-label">Category</label>
        <Select labelledBy="retained-label" id="blog-studio-category" value="" options={ OPTIONS } onChange={ noop } />
      </>
    );
    expect( screen.getByRole( 'combobox', { name: 'Category' } ) ).toBeInTheDocument();
  } );

  it( 'is why the attribute assertion is banned: a dangling labelledBy names NOTHING', () => {
    // This is the test that justifies the other five. The combobox below has an
    // aria-labelledby attribute, so `toHaveAttribute( 'aria-labelledby', 'typo-id' )` would
    // pass - and the control has no accessible name at all beyond its own placeholder text.
    // An id typo and a deleted target element both produce exactly this.
    render(
      <>
        <span id="external-span">Assignee</span>
        <Select labelledBy="typo-id" placeholder="Pick one" value="" options={ OPTIONS } onChange={ noop } />
      </>
    );
    expect( screen.queryByRole( 'combobox', { name: 'Assignee' } ) ).toBeNull();
    // AND IT IS WORSE THAN THE DESIGN'S WORST CASE, which is worth recording because it was
    // measured here rather than assumed. design 5.2 says such a control "announces only its
    // selected value" - the "WhatsApp / Paid / Unassigned" failure. Measured against
    // dom-accessibility-api, a DANGLING aria-labelledby does not fall through to the button's
    // contents at all: the computed name is the EMPTY STRING, so the control announces
    // nothing. Either way the attribute assertion would have passed.
    expect( screen.queryByRole( 'combobox', { name: 'Pick one' } ) ).toBeNull();
    expect( screen.getByRole( 'combobox', { name: '' } ) ).toBeInTheDocument();
  } );
} );
