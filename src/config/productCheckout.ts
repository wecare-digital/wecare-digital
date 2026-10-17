/** Fresh SKU-first product checkout mappings. */
export interface ProductCheckoutLine {
  readonly productId: string;
  readonly variantId: string;
  readonly name: string;
  readonly slug: string;
  readonly formattedPrice: string;
}

const line = (
  productId: string, slug: string, sku: string, name: string, formattedPrice: string,
): ProductCheckoutLine => ( { productId, variantId: sku, name, slug, formattedPrice } );

/** Ordinary products. Request services and Contribute use their dedicated guarded checkout paths. */
export const PRODUCT_CHECKOUT: Readonly<Record<string, ProductCheckoutLine>> = {
  'grahak-os': line( '2d5dff1a-2542-5839-9c6e-e65d10fcc643', 'grahak-os', 'GOS7K4M2', 'Grahak OS', '₹899.00' ),
  'bharat-rx': line( '032039ce-c4ec-5d44-8fdb-d4d9ffb91f02', 'bharat-rx', 'BRX5N8Q3', 'Bharat Rx', '₹550.00' ),
  'elsewhere-visa': line( 'f74ed861-5945-5893-a0cc-02024511687a', 'elsewhere-visa', 'EVS9P4L7', 'Elsewhere · Visa', '₹899.00' ),
  'elsewhere-trip': line( '619ac1ba-159e-5811-b1b7-98131020cd03', 'elsewhere-trip', 'ETR6M3K8', 'Elsewhere · Trip', '₹899.00' ),
  'expo-week': line( '331e83ee-384e-5f4e-b348-e205990ba546', 'expo-week', 'EXP4Q7N5', 'Expo Week', '₹899.00' ),
  'dastavez-drafting': line( '94af52d3-d91f-5a84-aab5-2033237aba46', 'dastavez-drafting', 'DDF8K5P2', 'Dastavez · Drafting', '₹1,499.00' ),
  'dastavez-registration': line( '3ddcc49c-86f4-59e0-b6ec-b5cffee7ea4d', 'dastavez-registration', 'DRG7M4Q9', 'Dastavez · Registration', '₹899.00' ),
  'dastavez-legal-reference': line( '7d7eda2f-943a-5131-852e-32483dda0259', 'dastavez-legal-reference', 'DLR5P8K3', 'Dastavez · Legal Reference', '₹599.00' ),
  'guided-resolution': line( 'c3921ac7-32d5-5852-96b8-434161bb53fd', 'guided-resolution', 'CGR9N6M4', 'Clear Closure · Guided Resolution', '₹1,999.00' ),
  'file-assist': line( '9e51eb4c-00f2-523e-91be-6c9d312adfa7', 'file-assist', 'CCS7K3P8', 'Clear Closure · Case Submission', '₹1,499.00' ),
  'paperwork': line( '78334b88-160f-5811-9827-d958e50dfcde', 'paperwork', 'CPW5M9Q2', 'Clear Closure · Paperwork', '₹899.00' ),
  'ritual-guru-puja-guidance': line( '0e0cc8ea-036c-5b57-aec2-8f98e3c2df82', 'ritual-guru-puja-guidance', 'RPG8N4K6', 'Ritual Guru · Puja Guidance', '₹399.00' ),
  'ritual-guru-diy-puja-kit': line( '45af1dfb-fddb-53b0-950c-da703ade9264', 'ritual-guru-diy-puja-kit', 'RDK6P3M9', 'Ritual Guru · DIY Puja Kit', '₹899.00' ),
  'anew': line( '6794847f-303e-598e-bdfb-74db0a642fed', 'anew', 'ANW7Q5K2', 'Anew', '₹599.00' ),
  'hunar-kaushal': line( 'native:hunar-kaushal', 'hunar-kaushal', 'KSL9M2Q4', 'Hunar · Kaushal', '₹99.00' ),
  'hunar-prastuti': line( 'native:hunar-prastuti', 'hunar-prastuti', 'PST7K4N2', 'Hunar · Prastuti', '₹299.00' ),
  'niji-setu': line( 'abe4870e-fae3-59cc-b1a7-9bd28eff048a', 'niji-setu', 'NJS5K8Q3', 'Niji Setu', '₹299.00' ),
  'shipments-track': line( 'f45dec5c-5bcc-5fca-9c50-5f63b57554d2', 'shipments-track', 'SHT8M5P3', 'Shipment · Track', '₹49.00' ),
  'referral-partner': line( '944c8cb0-5a8b-57f1-9204-e29bfb5f1554', 'referral-partner', 'PRF5M8K2', 'Partner · Referral', '₹899.00' ),
  'merchandise': line( '884281fd-e6e3-537a-b58e-9c6e1342597d', 'merchandise', 'PMD9Q3P6', 'Partner · Merchandise', '₹1,999.00' ),
  'kiosk': line( '84eb1e0c-0d07-5a64-8cf4-cff09e8ee5be', 'kiosk', 'PKS7K5M4', 'Partner · Kiosk', '₹26,999.00' ),
  'shipments': line( 'f45dec5c-5bcc-5fca-9c50-5f63b57554d2', 'shipments-track', 'SHT8M5P3', 'Shipment · Track', '₹49.00' ),
  'refer-and-earn': line( '944c8cb0-5a8b-57f1-9204-e29bfb5f1554', 'referral-partner', 'PRF5M8K2', 'Partner · Referral', '₹899.00' ),
};

export const productCheckoutLine = ( slug: string ): ProductCheckoutLine | null =>
  PRODUCT_CHECKOUT[ slug ] ?? null;
