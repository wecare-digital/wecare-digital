import { buildPageTitle } from '../../lib/page-title';
/**
 * /checkout/ - the website full-cart review and Razorpay rail.
 * A read-only server quote displays every line, discount, supply GST, delivery,
 * convenience fee and fee GST before payment. Neither cart prices nor browser
 * calculations are sent as money; prepare must match the reviewed server total.
 * A verified captured attempt is the only successful order transition.
 * WhatsApp checkout is a separate follow-up route and is not initiated here.
 */
import Head from 'next/head';
import Link from 'next/link';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import RotatingHero from '../RotatingHero';
import CheckoutProfile from '../CheckoutProfile';
import PublicNotice from '../public/PublicNotice';
import type { CheckoutProfileMode, CheckoutProfileValue } from '../CheckoutProfile';
import CheckoutIdentityCard from '../CheckoutIdentityCard';
import type { StoredAddress } from '../AddressFields';
import Select from '../ui/Select';
import { getSession, restoreSession } from '../../lib/customerAuth';
import type { CustomerSession } from '../../lib/customerAuth';
import {
  readCart, addItem, removeItem, setQuantity, clearCart, toLineItems, availableVariantsForItem,
  needsVariantSelection, setVariant,
  basketFingerprint, cartRequiresDelivery,
  serviceIntentFor, mergeClaimedLines, rememberServiceIntent,
} from '../../lib/cart';
import { SERVICE_REFUSAL_MESSAGES, isServiceRefusal, postRequestIntent } from '../../lib/serviceRequests';
import { SERVICE_PRODUCT_IDS, SERVICE_CHOICES } from '../../config/services';
import type { CartItem, CheckoutLineItem } from '../../lib/cart';
import type { ShopProduct } from '../../content/shop';
import { parseCheckoutQuote, type CheckoutQuote } from '../../lib/checkoutQuote';
import { formatPaiseINR } from '../../lib/money';
// The WhatsApp catalogue hand-off. The page owns WHEN to claim; the module owns HOW, so the
// request shape has one definition. See `src/lib/whatsappBasket.ts`.
import {
  basketTokenFromUrl, claimBasket, claimMessage, rememberBasketToken, stripBasketParam,
  CLAIM_NOT_SHOWN_MESSAGE,
} from '../../lib/whatsappBasket';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../../config/contribution';
import { colors } from '../../lib/design-tokens';
/**
 * THE OPAQUE SQUARE MARK, and it has to be that one. Razorpay composites this logo onto its own
 * modal surface, so it is a renderer we do not control - exactly the case src/test/BrandAssets.
 * test.ts bans `wecaredigital.png` from, because that file is 68.4% transparent with a black mark
 * and flattens to an invisible logo on a dark ground. `schema.ts`'s LOGO_URL is the 1080x1080
 * opaque-white-ground asset already serving apple-touch-icon and the Organization logo, and it is
 * imported rather than restated so the two cannot drift.
 */
import { LOGO_URL } from '../../lib/schema';
import { stashPendingAction, takePendingAction, type CheckoutChannel } from '../../lib/serviceEntry';
// The two request-key slots live with the status-screen hand-off, so the screen that empties a
// paid cart and the page that minted its key name the same storage keys.
import {
  CHECKOUT_REQUEST_BASKET, CHECKOUT_REQUEST_KEY, rememberCheckoutAttempt,
} from '../../lib/checkoutHandoff';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const PREPARE_CHECKOUT_URL = `${API_BASE}/ecommerce/prepare-checkout`;
const VERIFY_CHECKOUT_URL = `${API_BASE}/ecommerce/verify-callback`;
const RAZORPAY_SDK = 'https://checkout.razorpay.com/v1/checkout.js';
// The old production checkout Lambda treats unknown actions as CREATE. Until
// version-pinned backend deployment proves it understands action:quote, do not
// send a quote request at all. This switch is compile-time, default OFF.
const WEBSITE_FULL_CART_QUOTE_ENABLED =
  process.env.NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED === 'true';

/**
 * One directly linked commerce QA item. It is intentionally absent from
 * catalogSnapshot, SHOP_PRODUCTS, SHOP_LISTINGS, /shop/ and Meta: those are
 * publication surfaces, not the ProductsTable payment authority.
 *
 * The static cart page already exists and is noindex,nofollow; this creates
 * neither a product page nor a public shop listing. The browser carries only
 * product/variant IDs to checkout, where ProductsTable supplies the price.
 */
const COMMERCE_TEST_VARIANT_ID = 'WCTEST2R26';
const COMMERCE_TEST_PRODUCT: ShopProduct = {
  id: 'native:commerce-test-2',
  name: 'Commerce Test - Rs 2',
  slug: '', // No /shop/commerce-test-2/ page exists.
  formattedPrice: '₹2.00', // Display only, NEVER transmitted to checkout.
  price: '2.00',
  currency: 'INR',
  inStock: true,
  tagline: 'Internal commerce verification only',
  body: [],
  variants: [ { id: COMMERCE_TEST_VARIANT_ID, label: 'Standard', inStock: true } ],
};

/**
 * A one-time direct cart-prefill link, not a payment link or a second checkout.
 * It is an allowlist of exactly one product/variant, not a caller-supplied
 * product ID or price. A saved cart stays intact; an existing QA line is not
 * incremented on refresh, React StrictMode remount or link re-open.
 */
function cartFromDirectTestLink (): CartItem[] {
  const existing = readCart();
  if ( typeof window === 'undefined' ) return existing;
  const query = new URLSearchParams( window.location.search );
  if ( query.get( 'test' ) !== COMMERCE_TEST_VARIANT_ID || query.has( 'basket' ) )
    return existing;

  const present = existing.some( item =>
    item.productId === COMMERCE_TEST_PRODUCT.id
    && item.variantId === COMMERCE_TEST_VARIANT_ID );
  const items = present ? existing : addItem( COMMERCE_TEST_PRODUCT, 1, COMMERCE_TEST_VARIANT_ID );

  // The link is consumed once. A reload must never add a second unit.
  query.delete( 'test' );
  const remaining = query.toString();
  window.history?.replaceState?.( null, '', window.location.pathname
    + ( remaining ? '?' + remaining : '' ) + window.location.hash );
  return items;
}

/**
 * Every hand-off to /checkout/status/. The attempt is recorded first, so that screen empties this
 * cart once the server reports that attempt PAID (`lib/checkoutHandoff`). The cart stays until
 * then: the hand-off itself proves nothing about money.
 */
