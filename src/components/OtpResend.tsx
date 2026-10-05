import React, { useEffect, useState } from 'react';

/**
 * ASK FOR ANOTHER CODE. One control, so every OTP surface offers the same affordance with the
 * same words and the same cooldown.
 *
 * WHY THIS EXISTS. The Phase 4 audit measured the four OTP surfaces and found three different
 * answers to the same question:
 *
 *   /account/sign-in/   "Send OTP on WhatsApp"            NO resend at all
 *   /get/               "Send OTP on WhatsApp"            NO resend at all
 *   BlogSubscribe       "Send OTP on WhatsApp"            resend, no cooldown, lime fill
 *   CheckoutProfile     "Send verification code by email" resend, 60s cooldown, plain button
 *
 * On the two sign-in surfaces a shopper whose code did not arrive had nothing to press. The
 * only way forward was to leave the page. That is the owner's "OTP + OTP-resend buttons
 * inconsistent or missing", and it is a functional gap rather than a styling one.
 *
 * THE WORDS ARE FIXED, ON OWNER INSTRUCTION. "Resend OTP on WhatsApp", always, because OTP is
 * a WhatsApp-only channel on this site. Email is used ONLY for the one-time email VERIFICATION
 * during profile creation or an email change, never as a sign-in channel - so the one caller
 * that resends an email code passes `channel="email"` and gets "Resend email code". There is
 * deliberately no free-text label prop: a caller cannot invent a third wording, and cannot
 * imply an email sign-in exists.
 *
 * IT IS THE DERIVED SECONDARY, NOT A SECOND PRIMARY. The owner's rule is one primary lime
 * surface per page, and on a code step the primary is "Confirm WhatsApp code". So this control
 * takes the home CTA's geometry - 52px, fully-rounded, 17px/600, 2px #1a3a2a edge, #1a3a2a
 * focus ring at 3px offset - and inverts the fill to white, with lime arriving only on hover.
 * That is exactly how .co-btn-quiet and .cs-btn-quiet already derive their quiet action, and it
 * is what makes BlogSubscribe stop rendering two equal lime fills side by side.
 *
 * THE COOLDOWN IS AN EPOCH MILLISECOND, NOT A COUNTER, and that is copied from CheckoutProfile
 * on purpose: a decrementing counter drifts when the tab is backgrounded and a timer is
 * throttled, an absolute deadline cannot. The interval clears both on unmount AND the moment it
 * expires, so a finished cooldown is not a re-render every second for the life of the page.
 *
 * THE COUNTDOWN IS NOT THE ONLY SIGNAL. The button is genuinely `disabled` while cooling, and
 * the remaining seconds are appended to the visible label rather than shown as a bare number
 * beside it - so the state is in the accessible name, announced when focus lands, instead of
 * depending on a reader noticing a separate digit. `aria-live="polite"` is deliberately NOT
 * used: a per-second live region is 30 announcements nobody asked for.
 */

/** 30s. The server's own resend window is 60s on the email path; this is the client's floor. */
export const OTP_RESEND_COOLDOWN_MS = 30_000;

export interface OtpResendProps {
  onResend: () => void;
  /** WhatsApp is the OTP channel. 'email' is the one-time verification path only. */
  channel?: 'whatsapp' | 'email';
  /** A request is in flight, or the surface is otherwise busy. */
  busy?: boolean;
  /**
   * Refused outright - the hourly send cap is spent. Distinct from a cooldown: there is no
   * number to count down to, so the control simply stops asking.
   */
  blocked?: boolean;
  /**
   * An epoch millisecond the caller owns, for when the SERVER dictates the wait (a 429 with
   * retryAfterSeconds). Left undefined, the component runs its own OTP_RESEND_COOLDOWN_MS from
   * each press, which is what the two sign-in surfaces need.
   */
  cooldownUntil?: number;
  /** Full-width in its container. */
  block?: boolean;
  /**
   * The site's two action heights, and they are not invented here: src/styles/button.css
   * publishes `.btn-md` at 44px/14px and `.btn-lg` at 52px/17px, and 52px is the home CTA.
   *
   * 'lg' is the default because this control usually sits under a 52px primary. 'md' exists for
   * BlogSubscribe, whose verify row is built on 44px controls and scrolls horizontally on a
   * phone - dropping a 52px button into a 44px row is the kind of one-off mismatch this sweep
   * is removing, so the shared control carries both rungs rather than the page overriding one.
   */
  size?: 'md' | 'lg';
}

