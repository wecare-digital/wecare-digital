import React from 'react';
import ProductPage from '../components/ProductPage';
import { customerserviceBySlug } from '../content/customerservice';

/**
 * /request-pickup — the Request Pickup page.
 *
 * DELIBERATELY THIN, like its siblings in the Request group. Copy lives in
 * src/content/customerservice.ts and the layout in ProductPage.tsx, so the pages that share that
 * shape cannot drift apart. This file exists only to own the route.
 *
 * WHY IT EXISTS: live Wix began returning a fifth variant of the services product on 2026-10-10,
 * and a service that can be paid for needs a page a customer can read first. The variant is
 * declared in src/config/services.ts and mirrored in service_requests.py; this is its address.
 *
 * ROUTING: '/request-pickup' must be in PUBLIC_PAGE_META in _app.tsx or this renders an empty body
 * with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 * trailingSlash means the URL is /request-pickup/.
 */
const RequestPickupPage: React.FC = () => (
  <ProductPage product={ customerserviceBySlug( 'request-pickup' ) } />
);

export default RequestPickupPage;
