import React from 'react';

/**
 * THE TWO-SEGMENT PILL, the home-page phone-number treatment turned into a reusable control.
 *
 * WHAT THE OWNER ASKED FOR. "In our home page design and theme, the phone number button - make
 * this style for cart login or any other login." The reference is a fully-rounded pill split into
 * two butted segments: a dark-green LEFT segment carrying a static label in white, and a brighter
 * MINT RIGHT segment carrying the action in dark-green type. This component is that pill, built
 * once so every customer login CTA uses the same markup and the same tokens and cannot drift.
 *
 * IT IS A STYLE, NOT A NEW CONTROL. The pill renders either a real <button> or a real <a> - the
 * caller chooses with `as` - so submit semantics, disabled/busy state, click handling, keyboard
 * focus and link navigation are all the platform's, untouched. The two visible segments are
 * decoration layered on top of one actionable element.
 *
 * THE ACCESSIBLE NAME IS THE VISIBLE TEXT. WCAG 2.5.3 LABEL IN NAME, AND WHY THE OLD
 * `aria-label` HAD TO GO.
 *
 * This component used to carry an explicit `aria-label` equal to the ACTION text alone, with both
 * visible segments marked `aria-hidden`, so a pill reading "Sign in | Confirm code" announced only
 * "Confirm code". That is a direct failure of WCAG 2.5.3 Label in Name (Level A): the accessible
 * name must CONTAIN the visible label text. Hiding a control's own visible label from the
 * accessibility tree is the anti-pattern that creates the mismatch, not a fix for it.
 *
 * THE PEOPLE THIS BROKE ARE SPEECH-INPUT USERS. Someone driving the page by voice says "click Sign
 * in" at a button whose name is "Confirm code" and nothing happens. There is no visual symptom, so
 * no amount of styling fixes it, and the owner's two-tone design is not the problem.
 *
 * SO: neither segment is aria-hidden, and there is NO `aria-label`. The accessible name is the
 * platform's own concatenation of the visible text - "Sign in Confirm code", "Checkout Proceed",
 * "Collect Send code" - which contains the visible label text by construction and therefore
 * cannot drift out of compliance. Nothing changes visually; this is an accessibility-tree change
 * only.
 *
 * THERE IS DELIBERATELY NO `ariaLabel` PROP ANY MORE. It existed so the cart could show "Proceed"
 * while announcing "Proceed to checkout", and that override is exactly how 2.5.3 gets broken - the
 * name it set did not contain the visible text. Removing the prop rather than merely not using it
 * makes the guarantee STRUCTURAL: there is no longer any way to give this control a name that
 * disagrees with what is on screen. If a pill ever needs more context than its visible text, the
 * name must still CONTAIN that text - extend the visible action, or use `describedBy`, which adds
 * description without replacing the name.
 *
 * `src/test/PillButtonAccessibleName.test.tsx` asserts the property (name contains visible text)
 * across every call site's prop shape, rather than pinning today's five strings.
 *
 * ONE LIME SURFACE, NOT TWO TONES — CHANGED 2026-10-02 ON OWNER INSTRUCTION.
 * This was a two-segment pill: a dark #1a3a2a label half and a mint #5fe3b0 action half split by a
 * 2px rule. The owner called it "old multi colour out of date" and supplied the replacement
 * directly: a single lime pill (their reference image reads "Contribute"). The two-tone treatment
 * is retired here and was separately rejected as a model for the phone field.
 *
 * THE PALETTE IS THE SITE'S, AND THE CONTRAST IS MEASURED, NOT ASSUMED.
 *   - SURFACE #d1f470 with #1a3a2a text => 10.04:1, passes AAA. This is the home page's own lime:
 *     src/pages/index.tsx uses #d1f470 eight times and #5fe3b0 zero times, and a repo-wide grep
 *     for #5fe3b0 found it ONLY in this component and its test - an orphan colour present nowhere
 *     else on the site, which is what made this button look foreign on its own pages.
 *     Lime also beats the mint it replaced on contrast (10.04:1 vs 7.79:1), so nothing was traded
 *     away to get the brand right.
 *   - HOVER inverts to #ffffff, giving #1a3a2a text 12.48:1. The OLD hover deepened the mint to
 *     the site's base green #3da35a while keeping #1a3a2a text: 3.91:1, which FAILS the 4.5:1
 *     requirement. The old note excused it as "no small text relies on that shade" - incorrect,
 *     because this label is 17px bold and WCAG's large-text exemption starts at 18.66px bold.
 *     That defect is fixed by the inversion, which is also the house pattern (.ship-close-cta).
 *   - THE EDGE. #d1f470 against a white page is only 1.24:1, far under WCAG 1.4.11's 3:1 for a
 *     component boundary, so the lime cannot be the thing that separates the button from the page.
 *     The pill therefore carries a 2px #1a3a2a border (12.48:1 against white), which is what
 *     clears 1.4.11 - exactly how the home CTA (.home-close-cta) and PhoneField draw their edge.
 *
 * THE RADIUS IS SCOPED SO THE GLOBAL 13px CANNOT FLATTEN IT. src/styles/button.css puts a global
 * 13px radius on .btn controls; this component uses its own class names (never .btn) and sets
 * border-radius:999px on the pill with per-corner logical radii on the segments, so the full pill
 * shape survives regardless of what the global sheet says. The segments use start/end logical
 * radii so the rounded ends follow the reading direction and the pill mirrors cleanly in RTL -
 * the same technique PhoneField uses for its divided field.
 *
 * MOTION IS OPTIONAL AND REDUCED-MOTION-AWARE. The hover lift and the one allowed shadow match the
 * home CTA, and both are dropped under prefers-reduced-motion: reduce.
 *
 * STYLED-JSX SCOPING. This component styles its own lowercase tags (<span>, <button>, <a>) in its
 * own <style jsx> block; it does not rely on a consumer's styles reaching it, which they cannot.
 */

