import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import GetPage from '../components/get/GetPage';

/**
 * Vault is NOT a standalone public product page. Bare /vault/ entries
 * without a file identifier return to the homepage.
 *
 * Preserve /vault/?file=<fileId> as the ONE exact-file download route used by
 * approved WhatsApp templates and the website's paid Vault return journey.
 * That URL is owner-checked by GetPage and must never be redirected by an
 * Amplify path-only rule, because such a rule would also consume ?file= links.
 */
const VAULT_AUTH_RETURN_FILE_KEY = 'wecare.vault.authReturnFile';
const VAULT_FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,120}$/;

const VaultPage: React.FC = () => {
  const router = useRouter();
  const fileParam = router.query.file;
  const queryFileId = Array.isArray( fileParam ) ? fileParam[ 0 ] : fileParam;
  const [ restoredFileId, setRestoredFileId ] = useState( '' );

  useEffect( () => {
    if ( !router.isReady ) return;
    if ( queryFileId ) {
      if ( !VAULT_FILE_ID_PATTERN.test( queryFileId ) ) {
        // Malformed file identifiers return directly Home without sign-in.
        void router.replace( '/' );
      }
      return;
    }
    // Sign-in can return here with the exact file id saved out of band. Restore
    // that file BEFORE considering the ordinary bare-route redirect.
    try
    {
      const saved = window.sessionStorage.getItem( VAULT_AUTH_RETURN_FILE_KEY ) || '';
      if ( VAULT_FILE_ID_PATTERN.test( saved ) ) {
        window.sessionStorage.removeItem( VAULT_AUTH_RETURN_FILE_KEY );
        setRestoredFileId( saved );
        void router.replace( { pathname: '/vault/', query: { file: saved } }, undefined,
          { shallow: true } );
        return;
      }
    } catch
    {
      // Storage can be unavailable; no file target means Home.
    }
    void router.replace( '/' );
  }, [ router, router.isReady, queryFileId ] );

  const targetFileId = queryFileId || restoredFileId;
  if ( router.isReady && VAULT_FILE_ID_PATTERN.test( targetFileId ) ) {
    return <GetPage targetFileId={ targetFileId } />;
  }

  // No meta-refresh: static export generates this SAME HTML for ?file= URLs.
  // Meta refresh would hijack a valid file link before React reads its query.
  return (
    <>
      <Head>
        <meta name="robots" content="noindex, nofollow" />
        <link rel="canonical" key="canonical" href="https://wecare.digital/" />
      </Head>
      <main style={ { maxWidth: '1100px', margin: '50px auto', padding: '0 24px' } }>
        <p>Opening your account…</p>
        <Link href="/">Go to Home</Link>
      </main>
    </>
  );
};

export default VaultPage;