const OtpResend: React.FC<OtpResendProps> = ( {
  onResend, channel = 'whatsapp', busy, blocked, cooldownUntil, block, size = 'lg',
} ) => {
  const [ ownUntil, setOwnUntil ] = useState( 0 );
  const [ tick, setTick ] = useState( () => Date.now() );

  // The caller's deadline wins when it has one, so a server 429 is never shortened by the
  // client's own floor.
  const until = Math.max( ownUntil, cooldownUntil || 0 );

  useEffect( () => {
    if ( until <= Date.now() ) return undefined;
    setTick( Date.now() );
    const id = setInterval( () => {
      const now = Date.now();
      setTick( now );
      if ( now >= until ) clearInterval( id );
    }, 1000 );
    return () => clearInterval( id );
  }, [ until ] );

  const seconds = Math.max( 0, Math.ceil( ( until - tick ) / 1000 ) );
  const cooling = seconds > 0;
  const base = channel === 'email' ? 'Resend email code' : 'Resend OTP on WhatsApp';
  /*
   * THE SECONDS ARE IN THE LABEL, so they are in the accessible name too and are announced when
   * focus lands, rather than living in a separate digit beside the button that a screen reader
   * user has no reason to visit.
   *
   * A PLAIN SPACE, NOT A MIDDOT, and that is deliberate rather than arbitrary. CheckoutProfile's
   * sibling send control already renders "Send email code 25s" and its tests pin that spelling;
   * introducing "Resend email code · 25s" beside it would put two separator conventions on one
   * card, which is the class of inconsistency this whole sweep exists to remove.
   */
  const label = cooling ? `${ base } ${ seconds }s` : base;

  return (
    <>
      <button
        className={ `otp-resend otp-resend-${ size }${ block ? ' otp-resend-block' : '' }` }
        type="button"
        disabled={ Boolean( busy ) || Boolean( blocked ) || cooling }
        onClick={ () => {
          if ( cooling ) return;
          setOwnUntil( Date.now() + OTP_RESEND_COOLDOWN_MS );
          onResend();
        } }
      >
        { label }
      </button>

      <style jsx>{`
        /* THE DERIVED SECONDARY. Same geometry as the home CTA (src/pages/index.tsx
           .home-close-cta) and the same geometry as PillButton, with the fill inverted: white
           at rest, lime on hover. One primary lime surface per page stays true on a code step,
           where the primary is the confirm button beside this one.
           NO BACKTICKS IN THIS BLOCK: it is a styled-jsx template literal, so a backtick ends
           the CSS string early. src/test/StyledJsxBackticks.test.tsx guards it. */
        .otp-resend{
          display:inline-flex;align-items:center;justify-content:center;
          box-sizing:border-box;
          border:2px solid #1a3a2a;border-radius:999px;background:#fff;
          color:#1a3a2a;font-family:inherit;font-weight:600;line-height:1.2;
          text-align:center;white-space:nowrap;cursor:pointer;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        /* The two rungs src/styles/button.css already publishes as .btn-lg and .btn-md. 52px is
           the home CTA height; 44px is the accessibility floor and never goes below it. */
        .otp-resend-lg{min-height:52px;padding:0 24px;font-size:17px}
        .otp-resend-md{min-height:44px;padding:0 16px;font-size:14px}
        .otp-resend-block{display:flex;width:100%}

        /* The house inversion, in the other direction: white to lime. The lift and the one
           allowed shadow match .home-close-cta exactly, including the .12 alpha. */
        .otp-resend:hover:not(:disabled){
          background:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .otp-resend:active:not(:disabled){transform:translateY(0);box-shadow:none}

        /* The site's indicator, outside the control, 3px at 3px offset - the same ring every
           other button on this site draws. */
        .otp-resend:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        /* Cooling or spent. Dimmed and inert, with the reason in the label rather than in the
           colour - there is nothing here a colour-blind reader loses. */
        .otp-resend:disabled{opacity:.55;cursor:default;transform:none;box-shadow:none}

        /* NARROW VIEWPORTS. The label is the longest string on the control and it must not be
           what forces a horizontal scroll at 280px, so the padding tightens and the large rung
           steps to 16px - still at the iOS zoom floor. The 52px and 44px heights are never
           traded away, and white-space:normal lets the label wrap inside the pill rather than
           push the page wider than the viewport. */
        @media(max-width:480px){
          .otp-resend-lg{padding:0 16px;font-size:16px}
        }
        @media(max-width:360px){
          .otp-resend{padding:0 12px;white-space:normal;line-height:1.25}
        }

        @media(prefers-reduced-motion:reduce){
          .otp-resend{transition:none}
          .otp-resend:hover:not(:disabled){transform:none;box-shadow:none}
        }
      `}</style>
    </>
  );
};

export default OtpResend;
