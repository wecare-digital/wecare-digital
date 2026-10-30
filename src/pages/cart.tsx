import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import React, { useEffect } from 'react';

/** Legacy cart links redirect to the one checkout, preserving the bounded basket token. */
export default function LegacyCartRedirect (): React.ReactElement {
  const router = useRouter();
  useEffect( () => {
    const token = new URLSearchParams( window.location.search ).get( 'basket' ) || '';
    const query = token.length > 0 && token.length <= 100
      ? `?basket=${ encodeURIComponent( token ) }` : '';
    void router.replace( `/checkout/${ query }` );
  }, [ router ] );
  return (
    <main style={ { padding: '140px 24px 48px', textAlign: 'center' } }>
      <Head>
        <title>Checkout | WECARE.DIGITAL</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <h1>Continue to checkout</h1>
      <p>Your selected product is ready for review.</p>
      <Link href="/checkout/">Continue to checkout</Link>
    </main>
  );
}
