import React, { useCallback, useState } from 'react';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_CURRENCY } from '../config/contribution';
import { setContribution } from '../lib/cart';
import { CONTRIBUTE_CTA_HREF } from './BlogContribution';

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
      <p className="contribute-copy">If this helped, consider a small voluntary contribution.</p>

      <div className="contribute-actions">
        {/* PRIMARY, LIME - the WhatsApp conversation. A real anchor at the owner's Contribute Meta
            message link, re-used from BlogContribution so the two surfaces cannot diverge. The
            accessible name contains the visible "Continue" (WCAG 2.5.3). */}
        <a
          className="contribute-cta contribute-cta-primary"
          href={ CONTRIBUTE_CTA_HREF }
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Continue on WhatsApp to contribute"
        >Continue on WhatsApp →</a>

        {/* SECONDARY, OUTLINED - the on-site checkout. Adds the Contribute product to the cart and
            goes to /cart/. A button, because it writes to the cart and navigates rather than
            leaving the site. The accessible name contains the visible "Continue" (WCAG 2.5.3). */}
        <button
          type="button"
          className="contribute-cta contribute-cta-secondary"
          onClick={ onCheckout }
          disabled={ busy }
          aria-busy={ busy }
          aria-label="Continue to checkout to contribute"
        >{ busy ? 'One moment…' : 'Continue to checkout →' }</button>
      </div>

      {/* THE AMOUNT, A STATIC LABEL - "₹250 · voluntary". The figure is from the central config;
          "voluntary" says the ask is optional. No price is sent from the browser; the server
          prices the named variant. */}
      <p className="contribute-amount" data-wc-no-translate="true">
        { `${ CONTRIBUTE_BLOCK_AMOUNT_LABEL } \u00B7 voluntary` }
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
        .contribute-copy{
          font-size:18px;line-height:1.5;letter-spacing:-.125px;font-weight:400;
          color:rgba(0,0,0,.898);margin:0 0 20px;max-width:60ch;
        }
        /* THE PAIR, like the product buy-box: the lime primary first, the outlined secondary
           beside it, wrapping to a second line on a narrow screen. Each is a >=44px (actually
           52px) WCAG 2.5.8 tap target. */
        .contribute-actions{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center}
        /* SHARED PILL GEOMETRY - the site's CTA object, identical to .bc-cta / .ps-subscribe:
           min-height 52px, 28px inline padding, a 2px #1a3a2a edge (the edge clears WCAG 1.4.11
           for a control boundary - lime alone is 1.24:1), 50px radius, 17px/600 label. */
        .contribute-cta{
          display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;
          min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
          font-size:17px;font-weight:600;line-height:1.2;text-decoration:none;cursor:pointer;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        /* PRIMARY: lime fill, #1a3a2a type at 10.04:1; the house white hover inversion with the one
           allowed lift and shadow (white gives #1a3a2a type 12.48:1). */
        .contribute-cta-primary{background:#d1f470;color:#1a3a2a}
        .contribute-cta-primary:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .contribute-cta-primary:active{transform:translateY(0)}
        /* SECONDARY: outlined white, inverting to the lime fill on hover - the ProductBuyBox
           .pbb-cta treatment, so the two families match. */
        .contribute-cta-secondary{background:#fff;color:#1a3a2a}
        .contribute-cta-secondary:hover:not(:disabled){background:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .contribute-cta-secondary:active:not(:disabled){transform:translateY(0)}
        .contribute-cta-secondary:disabled{opacity:.55;cursor:default}
        /* Opaque focus ring at offset, the page's standard - never a translucent alpha. */
        .contribute-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        /* THE AMOUNT LINE, quiet and tabular so it reads as a figure rather than a claim. */
        .contribute-amount{
          margin:16px 0 0;font-size:15px;font-weight:600;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.54);font-variant-numeric:tabular-nums;
        }
        /* NOTHING MOVES FOR A READER WHO ASKED FOR LESS MOTION - the lift and shadow are the only
           motion here, so both are cancelled while the colour feedback stays. */
        @media(prefers-reduced-motion:reduce){
          .contribute-cta{transition:background-color .2s}
          .contribute-cta-primary:hover,.contribute-cta-secondary:hover:not(:disabled){transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default ContributeBlock;
