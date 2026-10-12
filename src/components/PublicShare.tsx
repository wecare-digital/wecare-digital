import React, { useEffect, useState } from 'react';
import ShareLinks from './ShareLinks';

/**
 * The Subscribe WhatsApp link: the dedicated Meta short link, equal to SUBSCRIBE_CTA_HREF in
 * src/content/subscribe.ts and the whatsappServiceEntries 'subscribe' row, so every Subscribe
 * entry point agrees and matches the blog surfaces.
 */
const SUBSCRIBE_HREF = 'https://wa.me/message/WUDPTMYSO6XII1';

/**
 * THE "SUBSCRIBE + SHARE" BLOCK FOR PUBLIC PAGES.
 *
 * Owner instruction: every public page carries ONE consistent block at the end of its own content
 * (where the content ends / naturally sits) - NOT in the footer, and NOT a single global strip -
 * holding Subscribe FOLLOWED BY Share on the same row. Subscribe is the WhatsApp pill (the same
 * one the blog surfaces use); Share is the icon row that shares THAT page's own info (its
 * canonical URL and title). The two sit in one row and wrap to two lines on a narrow screen.
 *
 * WHY IT RESOLVES THE URL/TITLE ITSELF rather than taking them as props. The point of the block
 * is "share the page you are on", and that is the same answer on every page - the current
 * location and the current document title. Reading them here means a page adds the block with a
 * bare <PublicShare /> and cannot pass a stale or mismatched URL. A caller that genuinely needs a
 * different target (e.g. a canonical that differs from location, or a custom share message like
 * VayuLok's live air+weather text) passes the optional overrides below.
 *
 * SSR-SAFE. The static export has no window at build time, so the first render uses the optional
 * `url`/`title` props or empty strings, and an effect fills in the live location.href and
 * document.title after mount. ShareLinks already degrades gracefully: its WhatsApp anchor is a
 * real href (so it works pre-hydration when a url is supplied), and the native-share and
 * copy-link controls are script-only and reveal themselves only once their APIs are confirmed.
 *
 * NOT ON /blog OR /post. Those surfaces already carry their own Share inside the BlogFooterCTA /
 * post-page CTA band, so a page that owns a Share must not also render this one - the caller
 * simply does not add <PublicShare /> there.
 */

export interface PublicShareProps {
  /**
   * Override the shared URL. Defaults to the page's own canonical (location.href with any query
   * or hash stripped). Pass this when the canonical differs from the address bar.
   */
  url?: string;
  /** Override the shared title. Defaults to the document title. */
  title?: string;
  /** The row label. Defaults to 'Share'. */
  label?: string;
}

/** Strip query + hash so a shared link is the page's clean canonical, not the reader's URL. */
const cleanUrl = ( href: string ): string => {
  try {
    const u = new URL( href );
    return `${u.origin}${u.pathname}`;
  } catch {
    return href;
  }
};

const PublicShare: React.FC<PublicShareProps> = ( { url, title, label = 'Share' } ) => {
  // First render (and the static export) use the props or empty strings; the effect fills in the
  // live values after mount. Empty strings are fine: ShareLinks renders, and the controls that
  // need a URL simply have nothing to act on until hydration supplies it a tick later.
  const [ resolvedUrl, setResolvedUrl ] = useState<string>( url || '' );
  const [ resolvedTitle, setResolvedTitle ] = useState<string>( title || '' );

  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    if ( !url ) setResolvedUrl( cleanUrl( window.location.href ) );
    if ( !title ) setResolvedTitle( document.title || window.location.hostname );
  }, [ url, title ] );

  return (
    <section className="public-share" aria-label="Subscribe and share this page">
      <div className="ps-row">
        {/* SUBSCRIBE, FIRST. A real anchor to the WhatsApp subscribe deep link (it leaves the
            site, so it must be middle-clickable, long-pressable and copyable). The lime pill is
            the same object the blog Subscribe uses. It sits on the same row as the Share controls,
            which follow it. */}
        <a
          className="ps-subscribe"
          href={ SUBSCRIBE_HREF }
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Subscribe on WhatsApp"
        >Subscribe</a>

        {/* SHARE, FOLLOWING SUBSCRIBE on the same row. Shares this page's own URL + title. */}
        <ShareLinks url={ resolvedUrl } title={ resolvedTitle } label={ label } />
      </div>

      <style jsx>{`
        /* public-share- is deliberately specific: the globally imported src/styles/*.css declares
           unscoped rules for generic names, and styled-jsx does not shield a block from them. The
           band sits at the end of a page's content in the site's hairline rhythm - 28px of air
           under a 1px #e5e7eb rule - the same treatment the post page's share row uses, so the
           tail of any public page reads the same. ShareLinks styles its own controls. */
        /* EQUAL PADDING TOP AND BOTTOM so the Subscribe+Share row sits VERTICALLY CENTERED between
           its separators (owner instruction) - it used to hug the top with padding-top only. The
           row stays LEFT-aligned horizontally; this only balances the vertical space. The
           border-top is the full-width separator; the band's own bottom padding gives the matching
           space beneath the row before whatever follows. */
        /* The band sizes to its content with equal top/bottom air - NO min-height. A forced
           min-height left a large empty gap below the row before the footer, which read as a
           defect. 28px top and bottom around the 52px row gives a balanced ~108px band.
           width:100% so the block spans the FULL content measure (not a narrow strip); the
           separator rule therefore runs the whole width. Left-aligned horizontally. */
        .public-share{
          width:100%;margin-top:48px;padding:28px 0;border-top:1px solid #e5e7eb;box-sizing:border-box;
          display:flex;align-items:center;
          font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        }
        /* ONE ROW, LEFT-ALIGNED: Subscribe pill, then the Share controls, flush to the start of
           the content measure (owner instruction - an independent block with its own full-width
           separators, NOT centred). align-items:center aligns the 52px pill with the 44px share
           icons; gap:16px/20px separates Subscribe from Share.
           DEVICE-COMPATIBLE: flex-wrap:wrap means the Share group drops onto its own line under
           Subscribe before anything can overflow, so there is no horizontal scroll at any width
           from 320px up; every control is already a >=44px WCAG 2.5.8 tap target. */
        .ps-row{display:flex;align-items:center;flex-wrap:wrap;gap:16px 20px}
        /* On the narrowest phones stack the two groups, each starting at the left edge, so a long
           Share label never crowds the pill. 400px is above 320-375 handsets and below the point
           the single row fits comfortably. */
        @media(max-width:400px){
          .ps-row{flex-direction:column;align-items:flex-start}
        }
        /* THE SUBSCRIBE PILL - the site's lime CTA object (same values as the blog Subscribe):
           52px, 2px #1a3a2a edge (the edge is what clears WCAG 1.4.11 for a control boundary -
           lime alone is 1.24:1), #1a3a2a type on #d1f470 at 10.04:1, the house white hover
           inversion with the one allowed lift and shadow, and the opaque focus ring. */
        .ps-subscribe{
          display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;
          min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
          text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .ps-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .ps-subscribe:active{transform:translateY(0)}
        .ps-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        @media(prefers-reduced-motion:reduce){
          .ps-subscribe{transition:none}
          .ps-subscribe:hover{transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default PublicShare;
