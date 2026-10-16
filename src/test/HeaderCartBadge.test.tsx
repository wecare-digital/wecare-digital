  it( 'flags the drawn number as untranslatable, the way prices are', async () => {
    cart.addItem( PRODUCT, 2 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '2' ) );
    // A regrouped numeral is a different number. Belt and braces - the glyph is aria-hidden, which
    // the walker already skips - but it keeps the handling of numbers consistent across the site.
    expect( container.querySelector( '.hdr-cart-n' ) )
      .toHaveAttribute( 'data-wc-no-translate', 'true' );
  } );
} );

describe( 'the header still reads the way its own tests require', () => {
  /*
   * Header.test.tsx reaches the menu trigger with container.querySelector('button') to prove the
   * chevron is drawn rather than typed. Adding a control to the header could have broken that
   * silently, so the ordering is asserted here too - from the other side, where the bag is the thing
   * being added.
   */
  it( 'leaves the menu trigger as the first and only button', () => {
    const { container } = render( <Header /> );
    const buttons = container.querySelectorAll( 'button' );
    expect( buttons[ 0 ].className ).toContain( 'nav-trigger' );
    // The bag is an anchor, so it adds no button at all. The trigger glyph is SVG,
    // not ligature text, so the button itself still has no text content.
    expect( buttons[ 0 ].textContent ).toBe( '' );
  } );

  it( 'puts the bag after the brand in the reading and tab order', () => {
    const { container } = render( <Header /> );
    const logo = container.querySelector( '.logo' ) as Node;
    const bagLink = container.querySelector( '.hdr-cart' ) as Node;
    expect( logo ).not.toBeNull();
    expect( bagLink ).not.toBeNull();
    // DOCUMENT_POSITION_FOLLOWING = 4. The bag comes after the lockup, so a keyboard user reaches
    // the brand and the menu first.
    expect( logo.compareDocumentPosition( bagLink ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
  } );

  it( 'reserves room for a 44px chip at 280px rather than letting it overflow', () => {
    /*
     * MEASURED, NOT GUESSED, AND THE NUMBERS ARE WHY THIS RULE EXISTS. On the built header at 280px
     * - Galaxy Fold, folded, the narrowest posture devicecheck.js carries - the 16px gutter leaves a