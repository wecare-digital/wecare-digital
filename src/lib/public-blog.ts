import blogMerges from '../../config/blog-merges.json';

export interface PublicBlogPost {
  id: string;
  title: string;
  slug: string;
  excerpt: string;
  url: string;
  content?: string;
  richContent?: { nodes?: any[] };
  seoTitle?: string;
  metaDescription?: string;
  focusKeyword?: string;
  keywords?: string[];
  jsonLd?: Record<string, any>;
  publishedDate?: string;
  modifiedDate?: string;
  coverImage?: string;
  category?: string;
  tags?: string[];
  hashtags?: string[];
  authorName?: string;
  robots?: string;
}

/**
 * WHAT A BLOG CARD ACTUALLY NEEDS - seven fields of the eighteen the API returns.
 *
 * THIS TYPE IS THE FIX FOR AN 842 kB PAGE. /blog/ shipped every field of all 834 posts
 * into __NEXT_DATA__ and rendered seven of them. Measured against the live endpoint,
 * the response is 874 kB and breaks down like this:
 *
 *   excerpt 180k  metaDescription 122k  url 61k  seoTitle 52k  slug 37k  title 35k
 *   robots 33k  id 32k  tags 25k  modifiedDate 22k  publishedDate 21k  authorName 20k
 *   category 12k  + focusKeyword/keywords/jsonLd/coverImage/hashtags ~7k
 *
 * metaDescription, seoTitle, robots, tags, modifiedDate, url and id are 357 kB that no
 * card renders - metaDescription and seoTitle exist for the POST page's <head>, and it
 * fetches its own post. `id` goes too: it was only ever the React key, and slug is
 * unique and already present.
 *
 * Kept deliberately: excerpt is the single largest field and it stays, because the card
 * prints it and search matches on it. coverImage is kept although the card does not use
 * it today - it is 1.7 kB across all 834 posts, which is the cost of one small image, and
 * leaving it out would make adding card art a data change rather than a markup one.
 *
 * `tags` CAME BACK, and it is the one field here that is carried for SEARCH rather than for
 * rendering. It was dropped as part of the 357 kB because no card prints it, which was true and
 * is still true - nothing renders it. What that reasoning missed is that search matches on more
 * than what is visible: every post in the corpus carries tags, and they hold the words a reader
 * actually types. "Beverages", "Herbal Tea", "Chai", "Lemongrass" are tags on posts whose titles
 * and excerpts contain none of those strings, so searching any of them returned nothing at all.
 *
 * The cost is small and it is paid by the right people. Measured against the live endpoint over
 * 1064 posts, adding tags takes the search index from 350.0 kB to 391.4 kB - and that index is
 * fetched lazily, only once a reader types, so a visitor who never searches downloads none of it.
 * In a page's own props it is roughly 1 kB across 24 cards.
 */
export interface BlogCard {
  slug: string;
  title: string;
  excerpt?: string;
  category?: string;
  publishedDate?: string;
  authorName?: string;
  coverImage?: string;
  /** Matched by search, never rendered. See the note above. */
  tags?: string[];
}

/** Narrow a full post to the card fields. One place, so a page cannot widen it by accident. */
export function toBlogCard ( post: PublicBlogPost ): BlogCard {
  return {
    slug: post.slug,
    title: post.title,
    // `|| undefined` rather than passing '' through: Next refuses to serialise undefined
    // in props, and an empty string would render an empty <p>. Normalised here so every
    // consumer gets the same shape.
    ...( post.excerpt ? { excerpt: post.excerpt } : {} ),
    ...( post.category ? { category: post.category } : {} ),
    ...( post.publishedDate ? { publishedDate: post.publishedDate } : {} ),
    ...( post.authorName ? { authorName: post.authorName } : {} ),
    ...( post.coverImage ? { coverImage: post.coverImage } : {} ),
    // Guarded on length as well as existence: an empty array would serialise as [] on every card
    // and search would gain nothing for the bytes.
    ...( post.tags && post.tags.length ? { tags: post.tags } : {} ),
  };
}

/**
 * HOW MANY CARDS ON A PAGE. 24 divides cleanly by the grid's 3 and 2 column counts, so no
 * page ends on a ragged row at any width, and it puts /blog/ at roughly 3.3 screens instead
 * of the 115.5 screens 834 cards measured.
 */
export const POSTS_PER_PAGE = 24;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const PUBLIC_BLOG_API = `${API_BASE}/seo-tools/blog-public`;

