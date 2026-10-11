import React from 'react';
import Link from 'next/link';

/**
 * The listing paginator. ONE declaration, every paginated listing.
 *
 * THE PERSPECTIVES-PANEL PAGER, SITEWIDE. Owner instruction: everywhere a numbered Previous/Next
 * paginator was used, show the product-page blog panel's control instead - two circular lime
 * arrow buttons plus a slim lime progress bar, NO page numbers. This component was that numbered
 * paginator (first/last/window of page links + Newer/Older steps); it is now the Perspectives
 * pager, so every consumer (the blog index, and anything else that renders <Pager>) picks the new
 * look up from one place. src/components/ProductBlogPanel.tsx (.pbp-arrows / .pbp-progress-track)
 * is the control this mirrors rung for rung.
 *
 * STILL URL-DRIVEN, UNLIKE THE SHOP RAIL. The shop renders one horizontal scroll row and its
 * arrows scroll it; a URL-paginated listing like the blog has no single row to scroll - each page
 * is its own prerendered route. So here the arrows are real prev/next LINKS to the adjacent page
 * URL, which keeps the no-JavaScript path working and keeps the crawlable rel=prev/next the SEO
 * rule wants. The progress bar shows page / totalPages as position, with no number printed.
 *
 * SELF-STYLING, like Breadcrumbs, RotatingHero and BlogSearch: styled-jsx does not scope a
 * composite component from its parent, so a consumer's <style jsx> cannot reach in here. It owns
 * every rule it needs, including its own narrow-screen block.
 *
 * THE ARROWS ARE DRAWN CHEVRONS (‹ ›), the same glyphs the Anew panel uses, not webfont-dependent
 * U+2190/U+2192 that fall back to tofu when the face is unavailable.
 */

/**
 * KEPT AND STILL EXPORTED, though the pager no longer prints numbers. Which page numbers a
 * windowed numeric pager would show is a pure function with its own tests
 * (src/test/Pager.test.tsx), and other code may still want "first, last, a window around the
 * current page". Removing it would be an unrelated deletion; it simply is not called from the
 * Perspectives pager below.
 */
export function pageWindow ( page: number, totalPages: number ): ( number | null )[] {
  if ( totalPages <= 7 ) return Array.from( { length: totalPages }, ( _, i ) => i + 1 );
  const around = [ page - 1, page, page + 1 ].filter( n => n > 1 && n < totalPages );
  const shown = [ 1, ...around, totalPages ];
  const out: ( number | null )[] = [];
  for ( let i = 0; i < shown.length; i++ ) {
    if ( i > 0 && shown[ i ] - shown[ i - 1 ] > 1 ) out.push( null );
    out.push( shown[ i ] );
  }
  return out;
}

interface PagerProps {
  /** 1-based. */
  page: number;
  totalPages: number;
  /** Where a page goes. Each listing owns its own URL shape. */
  hrefFor: ( page: number ) => string;
  /** Accessible name for the nav landmark, e.g. "Blog pages". */
  ariaLabel: string;
  /**
   * STEP LABELS, now the arrows' accessible names only (nothing visible prints them). Defaulted
   * to the blog's Newer/Older so BlogIndexView passes nothing; the shop no longer uses this
   * component, so Previous/Next is here only for any future URL-paginated caller that wants it.
   */
  prevLabel?: string;
  nextLabel?: string;
}

