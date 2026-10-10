import React, { useCallback, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import type { BlogCard } from '../lib/public-blog';

/**
 * THE RIGHT-HAND BLOG PANEL on a product page (today only /anew/).
 *
 * A product page is one centred column at most 700px wide inside RotatingHero's 1300px measure,
 * so on a wide screen there is ~500px of unused space to its right. This fills it with a reader of
 * the blog: a two-category switch, a live borderless search, and the FULL list of cards (no cap)
 * in a scrollable rail, with a progress bar at the foot that tracks how far the reader has
 * scrolled through the list. On a narrow screen the two-column grid in ProductPage collapses and
 * this drops below the product copy.
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
 * THE PROGRESS BAR TRACKS SCROLL, NOT COUNT. It fills as the reader scrolls down the (unlimited)
 * list - 0% at the top, 100% at the bottom - rather than reporting shown-of-total. No numbers are
 * shown, per owner instruction: it is a pure visual scroll indicator.
 */

export interface ProductBlogPanelProps {
  cards: BlogCard[];
  /** Panel heading. */
  heading?: string;
}

const NEW_WINDOW_DAYS = 30;

/** Published within the last NEW_WINDOW_DAYS. Missing/!parseable date is never "new". */
function isNew ( publishedDate?: string ): boolean {
  if ( !publishedDate ) return false;
  const t = Date.parse( publishedDate );
  if ( Number.isNaN( t ) ) return false;
  return Date.now() - t <= NEW_WINDOW_DAYS * 24 * 60 * 60 * 1000;
}

/** "12 Oct 2026", UTC-fixed so server and client agree during static export. */
function cardDate ( publishedDate?: string ): string {
  if ( !publishedDate ) return '';
  const d = new Date( publishedDate );
  if ( Number.isNaN( d.getTime() ) ) return '';
  return d.toLocaleDateString( 'en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' } );
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
  const [ scrolled, setScrolled ] = useState<number>( 0 );
  const listRef = useRef<HTMLUListElement | null>( null );

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

  // Scroll progress: 0 at the top of the list, 1 at the bottom. When the content fits (nothing to
  // scroll) it reads full, so the bar is never stuck empty on a short list.
  const onScroll = useCallback( (): void => {
    const el = listRef.current;
    if ( !el ) return;
    const max = el.scrollHeight - el.clientHeight;
    setScrolled( max <= 0 ? 1 : Math.min( 1, Math.max( 0, el.scrollTop / max ) ) );
  }, [] );

  // Reset scroll to the top when the result set changes, so the bar is not left mid-way over a
  // list that is now shorter.
  const selectCategory = useCallback( ( c: string ): void => {
    setCategory( c );
    const el = listRef.current;
    if ( el ) { el.scrollTop = 0; setScrolled( 0 ); }
  }, [] );

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
          onChange={ e => { setQuery( e.target.value ); const el = listRef.current; if ( el ) { el.scrollTop = 0; setScrolled( 0 ); } } }
        />
      </div>

      {/* The FULL list - no cap - in a scrollable rail. */}
      { filtered.length === 0
        ? <p className="pbp-empty" aria-live="polite">No posts match that search.</p>
        : (
          <ul className="pbp-list" ref={ listRef } onScroll={ onScroll }>
            { filtered.map( card => (
              <li key={ card.slug } className="pbp-card">
                <Link className="pbp-link" href={ `/post/${card.slug}/` }>
                  <span className="pbp-meta">
                    { isNew( card.publishedDate ) && <span className="pbp-badge">New</span> }
                    { card.category && <span className="pbp-chip">{ card.category }</span> }
                    { cardDate( card.publishedDate ) && <span className="pbp-date">{ cardDate( card.publishedDate ) }</span> }
                  </span>
                  <span className="pbp-title">{ card.title }</span>
                  { card.excerpt && <span className="pbp-excerpt">{ card.excerpt }</span> }
                </Link>
              </li>
            ) ) }
          </ul>
        ) }

      {/* SCROLL PROGRESS BAR at the foot of the panel. Pure visual - no numbers. The fill tracks
          how far the reader has scrolled through the list (0% top, 100% bottom). role=progressbar
          with a 0-100 range and a percentage valuenow so it is announced, with no on-screen text.
          Hidden when there is nothing to show. */}
      { filtered.length > 0 && (
        <div className="pbp-progress">
          <div
            className="pbp-progress-track"
            role="progressbar"
            aria-label="Reading progress through the list"
            aria-valuemin={ 0 }
            aria-valuemax={ 100 }
            aria-valuenow={ Math.round( scrolled * 100 ) }
          >
            <div className="pbp-progress-fill" style={ { width: `${Math.round( scrolled * 100 )}%` } } />
          </div>
        </div>
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

        /* THE LIST IS A SCROLL RAIL. Unlimited cards, capped by HEIGHT not count: it scrolls
           within the panel so the whole corpus is reachable without the panel running taller than
           the page. The progress bar below tracks this element's scroll. max-height leaves room
           for the heading, pills, search and the bar. Thin scrollbar, lime thumb, to match. */
        .pbp-list{
          list-style:none;margin:0;padding:0 2px 0 0;
          display:flex;flex-direction:column;gap:10px;
          max-height:min(70vh,620px);overflow-y:auto;overscroll-behavior:contain;
          scrollbar-width:thin;scrollbar-color:#d1f470 transparent;
        }
        .pbp-list::-webkit-scrollbar{width:6px}
        .pbp-list::-webkit-scrollbar-thumb{background:#d1f470;border-radius:50px}
        .pbp-list::-webkit-scrollbar-track{background:transparent}
        .pbp-card{margin:0}

        /* SCROLL PROGRESS BAR. The track is a hairline on near-white; the fill is lime - the one
           place lime labels progress rather than action, fine as a thin bar. No numbers. 14px of
           air above it. */
        .pbp-progress{margin:14px 0 0}
        .pbp-progress-track{
          width:100%;height:6px;border-radius:50px;background:#eef0f2;overflow:hidden;
        }
        .pbp-progress-fill{
          height:100%;border-radius:50px;background:#d1f470;
          transition:width .12s linear;
        }

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
        .pbp-date{font-size:12px;color:rgba(0,0,0,.44)}

        .pbp-title{font-size:17px;font-weight:700;line-height:1.3;letter-spacing:-.2px;color:#000}
        /* The short review: the post excerpt, clamped to two lines so no card runs long. */
        .pbp-excerpt{
          font-size:14px;line-height:1.45;color:rgba(0,0,0,.62);
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
        }

        @media(prefers-reduced-motion:reduce){
          .pbp-pill,.pbp-link,.pbp-search input,.pbp-progress-fill{transition:none}
          .pbp-link:hover{transform:none;box-shadow:none}
        }
      `}</style>
    </aside>
  );
};

export default ProductBlogPanel;
