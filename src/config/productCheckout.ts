/**
 * Fresh SKU-first product checkout mappings.
 *
 * Product ids are the AWS-native catalog ids created for this catalog generation. Variant ids are
 * the public 8-character SKUs; the browser sends identities only and ProductsTable remains the
 * server-side price authority at checkout.
 */

export interface ProductCheckoutLine {
  readonly productId: string;
  readonly variantId: string;
  readonly name: string;
  readonly slug: string;
  readonly formattedPrice: string;
}

const line = (
  slug: string, sku: string, name: string, formattedPrice: string,
): ProductCheckoutLine => ( {
  productId: `native:${ slug }`,
  variantId: sku,
  name,
  slug,
  formattedPrice,
} );

/** Ordinary products. Request services and Contribute use their dedicated guarded checkout paths. */
export const PRODUCT_CHECKOUT: Readonly<Record<string, ProductCheckoutLine>> = {
  'grahak-os': line( 'grahak-os', 'GOS7K4M2', 'Grahak OS', '₹899.00' ),
  'bharat-rx': line( 'bharat-rx', 'BRX5N8Q3', 'Bharat Rx', '₹550.00' ),
  'elsewhere-visa': line( 'elsewhere-visa', 'EVS9P4L7', 'Elsewhere · Visa', '₹899.00' ),
  'elsewhere-trip': line( 'elsewhere-trip', 'ETR6M3K8', 'Elsewhere · Trip', '₹899.00' ),
  'expo-week': line( 'expo-week', 'EXP4Q7N5', 'Expo Week', '₹899.00' ),
  'dastavez-drafting': line( 'dastavez-drafting', 'DDF8K5P2', 'Dastavez · Drafting', '₹1,499.00' ),
  'dastavez-registration': line( 'dastavez-registration', 'DRG7M4Q9', 'Dastavez · Registration', '₹899.00' ),
  'dastavez-legal-reference': line( 'dastavez-legal-reference', 'DLR5P8K3', 'Dastavez · Legal Reference', '₹599.00' ),
  'guided-resolution': line( 'guided-resolution', 'CGR9N6M4', 'Clear Closure · Guided Resolution', '₹1,999.00' ),
  'file-assist': line( 'file-assist', 'CCS7K3P8', 'Clear Closure · Case Submission', '₹1,499.00' ),
  'paperwork': line( 'paperwork', 'CPW5M9Q2', 'Clear Closure · Paperwork', '₹899.00' ),
  'ritual-guru-puja-guidance': line( 'ritual-guru-puja-guidance', 'RPG8N4K6', 'Ritual Guru · Puja Guidance', '₹399.00' ),
  'ritual-guru-diy-puja-kit': line( 'ritual-guru-diy-puja-kit', 'RDK6P3M9', 'Ritual Guru · DIY Puja Kit', '₹899.00' ),
  'anew': line( 'anew', 'ANW7Q5K2', 'Anew', '₹599.00' ),
  'hunar': line( 'hunar', 'HNR9M4P6', 'Hunar', '₹599.00' ),
  'niji-setu': line( 'niji-setu', 'NJS5K8Q3', 'Niji Setu', '₹299.00' ),
  'shipments-track': line( 'shipments-track', 'SHT8M5P3', 'Shipment · Track', '₹49.00' ),
  'shipments': line( 'shipments-track', 'SHT8M5P3', 'Shipment · Track', '₹49.00' ),
  'referral-partner': line( 'referral-partner', 'PRF5M8K2', 'Partner · Referral', '₹899.00' ),
  'refer-and-earn': line( 'referral-partner', 'PRF5M8K2', 'Partner · Referral', '₹899.00' ),
  'merchandise': line( 'merchandise', 'PMD9Q3P6', 'Partner · Merchandise', '₹1,999.00' ),
  'kiosk': line( 'kiosk', 'PKS7K5M4', 'Partner · Kiosk', '₹26,999.00' ),
};

/** Returns a configured line only; there is deliberately no placeholder fallback. */
export const productCheckoutLine = ( slug: string ): ProductCheckoutLine | null =>
  PRODUCT_CHECKOUT[ slug ] ?? null;
