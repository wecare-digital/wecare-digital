/**
 * /cart/ - the cart review page and the checkout `create` handoff.
 *
 * WHAT IT DOES. Lists the cart (name + Wix formattedPrice for DISPLAY only), lets the shopper
 * change quantities or remove lines, and on "Proceed to checkout" ensures a customer session then
 * POSTs {action:'create', lineItems} to {NEXT_PUBLIC_API_BASE}/ecommerce/checkout with a
 * Authorization: Bearer token from getSession(). The lineItems carry catalogue references and
 * quantities ONLY (src/lib/cart.ts, toLineItems) - the browser never sends a price.
 *
 * THE AUTH GATE. The checkout create endpoint requires an authenticated customer
 * (customer_auth.require_customer). If getSession() is null the shopper is sent to
 * /account/sign-in/?return=/cart/ FIRST and returned here afterwards; the cart is in localStorage
 * so it survives the redirect. A signed-in shopper proceeds directly. A test asserts that a null
 * session routes to sign-in and makes NO create call.
 *
 * THE READINESS QUESTION IS ASKED BEFORE ANYTHING IS RENDERED. This page used to decide whether to
 * show the checkout form from `profile`, a piece of state that is null on every arrival - so a
 * customer who had already saved their name, verified email and delivery address was shown the
 * form again, every single visit. It now POSTs {action:'profile'} on mount and again on the click,
 * and renders the form only when the answer says something is missing. A returning customer gets
 * CheckoutIdentityCard - what we already know, with three edit affordances - and no form at all.
 *
 * TWO RULES ABOUT THAT ANSWER, and both are the difference between a sale and a dead end.
 *   1. `proceed` branches on a LOCAL `status`, assigned from `deriveStatus`'s RETURN value, never
 *      on the `profileStatus` state. `setProfileStatus` cannot change the value captured in the
 *      `useCallback` closure, so branching on the state after setting it means the 'ready' arm is
 *      never taken on a first click.
 *   2. 'ready' AND 'unknown' BOTH continue to the prepare POST. `deriveStatus` answers 'unknown'
 *      for a 500, a network failure, a parse failure or a status string this build does not
 *      recognise, and the server's own 409 arms are the authority on readiness - so a transient
 *      index blip costs one wasted prepare call and the customer still pays. A FAILED READINESS
 *      READ MUST NEVER BE THE THING THAT STOPS A PAYABLE CUSTOMER.
 *
 * TRUTHFUL RESPONSE HANDLING - the honesty requirement. The create responses are mapped exactly as
 * checkout/handler.py documents them:
 *   PAYMENT_INITIATION_DISABLED (200) -> INLINE, cart preserved: the server's initiation gate is
 *     off, so it stopped before the payment rail and no charge can have been made. Offers NO
 *     pay-now button. It does NOT hand off to /checkout/status/ - see NOT_PREPARED below for why
 *     that screen cannot carry this claim.
 *   PAYMENT_REQUEST_SENT (200)        -> /checkout/status/?a=<paymentAttemptId> (in-flight view).
 *     RETAINED legacy in-chat response: the server still returns it for the in-WhatsApp flow and
 *     this mapping stays until that path is migrated. See the website contract note below.
 *   payment_unavailable (409)         -> inline: no charge was made.
 *   SEND_FAILED (502)                 -> inline, with a retry: no charge was made.
 *   LINE_ITEMS_REQUIRED (400)         -> empty-cart state.
 *   UNSUPPORTED_CURRENCY / AMOUNT_NOT_SETTLED / CATALOGUE_UNAVAILABLE -> honest error copy.
 *   401                               -> session gone: back to sign-in.
 * There is NEVER a control that claims to take payment while initiation is off.
 *
 * "No charge was made" APPEARS ONLY WHERE THE SERVER HAS SAID SO. Each notice below is reached from
 * a status that means the attempt never got as far as money moving - the initiation gate was off, a
 * readiness block, a message that did not send, a request that was refused or one that never left
 * the browser. It is deliberately absent from the one path that hands off to /checkout/status/,
 * because once an attempt is in flight the browser cannot know whether the money moved, and neither
 * this page nor that one may guess.
 *
 * ADDITIVE WEBSITE RAZORPAY STANDARD CHECKOUT CONTRACT (section 8), replacing PAYMENT_REQUEST_SENT
 * for the website path without removing it for the in-chat path. The backend
 * (lambda_utils/ecommerce/website_checkout.py) returns, behind the SAME initiation gate:
 *   PAYMENT_INITIATION_DISABLED (gate off, the default) -> INLINE, cart preserved, no pay button:
 *     the gate is off, no Razorpay gateway order was created and no charge can have been made.
 *   CHECKOUT_OPTIONS_READY (gate on) -> the browser opens the Razorpay Standard Checkout hosted
 *     modal with ONLY {keyId (public), orderId (server-stored gateway order id), amountPaise
 *     (the FEAT-001 calculator total: collection+fee+GST, never the raw Wix total), currency,
 *     prefill, paymentAttemptId}. The modal's result is POSTed back to the owned backend
 *     callback, which verifies the signature over the STORED order id and STILL requires an
 *     authoritative Razorpay capture before any paid state.
 *   CHECKOUT_REJECTED -> inline, no charge was made (ownership/snapshot/intent failed).
 *   CHECKOUT_AMBIGUOUS -> hand off to /checkout/status/; the browser must not claim a charge was
 *     or was not made, exactly as the in-flight rule above requires.
 * Cart/resume data is kept until a VERIFIED_PAID finalization. "No charge was made" still appears
 * ONLY where the server has said so (the gate-off, rejected and unavailable paths), never once a
 * gateway order exists.
 *
 * CHROME AND INDEXING. Customer-session route registered in the _app.tsx isPublic chain beside
 * /checkout/status and /checkout/success; noindex; imports no Layout/Header/Footer/SupportWidget.
 * Absent from PUBLIC_PAGE_META, the sitemap and the browser route lists.
 *
 * THE TOP BAND IS SHARED. components/PageTopBand owns the main landmark, the h1, the 108px/96px
 * header clearance, the 1300px measure and the entrance animation, so this page cannot drift from
 * the fifteen routes built on RotatingHero. The band carries no price and no button: §6 of the
 * new-public-page skill puts the action further down, which is where the lime CTA sits.
 */

import Head from 'next/head';
import Link from 'next/link';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import PageTopBand from '../components/PageTopBand';
import PillButton from '../components/PillButton';
import CheckoutProfile from '../components/CheckoutProfile';
import type { CheckoutProfileMode, CheckoutProfileValue } from '../components/CheckoutProfile';
import CheckoutIdentityCard from '../components/CheckoutIdentityCard';
import type { StoredAddress } from '../components/AddressFields';
import { getSession, restoreSession } from '../lib/customerAuth';
import type { CustomerSession } from '../lib/customerAuth';
import {
  readCart, setQuantity, removeItem, clearCart, toLineItems, availableVariantsForItem,
  needsVariantSelection, setVariant,
  basketFingerprint, cartRequiresDelivery,
  isContributionItem, setContribution, serviceIntentFor,
} from '../lib/cart';
import { SERVICE_REFUSAL_MESSAGES, isServiceRefusal } from '../lib/serviceRequests';
import type { CartItem, CheckoutLineItem } from '../lib/cart';
// The WhatsApp catalogue hand-off. The page owns WHEN to claim; the module owns HOW, so the
// request shape has one definition. See `src/lib/whatsappBasket.ts`.
import {
  basketTokenFromUrl, claimBasket, claimMessage, stripBasketParam,
} from '../lib/whatsappBasket';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../config/contribution';
import { colors } from '../lib/design-tokens';
/**
 * THE OPAQUE SQUARE MARK, and it has to be that one. Razorpay composites this logo onto its own
 * modal surface, so it is a renderer we do not control - exactly the case src/test/BrandAssets.
 * test.ts bans `wecaredigital.png` from, because that file is 68.4% transparent with a black mark
 * and flattens to an invisible logo on a dark ground. `schema.ts`'s LOGO_URL is the 1080x1080
 * opaque-white-ground asset already serving apple-touch-icon and the Organization logo, and it is
 * imported rather than restated so the two cannot drift.
 */
import { LOGO_URL } from '../lib/schema';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const PREPARE_CHECKOUT_URL = `${API_BASE}/ecommerce/prepare-checkout`;
const VERIFY_CHECKOUT_URL = `${API_BASE}/ecommerce/verify-callback`;
const RAZORPAY_SDK = 'https://checkout.razorpay.com/v1/checkout.js';
const CHECKOUT_REQUEST_KEY = 'wc_checkout_request_key';
/**
 * The basket fingerprint the request key above was minted for.
 *
 * TWO SLOTS, FIXED, so there is no growth to bound: one key plus the basket it belongs to. Keying
 * the slot NAME on the fingerprint was the alternative and is worse - it leaves basket A's key
 * sitting there when the customer edits back to A, and resuming it is a GUARANTEED refusal rather
 * than a resumption, because getting back to A re-ran the server-side reconcile and moved both
 * `cart.revision` and `snapshot_hash`.
 */
const CHECKOUT_REQUEST_BASKET = 'wc_checkout_request_basket';
/**
 * What to say when the server refuses the contribution amount.
 *
 * It names the three amounts rather than a range, because there is no range: a contribution is one
 * of three fixed-price variants. DERIVED from `CONTRIBUTION_CHOICES`, so the sentence cannot offer
 * an amount the server does not accept - which a re-typed list eventually would.
 *
 * Reachable only from a crafted request or a cart written by an older build, since the only
 * controls that write a contribution line emit one of the three. Kept because the server can
 * answer it and a dead end is worse than a sentence.
 */
const CONTRIBUTION_HELP = `Choose one of the offered contribution amounts: ${
  CONTRIBUTION_CHOICES.map( choice => `\u20B9${ choice.rupees }` ).join( ', ' ) }.`;
/**
 * One contribution at a time.
 *
 * IT USED TO SAY "a contribution is paid on its own", AND THAT RULE IS GONE. Owner decision,
 * 2026-10-06: a product and a contribution check out together, priced the way any single order is
 * priced -- Wix prices every line and `checkout_pricing` adds the 2.5% convenience fee plus 18%
 * GST on that fee over the whole collection. So there is no longer a browser-side mixed-basket
 * refusal, no notice and no disabled CTA for one.
 *
 * What remains is the server's narrowed `CONTRIBUTION_NOT_ALONE`: TWO contribution lines, which
 * is two contributions in one payment and has no single expected collection. Still ONE constant
 * shared with that outcome arm, so the sentence the customer reads is word for word the server's
 * own message.
 *
 * REACHABLE ONLY FROM A CRAFTED REQUEST, because `setContribution` replaces the contribution line
 * rather than adding to it. Kept for the same reason `CONTRIBUTION_HELP` is: the server can
 * answer it, and a dead end is worse than a sentence.
 */
const CONTRIBUTION_ALONE_MESSAGE =
  'Only one contribution can be paid at a time. Remove the extra contribution, then check out.';
/** The same words the blog block uses when the product is not configured. */
const CONTRIBUTION_UNAVAILABLE_MESSAGE = 'Contributions are not available right now.';
/**
 * What to say when the server could price nothing for a contribution basket.
 *
 * SEPARATE from `CART_NOT_PAYABLE`'s "Please review your cart and try again", because that names
 * the one action a contribution basket cannot take: it holds a single donation, so there is
 * nothing in it to review and no edit the customer can make that changes the answer. The second
 * sentence is there because this refusal arrives AFTER the Checkout press, which reads like a
 * failed payment unless it says otherwise - nothing is reserved, attempted or charged on this
 * path. Word for word the server's `CONTRIBUTION_NOT_PAYABLE` message.
 */
const CONTRIBUTION_NOT_PAYABLE_MESSAGE =
  'Contributions cannot be taken right now. Nothing has been charged.';
/**
 * SECTION 2 REDEMPTION ENDPOINT. The coupon/gift-card apply/remove requests go here; the SERVER
 * decides every amount (an authoritative Wix/backend discount, an authoritative gift-card balance),
 * and this page only ever RENDERS what the server returns. The browser never computes a discount or
 * a payable, and never sends an amount - it sends a code and an action, nothing more.
 */
const REDEMPTION_URL = `${API_BASE}/ecommerce/redemption`;

/** Where an unauthenticated shopper is sent, and returned from, before checkout. */
const SIGN_IN_PATH = '/account/sign-in/?return=/cart/';

/**
 * Rupees from authoritative integer paise, for DISPLAY ONLY. The server owns the arithmetic; this
 * is a presentation of a number the server already decided, never a calculation the total depends
 * on. ``₹1,214.81`` from ``121481``. Grouping is Indian (lakh/crore) via Intl.
 */
