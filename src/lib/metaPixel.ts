/** Meta Pixel commerce events keyed to the exact Meta catalog retailer_id contract.
 *
 * The browser never invents prices for checkout. Values here are presentation/analytics only;
 * payment authority remains server-side. The important join field is content_ids, generated with
 * the same legacy/v2/v3 contract as lambda_utils.ecommerce.meta_catalog_sync.retailer_id.
 */

const RETAILER_PREFIX = 'WECARE.DIGITAL';
const MAX_RETAILER_ID_LENGTH = 100;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SAFE_SKU_RE = /^[A-Za-z0-9._-]+$/;

type Fbq = ( ...args: unknown[] ) => void;

function fbq (): Fbq | null {
  if ( typeof window === 'undefined' ) return null;
  const candidate = ( window as typeof window & { fbq?: Fbq } ).fbq;
  return typeof candidate === 'function' ? candidate : null;
}

function base64Url ( value: string ): string {
  const bytes = new TextEncoder().encode( value );
  let binary = '';
  bytes.forEach( byte => { binary += String.fromCharCode( byte ); } );
  return btoa( binary ).replace( /\+/g, '-' ).replace( /\//g, '_' ).replace( /=+$/g, '' );
}

export function metaRetailerId ( productId: string, variantId: string ): string {
  const product = String( productId || '' ).trim();
  const variant = String( variantId || '' ).trim();
  if ( !product || !variant ) return '';

  const lowerProduct = product.toLowerCase();
  const lowerVariant = variant.toLowerCase();
  let value: string;

  if ( UUID_RE.test( lowerProduct ) && UUID_RE.test( lowerVariant ) ) {
    value = `${RETAILER_PREFIX}:${lowerProduct}:${lowerVariant}`;
  } else {
    value = `${RETAILER_PREFIX}:v2:${base64Url( product )}:${base64Url( variant )}`;
    if ( value.length > MAX_RETAILER_ID_LENGTH && SAFE_SKU_RE.test( variant ) ) {
      value = `${RETAILER_PREFIX}:v3:${base64Url( product )}:${variant}`;
    }
  }

  return value.length <= MAX_RETAILER_ID_LENGTH ? value : '';
}

export function rupeesFromFormattedPrice ( value: string | undefined ): number | undefined {
  const parsed = Number( String( value || '' ).replace( /,/g, '' ).replace( /[^0-9.]/g, '' ) );
  return Number.isFinite( parsed ) && parsed > 0 ? parsed : undefined;
}

interface ProductEventInput {
  productId: string;
  variantId: string;
  name?: string;
  value?: number;
  currency?: string;
}

function productPayload ( input: ProductEventInput ): Record<string, unknown> | null {
  const retailerId = metaRetailerId( input.productId, input.variantId );
  if ( !retailerId ) return null;
  return {
    content_ids: [ retailerId ],
    content_type: 'product',
    ...( input.name ? { content_name: input.name } : {} ),
    ...( input.value && input.value > 0 ? { value: input.value } : {} ),
    currency: input.currency || 'INR',
  };
}

export function trackMetaViewContent ( input: ProductEventInput ): void {
  const pixel = fbq();
  const payload = productPayload( input );
  if ( !pixel || !payload ) return;
  pixel( 'track', 'ViewContent', payload );
}

export function trackMetaAddToCart ( input: ProductEventInput ): void {
  const pixel = fbq();
  const payload = productPayload( input );
  if ( !pixel || !payload ) return;
  pixel( 'track', 'AddToCart', payload );
}

export interface PaidCatalogEvent {
  contents?: Array<{ id?: string; quantity?: number }>;
  amountPaise?: number;
  currency?: string;
}

export function trackMetaPurchase (
  attemptId: string,
  event: PaidCatalogEvent | undefined,
): void {
  const pixel = fbq();
  if ( !pixel || !event || !Array.isArray( event.contents ) || !event.contents.length ) return;

  const ids = event.contents
    .map( line => String( line?.id || '' ).trim() )
    .filter( Boolean );
  if ( !ids.length || ids.length !== event.contents.length ) return;

  const amountPaise = Number( event.amountPaise );
  if ( !Number.isFinite( amountPaise ) || amountPaise <= 0 ) return;

  const eventId = `purchase:${String( attemptId || '' ).trim()}`;
  if ( !eventId || eventId === 'purchase:' ) return;

  // Polling can render the paid state more than once. One session should emit one Purchase.
  const storageKey = `wecare.meta.${eventId}`;
  try {
    if ( window.sessionStorage.getItem( storageKey ) === '1' ) return;
  } catch {
    // Storage denial must not block analytics; eventID still enables downstream dedupe.
  }

  pixel(
    'track',
    'Purchase',
    {
      content_ids: ids,
      contents: event.contents.map( line => ( {
        id: String( line.id ),
        quantity: Number( line.quantity ) || 1,
      } ) ),
      content_type: 'product',
      value: amountPaise / 100,
      currency: event.currency || 'INR',
    },
    { eventID: eventId },
  );

  try { window.sessionStorage.setItem( storageKey, '1' ); } catch { /* optional */ }
}
