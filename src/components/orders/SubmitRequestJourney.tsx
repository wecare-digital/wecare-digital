import React, { useCallback, useEffect, useRef, useState } from 'react';
import { usePublicToast } from '../public/PublicToastProvider';
import { loadRazorpaySdk, type RazorpaySuccess } from '../../lib/razorpayCheckout';
import { colors } from '../../lib/design-tokens';
import { LOGO_URL } from '../../lib/schema';
import SubmitRequestForm, { type SubmitRequestPaymentState, type SubmitRequestQuote } from './SubmitRequestForm';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const ENDPOINT = `${API_BASE}/ecommerce/checkout`;
type Phase = Exclude<SubmitRequestPaymentState, 'starting'>;
type State = { state: Phase; orderNumber: string; requestKey?: string; resumeAmount: number };
type Reply = { state?: unknown; orderNumber?: unknown; requestKey?: unknown; quote?: SubmitRequestQuote; error?: string; resumeAvailable?: unknown; amountPaise?: unknown; options?: unknown };
type GatewayOptions = { keyId: string; orderId: string; amountPaise: number; currency: 'INR'; paymentAttemptId: string };

function parseOptions ( value: unknown, amount: number ): GatewayOptions | null {
  if ( !value || typeof value !== 'object' || !Number.isSafeInteger( amount ) || amount <= 0 ) return null;
  const o = value as Partial<GatewayOptions>;
  if ( typeof o.keyId !== 'string' || !o.keyId.startsWith( 'rzp_' )
    || typeof o.orderId !== 'string' || !o.orderId.startsWith( 'order_' )
    || typeof o.paymentAttemptId !== 'string' || !o.paymentAttemptId
    || o.currency !== 'INR' || o.amountPaise !== amount ) return null;
  return o as GatewayOptions;
}
type Props = { orderNumber: string; accessToken: string; onDone: () => void; onExpired: () => void };

function parseState ( reply: Reply, orderNumber: string ): State | null {
  const phase = reply.state;
  if ( reply.orderNumber !== orderNumber
    || ( phase !== 'idle' && phase !== 'pending' && phase !== 'saving' && phase !== 'received' && phase !== 'failed' ) ) return null;
  const key = typeof reply.requestKey === 'string' && /^[a-f0-9]{32}$/.test( reply.requestKey ) ? reply.requestKey : undefined;
  if ( phase !== 'idle' && !key ) return null;
  const resumeAmount = phase === 'pending' && reply.resumeAvailable === true
    && typeof reply.amountPaise === 'number' && Number.isSafeInteger( reply.amountPaise ) && reply.amountPaise > 0
    ? reply.amountPaise : 0;
  return { state: phase, orderNumber, requestKey: key, resumeAmount };
}

