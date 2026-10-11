import type { GetStaticProps } from 'next';
import ShopListingView from '../../components/ShopListingView';
import {
  SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount, type ShopListing,
} from '../../content/shopProducts';

/**
 * /shop/ - page 1 of the catalogue listing.
 *
 * RESTORED 2026-10-10, on owner instruction, after being withdrawn on 2026-10-04: the three
 * /shop 301 rules were removed from scripts/provision_legacy_redirects.py, and '/shop' is in
 * PUBLIC_PAGE_META (src/pages/_app.tsx) and PUBLIC_EXACT (scripts/generate-sitemap.js). Those two
 * are what make this route render at HTTP 200 with a public shell rather than the staff sign-in
 * page, and keep it in the sitemap. src/test/ShopIndexRedirect.test.ts pins all of it.
 *
 * THIN ON PURPOSE. This file was 130 lines of markup and styles over the eight Wix rows; it is
 * now a route that says "page 1". The view lives in components/ShopListingView.tsx and the data
 * in src/content/shopProducts.ts, both shared with src/pages/shop/page/[page].tsx - two routes
 * render the identical page and a copy of either would drift.
 *
 * IT KEEPS BOTH A DEFAULT EXPORT AND A getStaticProps, and both are load-bearing: output:
 * 'export' builds the page from that pair, and item (i) of ShopIndexRedirect.test.ts asserts
 * exactly it.
 *
 * NO Header AND NO Footer. _app.tsx mounts the chrome for every public route, and
 * src/test/PublicRouteRegistration.test.ts fails any public page that mounts it per page.
 *
 * THE HEAD IS NOT OWNED HERE. This is a static pathname-keyed route, so the sitewide block in
 * _app.tsx reads PUBLIC_PAGE_META['/shop'] and emits the canonical, the WebPage node, the title
 * and a BreadcrumbList of [Home, Shop] - which is the trail the view renders. Do not add a second
 * <head> here. /shop/page/N/ is the opposite case and owns its whole head through
 * components/ShopListingHead.tsx; the reason is written there.
 *
 * PAGE 1 IS HERE AND NOT AT /shop/page/1/. Two URLs serving the same six cards is duplicate
 * content, and /shop/ is the one in the sitemap, in config/public-pages.json and in the header.
 * getStaticPaths in the sibling route therefore starts at 2, and shopListingPageHref() knows to
 * send page 1 here.
 */

export interface ShopListingPageProps {
  listings: ShopListing[];
  allListings: ShopListing[];
  page: number;
  totalPages: number;
}

const ShopIndex = ( props: ShopListingPageProps ) => <ShopListingView { ...props } />;

export const getStaticProps: GetStaticProps<ShopListingPageProps> = async () => ( {
  props: {
    listings: SHOP_LISTINGS.slice( 0, SHOP_LISTINGS_PER_PAGE ),
    // The WHOLE shelf as well as the slice, so the search box filters every product rather than
    // this page's six. Roughly 2 kB of __NEXT_DATA__ against the 128 kB threshold blogcheck
    // enforces, which is why the blog's lazily-fetched index is not needed here.
    allListings: SHOP_LISTINGS,
    page: 1,
    totalPages: shopListingPageCount( SHOP_LISTINGS.length ),
  },
} );

export default ShopIndex;
