import React from 'react';
import Link from 'next/link';

/**
 * THE SHARED TAG ROW. One component now renders a post's tags everywhere they appear - the post
 * page's end-of-article row and the /anew/ panel's card foot - so the pill language, the hue
 * hash and the search destination live in ONE place rather than being re-typed per surface.
 *
 * It was born on src/pages/post/[slug].tsx, where the tag markup, the tagHue hash and the
 * .tags/.tag-h0..3 CSS all lived inline. ProductBlogPanel rendered its own plain-span chips with
 * a different look, so a tag read as two different objects on two surfaces. Lifting the whole
 * thing - markup, hash and CSS, byte for byte - into this component is what makes a tag look the
 * same wherever it is shown and keeps the BlogDesign.test.tsx assertions meaningful: they render
 * <BlogPostPage>, which renders this, so this component's style block is present in that tree.
 *
 * WHICH ACCENT A TAG GETS, DERIVED FROM THE TAG ITSELF RATHER THAN FROM ITS POSITION.
 *
 * The blog already cycles the contract's accent hues by position: .post-card steps
 * #3da35a, #2563eb, #9849e8 with nth-child(3n+...). That is right for a card in a stream,
 * where position is the only thing available and nobody expects card three to look like
 * card three on another page.
 *
 * It is wrong for a tag. The same tag appears across many posts, and position-based cycling
 * would colour "Chai" green on one post and blue on the next - which spends the colour
 * without buying the recognition it is for. Hashing the tag name makes a tag look the same
 * everywhere it appears, so the colour becomes a property of the tag rather than of the row.
 *
 * Deterministic and pure, so the server and the client compute the same value and hydration
 * does not mismatch - that is the reason this is a hash rather than a random pick or a
 * useState.
 *
 * FOUR HUES, NOT FIVE. Amber #f0a818 is the one the hero pills use that is excluded here: it
 * measures 2.04:1 on white, which is the ratio the design contract records as the reason it
 * was rejected for light surfaces. The other four all clear the 3:1 that WCAG 1.4.11 asks of
 * a graphic used to identify a control - green 3.19:1, blue 5.17:1, purple 4.72:1, red
 * 4.83:1 - so this palette is measured rather than picked.
 *
 * THE UNSIGNED SHIFT IS LOAD-BEARING, and this is the bug the first version shipped.
 * It used & 0xffffffff, which in JavaScript yields a SIGNED 32-bit integer - and a negative
 * remainder stays negative, because -5 % 4 is -1 in JS rather than 3. So tags hashing to a
 * negative value produced class names like tag-h-1 and tag-h-2, which match no rule, and
 * those pills silently fell back to the neutral grey border. The >>> 0 keeps it unsigned.
 */
const TAG_HUE_COUNT = 4;
export const tagHue = ( tag: string ): number => {
  let h = 0;
  for ( let i = 0; i < tag.length; i += 1 ) h = ( h * 33 + tag.charCodeAt( i ) ) >>> 0;
  return h % TAG_HUE_COUNT;
};

export interface BlogTagsProps {
  /** The post's tags. An empty array renders nothing. */
  tags: string[];
  /**
   * An EXTRA class on the <nav>, for a consumer that needs to override the container's layout -
   * the /anew/ panel passes "pbp-tagrow" to drop the 52px top margin and the hairline that suit
   * the end of an article but not the foot of a card. The styling hook `tags` is ALWAYS present
   * underneath it, so the pill appearance and the hue dots style every surface identically; this
   * class only adds to it.
   */
  className?: string;
  /** The landmark's accessible name. Defaults to a plain 'Tags'. */
  ariaLabel?: string;
}

/**
 * TAGS ARE LINKS, AND THEY GO WHERE TAGS ARE ALREADY USED.
 * They were plain spans, so giving them a hover would have been an affordance for nothing.
 * There is no /blog/tag/<x>/ route and inventing one is not the answer, because the
 * destination already exists: scripts/generate-blog-search-index.js records that `tags` is
 * requested FOR SEARCH rather than for display. So a tag linking to a search FOR ITSELF is the
 * one destination that matches what the field is for. /blog/?q= is a real target that also
 * works with JavaScript off, which is why this is a plain navigation rather than a click handler.
 *
 * next/link with :global() in the CSS below, matching .category-switch and .post-related-card -
 * styled-jsx does not scope a composite component, so a className passed to Link would arrive
 * unstyled.
 */
