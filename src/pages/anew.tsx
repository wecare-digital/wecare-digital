import React from 'react';
import ProductPage from '../components/ProductPage';
import { productBySlug } from '../content/products';

/**
 * /anew — the Anew product page.
 *
 * RENAMED TWICE. This file was src/pages/swdhya.tsx, then src/pages/open-possibility.tsx.
 * The route followed the brand name each time rather than leaving a new name at an old
 * address. No redirects are needed because neither earlier URL was ever published - the
 * page has only ever existed on an unmerged branch, so nothing links to [retired public path]/ or
 * [retired public path]/.
 *
 * NOT TO BE CONFUSED with the other "Swdhya" references still in this repo, which are
 * deliberately untouched: "Swdhya Vaksetu" is the blog author's name (seo/schema/schema-templates.json and the retained SEO
 * implementation history), and the WhatsApp brand
 * catalogue in amplify/functions/ai/ai-generate-response still advertises Swdhya at
 * swdhya.in with live payload ids like store_swdhya. Those are a person and a running
 * production flow, not this page, and renaming them needs an explicit decision.
 *
 * DELIBERATELY THIN. Copy lives in src/content/products.ts and the layout in
 * ProductPage.tsx, so all seven product pages cannot drift apart. This file exists only to
 * own the route.
 *
 * ROUTING: '/anew' must be in the EXACT-MATCH allowlist in _app.tsx or this renders an
 * empty body with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is
 * never advertised. trailingSlash means the URL is /anew/.
 *
 * A STATIC ROUTE, NOT A DYNAMIC ONE. A single pages/[slug].tsx would have been less code,
 * but _app.tsx gates public access on an exact router.pathname match and the sitemap uses an
 * exact allowlist; a catch-all would have to be special-cased in both, and would also
 * swallow every unknown path on a static export.
 */
const AnewPage: React.FC = () => <ProductPage product={ productBySlug( 'anew' ) } />;

export default AnewPage;
