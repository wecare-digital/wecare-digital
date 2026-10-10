#!/usr/bin/env node
/**
 * Pull the Wix Stores catalog into a committed snapshot at
 * src/content/wix-catalog.json.
 *
 * WHY A SNAPSHOT AND NOT A RUNTIME FETCH. next.config.js sets output:'export', so the
 * public site is pre-generated HTML with no server of ours at runtime. Fetching through
 * our own Lambda at runtime works and already exists
 * (wecare.digital/api/wix-store/products), but it is authenticated - it answers 401 to
 * the public - and it puts a network hop and a spinner in front of a product list that
 * changes a few times a month. So the OUTPUT - names, prices, descriptions, which are
 * public information by definition - is committed, and the site renders it with no
 * network call at all.
 *
 * THE SNAPSHOT GOES STALE, and that is the trade-off being accepted. Re-run this after
 * any catalog edit in Wix. It is deliberately NOT wired into `npm run build`: a build
 * that reaches the network is a build that fails when the network does.
 *
 * USAGE - and note what is no longer required
 *   node scripts/fetch-wix-catalog.js
 *
 * NO CREDENTIAL. THIS IS THE POINT OF THE 2026-09-26 REWRITE.
 * ----------------------------------------------------------
 * This script used to demand `WIX_API_KEY` - an account-scoped admin bearer token - to
 * read seven public product names and prices. That was both unusable and unnecessary:
 *
 *   - UNUSABLE: `wecare/wix/headless-api-key` holds **0 versions**. The credential does
 *     not exist, so the old script could not run at all. Its own header carried a TODO
 *     saying the key "must come from AWS Secrets Manager" - but the better answer is to
 *     remove the credential from the problem, not to relocate it.
 *   - UNNECESSARY: WIX_CLIENT_ID is the PUBLIC half of the headless OAuth client. Wix
 *     exchanges it for an anonymous VISITOR token, which is exactly the scope a
 *     storefront page has, and a storefront can read the catalog. Least privilege, and
 *     it works today with nothing to provision.
 *
 * CONSEQUENCE, stated because it is a real behavioural change: a visitor token sees only
 * PUBLICLY VISIBLE products. An admin key would also return `visible: false` products.
 * All seven products are currently `visible: true`, so this makes no difference to the
 * present snapshot - but a product hidden in Wix will now simply be absent rather than
 * present-and-flagged. That is correct for a snapshot that feeds the public site, and it
 * is why `visible` is still emitted per product: if it is ever anything but `true`, the
 * scope assumption has changed.
 *
 * CATALOG V3, AND THE INCONSISTENCY THIS CLOSES
 * ---------------------------------------------
 * The old script used `stores-reader/v1/products/query` and its header recorded the
 * problem: `amplify/functions/ecommerce/wix-store/handler.py` uses `stores/v3` (17
 * references), so the repo read one catalog through two API versions. The old header
 * said porting was deferred because "mapping those fields without inspecting a real v3
 * response would be guesswork. Inspect one v3 payload first, then port slim()."
 *
 * Done. A real v3 payload for all seven products was inspected on 2026-09-26 via a
 * visitor token, and slim() below is mapped against it rather than against the docs.
 *
 * The site is on CATALOG_V3, confirmed by Wix itself rather than inferred:
 * `POST /stores/v1/products/query` returns HTTP 428 with
 * `applicationError.code = CATALOG_V3_CALLING_CATALOG_V1_API`. `stores-reader/v1` keeps
 * returning 200 on a V3 site, which is why the old endpoint choice looked fine - it is a
 * compatibility shim, so it failed silently rather than loudly. See
 * `scripts/probe_wix_capabilities.py`.
 *
 * WHAT CHANGED IN THE OUTPUT SCHEMA, because it is not a drop-in
 * -------------------------------------------------------------
 *   price            number -> DECIMAL STRING ("599.00"). V3 returns money as a string
 *                    on purpose. Keeping it a string preserves it exactly; anything
 *                    doing arithmetic must parse deliberately rather than inheriting a
 *                    float nobody chose.
 *   currency         moved from priceData.currency to a top-level `currency`
 *   formattedPrice   from actualPriceRange.minValue.formattedAmount ("Rs599.00")
 *   priceMax         NEW. V3 prices are a RANGE. min === max for all seven today, but a
 *                    product with variant pricing will differ and a single `price` would
 *                    quietly misreport it.
 *   discountedPrice  GONE. V3 has no equivalent. Its `compareAtPriceRange` is the
 *                    opposite idea - the higher struck-through "was" price - so mapping
 *                    one to the other would invert the meaning. Emitted as
 *                    `compareAtPrice` when Wix sends it; absent on all seven today.
 *   inStock          from inventory.availabilityStatus === 'IN_STOCK'
 *   descriptionHtml  from plainDescription. In V3 `description` is Ricos rich-content
 *                    NODES, not HTML, and `plainDescription` is the HTML string. Reading
 *                    `description` here would have produced a JSON blob in the UI.
 *   collectionIds    -> categoryIds, from directCategoriesInfo. V3 renamed collections
 *                    to categories and they live behind /categories/v1.
 *   sku              GONE. V3 has no product-level SKU; it is per variant.
 *   productType      now UPPERCASE ('PHYSICAL'), where V1 was lowercase ('physical').
 *   variantCount     from variantSummary.variantCount, not variants.length
 *   mediaCount       from media.itemsInfo.items, not media.items
 *   infoSectionCount NEW. V3 info sections carry the real product copy.
 *   productUrl       NEW. Wix's own canonical URL for the product.
 *   variants         NEW, 2026-10-04. See below - this script used to emit variantCount and no
 *                    variants array, so running it DESTROYED data the site depends on.
 *
 * IMAGES ARE NOT PULLED. Data only, and all seven products carry zero media items.
 *
 * VARIANTS ARE HYDRATED FROM A SECOND ENDPOINT, AND THIS CLOSES A LATENT DATA-LOSS BUG
 * ------------------------------------------------------------------------------------
 * Added 2026-10-04. Before this, slim() emitted `variantCount` from variantSummary and NO
 * `variants` array, and there was no top-level `variantVerifiedAt` - while the committed snapshot
 * carries both. So this script was no longer able to reproduce its own output: running it would
 * have silently dropped every variant array and broken three things at once, none of which would
 * have failed at build time:
 *
 *   - the merchandise fit/size selector in src/pages/shop/[slug].tsx, which renders only when
 *     `product.variants.length > 1` - it would simply stop appearing, and merchandise has 10
 *   - `toLineItems()` in src/lib/cart.ts, which sends `catalogReference.options.variantId`
 *   - the merchandise variant test in src/test/ShopCatalogue.test.tsx
 *
 * `/stores/v3/products/search` does NOT return variants, so a second call is required.
 *
 * THE REQUEST ENVELOPE IS NOT THE PRODUCT LOOP'S, and getting that wrong is a 400 rather than an
 * empty result. The search endpoint takes `{ search: { cursorPaging }, fields }`;
 * query-variants takes `{ fields, query }` with the paging INSIDE `query`. The endpoint, the
 * `productData.productId $in` filter and the cursor loop are mirrored from
 * amplify/functions/ecommerce/wix-store/handler.py:196-209, which is the only first-party
 * evidence in this repo of a working call against it.
 *
 * THE PROJECTION IS NOT MIRRORED - it is new here, and deliberately different. The Python helper's
 * `_read_only_variant_to_product_variant` emits the DASHBOARD shape; the site needs
 * `{ id, label, inStock }`. src/test/ShopIndexRedirect.test.ts assertion (h) is what pins this
 * shape against the committed snapshot, so a future change to either one is caught.
 *
 * `variantVerifiedAt` is emitted TOP-LEVEL, not per product, and records the date the variants
 * endpoint was actually read - it is the field that distinguishes "this snapshot has verified
 * variant data" from "this snapshot predates variant hydration".
 *
 * THE PER-VARIANT CATALOGUE IDENTITY, ADDED 2026-10-10, AND WHY IT IS PULLED RATHER THAN TYPED
 * -------------------------------------------------------------------------------------------
 * The variant projection used to stop at `{ id, label, inStock }`, so three values that ARE part
 * of Wix's own catalogue identity had to be written out by hand somewhere else -
 * `src/config/services.ts` declares them, and a hand-kept copy of an upstream id is a copy that
 * eventually disagrees with upstream. The repo has a documented history of exactly that failure
 * with Meta catalog ids. The `query-variants` call this script ALREADY makes returns all three,
 * so they are now read instead:
 *
 *   sku         from `sku`. The V3 SKU lives on the variant, not the product - which is why
 *               `sku` is asserted ABSENT at product level in tests/test_wix_catalog_snapshot.py
 *               and present here. `SERVICE-VAULT`, `SERVICE-DROP-DOCS` and so on.
 *   choiceId    from `optionChoices[0].optionChoiceIds.choiceId`. The id of the chosen option
 *               value, stable across a rename of the choice's display name.
 *   optionId    from `optionChoices[0].optionChoiceIds.optionId`. The id of the option the choice
 *               belongs to ('Service' for the services product).
 *   pricePaise  from `price.actualPrice.amount`, converted by digit slicing - see
 *               `paiseFromMajor()`. THE PRODUCT-LEVEL PRICE CANNOT STAND IN FOR IT: V3 reports a
 *               product as a price RANGE and `price` is the MINIMUM, so for the services product
 *               (49-350) four of the five variants would be understated by up to 301 rupees.
 *               `_variant_price_paise` in meta_catalog_sync.py refuses the product-level fallback
 *               outright when it is about to write to Meta, for that reason.
 *
 * ONLY THE FIRST optionChoices ENTRY is read for choiceId/optionId. A multi-option product
 * (merchandise is Style x Size) has several, and collapsing them to one pair would be wrong - but
 * `label` already carries the full combination, and the single-option services product is the only
 * consumer of the id pair today. A second option's ids are deliberately NOT invented here.
 *
 * ABSENT FIELDS ARE EMITTED AS EMPTY STRINGS, not omitted. A uniform row shape means a consumer
 * can read `row.sku` without first proving the key exists, and it makes "Wix sent nothing" visible
 * in the committed diff rather than silent.
 *
 * `image` IS WHATEVER WIX RETURNS, AND THIS SCRIPT IS A PURE OVERWRITE
 * -------------------------------------------------------------------
 * Owner decision, 2026-10-10, recorded because the alternative was chosen against explicitly.
 *
 * `image` at product level comes from `media.main`; `image` on a variant comes from that variant's
 * own `media` in the query-variants response. Both are copied and neither is derived, inferred or
 * carried forward. That matters because the committed snapshot used to hold FOUR DISTINCT service
 * pictures that this script never produced - they were written into the file by hand on 9 October,
 * along with a `serviceArtworkVerifiedAt` stamp, and a refresh therefore deleted them. Wix no
 * longer declares which gallery image belongs to which choice: every
 * `options[].choicesSettings.choices[].linkedMedia` comes back empty to a visitor token, and
 * query-variants answers with the product's MAIN image for all five rows.
 *
 * Three ways to keep the old pictures were considered and REJECTED by the owner:
 * carrying the previous snapshot's values forward (this script would become a merge, and the
 * snapshot would stop being a read of Wix), joining choice name to media `altText` (an inference
 * Wix does not declare, which a rename in the dashboard breaks silently), and blocking the sync
 * until the artwork is re-linked in Wix.
 *
 * THE ACCEPTED CONSEQUENCE: the Meta/WhatsApp catalogue items for the services product all show
 * the product's main image until the per-choice artwork is re-linked in the Wix dashboard. The fix
 * belongs in Wix, not in a mirror of Wix - the same reasoning `slim()` already applies to
 * `productType`. Nothing is invented here to cover for it: `blockers()` in meta_catalog_sync.py
 * reports an imageless item rather than substituting a placeholder, because an item with a
 * made-up picture would pass Meta commerce review under false pretences. Nine of the ten products
 * carry no media at all today and are blocked for exactly that reason.
 */

