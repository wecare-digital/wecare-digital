/**
 * src/components/ui/ColorField.tsx - THE HEX CONTRACT, AND THE CAPABILITY THAT WENT WITH IT.
 *
 * The three migrated call sites are AppBuilderTab's brand colours, and each one keeps a free
 * text input beside the picker bound to the same state. So the string this component emits has
 * to be exactly what the native control emitted - lowercase `#rrggbb` - or the two halves of
 * one field start disagreeing about the same colour. That is what most of this file proves.
 *
 * THE CAPABILITY LOSS IS ASSERTED, NOT JUST DESCRIBED. The native control opened the OS picker:
 * an HSV area, an eyedropper, recent colours. None of that is rebuilt, so a colour outside the
 * design palette is reachable ONLY by typing its hex. The last describe block pins that as
 * behaviour - an off-palette value round-trips through the hex field and shows as checked
 * nowhere in the grid - so the limitation stays a recorded decision rather than becoming a bug
 * report.
 *
 * jsdom has no layout: nothing here observes Popover's flip, clamp or clipping. See
 * UiDateField.test.tsx's header for where that evidence actually comes from.
 */
import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import ColorField, { type ColorFieldProps, PALETTE, normaliseHex } from '../components/ui/ColorField';
import { colors } from '../lib/design-tokens';

const BASE = { value: '#1a3a2a', onChange: () => undefined };
// @ts-expect-error - at least one of label / ariaLabel / labelledBy is required
const UNLABELLED_IS_REJECTED: ColorFieldProps = BASE;
void UNLABELLED_IS_REJECTED;

interface HarnessProps { initial?: string; onChange?: ( hex: string ) => void; name?: string }

const Harness: React.FC<HarnessProps> = ( { initial = '#1a3a2a', onChange, name } ) => {
  const [ value, setValue ] = useState( initial );
  return (
    <ColorField
      label="Primary colour"
      value={ value }
      name={ name }
      onChange={ hex => { setValue( hex ); onChange?.( hex ); } }
    />
  );
};

const trigger = () => screen.getByRole( 'button', { name: 'Primary colour' } );
const hexField = () => screen.getByRole( 'textbox', { name: 'Hex' } );

describe( 'ColorField - the palette', () => {
  it( 'is derived from the design tokens rather than retyped, with no alpha and no duplicates', () => {
    // A second hand-written list would drift from the tokens the rest of the app draws with,
    // and no new hex may be introduced here at all.
    expect( PALETTE.length ).toBeGreaterThan( 10 );
    for ( const swatch of PALETTE ) {
      expect( swatch.hex ).toMatch( /^#[0-9a-f]{6}$/ );
      expect( ( colors as Record<string, string> )[ swatch.token ].toLowerCase() ).toBe( swatch.hex );
    }
    // rgba() tokens are skipped - a colour input cannot carry alpha - and a hex that two tokens
    // share appears ONCE, or two radios would report aria-checked for one value.
    expect( PALETTE.some( s => s.token === 'textSecondary' ) ).toBe( false );
    expect( new Set( PALETTE.map( s => s.hex ) ).size ).toBe( PALETTE.length );
    // The two brand colours are in it, which is the whole point for a brand-colour picker.
    expect( PALETTE.map( s => s.hex ) ).toContain( '#1a3a2a' );
    expect( PALETTE.map( s => s.hex ) ).toContain( '#d1f470' );
  } );

  it( 'names each swatch by its TOKEN, not by its hex', () => {
    render( <Harness /> );
    fireEvent.click( trigger() );
    // "primary hover", not "#0f2a1d": a hex read aloud is not a colour anybody recognises.
    expect( screen.getByRole( 'radio', { name: 'primary hover' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'radio', { name: 'lime' } ) ).toBeInTheDocument();
  } );

  it( 'marks the current value checked, and only that one', () => {
    render( <Harness initial="#d1f470" /> );
    fireEvent.click( trigger() );
    const checked = screen.getAllByRole( 'radio' ).filter( r => r.getAttribute( 'aria-checked' ) === 'true' );
    expect( checked ).toHaveLength( 1 );
    expect( checked[ 0 ] ).toHaveAccessibleName( 'lime' );
  } );
} );

describe( 'ColorField - the string it emits', () => {
  it( 'shows the hex as TEXT on the trigger, so colour is not the only indicator', () => {
    render( <Harness initial="#d1f470" /> );
    expect( trigger() ).toHaveTextContent( '#d1f470' );
  } );

  it( 'emits lowercase #rrggbb when a swatch is chosen, and closes', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'radio', { name: 'lime' } ) );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '#d1f470' );
    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
  } );

  it( 'does not emit when the chosen swatch is the current value', () => {
    const onChange = vi.fn();
    render( <Harness initial="#d1f470" onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.click( screen.getByRole( 'radio', { name: 'lime' } ) );
    expect( onChange ).not.toHaveBeenCalled();
  } );

  it( 'the arrow keys move and check, as a radiogroup does', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.keyDown( screen.getByRole( 'radiogroup' ), { key: 'ArrowRight' } );
    // PALETTE[0] is `primary` (#1a3a2a), the initial value, so one step right is `primaryHover`.
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( PALETTE[ 1 ].hex );
    // Arrow-checking does NOT close: it is a live preview, and the operator is still choosing.
    expect( screen.getByRole( 'dialog' ) ).toBeInTheDocument();
  } );

  it( 'Esc closes and restores focus to the trigger', () => {
    render( <Harness /> );
    fireEvent.click( trigger() );
    fireEvent.keyDown( screen.getByRole( 'radiogroup' ), { key: 'Escape' } );
    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
    expect( document.activeElement ).toBe( trigger() );
  } );

  it( 'TAB closes and restores focus to the trigger, rather than dropping it on <body>', () => {
    // Popover's 'escape' arm refocuses the anchor; its 'tab' arm does not. Roving focus lives
    // on a swatch INSIDE the portalled panel, so before the fix the unmount removed the node
    // the browser would have computed the next tab stop from - measured in jsdom as
    // activeElement '.ui-color-swatch' before the key and BODY after.
    render( <Harness /> );
    fireEvent.click( trigger() );
    expect( document.activeElement ).toHaveClass( 'ui-color-swatch' );

    fireEvent.keyDown( screen.getByRole( 'radiogroup' ), { key: 'Tab' } );

    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
    expect( document.activeElement ).toBe( trigger() );
    expect( document.activeElement ).not.toBe( document.body );
  } );

  it( 'an outside press closes and takes focus back too', () => {
    render( <Harness /> );
    fireEvent.click( trigger() );
    fireEvent.pointerDown( document.body );
    expect( screen.queryByRole( 'dialog' ) ).not.toBeInTheDocument();
    expect( document.activeElement ).toBe( trigger() );
  } );

  it( 'Tab emits nothing of its own - the arrows already committed as they moved', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.keyDown( screen.getByRole( 'radiogroup' ), { key: 'ArrowRight' } );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( PALETTE[ 1 ].hex );
    fireEvent.keyDown( screen.getByRole( 'radiogroup' ), { key: 'Tab' } );
    // Still exactly one call: closing does not re-emit the already-committed swatch.
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( PALETTE[ 1 ].hex );
  } );

  it( 'carries the value in a hidden input, so a form submission still sees it', () => {
    const { container } = render( <Harness initial="#d1f470" name="primaryColor" /> );
    expect( container.querySelector( 'input[type="hidden"][name="primaryColor"]' ) ).toHaveValue( '#d1f470' );
  } );
} );

