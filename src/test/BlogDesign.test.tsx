import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import BlogIndex from '../pages/blog/index';
import BlogIndexPage from '../pages/blog/page/[page]';
import BlogPostPage from '../pages/post/[slug]';
import { toBlogCard, blogPageCount, POSTS_PER_PAGE, type BlogCard, type PublicBlogPost } from '../lib/public-blog';
import type { BlogIndexPageProps } from '../lib/blog-index-props';
import { CONTRIBUTION_PRESETS_PAISE, paiseToRupees } from '../config/contribution';

vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );

const cssOf = ( container: HTMLElement ) =>
  Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

/**
 * ONE COMPONENT'S STYLE BLOCK, PICKED BY A SELECTOR ONLY IT DECLARES.
 *
 * cssOf joins every style element in the tree, and a blog page mounts four components that each
 * ship their own - RotatingHero, Breadcrumbs, BlogSearch and the view itself. That is fine for
 * asserting a rule is PRESENT, but it makes a negative assertion meaningless: checking that the
 * page carries no rgba(26,58,42,.25) focus ring failed on RotatingHero's stylesheet, not on the
 * one under test. Anything of the form "this component no longer contains X" has to be scoped.
 */
const styleBlockWith = ( container: HTMLElement, marker: string ) =>
  Array.from( container.querySelectorAll( 'style' ) )
    .map( node => node.textContent || '' )
    .find( text => text.includes( marker ) ) || '';

/**
 * CSS COMMENTS STRIPPED BEFORE A NEGATIVE ASSERTION - the same argument BrandAssets.test.ts
 * already makes about source comments, and it bit here for the same reason.
 *
 * styled-jsx keeps comments in its compiled output, and the comments in these style blocks NAME
 * the values they replaced: "Opaque focus ring, was rgba(26,58,42,.25)" and "It named
 * .category-switch button". A substring search cannot tell an explanation from a declaration, so
 * the first version of this failed on its own documentation. A rule against using a value must
 * not also be a rule against recording why it went, or the next person deletes the note to make
 * the suite green.
 */
