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

import type { ClaimedLine } from './cart';

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
  | { kind: 'CLAIMED'; mergedLines: number; lines: ClaimedLine[] }
  | { kind: 'CART_IN_USE'; handoffLines: number }
  | { kind: 'RETRY' }
  | { kind: 'REFUSED' }
  | { kind: 'LOST' };

/**
 * One claimed line: a catalogue reference and a quantity, which is the whole of it.
 *
 * NO PRICE FIELD, AND NOTHING TO PUT IN ONE. The server merged these into the Wix cart and
 * returned them so the browser cart can hold the same basket; the amount still comes from
 * `checkout_pricing.compute_quote` on the prepare that follows, and the figure shown beside the
 * line comes from the committed catalogue snapshot every other cart line already reads.
 *
 * One declaration, in the module that owns the cart storage (see `src/lib/cart.ts`). Re-exported
 * here because the claim response is where these arrive.
 */
export type { ClaimedLine };

/** The claimed lines, validated into the shape `cart.ts` merges. Unusable entries are dropped. */
function claimedLines ( value: unknown ): ClaimedLine[] {
  if ( !Array.isArray( value ) ) return [];
  const lines: ClaimedLine[] = [];
  for ( const entry of value )
  {
    const line = entry as Partial<ClaimedLine>;
    const productId = String( line?.productId || '' ).trim();
    const variantId = String( line?.variantId || '' ).trim();
    const quantity = Math.floor( Number( line?.quantity ) );
    if ( !productId || !variantId || !Number.isFinite( quantity ) || quantity <= 0 ) continue;
    lines.push( { productId, variantId, quantity } );
  }
  return lines;
}

/**
 * Where the token waits while the customer signs in. ONE key, overwritten rather than queued.
 *
 * WHY IT IS NEEDED AT ALL. A WhatsApp link opened in the in-app browser usually has no session, so
 * the cart sends the customer to `/account/sign-in/?return=...` first. That `return` value is
 * validated by `safeLocalReturnPath` (`src/lib/safeReturnPath.ts`), which REJECTS any value
 * carrying a query string and re-emits the normalised allowlist member -- so the path that survives
 * sign-in is a bare `/cart/` and `?basket=` is gone by the time the customer arrives back. That
 * refusal is deliberate and is the control against a smuggled query, so the token travels BESIDE
 * the URL instead of inside it.
 *
 * `sessionStorage`, not `localStorage`: the stash is scoped to the tab doing the signing in and
 * disappears when it closes, so a token cannot linger on a shared device after the visit that
 * created it.
 */
const BASKET_STASH_KEY = 'wc.basketToken';

/** A token that could plausibly have been issued. The same bound the server applies. */
const usableToken = ( value: string ): string =>
  value.length > 0 && value.length <= 100 ? value : '';

/**
 * Stash the token for the sign-in round trip. Called immediately before the redirect.
 *
 * SSR-guarded and swallowing, like everything else in this file: the cart is statically exported,
 * and `sessionStorage` is not merely empty but THROWS on access in some privacy modes. A customer
 * in one of those modes loses the claim, which is the outcome they had before this stash existed;
 * a thrown error would instead take the whole cart page down.
 */
export function rememberBasketToken ( token: string ): void {
  if ( typeof window === 'undefined' || !usableToken( token ) ) return;
  try
  {
    window.sessionStorage.setItem( BASKET_STASH_KEY, token );
  }
  catch
  {
    // No stash, so no claim after sign-in. The hand-off row stays claimable for seven days and
    // re-tapping the WhatsApp link while signed in still works.
  }
}

/**
 * The token from `?basket=`, falling back to the sign-in stash. SSR-guarded, because these pages
 * are statically exported.
 *
 * THE FALLBACK IS SINGLE-USE: the key is CLEARED as it is read, whether or not the claim that
 * follows succeeds. A claim is a single-use server-side write, so a token left in the stash could
 * only be re-posted on some later visit to `/cart/` and refused -- showing a refusal for a basket
 * the customer already has. Clearing on read is what makes the stash a hand-off and not a replay.
 *
 * The URL wins when both are present. `?basket=` is the link the customer just opened; the stash
 * is at most a leftover from an earlier one.
 */
