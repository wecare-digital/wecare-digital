/**
 * The browser shopping cart for /shop/ - references and quantities only.
 *
 * THE ONE RULE THIS FILE EXISTS TO ENFORCE: the browser never sends a price, an amount, a
 * currency or any financial figure to the checkout. A cart entry carries a catalogue REFERENCE
 * (the product's ProductsTable id, with its slug and name for display) and a QUANTITY, and nothing
 * else reaches the server. The amount charged is decided server-side from a live ProductsTable read
 * and compared in integer paise (amplify/functions/ecommerce/checkout/handler.py rule 2), so a
 * number invented here could only ever be wrong or dangerous. `formattedPrice` is kept for the
 * cart LIST rendering only - it is the catalogue's own formatted string, never rebuilt, and it is
 * stripped out entirely by toLineItems(): see the test that asserts the serialized payload has no
 * price-like key.
 *
 * WHY LOCALSTORAGE. The cart must survive the sign-in/register redirect (a public shopper who
 * proceeds is bounced to the OTP step and back), so it cannot live in component state. It is not
 * sensitive - it is a list of catalogue references a visitor chose - so localStorage is the right
 * store; the session token stays in sessionStorage (customerAuth.ts) where it belongs. Every
 * window/storage access is SSR-guarded (typeof window === 'undefined'), matching customerAuth.ts,
 * because these pages are statically exported and this module is imported into prerendered code.
 *
 * THE lineItems SHAPE MATCHES THE BACKEND CONTRACT. What `toLineItems()` emits:
 *
 *   { catalogReference: { catalogItemId, options?: { variantId } }, quantity }
 *
 *   * `catalogItemId` is the PRODUCT id, never the slug and never a variant id. A variant id
 *     here would 404 at the catalog lookup.
 *   * `options.variantId` is present only when the line carries one: a no-option product's
 *     reference carries no `options`.
 *
 * Nothing else rides in the reference. Product and variant ids are ProductsTable keys (some are
 * preserved legacy catalogue ids), and the committed snapshot carries the same ids the checkout
 * resolves, so every line this function builds names a row the server can price.
 */

import { KNOWN_CATALOGUE_PRODUCT_IDS, SHOP_PRODUCTS } from '../content/shop';
import type { ShopProduct, ShopVariant } from '../content/shop';
import type { ContributionChoice } from '../config/contribution';
import { CONTRIBUTION_PRODUCT_ID, contributionChoice } from '../config/contribution';
import { SERVICE_PRODUCT_IDS, serviceChoice } from '../config/services';

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

/** Part 1 storefront checkout: one catalogue selection, one unit, no invisible basket truncation. */
export const SHORT_COMMERCE_ONE_PRODUCT_MESSAGE =
  'Buy one product at a time (quantity 1). Remove extra cart lines to continue.';

