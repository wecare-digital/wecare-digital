import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import type { BlogCard } from '../lib/public-blog';
import { loadBlogCardIndex } from '../lib/blog-card-index';
import BlogTags from './BlogTags';
import RssIcon from './RssIcon';
import VoiceSearchMic from './VoiceSearchMic';
import { publicActionText } from '../lib/publicActionNotices';

/**
 * THE RIGHT-HAND BLOG PANEL on a product page (today only /anew/).
 *
 * A product page is one centred column at most 700px wide inside RotatingHero's 1300px measure,
 * so on a wide screen there is ~500px of unused space to its right. This fills it with a reader of
 * the blog: a two-category switch, a live borderless search, and the FULL list of cards (no cap)
 * laid out as a SWIPEABLE PAGER - the cards are grouped into pages, and the reader moves between
 * pages by swiping left/right (touch), dragging, pressing the arrow buttons, or the arrow keys.
 * Each page scrolls vertically on its own if its cards overflow, so swipe (horizontal) and scroll
 * (vertical) never fight. On a narrow screen the two-column grid in ProductPage collapses and this
 * drops below the product copy.
 *
 * DATES ARE NOT SHOWN. Owner instruction: the per-card published date was removed. The "New"
 * badge stays - it reads a date internally to decide recency but prints no date.
 *
 * SELF-STYLING, pbp- prefixed, for the same reason as RotatingHero and BlogSearch: styled-jsx does
 * not scope a composite component from its parent, so this owns every rule it needs.
 *
 * REUSES THE BLOG'S OWN DATA SHAPE. The cards are BlogCard (src/lib/public-blog.ts), the same
 * projection /blog/ renders and the same one search already matches on - title, excerpt, category,
 * tags, publishedDate. Anew supplies a small static seed; the shared blog index supplies the complete list after hydration.
 *
 * THE SEARCH BOX keeps the borderless live-search treatment and now carries the same shared
 * lime voice mic as the menu, VayuLok and the other public search surfaces.
 *
 * TWO CATEGORIES, NO "ALL". Owner instruction: the switch shows only the real categories
 * (Conversations, Gastronomy today), with no "All" option. It defaults to the first category.
 * The set is derived from the cards handed in, so a third category added later appears on its own.
 *
 * THE PAGE DOTS SHOW POSITION, NOT COUNT-OF-TOTAL. A row of dots marks how many pages the current
 * result set has and which one is in view, so the reader knows there is more to swipe to. No
 * numbers, per owner instruction - a pure visual indicator, matched by the two arrow buttons.
 */

export interface ProductBlogPanelProps {
  cards: BlogCard[];
  /** Complete category names enable progressive loading for the Anew static seed. */
  categories?: string[];
  /** Panel heading. */
  heading?: string;
}

/**
 * HOW MANY CARDS PER PAGE. Three gives each article enough room to read as editorial content
 * rather than a compressed widget. The last page simply holds the remainder.
 */
const CARDS_PER_PAGE = 3;

/** How many tag chips a card shows at most, so a heavily-tagged post does not run its card long. */
const CARD_TAGS = 2;

/** True when the OS asks for reduced motion, so page changes jump instead of sliding. SSR-safe. */
function prefersReducedMotion (): boolean {
  if ( typeof window === 'undefined' || !window.matchMedia ) return false;
  return window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
}

/** The first CARD_TAGS non-empty tags of a card, trimmed. Empty when the post carries none. */
function cardTags ( card: BlogCard ): string[] {
  return ( card.tags || [] )
    .map( t => t.trim() )
    .filter( Boolean )
    .slice( 0, CARD_TAGS );
}

