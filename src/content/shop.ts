/**
 * The shop catalogue, read from the committed Wix snapshot.
 *
 * `src/content/wix-catalog.json` is produced by `scripts/fetch-wix-catalog.js` and committed.
 * next.config.js sets `output: 'export'`, so these pages are built once and served as static HTML -
 * there is no server to make a live call from, and a client-side fetch would put an unauthenticated
 * Wix read in the browser. Refreshing the catalogue is a deliberate act: re-run the script and
 * commit. The snapshot is credential-free by construction; it was taken with an anonymous visitor
 * token, recorded in its own `source` field.
 *
 * THE PRICES HERE ARE FOR DISPLAY AND MUST NEVER REACH A PAYMENT. The amount in a payment request
 * comes from a live checkout read, compared in integer paise, and any mismatch fails closed - see
 * amplify/functions/shared/order_creation.py. `formattedPrice` is passed through from Wix rather
 * than reformatted locally, so a page cannot invent a different number from the one Wix would quote.
 * `inStock` labels a card and never promises availability at payment time.
 *
 * Three fields in the snapshot are deliberately not exposed on the interface:
 *   productType  reads "PHYSICAL" on all seven, which is Wix's default for a product with no
 *                shipping profile. Five of the seven are documents and coordination, so surfacing
 *                it would put a false statement on five pages.
 *   mediaCount   zero on all seven, so there is no image URL. The pages ship no product image and
 *                no placeholder frame, and the Product schema emits no `image`.
 *   productUrl   points at the current canonical product page.
 */
import catalog from './wix-catalog.json';
// The contribution vehicle's identity, so the shop exclusion and the cart line read ONE
// declaration. src/config/contribution.ts imports nothing from here, so there is no cycle.
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../config/contribution';

export interface ShopVariant { id: string; label: string; inStock: boolean; }

export interface ShopProduct {
  variants?: ShopVariant[];
  id: string;
  name: string;
  slug: string;
  /** Wix's own formatted string, e.g. "₹6,999.00". Passed through, never rebuilt. */
  formattedPrice: string;
  /**
   * The decimal string Wix returns, e.g. "6999.00". Used for sorting and for the `price` in the
   * Product schema, where schema.org wants a bare number. NEVER used to charge anyone.
   */
  price: string;
  currency: string;
  inStock: boolean;
  /**
   * Absolute URL of the product's primary image, when one exists. Absent on all seven today, and
   * that absence gates the Product structured data - see ShopProductHead.tsx. Populating it needs
   * images uploaded in Wix and scripts/fetch-wix-catalog.js extended to capture the URL.
   */
  image?: string;
  /**
   * The bold opening line of the Wix description - the product's own one-line statement of what it
   * does, which is what a card in a grid needs and what a meta description should open with.
   */
  tagline: string;
  /** The remaining paragraphs, in order, as plain text. */
  body: string[];
}

interface RawProduct {
  variants?: ShopVariant[];
  id?: string;
  name?: string;
  slug?: string;
  formattedPrice?: string;
  price?: string;
  currency?: string;
  inStock?: boolean;
  visible?: boolean;
  descriptionHtml?: string;
  image?: string;
}

/** U+0001, which cannot appear in Wix rich text and is not whitespace, so \s+ leaves it alone. */
const BREAK = '\u0001';

/**
 * Remove tag-shaped runs until the string stops changing, then delete any surviving delimiter.
 *
 * BOTH HALVES ARE LOAD-BEARING AND NEITHER IS SAFE TO SIMPLIFY. One pass of `/<[^>]*>/g` is
 * defeated by nesting, because removing the inner match splices the outer one together
 * (`<scr<script>ipt>` -> `<script>`), so the loop runs to a fixed point. And an UNTERMINATED run
 * never matches at all, so `<script` with no closing bracket passed through untouched - hence the
 * final sweep of bare `[<>]`. A raw angle bracket surviving to that point cannot be legitimate
 * content: well-formed HTML encodes one as an entity, and entities are decoded AFTER this runs.
 */
const stripTags = ( value: string ): string => {
  let text = value;
  for ( ; ; ) {
    const next = text.replace( /<[^>]*>/g, '' );
    if ( next === text ) break;
    text = next;
  }
  return text.replace( /[<>]/g, '' );
};

/**
 * Wix description HTML reduced to plain paragraph strings.
 *
 * NOT an HTML sanitiser, and its result must never reach dangerouslySetInnerHTML: the safety
 * property is that the output is rendered as React children, which escape on render. `<p>` and
 * `<br>` become paragraph breaks because they are the only structure this copy uses; everything
 * else is dropped rather than approximated.
 *
 * THE ORDER OF THE THREE STEPS IS LOAD-BEARING:
 *   - the whitespace collapse runs PER LINE, after the split, or it would eat the separators this
 *     function just inserted;
 *   - the separator is a control character and not '\n', because a raw newline in HTML is
 *     whitespace and must collapse to a space rather than break a paragraph;
 *   - `&amp;` decodes LAST, or a literal "&amp;lt;" in the source would double-decode to "<".
 */
