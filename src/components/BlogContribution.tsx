import React, { useState } from 'react';
import PillButton from './PillButton';
import { CONTRIBUTION_CHOICES } from '../config/contribution';
import { CONTRIBUTION_CONFIGURED } from '../content/shop';
import { isContributionItem, readCart, setContribution } from '../lib/cart';

/**
 * "SUPPORT THIS WORK" - the Section 5 voluntary-contribution block that sits on every blog post,
 * after the Tags row and before the Share controls (see src/pages/post/[slug].tsx for the exact
 * DOM position and why the share reveal sentinel stays where it is).
 *
 * WHAT THIS COMPONENT IS, AND WHAT IT IS NOT
 * ------------------------------------------
 * It is the UI and NOTHING ELSE. It renders the three fixed contribution choices, and on a user
 * action it PUTS A LINE IN THE CART and navigates to /cart/. It issues no network request, holds
 * no payment state, and knows nothing about Razorpay.
 *
 * There is no custom-amount input and no client-side amount validation: a choice is one of three
 * fixed-price Wix variants, so there is no number for the reader to propose and nothing to parse.
 *
 * PHASE 2 (2026-10-03): THE ENTIRE NETWORK AND PAYMENT HALF OF THIS COMPONENT WAS DELETED
 * ----------------------------------------------------------------------------------------
 * It used to POST to `${API_BASE}/ecommerce/contribution` and branch on a backend state. That
 * endpoint never existed - it answered 404, which the component honestly degraded to
 * "Contributions are not available right now." - and it is never going to exist. A contribution is
 * now ONE fixed-price Wix product line in the existing cart, paid on the one live checkout path:
 *
 *   choose an amount -> setContribution( variantId ) -> /cart/ -> POST /ecommerce/prepare-checkout
 *   -> cart_v2.calculate prices it -> Razorpay modal -> POST /ecommerce/verify-callback -> one order
 *
 * `src/pages/cart.tsx` already owns the Razorpay SDK load, the modal, the `payment.failed`
 * handler, the dismiss handler, the rail-terminal latch and the verify POST. Deleting the ~70
 * lines of client-side payment handling that used to live here is what makes "one checkout path"
 * true rather than aspirational, and nothing replaces them.
 *
 * THREE FIXED CHOICES, NO "OTHER" (owner model change, 2026-10-04)
 * ---------------------------------------------------------------
 * There are exactly three contributions - Rs.100, Rs.250, Rs.500 - each a fixed-price variant of
 * the one `Contribute` product, added at quantity 1. The custom-amount radio, the free-text rupee
 * field, its `aria-describedby` help text, the client-side bounds check and the `invalid` phase
 * are all GONE rather than hidden. A form with no free text cannot be given an invalid value, so
 * there is no refusal to render: every control on it leads somewhere.
 *
 * HONEST DEGRADATION IS STILL THE WHOLE POINT, with a narrower and knowable trigger
 * ---------------------------------------------------------------------------------
 * The only browser-side gate is now CONFIGURATION, and it is knowable at BUILD time - which is
 * what a static export needs. Configured means a contribution product id and three variant ids are
 * declared in src/config/contribution.ts. Unconfigured renders the honest line and NO FORM, and
 * never navigates - so a build with no vehicle says contributions are unavailable instead of
 * offering a button that cannot work.
 *
 * The server remains the authority: `_contribution_request` looks the chosen variant up in its OWN
 * committed copy of the three choices and refuses anything else, and `_assert_contribution_total`
 * holds Wix's computed total to the figure on the button. Nothing here is ever treated as proof of
 * payment, because nothing here touches a payment.
 */

export interface BlogContributionProps {
  /** The blog post's authoritative id (PublicBlogPost.id), so a contribution is attributable. */
  postId: string;
  /** The post slug, carried alongside the id for human-readable attribution and reconciliation. */
  slug: string;
  /** Removes the component's own top rule when a parent surface already owns section rhythm. */
  embedded?: boolean;
}

const HONEST_UNAVAILABLE = 'Contributions are not available right now.';