export interface CartItem {
  productId?: string;
  variantId?: string;
  /** The catalogue reference: the product's catalogue id. Never a price. */
  ref: string;
  /** The product slug, so the cart can link back to /shop/<slug>/. */
  slug: string;
  /** Display name for the cart list. */
  name: string;
  /** The catalogue's formatted price string, e.g. "₹6,999.00". DISPLAY ONLY - never sent to the server. */
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
  catalogReference: { catalogItemId: string; options?: { variantId: string } };
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

/** A catalogue id: a lowercase UUID. What a `productId` and a modern `ref` base both are. */
const CATALOGUE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Should an UNRESOLVABLE stored line be thrown away rather than carried into checkout?
 *
 * Only ever consulted for a line `currentProduct` could not resolve, and the predicate is
 * deliberately narrow: **the line names a catalogue id (a UUID) that this snapshot has never
 * heard of.** That is exactly the pre-migration row - every product id was re-minted on
 * 2026-10-05, so a browser holding the old ₹1 test product carries a well-formed id that exists
 * nowhere in the current catalogue.
 *
 * Three things it is careful NOT to do:
 *
 *   * **It does not key on `SHOP_PRODUCTS`.** That list excludes real, purchasable rows - the
 *     contribution vehicle and the services vehicle - so "absent from /shop/" is not "absent from
 *     the catalogue". `KNOWN_CATALOGUE_PRODUCT_IDS` reads the raw snapshot for that reason, and a
 *     contribution line is kept on CONFIG identity whether or not the snapshot has been refreshed
 *     at all. (It used to exclude thirteen: twelve template sample rows have since left the
 *     catalogue, so the snapshot no longer carries them either and a stored row naming one is
 *     now correctly dropped.)
 *   * **It does not touch a non-UUID `ref`.** Those are the pre-2026-10 rows that carry a slug or
 *     an opaque reference, and the slug fallback in `currentProduct` is what repairs them; a row
 *     that fallback cannot place keeps today's behaviour exactly rather than being deleted on a
 *     guess about an id shape the catalogue never used.
 *   * **It does not claim to be the authority.** ProductsTable is, and the server still refuses
 *     what it does not recognise. This only spares a customer learning it after pressing
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
 * strings; checkout still sends references + quantities and the backend still prices from
 * ProductsTable. A multi-variant legacy row with no recoverable choice is deliberately left
 * WITHOUT a variant so /cart/ can ask the customer to choose one instead of silently guessing a
 * size.
 *
 * AN ID FROM THE PREVIOUS CATALOGUE IS NOW DROPPED RATHER THAN CARRIED. Every product id was
 * re-minted on 2026-10-05, so a returning visitor's localStorage can hold a product id (e.g. the
 * old ₹1 test product) that exists nowhere in the current catalogue. Carried into
 * `toLineItems()` it reaches the catalog lookup, 404s, and the
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
      // Website purchases are single-unit by policy. Old stored quantities are collapsed on read.
      quantity: 1,
    };
    return [ next ];
  } );

  // A legacy line and a newer line can reconcile to the same canonical ref. Merge only then, so
  // the customer cannot be charged twice for two storage records that now mean one cart line.
  const merged: CartItem[] = [];
  for ( const item of reconciled )
  {
    const existing = merged.find( candidate => candidate.ref === item.ref );
    if ( existing ) existing.quantity = 1;
    else merged.push( { ...item, quantity: 1 } );
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
 * Select the one storefront product for checkout. Re-selecting it is idempotent; choosing a
 * different product or variant replaces the earlier UNPAID browser selection. Quantity remains
 * fixed to 1 and the payment, order and invoice contracts are not changed.
 */
export function addItem ( product: ShopProduct, qty = 1, selectedVariantId?: string ): CartItem[] {
  const variantId = selectedVariantId || ( product.variants?.length === 1 ? product.variants[0].id : undefined );
  if ( product.variants && product.variants.length > 1 && !variantId ) throw new Error( 'Choose an option first.' );
  if ( variantId && !product.variants?.some( variant => variant.id === variantId && variant.inStock ) ) throw new Error( 'Choose an available option.' );
  const ref = String( product.id || product.slug || '' ) + ( variantId ? `:${variantId}` : '' );
  if ( !ref ) return readCart();
  void qty;
  const existing = readCart().find( item => item.ref === ref );
  const selected: CartItem = existing ? { ...existing, quantity: 1 } : {
    productId: product.id,
    ...( variantId ? { variantId } : {} ),
    ref,
    slug: String( product.slug || '' ),
    name: product.variants && product.variants.length > 1
      ? `${product.name} (${product.variants.find( variant => variant.id === variantId )!.label})`
      : String( product.name || '' ),
    formattedPrice: String( product.formattedPrice || '' ),
    quantity: 1,
  };
  // A new selection replaces the prior UNPAID website selection. No multi-bag checkout.
  writeCart( [ selected ] );
  return [ selected ];
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
  if ( duplicate ) duplicate.quantity = 1;
  else remaining.splice( index, 0, { ...next, quantity: 1 } );
  writeCart( remaining );
  return remaining;
}

/**
 * Compatibility helper for older callers. Website quantity is fixed to 1: zero/below removes
 * the line; any positive value keeps exactly one unit.
 */
export function setQuantity ( ref: string, qty: number ): CartItem[] {
  const items = readCart();
  const next = Math.floor( Number( qty ) );
  if ( !Number.isFinite( next ) || next <= 0 )
  {
    return removeItem( ref );
  }
  const existing = items.find( item => item.ref === ref );
  if ( existing ) existing.quantity = 1;
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
 * A contribution is the one selected cart line; choosing an amount SETS it.
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
  const selected: CartItem = {
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
    // A REAL PRICE NOW, and it is honest: the variant is priced at exactly this figure in the
    // catalogue and the quantity is 1, so the row total is the row price. Under the retired model
    // this had to be blank, because a per-unit "Rs.1.00" beside a Rs.400 contribution was a lie.
    formattedPrice: `\u20B9${ choice.rupees }.00`,
    quantity: 1,
  };
  writeCart( [ selected ] );
  return [ selected ];
}

/**
 * Accept exactly one unit from a WhatsApp hand-off claim into the storefront cart.
 *
 * WHY THIS IS NEEDED AT ALL. The claim merges the lines into the customer's SERVER-side cart, but
 * the cart this page renders - and the basket `prepare-checkout` is given, because `toLineItems()`
 * reads the same storage - is the browser cart. Without this the claim succeeded invisibly: the
 * customer saw no new items, and the next checkout reconciled the claimed lines straight back OUT
 * of the server-side cart, because the checkout makes that cart match the REQUEST.
 *
 * IT ADDS NO SECOND STORAGE PATH. A single eligible claimed line goes through `addItem` or
 * `setContribution`, which both use the same `writeCart` and `CART_CHANGED_EVENT`. Multi-line
 * or multi-unit claims are NOT partly merged: the caller displays its existing refusal message,
 * preserving the ability to reconcile the original WhatsApp basket without undercharging.
 *
 * A LINE THIS BUILD CANNOT PLACE IS SKIPPED, NOT GUESSED AT, and the count says so. A claimed
 * product can be absent from `SHOP_PRODUCTS` (added to ProductsTable since the committed snapshot
 * was published) or name a variant that snapshot no longer sells; there is no name and no price to
 * show for either, and inventing a row would put an unidentifiable line in a cart that is about to
 * be paid for. Skipping is also the safe direction at checkout: the server reconciles its cart
 * down to what was requested, so the customer pays for exactly the lines they can see. The caller
 * uses `merged === 0` to say so out loud rather than showing an unchanged cart after a success.
 *
 * A CONTRIBUTION GOES THROUGH `setContribution`, which REPLACES rather than increments - there is
 * exactly one contribution line per cart, and `addItem` would leave two for a customer who had
 * already chosen an amount here, which is the basket the server refuses as two contributions.
 */
export function mergeClaimedLines ( lines: ClaimedLine[] ): { items: CartItem[]; merged: number } {
  // A WhatsApp hand-off may contain a legacy multi-line or multi-quantity basket.
  // Never silently discard paid intent or choose an arbitrary line for checkout.
  if ( !Array.isArray( lines ) || lines.length !== 1 ||
       !Number.isInteger( lines[ 0 ].quantity ) || lines[ 0 ].quantity !== 1 )
  {
    return { items: readCart(), merged: 0 };
  }
  let merged = 0;
  for ( const line of lines || [] )
  {
    const productId = String( line?.productId || '' ).trim();
    const variantId = String( line?.variantId || '' ).trim();
    if ( !productId || !variantId ) continue;
    // A claimed website cart line is also single-unit, regardless of the source basket count.
    const quantity = 1;

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
 * BOTH SIDES NOW KEY ON IDENTITY, which they did not always: the server used to read the
 * catalogue's `productType`, and the live `Contribute` product is PHYSICAL, so the two disagreed
 * about the same basket. The checkout overrides the `productType` rule for a recognised
 * contribution line, which is the rule mirrored here.
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
 * same intent and the checkout prices them identically.
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
 * asserts the serialized JSON of this output contains no price-like key. `catalogReference` names
 * the product (and, when there is one, the variant) by catalogue id - see the module docblock; the
 * server reads the authoritative total from ProductsTable, not from this.
 */
export function toLineItems ( items: CartItem[] = readCart() ): CheckoutLineItem[] {
  // Defense in depth for legacy/crafted carts; no request may silently drop a second line
  // or turn a stored quantity > 1 into a charged single unit.
  if ( items.length > 1 || items.some( item => item.quantity !== 1 ) )
  {
    throw new Error( SHORT_COMMERCE_ONE_PRODUCT_MESSAGE );
  }
  return items
    .filter( item => item.ref && item.quantity > 0 )
    .map( item => ( { catalogReference: { catalogItemId: item.productId || item.ref, ...( item.variantId ? { options: { variantId: item.variantId } } : {} ) }, quantity: 1 } ) );
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
  !!item.productId && SERVICE_PRODUCT_IDS.has( item.productId );

/**
 * SET the single selected service line (replacing any unpaid cart line) and remember its intent id.
 *
 * Exactly one service per order (the server refuses two), quantity 1, display name and price from
 * config. An unrecognised variant - including Drop Docs and Vault - writes nothing.
 */
export function setServiceLine (
  variantId: string, intentId: string, linePaise: number,
): CartItem[] {
  const choice = serviceChoice( variantId );
  if ( !choice || !choice.productId || !intentId ) return readCart();
  // `linePaise` is the LIVE catalogue price for the variant, passed in by the buy box, which only
  // offers the line once it has one. There is no figure in `src/config/services.ts` to fall back
  // on any more (owner decision 2026-10-08: a price is editable in the catalogue with no deploy),
  // and inventing one here would put a number on a cart row that the checkout had never priced. A
  // row with no usable amount is therefore not written at all.
  if ( !Number.isSafeInteger( linePaise ) || linePaise <= 0 ) return readCart();
  const selected: CartItem = {
    productId: choice.productId,
    variantId: choice.variantId,
    ref: `${ choice.productId }:${ choice.variantId }`,
    // Empty, so the cart row does not link to a /shop/ page that deliberately does not exist.
    slug: '',
    name: choice.label,
    // Integer division and modulo, never `linePaise / 100`. Display only: `toLineItems` stays
    // price-free and the checkout re-prices the line against ProductsTable.
    formattedPrice: `\u20B9${ Math.trunc( linePaise / 100 ) }`
      + `.${ String( linePaise % 100 ).padStart( 2, '0' ) }`,
    quantity: 1,
  };
  if ( hasWindow() )
  {
    window.localStorage.setItem(
      SERVICE_INTENT_KEY, JSON.stringify( { variantId: choice.variantId, intentId } ) );
  }
  writeCart( [ selected ] );
  return [ selected ];
}

/**
 * The stored intent id, but ONLY when the basket's single service line is the same variant the
 * intent was taken for. Anything else - no service line, two of them, a different variant, a
 * corrupt pointer - answers '' and the server refuses with SERVICE_INTENT_REQUIRED.
 */
export function serviceIntentFor ( lineItems: CheckoutLineItem[] ): string {
  if ( !hasWindow() ) return '';
  const lines = lineItems.filter( line => SERVICE_PRODUCT_IDS.has( line.catalogReference.catalogItemId ) );
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