export interface PillButtonProps {
  /** Formerly the dark LEFT-segment's text, e.g. "Sign in". No longer rendered - see below. */
  /**
   * NO LONGER RENDERED, and kept only so the existing call sites keep compiling.
   *
   * This was the dark left segment's text ("Sign in", "Collect", "Pay"). The pill is now a single
   * lime surface showing the ACTION alone - which was already the control's accessible name, so
   * what is read aloud and what is on screen are now the same string instead of two.
   * It is deliberately NOT rendered as visually-hidden text: this repo has explicitly rejected
   * hidden text for naming elsewhere (see the note in PhoneField about the country select), and
   * the surrounding page already supplies the context the label used to carry - /account/sign-in
   * is headed "Sign in to check out", and /get is headed "Collect your files".
   * Optional so new call sites need not pass it. There is NO name-override prop to reach for
   * either: `ariaLabel` was removed upstream so a caller cannot reopen the 2.5.3 failure by
   * setting a name that disagrees with the screen. If the visible action does not read as the
   * whole action, change the ACTION TEXT - what is on screen is what is announced.
   */
  label?: string;
  /** The visible ACTION text, e.g. "Send code" - the pill's only label now that it is a single
   *  lime surface. By default this is also the control's accessible name, so it must read as the
   *  whole action on its own; there is no override prop, by design.
   *  THIS SATISFIES THE UPSTREAM WCAG 2.5.3 FIX (2b581d8b) BY CONSTRUCTION: that commit removed
   *  aria-hidden from the two segments so the accessible name would match the visible two-word
   *  text. With one segment there is one string, so visible text and accessible name are the same
   *  by definition and there is no longer a mismatch to fix. */
  action: string;
  /** Render a <button> (default) or an <a>. */
  as?: 'button' | 'a';
  /** For as="button": the native type. Defaults to 'button' so it never submits by accident. */
  type?: 'button' | 'submit';
  /** For as="a": the destination. */
  href?: string;
  onClick?: ( event: React.MouseEvent ) => void;
  /** Disabled/busy for buttons. A disabled pill is dimmed and non-interactive. */
  disabled?: boolean;
  /** True while an action is in flight; dims the pill and sets aria-busy. */
  busy?: boolean;
  /** Full-width in its container (the sign-in and cart forms want this). */
  block?: boolean;
  /** Extra describedby ids, passed straight through. */
  describedBy?: string;
}