const ProductBlogPanel: React.FC<ProductBlogPanelProps> = ( { cards: initialCards, categories: initialCategories, heading = 'From the blog' } ) => {
  const [ allCards, setAllCards ] = useState<BlogCard[] | null>( null );
  const [ failed, setFailed ] = useState( false );
  const [ attempt, setAttempt ] = useState( 0 );
  useEffect( () => {
    if ( !initialCategories ) return;
    let active = true;
    loadBlogCardIndex().then( cards => {
      // The generator emits an empty index when its API source is unavailable. Keep the
      // prerendered seed and expose retry rather than replacing useful cards with nothing.
      if ( !cards.length && initialCards.length ) throw new Error( 'Blog index unavailable' );
      if ( active ) { setAllCards( cards ); setFailed( false ); }
    } ).catch( () => { if ( active ) setFailed( true ); } );
    return () => { active = false; };
  }, [ initialCategories, attempt ] );
  const cards = allCards ?? initialCards;
  // The real categories present in the data, sorted. No "All" - owner instruction.
  const categories = useMemo<string[]>( () => {
    const set = new Set<string>( initialCategories );
    for ( const c of cards ) if ( c.category ) set.add( c.category );
    return Array.from( set ).sort( ( a, b ) => a.localeCompare( b ) );
  }, [ cards, initialCategories ] );

  const [ category, setCategory ] = useState<string>( () => categories[ 0 ] || '' );
  const [ query, setQuery ] = useState<string>( '' );
  const [ page, setPage ] = useState<number>( 0 );
  const trackRef = useRef<HTMLDivElement | null>( null );

  // Filter by active category, then by the typed query across title + excerpt + category + tags.
  const filtered = useMemo<BlogCard[]>( () => {
    const q = query.trim().toLowerCase();
    return cards.filter( c => {
      if ( category && c.category !== category ) return false;
      if ( !q ) return true;
      const hay = [
        c.title,
        c.excerpt || '',
        c.category || '',
        ...( c.tags || [] ),
      ].join( ' ' ).toLowerCase();
      return hay.includes( q );
    } );
  }, [ cards, category, query ] );

  // Group the filtered cards into fixed-size pages. The pager scrolls between these horizontally;
  // three editorial entries per page keeps the rail readable without an inner vertical scroller.
  const pages = useMemo<BlogCard[][]>( () => {
    const out: BlogCard[][] = [];
    for ( let i = 0; i < filtered.length; i += CARDS_PER_PAGE ) {
      out.push( filtered.slice( i, i + CARDS_PER_PAGE ) );
    }
    return out;
  }, [ filtered ] );

  const pageCount = pages.length;

  // Keep the active page in range and snap the track to it. The track is a horizontal
  // scroll-snap container, so moving pages is a scrollTo on the track - which also drives the
  // native touch swipe: the browser snaps to the nearest page and we read that back on scroll.
  const goToPage = useCallback( ( next: number ): void => {
    const clamped = Math.min( Math.max( 0, next ), Math.max( 0, pageCount - 1 ) );
    setPage( clamped );
    const el = trackRef.current;
    if ( el ) el.scrollTo( { left: clamped * el.clientWidth, behavior: prefersReducedMotion() ? 'auto' : 'smooth' } );
  }, [ pageCount ] );

  // Read the page back from a native swipe/drag: snap settles on a page boundary, so round the
  // track's scrollLeft to the nearest page width.
  const onTrackScroll = useCallback( (): void => {
    const el = trackRef.current;
    if ( !el || el.clientWidth === 0 ) return;
    const nearest = Math.round( el.scrollLeft / el.clientWidth );
    setPage( p => ( p === nearest ? p : Math.min( Math.max( 0, nearest ), Math.max( 0, pageCount - 1 ) ) ) );
  }, [ pageCount ] );

  // When the result set changes (new category or query), jump back to the first page.
  const resetToFirstPage = useCallback( (): void => {
    setPage( 0 );
    const el = trackRef.current;
    if ( el ) el.scrollTo( { left: 0, behavior: 'auto' } );
  }, [] );

  const selectCategory = useCallback( ( c: string ): void => {
    setCategory( c );
    resetToFirstPage();
  }, [ resetToFirstPage ] );

  // No clamp-in-effect is needed: every path that shrinks the result set (category switch, search
  // typing) routes through resetToFirstPage(), which puts the pager back on page 0 - a page that
  // always exists while there are any results. So `page` can never be left pointing past the end.
  // The active page used for ARIA/dots is still bounded defensively below.
  const activePage = Math.min( page, Math.max( 0, pageCount - 1 ) );

  // Arrow-key paging when focus is within the pager, so it is reachable without a pointer.
  const onTrackKeyDown = useCallback( ( e: React.KeyboardEvent<HTMLDivElement> ): void => {
    if ( e.key === 'ArrowRight' ) { e.preventDefault(); goToPage( activePage + 1 ); }
    else if ( e.key === 'ArrowLeft' ) { e.preventDefault(); goToPage( activePage - 1 ); }
  }, [ goToPage, activePage ] );

  const showPager = filtered.length > 0 && pageCount > 1;

  return (
    <aside className="pbp" aria-label={ heading }>
      {/* HEADER ROW: the heading on the left, the pager arrows pinned top-right (owner choice).
          Paging lives at the top so it is reachable without scrolling past the cards; the slim
          progress bar sits directly under this row as the position indicator. */}
      <div className="pbp-head">
        <div className="pbp-intro">
          <h2 className="pbp-h">{ heading }</h2>
          <p className="pbp-deck">Ideas worth another look.</p>
        </div>
      </div>

      {/* Category switch - the two real categories, no "All". Lime when active, hairline when
          not; the site's pill language, no new colours. */}
      <div className="pbp-pills" role="group" aria-label="Filter posts by category">
        { categories.map( c => (
          <button
            key={ c }
            type="button"
            className={ c === category ? 'pbp-pill is-on' : 'pbp-pill' }
            aria-pressed={ c === category }
            onClick={ () => selectCategory( c ) }
          >{ c }</button>
        ) ) }
      </div>

      {/* Borderless live search with the shared site voice mic. */}
      <div className="pbp-search">
        <label className="pbp-sr" htmlFor="pbp-q">Search the blog</label>
        <input
          id="pbp-q"
          type="search"
          autoComplete="off"
          placeholder="Search posts"
          value={ query }
          onChange={ e => { setQuery( e.target.value ); resetToFirstPage(); } }
        />
        <VoiceSearchMic onTranscript={ transcript => { setQuery( transcript ); resetToFirstPage(); } } />
      </div>

      { initialCategories && !allCards && (
        <div className={ failed ? 'pbp-load is-error' : 'pbp-load pbp-sr' } role="status">
          { failed
            ? <>{ publicActionText( 'failure' ) } <button type="button" onClick={ () => setAttempt( value => value + 1 ) }>Try again</button></>
            : publicActionText( 'processing' ) }
        </div>
      ) }
      {/* THE SWIPEABLE PAGER. The track is a horizontal scroll-snap container: each child .pbp-page
          is one viewport wide, so a touch swipe snaps page to page natively, and the arrow buttons
          / arrow keys drive the same scrollTo. */}
      { filtered.length === 0
        ? <p className="pbp-empty" aria-live="polite">No posts match that search.</p>
        : (
            <div
              className="pbp-track"
              ref={ trackRef }
              onScroll={ onTrackScroll }
              onKeyDown={ onTrackKeyDown }
              tabIndex={ 0 }
              role="group"
              aria-label={ `${heading}, page ${activePage + 1} of ${pageCount}` }
            >
              { pages.map( ( pageCards, pageIndex ) => (
                <ul
                  className="pbp-page"
                  key={ pageIndex }
                  aria-hidden={ pageIndex === activePage ? undefined : true }
                >
                  { pageCards.map( card => (
                    <li key={ card.slug } className="pbp-card">
                      {/* THE MAIN LINK COVERS TITLE + EXCERPT ONLY. The tags below are LINKS
                          now (shared BlogTags), and an <a> inside an <a> is invalid HTML - a
                          browser closes the outer anchor at the inner one, so the card's own
                          link would end early and the layout would break. So the tag nav is a
                          SIBLING after the card link, still inside the <li>: the card stays
                          clickable to the post, and each tag is its own link to a search. */}
                      <Link className="pbp-link" href={ `/post/${card.slug}/` } tabIndex={ pageIndex === activePage ? undefined : -1 }>
                        <h3 className="pbp-title">{ card.title }</h3>
                        { card.excerpt && <span className="pbp-excerpt">{ card.excerpt }</span> }
                      </Link>
                      {/* REAL TAGS, the shared component. Up to CARD_TAGS of the post's own tags,
                          each a link to /blog/?q=<tag> - the same object the post page renders.
                          The category is NOT repeated here because the active category pill at
                          the top already says which stream this is. Renders nothing when the post
                          carries no tags. */}
                      <BlogTags tags={ cardTags( card ) } className="pbp-tagrow" />
                    </li>
                  ) ) }
                </ul>
              ) ) }
            </div>
        ) }

      { showPager && (
        <div className="pbp-nav" aria-label="Perspectives pagination">
          <div className="pbp-nav-row">
            <div className="pbp-arrows">
              <button
                type="button"
                className="pbp-arrow"
                aria-label="Previous page"
                disabled={ activePage === 0 }
                onClick={ () => goToPage( activePage - 1 ) }
              >‹</button>
              <button
                type="button"
                className="pbp-arrow"
                aria-label="Next page"
                disabled={ activePage >= pageCount - 1 }
                onClick={ () => goToPage( activePage + 1 ) }
              >›</button>
            </div>
          </div>
          <div
            className="pbp-progress-track"
            role="progressbar"
            aria-label="Position through the pages"
            aria-valuemin={ 1 }
            aria-valuemax={ pageCount }
            aria-valuenow={ activePage + 1 }
            aria-valuetext={ `Page ${activePage + 1} of ${pageCount}` }
          >
            <div
              className="pbp-progress-fill"
              style={ { width: `${Math.max( ( ( activePage + 1 ) / pageCount ) * 100, 4 )}%` } }
            />
          </div>
        </div>
      ) }

      <div className="pbp-foot">
        <Link className="pbp-browse" href="/blog/">Browse perspectives <span aria-hidden="true">→</span></Link>
        <RssIcon />
      </div>

      <style jsx>{`
        .pbp{max-width:560px;width:100%}
        .pbp-foot{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:22px 0 0}
        /* min-height: the 44px tap floor. 8px padding around a 17px x 1.4 line came to 40px. */
        .pbp :global(.pbp-browse){
          display:inline-flex;align-items:center;gap:5px;width:max-content;margin-inline-start:-10px;padding:8px 10px;
          min-height:var(--tap-min);box-sizing:border-box;
          border-radius:10px;color:var(--public-brand-green);
          font-size:17px;font-weight:600;line-height:1.4;letter-spacing:-.05px;
          text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:3px;
          transition:background-color .18s,color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
        }
        .pbp :global(.pbp-browse:hover){
          background:var(--public-brand-lime);color:var(--public-brand-green);text-decoration-color:transparent;
          transform:translateY(-1px);box-shadow:0 6px 18px rgba(26,58,42,.12);
        }
        .pbp :global(.pbp-browse:focus-visible){
          background:var(--public-brand-lime);color:var(--public-brand-green);text-decoration-color:transparent;
          outline:3px solid var(--public-brand-green);outline-offset:3px;
        }

        /* HEADER ROW: heading left, pager arrows pinned right. Baseline-aligned so the arrows sit
           on the heading's line rather than floating. The progress bar follows directly below. */
        .pbp-head{margin:0 0 24px}
        .pbp-intro{display:flex;flex-direction:column;gap:8px}
        .pbp-h{
          font-size:clamp(24px,2.6vw,30px);font-weight:700;line-height:1.08;
          letter-spacing:-.6px;color:rgba(0,0,0,.95);margin:0;
        }
        .pbp-deck{
          margin:0;max-width:34ch;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-muted);
        }

        /* PILLS - the site's pill geometry. Lime active, hairline inactive, no new colours. */
        .pbp-pills{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 20px}
        .pbp-pill{
          display:inline-flex;align-items:center;min-height:44px;padding:0 18px;
          border:1px solid var(--public-hairline);border-radius:50px;background:#fff;
          color:var(--public-brand-green);font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);font-family:inherit;cursor:pointer;
          transition:background-color .2s,border-color .2s;
        }
        .pbp-pill:hover{border-color:var(--public-brand-green)}
        .pbp-pill.is-on{background:var(--public-brand-lime);border-color:var(--public-brand-green)}
        .pbp-pill:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}

        /* BORDERLESS SEARCH. One quiet bottom hairline plus the shared lime voice mic. */
        .pbp-search{position:relative;margin:0 0 28px}
        .pbp-sr{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        .pbp-search input{
          width:100%;box-sizing:border-box;height:48px;padding:0 44px 0 2px;
          font-size:18px;font-family:inherit;color:#1a1a1a;background:transparent;
          border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .pbp-search input::placeholder{color:rgba(0,0,0,.44)}
        .pbp-search input:focus-visible{
          border-bottom-color:var(--public-brand-green);box-shadow:0 1px 0 0 var(--public-brand-lime);
        }

        .pbp-empty{margin:0;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted)}

        /* THE PAGER TRACK. A horizontal scroll-snap container, one page wide, that holds the pages
           side by side. scroll-snap-type:x mandatory makes a touch swipe settle cleanly on a page;
           overflow-x is the swipe axis; overscroll-behavior:contain stops a swipe past the last
           page from scrolling the browser. The scrollbar colour is NOT set here on purpose: the
           canonical global block in src/styles/inner-ux.css styles every scroller from the
           --scrollbar-* tokens, and ScrollbarDeclarations.test.ts forbids a second colour
           declaration in a component. scrollbar-width:none hides the horizontal bar because the
           dots and arrows are the page affordance; the per-page vertical scrollbar still shows. */
        .pbp-track{
          display:flex;flex-direction:row;
          overflow-x:auto;overflow-y:hidden;
          scroll-snap-type:x mandatory;overscroll-behavior:contain;
          /* Momentum scrolling for the horizontal swipe on older iOS Safari / iOS WebView, where
             it is off by default and a swipe otherwise feels dead. Harmless elsewhere. */
          -webkit-overflow-scrolling:touch;
          scrollbar-width:none;outline:none;
        }
        .pbp-track::-webkit-scrollbar{display:none}
        .pbp-track:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px;border-radius:14px}

        /* ONE PAGE. Exactly the track's width so one editorial page shows at a time and the next
           sits just off-screen to swipe to. Three entries keep the rail readable without nesting
           another vertical scroll area inside the page. */
        .pbp-page{
          list-style:none;margin:0;padding:2px 2px 0;
          flex:0 0 100%;width:100%;box-sizing:border-box;
          scroll-snap-align:start;scroll-snap-stop:always;
          display:flex;flex-direction:column;gap:24px;
        }
        .pbp-card{margin:0;padding:0 0 24px;border-bottom:1px solid var(--public-hairline)}
        .pbp-card:last-child{padding-bottom:0;border-bottom:0}

        /* PAGER CONTROLS: arrows flanking the progress bar, which stretches to fill the row.
        /* PAGER ARROWS - lime-themed, matching our pill language. Dark-green border and lime type
           at rest (so they read as "ours" before you touch them), filling full lime on hover like
           the CTA. 2px border because the house rule is 2px means hoverable. */
        .pbp-arrow{
          display:inline-flex;align-items:center;justify-content:center;
          /* 44x44 is the WCAG 2.5.8 / platform minimum touch target, so the arrows are reliably
             tappable on phones, foldables and in-app browsers, not just clickable with a mouse. */
          width:44px;height:44px;flex:0 0 auto;
          border:2px solid #1a3a2a;border-radius:50%;background:#fff;
          color:var(--public-brand-green);font-size:20px;line-height:1;font-family:inherit;cursor:pointer;
          transition:background-color .2s,border-color .2s,opacity .2s;
        }
        .pbp-arrow:hover:not(:disabled){background:var(--public-brand-lime)}
        .pbp-arrow:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}
        .pbp-arrow:disabled{opacity:.3;cursor:default;border-color:#cfd4d9;color:rgba(0,0,0,.4)}

        .pbp-nav{
          display:flex;flex-direction:column;gap:12px;margin:26px 0 0;padding:24px 0 0;
          border-top:1px solid var(--public-hairline);
        }
        .pbp-nav-row{display:flex;align-items:center;justify-content:flex-end}
        .pbp-arrows{display:flex;align-items:center;gap:8px}
        .pbp-progress-track{
          width:100%;height:6px;border-radius:50px;background:#eef0f2;overflow:hidden;
          margin:0;
        }
        .pbp-progress-fill{
          height:100%;border-radius:50px;background:var(--public-brand-lime);
          transition:width .2s ease;
        }

        /* The whole card is the link. Hairline quiet card at rest; on hover it lifts, borders dark
           green and the surface warms to the site's quiet lime tint - the same brand lime hover
           the rest of the page uses (the CTA's full #d1f470, the number markers' .22 tint). A soft
           rgba(209,244,112,.18) is used rather than full-strength lime so a whole card hovering
           does not read as a second CTA; the dark-green border is what says "actionable". */
        .pbp-link{
          display:flex;flex-direction:column;gap:9px;
          padding:0;text-decoration:none;color:inherit;
          transition:color .2s;
        }
        .pbp-link:hover .pbp-title{color:var(--public-brand-green)}
        .pbp-link:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:4px;border-radius:4px}

        /* TAG ROW at the foot of a card, now the shared BlogTags component (nav.tags.pbp-tagrow).
           BlogTags styles the pills themselves - the dot, the hairline, the lime hover; this only
           overrides its container, which at rest carries the 52px top margin and the hairline rule
           that suit the end of an article, not the foot of a 16px card. :global() because the nav
           is a composite component, so styled-jsx does not scope it from here - the same reason
           .pbp-link below is reached through the structure rather than a scoped class. The old
           per-card .pbp-chip went with the markup: the chips are links now and live in BlogTags. */
        .pbp-card :global(.pbp-tagrow){margin-top:12px;padding-top:0;border-top:0}
        .pbp-title{
          margin:0;font-size:var(--public-card-size);font-weight:var(--public-card-weight);
          line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading);
          transition:color .2s;
        }
        .pbp-excerpt{
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body);
          display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
        }

        @media(prefers-reduced-motion:reduce){
          .pbp-pill,.pbp-link,.pbp-title,.pbp-search input,.pbp-arrow,.pbp-progress-fill{transition:none}
          .pbp :global(.pbp-browse){transition:none}
          .pbp :global(.pbp-browse:hover){transform:none;box-shadow:none}
          /* A reduced-motion reader gets instant page jumps instead of the smooth scroll; the
             track still snaps, it just does not animate the slide. */
          .pbp-track{scroll-behavior:auto}
        }
      `}</style>
    </aside>
  );
};

export default ProductBlogPanel;
