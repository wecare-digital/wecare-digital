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
 * a post are a matched pair - the same lime pill, the same WhatsApp glyph, a one-word label. So
 * the icon markup below is the SAME path data as `.blog-wa-subscribe` in src/pages/post/[slug].tsx
 * and the pill geometry is the same.
 *
 * NO SUBTEXT UNDER THE BUTTON, and that is a RECORDED DECISION rather than an omission. The task
 * brief originally asked for a small muted line below the pill; the owner then revised the design
 * to an icon instead, and on confirming that the WhatsApp glyph already makes the destination
 * obvious, settled it as "no need for subtext". The decision and its chain are written down at
 * .agents/tasks/contribute-whatsapp-cta/owner-decision.md so the deviation from the brief is
 * traceable to the owner and not to this file's author. The glyph is what says "this opens
 * WhatsApp"; a line saying so would repeat what the reader can already see. Subscribe, 44px
 * above, carries no subtext either, which is the pair this matches.
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
 * 2.5.3 Label in Name, the same contract the Subscribe anchor keeps with "Subscribe on WhatsApp"
 * and the failure PillButton's docblock records at length. The glyph is `aria-hidden` because the
 * label already says what it depicts.
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
        above it records. The SVG is that button's glyph, path for path, so the pair cannot drift
        into two icons. */}
    <a
      className="bc-cta"
      href={ CONTRIBUTE_CTA_HREF }
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Contribute on WhatsApp"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" width="20" height="20">
        <path fill="currentColor" d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.03 1.02-1.03 2.48 0 1.46 1.06 2.87 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2-1.41.25-.7.25-1.29.18-1.42-.08-.12-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 01-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 01-1.51-5.26C2.16 6.45 6.6 2.01 12.05 2.01c2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 012.89 6.99c0 5.45-4.44 9.89-9.88 9.89M20.46 3.49A11.82 11.82 0 0012.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 005.69 1.45c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.17-3.48-8.42z" />
      </svg>
      <span>Contribute</span>
    </a>

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
        display:inline-flex;align-items:center;gap:10px;box-sizing:border-box;
        min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
        background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
        text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
      }
      .bc-cta svg{flex:0 0 auto}
      /* The house inversion - lime to white - plus the one allowed lift and shadow. White gives
         #1a3a2a type 12.48:1; deepening to the base green would be 3.91:1 and fail at this size. */
      .bc-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
      .bc-cta:active{transform:translateY(0)}
      /* Opaque focus ring at offset, the page's standard - never a translucent alpha. 3px offset
         rather than 2px, because this is now the pill object and the pill rings outside itself. */
      .bc-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
      @media(prefers-reduced-motion:reduce){
        .bc-cta{transition:none}
        .bc-cta:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </section>
);

export default BlogContribution;