const BlogTags: React.FC<BlogTagsProps> = ( { tags, className, ariaLabel = 'Tags' } ) => {
  const clean = ( tags || [] ).map( t => t.trim() ).filter( Boolean );
  if ( clean.length === 0 ) return null;

  // `tags` is the styling hook and is always present; any passed class is added once, deduped so
  // a consumer that passes "tags" itself (the post page) does not render class="tags tags".
  const navClass = [ 'tags', ...( className ? className.split( /\s+/ ) : [] ) ]
    .filter( ( c, i, all ) => c && all.indexOf( c ) === i )
    .join( ' ' );

  return (
    <nav className={ navClass } aria-label={ ariaLabel }>
      { clean.map( tag => (
        <Link
          key={ tag }
          href={ `/blog/?q=${encodeURIComponent( tag )}` }
          className={ `tag-h${tagHue( tag )}` }
          aria-label={ `Search posts tagged ${tag}` }
        >{ tag }</Link>
      ) ) }

      <style jsx>{`
        /* ONE LINE THAT SCROLLS, NOT A BLOCK THAT WRAPS.
           This was flex-wrap:wrap, so on a phone a post with six tags grew the row to three
           lines and pushed the footer down; on a landscape phone it wrapped for no reason at
           all, because the width was there and the row simply refused to use it. nowrap plus
           overflow-x:auto keeps it to a single line at every width and lets the row scroll
           instead - which is exactly what .category-switch on /blog/ already does, so this is
           the site's existing answer to the same problem rather than a new one.

           DIRECTION IS NOT HARD-CODED. overflow-x on a flex row follows the document's dir
           so under the RTL languages SupportWidget switches to, the row starts at the right and
           scrolls leftward with no separate rule. That is why there is no direction or
           margin-left declaration here - a logical layout gets RTL for free, and rtlcheck asserts it.

           padding-bottom:6px is for the FOCUS RING, not for looks. A scroll container clips its
           children, and these pills carry a 3px outline at 2px offset; without the room the ring
           on a focused tag is sliced off at the container's edge. .category-switch carries the
           same 6px for the same reason. -2px top padding does the same for the hover lift.

           scrollbar-width:thin rather than hidden: a row that scrolls should say so. Hiding the
           bar leaves a mouse-only user with no indication there is more to the right. */
        .tags{
          display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;
          margin-top:52px;padding:26px 0 6px;border-top:1px solid #e5e7eb;
          scrollbar-width:thin;align-items:center;
        }
        /* 2px, not 1px - and that change is the whole point of making these links.
           The hairline rule is weight-as-meaning: 2px means hoverable, 1px means static. These
           were spans at 1px, correctly, because nothing happened when you moused over them. Now
           that each one navigates to a search for itself, it is a hoverable control and takes
           the 2px edge that .pill, .pp-pill and .category-switch all carry.
           :global() because these are next/link, and styled-jsx does not scope a composite
           component - the same reason .category-switch and .post-related-card use it. */
        .tags :global(a){
          flex:0 0 auto;display:inline-flex;align-items:center;gap:7px;
          font-size:14px;font-weight:400;letter-spacing:-.125px;
          background:#fff;border:2px solid #e5e7eb;border-radius:999px;
          padding:6px 13px;color:rgba(0,0,0,.54);text-decoration:none;white-space:nowrap;
          transition:background-color .2s,border-color .2s,color .2s,transform .2s,box-shadow .2s;
        }
        /* THE DOT IS THE HOME HERO PILL'S OTHER HALF.
           Those pills are a pale tint with a saturated dot of the same hue. The dot travels
           here; the tint does not, and that is a contrast decision rather than a stylistic
           one. The label is rgba(0,0,0,.54), which measures 4.61:1 on white and clears the
           4.5:1 AA minimum for normal text with almost nothing to spare - over a pale tint it
           drops under. So the ground stays white and the hue arrives as a dot and a border instead.
           A pseudo-element, so it is decorative by construction and never reaches the
           accessibility tree - the same reason the hero dot carries aria-hidden. */
        .tags :global(a)::before{
          content:'';flex:0 0 auto;width:7px;height:7px;border-radius:50%;
          background:#e5e7eb;transition:background-color .2s;
        }
        /* THE HUE IS IN THE DOT ONLY. THE BORDER STAYS THE NEUTRAL HAIRLINE.
           An earlier pass put the accent on the border as well, and it was too loud: a 2px
           saturated edge runs the whole perimeter, so three or four tags in different hues
           sitting side by side competed with the post they belong to instead of labelling it.
           The dot is 7px and carries the same information for a fraction of the ink.
           Every other pill in this design language rests on 2px #e5e7eb - .pill, .pp-pill and
           .category-switch all do - so a coloured resting edge made the tags the only pill on
           the site with one. Neutral border, coloured dot: quieter AND more consistent. */
        .tags :global(.tag-h0)::before{background:#3da35a}
        .tags :global(.tag-h1)::before{background:#2563eb}
        .tags :global(.tag-h2)::before{background:#9849e8}
        .tags :global(.tag-h3)::before{background:#dc2626}
        /* THE HOME PAGE'S HOVER, EXACTLY. Lime border, the .22 state tint, a 2px lift and the one
           shadow this design language uses - the same four properties .category-switch and the
           home closing CTA move, at the same .2s. The label also goes from the muted
           rgba(0,0,0,.54) to solid #1a3a2a, because a control being pointed at should read as
           active rather than as quiet metadata: 12.48:1 on the tint.
           Anchored on :hover AND :focus-visible so a keyboard user gets the same feedback a
           mouse user does. */
        .tags :global(a:hover),.tags :global(a:focus-visible){
          border-color:#d1f470;background:rgba(209,244,112,.22);color:#1a3a2a;
          transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .tags :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px}
        @media(prefers-reduced-motion:reduce){
          /* The tag pills lose the lift, not the feedback. transform is the part a reader who
             asked for less motion should not get; the lime border, the tint and the darkened
             label all stay, so the control still answers when it is pointed at. */
          .tags :global(a),.tags :global(a)::before{transition:none}
          .tags :global(a:hover),.tags :global(a:focus-visible){transform:none;box-shadow:none}
        }
      `}</style>
    </nav>
  );
};

export default BlogTags;