export function toParagraphs ( html: string ): string[] {
  const withBreaks = html
    // Any BREAK is stripped first, so a control character in the source cannot be mistaken for one
    // this function inserted.
    .replace( new RegExp( BREAK, 'g' ), '' )
    .replace( /<\s*br\s*\/?\s*>/gi, BREAK )
    .replace( /<\/\s*p\s*>/gi, BREAK );

  return stripTags( withBreaks )
    .replace( /&nbsp;/g, ' ' )
    .replace( /&lt;/g, '<' )
    .replace( /&gt;/g, '>' )
    .replace( /&quot;/g, '"' )
    .replace( /&#39;|&apos;/g, "'" )
    .replace( /&amp;/g, '&' )
    .split( BREAK )
    .map( line => line.replace( /\s+/g, ' ' ).trim() )
    .filter( Boolean );
}

/**
 * Only visible products. `visible: false` in Wix means the merchant has taken the product off the
 * storefront; a product with no slug is dropped because the slug IS the route.
 *
 * Sorted by name, which is the only ordering the snapshot supports - Wix returns no sort weight and
 * all seven carry the same mainCategoryId, so any other order would be the order the API happened
 * to answer in.
 */
/**
 * The contribution product is a payment VEHICLE, not a shop listing.
 *
 * It has to be visible in Wix, because the checkout refuses `product.visible === false` - so
 * `scripts/fetch-wix-catalog.js` picks it up and it would otherwise appear at `/shop/` with its own
 * `/shop/contribute/` page and a sitemap entry. The place to choose a contribution is the
 * "Contribute" block at the foot of a blog post, not a product page with an "Amount" dropdown.
 *
 * EXCLUDED BY PRODUCT ID FIRST, SLUG SECOND. The id is the identity the server, the cart and this
 * file all key on, and it cannot be edited in the Wix dashboard; the slug can. The slug is still
 * checked so the exclusion survives a product id override via `NEXT_PUBLIC_*`.
 */
export const CONTRIBUTION_SLUG = 'contribute';

/** Is this raw snapshot row the contribution vehicle rather than a shop listing? */
const isContributionRow = ( raw: RawProduct ): boolean =>
  String( raw.id || '' ).trim().toLowerCase() === CONTRIBUTION_PRODUCT_ID
  || raw.slug === CONTRIBUTION_SLUG;

/** The one projection, so the excluded entry is a real `ShopProduct` and not a raw snapshot row. */
const project = ( raw: RawProduct ): ShopProduct => {
  const paragraphs = toParagraphs( String( raw.descriptionHtml || '' ) );
  return {
    ...( raw.variants ? { variants: raw.variants } : {} ),
    id: String( raw.id || '' ),
    name: String( raw.name || '' ),
    slug: String( raw.slug || '' ),
    formattedPrice: String( raw.formattedPrice || '' ),
    price: String( raw.price || '' ),
    currency: String( raw.currency || 'INR' ),
    inStock: raw.inStock !== false,
    // Spread, not `image: raw.image || undefined`, so a product with no image has no `image` KEY
    // at all. ShopProductHead gates the Product node on the field's presence.
    ...( raw.image ? { image: String( raw.image ) } : {} ),
    tagline: paragraphs[ 0 ] || '',
    body: paragraphs.slice( 1 ),
  };
};

const VISIBLE = ( ( catalog as { products?: RawProduct[] } ).products || [] )
  .filter( raw => raw.visible !== false && !!raw.slug && !!raw.name );

export const SHOP_PRODUCTS: ShopProduct[] = VISIBLE
  .filter( raw => !isContributionRow( raw ) )
  .map( project )
  .sort( ( a, b ) => a.name.localeCompare( b.name ) );

/** The contribution product, projected the same way. Null until the snapshot is refreshed. */
export const CONTRIBUTION_PRODUCT: ShopProduct | null =
  VISIBLE.filter( isContributionRow ).map( project )[ 0 ] || null;

/**
 * The raw snapshot row for the contribution product, for INVARIANT CHECKS ONLY.
 *
 * `productType` and the three counts are deliberately NOT on `ShopProduct` - see this file's
 * header: `productType` reads PHYSICAL on every product in the snapshot, so surfacing it would put
 * a false statement on five pages. They are read here rather than by widening the interface every
 * product page consumes.
 *
 * Null until `scripts/fetch-wix-catalog.js` is re-run, which is NOT a configuration problem: the
 * ids a contribution line needs are committed in src/config/contribution.ts, so the feature works
 * with this row absent. All it costs is the `/shop/` exclusion, which only matters once the row
 * exists in the first place.
 */
export const CONTRIBUTION_RAW: Record<string, unknown> | null =
  ( ( ( catalog as { products?: RawProduct[] } ).products || [] )
    .find( isContributionRow ) as Record<string, unknown> | undefined ) || null;

/**
 * Re-exported so a cart line, the shop exclusion and the blog form all read ONE declaration.
 *
 * The ids used to be derived from the committed catalogue snapshot, with `NEXT_PUBLIC_*` as a
 * bridge. They are now committed constants in src/config/contribution.ts, because the snapshot
 * cannot supply them: `slim()` in scripts/fetch-wix-catalog.js emits no `variants` array at all,
 * so a refresh gives the product id and never the three variant ids a choice needs.
 */
export { CONTRIBUTION_PRODUCT_ID };

/**
 * Is a contribution offerable by this build at all?
 *
 * A product id and three choices, read together: a line with a product id and no variant id would
 * reach `normalized_catalog_items`' single-variant fallback, which is exactly the guess the
 * explicit variant exists to avoid - and on this three-variant product it answers `choose an
 * available product option` as a 502.
 */
export const CONTRIBUTION_CONFIGURED: boolean =
  !!CONTRIBUTION_PRODUCT_ID && CONTRIBUTION_CHOICES.length > 0
  && CONTRIBUTION_CHOICES.every( choice => !!choice.variantId );

/**
 * The projection, exposed so a test can drive it from an injected row.
 *
 * The contribution entry does not exist in the committed snapshot until the owner creates the
 * product in Wix, so asserting the projection against `CONTRIBUTION_PRODUCT` would be asserting
 * against `null` - and re-implementing the projection inside the test would be testing a copy of
 * the thing rather than the thing. Named `projectForTest` rather than `project` so nothing in a
 * page is tempted to call it: a page gets a projected product from `SHOP_PRODUCTS`.
 */
export const projectForTest = project;

export const shopProductBySlug = ( slug: string ): ShopProduct | null =>
  SHOP_PRODUCTS.find( product => product.slug === slug ) || null;

/** When the snapshot was taken, so a reader can tell how fresh the catalogue is. */
export const CATALOG_FETCHED_AT = String(
  ( catalog as { fetchedAt?: string } ).fetchedAt || '',
);

/** "26 September 2026" - the fetch timestamp as a date a reader can place. */
export const catalogReadOn = (): string => {
  const at = new Date( CATALOG_FETCHED_AT );
  if ( Number.isNaN( at.getTime() ) ) return '';
  // en-GB with an EXPLICIT UTC zone. The snapshot timestamp is UTC, and letting this resolve in the
  // visitor's zone would render a different date either side of midnight for the same build - a
  // hydration mismatch as well as a wrong answer.
  return at.toLocaleDateString( 'en-GB', {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  } );
};

/**
 * The meta description for a product page: the owner's own sentences, joined in order until the next
 * one would not fit, and never cut mid-sentence.
 *
 * 160 characters is the budget because that is roughly where Google stops rendering. Truncating at a
 * word boundary with an ellipsis was the alternative and it is worse: this copy is written as short,
 * complete paragraphs, so a cut always lands inside an argument. Measured output runs 54 to 159
 * characters across the seven; a thin description is the right answer anyway, because Google
 * supplements from the page and will not invent a sentence nobody wrote.
 */
export const shopMetaDescription = ( product: ShopProduct ): string => {
  const budget = 160;
  let out = '';
  for ( const paragraph of [ product.tagline, ...product.body ] ) {
    const candidate = out ? out + ' ' + paragraph : paragraph;
    if ( candidate.length > budget ) break;
    out = candidate;
  }
  return out;
};

/**
 * "Kiosk — price and what it includes | WECARE.DIGITAL".
 *
 * The descriptor is the same on all seven because it is a statement about the PAGE, not the product.
 * Splicing in each product's own tagline breaks the length bound: Paperwork's is 60 characters,
 * which with the name and suffix runs to 96 against tools/browser/seocheck.js's 75-character
 * ceiling. The longest of the seven as written is 62.
 */
export const shopPageTitle = ( product: ShopProduct ): string =>
  product.name + ' — price and what it includes | WECARE.DIGITAL';

/** '/shop/kiosk/' - trailingSlash is on, so the canonical form carries one. */
export const shopProductPath = ( product: ShopProduct ): string =>
  '/shop/' + product.slug + '/';
