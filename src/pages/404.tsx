import { buildPageTitle } from '../lib/page-title';
import React, { useEffect } from 'react';
import Head from 'next/head';

const NotFound: React.FC = () => {
  useEffect( () => {
    // Every missing or retired public page hands visitors back to Home.
    // Use a full document navigation: a static 404 may have no matching Next route.
    // The root guard avoids a redirect loop if the homepage itself ever fails.
    if ( window.location.pathname !== '/' ) window.location.replace( '/' );
  }, [] );

  // Amplify still serves this document with HTTP 404 for missing URLs.
  // Keep the noindex and a working link for clients without JavaScript.
  return (
    <>
      <Head>
        <title>{ buildPageTitle( 'Page not found' ) }</title>
        <meta name="robots" content="noindex, follow" />
      </Head>
      <main style={ { maxWidth: 680, margin: '80px auto', padding: '24px' } }>
        <h1>Page not found</h1>
        <p>This page is no longer available.</p>
        <a href="/">Visit WECARE.DIGITAL</a>
      </main>
    </>
  );
};

export default NotFound;
