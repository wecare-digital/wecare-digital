/**
 * The browser shopping cart for /shop/ - references and quantities only.
 *
 * THE ONE RULE THIS FILE EXISTS TO ENFORCE: the browser never sends a price, an amount, a
 * currency or any financial figure to the checkout. A cart entry carries a catalogue REFERENCE
 * (the product's Wix catalogue id, with its slug and name for display) and a QUANTITY, and nothing
 * else reaches the server. The amount charged is decided server-side from a live Wix checkout read
 * and compared in integer paise (amplify/functions/ecommerce/checkout/handler.py rule 2), so a
 * number invented here could only ever be wrong or dangerous. `formattedPrice` is kept for the
 * cart LIST rendering only - it is Wix's own passthrough string, never rebuilt, and it is stripped
 * out entirely by toLineItems(): see the test that asserts the serialized payload has no
 * price-like key.
 *
 * WHY LOCALSTORAGE. The cart must survive the sign-in/register redirect (a public shopper who
 * proceeds is bounced to the OTP step and back), so it cannot live in component state. It is not
 * sensitive - it is a list of catalogue references a visitor chose - so localStorage is the right
 * store; the session token stays in sessionStorage (customerAuth.ts) where it belongs. Every
 * window/storage access is SSR-guarded (typeof window === 'undefined'), matching customerAuth.ts,
 * because these pages are statically exported and this module is imported into prerendered code.
 *
 * THE lineItems SHAPE MATCHES THE BACKEND CONTRACT, AND IT IS MEASURED RATHER THAN GUESSED.
 *
 * THE PARAGRAPH THAT USED TO BE HERE WAS FALSE, AND ITS FALSENESS COST A WRONG DIAGNOSIS OF A
 * LIVE PAYMENT OUTAGE (2026-10-04). It said: "The products are dummy placeholders today, so the
 * exact nested Wix catalogReference object (catalogItemId/appId) is not knowable from this repo;
 * toLineItems() therefore sends the product's Wix catalogue id as the catalogReference ... and is
 * trivially remapped to the final nested shape once real products are chosen." That described an
 * EARLIER implementation. The code moved to the real nested shape and the comment did not, so a
 * reader looking for the cause of a 502 found a self-declared guess sitting on top of correct
 * code and reasonably suspected it.
 *
 * What `toLineItems()` actually emits, and why each part is right, verified against the LIVE Wix
 * Catalog V3 API on 2026-10-04:
 *
 *   { catalogReference: { appId, catalogItemId, options?: { variantId } }, quantity }
 *
 *   * `appId` is the Wix Stores app id `215238eb-22a5-4c36-9e7b-e7c08025e04e`, and it must equal
 *     `cart_v2.STORES_APP_ID` exactly -- `resolved_catalog_lines` refuses any other value as
 *     "invalid catalogue reference". It does. Pinned by a test, because the two are separate
 *     declarations in two languages.
 *   * `catalogItemId` is the V3 PRODUCT id, never the slug and never a variant id. A variant id
 *     here would 404 at `GET /stores/v3/products/{id}`.
 *   * `options.variantId` is present only when the line carries one, which is the correct V3
 *     shape: a no-option product's reference carries no `options`.
 *
 * AND THE VARIANT IDS IN THE COMMITTED SNAPSHOT ARE LIVE, NOT STALE V1 LEFTOVERS. Measured for
 * all seven shop products: 19 of 19 committed variant ids exist in the live V3 response, every
 * one `visible: true` and `inStock: true`. A V3 product with `options: []` still has exactly one
 * real variant with a real id, and the snapshot holds that id. So `resolved_catalog_lines`
 * accepts every line this function builds, and it is NOT the source of the live 502.
 */

import { KNOWN_CATALOGUE_PRODUCT_IDS, SHOP_PRODUCTS } from '../content/shop';
import type { ShopProduct, ShopVariant } from '../content/shop';
import type { ContributionChoice } from '../config/contribution';
import { CONTRIBUTION_PRODUCT_ID, contributionChoice } from '../config/contribution';
import { SERVICES_PRODUCT_ID, serviceChoice } from '../config/services';
import { trackCatalogAdd } from './metaCatalogAnalytics';

/** localStorage key. Namespaced and versioned so a shape change can be migrated, not guessed. */
const CART_KEY = 'wecare.cart.v1';

