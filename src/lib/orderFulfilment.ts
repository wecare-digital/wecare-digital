export type FulfilmentStatus =
  | 'pending'
  | 'processing'
  | 'partially-shipped'
  | 'shipped'
  | 'completed'
  | 'canceled';

const PAID = new Set( [ 'paid', 'captured', 'PAYMENT_PAID' ] );

const NEXT: Record<FulfilmentStatus, FulfilmentStatus[]> = {
  pending: [ 'processing' ],
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
  return PAID.has( String( paymentStatus || '' ) ) ? 'processing' : 'pending';
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
    .replace( /-/g, ' ' )
    .replace( /\b\w/g, letter => letter.toUpperCase() );
}
