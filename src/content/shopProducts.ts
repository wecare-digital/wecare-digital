/**
 * Shop listing contract.
 *
 * The retired Shop snapshot and the old merged shelf are removed. /shop/ is deliberately empty
 * until the fresh 25-item SKU-first catalog is created.
 */

export interface ShopListing {
  slug: string;
  name: string;
  blurb: string;
  sku?: string;
  href: string;
  formattedPrice?: string;
  inStock?: boolean;
  image?: string;
  source: 'product' | 'catalogue';
}

/** Clean-slate Shop: no legacy or source-defined product cards are published. */
export const SHOP_LISTINGS: ShopListing[] = [];

export const SHOP_LISTINGS_PER_PAGE = 6;

export const shopListingPageCount = ( total: number ): number =>
  Math.max( 1, Math.ceil( total / SHOP_LISTINGS_PER_PAGE ) );

export const shopListingPageHref = ( page: number ): string =>
  ( page <= 1 ? '/shop/' : `/shop/page/${page}/` );
