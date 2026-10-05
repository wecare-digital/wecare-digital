import React, { useEffect, useState } from 'react';

/**
 * The top section every public page must carry, for pages whose heading is a fixed statement
 * rather than a rotating one.
 *
 * WHY THIS EXISTS BESIDE RotatingHero. The skill's §6 asks every public page for the same top
 * band: one visible h1 inside main, above the fold, saying what the page is about, with no CTA and
 * no price in it. RotatingHero delivers that and is the right component for a marketing page - but
 * it carries two things a transactional page should not have. It rotates a word every 2400ms for
 * as long as the page is open, which is content moving automatically for well over five seconds
 * with no pause mechanism (WCAG 2.2.2), and it needs four cycle words per page held within a few
 * characters of each other, which on /cart/ or /checkout/status/ would be invented marketing copy
 * on a screen a customer is reading to find out whether their money moved.
 *
 * So this is the same band with the rotation removed. Every number in the stylesheet below is
 * .rh-shell's and .rh-layout's, value for value, because a page that does not use RotatingHero
 * must still agree with the fifteen that do: the 108px/96px two-height header clearance, the
 * 1300px measure, the 24px/16px gutter, the 80px/96px and 48px/64px band padding, the
 * clamp(36px,4.3vw,60px)/600 hero rung with its tracking in em, and the 20px/400/1.4 body rung at
 * rgba(0,0,0,.898). Tracking is em and not px on purpose: against a fluid clamp a fixed px value
 * made optical tightness swing 2.75x across the breakpoints.
 *
 * SELF-STYLING, AND THAT IS NOT OPTIONAL. styled-jsx attaches its scoping class only to lowercase
 * DOM tags in the file it compiles, so a consumer's <style jsx> cannot reach this markup. A
 * consumer therefore owns nothing but the props - and its own children, which it styles in its own
 * block. RotatingHero, BrandLockup and BrandBadge are all arranged the same way.
 *
 * THE FONT STACK IS DECLARED, NOT INHERITED, and the declaration stays - but the reason given
 * here was wrong and is corrected rather than deleted, because the wrong reason is the kind that
 * gets acted on. It read: "the public pages render in Inter only because @aws-amplify/ui-react's
 * stylesheet happens to set a family on body that starts with Inter; --font-sans in Pages.css has
 * no Inter in it." Both halves are false. `Layout.css:116` sets body's family to
 * 'Inter', ui-sans-serif, system-ui, … - which is the value a browser actually computes on these
 * pages, measured - and `Pages.css:60`'s --font-sans begins with 'Inter' too. The Amplify
 * stylesheet is no longer imported globally at all (see src/styles/amplify-base.css for what it
 * was really contributing). Declaring the stack is still right: a band that inherited would follow
 * whatever body happens to say, and this component is used on pages that set their own shell font.
 *
 * THE ENTRANCE IS OPT-IN. The CSS ships the readable, settled state - opacity 1, no transform - and
 * JavaScript adds .is-armed to put the start state back, then .show to play it. No JavaScript, a
 * failed bundle or a reduced-motion preference therefore all render a finished heading rather than
 * an invisible one. This is the inverse of the pattern that shipped a blank hero on twelve pages;
 * see the long note in RotatingHero.tsx.
 *
 * THE PHASE IS IN className, NOT classList. RotatingHero records why: React rewrites className on
 * every render and silently drops a class added imperatively. This component does not re-render on
 * a timer the way that one does, so classList would work here by luck - which is the argument for
 * doing it the same way as the component next to it rather than the argument against.
 *
 * ONLY THE HEADING AND THE SUB-LINE ARE ARMED. The children are not, and that is deliberate:
 * opacity:0 does not remove an element from the tab order, so arming a band that contains a form
 * or a button would leave invisible focusable controls for the length of the reveal.
 */

interface PageTopBandProps {
  /** The page's one h1. Says what the page is, not what to do on it. */
  heading: string;
  /** The single body line under it. Optional. */
  sub?: React.ReactNode;
  /** Accessible name for the main landmark. */
  ariaLabel: string;
  /** The page itself, below the band and inside the same 1300px measure. */
  children?: React.ReactNode;
}

