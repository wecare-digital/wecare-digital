import React, { useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { buildPageTitle } from '../lib/page-title';

/**
 * Legacy customer file entry.
 *
 * /vault/?file=<fileId> is the only customer download surface. /get/ remains only as a
 * redirecting signpost for old links; /get/<*> is a separate CloudFront media namespace.
 */
const GetRedirect: React.FC = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( '/vault/' );
  }, [ router ] );

  return (
    <Head>
      <title>{ buildPageTitle( 'Vault' ) }</title>
      <meta name="robots" content="noindex, follow" />
      <meta httpEquiv="refresh" content="0; url=/vault/" />
      <link rel="canonical" key="canonical" href="https://wecare.digital/vault/" />
    </Head>
  );
};

export default GetRedirect;