export default function SubmitRequestJourney ( { orderNumber, accessToken, onDone, onExpired }: Props ): React.ReactElement {
  const [ ready, setReady ] = useState( false );
  const [ unavailable, setUnavailable ] = useState( false );
  const [ quote, setQuote ] = useState<SubmitRequestQuote | null>( null );
  const [ quoteUnavailable, setQuoteUnavailable ] = useState( false );
  const [ paymentState, setPaymentState ] = useState<SubmitRequestPaymentState>( 'idle' );
  const [ generation, setGeneration ] = useState( 0 );
  const [ resumeAmount, setResumeAmount ] = useState( 0 );
  const [ modalOpen, setModalOpen ] = useState( false );
  const [ verificationStarted, setVerificationStarted ] = useState( false );
  const modalRef = useRef( false );
  const verifyingRef = useRef( false );
  const { showToast } = usePublicToast();
  const toastRef = useRef( showToast );
  useEffect( () => { toastRef.current = showToast; }, [ showToast ] );
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
    setResumeAmount( state.resumeAmount );
    if ( state.state === 'received' && phaseRef.current !== 'received' ) toastRef.current( 'success' );
    changePhase( state.state );
    return true;
  }, [ changePhase ] );

  const checkStatus = useCallback( async ( initial = false, notify = false ) => {
    if ( checking.current || starting.current ) return;
    checking.current = true;
    try {
      const result = await call( 'request-service-web-status' );
      if ( !mounted.current ) return;
      const state = result.ok ? parseState( result.data, orderNumber ) : null;
      if ( !state ) {
        if ( initial ) setUnavailable( true );
        else if ( notify ) toastRef.current( 'failure' );
        return;
      }
      if ( !applyState( state ) && notify ) toastRef.current( 'blocked' );
      setReady( true );
      setUnavailable( false );
    }
    catch {
      if ( !mounted.current ) return;
      if ( initial ) setUnavailable( true );
      else if ( notify ) toastRef.current( 'failure' );
    }
    finally { checking.current = false; }
  }, [ applyState, call, orderNumber ] );

  useEffect( () => {
    mounted.current = true;
    const initial = window.setTimeout( () => { void checkStatus( true ); }, 0 );
    return () => {
      window.clearTimeout( initial );
      mounted.current = false;
    };
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

  const review = useCallback( async () => {
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
  }, [ call, orderNumber ] );

  useEffect( () => {
    if ( !ready || ( paymentState !== 'idle' && paymentState !== 'failed' ) ) return undefined;
    const timer = window.setTimeout( () => { void review(); }, 0 );
    return () => window.clearTimeout( timer );
  }, [ ready, generation, paymentState, review ] );

  const openGateway = async ( value: unknown, amount: number ) => {
    const options = parseOptions( value, amount );
    if ( !options || modalRef.current || verifyingRef.current || !mounted.current ) return;
    if ( !await loadRazorpaySdk() || !window.Razorpay || !mounted.current ) {
      if ( mounted.current ) toastRef.current( 'failure' );
      return;
    }
    if ( phaseRef.current !== 'pending' || modalRef.current || verifyingRef.current ) return;
    modalRef.current = true;
    setModalOpen( true );
    const close = () => {
      modalRef.current = false;
      if ( mounted.current ) {
        setModalOpen( false );
        void checkStatus();
      }
    };
    try {
      const gateway = new window.Razorpay( {
        key: options.keyId, order_id: options.orderId,
        amount: options.amountPaise, currency: options.currency,
        name: 'WECARE.DIGITAL', description: 'Submit Request', image: LOGO_URL,
        theme: { color: colors.primary },
        handler: async ( result: RazorpaySuccess ) => {
          if ( verifyingRef.current ) return;
          verifyingRef.current = true;
          if ( mounted.current ) setVerificationStarted( true );
          close();
          try {
            // The server verifies signature AND captured payment. The modal's
            // callback is never proof of a completed request.
            const response = await fetch( `${API_BASE}/ecommerce/verify-callback`, {
              method: 'POST', cache: 'no-store',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
              body: JSON.stringify( {
                action: 'verify', razorpay_order_id: result.razorpay_order_id,
                razorpay_payment_id: result.razorpay_payment_id, razorpay_signature: result.razorpay_signature,
              } ),
            } );
            if ( response.status === 401 && mounted.current ) expired.current();
          } catch { /* Independent webhook and owned status polling settle uncertain callbacks. */ }
          finally { if ( mounted.current ) void checkStatus(); }
        },
        modal: { ondismiss: close },
      } );
      gateway.on( 'payment.failed', () => { if ( mounted.current ) void checkStatus(); } );
      gateway.open();
    } catch {
      close();
      if ( mounted.current ) toastRef.current( 'failure' );
    }
  };

  const resumePayment = async () => {
    if ( starting.current || checking.current || modalRef.current || verifyingRef.current || !resumeAmount ) return;
    starting.current = true;
    try {
      const key = acceptedKey.current;
      const result = await call( 'request-service-web-resume' );
      if ( !mounted.current ) return;
      const state = result.ok ? parseState( result.data, orderNumber ) : null;
      if ( !state || state.requestKey !== key || !applyState( state ) ) {
        toastRef.current( 'blocked' );
        return;
      }
      if ( state.state === 'pending' && state.resumeAmount === resumeAmount && result.data.options ) {
        await openGateway( result.data.options, resumeAmount );
      }
    } catch { if ( mounted.current ) toastRef.current( 'failure' ); }
    finally { starting.current = false; if ( mounted.current ) void checkStatus(); }
  };

  const pay = async ( input: { orderNumber: string; note: string; expectedTotalPaise: number } ) => {
    if ( starting.current || checking.current || quoting.current || ambiguous.current
      || !requestKey.current || !quote || quote.orderNumber !== orderNumber
      || input.orderNumber !== orderNumber || input.expectedTotalPaise !== quote.totalPayablePaise ) return;
    starting.current = true;
    acceptedKey.current = '';
    changePhase( 'starting' );

    try {
      const result = await call( 'request-service-web-prepare', {
        requestKey: requestKey.current, note: input.note, expectedTotalPaise: input.expectedTotalPaise,
      } );
      if ( !mounted.current ) return;
      const state = result.ok ? parseState( result.data, orderNumber ) : null;
      if ( state && state.state !== 'idle' && applyState( state ) ) {
        if ( state.state === 'failed' ) {
          previousKey.current = state.requestKey || '';
          setQuoteUnavailable( true );
          requestKey.current = '';
        } else if ( state.state === 'pending' && state.requestKey === requestKey.current
          && result.data.options ) {
          await openGateway( result.data.options, input.expectedTotalPaise );
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

    verifyingRef.current = false;
    setVerificationStarted( false );
    setResumeAmount( 0 );
    setGeneration( value => value + 1 );
    changePhase( 'idle' );
  };

  return (
    <div className="sr-journey">
      { ready ? <>
        <SubmitRequestForm key={ generation } orderNumber={ orderNumber } quote={ quote }
          quoteUnavailable={ quoteUnavailable } paymentState={ paymentState }
          onReview={ () => { void review(); } } onPay={ input => { void pay( input ); } }
          onCheckStatus={ () => { void checkStatus( false, true ); } } onDone={ onDone } onNewRequest={ newRequest }
          resumeAmount={ !modalOpen && !verificationStarted ? resumeAmount : 0 }
          onResume={ () => { void resumePayment(); } } />
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
        .sr-journey-loading p{color:var(--public-text);font-size:15px;line-height:1.5}
        .sr-journey-action{display:flex;align-items:center;justify-content:center;min-height:52px;width:100%;margin-top:10px;padding:10px 18px;border:0;border-radius:var(--public-hover-radius);background:var(--public-lime-tint);color:var(--public-brand-green);font:700 var(--public-responsive-cta-size)/1.35 var(--font-sans);text-align:center;text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;cursor:pointer}
        @media(hover:hover) and (pointer:fine){.sr-journey-action:hover{background:var(--public-button-hover)}}
        .sr-journey-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
      ` }</style>
    </div>
  );
}