/**
 * Fired on `window` after every write, so the header's Shopping Bag badge can re-read the count.
 *
 * The browser's own `storage` event is not enough on its own: it fires in OTHER tabs and never in
 * the one that made the write, so adding an item on /shop/<slug>/ would leave the badge in the
 * same document stale until the next navigation. The header listens for both.
 */
export const CART_CHANGED_EVENT = 'wecare:cart-changed';

export interface CartItem {
  productId?: string;
  variantId?: string;
  /** The catalogue reference: the product's Wix catalogue id. Never a price. */
  ref: string;
  /** The product slug, so the cart can link back to /shop/<slug>/. */
  slug: string;
  /** Display name for the cart list. */
  name: string;
  /** Wix's own formatted price string, e.g. "₹6,999.00". DISPLAY ONLY - never sent to the server. */
  formattedPrice: string;
  /** How many, always a positive integer. */
  quantity: number;
}

/**
 * One line of a claimed WhatsApp hand-off: a catalogue reference and a quantity.
 *
 * Declared HERE rather than beside the claim call, because this module owns the one storage writer
 * and `mergeClaimedLines` is what consumes the shape; `src/lib/whatsappBasket.ts` imports the type
 * so there is a single declaration to audit for the absence of a price field.
 */
export interface ClaimedLine {
  productId: string;
  variantId: string;
  quantity: number;
}

/** One entry of the checkout `create` payload: a catalogue reference and a quantity, nothing else. */
export interface CheckoutLineItem {
  catalogReference: { appId: string; catalogItemId: string; options?: { variantId: string } };
  quantity: number;
}

/** True when there is a browser to read storage from. Mirrors customerAuth.ts's SSR guard. */
function hasWindow (): boolean {
  return typeof window !== 'undefined';
}

/** A quantity coerced to a positive integer; anything invalid becomes 1. */
function normaliseQuantity ( value: unknown ): number {
  const n = Math.floor( Number( value ) );
  return Number.isFinite( n ) && n > 0 ? n : 1;
}

/**
 * Resolve the CURRENT catalogue product for a stored line.
 *
 * Rows written since 2026-10-01 carry `productId`, and that ID is authoritative. Older
 * `wecare.cart.v1` rows predate both `productId` and variant capture; for those rows only, fall
 * back to the historical `ref` / slug. That narrow fallback is what repairs an old browser cart
 * without ever remapping a modern row whose product ID points somewhere else.
 */
function currentProduct ( item: CartItem ): ShopProduct | null {
  if ( item.productId )
  {
    return SHOP_PRODUCTS.find( product => product.id === item.productId ) || null;
  }
  const baseRef = String( item.ref || '' ).split( ':' )[ 0 ];
  return SHOP_PRODUCTS.find( product =>
    product.id === baseRef || product.slug === item.slug || product.slug === baseRef ) || null;
}

/** The current in-stock variant a stored line means, when that meaning is unambiguous. */
function currentVariant ( item: CartItem, product: ShopProduct ): ShopVariant | null {
  const available = ( product.variants || [] ).filter( variant => variant.inStock );
  const exact = item.variantId
    ? available.find( variant => variant.id === item.variantId )
    : undefined;
  if ( exact ) return exact;

  // A single-variant product is safe to repair automatically: there is no customer choice to
  // invent. This also upgrades the six pre-variant cart rows created before 2026-10-01.
  if ( available.length === 1 ) return available[ 0 ];

  // If a variant ID changed but the old row already carries the human label, preserve the
  // customer's choice by matching that exact label. Never choose among multiple possibilities.
  const labelled = available.filter(
    variant => item.name === `${product.name} (${variant.label})`,
  );
  return labelled.length === 1 ? labelled[ 0 ] : null;
}

/** A Wix catalogue id: a lowercase UUID. What a `productId` and a modern `ref` base both are. */
const CATALOGUE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Should an UNRESOLVABLE stored line be thrown away rather than carried into checkout?
 *
 * Only ever consulted for a line `currentProduct` could not resolve, and the predicate is
 * deliberately narrow: **the line names a Wix catalogue id (a UUID) that this snapshot has never
 * heard of.** That is exactly the pre-migration row - `/shop/` moved to Wix site `c993128b` on
 * 2026-10-05 and every product id was re-minted, so a browser holding the old ₹1 test product
 * carries a well-formed id that exists nowhere in the new catalogue.
 *
 * Three things it is careful NOT to do:
 *
 *   * **It does not key on `SHOP_PRODUCTS`.** That list excludes thirteen real, purchasable rows -
 *     the contribution vehicle and the twelve Wix template samples - so "absent from /shop/" is not
 *     "absent from the catalogue". `KNOWN_CATALOGUE_PRODUCT_IDS` reads the raw snapshot for that
 *     reason, and a contribution line is kept on CONFIG identity whether or not the snapshot has
 *     been refreshed at all.
 *   * **It does not touch a non-UUID `ref`.** Those are the pre-2026-10 rows that carry a slug or
 *     an opaque reference, and the slug fallback in `currentProduct` is what repairs them; a row
 *     that fallback cannot place keeps today's behaviour exactly rather than being deleted on a
 *     guess about an id shape the catalogue never used.
 *   * **It does not claim to be the authority.** The live Wix catalogue is, and the server still
 *     refuses what it does not recognise. This only spares a customer learning it after pressing
 *     Checkout.
 */