const BlogContribution: React.FC<BlogContributionProps> = ( { postId, slug, embedded = false } ) => {
  /**
   * The selected variant id. A STRING rather than an index, so the value in state is the value
   * that goes into the cart line and no lookup can slip between the two.
   *
   * There is no `null` state and no validation state: one of the three is always selected, so
   * "nothing chosen" and "chosen badly" are both unreachable.
   */
  const [ variantId, setVariantId ] = useState<string>( CONTRIBUTION_CHOICES[ 0 ].variantId );

  const chosen = CONTRIBUTION_CHOICES.find( choice => choice.variantId === variantId )
    || CONTRIBUTION_CHOICES[ 0 ];

  /**
   * Put the choice in the cart and go there. NO `async`, no network, no payment state.
   *
   * Two steps and that is the whole of it: `setContribution`, navigate. `setContribution` SETS
   * rather than increments, so choosing Rs.100 and then Rs.500 leaves ONE line at Rs.500 - which
   * is what "choose an amount" means, and is why `addItem` is not reused.
   */
  const onSubmit = ( event: React.FormEvent ) => {
    event.preventDefault();
    setContribution( chosen.variantId );
    window.location.assign( '/cart/' );
  };

  /**
   * Unconfigured renders the honest line and NO FORM, and never navigates.
   *
   * Placed before every control rather than disabling them, because a form that cannot work is
   * worse than no form: it invites the click and then explains. Returned early so the markup below
   * does not need a conditional on every node.
   */
  if ( !CONTRIBUTION_CONFIGURED )
  {
    return (
      <section className={ embedded ? 'bc is-embedded' : 'bc' } aria-labelledby="bc-title" data-post-id={ postId }>
        <h2 className="bc-title" id="bc-title">Contribute</h2>
        <p className="bc-status" role="status" data-phase="unavailable">{ HONEST_UNAVAILABLE }</p>
        <style jsx>{`
          .bc{
            margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb;
            font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          }
          .bc.is-embedded{margin-top:0;padding-top:0;border-top:0}
          .bc-title{
            font-size:12px;font-weight:700;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;
            color:rgba(0,0,0,.54);margin:0 0 12px;
          }
          .bc-status{font-size:15px;line-height:1.5;color:rgba(0,0,0,.7);margin:0}
        `}</style>
      </section>
    );
  }

  /**
   * Does the cart ALREADY hold something that is not a contribution?
   *
   * NOT `cartMixesContribution()`, which answers "is the basket already mixed" and is therefore
   * false at the moment this warning is needed: the contribution has not been added yet. The
   * question here is whether adding one WOULD mix it.
   *
   * Reads storage rather than taking an argument, because the cart may have been edited in
   * another tab since this page rendered.
   */
  const mixes = readCart().some( item => !isContributionItem( item ) );

  return (
    <section className={ embedded ? 'bc is-embedded' : 'bc' } aria-labelledby="bc-title" data-post-id={ postId }>
      {/* h2, never h1: the post page already owns the single h1, and htmlcheck guards H1-MANY. */}
      <h2 className="bc-title" id="bc-title">Contribute</h2>
      <p className="bc-copy">
        If you found this useful, you’re welcome to make a small voluntary contribution.
      </p>

      <form className="bc-form" onSubmit={ onSubmit } noValidate>
        <fieldset className="bc-fieldset">
          <legend className="bc-legend">Choose an amount</legend>
          <div className="bc-choices" role="radiogroup" aria-label="Contribution amount">
            { CONTRIBUTION_CHOICES.map( choice => (
              <label className="bc-choice" key={ choice.variantId }>
                <input
                  type="radio"
                  name={ `bc-amount-${ slug }` }
                  className="bc-radio"
                  value={ choice.variantId }
                  checked={ variantId === choice.variantId }
                  onChange={ () => setVariantId( choice.variantId ) }
                />
                <span className="bc-choice-face">&#8377;{ choice.rupees }</span>
              </label>
            ) ) }
          </div>
        </fieldset>

        <div className="bc-submit-wrap">
          {/* The button NAVIGATES rather than pays now, so it must say what it is about to put in
              the cart. It can always name a figure, because one of the three is always selected.
              No fee-disclosure line sits under it: OWNER DECISION [PHASE2-FEE-001] is answered
              fee-exempt, so the customer pays exactly the figure on the button and a disclosure
              about a fee that is not charged would be its own small untruth. */}
          <PillButton
            as="button"
            type="submit"
            action={ `Contribute \u20B9${ chosen.rupees }` }
          />
        </div>

        {/* A contribution is paid on its own, so warn at the ENTRY POINT rather than letting the
            customer discover it at the cart. The submit still navigates to /cart/, where the
            notice and the per-row Remove controls live - deciding for them which lines to drop
            would be worse than telling them.

            The copy DESCRIBES WHAT THE CART DOES rather than promising a prompt. It used to read
            "the cart will ask which to keep"; the cart does not ask - it shows a notice, disables
            Checkout and leaves every row's Remove button in place. Naming an interaction that
            does not exist sends the customer looking for it. */}
        { mixes && (
          <p className="bc-note" data-phase="mixed">
            Your cart has other items. A contribution is paid on its own, so remove either the
            contribution or the other items at the cart before checking out.
          </p>
        ) }

        {/* NO LIVE REGION ON THE FORM ANY MORE. It existed to announce a rejected custom amount,
            and with three fixed choices there is no amount to reject. The unavailable branch above
            keeps its own `role="status"`, which is the one message that remains. */}
      </form>

      <style jsx>{`
        /* bc- prefixed because the globally imported src/styles/*.css declares unscoped rules for
           generic names and styled-jsx does not shield a block from them. The treatment reuses the
           blog post page's own rhythm (the hairline band, the e5e7eb rules) and the site's lime
           CTA language (see zip.tsx / the related-posts CTA on this same page). */
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
        .bc-form{margin:0}
        .bc-fieldset{border:0;margin:0;padding:0}
        .bc-legend{font-size:12px;font-weight:600;letter-spacing:.01em;color:rgba(0,0,0,.54);padding:0;margin:0 0 10px}
        .bc-choices{display:flex;flex-wrap:wrap;gap:10px}
        /* The real radio is visually hidden but keyboard-reachable; the face is the pill. */
        .bc-choice{position:relative;display:inline-flex}
        .bc-radio{position:absolute;opacity:0;width:1px;height:1px;margin:0}
        /* min-height 44px is the tap-target floor, and it is here because the pill MEASURED
           43px in Chromium at 390x844 - one pixel under, which no suite was looking at and no
           eye would catch. The 8px/16px padding is kept so the shape does not change; the floor
           just stops the box rounding below it. The site's primary CTA is 52px; a secondary
           choice is not required to match it, only to clear 44. */
        .bc-choice-face{
          display:inline-flex;align-items:center;justify-content:center;min-width:64px;
          min-height:44px;
          padding:8px 16px;border:2px solid #e5e7eb;border-radius:999px;background:#fff;
          font-size:15px;font-weight:700;letter-spacing:-.125px;color:#1a3a2a;cursor:pointer;
          transition:border-color .2s,background-color .2s,transform .2s,box-shadow .2s;
        }
        .bc-radio:hover + .bc-choice-face{
          border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        /* Checked is the lime identity fill - the same #d1f470/#1a3a2a voice the related CTA uses. */
        .bc-radio:checked + .bc-choice-face{border-color:#1a3a2a;background:#d1f470}
        /* Opaque focus ring at offset, the page's standard - never a translucent alpha. */
        .bc-radio:focus-visible + .bc-choice-face{outline:3px solid #1a3a2a;outline-offset:2px}
        /* The custom-amount field's six rules (.bc-custom, -label, -row, .bc-rupee, -input, and
           the :focus-within border) went with the field itself. .bc-note is what is left: the
           quiet line under the choices that warns a mixed basket. */
        .bc-note{font-size:13px;line-height:1.4;color:rgba(0,0,0,.54);margin:8px 0 0}
        /* The action itself is the shared public PillButton. This wrapper owns only placement,
           so Contribute cannot drift from Sign in / Checkout / Subscribe in shape or palette. */
        .bc-submit-wrap{margin-top:20px;display:flex;align-items:center}
        /* The status line is deliberately plain, not a success banner: it carries the honest
           "not available" sentence and nothing else. It is never a receipt. */
        .bc-status{font-size:15px;line-height:1.5;color:rgba(0,0,0,.7);margin:16px 0 0}
        @media(prefers-reduced-motion:reduce){
          .bc-choice-face{transition:none}
          .bc-radio:hover + .bc-choice-face{transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default BlogContribution;
