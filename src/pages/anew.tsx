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

/**
 * HOW MANY CARDS PER CATEGORY the panel receives.
 *
 * The owner asked for "all blogs" with no visible cap, and the panel now scrolls, so there is no
 * count limit in the UI. This per-category ceiling is a PAYLOAD guard, not a UX one: shipping all
 * ~1300 cards into __NEXT_DATA__ would add ~400kB to the page for a browsing rail. 80 of each
 * category (newest first) is deep enough to read as "everything" while keeping the page lean, and
 * it guarantees both categories are well represented regardless of which has the newest posts.
 */
const ANEW_PANEL_CARDS_PER_CATEGORY = 80;

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
    blogHeading="Journal"
    price="₹599"
    priceUnit="· one decision · written reflection · usually 2–3 business days"
    shareUrl={ `${SITE_ORIGIN}/anew/` }
  />
);

export const getStaticProps: GetStaticProps<AnewPageProps> = async () => {
  // listBlogCards is already newest-first, so taking the first N of each category keeps the
  // per-category order correct without re-sorting.
  const ordered = listBlogCards( await listPublicBlogPosts() );
  const perCategory = new Map<string, number>();
  const blogCards: BlogCard[] = [];
  for ( const card of ordered ) {
    const key = card.category || 'Uncategorised';
    const count = perCategory.get( key ) || 0;
    if ( count >= ANEW_PANEL_CARDS_PER_CATEGORY ) continue;
    perCategory.set( key, count + 1 );
    blogCards.push( card );
  }
  // Re-order the kept cards newest-first across categories so the first category's rail reads as
  // newest-first rather than category-grouped.
  blogCards.sort( ( a, b ) => {
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
