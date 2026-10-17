import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ShopIndex from '../pages/shop/index';
import { SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount, shopListingPageHref } from '../content/shopProducts';

describe( 'the fresh 25 + Contribute Shop', () => {
  it( 'publishes all 26 fresh catalog cards with unique SKUs', () => {
    expect( SHOP_LISTINGS ).toHaveLength( 26 );
    expect( new Set( SHOP_LISTINGS.map( item => item.sku ) ).size ).toBe( 26 );
    expect( SHOP_LISTINGS.some( item => item.slug === 'contribute' && item.sku === 'CNT5Q2M8' && item.formattedPrice === '₹250.00' ) ).toBe( true );
    expect( shopListingPageCount( SHOP_LISTINGS.length ) ).toBe( 5 );
  } );

  it( 'keeps /shop/ as the canonical first page', () => {
    expect( shopListingPageHref( 1 ) ).toBe( '/shop/' );
    expect( shopListingPageHref( 2 ) ).toBe( '/shop/page/2/' );
  } );

  it( 'links representative cards to their respective existing product pages', () => {
    expect( SHOP_LISTINGS.find( item => item.slug === 'grahak-os' )?.href ).toBe( '/grahak-os/' );
    expect( SHOP_LISTINGS.find( item => item.slug === 'submit-request' )?.href ).toBe( '/submit-request/' );
    expect( SHOP_LISTINGS.find( item => item.slug === 'referral-partner' )?.href ).toBe( '/refer-and-earn/' );
    expect( SHOP_LISTINGS.find( item => item.slug === 'contribute' )?.href ).toBe( '/shop/contribute/' );
  } );

  it( 'renders the whole horizontal shelf while page 1 still receives its six-card crawl slice', () => {
    const first = SHOP_LISTINGS.slice( 0, SHOP_LISTINGS_PER_PAGE );
    expect( first ).toHaveLength( SHOP_LISTINGS_PER_PAGE );
    const { container } = render(
      <ShopIndex listings={ first } allListings={ SHOP_LISTINGS } page={ 1 } totalPages={ 5 } />,
    );
    // The interactive rail deliberately renders all products; the six-card slice remains the
    // prerender/crawl contract passed through the page props.
    expect( container.querySelectorAll( 'article.shop-card' ) ).toHaveLength( SHOP_LISTINGS.length );
    expect( screen.getByLabelText( 'Search the shop' ) ).toHaveAttribute( 'type', 'search' );
  } );
} );
