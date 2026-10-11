/**
 * TEMPORARY PRODUCT-CHECKOUT PLACEHOLDER, for the nine product pages whose real catalogue line
 * does not exist yet (Elsewhere, Expo Week, Dastavez, Clear Closure, Ritual Guru, Anew, Hunar,
 * Niji Setu, Bharat Rx).
 *
 * WHAT THIS IS FOR. The owner wants the "Continue to checkout →" format LIVE on every product page
 * now, paid end to end, so the whole flow is proven. Until each product has its own Wix line, the
 * button checks out a REAL ₹1 catalogue product — `₹1 test product`, which exists and is in stock
 * in the live Wix catalogue (src/content/wix-catalog.json) — so the checkout is genuine and the
 * server accepts it, rather than a fake id that would 404 at Wix and dead-end.
 *
 * HOW TO MAKE A PRODUCT REAL. When a product gets its own Wix line, give it an entry in
 * `PRODUCT_CHECKOUT` below keyed on its page slug, with the live `productId`/`variantId`. The
 * ProductBuyBox reads this map and falls back to `PLACEHOLDER_LINE` only for a slug not yet listed
 * — so going live for one product is a one-line edit here, the format and the component unchanged.
 *
 * NO PRICE IS DECLARED HERE. Like services, the amount is Wix's: the cart row shows the catalogue
 * `formattedPrice` and the server re-prices the line on prepare. The ₹1 is Wix's price for the
 * test product, not a figure invented in the frontend.
 */

/** A catalogue line the product buy box can add to the cart: a real Wix product + variant. */
export interface ProductCheckoutLine {
  readonly productId: string;
  readonly variantId: string;
  /** Display name for the cart row and the ProductBuyBox price fetch fallback. */
  readonly name: string;
  /** The product's catalogue slug (for the cart row's back-link; '' keeps it unlinked). */
  readonly slug: string;
  /** Wix's own formatted price string, DISPLAY ONLY — never sent to the server. */
  readonly formattedPrice: string;
}

/**
 * THE ₹1 PLACEHOLDER LINE. A real, in-stock catalogue product so the checkout is honest and
 * accepted. Replace a product's use of this by adding its slug to `PRODUCT_CHECKOUT`.
 */
export const PLACEHOLDER_LINE: ProductCheckoutLine = {
  productId: '121c9d57-2cc9-490b-8eed-66bf7b9c172a',
  variantId: 'c2edc783-c8fa-4b3e-a922-f7800889e56a',
  name: '\u20B91 test product',
  slug: '1-test-product',
  formattedPrice: '\u20B91.00',
};

/**
 * Per-product real catalogue lines, keyed by PAGE SLUG. EMPTY for now: every product uses the ₹1
 * placeholder. Add an entry here as each product's real Wix line is created, and that product
 * stops using the placeholder with no change to the component.
 */
export const PRODUCT_CHECKOUT: Readonly<Record<string, ProductCheckoutLine>> = {
  // elsewhere: { productId: '…', variantId: '…', name: 'Elsewhere', slug: 'elsewhere', formattedPrice: '₹…' },
};

/** The checkout line for a product page slug: its real line if listed, else the ₹1 placeholder. */
export const productCheckoutLine = ( slug: string ): ProductCheckoutLine =>
  PRODUCT_CHECKOUT[ slug ] ?? PLACEHOLDER_LINE;

/** True while a slug is still on the placeholder (useful for a quiet "in testing" note if wanted). */
export const isPlaceholderCheckout = ( slug: string ): boolean =>
  !Object.prototype.hasOwnProperty.call( PRODUCT_CHECKOUT, slug );
