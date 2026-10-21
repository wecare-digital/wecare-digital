import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * GUARDS THE MECHANISM THAT PUT 219 DEAD LINKS ON THE LIVE SITE.
 *
 * `fetchPost` returned `null` for both "no such post" and "the request failed".
 * /post/[slug]'s getStaticProps turns `null` into `notFound: true`, and under
 * `output: 'export'` a notFound page is simply not emitted - silently. The LIST call had
 * succeeded, so the index pages still rendered a card and a link for every post.
 *
 * Measured on the 2026-09-29 build: 1089 posts listed, 870 pages emitted, 1089 links
 * rendered, 219 of them dead. 117 per-slug requests had come back 429 in a 24h window.
 *
 * The contract these tests pin down:
 *   - 404 means absent, and returns null.
 *   - 429 / 5xx / network errors are retried, then THROW. They must never become null.
 *   - a throw is not cached, so a later caller retries rather than inheriting it.
 *
 * Module state is per-import (the memos are module-level), so each test re-imports with
 * `vi.resetModules()` to get a clean memo.
 */

const API = 'https://wecare.digital/api/seo-tools/blog-public';

const post = ( slug: string ) => ( {
  slug, title: slug, excerpt: '', url: '', seoTitle: '', metaDescription: '',
  publishedDate: '2026-01-01T00:00:00.000Z', category: 'Conversations', tags: [],
} );

const jsonResponse = ( body: unknown, status = 200 ): Response => ( {
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
} as Response );

const load = async () => {
  vi.resetModules();
  return import( '../lib/public-blog' );
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach( () => {
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
  // Backoff is real time; make it instant so the retry tests do not sleep for seconds.
  vi.spyOn( globalThis, 'setTimeout' ).mockImplementation( ( ( handler: any ) => {
    handler();
    return 0 as any;
  } ) as any );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'a genuine 404 is the only thing that means "no such post"', () => {
  it( 'returns null for a 404', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 404 ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'never-existed' ) ).resolves.toBeNull();
  } );

  it( 'does not retry a 404', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 404 ) );
    const { getPublicBlogPost } = await load();
    await getPublicBlogPost( 'never-existed' );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'returns the post on a 200', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { ok: true, post: post( 'a-real-post' ) } ) );
    const { getPublicBlogPost } = await load();
    const result = await getPublicBlogPost( 'a-real-post' );
    expect( result?.slug ).toBe( 'a-real-post' );
  } );
} );

describe( 'a failed request throws rather than silently dropping the page', () => {
  it.each( [ 429, 500, 502, 503, 504, 408 ] )( 'throws on a persistent %i', async ( status ) => {
    fetchMock.mockResolvedValue( jsonResponse( {}, status ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'throttled' ) ).rejects.toThrow( /gave up after/ );
  } );

  it( 'throws on a persistent network error', async () => {
    fetchMock.mockRejectedValue( Object.assign( new Error( 'socket hang up' ),
      { name: 'FetchError' } ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'offline' ) ).rejects.toThrow( /gave up after/ );
  } );

  it( 'throws immediately on a non-retryable status', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 403 ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'forbidden' ) ).rejects.toThrow( /not retryable/ );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'never resolves to null for a throttled request', async () => {
    // The precise defect: 429 -> null -> notFound -> no page emitted, index still links it.
    fetchMock.mockResolvedValue( jsonResponse( {}, 429 ) );
    const { getPublicBlogPost } = await load();
    const result = await getPublicBlogPost( 'throttled' ).catch( () => 'threw' );
    expect( result ).toBe( 'threw' );
  } );
} );

