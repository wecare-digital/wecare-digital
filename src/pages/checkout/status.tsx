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

const COPY: Record<View, { title: string }> = {
  confirming: { title: 'Confirming your payment' },
  paid: { title: 'Payment received' },
  finalizing: { title: 'Payment received' },
  failed: { title: "Payment wasn't completed" },
  unavailable: { title: 'Nothing to show here' },
};

export default function CheckoutStatus (): React.ReactElement {
  const [ view, setView ] = useState<View>( 'confirming' );
  const [ orderNumber, setOrderNumber ] = useState( '' );
  const [ amount, setAmount ] = useState( '' );
  const [ stalled, setStalled ] = useState( false );
  const [ vaultReturnFile, setVaultReturnFile ] = useState( '' );
  const handedOffRef = useRef( false );
  const router = useRouter();

  useEffect( () => {
    try {
      const file = window.sessionStorage.getItem( 'wecare.vault.websiteCheckoutReturnFile' ) || '';
      if ( /^[A-Za-z0-9_-]{1,120}$/.test( file ) ) setVaultReturnFile( file );
    } catch { /* A return hint never establishes payment or file ownership. */ }
  }, [] );

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
    // A website Vault renewal returns to its own authenticated document instead.
    // Other completed purchases go to the one compact Orders history; no receipt
    // expansion or per-order selector is queued.
    if ( view !== 'paid' || !orderNumber || handedOffRef.current || vaultReturnFile ) return;
    handedOffRef.current = true;
    void router.replace( orderPagePath( orderNumber ) ).catch( () => undefined );
  }, [ orderNumber, router, view, vaultReturnFile ] );

  const copy = COPY[ view ];

  return (
    <>
      <Head>
        <title>{ `${ copy.title } | WECARE.DIGITAL` }</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
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
        <section className="co-card" role="status" aria-live="polite">
          <h2 className="co-title">{ copy.title }</h2>
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
              { vaultReturnFile && (
                <Link className="co-auth-action co-auth-primary"
                  href={ { pathname: '/vault/', query: { file: vaultReturnFile } } }
                  onClick={ () => { try { window.sessionStorage.removeItem( 'wecare.vault.websiteCheckoutReturnFile' ); } catch { /* best effort */ } } }>
                  Return to Vault · Download
                </Link>
              ) }
              <Link className="co-auth-action" href={ orderPagePath( orderNumber ) }>View orders</Link>
            </div>
          ) }

          { view === 'finalizing' && !stalled && (
            <p className="co-note">Do not pay again.</p>
          ) }

          { stalled && ( view === 'confirming' || view === 'finalizing' ) && (
            <div className="co-actions">
              <Link className="co-auth-action co-auth-primary" href="/orders/">Orders</Link>
            </div>
          ) }

          { view === 'failed' && (
            <div className="co-actions">
              <Link className="co-auth-action co-auth-primary" href="/checkout/">Retry</Link>
            </div>
          ) }

          { view === 'unavailable' && (
            <div className="co-actions">
              <Link className="co-auth-action" href="/orders/">Orders</Link>
            </div>
          ) }
        </section>

        <style jsx>{`
          .co-card{width:min(100%,560px);max-width:100%;margin:0;padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);box-sizing:border-box;color:var(--public-text);font-family:var(--font-sans)}
          .co-title{margin:0 0 24px;color:var(--public-text);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking)}
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
          .co-actions{margin-block-start:28px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
          .co-card :global(.co-auth-action){display:inline-flex;align-items:center;justify-content:center;min-height:var(--public-cta-height);min-width:48px;padding:8px 14px;border:0;border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);font:600 var(--public-cta-font-size)/1.35 var(--font-sans);text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;touch-action:manipulation;cursor:pointer;transition:background-color .18s,transform .18s,box-shadow .18s}
          .co-card :global(.co-auth-primary){font-weight:700}
          .co-card :global(.co-auth-action:hover){background:var(--public-brand-lime);transform:translateY(-1px);box-shadow:var(--public-lift-shadow);text-decoration-color:transparent}
          .co-card :global(.co-auth-action:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}
          @keyframes co-spin{to{transform:rotate(360deg)}}
          @media(max-width:767px){.co-card{width:100%;padding:24px 18px max(24px,env(safe-area-inset-bottom));border-radius:20px}.co-title{margin-bottom:18px;font-size:var(--public-mobile-card-size)}.co-mark{inline-size:48px;block-size:48px;margin-block-end:18px}.co-actions{display:grid;grid-template-columns:1fr;width:100%;margin-block-start:22px}.co-card :global(.co-auth-action){width:100%}}
          @media(prefers-reduced-motion:reduce){.co-mark-confirming,.co-mark-finalizing{animation:none}.co-card :global(.co-auth-action){transition:none}.co-card :global(.co-auth-action:hover){transform:none;box-shadow:none}}
        `}</style>
      </RotatingHero>
    </>
  );
}
