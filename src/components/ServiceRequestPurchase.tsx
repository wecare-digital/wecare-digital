import React, { useEffect, useRef, useState } from 'react';
import PillButton from './PillButton';
import { SERVICES_PRODUCT_ID, serviceByKind } from '../config/services';
import type { ServiceKind } from '../config/services';
import { setServiceLine } from '../lib/cart';
import { getSession, restoreSession } from '../lib/customerAuth';
import { fetchMyRequests, postRequestIntent } from '../lib/serviceRequests';
import type { ServiceRequestRow } from '../lib/serviceRequests';
import { colors, fontSize, radius, space } from '../lib/design-tokens';
import catalog from '../content/wix-catalog.json';

/**
 * THE BUY BOX for Submit Request / Request Amendment (Phase O-1), rendered AFTER the shared
 * ProductPage on the two service pages - ProductPage is shared by twelve pages and is not edited.
 *
 * Flow: signed in (the existing WhatsApp-OTP Cognito session, reused) -> ask the server for an
 * INTENT (no money, no request yet) -> put the one service line in the existing cart -> /cart/,
 * where the ordinary checkout charges it. The copyable request id is created by the server only
 * after the paid order exists, and is shown on /orders.
 *
 * Amount and label come from src/config/services.ts and nothing else; no figure is typed here.
 * The control is disabled only while a request is in flight, never frozen.
 */

type Phase = 'checking' | 'signedOut' | 'ready' | 'busy';

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
  const [ phase, setPhase ] = useState<Phase>( 'checking' );
  const [ token, setToken ] = useState( '' );
  const [ status, setStatus ] = useState( '' );
  const [ targets, setTargets ] = useState<ServiceRequestRow[] | null>( null );
  const [ chosen, setChosen ] = useState( '' );
  const live = useRef( true );
  useEffect( () => () => { live.current = false; }, [] );

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
      if ( kind === 'REQUEST_AMENDMENT' )
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
  const returnPath = service.path;
  const unavailable = catalogueSaysUnavailable( service.variantId );
  const needsTarget = kind === 'REQUEST_AMENDMENT';

  const buy = async () => {
    if ( !token || phase === 'busy' ) return;
    if ( needsTarget && !chosen )
    {
      setStatus( 'Choose the request you want to amend.' );
      return;
    }
    setPhase( 'busy' );
    setStatus( '' );
    const outcome = await postRequestIntent( token, kind, needsTarget ? chosen : undefined );
    if ( !live.current ) return;
    switch ( outcome.kind )
    {
      case 'ok':
        setServiceLine( outcome.intent.variantId, outcome.intent.intentId );
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
        <span className="srp-amount">{ `\u20B9${ service.rupees }` }</span>
        <span className="srp-note"> + a convenience fee, added at checkout</span>
      </p>
      { unavailable && (
        <p className="srp-hint">This service may be temporarily unavailable.</p>
      ) }

      { phase === 'signedOut' && (
        <PillButton
          as="a"
          href={ `/account/sign-in/?return=${ returnPath }` }
          action="Sign in on WhatsApp to continue"
        />
      ) }

      { ( phase === 'ready' || phase === 'busy' ) && needsTarget && targets !== null && (
        targets.length === 0
          ? (
            <p className="srp-p">
              You have no request to amend yet.{ ' ' }
              { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
              <a className="srp-link" href="/submit-request/">Submit a request</a> first.
            </p>
          )
          : (
            <fieldset className="srp-choices">
              <legend className="srp-legend">Which request are you amending?</legend>
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

      { ( phase === 'ready' || phase === 'busy' )
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
