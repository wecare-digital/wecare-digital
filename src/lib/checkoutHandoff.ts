/**
 * The hand-off between /cart/ and /checkout/status/: which browser cart a payment belongs to.
 *
 * WHY THIS EXISTS. /cart/ empties the browser cart only on a VERIFIED_PAID verify reply, the one
 * moment it has server proof that the basket was paid. Every other way a payment leaves the cart
 * page goes through /checkout/status/ instead: a WhatsApp payment request, a basket that already
 * has a live payment (CHECKOUT_AMBIGUOUS), and a Razorpay payment whose verify reply was lost or
 * did not confirm. That screen learns the attempt was paid, but it never knew which cart it came
 * from, so the paid basket stayed in the browser and the next visit to /cart/ offered it again.
 *
 * So /cart/ records the attempt it handed off (`rememberCheckoutAttempt`), and the status screen
 * empties the cart only when the attempt the server reports PAID is that same attempt
 * (`settlePaidCheckout`). A status link opened later, in another tab or for an older payment,
 * names a different attempt and leaves the current cart alone.
 *
 * sessionStorage, not localStorage: the hand-off happens in this tab, and a stale marker must not
 * outlive the tab it was written in.
 */
import { clearCart } from './cart';

/** The idempotency key the current basket's checkout reuses on every retry. */
export const CHECKOUT_REQUEST_KEY = 'wc_checkout_request_key';
/**
 * The basket fingerprint the request key above was minted for.
 *
 * TWO SLOTS, FIXED, so there is no growth to bound: one key plus the basket it belongs to. Keying
 * the slot NAME on the fingerprint was the alternative and is worse - it leaves basket A's key
 * sitting there when the customer edits back to A, and resuming it is a GUARANTEED refusal rather
 * than a resumption, because getting back to A re-ran the server-side reconcile and moved both
 * `cart.revision` and `snapshot_hash`.
 */
export const CHECKOUT_REQUEST_BASKET = 'wc_checkout_request_basket';
/** The attempt /cart/ last handed to /checkout/status/. */
const HANDED_OFF_ATTEMPT = 'wc_checkout_handed_off_attempt';

/** Record the attempt this cart's payment is now tracked under. Storage may be off; that is fine. */
export function rememberCheckoutAttempt ( attemptId: string ): void {
  if ( typeof window === 'undefined' || !attemptId ) return;
  try { window.sessionStorage.setItem( HANDED_OFF_ATTEMPT, attemptId ); }
  catch { /* storage disabled: the cart simply survives, as it did before */ }
}

/**
 * The server has confirmed `attemptId` PAID. Empty the cart and its request-key slots when this
 * tab's cart is the one that attempt paid for. Returns whether it did.
 */
export function settlePaidCheckout ( attemptId: string ): boolean {
  if ( typeof window === 'undefined' || !attemptId ) return false;
  try
  {
    if ( window.sessionStorage.getItem( HANDED_OFF_ATTEMPT ) !== attemptId ) return false;
    clearCart();
    window.sessionStorage.removeItem( CHECKOUT_REQUEST_KEY );
    window.sessionStorage.removeItem( CHECKOUT_REQUEST_BASKET );
    window.sessionStorage.removeItem( HANDED_OFF_ATTEMPT );
    return true;
  }
  catch
  {
    return false;
  }
}
