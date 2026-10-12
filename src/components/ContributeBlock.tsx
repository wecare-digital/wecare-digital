import React, { useCallback, useState } from 'react';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_CURRENCY } from '../config/contribution';
import { setContribution } from '../lib/cart';

/**
 * The owner's Contribute Meta message link. The ONE place this URL is written now that the old
 * WhatsApp-only BlogContribution block has been retired. It used to live in BlogContribution and
 * be re-used here; with that component deleted the constant moves to its only remaining home.
 */
export const CONTRIBUTE_CTA_HREF = 'https://wa.me/message/BYFLCAAMSZBXD1';

/**
 * CONTRIBUTE BLOCK - a reusable voluntary-contribution block that offers BOTH ways to give.
 *
 * WHY THIS EXISTS ALONGSIDE BlogContribution. BlogContribution is deliberately a single WhatsApp
 * link and nothing else - no cart write, no navigation - because on a blog post the owner wanted a
 * contribution to be a CONVERSATION. This block is the richer pair the product surfaces use: it
 * offers the SAME WhatsApp conversation AND the on-site checkout path, styled like the product
 * buy-box pair (a lime primary pill and an outlined secondary pill). The owner will place it on
 * specific pages (VayuLok, centres) later; it is NOT mounted anywhere yet.
 *
 * THE AMOUNT IS A LABEL, NEVER A PRICE THE BROWSER SENDS. Both the figure on screen and the cart
 * line are read from the central src/config/contribution.ts (CONTRIBUTION_CHOICES[0].rupees = 250,
 * ₹ for CONTRIBUTION_CURRENCY = 'INR'), the same source the cart row and the server's own mirror
 * read, so the number cannot drift from the one the cart would price. Nothing about the amount,
 * price or currency leaves the browser - cart_v2.calculate remains the sole price authority. The
 * checkout path only NAMES the variant (via setContribution, which writes a catalogue reference +
 * quantity 1 and replaces any existing contribution line), exactly like the cart contribution row.
 *
 * TWO PATHS, ONE INTENT.
 *   - WhatsApp (primary, lime): a real anchor at CONTRIBUTE_CTA_HREF (the owner's Contribute Meta
 *     message link, wa.me/message/BYFLCAAMSZBXD1 - the ONE place that URL is declared, re-used
 *     from BlogContribution so the two cannot diverge). An anchor, not a button, because it leaves
 *     the site and must be middle-clickable, long-pressable and copyable.
 *   - Checkout (secondary, outlined): a button that adds the Contribute product to the cart via
 *     setContribution( CONTRIBUTION_CHOICES[0].variantId ) and navigates to /cart/, where the
 *     existing checkout prices and collects. setContribution REPLACES rather than increments, so
 *     tapping it twice leaves one contribution line, which is the basket the server accepts.
 *
 * ACCESSIBLE. Each control's accessible name CONTAINS its visible word (WCAG 2.5.3 Label in Name):
 * "Continue on WhatsApp" and "Continue to checkout", so a speech-input user saying "click
 * Continue" reaches them. The heading is an h2, never an h1, so a host page keeps its single h1.
 *
 * SELF-STYLING with styled-jsx and .contribute-* prefixed classes, because the globally imported
 * src/styles/*.css declares unscoped rules for generic names and styled-jsx does not shield a
 * block from them. The lime pill matches the site's CTA language exactly (same geometry as .bc-cta
 * and .ps-subscribe): min-height 52px, 2px #1a3a2a edge, 50px radius, #d1f470 fill, #1a3a2a type,
 * the white hover inversion with the one allowed lift and shadow, an opaque focus ring, and a
 * reduced-motion guard. The outlined secondary mirrors ProductBuyBox's .pbb-cta.
 */

/** The suggested amount, read from the central config so the figure is never re-typed. */
const [ SUGGESTED ] = CONTRIBUTION_CHOICES;
/** The display glyph for the single currency contributions are taken in. INR -> ₹. */
const CURRENCY_GLYPH: Record<string, string> = { INR: '\u20B9' };
/** e.g. "₹250" - the suggested amount shown on the amount line. */
export const CONTRIBUTE_BLOCK_AMOUNT_LABEL =
  `${ CURRENCY_GLYPH[ CONTRIBUTION_CURRENCY ] || '' }${ SUGGESTED.rupees }`;

export interface ContributeBlockProps {
  /** Removes the component's own top rule when a parent surface already owns section rhythm. */
  embedded?: boolean;
}

