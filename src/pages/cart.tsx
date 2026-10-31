import Head from 'next/head';
import Link from 'next/link';
import React, { useEffect } from 'react';
import { basketTokenFromUrl } from '../lib/whatsappBasket';

/** Historic /cart/ entry. The full basket and payment review live at /checkout/. */
export default function CartRedirect (): React.ReactElement {
  useEffect( () => {
    const token = basketTokenFromUrl();
    // Preserve an existing hand-off link when moving to the real checkout.
    window.location.replace( token
      ? `/checkout/?basket=${encodeURIComponent( token )}`
      : '/checkout/' );
  }, [] );
  return (
    <>
      <Head>
        <title>Continue to checkout | WECARE.DIGITAL</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <main className="cart-return">
        <h1>Continue to checkout</h1>
        <p>Your cart and secure payment are on the checkout page.</p>
        <Link href="/checkout/">Review checkout</Link>
        <style jsx>{`
          .cart-return{padding:150px 24px 70px;max-width:650px;margin:auto;text-align:center;font-family:var(--font-sans);color:var(--public-text)}
          .cart-return h1{font-size:var(--public-section-size);line-height:var(--public-section-leading);font-weight:var(--public-section-weight)}
          .cart-return p{font-size:var(--public-body-size);line-height:var(--public-body-leading)}
        `}</style>
      </main>
    </>
  );
}
