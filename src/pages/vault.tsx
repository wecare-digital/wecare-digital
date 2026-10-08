import React from 'react';
import ProductPage from '../components/ProductPage';
import ServiceRequestPurchase from '../components/ServiceRequestPurchase';
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
 * NOT A SECOND /get/. That route is the mechanism: verify a number over WhatsApp, then
 * collect the files shared with you. It is noindex,nofollow and has zero inbound links in the
 * whole export, which is deliberate - it is reached from the message that carries the link.
 * This page is the part that CAN sit in a menu: what is kept, for how long, and how a copy is
 * released.
 *
 * ITS CTA GOES TO /contact/, NOT TO /get/, like all five of its siblings. /get/ only has
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
// The buy box renders AFTER the shared ProductPage, which is not edited.
const VaultPage: React.FC = () => (
  <>
    <ProductPage product={ customerserviceBySlug( 'vault' ) } />
    <ServiceRequestPurchase kind="VAULT" />
  </>
);

export default VaultPage;