// ESM, because package.json declares "type": "module" - a require() here dies with
// "require is not defined in ES module scope", which reads like a broken script rather
// than a module-system mismatch. __dirname does not exist in ESM either, hence the
// fileURLToPath dance.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname( fileURLToPath( import.meta.url ) );
const OUT = path.resolve( HERE, '..', 'src', 'content', 'wix-catalog.json' );
const CONFIG = path.resolve( HERE, '..', 'src', 'config', 'wix.ts' );

const API = 'https://www.wixapis.com';
const PAGE_SIZE = 100;

// Field projections. V3 omits description, currency, url and category info unless asked,
// so a search without these returns a product with no price currency and no description
// and looks like an empty catalog. Mirrors CATALOG_PRODUCT_FIELDS in
// amplify/functions/ecommerce/wix-store/handler.py so the two consumers of this catalog
// ask for the same shape.
const FIELDS = [
  'URL',
  'CURRENCY',
  'MEDIA_ITEMS_INFO',
  'PLAIN_DESCRIPTION',
  'DIRECT_CATEGORIES_INFO',
  'VARIANT_OPTION_CHOICE_NAMES',
  'INFO_SECTION',
];

function die( msg ) {
  console.error( `fetch-wix-catalog: ${msg}` );
  process.exit( 1 );
}