const declarationsOnly = ( css: string ) => css.replace( /\/\*[\s\S]*?\*\//g, '' );

const samplePost: PublicBlogPost = {
  id: 'post-1',
  title: 'A Clear Question Can Change the Work',
  slug: 'a-clear-question-can-change-the-work',
  excerpt: 'A short excerpt that makes the listing readable without turning the card into UI chrome.',
  url: '/post/a-clear-question-can-change-the-work',
  category: 'Conversations',
  tags: [ 'Practice', 'Inquiry' ],
  authorName: 'Anew by WECARE.DIGITAL',
  publishedDate: '2026-09-27T00:00:00Z',
  seoTitle: 'A Clear Question Can Change the Work | WECARE.DIGITAL',
  metaDescription: 'A meta description that belongs to the post page head, not to a listing card.',
  robots: 'index, follow',
  modifiedDate: '2026-09-28T00:00:00Z',
  richContent: {
    nodes: [
      {
        type: 'PARAGRAPH',
        nodes: [ { type: 'TEXT', textData: { text: 'First paragraph.', decorations: [] } } ],
      },
      {
        type: 'PARAGRAPH',
        nodes: [ { type: 'TEXT', textData: { text: 'Second paragraph.', decorations: [] } } ],
      },
      {
        type: 'HEADING',
        headingData: { level: 2 },
        nodes: [ { type: 'TEXT', textData: { text: 'A section', decorations: [] } } ],
      },
    ],
  },
};

const secondPost: PublicBlogPost = {
  ...samplePost,
  id: 'post-2',
  title: 'A Guide to Better Decisions',
  slug: 'a-guide-to-better-decisions',
  category: 'Guides',
};

const firstCard = toBlogCard( samplePost );
const secondCard = toBlogCard( secondPost );

/**
 * Props for one index page, the way lib/blog-index-props.ts builds them: categories come from
 * the whole corpus and totalPosts is the corpus count, NOT this page's length. Tests that pass
 * a page's own cards as the corpus would never catch the bug those two fields exist to prevent.
 */
const propsFor = ( overrides: Partial<BlogIndexPageProps> = {} ): BlogIndexPageProps => ( {
  posts: [ firstCard, secondCard ],
  page: 1,
  totalPages: 1,
  totalPosts: 2,
  // Sorted; categories[0] is the default, served at /blog/. The rest are their own streams.
  categories: [ 'Conversations', 'Guides' ],
  categoryCounts: { Conversations: 1, Guides: 1 },
  // Server-decided, never client state - see the note in BlogIndexView.
  activeCategory: 'Conversations',
  defaultCategory: 'Conversations',
  ...overrides,
} );

/** Stand in for the lazily-fetched /blog/search-index.json. */
function mockSearchIndex ( posts: BlogCard[] ) {
  const fetchMock = vi.fn().mockResolvedValue( {
    ok: true,
    json: async () => ( { ok: true, count: posts.length, posts } ),
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'Blog design alignment', () => {
  /**
   * REWRITTEN WITH THE PAGE, AND THE INTENT IS UNCHANGED.
   *
   * This asserted that /blog/ matched the home page's hero typography by pinning blog-LOCAL
   * copies of those rungs: .blog-hero h1 reading "Blog", .blog-shell{max-width:1300px, a
   * clamp(36px,4.3vw,60px) h1 rule and a .blog-hero>p body rule. That was the right intent
   * pursued by duplication - the numbers were re-typed into this page, so they could drift
   * from the home page they were copied from and this test would have kept passing.
   *
   * The page now renders the actual RotatingHero the home page uses, so the typography cannot
   * drift: there is one declaration, in one component. The assertions therefore move from
   * "these numbers appear in this page's CSS" to "this page renders that component".
   *
   * THE ONE THING KEPT VERBATIM is the no-repeated-brand-eyebrow rule, because that is a
   * design decision rather than an implementation detail. The home page removed its own copy
   * of the lime badge for exactly this reason - it restated the header's lockup 109px below
   * it - so badgeLabel is deliberately not passed here, and RotatingHero renders no
   * .brand-badge without it.
   */
  it( 'renders the homepage rotating hero on /blog/, and still does not repeat the brand eyebrow', () => {
    const { container } = render( <BlogIndex { ...propsFor() } /> );

    // The shared hero, not a local copy of its numbers.
    expect( container.querySelector( '.rh-hero' ) ).not.toBeNull();
    expect( container.querySelector( '.rh-head' ) ).not.toBeNull();

    // The old markup is gone, along with the line that restated the heading.
    expect( container.querySelector( '.blog-hero' ) ).toBeNull();
    expect( container.textContent ).not.toContain( 'Ideas, guides and updates published' );

    // The brand lockup must not appear twice on the page: header owns it.
    expect( container.querySelector( '.brand-badge' ) ).toBeNull();
    expect( container.querySelector( '.eyebrow' ) ).toBeNull();

    // Exactly one h1, and it is the hero's - the page has no competing headline.
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );

    // The breadcrumb and the blog-scoped search box are both present.
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).not.toBeNull();
    expect( container.querySelector( 'form[role="search"]' ) ).not.toBeNull();
  } );

  /**
   * NO "ALL" PILL, AND THE FIRST CATEGORY IS THE DEFAULT. Owner instruction, and the corpus
   * supports it: measured live, 834 posts carry two categories - Conversations 824 (98.8%) and
   * Gastronomy 10 (1.2%). "All" selected 834 where the next pill selected 824, so the control
   * offered a choice between two lists that are the same list.
   */
  it( 'has no All pill, and the categories are links rather than buttons', () => {
    /*
     * "All" selected 864 posts where the next pill selected 824 - two options, one list - so it
     * went on owner instruction.
     *
     * LINKS, NOT BUTTONS, and that is the load-bearing part. Filtering the full-corpus pages
     * client-side to honour the instruction left 40 posts on no index page and rendered /blog/
     * with ZERO cards, because the 40 Gastronomy posts are the newest and filled page 1. Each
     * category is now its own prerendered stream, so the switch is navigation.
     */
    render( <BlogIndex { ...propsFor() } /> );

    expect( screen.queryByRole( 'button', { name: 'All' } ) ).toBeNull();
    // No buttons at all in the switch - if these are buttons again, the streams are gone.
    expect( screen.queryByRole( 'button', { name: 'Conversations' } ) ).toBeNull();

    // The active one is not a link, and says so to a screen reader.
    const here = document.querySelector( '.category-switch .cat-here' );
    expect( here?.textContent ).toContain( 'Conversations' );
    expect( here ).toHaveAttribute( 'aria-current', 'page' );

    // The other is a real href to its own stream.
    const other = screen.getByRole( 'link', { name: /Guides/ } );
    expect( String( other.getAttribute( 'href' ) ).replace( /\/$/, '' ) ).toBe( '/blog/topic/guides' );
  } );

  it( 'keeps the post count OFF the category pills, and on the line that reports it', () => {
    /*
     * REVERSED ON OWNER INSTRUCTION. This test used to assert the opposite - that each pill
     * showed its own size, "Conversations 824" - so it is inverted rather than deleted: the
     * count must now be absent from the pills, and the assertion is what stops it drifting back.
     *
     * It is asserted as "no digits in the nav" rather than "no <i> element", because the element
     * is an implementation detail and a future pill could reintroduce the number some other way.
     *
     * The second half matters as much as the first: `categoryCounts` is still a live prop, feeding
     * the search box's "N of M posts" denominator, so the count was moved off the pills rather
     * than deleted from the page. Without that assertion this test would pass just as well if the
     * counts had been ripped out altogether, which is not what was asked for. That line only
     * renders while a query is active - BlogSearch omits it when there is nothing to count - so
     * the search has to be driven to see it.
     */
    render( <BlogIndex { ...propsFor( { categoryCounts: { Conversations: 824, Guides: 40 } } ) } /> );

    const nav = document.querySelector( '.category-switch' );
    expect( nav?.textContent ).toContain( 'Conversations' );
    expect( nav?.textContent ).toContain( 'Guides' );
    expect( nav?.textContent ).not.toMatch( /\d/ );
    expect( nav?.querySelector( 'i' ) ).toBeNull();

    // The denominator still comes from categoryCounts, on the line that is meant to report it.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'a' } } );
    expect( document.querySelector( '.bs-count' )?.textContent ).toContain( 'of 824 posts' );
  } );

  it( 'needs no fetch to render a category stream, because the page IS the category', () => {
    /*
     * The payload win survives the change: a plain page view fetches nothing, because the
     * server already sliced this page to one category.
     */
    const fetchMock = mockSearchIndex( [ firstCard, secondCard ] );
    render( <BlogIndex { ...propsFor() } /> );
    expect( fetchMock ).not.toHaveBeenCalled();
    expect( screen.getByRole( 'heading', { name: samplePost.title } ) ).toBeInTheDocument();
  } );

  it( 'scopes a search to the category the reader is in', async () => {
    /*
     * The index covers all 864 posts, so it has to be narrowed: someone reading Conversations
     * who searches "paneer" should get nothing, not a Gastronomy post from a stream they are
     * not in.
     */
    mockSearchIndex( [ firstCard, secondCard ] );
    render( <BlogIndex { ...propsFor() } /> );
    const box = screen.getByLabelText( 'Search the blog' );

    fireEvent.change( box, { target: { value: 'Better Decisions' } } );
    await waitFor( () => {
      expect( screen.queryByRole( 'heading', { name: samplePost.title } ) ).toBeNull();
    } );
    // The Guides post matches the text but is in another stream, so it stays out.
    expect( screen.queryByRole( 'heading', { name: secondPost.title } ) ).toBeNull();

    fireEvent.change( box, { target: { value: 'Clear Question' } } );
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: samplePost.title } ) ).toBeInTheDocument();
    } );

    fireEvent.change( box, { target: { value: '   ' } } );
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: samplePost.title } ) ).toBeInTheDocument();
    } );
  } );

  /**
   * THE LISTING CARDS ARE ON THE HOME PAGE'S RUNGS, and this asserts the rungs rather than the
   * literal block strings it used to pin.
   *
   * It previously required 'h2{font-size:23px;line-height:1.22' and
   * '.post-copy p{font-size:16px;line-height:1.5' - two type sizes that existed nowhere else on
   * the public site - so the test was holding the drift in place: any attempt to move this grid
   * onto the shared scale failed the test that was meant to protect the design. What is worth
   * pinning is the relationship to the home page, so that is what it checks now.
   */
  it( 'puts listing cards on the home page type rungs, accent order and hover treatment', () => {
    const { container } = render( <BlogIndex { ...propsFor() } /> );
    // Scoped to BlogIndexView's own block: the negative assertions at the end of this test are
    // about what THIS component stopped declaring, and the page mounts three other components
    // that ship stylesheets of their own.
    const css = styleBlockWith( container, '.post-card{' );

    // The home card-heading rung, and the single body rung the whole public site shares.
    expect( css ).toContain( 'h2{font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px' );
    expect( css ).toContain( 'font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;' );
    // The home accent device, in the contract's order. The set is closed at these three.
    expect( css ).toContain( 'border-inline-start:3px solid #3da35a' );
    expect( css ).toContain( '.post-card:nth-child(3n+2){border-inline-start-color:#2563eb}' );
    expect( css ).toContain( '.post-card:nth-child(3n+3){border-inline-start-color:#9849e8}' );
    // The home CTA's hover: a 2px lift plus the one shadow this design language allows.
    expect( css ).toContain( '.post-card:hover{border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}' );
    // The home breakpoints, replacing the 1050/680 pair that disagreed with the hero above.
    expect( css ).toContain( '@media(max-width:1024px)' );
    expect( css ).toContain( '@media(max-width:767px)' );

    // The reduced-motion block has to reach the pills, which are next/link and therefore need
    // :global(). It used to name .category-switch button, which nothing has rendered since the
    // categories became routes, so a reader asking for less motion still got the lift.
    expect( css ).toContain( '.post-card,.category-switch :global(a){transition:none}' );
    expect( css ).toContain( 'outline:3px solid #1a3a2a' );

    // THREE REGRESSIONS THIS NOW GUARDS, asserted against declarations with the comments
    // stripped - see declarationsOnly. The translucent focus ring measures 1.51:1 against white
    // and fails WCAG 1.4.11, so the home page moved off it. 6b7280 is a dashboard token out of
    // tokens.css. And .category-switch button is the selector that matched nothing.
    const declared = declarationsOnly( css );
    expect( declared ).not.toContain( 'rgba(26,58,42,.25)' );
    expect( declared ).not.toContain( '#6b7280' );
    expect( declared ).not.toContain( '.category-switch button' );
  } );

  /**
   * NO PUBLISHED DATE ON ANY LISTING SURFACE. BlogIndexView renders /blog/, /blog/page/N/, both
   * topic-stream shapes AND the client-side search results, so this one assertion covers every
   * listing surface at once.
   *
   * Structural rather than textual on purpose: asserting the absence of a formatted string
   * would depend on the ICU build's en-IN output, whereas the element either exists or it does
   * not. The field itself must survive in the projection - the corpus is ordered by it, and with
   * 35 pages an ordering change moves posts between page URLs - which is why the toBlogCard
   * key-set test further down still expects publishedDate to be present.
   */
  it( 'renders no published date on listing cards, while keeping the field for ordering', () => {
    const { container } = render( <BlogIndex { ...propsFor() } /> );

    expect( container.querySelector( 'time' ) ).toBeNull();
    expect( container.querySelector( '[datetime]' ) ).toBeNull();
    // Still projected, because orderPostsNewestFirst reads it.
    expect( firstCard.publishedDate ).toBe( '2026-09-27T00:00:00Z' );
  } );
} );