const PageTopBand: React.FC<PageTopBandProps> = ( { heading, sub, ariaLabel, children } ) => {
  const [ phase, setPhase ] = useState<'final' | 'armed' | 'shown'>( 'final' );

  useEffect( () => {
    let cancelled = false;
    let reveal = 0;
    // Scheduled in a timeout rather than set in the effect body: that is the
    // react-hooks/set-state-in-effect case, and matchMedia is browser-only so it must not be
    // reached during the static export.
    const start = window.setTimeout( () => {
      if ( cancelled ) return;
      // typeof guard as well as the call - jsdom does not implement matchMedia and throws rather
      // than returning undefined. A shared component must not depend on the test setup stubbing it.
      const reduce = typeof window.matchMedia === 'function'
        && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
      // Stay at 'final': the CSS default is the settled band, so there is nothing to do.
      if ( reduce ) return;
      setPhase( 'armed' );
      reveal = window.setTimeout( () => { if ( !cancelled ) setPhase( 'shown' ); }, 60 );
    }, 0 );
    return () => {
      cancelled = true;
      window.clearTimeout( start );
      window.clearTimeout( reveal );
    };
  }, [] );

  return (
    <main className="ptb-shell" aria-label={ ariaLabel }>
      <div className={ [
        'ptb-layout',
        phase === 'armed' || phase === 'shown' ? 'is-armed' : '',
        phase === 'shown' ? 'show' : '',
      ].filter( Boolean ).join( ' ' ) }>
        <div className="ptb-top">
          <h1 className="ptb-h1">{ heading }</h1>
          { sub && <p className="ptb-sub">{ sub }</p> }
        </div>

        { children }
      </div>

      <style jsx>{`
        /* dvh declared after vh, which .rh-shell does not do and should. 100vh is the viewport
           with the browser chrome HIDDEN, so anything sized to it is taller than what a phone
           visitor can actually see; vh stays first as the fallback for engines without dvh. */
        .ptb-shell{
          min-height:calc(100vh - 69px);
          min-height:calc(100dvh - 69px);
          padding-top:108px;
          box-sizing:border-box;
          background:#fff;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;
        }
        .ptb-layout{
          width:100%;max-width:1300px;margin:0 auto;
          padding:80px 24px 96px;box-sizing:border-box;
          display:flex;flex-direction:column;gap:96px;
        }
        /* align-items:flex-start, or the flex default stretches the heading box to the full
           1300px measure and text-wrap:balance below has nothing to balance against. */
        .ptb-top{display:flex;flex-direction:column;align-items:flex-start}

        /* The hero rung, verbatim from .rh-head: 600 weight, which is LIGHTER than the 700 of the
           section level. That inversion is the site's and is deliberate - the same guard sits on
           .rh-head, .vl-head and .hero-left h1. Do not "correct" it. */
        .ptb-h1{
          font-size:clamp(36px,4.3vw,60px);font-weight:600;line-height:1.04;
          letter-spacing:-0.04em;color:rgba(0,0,0,.95);margin:0;max-width:900px;
          text-wrap:balance;
        }
        /* The single body rung the contract allows: 20px/400/1.4/-.125px at rgba(0,0,0,.898).
           560px rather than the heading's 900px - at 20px a 900px measure runs to ~110 characters
           a line, well past the 45-75 the rest of the site holds to. */
        .ptb-sub{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:24px 0 0;max-width:560px;text-wrap:balance;
        }

        /* THE SETTLED STATE IS THE DEFAULT. These two declarations are what a visitor sees with
           no JavaScript, a blocked bundle or reduced motion. */
        .ptb-h1,.ptb-sub{
          opacity:1;transform:translateY(0);
          transition:opacity .52s cubic-bezier(.16,1,.3,1),transform .52s cubic-bezier(.16,1,.3,1);
        }
        /* .is-armed puts the START state back - the same easing and the same 0.52s the pill's
           width glide and tint use on the home band, so the family moves as one. */
        .ptb-layout.is-armed .ptb-h1,.ptb-layout.is-armed .ptb-sub{opacity:0;transform:translateY(14px)}
        .ptb-layout.is-armed.show .ptb-h1,.ptb-layout.is-armed.show .ptb-sub{opacity:1;transform:translateY(0)}
        /* The delay is on the REVEAL only. On the base rule it would also delay the arming, which
           would make the start state visibly land after the settled one. */
        .ptb-layout.is-armed.show .ptb-sub{transition-delay:.12s}

        @media(max-width:767px){
          .ptb-shell{
            min-height:calc(100vh - 85px);
            min-height:calc(100dvh - 85px);
            padding-top:96px;
          }
          .ptb-layout{padding:48px 16px 64px;gap:64px}
          .ptb-h1{line-height:1.1}
        }

        /* NO 400px/340px FONT STEPS, and the absence is measured rather than assumed.
           RotatingHero carries them because its headline sits inside an animated pill whose
           ~0.52em of padding pushed "amend a request" 11px past a 320px measure. There is no pill
           here and no fixed phrase: the longest word any consumer passes wraps freely. Asserted at
           280px and 320px by tools/browser/devicecheck.js, which carries all five of these
           routes. */

        @media(prefers-reduced-motion:reduce){
          /* Scoped to .is-armed so these WIN rather than winning by accident: unscoped they would
             be (0,1,1) against the armed rule's (0,2,1). The settled state is the CSS default
             anyway, so all this has to cover is the preference changing after the class is on the
             node - the one case the JS check cannot. */
          .ptb-layout.is-armed .ptb-h1,.ptb-layout.is-armed .ptb-sub{opacity:1;transform:translateY(0)}
          .ptb-h1,.ptb-sub{transition:none}
        }
      `}</style>
    </main>
  );
};

export default PageTopBand;
