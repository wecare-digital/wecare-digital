import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import BlogIndex from '../pages/blog/index';
import BlogIndexPage from '../pages/blog/page/[page]';
import BlogPostPage from '../pages/post/[slug]';
import ProductBlogPanel from '../components/ProductBlogPanel';
import { CONTRIBUTION_AMOUNT_LABEL } from '../config/contribution';
import { toBlogCard, blogPageCount, POSTS_PER_PAGE, type BlogCard, type PublicBlogPost } from '../lib/public-blog';
import type { BlogIndexPageProps } from '../lib/blog-index-props';
/* CONTRIBUTION_CHOICES was imported here to hold the rendered amount pills equal to the central
   config. The pills were removed on owner instruction (2026-10-10) when the contribution block
   became a single WhatsApp link, so there is nothing on this page left to compare against it.
   The config is unchanged and still pinned in src/test/BlogContribution.test.tsx. */

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

/** Stand in for the full post list at /blog/search-index.json, fetched by the index on mount. */
function mockSearchIndex ( posts: BlogCard[] ) {
  const fetchMock = vi.fn().mockResolvedValue( {
    ok: true,
    json: async () => ( { ok: true, count: posts.length, posts } ),
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

/**
 * BlogIndexView fetches /blog/search-index.json ON MOUNT now (it was lazy, on the first
 * keystroke, while the search box existed). Every render of the index therefore touches fetch,
 * so the suite installs a harmless default - an empty list that leaves the prerendered slice in
 * place - and the cases that care about the full list override it with mockSearchIndex. Without
 * this, a plain render would call an undefined global and reject unhandled.
 */
beforeEach( () => {
  vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
    ok: true,
    json: async () => ( { ok: true, count: 0, posts: [] } ),
  } ) );
} );

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

    // The breadcrumb is present. The borderless live search is back (owner instruction): a real
    // labelled input, no inner border, no icon, no submit button - the /anew/ panel's field - so
    // it is NOT a form[role="search"] (that was the old GET-form search). It is found by its
    // accessible name instead.
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).not.toBeNull();
    expect( container.querySelector( 'form[role="search"]' ) ).toBeNull();
    expect( screen.getByLabelText( 'Search the blog' ) ).toBeInTheDocument();
    expect( container.querySelector( '.blog-search input[type="search"]' ) ).not.toBeNull();

    // The RSS affordance is now ICON-ONLY and at the BOTTOM: a plain <a> to the feed
    // /blog/rss.xml (an XML file a build script writes to out/, not a Next route), containing an
    // SVG glyph and a visually-hidden label - no visible "Subscribe via RSS" text. The old top
    // text pill (.blog-rss) and the "N posts" count (.blog-count) are gone.
    expect( container.querySelector( '.blog-rss' ) ).toBeNull();
    expect( container.querySelector( '.blog-count' ) ).toBeNull();
    const rss = container.querySelector( 'a.rss-icon' );
    expect( rss ).not.toBeNull();
    expect( rss!.getAttribute( 'href' ) ).toBe( '/blog/rss.xml' );
    expect( rss!.getAttribute( 'type' ) ).toBe( 'application/rss+xml' );
    expect( rss!.getAttribute( 'aria-label' ) ).toBe( 'Subscribe via RSS' );
    expect( rss!.querySelector( 'svg[aria-hidden="true"]' ) ).not.toBeNull();
    // The label is sr-only: the accessible name exists, but no VISIBLE text node reads it.
    const srLabel = rss!.querySelector( '.rss-icon-sr' );
    expect( srLabel?.textContent ).toBe( 'Subscribe via RSS' );
    // It sits at the foot of the page, after the post grid.
    const grid = container.querySelector( '.post-grid' );
    const foot = container.querySelector( '.blog-rss-foot' );
    expect( foot ).not.toBeNull();
    if ( grid ) {
      expect( grid.compareDocumentPosition( foot! ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
    }
  } );

  /**
   * THE GLOBAL SUBSCRIBE + SHARE BLOCK IS ON THE INDEX NOW. The owner unified every public
   * surface onto the ONE PublicShare block (Subscribe followed by Share), so BlogIndexView no
   * longer passes `noShare` to RotatingHero and no longer renders its own three-part BlogFooterCTA
   * band. This pins that the index carries exactly ONE PublicShare (Subscribe pill at the
   * subscribe deep link + the Share row) and NO old `.blog-cta` band.
   */
  it( 'carries exactly one global Subscribe + Share block at the foot of the index', () => {
    mockSearchIndex( [ firstCard, secondCard ] );
    const { container } = render( <BlogIndex { ...propsFor() } /> );

    // Exactly ONE PublicShare block.
    const shares = container.querySelectorAll( 'section.public-share' );
    expect( shares ).toHaveLength( 1 );

    // Subscribe is now the 48px notification action in the common dock. Its accessible name and
    // destination are the contract; Material Symbols text is intentionally aria-hidden.
    const subscribe = shares[ 0 ].querySelector( 'a.ps-subscribe' );
    expect( subscribe ).not.toBeNull();
    expect( subscribe!.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( subscribe!.getAttribute( 'aria-label' ) ).toBe( 'Subscribe on WhatsApp' );

    // Share: the row follows Subscribe inside the same block.
    expect( shares[ 0 ].querySelector( '.ps-row' ) ).not.toBeNull();

    // The OLD three-part band is gone, markup and all - no .blog-cta, no .blog-cta-subscribe.
    expect( container.querySelector( '.blog-cta' ) ).toBeNull();
    expect( container.querySelector( 'a.blog-cta-subscribe' ) ).toBeNull();

    // Ordering: the block sits after the post grid.
    const grid = container.querySelector( '.post-grid' );
    if ( grid ) {
      expect( grid.compareDocumentPosition( shares[ 0 ] ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
    }
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

  it( 'keeps the post count off the pills, and renders no count anywhere on the index', () => {
    /*
     * NO COUNT ANYWHERE, on owner instruction. The pills never carried their size - that was
     * reversed earlier - and now the "N posts" toolbar line is gone too: the reader can see the
     * whole list, so a count is a label on nothing. The number must be absent from the nav AND
     * from the page, and this assertion is what stops either drifting back.
     *
     * `categoryCounts` is STILL a live prop on the interface - callers and the props builder pass
     * it - so it is given a large value here specifically to prove nothing on the page renders
     * it. The prop is retained for compatibility; the body no longer reads it.
     */
    const { container } = render(
      <BlogIndex { ...propsFor( { categoryCounts: { Conversations: 824, Guides: 40 } } ) } />
    );

    const nav = document.querySelector( '.category-switch' );
    expect( nav?.textContent ).toContain( 'Conversations' );
    expect( nav?.textContent ).toContain( 'Guides' );
    expect( nav?.textContent ).not.toMatch( /\d/ );
    expect( nav?.querySelector( 'i' ) ).toBeNull();

    // The old toolbar count element is gone, and neither of the passed counts prints anywhere.
    expect( container.querySelector( '.blog-count' ) ).toBeNull();
    expect( container.textContent ).not.toContain( '824 posts' );
    expect( container.textContent ).not.toContain( '40 posts' );
  } );

  it( 'fetches the full list on mount and shows every post in the category', async () => {
    /*
     * THE "SHOW EVERY POST" BEHAVIOUR (owner instruction, 2026-10-11). The page is prerendered
     * with its slice, then the whole corpus arrives from /blog/search-index.json on mount and
     * replaces it - scoped to the active category, so /blog/ grows to the default category's
     * full list and never pulls in another stream's posts.
     */
    // Both posts are in the active category, so the fetched list expands the one-card slice.
    const secondConversations = { ...secondCard, category: 'Conversations' };
    const fetchMock = mockSearchIndex( [ firstCard, secondConversations ] );
    render( <BlogIndex { ...propsFor( {
      posts: [ firstCard ], totalPosts: 2,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 2 },
      activeCategory: 'Conversations', defaultCategory: 'Conversations',
    } ) } /> );

    // The slice is painted immediately.
    expect( screen.getByRole( 'heading', { name: samplePost.title } ) ).toBeInTheDocument();
    // The full list is fetched once, on mount, with no interaction.
    await waitFor( () => {
      expect( fetchMock ).toHaveBeenCalledWith( '/blog/search-index.json', expect.anything() );
    } );
    // And the second Conversations post, absent from the one-card slice, appears once it lands.
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: secondPost.title } ) ).toBeInTheDocument();
    } );
  } );

  it( 'does not pull another category into the stream when the full list lands', async () => {
    /*
     * The index covers every category, so it must be narrowed: a reader on Conversations should
     * never see a Gastronomy post appended once the on-mount fetch resolves.
     */
    const conversations = { ...firstCard, category: 'Conversations' };
    const gastronomy = { ...secondCard, category: 'Gastronomy', title: 'A Gastronomy Post' };
    mockSearchIndex( [ conversations, gastronomy ] );
    render( <BlogIndex { ...propsFor( {
      posts: [ conversations ], totalPosts: 1,
      categories: [ 'Conversations', 'Gastronomy' ],
      categoryCounts: { Conversations: 1, Gastronomy: 1 },
      activeCategory: 'Conversations', defaultCategory: 'Conversations',
    } ) } /> );

    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: conversations.title } ) ).toBeInTheDocument();
    } );
    // The Gastronomy post is in the fetched index but in another stream, so it stays out.
    expect( screen.queryByRole( 'heading', { name: 'A Gastronomy Post' } ) ).toBeNull();
  } );

  it( 'filters the full corpus live as the reader types, and lists every match', async () => {
    /*
     * THE BORDERLESS LIVE SEARCH (owner instruction). The box filters the WHOLE corpus - fetched
     * on mount into allCards - across title + excerpt + category + tags, scoped to the active
     * category, and shows ALL matches. Typing a query that one card carries and the other does
     * not must leave only the matching card.
     */
    const matching = { ...firstCard, title: 'Clarity on a hard decision', category: 'Conversations' };
    const other = { ...secondCard, title: 'An unrelated piece', excerpt: 'nothing to see', category: 'Conversations' };
    mockSearchIndex( [ matching, other ] );
    render( <BlogIndex { ...propsFor( {
      posts: [ matching, other ], totalPosts: 2,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 2 },
      activeCategory: 'Conversations', defaultCategory: 'Conversations',
    } ) } /> );

    // The full list is in once the on-mount fetch lands.
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'An unrelated piece' } ) ).toBeInTheDocument();
    } );

    // Typing narrows to the one post whose title carries the word.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'clarity' } } );
    await waitFor( () => {
      expect( screen.queryByRole( 'heading', { name: 'An unrelated piece' } ) ).toBeNull();
    } );
    expect( screen.getByRole( 'heading', { name: 'Clarity on a hard decision' } ) ).toBeInTheDocument();

    // Clearing the box restores the whole list.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: '' } } );
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'An unrelated piece' } ) ).toBeInTheDocument();
    } );
  } );

  it( 'matches on tags, not just the visible title and excerpt', async () => {
    /*
     * TAGS ARE SEARCHED. The global tag links point at /blog/?q=<tag>, so the filter has to match
     * the tag field even when the word appears nowhere a reader can see - which is the whole
     * reason generate-blog-search-index.js carries tags for search rather than for display.
     */
    const tagged = { ...firstCard, title: 'A piece about nothing in particular', tags: [ 'Lemongrass' ], category: 'Conversations' };
    const plain = { ...secondCard, title: 'Another piece', excerpt: 'no herbs here', tags: [], category: 'Conversations' };
    mockSearchIndex( [ tagged, plain ] );
    render( <BlogIndex { ...propsFor( {
      posts: [ tagged, plain ], totalPosts: 2,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 2 },
      activeCategory: 'Conversations', defaultCategory: 'Conversations',
    } ) } /> );

    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Another piece' } ) ).toBeInTheDocument();
    } );

    // 'Lemongrass' is in the tagged post's tags only - its title and excerpt do not contain it.
    fireEvent.change( screen.getByLabelText( 'Search the blog' ), { target: { value: 'lemongrass' } } );
    await waitFor( () => {
      expect( screen.queryByRole( 'heading', { name: 'Another piece' } ) ).toBeNull();
    } );
    expect( screen.getByRole( 'heading', { name: 'A piece about nothing in particular' } ) ).toBeInTheDocument();
  } );

  it( 'seeds the search from ?q= on first render, so a tag link lands on a filtered list', async () => {
    /*
     * THE GLOBAL TAG LINKS WORK. A tag on the post page / panel is /blog/?q=<tag>; arriving here
     * with that parameter must seed the box and filter the list to the tag on the FIRST render,
     * before any typing. The seed is a lazy, window-guarded initializer.
     */
    const matching = { ...firstCard, title: 'Seeded match', category: 'Conversations' };
    const other = { ...secondCard, title: 'Not the seeded one', excerpt: 'different', category: 'Conversations' };
    mockSearchIndex( [ matching, other ] );

    // Put ?q= on the URL the lazy initializer reads. jsdom lets us set the search string.
    const original = window.location.search;
    Object.defineProperty( window, 'location', {
      value: { ...window.location, search: '?q=Seeded%20match' },
      writable: true,
      configurable: true,
    } );

    try {
      render( <BlogIndex { ...propsFor( {
        posts: [ matching, other ], totalPosts: 2,
        categories: [ 'Conversations' ], categoryCounts: { Conversations: 2 },
        activeCategory: 'Conversations', defaultCategory: 'Conversations',
      } ) } /> );

      // The box is pre-filled with the decoded query.
      expect( ( screen.getByLabelText( 'Search the blog' ) as HTMLInputElement ).value ).toBe( 'Seeded match' );

      // Once the corpus lands, the list is already filtered to the seeded query - the other post
      // never appears.
      await waitFor( () => {
        expect( screen.getByRole( 'heading', { name: 'Seeded match' } ) ).toBeInTheDocument();
      } );
      expect( screen.queryByRole( 'heading', { name: 'Not the seeded one' } ) ).toBeNull();
    } finally {
      Object.defineProperty( window, 'location', {
        value: { ...window.location, search: original },
        writable: true,
        configurable: true,
      } );
    }
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

    // The prev arrow (rel=prev) is now the only control that points at page 1, and it must point
    // at /blog/ rather than /blog/page/1/. The Perspectives pager prints no numbered page links.
    const newer = container.querySelector( 'a[rel="prev"]' );
    expect( newer ).not.toBeNull();
    expect( samePath( newer!.getAttribute( 'href' ) ) ).toBe( '/blog' );
    expect( container.querySelector( 'a.pager-num' ) ).toBeNull();
  } );

  it( 'is a Perspectives pager: arrows for the directions that exist, no numbers', () => {
    const { container: first } = render( <BlogIndex { ...propsFor( { posts: manyCards, page: 1, totalPages: 3, totalPosts: 60 } ) } /> );
    // Page 1 has no previous page: the arrow is rendered so the row does not reflow, but it is
    // not a link and is hidden from the accessibility tree.
    expect( first.querySelector( 'a[rel="prev"]' ) ).toBeNull();
    expect( first.querySelector( '.pager-arrow.is-off[aria-hidden="true"]' ) ).not.toBeNull();
    expect( samePath( first.querySelector( 'a[rel="next"]' )!.getAttribute( 'href' ) ) ).toBe( '/blog/page/2' );
    // No numbered page chip anywhere in the pager - position lives in the progress bar instead.
    expect( first.querySelector( '.pager .pager-num' ) ).toBeNull();
    expect( first.querySelector( '.pager [aria-current="page"]' ) ).toBeNull();
    const firstBar = first.querySelector( '.pager-progress-track' )!;
    expect( firstBar.getAttribute( 'aria-valuenow' ) ).toBe( '1' );
    expect( firstBar.getAttribute( 'aria-valuetext' ) ).toBe( 'Page 1 of 3' );

    const { container: last } = render( <BlogIndexPage { ...propsFor( { posts: manyCards, page: 3, totalPages: 3, totalPosts: 60 } ) } /> );
    expect( last.querySelector( 'a[rel="next"]' ) ).toBeNull();
    expect( samePath( last.querySelector( 'a[rel="prev"]' )!.getAttribute( 'href' ) ) ).toBe( '/blog/page/2' );
    expect( last.querySelector( '.pager-progress-track' )!.getAttribute( 'aria-valuetext' ) ).toBe( 'Page 3 of 3' );
  } );

  it( 'paginates the prerendered slice until the full list arrives, then drops the pager', async () => {
    // A fetch that resolves with the whole corpus.
    const fetchMock = mockSearchIndex( manyCards );
    const { container } = render( <BlogIndex { ...propsFor( {
      posts: manyCards.slice( 0, 2 ), page: 1, totalPages: 3, totalPosts: 5,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 5 },
    } ) } /> );

    // Once the full list is in, the pager is gone and every post is listed.
    await waitFor( () => {
      expect( container.querySelector( 'nav[aria-label="Blog pages"]' ) ).toBeNull();
    } );
    expect( fetchMock ).toHaveBeenCalledWith( '/blog/search-index.json', expect.anything() );
    expect( screen.getByRole( 'heading', { name: 'Post number 5' } ) ).toBeInTheDocument();
    // Fetched exactly once, on mount.
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'shows every published post, not just the page in front of the reader', async () => {
    /**
     * THE CASE "SHOW EVERY POST" EXISTS FOR. The page carries 2 cards; the corpus has 5. The
     * three posts that are NOT on this prerendered page must appear once the on-mount fetch of
     * /blog/search-index.json lands. Before this the reader had to turn pages or search; now the
     * whole category is on one scroll.
     */
    const fetchMock = mockSearchIndex( manyCards );
    render( <BlogIndex { ...propsFor( {
      posts: manyCards.slice( 0, 2 ), page: 1, totalPages: 3, totalPosts: 5,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 5 },
    } ) } /> );

    // The two prerendered cards are there from the first paint.
    expect( screen.getByRole( 'heading', { name: 'Post number 1' } ) ).toBeInTheDocument();

    // The off-page posts arrive from the on-mount fetch.
    await waitFor( () => {
      expect( screen.getByRole( 'heading', { name: 'Post number 5' } ) ).toBeInTheDocument();
    } );
    expect( screen.getByRole( 'heading', { name: 'Post number 4' } ) ).toBeInTheDocument();
    expect( fetchMock ).toHaveBeenCalledWith( '/blog/search-index.json', expect.anything() );
  } );

  it( 'falls back to the paginated slice when the full list cannot be loaded', async () => {
    /*
     * The full-list fetch is a progressive enhancement over a prerendered, paginated page. If it
     * fails, the reader keeps exactly what shipped: the slice and its pager, with no error state
     * - nothing was lost, the page is simply not expanded.
     */
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 502, json: async () => ( {} ) } ) );
    const { container } = render( <BlogIndex { ...propsFor( {
      posts: manyCards.slice( 0, 2 ), page: 1, totalPages: 3, totalPosts: 5,
      categories: [ 'Conversations' ], categoryCounts: { Conversations: 5 },
    } ) } /> );

    // The prerendered slice stays, and the pager with it.
    await waitFor( () => {
      expect( container.querySelector( 'nav[aria-label="Blog pages"]' ) ).not.toBeNull();
    } );
    expect( screen.getByRole( 'heading', { name: 'Post number 1' } ) ).toBeInTheDocument();
    // The off-page post never appears, because the fetch that would bring it failed.
    expect( screen.queryByRole( 'heading', { name: 'Post number 5' } ) ).toBeNull();
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
   * THE ONE COMMON ACTION DOCK SITS BETWEEN TAGS AND THE PAGER.
   *
   * Contribute, Subscribe and Share are now children of ONE PublicShare component. The post no
   * longer renders a separate ContributeBlock or inline Subscribe/Share row.
   */
  it( 'renders the unified Contribute + Subscribe + Share dock after Tags', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    const tags = container.querySelector( 'nav.tags' );
    const share = container.querySelector( '.post-share' );
    const publicShare = container.querySelector( 'section.public-share' );
    const contribution = publicShare?.querySelector( 'section.contribute' ) || null;

    expect( tags ).not.toBeNull();
    expect( share ).not.toBeNull();
    expect( publicShare ).not.toBeNull();
    expect( contribution ).not.toBeNull();

    expect( container.querySelector( 'a.blog-wa-subscribe' ) ).toBeNull();
    expect( container.querySelector( 'section.blog-subscribe' ) ).toBeNull();
    expect( container.querySelectorAll( 'section.public-share' ) ).toHaveLength( 1 );
    expect( share!.contains( publicShare! ) ).toBe( true );
    expect( publicShare!.contains( contribution! ) ).toBe( true );

    expect( publicShare!.querySelector( 'a.ps-subscribe' )!.getAttribute( 'href' ) )
      .toBe( 'https://wa.me/message/WUDPTMYSO6XII1' );

    expect( tags!.compareDocumentPosition( share! ) & Node.DOCUMENT_POSITION_FOLLOWING )
      .toBeTruthy();
    expect( share!.classList.contains( 'post-share' ) ).toBe( true );
  } );

  /**
   * THE MANDATED COPY, AND NO SECOND H1. The heading and primary message are fixed strings in the
   * brief; the heading must be an h2 so the post keeps exactly one h1 (htmlcheck guards H1-MANY).
   */
  it( 'shows the Contribute heading and amount in the unified dock, and adds no second h1', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    const dock = container.querySelector( 'section.public-share' )!;
    const block = dock.querySelector( 'section.contribute' )!;
    const menu = dock.querySelector( '#ps-contribute-menu' )!;

    expect( block.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( block.querySelector( 'button.ps-contribute' ) )
      .toHaveAttribute( 'aria-label', `Contribute ${ CONTRIBUTION_AMOUNT_LABEL }` );
    expect( menu.querySelector( '.contribute-label' )?.textContent )
      .toBe( `Contribute ${ CONTRIBUTION_AMOUNT_LABEL }` );
    expect( dock.textContent ).not.toContain( 'If this helped' );

    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( block.querySelector( 'h1' ) ).toBeNull();
  } );

  /**
   * THE CONTRIBUTION BLOCK IS ONE COMPACT LINE WITH BOTH PATHS - owner instruction, 2026-10-12.
   *
   * The post page carries components/ContributeBlock. The two big pill buttons and the copy
   * sentence are gone; the block is now the eyebrow + a single line: a ₹ glyph, a "Contribute
   * ₹250" static label, then two inline TEXT links - "on WhatsApp" (a real anchor to the Contribute
   * chat) and "on the website →" (a button that names the variant in the cart and goes to /cart/).
   * The amount is a static label from src/config/contribution.ts, so the figure cannot drift. No
   * radio group and no on-page form - the browser never sends a price; cart_v2 prices the variant.
   */
  it( 'offers both contribution paths inside the unified Contribute menu', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    const dock = container.querySelector( 'section.public-share' )!;
    const menu = dock.querySelector( '#ps-contribute-menu' )!;

    const whatsapp = menu.querySelector( 'a.contribute-link' )!;
    expect( whatsapp ).toHaveAttribute( 'href', 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( whatsapp.getAttribute( 'aria-label' ) ).toBe( 'Contribute on WhatsApp' );
    expect( whatsapp.textContent ).toContain( 'Continue on WhatsApp' );

    const website = menu.querySelector( 'button.contribute-link-btn' )!;
    expect( website.getAttribute( 'aria-label' ) ).toContain( 'website' );
    expect( website.textContent ).toContain( 'Continue to checkout' );

    expect( menu.querySelector( '.contribute-label' )?.textContent )
      .toBe( `Contribute ${ CONTRIBUTION_AMOUNT_LABEL }` );
    expect( menu.querySelector( '[role="radiogroup"]' ) ).toBeNull();
    expect( menu.querySelectorAll( 'form, input, fieldset' ) ).toHaveLength( 0 );
    expect( menu.textContent || '' ).toContain( '₹250' );
  } );

  /**
   * TWO WHATSAPP CTAS AT THE TAIL OF A POST, TWO DISTINCT CONVERSATIONS - BUT FROM TWO SOURCES.
   *
   * The owner unified the Subscribe pill into the ONE global PublicShare block, so the post page
   * no longer owns its inline Subscribe pill. The two WhatsApp links at the tail are now:
   *   - Contribute, from ContributeBlock (`section.contribute a.contribute-link`), opening
   *     BYFLCAAMSZBXD1; and
   *   - Subscribe, from the global PublicShare (`section.public-share a.ps-subscribe`), opening
   *     WUDPTMYSO6XII1.
   * They are still DIFFERENT Meta message links - pointing one at the other's link would look
   * entirely correct on screen, which is why both hrefs are pinned here as literals AND asserted
   * to differ. The Contribute link is a quiet text link on the compact line; PublicShare's
   * Subscribe is a lime pill.
   */
  it( 'keeps Contribute and Subscribe on distinct WhatsApp destinations in the common dock', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    const dock = container.querySelector( 'section.public-share' )!;
    const contribute = dock.querySelector( '#ps-contribute-menu a.contribute-link' )!;
    const subscribe = dock.querySelector( 'a.ps-subscribe' )!;

    expect( contribute ).not.toBeNull();
    expect( subscribe ).not.toBeNull();
    expect( subscribe.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( contribute.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/BYFLCAAMSZBXD1' );
    expect( subscribe.getAttribute( 'href' ) ).not.toBe( contribute.getAttribute( 'href' ) );
    expect( subscribe.getAttribute( 'aria-label' ) ).toBe( 'Subscribe on WhatsApp' );
    expect( contribute.getAttribute( 'aria-label' ) ).toBe( 'Contribute on WhatsApp' );

    expect( container.querySelector( 'a.blog-wa-subscribe' ) ).toBeNull();
    expect( container.querySelector( '.blog-wa-note' ) ).toBeNull();
    expect( container.querySelector( '.bc-cta-note' ) ).toBeNull();

    const css = cssOf( container );
    const selector = '.ps-action{';
    const rule = css.slice( css.indexOf( selector ), css.indexOf( '}', css.indexOf( selector ) ) );
    expect( rule ).toContain( 'width:48px' );
    expect( rule ).toContain( 'height:48px' );
    expect( rule ).toContain( 'border-radius:50%' );
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
    // display. /blog/ reads ?q= on first render and seeds its live filter from it, so /blog/?q=
    // is a real target - the blog index filters to that tag.
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

  /**
   * THE GLOBAL BORDERLESS SEARCH IS ON THE POST PAGE, AND THE RSS LINK IS AT THE FOOT, TO THE
   * SIDE. Owner instruction, 2026-10-11: the post page carries the same button-less borderless
   * search field as /blog/ and the /anew/ panel - here a GET form to /blog/?q= because a post page
   * has no list to filter live - and the icon-only RSS affordance sits end-aligned (not centered)
   * at the foot.
   */
  it( 'has the global borderless search and an end-aligned icon-only RSS link at the foot', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );

    // The borderless search is back: a real GET form to /blog/ with a q field and NO submit
    // button, found by its accessible name.
    const form = container.querySelector( 'form.post-search[role="search"]' );
    expect( form ).not.toBeNull();
    expect( form!.getAttribute( 'action' ) ).toBe( '/blog/' );
    expect( form!.getAttribute( 'method' ) ).toBe( 'get' );
    expect( screen.getByLabelText( 'Search the blog' ) ).toBeInTheDocument();
    expect( form!.querySelector( 'input[name="q"][type="search"]' ) ).not.toBeNull();
    expect( form!.querySelector( 'button' ) ).toBeNull();

    // The RSS icon is present, icon-only (no visible text, name is sr-only), pointing at the feed.
    const rss = container.querySelector( 'a.rss-icon' );
    expect( rss ).not.toBeNull();
    expect( rss!.getAttribute( 'href' ) ).toBe( '/blog/rss.xml' );
    expect( rss!.getAttribute( 'aria-label' ) ).toBe( 'Subscribe via RSS' );
    expect( rss!.querySelector( 'svg[aria-hidden="true"]' ) ).not.toBeNull();
    // It sits at the foot: after the tags nav, inside the article, end-aligned (not centered).
    const tags = container.querySelector( 'nav.tags' )!;
    expect( tags.compareDocumentPosition( rss! ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
    expect( cssOf( container ) ).toContain( '.post-rss{display:flex;justify-content:flex-end' );
  } );
} );

/**
 * THE /anew/ PANEL'S TAGS ARE THE SHARED LINKS NOW.
 *
 * ProductBlogPanel used to render its own plain-span .pbp-chip chips; they are the shared
 * BlogTags links now, so a tag reads as the same object on the panel as on the post page. These
 * are light checks: the tags are anchors to /blog/?q=, they carry a tag-h hue class, and - the
 * part that was invalid before - no anchor is nested inside the card's own anchor.
 */
describe( 'Anew blog panel tags are the shared link component', () => {
  const panelCards: BlogCard[] = [
    {
      slug: 'anew-post-1',
      title: 'A panel post',
      excerpt: 'An excerpt for the panel card.',
      category: 'Conversations',
      tags: [ 'Practice', 'Inquiry' ],
    },
  ];

  it( 'renders the card tags as links to the blog search, with a hue class', () => {
    const { container } = render( <ProductBlogPanel cards={ panelCards } /> );

    // The tag row is the shared nav, and its entries are links, not spans.
    const tagLinks = Array.from( container.querySelectorAll( '.pbp-card nav.tags a' ) );
    expect( tagLinks.length ).toBeGreaterThan( 0 );
    tagLinks.forEach( a => {
      expect( a.getAttribute( 'href' ) ).toMatch( /^\/blog\/?\?q=/ );
      expect( a.getAttribute( 'class' ) ).toMatch( /tag-h[0-3]\b/ );
      expect( a.getAttribute( 'class' ) ).not.toMatch( /tag-h-/ );
    } );

    // The old span chips are gone.
    expect( container.querySelector( '.pbp-chip' ) ).toBeNull();
  } );

  it( 'does not nest a tag anchor inside the card link', () => {
    const { container } = render( <ProductBlogPanel cards={ panelCards } /> );

    // No <a> anywhere inside another <a> - the tags are siblings of .pbp-link, not children.
    for ( const anchor of Array.from( container.querySelectorAll( 'a' ) ) ) {
      expect( anchor.querySelector( 'a' ) ).toBeNull();
    }
    // The main card link covers the title; the tag nav sits after it, inside the same li.
    const li = container.querySelector( '.pbp-card' )!;
    const link = li.querySelector( 'a.pbp-link' )!;
    const tagNav = li.querySelector( 'nav.tags' )!;
    expect( link.contains( tagNav ) ).toBe( false );
    expect( link.compareDocumentPosition( tagNav ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
  } );

  it( 'places an icon-only RSS link at the foot of the panel', () => {
    const { container } = render( <ProductBlogPanel cards={ panelCards } /> );

    const rss = container.querySelector( 'a.rss-icon' );
    expect( rss ).not.toBeNull();
    expect( rss!.getAttribute( 'href' ) ).toBe( '/blog/rss.xml' );
    expect( rss!.getAttribute( 'aria-label' ) ).toBe( 'Subscribe via RSS' );
    expect( rss!.querySelector( 'svg[aria-hidden="true"]' ) ).not.toBeNull();
  } );
} );