describe( 'a transient failure recovers instead of becoming a hole', () => {
  it( 'allows a longer recovery window for a throttled post', async () => {
    fetchMock
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( { ok: true, post: post( 'late-recovery' ) } ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'late-recovery' ) ).resolves.toMatchObject( { slug: 'late-recovery' } );
    expect( fetchMock ).toHaveBeenCalledTimes( 6 );
  } );

  it( 'retries a 429 and succeeds', async () => {
    fetchMock
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( {}, 429 ) )
      .mockResolvedValueOnce( jsonResponse( { ok: true, post: post( 'recovered' ) } ) );
    const { getPublicBlogPost } = await load();
    const result = await getPublicBlogPost( 'recovered' );
    expect( result?.slug ).toBe( 'recovered' );
    expect( fetchMock ).toHaveBeenCalledTimes( 3 );
  } );

  it( 'retries a network error and succeeds', async () => {
    fetchMock
      .mockRejectedValueOnce( Object.assign( new Error( 'reset' ), { name: 'FetchError' } ) )
      .mockResolvedValueOnce( jsonResponse( { ok: true, post: post( 'recovered' ) } ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'recovered' ) ).resolves.not.toBeNull();
  } );
} );

describe( 'the listing does not degrade to an empty blog', () => {
  it( 'throws rather than returning [] when the listing keeps failing', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 503 ) );
    const { listPublicBlogPosts } = await load();
    await expect( listPublicBlogPosts() ).rejects.toThrow( /gave up after/ );
  } );

  it( 'throws when the listing returns a shape that is not a post array', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { ok: true, posts: 'nope' } ) );
    const { listPublicBlogPosts } = await load();
    await expect( listPublicBlogPosts() ).rejects.toThrow( /not a post array/ );
  } );

  it( 'returns the corpus on success and memoises it', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { ok: true, posts: [ post( 'a' ), post( 'b' ) ] } ) );
    const { listPublicBlogPosts } = await load();
    expect( await listPublicBlogPosts() ).toHaveLength( 2 );
    await listPublicBlogPosts();
    // One request for the whole build, which is the point of the memo.
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );
} );

describe( 'a rejection is not cached', () => {
  it( 'lets a later caller retry a slug that failed', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 503 ) );
    const { getPublicBlogPost } = await load();
    await expect( getPublicBlogPost( 'flaky' ) ).rejects.toThrow();
    const attemptsAfterFirst = fetchMock.mock.calls.length;

    fetchMock.mockResolvedValue( jsonResponse( { ok: true, post: post( 'flaky' ) } ) );
    await expect( getPublicBlogPost( 'flaky' ) ).resolves.not.toBeNull();
    expect( fetchMock.mock.calls.length ).toBeGreaterThan( attemptsAfterFirst );
  } );

  it( 'lets a later caller retry the listing', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {}, 503 ) );
    const { listPublicBlogPosts } = await load();
    await expect( listPublicBlogPosts() ).rejects.toThrow();
    fetchMock.mockResolvedValue( jsonResponse( { ok: true, posts: [ post( 'a' ) ] } ) );
    await expect( listPublicBlogPosts() ).resolves.toHaveLength( 1 );
  } );
} );

describe( 'concurrent callers share one request per slug', () => {
  it( 'does not multiply fetches for the same slug', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { ok: true, post: post( 'shared' ) } ) );
    const { getPublicBlogPost } = await load();
    await Promise.all( Array.from( { length: 8 }, () => getPublicBlogPost( 'shared' ) ) );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'bounds how many requests are open at once', async () => {
    let open = 0;
    let peak = 0;
    fetchMock.mockImplementation( async () => {
      open += 1;
      peak = Math.max( peak, open );
      await Promise.resolve();
      open -= 1;
      return jsonResponse( { ok: true, post: post( 'x' ) } );
    } );
    const { getPublicBlogPost } = await load();
    await Promise.all(
      Array.from( { length: 40 }, ( _, index ) => getPublicBlogPost( `slug-${ index }` ) ) );
    // The build runs multiple render workers, so this per-process ceiling has to stay low enough
    // that aggregate concurrency does not recreate the 429 burst that dropped post pages.
    expect( peak ).toBeLessThanOrEqual( 2 );
  } );
} );
