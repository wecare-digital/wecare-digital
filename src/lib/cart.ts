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
 * THE lineItems SHAPE MATCHES THE BACKEND CONTRACT. wix_ecom.create_checkout documents its input
 * as `{catalogReference, quantity}` entries - "a reference into the Wix catalogue, never a price".
 * The products are dummy placeholders today, so the exact nested Wix catalogReference object
 * (catalogItemId/appId) is not knowable from this repo; toLineItems() therefore sends the
 * product's Wix catalogue id as the catalogReference and the quantity, which is refs+quantities
 * ONLY and is trivially remapped to the final nested shape once real products are chosen. See the
 * findings note on the assumption.
 */

import { SHOP_PRODUCTS } from '../content/shop';
import type { ShopProduct, ShopVariant } from '../content/shop';

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

/**
 * Reconcile persisted rows against the catalogue bundled with THIS deployed storefront.
 *
 * This does not make the browser a price authority. It only upgrades identifiers and display
 * strings; checkout still sends references + quantities and the backend still prices from live
 * Wix. A multi-variant legacy row with no recoverable choice is deliberately left WITHOUT a
 * variant so /cart/ can ask the customer to choose one instead of silently guessing a size.
 */
function reconcileStoredCart ( items: CartItem[] ): { items: CartItem[]; changed: boolean } {
  const reconciled = items.map( item => {
    const product = currentProduct( item );
    if ( !product ) return item;

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
    return next;
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

/** Empty the cart. Called after a checkout is successfully prepared. */
export function clearCart (): void {
  if ( !hasWindow() ) return;
  window.localStorage.removeItem( CART_KEY );
  announce();
}

/** Total number of units across all lines - for a header badge or an empty check. */
export function cartCount (): number {
  return readCart().reduce( ( sum, item ) => sum + item.quantity, 0 );
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
