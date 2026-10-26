/**
 * The order page: `/orders/?o=<orderNumber>`, one of the signed-in customer's own orders.
 *
 * Both purchase channels reach it once the payment is confirmed: the website's
 * /checkout/status/ screen hands off to it, and a WhatsApp buyer gets a "View your order" button
 * after the paid invoice (the invoice engine's `_send_order_page_link` builds the same
 * `/orders/?o=<orderNumber>` shape). Fulfilment is read from the internal OrderTable projection;
 * no WhatsApp order-status message is part of this path.
 *
 * THE NUMBER SELECTS, THE SESSION AUTHORISES. An order number is printed on receipts and read
 * aloud to support, so it is never a credential. The page reads the order through the checkout
 * `order` action, which answers only for an order the WhatsApp-OTP session owns, so a number in
 * a URL reveals nothing on its own.
 *
 * WHY THE NUMBER RIDES SESSIONSTORAGE THROUGH SIGN-IN. `safeLocalReturnPath` refuses any
 * `?` in a return path, and that allowlist is a security control this does not loosen. A
 * signed-out visitor who opened an order link therefore has the number stashed out of band,
 * the same pattern `serviceEntry` uses for a pending checkout, and `/orders/` picks it up once
 * the sign-in returns there.
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

/** `/orders/?o=<orderNumber>`, or the order history when the value is not an order number. */
export function orderPagePath ( orderNumber: string ): string {
  return isPublicOrderNumber( orderNumber )
    ? `/orders/?${ ORDER_PARAM }=${ encodeURIComponent( orderNumber ) }`
    : '/orders/';
}

/** The order number in the current URL, or '' when there is none or it is malformed. */
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