export function basketTokenFromUrl (): string {
  if ( typeof window === 'undefined' ) return '';
  let fromUrl = '';
  try
  {
    // Bounded here as well as on the server. A token this long was never issued, and sending it
    // would only make the server refuse it after a round trip.
    fromUrl = usableToken( new URLSearchParams( window.location.search ).get( BASKET_PARAM ) || '' );
  }
  catch
  {
    fromUrl = '';
  }
  if ( fromUrl ) return fromUrl;
  try
  {
    const stashed = window.sessionStorage.getItem( BASKET_STASH_KEY ) || '';
    window.sessionStorage.removeItem( BASKET_STASH_KEY );
    return usableToken( stashed );
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
export async function claimBasket ( accessToken: string, token: string,
                                    options: { resetCart?: boolean } = {} ): Promise<ClaimOutcome> {
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
      //
      // `resetCart` is sent ONLY on the one retry described in `cart.tsx`, and only as a literal
      // `true` - the server compares with `is True`, so the key is omitted rather than sent false.
      body: JSON.stringify( {
        action: 'claim-basket',
        [ BASKET_PARAM ]: token,
        ...( options.resetCart ? { resetCart: true } : {} ),
      } ),
    } );
    if ( response.status === 401 ) return { kind: 'REFUSED' };
    const data = await response.json().catch( () => null );
    const status = data && typeof data === 'object' ? String( data.status || '' ) : '';
    if ( status === 'BASKET_CLAIMED' )
    {
      return { kind: 'CLAIMED', mergedLines: Number( data.mergedLines || 0 ),
        lines: claimedLines( data.lines ) };
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

/**
 * A claim succeeded and this build could place NONE of its lines in the visible cart.
 *
 * Reachable for a product that exists in the live Wix catalogue - and therefore in the WhatsApp
 * catalogue the sync projects from it - but not in `src/content/wix-catalog.json`, the snapshot
 * committed with this deployment. A product added in Wix since the last catalogue sync is exactly
 * that case. Saying nothing here would reproduce the failure the returned lines exist to fix:
 * a successful claim that looks identical to a refusal.
 *
 * It does NOT suggest reloading. The claim is spent and the lines are in the server-side cart, so
 * a reload would place exactly as little; the only action that moves this forward is a reply on
 * WhatsApp.
 */
export const CLAIM_NOT_SHOWN_MESSAGE =
  'Your WhatsApp cart was received, but this page cannot show those items yet. Reply on WhatsApp '
  + 'and we will finish the order with you.';

/** The one sentence shown for each non-success outcome. `null` means say nothing. */
export function claimMessage ( outcome: ClaimOutcome ): string | null {
  switch ( outcome.kind )
  {
    case 'CLAIMED':
      // Nothing to explain: the items are on screen, which is the whole message. That is now TRUE
      // rather than aspirational - `cart.tsx` merges `outcome.lines` into the browser cart before
      // this is consulted, and says `CLAIM_NOT_SHOWN_MESSAGE` when it could place none of them.
      return null;
    case 'CART_IN_USE':
      // ONLY REACHED WITH A NON-EMPTY BROWSER CART, which is what makes this instruction
      // performable. The server condition is the saved `CUSTOMERCART#` pointer, and emptying
      // localStorage does not release it - so `cart.tsx` retries once with `resetCart: true` when
      // its own cart is already empty, and this sentence is shown only when the customer really
      // does have website items to clear. Byte-identical to the handler's own
      // `BASKET_CART_IN_USE` message, pinned equal by
      // `tests/test_checkout_claim_basket.py::test_the_cart_in_use_sentence_is_the_same_on_both_sides`.
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