function droppableUnknown ( item: CartItem ): boolean {
  if ( isContributionItem( item ) || isServiceItem( item ) ) return false;
  const claimed = [ item.productId, String( item.ref || '' ).split( ':' )[ 0 ] ]
    .map( value => String( value || '' ).trim().toLowerCase() )
    .filter( value => CATALOGUE_ID.test( value ) );
  return claimed.length > 0 && !claimed.some( id => KNOWN_CATALOGUE_PRODUCT_IDS.has( id ) );
}

/**
 * Reconcile persisted rows against the catalogue bundled with THIS deployed storefront.
 *
 * This does not make the browser a price authority. It only upgrades identifiers and display
 * strings; checkout still sends references + quantities and the backend still prices from live
 * Wix. A multi-variant legacy row with no recoverable choice is deliberately left WITHOUT a
 * variant so /cart/ can ask the customer to choose one instead of silently guessing a size.
 *
 * AN ID FROM THE PREVIOUS SITE IS NOW DROPPED RATHER THAN CARRIED. `/shop/` moved to Wix site
 * `c993128b` on 2026-10-05 and every product id was re-minted, so a returning visitor's
 * localStorage can hold a product id (e.g. the old ₹1 test product) that exists nowhere in the new
 * catalogue. Carried into `toLineItems()` it reaches `GET /stores/v3/products/{id}`, 404s, and the
 * customer is told "An item in your cart is no longer available" only AFTER pressing Checkout.
 * Dropping it on read means they see the cart they can actually buy, and `readCart` persists the
 * pruned list because `changed` moves with the length.
 *
 * Deliberately NOT a blanket "drop anything /shop/ does not list" - see `droppableUnknown`.
 */
function reconcileStoredCart ( items: CartItem[] ): { items: CartItem[]; changed: boolean } {
  const reconciled = items.flatMap( item => {
    const product = currentProduct( item );
    if ( !product ) return droppableUnknown( item ) ? [] : [ item ];

    const variant = currentVariant( item, product );
    const hasMultiple = ( product.variants || [] ).length > 1;
    const next: CartItem = {
      productId: product.id,
      ...( variant ? { variantId: variant.id } : {} ),
      // Keep an unresolved legacy ref distinct until the customer chooses an option. Once a
      // variant is known, the ref is the canonical product+variant identity used for cart merging.
      ref: variant ? `${product.id}:${variant.id}` : item.ref,
      slug: product.slug,
      name: hasMultiple && variant ? `${product.name} (${variant.label})` : product.name,
      formattedPrice: product.formattedPrice,
      quantity: item.quantity,
    };
    return [ next ];
  } );

  // A legacy line and a newer line can reconcile to the same canonical ref. Merge only then, so
  // the customer cannot be charged twice for two storage records that now mean one cart line.
  const merged: CartItem[] = [];
  for ( const item of reconciled )
  {
    const existing = merged.find( candidate => candidate.ref === item.ref );
    if ( existing ) existing.quantity += item.quantity;
    else merged.push( { ...item } );
  }

  return {
    items: merged,
    changed: JSON.stringify( merged ) !== JSON.stringify( items ),
  };
}

/** Parse and validate whatever is in storage into a clean CartItem[]. Never throws. */
function parseCart ( raw: string | null ): CartItem[] {
  if ( !raw ) return [];
  let parsed: unknown;
  try
  {
    parsed = JSON.parse( raw );
  }
  catch
  {
    return [];
  }
  if ( !Array.isArray( parsed ) ) return [];
  const out: CartItem[] = [];
  for ( const entry of parsed )
  {
    const item = entry as Partial<CartItem>;
    const ref = String( item?.ref || '' );
    if ( !ref ) continue;
    out.push( {
      ref,
      ...( item.productId ? { productId: String( item.productId ) } : {} ),
      ...( item.variantId ? { variantId: String( item.variantId ) } : {} ),
      slug: String( item?.slug || '' ),
      name: String( item?.name || '' ),
      formattedPrice: String( item?.formattedPrice || '' ),
      quantity: normaliseQuantity( item?.quantity ),
    } );
  }
  return out;
}

