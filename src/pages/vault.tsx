import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import GetPage from '../components/get/GetPage';
import ProductPage from '../components/ProductPage';
import { customerserviceBySlug } from '../content/customerservice';

/**
 * One route, two deliberately separate presentations:
 * - /vault/ is the public explanatory page. It must never redirect to Orders.
 * - /vault/?file=<fileId> remains the owner-authenticated, exact-file download
 *   surface. GetPage performs all server-backed paid-entitlement checks.
 * Missing, invalid or revoked exact-file links use the existing 404 -> Home
 * fallback. Do not install any host-level redirect on /vault/: Amplify rules
 * cannot differentiate a bare path from the approved WhatsApp ?file= button.
 */
const VAULT_AUTH_RETURN_FILE_KEY = 'wecare.vault.authReturnFile';
const VAULT_FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,120}$/;

const VaultPage: React.FC = () => {
  const router = useRouter();
  const fileParam = router.query.file;
  const hasFileParam = fileParam !== undefined;
  // Duplicate file parameters are invalid; never silently choose an ID.
  const queryFileId = typeof fileParam === 'string' ? fileParam : '';
  const [ restoredFileId, setRestoredFileId ] = useState( '' );

  useEffect( () => {
    if ( !router.isReady ) return;
    if ( hasFileParam ) {
      if ( !VAULT_FILE_ID_PATTERN.test( queryFileId ) ) {
        // The same missing-document fallback the authenticated file reader uses.
        void router.replace( '/404' );
      }
      return;
    }

    // A verified sign-in can return without the query, with the original exact
    // file bound in sessionStorage in this tab. Restore it before showing the
    // generic public entry to the customer. No file id is trusted as ownership.
    try {
      const saved = window.sessionStorage.getItem( VAULT_AUTH_RETURN_FILE_KEY ) || '';
      if ( VAULT_FILE_ID_PATTERN.test( saved ) ) {
        window.sessionStorage.removeItem( VAULT_AUTH_RETURN_FILE_KEY );
        setRestoredFileId( saved );
        void router.replace( { pathname: '/vault/', query: { file: saved } },
          undefined, { shallow: true } );
        return;
      }
    } catch {
      // Public landing remains available even when storage is blocked.
    }
  }, [ router, router.isReady, hasFileParam, queryFileId ] );

  const targetFileId = queryFileId || restoredFileId;
  if ( router.isReady && hasFileParam ) {
    if ( VAULT_FILE_ID_PATTERN.test( queryFileId ) ) {
      return <GetPage targetFileId={ queryFileId } />;
    }
    // An invalid query never renders a payment/file page while Home fallback runs.
    return <Head><meta name="robots" content="noindex, nofollow" /></Head>;
  }
  if ( router.isReady && VAULT_FILE_ID_PATTERN.test( restoredFileId ) ) {
    return <GetPage targetFileId={ targetFileId } />;
  }

  // Build-time static HTML is the actual public landing page. Private file
  // requests hydrate into GetPage ONLY after the query is available in router.
  return <ProductPage product={ customerserviceBySlug( 'vault' ) }
    canonicalPath="/vault/" mobileFoundation />;
};

export default VaultPage;
