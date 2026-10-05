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

/**
 * THE WIX TEMPLATE'S OWN SAMPLE PRODUCTS, which are not this storefront. Owner decision,
 * 2026-10-05, on migrating the catalogue to site `c993128b-26be-41cd-9fcd-904abe23462f`.
 *
 * The new site was created from a Wix store template, so it shipped with twelve demo products
 * already in its catalogue. They are `visible: true` and real catalogue rows, so
 * `scripts/fetch-wix-catalog.js` collects them and the snapshot went from 9 products to 21 - and
 * every one of them would otherwise get a `/shop/<slug>/` page and a sitemap entry on the next
 * build.
 *
 * WHY THEY ARE EXCLUDED RATHER THAN RE-COPIED. Ten of the twelve carry Wix's placeholder text
 * verbatim ("I'm a product description. I'm a great place to add more details about...") and share
 * it word for word, so publishing them lands ten public pages with the same meta description and
 * one title past the 75-character bound `tools/browser/seocheck.js` enforces. The two bounds tests
 * in src/test/ShopCatalogue.test.tsx catch exactly that, and they are left intact: the fix is to
 * not publish a template's sample data, not to loosen the guard that noticed it.
 *
 * EXCLUDED BY PRODUCT ID FIRST, SLUG SECOND, for the same reason `isContributionRow` is: the id is
 * the identity the catalogue keys on and cannot be edited in the Wix dashboard, while the slug can.
 *
 * REVERSIBLE AND NON-DESTRUCTIVE, deliberately. Nothing is deleted from Wix and nothing is removed
 * from the snapshot - the rows stay committed in src/content/wix-catalog.json, so a product the
 * owner decides to sell is published by deleting its line here (or by giving it real copy in Wix
 * and deleting its line here). Checkout is untouched: it reads the live Wix catalogue, not
 * `SHOP_PRODUCTS`, so a demo product remains purchasable by direct cart reference if one ever is.
 */
export const WIX_TEMPLATE_SAMPLE_PRODUCT_IDS: readonly string[] = [
  '618dcfe4-8d85-40a9-87c6-0dea57abe644', // Baseball Cap
  'af654225-662f-42e5-ac51-fbebc88f63ed', // Ceramic Flower Vase
  'df8ae122-9a06-4fa2-96bb-4b058db5959f', // Crew T-Shirt
  'f68519fb-2095-4dfc-8684-ec55d60c2adc', // Essential Oil Diffuser
  '96ff5295-1660-40d1-89e4-d1f1a34309be', // Foaming Facial Cleanser
  'ca71fee6-1fc9-4a57-8fa7-967c8edcaabb', // Hydrating Eye Serum - Pre Order
  '99684dfe-d36a-4869-858a-dba67af9b993', // Knitted Golf Sweater
  'fedfcb20-1ad2-405b-950b-e65112bb6222', // Minimalist Tote Bag
  'd86d7bea-fe19-4654-a597-bfe8dd449407', // Round Eyeglasses
  '42941ee7-1707-4b5d-a7d7-41e12da6ab9e', // Solid Wood Chair
  '1190303d-1fb5-40ca-bb60-2d5c1af3ae97', // Stainless Steel Water Bottle
  'd2dc8bef-0a26-414a-b1dc-7bbba867bc6a', // Textured Loop Earrings
] as const;

/** The same twelve by slug, so the exclusion survives a product being re-created in Wix. */
export const WIX_TEMPLATE_SAMPLE_SLUGS: readonly string[] = [
  'baseball-cap', 'ceramic-flower-vase', 'crew-t-shirt', 'essential-oil-diffuser',
  'foaming-facial-cleanser', 'hydrating-eye-serum', 'knitted-golf-sweater',
  'minimalist-tote-bag', 'round-eyeglasses', 'solid-wood-chair',
  'stainless-steel-water-bottle', 'textured-loop-earrings',
] as const;