/** The current cart, or [] on the server / when storage is empty or corrupt. */
export function readCart (): CartItem[] {
  if ( !hasWindow() ) return [];
  const parsed = parseCart( window.localStorage.getItem( CART_KEY ) );
  const reconciled = reconcileStoredCart( parsed );
  if ( reconciled.changed )
  {
    // Migration is an implementation detail of the read, not a user cart action. Write directly
    // rather than dispatching CART_CHANGED_EVENT and synchronously re-entering every cart listener.
    window.localStorage.setItem( CART_KEY, JSON.stringify( reconciled.items ) );
  }
  return reconciled.items;
}

/** Persist the cart. No-op on the server. */
function writeCart ( items: CartItem[] ): void {
  if ( !hasWindow() ) return;
  window.localStorage.setItem( CART_KEY, JSON.stringify( items ) );
  announce();
}

/**
 * Tell this document the cart moved. Guarded on CustomEvent as well as window, because the SSR
 * guard above only proves there is a window - and jsdom-less environments have neither.
 */
function announce (): void {
  if ( !hasWindow() || typeof window.CustomEvent !== 'function' ) return;
  window.dispatchEvent( new window.CustomEvent( CART_CHANGED_EVENT ) );
}

/**
 * Add a product to the cart, or increase its quantity if it is already there. Keyed on the
 * product's catalogue id (its stable reference), not its name, so a renamed product still merges.
 * Returns the updated cart.
 */
export function addItem ( product: ShopProduct, qty = 1, selectedVariantId?: string ): CartItem[] {
  const variantId = selectedVariantId || ( product.variants?.length === 1 ? product.variants[0].id : undefined );
  if ( product.variants && product.variants.length > 1 && !variantId ) throw new Error( 'Choose an option first.' );
  if ( variantId && !product.variants?.some( variant => variant.id === variantId && variant.inStock ) ) throw new Error( 'Choose an available option.' );
  const ref = String( product.id || product.slug || '' ) + ( variantId ? `:${variantId}` : '' );
  if ( !ref ) return readCart();
  const quantity = normaliseQuantity( qty );
  const items = readCart();
  const existing = items.find( item => item.ref === ref );
  if ( existing )
  {
    existing.quantity += quantity;
  }
  else
  {
    items.push( {
      productId: product.id,
      ...( variantId ? { variantId } : {} ),
      ref,
      slug: String( product.slug || '' ),
      name: product.variants && product.variants.length > 1
        ? `${product.name} (${product.variants.find( variant => variant.id === variantId )!.label})`
        : String( product.name || '' ),
      formattedPrice: String( product.formattedPrice || '' ),
      quantity,
    } );
  }
  writeCart( items );
  return items;
}

/**
 * In-stock choices for a cart line whose current product has multiple variants.
 *
 * Empty means either "this item has no customer-selectable choice" or "the product is not in this
 * deployed snapshot"; the live backend remains authoritative for the latter.
 */
export function availableVariantsForItem ( item: CartItem ): ShopVariant[] {
  const product = currentProduct( item );
  if ( !product || ( product.variants || [] ).length <= 1 ) return [];
  return ( product.variants || [] ).filter( variant => variant.inStock );
}

/** Whether checkout must stop and ask the customer to choose a current variant for this line. */
export function needsVariantSelection ( item: CartItem ): boolean {
  const variants = availableVariantsForItem( item );
  if ( variants.length === 0 ) return false;
  return !item.variantId || !variants.some( variant => variant.id === item.variantId );
}

/**
 * Replace one cart line's variant with an explicitly chosen CURRENT in-stock variant.
 *
 * This is the repair path for legacy Merchandise rows that were created before the store captured
 * Fit/Size. It is intentionally explicit: when several variants exist, the browser never guesses.
 */
