import React, { useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { buildPageTitle } from '../lib/page-title';

/**
 * Legacy customer file entry.
 *
 * /vault/?file=<fileId> is the only customer download surface. Bare /get/ is
 * a legacy path without a file and returns Home; /get/<*> is a separate CloudFront
 * media namespace and must retain its existing 200 proxy rewrite.
 */
const GetRedirect: React.FC = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( '/' );
  }, [ router ] );

  return (
    <Head>
      <title>{ buildPageTitle( 'Vault' ) }</title>
      <meta name="robots" content="noindex, follow" />
      <meta httpEquiv="refresh" content="0; url=/" />
      <link rel="canonical" key="canonical" href="https://wecare.digital/" />
    </Head>
  );
};

export default GetRedirect;
