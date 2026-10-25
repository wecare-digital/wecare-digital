import React from 'react';
import { useRouter } from 'next/router';
import ProductPage from '../components/ProductPage';
import GetPage from '../components/get/GetPage';
import ServiceBuyBox from '../components/ServiceBuyBox';
import { customerserviceBySlug } from '../content/customerservice';
import { serviceByKind } from '../config/services';

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
 * ITS CTA OPENS THE VAULT WHATSAPP CONVERSATION (whatsappServiceLink('vault')), NOT /get/, the
 * same way each sibling opens its own service conversation. /get/ only has
 * something to show once files have actually been shared with you; a visitor whose document
 * was never put there would land on an empty collection screen, which is a worse answer than
 * being asked. The third point below describes the mechanism without linking to it, because
 * describing it is accurate and linking it would only work for some readers.
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

  const service = serviceByKind( 'VAULT' );
  const product = customerserviceBySlug( 'vault' );
  return (
    <ProductPage
      product={ product }
      crumbs={ [ { label: 'Home', href: '/' }, { label: product.name } ] }
      belowCta={ service ? <ServiceBuyBox service={ service } /> : null }
    />
  );
};

export default VaultPage;
