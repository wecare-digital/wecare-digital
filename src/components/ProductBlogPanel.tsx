import React, { useCallback, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import type { BlogCard } from '../lib/public-blog';

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
 * tags, publishedDate. Nothing new is fetched; anew.tsx hands these in from getStaticProps.
 *
 * THE SEARCH BOX IS DELIBERATELY PLAINER THAN BlogSearch. Owner spec: no inner border, no search
 * icon, no submit button - it filters live as you type.
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
  /** Panel heading. */
  heading?: string;
}

const NEW_WINDOW_DAYS = 30;

/**
 * HOW MANY CARDS PER PAGE. Four reads as a comfortable page in the ~460px rail: enough to feel
 * like a spread, few enough that a page rarely needs to scroll. The last page simply holds the
 * remainder.
 */
const CARDS_PER_PAGE = 4;

/** True when the OS asks for reduced motion, so page changes jump instead of sliding. SSR-safe. */
function prefersReducedMotion (): boolean {
  if ( typeof window === 'undefined' || !window.matchMedia ) return false;
  return window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
}

/** Published within the last NEW_WINDOW_DAYS. Missing/!parseable date is never "new". */
function isNew ( publishedDate?: string ): boolean {
  if ( !publishedDate ) return false;
  const t = Date.parse( publishedDate );
  if ( Number.isNaN( t ) ) return false;
  return Date.now() - t <= NEW_WINDOW_DAYS * 24 * 60 * 60 * 1000;
}

