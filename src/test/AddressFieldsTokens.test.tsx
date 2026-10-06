import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import AddressFields from '../components/AddressFields';
import type { AddressDraft } from '../components/AddressFields';

/**
 * THE ONE CHANGE IN LAYER 1 THAT NO BROWSER IN THIS REPO CAN VERIFY, so it is pinned here.
 *
 * `cart.tsx:1790` gates `CheckoutProfile` - and therefore this form - on
 * `showProfile && checkoutAccessToken`: the profile editor must be OPEN and an authenticated
 * checkout token present. An unauthenticated Playwright context has neither, and `/orders/`,
 * the other render site, is behind the same sign-in. So `controlprobe.js --cart` can measure
 * the three money-row controls and cannot reach these six, and the evidence for this rule is:
 *
 *   1. source review of a four-declaration diff, small enough to read exhaustively;
 *   2. this test;
 *   3. the owner's signed-in visual pass, which is where a real checkout address form appears.
 *
 * THIS IS A TEMPLATE-CONTENT ASSERTION AND IS HONEST ABOUT BEING ONE. jsdom does not compute
 * styled-jsx: the <style> content is emitted into the document but nothing resolves a custom
 * property or applies a cascade, so `getComputedStyle` here would report nothing useful. What
 * can be checked is that the rule the component SHIPS names the shared tokens and no longer
 * names the three private numbers it used to. That is weaker than a measurement and it is not
 * nothing: the failure this guards against is a hand-written literal creeping back, which is a
 * property of the text.
 *
 * WHY IT MATTERS THAT ALL SIX MOVE TOGETHER. `form-controls.css` reaches the India state
 * <select> and cannot reach the five <input>s in the same `.address-grid` - address line 1 and
 * 2, city, PIN code and the read-only country field. Skinning only the select would leave the
 * state field a different height, radius and border weight from the five fields beside it in
 * one grid, on the checkout page. That is why this rule was rewritten by hand instead of
 * overridden.
 */
const DRAFT: AddressDraft = {
  addressLine1: '12 MG Road',
  addressLine2: '',
  city: 'Bengaluru',
  state: 'Karnataka',
  postalCode: '560001',
};

/** The styled-jsx template text the component emits, as one string. */
function styleText (): string {
  const { container } = render(
    <AddressFields value={DRAFT} onChange={vi.fn()} />
  );
  const styles = Array.from( container.ownerDocument.querySelectorAll( 'style' ) )
    .map( el => el.textContent || '' )
    .join( '\n' );
  return styles;
}

/** The `input,select` rule only, so a number elsewhere in the sheet cannot pass or fail it. */
function sharedControlRule ( css: string ): string {
  const match = /(?:^|[}\s])input\s*,\s*select\s*\{([^}]*)\}/.exec( css );
  return match ? match[ 1 ] : '';
}

describe( 'AddressFields uses the shared control tokens', () => {
  it( 'emits a styled-jsx rule for the six controls', () => {
    const css = styleText();
    expect( css, 'the component must emit its styled-jsx template' ).not.toBe( '' );
    expect( sharedControlRule( css ), 'the input,select rule must be in the emitted template' )
      .not.toBe( '' );
  } );

  it( 'names the control tokens rather than private numbers', () => {
    const rule = sharedControlRule( styleText() );
    expect( rule ).toContain( 'var(--control-h)' );
    expect( rule ).toContain( 'var(--control-radius)' );
    expect( rule ).toContain( 'var(--control-border-w)' );
    expect( rule ).toContain( 'var(--control-border)' );
  } );

  it( 'no longer carries the three literals it was built on', () => {
    // 52px was the height, 10px the radius, 1px the border. Scoped to the rule, because the
    // sheet legitimately contains 10px elsewhere - the legend margin and the help text - and a
    // whole-template negative would fail on a number that has nothing to do with a control.
    const rule = sharedControlRule( styleText() );
    expect( rule ).not.toContain( '52px' );
    expect( rule ).not.toContain( '10px' );
    expect( rule ).not.toContain( '1px solid' );
  } );

  it( 'pairs the focus ring with the focus outline', () => {
    // Section 4.3's ring-pairing rule, asserted as the PROPERTY rather than one spelling of it,
    // so it survives a reorder or a colour change. The <select> takes --focus-ring from
    // form-controls.css; the five <input>s are outside that selector, so without this
    // declaration one control in six would ring and five would not, in one grid.
    const css = styleText();
    const focusRules = [ ...css.matchAll( /([^{}]*:focus-visible[^{]*)\{([^}]*)\}/g ) ];
    expect( focusRules.length ).toBeGreaterThan( 0 );
    for ( const [ , selector, body ] of focusRules ) {
      if ( !/outline\s*:/.test( body ) ) continue;
      expect( body, `${selector.trim()} sets an outline, so it must set a box-shadow too` )
        .toMatch( /box-shadow\s*:/ );
    }
  } );

  it( 'keeps the outline important, which is the only axis it can win on', () => {
    // form-controls.css declares a NON-important `outline: none` at (0,5,1). This rule is
    // (0,0,1). Importance is the only axis on which it can keep the 3px dark-green outline, so
    // the !important here is load-bearing rather than defensive.
    const css = styleText();
    const focus = /input\s*:\s*focus-visible\s*,\s*select\s*:\s*focus-visible\s*\{([^}]*)\}/.exec( css );
    expect( focus ).not.toBeNull();
    expect( focus?.[ 1 ] ).toMatch( /outline:\s*3px solid var\(--accent\)\s*!important/ );
  } );

  it( 'still marks an invalid field with its own border colour', () => {
    // Left alone on purpose: the aria-invalid rule is the server's answer landing on the right
    // input, and it is not geometry.
    expect( styleText() ).toMatch( /\[aria-invalid='true'\][^}]*border-color:\s*#8c1d18/ );
  } );

  it( 'keeps the state field autocompletable', () => {
    // autoComplete="address-level1" is an attribute, and this batch changes no attribute. The
    // assertion is here because the styled-jsx rewrite is in the same file, two lines away.
    const { container } = render( <AddressFields value={DRAFT} onChange={vi.fn()} /> );
    const select = container.querySelector( 'select' );
    expect( select ).not.toBeNull();
    expect( select?.getAttribute( 'autocomplete' ) ).toBe( 'address-level1' );
  } );
} );