export function setVariant ( ref: string, variantId: string ): CartItem[] {
  const items = readCart();
  const index = items.findIndex( item => item.ref === ref );
  if ( index < 0 ) return items;

  const item = items[ index ];
  const product = currentProduct( item );
  const variant = product?.variants?.find(
    candidate => candidate.id === variantId && candidate.inStock,
  );
  if ( !product || !variant ) throw new Error( 'Choose an available option.' );

  const next: CartItem = {
    ...item,
    productId: product.id,
    variantId: variant.id,
    ref: `${product.id}:${variant.id}`,
    slug: product.slug,
    name: ( product.variants || [] ).length > 1
      ? `${product.name} (${variant.label})`
      : product.name,
    formattedPrice: product.formattedPrice,
  };

  const remaining = items.filter( ( _candidate, candidateIndex ) => candidateIndex !== index );
  const duplicate = remaining.find( candidate => candidate.ref === next.ref );
  if ( duplicate ) duplicate.quantity += next.quantity;
  else remaining.splice( index, 0, next );
  writeCart( remaining );
  return remaining;
}

/**
 * Set the exact quantity for a reference. A quantity of zero or below removes the line, so the
 * quantity control can reach "gone" without a separate button. Returns the updated cart.
 */
export function setQuantity ( ref: string, qty: number ): CartItem[] {
  const items = readCart();
  const next = Math.floor( Number( qty ) );
  if ( !Number.isFinite( next ) || next <= 0 )
  {
    return removeItem( ref );
  }
  const existing = items.find( item => item.ref === ref );
  if ( existing ) existing.quantity = next;
  writeCart( items );
  return items;
}

/** Remove a line by reference. Returns the updated cart. */
export function removeItem ( ref: string ): CartItem[] {
  const items = readCart().filter( item => item.ref !== ref );
  writeCart( items );
  return items;
}

/**
 * Empty the cart. Called on a `VERIFIED_PAID` verify response and nowhere else.
 *
 * NOT ON A PREPARE, which is what this docstring used to claim and what no caller ever did. A
 * prepared checkout is not a paid one: clearing there would empty the basket of a customer who
 * closed the Razorpay modal. The single call site is `src/pages/cart.tsx`'s verify handler, on the
 * one status where the server has confirmed an authoritative capture.
 */
export function clearCart (): void {
  if ( !hasWindow() ) return;
  window.localStorage.removeItem( CART_KEY );
  announce();
}

/**
 * How many lines-worth of things are in the cart, for the header badge and the empty check.
 *
 * NO CONTRIBUTION SPECIAL CASE, and the absence is deliberate rather than an omission. Under the
 * retired amount-as-quantity model a Rs.400 contribution was `quantity: 400`, so a plain sum
 * rendered "Shopping Bag, 400 items" and a `99+` badge for one contribution. A contribution is now
 * a fixed-price variant at `quantity: 1`, so the sum is already the honest answer and an exception
 * here would be dead code with a misleading comment attached.
 */
export function cartCount (): number {
  return readCart().reduce( ( sum, item ) => sum + item.quantity, 0 );
}

/**
 * Is this line the contribution vehicle? On `productId`, so a `ref` format change cannot break it.
 *
 * ALL THREE AMOUNTS ARE ONE PRODUCT, which is what makes a product-id test sufficient: the live
 * `Contribute` product carries an "Amount" option with three variants, so the choice is the
 * `variantId` and the identity is the `productId`.
 *
 * Returns false for every line when nothing is configured, which makes every helper below inert
 * rather than guessing. The browser's answer is a COURTESY: the server re-derives recognition from
 * its own committed set and refuses what it does not like.
 */
export const isContributionItem = ( item: CartItem ): boolean =>
  !!CONTRIBUTION_PRODUCT_ID && item.productId === CONTRIBUTION_PRODUCT_ID;

/** The amount a contribution line represents, or null when the line is not one of the three. */
export const contributionOf = ( item: CartItem ): ContributionChoice | null =>
  isContributionItem( item ) ? contributionChoice( item.variantId ) : null;

/**
 * Exactly one contribution line per cart, and choosing an amount SETS it.
 *
 * THE ARGUMENT IS A CHOICE, NOT AN AMOUNT (owner model change, 2026-10-04). It used to take a
 * rupee integer and validate it against ₹10–₹1,00,000 bounds, because the figure became the line's
 * quantity and a free-text field could produce anything. There are now three fixed-price variants
 * and no free text, so the only thing to check is membership: an unrecognised `variantId` returns
 * the cart unchanged and writes nothing. Nothing is clamped and nothing is coerced, because there
 * is no longer a number to coerce.
 *
 * `addItem` is NOT reused: it INCREMENTS, so choosing ₹100 and then ₹500 would leave two
 * contribution lines, which is a basket the server refuses as two contributions. Choosing an
 * amount replaces the line.
 *
 * Returns the updated cart, or the current one unchanged on reject.
 */
