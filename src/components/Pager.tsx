import React from 'react';
import Link from 'next/link';

/**
 * The listing paginator. ONE declaration, two listings.
 *
 * EXTRACTED FROM BlogIndexView, NOT COPIED. /shop/ needed "the exact blog paginator", and the
 * other way to get one was a second copy of this markup plus about 45 lines of CSS that carries
 * a documented :global() trap and a documented WCAG contrast carve-out. Two copies of that drift,
 * and a fix lands on one listing. So the control moved here whole and BlogIndexView imports it -
 * every class name, every attribute and every declaration is what it was, which is why
 * src/test/BlogDesign.test.tsx needs no edit.
 *
 * SELF-STYLING, like Breadcrumbs, RotatingHero and BlogSearch: styled-jsx does not scope a
 * composite component from its parent, so a consumer's <style jsx> cannot reach in here. It owns
 * every rule it needs, INCLUDING its own @media(max-width:767px) block - those three responsive
 * rules used to sit in BlogIndexView's shared narrow-screen block, and leaving them there would
 * have left them matching nothing: nav.pager and ol.pager-list now carry THIS component's hash.
 * Nothing would have caught it either; jsdom cannot read a computed style and every pager
 * assertion in BlogDesign.test.tsx is DOM-level.
 *
 * THE ARROW IS DRAWN, NOT TYPED. The steps read "← Newer" and "Older →" with literal U+2190 /
 * U+2192, and in a browser with the webfont unavailable both rendered as TOFU - a hollow box -
 * beside perfectly legible text. Measured with a canvas advance-width comparison: the arrows came
 * back identical to a private-use codepoint that has no glyph anywhere. A rotated border box
 * cannot fall back to a missing glyph. Same technique as Breadcrumbs' chevron.
 *
 * "UNLIMITED" PAGINATION IS WHAT pageWindow ALREADY DELIVERS: no page cap anywhere, every number
 * printed up to 7 pages, and first + last + a window around the current page beyond that.
 */

/**
 * Which page numbers to render. 35 pages of numbers is its own wall of links, so this shows
 * first, last, and a window around the current page, with gaps marked. Returns numbers and
 * nulls, where null is an elision.
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
  /** Where a page number goes. Each listing owns its own URL shape. */
  hrefFor: ( page: number ) => string;
  /** Accessible name for the nav landmark, e.g. "Blog pages". */
  ariaLabel: string;
  /**
   * STEP LABELS, DEFAULTED TO THE BLOG'S. The blog is sorted newest-first, so its directions are
   * Newer and Older, and defaulting to them is what lets BlogIndexView pass nothing and render
   * byte for byte what it rendered before the extraction.
   *
   * The shop passes Previous and Next instead, because its order is declaration order and then
   * name order: telling a reader the next six products are "Older" would be a statement about a
   * sort this listing does not perform.
   */
  prevLabel?: string;
  nextLabel?: string;
}

