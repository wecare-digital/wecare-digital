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
  readCart, setQuantity, removeItem, toLineItems,
} from '../lib/cart';
import type { CartItem } from '../lib/cart';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const PREPARE_CHECKOUT_URL = `${API_BASE}/ecommerce/prepare-checkout`;
const VERIFY_CHECKOUT_URL = `${API_BASE}/ecommerce/verify-callback`;
const RAZORPAY_SDK = 'https://checkout.razorpay.com/v1/checkout.js';
const CHECKOUT_REQUEST_KEY = 'wc_checkout_request_key';
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
  | { kind: 'CHECKOUT_REJECTED' }
  | { kind: 'PAYMENT_INITIATION_DISABLED' }
  | { kind: 'PAYMENT_UNAVAILABLE' }
  | { kind: 'LINE_ITEMS_REQUIRED' }
  | { kind: 'SEND_FAILED' }
  | { kind: 'PRICING_UNAVAILABLE' }
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
  prefill?: Record<string, string>;
  handler: ( result: RazorpaySuccess ) => void | Promise<void>;
  modal?: { ondismiss?: () => void };
};

declare global {
  interface Window {
    Razorpay?: new ( options: RazorpayOptions ) => {
      open: () => void;
      on: ( event: string, callback: ( payload: unknown ) => void ) => void;
    };
  }
}

function getCheckoutRequestKey (): string {
  if ( typeof window === 'undefined' ) return '';
  const existing = window.sessionStorage.getItem( CHECKOUT_REQUEST_KEY );
  if ( existing ) return existing;
  const generated = typeof window.crypto?.randomUUID === 'function'
    ? window.crypto.randomUUID()
    : `checkout-${ Date.now() }-${ Math.random().toString( 36 ).slice( 2 ) }`;
  window.sessionStorage.setItem( CHECKOUT_REQUEST_KEY, generated );
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
  // The payment rail was entered and returned a RESULT. A ref for the decision, so `proceed` is
  // never a render behind; a state for the render. DEFENCE IN DEPTH, NOT THE GUARANTEE: the latch
  // dies with the page, so a reload or a second tab walks straight past it. The server-side
  // one-live-payment-per-basket guard is the guarantee.
  const railTerminalRef = useRef<boolean>( false );
  // In-flight latch, distinct from railTerminalRef (which guards the terminal rail). This stops a
  // second concurrent proceed() from firing a second prepare-checkout before the first completes:
  // the duplicate hit Wix on the already-reserved cart and the server returned 502
  // CATALOGUE_UNAVAILABLE, shown as "We could not prepare this order." Synchronous ref so the
  // check-and-set is atomic within a turn.
  const prepareInFlightRef = useRef<boolean>( false );
  const [ railTerminal, setRailTerminal ] = useState<boolean>( false );

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

  const changeQuantity = useCallback( ( ref: string, quantity: number ): void => {
    setItems( setQuantity( ref, quantity ) );
  }, [] );

  const drop = useCallback( ( ref: string ): void => {
    setItems( removeItem( ref ) );
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
          requestKey: getCheckoutRequestKey(),
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
          name: 'WECARE.DIGITAL',
          description: 'Order payment',
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
        return { kind: 'CHECKOUT_REJECTED' };
      }

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

    if ( outcome.kind === 'SDK_UNAVAILABLE' )
    {
      setNotice( { kind: 'error', message: 'Secure payment could not open. Your cart is unchanged.' } );
      return;
    }

    // MALFORMED, LOST and UNRECOGNISED. Safe to claim nothing: a lost response cannot prove the
    // request never reached the server, and the others carried no live attempt to be wrong about.
    setNotice( { kind: 'error', message: 'We could not confirm checkout. Check your orders before trying again.' } );
  }, [] );

  const proceed = useCallback( async (): Promise<void> => {
    // AHEAD of the notice reset, deliberately: a re-entry -- from CheckoutProfile's onSaved, or
    // a stray click -- must neither re-enter the rail nor wipe the explanation already on screen.
    if ( railTerminalRef.current ) return;
    // Re-entry latch: ignore a duplicate proceed() while a prepare-checkout is already in flight,
    // so the server never receives a second prepare on the already-reserved cart (which 502s).
    if ( prepareInFlightRef.current ) return;
    prepareInFlightRef.current = true;
    try {
    setNotice( { kind: 'none' } );

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

    if ( status === 'required' )
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
    const lineItems = toLineItems();
    if ( lineItems.length === 0 )
    {
      setItems( readCart() );
      return;
    }

    setBusy( true );
    try
    {
      let outcome = await postPrepare( session, lineItems );

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

      applyOutcome( outcome, session );
    }
    finally
    {
      setBusy( false );
    }
    } finally {
      prepareInFlightRef.current = false;
    }
    // `postPrepare` and `applyOutcome` are `useCallback(..., [])`, so they are referentially
    // stable for the life of this component and cannot go stale. The only live dependencies are
    // the two pieces of state read above.
  }, [ profile, profileStatus ] );

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
                    </div>
                    <div className="cart-row-controls">
                      <label className="cart-qty-label" htmlFor={ `qty-${item.ref}` }>Qty</label>
                      <input
                        id={ `qty-${item.ref}` }
                        className="cart-qty"
                        type="number"
                        min={ 1 }
                        value={ item.quantity }
                        onChange={ e => changeQuantity( item.ref, Number( e.target.value ) ) }
                      />
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
                  gate off this shows an honest unavailable state and cannot transact. */}
              <RedemptionPanel />

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

              {/* role is chosen by severity, not by colour: 'status' is polite for a state the
                  shopper can simply retry, 'alert' interrupts for one they cannot. Neither relies
                  on the tint to carry the meaning - the sentence does. */}
              {notice.kind === 'quiet' && (
                <p className="cart-status" role="status">{ notice.message }</p>
              )}
              {notice.kind === 'error' && (
                <p className="cart-status cart-status-firm" role="alert">{ notice.message }</p>
              )}

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
          .cart-row-controls{display:flex;align-items:center;gap:12px}
          .cart-qty-label{font-size:14px;font-weight:700;color:#1a3a2a}
          /* 44px is the tap-target floor. The site's CTA is 52px; a secondary field is not
             required to match it, only to clear 44. */
          .cart-qty{
            width:72px;min-height:44px;padding:0 10px;border:1px solid #e5e7eb;border-radius:8px;
            font-family:inherit;font-size:16px;text-align:center;color:#1a1a1a;
          }
          .cart-qty:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
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