/**
 * Read the public client id out of the committed config rather than hardcoding it.
 *
 * Parsed with a regex instead of imported because this is plain Node ESM and wix.ts is
 * TypeScript - importing it would need a loader for one string. Reading the real file
 * means this script cannot drift away from the id the application uses, which a second
 * copy of the constant would eventually do.
 */
function publicClientId() {
  let text;
  try {
    text = fs.readFileSync( CONFIG, 'utf-8' );
  } catch {
    die( `cannot read ${path.relative( process.cwd(), CONFIG )}` );
  }
  const match = /export const WIX_CLIENT_ID = '([^']+)'/.exec( text );
  if ( !match ) die( `WIX_CLIENT_ID not found in ${path.relative( process.cwd(), CONFIG )}` );
  return match[ 1 ];
}

/** Anonymous visitor token. Held in memory, never logged, never written to the output. */
async function visitorToken( clientId ) {
  const res = await fetch( `${API}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify( { clientId, grantType: 'anonymous' } ),
  } );
  if ( !res.ok ) {
    const body = await res.text().catch( () => '' );
    die( `could not mint a visitor token: HTTP ${res.status}. ${body.slice( 0, 200 )}\n` +
      '  This needs no secret - it uses the PUBLIC client id from src/config/wix.ts.\n' +
      '  A failure here means the headless OAuth client was changed or removed in Wix.' );
  }
  const data = await res.json();
  if ( !data.access_token ) die( 'token response carried no access_token' );
  return data.access_token;
}

const money = range => ( range && range.minValue ) || {};

/** First media item url for a product or a variant, '' when Wix sent none. */
const mediaUrl = item => String( ( ( item || {} ).image || {} ).url || '' );

/**
 * A Wix decimal-string amount in major units ( '350.00' ) -> integer paise, or null.
 *
 * BY CONCATENATING DIGITS, not by multiplying, which is the same rule `price_text` in
 * meta_catalog_sync.py applies in the other direction and for the same reason: `3.50 * 100` is a
 * binary-floating-point question with a wrong answer available, and a one-paise disagreement with
 * a checkout total has to be impossible rather than unlikely.
 *
 * An amount with more than two decimal places is REFUSED rather than rounded - a fractional paise
 * in a catalogue price is a data error in Wix, and rounding it here would hide it and plant the
 * mismatch further downstream. `paise_from_major` refuses it too.
 */
function paiseFromMajor( value ) {
  const text = String( value == null ? '' : value ).trim();
  if ( !/^\d+(\.\d{1,2})?$/.test( text ) ) return null;
  const [ rupees, fraction = '' ] = text.split( '.' );
  const paise = Number( rupees + fraction.padEnd( 2, '0' ) );
  return paise > 0 ? paise : null;
}

/**
 * Hydrate every product's variants from /stores/v3/products/query-variants.
 *
 * Returns a Map of productId -> [ { id, label, inStock, sku, choiceId, optionId, pricePaise } ],
 * with the API's own order preserved within each product. Order matters: the fit/size <select>
 * renders in array order, and sorting it here would make the committed snapshot churn whenever
 * Wix reordered its response.
 *
 * `visible !== false` rather than `visible === true`: a row that omits the field is treated as
 * visible, which matches how slim() reads the product-level flag.
 */
async function fetchVariants( token, productIds ) {
  const byProduct = new Map( productIds.map( id => [ id, [] ] ) );
  let cursor = '';

  // Same guard as the product loop, and for the same reason: a cursor that never empties would
  // otherwise spin forever. 1000 per page against seven products means one request today.
  for ( let guard = 0; guard < 50; guard++ ) {
    const query = cursor
      ? { cursorPaging: { limit: 1000, cursor } }
      : { filter: { 'productData.productId': { $in: productIds } }, cursorPaging: { limit: 1000 } };

    const res = await fetch( `${API}/stores/v3/products/query-variants`, {
      method: 'POST',
      headers: { 'Authorization': token, 'Content-Type': 'application/json' },
      // NOTE THE SHAPE: { fields, query }, with paging inside `query`. The product search above
      // takes { search: { cursorPaging }, fields } - sending that shape here returns 400.
      body: JSON.stringify( { fields: [ 'CURRENCY' ], query } ),
    } );

    if ( !res.ok ) {
      const body = await res.text().catch( () => '' );
      die( `HTTP ${res.status} from the Wix variants endpoint. ${body.slice( 0, 300 )}\n` +
        '  A 400 here usually means the request envelope was built like the product search.\n' +
        '  query-variants takes { fields, query } with cursorPaging INSIDE query - see\n' +
        '  amplify/functions/ecommerce/wix-store/handler.py for the working call.\n' +
        '  Nothing is written when this fails: the existing snapshot keeps its variants.' );
    }

    const data = await res.json();
    const rows = data.variants || [];

    for ( const row of rows ) {
      if ( row.visible === false ) continue;
      const productId = ( row.productData || {} ).productId;
      if ( !byProduct.has( productId ) ) continue;
      // Only the FIRST option pair - see the header. A multi-option product has several and
      // collapsing them would misreport the combination that `label` already carries in full.
      const ids = ( ( row.optionChoices || [] )[ 0 ] || {} ).optionChoiceIds || {};
      byProduct.get( productId ).push( {
        id: row.variantId || row.id,
        label: ( row.optionChoices || [] )
          .map( c => ( c.optionChoiceNames || {} ).choiceName )
          .filter( Boolean )
          .join( ' / ' ) || 'Standard',
        inStock: ( row.inventoryStatus || {} ).inStock === true,
        sku: String( row.sku || '' ),
        choiceId: String( ids.choiceId || '' ),
        optionId: String( ids.optionId || '' ),
        // EXACTLY what Wix returns for this variant and nothing else - see the header. Today that
        // is the product's main image for every row, because no choice carries linked media.
        image: mediaUrl( row.media ),
        // The variant's OWN price. The product-level `price` is the range minimum and would be
        // wrong for most variants of a product priced per choice.
        pricePaise: paiseFromMajor( ( ( row.price || {} ).actualPrice || {} ).amount ),
      } );
    }

    const meta = data.pagingMetadata || {};
    cursor = ( meta.cursors || {} ).next || '';
    if ( !rows.length || !cursor ) break;
  }

  return byProduct;
}

/**
 * Keep only the fields the site actually renders. Two reasons beyond tidiness: the raw
 * payload is mostly media and inventory internals, and a snapshot that mirrors every
 * upstream field turns every unrelated Wix change into a diff in this repo.
 */
function slim( p, variantsByProduct ) {
  const min = money( p.actualPriceRange );
  const max = ( p.actualPriceRange && p.actualPriceRange.maxValue ) || {};
  const compareAt = money( p.compareAtPriceRange );
  const categories = ( ( p.directCategoriesInfo || {} ).categories || [] )
    .map( c => c.id )
    .filter( Boolean );

  return {
    id: p.id,
    name: p.name || '',
    slug: p.slug || '',
    // productType is 'PHYSICAL' for all seven today, which is wrong for the service
    // ones - it makes Wix demand a shipping address at checkout. Recorded as-is rather
    // than corrected here, because the fix belongs in Wix, not in a mirror of Wix.
    productType: p.productType || '',
    // Should always be true: a visitor token cannot see hidden products. If this is ever
    // false, the auth scope changed.
    visible: p.visible !== false,
    ribbon: p.ribbon || '',
    // DECIMAL STRINGS, exactly as Wix sends them. Do not coerce to a float here - see
    // the schema note in the header.
    price: min.amount || null,
    priceMax: max.amount || null,
    currency: p.currency || '',
    formattedPrice: min.formattedAmount || '',
    compareAtPrice: compareAt.amount || null,
    inStock: ( p.inventory || {} ).availabilityStatus === 'IN_STOCK',
    // Wix returns this as HTML. It is stored raw and MUST be treated as untrusted when
    // rendered - it is authored in Wix, outside this repo's review.
    descriptionHtml: p.plainDescription || '',
    categoryIds: categories,
    mainCategoryId: p.mainCategoryId || '',
    optionCount: ( p.options || [] ).length,
    modifierCount: ( p.modifiers || [] ).length,
    variantCount: ( p.variantSummary || {} ).variantCount || 0,
    mediaCount: ( ( ( p.media || {} ).itemsInfo || {} ).items || [] ).length,
    infoSectionCount: ( p.infoSections || [] ).length,
    productUrl: `https://wecare.digital/shop/${p.slug}/`,
    // Wix's own MAIN image, falling back to the first gallery item. '' when the product carries no
    // media, which is the state nine of the ten products are in - and which `blockers()` in
    // meta_catalog_sync.py reports rather than papering over with a placeholder.
    image: mediaUrl( ( p.media || {} ).main )
      || mediaUrl( ( ( ( p.media || {} ).itemsInfo || {} ).items || [] )[ 0 ] ),
    // Hydrated from query-variants, not from the product payload - the search endpoint does not
    // return variants at all. Emitting this is what stops a refresh destroying the fit/size
    // selector and the catalogReference.options.variantId the cart sends.
    variants: ( variantsByProduct && variantsByProduct.get( p.id ) ) || [],
  };
}

