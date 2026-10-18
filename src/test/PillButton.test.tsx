import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import PillButton from '../components/PillButton';

/**
 * The two-segment pill, the home-page phone-number treatment turned reusable and applied to every
 * customer login CTA. jsdom cannot compute styled-jsx, so the colours and the pill radius are the
 * browser harness's job; here we pin the two properties that keep the login flow and its tests
 * working no matter how the pill looks:
 *
 *   1. THE ACCESSIBLE NAME. The visible pill is two words, but the control must answer to the ACTION
 *      alone - that is the name AccountSignIn.test / CartCheckout.test query ("Send code",
 *      "Confirm code", "Proceed to checkout"). A regression here breaks the login tests silently, so
 *      it is asserted directly: the name is the action, or the ariaLabel override when given, and the
 *      static label is NOT part of it.
 *   2. REAL CONTROL SEMANTICS. A submit button submits, a disabled pill does not fire onClick, and an
 *      as="a" pill is a link with an href - the pill is a style on a real control, never a div.
 *
 * Plus a source-level check that the measured contrast tokens are the ones actually in the file, so
 * the dark-green/mint pair the briefing signed off on cannot drift to a failing shade unnoticed.
 */

afterEach( () => vi.restoreAllMocks() );

/**
 * TWO CONTRACTS MET AT ONCE, and the history is worth recording because each looked complete on
 * its own.
 *
 * The ORIGINAL contract asserted the name was the ACTION ALONE and that the visible label must
 * NOT appear in it ("Send code", never "Sign in Send code"), achieved with `aria-hidden` on both
 * segments plus an `aria-label`. That hid a control's own visible label from its accessible name,
 * so a speech-input user saying "click Sign in" at that button got nothing. WCAG 2.5.3 Label in
 * Name is Level A and requires the opposite: the name must CONTAIN the visible text.
 *
 * Upstream fixed that by un-hiding both segments so the name became the platform's concatenation,
 * "Sign in Send code", and removed the `ariaLabel` override from the component entirely.
 *
 * THE OWNER THEN RETIRED THE TWO-TONE PILL (2026-10-02, "old multi colour out of date"), so there
 * is now ONE lime surface showing the ACTION only. That satisfies 2.5.3 by construction rather
 * than by repair: with a single visible string, the accessible name and the visible text are the
 * same string and cannot disagree. The `ariaLabel` removal is kept - it is what stops a caller
 * reopening the failure - and no segment is aria-hidden.
 */
describe( 'the accessible name is the visible pill text', () => {
  it( 'answers to its visible text, which is now the action alone', () => {
    render( <PillButton label="Sign in" action="Send code" /> );
    // The pinned login query form, and it survives both changes: the action was always the name,
    // and it is now also the only thing on screen.
    expect( screen.getByRole( 'button', { name: 'Send code' } ) ).toBeTruthy();
    // 2.5.3: the name contains the full visible text, because they are the same string.
    expect( screen.getByRole( 'button' ).textContent ).toBe( 'Send code' );
    // The retired dark half renders nothing, so there is no visible label left OUT of the name.
    expect( screen.queryByText( 'Sign in' ) ).toBeNull();
    expect( screen.getByText( 'Send code' ) ).toBeTruthy();
  } );

  it( 'names the cart pill by its visible text too, with no override available', () => {
    render( <PillButton label="Checkout" action="Proceed" /> );
    // The cart test queries this exact name. It used to be "Proceed to checkout", set by
    // ariaLabel - a name containing neither visible word in order.
    expect( screen.getByRole( 'button', { name: 'Proceed' } ) ).toBeTruthy();
    expect( screen.queryByRole( 'button', { name: 'Proceed to checkout' } ) ).toBeNull();
    expect( screen.getByText( 'Proceed' ) ).toBeTruthy();
  } );
} );

