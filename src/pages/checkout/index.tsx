import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import React, { useEffect } from 'react';

import { CHECKOUT_PATH } from '../../lib/serviceEntry';
import { buildPageTitle } from '../../lib/page-title';

/**
 * Compatibility route for older /checkout/ links.
 *
 * Short Commerce Part 1 chooses the existing website or WhatsApp payment rail
 * on /cart/, after reviewing exactly one product. Do not leave a second
 * payment-method page or start a payment during the redirect.
 */
export default function CheckoutMethodPage (): React.ReactElement {
  const router = useRouter();

  useEffect( () => {
    void router.replace( CHECKOUT_PATH );
  }, [ router ] );

  return (
    <>
      <Head>
        <title>{ buildPageTitle( 'Checkout' ) }</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <main className="checkout-return">
        <h1>Checkout continues in your cart.</h1>
        <Link href={ CHECKOUT_PATH }>Continue to cart</Link>
        <style jsx>{`
          .checkout-return{
            min-height:40vh;display:flex;flex-direction:column;align-items:center;
            justify-content:center;gap:12px;padding:120px 24px 48px;
            color:var(--public-text);font-family:var(--font-sans);
            text-align:center;
          }
          .checkout-return h1{margin:0;font-size:18px;font-weight:600;line-height:1.4}
        `}</style>
      </main>
    </>
  );
}
