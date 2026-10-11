import React from 'react';
import ProductPage from '../components/ProductPage';
import { productBySlug } from '../content/products';

/**
 * /hunar — the Hunar product page: skills, CV profiles and the professional pitch.
 *
 * DELIBERATELY THIN, like the other product pages. Copy lives in src/content/products.ts and
 * the layout in ProductPage.tsx, so the pages that share that shape cannot drift apart. This
 * file exists only to own the route.
 *
 * WHY IT IS NOT A BESPOKE PAGE. The brief asked for animation and a top section with its own
 * content directly under the header, and ProductPage already delivers exactly that: the
 * RotatingHero cycles the h1's word through the four hues in products.ts, and its .rh-layout
 * is the band that sits immediately after the fixed header - measured on 18 other routes in
 * the export, not just the product pages. Writing a second layout to get the same effect would
 * mean re-solving every problem this one has already solved: the 108px/96px header clearance,
 * the h1 not changing height as the pill rotates across 21 viewports, one body rung, the
 * reduced-motion resting state, RTL, and zero horizontal overflow at 320px. A new page would
 * be measured against all of it and would start by failing several.
 *
 * THE MENU ENTRY IS NOT WRITTEN ANYWHERE. Header.tsx maps over PRODUCTS, so adding the entry
 * to src/content/products.ts is what puts Hunar under the Products heading. That is the point
 * of the array: a product cannot be listed in the menu without a page, or have a page nobody
 * can reach.
 *
 * ROUTING: '/hunar' must be in PUBLIC_PAGE_META in _app.tsx or this renders an empty body with
 * HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 * trailingSlash means the URL is /hunar/.
 */
/* Home / Shop / <Product>, matching what /shop/<slug>/ renders, so the trail from the listing into
   a product is unbroken. ProductPage's `crumbs` prop is opt-in - see its docblock for why. */
const HunarPage: React.FC = () => (
  <ProductPage
    product={ productBySlug( 'hunar' ) }
    crumbs={ [ { label: 'Home', href: '/' }, { label: 'Shop', href: '/shop/' }, { label: 'Hunar' } ] }
  />
);

export default HunarPage;