/**
 * BUILD-TIME MEMO, and it is not premature.
 *
 * getStaticPaths for /post/[slug] calls this once, and now getStaticProps for /blog/ and
 * each of the 35 /blog/page/N pages does too. Without a memo that is 36 requests for the
 * same 874 kB during one build - 31 MB over the wire to render data that cannot change
 * mid-build. The module is evaluated once per build process, so a module-level promise is
 * the whole mechanism needed.
 *
 * THE PROMISE IS CACHED, NOT THE RESULT, so concurrent callers share one in-flight request
 * instead of each starting their own before the first resolves. Next renders pages in
 * parallel, so that case is the normal one rather than the edge.
 *
 * A FAILED FETCH IS NOT CACHED, and it no longer degrades to an empty array either.
 * `fetchAllPosts` used to swallow every error and return [], which meant one bad request
 * could render a site with no blog; the memo was cleared on empty so the next caller would
 * retry. It now retries internally and THROWS when it cannot succeed, so the rejected
 * promise is cleared here and the failure reaches the build instead of being absorbed.
 * generate-sitemap.js refuses to write a sitemap with zero post pages for the same reason.
 */
let postsPromise: Promise<PublicBlogPost[]> | null = null;

export async function listPublicBlogPosts (): Promise<PublicBlogPost[]> {
  if ( postsPromise ) return postsPromise;
  postsPromise = fetchAllPosts();
  try
  {
    const posts = await postsPromise;
    if ( posts.length === 0 ) postsPromise = null;
    return posts;
  } catch ( error )
  {
    // Drop the rejected promise so a later caller retries from scratch rather than
    // inheriting this rejection for the rest of the build.
    postsPromise = null;
    throw error;
  }
}

/* ------------------------------------------------------------------------- *
 * A FAILED REQUEST MUST NOT BECOME A MISSING PAGE.
 *
 * This is the mechanism that shipped 219 dead links to the live site, and it is worth
 * spelling out because every individual piece of it looked reasonable.
 *
 * `fetchPost` returned `null` for BOTH "no such post" and "the request failed".
 * `getStaticProps` in /post/[slug] turns `null` into `notFound: true`. Under
 * `output: 'export'` a `notFound` page is simply NOT EMITTED - no error, no warning.
 * Meanwhile the LIST call had succeeded, so the index pages still rendered a card and a
 * link for every one of those posts.
 *
 * Measured on the 2026-09-29 build: the list returned 1089 posts, 870 post pages were
 * emitted, and the index pages linked all 1089. 219 of those links went to pages that do
 * not exist. The comment above this block already recorded that 117 of the per-slug
 * requests came back 429 in a 24-hour window, so the throttling was known - what was
 * missing was any consequence for it.
 *
 * Three changes, each addressing a different term:
 *
 *   1. 404 is distinguished from failure. Only a 404 means "no such post".
 *   2. A retryable status or a network error is RETRIED with backoff and jitter, which is
 *      what actually recovers a 429 rather than converting it into a hole.
 *   3. When the retries are exhausted the fetch THROWS, failing the build. A build that
 *      dies loudly is strictly better than one that publishes 219 dead links, and this is
 *      the deliberate opposite of the "stale beats empty" choice in the Lambda's own cache
 *      - there, the fallback is complete-but-slightly-old data; here, the fallback was an
 *      incomplete site.
 *
 * The bounded concurrency below addresses the cause rather than the symptom: 1089 per-slug
 * fetches issued as fast as nine Next workers can dispatch them is what produced the 429s
 * in the first place.
 * ------------------------------------------------------------------------- */

/** Statuses worth another attempt. 404 is handled separately; 4xx otherwise is fatal. */
const RETRYABLE_STATUS = new Set( [ 408, 425, 429, 500, 502, 503, 504 ] );
const MAX_ATTEMPTS = 6;
/**
 * A 429 GETS A LONGER BUDGET THAN A FAULT. It is the prod stage's default throttle (100 rps,
 * 200 burst; the blog routes have no override), which drains as soon as the burst passes.
 * Public UI compliance builds the site twice per run, in parallel, often while Amplify builds
 * the same commit, and run 40620178043 failed when one post stayed throttled for all six
 * attempts (about 12 s). Eight attempts with the delay capped at 15 s wait about 40 s before
 * giving up. A 5xx or network error keeps the six-attempt schedule, so an outage still fails
 * the build at the same speed.
 */
const MAX_THROTTLED_ATTEMPTS = 8;
const BASE_BACKOFF_MS = 400;
const MAX_BACKOFF_MS = 15000;

