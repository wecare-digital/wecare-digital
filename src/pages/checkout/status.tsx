import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import RotatingHero from '../../components/RotatingHero';
import { getSession, restoreSession } from '../../lib/customerAuth';
import { orderPagePath } from '../../lib/orderPage';
import { settlePaidCheckout } from '../../lib/checkoutHandoff';
import { amountLabel, isInFlight, isOrderNumber, isPaid, isRetryable } from '../../lib/paymentVocabulary';
import { trackMetaPurchase, type PaidCatalogEvent } from '../../lib/metaPixel';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const CHECKOUT_STATUS_URL = `${ API_BASE }/ecommerce/checkout/status`;
const POLL_INTERVAL_MS = 4000;
const POLL_CEILING_MS = 5 * 60 * 1000;

type View = 'confirming' | 'paid' | 'finalizing' | 'failed' | 'unavailable';

interface AttemptView {
  status?: string;
  orderNumber?: string | null;
  amountPaise?: number | null;
  currency?: string | null;
  catalogEvent?: PaidCatalogEvent;
}

export function viewFor ( status: string | undefined, orderNumber: string | null | undefined ): View {
  if ( isPaid( status ) ) return isOrderNumber( orderNumber ) ? 'paid' : 'finalizing';
  if ( isRetryable( status ) ) return 'failed';
  if ( isInFlight( status ) ) return 'confirming';
  return 'unavailable';
}

function attemptIdFromUrl (): string {
  if ( typeof window === 'undefined' ) return '';
  return String( new URLSearchParams( window.location.search ).get( 'a' ) || '' ).trim();
}

const COPY: Record<View, { title: string; body: string }> = {
  confirming: {
    title: 'Confirming your payment',
    body: 'We are checking with the payment provider. This page updates on its own.',
  },
  paid: {
    title: 'Payment received',
    body: 'Your order is confirmed. We will be in touch on WhatsApp.',
  },
  finalizing: {
    title: 'Payment received',
    body: 'We are creating your order now. Do not pay again.',
  },
  failed: {
    title: "Payment wasn't completed",
    body: 'No order was created. You can start again whenever you are ready.',
  },
  unavailable: {
    title: 'Nothing to show here',
    body: 'We could not find a payment to confirm. If you have just paid, check WhatsApp for your confirmation.',
  },
};

