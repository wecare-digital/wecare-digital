import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import PillButton from './PillButton';
import { SERVICES_PRODUCT_ID, serviceByKind } from '../config/services';
import type { ServiceKind } from '../config/services';
import { setServiceLine } from '../lib/cart';
import { getSession, restoreSession } from '../lib/customerAuth';
import { SIGN_IN_PATH, goToServiceAction } from '../lib/serviceEntry';
import { fetchServicePrices } from '../lib/servicePricing';
import type { ServicePrice } from '../lib/servicePricing';
import { fetchMyRequests, postRequestIntent } from '../lib/serviceRequests';
import type { ServiceRequestRow } from '../lib/serviceRequests';
import { colors, fontSize, radius, space } from '../lib/design-tokens';
import catalog from '../content/wix-catalog.json';

/**
 * THE BUY BOX for all four services, rendered AFTER the shared ProductPage on the four service
 * pages - ProductPage is shared by twelve pages and is not edited.
 *
 * Flow: signed in (the existing WhatsApp-OTP Cognito session, reused) -> ask the server for an
 * INTENT (no money, no request yet) -> put the one service line in the existing cart -> /cart/,
 * where the ordinary checkout charges it. The copyable request id is created by the server only
 * after the paid order exists, and is shown on /orders.
 *
 * WHETHER A TARGET REQUEST IS ASKED FOR comes from `service.needsTarget`, never from a comparison
 * against one kind: Request Amendment, Drop Docs and Vault all work on a request the caller has
 * already submitted, and the wording below is driven off `service.label` so one code path reads
 * correctly for all three. The server is the authority either way
 * (service_requests.py TARGET_REQUIRED_KINDS); this flag only decides what the form asks for.
 *
 * THE AMOUNT IS WIX'S, READ LIVE, AND NO FIGURE IS TYPED ANYWHERE IN THIS FILE. Owner decision
 * 2026-10-08: a price must be changeable in Wix with no deploy. `fetchServicePrices()` is called
 * on mount, INDEPENDENTLY of the session fetch, because an anonymous visitor has to be able to
 * read the price — it is what decides whether they sign in at all. Each page asks for its OWN
 * slug (`service.slug`), which is what keeps four pages showing four prices.
 *
 * WHEN THE PRICE IS UNKNOWN, NOTHING CAN BE BOUGHT. While loading, a neutral placeholder rather
 * than a number. If the live price cannot be resolved the card shows "This service may be
 * temporarily unavailable." and BOTH calls to action are suppressed, so no path reaches payment
 * with a guessed price. The separate committed-catalogue stock hint remains NON-BLOCKING, as it
 * always has been — see the comment on `unavailable` below for why that distinction is kept.
 *
 * The control is disabled only while a request is in flight, never frozen.
 */

type Phase = 'checking' | 'signedOut' | 'ready' | 'busy';

/** 'loading' until the one price call answers; then the slug's own live price, or unavailable. */
type PriceState = 'loading' | ServicePrice;

interface Props {
  kind: ServiceKind;
}

/** The committed catalogue's stock hint. Non-blocking: checkout's 409 is the authority. */
function catalogueSaysUnavailable ( variantId: string ): boolean {
  const products = ( catalog as { products?: Array<Record<string, unknown>> } ).products || [];
  const product = products.find( row => row.id === SERVICES_PRODUCT_ID );
  const variants = ( product?.variants as Array<{ id: string; inStock: boolean }> | undefined ) || [];
  const variant = variants.find( row => row.id === variantId );
  return !!variant && variant.inStock === false;
}