describe( 'it is a real control, not a styled div', () => {
  it( 'renders a submit button when asked, so it drives a form submit', () => {
    const onSubmit = vi.fn( ( e: React.FormEvent ) => e.preventDefault() );
    render(
      <form onSubmit={ onSubmit }>
        <PillButton label="Sign in" action="Send code" type="submit" />
      </form>,
    );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send code' } ) );
    expect( onSubmit ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'does not fire onClick while disabled, and marks aria-busy when busy', () => {
    const onClick = vi.fn();
    render(
      <PillButton label="Sign in" action="Sending…" onClick={ onClick } disabled busy />,
    );
    // The busy name follows the visible text, so it is the busy wording - not a frozen
    // "Send code" supplied by an override. That override is gone; see the docblock.
    const button = screen.getByRole( 'button', { name: 'Sending…' } );
    fireEvent.click( button );
    expect( onClick ).not.toHaveBeenCalled();
    expect( ( button as HTMLButtonElement ).disabled ).toBe( true );
    expect( button.getAttribute( 'aria-busy' ) ).toBe( 'true' );
  } );

  it( 'renders an anchor with an href when as="a"', () => {
    render( <PillButton as="a" href="/account/sign-in/" label="Sign in" action="Continue" /> );
    // Single lime surface: the action is the only visible text, so it is the whole name.
    const link = screen.getByRole( 'link', { name: 'Continue' } );
    expect( link.getAttribute( 'href' ) ).toBe( '/account/sign-in/' );
  } );
} );

describe( 'the measured palette is the one in the file', () => {
  const SOURCE = readFileSync(
    join( __dirname, '..', 'components', 'PillButton.tsx' ), 'utf8',
  );

  /** The DECLARATIONS only - comments are stripped, because this file's docblock discusses the
   *  retired mint by name and an un-stripped check would pass on the explanation. */
  const CSS = SOURCE.slice( SOURCE.indexOf( '<style jsx>' ) )
    .replace( /\/\*[\s\S]*?\*\//g, '' );

  it( 'is ONE lime #d1f470 surface with a dark-green edge, and no mint survives', () => {
    // #1a3a2a vs white is 12.48:1, so the 2px edge clears WCAG 1.4.11's 3:1 for a control
    // boundary - the lime cannot do that itself, at only 1.24:1 against the page.
    expect( CSS ).toContain( 'var(--public-brand-green)' );
    // THE SURFACE IS THE HOME PAGE'S LIME. #d1f470 with #1a3a2a text is 10.04:1.
    expect( CSS ).toContain( 'var(--public-brand-lime)' );
    // THE TWO-TONE TREATMENT IS RETIRED, on owner instruction 2026-10-02 ("old multi colour out of
    // date"). #5fe3b0 was an orphan colour - a repo-wide grep found it only in this component and
    // this test, and the home page uses #d1f470 eight times and the mint never. It must not return
    // as a declaration.
    expect( CSS ).not.toContain( '#5fe3b0' );
    // AND NEITHER MAY THE FAILING HOVER. #3da35a behind #1a3a2a 17px/700 text is 3.91:1, under the
    // 4.5:1 this size requires (WCAG's large-text exemption starts at 18.66px bold). The hover now
    // inverts to white, which gives 12.48:1.
    expect( CSS ).not.toContain( '#3da35a' );
    expect( CSS ).toMatch( /:hover[^{]*\{[^}]*background:#fff/ );
    // A full pill radius, scoped so the global 13px in button.css cannot flatten it.
    expect( CSS ).toContain( 'border-radius:var(--public-cta-radius)' );
    // Reduced motion is respected.
    expect( SOURCE ).toContain( 'prefers-reduced-motion' );
  } );

  /**
   * THE REGRESSION THAT SHIPPED TO PRODUCTION, and the reason this test exists.
   *
   * The two segments were once hoisted into a single `const inner = (<>...</>)` and referenced from
   * both the <a> and <button> branches. styled-jsx's transform only stamps its scoping hash class
   * onto JSX inside the same return tree as the <style jsx> element, so hoisted JSX was never
   * stamped: the built markup emitted `class="pill-label"` / `class="pill-action"` with NO hash,
   * while the rules compiled to `.pill-label.jsx-<hash>{...}`. Those selectors could not match.
   * The outer control WAS stamped, so the pill kept its shape, its 2px edge and its dark fill
   * while neither segment got its own background or colour - it rendered as one dark slab reading
   * "Sign inSend code". It was live on /account/sign-in/ in that state.
   *
   * STILL RELEVANT AFTER THE TWO-TONE RETIREMENT. The pill is now ONE lime surface with a single
   * .pill-action span, so there is one span per branch rather than two - but the hoisting hazard
   * is unchanged: lift that span into a variable and styled-jsx stops stamping it, and the label
   * loses its colour and centring exactly as both segments did before.
   *
   * jsdom cannot compute styled-jsx, so this is asserted on the SOURCE: the span must appear
   * exactly TWICE - once inside each branch's own return tree - and never be assigned to a
   * variable or produced by a helper.
   */
  it( 'writes the label span inline in each branch, so styled-jsx can scope it', () => {
    // COMMENTS ARE STRIPPED FIRST. The fix's own docblock quotes the broken pattern it replaced
    // ("const inner = ...") so that the next reader understands why the duplication below is
    // deliberate - asserting against the raw source would match that explanation and fail,
    // punishing the documentation rather than the defect. What must be absent is real CODE.
    const code = SOURCE
      .replace( /\/\*[\s\S]*?\*\//g, '' )
      .replace( /^\s*\/\/.*$/gm, '' );

    const actions = code.match( /className="pill-action"/g ) || [];
    // Twice: the <a> branch and the <button> branch each write their own.
    expect( actions ).toHaveLength( 2 );
    // The retired dark half must not come back as markup.
    expect( code ).not.toContain( 'className="pill-label"' );

    // NOT HOISTED. Any of these means the segments have been lifted out of the return tree again
    // and the scoping hash will silently stop being applied.
    expect( code ).not.toMatch( /const\s+inner\s*=/ );
    expect( code ).not.toMatch( /const\s+segments\s*=/ );
    expect( code ).not.toMatch( /function\s+renderSegments/ );
  } );

  /**
   * The same guard from the other side, and the single-surface contract.
   *
   * WHAT IS ON SCREEN IS NOW WHAT IS ANNOUNCED. The old control showed two words ("Sign in" +
   * "Send code") while answering only to the second, which is why the label had to be
   * aria-hidden. With one lime surface the visible text IS the accessible name, so the span is
   * no longer hidden from the accessibility tree - and `label` is accepted but not rendered.
   */
  it( 'renders the action as the only visible text and as the accessible name', () => {
    const { container } = render( <PillButton label="Collect" action="Send code" /> );
    const action = container.querySelector( '.pill-action' );
    expect( action?.textContent ).toBe( 'Send code' );
    // The retired dark half is gone, and the `label` prop is deliberately not rendered anywhere.
    expect( container.querySelector( '.pill-label' ) ).toBeNull();
    // Asserted on the CONTROL, not the container: container.textContent also includes the
    // <style jsx> CSS, whose explanatory comment names "Collect" as a former label - so a
    // container-wide check matches the documentation rather than the markup.
    expect( screen.getByRole( 'button' ).textContent ).toBe( 'Send code' );
    /*
     * NOT aria-hidden - UPSTREAM'S REQUIREMENT, KEPT. The span previously carried
     * aria-hidden="true" alongside an aria-label of the action, which hid the control's visible
     * label from its own name and broke WCAG 2.5.3 for speech input. With one surface the visible
     * text IS the name, so hiding it would make the control nameless rather than merely
     * mismatched. This assertion is what stops aria-hidden being reintroduced "for tidiness".
     */
    expect( action?.hasAttribute( 'aria-hidden' ) ).toBe( false );
    expect( screen.getByRole( 'button', { name: 'Send code' } ) ).toBeTruthy();
  } );
} );
