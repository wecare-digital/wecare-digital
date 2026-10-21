import Head from 'next/head';
import { useRouter } from 'next/router';
import React, { useCallback, useState } from 'react';

import RotatingHero from '../../components/RotatingHero';
import CheckoutAction from '../../components/CheckoutAction';
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
          <div className="checkout-method-actions">
            <CheckoutAction
              disabled={ Boolean( busy ) }
              busy={ busy === 'whatsapp' }
              ariaLabel="Pay on WhatsApp"
              onClick={ () => { void choose( 'whatsapp' ); } }
            >
              { busy === 'whatsapp' ? 'Preparing…' : 'Pay on WhatsApp' }
            </CheckoutAction>
            <CheckoutAction
              disabled={ Boolean( busy ) }
              busy={ busy === 'website' }
              ariaLabel="Pay here"
              onClick={ () => { void choose( 'website' ); } }
            >
              { busy === 'website' ? 'Preparing…' : 'Pay here' }
            </CheckoutAction>
          </div>

          <p className="checkout-method-note">
            You sign in only once. Both methods use the same cart, customer and final Orders history.
          </p>
          { error && <p className="checkout-method-error" role="alert">{ error }</p> }

          <style jsx>{`
            .checkout-method{
              width:min(100%,720px);display:grid;gap:14px;margin-top:26px;
            }
            .checkout-method-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
            .checkout-method-note{
              margin:4px 0 0;color:var(--public-muted);font-size:14px;line-height:1.5;
            }
            .checkout-method-error{margin:0;color:#b91c1c;font-size:14px;line-height:1.5}
          `}</style>
        </section>
      </RotatingHero>
    </>
  );
}
