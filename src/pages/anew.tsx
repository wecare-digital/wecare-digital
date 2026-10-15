import React from 'react';
import type { GetStaticProps } from 'next';
import ProductPage from '../components/ProductPage';
import { breadcrumbTrail } from '../content/breadcrumbTrails';
import ProductBuyBox from '../components/ProductBuyBox';
import { productBySlug } from '../content/products';
import { listPublicBlogPosts, listBlogCards, type BlogCard } from '../lib/public-blog';

/** /anew/ owns its URL and static seed. The complete card index is fetched after hydration,
 * using the same static transport as /blog/. Four cards per category keep initial content
 * useful for readers and crawlers without serialising the corpus into __NEXT_DATA__.
 * Keep /anew registered in PUBLIC_PAGE_META, PUBLIC_EXACT and the generated catalogue.
 */

interface AnewPageProps {
  blogCards: BlogCard[];
  blogCategories: string[];
}

const AnewPage: React.FC<AnewPageProps> = ( { blogCards, blogCategories } ) => (
  <ProductPage
    product={ productBySlug( 'anew' ) }
    crumbs={ breadcrumbTrail( '/anew' ) }
    blogCards={ blogCards }
    blogCategories={ blogCategories }
    blogHeading="Perspectives"
    price="₹599"
    priceUnit="· one decision · written reflection · usually 2–3 business days"
    belowCta={ <ProductBuyBox slug="anew" showPrice={ false } /> }
  />
);

export const getStaticProps: GetStaticProps<AnewPageProps> = async () => {
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
  const blogCategories = Array.from( new Set( blogCards.map( card => card.category ).filter( Boolean ) as string[] ) )
    .sort( ( a, b ) => a.localeCompare( b ) );
  const counts = new Map<string, number>();
  const initialCards = blogCards.filter( card => {
    const category = card.category || '';
    const count = counts.get( category ) || 0;
    counts.set( category, count + 1 );
    return count < 4;
  } );
  return { props: { blogCards: initialCards, blogCategories } };
};

export default AnewPage;