/**
 * PAGINATION.
 *
 * /blog/ rendered all 834 posts in one document - 103,908px at 1280x900, and a build warning
 * on every run that its 842 kB of props exceeded the 128 kB threshold. These assertions pin
 * the three things that were easy to get wrong while splitting it, all of which would have
 * been invisible on a page that merely looked right:
 *
 *   1. Page 1 links to /blog/, never /blog/page/1/. A second URL for the same 24 cards is
 *      duplicate content, and every page is self-canonical, so both would be indexed.
 *   2. The paginator disappears while a search or category is active. Filtered results are
 *      already a narrowing and all matches are shown; paging them too would put two
 *      independent narrowings between a reader and one post.
 *   3. Search counts and searches the WHOLE corpus, not the page. "3 of 24" would be a lie
 *      about what was searched.
 */
describe( 'Blog pagination', () => {
  /*
   * All one category, and deliberately so: these cases are about paging, and mixing categories
   * in here would mean the default-category filter silently removed cards from every count. The
   * category behaviour has its own cases above.
   */
  const manyCards: BlogCard[] = Array.from( { length: 5 }, ( _, i ) => ( {
    slug: `post-${i + 1}`,
    title: `Post number ${i + 1}`,
    excerpt: `Excerpt for post ${i + 1}.`,
    category: 'Conversations',
  } ) );

  /**
   * TRAILING SLASHES ARE COMPARED LOOSELY HERE, ON PURPOSE.
   *
   * next.config.js sets trailingSlash:true, and next/link normalises against that config at
   * runtime - which jsdom does not load, so a Link given '/blog/' renders href="/blog" in
   * this environment and href="/blog/" in the export. Pinning the slash here would assert a
   * property of the test environment rather than of the site.
   *
   * The slash IS asserted, by routegraph.js, against the built HTML: its "MIXED TRAILING
   * SLASH - href without the slash trailingSlash:true emits" check reads the real hrefs out
   * of out/ and is currently 0. That is the right place for it - this test owns which page a
   * link points at, and routegraph owns how the URL is spelled.
   */
  const samePath = ( href: string | null ) => String( href ).replace( /\/$/, '' ) || '/';

  it( 'sends page 1 to /blog/ rather than to /blog/page/1/', () => {
    const { container } = render( <BlogIndexPage { ...propsFor( { posts: manyCards, page: 2, totalPages: 3, totalPosts: 60 } ) } /> );

    const newer = container.querySelector( 'a[rel="prev"]' );
    expect( newer ).not.toBeNull();
    expect( samePath( newer!.getAttribute( 'href' ) ) ).toBe( '/blog' );

    // And the numbered link for page 1 agrees with it - not /blog/page/1/.
    const one = Array.from( container.querySelectorAll( 'a.pager-num' ) )
      .find( node => node.textContent?.trim().endsWith( '1' ) );
    expect( samePath( one!.getAttribute( 'href' ) ) ).toBe( '/blog' );
  } );

  it( 'marks the current page and offers only the directions that exist', () => {
    const { container: first } = render( <BlogIndex { ...propsFor( { posts: manyCards, page: 1, totalPages: 3, totalPosts: 60 } ) } /> );
    // Page 1 has no previous page: the control is rendered so the row does not reflow, but it
    // is not a link and is hidden from the accessibility tree.
    expect( first.querySelector( 'a[rel="prev"]' ) ).toBeNull();
    expect( first.querySelector( '.pager-step.is-off[aria-hidden="true"]' ) ).not.toBeNull();
    expect( samePath( first.querySelector( 'a[rel="next"]' )!.getAttribute( 'href' ) ) ).toBe( '/blog/page/2' );
    // Scoped to the pager: Breadcrumbs marks its own last crumb aria-current="page", so an
    // unscoped query finds "Blog" first and would pass on page 1 for the wrong reason.
    expect( first.querySelector( '.pager [aria-current="page"]' )!.textContent ).toBe( '1' );

    const { container: last } = render( <BlogIndexPage { ...propsFor( { posts: manyCards, page: 3, totalPages: 3, totalPosts: 60 } ) } /> );
    expect( last.querySelector( 'a[rel="next"]' ) ).toBeNull();
    expect( samePath( last.querySelector( 'a[rel="prev"]' )!.getAttribute( 'href' ) ) ).toBe( '/blog/page/2' );
    expect( last.querySelector( '.pager [aria-current="page"]' )!.textContent ).toBe( '3' );
  } );

  it( 'hides the paginator while a search or a category is narrowing the list', async () => {
    mockSearchIndex( manyCards );
    const { container } = render( <BlogIndex { ...propsFor( { posts: manyCards, page: 1, totalPages: 3, totalPosts: 60 } ) } /> );

    expect( container.querySelector( 'nav[aria-label="Blog pages"]' ) ).not.toBeNull();

    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'number 3' } } );
    await waitFor( () => {
      expect( container.querySelector( 'nav[aria-label="Blog pages"]' ) ).toBeNull();
    } );
    // The grid relabels itself, so a screen reader is told these are matches and not the page.
    expect( container.querySelector( 'section[aria-label="Matching posts"]' ) ).not.toBeNull();

    // Clearing the query brings the paginator back.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: '' } } );
    await waitFor( () => {
      expect( container.querySelector( 'nav[aria-label="Blog pages"]' ) ).not.toBeNull();
    } );
  } );

  it( 'searches every published post, not just the page in front of the reader', async () => {
    /**
     * THE CASE THIS EXISTS FOR. The page carries 2 cards; the corpus has 5. A search for a
     * post that is NOT on this page must find it, which is only possible via the lazily
     * fetched index - and the announced count must be against the corpus. Before pagination
     * this was free because every post was in the page; it is now the thing most likely to
     * regress, and it would regress silently.
     */
    const fetchMock = mockSearchIndex( manyCards );
    render( <BlogIndex { ...propsFor( {
      posts: manyCards.slice( 0, 2 ), page: 1, totalPages: 3, totalPosts: 5,
      // The announced denominator is the ACTIVE CATEGORY's corpus count, not the whole corpus:
      // with "All" gone, "3 of 834" would be counting a list the reader is not looking at.
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 5 },
    } ) } /> );

    // Nothing is fetched for a plain page view.
    expect( fetchMock ).not.toHaveBeenCalled();

    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'number 5' } } );

    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Post number 5' } ) ).toBeInTheDocument();
    } );
    expect( fetchMock ).toHaveBeenCalledWith( '/blog/search-index.json', expect.anything() );
    // Counted against all 5, not against the 2 on this page.
    expect( screen.getByText( '1 of 5 posts' ) ).toBeInTheDocument();

    // And it is fetched ONCE however much more is typed.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'number' } } );
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Post number 4' } ) ).toBeInTheDocument();
    } );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'says so when the search index cannot be loaded instead of silently searching one page', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 502, json: async () => ( {} ) } ) );
    render( <BlogIndex { ...propsFor( { posts: manyCards.slice( 0, 2 ), page: 1, totalPages: 3, totalPosts: 5 } ) } /> );

    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'number' } } );

    await waitFor( () => {
      expect( screen.getByRole( 'status' ).textContent ).toContain( 'could not be loaded' );
    } );
    // It still filters what it has rather than showing nothing.
    expect( screen.getByRole( 'heading', { name: 'Post number 1' } ) ).toBeInTheDocument();
  } );

  /**
   * SEARCH MATCHES TAGS, AND THIS IS THE CASE IT EXISTS FOR.
   *
   * The fixture is built so the query appears in NEITHER the title NOR the excerpt - only in the
   * tags. Before tags were matched, every one of these searches returned "No posts match that
   * search" against a corpus full of them, which reads as a broken box rather than an honest miss.
   * Tagging is universal on this corpus, and the tags hold exactly the words a reader types.
   */
  it( 'finds a post by a tag that appears nowhere in its title or excerpt', async () => {
    const tagged: BlogCard[] = [
      {
        slug: 'daikon-tea', title: 'Daikon Tea', excerpt: 'A quiet cup at the end of a long day.',
        category: 'Conversations', tags: [ 'Herbal Tea', 'Beverages' ],
      },
      {
        slug: 'a-clear-question', title: 'A Clear Question', excerpt: 'On asking better.',
        category: 'Conversations', tags: [ 'Practice' ],
      },
    ];
    mockSearchIndex( tagged );
    render( <BlogIndex { ...propsFor( {
      posts: tagged, totalPosts: 2, categories: [ 'Conversations' ], categoryCounts: { Conversations: 2 },
    } ) } /> );

    // "beverages" is a tag on the first post and appears in no visible text on either.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'beverages' } } );

    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Daikon Tea' } ) ).toBeInTheDocument();
    } );
    // And it is a filter, not a pass-through: the untagged-for-this-term post is gone.
    expect( screen.queryByRole( 'heading', { name: 'A Clear Question' } ) ).toBeNull();
  } );

  /**
   * TAG SEARCH ON A TOPIC STREAM, WHICH IS THE OTHER HALF OF THE CORPUS.
   *
   * The cases above all run with activeCategory at the default, which is what /blog/ serves. The
   * non-default categories are their own prerendered routes - /blog/topic/<slug>/ - and they pass a
   * different activeCategory through the same component. Both halves matter and they are not the
   * same size: measured on the built index, Conversations is 824 posts with 323 unique tags and
   * Gastronomy is 240 with 278, and each had 50 tag terms that previously matched nothing. The
   * Gastronomy ones are the more obviously broken - desserts, salads, beverages, condiments.
   */
  it( 'matches tags on a non-default topic stream too', async () => {
    const gastronomy: BlogCard[] = [
      {
        slug: 'daikon-tea', title: 'Daikon Tea', excerpt: 'A quiet cup.',
        category: 'Gastronomy', tags: [ 'Herbal Tea', 'Beverages' ],
      },
      {
        slug: 'milky-masala-chai', title: 'Milky Masala Chai', excerpt: 'Boiled long.',
        category: 'Gastronomy', tags: [ 'Chai', 'Beverages' ],
      },
    ];
    mockSearchIndex( gastronomy );
    render( <BlogIndex { ...propsFor( {
      posts: gastronomy, totalPosts: 2,
      categories: [ 'Conversations', 'Gastronomy' ],
      categoryCounts: { Conversations: 0, Gastronomy: 2 },
      // What /blog/topic/gastronomy/ passes: a non-default active category.
      activeCategory: 'Gastronomy', defaultCategory: 'Conversations',
    } ) } /> );

    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'beverages' } } );

    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Daikon Tea' } ) ).toBeInTheDocument();
    } );
    expect( screen.getByRole( 'heading', { name: 'Milky Masala Chai' } ) ).toBeInTheDocument();
  } );

  /**
   * A TAG MATCH MUST NOT LEAK ACROSS CATEGORIES. Search is scoped to the active stream - the rule
   * the code states as "a reader on Conversations searching paneer should get nothing, not a
   * Gastronomy post from a stream they are not in" - and matching tags gives that rule a new way to
   * be broken, because the index is the whole corpus and a tag is a much broader net than a title.
   * Without the category filter, searching "beverages" from Conversations would surface Gastronomy
   * posts, which is a reader being shown a stream they did not choose.
   */
  it( 'keeps a tag match inside the active category rather than leaking the whole corpus', async () => {
    const corpus: BlogCard[] = [
      {
        slug: 'daikon-tea', title: 'Daikon Tea', excerpt: 'A quiet cup.',
        category: 'Gastronomy', tags: [ 'Beverages' ],
      },
      {
        slug: 'a-clear-question', title: 'A Clear Question', excerpt: 'On asking better.',
        category: 'Conversations', tags: [ 'Practice' ],
      },
    ];
    mockSearchIndex( corpus );
    render( <BlogIndex { ...propsFor( {
      posts: [ corpus[ 1 ] ], totalPosts: 1,
      categories: [ 'Conversations', 'Gastronomy' ],
      categoryCounts: { Conversations: 1, Gastronomy: 1 },
      activeCategory: 'Conversations', defaultCategory: 'Conversations',
    } ) } /> );

    // "beverages" is a real tag in the corpus, but only on a Gastronomy post.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'beverages' } } );

    await waitFor( () => {
      expect( screen.getByText( 'No posts match that search.' ) ).toBeInTheDocument();
    } );
    expect( screen.queryByRole( 'heading', { name: 'Daikon Tea' } ) ).toBeNull();
  } );

  /**
   * A QUERY MUST NOT MATCH ACROSS THE GAP BETWEEN TWO FIELDS, and this test earned its place by
   * failing.
   *
   * The fields were first joined with a space, on the assumption that a match would still have to
   * fall inside one of them. That is not what a space does: "Herbal Tea" and "Spices" joined by one
   * become "Herbal Tea Spices", which contains "tea spices" - a phrase no post has, composed of the
   * end of one tag and the start of the next. This case caught it, and the join is a newline now,
   * which a typed query cannot contain.
   *
   * The same false positive existed between title and excerpt long before tags did, so fixing the
   * separator fixed both.
   */
  it( 'does not let a query match across the gap between two tags', async () => {
    const tagged: BlogCard[] = [ {
      slug: 'yogi-tea', title: 'Tea Fit for a Yogi', excerpt: 'Warmth without weight.',
      category: 'Conversations', tags: [ 'Herbal Tea', 'Spices' ],
    } ];
    mockSearchIndex( tagged );
    render( <BlogIndex { ...propsFor( {
      posts: tagged, totalPosts: 1, categories: [ 'Conversations' ], categoryCounts: { Conversations: 1 },
    } ) } /> );

    const box = screen.getByLabelText( 'Search the blog' );

    // Each tag on its own is found.
    fireEvent.change( box, { target: { value: 'spices' } } );
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Tea Fit for a Yogi' } ) ).toBeInTheDocument();
    } );

    // The seam between them is not.
    fireEvent.change( box, { target: { value: 'tea spices' } } );
    await waitFor( () => {
      expect( screen.queryByRole( 'heading', { name: 'Tea Fit for a Yogi' } ) ).toBeNull();
    } );
  } );

  it( 'projects a post down to what a card renders or search matches, and drops the rest', () => {
    const card = toBlogCard( samplePost ) as unknown as Record<string, unknown>;

    /*
     * `tags` IS IN THIS LIST NOW, and it is the only field here that is carried for SEARCH rather
     * than for rendering - nothing prints it. It was dropped originally on the grounds that no card
     * renders it, which was true and still is; what that missed is that search matches more than
     * what is visible. Every post carries tags and they hold the words readers type, so leaving
     * them out made "Beverages" or "Chai" return nothing on a corpus full of both.
     */
    expect( Object.keys( card ).sort() ).toEqual(
      [ 'authorName', 'category', 'excerpt', 'publishedDate', 'slug', 'tags', 'title' ]
    );

    // Dropped: the post page's head fields and the crawler hints. These were 357 kB of the
    // 842 kB payload across 834 posts, and no listing card ever rendered one of them.
    for ( const field of [ 'metaDescription', 'seoTitle', 'robots', 'modifiedDate', 'url', 'id', 'richContent' ] ) {
      expect( card ).not.toHaveProperty( field );
    }

    // An empty tag array is not carried: it would be bytes on every record for nothing.
    const untagged = toBlogCard( { ...samplePost, tags: [] } ) as unknown as Record<string, unknown>;
    expect( untagged ).not.toHaveProperty( 'tags' );
  } );

  it( 'never reports zero pages, so an empty blog still has a /blog/', () => {
    expect( blogPageCount( 0 ) ).toBe( 1 );
    expect( blogPageCount( 1 ) ).toBe( 1 );
    expect( blogPageCount( POSTS_PER_PAGE ) ).toBe( 1 );
    expect( blogPageCount( POSTS_PER_PAGE + 1 ) ).toBe( 2 );
    // The live corpus at the time of the split.
    expect( blogPageCount( 834 ) ).toBe( 35 );
  } );
} );

