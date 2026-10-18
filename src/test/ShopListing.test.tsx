import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ShopIndex from '../pages/shop/index';
import { SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount, shopListingPageHref } from '../content/shopProducts';

describe( 'the fresh 26 + Contribute Shop', () => {
  it( 'publishes all 27 fresh catalog cards with unique SKUs', () => {
    expect( SHOP_LISTINGS ).toHaveLength( 27 );
    expect( new Set( SHOP_LISTINGS.map( item => item.sku ) ).size ).toBe( 27 );
    expect( SHOP_LISTINGS.some( item => item.slug === 'contribute' && item.sku === 'CNT5Q2M8' && item.formattedPrice === '₹250.00' ) ).toBe( true );
    expect( SHOP_LISTINGS.some( item => item.slug === 'hunar-kaushal' && item.sku === 'KSL9M2Q4' && item.formattedPrice === '₹99.00' ) ).toBe( true );
    expect( SHOP_LISTINGS.some( item => item.slug === 'hunar-prastuti' && item.sku === 'PST7K4N2' && item.formattedPrice === '₹299.00' ) ).toBe( true );
    expect( SHOP_LISTINGS.some( item => item.slug === 'hunar' ) ).toBe( false );
    expect( shopListingPageCount( SHOP_LISTINGS.length ) ).toBe( 5 );
  } );

  it( 'keeps /shop/ as the canonical first page', () => {
    expect( shopListingPageHref( 1 ) ).toBe( '/shop/' );
    expect( shopListingPageHref( 2 ) ).toBe( '/shop/page/2/' );
  } );

  it( 'links representative cards to their respective existing product pages', () => {
    expect( SHOP_LISTINGS.find( item => item.slug === 'grahak-os' )?.href ).toBe( '/grahak-os/' );
    expect( SHOP_LISTINGS.find( item => item.slug === 'submit-request' )?.href ).toBe( '/submit-request/' );
    expect( SHOP_LISTINGS.find( item => item.slug === 'referral-partner' ) ).toBeUndefined();
    expect( SHOP_LISTINGS.find( item => item.slug === 'contribute' )?.href ).toBe( '/shop/contribute/' );
  } );

  it( 'renders the whole 27-item shelf while keeping the paginated crawl props honest', () => {
    const first = SHOP_LISTINGS.slice( 0, SHOP_LISTINGS_PER_PAGE );
    const { container } = render(
      <ShopIndex listings={ first } allListings={ SHOP_LISTINGS } page={ 1 } totalPages={ shopListingPageCount( SHOP_LISTINGS.length ) } />,
    );
    expect( first ).toHaveLength( SHOP_LISTINGS_PER_PAGE );
    expect( container.querySelectorAll( 'article.shop-card' ) ).toHaveLength( SHOP_LISTINGS.length );
    expect( screen.getByLabelText( 'Search the shop' ) ).toHaveAttribute( 'type', 'search' );
  } );
} );
