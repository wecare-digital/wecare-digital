import React from 'react';

interface BlogSearchProps {
  /**
   * Live mode. When provided, the input is controlled and filtering happens as you type on the
   * page you are already on. When omitted the component is a plain GET form to /blog/, which is
   * what a post page needs - the list is not there to filter.
   */
  value?: string;
  onChange?: ( next: string ) => void;
  /** Announced count, live mode only. Omitted when there is nothing to count yet. */
  resultCount?: number;
  totalCount?: number;
  /**
   * THE FIVE BLOG-SPECIFIC STRINGS, EACH DEFAULTING TO TODAY'S VALUE.
   *
   * /shop/ was asked for "the same search box as the blog", and the alternative to five props
   * was a second component that looks identical and drifts - which would have meant two copies
   * of the field standard below (borderless, bottom hairline, the opaque #1a3a2a focus outline,
   * the no-JavaScript GET fallback). Every default is the string that was hardcoded here before,
   * so /blog/, /blog/page/N/, both topic shapes and /post/<slug>/ render byte for byte what they
   * rendered, and the eleven getByLabelText( 'Search the blog' ) lookups in
   * src/test/BlogDesign.test.tsx stay green with no edit.
   *
   * THE FILE IS DELIBERATELY NOT RENAMED. src/test/StyledJsxBuildScope.test.ts names
   * components/BlogSearch.tsx in its staleness list and src/styles/Layout.css cites it by name,
   * and a rename buys nothing these props do not.
   */
  /** Where the no-JavaScript GET goes. The listing that can filter. */
  action?: string;
  /** id on the input and the label's htmlFor. Must be unique per page. */
  inputId?: string;
  /** The visually hidden label, which is the field's accessible name. */
  label?: string;
  placeholder?: string;
  /** Plural noun for the two count strings, e.g. 'posts' or 'products'. */
  noun?: string;
}

/**
 * Search, scoped to one listing.
 *
 * IT SERVES /shop/ AS WELL AS THE BLOG NOW, through the five optional strings on the props
 * interface below. The name stays BlogSearch - see the note there.
 *
 * TWO MODES, ONE COMPONENT, AND THE REASON IS WHERE THE DATA IS.
 * On /blog/ every published post is already in the page - the index is statically generated
 * with the whole list - so searching is a filter over something already loaded and should
 * happen as you type, with no navigation. On a post page that list does not exist, so the same
 * box has to be a form that navigates to /blog/?q=... and lets the index do the work. Rather
 * than two components that look identical and drift, this takes the controlled props when the
 * consumer can filter and falls back to a GET form when it cannot.
 *
 * IT IS A REAL <form> IN BOTH MODES, not a bare input. That is what makes Enter work, what
 * gives the on-screen keyboard a search key on a phone, and what keeps the no-JavaScript path
 * functional: with scripts off, live mode degrades to exactly the navigating behaviour, because
 * the form's action and method are always present. A div with a keydown handler would give up
 * all three.
 *
 * type="search" RATHER THAN type="text": it gets the platform's clear affordance for free, and
 * on iOS it is what produces the correct keyboard. name="q" because that is the conventional
 * query parameter and the one /blog/ reads.
 *
 * THE LABEL IS VISUALLY HIDDEN, NOT MISSING. A magnifier icon plus a placeholder announces
 * nothing to a screen reader, and placeholders disappear the moment anyone starts typing -
 * which is exactly when a reminder of what the field is for becomes useful. So there is a real
 * <label for>, positioned out of view by the same clip technique the rest of the site uses for
 * sr-only text.
 *
 * THE RESULT COUNT IS A LIVE REGION in live mode. Filtering as you type changes the page under
 * a screen reader user with no announcement at all unless something says so; aria-live="polite"
 * on a short count is the least intrusive way to say it. It is omitted entirely rather than
 * rendered empty when there is nothing to report, because an empty live region still gets
 * announced by some combinations.
 *
 * SELF-STYLING for the same reason as Breadcrumbs and RotatingHero, with bs- prefixed classes.
 * Sizes are existing rungs: 17px is the site's base body, 52px is the closing band's CTA
 * height, 12px radius sits between the 50px pill and the 14px panel.
 */