const ProductBlogPanel: React.FC<ProductBlogPanelProps> = ( { cards, heading = 'From the blog' } ) => {
  // The real categories present in the data, sorted. No "All" - owner instruction.
  const categories = useMemo<string[]>( () => {
    const set = new Set<string>();
    for ( const c of cards ) if ( c.category ) set.add( c.category );
    return Array.from( set ).sort( ( a, b ) => a.localeCompare( b ) );
  }, [ cards ] );

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
  // each page scrolls vertically on its own if its four cards overflow the rail.
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

  return (
    <aside className="pbp" aria-label={ heading }>
      <h2 className="pbp-h">{ heading }</h2>

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

      {/* Borderless live search. A real labelled input (sr-only label), no icon, no button. */}
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
      </div>

      {/* THE SWIPEABLE PAGER. The track is a horizontal scroll-snap container: each child .pbp-page
          is one viewport wide, so a touch swipe snaps page to page natively, and the arrow buttons
          / arrow keys drive the same scrollTo. Each page is its own vertical scroller, so swiping
          sideways and scrolling a long page down never fight. */}
      { filtered.length === 0
        ? <p className="pbp-empty" aria-live="polite">No posts match that search.</p>
        : (
          <>
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
                      <Link className="pbp-link" href={ `/post/${card.slug}/` } tabIndex={ pageIndex === activePage ? undefined : -1 }>
                        <span className="pbp-meta">
                          { isNew( card.publishedDate ) && <span className="pbp-badge">New</span> }
                          { card.category && <span className="pbp-chip">{ card.category }</span> }
                        </span>
                        <span className="pbp-title">{ card.title }</span>
                        { card.excerpt && <span className="pbp-excerpt">{ card.excerpt }</span> }
                      </Link>
                    </li>
                  ) ) }
                </ul>
              ) ) }
            </div>

            {/* PAGER CONTROLS: a previous/next arrow pair and a row of page dots. Shown only when
                there is more than one page - a single page needs no navigation. The dots mark
                position, not count; no numbers, per owner instruction. */}
            { pageCount > 1 && (
              <div className="pbp-nav">
                <button
                  type="button"
                  className="pbp-arrow"
                  aria-label="Previous page"
                  disabled={ activePage === 0 }
                  onClick={ () => goToPage( activePage - 1 ) }
                >‹</button>

                <div className="pbp-dots" role="tablist" aria-label="Blog pages">
                  { pages.map( ( _p, i ) => (
                    <button
                      key={ i }
                      type="button"
                      className={ i === activePage ? 'pbp-dot is-on' : 'pbp-dot' }
                      aria-label={ `Go to page ${i + 1}` }
                      aria-current={ i === activePage ? 'true' : undefined }
                      onClick={ () => goToPage( i ) }
                    />
                  ) ) }
                </div>

                <button
                  type="button"
                  className="pbp-arrow"
                  aria-label="Next page"
                  disabled={ activePage >= pageCount - 1 }
                  onClick={ () => goToPage( activePage + 1 ) }
                >›</button>
              </div>
            ) }
          </>
        ) }

      <style jsx>{`
        .pbp{max-width:460px}
        .pbp-h{
          font-size:clamp(22px,2.4vw,28px);font-weight:700;line-height:1.1;
          letter-spacing:-.5px;color:rgba(0,0,0,.95);margin:0 0 18px;
        }

        /* PILLS - the site's pill geometry. Lime active, hairline inactive, no new colours. */
        .pbp-pills{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
        .pbp-pill{
          display:inline-flex;align-items:center;min-height:36px;padding:0 16px;
          border:1px solid #e5e7eb;border-radius:50px;background:#fff;
          color:#1a3a2a;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;
          transition:background-color .2s,border-color .2s;
        }
        .pbp-pill:hover{border-color:#1a3a2a}
        .pbp-pill.is-on{background:#d1f470;border-color:#1a3a2a}
        .pbp-pill:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

        /* BORDERLESS SEARCH. No inner border, no icon, no button. One quiet bottom hairline so it
           still reads as a field; the hairline darkens and a lime underline grows on focus. */
        .pbp-search{position:relative;margin:0 0 16px}
        .pbp-sr{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        .pbp-search input{
          width:100%;box-sizing:border-box;height:48px;padding:0 2px;
          font-size:17px;font-family:inherit;color:#1a1a1a;background:transparent;
          border:0;border-bottom:1px solid #e5e7eb;border-radius:0;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .pbp-search input::placeholder{color:rgba(0,0,0,.44)}
        .pbp-search input:focus-visible{
          border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470;
        }

        .pbp-empty{margin:0;font-size:14px;line-height:1.4;color:rgba(0,0,0,.54)}

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
          scrollbar-width:none;outline:none;
        }
        .pbp-track::-webkit-scrollbar{display:none}
        .pbp-track:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;border-radius:14px}

        /* ONE PAGE. Exactly the track's width so one page shows at a time and the next sits just
           off-screen to swipe to. Its own vertical scroller: four cards usually fit, but a page
           that overflows scrolls down on its own without disturbing the horizontal swipe. */
        .pbp-page{
          list-style:none;margin:0;padding:2px;
          flex:0 0 100%;width:100%;box-sizing:border-box;
          scroll-snap-align:start;scroll-snap-stop:always;
          display:flex;flex-direction:column;gap:10px;
          max-height:min(70vh,620px);overflow-y:auto;overscroll-behavior:contain;
        }
        .pbp-card{margin:0}

        /* PAGER CONTROLS: arrows flanking a row of dots, centred, 14px of air above. */
        .pbp-nav{display:flex;align-items:center;justify-content:center;gap:12px;margin:14px 0 0}
        .pbp-arrow{
          display:inline-flex;align-items:center;justify-content:center;
          width:34px;height:34px;flex:0 0 auto;
          border:1px solid #e5e7eb;border-radius:50%;background:#fff;
          color:#1a3a2a;font-size:20px;line-height:1;font-family:inherit;cursor:pointer;
          transition:background-color .2s,border-color .2s,opacity .2s;
        }
        .pbp-arrow:hover:not(:disabled){border-color:#1a3a2a;background:#d1f470}
        .pbp-arrow:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
        .pbp-arrow:disabled{opacity:.35;cursor:default}

        /* PAGE DOTS. Hairline dots; the active one fills lime and widens into a pill - position,
           not count, no numbers. */
        .pbp-dots{display:flex;align-items:center;gap:8px}
        .pbp-dot{
          width:8px;height:8px;flex:0 0 auto;padding:0;
          border:1px solid #cfd4d9;border-radius:50px;background:#fff;cursor:pointer;
          transition:width .2s,background-color .2s,border-color .2s;
        }
        .pbp-dot:hover{border-color:#1a3a2a}
        .pbp-dot.is-on{width:22px;background:#d1f470;border-color:#1a3a2a}
        .pbp-dot:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

        /* The whole card is the link. Hairline quiet card, lifts and borders dark on hover. */
        .pbp-link{
          display:flex;flex-direction:column;gap:6px;
          padding:16px;border:1px solid #e5e7eb;border-radius:14px;background:#fcfdfb;
          text-decoration:none;color:inherit;
          transition:border-color .2s,transform .2s,box-shadow .2s;
        }
        .pbp-link:hover{border-color:#1a3a2a;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .pbp-link:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

        .pbp-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
        /* STATUS: a lime "New" badge for recent posts. */
        .pbp-badge{
          display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:11px;font-weight:700;letter-spacing:.02em;
          text-transform:uppercase;
        }
        /* STATUS: the category as a quiet chip. */
        .pbp-chip{
          display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:50px;
          border:1px solid #e5e7eb;color:rgba(0,0,0,.62);font-size:11px;font-weight:600;
          letter-spacing:.02em;text-transform:uppercase;
        }
        .pbp-title{font-size:17px;font-weight:700;line-height:1.3;letter-spacing:-.2px;color:#000}
        /* The short review: the post excerpt, clamped to two lines so no card runs long. */
        .pbp-excerpt{
          font-size:14px;line-height:1.45;color:rgba(0,0,0,.62);
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
        }

        @media(prefers-reduced-motion:reduce){
          .pbp-pill,.pbp-link,.pbp-search input,.pbp-arrow,.pbp-dot{transition:none}
          .pbp-link:hover{transform:none;box-shadow:none}
          /* A reduced-motion reader gets instant page jumps instead of the smooth scroll; the
             track still snaps, it just does not animate the slide. */
          .pbp-track{scroll-behavior:auto}
        }
      `}</style>
    </aside>
  );
};

export default ProductBlogPanel;