const Pager: React.FC<PagerProps> = ( {
  page, totalPages, hrefFor, ariaLabel, prevLabel = 'Newer', nextLabel = 'Older',
} ) => {
  const windowed = pageWindow( page, totalPages );

  return (
    <nav className="pager" aria-label={ ariaLabel }>
      {/* rel=prev/next as well as the visible label: Google retired them as an indexing
          signal, they are still the semantic relationship, and some readers' browsers and
          extensions use them to move between pages. */}
      { page > 1
        ? <Link className="pager-step is-prev" rel="prev" href={ hrefFor( page - 1 ) }>
          <i className="pager-mark" aria-hidden="true" />{ prevLabel }
        </Link>
        : <span className="pager-step is-prev is-off" aria-hidden="true">
          <i className="pager-mark" />{ prevLabel }
        </span> }

      <ol className="pager-list">
        { windowed.map( ( n, i ) => (
          <li key={ n === null ? `gap-${i}` : n }>
            { n === null
              // A real character, not a styled empty element: a screen reader
              // needs something between "1" and "17" or the jump is silent.
              ? <span className="pager-gap">…</span>
              : n === page
                // aria-current is what says WHICH page this is. Bold alone says it
                // to sighted readers only, and a link to the page you are on is a
                // control that does nothing.
                ? <span className="pager-num is-here" aria-current="page">{ n }</span>
                : <Link className="pager-num" href={ hrefFor( n ) }>
                  <span className="pager-sr">Page </span>{ n }
                </Link> }
          </li>
        ) ) }
      </ol>

      { page < totalPages
        ? <Link className="pager-step is-next" rel="next" href={ hrefFor( page + 1 ) }>
          { nextLabel }<i className="pager-mark" aria-hidden="true" />
        </Link>
        : <span className="pager-step is-next is-off" aria-hidden="true">
          { nextLabel }<i className="pager-mark" />
        </span> }

      <style jsx>{`
        /* THE PAGER. 44px minimum touch target on every control - that is the WCAG 2.5.8
           floor and a row of page numbers is exactly the case it exists for. Sizes reuse
           existing rungs: 12px radius from the search field, the lime-on-dark-green pairing
           from the closing band's button for the current page. */
        /* EVERY CHILD SELECTOR HERE GOES THROUGH :global(), AND WITHOUT IT NONE OF THIS APPLIED.
           styled-jsx adds its scoping class only to lowercase DOM tags it can see in this file,
           never to a capitalised component - it cannot know whether the component forwards
           className to a DOM node. The steps and the page numbers are next/link, so they rendered
           class="pager-step" with no jsx- hash and the compiled .jsx-xxx.pager-step rule matched
           nothing. The current page and the dead direction are <span>, so THOSE were styled.
           Measured on the built page before this fix, at /blog/page/2/:
             a.pager-step   69x32   radius 0   border 0   transparent
             a.pager-num     7x20   radius 0   border 0   transparent
             span.pager-num.is-here  44x44  radius 12px  border 2px  lime
           So the row read as one lime chip beside bare 7px-wide text, the 44px touch targets the
           comment above claims did not exist, and 2.5.8 failed on the only navigation control on
           the page. It is the identical trap .home-close-cta documents on the home page.
           :global() INSIDE A SCOPED PARENT rather than a bare :global - .pager itself is a <nav>
           in this file and does carry the hash, so these compile to .jsx-xxx.pager .pager-step and
           cannot leak out of this component.
           Do not "simplify" these back to plain selectors, and do not swap next/link for <a> to
           avoid the wrapper: the link keeps client-side navigation, and an inner <span> carrying
           the class would move the class off the focusable element and break the focus ring. */
        .pager{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:48px 0 0;padding:24px 0 0;border-top:1px solid #e5e7eb}
        .pager-list{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin:0;padding:0;list-style:none}
        .pager :global(.pager-num),.pager :global(.pager-step),.pager :global(.pager-gap){
          display:inline-flex;align-items:center;justify-content:center;gap:8px;
          min-width:44px;min-height:44px;padding:0 12px;
          border-radius:12px;font-size:16px;font-weight:600;
          color:#1a3a2a;text-decoration:none;
        }
        /* The direction mark: two borders of a square, rotated. currentColor so it dims with the
           text in the is-off state without a second rule. 2px to match the step's own border
           weight - a 1px mark beside a 2px edge reads as a different object. */
        .pager :global(.pager-mark){
          width:7px;height:7px;flex:0 0 auto;
          border-top:2px solid currentColor;border-right:2px solid currentColor;
        }
        .pager :global(.is-prev .pager-mark){transform:rotate(-135deg)}
        .pager :global(.is-next .pager-mark){transform:rotate(45deg)}
        /* .22, not .28 - the contract's one state tint. */
        .pager :global(.pager-num:hover),.pager :global(.pager-step:hover){background:rgba(209,244,112,.22)}
        .pager :global(.pager-num:focus-visible),.pager :global(.pager-step:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px}
        /* The current page: filled, and it is a <span>, so there is nothing to hover. */
        .pager :global(.pager-num.is-here){background:#d1f470;border:2px solid #1a3a2a;cursor:default}
        .pager :global(.pager-gap){color:rgba(0,0,0,.42);font-weight:400;min-width:24px;padding:0}
        .pager :global(.pager-step){border:2px solid rgba(26,58,42,.22)}
        /* The end of the run. Rendered rather than omitted so the row does not reflow as a
           reader pages through, and aria-hidden so it is not announced as a dead control. */
        /* LIGHTHOUSE FLAGS THIS AT 2.24:1 AND IT IS CORRECT TO LEAVE IT.
           rgba(0,0,0,.32) composites to rgb(173,173,173) over white. axe reports it as a
           colour-contrast failure because axe cannot always tell an inactive control from an
           active one. Two separate exemptions apply here:
           - WCAG 1.4.3 has no contrast requirement for text that is part of an INACTIVE user
             interface component, and this is the disabled end of the pager.
           - the markup renders these as span[aria-hidden="true"], so they are not exposed to
             assistive technology at all; the real state is carried by the absence of a link.
           Raising the contrast would make "unavailable" look available, which is the one thing
           this rule exists to prevent. Do not "fix" it off a Lighthouse report. */
        .pager :global(.pager-step.is-off){color:rgba(0,0,0,.32);border-color:#e5e7eb;cursor:default}
        /* "Page 7" to a screen reader, "7" on screen: a bare number read out of the list
           context is ambiguous. Same clip technique as .bs-label. */
        .pager :global(.pager-sr){position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}

        /* THESE THREE RULES MOVED HERE WITH THE MARKUP, and they had to. They used to sit in
           BlogIndexView's shared @media(max-width:767px) block beside .category-switch and
           .post-copy; once nav.pager and ol.pager-list carry this component's hash instead of
           that one, a rule written there matches nothing and the mobile pager silently loses its
           wrap-to-own-row layout and its full-width steps on BOTH listings.
           The numbers wrap to their own row under the prev/next pair rather than squeezing: 35
           pages cannot share a 390px line with two labelled steps. 767px is the home page's
           narrow step, which RotatingHero above also breaks at. */
        @media(max-width:767px){
          .pager{gap:8px}
          .pager-list{order:3;width:100%;justify-content:center}
          /* :global for the same reason as the block above - these are next/link. */
          .pager :global(.pager-step){flex:1}
        }
      `}</style>
    </nav>
  );
};

export default Pager;