export function setContribution ( variantId: string ): CartItem[] {
  if ( !CONTRIBUTION_PRODUCT_ID ) return readCart();
  const choice = contributionChoice( variantId );
  if ( !choice ) return readCart();
  const ref = `${CONTRIBUTION_PRODUCT_ID}:${choice.variantId}`;
  const items = readCart().filter( item => !isContributionItem( item ) );
  items.push( {
    productId: CONTRIBUTION_PRODUCT_ID,
    variantId: choice.variantId,
    // The shape `addItem` builds, so `removeItem` and the `key` prop work unchanged.
    ref,
    // Empty, so cart.tsx's existing `item.slug ? <Link> : item.name` does NOT link to a
    // /shop/contribute/ page that `SHOP_PRODUCTS` deliberately excludes.
    slug: '',
    // The amount is IN THE NAME, because a contribution has no other distinguishing feature and
    // "Contribute" alone beside a price would read as a product.
    name: `Contribute \u20B9${ choice.rupees }`,
    // A REAL PRICE NOW, and it is honest: the variant is priced at exactly this figure in Wix and
    // the quantity is 1, so the row total is the row price. Under the retired model this had to be
    // blank, because a per-unit "Rs.1.00" beside a Rs.400 contribution was a lie.
    formattedPrice: `\u20B9${ choice.rupees }.00`,
    quantity: 1,
  } );
  writeCart( items );
  return items;
}

/**
 * Merge the lines a WhatsApp hand-off claim returned into the cart the customer pays from.
 *
 * WHY THIS IS NEEDED AT ALL. The claim merges the lines into the SERVER-side Wix cart, but the
 * cart this page renders - and the basket `prepare-checkout` is given, because `toLineItems()`
 * reads the same storage - is the browser cart. Without this the claim succeeded invisibly: the
 * customer saw no new items, and the next checkout reconciled the claimed lines straight back OUT
 * of the Wix cart, because `_reconcile_saved_cart` makes the Wix cart match the REQUEST.
 *
 * IT ADDS NO SECOND STORAGE PATH. Every write goes through `addItem` or `setContribution`, which
 * both end at `writeCart` - the one writer - so a claimed line is indistinguishable from a line
 * added on /shop/ and announces the same `CART_CHANGED_EVENT` for the header badge.
 *
 * A LINE THIS BUILD CANNOT PLACE IS SKIPPED, NOT GUESSED AT, and the count says so. A claimed
 * product can be absent from `SHOP_PRODUCTS` (added in Wix since the committed snapshot was
 * fetched) or name a variant that snapshot no longer sells; there is no name and no price to show
 * for either, and inventing a row would put an unidentifiable line in a cart that is about to be
 * paid for. Skipping is also the safe direction at checkout: the server reconciles the Wix cart
 * down to what was requested, so the customer pays for exactly the lines they can see. The caller
 * uses `merged === 0` to say so out loud rather than showing an unchanged cart after a success.
 *
 * A CONTRIBUTION GOES THROUGH `setContribution`, which REPLACES rather than increments - there is
 * exactly one contribution line per cart, and `addItem` would leave two for a customer who had
 * already chosen an amount here, which is the basket the server refuses as two contributions.
 */
export function mergeClaimedLines ( lines: ClaimedLine[] ): { items: CartItem[]; merged: number } {
  let merged = 0;
  for ( const line of lines || [] )
  {
    const productId = String( line?.productId || '' ).trim();
    const variantId = String( line?.variantId || '' ).trim();
    if ( !productId || !variantId ) continue;
    const quantity = normaliseQuantity( line?.quantity );

    if ( CONTRIBUTION_PRODUCT_ID && productId === CONTRIBUTION_PRODUCT_ID )
    {
      // `setContribution` returns the cart unchanged for an unrecognised variant, so the presence
      // of the chosen line is the honest test of whether anything was placed.
      const after = setContribution( variantId );
      if ( after.some( item => isContributionItem( item ) && item.variantId === variantId ) )
      {
        merged += 1;
      }
      continue;
    }

    const product = SHOP_PRODUCTS.find( candidate => candidate.id === productId );
    if ( !product ) continue;
    try
    {
      addItem( product, quantity, variantId );
      merged += 1;
    }
    catch
    {
      // `addItem` throws for a variant this snapshot does not sell. Skipped, per the docblock.
    }
  }
  return { items: readCart(), merged };
}

