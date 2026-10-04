import React from 'react';
import ProductPage from '../components/ProductPage';
import { customerserviceBySlug } from '../content/customerservice';

/**
 * /request-amendment — the Request Amendment page.
 *
 * DELIBERATELY THIN, like the seven product pages. Copy lives in
 * src/content/customerservice.ts and the layout in ProductPage.tsx, so the twelve pages that
 * share that shape cannot drift apart. This file exists only to own the route.
 *
 * WHY IT EXISTS AT ALL: the header's Customer service column offered six labels and every one of
 * them resolved to /contact/. Header.tsx recorded that as a placeholder and named the fix —
 * build public pages and register each in PUBLIC_PAGE_META.
 *
 * ROUTING: '/request-amendment' must be in PUBLIC_PAGE_META in _app.tsx or this renders an empty body
 * with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never
 * advertised. trailingSlash means the URL is /request-amendment/.
 *
 * PUBLIC, AND NOT [retired public path]/request-amendment. That route exists and is authenticated by design — it
 * renders the dashboard Layout and reads a Cognito session. This page touches neither.
 */
const RequestAmendmentPage: React.FC = () => <ProductPage product={ customerserviceBySlug( 'request-amendment' ) } />;

export default RequestAmendmentPage;
