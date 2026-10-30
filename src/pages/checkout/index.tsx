import Head from 'next/head';
import { useRouter } from 'next/router';
import React, { useCallback, useState } from 'react';

import RotatingHero from '../../components/RotatingHero';
import { readCart } from '../../lib/cart';
import {
  CHECKOUT_PATH,
  goToServiceAction,
  type CheckoutChannel,
} from '../../lib/serviceEntry';
import { buildPageTitle } from '../../lib/page-title';

/**
 * The ONE payment-method decision after cart review.
 *
 * Route/product pages expose only Checkout. /cart/ exposes only Proceed. This page is the sole
 * place a customer chooses HOW to pay. The choice is stashed out of band and the existing single
 * WhatsApp-OTP gate returns to /cart/, where checkout resumes against the same catalogue basket and
 * same session-owned ContactsTable customer. No price, customer id or provider identity rides in
 * the URL.
 */
export default function CheckoutMethodPage (): React.ReactElement {
  const router = useRouter();
  const [ busy, setBusy ] = useState<CheckoutChannel | null>( null );
  const [ error, setError ] = useState( '' );

  const choose = useCallback( async ( channel: CheckoutChannel ) => {
    if ( busy ) return;
    if ( readCart().length === 0 ) {
      await router.push( CHECKOUT_PATH );
      return;
    }
    setBusy( channel );
    setError( '' );
    try {
      await goToServiceAction( router, {
        destination: CHECKOUT_PATH,
        action: { kind: 'checkout', channel },
      } );
    } catch {
      setBusy( null );
      setError( 'We could not continue checkout. Nothing has been charged. Please try again.' );
    }
  }, [ busy, router ] );

  return (
    <>
      <Head>
        <title>{ buildPageTitle( 'Choose payment method' ) }</title>
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
        <section className="checkout-method" aria-label="Payment method">
          <div className="checkout-method-actions">
            <button
              type="button"
              className="checkout-auth-action checkout-auth-primary"
              disabled={ Boolean( busy ) }
              aria-busy={ busy === 'whatsapp' ? 'true' : undefined }
              onClick={ () => { void choose( 'whatsapp' ); } }
            >
              { busy === 'whatsapp' ? 'Preparing…' : 'Pay on WhatsApp' }
            </button>
            <button
              type="button"
              className="checkout-auth-action"
              disabled={ Boolean( busy ) }
              aria-busy={ busy === 'website' ? 'true' : undefined }
              onClick={ () => { void choose( 'website' ); } }
            >
              { busy === 'website' ? 'Preparing…' : 'Pay here' }
            </button>
          </div>

          { error && <p className="checkout-method-error" role="alert">{ error }</p> }

          <style jsx>{`
            .checkout-method{
              width:min(100%,560px);max-width:100%;display:grid;gap:18px;margin:0;
              padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);
              border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);
              border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);
              box-sizing:border-box;
            }
            .checkout-method-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px}
            .checkout-auth-action{
              min-height:48px;min-width:48px;padding:8px 14px;border:0;border-radius:10px;
              background:var(--public-lime-tint);color:var(--public-brand-green);
              font:600 var(--public-cta-font-size)/1.35 var(--font-sans);
              text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;
              touch-action:manipulation;cursor:pointer;
              transition:background-color .18s,transform .18s,box-shadow .18s;
            }
            .checkout-auth-primary{font-weight:700}
            .checkout-auth-action:hover{background:var(--public-brand-lime);transform:translateY(-1px);box-shadow:var(--public-lift-shadow);text-decoration-color:transparent}
            .checkout-auth-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
            .checkout-auth-action:disabled{opacity:.6;cursor:wait;transform:none;box-shadow:none}
            .checkout-method-error{margin:0;padding:11px 13px;border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;background:var(--public-lime-tint);color:var(--public-text);font-size:14px;font-weight:600;line-height:1.4}
            @media(max-width:767px){
              .checkout-method{width:100%;padding:28px 20px max(30px,env(safe-area-inset-bottom));border-radius:20px}
              .checkout-method-actions{display:grid;grid-template-columns:1fr;width:100%}
              .checkout-auth-action{width:100%}
            }
            @media(prefers-reduced-motion:reduce){
              .checkout-auth-action{transition:none}
              .checkout-auth-action:hover{transform:none;box-shadow:none}
            }
          `}</style>
        </section>
      </RotatingHero>
    </>
  );
}