/** Is this raw snapshot row one of the Wix template's sample products? */
const isTemplateSampleRow = ( raw: RawProduct ): boolean =>
  WIX_TEMPLATE_SAMPLE_PRODUCT_IDS.includes( String( raw.id || '' ).trim().toLowerCase() )
  || WIX_TEMPLATE_SAMPLE_SLUGS.includes( String( raw.slug || '' ).trim().toLowerCase() );

/** The one projection, so the excluded entry is a real `ShopProduct` and not a raw snapshot row. */
const project = ( raw: RawProduct ): ShopProduct => {
  const paragraphs = toParagraphs( String( raw.descriptionHtml || '' ) );
  const name = String( raw.name || '' );
  // A product authored in Wix without a description must still render a complete page and a valid
  // meta description, or the build invariants reject a real live product (which is exactly how a
  // newly-added product first appears: no copy yet). When Wix carries no description we synthesise
  // a safe, name-based tagline and one body line from the product name alone — never inventing a
  // claim, just stating the product's own name. The owner can add real copy in Wix at any time and
  // it replaces this automatically on the next catalogue sync.
  const fallbackTagline = name ? `${name} from WECARE.DIGITAL.` : 'A product from WECARE.DIGITAL.';
  const fallbackBody = name
    ? `${name} is available to order from WECARE.DIGITAL. See the details and secure checkout below.`
    : 'Available to order from WECARE.DIGITAL with secure checkout.';
  const tagline = paragraphs[ 0 ] || fallbackTagline;
  const body = paragraphs.length > 1 ? paragraphs.slice( 1 ) : [ fallbackBody ];
  return {
    ...( raw.variants ? { variants: raw.variants } : {} ),
    id: String( raw.id || '' ),
    name,
    slug: String( raw.slug || '' ),
    formattedPrice: String( raw.formattedPrice || '' ),
    price: String( raw.price || '' ),
    currency: String( raw.currency || 'INR' ),
    inStock: raw.inStock !== false,
    // Spread, not `image: raw.image || undefined`, so a product with no image has no `image` KEY
    // at all. ShopProductHead gates the Product node on the field's presence.
    ...( raw.image ? { image: String( raw.image ) } : {} ),
    tagline,
    body,
  };
};

const VISIBLE = ( ( catalog as { products?: RawProduct[] } ).products || [] )
  .filter( raw => raw.visible !== false && !!raw.slug && !!raw.name );

export const SHOP_PRODUCTS: ShopProduct[] = VISIBLE
  .filter( raw => !isContributionRow( raw ) && !isTemplateSampleRow( raw ) )
  .map( project )
  .sort( ( a, b ) => a.name.localeCompare( b.name ) );

/**
 * EVERY product id this deployed snapshot knows about, lowercased. Not just `SHOP_PRODUCTS`.
 *
 * Read from the raw rows rather than from the projection on purpose, because the projection
 * EXCLUDES ids that are still perfectly real catalogue products: the contribution vehicle and the
 * twelve Wix template samples are filtered out of `/shop/` and remain purchasable by direct cart
 * reference. A "do I know this id?" test built on `SHOP_PRODUCTS` would answer no for thirteen
 * live products and throw their cart lines away.
 *
 * What this exists for is the other direction: a `wecare.cart.v1` row written before the catalogue
 * moved to site `c993128b` names a product id that does not exist anywhere on the new site. Sent
 * to checkout it 404s at `GET /stores/v3/products/{id}` and the customer is told to remove an item
 * — which they can at least do, but only after a failed payment attempt tells them to. Dropping it
 * at read time is the cheaper failure. See `reconcileStoredCart` in src/lib/cart.ts.
 */
export const KNOWN_CATALOGUE_PRODUCT_IDS: ReadonlySet<string> = new Set(
  ( ( catalog as { products?: RawProduct[] } ).products || [] )
    .map( raw => String( raw.id || '' ).trim().toLowerCase() )
    .filter( Boolean ),
);

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