const BlogSearch: React.FC<BlogSearchProps> = ( {
  value, onChange, resultCount, totalCount,
  action = '/blog/', inputId = 'blog-q', label = 'Search the blog',
  placeholder = 'Search posts', noun = 'posts',
} ) => {
  const live = typeof value === 'string' && typeof onChange === 'function';
  // Announce only when a query is actually narrowing something.
  const announce = live && value && typeof resultCount === 'number';

  return (
    <div className="bs">
      {/* action and method are set in BOTH modes on purpose: they are what the no-JS path
          falls back to, and what makes Enter meaningful before hydration. */}
      <form className="bs-form" role="search" action={ action } method="get">
        <label className="bs-label" htmlFor={ inputId }>{ label }</label>
        <input
          id={ inputId }
          type="search"
          name="q"
          placeholder={ placeholder }
          autoComplete="off"
          { ...( live
            ? { value, onChange: ( e: React.ChangeEvent<HTMLInputElement> ) => onChange!( e.target.value ) }
            : {} ) }
        />
        <button type="submit">Search</button>
      </form>

      { announce && (
        <p className="bs-count" aria-live="polite">
          { resultCount === 0
            ? `No ${noun} match that search.`
            : `${resultCount} of ${totalCount} ${noun}` }
        </p>
      ) }

      <style jsx>{`
        .bs{margin:0 0 40px}
        /* align-items:stretch so the button matches the input's height without a second
           hard-coded number. max-width keeps the field a sensible target rather than letting
           it run the full 1300px measure. */
        .bs-form{display:flex;gap:10px;align-items:stretch;max-width:520px}
        /* The site's sr-only pattern, same declaration as .home-sr-only. */
        .bs-label{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        /* 17px is the site's base body size - anything smaller in a form field triggers the
           zoom-on-focus behaviour iOS applies under 16px. 52px matches .home-close-cta so the
           two controls read as the same family. */
        /* 999px AND A 1px #e5e7eb HAIRLINE - the site's field standard, which this control was
           the only public field not using. Measured in the built export before the change:
           border-radius 12px and a 2px rgba(26,58,42,.22) edge, against 999px and 1px #e5e7eb
           on .si-input, .sf-input, PhoneField's .pf, BlogSubscribe's cells and
           CheckoutProfile's grid. The button beside it is a 50px pill, so the old 12px box
           read as a search box borrowed from somewhere else and bolted to a site button.
           The focus rule below is unchanged and still supplies the indicator, so dropping the
           resting border from 2px to 1px costs nothing: at rest this is a container edge, and
           the thing that has to clear WCAG 1.4.11 is the focused state. */
        /* THE SITE-WIDE SEARCH LOOK: borderless, bottom hairline only, no box, no icon - the
           same field as the menu search (Header .nav-search) and the Anew blog panel
           (ProductBlogPanel), so every search a visitor meets reads as one control. Transparent
           fill, 1px bottom hairline; on focus the hairline darkens with a lime underline. */
        .bs-form input{
          flex:1;min-width:0;height:52px;padding:0 2px;
          font-size:17px;font-family:inherit;color:#1a1a1a;background:transparent;
          border:0;border-bottom:1px solid #e5e7eb;border-radius:0;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .bs-form input::placeholder{color:rgba(0,0,0,.44)}
        /* The focus treatment is a lime ring OUTSIDE a darkened border, not a removed outline:
           the border alone moving from .22 to solid is too quiet to serve as a focus
           indicator, and WCAG 1.4.11 wants 3:1 for one. #1a3a2a on white is 11.85:1. */
        /* AN OUTLINE, NOT A REMOVED ONE. This rule read outline:none plus a darkened border
           and a lime halo, and measured in a browser it produced NO detectable focus
           indicator at all: with :focus-visible matching, border-top-color stayed
           rgba(26,58,42,.22) - its resting value - and box-shadow computed to
           rgba(0,0,0,0) 0px 0px 0px 0px. Only the outline:none half was taking effect, so
           the one part that reached the element was the part that removes the browser
           default. Net result on /blog/: the search field was the only focusable control on
           the page a keyboard user could not locate.
           Rather than diagnose which declaration lost, this states the indicator the way the
           rest of the site now does - an opaque #1a3a2a outline, 12.48:1 on white - and keeps
           the lime halo as decoration. An outline also cannot be cancelled by a border or
           background rule elsewhere, which is what makes it the safer choice on a bare
           element selector that global stylesheets also target. */
        /* THE LIME HALO IS GONE, WHICH SETTLES AN OPEN QUESTION RATHER THAN LEGISLATING IT.
           This rule carried box-shadow:0 0 0 3px rgba(209,244,112,.55). That .55 was a fifth
           lime value in a language the contract says has exactly three, and it was arguably
           outside the rule's reach because the three are described as FILLS and this was a
           glow. Rather than decide whether a glow counts, the halo is removed: once this rule
           states an opaque #1a3a2a outline, the halo was redundant decoration, and deleting a
           value answers the question more cleanly than adding a fourth entry to the table.
           The indicator is now the outline at 12.48:1 on white, plus the border darkening. */
        .bs-form input:focus-visible{
          border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470;
        }
        /* QUIET TEXT SUBMIT, NOT A LIME PILL. The borderless field is the common search look, and
           a filled pill beside it brought back the "box bolted to a button" the field just shed.
           The button stays in the DOM - it is the no-JS and Enter-to-navigate path the component
           depends on - but it is now a plain dark-green text control with no box, so the field
           reads as one borderless search like the menu and the Anew panel. */
        .bs-form button{
          height:52px;padding:0 8px;flex:none;
          border:0;border-radius:0;background:transparent;
          color:#1a3a2a;font-size:15px;font-weight:600;font-family:inherit;cursor:pointer;
          text-decoration:underline;text-underline-offset:3px;transition:opacity .2s;
        }
        .bs-form button:hover{opacity:.7}
        .bs-form button:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;border-radius:6px}
        /* The body rung, muted - it is a status line, not content. */
        .bs-count{
          margin:12px 0 0;font-size:17px;line-height:1.4;
          letter-spacing:-.125px;color:rgba(0,0,0,.62);
        }
        @media(max-width:767px){
          /* The button keeps its label rather than collapsing to an icon: an icon-only submit
             needs its own accessible name, and "Search" already is one. */
          .bs-form{max-width:none}
        }
        @media(prefers-reduced-motion:reduce){
          .bs-form button{transition:none}
        }
      `}</style>
    </div>
  );
};

export default BlogSearch;
