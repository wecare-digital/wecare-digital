import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ShopIndex from '../pages/shop/index';
import { SHOP_LISTINGS, shopListingPageCount, shopListingPageHref } from '../content/shopProducts';

describe( 'the clean-slate Shop', () => {
  it( 'publishes no legacy product cards', () => {
    expect( SHOP_LISTINGS ).toEqual( [] );
    expect( shopListingPageCount( SHOP_LISTINGS.length ) ).toBe( 1 );
  } );

  it( 'keeps /shop/ as the canonical first page', () => {
    expect( shopListingPageHref( 1 ) ).toBe( '/shop/' );
    expect( shopListingPageHref( 2 ) ).toBe( '/shop/page/2/' );
  } );

  it( 'renders the Shop shell and search field without stale cards', () => {
    const { container } = render(
      <ShopIndex listings={ [] } allListings={ [] } page={ 1 } totalPages={ 1 } />,
    );
    expect( container.querySelectorAll( 'article.shop-card' ) ).toHaveLength( 0 );
    expect( screen.getByLabelText( 'Search the shop' ) ).toHaveAttribute( 'type', 'search' );
  } );
} );
