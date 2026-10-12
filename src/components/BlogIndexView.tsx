import React, { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import type { BlogCard } from '../lib/public-blog';
import { topicSlug } from '../lib/blog-index-props';
import RotatingHero, { CycleWord } from './RotatingHero';
import Breadcrumbs from './Breadcrumbs';
import Pager from './Pager';
import BlogFooterCTA from './BlogFooterCTA';
import RssIcon from './RssIcon';
import VoiceSearchMic from './VoiceSearchMic';

/**
 * The blog index, one page of it.
 *
 * WHY THIS IS A COMPONENT AND NOT JUST src/pages/blog/index.tsx. There are now two routes
 * that render this exact page - /blog/ for the first 24 posts and /blog/page/N/ for the
 * rest - and they must not be two copies of 250 lines of markup and styles. Both pages are
 * thin: they fetch, slice, and hand the slice here.
 *
 * WHY THE BLOG IS PAGINATED AT ALL
 * --------------------------------
 * /blog/ rendered all 834 published posts in one document. Measured at 1280x900 that was
 * 103,908px - 115.5 screens - and the build printed its own warning on every run:
 *
 *   Warning: data for page "/blog" (path "/blog/") is 842 kB which exceeds the
 *   threshold of 128 kB, this amount of data can reduce performance.
 *
 * Two separate costs behind one symptom, and both had to go:
 *
 *   THE PAYLOAD. Every field of every post was serialised into __NEXT_DATA__ and seven
 *   were rendered. See BlogCard in lib/public-blog.ts - projecting to the fields the card
 *   actually prints drops 357 kB of metaDescription, seoTitle, robots, tags, modifiedDate,
 *   url and id that no reader ever saw.
 *
 *   THE DOM. 834 cards is 834 <article>s with links and headings in them, parsed and laid
 *   out before anything is interactive, on a phone as much as a laptop. Projection does not
 *   touch that; only slicing does.
 *
 * Together: ~9 kB and ~3.3 screens per page, against 842 kB and 115.5.
 *
 * SHOW EVERY POST BY DEFAULT, WITH A LIVE SEARCH OVER THE WHOLE CORPUS
 * -------------------------------------------------------------------------------------
 * The index loads the WHOLE corpus client-side and renders every post in the active category at
 * once, so a reader scrolls the full list rather than paging. On top of that it carries a
 * borderless live search - the same field the /anew/ panel uses - so a reader can also filter
 * the full corpus as they type. When the box is empty the behaviour is unchanged: every post in
 * the active category once the fetch lands, else the prerendered slice. The paginator is for the
 * no-JS path only, and it hides while a query is active (all matches are shown, nothing to page).
 *
 * THE SEARCH IS SEEDED FROM ?q= ON FIRST RENDER, so the global tag links the post page and the
 * /anew/ panel render - /blog/?q=<tag> - land here and filter the list to that tag. It is a lazy,
 * window-guarded initializer so SSR and the no-JS render carry an empty query and the full list.
 *
 * THE FULL LIST IS STILL /blog/search-index.json - slug, title, excerpt, category and tags,
 * written by scripts/generate-blog-search-index.js after the build. It is the same file the
 * search box used; nothing about the build changed. The difference is WHEN it is fetched: it
 * was lazy, on the first keystroke, so a reader who did not search never paid for it. Now it is
 * fetched ONCE on mount, because showing every post is the default rather than an action - the
 * whole point of the change is that the reader does not have to ask. It is still a client fetch
 * and still NOT in __NEXT_DATA__, so the 842 kB payload the pagination note below records does
 * not come back: the page ships its 24-card prerender and the DOM grows only after hydration.
 *
 * SCOPED TO THE ACTIVE CATEGORY. /blog/ shows the default category's whole corpus; each
 * /blog/topic/<slug>/ shows that stream's whole corpus. The index covers everything, so it is
 * narrowed to activeCategory here - a reader on Conversations should not suddenly see 240
 * Gastronomy posts appended once the fetch lands.
 *
 * NO-JAVASCRIPT PATH, UNCHANGED. The prerendered page is still the first 24 posts with real
 * pagination links to real prerendered pages, so the whole blog is reachable with scripts off.
 * The "show every post" expansion is a progressive enhancement layered on top of that: when the
 * fetch succeeds, the full list replaces the slice and the paginator is hidden because there is
 * nothing left to page; when it fails or JS is off, the paginated slice is exactly what a reader
 * gets, which is the behaviour that already shipped.
 */

/**
 * The rotation. Four words, held close in length so the pill barely travels - the same
 * constraint products.ts documents. Tints are the four pairs reused verbatim from the Grahak
 * OS hero; no new colours.
 *
 * THEY DESCRIBE WHAT IS ACTUALLY PUBLISHED HERE. The corpus is short reflective pieces -
 * "A page view is not a person", "Acceptance begins where control ends", "A promise is not a
 * prediction" - so the words name the subject matter rather than promising guides or product
 * updates, which is what the old sub-line implied and the posts do not deliver.
 */
export const HERO_WORDS: CycleWord[] = [
  { word: 'clarity', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'practice', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'meaning', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'change', tint: '#ede9fe', dot: '#9849e8' },
];

/** The canonical origin, for building absolute share URLs for the footer CTA's Share row. The
 *  same origin BlogIndexHead uses for canonicals. */
const ORIGIN = 'https://wecare.digital';

/** Where the full post list lives. Written post-build, beside the page it serves. Fetched once
 *  on mount now that "show every post" is the default rather than a search action. The name is
 *  kept for continuity with scripts/generate-blog-search-index.js, which writes it. */
const FULL_INDEX_URL = '/blog/search-index.json';

/* The feed scripts/generate-blog-rss.js writes post-build lives at /blog/rss.xml. The visible
 * affordance is now the icon-only <RssIcon> at the foot of the page (components/RssIcon.tsx, which
 * owns the URL); the <link rel="alternate"> autodiscovery tag in BlogIndexHead points at the same
 * file. The old top text pill and its RSS_URL constant went when the icon took over. */

interface BlogIndexViewProps {
  /** This page's slice, already projected and sorted. */
  posts: BlogCard[];
  /** 1-based. Page 1 is /blog/; every other page is /blog/page/N/. */
  page: number;
  totalPages: number;
  /** Every published post across the whole corpus. */
  totalPosts: number;
  /** Every category across the whole corpus, not just this page's - see below. Sorted, and the
   *  FIRST one is the default pill now that "All" is gone. */
  categories: string[];
  /** Posts per category across the whole corpus. NOTHING RENDERS A COUNT any more - the "N
   *  posts" line went on owner instruction - but the prop stays on the interface so the callers
   *  and tests that build props do not break. It is deliberately unread in the body. */
  categoryCounts?: Record<string, number>;
  /** Which category this prerendered page lists. Server-decided, never client state. */
  activeCategory?: string;
  /** The category that lives at /blog/; all others at /blog/topic/<slug>/. */
  defaultCategory?: string;
}

/**
 * Page 1 is the stream's own URL; page N hangs off it. Page 1 must not also exist at page/1/.
 *
 * `streamBase` EXISTS BECAUSE THE CATEGORY STREAMS ARE PAGINATED NOW TOO. It was hardcoded to
 * /blog/, which was true while /blog/topic/<slug>/ listed a whole category on one page. That
 * stopped being viable: Gastronomy has gone from 40 posts to 90, its props measured 30.2 kB
 * against the 128 kB threshold blogcheck enforces, and the topic route's own comment said to
 * paginate it past roughly 100. Passing the base in means one helper serves both shapes -
 * /blog/page/2/ and /blog/topic/gastronomy/page/2/ - so the two cannot drift into two URL
 * conventions for one idea.
 */
export const blogPageHref = ( page: number, streamBase = '/blog/' ): string =>
  page <= 1 ? streamBase : `${streamBase}page/${page}/`;

/**
 * pageWindow() AND THE WHOLE PAGINATOR NOW LIVE IN components/Pager.tsx, markup and CSS
 * together, because /shop/ renders the identical control. Two copies of a row whose styles
 * carry a documented :global() trap and a documented WCAG contrast carve-out would drift, and
 * a fix would land on one listing. Nothing here changed shape: every class name and attribute
 * is what it was, which is why the pager assertions in src/test/BlogDesign.test.tsx are
 * untouched, and the step labels default to this listing's Newer / Older so this call site
 * passes neither.
 */

const BlogIndexView: React.FC<BlogIndexViewProps> = ( {
  posts, page, totalPages, totalPosts, categories,
  activeCategory = '', defaultCategory = '',
} ) => {
  /**
   * NO "ALL" PILL, AND THE ACTIVE CATEGORY IS DECIDED BY THE SERVER.
   *
   * Owner instruction to drop "All" and default to the first category, and the corpus supports
   * it: measured live, 864 posts carry two categories - Conversations 824 and Gastronomy 40 -
   * so "All" selected 864 where the next pill selected 824. Two options, effectively one list.
   *
   * IT IS NOT CLIENT STATE ANY MORE, and that is the important part. Filtering the full-corpus
   * pages in the browser looked equivalent and was not: the 40 Gastronomy posts are the NEWEST
   * in the corpus, so in date order they filled the whole of page 1 and 16 of page 2. A default
   * filter rendered /blog/ with ZERO cards and left 40 posts on no index page at all - caught
   * by blogcheck, not by looking. Each category is now its own prerendered stream, so the HTML
   * is what the reader sees and the pills are links rather than state.
   */
  /** The whole corpus, or null until the on-mount fetch lands. */
  const [ allCards, setAllCards ] = useState<BlogCard[] | null>( null );
  const [ indexState, setIndexState ] = useState<'loading' | 'ready' | 'failed'>( 'loading' );
  const requested = useRef( false );

  /**
   * THE LIVE SEARCH QUERY, SEEDED FROM ?q= ON FIRST RENDER.
   *
   * A lazy initializer so it runs once, and window-guarded so SSR and the no-JavaScript render
   * seed an empty string - the full list - rather than touching an undefined `window`. The seed
   * is what makes the global tag links work: the post page and the /anew/ panel render tags as
   * /blog/?q=<tag>, so arriving here with that parameter filters the list to the tag immediately.
   * decodeURIComponent because the tag links encode the value; a bad escape falls back to raw.
   */
  const [ query, setQuery ] = useState<string>( () => {
    if ( typeof window === 'undefined' ) return '';
    const q = new URLSearchParams( window.location.search ).get( 'q' ) || '';
    try { return decodeURIComponent( q ); } catch { return q; }
  } );

  /**
   * FETCH THE FULL LIST ONCE, ON MOUNT. The search box used to defer this to the first
   * keystroke; "show every post" is the default now, so there is nothing to defer to - the
   * reader wants the whole list the moment the page loads. Guarded by a ref so React 18's
   * double-invoke in development (and any re-render before the request settles) cannot fire a
   * second fetch. On failure requested.current stays true: the prerendered slice is a correct
   * fallback, so there is no value in hammering an endpoint that just failed.
   */
  useEffect( () => {
    if ( requested.current ) return;
    requested.current = true;
    fetch( FULL_INDEX_URL, { headers: { Accept: 'application/json' } } )
      .then( r => ( r.ok ? r.json() : Promise.reject( new Error( String( r.status ) ) ) ) )
      .then( ( body: { posts?: BlogCard[] } ) => {
        if ( !Array.isArray( body?.posts ) ) throw new Error( 'shape' );
        setAllCards( body.posts );
        setIndexState( 'ready' );
      } )
      .catch( () => {
        setIndexState( 'failed' );
      } );
  }, [] );

  /**
   * True once the full corpus is in hand AND it actually contains this category's posts.
   *
   * An EMPTY successful response does not expand. A transient empty index must not blank a blog
   * that prerendered cards perfectly well - the same non-fatal-on-empty rule the feed and the
   * index generators follow - so when the fetch comes back with nothing for this category the
   * prerendered slice is left exactly as it shipped rather than being replaced by "no posts".
   */
  const expanded =
    indexState === 'ready' &&
    allCards !== null &&
    ( activeCategory
      ? allCards.some( post => post.category === activeCategory )
      : allCards.length > 0 );

  /**
   * EVERY POST IN THIS CATEGORY, or the prerendered slice until the fetch lands / if it fails.
   *
   * The index covers the whole corpus, so it is narrowed to activeCategory here - /blog/ must
   * not grow 240 Gastronomy posts once the fetch resolves, and a topic stream must not grow the
   * rest of the site. Before expansion this is exactly the server-sent slice, so the first paint
   * and the no-JS render are identical to what shipped.
   */
  /**
   * WHAT THE READER SEES, IN THREE CASES.
   *
   *   A query is typed - filter the WHOLE corpus (scoped to this category) across
   *     title + excerpt + category + tags, and show every match. This needs allCards, so it only
   *     narrows once the fetch has landed; before that there is nothing to search and the normal
   *     list shows. All matches, no slice: the point of the box is to find a post, not to page to it.
   *   No query, expanded - every post in the active category, the show-every-post default.
   *   No query, not expanded - the prerendered slice, which is the first paint and the no-JS path.
   *
   * The category scope is the same in all three: /blog/ is the default category, each topic
   * stream is its own, so a search on Conversations never surfaces a Gastronomy post.
   */
  const trimmedQuery = query.trim().toLowerCase();
  const searching = trimmedQuery.length > 0 && allCards !== null;

  const visiblePosts = useMemo( () => {
    if ( searching ) {
      const scoped = activeCategory
        ? allCards!.filter( post => post.category === activeCategory )
        : allCards!;
      return scoped.filter( post => {
        const hay = [
          post.title,
          post.excerpt || '',
          post.category || '',
          ...( post.tags || [] ),
        ].join( '\n' ).toLowerCase();
        return hay.includes( trimmedQuery );
      } );
    }
    if ( !expanded ) return posts;
    return activeCategory
      ? allCards!.filter( post => post.category === activeCategory )
      : allCards!;
  }, [ searching, trimmedQuery, expanded, allCards, posts, activeCategory ] );

  /* WHICH STREAM THIS VIEW IS PAGING. Derived here rather than passed in, because the component
   * already holds both halves of the answer and the pills two hundred lines below compute the
   * same branch from the same two values - a prop would be a third place for it to disagree. */
  const streamBase = !activeCategory || activeCategory === defaultCategory
    ? '/blog/'
    : `/blog/topic/${topicSlug( activeCategory )}/`;

  return (
    <RotatingHero
      frame="Notes on"
      words={ HERO_WORDS }
      sub="Short pieces on the distinctions that change how a thing is seen — written by the people doing the work."
      ariaLabel="WECARE.DIGITAL blog"
      noShare
    >
      <div className="blog-shell">
        <Breadcrumbs
          items={ page > 1
            ? [ { label: 'Home', href: '/' }, { label: 'Blog', href: '/blog/' }, { label: `Page ${page}` } ]
            : [ { label: 'Home', href: '/' }, { label: 'Blog' } ] }
        />
        {/* BORDERLESS LIVE SEARCH over the WHOLE corpus - the same field as the /anew/ panel
            (ProductBlogPanel .pbp-search): no inner border, one quiet bottom hairline, the shared
            lime voice mic, and no submit button, filtering as you type. A real sr-only label gives it an accessible
            name. The old top toolbar - the "N posts" count and the text RSS pill - is gone; the
            count went on owner instruction and the RSS affordance moved to an icon at the bottom.
            It filters the full corpus (scoped to this category) and seeds from ?q= on first
            render, so the global tag links land here and narrow the list. */}
        <div className="blog-search">
          <label className="blog-search-sr" htmlFor="blog-q">Search the blog</label>
          <input
            id="blog-q"
            type="search"
            autoComplete="off"
            placeholder="Search posts"
            value={ query }
            onChange={ e => setQuery( e.target.value ) }
          />
          <VoiceSearchMic onTranscript={ setQuery } />
        </div>

        { totalPosts > 0 ? (
          <>
            {/* CATEGORIES COME FROM THE WHOLE CORPUS, passed in as a prop, not derived from
                this page's 24. Deriving them locally would give each page a different set of
                pills - page 3 would offer four categories and page 9 a different four - which
                reads as the filter being broken rather than as the data being sliced. */}
            {/* NO "ALL" BUTTON, and these are LINKS rather than buttons.
                "All" selected 864 posts where the next pill selected 824 - two options that
                were effectively one list - so it went on owner instruction.
                Links, not buttons, because each category is now its own prerendered stream:
                the default lives at /blog/ and every other category at /blog/topic/<slug>/.
                That makes the switch work with JavaScript off, gives each category a URL a
                reader can share, and means no 301 kB index has to be fetched to change
                category. aria-current marks the one you are on, which is what a link set uses
                where a button set would use aria-pressed. */}
            { categories.length > 1 && (
              <nav className="category-switch" aria-label="Blog categories">
                { categories.map( category => {
                  const href = category === defaultCategory ? '/blog/' : `/blog/topic/${topicSlug( category )}/`;
                  const here = category === activeCategory;
                  /* NO POST COUNT ON THE PILL, on owner instruction. Each pill carried
                     <i>{ categoryCounts[ category ] }</i> - "Conversations 824" - so the label
                     was a name followed by a number, and the pills go back to being what they
                     are - a set of names you choose between. `categoryCounts` stays a prop
                     because categoryTotal below still derives the honest per-category denominator
                     from it. */
                  return here
                    ? <span key={ category } className="cat-here" aria-current="page">{ category }</span>
                    : <Link key={ category } href={ href }>{ category }</Link>;
                } ) }
              </nav>
            ) }

            { visiblePosts.length > 0 ? (
              <section className="post-grid" aria-label="Published posts">
                { visiblePosts.map( post => (
                  <article key={ post.slug } className="post-card">
                    <div className="post-copy">
                      { post.category && <span className="category">{ post.category }</span> }
                      <h2><Link href={ `/post/${post.slug}/` }>{ post.title }</Link></h2>
                      { post.excerpt && <p>{ post.excerpt }</p> }
                      {/* NO DATE ON A CARD, on owner instruction, and the flag moved with it.
                          This row held the author beside a formatted publishedDate. The date is
                          gone from every listing surface - this one component renders /blog/,
                          /blog/page/N/ and both topic stream shapes, so removing it here removes
                          it from all of them at once.
                          publishedDate IS STILL CARRIED in the BlogCard projection and must
                          stay: lib/public-blog.ts orders the whole corpus by it, and with 35
                          pages an ordering change moves posts between page URLs. It is read,
                          never printed.
                          data-wc-no-translate NOW SITS ON THE ROW rather than the span. It was
                          on the span specifically so the sibling time element could still
                          translate; with only a proper noun left in here, the wrapper is the
                          honest place for it and it is one attribute instead of one per card. */}
                      { post.authorName && (
                        <div className="meta" data-wc-no-translate="true">{ post.authorName }</div>
                      ) }
                    </div>
                  </article>
                ) ) }
              </section>
            ) : (
              <div className="empty">
                { indexState === 'loading' ? 'Loading all posts…' : 'No posts have been published yet.' }
              </div>
            ) }

            {/* THE PAGINATOR IS THE NO-JAVASCRIPT PATH, SO IT HIDES ONCE THE FULL LIST IS IN -
                AND WHILE A SEARCH IS ACTIVE. When the on-mount fetch succeeds, every post in this
                category is already on screen and there are no more pages to turn; and when a query
                is typed, all matches are shown at once, so paging them would put two narrowings
                between a reader and one post. Until then (first paint, a failed fetch, or scripts
                off) the prerendered slice is paginated exactly as it shipped, which keeps the
                whole blog reachable without JavaScript. */}
            { !searching && !expanded && totalPages > 1 && (
              /* components/Pager.tsx, which is this exact control moved out whole so /shop/
                 renders one declaration of it rather than a second copy. No prevLabel or
                 nextLabel: they default to Newer / Older, which is this listing's own copy. */
              <Pager
                page={ page }
                totalPages={ totalPages }
                hrefFor={ n => blogPageHref( n, streamBase ) }
                ariaLabel="Blog pages"
              />
            ) }

            {/* THE SUBSCRIBE / CONTRIBUTE / SHARE BAND - the same block the post page carries at
                its foot, on owner instruction, so the blog index tail reads as the same object.
                The shared component (components/BlogFooterCTA.tsx) renders the WhatsApp Subscribe
                pill, the Contribute block and the Share row. shareUrl is this listing's own
                canonical page URL, built from the same streamBase/page the pager uses so a shared
                link points at the page the reader is on. */}
            <BlogFooterCTA
              shareUrl={ `${ORIGIN}${blogPageHref( page, streamBase )}` }
              shareTitle="WECARE.DIGITAL Blog"
            />

            {/* THE RSS SUBSCRIBE AFFORDANCE, ICON-ONLY, AT THE BOTTOM. It replaces the old text
                pill that sat in a toolbar at the top; on owner instruction it is now a compact
                lime glyph after the grid and pager, the same control the /anew/ panel places at
                its own foot. End-aligned to the measure. */}
            <div className="blog-rss-foot">
              <RssIcon />
            </div>
          </>
        ) : (
          <div className="empty">No posts have been published yet.</div>
        ) }
      </div>

      <style jsx>{`
        /* NO TOP PADDING AND NO MAX-WIDTH: RotatingHero owns both. This was the page's
           <main> at padding:156px 24px 96px with its own 1300px measure. It is now a <div>
           inside .rh-layout, which already applies the header offset, the page measure and
           the horizontal gutter - keeping them here would double every one of them. Only the
           space between the hero and the list is left, which is this element's own job.
           The font stack goes too: .rh-shell declares it one level up. */
        .blog-shell{margin:0}
        /* .blog-hero IS GONE, with the markup it styled. It held <h1>Blog</h1> and "Ideas,
           guides and updates published by the WECARE.DIGITAL team." - a heading that named the
           section and a line that restated it, on a page sharing no design language with the
           rest of the site. RotatingHero replaced both. */
        /* THE DEAD h1 RULE IS GONE. It styled an element this file has not rendered since
           RotatingHero took the headline: the hero owns the only h1 on the page, and .rh-head
           already carries this exact declaration. A rule matching nothing is worse than no
           rule, because the next person reads it as the page's title treatment and edits it.
           .blog-hero went the same way earlier, with the markup it styled. */
        /* THE PILLS, NOW ON THE HOME PAGE'S OWN AFFORDANCE RULES.
           Three things changed and each one was a defect rather than a preference.
           min-height 44px, was 38px. This is the WCAG 2.5.8 floor and these are the primary
           navigation on the page - the pager beside them already holds 44px, so the two
           control sets disagreed about how big a touch target is.
           2px border, was 1px. The design contract is one line: 1px means a static edge, 2px
           means a hoverable one, and the colour is always e5e7eb. These have a lime hover, so
           they were a hoverable edge drawn at the static weight, against d1d5db which is not
           the hairline colour the rest of the site uses.
           Opaque focus ring, was rgba(26,58,42,.25). The home page moved off the translucent
           ring because it failed WCAG 1.4.11 at 1.51:1 against white - a focus indicator you
           cannot see is not one. Same fix, same value.
           The hover now matches the home CTA exactly - lime tint, a 2px lift and the one
           shadow this design language uses - so a pill behaves like every other raised
           control on the site instead of having its own quieter version. */
        /* TYPE AND TRACKING PUT ON THE LABEL RUNG, 2026-09-29.
           13px was its own private size, and letter-spacing:.01em is positive tracking on a
           label - the contract says eyebrows and labels are not letter-spaced and not
           uppercase, because notion sets them plain. 14px/-.125px is the rung BrandBadge and
           the tag pills use, so all three now agree.
           The hover tint moves .28 -> .22. Here the tint IS the right treatment - hover is a
           transient state, which is exactly what the .22 value is for - it was just written at
           an alpha that does not exist in the language. The fill stays reserved for .cat-here,
           which is identity: the category you are actually on. */
        .category-switch{display:flex;gap:8px;overflow-x:auto;margin:0 0 32px;padding:2px 0 6px;scrollbar-width:thin;align-items:center}
        .category-switch :global(a),.category-switch .cat-here{
          flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;
          min-height:44px;padding:0 18px;border:2px solid #e5e7eb;border-radius:999px;
          background:#fff;color:#1a3a2a;font:inherit;font-size:14px;font-weight:600;
          letter-spacing:-.125px;text-decoration:none;
          transition:background-color .2s,border-color .2s,transform .2s,box-shadow .2s;
        }
        .category-switch :global(a:hover){
          border-color:#d1f470;background:rgba(209,244,112,.22);
          transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .category-switch :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}
        /* The current category: filled, and not a link, so there is nothing to click. The 2px
           1a3a2a edge is the same pairing the pager gives the page you are on - lime fill plus
           dark-green type and border, which the contract measures at about 10:1. */
        .category-switch .cat-here{background:#d1f470;border-color:#1a3a2a}
        /* The count. Tabular so the pills do not jiggle, and quiet so the name leads. */
        /* The .category-switch i rules that styled the per-pill post count went with the count
           itself - see the note in the markup. Nothing else in this nav renders an <i>. */
        /* THE CARDS, PUT ON THE HOME PAGE'S RUNGS.
           This grid had invented its own type scale. The heading was 23px at an undeclared
           weight - so browser-default bold - with -.3px tracking, and the body was
           16px/1.5 at rgba(0,0,0,.72). None of those three values exists anywhere else on the
           public site. The home page carries exactly one card-heading rung and exactly one
           body rung, and the body one is the same declaration used by the hero sub, the flow
           lead, the flow list and the closing points, which is what makes those bands read as
           one document. This listing now uses both.
           Heading: 22px/700/1.27/-.25px on solid black, the home card rung.
           Body: 20px/400/1.4/-.125px at rgba(0,0,0,.898), the one body rung. It is larger than
           what was here, which is the point - the home page fixed this exact defect on its own
           cards and recorded that a fourth body size was the bug, not the remedy.
           THE EXCERPT IS CLAMPED TO FOUR LINES because the rung is now bigger and excerpts
           arrive from the API at whatever length they were written. Clamping keeps a long one
           from setting the height of its whole row without inventing a smaller size for it.
           THE SPINE IS THE HOME PAGE'S ACCENT DEVICE. .home-flow-list gives its three items a
           3px inline-start bar in green, blue and purple, in that order, and that is the site's
           only accent motif - amber was measured at 2.04:1 and rejected, and the set is not to
           be extended. Cycling the three across the grid ties the listing to the band it was
           borrowed from and gives an otherwise uniform wall of cards a rhythm. It replaces the
           1px hairline on that one edge only, so the hoverable-edge rule is untouched.
           HOVER AND FOCUS ARE THE HOME CTA'S. A 2px lift with the single
           0 4px 12px rgba(26,58,42,.12) shadow this design language allows, and an opaque
           1a3a2a focus ring - the translucent one failed 1.4.11 at 1.51:1.
           The card is a flex column so .meta sits on the baseline of the tallest card in the
           row instead of floating directly under a short excerpt. */
        .post-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}
        .post-card{
          display:flex;background:#fff;border:1px solid #e5e7eb;
          border-inline-start:3px solid #3da35a;border-radius:14px;overflow:hidden;
          transition:border-color .2s,transform .2s,box-shadow .2s;
        }
        .post-card:nth-child(3n+2){border-inline-start-color:#2563eb}
        .post-card:nth-child(3n+3){border-inline-start-color:#9849e8}
        .post-card:hover{border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .post-copy{display:flex;flex-direction:column;flex:1;padding:26px}
        /* THE CATEGORY BADGE IS IDENTITY, SO IT GETS THE FULL LIME VOICE.
           It was rgba(209,244,112,.28) at 11px/700. Two separate problems.
           First, .28 is a FOURTH lime value. The contract lists exactly three treatments and
           says in as many words not to mix a fresh tint or a new alpha, because inventing an
           in-between value is how #f2fbf6 and #fbfff0 got into the codebase. The state tint is
           .22; .28 is neither that nor the fill.
           Second, and the reason the answer is the fill rather than .22: this badge NAMES the
           post's category, which is identity, not a transient state. BrandBadge went through
           exactly this - it began on the .22 tint and was lifted to the full fill because .22
           composites to (245,253,224) over white, a wash that reads as barely-not-white rather
           than as a green badge. A category that reads as barely-not-white has the same
           problem, so it takes the same answer.
           Now BrandBadge's own rung: 14px/600/-.125px, #d1f470 fill, #1a3a2a type, and NO
           border - which .tab.active and .msg.sent also carry none of, and which is already
           what this rule did. #1a3a2a on #d1f470 is ~10:1. */
        .category{display:inline-block;align-self:flex-start;background:#d1f470;color:#1a3a2a;border-radius:999px;padding:6px 12px;font-size:14px;font-weight:600;letter-spacing:-.125px;margin-bottom:14px}
        h2{font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;margin:0 0 12px}
        h2 :global(a){color:#000;text-decoration:none;text-underline-offset:3px}
        h2 :global(a:hover){color:#1a3a2a}
        h2 :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
        .post-copy p{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:0 0 20px;
          display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;
        }
        /* The author line. margin-top:auto pins it to the bottom of the card. The colour is the
           site's own dim rung rather than 6b7280, which is a dashboard token from tokens.css
           and had no business on a public page. */
        .meta{margin-top:auto;font-size:12px;font-weight:600;line-height:1.4;color:rgba(0,0,0,.54)}
        .empty{border:1px dashed #d1d5db;border-radius:14px;padding:40px;text-align:center;font-size:20px;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.54)}

        /* BORDERLESS LIVE SEARCH - the /anew/ panel's field (ProductBlogPanel .pbp-search),
           so every search a visitor meets on the site reads as one control: no inner border, one
           quiet bottom hairline, the shared lime mic, no submit button. The hairline darkens and a lime underline
           grows on focus. 52px is the site's field height (BlogSearch's own), 17px the base body
           size that keeps iOS from zooming the field on focus. */
        .blog-search{position:relative;margin:0 0 32px;max-width:520px}
        /* The site's sr-only pattern, same declaration as .home-sr-only. */
        .blog-search-sr{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        .blog-search input{
          width:100%;box-sizing:border-box;height:52px;padding:0 44px 0 2px;
          font-size:17px;font-family:inherit;color:#1a1a1a;background:transparent;
          border:0;border-bottom:1px solid #e5e7eb;border-radius:0;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .blog-search input::placeholder{color:rgba(0,0,0,.44)}
        .blog-search input:focus-visible{
          border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470;
        }
        /* THE RSS ICON'S ROW AT THE BOTTOM. End-aligned under the grid and pager, with the
           listing's own vertical rhythm above it. The icon styles itself (components/RssIcon.tsx). */
        .blog-rss-foot{display:flex;justify-content:flex-end;margin:40px 0 0}
        @media(prefers-reduced-motion:reduce){
          .blog-search input{transition:none}
        }

        /* THE PAGER'S RULES ARE GONE FROM THIS FILE, all of them, including the three that used
           to sit in the narrow-screen block below (.pager gap, .pager-list order:3 and the
           :global(.pager-step) flex:1). They live in components/Pager.tsx now, with the markup
           they style, and they HAD to move together: nav.pager and ol.pager-list carry Pager's
           styled-jsx hash, so a rule left here would match nothing and the mobile pager would
           silently lose its wrap-to-own-row layout on both listings - with nothing to catch it,
           because jsdom cannot read a computed style. src/test/Pager.test.tsx pins the media
           block in its new home. */

        /* THE BREAKPOINTS ARE THE HOME PAGE'S NOW: 1024px and 767px, not 1050px and 680px.
           Four steps across two files that mean the same thing is how a layout ends up
           reflowing in two places 30px apart. RotatingHero, which wraps this view and owns the
           band above it, already breaks at 767px, so the old 680px step meant the hero had
           gone to its narrow treatment while the grid below was still in its wide one. */
        @media(max-width:1024px){.post-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:767px){
          /* Nothing to override for the hero: its own narrow-screen padding applies. */
          .category-switch{margin-bottom:24px}
          .post-grid{grid-template-columns:1fr;gap:18px}
          .post-copy{padding:22px}
          /* The excerpt gets the full measure at one column, so it can run longer before the
             clamp bites - six lines rather than four. No new font size: same rung. */
          .post-copy p{-webkit-line-clamp:6}
        }
        /* THE REDUCED-MOTION BLOCK WAS AIMING AT NOTHING. It named
           .category-switch button, and the pills stopped being buttons when each category
           became its own route - so a reader who asks for less motion still got the pill
           transition and lift. The pills are next/link now, which is why the selector has to
           go through :global() exactly as the hover rules above do.
           Transform AND box-shadow are both cancelled: a shadow appearing under a card is the
           same "something moved" cue as the lift itself. */
        @media(prefers-reduced-motion:reduce){
          .post-card,.category-switch :global(a){transition:none}
          .post-card:hover,.category-switch :global(a:hover){transform:none;box-shadow:none}
        }
      `}</style>
    </RotatingHero>
  );
};

export default BlogIndexView;
