/**
 * The single customer Orders page is /orders/ for all purchase channels.
 * New links never carry an Order Number; historical ?o= links are still read
 * to expand the owned order before cleaning the address bar.
 * Session storage carries an order through OTP sign-in without weakening returns.
 */

/**
 * The current `WD-ORD-` + 8 form and the bare 12-character legacy form, over the server's
 * 30-symbol alphabet (no 0 1 I L O U). The same rule as `order_keys.is_public_order_number`,
 * so a value this accepts is one the server can resolve.
 */
const PUBLIC_ORDER_NUMBER = /^(?:WD-ORD-[2-9A-HJKMNP-TV-Z]{8}|[2-9A-HJKMNP-TV-Z]{12})$/;

/** The query parameter that names the order. */
const ORDER_PARAM = 'o';

/** Out-of-band carrier for an order link opened while signed out. Single use. */
const PENDING_ORDER_KEY = 'wecare.pendingOrderView';

export function isPublicOrderNumber ( value: unknown ): value is string {
  return typeof value === 'string' && PUBLIC_ORDER_NUMBER.test( value );
}

/** Canonical destination, without a second order-detail route. */
export function orderPagePath ( _orderNumber: string ): string {
  return '/orders/';
}

/** Read an older ?o= deep link during migration; do not generate new ones. */
export function orderNumberFromUrl (): string {
  if ( typeof window === 'undefined' ) return '';
  const value = new URLSearchParams( window.location.search ).get( ORDER_PARAM ) || '';
  const trimmed = value.trim();
  return isPublicOrderNumber( trimmed ) ? trimmed : '';
}

/** Keep the order to reopen after a sign-in round trip. Storage may be disabled; that is fine. */
export function stashPendingOrder ( orderNumber: string ): void {
  if ( typeof window === 'undefined' || !isPublicOrderNumber( orderNumber ) ) return;
  try { window.sessionStorage.setItem( PENDING_ORDER_KEY, orderNumber ); }
  catch { /* storage disabled: the customer lands on their order history instead */ }
}

/** Read and CLEAR the stashed order, so it reopens once and never again. */
export function takePendingOrder (): string {
  if ( typeof window === 'undefined' ) return '';
  try
  {
    const value = window.sessionStorage.getItem( PENDING_ORDER_KEY ) || '';
    window.sessionStorage.removeItem( PENDING_ORDER_KEY );
    return isPublicOrderNumber( value ) ? value : '';
  }
  catch { return ''; }
}