describe( 'Blog post page', () => {
  it( 'uses a reading measure and paragraph rhythm appropriate for long-form posts', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    expect( css ).toContain( '.article-shell{max-width:1300px' );
    expect( css ).toContain( 'article{max-width:700px' );
    expect( css ).toContain( 'h1{font-size:clamp(36px,4.3vw,60px);line-height:1.04;letter-spacing:-0.04em;color:rgba(0,0,0,.95)' );
    expect( css ).toContain( 'text-wrap:balance;max-width:20ch' );
    expect( css ).toContain( 'font-size:20px;line-height:1.55;letter-spacing:-.125px' );
    expect( css ).toContain( '.content :global(p + p){margin-top:28px}' );
  } );

  it( 'finishes the rich-content styles for headings, lists, quotes and accessible links', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    expect( css ).toContain( '.content :global(h2){font-size:30px;line-height:1.15' );
    expect( css ).toContain( '.content :global(ul),.content :global(ol){margin:28px 0;padding-inline-start:1.4em}' );
    expect( css ).toContain( '.content :global(li + li){margin-top:10px}' );
    expect( css ).toContain( '.content :global(blockquote){margin:36px 0;padding:2px 0 2px 22px;border-inline-start:3px solid #d1f470;font-size:21px;line-height:1.5;' );
    /*
     * THE CONTENT LINK RING IS OPAQUE, AND THIS IS THE LAST OF THE TRANSLUCENT FAMILY.
     *
     * It was rgba(26,58,42,.25), which composites to rgb(205,212,208) over the white article
     * column and measures 1.51:1 against it - well under the 3:1 WCAG 1.4.11 asks of a focus
     * indicator. Opaque #1a3a2a on white is 12.48:1. Body copy is the one place a keyboard
     * user follows links continuously, so a ring they cannot see is worst here.
     *
     * `.post-related-all` in this same file was already opaque, so the page shipped two
     * different focus treatments; that inconsistency is what made this one easy to miss.
     * Eighteen rings across thirteen files were on the translucent value and all are now
     * #1a3a2a. Do not reintroduce an alpha - outline-offset is what softens a ring, and it
     * costs no contrast.
     */
    expect( css ).toContain( '.content :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}' );
    // Scoped to this component's own style block and stripped of comments, because the note
    // above names the value it replaced - see styleBlockWith and declarationsOnly at the top.
    expect( declarationsOnly( styleBlockWith( container, '.content :global(a:focus-visible)' ) ) )
      .not.toContain( 'rgba(26,58,42,.25)' );
  } );

  /**
   * THE BYLINE IS AUTHOR-ONLY, AND THE STRUCTURED DATA IS NOT.
   *
   * The visible date is gone from the byline on owner instruction. datePublished and
   * dateModified stay in the BlogPosting JSON-LD deliberately: they are machine-readable, a
   * reader never sees them, Google treats datePublished as recommended on an article, and the
   * stored-schema branch could not be stripped from the page anyway - when the API supplies
   * post.jsonLd.blogPosting that object is emitted verbatim. Asserting both halves here stops a
   * later "finish the job" sweep taking the schema fields with the visible ones.
   */
  it( 'shows no date in the byline but keeps the dates in the article structured data', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    expect( container.querySelector( 'time' ) ).toBeNull();
    expect( container.querySelector( '[datetime]' ) ).toBeNull();
    expect( container.querySelector( '.byline' )?.textContent ).toBe( 'Anew by WECARE.DIGITAL' );

    /*
     * FINDS THE BlogPosting BLOCK, rather than trusting it to be the first one.
     *
     * This used to take `querySelector(...)` - the first JSON-LD block on the page - which was
     * the article only by accident of ordering. The post page now also emits the site-level
     * Organization and WebSite nodes, because _app.tsx's <Head> is suppressed on this route and
     * those entities were previously absent from all 1,279 posts; so the first block is the
     * Organization and the old assertion looked for `datePublished` in a company description.
     *
     * Selecting by @type is what the assertion always meant, and it is strictly stronger: the
     * dates now have to be on the article node specifically, not merely somewhere in the head.
     */
    const blocks = [ ...container.querySelectorAll( 'script[type="application/ld+json"]' ) ]
      .map( s => JSON.parse( s.textContent || '{}' ) );
    const article = blocks.find( b => b[ '@type' ] === 'BlogPosting' );
    expect( article ).toBeDefined();
    expect( article.datePublished ).toBeTruthy();
    expect( article.dateModified ).toBeTruthy();
    /*
     * `image` IS ASSERTED HERE TOO, because its absence was the defect that made every post
     * ineligible for the Article rich result. Google documents it as required on Article, the
     * asset was already in scope on the page for og:image, and the schema simply never received
     * it - on all 1,279 posts. A test that pins the dates but not the image would let the
     * expensive half regress silently.
     */
    expect( article.image?.url ).toMatch( /^https:\/\// );
    expect( article.publisher?.[ '@id' ] ).toContain( '#organization' );
    // And the referenced Organization must actually be defined on the same page, or the
    // publisher reference dangles. This is the pairing tools/audit/schemacheck.js enforces
    // across the whole export; asserted here so a unit run catches it first.
    expect( blocks.some( b => b[ '@type' ] === 'Organization' && b[ '@id' ] === article.publisher[ '@id' ] ) ).toBe( true );
  } );

  /**
   * RELATED POSTS READ AS THE LISTING'S CARDS. Same heading rung, same accent order, same hover.
   * The block was a single column of title-only boxes at every width; the grid, the spanning
   * third card and the lime CTA are the improvement, and this pins the parts that would
   * otherwise drift back.
   */
  it( 'lays related posts out as home-style cards with a spanning third and a lime CTA', () => {
    const { container } = render(
      <BlogPostPage
        post={ samplePost }
        related={ [
          { slug: 'first-related', title: 'The First Related Post' },
          { slug: 'second-related', title: 'The Second Related Post' },
          { slug: 'third-related', title: 'The Third Related Post' },
        ] }
        streamHref="/blog/"
        streamLabel="Conversations"
      />
    );
    const css = cssOf( container );

    // All three render, and the section is still labelled by its own eyebrow heading.
    expect( container.querySelectorAll( '.post-related-card' ) ).toHaveLength( 3 );
    expect( screen.getByRole( 'heading', { name: 'More in Conversations' } ) ).toBeInTheDocument();

    // Two columns, with an odd last card taking the full measure rather than sitting
    // half-width beside empty space.
    expect( css ).toContain( '.post-related-list{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}' );
    expect( css ).toContain( '.post-related-list li:last-child:nth-child(odd){grid-column:1 / -1}' );

    // The home card-heading rung and the home accent order, matching the listing grid.
    expect( css ).toContain( '.post-related-card h3{margin:0;flex:1;font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px}' );
    expect( css ).toContain( '.post-related-card:nth-child(2){border-inline-start-color:#2563eb}' );
    expect( css ).toContain( '.post-related-card:nth-child(3){border-inline-start-color:#9849e8}' );
    expect( css ).toContain( '.post-related-card:hover{border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}' );

    // The closing link is the home CTA object, and its focus ring is the opaque one.
    expect( css ).toContain( 'border:2px solid #1a3a2a;border-radius:50px;background:#d1f470;' );
    expect( css ).toContain( '.post-related :global(.post-related-all:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}' );

    // Nothing lifts for a reader who asked for less motion - this page had no such block.
    expect( css ).toContain( '@media(prefers-reduced-motion:reduce)' );
  } );

  /**
   * THE WHATSAPP SUBSCRIBE BUTTON AND CONTRIBUTION SIT BETWEEN TAGS AND SHARE, in that order.
   *
   * The in-page subscriber form was removed in favour of a single button that opens a WhatsApp
   * conversation (a.blog-wa-subscribe, href wa.me/message/BEA3HNW3LNM3A1). It sits where the box used to,
   * so the end of the article is content -> Tags -> WhatsApp subscribe -> Contribution -> Share.
   * Document position is asserted rather than mere presence so either block moving silently fails.
   */
  it( 'renders the WhatsApp subscribe button above Contribution, between Tags and Share', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    const tags = container.querySelector( 'nav.tags' );
    const subscribe = container.querySelector( 'a.blog-wa-subscribe' );
    const contribution = container.querySelector( 'section.bc' );
    const share = container.querySelector( '.post-share' );

    expect( tags ).not.toBeNull();
    expect( subscribe ).not.toBeNull();
    expect( contribution ).not.toBeNull();
    expect( share ).not.toBeNull();

    // The in-page signup box is gone; nothing renders section.blog-subscribe any more.
    expect( container.querySelector( 'section.blog-subscribe' ) ).toBeNull();

    // The button points directly at the WhatsApp subscribe deep link.
    expect( subscribe!.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/BEA3HNW3LNM3A1' );

    expect( tags!.compareDocumentPosition( subscribe! ) & Node.DOCUMENT_POSITION_FOLLOWING )
      .toBeTruthy();
    expect( subscribe!.compareDocumentPosition( contribution! ) & Node.DOCUMENT_POSITION_FOLLOWING )
      .toBeTruthy();
    expect( contribution!.compareDocumentPosition( share! ) & Node.DOCUMENT_POSITION_FOLLOWING )
      .toBeTruthy();

    // The reveal sentinel is untouched: shareRef still names .post-share.
    expect( share!.classList.contains( 'post-share' ) ).toBe( true );
  } );

  /**
   * THE MANDATED COPY, AND NO SECOND H1. The heading and primary message are fixed strings in the
   * brief; the heading must be an h2 so the post keeps exactly one h1 (htmlcheck guards H1-MANY).
   */
  it( 'shows the Contribute heading and message, and adds no second h1', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    const block = container.querySelector( 'section.bc' )!;
    expect( block.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( block.textContent ).toContain(
      'If you found this useful, you\u2019re welcome to make a small voluntary contribution.'
    );
    // Still exactly one h1 on the whole page - the title - and the contribution added none.
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( block.querySelector( 'h1' ) ).toBeNull();
  } );

  /**
   * THE PRESET AMOUNTS COME FROM THE CENTRAL CONFIG, not from literals re-typed into the page.
   * Reading them from src/config/contribution.ts here is the same move ShareMeta.test.tsx makes
   * for the share card: the test holds the rendered values equal to the one source.
   */
  it( 'renders the preset amounts from the central contribution config', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const faces = Array.from( container.querySelectorAll( 'section.bc .bc-choice-face' ) )
      .map( n => n.textContent || '' );

    for ( const paise of CONTRIBUTION_PRESETS_PAISE ) {
      expect( faces.some( f => f.includes( String( paiseToRupees( paise ) ) ) ) ).toBe( true );
    }
    // The common contribution UI is preset-only; there is no separate custom option.
    expect( faces.some( f => f.includes( 'Other' ) ) ).toBe( false );
    expect( faces ).toEqual( [ '₹100', '₹250', '₹500' ] );
  } );
} );

