import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { serviceByKind, type ServiceChoice } from '../config/services';
import {
  fetchServicePrices, rupeesFromPaise, type ServicePrice,
} from '../lib/servicePricing';
import { getSession, restoreSession } from '../lib/customerAuth';
import { postRequestIntent, fetchMyRequests, type ServiceRequestRow } from '../lib/serviceRequests';
import { setServiceLine } from '../lib/cart';
import { CHECKOUT_PATH, goToServiceAction } from '../lib/serviceEntry';
import CheckoutAction from './CheckoutAction';

/**
 * THE SERVICE CHECKOUT ACTION for Submit Request, Request Amendment, Drop Docs, Vault and
 * Request Pickup.
 *
 * ProductPage suppresses its generic conversation CTA whenever this buy box is present, so this is
 * the route's ONE paid Checkout entry. It adds the service intent to the cart; Pay on WhatsApp vs
 * Pay here is chosen only after cart review.
 *
 * WHY A COMPONENT RATHER THAN TWO CONTENT FIELDS. Unlike /anew/'s static `price="₹599"`, a
 * service price is LIVE from the catalogue (owner decision 2026-10-08: a price must change with no deploy),
 * and the button has to do real work on click — resolve the session, mint a pre-payment intent,
 * and write the one service line the cart prices. None of that is expressible as a content string,
 * so it lives here and the five thin route files mount it.
 *
 * IT NEVER SENDS A PRICE AND NEVER INVENTS ONE. The amount shown is the catalogue's own, read through
 * `fetchServicePrices` (which fails closed). The amount CHARGED is decided server-side on
 * `prepare-checkout`, exactly as every other cart line. `setServiceLine` carries the live paise
 * only so the cart row has a display figure; `toLineItems` strips it before the server sees it.
 *
 * FAIL CLOSED. If the live price cannot be read, no price line renders and the checkout pill is
 * NOT offered — a button that cannot name an honest amount is worse than no button. The WhatsApp
 * route still works, so the customer is never stranded.
 *
 * THE TARGET REQUIREMENT. Four of the five services (`needsTarget`) amend/attach to one of the
 * customer's OWN paid orders, and the server refuses an intent without a `targetRequestId`
 * (SERVICE_ORIGINAL_ORDER_REQUIRED). For those, a signed-in customer picks the order first and the
 * pill stays disabled until they do. Submit Request has no target and goes straight through.
 *
 * CART IS UNTOUCHED BY DESIGN. This sets the service line (and its intent pointer) in storage,
 * THEN navigates to `/cart/`. The cart page already reads `readCart()` on mount and `postPrepare`
 * already mints/validates the intent for a single service line, so no change to `cart.tsx` is
 * needed — the line is simply already there when the customer arrives.
 */

interface ServiceBuyBoxProps {
  /** The service this page sells. One of the five SERVICE_CHOICES. */
  service: ServiceChoice;
}

/**
 * PLACEHOLDER DISPLAY PRICES, by service slug, for the time being (owner instruction). Used ONLY
 * when the live `service-prices` API returns no usable price for the slug. Today that is Request
 * Pickup at ₹550 — the backend does not yet price it, so this keeps its Checkout action live rather
 * than hidden. DISPLAY ONLY: the server re-prices on prepare. Remove a slug
 * here once the API returns its real price; a slug not listed and not priced stays hidden.
 */
const PLACEHOLDER_SERVICE_PAISE: Readonly<Record<string, number>> = {
  'request-pickup': 55000,
};

type Phase =
  | { kind: 'loading' }                    // price fetch in flight
  | { kind: 'unavailable' }                // no honest price → no pill
  | { kind: 'ready'; price: Extract<ServicePrice, { available: true }> };

