import type { BlogCard } from './public-blog';

/** The same static search transport used by /blog/. Share requests, and allow retry on failure. */
let pending: Promise<BlogCard[]> | undefined;
export function loadBlogCardIndex(): Promise<BlogCard[]> {
  if ( !pending ) {
    pending = fetch( '/blog/search-index.json', { headers: { Accept: 'application/json' } } )
      .then( async response => {
        if ( !response.ok ) throw new Error( `Blog index: ${response.status}` );
        const body = await response.json();
        if ( !Array.isArray( body?.posts ) || !body.posts.every( ( post: BlogCard ) =>
          typeof post?.slug === 'string' && typeof post?.title === 'string' ) ) {
          throw new Error( 'Invalid blog index' );
        }
        return body.posts as BlogCard[];
      } )
      .finally( () => { pending = undefined; } );
  }
  return pending;
}