/**
 * THE PILLS ARE ON THE HOME PAGE'S LANGUAGE, AND EACH VALUE HERE IS THE REASON WHY.
 *
 * Before this, the blog carried four pill treatments that agreed with nothing: tag chips at
 * 11px on an off-palette #f3f4f6 with no border, a category badge at 11px/700 on a lime alpha
 * that does not exist in the design language, category-switch pills at 13px with POSITIVE
 * letter-spacing, and the same category badge styled two different ways on the listing card
 * and on the post itself.
 *
 * The contract they are measured against is `.kiro/steering/grahak-os-design.md`:
 *
 *   - Exactly THREE lime treatments. `#d1f470` fill + `#1a3a2a` type for our own surfaces,
 *     `rgba(209,244,112,.22)` for transient state, `#1a3a2a` fill + `#d1f470` type inverted.
 *     The contract says in as many words not to invent an in-between alpha, naming `#f2fbf6`
 *     and `#fbfff0` as what happened last time. `.28` was a fourth value in four places.
 *   - Hairline weight carries meaning: `2px` hoverable, `1px` static, colour always `#e5e7eb`.
 *   - Labels are not uppercase and not letter-spaced.
 *   - `BrandBadge` is the lime identity rung: 14px/600/-.125px, no border.
 *
 * Measured after, in a browser: category-switch 12.48:1, `.cat-here` 10.04:1, both category
 * badges 10.04:1, tag chips 4.59:1 — up from 4.49:1, which failed the 4.5:1 AA minimum for
 * normal text by 0.01. Moving the chips onto the palette fixed a contrast miss as a side
 * effect rather than needing a darker grey.
 */