function paiseToDisplay ( paise: number ): string {
  const rupees = Math.round( paise ) / 100;
  return '₹' + rupees.toLocaleString( 'en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 } );
}

/**
 * THE OWNER-APPROVED INITIATION-FAILURE SENTENCE, verbatim, in one place.
 *
 * ITS PLACEMENT IS THE WHOLE OF ITS CORRECTNESS. It asserts that no charge was made, so it may be
 * shown only where the backend has said something that rules a charge out - the initiation gate was
 * off, readiness refused, the request was rejected, or it never left the browser. Every use below is
 * one of those. It is deliberately ABSENT from the two handoffs to /checkout/status/ and from that
 * screen entirely: once an attempt is live, "pending", "unknown" and "captured but not finalised"
 * are indistinguishable from here, and inviting a retry in any of them risks a second charge.
 *
 * A constant rather than four string literals so the claim has exactly one definition to audit, and
 * so a future edit cannot drift one copy of it onto a path that cannot support it.
 */
const NOT_PREPARED = 'We could not prepare this order. No charge was made - please try again shortly.';

/** The inline states this page can show without leaving it. Handoffs navigate instead. */
type Notice =
  | { kind: 'none' }
  | { kind: 'quiet'; message: string }
  | { kind: 'error'; message: string };

/**
 * THE READINESS QUESTION, ASKED BEFORE ANYTHING IS RENDERED.
 *
 *   unknown  - not asked yet, or the answer never arrived (network, 5xx, bad JSON, a status
 *              string this build does not recognise). NEVER a block: see `proceed`.
 *   checking - a status call is in flight. A renderable state, deliberately NOT a lock.
 *   ready    - PAYABLE NOW: profile complete AND an address on file.
 *   required - something the customer must supply before the server will price the cart.
 */
type ProfileStatus = 'unknown' | 'checking' | 'ready' | 'required';

/** The `action:'profile'` reply. PROFILE_REQUIRED carries ONLY `status`; the rest are absent. */
type ProfileReply = {
  status?: string;
  contactId?: string;
  name?: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  emailVerified?: boolean;
  addressComplete?: boolean;
  address?: StoredAddress | null;
};

/**
 * ONE DERIVATION OF `profileStatus`, USED BY EVERY WRITER - the mount effect, `proceed`'s own
 * status call, the server arms and `onReady`.
 *
 * `'ready'` means PAYABLE NOW: profile complete *and* an address on file. So a customer with a
 * verified email and no stored address is `'required'` and never sees an identity card with an
 * empty Deliver row. It is a PURE function precisely so a caller can branch on its RETURNED value
 * rather than on the state it later writes - see `proceed`.
 */
const deriveStatus = ( status: string, addressComplete: boolean ): ProfileStatus =>
  status === 'PROFILE_READY' && addressComplete ? 'ready'
    : status === 'PROFILE_READY' || status === 'PROFILE_REQUIRED' ? 'required'
      : 'unknown';

/**
 * The reply projected onto the editor's value type, or `null` when there is no profile to hold.
 *
 * NULL FOR ANYTHING BUT `PROFILE_READY`, DELIBERATELY. `PROFILE_REQUIRED` carries one key, so a
 * projection of it would be an all-empty object - non-null, and therefore read by the CTA label
 * and by `initial` as "we know who this is". A first-time shopper would be shown "Pay securely"
 * over a form they have not filled in. Absent is the honest value for absent.
 */
function profileFrom ( reply: ProfileReply ): CheckoutProfileValue | null {
  if ( String( reply.status || '' ) !== 'PROFILE_READY' ) return null;
  return {
    contactId: String( reply.contactId || '' ),
    name: String( reply.name || '' ),
    firstName: String( reply.firstName || '' ),
    lastName: String( reply.lastName || '' ),
    email: String( reply.email || '' ),
    phone: String( reply.phone || '' ),
    addressComplete: Boolean( reply.addressComplete ),
    address: reply.address || null,
  };
}

/**
 * THE READINESS READ, WHICH NEVER THROWS. Returns the parsed reply, or `null` on a network
 * failure, a 4xx, a 5xx or a body that will not parse.
 *
 * Both answers are 200 and the state is in `status`, never in the status code - a 409 here would
 * make the browser treat a normal first-time customer as an error. It takes the token as an
 * ARGUMENT and closes over no state, so it adds no `useCallback` dependency and cannot go stale.
 */
async function loadProfileStatus ( accessToken: string ): Promise<ProfileReply | null> {
  try
  {
    const response = await fetch( PREPARE_CHECKOUT_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ accessToken }`,
      },
      body: JSON.stringify( { action: 'profile' } ),
    } );
    if ( !response.ok ) return null;
    const data = await response.json().catch( () => null );
    if ( !data || typeof data !== 'object' ) return null;
    return data as ProfileReply;
  }
  catch
  {
    // A lost readiness read is not an answer, and it is never a refusal either.
    return null;
  }
}

/**
 * What a `prepare` POST did, so the caller can act on it ONCE - including after a retry.
 *
 *   OPENED / NAVIGATED - the rail was entered or the browser was handed off; nothing left to say.
 *   UNAUTHORIZED       - 401, the session is gone.
 *   MALFORMED          - CHECKOUT_OPTIONS_READY with options the browser cannot open.
 *   SDK_UNAVAILABLE    - the hosted checkout script would not load.
 *   LOST               - the response never arrived, so it proves nothing in either direction.
 *   everything else    - the server's own status/error string, verbatim.
 */
type Outcome =
  | { kind: 'OPENED' }
  | { kind: 'NAVIGATED' }
  | { kind: 'UNAUTHORIZED' }
  | { kind: 'MALFORMED' }
  | { kind: 'SDK_UNAVAILABLE' }
  | { kind: 'LOST' }
  | { kind: 'PROFILE_REQUIRED' }
  | { kind: 'DELIVERY_DETAILS_REQUIRED' }
  | { kind: 'DELIVERY_METHOD_UNAVAILABLE' }
  | { kind: 'CHECKOUT_REJECTED'; reason: string }
  | { kind: 'CONTRIBUTION_AMOUNT_INVALID' }
  | { kind: 'CONTRIBUTION_NOT_ALONE' }
  | { kind: 'CONTRIBUTION_UNAVAILABLE' }
  | { kind: 'CONTRIBUTION_REDEMPTION_NOT_ALLOWED' }
  | { kind: 'CONTRIBUTION_NOT_PAYABLE' }
  | { kind: 'SERVICE_REFUSED'; message: string }
  | { kind: 'CART_RESET_REQUIRED' }
  | { kind: 'CART_NOT_PAYABLE' }
  | { kind: 'CART_RECONCILIATION_REQUIRED' }
  | { kind: 'ITEMS_UNAVAILABLE' }
  | { kind: 'QUANTITY_REDUCED' }
  | { kind: 'PAYMENT_INITIATION_DISABLED' }
  | { kind: 'PAYMENT_UNAVAILABLE' }
  | { kind: 'LINE_ITEMS_REQUIRED' }
  | { kind: 'SEND_FAILED' }
  | { kind: 'PRICING_UNAVAILABLE' }
  | { kind: 'ITEM_UNAVAILABLE' }
  | { kind: 'UNRECOGNISED' };

/**
 * The one wait before the single post-save `prepare` retry.
 *
 * `_checkout_profile` and `_load_owned_address` both read `phone-index`, a GLOBAL secondary index,
 * which cannot be read strongly consistent - so a `prepare` issued immediately after a save can
 * legitimately see the pre-save row. A mitigation, not a guarantee.
 */
const POST_SAVE_RETRY_MS = 1200;

const sleep = ( ms: number ): Promise<void> => new Promise( resolve => {
  setTimeout( resolve, ms );
} );

type RazorpaySuccess = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description: string;
  /** Absolute URL of the brand mark Razorpay paints at the head of its modal. */
  image?: string;
  /** Razorpay tints the modal header and its primary button with this hex. */
  theme?: { color: string };
  prefill?: Record<string, string>;
  handler: ( result: RazorpaySuccess ) => void | Promise<void>;
  modal?: { ondismiss?: () => void };
};

/**
 * WHAT THE MODAL CALLS THIS PAYMENT, derived from the basket being sent and nothing else.
 *
 * A CONTRIBUTION IS NOT AN ORDER, which is why this is a branch rather than one string. The terms
 * say so in as many words - a contribution "does not create an order, a product or a shipment" -
 * so labelling a contribution modal "Order payment" would be the payment surface contradicting
 * the agreement the same page links to.
 *
 * IT TAKES THE LINE ITEMS AS AN ARGUMENT for the same reason `postPrepare` takes everything as
 * one: the descriptor must describe the basket in THIS request body, and reading component state
 * here would let the post-save retry label a basket it is not sending. `CheckoutLineItem` carries
 * a catalogue reference and a quantity only - never a name and never a price - so the item count
 * is the most this can honestly say about a mixed basket, and no money figure appears in it.
 *
 * Falls back to 'Order payment' for an empty list, which `proceed` does not produce.
 */
function checkoutDescription ( lineItems: CheckoutLineItem[] ): string {
  if ( lineItems.length === 0 ) return 'Order payment';
  const allContribution = !!CONTRIBUTION_PRODUCT_ID && lineItems.every(
    line => line.catalogReference.catalogItemId === CONTRIBUTION_PRODUCT_ID,
  );
  if ( allContribution ) return 'Contribution to WECARE.DIGITAL';
  const units = lineItems.reduce( ( total, line ) => total + line.quantity, 0 );
  return units === 1 ? 'Order payment - 1 item' : `Order payment - ${ units } items`;
}

declare global {
  interface Window {
    Razorpay?: new ( options: RazorpayOptions ) => {
      open: () => void;
      on: ( event: string, callback: ( payload: unknown ) => void ) => void;
    };
  }
}

/**
 * ONE REQUEST KEY, PLUS THE BASKET FINGERPRINT IT WAS MINTED FOR.
 *
 * The reservation's purpose is to make two clicks on the SAME basket resume one gateway order
 * instead of minting two. It was never meant to outlive the basket: a changed basket is a different
 * intent, `website_checkout.intent_fingerprint` refuses a resumed key whose intent moved, and
 * `applyOutcome` rendered that refusal as a PERMANENT `CHECKOUT_REJECTED` with `paymentBlocked`
 * latched for the life of the tab and no retry arm. The key was minted once per tab and the three
 * references to its slot never removed it. Recording the fingerprint keeps the property that was
 * wanted and drops the one that was not.
 *
 * RETURNING TO AN EARLIER BASKET MINTS A FRESH KEY, DELIBERATELY. One slot cannot be stale in the
 * way a per-basket slot can: edits to A, then B, then back to A re-ran the server-side reconcile,
 * whose add/remove commands mint new `lineItemId`s and move `cart.revision`, so A's original
 * reservation CANNOT match any more and resuming it would be a guaranteed refusal.
 *
 * IT TAKES THE PAYLOAD IT IS KEYING, for the same reason `postPrepare` takes everything as
 * arguments. The key must describe the basket in THIS request body. The no-argument,
 * read-from-storage rule applies to the render-path helpers, where the alternative is component
 * state captured by `useCallback`; here the value is a parameter already in hand at the call site,
 * and re-reading storage would let the post-save retry key a basket it is not sending.
 */
function getCheckoutRequestKey ( lineItems: CheckoutLineItem[] ): string {
  if ( typeof window === 'undefined' ) return '';
  // Phase O-1: a services basket also keys on its intent id, so switching an amendment's target
  // (same lines, new intent) mints a fresh key instead of resuming the superseded attempt. The
  // server refuses that resume with INTENT_CHANGED regardless; this saves the round trip. Every
  // other basket's fingerprint is byte-identical to before.
  const serviceIntent = serviceIntentFor( lineItems );
  const fingerprint = serviceIntent
    ? `${ basketFingerprint( lineItems ) }|intent:${ serviceIntent }`
    : basketFingerprint( lineItems );
  const minted = window.sessionStorage.getItem( CHECKOUT_REQUEST_BASKET );
  const existing = window.sessionStorage.getItem( CHECKOUT_REQUEST_KEY );
  if ( existing && minted === fingerprint ) return existing;
  const generated = typeof window.crypto?.randomUUID === 'function'
    ? window.crypto.randomUUID()
    : `checkout-${ Date.now() }-${ Math.random().toString( 36 ).slice( 2 ) }`;
  window.sessionStorage.setItem( CHECKOUT_REQUEST_KEY, generated );
  window.sessionStorage.setItem( CHECKOUT_REQUEST_BASKET, fingerprint );
  return generated;
}

function loadRazorpaySdk (): Promise<boolean> {
  if ( typeof window === 'undefined' ) return Promise.resolve( false );
  if ( window.Razorpay ) return Promise.resolve( true );
  const existing = document.querySelector<HTMLScriptElement>( `script[src="${ RAZORPAY_SDK }"]` );
  if ( existing ) {
    return new Promise( resolve => {
      existing.addEventListener( 'load', () => resolve( Boolean( window.Razorpay ) ), { once: true } );
      existing.addEventListener( 'error', () => resolve( false ), { once: true } );
    } );
  }
  return new Promise( resolve => {
    const script = document.createElement( 'script' );
    script.src = RAZORPAY_SDK;
    script.async = true;
    script.onload = () => resolve( Boolean( window.Razorpay ) );
    script.onerror = () => resolve( false );
    document.head.appendChild( script );
  } );
}

/**
 * THE SERVER-AUTHORITATIVE REDEMPTION RESPONSE, projected to the browser-safe fields only. Every
 * amount here was decided by the server; the browser renders them and never recomputes them.
 *   state                      - the backend's typed outcome the UI branches on.
 *   couponReason               - APPLIED / INVALID / EXPIRED / INELIGIBLE (coupon states).
 *   giftCardReason             - APPLIED / INVALID / EXPIRED / INELIGIBLE / INSUFFICIENT_BALANCE.
 *   discountPaise              - the authoritative coupon discount in integer paise.
 *   giftCardAppliedPaise       - the authoritative verified gift-card redemption in integer paise.
 *   remainingPayablePaise      - authoritative total - verified redemption, in integer paise.
 */
type RedemptionResponse = {
  state?: string;
  couponReason?: string;
  giftCardReason?: string;
  discountPaise?: number;
  giftCardAppliedPaise?: number;
  remainingPayablePaise?: number;
};

/** The honest copy for a gated-off / unavailable redemption surface. No provider name, ever. */
const REDEMPTION_UNAVAILABLE = 'Discounts and gift cards are not available right now.';

/** Human copy for each server-returned coupon reason. Keyed by the server's typed reason. */
const COUPON_MESSAGES: Record<string, string> = {
  INVALID: 'That coupon code is not valid.',
  EXPIRED: 'That coupon has expired.',
  INELIGIBLE: 'That coupon does not apply to the items in your cart.',
};

/** Human copy for each server-returned gift-card reason. */
const GIFT_CARD_MESSAGES: Record<string, string> = {
  INVALID: 'That gift-card code is not valid.',
  EXPIRED: 'That gift card has expired.',
  INELIGIBLE: 'That gift card cannot be used for this order.',
  INSUFFICIENT_BALANCE: 'That gift card has no balance left to use.',
};

type RedeemKind = 'coupon' | 'giftCard';

/**
 * THE COUPON + GIFT-CARD PANEL, built but honest while the backend gate is off.
 *
 * WHAT IS TRUE ABOUT IT.
 *   1. Every displayed amount - the applied discount, the applied gift-card amount, the remaining
 *      payable balance - comes from the server response, never from browser arithmetic. The server
 *      is Wix/backend-authoritative; a browser-calculated discount is never trusted.
 *   2. With the gate off / the endpoint absent / a network failure, it shows an honest unavailable
 *      state and offers no way to transact. A browser signal is never treated as proof.
 *   3. It never fetches at render/prerender time - a request happens only on an Apply/Remove click,
 *      so the static export is not broken.
 *   4. No third-party provider name appears anywhere.
 */
/**
 * THE CONTRIBUTION ROW CHOOSES AN AMOUNT, IT DOES NOT COUNT COPIES.
 *
 * A stepper labelled "Qty" is the wrong control for a contribution: two copies of a Rs.250
 * contribution is not a Rs.500 contribution, it is a basket the server refuses as two
 * contributions. So the row offers the three amounts instead of a count.
 *
 * A NATIVE `<select>` ON PURPOSE, AND IT REPLACED A FREE-TEXT FIELD (owner model change,
 * 2026-10-04). The previous revision held a draft string, committed on blur or Enter, validated
 * against Rs.10-Rs.1,00,000 bounds, and rendered a help line on refusal - all of it to keep an
 * arbitrary keystroke from becoming money, because `min`/`max`/`step` on a number input are not
 * enforced while typing or on paste. A control that can only emit one of three committed values
 * deletes that whole apparatus: there is no draft, no commit moment, no rejection and no help
 * text, because there is no invalid value to produce.
 *
 * `setContribution` still SETS rather than increments, so changing the amount replaces the line
 * rather than adding a second one.
 */
function ContributionAmount (
  { item, onCommitted }: { item: CartItem; onCommitted: () => void },
): React.ReactElement {
  const inputId = `amount-${ item.ref }`;

  return (
    <>
      <label className="cart-qty-label" htmlFor={ inputId }>Contribute amount</label>
      <select
        id={ inputId }
        className="cart-amount-select"
        value={ item.variantId }
        onChange={ e => { setContribution( e.target.value ); onCommitted(); } }
      >
        { CONTRIBUTION_CHOICES.map( choice => (
          <option key={ choice.variantId } value={ choice.variantId }>
            &#8377;{ choice.rupees }
          </option>
        ) ) }
      </select>
    </>
  );
}

function RedemptionPanel (): React.ReactElement {
  const [ couponCode, setCouponCode ] = useState<string>( '' );
  const [ giftCardCode, setGiftCardCode ] = useState<string>( '' );
  const [ busy, setBusy ] = useState<RedeemKind | null>( null );
  const [ unavailable, setUnavailable ] = useState<boolean>( false );
  const [ couponApplied, setCouponApplied ] = useState<number | null>( null );
  const [ couponMessage, setCouponMessage ] = useState<string>( '' );
  const [ giftCardApplied, setGiftCardApplied ] = useState<number | null>( null );
  const [ giftCardMessage, setGiftCardMessage ] = useState<string>( '' );
  const [ remainingPayable, setRemainingPayable ] = useState<number | null>( null );

  const send = useCallback( async ( kind: RedeemKind, action: 'apply' | 'remove', code: string ): Promise<void> => {
    setBusy( kind );
    setUnavailable( false );
    try {
      // CODE + ACTION ONLY. No amount, no discount, no price leaves the browser.
      const response = await fetch( REDEMPTION_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { kind, action, code } ),
      } );
      if ( !response.ok ) {
        setUnavailable( true );
        return;
      }
      const data = ( await response.json().catch( () => ( {} ) ) ) as RedemptionResponse;
      const state = String( data.state || '' ).toUpperCase();

      // Gate off / rejected / ambiguous / anything unrecognised -> honest unavailable, no amounts.
      if (
        state === 'PAYMENT_INITIATION_DISABLED' || state === 'REDEMPTION_UNAVAILABLE'
        || state === 'CHECKOUT_REJECTED' || state === 'CHECKOUT_AMBIGUOUS' || state === ''
      ) {
        setUnavailable( true );
        return;
      }

      // The server-authoritative remaining payable, when the server reports one.
      if ( typeof data.remainingPayablePaise === 'number' ) {
        setRemainingPayable( data.remainingPayablePaise );
      }

      if ( kind === 'coupon' ) {
        const reason = String( data.couponReason || '' ).toUpperCase();
        if ( action === 'remove' ) {
          setCouponApplied( null );
          setCouponMessage( '' );
          return;
        }
        if ( reason === 'APPLIED' && typeof data.discountPaise === 'number' ) {
          setCouponApplied( data.discountPaise );   // server authority, never browser math
          setCouponMessage( '' );
        } else {
          setCouponApplied( null );
          setCouponMessage( COUPON_MESSAGES[ reason ] || COUPON_MESSAGES.INVALID );
        }
        return;
      }

      // gift card
      const reason = String( data.giftCardReason || '' ).toUpperCase();
      if ( action === 'remove' ) {
        setGiftCardApplied( null );
        setGiftCardMessage( '' );
        return;
      }
      if ( reason === 'APPLIED' && typeof data.giftCardAppliedPaise === 'number' ) {
        setGiftCardApplied( data.giftCardAppliedPaise );  // server authority, never browser math
        setGiftCardMessage( '' );
      } else {
        setGiftCardApplied( null );
        setGiftCardMessage( GIFT_CARD_MESSAGES[ reason ] || GIFT_CARD_MESSAGES.INVALID );
      }
    } catch {
      // A lost response cannot prove a redemption; degrade to the honest unavailable state.
      setUnavailable( true );
    } finally {
      setBusy( null );
    }
  }, [] );

  return (
    <section className="cart-redeem" aria-label="Discounts and gift cards">
      {/* COUPON */}
      <div className="cart-redeem-group">
        <label className="cart-redeem-label" htmlFor="cart-coupon">Coupon code</label>
        <div className="cart-redeem-row">
          <input
            id="cart-coupon"
            className="cart-redeem-input"
            type="text"
            autoComplete="off"
            value={ couponCode }
            onChange={ e => setCouponCode( e.target.value ) }
          />
          <button
            className="cart-redeem-apply"
            type="button"
            disabled={ busy !== null || couponCode.trim() === '' }
            onClick={ () => send( 'coupon', 'apply', couponCode.trim() ) }
          >
            { busy === 'coupon' ? 'Applying…' : 'Apply' }
          </button>
          { couponApplied !== null && (
            <button
              className="cart-redeem-remove"
              type="button"
              disabled={ busy !== null }
              onClick={ () => send( 'coupon', 'remove', '' ) }
            >
              Remove
            </button>
          ) }
        </div>
        { couponApplied !== null && (
          <p className="cart-redeem-applied" role="status" data-wc-no-translate="true">
            Applied discount: { paiseToDisplay( couponApplied ) }
          </p>
        ) }
        { couponMessage && (
          <p className="cart-redeem-msg" role="status">{ couponMessage }</p>
        ) }
      </div>

      {/* GIFT CARD */}
      <div className="cart-redeem-group">
        <label className="cart-redeem-label" htmlFor="cart-giftcard">Gift-card code</label>
        <div className="cart-redeem-row">
          <input
            id="cart-giftcard"
            className="cart-redeem-input"
            type="text"
            autoComplete="off"
            value={ giftCardCode }
            onChange={ e => setGiftCardCode( e.target.value ) }
          />
          <button
            className="cart-redeem-apply"
            type="button"
            disabled={ busy !== null || giftCardCode.trim() === '' }
            onClick={ () => send( 'giftCard', 'apply', giftCardCode.trim() ) }
          >
            { busy === 'giftCard' ? 'Applying…' : 'Apply' }
          </button>
          { giftCardApplied !== null && (
            <button
              className="cart-redeem-remove"
              type="button"
              disabled={ busy !== null }
              onClick={ () => send( 'giftCard', 'remove', '' ) }
            >
              Remove
            </button>
          ) }
        </div>
        { giftCardApplied !== null && (
          <p className="cart-redeem-applied" role="status" data-wc-no-translate="true">
            Applied gift card: { paiseToDisplay( giftCardApplied ) }
          </p>
        ) }
        { giftCardApplied !== null && remainingPayable !== null && (
          <p className="cart-redeem-remaining" role="status" data-wc-no-translate="true">
            Remaining payable balance: { paiseToDisplay( remainingPayable ) }
          </p>
        ) }
        { giftCardMessage && (
          <p className="cart-redeem-msg" role="status">{ giftCardMessage }</p>
        ) }
      </div>

      { unavailable && (
        <p className="cart-redeem-off" role="status" data-phase="unavailable">
          { REDEMPTION_UNAVAILABLE }
        </p>
      ) }

      <style jsx>{`
        .cart-redeem{margin:28px 0 0;padding:20px 0 0;border-block-start:1px solid #e5e7eb}
        .cart-redeem-group{margin:0 0 20px}
        .cart-redeem-group:last-of-type{margin-bottom:0}
        .cart-redeem-label{display:block;font-size:14px;font-weight:700;color:#1a3a2a;margin:0 0 8px}
        .cart-redeem-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
        .cart-redeem-input{
          flex:1 1 220px;min-height:44px;padding:0 12px;border:1px solid #e5e7eb;border-radius:8px;
          font-family:inherit;font-size:16px;color:#1a1a1a;
        }
        .cart-redeem-input:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
        /* The apply control takes the site's lime, like the main CTA but at the secondary rung. */
        .cart-redeem-apply{
          display:inline-flex;align-items:center;justify-content:center;min-height:44px;
          padding:0 20px;border:2px solid #1a3a2a;border-radius:50px;background:#d1f470;
          color:#1a3a2a;font-family:inherit;font-size:16px;font-weight:600;cursor:pointer;
          transition:background-color .2s;
        }
        .cart-redeem-apply:hover:not(:disabled){background:#fff}
        .cart-redeem-apply:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        .cart-redeem-apply:disabled{opacity:.6;cursor:default}
        .cart-redeem-remove{
          display:inline-flex;align-items:center;min-height:44px;padding-inline:8px;border:none;
          background:none;color:#1a3a2a;font-family:inherit;font-size:16px;font-weight:700;
          cursor:pointer;text-decoration:underline;text-underline-offset:3px;
        }
        .cart-redeem-remove:hover{background:rgba(209,244,112,.22);border-radius:8px}
        .cart-redeem-remove:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px;border-radius:2px}
        .cart-redeem-remove:disabled{opacity:.6;cursor:default}
        .cart-redeem-applied,.cart-redeem-remaining{
          margin:10px 0 0;font-size:16px;font-weight:700;color:#1a3a2a;
          font-variant-numeric:tabular-nums;
        }
        .cart-redeem-remaining{color:#1a1a1a}
        .cart-redeem-msg{
          margin:10px 0 0;padding:12px 14px;border-radius:10px;background:rgba(209,244,112,.22);
          border-inline-start:3px solid #d1f470;font-size:16px;line-height:1.5;color:#1a3a2a;
        }
        .cart-redeem-off{
          margin:16px 0 0;padding:12px 14px;border-radius:10px;background:rgba(209,244,112,.22);
          border-inline-start:3px solid #d1f470;font-size:16px;line-height:1.5;color:#1a3a2a;
        }
      `}</style>
    </section>
  );
}

export default function Cart (): React.ReactElement {
  const [ items, setItems ] = useState<CartItem[]>( [] );
  const [ ready, setReady ] = useState<boolean>( false );
  const [ busy, setBusy ] = useState<boolean>( false );
  const [ notice, setNotice ] = useState<Notice>( { kind: 'none' } );
  const [ showProfile, setShowProfile ] = useState<boolean>( false );
  const [ checkoutAccessToken, setCheckoutAccessToken ] = useState<string>( '' );
  const [ profile, setProfile ] = useState<CheckoutProfileValue | null>( null );
  const [ profileStatus, setProfileStatus ] = useState<ProfileStatus>( 'unknown' );
  const [ profileMode, setProfileMode ] = useState<CheckoutProfileMode>( 'create' );
  // A save landed in this page's lifetime, so a readiness refusal from the NEXT `prepare` may be
  // reading the pre-save row off an eventually-consistent GSI rather than reporting a real gap.
  // A ref, not state: the decision is made inside one `proceed` invocation.
  const justSavedRef = useRef<boolean>( false );
  const [ paymentBlocked, setPaymentBlocked ] = useState<boolean>( false );
  /**
   * Whether the "Start a new cart" control is on screen.
   *
   * Set only by the `CART_RESET_REQUIRED` outcome, and cleared on the next `proceed`, so the
   * control never lingers after the condition it answers is gone. It is NOT `paymentBlocked`: a
   * saved cart too large to reconcile is a recoverable state with exactly one action.
   */
  const [ cartResetOffered, setCartResetOffered ] = useState<boolean>( false );
  /**
   * One-shot: the next prepare carries `resetCart: true`, then this is cleared.
   *
   * A ref and not state, for the same reason `justSavedRef` is: the decision is made inside one
   * `proceed` invocation and must not be a render behind.
   *
   * READ AND CLEARED AT THE TOP OF `proceed`, above every early return, so the flag cannot leak
   * into a later click -- abandoning a customer's saved cart twice for one refusal would be a
   * surprise rather than a recovery. Reading it next to the first `postPrepare` instead leaves it
   * armed through a mixed-basket refusal, a sign-in failure or the address editor, and the reset
   * then fires on an unrelated click. Keep the read where it is.
   */
  const resetCartRef = useRef<boolean>( false );
  // The payment rail was entered and returned a RESULT. A ref for the decision, so `proceed` is
  // never a render behind; a state for the render. DEFENCE IN DEPTH, NOT THE GUARANTEE: the latch
  // dies with the page, so a reload or a second tab walks straight past it. The server-side
  // one-live-payment-per-basket guard is the guarantee.
  const railTerminalRef = useRef<boolean>( false );
  const [ railTerminal, setRailTerminal ] = useState<boolean>( false );
  /**
   * A checkout run is in flight, so a second one must not start. SYNCHRONOUS, which is the whole
   * point, and it is ADDITIONAL to every guard already here rather than a replacement for one.
   *
   * THE MEASURED BUG IT FIXES (checkout v11, from API Gateway and Lambda logs): `prepare-checkout`
   * was posted TWICE in rapid succession. The first answered 200 and reserved the cart; the second,
   * one to three seconds later, reached Wix on that already-reserved cart, `wix_ecom` raised, and
   * `handler.py`'s `except wix_ecom.WixEcomError` answered 502 `CATALOGUE_UNAVAILABLE` -- which
   * this page renders as "We could not prepare this order." Every payment attempt failed that way,
   * and the customer's own first attempt was what broke their second.
   *
   * WHY THE EXISTING GUARDS DO NOT COVER IT, each for its own reason:
   *   * `disabled={ busy || ... }` is REACT STATE. `setBusy(true)` does not disable the button
   *     until a render commits, so two clicks (or a double-tap, or a click arriving beside
   *     `CheckoutProfile`'s `onSaved`) both enter `proceed` while the attribute is still false.
   *     State cannot guard re-entry into the function that sets it.
   *   * `railTerminalRef` is synchronous but answers a different question: "the rail already
   *     returned a RESULT". It is set when a payment finishes, not while one is being prepared,
   *     so it is false for the whole window this latch covers.
   *   * The server's one-live-payment guard IS the guarantee, and it still is -- but it sits
   *     BELOW the Wix work in `_v2_snapshot`, so the second request reaches Wix and fails as a
   *     catalogue error before the guard can answer its designed 409. Stopping the second post is
   *     what keeps that 502 unreachable from this page.
   *
   * A ref and not state for the reason `justSavedRef` and `resetCartRef` are: the decision is
   * made inside one invocation and must not be a render behind. Cleared in a `finally`, so a
   * throw anywhere in the run cannot leave the page permanently unable to check out.
   */
  const proceedInFlightRef = useRef<boolean>( false );
  /**
   * The WhatsApp hand-off claim has been attempted in this page's lifetime.
   *
   * A ref and not state because the claim is a SERVER-SIDE SINGLE-USE write: React 19 StrictMode
   * double-invokes effects in development, and a second POST is refused by design, so a state flag
   * (a render behind) would surface "this link is no longer available" for a claim that in fact
   * succeeded a millisecond earlier.
   */
  const basketClaimedRef = useRef<boolean>( false );
  /** The one sentence a non-successful claim leaves on screen, or `null`. */
  const [ basketClaim, setBasketClaim ] = useState<string | null>( null );

  useEffect( () => {
    setItems( readCart() );
    setReady( true );

    // ASK THE READINESS QUESTION ONCE, ON ARRIVAL, so a returning customer is shown what we
    // already know instead of a form they filled in weeks ago. A FAILURE BLOCKS NOTHING AND SAYS
    // NOTHING: the status stays 'unknown' and `proceed` re-derives the truth on the click.
    const session = getSession();
    if ( !session ) return;
    setCheckoutAccessToken( session.accessToken );
    let live = true;
    void ( async () => {
      const reply = await loadProfileStatus( session.accessToken );
      if ( !live || !reply ) return;
      setProfile( profileFrom( reply ) );
      setProfileStatus( deriveStatus( String( reply.status || '' ), Boolean( reply.addressComplete ) ) );
    } )();
    return () => { live = false; };
  }, [] );

  /**
   * THE WHATSAPP BASKET CLAIM. Runs only when `?basket=` is present, and at most once.
   *
   * ONCE IS ENFORCED BY A REF, NOT BY THE DEPENDENCY LIST. The effect has an empty list, but React
   * 19's StrictMode double-invokes effects in development and the claim is a SERVER-SIDE
   * SINGLE-USE write: a second POST is refused by design, so a double invoke would render "this
   * link is no longer available" over a cart that had just been filled correctly. A synchronous
   * ref latch is the only guard that holds, for the same reason `proceedInFlightRef` is one.
   *
   * NO SESSION MEANS SIGN IN FIRST, AND NOTHING IS REIMPLEMENTED HERE. `SIGN_IN_PATH` already
   * carries `?return=/cart/`, and the WhatsApp link's own `?basket=` is preserved by sending the
   * customer to the sign-in page and letting it return them to this URL -- which is why the
   * parameter is read from `window.location` on arrival rather than captured into state earlier.
   *
   * THE PARAMETER IS STRIPPED ON SUCCESS ONLY. On a refusal it is left in place: the sentence
   * explains what happened, and a customer who reloads sees the same honest answer rather than a
   * silently different page. See `stripBasketParam`.
   *
   * IT FETCHES NOTHING WHEN THE PARAMETER IS ABSENT, which is most visits. That keeps the static
   * export's no-fetch-at-render property intact -- `src/test/CartRedemption.test.tsx` asserts it.
   */
  useEffect( () => {
    const token = basketTokenFromUrl();
    if ( !token || basketClaimedRef.current ) return;
    basketClaimedRef.current = true;

    const session = getSession();
    if ( !session )
    {
      // The sign-in flow returns to `/cart/`, and the token is still in the URL when it does.
      window.location.assign( `/account/sign-in/?return=${ encodeURIComponent(
        window.location.pathname + window.location.search ) }` );
      return;
    }

    let live = true;
    void ( async () => {
      const outcome = await claimBasket( session.accessToken, token );
      if ( !live ) return;
      if ( outcome.kind === 'CLAIMED' )
      {
        stripBasketParam();
        setBasketClaim( null );
        return;
      }
      setBasketClaim( claimMessage( outcome ) );
    } )();
    return () => { live = false; };
  }, [] );

  const changeQuantity = useCallback( ( ref: string, quantity: number ): void => {
    setItems( setQuantity( ref, quantity ) );
  }, [] );

  const drop = useCallback( ( ref: string ): void => {
    setItems( removeItem( ref ) );
  }, [] );

  /*
   * `keepOnlyContribution` WAS HERE, and it went with the rule it served.
   *
   * It emptied every non-contribution line in one press, as the offered exit from the
   * mixed-basket refusal. With a mix now payable there is nothing to exit from, and a button that
   * silently discards a customer's products to "fix" a basket that is not broken would be a
   * destructive write nobody asked for. The per-row Remove buttons are unchanged and remain the
   * only way a line leaves the cart.
   */

  const chooseVariant = useCallback( ( ref: string, variantId: string ): void => {
    if ( !variantId ) return;
    setItems( setVariant( ref, variantId ) );
    setPaymentBlocked( false );
    setNotice( { kind: 'quiet', message: 'Product option updated. Continue to secure payment.' } );
  }, [] );

  /**
   * THE PREPARE POST AND ITS WHOLE RESPONSE HANDLING, LIFTED OUT OF `proceed` UNCHANGED.
   *
   * WHY IT IS ITS OWN FUNCTION. The post-save retry needs a SECOND call, and `proceed` cannot
   * call itself: `proceed` is a `useCallback`, so naming it inside its own initialiser is a
   * use-before-define problem, and re-entering it would re-run the auth gate, the
   * `railTerminalRef` short-circuit, the `setNotice({kind:'none'})` reset and the
   * `setBusy`/`finally` pair. This is therefore the ONLY thing the retry re-runs, and `busy`
   * stays true across the wait, so the CTA stays disabled and the copy stays honest throughout.
   *
   * It takes everything it needs as ARGUMENTS and closes over no state, so it adds no dependency
   * to `proceed` and cannot go stale. Nothing about the response handling changed - it moved. The
   * copy for each refusal lives in `applyOutcome`, with the evidence note that justifies it.
   */
  const postPrepare = useCallback( async (
    session: CustomerSession,
    lineItems: ReturnType<typeof toLineItems>,
    // AN ARGUMENT, not a ref read inside the body, for the same reason `lineItems` is one: this
    // callback closes over no state, so what it sends has to be handed to it.
    resetCart = false,
  ): Promise<Outcome> => {
    try
    {
      const response = await fetch( PREPARE_CHECKOUT_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.accessToken}`,
        },
        body: JSON.stringify( {
          action: 'prepare',
          lineItems,
          requestKey: getCheckoutRequestKey( lineItems ),
          // Omitted entirely unless asked for, so an ordinary prepare's body is byte-identical to
          // what it was. The server reads `body.get("resetCart") is True` -- an identity
          // comparison, no coercion -- so an absent key and a false one are the same thing.
          ...( resetCart ? { resetCart: true } : {} ),
          // Phase O-1: only a services basket carries its intent id; every other body is
          // byte-identical to before.
          ...( serviceIntentFor( lineItems ) ? { serviceIntentId: serviceIntentFor( lineItems ) } : {} ),
        } ),
      } );

      if ( response.status === 401 )
      {
        // Session gone or invalid: sign in again.
        return { kind: 'UNAUTHORIZED' };
      }

      const data = ( await response.json().catch( () => ( {} ) ) ) as {
        status?: string;
        error?: string;
        paymentAttemptId?: string;
        message?: string;
        /**
         * The refusal reason on a `CHECKOUT_REJECTED`. Read because exactly one value --
         * `INTENT_CHANGED` -- is recoverable by rotating the request key, and the rest are not.
         */
        reason?: string;
        options?: {
          keyId?: string;
          orderId?: string;
          amountPaise?: number;
          currency?: string;
          prefill?: Record<string, string>;
          paymentAttemptId?: string;
        };
      };
      const status = String( data.status || data.error || '' ).toUpperCase();

      // THE THREE READINESS REFUSALS. The server is the authority on readiness, which is why
      // 'unknown' is allowed to reach this call at all - these arms are what catch it.
      if ( status === 'PROFILE_REQUIRED' ) return { kind: 'PROFILE_REQUIRED' };
      if ( status === 'DELIVERY_DETAILS_REQUIRED' ) return { kind: 'DELIVERY_DETAILS_REQUIRED' };
      if ( status === 'DELIVERY_METHOD_UNAVAILABLE' ) return { kind: 'DELIVERY_METHOD_UNAVAILABLE' };

      if ( status === 'CHECKOUT_OPTIONS_READY' && data.options )
      {
        const options = data.options;
        if (
          !options.keyId || !options.orderId || typeof options.amountPaise !== 'number'
          || !options.currency || !data.paymentAttemptId
        )
        {
          return { kind: 'MALFORMED' };
        }

        const sdkReady = await loadRazorpaySdk();
        if ( !sdkReady || !window.Razorpay )
        {
          return { kind: 'SDK_UNAVAILABLE' };
        }

        const attemptId = String( data.paymentAttemptId );
        const razorpay = new window.Razorpay( {
          key: options.keyId,
          amount: options.amountPaise,
          currency: options.currency,
          order_id: options.orderId,
          /*
           * THE BRAND HALF OF THE MODAL, and it is the ONLY half this block decides. `key`,
           * `amount`, `currency` and `order_id` above all come from the server's prepare
           * response and are untouched - the browser still never names a figure or an order.
           *
           * `theme.color` is `colors.primary` from src/lib/design-tokens.ts (#1a3a2a, the dark
           * forest green that tokens.css publishes as --accent / --color-primary), imported
           * rather than written as a hex so the pay modal cannot drift from the site it opened
           * from. The lime (#d1f470) is deliberately NOT used here: Razorpay tints its primary
           * BUTTON with this value and paints white label text on it, and lime measures about
           * 1.4:1 against white - the same measurement that already disqualified it as a mark in
           * BrandLockup. The green is the colour the rest of the site uses for a primary action.
           */
          name: 'WECARE.DIGITAL',
          description: checkoutDescription( lineItems ),
          image: LOGO_URL,
          theme: { color: colors.primary },
          prefill: options.prefill,
          handler: async ( result: RazorpaySuccess ) => {
            // Latched BEFORE verify runs. This is what makes it hold on a LOST response: the
            // request throwing is exactly the case where money may have moved and there is no
            // body to read. Setting it after the fetch would leave the catch arm with a live CTA.
            railTerminalRef.current = true;
            setRailTerminal( true );
            try {
              const verified = await fetch( VERIFY_CHECKOUT_URL, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${ session.accessToken }`,
                },
                body: JSON.stringify( {
                  action: 'verify',
                  razorpay_payment_id: result.razorpay_payment_id,
                  razorpay_order_id: result.razorpay_order_id,
                  razorpay_signature: result.razorpay_signature,
                } ),
              } );
              const verdict = await verified.json().catch( () => ( {} ) ) as {
                status?: string;
                paymentAttemptId?: string;
              };
              if ( verified.ok && String( verdict.status || '' ).toUpperCase() === 'VERIFIED_PAID' )
              {
                /*
                 * THE FINALIZATION THE DOCBLOCK AT THE TOP OF THIS FILE PROMISES. "Cart/resume
                 * data is kept until a VERIFIED_PAID finalization" was half-implemented: the
                 * keeping worked, the finalization did not exist, so `clearCart` shipped as dead
                 * code and EVERY paid order left its lines in the browser. The next basket then
                 * silently carried the previous purchase - an over-charge risk for a product
                 * basket, and the whole of the contribution dead end, because a leftover product
                 * plus a contribution is the mixed basket the Checkout button refuses.
                 *
                 * `VERIFIED_PAID` IS THE ONLY MOMENT THIS MAY RUN. It is the single point where
                 * the server has confirmed an authoritative capture. Deliberately NOT on
                 * `OPENED`, on dismiss, on `payment.failed`, on the two verify-failure arms
                 * below, or on `CHECKOUT_AMBIGUOUS` - the resume data is exactly what lets an
                 * unresolved attempt be recovered, and emptying the cart on a pending or failed
                 * state destroys it.
                 *
                 * The two reservation slots go with it, so the next basket mints a fresh request
                 * key rather than resuming the one this payment just consumed.
                 *
                 * It cannot race the success screen: /checkout/status/ is a full navigation that
                 * reads the attempt from the server by id and never reads the cart, and the
                 * `assign` below is the last statement on this path.
                 */
                clearCart();
                window.sessionStorage.removeItem( CHECKOUT_REQUEST_KEY );
                window.sessionStorage.removeItem( CHECKOUT_REQUEST_BASKET );
                const paidAttempt = encodeURIComponent( String( verdict.paymentAttemptId || attemptId ) );
                window.location.assign( `/checkout/status/?a=${ paidAttempt }` );
                return;
              }
              setNotice( {
                kind: 'error',
                message: 'Payment returned, but we are still verifying it. Check your orders before retrying.',
              } );
            } catch {
              setNotice( {
                kind: 'error',
                message: 'Payment returned, but we could not confirm it yet. Check your orders before retrying.',
              } );
            }
          },
          modal: {
            ondismiss: () => setNotice( {
              kind: 'quiet',
              message: 'Payment window closed. Your cart is unchanged.',
            } ),
          },
        } );
        razorpay.on( 'payment.failed', () => {
          setNotice( {
            kind: 'error',
            message: 'Payment was not completed. Check your orders before trying again.',
          } );
        } );
        razorpay.open();
        return { kind: 'OPENED' };
      }

      if ( status === 'CHECKOUT_AMBIGUOUS' && data.paymentAttemptId )
      {
        const a = encodeURIComponent( String( data.paymentAttemptId ) );
        window.location.assign( `/checkout/status/?a=${a}` );
        return { kind: 'NAVIGATED' };
      }

      if ( status === 'CHECKOUT_REJECTED' )
      {
        // The reason travels with the refusal now, because exactly ONE of them is recoverable by
        // a retry: `INTENT_CHANGED` means the reservation was taken against a fingerprint that
        // has since moved for a reason the browser cannot observe. `proceed` rotates the key once
        // for that one; every other reason still latches on the first refusal.
        return { kind: 'CHECKOUT_REJECTED', reason: String( data.reason || '' ) };
      }

      // The contribution arms. These codes could not arrive on this route before Phase 2 -- the
      // conditions existed, but `_website_prepare` had no arm for them and they fell through to a
      // generic 503 the browser reads as transient.
      if ( status === 'CONTRIBUTION_AMOUNT_INVALID' ) return { kind: 'CONTRIBUTION_AMOUNT_INVALID' };
      if ( status === 'CONTRIBUTION_NOT_ALONE' ) return { kind: 'CONTRIBUTION_NOT_ALONE' };
      if ( status === 'CONTRIBUTION_UNAVAILABLE' ) return { kind: 'CONTRIBUTION_UNAVAILABLE' };
      if ( status === 'CONTRIBUTION_REDEMPTION_NOT_ALLOWED' )
      {
        return { kind: 'CONTRIBUTION_REDEMPTION_NOT_ALLOWED' };
      }
      if ( status === 'CONTRIBUTION_NOT_PAYABLE' ) return { kind: 'CONTRIBUTION_NOT_PAYABLE' };
      // Phase O-1 service refusals, one sentence each, all before any money moves.
      if ( isServiceRefusal( status ) )
      {
        return { kind: 'SERVICE_REFUSED', message: SERVICE_REFUSAL_MESSAGES[ status ] };
      }
      // The Cart V2 arms, in the vocabulary `_create` already speaks.
      if ( status === 'CART_RESET_REQUIRED' ) return { kind: 'CART_RESET_REQUIRED' };
      if ( status === 'CART_NOT_PAYABLE' ) return { kind: 'CART_NOT_PAYABLE' };
      if ( status === 'CART_RECONCILIATION_REQUIRED' )
      {
        return { kind: 'CART_RECONCILIATION_REQUIRED' };
      }
      if ( status === 'ITEMS_UNAVAILABLE' ) return { kind: 'ITEMS_UNAVAILABLE' };
      if ( status === 'QUANTITY_REDUCED' ) return { kind: 'QUANTITY_REDUCED' };

      // PAYMENT_REQUEST_SENT hands off to the hosted status screen, which owns the honest copy for
      // an attempt that is genuinely in flight. NO claim about a charge is made here in either
      // direction: the request has left and only the server knows where it stands.
      if ( status === 'PAYMENT_REQUEST_SENT' && data.paymentAttemptId )
      {
        // Keep the cart until the server confirms a paid order.
        const a = encodeURIComponent( String( data.paymentAttemptId ) );
        window.location.assign( `/checkout/status/?a=${a}` );
        return { kind: 'NAVIGATED' };
      }

      if ( status === 'PAYMENT_INITIATION_DISABLED' ) return { kind: 'PAYMENT_INITIATION_DISABLED' };

      // 409 readiness-blocked.
      if ( status === 'PAYMENT_UNAVAILABLE' ) return { kind: 'PAYMENT_UNAVAILABLE' };

      // Empty cart per the server.
      if ( status === 'LINE_ITEMS_REQUIRED' ) return { kind: 'LINE_ITEMS_REQUIRED' };

      // The message did not go out. The attempt exists and nothing was charged.
      if ( status === 'SEND_FAILED' ) return { kind: 'SEND_FAILED' };

      // A cart item is no longer available in the store (retired/out-of-stock product or variant).
      // Permanent and caller-fixable: tell the customer to remove it, do not imply a system failure.
      if ( status === 'CART_ITEM_UNAVAILABLE' )
      {
        return { kind: 'ITEM_UNAVAILABLE' };
      }

      // Priced/currency/catalogue problems. The request was refused, so nothing was charged.
      if (
        status === 'UNSUPPORTED_CURRENCY' || status === 'AMOUNT_NOT_SETTLED'
        || status === 'CATALOGUE_UNAVAILABLE'
      )
      {
        return { kind: 'PRICING_UNAVAILABLE' };
      }

      // Anything unrecognised: fail honestly rather than implying success.
      return { kind: 'UNRECOGNISED' };
    }
    catch
    {
      // A lost response cannot prove that the request never reached the server.
      return { kind: 'LOST' };
    }
  }, [] );

  /**
   * ACT ON ONE `prepare` OUTCOME, EXACTLY ONCE.
   *
   * Named `applyOutcome` and not `act`, because `act` is testing-library's.
   *
   * Every sentence below is the one the evidence supports, and nothing else: "no charge was made"
   * appears only on an outcome that means the request never reached the payment rail. Like
   * `postPrepare`, it takes what it needs as arguments and closes over no state.
   */
  const applyOutcome = useCallback( ( outcome: Outcome, session: CustomerSession ): void => {
    // The rail was entered, or the browser was handed off. The server has now priced the cart
    // against the saved row, so a later refusal is a real refusal rather than a stale read.
    if ( outcome.kind === 'OPENED' || outcome.kind === 'NAVIGATED' )
    {
      justSavedRef.current = false;
      return;
    }

    if ( outcome.kind === 'UNAUTHORIZED' )
    {
      window.location.assign( SIGN_IN_PATH );
      return;
    }

    if ( outcome.kind === 'PROFILE_REQUIRED' )
    {
      setCheckoutAccessToken( session.accessToken );
      setProfile( null );
      setProfileMode( 'create' );
      setProfileStatus( 'required' );
      setShowProfile( true );
      setNotice( { kind: 'quiet', message: 'Verify and save your checkout details again.' } );
      return;
    }

    // The server has the profile and refuses the ADDRESS, so the address form is the thing to
    // open - not the whole creation flow the customer already completed.
    if ( outcome.kind === 'DELIVERY_DETAILS_REQUIRED' )
    {
      setProfileMode( 'address' );
      setProfileStatus( 'required' );
      setShowProfile( true );
      setNotice( { kind: 'quiet', message: 'Confirm your delivery address to continue.' } );
      return;
    }

    // NOT THE CUSTOMER'S MISTAKE, so no editor opens. The address is known-good; the store has no
    // delivery method that serves it, which needs a shipping rule on our side. The cart survives,
    // the same way PAYMENT_INITIATION_DISABLED leaves it alone.
    if ( outcome.kind === 'DELIVERY_METHOD_UNAVAILABLE' )
    {
      setPaymentBlocked( true );
      setNotice( {
        kind: 'quiet',
        message: 'We could not get a delivery option for this address. Nothing was charged.',
      } );
      return;
    }

    if ( outcome.kind === 'CHECKOUT_REJECTED' )
    {
      setPaymentBlocked( true );
      setNotice( { kind: 'error', message: NOT_PREPARED } );
      return;
    }

    // ── the contribution refusals ──────────────────────────────────────────────
    // None of these latches `paymentBlocked`: every one is either an amount the customer can
    // change, a basket they can fix, or a configuration state that has nothing to do with them.
    if ( outcome.kind === 'CONTRIBUTION_AMOUNT_INVALID' )
    {
      setNotice( { kind: 'quiet', message: CONTRIBUTION_HELP } );
      return;
    }
    if ( outcome.kind === 'CONTRIBUTION_NOT_ALONE' )
    {
      // NOW THE ONLY PLACE THIS SENTENCE APPEARS. There is no browser-side mixed-basket refusal
      // to agree with any more -- the server narrowed this code to two contribution lines, which
      // only a crafted request builds -- so this arm is both the sole call site and the sole way
      // the customer ever sees it. Still word for word the server's own message.
      setNotice( { kind: 'quiet', message: CONTRIBUTION_ALONE_MESSAGE } );
      return;
    }
    if ( outcome.kind === 'CONTRIBUTION_UNAVAILABLE' )
    {
      setNotice( { kind: 'quiet', message: CONTRIBUTION_UNAVAILABLE_MESSAGE } );
      return;
    }
    if ( outcome.kind === 'CONTRIBUTION_REDEMPTION_NOT_ALLOWED' )
    {
      // Copy that NAMES the action, because this one is recoverable -- unlike the
      // misconfiguration refusal, which looks the same to the server and is not.
      setNotice( {
        kind: 'quiet',
        message: 'A contribution takes no coupon or gift card. Remove it to continue.',
      } );
      return;
    }
    if ( outcome.kind === 'CONTRIBUTION_NOT_PAYABLE' )
    {
      // `error` rather than `quiet`: unlike the four above, this one is not something the
      // customer did and not something they can undo, so it is the page's own failure to report
      // rather than a gentle correction. It still does not latch `paymentBlocked` -- no payment
      // was attempted, and a dashboard setting can be fixed between two presses.
      setNotice( { kind: 'error', message: CONTRIBUTION_NOT_PAYABLE_MESSAGE } );
      return;
    }

    // Phase O-1: shown as an error and deliberately NOT latched -- nothing was charged, and the
    // customer (or a dashboard fix) can clear every one of these between two presses.
    if ( outcome.kind === 'SERVICE_REFUSED' )
    {
      setNotice( { kind: 'error', message: outcome.message } );
      return;
    }

    // ── the Cart V2 refusals ───────────────────────────────────────────────────
    if ( outcome.kind === 'CART_RESET_REQUIRED' )
    {
      // The ONE outcome arm that carries an action rather than only words. The excess lines are on
      // the SERVER cart, which nothing on this page can touch, so "review your cart" would name
      // an action the customer cannot perform. `resetCart` abandons the server pointer only; the
      // browser cart is untouched and the next prepare rebuilds the Wix cart from it.
      setCartResetOffered( true );
      setNotice( {
        kind: 'quiet',
        message: 'Your saved cart has too many items to update. Start a new cart.',
      } );
      return;
    }
    if ( outcome.kind === 'CART_NOT_PAYABLE' )
    {
      setNotice( { kind: 'error', message: 'Please review your cart and try again.' } );
      return;
    }
    if ( outcome.kind === 'CART_RECONCILIATION_REQUIRED' )
    {
      setNotice( { kind: 'quiet', message: 'Your cart is being updated. Please try again shortly.' } );
      return;
    }
    if ( outcome.kind === 'ITEMS_UNAVAILABLE' )
    {
      setNotice( {
        kind: 'error',
        message: 'Some items are no longer available. Please review your cart.',
      } );
      return;
    }
    if ( outcome.kind === 'QUANTITY_REDUCED' )
    {
      setNotice( {
        kind: 'error',
        message: 'Some items are available in smaller quantities than you asked for. '
          + 'Please confirm the new amounts.',
      } );
      return;
    }

    // PAYMENT_INITIATION_DISABLED IS ANSWERED HERE, NOT ON THE STATUS SCREEN, and both halves of
    // that are deliberate.
    //
    // WHY IT STAYS ON THIS PAGE. This status means the server's own initiation gate is off, so it
    // stopped before the payment rail: there is backend evidence that nothing reached a provider,
    // which is exactly the condition the approved sentence requires. The status screen cannot
    // carry that sentence, because its viewFor() folds this status in with "we cannot find this
    // attempt" and anything unrecognised - states where the money may in fact have moved - and a
    // claim of no charge is the one wrong answer that cannot be taken back. Keeping the sentence
    // on the page that received the response keeps it pinned to the evidence for it.
    //
    // WHY THE CART SURVIVES. It used to be cleared here, alongside the in-flight case. That was
    // wrong twice over: a disabled gate leaves the shopper nothing to come back to, and the
    // notice below renders inside the items list, so clearing the cart would have replaced the
    // explanation with "Your cart is empty." The attempt the server recorded is not payable, so
    // the cart is still the shopper's.
    if ( outcome.kind === 'PAYMENT_INITIATION_DISABLED' )
    {
      setPaymentBlocked( true );
      setNotice( { kind: 'quiet', message: NOT_PREPARED } );
      return;
    }

    // 409 readiness-blocked. The server refused before reaching the payment rail, so the same
    // evidence holds and the same sentence is the honest one.
    if ( outcome.kind === 'PAYMENT_UNAVAILABLE' )
    {
      setPaymentBlocked( true );
      setNotice( { kind: 'quiet', message: NOT_PREPARED } );
      return;
    }

    // Empty cart per the server: reflect the empty state.
    if ( outcome.kind === 'LINE_ITEMS_REQUIRED' )
    {
      setItems( readCart() );
      return;
    }

    // The message did not go out. The attempt exists and nothing was charged, so a retry is safe.
    if ( outcome.kind === 'SEND_FAILED' )
    {
      setPaymentBlocked( true );
      setNotice( {
        kind: 'quiet',
        message: 'We could not open the payment. No charge was made - please try again.',
      } );
      return;
    }

    if ( outcome.kind === 'PRICING_UNAVAILABLE' )
    {
      setPaymentBlocked( true );
      setNotice( { kind: 'error', message: NOT_PREPARED } );
      return;
    }

    if ( outcome.kind === 'ITEM_UNAVAILABLE' )
    {
      setPaymentBlocked( true );
      setNotice( {
        kind: 'error',
        message: 'An item in your cart is no longer available. Remove it and try again.',
      } );
      return;
    }

    if ( outcome.kind === 'SDK_UNAVAILABLE' )
    {
      setNotice( { kind: 'error', message: 'Secure payment could not open. Your cart is unchanged.' } );
      return;
    }

    // MALFORMED, LOST and UNRECOGNISED. Safe to claim nothing: a lost response cannot prove the
    // request never reached the server, and the others carried no live attempt to be wrong about.
    setNotice( { kind: 'error', message: 'We could not confirm checkout. Check your orders before trying again.' } );
  }, [] );

  const runCheckout = useCallback( async (): Promise<void> => {
    // AHEAD of the notice reset, deliberately: a re-entry -- from CheckoutProfile's onSaved, or
    // a stray click -- must neither re-enter the rail nor wipe the explanation already on screen.
    if ( railTerminalRef.current ) return;
    // THE IN-FLIGHT LATCH IS NOT HERE. It is `proceedInFlightRef`, in `proceed`, which is the only
    // caller of this function -- see that docstring for the measured double-fire it fixes and for
    // why it is a wrapper rather than a check bolted in at this line. An inline latch was tried
    // and removed: it sat ABOVE the one-shot consume below and did not disarm it, so a call it
    // turned away left `resetCart` armed for the next click, which is the exact leak the consume's
    // placement exists to prevent. The wrapper disarms the one-shot on the path it refuses.
    setNotice( { kind: 'none' } );
    setCartResetOffered( false );

    // THE ONE-SHOT IS CONSUMED ON ENTRY, beside the control it answers, and the placement is the
    // whole guarantee rather than a tidy-up.
    //
    // It used to be read immediately before the first `postPrepare`, with SIX `return`s above that
    // point -- the mixed-basket refusal, a `restoreSession()` throw, an empty basket, and the
    // `status === 'required'` arm that opens the address editor and returns WITHOUT navigating
    // away. Arm the flag with "Start a new cart", hit any of them, and the flag survived: the next
    // Checkout click posted `resetCart: true` and the server abandoned a saved cart nobody asked
    // to discard. `setCartResetOffered(false)` is on the line above, so the control vanished while
    // the flag it armed stayed armed -- the docstring on `resetCartRef` promised exactly the
    // property the old position did not hold.
    //
    // Consuming it here makes the one-shot independent of WHICH branch returns. The cost of
    // consuming it on a branch that never posts is that the customer clicks "Start a new cart"
    // again after fixing the basket, which is the recoverable direction: the control is re-offered
    // by the next `CART_RESET_REQUIRED`, and the alternative is a silent destructive write.
    //
    // The `railTerminalRef` return above is deliberately NOT covered, and cannot leak: nothing
    // clears that ref, so once it is set every later `proceed` returns on that same line and no
    // `postPrepare` can ever carry the flag again.
    const resetCart = resetCartRef.current;
    resetCartRef.current = false;

    // THE MIXED-BASKET REFUSAL THAT USED TO SIT HERE IS GONE, and nothing replaced it.
    //
    // Owner decision, 2026-10-06: a product and a contribution are paid together. There is no
    // longer a local fact to refuse on, so the basket goes to the server and is priced like any
    // other order. The server's `_contribution_request` returns `None` for a mix, which puts it
    // on the ordinary path -- fee-bearing quote, ordinary delivery handling -- rather than on the
    // fee-exempt contribution path.
    //
    // ONE-SHOT NOTE, since the consume above was positioned partly because of this return: the
    // early returns it defends against are still there (`restoreSession()` throwing, an empty
    // basket, an unresolved variant, the `status === 'required'` address arm), so its placement
    // is unchanged and still load-bearing.

    // AUTH GATE. No session -> sign-in first, cart preserved in localStorage. No create call.
    let session;
    try { session = getSession() || await restoreSession(); }
    catch {
      setNotice( { kind: 'quiet', message: 'Sign-in is temporarily unavailable. Please try again.' } );
      return;
    }
    if ( !session )
    {
      window.location.assign( SIGN_IN_PATH );
      return;
    }

    // THE TOKEN HOIST, and it is load-bearing rather than tidy. The editor is gated on
    // `showProfile && checkoutAccessToken` and the token starts ''. Any arm below that opens the
    // editor without passing through here would leave a customer reading "Add your delivery
    // address to continue" above NO FORM - the same dead-end class this phase exists to remove.
    setCheckoutAccessToken( session.accessToken );

    // ASK THE READINESS QUESTION FIRST, AND BRANCH ON THE LOCAL, NOT ON THE STATE.
    //
    // `profileStatus` is a `useState` value captured in this `useCallback`'s closure, so
    // `setProfileStatus(...)` does NOT change it for the remainder of this invocation. Branching
    // on the state after setting it means the 'ready' arm is never taken on a first click and the
    // whole first-click path falls through every branch. `deriveStatus` is pure precisely so this
    // can branch on its RETURNED value; `setProfileStatus` is still called, as a cache for the
    // next render and the next click.
    let status = profileStatus;
    let mode: CheckoutProfileMode = profile?.email ? 'address' : 'create';
    if ( status === 'unknown' || status === 'checking' )
    {
      setProfileStatus( 'checking' );
      const reply = await loadProfileStatus( session.accessToken );
      status = reply ? deriveStatus( String( reply.status || '' ), Boolean( reply.addressComplete ) ) : 'unknown';
      if ( reply )
      {
        setProfile( profileFrom( reply ) );
        // The REPLY decides the mode, not a guess: PROFILE_READY with no usable address needs the
        // address form, PROFILE_REQUIRED needs the whole creation flow.
        mode = String( reply.status || '' ) === 'PROFILE_READY' ? 'address' : 'create';
      }
      setProfileStatus( status );
    }

    // THE DELIVERY GATE IS NOW CONDITIONAL ON THE BASKET, and on `mode` rather than on `profile`.
    //
    // `deriveStatus('PROFILE_READY', addressComplete=false)` returns 'required', which opens the
    // address editor -- so a contribution-only cart would never reach the server's delivery skip.
    // A missing ADDRESS blocks only a basket that needs delivery; a missing IDENTITY blocks every
    // basket, and `mode === 'create'` is exactly "there is no identity yet".
    //
    // `mode`, NOT `profile?.email`: `profile` is a `useState` value captured in this closure and
    // `setProfile(...)` does not change it for the remainder of this invocation, and `profileFrom`
    // returns null for anything that is not PROFILE_READY. On a FIRST click `status` starts
    // 'unknown' and `profile` is still undefined, so `!profile?.email` would be true and a
    // contribution-only cart belonging to a fully provisioned customer would open the address
    // editor anyway -- failing on the first click and working on the second. `mode` carries no
    // stale read: it is reassigned from the reply inside the branch above.
    //
    // The server remains the authority. If this guesses wrong and lets a physical basket through,
    // `prepare` answers 409 DELIVERY_DETAILS_REQUIRED and the arm below opens the editor.
    const needsDelivery = cartRequiresDelivery();
    if ( status === 'required' && ( needsDelivery || mode === 'create' ) )
    {
      setProfileMode( mode );
      setShowProfile( true );
      setNotice( { kind: 'quiet', message: mode === 'address'
        ? 'Add your delivery address to continue.'
        : 'Confirm your name and verify your email before secure payment.' } );
      return;
    }

    // 'ready' AND 'unknown' BOTH FALL THROUGH, and the 'unknown' half is the single most
    // consequential line on this page. `deriveStatus` returns 'unknown' for a 500, a network
    // failure, a parse failure or a status string this build does not recognise, and
    // `loadProfileStatus` returns null rather than throwing. The server's 409 arms are the
    // authority on readiness, so a transient DynamoDB blip costs ONE wasted `prepare` call and
    // the customer still pays. Opening the editor or stopping with a notice here would hand a
    // blip the power to block a payable customer.

    setPaymentBlocked( false );
    const currentItems = readCart();
    const unresolved = currentItems.find( needsVariantSelection );
    if ( unresolved )
    {
      setItems( currentItems );
      setPaymentBlocked( true );
      setNotice( {
        kind: 'quiet',
        message: 'Choose a current product option below before secure payment.',
      } );
      return;
    }
    const lineItems = toLineItems( currentItems );
    if ( lineItems.length === 0 )
    {
      setItems( readCart() );
      return;
    }

    setBusy( true );
    try
    {
      // MUST STAY A `let`: the rotation below reassigns it, so "tidying" this into a `const`
      // breaks that block rather than the line it is on.
      //
      // ONLY THE FIRST POST OF THIS INVOCATION CARRIES `resetCart` -- it was read and cleared at
      // the top of `proceed`, and the retry and the rotation below deliberately omit it: both are
      // re-posts of a request whose cart was already abandoned, and abandoning it a second time
      // would mint a third cart.
      let outcome = await postPrepare( session, lineItems, resetCart );

      // ONE BOUNDED RETRY AFTER A SAVE. `phone-index` is a GLOBAL secondary index and cannot be
      // read strongly consistent, so a `prepare` issued seconds after a save can legitimately see
      // the pre-save row and refuse an address that is already stored. The ref is cleared BEFORE
      // the retry so this cannot loop, and only the SECOND refusal reaches the editor-opening
      // arms. `busy` stays true across the wait, so the CTA stays disabled throughout.
      if (
        ( outcome.kind === 'DELIVERY_DETAILS_REQUIRED' || outcome.kind === 'PROFILE_REQUIRED' )
        && justSavedRef.current
      )
      {
        justSavedRef.current = false;
        await sleep( POST_SAVE_RETRY_MS );
        outcome = await postPrepare( session, lineItems );
      }

      // ONE ROTATION ON `INTENT_CHANGED`, and this is the ONE `CHECKOUT_REJECTED` reason a
      // rotation can clear.
      //
      // The reservation was taken against a fingerprint that has since moved for a reason the
      // browser cannot observe: `intent_fingerprint` keeps `cart_revision` AND `snapshot_hash`,
      // and `checkout_pricing.basket_hash`'s own docstring records as MEASURED that the website
      // prepare path writes to the Wix cart on every call -- so a second prepare of an UNEDITED
      // basket can present a different `snapshot_hash`. Every reason the browser CAN predict is
      // already handled by the basket-scoped key, so this is off the common path.
      //
      // It lives HERE and not in `applyOutcome`, and that placement is forced rather than
      // preferred: a re-post must be awaited, `applyOutcome` is `useCallback(..., [])` returning
      // void, and calling it from inside its own initialiser is a use-before-define. `proceed` is
      // async, already holds `lineItems`, and already has exactly this shape in the retry above.
      //
      // THE BOUND IS THE ABSENCE OF A LOOP, and nothing else. This block is straight-line code
      // reached once per `proceed`, so one rotation per click is structural. It previously also
      // carried a `rotated` local guarding its own condition; that flag was dead -- `!rotated` was
      // unconditionally true at its single evaluation and the assignment was never read -- so it
      // was removed rather than left reading as a guarantee it did not provide. Do NOT wrap this in
      // a loop: the bound would go with it.
      //
      // One rotation is also provably SUFFICIENT: the second post cannot answer `INTENT_CHANGED` at
      // all, because both slots were just removed, so `getCheckoutRequestKey` mints a key no
      // reservation holds and the server's reservation WINS rather than losing.
      //
      // It cannot mint a second gateway order: the one-live-payment guard is keyed on the CART,
      // not on the request key, and it runs before the reservation is attempted. The re-post
      // either prepares cleanly or is refused as `CHECKOUT_AMBIGUOUS`, which this page already
      // handles by navigating to /checkout/status/.
      //
      // A non-`INTENT_CHANGED` `CHECKOUT_REJECTED` still latches on the FIRST refusal, unchanged.
      if ( outcome.kind === 'CHECKOUT_REJECTED' && outcome.reason === 'INTENT_CHANGED' )
      {
        if ( typeof window !== 'undefined' )
        {
          window.sessionStorage.removeItem( CHECKOUT_REQUEST_KEY );
          window.sessionStorage.removeItem( CHECKOUT_REQUEST_BASKET );
        }
        outcome = await postPrepare( session, lineItems );
      }

      applyOutcome( outcome, session );
    }
    finally
    {
      setBusy( false );
    }
    // `postPrepare` and `applyOutcome` are `useCallback(..., [])`, so they are referentially
    // stable for the life of this component and cannot go stale. The only live dependencies are
    // the two pieces of state read above.
  }, [ profile, profileStatus ] );

  /**
   * THE ONLY WAY INTO A CHECKOUT RUN, and it is a latch and nothing else.
   *
   * A thin wrapper rather than a check bolted inside `runCheckout`, for two reasons that are both
   * about the guarantee rather than about style:
   *
   *   1. `runCheckout` has fourteen `return` statements. A `finally` has to wrap the WHOLE body
   *      to clear the latch on every one of them, and wrapping a 200-line body in a `try` makes
   *      the diff the body rather than the fix -- so the next reader cannot see what changed.
   *   2. A latch that lives outside the function it guards cannot be defeated by an early return
   *      added later. There is no path into the run that skips it, because there is no other
   *      caller: `onClick` and `startNewCart` both call THIS.
   *
   * CHECK-AND-SET, SYNCHRONOUSLY, BEFORE THE FIRST `await`. JavaScript is single-threaded, so
   * nothing can interleave between the read and the write; that is what makes a ref sufficient
   * here where React state is not.
   *
   * THE RESET ONE-SHOT IS DISARMED ON A REFUSED ENTRY, which is not optional. `startNewCart` arms
   * `resetCartRef` and then calls this; if the latch turns that call away, a flag the customer
   * armed would survive into their NEXT click and abandon a saved cart on an ordinary Checkout
   * press. `resetCartRef`'s own docstring calls that out as the failure to avoid. The cost is one
   * more click on "Start a new cart" after the in-flight run finishes -- and the control is
   * re-offered by the next `CART_RESET_REQUIRED`, so the recoverable direction is the one taken.
   *
   * No notice is set on a refused entry, deliberately. The run in flight is already showing
   * "Preparing…" on the CTA, and "please wait" on top of that explains nothing the customer cannot
   * already see.
   */
  const proceed = useCallback( async (): Promise<void> => {
    if ( proceedInFlightRef.current )
    {
      resetCartRef.current = false;
      return;
    }
    proceedInFlightRef.current = true;
    try
    {
      await runCheckout();
    }
    finally
    {
      proceedInFlightRef.current = false;
    }
  }, [ runCheckout ] );

  /**
   * Re-post the SAME prepare with `resetCart: true`, the answer to `CART_RESET_REQUIRED`.
   *
   * It goes through `proceed` rather than calling `postPrepare` directly, so the auth gate, the
   * readiness question, the retry and every outcome arm still apply -- a reset is an ordinary
   * checkout with one extra boolean, not a second path. `proceed` consumes the flag ON ENTRY, so
   * if this click is refused before it ever posts -- a mixed basket, a sign-in failure, the
   * address editor -- the flag dies with that invocation rather than silently abandoning a cart on
   * a later click. The customer clicks this again once the refusal is cleared, and the control is
   * re-offered by the next `CART_RESET_REQUIRED`.
   */
  const startNewCart = useCallback( (): void => {
    resetCartRef.current = true;
    setCartResetOffered( false );
    void proceed();
  }, [ proceed ] );

  const isEmpty = ready && items.length === 0;

  return (
    <>
      <Head>
        <title>Your cart — WECARE.DIGITAL</title>
        {/* Customer-session, per-person: never indexed. */}
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <PageTopBand
        heading="Your cart"
        sub="Review what you have added before you check out."
        ariaLabel="Your cart"
      >
        <div className="cart-in">
          {!ready && <p className="cart-body">Loading your cart…</p>}

          {isEmpty && (
            <div className="cart-empty">
              <p className="cart-body">Your cart is empty.</p>
              <p className="cart-back"><Link href="/shop/">Browse the shop</Link></p>
            </div>
          )}

          {ready && items.length > 0 && (
            <>
              <ul className="cart-list">
                { items.map( item => (
                  <li className="cart-row" key={ item.ref }>
                    <div className="cart-row-main">
                      <p className="cart-name">
                        { item.slug
                          ? <Link href={ `/shop/${item.slug}/` }>{ item.name }</Link>
                          : item.name }
                      </p>
                      {/* DISPLAY ONLY. This Wix passthrough price never reaches the server. */}
                      <p className="cart-price" data-wc-no-translate="true">{ item.formattedPrice }</p>
                      { needsVariantSelection( item ) && (
                        <label className="cart-option-label">
                          <span>Choose option</span>
                          <select
                            className="cart-option"
                            aria-label={ `Choose option for ${item.name}` }
                            value=""
                            onChange={ e => chooseVariant( item.ref, e.target.value ) }
                          >
                            <option value="" disabled>Select fit / size</option>
                            { availableVariantsForItem( item ).map( variant => (
                              <option key={ variant.id } value={ variant.id }>{ variant.label }</option>
                            ) ) }
                          </select>
                        </label>
                      ) }
                    </div>
                    <div className="cart-row-controls">
                      { isContributionItem( item )
                        ? <ContributionAmount item={ item } onCommitted={ () => setItems( readCart() ) } />
                        : (
                          <>
                            <label className="cart-qty-label" htmlFor={ `qty-${item.ref}` }>Qty</label>
                            <input
                              id={ `qty-${item.ref}` }
                              className="cart-qty"
                              type="number"
                              min={ 1 }
                              value={ item.quantity }
                              onChange={ e => changeQuantity( item.ref, Number( e.target.value ) ) }
                            />
                          </>
                        ) }
                      <button
                        className="cart-remove"
                        type="button"
                        onClick={ () => drop( item.ref ) }
                        aria-label={ `Remove ${item.name}` }
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ) ) }
              </ul>

              {/* Coupon + gift card. Every amount shown is server-authoritative; with the backend
                  gate off this shows an honest unavailable state and cannot transact.

                  NOT RENDERED ON A CART CONTAINING A CONTRIBUTION. A contribution takes neither:
                  a coupon would make the recorded amount differ from the amount contributed, and a
                  gift card is store credit -- spending store credit is not a contribution. Removing
                  the entry point is the cheap half; the server refusal is the authoritative half,
                  since this panel is not the only way a coupon could ever land on a Wix cart. A
                  render-time read of `items` is correct here. */}
              { !items.some( isContributionItem ) && <RedemptionPanel /> }

              {/* THE RETURNING CUSTOMER SEES WHAT WE ALREADY KNOW, not a form. Rendered only on
                  'ready', which means profile complete AND an address on file, so the Deliver row
                  can never be empty. The card STAYS while an editor is open beneath it - with its
                  three buttons disabled - so the customer can see what they are changing from. */}
              { profileStatus === 'ready' && profile && (
                <CheckoutIdentityCard
                  identity={ profile }
                  editorOpen={ showProfile }
                  onEditName={ () => { setProfileMode( 'name' ); setShowProfile( true ); } }
                  onChangeEmail={ () => { setProfileMode( 'email' ); setShowProfile( true ); } }
                  onEditAddress={ () => { setProfileMode( 'address' ); setShowProfile( true ); } }
                />
              ) }

              { showProfile && checkoutAccessToken && (
                <CheckoutProfile
                  /* `initial` is read ONCE at mount, so the editor is keyed on the mode: an
                     affordance that changes the mode gets a FRESH editor prefilled from the
                     current profile rather than a stale one that ignored the new prop. */
                  key={ profileMode }
                  accessToken={ checkoutAccessToken }
                  mode={ profileMode }
                  initial={ {
                    firstName: profile?.firstName || '',
                    lastName: profile?.lastName || '',
                    email: profile?.email || '',
                    address: profile?.address || null,
                  } }
                  onReady={ next => {
                    // THE STATUS DECIDES THE EDITOR, NOT THE SAVE EVENT. A save that lands
                    // without a usable address must leave the address form MOUNTED: closing it
                    // and then asking for an address is a dead end, and it is reachable - a
                    // stored address that stopped mapping, or a backend that wrote one it cannot
                    // re-validate.
                    const nextStatus = deriveStatus( 'PROFILE_READY', next.addressComplete );
                    setProfile( next );
                    justSavedRef.current = true;
                    setProfileStatus( nextStatus );
                    if ( nextStatus === 'ready' )
                    {
                      setShowProfile( false );
                      setNotice( {
                        kind: 'quiet',
                        message: 'Checkout details saved. Continue to secure payment.',
                      } );
                    }
                    else
                    {
                      setProfileMode( 'address' );
                      setShowProfile( true );
                      setNotice( {
                        kind: 'quiet',
                        message: 'Add your delivery address to continue.',
                      } );
                    }
                  } }
                />
              ) }

              {/* Catalogue prices are for display; the server approves the payable total. */}
              <p className="cart-note">
                The store confirms your final total, including taxes and fees, before payment.
              </p>

              {/* THE WHATSAPP CLAIM, when it did not simply work. One line, no amount, no retry
                  button: every outcome's own sentence already names the action that helps, and a
                  button here would re-post a single-use claim. A success says nothing at all -
                  the items appearing in the list is the message. */}
              { basketClaim && (
                <p className="cart-status" role="status" data-wc-basket-claim="true">
                  { basketClaim }
                </p>
              ) }

              {/* role is chosen by severity, not by colour: 'status' is polite for a state the
                  shopper can simply retry, 'alert' interrupts for one they cannot. Neither relies
                  on the tint to carry the meaning - the sentence does. */}
              {notice.kind === 'quiet' && (
                <p className="cart-status" role="status">{ notice.message }</p>
              )}
              {notice.kind === 'error' && (
                <p className="cart-status cart-status-firm" role="alert">{ notice.message }</p>
              )}

              {/* THE MIXED-BASKET NOTICE AND ITS "Keep only the contribution" BUTTON WERE HERE.
                  Both are gone with the rule: a product and a contribution check out together as
                  of 2026-10-06, so there is no basket state to explain at render time and no
                  reason to dim the CTA for one. `CONTRIBUTION_ALONE_MESSAGE` survives for the one
                  refusal that is left -- two contribution lines, which only a crafted request can
                  build -- and is shown by `applyOutcome` when the server answers it, which is a
                  press away rather than at render, because nothing local can predict it. */}

              {/* THE ONE REFUSAL THAT CARRIES AN ACTION. The excess lines are on the SERVER cart,
                  which nothing on this page can touch, so words alone would name an action the
                  customer cannot perform. This re-posts the SAME prepare with `resetCart: true`
                  and the SAME lineItems; the browser cart is not touched, and the next prepare
                  rebuilds the Wix cart from it. */}
              { cartResetOffered && !railTerminal && (
                <p className="cart-back">
                  <button className="cart-remove" type="button" disabled={ busy }
                          onClick={ startNewCart }>
                    Start a new cart
                  </button>
                </p>
              ) }

              {/* THE SAME TWO-SEGMENT PILL as the sign-in CTA (PillButton), because this button is
                  the customer login gate: an anonymous shopper who clicks it is sent to
                  /account/sign-in. Never a "pay now" claim. The visible pill reads
                  "Checkout | Proceed" and its accessible name is now that same visible text,
                  "Checkout Proceed".

                  IT USED TO PASS ariaLabel="Proceed to checkout", which read better but was a
                  WCAG 2.5.3 Label in Name failure: the name did not contain the visible text, so
                  a speech-input user saying "click Checkout" or "click Proceed" hit nothing. The
                  prop no longer exists - see PillButton's docblock. Visible text is unchanged;
                  only the accessible name moved. Real type="button" running proceed(), disabled
                  while busy. */}
              <div className="cart-pill">
                { railTerminal
                  /* A way off a finished page. A LINK, never a button, with words that cannot
                     read as "pay again". */
                  ? <p className="cart-back"><Link href="/orders/">Check your orders</Link></p>
                  : <PillButton
                      as="button"
                      type="button"
                      label={ profile && !paymentBlocked ? 'Secure checkout' : 'Checkout' }
                      action={ busy
                        ? 'Preparing…'
                        : ( profile ? ( paymentBlocked ? 'Try again' : 'Pay securely' ) : 'Proceed' ) }
                      onClick={ proceed }
                      /* `railTerminal` is kept here even though the branch above makes it
                         unreachable: belt-and-braces ACROSS THE RENDER BOUNDARY. The two
                         mechanisms fail independently, and if a later edit reinstates the button
                         on the latched branch -- the obvious way to "improve" this -- the
                         disabled term is what keeps it dead. `busy` is left alone: the spinner
                         means "a request is in flight", and a latched page is not busy, it is
                         finished. */
                      /* NO BASKET TERM HERE ANY MORE. `mixedBasket` used to be the third term and
                         is gone: a mix is payable, so the only things that dim this control are a
                         request in flight and a finished rail. */
                      disabled={ busy || railTerminal }
                      busy={ busy }
                    /> }
              </div>

              <p className="cart-back"><Link href="/shop/">Keep shopping</Link></p>
            </>
          )}
        </div>

        <style jsx>{`
          /* NO TOP PADDING, NO MEASURE AND NO FONT STACK HERE: PageTopBand owns all three, the
             way .shop-shell records for RotatingHero. This div sits inside .ptb-layout, which has
             already applied the 108px/96px header clearance, the 1300px measure and the gutter.
             820px is the reading measure for a list of lines plus a paragraph of terms - the band
             above it is wider, which is the same relationship .rh-sub has to .rh-head. */
          .cart-in{width:100%;max-width:820px;margin:0}
          /* The body rung: 20px/400/1.4/-.125px at rgba(0,0,0,.898). It was 18px at .7 alpha,
             which is neither of the two rungs this site has. */
          .cart-body{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0;
          }
          .cart-empty{margin:0}
          .cart-list{list-style:none;margin:0;padding:0}
          /* 1px #e5e7eb is the static hairline, per the rule that 1px is a static edge and 2px a
             hoverable one. Logical block-end so a mirrored document keeps the rule under the row. */
          .cart-row{
            display:flex;justify-content:space-between;align-items:center;gap:24px;
            padding-block:20px;border-block-end:1px solid #e5e7eb;flex-wrap:wrap;
          }
          .cart-row-main{min-width:0}
          /* The card-heading rung: 22px/700/lh1.27/-.25px, the same three numbers as .shop-name
             and .shopd-price, which is what makes the cart read as the same site as the catalogue.
             It was 20px/600, a rung that exists nowhere else. */
          .cart-name{font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;margin:0 0 8px}
          /* EVERY LINK RULE GOES THROUGH :global(). styled-jsx adds its scoping class only to
             lowercase DOM tags it can see in this file, never to a capitalised component, so the
             compiled rule for a next/link child would match nothing. */
          .cart-name :global(a){color:#000;text-decoration:none;text-underline-offset:3px}
          .cart-name :global(a:hover){color:#1a3a2a}
          .cart-name :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
          /* Price in dark green, never lime: lime means actionable and the page's one lime surface
             is the button below. #1a3a2a on white is about 11:1. Tabular figures so a column of
             prices lines up on the decimal. */
          .cart-price{
            font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;
            color:#1a3a2a;margin:0;font-variant-numeric:tabular-nums;
          }
          .cart-option-label{display:flex;flex-direction:column;gap:6px;margin-top:12px;font-size:14px;font-weight:700;color:#1a3a2a}
          .cart-option{
            min-height:44px;max-width:260px;padding:0 12px;border:1px solid #cbd5e1;border-radius:8px;
            background:#fff;color:#1a1a1a;font:inherit;
          }
          .cart-option:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
          .cart-row-controls{display:flex;align-items:center;gap:12px}
          .cart-qty-label{font-size:14px;font-weight:700;color:#1a3a2a}
          /* 44px is the tap-target floor. The site's CTA is 52px; a secondary field is not
             required to match it, only to clear 44. */
          .cart-qty{
            width:72px;min-height:44px;padding:0 10px;border:1px solid #e5e7eb;border-radius:8px;
            font-family:inherit;font-size:16px;text-align:center;color:#1a1a1a;
          }
          .cart-qty:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
          /* The contribution row's amount chooser. Deliberately the SAME box as .cart-qty - the
             1px #e5e7eb hairline, the 8px radius, the 44px tap floor and the 16px type - because
             it occupies the same slot in the row and a second control idiom there would read as a
             different kind of thing. Wider, because "₹250" plus the native disclosure arrow does
             not fit 72px. The leading rupee mark that used to sit beside the old free-text field
             went with it: each option already carries its own ₹.

             #1a3a2a is --accent / colors.primary and #e5e7eb is the shared hairline; no new hue is
             introduced by this phase. */
          .cart-amount-select{
            min-width:96px;min-height:44px;padding:0 10px;border:1px solid #e5e7eb;border-radius:8px;
            font-family:inherit;font-size:16px;color:#1a1a1a;background:#fff;
          }
          .cart-amount-select:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
          /* A 44px target, not a 27px one. This was padding:6px around a 15px line, which
             computed to about 27px tall - under the floor devicecheck enforces elsewhere on the
             site and the smallest control on the page. */
          .cart-remove{
            display:inline-flex;align-items:center;min-height:44px;padding-inline:8px;
            border:none;background:none;color:#1a3a2a;font-family:inherit;font-size:16px;
            font-weight:700;cursor:pointer;text-decoration:underline;text-underline-offset:3px;
          }
          .cart-remove:hover{background:rgba(209,244,112,.22);border-radius:8px}
          .cart-remove:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px;border-radius:2px}
          /* The terms box takes the catalogue's own notice treatment - 1px #e5e7eb hairline,
             12px radius, the dim rung at rgba(0,0,0,.54) - so it reads as the same kind of aside
             .shopd-note and .shop-asof are. */
          .cart-note{
            margin:28px 0 0;padding:16px 18px;border:1px solid #e5e7eb;border-radius:12px;
            font-size:16px;line-height:1.55;color:rgba(0,0,0,.54);
          }

          /* NO RED, ON OWNER INSTRUCTION, AND THE PALETTE HAS A BETTER ANSWER ANYWAY.
             This was #fbe9e9 on a #f0c0c0 border with #8a1f1f text - three colours that appear
             nowhere in the home design, on a site whose only red is the single full stop in the
             wordmark. The replacement is the lime state tint rgba(209,244,112,.22) behind a solid
             #d1f470 inline-start edge with #1a3a2a type, which is exactly the treatment
             .shop-asof and .blog-degraded already use for "read this before you trust what is
             below it". #1a3a2a on the composited tint measures about 10:1.
             COLOUR IS NOT THE ONLY CUE, which is what makes dropping red safe rather than a
             regression: the sentence states the problem, and role=status / role=alert carries the
             severity to assistive technology. The firmer variant thickens the edge to 4px and goes
             to weight 700 rather than changing hue - a luminance and weight step, which survives
             forced-colors and reduced colour discrimination in a way a hue swap does not.
             border-inline-start, not border-left, so the edge follows the reading direction. */
          .cart-status{
            margin:20px 0 0;padding:14px 16px;border-radius:10px;
            background:rgba(209,244,112,.22);border-inline-start:3px solid #d1f470;
            font-size:16px;line-height:1.5;color:#1a3a2a;
          }
          .cart-status-firm{border-inline-start-width:4px;font-weight:700}

          /* THE CHECKOUT/LOGIN CTA IS NOW PillButton, the home-page two-segment pill, so this page
             no longer carries a .cart-cta rule: the component owns the pill's shape, colours, focus
             ring, hover lift and reduced-motion handling. It replaced the single lime surface on
             owner instruction, to make the login gate the dark-green + mint pill. There is 28px of
             space above it, applied by the pill's own container margin via .cart-pill below. */
          .cart-pill{margin-top:28px}
          /* 44px, so the way back off this page is a real target too. */
          .cart-back{margin:28px 0 0;font-size:16px;line-height:1.55}
          .cart-back :global(a){
            display:inline-flex;align-items:center;min-height:44px;
            color:#1a3a2a;font-weight:700;text-underline-offset:3px;
          }
          .cart-back :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
          @media(max-width:767px){
            .cart-body{font-size:18px}
            .cart-row{gap:16px}
          }
          /* The CTA's reduced-motion handling moved into PillButton with the button itself. */
        `}</style>
      </PageTopBand>
    </>
  );
}
