import React from 'react';

/**
 * "CONTRIBUTE" - the voluntary-contribution block that sits on every blog post, after the Tags
 * row and the WhatsApp Subscribe button and before the Share controls (see
 * src/pages/post/[slug].tsx for the exact DOM position and why the share reveal sentinel stays
 * where it is).
 *
 * WHAT THIS COMPONENT IS NOW: ONE LINK, AND NOTHING ELSE.
 * ------------------------------------------------------
 * Owner instruction, 2026-10-10: remove BOTH button-looking things from this block - the ₹250
 * amount pill AND the "Contribute ₹250" submit - and hand the reader to WhatsApp the way the rest
 * of the site does. So this is a plain anchor at the owner's Contribute message link. There is no
 * form, no field, no radio group, no cart write and no navigation to /cart/: a contribution is now
 * a CONVERSATION, started by the reader in WhatsApp.
 *
 * WHY A WHATSAPP LINK RATHER THAN A CART LINE. Every other "ask us for something" surface on this
 * site is already a wa.me message link - /subscribe/ (src/content/subscribe.ts), /shipments/
 * (src/content/shipments.ts), Leave Review, and the Subscribe button directly above this block on
 * this very page. A contribution form was the one place that still asked the reader to transact on
 * the page, which is why it read as a different product.
 *
 * IT IS THE SUBSCRIBE BUTTON'S TWIN, DELIBERATELY. Owner instruction: the two CTAs at the tail of
 * a post are a matched pair - the same lime pill, a one-word label, and the same quiet microcopy
 * underneath. The twin is `.blog-wa-subscribe` in src/pages/post/[slug].tsx and the pill geometry
 * is the same.
 *
 * TEXT-ONLY BUTTON WITH MICROCOPY, and the design history matters because it moved twice. The
 * brief first asked for a small subtext line; the owner tried a WhatsApp glyph on the button
 * instead; on seeing it the owner found the logo inside the filled lime pill too busy and asked
 * to drop it. The settled design is a TEXT-ONLY pill reading "Contribute", with the destination
 * named in a very short `.bc-cta-note` microcopy line below it - "Continue on WhatsApp →". The
 * arrow is part of the text (it says "leaves here"), not a reintroduced icon. The chain is
 * recorded at .agents/tasks/contribute-whatsapp-cta/owner-decision.md. Subscribe, 44px above,
 * carries the identical text-only-plus-microcopy treatment, which is the pair this matches.
 *
 * WHAT WAS DELETED, so the absence is not read as a gap:
 *   - `CONTRIBUTION_CHOICES` and the ₹250 amount pill, with its visually-hidden radio, its
 *     `data-ui-raw` opt-out from the shared control skin and its five `.bc-radio` CSS rules.
 *   - `setContribution` and the `window.location.assign( '/cart/' )` navigation.
 *   - `PillButton`, the submit button and the `variantId` state.
 *   - The `CONTRIBUTION_CONFIGURED` honest-degradation branch. It existed because a button that
 *     cannot work is worse than no button, and it was gated on a contribution product and variant
 *     ids being declared at build time. A static wa.me link depends on no configuration, so there
 *     is no longer a state in which this block cannot work, and the branch would be dead code
 *     dressed as a safeguard.
 * `src/config/contribution.ts` is deliberately untouched: the cart, the server and their tests
 * still own the fixed-price `Contribute` product line, and nothing about this block's change
 * retires that path.
 *
 * TWO DISTINCT MESSAGE LINKS ON ONE PAGE, AND THEY MUST NOT BE MERGED. Subscribe opens
 * wa.me/message/WUDPTMYSO6XII1 (the post page owns that anchor); Contribute opens
 * wa.me/message/BYFLCAAMSZBXD1, below. They are different conversations with different Meta
 * message links - src/test/BlogDesign.test.tsx asserts both, and that they differ. Pointing one
 * button at the other's link would look entirely correct on screen, which is the reason that
 * assertion exists.
 *
 * THE ACCESSIBLE NAME CARRIES THE VISIBLE WORD. `aria-label="Contribute on WhatsApp"` CONTAINS
 * the visible "Contribute", so a speech-input user saying "click Contribute" reaches it - WCAG
 * 2.5.3 Label in Name, the same contract the Subscribe anchor keeps with "Subscribe on WhatsApp".
 * The microcopy line below is `aria-hidden`: the anchor's accessible name already carries
 * "on WhatsApp", so announcing the destination again would be a duplicate.
 */

