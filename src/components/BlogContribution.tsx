import React, { useState } from 'react';
import PillButton from './PillButton';
import {
  CONTRIBUTION_CURRENCY,
  CONTRIBUTION_PRESETS_PAISE,
  CONTRIBUTION_PURPOSE,
  paiseToRupees,
} from '../config/contribution';

/**
 * "SUPPORT THIS WORK" - the Section 5 voluntary-contribution block that sits on every blog post,
 * after the Tags row and before the Share controls (see src/pages/post/[slug].tsx for the exact
 * DOM position and why the share reveal sentinel stays where it is).
 *
 * WHAT THIS COMPONENT IS, AND WHAT IT IS NOT
 * ------------------------------------------
 * It is the UI + the client seam. It renders the three common preset amounts and, on a user
 * action, ASKS a backend contribution-initiation endpoint to start a payment. It is NOT the payment. The authoritative half - the BLOG_CONTRIBUTION purpose, the
 * server-decided amount, the Razorpay gateway order, verification, the webhook, idempotency and the
 * stored records - is FEAT-004 and lives in the Python backend. That endpoint is gated OFF by
 * default (CHECKOUT_INITIATION_ENABLED, see amplify/functions/ecommerce/checkout/handler.py), so
 * for now the call cannot complete a real charge, and this component is built to say so honestly.
 *
 * HONEST DEGRADATION IS THE WHOLE POINT
 * -------------------------------------
 * The brief is explicit that we must never treat a query string, a browser success callback,
 * frontend state, or a bare Razorpay signature as proof of payment. So:
 *   - The default, server-rendered state is the normal available-presets form. It does NOT fetch
 *     at render/prerender time (this is a static export; a fetch at build time would break it).
 *   - A call happens ONLY on a user click, in the browser.
 *   - PAYMENT_INITIATION_DISABLED (the gate's default), any non-ready/unknown response, a network
 *     failure, or an endpoint that does not exist yet all resolve to the SAME honest state:
 *     "Contributions are not available right now." No success is ever fabricated.
 *   - A CHECKOUT_OPTIONS_READY response does NOT itself mean "paid". It would carry the public
 *     keyId / gateway orderId / server amount for a Razorpay handoff that FEAT-004 wires; until
 *     then this component treats "ready" as "the backend is live" and leaves the actual Razorpay
 *     open + verify to FEAT-004. It never shows a receipt or a thank-you as if money moved.
 *
 * The request/response contract shape mirrors the website-checkout client contract documented in
 * handler.py: POST a small JSON body, read a `state` field, branch on PAYMENT_INITIATION_DISABLED /
 * CHECKOUT_OPTIONS_READY / CHECKOUT_REJECTED / CHECKOUT_AMBIGUOUS. FEAT-004 can bind to this seam.
 */

export interface BlogContributionProps {
  /** The blog post's authoritative id (PublicBlogPost.id), so a contribution is attributable. */
  postId: string;
  /** The post slug, carried alongside the id for human-readable attribution and reconciliation. */
  slug: string;
  /** Removes the component's own top rule when a parent surface already owns section rhythm. */
  embedded?: boolean;
}

/** The browser-visible outcome states. "idle" is the default, server-rendered state. */
type Phase = 'idle' | 'submitting' | 'unavailable' | 'ready';

/** The documented backend states this client understands. Anything else degrades to unavailable. */
type BackendState =
  | 'PAYMENT_INITIATION_DISABLED'
  | 'CHECKOUT_OPTIONS_READY'
  | 'CHECKOUT_REJECTED'
  | 'CHECKOUT_AMBIGUOUS';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
/**
 * The initiation endpoint FEAT-004 owns. Kept here as the one place the path is named so the
 * backend binding is a one-line change. The call is defensive about this not existing yet.
 */
const CONTRIBUTION_INITIATE_URL = `${API_BASE}/ecommerce/contribution`;


const HONEST_UNAVAILABLE = 'Contributions are not available right now.';

