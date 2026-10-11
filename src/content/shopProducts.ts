import { PRODUCTS } from './products';
import { SHOP_PRODUCTS, shopProductPath } from './shop';

/**
 * Everything WECARE.DIGITAL sells, as ONE list for ONE listing page.
 *
 * WHY THIS FILE EXISTS. /shop/ used to list the eight visible Wix catalogue rows and nothing
 * else, so the eight ProductDef pages - Elsewhere, Expo Week, Dastavez, Clear Closure, Ritual
 * Guru, Anew, Hunar, Niji Setu - were sold by the site and absent from its shop. This merges the
 * two halves so the listing is the whole shelf.
 *
 * IT AUTHORS NO COPY. Every name and every blurb is IMPORTED verbatim from the module that owns
 * it: `ProductDef.blurb` for a product (its docblock says it exists to be "scannable in one
 * glance", which is exactly a card) and `ShopProduct.tagline` for a catalogue row (its twin,
 * "the product's own one-line statement of what it does"). Re-typing either here would be a
 * second copy of a sentence, which the house style forbids.
 *
 * IT AUTHORS NO DETAIL PAGE AND NO PRICE EITHER. `href` always points at a page that already
 * exists - `/<slug>/` for a ProductDef, `/shop/<slug>/` for a catalogue row - and the only prices
 * are `formattedPrice` strings passed straight through from Wix. A ProductDef entry carries no
 * price at all, so the listing can never print a number nobody quoted.
 *
 * FRESHNESS COMES FROM THE EXISTING MECHANISM, not from a new fetch. next.config.js sets
 * output: 'export', so there is no server of ours at runtime and a client-side storefront read
 * would be an unauthenticated Wix call in the browser. .github/workflows/catalogue-sync.yml
 * re-reads Wix every six hours and commits src/content/wix-catalog.json, and the ProductDef half
 * is source code. The listing prints `catalogReadOn()` so a reader can see how fresh the Wix half
 * is rather than being asked to assume.
 *
 * WHAT IS DELIBERATELY ABSENT. /grahak-os/, /vayulok/ and /bharat-rx/ have no importable
 * one-liner - their only one is a string LITERAL inside PUBLIC_PAGE_META, which
 * renderAllowlist() in scripts/generate-public-pages.js and allRoutes() in
 * StructuredDataService.test.ts both parse as text and both require to stay a literal. The seven
 * CUSTOMERSERVICE entries, /shipments/ and /subscribe/ are request ACTIONS and front doors, which
 * is why StructuredDataService.test.ts lists all nine in NOT_OFFERINGS: none of them is a thing
 * we sell, and putting one on a shelf would misdescribe the site.
 */

export interface ShopListing {
  /** Stable React key and de-dup key. The product's own slug. */
  slug: string;
  /** Display name. From ProductDef.name or ShopProduct.name, verbatim. */
  name: string;
  /** One scannable line. From ProductDef.blurb or ShopProduct.tagline, verbatim. */
  blurb: string;
  /** The EXISTING detail page. '/anew/' for a ProductDef, '/shop/kiosk/' for a Wix row. */
  href: string;
  /**
   * Wix's own formatted string, passed through, present only on a Wix-backed entry.
   * Never rebuilt, never derived, never shown for a ProductDef entry.
   */
  formattedPrice?: string;
  /** Wix stock flag, present only on a Wix-backed entry. */
  inStock?: boolean;
  /** Which half this came from. Read by the card to decide whether to print a price. */
  source: 'product' | 'catalogue';
}

/**
 * ORDERING: the ProductDef half first in DECLARATION order, then the catalogue half in NAME
 * order. Both orderings already exist in the repo - declaration order is what the header's
 * Products column prints, and name order is the only one the Wix snapshot supports (shop.ts
 * records that Wix returns no sort weight and all rows share one category) - so neither is
 * invented here.
 *
 * DE-DUPLICATION IS STRUCTURAL, through a Map keyed on slug. `anew` is in both halves and
 * resolves in favour of /anew/: that is the richer page (rotating hero, three points, boundary
 * note, price, share row, blog panel) and its price already matches the Wix row.
 * /shop/anew/ is NOT deleted or de-indexed - it is the add-to-cart path and is pinned by
 * ShopIndexRedirect.test.ts.
 */
