import React from 'react';
import Link from 'next/link';

export interface Crumb {
  label: string;
  /** Omit on the last item: the current page is not a link to itself. */
  href?: string;
}

/**
 * A breadcrumb trail, on the site's own rungs.
 *
 * WHAT IT REPLACES. Post pages offered a single Link reading "Blog" with a CSS-generated
 * arrow, at 13px/650 in #1a3a2a. That is a back button, not a breadcrumb: it names one
 * ancestor, gives no sense of depth, and was the only control on the page at 13px when the
 * site's smallest UI rung is 12px/700 uppercase (.home-close-eyebrow) and its base body is
 * 17px. Meanwhile both blog templates already emit a JSON-LD BreadcrumbList - so the
 * structured data described a trail the page never rendered, which is the kind of mismatch
 * that makes a rich result disappear without explanation.
 *
 * MARKUP IS nav > ol > li, which is what assistive technology expects for an ordered path and
 * what the BreadcrumbList claims exists. The separator is a ::before on li + li, so it is
 * drawn rather than typed: a literal chevron or slash in the markup is announced by a screen
 * reader on every item ("Home slash Blog slash..."), and a CSS pseudo-element is not in the
 * accessibility tree at all.
 *
 * aria-current="page" MARKS THE LAST ITEM, which is how a screen reader user knows the trail
 * has ended without relying on it being visually dimmed. It is also not a link - linking a
 * page to itself is a documented WCAG annoyance rather than a help.
 *
 * TYPE IS 15px/600 SENTENCE CASE WITH A LIME UNDERLINE (owner "Option B", 2026-10-13). It used
 * to sit on the 12px/700 uppercase .home-close-eyebrow rung, but the owner wanted the trail to
 * read like the site's own navigation rather than a tiny label, and to carry the home-page lime
 * accent that the CTAs and the Contribute links use. The links show the lime underline at rest
 * (darkening to #1a3a2a on hover); the current-page crumb stays dimmed and unlinked.
 *
 * THE CURRENT PAGE TRUNCATES AT 46ch rather than wrapping. Blog titles here run to 70-plus
 * characters ("A page view is not a person" is short for this corpus), and a trail that wraps
 * to three lines stops reading as a trail. The full title is the h1 immediately below, so
 * nothing is lost by clipping it here.
 *
 * SELF-STYLING, like BrandBadge and RotatingHero: styled-jsx cannot scope a composite
 * component from its parent, so this owns every rule it needs and the consumer owns placement.
 * Classes are bc- prefixed because the globally imported src/styles/*.css declares unscoped
 * rules for generic names.
 */
const Breadcrumbs: React.FC<{ items: Crumb[] }> = ( { items } ) => (
  <nav className="bc" aria-label="Breadcrumb">
    <ol>
      { items.map( ( item, i ) => (
        <li key={ `${item.label}-${i}` }>
          { item.href
            ? <Link href={ item.href }>{ item.label }</Link>
            // The last crumb: plain text, marked as the current page.
            : <span aria-current="page">{ item.label }</span> }
        </li>
      ) ) }
    </ol>

    <style jsx>{`
      .bc{margin:0 0 22px}
      .bc ol{display:flex;flex-wrap:wrap;align-items:center;gap:0;margin:0;padding:0;list-style:none}
      /* 15px/600 SENTENCE CASE, NOT the 12px/700 uppercase eyebrow. Owner instruction
         (2026-10-13, "Option B"): the trail should read like the site's own navigation rather
         than a tiny label, so it moves off the .home-close-eyebrow rung onto a quiet nav rung -
         15px, 600, mixed case (the labels are already passed as "Home"/"Shop"/"Blog"), with the
         lime underline the home-page CTAs and the Contribute links use. */
      /* min-width:0 IS THE FIX FOR A MEASURED OVERFLOW, not tidying. A flex item defaults to
         min-width:auto, which refuses to shrink below its content - so the ellipsis on the
         current-page crumb below could never engage once the crumb was wider than the room left
         for it, and the page scrolled sideways instead. See the note on that rule. */
      .bc li{
        display:flex;align-items:center;min-width:0;
        font-size:15px;font-weight:600;letter-spacing:-.01em;
        line-height:1.4;color:#1a3a2a;
      }
      /* DRAWN, NOT TYPED. A chevron character in the markup is read aloud on every item; a
         rotated border box is not in the accessibility tree. Same technique as the tick in
         the home page's closing band. */
      .bc li + li::before{
        content:'';display:inline-block;width:6px;height:6px;margin:0 11px;
        border-top:2px solid rgba(26,58,42,.38);
        border-right:2px solid rgba(26,58,42,.38);
        transform:rotate(45deg);
      }
      /* LIME UNDERLINE AT REST (Option B) - the home-page CTA / Contribute-link accent, so the
         trail reads as a house link. The text stays #1a3a2a (12.48:1 on white, readable); the
         underline is the brand lime #d1f470 and darkens to #1a3a2a on hover. text-underline-offset
         lifts the rule off the descenders so it reads as an accent, not a strike. */
      .bc a{
        color:#1a3a2a;text-decoration:underline;text-decoration-color:#d1f470;
        text-decoration-thickness:2px;text-underline-offset:3px;transition:text-decoration-color .2s;
      }
      .bc a:hover{text-decoration-color:#1a3a2a}
      .bc a:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
      /* The current page, dimmed so the trail reads as a path with an end, and clipped
         because this corpus has long titles.
         THE CAP IS THE CONTAINER, NOT A CHARACTER COUNT, and that is a measured correction.
         This was max-width:46ch with a max-width:34ch override under 767px, and the override's
         own comment recorded the problem it could not solve: "46 would still overflow a 358px
         measure at this size". 34 was the next guess and it overflows too, just later. Measured
         on /post/<slug>/ at 280px - the folded Galaxy Fold posture - the trail ran to 318px in a
         280px viewport: 38px of sideways scroll on every post page with a long title.
         A ch cap cannot work here, because the room available to the last crumb is whatever the
         crumbs before it did not use, and no character count knows that number. So the crumb is
         allowed to shrink instead (min-width:0 here and on the li above) and the ellipsis does
         the work it was always there to do, at every width, against the space actually left.
         46ch stays as the upper bound so a long title does not run the full measure on a wide
         screen - it is now a preference rather than the only constraint.
         Caught by rtlcheck at the fold postures; devicecheck missed it because its route list
         had no /post/ entry, which is fixed alongside this. */
      /* .72, not .58. The current crumb is quieter than the links before it on purpose - it is
         where you already are, so it should not invite a click - but .58 composites to
         rgb(122,141,131) over white and measures 3.53:1, and at 12px that is normal text needing
         4.5:1. .72 measures 5.26:1 and is still visibly quieter than the .bc a links beside it,
         so the hierarchy survives the fix.
         Deliberately not the full #1a3a2a: that would make the crumb you are on look exactly
         like the ones you can follow, which is the distinction this rule exists to draw.
         Found by Lighthouse's axe pass rather than by the focus-ring sweep, which measured
         indicators and named label colours and never walked ordinary text. */
      .bc [aria-current]{
        color:rgba(26,58,42,.72);
        min-width:0;max-width:46ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
      }
      @media(prefers-reduced-motion:reduce){
        .bc a{transition:none}
      }
    `}</style>
  </nav>
);

export default Breadcrumbs;