/**
 * Does this basket need a delivery address? Mirrors the server's rule and is NOT the authority.
 *
 * BOTH SIDES NOW KEY ON IDENTITY, which they did not always: the server used to read Wix's
 * `productType`, and the live `Contribute` product is PHYSICAL, so the two disagreed about the
 * same basket. `checkout/handler.py:_v2_catalog_items` overrides the `productType` rule for a
 * recognised contribution line, which is the rule mirrored here.
 *
 * FAIL-CLOSED HERE TOO, by construction: true unless the basket is PROVABLY contribution-only.
 * `[]` therefore returns true, which never reaches the gate because `proceed`'s
 * `lineItems.length === 0` guard runs first.
 *
 * CALL IT WITH NO ARGUMENT from inside `proceed`. The default reads STORAGE; passing the `items`
 * state would read a value captured at the last render, and `proceed` is
 * `useCallback(..., [profile, profileStatus])` with `items` deliberately not a dependency.
 */
export const cartRequiresDelivery = ( items: CartItem[] = readCart() ): boolean =>
  !( items.length > 0 && items.every( item => isContributionItem( item ) || isServiceItem( item ) ) );

/*
 * `cartMixesContribution` WAS HERE AND IS DELETED RATHER THAN LEFT DEAD.
 *
 * It answered "is this a basket the server will refuse", and as of the owner decision on
 * 2026-10-06 the answer is no for every basket it could identify: a product and a contribution
 * are paid together, priced the way any single order is priced. Leaving the export in place would
 * leave a helper whose name reads as a rule and whose docstring asserted a refusal that no longer
 * exists -- the next reader would reinstate the gate from it. There were no other importers: the
 * cart page's notice, its "Keep only the contribution" button and its disabled CTA all went in
 * the same change, and `BlogContribution` deliberately never used it.
 *
 * `cartRequiresDelivery` above is NOT the same question and stays: a mixed basket genuinely does
 * need an address, because the product in it does.
 */

/**
 * A stable identifier for WHAT IS IN the basket, for scoping the checkout request key.
 *
 * Not a hash in the cryptographic sense and not security-bearing: it only has to change when the
 * basket changes and not change when it does not.
 *
 * Derived from `toLineItems()` rather than from `CartItem[]`, so it is computed from exactly the
 * payload the server will fingerprint - catalogue reference, variant and quantity, nothing else.
 * Order-independent (`sort`), because two carts holding the same lines in a different order are the
 * same intent and `cart_v2.calculate` prices them identically.
 *
 * NO CRYPTO AND NO ASYNC, deliberately: `crypto.subtle.digest` is a Promise, and `proceed` reads
 * the request key synchronously on a user gesture. A short djb2-style digest of the sorted
 * reference list is sufficient for a sessionStorage key name.
 *
 * THE LENGTH AND LINE-COUNT SUFFIX IS NOT DECORATION. The djb2 accumulator is `>>> 0`, so the
 * digest alone carries 32 bits - and two DIFFERENT baskets sharing a slot is precisely the failure
 * the request-key scoping removes: a resumed key whose `intent_fingerprint` has moved, answered
 * 409 CHECKOUT_REJECTED, latching `paymentBlocked` for the life of the tab. Appending the canonical
 * length and the line count costs one template literal and means colliding baskets would also have
 * to agree on both.
 *
 * The explicit-argument form is what the request-key call site uses, because the key must describe
 * the basket in THIS request body - a re-read of storage during the post-save retry could key a
 * basket it is not sending.
 */
export function basketFingerprint ( items: CheckoutLineItem[] = toLineItems() ): string {
  const canonical = items
    .map( line => `${ line.catalogReference.catalogItemId }:${
      line.catalogReference.options?.variantId || '' }:${ line.quantity }` )
    .sort()
    .join( '|' );
  let hash = 5381;
  for ( let i = 0; i < canonical.length; i += 1 )
  {
    hash = ( ( hash * 33 ) ^ canonical.charCodeAt( i ) ) >>> 0;
  }
  return `${ hash.toString( 36 ) }.${ canonical.length.toString( 36 ) }.${ items.length }`;
}

/**
 * The checkout `create` payload: catalogue references and quantities ONLY.
 *
 * This is the boundary the whole design rests on. Every returned entry is exactly
 * `{ catalogReference, quantity }` - no price, no amount, no currency, no formattedPrice. A test
 * asserts the serialized JSON of this output contains no price-like key. `catalogReference` is the
 * product's Wix catalogue id (see the module docblock and findings for the dummy-product
 * assumption); the server reads the authoritative total from a live Wix checkout, not from this.
 */
