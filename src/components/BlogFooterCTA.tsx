import React from 'react';
import BlogContribution from './BlogContribution';
import ShareLinks from './ShareLinks';

/**
 * THE SUBSCRIBE / CONTRIBUTE / SHARE BLOCK AT THE TAIL OF A BLOG SURFACE.
 *
 * This is the three-part CTA band that already sits at the foot of every post page - a WhatsApp
 * Subscribe pill, the Contribute block, and the Share row - lifted into one component so the
 * blog INDEX (/blog/ and /blog/page/N/, via BlogIndexView) can carry the same band the owner
 * asked for, without the markup being re-typed on a second surface and drifting from the post
 * page it was copied from.
 *
 * WHAT IS SHARED vs OWNED HERE.
 *   - Contribute is <BlogContribution> and Share is <ShareLinks> - both already reusable
 *     components, rendered verbatim, so their behaviour and the two distinct WhatsApp message
 *     links cannot diverge between surfaces.
 *   - The Subscribe pill is a plain anchor whose markup and CSS the post page kept inline. The
 *     SAME object is declared here (byte for byte: 52px lime pill, 2px #1a3a2a edge, the white
 *     hover inversion, the opaque focus ring) so the pair stays a pair. The post page keeps its
 *     own copy because its band is wrapped in an IntersectionObserver reveal (article.is-armed)
 *     that this component deliberately does not carry - the index has no such sentinel.
 *
 * NO REVEAL ANIMATION. On the post page the Share row is the reveal sentinel; here the band is
 * static. That is the one intentional difference from the post-page block, and it is why this is
 * a sibling component rather than the post page importing it too (yet).
 *
 * TWO DISTINCT MESSAGE LINKS, UNCHANGED. Subscribe opens wa.me/message/WUDPTMYSO6XII1; Contribute
 * opens its own link inside BlogContribution. They are different conversations and must not be
 * merged - the post-page tests already pin that both exist and differ.
 */

export interface BlogFooterCTAProps {
  /** Absolute canonical URL to share. On the index this is the blog page's own URL. */
  shareUrl: string;
  /** Plain-text share title - the first line of a WhatsApp message / the share-sheet title. */
  shareTitle: string;
  /** Attribution id for the Contribute block. The index has no single post, so a surface id. */
  contributionId?: string;
}

/** The owner's Subscribe Meta message link - the same anchor the post page carries. */
const SUBSCRIBE_HREF = 'https://wa.me/message/WUDPTMYSO6XII1';

const BlogFooterCTA: React.FC<BlogFooterCTAProps> = ( { shareUrl, shareTitle, contributionId = 'blog-index' } ) => (
  <aside className="blog-cta" aria-label="Subscribe, contribute and share">
    {/* SUBSCRIBE ON WHATSAPP - a real anchor (it leaves the site, so it must be middle-clickable,
        long-pressable and copyable), text-only with the destination in the quiet microcopy below.
        The matched twin of the Contribute pill in BlogContribution. */}
    <a
      className="blog-cta-subscribe"
      href={ SUBSCRIBE_HREF }
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Subscribe on WhatsApp"
    >
      <span>Subscribe</span>
    </a>
    <p className="wc-sweep-note" aria-hidden="true">Continue on WhatsApp →</p>

    {/* CONTRIBUTE - the shared block. embedded drops its own top rule since this aside already
        owns the band rhythm. */}
    <BlogContribution postId={ contributionId } slug={ contributionId } embedded />

    {/* SHARE - the shared row. On the index there is no reveal sentinel, so it is simply the
        static controls. */}
    <div className="blog-cta-share">
      <ShareLinks url={ shareUrl } title={ shareTitle } />
    </div>

    <style jsx>{`
      /* blog-cta- prefixed because the globally imported src/styles/*.css declares unscoped rules
         for generic names and styled-jsx does not shield a block from them. The band reuses the
         post page's hairline rhythm and the site's lime CTA language. */
      .blog-cta{
        margin-top:48px;padding-top:28px;border-top:1px solid #e5e7eb;
        display:flex;flex-direction:column;align-items:flex-start;
        font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      }
      /* THE SUBSCRIBE PILL - the post page's .blog-wa-subscribe object, declared identically: a
         52px lime pill with a 2px #1a3a2a edge (the edge is what clears WCAG 1.4.11 for a control
         boundary - lime alone is 1.24:1), #1a3a2a type on #d1f470 at 10.04:1, and the house white
         hover inversion with the one allowed lift and shadow. No margin-top here: the band's own
         padding opens the space. */
      .blog-cta-subscribe{
        display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;
        min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
        background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
        text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
      }
      .blog-cta-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
      .blog-cta-subscribe:active{transform:translateY(0)}
      .blog-cta-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
      /* The share row sits in the same hairline rhythm the Contribute block opens above it. */
      .blog-cta-share{margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb;align-self:stretch}
      @media(prefers-reduced-motion:reduce){
        .blog-cta-subscribe{transition:none}
        .blog-cta-subscribe:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </aside>
);

export default BlogFooterCTA;
