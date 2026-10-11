import React from 'react';

/**
 * THE RSS SUBSCRIBE AFFORDANCE, ICON-ONLY, AT THE FOOT OF A BLOG SURFACE.
 *
 * It replaces the old text pill ("Subscribe via RSS") that sat in a toolbar row at the TOP of
 * /blog/. On owner instruction the affordance is now a compact lime glyph placed at the BOTTOM
 * of both /blog/ and the /anew/ panel, so the two surfaces advertise the same feed with the
 * same control.
 *
 * A PLAIN <a>, NOT next/link. /blog/rss.xml is an XML file scripts/generate-blog-rss.js writes
 * to out/ after the build - it is a build artifact, not a Next page route - so routing it
 * client-side would 404 against the page router. The @next/next/no-html-link-for-pages lint only
 * fires for hrefs that resolve to a file under pages/, which /blog/rss.xml does not, so no
 * disable directive is needed. type="application/rss+xml" tells the browser what it points at.
 *
 * ICON-ONLY, BUT NOT NAMELESS. The visible content is just the glyph; the accessible name comes
 * from two sources that agree - an explicit aria-label and a visually-hidden <span> - so a
 * screen reader announces "Subscribe via RSS" while a sighted reader sees only the lime mark.
 * The SVG is aria-hidden because the text already carries the name (WCAG 2.5.3 / 4.1.2).
 *
 * CONTRAST, DELIBERATELY DARK-GREEN GLYPH ON LIME. The glyph is #1a3a2a on a #d1f470 fill
 * (~10:1), not a lime glyph on white (which would be ~1.3:1 and fail). The fill carries the
 * brand; the ink carries the shape.
 */

export interface RssIconProps {
  /** Extra class on the <a>, e.g. to align it within its container. */
  className?: string;
}

const RSS_URL = '/blog/rss.xml';

const RssIcon: React.FC<RssIconProps> = ( { className } ) => (
  <a
    className={ className ? `rss-icon ${className}` : 'rss-icon' }
    href={ RSS_URL }
    type="application/rss+xml"
    aria-label="Subscribe via RSS"
  >
    {/* The standard RSS mark: two arcs and a dot, drawn in currentColor so one glyph colour
        tracks the ink. aria-hidden because the accessible name is on the anchor and the span. */}
    <svg className="rss-icon-glyph" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M4 11a9 9 0 0 1 9 9" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M4 4a16 16 0 0 1 16 16" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="5" cy="19" r="2.4" fill="currentColor" />
    </svg>
    <span className="rss-icon-sr">Subscribe via RSS</span>

    <style jsx>{`
      /* A COMPACT LIME CIRCLE, 44x44 - the WCAG 2.5.8 touch-target floor, so it is reliably
         tappable rather than merely clickable. Lime fill, dark-green glyph for contrast. */
      .rss-icon{
        display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;
        width:44px;height:44px;border-radius:50%;
        background:#d1f470;color:#1a3a2a;text-decoration:none;
        transition:transform .2s,box-shadow .2s,background-color .2s;
      }
      .rss-icon:hover{
        transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
      }
      /* The opaque dark-green ring the rest of the site uses - the translucent one failed WCAG
         1.4.11 at 1.51:1 against white. 3px here per the owner spec for this control. */
      .rss-icon:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
      .rss-icon-glyph{display:block}
      /* The site's sr-only pattern - the accessible name a screen reader reads, out of view. */
      .rss-icon-sr{
        position:absolute;width:1px;height:1px;padding:0;margin:-1px;
        overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
      }
      @media(prefers-reduced-motion:reduce){
        .rss-icon{transition:none}
        .rss-icon:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </a>
);

export default RssIcon;
