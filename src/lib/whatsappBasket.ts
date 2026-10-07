/**
 * Claiming a WhatsApp catalogue basket, from the browser.
 *
 * WHAT A CLAIM IS. A customer sends their cart in the WhatsApp catalogue; the inbound Lambda writes
 * a phone-bound hand-off row and replies with a link to `/cart/?basket=<token>`. Opening that link
 * while signed in merges the lines into the customer's own Wix cart. The token alone is not
 * authority: the server additionally requires the session's verified phone to equal the phone the
 * hand-off was written for, so a leaked link cannot be redeemed by whoever holds it.
 *
 * THIS FILE SENDS A TOKEN AND NOTHING ELSE, and reads no money back. The claim is not a quote:
 * the payable is produced once, server-side, by `checkout_pricing.compute_quote`, on the `prepare`
 * that follows. Keeping that discipline here is the browser half of the reason the WhatsApp leg no
 * longer has a price of its own - there is no amount in the request and no amount in the reply.
 *
 * WHY IT IS BESIDE THE CHECKOUT CALLS RATHER THAN INSIDE `cart.tsx`. The page owns when to claim;
 * this owns how, so the shape of the request has one definition and a test can assert the payload
 * carries no price-like key the same way `toLineItems()` is asserted.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/** The same authenticated route `prepare` and `verify` use. One function, one action word. */
export const CLAIM_BASKET_URL = `${ API_BASE }/ecommerce/prepare-checkout`;

/** The query parameter the WhatsApp link carries. */
export const BASKET_PARAM = 'basket';

/**
 * What a claim did, so the page can say one honest sentence about it.
 *
 *   CLAIMED    - the lines are in the cart. Nothing more to say; the page just refreshes.
 *   CART_IN_USE - the website cart already holds items, so nothing was merged. The hand-off is
 *                 STILL CLAIMABLE: the same link works once the cart is empty, which is why this
 *                 is a distinct outcome rather than a refusal.
 *   RETRY      - a transient server state (a cart operation in flight). Worth trying again.
 *   REFUSED    - the link is spent, expired, or not this customer's. Deliberately ONE outcome for
 *                all three: the server answers them identically so the endpoint is not an
 *                existence oracle, and the browser must not invent a distinction it was not told.
 *   LOST       - the request never produced an answer, so it proves nothing either way.
 */
export type ClaimOutcome =
  | { kind: 'CLAIMED'; mergedLines: number }
  | { kind: 'CART_IN_USE'; handoffLines: number }
  | { kind: 'RETRY' }
  | { kind: 'REFUSED' }
  | { kind: 'LOST' };

/** The token from `?basket=`, or `''`. SSR-guarded, because these pages are statically exported. */
export function basketTokenFromUrl (): string {
  if ( typeof window === 'undefined' ) return '';
  try
  {
    const token = new URLSearchParams( window.location.search ).get( BASKET_PARAM ) || '';
    // Bounded here as well as on the server. A token this long was never issued, and sending it
    // would only make the server refuse it after a round trip.
    return token.length > 0 && token.length <= 100 ? token : '';
  }
  catch
  {
    return '';
  }
}

/**
 * Drop `?basket=` from the address bar without reloading or adding a history entry.
 *
 * WHY IT IS STRIPPED ON SUCCESS. A claim is single-use: the row is marked claimed and a second
 * attempt is refused. Leaving the token in the URL means a refresh, a back-button press or a
 * shared link re-posts a claim that can only fail, and the customer reads a refusal about a basket
 * that is already in their cart. `replaceState`, not `pushState`, so Back still goes where the
 * customer expects.
 */
export function stripBasketParam (): void {
  if ( typeof window === 'undefined' || !window.history?.replaceState ) return;
  try
  {
    const url = new URL( window.location.href );
    if ( !url.searchParams.has( BASKET_PARAM ) ) return;
    url.searchParams.delete( BASKET_PARAM );
    const query = url.searchParams.toString();
    window.history.replaceState( null, '', url.pathname + ( query ? `?${ query }` : '' ) + url.hash );
  }
  catch
  {
    // An unparseable location is not worth a thrown error on a page that otherwise works.
  }
}

/**
 * POST the claim. NEVER THROWS - every failure is an outcome, so the caller has no error path.
 *
 * `accessToken` is an argument rather than read here, for the reason `loadProfileStatus` takes one:
 * this closes over no state, so it adds no `useCallback` dependency and cannot go stale.
 */
export async function claimBasket ( accessToken: string, token: string ): Promise<ClaimOutcome> {
  if ( !accessToken || !token ) return { kind: 'REFUSED' };
  try
  {
    const response = await fetch( CLAIM_BASKET_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ accessToken }`,
      },
      // A token and an action. No amount, no phone, no customer id: the server takes identity from
      // the proven session and the phone from the hand-off row.
      body: JSON.stringify( { action: 'claim-basket', [ BASKET_PARAM ]: token } ),
    } );
    if ( response.status === 401 ) return { kind: 'REFUSED' };
    const data = await response.json().catch( () => null );
    const status = data && typeof data === 'object' ? String( data.status || '' ) : '';
    if ( status === 'BASKET_CLAIMED' )
    {
      return { kind: 'CLAIMED', mergedLines: Number( data.mergedLines || 0 ) };
    }
    if ( status === 'BASKET_CART_IN_USE' )
    {
      return { kind: 'CART_IN_USE', handoffLines: Number( data.handoffLines || 0 ) };
    }
    if ( status === 'CART_RECONCILIATION_REQUIRED' ) return { kind: 'RETRY' };
    if ( status === 'BASKET_UNAVAILABLE' ) return { kind: 'REFUSED' };
    // An unrecognised answer is not a refusal and not a success. Saying "lost" is the honest
    // reading of a reply this build does not understand.
    return { kind: 'LOST' };
  }
  catch
  {
    return { kind: 'LOST' };
  }
}

/** The one sentence shown for each non-success outcome. `null` means say nothing. */
export function claimMessage ( outcome: ClaimOutcome ): string | null {
  switch ( outcome.kind )
  {
    case 'CLAIMED':
      // Nothing to explain: the items are on screen, which is the whole message.
      return null;
    case 'CART_IN_USE':
      return 'Your website cart already has items in it. Empty it, then open your WhatsApp cart '
        + 'link again.';
    case 'RETRY':
      return 'Your cart is being updated. Please try again shortly.';
    case 'REFUSED':
      return 'This cart link is no longer available. Send your cart again on WhatsApp to get a '
        + 'fresh link.';
    case 'LOST':
      return 'We could not open your WhatsApp cart just now. Please try the link again.';
  }
}
