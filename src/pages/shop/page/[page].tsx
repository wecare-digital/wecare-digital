import type { GetStaticPaths, GetStaticProps } from 'next';
import ShopListingView from '../../../components/ShopListingView';
import ShopListingHead from '../../../components/ShopListingHead';
import type { ShopListingPageProps } from '../index';
import {
  SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount,
} from '../../../content/shopProducts';

/**
 * /shop/page/2/ … /shop/page/N/ - the rest of the catalogue listing.
 *
 * A DYNAMIC SEGMENT IN A STATIC EXPORT IS ONLY SAFE WITH getStaticPaths. /workspace/seo/page/[id]
 * had none - its ids come from a live API - so the export emitted exactly one file: a directory
 * named, literally, `[id]`, which served HTTP 200 at /%5Bid%5D/ while every real id 404'd on
 * reload. Here the page numbers ARE known at build time, so getStaticPaths lists all of them with
 * fallback: false and the export writes real directories. `find out -name '*[*'` must stay empty;
 * that is the check.
 *
 * PATHS START AT 2. Page 1 is /shop/, which is the URL in the sitemap, in PUBLIC_EXACT, in
 * config/public-pages.json and in the header. Emitting /shop/page/1/ as well would be the same
 * six cards at a second URL, and every page here is self-canonical, so both would be indexed.
 *
 * THE COUNT COMES FROM THE SAME LIST getStaticProps SLICES. If paths and props disagreed by one,
 * the last page would either 404 or render empty with a paginator pointing nowhere.
 *
 * ROUTE COLLISION, AND WHY THERE IS NOT ONE. Next resolves a static segment ahead of a dynamic
 * one, so /shop/page/2/ matches this file and never src/pages/shop/[slug].tsx. The reverse
 * hazard - a Wix product slugged `page` emitting out/shop/page/index.html - is closed by the
 * build-time invariant in src/content/shopProducts.ts.
 *
 * ROUTING: '/shop/page/[page]' must be in the isContentPublic check in _app.tsx or this renders
 * an empty body at HTTP 200 - a 404 that does not look like one, with a 200 in the sitemap and a
 * 200 in every uptime check. It needs NO PUBLIC_EXACT entry, no STRUCTURAL entry and no
 * config/public-pages.json row: '/shop/' is already in PUBLIC_PREFIXES in
 * scripts/generate-sitemap.js, and the sitemap is built by walking out/ for index.html, so these
 * pages enter it automatically. Do not add a redundant '/shop/page/' prefix.
 */
export default function ShopListingPage ( props: ShopListingPageProps ) {
  return (
    <>
      <ShopListingHead page={ props.page } totalPages={ props.totalPages } />
      <ShopListingView { ...props } />
    </>
  );
}

export const getStaticPaths: GetStaticPaths = async () => {
  const totalPages = shopListingPageCount( SHOP_LISTINGS.length );
  const paths = [];
  for ( let page = 2; page <= totalPages; page++ ) {
    paths.push( { params: { page: String( page ) } } );
  }
  // totalPages === 1 yields no paths at all, which is correct rather than a failure: no
  // /shop/page/ directory is emitted and the view hides the paginator because totalPages > 1 is
  // false. No dead links either way.
  return { paths, fallback: false };
};

export const getStaticProps: GetStaticProps<ShopListingPageProps> = async ( context ) => {
  const page = Number( context.params?.page );
  /**
   * Guard even though getStaticPaths only ever hands over integers from 2 to N. fallback is
   * false, so an out-of-range page cannot arrive at build time - but a hand-edited params object
   * or a future move to fallback: 'blocking' would, and notFound is the honest answer rather than
   * a page rendering an empty grid.
   */
  if ( !Number.isInteger( page ) || page < 2 ) return { notFound: true };
  const totalPages = shopListingPageCount( SHOP_LISTINGS.length );
  if ( page > totalPages ) return { notFound: true };
  const start = ( page - 1 ) * SHOP_LISTINGS_PER_PAGE;
  return {
    props: {
      listings: SHOP_LISTINGS.slice( start, start + SHOP_LISTINGS_PER_PAGE ),
      allListings: SHOP_LISTINGS,
      page,
      totalPages,
    },
  };
};