describe( 'Blog pills sit on the home page design language', () => {
  it( 'gives tag chips the static hairline and the label rung', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    // 2px, NOT 1px, and the two halves of that rule are the history of this pill. The hairline
    // weight carries meaning: 2px hoverable, 1px static. These began as spans and were correctly
    // 1px, because nothing happened when you moused over them. They are links now - each one
    // navigates to /blog/?q=<tag> - so they are hoverable controls and take the 2px edge that
    // .pill, .pp-pill and .category-switch carry.
    // #fff rather than #f3f4f6: the palette's grey is #e5e7eb, and this repo has already
    // retired #4b5563 and #9ca3af from that same Tailwind family.
    // Weight 400, not 600: these are metadata, so they take the contract's label spec rather
    // than BrandBadge's identity weight.
    // :global() because they are next/link - styled-jsx does not scope a composite component.
    expect( css ).toContain( 'background:#fff;border:2px solid #e5e7eb;border-radius:999px;' );
    expect( declarationsOnly( styleBlockWith( container, '.tags :global(a)' ) ) ).not.toContain( '#f3f4f6' );
  } );

  it( 'keeps the tag row on one line and lets it scroll instead of wrapping', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    // THE DEFECT: flex-wrap:wrap. Six tags on a phone grew the row to three lines and pushed
    // the footer down, and on a landscape phone it wrapped while the width sat there unused.
    // nowrap + overflow-x:auto is what .category-switch on /blog/ already does, so this is the
    // site's existing answer to the same problem rather than a new one.
    expect( css ).toContain( 'display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;' );
    expect( declarationsOnly( styleBlockWith( container, '.tags{' ) ) ).not.toContain( 'flex-wrap:wrap' );

    // padding-bottom is for the FOCUS RING, not for looks: a scroll container clips its
    // children, and these carry a 3px outline at 2px offset. Without the room the ring on a
    // focused tag is sliced off at the container edge.
    expect( css ).toContain( 'padding:26px 0 6px' );

    // DIRECTION IS NOT HARD-CODED. overflow-x on a flex row follows the document dir, so the
    // row starts at the right and scrolls leftward under the RTL languages SupportWidget
    // switches to. A direction or margin-left declaration here would break that.
    const tagBlock = declarationsOnly( styleBlockWith( container, '.tags{' ) );
    expect( tagBlock ).not.toContain( 'direction:rtl' );
    expect( tagBlock ).not.toContain( 'margin-left' );
  } );

  it( 'gives the tag pills the home page hover, and drops only the lift under reduced motion', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    // The same four properties .category-switch and the home closing CTA move, at the same .2s:
    // lime border, the .22 state tint, a 2px lift and the one shadow this language uses. The
    // label also darkens from the muted rgba(0,0,0,.54) to solid #1a3a2a at 12.48:1, because a
    // control being pointed at should read as active rather than as quiet metadata.
    expect( css ).toContain( 'border-color:#d1f470;background:rgba(209,244,112,.22);color:#1a3a2a;' );
    expect( css ).toContain( 'transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);' );

    // Hover AND focus-visible share the rule, so a keyboard user gets what a mouse user gets.
    expect( css ).toContain( '.tags :global(a:hover),.tags :global(a:focus-visible)' );

    // Under reduced motion the lift goes and the feedback stays - transform is the part a
    // reader who asked for less motion should not get; the colour change still answers.
    expect( css ).toContain( '.tags :global(a:hover),.tags :global(a:focus-visible){transform:none;box-shadow:none}' );
  } );

  it( 'colours each tag from the contract accents, by tag name rather than by position', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    // THE HUE IS IN THE DOT ONLY, and the border stays the neutral hairline.
    // An earlier pass coloured the border too and it was too loud - a 2px saturated edge runs
    // the whole perimeter, so several tags in different hues competed with the post rather than
    // labelling it. The 7px dot carries the same information for a fraction of the ink.
    // The consistency argument is the stronger one: .pill, .pp-pill and .category-switch all
    // rest on 2px #e5e7eb, so a coloured resting edge made tags the ONLY pill on the site with
    // one - the opposite of matching the home page.
    expect( css ).toContain( '.tags :global(.tag-h0)::before{background:#3da35a}' );
    expect( css ).toContain( '.tags :global(.tag-h1)::before{background:#2563eb}' );
    expect( css ).toContain( '.tags :global(.tag-h2)::before{background:#9849e8}' );
    expect( css ).toContain( '.tags :global(.tag-h3)::before{background:#dc2626}' );
    // No accent on the resting border. Comments stripped, since the note above names the
    // treatment it replaced.
    const tagDecls = declarationsOnly( styleBlockWith( container, '.tag-h0' ) );
    expect( tagDecls ).not.toContain( '.tag-h0){border-color' );
    expect( tagDecls ).not.toContain( '.tag-h3){border-color' );

    // FOUR hues, not five. Amber #f0a818 is the one the hero pills use that is excluded here:
    // 2.04:1 on white, the ratio the contract records as the reason it was rejected for light
    // surfaces. The other four clear the 3:1 WCAG 1.4.11 asks of an identifying graphic.
    expect( declarationsOnly( styleBlockWith( container, '.tag-h0' ) ) ).not.toContain( '#f0a818' );

    // The dot is the hero pill's other half. The TINT is deliberately not carried over: the
    // label is rgba(0,0,0,.54) at 4.61:1 on white, which clears 4.5:1 with almost nothing
    // spare, and over a pale tint it drops under - these pills were on #f3f4f6 and measured
    // 4.49:1, failing by 0.01. So the ground stays white and the hue arrives as dot + border.
    expect( css ).toContain( 'content:\'\';flex:0 0 auto;width:7px;height:7px;border-radius:50%;' );
    expect( css ).toContain( 'background:#fff;border:2px solid #e5e7eb;border-radius:999px;' );

    // A hue per TAG, not per position. .post-card cycles by nth-child, which is right for a
    // card in a stream; for a tag it would colour the same word differently on each post and
    // spend the colour without buying the recognition it is for.
    const cls = Array.from( container.querySelectorAll( '.tags a' ) ).map( a => a.getAttribute( 'class' ) || '' );
    expect( cls.length ).toBeGreaterThan( 0 );
    cls.forEach( c => expect( c ).toMatch( /tag-h[0-3]\b/ ) );

    // AND NO NEGATIVE INDEX. The first version hashed with & 0xffffffff, which in JavaScript is
    // a SIGNED 32-bit integer, and -5 % 4 is -1 - so tags produced class names like tag-h-1
    // that match no rule and fell back to neutral grey. Two of three tags on one post were
    // grey. It passed its own check because that check was written in Python, where the mask is
    // unsigned. This assertion is the one that would have caught it.
    cls.forEach( c => expect( c ).not.toMatch( /tag-h-/ ) );
  } );

  it( 'points each tag at the search that already uses tags, not at a route it invented', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    // There is no /blog/tag/<x>/ route, and the destination does not need inventing:
    // generate-blog-search-index.js records that `tags` is requested FOR SEARCH rather than for
    // display. BlogSearch is a form with action="/blog/" method="get" and name="q", so /blog/?q=
    // is a real target that also works with JavaScript off.
    const hrefs = Array.from( container.querySelectorAll( '.tags a' ) ).map( a => a.getAttribute( 'href' ) );
    expect( hrefs.length ).toBeGreaterThan( 0 );
    // The slash is optional in this assertion ON PURPOSE. next.config.js sets trailingSlash,
    // so the exported HTML carries /blog/?q=, but next/link under jsdom renders /blog?q= - the
    // normalisation happens in the router, not in the component. Pinning the built form here
    // would fail on a correct component, so the assertion covers the part that matters: it is
    // the blog index with a q parameter, not an invented /blog/tag/ route.
    hrefs.forEach( h => expect( h ).toMatch( /^\/blog\/?\?q=/ ) );
    // Encoded, so a tag with a space or an ampersand does not break the query.
    expect( hrefs.some( h => h && /%20|\+/.test( h ) ) || hrefs.every( h => !/ /.test( h || '' ) ) ).toBe( true );
    // A landmark with a name, copying .category-switch - not a heading, which would collide with
    // typecheck.js's assertion that every section h2 sits on the 40px/700 rung.
    const nav = container.querySelector( 'nav.tags' );
    expect( nav ).not.toBeNull();
    expect( nav?.getAttribute( 'aria-label' ) ).toBe( 'Tags on this post' );
  } );

  it( 'gives the category badge the full lime voice, because it is identity', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const css = cssOf( container );

    // The fill, not the .22 tint. BrandBadge went through exactly this move: it began on .22
    // and was lifted because that value composites to (245,253,224) over white - a wash that
    // reads as barely-not-white rather than as a green badge. A category badge naming the
    // post's category is identity, so it has the same requirement and takes the same answer.
    // No border, which .tab.active, .msg.sent and BrandBadge also carry none of.
    expect( css ).toContain( '.category{display:inline-block;background:#d1f470;color:#1a3a2a;border-radius:999px;padding:6px 12px;font-size:14px;font-weight:600;letter-spacing:-.125px;margin-bottom:18px}' );
  } );

  it( 'keeps every lime state tint on the one documented alpha', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    // Hover IS the right place for a tint - transient state is exactly what .22 is for. What
    // was wrong was the alpha. Comments stripped: the notes at those rules name the .28 they
    // replaced, and a substring search cannot tell a citation from a declaration.
    const declared = declarationsOnly( cssOf( container ) );
    expect( declared ).not.toContain( 'rgba(209,244,112,.28)' );
    expect( declared ).toContain( 'rgba(209,244,112,.22)' );
  } );
} );
