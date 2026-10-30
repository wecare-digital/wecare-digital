import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import ProductPage from '../components/ProductPage';
import GetPage from '../components/get/GetPage';
import { customerserviceBySlug } from '../content/customerservice';

/**
 * /vault — asking for a copy of a document held against one of your requests.
 *
 * DELIBERATELY THIN, like Drop Docs and the rest of the Requests group. Copy lives in
 * src/content/customerservice.ts and the layout in ProductPage.tsx.
 *
 * IT SITS UNDER DROP DOCS IN THE MENU because it is the same door in the other direction:
 * Drop Docs sends paperwork in, Vault gets a copy back out. Unlike the Products column, the
 * Requests rows in Header.tsx are written out rather than mapped from the content file, so
 * this one needed adding there by hand - if it is ever missing from the menu, that is where
 * to look, not here.
 *
 * Without a file query this remains the public Vault service page. The approved WhatsApp
 * template lands on /vault/?file={{1}}; that exact-file URL is the one customer download path
 * and mounts the authenticated file view scoped to the named file.
 * This page is the part that CAN sit in a menu: what is kept, for how long, and how a copy is
 * released.
 *
 * PUBLIC, AND NOT /workspace/*. The authenticated file surfaces read a Cognito session and
 * render the dashboard Layout; a public row pointing there shows an anonymous visitor a login
 * wall instead of an answer.
 *
 * ROUTING: '/vault' must be in PUBLIC_PAGE_META in _app.tsx or this renders an empty body with
 * HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 * trailingSlash means the URL is /vault/.
 */
const VAULT_AUTH_RETURN_FILE_KEY = 'wecare.vault.authReturnFile';
const VAULT_FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,120}$/;

const VaultPage: React.FC = () => {
  const router = useRouter();
  const fileParam = router.query.file;
  const queryFileId = Array.isArray( fileParam ) ? fileParam[ 0 ] : fileParam;
  const [ restoredFileId, setRestoredFileId ] = useState( '' );

  useEffect( () => {
    if ( !router.isReady || queryFileId ) return;
    try
    {
      const saved = window.sessionStorage.getItem( VAULT_AUTH_RETURN_FILE_KEY ) || '';
      if ( !VAULT_FILE_ID_PATTERN.test( saved ) ) return;
      window.sessionStorage.removeItem( VAULT_AUTH_RETURN_FILE_KEY );
      setRestoredFileId( saved );
      void router.replace( { pathname: '/vault/', query: { file: saved } }, undefined, { shallow: true } );
    } catch
    {
      // Storage is best-effort only; a failed restore falls back to the public Vault page.
    }
  }, [ router, router.isReady, queryFileId ] );

  const targetFileId = queryFileId || restoredFileId;

  // The approved WhatsApp download template lands here with ?file={{1}}.
  // No file parameter keeps the public Vault service page unchanged; a file parameter
  // enters the authenticated collection surface for that exact file.
  if ( router.isReady && targetFileId )
  {
    return <GetPage targetFileId={ targetFileId } />;
  }

  const product = customerserviceBySlug( 'vault' );
  return (
    <ProductPage
      mobileFoundation
      product={ product }
      crumbs={ [ { label: 'Home', href: '/' }, { label: product.name } ] }
    />
  );
};

export default VaultPage;
