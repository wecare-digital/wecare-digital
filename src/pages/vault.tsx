import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import ProductPage from '../components/ProductPage';
import GetPage from '../components/get/GetPage';
import PillButton from '../components/PillButton';
import { customerserviceBySlug } from '../content/customerservice';

/**
 * Vault is bought per DOCUMENT, so the public service page does not mint a generic service intent.
 * The authenticated Vault collection owns the file picker. Once the customer selects an owned
 * file, it creates a file-bound service intent and hands that exact document to the shared cart;
 * /checkout/ then offers Pay here or Pay on WhatsApp.
 */
const VaultActions: React.FC = () => (
  <div className="vault-actions">
    <PillButton
      as="a"
      href="/get/"
      label="Vault"
      action="Open your documents"
      block
    />
    <p className="vault-fine">
      Verify your WhatsApp number, choose your document, then use the shared checkout to pay here
      or on WhatsApp. Already received an Access Vault link? <Link href="/get/">Open your documents</Link>.
    </p>
    <style jsx>{ `
      .vault-actions{display:flex;flex-direction:column;gap:12px;max-width:460px}
      .vault-fine{margin:0;font-size:var(--text-md);line-height:1.45;color:rgba(26,58,42,.78)}
      .vault-fine :global(a){color:var(--accent);font-weight:600;text-decoration:underline;
        text-underline-offset:3px;display:inline-block;min-height:var(--tap-min,44px);line-height:44px}
    ` }</style>
  </div>
);

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
 * template lands on /vault/?file={{1}}; that deep-link delegates to the same authenticated
 * collection component as /get/, scoped to the named file.
 * This page is the part that CAN sit in a menu: what is kept, for how long, and how a copy is
 * released.
 *
 * ITS CTA OPENS /get/, the authenticated Vault collection. That collection is the only website
 * surface that can safely choose an exact customer-owned file before payment. A visitor with no
 * shared files sees an empty owned collection and cannot create a payable Vault intent.
 *
 * PUBLIC, AND NOT /workspace/*. The authenticated file surfaces read a Cognito session and
 * render the dashboard Layout; a public row pointing there shows an anonymous visitor a login
 * wall instead of an answer.
 *
 * ROUTING: '/vault' must be in PUBLIC_PAGE_META in _app.tsx or this renders an empty body with
 * HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 * trailingSlash means the URL is /vault/.
 */
const VaultPage: React.FC = () => {
  const router = useRouter();
  const fileParam = router.query.file;
  const targetFileId = Array.isArray( fileParam ) ? fileParam[ 0 ] : fileParam;

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
      belowCta={ <VaultActions /> }
    />
  );
};

export default VaultPage;