describe( 'ColorField - the hex field, which is the ONLY route to an off-palette colour', () => {
  it( 'round-trips a hex, normalising case and a missing hash', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.change( hexField(), { target: { value: 'D1F470' } } );
    fireEvent.blur( hexField() );
    // Uppercase in, lowercase out, hash added: exactly what the native control emitted.
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '#d1f470' );
    expect( hexField() ).toHaveValue( '#d1f470' );
  } );

  it( 'commits on Enter as well as on blur, and never per keystroke', () => {
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.change( hexField(), { target: { value: '#d1f4' } } );
    expect( onChange ).not.toHaveBeenCalled();
    fireEvent.change( hexField(), { target: { value: '#d1f470' } } );
    fireEvent.keyDown( hexField(), { key: 'Enter' } );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '#d1f470' );
  } );

  it( 'reverts an invalid hex to the last valid value', () => {
    const onChange = vi.fn();
    render( <Harness initial="#1a3a2a" onChange={ onChange } /> );
    fireEvent.click( trigger() );
    for ( const typed of [ 'rebeccapurple', '#1a3', '#1a3a2az', 'rgb(0,0,0)', '' ] ) {
      fireEvent.change( hexField(), { target: { value: typed } } );
      fireEvent.blur( hexField() );
    }
    expect( onChange ).not.toHaveBeenCalled();
    expect( hexField() ).toHaveValue( '#1a3a2a' );
  } );

  it( 'REACHES AN OFF-PALETTE COLOUR, and that is the only way to reach one', () => {
    // THE RECORDED CAPABILITY LOSS, asserted as behaviour. #ff00ff is not a design token, so no
    // swatch offers it; the hex field accepts it, the value is kept verbatim, and NOTHING in
    // the grid reads as checked. A future HSV panel would change the first half of this test
    // and must not change the second.
    const onChange = vi.fn();
    render( <Harness onChange={ onChange } /> );
    fireEvent.click( trigger() );
    fireEvent.change( hexField(), { target: { value: '#ff00ff' } } );
    fireEvent.blur( hexField() );
    expect( onChange ).toHaveBeenCalledExactlyOnceWith( '#ff00ff' );
    expect( trigger() ).toHaveTextContent( '#ff00ff' );
    const checked = screen.getAllByRole( 'radio' ).filter( r => r.getAttribute( 'aria-checked' ) === 'true' );
    expect( checked ).toHaveLength( 0 );
  } );

  it( 'normaliseHex is the single parse, and it is strict', () => {
    expect( normaliseHex( 'D1F470' ) ).toBe( '#d1f470' );
    expect( normaliseHex( '  #D1F470 ' ) ).toBe( '#d1f470' );
    expect( normaliseHex( '#fff' ) ).toBeNull();        // three-digit shorthand is NOT accepted:
    expect( normaliseHex( '#ffffffff' ) ).toBeNull();   // the native value is always six digits
    expect( normaliseHex( 'white' ) ).toBeNull();
  } );
} );