const ServiceRequestPurchase: React.FC<Props> = ( { kind } ) => {
  const service = serviceByKind( kind );
  const router = useRouter();
  const [ phase, setPhase ] = useState<Phase>( 'checking' );
  const [ token, setToken ] = useState( '' );
  const [ status, setStatus ] = useState( '' );
  const [ targets, setTargets ] = useState<ServiceRequestRow[] | null>( null );
  const [ chosen, setChosen ] = useState( '' );
  const [ price, setPrice ] = useState<PriceState>( 'loading' );
  const live = useRef( true );
  useEffect( () => () => { live.current = false; }, [] );

  // The price, on its own effect and its own fetch. Deliberately NOT inside the session effect:
  // a signed-out visitor must see the amount, and `fetchServicePrices` never throws and never
  // returns a partial map, so this needs no error branch of its own.
  useEffect( () => {
    ( async () => {
      const prices = await fetchServicePrices();
      if ( !live.current ) return;
      const slug = serviceByKind( kind )?.slug;
      setPrice( ( slug && prices[ slug ] ) || { available: false } );
    } )();
  }, [ kind ] );

  useEffect( () => {
    ( async () => {
      let session = getSession();
      if ( !session )
      {
        try { session = await restoreSession(); }
        catch { session = null; }
      }
      if ( !live.current ) return;
      if ( !session ) { setPhase( 'signedOut' ); return; }
      setToken( session.accessToken );
      setPhase( 'ready' );
      if ( serviceByKind( kind )?.needsTarget )
      {
        const outcome = await fetchMyRequests( session.accessToken, [] );
        if ( !live.current ) return;
        if ( outcome.kind === 'ok' )
        {
          setTargets( outcome.requests.filter( row => row.kind === 'SUBMIT_REQUEST' ) );
        }
        else if ( outcome.kind === 'expired' ) setPhase( 'signedOut' );
        else setStatus( 'Your requests could not be loaded right now. Try again shortly.' );
      }
    } )();
  }, [ kind ] );

  if ( !service ) return null;
  const needsTarget = service.needsTarget;
  const priced = price !== 'loading' && price.available ? price : null;
  const priceUnavailable = price !== 'loading' && !price.available;
  // Two reasons to show the one honest sentence, and they are NOT equally blocking.
  //
  // `catalogueSaysUnavailable` reads the COMMITTED snapshot in src/content/wix-catalog.json, and
  // that snapshot currently records all four variants as out of stock while all four are on sale.
  // It has always been a non-blocking hint here — "checkout's 409 is the authority" — and it
  // stays one: suppressing the CTA on it would take every service off sale on a stale file, which
  // is a far worse failure than showing a cautious sentence.
  //
  // An UNRESOLVED LIVE PRICE is different, and it does block. There is no committed figure to
  // fall back on any more, so with no price there is nothing honest to charge, and the only safe
  // answer is to offer no way to pay at all.
  const unavailable = catalogueSaysUnavailable( service.variantId ) || priceUnavailable;
  const sellable = priced !== null;

  const buy = async () => {
    if ( !token || phase === 'busy' || !priced ) return;
    if ( needsTarget && !chosen )
    {
      setStatus( `Choose the request this ${ service.label } is for.` );
      return;
    }
    setPhase( 'busy' );
    setStatus( '' );
    const outcome = await postRequestIntent( token, kind, needsTarget ? chosen : undefined );
    if ( !live.current ) return;
    switch ( outcome.kind )
    {
      case 'ok':
        // Wix's live paise, so the cart row reads the same figure the card promised. The
        // checkout re-prices the line against Wix anyway; this is display continuity, not the
        // amount that will be charged.
        setServiceLine( outcome.intent.variantId, outcome.intent.intentId, priced.paise );
        window.location.assign( '/cart/' );
        return;
      case 'notFound':
        setStatus( 'We could not find that request on your account.' );
        break;
      case 'refused':
        setStatus( outcome.message );
        break;
      case 'expired':
        setPhase( 'signedOut' );
        return;
      case 'rate':
        setStatus( 'Too many requests. Wait a moment and try again.' );
        break;
      case 'failed':
        setStatus( 'We could not start this right now. Nothing has been charged. Try again.' );
        break;
      default: { const unhandled: never = outcome; void unhandled; }
    }
    setPhase( 'ready' );
  };

  return (
    <section className="srp" aria-labelledby="srp-title">
      <h2 className="srp-title" id="srp-title">{ service.label }</h2>
      <p className="srp-price">
        <span className="srp-amount" data-wc-no-translate>
          { priced ? `\u20B9${ priced.rupees }` : '\u2014' }
        </span>
        { /* Unchanged wording, and still truthful: the fee and the 18% GST on it are added by
             the backend checkout (checkout_pricing), never by this card. */ }
        <span className="srp-note"> + a convenience fee, added at checkout</span>
      </p>
      { unavailable && (
        <p className="srp-hint">This service may be temporarily unavailable.</p>
      ) }

      { /* THE ONE LOGIN. The click now routes through `goToServiceAction` — the single gate every
           service/product/contribute CTA uses — instead of this component hand-building a
           `?return=` URL, so one place owns the signed-in/signed-out decision and the pending
           action is stashed out of band. It stays an <a> with a real `href`: the accessible role,
           open-in-new-tab, and the no-JS path all survive, and the handler only takes over when
           JavaScript is running. The visible copy is unchanged.
           Rendered only when the service is sellable — a sign-in that leads to a price we could
           not resolve is a dead end. */ }
      { phase === 'signedOut' && sellable && (
        <PillButton
          as="a"
          href={ `${ SIGN_IN_PATH }?return=${ encodeURIComponent( service.path ) }` }
          action="Sign in on WhatsApp to continue"
          onClick={ event => {
            event.preventDefault();
            void goToServiceAction( router, {
              destination: service.path,
              action: {
                kind: service.slug, productId: SERVICES_PRODUCT_ID,
                variantId: service.variantId, label: service.label,
              },
            } );
          } }
        />
      ) }

      { ( phase === 'ready' || phase === 'busy' ) && needsTarget && targets !== null && (
        targets.length === 0
          ? (
            <p className="srp-p">
              { service.label } works on a request you have already submitted, and you have none
              yet.{ ' ' }
              { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
              <a className="srp-link" href="/submit-request/">Submit a request</a> first.
            </p>
          )
          : (
            <fieldset className="srp-choices">
              <legend className="srp-legend">
                { `Which request is this ${ service.label } for?` }
              </legend>
              { targets.map( row => (
                <label className="srp-choice" key={ row.requestId }>
                  <input
                    type="radio"
                    name="srp-target"
                    value={ row.requestId }
                    checked={ chosen === row.requestId }
                    onChange={ () => setChosen( row.requestId ) }
                  />
                  <span data-wc-no-translate>{ row.requestId }</span>
                </label>
              ) ) }
            </fieldset>
          )
      ) }

      { /* `sellable` is the new condition, and it is the fail-closed rail: with no live price
           there is no "Continue to pay", so no path can reach the checkout on a guessed figure. */ }
      { sellable && ( phase === 'ready' || phase === 'busy' )
        && !( needsTarget && ( targets === null || targets.length === 0 ) ) && (
        <PillButton
          action={ `Continue to pay for ${ service.label }` }
          onClick={ buy }
          busy={ phase === 'busy' }
          disabled={ phase === 'busy' }
        />
      ) }

      <p className="srp-status" role="status" aria-live="polite">{ status }</p>

      <style jsx>{ `
        .srp{display:flex;flex-direction:column;gap:${ space[ 3 ] }px;margin-block:${ space[ 8 ] }px;
          padding:${ space[ 6 ] }px;border:1px solid ${ colors.border };border-radius:${ radius.lg }px;
          max-inline-size:640px;margin-inline:auto}
        .srp-title{margin:0;font-size:${ fontSize.h3 }px;font-weight:700;color:${ colors.grey900 }}
        .srp-price{margin:0;font-size:${ fontSize.base }px;color:${ colors.text }}
        .srp-amount{font-weight:700}
        .srp-note,.srp-hint{color:${ colors.textSecondary }}
        .srp-hint,.srp-p,.srp-status{margin:0;font-size:${ fontSize.md }px}
        .srp-status:empty{display:none}
        .srp-choices{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:${ space[ 2 ] }px}
        .srp-legend{font-size:${ fontSize.md }px;color:${ colors.textSecondary };margin-block-end:${ space[ 2 ] }px}
        .srp-choice{display:flex;align-items:center;gap:${ space[ 2 ] }px;font-size:${ fontSize.base }px}
        .srp-choice input:focus-visible,.srp-link:focus-visible{outline:3px solid ${ colors.primary };outline-offset:2px}
        .srp-link{color:${ colors.primary };text-decoration:underline}
      ` }</style>
    </section>
  );
};

export default ServiceRequestPurchase;
