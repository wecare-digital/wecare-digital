import React from 'react';
import type { GetStaticProps } from 'next';
import ProductPage from '../components/ProductPage';
import { productBySlug } from '../content/products';
import { listPublicBlogPosts, listBlogCards, type BlogCard } from '../lib/public-blog';
import { SITE_ORIGIN } from '../config/share';

/**
 * /anew — the Anew product page.
 *
 * RENAMED TWICE. This file was src/pages/swdhya.tsx, then src/pages/open-possibility.tsx. The
 * route followed the brand name each time rather than leaving a new name at an old address. No
 * redirects are needed because neither earlier URL was ever published.
 *
 * NO LONGER AS THIN AS ITS SIBLINGS, and on purpose. The other six product pages are a single
 * line - <ProductPage product={...} /> - because they render only their own copy. Anew also
 * carries a right-hand blog panel, so it needs the blog corpus, and the corpus is fetched at
 * build time (output: 'export', so there is no runtime fetch). getStaticProps calls the same
 * listPublicBlogPosts() / listBlogCards() that /blog/ uses - no new data source, no new fetch
 * logic - and hands the newest ~30 cards to ProductPage, which renders the panel. The panel
 * filters and caps client-side. The build-time memo in public-blog.ts means this adds no extra
 * upstream request: /blog/ and /post/[slug] already warm the same cached promise.
 *
 * ROUTING: '/anew' must be in the EXACT-MATCH allowlist in _app.tsx or this renders an empty body
 * with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 */

/** Newest cards handed to the panel. 30 is generous headroom over the panel's visible cap of 6,
 *  so category filtering and search have real material to work with without shipping the corpus. */
const ANEW_PANEL_CARDS = 30;

interface AnewPageProps {
  blogCards: BlogCard[];
}

const AnewPage: React.FC<AnewPageProps> = ( { blogCards } ) => (
  <ProductPage
    product={ productBySlug( 'anew' ) }
    blogCards={ blogCards }
    price="₹599"
    priceUnit="one written reflection"
    catalogueHref="/shop/"
    catalogueLabel="See everything on WECARE.DIGITAL"
    shareUrl={ `${SITE_ORIGIN}/anew/` }
  />
);

export const getStaticProps: GetStaticProps<AnewPageProps> = async () => {
  const posts = await listPublicBlogPosts();
  const blogCards = listBlogCards( posts ).slice( 0, ANEW_PANEL_CARDS );
  return { props: { blogCards } };
};

export default AnewPage;
