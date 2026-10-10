import React from 'react';
import ProductPage from '../components/ProductPage';
import { SHIPMENTS } from '../content/shipments';

/**
 * /shipments — the Shipments page.
 *
 * DELIBERATELY THIN, like /drop-docs/ and /subscribe/. All copy lives in
 * src/content/shipments.ts and the layout in ProductPage.tsx, so this page cannot drift from
 * its siblings. This file exists only to own the route.
 *
 * TWO CTAs: Shipments ships both a tracking door and a pickup door, so its ProductDef carries
 * the optional ctaLabel2/ctaHref2 pair and ProductPage renders a second pill. Everything about
 * why those live as data — and why the pickup href bypasses whatsappServiceLink() — is in
 * src/content/shipments.ts.
 *
 * NOT A SEVENTH CUSTOMERSERVICE ENTRY: the copy is its own module (src/content/shipments.ts),
 * following the src/content/subscribe.ts precedent, because both CTAs are wa.me links (which a
 * CUSTOMERSERVICE guard forbids) and /shipments is already filed in the `start` catalogue group.
 *
 * THE PAGE WAS CALLED "ZIP" AND THE NAME IS GONE, on owner instruction (2026-10-02). It must not
 * reappear anywhere, including in schema output.
 *
 * ROUTING: '/shipments' must be in PUBLIC_PAGE_META in _app.tsx, PUBLIC_EXACT in
 * scripts/generate-sitemap.js, and config/public-pages.json (generated). trailingSlash means the
 * URL is /shipments/.
 */
const ShipmentsPage: React.FC = () => (
  <ProductPage product={ SHIPMENTS } />
);

export default ShipmentsPage;