async function main() {
  const token = await visitorToken( publicClientId() );

  const products = [];
  let cursor = null;

  // Cursor paging, not offset. V3 dropped offset paging, and an offset loop against V3
  // silently returns page 1 forever. Seven products fit in one request today; hardcoding
  // that assumption is how a catalog truncates at 101.
  for ( let guard = 0; guard < 50; guard++ ) {
    const cursorPaging = cursor ? { limit: PAGE_SIZE, cursor } : { limit: PAGE_SIZE };
    const res = await fetch( `${API}/stores/v3/products/search`, {
      method: 'POST',
      headers: { 'Authorization': token, 'Content-Type': 'application/json' },
      body: JSON.stringify( { search: { cursorPaging }, fields: FIELDS } ),
    } );

    if ( !res.ok ) {
      const body = await res.text().catch( () => '' );
      die( `HTTP ${res.status} from Wix. ${body.slice( 0, 300 )}\n` +
        '  428 CATALOG_V1_CALLING_CATALOG_V3_API would mean the site moved back to\n' +
        '  Catalog V1, which would make this whole script the wrong shape.\n' +
        '  Re-check with: python scripts/probe_wix_capabilities.py' );
    }

    const data = await res.json();
    const page = data.products || [];
    products.push( ...page );

    const meta = data.pagingMetadata || {};
    cursor = ( meta.cursors || {} ).next || null;
    if ( !page.length || !cursor ) break;
  }

  if ( !products.length ) {
    die( 'Wix returned 0 products.\n' +
      '  The existing snapshot is left untouched rather than emptied, because an empty\n' +
      '  catalog is far more likely to be a scope or query problem than a real change.' );
  }

  // Read the variants BEFORE building the snapshot, so a failure here writes nothing at all and
  // the committed file keeps the variant data it already has.
  const variantsByProduct = await fetchVariants(
    token, products.map( p => p.id ).filter( Boolean ),
  );
  const variantVerifiedAt = new Date().toISOString();

  const slimmed = products
    .map( p => slim( p, variantsByProduct ) )
    // Stable order so the committed file does not churn when Wix reorders its response.
    .sort( ( a, b ) => a.slug.localeCompare( b.slug ) );

  const snapshot = {
    // No token, no account id, no site id in the output. The site id is a tenant
    // identifier and there is no reason for it to sit in a public bundle.
    source: 'wix stores/v3 products/search (anonymous visitor token)',
    catalogVersion: 'V3',
    fetchedAt: new Date().toISOString(),
    productCount: slimmed.length,
    products: slimmed,
    // TOP-LEVEL, not per product: it records when the variants ENDPOINT was read, which is one
    // fact about the whole snapshot rather than seven facts about seven products.
    variantVerifiedAt,
  };

  fs.mkdirSync( path.dirname( OUT ), { recursive: true } );
  fs.writeFileSync( OUT, JSON.stringify( snapshot, null, 2 ) + '\n' );

  console.log( `fetch-wix-catalog: wrote ${slimmed.length} product(s) to ${path.relative( process.cwd(), OUT )}` );
  for ( const p of slimmed ) {
    const range = p.price !== p.priceMax ? `${p.formattedPrice}+` : p.formattedPrice;
    console.log( `  ${p.slug.padEnd( 20 )} ${range.padStart( 11 )}  ${p.productType.padEnd( 9 )} ` +
      // Both numbers, because they come from different endpoints: variantCount is
      // variantSummary from the product search, variants.length is what query-variants
      // actually returned. A disagreement is the visible symptom of a hydration problem.
      `opts=${p.optionCount} variants=${p.variantCount}/${p.variants.length} media=${p.mediaCount} ` +
      `info=${p.infoSectionCount}${p.visible ? '' : '  (HIDDEN)'}` );
  }
}

main().catch( e => die( e && e.message ? e.message : String( e ) ) );