export function toLineItems ( items: CartItem[] = readCart() ): CheckoutLineItem[] {
  return items
    .filter( item => item.ref && item.quantity > 0 )
    .map( item => ( { catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e', catalogItemId: item.productId || item.ref, ...( item.variantId ? { options: { variantId: item.variantId } } : {} ) }, quantity: item.quantity } ) );
}

/* ── Phase O-1 services: Submit Request / Request Amendment ─────────────────────────────────── */

/**
 * Where the service INTENT pointer lives. NOT on the CartItem: `parseCart` and
 * `reconcileStoredCart` rebuild every item from a fixed field list, so an extra field would be
 * silently dropped on the next read. A separate key survives both.
 */
const SERVICE_INTENT_KEY = 'wecare.cart.serviceIntent.v1';

/** Attach an authenticated service intent without replacing a claimed catalog basket. */
export function rememberServiceIntent ( variantId: string, intentId: string ): void {
  if ( hasWindow() && serviceChoice( variantId ) && intentId )
  {
    window.localStorage.setItem( SERVICE_INTENT_KEY, JSON.stringify( { variantId, intentId } ) );
  }
}

/** Is this line the services product? On `productId`, like `isContributionItem`. */
export const isServiceItem = ( item: CartItem ): boolean =>
  !!SERVICES_PRODUCT_ID && item.productId === SERVICES_PRODUCT_ID;

/**
 * SET the one service line (replacing any other service line) and remember its intent id.
 *
 * Exactly one service per order (the server refuses two), quantity 1, display name and price from
 * config. An unrecognised variant - including Drop Docs and Vault - writes nothing.
 */
export function setServiceLine (
  variantId: string, intentId: string, linePaise: number,
): CartItem[] {
  const choice = serviceChoice( variantId );
  if ( !SERVICES_PRODUCT_ID || !choice || !intentId ) return readCart();
  // `linePaise` is WIX'S LIVE price for the variant, passed in by the buy box, which only offers
  // the line once it has one. There is no figure in `src/config/services.ts` to fall back on any
  // more (owner decision 2026-10-08: a price is editable in Wix with no deploy), and inventing
  // one here would put a number on a cart row that the checkout had never priced. A row with no
  // usable amount is therefore not written at all.
  if ( !Number.isSafeInteger( linePaise ) || linePaise <= 0 ) return readCart();
  const items = readCart().filter( item => !isServiceItem( item ) );
  items.push( {
    productId: SERVICES_PRODUCT_ID,
    variantId: choice.variantId,
    ref: `${ SERVICES_PRODUCT_ID }:${ choice.variantId }`,
    // Empty, so the cart row does not link to a /shop/ page that deliberately does not exist.
    slug: '',
    name: choice.label,
    // Integer division and modulo, never `linePaise / 100`. Display only: `toLineItems` stays
    // price-free and the checkout re-prices the line against Wix.
    formattedPrice: `\u20B9${ Math.trunc( linePaise / 100 ) }`
      + `.${ String( linePaise % 100 ).padStart( 2, '0' ) }`,
    quantity: 1,
  } );
  if ( hasWindow() )
  {
    window.localStorage.setItem(
      SERVICE_INTENT_KEY, JSON.stringify( { variantId: choice.variantId, intentId } ) );
  }
  writeCart( items );
  trackCatalogAdd( choice.variantId, linePaise );
  return items;
}

/**
 * The stored intent id, but ONLY when the basket's single service line is the same variant the
 * intent was taken for. Anything else - no service line, two of them, a different variant, a
 * corrupt pointer - answers '' and the server refuses with SERVICE_INTENT_REQUIRED.
 */
export function serviceIntentFor ( lineItems: CheckoutLineItem[] ): string {
  if ( !hasWindow() ) return '';
  const lines = lineItems.filter( line => line.catalogReference.catalogItemId === SERVICES_PRODUCT_ID );
  if ( lines.length !== 1 ) return '';
  try
  {
    const stored = JSON.parse( window.localStorage.getItem( SERVICE_INTENT_KEY ) || 'null' ) as
      { variantId?: unknown; intentId?: unknown } | null;
    if ( !stored || typeof stored.intentId !== 'string' ) return '';
    return stored.variantId === lines[ 0 ].catalogReference.options?.variantId ? stored.intentId : '';
  }
  catch
  {
    return '';
  }
}
