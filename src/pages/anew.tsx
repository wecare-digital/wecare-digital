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

/**
 * HOW MANY CARDS PER CATEGORY the panel receives.
 *
 * NEWEST-PER-CATEGORY, NOT NEWEST-OVERALL. The corpus has two categories (Conversations,
 * Gastronomy) and the newest posts are overwhelmingly Conversations, so "newest 30 overall" gave
 * the panel zero Gastronomy cards - its pill never appeared and clicking it would have shown
 * nothing. Taking the newest N FROM EACH category guarantees every category pill has real cards
 * behind it, which is what makes the switch meaningful. 20 each is generous headroom over the
 * panel's visible cap of 6 so search and the category switch have material to work with.
 */
const ANEW_PANEL_CARDS_PER_CATEGORY = 20;

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
  // Re-order the kept cards newest-first across categories so the default "All" pill still reads
  // as a newest-first mix rather than category-grouped.
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
