import { buildPageTitle } from '../lib/page-title';
import React, { useEffect } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';

// Owner-requested retirement: these former product paths must not redirect.
const RETIRED_PRODUCT_PATHS = new Set( [ '/grahak-os', '/vayulok', '/sehat', '/niji-setu', '/shop/niji-setu' ] );

const NotFound: React.FC = () => {
  const router = useRouter();
  useEffect( () => {
    const path = window.location.pathname.replace( /\/+$/, '' ) || '/';
    if ( !RETIRED_PRODUCT_PATHS.has( path ) ) void router.replace( '/' );
  }, [ router ] );
  // A static export cannot distinguish a missing URL until JS runs. No meta refresh:
  // retired paths must remain at their own 404, including without JavaScript.
  return (
    <>
      <Head>
        <title>{ buildPageTitle( 'Page not found' ) }</title>
        <meta name="robots" content="noindex, follow" />
      </Head>
      <main style={ { maxWidth: 680, margin: '80px auto', padding: '24px' } }>
        <h1>Page not found</h1>
        <p>This page is no longer available.</p>
        <Link href="/">Visit WECARE.DIGITAL</Link>
      </main>
    </>
  );
};

export default NotFound;