const ServiceBuyBox: React.FC<ServiceBuyBoxProps> = ( { service } ) => {
  const router = useRouter();
  const [ phase, setPhase ] = useState<Phase>( { kind: 'loading' } );
  const [ signedIn, setSignedIn ] = useState( false );
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );

  // Target-order picking, only consulted for a service that needs one.
  const [ targets, setTargets ] = useState<ServiceRequestRow[] | null>( null );
  const [ targetsLoading, setTargetsLoading ] = useState( false );
  const [ chosenTarget, setChosenTarget ] = useState<string>( '' );

  // Guards an unmounted setState after an await, the pattern the rest of the codebase uses.
  const alive = useRef( true );
  useEffect( () => () => { alive.current = false; }, [] );

  // Live price on mount. Fails closed: any rejection renders no pill.
  useEffect( () => {
    let cancelled = false;
    void ( async () => {
      const prices = await fetchServicePrices();
      if ( cancelled || !alive.current ) return;
      const price = prices[ service.slug ];
      if ( price && price.available ) {
        setPhase( { kind: 'ready', price } );
        return;
      }
      // PLACEHOLDER FALLBACK (owner instruction, time being). When the live API cannot price a
      // service — today only Request Pickup, which the backend does not yet return — the button
      // still shows at a placeholder figure so the format is live end to end, rather than being
      // hidden. The server re-prices on prepare, so this is a DISPLAY figure only; it becomes the
      // real live price automatically the moment the backend starts returning one for this slug.
      const fallback = PLACEHOLDER_SERVICE_PAISE[ service.slug ];
      setPhase( typeof fallback === 'number'
        ? { kind: 'ready', price: { available: true, paise: fallback, rupees: rupeesFromPaise( fallback ) } }
        : { kind: 'unavailable' } );
    } )();
    return () => { cancelled = true; };
  }, [ service.slug ] );

  // Resolve the session (sync first, then a server restore), so the pill knows which label to
  // show and whether to load the customer's orders for a target pick.
  useEffect( () => {
    let cancelled = false;
    void ( async () => {
      let live = getSession() !== null;
      if ( !live ) {
        try { live = ( await restoreSession() ) !== null; } catch { live = false; }
      }
      if ( !cancelled && alive.current ) setSignedIn( live );
    } )();
    return () => { cancelled = true; };
  }, [] );

  // Load the customer's own requests to choose a target from, once, when a signed-in customer is
  // on a target-needing service. `fetchMyRequests` takes paid-order references; passing none asks
  // for the caller's recent requests, which is the list a target is chosen from.
  useEffect( () => {
    if ( !signedIn || !service.needsTarget || targets !== null ) return;
    const session = getSession();
    if ( !session ) return;
    let cancelled = false;
    void ( async () => {
      // The loading flag is set INSIDE the async body (not synchronously in the effect) so an
      // extra cascading render is not triggered on mount — the behaviour is the same, the hint is
      // raised one microtask later.
      if ( !cancelled && alive.current ) setTargetsLoading( true );
      const outcome = await fetchMyRequests( session.accessToken, [] );
      if ( cancelled || !alive.current ) return;
      setTargets( outcome.kind === 'ok' ? outcome.requests : [] );
      setTargetsLoading( false );
    } )();
    return () => { cancelled = true; };
  }, [ signedIn, service.needsTarget, targets ] );

  /**
   * The click. Signed out → the one WhatsApp sign-in, returning to THIS service page so the buy
   * box resumes (not to /cart/, so a target can still be picked). Signed in → mint the intent,
   * set the one service line with the live price, then go to the cart.
   */
  const onContinue = useCallback( async () => {
    if ( phase.kind !== 'ready' || busy ) return;
    setError( null );

    // Signed out: hand to the one WhatsApp login, returning here. `goToServiceAction` stashes the
    // pending action and routes to /account/sign-in?return=<this page>.
    if ( !signedIn ) {
      await goToServiceAction( router, {
        destination: service.path,
        action: { kind: service.slug, variantId: service.variantId, label: service.label },
      } );
      return;
    }

    const session = getSession();
    if ( !session ) { setSignedIn( false ); return; }

    if ( service.needsTarget && !chosenTarget ) {
      setError( 'Choose which order this is for.' );
      return;
    }

    setBusy( true );
    try {
      const outcome = await postRequestIntent(
        session.accessToken,
        service.kind,
        service.needsTarget ? chosenTarget : undefined,
      );
      if ( !alive.current ) return;
      if ( outcome.kind === 'expired' ) { setSignedIn( false ); setBusy( false ); return; }
      if ( outcome.kind !== 'ok' ) {
        setError( outcome.kind === 'refused'
          ? outcome.message
          : 'We could not start this just now. Nothing has been charged. Please try again.' );
        setBusy( false );
        return;
      }
      // One service line, priced for display from the live catalogue paise; intent pointer stored beside
      // it. `setServiceLine` writes nothing if the variant or amount is not usable.
      setServiceLine( service.variantId, outcome.intent.intentId, phase.price.paise );
      await router.push( CHECKOUT_PATH );
    } catch {
      if ( alive.current ) {
        setError( 'Something went wrong. Nothing has been charged. Please try again.' );
        setBusy( false );
      }
    }
  }, [ phase, busy, signedIn, router, service, chosenTarget ] );

  // No honest price → render no commerce action rather than offering a checkout the server cannot price.
  if ( phase.kind === 'loading' || phase.kind === 'unavailable' ) {
    return null;
  }

  const needsTargetChoice = service.needsTarget;
  const noTargetsYet = needsTargetChoice && targets !== null && targets.length === 0;
  const disabled = busy
    || ( signedIn && needsTargetChoice && ( noTargetsYet || !chosenTarget ) );
  // Always "Checkout", signed in or out. WhatsApp OTP is an identity step, not a payment choice.
  const label = 'Checkout';

  return (
    <div className="sbb">
      {/* The target picker: only for a signed-in customer on a target-needing service. */}
      { signedIn && needsTargetChoice && (
        <div className="sbb-target">
          { targetsLoading && <p className="sbb-hint">Loading your orders…</p> }
          { noTargetsYet && (
            <p className="sbb-hint">You have no paid orders yet. There is nothing to attach this to.</p>
          ) }
          { targets !== null && targets.length > 0 && (
            <label className="sbb-pick">
              <span className="sbb-pick-label">Which order is this for?</span>
              <select
                className="sbb-select"
                value={ chosenTarget }
                onChange={ e => { setChosenTarget( e.target.value ); setError( null ); } }
                disabled={ busy }
              >
                <option value="">Choose an order…</option>
                { targets.map( row => (
                  <option key={ row.requestId } value={ row.requestId }>
                    { row.requestId }{ row.orderNumber ? ` · ${ row.orderNumber }` : '' }
                  </option>
                ) ) }
              </select>
            </label>
          ) }
        </div>
      ) }

      <CheckoutAction
        onClick={ () => { void onContinue(); } }
        disabled={ disabled }
        busy={ busy }
      >
        { busy ? 'One moment…' : label }
      </CheckoutAction>

      {/* The price, in /anew/'s own treatment: just the amount, no fee copy. */}
      <p className="sbb-buy">
        <span className="sbb-price" data-wc-no-translate="true">{ `\u20B9${ phase.price.rupees }` }</span>
      </p>
      <p className="sbb-offer-note">One-time service</p>

      { error && <p className="sbb-error" role="alert">{ error }</p> }

      <style jsx>{`
        /* Sits in ProductPage's .pdp-ctas column, directly under the WhatsApp pill. The pill
           geometry is the house pill (.pdp-cta): 52px, pill radius, 2px #1a3a2a edge. This is the
           SECONDARY of the pair, so it is the inverted treatment — white fill, dark edge and type
           — with the SAME hover lift the primary uses, which is also how the home CTA and
           PhoneField draw a secondary action. */
        .sbb{display:flex;flex-direction:column;align-items:flex-start;gap:0;margin-top:12px}
        .sbb-target{margin:0 0 14px}
        .sbb-pick{display:flex;flex-direction:column;gap:6px}
        .sbb-pick-label{font-size:15px;font-weight:600;color:var(--public-brand-green)}
        .sbb-select{
          min-height:48px;padding:0 14px;border:1px solid #d1d5db;border-radius:10px;
          background:#fff;font-size:15px;color:var(--public-body);min-width:min(100%,420px);
        }
        .sbb-select:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}
        .sbb-hint{margin:0 0 2px;font-size:14px;color:var(--public-muted)}

        /* The shared commerce price rung: 22px/700 dark green, tabular numerals, with one
           muted body-typography supporting line below it. */
        .sbb-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
        .sbb-price{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .sbb-offer-note{
          max-width:var(--public-copy-max);margin:7px 0 0;font-family:var(--font-sans);
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-muted);text-wrap:balance;
        }

        .sbb-error{margin:12px 0 0;font-size:14px;color:#b91c1c}

      `}</style>
    </div>
  );
};

export default ServiceBuyBox;

// Re-exported so a route file can resolve its service by kind without importing the config twice.
export { serviceByKind };
