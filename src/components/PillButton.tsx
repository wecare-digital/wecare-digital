import React from 'react';

/** Legacy component name retained for callers; uses the Auth action style.
 * Native button/link semantics and visible accessible names remain unchanged. */
interface PillButtonProps {
  /** Formerly the dark LEFT-segment's text, e.g. "Sign in". No longer rendered - see below. */
  /**
   * NO LONGER RENDERED, and kept only so the existing call sites keep compiling.
   *
   * This was the dark left segment's text ("Sign in", "Collect", "Pay"). The pill is now a single
   * lime surface showing the ACTION alone - which was already the control's accessible name, so
   * what is read aloud and what is on screen are now the same string instead of two.
   * It is deliberately NOT rendered as visually-hidden text: this repo has explicitly rejected
   * hidden text for naming elsewhere (see the note in PhoneField about the country select), and
   * the surrounding page already supplies the context the label used to carry; customer sign-in
   * now lives only at the backend-routed /auth endpoint, while /get is headed "Collect your files".
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
  const className = `pill public-auth-action${ block ? ' pill-block' : '' }`;

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
   * near-black. Measured in the retired static customer sign-in export before this fix.
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
        .pill-block{display:flex;width:100%}
        .pill-action{min-inline-size:0;max-inline-size:100%;overflow-wrap:anywhere}
        .pill[aria-busy='true']{cursor:progress}
      `}</style>
    </>
  );
};

export default PillButton;
