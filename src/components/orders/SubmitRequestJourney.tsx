import React, { useCallback, useEffect, useRef, useState } from 'react';
import SubmitRequestForm, { type SubmitRequestPaymentState, type SubmitRequestQuote } from './SubmitRequestForm';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const ENDPOINT = `${API_BASE}/ecommerce/checkout`;
type Phase = Exclude<SubmitRequestPaymentState, 'starting'>;
type State = { state: Phase; orderNumber: string; requestKey?: string };
type Reply = { state?: unknown; orderNumber?: unknown; requestKey?: unknown; quote?: SubmitRequestQuote; error?: string };
type Props = { orderNumber: string; accessToken: string; onDone: () => void; onExpired: () => void };

function parseState ( reply: Reply, orderNumber: string ): State | null {
  const phase = reply.state;
  if ( reply.orderNumber !== orderNumber
    || ( phase !== 'idle' && phase !== 'pending' && phase !== 'saving' && phase !== 'received' && phase !== 'failed' ) ) return null;
  const key = typeof reply.requestKey === 'string' && /^[a-f0-9]{32}$/.test( reply.requestKey ) ? reply.requestKey : undefined;
  if ( phase !== 'idle' && !key ) return null;
  return { state: phase, orderNumber, requestKey: key };
}

export default function SubmitRequestJourney ( { orderNumber, accessToken, onDone, onExpired }: Props ): React.ReactElement {
  const [ ready, setReady ] = useState( false );
  const [ unavailable, setUnavailable ] = useState( false );
  const [ quote, setQuote ] = useState<SubmitRequestQuote | null>( null );
  const [ quoteUnavailable, setQuoteUnavailable ] = useState( false );
  const [ paymentState, setPaymentState ] = useState<SubmitRequestPaymentState>( 'idle' );
  const [ generation, setGeneration ] = useState( 0 );
  const [ statusMessage, setStatusMessage ] = useState( '' );
  const mounted = useRef( false );
  const checking = useRef( false );
  const starting = useRef( false );
  const quoting = useRef( false );
  const requestKey = useRef( '' );
  const acceptedKey = useRef( '' );
  const previousKey = useRef( '' );
  const ambiguous = useRef( false );
  const phaseRef = useRef<SubmitRequestPaymentState>( 'idle' );
  const expired = useRef( onExpired );
  useEffect( () => { expired.current = onExpired; }, [ onExpired ] );

  const changePhase = useCallback( ( phase: SubmitRequestPaymentState ) => {
    phaseRef.current = phase;
    if ( mounted.current ) setPaymentState( phase );
  }, [] );

  const call = useCallback( async ( action: string, fields: Record<string, unknown> = {} ) => {
    const response = await fetch( ENDPOINT, {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify( { action, selectedOrderNumber: orderNumber, ...fields } ),
    } );
    if ( response.status === 401 ) {
      if ( mounted.current ) expired.current();
      throw new Error( 'SESSION_EXPIRED' );
    }
    const data = await response.json() as Reply;
    return { ok: response.ok, status: response.status, data };
  }, [ accessToken, orderNumber ] );

  const applyState = useCallback( ( state: State ) => {
    // A prior receipt can never complete a newer, unconfirmed payment.
    if ( state.requestKey && state.requestKey === previousKey.current ) return false;
    if ( state.state === 'idle' && ambiguous.current ) return false;
    if ( state.state === 'received' && requestKey.current && !acceptedKey.current
      && state.requestKey !== requestKey.current ) return false;
    if ( state.requestKey ) acceptedKey.current = state.requestKey;
    if ( state.state !== 'idle' ) ambiguous.current = false;
    if ( state.state === 'failed' && phaseRef.current !== 'failed' ) {
      requestKey.current = '';
      setQuote( null );
      setQuoteUnavailable( true );
    }
    changePhase( state.state );
    setStatusMessage( '' );
    return true;
  }, [ changePhase ] );

  const checkStatus = useCallback( async ( initial = false ) => {
    if ( checking.current || starting.current ) return;
    checking.current = true;
    try {
      const result = await call( 'request-service-web-status' );
      if ( !mounted.current ) return;
      const state = result.ok ? parseState( result.data, orderNumber ) : null;
      if ( !state ) {
        if ( initial ) setUnavailable( true );
        else setStatusMessage( 'Status unavailable. Try again.' );
        return;
      }
      if ( !applyState( state ) ) setStatusMessage( 'Payment status is not confirmed yet.' );
      setReady( true );
      setUnavailable( false );
    }
    catch {
      if ( !mounted.current ) return;
      if ( initial ) setUnavailable( true );
      else setStatusMessage( 'Status unavailable. Try again.' );
    }
    finally { checking.current = false; }
  }, [ applyState, call, orderNumber ] );

  useEffect( () => {
    mounted.current = true;
    void checkStatus( true );
    return () => { mounted.current = false; };
  }, [ checkStatus ] );

  useEffect( () => {
    if ( paymentState !== 'pending' && paymentState !== 'saving' ) return undefined;
    const refresh = () => { if ( document.visibilityState === 'visible' ) void checkStatus(); };
    const interval = window.setInterval( refresh, 4000 );
    const timeout = window.setTimeout( () => window.clearInterval( interval ), 5 * 60 * 1000 );
    window.addEventListener( 'focus', refresh );
    document.addEventListener( 'visibilitychange', refresh );
    return () => {
      window.clearInterval( interval );
      window.clearTimeout( timeout );
      window.removeEventListener( 'focus', refresh );
      document.removeEventListener( 'visibilitychange', refresh );
    };
  }, [ checkStatus, paymentState ] );

  const review = async () => {
    if ( quoting.current || starting.current || ambiguous.current ) return;
    quoting.current = true;
    // A definitive failure permits a fresh, reviewed click, not a resend of
    // the old immutable key.
    if ( phaseRef.current === 'failed' ) previousKey.current = acceptedKey.current;
    setQuote( null );
    setQuoteUnavailable( false );
    try {
      const result = await call( 'request-service-web-quote' );
      if ( !mounted.current ) return;
      const { quote: next, requestKey: key } = result.data;
      if ( !result.ok || !next || next.orderNumber !== orderNumber || typeof key !== 'string'
        || !/^[a-f0-9]{32}$/.test( key ) ) {
        setQuoteUnavailable( true );
        return;
      }
      requestKey.current = key;
      setQuote( next );
    }
    catch { if ( mounted.current ) setQuoteUnavailable( true ); }
    finally { quoting.current = false; }
  };

  const pay = async ( input: { orderNumber: string; note: string; expectedTotalPaise: number } ) => {
    if ( starting.current || checking.current || quoting.current || ambiguous.current
      || !requestKey.current || !quote || quote.orderNumber !== orderNumber
      || input.orderNumber !== orderNumber || input.expectedTotalPaise !== quote.totalPayablePaise ) return;
    starting.current = true;
    acceptedKey.current = '';
    changePhase( 'starting' );
    setStatusMessage( '' );
    try {
      const result = await call( 'request-service-web-start', {
        requestKey: requestKey.current, note: input.note, expectedTotalPaise: input.expectedTotalPaise,
      } );
      if ( !mounted.current ) return;
      const state = result.ok ? parseState( result.data, orderNumber ) : null;
      if ( state && state.state !== 'idle' && applyState( state ) ) {
        if ( state.state === 'failed' ) {
          previousKey.current = state.requestKey || '';
          setQuoteUnavailable( true );
          requestKey.current = '';
        }
        return;
      }
      // Only explicit client refusals can unlock a new reviewed payment.
      // Server errors and lost replies may already have created an attempt.
      if ( !result.ok && result.status >= 400 && result.status < 500 ) {
        changePhase( 'failed' );
        requestKey.current = '';
        setQuote( null );
        setQuoteUnavailable( true );
      } else {
        ambiguous.current = true;
        changePhase( 'pending' );
      }
    }
    catch {
      if ( mounted.current ) {
        ambiguous.current = true;
        changePhase( 'pending' );
      }
    }
    finally {
      starting.current = false;
      if ( mounted.current && phaseRef.current === 'pending' ) void checkStatus();
    }
  };

  const newRequest = () => {
    previousKey.current = acceptedKey.current;
    acceptedKey.current = '';
    requestKey.current = '';
    ambiguous.current = false;
    setQuote( null );
    setQuoteUnavailable( false );
    setStatusMessage( '' );
    setGeneration( value => value + 1 );
    changePhase( 'idle' );
  };

  return (
    <div className="sr-journey">
      { ready ? <>
        <SubmitRequestForm key={ generation } orderNumber={ orderNumber } quote={ quote }
          quoteUnavailable={ quoteUnavailable } paymentState={ paymentState }
          onReview={ () => { void review(); } } onPay={ input => { void pay( input ); } }
          onCheckStatus={ () => { void checkStatus(); } } onDone={ onDone } onNewRequest={ newRequest } />
        { statusMessage && <p className="sr-journey-status" role="status">{ statusMessage }</p> }
      </> : <section className="sr-journey-loading" aria-label="Submit Request">
        <h2>Submit Request</h2>
        <p role="status">{ unavailable ? 'Submit Request is temporarily unavailable.' : 'Checking request status…' }</p>
        { unavailable && <button type="button" className="sr-journey-action" onClick={ () => { void checkStatus( true ); } }>Try again</button> }
        <button type="button" className="sr-journey-action" onClick={ onDone }>Back to orders</button>
      </section> }
      <style jsx>{ `
        .sr-journey{width:100%;max-width:440px;min-width:0;margin:0 auto}
        .sr-journey-loading{padding:24px 22px;margin:0 auto;color:var(--public-brand-green)}
        .sr-journey-loading h2{font-size:26px;margin:0 0 12px}
        .sr-journey-loading p,.sr-journey-status{color:var(--public-text);font-size:15px;line-height:1.5}
        .sr-journey-status{margin:0 auto 24px;padding:0 22px;max-width:440px}
        .sr-journey-action{display:flex;align-items:center;justify-content:center;min-height:52px;width:100%;margin-top:10px;padding:10px 18px;border:0;border-radius:var(--public-hover-radius);background:var(--public-lime-tint);color:var(--public-brand-green);font:700 var(--public-responsive-cta-size)/1.35 var(--font-sans);text-align:center;text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;cursor:pointer}
        .sr-journey-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
      ` }</style>
    </div>
  );
}