export default function CheckoutStatus (): React.ReactElement {
  const [ view, setView ] = useState<View>( 'confirming' );
  const [ orderNumber, setOrderNumber ] = useState( '' );
  const [ amount, setAmount ] = useState( '' );
  const [ stalled, setStalled ] = useState( false );
  const handedOffRef = useRef( false );
  const router = useRouter();

  const poll = useCallback( async ( attemptId: string ): Promise<boolean> => {
    let session;
    try {
      session = getSession() || await restoreSession();
    } catch {
      return false;
    }
    if ( !session ) {
      window.location.replace( '/auth?return=/orders/' );
      return true;
    }

    try {
      const response = await fetch( CHECKOUT_STATUS_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${ session.accessToken }`,
        },
        body: JSON.stringify( { action: 'status', paymentAttemptId: attemptId } ),
      } );
      if ( response.status === 401 ) {
        window.location.replace( '/auth?return=/orders/' );
        return true;
      }
      if ( !response.ok ) {
        setView( current => current === 'finalizing' ? current : 'unavailable' );
        return false;
      }

      const data = await response.json() as { attempt?: AttemptView };
      const attempt = data.attempt || {};
      const nextView = viewFor( attempt.status, attempt.orderNumber );
      if ( isPaid( attempt.status ) ) settlePaidCheckout( attemptId );
      if ( nextView === 'paid' ) {
        setOrderNumber( String( attempt.orderNumber ) );
        setAmount( amountLabel( attempt.amountPaise, attempt.currency ) );
        trackMetaPurchase( attemptId, attempt.catalogEvent );
      }
      setView( nextView );
      return nextView !== 'confirming' && nextView !== 'finalizing';
    } catch {
      return false;
    }
  }, [] );

  useEffect( () => {
    const attemptId = attemptIdFromUrl();
    if ( !attemptId ) {
      setView( 'unavailable' );
      return undefined;
    }

    let stopped = false;
    const startedAt = Date.now();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async (): Promise<void> => {
      if ( stopped ) return;
      const done = await poll( attemptId );
      if ( stopped || done ) return;
      if ( Date.now() - startedAt > POLL_CEILING_MS ) {
        setStalled( true );
        return;
      }
      timer = setTimeout( tick, POLL_INTERVAL_MS );
    };
    void tick();
    return () => {
      stopped = true;
      if ( timer ) clearTimeout( timer );
    };
  }, [ poll ] );

  useEffect( () => {
    if ( view !== 'paid' || !orderNumber || handedOffRef.current ) return;
    handedOffRef.current = true;
    void router.replace( orderPagePath( orderNumber ) ).catch( () => undefined );
  }, [ orderNumber, router, view ] );

  const copy = COPY[ view ];

  return (
    <>
      <Head>
        <title>{ `${ copy.title } | WECARE.DIGITAL` }</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <RotatingHero
        frame={ copy.title }
        words={ [ { word: 'your payment', tint: '#e0f7c8', dot: '#3da35a' } ] }
        sub={ copy.body }
        ariaLabel="Checkout status"
      >
        <section className="co-card" role="status" aria-live="polite">
          { view === 'paid'
            ? <div className="co-mark co-mark-paid" aria-hidden="true"><i className="co-tick" /></div>
            : <div className={ `co-mark co-mark-${ view }` } aria-hidden="true" /> }

          { view === 'paid' && (
            <dl className="co-facts">
              <div className="co-fact">
                <dt>Order number</dt>
                <dd data-wc-no-translate="true">{ orderNumber }</dd>
              </div>
              { amount && (
                <div className="co-fact">
                  <dt>Amount paid</dt>
                  <dd data-wc-no-translate="true">{ amount }</dd>
                </div>
              ) }
            </dl>
          ) }

          { view === 'paid' && (
            <div className="co-actions">
              <Link className="co-btn co-btn-primary" href={ orderPagePath( orderNumber ) }>View your order</Link>
              <Link className="co-btn co-btn-quiet" href="/shop/">Continue shopping</Link>
            </div>
          ) }

          { view === 'finalizing' && !stalled && (
            <p className="co-note">Keep this page open. It usually takes a few seconds.</p>
          ) }

          { stalled && ( view === 'confirming' || view === 'finalizing' ) && (
            <>
              <p className="co-note">This is taking longer than usual. Your orders page shows the latest status.</p>
              <div className="co-actions">
                <Link className="co-btn co-btn-primary" href="/orders/">Check your orders</Link>
              </div>
            </>
          ) }

          { view === 'failed' && (
            <div className="co-actions">
              <Link className="co-btn co-btn-primary" href="/shop/">Start again</Link>
              <Link className="co-btn co-btn-quiet" href="/">Back to home</Link>
            </div>
          ) }

          { view === 'unavailable' && (
            <div className="co-actions">
              <Link className="co-btn co-btn-quiet" href="/shop/">Return to the store</Link>
            </div>
          ) }
        </section>

        <style jsx>{`
          .co-card{width:100%;max-width:700px;margin:0}
          .co-mark{inline-size:56px;block-size:56px;margin-block-end:24px;border-radius:50%}
          .co-mark-confirming,.co-mark-finalizing{border:3px solid rgba(0,0,0,.12);border-block-start-color:#3da35a;animation:co-spin 900ms linear infinite}
          .co-mark-paid{background:#3da35a;display:flex;align-items:center;justify-content:center}
          .co-tick{inline-size:10px;block-size:20px;box-sizing:border-box;border-right:3px solid #fff;border-bottom:3px solid #fff;transform:rotate(45deg) translateY(-2px)}
          .co-mark-failed,.co-mark-unavailable{background:rgba(0,0,0,.06)}
          .co-facts{margin:0;display:flex;flex-wrap:wrap;gap:24px 48px}
          .co-fact{display:flex;flex-direction:column;gap:6px}
          .co-facts dt{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--public-muted)}
          .co-facts dd{margin:0;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
          .co-note{margin:0;font-size:16px;line-height:1.55;color:var(--public-muted)}
          .co-actions{margin-block-start:28px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
          .co-card :global(.co-btn){display:inline-flex;align-items:center;justify-content:center;min-height:var(--public-cta-height);padding-inline:26px;border-radius:var(--public-cta-radius);font-family:inherit;font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);text-decoration:none;line-height:normal;transition:background-color .2s,transform .2s,box-shadow .2s}
          .co-card :global(.co-btn-primary){background:var(--public-brand-lime);border:var(--public-cta-border) solid var(--public-brand-green);color:var(--public-brand-green)}
          .co-card :global(.co-btn-primary:hover){background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          .co-card :global(.co-btn-quiet){background:#fff;border:var(--public-cta-border) solid var(--public-brand-lime);color:var(--public-brand-green)}
          .co-card :global(.co-btn-quiet:hover){background:rgba(209,244,112,.22)}
          .co-card :global(.co-btn:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}
          @keyframes co-spin{to{transform:rotate(360deg)}}
          @media(prefers-reduced-motion:reduce){.co-mark-confirming,.co-mark-finalizing{animation:none}.co-card :global(.co-btn){transition:none}.co-card :global(.co-btn:hover){transform:none;box-shadow:none}}
        `}</style>
      </RotatingHero>
    </>
  );
}
