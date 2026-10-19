import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Header from '../Header';
import { REVIEW_ENTRY_URL } from '../../lib/reviewEntry';

const routerState = vi.hoisted( () => ( { pathname: '/', asPath: '' } ) );
vi.mock( 'next/router', () => ( { useRouter: () => routerState } ) );

const browserOpen = vi.hoisted( () => vi.fn( async ( _options: { url: string } ) => undefined ) );
vi.mock( '@capacitor/browser', () => ( { Browser: { open: browserOpen } } ) );

describe( 'Header', () => {
  it( 'shows the shared WECARE.DIGITAL brand', () => {
    render( <Header /> );
    expect( screen.getByText( /WECARE/ ) ).toBeInTheDocument();
    expect( screen.getByText( 'DIGITAL' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: /WECARE.DIGITAL home/i } ) ).toHaveAttribute( 'href', '/' );
  } );

  it( 'links the navigation trigger to its controlled menu for assistive technology', () => {
    render( <Header /> );
    const trigger = screen.getByRole( 'button', { name: 'Open navigation' } );
    expect( trigger ).toHaveAttribute( 'aria-controls', 'public-navigation-menu' );
    fireEvent.click( trigger );
    const menu = screen.getByRole( 'navigation', { name: 'Public navigation' } );
    expect( menu ).toHaveAttribute( 'id', 'public-navigation-menu' );
  } );

  it( 'opens external menu destinations through Capacitor Browser in a native app shell', async () => {
    const nativeWindow = window as typeof window & { Capacitor?: { isNativePlatform?: () => boolean } };
    nativeWindow.Capacitor = { isNativePlatform: () => true };
    browserOpen.mockClear();

    try {
      render( <Header /> );
      fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
      fireEvent.click( screen.getByRole( 'link', { name: 'Subscribe' } ) );

      await waitFor( () => expect( browserOpen ).toHaveBeenCalledTimes( 1 ) );
      expect( browserOpen.mock.calls[ 0 ]?.[ 0 ] ).toEqual( { url: expect.any( String ) } );
      expect( screen.getByRole( 'button', { name: 'Open navigation' } ) ).toHaveAttribute( 'aria-expanded', 'false' );
    } finally {
      delete nativeWindow.Capacitor;
    }
  } );

  it( 'restores Home and makes Shop itself the catalogue destination', () => {
    routerState.pathname = '/';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    expect( screen.getByRole( 'link', { name: 'Home' } ) ).toHaveAttribute( 'href', '/' );
    expect( screen.getByRole( 'link', { name: 'Home' } ) ).toHaveAttribute( 'aria-current', 'page' );
    expect( screen.getByRole( 'link', { name: 'Shop' } ) ).toHaveAttribute( 'href', '/shop/' );
    expect( screen.queryByRole( 'link', { name: 'Browse All' } ) ).toBeNull();
  } );

  it( 'selects only Shop on the /shop route', () => {
    routerState.pathname = '/shop';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const selected = screen.getAllByRole( 'link' ).filter( link => link.getAttribute( 'aria-current' ) === 'page' );
    expect( selected.map( link => link.textContent ) ).toEqual( [ 'Shop' ] );
    routerState.pathname = '/';
  } );

  it( 'marks Grahak OS active on its public route', () => {
    routerState.pathname = '/grahak-os';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Grahak OS' } ) ).toHaveAttribute( 'aria-current', 'page' );
  } );

  it( 'renders the agreed product hierarchy without 1-of-2 headings', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const products = screen.getByText( 'Products' ).closest( '.nav-group' );
    expect( products ).not.toBeNull();
    for ( const label of [
      'Grahak OS', 'VayuLok', 'Bharat Rx', 'Elsewhere', 'Visa', 'Trip', 'Activities',
      'Expo Week', 'Dastavez', 'Drafting', 'Registration', 'Legal Reference',
      'Clear Closure', 'Guided Resolution', 'Case Submission', 'Paperwork',
      'Ritual Guru', 'Puja Guidance', 'DIY Puja Kit', 'Anew', 'Hunar', 'Kaushal', 'Prastuti', 'Niji Setu',
    ] ) expect( products?.textContent ).toContain( label );

    expect( screen.queryByText( 'Products 1 of 2' ) ).toBeNull();
    expect( screen.queryByText( 'Products 2 of 2' ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Elsewhere' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Dastavez' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Clear Closure' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Ritual Guru' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Hunar' } ) ).toBeNull();

    expect( screen.getByRole( 'link', { name: 'Visa' } ) ).toHaveAttribute( 'href', '/elsewhere/visa/' );
    expect( screen.getByRole( 'link', { name: 'Trip' } ) ).toHaveAttribute( 'href', '/elsewhere/trip/' );
    expect( screen.getByRole( 'link', { name: 'Activities' } ) ).toHaveAttribute( 'href', '/elsewhere/activities/' );
    expect( screen.getByRole( 'link', { name: 'Kaushal' } ) ).toHaveAttribute( 'href', '/hunar/kaushal/' );
    expect( screen.getByRole( 'link', { name: 'Prastuti' } ) ).toHaveAttribute( 'href', '/hunar/prastuti/' );
  } );

  it( 'keeps Request rows in the approved order', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    const request = screen.getByText( 'Request' ).closest( '.nav-group' );
    expect( Array.from( request?.querySelectorAll( '.nav-item' ) || [] ).map( n => n.textContent ) )
      .toEqual( [ 'Orders', 'Submit Request', 'Request Amendment', 'Drop Docs', 'Vault', 'Shipments', 'Track', 'Pickup Request', 'Leave Review', 'Subscribe' ] );
    expect( screen.getByRole( 'link', { name: 'Leave Review' } ) ).toHaveAttribute( 'href', REVIEW_ENTRY_URL );
  } );

  it( 'keeps Blog published but hides it from public navigation and navigation search', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const extras = screen.getByText( 'Extras' ).closest( '.nav-group' );
    expect( extras ).not.toBeNull();
    expect( extras?.textContent ).toContain( 'Perks' );
    expect( extras?.textContent ).toContain( 'Google Play' );
    expect( extras?.textContent ).toContain( 'App Store' );
    expect( extras?.textContent ).not.toContain( 'Blog' );
    expect( screen.queryByRole( 'link', { name: 'Blog' } ) ).toBeNull();

    const perks = screen.getByRole( 'link', { name: 'Perks' } );
    const googlePlay = screen.getByRole( 'link', { name: 'Google Play' } );
    const appStore = screen.getByRole( 'link', { name: 'App Store' } );

    expect( perks ).toHaveAttribute( 'href', 'https://wa.me/message/377GALDW4E26F1' );
    expect( googlePlay ).toHaveAttribute( 'href', 'https://wecare.digital/' );
    expect( appStore ).toHaveAttribute( 'href', 'https://wecare.digital/' );

    for ( const link of [ googlePlay, appStore ] ) {
      const icon = link.querySelector( 'svg.nav-row-icon' );
      expect( icon ).toHaveClass( 'nav-row-icon-material' );
      expect( icon ).toHaveAttribute( 'viewBox', '0 -960 960 960' );
    }

    for ( const link of [ perks, googlePlay, appStore ] ) expect( link ).toHaveClass( 'nav-item' );
    expect( Array.from( extras?.querySelectorAll( 'a.nav-item' ) || [] ).map( link => link.textContent ) )
      .toEqual( [ 'Perks', 'Google Play', 'App Store' ] );
    expect( extras?.querySelectorAll( '.nav-row-chevron' ) ).toHaveLength( 0 );

    const search = screen.getByLabelText( 'Search navigation' );
    fireEvent.change( search, { target: { value: 'blog' } } );
    expect( screen.queryByRole( 'link', { name: 'Blog' } ) ).toBeNull();

    fireEvent.change( search, { target: { value: 'android' } } );
    expect( screen.getByRole( 'link', { name: 'Google Play' } ) ).toHaveAttribute( 'href', 'https://wecare.digital/' );

    fireEvent.change( search, { target: { value: 'iphone' } } );
    expect( screen.getByRole( 'link', { name: 'App Store' } ) ).toHaveAttribute( 'href', 'https://wecare.digital/' );
  } );

  it( 'uses menu-only search and family names find their real child destinations', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    const search = screen.getByLabelText( 'Search navigation' );

    fireEvent.change( search, { target: { value: 'elsewhere' } } );
    expect( screen.getByRole( 'link', { name: 'Visa' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Trip' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Activities' } ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'link', { name: 'Elsewhere' } ) ).toBeNull();

    fireEvent.change( search, { target: { value: 'dastavez' } } );
    expect( screen.queryByRole( 'link', { name: 'Dastavez' } ) ).toBeNull();
    expect( screen.getByRole( 'link', { name: 'Drafting' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Registration' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Legal Reference' } ) ).toBeInTheDocument();
  } );

  it( 'allows only one active destination for a child route', () => {
    routerState.pathname = '/dastavez/drafting';
    routerState.asPath = '/dastavez/drafting/';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const selected = screen.getAllByRole( 'link' ).filter( link => link.getAttribute( 'aria-current' ) === 'page' );
    expect( selected.map( link => link.textContent ) ).toEqual( [ 'Drafting' ] );
    expect( screen.queryByRole( 'link', { name: 'Dastavez' } ) ).toBeNull();
    routerState.pathname = '/';
    routerState.asPath = '';
  } );

  it.each( [
    [ '/shop/guided-resolution/', 'Guided Resolution' ],
    [ '/shop/file-assist/', 'Case Submission' ],
    [ '/shop/paperwork/', 'Paperwork' ],
  ] )( 'selects only the concrete Clear Closure child on %s', ( asPath, label ) => {
    routerState.pathname = '/shop/[slug]';
    routerState.asPath = asPath;
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const selected = screen.getAllByRole( 'link' ).filter( link => link.getAttribute( 'aria-current' ) === 'page' );
    expect( selected.map( link => link.textContent ) ).toEqual( [ label ] );
    expect( screen.queryByRole( 'link', { name: 'Clear Closure' } ) ).toBeNull();
    routerState.pathname = '/';
    routerState.asPath = '';
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

  it( 'groups Track and Pickup Request under a non-clickable Shipments family', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const request = screen.getByText( 'Request' ).closest( '.nav-group' );
    expect( request?.textContent ).toContain( 'Shipments' );
    expect( screen.queryByRole( 'link', { name: 'Shipments' } ) ).toBeNull();
    expect( screen.getByRole( 'link', { name: 'Track' } ) ).toHaveAttribute( 'href', '/shipments/track/' );
    expect( screen.getByRole( 'link', { name: 'Pickup Request' } ) ).toHaveAttribute( 'href', '/request-pickup/' );

    const labels = Array.from( request?.querySelectorAll( '.nav-item' ) || [] ).map( node => node.textContent );
    expect( labels ).toEqual( [
      'Orders', 'Submit Request', 'Request Amendment', 'Drop Docs', 'Vault',
      'Shipments', 'Track', 'Pickup Request', 'Leave Review', 'Subscribe',
    ] );
  } );

  it( 'searching Shipments returns its real destinations, not a dead family link', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    fireEvent.change( screen.getByLabelText( 'Search navigation' ), { target: { value: 'shipments' } } );

    expect( screen.getByRole( 'link', { name: 'Track' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Pickup Request' } ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'link', { name: 'Shipments' } ) ).toBeNull();
  } );

  it( 'selects Track and Pickup Request independently', () => {
    routerState.pathname = '/shipments/track';
    routerState.asPath = '/shipments/track/';
    const first = render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Track' } ) ).toHaveAttribute( 'aria-current', 'page' );
    expect( screen.getByRole( 'link', { name: 'Pickup Request' } ) ).not.toHaveAttribute( 'aria-current' );
    first.unmount();

    routerState.pathname = '/request-pickup';
    routerState.asPath = '/request-pickup/';
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Pickup Request' } ) ).toHaveAttribute( 'aria-current', 'page' );
    expect( screen.getByRole( 'link', { name: 'Track' } ) ).not.toHaveAttribute( 'aria-current' );
    routerState.pathname = '/';
    routerState.asPath = '';
  } );

  it( 'exposes Subscribe as the verified direct WhatsApp action, never as a website route', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    expect( screen.getByRole( 'link', { name: 'Subscribe' } ) )
      .toHaveAttribute( 'href', 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( document.body.innerHTML ).not.toContain( '/subscribe/' );
    fireEvent.change( screen.getByLabelText( 'Search navigation' ), { target: { value: 'subscribe' } } );
    expect( screen.getByRole( 'link', { name: 'Subscribe' } ) )
      .toHaveAttribute( 'href', 'https://wa.me/message/WUDPTMYSO6XII1' );
  } );

  it( 'keeps Refer & Earn and Partner non-clickable while their destinations remain searchable', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    expect( screen.queryByRole( 'link', { name: 'Refer & Earn' } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: 'Partner' } ) ).toBeNull();
    const partner = screen.getByText( 'Partner' ).closest( '.nav-tree-item' );
    const partnerLabels = Array.from( partner?.querySelectorAll( '.nav-item' ) || [] ).map( node => node.textContent );
    expect( partnerLabels ).toEqual( [ 'Partner', 'Referral', 'Merchandise', 'Kiosk' ] );
    expect( screen.getByRole( 'link', { name: 'Referral' } ) ).toHaveAttribute( 'href', 'https://wa.me/message/S6A2QEXZSYXTG1' );
    expect( screen.getByRole( 'link', { name: 'Merchandise' } ) ).toHaveAttribute( 'href', '/shop/merchandise/' );
    expect( screen.getByRole( 'link', { name: 'Kiosk' } ) ).toHaveAttribute( 'href', '/shop/kiosk/' );

    fireEvent.change( screen.getByLabelText( 'Search navigation' ), { target: { value: 'partner' } } );
    expect( screen.getByRole( 'link', { name: 'Merchandise' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Kiosk' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Referral' } ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'link', { name: 'Partner' } ) ).toBeNull();
  } );

  it( 'places Puja Guidance above DIY Puja Kit', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    const ritual = screen.getByText( 'Ritual Guru' ).closest( '.nav-tree-item' );
    const labels = Array.from( ritual?.querySelectorAll( '.nav-item' ) || [] ).map( node => node.textContent );
    expect( labels ).toEqual( [ 'Ritual Guru', 'Puja Guidance', 'DIY Puja Kit', 'Ritva' ] );
  } );

  it( 'keeps keyboard access standard and adds no close button', () => {
    render( <Header /> );
    const trigger = screen.getByRole( 'button', { name: 'Open navigation' } );
    expect( trigger ).toHaveAttribute( 'aria-keyshortcuts', 'Enter Space Escape' );
    fireEvent.click( trigger );
    expect( screen.queryByRole( 'button', { name: /close/i } ) ).toBeNull();
  } );

  it( 'keeps the thin animated row divider after tree wrapping', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( ".nav-item::before{content:''" );
    expect( css ).toContain( 'transition:transform .22s cubic-bezier(.16,1,.3,1),opacity .14s ease' );
    expect( css ).toContain( '.nav-tree-item:last-child > .nav-item:last-child::after{display:none}' );
    expect( css ).toContain( 'background:linear-gradient(90deg,transparent 0,#e5eadc 12%,#e5eadc 88%,transparent 100%)' );
  } );

  it( 'keeps Extras above Contact and Legal Stuff', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    // Extras remains the category heading; Perks is its WhatsApp action row.

    // Approved order in this column is Refer & Earn, Extras, Contact, Legal Stuff.
    const extrasCol = screen.getByText( 'Extras' ).closest( '.nav-col' );
    expect( extrasCol?.textContent ).toContain( 'Contact' );
    expect( extrasCol?.textContent ).toContain( 'Legal Stuff' );
    const groups = Array.from( extrasCol?.querySelectorAll<HTMLElement>( '.nav-group' ) ?? [] );
    const contactIndex = groups.findIndex( g => g.textContent?.startsWith( 'Contact' ) );
    const perksIndex = groups.findIndex( g => g.textContent?.startsWith( 'Extras' ) );
    const legalIndex = groups.findIndex( g => g.textContent?.startsWith( 'Legal Stuff' ) );
    expect( perksIndex ).toBeGreaterThanOrEqual( 0 );
    expect( contactIndex ).toBe( perksIndex + 1 );
    expect( legalIndex ).toBe( contactIndex + 1 );

    // No third-party gift-card provider name may appear in the menu.
    expect( screen.queryByText( /Gift ?Up/i ) ).toBeNull();
  } );

  it( 'keeps parent and child navigation on the same 19px/600 type rung', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    const navItemRule = css.match( /\.nav-item\{[^}]*\}/ )?.[ 0 ] || '';
    expect( navItemRule ).toContain( 'min-height:46px' );
    expect( navItemRule ).toContain( 'font-size:19px' );
    expect( navItemRule ).toContain( 'font-weight:600' );
    const navChildRule = css.match( /\.nav-child\{[^}]*\}/ )?.[ 0 ] || '';
    expect( navChildRule ).toContain( 'font-size:19px' );
    expect( navChildRule ).toContain( 'font-weight:600' );
    expect( navChildRule ).toContain( 'min-height:46px' );
    expect( css ).not.toContain( '.nav-sub{font-size:17px' );
  } );

  it( 'announces menu search result counts to assistive technology', () => {
    render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
    fireEvent.change( screen.getByLabelText( 'Search navigation' ), { target: { value: 'elsewhere' } } );
    expect( screen.getByRole( 'status' ) ).toHaveTextContent( '3 menu results.' );
  } );

  it( 'uses measured desktop menu width plus vh fallback, dynamic viewport sizing and native safe-area insets', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( 'width:min(760px,var(--nav-menu-available-width,760px))' );
    const cssWithoutComments = css.replace( /\/\*[\s\S]*?\*\//g, '' );
    expect( cssWithoutComments ).not.toContain( 'calc(100vw - 256px)' );
    expect( css ).toContain( 'max-height:calc(100vh - 140px)' );
    // The safe-area insets now reference the single --safe-* token contract (src/styles/tokens.css,
    // unified-mobile Phase 1) rather than repeating the raw env(safe-area-inset-*) literal. The
    // tokens are defined as exactly env(safe-area-inset-*), so the resolved value is identical; the
    // max(16px, ...) guards on the mobile panel are preserved.
    expect( css ).toContain( 'max-height:calc(100dvh - 140px - var(--safe-bottom))' );
    expect( css ).toContain( 'max(16px,var(--safe-left))' );
    expect( css ).toContain( 'max(16px,var(--safe-right))' );
    expect( css ).toContain( 'touch-action:pan-y' );
  } );

  it( 'keeps desktop Products capped but removes nested product scrolling on mobile', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( 'max-height:230px;' );
    expect( css ).toContain( '.nav-products-scroll{max-height:none;overflow:visible;overscroll-behavior:auto' );
  } );

  it( 'uses the approved Material icon set for the refreshed menu items', () => {
    const { container } = render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    const expected = [
      [ 'VayuLok', 'M460-160q-50 0-85-35t-35-85h80' ],
      [ 'Bharat Rx', 'M345-120q-94 0-159.5-65.5T120-345' ],
      [ 'Niji Setu', 'M440-280H280q-83 0-141.5-58.5T80-480' ],
      [ 'Submit Request', 'M200-120q-33 0-56.5-23.5T120-200' ],
      [ 'Vault', 'M480-320 280-520l56-58 104 104' ],
    ] as const;

    for ( const [ label, prefix ] of expected ) {
      const icon = screen.getByRole( 'link', { name: label } ).querySelector( 'svg.nav-row-icon-material path' );
      expect( icon?.getAttribute( 'd' ) ).toContain( prefix );
    }

    const hunar = screen.getByText( 'Hunar' ).closest( '.nav-family-label' );
    const hunarIcon = hunar?.querySelector( 'svg.nav-row-icon-material path' );
    expect( hunarIcon?.getAttribute( 'd' ) ).toContain( 'm387-412 35-114-92-74h114' );
    expect( screen.queryByRole( 'link', { name: 'Hunar' } ) ).toBeNull();

    const referHeading = screen.getByText( 'Refer & Earn' );
    const referIcon = referHeading.parentElement?.querySelector( 'svg.nav-section-icon-material path' );
    expect( referIcon?.getAttribute( 'd' ) ).toContain( 'M720-80q-50 0-85-35t-35-85' );

    const partner = screen.getByText( 'Partner' ).closest( '.nav-family-label' );
    const partnerIcon = partner?.querySelector( 'svg.nav-row-icon-material path' );
    expect( partnerIcon?.getAttribute( 'd' ) ).toContain( 'M160-80q-33 0-56.5-23.5T80-160' );

    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( '.nav-row-icon-material{fill:currentColor;stroke:none}' );
    expect( css ).toContain( '.nav-section-icon-material{fill:currentColor;stroke:none}' );
  } );

  it( 'adds visual icons without changing the navigation schema or labels', () => {
    const { container } = render( <Header /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );

    expect( screen.getByRole( 'link', { name: 'Shop' } ).querySelector( '.nav-row-icon' ) ).not.toBeNull();
    const productsGroup = screen.getByText( 'Products' ).closest( '.nav-group' );
    expect( productsGroup?.querySelector( '.nav-group-label .nav-section-icon' ) ).not.toBeNull();
    expect( screen.getByText( 'Elsewhere' ).parentElement?.querySelector( '.nav-row-chevron' ) ).not.toBeNull();
    expect( screen.getByRole( 'link', { name: 'Visa' } ).querySelector( '.nav-sub-icon' ) ).not.toBeNull();

    expect( screen.getByRole( 'link', { name: 'Shop' } ) ).toHaveAttribute( 'href', '/shop/' );
    expect( screen.getByRole( 'link', { name: 'Visa' } ) ).toHaveAttribute( 'href', '/elsewhere/visa/' );

    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( '.nav-row-icon{width:20px;height:20px' );
    expect( css ).toContain( '.nav-sub-icon{width:17px;height:17px' );
    expect( css ).toContain( '.nav-row-chevron{width:17px;height:17px' );
  } );

  it( 'right-aligns the Products continuation cue and uses the Google double-arrow icon', () => {
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

    expect( css ).toContain( '.nav-products-cue-row{height:46px;display:flex;align-items:center;justify-content:flex-end;flex:0 0 46px;margin-top:6px;padding-inline-end:4px' );
    expect( css ).toContain( '.nav-products-more{display:flex;align-items:center;justify-content:center;width:46px;height:46px' );
    expect( css ).toContain( 'border-radius:50%;background:var(--public-brand-lime);color:#0f2a1d' );
    expect( css ).toContain( '.nav-products-more:hover{background:#c5ed51;transform:translateY(-1px) scale(1.06)' );
    expect( css ).toContain( '.nav-products-more-icon{display:block;width:31px;height:31px;fill:currentColor' );
    expect( css ).toContain( '.nav-products-cue-row{display:none}' );
    expect( css ).not.toContain( '.nav-products-more{position:absolute' );
    expect( css ).not.toContain( 'More products' );

    const matchMedia = vi.spyOn( window, 'matchMedia' ).mockImplementation( query => ( {
      media: query,
      matches: query.includes( 'min-width: 768px' ),
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    } as unknown as MediaQueryList ) );

    const scrollHeight = Object.getOwnPropertyDescriptor( HTMLElement.prototype, 'scrollHeight' );
    const clientHeight = Object.getOwnPropertyDescriptor( HTMLElement.prototype, 'clientHeight' );
    Object.defineProperty( HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get () { return this.classList?.contains( 'nav-products-scroll' ) ? 500 : 0; },
    } );
    Object.defineProperty( HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get () { return this.classList?.contains( 'nav-products-scroll' ) ? 230 : 0; },
    } );

    try {
      fireEvent.click( screen.getByRole( 'button', { name: 'Open navigation' } ) );
      const cue = screen.getByRole( 'button', { name: 'Scroll to more products' } );
      expect( cue.textContent ).toBe( '' );
      expect( cue.querySelector( 'svg.nav-products-more-icon path' )?.getAttribute( 'd' ) )
        .toContain( 'M480-200 240-440l42-42 198 198' );
    } finally {
      matchMedia.mockRestore();
      if ( scrollHeight ) Object.defineProperty( HTMLElement.prototype, 'scrollHeight', scrollHeight );
      else Reflect.deleteProperty( HTMLElement.prototype, 'scrollHeight' );
      if ( clientHeight ) Object.defineProperty( HTMLElement.prototype, 'clientHeight', clientHeight );
      else Reflect.deleteProperty( HTMLElement.prototype, 'clientHeight' );
    }
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
    expect( css ).toContain( 'background:var(--public-brand-lime);outline:none' );
    // The dark fill is GONE as a declaration, not merely overridden. Comments stripped first:
    // the rule above cites #1a3a2a as the border colour and documents the fill it replaced, and
    // a substring search cannot tell a citation from a declaration.
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( 'background:#1a3a2a' );
    // The trigger is borderless in every visual state; only its background animates.
    expect( css ).not.toContain( 'border-width .18s ease' );

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

    // The main dropdown control now uses the Google Material keyboard_arrow_down glyph.
    const trigger = screen.getByRole( 'button', { name: 'Open navigation' } );
    const triggerIcon = trigger.querySelector( 'svg.nav-trigger-icon' );
    expect( triggerIcon ).not.toBeNull();
    expect( triggerIcon?.textContent ).toBe( '' );
    expect( triggerIcon?.getAttribute( 'aria-hidden' ) ).toBe( 'true' );
    expect( triggerIcon?.querySelector( 'path' )?.getAttribute( 'd' ) )
      .toBe( 'M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z' );
    expect( css ).toContain( '.nav-trigger-icon{display:block;width:27px;height:27px;margin:0;fill:#1a3a2a' );
    expect( css ).toContain( ".nav-trigger[aria-expanded='true'] .nav-trigger-icon{transform:rotate(180deg)}" );
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( '.nav-arrow{' );

    // The main dropdown panel keeps its radius/background/shadow but no longer draws an outer
    // grey border or lime top rule.
    expect( css ).toContain( '.nav-trigger{min-width:46px;min-height:46px;background:#f4f7ee;border:0' );
    expect( css ).toContain( 'background:#fcfdfb;border:0;border-radius:14px' );
    expect( css.replace( /\/\*[\s\S]*?\*\//g, '' ) ).not.toContain( 'border-top:3px solid #d1f470' );
  } );
} );