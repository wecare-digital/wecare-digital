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
        frame="Choose"
        words={ [ { word: 'payment', tint: '#e0f7c8', dot: '#3da35a' } ] }
        sub="Your cart stays the same. Choose where you want to complete payment."
        ariaLabel="Choose payment method"
      >
        <section className="checkout-method" aria-label="Payment method">
          <button
            type="button"
            className="checkout-method-card checkout-method-primary"
            disabled={ Boolean( busy ) }
            aria-busy={ busy === 'whatsapp' }
            onClick={ () => { void choose( 'whatsapp' ); } }
          >
            <strong>{ busy === 'whatsapp' ? 'Preparing…' : 'WhatsApp' }</strong>
            <span>Send the order to your verified WhatsApp number and complete Review and Pay there.</span>
          </button>

          <button
            type="button"
            className="checkout-method-card"
            disabled={ Boolean( busy ) }
            aria-busy={ busy === 'website' }
            onClick={ () => { void choose( 'website' ); } }
          >
            <strong>{ busy === 'website' ? 'Preparing…' : 'Here' }</strong>
            <span>Complete secure payment on WECARE.DIGITAL.</span>
          </button>

          <p className="checkout-method-note">
            You sign in only once. Both methods use the same cart, customer and final Orders history.
          </p>
          { error && <p className="checkout-method-error" role="alert">{ error }</p> }

          <style jsx>{`
            .checkout-method{
              width:min(100%,720px);display:grid;gap:14px;margin-top:26px;
            }
            .checkout-method-card{
              width:100%;min-height:92px;padding:18px 20px;text-align:left;
              display:grid;gap:5px;border:2px solid var(--public-brand-green);
              border-radius:18px;background:#fff;color:var(--public-brand-green);
              cursor:pointer;transition:transform .2s,box-shadow .2s,background-color .2s;
              font:inherit;
            }
            .checkout-method-card strong{font-size:18px;line-height:1.25}
            .checkout-method-card span{
              color:var(--public-muted);font-size:15px;line-height:1.45;
            }
            .checkout-method-primary{background:var(--public-brand-lime)}
            .checkout-method-card:hover:not(:disabled){
              transform:translateY(-2px);box-shadow:var(--public-lift-shadow);
            }
            .checkout-method-card:focus-visible{
              outline:3px solid var(--public-brand-green);outline-offset:3px;
            }
            .checkout-method-card:disabled{opacity:.55;cursor:default}
            .checkout-method-note{
              margin:4px 0 0;color:var(--public-muted);font-size:14px;line-height:1.5;
            }
            .checkout-method-error{margin:0;color:#b91c1c;font-size:14px;line-height:1.5}
            @media(prefers-reduced-motion:reduce){
              .checkout-method-card{transition:background-color .2s}
              .checkout-method-card:hover:not(:disabled){transform:none;box-shadow:none}
            }
          `}</style>
        </section>
      </RotatingHero>
    </>
  );
}
