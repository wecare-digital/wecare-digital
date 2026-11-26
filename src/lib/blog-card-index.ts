import type { BlogCard } from './public-blog';

/** Reuse a successfully loaded static build index across client-side navigation.
 * Failed or empty responses are never cached, so a later explicit retry still works.
 */
let pending: Promise<BlogCard[]> | undefined;
let cached: BlogCard[] | undefined;
export function loadBlogCardIndex(): Promise<BlogCard[]> {
  if ( cached ) return Promise.resolve( cached );
  if ( !pending ) {
    pending = fetch( '/blog/search-index.json', { headers: { Accept: 'application/json' } } )
      .then( async response => {
        if ( !response.ok ) throw new Error( `Blog index: ${response.status}` );
        const body = await response.json();
        if ( !Array.isArray( body?.posts ) || !body.posts.every( ( post: BlogCard ) =>
          typeof post?.slug === 'string' && typeof post?.title === 'string' ) ) {
          throw new Error( 'Invalid blog index' );
        }
        const cards = body.posts as BlogCard[];
        if ( cards.length ) cached = cards;
        return cards;
      } )
      .finally( () => { pending = undefined; } );
  }
  return pending;
}