const Pager: React.FC<PagerProps> = ( {
  page, totalPages, hrefFor, ariaLabel, prevLabel = 'Newer', nextLabel = 'Older',
} ) => {
  const hasPrev = page > 1;
  const hasNext = page < totalPages;
  // Position through the run, 0..1. A single-page run reads as full; a floor keeps a sliver of
  // lime visible on page 1 of a long run so the bar never looks empty.
  const progress = totalPages <= 1 ? 1 : page / totalPages;

  return (
    <nav className="pager" aria-label={ ariaLabel }>
      {/* ARROWS pinned right, matching the Anew Perspectives panel. Real prev/next links where a
          page exists (rel=prev/next, crawlable, no-JS); an inert, aria-hidden span at the end of
          the run so the row does not reflow as a reader pages through. No page numbers. */}
      <div className="pager-row">
        <div className="pager-arrows">
          { hasPrev
            ? <Link className="pager-arrow" rel="prev" href={ hrefFor( page - 1 ) } aria-label={ `${prevLabel} page` }>‹</Link>
            : <span className="pager-arrow is-off" aria-hidden="true">‹</span> }
          { hasNext
            ? <Link className="pager-arrow" rel="next" href={ hrefFor( page + 1 ) } aria-label={ `${nextLabel} page` }>›</Link>
            : <span className="pager-arrow is-off" aria-hidden="true">›</span> }
        </div>
      </div>

      {/* POSITION BAR - lime fill, no numbers. role=progressbar carries the position for assistive
          tech since nothing is printed; aria-valuetext says it in words rather than exposing a
          raw page count the sighted reader does not see. */}
      <div
        className="pager-progress-track"
        role="progressbar"
        aria-label="Position through the pages"
        aria-valuemin={ 1 }
        aria-valuemax={ totalPages }
        aria-valuenow={ page }
        aria-valuetext={ `Page ${page} of ${totalPages}` }
      >
        <div className="pager-progress-fill" style={ { width: `${Math.max( progress * 100, 4 )}%` } } />
      </div>

      <style jsx>{`
        /* THE PAGER, on the Anew panel's rungs (components/ProductBlogPanel .pbp-arrows /
           .pbp-progress-track). A column: the arrows pinned right on their own row, the lime
           progress bar below. Same top border and spacing the numbered pager used, so the listing
           footer keeps its shape. */
        .pager{display:flex;flex-direction:column;gap:12px;margin:48px 0 0;padding:24px 0 0;border-top:1px solid #e5e7eb}
        .pager-row{display:flex;align-items:center;justify-content:flex-end}
        .pager-arrows{display:flex;align-items:center;gap:8px}

        /* EVERY ARROW RULE GOES THROUGH :global(), because .pager-arrow is on a next/link
           (capitalised component), and styled-jsx attaches its scoping class only to lowercase
           DOM tags it can see here - a bare .pager-arrow rule would match nothing and the arrows
           would render as plain blue chevrons. .pager itself is a <nav> in this file and carries
           the hash, so these compile to .jsx-xxx.pager .pager-arrow and cannot leak out.
           Lime-themed to match the pill language: dark-green 2px edge at rest (2px means
           hoverable), full lime on hover like the CTA. 44x44 is the WCAG 2.5.8 touch floor. */
        .pager :global(.pager-arrow){
          display:inline-flex;align-items:center;justify-content:center;
          width:44px;height:44px;flex:0 0 auto;
          border:2px solid #1a3a2a;border-radius:50%;background:#fff;
          color:#1a3a2a;font-size:20px;line-height:1;text-decoration:none;
          transition:background-color .2s,border-color .2s,opacity .2s;
        }
        .pager :global(.pager-arrow:hover){background:#d1f470}
        .pager :global(.pager-arrow:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px}
        /* The end of the run: faint, not announced. Same intentional contrast carve-out the
           numbered pager documented - an inactive control has no WCAG 1.4.3 contrast floor, and
           aria-hidden keeps it out of the accessibility tree, so "unavailable" never looks
           available. */
        .pager :global(.pager-arrow.is-off){
          opacity:.3;cursor:default;border-color:#cfd4d9;color:rgba(0,0,0,.4);
        }

        /* POSITION BAR: hairline track, lime fill, no numbers - the one place lime marks progress
           rather than action, fine as a thin bar. The fill width is inline from page/totalPages,
           with a 4% floor so a sliver shows on page 1. */
        .pager-progress-track{
          width:100%;height:6px;border-radius:50px;background:#eef0f2;overflow:hidden;
        }
        .pager-progress-fill{
          height:100%;border-radius:50px;background:#d1f470;transition:width .2s ease;
        }

        /* The narrow-screen block stays declared on THIS component (its tags carry this file's
           hash), even though there is little to reflow now - the arrows are a 44px pair that fits
           any width. Keeping the block means a future rule has a home here rather than drifting
           back into a consumer's stylesheet, which was the bug the numbered pager documented. */
        @media(max-width:767px){
          .pager{gap:10px}
        }
        @media(prefers-reduced-motion:reduce){
          .pager :global(.pager-arrow),.pager-progress-fill{transition:none}
        }
      `}</style>
    </nav>
  );
};

export default Pager;