const BlogContribution: React.FC<BlogContributionProps> = ( { postId, slug, embedded = false } ) => {
  const [ choice, setChoice ] = useState<number>( CONTRIBUTION_PRESETS_PAISE[ 0 ] );
  const [ phase, setPhase ] = useState<Phase>( 'idle' );
  const [ message, setMessage ] = useState( '' );


  const onSubmit = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const paise = choice;

    setPhase( 'submitting' );
    setMessage( '' );

    try {
      const response = await fetch( CONTRIBUTION_INITIATE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify( {
          purpose: CONTRIBUTION_PURPOSE,
          postId,
          slug,
          // The browser's REQUESTED amount, in paise. The server re-decides authoritatively.
          amountPaise: paise,
          currency: CONTRIBUTION_CURRENCY,
        } ),
      } );

      // A missing endpoint (404) or any non-OK status is honestly unavailable, never a failure
      // the reader has to read as their fault.
      if ( !response.ok ) {
        setPhase( 'unavailable' );
        setMessage( HONEST_UNAVAILABLE );
        return;
      }

      const body = await response.json().catch( () => ( {} as Record<string, unknown> ) );
      const state = String( ( body as { state?: string } ).state || '' ) as BackendState | '';

      if ( state === 'CHECKOUT_OPTIONS_READY' ) {
        // The backend is live and has issued a server-side gateway order. The actual Razorpay
        // open + authoritative verify is FEAT-004's job; we DO NOT fabricate a paid/thank-you
        // state here, because a browser-side "ready" is not proof of payment.
        setPhase( 'ready' );
        setMessage( 'Opening a secure payment\u2026' );
        return;
      }

      // PAYMENT_INITIATION_DISABLED (the default gate), CHECKOUT_REJECTED, CHECKOUT_AMBIGUOUS and
      // any unknown/absent state all land on the same honest, non-error unavailable message.
      setPhase( 'unavailable' );
      setMessage( HONEST_UNAVAILABLE );
    } catch {
      // Network absent, offline, DNS, CORS - all transient in shape and none of them a charge.
      setPhase( 'unavailable' );
      setMessage( HONEST_UNAVAILABLE );
    }
  };


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
            { CONTRIBUTION_PRESETS_PAISE.map( paise => (
              <label className="bc-choice" key={ paise }>
                <input
                  type="radio"
                  name="bc-amount"
                  className="bc-radio"
                  value={ String( paise ) }
                  checked={ choice === paise }
                  onChange={ () => { setChoice( paise ); setPhase( 'idle' ); setMessage( '' ); } }
                />
                <span className="bc-choice-face">&#8377;{ paiseToRupees( paise ) }</span>
              </label>
            ) ) }
          </div>
        </fieldset>


        <div className="bc-submit-wrap">
          <PillButton
            as="button"
            type="submit"
            action={ phase === 'submitting' ? 'One moment\u2026' : 'Contribute' }
            disabled={ phase === 'submitting' }
            busy={ phase === 'submitting' }
          />
        </div>

        {/* One live region for every outcome. role=status so a screen reader hears the honest
            unavailable/invalid message; it is never a success affordance. */}
        { message && (
          <p
            className={ `bc-status${ phase === 'ready' ? ' is-ready' : '' }` }
            role="status"
            data-phase={ phase }
          >
            { message }
          </p>
        ) }
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
        .bc-choice-face{
          display:inline-flex;align-items:center;justify-content:center;min-width:64px;
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
        /* The action itself is the shared public PillButton. This wrapper owns only placement,
           so Contribute cannot drift from Sign in / Checkout / Subscribe in shape or palette. */
        .bc-submit-wrap{margin-top:20px;display:flex;align-items:center}
        /* The status line is deliberately plain, not a success banner. The ready variant is
           informational only and never a receipt. */
        .bc-status{font-size:15px;line-height:1.5;color:rgba(0,0,0,.7);margin:16px 0 0}
        .bc-status.is-ready{color:#1a3a2a}
        @media(prefers-reduced-motion:reduce){
          .bc-choice-face{transition:none}
          .bc-radio:hover + .bc-choice-face{transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default BlogContribution;
