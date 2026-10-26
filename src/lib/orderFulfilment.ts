export type FulfilmentStatus =
  | 'pending'
  | 'processing'
  | 'partially-shipped'
  | 'shipped'
  | 'completed'
  | 'canceled';

const PAID = new Set( [ 'paid', 'captured', 'PAYMENT_PAID' ] );

// The same table as the server's `wa_order_status._TRANSITIONS`, which stays the authority.
// `pending` reaches every status, so a paid order whose automatic `processing` update never went
// out can still be shipped or completed. Cancelling has its own audited workflow, so it is
// never offered here.
const NEXT: Record<FulfilmentStatus, FulfilmentStatus[]> = {
  pending: [ 'processing', 'partially-shipped', 'shipped', 'completed' ],
  processing: [ 'partially-shipped', 'shipped', 'completed' ],
  'partially-shipped': [ 'shipped', 'completed' ],
  shipped: [ 'completed' ],
  completed: [],
  canceled: [],
};

export function canonicalFulfilmentStatus (
  raw: string | undefined,
  paymentStatus?: string,
): FulfilmentStatus {
  const value = String( raw || '' ).trim().toLowerCase().replace( /_/g, '-' );
  if ( value === 'fulfilled' ) return 'completed';
  if ( value === 'cancelled' ) return 'canceled';
  if ( value === 'active' ) return PAID.has( String( paymentStatus || '' ) ) ? 'processing' : 'pending';
  if ( value === 'pending' || value === 'processing' || value === 'partially-shipped'
    || value === 'shipped' || value === 'completed' || value === 'canceled' ) return value;
  // Unknown/corrupt provider or legacy words must fail closed. Payment evidence does not
  // prove a fulfilment state; only a recognised lifecycle word (or explicit legacy active)
  // may enter processing.
  return 'pending';
}

export function allowedFulfilmentTargets (
  rawStatus: string | undefined,
  paymentStatus?: string,
): FulfilmentStatus[] {
  const current = canonicalFulfilmentStatus( rawStatus, paymentStatus );
  if ( current === 'pending' && !PAID.has( String( paymentStatus || '' ) ) ) return [];
  return NEXT[ current ];
}

export function fulfilmentLabel ( value: string ): string {
  return String( value || '' )
    .replace( /[-_]/g, ' ' )
    .replace( /\b\w/g, letter => letter.toUpperCase() );
}

// WhatsApp ORDER_DETAILS checkout modes. Used only to hide manual payment-status controls;
// the backend owns the automatic processing -> completed sequence.
const WHATSAPP_ORDER_CHECKOUT_MODES: ReadonlySet<string> = new Set( [
  'WHATSAPP_NATIVE_PG', 'WHATSAPP_NATIVE_CART', 'AWS_NATIVE',
] );

export function isWhatsAppOrder ( checkoutMode: string | undefined ): boolean {
  return WHATSAPP_ORDER_CHECKOUT_MODES.has( String( checkoutMode || '' ) );
}
