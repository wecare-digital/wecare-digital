import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Header from '../Header';

const routerState = vi.hoisted( () => ( { pathname: '/' } ) );
vi.mock( 'next/router', () => ( { useRouter: () => routerState } ) );

describe( 'Header', () => {
  it( 'shows the shared WECARE.DIGITAL brand', () => {
    render( <Header /> );
    expect( screen.getByText( /WECARE/ ) ).toBeInTheDocument();
    expect( screen.getByText( 'DIGITAL' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: /WECARE.DIGITAL home/i } ) ).toHaveAttribute( 'href', '/' );
  } );

  it( 'uses separate Home and Grahak OS routes', () => {
    routerState.pathname = '/';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Home' } ) ).toHaveAttribute( 'href', '/' );
    expect( screen.getByRole( 'link', { name: 'Home' } ) ).toHaveAttribute( 'aria-current', 'page' );
    expect( screen.getByRole( 'link', { name: 'Grahak OS' } ) ).toHaveAttribute( 'href', '/grahak-os/' );
    expect( screen.getByRole( 'link', { name: 'Grahak OS' } ) ).not.toHaveAttribute( 'aria-current' );
  } );

  it( 'marks Grahak OS active on its public route', () => {
    routerState.pathname = '/grahak-os';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Grahak OS' } ) ).toHaveAttribute( 'aria-current', 'page' );
  } );

  it( 'removes internal Sign in, and removes retired pages', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // SIGN IN IS GONE from the public menu, on owner instruction. The old row pointed at
    // [retired public path], the INTERNAL staff dashboard login (Cognito), which does not belong in
    // public navigation. A fresh customer login (WhatsApp OTP with SMS/email fallback)
    // will live on the /orders page instead. So there must be no "Sign in" link, and
    // no "Account" heading, anywhere in this menu.
    expect( screen.queryByRole( 'link', { name: 'Sign in' } ) ).toBeNull();
    expect( screen.queryByText( 'Account' ) ).toBeNull();

    // Contact now has its OWN heading ("Contact") with a single row labelled "Contact
    // us", both pointing at the real local /contact page. The link name is therefore
    // "Contact us"; assert that rather than the bare "Contact", which is now the group
    // heading, not a link. Studio and Sustainability are still retired and those guards stay.
    expect( screen.getByRole( 'link', { name: 'Contact us' } ) ).toHaveAttribute( 'href', '/contact/' );
    expect( screen.queryByText( 'Studio' ) ).toBeNull();
    expect( screen.queryByText( 'Sustainability' ) ).toBeNull();
  } );

  it( 'moves Bharat Rx to Products and drops FAQ entirely', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // FAQ has no entry point left anywhere: the local page was deleted earlier and
    // this row is now gone too.
    expect( screen.queryByRole( 'link', { name: 'FAQ' } ) ).toBeNull();

    // Bharat Rx is a product, not one of the request actions. Asserted by
    // column position, because the label alone would pass wherever it sat.
    const products = screen.getByText( 'Products' ).closest( '.nav-group' );
    expect( products ).not.toBeNull();
    expect( products?.textContent ).toContain( 'Bharat Rx' );

    // The group is 'Request' (singular), the exact customer-facing label the owner mandates in
    // Section 1 - renamed from 'Selfservice' -> 'Requests' -> 'Request'. Found by TEXT, not by
    // role=link: the heading is a plain group label, not a destination, so getByRole('link')
    // would throw here.
    const requests = screen.getByText( 'Request' ).closest( '.nav-group' );
    expect( requests ).not.toBeNull();
    expect( requests?.textContent ).not.toContain( 'Bharat Rx' );

    // And it must NOT be a link - that is the actual requirement, so assert it
    // rather than leaving it implied by the lookup above happening to work.
    expect( screen.queryByRole( 'link', { name: 'Request' } ) ).toBeNull();

    // The banned labels must never appear: Section 1 forbids 'Get Help', 'Customer-Service',
    // 'Selfservice' and 'Help Hub' as the customer-facing group label.
    expect( screen.queryByText( /Get Help/i ) ).toBeNull();
    expect( screen.queryByText( /Customer-Service/i ) ).toBeNull();
    expect( screen.queryByText( /Help Hub/i ) ).toBeNull();

    // The retired word must not come back anywhere in the menu. This is the guard for the
    // owner instruction, not a restatement of the rename: a new row or heading carrying
    // 'Selfservice' would name a destination that does not exist.
    expect( screen.queryByText( /Selfservice/i ) ).toBeNull();
  } );

  it( 'lists Terms and Privacy under a Legal Stuff heading', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    expect( screen.getByRole( 'link', { name: 'Terms' } ) ).toHaveAttribute( 'href', '/terms/' );

    // Privacy is linked now. It was deliberately unlinked while its text was a
    // placeholder, and the assertion here guarded that; the owner asked for it to be
    // listed once the real policy landed, so the guard is replaced rather than deleted.
    expect( screen.getByRole( 'link', { name: 'Privacy' } ) ).toHaveAttribute( 'href', '/privacy/' );

    // The heading matches the published document's own title.
    expect( screen.getByText( 'Legal Stuff' ) ).toBeInTheDocument();
    expect( screen.queryByText( /^Legal$/ ) ).toBeNull();

    // Legal Stuff now sits in the SAME column as "Refer & Earn" (the Work with us
    // column), not under the request actions where it used to be. Asserted by shared
    // column ancestor so a future reorder that splits them is caught.
    const legalCol = screen.getByText( 'Legal Stuff' ).closest( '.nav-col' );
    expect( legalCol ).not.toBeNull();
    expect( legalCol?.textContent ).toContain( 'Refer & Earn' );
    // And it is no longer beside the request actions. The group is now labelled 'Request'
    // (singular); this looks it up by that label.
    const requestsCol = screen.getByText( 'Request' ).closest( '.nav-col' );
    expect( requestsCol?.textContent ).not.toContain( 'Legal Stuff' );
  } );

  it( 'adds a Shipments row to the Request group, immediately above Leave Review', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // Shipments is a real public page under the Request group (Section 3). THE ROUTE IS
    // /shipments/ — the page was called "Zip" and the owner retired the name on 2026-10-02, so
    // the route moved from /zip/ along with the page file, the sitemap entry, the
    // PUBLIC_PAGE_META key and config/public-pages.json. The trailing slash is load-bearing
    // (trailingSlash is set, so /shipments would redirect before resolving).
    expect( screen.getByRole( 'link', { name: 'Shipments' } ) ).toHaveAttribute( 'href', '/shipments/' );
    // The retired route must not come back in the menu.
    expect( document.body.innerHTML ).not.toContain( '/zip' );

    // It lives in the Request group, not somewhere else.
    const request = screen.getByText( 'Request' ).closest( '.nav-group' );
    expect( request?.textContent ).toContain( 'Shipments' );

    // Order: Shipments sits immediately BEFORE Leave Review. Leave Review is no longer the last
    // item of the group: on owner instruction Subscribe now follows it (the order is Orders,
    // Submit Request, Request Amendment, Drop Docs, Vault, Shipments, Leave Review, Subscribe).
    const labels = Array.from( request?.querySelectorAll( '.nav-item' ) || [] )
      .map( node => node.textContent );
    expect( labels.indexOf( 'Shipments' ) ).toBe( labels.indexOf( 'Leave Review' ) - 1 );
    expect( labels.indexOf( 'Subscribe' ) ).toBe( labels.indexOf( 'Leave Review' ) + 1 );
    expect( labels.indexOf( 'Subscribe' ) ).toBe( labels.length - 1 );
    // Orders remains the first row in the group.
    expect( labels.indexOf( 'Orders' ) ).toBe( 0 );
  } );

  it( 'marks Shipments active on its public /shipments route', () => {
    routerState.pathname = '/shipments';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Shipments' } ) ).toHaveAttribute( 'aria-current', 'page' );
    routerState.pathname = '/';
  } );

  it( 'adds a Subscribe row to the Request group, directly after Leave Review and last', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // Subscribe is a real public page at /subscribe/. The trailing slash is load-bearing
    // (trailingSlash is set, so /subscribe would redirect before resolving).
    expect( screen.getByRole( 'link', { name: 'Subscribe' } ) ).toHaveAttribute( 'href', '/subscribe/' );

    // It lives in the Request group, and the whole group reads in this exact order. Pinning the
    // full list, not just the tail, so a reorder anywhere in the group is caught.
    const request = screen.getByText( 'Request' ).closest( '.nav-group' );
    expect( request?.textContent ).toContain( 'Subscribe' );
    const labels = Array.from( request?.querySelectorAll( '.nav-item' ) || [] )
      .map( node => node.textContent );
    expect( labels ).toEqual( [
      'Orders', 'Submit Request', 'Request Amendment', 'Drop Docs', 'Vault', 'Shipments',
      'Leave Review', 'Subscribe',
    ] );
  } );

  it( 'marks Subscribe active on its public /subscribe route', () => {
    routerState.pathname = '/subscribe';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Subscribe' } ) ).toHaveAttribute( 'aria-current', 'page' );
    routerState.pathname = '/';
  } );

  it( 'finds Subscribe through the navigation search', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    fireEvent.change( screen.getByLabelText( 'Search navigation' ), { target: { value: 'subscribe' } } );
    expect( screen.getByRole( 'link', { name: 'Subscribe' } ) ).toHaveAttribute( 'href', '/subscribe/' );
  } );

  it( 'adds an Extras group immediately above Legal Stuff', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // THE GROUP HEADING IS "Extras" (the category) AND THE ROW IS "Perks" (the page's own name).
    // This pairing is the fix for a reported bug: the row ALSO read "Extras", so the menu printed
    // the same word twice, one directly beneath the other. An earlier instruction had renamed the
    // page Perks -> Extras; the owner reversed that on 2026-10-02. The ROUTE stays /perks/ — it
    // already matches the name, so nothing to rename there.
    //
    // The group was collapsed from three ANCHOR rows (Gift Cards -> /perks/#gift-cards, Rewards ->
    // /perks/#rewards, Offers -> /perks/#offers) to a single link to the /perks/ page, because the
    // owner removed those gift-card / offers / rewards sections and their anchors from the page.
    // Nothing in the menu may still point at a removed anchor.
    const perksLink = screen.getByRole( 'link', { name: 'Perks' } );
    expect( perksLink ).toHaveAttribute( 'href', '/perks/' );
    // THE DUPLICATION GUARD: "Extras" is the heading only, never a link row. If a row labelled
    // "Extras" reappears, the word is being printed twice again and this fails.
    expect( screen.queryByRole( 'link', { name: 'Extras' } ) ).toBeNull();

    // The old anchor rows and their dead targets are gone.
    expect( screen.queryByRole( 'link', { name: 'Gift Cards' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Rewards' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Offers' } ) ).toBeNull();
    const menuHtml = document.body.innerHTML;
    expect( menuHtml ).not.toContain( '/perks/#gift-cards' );
    expect( menuHtml ).not.toContain( '/perks/#rewards' );
    expect( menuHtml ).not.toContain( '/perks/#offers' );

    // Extras sits in the SAME column as Legal Stuff, and immediately above it: the Extras group
    // node precedes the Legal Stuff group node among that column's groups.
    const perksCol = perksLink.closest( '.nav-col' );
    expect( perksCol?.textContent ).toContain( 'Legal Stuff' );
    const groups = Array.from( perksCol?.querySelectorAll( '.nav-group' ) || [] );
    const perksIndex = groups.findIndex( g => g.textContent?.startsWith( 'Extras' ) );
    const legalIndex = groups.findIndex( g => g.textContent?.startsWith( 'Legal Stuff' ) );
    expect( perksIndex ).toBeGreaterThanOrEqual( 0 );
    expect( legalIndex ).toBe( perksIndex + 1 );

    // No third-party gift-card provider name may appear in the menu.
    expect( screen.queryByText( /Gift ?Up/i ) ).toBeNull();
  } );

  it( 'uses the approved public header dimensions and brand navigation colors', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

    expect( css ).toContain( 'box-sizing:border-box;height:108px' );
    expect( css ).toContain( '@media(max-width:767px){.hdr-in{height:96px' );

    /*
     * THE TRIGGER'S ACTIVE STATE INVERTS NOW. This asserted
     *   .nav-trigger[aria-expanded='true']{background:rgba(209,244,112,.22)}
     * and that value is exactly what was wrong with it. Over the white header that tint
     * composites to rgb(245,253,224), which measures 1.032:1 against the chip's own #f4f7ee - an
     * RGB move of 15 out of a possible 441. The test was pinning a state change that was not
     * perceptible, which is how it survived a report of "no hover effect".
     *
     * Lime cannot carry it as a FILL either: lime is a LIGHT colour, so measured against #f4f7ee
     * the solid #d1f470 still only reaches 1.15:1. That measurement has not changed and is why
     * the state is never a lime tint.
     *
     * WHAT DID CHANGE, AND WHY THIS NO LONGER PINS #1a3a2a AS THE FILL. The first fix inverted
     * the whole chip, and the owner reported the result as "on select too much green" - filling
     * all 2116px² of a 46x46 chip with dark green made this the heaviest element in a header
     * that otherwise holds a wordmark and some text. Correct about the measurement, wrong about
     * the mass.
     *
     * So the luminance step moved to the EDGE and the fill was freed to be lime. #1a3a2a against
     * the resting #cfe0a6 border is 8.84:1, at 2px; dark area falls to 352px², 16.6% of what the
     * inversion painted. Three signals now carry "open" - the border darkens, the fill brightens,
     * and the chevron rotates - so the hue-only objection to a lime fill is answered by the two
     * that are not hue. The five options and their computed numbers are in
     * docs/menu-icon-options.md; this is G4.
     *
     * Asserted as one rule covering all three states, because the original defect was partly
     * that they were separate declarations drifting apart.
     */
    expect( css ).toContain( ".nav-trigger:hover,.nav-trigger:focus-visible,.nav-trigger[aria-expanded='true']" );
    expect( css ).toContain( 'background:#d1f470;border-color:#1a3a2a;border-width:2px' );
    // The dark fill is GONE as a declaration, not merely overridden. Comments stripped first:
    // the rule above cites #1a3a2a as the border colour and documents the fill it replaced, and
    // a substring search cannot tell a citation from a declaration.
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( 'background:#1a3a2a' );
    // border-width is transitioned, or the 1px -> 2px step snaps while the colours glide.
    expect( css ).toContain( 'border-width .18s ease' );

    /*
     * THE FOCUS RING IS TWO-TONE, AND BOTH STOPS ARE LOAD-BEARING.
     *
     * It was a single box-shadow at rgba(26,58,42,.2), which composites to rgb(200,209,199)
     * over the header and measures 1.44:1 against it - under the 3:1 WCAG 1.4.11 asks of a
     * focus indicator. The rule above also sets outline:none, so that faint shadow was the
     * entire ring.
     *
     * Opaque #1a3a2a on its own did not fix it when the chip inverted, and the two-tone ring is
     * kept now that the chip goes LIME rather than dark - because it has to work against both.
     * A dark green ring drawn tight against a lime chip does have an edge, so the white spacer is
     * less critical than it was; but the same pair is what makes the ring survive whichever fill
     * this control ends up with, which is exactly the durability that earned it. The 3px of dark
     * green outside measures 12.48:1 against the white header.
     *
     * Do not collapse this to one stop in either direction.
     */
    expect( css ).toContain( '.nav-trigger:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}' );
    // Comments stripped before the negative check: the rule above documents the value it
    // replaced, and a substring search cannot tell a citation from a declaration. Banning
    // the string outright would mean deleting the measurement that justifies the fix.
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( 'rgba(26,58,42,.2)' );
    // THE CHEVRON NO LONGER RECOLOURS, and the absence is asserted. It had to flip to lime when
    // the chip went dark underneath it; on a lime chip the same #1a3a2a glyph is 10.04:1, so the
    // rule is deleted rather than left setting a colour to the colour it already has.
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) )
      .not.toContain( 'border-right-color:#d1f470' );

    // The dropdown control is a CSS-drawn chevron, not a text triangle. The old
    // literal glyph rendered nothing but a font character, so its shape and
    // weight varied by platform; two borders on a rotated box do not.
    const trigger = container.querySelector( 'button' );
    const arrow = container.querySelector( 'button span' );
    expect( trigger?.textContent ).toBe( '' );
    expect( container.textContent ).not.toContain( '▼' );
    expect( arrow ).not.toBeNull();
    expect( arrow?.getAttribute( 'aria-hidden' ) ).toBe( 'true' );

    // Drawn with two 3px WECARE.DIGITAL dark-green borders on an 8px border-box, rotated 45deg,
    // at full opacity. margin:0 defeats the global .nav-arrow{margin-left:auto} in Layout.css,
    // which would otherwise push it off centre.
    //
    // 3px, NOT 2.5px, AND THE FRACTION IS THE WHOLE POINT. This previously asserted 2.5px, with
    // a comment saying the strokes had been bumped from 2px so the chevron would stop reading as
    // a hairline. Measured on the built page at devicePixelRatio 1,
    // getComputedStyle('.nav-arrow').borderRightWidth was 2px: a 2.5px border rounds down on a
    // 1x display, so the thickening existed in the stylesheet and nowhere else, and the test
    // pinned it as though it had worked. That is the same defect as the imperceptible hover tint
    // above - an assertion on a declared value that never reached a pixel.
    //
    // A whole 3px cannot be rounded away, which is why the fix is not another fraction. The
    // .85 opacity is gone too: it was softening the one element that carries the meaning.
    expect( css ).toContain( '.nav-arrow{width:8px;height:8px;box-sizing:border-box;margin:0' );
    expect( css ).toContain( 'border-right:3px solid #1a3a2a' );
    expect( css ).toContain( 'border-bottom:3px solid #1a3a2a' );
    expect( css ).toContain( 'opacity:1;transform:translateY(-2px) rotate(45deg)' );
    // No fractional stroke anywhere on this glyph, or the rounding trap comes back.
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( '2.5px solid' );
    expect( css ).toContain( 'transform:translateY(-2px) rotate(45deg)' );

    // Open state is an exact 180deg flip of the shape (45 -> 225), on the same
    // restrained .2s transition, still keyed off aria-expanded.
    expect( css ).toContain( ".nav-trigger[aria-expanded='true'] .nav-arrow{transform:translateY(2px) rotate(225deg)}" );
    expect( css ).toContain( 'transition:transform .2s' );
  } );
} );
