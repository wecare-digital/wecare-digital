import React from 'react';
import ProductPage from '../components/ProductPage';
import { SUBSCRIBE } from '../content/subscribe';

/**
 * /subscribe - the Subscribe page.
 *
 * DELIBERATELY THIN, like /leave-review/ and the product pages. Copy lives in
 * src/content/subscribe.ts and the layout in ProductPage.tsx, so this file exists only to own
 * the route. The hero is the shared RotatingHero that ProductPage renders, the same animated
 * headline pill as the home page, with this page's own badge, headline and sub-line.
 *
 * THE CTA GOES TO /contact/, on owner instruction, until the subscription backend exists. There
 * is no form and nothing is stored. The label and href are SUBSCRIBE_CTA_LABEL and
 * SUBSCRIBE_CTA_HREF in the content module.
 *
 * CHROME IS NOT IMPORTED HERE. _app.tsx mounts the shared Header, Footer and SupportWidget for
 * every public route.
 *
 * ROUTING: '/subscribe' must be in PUBLIC_PAGE_META in _app.tsx or this renders the staff
 * sign-in shell with HTTP 200, in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never
 * advertised, and in STRUCTURAL in scripts/generate-public-pages.js or the catalogue misses it.
 * trailingSlash means the URL is /subscribe/.
 */
const SubscribePage: React.FC = () => <ProductPage product={ SUBSCRIBE } />;

export default SubscribePage;
