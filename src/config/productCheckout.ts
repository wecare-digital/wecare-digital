/**
 * Product checkout mappings.
 *
 * The previous AWS catalog rows were retired and deleted. Product pages remain public, but no
 * product may fall back to a deleted test row or another retired catalog identity.
 *
 * Fresh checkout mappings will be added only when the new SKU-first catalog is created.
 */

export interface ProductCheckoutLine {
  readonly productId: string;
  readonly variantId: string;
  readonly name: string;
  readonly slug: string;
  readonly formattedPrice: string;
}

/** No retired catalog rows are eligible for checkout. */
export const PRODUCT_CHECKOUT: Readonly<Record<string, ProductCheckoutLine>> = {};

/** Returns a live configured line only; there is deliberately no placeholder fallback. */
export const productCheckoutLine = ( slug: string ): ProductCheckoutLine | null =>
  PRODUCT_CHECKOUT[ slug ] ?? null;