/**
 * In-flight request ceiling PER BUILD PROCESS.
 *
 * Next renders with multiple workers, so this is not a global limit and does not pretend to be.
 * Keep the per-process ceiling intentionally low: the build has previously failed after repeated
 * HTTP 429 responses while prerendering individual posts. With three render workers, a ceiling of
 * two keeps the aggregate burst near six instead of eighteen while still allowing useful overlap.
 */
const MAX_IN_FLIGHT = 2;
let inFlight = 0;
const waiting: Array<() => void> = [];

async function acquire (): Promise<void> {
  if ( inFlight < MAX_IN_FLIGHT )
  {
    inFlight += 1;
    return;
  }
  await new Promise<void>( ( resolve ) => waiting.push( resolve ) );
  inFlight += 1;
}

function release (): void {
  inFlight -= 1;
  const next = waiting.shift();
  if ( next ) next();
}

const sleep = ( ms: number ): Promise<void> =>
  new Promise( ( resolve ) => setTimeout( resolve, ms ) );

type Attempt =
  | { kind: 'ok'; body: any }
  /** A real 404. The post does not exist. */
  | { kind: 'absent' }
  | { kind: 'retry'; reason: string; throttled: boolean }
  | { kind: 'fatal'; reason: string };

async function attemptJson ( url: string ): Promise<Attempt> {
  await acquire();
  try
  {
    const response = await fetch( url, { headers: { Accept: 'application/json' } } );
    if ( response.status === 404 ) return { kind: 'absent' };
    if ( response.ok ) return { kind: 'ok', body: await response.json() };
    if ( RETRYABLE_STATUS.has( response.status ) )
    {
      return { kind: 'retry', reason: `HTTP ${ response.status }`, throttled: response.status === 429 };
    }
    return { kind: 'fatal', reason: `HTTP ${ response.status }` };
  } catch ( error: any )
  {
    // A network error, a DNS failure or an aborted socket. All transient in shape.
    return { kind: 'retry', reason: error?.name || 'network error', throttled: false };
  } finally
  {
    release();
  }
}

/**
 * Fetch JSON, retrying transient failures, and THROW rather than return empty.
 * Returns `null` only for a genuine 404.
 */
async function fetchJsonOrThrow ( url: string, label: string ): Promise<any | null> {
  for ( let attempt = 1; ; attempt += 1 )
  {
    const result = await attemptJson( url );
    if ( result.kind === 'ok' ) return result.body;
    if ( result.kind === 'absent' ) return null;
    if ( result.kind === 'fatal' )
    {
      throw new Error( `${ label }: ${ result.reason } (not retryable)` );
    }
    if ( attempt >= ( result.throttled ? MAX_THROTTLED_ATTEMPTS : MAX_ATTEMPTS ) )
    {
      throw new Error(
        `${ label }: gave up after ${ attempt } attempts (last: ${ result.reason }). `
        + 'Failing the build on purpose - continuing would emit an index that links pages '
        + 'which were never generated.'
      );
    }
    // Jittered exponential backoff. The jitter matters with nine workers backing off
    // together: without it they retry in lockstep and reproduce the burst that caused
    // the throttling.
    const delay = Math.min( BASE_BACKOFF_MS * 2 ** ( attempt - 1 ), MAX_BACKOFF_MS );
    await sleep( delay + Math.floor( Math.random() * BASE_BACKOFF_MS ) );
  }
}

/**
 * POSTS RETIRED BY AN APPROVED MERGE (config/blog-merges.json). Their URL answers 301 to the
 * post that stays, so they are dropped here, once, for every page that lists the corpus: no
 * /post/<from>/ page, no card, no pager or related link, and therefore no sitemap entry.
 */
const MERGED_AWAY = new Set( blogMerges.merges.map( merge => merge.from ) );

async function fetchAllPosts (): Promise<PublicBlogPost[]> {
  const body = await fetchJsonOrThrow( PUBLIC_BLOG_API, 'blog listing' );
  if ( !body?.ok || !Array.isArray( body.posts ) )
  {
    throw new Error( 'blog listing: response was not a post array' );
  }
  const posts: PublicBlogPost[] = body.posts;
  return posts.filter( post => !MERGED_AWAY.has( post.slug ) );
}

/**
 * The card list in the order the index shows it: newest first.
 *
 * SORTED HERE RATHER THAN TRUSTED FROM THE API, because pagination makes order load-bearing
 * in a way a single page did not. With one page, an inconsistent order shuffled cards; with
 * 35 pages, it can move a post between pages between builds, so a link to /blog/page/7/
 * silently comes to mean something else. Posts with no publishedDate sort last rather than
 * being dropped - a post with a missing date is a data problem, not a reason to hide it.
 */