const merge = (): ShopListing[] => {
  const byslug = new Map<string, ShopListing>();

  for ( const product of PRODUCTS ) {
    byslug.set( product.slug, {
      slug: product.slug,
      name: product.name,
      blurb: product.blurb,
      href: `/${product.slug}/`,
      source: 'product',
    } );
  }

  for ( const product of SHOP_PRODUCTS ) {
    if ( byslug.has( product.slug ) ) continue;
    byslug.set( product.slug, {
      slug: product.slug,
      name: product.name,
      blurb: product.tagline,
      // The existing helper, so the trailing-slash canonical form is not spelled twice.
      href: shopProductPath( product ),
      formattedPrice: product.formattedPrice,
      inStock: product.inStock,
      source: 'catalogue',
    } );
  }

  return [ ...byslug.values() ];
};

/**
 * BUILD-TIME INVARIANTS, ENFORCED HERE AND NOT IN THE PAGE, because the slug IS a path segment
 * and a bad value has to fail the build rather than ship a broken route.
 *
 * `next build` evaluates this module while prerendering /shop/, so a bad value fails the build
 * rather than shipping a broken route. (It is NOT caught by scripts/generate-public-pages.js,
 * which runs first but reads src/content/* as TEXT and never imports it.)
 *
 * Nothing is caught and nothing is defaulted. A derived list agrees with whatever it derived
 * from, including an empty array, and catching here is how a catalogue page ships blank.
 */
const validate = ( listings: ShopListing[] ): ShopListing[] => {
  const ROUTE_SAFE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  for ( const listing of listings ) {
    if ( !ROUTE_SAFE.test( listing.slug ) ) {
      throw new Error(
        `shopProducts: slug ${JSON.stringify( listing.slug )} is not route-safe, and the slug is a path segment.`,
      );
    }
    // A product slugged 'page' would emit out/shop/page/index.html and collide with the
    // /shop/page/[page]/ listing route directory in the static export.
    if ( listing.slug === 'page' ) {
      throw new Error( 'shopProducts: a product slugged "page" collides with the /shop/page/N/ route.' );
    }
    if ( !listing.name.trim() ) {
      throw new Error( `shopProducts: ${listing.slug} has no name, so its card cannot render.` );
    }
    // shop.ts already synthesises a name-based tagline for a Wix row with no description, so an
    // empty blurb here means a ProductDef regression rather than missing merchant copy.
    if ( !listing.blurb.trim() ) {
      throw new Error( `shopProducts: ${listing.slug} has no blurb, so its card would render a blank line.` );
    }
  }
  // The floor is 8 because PRODUCTS alone supplies 8. Only a deliberate code deletion can cross
  // it; a product added or removed in Wix cannot.
  if ( listings.length < 8 ) {
    throw new Error( `shopProducts: only ${listings.length} listings, which is fewer than the 8 PRODUCTS alone supply.` );
  }
  return listings;
};

/** The merged shelf. 15 entries as of the 2026-10-10 snapshot; the floor is 8. */
export const SHOP_LISTINGS: ShopListing[] = validate( merge() );

/**
 * SIX PER PAGE. The blog's 24 would put the whole shelf on one page and never render the
 * paginator. Six one-per-row cards is roughly three screens, which is the density the blog
 * landed on after measuring.
 */
export const SHOP_LISTINGS_PER_PAGE = 6;

export const shopListingPageCount = ( total: number ): number =>
  Math.max( 1, Math.ceil( total / SHOP_LISTINGS_PER_PAGE ) );

/**
 * PAGE 1 IS /shop/, NOT /shop/page/1/. Two URLs serving the same six cards is duplicate content,
 * and /shop/ is the one in PUBLIC_EXACT, in config/public-pages.json, in the sitemap and in the
 * header. getStaticPaths in src/pages/shop/page/[page].tsx therefore starts at 2.
 */
export const shopListingPageHref = ( page: number ): string =>
  ( page <= 1 ? '/shop/' : `/shop/page/${page}/` );