const ContributeBlock: React.FC<ContributeBlockProps> = ( { embedded = false } ) => {
  const [ busy, setBusy ] = useState( false );

  /**
   * The on-site path: name the contribution variant in the cart, then go to /cart/. No amount is
   * sent - setContribution writes a catalogue reference + quantity 1 and the server prices it.
   * window.location is used rather than next/router so the block has no router dependency and can
   * be dropped onto any surface; the write happens BEFORE the navigation so the line is present on
   * arrival, the same contract the shop cart uses.
   */
  const onCheckout = useCallback( () => {
    if ( busy ) return;
    setBusy( true );
    try {
      setContribution( SUGGESTED.variantId );
    } catch {
      /* a rejected variant writes nothing; the cart page still loads */
    }
    if ( typeof window !== 'undefined' ) window.location.assign( '/cart/' );
  }, [ busy ] );

  return (
    <section className={ embedded ? 'contribute is-embedded' : 'contribute' } aria-labelledby="contribute-title">
      {/* h2, never h1: a host page already owns its single h1. */}
      <h2 className="contribute-title" id="contribute-title">Contribute</h2>

      {/* ONE COMPACT LINE, BOTH PATHS. Owner instruction (2026-10-12): drop the two big pill
          buttons and the copy sentence; the whole appeal is a single quiet line - a ₹ glyph, the
          suggested amount as a static label, then two small inline links that address the two
          contribution paths. "₹250" is a label from the central config, never a price the browser
          sends. The two links are the SAME destinations the old pills had, now as text:
            - "on WhatsApp" -> the Contribute Meta chat (a real anchor, new tab);
            - "on the website" -> a button that names the variant in the cart and goes to /cart/.
          Rendered as a <p> so the glyph+label is text and the two actions sit inline within it. */}
      <p className="contribute-line">
        <span className="contribute-mark" aria-hidden="true">{ '\u20B9' }</span>
        <span className="contribute-label" data-wc-no-translate="true">
          { `Contribute ${ CONTRIBUTE_BLOCK_AMOUNT_LABEL }` }
        </span>
        <span className="contribute-sep" aria-hidden="true">{ '\u00B7' }</span>
        {/* WhatsApp path - a real anchor (leaves the site, so middle-clickable/copyable). The
            accessible name names the action AND the destination (WCAG 2.5.3). */}
        <a
          className="contribute-link"
          href={ CONTRIBUTE_CTA_HREF }
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Contribute on WhatsApp"
        >on WhatsApp</a>
        <span className="contribute-sep" aria-hidden="true">{ '\u00B7' }</span>
        {/* On-site path - a button, because it writes the cart and navigates rather than leaving
            the site. Styled as a text link to match its sibling. */}
        <button
          type="button"
          className="contribute-link contribute-link-btn"
          onClick={ onCheckout }
          disabled={ busy }
          aria-busy={ busy }
          aria-label="Contribute on the website at checkout"
        >{ busy ? 'one moment…' : 'on the website \u2192' }</button>
      </p>

      <style jsx>{`
        /* contribute- prefixed: the globally imported src/styles/*.css declares unscoped rules for
           generic names and styled-jsx does not shield a block from them. The treatment reuses the
           site's hairline rhythm and lime CTA language. */
        .contribute{
          margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb;
          font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        }
        .contribute.is-embedded{margin-top:0;padding-top:0;border-top:0}
        /* h2 at the related-section eyebrow rung, NOT the 40px/700 section rung, because this is a
           quiet appeal rather than a claim - the same treatment the blog "More in ..." heading and
           the breadcrumb furniture use. */
        .contribute-title{
          font-size:12px;font-weight:700;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;
          color:rgba(0,0,0,.54);margin:0 0 12px;
        }
        /* THE ONE LINE. A single flowing row: the ₹ glyph, the "Contribute ₹250" label, then the
           two inline text links separated by middle dots. flex-wrap means on a narrow phone the
           links drop to a second line before anything overflows; align-items:baseline keeps the
           glyph, label and links sitting on one type baseline. 17px/400 is reading text, not a
           pill - this is a quiet line, not a buy-box. */
        .contribute-line{
          margin:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:0 8px;
          font-size:17px;line-height:1.5;letter-spacing:-.125px;color:rgba(0,0,0,.898);
        }
        /* THE ₹ GLYPH in a soft lime disc - a small quiet mark, not a control. tabular so the
           rupee sign sits centred. */
        .contribute-mark{
          display:inline-flex;align-items:center;justify-content:center;
          width:26px;height:26px;border-radius:50%;background:#eef7d6;
          font-size:15px;font-weight:700;color:#1a3a2a;flex:none;
        }
        /* THE LABEL - "Contribute ₹250", the static figure from config. Slightly heavier than the
           links so the amount reads as the subject of the line. */
        .contribute-label{font-weight:600;color:#1a1a1a;font-variant-numeric:tabular-nums}
        /* THE SEPARATOR DOTS between label and links, and between the two links. */
        .contribute-sep{color:rgba(0,0,0,.32)}
        /* THE TWO ACTIONS, as text links. Underlined so each reads as a link rather than running
           into the label; #1a3a2a type on white is 12.48:1. The button variant resets native
           chrome so it matches the anchor exactly - same font, no border, no background, pointer
           cursor - because it does the same job (start a contribution) and should read the same. */
        /* THE TWO ACTIONS, as text links with a LIME underline. The text stays #1a3a2a (12.48:1
           on white, the readable value); only the underline is the brand lime #d1f470, set with
           text-decoration-color so the link reads as a house link rather than a default dark one.
           A thicker 2.5px rule makes the lime visible under the type. The button variant resets
           native chrome so it matches the anchor exactly. */
        .contribute-link{
          font:inherit;font-weight:600;color:#1a3a2a;
          text-decoration:underline;text-decoration-color:#d1f470;
          text-underline-offset:3px;text-decoration-thickness:2.5px;cursor:pointer;
          background:none;border:0;padding:0;transition:text-decoration-color .18s;
        }
        .contribute-link:hover{text-decoration-color:#1a3a2a}
        .contribute-link:disabled{opacity:.55;cursor:default;text-decoration:none}
        /* Opaque focus ring at offset, the page's standard - never a translucent alpha. */
        .contribute-link:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;border-radius:3px}
      `}</style>
    </section>
  );
};

export default ContributeBlock;