export function listBlogCards ( posts: PublicBlogPost[] ): BlogCard[] {
  return orderPostsNewestFirst( posts ).map( toBlogCard );
}

/**
 * The corpus in index order, still as FULL posts.
 *
 * Extracted from listBlogCards so there is exactly one definition of "newest first" on the site.
 * The post page's newer/older pager walks the same sequence the index paginates, and it needs
 * fields the card projection drops - `tags`, for related posts - so it cannot go through
 * listBlogCards. Two comparators would be two orders, and the note above is explicit that order
 * is load-bearing here: a pager that disagreed with the index by one would offer a reader a
 * "newer" post that the listing shows as older.
 */
export function orderPostsNewestFirst ( posts: PublicBlogPost[] ): PublicBlogPost[] {
  return posts
    .slice()
    .sort( ( a, b ) => {
      const at = a.publishedDate ? Date.parse( a.publishedDate ) : NaN;
      const bt = b.publishedDate ? Date.parse( b.publishedDate ) : NaN;
      if ( Number.isNaN( at ) && Number.isNaN( bt ) ) return a.slug.localeCompare( b.slug );
      if ( Number.isNaN( at ) ) return 1;
      if ( Number.isNaN( bt ) ) return -1;
      return bt - at;
    } );
}

/** Total index pages for a post count. Always at least 1, so an empty blog still has /blog/. */
export function blogPageCount ( total: number ): number {
  return Math.max( 1, Math.ceil( total / POSTS_PER_PAGE ) );
}

/**
 * PER-SLUG BUILD-TIME MEMO. The same mechanism as postsPromise above, and it was missing
 * here, which cost roughly four times more upstream requests than the build needs.
 *
 * MEASURED, not guessed. API Gateway access logs for 24h on 2026-09-28:
 *
 *     185,576 requests to /seo-tools/blog-public*, all userAgent "node"
 *     890 distinct paths - exactly the 889 slugs plus the list endpoint
 *     each slug hit ~219 times, against 54 Amplify builds in the same window
 *
 * 219 / 54 is about 4 fetches of every slug per build. 117 of those requests came back
 * 429, so it was consuming API Gateway stage capacity from every other route on the API.
 *
 * WHY FOUR AND NOT ONE. Next renders with 9 workers and more than one page type resolves a
 * post: /post/[slug] via getStaticProps, and the blog index, its 35 paginated pages and the
 * per-category streams all sit on the same corpus. Without a memo each of those paths is an
 * independent fetch of the same document, and the module-level memo on the LIST call is
 * exactly why the list was not also multiplied.
 *
 * THE PER-SLUG FETCH ITSELF IS NECESSARY and must not be replaced by a filter over
 * listPublicBlogPosts(): the single-post response carries `content` and `richContent`, which
 * the list response omits. Checked against the live API rather than assumed. So the fix is
 * to fetch each slug once, not to stop fetching.
 *
 * NULL NOW MEANS ONE THING ONLY: a 404. It used to mean "no such post" OR "the request
 * failed", and conflating those is what put 219 dead links on the live site - see the long
 * note above `RETRYABLE_STATUS`. A failed request throws now, so a caller that receives
 * null can safely treat the post as genuinely absent.
 *
 * Caching the promise rather than the value also means concurrent callers share one
 * in-flight request instead of each starting their own, which is the normal case here
 * because Next renders pages in parallel. A rejection is evicted so a later caller retries.
 */
const postPromises = new Map<string, Promise<PublicBlogPost | null>>();

export async function getPublicBlogPost ( slug: string ): Promise<PublicBlogPost | null> {
  const cached = postPromises.get( slug );
  if ( cached ) return cached;
  const pending = fetchPost( slug );
  postPromises.set( slug, pending );
  try
  {
    const post = await pending;
    if ( post === null ) postPromises.delete( slug );
    return post;
  } catch ( error )
  {
    postPromises.delete( slug );
    throw error;
  }
}

async function fetchPost ( slug: string ): Promise<PublicBlogPost | null> {
  const body = await fetchJsonOrThrow(
    `${ PUBLIC_BLOG_API }/${ encodeURIComponent( slug ) }`, `post ${ slug }` );
  // `null` here is a 404 and nothing else, so /post/[slug] can safely turn it into
  // notFound. Every other failure has already thrown.
  if ( body === null ) return null;
  return body?.ok && body.post ? body.post : null;
}
