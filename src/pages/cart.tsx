import Head from 'next/head';
import React, { useEffect } from 'react';
import { basketTokenFromUrl } from '../lib/whatsappBasket';

/** Historic /cart/ entry. Redirect silently, retaining any basket token for /checkout/. */
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
      {/* No visible waypoint: the effect carries the basket token to Checkout. */}
    </>
  );
}
