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
 * logic - and hands the cards to ProductPage, which renders the panel. The panel shows them all
 * in a scroll rail and filters client-side. The build-time memo in public-blog.ts means this adds
 * no extra upstream request: /blog/ and /post/[slug] already warm the same cached promise, and
 * every build re-fetches the live corpus from Wix, so the panel is always current.
 *
 * ROUTING: '/anew' must be in the EXACT-MATCH allowlist in _app.tsx or this renders an empty body
 * with HTTP 200, and in PUBLIC_EXACT in scripts/generate-sitemap.js or it is never advertised.
 */

/*
 * THE PANEL RECEIVES THE WHOLE CORPUS, no per-category cap. Owner instruction: load all blogs, not
 * a limited set. The previous 80-per-category ceiling was a payload guard - shipping every card
 * into __NEXT_DATA__ adds weight (~400kB for ~1300 cards) - but the owner wants the Perspectives
 * pager to page through everything, so that trade is accepted. The pager (ProductBlogPanel)
 * groups the full list into pages client-side, so the UI stays light regardless of count; only the
 * build-time payload grows. The cards still arrive newest-first across categories (sorted below),
 * and the per-category pills continue to filter the full set client-side.
 */

interface AnewPageProps {
  blogCards: BlogCard[];
}

/* THE TRAIL: Home / Shop / <Product>, matching what /shop/<slug>/ renders. /anew/ is the page the
   Anew card on /shop/ points at - the slug exists in both halves of the shelf and resolves here,
   because this is the richer page. ProductPage's `crumbs` prop is opt-in; see its docblock.
   This route is also the only one that passes blogCards, so .pdp-wrap is a GRID here - the
   .pdp-crumbs wrapper and its grid-column:1 / -1 rule are what keep the blog rail where it
   belongs rather than letting the trail push the copy into it. */
const AnewPage: React.FC<AnewPageProps> = ( { blogCards } ) => (
  <ProductPage
    product={ productBySlug( 'anew' ) }
    crumbs={ [ { label: 'Home', href: '/' }, { label: 'Shop', href: '/shop/' }, { label: 'Anew' } ] }
    blogCards={ blogCards }
    blogHeading="Perspectives"
    price="₹599"
    priceUnit="· one decision · written reflection · usually 2–3 business days"
    shareUrl={ `${SITE_ORIGIN}/anew/` }
  />
);

export const getStaticProps: GetStaticProps<AnewPageProps> = async () => {
  // The FULL corpus, newest-first. listBlogCards is already newest-first; no per-category cap - the
  // panel pages through everything.
  const blogCards = listBlogCards( await listPublicBlogPosts() )
    .slice()
    .sort( ( a, b ) => {
      const at = a.publishedDate ? Date.parse( a.publishedDate ) : NaN;
      const bt = b.publishedDate ? Date.parse( b.publishedDate ) : NaN;
      if ( Number.isNaN( at ) && Number.isNaN( bt ) ) return a.slug.localeCompare( b.slug );
      if ( Number.isNaN( at ) ) return 1;
      if ( Number.isNaN( bt ) ) return -1;
      return bt - at;
    } );
  return { props: { blogCards } };
};

export default AnewPage;