function goToCheckoutStatus ( attemptId: string ): void {
  rememberCheckoutAttempt( attemptId );
  window.location.assign( `/checkout/status/?a=${ encodeURIComponent( attemptId ) }` );
}
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
 * priced -- ProductsTable prices every line and `checkout_pricing` adds the 2.5% convenience fee plus 18%
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
 * Discounts are payment facts, not cart decoration. There is no coupon or gift-card system any
 * more: the one discount is the always-on Delight policy, applied SERVER-SIDE at checkout. This
 * page therefore STATES Delight and never offers an Apply control or a code field.
 */
/** Where an unauthenticated shopper is sent, and returned from, before checkout. */
const SIGN_IN_PATH = '/auth?return=/checkout/';

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
const NOT_PREPARED = 'We could not start this order. No charge was made. Please try again shortly.';

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
  username?: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  emailVerified?: boolean;
  companyName?: string;
  designation?: string;
  phone?: string;
  profileComplete?: boolean;
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
const deriveStatus = ( status: string, addressComplete: boolean, profileComplete?: boolean ): ProfileStatus =>
  status === 'PROFILE_READY' && addressComplete && profileComplete !== false ? 'ready'
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
    username: String( reply.username || '' ),
    firstName: String( reply.firstName || '' ),
    lastName: String( reply.lastName || '' ),
    email: String( reply.email || '' ),
    emailVerified: reply.emailVerified === true,
    companyName: String( reply.companyName || '' ),
    designation: String( reply.designation || '' ),
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
  | { kind: 'QUOTE_CHANGED' }
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
  | { kind: 'SHORT_CHECKOUT_ONE_ITEM' }
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

interface CartPageProps {
  /** Optional rail retained for legacy sign-in and explicit channel hand-offs. */
  checkoutChannel?: CheckoutChannel;
}