/** The owner's Contribute Meta message link. The ONE place this URL is written. */
export const CONTRIBUTE_CTA_HREF = 'https://wa.me/message/BYFLCAAMSZBXD1';

export interface BlogContributionProps {
  /** The blog post's authoritative id (PublicBlogPost.id), kept so the block is attributable. */
  postId: string;
  /**
   * The post slug, carried alongside the id for human-readable attribution.
   *
   * NOT RENDERED ANY MORE, and kept so the call sites keep compiling and the props stay a stable
   * shape. It used to scope the radio group's `name` to the post so two blocks on one page could
   * not share state; with no form there is no state to share.
   */
  slug: string;
  /** Removes the component's own top rule when a parent surface already owns section rhythm. */
  embedded?: boolean;
}

const BlogContribution: React.FC<BlogContributionProps> = ( { postId, embedded = false } ) => (
  <section className={ embedded ? 'bc is-embedded' : 'bc' } aria-labelledby="bc-title" data-post-id={ postId }>
    {/* h2, never h1: the post page already owns the single h1, and htmlcheck guards H1-MANY. */}
    <h2 className="bc-title" id="bc-title">Contribute</h2>
    <p className="bc-copy">
      If you found this useful, you’re welcome to make a small voluntary contribution.
    </p>

    {/* A REAL ANCHOR, not a button with an onClick: it leaves the site, so it has to be
        middle-clickable, long-pressable and copyable - the same argument the Subscribe button
        above it records. TEXT ONLY, no glyph: the owner found the WhatsApp logo inside the filled
        pill too busy, so the destination moves to the quiet `.bc-cta-note` microcopy below rather
        than onto the button. Subscribe, 44px above, is the matched pair and carries the same
        treatment. */}
    <a
      className="bc-cta"
      href={ CONTRIBUTE_CTA_HREF }
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Contribute on WhatsApp"
    >
      <span>Contribute</span>
    </a>
    {/* MICROCOPY, not a sentence: it names where the button goes in three words and a trailing
        arrow that says "leaves here". The accessible name on the anchor already carries
        "on WhatsApp", so this line is aria-hidden to avoid a screen reader announcing the
        destination twice. */}
    <p className="bc-cta-note" aria-hidden="true">Continue on WhatsApp →</p>

    <style jsx>{`
      /* bc- prefixed because the globally imported src/styles/*.css declares unscoped rules for
         generic names and styled-jsx does not shield a block from them. The treatment reuses the
         blog post page's own rhythm (the hairline band, the e5e7eb rules) and the site's lime
         CTA language. */
      .bc{
        margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb;
        font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      }
      .bc.is-embedded{margin-top:0;padding-top:0;border-top:0}
      /* h2 at the related-section eyebrow rung, NOT the 40px/700 section rung, because this is a
         quiet appeal at the tail of the reading rather than a claim - same treatment the
         "More in ..." related heading and the breadcrumb furniture use. */
      .bc-title{
        font-size:12px;font-weight:700;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;
        color:rgba(0,0,0,.54);margin:0 0 12px;
      }
      .bc-copy{
        font-size:18px;line-height:1.5;letter-spacing:-.125px;font-weight:400;
        color:rgba(0,0,0,.898);margin:0 0 20px;max-width:60ch;
      }
      /* THE SUBSCRIBE BUTTON'S OBJECT - see .blog-wa-subscribe in src/pages/post/[slug].tsx,
         which is the pair this has to match. THE VALUES ACTUALLY SHARED, each one declared
         identically in both rules: min-height:52px, padding:0 28px, border:2px solid #1a3a2a,
         border-radius:50px, background:#d1f470, color:#1a3a2a, font-size:17px, font-weight:600,
         gap:10px, and the white hover inversion with its lift and shadow.
         WHY EACH NUMBER. The edge is what clears WCAG 1.4.11 for a control boundary (#1a3a2a on
         white is 12.48:1; the lime alone is 1.24:1 and cannot be the thing that separates the
         button from the page). #1a3a2a type on #d1f470 is 10.04:1. The radius is 50px rather
         than the 999px this rule used to carry, so it is the SAME DECLARATION as the sibling
         rather than a different number that happens to round the same way at 52px - and either
         value overrides the global 13px in src/styles/button.css, which is the flattening the
         explicit declaration exists to prevent.
         WHAT IS DELIBERATELY NOT SHARED: margin-top. Subscribe sets 44px because it opens a
         band. This rule sets NO margin-top at all - the 20px of air above the pill comes from
         .bc-copy's own margin:0 0 20px above, because the pill follows its copy line inside a
         band this section has already opened. Said explicitly because an earlier version of
         this comment credited a margin-top:20px that was never declared here. */
      .bc-cta{
        display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;
        min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
        background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
        text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
      }
      /* The house inversion - lime to white - plus the one allowed lift and shadow. White gives
         #1a3a2a type 12.48:1; deepening to the base green would be 3.91:1 and fail at this size. */
      .bc-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
      .bc-cta:active{transform:translateY(0)}
      /* Opaque focus ring at offset, the page's standard - never a translucent alpha. 3px offset
         rather than 2px, because this is now the pill object and the pill rings outside itself. */
      .bc-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
      /* MICROCOPY under the pill: very small, quiet, naming the destination the button no longer
         shows with a glyph. 13px/rgba(0,0,0,.54) is the page's muted-metadata rung; 10px of air
         sits it close to the button it belongs to. The arrow is part of the text, not an icon.

         HOVER CARRIES THE FOOTER TAGLINE'S COLOUR SWEEP, on owner instruction: a band of brand
         green runs left-to-right through the muted text, exactly the .ft-tagline treatment in
         Footer.tsx (gradient grey -> #1a3a2a -> grey, clipped to the text, driven by
         background-position). The one difference is the TRIGGER: the footer plays it once on
         scroll-arrival and replays on pointer; here it is hover-only, because this line is the
         caption of a pill the reader is already pointing at.
         WHY THE CLIP LIVES UNDER :hover AND NOT AT REST. background-clip:text needs
         color:transparent to show the gradient, and transparent text with no painted gradient is
         an invisible line - the exact trap Footer.tsx documents. So the resting rule keeps a
         solid colour and only :hover introduces the gradient, the clip and the transparent fill.
         Hover-out drops them and the line is plain grey again, with no JS anywhere.
         READABILITY: both gradient stops are measured on white - rgba(0,0,0,.54)=4.61:1 and
         #1a3a2a=12.48:1 - so the band only ever makes the text darker than its resting state,
         never a lime wash that would erase it. */
      .bc-cta-note{
        font-size:13px;line-height:1.4;color:rgba(0,0,0,.54);margin:10px 0 0;
      }
      /* The sweep: the gradient's dark band travels across, once per hover. The gradient itself,
         the clip and the transparent fill ALL live here, not at rest. Declaring the gradient at
         rest without background-clip:text paints the whole paragraph box grey - the full-width
         bar bug - so the resting line is plain muted text and the band only exists on hover.
         background-position is the only animated property, so it composites off the main thread. */
      .bc-cta-note:hover{
        background-image:linear-gradient(100deg,
          rgba(0,0,0,.54) 42%, #1a3a2a 50%, rgba(0,0,0,.54) 58%);
        background-size:300% 100%;background-position:100% 0;background-repeat:no-repeat;
        -webkit-background-clip:text;background-clip:text;
        -webkit-text-fill-color:transparent;color:transparent;
        animation:bc-note-sweep 1.15s cubic-bezier(.45,.05,.55,.95) 1 forwards;
      }
      @keyframes bc-note-sweep{from{background-position:100% 0}to{background-position:0% 0}}
      @media(prefers-reduced-motion:reduce){
        .bc-cta{transition:none}
        .bc-cta:hover{transform:none;box-shadow:none}
        /* Neutralise the sweep: hand the text back its solid colour and kill the animation, or a
           reduced-motion reader gets transparent text over a parked gradient - an invisible line.
           Matches the guard Footer.tsx applies to .ft-tagline under this preference. */
        .bc-cta-note:hover{
          animation:none;background-image:none;
          -webkit-text-fill-color:currentColor;color:rgba(0,0,0,.54);
        }
      }
    `}</style>
  </section>
);

export default BlogContribution;
