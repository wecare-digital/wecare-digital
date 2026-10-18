import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ShopIndex from '../pages/shop/index';
import { SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount, shopListingPageHref } from '../content/shopProducts';
import { shopProductBySlug } from '../content/shop';

describe( 'the fresh 25-item Shop shelf + purchasable Contribute', () => {
  it( 'keeps all 26 catalog entries while Contribute stays live but hidden from the shelf', () => {
    expect( SHOP_LISTINGS ).toHaveLength( 26 );
    expect( new Set( SHOP_LISTINGS.map( item => item.sku ) ).size ).toBe( 26 );
    expect( SHOP_LISTINGS.some( item => item.slug === 'contribute' && item.sku === 'CNT5Q2M8' && item.formattedPrice === '₹250.00' && item.inStock === true && item.showOnShopShelf === false ) ).toBe( true );
    const contribution = shopProductBySlug( 'contribute' );
    expect( contribution ).not.toBeNull();
    expect( contribution?.inStock ).toBe( true );
    expect( contribution?.variants?.some( variant => variant.id === 'CNT5Q2M8' && variant.inStock ) ).toBe( true );
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

  it( 'renders the 25 public shelf cards while keeping Contribute out of the rail', () => {
    const first = SHOP_LISTINGS.slice( 0, SHOP_LISTINGS_PER_PAGE );
    const { container } = render(
      <ShopIndex listings={ first } allListings={ SHOP_LISTINGS } page={ 1 } totalPages={ shopListingPageCount( SHOP_LISTINGS.length ) } />,
    );
    expect( first ).toHaveLength( SHOP_LISTINGS_PER_PAGE );
    expect( container.querySelectorAll( 'article.shop-card' ) ).toHaveLength( SHOP_LISTINGS.length - 1 );
    expect( screen.queryByText( 'SKU: CNT5Q2M8' ) ).not.toBeInTheDocument();
    expect( screen.getByLabelText( 'Search the shop' ) ).toHaveAttribute( 'type', 'search' );
  } );
} );