export default function Cart ( { checkoutChannel }: CartPageProps = {} ): React.ReactElement {
  const [ items, setItems ] = useState<CartItem[]>( [] );
  const [ ready, setReady ] = useState<boolean>( false );
  const [ quote, setQuote ] = useState<CheckoutQuote | null>( null );
  const [ quoteFor, setQuoteFor ] = useState( '' );
  const [ quoteLoading, setQuoteLoading ] = useState( false );
  const [ quoteNotice, setQuoteNotice ] = useState( '' );
  const [ quoteRevision, setQuoteRevision ] = useState( 0 );
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
   * one to three seconds later, hit the catalogue step on that already-reserved cart, failed, and
   * `handler.py` answered 502 `CATALOGUE_UNAVAILABLE` -- which this page renders as "We could not
   * prepare this order." Every payment attempt failed that way, and the customer's own first
   * attempt was what broke their second.
   *
   * WHY THE EXISTING GUARDS DO NOT COVER IT, each for its own reason:
   *   * `disabled={ busy || ... }` is REACT STATE. `setBusy(true)` does not disable the button
   *     until a render commits, so two clicks (or a double-tap, or a click arriving beside
   *     `CheckoutProfile`'s `onSaved`) both enter `proceed` while the attribute is still false.
   *     State cannot guard re-entry into the function that sets it.
   *   * `railTerminalRef` is synchronous but answers a different question: "the rail already
   *     returned a RESULT". It is set when a payment finishes, not while one is being prepared,
   *     so it is false for the whole window this latch covers.
   *   * The server's one-live-payment guard IS the guarantee, and it still is -- but when this was
   *     measured it sat BELOW the catalogue step, so the second request failed as a catalogue
   *     error before the guard could answer its designed 409. Stopping the second post is what
   *     keeps that 502 unreachable from this page.
   *
   * A ref and not state for the reason `justSavedRef` and `resetCartRef` are: the decision is
   * made inside one invocation and must not be a render behind. Cleared in a `finally`, so a
   * throw anywhere in the run cannot leave the page permanently unable to check out.
   */
  const proceedInFlightRef = useRef<boolean>( false );
  const selectedCheckoutChannelRef = useRef<CheckoutChannel | undefined>( undefined );
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
    setItems( cartFromDirectTestLink() );
    setReady( true );

    // ASK THE READINESS QUESTION ONCE, ON ARRIVAL, so a returning customer is shown what we
    // already know instead of a form they filled in weeks ago. A FAILURE BLOCKS NOTHING AND SAYS
    // NOTHING: the status stays 'unknown' and `proceed` re-derives the truth on the click.
    let live = true;
    void ( async () => {
      // A returning OTP-verified customer may have only a persisted session.
      // Restore it before deciding the profile is absent on first cart load.
      let session;
      try { session = getSession() || await restoreSession(); }
      catch { return; }
      if ( !live || !session ) return;
      setCheckoutAccessToken( session.accessToken );
      const reply = await loadProfileStatus( session.accessToken );
      if ( !live || !reply ) return;
      setProfile( profileFrom( reply ) );
      setProfileStatus( deriveStatus( String( reply.status || '' ), Boolean( reply.addressComplete ), reply.profileComplete ) );
    } )();
    return () => { live = false; };
  }, [] );

  // A read-only ProductsTable quote is mandatory before the website can start
  // Razorpay. Profile, delivery or cart edits trigger an independent fresh quote.
  // No payment attempt or provider order is created by this effect.
  useEffect( () => {
    let live = true;
    if ( !WEBSITE_FULL_CART_QUOTE_ENABLED ) {
      setQuote( null );
      setQuoteFor( '' );
      setQuoteLoading( false );
      setQuoteNotice( 'Checkout not ready. Payment unavailable.' );
      return () => { live = false; };
    }
    if ( !ready || items.length === 0 ) {
      setQuote( null );
      setQuoteFor( '' );
      setQuoteLoading( false );
      return () => { live = false; };
    }
    if ( items.some( needsVariantSelection ) ) {
      setQuote( null );
      setQuoteFor( '' );
      setQuoteNotice( 'Choose product options to see total.' );
      setQuoteLoading( false );
      return () => { live = false; };
    }

    let lines: CheckoutLineItem[];
    try { lines = toLineItems( items ); }
    catch {
      setQuote( null );
      setQuoteFor( '' );
      setQuoteNotice( 'Check cart items and quantities.' );
      setQuoteLoading( false );
      return () => { live = false; };
    }
    const fingerprint = basketFingerprint( lines );
    setQuote( null );
    setQuoteFor( '' );
    setQuoteLoading( true );
    setQuoteNotice( '' );
    void ( async () => {
      try {
        const session = getSession() || await restoreSession();
        if ( !session ) {
          if ( live ) setQuoteNotice( 'Sign in to view final price.' );
          return;
        }
        const serviceIntent = serviceIntentFor( lines );
        const response = await fetch( PREPARE_CHECKOUT_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json',
            Authorization: `Bearer ${ session.accessToken }` },
          body: JSON.stringify( { action: 'quote', lineItems: lines,
            ...( serviceIntent ? { serviceIntentId: serviceIntent } : {} ) } ),
        } );
        const body = await response.json().catch( () => ( {} ) ) as Record<string, unknown>;
        if ( !live ) return;
        const parsed = response.ok ? parseCheckoutQuote( body ) : null;
        if ( !parsed ) {
          const error = String( body.error || '' );
          if ( error === 'PROFILE_REQUIRED' || error === 'DELIVERY_DETAILS_REQUIRED' ) {
            // The price cannot be computed for a missing identity/address.
            // The checkout editor must be usable WITHOUT a payable button.
            setCheckoutAccessToken( session.accessToken );
            setProfileMode( error === 'DELIVERY_DETAILS_REQUIRED' ? 'address' : 'create' );
            setProfileStatus( 'required' );
            setShowProfile( true );
          }
          setQuoteNotice( error === 'PROFILE_REQUIRED' ? 'Enter your name to view price.'
            : error === 'DELIVERY_DETAILS_REQUIRED' ? 'Confirm address to view final price.'
              : error === 'CART_NOT_PAYABLE' ? 'Item price unavailable. Review cart.'
                : response.status === 401 ? 'Sign in again to view price.'
                  : 'Verified price unavailable. Payment disabled.' );
          return;
        }
        // A stale response must never price a different basket selected meanwhile.
        if ( basketFingerprint( toLineItems( readCart() ) ) !== fingerprint ) return;
        setQuote( parsed );
        setQuoteFor( fingerprint );
        setQuoteNotice( '' );
      } catch {
        if ( live ) setQuoteNotice( 'Price service unavailable. Payment disabled.' );
      } finally {
        if ( live ) setQuoteLoading( false );
      }
    } )();
    return () => { live = false; };
  }, [ items, ready, profile, profileStatus, quoteRevision ] );

  /**
   * THE WHATSAPP BASKET CLAIM. Runs only when `?basket=` is present, and at most once.
   *
   * ONCE IS ENFORCED BY A REF, NOT BY THE DEPENDENCY LIST. The effect has an empty list, but React
   * 19's StrictMode double-invokes effects in development and the claim is a SERVER-SIDE
   * SINGLE-USE write: a second POST is refused by design, so a double invoke would render "this
   * link is no longer available" over a cart that had just been filled correctly. A synchronous
   * ref latch is the only guard that holds, for the same reason `proceedInFlightRef` is one.
   *
   * NO SESSION MEANS SIGN IN FIRST, AND THE TOKEN TRAVELS BESIDE THE URL, NOT INSIDE IT. A link
   * opened in WhatsApp's in-app browser usually has no session, so this is the normal case rather
   * than an edge. The `return` value is validated by `safeLocalReturnPath`
   * (`src/lib/safeReturnPath.ts`), which REJECTS any value carrying a query string and re-emits the
   * normalised ALLOWLIST member rather than the input -- so `?return=%2Fcart%2F%3Fbasket%3D<token>`
   * comes back as a bare `/cart/` and the token is gone. That refusal is the control against a
   * smuggled query and must not be loosened, so `rememberBasketToken` stashes the token in
   * `sessionStorage` before the redirect and `basketTokenFromUrl()` reads and CLEARS it on arrival.
   * Single-use on purpose: a stale token could only be refused, and a refusal for a basket already
   * in the cart is the confusing outcome this whole effect exists to avoid.
   *
   * THE PARAMETER IS STRIPPED ON SUCCESS ONLY. On a refusal it is left in place: the sentence
   * explains what happened, and a customer who reloads sees the same honest answer rather than a
   * silently different page. See `stripBasketParam`.
   *
   * IT FETCHES NOTHING WHEN THE PARAMETER IS ABSENT, which is most visits. That keeps the static
   * export's no-fetch-at-render property intact -- `src/test/CartRedemption.test.tsx` asserts it.
   *
   * THE CLAIMED LINES ARE MERGED INTO THE BROWSER CART, and that is the whole point of the round
   * trip rather than a nicety. The claim merges them into the customer's SERVER-side cart, but this
   * page renders `readCart()` and `proceed` posts `toLineItems( currentItems )` from the same
   * storage -- so a claim that returned only a count left the customer looking at an unchanged cart
   * (a success indistinguishable from a refusal) and the next checkout reconciled the claimed lines
   * back OUT of the server-side cart, because the checkout makes that cart match the REQUEST.
   * `mergeClaimedLines` writes them through the same `cart.ts` helpers /shop/ uses.
   *
   * ONE RETRY FOR A STALE SAVED CART, AND ONLY WHEN THIS CART IS EMPTY. `BASKET_CART_IN_USE` is
   * the server's `CUSTOMERCART#<phone>` pointer, which lives thirty days and SURVIVES the payment
   * that consumed its cart -- `clearCart()` only empties localStorage. So "empty your website cart
   * and open the link again" was an instruction with no way to follow it for anyone who had
   * already paid once. With an empty cart here there is nothing of the customer's to lose, so the
   * retry sends `resetCart: true`, which releases that pointer exactly as the existing "Start a
   * new cart" control does. With a NON-empty cart the sentence is true as written, and is shown.
   */
  useEffect( () => {
    const token = basketTokenFromUrl();
    if ( !token || basketClaimedRef.current ) return;
    basketClaimedRef.current = true;

    const session = getSession();
    if ( !session )
    {
      // The sign-in flow returns to a BARE `/cart/` -- the allowlist strips the query -- so the
      // token has to be stashed here or it is lost. See the docblock above.
      rememberBasketToken( token );
      window.location.assign( `/auth?return=${ encodeURIComponent(
        window.location.pathname + window.location.search ) }` );
      return;
    }

    let live = true;
    void ( async () => {
      let outcome = await claimBasket( session.accessToken, token );
      if ( !live ) return;
      if ( outcome.kind === 'CART_IN_USE' && readCart().length === 0 )
      {
        outcome = await claimBasket( session.accessToken, token, { resetCart: true } );
        if ( !live ) return;
      }
      if ( outcome.kind === 'CLAIMED' )
      {
        const { items: merged, merged: placed } = mergeClaimedLines( outcome.lines );
        setItems( merged );
        // Said out loud only when NOTHING could be placed. A partial merge needs no sentence: the
        // customer pays for the lines they can see, which the server reconciles the cart down to.
        setBasketClaim( outcome.lines.length > 0 && placed === 0
          ? CLAIM_NOT_SHOWN_MESSAGE : null );
        stripBasketParam();
        return;
      }
      setBasketClaim( claimMessage( outcome ) );
    } )();
    return () => { live = false; };
  }, [] );

  const drop = useCallback( ( ref: string ): void => {
    setItems( removeItem( ref ) );
    setQuote( null );
  }, [] );

  const changeQuantity = useCallback( ( ref: string, quantity: number ): void => {
    try {
      setItems( setQuantity( ref, quantity ) );
      setQuote( null );
      setNotice( { kind: 'none' } );
      setPaymentBlocked( false );
    } catch {
      setNotice( { kind: 'quiet', message: 'Choose a quantity from 1 to 99.' } );
    }
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
    setQuote( null );
    setPaymentBlocked( false );
    setNotice( { kind: 'none' } );
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
    channel: CheckoutChannel,
    expectedTotalPaise: number,
    // AN ARGUMENT, not a ref read inside the body, for the same reason `lineItems` is one: this
    // callback closes over no state, so what it sends has to be handed to it.
    resetCart = false,
  ): Promise<Outcome> => {
    try
    {
      let serviceIntent = serviceIntentFor( lineItems );
      const services = lineItems.filter( line => SERVICE_PRODUCT_IDS.has( line.catalogReference.catalogItemId ) );
      const submit = SERVICE_CHOICES.find( choice => choice.kind === 'SUBMIT_REQUEST' )!;
      if ( !serviceIntent && services.length === 1 && services[ 0 ].quantity === 1
        && services[ 0 ].catalogReference.options?.variantId === submit.variantId )
      {
        const intent = await postRequestIntent( session.accessToken, 'SUBMIT_REQUEST' );
        if ( intent.kind === 'expired' ) return { kind: 'UNAUTHORIZED' };
        if ( intent.kind !== 'ok' || intent.intent.variantId !== submit.variantId )
        {
          return { kind: 'SERVICE_REFUSED', message: intent.kind === 'refused'
            ? intent.message : 'We could not start your service. Nothing has been charged. Please try again.' };
        }
        rememberServiceIntent( submit.variantId, intent.intent.intentId );
        serviceIntent = intent.intent.intentId;
      }
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
          ...( serviceIntent ? { serviceIntentId: serviceIntent } : {} ),
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

        // A quote change between review and prepare must never open a payment modal.
        // Exact integer paise equality is checked BEFORE invoking the provider SDK.
        if ( options.currency !== 'INR' || options.amountPaise !== expectedTotalPaise ) {
          return { kind: 'QUOTE_CHANGED' };
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
                // The same hand-off as every other path: remember the attempt, then navigate.
                goToCheckoutStatus( String( verdict.paymentAttemptId || attemptId ) );
                return;
              }
              /*
               * ANY OTHER ANSWER, OR NONE, HANDS OFF TO THE STATUS SCREEN. Razorpay has returned a
               * payment for this attempt, so the money may have moved whatever verify said: a lost
               * response, a 503, or NOT_CAPTURED while the capture is still settling. The Razorpay
               * webhook settles the attempt independently, and /checkout/status/ polls exactly
               * that and opens the order page once it is paid. Staying here left the customer on
               * a latched cart, told to "check your orders". The screen never says a charge was
               * or was not made; the cart is emptied there only if this attempt is reported PAID.
               */
              goToCheckoutStatus( String( verdict.paymentAttemptId || attemptId ) );
            } catch {
              // The verify request itself failed. Same hand-off: the attempt is the one Razorpay
              // just returned, and the status screen asks the server about it.
              goToCheckoutStatus( attemptId );
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
        goToCheckoutStatus( String( data.paymentAttemptId ) );
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
      // Optional Part 1 server preflight: this 409 is before payment initiation.
      if ( status === 'SHORT_CHECKOUT_ONE_ITEM' ) return { kind: 'SHORT_CHECKOUT_ONE_ITEM' };
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
        // Keep the cart until the server confirms a paid order; the status screen empties it then.
        goToCheckoutStatus( String( data.paymentAttemptId ) );
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

    if ( outcome.kind === 'QUOTE_CHANGED' )
    {
      setQuote( null );
      setQuoteFor( '' );
      setQuoteRevision( previous => previous + 1 );
      setNotice( { kind: 'quiet', message:
        'The payable amount changed. Review the updated price breakdown before paying.' } );
      return;
    }

    if ( outcome.kind === 'UNAUTHORIZED' )
    {
      // A customer who chose native WhatsApp must not silently switch to website
      // payment after their session expires. Keep the explicit choice out of the URL.
      const channel = selectedCheckoutChannelRef.current;
      if ( channel ) stashPendingAction( { kind: 'checkout', channel } );
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
        message: 'A contribution takes no discount. Remove it to continue.',
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

    // The backend refused the proposed order shape before creating a PaymentAttempt.
    // Do not misreport this as an ambiguous or possibly captured payment.
    if ( outcome.kind === 'SHORT_CHECKOUT_ONE_ITEM' )
    {
      setPaymentBlocked( true );
      setNotice( {
        kind: 'quiet',
        message: 'Choose one product, quantity one. Remove extra cart lines to continue. Nothing has been charged.',
      } );
      return;
    }

    // ── the Cart V2 refusals ───────────────────────────────────────────────────
    if ( outcome.kind === 'CART_RESET_REQUIRED' )
    {
      // The ONE outcome arm that carries an action rather than only words. The excess lines are on
      // the SERVER cart, which nothing on this page can touch, so "review your cart" would name
      // an action the customer cannot perform. `resetCart` abandons the server pointer only; the
      // browser cart is untouched and the next prepare rebuilds the server cart from it.
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

  const runCheckout = useCallback( async ( channel?: CheckoutChannel ): Promise<void> => {
    // Website payment is the ordinary cart action. An explicit WhatsApp choice still uses
    // the existing native leg, and survives the profile editor / sign-in round trip.
    if ( !WEBSITE_FULL_CART_QUOTE_ENABLED ) {
      setNotice( { kind: 'quiet', message:
        'Secure checkout is being prepared. No payment has been started.' } );
      return;
    }
    // Website checkout is the only payment rail on this page. WhatsApp has its
    // own route, where no payment is started until that separate project ships.
    const chosenChannel: CheckoutChannel = 'website';
    void channel;
    void checkoutChannel;
    selectedCheckoutChannelRef.current = chosenChannel;
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
      // Remember the chosen rail across WhatsApp OTP. /auth returns to /cart/,
      // whose one-shot pending checkout resumes this exact channel after sign-in.
      stashPendingAction( { kind: 'checkout', channel: chosenChannel } );
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
    // An owned phone-only bootstrap needs a name edit, not a new profile form.
    let mode: CheckoutProfileMode = profile?.name ? 'address' : profile ? 'name' : 'create';
    if ( status === 'unknown' || status === 'checking' )
    {
      setProfileStatus( 'checking' );
      const reply = await loadProfileStatus( session.accessToken );
      status = reply ? deriveStatus( String( reply.status || '' ), Boolean( reply.addressComplete ), reply.profileComplete ) : 'unknown';
      if ( reply )
      {
        setProfile( profileFrom( reply ) );
        // The REPLY decides the mode, not a guess: PROFILE_READY with no usable address needs the
        // address form, PROFILE_REQUIRED needs the whole creation flow.
        mode = String( reply.status || '' ) === 'PROFILE_READY'
          ? ( reply.profileComplete === false ? 'name' : 'address' )
          : 'create';
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
    // `mode`, NOT profile state: `profile` is a `useState` value captured in this closure and
    // `setProfile(...)` does not change it for the remainder of this invocation, and `profileFrom`
    // returns null for anything that is not PROFILE_READY. On a FIRST click `status` starts
    // 'unknown' and `profile` is still undefined, so a stale profile read would be true and a
    // contribution-only cart belonging to a fully provisioned customer would open the address
    // editor anyway -- failing on the first click and working on the second. `mode` carries no
    // stale read: it is reassigned from the reply inside the branch above.
    //
    // The server remains the authority. If this guesses wrong and lets a physical basket through,
    // `prepare` answers 409 DELIVERY_DETAILS_REQUIRED and the arm below opens the editor.
    const needsDelivery = cartRequiresDelivery();
    if ( status === 'required' && ( needsDelivery || mode === 'create' || mode === 'name' ) )
    {
      setProfileMode( mode );
      setShowProfile( true );
      setNotice( { kind: 'none' } );
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
    // A full website basket is allowed; the server checks every line/quantity.
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
    let lineItems: CheckoutLineItem[];
    try { lineItems = toLineItems( currentItems ); }
    catch {
      setItems( currentItems );
      setNotice( { kind: 'quiet', message: 'Review the quantities in your cart.' } );
      return;
    }
    if ( lineItems.length === 0 ) {
      setItems( readCart() );
      return;
    }
    if ( !quote || quoteFor !== basketFingerprint( lineItems ) || quoteLoading ) {
      setNotice( { kind: 'quiet', message:
        'Wait for the verified price breakdown before opening Razorpay.' } );
      setQuoteRevision( previous => previous + 1 );
      return;
    }
    const expectedTotalPaise = quote.charges.totalPaise;

    // Payment is initiated from this reviewed one-product cart, without a second chooser page.
    // The two existing server actions, their idempotency key, and verification remain unchanged.
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
      let outcome = await postPrepare( session, lineItems, chosenChannel, expectedTotalPaise, resetCart );

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
        outcome = await postPrepare( session, lineItems, chosenChannel, expectedTotalPaise );
      }

      // ONE ROTATION ON `INTENT_CHANGED`, and this is the ONE `CHECKOUT_REJECTED` reason a
      // rotation can clear.
      //
      // The reservation was taken against a fingerprint that has since moved for a reason the
      // browser cannot observe: `intent_fingerprint` keeps `cart_revision` AND `snapshot_hash`,
      // and `checkout_pricing.basket_hash`'s own docstring records as MEASURED that the website
      // prepare path writes to the server cart on every call -- so a second prepare of an UNEDITED
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
        outcome = await postPrepare( session, lineItems, chosenChannel, expectedTotalPaise );
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
  }, [ profile, profileStatus, checkoutChannel, quote, quoteFor, quoteLoading ] );

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
  const proceed = useCallback( async ( channel?: CheckoutChannel ): Promise<void> => {
    if ( proceedInFlightRef.current )
    {
      resetCartRef.current = false;
      return;
    }
    proceedInFlightRef.current = true;
    try
    {
      await runCheckout( channel );
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
    void proceed( selectedCheckoutChannelRef.current );
  }, [ proceed ] );

  useEffect( () => {
    // A saved payment-channel choice is not permission to initiate a charge
    // automatically after OTP. Show the reviewed price and require a fresh click.
    takePendingAction();
  }, [] );

  const isEmpty = ready && items.length === 0;
  const reviewedBasketFingerprint = ( (): string => {
    try { return basketFingerprint( toLineItems( items ) ); }
    catch { return ''; }
  } )();
  const quoteReady = Boolean( WEBSITE_FULL_CART_QUOTE_ENABLED && quote && !quoteLoading
    && quoteFor && quoteFor === reviewedBasketFingerprint
    && !items.some( needsVariantSelection ) );

  /**
   * THE WHATSAPP CLAIM SENTENCE, when the claim did not simply work. One line, no amount, no retry
   * button: every outcome's own sentence already names the action that helps, and a button here
   * would re-post a single-use claim. A success says nothing at all - the items appearing in the
   * list is the message.
   *
   * HOISTED OUT OF THE LIST BRANCH because it was unreachable exactly when it mattered most. It
   * used to live inside `items.length > 0`, so a customer whose cart was EMPTY - which is the
   * state every refusal arrives in for anyone who has just paid, and the state the stale-saved-cart
   * retry is for - read nothing at all and was left on "Your cart is empty." with no explanation
   * of the link they had just opened. Rendered in both branches from one definition, in the same
   * position within the list branch as before, so nothing moves for a customer who has items.
   */
  const basketClaimLine = basketClaim ? (
    <p className="cart-status" role="status" data-wc-basket-claim="true">
      { basketClaim }
    </p>
  ) : null;

  return (
    <>
      <Head>
        <title>{ buildPageTitle( 'Checkout' ) }</title>
        {/* Customer-session, per-person: never indexed. */}
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      {/* UNIFIED TOP HERO (owner 2026-10-13): every public page carries the same frame + lime pill
          + sub via the shared RotatingHero. A SINGLE word is passed so the pill is static (no
          2400ms rotation) - a cart is a task screen, so the house look without indefinite motion
          keeps WCAG 2.2.2. The global action dock is mounted once by _app after route policy. */}
      <RotatingHero
        ariaLabel="WECARE.DIGITAL customer"
        frame="One account."
        words={ [
          { word: 'securely', tint: '#e0f7c8', dot: '#3da35a' },
          { word: 'simply', tint: '#dbeafe', dot: '#2563eb' },
          { word: 'anywhere', tint: '#ede9fe', dot: '#9849e8' },
        ] }
        sub="Pick up where you left off."
        mobileFoundation
        compact
      >
        <div className="cart-in">
          <h1 className="cart-heading">Checkout</h1>
          <p className="cart-body cart-intro">Review every item and the verified total before paying securely.</p>
          {!ready && <p className="cart-body">Loading your cart…</p>}

          {isEmpty && (
            <div className="cart-empty">
              <p className="cart-body">Your cart is empty.</p>
              { basketClaimLine }
            </div>
          )}

          {ready && items.length > 0 && (
            <>
              <h2 className="cart-subheading">Your cart</h2>
              <ul className="cart-list">
                { items.map( item => (
                  <li className="cart-row" key={ item.ref }>
                    <div className="cart-row-main">
                      <p className="cart-name">{ item.name }</p>
                      {/* DISPLAY ONLY. This catalogue passthrough price never reaches the server. */}
                      <p className="cart-price" data-wc-no-translate="true">{ item.formattedPrice }</p>
                      { needsVariantSelection( item ) && (
                        /*
                         * BOTH LABELLING SOURCES, AND THAT IS THE POINT. The visible text is the
                         * same two words on every cart row, so it is `label` and the component
                         * renders and wires it; the accessible name is PER ITEM, so a shopper on
                         * a screen reader with three unvariant rows can tell the three
                         * comboboxes apart, and that is `ariaLabel`. Select emits `aria-label`
                         * and deliberately NOT `aria-labelledby` when both are passed, because
                         * `aria-labelledby` outranks `aria-label` and the per-item name would be
                         * lost silently. CartCheckout.test.tsx resolves this control by the EXACT
                         * string, which is the test standing in front of a wrong-amount order.
                         *
                         * The wrapping <label> is gone: a <button role="combobox"> inside a
                         * <label> still associates, so the name would be computed by walking the
                         * label subtree and would come out as the caption plus the trigger text.
                         *
                         * The '' row stays a REAL option, disabled, rather than becoming a
                         * `placeholder`, so the row list is exactly what it was.
                         */
                        <Select
                          className="cart-option"
                          label="Choose option"
                          ariaLabel={ `Choose option for ${item.name}` }
                          value=""
                          onChange={ value => chooseVariant( item.ref, value ) }
                          options={ [
                            { value: '', label: 'Select fit / size', disabled: true },
                            ...availableVariantsForItem( item ).map(
                              variant => ( { value: variant.id, label: variant.label } )
                            ),
                          ] }
                        />
                      ) }
                    </div>
                    <div className="cart-row-controls">
                      <div className="cart-qty" role="group" aria-label={ `Quantity for ${item.name}` }>
                        <button type="button" onClick={ () => changeQuantity( item.ref, item.quantity - 1 ) }
                          disabled={ item.quantity <= 1 } aria-label={ `Decrease ${item.name} quantity` }>−</button>
                        <span data-wc-no-translate="true" aria-live="polite">{ item.quantity }</span>
                        <button type="button" onClick={ () => changeQuantity( item.ref, item.quantity + 1 ) }
                          disabled={ item.quantity >= 99 } aria-label={ `Increase ${item.name} quantity` }>+</button>
                      </div>
                      <button
                        className="cart-remove"
                        type="button"
                        onClick={ () => drop( item.ref ) }
                        aria-label={ `Remove ${item.name}` }
                        title="Remove"
                      >
                        {/* Trash icon replaces the "Remove" text (owner request). aria-label +
                            title keep the accessible name and a hover tooltip. */}
                        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" width="20" height="20">
                          <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7m4 4v6m4-6v6" />
                        </svg>
                      </button>
                    </div>
                  </li>
                ) ) }
              </ul>

              <section className="cart-quote" aria-labelledby="cart-price-heading">
                <div className="cart-quote-title">
                  <h2 className="cart-subheading" id="cart-price-heading">Price breakdown</h2>
                  <button className="cart-quiet-refresh" type="button" disabled={ quoteLoading }
                    onClick={ () => setQuoteRevision( previous => previous + 1 ) }>
                    Refresh prices
                  </button>
                </div>
                { quoteLoading && <p className="cart-body" role="status">Checking prices…</p> }
                { quoteNotice && <p className="cart-status" role="status">{ quoteNotice }</p> }
                { quoteNotice.startsWith( 'Sign in' ) && (
                  <Link className="cart-auth-action" href="/auth?return=/checkout/">
                    Sign in on WhatsApp
                  </Link>
                ) }
                { quoteReady && quote && (
                  <>
                    <div className="cart-table-wrap">
                      <table className="cart-breakdown-table">
                        <caption className="cart-visually-hidden">Server-verified cart item prices</caption>
                        <thead><tr><th scope="col">Item</th><th scope="col">Qty</th><th scope="col">Unit price</th><th scope="col">Amount</th></tr></thead>
                        <tbody>
                          { quote.items.map( ( row, index ) => (
                            <tr key={ `${index}-${row.name}` }>
                              <th scope="row">{ row.name }</th>
                              <td data-wc-no-translate="true">{ row.quantity }</td>
                              <td data-wc-no-translate="true">{ formatPaiseINR( row.unitPricePaise, quote.currency ) }</td>
                              <td data-wc-no-translate="true">{ formatPaiseINR( row.totalPaise, quote.currency ) }</td>
                            </tr>
                          ) ) }
                        </tbody>
                      </table>
                    </div>
                    <dl className="cart-summary">
                      <div><dt>Items subtotal</dt><dd data-wc-no-translate="true">{ formatPaiseINR( quote.charges.merchandisePaise, quote.currency ) }</dd></div>
                      { quote.charges.supplyGstPaise > 0 && <div><dt>GST on products / services</dt><dd data-wc-no-translate="true">{ formatPaiseINR( quote.charges.supplyGstPaise, quote.currency ) }</dd></div> }
                      { quote.charges.discountPaise > 0 && <div><dt>{ quote.charges.discountLabel || 'Discount' }</dt><dd data-wc-no-translate="true">−{ formatPaiseINR( quote.charges.discountPaise, quote.currency ) }</dd></div> }
                      <div><dt>Delivery</dt><dd>{ quote.charges.deliveryPaise > 0 ? formatPaiseINR( quote.charges.deliveryPaise, quote.currency ) : 'Free' }</dd></div>
                      <div><dt>Convenience fee</dt><dd data-wc-no-translate="true">{ formatPaiseINR( quote.charges.convenienceFeePaise, quote.currency ) }</dd></div>
                      <div><dt>GST on convenience fee</dt><dd data-wc-no-translate="true">{ formatPaiseINR( quote.charges.convenienceGstPaise, quote.currency ) }</dd></div>
                      <div className="cart-summary-total"><dt>Final amount to pay</dt><dd data-wc-no-translate="true">{ formatPaiseINR( quote.charges.totalPaise, quote.currency ) }</dd></div>
                    </dl>
                  </>
                ) }
                <p className="cart-price-note">The total comes from the live server quotation.
                  Razorpay must show this same amount before you authorise payment.</p>
              </section>

              {/* The always-on Delight discount, stated (not applied) here. Every figure is
                  server-authoritative: Delight is priced by the invoice engine at checkout, not in
                  the browser.

                  NOT RENDERED ON A CART CONTAINING A CONTRIBUTION OR EXACT-PRICE SERVICE. A discount would make the
                  recorded amount differ from the amount contributed, so the server suppresses
                  Delight on a contribution and this panel is hidden to match. A render-time read of
                  `items` is correct here. */}

              {/* A returning customer's stored identity must remain visible when the
                  shipping address is missing. Non-shipping baskets omit the Deliver row;
                  physical baskets explicitly label an unsaved address. */}
              { profile && Boolean( profile.name ) && ( profileStatus === 'ready' || profileStatus === 'required' ) && (
                <CheckoutIdentityCard
                  identity={ profile }
                  showAddress={ cartRequiresDelivery() }
                  emptyAddressLabel="Not saved yet"
                  editorOpen={ showProfile }
                  onEditProfile={ () => { setProfileMode( 'profile' ); setShowProfile( true ); } }
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
                    name: profile?.name || '',
                    username: profile?.username || '',
                    companyName: profile?.companyName || '',
                    designation: profile?.designation || '',
                    address: profile?.address || null,
                  } }
                  onReady={ next => {
                    // THE STATUS DECIDES THE EDITOR, NOT THE SAVE EVENT. A save that lands
                    // without a usable address must leave the address form MOUNTED: closing it
                    // and then asking for an address is a dead end, and it is reachable - a
                    // stored address that stopped mapping, or a backend that wrote one it cannot
                    // re-validate.
                    const nextStatus = deriveStatus(
                      'PROFILE_READY',
                      next.addressComplete,
                      Boolean( next.name ),
                    );
                    setProfile( next );
                    justSavedRef.current = true;
                    setProfileStatus( nextStatus );
                    // Digital-only carts need a name and a verified phone, not
                    // a shipping address. Do not keep reopening an unnecessary
                    // address editor after a successful name-only save.
                    if ( nextStatus === 'ready' || ( next.name.trim() && !cartRequiresDelivery() ) )
                    {
                      setShowProfile( false );
                      setNotice( { kind: 'none' } );
                    }
                    else
                    {
                      setProfileMode( next.name.trim() ? 'address' : 'name' );
                      setShowProfile( true );
                      setNotice( { kind: 'none' } );
                    }
                  } }
                />
              ) }

              {/* The WhatsApp claim sentence. Defined once above, beside the reason it is not
                  written inline here any more. */}
              { basketClaimLine }

              {/* PublicNotice keeps both states inline until the checkout issue is resolved.
                  Error announcements stay assertive; no timer hides payment uncertainty. */}
              {notice.kind === 'quiet' && (
                <PublicNotice mode="inline" tone="info" message={ notice.message } />
              )}
              {notice.kind === 'error' && (
                <PublicNotice mode="inline" tone="error" message={ notice.message } />
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
                  rebuilds the server cart from it. */}
              { cartResetOffered && !railTerminal && (
                <p className="cart-back">
                  <button className="cart-auth-action" type="button" disabled={ busy }
                          onClick={ startNewCart }>
                    New cart
                  </button>
                </p>
              ) }

              <div className="cart-actions">
                { railTerminal
                  ? <Link className="cart-auth-action cart-auth-primary" href="/orders/">Orders</Link>
                  : <>
                    <button
                      className="cart-auth-action cart-auth-primary"
                      type="button"
                      onClick={ () => { void proceed( 'website' ); } }
                      disabled={ busy || !quoteReady }
                      aria-busy={ busy ? 'true' : undefined }
                    >
                      { busy ? 'Preparing…' : ( paymentBlocked ? 'Try again' : 'Pay here' ) }
                    </button>
                  </> }
              </div>
            </>
          )}

          {/* The site-wide Contribute / Subscribe / Share band is mounted once in _app, directly
              above Footer, so task pages do not own or duplicate it. */}
        </div>

        <style jsx>{`
          /* NO TOP PADDING, NO MEASURE AND NO FONT STACK HERE: PageTopBand owns all three, the
             way .shop-shell records for RotatingHero. This div sits inside .ptb-layout, which has
             already applied the 108px/96px header clearance, the 1300px measure and the gutter.
             820px is the reading measure for a list of lines plus a paragraph of terms - the band
             above it is wider, which is the same relationship .rh-sub has to .rh-head. */
          .cart-heading{margin:0 0 12px;color:var(--public-heading);font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking)}
          .cart-intro{margin-bottom:24px}
          .cart-subheading{margin:0;font-size:var(--public-card-size);line-height:var(--public-card-leading);font-weight:var(--public-card-weight);letter-spacing:var(--public-card-tracking);color:var(--public-heading)}
          .cart-qty{display:flex;align-items:center;gap:8px;white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--public-heading)}
          .cart-qty button{width:36px;height:40px;border:1px solid var(--public-hairline);border-radius:8px;background:var(--public-lime-tint);color:var(--public-brand-green);font-size:20px;cursor:pointer}
          .cart-qty button:disabled{opacity:.4;cursor:default}
          .cart-qty button:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}
          .cart-qty span{min-width:26px;text-align:center}
          .cart-quote{margin-top:26px;padding-top:24px;border-top:1px solid var(--public-hairline)}
          .cart-quote-title{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap}
          .cart-quiet-refresh{padding:8px;border:0;border-radius:8px;background:transparent;color:var(--public-brand-green);text-decoration:underline;cursor:pointer}
          .cart-quiet-refresh:disabled{opacity:.5}
          .cart-table-wrap{overflow-x:auto}
          .cart-breakdown-table{width:100%;border-collapse:collapse;text-align:left;font-size:14px;line-height:1.5;color:var(--public-text)}
          .cart-breakdown-table th,.cart-breakdown-table td{padding:9px 8px;border-bottom:1px solid var(--public-hairline)}
          .cart-breakdown-table thead th{font-size:13px;color:var(--public-brand-green)}
          .cart-breakdown-table td:not(:first-child){font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
          .cart-breakdown-table th:first-child{min-width:110px;overflow-wrap:anywhere}
          .cart-summary{display:flex;flex-direction:column;gap:11px;margin:24px 0 0;font-size:15px}
          .cart-summary>div{display:flex;gap:18px;justify-content:space-between;align-items:baseline}
          .cart-summary dt{color:var(--public-muted)}
          .cart-summary dd{margin:0;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;color:var(--public-heading)}
          .cart-summary-total{padding-top:14px;border-top:1px solid var(--public-hairline);font-size:19px}
          .cart-summary-total dt,.cart-summary-total dd{font-weight:700;color:var(--public-brand-green)}
          .cart-visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
          .cart-in{width:min(100%,560px);max-width:100%;margin:0;padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);box-sizing:border-box;color:var(--public-text);font-family:var(--font-sans)}
          /* The body rung: 20px/400/1.4/-.125px at rgba(0,0,0,.898). It was 18px at .7 alpha,
             which is neither of the two rungs this site has. */
          .cart-body{
            font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
            color:var(--public-body);margin:0;
          }
          .cart-empty{margin:0}
          /* The cart is one review surface rather than a stack of loose divider rows. Keep one
             neutral card around the basket, matching the Orders table container: white fill,
             1px static hairline, 16px radius, no decorative shadow. */
          .cart-list{
            list-style:none;margin:0;padding:0;
            border:0;border-radius:0;background:transparent;
            overflow:visible;
          }
          /* Rows stay structurally identical; only the visual grouping changes. */
          .cart-row{
            display:flex;justify-content:space-between;align-items:center;gap:16px;
            padding-block:14px;border:0;flex-wrap:nowrap;
          }
          .cart-row-main{min-width:0}
          /* The card-heading rung: 22px/700/lh1.27/-.25px, the same three numbers as .shop-name
             and .shopd-price, which is what makes the cart read as the same site as the catalogue.
             It was 20px/600, a rung that exists nowhere else. */
          .cart-name{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);margin:0 0 4px;color:var(--public-text)}
          /* Price in dark green, never lime: lime means actionable and the page's one lime surface
             is the button below. #1a3a2a on white is about 11:1. Tabular figures so a column of
             prices lines up on the decimal. */
          .cart-price{
            font-size:var(--public-body-size);font-weight:600;line-height:1.3;letter-spacing:var(--public-body-tracking);
            color:var(--public-brand-green);margin:0;font-variant-numeric:tabular-nums;
          }
          .cart-price-note{
            margin:0 0 12px;font-size:14px;line-height:1.5;
            color:var(--public-muted);
          }
          /* THE VARIANT CHOOSER, NOW OUR OWN COMBOBOX (batch 2f). What was a .cart-option-label
             wrapping a .cart-option select is one Select, so .cart-option is the className on
             the FIELD WRAPPER and the two rules below are the label-and-field layout the old
             wrapping label carried: the flex column, the 6px gap, the 12px top margin, and the
             caption type, inherited by the component label rather than restated on it.
             :global() IS MANDATORY ON BOTH, for the reason shop/<slug>.tsx records at length:
             styled-jsx stamps its scope hash only onto the lowercase DOM tags it can see in this
             file, and a className handed to a component reaches a node it never saw - so without
             :global() these rules match nothing and the chooser renders unspaced.
             max-width moves from the control to the wrapper, because the trigger is
             inline-size:100% of its field; 260px is the number the native control was capped at.
             THE BOX IS NOW form-controls.css's: the same 2px #e5e7eb, the same 13px radius, the
             same 44px floor and the same drawn chevron the native control was given in 1.3a, so
             the closed state does not change. What changes is the OPEN list, which is the one
             part no stylesheet could reach.
             THE FOCUS OUTLINE IS NOT REPRODUCED, and that is the one visible loss here: the
             shared file paints box-shadow var(--focus-ring) on :focus and declares outline none,
             which is what every other migrated control in the app does, and re-adding a 3px
             outline for this one control would make the checkout page the odd one out. The
             pairing rule is still gated - FormControlsCss.test.ts holds the ring on
             .ui-select-trigger:focus, and CartCheckout.test.tsx holds it on the two controls that
             are still styled here.
             NO APOSTROPHE OR STRAY QUOTE IN A CSS COMMENT HERE, deliberately: the census
             scanner blanks comments with a scanner that treats a quote as a string opener, so a
             lone apostrophe swallows the rules that follow and the census silently UNDER-counts.
             That is the one direction a gate must never fail in. */
          .cart-row-main :global(.cart-option){
            display:flex;flex-direction:column;gap:6px;margin-top:12px;max-width:260px;
            font-size:14px;font-weight:700;color:var(--public-brand-green);
          }
          .cart-row-main :global(.cart-option .ui-field-label){
            margin-block-end:0;color:inherit;font-size:inherit;font-weight:inherit;
          }
          .cart-row-controls{display:flex;align-items:center;gap:12px}
          /* Icon-only remove (trash), 44px target. Was an underlined "Remove" text link; now a
             quiet icon button that darkens on hover. The SVG inherits currentColor. */
          .cart-remove{
            display:inline-flex;align-items:center;justify-content:center;
            width:44px;height:44px;min-height:44px;padding:0;
            border:none;background:none;color:var(--public-brand-green);cursor:pointer;border-radius:999px;
          }
          .cart-remove:hover{background:rgba(209,244,112,.22);color:#0f2a1d}
          .cart-remove:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}
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
            font-size:16px;line-height:1.5;color:var(--public-brand-green);
          }
          .cart-status-firm{border-inline-start-width:4px;font-weight:700}

          .cart-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:28px}
          .cart-back{margin:28px 0 0;font-size:16px;line-height:1.55}
          .cart-auth-action{
            min-height:48px;min-width:48px;padding:8px 14px;border:0;border-radius:10px;
            background:var(--public-lime-tint);color:var(--public-brand-green);
            font:600 var(--public-cta-font-size)/1.35 var(--font-sans);
            text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;
            touch-action:manipulation;cursor:pointer;
            transition:background-color .18s,transform .18s,box-shadow .18s;
            display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;
          }
          .cart-auth-primary{font-weight:700}
          .cart-auth-action:hover{background:var(--public-brand-lime);transform:translateY(-1px);box-shadow:var(--public-lift-shadow);text-decoration-color:transparent}
          .cart-auth-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
          .cart-auth-action:disabled{opacity:.6;cursor:wait;transform:none;box-shadow:none}
          @media(max-width:767px){
            .cart-in{width:100%;padding:24px 18px max(24px,env(safe-area-inset-bottom));border-radius:20px}
            .cart-row{gap:12px;padding-block:12px;align-items:center}
            .cart-row-main{flex:1 1 auto;min-width:0}
            .cart-name,.cart-price{font-size:18px}
            .cart-row-controls{width:auto;flex:0 0 auto;justify-content:flex-end}
            .cart-remove{width:42px;height:42px;min-height:42px}
            .cart-actions{display:grid;grid-template-columns:1fr;width:100%;margin-top:22px}
            .cart-auth-action{width:100%}
          }
          @media(prefers-reduced-motion:reduce){
            .cart-auth-action{transition:none}
            .cart-auth-action:hover{transform:none;box-shadow:none}
          }
        `}</style>
      </RotatingHero>
    </>
  );
}
