import React from 'react';
import ProductPage from '../components/ProductPage';
import { productBySlug } from '../content/products';

/**
 * /niji-setu — the Niji Setu product page.
 *
 * DELIBERATELY THIN. Copy lives in src/content/products.ts and the layout in
 * ProductPage.tsx, so all seven product pages cannot drift apart. This file exists only to
 * own the route.
 *
 * ROUTING: '/niji-setu' must be in the EXACT-MATCH allowlist in _app.tsx or this renders an
 * empty body with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is
 * never advertised. trailingSlash means the URL is /niji-setu/.
 *
 * A STATIC ROUTE, NOT A DYNAMIC ONE. A single pages/[slug].tsx would have been less code,
 * but _app.tsx gates public access on an exact router.pathname match and the sitemap uses an
 * exact allowlist; a catch-all would have to be special-cased in both, and would also
 * swallow every unknown path on a static export.
 */
/* Home / Shop / <Product>, matching what /shop/<slug>/ renders, so the trail from the listing into
   a product is unbroken. ProductPage's `crumbs` prop is opt-in - see its docblock for why. */
const NijiSetuPage: React.FC = () => (
  <ProductPage
    product={ productBySlug( 'niji-setu' ) }
    crumbs={ [ { label: 'Home', href: '/' }, { label: 'Shop', href: '/shop/' }, { label: 'Niji Setu' } ] }
  />
);

export default NijiSetuPage;