const PillButton: React.FC<PillButtonProps> = ( {
  label, action, as = 'button', type = 'button', href,
  onClick, disabled, busy, block, describedBy,
} ) => {
  const className = `pill${ block ? ' pill-block' : '' }`;

  /*
   * THE TWO SEGMENTS ARE WRITTEN OUT TWICE, INLINE, AND THAT DUPLICATION IS DELIBERATE.
   *
   * They used to be hoisted into one `const inner = (<>...</>)` and referenced from both branches,
   * which is tidier to read and was SILENTLY BROKEN. styled-jsx's transform only stamps its
   * scoping hash class onto JSX elements that appear inside the same return tree as the
   * <style jsx> element below. JSX lifted into a variable never gets stamped, so the built markup
   * emitted `class="pill-label"` and `class="pill-action"` with NO hash while the rules compiled
   * to `.pill-label.jsx-<hash>{...}` - selectors that could never match. The outer <button> was
   * stamped correctly, which is why the pill had its shape, its 2px edge and its dark fill but
   * NEITHER segment had its own background or colour: it rendered as one dark slab with the label
   * and the action jammed together, "Sign inSend code", with white-on-dark text falling back to
   * near-black. Measured in the built export AND on the live site at /account/sign-in/ before this
   * fix.
   *
   * THIS REPO ALREADY KNEW THIS FAILURE MODE. RotatingHero's docblock records it costing "a full
   * debugging round on the mega menu, where a renderLink() helper left the rules behind and every
   * row fell through to a global". Same trap, same component family. Do not re-hoist these spans,
   * and do not extract them into a helper or a child component: either reintroduces the bug.
   *
   * NEITHER SEGMENT IS aria-hidden, AND THERE IS NO aria-label. Both carried `aria-hidden="true"`
   * and the control carried an `aria-label` of the action alone, which hid the pill's own visible
   * label from its accessible name - a WCAG 2.5.3 Label in Name failure. The name is now the
   * platform's concatenation of the visible text, so it contains the visible label by
   * construction. See the docblock. This changes nothing visually.
   */
  return (
    <>
      { as === 'a' ? (
        <a
          className={ className }
          href={ href }
          onClick={ onClick }
          aria-describedby={ describedBy }
        >
          <span className="pill-action">{ action }</span>
        </a>
      ) : (
        <button
          className={ className }
          type={ type }
          onClick={ onClick }
          disabled={ disabled }
          aria-busy={ busy ? 'true' : undefined }
          aria-describedby={ describedBy }
        >
          <span className="pill-action">{ action }</span>
        </button>
      ) }

      <style jsx>{`
        /* THE PILL — ONE LIME SURFACE, not two tones.
           
           REWRITTEN ON OWNER INSTRUCTION (2026-10-02): "i see still old multi colour out of date
           button". The control was a two-segment pill - a dark #1a3a2a label half and a mint
           #5fe3b0 action half divided by a 2px rule. The owner supplied the replacement reference
           directly (a single lime pill reading "Contribute") and rejected the two-tone treatment,
           both for buttons and, separately, as a model for the phone field.
           
           WHY LIME AND NOT MINT, measured rather than preferred: src/pages/index.tsx (the home
           page) uses #d1f470 eight times and #5fe3b0 zero times, and a repo-wide grep for #5fe3b0
           returned only this component and its test - an orphan colour that appeared nowhere else
           on the site. Contrast favours lime too: #d1f470 with #1a3a2a type computes 10.04:1
           against mint's 7.79:1. So there was no accessibility argument for keeping mint either.
           
           The 2px #1a3a2a edge stays (12.48:1 vs white, clears WCAG 1.4.11 for a control
           boundary), the full 999px radius stays so the global 13px in src/styles/button.css
           cannot flatten it, and 52px stays as the site's CTA height, matching PhoneField and
           .si-input.

           TWO NUMBERS WERE PULLED BACK TO THE REFERENCE IN THE PHASE 4 SWEEP, both measured
           against src/pages/index.tsx's .home-close-cta, which is the home page's only call to
           action and therefore the button standard:
             - the label was font-weight:700 where the reference is 600. Measured in the built
               export, .shopd-cta, .co-btn-primary, .cs-btn-primary and the /blog/ search
               button all render 600, so this control was the single outlier - on
               /account/sign-in/, /cart/, /get/, /orders/ and the contribute blocks, i.e. most
               of the places a customer meets a button.
             - the hover shadow was rgba(26,58,42,.18) where every other primary on the site,
               and the reference, use .12.
           Neither changes the silhouette; both are why the pages read as slightly different
           designs when you move between them. */
        /* color AND font-weight ARE ON THE CONTROL, not only on the label span, and that is a
           Phase 4 correction. The outer element declared neither, so it measured
           color:rgb(0,0,0) / font-weight:400 while .pill-action inside it painted #1a3a2a / 600.
           Nothing visible was wrong - the span holds all the text - but anything the control
           renders without going through that span (a glyph, a pseudo-element, a future icon)
           would arrive black at weight 400 on a lime fill. The reference .home-close-cta
           declares both on the control itself; this now matches it, and the span's identical
           declarations become a harmless restatement rather than the only source. */
        .pill{
          display:inline-flex;align-items:center;justify-content:center;isolation:isolate;
          min-height:52px;box-sizing:border-box;
          border:2px solid #1a3a2a;border-radius:999px;background:#d1f470;
          padding:0 28px;cursor:pointer;
          color:#1a3a2a;font-family:inherit;font-size:17px;font-weight:600;text-decoration:none;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .pill-block{display:flex;width:100%}

        /* THE ONE LABEL. The pill now shows the ACTION only - the text that already was the
           control's accessible name - so what is read aloud and what is on screen are the same
           string. The former label half ("Sign in", "Collect", "Pay") is no longer rendered;
           see the note on the prop for why it is still accepted.
           17px/700 #1a3a2a on #d1f470 = 10.04:1, comfortably past the 4.5:1 this size needs.
           NO BACKTICKS IN THIS BLOCK: it is a styled-jsx template literal, so a backtick here
           terminates the CSS string early. src/test/StyledJsxBackticks.test.tsx guards it. */
        .pill-action{
          display:inline-flex;align-items:center;justify-content:center;
          min-inline-size:0;
          color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
          text-align:center;
        }

        /* HOVER/PRESS: the house inversion - lime to white - plus the single allowed lift and
           shadow, exactly as .ship-close-cta and the home CTA do it.
           THE OLD HOVER WAS AN ACCESSIBILITY DEFECT AND IS GONE. It deepened the action half to
           the site's base green #3da35a while keeping #1a3a2a type, which computes 3.91:1 and
           FAILS the 4.5:1 requirement. The old comment excused it as "no small text relies on that
           shade" - wrong, because the label is 17px bold and WCAG's large-text exemption only
           begins at 18.66px bold (or 24px regular). White gives #1a3a2a type 12.48:1 instead. */
        .pill:hover:not([disabled]):not([aria-disabled='true']){
          background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .pill:active:not([disabled]):not([aria-disabled='true']){transform:translateY(0)}

        /* FOCUS. The site's #1a3a2a indicator at 3px, offset OUTSIDE the pill so the ring reads as
           one ring around the whole control (unlike PhoneField, which has two focusable segments
           and insets per segment; this pill is ONE control, so one outer ring is correct). */
        .pill:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        /* DISABLED/BUSY: dim the whole pill, drop the pointer. Covers both the native button
           :disabled and the belt-and-braces attribute. */
        .pill:disabled,.pill[aria-disabled='true']{opacity:.6;cursor:default}
        .pill[aria-busy='true']{cursor:progress}

        /* NARROW VIEWPORTS. Tighten padding rather than shrink the 52px target; the action segment
           absorbs the remaining width so the label does not overflow at 320px. */
        @media(max-width:360px){
          .pill{padding:0 18px}
          .pill-action{font-size:16px}
        }

        /* REDUCED MOTION: no lift, no shadow transition. */
        @media(prefers-reduced-motion:reduce){
          .pill{transition:none}
          .pill:hover:not([disabled]):not([aria-disabled='true']){transform:none;box-shadow:none}
        }
      `}</style>
    </>
  );
};

export default PillButton;
